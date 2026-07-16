#!/usr/bin/env python3
"""ルールファイルへの禁止語の再混入を検出する回帰テスト。

config/runtime_rules.md, config/glossary.md, prompts/translate.md,
docs/worldbook.md に、過去に存在した矛盾したルール(王国議会、政党名
カタカナ変換、法案の成立・否決へのクエスト語彙、西洋王国語彙)が
再混入していないかを検査する。

「◯◯は使わない」のような禁止の説明文には禁止語そのものが登場するため、
単純な部分文字列検索では誤検出する。そのため、以下の3パターンでのみ
「再混入」とみなす:

1. Markdownテーブルのセル内(`| ... 禁止語 ... |`)に変換先として現れる
2. 矢印表記の変換先(`→ 禁止語` 等)として現れる
3. 「使ってよい語」の一覧の箇条書き項目(`- 禁止語`)として現れる
4. 【異世界ニホン・◯◯】タグで始まる投稿例ブロックの中に現れる

docs/worldbook.md §16は「旧記載→新基準」を対比させる歴史的な記録であり、
旧記載側に禁止語が矢印付きで登場するのは意図的なため、検査対象から除外する。

Python標準ライブラリのみを使用する(unittest, pathlib, re, sys)。
"""
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from banned_terms import FORBIDDEN_PARTY_KATAKANA, FORBIDDEN_TERMS  # noqa: E402

TARGET_FILES = [
    ROOT / "config" / "runtime_rules.md",
    ROOT / "config" / "glossary.md",
    ROOT / "prompts" / "translate.md",
    ROOT / "docs" / "worldbook.md",
]

# docs/worldbook.md §16は「旧記載→新基準」の歴史的な対比表であり、
# 旧記載側に禁止語が矢印付きで登場するのは意図的な記録のため除外する。
# 変更履歴も、修正内容の説明として禁止語の名前そのものに言及するため除外する。
EXCLUDED_SECTION_HEADINGS = {
    ROOT / "docs" / "worldbook.md": [
        "## 16. 用語表へ反映すべき確定事項",
        "## 変更履歴",
    ],
}

EXAMPLE_BLOCK_RE = re.compile(
    r"【異世界ニホン・[^】]+】.*?(?=\n[ \t]*\n|\Z)",
    re.DOTALL,
)


def strip_excluded_sections(path, text):
    headings = EXCLUDED_SECTION_HEADINGS.get(path, [])
    for heading in headings:
        start = text.find(heading)
        if start == -1:
            continue
        next_heading = re.search(r"\n## \d", text[start + len(heading):])
        end = start + len(heading) + next_heading.start() if next_heading else len(text)
        text = text[:start] + text[end:]
    return text


def find_mapping_usages(text, term):
    """termが「変換先」として使われている箇所(テーブルセル/矢印表記)を返す。

    テーブルセルはセル全体が完全一致でなくとも、セル内にtermが含まれていれば
    検出する(例: `| 地方自治体 | 地方領、都道府県、市町村 |`)。矢印表記は
    →/⇒/⟶/->/=> のいずれか、および直後の強調記法(**/__ 等)を許容する。
    """
    escaped = re.escape(term)
    table_cell = rf"\|[^|\n]*{escaped}[^|\n]*\|"
    arrow = rf"(?:→|⇒|⟶|->|=>)\s*[*_]*{escaped}"
    pattern = re.compile(rf"{table_cell}|{arrow}")
    return pattern.findall(text)


def find_bullet_list_usages(text, term):
    """termが箇条書きの1項目として単独で使われている箇所を返す。

    「使ってよい語」のような一覧に禁止語が紛れ込むケースを検出する
    (例: `- 王都`)。
    """
    escaped = re.escape(term)
    pattern = re.compile(rf"^[-*]\s*{escaped}\s*$", re.MULTILINE)
    return pattern.findall(text)


def find_example_post_usages(text, term):
    """【異世界ニホン・◯◯】タグで始まる投稿例ブロック内でのtermの使用を返す。"""
    matches = []
    for block_match in EXAMPLE_BLOCK_RE.finditer(text):
        block = block_match.group(0)
        if term in block:
            matches.append(block.splitlines()[0])
    return matches


def find_all_usages(text, term):
    return (
        find_mapping_usages(text, term)
        + find_bullet_list_usages(text, term)
        + find_example_post_usages(text, term)
    )


class RuleConsistencyTest(unittest.TestCase):
    def test_target_files_exist(self):
        for path in TARGET_FILES:
            self.assertTrue(path.is_file(), f"{path} が存在しません")

    def test_forbidden_terms_not_reintroduced(self):
        for path in TARGET_FILES:
            text = strip_excluded_sections(path, path.read_text(encoding="utf-8"))
            for term in FORBIDDEN_TERMS:
                matches = find_all_usages(text, term)
                self.assertEqual(
                    matches,
                    [],
                    f"{path.relative_to(ROOT)} に禁止語「{term}」が変換先・許可リスト・"
                    f"投稿例として再混入しています: {matches}",
                )

    def test_party_katakana_not_reintroduced(self):
        for path in TARGET_FILES:
            text = strip_excluded_sections(path, path.read_text(encoding="utf-8"))
            for term in FORBIDDEN_PARTY_KATAKANA:
                matches = find_all_usages(text, term)
                self.assertEqual(
                    matches,
                    [],
                    f"{path.relative_to(ROOT)} に政党名カタカナ変換「{term}」が"
                    f"変換先・許可リスト・投稿例として再混入しています: {matches}",
                )


if __name__ == "__main__":
    unittest.main()
