"""The floors extension's layout step: multi-storey buildings.

Each upper storey becomes its own walled region in a band off the east side
of the map, behind a boundary strip (SEPARATOR_WIDTH cells, the full height
of the map). The strip is sealed by one mega-object — "The World's Edge", a
lightless slab the colour of the out-of-bounds void that blocks every cell
it covers — so nobody can walk up to the outside of an upper floor, and the
band reads as the edge of the world on the map and the minimap alike. Each
storey is exactly the size of its building's ground region and laid out over
it corner to corner (the floors game mod stacks the two). Inside, rooms and
furniture are laid out like a ground floor, and the rooms connect through
interior doors like ground rooms do.

An upper storey is sealed: no opening on its outer border, no exterior
doors — its only ways in and out are its stairs (the portals mod). The flat
map builder cannot know that, so the spec it reads carries one build-time
door per storey where the ground entrance sits; inject_arpg_mods strips
those cells again when it writes the shipped scenario, which the checks
then verify. The boundary slab is the same trick twice over: the spec
carries it as passable so the builder's reachability walk can cross the
strip to those doors, and inject_arpg_mods hardens it to walkability 0 —
and writes its sprite — in the shipped scenario.

An opening — the hole in an upper floor above a ground room — becomes an
unwalled region inside one upper room, directly above the ground room's
cells and kept clear of furniture. The game mod blocks its cells, so nobody
walks into it; the generator only has to keep it empty.
"""
from ..layout_building import layout_rooms
from ..layout_room import layout_room
from ..model import (BuildingDesign, ObjectTemplate, Rect, door_inner_cell,
                     shared_wall_cells)

SEPARATOR_WIDTH = 24  # the boundary strip between the play area and the band
BOUNDARY_NAME = "The Edge of the World"   # the region under the slab
SLAB_NAME = "The World's Edge"            # the slab object itself
BOUNDARY_COLOR = "#171614"                # the game's out-of-bounds void
BAND_MARGIN = 2  # the band's offset from the map's bottom edge
FLOOR_GAP = 2    # between stacked upper storeys in the band

STORY_SUFFIX = {2: "upper floor", 3: "top floor"}


class FloorOut:
    def __init__(self, building, storey, region_name, above_name, rect, layout):
        self.building = building      # ground building name
        self.storey = storey          # 2..n
        self.region_name = region_name
        self.above = above_name       # region name of the storey below
        self.rect = rect              # same size as the ground building rect
        self.layout = layout          # BuildingLayout of this storey
        self.opening_name = None      # the opening's region name, when it has one
        self.opening_rect = None
        # every stair is its own object, so each portal edge has its own pad:
        # (template name, cell) pairs, one per direction
        self.stair_down = None        # this storey's stair to the storey below
        self.stair_up = None          # this storey's stair to the storey above (top: None)
        self.stair_below_up = None    # the up stair on the storey below (ground for storey 2)
        # builder entity names, e.g. "Pillar 12 Apartments stairs up 1"
        self.stair_down_object = None
        self.stair_up_object = None
        self.stair_below_up_object = None
        self.builder_door = None      # the storey's build-time door cell (see above)


def apply(world, plan_data, rng):
    """Place every multi-storey building's upper storeys. Runs after the
    zone loop, before the schedules choose where people sleep. A compound's
    parts keep their ground arrangement in the band: each storey sits at
    its part's offset within the compound block, so storeys at the same
    level touch where their ground regions touch, and a walkable wall gets
    a wall-walk storey wherever both parts it joins have a storey 2."""
    from .. import ObjectOut

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
                                              if c.name == comp)))[0].append(b)
        else:
            singles.append((b, uppers))
    if not singles and not groups:
        return
    stairs = {id(b): _stair_templates(world, plan_data, b.layout.design.name)
              for (b, _u) in singles}
    for (bs, _comp) in groups.values():
        for b in bs:
            stairs[id(b)] = _stair_templates(world, plan_data, b.layout.design.name)

    # ---- the band: east of everything, behind the boundary strip, floors
    # stacked in columns. It is sized from the storeys it must hold and the
    # map grows to fit it; a planned storey is never dropped for lack of
    # room. A stack taller than the band's height budget (the play area's
    # height, a six-storey block say) wraps into another column, so the
    # World's Edge strip, the seal and the per-building mapping stay whole.
    strip_x = world.grid[0]
    band_x = strip_x + SEPARATOR_WIDTH
    width = max([b.layout.rect.w for (b, _u) in singles]
                + [comp.rect.w for (_bs, comp) in groups.values()] or [1])
    budget = max(world.grid[1], 4 * BAND_MARGIN)
    x, y = band_x, BAND_MARGIN
    top = BAND_MARGIN

    def reserve(need):
        """Column space for a stack `need` tall: wrap to a fresh column when
        the current one cannot fit it (an over-tall stack gets its own
        column and the map grows)."""
        nonlocal x, y, top
        if y > BAND_MARGIN and y + need - FLOOR_GAP > budget:
            x += width + FLOOR_GAP
            y = BAND_MARGIN
        spot = y
        y += need + FLOOR_GAP
        top = max(top, y - FLOOR_GAP)
        return spot

    rects = {}
    for (b, uppers) in singles:
        base = reserve(len(uppers) * b.layout.rect.h
                       + (len(uppers) - 1) * FLOOR_GAP)
        rs = []
        for _spec in uppers:
            r = Rect(x, base, b.layout.rect.w, b.layout.rect.h)
            rs.append(r)
            base += r.h + FLOOR_GAP
        rects[id(b)] = rs
    walks = []      # [(CompoundOut, CorridorOut, Rect)]
    group_extras = {}   # id(b) -> {upper index: [door cells]}
    for (bs, comp) in groups.values():
        max_storey = max(b.layout.design.storeys for b in bs)
        levels = max_storey - 1
        base = reserve(levels * comp.rect.h + (levels - 1) * FLOOR_GAP)
        for storey in range(2, max_storey + 1):
            level_rects = []   # [(b or None, corridor or None, rect)]
            for b in bs:
                if b.layout.design.storeys < storey:
                    continue
                i = storey - 2
                while len(rects.setdefault(id(b), [])) <= i:
                    rects[id(b)].append(None)
                r = Rect(x + (b.layout.rect.x - comp.rect.x),
                         base + (b.layout.rect.y - comp.rect.y),
                         b.layout.rect.w, b.layout.rect.h)
                rects[id(b)][i] = r
                level_rects.append((b, None, r))
            if storey == 2 and comp.corridors:
                for corridor in comp.corridors:
                    if not _walk_ends_have_storey(comp, corridor, 2):
                        continue
                    r = Rect(x + (corridor.rect.x - comp.rect.x),
                             base + (corridor.rect.y - comp.rect.y),
                             corridor.rect.w, corridor.rect.h)
                    walks.append((comp, corridor, r))
                    level_rects.append((None, corridor, r))
            # the doors auto-connect will open between touching storeys at
            # this level: the rooms behind them learn their cells now, so
            # furniture keeps the walkways clear
            for i, (ba, ca, ra) in enumerate(level_rects):
                for (bb, _cb, rb) in level_rects[i + 1:]:
                    for cell in shared_wall_cells(ra, rb):
                        if ra.contains_cell(cell) and ba is not None:
                            group_extras.setdefault(id(ba), {}).setdefault(
                                storey - 2, []).append(cell)
                        if rb.contains_cell(cell) and bb is not None:
                            group_extras.setdefault(id(bb), {}).setdefault(
                                storey - 2, []).append(cell)
            base += comp.rect.h + FLOOR_GAP
    world.grid = (x + width, max(world.grid[1], top + BAND_MARGIN))

    _add_boundary(world, plan_data, strip_x)
    for (b, uppers) in singles:
        _build_storeys(world, b, uppers, rects[id(b)], stairs[id(b)], rng)
    for (bs, comp) in groups.values():
        for b in bs:
            _build_storeys(world, b, list(b.layout.design.upper), rects[id(b)],
                           stairs[id(b)], rng,
                           extra_doors=group_extras.get(id(b)))
    for (comp, corridor, r) in walks:
        _build_wall_walk(world, comp, corridor, r)
    _name_stairs(world)


def _walk_ends_have_storey(comp, corridor, storey):
    """True when every part a wall corridor joins has a storey at `storey`:
    the wall walk above it runs tower to tower."""
    by_name = {b.layout.design.name: b for b in comp.parts}
    ends = [b for b in comp.parts if shared_wall_cells(b.layout.rect, corridor.rect)]
    return bool(ends) and all(by_name[b.layout.design.name].layout.design.storeys >= storey
                              for b in ends)


def _add_boundary(world, plan_data, strip_x):
    """The boundary: everything east of the play area. One region spans the
    strip and the band behind it, tinted the out-of-bounds void's colour —
    the band's gaps and margins show that tint, so the storeys stand out as
    the only things lit east of the play area — and the strip itself is
    sealed by one mega-object, "The World's Edge", blocking every cell it
    covers. The slab is passable in the spec alone (passableAtBuild): the
    builder's reachability walk must cross the strip, and inject_arpg_mods
    hardens it to walkability 0 — and writes its sprite — in the shipped
    scenario."""
    from .. import ObjectOut, RegionOut
    rect = Rect(strip_x, 0, world.grid[0] - strip_x, world.grid[1])
    world.regions.append(RegionOut(
        BOUNDARY_NAME, rect, "boundary", ground="stone", ground_texture="rock",
        ground_color=BOUNDARY_COLOR,
        description="The world's edge: nothing beyond it."))
    t = ObjectTemplate(
        name=SLAB_NAME, size=(SEPARATOR_WIDTH, world.grid[1]), walkability=0.0,
        description="The world simply ends here; nothing lies beyond.",
        physicalDescription="A sheer, lightless wall sealing the edge of the world.",
        tags=["landmark"],
        extras={"passableAtBuild": True, "maxHp": 999, "heightM": 3})
    world.templates[SLAB_NAME] = t
    # replace, never append-if-absent: the growth loop rebuilds on a bigger
    # map each pass, and a stale first-pass height would leave the strip's
    # south end uncovered in the spec
    plan_data["templates"] = [x for x in plan_data.get("templates", [])
                              if x.get("name") != SLAB_NAME]
    plan_data["templates"].append(
        {"name": SLAB_NAME, "size": [SEPARATOR_WIDTH, world.grid[1]],
         "walkability": 0.0,
         "passableAtBuild": True, "maxHp": 999, "heightM": 3,
         "description": t.description, "physicalDescription": t.physicalDescription,
         "tags": list(t.tags), "rule": "the world's edge; covers the whole strip"})
    world.objects.append(ObjectOut(SLAB_NAME, (rect.x, rect.y), BOUNDARY_NAME))


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
    rooms. The storey keeps the ground entrance's side (its door sits over
    the ground door), except east: the band hugs the map's east edge, so an
    east door would open off the grid — that one flips to west, onto the
    boundary slab, which is passable at build time."""
    side = "west" if design.entrance_side == "east" else design.entrance_side
    return BuildingDesign(
        name=region_name, kind=design.kind, size_class=design.size_class,
        purpose=f"the storey above {design.name}", wall=design.wall, ground=design.ground,
        rooms=spec.rooms, connections=spec.connections,
        entrance_room=spec.rooms[0].name if spec.rooms else "",
        entrance_side=side, furniture=spec.furniture)


def _stairs_room(bl):
    """The ground room the stairs rise from: the design's stairs room, or the
    entrance room when the plan named one the ground floor does not have."""
    room = bl.room_by_base(bl.design.stairs_room)
    return room if room is not None else bl.entrance_room


def _build_storeys(world, b, uppers, rects, stairs, rng, extra_doors=None):
    """Lay out one building's upper storeys and commit them (regions,
    objects, floors and stair objects) only when every storey got the stairs
    it needs; otherwise the building stays single-storey. ``extra_doors`` is
    {upper index: [cells]} — doors the builder's auto-connect will open to a
    neighbouring storey of the same compound, given to the rooms behind them
    before the furniture is laid out."""
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
        for cell in (extra_doors or {}).get(i, []):
            _room_door(layout, cell)
        names = {r.base_name for r in layout.rooms}
        for f in layout.furniture:
            if f.room not in names:
                world.failures.append((f"piece {f.template} in {region_name}",
                                       f"room {f.room!r} not in the storey"))
        opening_rect, opening_room = (None, None)
        if spec is not None and spec.opening is not None:
            ground_room = bl.room_by_base(spec.opening.over_room)
            if ground_room is None:
                world.failures.append((f"opening in {region_name}",
                                       f"over_room {spec.opening.over_room!r} is not a "
                                       f"ground room; dropped"))
            else:
                area = Rect(rect.x + (ground_room.rect.x - bl.rect.x),
                            rect.y + (ground_room.rect.y - bl.rect.y),
                            ground_room.rect.w, ground_room.rect.h)
                opening_rect, opening_room = _choose_opening(layout, area)
                if opening_rect is None:
                    world.failures.append((f"opening in {region_name}",
                                           f"no clear spot above {spec.opening.over_room}; dropped"))
        for room in layout.rooms:
            furniture = [f for f in layout.furniture if f.room == room.base_name]
            keep_clear = opening_rect.cells() if room is opening_room else None
            room.furniture = layout_room(room.rect, sorted(room.doors), furniture,
                                         world.templates, rng, keep_clear=keep_clear)
            for (t, n, reason) in room.furniture.failures:
                world.failures.append((f"piece {t} in {region_name} {room.base_name}",
                                       f"placed {n} of the requested count: {reason}"))
            for (t, reason) in room.furniture.fallbacks:
                world.fallbacks.append((f"piece {t} in {region_name} {room.base_name}", reason))

        f = FloorOut(design.name, storey, region_name, above, rect, layout)
        f.opening_rect = opening_rect
        single = len(layout.rooms) == 1 and layout.rooms[0].rect == rect
        room_names = ({region_name} if single
                      else {f"{region_name} {r.base_name}" for r in layout.rooms})
        if opening_rect is not None:
            # "Gallery Well" style; the plain kind word when no room took it
            base = f"{region_name} {spec.opening.kind.capitalize()}"
            f.opening_name = base if base not in room_names else f"{base} Well"
        f.builder_door = layout.entrance_door
        # sealed: an upper storey has no opening on its outer border — its
        # only ways in and out are its stairs (the builder_door is a
        # build-time fiction the spec writer adds and injection strips)
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
            for (tname, pos) in room.furniture.placements:
                objects.append(ObjectOut(tname, pos, room.full_name))
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
        if opening_rect is not None:
            regions.append(RegionOut(f.opening_name, opening_rect, "opening",
                                     parent=region_name, ground="wood",
                                     ground_texture="floorboards",
                                     ambience={"day": "quiet_indoor"},
                                     description=f"The open {spec.opening.kind} down to "
                                                 f"{design.name} {spec.opening.over_room}."))
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

def _intersect(a, b):
    x0, y0 = max(a.x, b.x), max(a.y, b.y)
    x1, y1 = min(a.x1, b.x1), min(a.y1, b.y1)
    return Rect(x0, y0, x1 - x0 + 1, y1 - y0 + 1) if x1 >= x0 and y1 >= y0 else None


def _choose_opening(layout, area):
    """(rect, room) for an opening: inside one upper room, over the ground
    room's cells, at most half the room (the rest stays floor), never sealing
    part of the room it sits in. The biggest shape that passes wins, so a
    gallery gets a wide well and a strip room a short one."""
    best_room, best_base = None, None
    for room in layout.rooms:
        base = _intersect(area, room.rect.interior())
        if base is not None and (best_base is None or base.w * base.h > best_base.w * best_base.h):
            best_room, best_base = room, base
    if best_room is None:
        return None, None
    inter = best_room.rect.interior()
    half = (inter.w * inter.h) // 2
    inner_doors = {door_inner_cell(best_room.rect, d) for d in best_room.doors}
    ws = sorted({w for w in (best_base.w, best_base.w - 2, max(2, best_base.w // 2))
                 if 2 <= w <= best_base.w})
    hs = sorted({h for h in (best_base.h, best_base.h - 2, max(2, best_base.h // 2))
                 if 2 <= h <= best_base.h})
    sizes = sorted(((cw, ch) for cw in ws for ch in hs),
                   key=lambda s: (-(s[0] * s[1]), -min(s[0], s[1])))
    cx, cy = best_base.center()
    for (cw, ch) in sizes:
        if cw * ch > half:
            continue
        spots = [(x, y) for x in range(best_base.x, best_base.x1 - cw + 2)
                 for y in range(best_base.y, best_base.y1 - ch + 2)]
        spots.sort(key=lambda p: (abs(p[0] + (cw - 1) / 2.0 - cx) + abs(p[1] + (ch - 1) / 2.0 - cy),
                                  p[1], p[0]))
        for (x, y) in spots:
            cand = Rect(x, y, cw, ch)
            if cand.cells() & inner_doors:
                continue   # the opening would block the door's approach cell
            if not _seals_room(best_room, cand):
                return cand, best_room
    return None, None


def _seals_room(room, opening):
    """True when the opening cuts part of the room off from its doors."""
    walk = set(room.rect.interior().cells()) - set(opening.cells())
    starts = {door_inner_cell(room.rect, d) for d in room.doors}
    seen = set(c for c in starts if c in walk)
    todo = list(seen)
    while todo:
        x, y = todo.pop()
        for c in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if c in walk and c not in seen:
                seen.add(c)
                todo.append(c)
    return seen != walk


# ------------------------------------------------------------------ the stairs

def _ring(rect):
    return {c for c in rect.cells() if c[0] in (rect.x, rect.x1) or c[1] in (rect.y, rect.y1)}


def _free_stair_cells(world, rooms, opening_rect, avoid=(), relax=False):
    """Cells a 1x1 stair may take in `rooms`: inside the walls, never on
    furniture or in the opening, off the reserved walkways unless `relax`,
    minus the `avoid` cells."""
    free = set()
    for room in rooms:
        cells = set(room.rect.interior().cells())
        for (t, pos) in room.furniture.placements:
            tw, th = world.templates[t].size
            cells -= {(x, y) for x in range(pos[0], pos[0] + tw)
                      for y in range(pos[1], pos[1] + th)}
        if not relax and room.furniture is not None:
            cells -= set(room.furniture.reserved)
        free |= cells
    if opening_rect is not None:
        free -= opening_rect.cells()
    return free - set(avoid)


def _pick_stair_cell(world, rooms, opening_rect, avoid=(), prefer=None, relax=False):
    """The best free stair cell among `rooms`, nearest to `prefer` (the room
    cluster's centre by default). None when every cell is taken."""
    free = _free_stair_cells(world, rooms, opening_rect, avoid, relax)
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
    walls between its rooms minus the door cells those rooms share, solid
    furniture, and the opening (the game mod blocks it)."""
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
                tw, th = world.templates[t].size
                blocked |= {(x, y) for x in range(pos[0], pos[0] + tw)
                            for y in range(pos[1], pos[1] + th)}
    if f.opening_rect is not None:
        blocked |= f.opening_rect.cells()
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
        cands = _free_stair_cells(world, f.layout.rooms, f.opening_rect, avoid, relax)
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
    cell = _pick_stair_cell(world, [g_room], None) \
        or _pick_stair_cell(world, [g_room], None, relax=True) \
        or _pick_stair_cell(world, bl.rooms, None, relax=True)
    if cell is None:
        return None, "the ground floor"
    out.append((g_room, t_up.name, cell))
    below_up = (t_up.name, cell)
    below_rect = bl.rect
    for i, f in enumerate(floors):
        prefer = (f.rect.x + (below_up[1][0] - below_rect.x),
                  f.rect.y + (below_up[1][1] - below_rect.y))
        cell = _pick_stair_cell(world, f.layout.rooms, f.opening_rect, prefer=prefer) \
            or _pick_stair_cell(world, f.layout.rooms, f.opening_rect, prefer=prefer, relax=True)
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


def _room_door(layout, cell):
    """An auto-connect door cell on a storey's outer border: the room whose
    wall it sits on learns it, so its furniture keeps the walkway clear."""
    x, y = cell
    extra = list(getattr(layout, "extra_doors", []))
    if cell not in extra:
        extra.append(cell)
    layout.extra_doors = extra
    for room in layout.rooms:
        if room.rect.contains_cell(cell) and \
                (x in (room.rect.x, room.rect.x1) or y in (room.rect.y, room.rect.y1)):
            room.doors.add(cell)
            return


def _build_wall_walk(world, comp, corridor, rect):
    """The storey above a walkable wall: a sealed walled region the size of
    the corridor, no rooms and no stairs of its own — its ways in and out
    are the doors it shares with the parts it joins upstairs."""
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


def _name_stairs(world):
    """Give every stair object its builder entity name ("<template> <i>",
    numbered per template in placement order, exactly as build_scenario.py
    numbers them) and link the stair pairs as two-way portals: the up stair
    on the storey below to the down stair on the storey above — two
    different objects, so no pad is ever the end of two portals. A wall walk
    carries no stairs; it is skipped here."""
    counts, names = {}, {}
    for o in world.objects:
        counts[o.template] = counts.get(o.template, 0) + 1
        names[(o.template, o.pos)] = f"{o.template} {counts[o.template]}"

    def end(ref):
        return names.get((ref[0], ref[1])) if ref is not None else None

    for f in world.floors:
        if f.stair_down is None and f.stair_below_up is None:
            continue   # a wall walk: its doors, not stairs, are its ways in
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


# ------------------------------------------------------------------ the output

def shared_storey_doors(rects_by_name, openings_by_name):
    """{storey name: {cells}} — the openings on each storey area's border
    that are doors to another storey: a wall-walk door. Two storeys that
    touch (edges 0 or 1 apart) share one wall line (a single cell) or a
    facing pair of cells; each side is kept when it is an opening of the
    region it sits on and the other side is an opening of its own.
    Everything else on a storey's border is a build-time fiction door:
    sealed away in play."""
    from ..model import shared_wall_cells as _shared
    names = list(rects_by_name)
    keep = {n: set() for n in names}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            pair = _shared(rects_by_name[a], rects_by_name[b])
            if not pair:
                continue
            oa = openings_by_name.get(a, set())
            ob = openings_by_name.get(b, set())
            if len(pair) == 1:
                (cell,) = pair
                if cell in oa and cell in ob:
                    keep[a].add(cell)
                    keep[b].add(cell)
                continue
            ca, cb = pair
            if ca in oa and cb in ob:
                if rects_by_name[a].contains_cell(ca):
                    keep[a].add(ca)
                    keep[b].add(cb)
                else:
                    keep[a].add(cb)
                    keep[b].add(ca)
    return keep


def arpg_mods(world):
    """The spec's arpgMods: one floors entry per upper storey, one portals
    entry per stair pair. The build injects the dict into scenario.json."""
    floors = []
    for f in world.floors:
        floors.append({
            "name": f"{f.building} floor {f.storey}",
            "area": f.region_name,
            "above": f.above,
            "openings": [f.opening_name] if f.opening_name else [],
        })
    return {"floors": floors, "portals": [dict(p) for p in world.portals]}
