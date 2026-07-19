#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

# 通常モードと緊急モードが同時に実行された場合、処理済み台帳
# (data/state/processed_work_issues.json)の読み込み→更新の間に競合が
# 起こり得る(Codexレビュー指摘: 未ロックのread-modify-write、pendingの
# 一時ファイル名衝突、同一Issueの二重下書き生成)。これを防ぐため、
# スクリプト全体(通常モード・緊急モードの両方)を単一の排他ロックで
# 直列化する。ロックはプロセス終了時に自動解放される(ロックファイル
# 自体はgitignore対象で内容は使わない)。
mkdir -p data/state
exec 200>data/state/.run.lock
if ! flock -w 300 200; then
  echo "[ERROR] 他のrun.sh実行が進行中のため300秒待機してもロックを取得できませんでした。しばらくしてから再実行してください。" >&2
  exit 1
fi

# 緊急ニュース処理モード(--urgent --issue ISSUE_NUMBER)の引数解析。
# 通常モードの挙動には一切影響しない(URGENT_MODE=0のときは既存どおり)。
URGENT_MODE=0
URGENT_ISSUE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --urgent)
      URGENT_MODE=1
      shift
      ;;
    --issue)
      if [ $# -lt 2 ]; then
        echo "使用法: bash run.sh --urgent --issue ISSUE_NUMBER" >&2
        exit 1
      fi
      URGENT_ISSUE="$2"
      shift 2
      ;;
    *)
      echo "[ERROR] 不明な引数です: $1" >&2
      echo "使用法: bash run.sh [--urgent --issue ISSUE_NUMBER]" >&2
      exit 1
      ;;
  esac
done

if [ "${URGENT_MODE}" -eq 1 ] && [ -z "${URGENT_ISSUE}" ]; then
  echo "使用法: bash run.sh --urgent --issue ISSUE_NUMBER" >&2
  exit 1
fi
if [ "${URGENT_MODE}" -eq 0 ] && [ -n "${URGENT_ISSUE}" ]; then
  echo "使用法: bash run.sh --urgent --issue ISSUE_NUMBER" >&2
  exit 1
fi
if [ "${URGENT_MODE}" -eq 1 ] && ! [[ "${URGENT_ISSUE}" =~ ^[1-9][0-9]*$ ]]; then
  echo "[ERROR] --issueは正の整数で指定してください: ${URGENT_ISSUE}" >&2
  exit 1
fi

TODAY=$(TZ=Asia/Tokyo date +%F)
LEDGER="data/state/processed_work_issues.json"
WORK_REPO="popchami/news-game-translator"

if [ "${URGENT_MODE}" -eq 0 ]; then
RAW="data/raw/${TODAY}.json"
TMP="drafts/.tmp_${TODAY}.md"
OUT="drafts/${TODAY}.md"
WORK_PENDING="data/state/.pending_${TODAY}.json"
RSS_LEDGER="data/state/recent_rss_links.json"
RSS_PENDING="data/state/.pending_rss_links_${TODAY}.json"

# 同日の下書きが既に完成している場合は何もしない(上書き防止)。
# Work Issueの確認すら行わない(未処理のWork Issueは翌日の実行対象として残す)。
if [ -s "${OUT}" ]; then
  echo "本日分は既に完成済みです: ${OUT}"
  exit 0
fi

rm -f "${WORK_PENDING}" "${RSS_PENDING}"

SOURCE=rss
echo "== Work Issue確認 =="
# fetchの終了コードは3値(0=新規Work記事あり/2=重複記事のみで処理済み
# 確定可/その他=RSSへフォールバック)を使う。set -eの対象外にするため
# 一時的に無効化してから終了コードを取得する。
set +e
python3 scripts/import_work_news.py fetch \
  --repo "${WORK_REPO}" --ledger "${LEDGER}" --out "${RAW}" \
  --pending-out "${WORK_PENDING}"
FETCH_RC=$?
set -e

case "${FETCH_RC}" in
  0)
    SOURCE=work
    echo "Work記事を使用します"
    ;;
  2)
    echo "[INFO] 新規Work記事は重複のみのため、処理済みとして確定します(下書きはRSSを使用。Issueはopenのまま)"
    python3 scripts/import_work_news.py commit-pending \
      --pending "${WORK_PENDING}" --ledger "${LEDGER}"
    ;;
  *)
    echo "[WARN] Work記事は使用しません。既存RSS収集へフォールバックします" >&2
    ;;
esac

if [ "${SOURCE}" = "rss" ]; then
  echo "== collect(RSS) =="
  # collect.pyの終了コードは3値(0=新規記事あり/2=重複除外の結果0件/
  # その他=全URL取得失敗)を使う。
  set +e
  python3 scripts/collect.py \
    --out "${RAW}" --pending-out "${RSS_PENDING}" --recent-links "${RSS_LEDGER}"
  COLLECT_RC=$?
  set -e

  if [ "${COLLECT_RC}" -eq 2 ]; then
    echo "本日の新規RSS記事はありません"
    exit 0
  elif [ "${COLLECT_RC}" -ne 0 ]; then
    echo "[ERROR] RSS収集に失敗しました" >&2
    exit 1
  fi
fi

echo "== translate =="
claude -p "prompts/translate.md の指示に従え。入力JSON: ${RAW} 、出力先: ${TMP} 、日付: ${TODAY}" \
  --allowedTools "Read,Write" \
  --max-turns 15

if [ ! -s "${TMP}" ]; then
  echo "[ERROR] translate失敗: ${TMP} が生成されていません" >&2
  exit 1
fi

echo "== validate =="
if ! python3 scripts/validate.py "${TMP}" "${RAW}"; then
  echo "[ERROR] validate失敗: 構造違反が見つかりました。検査結果は ${TMP} を確認してください" >&2
  exit 1
fi
mv "${TMP}" "${OUT}"

if [ "${SOURCE}" = "work" ]; then
  echo "== Work Issue処理済み台帳を更新 =="
  python3 scripts/import_work_news.py commit-pending \
    --pending "${WORK_PENDING}" --ledger "${LEDGER}"
fi
if [ "${SOURCE}" = "rss" ]; then
  echo "== RSSリンク台帳を更新 =="
  python3 scripts/rss_dedup.py commit-pending \
    --pending "${RSS_PENDING}" --ledger "${RSS_LEDGER}"
fi
rm -f "${WORK_PENDING}" "${RSS_PENDING}"

echo "完成: ${OUT}(収集経路: ${SOURCE})"
fi

if [ "${URGENT_MODE}" -eq 1 ]; then
# 緊急ニュース処理モード: 指定したWork News Issue 1件だけを、通常便とは
# 独立に追加処理する。通常便の同日下書き有無やRSSは一切関知しない。
URGENT_SUFFIX="urgent-issue${URGENT_ISSUE}"
URGENT_RAW="data/raw/${TODAY}-${URGENT_SUFFIX}.json"
URGENT_TMP="drafts/.tmp_${TODAY}-${URGENT_SUFFIX}.md"
URGENT_OUT="drafts/${TODAY}-${URGENT_SUFFIX}.md"
URGENT_PENDING="data/state/.pending_${TODAY}-${URGENT_SUFFIX}.json"

# 同じIssueの緊急便が既に完成している場合は上書きしない(通常便・
# 他の緊急便のファイルとは名前が衝突しないため、それらには影響しない)。
if [ -s "${URGENT_OUT}" ]; then
  echo "[INFO] 緊急Issue #${URGENT_ISSUE} の下書きは既に完成済みです: ${URGENT_OUT}"
  exit 0
fi

rm -f "${URGENT_PENDING}"

echo "== 緊急Issue確認(Issue #${URGENT_ISSUE}) =="
# fetch-singleの終了コードは3値(0=新規記事あり/2=処理済みまたは重複の
# ため変換対象なし/その他=Issueが無効・gh取得失敗)を使う。緊急モードは
# RSSへフォールバックしない。
set +e
python3 scripts/import_work_news.py fetch-single \
  --repo "${WORK_REPO}" --issue "${URGENT_ISSUE}" --ledger "${LEDGER}" \
  --out "${URGENT_RAW}" --pending-out "${URGENT_PENDING}"
URGENT_FETCH_RC=$?
set -e

case "${URGENT_FETCH_RC}" in
  0)
    echo "緊急Issue #${URGENT_ISSUE} の記事を取得しました"
    ;;
  2)
    python3 scripts/import_work_news.py commit-pending \
      --pending "${URGENT_PENDING}" --ledger "${LEDGER}"
    echo "指定Issueは処理済み、または新規記事がありません"
    exit 0
    ;;
  *)
    echo "[ERROR] 緊急Issue #${URGENT_ISSUE} は使用できません" >&2
    exit 1
    ;;
esac

echo "== translate(緊急便) =="
claude -p "prompts/translate.md の指示に従え。入力JSON: ${URGENT_RAW} 、出力先: ${URGENT_TMP} 、日付: ${TODAY}" \
  --allowedTools "Read,Write" \
  --max-turns 15

if [ ! -s "${URGENT_TMP}" ]; then
  echo "[ERROR] translate失敗: ${URGENT_TMP} が生成されていません" >&2
  exit 1
fi

echo "== validate(緊急便) =="
if ! python3 scripts/validate.py "${URGENT_TMP}" "${URGENT_RAW}"; then
  echo "[ERROR] validate失敗: 構造違反が見つかりました。検査結果は ${URGENT_TMP} を確認してください" >&2
  exit 1
fi
mv "${URGENT_TMP}" "${URGENT_OUT}"

echo "== 緊急Issue処理済み台帳を更新 =="
python3 scripts/import_work_news.py commit-pending \
  --pending "${URGENT_PENDING}" --ledger "${LEDGER}"
rm -f "${URGENT_PENDING}"

echo "完成(緊急便): ${URGENT_OUT}(Issue #${URGENT_ISSUE})"
fi
