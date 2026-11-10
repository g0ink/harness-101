#!/usr/bin/env bash
# Run the eval suite.
#
#   ./bin/eval.sh --verify-only     check the task set can be scored (no model)
#   ./bin/eval.sh --limit 3         smoke test
#   ./bin/eval.sh --tag baseline    full 30-task run
set -euo pipefail

# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
exec "${PYTHON}" evals/runner.py "$@"
