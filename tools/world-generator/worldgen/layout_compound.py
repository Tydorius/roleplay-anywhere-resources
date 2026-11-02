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
        self.corridors = []          # [CorridorOut] (walkable walls)
        self.wall_strips = []        # [WallStrip] (solid walls)
        self.paths = []              # [Rect] courtyard path pieces
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
    the enclosure can size its bands for the widest case and place with the
    exact one."""
    out = {}
    for part in compound.parts:
        design = _design_of(zone, part.building)
        if design is None:
            continue
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
    return _plan_geometry(zone, compound, templates, plans)["outer"]


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
