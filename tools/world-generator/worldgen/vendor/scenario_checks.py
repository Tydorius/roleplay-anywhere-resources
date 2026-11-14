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
import math
import re
import sys
import zipfile
from functools import lru_cache
from pathlib import Path

# Character and creature sprites in Anywhere RPG 1.0 (build 26557354): the keys of the bundle's sprite table,
# less the two vehicle sheets. 0.18 had 146; 1.0 renamed a few and migrates the old names on import.
ANIMATIONS = set("""adventurer-man adventurer-woman alien ancient-chinese-man ancient-chinese-woman android-man android-woman angel ant
arabian-man arabian-woman archer-man archer-woman arctic-explorer assassin-man assassin-woman astronaut athlete-man
athlete-woman aviator-man aviator-woman aztec-warrior-man aztec-warrior-woman banshee barbarian-man barbarian-woman
bard-man bard-woman bat bat-swarm bear-folk bee beetle beggar-man beggar-woman bird-folk blacksmith-man
blacksmith-woman boar bride brown-bear butcher-man butcher-woman butterfly camel casual-man casual-woman cat
cat-folk-man cat-folk-woman caterpillar caveperson-man caveperson-woman centaur centipede chef-man chef-woman chicken
child clergy-man clergy-woman cleric-man cleric-woman clown cockroach cow cowboy-man cowboy-woman crab crocodile crow
cultist cyborg-man cyborg-woman dark-elf-man dark-elf-woman deer demon detective-man detective-woman doctor-man
doctor-woman dog dog-folk dolphin donkey dragon dragonborn dragonfly druid-man druid-woman duck dwarf-man dwarf-woman
eagle egyptian-man egyptian-woman elemental elephant elf-man elf-woman elk fairy farmer-man farmer-woman
firefighter-man firefighter-woman firefly fish-school fisher-man fisher-woman fly formal-man formal-woman fox-folk-man
fox-folk-woman frog frog-folk gargoyle ghost ghoul gladiator-man gladiator-woman gnoll gnome goat goblin golem gorilla
grasshopper gray-wolf greek-citizen-man greek-citizen-woman griffin groom hacker-man hacker-woman halfling-man
halfling-woman harpy hazmat healer-man healer-woman hedgehog hellhound hoplite horse hunter-man hunter-woman imp
innkeeper-man innkeeper-woman insect-swarm insectoid-alien janitor-man janitor-woman jester kimono-man kimono-woman
knight-man knight-woman kobold ladybug lich line-infantry-man line-infantry-woman lion lizard lizard-folk mage-man
mage-woman mantis mechanic-man mechanic-woman medieval-boy medieval-girl merchant-man merchant-woman mermaid mimic
miner-man miner-woman minotaur monk-man monk-woman monkey mosquito moth mouse-folk mummy mushroom-folk mutant
necromancer-man necromancer-woman ninja-man ninja-woman noble-man noble-woman nomad-man nomad-woman nurse-man
nurse-woman octopus office-man office-woman officer-man officer-woman ogre old-man old-woman orc otter owl paladin-man
paladin-woman panda parrot peasant-man peasant-woman penguin phoenix pig pirate-man pirate-woman plague-doctor
polar-bear police-man police-woman possessed-doll prisoner-man prisoner-woman professor-man professor-woman
pterodactyl punk-man punk-woman rabbit rabbit-folk raccoon raider-man raider-woman raptor rat rat-folk red-fox
reptilian-alien roaring-twenties-man roaring-twenties-woman robot rogue-man rogue-woman roman-citizen-man
roman-citizen-woman roman-legionary royalty-man royalty-woman sailor-man sailor-woman samurai-man samurai-woman satyr
scarecrow scholar-man scholar-woman scientist-man scientist-woman scorpion seagull seal security-guard-man
security-guard-woman serpent servant-man servant-woman shark sheep skeleton slime snail soldier-man soldier-woman
south-asian-man south-asian-woman space-marine spider squirrel starship-crew-man starship-crew-woman steampunk-man
steampunk-woman stegosaurus student-man student-woman superhero-man superhero-woman t-rex tentacle-horror tiefling-man
tiefling-woman tiger town-guard-man town-guard-woman tree-ent triceratops troll turtle unicorn vampire-man
vampire-woman victorian-man victorian-woman viking-man viking-woman waiter-man waiter-woman wasp werewolf witch
wizard-student-man wizard-student-woman wolf-folk-man wolf-folk-woman worker-man worker-woman worm wraith ww2-soldier
wyvern yeti zombie""".split())
ANIMATION_ALIASES = {"bounty-hunter-man": "aviator-man", "bounty-hunter-woman": "aviator-woman", "giant-crab": "crab",
                     "giant-lizard": "lizard", "giant-rat": "rat", "giant-scorpion": "scorpion"}
VEHICLE_SHEETS = {"bicycle", "dune-buggy"}  # built-in sheets an object template's `sheet` can name
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
OBJECT_TAGS = ["bed", "table", "social", "chair", "light", "work", "food", "storage", "filler", "landmark", "plant"]
VOICE_TAGS = ["Announcer", "Australian", "British", "Eager", "Emphatic", "Southern", "Villain", "Whispering", "Smooth",
              "Yelling", "Scottish", "Indian", "WestAfrican", "EasternEuropean", "Demonic", "Ghostly", "Robotic"]
# Anywhere RPG 1.0 additions, from its bundle (index-BrLojUrw.js):
STANCES = {"hostile", "neutral", "fleeing", "skittish"}  # a character's stance
TEMPLATE_STANCES = {"hostile", "neutral", "skittish"}    # an NPC template's (populations are neutral or skittish)
DOOR_KINDS = ["door", "bars", "gate", "curtain"]         # a walled region's `door`; "none" leaves its doorways open
SIDES = {"n": (0, 1), "e": (1, 0), "s": (0, -1), "w": (-1, 0)}  # an opening's third element: the side it opens
VEHICLES = {"drive", "ride"}                             # an object template's `vehicle`
WALKS = {"yes", "slow", "no"}                            # a liquid's `walk` in unbounded.profile.media
SHAPES = {"organic"}                                     # region `shape`; rounds open regions at least 5 x 5
ORGANIC_MIN = 5
MAX_MEDIA = 8       # the game's own unbounded.profile.media lists have at most 8 entries, and it adds no more
NEW_COLOR = "#3a6d8a"  # the medium the game appends for a surface no medium matches
DEFAULT_MEDIA = ({"name": "deep water", "walk": "no", "color": "#24506e", "flows": True},
                 {"name": "shallow water", "walk": "slow", "color": "#3f7f90", "flows": True})
FLOOR_GAP = 24  # the game lays floors out east of the map, 24 cells apart (it reads any spot outside it)


def meta():
    """The value lists the editor offers, from the same sets the checks use."""
    return {"animations": sorted(ANIMATIONS), "ground": sorted(GROUND), "textures": sorted(TEXTURES),
            "walls": sorted(WALLS), "ambience": sorted(AMBIENCE - {"none"}), "itemTypes": sorted(ITEM_TYPES),
            "slots": [s for s in ("head", "face", "necklace", "innerTorso", "torso", "wieldable1", "wieldable2",
                                  "gloves", "pants", "boots", "ring")],
            "quality": ["common", "uncommon", "rare", "epic", "legendary"], "attributes": sorted(ATTRS),
            "ages": ["Child", "Teen", "Adult", "MiddleAged", "Senior"], "pitch": ["Deeper", "Average", "Brighter"],
            "roles": ["work", "leisure", "sleep"], "objectTags": OBJECT_TAGS, "voiceTags": VOICE_TAGS,
            "animationAliases": ANIMATION_ALIASES, "vehicleSheets": sorted(VEHICLE_SHEETS),
            "stances": ["neutral", "skittish", "hostile", "fleeing"], "templateStances": ["neutral", "skittish", "hostile"],
            "doorKinds": DOOR_KINDS + ["none"], "vehicles": sorted(VEHICLES), "shapes": sorted(SHAPES)}
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
HOSTILE_BUFFER = 15  # cells between a hostile region and anywhere peaceful NPCs spend their day
ROOM_CAP = 8         # people awake in one walled room: the GM reads each in full every turn
CIRCLE_CELLS = 615   # one 14-cell circle: open ground gets ROOM_CAP per circle


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


# ---------------------------------------------------------------- Anywhere RPG 1.0 structures
def npc_templates(scn):
    """(templates, key, legacy): the NPC templates the game keeps. 1.0 writes `npcTemplates`; 0.18 and the bundled
    presets write `hostileNpcTemplates`, which the import renames, or drops when `npcTemplates` is there too."""
    if isinstance(scn.get("npcTemplates"), list):
        return scn["npcTemplates"], "npcTemplates", False
    legacy = scn.get("hostileNpcTemplates")
    return (legacy if isinstance(legacy, list) else []), "hostileNpcTemplates", True


def template_homes(t):
    """[(region id, count)] an NPC template spawns in: 1.0's `homes`, or 0.18's `regionId` and `count`."""
    if isinstance(t.get("homes"), list):
        return [(h.get("regionId"), h.get("count", 0)) for h in t["homes"] if isinstance(h, dict)]
    return [(t["regionId"], t.get("count", 0))] if t.get("regionId") else []


def template_stance(t, legacy):
    """The stance a template plays with after the import: its own, else hostile for a 0.18 hostile type unless
    attacksOnSight is false."""
    if t.get("stance"):
        return t["stance"]
    return "hostile" if legacy and t.get("attacksOnSight") is not False else None


def is_opening(o):
    return isinstance(o, (list, tuple)) and len(o) in (2, 3) and all(isinstance(v, (int, float)) for v in o[:2])


def opening_sides(r, o):
    """The sides an opening [x, y] or [x, y, side] of region r opens, as the 1.0 import reads it: a side the cell is
    on is kept; anything else opens every side of the region's edge the cell is on; off the edge, nothing."""
    x0, y0, x1, y1 = rect(r["position"], r["size"])
    x, y = o[0], o[1]
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return []
    on = [s for s, hit in (("n", y == y1), ("e", x == x1), ("s", y == y0), ("w", x == x0)) if hit]
    return [o[2]] if len(o) > 2 and o[2] in on else on


def is_floor(r):
    """A 1.0 floor (`pocket: {anchor, level}`): a storey, cellar or tunnel laid out as its own plane beside the map."""
    return isinstance(r.get("pocket"), dict) and _has_geometry(r)


def plane_of(floor_rects, rr):
    """The id of the floor whose rectangle holds rr, or None (the main map, or nowhere)."""
    return next((fid for fid, f in floor_rects.items() if contains(f, rr)), None)


def footprint(e, tpl):
    """The cells an object covers; a door (a zero-width object on a doorway) covers none."""
    t = tpl.get(e.get("templateId")) or {}
    return cells(rect(e["pos"], e.get("size") or t.get("size") or [1, 1]))


def is_locked(e):
    return any(m.get("type") == "locked" for s in e.get("statusEffects") or [] if isinstance(s, dict)
               for m in (s.get("def") or {}).get("mechanics") or [] if isinstance(m, dict))


def norm_shape(v):
    """'organic' as the game reads a region's `shape` (trimmed, any case, 'natural' the same word), or None
    when it draws a rectangle."""
    if isinstance(v, str):
        v = v.strip().lower()
        if v in ("organic", "natural"):
            return "organic"
    return None


def norm_surface(v):
    """The `surface` the game keeps: trimmed, lowercased, cut to 40 characters, or None (no surface)."""
    if isinstance(v, str):
        v = v.strip().lower()[:40]
        return v or None
    return None


def media_list(scn):
    """(list, defaults): the liquid list the game reads. A scenario with no `unbounded` key gets the two
    built-in waters; `unbounded` without a profile.media list gives (None, False): the game fails to load it
    as soon as any region has a surface."""
    u = scn.get("unbounded")
    if u is None:
        return DEFAULT_MEDIA, True
    prof = u.get("profile") if isinstance(u, dict) else None
    media = prof.get("media") if isinstance(prof, dict) else None
    return (media, False) if isinstance(media, list) else (None, False)


def is_river(r):
    """A liquid region at least three times as long as it is wide, and at most 12 wide: the game draws it as a
    meandering band of its narrower size through the middle, not a pool filling the region."""
    w, h = r.get("size", (0, 0))
    return max(w, h) >= 3 * min(w, h) and min(w, h) <= 12


def _surface_region(r):
    """A region whose surface the game resolves: not a floor, not walled, with geometry and a non-empty surface."""
    return (not r.get("wall") and "pocket" not in r and _has_geometry(r)
            and isinstance(r.get("surface"), str) and r["surface"].strip())


def resolve_surfaces(scn):
    """Every surface the game resolves, regions in scenario order against a working copy of the media list
    (later regions see what earlier ones made it add): {region id: {"medium": m, "kind": "pool"|"river",
    "added": bool}}, or None for a region whose surface is ignored because the list is full. None as a whole
    when the media list itself is broken: the game fails to load the scenario then."""
    media, _defaults = media_list(scn)
    if media is None:
        return None
    out = {}
    media = list(media)
    for r in scn.get("regions", []):
        if not (isinstance(r, dict) and _surface_region(r)):
            continue
        surf = norm_surface(r["surface"])
        m = next((e for e in media if isinstance(e, dict) and e.get("name") == surf), None)
        added = False
        if m is None:
            near = [e for e in media if isinstance(e, dict) and isinstance(e.get("name"), str)
                    and (surf in e["name"] or e["name"] in surf)]
            if near:
                want = "slow" if min(r["size"]) <= 3 else "no"  # a narrow stream is waded, a wide one isn't
                m = next((e for e in near if e.get("walk") == want), near[0])
            elif len(media) < MAX_MEDIA:
                m = {"name": surf, "walk": "no", "color": NEW_COLOR, "flows": True}
                media.append(m)
                added = True
            else:
                out[r.get("id")] = None
                continue
        out[r.get("id")] = {"medium": m, "kind": "river" if is_river(r) else "pool", "added": added}
    return out


def _i32(x):
    x &= 0xFFFFFFFF
    return x - 0x100000000 if x & 0x80000000 else x


def _imul(a, b):  # Math.imul: the low 32 bits of the product, as a signed integer
    return _i32(a * b)


def _hash32(s):
    t = 0
    for ch in s:
        t = _i32(t * 31 + ord(ch))
    return t & 0xFFFFFFFF


def _rng(seed):
    t = _i32(seed)

    def nxt():
        nonlocal t
        t = _i32(t + 1831565813)
        n = _imul(t ^ (t & 0xFFFFFFFF) >> 15, t | 1)
        n = _i32(n + _imul(n ^ (n & 0xFFFFFFFF) >> 7, n | 61)) ^ n
        return ((n ^ ((n & 0xFFFFFFFF) >> 14)) & 0xFFFFFFFF) / 4294967296

    return nxt


_FILL, _P, _U0 = .7, 3, .4


def _keep_centre(p, w, h):
    """The blob's centre cell forced on, then only the 1s the centre reaches across (4-connected) survive.
    Returns how many cells were reached."""
    c = (h // 2) * w + w // 2
    p[c] = 1
    seen = bytearray(w * h)
    seen[c] = 1
    todo, n = [c], 0
    while todo:
        i = todo.pop()
        n += 1
        x, y = i % w, i // w
        for ok, j in ((x > 0, i - 1), (x < w - 1, i + 1), (y > 0, i - w), (y < h - 1, i + w)):
            if ok and not seen[j] and p[j]:
                seen[j] = 1
                todo.append(j)
    for k in range(w * h):
        if p[k] and not seen[k]:
            p[k] = 0
    return n


@lru_cache(maxsize=None)
def blob_mask(rid, w, h):
    """The blob a region with this id fills in a w x h rectangle: the game's own Hhe(id, w, h), bit for bit
    (its 32-bit hash and rng, then the same float maths and centre-keeping fill). bytes of 0 and 1, [y * w + x],
    row 0 the region's lowest y."""
    i = _rng(_hash32("organic:" + rid))
    o = [2 + math.floor(i() * 2), 4 + math.floor(i() * 2), 7]  # each harmonic's base radius, in cells
    g = [i() * math.pi * 2 for _ in o]                         # its phase
    r = [.5, .3, .2]                                           # its weight
    m = lambda u: sum((r[l] * math.sin(o[l] * u + g[l]) for l in range(3)), 0)  # the wobble along angle u
    lo, hi = math.inf, -math.inf
    for u in range(360):
        c = m(u / 360 * math.pi * 2)
        lo, hi = min(lo, c), max(hi, c)
    p = bytearray(w * h)
    u = _U0
    while True:  # shrink until the blob is at least 70% filled, keeping its centre
        for k in range(w * h):
            p[k] = 0
        for y in range(h):
            for x in range(w):
                d = (x + .5) / w * 2 - 1
                A = (y + .5) / h * 2 - 1
                f = math.pow(math.pow(abs(d), _P) + math.pow(abs(A), _P), 1 / _P)
                v = (m(math.atan2(A, d)) - lo) / ((hi - lo) or 1)
                if f <= 1 - u * v:
                    p[y * w + x] = 1
        if _keep_centre(p, w, h) >= _FILL * w * h or u < .02:
            return bytes(p)
        u *= .8


def liquid_cells(scn, regions):
    """Cells nobody can walk on because a region's surface is a liquid with walk 'no', the way the game
    resolves it. An organic region counts only the cells of its blob (blob_mask); a region without a surface
    inside it (a bridge, a jetty) is dry."""
    out = set()
    resolved = resolve_surfaces(scn) or {}
    for r in regions:
        res = resolved.get(r.get("id"))
        if not res or res["medium"].get("walk") != "no":
            continue
        rr = rect(r["position"], r["size"])
        w, h = r["size"]
        if norm_shape(r.get("shape")) and min(w, h) >= ORGANIC_MIN:
            mask = blob_mask(str(r.get("id")), w, h)
            wet = {(r["position"][0] + x, r["position"][1] + y)
                   for y in range(h) for x in range(w) if mask[y * w + x]}
        else:
            wet = set(cells(rr))
        for d in regions:
            if d is not r and not d.get("surface") and _has_geometry(d) and contains(rr, rect(d["position"], d["size"])):
                wet -= set(cells(rect(d["position"], d["size"])))
        out |= wet
    return out


# ---------------------------------------------------------------- checks
def check(scn, media=frozenset()):
    out = []

    def add(level, msg, *refs):
        out.append({"level": level, "msg": msg, "refs": [r for r in refs if r]})

    regions = [r for r in scn.get("regions", []) if isinstance(r, dict)]
    resolved = resolve_surfaces(scn)
    _top(scn, add, any(_surface_region(r) for r in regions))
    by_name = {}
    for r in regions:
        by_name.setdefault(r.get("name"), []).append(r)
    mods = _code_mods(scn, regions, add)
    _native_portals(scn, regions, add, mods)
    _regions(scn, regions, by_name, add, mods, resolved)
    _templates(scn, regions, add)
    _entities(scn, by_name, media, add)
    if all(_has_geometry(r) for r in regions):
        _map(scn, regions, by_name, add, mods)
    _media(media, add)
    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda p: order[p["level"]])
    return out


def _has_geometry(r):
    return all(isinstance(r.get(k), list) and len(r[k]) == 2 for k in ("position", "size"))


def _code_mods(scn, regions, add):
    """What the scenario's code-mod data (arpgMods) changes about the map, from the mods' READMEs in
    ../code-mod-loader/examples:
    - portals: each end is an object pad, a cell or a region. You step onto a pad (or into the region)
      and come out on a free cell beside the other end (or anywhere in its region); twoWay works both ways;
    - floors: a storey's openings are regions nobody can walk into, and its stairs are portals.
    Returns {"portals": [(name, from_end, to_end, two_way)], "openings": {region ids}, "entered": {region
    ids a portal leads into}}, where an end is ("pad" | "region", [cells]). A scenario without arpgMods
    gets empty sets, so the plain checks are unchanged. Region groups need no scenario data, so the
    checks can't tell when that mod is in use."""
    out = {"portals": [], "openings": set(), "entered": set()}
    mods = scn.get("arpgMods")
    if not isinstance(mods, dict) or not mods:
        return out
    add("info", f"Uses code-mod data: {', '.join(sorted(mods))}. Those mods must be installed in the game.")
    geo = [r for r in regions if _has_geometry(r)]
    region_by = {}
    for r in geo:
        region_by.setdefault((r.get("name") or "").lower(), r)
    tpl = {t.get("id"): t for t in scn.get("objectTemplates", [])}
    obj_by = {}
    for e in scn.get("entities", []):
        if e.get("type") == "object" and isinstance(e.get("pos"), list) and len(e["pos"]) == 2:
            obj_by.setdefault((e.get("name") or "").lower(), e)

    def end(spec):
        if not isinstance(spec, dict):
            return None
        if isinstance(spec.get("cell"), list) and len(spec["cell"]) == 2:
            return "pad", [tuple(spec["cell"])]
        if spec.get("object"):
            e = obj_by.get(str(spec["object"]).lower())
            if e:
                t = tpl.get(e.get("templateId")) or {}
                return "pad", cells(rect(e["pos"], e.get("size") or t.get("size") or [1, 1]))
        if spec.get("region"):
            r = region_by.get(str(spec["region"]).lower())
            if r:
                return "region", cells(rect(r["position"], r["size"]))
        return None

    portals = mods.get("portals") if isinstance(mods.get("portals"), list) else []
    for p in portals:
        if not isinstance(p, dict):
            continue
        a, b = end(p.get("from")), end(p.get("to"))
        for side, e in (("from", a), ("to", b)):
            if e is None:
                add("warning", f"Portal {p.get('name')!r}: its {side} end names nothing on the map, so the portals "
                               "mod drops it.")
        if a and b:
            out["portals"].append((p.get("name"), a, b, bool(p.get("twoWay"))))
    floors = mods.get("floors") if isinstance(mods.get("floors"), list) else []
    if floors and not portals:
        add("warning", "arpgMods has floors but no portals: the storeys' stairs are portals, so nobody can reach them.")
    for f in floors:
        if not isinstance(f, dict):
            continue
        for key in ("area", "above"):
            if f.get(key) and str(f[key]).lower() not in region_by:
                add("warning", f"Floor {f.get('name')!r}: {key} {f[key]!r} names no region.")
        for o in f.get("openings") or []:
            r = region_by.get(str(o).lower())
            if r:
                out["openings"].add(r["id"])
            else:
                add("warning", f"Floor {f.get('name')!r}: opening {o!r} names no region.")
    # a region a portal leads into (a storey reached only by its stairs) is not sealed
    ends = {c for (_n, a, b, two) in out["portals"] for c in b[1] + (a[1] if two else [])}
    for r in geo:
        if any(c in ends for c in cells(rect(r["position"], r["size"]))):
            out["entered"].add(r["id"])
    return out


def _native_portals(scn, regions, add, mods):
    """Anywhere RPG 1.0's own portals: an object with `portal: {to: <object id>}` takes you to a free cell beside
    the other object (god mode's Link Portal sets both ends). Adds each working end to mods["portals"] as a one-way
    pad-to-pad jump, and the regions they lead into to mods["entered"]."""
    ents = [e for e in scn.get("entities", []) if isinstance(e, dict)]
    by_id = {e.get("id"): e for e in ents}
    tpl = {t.get("id"): t for t in scn.get("objectTemplates", []) if isinstance(t, dict)}

    def pad(e):
        if not (isinstance(e.get("pos"), list) and len(e["pos"]) == 2):
            return None
        return footprint(e, tpl) or [tuple(e["pos"])]

    for e in ents:
        if "portal" not in e:
            continue
        label = f"{e.get('name')!r}"
        p = e["portal"]
        to = p.get("to") if isinstance(p, dict) else None
        other = by_id.get(to)
        if e.get("type") != "object":
            add("warning", f"{label} has a portal, but only objects lead anywhere.", e.get("id"))
        elif not isinstance(p, dict) or not to:
            add("warning", f"Portal {label}: portal must be {{to: <id of the object at the other end>}}.", e.get("id"))
        elif other is None or other.get("type") != "object":
            add("error", f"Portal {label} leads to {to!r}, which is no object in the scenario.", e.get("id"))
        elif other is e:
            add("warning", f"Portal {label} leads to itself.", e.get("id"))
        else:
            back = other.get("portal") if isinstance(other.get("portal"), dict) else {}
            if back.get("to") != e.get("id"):
                add("info", f"Portal {label} leads to {other.get('name')!r}, which doesn't lead back (one way).",
                    e.get("id"), other.get("id"))
            a, b = pad(e), pad(other)
            if a and b:
                mods["portals"].append((e.get("name"), ("pad", a), ("pad", b), False))
                for r in regions:
                    if _has_geometry(r) and any(c in b for c in cells(rect(r["position"], r["size"]))):
                        mods["entered"].add(r["id"])


def _top(scn, add, any_surface=False):
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
    if isinstance(scn.get("npcTemplates"), list) and scn.get("hostileNpcTemplates"):
        add("warning", "The scenario has both npcTemplates and hostileNpcTemplates; the game keeps npcTemplates and "
                       "drops hostileNpcTemplates.")
    _unbounded(scn.get("unbounded"), add, any_surface)


def _unbounded(u, add, any_surface=False):
    """The open world around the map (1.0): the seed and the liquid media the game draws surfaces with. The
    editor keeps it as it is; this only catches a broken shape."""
    if u is None:
        return
    if not isinstance(u, dict):
        add("error", "unbounded must be an object {seed, profile, areas}.")
        return
    if not isinstance(u.get("seed"), (int, float)):
        add("warning", "unbounded.seed should be a number.")
    prof = u.get("profile")
    media = prof.get("media") if isinstance(prof, dict) else None
    if prof is not None and not (isinstance(prof, dict) and isinstance(media or [], list)):
        add("warning", "unbounded.profile should be {media: [...], lowEdges: [...]}.")
        media = None
    if not isinstance(media, list):
        if any_surface:
            add("error", "unbounded.profile.media is not a list; the game fails to load the scenario as soon "
                         "as a region has a surface.")
        media = []
    names = set()
    for m in media:
        if not isinstance(m, dict):
            add("warning", f"unbounded.profile.media entry {m!r} needs a name and walk yes, slow or no.")
            continue
        nm = m.get("name")
        if not (isinstance(nm, str) and nm and nm == nm.lower() and len(nm) <= 40):
            add("warning", f"unbounded.profile.media entry {nm!r}: name must be a lowercase string of 1-40 "
                           "characters.")
        if isinstance(nm, str):
            if nm.lower() in names:
                add("warning", f"unbounded.profile.media: two entries named {nm!r}; the game's own names are unique.")
            names.add(nm.lower())
        if m.get("walk") not in WALKS:
            add("warning", f"unbounded.profile.media entry {nm!r}: walk {m.get('walk')!r} isn't yes, slow or no.")
        if not (isinstance(m.get("color"), str) and HEX.match(m["color"])):
            add("warning", f"unbounded.profile.media entry {nm!r}: color {m.get('color')!r} isn't a colour like "
                           "#24506e.")
        for key in ("flows", "glow"):
            if key in m and not isinstance(m[key], bool):
                add("warning", f"unbounded.profile.media entry {nm!r}: {key} must be true or false.")
    if len(media) > MAX_MEDIA:
        add("info", f"unbounded.profile.media has {len(media)} entries; the game's own lists have at most "
                    f"{MAX_MEDIA}, and it adds no more.")
    areas = u.get("areas")
    if areas is not None and not isinstance(areas, list):
        add("warning", "unbounded.areas should be a list.")
    for a in areas or []:
        rec = a.get("record") if isinstance(a, dict) else None
        if not (isinstance(rec, dict) and isinstance(rec.get("id"), str)):
            add("warning", "An unbounded area has no record with an id like \"-1,0\".")


def _regions(scn, regions, by_name, add, mods, resolved=None):
    gw, gh = (scn.get("gridSize") or [0, 0])[:2]
    if not all(isinstance(v, (int, float)) for v in (gw, gh)):
        gw, gh = 0, 0
    main = (0, 0, gw - 1, gh - 1)
    floor_rects = {r["id"]: rect(r["position"], r["size"]) for r in regions if is_floor(r)}
    ids = {r.get("id") for r in regions}
    people = {e.get("name") for e in scn.get("entities", []) if isinstance(e, dict) and e.get("type") in ("npc", "player")}
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
        if is_floor(r):
            if not disjoint(rr, main):
                add("warning", f"{label} is a floor but lies on the map; the game lays floors out beside it, and "
                               "the map cells under it would become part of the floor.", rid)
        elif not contains(main, rr) and plane_of(floor_rects, rr) is None:
            add("error", f"{label} reaches outside the {gw}x{gh} map" + (" and isn't inside a floor." if floor_rects
                                                                        else "."), rid)
        for o in r.get("openings") or []:
            if not is_opening(o):
                add("warning", f"{label}: door {o!r} isn't [x, y] or [x, y, side]; the game drops it.", rid)
            elif not opening_sides(r, o):
                add("warning", f"{label}: door {list(o[:2])} is not on its edge; the game drops it.", rid)
            elif len(o) > 2 and o[2] not in opening_sides(r, o[:2]):
                add("warning", f"{label}: door {list(o)}: the third value is the side it opens ({', '.join(SIDES)}) "
                               "and that cell isn't on that side, so the game opens every side it is on.", rid)
        doors = [o for o in r.get("openings") or [] if is_opening(o) and opening_sides(r, o)]
        if r.get("wall") and not doors and rid not in mods["entered"] and rid not in mods["openings"]:
            add("warning", f"Walled region {r['name']!r} has no door, so it is sealed.", rid)
        _region_1_0(scn, r, label, ids, people, add, resolved)
    _floors(regions, floor_rects, main, add)
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


HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _region_1_0(scn, r, label, ids, people, add, resolved=None):
    """A region's Anywhere RPG 1.0 fields: shape, liquid surface, door kind and colour, the theft flag, and the
    world generator's fields that a scenario can't use."""
    rid, walled = r.get("id"), bool(r.get("wall"))
    shp = r.get("shape")
    if shp is not None:
        word = shp.strip().lower() if isinstance(shp, str) else None
        if word == "natural":
            add("info", f"{label}: the game reads 'natural' as 'organic'.", rid)
        elif word != "organic":
            add("warning", f"{label}: shape {shp!r} isn't 'organic'; the game draws a rectangle.", rid)
        if word in ("natural", "organic") and (walled or "pocket" in r):
            add("info", f"{label}: walled regions and floors stay rectangular, so shape is ignored.", rid)
        elif word in ("natural", "organic") and min(r["size"]) < ORGANIC_MIN:
            add("info", f"{label} is too small to round off (it needs {ORGANIC_MIN} x {ORGANIC_MIN}); it stays a "
                        "rectangle.", rid)
    surf = r.get("surface")
    if surf is not None:
        if not (isinstance(surf, str) and surf.strip()):
            add("warning", f"{label}: surface must be the name of a liquid.", rid)
        elif walled or "pocket" in r:
            add("warning", f"{label}: walled regions and floors can't be a liquid; the game ignores surface here.", rid)
        else:
            norm = norm_surface(surf)
            if norm != surf:
                add("info", f"{label}: the game reads surface {surf!r} as {norm!r}.", rid)
            res = (resolved or {}).get(rid)
            if resolved is not None and res is None:
                add("warning", f"{label}: surface {norm!r} is ignored; unbounded.profile.media already has "
                               f"{MAX_MEDIA} entries and the game adds no more.", rid)
            elif res is not None:
                m = res["medium"]
                if res["added"]:
                    add("info", f"{label}: liquid {norm!r} isn't in the media list, so the game adds it as a new "
                                "deep liquid nobody can walk through.", rid)
                elif m.get("name") != norm:
                    add("info", f"{label}: the game reads liquid {norm!r} as {m.get('name')!r} (walk: {m.get('walk')}).",
                        rid)
                if res["kind"] == "river":
                    add("info", f"{label} is long and thin, so the game draws it as a river {min(r['size'])} cells "
                                "wide, not a pool.", rid)
    door = r.get("door")
    if door is not None:
        if not walled:
            add("info", f"{label}: door is ignored on a region without walls.", rid)
        elif door not in DOOR_KINDS + ["none"]:
            add("warning", f"{label}: door {door!r} isn't {', '.join(DOOR_KINDS)} or none.", rid)
    if r.get("doorColor") is not None and not (isinstance(r["doorColor"], str) and HEX.match(r["doorColor"])):
        add("warning", f"{label}: doorColor {r['doorColor']!r} isn't a colour like #8a5a2b.", rid)
    if "takingIsTheft" in r and not isinstance(r["takingIsTheft"], bool):
        add("warning", f"{label}: takingIsTheft must be true or false.", rid)
    p = r.get("pocket")
    if "pocket" in r and not isinstance(p, dict):
        add("warning", f"{label}: pocket must be {{anchor: <region id>, level: N}}; the game reads an ordinary region.",
            rid)
    if isinstance(p, dict):
        lvl = p.get("level")
        if not isinstance(lvl, int) or isinstance(lvl, bool) or lvl == 0:
            add("warning", f"{label}: a floor's level is a whole number other than 0 (1 is one up, -1 one down), "
                           f"not {lvl!r}.", rid)
        anchor = p.get("anchor")
        if anchor is None:
            add("info", f"{label} is a floor with no anchor, so it belongs to no building.", rid)
        elif anchor == rid or anchor not in ids:
            add("warning", f"{label}: its anchor {anchor!r} isn't another region.", rid)
    elif "level" in r or "anchor" in r:
        add("warning", f"{label}: level and anchor aren't read from a scenario; a floor is "
                       "pocket: {anchor: <region id>, level: N}. The game treats this as an ordinary region.", rid)
    if "floors" in r:
        add("warning", f"{label}: floors is a world-generation field the import ignores; make each floor a region "
                       "with pocket.", rid)
    if "keyHolders" in r:
        kh = r["keyHolders"]
        names = [kh] if isinstance(kh, str) else [n for n in kh if isinstance(n, str)] if isinstance(kh, list) else []
        unknown = [n for n in names if n not in people]
        add("warning", f"{label}: keyHolders is a world-generation field the import ignores. In a scenario, a lock is a "
                       "locked effect on the region's door objects, and a key is an item whose opens is the region's id"
            + (f"; {', '.join(map(repr, unknown))} {'is' if len(unknown) == 1 else 'are'} no character here either."
               if unknown else "."), rid)


def _floors(regions, floor_rects, main, add):
    """Floors are planes of their own: kept apart from the map and from each other."""
    name = {r["id"]: r.get("name") for r in regions}
    fl = list(floor_rects.items())
    for i, (a, ra) in enumerate(fl):
        if disjoint(ra, main) and gap(ra, main) == 0:
            add("warning", f"Floor {name[a]!r} touches the map; leave a gap (the game leaves {FLOOR_GAP} cells) so "
                           "nobody steps straight between them.", a)
        for b, rb in fl[i + 1:]:
            if contains(ra, rb) or contains(rb, ra):
                inner, outer = (b, a) if contains(ra, rb) else (a, b)
                add("warning", f"Floor {name[inner]!r} lies inside floor {name[outer]!r}; each floor is a plane of "
                               "its own.", a, b)
            elif disjoint(ra, rb) and gap(ra, rb) == 0:
                add("warning", f"Floors {name[a]!r} and {name[b]!r} touch; leave a gap so nobody steps straight "
                               "between them.", a, b)


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
    npcs, _key, legacy = npc_templates(scn)
    for t in scn.get("objectTemplates", []) + npcs:
        label = f"Template {t.get('name')!r}"
        for lid in t.get("lootPoolIds", []):
            if lid not in items:
                add("error", f"{label}: loot {lid} is not an item template.", t.get("id"))
        if "money" in t and not (isinstance(t["money"], (int, float)) and 0 <= t["money"] <= 5):
            add("error", f"{label}: money is a tier from 0 to 5, not {t['money']!r}.", t.get("id"))
        for eff in t.get("startingEffects", []):
            for es in eff.get("endState", []):
                if es.get("type") in ("spawnEntity", "replaceSelfWith") and es.get("templateId")                         and es["templateId"] not in objs:
                    add("error", f"{label}: effect {eff.get('desc')!r} spawns an object template that doesn't exist.",
                        t.get("id"))
    for t in scn.get("objectTemplates", []):
        label = f"Object type {t.get('name')!r}"
        if "vehicle" in t and t["vehicle"] not in VEHICLES:
            add("warning", f"{label}: vehicle {t['vehicle']!r} isn't drive or ride.", t.get("id"))
        if t.get("sheet") and t["sheet"] not in VEHICLE_SHEETS:
            add("warning", f"{label}: sheet {t['sheet']!r} isn't a built-in vehicle sheet "
                           f"({', '.join(sorted(VEHICLE_SHEETS))}); the game draws its own image.", t.get("id"))
        if t.get("door") and t["door"] not in DOOR_KINDS:
            add("warning", f"{label}: door {t['door']!r} isn't {', '.join(DOOR_KINDS)}.", t.get("id"))
        if "takingIsTheft" in t and not isinstance(t["takingIsTheft"], bool):
            add("warning", f"{label}: takingIsTheft must be true or false.", t.get("id"))
    for t in scn.get("itemTemplates", []):
        if "opens" in t and t["opens"] not in region_ids:
            add("warning", f"Item {t.get('name')!r} is a key to {t['opens']!r}, which is no region.", t.get("id"))
    for t in npcs:
        label = f"{'Hostile' if legacy else 'NPC'} type {t.get('name')!r}"
        stance = template_stance(t, legacy)
        homes = template_homes(t)
        if legacy and not homes:
            add("error", f"{label}: its home region doesn't exist.", t.get("id"))
        for rid, _count in homes:
            r = region_ids.get(rid)
            if not r:
                add("error", f"{label}: its home region {rid!r} doesn't exist.", t.get("id"))
            elif stance == "hostile" and not r.get("hostile"):
                add("warning", f"{label} lives in {r['name']!r}, which isn't marked hostile.", t.get("id"), r["id"])
        if t.get("stance") is not None and t["stance"] not in TEMPLATE_STANCES:
            add("warning", f"{label}: stance {t['stance']!r} isn't {', '.join(sorted(TEMPLATE_STANCES))}.", t.get("id"))
        _sprite(t, label, "error", add)
    # containers that all start empty: the hand-authored version of a world whose containers drew
    # no loot. Storage-tagged or pool-carrying object templates with placements, but no entity
    # anywhere carries an inventory and no template ships money. A hand-made world may want empty
    # containers, so it is a note, and only once a few of them are placed.
    ents = [e for e in scn.get("entities", []) if isinstance(e, dict)]
    tpl = {t.get("id"): t for t in scn.get("objectTemplates", []) if isinstance(t, dict)}
    boxes, tids = 0, set()
    for e in ents:
        if e.get("type") != "object":
            continue
        t = tpl.get(e.get("templateId")) or {}
        if t.get("lootPoolIds") or "storage" in (t.get("tags") or []):
            boxes += 1
            if t.get("id"):
                tids.add(t["id"])
    stocked = any(e.get("inventory") for e in ents)
    moneyed = any("money" in t for t in list(tpl.values()) + list(npcs))
    if boxes >= 3 and not stocked and not moneyed:
        add("info", "This scenario's containers all start empty.", *sorted(tids))


def _sprite(o, label, level, add):
    a = o.get("animationId")
    if a in ANIMATION_ALIASES:
        add("info", f"{label}: sprite {a!r} was renamed {ANIMATION_ALIASES[a]!r} in 1.0; the import switches it.",
            o.get("id"))
    elif a not in ANIMATIONS:
        add(level, f"{label}: unknown sprite {a!r}" + (" (the game uses casual-man/woman)." if level == "warning"
                                                        else "."), o.get("id"))


def _entities(scn, by_name, media, add):
    items = {t.get("id") for t in scn.get("itemTemplates", [])}
    objs = {t.get("id") for t in scn.get("objectTemplates", [])}
    htpl = {t.get("id") for t in npc_templates(scn)[0]}
    region_ids = {r.get("id") for r in scn.get("regions", []) if isinstance(r, dict)}
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
        if e.get("templateId") and kind == "player":
            add("error", f"{label} has a templateId; the import refuses a player made from a template.", eid)
        elif e.get("templateId") and e["templateId"] not in htpl:
            add("error", f"{label}: its NPC type doesn't exist; the import refuses the file.", eid)
        if e.get("npcHome") is not None and e["npcHome"] not in region_ids:
            add("warning", f"{label}: npcHome {e['npcHome']!r} is no region.", eid)
        _sprite(e, label, "warning", add)
        if e.get("gender") not in ("male", "female"):
            add("error", f"{label}: gender must be male or female.", eid)
        if e.get("stance") is not None and e["stance"] not in STANCES:
            add("error", f"{label}: stance {e['stance']!r} is not {', '.join(sorted(STANCES))}.", eid)
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
    """The engine's movement rules (class `Yt` in 1.0's code): only objects with walkability <= 0 block a cell, and
    walls are thin lines on a walled region's outer border. A step across that border is blocked unless the cell on
    the inside is one of the region's openings on that side ([x, y] opens every side of the edge the cell is on,
    [x, y, side] only that side), so every cell of a room can be stood on and a door is a cell of the room itself.
    The map is one plane and each floor (a `pocket` region) is another; only cells on a plane exist."""

    def __init__(self, regions, solid, gw, gh, blocked=frozenset(), floors=()):
        self.solid, self.gw, self.gh, self.blocked = solid, gw, gh, blocked  # blocked: floor openings and liquids
        self.floors = list(floors)  # rects of the floor planes
        self.jumps = {}  # cell -> cells a portal there puts you on (set by portal_jumps)
        self.inside = {}  # cell -> ids of the walled regions it is in
        self.doors = {}  # region id -> {(x, y, side)}
        for r in regions:
            if r.get("wall"):
                self.doors[r["id"]] = {(o[0], o[1], side) for o in r.get("openings") or [] if is_opening(o)
                                       for side in opening_sides(r, o)}
                for c in cells(rect(r["position"], r["size"])):
                    self.inside.setdefault(c, set()).add(r["id"])

    def in_bounds(self, c):
        return (0 <= c[0] < self.gw and 0 <= c[1] < self.gh) or \
            any(f[0] <= c[0] <= f[2] and f[1] <= c[1] <= f[3] for f in self.floors)

    def walkable(self, c):
        return self.in_bounds(c) and c not in self.solid and c not in self.blocked

    def portal_jumps(self, portals):
        """Each portal end's cells -> where it puts you: anywhere in a region end, or a free cell beside a pad
        (an object or a cell) on the pad's own side of any wall."""
        def arrive(kind, cs):
            if kind == "region":
                return [c for c in cs if self.walkable(c)]
            pad = set(cs)
            home = self.inside.get(cs[0], set())
            ring = {(x + dx, y + dy) for (x, y) in cs for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - pad
            return [c for c in ring if self.walkable(c) and self.inside.get(c, set()) == home]

        for (_name, a, b, two) in portals:
            for (src, dst) in ((a, b), (b, a)) if two else ((a, b),):
                land = arrive(*dst)
                for c in src[1]:
                    self.jumps.setdefault(c, []).extend(land)

    def step(self, a, b):
        """Whether a person can step between neighbouring cells a and b (either way)."""
        ia, ib = self.inside.get(a, set()), self.inside.get(b, set())
        out_a = SIDE_OF[(b[0] - a[0], b[1] - a[1])]
        out_b = SIDE_OF[(a[0] - b[0], a[1] - b[1])]
        return all((a[0], a[1], out_a) in self.doors[r] for r in ia - ib) and \
            all((b[0], b[1], out_b) in self.doors[r] for r in ib - ia)

    def flood(self, start):
        seen, todo = {start}, [start]
        while todo:
            x, y = c = todo.pop()
            steps = [n for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)) if self.walkable(n) and self.step(c, n)]
            for n in steps + self.jumps.get(c, []):
                if n not in seen:
                    seen.add(n)
                    todo.append(n)
        return seen


SIDE_OF = {v: k for k, v in SIDES.items()}


def _map(scn, regions, by_name, add, mods):
    gw, gh = (scn.get("gridSize") or [0, 0])[:2]
    if not all(isinstance(v, (int, float)) for v in (gw, gh)):
        return
    gw, gh = int(gw), int(gh)
    tpl = {t.get("id"): t for t in scn.get("objectTemplates", [])}
    rects = {r["id"]: rect(r["position"], r["size"]) for r in regions}
    parent = region_tree(regions)
    floor_rects = {r["id"]: rects[r["id"]] for r in regions if is_floor(r)}

    ents = [e for e in scn.get("entities", []) if isinstance(e.get("pos"), list) and len(e["pos"]) == 2]
    objs = [e for e in ents if e.get("type") == "object"]
    probe = Walls([], {}, gw, gh, floors=floor_rects.values())
    solid, occupied = {}, {}  # cell -> object; solid = walkability 0 or less
    for e in objs:
        t = tpl.get(e.get("templateId")) or {}
        walk = t.get("walkability") or 0
        foot = footprint(e, tpl)  # a door object on a doorway is zero-width and covers no cell
        if foot and not all(probe.in_bounds(c) for c in foot):
            add("error", f"Object {e.get('name')!r} reaches outside the map.", e.get("id"))
        for c in foot:
            if walk <= 0:
                solid[c] = e
            if walk < 1:
                other = occupied.get(c)
                if other and other is not e:
                    add("warning", f"Objects {other.get('name')!r} and {e.get('name')!r} overlap at {list(c)}.",
                        other.get("id"), e.get("id"))
                occupied[c] = e
    sealed = {c for r in regions if r["id"] in mods["openings"] for c in cells(rects[r["id"]])}
    wet = liquid_cells(scn, regions)
    walls = Walls(regions, solid, gw, gh, sealed | wet, floor_rects.values())
    walls.portal_jumps(mods["portals"])

    for r in regions:
        if not r.get("wall"):
            continue
        for o in r.get("openings") or []:
            if not is_opening(o):
                continue
            c = (o[0], o[1])
            if c in solid:
                add("warning", f"Region {r['name']!r}: {solid[c].get('name')!r} blocks the door at {list(c)}.",
                    r["id"], solid[c].get("id"))
                continue
            out = [(c[0] + SIDES[s][0], c[1] + SIDES[s][1]) for s in opening_sides(r, o)]
            if out and not any(walls.walkable(n) and walls.step(c, n) for n in out):
                add("warning", f"Region {r['name']!r}: the door at {list(c)} leads nowhere (blocked outside, or a "
                               "neighbouring room has no matching door).", r["id"])

    people = [e for e in ents if e.get("type") in ("npc", "player")]
    for e in people:
        c = tuple(e["pos"])
        if not walls.in_bounds(c):
            add("error", f"{e.get('name')!r} stands outside the map.", e.get("id"))
        elif c in solid:
            add("error", f"{e.get('name')!r} starts inside {solid[c].get('name')!r}.", e.get("id"), solid[c].get("id"))
        elif c in wet:
            add("error", f"{e.get('name')!r} starts in a liquid nobody can walk through.", e.get("id"))

    player = next((e for e in ents if e.get("id") == scn.get("playerId")), None)
    if player and walls.walkable(tuple(player["pos"])):
        seen = walls.flood(tuple(player["pos"]))
        how = "on foot or through a portal" if mods["portals"] else "on foot"
        for e in people:
            if e is not player and walls.walkable(tuple(e["pos"])) and tuple(e["pos"]) not in seen:
                add("warning" if e.get("hostile") else "error",
                    f"{e.get('name')!r} can't be reached {how} from the player.", e.get("id"))
        for r in regions:
            if r.get("wall") and r["id"] not in mods["openings"] and not any(c in seen for c in cells(rects[r["id"]])):
                add("error", f"Room {r['name']!r} can't be reached {how} from the player.", r["id"])
        for e in objs:
            foot = footprint(e, tpl)
            if not foot:
                continue
            x0, y0 = min(c[0] for c in foot), min(c[1] for c in foot)
            x1, y1 = max(c[0] for c in foot), max(c[1] for c in foot)
            ring = [(x, y) for x in range(x0 - 1, x1 + 2) for y in range(y0 - 1, y1 + 2)
                    if not (x0 <= x <= x1 and y0 <= y <= y1)]
            if not any(c in seen for c in ring + foot):
                add("warning", f"Nobody can stand beside {e.get('name')!r}.", e.get("id"))

    _locks(scn, regions, rects, objs, tpl, add)
    _sleep_and_safety(scn, regions, by_name, rects, parent, objs, tpl, add, floor_rects)
    _crowds(scn, regions, by_name, rects, parent, add)


def _locks(scn, regions, rects, objs, tpl, add):
    """1.0 locks: a door object with a locked effect, opened by an item whose `opens` is the id of the region the
    door is in (or of a region around it). Warns about a locked door nobody carries a key for."""
    keys = {t.get("id"): t.get("opens") for t in scn.get("itemTemplates", []) if t.get("opens")}
    held = {keys[st.get("templateId")] for e in scn.get("entities", []) if e.get("type") in ("npc", "player")
            for st in e.get("inventory") or [] if isinstance(st, dict) and st.get("templateId") in keys}
    walled = [r for r in regions if r.get("wall")]

    def inside(q, c):
        return q[0] <= c[0] <= q[2] and q[1] <= c[1] <= q[3]

    for e in objs:
        t = tpl.get(e.get("templateId")) or {}
        if not t.get("door") or not is_locked(e):
            continue
        x, y = e["pos"]
        size = e.get("size") or t.get("size") or [1, 0]
        a, b = ((x - 1, y), (x, y)) if size[0] == 0 else ((x, y - 1), (x, y))
        rooms = [r for r in walled if inside(rects[r["id"]], a) != inside(rects[r["id"]], b)]
        opened = {r["id"] for r in walled if any(contains(rects[r["id"]], rects[q["id"]]) for q in rooms)}
        if rooms and not held & opened:
            add("warning", f"{e.get('name')!r} on {rooms[0]['name']!r} is locked and nobody carries its key.",
                e.get("id"), rooms[0]["id"])


def bed_capacity(r):
    """People one sleep object holds: 2 for a 2x2 or larger (a double bed), else 1 (a 1x2 or a 2x1 is a single
    bed, turned or not). The game itself has no capacity: a sleeper takes any bed spot nobody has claimed."""
    return 2 if min(r[2] - r[0], r[3] - r[1]) >= 1 else 1


def _sleep_and_safety(scn, regions, by_name, rects, parent, objs, tpl, add, floor_rects=None):
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
        n = sum(bed_capacity(b) for b in beds if contains(rects[rid], b))
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
            if plane_of(floor_rects or {}, rects[h]) != plane_of(floor_rects or {}, rects[rid]):
                continue  # on different planes
            d = gap(rects[h], rects[rid])
            if d < HOSTILE_BUFFER:
                near.append((d, rid))
        if near:
            near.sort()
            listed = ", ".join(f"{name[rid]!r} ({d})" for d, rid in near[:4])
            more = f" and {len(near) - 4} more" if len(near) > 4 else ""
            add("warning", f"Hostile {name[h]!r} is within {HOSTILE_BUFFER} cells of places peaceful NPCs use: "
                           f"{listed}{more}.", h, *[rid for _, rid in near])


def _covers(block, minute):
    s, e = _minutes(block["start"]), _minutes(block["end"])
    if s == e:
        return True
    return s <= minute < e if s < e else minute >= s or minute < e


def _crowds(scn, regions, by_name, rects, parent, add):
    """People by the hour, the way the GM sees a space: everyone in the same
    walled room, or on the same stretch of open ground. Sleepers are limited
    by the beds, so a full barracks is a note and not a warning."""
    walled = {r["id"] for r in regions if r.get("wall")}

    def space(rid):
        here = rid
        while here:
            if here in walled:
                return here
            here = parent.get(here)
        return rid

    awake, asleep = {}, {}
    for e in scn.get("entities", []):
        if e.get("type") != "npc":
            continue
        for b in e.get("schedule") or []:
            r = (by_name.get(b.get("location")) or [None])[0]
            if not r or not (HHMM.match(str(b.get("start", ""))) and HHMM.match(str(b.get("end", "")))):
                continue
            hours = (asleep if b.get("role") == "sleep" else awake).setdefault(
                space(r["id"]), [set() for _ in range(24)])
            for h in range(24):
                if _covers(b, h * 60):
                    hours[h].add(e.get("id"))

    def cap(rid):
        if rid in walled:
            return ROOM_CAP
        q = rects[rid]
        return ROOM_CAP * max(1, (q[2] - q[0] + 1) * (q[3] - q[1] + 1) // CIRCLE_CELLS)

    name = {r["id"]: r["name"] for r in regions}
    for rid, hours in awake.items():
        peak = max(range(24), key=lambda h: len(hours[h]))
        if len(hours[peak]) > cap(rid):
            add("warning", f"{len(hours[peak])} people are in {name[rid]!r} at {peak:02d}:00, more than the "
                           f"{cap(rid)} the GM can read comfortably there.", rid, *sorted(hours[peak]))
    for rid, hours in asleep.items():
        most = max(len(who) for who in hours)
        if most > cap(rid):
            add("info", f"{most} sleep in {name[rid]!r}: the GM reads them all when the player is in there.", rid)


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
