#!/usr/bin/env python3
"""run.shのWork/RSS分岐・Issue close呼び出し構造の検証(Phase 2a)。

run.sh自体はclaude CLI・実際のgh認証・ネットワークに依存するため、
CIやこのテスト環境ではエンドツーエンド実行できない。そのため、run.shの
テキスト構造を検査し、以下を静的に保証する:

- scripts/import_work_news.py fetch の終了コード(0/2/その他)で
  3方向に分岐している
- scripts/collect.py(RSS)は、Workで新規記事が得られなかった場合の
  分岐内でのみ呼ばれる(無条件には呼ばれない → 同一実行内でWork/RSSが
  混在しない)
- commit-pending(台帳更新+close)は、exit 0(SOURCE=work、validate成功後)
  とexit 2(duplicate_only)の場合にのみ呼ばれ、それ以外(RSSフォール
  バック)では呼ばれない

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

    def test_work_fetch_exit_code_is_captured_and_branches_three_ways(self):
        self.assertIn("scripts/import_work_news.py fetch", self.text)
        self.assertRegex(
            self.text,
            r"FETCH_RC=\$\?",
            "run.shはimport_work_news.py fetchの終了コードを変数に捕捉する必要がある",
        )
        self.assertRegex(
            self.text,
            r'case "\$\{FETCH_RC\}" in',
            "run.shはFETCH_RCで分岐するcase文を持つ必要がある",
        )
        # 0(Work成功)/2(duplicate_only)/*(フォールバック)の3分岐がある。
        case_match = re.search(r'case "\$\{FETCH_RC\}" in\n(.*?)\nesac', self.text, re.S)
        self.assertIsNotNone(case_match)
        case_body = case_match.group(1)
        self.assertRegex(case_body, re.compile(r"^\s*0\)", re.MULTILINE))
        self.assertRegex(case_body, re.compile(r"^\s*2\)", re.MULTILINE))
        self.assertRegex(case_body, re.compile(r"^\s*\*\)", re.MULTILINE))

    def test_source_work_only_set_in_exit_code_zero_branch(self):
        case_match = re.search(r'case "\$\{FETCH_RC\}" in\n(.*?)\nesac', self.text, re.S)
        self.assertIsNotNone(case_match)
        case_body = case_match.group(1)
        branch_0 = re.search(r"0\)\n(.*?);;", case_body, re.S).group(1)
        self.assertIn("SOURCE=work", branch_0)

        branch_2 = re.search(r"2\)\n(.*?);;", case_body, re.S).group(1)
        self.assertNotIn("SOURCE=work", branch_2, "duplicate_only(exit 2)は下書き生成をWorkに切り替えてはいけない")

        branch_default = re.search(r"\*\)\n(.*?);;", case_body, re.S).group(1)
        self.assertNotIn("SOURCE=work", branch_default)

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

    def test_commit_pending_called_only_for_work_success_or_duplicate_only(self):
        case_match = re.search(r'case "\$\{FETCH_RC\}" in\n(.*?)\nesac', self.text, re.S)
        case_body = case_match.group(1)
        branch_2 = re.search(r"2\)\n(.*?);;", case_body, re.S).group(1)
        self.assertIn("commit-pending", branch_2, "duplicate_only(exit 2)ではその場でcommit-pending(台帳更新+close)を呼ぶ")
        branch_default = re.search(r"\*\)\n(.*?);;", case_body, re.S).group(1)
        self.assertNotIn("commit-pending", branch_default, "RSSフォールバックのみの場合はcommit-pendingを呼ばない")

        m = re.search(r'if \[ "\$\{SOURCE\}" = "work" \]; then\n(.*?)\nfi', self.text, re.S)
        self.assertIsNotNone(m, "SOURCE=workの条件ブロック(validate成功後)が見つかりません")
        work_block = m.group(1)
        self.assertIn("commit-pending", work_block)

        # RSSフォールバック分岐(SOURCE=rssのcollect.pyブロック)には
        # commit-pendingが含まれない。
        rss_block = re.search(r'if \[ "\$\{SOURCE\}" = "rss" \]; then\n(.*?)\nfi', self.text, re.S).group(1)
        self.assertNotIn("commit-pending", rss_block)

    def test_commit_pending_passes_repo_for_close(self):
        case_match = re.search(r'case "\$\{FETCH_RC\}" in\n(.*?)\nesac', self.text, re.S)
        branch_2 = re.search(r"2\)\n(.*?);;", case_match.group(1), re.S).group(1)
        self.assertIn("--repo", branch_2, "duplicate_only分岐のcommit-pendingは--repoを渡してcloseを有効化する必要がある")

        work_block = re.search(r'if \[ "\$\{SOURCE\}" = "work" \]; then\n(.*?)\nfi', self.text, re.S).group(1)
        self.assertIn("--repo", work_block, "Work成功時のcommit-pendingは--repoを渡してcloseを有効化する必要がある")

    def test_no_forbidden_gh_write_subcommands_in_run_sh(self):
        forbidden = ["issue comment", "issue edit", "issue reopen", "issue delete", "--add-label", "--remove-label"]
        for snippet in forbidden:
            self.assertNotIn(snippet, self.text)

    def test_set_euo_pipefail_present(self):
        self.assertIn("set -euo pipefail", self.text)


if __name__ == "__main__":
    unittest.main()
