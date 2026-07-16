#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from news_schema import normalize_rss_article

JST = timezone(timedelta(hours=9))
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEEDS_FILE = os.path.join(BASE_DIR, "config", "feeds.txt")
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
USER_AGENT = "news-game-translator/0.1 (personal use)"
TIMEOUT = 30
MAX_ARTICLES = 10


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


def main():
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

    selected = select(dedupe(all_items), MAX_ARTICLES)

    output = [
        normalize_rss_article(
            title=item["title"],
            link=item["link"],
            summary=item["summary"],
            pub_date=item["pub_dt"].isoformat() if item["pub_dt"] else None,
        )
        for item in selected
    ]

    date_str = datetime.now(JST).strftime("%Y-%m-%d")
    os.makedirs(RAW_DIR, exist_ok=True)
    tmp_path = os.path.join(RAW_DIR, f".tmp_{date_str}.json")
    final_path = os.path.join(RAW_DIR, f"{date_str}.json")

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, final_path)

    print(f"取得{fetched_count}件 → 採用{len(selected)}件 → {final_path}")


if __name__ == "__main__":
    main()
