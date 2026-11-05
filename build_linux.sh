#!/usr/bin/env bash
# Genera dist/ReForgeStudio (binario único para Linux)
set -e
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt pyinstaller
python3 -m PyInstaller --noconfirm --clean --onefile --windowed \
  --name ReForgeStudio --add-data "assets:assets" main.py
echo "Listo: dist/ReForgeStudio"
