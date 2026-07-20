#!/usr/bin/env python3
"""scripts/validate_manga.py のテスト(異世界ニホン4コマ版 Phase 1)。

manga_schema.pyの構造検証(4コマ固定・登場キャラ<=3人等)に加え、
scripts/banned_terms.pyの禁止語検証(法案・選挙の文脈語、政党名
カタカナ化、ニホンに実在しない王制表現)がPacket内の日本語テキスト
全体に対して行われること、およびオプションの元記事JSON(raw_article)を
渡すことで王制語検査の入力照合範囲が広がることを検証する。Python標準
ライブラリのみを使用する(unittest, pathlib, sys, json, subprocess,
tempfile)。
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import manga_schema  # noqa: E402
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


class RawArticleWideningTest(unittest.TestCase):
    """Packetのsource(title・url・summaryのみ)だけでは元記事の情報量が
    乏しく、元記事に実在する正当な語彙が誤ってNGになる問題(Codexレビュー
    Critical指摘)を、raw_articleを渡すことで解消できることを確認する。
    """

    def test_term_only_in_raw_article_confirmed_facts_is_now_allowed(self):
        # Packetのsummaryには「王都」が含まれないが、元記事の
        # confirmedFactsには含まれる。source単体では誤NGになるが、
        # raw_articleを渡せば許可される。
        packet = make_packet(
            source={
                "title": "外国の史跡に関する報道",
                "url": "https://example.com/raw-1",
                "summary": "外国の行事を報じた。",
            },
            scribe_note="かつての「王都」の跡地が一般公開された。",
        )
        raw_article = {
            "title": "外国の史跡に関する報道",
            "link": "https://example.com/raw-1",
            "summary": "外国の行事を報じた。",
            "confirmedFacts": ["かつての「王都」の跡地が一般公開された"],
        }

        without_raw = vm.validate_manga_packet(packet)
        self.assertTrue(any("王都" in r for r in without_raw), "raw_articleなしでは誤NGになる状況のはず")

        with_raw = vm.validate_manga_packet(packet, raw_article=raw_article)
        self.assertFalse(any("王都" in r for r in with_raw))

    def test_non_matching_link_is_not_selected_by_find_matching_raw_article(self):
        # validate_manga_packet自体はraw_articleをそのまま信頼して使う
        # (呼び出し側の責務)ため、リンク一致の保証はfind_matching_raw_article
        # 側で検証する。main()はこの関数の戻り値だけをraw_articleとして渡す
        # (下記CliSourceJsonArgumentTest参照)。
        packet = make_packet(
            source={
                "title": "外国の史跡に関する報道",
                "url": "https://example.com/raw-2",
                "summary": "外国の行事を報じた。",
            },
            scribe_note="かつての「王都」の跡地が一般公開された。",
        )
        raw_articles = [
            {
                "title": "無関係な記事",
                "link": "https://example.com/different-link",
                "summary": "",
                "confirmedFacts": ["かつての「王都」の跡地が一般公開された"],
            }
        ]
        matched = vm.find_matching_raw_article(raw_articles, packet["source"]["url"])
        self.assertIsNone(matched)

        reasons = vm.validate_manga_packet(packet, raw_article=matched)
        self.assertTrue(any("王都" in r for r in reasons), "linkが一致しないraw_articleは照合対象に含めてはいけない")

    def test_find_matching_raw_article_by_link(self):
        articles = [
            {"link": "https://example.com/a", "title": "A"},
            {"link": "https://example.com/b", "title": "B"},
        ]
        found = vm.find_matching_raw_article(articles, "https://example.com/b")
        self.assertEqual(found["title"], "B")

    def test_find_matching_raw_article_no_match_returns_none(self):
        articles = [{"link": "https://example.com/a", "title": "A"}]
        self.assertIsNone(vm.find_matching_raw_article(articles, "https://example.com/z"))
        self.assertIsNone(vm.find_matching_raw_article(articles, None))
        self.assertIsNone(vm.find_matching_raw_article("not-a-list", "https://example.com/a"))


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
        panels[0] = make_panel(
            1,
            scene="固有シーン語",
            dialogue="固有セリフ語",
            background="固有背景語",
            image_prompt="unique image prompt marker",
        )
        packet = make_packet(panels=panels)
        blob = vm.build_packet_text_blob(packet)
        self.assertIn("固有シーン語", blob)
        self.assertIn("固有セリフ語", blob)
        self.assertIn("固有背景語", blob)
        self.assertIn("unique image prompt marker", blob)

    def test_banned_japanese_term_leaked_into_image_prompt_is_detected(self):
        # image_promptは本来英語だが、日本語の禁止語が混入した場合を
        # 検査で捕捉できることを確認する(Codexレビュー指摘)。
        panels = make_panels()
        panels[0] = make_panel(1, image_prompt="anime scene, ジミン党 representative at a podium")
        packet = make_packet(panels=panels)
        reasons = vm.validate_manga_packet(packet)
        self.assertTrue(any("ジミン党" in r for r in reasons))

    def test_source_text_blob_includes_title_and_summary(self):
        source = {"title": "固有タイトル語", "url": "https://example.com/x", "summary": "固有要約語"}
        blob = vm.build_source_text_blob(source)
        self.assertIn("固有タイトル語", blob)
        self.assertIn("固有要約語", blob)

    def test_source_text_blob_includes_raw_article_when_given(self):
        source = {"title": "固有タイトル語", "url": "https://example.com/x", "summary": "固有要約語"}
        raw_article = {"title": "固有タイトル語", "link": "https://example.com/x", "confirmedFacts": ["固有事実語"]}
        blob = vm.build_source_text_blob(source, raw_article=raw_article)
        self.assertIn("固有事実語", blob)


def _make_chatgpt_route_packet():
    """panels1〜4をハルト・ナツキ(reference_images複数形)、書記官は
    scribe_note専任とした、ChatGPTルート仕様に沿ったPacketを返す。
    """
    panels = []
    for i in range(4):
        panel = make_panel(i + 1)
        del panel["reference_image"]
        panel["reference_images"] = {
            "ハルト": "haruto/surprise-medium.png",
            "ナツキ": "natsuki/neutral.png",
        }
        panels.append(panel)
    return make_packet(characters=["ハルト", "ナツキ", "書記官"], panels=panels)


class ChatGptRouteValidationTest(unittest.TestCase):
    """validate_chatgpt_route: panels1〜4=ハルト・ナツキ専任、
    charactersは{ハルト,ナツキ,書記官}のみという追加制約を検証する。
    """

    def test_valid_chatgpt_route_packet_passes(self):
        packet = _make_chatgpt_route_packet()
        self.assertEqual(vm.validate_chatgpt_route(packet), [])

    def test_generic_structural_validation_still_passes_for_same_packet(self):
        # ChatGPTルート追加検証と、既存の汎用構造検証は独立して両方合格する。
        packet = _make_chatgpt_route_packet()
        self.assertEqual(manga_schema.validate_packet(packet), [])

    def test_panel_using_legacy_singular_reference_image_rejected(self):
        # ChatGPTルートではreference_images(複数形)が必須。
        packet = _make_chatgpt_route_packet()
        packet["panels"][0] = make_panel(1)  # legacy単数のreference_imageに戻す
        reasons = vm.validate_chatgpt_route(packet)
        self.assertTrue(any("reference_images(複数形)の指定が必要です" in r for r in reasons))

    def test_scribe_in_panel_reference_images_rejected(self):
        packet = _make_chatgpt_route_packet()
        packet["panels"][3]["reference_images"] = {"書記官": "scribe/speaking-normal.png"}
        reasons = vm.validate_chatgpt_route(packet)
        self.assertTrue(
            any("ChatGPTルートで許可されないキャラクター" in r and "書記官" in r for r in reasons)
        )

    def test_akira_or_fuyumi_in_panel_reference_images_rejected(self):
        packet = _make_chatgpt_route_packet()
        packet["panels"][0]["reference_images"] = {"アキラ": "akira/neutral.png"}
        reasons = vm.validate_chatgpt_route(packet)
        self.assertTrue(any("アキラ" in r for r in reasons))

    def test_top_level_characters_with_akira_rejected(self):
        packet = _make_chatgpt_route_packet()
        packet["characters"] = ["ハルト", "アキラ"]
        reasons = vm.validate_chatgpt_route(packet)
        self.assertTrue(any("アキラ" in r for r in reasons))

    def test_top_level_characters_with_scribe_allowed(self):
        # 書記官はscribe_note(第5コマ)専任だがcharacters一覧への記載自体は
        # 許可する(トップレベルcharactersはパネル出演とは別概念のため)。
        packet = _make_chatgpt_route_packet()
        packet["characters"] = ["ハルト", "書記官"]
        self.assertEqual(vm.validate_chatgpt_route(packet), [])

    def test_non_dict_packet_rejected(self):
        self.assertTrue(vm.validate_chatgpt_route("not-a-dict"))

    def test_malformed_panel_does_not_crash(self):
        packet = _make_chatgpt_route_packet()
        packet["panels"][0] = "not-a-dict"
        # クラッシュしないことを確認する(型不正の詳細検出はmanga_schema側の責務)。
        vm.validate_chatgpt_route(packet)

    def test_default_make_packet_using_legacy_single_reference_image_fails_route_check(self):
        # 既存のmake_packet()(reference_image単数、characters=ハルト/アキラ/書記官)は
        # 汎用構造検証(manga_schema.validate_packet)には合格し続けるが、
        # ChatGPTルート追加検証には合格しない(後方互換と新ルート制約は別レイヤー)。
        packet = make_packet()
        self.assertEqual(manga_schema.validate_packet(packet), [])
        self.assertTrue(vm.validate_chatgpt_route(packet))


class ChatGptRouteExampleFileTest(unittest.TestCase):
    """data/state/manga_packet.chatgpt_route.example.json が、構造検証・
    ChatGPTルート追加検証・禁止語検証のすべてに合格することを確認する。
    """

    def _load(self):
        example_path = ROOT / "data" / "state" / "manga_packet.chatgpt_route.example.json"
        with example_path.open(encoding="utf-8") as f:
            return json.load(f)

    def test_passes_generic_structural_validation(self):
        packet = self._load()
        self.assertEqual(manga_schema.validate_packet(packet), [])

    def test_passes_chatgpt_route_validation(self):
        packet = self._load()
        self.assertEqual(vm.validate_chatgpt_route(packet), [])

    def test_passes_full_validate_manga_packet(self):
        # 禁止語検証(scripts/banned_terms.py)も含めて合格することを確認する。
        packet = self._load()
        self.assertEqual(vm.validate_manga_packet(packet), [])

    def test_legacy_example_file_does_not_pass_chatgpt_route_validation(self):
        # 旧形式サンプル(data/state/manga_packet.example.json)は、
        # 構造検証には合格し続けるが、ChatGPTルート追加検証には合格しない
        # (4コマ目が書記官であるため)。新旧の使い分けが機能していることの
        # 回帰確認。
        legacy_path = ROOT / "data" / "state" / "manga_packet.example.json"
        with legacy_path.open(encoding="utf-8") as f:
            legacy_packet = json.load(f)
        self.assertEqual(manga_schema.validate_packet(legacy_packet), [])
        self.assertTrue(vm.validate_chatgpt_route(legacy_packet))


class CliSourceJsonArgumentTest(unittest.TestCase):
    """CLI(validate_manga.py <packet_file> [<source_json>])が、
    第2引数の元記事JSONを正しく照合対象に取り込むことを確認する。
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp = pathlib.Path(self._tmpdir.name)

    def test_main_uses_source_json_to_avoid_false_positive(self):
        packet = make_packet(
            source={
                "title": "外国の史跡に関する報道",
                "url": "https://example.com/cli-1",
                "summary": "外国の行事を報じた。",
            },
            scribe_note="かつての「王都」の跡地が一般公開された。",
        )
        raw_articles = [
            {
                "title": "外国の史跡に関する報道",
                "link": "https://example.com/cli-1",
                "summary": "外国の行事を報じた。",
                "confirmedFacts": ["かつての「王都」の跡地が一般公開された"],
            }
        ]
        packet_path = self.tmp / "packet.json"
        source_path = self.tmp / "source.json"
        packet_path.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")
        source_path.write_text(json.dumps(raw_articles, ensure_ascii=False), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "validate_manga.py"), str(packet_path), str(source_path)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_main_without_source_json_still_rejects(self):
        packet = make_packet(
            source={
                "title": "外国の史跡に関する報道",
                "url": "https://example.com/cli-2",
                "summary": "外国の行事を報じた。",
            },
            scribe_note="かつての「王都」の跡地が一般公開された。",
        )
        packet_path = self.tmp / "packet.json"
        packet_path.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "validate_manga.py"), str(packet_path)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("王都", result.stdout)


if __name__ == "__main__":
    unittest.main()
