#!/usr/bin/env python3
"""scripts/rss_dedup.py と scripts/collect.py の日またぎ重複除外・
台帳トランザクション・初回復元のテスト(Phase 2c)。

RSSのURL完全一致による重複除外(タイトル一致・意味的類似では除外
しない)、pending→commit-pendingによる全工程成功後だけの台帳更新、
30日保持、data/raw+drafts一致による初回復元を検証する。
Python標準ライブラリのみを使用する
(unittest, unittest.mock, json, pathlib, sys, tempfile)。
"""
import json
import pathlib
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import collect  # noqa: E402
import rss_dedup  # noqa: E402


def make_item(link, title="タイトル", pub_dt=None):
    return {"title": title, "link": link, "summary": "概要", "pub_dt": pub_dt}


class FilterNewItemsTest(unittest.TestCase):
    def test_url_exact_match_excluded(self):
        recent = {"https://example.com/a": "2026-07-01"}
        items = [make_item("https://example.com/a"), make_item("https://example.com/b")]
        result = rss_dedup.filter_new_items(items, recent)
        self.assertEqual([i["link"] for i in result], ["https://example.com/b"])

    def test_same_title_different_url_kept(self):
        # タイトルが同じでもURLが違えば除外しない。
        recent = {"https://example.com/a": "2026-07-01"}
        items = [make_item("https://example.com/a-updated", title="タイトル")]
        result = rss_dedup.filter_new_items(items, recent)
        self.assertEqual(len(result), 1)

    def test_semantically_similar_different_url_kept(self):
        # rss_dedupはURL完全一致のみを見る。意味的な類似は判定しないため
        # 除外されない。
        recent = {"https://example.com/a": "2026-07-01"}
        items = [make_item("https://example.com/c", title="内容は似ているが別記事")]
        result = rss_dedup.filter_new_items(items, recent)
        self.assertEqual(len(result), 1)


class BackfillTest(unittest.TestCase):
    def test_excluded_then_backfilled_to_limit(self):
        # 重複10件(優先順位が高い=公開日時が新しい)+新規10件(優先順位が
        # 低い=公開日時が古い)の合計20件。フィルタせずに上位10件を選ぶと
        # 重複だけで埋まってしまう(=0件しか新規が残らない)ため、
        # 「フィルタしてから選ぶ」実装でなければ10件の補充は成立しない。
        from datetime import datetime, timedelta, timezone

        base = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
        recent = {f"https://example.com/dup/{i}": "2026-07-01" for i in range(10)}
        items = [
            make_item(f"https://example.com/dup/{i}", pub_dt=base - timedelta(hours=i))
            for i in range(10)
        ]
        items += [
            make_item(f"https://example.com/new/{i}", pub_dt=base - timedelta(hours=100 + i))
            for i in range(10)
        ]
        filtered = rss_dedup.filter_new_items(items, recent)
        selected = collect.select(filtered, collect.MAX_ARTICLES)
        self.assertEqual(len(selected), 10, "重複除外後、新規10件まで補充されるべき")
        self.assertTrue(all("new" in i["link"] for i in selected), "補充された記事はすべて新規でなければならない")

    def test_seven_duplicates_and_three_new_selects_only_three(self):
        # 実際に発生したケースを模した疑似シナリオ:
        # 7件重複+3件新規 → 新規3件だけが選ばれる。
        recent = {f"https://example.com/dup/{i}": "2026-07-16" for i in range(7)}
        items = [make_item(f"https://example.com/dup/{i}") for i in range(7)]
        items += [make_item(f"https://example.com/new/{i}") for i in range(3)]
        filtered = rss_dedup.filter_new_items(items, recent)
        selected = collect.select(filtered, collect.MAX_ARTICLES)
        self.assertEqual(len(selected), 3)
        self.assertTrue(all("new" in i["link"] for i in selected))


class LoadRecentLinksTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.path = pathlib.Path(self._tmpdir.name) / "recent_rss_links.json"

    def test_missing_file_returns_empty(self):
        self.assertEqual(rss_dedup.load_recent_rss_links(self.path), {})

    def test_valid_file_loaded(self):
        rss_dedup.write_json_atomic(self.path, {"links": {"https://example.com/a": "2026-07-01"}})
        self.assertEqual(rss_dedup.load_recent_rss_links(self.path), {"https://example.com/a": "2026-07-01"})

    def test_corrupted_json_raises(self):
        self.path.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            rss_dedup.load_recent_rss_links(self.path)

    def test_wrong_root_type_raises(self):
        self.path.write_text("[]", encoding="utf-8")
        with self.assertRaises(ValueError):
            rss_dedup.load_recent_rss_links(self.path)

    def test_wrong_links_type_raises(self):
        rss_dedup.write_json_atomic(self.path, {"links": ["not", "a", "dict"]})
        with self.assertRaises(ValueError):
            rss_dedup.load_recent_rss_links(self.path)

    def test_non_string_element_raises(self):
        rss_dedup.write_json_atomic(self.path, {"links": {"https://example.com/a": 123}})
        with self.assertRaises(ValueError):
            rss_dedup.load_recent_rss_links(self.path)


class PruneExpiredTest(unittest.TestCase):
    def test_exactly_30_days_old_is_kept(self):
        today = date(2026, 7, 31)
        links = {"https://example.com/a": (today - timedelta(days=30)).isoformat()}
        pruned = rss_dedup.prune_expired(links, today)
        self.assertIn("https://example.com/a", pruned)

    def test_31_days_old_is_removed(self):
        today = date(2026, 7, 31)
        links = {"https://example.com/a": (today - timedelta(days=31)).isoformat()}
        pruned = rss_dedup.prune_expired(links, today)
        self.assertNotIn("https://example.com/a", pruned)

    def test_recent_link_is_kept(self):
        today = date(2026, 7, 31)
        links = {"https://example.com/a": today.isoformat()}
        pruned = rss_dedup.prune_expired(links, today)
        self.assertIn("https://example.com/a", pruned)

    def test_malformed_date_entry_is_dropped(self):
        today = date(2026, 7, 31)
        links = {"https://example.com/a": "not-a-date"}
        pruned = rss_dedup.prune_expired(links, today)
        self.assertNotIn("https://example.com/a", pruned)


class CommitPendingTransactionTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp = pathlib.Path(self._tmpdir.name)
        self.ledger_path = self.tmp / "recent_rss_links.json"
        self.pending_path = self.tmp / ".pending_rss_links_test.json"

    def test_commit_pending_noop_when_pending_missing(self):
        rss_dedup.commit_pending(self.pending_path, self.ledger_path, date(2026, 7, 17))
        self.assertFalse(self.ledger_path.exists())

    def test_pipeline_failure_does_not_update_ledger(self):
        # write_pendingだけ呼ばれ、commit_pendingが呼ばれない
        # (パイプライン失敗を模擬)限り、台帳は更新されない。
        rss_dedup.write_pending(self.pending_path, ["https://example.com/a"])
        self.assertFalse(self.ledger_path.exists(), "commit-pendingを呼ぶまで台帳は更新されない")

    def test_commit_after_full_success_updates_ledger(self):
        rss_dedup.write_pending(self.pending_path, ["https://example.com/a", "https://example.com/b"])
        rss_dedup.commit_pending(self.pending_path, self.ledger_path, date(2026, 7, 17))
        ledger = rss_dedup.load_recent_rss_links(self.ledger_path)
        self.assertEqual(
            ledger,
            {"https://example.com/a": "2026-07-17", "https://example.com/b": "2026-07-17"},
        )
        self.assertFalse(self.pending_path.exists(), "commit後はpendingファイルを削除する")

    def test_commit_pending_prunes_expired_entries(self):
        rss_dedup.write_json_atomic(self.ledger_path, {"links": {"https://example.com/old": "2026-01-01"}})
        rss_dedup.write_pending(self.pending_path, ["https://example.com/new"])
        rss_dedup.commit_pending(self.pending_path, self.ledger_path, date(2026, 7, 17))
        ledger = rss_dedup.load_recent_rss_links(self.ledger_path)
        self.assertNotIn("https://example.com/old", ledger)
        self.assertIn("https://example.com/new", ledger)

    def test_corrupted_ledger_rejected_not_silently_reset(self):
        self.ledger_path.write_text("not valid json", encoding="utf-8")
        rss_dedup.write_pending(self.pending_path, ["https://example.com/a"])
        with self.assertRaises(json.JSONDecodeError):
            rss_dedup.commit_pending(self.pending_path, self.ledger_path, date(2026, 7, 17))
        self.assertEqual(self.ledger_path.read_text(encoding="utf-8"), "not valid json")

    def test_first_commit_bootstraps_history_and_merges_pending_in_one_write(self):
        # Codexレビュー対応: 台帳の初回書き込みはcollect.pyではなく
        # commit_pendingが行う。台帳がまだ存在しない場合、raw_dir/
        # drafts_dirから履歴を復元したうえで今回のpending分もマージし、
        # 1回の原子的書き込みで確定させる。
        raw_dir = self.tmp / "raw"
        drafts_dir = self.tmp / "drafts"
        raw_dir.mkdir()
        drafts_dir.mkdir()
        (raw_dir / "2026-07-16.json").write_text(
            json.dumps([{"sourceType": "rss", "link": "https://example.com/history"}], ensure_ascii=False),
            encoding="utf-8",
        )
        (drafts_dir / "2026-07-16.md").write_text(
            "## 下書き1\n### 投稿文\n【異世界ニホン・国法】\n本文。\n\n【書記官の解説】\n解説。\n\n"
            "https://example.com/history\n#異世界ニホン\n### メモ\n- 元記事: テスト\n",
            encoding="utf-8",
        )
        self.assertFalse(self.ledger_path.exists(), "前提: 台帳はまだ存在しない")

        rss_dedup.write_pending(self.pending_path, ["https://example.com/today"])
        rss_dedup.commit_pending(
            self.pending_path, self.ledger_path, date(2026, 7, 17),
            raw_dir=str(raw_dir), drafts_dir=str(drafts_dir),
        )

        ledger = rss_dedup.load_recent_rss_links(self.ledger_path)
        self.assertEqual(
            ledger,
            {"https://example.com/history": "2026-07-16", "https://example.com/today": "2026-07-17"},
        )


class BootstrapFromHistoryTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp = pathlib.Path(self._tmpdir.name)
        self.raw_dir = self.tmp / "raw"
        self.drafts_dir = self.tmp / "drafts"
        self.raw_dir.mkdir()
        self.drafts_dir.mkdir()

    def write_raw(self, date_str, articles):
        (self.raw_dir / f"{date_str}.json").write_text(json.dumps(articles, ensure_ascii=False), encoding="utf-8")

    def make_draft_block(self, idx, link, memo_extra_link=None):
        memo_note = f"- 注意: 関連URL {memo_extra_link} を参照" if memo_extra_link else "- 注意: なし"
        return (
            f"## 下書き{idx}\n"
            "### 投稿文\n"
            "【異世界ニホン・国法】\n"
            "テスト本文。\n"
            "\n"
            "【書記官の解説】\n"
            "テスト解説。\n"
            "\n"
            f"{link}\n"
            "#異世界ニホン\n"
            "### メモ\n"
            "- 元記事: テスト\n"
            "- 要約: テスト要約\n"
            f"{memo_note}\n"
            "- 収集経路: RSS\n"
        )

    def write_draft(self, date_str, blocks):
        body = f"# X投稿下書き {date_str}\n\n" + "\n".join(blocks)
        (self.drafts_dir / f"{date_str}.md").write_text(body, encoding="utf-8")

    def test_link_present_in_both_raw_and_draft_is_restored(self):
        self.write_raw("2026-07-16", [{"sourceType": "rss", "link": "https://example.com/a"}])
        self.write_draft("2026-07-16", [self.make_draft_block(1, "https://example.com/a")])
        restored = rss_dedup.bootstrap_from_history(str(self.raw_dir), str(self.drafts_dir), date(2026, 7, 17))
        self.assertEqual(restored, {"https://example.com/a": "2026-07-16"})

    def test_link_only_in_raw_not_restored(self):
        self.write_raw("2026-07-16", [{"sourceType": "rss", "link": "https://example.com/a"}])
        self.write_draft("2026-07-16", [self.make_draft_block(1, "https://example.com/different")])
        restored = rss_dedup.bootstrap_from_history(str(self.raw_dir), str(self.drafts_dir), date(2026, 7, 17))
        self.assertEqual(restored, {})

    def test_link_only_in_memo_not_in_post_body_not_restored(self):
        # Codexレビューで指摘: 投稿文セクション以外(メモ・解説)に偶然
        # 現れたURLを誤って「使用済みリンク」と扱ってはいけない。
        # rawのlinkが、投稿文の元記事リンクとしてではなく、別ブロックの
        # メモ欄にたまたま現れているだけの場合は復元しない。
        self.write_raw("2026-07-16", [{"sourceType": "rss", "link": "https://example.com/a"}])
        self.write_draft(
            "2026-07-16",
            [self.make_draft_block(1, "https://example.com/other", memo_extra_link="https://example.com/a")],
        )
        restored = rss_dedup.bootstrap_from_history(str(self.raw_dir), str(self.drafts_dir), date(2026, 7, 17))
        self.assertEqual(restored, {}, "メモ欄のURLは元記事リンクとして復元してはいけない")

    def test_no_draft_file_not_restored(self):
        self.write_raw("2026-07-16", [{"sourceType": "rss", "link": "https://example.com/a"}])
        restored = rss_dedup.bootstrap_from_history(str(self.raw_dir), str(self.drafts_dir), date(2026, 7, 17))
        self.assertEqual(restored, {})

    def test_work_source_type_link_not_restored(self):
        self.write_raw("2026-07-16", [{"sourceType": "work", "link": "https://example.com/a"}])
        self.write_draft("2026-07-16", [self.make_draft_block(1, "https://example.com/a")])
        restored = rss_dedup.bootstrap_from_history(str(self.raw_dir), str(self.drafts_dir), date(2026, 7, 17))
        self.assertEqual(restored, {}, "Work由来のlinkはRSS台帳へ登録してはいけない")

    def test_older_than_retention_not_restored(self):
        old_date = (date(2026, 7, 17) - timedelta(days=40)).isoformat()
        self.write_raw(old_date, [{"sourceType": "rss", "link": "https://example.com/a"}])
        self.write_draft(old_date, [self.make_draft_block(1, "https://example.com/a")])
        restored = rss_dedup.bootstrap_from_history(str(self.raw_dir), str(self.drafts_dir), date(2026, 7, 17))
        self.assertEqual(restored, {})


SAMPLE_RSS_TEMPLATE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
{items}
</channel></rss>"""


def make_rss_item_xml(title, link, pub_date="Thu, 16 Jul 2026 19:00:00 +0900"):
    return f"<item><title>{title}</title><link>{link}</link><description>概要</description><pubDate>{pub_date}</pubDate></item>"


class CollectMainExitCodeTest(unittest.TestCase):
    """collect.py全体の終了コード契約(0=新規あり/2=重複除外の結果0件)を、
    ネットワークI/Oをモックして検証する。
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp = pathlib.Path(self._tmpdir.name)

    def run_collect(self, xml_bytes, recent_links_path, out_path, pending_path):
        argv = [
            "collect.py",
            "--out", str(out_path),
            "--pending-out", str(pending_path),
            "--recent-links", str(recent_links_path),
        ]
        with mock.patch.object(collect, "read_feeds", return_value=["https://example.com/feed.xml"]), \
             mock.patch.object(collect, "fetch", return_value=xml_bytes), \
             mock.patch.object(sys, "argv", argv):
            try:
                collect.main()
                return 0
            except SystemExit as e:
                return e.code

    def test_exit_2_when_all_duplicates(self):
        recent_path = self.tmp / "recent.json"
        rss_dedup.write_json_atomic(recent_path, {"links": {"https://example.com/a": "2026-07-16"}})
        original_content = recent_path.read_text(encoding="utf-8")
        xml = SAMPLE_RSS_TEMPLATE.format(items=make_rss_item_xml("重複記事", "https://example.com/a")).encode()
        out_path = self.tmp / "raw.json"
        pending_path = self.tmp / "pending.json"
        rc = self.run_collect(xml, recent_path, out_path, pending_path)
        self.assertEqual(rc, collect.EXIT_NO_NEW_ARTICLES)
        self.assertFalse(out_path.exists())
        self.assertFalse(pending_path.exists())
        self.assertEqual(
            recent_path.read_text(encoding="utf-8"), original_content,
            "collect.pyは既存の台帳ファイルを書き換えてはいけない",
        )

    def test_exit_0_with_new_articles(self):
        recent_path = self.tmp / "recent.json"
        xml = SAMPLE_RSS_TEMPLATE.format(items=make_rss_item_xml("新規記事", "https://example.com/new")).encode()
        out_path = self.tmp / "raw.json"
        pending_path = self.tmp / "pending.json"
        rc = self.run_collect(xml, recent_path, out_path, pending_path)
        self.assertEqual(rc, 0)
        self.assertTrue(out_path.exists())
        articles = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(len(articles), 1)
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
        self.assertEqual(pending["links"], ["https://example.com/new"])
        # Codexレビュー対応(Critical): collect.pyは台帳ファイルへ一切
        # 書き込んではいけない(存在しなかった場合、ファイルを新規作成
        # することも含む)。実ファイルへの書き込みはcommit_pendingのみ。
        self.assertFalse(recent_path.exists(), "collect.pyは台帳ファイルを直接作成してはいけない")


if __name__ == "__main__":
    unittest.main()
