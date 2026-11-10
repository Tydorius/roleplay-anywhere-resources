#!/usr/bin/env python3
"""Check or rebuild the voices-delivery-cues pack against a game install.

The pack replaces the game's whole overseer/scene_dsl.txt. It is the game's
default file plus one line: the delivery-cue rule that starts
'SAY_TO "text" is performed aloud', placed just above the line that starts
'Never write two consecutive lines to the *player*'.

After a game update, run:

    python rebase_delivery_cues.py "D:/SteamLibrary/steamapps/common/Anywhere RPG"

It rebuilds the file from the game's current default and says whether the pack
still matches. Add --write to update the pack. The path can be the install
folder, its resources/config/default folder, or a scene_dsl.txt file.
"""
import argparse
import difflib
import sys
from pathlib import Path

PACK_FILE = (Path(__file__).resolve().parent.parent
             / "packs" / "voices-delivery-cues" / "overseer" / "scene_dsl.txt")
CUE_START = 'SAY_TO "text" is performed aloud'
ANCHOR_START = "Never write two consecutive lines to the *player*"


def find_default(path: Path) -> Path:
    for candidate in (path,
                      path / "overseer" / "scene_dsl.txt",
                      path / "config" / "default" / "overseer" / "scene_dsl.txt",
                      path / "resources" / "config" / "default" / "overseer" / "scene_dsl.txt"):
        if candidate.is_file():
            return candidate
    sys.exit(f"No overseer/scene_dsl.txt found under {path}")


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("game", type=Path, help="game install folder (or its config/default folder, or the file)")
    ap.add_argument("--write", action="store_true", help="write the rebuilt file into the pack")
    args = ap.parse_args()

    default_path = find_default(args.game)
    default = read_lines(default_path)
    pack = read_lines(PACK_FILE)

    cues = [line for line in pack if line.startswith(CUE_START)]
    if len(cues) != 1:
        sys.exit(f"Expected one line starting {CUE_START!r} in {PACK_FILE}, found {len(cues)}")
    if any(line.startswith(CUE_START) for line in default):
        sys.exit("The game's default already has a delivery-cue line. Compare by hand.")

    anchors = [i for i, line in enumerate(default) if line.startswith(ANCHOR_START)]
    if len(anchors) != 1:
        sys.exit(f"The game's default has no single line starting {ANCHOR_START!r}. "
                 "The file has changed shape: insert the cue line by hand.")
    rebuilt = default[:anchors[0]] + cues + default[anchors[0]:]

    if rebuilt == pack:
        print(f"Up to date: the pack is {default_path} plus the cue line.")
        return 0

    sys.stdout.writelines(difflib.unified_diff(
        [l + "\n" for l in pack], [l + "\n" for l in rebuilt],
        "pack (current)", "pack (rebuilt from game default)"))
    if args.write:
        PACK_FILE.write_text("\n".join(rebuilt), encoding="utf-8", newline="\n")
        print(f"\nWrote {PACK_FILE}")
        return 0
    print("\nThe pack is out of date. Re-run with --write to update it.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
