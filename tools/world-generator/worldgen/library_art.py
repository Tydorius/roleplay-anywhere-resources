"""Shipped sprites for room-library objects (ROOM_LIBRARY_DESIGN.md, "Art").

Sprites live in ``library/sprites/<band>/<object id>.webp`` with an
``index.json`` per band: for each object, the materials and physical text the
art was drawn from, so a template that uses the sprite describes what is drawn,
and whether a person has reviewed it.

``attach_sprites`` puts a built scenario's sprites in place: every object
template whose plan template carries a ``sprite`` gets
``media/<template id>/<template id>-sprite.webp``, and the zip is rebuilt. The
game then shows the shipped art instead of drawing its own.
"""
import json
import os
import shutil
import zipfile

from .library import LIB_DIR

SPRITES_DIR = os.path.join(LIB_DIR, "sprites")


def load_index(band, root=SPRITES_DIR):
    """{object id: entry} for a band ({} when it has no sprites)."""
    path = os.path.join(root, band, "index.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f).get("objects", {})


def sprite_path(band, object_id, root=SPRITES_DIR):
    return os.path.join(root, band, object_id + ".webp")


def attach_sprites(scenario_dir, plan_data, root=os.path.dirname(LIB_DIR)):
    """Copy shipped sprites into a built scenario and rebuild its zip.
    Returns how many were attached."""
    want = {t["name"]: t["sprite"] for t in plan_data.get("templates", [])
            if t.get("sprite")}
    if not want:
        return 0
    scn_path = os.path.join(scenario_dir, "scenario.json")
    with open(scn_path, "r", encoding="utf-8") as f:
        scn = json.load(f)
    n = 0
    for t in scn.get("objectTemplates", []):
        rel = want.get(t.get("name"))
        if not rel:
            continue
        src = os.path.join(root, rel)
        if not os.path.exists(src):
            continue
        d = os.path.join(scenario_dir, "media", t["id"])
        os.makedirs(d, exist_ok=True)
        shutil.copyfile(src, os.path.join(d, f"{t['id']}-sprite.webp"))
        n += 1
    if n:
        zip_path = scenario_dir.rstrip("\\/") + ".zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for base, _dirs, files in os.walk(scenario_dir):
                for fn in files:
                    full = os.path.join(base, fn)
                    z.write(full, os.path.relpath(full, scenario_dir).replace(os.sep, "/"))
    return n
