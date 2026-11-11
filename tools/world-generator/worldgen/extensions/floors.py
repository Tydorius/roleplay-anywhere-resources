"""The floors extension's layout step: multi-storey buildings.

Anywhere RPG 1.0 has floors of its own: each upper storey is a region with
``pocket: {anchor: <its ground region>, level: N}``, laid out as a plane of
its own beside the map. We place them as the game does — the first at
``gridSize[0] + FLOOR_GAP``, then FLOOR_GAP cells apart, one spot per
storey, each the size of its building's ground region (``gridSize`` stays
the play area; the floors sit outside it). Inside, rooms and furniture are
laid out like a ground floor, and the rooms connect through interior doors
like ground rooms do.

An upper storey is sealed: no opening on its outer border, no exterior
doors — its only ways in and out are its stairs, 1.0 portal objects pointing
at each other ("Link Portal"). The flat-map builder cannot know that, so the
spec it reads carries one build-time door per storey where the ground
entrance sits; finish_scenario strips those cells again — and writes the
pockets and the portal links — in the shipped scenario, which the checks
then verify. 1.0 has no see-through openings between floors, so a planned
gallery or well simply stays ordinary room floor.

A compound's wall walk (the storey above a walkable wall) is a floor too,
reached like any other: a walkable 1x1 passage object in the walk and one
in each tower's storey, linked as a portal pair the way stairs are — planes
cannot share a door in 1.0.
"""
from ..layout_building import layout_rooms
from ..layout_room import layout_room
from ..model import BuildingDesign, ObjectTemplate, Rect, shared_wall_cells

FLOOR_GAP = 24     # 1.0 lays floors out east of the map, 24 cells apart
FLOOR_Y = 1        # the floors' row: a south build-time door keeps a cell to open onto
BOUNDARY_COLOR = "#171614"     # the game's out-of-bounds void (the void zones' tint)

STORY_SUFFIX = {2: "upper floor", 3: "top floor"}


class FloorOut:
    def __init__(self, building, storey, region_name, above_name, rect, layout):
        self.building = building      # ground building (or wall) region name; the pocket anchor
        self.storey = storey          # 2..n
        self.region_name = region_name
        self.above = above_name       # region name of the storey below
        self.rect = rect              # same size as the ground building rect
        self.layout = layout          # BuildingLayout of this storey
        # every stair is its own object, so each portal edge has its own pad:
        # (template name, cell) pairs, one per direction
        self.stair_down = None        # this storey's stair to the storey below
        self.stair_up = None          # this storey's stair to the storey above (top: None)
        self.stair_below_up = None    # the up stair on the storey below (ground for storey 2)
        # builder entity names, e.g. "Pillar 12 Apartments stairs up 1"
        self.stair_down_object = None
        self.stair_up_object = None
        self.stair_below_up_object = None
        # a wall walk's passage pads: (template name, cell) in this storey,
        # paired with the walk's own pads in world.walk_links
        self.passages = []
        self.builder_door = None      # the storey's build-time door cell (see above)


def apply(world, plan_data, rng):
    """Place every multi-storey building's upper storeys. Runs after the
    zone loop, before the schedules choose where people sleep. Each storey
    is its own 1.0 floor plane east of the play area (first at the map's
    width + FLOOR_GAP, then FLOOR_GAP apart, any y >= 0), and a walkable
    compound wall gets a wall-walk storey wherever both parts it joins have
    a storey 2, linked to them by passage portals."""
    if "floors" not in world.extensions:
        return
    singles = []    # [(BuildingOut, [UpperStorey or None])]
    groups = {}     # compound name -> ([BuildingOut-with-uppers], CompoundOut)
    for b in world.buildings:
        d = b.layout.design
        if d.storeys < 2 or (not d.upper and not getattr(d, "units", None)):
            continue
        # a unit building's upper storeys repeat its ground stamp: no
        # per-storey design exists, so it carries None placeholders
        uppers = list(d.upper) if d.upper else [None] * (d.storeys - 1)
        if b.layout.room_by_base(d.stairs_room) is None and not getattr(d, "units", None):
            # a stairs room the ground floor does not have would cost the
            # building its storeys; the stairs rise from the entrance room
            # instead (recorded as a hint fallback, never a drop)
            world.fallbacks.append((f"floors of {d.name}",
                                    f"stairs room {d.stairs_room!r} is not a ground room; "
                                    f"the stairs rise from the entrance room"))
        comp = getattr(b, "compound", None)
        if comp and any(c.name == comp for c in getattr(world, "compounds", []) or []):
            groups.setdefault(comp, ([], next(c for c in world.compounds
                                              if c.name == comp)))[0].append((b, uppers))
        else:
            singles.append((b, uppers))
    if not singles and not groups:
        return
    stairs = {id(b): _stair_templates(world, plan_data, b.layout.design.name)
              for (b, _u) in singles}
    for (bs, _comp) in groups.values():
        for (b, _u) in bs:
            stairs[id(b)] = _stair_templates(world, plan_data, b.layout.design.name)

    # ---- the floors: one spot per storey, east of the play area, FLOOR_GAP
    # cells apart like the game's own nextFloorSpot. The map (gridSize) is
    # the play area only and never grows to hold them; a planned storey is
    # never dropped for lack of room — the planes just march further east.
    x = world.grid[0] + FLOOR_GAP
    rects = {}

    def spots(b):
        nonlocal x
        rs = []
        for _spec in range(b.layout.design.storeys - 1):
            r = Rect(x, FLOOR_Y, b.layout.rect.w, b.layout.rect.h)
            rs.append(r)
            x += r.w + FLOOR_GAP
        return rs

    for (b, uppers) in singles:
        rects[id(b)] = spots(b)
    walks = []      # [(CompoundOut, CorridorOut, Rect)]
    for (bs, comp) in groups.values():
        for (b, uppers) in bs:
            rects[id(b)] = spots(b)
        for corridor in comp.corridors:
            if not _walk_ends(comp, corridor):
                continue
            r = Rect(x, FLOOR_Y, corridor.rect.w, corridor.rect.h)
            walks.append((comp, corridor, r))
            x += r.w + FLOOR_GAP

    world.walk_links = []   # [(walk pad, end pad)] — the passage pairs
    for (b, uppers) in singles:
        _build_storeys(world, b, uppers, rects[id(b)], stairs[id(b)], rng)
    for (bs, comp) in groups.values():
        for (b, uppers) in bs:
            _build_storeys(world, b, uppers, rects[id(b)], stairs[id(b)], rng)
    for (comp, corridor, r) in walks:
        # a walk with an end that lost its storey (no stair cell) would
        # dead-end upstairs; its spot stays empty ground instead
        if all(any(f.storey == 2 for f in getattr(b, "floors", []) or [])
               for b in _walk_ends(comp, corridor)):
            _build_wall_walk(world, comp, corridor, r)
    _link_walks(world, plan_data)
    _name_stairs(world)


def _walk_ends(comp, corridor, storey=2):
    """The parts a wall corridor joins that rise to `storey` by design: the
    wall walk above it runs tower to tower between them."""
    by_name = {b.layout.design.name: b for b in comp.parts}
    ends = [by_name[b.layout.design.name] for b in comp.parts
            if shared_wall_cells(b.layout.rect, corridor.rect)]
    # every part it joins must rise that high, or the walk dead-ends upstairs
    if not ends or any(b.layout.design.storeys < storey for b in ends):
        return []
    return ends


def _stair_templates(world, plan_data, building):
    """(up template, down template): one walkable 1x1 stair template per
    direction per building — "<Building> stairs up", "<Building> stairs
    down" — so every portal edge names its own pad."""
    out = {}
    for direction in ("up", "down"):
        name = f"{building} stairs {direction}"
        t = world.templates.get(name)
        if t is None:
            where = "up to the floor above" if direction == "up" \
                else "down to the floor below"
            t = ObjectTemplate(name=name, size=(1, 1), walkability=1.0,
                               description=f"The stair {where}, in {building}.",
                               physicalDescription="a narrow staircase seen from above",
                               tags=["stairs"], rule="in the stair hall; kept walkable")
            world.templates[name] = t
            known = {x.get("name") for x in plan_data.setdefault("templates", [])}
            if name not in known:
                plan_data["templates"].append(
                    {"name": name, "size": [1, 1], "walkability": 1.0,
                     "description": t.description, "physicalDescription": t.physicalDescription,
                     "tags": list(t.tags), "rule": t.rule})
        out[direction] = t
    return out["up"], out["down"]


def _upper_design(design, spec, region_name):
    """The storey's own design: the ground building's shell around the spec's
    rooms. The storey keeps the ground entrance's side (its build-time door
    sits over the ground door); the builder's grid pads a cell past every
    edge, so the door always opens onto open ground."""
    return BuildingDesign(
        name=region_name, kind=design.kind, size_class=design.size_class,
        purpose=f"the storey above {design.name}", wall=design.wall, ground=design.ground,
        rooms=spec.rooms, connections=spec.connections,
        entrance_room=spec.rooms[0].name if spec.rooms else "",
        entrance_side=design.entrance_side, furniture=spec.furniture)


def _stairs_room(bl):
    """The ground room the stairs rise from: the design's stairs room, or the
    entrance room when the plan named one the ground floor does not have."""
    room = bl.room_by_base(bl.design.stairs_room)
    return room if room is not None else bl.entrance_room


def _build_storeys(world, b, uppers, rects, stairs, rng):
    """Lay out one building's upper storeys and commit them (regions,
    objects, floors and stair objects) only when every storey got the stairs
    it needs; otherwise the building stays single-storey."""
    from .. import ObjectOut, RegionOut

    bl = b.layout
    design = bl.design
    floors, regions, objects = [], [], []
    above = design.name
    for i, (spec, rect) in enumerate(zip(uppers, rects)):
        storey = i + 2
        region_name = f"{design.name} ({STORY_SUFFIX.get(storey, f'floor {storey}')})"
        if getattr(design, "units", None):
            # a unit storey is the ground stamp again: the corridor and the
            # copies' positions repeat, the numbering continues upstairs
            from ..layout_building import layout_units
            layout = layout_units(design, rect, rng, world.templates,
                                  storey=storey, make_entrance=False)
        else:
            layout = layout_rooms(_upper_design(design, spec, region_name), rect, rng,
                                  world.templates, furniture=spec.furniture)
        names = {r.base_name for r in layout.rooms}
        for f in layout.furniture:
            if f.room not in names:
                world.failures.append((f"piece {f.template} in {region_name}",
                                       f"room {f.room!r} not in the storey"))
        for room in layout.rooms:
            furniture = [f for f in layout.furniture if f.room == room.base_name]
            room.furniture = layout_room(room.rect, sorted(room.doors), furniture,
                                         world.templates, rng)
            for (t, n, reason) in room.furniture.failures:
                world.failures.append((f"piece {t} in {region_name} {room.base_name}",
                                       f"placed {n} of the requested count: {reason}"))
            for (t, reason) in room.furniture.fallbacks:
                world.fallbacks.append((f"piece {t} in {region_name} {room.base_name}", reason))

        f = FloorOut(design.name, storey, region_name, above, rect, layout)
        single = len(layout.rooms) == 1 and layout.rooms[0].rect == rect
        f.builder_door = layout.entrance_door
        # sealed: an upper storey has no opening on its outer border — its
        # only ways in and out are its stairs (the builder_door is a
        # build-time fiction the spec writer adds and finish_scenario strips)
        storey_reg = RegionOut(region_name, rect, "building", parent=None,
                               wall=design.wall, ground="wood", ground_texture="floorboards",
                               ambience={"day": "quiet_indoor"},
                               description=f"The {STORY_SUFFIX.get(storey, 'next floor')} "
                                           f"of {design.name}.",
                               doors=set())
        regions.append(storey_reg)
        for room in layout.rooms:
            room.full_name = region_name if single else f"{region_name} {room.base_name}"
            amb = {"day": "quiet_indoor"}
            for (t, _p) in room.furniture.placements:
                if "light" in world.templates[t].tags and world.templates[t].walkability <= 0:
                    amb = {"day": "fireplace"}
                    break
            if single:
                storey_reg.ambience = amb
            else:
                purposes = {r.name: r.purpose for r in spec.rooms} if spec is not None \
                    else {r.name: r.purpose for r in layout.design.rooms}
                reg = RegionOut(room.full_name, room.rect, "room", parent=region_name,
                                wall=design.wall, ground="wood", ground_texture="floorboards",
                                ambience=amb,
                                description=purposes.get(room.base_name, ""))
                reg.entrance_door = None   # sealed: no exterior door upstairs
                regions.append(reg)
            # each piece keeps the quarter turn the room layout gave it, as on
            # the ground floor: the layout checked the turned cells, so an
            # unturned piece would ship on cells nobody checked
            for (tname, pos) in room.furniture.placements:
                objects.append(ObjectOut(tname, pos, room.full_name,
                                         room.furniture.rot(tname, pos)))
        if getattr(design, "units", None):
            from .. import _emit_unit_regions
            from ..layout_room import layout_room as _lr
            for uo in layout.unit_outs:
                for room in uo.layout.rooms:
                    furniture = [f for f in uo.layout.furniture
                                 if f.room == room.base_name]
                    room.furniture = _lr(room.rect, sorted(room.doors), furniture,
                                         world.templates, rng)
                    for (t, n, reason) in room.furniture.failures:
                        world.failures.append((f"piece {t} in {uo.name} {room.base_name}",
                                               f"placed {n} of the requested count: {reason}"))
                    for (t, reason) in room.furniture.fallbacks:
                        world.fallbacks.append((f"piece {t} in {uo.name} {room.base_name}",
                                                reason))
            uregs, uobjs = _emit_unit_regions(world, layout, region_name, {})
            regions.extend(uregs)
            objects.extend(uobjs)
        above = region_name
        floors.append(f)

    placed, where = _plan_stairs(world, b, floors, stairs)
    if placed is None:
        world.failures.append((f"floors of {design.name}",
                               f"no free cell for the stairs on {where}; "
                               f"built single-storey"))
        return
    for (room, tname, cell) in placed:
        room.furniture.placements.append((tname, cell))
        objects.append(ObjectOut(tname, cell, room.full_name))

    world.regions.extend(regions)
    world.objects.extend(objects)
    world.floors.extend(floors)
    b.floors = floors


# ------------------------------------------------------------------ geometry

def _ring(rect):
    return {c for c in rect.cells() if c[0] in (rect.x, rect.x1) or c[1] in (rect.y, rect.y1)}


def _free_stair_cells(world, rooms, avoid=(), relax=False):
    """Cells a 1x1 stair may take in `rooms`: inside the walls, never on
    furniture, off the reserved walkways unless `relax`, minus the `avoid`
    cells."""
    free = set()
    for room in rooms:
        cells = set(room.rect.interior().cells())
        for (t, pos) in room.furniture.placements:
            tw, th = room.furniture.size_of(t, pos, world.templates)
            cells -= {(x, y) for x in range(pos[0], pos[0] + tw)
                      for y in range(pos[1], pos[1] + th)}
        if not relax and room.furniture is not None:
            cells -= set(room.furniture.reserved)
        free |= cells
    return free - set(avoid)


def _pick_stair_cell(world, rooms, avoid=(), prefer=None, relax=False):
    """The best free stair cell among `rooms`, nearest to `prefer` (the room
    cluster's centre by default). None when every cell is taken."""
    free = _free_stair_cells(world, rooms, avoid, relax)
    if not free:
        return None
    if prefer is None:
        prefer = (sum(c[0] for c in free) // len(free), sum(c[1] for c in free) // len(free))
    return min(free, key=lambda c: (abs(c[0] - prefer[0]) + abs(c[1] - prefer[1]), c[1], c[0]))


def _room_holding(layout, cell):
    for r in layout.rooms:
        if r.rect.interior().contains_cell(cell):
            return r
    return layout.rooms[0]


def _storey_blocked(world, f):
    """The cells nobody can cross on one storey: its sealed outer wall, the
    walls between its rooms minus the door cells those rooms share, and
    solid furniture."""
    blocked = _ring(f.rect)
    rooms = f.layout.rooms
    doors = set()
    for i, ra in enumerate(rooms):
        for rb in rooms[i + 1:]:
            for cell in shared_wall_cells(ra.rect, rb.rect):
                doors.add(cell)
    for room in rooms:
        blocked |= (_ring(room.rect) - doors)
        for (t, pos) in room.furniture.placements:
            if world.templates[t].walkability <= 0:
                tw, th = room.furniture.size_of(t, pos, world.templates)
                blocked |= {(x, y) for x in range(pos[0], pos[0] + tw)
                            for y in range(pos[1], pos[1] + th)}
    return blocked


def _connected(rect, a, b, blocked):
    """Whether `b` is walkable from `a` inside `rect` with `blocked` closed."""
    if a in blocked or b in blocked:
        return a == b
    seen = {a}
    todo = [a]
    while todo:
        x, y = todo.pop()
        if (x, y) == b:
            return True
        for c in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if c in seen or not rect.contains_cell(c) or c in blocked:
                continue
            seen.add(c)
            todo.append(c)
    return False


def _pick_second_stair_cell(world, f, down):
    """The cell for a storey's up stair: a cell of its own, never adjacent to
    the down stair (so neither blocks the other's approach), still reachable
    from it across the storey. Nearest cell about three cells out wins; the
    distance and then the reachability requirement relax as a last resort."""
    near = {(x, y) for x in range(down[0] - 1, down[0] + 2)
            for y in range(down[1] - 1, down[1] + 2)}
    blocked = _storey_blocked(world, f)
    for avoid, need_path, relax in ((near, True, False), ({down}, True, False),
                                    (near, True, True), ({down}, True, True),
                                    (near, False, True)):
        cands = _free_stair_cells(world, f.layout.rooms, avoid, relax)
        if need_path:
            cands = {c for c in cands if _connected(f.rect, down, c, blocked)}
        if cands:
            def gap(c):
                return max(abs(c[0] - down[0]), abs(c[1] - down[1]))
            return min(cands, key=lambda c: (abs(gap(c) - 3), c[1], c[0]))
    return None


def _plan_stairs(world, b, floors, stairs):
    """[(room, template name, cell)] for every stair of one building, or
    (None, where) when a storey has no cell for the stairs it needs. The up
    stair rises from the ground stairs room; every upper storey gets a down
    stair (preferring the cell over the stair it pairs with) and, below the
    top storey, an up stair of its own — every stair a separate object, so
    each portal edge has its own pad."""
    bl = b.layout
    t_up, t_down = stairs
    out = []
    g_room = _stairs_room(bl)
    cell = _pick_stair_cell(world, [g_room]) \
        or _pick_stair_cell(world, [g_room], relax=True) \
        or _pick_stair_cell(world, bl.rooms, relax=True)
    if cell is None:
        return None, "the ground floor"
    out.append((g_room, t_up.name, cell))
    below_up = (t_up.name, cell)
    below_rect = bl.rect
    for i, f in enumerate(floors):
        prefer = (f.rect.x + (below_up[1][0] - below_rect.x),
                  f.rect.y + (below_up[1][1] - below_rect.y))
        cell = _pick_stair_cell(world, f.layout.rooms, prefer=prefer) \
            or _pick_stair_cell(world, f.layout.rooms, prefer=prefer, relax=True)
        if cell is None:
            return None, f.region_name
        f.stair_down = (t_down.name, cell)
        f.stair_below_up = below_up
        out.append((_room_holding(f.layout, cell), t_down.name, cell))
        if i + 1 < len(floors):
            up = _pick_second_stair_cell(world, f, cell)
            if up is None:
                return None, f"{f.region_name}: no second cell for its up stair"
            f.stair_up = (t_up.name, up)
            out.append((_room_holding(f.layout, up), t_up.name, up))
            below_up = f.stair_up
        below_rect = f.rect
    return out, None


def _build_wall_walk(world, comp, corridor, rect):
    """The storey above a walkable wall: a sealed walled floor the size of
    the corridor, no rooms and no stairs of its own — its ways in and out
    are the passages linked to the parts it joins upstairs."""
    from .. import RegionOut
    from ..layout_building import BuildingLayout
    from ..model import BuildingDesign

    region_name = f"{corridor.name} ({STORY_SUFFIX[2]})"
    design = BuildingDesign(name=corridor.name, wall=corridor.wall)
    layout = BuildingLayout(design, rect)
    f = FloorOut(corridor.name, 2, region_name, corridor.name, rect, layout)
    f.builder_door = (rect.x, rect.y + (rect.h - 1) // 2)
    world.regions.append(RegionOut(
        region_name, rect, "building", parent=None, wall=corridor.wall,
        ground="wood", ground_texture="floorboards",
        ambience={"day": "quiet_indoor"},
        description=f"The walk above {corridor.name}.", doors=set()))
    world.floors.append(f)
    return f


def _passage_template(world, plan_data, name):
    """One walkable 1x1 passage template per name — "<name> passage" — the
    pad a wall walk's portal ends stand on."""
    tname = f"{name} passage"
    t = world.templates.get(tname)
    if t is None:
        t = ObjectTemplate(name=tname, size=(1, 1), walkability=1.0,
                           description=f"The way along {name}, seen from above.",
                           physicalDescription="a narrow walkway",
                           tags=["stairs"], rule="kept walkable")
        world.templates[tname] = t
        known = {x.get("name") for x in plan_data.setdefault("templates", [])}
        if tname not in known:
            plan_data["templates"].append(
                {"name": tname, "size": [1, 1], "walkability": 1.0,
                 "description": t.description, "physicalDescription": t.physicalDescription,
                 "tags": list(t.tags), "rule": t.rule})
    return tname


def _link_walks(world, plan_data):
    """A two-way portal pair for every part a wall walk joins: one walkable
    1x1 passage object in the walk and one just inside that part's storey
    above, placed like stairs (a free cell off the walkways) and linked the
    same way — planes cannot share a door in 1.0, so the walk's old doors
    become portals. Each end gets its own pad in the walk, nearest the part
    it serves, so no pad is ever the end of two portals."""
    from .. import ObjectOut

    walks = [f for f in world.floors
             if f.stair_down is None and f.stair_up is None and f.stair_below_up is None]
    for comp in getattr(world, "compounds", []) or []:
        for corridor in comp.corridors:
            walk = next((f for f in walks if f.building == corridor.name), None)
            if walk is None:
                continue
            wt = _passage_template(world, plan_data, corridor.name)
            ends = [f for b in _walk_ends(comp, corridor)
                    for f in getattr(b, "floors", []) or [] if f.storey == 2]
            if not ends:
                continue
            inter = walk.rect.interior().cells()
            used, links, taken = set(), [], {}   # taken: end floor -> its pad cell
            for b in _walk_ends(comp, corridor):
                f2 = next((f for f in getattr(b, "floors", []) or []
                           if f.storey == 2), None)
                if f2 is None:
                    continue
                # the walk pad nearest the end part, mirroring where its
                # ground wall the corridor meets
                tx = (b.layout.rect.x + b.layout.rect.w // 2
                      - corridor.rect.x + walk.rect.x)
                ty = (b.layout.rect.y + b.layout.rect.h // 2
                      - corridor.rect.y + walk.rect.y)
                free = [c for c in inter if c not in used]
                if not free:
                    world.failures.append((f"wall walk {corridor.name}",
                                           "no clear cell for its passages"))
                    break
                wcell = min(free, key=lambda c: (abs(c[0] - tx) + abs(c[1] - ty),
                                                 c[1], c[0]))
                used.add(wcell)
                t = _passage_template(world, plan_data, f2.building)
                avoid = {ref[1] for ref in (f2.stair_down, f2.stair_up,
                                            f2.stair_below_up) if ref is not None}
                avoid |= {c for (ff, c) in taken.items() if ff is f2}
                cell = _pick_stair_cell(world, f2.layout.rooms, avoid=avoid) \
                    or _pick_stair_cell(world, f2.layout.rooms, avoid=avoid, relax=True)
                if cell is None:
                    world.failures.append((f"wall walk {corridor.name}",
                                           f"no free cell for a passage in {f2.region_name}"))
                    continue
                taken[f2] = cell
                links.append((wcell, f2, t, cell))
            for (wcell, f2, t, cell) in links:
                walk.passages.append((wt, wcell))
                world.objects.append(ObjectOut(wt, wcell, walk.region_name))
                f2.passages.append((t, cell))
                room = _room_holding(f2.layout, cell)
                room.furniture.placements.append((t, cell))
                world.objects.append(ObjectOut(t, cell, room.full_name))
                world.walk_links.append(((wt, wcell), (t, cell)))


def _name_stairs(world):
    """Give every stair and passage object its builder entity name
    ("<template> <i>", numbered per template in placement order, exactly as
    build_scenario.py numbers them) and link the pairs as two-way portals:
    the up stair on the storey below to the down stair on the storey above,
    and each wall walk's passage pads to their partners — two different
    objects every time, so no pad is ever the end of two portals."""
    counts, names = {}, {}
    for o in world.objects:
        counts[o.template] = counts.get(o.template, 0) + 1
        names[(o.template, o.pos)] = f"{o.template} {counts[o.template]}"

    def end(ref):
        return names.get((ref[0], ref[1])) if ref is not None else None

    for f in world.floors:
        if f.stair_down is None and f.stair_below_up is None:
            continue   # a wall walk: its passages, not stairs, are its ways in
        f.stair_down_object = end(f.stair_down)
        f.stair_up_object = end(f.stair_up)
        f.stair_below_up_object = end(f.stair_below_up)
        if f.stair_down_object is None or f.stair_below_up_object is None:
            world.failures.append((f"stairs of {f.building}",
                                   "a stair object has no builder name"))
            continue
        world.portals.append({
            "name": f"{f.building} Stairs {f.storey - 1}-{f.storey}",
            "from": {"object": f.stair_below_up_object},
            "to": {"object": f.stair_down_object},
            "twoWay": True,
        })
    for (wpad, epad) in getattr(world, "walk_links", []) or []:
        a, b = end(wpad), end(epad)
        if a is None or b is None:
            world.failures.append(("passages of the wall walks",
                                   "a passage object has no builder name"))
            continue
        world.portals.append({
            "name": f"Passage {a} to {b}",
            "from": {"object": a},
            "to": {"object": b},
            "twoWay": True,
        })


# ------------------------------------------------------------------ the output

def native_floors(world):
    """The 1.0-native floor data the output step splices into the built
    scenario: one entry per storey (its region name, the ground region it
    hangs off, its level — storey 2 is level 1), one pair per linked stair
    or passage (object entity names), the storeys whose build-time fiction
    doors the seal strips, and the play-area grid the floors sit outside
    (the shipped gridSize; the builder's grid is bigger to hold the floors)."""
    return {
        "grid": [world.grid[0], world.grid[1]],
        "floors": [{"region": f.region_name, "anchor": f.building,
                    "level": f.storey - 1} for f in world.floors],
        "portals": [{"a": p["from"]["object"], "b": p["to"]["object"]}
                    for p in world.portals],
        "seal": [f.region_name for f in world.floors],
    }
