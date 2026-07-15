#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.11 or newer is required." >&2
  exit 1
fi

python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || {
  echo "ReqPilot requires Python 3.11 or newer." >&2
  exit 1
}

if [ ! -x .venv/bin/python ]; then
  echo "First run: creating the ReqPilot Python environment..."
  python3 -m venv .venv
  if [ -d wheelhouse ]; then
    echo "Installing from the offline wheelhouse..."
    .venv/bin/python -m pip install --no-index --find-links wheelhouse -r requirements.txt
  else
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt
  fi
fi

echo "Checking local speech models..."
.venv/bin/python -m scripts.fetch_models
echo "Starting ReqPilot at http://127.0.0.1:8765"
exec .venv/bin/python -m src.server
