"""worldgen: deterministic, seeded code layout for Roleplay Anywhere scenarios.

`run(plan_dict, seed)` executes the whole pipeline (map -> zones -> buildings ->
rooms -> people -> checks) and returns a World with everything the spec writer
and the CLI need. No model calls happen here.
"""
import dataclasses
import random

from . import checks, layout_map, layout_zone, schedule as schedule_mod, spec_writer
from .model import ObjectTemplate, Rect, parse_plan


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
        self.extensions = set()
        self.zone_building_area = {}   # zone name -> placed footprint cells
        self.floors = []               # upper storeys (extensions/floors.py)
        self.portals = []              # stair portals, as arpgMods entries


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
    """The catalogue's bed: the smallest sleep template, or a plain 1x2 Bed
    added to the plan when the catalogue has none."""
    beds = [t for t in world.templates.values() if t.for_sleep]
    if beds:
        return min(beds, key=lambda t: (t.size[0] * t.size[1], t.name))
    t = ObjectTemplate(name="Bed", size=(1, 2), walkability=0.0,
                       description="A plain bed.",
                       physicalDescription="A wooden bed frame with a straw mattress.",
                       tags=["bed"], rule="against the wall of a sleeping room",
                       extras={"forSleep": True})
    world.templates[t.name] = t
    plan_data.setdefault("templates", []).append(
        {"name": t.name, "size": [1, 2], "walkability": 0.0, "forSleep": True,
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


def _ensure_beds(world, plan, plan_data):
    """Every person sleeps in a bed. A home whose building has no sleep object
    borrows the nearest bedded building of its household (the same zone); when
    the household has none, one bed is added to the home's most private room."""
    for person in plan.npcs + [plan.player]:
        home = next((b for b in world.buildings
                     if b.layout.design.name == person.home), None)
        if home is None or schedule_mod.sleep_room(world, person.home) is not None:
            continue
        zone = schedule_mod.zone_of(world, person.home)
        if any(b is not home
               and schedule_mod.zone_of(world, b.layout.design.name) == zone
               and schedule_mod.sleep_room(world, b.layout.design.name) is not None
               for b in world.buildings):
            continue   # the schedule will point at the household's bed
        room = _most_private_room(world, home)
        tmpl = _bed_template(world, plan_data)
        pos = _place_bed(world, room, tmpl)
        if pos is None:
            world.failures.append((f"bed for {person.name}",
                                   f"no free cell for a bed in {room.full_name}"))
            continue
        room.furniture.placements.append((tmpl.name, pos))
        world.objects.append(ObjectOut(tmpl.name, pos, room.full_name))


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
    for _ in range(MAX_GROWTH_PASSES):
        grow = _growth_scale(plan, world)
        if not grow:
            break
        # each pass compounds: a zone keeps the scale it earned even once its
        # own buildings fit (a smaller base would bring the drops back)
        growth = dict(growth)
        for n, f in grow.items():
            growth[n] = growth.get(n, 1.0) * f
        retry, retry_data = attempt(growth)
        if _dropped_count(retry) > _dropped_count(world):
            break   # growing lost more than it placed; keep the better build
        world, winner = retry, retry_data
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
MAX_GROWTH_PASSES = 8   # 1.4^8 is about 14x: enough for the fullest plan


def _dropped_count(world):
    """How many planned buildings, storeys and zones a build dropped."""
    from .checks import dropped_failures
    return len(dropped_failures(world.failures))


def _growth_scale(plan, world):
    """{zone name: factor} for zones that dropped a building or a storey: the
    zone's weight grows until its content fits, so nothing planned is lost."""
    from .checks import dropped_failures
    zone_of = {b.name: z.name for z in plan.zones for b in z.buildings}
    out = {}
    for (what, _reason) in dropped_failures(world.failures):
        if what.startswith("building "):
            name = what[len("building "):]
        elif what.startswith("floors of "):
            name = what[len("floors of "):]
        else:
            continue
        name = name.split(" [")[0]   # strip a piece label, when there is one
        zone = zone_of.get(name)
        if zone is not None:
            out[zone] = GROWTH_FACTOR
    return out


def _coverage_scale(plan, world):
    """{zone name: weight multiplier} for settlement zones whose measured
    building coverage missed its target by more than a fifth."""
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
        if abs(actual - target) > 0.2 * target:
            scale[z.name] = min(1.5, max(0.7, actual / target))
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
        primary = max(pieces, key=lambda r: (r.w * r.h, r.x, r.y))
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
                # extra pieces carry no buildings, paths or centre props; they
                # still take the zone's filler so a wrap dresses like one land
                zz = dataclasses.replace(
                    z, buildings=[], outdoor=[],
                    dressing=dataclasses.replace(z.dressing, props=[], paths="none"))
                piece_label = f"{z.name} {_piece_direction(primary, prect)}"
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
                fg, ftex = zout.spine_ground if zout.spine_rects else zone_ground.get(z.ground, ("grass", "grass"))
                world.regions.append(RegionOut(f"{z.name} Square", zout.feature, "square", parent=z.name,
                                               ground=fg, ground_texture=ftex,
                                               ambience={"day": "nature_outdoors", "night": "crickets"},
                                               description=f"The open heart of {z.name}."))
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
            for b in zout.buildings:
                bl = b.layout
                design = bl.design
                building_name = design.name
                world.buildings.append(b)
                breg = RegionOut(
                    building_name, bl.rect, "building", parent=z.name, wall=design.wall,
                    ground="wood", ground_texture="floorboards",
                    ambience={"day": "quiet_indoor"}, description=design.purpose,
                    doors={bl.entrance_door})
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
            for prop in zout.props:
                world.objects.append(ObjectOut(prop.template, prop.pos, prop.region))

    # ---- upper storeys (the floors extension): placed once the zones have
    # set the play area, in a band beyond it, so the stairs and openings
    # exist before the schedules pick where people sleep
    if "floors" in exts:
        from .extensions import floors as floors_ext
        floors_ext.apply(world, plan_data, rng)

    world.regions_by_name = {r.name: r for r in world.regions}
    if len(world.regions_by_name) != len(world.regions):
        dupes = [r.name for r in world.regions if [x.name for x in world.regions].count(r.name) > 1]
        world.failures.append(("regions", f"duplicate region names: {sorted(set(dupes))}"))

    # ---- everyone sleeps in a bed, before the schedules pick the rooms
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
    for person in plan.npcs + [plan.player]:
        is_player = person is plan.player
        sched, start_region = schedule_mod.make_schedule(world, person)
        pos = schedule_mod.free_cell(world, start_region, taken, connected)
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
