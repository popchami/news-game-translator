#!/usr/bin/env python3
"""scripts/manga_schema.py のテスト(異世界ニホン X用5コマ構成 Packet v2)。

Manga News Packetの構造検証(packet_version・source・4コマ固定・
登場キャラクター(書記官必須+物語側2〜3人)・performers/dialogues・
scribe_panel・画角/フレーミングの多様性等)を検証する。Python標準
ライブラリのみを使用する(unittest, copy, json, pathlib, sys)。
"""
import copy
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import manga_schema as ms  # noqa: E402


def make_performer(name="ハルト", **overrides):
    ref_id = ms.CHARACTER_REFERENCE_ID[name]
    performer = {
        "name": name,
        "position": "left",
        "facing": "three_quarter_right",
        "gaze": "object",
        "expression": "neutral",
        "reference_image": f"{ref_id}/neutral.png",
    }
    performer.update(overrides)
    return performer


def make_dialogue(speaker="ハルト", text="おい見ろよ、これ", bubble_position="upper_left", **overrides):
    dialogue = {"speaker": speaker, "text": text, "bubble_position": bubble_position}
    dialogue.update(overrides)
    return dialogue


def make_panel(panel_no=1, **overrides):
    role = ms.ROLE_BY_PANEL_NO[panel_no]
    panel = {
        "panel_no": panel_no,
        "role": role,
        "scene": "掲示板前でハルトが掲示に気づく",
        "background": "掲示板前の広場",
        "framing": "waist",
        "camera_angle": "eye_level",
        "image_prompt": "young adventurer pointing at a bulletin board, anime style",
        "negative_prompt": "text, speech bubble, japanese characters, onomatopoeia, panel border",
        "performers": [make_performer("ハルト")],
        "dialogues": [make_dialogue()],
    }
    panel.update(overrides)
    return panel


def make_panels():
    return [
        make_panel(1, framing="waist", camera_angle="eye_level"),
        make_panel(2, framing="bust", camera_angle="eye_level"),
        make_panel(3, framing="close_up", camera_angle="low_angle"),
        make_panel(4, framing="wide", camera_angle="eye_level"),
    ]


def make_scribe_panel(**overrides):
    scribe_panel = {
        "layout": ms.SCRIBE_PANEL_LAYOUT,
        "expression": "neutral",
        "reference_image": "scribe/neutral.png",
        "emblem_reference": ms.SCRIBE_EMBLEM_REFERENCE,
    }
    scribe_panel.update(overrides)
    return scribe_panel


def make_packet(**overrides):
    packet = {
        "packet_version": 2,
        "created_at": "2026-07-19T09:00:00+09:00",
        "source": {
            "title": "「副首都」構想法案 衆議院を通過",
            "url": "https://example.com/articles/1",
            "summary": "大規模災害時の首都代替機能を担う法案が衆議院を通過した。",
        },
        "isekai_text": "中央評議会で「副首都」の国法がシュウギ院を通過した。",
        "scribe_note": "副首都構想の関連法案が\n衆議院本会議で可決された。",
        "characters": ["ハルト", "ナツキ", "書記官"],
        "panels": make_panels(),
        "scribe_panel": make_scribe_panel(),
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
        reasons = ms.validate_packet(make_packet(packet_version=1))
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


class SourceOptionalFieldsTest(unittest.TestCase):
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


class ExpressionTagTest(unittest.TestCase):
    def test_exact_tag_set_matches_confirmed_asset_scheme(self):
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


class ValidateCharactersTest(unittest.TestCase):
    def test_two_story_plus_scribe_passes(self):
        self.assertEqual(ms.validate_characters(["ハルト", "ナツキ", "書記官"]), [])

    def test_three_story_plus_scribe_passes(self):
        self.assertEqual(ms.validate_characters(["ハルト", "ナツキ", "アキラ", "書記官"]), [])

    def test_scribe_missing_rejected(self):
        reasons = ms.validate_characters(["ハルト", "ナツキ"])
        self.assertTrue(any("書記官" in r and "含まれていません" in r for r in reasons))

    def test_more_than_four_total_rejected(self):
        reasons = ms.validate_characters(["ハルト", "ナツキ", "アキラ", "フユミ", "書記官"])
        self.assertTrue(any("4人を超えています" in r for r in reasons))

    def test_story_count_below_two_rejected(self):
        reasons = ms.validate_characters(["ハルト", "書記官"])
        self.assertTrue(any("2人未満です" in r for r in reasons))

    def test_story_count_above_three_rejected(self):
        reasons = ms.validate_characters(["ハルト", "ナツキ", "アキラ", "フユミ", "書記官", "書記官"])
        # 6要素は4人上限違反でも報告されるが、重複書記官のケースも別途検出する
        self.assertTrue(any("重複" in r for r in reasons))

    def test_disallowed_name_rejected(self):
        reasons = ms.validate_characters(["ハルト", "書記官", "宰相タカイチ"])
        self.assertTrue(any("許可されていない名前" in r for r in reasons))

    def test_duplicate_story_name_rejected(self):
        reasons = ms.validate_characters(["ハルト", "ハルト", "ナツキ", "書記官"])
        self.assertTrue(any("重複" in r for r in reasons))

    def test_non_list_rejected(self):
        self.assertTrue(ms.validate_characters("ハルト"))

    def test_non_string_element_rejected(self):
        reasons = ms.validate_characters(["ハルト", 123, "書記官"])
        self.assertTrue(any("文字列ではありません" in r for r in reasons))

    def test_all_four_story_characters_individually_combinable(self):
        for name in ms.STORY_CHARACTERS:
            with self.subTest(name=name):
                other = [n for n in ms.STORY_CHARACTERS if n != name][0]
                self.assertEqual(ms.validate_characters([name, other, "書記官"]), [])


class ValidatePerformerTest(unittest.TestCase):
    def test_valid_performer_passes(self):
        characters = ["ハルト", "ナツキ", "書記官"]
        self.assertEqual(ms.validate_performer(make_performer("ハルト"), 0, 0, characters), [])

    def test_non_dict_performer_rejected(self):
        self.assertTrue(ms.validate_performer("not-a-dict", 0, 0, []))

    def test_scribe_name_rejected_in_panel(self):
        performer = make_performer("書記官")
        reasons = ms.validate_performer(performer, 0, 0, ["ハルト", "ナツキ", "書記官"])
        self.assertTrue(any("書記官" in r and "登場させることはできません" in r for r in reasons))

    def test_name_not_in_characters_rejected(self):
        performer = make_performer("アキラ")
        reasons = ms.validate_performer(performer, 0, 0, ["ハルト", "ナツキ", "書記官"])
        self.assertTrue(any("charactersに存在しません" in r for r in reasons))

    def test_invalid_position_rejected(self):
        performer = make_performer("ハルト", position="top")
        reasons = ms.validate_performer(performer, 0, 0, ["ハルト", "ナツキ", "書記官"])
        self.assertTrue(any("position" in r for r in reasons))

    def test_invalid_facing_rejected(self):
        performer = make_performer("ハルト", facing="sideways")
        reasons = ms.validate_performer(performer, 0, 0, ["ハルト", "ナツキ", "書記官"])
        self.assertTrue(any("facing" in r for r in reasons))

    def test_invalid_gaze_rejected(self):
        performer = make_performer("ハルト", gaze="ceiling")
        reasons = ms.validate_performer(performer, 0, 0, ["ハルト", "ナツキ", "書記官"])
        self.assertTrue(any("gaze" in r for r in reasons))

    def test_invalid_expression_rejected(self):
        performer = make_performer("ハルト", expression="happy")
        reasons = ms.validate_performer(performer, 0, 0, ["ハルト", "ナツキ", "書記官"])
        self.assertTrue(any("expression" in r for r in reasons))

    def test_reference_image_tag_mismatch_rejected(self):
        performer = make_performer("ハルト", expression="joy-medium", reference_image="haruto/neutral.png")
        reasons = ms.validate_performer(performer, 0, 0, ["ハルト", "ナツキ", "書記官"])
        self.assertTrue(any("タグがexpressionと一致しません" in r for r in reasons))

    def test_reference_image_character_mismatch_rejected(self):
        performer = make_performer("ハルト", reference_image="natsuki/neutral.png")
        reasons = ms.validate_performer(performer, 0, 0, ["ハルト", "ナツキ", "書記官"])
        self.assertTrue(any("character部分が一致しません" in r for r in reasons))

    def test_all_story_characters_correct_reference_image_pairing_passes(self):
        # 物語側4人(ハルト・ナツキ・アキラ・フユミ)それぞれについて、日本語名と
        # 正しいローマ字ID(CHARACTER_REFERENCE_ID)の組み合わせが通ることを確認する。
        for name in ms.STORY_CHARACTERS:
            with self.subTest(name=name):
                performer = make_performer(name)
                characters = list({name, "書記官"})
                self.assertEqual(ms.validate_performer(performer, 0, 0, characters), [])

    def test_every_other_characters_reference_image_rejected(self):
        # 5人全員の組み合わせについて、自分以外のローマ字IDを指定した場合は
        # すべて拒否されることを確認する(取り違えを網羅的に検出)。
        for name in ms.ALLOWED_CHARACTERS:
            for other_name in ms.ALLOWED_CHARACTERS:
                if other_name == name or name == ms.SCRIBE_CHARACTER:
                    continue
                with self.subTest(name=name, other_name=other_name):
                    wrong_id = ms.CHARACTER_REFERENCE_ID[other_name]
                    performer = make_performer(name, reference_image=f"{wrong_id}/neutral.png")
                    characters = list({name, "書記官"})
                    reasons = ms.validate_performer(performer, 0, 0, characters)
                    self.assertTrue(any("character部分が一致しません" in r for r in reasons))

    def test_all_positions_facings_gazes_individually_valid(self):
        for position in ms.POSITIONS:
            for facing in ms.FACINGS:
                for gaze in ms.GAZES:
                    with self.subTest(position=position, facing=facing, gaze=gaze):
                        performer = make_performer("ハルト", position=position, facing=facing, gaze=gaze)
                        self.assertEqual(
                            ms.validate_performer(performer, 0, 0, ["ハルト", "ナツキ", "書記官"]), []
                        )


class ValidateDialogueTest(unittest.TestCase):
    def test_valid_dialogue_passes(self):
        self.assertEqual(ms.validate_dialogue(make_dialogue(), 0, 0, ["ハルト"]), [])

    def test_non_dict_dialogue_rejected(self):
        self.assertTrue(ms.validate_dialogue("not-a-dict", 0, 0, ["ハルト"]))

    def test_speaker_not_a_performer_rejected(self):
        dialogue = make_dialogue(speaker="ナツキ")
        reasons = ms.validate_dialogue(dialogue, 0, 0, ["ハルト"])
        self.assertTrue(any("speaker" in r and "存在しません" in r for r in reasons))

    def test_empty_text_rejected(self):
        dialogue = make_dialogue(text="")
        reasons = ms.validate_dialogue(dialogue, 0, 0, ["ハルト"])
        self.assertTrue(any("text" in r for r in reasons))

    def test_ellipsis_only_text_rejected(self):
        for bad_text in ["……", "…", "・・・", "...", "…\n…"]:
            with self.subTest(bad_text=bad_text):
                dialogue = make_dialogue(text=bad_text)
                reasons = ms.validate_dialogue(dialogue, 0, 0, ["ハルト"])
                self.assertTrue(any("三点リーダー" in r for r in reasons))

    def test_text_over_24_chars_rejected(self):
        dialogue = make_dialogue(text="あ" * 25)
        reasons = ms.validate_dialogue(dialogue, 0, 0, ["ハルト"])
        self.assertTrue(any("24文字を超えています" in r for r in reasons))

    def test_text_exactly_24_chars_passes(self):
        dialogue = make_dialogue(text=("あ" * 12) + "\n" + ("い" * 12))
        self.assertEqual(ms.validate_dialogue(dialogue, 0, 0, ["ハルト"]), [])

    def test_line_over_12_chars_rejected(self):
        dialogue = make_dialogue(text="あ" * 13)
        reasons = ms.validate_dialogue(dialogue, 0, 0, ["ハルト"])
        self.assertTrue(any("12文字を超えています" in r for r in reasons))

    def test_more_than_2_lines_rejected(self):
        dialogue = make_dialogue(text="あ\nい\nう")
        reasons = ms.validate_dialogue(dialogue, 0, 0, ["ハルト"])
        self.assertTrue(any("2行を超えています" in r for r in reasons))

    def test_invalid_bubble_position_rejected(self):
        dialogue = make_dialogue(bubble_position="top")
        reasons = ms.validate_dialogue(dialogue, 0, 0, ["ハルト"])
        self.assertTrue(any("bubble_position" in r for r in reasons))

    def test_empty_bubble_position_rejected(self):
        dialogue = make_dialogue(bubble_position="")
        reasons = ms.validate_dialogue(dialogue, 0, 0, ["ハルト"])
        self.assertTrue(any("bubble_position" in r for r in reasons))

    def test_all_six_bubble_positions_individually_valid(self):
        self.assertEqual(
            set(ms.BUBBLE_POSITIONS),
            {"upper_left", "upper_center", "upper_right", "lower_left", "lower_center", "lower_right"},
        )
        for bubble_position in ms.BUBBLE_POSITIONS:
            with self.subTest(bubble_position=bubble_position):
                dialogue = make_dialogue(bubble_position=bubble_position)
                self.assertEqual(ms.validate_dialogue(dialogue, 0, 0, ["ハルト"]), [])

    def test_bubble_position_does_not_share_enum_with_performer_position(self):
        # performer.position(left/center/right)とbubble_position(upper_*/
        # lower_*)は別概念であり、performer.positionの値をbubble_positionへ
        # そのまま使うと拒否されることを確認する。
        for value in ms.POSITIONS:
            with self.subTest(value=value):
                dialogue = make_dialogue(bubble_position=value)
                reasons = ms.validate_dialogue(dialogue, 0, 0, ["ハルト"])
                self.assertTrue(any("bubble_position" in r for r in reasons))


class ValidatePanelTest(unittest.TestCase):
    def test_valid_panel_passes(self):
        characters = ["ハルト", "ナツキ", "書記官"]
        self.assertEqual(ms.validate_panel(make_panel(1), 0, characters), [])

    def test_non_dict_panel_rejected(self):
        self.assertTrue(ms.validate_panel("not-a-dict", 0, []))

    def test_wrong_panel_no_rejected(self):
        panel = make_panel(1)
        panel["panel_no"] = 2
        reasons = ms.validate_panel(panel, 0, [])
        self.assertTrue(any("panel_no" in r for r in reasons))

    def test_bool_panel_no_rejected_even_though_equal_to_int(self):
        panel = make_panel(1)
        panel["panel_no"] = True
        reasons = ms.validate_panel(panel, 0, [])
        self.assertTrue(any("panel_no" in r for r in reasons))

    def test_role_mismatch_with_panel_no_rejected(self):
        panel = make_panel(1)
        panel["role"] = "development"
        reasons = ms.validate_panel(panel, 0, [])
        self.assertTrue(any("roleがpanel_noと一致しません" in r for r in reasons))

    def test_invalid_role_value_rejected(self):
        panel = make_panel(1)
        panel["role"] = "climax"
        reasons = ms.validate_panel(panel, 0, [])
        self.assertTrue(any("roleが不正です" in r for r in reasons))

    def test_missing_required_field_rejected(self):
        for field in ms.REQUIRED_PANEL_STR_FIELDS:
            with self.subTest(field=field):
                panel = make_panel(1)
                del panel[field]
                reasons = ms.validate_panel(panel, 0, [])
                self.assertTrue(any(field in r for r in reasons))

    def test_empty_string_field_rejected(self):
        panel = make_panel(1, scene="")
        reasons = ms.validate_panel(panel, 0, [])
        self.assertTrue(any("scene" in r for r in reasons))

    def test_invalid_framing_rejected(self):
        panel = make_panel(1, framing="extreme")
        reasons = ms.validate_panel(panel, 0, [])
        self.assertTrue(any("framing" in r for r in reasons))

    def test_all_framings_individually_valid(self):
        for framing in ms.FRAMINGS:
            with self.subTest(framing=framing):
                panel = make_panel(1, framing=framing)
                self.assertEqual(ms.validate_panel(panel, 0, ["ハルト"]), [])

    def test_all_five_camera_angles_individually_valid(self):
        self.assertEqual(
            set(ms.CAMERA_ANGLES),
            {"eye_level", "high_angle", "low_angle", "over_shoulder", "top_down"},
        )
        for camera_angle in ms.CAMERA_ANGLES:
            with self.subTest(camera_angle=camera_angle):
                panel = make_panel(1, camera_angle=camera_angle)
                self.assertEqual(ms.validate_panel(panel, 0, ["ハルト"]), [])

    def test_unknown_camera_angle_rejected(self):
        panel = make_panel(1, camera_angle="dutch_angle")
        reasons = ms.validate_panel(panel, 0, [])
        self.assertTrue(any("camera_angle" in r for r in reasons))

    def test_empty_camera_angle_rejected(self):
        panel = make_panel(1, camera_angle="")
        reasons = ms.validate_panel(panel, 0, [])
        self.assertTrue(any("camera_angle" in r for r in reasons))

    def test_camera_angle_wording_variants_rejected_without_normalization(self):
        # 表記揺れ("eye level"、"eye-level"、"normal angle"、"standard angle"等)を
        # 自動補正せず、固定enum外として明確に拒否することを確認する
        # (自由記述だと表記揺れで連続構図の検証を回避できてしまうため)。
        for bad_value in ["eye level", "eye-level", "Eye_Level", "EYE_LEVEL", "normal angle", "standard angle"]:
            with self.subTest(bad_value=bad_value):
                panel = make_panel(1, camera_angle=bad_value)
                reasons = ms.validate_panel(panel, 0, [])
                self.assertTrue(any("camera_angle" in r for r in reasons))

    def test_caption_absent_passes(self):
        panel = make_panel(1)
        self.assertEqual(ms.validate_panel(panel, 0, ["ハルト"]), [])

    def test_caption_within_limit_passes(self):
        panel = make_panel(1, caption="あ" * 16)
        self.assertEqual(ms.validate_panel(panel, 0, ["ハルト"]), [])

    def test_caption_over_16_chars_rejected(self):
        panel = make_panel(1, caption="あ" * 17)
        reasons = ms.validate_panel(panel, 0, ["ハルト"])
        self.assertTrue(any("caption" in r for r in reasons))

    def test_empty_performers_rejected(self):
        panel = make_panel(1, performers=[])
        reasons = ms.validate_panel(panel, 0, ["ハルト"])
        self.assertTrue(any("performers" in r for r in reasons))

    def test_three_performers_rejected(self):
        panel = make_panel(
            1,
            performers=[make_performer("ハルト"), make_performer("ナツキ"), make_performer("アキラ")],
        )
        reasons = ms.validate_panel(panel, 0, ["ハルト", "ナツキ", "アキラ", "書記官"])
        self.assertTrue(any("performersが" in r and "超えています" in r for r in reasons))

    def test_two_performers_passes(self):
        panel = make_panel(1, performers=[make_performer("ハルト"), make_performer("ナツキ")])
        self.assertEqual(ms.validate_panel(panel, 0, ["ハルト", "ナツキ", "書記官"]), [])

    def test_duplicate_performer_name_rejected(self):
        panel = make_panel(1, performers=[make_performer("ハルト"), make_performer("ハルト")])
        reasons = ms.validate_panel(panel, 0, ["ハルト", "書記官"])
        self.assertTrue(any("重複しています" in r for r in reasons))

    def test_empty_dialogues_rejected(self):
        panel = make_panel(1, dialogues=[])
        reasons = ms.validate_panel(panel, 0, ["ハルト"])
        self.assertTrue(any("dialogues" in r for r in reasons))

    def test_three_dialogues_rejected(self):
        panel = make_panel(
            1,
            performers=[make_performer("ハルト"), make_performer("ナツキ")],
            dialogues=[
                make_dialogue("ハルト", "あ", "upper_left"),
                make_dialogue("ナツキ", "い", "upper_right"),
                make_dialogue("ハルト", "う", "lower_center"),
            ],
        )
        reasons = ms.validate_panel(panel, 0, ["ハルト", "ナツキ", "書記官"])
        self.assertTrue(any("dialoguesが2個を超えています" in r for r in reasons))

    def test_duplicate_bubble_position_rejected(self):
        panel = make_panel(
            1,
            performers=[make_performer("ハルト"), make_performer("ナツキ")],
            dialogues=[
                make_dialogue("ハルト", "おはよう", "upper_left"),
                make_dialogue("ナツキ", "うん、そう", "upper_left"),
            ],
        )
        reasons = ms.validate_panel(panel, 0, ["ハルト", "ナツキ", "書記官"])
        self.assertTrue(any("bubble_positionが重複しています" in r for r in reasons))

    def test_bubble_position_differing_from_performer_position_still_passes(self):
        # bubble_position(吹き出し本体の位置)とperformer.position(人物の
        # 左右配置)は独立した概念であり、一致は要求しない。
        panel = make_panel(
            1,
            performers=[make_performer("ハルト", position="left")],
            dialogues=[make_dialogue("ハルト", "おはよう", "lower_right")],
        )
        self.assertEqual(ms.validate_panel(panel, 0, ["ハルト", "書記官"]), [])

    def test_panel_total_dialogue_chars_over_36_rejected(self):
        panel = make_panel(
            1,
            performers=[make_performer("ハルト"), make_performer("ナツキ")],
            dialogues=[
                make_dialogue("ハルト", "あ" * 24, "upper_left"),
                make_dialogue("ナツキ", "い" * 13, "upper_right"),
            ],
        )
        reasons = ms.validate_panel(panel, 0, ["ハルト", "ナツキ", "書記官"])
        self.assertTrue(any("36文字を超えています" in r for r in reasons))

    def test_panel_total_dialogue_chars_exactly_36_passes(self):
        panel = make_panel(
            1,
            performers=[make_performer("ハルト"), make_performer("ナツキ")],
            dialogues=[
                make_dialogue("ハルト", ("あ" * 12) + "\n" + ("あ" * 12), "upper_left"),
                make_dialogue("ナツキ", "い" * 12, "upper_right"),
            ],
        )
        self.assertEqual(ms.validate_panel(panel, 0, ["ハルト", "ナツキ", "書記官"]), [])


class PanelCountTest(unittest.TestCase):
    def test_exactly_four_panels_required(self):
        self.assertEqual(ms.validate_packet(make_packet()), [])

    def test_three_panels_rejected(self):
        packet = make_packet(panels=make_panels()[:3])
        reasons = ms.validate_packet(packet)
        self.assertTrue(any("4要素である必要があります" in r for r in reasons))

    def test_five_panels_rejected(self):
        extra = make_panel(4)
        extra["panel_no"] = 5
        panels = make_panels() + [extra]
        packet = make_packet(panels=panels)
        reasons = ms.validate_packet(packet)
        self.assertTrue(any("4要素である必要があります" in r for r in reasons))

    def test_non_list_panels_rejected(self):
        packet = make_packet(panels="not-a-list")
        reasons = ms.validate_packet(packet)
        self.assertTrue(any("panelsが配列ではありません" in r for r in reasons))


class NoSilentPanelTest(unittest.TestCase):
    """無言コマ不採用の再確認。第1〜4コマすべてにdialogues(1〜2個、内容の
    あるセリフ)を必須とすることを、packet全体レベルで確認する。
    """

    def test_all_four_panels_have_non_empty_dialogues_in_valid_packet(self):
        packet = make_packet()
        for panel in packet["panels"]:
            self.assertGreaterEqual(len(panel["dialogues"]), 1)
            for dialogue in panel["dialogues"]:
                self.assertNotEqual(dialogue["text"], "")
        self.assertEqual(ms.validate_packet(packet), [])

    def test_empty_dialogues_array_rejected_for_each_panel(self):
        for index in range(ms.PANEL_COUNT):
            with self.subTest(panel_index=index):
                packet = make_packet()
                packet["panels"][index]["dialogues"] = []
                reasons = ms.validate_packet(packet)
                self.assertTrue(any("dialogues" in r for r in reasons))

    def test_symbol_only_dialogue_rejected_for_each_panel(self):
        for index in range(ms.PANEL_COUNT):
            with self.subTest(panel_index=index):
                packet = make_packet()
                packet["panels"][index]["dialogues"] = [make_dialogue(text="……")]
                reasons = ms.validate_packet(packet)
                self.assertTrue(any("三点リーダー" in r for r in reasons))

    def test_fifth_koma_uses_scribe_note_not_dialogues(self):
        # 第5コマ(scribe_panel)にdialoguesフィールドは存在しない
        # (scribe_noteを使う)。
        packet = make_packet()
        self.assertNotIn("dialogues", packet["scribe_panel"])


class ScribeExcludedFromPanelsTest(unittest.TestCase):
    def test_scribe_in_panel_performers_rejected(self):
        packet = make_packet()
        packet["panels"][0]["performers"] = [make_performer("書記官")]
        packet["panels"][0]["dialogues"] = [make_dialogue(speaker="書記官")]
        reasons = ms.validate_packet(packet)
        self.assertTrue(any("書記官" in r and "登場させることはできません" in r for r in reasons))


class PanelDiversityTest(unittest.TestCase):
    def test_consecutive_identical_camera_and_framing_rejected(self):
        panels = make_panels()
        panels[1]["framing"] = panels[0]["framing"]
        panels[1]["camera_angle"] = panels[0]["camera_angle"]
        packet = make_packet(panels=panels)
        reasons = ms.validate_packet(packet)
        self.assertTrue(any("同じ構図を使わない" in r for r in reasons))

    def test_fewer_than_three_distinct_combos_rejected(self):
        panels = make_panels()
        for panel in panels:
            panel["framing"] = "waist"
            panel["camera_angle"] = "eye_level"
        # 連続同一を避けるため2種類だけ交互にする(それでも3種類未満で拒否)
        panels[1]["framing"] = "bust"
        panels[3]["framing"] = "bust"
        packet = make_packet(panels=panels)
        reasons = ms.validate_packet(packet)
        self.assertTrue(any("3種類未満です" in r for r in reasons))

    def test_more_than_one_full_body_panel_rejected(self):
        panels = make_panels()
        panels[0]["framing"] = "full"
        panels[2]["framing"] = "full"
        packet = make_packet(panels=panels)
        reasons = ms.validate_packet(packet)
        self.assertTrue(any("全身構図" in r for r in reasons))

    def test_zero_full_body_panels_passes(self):
        # 既定のmake_packet()はframing="full"を1枚も使わない(0<=1)。
        packet = make_packet()
        reasons = ms.validate_packet(packet)
        self.assertEqual(reasons, [])

    def test_exactly_one_full_body_panel_passes(self):
        # Codexレビュー指摘(Minor): テスト名に反し、実際にはframing="full"の
        # コマが0枚だった。実際に1枚だけfullを含む構成で検証する。
        panels = make_panels()
        panels[0]["framing"] = "full"
        packet = make_packet(panels=panels)
        reasons = ms.validate_packet(packet)
        self.assertFalse(any("全身構図" in r for r in reasons))

    def test_same_camera_angle_different_framing_allowed_consecutive(self):
        # camera_angleだけが同じでもframingが異なれば連続を許可する。
        panels = make_panels()
        panels[1]["camera_angle"] = panels[0]["camera_angle"]
        # framingは元からwaist/bustで異なるため、この時点で(camera_angle,
        # framing)の組は同一ではない。
        self.assertNotEqual(panels[0]["framing"], panels[1]["framing"])
        packet = make_packet(panels=panels)
        reasons = ms.validate_packet(packet)
        self.assertFalse(any("同じ構図を使わない" in r for r in reasons))

    def test_same_framing_different_camera_angle_allowed_consecutive(self):
        # framingだけが同じでもcamera_angleが異なれば連続を許可する。
        panels = make_panels()
        panels[0]["framing"] = "waist"
        panels[1]["framing"] = "waist"
        panels[0]["camera_angle"] = "eye_level"
        panels[1]["camera_angle"] = "high_angle"
        packet = make_packet(panels=panels)
        reasons = ms.validate_packet(packet)
        self.assertFalse(any("同じ構図を使わない" in r for r in reasons))

    def test_four_distinct_combos_passes(self):
        packet = make_packet()  # make_panels()は4種類の(camera_angle, framing)を使う
        reasons = ms.validate_packet(packet)
        self.assertFalse(any("3種類未満です" in r for r in reasons))

    def test_exactly_three_distinct_combos_boundary_passes(self):
        # Codexレビュー指摘(Minor): 「3種類以上」の境界(ちょうど3種類)が
        # 未検証だった(既存テストは4種類を使っていた)。
        panels = make_panels()
        panels[0]["camera_angle"], panels[0]["framing"] = "eye_level", "waist"
        panels[1]["camera_angle"], panels[1]["framing"] = "eye_level", "bust"
        panels[2]["camera_angle"], panels[2]["framing"] = "low_angle", "close_up"
        panels[3]["camera_angle"], panels[3]["framing"] = "eye_level", "bust"
        packet = make_packet(panels=panels)
        reasons = ms.validate_packet(packet)
        self.assertFalse(any("3種類未満です" in r for r in reasons))


class ValidateScribePanelTest(unittest.TestCase):
    def test_valid_scribe_panel_passes(self):
        self.assertEqual(ms.validate_scribe_panel(make_scribe_panel()), [])

    def test_non_dict_rejected(self):
        self.assertTrue(ms.validate_scribe_panel("not-a-dict"))

    def test_wrong_layout_rejected(self):
        reasons = ms.validate_scribe_panel(make_scribe_panel(layout="note-left_scribe-right"))
        self.assertTrue(any("layout" in r for r in reasons))

    def test_invalid_expression_rejected(self):
        reasons = ms.validate_scribe_panel(make_scribe_panel(expression="happy"))
        self.assertTrue(any("expression" in r for r in reasons))

    def test_reference_image_tag_mismatch_rejected(self):
        reasons = ms.validate_scribe_panel(
            make_scribe_panel(expression="joy-medium", reference_image="scribe/neutral.png")
        )
        self.assertTrue(any("タグがexpressionと一致しません" in r for r in reasons))

    def test_wrong_emblem_reference_rejected(self):
        reasons = ms.validate_scribe_panel(make_scribe_panel(emblem_reference="scribe/equipment/other.png"))
        self.assertTrue(any("emblem_reference" in r for r in reasons))

    def test_missing_scribe_panel_rejected_at_packet_level(self):
        packet = make_packet()
        del packet["scribe_panel"]
        reasons = ms.validate_packet(packet)
        self.assertTrue(any("scribe_panel" in r for r in reasons))


class ScribeNoteTest(unittest.TestCase):
    def test_empty_scribe_note_rejected(self):
        reasons = ms.validate_packet(make_packet(scribe_note=""))
        self.assertTrue(any("scribe_note" in r for r in reasons))

    def test_whitespace_only_scribe_note_rejected(self):
        # Codexレビューで発見: 空白のみ("   ")は空文字列と等しくないため、
        # 非空チェックだけでは素通りしてしまっていた(2026-07-24修正)。
        for bad_value in ["   ", "\n\n\n", "　　"]:
            with self.subTest(bad_value=bad_value):
                reasons = ms.validate_packet(make_packet(scribe_note=bad_value))
                self.assertTrue(any("scribe_note" in r for r in reasons))

    def test_ellipsis_only_scribe_note_rejected(self):
        for bad_value in ["……", "…", "・・・", "..."]:
            with self.subTest(bad_value=bad_value):
                reasons = ms.validate_packet(make_packet(scribe_note=bad_value))
                self.assertTrue(any("三点リーダー" in r for r in reasons))

    def test_scribe_note_over_72_chars_rejected(self):
        text = "\n".join(["あ" * 18] * 5)  # 5行×18文字=90文字
        reasons = ms.validate_packet(make_packet(scribe_note=text))
        self.assertTrue(any("72文字を超えています" in r for r in reasons))

    def test_scribe_note_line_over_18_chars_rejected(self):
        reasons = ms.validate_packet(make_packet(scribe_note="あ" * 19))
        self.assertTrue(any("18文字を超えています" in r for r in reasons))

    def test_scribe_note_over_4_lines_rejected(self):
        text = "\n".join(["あ"] * 5)
        reasons = ms.validate_packet(make_packet(scribe_note=text))
        self.assertTrue(any("4行を超えています" in r for r in reasons))

    def test_scribe_note_exactly_72_chars_passes(self):
        text = "\n".join(["あ" * 18] * 4)  # 4行×18文字=72文字
        reasons = ms.validate_packet(make_packet(scribe_note=text))
        self.assertEqual(reasons, [])

    def test_whitespace_separated_ellipsis_rejected(self):
        # Codexレビュー指摘(Major): 三点リーダーの間に空白を挟むと、行頭・
        # 行末のみのstripでは検出できず素通りしていた(2026-07-24修正)。
        for bad_value in ["… …", "…　…", "・ ・ ・"]:
            with self.subTest(bad_value=bad_value):
                reasons = ms.validate_packet(make_packet(scribe_note=bad_value))
                self.assertTrue(any("三点リーダー" in r for r in reasons))

    def test_midline_horizontal_ellipsis_variant_rejected(self):
        # U+22EF(MIDLINE HORIZONTAL ELLIPSIS)も三点リーダー扱いで拒否する
        # (Codexレビュー指摘、Major)。
        reasons = ms.validate_packet(make_packet(scribe_note="⋯"))
        self.assertTrue(any("三点リーダー" in r for r in reasons))


class RobustnessAgainstMalformedInputTest(unittest.TestCase):
    """Codexレビュー(2026-07-24、分割レビューA)で発見された、型不正な入力に
    対するクラッシュ(TypeError/AttributeError)の回帰確認。
    """

    def test_unhashable_performer_expression_does_not_crash(self):
        performer = make_performer("ハルト", expression={})
        reasons = ms.validate_performer(performer, 0, 0, ["ハルト", "書記官"])
        self.assertTrue(any("expression" in r for r in reasons))

    def test_unhashable_scribe_panel_expression_does_not_crash(self):
        scribe_panel = make_scribe_panel(expression=[])
        reasons = ms.validate_scribe_panel(scribe_panel)
        self.assertTrue(any("expression" in r for r in reasons))

    def test_unhashable_framing_in_diversity_check_does_not_crash(self):
        panels = make_panels()
        panels[0]["framing"] = {}
        packet = make_packet(panels=panels)
        # クラッシュしないことが本テストの主眼(reasonsの内容は問わない)。
        ms.validate_packet(packet)

    def test_dialogue_ellipsis_with_internal_whitespace_rejected(self):
        dialogue = make_dialogue(text="… …")
        reasons = ms.validate_dialogue(dialogue, 0, 0, ["ハルト"])
        self.assertTrue(any("三点リーダー" in r for r in reasons))


class ReferenceImageMalformedInputTest(unittest.TestCase):
    """reference_imageの形式検証(パストラバーサル・末尾改行等)の回帰確認。"""

    def test_trailing_newline_reference_image_rejected(self):
        # Codexレビュー指摘(Major): 正規表現の`$`が末尾改行の直前にも
        # マッチするPython仕様のため、"haruto/neutral.png\n"を誤って
        # 許可していた(`\Z`へ変更して修正、2026-07-24)。
        performer = make_performer("ハルト", reference_image="haruto/neutral.png\n")
        reasons = ms.validate_performer(performer, 0, 0, ["ハルト", "書記官"])
        self.assertTrue(any("reference_image" in r for r in reasons))

    def test_path_traversal_reference_image_rejected(self):
        for bad_value in ["../haruto/neutral.png", "haruto/../neutral.png", "haruto/../../etc/passwd.png"]:
            with self.subTest(bad_value=bad_value):
                performer = make_performer("ハルト", reference_image=bad_value)
                reasons = ms.validate_performer(performer, 0, 0, ["ハルト", "書記官"])
                self.assertTrue(any("reference_image" in r for r in reasons))


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
