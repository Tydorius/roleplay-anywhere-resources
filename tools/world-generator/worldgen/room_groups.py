"""Furniture groups: the fixed clusters the layouts hint at through their
beside:/around: anchors — a bed with its bedside tables, a table with its
chairs — one JSON file per family under ``library/groups/``, holding the
family's groups and one recipe per layout. ``library-seed/layouts_to_groups.py``
generates the files; they may be hand-edited afterwards. This module loads
and checks them.

  load(groups_dir)  -> {"groups": {id: group}, "recipes": {layout id: recipe},
                       "pools": {family: [entry, ...]}}, each entry carrying
                       its file in "_file"
  check(data, lib)  -> [error, ...], plain sentences starting with the file
"""
import json
import os

from . import fixed_rooms
from .library import ID_RE, LIB_DIR, SIDES, _size_ok, check_role_access

GROUPS_DIR = os.path.join(LIB_DIR, "groups")
WALLS = ("back", "corner", "none")
KINDS = ("anchor", "required", "optional", "repeatable")
# the kinds a luxury pool group can count against (room_composer.LUXURY_LIMITS):
# a group may be two — the fireplace seating is both hearth and seating
LUXURY_KINDS = ("seating", "hearth", "work", "decor", "display", "books",
                "storage")


def luxury_kinds(group):
    """The luxury pool kinds a group counts against, as a tuple (a plain
    string kind is one entry; a list is read as is). () when the group has
    no usable kind field."""
    k = (group or {}).get("kind")
    if isinstance(k, str):
        return (k,)
    if isinstance(k, list) and k and all(isinstance(x, str) for x in k):
        return tuple(k)
    return ()


def load(path=None):
    """Every ``library/groups/<family>.json`` as {"groups": {id: group},
    "recipes": {layout id: recipe}, "pools": {family: [entry, ...]}}, sorted
    by file name. A missing folder is
    an empty set (nothing has been generated yet). A file that isn't valid
    JSON becomes a "!<file>" group entry carrying ``_load_error``; the second
    group with an id (or recipe for a layout) keeps a ``_dupe_files`` list on
    the first. Both are reported by ``check``."""
    folder = path or GROUPS_DIR
    data = {"groups": {}, "recipes": {}, "pools": {}}
    if not os.path.isdir(folder):
        return data

    def keep(store, key, entry, name):
        entry["_file"] = name
        if key in store:
            first = store[key]
            dupes = first.setdefault("_dupe_files", [first.get("_file")])
            dupes.append(name)
            return
        store[key] = entry

    for path in sorted(os.path.join(folder, n) for n in os.listdir(folder)
                       if n.endswith(".json")):
        name = os.path.basename(path)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError) as e:
            # an unreadable file must fail the check, never vanish from it
            data["groups"]["!" + name] = {"_file": name, "_load_error": str(e)}
            continue
        if not isinstance(raw, dict):
            data["groups"]["!" + name] = {"_file": name,
                                          "_load_error": "not a JSON object"}
            continue
        for g in raw.get("groups") or []:
            if isinstance(g, dict):
                keep(data["groups"], g.get("id"), g, name)
        for r in raw.get("recipes") or []:
            if isinstance(r, dict):
                keep(data["recipes"], r.get("layout"), r, name)
        pools = raw.get("pools")
        if isinstance(pools, dict):
            for fam, entries in pools.items():
                if isinstance(entries, list):
                    for e in entries:
                        if isinstance(e, dict):
                            e = dict(e)
                            e["_file"] = name
                            data["pools"].setdefault(str(fam), []).append(e)
    return data


# ------------------------------------------------------------------ checks

def _int_pair(v, lo=0, hi=40):
    return (isinstance(v, list) and len(v) == 2
            and all(isinstance(x, int) and not isinstance(x, bool)
                    and lo <= x <= hi for x in v))


def _check_source(entry, err):
    """``source`` marks hand work the converter keeps verbatim: "hand" is
    the only value it may hold."""
    if entry.get("source") is not None and entry.get("source") != "hand":
        err('source must be "hand" or left out')


def _check_piece(p, roles, tiers, err):
    if not isinstance(p, dict):
        err("a piece must be a JSON object")
        return
    if p.get("role") not in roles:
        err(f"unknown role {p.get('role')!r}")
    if not _size_ok(p.get("size"), hi=12):
        err("piece size must be [w, h]")
    if not _int_pair(p.get("at")):
        err("piece at must be [x, y] cell offsets, zero or more")
    if p.get("back") is not None and p.get("back") not in SIDES:
        err(f"piece back must be one of {'/'.join(SIDES)} or left out")
    if p.get("optional") is not None and not isinstance(p.get("optional"), bool):
        err("piece optional must be true or false")
    if p.get("minWealth") is not None and p.get("minWealth") not in tiers:
        err(f"unknown minWealth {p.get('minWealth')!r}")


def _rects(pieces):
    """The placed rectangles, or None when any piece's geometry is broken
    (its own error has already been reported)."""
    out = []
    for p in pieces:
        size, at = p.get("size"), p.get("at")
        if not (_size_ok(size, hi=12) and _int_pair(at)):
            return None
        out.append((at[0], at[1], size[0], size[1]))
    return out


def _check_placement(pieces, wall, err):
    """Pieces never overlap, form one connected shape edge to edge, and a
    wall-bound piece backs north on the group's north edge."""
    rects = _rects(pieces)
    if rects is None:
        return
    for i in range(len(rects)):
        x, y, w, h = rects[i]
        for j in range(i + 1, len(rects)):
            a, b, cw, ch = rects[j]
            if x < a + cw and a < x + w and y < b + ch and b < y + h:
                err(f"pieces {pieces[i].get('role')!r} and "
                    f"{pieces[j].get('role')!r} overlap")
    # flood fill across pieces sharing an edge (a cell of one orthogonally
    # adjacent to a cell of the other)
    cells, edges = [], []
    for (x, y, w, h) in rects:
        cells.append({(cx, cy) for cx in range(x, x + w) for cy in range(y, y + h)})
        e = set()
        for cx in range(x, x + w):
            e.add((cx, y - 1))
            e.add((cx, y + h))
        for cy in range(y, y + h):
            e.add((x - 1, cy))
            e.add((x + w, cy))
        edges.append(e)
    adj = [[] for _ in rects]
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if (edges[i] & cells[j]) or (edges[j] & cells[i]):
                adj[i].append(j)
                adj[j].append(i)
    seen = {0}
    stack = [0]
    while stack:
        for k in adj[stack.pop()]:
            if k not in seen:
                seen.add(k)
                stack.append(k)
    if len(seen) != len(rects):
        off = [str(pieces[k].get("role")) for k in range(len(rects)) if k not in seen]
        err(f"pieces must form one connected shape; {', '.join(off)} touch nothing")
    for p in pieces:
        if p.get("back") is None:
            continue
        at = p.get("at") or [None, None]
        if wall == "none":
            err(f"a group with wall \"none\" has a wall-bound "
                f"{p.get('role')!r} piece")
        elif p.get("back") != "north" or at[1] != 0:
            err(f"piece {p.get('role')!r} backs {p.get('back')!r} at row "
                f"{at[1]}; a wall-bound piece backs north on the group's "
                f"north edge")


def _check_group_access(g, lib, err):
    """The group's own access, in its own frame: a hand group's ``access``
    entries sit in the ring of cells around the group, off its own
    furniture and off the walls its ``wall`` stands on (the north ring of a
    wall-bound group, the north and west of a corner one), and every
    constraint — derived from the roles or handed in — keeps its need of
    cells usable: not covered by the group's own pieces, not walled. A seat
    with no table, desk or counter in the group must back a wall."""
    raw = g.get("pieces") or []
    if not all(isinstance(p, dict) for p in raw):
        return
    pieces = raw
    rects = _rects(pieces)
    if rects is None:
        return
    minx = min(r[0] for r in rects)
    miny = min(r[1] for r in rects)
    W = max(r[0] + r[2] for r in rects)
    H = max(r[1] + r[3] for r in rects)
    wall = g.get("wall")
    furniture = {(cx, cy) for (x, y, w, h) in rects
                 for cx in range(x, x + w) for cy in range(y, y + h)}

    def walled(c):
        return ((wall in ("back", "corner") and c[1] == miny - 1)
                or (wall == "corner" and c[0] == minx - 1))

    def cell_ok(c):
        return (isinstance(c, list) and len(c) == 2
                and all(isinstance(v, int) and not isinstance(v, bool)
                        for v in c))

    access = g.get("access")
    if access is not None:
        if g.get("source") != "hand":
            err('access is hand work: the group must carry "source": "hand"')
        if not isinstance(access, list):
            err("access must be a list of {cells, need, replaces} entries")
            access = []
        for entry in access:
            if not isinstance(entry, dict):
                err(f"an access entry must be a JSON object, not {entry!r}")
                continue
            cells = entry.get("cells")
            if not (isinstance(cells, list) and cells
                    and all(cell_ok(c) for c in cells)):
                err("an access entry needs cells: [[x, y], ...]")
                continue
            need = entry.get("need")
            if not (isinstance(need, int) and not isinstance(need, bool)
                    and 1 <= need <= len(cells)):
                err(f"access need must be 1 to {len(cells)} (its cell count), "
                    f"not {need!r}")
            for c in cells:
                if not (minx - 1 <= c[0] <= W and miny - 1 <= c[1] <= H):
                    err(f"access cell {c} lies outside the ring of cells "
                        f"around the group")
                elif tuple(c) in furniture:
                    err(f"access cell {c} sits on the group's own furniture")
                elif walled(tuple(c)):
                    err(f"access cell {c} sits on the wall the group "
                        f"{'backs' if wall == 'back' else 'corners'}")
            repl = entry.get("replaces")
            if not isinstance(repl, list) or not repl or not all(
                    isinstance(k, int) and not isinstance(k, bool)
                    and 0 <= k < len(pieces) for k in repl):
                err("an access entry must replace the piece indexes it "
                    f"stands for, not {repl!r}")
    for c in fixed_rooms.group_constraints(g, lib):
        cells = [(cc[0], cc[1]) for cc in c["cells"]]
        i = c.get("piece")
        p = pieces[i] if isinstance(i, int) and 0 <= i < len(pieces) else None
        named = (f"piece {p.get('role')!r} at {p['at']}" if p
                 else "a piece of the group")
        usable = [cc for cc in cells if not walled(cc)]
        if len(usable) < (c.get("need") or 1):
            if not cells:
                err(f"{named} has no access cell left: its own group covers "
                    f"them all")
            else:
                listed = "[" + ", ".join(f"[{cc[0]}, {cc[1]}]"
                                         for cc in cells) + "]"
                err(f"{named} has no usable access cell among {listed}: the "
                    f"wall or its own furniture blocks them")
    for p in pieces:
        if p.get("role") not in fixed_rooms.SEAT_ROLES \
                or p.get("back") in SIDES:
            continue
        if any(fixed_rooms.seat_facing(q.get("role")) for q in pieces):
            continue
        err(f"piece {p.get('role')!r} at {p['at']} faces nothing: a seat "
            f"with no table, desk or counter in its group must back a wall")


def _check_groups(groups, lib, errors):
    families = lib.vocab.get("families", {})
    roles = lib.vocab.get("roles", {})
    for gid, g in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if "_load_error" in g:
            errors.append(f"{g.get('_file')}: cannot be read ({g['_load_error']})")
            continue

        def err(msg, gid=gid, g=g):
            errors.append(f"{g.get('_file')}: group {gid!r}: {msg}")

        files = g.get("_dupe_files")
        if files:
            errors.append(f"group id {gid!r} appears in {' and '.join(sorted(set(files)))}")
        if not isinstance(gid, str) or not ID_RE.match(gid):
            err("id must be lower case words separated by dots")
            continue
        _check_source(g, err)
        if g.get("family") not in families:
            err(f"unknown family {g.get('family')!r}")
        if g.get("wall") not in WALLS:
            err(f"wall must be one of {'/'.join(WALLS)}")
        use = g.get("use")
        if (not isinstance(use, list) or any(u not in SIDES for u in use)
                or len(set(use)) != len(use)):
            err(f"use must list {'/'.join(SIDES)} sides, no repeats")
        pieces = g.get("pieces")
        if not isinstance(pieces, list) or not pieces:
            err("pieces must be a list with at least one piece")
            continue
        for p in pieces:
            _check_piece(p, roles, lib.tiers, err)
        _check_placement(pieces, g.get("wall"), err)
        _check_group_access(g, lib, err)


def _check_count(e, group, err):
    if "count" not in e:
        return
    count = e["count"]
    piece_roles = [p.get("role") for p in (group or {}).get("pieces") or []
                   if isinstance(p, dict)]
    if count == "singles":
        if "sleep" not in piece_roles:
            err("count \"singles\" is for a group with a sleep piece")
    elif count == "couples":
        if "sleep.couple" not in piece_roles:
            err("count \"couples\" is for a group with a sleep.couple piece")
    elif not (isinstance(count, int) and not isinstance(count, bool)
              and count >= 1) and not (
            isinstance(count, list) and len(count) == 2
            and all(isinstance(x, int) and not isinstance(x, bool) for x in count)
            and 0 <= count[0] <= count[1] and count[1] >= 1):
        err(f"bad count {count!r}")


def _check_family_bands(lib, errors):
    """library.json's familySizeBands table: every entry a known family, band
    names unique within it, sane cell and aspect ranges (a room never reads
    longer than 4 to 1) and maxFloorPerPiece counting cells when given."""
    families = lib.vocab.get("families", {})
    for fam in sorted((lib.vocab.get("familySizeBands") or {}), key=str):
        if fam.startswith("_"):
            continue
        spec = (lib.vocab.get("familySizeBands") or {}).get(fam)

        def err(msg, fam=fam):
            errors.append(f"library.json: familySizeBands {fam!r}: {msg}")

        if fam not in families:
            err(f"names unknown family {fam!r}")
        if not (isinstance(spec, dict) and isinstance(spec.get("bands"), list)
                and spec["bands"]):
            err("needs a bands list with at least one band")
            continue
        mfp = spec.get("maxFloorPerPiece")
        if mfp is not None and not (isinstance(mfp, int)
                                    and not isinstance(mfp, bool) and mfp >= 0):
            err(f"maxFloorPerPiece must count floor cells, not {mfp!r}")
        names = set()
        for b in spec["bands"]:
            if not isinstance(b, dict) or not isinstance(b.get("name"), str):
                err(f"band {b!r} needs a name")
                continue
            name = b["name"]
            if name in names:
                err(f"band name {name!r} repeats")
            names.add(name)
            cells = b.get("cells")
            if not (isinstance(cells, list) and len(cells) == 2
                    and all(isinstance(x, int) and not isinstance(x, bool)
                            and 1 <= x <= 1600 for x in cells)
                    and cells[0] <= cells[1]):
                err(f"band {name!r} cells must be [lo, hi] with "
                    f"1 <= lo <= hi <= 1600, not {cells!r}")
            aspect = b.get("aspect")
            if aspect is not None:
                if not (isinstance(aspect, list) and len(aspect) == 2
                        and all(isinstance(x, (int, float))
                                and not isinstance(x, bool) and x > 0
                                for x in aspect)
                        and aspect[0] <= aspect[1]):
                    err(f"band {name!r} aspect must be [lo, hi] with "
                        f"0 < lo <= hi, not {aspect!r}")
                elif aspect[1] > 4:
                    err(f"band {name!r} aspect {aspect[1]:g} is over the "
                        f"4 to 1 a room may read at most")
            mfp = b.get("maxFloorPerPiece")
            if mfp is not None and not (isinstance(mfp, int)
                                        and not isinstance(mfp, bool)
                                        and mfp >= 0):
                err(f"band {name!r} maxFloorPerPiece must count floor "
                    f"cells, not {mfp!r}")


def _family_band_names(lib, family):
    """The family's own band names from familySizeBands, or [] when the
    family shares the sizeBands table."""
    spec = (lib.vocab.get("familySizeBands") or {}).get(family)
    if not isinstance(spec, dict):
        return []
    return [b.get("name") for b in spec.get("bands") or []
            if isinstance(b, dict) and isinstance(b.get("name"), str)]


def _check_recipes(data, lib, errors):
    groups, recipes, layouts = data["groups"], data["recipes"], lib.layouts
    for r in sorted(recipes.values(), key=lambda r: str(r.get("layout"))):
        lid = r.get("layout")

        def err(msg, lid=lid, r=r):
            errors.append(f"{r.get('_file')}: recipe {lid!r}: {msg}")

        files = r.get("_dupe_files")
        if files:
            errors.append(f"layout {lid!r} has recipes in "
                          f"{' and '.join(sorted(set(files)))}")
        _check_source(r, err)
        hand = r.get("source") == "hand"
        layout = layouts.get(lid)
        if layout is None and not hand:
            err("names no layout in the library")
        if layout is not None:
            if r.get("family") != layout.get("family"):
                err(f"family {r.get('family')!r} doesn't match the layout's "
                    f"{layout.get('family')!r}")
            # a hand recipe may retag a layout's bands (the privy recipes
            # name the family's own bands), so its sizeBands need not equal
            # the layout's
            if not hand and r.get("sizeBands") != layout.get("sizeBands"):
                err(f"sizeBands must be the layout's {layout.get('sizeBands')}")
        # every recipe's sizeBands name bands of its own family: the
        # familySizeBands table when the family has one, else the shared
        # sizeBands
        fam = r.get("family")
        own = _family_band_names(lib, fam)
        pool = set(own) if own else set(lib.vocab.get("sizeBands", {}))
        bands = r.get("sizeBands")
        if bands is not None:
            if not isinstance(bands, list) or not bands:
                err(f"sizeBands must list one or more of "
                    f"{', '.join(sorted(pool))}")
            else:
                for b in bands:
                    if b not in pool:
                        err(f"sizeBands names {b!r}, which is not a band of "
                            f"family {fam!r} "
                            f"(one of: {', '.join(sorted(pool))})")
        wealth = r.get("wealth")
        if wealth is not None:
            if not isinstance(wealth, list) or not wealth \
                    or any(t not in lib.tiers for t in wealth):
                err(f"wealth must list one or more of {', '.join(lib.tiers)}")
        entries = r.get("groups")
        if not isinstance(entries, list) or not entries:
            err("groups must be a list with at least one entry")
            entries = []
        anchors = 0
        for e in entries:
            if not isinstance(e, dict):
                err("a recipe entry must be a JSON object")
                continue
            gid = e.get("group")
            if gid not in groups:
                err(f"names no group {gid!r}")
            _check_source(e, err)
            if e.get("kind") not in KINDS:
                err(f"kind must be one of {'/'.join(KINDS)}")
            if e.get("kind") == "anchor":
                anchors += 1
            _check_count(e, groups.get(gid), err)
            if e.get("minWealth") is not None and e.get("minWealth") not in lib.tiers:
                err(f"unknown minWealth {e.get('minWealth')!r}")
        if anchors != 1:
            err(f"needs exactly one anchor, has {anchors}")
    covered = {r.get("layout") for r in recipes.values()}
    for lid in sorted(set(layouts) - covered):
        errors.append(f"layout {lid!r} has no recipe")


def _check_pools(data, lib, errors):
    """The luxury pools: every pool names a known family, every entry names
    a shipped group and bands of that family — its own when it has a table,
    else the shared sizeBands — every piece of a pooled group carries
    minWealth wealthy or elite — a pool group is what makes a grand private
    room grander, so it is furniture of the rich by definition — and every
    pooled group declares a valid luxury kind (what the composer's per-room
    limits count it against)."""
    families = lib.vocab.get("families", {})
    pools = data.get("pools") or {}
    for fam in sorted(pools, key=str):
        own = _family_band_names(lib, fam)
        bands = set(own) if own else set(lib.vocab.get("sizeBands", {}))
        entries = pools[fam]
        files = sorted({e.get("_file") for e in entries
                        if isinstance(e, dict)})
        if len(files) > 1:
            errors.append(f"pool for {fam!r} appears in {' and '.join(files)}")
        if fam not in families:
            where = entries[0].get("_file") if entries and \
                isinstance(entries[0], dict) else "?"
            errors.append(f"{where}: pool names unknown family {fam!r}")
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue

            def err(msg, e=e, fam=fam):
                errors.append(f"{e.get('_file')}: pool for {fam!r}: {msg}")

            gid = e.get("group")
            g = (data["groups"] or {}).get(gid)
            if g is None or "_load_error" in g:
                err(f"names no group {gid!r}")
                continue
            eb = e.get("bands")
            if not isinstance(eb, list) or not eb \
                    or any(b not in bands for b in eb):
                err(f"bands must list one or more of "
                    f"{', '.join(sorted(bands))}")
            kinds = luxury_kinds(g)
            if not kinds or any(k not in LUXURY_KINDS for k in kinds):
                err(f"group {gid!r} needs a kind: one or more of "
                    f"{', '.join(LUXURY_KINDS)}")
            for p in g.get("pieces") or []:
                if isinstance(p, dict) \
                        and p.get("minWealth") not in ("wealthy", "elite"):
                    err(f"group {gid!r} has a {p.get('role')!r} piece "
                        f"without minWealth wealthy or elite")
                    break


def check(data, lib):
    """Every rule of the group format the code can check, as plain sentences:
    group fields against the vocabulary, pieces that overlap or float apart,
    wall-bound pieces off the north edge, every group's access cells usable
    (a hand group's ``access`` entries in the ring around it and off its own
    furniture, and no seat facing nothing without a wall behind it),
    roleAccess covering every role, recipe kinds and counts, exactly
    one anchor per recipe, one recipe per layout (a hand recipe may name a
    layout of its own family without matching the layout's sizeBands, or no
    layout at all), every recipe's sizeBands naming bands of its own family,
    the familySizeBands table itself, the luxury pools naming
    known families, groups, size bands, kinds and wealth, and "hand" as the
    only source a group, recipe or recipe entry may declare."""
    errors = []
    _check_family_bands(lib, errors)
    errors += check_role_access(lib.vocab)
    _check_groups(data["groups"], lib, errors)
    _check_recipes(data, lib, errors)
    _check_pools(data, lib, errors)
    return errors
