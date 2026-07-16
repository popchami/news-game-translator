#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

TODAY=$(TZ=Asia/Tokyo date +%F)
RAW="data/raw/${TODAY}.json"
TMP="drafts/.tmp_${TODAY}.md"
OUT="drafts/${TODAY}.md"
PENDING="data/state/.pending_${TODAY}.json"
LEDGER="data/state/processed_work_issues.json"
WORK_REPO="popchami/news-game-translator"

rm -f "${PENDING}"

SOURCE=rss
echo "== Work Issue確認 =="
if python3 scripts/import_work_news.py fetch \
  --repo "${WORK_REPO}" --ledger "${LEDGER}" --out "${RAW}" --pending-out "${PENDING}"; then
  SOURCE=work
  echo "Work記事を使用します"
else
  echo "[WARN] Work記事は使用しません。既存RSS収集へフォールバックします" >&2
fi

if [ "${SOURCE}" = "rss" ]; then
  echo "== collect(RSS) =="
  python3 scripts/collect.py
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
  python3 scripts/import_work_news.py commit-pending --pending "${PENDING}" --ledger "${LEDGER}"
fi
rm -f "${PENDING}"

echo "完成: ${OUT}(収集経路: ${SOURCE})"
