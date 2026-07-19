#!/usr/bin/env python3
"""scripts/serve_inbox.py のテスト(異世界ニホン5コマ構成 Phase 1)。

受信アプリ用ローカルHTTPサーバーの純粋関数部分(Packet一覧の取得、単一
Packetの読み込み、ファイル名の安全性検証)を検証する。実際にHTTPサーバー
を起動するテストは行わない(list_packets/load_packetを直接呼び出す)。
PACKETS_DIRは一時ディレクトリへ差し替えてテストする。Python標準
ライブラリのみを使用する(unittest, unittest.mock, json, pathlib,
tempfile)。
"""
import json
import pathlib
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import serve_inbox as si  # noqa: E402


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


class ListPacketsTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.packets_dir = pathlib.Path(self._tmpdir.name)
        self._patcher = mock.patch.object(si, "PACKETS_DIR", self.packets_dir)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_missing_directory_returns_empty_list(self):
        missing = self.packets_dir / "does-not-exist"
        with mock.patch.object(si, "PACKETS_DIR", missing):
            self.assertEqual(si.list_packets(), [])

    def test_empty_directory_returns_empty_list(self):
        self.assertEqual(si.list_packets(), [])

    def test_valid_packet_included_with_title_created_at_status(self):
        write_json(
            self.packets_dir / "a.json",
            {
                "created_at": "2026-07-19T09:00:00+09:00",
                "source": {"title": "テストタイトル", "url": "https://example.com", "summary": "s"},
            },
        )
        items = si.list_packets()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["filename"], "a.json")
        self.assertEqual(items[0]["title"], "テストタイトル")
        self.assertEqual(items[0]["created_at"], "2026-07-19T09:00:00+09:00")
        self.assertEqual(items[0]["status"], "生成待ち")

    def test_malformed_json_skipped(self):
        (self.packets_dir / "broken.json").write_text("{not valid json", encoding="utf-8")
        self.assertEqual(si.list_packets(), [])

    def test_non_dict_root_skipped(self):
        write_json(self.packets_dir / "list.json", ["not", "a", "dict"])
        self.assertEqual(si.list_packets(), [])

    def test_non_json_files_ignored(self):
        (self.packets_dir / "note.txt").write_text("hello", encoding="utf-8")
        self.assertEqual(si.list_packets(), [])

    def test_missing_source_does_not_crash(self):
        write_json(self.packets_dir / "b.json", {"created_at": "2026-07-19T09:00:00+09:00"})
        items = si.list_packets()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "")

    def test_multiple_packets_sorted_by_filename(self):
        write_json(self.packets_dir / "b.json", {"source": {"title": "B"}})
        write_json(self.packets_dir / "a.json", {"source": {"title": "A"}})
        items = si.list_packets()
        self.assertEqual([i["filename"] for i in items], ["a.json", "b.json"])

    def test_symlink_escaping_packets_dir_excluded_from_list(self):
        # load_packetだけでなくlist_packetsも、PACKETS_DIR外を指す
        # シンボリックリンクを一覧から除外することを確認する
        # (Codexレビュー指摘: 以前はload_packetのみがこの境界チェックを
        # 持っていた)。
        outside_dir = tempfile.TemporaryDirectory()
        self.addCleanup(outside_dir.cleanup)
        outside_file = pathlib.Path(outside_dir.name) / "secret.json"
        write_json(outside_file, {"source": {"title": "秘密の記事"}})

        link_path = self.packets_dir / "link.json"
        try:
            link_path.symlink_to(outside_file)
        except (OSError, NotImplementedError):
            self.skipTest("この環境はシンボリックリンクを作成できません")

        items = si.list_packets()
        self.assertEqual(items, [])


class LoadPacketTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.packets_dir = pathlib.Path(self._tmpdir.name)
        self._patcher = mock.patch.object(si, "PACKETS_DIR", self.packets_dir)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_valid_filename_loads_packet(self):
        write_json(self.packets_dir / "a.json", {"source": {"title": "A"}})
        packet = si.load_packet("a.json")
        self.assertEqual(packet["source"]["title"], "A")

    def test_missing_file_returns_none(self):
        self.assertIsNone(si.load_packet("missing.json"))

    def test_malformed_json_returns_none(self):
        (self.packets_dir / "broken.json").write_text("{not valid", encoding="utf-8")
        self.assertIsNone(si.load_packet("broken.json"))

    def test_path_traversal_style_names_rejected(self):
        # SAFE_FILENAME_REがスラッシュ・".."を含む名前を拒否することを
        # 確認する(ディレクトリトラバーサル対策)。
        for bad_name in [
            "../secret.json",
            "..%2f..%2fetc%2fpasswd",
            "sub/dir.json",
            "a.json/../../etc/passwd",
            "a.json%00.txt",
            "",
        ]:
            with self.subTest(bad_name=bad_name):
                self.assertIsNone(si.load_packet(bad_name))

    def test_non_json_extension_rejected(self):
        (self.packets_dir / "a.txt").write_text("{}", encoding="utf-8")
        self.assertIsNone(si.load_packet("a.txt"))

    def test_symlink_escaping_packets_dir_rejected(self):
        # PACKETS_DIR外を指すシンボリックリンクは、resolve()後の親ディレクトリ
        # 比較で弾かれることを確認する。
        outside_dir = tempfile.TemporaryDirectory()
        self.addCleanup(outside_dir.cleanup)
        outside_file = pathlib.Path(outside_dir.name) / "secret.json"
        write_json(outside_file, {"secret": True})

        link_path = self.packets_dir / "link.json"
        try:
            link_path.symlink_to(outside_file)
        except (OSError, NotImplementedError):
            self.skipTest("この環境はシンボリックリンクを作成できません")

        self.assertIsNone(si.load_packet("link.json"))


class SafeFilenameRegexTest(unittest.TestCase):
    def test_valid_filenames_accepted(self):
        for name in ["2026-07-19.json", "a_b.c-1.json", "PACKET.json"]:
            with self.subTest(name=name):
                self.assertTrue(si.SAFE_FILENAME_RE.match(name))

    def test_invalid_filenames_rejected(self):
        for name in ["../a.json", "a/b.json", "a.json.bak", "a.JSON", "", "a json.json"]:
            with self.subTest(name=name):
                self.assertFalse(si.SAFE_FILENAME_RE.match(name))


class HttpRoutingTest(unittest.TestCase):
    """実際にサーバーを起動し、do_GET・PACKET_PATH_REを生のHTTPリクエスト
    経由で検証する(Codexレビュー指摘: 従来のテストは純粋関数のみを検証
    しており、ルーティング層自体は未検証だった)。
    """

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.packets_dir = pathlib.Path(cls._tmpdir.name)
        cls._patcher = mock.patch.object(si, "PACKETS_DIR", cls.packets_dir)
        cls._patcher.start()
        write_json(
            cls.packets_dir / "a.json",
            {"created_at": "2026-07-19T00:00:00Z", "source": {"title": "A"}},
        )

        cls.server = si.ThreadingHTTPServer(("127.0.0.1", 0), si.InboxHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls._patcher.stop()
        cls._tmpdir.cleanup()

    def _get(self, path):
        url = "http://127.0.0.1:" + str(self.port) + path
        try:
            with urllib.request.urlopen(url, timeout=5) as res:
                return res.status, res.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read()

    def test_index_served(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"<html", body.lower())

    def test_packets_list_endpoint(self):
        status, body = self._get("/api/packets")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual([i["filename"] for i in data], ["a.json"])

    def test_packet_detail_endpoint(self):
        status, body = self._get("/api/packets/a.json")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["source"]["title"], "A")

    def test_unknown_packet_returns_404(self):
        status, _ = self._get("/api/packets/missing.json")
        self.assertEqual(status, 404)

    def test_url_encoded_traversal_rejected(self):
        for path in [
            "/api/packets/%2e%2e%2fetc%2fpasswd",
            "/api/packets/..%2fsecret.json",
            "/api/packets/..%2f..%2fetc%2fpasswd.json",
        ]:
            with self.subTest(path=path):
                status, _ = self._get(path)
                self.assertEqual(status, 404, path)

    def test_query_string_appended_to_filename_rejected(self):
        status, _ = self._get("/api/packets/a.json?x=1")
        self.assertEqual(status, 404)

    def test_unrelated_path_returns_404(self):
        status, _ = self._get("/does-not-exist")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
