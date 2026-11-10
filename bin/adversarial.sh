#!/usr/bin/env bash
# Adversarial cases: 11 attack surfaces against the guard layer.
set -euo pipefail

# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
exec "${PYTHON}" scripts/adversarial.py
