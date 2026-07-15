#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.11 or newer is required." >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First run: creating the ReqPilot Python environment..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi

echo "Checking local speech models..."
.venv/bin/python -m scripts.fetch_models
echo "Starting ReqPilot at http://127.0.0.1:8765"
exec .venv/bin/python -m src.server
