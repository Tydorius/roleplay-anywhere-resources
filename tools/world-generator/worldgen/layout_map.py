"""Zones on the map.

The settlement sits in the middle of the map; the other zones surround it,
each on the side its adjacency points at, as bands on the map's sides. A thin
margin of open country frames the map, so no zone ever spans it edge to
edge, and the margins carry the roads that have to walk between zones. The
gutters between neighbouring zones (2-3 cells) carry the roads that cross
directly, so roads run continuously from zone to zone.

A settlement zone is sized to its content — its buildings' footprints, the
street grid and a coverage target (packed city blocks, loose villages) — so
several settlement zones form one connected urban core of neighbouring
blocks side by side, and the grid is those zones plus the wild margin
(48x48 at least).

With the region-groups extension a surrounding zone may take two touching
rects, one on each of two adjacent sides, wrapping itself round a corner —
a forest round two sides of a village, say. The pieces share the zone's
name in the spec through a regionGroup field; the game mod
examples/region-groups makes them act as one region.
"""
import math

from .model import Rect, building_coverage_target, zone_class

GRID_MIN, GRID_MAX = 48, 160
MIN_GUTTER, MAX_GUTTER = 2, 3   # empty cells between neighbouring zones
MIN_ZONE_SIDE = 12              # thinnest zone the partition ever cuts
AREA_HEADROOM = 1.15            # grid area over the zones' nominal area
FIT_SLACK = 0.85                # footprint estimates run hot; buildings resolve smaller
SIDES = ("west", "east", "north", "south")
OPPOSITE = {"west": "east", "east": "west", "north": "south", "south": "north"}

ROAD_GROUND = {
    "dirt": ("dirt", "dirt"),
    "gravel": ("gravel", "gravel"),
    "cobble": ("stone", "cobblestone"),
    "paved": ("stone", "flagstone-light"),
}

GROUND_TEXTURES = {
    "grass": ("grass", "grass"), "dirt": ("dirt", "dirt"),
    "gravel": ("gravel", "gravel"), "stone": ("stone", "rock"),
}


class RoadOut:
    def __init__(self, name, rects, kind, a, b):
        self.name = name
        self.rects = rects   # disjoint Rects forming the road
        self.kind = kind
        self.a = a           # endpoint zone names
        self.b = b

    @property
    def ground(self):
        return ROAD_GROUND.get(self.kind, ("dirt", "dirt"))

    def cells(self):
        s = set()
        for r in self.rects:
            s |= r.cells()
        return s


class MapOut:
    def __init__(self):
        self.grid = (GRID_MIN, GRID_MIN)
        self.zones = {}          # zone name -> primary Rect (the biggest piece)
        self.zone_pieces = {}    # zone name -> [Rect] (one, except wraps)
        self.roads = []          # [RoadOut]
        self.zone_road_reserve = {}  # zone name -> cells that must stay clear (road mouths)
        self.failures = []
        self.default_ground = ("grass", "grass")  # the plan's dominant wild ground
        self.density_scale = 1.0                 # setting density -> filler scale
        self.extensions = set()
        self.field_names = set()                 # field plot names across all zones

    def all_pieces(self):
        return [(name, r) for name, rects in self.zone_pieces.items() for r in rects]


def layout_map(plan, rng, extensions=(), weight_scale=None):
    """Place the zones on the grid and lay the roads; returns a MapOut.
    ``weight_scale`` multiplies selected zones' weights (a second pass
    nudging zones whose measured building coverage missed its target)."""
    from .layout_zone import ZONE_SIZES, PATH_WIDTH, lot_spacing, side_street_count
    from .layout_building import building_footprint

    tmap = {t.name: t for t in plan.templates}

    def zone_fit(z):
        """(area, cross, along) the zone's street grid and lots need: the
        widest pair of buildings facing across the street, the fuller side's
        row along it, and (for a settlement grid) the side streets' bite out
        of the street's length."""
        fps = sorted((building_footprint(b, tmap) for b in z.buildings),
                     key=lambda f: (-f[0], -f[1]))
        spacing = lot_spacing(z)
        sides = ([], [])
        for f in fps:   # big first, alternating sides like the band packer
            sides[1 if len(sides[1]) < len(sides[0]) else 0].append(f)
        cross = 4 + spacing + PATH_WIDTH + \
            sum((max(f[0] for f in s) if s else 0) for s in sides)
        along = 6 + max((sum(f[1] + spacing for f in s) for s in sides), default=0)
        if zone_class(z) == "settlement":
            k = side_street_count(max(ZONE_SIZES[z.size_class]), len(z.buildings))
            along += k * (spacing + 3)
        return cross * along, cross, along

    def zone_weight(z):
        """The zone's nominal area, or the area its content actually needs
        (footprints plus paths, yards and props), whichever is larger. A
        settlement zone is sized for its building coverage target instead of
        the loose 4x footprint rule."""
        nominal = ZONE_SIZES[z.size_class][0] * ZONE_SIZES[z.size_class][1]
        if not z.buildings:
            return nominal
        built = sum(building_footprint(b, tmap)[0] * building_footprint(b, tmap)[1]
                    for b in z.buildings)
        if zone_class(z) == "settlement":
            return max(nominal, zone_fit(z)[0] * FIT_SLACK,
                       built / building_coverage_target(z, plan.setting))
        return max(nominal, 4 * built, zone_fit(z)[0])

    def zone_min_side(z):
        """The narrowest the zone may be cut: its widest building plus the
        street and its margins (and, for a settlement, its street grid's
        width), so a band can always hold it."""
        if not z.buildings:
            return MIN_ZONE_SIDE
        widest = max(max(building_footprint(b, tmap)) for b in z.buildings)
        base = max(MIN_ZONE_SIDE, widest + lot_spacing(z) + PATH_WIDTH + 4)
        if zone_class(z) == "settlement":
            base = max(base, round(zone_fit(z)[1] * FIT_SLACK))
        return base

    scale = weight_scale or {}
    weights = {z.name: zone_weight(z) * scale.get(z.name, 1.0) for z in plan.zones}
    mins = {z.name: zone_min_side(z) for z in plan.zones}
    aspects = {z.name: ZONE_SIZES[z.size_class][0] / float(ZONE_SIZES[z.size_class][1])
               for z in plan.zones}
    fits = {z.name: tuple(c * FIT_SLACK for c in zone_fit(z)) for z in plan.zones
            if zone_class(z) == "settlement" and z.buildings}
    margin = rng.randint(2, 3)
    gut = rng.randint(MIN_GUTTER, MAX_GUTTER)

    # several settlement zones sit as blocks side by side: the core is as
    # wide as their street grids and as tall as the fullest one; the greater
    # of that span and their weight sum shapes the grid
    core = None
    if len(fits) >= 2:
        core = (sum(f[1] for f in fits.values()) + gut * (len(fits) - 1),
                max(f[2] for f in fits.values()),
                sum(weights[n] for n in fits))
    m = MapOut()
    m.grid = _grid_size(weights, core)
    m.extensions = set(extensions)
    m.density_scale = {"sparse": 0.6, "normal": 1.0, "dense": 1.4}.get(
        (plan.setting or {}).get("density"), 1.0)
    _place_centred(plan, m, weights, mins, aspects, rng, fits, margin, gut)
    m.roads, road_failures = _place_roads(plan, m.zones, m.grid, rng, m.all_pieces())
    m.failures.extend(road_failures)
    m.zone_road_reserve = _road_mouths(m.all_pieces(), m.roads)
    m.default_ground = _default_ground(plan, weights)
    return m


# ------------------------------------------------------------------ placement

def _place_centred(plan, m, weights, mins, aspects, rng, fits=None, margin=2, gut=2):
    """The settlement group takes a central block; every other zone takes a
    band on the side its adjacency points at. A thin margin of open country
    frames the map, so no zone spans it edge to edge; the leftover margin is
    where roads walk when their endpoints do not face each other.

    The settlement group forms one connected core: its zones sit as
    neighbouring blocks side by side, so the core is as wide as their
    street grids and the grid stretches to fit before anything is placed."""
    fits = fits or {}
    W, H = m.grid
    classes = {z.name: zone_class(z) for z in plan.zones}
    settle = [z for z in plan.zones if classes[z.name] == "settlement"]
    if not settle:
        settle = [max(plan.zones, key=lambda z: (len(z.buildings), weights[z.name]))]
    settle_names = {z.name for z in settle}
    outer = [z for z in plan.zones if z.name not in settle_names]

    sides = _assign_sides(plan, settle, outer, weights, rng, W, H)

    # the core's blocks and the bands around them pin the grid's least size;
    # stretch once, then resolve the sides again on the real grid. A wrap can
    # add one more band than the sides show, so it gets a reserve too.
    core_names = [n for n in settle_names if n in fits]
    if len(core_names) >= 2:
        crosses = [fits[n][1] for n in core_names]
        alongs = [fits[n][2] for n in core_names]
        core_w = sum(crosses) + gut * (len(core_names) - 1)
        core_h = max(alongs)
        need_w = core_w + 2 * margin
        need_h = core_h + 2 * margin
        for s in ("west", "east"):
            if sides[s]:
                need_w += gut + max(mins[n] for n in sides[s])
        for s in ("south", "north"):
            if sides[s]:
                need_h += gut + max(mins[n] for n in sides[s])
        if "region-groups" in m.extensions and outer:
            need_w += gut + MIN_ZONE_SIDE
            need_h += gut + MIN_ZONE_SIDE
        stretched = (min(GRID_MAX, max(W, round(need_w))), min(GRID_MAX, max(H, round(need_h))))
        if stretched != (W, H):
            W, H = stretched
            m.grid = (W, H)
            sides = _assign_sides(plan, settle, outer, weights, rng, W, H)

    # the core's blocks also pin the centre's least size on each axis: cut
    # as a row on a wide map (blocks side by side), as a column on a tall one
    cmin = {s: max([mins[n] for n in settle_names] + [MIN_ZONE_SIDE]) for s in SIDES}
    if len(core_names) >= 2:
        if W >= H:
            cmin["west"] = cmin["east"] = core_w
            cmin["south"] = cmin["north"] = core_h
        else:
            cmin["west"] = cmin["east"] = max(crosses)
            cmin["south"] = cmin["north"] = sum(alongs) + gut * (len(alongs) - 1)
    wraps = _choose_wraps(outer, sides, classes, weights, rng) \
        if "region-groups" in m.extensions else {}

    def band_weight(side):
        total = sum(weights[n] for n in sides[side])
        total += sum(weights[n] for n, (v, h) in wraps.items()
                     if side in (v, h) and n not in sides[side])
        return total

    def band_min(side):
        ms = [mins[n] for n in sides[side]]
        ms += [mins[n] for n, (v, h) in wraps.items()
               if side in (v, h) and n not in sides[side]]
        return max(ms + [0])

    # ---- axis layouts: [band?, centre, band?]. The centre block absorbs all
    # the slack, and the bands are capped so the centre provably stays in the
    # middle third of the map however lopsided the zone weights are.
    def axis(side_lo, side_hi, span):
        center_wgt = sum(weights[n] for n in settle_names)
        center_min = max([mins[n] for n in settle_names]
                         + [MIN_ZONE_SIDE, cmin[side_lo]])
        active = ([(band_weight(side_lo), band_min(side_lo))] if sides[side_lo] else []) + \
                 [(center_wgt, center_min)] + \
                 ([(band_weight(side_hi), band_min(side_hi))] if sides[side_hi] else [])
        avail = span - 2 * margin - gut * (len(active) - 1)
        sizes = _sizes_mins(avail, [w for (w, _mn) in active],
                            [mn for (_w, mn) in active])
        has_lo, has_hi = bool(sides[side_lo]), bool(sides[side_hi])
        lo_min, hi_min = band_min(side_lo), band_min(side_hi)
        lo_i, hi_i = (0 if has_lo else None), (len(active) - 1 if has_hi else None)
        if has_lo and has_hi and abs(sizes[lo_i] - sizes[hi_i]) > span // 3:
            i = lo_i if sizes[lo_i] > sizes[hi_i] else hi_i
            sizes[i] = max(sizes[lo_i + hi_i - i] + span // 3,
                           lo_min if i == 0 else hi_min)
        elif has_lo != has_hi:
            # one band: leave room for the centre to sit at least a third of
            # the way in from the empty side
            i = lo_i if has_lo else hi_i
            sizes[i] = min(sizes[i], max(span // 3 - 1 - margin - gut,
                                         lo_min if i == lo_i else hi_min))
        d_lo = sizes[lo_i] if has_lo else 0
        d_hi = sizes[hi_i] if has_hi else 0
        c_size = avail - d_lo - d_hi
        ranges = {side_lo: None, "center": None, side_hi: None}
        pos = margin
        if has_lo:
            ranges[side_lo] = (pos, pos + d_lo - 1)
            pos += d_lo + gut
        ranges["center"] = (pos, pos + c_size - 1)
        pos += c_size + gut
        if has_hi:
            ranges[side_hi] = (pos, pos + d_hi - 1)
        return ranges

    xr = axis("west", "east", W)
    yr = axis("south", "north", H)
    vertical_full = rng.random() < 0.5
    bands = _ring_bands(xr, yr, margin, gut, W, H, vertical_full)

    # ---- the settlement group partitions the central block
    pieces = {z.name: [] for z in plan.zones}
    if xr["center"] and yr["center"]:
        center = Rect(xr["center"][0], yr["center"][0],
                      xr["center"][1] - xr["center"][0] + 1,
                      yr["center"][1] - yr["center"][0] + 1)
        adj = _symmetric_adjacency(plan)
        s_adj = {n: adj[n] & settle_names for n in settle_names}
        comps = _components(settle_names, s_adj)
        for a, b in zip(comps, comps[1:]):   # bridge disconnected groups
            s_adj[a[0]].add(b[0])
            s_adj[b[0]].add(a[0])
        local = {}
        _partition(center, sorted(settle_names), None, None, s_adj, weights,
                   aspects, rng, local, mins)
        for n, r in local.items():
            pieces[n] = [r]

    # ---- the surrounding bands; a wrap's weight was counted on both bands,
    # so it is a member of both and gets a segment in each
    band_zones = {s: list(sides[s]) for s in SIDES if s in bands}
    for n, (v, h) in wraps.items():
        for s in (v, h):
            if s in band_zones and n not in band_zones[s]:
                band_zones[s].append(n)

    seg_by_band = {}   # (side, name) -> Rect
    for side, band in bands.items():
        members = band_zones.get(side) or []
        if not members:
            continue
        pinned = {}
        for n, (v, h) in wraps.items():
            if side == v and h in bands:
                pinned[n] = h          # a vertical band pins to north/south
            elif side == h and v in bands:
                pinned[n] = v          # a horizontal band pins to west/east
        segs = _stack_band(band, side, members, pinned, weights, mins, gut, rng)
        for n, r in segs.items():
            seg_by_band[(side, n)] = r
            pieces[n].append(r)

    # ---- a wrap's perpendicular piece slides flush against its corner piece
    # (no gutter between two pieces of one zone, so they read as one region)
    for n, (v, h) in wraps.items():
        if (v, n) not in seg_by_band or (h, n) not in seg_by_band:
            continue
        corner = seg_by_band[(v, n)]
        flush = seg_by_band[(h, n)]
        if vertical_full:
            dx = -gut if v == "west" else gut
            seg_by_band[(h, n)] = Rect(flush.x + dx, flush.y, flush.w, flush.h)
        else:
            dy = -gut if h == "south" else gut
            seg_by_band[(v, n)] = Rect(corner.x, corner.y + dy, corner.w, corner.h)
        pieces[n] = [seg_by_band[(v, n)], seg_by_band[(h, n)]]

    for z in plan.zones:
        if not pieces[z.name]:
            m.failures.append((f"zone {z.name}", "not placed"))
    m.zones = {z.name: max(pieces[z.name], key=lambda r: (r.w * r.h, r.x, r.y))
               for z in plan.zones if pieces[z.name]}
    m.zone_pieces = {z.name: pieces[z.name] for z in plan.zones if pieces[z.name]}


def _ring_bands(xr, yr, margin, gut, W, H, vertical_full):
    """The four side bands. Vertical-full: the west/east bands span the map's
    full height and the north/south bands fill the span between them (the
    corners belong to the vertical bands). Horizontal-full mirrors that."""
    bands = {}
    if vertical_full:
        if xr["west"]:
            xr0, xr1 = xr["west"]
            bands["west"] = Rect(xr0, margin, xr1 - xr0 + 1, H - 2 * margin)
        if xr["east"]:
            xr0, xr1 = xr["east"]
            bands["east"] = Rect(xr0, margin, xr1 - xr0 + 1, H - 2 * margin)
        x0 = (xr["west"][1] + 1 + gut) if xr["west"] else margin
        x1 = (xr["east"][0] - 1 - gut) if xr["east"] else W - 1 - margin
        if x1 >= x0:
            if yr["north"]:
                yr0, yr1 = yr["north"]
                bands["north"] = Rect(x0, yr0, x1 - x0 + 1, yr1 - yr0 + 1)
            if yr["south"]:
                yr0, yr1 = yr["south"]
                bands["south"] = Rect(x0, yr0, x1 - x0 + 1, yr1 - yr0 + 1)
    else:
        if yr["south"]:
            yr0, yr1 = yr["south"]
            bands["south"] = Rect(margin, yr0, W - 2 * margin, yr1 - yr0 + 1)
        if yr["north"]:
            yr0, yr1 = yr["north"]
            bands["north"] = Rect(margin, yr0, W - 2 * margin, yr1 - yr0 + 1)
        y0 = (yr["south"][1] + 1 + gut) if yr["south"] else margin
        y1 = (yr["north"][0] - 1 - gut) if yr["north"] else H - 1 - margin
        if y1 >= y0:
            if xr["west"]:
                xr0, xr1 = xr["west"]
                bands["west"] = Rect(xr0, y0, xr1 - xr0 + 1, y1 - y0 + 1)
            if xr["east"]:
                xr0, xr1 = xr["east"]
                bands["east"] = Rect(xr0, y0, xr1 - xr0 + 1, y1 - y0 + 1)
    return bands


def _stack_band(band, side, members, pinned, weights, mins, gut, rng):
    """Cut one band into per-zone segments. Pinned zones (a wrap's pieces)
    sit at their end of the band; the rest fill the middle by weight from a
    seeded end. Returns {name: Rect}."""
    along = band.h if side in ("west", "east") else band.w
    sizes = _sizes_mins(along - gut * (len(members) - 1),
                        [weights[n] for n in members],
                        [min(max(mins[n], MIN_ZONE_SIDE), along) for n in members])
    size_of = dict(zip(members, sizes))

    def place(n, start, size):
        if side in ("west", "east"):
            return Rect(band.x, band.y + start, band.w, size)
        return Rect(band.x + start, band.y, size, band.h)

    out = {}
    lo, hi = 0, along - 1
    for (n, end) in sorted(pinned.items(), key=lambda kv: (-size_of[kv[0]], kv[0])):
        size = min(size_of[n], hi - lo + 1)
        if end in ("north", "east"):       # the band's high end
            out[n] = place(n, hi - size + 1, size)
            hi -= size + gut
        else:
            out[n] = place(n, lo, size)
            lo += size + gut
    middle = [n for n in members if n not in pinned]
    middle.sort(key=lambda n: (-weights[n], n))
    if rng.random() < 0.5:
        middle.reverse()
    for n in middle:
        size = min(size_of[n], max(1, hi - lo + 1))
        out[n] = place(n, lo, size)
        lo += size + gut
    return out


def _components(names, adj):
    seen = set()
    comps = []
    for n in sorted(names):
        if n in seen:
            continue
        comp, todo = [], [n]
        seen.add(n)
        while todo:
            cur = todo.pop(0)
            comp.append(cur)
            for nb in sorted(adj[cur]):
                if nb in names and nb not in seen:
                    seen.add(nb)
                    todo.append(nb)
        comps.append(sorted(comp))
    return comps


def _assign_sides(plan, settle, outer, weights, rng, W, H):
    """Each surrounding zone goes to the side its settlement adjacency points
    at: the direction from the settlement zone it touches towards the middle
    of the map. Zones with no settlement neighbour follow an adjacent outer
    zone, and loads are balanced so the sides fill evenly."""
    settle_names = {z.name for z in settle}
    adj = _symmetric_adjacency(plan)
    # a nominal central partition learns where each settlement zone sits
    nominal_w = max(2 * MIN_ZONE_SIDE, int(round(W * 0.5)))
    nominal_h = max(2 * MIN_ZONE_SIDE, int(round(H * 0.5)))
    s_adj = {n: adj[n] & settle_names for n in settle_names}
    comps = _components(settle_names, s_adj)
    for a, b in zip(comps, comps[1:]):
        s_adj[a[0]].add(b[0])
        s_adj[b[0]].add(a[0])
    pos = {}
    _partition(Rect((W - nominal_w) // 2, (H - nominal_h) // 2, nominal_w, nominal_h),
               sorted(settle_names), None, None, s_adj, weights,
               {n: 1.0 for n in settle_names}, rng, pos,
               {n: MIN_ZONE_SIDE for n in settle_names})

    cx, cy = W / 2.0, H / 2.0
    sides = {s: [] for s in SIDES}
    resolved = {}

    def votes_for(z):
        votes = []
        for n in z.adjacentTo:
            if n in pos:
                px, py = pos[n].center()
                dx, dy = cx - px, cy - py
                if abs(dx) > abs(dy) + 1:
                    votes.append("west" if dx > 0 else "east")
                elif abs(dy) > abs(dx) + 1:
                    votes.append("south" if dy > 0 else "north")
        if not votes:
            for n in z.adjacentTo:
                if n in resolved:
                    votes.append(resolved[n])
        return votes

    pending = sorted(outer, key=lambda z: (-weights[z.name], z.name))
    while pending:
        progressed = False
        for z in list(pending):
            votes = votes_for(z)
            if not votes:
                continue   # retry once more zones have resolved
            load = {s: sum(weights[n] for n in sides[s]) for s in SIDES}
            side = min(votes, key=lambda s: (load[s], s))
            sides[side].append(z.name)
            resolved[z.name] = side
            pending.remove(z)
            progressed = True
        if not progressed:
            # nothing is adjacent to anything placed: spread by weight
            for z in pending:
                load = {s: sum(weights[n] for n in sides[s]) for s in SIDES}
                side = min(SIDES, key=lambda s: (load[s], s))
                sides[side].append(z.name)
                resolved[z.name] = side
            pending = []

    # neighbouring zones stuck on opposite sides join up on one axis
    for z in outer:
        for n in z.adjacentTo:
            if n in resolved and n not in settle_names and \
                    resolved[n] == OPPOSITE[resolved[z.name]]:
                base = resolved[n]
                perp = ("north", "south") if base in ("west", "east") else ("west", "east")
                load = {s: sum(weights[k] for k in sides[s]) for s in perp}
                new_side = min(perp, key=lambda s: (load[s], s))
                mover = z.name if weights[z.name] <= weights[n] else n
                sides[resolved[mover]].remove(mover)
                sides[new_side].append(mover)
                resolved[mover] = new_side

    # exactly two surrounding zones: keep their sides adjacent, so a corner
    # exists between them (and a wrap can bridge it)
    if len(outer) == 2:
        a, b = outer[0].name, outer[1].name
        if resolved[a] == OPPOSITE[resolved[b]]:
            mover = a if rng.random() < 0.5 else b
            other = resolved[b if mover == a else a]
            perp = ("north", "south") if other in ("west", "east") else ("west", "east")
            new_side = perp[rng.randrange(2)]
            sides[resolved[mover]].remove(mover)
            sides[new_side].append(mover)
            resolved[mover] = new_side
    return sides


def _choose_wraps(outer, sides, classes, weights, rng):
    """Pick up to two surrounding zones (wild first, then the biggest) to
    wrap round a corner: they take touching pieces on two adjacent sides. A
    lone surrounding zone always wraps, so it surrounds rather than flanks."""
    wraps = {}
    corners = [("west", "north"), ("east", "north"), ("east", "south"), ("west", "south")]
    rng.shuffle(corners)
    if len(outer) == 1:
        n = outer[0].name
        for (v, h) in corners:
            if n in sides[v] or n in sides[h]:
                wraps[n] = (v, h)
                for s in (v, h):
                    if n not in sides[s]:
                        sides[s].append(n)
                return wraps
        return wraps
    for (v, h) in corners:
        if len(wraps) >= 2:
            break
        if not sides[v] or not sides[h]:
            continue
        pool = [n for n in sides[v] + sides[h] if n not in wraps]
        if not pool:
            continue
        pool.sort(key=lambda n: (0 if classes[n] == "wild" else 1,
                                 -weights[n], n))
        if rng.random() < 0.7 or not wraps:
            # the first wrap is guaranteed: a corner between two populated
            # sides reads as one land round the settlement, not two slabs
            wraps[pool[0]] = (v, h)
    return wraps

def _grid_size(weights, core=None):
    """Grid area from the zone weights. ``core`` is (w, h, weight): the
    settlement core's own span when it is a row of blocks — the greater of
    that rectangle and the settlement weights shapes the grid, so the core's
    blocks stay blocks instead of stretching into bands."""
    area = float(sum(weights.values()))
    aspect = 1.0
    if core:
        area = area - core[2] + max(core[2], core[0] * core[1])
        aspect = core[0] / float(core[1])
    area *= AREA_HEADROOM
    gw = max(GRID_MIN, min(GRID_MAX, int(round(math.sqrt(area * aspect)))))
    gh = max(GRID_MIN, min(GRID_MAX, int(round(area / gw))))
    return (gw, gh)


def _symmetric_adjacency(plan):
    adj = {z.name: set() for z in plan.zones}
    for z in plan.zones:
        for n in z.adjacentTo:
            if n in adj:
                adj[z.name].add(n)
                adj[n].add(z.name)
    return adj


def _bfs_tree(root, members, adj, weights):
    """Parent->children tree over `members` from `root`, biggest neighbour first."""
    children = {n: [] for n in members}
    seen = {root}
    todo = [root]
    while todo:
        n = todo.pop(0)
        for nb in sorted(adj[n] & (set(members) - seen), key=lambda m: (-weights[m], m)):
            seen.add(nb)
            children[n].append(nb)
            todo.append(nb)
    return children


def _subtree(lead, children):
    out, todo = [lead], [lead]
    while todo:
        n = todo.pop(0)
        for c in children[n]:
            out.append(c)
            todo.append(c)
    return out


def _partition(rect, members, entry, anchor, adj, weights, aspects, rng, assign, mins):
    """Cut `rect` among the connected zone group `members`. `entry` is the
    member that must sit against `anchor` (the side of `rect` facing the
    already-placed neighbour), or None when the group is free."""
    if len(members) == 1:
        assign[members[0]] = rect
        return
    root = entry if entry in members else max(members, key=lambda n: (weights[n], n))
    children = _bfs_tree(root, members, adj, weights)
    arms = children[root]
    if len(arms) == 1:
        lead = arms[0]
        rest = _subtree(lead, children)
        side = _chain_side(rect, root, rest, anchor, weights, aspects, rng)
        gut = rng.randint(MIN_GUTTER, MAX_GUTTER)
        axis = rect.w if side in ("west", "east") else rect.h
        size = _sizes_mins(axis - gut, [weights[root], sum(weights[n] for n in rest)],
                           [mins[root], max([mins[n] for n in rest] + [MIN_ZONE_SIDE])])[0]
        strip, rest_rect = _cut(rect, side, size, gut)
        assign[root] = strip
        _partition(rest_rect, rest, lead, side, adj, weights, aspects, rng, assign, mins)
    elif anchor is None and len(arms) <= 4:
        _frame(rect, root, arms, children, adj, weights, aspects, rng, assign, mins)
    else:
        _teeth(rect, root, arms, children, anchor, adj, weights, aspects, rng, assign, mins)


def _chain_side(rect, root, rest, anchor, weights, aspects, rng):
    """Which side to cut the root strip from. Any side works without an
    anchor; with one, the strip must span the anchor side so the root keeps
    touching its neighbour. Prefers the cut giving the root its nominal shape."""
    if anchor is None:
        cands = ("west", "east", "north", "south")
    else:
        perp = ("north", "south") if anchor in ("west", "east") else ("west", "east")
        cands = (anchor,) + perp
    total = weights[root] + sum(weights[n] for n in rest)
    scored = []
    for side in cands:
        axis = rect.w if side in ("west", "east") else rect.h
        span = rect.h if side in ("west", "east") else rect.w
        if axis <= MIN_ZONE_SIDE + MIN_GUTTER + 1:
            continue
        avail = axis - MIN_GUTTER
        size = max(MIN_ZONE_SIDE, min(avail - MIN_ZONE_SIDE, round(avail * weights[root] / total)))
        aspect = size / float(span) if side in ("west", "east") else span / float(size)
        scored.append((abs(math.log(max(aspect, 1e-6) / aspects[root])) + rng.random() * 0.3, side))
    if not scored:
        return anchor or "west"
    scored.sort()
    return scored[0][1]


def _cut(rect, side, size, gut):
    size = max(1, size)
    if side == "west":
        return (Rect(rect.x, rect.y, size, rect.h),
                Rect(rect.x + size + gut, rect.y, max(1, rect.w - size - gut), rect.h))
    if side == "east":
        return (Rect(rect.x1 - size + 1, rect.y, size, rect.h),
                Rect(rect.x, rect.y, max(1, rect.w - size - gut), rect.h))
    if side == "north":
        return (Rect(rect.x, rect.y1 - size + 1, rect.w, size),
                Rect(rect.x, rect.y, rect.w, max(1, rect.h - size - gut)))
    return (Rect(rect.x, rect.y, rect.w, size),
            Rect(rect.x, rect.y + size + gut, rect.w, max(1, rect.h - size - gut)))


def _frame(rect, root, arms, children, adj, weights, aspects, rng, assign, mins):
    """A hub: the root takes the centre, its neighbours' subtrees fill the
    sides of the frame around it (every arm touches the centre)."""
    all_sides = ["west", "east", "south", "north"]
    k = len(arms)
    if k == 2:
        # cut side to side on a wide block (each zone a compact block), stack
        # on a tall one; the core is as wide as its blocks, so wide is usual
        sides = list(("west", "east") if rect.w >= rect.h else ("south", "north"))
    elif k == 3:
        sides = [s for s in all_sides if s != rng.choice(all_sides)]
    else:
        rot = rng.randrange(4)
        sides = all_sides[rot:] + all_sides[:rot]
    arms_sorted = sorted(arms, key=lambda n: (-weights[n], n))
    side_of = dict(zip(arms_sorted, sides))
    sub = {a: _subtree(a, children) for a in arms_sorted}
    gut = rng.randint(MIN_GUTTER, MAX_GUTTER)

    def axis_sizes(vertical):
        # the Y stack: south arms, root, north arms; the X stack: west, root, east
        parts = []
        part_mins = []
        for a in arms_sorted:
            if side_of[a] == ("south" if vertical else "west"):
                parts.append(sum(weights[n] for n in sub[a]))
                part_mins.append(max(mins[n] for n in sub[a]))
        parts.append(weights[root])
        part_mins.append(mins[root])
        for a in arms_sorted:
            if side_of[a] == ("north" if vertical else "east"):
                parts.append(sum(weights[n] for n in sub[a]))
                part_mins.append(max(mins[n] for n in sub[a]))
        axis = rect.h if vertical else rect.w
        n_gaps = len(parts) - 1
        return _sizes_mins(axis - gut * n_gaps, parts, part_mins)

    heights = axis_sizes(vertical=True)    # south?, centre, north?
    widths = axis_sizes(vertical=False)    # west?, centre, east?
    has_s = any(side_of[a] == "south" for a in arms_sorted)
    has_n = any(side_of[a] == "north" for a in arms_sorted)
    has_w = any(side_of[a] == "west" for a in arms_sorted)
    has_e = any(side_of[a] == "east" for a in arms_sorted)
    ss = heights[0] if has_s else 0
    cs = heights[len(heights) // 2]
    nn = heights[-1] if has_n else 0
    sw = widths[0] if has_w else 0
    cw = widths[len(widths) // 2]
    ee = widths[-1] if has_e else 0
    x0 = rect.x + sw + (gut if has_w else 0)
    y0 = rect.y + ss + (gut if has_s else 0)
    assign[root] = Rect(x0, y0, cw, cs)
    for a in arms_sorted:
        s = side_of[a]
        if s == "south":
            ar = Rect(x0, rect.y, cw, ss)
        elif s == "north":
            ar = Rect(x0, rect.y1 - nn + 1, cw, nn)
        elif s == "west":
            ar = Rect(rect.x, rect.y, sw, rect.h)
        else:
            ar = Rect(rect.x1 - ee + 1, rect.y, ee, rect.h)
        facing = {"south": "north", "north": "south", "west": "east", "east": "west"}[s]
        _partition(ar, sub[a], a, facing, adj, weights, aspects, rng, assign, mins)


def _teeth(rect, root, arms, children, anchor, adj, weights, aspects, rng, assign, mins):
    """A hub against an outside neighbour: the root is a strip along the
    anchor side and every arm is a strip cut from the remainder, so each arm
    (and the root) touches what it must."""
    subs = [_subtree(a, children) for a in sorted(arms, key=lambda n: (-weights[n], n))]
    flat = [n for sub in subs for n in sub]
    side = anchor or _chain_side(rect, root, flat, None, weights, aspects, rng)
    gut = rng.randint(MIN_GUTTER, MAX_GUTTER)
    axis = rect.w if side in ("west", "east") else rect.h
    size = _sizes_mins(axis - gut, [weights[root], sum(weights[n] for n in flat)],
                       [mins[root], max([mins[n] for n in flat] + [MIN_ZONE_SIDE])])[0]
    strip, rest = _cut(rect, side, size, gut)
    assign[root] = strip
    if side in ("west", "east"):
        sizes = _sizes_mins(rest.h - gut * (len(subs) - 1),
                            [sum(weights[n] for n in s) for s in subs],
                            [max(mins[n] for n in s) for s in subs])
        y = rest.y
        for sub, h in zip(subs, sizes):
            _partition(Rect(rest.x, y, rest.w, h), sub, sub[0], side,
                       adj, weights, aspects, rng, assign, mins)
            y += h + gut
    else:
        sizes = _sizes_mins(rest.w - gut * (len(subs) - 1),
                            [sum(weights[n] for n in s) for s in subs],
                            [max(mins[n] for n in s) for s in subs])
        x = rest.x
        for sub, w in zip(subs, sizes):
            _partition(Rect(x, rest.y, w, rest.h), sub, sub[0], side,
                       adj, weights, aspects, rng, assign, mins)
            x += w + gut


def _weighted_sizes(total, weights, min_size):
    """Integer sizes proportional to `weights`, summing to `total`, each at
    least `min_size` where `total` allows it."""
    tw = float(sum(weights)) or 1.0
    sizes = [max(1, int(round(total * w / tw))) for w in weights]
    while sum(sizes) < total:
        sizes[sizes.index(min(sizes))] += 1
    while sum(sizes) > total and max(sizes) > 1:
        sizes[sizes.index(max(sizes))] -= 1
    if total >= len(weights) * min_size:
        for _ in range(len(weights) * 2):
            short = next((i for i, s in enumerate(sizes) if s < min_size), None)
            if short is None:
                break
            tall = sizes.index(max(sizes))
            if sizes[tall] <= min_size:
                break
            sizes[tall] -= 1
            sizes[short] += 1
    return sizes


def _sizes_mins(total, weights, mins):
    """Integer sizes proportional to `weights`, summing to `total`, each at
    least its own min where the total allows it."""
    n = len(weights)
    mins = [min(m, max(1, total - n + 1)) for m in mins]
    sizes = _weighted_sizes(total, weights, min(mins) if mins else 1)
    for _ in range(n * 2):
        short = next((i for i in range(n) if sizes[i] < mins[i]), None)
        if short is None:
            break
        tall = max(range(n), key=lambda i: sizes[i] - mins[i])
        if sizes[tall] <= mins[tall]:
            break
        sizes[tall] -= 1
        sizes[short] += 1
    return sizes


# ------------------------------------------------------------------ roads

def _iter_rects(value):
    v = value if isinstance(value, (list, tuple)) else [value]
    return [r for r in v if r is not None]


def _place_roads(plan, zones, grid, rng, pieces=None):
    roads, failures, placed = [], [], []
    by_name = {}
    if pieces:
        for (name, r) in pieces:
            by_name.setdefault(name, []).append(r)
    else:
        by_name = {n: [r] for n, r in zones.items()}
    for r in plan.roads:
        if r.a not in by_name or r.b not in by_name:
            failures.append((f"road {r.a}-{r.b}", "unknown endpoint zone"))
            continue
        segs = None
        for a_rect in by_name[r.a]:
            for b_rect in by_name[r.b]:
                segs = _crossing(a_rect, b_rect, rng, placed)
                if segs is not None:
                    break
            if segs is not None:
                break
        if segs is None:
            segs = _route_through(by_name, r.a, r.b, rng, placed)
        if segs is None:
            starts = by_name[r.a]
            goals = by_name[r.b]
            for a_rect in starts:
                for b_rect in goals:
                    segs = _gutter_route(a_rect, b_rect, by_name, grid, placed)
                    if segs is not None:
                        break
                if segs is not None:
                    break
        if segs is None:
            failures.append((f"road {r.a} to {r.b}", "no corridor between zones"))
            continue
        roads.append(RoadOut(f"{r.a} to {r.b} Road", segs, r.kind, r.a, r.b))
        placed.extend(segs)
    return roads, failures


def _faces(a, b):
    """True when two zone rects touch across a gutter a road crossing can
    fill: facing edges with a shared stretch at least 2 cells long."""
    for (p, q) in ((a, b), (b, a)):
        if 1 <= q.x - p.x1 - 1 <= MAX_GUTTER \
                and min(p.y1, q.y1) - max(p.y, q.y) + 1 >= 2:
            return True
        if 1 <= q.y - p.y1 - 1 <= MAX_GUTTER \
                and min(p.x1, q.x1) - max(p.x, q.x) + 1 >= 2:
            return True
    return False


def _route_through(zones, a, b, rng, placed):
    """A road between two zones that do not face each other, routed through
    the zones between them: a chain of gutter crossings a -> ... -> b, each
    hop avoiding the roads already placed. Returns rect lists or None."""
    if a == b:
        return None
    by_name = zones if all(isinstance(v, list) for v in zones.values()) \
        else {n: [r] for n, r in zones.items()}
    names = sorted(by_name)
    adj = {n: set() for n in names}
    for i, p in enumerate(names):
        for q in names[i + 1:]:
            if any(_faces(pr, qr) for pr in by_name[p] for qr in by_name[q]):
                adj[p].add(q)
                adj[q].add(p)
    usable = {frozenset((p, q)) for p in adj for q in adj[p]}
    while True:
        prev = {a: None}   # shortest hop path over still-usable crossings
        todo = [a]
        while todo:
            n = todo.pop(0)
            if n == b:
                break
            for nb in sorted(adj[n]):
                if nb not in prev and frozenset((n, nb)) in usable:
                    prev[nb] = n
                    todo.append(nb)
        if b not in prev:
            return None
        path = [b]
        while prev[path[-1]] is not None:
            path.append(prev[path[-1]])
        path.reverse()
        segs = []
        for (p, q) in zip(path, path[1:]):
            seg = None
            for pr in by_name[p]:
                for qr in by_name[q]:
                    seg = _crossing(pr, qr, rng, placed)
                    if seg is not None:
                        break
                if seg is not None:
                    break
            if seg is None:   # another road already fills this gutter stretch
                usable.discard(frozenset((p, q)))
                segs = []
                break
            segs.extend(seg)
        if segs:
            return segs


def _crossing(a, b, rng, placed):
    """A road rect filling the gutter between two facing zones."""
    for (p, q) in ((a, b), (b, a)):
        gap = q.x - p.x1 - 1
        if 1 <= gap <= MAX_GUTTER:
            ov0, ov1 = max(p.y, q.y), min(p.y1, q.y1)
            length = min(3, ov1 - ov0 + 1)
            if length >= 2:
                starts = list(range(ov0, ov1 - length + 2))
                rng.shuffle(starts)
                for y0 in starts:
                    r = Rect(p.x1 + 1, y0, gap, length)
                    if all(not r.intersects(o) for o in placed):
                        return [r]
    for (p, q) in ((a, b), (b, a)):
        gap = q.y - p.y1 - 1
        if 1 <= gap <= MAX_GUTTER:
            ov0, ov1 = max(p.x, q.x), min(p.x1, q.x1)
            length = min(3, ov1 - ov0 + 1)
            if length >= 2:
                starts = list(range(ov0, ov1 - length + 2))
                rng.shuffle(starts)
                for x0 in starts:
                    r = Rect(x0, p.y1 + 1, length, gap)
                    if all(not r.intersects(o) for o in placed):
                        return [r]
    return None


def _gutter_route(a, b, zones, grid, placed):
    """Non-facing endpoints: walk the gutter network from a to b. Returns
    1-wide rects or None."""
    W, H = grid
    occupied = set()
    for zr in _iter_rects(list(zones.values())):
        occupied |= zr.cells()
    for r in placed:
        occupied |= r.cells()

    def edge_cells(zr):
        out = set()
        for x in range(zr.x, zr.x1 + 1):
            out |= {(x, zr.y - 1), (x, zr.y1 + 1)}
        for y in range(zr.y, zr.y1 + 1):
            out |= {(zr.x - 1, y), (zr.x1 + 1, y)}
        return {c for c in out if 0 <= c[0] < W and 0 <= c[1] < H and c not in occupied}

    starts, goals = edge_cells(a), edge_cells(b)
    if not starts or not goals:
        return None
    prev = {s: None for s in starts}
    todo = list(starts)
    found = None
    while todo and found is None:
        cur = todo.pop(0)
        if cur in goals:
            found = cur
            break
        x, y = cur
        for nxt in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if not (0 <= nxt[0] < W and 0 <= nxt[1] < H) or nxt in occupied or nxt in prev:
                continue
            prev[nxt] = cur
            todo.append(nxt)
    if found is None:
        return None
    path = set()
    cur = found
    while cur is not None:
        path.add(cur)
        cur = prev[cur]
    return _cells_to_rects(path)


def _cells_to_rects(cells):
    """Partition a cell set into disjoint rects: horizontal runs, merged when
    the run above has the same x range."""
    rows = {}
    for (x, y) in cells:
        rows.setdefault(y, []).append(x)
    runs = []   # [x, y, w, h] mutable
    for y in sorted(rows):
        xs = sorted(rows[y])
        i = 0
        while i < len(xs):
            j = i
            while j + 1 < len(xs) and xs[j + 1] == xs[j] + 1:
                j += 1
            x0, x1 = xs[i], xs[j]
            for run in runs:
                if run[1] + run[3] == y and run[0] == x0 and run[0] + run[2] - 1 == x1:
                    run[3] += 1
                    break
            else:
                runs.append([x0, y, x1 - x0 + 1, 1])
            i = j + 1
    return [Rect(r[0], r[1], r[2], r[3]) for r in sorted(runs, key=lambda r: (r[1], r[0]))]


def _road_mouths(pieces, roads):
    """For every road cell touching a zone piece edge, the zone cell behind
    it must stay clear of props so the road actually leads into the zone."""
    out = {}
    piece_list = list(pieces)
    for road in roads:
        for cell in road.cells():
            x, y = cell
            for nxt in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                for name, zr in piece_list:
                    if zr.contains_cell(nxt):
                        out.setdefault(name, set()).add(nxt)
    return out


def _default_ground(plan, weights):
    areas = {}
    for z in plan.zones:
        areas[z.ground] = areas.get(z.ground, 0) + weights[z.name]
    if not areas:
        return ("grass", "grass")
    ground = max(sorted(areas), key=lambda g: areas[g])
    return GROUND_TEXTURES.get(ground, ("grass", "grass"))
