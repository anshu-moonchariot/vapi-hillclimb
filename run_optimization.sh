#!/usr/bin/env bash
# Full baseline + optimization + final-eval. Requires .env with voice vars for --mode voice.
set -euo pipefail

cd "$(dirname "$0")"

MODE="${MODE:-voice}"
echo "MODE=${MODE}  (set MODE=chat for chat-only)"

echo "=== Step 1: Baseline ==="
conda run -n vapi-takehome python -m vapi_takehome.cli baseline --n 5 --mode "${MODE}"

echo ""
echo "=== Step 2: Optimize ==="
conda run -n vapi-takehome python -m vapi_takehome.cli optimize --mode "${MODE}"

RUN_ID="$(ls -td runs/optimize_* 2>/dev/null | grep -v '_final$' | head -1 | xargs basename 2>/dev/null || true)"
if [[ -z "${RUN_ID}" ]]; then
  echo "Could not find runs/optimize_* directory."
  exit 1
fi

echo ""
echo "=== Step 3: Final eval (run_id=${RUN_ID}) ==="
conda run -n vapi-takehome python -m vapi_takehome.cli final-eval --run-id "${RUN_ID}" --mode "${MODE}"

echo ""
echo "=== Step 4: Report ==="
conda run -n vapi-takehome python -m vapi_takehome.cli report --run-id "${RUN_ID}"

echo ""
echo "Done. Check runs/${RUN_ID} and results/."
