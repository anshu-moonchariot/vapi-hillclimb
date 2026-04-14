#!/bin/bash
# Full baseline + optimization run. Execute after midnight UTC when Vapi daily limit resets.
set -e

cd "$(dirname "$0")"

echo "=== Step 1: Baseline (5 voice calls) ==="
conda run -n vapi-takehome python -m vapi_takehome.cli baseline --n 5

echo ""
echo "=== Step 2: Hill-climbing optimizer ==="
conda run -n vapi-takehome python -m vapi_takehome.cli optimize

echo ""
echo "=== Step 3: Final eval ==="
conda run -n vapi-takehome python -m vapi_takehome.cli final-eval

echo ""
echo "=== Step 4: Report ==="
conda run -n vapi-takehome python -m vapi_takehome.cli report

echo ""
echo "Done. Check results/ for artifacts."
