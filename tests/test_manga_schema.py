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
        make_panel(4, expression="speaking-normal"),
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

    def test_non_iso8601_created_at_rejected(self):
        for bad_value in ["later", "2026-07-19", "2026/07/19 09:00:00", ""]:
            with self.subTest(bad_value=bad_value):
                reasons = ms.validate_packet(make_packet(created_at=bad_value))
                self.assertTrue(any("created_at" in r for r in reasons))

    def test_iso8601_created_at_with_offset_and_z_accepted(self):
        for good_value in ["2026-07-19T09:00:00+09:00", "2026-07-19T00:00:00Z", "2026-07-19T09:00:00.123+09:00"]:
            with self.subTest(good_value=good_value):
                reasons = ms.validate_packet(make_packet(created_at=good_value))
                self.assertFalse(any("created_at" in r for r in reasons))

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

    def test_bool_panel_no_rejected_even_though_equal_to_int(self):
        # bool は int のサブクラスであり True == 1 が成立するため、
        # panel_no: true を1として誤って通してしまわないことを確認する
        # (Codexレビュー指摘)。
        panel = make_panel(1)
        panel["panel_no"] = True
        reasons = ms.validate_panel(panel, 0)
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

    def test_all_standard_base_tags_with_all_standard_intensities_accepted(self):
        for base in ms.EXPRESSION_STANDARD_INTENSITY_BASE_TAGS:
            for intensity in ms.EXPRESSION_STANDARD_INTENSITIES:
                tag = f"{base}-{intensity}"
                with self.subTest(tag=tag):
                    panel = make_panel(1, expression=tag)
                    self.assertEqual(ms.validate_panel(panel, 0), [])

    def test_intensity_suffix_on_neutral_rejected(self):
        panel = make_panel(1, expression="neutral-medium")
        reasons = ms.validate_panel(panel, 0)
        self.assertTrue(any("expression" in r for r in reasons))

    def test_exact_tag_set_matches_confirmed_asset_scheme(self):
        # ハルト表情セットの実ファイル名体系(チャミによる実物検証済み):
        # 00: neutral / 01〜27: 9感情×weak/medium/strong /
        # 28〜30: speaking-small/normal/forceful。合計31種であることと、
        # 実装がこの厳密な集合と一致することを固定的に確認する
        # (実装内部の定数から機械的に生成しない、Codexレビュー指摘対応)。
        expected = {"neutral"}
        for base in [
            "joy", "surprise", "confusion", "worry", "anger",
            "sadness", "embarrassment", "determination", "tears",
        ]:
            for intensity in ["weak", "medium", "strong"]:
                expected.add(f"{base}-{intensity}")
        for intensity in ["small", "normal", "forceful"]:
            expected.add(f"speaking-{intensity}")

        self.assertEqual(len(expected), 31)
        self.assertEqual(ms.ALLOWED_EXPRESSION_TAGS, expected)

    def test_speaking_does_not_accept_standard_intensities(self):
        for intensity in ["weak", "medium", "strong"]:
            with self.subTest(intensity=intensity):
                panel = make_panel(1, expression=f"speaking-{intensity}")
                reasons = ms.validate_panel(panel, 0)
                self.assertTrue(any("expression" in r for r in reasons))

    def test_other_emotions_do_not_accept_speaking_intensities(self):
        for intensity in ["small", "normal", "forceful"]:
            with self.subTest(intensity=intensity):
                panel = make_panel(1, expression=f"joy-{intensity}")
                reasons = ms.validate_panel(panel, 0)
                self.assertTrue(any("expression" in r for r in reasons))

    def test_all_speaking_intensities_accepted(self):
        for intensity in ms.EXPRESSION_SPEAKING_INTENSITIES:
            tag = f"speaking-{intensity}"
            with self.subTest(tag=tag):
                panel = make_panel(1, expression=tag)
                self.assertEqual(ms.validate_panel(panel, 0), [])


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


class IsValidIso8601Test(unittest.TestCase):
    def test_valid_formats_accepted(self):
        for value in [
            "2026-07-19T09:00:00+09:00",
            "2026-07-19T00:00:00Z",
            "2026-07-19T09:00:00.5+09:00",
        ]:
            with self.subTest(value=value):
                self.assertTrue(ms.is_valid_iso8601(value))

    def test_invalid_formats_rejected(self):
        for value in ["2026-07-19", "later", "", None, 123, "2026-07-19 09:00:00+09:00"]:
            with self.subTest(value=value):
                self.assertFalse(ms.is_valid_iso8601(value))


class ReferenceImagesTest(unittest.TestCase):
    """panels[].reference_image(単数・既存)とreference_images(複数・新規)の
    排他ハンドリングを検証する(docs/manga-pipeline.md ChatGPTルート対応)。
    """

    def test_legacy_single_reference_image_still_passes(self):
        # 既存Packetとの後方互換の回帰確認。
        panel = make_panel(1)
        self.assertEqual(ms.validate_panel(panel, 0), [])

    def test_missing_both_forms_rejected(self):
        panel = make_panel(1)
        del panel["reference_image"]
        reasons = ms.validate_panel(panel, 0)
        self.assertTrue(any("reference_image" in r for r in reasons))

    def test_empty_single_reference_image_rejected(self):
        panel = make_panel(1, reference_image="")
        reasons = ms.validate_panel(panel, 0)
        self.assertTrue(any("reference_image" in r for r in reasons))

    def test_multi_reference_images_passes(self):
        panel = make_panel(1)
        del panel["reference_image"]
        panel["reference_images"] = {
            "ハルト": "haruto/surprise-medium.png",
            "ナツキ": "natsuki/neutral.png",
        }
        self.assertEqual(ms.validate_panel(panel, 0), [])

    def test_both_single_and_multi_specified_rejected(self):
        panel = make_panel(1)
        panel["reference_images"] = {"ハルト": "haruto/surprise-medium.png"}
        reasons = ms.validate_panel(panel, 0)
        self.assertTrue(
            any("reference_imageとreference_imagesを同時に指定できません" in r for r in reasons)
        )

    def test_empty_reference_images_dict_rejected(self):
        panel = make_panel(1)
        del panel["reference_image"]
        panel["reference_images"] = {}
        reasons = ms.validate_panel(panel, 0)
        self.assertTrue(any("reference_images" in r for r in reasons))

    def test_non_dict_reference_images_rejected(self):
        panel = make_panel(1)
        del panel["reference_image"]
        panel["reference_images"] = "haruto/surprise-medium.png"
        reasons = ms.validate_panel(panel, 0)
        self.assertTrue(any("reference_images" in r for r in reasons))

    def test_reference_images_disallowed_character_name_rejected(self):
        panel = make_panel(1)
        del panel["reference_image"]
        panel["reference_images"] = {"宰相タカイチ": "x.png"}
        reasons = ms.validate_panel(panel, 0)
        self.assertTrue(any("許可されていないキャラクター名" in r for r in reasons))

    def test_reference_images_all_five_allowed_names_individually_valid(self):
        for name in ms.ALLOWED_CHARACTERS:
            with self.subTest(name=name):
                panel = make_panel(1)
                del panel["reference_image"]
                panel["reference_images"] = {name: "x/y.png"}
                self.assertEqual(ms.validate_panel(panel, 0), [])

    def test_reference_images_empty_filename_value_rejected(self):
        panel = make_panel(1)
        del panel["reference_image"]
        panel["reference_images"] = {"ハルト": ""}
        reasons = ms.validate_panel(panel, 0)
        self.assertTrue(any("reference_images['ハルト']" in r for r in reasons))

    def test_reference_images_non_string_filename_value_rejected(self):
        panel = make_panel(1)
        del panel["reference_image"]
        panel["reference_images"] = {"ハルト": 123}
        reasons = ms.validate_panel(panel, 0)
        self.assertTrue(any("reference_images['ハルト']" in r for r in reasons))


class PanelRoleTest(unittest.TestCase):
    """panels[].role(任意フィールド)を検証する。"""

    def test_role_absent_still_passes(self):
        panel = make_panel(1)
        self.assertEqual(ms.validate_panel(panel, 0), [])

    def test_role_non_empty_string_passes(self):
        panel = make_panel(1, role="introduction")
        self.assertEqual(ms.validate_panel(panel, 0), [])

    def test_role_empty_string_rejected(self):
        panel = make_panel(1, role="")
        reasons = ms.validate_panel(panel, 0)
        self.assertTrue(any("role" in r for r in reasons))

    def test_role_non_string_rejected(self):
        panel = make_panel(1, role=123)
        reasons = ms.validate_panel(panel, 0)
        self.assertTrue(any("role" in r for r in reasons))


class SourceOptionalFieldsTest(unittest.TestCase):
    """source.decided/not_decided/next_step(任意フィールド)を検証する。"""

    def test_absent_optional_fields_still_pass(self):
        source = make_packet()["source"]
        self.assertEqual(ms.validate_source(source), [])

    def test_present_string_values_pass(self):
        source = make_packet()["source"]
        source["decided"] = "シュウギ院を通過した"
        source["not_decided"] = "サンギ院での審議結果"
        source["next_step"] = "サンギ院での審議"
        self.assertEqual(ms.validate_source(source), [])

    def test_present_empty_string_values_pass(self):
        # 該当情報がない項目を無理に埋める必要はないため、空文字列も許容する。
        source = make_packet()["source"]
        source["decided"] = ""
        self.assertEqual(ms.validate_source(source), [])

    def test_present_non_string_value_rejected(self):
        for field in ms.OPTIONAL_SOURCE_STR_FIELDS:
            with self.subTest(field=field):
                source = make_packet()["source"]
                source[field] = 123
                reasons = ms.validate_source(source)
                self.assertTrue(any(field in r for r in reasons))


if __name__ == "__main__":
    unittest.main()
