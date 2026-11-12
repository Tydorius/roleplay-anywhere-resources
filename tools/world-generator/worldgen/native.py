"""Anywhere RPG 1.0 door objects on a built scenario: a Python port of the
Scenario Editor's own doorway rules (world10.js), so the generator ships what
the game plays — a doorway with no door object is an open gap, and the game
adds no doors to imported scenarios. The lower half adds the 1.0 nature of a
laid-out world: which regions are water (and which of those deep), which get
a natural shape, and which object templates are vehicles.

Doorways come from openings on walled regions: an opening crossed from a cell
inside a walled region to the cell outside is a doorway only when every walled
region whose wall the crossing splits opens its side of it. A door object is
an object entity from one of the four door templates, sitting zero-wide on
the wall line; the doorway's room (the smallest region the wall splits) picks
the kind from its `door` field ("door" when missing, "none" leaves it open).
A locked door is a door object carrying the "locked" status effect; a key is
an item template whose `opens` names the region its doors belong to, held as
an inventory stack by whoever should open them.
Coordinates: [0,0] is the bottom-left cell, y grows north.
"""
import random
import re
import time

from .layout_room import object_cells, object_rect

DOOR_KINDS = ("door", "bars", "gate", "curtain")
DOOR_NAMES = {"door": "Door", "bars": "Barred door",
              "gate": "Gate", "curtain": "Curtain"}
# a side's step to the next cell
STEP = {"n": (0, 1), "e": (1, 0), "s": (0, -1), "w": (-1, 0)}


# ---------------------------------------------------------------- geometry

def _rect(region):
    x, y = region.get("position", (0, 0))
    w, h = region.get("size", (1, 1))
    return (x, y, x + w - 1, y + h - 1)


def _in_rect(r, x, y):
    return r[0] <= x <= r[2] and r[1] <= y <= r[3]


def _side_between(a, b):
    """The side pointing from cell a to the adjacent cell b."""
    if b[0] == a[0] + 1:
        return "e"
    if b[0] == a[0] - 1:
        return "w"
    if b[1] == a[1] + 1:
        return "n"
    return "s"


# ------------------------------------------------- openings and doorways

def opening_sides(region, o):
    """Which sides of the region's border the opening ``o`` (an ``[x, y]``
    cell) opens: nothing off the rectangle; the edge sides the cell sits on
    (a corner has two); just the entry's own third value when it has one and
    it is among them."""
    r = _rect(region)
    if not _in_rect(r, o[0], o[1]):
        return []
    sides = []
    if o[1] == r[3]:
        sides.append("n")
    if o[0] == r[2]:
        sides.append("e")
    if o[1] == r[1]:
        sides.append("s")
    if o[0] == r[0]:
        sides.append("w")
    return [o[2]] if len(o) > 2 and o[2] in sides else sides


def opens(region, cell, side):
    """Whether the region has an opening at ``cell`` that opens ``side``."""
    for g in region.get("openings") or []:
        if g[0] == cell[0] and g[1] == cell[1] \
                and side in opening_sides(region, g):
            return True
    return False


def doorways(scn):
    """Every doorway in the scenario, as the game works it out: an opening on
    a walled region's border, crossed from a cell inside it to the cell
    outside, where every walled region holding exactly one of the two cells
    opens its side of the crossing (a door in one wall but not the other is
    no doorway). Entries are ``{"cell", "out", "room", "key"}``: cell is the
    one inside the room, room is the smallest region the wall splits (the
    first wins a tie), and the key is ``"<x>,<y>,x|y"`` from the lower cell
    and the crossing's axis."""
    walled = [r for r in scn.get("regions", []) if r.get("wall")]
    out, seen = [], set()
    for o in walled:
        for g in o.get("openings") or []:
            for side in opening_sides(o, g):
                cell = (g[0], g[1])
                beyond = (cell[0] + STEP[side][0], cell[1] + STEP[side][1])
                r = _rect(o)
                if not _in_rect(r, *cell) or _in_rect(r, *beyond):
                    continue
                lo = cell if (cell < beyond) else beyond
                axis = "x" if cell[0] != beyond[0] else "y"
                key = f"{lo[0]},{lo[1]},{axis}"
                if key in seen:
                    continue
                split = [w for w in walled
                         if _in_rect(_rect(w), *cell)
                         != _in_rect(_rect(w), *beyond)]
                crossed = True
                for w in split:
                    inside = _in_rect(_rect(w), *cell)
                    c, other = (cell, beyond) if inside else (beyond, cell)
                    if not opens(w, c, _side_between(c, other)):
                        crossed = False
                        break
                if not crossed:
                    continue
                seen.add(key)
                room = split[0]

                def area(w):
                    sw, sh = w.get("size") or (1, 1)
                    return sw * sh

                for w in split[1:]:
                    if area(w) < area(room):
                        room = w
                inside = _in_rect(_rect(room), *cell)
                out.append({"cell": cell if inside else beyond,
                            "out": beyond if inside else cell,
                            "room": room, "key": key})
    return out


# ---------------------------------------------------------------- door objects

def is_door(scn, e):
    """Whether e is an object entity placed from one of the door templates."""
    if not e or e.get("type") != "object":
        return False
    t = next((t for t in scn.get("objectTemplates") or []
              if t.get("id") == e.get("templateId")), None)
    return t is not None and t.get("door") in DOOR_KINDS


def door_cells(e):
    """The two cells a door object separates (one apart in x or y), lower
    one first."""
    pos = e["pos"]
    if (e.get("size") or [1, 0])[0] == 0:
        return [(pos[0] - 1, pos[1]), (pos[0], pos[1])]
    return [(pos[0], pos[1] - 1), (pos[0], pos[1])]


def door_key_of(e):
    """The doorway key of a door object: "<x>,<y>,x|y" from its lower cell
    and crossing axis."""
    a, b = door_cells(e)
    return f"{a[0]},{a[1]},{'x' if a[0] != b[0] else 'y'}"


def doors_by_key(scn):
    """The scenario's door objects, keyed by the doorway they sit on."""
    m = {}
    for e in scn.get("entities") or []:
        if is_door(scn, e):
            m.setdefault(door_key_of(e), []).append(e)
    return m


def door_counts(scn):
    """How many door objects of each kind the scenario carries (kinds with
    none left out)."""
    tpl = {t.get("id"): t for t in scn.get("objectTemplates") or []}
    out = {}
    for e in scn.get("entities") or []:
        t = tpl.get(e.get("templateId")) or {}
        if e.get("type") == "object" and t.get("door") in DOOR_KINDS:
            out[t["door"]] = out.get(t["door"], 0) + 1
    return out


def door_placement(dw):
    """Where a door object sits on a doorway: on the wall line, zero-wide
    along it (``rot`` 1 with size ``[0, 1]`` when the crossing runs along x)."""
    cell, out = dw["cell"], dw["out"]
    rot = 1 if cell[0] != out[0] else 0
    return {"pos": [max(cell[0], out[0]), max(cell[1], out[1])],
            "rot": rot, "size": [0, 1] if rot else [1, 0]}


# ---------------------------------------------------------------- ids and names

_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def _b36(n):
    s = ""
    while True:
        n, r = divmod(n, 36)
        s = _B36[r] + s
        if n == 0:
            return s


class Ids:
    """The vendored builder's id shape, ``<prefix>_<base36 ms>_<base36
    counter>_<rand>``, with each id kept unique against the scenario."""

    def __init__(self, scn):
        self.taken = {e.get("id") for e in scn.get("entities") or []}
        self.taken |= {t.get("id") for t in scn.get("objectTemplates") or []}
        self.rng = random.Random(str(scn.get("name") or "worldgen-doors"))
        self.stamp = _b36(int(time.time() * 1000))
        self.n = 10

    def __call__(self, prefix):
        while True:
            self.n += 1
            rand = "".join(self.rng.choice(_B36) for _ in range(4))
            i = f"{prefix}_{self.stamp}_{_b36(self.n)}_{rand}"
            if i not in self.taken:
                self.taken.add(i)
                return i


def next_name(base, names):
    """``base N`` with the next number not used by any name in ``names``
    (a bare ``base`` counts as 1)."""
    n = 0
    pat = re.compile(r"\A" + re.escape(base) + r" ([0-9]+)\Z")
    for nm in names:
        m = pat.match(nm) if isinstance(nm, str) else None
        if m:
            n = max(n, int(m.group(1)))
        if nm == base:
            n = max(n, 1)
    return f"{base} {n + 1}"


# ---------------------------------------------------------------- hanging

def door_template(scn, kind, ids):
    """The kind's one door template (by kind and English name), created on
    first use."""
    name = DOOR_NAMES[kind]
    t = next((t for t in scn.get("objectTemplates") or []
              if t.get("door") == kind and t.get("name") == name), None)
    if t is not None:
        return t
    t = {"id": ids("otpl"), "name": name, "size": [1, 0], "walkability": 1,
         "door": kind, "heightM": 2.1, "maxHp": 60}
    scn.setdefault("objectTemplates", []).append(t)
    return t


def hang_door(scn, dw, kind, ids):
    """Hang a door object of ``kind`` on doorway ``dw``, named after its
    template ("Door 2")."""
    tpl = door_template(scn, kind, ids)
    place = door_placement(dw)
    e = {"id": ids("obj"), "type": "object",
         "name": next_name(tpl["name"],
                           [o.get("name") for o in scn.get("entities") or []]),
         "pos": place["pos"], "size": place["size"], "hp": 60, "maxHp": 60,
         "inventory": [], "statusEffects": [], "templateId": tpl["id"]}
    if place["rot"]:
        e["rot"] = place["rot"]
    scn.setdefault("entities", []).append(e)
    return e


def hang_doors(scn):
    """Hang a door object on every doorway without one, of the doorway's
    room's own kind ("door" by default, "none" left open), and return how
    many were hung."""
    have = doors_by_key(scn)
    ids = Ids(scn)
    hung = 0
    for dw in doorways(scn):
        kind = dw["room"].get("door") or "door"
        if kind == "none" or have.get(dw["key"]):
            continue
        hang_door(scn, dw, kind, ids)
        hung += 1
    return hung


# ---------------------------------------------------------------- locks and keys

def region_doors(scn, region):
    """A region's doors: the door objects whose two cells its wall splits
    (exactly one of them inside it)."""
    r = _rect(region)
    return [e for e in scn.get("entities") or []
            if is_door(scn, e)
            and sum(1 for c in door_cells(e) if _in_rect(r, *c)) == 1]


def is_lock(fx):
    """Whether a status effect is a lock: any whose mechanics hold a
    "locked" entry."""
    return bool(fx and isinstance(fx.get("def"), dict)
                and isinstance(fx["def"].get("mechanics"), list)
                and any(m and m.get("type") == "locked"
                        for m in fx["def"]["mechanics"] if isinstance(m, dict)))


def is_locked(e):
    return any(is_lock(fx) for fx in e.get("statusEffects") or [])


def region_locked(scn, region):
    """True when a region has doors and every one of them is locked."""
    doors = region_doors(scn, region)
    return bool(doors) and all(is_locked(d) for d in doors)


def set_locked(scn, region, locked, ids):
    """Lock or unlock every door of a region; doors already in the wanted
    state stay as they are. Returns ``{"count": doors changed}`` or
    ``{"error"}`` when the region has no doors."""
    doors = region_doors(scn, region)
    if not doors:
        return {"error": f'{region.get("name")} has no doors to lock; '
                         "hang doors first"}
    count = 0
    for d in doors:
        if locked and not is_locked(d):
            d.setdefault("statusEffects", []).append({
                "id": ids("se"),
                "def": {"desc": "locked", "emoji": "🔒", "type": "constant",
                        "mechanics": [{"type": "locked"}]},
                "appliedAt": 28800})
            count += 1
        elif not locked and is_locked(d):
            d["statusEffects"] = [fx for fx in d.get("statusEffects") or []
                                  if not is_lock(fx)]
            count += 1
    return {"count": count}


def keys_to(scn, region):
    """Every item template that opens the region."""
    return [t for t in scn.get("itemTemplates") or []
            if t.get("opens") == region.get("id")]


def key_template(scn, region, ids):
    """The region's key item template, created on first use."""
    t = next((t for t in scn.get("itemTemplates") or []
              if t.get("opens") == region.get("id")), None)
    if t is not None:
        return t
    t = {"id": ids("itpl"), "name": f'{region.get("name")} key',
         "description": "", "type": "misc", "quality": "common",
         "opens": region["id"]}
    scn.setdefault("itemTemplates", []).append(t)
    return t


def give_key(scn, region, person, ids):
    """Put the region's key in someone's inventory, unless they already hold
    one."""
    keys = {t["id"] for t in keys_to(scn, region)}
    if any(isinstance(s, dict) and s.get("templateId") in keys
           for s in person.get("inventory") or []):
        return
    tpl = key_template(scn, region, ids)
    person.setdefault("inventory", []).append(
        {"id": ids("it"), "templateId": tpl["id"], "count": 1})


# --------------------------------------------- nature, water and vehicles

# Open ground that reads as landscape rather than lots: whole words of the
# region's name (or of its zone's kind) name a green, grove, wood, meadow,
# field or garden. A shape "natural" region is drawn as an organic blob that
# covers at least 70% of its rectangle, so its corners may fall outside the
# drawn shape.
NATURAL_WORDS = frozenset(
    "green greens common commons grove groves copse copses wood woods woodland "
    "woodlands meadow meadows clearing clearings glade glades field fields "
    "pasture pastures paddock paddocks orchard orchards garden gardens pond "
    "ponds lake lakes marsh marshes".split())
# ... but never the paved or fenced shapes, which stay rectangles
NOT_NATURAL_WORDS = frozenset(
    "road roads street streets square squares plaza plazas yard yards".split())
NATURAL_REGION_KINDS = ("zone", "square", "field", "compound")

# carts and their kin the game should let the player drive; mounts are
# characters and stay as they are
CART_WORDS = re.compile(
    r"\b(carts?|wagons?|waggons?|carriages?|cabs?|cars?|trucks?|vans?|buggy|"
    r"buggies|bicycles?|bikes?|motorbikes?|motorcycles?)\b")
BIKE_WORDS = re.compile(r"\b(bicycles?|bikes?)\b")
# a boat drives only on water: beside a river or lake it is a vehicle,
# nowhere near one it is scenery
BOAT_WORDS = re.compile(
    r"\b(boats?|rowboats?|skiffs?|canoes?|punts?|rafts?|barges?|ferries?|"
    r"ferry)\b")
# ... but a vehicle word beside one of these names a part, a fixture or a
# picture of one, not something to drive: a bike rack, a wagon wheel, a
# carriage clock, a car park sign, a boat hook, a toy cart
NOT_VEHICLE_WORDS = re.compile(
    r"\b(racks?|wheels?|sheds?|parks?|parking|stands?|clocks?|signs?|"
    r"shelters?|lifts?|jacks?|parts?|tyres?|tires?|horns?|seats?|lamps?|"
    r"bells?|pumps?|hooks?|oars?|paddles?|models?|toys?|paintings?|"
    r"posters?|pictures?|wrecks?|wrecked|tracks?|rails?|repairs?|benches?)\b")


def _words(text):
    """The whole lowercase words of a name or kind."""
    return set(re.findall(r"[a-z]+", (text or "").lower()))


def is_water_region(world, region, zone_kinds=None):
    """Whether an unwalled region ships as water: water by name, or a zone
    whose class is water (a river, lake or shore zone — settlement and
    farmland words win over water ones, as in zone_class). Roads and paths
    are never water: a way across the water is a bridge, a region without a
    surface that the liquid flows under."""
    if region.wall or region.kind in ("road", "path"):
        return False
    from .model import (AGRICULTURAL_WORDS, SETTLEMENT_WORDS, WATER_WORDS)
    if _words(region.name) & set(WATER_WORDS):
        return True
    if region.kind == "zone":
        kind = _words((zone_kinds or {}).get(region.group or region.name, ""))
        if kind & set(WATER_WORDS) and not kind & set(SETTLEMENT_WORDS) \
                and not kind & set(AGRICULTURAL_WORDS):
            return True
    return False


def water_depth(region):
    """How the game's default media resolve a water region: a short side of
    3 cells or less is shallow water, waded at walk "slow"; anything deeper
    is deep water with walk "no", which nobody crosses."""
    return "shallow" if min(region.rect.w, region.rect.h) <= 3 else "deep"


def river_shape_p(region):
    """Whether the game draws the region as a meandering river of its short
    side's width: at least three times as long as wide, and at most 12 wide.
    Everything else is a pool."""
    w, h = region.rect.w, region.rect.h
    return max(w, h) >= 3 * min(w, h) and min(w, h) <= 12


def water_regions(world, zone_kinds=None):
    """{region name: 'deep' | 'shallow'} for every region that ships with a
    water surface, before any reachability drops."""
    out = {}
    for r in world.regions:
        if is_water_region(world, r, zone_kinds):
            out[r.name] = water_depth(r)
    return out


def wet_cells(world, water):
    """{region name: its wet cells} the way the game paints liquid: the
    region's rectangle minus the cells of regions nested inside it that carry
    no surface of their own — a bridge, a jetty or a walled yard over the
    water stays dry ground."""
    names = set(water)
    out = {}
    for name, _depth in water.items():
        r = world.regions_by_name.get(name)
        if r is None:
            continue
        cells = r.rect.cells()
        for d in world.regions:
            if d.name in names or d.name == name:
                continue
            if r.rect.contains_rect(d.rect):
                cells -= d.rect.cells()
        out[name] = cells
    return out


def deep_cells(world, water=None):
    """Every cell of deep water — blocked for reachability and for anything
    the generator places. Shallow water is waded, not blocked."""
    if water is None:
        water = final_water(world)
    out = set()
    for name, cells in wet_cells(world, water).items():
        if water[name] == "deep":
            out |= cells
    return out


def _must_reach_cells(world):
    """The cells the world's ways have to reach: room and building interiors,
    the cells before every entrance, compound courtyards and their parts,
    every character's cell and the player's start and bed."""
    from .model import SIDE_DX_DY
    need = set()
    for r in world.regions:
        if r.wall and r.is_room:
            need |= r.rect.interior().cells()
    for b in world.buildings:
        dx, dy = SIDE_DX_DY[b.layout.entrance_side]
        need.add((b.layout.entrance_door[0] + dx,
                  b.layout.entrance_door[1] + dy))
        need |= b.layout.rect.interior().cells()
    for comp in getattr(world, "compounds", None) or []:
        need |= comp.courtyard.interior().cells()
        for part in comp.parts:
            need |= part.layout.rect.interior().cells()
    for c in world.characters:
        need.add(tuple(c.pos))
    player = world.player
    if player is not None:
        need.add(tuple(player.pos))
        bed = (world.sleep_assign or {}).get(player.person.name)
        if bed is not None:
            need |= bed.rect.interior().cells()
    return need


def _unwalkable_drops(world, water):
    """Deep water regions that would cut the world's ways: with the region's
    cells blocked, some room interior, entrance approach, compound part,
    standing character or the player's start or bed could no longer be
    reached from the roads. Those regions keep no surface, the brief's own
    remedy for a world water would break."""
    from . import checks
    deep = sorted(n for n, d in water.items() if d == "deep")
    if not deep:
        return []
    wet = wet_cells(world, water)
    openings = checks.compute_openings(world)
    base, _doors = checks._base_grid(world, openings)
    jumps = checks.portal_jumps(world)
    starts = set(world.reserved)
    for road in world.roads:
        starts |= road.cells()
    reach = checks.flood(world, starts, base, jumps)
    need = _must_reach_cells(world)
    return [name for name in deep
            if (reach - checks.flood(world, starts, base | wet[name],
                                     jumps)) & need]


def final_water(world, zone_kinds=None, refresh=False):
    """{region name: depth} for the water that actually ships: every water
    region minus those whose deep cells would cut the world's ways. The zone
    kinds come from the world (set when its map is laid out) unless given, so
    the spec writer, the checks and the placement walks all see the same
    water; the answer is cached on the world until a refresh or a lookup with
    other zone kinds."""
    if zone_kinds is None:
        zone_kinds = getattr(world, "zone_kinds", None)
    cache = getattr(world, "_water_final", None)
    if cache is not None and not refresh and cache[0] == zone_kinds:
        return cache[1]
    water = water_regions(world, zone_kinds)
    drops = _unwalkable_drops(world, water)
    for name in drops:
        del water[name]
    world._water_final = (zone_kinds, water, drops)
    return water


def water_drops(world):
    """The water regions whose surface was dropped for reachability."""
    cache = getattr(world, "_water_final", None)
    return list(cache[2]) if cache else []


def water_metrics(world, water):
    """The water half of the run's metrics: each region's depth and how the
    game draws it (a river or a pool), plus the surfaces dropped to keep the
    world's ways walkable."""
    out = {"regions": [], "dropped": []}
    for name, depth in sorted(water.items()):
        r = world.regions_by_name.get(name)
        if r is None:
            continue
        out["regions"].append({"name": name, "depth": depth,
                               "draw": "river" if river_shape_p(r) else "pool"})
    for name in water_drops(world):
        out["dropped"].append({
            "name": name,
            "reason": "deep water here would cut the world's only ways, "
                      "so the region ships without its surface"})
    return out


def natural_regions(world, zone_kinds=None):
    """Names of the regions that ship with shape "natural": unwalled open
    ground named (or zoned) a green, grove, wood, meadow, field, garden or
    the like, both sides at least 5 — the game keeps the rectangle for
    anything smaller. Never roads, streets, squares, plazas, yards, anything
    walled or the built shapes."""
    kinds = _zone_word_kinds(zone_kinds)
    out = []
    for r in world.regions:
        if r.wall or r.kind not in NATURAL_REGION_KINDS:
            continue
        words = _words(r.name)
        natural = bool(words & NATURAL_WORDS)
        if not natural and r.kind == "zone":
            natural = bool(kinds.get(r.group or r.name, set()) & NATURAL_WORDS)
        if not natural or words & NOT_NATURAL_WORDS:
            continue
        if r.kind == "zone" and kinds.get(r.group or r.name,
                                          set()) & NOT_NATURAL_WORDS:
            continue
        if r.rect.w < 5 or r.rect.h < 5:
            continue
        out.append(r.name)
    return out


def _zone_word_kinds(zone_kinds):
    return {name: _words(kind) for name, kind in (zone_kinds or {}).items()}


def corner_cells(rect, reach=2):
    """The cells within `reach` of a rect's corners — where an organic blob
    that covers only part of its rectangle may leave ground outside the
    drawn shape. Nothing the generator means to place may sit there."""
    corners = ((rect.x, rect.y), (rect.x1, rect.y),
               (rect.x, rect.y1), (rect.x1, rect.y1))
    return {(x, y)
            for x in range(rect.x, rect.x1 + 1)
            for y in range(rect.y, rect.y1 + 1)
            if any(max(abs(x - cx), abs(y - cy)) <= reach
                   for cx, cy in corners)}


def vehicle_fields(name):
    """The 1.0 vehicle fields for a template the game should treat as a
    vehicle: carts, wagons, carriages, cars and the like drive; a bicycle
    also gets its built-in sheet. {} for everything else — mounts are
    characters, and boats need water beside them (see boat_on_water)."""
    text = name.lower()
    if NOT_VEHICLE_WORDS.search(text):
        return {}
    if BIKE_WORDS.search(text):
        return {"vehicle": "drive", "sheet": "bicycle", "takingIsTheft": True}
    if CART_WORDS.search(text):
        return {"vehicle": "drive", "takingIsTheft": True}
    return {}


def is_boat(name):
    """Whether the template's name is a boat (not a boat hook, an oar or a
    model of one)."""
    text = name.lower()
    return bool(BOAT_WORDS.search(text)) and not NOT_VEHICLE_WORDS.search(text)


def boat_on_water(world, template, water):
    """Whether any placement of the boat template sits on or beside the
    water: a boat nowhere near water is scenery."""
    rects = [world.regions_by_name[n].rect for n in water
             if n in world.regions_by_name]
    if not rects:
        return False
    for o in world.objects:
        if o.template != template:
            continue
        r = object_rect(world, o)
        if any(r.gap(w) <= 1 for w in rects):
            return True
    return False


def footprint(world, obj):
    """The cells an object covers, at its turned size (the walkability
    walk uses the same view)."""
    return object_cells(world, obj)
