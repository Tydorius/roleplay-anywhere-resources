"""The room composer: turns a recipe's groups into fixed rooms (design
section 5). The anchor goes down first (its back fixes the wall it stands
against); every later group is placed straight along X or Y from one placed
group — its parent — at the clearance gap, sliding along the parent so their
spans overlap (never off a diagonal from it). A wall-bound group landing on
the bounds edge fixes that edge as a wall and nothing later may cross it.
The bounding box of the placed groups is the room; a side no group fixed
gets 0 or 1 slack rows, both as candidates. The box never leaves the
family's aspect cap (MAX_ASPECT, looser for hall-like families), a placement
never seals a placed piece off its use sides, and at roomy and grand the
score pays for every wall the wall-bound groups spread over, so large rooms
fill out instead of stringing along one line. A grand private room
(PRIVATE_FAMILIES) keeps the roomy gap and spends the space on its luxury
pool instead: the pool's groups join the recipe's optionals at grand, each
inside the size bands the pool gives it, one group of each luxury kind at
most (LUXURY_LIMITS, decor two groups and three pieces) and never doubling
a role the recipe itself already places (EXCLUSIVE_ROLES: no second desk,
bed or fire). A grand private room also stays inside max_area, the grand
area cap its caller derives from the roomy sibling (GRAND_AREA_RATIO), so
optional groups join only while the cap holds. A small beam search keeps
the best partial rooms; a candidate counts only when fixed_rooms.check
passes.

  compose(recipe, groups, clearance, style, seed, ...) -> (rooms, reason)

``rooms`` are fixed-room dicts, best first; ``reason`` is None unless the
list is empty, then a plain sentence why. Pure functions throughout; the
only randomness is random.Random(seed), which breaks ties.
"""
import copy
import random

from . import fixed_rooms
from .fixed_rooms import CLEARANCES, STYLES, SLEEP_COUPLE_ROLE, \
    SLEEP_SINGLE_ROLES, TURN
from .library import SIDES
from .room_groups import luxury_kinds

BEAM_WIDTH = 24          # partial rooms kept per placement step
BEAM_SHAPE_KEEP = 3      # states kept per distinct shape (groups x box)
# when nothing comes out at the usual width, one wider pass before saying
# no: a many-group recipe at tight can hold a legal room the narrow beam
# starves out, and a recipe that fails both passes is honestly impossible
BEAM_RETRY = (96, 6)     # (width, per-shape keep) of that second pass
MAX_CANDIDATES = 6       # rooms returned, best first
OPEN_BASES = 8           # flush rooms the open style grows variants from
MAX_ROOM_SIDE = 30       # give up on runaway placements
GAP = {"tight": 1, "roomy": 2, "grand": 3}
SLACK = (0, 1)           # extra rows on a side no wall-bound group fixed
OPEN_GROWTH = (0, 1, 2)  # cells per axis the open style may add
MIN_FILLER = 2           # the open middle, at least 2x2
# the filler (a rug, a table in the open middle) at most this big, long
# side first, either orientation, per clearance
FILLER_MAX = {"tight": (3, 3), "roomy": (4, 3), "grand": (5, 4)}
FILLER_ASPECT = 2        # a filler's long side at most twice its short
MAX_ASPECT = 2.0         # long side never above this multiple of the short
HALL_ASPECT = 2.5        # hall-like families read long, so they get more
HALL_FAMILIES = ("chapel", "common_room", "dining", "hall", "taproom")
# one household's or one person's room: a grand private room keeps the roomy
# gap and spends the space on furniture (a pool group) instead of floor
PRIVATE_FAMILIES = ("bedroom", "bedroom.master", "washroom", "privy", "bath",
                    "closet", "cell", "hut", "office")
# a grand room is at least 19 cells: more than a lone anchor group and its
# slack rows can ever fill (a bed group tops out at 6x3 = 18), so anything
# kept at grand carries furniture beyond one group; the dead-floor rule,
# not this floor, rejects sparse grand rooms
GRAND_FLOOR = 19
WEALTH = {"tight": ["poor", "modest"], "roomy": ["wealthy"], "grand": ["elite"]}
# one of each luxury kind per grand private room: how many pool groups of
# each kind a room may take (decor two groups), and decor groups together
# hold at most this many pieces
LUXURY_LIMITS = {"seating": 1, "hearth": 1, "work": 1, "display": 1,
                 "books": 1, "storage": 1, "decor": 2}
LUXURY_DECOR_PIECES = 3
# a pool group never doubles one of these roles when the recipe itself
# already places it: no second desk, bed or fire in one room. Heat and
# hearth are one fire (a recipe with a stove takes no fireplace group), and
# sleep and sleep.couple one bed.
EXCLUSIVE_ROLES = ("desk", "sleep", "sleep.couple", "heat", "hearth")
_EXCLUSIVE_FAMILY = {"desk": "desk", "sleep": "sleep",
                     "sleep.couple": "sleep", "heat": "fire",
                     "hearth": "fire"}
# a grand private room's area stays at most this multiple of its roomy
# sibling's (same recipe and style), rounded up by the caller
GRAND_AREA_RATIO = 1.5
# score weights, lower is better: area dominates, aspect and door sides
# refine, symmetry earns its bonus where flagged, and at roomy and grand
# every wall the wall-bound groups fill earns the spread bonus
SCORE_AREA = 1.0
SCORE_ASPECT = 5.0
SCORE_DOOR_SIDE = 3.0
SCORE_SYMMETRY = 5.0
SCORE_WALLS_USED = 6.0
SCORE_OPEN_DEAD = 3.0   # the open beam pays this per dead cell in the box


def aspect_cap(family):
    """The most the long side may exceed the short side at any clearance or
    style: hall-like rooms (a nave, a refectory, a taproom) read long, so
    their cap is looser; everything else stays near square."""
    f = family or ""
    return HALL_ASPECT if f in HALL_FAMILIES or "hall" in f else MAX_ASPECT


def gap_for(family, clearance):
    """The gap in clear cells a family's rooms keep between groups at a
    clearance, from GAP — except that a grand private room stays roomy (a
    private room shows its wealth in furniture, not empty floor). Unknown
    clearances are tight, like fixed_rooms' table."""
    if clearance == "grand" and (family or "") in PRIVATE_FAMILIES:
        return GAP["roomy"]
    return GAP.get(clearance, GAP["tight"])


def compose(recipe, groups, clearance, style, seed, size_band=None,
            symmetric=False, sleepers=None, max_area=None):
    """Compose ``recipe`` (a recipe dict from room_groups) at ``clearance``
    (tight/roomy/grand) in ``style`` (flush/open) into fixed-room candidates,
    best first and each passing fixed_rooms.check. Returns (rooms, reason):
    reason is a plain sentence when no room could be made. ``sleepers`` is
    (singles, couples), defaulting to the family's usual occupancy. With
    ``size_band`` only rooms inside that band come back — a family's own band
    by that name when it has one (its aspect range, when the band has one,
    may stretch past the family's aspect cap), else a shared band. A band no
    room of the recipe's furniture can reach produces no room: the room is
    never padded to reach it. ``symmetric`` places
    the anchor on the centre line and every group off it mirrored across it.
    ``max_area`` caps the room's area: a grand private room stays within
    GRAND_AREA_RATIO of its roomy sibling, and optional and pool groups join
    only while that holds (the caller works the cap out; None is no cap).
    Deterministic per seed: the seed breaks ties and nothing else."""
    if clearance not in GAP:
        return ([], f"unknown clearance {clearance!r}")
    if style not in STYLES:
        return ([], f"unknown style {style!r}")
    gdefs = (groups or {}).get("groups") or {}
    entries = recipe.get("groups") or []
    family = recipe.get("family")
    if not family:
        return ([], "recipe has no family")
    for e in entries:
        gid = e.get("group") if isinstance(e, dict) else None
        if gid not in gdefs:
            return ([], f"recipe names no group {gid!r}")
    if sleepers is None:
        sleepers = _default_sleepers(recipe, gdefs)
    sleepers = (sleepers[0], sleepers[1])
    own = next((b for b in fixed_rooms.family_bands(family)
                if b["name"] == size_band), None) if size_band else None
    band = (own["cells"] if own else fixed_rooms.BANDS.get(size_band)) \
        if size_band else None
    if size_band and band is None:
        return ([], f"unknown size band {size_band!r}")
    cap = aspect_cap(family)
    if own is not None and own["aspect"] is not None:
        # a band's own aspect range may stretch past the family cap; free
        # composition (no size_band) stays at the family cap
        cap = max(cap, own["aspect"][1])
    layout = recipe.get("layout") or "hand"
    ctx = {"gap": gap_for(family, clearance), "band": band,
           "size_band": size_band,
           "symmetric": symmetric,
           "parity": 0, "clearance": clearance, "style": style,
           "family": family, "layout": layout, "gdefs": gdefs,
           "cap": cap,
           "floor": (GRAND_FLOOR if clearance == "grand" and not size_band
                     else 0),
           "lux_bands": {},
           "max_area": max_area,
           "fails": {},
           "rng": random.Random(seed), "sleepers": sleepers}

    # the anchor: one group, placed first, rotation 0 (north-facing); the
    # finished room is stored in that one orientation
    anchor = next((e for e in entries
                   if isinstance(e, dict) and e.get("kind") == "anchor"), None)
    if anchor is None:
        return ([], "recipe has no anchor group")
    form = _forms(gdefs[anchor["group"]])[0]
    mn, mx = _resolve_count(anchor.get("count"), sleepers)
    if mx < 1:
        return ([], f"the anchor {anchor['group']} resolves to zero copies "
                    f"with sleepers {sleepers}")
    if symmetric and not _self_mirrored(form):
        return ([], f"anchor group {anchor['group']} is not mirror-symmetric")
    ax = -(form["w"] // 2) if symmetric else 0
    ctx["parity"] = form["w"] % 2
    state = _anchor_state(form, ax, ctx)
    if state is None:
        return ([], f"the anchor alone does not fit size band {size_band}")
    states = [state]
    # an anchor with optional pieces also starts bare: the full form wins on
    # area wherever it composes, and the bare one is what a tight room of a
    # sparse recipe is made of (a symmetric room keeps the full form, whose
    # mirror the parity was computed for)
    if not symmetric:
        minimal = _minimal_form(form)
        if minimal is not None:
            bare = _anchor_state(minimal, 0, ctx)
            if bare is not None:
                states.append(bare)

    units = []
    if mx > 1:
        units.append(("repeat", anchor["group"], max(0, mn - 1), mx - 1))
    for e in entries:
        if not isinstance(e, dict) or e.get("kind") == "anchor":
            continue
        mn, mx = _resolve_count(e.get("count"), sleepers)
        kind = {"required": "one", "optional": "opt",
                "repeatable": "repeat"}[e.get("kind")]
        units.append((kind, e["group"], mn, mx))
    units += _luxury_units(recipe, groups, family, clearance, ctx)

    def _pass(width, keep):
        """One run of the units over the starting states at a beam width."""
        ctx["beam_width"], ctx["beam_keep"] = width, keep
        run = list(states)
        for kind, gid, mn, mx in units:
            run = _unit(run, kind, gid, mn, mx, ctx)
            if not run:
                note = f" inside size band {size_band}" if size_band else ""
                if kind == "one":
                    return ([], f"cannot place required group {gid}{note}")
                if kind == "repeat":
                    return ([], f"cannot place {mn} copies of {gid}{note}")
                return ([], f"cannot place {gid}{note}")

        cands = []
        for st in run:
            cands += _finish(st, ctx)
        cands = _dedup_cands(cands)
        if ctx["floor"]:
            floored = [c for c in cands
                       if c[2]["size"][0] * c[2]["size"][1] >= ctx["floor"]]
            if not floored and cands:
                # the recipe composes, but only rooms too small to be
                # grand: grown to a grand size they would be dead floor
                # end to end
                return ([], f"{clearance}: too little furniture (dead floor)")
            cands = floored
        if not cands:
            fails = ctx["fails"]
            if fails.get("dead"):
                return ([], f"{clearance}: too little furniture (dead floor)")
            if fails.get("aspect"):
                return ([], f"{clearance}: every candidate breaks the "
                            f"aspect cap")
            if fails.get("area"):
                return ([], f"{clearance}: no room fits inside the area cap "
                            f"of {ctx['max_area']} cells")
            if fails.get("luxband"):
                return ([], f"{clearance}: no room fits its luxury groups' "
                            f"size bands")
            if size_band:
                return ([], f"no room fits size band {size_band}")
            return ([], "no candidate passes the room checks")
        cands.sort(key=lambda c: (c[0], c[1]))
        if style == "open":
            # the open style grows only the top bases, and a base whose
            # walls are already lined is the one that can grow legally
            # (every wall line keeps a piece except the filler's buffer),
            # so they come first
            cands.sort(key=lambda c: (c[0] - _covered(c[2]) * SCORE_WALLS_USED,
                                      c[1]))
            opened = _open(cands[:OPEN_BASES], ctx)
            if not opened:
                hi, lo = FILLER_MAX[clearance]
                return ([], f"no open variant keeps a centred {MIN_FILLER}x"
                            f"{MIN_FILLER} to {hi}x{lo} filler clear of "
                            f"every wall with its wall groups on the walls")
            opened.sort(key=lambda c: (c[0], c[1]))
            cands = opened
        rooms = _finalize([c[2] for c in cands[:MAX_CANDIDATES]], ctx)
        return (rooms, None)

    rooms, reason = _pass(BEAM_WIDTH, BEAM_SHAPE_KEEP)
    if not rooms:
        wider, wider_reason = _pass(*BEAM_RETRY)
        if wider:
            return (wider, None)
        reason = wider_reason or reason
    return (rooms, reason)


# ------------------------------------------------------ recipes and counting

def _resolve_count(count, sleepers):
    """A recipe entry's count as (min, max) copies: an int, a [min, max]
    pair, or "singles"/"couples" filled from the sleepers."""
    if count == "singles":
        return (sleepers[0], sleepers[0])
    if count == "couples":
        return (sleepers[1], sleepers[1])
    if isinstance(count, bool):
        return (1, 1)
    if isinstance(count, int):
        return (max(0, count), max(0, count))
    if (isinstance(count, list) and len(count) == 2
            and all(isinstance(x, int) and not isinstance(x, bool)
                    for x in count)):
        return (max(0, count[0]), max(0, count[1]))
    return (1, 1)


def _default_sleepers(recipe, gdefs):
    """The family's usual occupancy: one single in a bedroom, one couple in
    a master bedroom, the recipe's own minimum count of sleep pieces
    otherwise."""
    family = recipe.get("family")
    if family == "bedroom":
        return (1, 0)
    if family == "bedroom.master":
        return (0, 1)
    singles = couples = 0
    for e in recipe.get("groups") or []:
        g = gdefs.get(e.get("group")) or {}
        roles = [p.get("role") for p in g.get("pieces") or []
                 if isinstance(p, dict)]
        mn, _ = _resolve_count(e.get("count"), (1, 1))
        if any(r in SLEEP_SINGLE_ROLES for r in roles):
            singles += mn
        if SLEEP_COUPLE_ROLE in roles:
            couples += mn
    return (singles, couples)


def _luxury_units(recipe, groups, family, clearance, ctx):
    """The family's luxury pool as pool units, grand private rooms only:
    each pool entry whose size bands meet the recipe's own (a large-only
    fireplace never joins a small recipe) becomes one fill-only group after
    the recipe's own, in pool order — that order is the preference, the
    fireplace and one seating area before decor. A group carrying one of
    EXCLUSIVE_ROLES that the recipe itself already places never joins (no
    second desk, bed or fire). Each entry's bands ride along in ctx and gate
    the finished room's band in _build_room."""
    if clearance != "grand" or family not in PRIVATE_FAMILIES:
        return []
    pools = (groups or {}).get("pools") or {}
    recipe_bands = recipe.get("sizeBands")
    taken = set()
    for e in recipe.get("groups") or []:
        for p in (ctx["gdefs"].get(e.get("group")) or {}).get("pieces") or []:
            if isinstance(p, dict):
                taken.add(_EXCLUSIVE_FAMILY.get(p.get("role")))
    taken.discard(None)
    units = []
    for e in pools.get(family) or []:
        gid = e.get("group") if isinstance(e, dict) else None
        if gid not in ctx["gdefs"] or gid in ctx["lux_bands"]:
            continue
        pieces = ctx["gdefs"][gid].get("pieces") or []
        if any(_EXCLUSIVE_FAMILY.get(p.get("role")) in taken
               for p in pieces if isinstance(p, dict)):
            continue
        bands = e.get("bands") or []
        if recipe_bands and not set(bands) & set(recipe_bands):
            continue
        ctx["lux_bands"][gid] = bands
        units.append(("lux", gid, 1, 1))
    return units


def _luxury_room_for(state, gid, ctx):
    """Whether one more luxury group ``gid`` fits the room's luxury limits:
    at most LUXURY_LIMITS groups of each of its kinds so far, and decor
    groups together at most LUXURY_DECOR_PIECES pieces."""
    gdef = ctx["gdefs"][gid]
    kinds = luxury_kinds(gdef)
    by, decor_pieces = {}, 0
    for g in state["placed"]:
        gk = luxury_kinds(ctx["gdefs"].get(g["gid"]) or {})
        if not gk:
            continue
        for k in gk:
            by[k] = by.get(k, 0) + 1
        if "decor" in gk:
            decor_pieces += len(g["pieces"])
    if any(by.get(k, 0) + 1 > LUXURY_LIMITS.get(k, 0) for k in kinds):
        return False
    if "decor" in kinds \
            and decor_pieces + len(gdef.get("pieces") or []) \
            > LUXURY_DECOR_PIECES:
        return False
    return True


def _inside_lux_bands(gids, band, ctx):
    """A room keeps its luxury pool groups only inside the size bands the
    pool gave them (growth can push a room past the band a group was placed
    in)."""
    for gid in gids:
        eb = ctx["lux_bands"].get(gid)
        if eb and band not in eb:
            return False
    return True


# ---------------------------------------------------------- turned group forms

def _piece_sig(pieces):
    return tuple(sorted((p["role"], p["at"][0], p["at"][1],
                         p["size"][0], p["size"][1], p["back"],
                         p["optional"]) for p in pieces))


def _turned(gdef, rot):
    """The group's pieces turned ``rot`` quarter turns clockwise, in a fresh
    north-facing box."""
    pieces = []
    for p in gdef.get("pieces") or []:
        x, y = p.get("at") or [0, 0]
        w, h = p.get("size") or [0, 0]
        pieces.append({"role": p.get("role"), "size": [w, h], "at": [x, y],
                       "back": p.get("back"),
                       "optional": bool(p.get("optional"))})
    W = max(p["at"][0] + p["size"][0] for p in pieces)
    H = max(p["at"][1] + p["size"][1] for p in pieces)
    for _ in range(rot % 4):
        for p in pieces:
            x, y = p["at"]
            w, h = p["size"]
            p["at"] = [H - y - h, x]
            p["size"] = [h, w]
            if p["back"] in TURN:
                p["back"] = TURN[p["back"]]
        W, H = H, W
    return pieces, W, H


def _forms(gdef):
    """The group's distinct turned forms (many small groups are their own
    rotation), each {gid, pieces, w, h, back}."""
    out = []
    seen = set()
    for rot in range(4):
        pieces, W, H = _turned(gdef, rot)
        sig = _piece_sig(pieces)
        if (W, H, sig) in seen:
            continue
        seen.add((W, H, sig))
        back = next((p["back"] for p in pieces if p["back"] in SIDES), None)
        out.append({"gid": gdef["id"], "pieces": pieces, "w": W, "h": H,
                    "back": back})
    return out


def _minimal_form(form):
    """The form holding only its required pieces, in the same box it fills
    (a bed group's optional bed sides and chest stay off). An anchor's
    optional pieces can make a tight room impossible — they wall the corners
    off — and the room goes on without them the same way it goes on without
    an optional group; None when every piece is required."""
    pieces = [p for p in form["pieces"] if not p.get("optional")]
    if len(pieces) == len(form["pieces"]):
        return None
    return {"gid": form["gid"], "pieces": pieces,
            "w": max(p["at"][0] + p["size"][0] for p in pieces),
            "h": max(p["at"][1] + p["size"][1] for p in pieces),
            "back": form["back"]}


def _mirror_form(form):
    """The form mirrored across the vertical axis of its own box."""
    w = form["w"]
    pieces = []
    for p in form["pieces"]:
        x, y = p["at"]
        pw, ph = p["size"]
        back = {"east": "west", "west": "east"}.get(p["back"], p["back"])
        pieces.append({"role": p["role"], "size": [pw, ph],
                       "at": [w - x - pw, y], "back": back,
                       "optional": p["optional"]})
    back = {"east": "west", "west": "east"}.get(form["back"], form["back"])
    return {"gid": form["gid"], "pieces": pieces, "w": w, "h": form["h"],
            "back": back}


def _self_mirrored(form):
    return _piece_sig(_mirror_form(form)["pieces"]) == _piece_sig(form["pieces"])


# ------------------------------------------------------------- search states

def _lines_covered(placed, minx, miny, maxx, maxy):
    """How many of the box's four edge lines carry a piece cell (0-4). The
    open style needs its walls lined — every wall line holds a piece except
    the one the filler's buffer keeps clear — and no placement rule forces
    that, so the open search pays for it."""
    covered = set()
    for g in placed:
        for p in g["pieces"]:
            x, y, pw, ph = p["at"][0], p["at"][1], p["size"][0], p["size"][1]
            if y == miny:
                covered.add("north")
            if y + ph == maxy + 1:
                covered.add("south")
            if x == minx:
                covered.add("west")
            if x + pw == maxx + 1:
                covered.add("east")
    return len(covered)


def _covered(room):
    """How many of the room's four wall lines carry a piece cell (0-4)."""
    w, h = room["size"]
    return _lines_covered([{"pieces": room["pieces"]}], 0, 0, w - 1, h - 1)


def _dead_in_box(placed, minx, miny, maxx, maxy, gap):
    """How many cells of the box lie more than ``gap`` (Chebyshev) from every
    piece — the same dead floor the checker flags on a room. An open style's
    base must be alive: a base with dead corners only grows into open rooms
    the checker rejects, so the open search pays for them up front."""
    dead = 0
    for cx in range(minx, maxx + 1):
        for cy in range(miny, maxy + 1):
            near = False
            for g in placed:
                for p in g["pieces"]:
                    x, y, pw, ph = p["at"][0], p["at"][1], p["size"][0], p["size"][1]
                    if max(x - cx, 0, cx - (x + pw - 1),
                           y - cy, 0, cy - (y + ph - 1)) <= gap:
                        near = True
                        break
                if near:
                    break
            if not near:
                dead += 1
    return dead


def _box_score(placed, minx, miny, maxx, maxy, walls, ctx):
    """The beam's partial score: area with the aspect penalty, a heavy
    handicap for boxes past the family's aspect cap (a later group can grow
    the short side and bring such a box back into shape, so it stays in the
    running, but far behind anything already within the cap), at roomy and
    grand a bonus for every wall a wall-bound group has already fixed
    (capped at four, one per wall) so the search spreads groups around the
    room instead of stringing them along one line, and for the open style a
    bonus for every edge line already lined with a piece (an open room
    tolerates no empty wall line beyond the filler's buffer) and a cost for
    every dead cell, the two together keeping the states that can grow into
    legal open rooms alive in the beam instead of losing tie-breaks to
    look-alikes the checker would reject."""
    w, h = maxx - minx + 1, maxy - miny + 1
    aspect = max(w, h) / min(w, h)
    s = w * h * SCORE_AREA + max(0.0, aspect - 2.0) * SCORE_ASPECT
    if aspect > ctx["cap"]:
        s += (aspect - ctx["cap"]) * SCORE_ASPECT * 10 + 10 * SCORE_ASPECT
    if ctx["gap"] >= 2:
        s -= min(sum(1 for c in walls.values() if c is not None), 4) \
            * SCORE_WALLS_USED
    if ctx["style"] == "open":
        s -= _lines_covered(placed, minx, miny, maxx, maxy) * SCORE_WALLS_USED
        s += _dead_in_box(placed, minx, miny, maxx, maxy,
                          ctx["gap"]) * SCORE_OPEN_DEAD
    return s


def _state(placed, minx, miny, maxx, maxy, walls, ctx):
    return {"placed": placed, "minx": minx, "miny": miny,
            "maxx": maxx, "maxy": maxy, "walls": walls,
            "score": _box_score(placed, minx, miny, maxx, maxy, walls, ctx),
            "tb": ctx["rng"].random(),
            "key": tuple(sorted((g["gid"], g["x"], g["y"], g["w"], g["h"],
                                 tuple(sorted((p["role"], p["at"][0], p["at"][1],
                                              p["size"][0], p["size"][1], p["back"])
                                             for p in g["pieces"])))
                                for g in placed))}


def _anchor_state(form, ax, ctx):
    walls = {s: None for s in SIDES}
    if form["back"]:
        walls[form["back"]] = {"north": 0, "south": form["h"] - 1,
                               "west": ax, "east": ax + form["w"] - 1}[form["back"]]
    minx, miny, maxx, maxy = ax, 0, ax + form["w"] - 1, form["h"] - 1
    if ctx["band"] and (maxx - minx + 1) * (maxy - miny + 1) > ctx["band"][1]:
        return None
    placed = ({"gid": form["gid"], "x": ax, "y": 0, "w": form["w"],
               "h": form["h"], "back": form["back"],
               "pieces": [dict(p, at=[p["at"][0] + ax, p["at"][1]])
                          for p in form["pieces"]]},)
    return _state(placed, minx, miny, maxx, maxy, walls, ctx)


def _beyond_walls(walls, x, y):
    """The cell lies past a wall some group fixed, so no room built on these
    walls can ever hold it."""
    return ((walls["north"] is not None and y < walls["north"])
            or (walls["south"] is not None and y > walls["south"])
            or (walls["west"] is not None and x < walls["west"])
            or (walls["east"] is not None and x > walls["east"]))


def _boxes_a_piece(placed, walls):
    """True when some placed piece can never be used again: every cell on
    its use sides is under a piece or past a fixed wall. A cell inside the
    bounds that is free stays free (later groups keep the clearance gap),
    and a free cell outside the bounds may still join the room when a later
    group grows the box — unless a fixed wall rules it out, which is what
    this catches (the bedside sealed in by its own bed, a chest and the
    walls the search fixed around them)."""
    occupied = set()
    for g in placed:
        for p in g["pieces"]:
            x, y, pw, ph = p["at"][0], p["at"][1], p["size"][0], p["size"][1]
            occupied |= {(cx, cy) for cx in range(x, x + pw)
                         for cy in range(y, y + ph)}
    for g in placed:
        for p in g["pieces"]:
            sides = fixed_rooms.use_sides(p, g["pieces"])
            if not sides:
                continue
            x, y, pw, ph = p["at"][0], p["at"][1], p["size"][0], p["size"][1]
            cells = []
            for s in sides:
                if s == "north":
                    cells += [(cx, y - 1) for cx in range(x, x + pw)]
                elif s == "south":
                    cells += [(cx, y + ph) for cx in range(x, x + pw)]
                elif s == "west":
                    cells += [(x - 1, cy) for cy in range(y, y + ph)]
                else:
                    cells += [(x + pw, cy) for cy in range(y, y + ph)]
            if not any(c not in occupied and not _beyond_walls(walls, *c)
                       for c in cells):
                return True
    return False


def _try_place(state, form, x, y, ctx, allow_growth=True):
    """One group form at (x, y): a clearance gap to every placed group, no
    crossing of a fixed wall, a wall-bound form flush on the edge it fixes,
    and no placement sealing a placed piece off its use sides. The box may
    pass the family's aspect cap mid-search (a later group can grow the
    short side); the cap is hard on the finished room. None when any rule
    fails."""
    w, h = form["w"], form["h"]
    minx, miny = min(state["minx"], x), min(state["miny"], y)
    maxx, maxy = max(state["maxx"], x + w - 1), max(state["maxy"], y + h - 1)
    if not allow_growth and (minx, miny, maxx, maxy) != (
            state["minx"], state["miny"], state["maxx"], state["maxy"]):
        return None
    for side, coord in state["walls"].items():
        if coord is None:
            continue
        if side == "north" and miny < coord:
            return None
        if side == "south" and maxy > coord:
            return None
        if side == "west" and minx < coord:
            return None
        if side == "east" and maxx > coord:
            return None
    gap = ctx["gap"]
    for g in state["placed"]:
        sx = max(x - (g["x"] + g["w"]), g["x"] - (x + w))
        sy = max(y - (g["y"] + g["h"]), g["y"] - (y + h))
        if max(sx, sy) < gap:
            return None
    walls = dict(state["walls"])
    if form["back"]:
        b = form["back"]
        bcoord = {"north": y, "south": y + h - 1,
                  "west": x, "east": x + w - 1}[b]
        if walls[b] is None:
            edge = {"north": miny, "south": maxy,
                    "west": minx, "east": maxx}[b]
            if bcoord != edge:
                return None
            walls[b] = bcoord
        elif walls[b] != bcoord:
            return None
    if maxx - minx + 1 > MAX_ROOM_SIDE or maxy - miny + 1 > MAX_ROOM_SIDE:
        return None
    if ctx["band"] and (maxx - minx + 1) * (maxy - miny + 1) > ctx["band"][1]:
        return None
    if ctx.get("max_area") is not None \
            and (maxx - minx + 1) * (maxy - miny + 1) > ctx["max_area"]:
        return None
    placed = state["placed"] + ({"gid": form["gid"], "x": x, "y": y, "w": w,
                                 "h": h, "back": form["back"],
                                 "pieces": [dict(p, at=[p["at"][0] + x, p["at"][1] + y])
                                            for p in form["pieces"]]},)
    if walls != state["walls"] and _boxes_a_piece(placed, walls):
        return None
    return _state(placed, minx, miny, maxx, maxy, walls, ctx)


def _mirror_x(x, w, parity):
    return -x - w + (1 if parity else 0)


def _place(state, form, x, y, ctx, allow_growth=True):
    """Place one form; in a symmetric room its mirror goes down in the same
    step (a self-mirrored form on the centre line goes down once)."""
    s2 = _try_place(state, form, x, y, ctx, allow_growth)
    if s2 is None or not ctx["symmetric"]:
        return s2
    mx = _mirror_x(x, form["w"], ctx["parity"])
    if (mx, y) == (x, y) and _self_mirrored(form):
        return s2
    return _try_place(s2, _mirror_form(form), mx, y, ctx, allow_growth)


def _placements(state, form, ctx, allow_growth=True):
    """Every (x, y) a form can go: straight north/east/south/west of every
    placed group at the gap, sliding across the parent's span so the two
    overlap along the line between them."""
    gap = ctx["gap"]
    out = []
    for g in state["placed"]:
        spans = {
            "north": (range(g["x"] - form["w"] + 1, g["x"] + g["w"]),
                      [g["y"] - gap - form["h"]]),
            "south": (range(g["x"] - form["w"] + 1, g["x"] + g["w"]),
                      [g["y"] + g["h"] + gap]),
            "west": ([g["x"] - gap - form["w"]],
                     range(g["y"] - form["h"] + 1, g["y"] + g["h"])),
            "east": ([g["x"] + g["w"] + gap],
                     range(g["y"] - form["h"] + 1, g["y"] + g["h"])),
        }
        for xs, ys in spans.values():
            for x in xs:
                for y in ys:
                    s2 = _place(state, form, x, y, ctx, allow_growth)
                    if s2 is not None:
                        out.append(s2)
    return out


def _trim(states, ctx):
    """Dedup by what stands where, then keep the best partial rooms — the
    champion of every distinct shape first (how many groups stand, in what
    box), then each shape's runner-up, and so on. A plain best-first beam
    floods with variants of one compact shape and starves every other, so a
    shape that is a dead end two groups later (a two-band box that can never
    take the next piece without leaving the aspect cap) takes the whole beam
    down with it; round-robin keeps the alternatives alive. The width and
    per-shape keep come from the pass (ctx), the retry pass running wider."""
    seen = set()
    stage = []
    for st in states:
        if st["key"] in seen:
            continue
        seen.add(st["key"])
        stage.append(st)
    stage.sort(key=lambda s: (s["score"], s["tb"]))
    shapes = {}
    for st in stage:
        shape = (len(st["placed"]), st["maxx"] - st["minx"] + 1,
                 st["maxy"] - st["miny"] + 1)
        shapes.setdefault(shape, []).append(st)
    width = ctx.get("beam_width", BEAM_WIDTH)
    keep = ctx.get("beam_keep", BEAM_SHAPE_KEEP)
    out = []
    for layer in range(keep):
        for shape in shapes:
            sts = shapes[shape]
            if layer < len(sts):
                out.append(sts[layer])
                if len(out) == width:
                    return out
    return out


def _unit(states, kind, gid, mn, mx, ctx):
    """Run one recipe unit over the beam: a required group (all states must
    place it), an optional one (added while a placement exists — never
    growing the room unless a size band was given, whose slack they fill),
    a pool group (like an optional one but never growing the room: the
    luxury pool fills the room the recipe's own groups made, it does not
    balloon it, and a state already at a kind's limit in LUXURY_LIMITS
    takes no group of that kind), or a repeatable one (between mn and mx
    copies)."""
    forms = _forms(ctx["gdefs"][gid])
    if kind in ("opt", "lux") and mx < 1:
        return states
    if kind == "repeat" and mx < 1:
        return states if mn < 1 else []
    if kind == "one":
        nxt = []
        for st in states:
            for form in forms:
                nxt += _placements(st, form, ctx)
        return _trim(nxt, ctx)
    if kind in ("opt", "lux"):
        # optional groups may grow the room when a size band was given
        # (whose slack they fill) and at roomy and grand, where the extra
        # furniture is what fills the bigger room — but there they only
        # ever fill: a placement that pushes the box past the aspect cap
        # is left unmade and the room goes on without the group
        allow = kind == "opt" and (ctx["band"] is not None or ctx["gap"] >= 2)
        nxt = []
        for st in states:
            if kind == "lux" and not _luxury_room_for(st, gid, ctx):
                continue
            for form in forms:
                nxt += _placements(st, form, ctx, allow_growth=allow)
        if allow and ctx["band"] is None:
            nxt = [s for s in nxt
                   if max(s["maxx"] - s["minx"] + 1, s["maxy"] - s["miny"] + 1)
                   <= ctx["cap"]
                   * min(s["maxx"] - s["minx"] + 1, s["maxy"] - s["miny"] + 1)]
        if allow and ctx["band"] is not None:
            # a band was asked for: the group fills slack, it never pads the
            # room up to the band — so the states without it stay in the beam
            # (a placement at the gap would balloon a small room past the
            # band's reach, and the bare room is the band's best fit)
            nxt = nxt + list(states)
        return _trim(nxt, ctx) if nxt else states
    # repeatable: copies form rows along walls and grids in the open, each
    # placed from any parent at the gap; collect every state from mn copies
    # up (with mn at zero the states before any copy count too — a recipe
    # asking for one or two copies may rightly stop at one)
    active = states
    done = list(states) if mn <= 0 else []
    for i in range(mx):
        nxt = []
        for st in active:
            for form in forms:
                nxt += _placements(st, form, ctx)
        if not nxt:
            break
        active = _trim(nxt, ctx)
        if i + 1 >= mn:
            done += active
    return _trim(done, ctx) if done else []


# ----------------------------------------------------------------- finishing

def _slack_variants(state, ctx):
    """The room box: the bounds, plus 0 or 1 slack rows on each side no
    wall-bound group fixed (a symmetric room grows its west/east pair
    together, or its mirror would break)."""
    walls = state["walls"]
    if ctx["symmetric"]:
        xpair = [(0, 0)]
        if walls["west"] is None and walls["east"] is None:
            xpair = [(0, 0), (1, 1)]
        norths = SLACK if walls["north"] is None else (0,)
        souths = SLACK if walls["south"] is None else (0,)
        for sw, se in xpair:
            for sn in norths:
                for ss in souths:
                    yield (sw, se, sn, ss)
        return
    wests = SLACK if walls["west"] is None else (0,)
    easts = SLACK if walls["east"] is None else (0,)
    norths = SLACK if walls["north"] is None else (0,)
    souths = SLACK if walls["south"] is None else (0,)
    for sw in wests:
        for se in easts:
            for sn in norths:
                for ss in souths:
                    yield (sw, se, sn, ss)


def _build_room(state, sw, se, sn, ss, ctx):
    """The room dict a finished state boxes into, doors derived from its
    free edge cells (or None when the box leaves the size band or the
    aspect cap)."""
    x0 = state["minx"] - sw
    y0 = state["miny"] - sn
    w = state["maxx"] - state["minx"] + 1 + sw + se
    h = state["maxy"] - state["miny"] + 1 + sn + ss
    if max(w, h) > ctx["cap"] * min(w, h):
        ctx["fails"]["aspect"] = ctx["fails"].get("aspect", 0) + 1
        return None
    if ctx["band"] and not ctx["band"][0] <= w * h <= ctx["band"][1]:
        ctx["fails"]["band"] = ctx["fails"].get("band", 0) + 1
        return None
    if ctx.get("max_area") is not None and w * h > ctx["max_area"]:
        ctx["fails"]["area"] = ctx["fails"].get("area", 0) + 1
        return None
    band = (fixed_rooms.band_for(ctx["family"], w, h)
            if fixed_rooms.family_bands(ctx["family"])
            else fixed_rooms.band_for_area(w * h))
    if not _inside_lux_bands((g["gid"] for g in state["placed"]), band, ctx):
        ctx["fails"]["luxband"] = ctx["fails"].get("luxband", 0) + 1
        return None
    pieces = []
    for g in state["placed"]:
        for p in g["pieces"]:
            x, y = p["at"][0] - x0, p["at"][1] - y0
            pw, ph = p["size"]
            pieces.append({"role": p["role"], "size": [pw, ph], "at": [x, y],
                           "group": g["gid"], "optional": p["optional"],
                           **({"back": p["back"]} if p["back"] else {})})
    pieces.sort(key=lambda p: (p["at"][1], p["at"][0], p["role"]))
    # draft id/description keep the mid-search check happy; _finalize writes
    # the real ones and checks again. sizeBand, sleeps, doors and the draft's
    # empty stretch all come from fixed_rooms.derive — the one derivation.
    room = {"id": ctx["family"] + ".draft", "family": ctx["family"],
            "clearance": ctx["clearance"], "style": "flush",
            "wealth": WEALTH[ctx["clearance"]], "size": [w, h],
            "pieces": pieces, "outdoor": False,
            "symmetric": ctx["symmetric"], "recipe": ctx["layout"],
            "description": "draft"}
    room = fixed_rooms.derive(room, stretch=False)
    room["stretch"] = {"x": [], "y": []}
    if room["sizeBand"] is None:
        return None
    # a requested band is a name, not a cell range: a room whose own band
    # comes out different (a 4x2 room is no narrow bedroom) is no room for
    # this request
    if ctx["size_band"] and room["sizeBand"] != ctx["size_band"]:
        ctx["fails"]["band"] = ctx["fails"].get("band", 0) + 1
        return None
    return room


def _score(room):
    w, h = room["size"]
    area = w * h
    s = area * SCORE_AREA
    s += max(0.0, max(w, h) / min(w, h) - 2.0) * SCORE_ASPECT
    s -= sum(1 for side in SIDES if room.get("doors", {}).get(side)) * SCORE_DOOR_SIDE
    if room.get("clearance") in ("roomy", "grand"):
        # every wall the wall-bound groups stand on (their pieces' backs,
        # at most four) spreads the furniture around the room
        used = len({p["back"] for p in room["pieces"] if p.get("back") in SIDES})
        s -= min(used, 4) * SCORE_WALLS_USED
    if room.get("style") == "open":
        # an open room reads right with its walls lined: every wall line
        # holds a piece except the filler's buffer
        s -= _covered(room) * SCORE_WALLS_USED
    if room.get("symmetric"):
        s -= SCORE_SYMMETRY
    return s


def _sig(room):
    return (tuple(room["size"]),
            tuple(sorted((p["role"], p["at"][0], p["at"][1],
                          p["size"][0], p["size"][1], p.get("back"))
                         for p in room["pieces"])))


def _finish(state, ctx):
    """Every slack variant of one finished state that checks out, as
    (score, tie-break, room). Variants the checker rejects are counted by
    kind (dead floor, aspect cap, other) so compose can say why no room
    came out."""
    out = []
    for sw, se, sn, ss in _slack_variants(state, ctx):
        room = _build_room(state, sw, se, sn, ss, ctx)
        if room is None:
            continue
        errors = fixed_rooms.check([room], {"groups": ctx["gdefs"]}, None)
        if errors:
            for e in errors:
                kind = ("dead" if "dead floor" in e
                        else "aspect" if "aspect" in e else "check")
                ctx["fails"][kind] = ctx["fails"].get(kind, 0) + 1
            continue
        out.append((_score(room), ctx["rng"].random(), room))
    return out


def _dedup_cands(cands):
    seen = set()
    out = []
    for c in cands:
        sig = _sig(c[2])
        if sig in seen:
            continue
        seen.add(sig)
        out.append(c)
    return out


# -------------------------------------------------------------- the open style

def _grown(room, gw, ge, gn, gs):
    """The room grown by gw+ge columns and gn+gs rows: wall-bound groups
    move out with their walls, everything else stays, doors derived again."""
    moved = copy.deepcopy(room)
    W, H = room["size"]
    moved["size"] = [W + gw + ge, H + gn + gs]
    for inst in fixed_rooms.instances(room):
        back = inst["back"]
        dx = gw + (-gw if back == "west" else ge if back == "east" else 0)
        dy = gn + (-gn if back == "north" else gs if back == "south" else 0)
        for i in inst["indices"]:
            p = moved["pieces"][i]
            p["at"] = [p["at"][0] + dx, p["at"][1] + dy]
    moved["pieces"].sort(key=lambda p: (p["at"][1], p["at"][0], p["role"]))
    moved = fixed_rooms.derive(moved, stretch=False)
    moved["stretch"] = {"x": [], "y": []}
    return moved


def _largest_clear(room, clearance):
    """The largest clear rectangle that makes a legal filler at the
    clearance: at least MIN_FILLER square, within FILLER_MAX (either
    orientation), its long side at most FILLER_ASPECT times its short, and
    centred — its distances to the west and east walls differ by at most 1,
    and the same for north and south. Clear means no piece on it and a
    clear cell to every wall. None when no such rectangle exists (a strip
    along a wall does not count; nobody lays a 2x11 rug)."""
    w, h = room["size"]
    hi, lo = FILLER_MAX[clearance]
    occupied = {(x, y) for x in range(w) for y in (0, h - 1)}
    occupied |= {(x, y) for y in range(h) for x in (0, w - 1)}
    for p in room["pieces"]:
        x, y, pw, ph = p["at"][0], p["at"][1], p["size"][0], p["size"][1]
        occupied |= {(cx, cy) for cx in range(x, x + pw)
                     for cy in range(y, y + ph)}
    best = None
    for fw in range(MIN_FILLER, min(w - 2, hi) + 1):
        for fh in range(MIN_FILLER, min(h - 2, hi) + 1):
            if max(fw, fh) > hi or min(fw, fh) > lo \
                    or max(fw, fh) > FILLER_ASPECT * min(fw, fh):
                continue
            # centring leaves at most two positions per axis
            for fx in {(w - fw) // 2, (w - fw + 1) // 2}:
                for fy in {(h - fh) // 2, (h - fh + 1) // 2}:
                    if any((cx, cy) in occupied
                           for cx in range(fx, fx + fw)
                           for cy in range(fy, fy + fh)):
                        continue
                    key = (fw * fh, min(fw, fh))
                    if best is None or key > best[0]:
                        best = (key, {"at": [fx, fy], "size": [fw, fh]})
    return None if best is None else best[1]


def _open(cands, ctx):
    """Open variants of the flush candidates: grow the room 1-2 cells on an
    axis (a symmetric room grows its columns in pairs), the wall-bound
    groups riding their walls out, and keep the largest clear middle that
    makes a legal filler — within FILLER_MAX at the clearance, at most
    FILLER_ASPECT to one, centred, off every wall. Growth variants that
    break a rule (an open room tolerates no empty wall line beyond the
    filler's buffer) or leave the band drop out; when every variant drops,
    the recipe has no open room."""
    out = []
    for _, _, room in cands:
        for gx in OPEN_GROWTH:
            for gw in range(gx + 1):
                if ctx["symmetric"] and 2 * gw != gx:
                    continue
                for gy in OPEN_GROWTH:
                    for gn in range(gy + 1):
                        if gx + gy == 0:
                            continue
                        grown = _grown(room, gw, gx - gw, gn, gy - gn)
                        fill = _largest_clear(grown, ctx["clearance"])
                        if fill is None:
                            continue
                        area = grown["size"][0] * grown["size"][1]
                        # _grown derived the family-aware band already
                        band = grown["sizeBand"]
                        if band is None:
                            continue
                        if not _inside_lux_bands(
                                (p.get("group") for p in grown["pieces"]),
                                band, ctx):
                            continue
                        if ctx["band"] and not ctx["band"][0] <= area <= ctx["band"][1]:
                            continue
                        if ctx["size_band"] and band != ctx["size_band"]:
                            continue
                        if ctx.get("max_area") is not None \
                                and area > ctx["max_area"]:
                            continue
                        grown["sizeBand"] = band
                        grown["style"] = "open"
                        grown["filler"] = fill
                        if fixed_rooms.check([grown], {"groups": ctx["gdefs"]}, None):
                            continue
                        out.append((_score(grown), ctx["rng"].random(), grown))
    return _dedup_cands(out)


# ------------------------------------------------------------------ finalize

def _finalize(rooms, ctx):
    """Ids, stretch lines and a description for the kept rooms, in rank
    order. The stretch lines are the gap lanes: every position where
    inserting an empty line keeps the room valid."""
    for i, room in enumerate(rooms, 1):
        style = ".open" if room["style"] == "open" else ""
        room["id"] = f"{ctx['family']}.{room['sizeBand']}.{i}." \
                     f"{ctx['clearance']}{style}"
        # the gap lanes come from fixed_rooms.derive with everything else:
        # every position where inserting an empty line keeps the room valid
        room.update(fixed_rooms.derive(room, {"groups": ctx["gdefs"]}, None))
        shape = f"{room['size'][0]}x{room['size'][1]}"
        room["description"] = (f"A {room['sizeBand']} {ctx['family']} room "
                               f"({shape}) of {len(fixed_rooms.instances(room))} "
                               f"furniture groups at {ctx['clearance']} spacing"
                               + (", mirrored" if room["symmetric"] else "")
                               + (" with an open middle" if room["style"] == "open"
                                  else "") + ".")
    return [r for r in rooms if not fixed_rooms.check(
        [r], {"groups": ctx["gdefs"]}, None)]
