#!/usr/bin/env python3
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import rss_dedup
from news_schema import normalize_rss_article

JST = timezone(timedelta(hours=9))
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEEDS_FILE = os.path.join(BASE_DIR, "config", "feeds.txt")
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
DRAFTS_DIR = os.path.join(BASE_DIR, "drafts")
STATE_DIR = os.path.join(BASE_DIR, "data", "state")
USER_AGENT = "news-game-translator/0.1 (personal use)"
TIMEOUT = 30
MAX_ARTICLES = 10

# 新規記事0件(重複除外の結果を含む)を示す終了コード。全URL取得失敗
# (exit 1)とは区別し、run.sh側でclaude -p/validate.pyを呼ばずに正常
#終了できるようにする。
EXIT_NO_NEW_ARTICLES = 2


def read_feeds(path):
    urls = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    return urls


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def parse_feed(data, source_url):
    items = []
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        print(f"[WARN] {source_url}: XML解析失敗: {e}", file=sys.stderr)
        return items

    channel = root.find("channel")
    if channel is None:
        print(f"[WARN] {source_url}: channel要素が見つかりません", file=sys.stderr)
        return items

    for item in channel.findall("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        link = link_el.text.strip() if link_el is not None and link_el.text else ""
        if not title or not link:
            print(f"[WARN] {source_url}: title/linkが欠けたitemをスキップ", file=sys.stderr)
            continue

        desc_el = item.find("description")
        summary = desc_el.text.strip() if desc_el is not None and desc_el.text else ""

        pubdate_el = item.find("pubDate")
        pub_dt = None
        if pubdate_el is not None and pubdate_el.text:
            try:
                pub_dt = parsedate_to_datetime(pubdate_el.text.strip())
            except (TypeError, ValueError) as e:
                print(f"[WARN] {source_url}: pubDate解析失敗 ({pubdate_el.text!r}): {e}", file=sys.stderr)

        items.append({"title": title, "link": link, "summary": summary, "pub_dt": pub_dt})
    return items


def dedupe(items):
    seen = set()
    result = []
    for item in items:
        if item["link"] in seen:
            continue
        seen.add(item["link"])
        result.append(item)
    return result


def select(items, limit):
    dated = [i for i in items if i["pub_dt"] is not None]
    undated = [i for i in items if i["pub_dt"] is None]
    dated.sort(key=lambda i: i["pub_dt"], reverse=True)
    return (dated + undated)[:limit]


def parse_args():
    parser = argparse.ArgumentParser(description="RSS収集(日またぎ重複除外込み)")
    parser.add_argument("--out", default=None, help="出力先(未指定時はdata/raw/{today}.json)")
    parser.add_argument("--pending-out", default=None, help="今回選択したlinkの一時記録先")
    parser.add_argument("--recent-links", default=None, help="RSSリンク台帳(未指定時はdata/state/recent_rss_links.json)")
    return parser.parse_args()


def main():
    args = parse_args()
    urls = read_feeds(FEEDS_FILE)

    all_items = []
    fetched_count = 0
    success_count = 0
    for url in urls:
        try:
            data = fetch(url)
        except (urllib.error.URLError, OSError) as e:
            print(f"[ERROR] {url}: 取得失敗: {e}", file=sys.stderr)
            continue
        success_count += 1
        items = parse_feed(data, url)
        fetched_count += len(items)
        all_items.extend(items)

    if success_count == 0:
        print("[ERROR] 全URLの取得に失敗しました。ファイルは書き込みません。", file=sys.stderr)
        sys.exit(1)

    date_str = datetime.now(JST).strftime("%Y-%m-%d")
    today = datetime.now(JST).date()

    out_path = args.out or os.path.join(RAW_DIR, f"{date_str}.json")
    pending_path = args.pending_out or os.path.join(STATE_DIR, f".pending_rss_links_{date_str}.json")
    recent_links_path = args.recent_links or rss_dedup.DEFAULT_LEDGER_PATH

    # 台帳ファイルへは一切書き込まない(collect.pyは台帳を確定更新しない)。
    # ファイルが存在しなければ、フィルタ用に履歴からメモリ上でのみ復元する。
    # 実ファイルへの書き込みはcommit_pending(全工程成功後)でのみ行う。
    if os.path.exists(recent_links_path):
        try:
            recent_links = rss_dedup.load_recent_rss_links(recent_links_path)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            print(f"[ERROR] RSSリンク台帳({recent_links_path})の読み込みに失敗しました: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        recent_links = rss_dedup.bootstrap_from_history(RAW_DIR, DRAFTS_DIR, today)
        print(
            f"[INFO] RSSリンク台帳がまだ存在しないため、過去実績から一時的に復元しました"
            f"({len(recent_links)}件、ファイルへの書き込みは今回の全工程成功後に行われます)",
            file=sys.stderr,
        )

    deduped = dedupe(all_items)
    non_duplicate = rss_dedup.filter_new_items(deduped, recent_links)
    excluded_count = len(deduped) - len(non_duplicate)

    selected = select(non_duplicate, MAX_ARTICLES)

    if not selected:
        print("本日の新規RSS記事はありません", file=sys.stderr)
        sys.exit(EXIT_NO_NEW_ARTICLES)

    output = [
        normalize_rss_article(
            title=item["title"],
            link=item["link"],
            summary=item["summary"],
            pub_date=item["pub_dt"].isoformat() if item["pub_dt"] else None,
        )
        for item in selected
    ]

    rss_dedup.write_json_atomic(out_path, output)
    rss_dedup.write_pending(pending_path, [item["link"] for item in selected])

    print(
        f"取得{fetched_count}件 → 重複除外{excluded_count}件 → 採用{len(selected)}件 → {out_path}"
    )


if __name__ == "__main__":
    main()
