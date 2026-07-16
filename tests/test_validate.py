#!/usr/bin/env python3
"""scripts/validate.py の異常系・正常系テスト。

Unicode正規化(NFKC・不可視文字除去)による検査回避への耐性と、
入力記事数と下書き数・リンクの一対一対応チェックを検証する。

scripts/validate.py を実際にサブプロセスとして起動する
ブラックボックステストである。Python標準ライブラリのみを使用する
(unittest, pathlib, subprocess, json, tempfile, sys)。
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
VALIDATE_PY = ROOT / "scripts" / "validate.py"


def run_validate(draft_text, source_articles):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = pathlib.Path(tmpdir)
        draft_path = tmp / "draft.md"
        source_path = tmp / "source.json"
        draft_path.write_text(draft_text, encoding="utf-8")
        source_path.write_text(json.dumps(source_articles, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(VALIDATE_PY), str(draft_path), str(source_path)],
            capture_output=True,
            text=True,
        )
        return result.returncode, draft_path.read_text(encoding="utf-8"), result.stdout, result.stderr


def make_source(n):
    return [
        {"title": f"t{i}", "link": f"http://example.com/{i}", "summary": "s", "pubDate": None}
        for i in range(n)
    ]


def draft_block(idx, tag, body, link):
    return (
        f"## 下書き{idx}\n"
        "### 投稿文\n"
        f"{tag}\n"
        f"{body}\n"
        "\n"
        "【書記官の解説】\n"
        "テスト用の解説文。\n"
        "\n"
        f"{link}\n"
        "#異世界ニホン\n"
        "### メモ\n"
        f"- 元記事: テスト{idx}\n"
    )


def make_draft(n, links=None, bodies=None, tags=None):
    links = links or [f"http://example.com/{i}" for i in range(n)]
    bodies = bodies or ["テスト本文。" for _ in range(n)]
    tags = tags or ["【異世界ニホン・国法】" for _ in range(n)]
    blocks = "\n".join(
        draft_block(i + 1, tags[i], bodies[i], links[i]) for i in range(n)
    )
    return "# X投稿下書き テスト\n\n" + blocks


class UnicodeEvasionTest(unittest.TestCase):
    def test_zero_width_inside_forbidden_term_is_detected(self):
        body = "中央評議会の王​国議会でクエストが進む。"
        draft = make_draft(1, bodies=[body])
        code, content, _, _ = run_validate(draft, make_source(1))
        self.assertNotEqual(code, 0)
        self.assertIn("⚠NG", content)
        self.assertIn("王国議会", content)

    def test_zero_width_inside_contextual_term_is_detected(self):
        body = "法案が否決され、クエスト​失敗となった。"
        draft = make_draft(1, bodies=[body])
        code, content, _, _ = run_validate(draft, make_source(1))
        self.assertNotEqual(code, 0)
        self.assertIn("⚠NG", content)

    def test_bom_and_word_joiner_inside_forbidden_term_is_detected(self):
        body = "選挙は民の選⁠抜﻿戦となる。"
        draft = make_draft(1, bodies=[body])
        code, content, _, _ = run_validate(draft, make_source(1))
        self.assertNotEqual(code, 0)
        self.assertIn("⚠NG", content)

    def test_fullwidth_compatibility_tag_is_still_parsed_correctly(self):
        # タグの全角丸括弧はそのまま、本文側に全角英数字(互換文字)を
        # 含めても正しく検査できる(NFKC正規化で本文チェックが壊れない)。
        tag = "【異世界ニホン・国法】"
        body = "テスト本文(ABC１２３)。"
        draft = make_draft(1, bodies=[body], tags=[tag])
        code, content, _, _ = run_validate(draft, make_source(1))
        self.assertEqual(code, 0, content)

    def test_halfwidth_katakana_party_name_is_detected_via_nfkc(self):
        # 半角カナの「ｼﾞﾐﾝ党」はNFKC正規化で「ジミン党」になる。
        # 正規化なしでは FORBIDDEN_PARTY_KATAKANA と文字列一致しないため、
        # NFKC正規化が実際に効いていることを直接証明するテスト。
        body = "ｼﾞﾐﾝ党が勝利した。"
        draft = make_draft(1, bodies=[body])
        code, content, _, _ = run_validate(draft, make_source(1))
        self.assertNotEqual(code, 0)
        self.assertIn("⚠NG", content)
        self.assertIn("政党名カタカナ変換", content)

    def test_output_file_preserves_original_text_unnormalized(self):
        # 検査は正規化済み文字列で行うが、ファイルへ書き戻す本文は
        # 元の(正規化前の)文字列のままである(下書き自体は書き換えない)。
        body = "中央評議会の王​国議会でクエストが進む。"  # 王<ZWSP>国議会
        draft = make_draft(1, bodies=[body])
        code, content, _, _ = run_validate(draft, make_source(1))
        self.assertNotEqual(code, 0)
        # 元のゼロ幅文字入り文字列がそのまま本文に残っている
        # (正規化後の「王国議会」に書き換えられていない)。
        self.assertIn("王​国議会", content)


class OneToOneCorrespondenceTest(unittest.TestCase):
    def test_fewer_drafts_than_articles_fails(self):
        draft = make_draft(9)
        code, _, _, stderr = run_validate(draft, make_source(10))
        self.assertNotEqual(code, 0)
        self.assertIn("下書き件数", stderr)

    def test_equal_count_but_one_duplicate_and_one_missing_link_fails(self):
        links = [f"http://example.com/{i}" for i in range(10)]
        links[9] = links[0]  # 9番目を0番目と重複させる(本来の9番目は欠落する)
        draft = make_draft(10, links=links)
        code, content, _, stderr = run_validate(draft, make_source(10))
        self.assertNotEqual(code, 0)
        # 重複は下書きの見出しにNGとして現れる
        self.assertIn("⚠NG", content)
        self.assertIn("他の下書きと重複", content)
        # 欠落は入力記事側のリンクがどれも使われていないため、
        # ファイルレベルのエラーとしてstderrに現れる
        self.assertIn("使われていません", stderr)
        self.assertIn("http://example.com/9", stderr)

    def test_duplicate_link_within_single_draft_fails(self):
        # 同じ下書きの中で同一URLを2回書いた場合も重複として検出する
        # (下書き間だけでなく、1下書き内の重複も許さない)。
        body = (
            "テスト本文。\n"
            "http://example.com/0"
        )
        draft = make_draft(1, bodies=[body])
        code, content, _, _ = run_validate(draft, make_source(1))
        self.assertNotEqual(code, 0)
        self.assertIn("⚠NG", content)
        self.assertIn("他の下書きと重複", content)

    def test_unrelated_link_fails(self):
        draft = make_draft(1, links=["http://example.com/not-in-source"])
        code, content, _, stderr = run_validate(draft, make_source(1))
        self.assertNotEqual(code, 0)
        self.assertIn("⚠NG", content)
        self.assertIn("入力JSONのlinkと一致しない", content)
        # 入力側の唯一のリンクも使われていないため、こちらも欠落として現れる
        self.assertIn("使われていません", stderr)

    def test_exact_one_to_one_passes(self):
        draft = make_draft(3)
        code, content, _, _ = run_validate(draft, make_source(3))
        self.assertEqual(code, 0, content)


if __name__ == "__main__":
    unittest.main()
