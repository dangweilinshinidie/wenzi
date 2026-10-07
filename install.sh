#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT_DIR"

PYTHON=${PYTHON:-python3}
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "ERROR: python3 was not found. Install Python 3.10 or 3.11 first." >&2
    exit 1
fi

"$PYTHON" - <<'PY'
import sys
if sys.version_info[:2] not in {(3, 10), (3, 11)}:
    raise SystemExit("ERROR: Wenzi recommends Python 3.10 or 3.11.")
PY

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "WARNING: ffmpeg was not found in PATH. Install it before using ASR." >&2
fi

if [ ! -x .venv/bin/python ]; then
    echo "[1/3] Creating virtual environment..."
    "$PYTHON" -m venv .venv
else
    echo "[1/3] Using existing .venv"
fi

echo "[2/3] Installing Python dependencies..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

if [ ! -f .env ]; then
    echo "[3/3] Creating .env from .env.example..."
    cp .env.example .env
else
    echo "[3/3] Keeping existing .env"
fi

echo
echo "Installation finished."
echo "Start Wenzi with: .venv/bin/python run.py"
echo "Then open: http://127.0.0.1:8000/ui"
