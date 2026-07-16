#!/usr/bin/env python3
import re
import sys

POST_BODY_LIMIT = 140

HEADING_RE = re.compile(r"^(## 下書き(\d+))(.*)$", re.MULTILINE)


def extract_post_section(block_text):
    m = re.search(r"### 投稿文\s*\n(.*?)(?=\n### メモ|\Z)", block_text, re.S)
    if not m:
        return None
    return m.group(1)


def check_post(post_text):
    reasons = []
    has_link = False
    body_lines = []
    for line in post_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("http"):
            has_link = True
            continue
        if stripped.startswith("#"):
            continue
        body_lines.append(stripped)

    body = "".join(body_lines)
    if len(body) > POST_BODY_LIMIT:
        reasons.append(f"{POST_BODY_LIMIT}字超過({len(body)}字)")
    if not has_link:
        reasons.append("元記事リンクなし")
    return reasons


def main():
    if len(sys.argv) != 2:
        print("usage: validate.py <draft_file>", file=sys.stderr)
        sys.exit(0)

    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        content = f.read()

    headings = list(HEADING_RE.finditer(content))
    total = len(headings)
    passed = 0
    replacements = []

    for idx, m in enumerate(headings):
        block_start = m.end()
        block_end = headings[idx + 1].start() if idx + 1 < total else len(content)
        block_text = content[block_start:block_end]
        post_text = extract_post_section(block_text)

        if post_text is None:
            reasons = ["投稿文セクションが見つかりません"]
        else:
            reasons = check_post(post_text)

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

    print(f"validate: 全{total}件中 合格{passed}件")
    sys.exit(0)


if __name__ == "__main__":
    main()
