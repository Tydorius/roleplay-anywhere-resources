"""Check a scenario.json / .scenario folder / .scenario.zip against the engine's known enums and
reference rules (see SCENARIO_AUTHORING_GUIDE.md). Works on game exports and on hand-built files.

Usage: python worldgen/vendor/validate_scenario.py <scenario.json|folder|zip> [...]
Exit code 1 if any ERROR.
"""
import io
import json
import os
import re
import sys
import zipfile

# The value lists and the Anywhere RPG 1.0 rules come from scenario_checks.py, vendored beside this file as an exact
# copy of tools/scenario-editor/scenario_checks.py (a test fails when the two drift apart).
try:
    from . import scenario_checks as sc
except ImportError:  # run as a script: python worldgen/vendor/validate_scenario.py
    import scenario_checks as sc

ANIMATIONS, ANIMATION_ALIASES, GROUND, TEXTURES, WALLS = sc.ANIMATIONS, sc.ANIMATION_ALIASES, sc.GROUND, sc.TEXTURES, sc.WALLS
AMBIENCE, ITEM_TYPES, SLOTS, QUALITY, WEATHER = sc.AMBIENCE, sc.ITEM_TYPES, sc.SLOTS, sc.QUALITY, sc.WEATHER
ATTRS, AGES, PITCH, STANCES = sc.ATTRS, sc.AGES, sc.PITCH, sc.STANCES
HHMM = re.compile(r"^\d\d:\d\d$")


def load(path):
    """Returns (scenario dict, set of media relative paths)."""
    if path.endswith(".zip"):
        z = zipfile.ZipFile(path)
        scn = json.load(io.TextIOWrapper(z.open("scenario.json"), encoding="utf-8"))
        return scn, {n for n in z.namelist() if n.startswith("media/")}
    root = path if os.path.isdir(path) else os.path.dirname(path)
    jp = os.path.join(root, "scenario.json") if os.path.isdir(path) else path
    scn = json.load(open(jp, encoding="utf-8"))
    media = set()
    for base, _, files in os.walk(os.path.join(root, "media")):
        for f in files:
            media.add(os.path.relpath(os.path.join(base, f), root).replace(os.sep, "/"))
    return scn, media


def validate(scn, media):
    E, W = [], []
    for k in ("name", "gridSize", "regions", "entities", "playerId"):
        if k not in scn:
            E.append(f"missing required key {k}")
    gw, gh = scn.get("gridSize", [0, 0])
    if not all(isinstance(v, (int, float)) for v in (gw, gh)):
        E.append("gridSize must be numbers")
    if scn.get("stancesAuthored") is not True:
        W.append("stancesAuthored is not true: every hostile npc will be forced to stance 'hostile' on import")
    for k in scn.get("weatherKinds", []):
        if k not in WEATHER:
            W.append(f"unknown weather kind {k!r} (dropped by the engine)")
    if set(scn.get("attributes", {})) - ATTRS:
        E.append(f"unknown attributes {set(scn['attributes']) - ATTRS}")
    spent = sum(v - 3 for v in scn.get("attributes", {}).values())
    if spent != 10:
        W.append(f"attribute points spent = {spent} (examples spend exactly 10 over a base of 3)")

    names = set()
    for r in [scn.get("defaultTile", {})] + scn.get("regions", []):
        if r.get("ground") and r["ground"] not in GROUND:
            E.append(f"region {r.get('name')!r}: ground {r['ground']!r}")
        if r.get("groundTexture") and r["groundTexture"] not in TEXTURES:
            E.append(f"region {r.get('name')!r}: groundTexture {r['groundTexture']!r}")
        amb = r.get("ambience")
        for v in ([amb] if isinstance(amb, str) else (amb or {}).values()):
            if v not in AMBIENCE:
                W.append(f"region {r.get('name')!r}: ambience {v!r} has no shipped sound folder")
    floors = {r["id"]: sc.rect(r["position"], r["size"]) for r in scn.get("regions", []) if sc.is_floor(r)}
    for r in scn.get("regions", []):
        names.add(r["name"])
        if "openings" not in r:
            E.append(f"region {r['name']!r} lacks openings:[] (hydration needs it)")
        if r.get("wall") and r["wall"] not in WALLS:
            W.append(f"region {r['name']!r}: wall {r['wall']!r} becomes 'wood'")
        x, y = r["position"]
        w, h = r["size"]
        on_map = not (x < 0 or y < 0 or x + w > gw or y + h > gh)
        if r["id"] in floors:  # a 1.0 floor: its own plane, beside the map
            if on_map or not sc.disjoint(floors[r["id"]], (0, 0, gw - 1, gh - 1)):
                E.append(f"floor {r['name']!r} lies on the map; floors go beside it")
        elif not on_map and sc.plane_of(floors, sc.rect(r["position"], r["size"])) is None:
            E.append(f"region {r['name']!r} out of bounds")
        if r.get("wall"):
            if not r.get("openings"):
                W.append(f"walled region {r['name']!r} has no openings: it is sealed")
            for o in r.get("openings", []):  # [x, y] or 1.0's [x, y, side]
                if not sc.is_opening(o) or not sc.opening_sides(r, o):
                    E.append(f"region {r['name']!r}: opening {o} not on its perimeter")

    items = {t["id"]: t for t in scn.get("itemTemplates", [])}
    objs = {t["id"]: t for t in scn.get("objectTemplates", [])}
    htpl = {t["id"]: t for t in sc.npc_templates(scn)[0]}
    for t in items.values():
        if t.get("type") not in ITEM_TYPES:
            E.append(f"item {t['name']!r}: type {t.get('type')!r}")
        if t.get("quality") not in QUALITY:
            E.append(f"item {t['name']!r}: quality {t.get('quality')!r}")
        ab = t.get("attributeBonus")
        if ab and ab.get("key") not in ATTRS:
            E.append(f"item {t['name']!r}: attributeBonus key {ab.get('key')!r}")
    for t in list(objs.values()) + list(htpl.values()):
        for lid in t.get("lootPoolIds", []):
            if lid not in items:
                E.append(f"template {t['name']!r}: loot id {lid} not an item template")
        if "money" in t and not 0 <= t["money"] <= 5:
            E.append(f"template {t['name']!r}: money is a tier 0-5, got {t['money']}")
    region_ids = {r["id"] for r in scn.get("regions", [])}
    for t in htpl.values():
        homes = sc.template_homes(t)
        if not homes and "homes" not in t:
            E.append(f"hostile template {t['name']!r}: regionId does not resolve")
        for rid, _count in homes:
            if rid not in region_ids:
                E.append(f"hostile template {t['name']!r}: home region {rid!r} does not resolve")
        if t.get("animationId") not in ANIMATIONS and t.get("animationId") not in ANIMATION_ALIASES:
            E.append(f"hostile template {t['name']!r}: animationId {t.get('animationId')!r}")

    ids = set()
    for e in scn.get("entities", []):
        if e["id"] in ids:
            E.append(f"duplicate entity id {e['id']}")
        ids.add(e["id"])
        if e.get("type") not in ("object", "npc", "player"):
            E.append(f"entity {e.get('name')!r}: type {e.get('type')!r}")
        for k in ("inventory", "statusEffects"):
            if not isinstance(e.get(k), list):
                E.append(f"entity {e.get('name')!r}: {k} must be a list")
        for st in e.get("inventory", []) + list((e.get("equipment") or {}).values()):
            if st.get("templateId") not in items:
                E.append(f"entity {e['name']!r}: item templateId {st.get('templateId')} does not resolve")
        for slot in (e.get("equipment") or {}):
            if slot not in SLOTS:
                E.append(f"entity {e['name']!r}: equipment slot {slot!r}")
        if e["type"] == "object":
            if e.get("templateId") not in objs:
                E.append(f"object {e['name']!r}: templateId does not resolve")
            continue
        if e.get("templateId") and e["templateId"] not in htpl:
            E.append(f"npc {e['name']!r}: templateId does not resolve")
        if e.get("animationId") not in ANIMATIONS and e.get("animationId") not in ANIMATION_ALIASES:
            E.append(f"{e['type']} {e['name']!r}: animationId {e.get('animationId')!r} (falls back to casual-*)")
        if e.get("gender") not in ("male", "female"):
            E.append(f"{e['type']} {e['name']!r}: gender {e.get('gender')!r}")
        if e.get("stance") is not None and e["stance"] not in STANCES:
            E.append(f"npc {e['name']!r}: stance {e['stance']!r}")
        vp = e.get("voiceProfile") or {}
        if set(vp.get("age", [])) - AGES or set(vp.get("pitch", [])) - PITCH:
            W.append(f"{e['name']!r}: voiceProfile age/pitch values outside the enum are dropped")
        for b in e.get("schedule", []):
            if b.get("location") not in names:
                E.append(f"{e['name']!r}: schedule location {b.get('location')!r} is not a region name")
            if b.get("role") not in ("work", "leisure", "sleep"):
                E.append(f"{e['name']!r}: schedule role {b.get('role')!r}")
            if not (HHMM.match(b.get("start", "")) and HHMM.match(b.get("end", ""))):
                E.append(f"{e['name']!r}: schedule times must be HH:MM")
        if e["type"] in ("npc", "player") and f"media/{e['id']}/{e['id']}-portrait.webp" not in media:
            W.append(f"{e['name']!r}: no portrait (the game will generate one if an image service is set)")
    if scn.get("playerId") not in ids:
        E.append("playerId does not match an entity")
    for c in scn.get("calendar", []):
        if c.get("location") and c["location"] not in names:
            E.append(f"calendar {c['name']!r}: location is not a region name")
        if c.get("recurrence") not in ("none", "daily", "weekly"):
            E.append(f"calendar {c['name']!r}: recurrence {c.get('recurrence')!r}")
    for m in media:
        if not re.match(r"^media/[^/]+/[^/]+$", m):
            W.append(f"media path {m} is ignored by the importer")
        elif not m.endswith(".webp"):
            W.append(f"media {m} is not .webp")
    return E, W


def main():
    bad = False
    for p in sys.argv[1:]:
        scn, media = load(p)
        E, W = validate(scn, media)
        print(f"== {p}: {len(scn.get('regions', []))} regions, {len(scn.get('entities', []))} entities, {len(media)} media files")
        for w in W:
            print("  WARN ", w)
        for e in E:
            print("  ERROR", e)
        print(f"  {len(E)} error(s), {len(W)} warning(s)")
        bad |= bool(E)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
