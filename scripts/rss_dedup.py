#!/usr/bin/env python3
"""RSS記事のURL完全一致による日またぎ重複除外を管理する。

data/state/recent_rss_links.json に、直近RETENTION_DAYS日分に下書き化
されたRSS記事のlinkと日付を記録する。scripts/collect.py はこの台帳と
URLが完全一致するlinkだけを実行前に除外してからclaude -p変換へ渡す
(タイトル一致・意味的類似だけでは除外しない)。

台帳の確定更新は、呼び出し側(run.sh)がclaude -p変換・validate.py全件
合格・drafts/への正式移動まですべて成功させた後に限り commit-pending
サブコマンドで行う。scripts/collect.py 自体は台帳を一切書き換えない
(今回選択したlinkをpendingファイルへ書き出すのみ)。

台帳が存在しない場合、data/raw/*.json(sourceType=rss)とdrafts/*.md の
実在するlinkが一致する組み合わせだけを「成功済み」として初回復元する
(bootstrap_from_history)。rawにあるだけでdraftsに存在しないlinkや、
sourceType=workのlinkは復元しない。
"""
import argparse
import glob
import json
import os
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone

import validate

JST = timezone(timedelta(hours=9))

RETENTION_DAYS = 30
DEFAULT_LEDGER_PATH = "data/state/recent_rss_links.json"
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RAW_DIR = os.path.join(_BASE_DIR, "data", "raw")
DEFAULT_DRAFTS_DIR = os.path.join(_BASE_DIR, "drafts")


def write_json_atomic(path, data):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, p)


def load_recent_rss_links(path):
    """台帳を読み込みlink→日付(YYYY-MM-DD文字列)の辞書を返す。

    ファイルが存在しない場合は空辞書。JSON構文または構造(ルートが
    オブジェクトでない、linksがオブジェクトでない、要素の型が不正)が
    誤っている場合は例外を送出し、黙って空へ初期化しない。
    """
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as f:
        data = json.load(f)  # json.JSONDecodeErrorはそのまま送出する
    if not isinstance(data, dict):
        raise ValueError(f"RSSリンク台帳({path})のルートはオブジェクトである必要があります")
    links = data.get("links")
    if not isinstance(links, dict):
        raise ValueError(f"RSSリンク台帳({path})のlinksはオブジェクトである必要があります")
    for link, d in links.items():
        if not isinstance(link, str) or not isinstance(d, str):
            raise ValueError(f"RSSリンク台帳({path})の要素が不正です: {link!r}: {d!r}")
    return dict(links)


def prune_expired(links, today, retention_days=RETENTION_DAYS):
    """today基準でretention_days日より古いエントリを取り除く。

    日付形式が不正なエントリは復元不能として取り除く。
    """
    cutoff = today - timedelta(days=retention_days)
    pruned = {}
    for link, date_str in links.items():
        try:
            d = date.fromisoformat(date_str)
        except ValueError:
            continue
        if d >= cutoff:
            pruned[link] = date_str
    return pruned


def filter_new_items(items, recent_links):
    """recent_linksに存在するlinkの記事を除外する(URL完全一致のみ)。

    タイトルの一致や意味的な類似では除外しない。items は"link"キーを
    持つ辞書のイテラブル(scripts/collect.pyのparse_feed出力形式)。
    """
    return [item for item in items if item.get("link") not in recent_links]


def write_pending(path, links):
    write_json_atomic(path, {"links": sorted(set(links))})


def commit_pending(pending_path, ledger_path, today, raw_dir=None, drafts_dir=None):
    """pendingのRSSリンクを確定台帳へ原子的にマージし、期限切れ分を整理する。

    pendingファイルが存在しない場合は何もしない(冪等)。

    台帳ファイルがまだ存在しない場合(初回)は、raw_dir/drafts_dirから
    履歴を復元したうえで今回のpending分をマージし、1回の原子的書き込み
    で確定させる(scripts/collect.pyは台帳ファイルへ一切書き込まず、
    フィルタ用にメモリ上でのみ復元結果を使う。台帳の実ファイルは
    commit_pendingでのみ、全工程成功後に書き込まれる)。
    """
    p = pathlib.Path(pending_path)
    if not p.exists():
        return
    with p.open(encoding="utf-8") as f:
        pending = json.load(f)
    pending_links = pending.get("links", [])

    if os.path.exists(ledger_path):
        existing = load_recent_rss_links(ledger_path)
    elif raw_dir is not None and drafts_dir is not None:
        existing = bootstrap_from_history(raw_dir, drafts_dir, today)
    else:
        existing = {}

    today_str = today.isoformat()
    for link in pending_links:
        existing[link] = today_str
    pruned = prune_expired(existing, today)
    write_json_atomic(ledger_path, {"links": pruned})
    p.unlink()


def _extract_draft_links(draft_text):
    """下書き本文から、各ブロックの「### 投稿文」セクション内にある実際の
    元記事リンクだけを抽出する。

    scripts/validate.py と同じ見出し・投稿文セクションの解析ロジックを
    再利用することで、【書記官の解説】やメモなど投稿文以外の場所に偶然
    URLらしき文字列があっても誤って「使用済みリンク」と扱わないように
    する(単純な「行全体がURL」という正規表現だけでは、投稿文セクション
    外のURLも拾ってしまう)。
    """
    links = set()
    headings = list(validate.HEADING_RE.finditer(draft_text))
    for idx, m in enumerate(headings):
        block_start = m.end()
        block_end = headings[idx + 1].start() if idx + 1 < len(headings) else len(draft_text)
        block_text = draft_text[block_start:block_end]
        post_text = validate.extract_post_section(block_text)
        if post_text is None:
            continue
        links.update(validate.extract_link_lines(post_text))
    return links


def bootstrap_from_history(raw_dir, drafts_dir, today, retention_days=RETENTION_DAYS):
    """recent_rss_links.jsonが存在しない場合の初回復元。

    data/raw/YYYY-MM-DD.json のsourceType=rss記事のうち、同日の
    drafts/YYYY-MM-DD.md に同じlinkが実在するものだけを成功済みとして
    復元する。rawにあるだけでdraftsに存在しないlinkは復元しない。
    sourceType=work(Work由来)のlinkはRSS台帳へ登録しない。
    """
    cutoff = today - timedelta(days=retention_days)
    restored = {}

    for raw_path in sorted(glob.glob(os.path.join(raw_dir, "*.json"))):
        name = os.path.basename(raw_path)
        if not name.endswith(".json") or name.startswith("."):
            continue
        date_str = name[: -len(".json")]
        try:
            file_date = date.fromisoformat(date_str)
        except ValueError:
            continue
        if file_date < cutoff:
            continue

        draft_path = os.path.join(drafts_dir, f"{date_str}.md")
        if not os.path.isfile(draft_path):
            continue

        try:
            with open(raw_path, encoding="utf-8") as f:
                articles = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(articles, list):
            continue

        with open(draft_path, encoding="utf-8") as f:
            draft_links = _extract_draft_links(f.read())

        for article in articles:
            if not isinstance(article, dict):
                continue
            if article.get("sourceType") != "rss":
                continue
            link = article.get("link")
            if isinstance(link, str) and link in draft_links:
                restored[link] = date_str

    return restored


def cmd_commit_pending(args):
    today = datetime.now(JST).date()
    commit_pending(args.pending, args.ledger, today, raw_dir=args.raw_dir, drafts_dir=args.drafts_dir)
    print(f"RSSリンク台帳を更新しました: {args.ledger}", file=sys.stderr)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_commit = sub.add_parser("commit-pending", help="pendingのRSSリンクを確定台帳へ反映する")
    p_commit.add_argument("--pending", required=True)
    p_commit.add_argument("--ledger", default=DEFAULT_LEDGER_PATH)
    p_commit.add_argument("--raw-dir", default=DEFAULT_RAW_DIR, help="初回のみ履歴復元に使うdata/rawディレクトリ")
    p_commit.add_argument("--drafts-dir", default=DEFAULT_DRAFTS_DIR, help="初回のみ履歴復元に使うdraftsディレクトリ")
    p_commit.set_defaults(func=cmd_commit_pending)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
