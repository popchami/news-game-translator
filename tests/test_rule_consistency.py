#!/usr/bin/env python3
"""ルールファイルへの禁止語の再混入を検出する回帰テスト。

config/runtime_rules.md, config/glossary.md, prompts/translate.md に、
過去に存在した矛盾したルール(王国議会、政党名カタカナ変換、法案の
成立・否決へのクエスト語彙)が「変換先」として再び指定されていないかを
検査する。

「◯◯は使わない」のような禁止の説明文には禁止語そのものが登場するため、
単純な部分文字列検索では誤検出する。そのため、Markdownテーブルのセル
(`| 禁止語 |`)または矢印表記の変換先(`→ 禁止語`)として使われている
場合のみを「再混入」とみなす。

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
]


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


class RuleConsistencyTest(unittest.TestCase):
    def test_target_files_exist(self):
        for path in TARGET_FILES:
            self.assertTrue(path.is_file(), f"{path} が存在しません")

    def test_forbidden_terms_not_used_as_mapping(self):
        for path in TARGET_FILES:
            text = path.read_text(encoding="utf-8")
            for term in FORBIDDEN_TERMS:
                matches = find_mapping_usages(text, term)
                self.assertEqual(
                    matches,
                    [],
                    f"{path.relative_to(ROOT)} に禁止語「{term}」が変換先として"
                    f"再混入しています: {matches}",
                )

    def test_party_katakana_not_used_as_mapping(self):
        for path in TARGET_FILES:
            text = path.read_text(encoding="utf-8")
            for term in FORBIDDEN_PARTY_KATAKANA:
                matches = find_mapping_usages(text, term)
                self.assertEqual(
                    matches,
                    [],
                    f"{path.relative_to(ROOT)} に政党名カタカナ変換「{term}」が"
                    f"変換先として再混入しています: {matches}",
                )


if __name__ == "__main__":
    unittest.main()
