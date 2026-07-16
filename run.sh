#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

TODAY=$(TZ=Asia/Tokyo date +%F)
RAW="data/raw/${TODAY}.json"
TMP="drafts/.tmp_${TODAY}.md"
OUT="drafts/${TODAY}.md"

echo "== collect =="
python3 scripts/collect.py

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
echo "完成: ${OUT}"
