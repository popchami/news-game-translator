#!/usr/bin/env python3
"""scripts/manga_schema.py のテスト(異世界ニホン4コマ版 Phase 1)。

Manga News Packetの構造検証(packet_version・source・4コマ固定・
登場キャラクター(manga/characters.mdの5人のみ、最大3人)・表情タグ)を
検証する。Python標準ライブラリのみを使用する(unittest, pathlib, sys)。
"""
import copy
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import manga_schema as ms  # noqa: E402


def make_panel(panel_no=1, **overrides):
    panel = {
        "panel_no": panel_no,
        "scene": "掲示板前でハルトが掲示に気づく",
        "dialogue": "ハルト「おい見ろよ、これ!」",
        "expression": "surprise-medium",
        "background": "掲示板前の広場",
        "image_prompt": "young adventurer pointing at a bulletin board, anime style",
        "reference_image": "haruto/surprise-medium.png",
    }
    panel.update(overrides)
    return panel


def make_panels():
    return [
        make_panel(1, expression="neutral"),
        make_panel(2, expression="surprise-medium"),
        make_panel(3, expression="determination-strong"),
        make_panel(4, expression="speaking-weak"),
    ]


def make_packet(**overrides):
    packet = {
        "packet_version": 1,
        "created_at": "2026-07-19T09:00:00+09:00",
        "source": {
            "title": "「副首都」構想法案 衆議院を通過",
            "url": "https://example.com/articles/1",
            "summary": "大規模災害時の首都代替機能を担う法案が衆議院を通過した。",
        },
        "isekai_text": "中央評議会で「副首都」の国法がシュウギ院を通過した。",
        "scribe_note": "副首都構想の関連法案が衆議院本会議で可決された。",
        "characters": ["ハルト", "アキラ", "書記官"],
        "panels": make_panels(),
        "cautions": [],
    }
    packet.update(overrides)
    return packet


class ValidatePacketStructureTest(unittest.TestCase):
    def test_valid_packet_passes(self):
        self.assertEqual(ms.validate_packet(make_packet()), [])

    def test_non_dict_root_rejected(self):
        self.assertTrue(ms.validate_packet([]))
        self.assertTrue(ms.validate_packet("not a dict"))

    def test_wrong_packet_version_rejected(self):
        reasons = ms.validate_packet(make_packet(packet_version=2))
        self.assertTrue(any("packet_version" in r for r in reasons))

    def test_missing_created_at_rejected(self):
        packet = make_packet()
        del packet["created_at"]
        reasons = ms.validate_packet(packet)
        self.assertTrue(any("created_at" in r for r in reasons))

    def test_empty_isekai_text_rejected(self):
        reasons = ms.validate_packet(make_packet(isekai_text=""))
        self.assertTrue(any("isekai_text" in r for r in reasons))

    def test_empty_scribe_note_rejected(self):
        reasons = ms.validate_packet(make_packet(scribe_note=""))
        self.assertTrue(any("scribe_note" in r for r in reasons))

    def test_non_list_cautions_rejected(self):
        reasons = ms.validate_packet(make_packet(cautions="not-a-list"))
        self.assertTrue(any("cautions" in r for r in reasons))

    def test_cautions_with_non_string_element_rejected(self):
        reasons = ms.validate_packet(make_packet(cautions=[123]))
        self.assertTrue(any("cautions" in r for r in reasons))

    def test_empty_cautions_allowed(self):
        self.assertEqual(ms.validate_packet(make_packet(cautions=[])), [])


class ValidateSourceTest(unittest.TestCase):
    def test_valid_source_passes(self):
        self.assertEqual(ms.validate_source(make_packet()["source"]), [])

    def test_non_dict_source_rejected(self):
        self.assertTrue(ms.validate_source("not-a-dict"))

    def test_missing_required_field_rejected(self):
        for field in ms.REQUIRED_SOURCE_STR_FIELDS:
            with self.subTest(field=field):
                source = make_packet()["source"]
                del source[field]
                reasons = ms.validate_source(source)
                self.assertTrue(any(field in r for r in reasons))

    def test_empty_string_field_rejected(self):
        source = make_packet()["source"]
        source["title"] = ""
        reasons = ms.validate_source(source)
        self.assertTrue(any("title" in r for r in reasons))


class ValidateCharactersTest(unittest.TestCase):
    def test_allowed_characters_up_to_three_pass(self):
        self.assertEqual(ms.validate_characters(["ハルト", "ナツキ"]), [])
        self.assertEqual(ms.validate_characters(["ハルト", "ナツキ", "書記官"]), [])

    def test_all_five_allowed_names_individually_valid(self):
        for name in ms.ALLOWED_CHARACTERS:
            with self.subTest(name=name):
                self.assertEqual(ms.validate_characters([name]), [])

    def test_zero_characters_rejected(self):
        reasons = ms.validate_characters([])
        self.assertTrue(any("0人" in r for r in reasons))

    def test_more_than_three_rejected(self):
        reasons = ms.validate_characters(["ハルト", "ナツキ", "アキラ", "フユミ"])
        self.assertTrue(any("3人を超えています" in r for r in reasons))

    def test_disallowed_name_rejected(self):
        reasons = ms.validate_characters(["ハルト", "宰相タカイチ"])
        self.assertTrue(any("許可されていない名前" in r for r in reasons))

    def test_duplicate_name_rejected(self):
        reasons = ms.validate_characters(["ハルト", "ハルト"])
        self.assertTrue(any("重複" in r for r in reasons))

    def test_non_list_rejected(self):
        self.assertTrue(ms.validate_characters("ハルト"))

    def test_non_string_element_rejected(self):
        reasons = ms.validate_characters(["ハルト", 123])
        self.assertTrue(any("文字列ではありません" in r for r in reasons))


class ValidatePanelTest(unittest.TestCase):
    def test_valid_panel_passes(self):
        self.assertEqual(ms.validate_panel(make_panel(1), 0), [])

    def test_non_dict_panel_rejected(self):
        self.assertTrue(ms.validate_panel("not-a-dict", 0))

    def test_wrong_panel_no_rejected(self):
        reasons = ms.validate_panel(make_panel(panel_no=2), 0)
        self.assertTrue(any("panel_no" in r for r in reasons))

    def test_missing_required_field_rejected(self):
        for field in ms.REQUIRED_PANEL_STR_FIELDS:
            with self.subTest(field=field):
                panel = make_panel(1)
                del panel[field]
                reasons = ms.validate_panel(panel, 0)
                self.assertTrue(any(field in r for r in reasons))

    def test_empty_string_field_rejected(self):
        panel = make_panel(1, scene="")
        reasons = ms.validate_panel(panel, 0)
        self.assertTrue(any("scene" in r for r in reasons))

    def test_invalid_expression_tag_rejected(self):
        panel = make_panel(1, expression="happy")
        reasons = ms.validate_panel(panel, 0)
        self.assertTrue(any("expression" in r for r in reasons))

    def test_neutral_without_intensity_accepted(self):
        panel = make_panel(1, expression="neutral")
        self.assertEqual(ms.validate_panel(panel, 0), [])

    def test_all_base_tags_with_all_intensities_accepted(self):
        for base in ms.EXPRESSION_BASE_TAGS_WITH_INTENSITY:
            for intensity in ms.EXPRESSION_INTENSITIES:
                tag = f"{base}-{intensity}"
                with self.subTest(tag=tag):
                    panel = make_panel(1, expression=tag)
                    self.assertEqual(ms.validate_panel(panel, 0), [])

    def test_intensity_suffix_on_neutral_rejected(self):
        panel = make_panel(1, expression="neutral-medium")
        reasons = ms.validate_panel(panel, 0)
        self.assertTrue(any("expression" in r for r in reasons))


class PanelCountTest(unittest.TestCase):
    def test_exactly_four_panels_required(self):
        self.assertEqual(ms.validate_packet(make_packet()), [])

    def test_three_panels_rejected(self):
        packet = make_packet(panels=make_panels()[:3])
        reasons = ms.validate_packet(packet)
        self.assertTrue(any("4要素である必要があります" in r for r in reasons))

    def test_five_panels_rejected(self):
        panels = make_panels() + [make_panel(5)]
        packet = make_packet(panels=panels)
        reasons = ms.validate_packet(packet)
        self.assertTrue(any("4要素である必要があります" in r for r in reasons))

    def test_non_list_panels_rejected(self):
        packet = make_packet(panels="not-a-list")
        reasons = ms.validate_packet(packet)
        self.assertTrue(any("panelsが配列ではありません" in r for r in reasons))


class ExampleFileTest(unittest.TestCase):
    """data/state/manga_packet.example.json がスキーマを通ることを確認する。"""

    def test_example_packet_passes_validation(self):
        example_path = ROOT / "data" / "state" / "manga_packet.example.json"
        with example_path.open(encoding="utf-8") as f:
            packet = json.load(f)
        self.assertEqual(ms.validate_packet(packet), [])

    def test_example_packet_not_mutated_by_validation(self):
        example_path = ROOT / "data" / "state" / "manga_packet.example.json"
        with example_path.open(encoding="utf-8") as f:
            packet = json.load(f)
        before = copy.deepcopy(packet)
        ms.validate_packet(packet)
        self.assertEqual(packet, before)


if __name__ == "__main__":
    unittest.main()
