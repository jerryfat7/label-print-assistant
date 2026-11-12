#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="${LABEL_STATE_DIR:-$HOME/.local/state/label-print-assistant}"
PYTHON="${LABEL_PYTHON:-$ROOT/.venv/bin/python}"
CONFIG="${LABEL_CONFIG:-$STATE/config.json}"
BOOTSTRAP="${LABEL_BOOTSTRAP_PYTHON:-python3}"
mkdir -p "$STATE"
if [[ ! -x "$PYTHON" ]]; then
  "$BOOTSTRAP" -m venv "$(dirname -- "$(dirname -- "$PYTHON")")"
fi
cd -- "$ROOT"
options=()
if [[ "$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')" == '3.11' ]]; then
  options=(-c "$ROOT/linux/constraints-py311.txt")
fi
"$PYTHON" -m pip install "${options[@]}" -r requirements-linux.txt
"$PYTHON" -m pip check
"$PYTHON" linux/install_fonts.py
if [[ ! -f "$CONFIG" ]]; then
  mkdir -p "$(dirname -- "$CONFIG")"
  cp -- linux/config.example.json "$CONFIG"
fi
echo "Installed. Review configuration: $CONFIG"
echo 'Set helper paths if this service should also supervise dtpweb.'
echo 'Start with: bash linux/service.sh start (use the same LABEL_* environment).'
