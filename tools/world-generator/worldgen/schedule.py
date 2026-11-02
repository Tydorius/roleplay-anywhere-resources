"""A simple day schedule from home and work.

Blocks are consecutive and cover 24 h (the last may wrap past midnight), each
with an exact region name and a role of work, leisure or sleep — the format
build_scenario.py accepts. Sleep always goes to a room that has a forSleep
object, because the builder checks that: a room of the person's home when it
has one, else the nearest bedded building of the same household (the same
zone). Work places like a smithy or a chapel are for daytime only.
"""

SLEEP = ("22:00", "06:00")
WORK = ("06:00", "18:00")
LEISURE = ("18:00", "22:00")


def sleep_room(world, building_name):
    """The room in a building with the most beds (None when it has none).
    Rooms whose purpose mentions guests are skipped so staff sleep in their
    own rooms. A home with upper storeys sleeps upstairs — its bedrooms moved
    up a storey — so the upper rooms come first."""
    def bedded(pool):
        best, best_n = None, 0
        for room in pool:
            n = sum(1 for (t, _p) in room.furniture.placements
                    if world.templates[t].for_sleep)
            if n > best_n:
                best, best_n = room, n
        return best

    def guest(room, design):
        purpose = _room_purpose(design, room.base_name).lower()
        return "guest" in purpose or "paying" in purpose

    for b in world.buildings:
        if b.layout.design.name != building_name:
            continue
        ground = [(r, b.layout.design) for r in b.layout.rooms]
        upper = [(r, f.layout.design) for f in b.floors for r in f.layout.rooms]
        for pool in ([r for (r, d) in upper if not guest(r, d)],
                     [r for (r, d) in ground if not guest(r, d)],
                     [r for (r, _d) in upper],
                     [r for (r, _d) in ground]):
            room = bedded(pool)
            if room is not None:
                return room
    return None


def zone_of(world, building_name):
    """The zone a building sits in, from its region parent."""
    r = world.regions_by_name.get(building_name)
    return r.parent if r is not None else None


def resolve_sleep(world, person):
    """The room the person sleeps in: a bedded room of their home, else the
    nearest bedded building of the same household (their zone) — never a
    daytime work place. None when there is no bed to point at."""
    room = sleep_room(world, person.home)
    if room is not None:
        return room
    home = next((b for b in world.buildings
                 if b.layout.design.name == person.home), None)
    zone = zone_of(world, person.home) if home is not None else None
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


def social_spot(world, person):
    """Evening gathering spot: the inn's common room if the world has one, else
    the home building's entrance room, else the home zone."""
    for b in world.buildings:
        kind = (b.layout.design.kind or "") + " " + (b.layout.design.purpose or "")
        if "inn" in kind.lower() or "tavern" in kind.lower():
            for room in b.layout.rooms:
                if "common" in room.base_name.lower() or "common" in _room_purpose(b.layout.design, room.base_name).lower():
                    return room.full_name
            return b.layout.entrance_room.full_name
    home = person.home
    for b in world.buildings:
        if b.layout.design.name == home:
            return b.layout.entrance_room.full_name
    if home in world.zones_by_name:
        return home
    z = next(iter(world.zones_by_name), None)
    return z


def _room_purpose(design, base_name):
    for r in design.rooms:
        if r.name == base_name:
            return r.purpose
    return ""


def make_schedule(world, person):
    """(schedule blocks, start_pos_region) for one person."""
    room = resolve_sleep(world, person)
    if room is not None:
        sleep_loc = room.full_name
    else:
        # no bed to sleep in anywhere near (ensure_beds records the missing
        # bed): sleep at home rather than in a work place
        home = next((b for b in world.buildings
                     if b.layout.design.name == person.home), None)
        sleep_loc = home.layout.entrance_room.full_name if home is not None \
            else social_spot(world, person)
    work_loc = work_location(world, person) or sleep_loc
    leisure_loc = social_spot(world, person)
    schedule = [
        {"start": SLEEP[0], "end": SLEEP[1], "location": sleep_loc, "role": "sleep"},
        {"start": WORK[0], "end": WORK[1], "location": work_loc, "role": "work"},
        {"start": LEISURE[0], "end": LEISURE[1], "location": leisure_loc, "role": "leisure"},
    ]
    start_region = None
    for r in schedule:
        if r["start"] <= "08:00" < (r["end"] if r["end"] > r["start"] else "24:00"):
            start_region = r["location"]
            break
    return schedule, (start_region or work_loc)


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
    for o in world.objects:
        if o.region == region_name:
            w, h = world.templates[o.template].size
            occupied |= {(x, y) for x in range(o.pos[0], o.pos[0] + w)
                         for y in range(o.pos[1], o.pos[1] + h)}
    anchor = region.entrance_door or (rect.x + rect.w // 2, rect.y + rect.h // 2)
    cands = sorted(rect.cells(), key=lambda c: (abs(c[0] - anchor[0]) + abs(c[1] - anchor[1]),
                                                c[1], c[0]))
    for c in cands:
        if region.wall and (c[0] in (rect.x, rect.x1) or c[1] in (rect.y, rect.y1)):
            continue  # the builder treats a walled region's ring as wall
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
