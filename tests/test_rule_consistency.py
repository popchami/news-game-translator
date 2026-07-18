#!/usr/bin/env python3
"""ルールファイルへの禁止語の再混入を検出する回帰テスト。

config/runtime_rules.md, config/glossary.md, prompts/translate.md,
docs/worldbook.md に、過去に存在した矛盾したルール(王国議会、政党名
カタカナ変換、法案の成立・否決へのクエスト語彙、西洋王国語彙)が
再混入していないかを検査する。

「◯◯は使わない」のような禁止の説明文には禁止語そのものが登場するため、
単純な部分文字列検索では誤検出する。そのため、以下の4パターンでのみ
「再混入」とみなす:

1. Markdownテーブルのセル内(`| ... 禁止語 ... |`)に変換先として現れる
2. 矢印表記の変換先(`→ 禁止語` 等)として現れる
3. 「使ってよい語」の一覧の箇条書き項目(`- 禁止語`)として現れる
4. 【異世界ニホン・◯◯】タグで始まる投稿例ブロックの中に現れる

ただし banned_terms.CONTEXTUAL_FORBIDDEN_TERMS(「クエスト受注」
「クエスト失敗」「正式実装」「選抜戦」)と banned_terms.
ROYALTY_ADJACENT_TERMS(「国王」「女王」「王家」「王族」「王子」「王女」
「王妃」)は、上記1・2(変換先としての使用)のみを検査する。前者は
実際のクエスト(政策実行)の結果やスポーツなど法案・選挙と無関係な
文脈で、後者は皇室典範上の正式な身位語・外国の君主号として、いずれも
下書きの投稿例や箇条書きに正当に現れうるため(2026-07-18改訂: 王制
語彙は単語単位の無条件禁止から、入力データとの照合方式へ変更した。
詳細は scripts/banned_terms.py 参照)、3・4のパターンでは検査しない。
下書き本文への出現は scripts/validate.py が別途、入力データとの照合で
検出する。

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

from banned_terms import (  # noqa: E402
    CONTEXTUAL_FORBIDDEN_TERMS,
    FORBIDDEN_PARTY_KATAKANA,
    KINGDOM_SMELL_TERMS,
    ROYALTY_ADJACENT_TERMS,
)

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
    """指定した見出しから、次の`## `見出し(番号の有無を問わない)または
    文末までを本文から取り除く。`### `等のより深い見出しは境界とみなさない
    (`\n## `は`\n### `の先頭3文字とは一致しないため誤って途中で止まらない)。
    """
    headings = EXCLUDED_SECTION_HEADINGS.get(path, [])
    for heading in headings:
        start = text.find(heading)
        if start == -1:
            continue
        next_heading = re.search(r"\n## ", text[start + len(heading):])
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
            for term in KINGDOM_SMELL_TERMS:
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

    def test_royalty_terms_not_used_as_mapping_target(self):
        """王制関連語(国王・女王・王家・王族・王子・王女・王妃)は実在語彙
        として許可されるため、箇条書き・投稿例での使用は検査しない(むしろ
        正当な使用例として現れうる)。天皇・皇族をこれらの語へ変換する
        「変換先」としての再混入だけを検査する。
        """
        for path in TARGET_FILES:
            text = strip_excluded_sections(path, path.read_text(encoding="utf-8"))
            for term in ROYALTY_ADJACENT_TERMS:
                matches = find_mapping_usages(text, term)
                self.assertEqual(
                    matches,
                    [],
                    f"{path.relative_to(ROOT)} に「{term}」が天皇・皇族の変換先として"
                    f"再混入しています: {matches}",
                )

    def test_contextual_terms_not_used_as_mapping(self):
        """文脈依存の禁止語は変換先としての再混入のみ検査する。

        投稿例・箇条書きでの正当な使用(実際のクエストの結果やスポーツ等、
        法案・選挙と無関係な文脈での用法)は許可するため、
        find_mapping_usages(テーブル/矢印)のみを使う
        (find_bullet_list_usages・find_example_post_usagesは使わない)。
        """
        for path in TARGET_FILES:
            text = strip_excluded_sections(path, path.read_text(encoding="utf-8"))
            for term in CONTEXTUAL_FORBIDDEN_TERMS:
                matches = find_mapping_usages(text, term)
                self.assertEqual(
                    matches,
                    [],
                    f"{path.relative_to(ROOT)} に「{term}」が変換先として"
                    f"再混入しています(法案・選挙関連の記事に使用不可): {matches}",
                )


if __name__ == "__main__":
    unittest.main()
