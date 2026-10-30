"""Checks for a finished Anywhere RPG scenario.json: the values the engine accepts, references that
must resolve, and the map rules (nesting, doors, walls, reachability, beds, hostile buffers).

    python scenario_checks.py <scenario.json | folder | .zip> [...]     # exit code 1 on any error

Standard library only. check(scn, media) returns a list of problems:
    {"level": "error" | "warning" | "info", "msg": str, "refs": [ids of the things involved]}
"error" is something the import rejects or the game handles badly, "warning" is something that
plays badly, "info" is worth knowing (an image the game will generate).
"""
import io
import json
import re
import sys
import zipfile
from pathlib import Path

ANIMATIONS = set("""adventurer-man adventurer-woman alien archer-man archer-woman arctic-explorer astronaut athlete-man
athlete-woman barbarian-man barbarian-woman bard-man bard-woman bat bat-swarm blacksmith-man blacksmith-woman boar brown-bear
butcher-man butcher-woman casual-man casual-woman cat caveperson-man caveperson-woman chef-man chef-woman chicken child cleric-man
cleric-woman cow cowboy-man cowboy-woman crow cultist cyborg-man cyborg-woman deer demon detective-man detective-woman doctor-man
doctor-woman dog dwarf-man dwarf-woman eagle egyptian-man egyptian-woman elemental elf-man elf-woman farmer-man farmer-woman
firefighter-man firefighter-woman formal-man formal-woman ghost giant-lizard giant-rat goblin golem gray-wolf hacker-man
hacker-woman hazmat hoplite horse insect-swarm insectoid-alien jester kimono-man kimono-woman knight-man knight-woman
line-infantry-man line-infantry-woman mage-man mage-woman mimic monk-man monk-woman mummy mushroom-folk mutant necromancer-man
necromancer-woman ninja-man ninja-woman nomad-man nomad-woman office-man office-woman officer-man officer-woman old-man old-woman
orc peasant-man peasant-woman pig pirate-man pirate-woman plague-doctor police-man police-woman punk-man punk-woman raider-man
raider-woman red-fox robot rogue-man rogue-woman royalty-man royalty-woman samurai-man samurai-woman serpent sheep skeleton slime
soldier-man soldier-woman space-marine spider steampunk-man steampunk-woman superhero-man superhero-woman tentacle-horror
tree-ent troll vampire-man vampire-woman viking-man viking-woman werewolf witch worker-man worker-woman wyvern zombie""".split())
GROUND = {"grass", "dirt", "gravel", "wood", "stone"}
TEXTURES = {"grass", "undergrowth", "dirt", "mud", "sand", "gravel", "rock", "snow", "cobblestone", "flagstone-light",
            "flagstone-dark", "asphalt", "concrete", "floorboards", "parquet", "tile-marble", "tile-slate", "tile-ceramic",
            "tile-ceramic-turquoise", "carpet-red", "carpet-blue", "carpet-green", "metal-deck", "tech-panel", "bio-mold",
            "bio-slime-purple", "crystals-green", "crystals-purple", "crystals-red"}
WALLS = {"wood", "brick", "stone", "steel"}
AMBIENCE = {"bar_tavern", "beach", "cave", "computer", "crickets", "fireplace", "machine_shop", "medieval_battle",
            "nature_outdoors", "outdoor_crowd", "quiet_indoor", "river_stream", "underwater", "urban_city", "warzone", "none"}
ITEM_TYPES = {"wieldable", "head", "face", "necklace", "innerTorso", "torso", "gloves", "pants", "boots", "ring",
              "consumable", "misc", "material"}
SLOTS = {"head", "face", "necklace", "innerTorso", "torso", "wieldable1", "wieldable2", "gloves", "pants", "boots", "ring",
         "wieldable"}  # "wieldable" accepted loosely; the engine's own slot keys are wieldable1/2
QUALITY = {"common", "uncommon", "rare", "epic", "legendary"}
WEATHER = {"clear", "fog", "rain", "thunderstorm", "snow", "blizzard", "wind", "dust_storm", "meteor_shower", "heat"}
ATTRS = {"strength", "dexterity", "intellect", "perception", "charisma"}
AGES = {"Child", "Teen", "Adult", "MiddleAged", "Senior"}
PITCH = {"Deeper", "Average", "Brighter"}
ROLES = {"work", "leisure", "sleep"}
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
HOSTILE_BUFFER = 15  # cells between a hostile region and anywhere peaceful NPCs spend their day


# ---------------------------------------------------------------- loading
def load(path):
    """scenario.json, a scenario folder or a .zip -> (scenario dict, set of media paths like media/<id>/<file>)."""
    p = Path(path)
    if p.suffix.lower() == ".zip":
        z = zipfile.ZipFile(p)
        scn = json.load(io.TextIOWrapper(z.open("scenario.json"), encoding="utf-8"))
        return scn, {n for n in z.namelist() if n.startswith("media/") and not n.endswith("/")}
    root = p if p.is_dir() else p.parent
    scn = json.loads((root / "scenario.json" if p.is_dir() else p).read_text("utf-8"))
    return scn, media_of(root)


def media_of(root):
    m = Path(root) / "media"
    return {f.relative_to(root).as_posix() for f in m.rglob("*") if f.is_file()} if m.is_dir() else set()


# ---------------------------------------------------------------- geometry
def rect(pos, size):
    """Inclusive (x0, y0, x1, y1)."""
    return pos[0], pos[1], pos[0] + size[0] - 1, pos[1] + size[1] - 1


def contains(outer, inner):
    return outer[0] <= inner[0] and outer[1] <= inner[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def disjoint(a, b):
    return a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1]


def gap(a, b):
    """Cells between two rectangles (0 if they touch or overlap), measured like a king moves."""
    return max(0, b[0] - a[2] - 1, a[0] - b[2] - 1, b[1] - a[3] - 1, a[1] - b[3] - 1)


def cells(r):
    return [(x, y) for x in range(r[0], r[2] + 1) for y in range(r[1], r[3] + 1)]


def perimeter(r):
    return [(x, y) for x, y in cells(r) if x in (r[0], r[2]) or y in (r[1], r[3])]


def region_tree(regions):
    """id -> parent id (the smallest region that contains it, or None)."""
    rects = {r["id"]: rect(r["position"], r["size"]) for r in regions}
    area = {i: (q[2] - q[0] + 1) * (q[3] - q[1] + 1) for i, q in rects.items()}
    parent = {}
    for r in regions:
        rr = rects[r["id"]]
        outer = [o["id"] for o in regions if o is not r and contains(rects[o["id"]], rr)
                 and (rects[o["id"]] != rr or o["id"] < r["id"])]  # identical rects: the lower id is the parent
        parent[r["id"]] = min(outer, key=lambda i: area[i]) if outer else None
    return parent


# ---------------------------------------------------------------- checks
def check(scn, media=frozenset()):
    out = []

    def add(level, msg, *refs):
        out.append({"level": level, "msg": msg, "refs": [r for r in refs if r]})

    _top(scn, add)
    regions = [r for r in scn.get("regions", []) if isinstance(r, dict)]
    by_name = {}
    for r in regions:
        by_name.setdefault(r.get("name"), []).append(r)
    _regions(scn, regions, by_name, add)
    _templates(scn, regions, add)
    _entities(scn, by_name, media, add)
    if all(_has_geometry(r) for r in regions):
        _map(scn, regions, by_name, add)
    _media(media, add)
    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda p: order[p["level"]])
    return out


def _has_geometry(r):
    return all(isinstance(r.get(k), list) and len(r[k]) == 2 for k in ("position", "size"))


def _top(scn, add):
    for k in ("name", "gridSize", "regions", "entities", "playerId"):
        if k not in scn:
            add("error", f"Missing required key {k!r}; the import refuses the file.")
    gs = scn.get("gridSize")
    if not (isinstance(gs, list) and len(gs) == 2 and all(isinstance(v, (int, float)) for v in gs)):
        add("error", "gridSize must be two numbers [width, height].")
    if scn.get("stancesAuthored") is not True:
        add("warning", "stancesAuthored is not true, so the import forces every hostile NPC to stance 'hostile'.")
    for k in scn.get("weatherKinds", []):
        if k not in WEATHER:
            add("warning", f"Unknown weather kind {k!r}; the game drops it.")
    attrs = scn.get("attributes", {})
    if set(attrs) - ATTRS:
        add("error", f"Unknown attributes: {', '.join(sorted(set(attrs) - ATTRS))}.")
    spent = sum(v - 3 for v in attrs.values() if isinstance(v, (int, float)))
    if attrs and spent != 10:
        add("warning", f"Player attributes spend {spent} points over the base of 3; the game expects exactly 10.")
    if scn.get("difficulty") not in (None, "casual", "medium", "insane"):
        add("error", f"difficulty {scn['difficulty']!r} is not casual, medium or insane.")


def _regions(scn, regions, by_name, add):
    gw, gh = (scn.get("gridSize") or [0, 0])[:2]
    for name, rs in by_name.items():
        if len(rs) > 1:
            add("error", f"{len(rs)} regions are named {name!r}; schedules find regions by name, so this is ambiguous.",
                *[r["id"] for r in rs])
    for r in [scn.get("defaultTile") or {}] + regions:
        label = f"Region {r.get('name')!r}" if r in regions else "The default tile"
        if r.get("ground") and r["ground"] not in GROUND:
            add("error", f"{label}: ground {r['ground']!r} is not one of {', '.join(sorted(GROUND))}.", r.get("id"))
        if r.get("groundTexture") and r["groundTexture"] not in TEXTURES:
            add("error", f"{label}: unknown ground texture {r['groundTexture']!r}.", r.get("id"))
        amb = r.get("ambience")
        for v in ([amb] if isinstance(amb, str) else (amb or {}).values()):
            if v not in AMBIENCE:
                add("warning", f"{label}: ambience {v!r} has no sound folder in the game.", r.get("id"))
    for r in regions:
        rid, label = r.get("id"), f"Region {r.get('name')!r}"
        if not _has_geometry(r):
            add("error", f"{label} needs position [x, y] and size [w, h].", rid)
            continue
        if not isinstance(r.get("openings"), list):
            add("error", f"{label} lacks openings: [] (the game fails to load it).", rid)
        if r.get("wall") and r["wall"] not in WALLS:
            add("warning", f"{label}: wall {r['wall']!r} becomes 'wood'.", rid)
        rr = rect(r["position"], r["size"])
        if r["size"][0] < 1 or r["size"][1] < 1:
            add("error", f"{label} has an empty size {r['size']}.", rid)
        if rr[0] < 0 or rr[1] < 0 or rr[2] >= gw or rr[3] >= gh:
            add("error", f"{label} reaches outside the {gw}x{gh} map.", rid)
        edge = set(perimeter(rr))
        for o in r.get("openings") or []:
            if tuple(o) not in edge:
                add("warning", f"{label}: door {list(o)} is not on its edge; the game moves it to the nearest edge cell.",
                    rid)
        if r.get("wall") and not r.get("openings"):
            add("warning", f"Walled region {r['name']!r} has no door, so it is sealed.", rid)
    for i, a in enumerate(regions):
        if not _has_geometry(a):
            continue
        ra = rect(a["position"], a["size"])
        for b in regions[i + 1:]:
            if not _has_geometry(b):
                continue
            rb = rect(b["position"], b["size"])
            if not (disjoint(ra, rb) or contains(ra, rb) or contains(rb, ra)):
                add("error", f"Regions {a['name']!r} and {b['name']!r} partly overlap; one must be inside the "
                             "other or apart.", a["id"], b["id"])


def _templates(scn, regions, add):
    items = {t.get("id") for t in scn.get("itemTemplates", [])}
    objs = {t.get("id") for t in scn.get("objectTemplates", [])}
    region_ids = {r.get("id"): r for r in regions}
    for t in scn.get("itemTemplates", []):
        label = f"Item {t.get('name')!r}"
        if t.get("type") not in ITEM_TYPES:
            add("error", f"{label}: type {t.get('type')!r} is not an item type.", t.get("id"))
        if t.get("quality") not in QUALITY:
            add("error", f"{label}: quality {t.get('quality')!r} is not {', '.join(sorted(QUALITY))}.", t.get("id"))
        ab = t.get("attributeBonus")
        if ab and ab.get("key") not in ATTRS:
            add("error", f"{label}: attributeBonus key {ab.get('key')!r} is not an attribute.", t.get("id"))
    for t in scn.get("objectTemplates", []) + scn.get("hostileNpcTemplates", []):
        label = f"Template {t.get('name')!r}"
        for lid in t.get("lootPoolIds", []):
            if lid not in items:
                add("error", f"{label}: loot {lid} is not an item template.", t.get("id"))
        if "money" in t and not (isinstance(t["money"], (int, float)) and 0 <= t["money"] <= 5):
            add("error", f"{label}: money is a tier from 0 to 5, not {t['money']!r}.", t.get("id"))
        for eff in t.get("startingEffects", []):
            for es in eff.get("endState", []):
                if es.get("type") in ("spawnEntity", "replaceSelfWith") and es.get("templateId") \
                        and es["templateId"] not in objs:
                    add("error", f"{label}: effect {eff.get('desc')!r} spawns an object template that doesn't exist.",
                        t.get("id"))
    for t in scn.get("hostileNpcTemplates", []):
        label = f"Hostile type {t.get('name')!r}"
        r = region_ids.get(t.get("regionId"))
        if not r:
            add("error", f"{label}: its home region doesn't exist.", t.get("id"))
        elif not r.get("hostile"):
            add("warning", f"{label} lives in {r['name']!r}, which isn't marked hostile.", t.get("id"), r["id"])
        if t.get("animationId") not in ANIMATIONS:
            add("error", f"{label}: unknown sprite {t.get('animationId')!r}.", t.get("id"))


def _entities(scn, by_name, media, add):
    items = {t.get("id") for t in scn.get("itemTemplates", [])}
    objs = {t.get("id") for t in scn.get("objectTemplates", [])}
    htpl = {t.get("id") for t in scn.get("hostileNpcTemplates", [])}
    ids = set()
    for e in scn.get("entities", []):
        eid, kind = e.get("id"), e.get("type")
        label = f"{'Object' if kind == 'object' else 'Player' if kind == 'player' else 'NPC'} {e.get('name')!r}"
        if eid in ids:
            add("error", f"Two entities share the id {eid}.", eid)
        ids.add(eid)
        if kind not in ("object", "npc", "player"):
            add("error", f"{label}: type {kind!r} is not object, npc or player.", eid)
        for k in ("inventory", "statusEffects"):
            if not isinstance(e.get(k), list):
                add("error", f"{label}: {k} must be a list (the game fails to load it).", eid)
        if not (isinstance(e.get("pos"), list) and len(e["pos"]) == 2):
            add("error", f"{label} has no position.", eid)
        stock = (e.get("merchant") or {}).get("stock") or []
        for st in list(e.get("inventory") or []) + list((e.get("equipment") or {}).values()) + list(stock):
            if isinstance(st, dict) and st.get("templateId") not in items:
                add("error", f"{label} carries an item whose template doesn't exist.", eid)
        for slot in e.get("equipment") or {}:
            if slot not in SLOTS:
                add("error", f"{label}: {slot!r} is not an equipment slot.", eid)
        if kind == "object":
            if e.get("templateId") not in objs:
                add("error", f"{label}: its object template doesn't exist.", eid)
            continue
        if e.get("templateId") and e["templateId"] not in htpl:
            add("error", f"{label}: its hostile type doesn't exist.", eid)
        if e.get("animationId") not in ANIMATIONS:
            add("warning", f"{label}: unknown sprite {e.get('animationId')!r} (the game uses casual-man/woman).", eid)
        if e.get("gender") not in ("male", "female"):
            add("error", f"{label}: gender must be male or female.", eid)
        if e.get("stance") not in (None, "hostile", "neutral", "fleeing"):
            add("error", f"{label}: stance {e['stance']!r} is not hostile, neutral or fleeing.", eid)
        vp = e.get("voiceProfile") or {}
        if set(vp.get("age", [])) - AGES or set(vp.get("pitch", [])) - PITCH:
            add("warning", f"{label}: voice age or pitch values the game doesn't know are dropped.", eid)
        _schedule(e, label, by_name, add)
        if f"media/{eid}/{eid}-portrait.webp" not in media:
            add("info", f"{label} has no portrait; the game generates one if an image service is set.", eid)
    if scn.get("playerId") not in ids:
        add("error", "playerId doesn't match any entity; the import refuses the file.")
    for c in scn.get("calendar", []):
        if c.get("location") and c["location"] not in by_name:
            add("error", f"Calendar event {c.get('name')!r}: {c['location']!r} is not a region name.", c.get("id"))
        if c.get("recurrence") not in ("none", "daily", "weekly"):
            add("error", f"Calendar event {c.get('name')!r}: repeat {c.get('recurrence')!r} is not none, daily or weekly.",
                c.get("id"))


def _minutes(hhmm):
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def _schedule(e, label, by_name, add):
    sch = e.get("schedule")
    if not sch:
        if e.get("type") == "npc":
            add("warning", f"{label} has no schedule.", e.get("id"))
        return
    ok = True
    for b in sch:
        if b.get("location") not in by_name:
            add("error", f"{label}: schedule place {b.get('location')!r} is not a region name.", e.get("id"))
        if b.get("role") not in ROLES:
            add("error", f"{label}: schedule role {b.get('role')!r} is not work, leisure or sleep.", e.get("id"))
        if not (HHMM.match(str(b.get("start", ""))) and HHMM.match(str(b.get("end", "")))):
            add("error", f"{label}: schedule times must be HH:MM.", e.get("id"))
            ok = False
    if not ok:
        return
    if len(sch) == 1 and sch[0]["start"] == sch[0]["end"]:
        return  # here all day
    total = 0
    for i, b in enumerate(sch):
        total += (_minutes(b["end"]) - _minutes(b["start"])) % 1440
        nxt = sch[(i + 1) % len(sch)]
        if b["end"] != nxt["start"]:
            add("error", f"{label}: schedule jumps from {b['end']} to {nxt['start']} (a gap or an overlap).", e.get("id"))
    if total != 1440:
        add("error", f"{label}: schedule covers {total // 60}h{total % 60:02d}, not 24 hours.", e.get("id"))


class Walls:
    """The engine's movement rules (class `on` in the game's code): only objects with walkability <= 0
    block a cell, and walls are thin lines on a walled region's outer border. A step that crosses that
    border is blocked unless the cell on the inside is one of the region's openings, so every cell of a
    room can be stood on and a door is a cell of the room itself."""

    def __init__(self, regions, solid, gw, gh):
        self.solid, self.gw, self.gh = solid, gw, gh
        self.inside = {}  # cell -> ids of the walled regions it is in
        self.doors = {}
        for r in regions:
            if r.get("wall"):
                self.doors[r["id"]] = {tuple(o) for o in r.get("openings") or []}
                for c in cells(rect(r["position"], r["size"])):
                    self.inside.setdefault(c, set()).add(r["id"])

    def walkable(self, c):
        return 0 <= c[0] < self.gw and 0 <= c[1] < self.gh and c not in self.solid

    def step(self, a, b):
        """Whether a person can step between neighbouring cells a and b (either way)."""
        ia, ib = self.inside.get(a, set()), self.inside.get(b, set())
        return all(a in self.doors[r] for r in ia - ib) and all(b in self.doors[r] for r in ib - ia)

    def flood(self, start):
        seen, todo = {start}, [start]
        while todo:
            x, y = c = todo.pop()
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n not in seen and self.walkable(n) and self.step(c, n):
                    seen.add(n)
                    todo.append(n)
        return seen


def _map(scn, regions, by_name, add):
    gw, gh = (scn.get("gridSize") or [0, 0])[:2]
    if not all(isinstance(v, (int, float)) for v in (gw, gh)):
        return
    gw, gh = int(gw), int(gh)
    tpl = {t.get("id"): t for t in scn.get("objectTemplates", [])}
    rects = {r["id"]: rect(r["position"], r["size"]) for r in regions}
    parent = region_tree(regions)

    ents = [e for e in scn.get("entities", []) if isinstance(e.get("pos"), list) and len(e["pos"]) == 2]
    objs = [e for e in ents if e.get("type") == "object"]
    solid, occupied = {}, {}  # cell -> object; solid = walkability 0 or less
    for e in objs:
        t = tpl.get(e.get("templateId")) or {}
        walk = t.get("walkability") or 0
        er = rect(e["pos"], e.get("size") or t.get("size") or [1, 1])
        if er[0] < 0 or er[1] < 0 or er[2] >= gw or er[3] >= gh:
            add("error", f"Object {e.get('name')!r} reaches outside the map.", e.get("id"))
        for c in cells(er):
            if walk <= 0:
                solid[c] = e
            if walk < 1:
                other = occupied.get(c)
                if other and other is not e:
                    add("warning", f"Objects {other.get('name')!r} and {e.get('name')!r} overlap at {list(c)}.",
                        other.get("id"), e.get("id"))
                occupied[c] = e
    walls = Walls(regions, solid, gw, gh)

    for r in regions:
        if not r.get("wall"):
            continue
        for o in r.get("openings") or []:
            c = tuple(o)
            if c in solid:
                add("warning", f"Region {r['name']!r}: {solid[c].get('name')!r} blocks the door at {list(c)}.",
                    r["id"], solid[c].get("id"))
                continue
            x, y = c
            out = [n for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
                   if r["id"] not in walls.inside.get(n, ())]
            if out and not any(walls.walkable(n) and walls.step(c, n) for n in out):
                add("warning", f"Region {r['name']!r}: the door at {list(c)} leads nowhere (blocked outside, or a "
                               "neighbouring room has no matching door).", r["id"])

    people = [e for e in ents if e.get("type") in ("npc", "player")]
    for e in people:
        c = tuple(e["pos"])
        if not (0 <= c[0] < gw and 0 <= c[1] < gh):
            add("error", f"{e.get('name')!r} stands outside the map.", e.get("id"))
        elif c in solid:
            add("error", f"{e.get('name')!r} starts inside {solid[c].get('name')!r}.", e.get("id"), solid[c].get("id"))

    player = next((e for e in ents if e.get("id") == scn.get("playerId")), None)
    if player and walls.walkable(tuple(player["pos"])):
        seen = walls.flood(tuple(player["pos"]))
        for e in people:
            if e is not player and walls.walkable(tuple(e["pos"])) and tuple(e["pos"]) not in seen:
                add("warning" if e.get("hostile") else "error",
                    f"{e.get('name')!r} can't be reached on foot from the player.", e.get("id"))
        for r in regions:
            if r.get("wall") and not any(c in seen for c in cells(rects[r["id"]])):
                add("error", f"Room {r['name']!r} can't be reached on foot from the player.", r["id"])
        for e in objs:
            t = tpl.get(e.get("templateId")) or {}
            x0, y0, x1, y1 = rect(e["pos"], e.get("size") or t.get("size") or [1, 1])
            ring = [(x, y) for x in range(x0 - 1, x1 + 2) for y in range(y0 - 1, y1 + 2)
                    if not (x0 <= x <= x1 and y0 <= y <= y1)]
            if not any(c in seen for c in ring + cells((x0, y0, x1, y1))):
                add("warning", f"Nobody can stand beside {e.get('name')!r}.", e.get("id"))

    _sleep_and_safety(scn, regions, by_name, rects, parent, objs, tpl, add)


def _sleep_and_safety(scn, regions, by_name, rects, parent, objs, tpl, add):
    def ancestors(rid):
        while rid:
            yield rid
            rid = parent.get(rid)

    hostile_ids = {r["id"] for r in regions if r.get("hostile")}
    sleepers, peaceful_places = {}, {}
    for e in scn.get("entities", []):
        if e.get("type") not in ("npc", "player") or e.get("templateId"):
            continue
        for b in e.get("schedule") or []:
            r = (by_name.get(b.get("location")) or [None])[0]
            if not r:
                continue
            if b.get("role") == "sleep":
                sleepers.setdefault(r["id"], set()).add(e.get("id"))
            if not e.get("hostile"):
                peaceful_places.setdefault(r["id"], set()).add(e.get("id"))
                if hostile_ids & set(ancestors(r["id"])):
                    add("warning", f"{e.get('name')!r} spends {b['start']}-{b['end']} in {r['name']!r}, "
                                   "which is hostile territory.", e.get("id"), r["id"])
    beds = [rect(e["pos"], e.get("size") or tpl[e["templateId"]].get("size") or [1, 1])
            for e in objs if (tpl.get(e.get("templateId")) or {}).get("forSleep")]
    for rid, who in sleepers.items():
        r = next(r for r in regions if r["id"] == rid)
        n = sum(1 for b in beds if contains(rects[rid], b))
        if n == 0:
            add("warning", f"{len(who)} sleep in {r['name']!r}, which has nothing to sleep on.", rid, *sorted(who))
        elif n < len(who):
            add("warning", f"{len(who)} sleep in {r['name']!r}, which has {n} place{'s' * (n != 1)} to sleep.",
                rid, *sorted(who))
    name = {r["id"]: r["name"] for r in regions}
    for h in sorted(hostile_ids):
        near = []
        for rid in peaceful_places:
            if h in set(ancestors(rid)) or rid in set(ancestors(h)):
                continue
            d = gap(rects[h], rects[rid])
            if d < HOSTILE_BUFFER:
                near.append((d, rid))
        if near:
            near.sort()
            listed = ", ".join(f"{name[rid]!r} ({d})" for d, rid in near[:4])
            more = f" and {len(near) - 4} more" if len(near) > 4 else ""
            add("warning", f"Hostile {name[h]!r} is within {HOSTILE_BUFFER} cells of places peaceful NPCs use: "
                           f"{listed}{more}.", h, *[rid for _, rid in near])


def _media(media, add):
    for m in sorted(media):
        if not re.match(r"^media/[^/]+/[^/]+$", m):
            add("warning", f"The import ignores {m} (only media/<id>/<file> is read).")
        elif not m.endswith(".webp"):
            add("warning", f"{m} is not a .webp file.")


# ---------------------------------------------------------------- command line
def main():
    bad = False
    for p in sys.argv[1:]:
        scn, media = load(p)
        found = check(scn, media)
        counts = {k: sum(1 for f in found if f["level"] == k) for k in ("error", "warning", "info")}
        print(f"== {p}: {len(scn.get('regions', []))} regions, {len(scn.get('entities', []))} entities")
        for f in found:
            if f["level"] != "info":
                print(f"  {f['level'].upper():7} {f['msg']}")
        print(f"  {counts['error']} error(s), {counts['warning']} warning(s), {counts['info']} note(s)")
        bad |= counts["error"] > 0
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
