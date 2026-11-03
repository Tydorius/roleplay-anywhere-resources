#!/bin/sh
# Linux: run ./start-world-generator.sh (or mark it executable and double-click it).
# The first time, it asks for your model provider and key and saves them in providers.json.
cd "$(dirname "$0")" || exit 1

for p in python3 python; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null; then
    "$p" launcher.py "$@" && exit 0
    echo
    printf "Press Enter to close."; read -r _
    exit 1
  fi
done

echo "Python 3.8 or newer is needed to run the world generator."
echo "Install it from https://www.python.org/downloads/ and double-click this file again."
echo
printf "Press Enter to close."; read -r _
exit 1
