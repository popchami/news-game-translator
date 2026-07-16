#!/usr/bin/env python3
"""scripts/news_schema.py のRSS記事正規化テスト(Phase 2a)。

RSSとWorkの共通スキーマへの正規化が、後方互換性を保ちつつ正しい
フィールド構成を作ることを検証する。
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from news_schema import COMMON_LIST_FIELDS, make_rss_event_key, normalize_rss_article  # noqa: E402


class RssNormalizeTest(unittest.TestCase):
    def test_normalize_rss_article_has_common_schema(self):
        article = normalize_rss_article(
            title="テスト記事", link="https://example.com/a", summary="概要", pub_date="2026-07-16T00:00:00+09:00"
        )
        self.assertEqual(article["sourceType"], "rss")
        self.assertEqual(article["title"], "テスト記事")
        self.assertEqual(article["link"], "https://example.com/a")
        self.assertEqual(article["summary"], "概要")
        self.assertEqual(article["pubDate"], "2026-07-16T00:00:00+09:00")
        self.assertEqual(article["category"], "")
        self.assertEqual(article["status"], "")
        for field in COMMON_LIST_FIELDS:
            self.assertEqual(article[field], [], f"{field}は空配列である必要")

    def test_normalize_rss_article_preserves_backward_compatible_fields(self):
        # Phase 1のvalidate.pyはtitle/link/summary/pubDateのみを参照する。
        # 正規化後もこれらのキーと値がそのまま残っていることを保証する。
        article = normalize_rss_article(title="t", link="https://example.com/b", summary="s", pub_date=None)
        self.assertEqual({"title": article["title"], "link": article["link"], "summary": article["summary"], "pubDate": article["pubDate"]},
                         {"title": "t", "link": "https://example.com/b", "summary": "s", "pubDate": None})

    def test_event_key_is_deterministic_for_same_link(self):
        key1 = make_rss_event_key("https://example.com/same")
        key2 = make_rss_event_key("https://example.com/same")
        self.assertEqual(key1, key2)

    def test_event_key_differs_for_different_links(self):
        key1 = make_rss_event_key("https://example.com/a")
        key2 = make_rss_event_key("https://example.com/b")
        self.assertNotEqual(key1, key2)


if __name__ == "__main__":
    unittest.main()
