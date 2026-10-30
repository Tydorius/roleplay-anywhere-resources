#!/bin/sh
# Linux: run ./start-scenario-editor.sh (or mark it executable and double-click it). Ctrl+C to stop.
cd "$(dirname "$0")" || exit 1

for p in python3 python; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null; then
    echo "Starting the Scenario Editor. It opens in your browser; close this window to stop it."
    echo
    "$p" scenario_editor.py "$@" && exit 0
    echo
    printf "Press Enter to close."; read -r _
    exit 1
  fi
done

echo "Python 3 is needed to run the Scenario Editor."
echo "Install it from https://www.python.org/downloads/ and double-click this file again."
echo
printf "Press Enter to close."; read -r _
exit 1
