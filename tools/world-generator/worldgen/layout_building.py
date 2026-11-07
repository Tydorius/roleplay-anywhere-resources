"""Rooms in a building.

Rooms are sized from what goes in them: each room's area is its furniture
footprints x2.5 plus a walkway allowance (3x3 minimum), and the building
footprint covers the sum — the sizeClass as a floor, 28x22 as a cap. Past
the cap a room that still cannot hold its furniture is split into two
connected rooms ("Dining Hall" and "Dining Hall Annex") before anything is
dropped; only then are the lowest-value pieces (decorative before
functional) dropped and recorded. The rooms are made with guillotine cuts
weighted by those areas, in a recursive strip pattern that mirrors the
connection tree rooted at the entrance room, so every connected pair of
rooms ends up sharing a wall: the room's strip is cut along the entrance
side first, its children fill the remainder side by side, each cut again
above/beside it. A door cell pair goes on every shared wall (the builder
auto-connects touching sibling rooms the same way), plus the entrance on
the given exterior side.
"""
import dataclasses
import math

from .layout_map import _sizes_mins
from .model import (FurniturePlan, Rect, RoomSpec, SIDE_DX_DY, bed_capacity,
                    shared_wall_cells)

FOOTPRINTS = {   # sizeClass -> (w, h); the outer ring is wall, so usable space is w-2 x h-2
    "hut": (8, 7),
    "small": (11, 8),
    "medium": (13, 10),
    "large": (16, 12),
    "hall": (20, 13),
}
SHARE_WEIGHT = {"small": 1, "medium": 2, "large": 3}
MIN_SIDE = 4  # a room narrower than 4 has an interior of 2, too thin for a bed

# rooms need floor space: 2 rooms do not fit a hut, 3-4 need large/hall
# (three stacked strips alone need 3 x MIN_SIDE = 12 rows)
ROOM_FLOOR = {2: "small", 3: "large", 4: "hall"}

FURN_SCALE = 2.5       # a room holds furniture on about a quarter of its cells
SOLID_FURN_SCALE = 1.6  # solid pieces also claim their standing room
ROOM_WALKWAY = 12      # per room: door reserves and the clear spine
MIN_ROOM_AREA = 9      # 3x3
ROOM_HEADROOM = 1.15   # split slack over the summed room areas
CAP = (28, 22)         # the largest building footprint
MAX_ANNEXES = 3        # room splits per building before pieces start dropping

# tags that make a piece functional; anything else drops first at the cap
FUNCTIONAL_TAGS = {"work", "storage", "seat", "table", "eat", "cook", "fire",
                   "water", "trade", "craft", "prayer", "landmark", "light",
                   "rest", "bed", "cart", "fuel", "horses", "animals", "grain",
                   "ale", "metal", "field", "fence", "hay", "wood"}


def footprint_for(size_class, room_count):
    """The footprint floor for a design: its sizeClass, grown to the floor its
    room count needs. One place so the zone packer and the layout agree."""
    w, h = FOOTPRINTS[size_class]
    floor = ROOM_FLOOR.get(min(room_count, 4))
    if floor is not None:
        fw, fh = FOOTPRINTS[floor]
        w, h = max(w, fw), max(h, fh)
    return (w, h)


def room_needs(design, templates, furniture=None):
    """{room name: (area, min_side)} — the room's area from its furniture
    (footprints x2.5 + walkway, 3x3 minimum; solid pieces count 1.6x, they
    cannot share cells with walkways or each other's standing room) and the
    narrowest side that still fits its tallest piece beside a walkway."""
    furn = design.furniture if furniture is None else furniture
    out = {}
    for r in design.rooms:
        area, tallest = 0, 1
        for f in furn:
            if f.room != r.name or f.template not in templates:
                continue
            t = templates[f.template]
            fp = f.count * t.size[0] * t.size[1]
            if t.walkability <= 0:
                fp = int(round(fp * SOLID_FURN_SCALE))
            area += fp
            tallest = max(tallest, t.size[1])
        min_side = MIN_SIDE + (1 if area else 0) + (1 if tallest >= 2 else 0)
        out[r.name] = (max(MIN_ROOM_AREA, int(round(area * FURN_SCALE + ROOM_WALKWAY))),
                       min_side)
    return out


def _share_needs(design):
    """Share-weight stand-ins for designs laid out without templates."""
    return {r.name: (SHARE_WEIGHT.get(r.share, 1) * 8, MIN_SIDE) for r in design.rooms}


def _drop_key(f, templates):
    """Drop order at the cap: unknown templates, then decorative pieces, then
    functional ones, beds last; the biggest footprint first within a class
    (one drop frees the most room)."""
    t = templates.get(f.template)
    if t is None:
        return (-1, 0, "")
    cls = 2 if t.for_sleep else \
        (1 if FUNCTIONAL_TAGS & {x.lower() for x in t.tags} else 0)
    return (cls, -(t.size[0] * t.size[1]), f.template)


def _shape(design, needs):
    """A footprint covering the summed room areas, shaped like its sizeClass
    footprint, with the sizeClass floor and the 24x18 cap."""
    fw, fh = footprint_for(design.size_class, len(design.rooms))
    area = max(int(round(sum(a for (a, _m) in needs.values()) * ROOM_HEADROOM)) + 6,
               fw * fh)
    w = max(3, int(round(math.sqrt(area * fw / float(fh)))))
    h = max(3, int(round(math.sqrt(area * fh / float(fw)))))
    while w < CAP[0] and w * h < area:
        w += 1
    while h < CAP[1] and w * h < area:
        h += 1
    return (min(CAP[0], max(w, fw)), min(CAP[1], max(h, fh)))


def _depth_for(area, span):
    """The strip depth at which a strip of this span holds `area` cells
    (the two wall rows included)."""
    return int(math.ceil(area / float(max(1, span - 2)))) + 2


class RoomOut:
    def __init__(self, base_name, rect):
        self.base_name = base_name
        self.rect = rect
        self.doors = set()     # absolute door cells on this room's ring
        self.furniture = None  # RoomLayout, filled by the caller


class BuildingLayout:
    def __init__(self, design, rect):
        self.design = design
        self.rect = rect
        self.rooms = []            # [RoomOut] (empty rect duplicates the building when there is one room)
        self.entrance_side = design.entrance_side
        self.entrance_door = None  # absolute (x, y) on the building ring
        self.door_pairs = []       # [[cellA, cellB]] facing pairs between rooms
        self.furniture = list(design.furniture)  # what _furnish places (cap-trimmed)
        self.dropped = []          # [(template, room)] pieces dropped at the cap
        self.unit_outs = []        # [UnitOut] stamped copies, unit buildings only
        self.unit_dropped = []     # names of copies that did not fit the rect
        self.residents = 0         # placed units x residents per unit

    def room_by_base(self, name):
        for r in self.rooms:
            if r.base_name == name:
                return r
        return None

    @property
    def entrance_room(self):
        r = self.room_by_base(self.design.entrance_room)
        return r or self.rooms[0]


def _connection_tree(design):
    """Rooms as a parent->children tree from the connection list, rooted at the
    entrance room. Rooms with no connections hang off the root so every room
    stays reachable; extra edges beyond the tree are dropped (the builder's
    auto-connect still gives them a door when they touch)."""
    rooms = [r.name for r in design.rooms]
    if not rooms:
        return {}, rooms[0] if rooms else None
    root = design.entrance_room if design.entrance_room in rooms else rooms[0]
    adj = {r: set() for r in rooms}
    for a, b in design.connections:
        if a in adj and b in adj and a != b:
            adj[a].add(b)
            adj[b].add(a)
    children = {r: [] for r in rooms}
    seen = {root}
    frontier = [root]
    while frontier:
        node = frontier.pop(0)
        # keep tree order deterministic: connection order, then room order
        nxt = [n for n in rooms if n in adj[node] and n not in seen]
        for n in nxt:
            seen.add(n)
            children[node].append(n)
        frontier.extend(nxt)
    for r in rooms:  # orphans hang off the root
        if r not in seen:
            children[root].append(r)
            seen.add(r)
    return children, root


def _strip_split(rect, side, size):
    """Cut a strip of `size` cells off `rect` along `side`. Returns (strip, rest)."""
    size = max(1, size)
    if side in ("south", "north"):
        strip = Rect(rect.x, rect.y if side == "south" else rect.y1 - size + 1, rect.w, size)
        rest = Rect(rect.x, rect.y + size if side == "south" else rect.y,
                    rect.w, rect.h - size)
    else:
        strip = Rect(rect.x if side == "west" else rect.x1 - size + 1, rect.y, size, rect.h)
        rest = Rect(rect.x + size if side == "west" else rect.x, rect.y,
                    rect.w - size, rect.h)
    return strip, rest


def _divide_children(rest, side, kids, weights, needs):
    """Split the remainder perpendicular to the parent's strip among the
    children, proportional to their subtree weights, each wide enough for
    its own subtree at this depth."""
    n = len(kids)
    if n == 0:
        return {}
    along = rest.w if side in ("south", "north") else rest.h
    depth = rest.h if side in ("south", "north") else rest.w
    mins = []
    for k in kids:
        m = max(MIN_SIDE, needs.get(k, (1, MIN_SIDE))[1],
                _depth_for(weights[k], depth))
        mins.append(min(m, along))
    sizes = _sizes_mins(along, [weights[k] for k in kids], mins)
    out = {}
    pos = 0
    for k, size in zip(kids, sizes):
        if side in ("south", "north"):
            out[k] = Rect(rest.x + pos, rest.y, size, rest.h)
        else:
            out[k] = Rect(rest.x, rest.y + pos, rest.w, size)
        pos += size
    return out


def _room_rects(design, rect, needs):
    """{room name: Rect} — guillotine strips down the connection tree,
    weighted by the rooms' needs, every strip deep enough for its own
    furniture and the remainder deep enough for the children."""
    children, root = _connection_tree(design)
    weights = {}  # subtree need per room

    def subtree(node):
        if node in weights:
            return weights[node]
        w = needs.get(node, (1, MIN_SIDE))[0]
        for c in children.get(node, []):
            w += subtree(c)
        weights[node] = w
        return w

    subtree(root)
    placements = {}

    def assign(node, crect, strip_side):
        kids = children.get(node, [])
        if not kids:
            placements[node] = crect
            return
        span = crect.w if strip_side in ("south", "north") else crect.h
        axis = crect.h if strip_side in ("south", "north") else crect.w
        own_need, own_min = needs.get(node, (1, MIN_SIDE))
        # the strip holds this room's furniture; the rest holds the children,
        # deep enough for their areas and for the tallest piece among them
        kids_min = max((needs.get(k, (1, MIN_SIDE))[1] for k in kids), default=MIN_SIDE)
        rest_min = max(MIN_SIDE, kids_min, _depth_for(weights[node] - own_need, span))
        lo = min(max(own_min, _depth_for(own_need, span)), axis - 1)
        hi = max(lo, axis - min(rest_min, axis - 1))
        size = int(round(axis * own_need / float(weights[node]))) if weights[node] else lo
        if len(kids) == 1:
            # a chain: keep this room's strip near the depth its furniture
            # needs and give the remainder to the tail, instead of stacking
            # proportional bands that starve the last room into a sliver
            size = min(size, max(lo, _depth_for(own_need, span) + 2))
        strip, rest = _strip_split(crect, strip_side, max(lo, min(size, hi)))
        placements[node] = strip
        kid_rects = _divide_children(rest, strip_side, kids, weights, needs)
        for k in kids:
            assign(k, kid_rects[k], strip_side)

    assign(root, rect, design.entrance_side)
    return placements


def _offending_rooms(design, w, h, needs):
    """Rooms whose rect at this footprint cannot hold their furniture,
    biggest need first."""
    rects = _room_rects(design, Rect(0, 0, w, h), needs)
    bad = []
    for name, (area, min_side) in needs.items():
        r = rects.get(name)
        if r is None:
            continue
        if r.w * r.h < area or min(r.w, r.h) < min_side:
            bad.append((area, name))
    bad.sort(reverse=True)
    return [name for (_area, name) in bad]


def _line_area(line, templates):
    t = templates.get(line.template)
    return line.count * t.size[0] * t.size[1] if t else 0


def _split_room(design, room_name, furniture, templates):
    """An over-stuffed room becomes two connected rooms: the room keeps the
    bigger half of its furniture, the rest moves to '<room> Annex'. Returns
    (design, furniture) with the annex wired in, or (None, None) when the
    furniture cannot be divided."""
    base = next((r for r in design.rooms if r.name == room_name), None)
    if base is None:
        return None, None
    lines = sorted((f for f in furniture if f.room == room_name),
                   key=lambda f: (-_line_area(f, templates), f.template))
    if not lines:
        return None, None
    total = sum(_line_area(f, templates) for f in lines)
    if len(lines) == 1 and lines[0].count < 2:
        return None, None
    annex_name = f"{room_name} Annex"
    main, annex = [], []
    kept = 0
    for i, f in enumerate(lines):
        if len(lines) == 1:
            keep = max(1, int(round(f.count * 0.55)))
            main.append(dataclasses.replace(f, count=keep))
            annex.append(dataclasses.replace(f, count=f.count - keep, room=annex_name))
            break
        if i < len(lines) - 1 and kept < 0.55 * total:
            main.append(f)
            kept += _line_area(f, templates)
        else:
            annex.append(dataclasses.replace(f, room=annex_name))
    if not annex or not main:
        return None, None
    rooms = list(design.rooms) + [RoomSpec(name=annex_name, share="small",
                                           purpose=base.purpose)]
    connections = list(design.connections) + [[room_name, annex_name]]
    furn = [f for f in furniture if f.room != room_name] + main + annex
    new = dataclasses.replace(design, rooms=rooms, connections=connections, furniture=furn)
    return new, list(furn)


def _resolve_plan(design, templates):
    """(w, h, design, furniture, dropped, needs): the footprint sized so every
    room fits its furniture — growing to the cap, splitting a room that still
    cannot hold its furniture into an annex before dropping pieces, then
    dropping the lowest-value pieces until it does. With upper storeys the
    footprint must fit every storey's rooms, so a building whose upstairs is
    the fuller one grows for it. The returned design is the one the rooms come
    from (the original unless a split happened)."""
    furniture = list(design.furniture)
    dropped = []
    resolved = design
    annexed = set()
    uppers = [u for u in getattr(design, "upper", []) or [] if u.rooms]

    def fits(w, h, needs):
        rects = _room_rects(resolved, Rect(0, 0, w, h), needs)
        return all(rects[name].w * rects[name].h >= area
                   and min(rects[name].w, rects[name].h) >= min_side
                   for name, (area, min_side) in needs.items())

    def storey_fits(spec, w, h):
        """The storey's own rooms inside the same footprint, laid out as the
        floors extension lays them out (the design's shell around the spec)."""
        d = dataclasses.replace(resolved, rooms=spec.rooms, connections=spec.connections,
                                entrance_room=spec.rooms[0].name, furniture=spec.furniture)
        needs = room_needs(d, templates, spec.furniture)
        rects = _room_rects(d, Rect(0, 0, w, h), needs)
        return all(rects[name].w * rects[name].h >= area
                   and min(rects[name].w, rects[name].h) >= min_side
                   for name, (area, min_side) in needs.items())

    def storeys_fit(w, h):
        return all(storey_fits(u, w, h) for u in uppers)

    needs = room_needs(resolved, templates, furniture)
    w, h = _shape(resolved, needs)
    n_furniture = len(design.furniture) + sum(len(u.furniture) for u in uppers)
    for _ in range(CAP[0] + CAP[1] + n_furniture + 8):
        needs = room_needs(resolved, templates, furniture)
        if fits(w, h, needs):
            if storeys_fit(w, h):
                break
            if w >= CAP[0] and h >= CAP[1]:
                # the footprint cannot grow any further; the storey's pieces
                # that do not fit are recorded when it is laid out
                break
            w, h = min(CAP[0], w + 1), min(CAP[1], h + 1)
            continue
        if w < CAP[0] or h < CAP[1]:
            w, h = min(CAP[0], w + 1), min(CAP[1], h + 1)
            continue
        # at the cap: split the worst-fitting room before dropping its pieces
        bad = [n for n in _offending_rooms(resolved, w, h, needs)
               if n not in annexed and not n.endswith(" Annex")]
        if bad and len(annexed) < MAX_ANNEXES:
            new, furn = _split_room(resolved, bad[0], furniture, templates)
            if new is not None:
                annexed.add(bad[0])
                resolved, furniture = new, furn
                needs = room_needs(resolved, templates, furniture)
                w, h = _shape(resolved, needs)
                continue
        if furniture:
            i = min(range(len(furniture)),
                    key=lambda j: _drop_key(furniture[j], templates))
            line = furniture[i]
            dropped.append((line.template, line.room))
            if line.count > 1:   # one piece at a time; never mutate the design
                furniture[i] = dataclasses.replace(line, count=line.count - 1)
            else:
                furniture.pop(i)
            # the dropped piece may make a smaller footprint viable again
            needs = room_needs(resolved, templates, furniture)
            nw, nh = _shape(resolved, needs)
            if fits(nw, nh, needs):
                w, h = nw, nh
                break
        else:
            break
    return w, h, resolved, furniture, dropped, needs


def building_footprint(design, templates):
    """The (w, h) the layout will give this design — one place so the map,
    the zone packer and the layout itself agree."""
    if getattr(design, "units", None):
        return units_footprint(design, templates)
    return _resolve_plan(design, templates)[:2]


# ------------------------------------------------------------------ units

UNIT_SPINE = 3        # the corridor spine's width between the two unit rows
UNIT_SPINE_NAME = "Corridor"
UNIT_ROW_GAP = 1      # open cells between unit rows and the shared strip


def _sleep_name(templates):
    """The catalogue's smallest sleep template, or None (the pipeline adds a
    plain Bed before layouts run, so this finds one)."""
    beds = [t for t in templates.values() if t.for_sleep]
    return min(beds, key=lambda t: (t.size[0] * t.size[1], t.name)).name if beds else None


def _bed_room(unit_design):
    """The unit room its residents' beds go in: one named or purposed for
    sleeping, else the first room."""
    import re
    for r in unit_design.rooms:
        if re.search(r"bed|chamber|sleep|quarter", f"{r.name} {r.purpose}".lower()):
            return r.name
    return unit_design.rooms[0].name if unit_design.rooms else "Room"


def _unit_furniture(design, templates):
    """One unit copy's furniture: its own pieces plus a bed for each resident
    they don't already sleep (P3 usually furnishes the unit with its beds)."""
    unit = design.units
    furn = list(unit.design.furniture)
    sleeps = sum(f.count * bed_capacity(templates[f.template]) for f in furn
                 if f.template in templates and templates[f.template].for_sleep)
    if unit.residents > sleeps and _sleep_name(templates):
        furn.append(FurniturePlan(template=_sleep_name(templates),
                                  room=_bed_room(unit.design),
                                  count=unit.residents - sleeps))
    return furn


def units_per_storey(design):
    """How many unit copies one storey carries: the plan's perStorey, or the
    count spread evenly over the building's storeys."""
    unit = design.units
    if unit.per_storey:
        return unit.per_storey
    return max(1, -(-unit.count // max(1, design.storeys)))


def _unit_size(design, templates):
    """(w, h) of one unit copy, with room for a bed per resident on top of its
    own furniture: a copy turned to face the corridor can stack its rooms
    where the plan sized them side by side, and that slack keeps a bedroom
    deep enough for its bed."""
    unit = design.units
    furn = list(unit.design.furniture)
    if unit.residents and _sleep_name(templates):
        furn.append(FurniturePlan(template=_sleep_name(templates),
                                  room=_bed_room(unit.design), count=unit.residents))
    return _resolve_plan(dataclasses.replace(unit.design, furniture=furn), templates)[:2]


def units_footprint(design, templates):
    """(w, h) of a unit building: two unit rows either side of a corridor
    spine, a shared-room strip at the entrance end. The cap applies to the
    unit and the corridor, not the block: its length follows from the unit
    count, and the zone grows to hold it. The spine runs away from the
    entrance side, so an east- or west-facing block lies on its side."""
    uw, uh = _unit_size(design, templates)
    per = units_per_storey(design)
    rows = max(1, -(-per // 2))
    vertical = design.entrance_side in ("south", "north")
    strip_h = _strip_plan(design, templates, uw if vertical else uh)[0]
    if vertical:
        return (2 * uw + UNIT_SPINE,
                strip_h + UNIT_ROW_GAP + rows * (uh + UNIT_ROW_GAP))
    return (strip_h + UNIT_ROW_GAP + rows * (uw + UNIT_ROW_GAP),
            2 * uh + UNIT_SPINE)


def _shared_strip_height(design, templates, width):
    """The depth the building's shared rooms (lobby, stair hall) need as one
    strip across the building's width."""
    needs = room_needs(design, templates)
    if not needs:
        return 0
    return max(MIN_SIDE, max(_depth_for(a, width) for (a, _m) in needs.values()))


def _strip_names(design):
    """The shared rooms that go in the entrance strip. A shared room the model
    called "Corridor" is the spine itself (its stair and furniture go there);
    a second room of that name would clash."""
    return [r.name for r in design.rooms
            if r.name.strip().lower() != UNIT_SPINE_NAME.lower()]


def _strip_plan(design, templates, along):
    """(depth, [side a rows, side b rows]) for the shared-room strip, each row
    ``(room names, depth)`` from the entrance end outward. Each side of the
    corridor is ``along`` cells wide, one unit copy's width. While every
    side's rooms fit side by side at their narrowest, each side is one row as
    deep as the strip. Past that, each room takes a full-width row of its own,
    the rooms shared between the sides by area, and the strip deepens.
    Squeezing them into one row left rooms too thin to furnish: a model that
    listed an inn's four guest rooms beside the unit design got four rooms in
    an 11-cell row, and the build failed on furniture sitting on walls."""
    names = _strip_names(design)
    if not names:
        return 0, [[], []]
    needs = room_needs(design, templates) if templates else _share_needs(design)
    half = -(-len(names) // 2)
    groups = (names[:half], names[half:])
    if all(sum(max(MIN_SIDE, needs.get(n, (1, MIN_SIDE))[1]) for n in g) <= along
           or len(g) <= 1 for g in groups):
        flat = _shared_strip_height(design, templates, along)
        return flat, [[(g, flat)] if g else [] for g in groups]
    depth_of = {n: max(MIN_SIDE, _depth_for(needs.get(n, (1, MIN_SIDE))[0], along))
                for n in names}
    sides, load = ([], []), [0, 0]
    for n in sorted(names, key=lambda n: -depth_of[n]):
        k = 0 if load[0] <= load[1] else 1
        sides[k].append(n)
        load[k] += depth_of[n]
    depth = max(load)
    out = []
    for k, side in enumerate(sides):
        side.sort(key=names.index)   # the plan's order from the entrance end
        rs = [([n], depth_of[n]) for n in side]
        if rs:
            # the shallower side's last row takes up the slack
            rs[-1] = (rs[-1][0], rs[-1][1] + depth - load[k])
        out.append(rs)
    return depth, out


def _fit_rows(rows, total, full):
    """The strip's rows scaled down when the block is shallower than the
    strip wants; the last row takes what is left."""
    if total >= full or not rows:
        return rows
    out, used = [], 0
    for i, (group, d) in enumerate(rows):
        nd = total - used if i == len(rows) - 1 else max(1, d * total // full)
        out.append((group, nd))
        used += nd
    return out


class UnitOut:
    """One stamped copy of the unit design, with the door cells on its
    corridor-facing wall."""
    def __init__(self, name, rect, layout):
        self.name = name
        self.rect = rect
        self.layout = layout   # BuildingLayout of the copy
        self.doors = set()


def unit_number(unit, storey, k, per):
    """The copy's number: plain runs 1..count across storeys; storey numbers
    each floor's copies 101, 102 ... 201, 202."""
    if unit.numbering == "storey":
        return storey * 100 + k
    return (storey - 1) * per + k


def layout_units(design, rect, rng, templates, storey=1, make_entrance=True):
    """Lay one storey of a unit building inside `rect`: the shared rooms as
    a strip at the entrance end, the corridor spine from it to the far end,
    and unit copies stamped down both sides, each mirrored so its door faces
    the corridor. ``storey`` numbers the copies (perStorey each); the
    entrance side picks the spine's axis, so a rotated block keeps its
    entrance in its strip."""
    unit = design.units
    side = design.entrance_side
    vertical = side in ("south", "north")
    uw, uh = _unit_size(design, templates)
    per = units_per_storey(design)
    strip_full, side_rows = _strip_plan(design, templates, uw if vertical else uh)
    strip_h = min(strip_full,
                  max(0, (rect.h if vertical else rect.w) - UNIT_ROW_GAP
                      - ((uh if vertical else uw) + UNIT_ROW_GAP)))
    b = BuildingLayout(design, rect)
    b.unit_outs = []
    b.residents = 0
    b.unit_dropped = []

    # ---- the shared rooms flank the corridor mouth at the entrance end;
    # the corridor itself runs from the entrance edge to the far end, so its
    # doors into the shared rooms (and its entrance) are the builder's own
    # auto-connect, never an alignment luck
    needs = room_needs(design, templates) if templates else _share_needs(design)
    names = _strip_names(design)
    strip_rooms = []
    if names and strip_h > 0:
        for col, rows in enumerate(side_rows):
            off = 0
            for (group, depth) in _fit_rows(rows, strip_h, strip_full):
                # each row a slice of the strip, the first at the entrance end
                if vertical:
                    x0 = rect.x + uw + UNIT_SPINE if col else rect.x
                    y0 = rect.y + off if side == "south" else rect.y1 - off - depth + 1
                    side_rect = Rect(x0, y0, uw, depth)
                else:
                    x0 = rect.x + off if side == "west" else rect.x1 - off - depth + 1
                    y0 = rect.y + uh + UNIT_SPINE if col else rect.y
                    side_rect = Rect(x0, y0, depth, uh)
                off += depth
                along = side_rect.w if vertical else side_rect.h
                weights = [needs.get(n, (1, MIN_SIDE))[0] for n in group]
                mins = [max(MIN_SIDE, needs.get(n, (1, MIN_SIDE))[1]) for n in group]
                sizes = _sizes_mins(along, weights, mins)
                pos = side_rect.x if vertical else side_rect.y
                for n, size in zip(group, sizes):
                    strip_rooms.append(RoomOut(
                        n, Rect(pos, side_rect.y, size, side_rect.h) if vertical
                        else Rect(side_rect.x, pos, side_rect.w, size)))
                    pos += size
    if vertical:
        corridor = RoomOut(UNIT_SPINE_NAME, Rect(rect.x + uw, rect.y, UNIT_SPINE, rect.h))
    else:
        corridor = RoomOut(UNIT_SPINE_NAME, Rect(rect.x, rect.y + uh, rect.w, UNIT_SPINE))
    b.rooms = strip_rooms + [corridor]

    # ---- unit copies down both sides of the spine, mirrored toward it
    unit_along = uh if vertical else uw
    room = (rect.h if vertical else rect.w) - strip_h - UNIT_ROW_GAP
    rows = max(0, room // (unit_along + UNIT_ROW_GAP))
    placed = 0
    for r in range(rows):
        if placed >= per:
            break
        # the r-th row, walking away from the entrance strip
        lead = strip_h + UNIT_ROW_GAP + r * (unit_along + UNIT_ROW_GAP)
        for (col, facing) in ((0, "east" if vertical else "north"),
                              (1, "west" if vertical else "south")):
            if placed >= per or lead + unit_along > room + strip_h:
                break
            k = placed + 1
            if vertical:
                y = (rect.y + lead) if side == "south" else (rect.y1 - lead - uh + 1)
                x = rect.x + uw + UNIT_SPINE if col else rect.x
                urect = Rect(x, y, uw, uh)
            else:
                x = (rect.x + lead) if side == "west" else (rect.x1 - lead - uw + 1)
                y = rect.y + uh + UNIT_SPINE if col else rect.y
                urect = Rect(x, y, uw, uh)
            ud = dataclasses.replace(unit.design, entrance_side=facing,
                                     furniture=_unit_furniture(design, templates))
            ul = layout_rooms(ud, urect, rng, templates)
            uo = UnitOut(f"{unit.name} {unit_number(unit, storey, k, per)}",
                         urect, ul)
            # the copy's door is the auto-connect pair with the corridor, not
            # the layout's own entrance guess: swap the cells over
            pair = shared_wall_cells(urect, corridor.rect)
            old = ul.entrance_door
            for rm in ul.rooms:
                rm.doors.discard(old)
            for c in pair:
                if urect.contains_cell(c):
                    uo.doors.add(c)
                    _cell_to_room(ul, c)
                if corridor.rect.contains_cell(c):
                    corridor.doors.add(c)
            ul.entrance_door = next(iter(sorted(uo.doors)), old)
            b.unit_outs.append(uo)
            b.residents += unit.residents
            placed += 1
    for k in range(placed + 1, per + 1):
        b.unit_dropped.append(f"{unit.name} {unit_number(unit, storey, k, per)}")

    # ---- doors: shared strip rooms touch each other and the corridor
    for i, ra in enumerate(b.rooms):
        for rb in b.rooms[i + 1:]:
            for cell in shared_wall_cells(ra.rect, rb.rect):
                if ra.rect.contains_cell(cell):
                    ra.doors.add(cell)
                if rb.rect.contains_cell(cell):
                    rb.doors.add(cell)
    b.entrance_side = side
    b.entrance_door = _entrance_cell(corridor.rect, side)
    corridor.doors.add(b.entrance_door)
    return b


def _cell_to_room(layout, cell):
    """A door cell on a room's ring, so its furniture keeps it clear."""
    x, y = cell
    for room in layout.rooms:
        if room.rect.contains_cell(cell) and \
                (x in (room.rect.x, room.rect.x1) or y in (room.rect.y, room.rect.y1)):
            room.doors.add(cell)
            return


def layout_rooms(design, rect, rng, templates=None, furniture=None):
    """Place one design's rooms and doors inside a fixed footprint rect (the
    shape layout_building gives it, or an upper storey's ground-identical
    copy). ``furniture`` is the list the rooms were sized for (layout_building
    passes its cap-trimmed list); the caller furnishes the rooms afterwards."""
    needs = room_needs(design, templates, furniture) if templates else _share_needs(design)
    b = BuildingLayout(design, rect)
    b.furniture = list(design.furniture) if furniture is None else list(furniture)
    if len(design.rooms) <= 1:
        # one room: the building itself is the room (a duplicate equal-sized child
        # region would confuse the builder's parent logic, so none is emitted)
        if design.rooms:
            b.rooms = [RoomOut(design.rooms[0].name, rect)]
        b.entrance_door = _entrance_cell(rect, design.entrance_side)
        b.rooms[0].doors.add(b.entrance_door)
        return b

    placements = _room_rects(design, rect, needs)
    b.rooms = [RoomOut(r.name, placements[r.name]) for r in design.rooms]

    # doors: every touching pair of rooms gets a facing cell pair (this covers
    # every connection, and is exactly what the builder auto-connects); each
    # cell goes to the room whose rect actually holds it
    for i, ra in enumerate(b.rooms):
        for rb in b.rooms[i + 1:]:
            pair = shared_wall_cells(ra.rect, rb.rect)
            if pair:
                b.door_pairs.append([pair[0], pair[1]])
                for cell in pair:
                    if ra.rect.contains_cell(cell):
                        ra.doors.add(cell)
                    elif rb.rect.contains_cell(cell):
                        rb.doors.add(cell)
    b.entrance_door = _entrance_cell(rect, design.entrance_side)
    root_room = b.entrance_room
    if root_room.rect.contains_cell(b.entrance_door) and _on_ring(root_room.rect, b.entrance_door):
        root_room.doors.add(b.entrance_door)
    return b


def layout_building(design, origin, rng, templates=None):
    """Place a building's rooms. origin is the bottom-left cell of its footprint."""
    if getattr(design, "units", None):
        w, h = units_footprint(design, templates)
        return layout_units(design, Rect(origin[0], origin[1], w, h), rng, templates)
    if templates:
        w, h, design, furniture, dropped, needs = _resolve_plan(design, templates)
    else:
        w, h = footprint_for(design.size_class, len(design.rooms))
        furniture, dropped, needs = design.furniture, [], _share_needs(design)
    b = layout_rooms(design, Rect(origin[0], origin[1], w, h), rng, templates,
                     furniture=furniture)
    b.dropped = list(dropped)
    return b


def _room_share(design, name):
    for r in design.rooms:
        if r.name == name:
            return r.share
    return "small"


def _on_ring(rect, cell):
    x, y = cell
    return rect.contains_cell(cell) and (x in (rect.x, rect.x1) or y in (rect.y, rect.y1))


def _entrance_cell(rect, side):
    dx, dy = SIDE_DX_DY[side]
    if side in ("north", "south"):
        return (rect.x + (rect.w - 1) // 2, rect.y1 if side == "north" else rect.y)
    return (rect.x1 if side == "east" else rect.x, rect.y + (rect.h - 1) // 2)
