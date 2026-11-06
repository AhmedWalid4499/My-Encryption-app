#!/bin/bash
# Build VeilMark for the Mac on your own Mac.
# Requirements: Python 3.11+ (python.org or Homebrew). Run:  bash build_macos.sh
# Result: dist/VeilMark.app and dist/VeilMark-macOS-<AppleSilicon|Intel>.dmg
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
if [ ! -d .venv ]; then "$PY" -m venv .venv; fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen python -m pytest -q
pyinstaller packaging/veilmark-macos.spec --noconfirm --clean
bash packaging/make_dmg.sh

echo
echo "App:         dist/VeilMark.app"
ls dist/*.dmg | sed 's/^/Disk image:  /'
