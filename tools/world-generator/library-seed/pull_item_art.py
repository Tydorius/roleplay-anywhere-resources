"""Pull kept item-art sprites from the gallery workspace into
library/item-sprites/.

The Scenario Editor's image tab queues each item look with its template id;
a person keeps the good ones. This copies the kept images for one set's
scenario (shared, medieval, industrial, modern or scifi) out of the gallery
workspace's media folder, names them ``<item id>.<look key>.webp`` and rewrites
that set's entries in ``library/item-sprites/index.json`` (entries from the
other sets are kept).

  python library-seed/pull_item_art.py <set> --kept [--work DIR] [--art DIR]

The manifest the scenario writer left beside the zip maps every template id
back to its item and look.
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(GEN))
sys.path.insert(0, GEN)

from worldgen.item_library import BANDS  # noqa: E402
from worldgen.library import LIB_DIR     # noqa: E402

ITEM_SPRITES_DIR = os.path.join(LIB_DIR, "item-sprites")


def in_set(bands, name):
    """The set an entry's bands put it in: shared when it covers two or more."""
    return len(bands) >= 2 if name == "shared" else bands == [name]


def pull_kept(a):
    set_name = a.set
    ws = os.path.join(a.work, f"Library-Items-{set_name.title()}")
    with open(os.path.join(ws, "scenario.json"), encoding="utf-8") as f:
        tmpls = json.load(f)["itemTemplates"]
    with open(os.path.join(a.art, set_name, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)["looks"]
    os.makedirs(ITEM_SPRITES_DIR, exist_ok=True)
    idx_path = os.path.join(ITEM_SPRITES_DIR, "index.json")
    index = {}
    if os.path.exists(idx_path):
        with open(idx_path, encoding="utf-8") as f:
            index = json.load(f)
    # this set's entries are rewritten; the other sets' stay as they are
    index = {k: v for k, v in index.items() if not in_set(v.get("bands") or [], set_name)}
    copied, missing = 0, []
    for t in tmpls:
        m = manifest.get(t["id"])
        src = os.path.join(ws, "media", t["id"], f"{t['id']}-item.webp")
        if m is None or not os.path.exists(src):
            missing.append(t["name"])
            continue
        key = f"{m['item']}.{m['look']}"
        shutil.copyfile(src, os.path.join(ITEM_SPRITES_DIR, key + ".webp"))
        index[key] = {"bands": m["bands"], "physical": m["physical"], "reviewed": True}
        copied += 1
    with open(idx_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(dict(sorted(index.items())), f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"{set_name}: {copied} kept item sprites copied into {ITEM_SPRITES_DIR}; "
          f"{len(missing)} without one"
          + (": " + ", ".join(missing) if missing else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("set", choices=("shared",) + BANDS)
    ap.add_argument("--kept", action="store_true", required=True,
                    help="copy the images kept in the gallery workspace")
    ap.add_argument("--art", default=r"E:\Misc Projects\Roleplay Anywhere Scenarios\_library-art-items")
    ap.add_argument("--work", default=os.path.join(REPO, "mods", "better-images",
                                                  "gallery-scenarios"))
    a = ap.parse_args()
    pull_kept(a)


if __name__ == "__main__":
    main()
