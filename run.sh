#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

TODAY=$(TZ=Asia/Tokyo date +%F)
RAW="data/raw/${TODAY}.json"
TMP="drafts/.tmp_${TODAY}.md"
OUT="drafts/${TODAY}.md"
WORK_PENDING="data/state/.pending_${TODAY}.json"
LEDGER="data/state/processed_work_issues.json"
WORK_REPO="popchami/news-game-translator"
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
