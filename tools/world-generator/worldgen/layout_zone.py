"""Buildings, yards, paths and outdoor props in one zone.

Settlement zones get a street network: a main street runs the zone's long
axis, 1-3 side streets cross it, and the buildings fill the blocks between
them on both sides of every street, so their spread covers the zone rather
than one street's edge. Urban districts get narrow alleys (1-2 cells) and
buildings that share walls along the streets; villages get wide lanes and
room for yards. The square or green sits at the main crossroads, among the
buildings. Other zones keep a single path spine: farmland lanes between the
road entries. A wild zone with nothing in it gets one track between its road
mouths, or no path at all when it has fewer than two. Outdoor props and
filler then spread over the remaining free ground, clear of paths, doors and
yards, to a density scaled by the setting.
"""
import dataclasses
import random
import re
from collections import deque

from . import layout_compound
from .exits import add_exits, solid_ground
from .hints import parse as parse_hint
from .layout_building import building_footprint, layout_building
from .layout_room import layout_room
from .layout_map import _cells_to_rects
from .model import (OPPOSITE_SIDE, ObjectTemplate, Rect, SIDE_DX_DY,
                    is_town_zone, is_urban_zone, zone_class)

ZONE_SIZES = {"small": (26, 20), "medium": (34, 26), "large": (42, 32), "huge": (52, 40)}
DENSITY_PER_100 = {"low": 2.0, "medium": 4.0, "high": 6.0}
SETTING_DENSITY_SCALE = {"sparse": 0.6, "normal": 1.0, "dense": 1.4}
YARD_DEPTH = 5
LOT_SPACING = 2   # minimum gap between lots, in cells
PATH_WIDTH = 3
ALLEY_MIN, ALLEY_MAX = 1, 2     # urban side streets
LANE_WIDTH = 3                  # village side streets
MAX_SIDE_STREETS = 3
FIELDS_FIT_BUMP = 2 * 10 * 7 + 8   # the two smallest crop plots, with their tracks


def lot_spacing(zone):
    """The least gap between two lots: urban buildings share walls, town
    buildings stand a cell apart, villages breathe."""
    if is_urban_zone(zone):
        return 0
    if is_town_zone(zone):
        return 1
    return LOT_SPACING


def lot_gap(zone):
    """(lo, hi) gap between consecutive lots along a street."""
    if is_urban_zone(zone):
        return (0, 1)
    if is_town_zone(zone):
        return (1, 3)
    return (2, 5)


def side_street_count(long_side, n_buildings):
    """0-3 side streets by zone size and building count: a hamlet of one or
    two buildings keeps just its main street, there is nothing for a side
    street to lead to."""
    if n_buildings < 3:
        return 0
    k = 1
    if long_side >= 34 or n_buildings >= 5:
        k += 1
    if long_side >= 48 and n_buildings >= 7:
        k += 1
    return min(MAX_SIDE_STREETS, k)


class Placement:
    def __init__(self, template, pos, region):
        self.template = template
        self.pos = pos
        self.region = region   # region name the piece belongs to


def _ring_loop(fp):
    """The cells just outside a footprint, in order round it."""
    x0 = min(c[0] for c in fp) - 1
    x1 = max(c[0] for c in fp) + 1
    y0 = min(c[1] for c in fp) - 1
    y1 = max(c[1] for c in fp) + 1
    return ([(x, y0) for x in range(x0, x1)] + [(x1, y) for y in range(y0, y1)]
            + [(x, y1) for x in range(x1, x0, -1)] + [(x0, y) for y in range(y1, y0, -1)])


def _splits_ground(fp, blocked, rect):
    """Would something solid here join two separate obstacles? Walking round
    it, the free cells must form one unbroken run: two runs mean it closes a
    gap, and the ground either side of it no longer meets there. A piece may
    stand alone or lean on one obstacle, so open ground keeps its shape however
    many pieces go down."""
    shut = [c in blocked or not rect.contains_cell(c) for c in _ring_loop(fp)]
    return sum(1 for i, s in enumerate(shut) if s and not shut[i - 1]) > 1


class BuildingOut:
    def __init__(self, layout, lot, yard_rect):
        self.layout = layout      # BuildingLayout
        self.lot = lot            # Rect: building + yard bounding box
        self.yard_rect = yard_rect
        self.floors = []          # upper storeys (extensions/floors.py fills this)
        self.compound = None      # compound name when this building is a part


class ZoneOut:
    def __init__(self, zone, rect):
        self.zone = zone
        self.rect = rect
        self.street = None        # the main path Rect the buildings line
        self.side_streets = []    # perpendicular street Rects (settlement grid)
        self.grid_vertical = False
        self.spine_rects = []     # street + side streets + entry arms, all disjoint
        self.spine_ground = ("dirt", "dirt")
        self.feature = None       # the square at the main crossroads
        self.buildings = []       # [BuildingOut]
        self.compounds = []       # [CompoundOut]
        self.yards = []           # [(name, Rect, building_name)]
        self.props = []           # [Placement] outdoor props (props + yard props + filler)
        self.fields = []          # [(name, Rect)] field plots (agricultural zones)
        self.field_cells = set()  # every cell of those plots, crops and furrows
        self.added_templates = [] # templates laid out of nothing (a generic crop row)
        self.reserved = set()     # path + branch + entrance approach cells
        self.failures = []        # (what, reason) strings
        self.fallbacks = []       # hints that could not be met, placed anywhere free
        self.side_exits = []      # (building or complex, room, cell) added by exits.py
        self.ground_blocked = set()  # what stands on the open ground (see _splits_ground)
        self.solid_props = set()  # cells of the solid props placed so far


def _yard_rect(building_rect, design):
    """The yard rect on the design's yard side (front = entrance side, back =
    opposite). The yard extends the building's cross-section by one cell each
    way and sits flush against the building."""
    side = design.yard.side if design.yard else None
    if side == "front":
        side = design.entrance_side
    elif side == "back":
        side = OPPOSITE_SIDE[design.entrance_side]
    elif side == "left":
        # facing out through the entrance, left hand side
        side = {"north": "west", "east": "north", "south": "east", "west": "south"}[design.entrance_side]
    elif side == "right":
        side = {"north": "east", "east": "south", "south": "west", "west": "north"}[design.entrance_side]
    if side in ("north", "south"):
        yard = Rect(building_rect.x - 1, building_rect.y1 + 1 if side == "north" else building_rect.y - YARD_DEPTH,
                    building_rect.w + 2, YARD_DEPTH)
    else:
        yard = Rect(building_rect.x1 + 1 if side == "east" else building_rect.x - YARD_DEPTH,
                    building_rect.y - 1, YARD_DEPTH, building_rect.h + 2)
    return yard


def _lot_rect(building_rect, yard_rect):
    if yard_rect is None:
        return building_rect
    x0 = min(building_rect.x, yard_rect.x)
    y0 = min(building_rect.y, yard_rect.y)
    x1 = max(building_rect.x1, yard_rect.x1)
    y1 = max(building_rect.y1, yard_rect.y1)
    return Rect(x0, y0, x1 - x0 + 1, y1 - y0 + 1)


def layout_zone(zone, rect, templates, rng, road_reserved=None, map_ctx=None):
    """Lay out one zone inside `rect`. road_reserved are zone-edge cells facing
    roads that must stay clear. Returns a ZoneOut."""
    out = ZoneOut(zone, rect)
    out.reserved |= set(road_reserved or ())
    density_scale = getattr(map_ctx, "density_scale", 1.0) if map_ctx is not None else 1.0
    compounds = list(getattr(zone, "compounds", None) or [])
    mouths = _mouth_clusters(rect, set(road_reserved or ()))

    # ---- the path: settlement zones get a street grid (main street plus
    # side streets, square at the crossroads); a zone that asks for it gets
    # one green ringed by its path instead; a fields zone gets farm lanes
    # whatever its kind; an empty wild zone gets one track between its road
    # mouths or none at all; other zones get one spine. A void zone has no
    # open ground to dress: everything walkable is inside walls, so it gets
    # no paths at all (the roads become walled connectors instead).
    if zone.exterior != "void" and zone.dressing.paths != "none":
        out.spine_ground = {"dirt": ("dirt", "dirt"), "cobble": ("stone", "cobblestone"),
                            "paved": ("stone", "flagstone-light")}.get(zone.dressing.paths, ("dirt", "dirt"))
        widest = (0, 0)
        for d in zone.buildings:
            fw, fh = building_footprint(d, templates)
            widest = (max(widest[0], fw), max(widest[1], fh))
        for c in compounds:
            fw, fh = layout_compound.compound_footprint(zone, c, templates)
            widest = (max(widest[0], fw), max(widest[1], fh))
        green_ring = None
        if zone.arrangement == "around_green":
            green_ring, rects, green = _green_ring(zone, rect, mouths, rng,
                                                   is_urban_zone(zone), templates)
        if green_ring is not None:
            out.street, out.spine_rects, out.feature = green_ring, rects, green
            out.grid_vertical = green_ring.h >= green_ring.w
        elif zone.arrangement != "fields" and zone_class(zone) == "wild" \
                and not zone.buildings and not compounds:
            out.street, out.spine_rects = _wild_track(rect, mouths)
            out.grid_vertical = out.street is not None and out.street.h >= out.street.w
        elif zone.arrangement != "fields" and \
                (zone_class(zone) == "settlement" or zone.arrangement == "along_street"):
            street, rects, square, sides = _settlement_streets(
                zone, rect, set(out.reserved), rng, widest, is_urban_zone(zone))
            # a zone too small for its green falls back to the street grid,
            # and keeps no centre feature: the green is the arrangement's own
            out.street, out.spine_rects, out.feature = street, rects, \
                (square if zone.arrangement != "around_green" else None)
            out.side_streets = sides
            out.grid_vertical = street is not None and street.h >= street.w
        else:
            out.street, out.spine_rects = _main_path(
                zone, rect, set(out.reserved), rng, widest,
                hug_road=zone.arrangement == "fields")
        for r in out.spine_rects:
            out.reserved |= r.cells()

    # ---- buildings fill the blocks (furniture laid out and checked as part
    # of placing each one, so a bad rotation can be undone); compounds go
    # in first, each as one block the other buildings pack around
    _place_buildings(zone, rect, out, rng, templates, mouths)

    # ---- side doors, before anything is put down outside them
    add_exits(out, templates)
    out.ground_blocked = solid_ground(out)

    # ---- branches: reserved cells from each entrance approach to the path.
    # A compound part's courtyard-facing entrance is reached through the
    # gate, not through the walls, so only the gates get a branch; every
    # branch walks round the compound blocks, never through them.
    path_cells = set()
    for r in out.spine_rects:
        path_cells |= r.cells()
    buildings_cells = set()
    for b in out.buildings:
        buildings_cells |= b.layout.rect.cells()
    block_cells = set()
    for comp in out.compounds:
        block_cells |= comp.rect.cells()
    gate_parts = {g.building for comp in out.compounds for g in comp.gates}
    for b in out.buildings:
        bl = b.layout
        if b.compound is not None and bl.design.name not in gate_parts:
            continue
        dx, dy = SIDE_DX_DY[bl.entrance_side]
        door = bl.entrance_door
        approach = (door[0] + dx, door[1] + dy)
        out.reserved.add(approach)
        if path_cells:
            out.reserved |= _route_branch(approach, path_cells, out.rect,
                                          buildings_cells | block_cells, b)

    # ---- crop fields: agricultural zones (and any zone that asks for the
    # fields arrangement) get fenced plots with crop rows
    if zone.exterior != "void" and \
            (zone_class(zone) == "agricultural" or zone.arrangement == "fields"):
        _place_fields(zone, rect, out, rng, templates, map_ctx)

    # ---- outdoor props (yard props first, then the zone's own props); a
    # void zone has no open ground for them
    occupied = set()
    for b in out.buildings:
        for room in b.layout.rooms:
            for (name, pos) in room.furniture.placements:
                w, h = room.furniture.size_of(name, pos, templates)
                occupied |= {(x, y) for x in range(pos[0], pos[0] + w) for y in range(pos[1], pos[1] + h)}
    occupied |= out.field_cells

    def building_index():
        return {b.layout.design.name: (b.layout.rect, b.layout.entrance_side) for b in out.buildings}

    for (yard_name, yard_rect, bname) in out.yards:
        if zone.exterior == "void":
            continue
        design = next(d for d in zone.buildings if d.name == bname)
        for prop in design.yard_props:
            _place_props(out, prop, yard_rect, templates, rng, occupied, building_index(),
                         area_name=yard_name, zone=zone)
    for prop in zone.dressing.props:
        if zone.exterior == "void":
            break
        _place_props(out, prop, rect, templates, rng, occupied, building_index(),
                     area_name=zone.name, zone=zone, buildings_cells=buildings_cells)

    # ---- filler to the density target, scaled by the setting's density
    # (never on void ground)
    feature_cells = out.feature.cells() if out.feature is not None else set()
    free_of_props = set(occupied)
    for f in zone.dressing.filler if zone.exterior != "void" else ():
        if f.template not in templates:
            out.failures.append((f"filler {f.template}", "unknown template"))
            continue
        tmpl = templates[f.template]
        target = round(rect.w * rect.h / 100.0
                       * DENSITY_PER_100.get(f.density, 2.0) * density_scale)
        yard_cells = set()
        for (_n, yr, _b) in out.yards:
            yard_cells |= yr.cells()
        w, h = tmpl.size
        candidates = [(x, y) for x in range(rect.x, rect.x1 - w + 2)
                      for y in range(rect.y, rect.y1 - h + 2)]
        rng.shuffle(candidates)
        props_and_filler = set(occupied)
        count = 0
        for pos in candidates:
            if count >= target:
                break
            fp = {(cx, cy) for cx in range(pos[0], pos[0] + w) for cy in range(pos[1], pos[1] + h)}
            ring = {(cx, cy) for cx in range(pos[0] - 1, pos[0] + w + 1)
                    for cy in range(pos[1] - 1, pos[1] + h + 1)}
            if fp & out.reserved or fp & buildings_cells or fp & yard_cells:
                continue
            if fp & feature_cells:
                continue
            if fp & out.field_cells:
                continue
            if fp & free_of_props:
                continue
            # one clear cell around props and buildings keeps them approachable;
            # filler may pack against other filler (it never seals a reserved path)
            if ring & props_and_filler or ring & buildings_cells:
                continue
            if tmpl.walkability <= 0:
                if _splits_ground(fp, out.ground_blocked, rect):
                    continue
                out.ground_blocked |= fp
            free_of_props |= fp
            out.props.append(Placement(f.template, pos, zone.name))
            count += 1
        if count < target:
            out.failures.append((f"filler {f.template}", f"placed {count} of {target} (zone full)"))
    return out


# ------------------------------------------------------------------ measuring

MEASURE_MARGIN = 2        # cells of slack for the zone's own paths and dressing
MEASURE_TRIES = 12        # frames tried, each bigger, before giving up growing
MEASURE_TIGHTEN = 6       # frames tried, each smaller, after one fits
REPLAY_TRIES = 4          # inner seeds a measured zone tries in its final rect
SCAN_FURNISH_SPOTS = 24   # spots whose rooms fail to furnish before a scan settles


def _entry_mouths(w, h, sides, rng):
    """Road-mouth cells on the given sides of a w x h frame, one 3-wide
    mouth per side at a seeded position in its middle half: what the map's
    roads will leave on those sides."""
    cells = set()
    for s in dict.fromkeys(x for x in sides if x in SIDE_DX_DY):
        if s in ("west", "east"):
            a = rng.randint(max(1, h // 4), max(2, min(h - 2, (3 * h) // 4)))
            cells |= ({(0, a + d) for d in (-1, 0, 1)} if s == "west"
                      else {(w - 1, a + d) for d in (-1, 0, 1)})
        else:
            a = rng.randint(max(1, w // 4), max(2, min(w - 2, (3 * w) // 4)))
            cells |= ({(a + d, 0) for d in (-1, 0, 1)} if s == "south"
                      else {(a + d, h - 1) for d in (-1, 0, 1)})
    return cells


def replay_zone(zone, rect, templates, inner, entry_sides, road_reserve=(),
                map_ctx=None):
    """Lay a measured zone out in its placed rect with the inner seed it was
    measured with, mouths synthesized on the same entry sides (the map's real
    road mouths stay reserved besides). The real mouths can still tip a tight
    frame, so a layout that loses content tries a few more inner seeds in the
    same rect. Returns the ZoneOut."""
    zout = None
    for k in range(REPLAY_TRIES):
        zrng = random.Random(inner ^ (k * 0x9E3779B1))
        mouths = {(x + rect.x, y + rect.y) for (x, y)
                  in _entry_mouths(rect.w, rect.h, entry_sides, zrng)}
        reserved = set(road_reserve) | mouths
        zout = layout_zone(zone, rect, templates, zrng, road_reserved=reserved,
                           map_ctx=map_ctx)
        if not any("no space in zone" in r for (_w, r) in zout.failures):
            break
    return zout


def measure_zone(zone, templates, rng, entry_sides=(), scale=1.0, probe=None):
    """(w, h) the zone's real layout needs, measured by laying it out: the
    zone runs in a local frame at the size its content is estimated at
    (``scale`` inflates that start — the growth passes' second chance),
    with road mouths on ``entry_sides`` (the sides its roads arrive on, so
    gates and streets face the way they will on the map). A frame that
    cannot hold the content grows until everything places, and the size
    that held it — plus a margin for the zone's own paths and dressing —
    is the measurement, never below the content minimums. A zone with
    nothing to build is not measured (None): it fills the space left over.

    Every attempt lays the zone out with the same inner seed, so the same
    rng state always measures the same size. ``probe``, when given, learns
    that seed: the map replays the layout it measured with it."""
    from .layout_map import (FIT_SLACK, MIN_ZONE_SIDE, _lightly_built,
                             _loose_blocks, _zone_fit, _zone_mins)
    if not (zone.buildings or getattr(zone, "compounds", None)):
        return None
    seed = rng.randrange(1 << 30)
    if probe is not None:
        probe["seed"] = seed
    fit = _zone_fit(zone, templates)
    mins = _zone_mins(zone, templates)
    loose, blocks = _loose_blocks(zone, templates)
    # a blocks-only zone's fit (or a lone building's one placement) is a
    # measurement already: trust it at full size; a loose packing's fit is
    # an estimate that runs hot, so the search starts below it
    slack = 1.0 if ((blocks and not loose) or _lightly_built(zone, templates)) \
        else FIT_SLACK
    w = max(MIN_ZONE_SIDE, mins[0], int(round(fit[1] * slack * scale)))
    h = max(MIN_ZONE_SIDE, mins[1], int(round(fit[2] * slack * scale)))
    want_buildings = len(zone.buildings)
    want_compounds = len(getattr(zone, "compounds", None) or [])

    def places(w, h, inner_seed):
        """One seeded layout at this frame size: everything placed?"""
        lrng = random.Random(inner_seed)
        mouths = _entry_mouths(w, h, entry_sides, lrng)
        out = layout_zone(zone, Rect(0, 0, w, h), templates, lrng,
                          road_reserved=mouths)
        lost = [r for (_what, r) in out.failures if "no space in zone" in r]
        return (len(out.buildings) == want_buildings
                and len(out.compounds) == want_compounds and not lost)

    def both_place(w, h):
        return places(w, h, seed) and places(w, h, seed ^ 0x5F3759DF)

    # a size only counts as measured when two different inner seeds both
    # place everything there — one seed's luck is not a measurement
    for _ in range(MEASURE_TRIES):
        if both_place(w, h):
            # the fit the search started at (and every growth step) runs
            # loose, and grows both axes together: walk each axis back down
            # on its own, so a measurement wider than the layout reads as
            # empty ground. Both seeds must still fit at every step: one
            # seed's tightest frame has no slack left for the real road
            # mouths the map brings
            for mi in (0, 1):
                for _ in range(MEASURE_TIGHTEN):
                    if mi == 0:
                        nw, nh = max(mins[0], MIN_ZONE_SIDE,
                                     w - max(2, w // 10)), h
                    else:
                        nw, nh = w, max(mins[1], MIN_ZONE_SIDE,
                                        h - max(2, h // 10))
                    if (nw, nh) == (w, h) or not both_place(nw, nh):
                        break
                    w, h = nw, nh
            # the margin is for paths and dressing on open ground; a void
            # zone has neither — everything walkable is already inside walls
            margin = 0 if zone.exterior == "void" else MEASURE_MARGIN
            return (max(w + margin, mins[0], MIN_ZONE_SIDE),
                    max(h + margin, mins[1], MIN_ZONE_SIDE))
        w += max(3, w // 6)
        h += max(3, h // 6)
    return (w, h)   # nothing fit: the biggest frame tried, the map's problem


# ------------------------------------------------------------------ the path

def _mouth_clusters(rect, mouths):
    """Road mouths grouped per road, as (side, centroid cell)."""
    if not mouths:
        return []
    cells = sorted(mouths)
    seen = set()
    clusters = []
    for c in cells:
        if c in seen:
            continue
        comp = [c]
        seen.add(c)
        todo = [c]
        while todo:
            x, y = todo.pop(0)
            for nxt in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if nxt in mouths and nxt not in seen:
                    seen.add(nxt)
                    comp.append(nxt)
                    todo.append(nxt)
        sides = []
        for (x, y) in comp:
            if x == rect.x:
                sides.append("west")
            elif x == rect.x1:
                sides.append("east")
            elif y == rect.y:
                sides.append("south")
            elif y == rect.y1:
                sides.append("north")
        side = max(sorted(set(sides)), key=sides.count) if sides else "inner"
        cx = sum(p[0] for p in comp) / float(len(comp))
        cy = sum(p[1] for p in comp) / float(len(comp))
        clusters.append((side, (cx, cy)))
    return clusters


def _main_path(zone, rect, mouths, rng, widest=(0, 0), hug_road=False):
    """(street Rect, [Rects]). The street runs the zone's long axis near its
    centre; each road mouth gets a 3-wide entry arm walking to it. A zone too
    narrow for its widest building on a side gets a one-sided street hugging
    its edge instead. With ``hug_road`` the street hugs the first road
    mouth's side when it runs along it (the fields arrangement runs its lane
    on the road side, so the buildings gather behind it at the corner).
    Built as one cell set and re-cut into disjoint rects, so the pieces can
    never partially overlap."""
    if max(rect.w, rect.h) < 14 or min(rect.w, rect.h) < 7:
        return None, []
    # the street runs with the axis most building entrances face, so lining
    # the street means at most a same-axis (180 degree) entrance rotation;
    # the zone's own aspect breaks ties
    ns = sum(1 for d in zone.buildings if d.entrance_side in ("north", "south"))
    ew = sum(1 for d in zone.buildings if d.entrance_side in ("east", "west"))
    if ns != ew:
        vertical = ew > ns
    else:
        vertical = rect.h > rect.w or (rect.h == rect.w and rng.random() < 0.5)
    cx, cy = rect.center()
    gateways = []
    for (side, (mx, my)) in _mouth_clusters(rect, mouths):
        if side in ("west", "east"):
            a = max(rect.y + 1, min(rect.y1 - 1, int(round(my))))
        else:
            a = max(rect.x + 1, min(rect.x1 - 1, int(round(mx))))
        if side != "inner":
            gateways.append((side, a))
    if not gateways:
        pair = (("west", "east") if vertical else ("south", "north"))
        if rng.random() < 0.5:
            pair = (pair[1], pair[0])
        mid = ((rect.y + rect.y1) // 2, (rect.x + rect.x1) // 2)
        gateways = [(pair[0], mid[0] if pair[0] in ("west", "east") else mid[1]),
                    (pair[1], mid[0] if pair[1] in ("west", "east") else mid[1])]
    elif len(gateways) == 1:
        g = gateways[0]
        opp = OPPOSITE_SIDE[g[0]]
        if opp in ("west", "east"):
            a = (rect.y + rect.y1) // 2 + rng.randint(-3, 3)
        else:
            a = (rect.x + rect.x1) // 2 + rng.randint(-3, 3)
        gateways.append((opp, a))
    else:
        def gcell(g):
            s, a = g
            return {"west": (rect.x, a), "east": (rect.x1, a),
                    "north": (a, rect.y1), "south": (a, rect.y)}[s]
        best = None
        for i in range(len(gateways)):
            for j in range(i + 1, len(gateways)):
                p, q = gcell(gateways[i]), gcell(gateways[j])
                d = abs(p[0] - q[0]) + abs(p[1] - q[1])
                if best is None or d > best[0]:
                    best = (d, i, j)
        gateways = [gateways[best[1]], gateways[best[2]]]

    cells = set()

    # the road-side hug: the first real road mouth's side, when the street
    # runs along it (a west mouth hugs nothing on a horizontal street)
    hug = ""
    if hug_road and mouths:
        hug = gateways[0][0]
        if hug not in (("west", "east") if vertical else ("south", "north")):
            hug = ""

    def offset_street(lo, hi, s, need):
        """Nudge the street so each open band fits the widest building; a
        zone too narrow for both hugs one edge (a one-sided street)."""
        left = s - lo
        right = hi - (s + PATH_WIDTH - 1)
        if left >= need and right >= need:
            return s
        if hi - lo + 1 - PATH_WIDTH < 2 * need:
            return lo if rng.random() < 0.5 else hi - PATH_WIDTH + 1
        if left < need:
            return min(hi - PATH_WIDTH + 1, s + (need - left))
        return max(lo, s - (need - right))

    if vertical:
        reach = max(4, rect.h // 4)
        sx = max(rect.x + 1, min(rect.x1 - PATH_WIDTH, int(cx) - 1 + rng.randint(-3, 3)))
        if hug in ("west", "east"):
            sx = rect.x if hug == "west" else rect.x1 - PATH_WIDTH + 1
        else:
            sx = offset_street(rect.x, rect.x1, sx, widest[0] + 2)
        top = int(cy) + reach + rng.randint(-2, 2)
        bot = int(cy) - reach + rng.randint(-2, 2)
        for (side, a) in gateways:
            if side in ("west", "east"):
                # the road walks in along the nearer end edge and along that
                # edge to the street, so the arm never cuts a building band
                ey = rect.y if (a - rect.y) < (rect.y1 - a) else rect.y1
                if ey == rect.y:
                    bot = min(bot, ey + 1)
                else:
                    top = max(top, ey - 1)
                ex = rect.x if side == "west" else rect.x1
                ax = sx + 1 if side == "west" else sx - 1
                cells |= _seg_cells((ex, a), (ex, ey), rect)
                cells |= _seg_cells((ex, ey), (ax, ey), rect)
            else:
                # the street runs to this edge and the arm hugs it, so the
                # entry never cuts a building band lengthwise
                if side == "north":
                    top = rect.y1
                else:
                    bot = rect.y
                ey = rect.y1 if side == "north" else rect.y
                cells |= _seg_cells((a, ey), (sx + 1, ey), rect)
        top = min(top, rect.y1)
        bot = max(bot, rect.y)
        if top - bot + 1 < PATH_WIDTH:
            bot = max(rect.y, top - PATH_WIDTH + 1)
            top = min(rect.y1, bot + PATH_WIDTH - 1)
        street = Rect(sx, bot, PATH_WIDTH, top - bot + 1)
        cells |= street.cells()
    else:
        reach = max(4, rect.w // 4)
        sy = max(rect.y + 1, min(rect.y1 - PATH_WIDTH, int(cy) - 1 + rng.randint(-3, 3)))
        if hug in ("south", "north"):
            sy = rect.y if hug == "south" else rect.y1 - PATH_WIDTH + 1
        else:
            sy = offset_street(rect.y, rect.y1, sy, widest[1] + 2)
        left = int(cx) - reach + rng.randint(-2, 2)
        right = int(cx) + reach + rng.randint(-2, 2)
        for (side, a) in gateways:
            if side in ("north", "south"):
                # the road walks in along the nearer end edge and along that
                # edge to the street, so the arm never cuts a building band
                ex = rect.x if (a - rect.x) < (rect.x1 - a) else rect.x1
                if ex == rect.x:
                    left = min(left, ex + 1)
                else:
                    right = max(right, ex - 1)
                ey = rect.y1 if side == "north" else rect.y
                ay = sy + 1 if side == "north" else sy - 1
                cells |= _seg_cells((a, ey), (ex, ey), rect)
                cells |= _seg_cells((ex, ey), (ex, ay), rect)
            else:
                # the street runs to this edge and the arm hugs it, so the
                # entry never cuts a building band lengthwise
                if side == "east":
                    right = rect.x1
                else:
                    left = rect.x
                ex = rect.x if side == "west" else rect.x1
                cells |= _seg_cells((ex, a), (ex, sy + 1), rect)
        left = max(left, rect.x)
        right = min(right, rect.x1)
        if right - left + 1 < PATH_WIDTH:
            left = max(rect.x, min(rect.x1, right - PATH_WIDTH + 1))
            right = min(rect.x1, left + PATH_WIDTH - 1)
        street = Rect(left, sy, right - left + 1, PATH_WIDTH)
        cells |= street.cells()
    return street, _cells_to_rects(cells)


def _wild_track(rect, mouths):
    """(street Rect or None, [Rects]). A wild zone's whole path: one track
    joining its road mouths — the first mouth's nearest neighbour walks an
    L to it, then the next nearest to any cell already joined — and nothing
    at all when it has fewer than two, so no street ever runs the zone's
    length beside empty ground."""
    entries = []
    for (side, (mx, my)) in mouths:
        if side == "inner":
            continue
        if side in ("west", "east"):
            a = max(rect.y + 1, min(rect.y1 - 1, int(round(my))))
            entries.append((rect.x if side == "west" else rect.x1, a))
        else:
            a = max(rect.x + 1, min(rect.x1 - 1, int(round(mx))))
            entries.append((a, rect.y if side == "south" else rect.y1))
    if len(entries) < 2:
        return None, []
    cells = set()
    joined = [entries[0]]
    rest = entries[1:]
    while rest:
        p, q = min(((p, q) for p in rest for q in joined),
                   key=lambda pq: (abs(pq[0][0] - pq[1][0]) + abs(pq[0][1] - pq[1][1]),
                                   pq[0], pq[1]))
        cells |= _seg_cells(p, (q[0], p[1]), rect)
        cells |= _seg_cells((q[0], p[1]), q, rect)
        joined.append(p)
        rest.remove(p)
    rects = _cells_to_rects(cells)
    street = max(rects, key=lambda r: r.w * r.h) if rects else None
    return street, rects


def _seg_cells(p, q, rect):
    """A 3-wide dilated axis-aligned segment, clipped to the zone."""
    cells = set()
    (x0, y0), (x1, y1) = p, q
    if y0 == y1:
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for dy in (-1, 0, 1):
                c = (x, y0 + dy)
                if rect.contains_cell(c):
                    cells.add(c)
    else:
        for y in range(min(y0, y1), max(y0, y1) + 1):
            for dx in (-1, 0, 1):
                c = (x0 + dx, y)
                if rect.contains_cell(c):
                    cells.add(c)
    return cells


# ------------------------------------------------------------------ streets

def green_size(zone, fps, urban):
    """(w, h) of an around_green green, from the buildings that ring it: each
    side carries about a quarter of the frontage, so a few buildings make a
    small green with a tight ring, many buildings a wide one."""
    if not fps:
        return (0, 0)
    gap = sum(lot_gap(zone)) // 2
    sides = ([], [], [], [])
    for length in sorted((max(f) for f in fps), reverse=True):
        sides[min(range(4), key=lambda i: (sum(sides[i]), i))].append(length)
    per = max(sum(s) + gap * max(0, len(s) - 1) for s in sides)
    gw = max((7 if urban else 9), min(13, int(round(per * 0.6))))
    gh = max((5 if urban else 6), min(9, int(round(gw * 0.7))))
    return gw, gh


def _green_ring(zone, rect, mouths, rng, urban, templates):
    """One open green with a ring path round it: the arrangement's whole
    path network (no side streets, no crossroads square), with an entry arm
    walking in from each road mouth. Each arm runs straight from the zone
    edge to the ring, so on an axis whose mouths face one side only the
    green leans that way — a lot ring's depth off the mouthed edge, the
    slack behind it — and an axis whose mouths face both ways, or none,
    keeps it centred. Returns (ring rect or None, spine rects, green rect
    or None)."""
    if max(rect.w, rect.h) < 16 or min(rect.w, rect.h) < 8:
        return None, [], None
    fps = [building_footprint(d, templates) for d in zone.buildings]
    gw, gh = green_size(zone, fps, urban)
    gw = min(gw, max((7 if urban else 9), rect.w // 3))
    gh = min(gh, max((5 if urban else 6), rect.h // 3))
    cx, cy = rect.center()
    near_x = rect.x + 1 + PATH_WIDTH
    far_x = rect.x1 - 1 - PATH_WIDTH - gw + 1
    near_y = rect.y + 1 + PATH_WIDTH
    far_y = rect.y1 - 1 - PATH_WIDTH - gh + 1
    sides = {side for (side, _c) in mouths}
    depths = sorted((min(f) for f in fps), reverse=True) if fps else [0]

    def lean(g, near, far, near_side, far_side, reserve):
        """The green's origin on one axis, pulled toward its mouthed side
        while the buildings ringing the green keep a lot's depth there."""
        if (near_side in sides) == (far_side in sides):
            return max(near, min(far, g))
        target = near + reserve if near_side in sides else far - reserve
        if not near <= target <= far:   # too tight to spare the lot depth: hug
            target = near if near_side in sides else far
        return target

    gx = lean(int(cx - gw / 2.0) + rng.randint(-2, 2),
              near_x, far_x, "west", "east", max(depths[1:4] + [0]))
    gy = lean(int(cy - gh / 2.0) + rng.randint(-2, 2),
              near_y, far_y, "south", "north", max(depths[1:4] + [0]))
    green = Rect(gx, gy, gw, gh)
    ring = Rect(green.x - PATH_WIDTH, green.y - PATH_WIDTH,
                green.w + 2 * PATH_WIDTH, green.h + 2 * PATH_WIDTH)
    if not rect.interior(1).contains_rect(ring):
        return None, [], None
    cells = ring.cells() - green.cells()
    for (side, (mx, my)) in mouths:
        a = max(rect.y + 1, min(rect.y1 - 1, int(round(my)))) \
            if side in ("west", "east") else \
            max(rect.x + 1, min(rect.x1 - 1, int(round(mx))))
        if side == "west":
            cells |= _seg_cells((rect.x, a), (ring.x, a), rect)
        elif side == "east":
            cells |= _seg_cells((rect.x1, a), (ring.x1, a), rect)
        elif side == "south":
            cells |= _seg_cells((a, rect.y), (a, ring.y), rect)
        elif side == "north":
            cells |= _seg_cells((a, rect.y1), (a, ring.y1), rect)
    return ring, _cells_to_rects(cells), green


def _settlement_streets(zone, rect, mouths, rng, widest, urban):
    """A settlement's street network: the main street runs the zone's long
    axis wall to wall, 1-3 side streets cross it, each road mouth gets an
    arm to the nearest street, and the square sits at the main crossroads.
    Returns (street Rect or None, spine rects, square Rect or None)."""
    if max(rect.w, rect.h) < 16 or min(rect.w, rect.h) < 8:
        return None, [], None, []
    vertical = rect.h > rect.w or (rect.h == rect.w and rng.random() < 0.5)
    short = rect.w if vertical else rect.h
    long_side = max(rect.w, rect.h)
    k = side_street_count(long_side, len(zone.buildings))
    # every column between the streets must still hold a building along the
    # street, and the cross-axis must fit the blocks either side of them
    max_along = widest[1] if vertical else widest[0]
    k = min(k, max(0, long_side // (max_along + 8) - 1))
    alley = rng.randint(ALLEY_MIN, ALLEY_MAX) if urban else LANE_WIDTH
    while k > 0 and short < 10 + k * (alley + 4):
        k -= 1   # not enough cross-room for this many streets

    cells = set()
    cx, cy = rect.center()
    if vertical:
        sx = max(rect.x + 1, min(rect.x1 - PATH_WIDTH, int(cx) - 1 + rng.randint(-2, 2)))
        left = sx - rect.x
        right = rect.x1 - (sx + PATH_WIDTH - 1)
        need = widest[0] + 2
        if left < need and right >= need:
            sx += need - left
        elif right < need and left >= need:
            sx -= need - right
        elif left < need and right < need:
            # too narrow to line both sides: a one-sided street hugging one
            # edge, so the single band can hold the widest building
            sx = rect.x if rng.random() < 0.5 else rect.x1 - PATH_WIDTH + 1
        street = Rect(sx, rect.y, PATH_WIDTH, rect.h)
        cells |= street.cells()
        sides = _side_street_rects(rect, k, alley, rng, vertical)
        for s in sides:
            cells |= s.cells()
        for (side, (mx, my)) in _mouth_clusters(rect, mouths):
            mx = max(rect.x + 1, min(rect.x1 - 1, int(round(mx))))
            my = max(rect.y + 1, min(rect.y1 - 1, int(round(my))))
            cells |= _seg_cells((mx, my), (sx + 1, my), rect)
    else:
        sy = max(rect.y + 1, min(rect.y1 - PATH_WIDTH, int(cy) - 1 + rng.randint(-2, 2)))
        below = sy - rect.y
        above = rect.y1 - (sy + PATH_WIDTH - 1)
        need = widest[1] + 2
        if below < need and above >= need:
            sy += need - below
        elif above < need and below >= need:
            sy -= need - above
        elif below < need and above < need:
            # too narrow to line both sides: a one-sided street
            sy = rect.y if rng.random() < 0.5 else rect.y1 - PATH_WIDTH + 1
        street = Rect(rect.x, sy, rect.w, PATH_WIDTH)
        cells |= street.cells()
        sides = _side_street_rects(rect, k, alley, rng, vertical)
        for s in sides:
            cells |= s.cells()
        for (side, (mx, my)) in _mouth_clusters(rect, mouths):
            mx = max(rect.x + 1, min(rect.x1 - 1, int(round(mx))))
            my = max(rect.y + 1, min(rect.y1 - 1, int(round(my))))
            cells |= _seg_cells((mx, my), (mx, sy + 1), rect)

    square = _crossroads_square(rect, street, sides, vertical, urban, rng)
    if square is not None:
        # a path that would cross the square (an entry arm, say) ends at its
        # edge instead, so the two regions can never partly overlap
        cells -= square.cells()
    return street, _cells_to_rects(cells), square, sides


def _side_street_rects(rect, k, width, rng, vertical):
    """k perpendicular streets crossing the zone, evenly spread with jitter.
    The position runs along the zone's long axis whichever way it points."""
    if k <= 0:
        return []
    long_side = rect.h if vertical else rect.w
    lo = (rect.y if vertical else rect.x) + 5
    hi = (rect.y1 if vertical else rect.x1) - 5 - width
    rects = []
    positions = []
    for i in range(1, k + 1):
        p = (rect.y if vertical else rect.x) + int(round(long_side * i / float(k + 1)))             + rng.randint(-2, 2)
        p = max(lo, min(hi, p))
        while any(abs(p - q) < 8 for q in positions):
            p += 1 if rng.random() < 0.5 else -1
            p = max(lo, min(hi, p))
        positions.append(p)
    for p in sorted(positions):
        rects.append(Rect(rect.x, p, rect.w, width) if vertical
                     else Rect(p, rect.y, width, rect.h))
    return rects


def _crossroads_square(rect, street, sides, vertical, urban, rng):
    """The square or green beside the main crossroads: the side street
    closest to the zone's centre crossing the main street, in one of the
    four block corners round that intersection."""
    if not sides:
        return None
    scx, scy = street.x + street.w // 2, street.y + street.h // 2
    cx, cy = rect.center()
    cross = min(sides, key=lambda s: abs(s.x + s.w / 2.0 - cx) + abs(s.y + s.h / 2.0 - cy))
    w, h = (7, 5) if urban else (9, 6)
    quads = []
    if vertical:
        ys = [cross.y1 + 1, cross.y - h]
        xs = [street.x1 + 1, street.x - w]
        for y in ys:
            for x in xs:
                quads.append(Rect(x, y, w, h))
    else:
        xs = [cross.x1 + 1, cross.x - w]
        ys = [street.y1 + 1, street.y - h]
        for y in ys:
            for x in xs:
                quads.append(Rect(x, y, w, h))
    rng.shuffle(quads)
    street_cells = set()
    street_cells |= street.cells()
    for s in sides:
        street_cells |= s.cells()
    for q in quads:
        if not rect.interior(1).contains_rect(q):
            continue
        if q.cells() & street_cells:
            continue
        return q
    return None


# ------------------------------------------------------------------ buildings

def _furnish(out, b, zone, templates, rng):
    """Lay out one building's room furniture (its stamped unit copies
    included). Returns its failure list without recording anything, so a
    rejected placement leaves no trace."""
    failures = []
    layouts = [b.layout] + [u.layout for u in getattr(b.layout, "unit_outs", [])]
    for bl in layouts:
        for room in bl.rooms:
            furniture = [f for f in bl.furniture if f.room == room.base_name]
            unknown = [f for f in bl.furniture
                       if f.room not in {r.base_name for r in bl.rooms}]
            for f in unknown:
                failures.append((f"piece {f.template}", f"room {f.room!r} not in building"))
            # far/side/near are measured from the door people come in by: the
            # one nearest the building's entrance
            entry = getattr(bl, "entrance_door", None)
            main = min(sorted(room.doors), key=lambda d: abs(d[0] - entry[0]) + abs(d[1] - entry[1]))                 if entry and room.doors else None
            room.furniture = layout_room(room.rect, sorted(room.doors), furniture, templates, rng,
                                         main_door=main)
            for (t, n, reason) in room.furniture.failures:
                failures.append((f"piece {t} in {room.base_name}",
                                 f"placed {n} of the requested count: {reason}"))
    return failures


def _record_furniture(out, b):
    for (t, room_name) in b.layout.dropped:
        out.failures.append((f"piece {t} in {room_name}", "dropped: over the 28x22 building cap"))
    for name in getattr(b.layout, "unit_dropped", []) or []:
        out.failures.append((f"unit {name}", "dropped: no room in the block"))
    layouts = [b.layout] + [u.layout for u in getattr(b.layout, "unit_outs", [])]
    for bl in layouts:
        for room in bl.rooms:
            for (t, reason) in room.furniture.fallbacks:
                out.fallbacks.append((f"piece {t} in {room.base_name}", reason))


def _slot(facing, axis, line, a0, a1, extreme):
    """One street-facing frontage: buildings pack along [a0, a1] on `axis`,
    their street-side edge at `line` (set back by 0-2 cells)."""
    return {"facing": facing, "axis": axis, "line": line,
            "a0": a0, "a1": a1, "cursor_lo": a0, "cursor_hi": a1,
            "extreme": extreme,
            "len": max(1, a1 - a0 + 1), "used": 0}


def _grid_slots(rect, street, sides, vertical):
    """The blocks between the streets, each contributing the frontages that
    face a street: both sides of every column face the main street, and the
    columns at a side street also face it along their end."""
    slots = []
    if vertical:
        sides = sorted(sides, key=lambda s: s.y)
        starts = [rect.y] + [s.y1 + 1 for s in sides]
        ends = [s.y - 1 for s in sides] + [rect.y1]
        bands = [("east", rect.x, street.x - 1), ("west", street.x1 + 1, rect.x1)]
        last = len(starts) - 1
        for (facing, bx0, bx1) in bands:
            if bx1 < bx0:
                continue
            for j, (y0, y1) in enumerate(zip(starts, ends)):
                lo, hi = max(y0, rect.y + 1), min(y1, rect.y1 - 1)
                if hi < lo:
                    continue
                slots.append(_slot(facing, "y", bx1 if facing == "east" else bx0,
                                   lo, hi, j in (0, last)))
                if j > 0:   # a side street along the column's south edge
                    slots.append(_slot("south", "x", y0,
                                       max(bx0, rect.x + 1), min(bx1, rect.x1 - 1), False))
                if j < last:   # one along the north edge
                    slots.append(_slot("north", "x", y1,
                                       max(bx0, rect.x + 1), min(bx1, rect.x1 - 1), False))
    else:
        sides = sorted(sides, key=lambda s: s.x)
        starts = [rect.x] + [s.x1 + 1 for s in sides]
        ends = [s.x - 1 for s in sides] + [rect.x1]
        bands = [("north", rect.y, street.y - 1), ("south", street.y1 + 1, rect.y1)]
        last = len(starts) - 1
        for (facing, by0, by1) in bands:
            if by1 < by0:
                continue
            for j, (x0, x1) in enumerate(zip(starts, ends)):
                lo, hi = max(x0, rect.x + 1), min(x1, rect.x1 - 1)
                if hi < lo:
                    continue
                slots.append(_slot(facing, "x", by1 if facing == "north" else by0,
                                   lo, hi, j in (0, last)))
                if j > 0:   # a side street along the column's west edge
                    slots.append(_slot("west", "y", x0,
                                       max(by0, rect.y + 1), min(by1, rect.y1 - 1), False))
                if j < last:   # one along the east edge
                    slots.append(_slot("east", "y", x1,
                                       max(by0, rect.y + 1), min(by1, rect.y1 - 1), False))
    return slots


def _slot_rect(slot, fp, a, off):
    """The building rect at frontage position `a`, set back `off` cells."""
    if slot["axis"] == "y":
        if slot["facing"] == "east":
            bx = slot["line"] - off - fp[0] + 1
        else:
            bx = slot["line"] + off
        return Rect(bx, a, fp[0], fp[1])
    if slot["facing"] == "north":
        by = slot["line"] - off - fp[1] + 1
    else:
        by = slot["line"] + off
    return Rect(a, by, fp[0], fp[1])


def _pack_in_slot(design, slot, fits, put, rollback, zone, templates, out, rng):
    """Place one building on this frontage, packing from whichever end has
    more room. The entrance faces the street; a placement that spoils the
    rooms is kept over turning the entrance away. Returns True if placed."""
    facing = slot["facing"]
    facing_d = dataclasses.replace(design, entrance_side=facing)
    variants = [facing_d] if design.entrance_side == facing else [facing_d, design]
    variants = [(rd, building_footprint(rd, templates)) for rd in variants]
    ends = ["lo", "hi"]
    rng.shuffle(ends)
    fallback = None
    for with_yard in (True, False):
        for rd, fp in variants:
            along = fp[1] if slot["axis"] == "y" else fp[0]
            for end in ends:
                a = slot["cursor_lo"] if end == "lo" else slot["cursor_hi"] - along + 1
                if a < slot["a0"] or a + along - 1 > slot["a1"]:
                    continue
                for off in (0, 1, 2):
                    br = _slot_rect(slot, fp, a, off)
                    yr = _yard_rect(br, rd) if (with_yard and rd.yard) else None
                    lot = _lot_rect(br, yr)
                    if not fits(lot, rd.entrance_side, br):
                        continue
                    b = put(rd, (br.x, br.y), yr)
                    failures = _furnish(out, b, zone, templates, rng)
                    if failures:
                        # room furniture is seeded; one redraw before giving
                        # up on this orientation keeps entrances facing streets
                        failures = _furnish(out, b, zone, templates, rng)
                    if not failures:
                        _record_furniture(out, b)
                        _advance_slot(slot, end, a, along, rng, lot_gap(zone))
                        return True
                    rollback(b)
                    if fallback is None:
                        fallback = (rd, (br.x, br.y), yr, end, a, along)
    if fallback is not None:
        rd, origin, yr, end, a, along = fallback
        b = put(rd, origin, yr)
        out.failures.extend(_furnish(out, b, zone, templates, rng))
        _record_furniture(out, b)
        _advance_slot(slot, end, a, along, rng, lot_gap(zone))
        return True
    return False


def _advance_slot(slot, end, a, along, rng, gap):
    rng_gap = rng.randint(gap[0], gap[1])
    if end == "lo":
        slot["cursor_lo"] = a + along + rng_gap
    else:
        slot["cursor_hi"] = a - rng_gap
    slot["used"] += along + rng_gap


def _place_buildings_grid(zone, rect, out, rng, templates, fits, put, rollback):
    """Fill the street grid's frontages, biggest buildings first, spreading
    over the least-filled slots so the buildings cover the zone."""
    slots = _grid_slots(rect, out.street, out.side_streets, out.grid_vertical)
    rng.shuffle(slots)
    designs = sorted(
        (d for d in zone.buildings if d.name not in {
            p.building for c in getattr(zone, "compounds", []) or [] for p in c.parts}),
        key=lambda d: (-(building_footprint(d, templates)[0]
                         * building_footprint(d, templates)[1]), d.name))
    for design in designs:
        order = sorted(slots, key=lambda s: (s["used"] / float(s["len"])
                                             - (0.2 if s["extreme"] else 0.0)))
        placed = any(_pack_in_slot(design, s, fits, put, rollback, zone, templates, out, rng)
                     for s in order)
        if not placed:
            if not _scan_place(design, rect, out.street, fits, put, rollback,
                               zone, templates, out, rng):
                out.failures.append((f"building {design.name}", "no space in zone"))


def _place_buildings_around_green(zone, rect, out, rng, templates, fits, put,
                                  rollback, mouths):
    """The around_green arrangement: buildings face the green on all sides
    of its ring, the largest at the head of the green — the side opposite
    the road mouth."""
    green = out.feature
    ring = Rect(green.x - PATH_WIDTH, green.y - PATH_WIDTH,
                green.w + 2 * PATH_WIDTH, green.h + 2 * PATH_WIDTH)
    head = OPPOSITE_SIDE[mouths[0][0]] if mouths else "north"
    slots = []
    for side in ("north", "south", "east", "west"):
        if side in ("north", "south"):
            line = ring.y1 + 1 if side == "north" else ring.y - 1
            lo = max(rect.x + 1, ring.x - 2)
            hi = min(rect.x1 - 1, ring.x1 + 2)
            slots.append(_slot(OPPOSITE_SIDE[side], "x", line, lo, hi, side == head))
        else:
            line = ring.x1 + 1 if side == "east" else ring.x - 1
            lo = max(rect.y + 1, ring.y - 2)
            hi = min(rect.y1 - 1, ring.y1 + 2)
            slots.append(_slot(OPPOSITE_SIDE[side], "y", line, lo, hi, side == head))
    rng.shuffle(slots)
    designs = sorted(
        (d for d in zone.buildings if d.name not in {
            p.building for c in getattr(zone, "compounds", []) or [] for p in c.parts}),
        key=lambda d: (-(building_footprint(d, templates)[0]
                         * building_footprint(d, templates)[1]), d.name))
    for i, design in enumerate(designs):
        order = sorted(slots, key=lambda s: (s["used"] / float(s["len"])
                                             - (0.2 if s["extreme"] else 0.0)))
        if i == 0:
            head_slots = [s for s in slots if s["extreme"]]
            order = head_slots + [s for s in order if s not in head_slots]
        placed = any(_pack_in_slot(design, s, fits, put, rollback, zone, templates, out, rng)
                     for s in order)
        if not placed:
            if not _scan_place(design, rect, out.street, fits, put, rollback,
                               zone, templates, out, rng):
                out.failures.append((f"building {design.name}", "no space in zone"))


def _fields_focus(rect, out, mouths):
    """The road-side corner the fields arrangement gathers its buildings
    at: the zone corner nearest the biggest road mouth."""
    if mouths:
        (_side, (mx, my)) = mouths[0]
        cx = rect.x if mx < rect.x + rect.w / 2.0 else rect.x1
        cy = rect.y if my < rect.y + rect.h / 2.0 else rect.y1
        return (cx, cy)
    if out.street is not None:
        return (out.street.x + out.street.w // 2, out.street.y + out.street.h // 2)
    return rect.center()


def _place_buildings(zone, rect, out, rng, templates, mouths=()):
    compounds = list(getattr(zone, "compounds", None) or [])
    part_names = {p.building for c in compounds for p in c.parts}
    designs = sorted((d for d in zone.buildings if d.name not in part_names),
                     key=lambda d: (-(building_footprint(d, templates)[0]
                                      * building_footprint(d, templates)[1]), d.name))
    placed_lots = []
    placed_faces = []   # (building rect, entrance side): doors stay approachable
    compound_blocks = []   # [Rect]: branch routing never cuts through them
    inner = rect.interior(1) if rect.w > 2 and rect.h > 2 else rect
    spacing = lot_spacing(zone)

    def approach_strip(brect, side):
        """The 1-wide band of cells a door on `side` opens onto."""
        if side in ("north", "south"):
            y0 = brect.y1 + 1 if side == "north" else brect.y - 1
            return Rect(brect.x, y0, brect.w, 1)
        x0 = brect.x1 + 1 if side == "east" else brect.x - 1
        return Rect(x0, brect.y, 1, brect.h)

    def fits(lot, side=None, brect=None):
        if not inner.contains_rect(lot):
            return False
        for other in placed_lots:
            if other.gap(lot) < spacing:
                return False
        if lot.cells() & out.reserved:
            return False
        if out.feature is not None and out.feature.intersects(lot):
            return False
        if side is not None and brect is not None:
            # shared walls are fine, but a door never opens into a neighbour
            strip = approach_strip(brect, side)
            for (pr, ps) in placed_faces:
                if strip.intersects(pr) or approach_strip(pr, ps).intersects(brect):
                    return False
        return True

    def put(design, origin, yard):
        b = BuildingOut(None, None, yard)
        b.layout = layout_building(design, origin, rng, templates)
        b.lot = _lot_rect(b.layout.rect, yard)
        placed_lots.append(b.lot)
        placed_faces.append((b.layout.rect, b.layout.entrance_side))
        out.buildings.append(b)
        if yard is not None:
            out.yards.append((f"{design.name} {design.yard.kind}".strip(), yard, design.name))
        return b

    def rollback(b):
        out.buildings.remove(b)
        placed_lots.remove(b.lot)
        placed_faces.remove((b.layout.rect, b.layout.entrance_side))
        if b.yard_rect is not None:
            out.yards = [(n, yr, bn) for (n, yr, bn) in out.yards if yr is not b.yard_rect]

    # ---- compounds: one block each, gate face towards the road it joins,
    # before the loose buildings pack round them
    def furnish_part(b):
        failures = _furnish(out, b, zone, templates, rng)
        if failures:
            failures = _furnish(out, b, zone, templates, rng)
        out.failures.extend(failures)
        _record_furniture(out, b)

    for compound in sorted(compounds, key=lambda c: c.name, reverse=True):
        fp = layout_compound.compound_footprint(zone, compound, templates)
        pos = _compound_position(zone, rect, out, compound, fp, inner, fits,
                                 rng, mouths)
        if pos is None:
            out.failures.append((f"compound {compound.name}", "no space in zone"))
            continue
        block = Rect(pos[0], pos[1], fp[0], fp[1])
        comp = layout_compound.place_compound(zone, compound, block, templates,
                                              rng, furnish_part, mouths=list(mouths))
        out.compounds.append(comp)
        out.failures.extend(comp.failures)
        placed_lots.append(block)
        compound_blocks.append(block)
        for b in comp.parts:
            out.buildings.append(b)
        targets = []
        by_name = {b.layout.design.name: b for b in comp.parts}
        if compound.shape == "enclosure":
            for part in compound.parts:
                b = by_name.get(part.building)
                if part.slot_kind != "inside" or b is None:
                    continue
                dx, dy = SIDE_DX_DY[b.layout.entrance_side]
                targets.append((b.layout.entrance_door[0] + dx,
                                b.layout.entrance_door[1] + dy))
            comp.paths = layout_compound.courtyard_paths(comp, targets)
        for pr in comp.paths:
            out.reserved |= pr.cells()
        # nothing of the zone dresses inside the walls: the block keeps its
        # ground clear (the parts' own cells excluded — their furniture is
        # theirs), so no filler tree ever stands in the courtyard
        reserved_block = block.cells()
        for b in comp.parts:
            reserved_block -= b.layout.rect.cells()
        out.reserved |= reserved_block

    street = out.street
    if zone.arrangement == "around_green" and out.feature is not None:
        _place_buildings_around_green(zone, rect, out, rng, templates, fits, put,
                                      rollback, mouths)
        return
    if zone.arrangement in ("scattered", "fields"):
        focus = _fields_focus(rect, out, mouths) if zone.arrangement == "fields" else None
        for design in designs:
            if not _scan_place(design, rect, street, fits, put, rollback,
                               zone, templates, out, rng, focus=focus):
                out.failures.append((f"building {design.name}", "no space in zone"))
        return
    if street is not None and out.side_streets:
        _place_buildings_grid(zone, rect, out, rng, templates, fits, put, rollback)
        return
    if street is None:
        for design in designs:
            if not _scan_place(design, rect, None, fits, put, rollback,
                               zone, templates, out, rng):
                out.failures.append((f"building {design.name}", "no space in zone"))
        return

    vertical = street.h >= street.w
    if vertical:
        a0, a1 = max(street.y, rect.y + 1), min(street.y1, rect.y1 - 1)
    else:
        a0, a1 = max(street.x, rect.x + 1), min(street.x1, rect.x1 - 1)
    sides = ["west", "east"] if vertical else ["south", "north"]
    rng.shuffle(sides)
    per_side = {s: [] for s in sides}
    for i, d in enumerate(designs):
        per_side[sides[i % 2]].append(d)

    # each band packs from one (seeded) end, buildings butted up to the street
    # with seeded gaps between lots (urban rows share walls)
    forward = {s: rng.random() < 0.5 for s in sides}
    cursor = {s: (a0 if forward[s] else a1) for s in sides}
    gap = lot_gap(zone)

    def try_bands(design, order):
        for b in order:
            for with_yard in (True, False):
                end = _pack_in_band(design, b, street, vertical, cursor[b], forward[b],
                                    with_yard, a0, a1, fits, put, rollback,
                                    zone, templates, out, rng)
                if end is not None:
                    cursor[b] = end + rng.randint(gap[0], gap[1]) if forward[b] \
                        else end - rng.randint(gap[0], gap[1])
                    return True
        return False

    for si, band in enumerate(sides):
        other = sides[1 - si]
        for design in per_side[band]:
            if not try_bands(design, (band, other)):
                if not _scan_place(design, rect, street, fits, put, rollback,
                                   zone, templates, out, rng):
                    out.failures.append((f"building {design.name}", "no space in zone"))


def _pack_in_band(design, band, street, vertical, cursor, forward, with_yard,
                  a0, a1, fits, put, rollback, zone, templates, out, rng):
    """Place one building in `band`, walking from the cursor along the street.
    The entrance faces the street; a rotation that spoils the rooms records
    failures rather than turning the entrance away, and the original orientation
    is only kept when the rotated one cannot be placed at all.
    Returns the lot's far edge along the street, or None if nothing fits."""
    entrance = {"west": "east", "east": "west", "south": "north", "north": "south"}[band]
    facing = dataclasses.replace(design, entrance_side=entrance)
    variants = [facing] if design.entrance_side == entrance else [facing, design]
    # the resolved footprint depends on the entrance side (it picks the strip
    # direction), so each orientation carries its own footprint
    variants = [(rd, building_footprint(rd, templates)) for rd in variants]
    offsets = [0, 1, 2]
    rng.shuffle(offsets)
    fallback = None
    for rd, fp in variants:
        along = fp[1] if vertical else fp[0]
        room = (a1 - a0 + 1) - along
        steps = range(0, room + 1)
        if not forward:
            steps = reversed(steps)
        for k in steps:
            head = cursor + k if forward else cursor - k
            base = head if forward else head - along + 1
            for off in offsets:
                if vertical:
                    bx = street.x - 1 - off - fp[0] + 1 if band == "west" else street.x1 + 1 + off
                    by = base
                else:
                    by = street.y - 1 - off - fp[1] + 1 if band == "south" else street.y1 + 1 + off
                    bx = base
                br = Rect(bx, by, fp[0], fp[1])
                if not _fits_domain(br, street, band, vertical):
                    continue
                yr = _yard_rect(br, rd) if (with_yard and rd.yard) else None
                lot = _lot_rect(br, yr)
                if not fits(lot, rd.entrance_side, br):
                    continue
                b = put(rd, (bx, by), yr)
                failures = _furnish(out, b, zone, templates, rng)
                if failures:
                    # room furniture is seeded; one redraw before giving up
                    # on this orientation keeps entrances facing the street
                    failures = _furnish(out, b, zone, templates, rng)
                far = (lot.y1 if vertical else lot.x1) if forward else (lot.y if vertical else lot.x)
                if not failures:
                    _record_furniture(out, b)
                    return far
                rollback(b)
                if fallback is None:
                    fallback = (rd, (bx, by), yr, far)
        if fallback is not None:
            # the street-facing orientation was placeable: keep it, room
            # failures and all, rather than turning the entrance away
            break
    if fallback is not None:
        rd, origin, yr, far = fallback
        b = put(rd, origin, yr)
        out.failures.extend(_furnish(out, b, zone, templates, rng))
        _record_furniture(out, b)
        return far
    return None


def _fits_domain(br, street, band, vertical):
    """The building itself must sit on the band side of the street, not just
    its lot: its entrance wall faces the street directly."""
    if vertical:
        if band == "west":
            return br.x1 <= street.x - 1
        return br.x >= street.x1 + 1
    if band == "south":
        return br.y1 <= street.y - 1
    return br.y >= street.y1 + 1


def _facing_street_side(br, street):
    """The side of `br` that faces the street, mirroring how the bands are
    read: a building south of the street faces north, and so on."""
    if street.h >= street.w:
        return "east" if br.x1 < street.x else "west"
    return "north" if br.y1 < street.y else "south"


def _scan_place(design, rect, street, fits, put, rollback, zone, templates, out, rng,
                focus=None):
    """Fallback: the first free spot in the zone, preferring near the street
    (or near ``focus``, the road-side corner of a fields arrangement). The
    entrance is turned to face the street when there is one; a spot whose
    rooms furnish cleanly wins over a best-effort spot, but the entrance never
    turns away from the street to rescue the rooms."""
    fp0 = building_footprint(design, templates)
    for with_yard in (True, False):
        cands = [(bx, by) for bx in range(rect.x + 1, rect.x1 - fp0[0] + 2)
                 for by in range(rect.y + 1, rect.y1 - fp0[1] + 2)]
        rng.shuffle(cands)
        if focus is not None:
            # the fields arrangement names where its buildings gather: that
            # beats the usual pull toward the street
            cands.sort(key=lambda p: abs(p[0] - focus[0]) + abs(p[1] - focus[1]))
        elif street is not None:
            sc = (street.x + street.w // 2, street.y + street.h // 2)
            cands.sort(key=lambda p: abs(p[0] - sc[0]) + abs(p[1] - sc[1]))
        fallback = None
        spoiled = 0
        for (bx, by) in cands:
            # a room that will not furnish usually fails the same way at every
            # spot: after a few such spots, settle for the first of them rather
            # than furnishing again at every free cell of the zone
            if spoiled >= SCAN_FURNISH_SPOTS:
                break
            # the entrance is turned to face the street first; the original
            # orientation is still better than not placing the building
            if street is None:
                variants = [design]
            else:
                side = _facing_street_side(Rect(bx, by, fp0[0], fp0[1]), street)
                variants = [design] if design.entrance_side == side else \
                    [dataclasses.replace(design, entrance_side=side), design]
            for rd in variants:
                # the resolved footprint depends on the entrance side; place the
                # rect the layout will actually build
                fp = building_footprint(rd, templates)
                br = Rect(bx, by, fp[0], fp[1])
                if not rect.interior(1).contains_rect(br):
                    continue
                yr = _yard_rect(br, rd) if (with_yard and rd.yard) else None
                if not fits(_lot_rect(br, yr), rd.entrance_side, br):
                    continue
                b = put(rd, (bx, by), yr)
                failures = _furnish(out, b, zone, templates, rng)
                if failures:
                    # room furniture is seeded; one redraw before settling
                    failures = _furnish(out, b, zone, templates, rng)
                if not failures:
                    _record_furniture(out, b)
                    return True
                rollback(b)
                spoiled += 1
                if fallback is None:
                    fallback = (rd, (bx, by), yr)
        if fallback is not None:
            rd, origin, yr = fallback
            b = put(rd, origin, yr)
            out.failures.extend(_furnish(out, b, zone, templates, rng))
            _record_furniture(out, b)
            return True
    return False


def _compound_position(zone, rect, out, compound, fp, inner, fits, rng, mouths):
    """Where a compound's block sits: the free spot whose gate face comes
    nearest the road mouth the zone is joined to (else the street, else the
    zone's centre). Returns the block's origin, or None when nothing fits."""
    w, h = fp
    explicit = [p for p in compound.parts if p.gate]
    gate_side = layout_compound._outward_side(explicit[0]) if explicit else \
        (mouths[0][0] if mouths else "")
    if mouths:
        focus = mouths[0][1]
    elif out.street is not None:
        focus = out.street.center()
    else:
        focus = rect.center()
    cands = [(bx, by) for bx in range(inner.x, inner.x1 - w + 2)
             for by in range(inner.y, inner.y1 - h + 2)]
    rng.shuffle(cands)

    def face_center(pos):
        r = Rect(pos[0], pos[1], w, h)
        c = r.center()
        return {"north": (c[0], r.y1), "south": (c[0], r.y),
                "east": (r.x1, c[1]), "west": (r.x, c[1])}.get(gate_side, c)

    best = None
    for pos in cands:
        lot = Rect(pos[0], pos[1], w, h)
        if not fits(lot):
            continue
        fc = face_center(pos)
        d = abs(fc[0] - focus[0]) + abs(fc[1] - focus[1])
        if best is None or d < best[0]:
            best = (d, pos)
        if best[0] <= 2:
            break
    return best[1] if best is not None else None


def _route_branch(approach, targets, zone_rect, buildings_cells, own_building):
    """BFS from the entrance approach to the nearest path cell, through the
    zone but never through a building. Returns the path cells (approach excluded)."""
    own_cells = own_building.layout.rect.cells()
    blocked = buildings_cells - {approach}
    start = approach
    if start in blocked:
        return set()
    prev = {start: None}
    q = deque([start])
    found = None
    while q:
        cur = q.popleft()
        if cur in targets:
            found = cur
            break
        x, y = cur
        for nxt in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if not zone_rect.contains_cell(nxt):
                continue
            if nxt in blocked or nxt in prev:
                continue
            prev[nxt] = cur
            q.append(nxt)
    if found is None:
        return set()
    path = set()
    cur = found
    while prev[cur] is not None:
        path.add(cur)
        cur = prev[cur]
    return path


# ------------------------------------------------------------------ fields

CROP_WORDS = ("crop", "wheat", "barley", "rye", "oat", "corn", "maize",
              "rice", "vegetable", "cabbage", "turnip", "carrot", "vine",
              "grape", "hop", "flax", "orchard", "pumpkin", "potato",
              "herb", "lettuce", "bean", "pea")
STORE_WORDS = ("sack", "stack", "store", "storage", "barrel", "crate",
               "cart", "bale", "bin", "shelf", "basket", "silo")
FENCE_WORDS = ("fence", "hedge", "palisade", "paling", "hurdle")


def _matches(t, words):
    """A word matches only as a whole word of the name or of one tag,
    singular or plain plural ('herbs' matches 'herb'): a counter tagged
    'shop' is not the crop 'hop', and 'corner' is not 'corn'."""
    tokens = set()
    for text in (t.name,) + tuple(t.tags or ()):
        tokens |= {tok for tok in re.split(r"[^a-z0-9]+", text.lower()) if tok}
    return any(tok == w or tok == w + "s" or tok == w + "es"
               for tok in tokens for w in words)


def _pick_crop(templates):
    """The catalogue's crop or field-row piece, walkable first and the
    fullest row wins (a wheat row over a herb bed, say)."""
    crops = [t for t in templates.values()
             if _matches(t, CROP_WORDS) and not _matches(t, STORE_WORDS)]
    return min(crops, key=lambda t: (t.walkability <= 0, -t.size[0] * t.size[1], t.name)) \
        if crops else None


def _pick_fence(templates):
    """The catalogue's fence, but only a thin piece (its smaller side is 1):
    the ring is one piece thick, so a 2x2 bed tagged 'fence' is no fence and
    the plot goes without a ring."""
    fences = [t for t in templates.values()
              if _matches(t, FENCE_WORDS) and min(t.size) == 1]
    return min(fences, key=lambda t: (t.size[0] * t.size[1], t.name)) if fences else None


def _compass_word(rect, p):
    dx = (p.x + p.w / 2.0) - (rect.x + rect.w / 2.0)
    dy = (p.y + p.h / 2.0) - (rect.y + rect.h / 2.0)
    if abs(dx) > abs(dy) * 2:
        return "East" if dx > 0 else "West"
    if abs(dy) > abs(dx) * 2:
        return "North" if dy > 0 else "South"
    if dx > 0:
        return "NorthEast" if dy > 0 else "SouthEast"
    return "NorthWest" if dy > 0 else "SouthWest"


def _field_track(p, rect, occupied, spine):
    """A straight 1-wide dirt line from the plot's edge to the nearest path
    cell, so the field opens onto the way to the farmstead. Tries the side
    facing the path first, then the others. ([], gate) when no side has a
    clear run all the way to the path."""
    cx, cy = int(round(p.x + (p.w - 1) / 2.0)), int(round(p.y + (p.h - 1) / 2.0))
    nearest = min(spine, key=lambda c: (c[0] - cx) ** 2 + (c[1] - cy) ** 2)
    dx, dy = nearest[0] - cx, nearest[1] - cy
    order = ["east" if dx > 0 else "west", "north" if dy > 0 else "south"]
    order += [s for s in ("east", "west", "north", "south") if s not in order]
    for gate in order:
        step = {"east": (1, 0), "west": (-1, 0), "north": (0, 1), "south": (0, -1)}[gate]
        x, y = (p.x1 + 1, cy) if gate == "east" else \
               (p.x - 1, cy) if gate == "west" else \
               (cx, p.y1 + 1) if gate == "north" else (cx, p.y - 1)
        cells = []
        while rect.contains_cell((x, y)):
            if (x, y) in spine:
                return cells, gate
            if (x, y) in occupied:
                break
            cells.append((x, y))
            x, y = x + step[0], y + step[1]
    return [], order[0]


def _place_fields(zone, rect, out, rng, templates, map_ctx=None):
    """2-6 rectangular crop plots: dirt sub-regions of parallel crop rows
    with one-cell furrows, ringed with the catalogue's fence when it has
    one, each with a gate and a dirt track walking to the path (and so to
    the farmstead)."""
    crop = _pick_crop(templates)
    if crop is None:
        crop = ObjectTemplate(name="Crop row", size=(1, 1), walkability=0.6,
                              description="A row of young crop plants in the dirt.",
                              physicalDescription="Green shoots in a straight plough line.",
                              tags=["crop", "field"], rule="in parallel rows, a furrow between")
        templates[crop.name] = crop
        out.added_templates.append(crop)
    fence = _pick_fence(templates)
    occupied = set(out.reserved)
    for b in out.buildings:
        occupied |= b.lot.cells()
    spine = set()
    for r in out.spine_rects:
        spine |= r.cells()
    pool = getattr(map_ctx, "field_names", None) if map_ctx is not None else None

    want = min(6, max(2, int(round(rect.w * rect.h / 650.0))))
    plots = []
    for (w_lo, w_hi, h_lo, h_hi) in ((11, 15, 8, 11), (8, 10, 6, 8)):
        tries = 0
        while len(plots) < want and tries < 600:
            tries += 1
            pw, ph = rng.randint(w_lo, w_hi), rng.randint(h_lo, h_hi)
            if rect.w < pw + 2 or rect.h < ph + 2:
                continue
            p = Rect(rng.randint(rect.x + 1, rect.x1 - pw),
                     rng.randint(rect.y + 1, rect.y1 - ph), pw, ph)
            if p.cells() & occupied or any(q.gap(p) < 1 for q in plots):
                continue
            plots.append(p)
            occupied |= p.cells()   # later plots and their tracks keep clear
        if len(plots) >= 2:
            break
    if not plots:
        return

    crop_word = crop.name.split()[0].title()
    for p in plots:
        track, gate = _field_track(p, rect, occupied, spine) if spine else ([], "south")
        base = f"{_compass_word(rect, p)} {crop_word} Field"
        name = base
        if pool is not None:
            k = 2
            while name in pool:
                name = f"{base} {k}"
                k += 1
            pool.add(name)
        out.fields.append((name, p))
        out.field_cells |= p.cells()

        # the fence ring (the catalogue's fence), with a gate gap on the side
        # the track leaves from
        claimed = set()
        fw, fh = fence.size if fence else (0, 0)
        gate_at = track[0][1] if (track and gate in ("east", "west")) else \
            track[0][0] if track else p.x + p.w // 2
        if fence:
            for side, y in (("south", p.y), ("north", p.y1 - fh + 1)):
                x = p.x
                while x + fw <= p.x1 + 1:
                    if side == gate and abs(x + fw // 2 - gate_at) <= 1:
                        x += fw
                        continue
                    cells = {(xx, yy) for xx in range(x, x + fw)
                             for yy in range(y, y + fh)}
                    if not cells & claimed:
                        out.props.append(Placement(fence.name, (x, y), name))
                        claimed |= cells
                    x += fw
            for side, x in (("west", p.x), ("east", p.x1 - fw + 1)):
                y = p.y + fh
                while y + fh <= p.y1 - fh + 1:
                    if side == gate and abs(y + fh // 2 - gate_at) <= 1:
                        y += fh
                        continue
                    cells = {(xx, yy) for xx in range(x, x + fw)
                             for yy in range(y, y + fh)}
                    if not cells & claimed:
                        out.props.append(Placement(fence.name, (x, y), name))
                        claimed |= cells
                    y += fh

        # parallel crop rows, a one-cell furrow between them, along the plot's
        # longer side, filling the plot shrunk by the ring's thickness
        inter = Rect(p.x + fw, p.y + fh, p.w - 2 * fw, p.h - 2 * fh) if fence \
            else p.interior(1)
        cw, ch = crop.size
        if p.w >= p.h:
            y = inter.y
            while y + ch <= inter.y1 + 1:
                x = inter.x
                while x + cw <= inter.x1 + 1:
                    cells = {(xx, yy) for xx in range(x, x + cw) for yy in range(y, y + ch)}
                    if not cells & claimed:
                        out.props.append(Placement(crop.name, (x, y), name))
                        claimed |= cells
                    x += cw
                y += ch + 1
        else:
            x = inter.x
            while x + cw <= inter.x1 + 1:
                y = inter.y
                while y + ch <= inter.y1 + 1:
                    cells = {(xx, yy) for xx in range(x, x + cw) for yy in range(y, y + ch)}
                    if not cells & claimed:
                        out.props.append(Placement(crop.name, (x, y), name))
                        claimed |= cells
                    y += ch
                x += cw + 1

        if track:
            x0, y0 = track[0]
            tr = Rect(min(c[0] for c in track), min(c[1] for c in track),
                      max(c[0] for c in track) - min(c[0] for c in track) + 1,
                      max(c[1] for c in track) - min(c[1] for c in track) + 1)
            out.spine_rects.append(tr)
            out.reserved |= set(track)
            # a later plot's track stops where it meets this one (joining
            # the path network) rather than crossing it: two path regions
            # that overlap are refused by the builder
            spine |= set(track)


#
# ------------------------------------------------------------------ props

def _distance_to_reserved(rect, reserved):
    """{cell: manhattan distance to the nearest reserved cell}: a
    multi-source breadth-first sweep over the zone (an unblocked grid, so
    the walk length is the manhattan distance)."""
    dist = {c: 0 for c in reserved if rect.contains_cell(c)}
    todo = deque(dist)
    while todo:
        x, y = todo.popleft()
        for nxt in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if not rect.contains_cell(nxt) or nxt in dist:
                continue
            dist[nxt] = dist[(x, y)] + 1
            todo.append(nxt)
    return dist


def _place_props(out, prop, area_rect, templates, rng, occupied, buildings, area_name,
                 zone=None, buildings_cells=None):
    """Place one PropPlan outdoors (a yard or the whole zone) by hint."""
    if prop.template not in templates:
        out.failures.append((f"prop {prop.template}", "unknown template"))
        return
    tmpl = templates[prop.template]
    w, h = tmpl.size
    hint = parse_hint(prop.hint)
    candidates = []
    for x in range(area_rect.x, area_rect.x1 - w + 2):
        for y in range(area_rect.y, area_rect.y1 - h + 2):
            candidates.append((x, y))

    feature = out.feature
    feature_cells = feature.cells() if feature is not None else set()

    solid = tmpl.walkability <= 0

    def free(pos, spaced=True):
        fp = {(cx, cy) for cx in range(pos[0], pos[0] + w) for cy in range(pos[1], pos[1] + h)}
        if fp & occupied or fp & out.reserved:
            return False
        if buildings_cells and fp & buildings_cells:
            return False
        if feature is not None and not hint.center and fp & feature_cells:
            return False
        if solid:
            # a gap beside every solid prop, so a row of stalls has ways through
            if spaced and set(_ring_loop(fp)) & out.solid_props:
                return False
            if _splits_ground(fp, out.ground_blocked, out.rect):
                return False
        return True

    def put(pos):
        fp = {(cx, cy) for cx in range(pos[0], pos[0] + w) for cy in range(pos[1], pos[1] + h)}
        occupied.update(fp)
        if solid:
            out.solid_props |= fp
            out.ground_blocked |= fp
        out.props.append(Placement(prop.template, pos, area_name))

    zone_center = out.rect.center()
    if hint.center and feature is not None:
        fc = feature.center()
        candidates = [c for c in candidates if feature.contains_cell(c)]
        candidates.sort(key=lambda p: abs(p[0] - fc[0]) + abs(p[1] - fc[1]))
    elif hint.building_ref and hint.building_ref in buildings:
        brect, entrance_side = buildings[hint.building_ref]
        band = _relative_band(brect, entrance_side, hint.rel, area_rect)
        if band:
            candidates = [c for c in candidates if band.contains_cell(c)]
            candidates.sort(key=lambda p: (abs(p[0] - (brect.x + brect.w // 2))
                                           + abs(p[1] - (brect.y + brect.h // 2))))
    elif hint.along_path:
        # one multi-source sweep instead of a per-candidate scan over every
        # reserved cell — the same nearest-reserved order, linear in the zone
        if out.reserved:
            dist = _distance_to_reserved(out.rect, out.reserved)
            candidates.sort(key=lambda p: dist.get(p, 0))
    elif hint.center:
        candidates.sort(key=lambda p: abs(p[0] - zone_center[0]) + abs(p[1] - zone_center[1]))
    elif hint.edge and zone is not None:
        def edge_dist(p):
            return min(p[0] - out.rect.x, out.rect.x1 - p[0], p[1] - out.rect.y, out.rect.y1 - p[1])
        candidates.sort(key=edge_dist)
    elif hint.cluster:
        anchor = min(candidates, key=lambda p: abs(p[0] - zone_center[0]) + abs(p[1] - zone_center[1]))
        candidates.sort(key=lambda p: abs(p[0] - anchor[0]) + abs(p[1] - anchor[1]))
    else:  # scatter / unknown / no hint: seeded random order
        rng.shuffle(candidates)

    placed_count = 0
    for pos in candidates:
        if placed_count >= prop.count:
            break
        if not free(pos):
            continue
        put(pos)
        placed_count += 1
    if placed_count < prop.count and candidates:
        # the hint's own ground is full (a front band is mostly street):
        # fall back to anywhere free, nearest the hint's focus first
        if hint.building_ref and hint.building_ref in buildings:
            brect, _side = buildings[hint.building_ref]
            bc = (brect.x + brect.w / 2.0, brect.y + brect.h / 2.0)
        else:
            bc = out.rect.center()
        rest = [(x, y) for x in range(area_rect.x, area_rect.x1 - w + 2)
                for y in range(area_rect.y, area_rect.y1 - h + 2)]
        rest.sort(key=lambda p: abs(p[0] - bc[0]) + abs(p[1] - bc[1]))
        # the last pass lets pieces touch, though never across a gap
        for spaced in (True, False):
            for pos in rest:
                if placed_count >= prop.count:
                    break
                if free(pos, spaced):
                    put(pos)
                    placed_count += 1
    if placed_count < prop.count:
        out.failures.append((f"prop {prop.template}",
                             f"placed {placed_count} of {prop.count} in {area_name}"))


def _relative_band(brect, entrance_side, rel, area_rect):
    """A depth-6 band beside a building: front = entrance side, behind = opposite,
    beside = the two lateral sides."""
    depth = 6
    if rel in ("front", "behind"):
        side = entrance_side if rel == "front" else OPPOSITE_SIDE[entrance_side]
        dx, dy = SIDE_DX_DY[side]
        if side in ("north", "south"):
            y0 = brect.y1 + 1 if side == "north" else brect.y - depth
            return Rect(brect.x - 1, y0, brect.w + 2, depth)
        x0 = brect.x1 + 1 if side == "east" else brect.x - depth
        return Rect(x0, brect.y - 1, depth, brect.h + 2)
    # beside: both lateral bands
    if entrance_side in ("north", "south"):
        return Rect(brect.x - depth - 1, brect.y - 1, brect.w + 2 * (depth + 1), brect.h + 2)
    return Rect(brect.x - 1, brect.y - depth - 1, brect.w + 2, brect.h + 2 * (depth + 1))
