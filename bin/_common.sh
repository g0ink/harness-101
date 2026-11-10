#!/usr/bin/env bash
# Shared bootstrap for every script in bin/.
#
# Resolution order for the interpreter:
#   1. PYTHON from the environment or .env
#   2. .venv/bin/python inside this directory
#   3. the interpreter of a conda env named harness101
#   4. python3 on PATH
set -euo pipefail

LAB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export LAB_ROOT

if [[ -f "${LAB_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${LAB_ROOT}/.env"
  set +a
fi

find_conda_python() {
  command -v conda >/dev/null 2>&1 || return 0
  conda env list --json 2>/dev/null | python3 -c '
import json, os, sys
envs = json.load(sys.stdin).get("envs", [])
for path in envs:
    if os.path.basename(path) == "harness101":
        print(os.path.join(path, "bin", "python"))
        break
' 2>/dev/null || true
}

if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "${LAB_ROOT}/.venv/bin/python" ]]; then
    PYTHON="${LAB_ROOT}/.venv/bin/python"
  elif [[ -n "$(find_conda_python)" ]]; then
    PYTHON="$(find_conda_python)"
  else
    PYTHON="$(command -v python3)"
  fi
fi
export PYTHON

cd "${LAB_ROOT}"
