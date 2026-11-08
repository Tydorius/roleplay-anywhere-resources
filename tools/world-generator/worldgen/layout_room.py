"""Furniture in one room.

Reserve each door cell's inner neighbour and a clear walkway connecting every
door (a spine through the middle of the room with a branch to each door, which
keeps the walls free for furniture). Then place furniture largest first, in
hint order. A piece never covers a door cell, a walkway cell or another piece,
and every solid piece keeps a standable cell beside it; a final flood from the
doors drops or relocates anything that would box itself in. Hints that cannot
be met fall back to "anywhere free" and are reported.

A template with a ``back`` (the room library's pieces) can be turned: its size
is the north-facing size, and a turn of ``rot`` quarter turns clockwise puts
its back to the north, east, south or west (0-3). On a wall or in a row it
stands back to that wall, in a corner back to one of its two walls, and round
a table it faces the table; otherwise it takes whichever turn fits, unturned
first. Templates without a ``back`` are never turned and place exactly as
before. ``wall:``/``row:`` also take far, side and near: the wall across from
the room's main door, one at right angles to it, and the door's own wall.
"""
from .hints import parse as parse_hint
from .model import Rect, door_inner_cell

TURN_SIDES = ("north", "east", "south", "west")    # rot 0-3: where the back points
OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}
PERPENDICULAR = {"north": ("east", "west"), "south": ("east", "west"),
                 "east": ("north", "south"), "west": ("north", "south")}
REL = ("far", "side", "near")


def turned(size, rot):
    """The footprint of a [w, h] north-facing size after ``rot`` quarter turns."""
    return (size[1], size[0]) if rot % 2 else (size[0], size[1])


def back_of(tmpl):
    """The template's back edge ("north" etc.), or None when it never turns."""
    b = getattr(tmpl, "extras", {}).get("back") if tmpl is not None else None
    return b if b in TURN_SIDES else None


class RoomLayout:
    def __init__(self):
        self.placements = []   # (template_name, (x, y)) absolute cells
        self.turns = {}        # (template_name, (x, y)) -> rot 1-3; absent means 0
        self.reserved = set()  # door inner cells + walkway cells (absolute)
        self.failures = []     # (template, count, reason)
        self.fallbacks = []    # (template, reason)

    def rot(self, name, pos):
        return self.turns.get((name, tuple(pos)), 0)

    def size_of(self, name, pos, templates):
        """The placed footprint of one placement (turned when it was turned)."""
        return turned(templates[name].size, self.rot(name, pos))


def _footprint(pos, size):
    x, y = pos
    w, h = size
    return {(cx, cy) for cx in range(x, x + w) for cy in range(y, y + h)}


def _ring(pos, size):
    x, y = pos
    w, h = size
    return {(cx, cy) for cx in range(x - 1, x + w + 1) for cy in range(y - 1, y + h + 1)
            if not (x <= cx < x + w and y <= cy < y + h)}


def reserve_walkways(rect, door_cells):
    """Door inner cells plus a clear walkway connecting every pair of them: a
    spine row (or column, in tall rooms) through the middle with a branch to
    each door. Keeps the walls free for furniture while guaranteeing that no
    placement can ever cut one door off from another."""
    inner = [door_inner_cell(rect, d) for d in door_cells]
    reserved = set(inner)
    if len(inner) >= 2:
        inter = rect.interior()
        xs = [p[0] for p in inner]
        ys = [p[1] for p in inner]
        if inter.w >= inter.h:
            sy = inter.y + (inter.h - 1) // 2
            for x in range(min(xs), max(xs) + 1):
                reserved.add((x, sy))
            for (x, y) in inner:
                for yy in range(min(y, sy), max(y, sy) + 1):
                    reserved.add((x, yy))
        else:
            sx = inter.x + (inter.w - 1) // 2
            for y in range(min(ys), max(ys) + 1):
                reserved.add((sx, y))
            for (x, y) in inner:
                for xx in range(min(x, sx), max(x, sx) + 1):
                    reserved.add((xx, y))
    return reserved, inner


def _flood_from(inter, covered, starts):
    walkable = set(inter.cells()) - covered
    seen = set(c for c in starts if c in walkable)
    todo = list(seen)
    while todo:
        x, y = todo.pop()
        for c in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if c in walkable and c not in seen:
                seen.add(c)
                todo.append(c)
    return seen


def door_side(rect, cell):
    """The wall of ``rect`` a ring cell sits on, or None."""
    x, y = cell
    if y == rect.y:
        return "south"
    if y == rect.y1:
        return "north"
    if x == rect.x:
        return "west"
    if x == rect.x1:
        return "east"
    return None


def layout_room(rect, door_cells, furniture, templates, rng, keep_clear=None, main_door=None):
    """Lay out one room.

    rect       -- the room's Rect (walls included; furniture goes in the ring inside)
    door_cells -- absolute [(x, y)] cells of doors on the room's ring
    furniture  -- [FurniturePlan] for this room only
    templates  -- {name: ObjectTemplate}
    keep_clear -- absolute cells nothing may cover (an opening in the floor above
                  the room's ground twin: the game blocks them, so they must
                  stay empty)
    main_door  -- the door far/side/near are measured from (default: the first
                  of door_cells)
    """
    out = RoomLayout()
    out.reserved, door_inner = reserve_walkways(rect, door_cells)
    inter = rect.interior()
    # a library room (its pieces have backs) also keeps the cell past each
    # door's threshold clear: pieces anchored near the door can otherwise ring
    # the threshold and seal the room. The plain route keeps its old reservation.
    library_room = any(back_of(templates.get(f.template)) for f in furniture)
    if library_room:
        for (dx, dy), (ix, iy) in zip(door_cells, door_inner):
            step = (ix + (ix - dx), iy + (iy - dy))
            if inter.contains_cell(step):
                out.reserved.add(step)
    if inter.w < 1 or inter.h < 1:
        for f in furniture:
            out.failures.append((f.template, 0, "room interior too small"))
        return out

    state = {
        "placements": [],   # [(name, (x, y), size)] in placement order
        "occupied": set(),
        "failures": [],
        "fallbacks": [],
    }

    def all_positions(size):
        w, h = size
        return [(x, y) for x in range(inter.x, inter.x1 - w + 2)
                for y in range(inter.y, inter.y1 - h + 2)]

    def dist(a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    center = (inter.x + (inter.w - 1) / 2.0, inter.y + (inter.h - 1) / 2.0)

    # far/side/near resolve against the main door's wall; a room with no door
    # treats them as any wall. The side pick is drawn only when needed, so a
    # room with no relative hints uses the random stream exactly as before.
    md = main_door if main_door is not None else (door_cells[0] if door_cells else None)
    near_side = door_side(rect, md) if md is not None else None
    side_pick = []

    def resolve(side):
        """[absolute sides] for a hint side, best first."""
        if side in TURN_SIDES:
            return [side]
        if near_side is None:
            return ["north", "east", "south", "west"]
        if side == "far":
            return [OPPOSITE[near_side]]
        if side == "near":
            return [near_side]
        if not side_pick:
            side_pick.append(rng.randrange(2))
        a, b = PERPENDICULAR[near_side]
        return [a, b] if side_pick[0] == 0 else [b, a]

    def mirror(pos, size):
        mx = inter.x1 - (pos[0] - inter.x) - (size[0] - 1)
        my = inter.y1 - (pos[1] - inter.y) - (size[1] - 1)
        return (mx, my)

    def wall_filter(side, size):
        w, h = size
        pos = []
        for (x, y) in all_positions(size):
            if side == "north" and y + h - 1 == inter.y1:
                pos.append((x, y))
            elif side == "south" and y == inter.y:
                pos.append((x, y))
            elif side == "west" and x == inter.x:
                pos.append((x, y))
            elif side == "east" and x + w - 1 == inter.x1:
                pos.append((x, y))
        return pos

    def corners(size):
        w, h = size
        pts = [(inter.x, inter.y), (inter.x1 - w + 1, inter.y),
               (inter.x, inter.y1 - h + 1), (inter.x1 - w + 1, inter.y1 - h + 1)]
        k = rng.randrange(4)
        return pts[k:] + pts[:k]

    def ring_around(fp, size):
        x0, y0, w, h = fp
        anchors = [(cx, cy)
                   for cx in range(x0 - 1, x0 + w + 1)
                   for cy in range(y0 - 1, y0 + h + 1)
                   if not (x0 <= cx < x0 + w and y0 <= cy < y0 + h)]
        return [(ax, ay) for (ax, ay) in anchors
                if inter.x <= ax and ay >= inter.y
                and ax + size[0] - 1 <= inter.x1 and ay + size[1] - 1 <= inter.y1]

    def near_footprint(fp, size):
        out_pos = []
        x0, y0, w, h = fp
        for (x, y) in all_positions(size):
            dx = max(x0 - (x + size[0] - 1), x - (x0 + w - 1), 0)
            dy = max(y0 - (y + size[1] - 1), y - (y0 + h - 1), 0)
            if max(dx, dy) <= 1:
                out_pos.append((x, y))
        return out_pos

    def ordered_candidates(hint, size, placed):
        """Candidate positions for a hint: (positions, fallback_reason).
        An empty list with a reason means the hint's target was missing."""
        if hint.around:
            targets = [p for p in placed if p[0] == hint.around]
            if not targets:
                return [], f"around:{hint.around} not placed yet"
            pos = []
            for (_n, tpos, tsize) in targets:
                pos.extend(ring_around((tpos[0], tpos[1], tsize[0], tsize[1]), size))
            seen, uniq = set(), []
            for p in pos:
                if p not in seen:
                    seen.add(p)
                    uniq.append(p)
            return uniq, None
        if hint.beside:
            targets = [p for p in placed if p[0] == hint.beside]
            if not targets:
                return [], f"beside:{hint.beside} not placed yet"
            pos = []
            for (_n, tpos, tsize) in targets:
                pos.extend(near_footprint((tpos[0], tpos[1], tsize[0], tsize[1]), size))
            seen, uniq = set(), []
            for p in pos:
                if p not in seen:
                    seen.add(p)
                    uniq.append(p)
            uniq.sort(key=lambda p: dist(p, targets[0][1]))
            return uniq, None
        pos = all_positions(size)
        constrained = False
        for side in hint.walls:
            wpos = wall_filter(side, size)
            if wpos:
                pos = wpos
                constrained = True
                break
        if hint.row:
            rpos = wall_filter(hint.row, size)
            if rpos:
                pos = sorted(rpos)
                constrained = True
        if hint.corner:
            pos = [p for p in corners(size) if p in pos] or corners(size)
            constrained = True
        if constrained:
            if hint.center:
                pos = sorted(pos, key=lambda p: dist(p, center))
            elif hint.near_door:
                pos = sorted(pos, key=lambda p: min(dist(p, d) for d in door_inner))
            elif hint.away_from_door:
                pos = sorted(pos, key=lambda p: -min(dist(p, d) for d in door_inner))
            return pos, None
        if hint.center:
            return sorted(pos, key=lambda p: dist(p, center)), None
        if hint.near_door:
            return sorted(pos, key=lambda p: min(dist(p, d) for d in door_inner)), None
        if hint.away_from_door:
            return sorted(pos, key=lambda p: -min(dist(p, d) for d in door_inner)), None
        return pos, None

    def turned_candidates(hint, size, placed):
        """[(pos, rot)] for a piece with a back, and a fallback reason."""
        def sz(r):
            return turned(size, r)

        if hint.around:
            targets = [p for p in placed if p[0] == hint.around]
            if not targets:
                return [], f"around:{hint.around} not placed yet"
            out_c, seen = [], set()
            for (_n, tpos, tsize) in targets:
                tc = (tpos[0] + (tsize[0] - 1) / 2.0, tpos[1] + (tsize[1] - 1) / 2.0)
                for r in range(4):
                    w, h = sz(r)
                    for p in ring_around((tpos[0], tpos[1], tsize[0], tsize[1]), (w, h)):
                        dx = tc[0] - (p[0] + (w - 1) / 2.0)
                        dy = tc[1] - (p[1] + (h - 1) / 2.0)
                        # the piece faces the target, so its back points away
                        if abs(dy) >= abs(dx):
                            want = 2 if dy > 0 else 0
                        else:
                            want = 3 if dx > 0 else 1
                        if r == want and (p, r) not in seen:
                            seen.add((p, r))
                            out_c.append((p, r))
            return out_c, None
        if hint.beside:
            targets = [p for p in placed if p[0] == hint.beside]
            if not targets:
                return [], f"beside:{hint.beside} not placed yet"
            out_c = []
            for r in (0, 1):
                for (_n, tpos, tsize) in targets:
                    for p in near_footprint((tpos[0], tpos[1], tsize[0], tsize[1]), sz(r)):
                        if (p, r) not in out_c:
                            out_c.append((p, r))
            out_c.sort(key=lambda c: (dist(c[0], targets[0][1]), c[1]))
            return out_c, None
        wall_sides = []
        if hint.row:
            wall_sides.extend(resolve(hint.row))
        for side in hint.walls:
            wall_sides.extend(s2 for s2 in resolve(side) if s2 not in wall_sides)
        out_c = []
        if wall_sides:
            for side in wall_sides:
                r = TURN_SIDES.index(side)
                cands = wall_filter(side, sz(r))
                if hint.row:
                    cands = sorted(cands)
                out_c.extend((p, r) for p in cands)
            if hint.corner:
                cs = []
                for (p, r) in out_c:
                    w, h = sz(r)
                    if p[0] in (inter.x, inter.x1 - w + 1) and p[1] in (inter.y, inter.y1 - h + 1):
                        cs.append((p, r))
                out_c = cs or out_c
        elif hint.corner:
            pts = []
            for r in range(4):
                w, h = sz(r)
                corner_walls = {(inter.x, inter.y): ("south", "west"),
                                (inter.x1 - w + 1, inter.y): ("south", "east"),
                                (inter.x, inter.y1 - h + 1): ("north", "west"),
                                (inter.x1 - w + 1, inter.y1 - h + 1): ("north", "east")}
                for p, walls in corner_walls.items():
                    if TURN_SIDES[r] in walls:
                        pts.append((p, r))
            k = rng.randrange(len(pts)) if pts else 0
            out_c = pts[k:] + pts[:k]
            # four corners fill fast: a piece that finds them taken stands
            # back to a wall rather than anywhere
            for r, side in enumerate(TURN_SIDES):
                out_c.extend((p, r) for p in wall_filter(side, sz(r)) if (p, r) not in pts)
        else:
            out_c = any_turn(size)
        if hint.center:
            out_c.sort(key=lambda c: dist(c[0], center))
        elif hint.near_door:
            out_c.sort(key=lambda c: min(dist(c[0], d) for d in door_inner))
        elif hint.away_from_door:
            out_c.sort(key=lambda c: -min(dist(c[0], d) for d in door_inner))
        return out_c, None

    def any_turn(size):
        out_c = [(p, 0) for p in all_positions(size)]
        if turned(size, 1) != tuple(size):
            out_c += [(p, 1) for p in all_positions(turned(size, 1))]
        return out_c

    def place_all(banned):
        """One full placement pass over every furniture plan."""
        placed = []
        occupied = set()
        failures = []
        fallbacks = []
        rots = {}

        def legal(pos, size):
            x, y = pos
            if x < inter.x or y < inter.y or x + size[0] - 1 > inter.x1 or y + size[1] - 1 > inter.y1:
                return False
            cells = _footprint(pos, size)
            if cells & occupied or cells & out.reserved:
                return False
            if keep_clear and cells & keep_clear:
                return False
            return True

        def try_positions(f, tmpl, hint, positions, budget):
            """``positions`` are cells, or (cell, rot) pairs for a piece that turns."""
            count = 0
            for cand in positions:
                if count >= budget:
                    break
                pos, rot = cand if isinstance(cand[0], tuple) else (cand, 0)
                size = turned(tmpl.size, rot)
                if (f.template, pos) in banned or not legal(pos, size):
                    continue
                if hint.symmetric and count + 2 <= budget:
                    m = mirror(pos, size)
                    # the mirror of a piece near the middle can overlap it;
                    # a turned mirror faces the other way
                    mrot = (rot + 2) % 4 if back_of(tmpl) else 0
                    if m != pos and (f.template, m) not in banned and legal(m, size) \
                            and not _footprint(pos, size) & _footprint(m, size):
                        for p, r in ((pos, rot), (m, mrot)):
                            occupied.update(_footprint(p, size))
                            placed.append((f.template, p, size))
                            if r:
                                rots[(f.template, p)] = r
                        count += 2
                        continue
                occupied.update(_footprint(pos, size))
                placed.append((f.template, pos, size))
                if rot:
                    rots[(f.template, pos)] = rot
                count += 1
            return count

        def area(name):
            t = templates.get(name)
            return t.size[0] * t.size[1] if t else 0

        if library_room:
            # a piece goes after the one it stands beside or around, so the
            # chairs never look for a table that isn't down yet
            depth = {}

            def dep(f, seen=()):
                h = parse_hint(f.hint)
                ref = h.around or h.beside
                if not ref or f.template in seen:
                    return 0
                tgt = [g for g in furniture if g.template == ref]
                return 1 + max((dep(g, seen + (f.template,)) for g in tgt), default=-1)
            for f in furniture:
                depth[id(f)] = dep(f)
            plans = sorted(furniture, key=lambda f: (depth[id(f)], -area(f.template)))
        else:
            plans = sorted(furniture, key=lambda f: -area(f.template))
        for f in plans:
            if f.template not in templates:
                failures.append((f.template, 0, "unknown template"))
                continue
            tmpl = templates[f.template]
            hint = parse_hint(f.hint)
            turns = back_of(tmpl) is not None
            if turns:
                cands, reason = turned_candidates(hint, tmpl.size, placed)
                anywhere = any_turn(tmpl.size)
            else:
                # far/side/near mean real walls to a piece that never turns too
                if any(w in REL for w in hint.walls):
                    hint.walls = tuple(s2 for w in hint.walls for s2 in resolve(w))
                if hint.row in REL:
                    hint.row = resolve(hint.row)[0]
                cands, reason = ordered_candidates(hint, tmpl.size, placed)
                anywhere = all_positions(tmpl.size)
                if library_room and hint.corner and cands:
                    # corners taken: along a wall before anywhere
                    seen = set(cands)
                    for side in TURN_SIDES:
                        cands = cands + [q for q in wall_filter(side, tmpl.size) if q not in seen]
                        seen.update(cands)
            if not cands:
                fallbacks.append((f.template, reason or "no candidate positions"))
                cands = anywhere
            if hint.symmetric:
                key = (lambda c: dist(c[0], center)) if turns else (lambda p: dist(p, center))
                tries = sorted(cands, key=key)
            else:
                tries = list(cands)
            count = try_positions(f, tmpl, hint, tries, f.count)
            if count < f.count and hint.constrained:
                fallbacks.append((f.template, f"hint {f.hint!r} could not be fully met"))
                count += try_positions(f, tmpl, hint, anywhere, f.count - count)
            if count < f.count:
                failures.append((f.template, count, "no free cell in the room"))
        return placed, failures, fallbacks, rots

    banned = set()
    for attempt in range(8):
        placements, failures, fallbacks, rots = place_all(banned)
        out.placements = [(n, p) for (n, p, _s) in placements]
        out.turns = rots
        out.failures = failures
        out.fallbacks = fallbacks
        boxed = _boxed_positions(placements, templates, inter, door_inner)
        if not boxed:
            break
        if attempt == 7:
            # last resort: relocate the boxed pieces anywhere they stop
            # boxing themselves in; drop only what has nowhere to go
            keep = [p for p in placements if (p[0], p[1]) not in boxed]
            covered = set()
            for (_n, p, s) in keep:
                covered |= _footprint(p, s)
            for (name, pos) in sorted(boxed):
                size = next(s for (n, p, s) in placements if (n, p) == (name, pos))
                moved = None
                for cand in sorted(all_positions(size), key=lambda p: dist(p, center)):
                    fp = _footprint(cand, size)
                    if fp & covered or fp & out.reserved:
                        continue
                    if keep_clear and fp & keep_clear:
                        continue
                    trial = keep + [(name, cand, size)]
                    if (name, cand) not in _boxed_positions(trial, templates, inter,
                                                            door_inner):
                        moved = cand
                        break
                if moved is None:
                    out.failures.append((name, 0, "no placement that keeps the room walkable"))
                else:
                    keep.append((name, moved, size))
                    covered |= _footprint(moved, size)
                    if rots.get((name, pos)):
                        # a relocated piece keeps its footprint, so it keeps its turn
                        rots[(name, moved)] = rots[(name, pos)]
            out.placements = [(n, p) for (n, p, _s) in keep]
            out.turns = {k: v for k, v in rots.items() if k in set(out.placements)}
        else:
            banned |= boxed
    return out


def _boxed_positions(placements, templates, inter, door_inner):
    """Solid pieces whose surrounding ring no flooded (reachable) cell touches."""
    solid = {}
    for (name, pos, size) in placements:
        if templates[name].walkability <= 0:
            solid[(name, pos)] = (_footprint(pos, size), size)
    covered = set().union(*(fp for fp, _s in solid.values())) if solid else set()
    seen = _flood_from(inter, covered, door_inner)
    return {(name, pos) for (name, pos), (fp, size) in solid.items()
            if not (_ring(pos, size) & seen)}
