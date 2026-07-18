#!/usr/bin/env python3
import json
import re
import sys
import unicodedata
from collections import Counter

from banned_terms import (
    CONTEXTUAL_FORBIDDEN_TERMS,
    FORBIDDEN_PARTY_KATAKANA,
    KINGDOM_SMELL_TERMS,
    ROYALTY_ADJACENT_TERMS,
)

POST_BODY_LIMIT = 130
HASHTAG_LINE = "#異世界ニホン"

HEADING_RE = re.compile(r"^(## 下書き(\d+))(.*)$", re.MULTILINE)
NARRATIVE_RE = re.compile(r"^(.*?)(?=\n【書記官の解説】|\Z)", re.S)
TAG_RE = re.compile(r"^【異世界ニホン・[^】]+】$")
MEMO_RE = re.compile(r"### メモ\s*\n(.*?)\Z", re.S)
COLLECTION_ROUTE_RE = re.compile(r"^-\s*収集経路:\s*(\S+)\s*$", re.MULTILINE)

# 入力記事のsourceType(work/rss)と、下書きメモに書くべき収集経路表記の対応。
SOURCE_TYPE_LABELS = {"work": "Work", "rss": "RSS"}

# 「ニホン」(助詞「の」の有無いずれも)に王制語彙が直接隣接する固定
# 複合表現だけを検出する(例:「ニホンの女王」「ニホン国王」)。「英国の
# 女王」のように「ニホン」に隣接しない場合は一致しない。「統治する」等、
# 文全体の意味理解が必要な主張はここでは判定しない(banned_terms.pyの
# モジュールdocstring参照)。
NIHON_ROYALTY_ADJACENT_RE = re.compile(
    "ニホン(?:の)?(?:" + "|".join(re.escape(t) for t in ROYALTY_ADJACENT_TERMS) + ")"
)

# 検査回避に使われうる不可視文字(禁止語やタグの途中に挿入して
# 部分文字列一致をすり抜ける手口への対策)。
INVISIBLE_CHARS = (
    "​"  # ZERO WIDTH SPACE
    "‌"  # ZERO WIDTH NON-JOINER
    "‍"  # ZERO WIDTH JOINER
    "⁠"  # WORD JOINER
    "﻿"  # ZERO WIDTH NO-BREAK SPACE / BOM
)
INVISIBLE_TRANS = str.maketrans("", "", INVISIBLE_CHARS)


def normalize_for_check(text):
    """禁止語・タグ・ハッシュタグ・政党名の検査用に、NFKC正規化と不可視文字の
    除去を行った文字列を作る。生成された下書きファイル自体は書き換えない
    (文字数カウントやリンクの比較には元のtextをそのまま使う)。
    """
    return unicodedata.normalize("NFKC", text).translate(INVISIBLE_TRANS)


def extract_post_section(block_text):
    m = re.search(r"### 投稿文\s*\n(.*?)(?=\n### メモ|\Z)", block_text, re.S)
    if not m:
        return None
    return m.group(1)


def extract_narrative(post_text):
    m = NARRATIVE_RE.match(post_text)
    return m.group(1) if m else post_text


def extract_memo_section(block_text):
    m = MEMO_RE.search(block_text)
    return m.group(1) if m else None


def load_source_articles(source_path):
    with open(source_path, encoding="utf-8") as f:
        articles = json.load(f)
    if not isinstance(articles, list):
        raise ValueError("入力JSONのルートは配列である必要があります")
    return articles


def extract_link_lines(post_text):
    return [line.strip() for line in post_text.splitlines() if line.strip().startswith("http")]


def build_source_text_blob(article):
    """入力記事1件のテキスト系フィールドを連結し、王制語の入力照合に使う
    正規化済みテキストを作る(NFKC正規化・不可視文字除去はnormalize_for_
    checkと同一処理)。id・URL・日付等、語彙照合に意味を持たないフィールド
    は含めない。
    """
    parts = [
        str(article.get("title", "") or ""),
        str(article.get("category", "") or ""),
        str(article.get("summary", "") or ""),
        str(article.get("status", "") or ""),
    ]
    for field in (
        "confirmedFacts",
        "remainingProcess",
        "people",
        "organizations",
        "sourceDifferences",
        "translationCautions",
    ):
        value = article.get(field)
        if isinstance(value, list):
            parts.extend(str(v) for v in value)
    return normalize_for_check("\n".join(parts))


def check_kingdom_terms(normalized_post, source_text):
    """ニホンに実在しない王制の創作だけを検出する。

    source_textがNoneの場合(入力照合ができない場合)は検査しない。
    入力記事に同一の表現が存在する語・複合表現は、引用・否定説明等の
    可能性があるため許可する(=NGにしない)。「統治する」等、文全体の
    意味理解が必要な主張はここでは判定しない
    (banned_terms.pyのモジュールdocstring参照)。
    """
    if source_text is None:
        return []

    reasons = []

    for term in KINGDOM_SMELL_TERMS:
        if term not in normalized_post:
            continue
        if term in source_text:
            continue
        reasons.append(f"入力に存在しない語「{term}」がニホンの制度として追加されています")

    reported_compounds = set()
    for match in NIHON_ROYALTY_ADJACENT_RE.finditer(normalized_post):
        compound = match.group(0)
        if compound in reported_compounds:
            continue
        if compound in source_text:
            continue
        reported_compounds.add(compound)
        reasons.append(f"入力に存在しない複合表現「{compound}」がニホンの制度として追加されています")

    return reasons


def check_post(
    post_text,
    source_links,
    duplicate_links,
    memo_text=None,
    link_source_type=None,
    link_to_source_text=None,
):
    reasons = []
    normalized_post = normalize_for_check(post_text)
    normalized_lines = [line.strip() for line in normalized_post.splitlines() if line.strip()]

    if not normalized_lines or not TAG_RE.match(normalized_lines[0]):
        reasons.append("冒頭に【異世界ニホン・◯◯】タグがない、または同じ行に余分な文字がある")

    # リンクは正規化せず元の文字列で比較する(URLをNFKC正規化すると
    # 実在するリンクを別物に変えてしまう可能性があるため)。
    link_lines = extract_link_lines(post_text)
    if not link_lines:
        reasons.append("元記事リンクなし")
    elif source_links is not None:
        unmatched = [link for link in link_lines if link not in source_links]
        if unmatched:
            reasons.append(f"元記事リンクが入力JSONのlinkと一致しない: {', '.join(unmatched)}")

    if duplicate_links:
        reasons.append(f"元記事リンクが他の下書きと重複: {', '.join(sorted(duplicate_links))}")

    hashtag_lines = [line for line in normalized_lines if line == HASHTAG_LINE]
    other_hashtag_lines = [
        line for line in normalized_lines if line.startswith("#") and line != HASHTAG_LINE
    ]
    if len(hashtag_lines) != 1:
        reasons.append(f"{HASHTAG_LINE}が{len(hashtag_lines)}個(1個である必要)")
    if other_hashtag_lines:
        reasons.append("規定外のハッシュタグ行がある")

    if "【書記官の解説】" not in normalized_post:
        reasons.append("【書記官の解説】がない")

    # 文字数は正規化前の元の文字列で数える(表示上の見た目を尊重するため)。
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

    # 王制語彙検査は、下書きに有効な元記事リンクが厳密に1件だけ存在し、
    # そのリンクから対応する入力記事を一意に特定できる場合だけ実行する。
    # 入力テキストblobの内容が偶然同じかどうかでは判定しない(リンク数を
    # 基準にする)。リンクが0件・2件以上の場合、または唯一のリンクが
    # 入力記事のいずれとも一致しない場合は実行しない(後者はリンク不一致
    # 検査で別途NGになる)。
    source_text = None
    if link_to_source_text is not None and len(link_lines) == 1:
        source_text = link_to_source_text.get(link_lines[0])
    reasons.extend(check_kingdom_terms(normalized_post, source_text))

    for term, context_markers in CONTEXTUAL_FORBIDDEN_TERMS.items():
        if term in normalized_post and any(marker in normalized_post for marker in context_markers):
            reasons.append(f"禁止語「{term}」を法案・選挙の文脈で検出")

    for term in FORBIDDEN_PARTY_KATAKANA:
        if term in normalized_post:
            reasons.append(f"政党名カタカナ変換「{term}」を検出")

    if link_source_type is not None:
        expected_types = {
            link_source_type[link] for link in link_lines if link in link_source_type
        }
        if len(expected_types) == 1:
            expected_label = SOURCE_TYPE_LABELS.get(next(iter(expected_types)))
            route_match = COLLECTION_ROUTE_RE.search(memo_text or "")
            if not route_match:
                reasons.append("メモに「収集経路: Work」または「収集経路: RSS」の記載がない")
            elif route_match.group(1) != expected_label:
                reasons.append(
                    f"メモの収集経路が入力記事のsourceTypeと不一致"
                    f"(記載: {route_match.group(1)}, 期待: {expected_label})"
                )

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
    link_source_type = None
    link_to_source_text = None
    file_level_reasons = []

    if source_path:
        try:
            source_articles = load_source_articles(source_path)
            source_count = len(source_articles)
            link_source_type = {
                a["link"]: a.get("sourceType")
                for a in source_articles
                if isinstance(a, dict) and a.get("link")
            }
            link_to_source_text = {
                a["link"]: build_source_text_blob(a)
                for a in source_articles
                if isinstance(a, dict) and a.get("link")
            }
            source_links = set(link_source_type.keys())
            invalid_source_types = sorted(
                {
                    str(a.get("sourceType"))
                    for a in source_articles
                    if isinstance(a, dict) and a.get("sourceType") not in ("work", "rss")
                }
            )
            if invalid_source_types:
                file_level_reasons.append(
                    f"入力記事のsourceTypeが不正です(workまたはrssである必要): {', '.join(invalid_source_types)}"
                )
        except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
            file_level_reasons.append(f"入力JSON({source_path})の読み込みに失敗: {e}")

    headings = list(HEADING_RE.finditer(content))
    total = len(headings)
    passed = 0
    replacements = []

    if total == 0:
        file_level_reasons.append("下書きが0件です")

    if source_count is not None and total != source_count:
        file_level_reasons.append(f"下書き件数({total})が入力記事数({source_count})と一致しません")

    # 1回目の走査: 各下書きの投稿文とリンクを収集し、リンクの重複・欠落を検出する
    blocks = []
    link_counter = Counter()
    all_used_links = set()
    for idx, m in enumerate(headings):
        block_start = m.end()
        block_end = headings[idx + 1].start() if idx + 1 < total else len(content)
        block_text = content[block_start:block_end]
        post_text = extract_post_section(block_text)
        memo_text = extract_memo_section(block_text)
        blocks.append((m, post_text, memo_text))
        if post_text is not None:
            draft_links = extract_link_lines(post_text)
            # setにせず実際の出現回数をそのまま数える。同一下書き内で
            # 同じリンクを2回書いた場合も「重複」として検出するため
            # (入力の各リンクが厳密に1回ずつ使われることを保証する)。
            link_counter.update(draft_links)
            all_used_links.update(draft_links)

    duplicated_links = {link for link, count in link_counter.items() if count > 1}

    if source_links is not None:
        missing_links = source_links - all_used_links
        if missing_links:
            file_level_reasons.append(
                f"入力記事のリンクが下書きに使われていません: {', '.join(sorted(missing_links))}"
            )

    # 2回目の走査: 各下書きを検証し、見出しを書き換える
    for m, post_text, memo_text in blocks:
        if post_text is None:
            reasons = ["投稿文セクションが見つかりません"]
        else:
            this_draft_links = set(extract_link_lines(post_text))
            reasons = check_post(
                post_text,
                source_links,
                this_draft_links & duplicated_links,
                memo_text,
                link_source_type,
                link_to_source_text,
            )

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
