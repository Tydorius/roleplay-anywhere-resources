"""worldgen: deterministic, seeded code layout for Roleplay Anywhere scenarios.

`run(plan_dict, seed)` executes the whole pipeline (map -> zones -> buildings ->
rooms -> people -> checks) and returns a World with everything the spec writer
and the CLI need. No model calls happen here.
"""
import dataclasses
import random

from . import checks, layout_map, layout_zone, schedule as schedule_mod, spec_writer
from .model import (ObjectTemplate, Rect, bed_capacity, green_feature_name,
                    parse_plan)


class RegionOut:
    def __init__(self, name, rect, kind, parent=None, wall=None, ground="dirt",
                 ground_texture="dirt", ambience=None, description="", doors=None,
                 group=None, ground_color=None, wall_color=None):
        self.name = name
        self.rect = rect
        self.kind = kind          # zone | road | path | yard | building | room | boundary
        self.parent = parent      # parent region name (nesting), or None
        self.wall = wall
        self.ground = ground
        self.ground_texture = ground_texture
        self.ambience = ambience
        self.description = description
        self.doors = doors or set()
        self.is_room = kind == "room"
        self.entrance_door = None
        self.group = group        # zones split into pieces share their name here
        self.ground_color = ground_color  # optional "#rrggbb" ground tint
        self.wall_color = wall_color      # optional "#rrggbb" wall tint (walled regions)


class ObjectOut:
    def __init__(self, template, pos, region):
        self.template = template
        self.pos = pos
        self.region = region


class CharOut:
    def __init__(self, person, pos, region, is_player=False):
        self.person = person
        self.name = person.name
        self.gender = person.gender
        self.pos = pos
        self.region = region
        self.schedule = []
        self.is_player = is_player


class World:
    def __init__(self):
        self.grid = (64, 64)
        self.seed = 1
        self.regions = []
        self.regions_by_name = {}
        self.zones_by_name = {}
        self.zone_pieces = {}      # zone name -> [Rect] (one per zone, except wraps)
        self.roads = []
        self.buildings = []
        self.objects = []
        self.templates = {}
        self.characters = []
        self.player = None
        self.reserved = set()
        self.failures = []
        self.fallbacks = []
        self.default_ground = ("grass", "grass")   # the plan's dominant wild ground
        self.metrics = {}
        self.map_warnings = []      # non-fatal map notes (a grid past GRID_WARN)
        self.extensions = set()
        self.zone_building_area = {}   # zone name -> placed footprint cells
        self.floors = []               # upper storeys (extensions/floors.py)
        self.portals = []              # stair portals, as arpgMods entries
        self.compounds = []            # [CompoundOut] (layout_compound.py)
        self.solid_walls = set()       # cells of intentional wall objects
        self.void_zones = set()        # zone names with exterior "void"
        self.void_default = False      # every zone void: void default tile
        self.sleep_assign = {}         # person name -> RoomOut with their bed


def _most_private_room(world, b):
    """The room a bed belongs in: one named or purposed for sleeping, else the
    room farthest from the entrance door."""
    import re
    bl = b.layout
    door = bl.entrance_door

    def score(room):
        purpose = next((r.purpose for r in bl.design.rooms
                        if r.name == room.base_name), "")
        if re.search(r"bed|chamber|sleep|private|quarter",
                     f"{room.base_name} {purpose}".lower()):
            return (2, 0.0)
        cx, cy = room.rect.center()
        return (1, float(abs(cx - door[0]) + abs(cy - door[1])))

    return max(bl.rooms, key=score)


def _bed_template(world, plan_data):
    """The catalogue's bed: the smallest template the catalogue flags
    forSleep, else the smallest its name calls a bed (a "Bedside locker" is
    furniture, not a bed), or a plain 1x2 Bed added to the plan when the
    catalogue has neither."""
    flagged = [t for t in world.templates.values()
               if t.extras.get("forSleep") is True]
    beds = flagged or [t for t in world.templates.values() if t.for_sleep]
    if beds:
        return min(beds, key=lambda t: (t.size[0] * t.size[1], t.name))
    t = ObjectTemplate(name="Bed", size=(1, 2), walkability=0.3,
                       description="A plain bed.",
                       physicalDescription="A wooden bed frame with a straw mattress.",
                       tags=["bed"], rule="against the wall of a sleeping room",
                       extras={"forSleep": True})
    world.templates[t.name] = t
    plan_data.setdefault("templates", []).append(
        {"name": t.name, "size": [1, 2], "walkability": 0.3, "forSleep": True,
         "description": t.description, "physicalDescription": t.physicalDescription,
         "tags": ["bed"], "rule": t.rule})
    return t


def _double_template(world, plan_data):
    """The catalogue's double bed: the smallest template the catalogue flags
    forSleep that sleeps two, or a plain 2x2 "Double bed" at walkability 0.3
    added to the plan when the catalogue has none."""
    doubles = [t for t in world.templates.values()
               if t.for_sleep and bed_capacity(t) == 2]
    if doubles:
        return min(doubles, key=lambda t: (t.size[0] * t.size[1], t.name))
    t = ObjectTemplate(name="Double bed", size=(2, 2), walkability=0.3,
                       description="A plain double bed.",
                       physicalDescription="A wide wooden bed frame with a straw mattress.",
                       tags=["bed"], rule="against the wall of a sleeping room",
                       extras={"forSleep": True})
    world.templates[t.name] = t
    plan_data.setdefault("templates", []).append(
        {"name": t.name, "size": [2, 2], "walkability": 0.3, "forSleep": True,
         "description": t.description, "physicalDescription": t.physicalDescription,
         "tags": ["bed"], "rule": t.rule})
    return t


def _place_bed(world, room, tmpl):
    """A free cell for one bed: against a wall, off the walkways and never
    boxing itself (or the room) in. None when the room has no room left."""
    from .layout_room import _boxed_positions, reserve_walkways
    rect = room.rect
    inter = rect.interior()
    if inter.w < tmpl.size[0] or inter.h < tmpl.size[1]:
        return None
    occupied = set()
    for (t, pos) in room.furniture.placements:
        w, h = world.templates[t].size
        occupied |= {(x, y) for x in range(pos[0], pos[0] + w)
                     for y in range(pos[1], pos[1] + h)}
    reserved, door_inner = reserve_walkways(rect, sorted(room.doors))

    def wall_dist(pos):
        return min(pos[0] - inter.x, inter.x1 - (pos[0] + tmpl.size[0] - 1),
                   pos[1] - inter.y, inter.y1 - (pos[1] + tmpl.size[1] - 1))

    cands = [(x, y) for x in range(inter.x, inter.x1 - tmpl.size[0] + 2)
             for y in range(inter.y, inter.y1 - tmpl.size[1] + 2)]
    cands.sort(key=lambda p: (wall_dist(p), p[1], p[0]))
    for pos in cands:
        fp = {(x, y) for x in range(pos[0], pos[0] + tmpl.size[0])
              for y in range(pos[1], pos[1] + tmpl.size[1])}
        if fp & occupied or fp & reserved:
            continue
        placements = [(n, p, world.templates[n].size)
                      for (n, p) in room.furniture.placements]
        placements.append((tmpl.name, pos, tmpl.size))
        if (tmpl.name, pos) not in _boxed_positions(placements, world.templates,
                                                    inter, door_inner):
            return pos
    return None


def _couples_by_home(plan):
    """The plan's couples as home name -> [[person, person], ...]: each home
    the plan says has couples pairs that many pairs of its residents, P5's
    mutual partner links first, the rest in order."""
    people_by_home = {}
    for p in plan.npcs + [plan.player]:
        people_by_home.setdefault(p.home, []).append(p)
    out = {}
    for z in plan.zones:
        for b in z.buildings:
            c = getattr(b, "couples", 0) or 0
            if c <= 0:
                continue
            residents = people_by_home.get(b.name, [])
            by_name = {p.name: p for p in residents}
            pairs, taken = [], set()
            for p in residents:                      # P5's partner links first
                q = by_name.get((p.extras or {}).get("partner") or "")
                if q is None or p.name in taken or q.name in taken:
                    continue
                if by_name.get((q.extras or {}).get("partner") or "") is p:
                    pairs.append([p, q])
                    taken |= {p.name, q.name}
            for p in residents:                      # then the rest, in order
                if len(pairs) >= c:
                    break
                if p.name in taken:
                    continue
                q = next((x for x in residents
                          if x.name not in taken and x is not p), None)
                if q is None:
                    break
                pairs.append([p, q])
                taken |= {p.name, q.name}
            out[b.name] = pairs[:c]
    return out


def _rooms_by_privacy(world, b):
    """A building's rooms (ground and uppers), most private first: one named
    or purposed for sleeping, else the farthest from the entrance door."""
    import re
    bl = b.layout
    door = bl.entrance_door

    def score(item):
        room, design = item
        purpose = next((r.purpose for r in design.rooms
                        if r.name == room.base_name), "")
        if re.search(r"bed|chamber|sleep|private|quarter",
                     f"{room.base_name} {purpose}".lower()):
            return (2, 0.0)
        cx, cy = room.rect.center()
        return (1, float(abs(cx - door[0]) + abs(cy - door[1])))

    rooms = [(r, bl.design) for r in bl.rooms]
    for f in getattr(b, "floors", []) or []:
        rooms += [(r, f.layout.design) for r in f.layout.rooms]
    return [r for (r, _d) in sorted(rooms, key=score, reverse=True)]


def _double_beds_in(world, building):
    """How many double beds a building's placed furniture holds."""
    n = sum(schedule_mod.room_doubles(world, r) for r in building.layout.rooms)
    for f in getattr(building, "floors", []) or []:
        n += sum(schedule_mod.room_doubles(world, r) for r in f.layout.rooms)
    return n


def _ensure_couple_beds(world, plan, plan_data, home_name, pairs):
    """One double bed per couple the plan promises this home, added in its
    most private room that has space when the furniture holds none (two
    single beds and a recorded failure when nothing fits a double), then the
    home's sleep assignment re-run so both partners share the double room."""
    home = next((b for b in world.buildings
                 if b.layout.design.name == home_name), None)
    if home is None:
        return
    want = getattr(home.layout.design, "couples", 0) or 0
    while _double_beds_in(world, home) < want:
        tmpl = _double_template(world, plan_data)
        placed = None
        for room in _rooms_by_privacy(world, home):
            pos = _place_bed(world, room, tmpl)
            if pos is not None:
                room.furniture.placements.append((tmpl.name, pos))
                world.objects.append(ObjectOut(tmpl.name, pos, room.full_name))
                placed = room
                break
        if placed is None:
            single = _bed_template(world, plan_data)
            room = None
            for r in _rooms_by_privacy(world, home):
                pos = _place_bed(world, r, single)
                if pos is not None:
                    r.furniture.placements.append((single.name, pos))
                    world.objects.append(ObjectOut(single.name, pos, r.full_name))
                    room = r
                    break
            names = " and ".join(p.name for pair in pairs for p in pair) or home_name
            why = f"no free cell for a double bed in {home_name}"
            if room is not None:
                why += "; one more single bed instead"
            world.failures.append((f"double bed for {names}", why))
            return
    residents = [p for p in plan.npcs + [plan.player] if p.home == home_name]
    schedule_mod.assign_sleep_rooms(world, residents,
                                    couples={home_name: pairs})


def _ensure_beds(world, plan, plan_data):
    """Every person sleeps in a bed. Couples come first: each home the plan
    says has couples gets one double bed per couple (added when its furniture
    holds none) with both partners assigned to it. Then a person the room
    assignment left without one gets a bed added at home: in the home's
    fullest bedded room when its beds are all taken (they stay home, crowded,
    when that room has no free cell), else in its most private room. A
    bedless home borrows the nearest bedded building of its household (the
    same zone) first."""
    for home_name, pairs in _couples_by_home(plan).items():
        _ensure_couple_beds(world, plan, plan_data, home_name, pairs)
    for person in plan.npcs + [plan.player]:
        if world.sleep_assign.get(person.name) is not None:
            continue   # the layout assigned them a bed of their own
        home = schedule_mod.home_building(world, person.home)
        if home is None:
            continue
        full = schedule_mod.sleep_room(world, home.layout.design.name)
        zone = schedule_mod.zone_of(world, home.layout.design.name)
        if full is None and any(
                b is not home
                and schedule_mod.zone_of(world, b.layout.design.name) == zone
                and schedule_mod.sleep_room(world, b.layout.design.name) is not None
                for b in world.buildings):
            continue   # the schedule will point at the household's bed
        room = full or _most_private_room(world, home)
        tmpl = _bed_template(world, plan_data)
        pos = _place_bed(world, room, tmpl)
        if pos is None:
            world.failures.append((f"bed for {person.name}",
                                   f"no free cell for a bed in {room.full_name}"))
            if full is not None:
                world.sleep_assign[person.name] = full   # home, over capacity
            continue
        room.furniture.placements.append((tmpl.name, pos))
        world.objects.append(ObjectOut(tmpl.name, pos, room.full_name))
        world.sleep_assign[person.name] = room


def _emit_unit_regions(world, bl, parent_name, names_seen):
    """The regions and objects of a layout's stamped unit copies (a ground
    block or a band storey): each copy a walled region under its parent,
    its own rooms nested inside, their furniture placed."""
    regions, objects = [], []
    for uo in getattr(bl, "unit_outs", []) or []:
        ul = uo.layout
        single = len(ul.rooms) == 1 and ul.rooms[0].rect == uo.rect
        ureg = RegionOut(
            uo.name, uo.rect, "building", parent=parent_name,
            wall=ul.design.wall, ground="wood", ground_texture="floorboards",
            ambience={"day": "quiet_indoor"},
            description=f"One of {parent_name}'s units.",
            doors=set(uo.doors))
        regions.append(ureg)
        for room in ul.rooms:
            room.full_name = uo.name if single else f"{uo.name} {room.base_name}"
            if room.full_name in names_seen:
                world.failures.append((f"room {room.full_name}", "duplicate name"))
            names_seen[room.full_name] = True
            amb = {"day": "quiet_indoor"}
            for (t, _p) in room.furniture.placements:
                if "light" in world.templates[t].tags and world.templates[t].walkability <= 0:
                    amb = {"day": "fireplace"}
                    break
            if single:
                ureg.ambience = amb
            else:
                regions.append(RegionOut(room.full_name, room.rect, "room",
                                         parent=uo.name, wall=ul.design.wall,
                                         ground="wood", ground_texture="floorboards",
                                         ambience=amb,
                                         description=next((r.purpose for r in ul.design.rooms
                                                           if r.name == room.base_name), "")))
            for (tname, pos) in room.furniture.placements:
                objects.append(ObjectOut(tname, pos, room.full_name))
    return regions, objects


def _seal_void_zones(world, plan, plan_data):
    """Interior-only zones (``"exterior": "void"``): everything outside the
    walled regions becomes out of bounds — walkability-0 slab objects over
    ground tinted the boundary colour, the same treatment as The World's
    Edge (passable at build so the builder's flat walk still works, hardened
    by inject_arpg_mods), and the roads to and from the zone become walled
    corridor connectors with an arm walking from the road mouth to the
    block's gate. A plan whose zones are all void gets a void default tile,
    so no walkable open ground is left anywhere."""
    from .extensions.floors import BOUNDARY_COLOR
    from .layout_map import _cells_to_rects

    voids = {z.name: z for z in plan.zones if z.exterior == "void"}
    if not voids:
        return
    world.void_zones = set(voids)
    world.void_default = all(z.exterior == "void" for z in plan.zones)

    # tint the void zones' own ground (their compound grounds too): the
    # walled regions and paths nested inside draw over it
    for r in world.regions:
        if r.name in voids and r.kind == "zone":
            r.ground_color = BOUNDARY_COLOR
        if r.kind == "compound" and r.parent in voids:
            r.ground_color = BOUNDARY_COLOR

    road_cells = set()
    for road in world.roads:
        road_cells |= road.cells()
    zone_cells = {n: set() for n in voids}
    for n, pieces in world.zone_pieces.items():
        if n in voids:
            for p in pieces:
                zone_cells[n] |= p.cells()

    _void_roads(world, plan_data, voids)
    _void_arms(world, plan_data, voids, zone_cells, road_cells)

    # the mask: every cell of a void zone that no walled region, path, yard
    # or arm covers becomes a slab (a compound's leftover ground included —
    # the gaps between a block's parts are not streets)
    keep = set()
    for r in world.regions:
        if r.wall or r.kind in ("path", "yard", "road"):
            keep |= r.rect.cells()
    for n in voids:
        mask = zone_cells[n] - keep
        _void_slabs(world, plan_data, mask, n)
    if world.void_default:
        covered = set()
        for r in world.regions:
            if r.kind != "boundary":
                covered |= r.rect.cells()
        covered |= road_cells
        _void_slabs(world, plan_data,
                    {(x, y) for x in range(world.grid[0])
                            for y in range(world.grid[1])} - covered,
                    "The Void", outside=True)


def _void_slabs(world, plan_data, cells, zone_name, outside=False):
    """Void cells as walkability-0 slab objects (one template per rect,
    passable at build): the builder's reachability walk crosses them, the
    shipped scenario hardens them and the tinted ground shows through."""
    from .extensions.floors import BOUNDARY_COLOR
    from .model import ObjectTemplate

    for i, r in enumerate(_rects_of(cells)):
        tname = f"{zone_name} Void Slab {i + 1}"
        t = ObjectTemplate(name=tname, size=(r.w, r.h), walkability=0.0,
                           description="Nothing lies this way.",
                           physicalDescription="A sealed, lightless bulk.",
                           tags=["wall"],
                           extras={"passableAtBuild": True, "maxHp": 999,
                                   "heightM": 3})
        world.templates[tname] = t
        known = {x.get("name") for x in plan_data.setdefault("templates", [])}
        if tname not in known:
            plan_data["templates"].append(
                {"name": tname, "size": [r.w, r.h], "walkability": 0.0,
                 "passableAtBuild": True, "maxHp": 999, "heightM": 3,
                 "description": t.description,
                 "physicalDescription": t.physicalDescription,
                 "tags": ["wall"], "rule": "out-of-bounds void"})
        world.objects.append(ObjectOut(tname, (r.x, r.y), zone_name))
        world.solid_walls |= r.cells()


def _rects_of(cells):
    from .layout_map import _cells_to_rects
    return _cells_to_rects(cells)


def _void_arms(world, plan_data, voids, zone_cells, road_cells):
    """One walled arm per void zone: from the road cell nearest its gate to
    the gate's outside door, a 3-wide corridor of rects under the zone,
    butting the gate's wall (an explicit facing-pair door, since their
    parents differ) and the road (an explicit door each side of the line)."""
    from .model import SIDE_DX_DY, shared_wall_cells

    # the road tubes (already corridors by now) are part of the walk's
    # starts: the BFS cannot cross their walls, but it can begin inside them
    starts = set(road_cells)
    for road in world.roads:
        if road.a not in voids and road.b not in voids:
            continue
        for r in world.regions:
            if r.name == road.name or r.name.startswith(f"{road.name} Section"):
                starts |= r.rect.cells()

    for zname in sorted(voids):
        comp = next((c for c in getattr(world, "compounds", []) or []
                     if c.compound.zone == zname and c.gates), None)
        if comp is None:
            continue
        gate = next((b for b in comp.parts
                     if b.layout.design.name == comp.gates[0].building), None)
        if gate is None:
            continue
        bl = gate.layout
        dx, dy = SIDE_DX_DY[bl.entrance_side]
        approach = (bl.entrance_door[0] + dx, bl.entrance_door[1] + dy)
        piece = next((p for p in world.zone_pieces.get(zname, [])
                      if p.contains_cell(approach)), None)
        if piece is None or not road_cells:
            continue
        # BFS from the road (and tube) cells to the gate's approach, keeping
        # one cell of clearance each side (the arm is a walled corridor: a
        # route pinched to one cell wide has no interior to walk). Zone and
        # road ground costs nothing, and neither does a compound's own open
        # ground — only its walled parts block — so the arm may cross the
        # block's margin inside its zone; the road's tube cells are starts
        # and never block the clearance test.
        covered = set()
        for r in world.regions:
            if r.kind in ("zone", "road", "compound"):
                continue
            covered |= r.rect.cells()
        W, H = world.grid

        def clear(c):
            """One cell of clearance each side: the arm is a walled corridor,
            and a route pinched to one cell wide has no interior to walk.
            Zone and road ground costs nothing, and neither does a
            compound's own open ground — only its walled parts block — so
            the arm may cross a block's margin; the tube's cells are starts
            and never block the clearance test."""
            x, y = c
            return all(0 <= x + ax < W and 0 <= y + ay < H
                       and ((x + ax, y + ay) not in covered
                            or (x + ax, y + ay) in starts)
                       for ax in (-1, 0, 1) for ay in (-1, 0, 1))

        prev = {c: None for c in starts}
        todo = list(starts)
        found = None
        while todo and found is None:
            cur = todo.pop(0)
            if cur == approach:
                found = cur
                break
            x, y = cur
            for nxt in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if not (0 <= nxt[0] < W and 0 <= nxt[1] < H):
                    continue
                if nxt in prev:
                    continue
                if nxt != approach and not clear(nxt):
                    continue
                prev[nxt] = cur
                todo.append(nxt)
        if found is None:
            world.failures.append((f"void zone {zname}",
                                   "no clear way from the road to the gate"))
            continue
        path = set()
        cur = found
        while cur is not None:
            path.add(cur)
            cur = prev[cur]
        arm = {(x + ax, y + ay) for (x, y) in path - starts
               for ax in (-1, 0, 1) for ay in (-1, 0, 1)}
        for r in world.regions:       # never over walls or roads
            if r.wall or r.kind == "road":
                arm -= r.rect.cells()
        if not arm:
            continue
        regs = []
        for i, cells in enumerate(_rects_of(arm)):
            src = RegionOut(f"{zname} Connector" + (f" {i + 1}" if i else ""),
                            cells, "building", parent=zname, wall="stone",
                            ground="stone", ground_texture="rock",
                            ambience={"day": "quiet_indoor"},
                            description=f"The sealed way into {zname}.")
            regs.extend(_split_connector(world, src))
        _seam_doors(regs)
        gate_reg = world.regions_by_name.get(bl.design.name) if hasattr(world, "regions_by_name") else None
        gate_reg = gate_reg or next(
            (r for r in world.regions if r.name == bl.design.name), None)
        if gate_reg is not None:
            # the whole seam into the gate opens: the pair the builder's own
            # rule would pick lands mid-wall, but the gate's own entrance
            # door sits elsewhere on the same wall
            _seam_doors(regs + [gate_reg])
        # every piece cell on the road line with a road cell just beyond is
        # a door onto the tube
        for reg in regs:
            r = reg.rect
            doors = set(reg.doors)
            for x in range(r.x, r.x1 + 1):
                if (x, r.y - 1) in road_cells:
                    doors.add((x, r.y))
                if (x, r.y1 + 1) in road_cells:
                    doors.add((x, r.y1))
            for y in range(r.y, r.y1 + 1):
                if (r.x - 1, y) in road_cells:
                    doors.add((r.x, y))
                if (r.x1 + 1, y) in road_cells:
                    doors.add((r.x1, y))
            reg.doors = doors
    # every tube–arm and arm–arm seam: explicit doors across each touching
    # cell pair, since their parents differ and the builder will not
    # auto-connect them
    _connector_seams(world)


def _split_connector(world, reg):
    """The builder wants every region nested in its parent or clear of it,
    and a connector (road tube or arm) straddles borders by nature. It is
    split along every zone and compound edge: each piece nests under the
    region that contains it, or stands alone in the gutter like a road.
    The first piece keeps the original name. Returns the pieces."""
    zones = [r for r in world.regions if r.kind == "zone"]
    comps = [r for r in world.regions if r.kind == "compound"]
    cells = reg.rect.cells()
    groups, taken = [], set()
    for cr in comps:
        c = cells & cr.rect.cells()
        if c:
            groups.append((cr.name, c))
            taken |= c
    for z in zones:
        c = (cells & z.rect.cells()) - taken
        if c:
            groups.append((z.name, c))
            taken |= c
    if cells - taken:
        groups.append((None, cells - taken))
    out = []
    for (parent, c) in groups:
        for r in _rects_of(c):
            out.append((parent, r))
    pieces = []
    used = {r.name for r in world.regions}
    for i, (parent, r) in enumerate(out):
        nm = reg.name if i == 0 and reg.name not in used else None
        if nm is None:
            k = 2
            nm = f"{reg.name} {k}"
            while nm in used:
                k += 1
                nm = f"{reg.name} {k}"
        used.add(nm)
        nreg = RegionOut(nm, r, "building", parent=parent, wall=reg.wall,
                         ground=reg.ground, ground_texture=reg.ground_texture,
                         ambience=reg.ambience, description=reg.description)
        nreg.doors = {c for c in reg.doors if r.contains_cell(c)} if i == 0 \
            else set()
        nreg.connector = True
        world.regions.append(nreg)
        pieces.append(nreg)
    return pieces


def _seam_doors(regs):
    """Doors across every place two of these walled regions touch: each
    adjacent cell pair becomes a door on both, so however the corridor was
    partitioned (along zone or compound borders) the walk runs end to end."""
    for i, a in enumerate(regs):
        for b in regs[i + 1:]:
            for (x, y) in a.rect.cells():
                for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if b.rect.contains_cell(n):
                        a.doors.add((x, y))
                        b.doors.add(n)


def _connector_seams(world):
    """_seam_doors over every connector pair on the map (tubes and arms)."""
    conns = [r for r in world.regions if getattr(r, "connector", False)]
    _seam_doors(conns)


def _void_roads(world, plan_data, voids):
    """The roads to and from a void zone become walled corridor connectors:
    one corridor per road rect, a mouth too thin for an interior widened to
    3 (the mouths' reserve keeps the cell it eats clear), doors on the ends
    no sibling rect continues from. Each corridor is split along the zone
    borders it straddles (_split_connector); the arms come after this and
    begin inside the tube."""
    for road in world.roads:
        if road.a not in voids and road.b not in voids:
            continue
        g, tex = road.ground
        old = [r for r in world.regions
               if r.kind == "road" and any(r.rect == s for s in road.rects)]
        for r in old:
            world.regions.remove(r)
        segs = [_widen_seg(world, s) for s in road.rects]
        for j, seg in enumerate(segs):
            name = road.name if len(segs) == 1 else f"{road.name} Section {j + 1}"
            reg = RegionOut(name, seg, "building", parent=None, wall="stone",
                            ground=g, ground_texture=tex,
                            ambience={"day": "quiet_indoor"},
                            description=f"The sealed way along {road.name}.",
                            doors=set(_free_ends(seg, segs)))
            reg.connector = True
            pieces = _split_connector(world, reg)
            _seam_doors(pieces)
            for p in pieces:
                p.doors |= {c for c in _free_ends(p.rect, [q.rect for q in pieces])
                            if p.rect.contains_cell(c)}


def _widen_seg(world, seg):
    """A road mouth 1-2 cells wide has no interior to wall: grow its thin
    side to 3 — into the gutter and one cell of whichever zone sits beyond,
    on the grid — keeping the mouth's position anchored at its start."""
    from .model import Rect

    if min(seg.w, seg.h) >= 3:
        return seg
    if seg.w < seg.h:
        x = max(0, min(seg.x, world.grid[0] - 3))
        return Rect(x, seg.y, 3, seg.h)
    y = max(0, min(seg.y, world.grid[1] - 3))
    return Rect(seg.x, y, seg.w, 3)


def _free_ends(seg, all_rects):
    """The middle cell of each of seg's edges that no sibling road rect lies
    just beyond: those ends need a door (the rest auto-connect)."""
    mids = [(seg.x + seg.w // 2, seg.y, (0, -1)),
            (seg.x + seg.w // 2, seg.y1, (0, 1)),
            (seg.x, seg.y + seg.h // 2, (-1, 0)),
            (seg.x1, seg.y + seg.h // 2, (1, 0))]
    out = []
    for (x, y, (dx, dy)) in mids:
        beyond = (x + dx, y + dy)
        if any(s != seg and s.contains_cell(beyond) for s in all_rects):
            continue
        out.append((x, y))
    return out


def _piece_direction(primary, piece):
    """The compass word for a zone piece beyond the first, from where it sits
    relative to the zone's primary piece."""
    px, py = primary.center()
    cx, cy = piece.center()
    dx, dy = cx - px, cy - py
    if abs(dx) > abs(dy) * 2:
        return "East" if dx > 0 else "West"
    if abs(dy) > abs(dx) * 2:
        return "North" if dy > 0 else "South"
    if dx > 0:
        return "NorthEast" if dy > 0 else "SouthEast"
    return "NorthWest" if dy > 0 else "SouthWest"


def run(plan_data, seed=1, extensions=()):
    import copy
    from .extensions import expand
    plan = parse_plan(plan_data)
    exts = expand(set(extensions)
                  | {e for e in plan_data.get("extensions", []) if isinstance(e, str)})

    # every attempt mutates the plan data it is handed (added templates, the
    # boundary slab's height). Each build works on its own copy and the
    # caller's dict ends up holding the winner's — a discarded pass must not
    # leave its sizes behind (a shorter slab than the strip it must cover).
    base = copy.deepcopy(plan_data)

    def attempt(weight_scale=None):
        data = copy.deepcopy(base)
        return _build_world(plan, data, seed, exts, weight_scale), data

    world, winner = attempt()
    # content sizing is a target, not a limit: a zone that dropped a building
    # or a storey grows (and the map with it) until everything the model
    # planned is placed
    growth = {}
    stalled = 0
    for _ in range(MAX_GROWTH_PASSES):
        grow = _growth_scale(plan, world, growth)
        if not grow:
            break
        # each pass compounds: a zone keeps the scale it earned even once its
        # own buildings fit (a smaller base would bring the drops back)
        growth = grow
        retry, retry_data = attempt(growth)
        if _dropped_count(retry) > _dropped_count(world):
            break   # growing lost more than it placed; keep the better build
        stalled = stalled + 1 if _dropped_count(retry) == _dropped_count(world) else 0
        world, winner = retry, retry_data
        if stalled >= MAX_STALLED_PASSES:
            break   # room isn't what it lacks, and each pass costs more than the last
    # a settlement zone sized to estimates can miss its measured building
    # coverage; one corrective pass, keeping whichever build landed closer
    # (nothing newly unplaced first, then the smaller coverage drift)
    scale = _coverage_scale(plan, world)
    if scale:
        merged = dict(growth)
        merged.update({n: growth.get(n, 1.0) * f for n, f in scale.items()})
        retry, retry_data = attempt(merged)
        if _build_score(plan, retry) < _build_score(plan, world):
            world, winner = retry, retry_data
    plan_data.clear()
    plan_data.update(winner)
    return world


GROWTH_FACTOR = 1.4     # how much a zone's content sizing grows per pass
GROWTH_ALLY = 1.15      # the other built zones grow with it, keeping their street blocks
MAX_GROWTH_PASSES = 8   # 1.4^8 is about 14x: enough for the fullest plan
MAX_STALLED_PASSES = 2  # passes in a row that placed nothing more before giving up


def _dropped_count(world):
    """How many planned buildings, storeys and zones a build dropped."""
    from .checks import dropped_failures
    return len(dropped_failures(world.failures))


def _growth_scale(plan, world, current=None):
    """{zone name: absolute factor} for zones that dropped a building, a
    storey or a compound's reachability: the zone's weight compounds until
    its content fits, so nothing planned is lost. Every other built zone
    grows with it once, not compounding — the map grows from the weight sum,
    so one zone growing alone would take the width its neighbours' street
    blocks need."""
    from .checks import dropped_failures
    current = current or {}
    zone_of = {b.name: z.name for z in plan.zones for b in z.buildings}
    zone_of.update({c.name: c.zone for c in getattr(plan, "compounds", []) or []})
    out = {}
    for (what, _reason) in dropped_failures(world.failures):
        if what.startswith("building "):
            name = what[len("building "):]
        elif what.startswith("floors of "):
            name = what[len("floors of "):]
        elif what.startswith("compound "):
            name = what[len("compound "):].split(" part ")[0].split(" wall ")[0]
        else:
            continue
        name = name.split(" [")[0]   # strip a piece label, when there is one
        zone = zone_of.get(name)
        if zone is not None:
            out[zone] = current.get(zone, 1.0) * GROWTH_FACTOR
    if out:
        for z in plan.zones:
            if z.name not in out and (z.buildings or getattr(z, "compounds", None)):
                out[z.name] = max(current.get(z.name, 1.0), GROWTH_ALLY)
        for n, f in current.items():
            out.setdefault(n, f)
    return out


def _coverage_scale(plan, world):
    """{zone name: weight multiplier} for settlement zones whose measured
    building coverage came out roomier than its target by more than a
    tenth. Zones are sized to their own measurement now, so the pass is the
    squeezer the old weight cuts were: a retry that drops content loses to
    the build score, so tightening past the measurement is always tried and
    never kept when it hurts."""
    from .model import building_coverage_target, zone_class
    scale = {}
    for z in plan.zones:
        if zone_class(z) != "settlement" or not z.buildings:
            continue
        area = sum(r.w * r.h for r in world.zone_pieces.get(z.name, []))
        built = world.zone_building_area.get(z.name, 0)
        if not area or not built:
            continue
        actual = built / float(area)
        target = building_coverage_target(z, plan.setting)
        if actual < target and target - actual > 0.1 * target:
            scale[z.name] = max(0.7, actual / target)
    return scale


def _coverage_error(plan, world):
    """The worst settlement zone's relative drift from its coverage target
    (0 when every zone is on it; large when nothing was measured)."""
    from .model import building_coverage_target, zone_class
    worst = 0.0
    measured = False
    for z in plan.zones:
        if zone_class(z) != "settlement" or not z.buildings:
            continue
        area = sum(r.w * r.h for r in world.zone_pieces.get(z.name, []))
        built = world.zone_building_area.get(z.name, 0)
        if not area or not built:
            continue
        measured = True
        actual = built / float(area)
        target = building_coverage_target(z, plan.setting)
        worst = max(worst, abs(actual - target) / target)
    return worst + (0.0 if measured else 1.0)


def _build_score(plan, world):
    """Lower is better: dropped buildings and storeys first, then unplaced
    pieces, then coverage drift."""
    from .checks import dropped_failures
    return (len(dropped_failures(world.failures)),
            len(world.metrics.get("objects", {}).get("unplaced", [])),
            _coverage_error(plan, world))


def _build_world(plan, plan_data, seed, exts, weight_scale=None):
    rng = random.Random(seed)
    world = World()
    world.seed = seed
    world.extensions = exts
    world.templates = {t.name: t for t in plan.templates}

    m = layout_map.layout_map(plan, rng, extensions=exts, weight_scale=weight_scale)
    world.grid = m.grid
    world.roads = m.roads
    world.default_ground = m.default_ground
    world.map_warnings = list(m.warnings)
    world.failures.extend(m.failures)
    world.zone_pieces = {z.name: m.zone_pieces[z.name] for z in plan.zones
                         if z.name in m.zone_pieces}

    # ---- regions: zones (one region per piece), roads, then each piece's
    # buildings, paths and props; only the primary piece carries buildings
    zone_ground = {  # P1 zone ground -> (ground, texture)
        "grass": ("grass", "grass"), "dirt": ("dirt", "dirt"),
        "gravel": ("gravel", "gravel"), "stone": ("stone", "rock"),
    }
    for z in plan.zones:
        pieces = m.zone_pieces.get(z.name) or []
        if not pieces:
            world.failures.append((f"zone {z.name}", "not placed"))
            continue
        primary = pieces[0]   # the piece its content lays out in
        world.zones_by_name[z.name] = primary
        g, tex = zone_ground.get(z.ground, ("grass", "grass"))
        for i, prect in enumerate(pieces):
            name = z.name if i == 0 else f"{z.name} {_piece_direction(primary, prect)}"
            world.regions.append(RegionOut(
                name, prect, "zone", ground=g, ground_texture=tex,
                ambience={"day": "nature_outdoors", "night": "crickets"},
                description=z.description,
                group=z.name if len(pieces) > 1 else None))
    for road in m.roads:
        g, tex = road.ground
        for i, seg in enumerate(road.rects):
            name = road.name if i == 0 else f"{road.name} Bend"
            world.regions.append(RegionOut(name, seg, "road", ground=g, ground_texture=tex,
                                           ambience={"day": "nature_outdoors", "night": "crickets"},
                                           description=f"The road from {road.a} to {road.b}."))

    names_seen = {}
    # a unit building stamps one bed per resident per copy: the catalogue's
    # bed (or a plain one added here) must exist before the zones lay out
    if any(getattr(b, "units", None) and b.units.residents
           for z in plan.zones for b in z.buildings):
        _bed_template(world, plan_data)
    for z in plan.zones:
        if z.name not in world.zones_by_name:
            continue
        pieces = m.zone_pieces[z.name]
        primary = world.zones_by_name[z.name]
        for i, prect in enumerate(pieces):
            if i == 0:
                zz = z
                piece_label = z.name
            else:
                # extra pieces carry no buildings, compounds, paths or centre
                # props; they still take the zone's filler so a wrap dresses
                # like one land
                zz = dataclasses.replace(
                    z, buildings=[], compounds=[], outdoor=[],
                    dressing=dataclasses.replace(z.dressing, props=[], paths="none"))
                piece_label = f"{z.name} {_piece_direction(primary, prect)}"
            zout = None
            if i == 0 and z.name in m.zone_layout:
                # a measured zone replays the layout the map checked it with
                inner, entry_sides = m.zone_layout[z.name]
                zout = layout_zone.replay_zone(zz, prect, world.templates, inner,
                                               entry_sides,
                                               m.zone_road_reserve.get(z.name, ()),
                                               map_ctx=m)
            else:
                zout = layout_zone.layout_zone(zz, prect, world.templates, rng,
                                               road_reserved=m.zone_road_reserve.get(z.name),
                                               map_ctx=m)
            world.reserved |= zout.reserved
            for t in zout.added_templates:   # a generic crop row, added to the plan
                if t.name not in world.templates:
                    world.templates[t.name] = t
                known = {x.get("name") for x in plan_data.setdefault("templates", [])}
                if t.name not in known:
                    plan_data["templates"].append(
                        {"name": t.name, "size": list(t.size), "walkability": t.walkability,
                         "description": t.description, "physicalDescription": t.physicalDescription,
                         "tags": list(t.tags), "rule": t.rule})
            if i == 0:   # the primary piece carries the zone's buildings
                world.zone_building_area[z.name] = sum(
                    b.layout.rect.w * b.layout.rect.h for b in zout.buildings)
            world.failures.extend([(w, r) if i == 0 else (f"{w} [{piece_label}]", r)
                                   for (w, r) in zout.failures])
            world.fallbacks.extend(zout.fallbacks)
            if zout.spine_rects:
                g, tex = zout.spine_ground
                # the street leads the spine regions, so on a size tie the zone's
                # dominant path is the one found first
                spine = sorted(zout.spine_rects, key=lambda r: r != zout.street)
                for j, seg in enumerate(spine):
                    pname = f"{piece_label} Path" if j == 0 else f"{piece_label} Path {j + 1}"
                    world.regions.append(RegionOut(pname, seg, "path", parent=z.name,
                                                   ground=g, ground_texture=tex,
                                                   ambience={"day": "nature_outdoors", "night": "crickets"},
                                                   description=f"The path through {z.name}."))
            if zout.feature is not None:
                fg, ftex = zout.spine_ground if zout.spine_rects else \
                    zone_ground.get(z.ground, ("grass", "grass"))
                fname, fdesc = f"{z.name} Square", f"The open heart of {z.name}."
                if zz.arrangement == "around_green":
                    # the arrangement's centre is a green: named for the
                    # zone's own green or common when it has one, and grass
                    # underfoot whatever its paths are made of
                    fg, ftex = ("grass", "grass")
                    fname, fdesc = green_feature_name(zz), f"The green heart of {zz.name}."
                world.regions.append(RegionOut(fname, zout.feature, "square", parent=z.name,
                                               ground=fg, ground_texture=ftex,
                                               ambience={"day": "nature_outdoors", "night": "crickets"},
                                               description=fdesc))
            for (fname, frect) in zout.fields:
                world.regions.append(RegionOut(fname, frect, "field", parent=z.name,
                                               ground="dirt", ground_texture="dirt",
                                               ambience={"day": "nature_outdoors", "night": "crickets"},
                                               description=f"Crop plots of {z.name}."))
            for (yard_name, yard_rect, _bname) in zout.yards:
                world.regions.append(RegionOut(yard_name, yard_rect, "yard", parent=z.name,
                                               ground="dirt", ground_texture="dirt",
                                               ambience={"day": "nature_outdoors", "night": "crickets"},
                                               description=f"The yard of {_bname}."))
            for comp in zout.compounds:
                world.compounds.append(comp)
                world.regions.append(RegionOut(
                    comp.name, comp.rect, "compound", parent=z.name,
                    ground=g, ground_texture=tex,
                    ambience={"day": "nature_outdoors", "night": "crickets"},
                    description=f"The grounds of {comp.name}."))
                for i, corridor in enumerate(comp.corridors):
                    world.regions.append(RegionOut(
                        corridor.name, corridor.rect, "building", parent=comp.name,
                        wall=corridor.wall, ground=g, ground_texture=tex,
                        ambience={"day": "nature_outdoors", "night": "crickets"},
                        description=f"The wall of {comp.name}."))
                for i, strip in enumerate(comp.wall_strips):
                    tname = f"{comp.name} Wall Section {i + 1}"
                    t = ObjectTemplate(name=tname, size=tuple(strip.size),
                                       walkability=0.0,
                                       description=f"The wall of {comp.name}.",
                                       physicalDescription="A high, sheer wall.",
                                       tags=["wall"],
                                       extras={"maxHp": 999, "heightM": 3})
                    world.templates[tname] = t
                    known = {x.get("name") for x in plan_data.setdefault("templates", [])}
                    if tname not in known:
                        plan_data["templates"].append(
                            {"name": tname, "size": list(strip.size),
                             "walkability": 0.0, "maxHp": 999, "heightM": 3,
                             "description": t.description,
                             "physicalDescription": t.physicalDescription,
                             "tags": ["wall"], "rule": "the compound's outer wall"})
                    world.objects.append(ObjectOut(tname, strip.pos, comp.name))
                    world.solid_walls |= {
                        (x, y) for x in range(strip.pos[0], strip.pos[0] + strip.size[0])
                        for y in range(strip.pos[1], strip.pos[1] + strip.size[1])}
                for j, pr in enumerate(comp.paths):
                    world.regions.append(RegionOut(
                        f"{comp.name} Path" + (f" {j + 1}" if j else ""), pr,
                        "path", parent=comp.name, ground="dirt", ground_texture="dirt",
                        ambience={"day": "nature_outdoors", "night": "crickets"},
                        description=f"The path through {comp.name}."))
                if comp.front_rect is not None and comp.front_kind != "none":
                    # a row's front strip: walkable ground (a street or
                    # walkway) or a paved yard with parked vehicles
                    fname = f"{comp.name} Front"
                    if comp.parking is not None:
                        fname, frect = comp.parking[0], comp.parking[1]
                        world.regions.append(RegionOut(
                            fname, frect, "yard", parent=comp.name,
                            ground="stone", ground_texture="flagstone-light",
                            ambience={"day": "nature_outdoors", "night": "crickets"},
                            description=f"The yard in front of {comp.name}."))
                        for (tname, pos) in comp.parking[2]:
                            world.objects.append(ObjectOut(tname, pos, fname))
                            tw, th = world.templates[tname].size
                            world.solid_walls |= {
                                (x, y) for x in range(pos[0], pos[0] + tw)
                                for y in range(pos[1], pos[1] + th)}
                    else:
                        fg, ftex = ("stone", "cobblestone") if comp.front_kind == "street" \
                            else ("gravel", "gravel")
                        world.regions.append(RegionOut(
                            fname, comp.front_rect, "path", parent=comp.name,
                            ground=fg, ground_texture=ftex,
                            ambience={"day": "nature_outdoors", "night": "crickets"},
                            description=f"The way along the front of {comp.name}."))
            for b in zout.buildings:
                bl = b.layout
                design = bl.design
                building_name = design.name
                world.buildings.append(b)
                breg = RegionOut(
                    building_name, bl.rect, "building",
                    parent=b.compound or z.name, wall=design.wall,
                    ground="wood", ground_texture="floorboards",
                    ambience={"day": "quiet_indoor"}, description=design.purpose,
                    doors={bl.entrance_door} | set(getattr(bl, "extra_doors", []) or ()))
                world.regions.append(breg)
                single = len(bl.rooms) == 1 and bl.rooms[0].rect == bl.rect
                for room in bl.rooms:
                    room.full_name = building_name if single else f"{building_name} {room.base_name}"
                    if room.full_name in names_seen:
                        world.failures.append((f"room {room.full_name}", "duplicate name"))
                    names_seen[room.full_name] = True
                    # rooms with a hearth or forge get fireplace ambience
                    amb = {"day": "quiet_indoor"}
                    for (t, _p) in room.furniture.placements:
                        if "light" in world.templates[t].tags and world.templates[t].walkability <= 0:
                            amb = {"day": "fireplace"}
                            break
                    if single:
                        # one room: the building region doubles as the room; an
                        # equal-sized child region would duplicate its name
                        breg.ambience = amb
                    else:
                        reg = RegionOut(room.full_name, room.rect, "room", parent=building_name,
                                        wall=design.wall, ground="wood", ground_texture="floorboards",
                                        ambience=amb,
                                        description=next((r.purpose for r in design.rooms
                                                          if r.name == room.base_name), ""))
                        reg.entrance_door = bl.entrance_door if (bl.entrance_room is room) else None
                        world.regions.append(reg)
                    for (tname, pos) in room.furniture.placements:
                        world.objects.append(ObjectOut(tname, pos, room.full_name))
                uregs, uobjs = _emit_unit_regions(world, bl, building_name, names_seen)
                world.regions.extend(uregs)
                world.objects.extend(uobjs)
            for prop in zout.props:
                world.objects.append(ObjectOut(prop.template, prop.pos, prop.region))

    # ---- upper storeys (the floors extension): placed once the zones have
    # set the play area, in a band beyond it, so the stairs and openings
    # exist before the schedules pick where people sleep
    _seal_void_zones(world, plan, plan_data)
    if "floors" in exts:
        from .extensions import floors as floors_ext
        floors_ext.apply(world, plan_data, rng)

    world.regions_by_name = {r.name: r for r in world.regions}
    if len(world.regions_by_name) != len(world.regions):
        dupes = [r.name for r in world.regions if [x.name for x in world.regions].count(r.name) > 1]
        world.failures.append(("regions", f"duplicate region names: {sorted(set(dupes))}"))

    # ---- everyone sleeps in a bed, before the schedules pick the rooms
    schedule_mod.assign_sleep_rooms(world, plan.npcs + [plan.player],
                                    couples=_couples_by_home(plan))
    _ensure_beds(world, plan, plan_data)

    # ---- people: schedules from home and work, start cells on cells that
    # are actually reachable from the roads (filler can seal off pockets)
    openings = checks.compute_openings(world)
    blocked, _doors = checks.walkability_grid(world, openings)
    starts = set()
    for road in world.roads:
        starts |= road.cells()
    starts |= world.reserved
    connected = checks.flood(world, starts, blocked)
    taken = set()
    schedules = schedule_mod.plan_schedules(world, plan.npcs + [plan.player])
    for person in plan.npcs + [plan.player]:
        is_player = person is plan.player
        sched, start_region = schedules[person.name]
        pos, start_region = schedule_mod.start_cell(world, start_region, taken, connected)
        if pos is None:
            world.failures.append((f"character {person.name}", f"no free cell in {start_region}"))
            pos = (world.grid[0] // 2, world.grid[1] // 2)
        taken.add(pos)
        c = CharOut(person, pos, start_region, is_player)
        c.schedule = sched
        world.characters.append(c)
        if is_player:
            world.player = c

    checks.run_checks(world)
    return world


def build_spec(world, plan_data):
    plan = parse_plan(plan_data)
    return spec_writer.build_spec(world, plan)
