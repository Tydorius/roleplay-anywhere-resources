"""A simple day schedule from home and work.

Blocks are consecutive and cover 24 h (the last may wrap past midnight), each
with an exact region name and a role of work, leisure or sleep — the format
build_scenario.py accepts, and made for everyone at once so no room passes
ROOM_CAP. Sleep always goes to a room that has a forSleep object, because the
builder checks that: each person's assigned bedroom when the layout gave them
one (assign_sleep_rooms), else a bedded room of their home's household — the
nearest bedded building of the same zone. Work places like a smithy or a
chapel are for waking hours only.
"""

import random
import re

from .model import bed_capacity, is_spare_room

# who sleeps, works and relaxes when; the blocks of a shift cover the 24 hours
SHIFTS = {
    "day": {"sleep": ("22:00", "06:00"), "work": ("06:00", "18:00"),
            "leisure": [("18:00", "22:00")]},
    "evening": {"sleep": ("00:00", "08:00"), "work": ("14:00", "22:00"),
                "leisure": [("08:00", "14:00"), ("22:00", "00:00")]},
    "night": {"sleep": ("08:00", "16:00"), "work": ("22:00", "06:00"),
              "leisure": [("06:00", "08:00"), ("16:00", "22:00")]},
}

# the most people awake in one walled room at any hour. The game sets no limit;
# the GM reads everyone in a room in full each turn, and this keeps that short
ROOM_CAP = 8
CIRCLE_CELLS = 615     # one 14-cell circle: what the GM can see outdoors
EVENING_WEIGHTS = {"inn": 0.45, "home": 0.35, "outside": 0.2}

INN_WORD = re.compile(r"\b(inns?|taverns?|pubs?|bars?|alehouses?|saloons?|cantinas?|"
                      r"teahouses?)\b")
PASSAGE_WORD = re.compile(r"\b(corridors?|hallways?|landings?|stairs?|stairwells?|"
                          r"passages?)\b")


def room_capacity(world, room):
    """How many sleepers a room beds: the summed capacity of its sleep
    objects (a double bed counts two)."""
    return sum(bed_capacity(world.templates[t])
               for (t, _p) in room.furniture.placements
               if world.templates[t].for_sleep)


def room_doubles(world, room):
    """How many double beds (a sleep object sleeping two) a room holds."""
    return sum(1 for (t, _p) in room.furniture.placements
               if world.templates[t].for_sleep
               and bed_capacity(world.templates[t]) == 2)


def _is_spare(room, design):
    return is_spare_room(room.base_name, _room_purpose(design, room.base_name))


def _storey_rooms(layout):
    """A storey's rooms with the design each belongs to: its own, then those
    of its stamped unit copies."""
    rooms = [(r, layout.design) for r in layout.rooms]
    for uo in getattr(layout, "unit_outs", []) or []:
        rooms += [(r, uo.layout.design) for r in uo.layout.rooms]
    return rooms


def bedded_pools(world, building):
    """A building's bedded rooms as pools in fill order: upper storeys
    before the ground floor, private rooms before spare ones (a guest room
    or a ward, whose beds need no owner)."""
    ground = _storey_rooms(building.layout)
    upper = [item for f in building.floors for item in _storey_rooms(f.layout)]
    pools = []
    for want_spare in (False, True):
        for rooms in (upper, ground):
            pool = [r for (r, d) in rooms
                    if room_capacity(world, r) > 0 and _is_spare(r, d) == want_spare]
            if pool:
                pools.append(pool)
    return pools


def sleep_room(world, building_name):
    """The room in a building bedding the most sleepers (None when it has
    none). Guest rooms and wards come last so staff sleep in their own
    rooms. A home with upper storeys sleeps upstairs — its bedrooms
    moved up a storey — so the upper rooms come first."""
    def bedded(pool):
        best, best_n = None, 0
        for room in pool:
            n = room_capacity(world, room)
            if n > best_n:
                best, best_n = room, n
        return best

    for b in world.buildings:
        if b.layout.design.name != building_name:
            continue
        for pool in bedded_pools(world, b):
            room = bedded(pool)
            if room is not None:
                return room
    return None


def unit_copies(world):
    """Every stamped unit copy as name -> (building, copy). A home may name a
    copy as its region does ("Cabin 2") or under its building ("Grendel Flats
    Apartment 1")."""
    out = {}
    for b in world.buildings:
        for layout in [b.layout] + [f.layout for f in b.floors]:
            for uo in getattr(layout, "unit_outs", []) or []:
                out[uo.name] = (b, uo)
                out[f"{b.layout.design.name} {uo.name}"] = (b, uo)
    return out


def home_building(world, home):
    """The building a person's home names, directly or through a unit copy."""
    b = next((b for b in world.buildings if b.layout.design.name == home), None)
    return b if b is not None else unit_copies(world).get(home, (None, None))[0]


def assign_sleep_rooms(world, people, couples=None):
    """One sleep room per person, not one per building: each bedded room
    holds as many people as its beds sleep, so nobody shares a room past its
    capacity. Couples (``couples`` maps a home to its pairs) go first, both
    partners into one room with a double bed that then sleeps nobody else —
    the game cannot keep partners together any other way. Everyone else fills
    the remaining capacity in the sleep_room order (upper storeys first,
    private rooms before guest rooms and wards), a partly-filled room before
    an empty one so a household does not spread one person per room while
    another room has free beds. Beds nobody is assigned to simply stay free:
    an inn's or a hospital's spare beds have no owner. A person whose home
    names one unit copy sleeps in that copy. People whose home runs out of
    free beds get no entry — _ensure_beds and resolve_sleep fall back for
    them."""
    homes = {}
    for p in people:
        homes.setdefault(p.home, []).append(p)
    copies = unit_copies(world)
    for home, residents in homes.items():
        uo = copies.get(home, (None, None))[1]
        if uo is None:
            continue
        beds = [r for r in uo.layout.rooms if room_capacity(world, r) > 0]
        left = {r: room_capacity(world, r) for r in beds}
        for p in residents:
            room = next((r for r in beds if left[r] > 0), None)
            if room is not None:
                left[room] -= 1
                world.sleep_assign[p.name] = room
    for b in world.buildings:
        residents = homes.get(b.layout.design.name)
        if not residents:
            continue
        pools = bedded_pools(world, b)
        cap = {r: room_capacity(world, r) for pool in pools for r in pool}
        used = dict.fromkeys(cap, 0)
        done = set()
        for pair in (couples or {}).get(b.layout.design.name, []):
            room = None
            for pool in pools:
                room = next((r for r in pool
                             if used[r] + 2 <= cap[r] and room_doubles(world, r)), None)
                if room is not None:
                    break
            if room is None:
                continue   # no double bed yet: they fill in with everyone else
            world.sleep_assign[pair[0].name] = room
            world.sleep_assign[pair[1].name] = room
            used[room] = cap[room]   # the couple's bedroom sleeps nobody else
            done.update(p.name for p in pair)
        for p in residents:
            if p.name in done:
                continue
            for pool in pools:
                cands = [r for r in pool if used[r] < cap[r]]
                if not cands:
                    continue
                room = min(cands, key=lambda r: (used[r] == 0, -cap[r]))
                used[room] += 1
                world.sleep_assign[p.name] = room
                break


def zone_of(world, building_name):
    """The zone a building sits in, from its region parent."""
    r = world.regions_by_name.get(building_name)
    return r.parent if r is not None else None


def resolve_sleep(world, person):
    """The room the person sleeps in: their assigned room when the layout
    gave them one, else the nearest bedded building of the same household
    (their zone) — never a daytime work place. None when there is no bed to
    point at."""
    room = world.sleep_assign.get(person.name)
    if room is not None:
        return room
    home = home_building(world, person.home)
    zone = zone_of(world, home.layout.design.name) if home is not None else None
    best, best_gap = None, None
    for b in world.buildings:
        if b is home:
            continue
        bl = b.layout
        if zone is not None and zone_of(world, bl.design.name) != zone:
            continue
        cand = sleep_room(world, bl.design.name)
        if cand is None:
            continue
        if home is None:
            return cand
        gap = home.layout.rect.gap(bl.rect)
        if best is None or gap < best_gap:
            best, best_gap = cand, gap
    return best


def work_location(world, person):
    """A region name for the person's work: the building's entrance room, or the
    zone itself."""
    target = person.work or person.home
    for b in world.buildings:
        if b.layout.design.name == target:
            return b.layout.entrance_room.full_name
    if target in world.zones_by_name:
        return target
    return None


def _is_inn(building):
    """Whether a building is where people drink of an evening, by whole words:
    a cabin and a dining hall are not inns."""
    design = building.layout.design
    return bool(INN_WORD.search(f"{design.kind or ''} {design.purpose or ''}".lower()))


def _inn_room(building):
    """An inn's gathering room: its common room, else the entrance room."""
    design = building.layout.design
    for room in building.layout.rooms:
        if "common" in room.base_name.lower() \
                or "common" in _room_purpose(design, room.base_name).lower():
            return room.full_name
    return building.layout.entrance_room.full_name


def social_spot(world, person):
    """Last-resort evening spot, for someone with no home to start from: the
    world's inn if it has one, else the home zone, else the first zone."""
    for b in world.buildings:
        if _is_inn(b):
            return _inn_room(b)
    if person.home in world.zones_by_name:
        return person.home
    return next(iter(world.zones_by_name), None)


def _room_purpose(design, base_name):
    for r in design.rooms:
        if r.name == base_name:
            return r.purpose
    return ""


def _block_hours(start, end):
    """The clock hours a block covers (blocks start on the hour)."""
    s, e = int(start[:2]), int(end[:2])
    return [h % 24 for h in range(s, e if e > s else e + 24)]


def _shift(person):
    """The person's (sleep, work, leisure blocks) hours: day unless the plan
    gave them an evening or night shift."""
    return SHIFTS.get((person.extras or {}).get("shift"), SHIFTS["day"])


def room_cap(world, name):
    """How many people a region holds awake at once. The GM reads everyone
    within 14 cells in the same walled room in full, so a walled room gets
    ROOM_CAP and open ground ROOM_CAP per 14-cell circle."""
    r = world.regions_by_name.get(name)
    if r is None or r.wall:
        return ROOM_CAP
    return ROOM_CAP * max(1, (r.rect.w * r.rect.h) // CIRCLE_CELLS)


class _Load:
    """Who is where, hour by hour, while the schedules are made."""
    def __init__(self, world):
        self.world = world
        self.hours = {}

    def peak(self, name, hours):
        row = self.hours.get(name)
        return max((row[h] for h in hours), default=0) if row else 0

    def fits(self, name, hours):
        return self.peak(name, hours) < room_cap(self.world, name)

    def add(self, name, hours):
        row = self.hours.setdefault(name, [0] * 24)
        for h in hours:
            row[h] += 1


def _outdoors(world, building_name):
    """The open ground around a building: its nearest unwalled ancestor, or
    None in a void zone, which has no outside."""
    r = world.regions_by_name.get(building_name)
    seen = set()
    while r is not None and r.name not in seen:
        seen.add(r.name)
        if not r.wall and r.name != building_name:
            if r.name in world.void_zones or world.void_default:
                return None
            return r.name
        r = world.regions_by_name.get(r.parent) if r.parent else None
    return None


def _work_rooms(world, building):
    """Where a building's staff stand: the entrance room, then its other
    ground-floor rooms that aren't bedrooms or passages."""
    entrance = building.layout.entrance_room
    rooms = [r for r in building.layout.rooms
             if r is not entrance and room_capacity(world, r) == 0
             and not PASSAGE_WORD.search(r.base_name.lower())]
    return [entrance.full_name] + [r.full_name for r in rooms]


def _place_work(world, load, person, hours, sleep_loc):
    """The person's work place, the least crowded room of their workplace.
    A full workplace spills onto the ground outside, then home; a full stretch
    of open ground spills into its buildings, then home."""
    target = person.work or person.home
    building = next((b for b in world.buildings
                     if b.layout.design.name == target), None)
    if building is None:
        place = work_location(world, person) or sleep_loc
        sheds = [b.layout.entrance_room.full_name for b in world.buildings
                 if zone_of(world, b.layout.design.name) == place]
        return next((n for n in [place] + sheds + [sleep_loc] if load.fits(n, hours)),
                    place)
    rooms = _work_rooms(world, building)
    room = min(rooms, key=lambda n: load.peak(n, hours))
    if load.fits(room, hours):
        return room
    for spill in (_outdoors(world, target), sleep_loc):
        if spill is not None and load.fits(spill, hours):
            return spill
    return room


def _home_spot(world, person, sleep_loc):
    """Where someone spends time at home: the home's entrance room, or their
    own flat in a unit building, whose entrance is everyone's lobby."""
    home = home_building(world, person.home)
    if home is None or getattr(home.layout, "unit_outs", None):
        return sleep_loc
    return home.layout.entrance_room.full_name


def _nearest_inn(world, person):
    """The gathering room of the nearest inn in the person's own zone."""
    home = home_building(world, person.home)
    if home is None:
        return None
    zone = zone_of(world, home.layout.design.name)
    inns = [b for b in world.buildings if _is_inn(b)
            and zone_of(world, b.layout.design.name) == zone]
    if not inns:
        return None
    return _inn_room(min(inns, key=lambda b: (home.layout.rect.gap(b.layout.rect),
                                              b.layout.design.name)))


def _place_evening(world, load, person, hours, sleep_loc):
    """The person's evening place: one seeded choice among the nearest inn,
    home and the ground outside, the next choice when that one is full."""
    rng = random.Random(f"{world.seed}:evening:{person.name}")
    home = home_building(world, person.home)
    spots = [(_nearest_inn(world, person), EVENING_WEIGHTS["inn"]),
             (_home_spot(world, person, sleep_loc), EVENING_WEIGHTS["home"]),
             (_outdoors(world, home.layout.design.name) if home is not None else None,
              EVENING_WEIGHTS["outside"])]
    spots = [(n, w) for n, w in spots if n is not None]
    if not spots:
        return social_spot(world, person) or sleep_loc
    order = sorted(spots, key=lambda s: rng.random() ** (1 / s[1]), reverse=True)
    for name, _w in order:
        if load.fits(name, hours):
            return name
    return min((n for n, _w in spots), key=lambda n: load.peak(n, hours))


def plan_schedules(world, people):
    """{person name: (schedule blocks, start region)} for everyone at once, so
    no room passes its cap: everyone's bed first, then the work places, then
    the evenings, counting who is where at every hour. A bed sets its own
    limit, so a room may sleep more than the cap."""
    load = _Load(world)
    sleeps, works, leisures = {}, {}, {}
    for person in people:
        room = resolve_sleep(world, person)
        if room is not None:
            sleeps[person.name] = room.full_name
        else:
            # no bed to sleep in anywhere near (ensure_beds records the missing
            # bed): sleep at home rather than in a work place
            home = home_building(world, person.home)
            sleeps[person.name] = home.layout.entrance_room.full_name if home is not None \
                else social_spot(world, person)
        load.add(sleeps[person.name], _block_hours(*_shift(person)["sleep"]))
    for person in people:
        hours = _block_hours(*_shift(person)["work"])
        works[person.name] = _place_work(world, load, person, hours, sleeps[person.name])
        load.add(works[person.name], hours)
    for person in people:
        hours = [h for b in _shift(person)["leisure"] for h in _block_hours(*b)]
        leisures[person.name] = _place_evening(world, load, person, hours, sleeps[person.name])
        load.add(leisures[person.name], hours)
    out = {}
    for person in people:
        shift = _shift(person)
        blocks = [(shift["sleep"], sleeps[person.name], "sleep"),
                  (shift["work"], works[person.name], "work")]
        blocks += [(b, leisures[person.name], "leisure") for b in shift["leisure"]]
        # a block that wraps past midnight goes last, as the builder expects
        blocks.sort(key=lambda b: (b[0][1] <= b[0][0] and b[0][1] != "00:00", b[0][0]))
        schedule = [{"start": b[0][0], "end": b[0][1], "location": b[1], "role": b[2]}
                    for b in blocks]
        start_region = next((r["location"] for r in schedule
                             if r["start"] <= "08:00" < (r["end"] if r["end"] > r["start"]
                                                         else "24:00")), works[person.name])
        out[person.name] = (schedule, start_region)
    return out


def free_cell(world, region_name, taken=(), connected=None):
    """A free cell in a region for a character's start position: inside the
    wall ring for rooms, near the door, on no object and on no other character.
    When `connected` is given, only cells reachable from the roads qualify, so
    nobody starts sealed off behind filler."""
    region = world.regions_by_name.get(region_name)
    if region is None:
        return None
    rect = region.rect
    occupied = set(taken)
    # every object on the region's floor, whatever region it was filed
    # under (a field's fence posts sit on the farm's ground too)
    for o in world.objects:
        w, h = world.templates[o.template].size
        if o.pos[0] + w <= rect.x or o.pos[0] > rect.x1 or \
                o.pos[1] + h <= rect.y or o.pos[1] > rect.y1:
            continue
        occupied |= {(x, y) for x in range(o.pos[0], o.pos[0] + w)
                     for y in range(o.pos[1], o.pos[1] + h)}
    # the wall rings of walled regions inside this one (a zone's buildings
    # and rooms): a doorway there can still be another room's wall
    rings = set()
    for r in world.regions:
        if r is region or not r.wall:
            continue
        rr = r.rect
        if rr.x > rect.x1 or rr.x1 < rect.x or rr.y > rect.y1 or rr.y1 < rect.y:
            continue
        rings |= {c for c in rr.cells()
                  if c[0] in (rr.x, rr.x1) or c[1] in (rr.y, rr.y1)}
    anchor = region.entrance_door or (rect.x + rect.w // 2, rect.y + rect.h // 2)
    cands = sorted(rect.cells(), key=lambda c: (abs(c[0] - anchor[0]) + abs(c[1] - anchor[1]),
                                                c[1], c[0]))
    for c in cands:
        if region.wall and (c[0] in (rect.x, rect.x1) or c[1] in (rect.y, rect.y1)):
            continue  # the builder treats a walled region's ring as wall
        if c in rings:
            continue
        if c in occupied:
            continue
        if connected is not None and c not in connected:
            continue
        return c
    return None


def start_cell(world, region_name, taken=(), connected=None):
    """(cell, region name) for a character's start: a free cell in the
    region, else in a sibling room of the same building, else the nearest
    free reachable cell anywhere, with the innermost region that holds it.
    A crowded room never strands its people at a made-up spot whose
    room-relative position lands outside the room."""
    cell = free_cell(world, region_name, taken, connected)
    if cell is not None:
        return cell, region_name
    region = world.regions_by_name.get(region_name)
    if region is None:
        return None, region_name
    for sib in world.regions:
        if sib is region or not sib.wall or sib.parent is None or sib.parent != region.parent:
            continue
        cell = free_cell(world, sib.name, taken, connected)
        if cell is not None:
            return cell, sib.name
    if connected is None:
        return None, region_name
    occupied = set(taken)
    for o in world.objects:
        w, h = world.templates[o.template].size
        occupied |= {(x, y) for x in range(o.pos[0], o.pos[0] + w)
                     for y in range(o.pos[1], o.pos[1] + h)}
    cx, cy = region.rect.x + region.rect.w // 2, region.rect.y + region.rect.h // 2
    for c in sorted(connected - occupied,
                    key=lambda c: (abs(c[0] - cx) + abs(c[1] - cy), c[1], c[0])):
        holder = _innermost(world, c)
        if holder is not None:
            return c, holder.name
    return None, region_name


def _innermost(world, cell):
    """The smallest region whose floor holds the cell (a walled region's ring
    is wall, not floor), or None."""
    best = None
    for r in world.regions:
        rect = r.rect
        if not rect.contains_cell(cell):
            continue
        if r.wall and (cell[0] in (rect.x, rect.x1) or cell[1] in (rect.y, rect.y1)):
            continue
        if best is None or rect.w * rect.h < best.rect.w * best.rect.h:
            best = r
    return best
