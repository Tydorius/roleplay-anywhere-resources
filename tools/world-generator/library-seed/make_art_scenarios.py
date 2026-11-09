"""One scenario per band holding every library object for that band, laid out
in rows on open ground, so their sprites can be generated and reviewed in the
Scenario Editor's image tab. A manifest beside each zip maps every template
back to its library object and the materials its text was filled with, so the
reviewed images can be pulled into library/sprites/ afterwards.

  python library-seed/make_art_scenarios.py [out folder]

Each object appears once per band, at its modest tier (or the nearest tier it
allows) in kept condition. Templates are named "<what it is> [<object id>]".
"""
import json
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.dirname(HERE)
sys.path.insert(0, GEN)

from worldgen import library as L  # noqa: E402

ROW_WIDTH = 48       # cells of objects per row before wrapping
GAP = 2              # clear cells between objects


def tier_for(lib, obj):
    tiers = lib.tiers
    if "modest" in obj["wealth"]:
        return "modest"
    return min(obj["wealth"], key=lambda t: abs(tiers.index(t) - tiers.index("modest")))


def build_band(lib, band, out_root):
    objs = [o for o in sorted(lib.objects.values(), key=lambda o: o["id"])
            if o["bands"] == ["*"] or band in o["bands"]]
    # tallest first so each row stays tidy
    objs.sort(key=lambda o: (-o["size"][1], o["category"], o["id"]))
    templates, manifest = [], []
    x, y, row_h = 2, 2, 0
    for o in objs:
        w, h = o["size"]
        if x + w > ROW_WIDTH + 2:
            x, y, row_h = 2, y + row_h + GAP, 0
        tier = tier_for(lib, o)
        text = L.fill_text(lib, o, band, tier, "kept", random.Random(f"art|{band}|{o['id']}"))
        noun = (o["names"].get(band) or o["names"]["*"])
        main = next(iter(text["materials"].values()), "")
        what = f"{main} {noun}" if main and main.lower() not in noun.lower() else noun
        name = f"{what[:1].upper() + what[1:]} [{o['id']}]"
        t = {"name": name, "size": list(o["size"]), "walkability": o["walkability"],
             "description": text["description"], "physicalDescription": text["physical"],
             "tags": list(o.get("tags") or [o["category"]]), "heightM": 1, "maxHp": 50,
             "placements": [[x, y]]}
        if o.get("forSleep"):
            t["forSleep"] = True
        if o.get("light"):
            t["light"] = o["light"]
        templates.append(t)
        manifest.append({"template": name, "object": o["id"], "band": band, "tier": tier,
                         "condition": "kept", "materials": text["materials"],
                         "physical": text["physical"]})
        x += w + GAP
        row_h = max(row_h, h)
    width, height = ROW_WIDTH + 6, y + row_h + 4
    title = f"Library Art {band.title()}"
    spec = {
        "name": title, "folderName": title.replace(" ", "-"), "seed": "1",
        "worldBackground": f"A showroom of every {band} room-library object, for drawing and "
                           "reviewing their sprites. Not a place to play.",
        "narrativeRules": ["This is an art-review scenario, not a game world."],
        "narrativeFlavor": "adaptive", "difficulty": "casual", "xpMultiplier": 1,
        "gridSize": [width, height],
        "defaultTile": {"name": "Showroom floor", "ground": "dirt", "groundTexture": "dirt",
                        "ambience": {"day": "quiet_indoor"}},
        "weatherKinds": ["clear"],
        "currency": {"name": "Coin", "description": "A plain coin.", "format": "{n} coins"},
        "startingCurrency": 0,
        "attributes": {"strength": 5, "dexterity": 5, "intellect": 5, "perception": 5,
                       "charisma": 5},
        "skills": {}, "variables": [],
        "perkTrees": [], "calendar": [], "quests": [],
        "regions": [{"name": "Showroom", "description": "Every object, in rows.",
                     "ground": "dirt", "groundTexture": "dirt", "position": [0, 0],
                     "size": [width, height], "ambience": {"day": "quiet_indoor"}}],
        "objectTemplates": templates, "itemTemplates": [], "npcs": [],
        "player": {"name": "Art Reviewer", "gender": "female", "pos": [1, 1], "level": 1,
                   "animationId": "casual-woman", "description": "Here to look at furniture.",
                   "physicalDescription": "A person in plain clothes holding a notebook.",
                   "voiceProfile": {"gender": "Female", "age": ["Adult"], "pitch": ["Average"],
                                    "tags": []},
                   "schedule": [{"start": "06:00", "end": "22:00", "location": "Showroom",
                                 "role": "leisure"},
                                {"start": "22:00", "end": "06:00", "location": "Showroom",
                                 "role": "sleep"}]},
    }
    out = os.path.join(out_root, band)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=1, ensure_ascii=False)
    # the vendored builder loads a spec.py module holding SPEC
    with open(os.path.join(out, "spec.py"), "w", encoding="utf-8") as f:
        nl = "\n"
        f.write('"""Library art-review spec."""' + nl + "import json" + nl + nl
                + 'SPEC = json.loads(r"""' + nl
                + json.dumps(spec, indent=1, ensure_ascii=False) + nl + '""")' + nl)
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"band": band, "library_version": lib.vocab.get("version", 1),
                   "objects": manifest}, f, indent=1, ensure_ascii=False)
    r = subprocess.run([sys.executable, os.path.join(GEN, "worldgen", "vendor", "build_scenario.py"),
                        os.path.join(out, "spec.py"), "--out", out],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = [l for l in (r.stdout + r.stderr).splitlines() if l.strip()][-3:]
    return len(templates), r.returncode, tail


def main():
    out_root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(GEN, "out", "library-art")
    lib = L.load()
    for band in lib.bands:
        n, code, tail = build_band(lib, band, out_root)
        print(f"{band}: {n} objects, build exit {code}")
        for l in tail:
            print("   ", l)


if __name__ == "__main__":
    main()
