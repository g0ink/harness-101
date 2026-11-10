#!/usr/bin/env bash
# Ask the harness one question.
#
#   ./bin/ask.sh "What does compaction do in corpus/memory.md?"
#   ./bin/ask.sh --quiet --budget 4000 "how large may a hot summary be?"
set -euo pipefail

# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
exec "${PYTHON}" -m harness.cli ask "$@"
