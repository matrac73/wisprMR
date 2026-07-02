#!/bin/bash
cd "$(dirname "$0")"
clear

if [[ -x ".venv/bin/python" ]]; then
  .venv/bin/python UNINSTALL.py
elif command -v python3 >/dev/null 2>&1; then
  python3 UNINSTALL.py
else
  echo "Python est introuvable, impossible de lancer UNINSTALL.py."
  echo
  read -r -p "Appuie sur Entree pour fermer..."
  exit 1
fi
