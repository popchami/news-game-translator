#!/usr/bin/env python3
"""scripts/validate_manga.py のテスト(異世界ニホン4コマ版 Phase 1)。

manga_schema.pyの構造検証(4コマ固定・登場キャラ<=3人等)に加え、
scripts/banned_terms.pyの禁止語検証(法案・選挙の文脈語、政党名
カタカナ化、ニホンに実在しない王制表現)がPacket内の日本語テキスト
全体に対して行われることを検証する。Python標準ライブラリのみを使用する
(unittest, pathlib, sys)。
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import validate_manga as vm  # noqa: E402

from test_manga_schema import make_packet, make_panel, make_panels  # noqa: E402


class ValidateMangaPacketStructureTest(unittest.TestCase):
    """manga_schema.pyの構造検証がvalidate_manga_packet経由でも効くことを確認する。"""

    def test_valid_packet_passes(self):
        self.assertEqual(vm.validate_manga_packet(make_packet()), [])

    def test_panel_count_not_four_rejected(self):
        packet = make_packet(panels=make_panels()[:3])
        reasons = vm.validate_manga_packet(packet)
        self.assertTrue(any("4要素である必要があります" in r for r in reasons))

    def test_more_than_three_characters_rejected(self):
        packet = make_packet(characters=["ハルト", "ナツキ", "アキラ", "フユミ"])
        reasons = vm.validate_manga_packet(packet)
        self.assertTrue(any("3人を超えています" in r for r in reasons))


class ContextualForbiddenTermTest(unittest.TestCase):
    def test_quest_terms_with_bill_context_rejected(self):
        packet = make_packet(scribe_note="この法案はクエスト受注として扱われる。")
        reasons = vm.validate_manga_packet(packet)
        self.assertTrue(any("クエスト受注" in r for r in reasons))

    def test_quest_terms_without_context_marker_allowed(self):
        # 文脈マーカー(法案・国法・審議等)が共起しない場合はNGにしない
        # (既存のscripts/validate.pyと同じ設計)。Packet全体のテキストに
        # 文脈マーカーが一切含まれないよう、isekai_text・scribe_noteとも
        # 上書きする(デフォルトのisekai_textには「国法」が含まれるため)。
        packet = make_packet(
            isekai_text="ハルトは今日も元気に街を歩いていた。",
            scribe_note="今日のクエスト受注は好調だった。",
        )
        reasons = vm.validate_manga_packet(packet)
        self.assertFalse(any("クエスト受注" in r for r in reasons))

    def test_election_battle_terms_with_context_rejected(self):
        packet = make_packet(isekai_text="今回の選抜戦で議席が決まる。")
        reasons = vm.validate_manga_packet(packet)
        self.assertTrue(any("選抜戦" in r for r in reasons))

    def test_forbidden_term_detected_in_panel_dialogue(self):
        panels = make_panels()
        panels[0] = make_panel(1, dialogue="ハルト「この法案はクエスト受注だ!」")
        packet = make_packet(panels=panels)
        reasons = vm.validate_manga_packet(packet)
        self.assertTrue(any("クエスト受注" in r for r in reasons))


class PartyKatakanaTest(unittest.TestCase):
    def test_party_katakana_rejected(self):
        packet = make_packet(scribe_note="ジミン党が法案を提出した。")
        reasons = vm.validate_manga_packet(packet)
        self.assertTrue(any("ジミン党" in r for r in reasons))

    def test_real_party_name_allowed(self):
        packet = make_packet(scribe_note="自民党が法案を提出した。")
        reasons = vm.validate_manga_packet(packet)
        self.assertEqual(reasons, [])


class KingdomTermTest(unittest.TestCase):
    def test_nihon_kingdom_term_absent_from_source_rejected(self):
        packet = make_packet(scribe_note="これはニホン王国の方針である。")
        reasons = vm.validate_manga_packet(packet)
        self.assertTrue(any("ニホン王国" in r for r in reasons))

    def test_nihon_kingdom_term_present_in_source_allowed(self):
        packet = make_packet(
            source={
                "title": "ニホン王国という表現についての報道",
                "url": "https://example.com/1",
                "summary": "ニホン王国という古い呼称が話題になった。",
            },
            scribe_note="かつて「ニホン王国」と呼ばれた時代があった。",
        )
        reasons = vm.validate_manga_packet(packet)
        self.assertFalse(any("ニホン王国" in r for r in reasons))

    def test_real_royalty_term_from_source_allowed(self):
        # 皇室典範上の正式な身位語は、入力(source)に存在すれば禁止しない
        # (scripts/banned_terms.pyの設計を継承)。
        packet = make_packet(
            source={
                "title": "英国王が来日",
                "url": "https://example.com/2",
                "summary": "英国国王が来日し、歓迎行事が開かれた。",
            },
            scribe_note="英国国王が来日し、歓迎行事が開かれた。",
        )
        reasons = vm.validate_manga_packet(packet)
        self.assertEqual(reasons, [])

    def test_nihon_no_joou_fabrication_rejected_even_if_source_has_unrelated_royalty_word(self):
        packet = make_packet(
            source={
                "title": "英国王が来日",
                "url": "https://example.com/3",
                "summary": "英国国王が来日した。",
            },
            scribe_note="ニホンの女王が統治しているという設定にした。",
        )
        reasons = vm.validate_manga_packet(packet)
        self.assertTrue(any("ニホンの女王" in r for r in reasons))


class BuildTextBlobTest(unittest.TestCase):
    def test_packet_text_blob_includes_all_panel_fields(self):
        panels = make_panels()
        panels[0] = make_panel(1, scene="固有シーン語", dialogue="固有セリフ語", background="固有背景語")
        packet = make_packet(panels=panels)
        blob = vm.build_packet_text_blob(packet)
        self.assertIn("固有シーン語", blob)
        self.assertIn("固有セリフ語", blob)
        self.assertIn("固有背景語", blob)

    def test_source_text_blob_includes_title_and_summary(self):
        source = {"title": "固有タイトル語", "url": "https://example.com/x", "summary": "固有要約語"}
        blob = vm.build_source_text_blob(source)
        self.assertIn("固有タイトル語", blob)
        self.assertIn("固有要約語", blob)


if __name__ == "__main__":
    unittest.main()
