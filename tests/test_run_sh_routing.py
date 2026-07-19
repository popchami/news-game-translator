#!/usr/bin/env python3
"""run.shのWork/RSS分岐・日またぎ重複対応・同日上書き防止の構造検証
(Phase 2a〜2c)。

run.sh自体はclaude CLI・実際のgh認証・ネットワークに依存するため、
CIやこのテスト環境ではエンドツーエンド実行できない。そのため、run.shの
テキスト構造を検査し、以下を静的に保証する:

- 同日の下書き(drafts/YYYY-MM-DD.md)が既に存在する場合、収集・変換・
  検証を一切行わずに正常終了する(Phase 2c)
- scripts/import_work_news.py fetch の終了コード(0/2/その他)で
  3方向に分岐している
- scripts/collect.py(RSS)は、Workで新規記事が得られなかった場合の
  分岐内でのみ呼ばれる(無条件には呼ばれない → 同一実行内でWork/RSSが
  混在しない)
- scripts/collect.py の終了コード(0/2/その他)に応じて、新規RSS記事
  なし(exit 0)・収集失敗(exit 1)を正しく分岐する(Phase 2c)
- commit-pending(台帳更新のみ。closeは行わない)は、exit 0
  (SOURCE=work、validate成功後)とexit 2(duplicate_only)の場合にのみ
  呼ばれ、それ以外(RSSフォールバック)では呼ばれない
- RSSリンク台帳のcommit-pendingは、validate成功後のSOURCE=rss分岐でのみ
  呼ばれる(Phase 2c)
- run.shにIssueのclose・コメント・ラベル・本文/タイトル変更に相当する
  gh呼び出しが存在しない(Termuxは読み取り専用)

Python標準ライブラリのみを使用する(unittest, pathlib, re)。
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUN_SH = ROOT / "run.sh"

IF_OPEN_RE = re.compile(r'^\s*if .*; then\s*$')
FI_RE = re.compile(r'^\s*fi\s*$')


def extract_if_block(text, condition_snippet):
    """condition_snippetを含む 'if ...; then' 行から、対応する 'fi' 行
    (ネストしたif/fiを正しく数えたうえで)までの本体を返す。
    見つからない場合はNone。
    """
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if condition_snippet in line and IF_OPEN_RE.match(line):
            start_idx = i
            break
    if start_idx is None:
        return None
    depth = 1
    body_lines = []
    for line in lines[start_idx + 1:]:
        if IF_OPEN_RE.match(line):
            depth += 1
        elif FI_RE.match(line):
            depth -= 1
            if depth == 0:
                break
        body_lines.append(line)
    return "\n".join(body_lines)


class RunShRoutingTest(unittest.TestCase):
    def setUp(self):
        self.text = RUN_SH.read_text(encoding="utf-8")

    def test_run_sh_exists(self):
        self.assertTrue(RUN_SH.is_file())

    def test_same_day_draft_guard_is_first_and_skips_everything(self):
        # 同日下書き存在チェックが、Work Issue確認より前(スクリプト冒頭)に
        # あり、既存の場合は何もせずexit 0することを確認する。
        guard_block = extract_if_block(self.text, '-s "${OUT}"')
        self.assertIsNotNone(guard_block, "同日下書き存在チェックのif文が見つかりません")
        self.assertIn("exit 0", guard_block)

        guard_pos = self.text.index('-s "${OUT}"')
        work_fetch_pos = self.text.index("scripts/import_work_news.py fetch")
        self.assertLess(guard_pos, work_fetch_pos, "同日下書きチェックはWork Issue確認より前に行う必要がある")

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
        # RSSフォールバック条件のブロック内(ネストしたif/fiも正しく含む)
        # にのみ現れることを確認する(Work成功時に無条件でRSSも実行される
        # =混在、を防ぐ構造チェック)。
        rss_block = extract_if_block(self.text, '"${SOURCE}" = "rss"')
        self.assertIsNotNone(rss_block, "SOURCE=rssの条件ブロックが見つかりません")
        self.assertIn("scripts/collect.py", rss_block)

        outside = self.text.replace(rss_block, "")
        self.assertNotIn("python3 scripts/collect.py", outside)

    def test_collect_exit_code_handled_for_zero_new_and_failure(self):
        # collect.py実行後、終了コードを捕捉し、2(新規0件)はexit 0の分岐へ、
        # それ以外の非0(収集失敗)はexit 1の分岐へ、それぞれ正しく
        # 結びついていることを確認する(分岐が入れ替わっていないか)。
        rss_block = extract_if_block(self.text, '"${SOURCE}" = "rss"')
        self.assertIsNotNone(rss_block)
        self.assertIn("COLLECT_RC=$?", rss_block)

        m = re.search(
            r'if \[ "\$\{COLLECT_RC\}" -eq 2 \]; then\n(.*?)\n\s*elif \[ "\$\{COLLECT_RC\}" -ne 0 \]; then\n(.*?)\n\s*(?=fi)',
            rss_block,
            re.S,
        )
        self.assertIsNotNone(m, "COLLECT_RCのif/elif構造が見つかりません")
        zero_new_branch, failure_branch = m.group(1), m.group(2)
        self.assertIn("exit 0", zero_new_branch)
        self.assertNotIn("exit 1", zero_new_branch, "新規0件の分岐にexit 1が混入している(分岐が入れ替わっている可能性)")
        self.assertIn("exit 1", failure_branch)
        self.assertNotIn("exit 0", failure_branch, "収集失敗の分岐にexit 0が混入している(分岐が入れ替わっている可能性)")

    def test_commit_pending_called_only_for_work_success_or_duplicate_only(self):
        case_match = re.search(r'case "\$\{FETCH_RC\}" in\n(.*?)\nesac', self.text, re.S)
        case_body = case_match.group(1)
        branch_2 = re.search(r"2\)\n(.*?);;", case_body, re.S).group(1)
        self.assertIn("commit-pending", branch_2, "duplicate_only(exit 2)ではその場でcommit-pending(台帳更新のみ)を呼ぶ")
        branch_default = re.search(r"\*\)\n(.*?);;", case_body, re.S).group(1)
        self.assertNotIn("commit-pending", branch_default, "RSSフォールバックのみの場合はcommit-pendingを呼ばない")

        work_block = extract_if_block(self.text, '"${SOURCE}" = "work"')
        self.assertIsNotNone(work_block, "SOURCE=workの条件ブロック(validate成功後)が見つかりません")
        self.assertIn("import_work_news.py commit-pending", work_block)

        # RSSフォールバック分岐(SOURCE=rssのcollect.pyブロック)には
        # Work側のcommit-pendingが含まれない。
        rss_block = extract_if_block(self.text, '"${SOURCE}" = "rss"')
        self.assertNotIn("import_work_news.py commit-pending", rss_block)

    def test_rss_ledger_commit_pending_called_only_after_rss_success(self):
        # RSSリンク台帳のcommit-pendingは、validate成功後のSOURCE=rss分岐
        # (下書き移動の後)でのみ呼ばれる。
        final_rss_blocks = [
            m for m in re.finditer(r'if \[ "\$\{SOURCE\}" = "rss" \]; then\n(.*?)\nfi', self.text, re.S)
        ]
        self.assertTrue(
            any("rss_dedup.py commit-pending" in m.group(1) for m in final_rss_blocks),
            "validate成功後にRSSリンク台帳のcommit-pendingを呼ぶブロックが見つかりません",
        )
        # collect.py自体の呼び出しブロック(重複除外の実行)にはRSSリンク
        # 台帳のcommit-pendingが含まれない(全工程成功前に確定させない)。
        collect_block = extract_if_block(self.text, '"${SOURCE}" = "rss"')
        self.assertNotIn("rss_dedup.py commit-pending", collect_block)

    def test_no_forbidden_gh_write_subcommands_in_run_sh(self):
        forbidden = [
            "issue close",
            "issue comment",
            "issue edit",
            "issue reopen",
            "issue delete",
            "--add-label",
            "--remove-label",
            "--repo",  # commit-pendingにはrepoを渡さない(closeを行わないため不要)
        ]
        # 通常モードのfetchと緊急モードのfetch-singleは、いずれも読み取り
        # 専用のgh呼び出し(--repoを含む)を正当に持つため、両方を除外して
        # からforbiddenスニペットの想定外混入を検査する。
        text_without_fetch_calls = re.sub(
            r"python3 scripts/import_work_news\.py fetch.*?--pending-out \"\$\{WORK_PENDING\}\"",
            "",
            self.text,
            flags=re.S,
        )
        text_without_fetch_calls = re.sub(
            r"python3 scripts/import_work_news\.py fetch-single.*?--pending-out \"\$\{URGENT_PENDING\}\"",
            "",
            text_without_fetch_calls,
            flags=re.S,
        )
        for snippet in forbidden:
            self.assertNotIn(snippet, text_without_fetch_calls, f"'{snippet}' が想定外の箇所に存在します")

    def test_close_retry_ledger_references_removed(self):
        self.assertNotIn("CLOSE_RETRY", self.text)
        self.assertNotIn("close-retry", self.text)
        self.assertNotIn("pending_work_issue_closures", self.text)

    def test_set_euo_pipefail_present(self):
        self.assertIn("set -euo pipefail", self.text)

    def test_whole_script_lock_precedes_mode_branching(self):
        # 通常モードと緊急モードの同時実行による台帳競合(Codexレビュー
        # 指摘)を防ぐため、flockによる排他ロックがURGENT_MODEの分岐より
        # 前(=両モード共通)に存在する必要がある。
        self.assertIn("flock", self.text)
        lock_pos = self.text.index("flock")
        urgent_mode_var_pos = self.text.index("URGENT_MODE=0")
        self.assertLess(lock_pos, urgent_mode_var_pos, "ロック取得は引数解析・モード分岐より前に必要")


class UrgentModeRoutingTest(unittest.TestCase):
    """緊急ニュース処理モード(--urgent --issue N)の静的構造検証(Phase 4)。

    run.sh自体はclaude CLI・gh認証に依存するためエンドツーエンドでは
    実行できない。テキスト構造を検査し、以下を静的に保証する:

    - --urgentと--issueは常にセットで必要(片方だけはusage表示して失敗)
    - --issueは正の整数のみを許可する検査がある
    - 緊急モードはRSS(collect.py)を一切呼ばない
    - 緊急モード専用のファイル名(URGENT_*)は通常モード(RAW/TMP/OUT/
      WORK_PENDING)と衝突しない別変数を使う
    - 緊急便の同一Issue上書き防止チェックがfetch-single呼び出しより前にある
    - fetch-singleの終了コード(0/2/その他)で分岐し、2はcommit-pending
      してRSSへ行かずexit 0、その他はexit 1(RSSフォールバックしない)
    - 台帳のcommit-pendingは、成功時(0→validate成功後)と重複のみ(2)
      の場合にのみ呼ばれる
    - 緊急モードのブロックにもgh書き込み系操作が存在しない
    """

    def setUp(self):
        self.text = RUN_SH.read_text(encoding="utf-8")
        urgent_start = self.text.index('if [ "${URGENT_MODE}" -eq 1 ]; then\n# 緊急ニュース処理モード')
        self.urgent_block = self.text[urgent_start:]

    def test_urgent_and_issue_required_together(self):
        self.assertIn(
            'if [ "${URGENT_MODE}" -eq 1 ] && [ -z "${URGENT_ISSUE}" ]',
            self.text,
        )
        self.assertIn(
            'if [ "${URGENT_MODE}" -eq 0 ] && [ -n "${URGENT_ISSUE}" ]',
            self.text,
        )
        # どちらの片方だけ違反ブロックも使用法を表示して非ゼロ終了する。
        for snippet in [
            'if [ "${URGENT_MODE}" -eq 1 ] && [ -z "${URGENT_ISSUE}" ]; then\n  echo "使用法:',
            'if [ "${URGENT_MODE}" -eq 0 ] && [ -n "${URGENT_ISSUE}" ]; then\n  echo "使用法:',
        ]:
            self.assertIn(snippet, self.text)

    def test_issue_number_must_be_positive_integer(self):
        self.assertRegex(
            self.text,
            re.compile(r'URGENT_ISSUE.*=~\s*\^\[1-9\]\[0-9\]\*\$'),
            "run.shは--issueが正の整数であることを検証する必要がある",
        )

    def test_urgent_block_never_calls_collect_py(self):
        self.assertNotIn("scripts/collect.py", self.urgent_block, "緊急モードはRSSへフォールバックしてはいけない")

    def test_urgent_file_variables_do_not_reuse_normal_mode_names(self):
        # 緊急モードは専用の変数名(URGENT_RAW/URGENT_TMP/URGENT_OUT/
        # URGENT_PENDING)を使い、通常モードのRAW/TMP/OUT/WORK_PENDINGと
        # 衝突しない。
        for var in ["URGENT_RAW", "URGENT_TMP", "URGENT_OUT", "URGENT_PENDING"]:
            self.assertIn(var, self.urgent_block)
        self.assertNotIn('"${RAW}"', self.urgent_block)
        self.assertNotIn('"${TMP}"', self.urgent_block)
        self.assertNotIn('"${OUT}"', self.urgent_block)
        self.assertNotIn('"${WORK_PENDING}"', self.urgent_block)

    def test_urgent_filenames_include_issue_number_suffix(self):
        self.assertIn('URGENT_SUFFIX="urgent-issue${URGENT_ISSUE}"', self.urgent_block)
        self.assertIn('URGENT_RAW="data/raw/${TODAY}-${URGENT_SUFFIX}.json"', self.urgent_block)
        self.assertIn('URGENT_TMP="drafts/.tmp_${TODAY}-${URGENT_SUFFIX}.md"', self.urgent_block)
        self.assertIn('URGENT_OUT="drafts/${TODAY}-${URGENT_SUFFIX}.md"', self.urgent_block)
        self.assertIn(
            'URGENT_PENDING="data/state/.pending_${TODAY}-${URGENT_SUFFIX}.json"', self.urgent_block
        )

    def test_urgent_overwrite_guard_precedes_fetch_single_call(self):
        guard_pos = self.urgent_block.index('-s "${URGENT_OUT}"')
        fetch_pos = self.urgent_block.index("scripts/import_work_news.py fetch-single")
        self.assertLess(guard_pos, fetch_pos, "既存の緊急下書きの上書き防止チェックはfetch-single呼び出しより前に必要")
        guard_block = extract_if_block(self.urgent_block, '-s "${URGENT_OUT}"')
        self.assertIsNotNone(guard_block)
        self.assertIn("exit 0", guard_block)

    def test_fetch_single_exit_code_branches_and_never_falls_back_to_rss(self):
        self.assertRegex(self.urgent_block, r"URGENT_FETCH_RC=\$\?")
        case_match = re.search(r'case "\$\{URGENT_FETCH_RC\}" in\n(.*?)\nesac', self.urgent_block, re.S)
        self.assertIsNotNone(case_match, "URGENT_FETCH_RCで分岐するcase文が見つかりません")
        case_body = case_match.group(1)

        branch_2 = re.search(r"2\)\n(.*?);;", case_body, re.S).group(1)
        self.assertIn("commit-pending", branch_2)
        self.assertIn("exit 0", branch_2)
        self.assertNotIn("claude -p", branch_2, "重複のみの場合はclaude -pを呼んではいけない")

        branch_default = re.search(r"\*\)\n(.*?);;", case_body, re.S).group(1)
        self.assertIn("exit 1", branch_default)
        self.assertNotIn("scripts/collect.py", branch_default, "緊急モード失敗時にRSSへフォールバックしてはいけない")

    def test_commit_pending_called_only_after_validate_success_or_duplicate(self):
        # validate成功→mvの直後にのみ、成功時のcommit-pendingが呼ばれる。
        mv_pos = self.urgent_block.index('mv "${URGENT_TMP}" "${URGENT_OUT}"')
        commit_positions = [
            m.start() for m in re.finditer(r"import_work_news\.py commit-pending", self.urgent_block)
        ]
        self.assertTrue(any(pos > mv_pos for pos in commit_positions), "validate成功(mv)後にcommit-pendingを呼ぶ必要がある")

        # commit-pending呼び出しはちょうど2箇所(重複のみ分岐と成功分岐)
        # のみで、それ以外(例えばvalidate失敗時)には存在しない。
        self.assertEqual(len(commit_positions), 2, "commit-pendingは重複のみ分岐と成功分岐の2箇所だけに存在するべき")

        # 重複のみ(2)分岐のcommit-pendingは、fetch-single呼び出しより後・
        # mvより前に位置する(claude -p/validateを経由しないため)。
        fetch_pos = self.urgent_block.index("scripts/import_work_news.py fetch-single")
        self.assertTrue(any(fetch_pos < pos < mv_pos for pos in commit_positions), "重複のみ分岐のcommit-pendingが正しい位置にありません")

    def test_urgent_block_has_no_forbidden_gh_write_subcommands(self):
        forbidden = [
            "issue close",
            "issue comment",
            "issue edit",
            "issue reopen",
            "issue delete",
            "--add-label",
            "--remove-label",
        ]
        for snippet in forbidden:
            self.assertNotIn(snippet, self.urgent_block, f"'{snippet}' が緊急モードブロックに存在します")


if __name__ == "__main__":
    unittest.main()
