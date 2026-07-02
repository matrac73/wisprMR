#!/bin/bash
cd "$(dirname "$0")"
clear

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 est introuvable."
  echo "Installe Python 3.11+ depuis https://www.python.org/downloads/macos/"
  echo "puis relance ce fichier."
  echo
  read -r -p "Appuie sur Entree pour fermer..."
  exit 1
fi

python3 INSTALL.py
