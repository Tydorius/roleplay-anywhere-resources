"""Ways out of a big building. A building's own design gives it one entrance, and
a spine compound's only door to the outside is its gate, so the far rooms of a
large complex can be a long walk through other people's rooms from the street.

This adds side doors after the buildings stand and before the zone's props go
down, so the ground outside each one stays clear. A room may be at most
EXIT_REACH cells from a door to open ground, and a complex of several parts gets
at least two ways out. A walled enclosure keeps its walls, and a void zone has no
ground to step onto."""
from collections import deque

from .model import is_sleep_name, shared_wall_cells

EXIT_REACH = 24          # cells; 48 m, about what a fire code allows
COMPLEX_EXITS = 2        # ways out of a compound of two or more parts
MAX_NEW_EXITS = 4        # side doors added to one building or complex


def solid_ground(out):
    """Every cell of the zone that a building or compound wall stands on."""
    solid = set()
    for b in out.buildings:
        solid |= b.layout.rect.cells()
    for comp in out.compounds:
        for c in comp.corridors:
            solid |= c.rect.cells()
        for s in comp.wall_strips:
            solid |= {(x, y) for x in range(s.pos[0], s.pos[0] + s.size[0])
                      for y in range(s.pos[1], s.pos[1] + s.size[1])}
    return solid


def _open_ground(out, solid):
    """The zone's connected open ground: the largest part touching its paths,
    or the largest part when it has none."""
    free = out.rect.cells() - solid
    best, best_key, seen = set(), (False, 0), set()
    for start in sorted(free):
        if start in seen:
            continue
        part, queue = {start}, deque([start])
        while queue:
            x, y = queue.popleft()
            for c in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if c in free and c not in part:
                    part.add(c)
                    queue.append(c)
        seen |= part
        key = (bool(out.reserved & part), len(part))
        if key > best_key:
            best, best_key = part, key
    return best


def _doors(b):
    bl = b.layout
    cells = {bl.entrance_door} | set(getattr(bl, "extra_doors", []) or ())
    for room in bl.rooms:
        cells |= room.doors
    cells.discard(None)
    return cells


def _floor(parts, corridors, templates):
    """The rooms with their standable cells, and every cell of the complex
    someone can walk on."""
    rooms, cells = [], set()
    for b in parts:
        for room in b.layout.rooms:
            furniture = set()
            for (name, pos) in (room.furniture.placements if room.furniture else ()):
                t = templates[name]
                if t.walkability <= 0:
                    furniture |= {(x, y) for x in range(pos[0], pos[0] + t.size[0])
                                  for y in range(pos[1], pos[1] + t.size[1])}
            inside = room.rect.interior().cells() - furniture
            rooms.append((b, room, inside))
            cells |= inside
        cells |= _doors(b)
    for c in corridors:
        cells |= c.rect.interior().cells()
        for b in parts:                  # the corridor's half of each door
            cells |= set(shared_wall_cells(b.layout.rect, c.rect))
    return rooms, cells


def _walk(starts, cells):
    dist = {c: 0 for c in starts if c in cells}
    queue = deque(dist)
    while queue:
        x, y = queue.popleft()
        d = dist[(x, y)] + 1
        for c in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if c in cells and c not in dist:
                dist[c] = d
                queue.append(c)
    return dist


def _worst(rooms, dist):
    """The longest walk from any room to a way out."""
    return max((dist[c] for (_b, _r, inside) in rooms for c in inside if c in dist),
               default=0)


def _outside_of(cell, ground):
    x, y = cell
    for c in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
        if c in ground:
            return c
    return None


def _spots(rooms, doors, ground, reachable):
    """One door cell per outer wall of each room, nearest the wall's middle."""
    spots = []
    for (b, room, _inside) in rooms:
        r, br = room.rect, b.layout.rect
        walls = []
        if r.x == br.x:
            walls.append([(r.x, y) for y in range(r.y + 1, r.y1)])
        if r.x1 == br.x1:
            walls.append([(r.x1, y) for y in range(r.y + 1, r.y1)])
        if r.y == br.y:
            walls.append([(x, r.y) for x in range(r.x + 1, r.x1)])
        if r.y1 == br.y1:
            walls.append([(x, r.y1) for x in range(r.x + 1, r.x1)])
        inside = r.interior().cells() & reachable
        for wall in walls:
            mid = len(wall) / 2.0
            for i in sorted(range(len(wall)), key=lambda k: abs(k + 0.5 - mid)):
                cell = wall[i]
                x, y = cell
                near = {(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)}
                inner = near & inside
                outer = _outside_of(cell, ground)
                if cell in doors or near & doors or not inner or outer is None:
                    continue
                spots.append((b, room, cell, min(inner), outer))
                break
    return spots


def _open_complex(out, name, parts, corridors, templates, ground, need):
    from .layout_compound import _door_into_room

    rooms, cells = _floor(parts, corridors, templates)
    doors = set().union(*(_doors(b) for b in parts))
    exits = {d for d in doors if _outside_of(d, ground) is not None}
    for _ in range(MAX_NEW_EXITS):
        dist = _walk(exits, cells)
        worst = _worst(rooms, dist)
        if worst <= EXIT_REACH and len(exits) >= need:
            break
        best = None
        for (b, room, cell, inner, outer) in _spots(rooms, doors, ground, set(dist)):
            walk = _worst(rooms, _walk(exits | {inner}, cells))
            # any spot inside the limit will do, so a public room wins there
            key = (max(walk, EXIT_REACH), is_sleep_name(room.base_name), walk, cell)
            if best is None or key < best[0]:
                best = (key, b, room, cell, outer)
        if best is None or (best[0][2] >= worst and len(exits) >= need):
            break
        _key, b, room, cell, outer = best
        _door_into_room(b.layout, cell)
        doors.add(cell)
        exits.add(cell)
        cells.add(cell)
        step = (2 * outer[0] - cell[0], 2 * outer[1] - cell[1])
        out.reserved.add(outer)
        if step in ground:
            out.reserved.add(step)
        out.side_exits.append((name, room.base_name, cell))


def add_exits(out, templates):
    """Give every big building and complex in the zone its ways out."""
    if out.zone.exterior == "void":
        return
    ground = _open_ground(out, solid_ground(out))
    if not ground:
        return
    in_compound = set()
    for comp in out.compounds:
        in_compound |= {id(b) for b in comp.parts}
        if comp.compound.shape in ("spine", "cluster", "row") and comp.parts:
            _open_complex(out, comp.name, comp.parts, comp.corridors, templates, ground,
                          COMPLEX_EXITS if len(comp.parts) > 1 else 1)
    for b in out.buildings:
        if id(b) not in in_compound:
            _open_complex(out, b.layout.design.name, [b], [], templates, ground, 1)
