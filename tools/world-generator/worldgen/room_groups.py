"""Furniture groups: the fixed clusters the layouts hint at through their
beside:/around: anchors — a bed with its bedside tables, a table with its
chairs — one JSON file per family under ``library/groups/``, holding the
family's groups and one recipe per layout. ``library-seed/layouts_to_groups.py``
generates the files; they may be hand-edited afterwards. This module loads
and checks them.

  load(groups_dir)  -> {"groups": {id: group}, "recipes": {layout id: recipe}},
                       each entry carrying its file in "_file"
  check(data, lib)  -> [error, ...], plain sentences starting with the file
"""
import json
import os

from .library import ID_RE, LIB_DIR, SIDES, _size_ok

GROUPS_DIR = os.path.join(LIB_DIR, "groups")
WALLS = ("back", "corner", "none")
KINDS = ("anchor", "required", "optional", "repeatable")


def load(path=None):
    """Every ``library/groups/<family>.json`` as {"groups": {id: group},
    "recipes": {layout id: recipe}}, sorted by file name. A missing folder is
    an empty set (nothing has been generated yet). A file that isn't valid
    JSON becomes a "!<file>" group entry carrying ``_load_error``; the second
    group with an id (or recipe for a layout) keeps a ``_dupe_files`` list on
    the first. Both are reported by ``check``."""
    folder = path or GROUPS_DIR
    data = {"groups": {}, "recipes": {}}
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
    return data


# ------------------------------------------------------------------ checks

def _int_pair(v, lo=0, hi=40):
    return (isinstance(v, list) and len(v) == 2
            and all(isinstance(x, int) and not isinstance(x, bool)
                    and lo <= x <= hi for x in v))


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
        layout = layouts.get(lid)
        if layout is None:
            err("names no layout in the library")
        else:
            if r.get("family") != layout.get("family"):
                err(f"family {r.get('family')!r} doesn't match the layout's "
                    f"{layout.get('family')!r}")
            if r.get("sizeBands") != layout.get("sizeBands"):
                err(f"sizeBands must be the layout's {layout.get('sizeBands')}")
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


def check(data, lib):
    """Every rule of the group format the code can check, as plain sentences:
    group fields against the vocabulary, pieces that overlap or float apart,
    wall-bound pieces off the north edge, recipe kinds and counts, exactly
    one anchor per recipe, and one recipe per layout."""
    errors = []
    _check_groups(data["groups"], lib, errors)
    _check_recipes(data, lib, errors)
    return errors
