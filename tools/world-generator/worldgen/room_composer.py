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
fill out instead of stringing along one line. A small beam search keeps the
best partial rooms; a candidate counts only when fixed_rooms.check passes.

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

BEAM_WIDTH = 24          # partial rooms kept per placement step
BEAM_SHAPE_KEEP = 3      # states kept per distinct shape (groups x box)
MAX_CANDIDATES = 6       # rooms returned, best first
OPEN_BASES = 8           # flush rooms the open style grows variants from
MAX_ROOM_SIDE = 30       # give up on runaway placements
GAP = {"tight": 1, "roomy": 2, "grand": 3}
SLACK = (0, 1)           # extra rows on a side no wall-bound group fixed
OPEN_GROWTH = (0, 1, 2)  # cells per axis the open style may add
MIN_FILLER = 2           # the open middle, at least 2x2
MAX_ASPECT = 2.0         # long side never above this multiple of the short
HALL_ASPECT = 2.5        # hall-like families read long, so they get more
HALL_FAMILIES = ("chapel", "common_room", "dining", "hall", "taproom")
GRAND_FLOOR = 25         # a grand room is at least a mid-sized room
WEALTH = {"tight": ["poor", "modest"], "roomy": ["wealthy"], "grand": ["elite"]}
# score weights, lower is better: area dominates, aspect and door sides
# refine, symmetry earns its bonus where flagged, and at roomy and grand
# every wall the wall-bound groups fill earns the spread bonus
SCORE_AREA = 1.0
SCORE_ASPECT = 5.0
SCORE_DOOR_SIDE = 3.0
SCORE_SYMMETRY = 5.0
SCORE_WALLS_USED = 6.0


def aspect_cap(family):
    """The most the long side may exceed the short side at any clearance or
    style: hall-like rooms (a nave, a refectory, a taproom) read long, so
    their cap is looser; everything else stays near square."""
    f = family or ""
    return HALL_ASPECT if f in HALL_FAMILIES or "hall" in f else MAX_ASPECT


def compose(recipe, groups, clearance, style, seed, size_band=None,
            symmetric=False, sleepers=None):
    """Compose ``recipe`` (a recipe dict from room_groups) at ``clearance``
    (tight/roomy/grand) in ``style`` (flush/open) into fixed-room candidates,
    best first and each passing fixed_rooms.check. Returns (rooms, reason):
    reason is a plain sentence when no room could be made. ``sleepers`` is
    (singles, couples), defaulting to the family's usual occupancy. With
    ``size_band`` only rooms inside that band come back. ``symmetric`` places
    the anchor on the centre line and every group off it mirrored across it.
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
    band = fixed_rooms.BANDS.get(size_band) if size_band else None
    if size_band and band is None:
        return ([], f"unknown size band {size_band!r}")
    layout = recipe.get("layout") or "hand"
    ctx = {"gap": GAP[clearance], "band": band, "symmetric": symmetric,
           "parity": 0, "clearance": clearance, "style": style,
           "family": family, "layout": layout, "gdefs": gdefs,
           "cap": aspect_cap(family),
           "floor": (GRAND_FLOOR if clearance == "grand" and not size_band
                     else 0),
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

    for kind, gid, mn, mx in units:
        states = _unit(states, kind, gid, mn, mx, ctx)
        if not states:
            note = f" inside size band {size_band}" if size_band else ""
            if kind == "one":
                return ([], f"cannot place required group {gid}{note}")
            if kind == "repeat":
                return ([], f"cannot place {mn} copies of {gid}{note}")
            return ([], f"cannot place {gid}{note}")

    cands = []
    for st in states:
        cands += _finish(st, ctx)
    cands = _dedup_cands(cands)
    if ctx["floor"]:
        floored = [c for c in cands
                   if c[2]["size"][0] * c[2]["size"][1] >= ctx["floor"]]
        if not floored and cands:
            # the recipe composes, but only rooms too small to be grand:
            # grown to a grand size they would be dead floor end to end
            return ([], f"{clearance}: too little furniture (dead floor)")
        cands = floored
    if not cands:
        fails = ctx["fails"]
        if fails.get("dead"):
            return ([], f"{clearance}: too little furniture (dead floor)")
        if fails.get("aspect"):
            return ([], f"{clearance}: every candidate breaks the aspect cap")
        if size_band:
            return ([], f"no room fits size band {size_band}")
        return ([], "no candidate passes the room checks")
    cands.sort(key=lambda c: (c[0], c[1]))
    if style == "open":
        opened = _open(cands[:OPEN_BASES], ctx)
        if not opened:
            return ([], f"no open variant keeps a {MIN_FILLER}x{MIN_FILLER} "
                        f"middle clear of every wall with its wall groups "
                        f"on the walls")
        opened.sort(key=lambda c: (c[0], c[1]))
        cands = opened
    rooms = _finalize([c[2] for c in cands[:MAX_CANDIDATES]], ctx)
    return (rooms, None)


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

def _box_score(minx, miny, maxx, maxy, walls, ctx):
    """The beam's partial score: area with the aspect penalty, a heavy
    handicap for boxes past the family's aspect cap (a later group can grow
    the short side and bring such a box back into shape, so it stays in the
    running, but far behind anything already within the cap), and at roomy
    and grand a bonus for every wall a wall-bound group has already fixed
    (capped at four, one per wall) so the search spreads groups around the
    room instead of stringing them along one line."""
    w, h = maxx - minx + 1, maxy - miny + 1
    aspect = max(w, h) / min(w, h)
    s = w * h * SCORE_AREA + max(0.0, aspect - 2.0) * SCORE_ASPECT
    if aspect > ctx["cap"]:
        s += (aspect - ctx["cap"]) * SCORE_ASPECT * 10 + 10 * SCORE_ASPECT
    if ctx["gap"] >= 2:
        s -= min(sum(1 for c in walls.values() if c is not None), 4) \
            * SCORE_WALLS_USED
    return s


def _state(placed, minx, miny, maxx, maxy, walls, ctx):
    return {"placed": placed, "minx": minx, "miny": miny,
            "maxx": maxx, "maxy": maxy, "walls": walls,
            "score": _box_score(minx, miny, maxx, maxy, walls, ctx),
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
    down with it; round-robin keeps the alternatives alive."""
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
    out = []
    for layer in range(BEAM_SHAPE_KEEP):
        for shape in shapes:
            sts = shapes[shape]
            if layer < len(sts):
                out.append(sts[layer])
                if len(out) == BEAM_WIDTH:
                    return out
    return out


def _unit(states, kind, gid, mn, mx, ctx):
    """Run one recipe unit over the beam: a required group (all states must
    place it), an optional one (added while a placement exists — never
    growing the room unless a size band was given, whose slack they fill),
    or a repeatable one (between mn and mx copies)."""
    forms = _forms(ctx["gdefs"][gid])
    if kind == "opt" and mx < 1:
        return states
    if kind == "repeat" and mx < 1:
        return states if mn < 1 else []
    if kind == "one":
        nxt = []
        for st in states:
            for form in forms:
                nxt += _placements(st, form, ctx)
        return _trim(nxt, ctx)
    if kind == "opt":
        # optional groups may grow the room when a size band was given
        # (whose slack they fill) and at roomy and grand, where the extra
        # furniture is what fills the bigger room — but there they only
        # ever fill: a placement that pushes the box past the aspect cap
        # is left unmade and the room goes on without the group
        allow = ctx["band"] is not None or ctx["gap"] >= 2
        nxt = []
        for st in states:
            for form in forms:
                nxt += _placements(st, form, ctx, allow_growth=allow)
        if allow and ctx["band"] is None:
            nxt = [s for s in nxt
                   if max(s["maxx"] - s["minx"] + 1, s["maxy"] - s["miny"] + 1)
                   <= ctx["cap"]
                   * min(s["maxx"] - s["minx"] + 1, s["maxy"] - s["miny"] + 1)]
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
    pieces = []
    occupied = set()
    for g in state["placed"]:
        for p in g["pieces"]:
            x, y = p["at"][0] - x0, p["at"][1] - y0
            pw, ph = p["size"]
            pieces.append({"role": p["role"], "size": [pw, ph], "at": [x, y],
                           "group": g["gid"], "optional": p["optional"],
                           **({"back": p["back"]} if p["back"] else {})})
            occupied |= {(cx, cy) for cx in range(x, x + pw)
                         for cy in range(y, y + ph)}
    pieces.sort(key=lambda p: (p["at"][1], p["at"][0], p["role"]))
    doors = {"north": [x for x in range(w) if (x, 0) not in occupied],
             "south": [x for x in range(w) if (x, h - 1) not in occupied],
             "west": [y for y in range(h) if (0, y) not in occupied],
             "east": [y for y in range(h) if (w - 1, y) not in occupied]}
    singles = sum(1 for p in pieces if p["role"] in SLEEP_SINGLE_ROLES)
    couples = sum(1 for p in pieces if p["role"] == SLEEP_COUPLE_ROLE)
    # draft id/description keep the mid-search check happy; _finalize writes
    # the real ones and checks again
    room = {"id": ctx["family"] + ".draft", "family": ctx["family"],
            "sizeBand": fixed_rooms.band_for_area(w * h),
            "clearance": ctx["clearance"], "style": "flush",
            "wealth": WEALTH[ctx["clearance"]], "size": [w, h],
            "sleeps": {"singles": singles, "couples": couples},
            "pieces": pieces, "doors": doors,
            "stretch": {"x": [], "y": []}, "outdoor": False,
            "symmetric": ctx["symmetric"], "recipe": ctx["layout"],
            "description": "draft"}
    if room["sizeBand"] is None:
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
    occupied = set()
    for p in moved["pieces"]:
        x, y, pw, ph = p["at"][0], p["at"][1], p["size"][0], p["size"][1]
        occupied |= {(cx, cy) for cx in range(x, x + pw)
                     for cy in range(y, y + ph)}
    w, h = moved["size"]
    moved["pieces"].sort(key=lambda p: (p["at"][1], p["at"][0], p["role"]))
    moved["doors"] = {"north": [x for x in range(w) if (x, 0) not in occupied],
                      "south": [x for x in range(w) if (x, h - 1) not in occupied],
                      "west": [y for y in range(h) if (0, y) not in occupied],
                      "east": [y for y in range(h) if (w - 1, y) not in occupied]}
    moved["stretch"] = {"x": [], "y": []}
    return moved


def _largest_clear(room):
    """The largest all-free rectangle at least MIN_FILLER by MIN_FILLER that
    touches no room edge — the open middle the filler (a rug, a table) goes
    into, with a clear cell between it and every wall. None when no such
    rectangle exists (a strip along a wall does not count)."""
    w, h = room["size"]
    if w < MIN_FILLER + 2 or h < MIN_FILLER + 2:
        return None
    occupied = {(x, y) for x in range(w) for y in (0, h - 1)}
    occupied |= {(x, y) for y in range(h) for x in (0, w - 1)}
    for p in room["pieces"]:
        x, y, pw, ph = p["at"][0], p["at"][1], p["size"][0], p["size"][1]
        occupied |= {(cx, cy) for cx in range(x, x + pw)
                     for cy in range(y, y + ph)}
    heights = [0] * w
    best = None
    for y in range(h):
        for x in range(w):
            heights[x] = 0 if (x, y) in occupied else heights[x] + 1
        stack = []
        for x in range(w + 1):
            hh = heights[x] if x < w else 0
            start = x
            while stack and stack[-1][1] > hh:
                sx, sh = stack.pop()
                if sh >= MIN_FILLER and x - sx >= MIN_FILLER:
                    area = sh * (x - sx)
                    if best is None or area > best[0]:
                        best = (area, [sx, y - sh + 1], [x - sx, sh])
                start = sx
            stack.append((start, hh))
    return None if best is None else {"at": best[1], "size": best[2]}


def _open(cands, ctx):
    """Open variants of the flush candidates: grow the room 1-2 cells on an
    axis (a symmetric room grows its columns in pairs), the wall-bound
    groups riding their walls out, and keep the largest clear middle — off
    every wall, at least MIN_FILLER square — as the filler area. Growth
    variants that break a rule (an open room tolerates no empty wall line
    beyond the filler's buffer) or leave the band drop out; when every
    variant drops, the recipe has no open room."""
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
                        fill = _largest_clear(grown)
                        if fill is None:
                            continue
                        area = grown["size"][0] * grown["size"][1]
                        band = fixed_rooms.band_for_area(area)
                        if band is None:
                            continue
                        if ctx["band"] and not ctx["band"][0] <= area <= ctx["band"][1]:
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
        w, h = room["size"]
        style = ".open" if room["style"] == "open" else ""
        room["id"] = f"{ctx['family']}.{room['sizeBand']}.{i}." \
                     f"{ctx['clearance']}{style}"
        room["stretch"] = {
            "x": [c for c in range(w + 1)
                  if fixed_rooms.stretch_ok(room, "x", c,
                                            {"groups": ctx["gdefs"]}, None) is None],
            "y": [r for r in range(h + 1)
                  if fixed_rooms.stretch_ok(room, "y", r,
                                            {"groups": ctx["gdefs"]}, None) is None]}
        shape = f"{room['size'][0]}x{room['size'][1]}"
        room["description"] = (f"A {room['sizeBand']} {ctx['family']} room "
                               f"({shape}) of {len(fixed_rooms.instances(room))} "
                               f"furniture groups at {ctx['clearance']} spacing"
                               + (", mirrored" if room["symmetric"] else "")
                               + (" with an open middle" if room["style"] == "open"
                                  else "") + ".")
    return [r for r in rooms if not fixed_rooms.check(
        [r], {"groups": ctx["gdefs"]}, None)]
