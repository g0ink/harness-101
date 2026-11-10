#!/usr/bin/env bash
# End-to-end demo: one real question, then the two offline suites.
set -euo pipefail

# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

echo "=== 1. ask one question ==============================================="
"${PYTHON}" -m harness.cli ask "In corpus/memory.md, what does compaction do?"

echo
echo "=== 2. self-check (no model needed) ==================================="
"${PYTHON}" scripts/selftest.py | tail -3

echo
echo "=== 3. adversarial cases (no model needed) ============================"
"${PYTHON}" scripts/adversarial.py | tail -3

echo
echo "done. traces are under runs/, audit lines under audit.jsonl"
