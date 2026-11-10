#!/usr/bin/env bash
# Offline self-check: 43 error paths. No model, no network.
set -euo pipefail

# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
exec "${PYTHON}" scripts/selftest.py
