#!/usr/bin/env python3
"""run.shのWork/RSS分岐構造の検証(Phase 2a)。

run.sh自体はclaude CLI・実際のgh認証・ネットワークに依存するため、
CIやこのテスト環境ではエンドツーエンド実行できない。そのため、run.shの
テキスト構造を検査し、以下を静的に保証する:

- scripts/import_work_news.py fetch の成否で分岐している
- scripts/collect.py(RSS)は、Work取得が失敗した場合の分岐内でのみ
  呼ばれる(無条件には呼ばれない → 同一実行内でWork/RSSが混在しない)
- 台帳のcommit-pendingは、SOURCE=workの場合のみ呼ばれる

Python標準ライブラリのみを使用する(unittest, pathlib, re)。
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUN_SH = ROOT / "run.sh"


class RunShRoutingTest(unittest.TestCase):
    def setUp(self):
        self.text = RUN_SH.read_text(encoding="utf-8")

    def test_run_sh_exists(self):
        self.assertTrue(RUN_SH.is_file())

    def test_work_fetch_result_drives_branch(self):
        self.assertRegex(
            self.text,
            r"if python3 scripts/import_work_news\.py fetch",
            "run.shはimport_work_news.py fetchの終了コードで分岐する必要がある",
        )

    def test_collect_py_only_called_inside_rss_fallback_branch(self):
        # collect.pyの呼び出しが、"if [ \"${SOURCE}\" = \"rss\" ]" のような
        # RSSフォールバック条件のブロック内にのみ現れることを確認する
        # (Work成功時に無条件でRSSも実行される=混在、を防ぐ構造チェック)。
        m = re.search(r'if \[ "\$\{SOURCE\}" = "rss" \]; then\n(.*?)\nfi', self.text, re.S)
        self.assertIsNotNone(m, "SOURCE=rssの条件ブロックが見つかりません")
        rss_block = m.group(1)
        self.assertIn("scripts/collect.py", rss_block)

        # 条件ブロックの外(全体からブロック本体を除いたテキスト)に
        # collect.py呼び出しが無条件で存在しないことを確認する。
        outside = self.text.replace(rss_block, "")
        self.assertNotIn("python3 scripts/collect.py", outside)

    def test_commit_pending_only_called_for_work_source(self):
        m = re.search(r'if \[ "\$\{SOURCE\}" = "work" \]; then\n(.*?)\nfi', self.text, re.S)
        self.assertIsNotNone(m, "SOURCE=workの条件ブロックが見つかりません")
        work_block = m.group(1)
        self.assertIn("commit-pending", work_block)

        outside = self.text.replace(work_block, "")
        self.assertNotIn("commit-pending", outside)

    def test_set_euo_pipefail_present(self):
        self.assertIn("set -euo pipefail", self.text)


if __name__ == "__main__":
    unittest.main()
