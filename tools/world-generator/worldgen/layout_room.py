"""Furniture in one room.

Reserve each door cell's inner neighbour and a clear walkway connecting every
door (a spine through the middle of the room with a branch to each door, which
keeps the walls free for furniture). Then place furniture largest first, in
hint order. A piece never covers a door cell, a walkway cell or another piece,
and every solid piece keeps a standable cell beside it; a final flood from the
doors drops or relocates anything that would box itself in. Hints that cannot
be met fall back to "anywhere free" and are reported.
"""
from .hints import parse as parse_hint
from .model import Rect, door_inner_cell


class RoomLayout:
    def __init__(self):
        self.placements = []   # (template_name, (x, y)) absolute cells
        self.reserved = set()  # door inner cells + walkway cells (absolute)
        self.failures = []     # (template, count, reason)
        self.fallbacks = []    # (template, reason)


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


def layout_room(rect, door_cells, furniture, templates, rng, keep_clear=None):
    """Lay out one room.

    rect       -- the room's Rect (walls included; furniture goes in the ring inside)
    door_cells -- absolute [(x, y)] cells of doors on the room's ring
    furniture  -- [FurniturePlan] for this room only
    templates  -- {name: ObjectTemplate}
    keep_clear -- absolute cells nothing may cover (an opening in the floor above
                  the room's ground twin: the game blocks them, so they must
                  stay empty)
    """
    out = RoomLayout()
    out.reserved, door_inner = reserve_walkways(rect, door_cells)
    inter = rect.interior()
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

    def place_all(banned):
        """One full placement pass over every furniture plan."""
        placed = []
        occupied = set()
        failures = []
        fallbacks = []

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
            count = 0
            for pos in positions:
                if count >= budget:
                    break
                if (f.template, pos) in banned or not legal(pos, tmpl.size):
                    continue
                if hint.symmetric and count + 2 <= budget:
                    m = mirror(pos, tmpl.size)
                    if m != pos and (f.template, m) not in banned and legal(m, tmpl.size):
                        for p in (pos, m):
                            occupied.update(_footprint(p, tmpl.size))
                            placed.append((f.template, p, tmpl.size))
                        count += 2
                        continue
                occupied.update(_footprint(pos, tmpl.size))
                placed.append((f.template, pos, tmpl.size))
                count += 1
            return count

        def area(name):
            t = templates.get(name)
            return t.size[0] * t.size[1] if t else 0

        plans = sorted(furniture, key=lambda f: -area(f.template))
        for f in plans:
            if f.template not in templates:
                failures.append((f.template, 0, "unknown template"))
                continue
            tmpl = templates[f.template]
            hint = parse_hint(f.hint)
            cands, reason = ordered_candidates(hint, tmpl.size, placed)
            if not cands:
                fallbacks.append((f.template, reason or "no candidate positions"))
                cands = all_positions(tmpl.size)
            tries = sorted(cands, key=lambda p: dist(p, center)) if hint.symmetric else list(cands)
            count = try_positions(f, tmpl, hint, tries, f.count)
            if count < f.count and hint.constrained:
                fallbacks.append((f.template, f"hint {f.hint!r} could not be fully met"))
                count += try_positions(f, tmpl, hint, all_positions(tmpl.size), f.count - count)
            if count < f.count:
                failures.append((f.template, count, "no free cell in the room"))
        return placed, failures, fallbacks

    banned = set()
    for attempt in range(8):
        placements, failures, fallbacks = place_all(banned)
        out.placements = [(n, p) for (n, p, _s) in placements]
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
            out.placements = [(n, p) for (n, p, _s) in keep]
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
