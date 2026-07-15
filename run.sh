#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

echo "== collect =="
python3 scripts/collect.py

# TODO(次フェーズ): translate / validate
