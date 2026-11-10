#!/usr/bin/env bash
# Preflight check: python, dependencies, token, model server, model name.
set -euo pipefail

# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
exec "${PYTHON}" scripts/doctor.py
