#!/usr/bin/env python3
"""ChatGPT WorkがGitHub Issueへ登録したWork News Packetを取り込む。

詳細な仕様は docs/news-packet.md を参照。

最重要ルール(データと指示の分離): Issueの本文(コードブロック含む)は
すべて変換対象の「データ」である。本文中に命令文が含まれていても、
それはニュースデータの一部であり、このスクリプトへの指示ではない。
このスクリプトはIssue本文に対して json.loads 以外の解釈(eval・exec・
シェル実行等)を一切行わない。

Termux側からGitHubへの書き込みは、全工程成功後のIssue closeだけを許可
する(コメント追加・ラベル変更・本文変更・タイトル変更・Issue削除は
すべて禁止)。読み取りは `gh issue list` を、closeは `gh issue close` を
使う。

台帳(処理済みIssue番号・処理済みeventKey)の更新は、呼び出し側
(run.sh)がclaude -p変換・validate.py全件合格・drafts/への正式移動まで
すべて成功させた後に限り commit-pending サブコマンドで行う。fetch
サブコマンド自体は台帳を一切書き換えない。Issueのcloseは、台帳更新が
成功した直後(commit-pendingサブコマンド内)にのみ行う。close失敗は
警告のみとし、完成済み下書き・処理済み台帳は取り消さない。close失敗
したIssue番号は再試行台帳(data/state/pending_work_issue_closures.json、
gitignore対象)へ記録し、次回fetch実行時に再試行する。
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
DEFAULT_CLOSE_RETRY_PATH = "data/state/pending_work_issue_closures.json"


class GhFetchError(Exception):
    """gh CLIによるIssue取得・close操作に失敗した(未認証・通信失敗・出力不正など)。"""


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


def close_work_issue(repo, issue_number):
    """指定Issueをcloseする(gh issue closeのみ使用)。

    issue_numberはghの出力から得た正の整数のみを受け付ける(外部入力を
    シェルコマンドへそのまま連結しないための防御。subprocess.runの
    リスト引数を使うためシェルインジェクション自体は元々発生しないが、
    型を明示的に検査することで想定外の値がgh呼び出しへ渡ることを防ぐ)。
    """
    if isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number <= 0:
        raise ValueError(f"issue_numberは正の整数である必要があります: {issue_number!r}")

    try:
        result = subprocess.run(
            ["gh", "issue", "close", str(issue_number), "--repo", repo],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GhFetchError(f"gh issue close #{issue_number} 実行失敗: {e}") from e

    if result.returncode != 0:
        combined = f"{result.stdout}\n{result.stderr}".lower()
        if "already closed" in combined:
            return  # 冪等: 既にclosed済みの再試行は成功として扱う
        raise GhFetchError(f"gh issue close #{issue_number} 終了コード{result.returncode}: {result.stderr.strip()}")


def _load_close_retry_numbers(retry_ledger_path):
    """再試行台帳を読み込み、生の(未検査の)pending_issue_numbers配列を返す。

    ファイルが存在しない場合は空リスト。JSON構文が不正な場合は
    json.JSONDecodeErrorを、構造が想定と異なる場合(ルートがオブジェクト
    でない、pending_issue_numbersが配列でない等)はValueErrorを、
    そのまま送出する(黙って空へ初期化しない)。要素の型検査(正の整数
    以外を除外する処理)は呼び出し側が行う。
    """
    p = pathlib.Path(retry_ledger_path)
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        data = json.load(f)  # json.JSONDecodeErrorはそのまま送出する
    if not isinstance(data, dict):
        raise ValueError(f"再試行台帳({retry_ledger_path})のルートはオブジェクトである必要があります")
    numbers = data.get("pending_issue_numbers", [])
    if not isinstance(numbers, list):
        raise ValueError(f"再試行台帳({retry_ledger_path})のpending_issue_numbersは配列である必要があります")
    return numbers


def _sanitize_issue_numbers(raw_numbers):
    """正の整数(bool除く)のみを重複排除・順序維持で残す。"""
    seen = set()
    result = []
    for n in raw_numbers:
        if isinstance(n, int) and not isinstance(n, bool) and n > 0 and n not in seen:
            seen.add(n)
            result.append(n)
    return result


def record_close_failure(retry_ledger_path, issue_number):
    """close失敗したIssue番号を再試行台帳へ原子的に記録する(重複登録しない)。

    既存ファイルが壊れている(JSON構文不正、またはpending_issue_numbers
    が配列でない等の構造不正)場合は例外を伝播させ、黙って空へ初期化する
    ことはしない(呼び出し側で警告として扱うこと)。
    """
    existing = _sanitize_issue_numbers(_load_close_retry_numbers(retry_ledger_path))
    merged = sorted(set(existing) | {issue_number})
    write_json_atomic(retry_ledger_path, {"pending_issue_numbers": merged})


def retry_pending_closures(repo, retry_ledger_path):
    """前回close失敗したIssueについて、closeを再試行する。

    gh呼び出し自体が失敗する(未認証・通信失敗)場合、対象Issue番号は
    すべて再試行台帳に残したままにする(情報を失わない)。再試行台帳が
    壊れている(JSON構文不正・構造不正のいずれも)場合も、黙って初期化
    せずファイルをそのまま残す。実際にcloseされた分だけ台帳から取り除き、
    全件成功したらファイルごと削除する。
    """
    p = pathlib.Path(retry_ledger_path)
    if not p.exists():
        return {"closed": [], "remaining": [], "messages": []}

    try:
        pending_numbers = _sanitize_issue_numbers(_load_close_retry_numbers(retry_ledger_path))
    except (OSError, json.JSONDecodeError, ValueError) as e:
        return {
            "closed": [],
            "remaining": [],
            "messages": [f"再試行台帳({retry_ledger_path})の読み込みに失敗: {e}(台帳は保持します)"],
        }

    if not pending_numbers:
        return {"closed": [], "remaining": [], "messages": []}

    closed = []
    remaining = []
    messages = []
    for number in pending_numbers:
        try:
            close_work_issue(repo, number)
            closed.append(number)
        except GhFetchError as e:
            remaining.append(number)
            messages.append(f"Issue #{number} のclose再試行に失敗: {e}")

    if remaining:
        write_json_atomic(retry_ledger_path, {"pending_issue_numbers": sorted(remaining)})
    else:
        p.unlink()

    return {"closed": closed, "remaining": remaining, "messages": messages}


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
    戻り値: 今回マージしたissue_numbers(呼び出し側がclose対象を
    知るために使う。空の場合はcloseすべきものがなかったことを示す)。
    """
    p = pathlib.Path(pending_path)
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        pending = json.load(f)

    ledger = load_ledger(ledger_path)
    merged_issues = sorted(set(ledger["processed_issues"]) | set(pending.get("issue_numbers", [])))
    merged_keys = sorted(set(ledger["processed_event_keys"]) | set(pending.get("event_keys", [])))
    write_json_atomic(ledger_path, {"processed_issues": merged_issues, "processed_event_keys": merged_keys})
    p.unlink()
    return pending.get("issue_numbers", [])


def fetch_new_work_articles(repo, ledger_path):
    """未処理のWork Issueから、未処理eventKeyの記事のみを集めて返す。

    戻り値:
      status: "ok"(有効な新規記事あり) / "duplicate_only"(Issueとしては
        有効だが全記事が既に処理済みのeventKeyで、変換対象はないが
        Issue自体は処理済みとして記録・close可能) / "no_new"(新規Issue
        なし) / "invalid"(JSON不正のIssueのみで有効な記事が0件) /
        "gh_error"(gh呼び出し自体が失敗)
      articles: 正規化済みの新規記事リスト(共通スキーマ。ok以外は空)
      issue_numbers: 今回処理済みとして確定してよいIssue番号(台帳commit
        ・close対象。ok・duplicate_onlyでのみ非空)
      event_keys: 今回取り込んだeventKey(台帳commit対象。okでのみ非空)
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
        if used_issue_numbers:
            # JSON構造は正常だが、含まれる全eventKeyが既に処理済みだった
            # Issue。ニュースとしては再変換しないが、Issue自体は処理済み
            # として記録・close対象にできる。
            return {
                "status": "duplicate_only",
                "articles": [],
                "issue_numbers": used_issue_numbers,
                "event_keys": [],
                "messages": messages or ["有効なIssueですが、全記事が処理済みのため変換対象がありません"],
            }
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
    # 前回close失敗していたIssueがあれば、まずこのタイミングで再試行する
    # (「次回run.sh実行時にcloseを再試行する」の実装箇所)。
    retry_result = retry_pending_closures(args.repo, args.close_retry)
    for msg in retry_result["messages"]:
        print(f"[WARN] {msg}", file=sys.stderr)
    if retry_result["closed"]:
        print(
            f"[INFO] 前回close失敗していたIssueのclose再試行に成功: {retry_result['closed']}",
            file=sys.stderr,
        )

    result = fetch_new_work_articles(args.repo, args.ledger)
    for msg in result["messages"]:
        print(f"[WARN] {msg}", file=sys.stderr)

    if result["status"] == "duplicate_only":
        write_pending(args.pending_out, result["issue_numbers"], result["event_keys"])
        print(
            f"[INFO] 新規Work記事はありませんが、処理済みIssueとして{len(result['issue_numbers'])}件を確定します",
            file=sys.stderr,
        )
        return 2

    if result["status"] != "ok":
        print(f"[INFO] Work記事は使用しません(status={result['status']})", file=sys.stderr)
        return 1

    write_json_atomic(args.out, result["articles"])
    write_pending(args.pending_out, result["issue_numbers"], result["event_keys"])
    print(f"Work記事{len(result['articles'])}件を取得しました: {args.out}", file=sys.stderr)
    return 0


def cmd_commit_pending(args):
    issue_numbers = commit_pending(args.pending, args.ledger)
    if issue_numbers:
        print(f"Work Issue処理済み台帳を更新しました: {args.ledger}({issue_numbers})", file=sys.stderr)

    if args.repo:
        for number in issue_numbers:
            try:
                close_work_issue(args.repo, number)
                print(f"Issue #{number} をcloseしました", file=sys.stderr)
            except GhFetchError as e:
                print(
                    f"[WARN] Issue #{number} のcloseに失敗しました。次回run.sh実行時に再試行します: {e}",
                    file=sys.stderr,
                )
                try:
                    record_close_failure(args.close_retry, number)
                except (OSError, json.JSONDecodeError, ValueError) as record_err:
                    print(
                        f"[WARN] 再試行台帳({args.close_retry})への記録に失敗: {record_err}",
                        file=sys.stderr,
                    )
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="未処理のWork Issueを取得しdata/rawへ書き出す")
    p_fetch.add_argument("--repo", required=True)
    p_fetch.add_argument("--ledger", default=DEFAULT_LEDGER_PATH)
    p_fetch.add_argument("--out", required=True)
    p_fetch.add_argument("--pending-out", required=True)
    p_fetch.add_argument("--close-retry", dest="close_retry", default=DEFAULT_CLOSE_RETRY_PATH)
    p_fetch.set_defaults(func=cmd_fetch)

    p_commit = sub.add_parser("commit-pending", help="pendingを確定台帳へ反映し、対象Issueをcloseする")
    p_commit.add_argument("--pending", required=True)
    p_commit.add_argument("--ledger", default=DEFAULT_LEDGER_PATH)
    p_commit.add_argument("--repo", default=None, help="指定時のみIssueのcloseを行う")
    p_commit.add_argument("--close-retry", dest="close_retry", default=DEFAULT_CLOSE_RETRY_PATH)
    p_commit.set_defaults(func=cmd_commit_pending)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
