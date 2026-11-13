"""Turn the laid-out plan into a builder spec: a JSON-serialisable dict in the
name-based format of the vendored build_scenario.py (guide section 10), written
out as both spec.json and spec.py (`SPEC = json.loads(...)`).
"""
import json
import re

from . import populations
from .layout_room import turned
from .sellers import sellers as sellers_of
from .vendor.scenario_checks import ANIMATIONS as KNOWN_ANIMATIONS

GROUND_MAP = {"grass": ("grass", "grass"), "dirt": ("dirt", "dirt"),
              "gravel": ("gravel", "gravel"), "stone": ("stone", "rock"),
              "wood": ("wood", "floorboards")}
OUT_AMBIENCE = {"day": "nature_outdoors", "night": "crickets"}

# A doorway's door kind from whole words of the design's kind/purpose and the
# room's name/purpose (a room's own match beats its building's): cells and
# cages take bars, cloth rooms a curtain, open-walled yards a gate. Whole
# words only — a cellar is not a cell, a stockroom not the stocks.
BARS_WORDS = re.compile(r"\b(cells?|jails?|cages?|kennels?|stocks|prisons?|gaols?)\b")
CURTAIN_WORDS = re.compile(r"\b(tents?|yurts?|stalls?|booths?|baths?|changing|back rooms?)\b")
GATE_WORDS = re.compile(r"\b(yards?|pens?|paddocks?|gardens?|compounds?|gatehouses?|gates?)\b")
DOOR_KINDS_BY_WORDS = (("bars", BARS_WORDS), ("curtain", CURTAIN_WORDS),
                       ("gate", GATE_WORDS))

# Rooms that ship locked, by whole words of the room's own name and purpose:
# strong rooms and holding cells only, so no ordinary home or shop door ever
# locks (a cellar is not a cell; a plain store holds nothing worth a key)
LOCKED_ROOM_WORDS = re.compile(
    r"\b(vaults?|strong\s?rooms?|treasur(?:y|ies)|safe\s?rooms?|armou?r(?:y|ies)|"
    r"cells?|jails?|gaols?|lock-?ups?|evidence\s+rooms?|cellar\s+stores?|"
    r"wine\s+cellars?)\b")
# Rooms that may stay locked with nobody holding a key: the key is meant to
# stay outside (CELL_WORDS names the same holding places as the lock list)
CELL_WORDS = re.compile(r"\b(cells?|jails?|gaols?|lock-?ups?)\b")
# ... but a "cell" in a chapel, temple or monastery is a monk's or keeper's
# bedroom, not a jail: when "cell" is the room's only lock word and the room or
# its building reads as religious, it stays unlocked
MONASTIC_WORDS = re.compile(
    r"\b(chapels?|church(?:es)?|temples?|shrines?|monaster(?:y|ies)|abbey|abbeys|"
    r"prior(?:y|ies)|convents?|nunner(?:y|ies)|friar(?:y|ies)|cloisters?|"
    r"monks?|nuns?|friars?|hermits?|sanctuar(?:y|ies))\b")
BARE_CELL_WORDS = re.compile(r"\bcells?\b")
# Who a locked room's key goes to first: the head of the place, by role words
HEAD_ROLE_WORDS = re.compile(
    r"\b(owners?|keepers?|captains?|wardens?|sheriffs?|jailers?|gaolers?|"
    r"priests?|priestesses?|abbots?|abbesses?|masters?|mistresses?|stewards?|"
    r"matrons?|reeves?|bailiffs?|constables?)\b")
# Inns, temples, halls and other public buildings take nothing: their rooms
# inherit takingIsTheft from the region above, which is no theft
PUBLIC_WORDS = re.compile(
    r"\b(inns?|taverns?|pubs?|bars?|alehouses?|saloons?|cantinas?|teahouses?|"
    r"temples?|chapels?|churches?|cathedrals?|shrines?|abbeys?|monasteries?|"
    r"halls?|guildhalls?)\b")
# Rooms hidden by their own name or purpose: their doorway onto the room they
# open through ships secret, known to the household
SECRET_ROOM_WORDS = re.compile(
    r"priest.?hole|hidden (room|chamber|stair)|secret (room|chamber|passage|stair)|"
    r"smuggl|bolt.?hole|escape (tunnel|passage)")
# Buildings that get one secret interior doorway of their own, now and then
# (a third of them at most): the strongholds and grand houses
# (whole words: "keep" must not catch an innkeeper's or a shopkeeper's house)
GRAND_BUILDING_WORDS = re.compile(
    r"\b(castles?|keeps?|manors?|palaces?|fortress(?:es)?|citadels?|ruins?|"
    r"ruined|abbeys?|monaster(?:y|ies)|towers?)\b")
# ... and the rooms such a doorway prefers to open into
SECRET_INTO_WORDS = re.compile(
    r"\b(stud(?:y|ies)|librar(?:y|ies)|chapels?|cellars?|stores?|storerooms?|"
    r"bed(?:rooms?|chambers?)|vaults?)\b")


def _door_kind(*texts):
    """The door kind whole words of the texts name, "door" when none does."""
    text = " ".join(t or "" for t in texts).lower()
    for kind, rx in DOOR_KINDS_BY_WORDS:
        if rx.search(text):
            return kind
    return "door"


def _door_kinds(world):
    """{walled region name: door kind} for the shipped scenario: every room
    from its own name and purpose first, then its design's kind and purpose;
    every other walled region (a compound's walls, a yard) from its own kind
    and name. The builder drops unknown region keys, so the kinds ride the
    spec by name and finish_scenario writes them onto the regions."""
    rooms = _loot_map(world)
    designs = {b.layout.design.name: b.layout.design for b in world.buildings}
    for b in world.buildings:
        for f in getattr(b, "floors", []) or []:
            designs[f.layout.design.name] = f.layout.design
    out = {}
    for r in world.regions:
        if not r.wall:
            continue
        if r.name in rooms:
            design, base = rooms[r.name]
            spec = next((s for s in design.rooms if s.name == base), None)
            own = _door_kind(base, getattr(spec, "purpose", "") if spec else "")
            out[r.name] = own if own != "door" else _door_kind(design.kind,
                                                               design.purpose)
            continue
        design = designs.get(r.name)
        if design is not None:
            out[r.name] = _door_kind(design.kind, design.purpose)
        else:
            out[r.name] = _door_kind(r.kind, r.name)
    return out


def _room_purpose(design, base_name):
    """A room base name's purpose in its design."""
    return next((r.purpose for r in design.rooms if r.name == base_name), "")


def _building_of_room(world):
    """{room full name: building} for every placed room — a building's own
    rooms, its stamped unit copies and its designed upper storeys."""
    out = {}
    for b in world.buildings:
        for layout in [b.layout] + [f.layout for f in getattr(b, "floors", []) or []]:
            for r in layout.rooms:
                out[r.full_name] = b
            for uo in getattr(layout, "unit_outs", []) or []:
                for r in uo.layout.rooms:
                    out[r.full_name] = b
    return out


def _key_holders(world, building):
    """The people a key to a room of this building goes to: whoever works
    there, else its residents, the head of the place first, two at most.
    The player only ever appears by their own work or home."""
    from .schedule import home_building
    name = building.layout.design.name
    pool = [c for c in world.characters if c.person.work == name]
    if not pool:
        pool = [c for c in world.characters
                if home_building(world, c.person.home) is building]
    heads = sorted(pool, key=lambda c: (0 if HEAD_ROLE_WORDS.search(
        (c.person.role or "").lower()) else 1, c.name))
    return [c.name for c in heads[:2]]


def _note(world, what, reason):
    """A soft problem for the run's notes. run_checks has already been through
    by the time the spec is written, so the note goes to the failures list and
    the written metrics both."""
    world.failures.append((what, reason))
    world.metrics.setdefault("objects", {}).setdefault("unplaced", []).append(
        {"what": what, "reason": reason})


def _seals_off(world, room, openings, blocked, jumps, starts):
    """Whether locking the room would cut the player off: with its doors
    blocked, the player's start cell or bed is no longer on the ground
    everyone walks. The player has no key coming, so the room must stay
    open instead."""
    from . import checks
    seen = checks.flood(world, starts - room.rect.cells(),
                        set(blocked) | set(openings.get(room.name) or ()), jumps)
    player = world.player
    if player is None:
        return False
    if tuple(player.pos) not in seen:
        return True
    bed = world.sleep_assign.get(player.person.name)
    return bed is not None and not (bed.rect.interior().cells() & seen)


def _locks(world):
    """[{room, holders}] for the rooms that ship locked: strong rooms and
    holding cells by their own name and purpose, their key with the people
    of the building (workers first, the head of the place preferred, two at
    most), never a room on the player's only way to their start cell or bed,
    and nobody-less rooms stay unlocked unless they are cells."""
    from . import checks
    rooms = _loot_map(world)
    buildings = _building_of_room(world)
    openings = checks.compute_openings(world)
    blocked, _doors = checks.walkability_grid(world, openings)
    jumps = checks.portal_jumps(world)
    starts = set(world.reserved)
    for road in world.roads:
        starts |= road.cells()
    out = []
    for name, (design, base) in sorted(rooms.items()):
        room = world.regions_by_name.get(name)
        building = buildings.get(name)
        if room is None or building is None:
            continue
        text = f"{base} {_room_purpose(design, base)}".lower()
        if not LOCKED_ROOM_WORDS.search(text):
            continue
        if BARE_CELL_WORDS.search(text) and \
                not LOCKED_ROOM_WORDS.search(BARE_CELL_WORDS.sub(" ", text)):
            d = building.layout.design
            if MONASTIC_WORDS.search(f"{text} {d.name} {d.kind} {d.purpose}".lower()):
                continue  # a sleeping cell, not a jail
        if not openings.get(name):
            continue      # no doors to lock, and no way in either
        if _seals_off(world, room, openings, blocked, jumps, starts):
            _note(world, f"room {name}",
                  "left unlocked: locking it would cut off the player's "
                  "start cell or bed")
            continue
        holders = _key_holders(world, building)
        if not holders and not CELL_WORDS.search(text):
            continue      # nobody to hold the key: only a cell stays locked
        out.append({"room": name, "holders": holders})
    return out


def _room_doorways(world, openings):
    """{room name: [(neighbour room name, doorway cells)]} for every doorway
    between two room regions — the rooms touch and both open their side of
    the wall between them, so it is a doorway in the built scenario too. A
    building's entrance or a side door to open ground never appears here:
    its other side is the building region, not a room."""
    rooms = [r for r in world.regions if r.is_room]
    out = {}
    for i, a in enumerate(rooms):
        for b in rooms[i + 1:]:
            cells = (openings.get(a.name) or set()) & (openings.get(b.name) or set())
            if not cells:
                continue
            out.setdefault(a.name, []).append((b.name, cells))
            out.setdefault(b.name, []).append((a.name, cells))
    return out


def _touches_portal(cells, jumps):
    """Whether a doorway sits on a stair or portal pad: hiding a door that
    opens straight onto a portal would send whoever steps through it flying."""
    pads = set(jumps or {})
    for (x, y) in cells:
        for c in ((x, y), (x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if c in pads:
                return True
    return False


def _opens_into(name_a, name_b, rooms):
    """Whether a doorway opens into a study, library, chapel, cellar, store,
    bedroom or vault — the rooms a secret door prefers (either side)."""
    for name in (name_a, name_b):
        entry = rooms.get(name)
        if entry is None:
            continue
        design, base = entry
        if SECRET_INTO_WORDS.search(
                f"{base} {_room_purpose(design, base)}".lower()):
            return True
    return False


def _secrets(world):
    """[{"between": [room, room], "knownBy": [names]}] for the doorways that
    ship secret. A room hidden by its own name or purpose — a priest hole, a
    smuggler's cache — gets the doorway into the smallest room it opens
    through (never the entrance, a stair or the player's only way to their
    start cell or bed, noted when it would be). A third of the castles,
    keeps, manors and their kin (rounding up) get one interior doorway of
    their own, chosen from the world's seed, into a study, library, chapel,
    cellar, store, bedroom or vault when one will do — a building that
    already got one by name gets no second. Whoever would hold the building's
    keys knows them; nobody else does."""
    import random
    from . import checks
    rooms = _loot_map(world)
    buildings = _building_of_room(world)
    openings = checks.compute_openings(world)
    blocked, _doors = checks.walkability_grid(world, openings)
    jumps = checks.portal_jumps(world)
    starts = set(world.reserved)
    for road in world.roads:
        starts |= road.cells()
    doorways = _room_doorways(world, openings)

    def region(name):
        return world.regions_by_name.get(name)

    out = []
    used = set()          # doorways already made secret, by their cells

    def hideable(cells):
        return not _touches_portal(cells, jumps) and frozenset(cells) not in used

    # ---- by name: the hidden rooms
    took_one = set()      # building names that already have a secret
    for name, (design, base) in sorted(rooms.items()):
        text = f"{base} {_room_purpose(design, base)}".lower()
        if not SECRET_ROOM_WORDS.search(text):
            continue
        room, building = region(name), buildings.get(name)
        if room is None or building is None:
            continue
        cands = [(other, cells) for (other, cells) in doorways.get(name) or ()
                 if hideable(cells)]
        if not cands:
            _note(world, f"room {name}",
                  "left an ordinary door: it opens onto no room a secret "
                  "door could hide (only the entrance, a stair or a doorway "
                  "already secret)")
            continue
        # the smallest room it opens through; area, then name, keeps it seeded
        other, cells = min(
            cands,
            key=lambda oc: (region(oc[0]).rect.w * region(oc[0]).rect.h, oc[0]))
        if _seals_off(world, room, {name: cells}, blocked, jumps, starts):
            _note(world, f"room {name}",
                  "left an ordinary door: a secret one would cut off the "
                  "player's start cell or bed")
            continue
        out.append({"between": [name, other],
                    "knownBy": _key_holders(world, building)})
        used.add(frozenset(cells))
        took_one.add(building.layout.design.name)

    # ---- by building: a third of the strongholds (rounding up), one secret
    # interior doorway each, chosen from the world's seed
    grand = sorted(
        b.layout.design.name for b in world.buildings
        if GRAND_BUILDING_WORDS.search(
            f"{b.layout.design.kind} {b.layout.design.name} "
            f"{b.layout.design.purpose}".lower()))
    if not grand:
        return out
    forbidden = set()     # the start cell's and the bed's rooms are never touched
    if world.player is not None:
        forbidden.add(world.player.region)
        bed = world.sleep_assign.get(world.player.person.name)
        if bed is not None:
            forbidden.add(bed.full_name)
    rng = random.Random(f"{world.seed}|nativeSecrets")
    # what the starts reach with every door open: a hidden doorway may take no
    # room of its building out of that, so a wing behind it stays reachable too
    reached = checks.flood(world, starts, blocked, jumps)

    def rooms_reached(seen, building):
        return {n for n, b in buildings.items() if b is building
                and region(n) is not None
                and region(n).rect.interior().cells() & seen}
    pick_from = [n for n in grand if n not in took_one]
    rng.shuffle(pick_from)
    for bname in pick_from[: -(-len(grand) // 3)]:
        building = next(b for b in world.buildings
                        if b.layout.design.name == bname)
        before = rooms_reached(reached, building)
        pairs = []
        for name, nbrs in sorted(doorways.items()):
            if buildings.get(name) is not building or name in forbidden:
                continue
            for (other, cells) in nbrs:
                if name > other or buildings.get(other) is not building \
                        or other in forbidden or not hideable(cells):
                    continue
                # every room of the building the starts reached still is,
                # without the doorway: a secret door is a wall to whoever
                # doesn't know it, and a hidden bridge would strand a wing
                seen = checks.flood(world, starts, blocked | set(cells), jumps)
                if rooms_reached(seen, building) >= before:
                    pairs.append((name, other, cells))
        if not pairs:
            continue
        preferred = [p for p in pairs if _opens_into(p[0], p[1], rooms)]
        name, other, cells = rng.choice(sorted(preferred or pairs,
                                               key=lambda p: (p[0], p[1])))
        out.append({"between": [name, other],
                    "knownBy": _key_holders(world, building)})
        used.add(frozenset(cells))
    return out


def _theft_buildings(world):
    """The building regions where taking things is theft: every shop and
    every seller's workplace, and every home — but never an inn, tavern,
    temple, hall or other public building, whose rooms inherit instead."""
    from .schedule import home_building, is_inn
    from .sellers import is_shop, sellers

    seller_names = sellers(world)
    out = []
    for b in world.buildings:
        design = b.layout.design
        if is_inn(b) or PUBLIC_WORDS.search(
                f"{design.kind} {design.purpose}".lower()):
            continue
        if design.status == "home" or is_shop(b) or any(
                c.person.name in seller_names and c.person.work == design.name
                for c in world.characters) or any(
                home_building(world, c.person.home) is b
                for c in world.characters):
            out.append(design.name)
    return out


def _vehicles(world, plan, water):
    """{template name: 1.0 vehicle fields} for the catalogue's carts, wagons
    and bikes (vehicles wherever they stand) and its boats (only when one
    sits on or beside water — a boat high and dry is scenery). Every vehicle
    is theft to drive off unless all its placements stand in the player's
    own home."""
    from . import native
    home = world.player.person.home if world.player is not None else ""
    out = {}
    for t in plan.templates:
        fields = native.vehicle_fields(t.name)
        if not fields and native.is_boat(t.name) and \
                native.boat_on_water(world, t.name, water):
            fields = {"vehicle": "drive", "takingIsTheft": True}
        if not fields:
            continue
        poses = [o for o in world.objects if o.template == t.name]
        if home and poses and all(_in_building(world, o.region, home) for o in poses):
            fields = {k: v for k, v in fields.items() if k != "takingIsTheft"}
        out[t.name] = fields
    return out


def _in_building(world, region_name, home):
    """Whether a region is the home building itself or one of its rooms."""
    r = world.regions_by_name.get(region_name)
    return region_name == home or (r is not None and r.parent == home)


def _dry_spot(world, obj, region, deep, taken):
    """The nearest origin for the object inside its own region where it
    covers no deep water and no cell another object holds. A moved prop
    keeps its rot, so it tries its turned size."""
    from . import checks as checks_mod
    from . import native
    w, h = turned(world.templates[obj.template].size, getattr(obj, "rot", 0) or 0)
    cells = region.rect.cells()
    for (x, y) in sorted(cells, key=lambda c: (abs(c[0] - obj.pos[0])
                                               + abs(c[1] - obj.pos[1]), c)):
        foot = {(cx, cy) for cx in range(x, x + w) for cy in range(y, y + h)}
        if not foot <= cells:
            continue
        if foot & deep or foot & taken:
            continue
        if not all(checks_mod.on_a_plane(world, c) for c in foot):
            continue
        return [x, y]
    return None


def _clear_deep_water(world, water, vehicles):
    """Nothing the generator places on purpose may stand on deep water: a
    prop on a pond moves to the nearest dry free cell of its own region, and
    one with nowhere dry to go (filler scattered over a river zone) is
    dropped, noted. Vehicles (boats) may sit on it; furniture inside walls
    is written room-relative and rooms never ship water."""
    from . import native
    deep = native.deep_cells(world, water)
    if not deep:
        return
    floats = {name for name, fields in vehicles.items()
              if fields.get("vehicle")}
    taken = set()
    for o in world.objects:
        if o.template in world.templates:
            taken |= native.footprint(world, o)
    keep = []
    for o in world.objects:
        region = world.regions_by_name.get(o.region)
        if o.template not in world.templates or o.template in floats or \
                (region is not None and region.wall) or \
                not (native.footprint(world, o) & deep):
            keep.append(o)
            continue
        spot = _dry_spot(world, o, region, deep, taken) if region else None
        if spot is None:
            _note(world, f"{o.template} at {list(o.pos)}",
                  "dropped: it stands on deep water and no dry cell near it "
                  "is free")
            continue
        taken -= native.footprint(world, o)
        o.pos = tuple(spot)
        taken |= native.footprint(world, o)
        keep.append(o)
    world.objects = keep


def _nature(world, plan):
    """The 1.0 nature of the laid-out world — natural shapes, water surfaces
    and vehicles — as region names and template fields the builder cannot
    carry (it drops unknown region and template keys), applied onto the built
    scenario by finish_scenario. A natural region is drawn as a blob that
    covers only part of its rectangle, so when anything the generator means
    to place sits within 2 cells of its corners the region keeps its
    rectangle instead, noted. Props on deep water move out of it first, so
    the shapes are decided against where things end up."""
    from . import native
    zone_kinds = {z.name: z.kind for z in plan.zones}
    water = native.final_water(world, zone_kinds)
    vehicles = _vehicles(world, plan, water)
    _clear_deep_water(world, water, vehicles)
    placed = set()
    for o in world.objects:
        if o.template in world.templates:
            placed |= native.footprint(world, o)
    placed |= {tuple(c.pos) for c in world.characters}
    if world.player is not None:
        placed.add(tuple(world.player.pos))
    posts = [r for r in world.regions if r.kind == "post"]
    shapes = []
    for name in native.natural_regions(world, zone_kinds) \
            + native.organic_water_regions(world):
        region = world.regions_by_name.get(name)
        danger = native.corner_cells(region.rect)
        what = None
        if placed & danger:
            what = "something the generator placed"
        elif any(p.rect.cells() & danger for p in posts):
            what = "an NPC post"
        if what is not None:
            _note(world, f"region {name}",
                  f"natural shape dropped: {what} sits within 2 cells of "
                  f"its corner, where the drawn blob may leave no ground")
            continue
        shapes.append(name)
    return {"shape": shapes, "water": native.water_surfaces(world, water),
            "vehicles": vehicles}


def _population_members(world, pops, natural):
    """Each population member's start cell, as world cells of its home region:
    free (no object's turned footprint, no character, no other member),
    walkable and reachable from the roads, off the deep water (the
    reachability grid blocks it) and off the corner cells of the regions that
    ship a natural shape, where the drawn blob may leave no ground. A home
    with too few such cells ships fewer members, noted — the game tops the
    home up again one member a day. The cells ride each home as ``members``;
    finish_scenario writes them into the entities once the ids exist."""
    from . import checks as checks_mod
    from . import native, schedule
    openings = checks_mod.compute_openings(world)
    blocked, _doors = checks_mod.walkability_grid(world, openings)
    jumps = checks_mod.portal_jumps(world)
    starts = set()
    for road in world.roads:
        starts |= road.cells()
    connected = checks_mod.flood(world, starts, blocked, jumps)
    taken = {tuple(c.pos) for c in world.characters}
    if world.player is not None:
        taken.add(tuple(world.player.pos))
    for name in natural:
        region = world.regions_by_name.get(name)
        if region is not None:
            taken |= native.corner_cells(region.rect)
    for p in pops:
        for h in p.get("homes") or []:
            members = []
            for _ in range(h.get("count") or 0):
                cell = schedule.free_cell(world, h["region"], taken, connected)
                if cell is None:
                    _note(world, f"population {p.get('name')} in {h['region']}",
                          f"only {len(members)} of {h.get('count')} members start "
                          "in place: no free reachable cell was left; the game "
                          "adds the rest one a day")
                    break
                taken.add(cell)
                members.append([cell[0], cell[1]])
            h["members"] = members

# Role keywords -> 1.0 sprite: `base` names a -man/-woman pair or one id both
# genders share. Every id must exist in scenario_checks.ANIMATIONS; a base whose
# id doesn't falls back to casual-*. More specific entries come first, so
# "town guard" wins over "guard" and tavern staff over "maid".
ANIMATIONS = [
    (("innkeeper", "tavern keeper", "barkeep"), "innkeeper"),
    (("barmaid", "waiter", "waitress"), "waiter"),
    (("cook", "chef", "baker"), "chef"),
    (("butcher",), "butcher"),
    (("smith", "blacksmith"), "blacksmith"),
    (("farmer", "farmhand", "farm hand", "farm worker", "shepherd"), "farmer"),
    (("fisher", "fisherman", "fisherwoman"), "fisher"),
    (("hunter",), "hunter"),
    (("miner",), "miner"),
    (("pirate",), "pirate"),
    (("merchant", "shopkeeper", "trader", "peddler"), "merchant"),
    (("maid", "chambermaid", "servant", "butler"), "servant"),
    (("noble", "lord", "lady"), "noble"),
    (("king", "queen"), "royalty"),
    (("security guard",), "security-guard"),
    (("town guard", "watchman", "guard"), "town-guard"),
    (("soldier",), "soldier"),
    (("knight",), "knight"),
    (("archer",), "archer"),
    (("priest", "priestess", "clergyman", "clergywoman", "clergy"), "clergy"),
    (("cleric",), "cleric"),
    (("monk", "nun"), "monk"),
    (("healer",), "healer"),
    (("doctor",), "doctor"),
    (("nurse",), "nurse"),
    (("scholar",), "scholar"),
    (("professor",), "professor"),
    (("scientist",), "scientist"),
    (("student",), "student"),
    (("mage", "wizard", "witch", "warlock", "sorcerer", "sorceress"), "mage"),
    (("necromancer",), "necromancer"),
    (("druid",), "druid"),
    (("bard", "minstrel"), "bard"),
    (("jester",), "jester"),
    (("beggar",), "beggar"),
    (("prisoner",), "prisoner"),
    (("thief", "rogue"), "rogue"),
    (("assassin",), "assassin"),
    (("detective",), "detective"),
    (("police", "policeman", "policewoman"), "police"),
    (("officer",), "officer"),
    (("sailor", "captain"), "sailor"),
    (("mechanic",), "mechanic"),
    (("janitor",), "janitor"),
    (("office worker", "office"), "office"),
    (("hacker",), "hacker"),
    (("astronaut",), "astronaut"),
    (("firefighter",), "firefighter"),
    (("cowboy",), "cowboy"),
    (("samurai",), "samurai"),
    (("ninja",), "ninja"),
    (("viking",), "viking"),
    (("traveler", "traveller", "adventurer"), "adventurer"),
    (("peasant", "villager", "labourer", "laborer", "worker"), "peasant"),
    (("weaver",), "casual"),  # 1.0 has no weaver sheet; it stays on the casual pair
    (("child",), "child"),
    (("old",), "old"),
]


def _ground_pair(key):
    return GROUND_MAP.get(key, ("dirt", "dirt"))


def _loot_map(world):
    """{region full name: (design, room base name)} for every placed room —
    a building's own rooms, its stamped unit copies (ground and upper) and
    its designed upper storeys — so a placement's pool resolves through the
    furniture line, the room, the building and the template default."""
    out = {}

    def add(design, rooms):
        for room in rooms:
            out[room.full_name] = (design, room.base_name)

    for b in world.buildings:
        bl = b.layout
        add(bl.design, bl.rooms)
        if getattr(bl.design, "units", None):
            for uo in getattr(bl, "unit_outs", []) or []:
                add(bl.design.units.design, uo.layout.rooms)
        for f in getattr(b, "floors", []) or []:
            add(f.layout.design, f.layout.rooms)
            if getattr(f.layout.design, "units", None):
                for uo in getattr(f.layout, "unit_outs", []) or []:
                    add(f.layout.design.units.design, uo.layout.rooms)
    return out


def _placements(world, plan):
    """{template name: [entry per placement]} where an entry is the position
    list, or a dict {"pos", "inventory"} when the placement draws a starting
    inventory from its pool. The draw is seeded by the world seed and the
    placement's name, so the same seed reproduces it and copied units
    differ."""
    from . import loot as loot_mod

    rooms = _loot_map(world)
    items_by_name = {it.name: it for it in plan.items}
    setting = plan.extras.get("loot", "normal")
    out = {}
    for o in world.objects:
        region = world.regions_by_name.get(o.region)
        pos = o.pos
        if region is not None and region.wall:
            inset = 1
            pos = [o.region, pos[0] - region.rect.x - inset, pos[1] - region.rect.y - inset]
        else:
            pos = [pos[0], pos[1]]
        entries = out.setdefault(o.template, [])
        pool = plan.loot_pools.get(loot_mod.resolve_pool(
            rooms.get(o.region), o.template, plan.loot_pools, world.templates))
        inv = loot_mod.draw_inventory(
            pool, items_by_name,
            f"{world.seed}|{o.template}|{len(entries) + 1}", setting) if pool else []
        rot = getattr(o, "rot", 0) or 0
        if inv or rot:
            entry = {"pos": pos}
            if inv:
                entry["inventory"] = [[n, c] for (n, c) in inv]
            if rot:
                entry["rot"] = rot
            entries.append(entry)
        else:
            entries.append(pos)
    return out


def _grid_size(world):
    """The builder's grid: the play area and — when the floors extension
    laid storeys east of it — the ground to hold them, padded one cell past
    every edge a build-time door may open onto (the shipped scenario's
    gridSize is the play area alone; nativeFloors carries it, and the floors
    are planes outside it)."""
    if not getattr(world, "floors", None):
        return [world.grid[0], world.grid[1]]
    w = max([world.grid[0]] + [r.rect.x1 + 2 for r in world.regions])
    h = max([world.grid[1]] + [r.rect.y1 + 2 for r in world.regions])
    return [w, h]


def build_spec(world, plan):
    # the nature pass runs first: it moves props off deep water, and the
    # placements below must be written from where they end up
    nature = _nature(world, plan)
    builder_doors = {f.region_name: list(f.builder_door)
                     for f in getattr(world, "floors", []) or []
                     if f.builder_door is not None}
    regions = []
    for r in world.regions:
        out = {
            "name": r.name,
            "description": r.description or r.name,
            "ground": r.ground,
            "groundTexture": r.ground_texture,
            "position": [r.rect.x, r.rect.y],
            "size": [r.rect.w, r.rect.h],
            "ambience": r.ambience or ({"day": "quiet_indoor"} if r.wall else OUT_AMBIENCE),
        }
        if r.wall:
            out["wall"] = r.wall
            doors = [list(d) for d in sorted(r.doors)]
            if not doors and r.name in builder_doors:
                # the flat-map builder needs one way into every walled region;
                # on a sealed upper storey that door is a build-time fiction —
                # finish_scenario strips it, and the stairs are the real way in
                doors = [builder_doors[r.name]]
            out["doors"] = doors
        if getattr(r, "ground_color", None):
            out["groundColor"] = r.ground_color
        if getattr(r, "wall_color", None):
            out["wallColor"] = r.wall_color
        if getattr(r, "group", None):
            out["regionGroup"] = r.group
        regions.append(out)

    # object templates with placements; room positions are written room-relative
    by_template = _placements(world, plan)

    object_templates = []
    for t in plan.templates:
        spec_t = {
            "name": t.name,
            "size": list(t.size),
            # passableAtBuild: a void zone's slabs must let the builder's
            # reachability walk cross them; finish_scenario hardens them back
            # to 0 in the shipped scenario, where nothing may cross
            "walkability": 1.0 if t.extras.get("passableAtBuild") else t.walkability,
            "description": t.description or t.name,
            "physicalDescription": t.physicalDescription or t.name,
            "tags": t.tags or ["filler"],
            "heightM": t.extras.get("heightM", 1),
            "maxHp": t.extras.get("maxHp", 50),
        }
        if t.for_sleep:
            spec_t["forSleep"] = True
        if t.extras.get("craftStation"):
            spec_t["craftStation"] = True
        light = t.extras.get("light")
        if "lights" in getattr(world, "extensions", ()):
            from .extensions.lights import light_for
            light = light_for(t)
        if isinstance(light, (int, float)) and not isinstance(light, bool) and light > 0:
            spec_t["light"] = light
        if "money" in t.extras:
            spec_t["money"] = t.extras["money"]
        # the template's DEFAULT pool only (not the union of its placements'
        # pools): the game draws lootPoolIds again on later searches, and a
        # union would let one store's shelves spawn another's goods then —
        # the per-placement variety lives in the drawn starting inventories
        pool = plan.loot_pools.get(t.extras.get("lootPool", "") or "")
        if pool is not None:
            spec_t["lootPool"] = list(pool.items)
        if t.name in by_template:
            spec_t["placements"] = by_template[t.name]
        object_templates.append(spec_t)

    sellers = sellers_of(world)

    def character(c):
        ent = {
            "name": c.name,
            "gender": c.gender,
            "pos": _char_pos(world, c),
            "level": c.person.extras.get("level", 2),
            "animationId": animation_for(c),
            "description": c.person.description or c.name,
            "physicalDescription": physical_for(c),
            "voiceProfile": voice_for(c),
            "schedule": c.schedule,
        }
        if c.is_player:
            ent.pop("level")
        if c.person.extras.get("animationId"):
            ent["animationId"] = c.person.extras["animationId"]
        inventory = list(c.person.extras.get("inventory") or [])
        equipment = {}
        # plans saved before slot checks may name a slot the game lacks
        # ("weapon"): map it, or carry the item when there is no free slot
        from .phases import EQUIP_SLOTS, SLOT_ALIASES
        for slot, item in (c.person.extras.get("equipment") or {}).items():
            real = slot if slot in EQUIP_SLOTS else SLOT_ALIASES.get(str(slot).lower())
            if real is None or real in equipment:
                inventory.append([item, 1])
            else:
                equipment[real] = item
        if inventory:
            ent["inventory"] = inventory
        if equipment:
            ent["equipment"] = equipment
        if c.person.name in sellers:
            ent["merchant"] = {}
        return ent

    extras = plan.extras
    dg, dtex = getattr(world, "default_ground", None) or ("grass", "grass")
    default_tile = {"name": "Meadow" if dg == "grass" else dg.capitalize(),
                    "ground": dg, "groundTexture": dtex,
                    "ambience": OUT_AMBIENCE}
    if getattr(world, "void_default", False):
        # every zone is void: the map's own tile is the out-of-bounds void
        from .extensions.floors import BOUNDARY_COLOR
        default_tile = {"name": "Void", "ground": "stone",
                        "groundTexture": "rock", "groundColor": BOUNDARY_COLOR,
                        "ambience": OUT_AMBIENCE}
    # the calendar points at regions by name; a building the layout could not
    # place no longer exists, so its entries go with it (logged like other
    # dropped planned content)
    region_names = {r["name"] for r in regions}
    calendar = []
    for c in extras.get("calendar", []):
        if isinstance(c, dict) and c.get("location") not in region_names:
            world.metrics.setdefault("errors", {}).setdefault("dropped", []).append(
                {"what": f"calendar '{c.get('name')}'",
                 "reason": f"location '{c.get('location')}' did not make it onto "
                           "the map"})
        else:
            calendar.append(c)

    spec = {
        "name": plan.name,
        "folderName": plan.name.replace(" ", "-"),
        "seed": str(world.seed),
        "worldBackground": plan.worldBackground,
        "narrativeRules": extras.get("narrativeRules", []),
        "narrativeFlavor": extras.get("narrativeFlavor", "adaptive"),
        "difficulty": extras.get("difficulty", "medium"),
        "xpMultiplier": extras.get("xpMultiplier", 1),
        "gridSize": _grid_size(world),
        "defaultTile": default_tile,
        "weatherKinds": extras.get("weatherKinds", ["clear", "rain", "fog"]),
        # genre-neutral fallbacks: no copper pennies in a cyberpunk world, and
        # the game's rule is base 3 each plus exactly 10 points (a 25 total)
        "currency": extras.get("currency", {"name": "Coin",
                                            "description": "The common coin of the region.",
                                            "format": "5 coins"}),
        "startingCurrency": extras.get("startingCurrency", 100),
        "attributes": extras.get("attributes", {"strength": 5, "dexterity": 5, "intellect": 5,
                                                "perception": 5, "charisma": 5}),
        "skills": extras.get("skills", {}),
        "variables": extras.get("variables", []),
        "perkTrees": extras.get("perkTrees", []),
        "calendar": calendar,
        "quests": extras.get("quests", []),
        "regions": regions,
        "objectTemplates": object_templates,
        "itemTemplates": [
            {"name": it.name, "type": it.type, "quality": it.quality,
             "value": it.value, "description": it.description,
             "physicalDescription": it.physicalDescription}
            for it in plan.items
        ],
        "npcs": [character(c) for c in world.characters if not c.is_player],
        "player": character(world.player),
    }
    if getattr(world, "floors", None):
        # the builder ignores keys it does not know: it never reads
        # nativeFloors, and finish_scenario drives the pockets, the portal
        # links and the seal from it once the build has assigned the ids
        from .extensions import floors
        spec["nativeFloors"] = floors.native_floors(world)
    # the walled regions' door kinds, by name for the same reason: the build
    # drops unknown region keys, so finish_scenario writes the `door` fields
    # and hangs the door objects once the build has assigned the ids
    spec["nativeDoors"] = _door_kinds(world)
    # the same goes for the locked rooms (with their key holders) and the
    # buildings where taking is theft: applied onto the built regions by name
    spec["nativeLocks"] = {"locks": _locks(world),
                           "theft": _theft_buildings(world)}
    # ... and for the secret doorways (with who knows them), which only the
    # secret-passages extension hides: without it no door gets the effect
    # and no mod data is written
    spec["nativeSecrets"] = (_secrets(world)
                             if "secret-passages" in getattr(world, "extensions", ())
                             else [])
    # ... and for the natural shapes, water surfaces and vehicle fields
    spec["nativeNature"] = nature
    # ... and for the native populations (livestock, vermin, crowds, patrols):
    # one template per kind with its home regions by name, applied onto the
    # built scenario as the game's own npcTemplates once the ids exist — with
    # each member's start cell picked here, so the homes open fully stocked
    pops = populations.choose(world, plan)
    _population_members(world, pops, nature.get("shape") or [])
    spec["nativePopulations"] = pops
    # the stairs kept in ruined buildings, by entity name: the shipped-scenario
    # check accepts them though they link to no portal
    spec["nativeStairs"] = {"ruined": list(getattr(world, "ruined_stairs", []) or [])}
    arpg_mods = {}
    if "lights" in getattr(world, "extensions", ()):
        from .extensions import lights
        arpg_mods.update(lights.arpg_mods(world))
    if arpg_mods:
        spec["arpgMods"] = arpg_mods
    return spec


def _char_pos(world, c):
    region = world.regions_by_name.get(c.region)
    pos = c.pos
    if region is not None and region.wall:
        return [region.name, pos[0] - region.rect.x - 1, pos[1] - region.rect.y - 1]
    return [pos[0], pos[1]]


def _kind(c):
    return (c.person.extras or {}).get("kind")


def _gender_id(base, gender):
    """The pair id for a gender; anything but male takes the -woman sheet."""
    return f"{base}-man" if gender == "male" else f"{base}-woman"


def animation_for(c):
    if _kind(c) == "child":
        return "child"
    if _kind(c) == "elder":
        return _gender_id("old", c.gender)
    role = (c.person.role or "").lower()
    for keywords, base in ANIMATIONS:
        if any(re.search(rf"\b{re.escape(kw)}s?\b", role) for kw in keywords):
            animation = base if base in KNOWN_ANIMATIONS else _gender_id(base, c.gender)
            if animation in KNOWN_ANIMATIONS:
                return animation
            break  # a base with no 1.0 sheet falls back to casual, not to a later entry
    return _gender_id("casual", c.gender)


def physical_for(c):
    """The portrait prompt. A child's or an elder's own description rarely says
    how old they are, and the portraits came out as adults until it did."""
    text = c.person.physicalDescription or c.name
    if _kind(c) == "child":
        return f"A young child, under twelve years old, with a child's small round face. {text}"
    if _kind(c) == "elder":
        word = "man" if c.gender == "male" else "woman"
        return f"Very old {word}, about eighty, deeply wrinkled, white hair. {text}"
    return text


def voice_for(c):
    gender = "Male" if c.gender == "male" else "Female"
    if _kind(c) == "child":
        return {"gender": gender, "age": ["Child"], "pitch": ["Brighter"], "tags": []}
    old = _kind(c) == "elder" or (c.person.role or "").lower().startswith("old")
    return {"gender": gender, "age": ["Senior"] if old else ["Adult"], "pitch": ["Average"],
            "tags": []}


def write_spec(out_dir, spec):
    import os
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=1)
    payload = json.dumps(spec, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "spec.py"), "w", encoding="utf-8") as f:
        f.write('"""Builder spec generated by the worldgen layout pipeline."""\n')
        f.write("import json\n\n")
        f.write('SPEC = json.loads(r"""\n' + payload + '\n""")\n')
    return payload
