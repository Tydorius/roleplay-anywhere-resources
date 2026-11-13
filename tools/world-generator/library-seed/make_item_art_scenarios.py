"""One scenario per item-library set holding every look for that set, so the
item sprites can be generated and reviewed in the Scenario Editor's image tab.
A look that covers two or more bands looks the same in each, so it is drawn
once in "shared"; a look for a single band is drawn in that band's scenario. A
manifest beside each zip maps every template id back to its item, look, bands
and physical text, so the kept images can be pulled into
library/item-sprites/ afterwards.

  python library-seed/make_item_art_scenarios.py [out folder]

Template names are "<Name for the look's first band> [<item id>#<look key>]".
Template ids are hashes of that pair, not the builder's fresh ones, so
re-running keeps the ids and the gallery keeps its reviewed images.
"""
import hashlib
import json
import os
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.dirname(HERE)
sys.path.insert(0, GEN)

from worldgen import item_library as IL  # noqa: E402

DEFAULT_OUT = r"E:\Misc Projects\Roleplay Anywhere Scenarios\_library-art-items"
SETS = ("shared",) + IL.BANDS


def template_id(iid, key):
    """A game-shaped id that only depends on the item and the look."""
    h = hashlib.sha256(f"{iid}#{key}".encode("utf-8")).hexdigest()[:10]
    return f"itpl_{h}"


def set_looks(items, name):
    """The looks for one set, as (item, look, bands) sorted by item and key."""
    out = []
    for iid, it in sorted(items.items()):
        for look in it.get("looks") or []:
            bands = IL.look_bands(it, look)
            if name == "shared":
                fits = len(bands) >= 2
            else:
                fits = bands == [name]
            if fits:
                out.append((it, look, bands))
    return out


def build_set(items, name, out_root):
    """Write one set's scenario (spec, zip, unzipped folder, manifest)."""
    title = name.title()
    folder_name = f"Library-Items-{title}"
    templates, manifest, by_name = [], {}, {}
    for it, look, bands in set_looks(items, name):
        iid, key = it["id"], look["key"]
        first = next(b for b in IL.BANDS if b in bands)
        noun = IL.name_for(it, first)
        tid = template_id(iid, key)
        templates.append({
            "name": f"{noun[:1].upper() + noun[1:]} [{iid}#{key}]",
            "type": it.get("type", "misc"), "quality": it.get("quality", "common"),
            "value": it.get("price", 1), "description": IL.description_for(it, first),
            "physicalDescription": look.get("physical", "")})
        manifest[tid] = {"item": iid, "look": key, "bands": bands,
                         "physical": look.get("physical", "")}
        by_name[templates[-1]["name"]] = tid
    spec = {
        "name": f"Library Items — {title}", "folderName": folder_name, "seed": "1",
        "worldBackground": f"Every {name} look of the item library, for drawing and "
                           "reviewing the item art. Not a place to play.",
        "narrativeRules": ["This is an art-review scenario, not a game world."],
        "narrativeFlavor": "adaptive", "difficulty": "casual", "xpMultiplier": 1,
        "gridSize": [16, 16],
        "defaultTile": {"name": "Showroom floor", "ground": "dirt", "groundTexture": "dirt",
                        "ambience": {"day": "quiet_indoor"}},
        "weatherKinds": ["clear"],
        "currency": {"name": "Coin", "description": "A plain coin.", "format": "{n} coins"},
        "startingCurrency": 0,
        "attributes": {"strength": 5, "dexterity": 5, "intellect": 5, "perception": 5,
                       "charisma": 5},
        "skills": {}, "variables": [],
        "perkTrees": [], "calendar": [], "quests": [],
        "regions": [{"name": "Showroom", "description": "Item art, no layout.",
                     "ground": "dirt", "groundTexture": "dirt", "position": [0, 0],
                     "size": [16, 16], "ambience": {"day": "quiet_indoor"}}],
        "objectTemplates": [], "itemTemplates": templates, "npcs": [],
        "player": {"name": "Art Reviewer", "gender": "female", "pos": [1, 1], "level": 1,
                   "animationId": "casual-woman", "description": "Here to look at items.",
                   "physicalDescription": "A person in plain clothes holding a notebook.",
                   "voiceProfile": {"gender": "Female", "age": ["Adult"], "pitch": ["Average"],
                                    "tags": []},
                   # no sleep entry: nothing here can be slept on, there are
                   # no objects at all, only the item art
                   "schedule": [{"start": "00:00", "end": "00:00", "location": "Showroom",
                                 "role": "leisure"}]},
    }
    out = os.path.join(out_root, name)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=1, ensure_ascii=False)
    # the vendored builder loads a spec.py module holding SPEC
    with open(os.path.join(out, "spec.py"), "w", encoding="utf-8") as f:
        nl = "\n"
        f.write('"""Library item-art spec."""' + nl + "import json" + nl + nl
                + 'SPEC = json.loads(r"""' + nl
                + json.dumps(spec, indent=1, ensure_ascii=False) + nl + '""")' + nl)
    r = subprocess.run([sys.executable, os.path.join(GEN, "worldgen", "vendor", "build_scenario.py"),
                        os.path.join(out, "spec.py"), "--out", out],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode == 0:
        _restamp_ids(os.path.join(out, folder_name + ".scenario"), by_name)
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"set": name, "looks": manifest}, f, indent=1, ensure_ascii=False)
    tail = [l for l in (r.stdout + r.stderr).splitlines() if l.strip()][-3:]
    return len(templates), r.returncode, tail


def _restamp_ids(root, by_name):
    """Swap the builder's fresh item template ids for the stable hashed ones
    (nothing references them: no item is placed) and rebuild the zip."""
    scn_path = os.path.join(root, "scenario.json")
    with open(scn_path, "r", encoding="utf-8") as f:
        scn = json.load(f)
    for t in scn.get("itemTemplates", []):
        if t.get("name") in by_name:
            t["id"] = by_name[t["name"]]
    with open(scn_path, "w", encoding="utf-8") as f:
        json.dump(scn, f, ensure_ascii=False, indent=1)
    with zipfile.ZipFile(root + ".zip", "w", zipfile.ZIP_DEFLATED) as z:
        for base, _, files in os.walk(root):
            for fn in files:
                full = os.path.join(base, fn)
                z.write(full, os.path.relpath(full, root).replace(os.sep, "/"))


def main():
    out_root = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    items = IL.load()
    errors = IL.check(items)
    if errors:
        for e in errors:
            print("ERROR " + e)
        sys.exit(f"{len(errors)} item library error(s); fix them first "
                 "(python -m worldgen library items)")
    print(f"{len(items)} items from {IL.ITEMS_DIR}")
    for name in SETS:
        n, code, tail = build_set(items, name, out_root)
        print(f"{name}: {n} looks, build exit {code}")
        for l in tail:
            print("   ", l)


if __name__ == "__main__":
    main()
