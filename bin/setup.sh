#!/usr/bin/env bash
# Create the environment, install the two dependencies, prepare .env.
set -euo pipefail

LAB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${LAB_ROOT}"

if command -v conda >/dev/null 2>&1; then
  echo "[setup] creating conda env 'harness101' (skip if it exists)"
  conda env create -f environment.yml 2>/dev/null || echo "[setup] env already exists"
  PYTHON="$(conda run -n harness101 python -c 'import sys; print(sys.executable)')"
else
  echo "[setup] conda not found, falling back to venv"
  python3 -m venv .venv
  PYTHON="${LAB_ROOT}/.venv/bin/python"
  "${PYTHON}" -m pip install --quiet -r requirements.txt
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
  echo "[setup] wrote .env -- put your LM Studio token in it"
fi

echo "[setup] interpreter: ${PYTHON}"
echo "[setup] next: ./bin/ask.sh \"What does compaction do?\""
