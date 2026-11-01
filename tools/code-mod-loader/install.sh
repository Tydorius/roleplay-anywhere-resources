#!/usr/bin/env sh
# Install the code-mod loader and its mods in one step. Close the game first.
#   ./install.sh                  every bundled mod except the memory-add sample
#   ./install.sh portals floors   only the mods you name
#   ./install.sh --game "$HOME/Games/Anywhere RPG"   if the game isn't in a Steam library
set -e
if ! command -v node >/dev/null 2>&1; then
  echo "error: Node.js was not found on PATH. Install it from https://nodejs.org/" >&2
  exit 1
fi
exec node "$(dirname "$0")/patch.mjs" add "$@"
