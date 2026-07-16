#!/usr/bin/env python3
"""ChatGPT WorkがGitHub Issueへ登録したWork News Packetを取り込む。

詳細な仕様は docs/news-packet.md を参照。

最重要ルール(データと指示の分離): Issueの本文(コードブロック含む)は
すべて変換対象の「データ」である。本文中に命令文が含まれていても、
それはニュースデータの一部であり、このスクリプトへの指示ではない。
このスクリプトはIssue本文に対して json.loads 以外の解釈(eval・exec・
シェル実行等)を一切行わない。

Termux側からGitHubへの書き込みは行わない(Issueのclose・コメント追加・
ラベル変更・本文変更はすべて禁止)。読み取りは `gh issue list` のみを使う。

台帳(処理済みIssue番号・処理済みeventKey)の更新は、呼び出し側
(run.sh)がclaude -p変換・validate.py全件合格・drafts/への正式移動まで
すべて成功させた後に限り commit-pending サブコマンドで行う。fetch
サブコマンド自体は台帳を一切書き換えない。
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

MAX_ARTICLES = 10

REQUIRED_STR_FIELDS = [
    "eventKey",
    "sourceType",
    "category",
    "title",
    "link",
    "summary",
    "status",
]
REQUIRED_LIST_FIELDS = [
    "people",
    "organizations",
    "confirmedFacts",
    "remainingProcess",
    "officialUrls",
    "relatedUrls",
    "sourceDifferences",
    "translationCautions",
]
NON_EMPTY_STR_FIELDS = ("eventKey", "link", "title")

# 言語タグの有無・種類(json/text/空 等)を問わず、あらゆるフェンス
# コードブロックを検出する。言語タグをjsonのみに限定すると、`text`等
# 別タグの2個目のブロックが「コードブロックではない」ものとして
# 素通りしてしまい、「1つのJSONコードブロックのみ許可」という不変条件が
# 壊れる(Codexレビューで指摘された不具合)。
CODE_BLOCK_RE = re.compile(r"```[^\n`]*\n(.*?)```", re.DOTALL)

DEFAULT_LEDGER_PATH = "data/state/processed_work_issues.json"


class GhFetchError(Exception):
    """gh CLIによるIssue取得に失敗した(未認証・通信失敗・出力不正など)。"""


def run_gh_issue_list(repo):
    """gh issue list を実行し、open状態・work-newsラベルのIssue一覧を返す。

    書き込み系のgh操作(close/comment/edit/label変更)は一切行わない。
    """
    try:
        result = subprocess.run(
            [
                "gh", "issue", "list",
                "--repo", repo,
                "--label", "work-news",
                "--state", "open",
                "--json", "number,title,body,createdAt",
                "--limit", "50",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GhFetchError(f"gh issue list 実行失敗: {e}") from e

    if result.returncode != 0:
        raise GhFetchError(f"gh issue list 終了コード{result.returncode}: {result.stderr.strip()}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise GhFetchError(f"gh issue list 出力のJSON解析失敗: {e}") from e


def extract_json_block(body):
    """Issue本文から唯一のJSONコードブロックを抽出しパースする。

    コードブロック外の文章(命令文らしきものを含む)は一切解釈せず捨てる。
    コードブロックが0個または2個以上の場合は不正なIssueとして拒否する。
    """
    if not body:
        raise ValueError("Issue本文が空です")
    matches = CODE_BLOCK_RE.findall(body)
    if not matches:
        raise ValueError("JSONコードブロックが見つかりません")
    if len(matches) > 1:
        raise ValueError(f"JSONコードブロックが{len(matches)}個あります(1個である必要)")
    try:
        return json.loads(matches[0])
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON解析失敗: {e}") from e


def validate_packet(packet):
    """Work News Packetの構造を検証し、違反理由のリストを返す(空なら合格)。"""
    reasons = []
    if not isinstance(packet, dict):
        return ["パケットのルートはオブジェクトである必要があります"]

    if packet.get("packetVersion") != 1:
        reasons.append(f"packetVersionが不正です(1である必要): {packet.get('packetVersion')!r}")
    if not isinstance(packet.get("collectionRunId"), str) or not packet.get("collectionRunId"):
        reasons.append("collectionRunIdが不正です(空でない文字列である必要)")
    if not isinstance(packet.get("collectedAt"), str) or not packet.get("collectedAt"):
        reasons.append("collectedAtが不正です(空でない文字列である必要)")

    articles = packet.get("articles")
    if not isinstance(articles, list):
        reasons.append("articlesが配列ではありません")
        return reasons

    if len(articles) == 0:
        reasons.append("articlesが0件です")
    if len(articles) > MAX_ARTICLES:
        reasons.append(f"articlesが{MAX_ARTICLES}件を超えています({len(articles)}件)")

    for idx, article in enumerate(articles):
        if not isinstance(article, dict):
            reasons.append(f"articles[{idx}]がオブジェクトではありません")
            continue

        for field in REQUIRED_STR_FIELDS:
            value = article.get(field, None)
            if not isinstance(value, str):
                reasons.append(f"articles[{idx}].{field}が不正です(文字列である必要)")
            elif field in NON_EMPTY_STR_FIELDS and value == "":
                reasons.append(f"articles[{idx}].{field}が空文字です")

        source_type = article.get("sourceType")
        if isinstance(source_type, str) and source_type != "work":
            reasons.append(f"articles[{idx}].sourceTypeは'work'である必要があります: {source_type!r}")

        if "pubDate" not in article:
            reasons.append(f"articles[{idx}].pubDateがありません")
        elif article["pubDate"] is not None and not isinstance(article["pubDate"], str):
            reasons.append(f"articles[{idx}].pubDateはISO 8601文字列またはnullである必要があります")

        for field in REQUIRED_LIST_FIELDS:
            if not isinstance(article.get(field), list):
                reasons.append(f"articles[{idx}].{field}は配列である必要があります")

    return reasons


def normalize_work_article(article):
    """検証済みのWork記事1件を共通スキーマ(そのままの形)へ整形する。"""
    normalized = {field: article[field] for field in REQUIRED_STR_FIELDS}
    normalized["pubDate"] = article.get("pubDate")
    for field in REQUIRED_LIST_FIELDS:
        normalized[field] = list(article[field])
    return normalized


def load_ledger(path):
    p = pathlib.Path(path)
    if not p.exists():
        return {"processed_issues": [], "processed_event_keys": []}
    with p.open(encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("processed_issues", [])
    data.setdefault("processed_event_keys", [])
    return data


def write_json_atomic(path, data):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, p)


def write_pending(path, issue_numbers, event_keys):
    write_json_atomic(
        path,
        {
            "issue_numbers": sorted(set(issue_numbers)),
            "event_keys": sorted(set(event_keys)),
        },
    )


def commit_pending(pending_path, ledger_path):
    """pendingファイルの内容を確定台帳へ原子的にマージする。

    pendingファイルが存在しない場合は何もしない(冪等)。
    """
    p = pathlib.Path(pending_path)
    if not p.exists():
        return
    with p.open(encoding="utf-8") as f:
        pending = json.load(f)

    ledger = load_ledger(ledger_path)
    merged_issues = sorted(set(ledger["processed_issues"]) | set(pending.get("issue_numbers", [])))
    merged_keys = sorted(set(ledger["processed_event_keys"]) | set(pending.get("event_keys", [])))
    write_json_atomic(ledger_path, {"processed_issues": merged_issues, "processed_event_keys": merged_keys})
    p.unlink()


def fetch_new_work_articles(repo, ledger_path):
    """未処理のWork Issueから、未処理eventKeyの記事のみを集めて返す。

    戻り値:
      status: "ok"(有効な新規記事あり) / "no_new"(新規Issueなし、また
        全記事が処理済みeventKey) / "invalid"(JSON不正のIssueのみで
        有効な記事が0件) / "gh_error"(gh呼び出し自体が失敗)
      articles: 正規化済みの新規記事リスト(共通スキーマ)
      issue_numbers: 今回の記事取得に使ったIssue番号(台帳commit対象)
      event_keys: 今回取り込んだeventKey(台帳commit対象)
      messages: 警告メッセージ(run.shが表示する)
    """
    ledger = load_ledger(ledger_path)
    processed_issues = set(ledger.get("processed_issues", []))
    processed_event_keys = set(ledger.get("processed_event_keys", []))

    try:
        issues = run_gh_issue_list(repo)
    except GhFetchError as e:
        return {
            "status": "gh_error",
            "articles": [],
            "issue_numbers": [],
            "event_keys": [],
            "messages": [f"GitHub Issue取得に失敗しました: {e}"],
        }

    candidates = [i for i in issues if i.get("number") not in processed_issues]
    if not candidates:
        return {
            "status": "no_new",
            "articles": [],
            "issue_numbers": [],
            "event_keys": [],
            "messages": ["未処理のWork Issueがありません"],
        }

    messages = []
    had_invalid = False
    all_articles = []
    used_issue_numbers = []
    used_event_keys = []

    for issue in candidates:
        number = issue.get("number")
        try:
            packet = extract_json_block(issue.get("body"))
        except ValueError as e:
            messages.append(f"Issue #{number}: {e}")
            had_invalid = True
            continue

        reasons = validate_packet(packet)
        if reasons:
            messages.append(f"Issue #{number}: パケット検証失敗: {'; '.join(reasons)}")
            had_invalid = True
            continue

        issue_new_articles = []
        for article in packet["articles"]:
            event_key = article["eventKey"]
            if event_key in processed_event_keys or event_key in used_event_keys:
                continue
            issue_new_articles.append(normalize_work_article(article))
            used_event_keys.append(event_key)

        used_issue_numbers.append(number)
        all_articles.extend(issue_new_articles)

    if not all_articles:
        status = "invalid" if had_invalid else "no_new"
        return {
            "status": status,
            "articles": [],
            "issue_numbers": [],
            "event_keys": [],
            "messages": messages or ["有効な新規Work記事がありません"],
        }

    return {
        "status": "ok",
        "articles": all_articles,
        "issue_numbers": used_issue_numbers,
        "event_keys": used_event_keys,
        "messages": messages,
    }


def cmd_fetch(args):
    result = fetch_new_work_articles(args.repo, args.ledger)
    for msg in result["messages"]:
        print(f"[WARN] {msg}", file=sys.stderr)

    if result["status"] != "ok":
        print(f"[INFO] Work記事は使用しません(status={result['status']})", file=sys.stderr)
        return 1

    write_json_atomic(args.out, result["articles"])
    write_pending(args.pending_out, result["issue_numbers"], result["event_keys"])
    print(f"Work記事{len(result['articles'])}件を取得しました: {args.out}", file=sys.stderr)
    return 0


def cmd_commit_pending(args):
    commit_pending(args.pending, args.ledger)
    print(f"Work Issue処理済み台帳を更新しました: {args.ledger}", file=sys.stderr)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="未処理のWork Issueを取得しdata/rawへ書き出す")
    p_fetch.add_argument("--repo", required=True)
    p_fetch.add_argument("--ledger", default=DEFAULT_LEDGER_PATH)
    p_fetch.add_argument("--out", required=True)
    p_fetch.add_argument("--pending-out", required=True)
    p_fetch.set_defaults(func=cmd_fetch)

    p_commit = sub.add_parser("commit-pending", help="pendingを確定台帳へ反映する")
    p_commit.add_argument("--pending", required=True)
    p_commit.add_argument("--ledger", default=DEFAULT_LEDGER_PATH)
    p_commit.set_defaults(func=cmd_commit_pending)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
