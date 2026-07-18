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


def make_source(n, source_type="rss"):
    return [
        {
            "title": f"t{i}",
            "link": f"http://example.com/{i}",
            "summary": "s",
            "pubDate": None,
            "sourceType": source_type,
        }
        for i in range(n)
    ]


def draft_block(idx, tag, body, link, route="RSS", explanation="テスト用の解説文。"):
    return (
        f"## 下書き{idx}\n"
        "### 投稿文\n"
        f"{tag}\n"
        f"{body}\n"
        "\n"
        "【書記官の解説】\n"
        f"{explanation}\n"
        "\n"
        f"{link}\n"
        "#異世界ニホン\n"
        "### メモ\n"
        f"- 元記事: テスト{idx}\n"
        f"- 収集経路: {route}\n"
    )


def make_draft(n, links=None, bodies=None, tags=None, routes=None, explanations=None):
    links = links or [f"http://example.com/{i}" for i in range(n)]
    bodies = bodies or ["テスト本文。" for _ in range(n)]
    tags = tags or ["【異世界ニホン・国法】" for _ in range(n)]
    routes = routes or ["RSS" for _ in range(n)]
    explanations = explanations or ["テスト用の解説文。" for _ in range(n)]
    blocks = "\n".join(
        draft_block(i + 1, tags[i], bodies[i], links[i], routes[i], explanations[i])
        for i in range(n)
    )
    return "# X投稿下書き テスト\n\n" + blocks


def make_source_with_facts(link, confirmed_facts=None, source_type="work", **extra_fields):
    article = {
        "title": "テスト記事",
        "link": link,
        "summary": "",
        "status": "",
        "category": "",
        "pubDate": None,
        "sourceType": source_type,
        "people": [],
        "organizations": [],
        "confirmedFacts": confirmed_facts or [],
        "remainingProcess": [],
        "officialUrls": [],
        "relatedUrls": [],
        "sourceDifferences": [],
        "translationCautions": [],
    }
    article.update(extra_fields)
    return [article]


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


class WorkSourceTypeTest(unittest.TestCase):
    """Phase 2a: 入力記事のsourceType(work/rss)と下書きメモの収集経路の
    整合性を検証する。
    """

    def test_source_type_work_with_matching_route_passes(self):
        draft = make_draft(1, routes=["Work"])
        code, content, _, _ = run_validate(draft, make_source(1, source_type="work"))
        self.assertEqual(code, 0, content)

    def test_mixed_work_and_rss_sources_with_matching_routes_pass(self):
        links = [f"http://example.com/{i}" for i in range(2)]
        draft = make_draft(2, links=links, routes=["Work", "RSS"])
        source = [
            {"title": "t0", "link": links[0], "summary": "s", "pubDate": None, "sourceType": "work"},
            {"title": "t1", "link": links[1], "summary": "s", "pubDate": None, "sourceType": "rss"},
        ]
        code, content, _, _ = run_validate(draft, source)
        self.assertEqual(code, 0, content)

    def test_invalid_source_type_rejected(self):
        draft = make_draft(1, routes=["Work"])
        source = make_source(1, source_type="work")
        source[0]["sourceType"] = "bogus"
        code, _, _, stderr = run_validate(draft, source)
        self.assertNotEqual(code, 0)
        self.assertIn("sourceTypeが不正です", stderr)

    def test_collection_route_mismatch_rejected(self):
        # 入力はwork記事だが、メモの収集経路はRSSと記載(不一致)
        draft = make_draft(1, routes=["RSS"])
        code, content, _, _ = run_validate(draft, make_source(1, source_type="work"))
        self.assertNotEqual(code, 0)
        self.assertIn("⚠NG", content)
        self.assertIn("収集経路が入力記事のsourceTypeと不一致", content)

    def test_collection_route_missing_rejected(self):
        draft_missing_route = (
            "# X投稿下書き テスト\n\n"
            "## 下書き1\n"
            "### 投稿文\n"
            "【異世界ニホン・国法】\n"
            "テスト本文。\n"
            "\n"
            "【書記官の解説】\n"
            "テスト用の解説文。\n"
            "\n"
            "http://example.com/0\n"
            "#異世界ニホン\n"
            "### メモ\n"
            "- 元記事: テスト1\n"
        )
        code, content, _, _ = run_validate(draft_missing_route, make_source(1))
        self.assertNotEqual(code, 0)
        self.assertIn("⚠NG", content)
        self.assertIn("収集経路", content)
        self.assertIn("記載がない", content)

    def test_work_link_duplicate_across_drafts_rejected(self):
        # Phase 1の一対一対応検査(重複リンク)はsourceType=workの記事にも
        # 同様に適用される。
        links = ["http://example.com/0", "http://example.com/0"]
        draft = make_draft(2, links=links, routes=["Work", "Work"])
        code, content, _, _ = run_validate(draft, make_source(2, source_type="work"))
        self.assertNotEqual(code, 0)
        self.assertIn("他の下書きと重複", content)


class KingdomTermsTest(unittest.TestCase):
    """2026-07-18改訂: 王制関連語(国王・女王・王家・王族・王子・王女・王妃・
    王都・領主等の「王国」不採用語)は、単語単位では禁止しない。入力記事に
    実在する語彙としてそのまま使う場合は許可し、入力にない「ニホン+王制語」
    の固定複合表現だけを禁止する。「統治する」等の文全体の意味理解が
    必要な主張はscripts/validate.pyでは判定しない
    (config/runtime_rules.mdと生成後レビューの対象)。
    """

    def test_official_imperial_terms_present_in_both_input_and_output_pass(self):
        # 1. 入力と出力の両方に「親王・王・王妃・女王」がある場合は合格
        link = "http://example.com/0"
        source = make_source_with_facts(
            link,
            confirmed_facts=["親王、親王妃、内親王、王、王妃及び女王は、皇室会議の議を経て、一定の要件を満たす男子を養子とすることができる。"],
        )
        explanation = "親王、親王妃、内親王、王、王妃及び女王は、皇室会議の議を経て、一定の要件を満たす男子を養子とすることができる。"
        draft = make_draft(1, links=[link], routes=["Work"], explanations=[explanation])
        code, content, _, _ = run_validate(draft, source)
        self.assertEqual(code, 0, content)

    def test_official_imperial_terms_variant_a_passes(self):
        # テスト1A: 内親王及び女王は、婚姻後も原則として皇族の身分を離れない。
        link = "http://example.com/0"
        explanation = "内親王及び女王は、婚姻後も原則として皇族の身分を離れない。"
        source = make_source_with_facts(link, confirmed_facts=[explanation])
        draft = make_draft(1, links=[link], routes=["Work"], explanations=[explanation])
        code, content, _, _ = run_validate(draft, source)
        self.assertEqual(code, 0, content)

    def test_official_imperial_terms_variant_b_passes(self):
        # テスト1B: 親王、親王妃、内親王、王、王妃及び女王は、皇室会議の議を
        # 経て、一定の要件を満たす男子を養子とすることができる。
        link = "http://example.com/0"
        explanation = "親王、親王妃、内親王、王、王妃及び女王は、皇室会議の議を経て、一定の要件を満たす男子を養子とすることができる。"
        source = make_source_with_facts(link, confirmed_facts=[explanation])
        draft = make_draft(1, links=[link], routes=["Work"], explanations=[explanation])
        code, content, _, _ = run_validate(draft, source)
        self.assertEqual(code, 0, content)

    def test_foreign_monarchy_terms_present_in_both_input_and_output_pass(self):
        # 2. 入力と出力の両方に外国の「国王・女王・王室・王子・王女」がある
        # 場合は合格
        link = "http://example.com/0"
        explanation = "英国のチャールズ国王とエリザベス前女王、ウィリアム王子について、王室行事の一環として報じられた。"
        source = make_source_with_facts(link, confirmed_facts=[explanation])
        draft = make_draft(1, links=[link], routes=["Work"], explanations=[explanation])
        code, content, _, _ = run_validate(draft, source)
        self.assertEqual(code, 0, content)

    def test_official_terms_remaining_in_explanation_still_pass(self):
        # 7. 入力に正式用語がある場合、書記官の解説に残っていてもvalidate.py
        # が合格させる(解説限定での再確認)
        link = "http://example.com/0"
        explanation = "王、王妃及び女王は皇族の身分を保つ。"
        source = make_source_with_facts(link, confirmed_facts=["王、王妃及び女王は皇族の身分を保つ。"])
        draft = make_draft(1, links=[link], routes=["Work"], explanations=[explanation])
        code, content, _, _ = run_validate(draft, source)
        self.assertEqual(code, 0, content)

    def test_smell_terms_fabricated_without_input_are_rejected(self):
        # 3. 入力にない「ニホン王国」「王国政府」「王国議会」「王都」は失敗する
        link = "http://example.com/0"
        source = make_source_with_facts(link, confirmed_facts=["普通の政治ニュース記事です。"])
        for term in ["ニホン王国", "王国政府", "王国議会", "王都"]:
            with self.subTest(term=term):
                explanation = f"{term}についての説明。"
                draft = make_draft(1, links=[link], routes=["Work"], explanations=[explanation])
                code, content, _, _ = run_validate(draft, source)
                self.assertNotEqual(code, 0, content)
                self.assertIn("⚠NG", content)
                # Minor2対応: NGの理由が王制語彙検査によるものであることを
                # 具体的に確認する(別の理由で偶然NGになったのではないか)。
                self.assertIn(f"入力に存在しない語「{term}」がニホンの制度として追加されています", content)

    def test_nihon_adjacent_royalty_compounds_fabricated_without_input_are_rejected(self):
        # 3/8. 入力にない「ニホンの女王」「ニホンの王家」等を出力側が追加
        # した場合はNG
        link = "http://example.com/0"
        source = make_source_with_facts(link, confirmed_facts=["普通の政治ニュース記事です。"])
        for compound in ["ニホンの女王", "ニホン国王", "ニホンの王家", "ニホン王家", "ニホン王室", "ニホンの王室"]:
            with self.subTest(compound=compound):
                explanation = f"{compound}についての説明。"
                draft = make_draft(1, links=[link], routes=["Work"], explanations=[explanation])
                code, content, _, _ = run_validate(draft, source)
                self.assertNotEqual(code, 0, content)
                self.assertIn("⚠NG", content)
                # Minor2対応: NGの理由が王制語彙検査によるものであることを
                # 具体的に確認する。
                self.assertIn(f"入力に存在しない複合表現「{compound}」がニホンの制度として追加されています", content)

    def test_bare_ou_character_in_unrelated_words_not_falsely_detected(self):
        # 5. 「王貞治」「王座」「王将」「王氏」を裸の「王」として誤検出しない
        link = "http://example.com/0"
        source = make_source_with_facts(link, confirmed_facts=["普通の政治ニュース記事です。"])
        for word in ["王貞治", "王座", "王将", "王氏"]:
            with self.subTest(word=word):
                explanation = f"{word}について解説では触れられた。"
                draft = make_draft(1, links=[link], routes=["Work"], explanations=[explanation])
                code, content, _, _ = run_validate(draft, source)
                self.assertEqual(code, 0, content)

    def test_foreign_and_historical_smell_terms_in_input_are_not_uniformly_rejected(self):
        # 6. 入力にある「王都・領主」等の外国・歴史用語を一律に弾かない
        link = "http://example.com/0"
        explanation = "中世の記録によれば、その地は王都と呼ばれ、領主が治めていたとされる。"
        source = make_source_with_facts(link, confirmed_facts=[explanation])
        draft = make_draft(1, links=[link], routes=["Work"], explanations=[explanation])
        code, content, _, _ = run_validate(draft, source)
        self.assertEqual(code, 0, content)

    def test_semantic_governance_claims_are_not_mechanically_rejected(self):
        # 4. 「女王がニホンを統治する」等、文全体の意味理解が必要な主張は
        # validate.pyでは無理にNGにしない(runtime_rules.mdと生成後レビュー
        # の対象とする、という設計上の意図的な境界を確認する)。
        link = "http://example.com/0"
        source = make_source_with_facts(link, confirmed_facts=["普通の政治ニュース記事です。"])
        sentences = [
            "女王がニホンを統治している。",
            "ニホンは女王が統治する国ではない。",
            "女王がニホンを統治している事実はない。",
            "ニホンに国王や女王が統治する制度は存在しない。",
            "英国国王が来日し、ニホンの統治制度について説明を受けた。",
        ]
        for explanation in sentences:
            with self.subTest(explanation=explanation):
                draft = make_draft(1, links=[link], routes=["Work"], explanations=[explanation])
                code, content, _, _ = run_validate(draft, source)
                self.assertEqual(
                    code, 0, f"意味理解が必要な文はvalidate.pyでNGにしない設計のはず: {content}"
                )

    def test_unrelated_negation_in_another_sentence_does_not_auto_pass_whole_post(self):
        # 9. 否定語が文中にあるだけで、文全体を自動的に合格させる実装に
        # なっていない: 「ニホンの女王」という固定複合表現(NG対象)を含む
        # 文の直後に、無関係な否定文を続けても、複合表現自体の違反判定は
        # 打ち消されない(=別文の否定語が全体を合格させることはない)。
        link = "http://example.com/0"
        source = make_source_with_facts(link, confirmed_facts=["普通の政治ニュース記事です。"])
        explanation = "ニホンの女王について記された。これは誤りではないかもしれない。"
        draft = make_draft(1, links=[link], routes=["Work"], explanations=[explanation])
        code, content, _, _ = run_validate(draft, source)
        self.assertNotEqual(code, 0, content)
        self.assertIn("⚠NG", content)
        # Minor2対応: 理由が王制語彙検査によるものであることを確認する。
        self.assertIn("入力に存在しない複合表現「ニホンの女王」がニホンの制度として追加されています", content)

    def test_foreign_royal_family_term_present_in_input_passes(self):
        # 王室追加の確認: 入力に外国の「王室」がある場合は合格する。
        link = "http://example.com/0"
        explanation = "英国王室は、王子の来日を歓迎する声明を発表した。"
        source = make_source_with_facts(link, confirmed_facts=[explanation])
        draft = make_draft(1, links=[link], routes=["Work"], explanations=[explanation])
        code, content, _, _ = run_validate(draft, source)
        self.assertEqual(code, 0, content)

    def test_narrative_within_130_chars_still_passes(self):
        # 5. 物語本文130字制限の既存検査が引き続き合格することを確認する。
        link = "http://example.com/0"
        source = make_source_with_facts(link, confirmed_facts=["普通の政治ニュース記事です。"])
        body = "テスト本文。" * 5  # 110字未満(130字制限内)
        draft = make_draft(1, links=[link], bodies=[body], routes=["Work"])
        code, content, _, _ = run_validate(draft, source)
        self.assertEqual(code, 0, content)

    def test_narrative_over_130_chars_still_rejected(self):
        # 5. 物語本文130字制限の既存検査が引き続き機能することを確認する
        # (王制語検査の変更で他の検査が壊れていないかの回帰確認)。
        link = "http://example.com/0"
        source = make_source_with_facts(link, confirmed_facts=["普通の政治ニュース記事です。"])
        body = "テスト本文。" * 23  # 138字(130字超過)
        draft = make_draft(1, links=[link], bodies=[body], routes=["Work"])
        code, content, _, _ = run_validate(draft, source)
        self.assertNotEqual(code, 0, content)
        self.assertIn("字超過", content)


class KingdomTermLinkMatchingTest(unittest.TestCase):
    """Codexレビュー指摘(Minor1)対応: 王制語彙検査は、下書きに有効な
    元記事リンクが厳密に1件だけあり、そのリンクから入力記事を一意に
    特定できる場合だけ実行する。入力テキストblobが偶然一致するか否かで
    判定しないことを確認する。
    """

    def test_two_draft_blocks_with_distinct_links_use_correct_source_each(self):
        # 同一内容の入力記事が2件存在しても、リンク数(各下書きブロックとも
        # 1件)を基準に、正しくそれぞれ対応する入力記事と照合される。
        link1 = "http://example.com/0"
        link2 = "http://example.com/1"
        facts = ["普通の政治ニュース記事です。"]  # 2記事とも同一内容
        source = [
            {
                "title": "t0", "link": link1, "summary": "", "status": "", "category": "",
                "pubDate": None, "sourceType": "work", "people": [], "organizations": [],
                "confirmedFacts": facts, "remainingProcess": [], "officialUrls": [],
                "relatedUrls": [], "sourceDifferences": [], "translationCautions": [],
            },
            {
                "title": "t1", "link": link2, "summary": "", "status": "", "category": "",
                "pubDate": None, "sourceType": "work", "people": [], "organizations": [],
                "confirmedFacts": facts, "remainingProcess": [], "officialUrls": [],
                "relatedUrls": [], "sourceDifferences": [], "translationCautions": [],
            },
        ]
        draft = make_draft(
            2,
            links=[link1, link2],
            routes=["Work", "Work"],
            explanations=["ニホンの女王について記された。", "普通の解説文。"],
        )
        code, content, _, _ = run_validate(draft, source)
        self.assertNotEqual(code, 0, content)
        self.assertIn("入力に存在しない複合表現「ニホンの女王」", content)
        # 2件目(下書き2)は正しい入力と照合されており、誤検出されていない。
        self.assertNotIn("下書き2 ⚠NG", content)

    def test_two_links_in_a_single_draft_block_skip_kingdom_check(self):
        # 1つの下書きブロックに元記事リンクが2件含まれる場合、王制語彙検査
        # は実行されない(=このテストでは王制語彙検査由来のNG理由が
        # つかないことだけを確認する)。
        link1 = "http://example.com/0"
        link2 = "http://example.com/1"
        source = [
            {
                "title": "t0", "link": link1, "summary": "", "status": "", "category": "",
                "pubDate": None, "sourceType": "work", "people": [], "organizations": [],
                "confirmedFacts": [], "remainingProcess": [], "officialUrls": [],
                "relatedUrls": [], "sourceDifferences": [], "translationCautions": [],
            },
            {
                "title": "t1", "link": link2, "summary": "", "status": "", "category": "",
                "pubDate": None, "sourceType": "work", "people": [], "organizations": [],
                "confirmedFacts": [], "remainingProcess": [], "officialUrls": [],
                "relatedUrls": [], "sourceDifferences": [], "translationCautions": [],
            },
        ]
        body = f"テスト本文。\n{link2}"
        draft = make_draft(
            1, links=[link1], bodies=[body], routes=["Work"],
            explanations=["ニホンの女王について記された。"],
        )
        code, content, _, _ = run_validate(draft, source)
        # リンクが2件になるため王制語彙検査は実行されない。
        self.assertNotIn("入力に存在しない複合表現", content)
        self.assertNotIn("がニホンの制度として追加されています", content)

    def test_link_not_matching_any_source_article_is_handled_by_existing_link_check(self):
        # 下書きのリンクに対応する入力記事がない場合、王制語彙検査は実行
        # されず(source_text=None)、既存のリンク不一致検査でNGになる。
        link = "http://example.com/not-in-source"
        source = make_source_with_facts("http://example.com/0", confirmed_facts=["普通の記事。"])
        draft = make_draft(
            1, links=[link], routes=["Work"], explanations=["ニホンの女王について記された。"]
        )
        code, content, _, _ = run_validate(draft, source)
        self.assertNotEqual(code, 0, content)
        self.assertIn("入力JSONのlinkと一致しない", content)
        # 王制語彙検査由来の理由は付かない(source_text=Noneで検査自体が
        # スキップされるため)。
        self.assertNotIn("入力に存在しない複合表現", content)


class TranslatePromptContentTest(unittest.TestCase):
    """prompts/translate.mdに、法律上の範囲を広げたり狭めたりしないという
    事実保持ルールが存在することを確認する(2026-07-18追加)。
    """

    def test_translate_md_has_scope_preservation_rule(self):
        translate_md = ROOT / "prompts" / "translate.md"
        text = translate_md.read_text(encoding="utf-8")
        self.assertIn("法律・制度の内容を短縮する際の注意", text)
        self.assertIn("広くまたは狭く読める表現へ一般化しては", text)


if __name__ == "__main__":
    unittest.main()
