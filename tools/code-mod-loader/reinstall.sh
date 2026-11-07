#!/usr/bin/env sh
# Re-apply the code-mod loader after a game update, Steam "Verify integrity",
# or a change to the mods in the code-mods folder.
# Extra arguments pass through, e.g.  ./reinstall.sh --game "$HOME/.steam/steam/steamapps/common/Anywhere RPG"
set -e
if ! command -v node >/dev/null 2>&1; then
  echo "error: Node.js was not found on PATH. Install it from https://nodejs.org/" >&2
  exit 1
fi
exec node "$(dirname "$0")/patch.mjs" install "$@"
