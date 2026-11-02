"""A compound: several connected structures placed as one block.

The model names the parts and their slots (corner towers, a gatehouse on an
edge, a keep in the courtyard, a chapel attached to the keep); code adds
the walls between them and the doors through them. The parts are the zone's
own buildings, furnished as usual; the wall segments are geometry the
layout makes, not plan buildings, so the same vocabulary describes a
castle, a monastery, a prison or a walled campus.

The enclosure: corner parts set the corner squares of a rectangular
perimeter band, edge parts sit on their side of the band, and wall segments
fill every perimeter gap between consecutive parts. Walkable walls are
3-wide single-room walled corridors (a 1-cell interior, per the feasibility
checks) that end one cell from the parts they join, so the builder's
auto-connect gives each end a facing-pair door into the room behind it.
Solid walls are 1-thick walkability-0 object strips on the perimeter line.
A corner with no part turns the corner: the horizontal side's run reaches
across the corner square and the vertical side's run starts three cells
in, so the two join without overlapping. The courtyard is sized from the
inside parts plus walking room, and the enclosure's outer size follows
from it — the block is never stretched to fill the zone.
"""
import dataclasses

from .layout_building import building_footprint, layout_building
from .model import OPPOSITE_SIDE, SIDE_DX_DY, Rect, shared_wall_cells

WALL_WIDTH = 3        # a walkable wall corridor's outer width (1-cell interior)
MIN_WALL_RUN = 3      # the shortest corridor run that still has an interior
MIN_BAND = 3          # the thinnest side band (room for a wall with no parts)
COURTYARD_CLEAR = {"small": 3, "medium": 5, "large": 7}
COURTYARD_FLOOR = 6   # a courtyard with no inside parts still gets air

SIDE_ORDER = ("south", "west", "north", "east")
# the corners each side runs between, in order along the side
SIDE_CORNERS = {"south": ("sw", "se"), "north": ("nw", "ne"),
                "west": ("sw", "nw"), "east": ("se", "ne")}


class CorridorOut:
    """One wall segment: a walled walkable region joining two parts."""
    def __init__(self, name, rect, wall):
        self.name = name
        self.rect = rect
        self.wall = wall


class WallStrip:
    """One solid wall run: a walkability-0 object footprint."""
    def __init__(self, pos, size):
        self.pos = pos
        self.size = size


class CompoundOut:
    def __init__(self, compound, rect):
        self.compound = compound
        self.name = compound.name
        self.rect = rect             # the whole block
        self.courtyard = rect        # the open ground inside the walls
        self.parts = []              # [BuildingOut], also in the zone's buildings
        self.corridors = []          # [CorridorOut] (walkable walls, a spine)
        self.wall_strips = []        # [WallStrip] (solid walls)
        self.paths = []              # [Rect] courtyard path pieces
        self.front_rect = None       # a row's front strip (street/walkway)
        self.front_kind = "none"     # street|parking|walkway|none
        self.parking = None          # (region name, Rect, [(template, pos)])
        self.gate_side = ""          # outward side of the first gate part
        self.gates = []              # [CompoundPart] with doors on both faces
        self.wall_material = "stone"
        self.failures = []


# ------------------------------------------------------------------ planning

def _inward_side(part):
    """The side a part's entrance faces: the courtyard side of a perimeter
    part, the head-on side of an inside part, away from the host of an
    attached part."""
    if part.slot_kind == "corner":
        return "east" if part.corner in ("nw", "sw") else "west"
    if part.slot_kind == "edge":
        return OPPOSITE_SIDE[part.side]
    if part.slot_kind == "inside":
        return OPPOSITE_SIDE[part.side] if part.side else "south"
    return part.side   # attached: the side it hangs on, away from its host


def _outward_side(part):
    """The side a gate part's outside entrance faces."""
    if part.slot_kind == "corner":
        return "north" if part.corner in ("nw", "ne") else "south"
    return part.side


def _design_of(zone, building):
    for d in zone.buildings:
        if d.name == building:
            return d
    return None


def part_plans(zone, compound, templates):
    """{building: (design, inward side, {side: (w, h)})} — each part's design
    with the entrance side the compound gives it, plus its footprint under
    every entrance side it could end up with (a gate's flips outward), so
    the compound can size its bands for the widest case and place with the
    exact one."""
    out = {}
    for part in compound.parts:
        design = _design_of(zone, part.building)
        if design is None:
            continue
        if compound.shape == "row":
            inward = compound.frontage      # every entrance faces the front
            sides = [inward]
        elif compound.shape in ("spine", "cluster"):
            inward = _spine_side(part, compound.axis)
            sides = [inward]
            outward = _spine_outward(part, compound.axis)
            for s in (outward if isinstance(outward, tuple) else (outward,)):
                if s != inward:
                    sides.append(s)
        else:
            inward = _inward_side(part)
            sides = [inward]
            if part.slot_kind in ("edge", "corner"):
                sides.append(_outward_side(part))
        fps = {}
        for s in dict.fromkeys(sides):
            fps[s] = building_footprint(
                dataclasses.replace(design, entrance_side=s), templates)
        out[part.building] = (design, inward, fps)
    return out


def _side_parts(compound):
    """({side: [CompoundPart in run order]}, {corner: CompoundPart}): corners
    first and last on their two sides, edge parts between them in
    start -> center -> end order."""
    corners = {p.corner: p for p in compound.parts if p.slot_kind == "corner"}
    sides = {}
    for side in SIDE_ORDER:
        edges = sorted((p for p in compound.parts
                        if p.slot_kind == "edge" and p.side == side),
                       key=lambda p: ({"start": 0, "center": 1, "end": 2}
                                      .get(p.offset, 1), p.building))
        first, last = SIDE_CORNERS[side]
        seq = ([corners[first]] if first in corners else []) + edges + \
              ([corners[last]] if last in corners else [])
        sides[side] = seq
    return sides, corners


def _host_of(part, compound):
    return next((p for p in compound.parts
                 if p.building == part.host and p.slot_kind != "attached"), None)


def _inside_rows(compound):
    """{row: [parts]}: the courtyard's inside parts in three rows (north,
    middle, south); a part attached to an inside part rides in its host's
    row. The middle row runs west-slotted, center, east-slotted."""
    rows = {"north": [], "middle": [], "south": []}
    order = {"west": 0, "": 1, "center": 1, "east": 2}

    def row_of(part):
        host = _host_of(part, compound) if part.slot_kind == "attached" else part
        if host is not None and host.slot_kind == "inside":
            return "north" if host.side == "north" else \
                   "south" if host.side == "south" else "middle"
        return None

    for p in compound.parts:
        r = row_of(p)
        if r is not None:
            rows[r].append(p)
    rows["middle"].sort(key=lambda p: order.get(
        p.side if p.slot_kind == "inside" else _host_of(p, compound).side, 1))
    return rows


def _fp(plans, part, side=None):
    """The part's (w, h) under its final entrance side (or a given one)."""
    design, inward, fps = plans[part.building]
    return fps[side or inward]


def _row_groups(row, plans):
    """A row as placement groups: a host and the parts attached to its east
    or west share one span; a part attached north or south rides above or
    below its host. Returns [{width, height, host, east: [], west: [],
    over: [], under: []}] in left-to-right order."""
    groups = []
    by_host = {}
    for p in row:
        fp = _fp(plans, p)
        if p.slot_kind == "attached" and p.side in ("east", "west") \
                and p.host in by_host:
            by_host[p.host][p.side].append(p)
            continue
        g = {"width": fp[0], "height": fp[1], "part": p, "east": [], "west": [],
             "over": [], "under": []}
        groups.append(g)
        by_host[p.building] = g
    for p in row:
        if p.slot_kind != "attached" or p.host not in by_host:
            continue
        fp = _fp(plans, p)
        g = by_host[p.host]
        if p.side in ("east", "west"):
            g[p.side].append(p)
            g["width"] += fp[0]
            continue
        spot = "over" if p.side == "north" else "under"
        g[spot].append(p)
        g["height"] = max(g["height"],
                          (fp[1] + 1) if spot == "over" else fp[1] + 1)
    return groups


def _perimeter_attached(compound):
    """Parts attached to a perimeter part: they reach into the courtyard."""
    out = []
    for p in compound.parts:
        if p.slot_kind != "attached":
            continue
        host = _host_of(p, compound)
        if host is not None and host.slot_kind in ("corner", "edge"):
            out.append((p, host))
    return out


def _plan_geometry(zone, compound, templates, plans):
    """The enclosure's shape from its parts: the four side bands, the
    courtyard the inside parts need (with walking room round every one),
    and the outer size that follows from both."""
    sides, corners = _side_parts(compound)
    clear = COURTYARD_CLEAR[compound.courtyard]

    def band(parts, axis):
        best = MIN_BAND
        for p in parts:
            for fp in plans[p.building][2].values():
                best = max(best, fp[axis])
        return best

    geo = {"west": band(sides["west"], 0), "east": band(sides["east"], 0),
           "north": band(sides["north"], 1), "south": band(sides["south"], 1),
           "clear": clear}

    # the courtyard: rows of inside parts (attached parts riding with their
    # host), clear ground round everything, wide enough for the edge parts
    # on each side and a wall run either side of them
    rows = _inside_rows(compound)
    need_w, row_heights = 0, []
    live_rows = [rows[r] for r in ("north", "middle", "south") if rows[r]]
    for row in live_rows:
        groups = _row_groups(row, plans)
        w = sum(g["width"] for g in groups) + (len(groups) - 1) * clear
        need_w = max(need_w, w + 2 * clear)
        row_heights.append(max(g["height"] for g in groups))
    need_h = sum(row_heights) + (len(live_rows) - 1) * clear + 2 * clear \
        if live_rows else 2 * clear
    # parts hanging off the perimeter reach into the courtyard: their side
    # needs its clear margin plus their depth
    for (p, host) in _perimeter_attached(compound):
        fp = _fp(plans, p)
        inward = OPPOSITE_SIDE[_outward_side(host)]
        if inward in ("north", "south"):
            need_h += fp[1] + 1
        else:
            need_w += fp[0] + 1
    # edge parts sit on their side with a wall run either side of each
    for side in ("north", "south"):
        edges = [p for p in sides[side] if p.slot_kind == "edge"]
        if edges:
            widest = sum(max(fp[0] for fp in plans[p.building][2].values())
                         for p in edges)
            need_w = max(need_w, widest + (len(edges) + 1) * MIN_WALL_RUN)
    for side in ("east", "west"):
        edges = [p for p in sides[side] if p.slot_kind == "edge"]
        if edges:
            widest = sum(max(fp[1] for fp in plans[p.building][2].values())
                         for p in edges)
            need_h = max(need_h, widest + (len(edges) + 1) * MIN_WALL_RUN)

    geo["court_w"] = max(need_w + 2, COURTYARD_FLOOR + 2 * clear)
    geo["court_h"] = max(need_h + 2, COURTYARD_FLOOR + 2 * clear)
    geo["outer"] = (geo["west"] + geo["court_w"] + geo["east"],
                    geo["south"] + geo["court_h"] + geo["north"])
    return geo


def compound_footprint(zone, compound, templates):
    """The (w, h) block the compound occupies — one place so the zone packer
    and the layout agree, like building_footprint for a building."""
    plans = part_plans(zone, compound, templates)
    if not plans:
        return (MIN_BAND * 3, MIN_BAND * 3)
    if compound.shape == "row":
        return _row_geometry(compound, plans)[0]
    if compound.shape in ("spine", "cluster"):
        return _spine_geometry(compound, plans)[0]
    return _plan_geometry(zone, compound, templates, plans)["outer"]


# ------------------------------------------------------------------ row

FRONT_DEPTH = {"street": 3, "walkway": 3, "parking": 5, "none": 0}
VEHICLE_WORDS = ("cart", "wagon", "car", "van", "truck", "vehicle",
                 "transport", "coach", "carriage", "dray", "pod")


def _vehicle_template(templates):
    """The catalogue's parked-vehicle piece, biggest first (a cart over a
    scooter), or None."""
    hits = [t for t in templates.values()
            if any(w in t.name.lower() or w in " ".join(t.tags).lower()
                   for w in VEHICLE_WORDS)]
    return max(hits, key=lambda t: (t.size[0] * t.size[1], t.name)) if hits else None


def _row_geometry(compound, plans):
    """The row's own frame: parts side by side along the axis the frontage
    faces, butted directly against a linked predecessor (the builder joins
    them with a door) and one cell clear of the rest (no door between
    strangers), the front strip in front of them. Returns ((w, h), placements,
    front rect or None)."""
    frontage = compound.frontage
    along_x = frontage in ("north", "south")
    parts = sorted((p for p in compound.parts if p.slot_kind == "row"),
                   key=lambda p: (p.index, p.building))
    fps, pos, cursor = {}, {}, 0
    for i, p in enumerate(parts):
        fp = plans[p.building][2][frontage]
        fps[p.building] = fp
        if i:
            cursor += 0 if parts[i].linked else 1
        pos[p.building] = (cursor, fp)
        cursor += fp[0] if along_x else fp[1]
    depth = max((fp[1] if along_x else fp[0]) for fp in fps.values()) if fps else MIN_BAND
    length = cursor
    front_d = FRONT_DEPTH[compound.front]
    if along_x:
        # the strip lies between the row and the frontage edge of the block
        front = Rect(0, 0 if frontage == "south" else depth,
                     max(1, length), front_d) if front_d else None
        block = (max(1, length), depth + front_d)
    else:
        front = Rect(0 if frontage == "west" else depth, 0,
                     front_d, max(1, length)) if front_d else None
        block = (depth + front_d, max(1, length))
    return block, (parts, fps, pos, depth, front), front


def _place_row(compound, rect, plans, geo):
    """The row's parts inside its block rect: same frame, shifted."""
    (parts, fps, pos, depth, front) = geo
    frontage = compound.frontage
    along_x = frontage in ("north", "south")
    front_d = FRONT_DEPTH[compound.front]
    out = {}
    for p in parts:
        (a, fp) = pos[p.building]
        if along_x:
            y = 0 if frontage == "north" else front_d
            out[p.building] = Rect(rect.x + a, rect.y + y, fp[0], fp[1])
        else:
            x = 0 if frontage == "east" else front_d
            out[p.building] = Rect(rect.x + x, rect.y + a, fp[0], fp[1])
    frect = front.shifted(rect.x, rect.y) if front is not None else None
    return out, frect


# ------------------------------------------------------------------ spine

def _spine_side(part, axis):
    """The side a spine part's entrance faces: into the spine."""
    if part.slot_kind == "hub":
        return {"ns": "south", "ew": "west"}[axis]
    if part.slot_kind == "spine_end":
        return "north" if part.side == "start" else "south" if axis == "ns" else \
               "east" if part.side == "start" else "west"
    if axis == "ns":
        return "east" if part.side == "left" else "west"
    return "north" if part.side == "left" else "south"


def _spine_outward(part, axis):
    """The side a spine part's outside entrance faces (the gate into the
    block)."""
    if part.slot_kind == "hub":
        return {"ns": ("south", "north"), "ew": ("west", "east")}[axis]
    if part.slot_kind == "spine_end":
        return {"ns": ("south", "north"), "ew": ("west", "east")}[axis]
    if axis == "ns":
        return "west" if part.side == "left" else "east"
    return "south" if part.side == "left" else "north"


def _spine_geometry(compound, plans):
    """The spine's own frame: a walled corridor (the spine, spineWidth wide)
    with parts butted along it on the left and right, end parts capping it,
    and an optional hub part at its centre or one end. ``cluster`` is the
    width-0 special case: no corridor, the parts pack round the hub. All the
    geometry runs in a north-south frame and transposes for an east-west
    axis. Returns ((w, h), geo, [corridor rects])."""
    sw = compound.spine_width
    hub = next((p for p in compound.parts if p.slot_kind == "hub"), None)
    lefts = sorted((p for p in compound.parts
                    if p.slot_kind == "spine" and p.side == "left"),
                   key=lambda p: (p.index, p.building))
    rights = sorted((p for p in compound.parts
                     if p.slot_kind == "spine" and p.side == "right"),
                    key=lambda p: (p.index, p.building))
    cap_s = next((p for p in compound.parts
                  if p.slot_kind == "spine_end" and p.side == "start"), None)
    cap_n = next((p for p in compound.parts
                  if p.slot_kind == "spine_end" and p.side == "end"), None)

    def fp(part, side=None):
        design, inward, fps = plans[part.building]
        return fps[side or _spine_side(part, compound.axis)]

    # every part's cross extent (its depth into its column) and along extent
    cross_of = {p.building: fp(p)[0] for p in lefts + rights}
    along_of = {p.building: fp(p)[1] for p in lefts + rights}
    ld = max([cross_of[p.building] for p in lefts] + [0])
    rd = max([cross_of[p.building] for p in rights] + [0])
    hub_w = hub_a = 0
    if hub is not None:
        hub_w, hub_a = fp(hub)[0], fp(hub)[1]
    cross = max(ld + sw + rd, 2 * max(ld, rd) + sw if hub else 0, hub_w + 2)
    scx = (cross - sw) // 2

    placements, corridors = {}, []

    def put(part, rect):
        placements[part.building] = rect

    # the start cap, then the spine's first row
    y = 0
    if cap_s is not None:
        f = fp(cap_s)
        put(cap_s, Rect(scx + sw // 2 - f[0] // 2, y, f[0], f[1]))
        y += f[1] + 1
    spine_y0 = y

    # where the hub sits on the along axis, from the columns' extent alone
    col_span = max(sum(along_of[p.building] + 1 for p in lefts),
                   sum(along_of[p.building] + 1 for p in rights))
    hub_rect = None
    if hub is not None:
        if compound.hub_pos == "start":
            hub_y = spine_y0
        elif compound.hub_pos == "end":
            hub_y = spine_y0 + col_span
        else:
            hub_y = spine_y0 + max(0, (col_span - hub_a) // 2)
        hub_rect = Rect(scx + sw // 2 - hub_w // 2, hub_y, hub_w, hub_a)
        put(hub, hub_rect)

    # the columns, stacked with one clear cell between parts (no doors
    # between strangers), skipping the hub's rows either side
    def column(parts_list, side):
        cy = spine_y0
        for p in parts_list:
            if hub_rect is not None and cy < hub_rect.y1 + 2:
                cy = hub_rect.y1 + 2
            c = cross_of[p.building]
            a = along_of[p.building]
            put(p, Rect(scx - c if side == "left" else scx + sw, cy, c, a))
            cy += a + 1
        return cy

    col_end = max(column(lefts, "left"), column(rights, "right"))
    top = col_end - 1
    if hub_rect is not None:
        top = max(top, hub_rect.y1)

    # the end cap above everything
    if cap_n is not None:
        f = fp(cap_n)
        put(cap_n, Rect(scx + sw // 2 - f[0] // 2, top + 1, f[0], f[1]))
        top = top + 1 + f[1] - 1

    # the spine run(s), split around a centre hub
    if sw > 0:
        runs = [(spine_y0, top)]
        if hub_rect is not None and compound.hub_pos == "center":
            runs = [(spine_y0, hub_rect.y - 1), (hub_rect.y1 + 1, top)]
        elif hub_rect is not None and compound.hub_pos == "start":
            runs = [(hub_rect.y1 + 1, top)]
        elif hub_rect is not None and compound.hub_pos == "end":
            runs = [(spine_y0, hub_rect.y - 1)]
        for (a0, a1) in runs:
            if a1 >= a0:
                corridors.append(Rect(scx, a0, sw, a1 - a0 + 1))

    rects = list(placements.values()) + corridors
    x0 = min(r.x for r in rects)
    y0 = min(r.y for r in rects)
    geo = {"placements": {n: r.shifted(-x0, -y0) for n, r in placements.items()},
           "corridors": [r.shifted(-x0, -y0) for r in corridors],
           "hub": hub, "order": lefts + rights + [cap_s, cap_n],
           "cross": cross}
    all_rects = list(geo["placements"].values()) + geo["corridors"]
    if compound.axis == "ew":
        geo["placements"] = {n: _transpose(r) for n, r in geo["placements"].items()}
        geo["corridors"] = [_transpose(r) for r in geo["corridors"]]
        all_rects = list(geo["placements"].values()) + geo["corridors"]
    w = max(r.x1 for r in all_rects) + 1
    h = max(r.y1 for r in all_rects) + 1
    return (w, h), geo, geo["corridors"]


def _transpose(rect):
    """A rect in the mirrored frame: (x, y, w, h) -> (y, x, h, w)."""
    return Rect(rect.y, rect.x, rect.h, rect.w)


# ------------------------------------------------------------------ placing

def _final_side(part, gates):
    if part in gates:
        return _outward_side(part)
    return _inward_side(part)


def _place_perimeter(part, plans, geo, rect, side):
    """The part's rect with its final entrance orientation, flush with its
    slot. Bands were sized for the widest orientation, so a narrower part
    leaves a pocket of open ground inside the walls — harmless."""
    fp = plans[part.building][2][side]
    w, h = fp
    if part.slot_kind == "corner":
        west, north = CORNER_WEST_NORTH[part.corner]
        x = rect.x if west else rect.x1 - w + 1
        y = rect.y1 - h + 1 if north else rect.y
        return Rect(x, y, w, h)
    if part.side in ("north", "south"):
        span0, span1 = rect.x + geo["west"], rect.x1 - geo["east"]
        x = span0 if part.offset == "start" else \
            span1 - w + 1 if part.offset == "end" else (span0 + span1 - w + 1) // 2
        y = rect.y1 - h + 1 if part.side == "north" else rect.y
        return Rect(x, y, w, h)
    span0, span1 = rect.y + geo["south"], rect.y1 - geo["north"]
    y = span0 if part.offset == "start" else \
        span1 - h + 1 if part.offset == "end" else (span0 + span1 - h + 1) // 2
    x = rect.x1 - w + 1 if part.side == "east" else rect.x
    return Rect(x, y, w, h)


CORNER_WEST_NORTH = {"nw": (True, True), "ne": (False, True),
                     "sw": (True, False), "se": (False, False)}


def _place_rows(compound, plans, geo, court):
    """{building: Rect} for the inside parts and the parts attached to them:
    rows stacked north to middle to south, groups side by side with clear
    ground between, attached parts beside, above or below their host."""
    clear = geo["clear"]
    rows = _inside_rows(compound)
    live = [(name, rows[name]) for name in ("north", "middle", "south") if rows[name]]
    out = {}
    if not live:
        return out
    shapes = []
    for (_name, row) in live:
        groups = _row_groups(row, plans)
        w = sum(g["width"] for g in groups) + (len(groups) - 1) * clear
        h = max(g["height"] for g in groups)
        shapes.append((groups, w, h))
    total = sum(h for (_g, _w, h) in shapes) + (len(shapes) - 1) * clear
    y = court.y1 - shapes[0][2] + 1     # the north row starts at the top
    for i, (groups, w, _h) in enumerate(shapes):
        x = court.x + max(0, (court.w - w) // 2)
        for g in groups:
            p = g["part"]
            fp = _fp(plans, p)
            west_total = sum(_fp(plans, q)[0] for q in g["west"])
            under = sum(_fp(plans, q)[1] for q in g["under"])
            gy = y + (g["height"] - fp[1] - under) // 2 + under
            out[p.building] = Rect(x + west_total, gy, fp[0], fp[1])
            wx = x + west_total
            for q in g["west"]:
                qfp = _fp(plans, q)
                wx -= qfp[0]
                out[q.building] = Rect(wx, gy + (fp[1] - qfp[1]) // 2, qfp[0], qfp[1])
            for q in g["east"]:
                qfp = _fp(plans, q)
                out[q.building] = Rect(out[p.building].x1 + 1,
                                       gy + (fp[1] - qfp[1]) // 2, qfp[0], qfp[1])
            for q in g["over"]:
                qfp = _fp(plans, q)
                out[q.building] = Rect(out[p.building].x + (fp[0] - qfp[0]) // 2,
                                       out[p.building].y1 + 1, qfp[0], qfp[1])
            for q in g["under"]:
                qfp = _fp(plans, q)
                out[q.building] = Rect(out[p.building].x + (fp[0] - qfp[0]) // 2,
                                       out[p.building].y - qfp[1], qfp[0], qfp[1])
            x += g["width"] + clear
        if i + 1 < len(shapes):
            y = y - clear - shapes[i + 1][2]
    return out


def _wall_spans(compound, placed, geo, rect):
    """The perimeter gaps between consecutive perimeter parts as (side, lo,
    hi) spans. A corner with no part turns the corner: the horizontal run
    reaches to the block edge across the corner square, the vertical run
    starts three cells in, so the two join (one cell apart) without
    overlapping."""
    sides, corners = _side_parts(compound)
    spans = []
    for side in SIDE_ORDER:
        horizontal = side in ("south", "north")
        seq = [placed[p.building] for p in sides[side] if p.building in placed]
        pts = [(r.x, r.x1) if horizontal else (r.y, r.y1) for r in seq]
        first_c, last_c = SIDE_CORNERS[side]
        if horizontal:
            lo0 = rect.x if first_c not in corners else pts[0][1] + 1
            hi0 = rect.x1 if last_c not in corners else pts[-1][0] - 1
        else:
            # a missing corner: the horizontal side takes the corner's outer
            # WALL_WIDTH cells, so this side starts/ends that far in
            lo0 = rect.y + WALL_WIDTH if first_c not in corners else pts[0][1] + 1
            hi0 = rect.y1 - WALL_WIDTH if last_c not in corners else pts[-1][0] - 1
        if not pts:
            if lo0 <= hi0:
                spans.append((side, lo0, hi0))
            continue
        if lo0 < pts[0][0]:
            spans.append((side, lo0, pts[0][0] - 1))
        for (a0, a1), (b0, _b1) in zip(pts, pts[1:]):
            if a1 + 1 < b0:
                spans.append((side, a1 + 1, b0 - 1))
        if pts[-1][1] < hi0:
            spans.append((side, pts[-1][1] + 1, hi0))
    return spans


def _span_rect(side, lo, hi, rect):
    """The corridor rect for one span: WALL_WIDTH thick on the perimeter line."""
    if side == "south":
        return Rect(lo, rect.y, hi - lo + 1, WALL_WIDTH)
    if side == "north":
        return Rect(lo, rect.y1 - WALL_WIDTH + 1, hi - lo + 1, WALL_WIDTH)
    if side == "west":
        return Rect(rect.x, lo, WALL_WIDTH, hi - lo + 1)
    return Rect(rect.x1 - WALL_WIDTH + 1, lo, WALL_WIDTH, hi - lo + 1)


def _pick_gates(compound, plans, geo, rect, mouths):
    """The marked gate parts, else the edge part nearest a road mouth, else
    the first edge part, else the first corner part."""
    gates = [p for p in compound.parts if p.gate]
    if gates:
        return gates
    edges = [p for p in compound.parts if p.slot_kind == "edge"]
    if edges and mouths:
        best = None
        for p in edges:
            for (mside, (mx, my)) in mouths:
                if mside != _outward_side(p):
                    continue
                fp = plans[p.building][2][_final_side(p, ())]
                cx, cy = _perimeter_center(p, fp, geo, rect)
                d = abs(cx - mx) + abs(cy - my)
                if best is None or d < best[0]:
                    best = (d, p)
        if best is not None:
            return [best[1]]
    if edges:
        return [edges[0]]
    corners = [p for p in compound.parts if p.slot_kind == "corner"]
    return [corners[0]] if corners else []


def _perimeter_center(part, fp, geo, rect):
    w, h = fp
    if part.slot_kind == "corner":
        west, north = CORNER_WEST_NORTH[part.corner]
        x = rect.x + w / 2.0 if west else rect.x1 - w / 2.0
        y = rect.y1 - h / 2.0 if north else rect.y + h / 2.0
        return (x, y)
    return rect.center()


def place_compound(zone, compound, rect, templates, rng, furnish, mouths=None):
    """Lay the compound out inside `rect` (its block). Returns a CompoundOut
    whose parts are BuildingOuts the caller appends to the zone's buildings;
    ``furnish(b)`` furnishes one part's rooms (the zone's own _furnish).
    ``mouths`` are the zone's road mouths as (side, (cx, cy)) clusters, used
    to pick the default gate."""
    from .layout_zone import BuildingOut

    out = CompoundOut(compound, rect)
    plans = part_plans(zone, compound, templates)
    if not plans:
        out.failures.append((f"compound {compound.name}", "no part buildings"))
        return out
    if compound.shape == "row":
        return _place_row_compound(zone, compound, rect, templates, rng,
                                   furnish, mouths, out, plans)
    if compound.shape in ("spine", "cluster"):
        return _place_spine_compound(zone, compound, rect, templates, rng,
                                     furnish, mouths, out, plans)
    return _place_enclosure(zone, compound, rect, templates, rng,
                            furnish, mouths, out, plans)


def _build_parts(zone, compound, out, placed, sides, plans, templates, rng,
                 furnish, doors_extra=None):
    """Every part's BuildingOut under its final orientation, furnished, with
    the auto-connect door cells the builder will open between touching
    parts and corridors recorded on the rooms behind them."""
    from .layout_zone import BuildingOut

    rects = []
    for part in compound.parts:
        r = placed.get(part.building)
        if r is None:
            out.failures.append((f"compound {compound.name} part {part.building}",
                                 "no slot placed it"))
            continue
        design = _design_of(zone, part.building)
        side = sides.get(part.building, design.entrance_side)
        d = dataclasses.replace(design, entrance_side=side)
        b = BuildingOut(None, r, None)
        b.layout = layout_building(d, (r.x, r.y), rng, templates)
        b.lot = r
        b.compound = compound.name
        if b.layout.rect != r:
            out.failures.append((f"compound {compound.name} part {part.building}",
                                 "its layout rect moved under re-resolution"))
            placed[part.building] = r = b.layout.rect
        for cell in (doors_extra or {}).get(part.building, []):
            _door_into_room(b.layout, cell)
        out.parts.append(b)
        rects.append((b.layout, r))
    for i, (bl_a, ra) in enumerate(rects):
        for (bl_b, rb) in rects[i + 1:]:
            for cell in shared_wall_cells(ra, rb):
                if ra.contains_cell(cell):
                    _door_into_room(bl_a, cell)
                if rb.contains_cell(cell):
                    _door_into_room(bl_b, cell)
        for corridor in out.corridors:
            for cell in shared_wall_cells(ra, corridor.rect):
                if ra.contains_cell(cell):
                    _door_into_room(bl_a, cell)
    for b in out.parts:
        furnish(b)


def _place_row_compound(zone, compound, rect, templates, rng, furnish,
                        mouths, out, plans):
    """A row: parts side by side facing the frontage, a street, walkway or
    parking strip in front. Every part's entrance opens onto the strip, so
    every part is its own gate; linked neighbours butt (and join by a door),
    the rest keep one clear cell (no door between strangers)."""
    _block, geo, front = _row_geometry(compound, plans)
    placed, frect = _place_row(compound, rect, plans, geo)
    sides = {p.building: compound.frontage
             for p in compound.parts if p.slot_kind == "row"}
    for p in compound.parts:   # an attached part keeps its own side
        if p.slot_kind == "attached":
            host_r = placed.get(p.host)
            if host_r is not None:
                fp = _fp(plans, p)
                placed[p.building] = _attached_rect(host_r, p.side, fp)
                sides[p.building] = p.side
    materials = [d.wall for d in zone.buildings if d.name in plans]
    out.wall_material = max(set(materials), key=materials.count) if materials else "stone"
    if frect is not None:
        out.front_rect, out.front_kind = frect, compound.front
        if compound.front == "parking":
            veh = _vehicle_template(templates)
            slots = []
            if veh is not None:
                vw, vh = veh.size
                along_x = frect.w >= frect.h
                n = max(0, ((frect.w if along_x else frect.h) - 2) // (vw + 1))
                for i in range(n):
                    if along_x:
                        pos = (frect.x + 1 + i * (vw + 1),
                               frect.y + max(0, (frect.h - vh) // 2))
                    else:
                        pos = (frect.x + max(0, (frect.w - vw) // 2),
                               frect.y + 1 + i * (vh + 1))
                    if pos[0] + vw <= frect.x1 and pos[1] + vh <= frect.y1:
                        slots.append((veh.name, pos))
            out.parking = (f"{compound.name} Parking", frect, slots)
    out.gates = [p for p in compound.parts if p.slot_kind == "row"]
    out.gate_side = compound.frontage
    _build_parts(zone, compound, out, placed, sides, plans, templates, rng, furnish)
    return out


def _attached_rect(host_r, side, fp):
    """A part attached to its host's side, sharing that wall."""
    if side == "east":
        return Rect(host_r.x1 + 1, host_r.y + (host_r.h - fp[1]) // 2, fp[0], fp[1])
    if side == "west":
        return Rect(host_r.x - fp[0], host_r.y + (host_r.h - fp[1]) // 2, fp[0], fp[1])
    if side == "north":
        return Rect(host_r.x + (host_r.w - fp[0]) // 2, host_r.y1 + 1, fp[0], fp[1])
    return Rect(host_r.x + (host_r.w - fp[0]) // 2, host_r.y - fp[1], fp[0], fp[1])


def _place_spine_compound(zone, compound, rect, templates, rng, furnish,
                          mouths, out, plans):
    """A spine: a walled corridor with parts butted along it (each touching
    it, so the builder's auto-connect gives every one a door onto it), end
    parts capping it and an optional hub at its centre or an end. The hub —
    or the first part — faces outward and is the block's gate."""
    _block, geo, _corr = _spine_geometry(compound, plans)
    placed = {n: r.shifted(rect.x, rect.y)
              for n, r in geo["placements"].items()}
    sides = {p.building: _spine_side(p, compound.axis)
             for p in compound.parts
             if p.slot_kind in ("spine", "spine_end", "hub")}
    materials = [d.wall for d in zone.buildings if d.name in plans]
    out.wall_material = max(set(materials), key=materials.count) if materials else "stone"
    for i, r in enumerate(geo["corridors"]):
        out.corridors.append(CorridorOut(f"{compound.name} Spine"
                                         + (f" {i + 1}" if i else ""),
                                         r.shifted(rect.x, rect.y),
                                         out.wall_material))
    for p in compound.parts:   # wings branch off any part
        if p.slot_kind == "attached":
            host_r = placed.get(p.host)
            if host_r is not None:
                fp = _fp(plans, p)
                placed[p.building] = _attached_rect(host_r, p.side, fp)
                sides[p.building] = p.side
    # the gate: the hub when there is one (facing away from the spine at its
    # end, or south/west from the centre), else the first part
    hub = geo["hub"]
    gate = hub or next((p for p in geo["order"] if p is not None), None)
    if gate is not None:
        outward = _spine_outward(gate, compound.axis)
        if isinstance(outward, tuple):
            pick = {"start": 0, "center": 0, "end": 1}[compound.hub_pos] \
                if gate is hub else 0
            outward = outward[pick]
        sides[gate.building] = outward
        out.gates = [gate]
        out.gate_side = outward
    _build_parts(zone, compound, out, placed, sides, plans, templates, rng, furnish)
    return out


def _place_enclosure(zone, compound, rect, templates, rng, furnish,
                     mouths, out, plans):
    from .layout_zone import BuildingOut

    geo = _plan_geometry(zone, compound, templates, plans)
    out.courtyard = Rect(rect.x + geo["west"], rect.y + geo["south"],
                         geo["court_w"], geo["court_h"])

    gates = _pick_gates(compound, plans, geo, rect, mouths)
    out.gates = gates
    out.gate_side = _outward_side(gates[0]) if gates else ""
    walls = compound.walls
    if not gates and walls != "none":
        # walls with no part to be the gate would seal the courtyard shut
        walls = "none"
        out.failures.append((f"compound {compound.name}",
                             "walls left open: no part can be the gate"))

    # ---- perimeter parts, each with its final orientation
    placed = {}
    for part in compound.parts:
        if part.slot_kind in ("corner", "edge"):
            side = _final_side(part, gates)
            placed[part.building] = _place_perimeter(part, plans, geo, rect, side)

    # ---- inside parts and their attached parts in the courtyard
    inside = _place_rows(compound, plans, geo, out.courtyard)
    for (p, host) in _perimeter_attached(compound):
        if p.building in inside:
            continue
        hrect = placed[host.building]
        fp = _fp(plans, p)
        if p.side == "east":
            r = Rect(hrect.x1 + 1, hrect.y + (hrect.h - fp[1]) // 2, fp[0], fp[1])
        elif p.side == "west":
            r = Rect(hrect.x - fp[0], hrect.y + (hrect.h - fp[1]) // 2, fp[0], fp[1])
        elif p.side == "north":
            r = Rect(hrect.x + (hrect.w - fp[0]) // 2, hrect.y1 + 1, fp[0], fp[1])
        else:
            r = Rect(hrect.x + (hrect.w - fp[0]) // 2, hrect.y - fp[1], fp[0], fp[1])
        inside[p.building] = r
    placed.update(inside)

    # ---- the walls between the perimeter parts
    materials = [d.wall for d in zone.buildings if d.name in plans]
    out.wall_material = max(set(materials), key=materials.count) if materials else "stone"
    spans = _wall_spans(compound, placed, geo, rect)
    if walls == "walkable":
        for i, (side, lo, hi) in enumerate(spans):
            if hi - lo + 1 < MIN_WALL_RUN:
                continue   # too short to walk; the parts nearly touch already
            name = f"{compound.name} Wall" + (f" {i + 1}" if i else "")
            out.corridors.append(CorridorOut(name, _span_rect(side, lo, hi, rect),
                                             out.wall_material))
    elif walls == "solid":
        for i, (side, lo, hi) in enumerate(spans):
            if side in ("south", "north"):
                y = rect.y if side == "south" else rect.y1
                out.wall_strips.append(WallStrip((lo, y), (hi - lo + 1, 1)))
            else:
                x = rect.x if side == "west" else rect.x1
                out.wall_strips.append(WallStrip((x, lo), (1, hi - lo + 1)))

    # ---- the parts themselves: their layouts under the same orientation
    # (the resolved footprint is deterministic, so each rect matches the
    # one the walls were spanned from), the gate's courtyard door added
    for part in compound.parts:
        r = placed.get(part.building)
        if r is None:
            out.failures.append((f"compound {compound.name} part {part.building}",
                                 "no slot placed it"))
            continue
        design = _design_of(zone, part.building)
        side = _final_side(part, gates)
        d = dataclasses.replace(design, entrance_side=side)
        b = BuildingOut(None, r, None)
        b.layout = layout_building(d, (r.x, r.y), rng, templates)
        b.lot = r
        b.compound = compound.name
        if b.layout.rect != r:
            out.failures.append((f"compound {compound.name} part {part.building}",
                                 "its layout rect moved under re-resolution"))
            r = b.layout.rect
        if part in gates:
            _add_courtyard_door(b, OPPOSITE_SIDE[side])
        out.parts.append(b)

    # every door the builder's auto-connect will open between touching
    # parts and walls: the room behind each one learns its cell now, so
    # the furniture keeps the walkway clear. A facing pair's cells belong
    # one to each side; a shared-line cell belongs to both.
    rects = [(b.layout, b.layout.rect) for b in out.parts]
    for i, (bl_a, ra) in enumerate(rects):
        for (bl_b, rb) in rects[i + 1:]:
            for cell in shared_wall_cells(ra, rb):
                if ra.contains_cell(cell):
                    _door_into_room(bl_a, cell)
                if rb.contains_cell(cell):
                    _door_into_room(bl_b, cell)
        for corridor in out.corridors:
            for cell in shared_wall_cells(ra, corridor.rect):
                if ra.contains_cell(cell):
                    _door_into_room(bl_a, cell)
    for b in out.parts:
        furnish(b)
    return out


def _door_into_room(bl, cell):
    """Record an auto-connect door cell on the building and the room whose
    wall it sits on, so the room's furniture keeps it clear."""
    extra = list(getattr(bl, "extra_doors", []))
    if cell not in extra:
        extra.append(cell)
    bl.extra_doors = extra
    x, y = cell
    for room in bl.rooms:
        if room.rect.contains_cell(cell) and \
                (x in (room.rect.x, room.rect.x1) or y in (room.rect.y, room.rect.y1)):
            room.doors.add(cell)
            return


def _add_courtyard_door(b, side):
    """The gate part's second door: the middle cell of its courtyard-facing
    wall, given to the building region and the room behind it, so the
    room's furniture keeps the walkway clear."""
    from .layout_building import _entrance_cell
    cell = _entrance_cell(b.layout.rect, side)
    extra = list(getattr(b.layout, "extra_doors", [])) + [cell]
    b.layout.extra_doors = extra
    for room in b.layout.rooms:
        x, y = cell
        if room.rect.contains_cell(cell) and \
                (x in (room.rect.x, room.rect.x1) or y in (room.rect.y, room.rect.y1)):
            room.doors.add(cell)
            break


def gate_courtyard_cell(compound_out):
    """The courtyard cell just outside the first gate's courtyard door, or
    None when the compound has no gate."""
    if not compound_out.gates:
        return None
    gate = compound_out.gates[0]
    extra = None
    for b in compound_out.parts:
        if b.layout.design.name == gate.building:
            extra = getattr(b.layout, "extra_doors", None)
            break
    if not extra:
        return None
    inward = OPPOSITE_SIDE[_outward_side(gate)]
    dx, dy = SIDE_DX_DY[inward]
    return (extra[0][0] + dx, extra[0][1] + dy)


def courtyard_paths(compound_out, targets):
    """1-wide path rects from the gate's courtyard door to each target cell
    (an inside part's entrance approach): one L shape each, clipped to the
    courtyard and clear of the parts and walls."""
    start = gate_courtyard_cell(compound_out)
    if start is None or not targets:
        return []
    court = compound_out.courtyard
    blocked = set()
    for b in compound_out.parts:
        blocked |= b.layout.rect.cells()
    for c in compound_out.corridors:
        blocked |= c.rect.cells()
    out = []
    for cell in targets:
        cells = _l_shape(start, cell)
        keep = [c for c in cells if court.contains_cell(c) and c not in blocked]
        if keep:
            xs = [c[0] for c in keep]
            ys = [c[1] for c in keep]
            out.append(Rect(min(xs), min(ys), max(xs) - min(xs) + 1,
                            max(ys) - min(ys) + 1))
    # drop pieces that overlap an earlier one (crossing paths share ground)
    merged = []
    for r in out:
        if not any(r.intersects(o) for o in merged):
            merged.append(r)
    return merged


def _l_shape(a, b):
    (x0, y0), (x1, y1) = a, b
    cells = [(x, y0) for x in range(min(x0, x1), max(x0, x1) + 1)]
    cells += [(x1, y) for y in range(min(y0, y1) + 1, max(y0, y1) + 1)]
    return cells
