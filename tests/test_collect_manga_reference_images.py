#!/usr/bin/env python3
"""scripts/collect_manga_reference_images.py のテスト。

comfyui-mobile-system側のローカルチェックアウト(案1: ネットワーク非依存の
ローカルパスコピー方式)を模した一時ディレクトリ構造を作り、論理ID解決・
収集・エラーハンドリングを検証する。Python標準ライブラリのみを使用する
(unittest, pathlib, sys, json, subprocess, tempfile)。
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import collect_manga_reference_images as cmri  # noqa: E402


def _make_fake_comfyui_root(base_dir):
    """comfyui-mobile-system側のreference_imagesツリーを模した最小構造を
    base_dir配下に作る。ハルトの表情2種・turnaround1種を用意する。
    """
    root = pathlib.Path(base_dir)
    haruto_dir = root / "profiles" / "sdxl" / "isekai_nihon_manga" / "reference_images" / "haruto"
    (haruto_dir / "images").mkdir(parents=True)
    (haruto_dir / "manifest.json").write_text(
        json.dumps({"neutral": "00-neutral.png", "surprise-medium": "05-surprise-medium.png"}),
        encoding="utf-8",
    )
    (haruto_dir / "images" / "00-neutral.png").write_bytes(b"fake-neutral")
    (haruto_dir / "images" / "05-surprise-medium.png").write_bytes(b"fake-surprise")

    (haruto_dir / "turnaround" / "images").mkdir(parents=True)
    (haruto_dir / "turnaround" / "manifest.json").write_text(
        json.dumps({"front": "00-front.png"}), encoding="utf-8"
    )
    (haruto_dir / "turnaround" / "images" / "00-front.png").write_bytes(b"fake-front")

    return root


class ParseReferenceImageTest(unittest.TestCase):
    def test_bare_two_segment_defaults_to_expressions(self):
        character, category, tag = cmri.parse_reference_image("haruto/neutral.png")
        self.assertEqual((character, category, tag), ("haruto", "expressions", "neutral"))

    def test_explicit_category_form(self):
        character, category, tag = cmri.parse_reference_image("haruto/turnaround/front.png")
        self.assertEqual((character, category, tag), ("haruto", "turnaround", "front"))

    def test_unknown_category_rejected(self):
        with self.assertRaises(cmri.CollectError):
            cmri.parse_reference_image("haruto/poses/front.png")

    def test_missing_slash_rejected(self):
        with self.assertRaises(cmri.CollectError):
            cmri.parse_reference_image("haruto-neutral.png")

    def test_reserved_underscore_segment_rejected(self):
        with self.assertRaises(cmri.CollectError):
            cmri.parse_reference_image("haruto/_comment.png")

    def test_dot_only_segment_rejected(self):
        with self.assertRaises(cmri.CollectError):
            cmri.parse_reference_image("../neutral.png")

    def test_non_png_rejected(self):
        with self.assertRaises(cmri.CollectError):
            cmri.parse_reference_image("haruto/neutral.jpg")


class ResolveSourcePathTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.comfyui_root = _make_fake_comfyui_root(self._tmpdir.name)

    def test_resolves_expressions_image(self):
        path = cmri.resolve_source_path(self.comfyui_root, "haruto/surprise-medium.png")
        self.assertTrue(path.is_file())
        self.assertEqual(path.name, "05-surprise-medium.png")

    def test_resolves_turnaround_image(self):
        path = cmri.resolve_source_path(self.comfyui_root, "haruto/turnaround/front.png")
        self.assertTrue(path.is_file())
        self.assertEqual(path.name, "00-front.png")

    def test_missing_manifest_rejected(self):
        with self.assertRaises(cmri.CollectError):
            cmri.resolve_source_path(self.comfyui_root, "natsuki/neutral.png")

    def test_unknown_tag_rejected(self):
        with self.assertRaises(cmri.CollectError):
            cmri.resolve_source_path(self.comfyui_root, "haruto/nonexistent-tag.png")

    def test_manifest_filename_path_traversal_rejected(self):
        haruto_dir = (
            self.comfyui_root
            / "profiles"
            / "sdxl"
            / "isekai_nihon_manga"
            / "reference_images"
            / "haruto"
        )
        (haruto_dir / "manifest.json").write_text(
            json.dumps({"neutral": "../../../etc/passwd.png"}), encoding="utf-8"
        )
        with self.assertRaises(cmri.CollectError):
            cmri.resolve_source_path(self.comfyui_root, "haruto/neutral.png")

    def test_actual_file_missing_rejected(self):
        haruto_dir = (
            self.comfyui_root
            / "profiles"
            / "sdxl"
            / "isekai_nihon_manga"
            / "reference_images"
            / "haruto"
        )
        (haruto_dir / "manifest.json").write_text(
            json.dumps({"neutral": "00-neutral.png", "missing-tag": "99-missing.png"}),
            encoding="utf-8",
        )
        with self.assertRaises(cmri.CollectError):
            cmri.resolve_source_path(self.comfyui_root, "haruto/missing-tag.png")


class ExtractReferenceImagesFromPacketTest(unittest.TestCase):
    """Manga News Packet v2(panels[].performers[]・scribe_panel)からの
    reference_image抽出を検証する。
    """

    def test_performers_extracted(self):
        packet = {
            "panels": [
                {
                    "performers": [
                        {"name": "ハルト", "reference_image": "haruto/neutral.png"},
                        {"name": "ナツキ", "reference_image": "natsuki/neutral.png"},
                    ]
                }
            ]
        }
        result = cmri.extract_reference_images_from_packet(packet)
        self.assertEqual(set(result), {"haruto/neutral.png", "natsuki/neutral.png"})

    def test_duplicates_removed_across_panels(self):
        packet = {
            "panels": [
                {"performers": [{"name": "ハルト", "reference_image": "haruto/neutral.png"}]},
                {"performers": [{"name": "ハルト", "reference_image": "haruto/neutral.png"}]},
            ]
        }
        self.assertEqual(cmri.extract_reference_images_from_packet(packet), ["haruto/neutral.png"])

    def test_scribe_panel_reference_and_emblem_extracted(self):
        packet = {
            "panels": [],
            "scribe_panel": {
                "reference_image": "scribe/neutral.png",
                "emblem_reference": "scribe/equipment/official-scribe-bureau-emblem.png",
            },
        }
        result = cmri.extract_reference_images_from_packet(packet)
        self.assertEqual(
            set(result),
            {"scribe/neutral.png", "scribe/equipment/official-scribe-bureau-emblem.png"},
        )

    def test_no_panels_or_scribe_panel_returns_empty(self):
        self.assertEqual(cmri.extract_reference_images_from_packet({}), [])


class CollectTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.comfyui_root = _make_fake_comfyui_root(self._tmpdir.name)

        self._dest_tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dest_tmpdir.cleanup)
        self.dest_dir = pathlib.Path(self._dest_tmpdir.name) / "collected"

    def test_collect_copies_files_with_flattened_names(self):
        results = cmri.collect(
            self.comfyui_root, ["haruto/neutral.png", "haruto/turnaround/front.png"], self.dest_dir
        )
        self.assertEqual(len(results), 2)
        for ref, path in results.items():
            self.assertTrue(path.is_file())
            self.assertEqual(path.name, ref.replace("/", "__"))

    def test_missing_comfyui_root_rejected(self):
        missing_root = pathlib.Path(self._tmpdir.name) / "does-not-exist"
        with self.assertRaises(cmri.CollectError):
            cmri.collect(missing_root, ["haruto/neutral.png"], self.dest_dir)

    def test_partial_failure_copies_nothing(self):
        # 1件でも解決に失敗した場合、成功したものも含め何もコピーしない
        # (Packet全体で必要な画像が揃わない限り、中途半端な収集結果を
        # 残さないため)。
        with self.assertRaises(cmri.CollectError):
            cmri.collect(
                self.comfyui_root,
                ["haruto/neutral.png", "haruto/nonexistent-tag.png"],
                self.dest_dir,
            )
        self.assertFalse(self.dest_dir.exists())


class CliTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.comfyui_root = _make_fake_comfyui_root(self._tmpdir.name)

        self._dest_tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dest_tmpdir.cleanup)
        self.dest_dir = pathlib.Path(self._dest_tmpdir.name) / "collected"

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "collect_manga_reference_images.py"), *args],
            capture_output=True,
            text=True,
        )

    def test_logical_id_mode(self):
        result = self._run(
            str(self.dest_dir),
            "--logical-id",
            "haruto/neutral.png",
            "--comfyui-root",
            str(self.comfyui_root),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.dest_dir / "haruto__neutral.png").is_file())

    def test_packet_mode(self):
        packet_path = pathlib.Path(self._tmpdir.name) / "packet.json"
        packet_path.write_text(
            json.dumps(
                {
                    "panels": [
                        {
                            "performers": [
                                {"name": "ハルト", "reference_image": "haruto/surprise-medium.png"}
                            ]
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        result = self._run(
            str(self.dest_dir),
            "--packet",
            str(packet_path),
            "--comfyui-root",
            str(self.comfyui_root),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.dest_dir / "haruto__surprise-medium.png").is_file())

    def test_missing_comfyui_root_reports_clear_error(self):
        result = self._run(
            str(self.dest_dir),
            "--logical-id",
            "haruto/neutral.png",
            "--comfyui-root",
            str(pathlib.Path(self._tmpdir.name) / "does-not-exist"),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("comfyui-mobile-systemのパスが見つかりません", result.stderr)

    def test_mutually_exclusive_source_args_rejected(self):
        result = self._run(
            str(self.dest_dir),
            "--logical-id",
            "haruto/neutral.png",
            "--default-turnaround",
            "--comfyui-root",
            str(self.comfyui_root),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_missing_packet_file_reports_clear_error_not_traceback(self):
        # セルフレビューで発見: 修正前は open() の FileNotFoundError が
        # そのままPythonトレースバックとして出力されていた。
        result = self._run(
            str(self.dest_dir),
            "--packet",
            str(pathlib.Path(self._tmpdir.name) / "does-not-exist.json"),
            "--comfyui-root",
            str(self.comfyui_root),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("[ERROR]", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_invalid_json_packet_file_reports_clear_error_not_traceback(self):
        packet_path = pathlib.Path(self._tmpdir.name) / "broken.json"
        packet_path.write_text("{not valid json", encoding="utf-8")
        result = self._run(
            str(self.dest_dir),
            "--packet",
            str(packet_path),
            "--comfyui-root",
            str(self.comfyui_root),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("[ERROR]", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
