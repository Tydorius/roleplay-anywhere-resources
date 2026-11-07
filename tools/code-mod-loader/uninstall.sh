#!/usr/bin/env sh
# Restore the game's original files. Your code-mods folder is left as it is.
# Extra arguments pass through, e.g.  ./uninstall.sh --game "$HOME/Games/Anywhere RPG"
set -e
if ! command -v node >/dev/null 2>&1; then
  echo "error: Node.js was not found on PATH. Install it from https://nodejs.org/" >&2
  exit 1
fi
exec node "$(dirname "$0")/patch.mjs" uninstall "$@"
