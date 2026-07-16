#!/usr/bin/env python3
import json
import re
import sys
from collections import Counter

from banned_terms import FORBIDDEN_PARTY_KATAKANA, FORBIDDEN_TERMS

POST_BODY_LIMIT = 130
HASHTAG_LINE = "#異世界ニホン"

HEADING_RE = re.compile(r"^(## 下書き(\d+))(.*)$", re.MULTILINE)
NARRATIVE_RE = re.compile(r"^(.*?)(?=\n【書記官の解説】|\Z)", re.S)
TAG_RE = re.compile(r"^【異世界ニホン・[^】]+】$")


def extract_post_section(block_text):
    m = re.search(r"### 投稿文\s*\n(.*?)(?=\n### メモ|\Z)", block_text, re.S)
    if not m:
        return None
    return m.group(1)


def extract_narrative(post_text):
    m = NARRATIVE_RE.match(post_text)
    return m.group(1) if m else post_text


def load_source_links(source_path):
    with open(source_path, encoding="utf-8") as f:
        articles = json.load(f)
    if not isinstance(articles, list):
        raise ValueError("入力JSONのルートは配列である必要があります")
    links = {a["link"] for a in articles if isinstance(a, dict) and a.get("link")}
    return links, len(articles)


def extract_link_lines(post_text):
    return [line.strip() for line in post_text.splitlines() if line.strip().startswith("http")]


def check_post(post_text, source_links, duplicate_links):
    reasons = []
    lines = [line.strip() for line in post_text.splitlines() if line.strip()]

    if not lines or not TAG_RE.match(lines[0]):
        reasons.append("冒頭に【異世界ニホン・◯◯】タグがない、または同じ行に余分な文字がある")

    link_lines = extract_link_lines(post_text)
    if not link_lines:
        reasons.append("元記事リンクなし")
    elif source_links is not None:
        unmatched = [link for link in link_lines if link not in source_links]
        if unmatched:
            reasons.append(f"元記事リンクが入力JSONのlinkと一致しない: {', '.join(unmatched)}")

    if duplicate_links:
        reasons.append(f"元記事リンクが他の下書きと重複: {', '.join(sorted(duplicate_links))}")

    hashtag_lines = [line for line in lines if line == HASHTAG_LINE]
    other_hashtag_lines = [
        line for line in lines if line.startswith("#") and line != HASHTAG_LINE
    ]
    if len(hashtag_lines) != 1:
        reasons.append(f"{HASHTAG_LINE}が{len(hashtag_lines)}個(1個である必要)")
    if other_hashtag_lines:
        reasons.append("規定外のハッシュタグ行がある")

    if "【書記官の解説】" not in post_text:
        reasons.append("【書記官の解説】がない")

    narrative = extract_narrative(post_text)
    body_lines = []
    for line in narrative.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("http"):
            continue
        if stripped.startswith("#"):
            continue
        body_lines.append(stripped)
    body = "".join(body_lines)
    if len(body) > POST_BODY_LIMIT:
        reasons.append(f"{POST_BODY_LIMIT}字超過({len(body)}字、物語本文のみ)")

    for term in FORBIDDEN_TERMS:
        if term in post_text:
            reasons.append(f"禁止語「{term}」を検出")

    for term in FORBIDDEN_PARTY_KATAKANA:
        if term in post_text:
            reasons.append(f"政党名カタカナ変換「{term}」を検出")

    return reasons


def main():
    if len(sys.argv) not in (2, 3):
        print("usage: validate.py <draft_file> [<source_json>]", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    source_path = sys.argv[2] if len(sys.argv) == 3 else None

    with open(path, encoding="utf-8") as f:
        content = f.read()

    source_links = None
    source_count = None
    file_level_reasons = []

    if source_path:
        try:
            source_links, source_count = load_source_links(source_path)
        except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
            file_level_reasons.append(f"入力JSON({source_path})の読み込みに失敗: {e}")

    headings = list(HEADING_RE.finditer(content))
    total = len(headings)
    passed = 0
    replacements = []

    if total == 0:
        file_level_reasons.append("下書きが0件です")

    if source_count is not None and total > source_count:
        file_level_reasons.append(f"下書き件数({total})が入力記事数({source_count})を超えています")

    # 1回目の走査: 各下書きの投稿文とリンクを収集し、リンクの重複を検出する
    blocks = []
    link_counter = Counter()
    for idx, m in enumerate(headings):
        block_start = m.end()
        block_end = headings[idx + 1].start() if idx + 1 < total else len(content)
        block_text = content[block_start:block_end]
        post_text = extract_post_section(block_text)
        blocks.append((m, post_text))
        if post_text is not None:
            link_counter.update(set(extract_link_lines(post_text)))

    duplicated_links = {link for link, count in link_counter.items() if count > 1}

    # 2回目の走査: 各下書きを検証し、見出しを書き換える
    for m, post_text in blocks:
        if post_text is None:
            reasons = ["投稿文セクションが見つかりません"]
        else:
            this_draft_links = set(extract_link_lines(post_text))
            reasons = check_post(post_text, source_links, this_draft_links & duplicated_links)

        if reasons:
            new_heading = f"{m.group(1)} ⚠NG({', '.join(reasons)})"
        else:
            new_heading = m.group(1)
            passed += 1
        replacements.append((m.start(), m.end(), new_heading))

    new_content = content
    for start, end, new_heading in reversed(replacements):
        new_content = new_content[:start] + new_heading + new_content[end:]

    new_content = new_content.rstrip("\n") + f"\n\n<!-- validate: 全{total}件中 合格{passed}件 -->\n"

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)

    ok = total > 0 and passed == total and not file_level_reasons

    print(f"validate: 全{total}件中 合格{passed}件")
    for reason in file_level_reasons:
        print(f"[ERROR] {reason}", file=sys.stderr)
    if not ok:
        print(f"[ERROR] 構造違反があるため非ゼロ終了します。検査結果は {path} を確認してください", file=sys.stderr)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
