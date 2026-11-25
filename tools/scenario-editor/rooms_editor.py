"""The room library behind the Scenario Editor's Rooms tab: the generator's
fixed rooms, groups and sprites, read for browsing (rl-04a) and written for
hand work (rl-04b) — a family's rooms are saved only when the whole family
passes the generator's own fixed_rooms.check, with the previous file backed
up to library/rooms/.backup/. The generator in ../world-generator stays
standalone: it is only imported (never changed), like worldgen_editor.py,
and every regeneration runs its code (compose_recipe, generate, describe).

The library folder is the module variable LIBRARY_DIR (the shipped
``../world-generator/library``); tests point it at a temp copy. When the
generator's modules cannot be imported, or the library has no rooms,
``present()`` is false, the Rooms tab stays hidden and the editor works as
today.

  meta()                    -> {present, families, roles, bands, ...}
  family(family)            -> the family's rooms, each with its errors,
                               and the file's hash for saving
  room(id, turn, mirror)    -> one room turned and mirrored (preview only)
  groups(family)            -> the family's recipes, groups and luxury pool
  allgroups()               -> every group in the library with its file
  group(id)                 -> one group, its file and hash, its users
  check_group(req)          -> the group checker's verdict, nothing written
  save_group(req)           -> one group written (checker, backup, hash)
  save_recipe(req)          -> one recipe written the same way
  delete_group(req)         -> remove a group nothing uses
  look(id, band, turn, mirror) -> per piece the object and sprite the world
                               generator would place, and the sprite's turn
  sprite(band, object)      -> (webp bytes, content type)
  check_rooms(req)          -> the checker's verdict, nothing written
  save(req)                 -> one family written (checker, backup, hash)
  regenerate(id)            -> candidate re-laid-out rooms for one room
  start_regen_family(fam)   -> regenerate a family in a background thread
  job() / apply_regen() / discard_regen() -> poll, write or drop that job
"""
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORLDGEN_DIR = HERE.parent / "world-generator"
if str(WORLDGEN_DIR) not in sys.path:
    sys.path.insert(0, str(WORLDGEN_DIR))

# The shipped library; tests point this at a temp copy. Everything below
# takes the folder from here, so a swapped library is used throughout.
LIBRARY_DIR = WORLDGEN_DIR / "library"

try:
    from worldgen import fixed_rooms, library as lib_mod, library_art, \
        room_composer, room_groups
    from worldgen.library_rooms import purpose_for_family
    from worldgen.room_palette import DEFAULT_ROLE, ROLES, css as role_css
    MODULES = True
except Exception as _e:                                    # pragma: no cover
    fixed_rooms = lib_mod = library_art = room_composer = room_groups = None
    purpose_for_family = role_css = None
    ROLES, DEFAULT_ROLE = (), (158, 158, 158)
    IMPORT_ERROR = str(_e)
    MODULES = False

# check() messages that name a room: "{file}: room {id!r}: ..." and the
# duplicate-id line "room id {id!r} appears in ..."
_ROOM_IN_MSG = re.compile(r"^(?:\S+: )?room (?:id )?(?:'([^']+)'|\"([^\"]+)\")")


def _rooms_dir():
    return os.path.join(str(LIBRARY_DIR), "rooms")


def _groups_dir():
    return os.path.join(str(LIBRARY_DIR), "groups")


def _sprites_dir():
    return os.path.join(str(LIBRARY_DIR), "sprites")


def _lib():
    return lib_mod.load(str(LIBRARY_DIR))


def present():
    """True when the generator's modules import and the library has at least
    one room file that loads: the Rooms tab appears, else it stays hidden."""
    if not MODULES:
        return False
    return any(not r.get("_load_error") for r in fixed_rooms.load(_rooms_dir())
               if isinstance(r, dict))


# ---------------------------------------------------------------- meta

def _families():
    """[{family, rooms, errors}] as the rooms folder holds them, in file
    order, each family checked on its own."""
    out = []
    folder = _rooms_dir()
    by_file = {}
    for r in fixed_rooms.load(folder):
        by_file.setdefault(r.get("_file"), []).append(r)
    groups = room_groups.load(_groups_dir())
    lib = _lib()
    for name in sorted(by_file):
        fam = name[:-5] if name.endswith(".json") else name
        rooms = by_file[name]
        errors = fixed_rooms.check(rooms, groups, lib) if rooms else []
        out.append({"family": fam, "rooms": len(rooms), "errors": len(errors)})
    return out


def meta():
    """What the tab needs before it can show anything: whether the library is
    there, its families with room and error counts, the role palette as css
    colours, and the item-art bands that ship a sprite index."""
    families = _families() if MODULES else []
    roles = {prefix: role_css(prefix) for prefix, _rgb in ROLES}
    roles["*"] = "#%02x%02x%02x" % DEFAULT_ROLE
    return {"present": present() and bool(families),
            "families": families,
            "roles": roles,
            "bands": _bands(),
            "clearances": list(fixed_rooms.CLEARANCES) if MODULES else [],
            "styles": list(fixed_rooms.STYLES) if MODULES else [],
            "tiers": list(_lib().tiers) if MODULES else [],
            "sizeBands": ({n: list(r) for n, r in fixed_rooms.BANDS.items()}
                          if MODULES else {}),
            # the bands a family uses instead of the shared sizeBands, in
            # table order (a family absent here shares sizeBands)
            "familySizeBands": _family_size_bands(),
            "wealthFor": _wealth_for() if MODULES else {},
            "letters": "abcdefghijklmnopqrstuvwxyz",
            # what the group editor needs: the library's own families,
            # every role a piece may take, and the group format's fields
            "libraryFamilies": sorted((_lib().vocab.get("families") or {}))
            if MODULES else [],
            "roleNames": sorted((_lib().vocab.get("roles") or {}))
            if MODULES else [],
            "sides": list(fixed_rooms.SIDES) if MODULES else [],
            "walls": list(room_groups.WALLS) if MODULES else [],
            "kinds": list(room_groups.KINDS) if MODULES else [],
            "luxuryKinds": list(room_groups.LUXURY_KINDS) if MODULES else []}


def _bands():
    """The item-art bands that ship a sprite index (sorted)."""
    return sorted(os.path.basename(os.path.dirname(p)) for p in _sprite_indexes())


def _family_size_bands():
    """{family: [band, ...]} for every family with its own band table in
    library.json's familySizeBands, each band {name, cells, aspect?,
    maxFloorPerPiece?} in table order ({}) when the modules are absent."""
    if not MODULES:
        return {}
    lib = _lib()
    out = {}
    for fam in (lib.vocab.get("familySizeBands") or {}):
        if fam.startswith("_"):
            continue
        bands = fixed_rooms.family_bands(fam, lib)
        if bands:
            out[fam] = [{"name": b["name"], "cells": list(b["cells"]),
                         **({"aspect": list(b["aspect"])}
                            if b["aspect"] else {}),
                         **({"maxFloorPerPiece": b["maxFloorPerPiece"]}
                            if b["maxFloorPerPiece"] is not None else {})}
                        for b in bands]
    return out


def _sprite_indexes():
    root = _sprites_dir()
    if not os.path.isdir(root):
        return []
    return [os.path.join(root, band, "index.json") for band in sorted(os.listdir(root))
            if os.path.isfile(os.path.join(root, band, "index.json"))]


# ---------------------------------------------------------------- family

def _plain(obj):
    """A loaded dict without the loader's bookkeeping keys."""
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def family(family):
    """One family's rooms as stored (no bookkeeping keys), each carrying its
    checker errors (``errors: []`` when clean); messages that name no room
    land in the top-level ``errors`` list."""
    _need_modules()
    name = f"{family}.json"
    rooms = [r for r in fixed_rooms.load(_rooms_dir()) if r.get("_file") == name]
    if not rooms and not os.path.isfile(os.path.join(_rooms_dir(), name)):
        raise LookupError(f"no rooms file for family {family!r}")
    errors = fixed_rooms.check(rooms, room_groups.load(_groups_dir()), _lib())
    by_id, loose = {}, []
    for r in rooms:
        clean = _plain(r)
        clean["errors"] = []
        by_id[r.get("id")] = clean
    for msg in errors:
        m = _ROOM_IN_MSG.match(msg)
        rid = (m.group(1) or m.group(2)) if m else None
        if rid in by_id:
            by_id[rid]["errors"].append(msg)
        else:
            loose.append(msg)
    return {"family": family, "rooms": list(by_id.values()), "errors": loose,
            "hash": _file_hash(os.path.join(_rooms_dir(), name))}


def _wealth_for():
    """clearance -> style -> the wealth tiers a fresh generation would give
    (the seed script's own wealth_for, imported never copied), so the page
    can say what a reset field returns to. {} when the seed script cannot be
    imported."""
    try:
        g = _generate_rooms_mod()
    except Exception:                                      # pragma: no cover
        return {}
    return {c: {s: g.wealth_for(c, s) for s in fixed_rooms.STYLES}
            for c in fixed_rooms.CLEARANCES}


def _generate_rooms_mod():
    """The seed script library-seed/generate_rooms.py, imported once: its
    compose rules, shape canonicalisation, descriptions and wealth tiers are
    the generator's own, called here and never copied."""
    global _GEN
    if _GEN is None:
        import importlib.util
        path = WORLDGEN_DIR / "library-seed" / "generate_rooms.py"
        spec = importlib.util.spec_from_file_location("generate_rooms",
                                                      str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _GEN = mod
    return _GEN


_GEN = None


# ---------------------------------------------------------------- one room

def _find_room(room_id):
    for r in fixed_rooms.load(_rooms_dir()):
        if r.get("id") == room_id:
            return r
    raise LookupError(f"no room {room_id!r}")


def _turn_mirror(turn, mirror):
    try:
        turn = int(turn or 0)
    except (TypeError, ValueError):
        raise ValueError("turn must be 0, 1, 2 or 3")
    if not 0 <= turn <= 3:
        raise ValueError("turn must be 0, 1, 2 or 3")
    if str(mirror or "0") not in ("0", "1"):
        raise ValueError("mirror must be 0 or 1")
    return turn, str(mirror or "0") == "1"


def room(room_id, turn=0, mirror=0):
    """One room turned ``turn`` quarter turns (and mirrored first when set)
    through the generator's own fixed_rooms.rotate — never a copy of its
    maths. Preview only: nothing is stored. The room carries ``_access``,
    its derived access constraints, for the plan to draw faintly."""
    _need_modules()
    t, m = _turn_mirror(turn, mirror)
    r = fixed_rooms.rotate(_find_room(room_id), t, m)
    groups = room_groups.load(_groups_dir())
    r["_access"] = fixed_rooms.access_constraints(
        r.get("pieces") or [], r, _lib(), groups)
    return r


# ---------------------------------------------------------------- look

def look(room_id, band, turn=0, mirror=0):
    """For each piece of the room (in ``pieces`` order) the library object
    the world generator would pick for its role, size, ``band`` and the
    room's highest wealth tier — the first candidate that ships a sprite in
    that band — plus how the sprite must be turned so the piece's ``back``
    faces its wall (layout_room's TURN_SIDES rule), or null when no
    candidate has a sprite."""
    _need_modules()
    t, m = _turn_mirror(turn, mirror)
    r = fixed_rooms.rotate(_find_room(room_id), t, m)
    lib = _lib()
    if band not in _bands():
        raise ValueError(f"unknown art band {band!r}")
    index = library_art.load_index(band, root=_sprites_dir())
    purpose = purpose_for_family(lib, r.get("family"))
    tier = _highest_tier(lib, r.get("wealth"))
    out = []
    for p in r.get("pieces") or []:
        if purpose is None or not isinstance(p, dict):
            out.append(None)
            continue
        for o in lib_mod.candidates(lib, purpose, p.get("role"), p.get("size"),
                                    band, tier):
            oid = o.get("id")
            if oid not in index:
                continue
            if not os.path.exists(library_art.sprite_path(band, oid,
                                                          root=_sprites_dir())):
                continue
            out.append({"object": oid, "rot": _sprite_rot(p, o),
                        "size": list(o.get("size") or [1, 1])})
            break
        else:
            out.append(None)
    return {"room": room_id, "band": band, "turn": t, "mirror": m,
            "tier": tier, "look": out}


def _highest_tier(lib, wealth):
    """The room's highest wealth tier (its list is stored low first)."""
    tiers = list(lib.tiers)
    for t in reversed(tiers):
        if t in (wealth or []):
            return t
    return tiers[-1] if tiers else "modest"


def _sprite_rot(piece, obj):
    """The quarter turns that put the object's back on the piece's wall
    side: layout_room.py's TURN_SIDES (rot r puts the back on TURN_SIDES[r]),
    as its wall hints use it (r = TURN_SIDES.index(side))."""
    sides = fixed_rooms.SIDES
    back, oback = piece.get("back"), obj.get("back")
    if back not in sides or oback not in sides:
        return 0
    return (sides.index(back) - sides.index(oback)) % 4


# ---------------------------------------------------------------- groups

def groups(family):
    """The family's recipes as loaded, every group those recipes or the
    family's luxury pool names with its pieces, and the pool entries with
    their size bands and luxury kinds. Each recipe carries the group file
    it lives in, and ``hashes`` maps every group file to its sha256 — what
    a recipe save needs for its stale-file guard."""
    _need_modules()
    data = room_groups.load(_groups_dir())
    recipes = []
    for r in sorted((e for e in data["recipes"].values()
                     if e.get("family") == family),
                    key=lambda r: str(r.get("layout"))):
        clean = _plain(r)
        clean["file"] = r.get("_file")
        recipes.append(clean)
    named = {e.get("group") for r in recipes for e in (r.get("groups") or [])
             if isinstance(e, dict)}
    pooled = {e.get("group") for e in data["pools"].get(family) or []
              if isinstance(e, dict)}
    out_groups = {gid: _plain(data["groups"][gid])
                  for gid in sorted(named | pooled, key=str)
                  if isinstance(data["groups"].get(gid), dict)}
    pool = []
    for e in data["pools"].get(family) or []:
        entry = _plain(e)
        g = data["groups"].get(entry.get("group")) or {}
        entry["kind"] = list(room_groups.luxury_kinds(g))
        pool.append(entry)
    return {"family": family, "recipes": recipes, "groups": out_groups,
            "pool": pool, "hashes": _group_file_hashes()}


def _group_file_hashes():
    """{file: sha256} for every group file, the stale-file guard for group
    and recipe saves."""
    out = {}
    if os.path.isdir(_groups_dir()):
        for name in sorted(os.listdir(_groups_dir())):
            path = os.path.join(_groups_dir(), name)
            if name.endswith(".json") and os.path.isfile(path):
                out[name] = _file_hash(path)
    return out


def allgroups():
    """GET /api/rooms/allgroups: every group in the library, sorted by id —
    its id, the file it lives in, family, wall, use, pieces, its luxury
    kinds, and the families whose recipes or pools use it."""
    _need_modules()
    data = room_groups.load(_groups_dir())
    users = {}
    for r in data["recipes"].values():
        if not isinstance(r, dict):
            continue
        for e in (r.get("groups") or []):
            if isinstance(e, dict):
                users.setdefault(e.get("group"), set()).add(r.get("family"))
    for fam, entries in (data.get("pools") or {}).items():
        for e in entries:
            if isinstance(e, dict):
                users.setdefault(e.get("group"), set()).add(fam)
    out = []
    for gid, g in sorted(data["groups"].items(), key=lambda kv: str(kv[0])):
        if not isinstance(g, dict) or "_load_error" in g:
            continue
        clean = _plain(g)
        clean["file"] = g.get("_file")
        clean["kind"] = list(room_groups.luxury_kinds(g))
        clean["usedBy"] = sorted(users.get(gid) or (), key=str)
        out.append(clean)
    return {"groups": out}


# ------------------------------------------------------------ group editing

def group(gid):
    """GET /api/rooms/group: one group as stored, the file it lives in with
    that file's hash (the stale-file guard when it is saved), the recipes
    that name it, the pools that offer it, and the stored rooms whose
    pieces carry it — an edited group never changes those rooms; they keep
    the pieces they were composed with."""
    _need_modules()
    data = room_groups.load(_groups_dir())
    g = data["groups"].get(gid)
    if not isinstance(g, dict) or "_load_error" in g:
        raise LookupError(f"no group {gid!r}")
    fname = g.get("_file")
    path = os.path.join(_groups_dir(), fname or "")
    if not os.path.isfile(path):
        raise LookupError(f"no group file {fname!r}")
    out = _plain(g)
    out["file"] = fname
    out["hash"] = _file_hash(path)
    out["recipes"] = [{"layout": r.get("layout"), "family": r.get("family"),
                       "kind": e.get("kind")}
                      for r in sorted(data["recipes"].values(),
                                      key=lambda r: str(r.get("layout")))
                      if isinstance(r, dict)
                      for e in (r.get("groups") or [])
                      if isinstance(e, dict) and e.get("group") == gid]
    out["pools"] = [{"family": fam, "bands": list(e.get("bands") or [])}
                    for fam in sorted((data.get("pools") or {}), key=str)
                    for e in ((data.get("pools") or {}).get(fam) or [])
                    if isinstance(e, dict) and e.get("group") == gid]
    out["rooms"] = _rooms_using(gid)
    # the rule-derived constraints on their own (the hand ``access`` list
    # stays in the group itself): what the group editor draws faintly
    out["accessDerived"] = fixed_rooms.group_constraints(
        {"pieces": g.get("pieces") or []}, _lib())
    return out


def _rooms_using(gid):
    """The stored rooms whose pieces name the group, [{id, family}] sorted
    by id — who a group edit has to be told about."""
    return [{"id": r.get("id"), "family": r.get("family")}
            for r in fixed_rooms.load(_rooms_dir())
            if isinstance(r, dict) and any(
                isinstance(p, dict) and p.get("group") == gid
                for p in (r.get("pieces") or []))]


def _clean_entry(entry):
    """A group or recipe as it is stored: no bookkeeping keys (the loader's
    ``_file``), no per-entry errors list, and none of the keys the editor's
    own replies add (file, hash, the users lists) — the page sends a loaded
    group straight back, and those must not reach the file."""
    drop = {"errors", "file", "hash", "recipes", "pools", "rooms", "usedBy",
            "accessDerived"}
    return {k: v for k, v in entry.items()
            if not k.startswith("_") and k not in drop}


def _pool_entries(pool):
    """A save or check request's pool entries, normalised to
    [{"family", "bands"}]: one object or a list of them (a new luxury group
    can join several families' pools)."""
    if pool is None:
        return []
    if isinstance(pool, dict):
        pool = [pool]
    if not isinstance(pool, list):
        raise ValueError("pool must be an object or a list of objects")
    out = []
    for e in pool:
        if not isinstance(e, dict):
            raise ValueError("every pool entry must be a JSON object")
        out.append({"family": e.get("family"),
                    "bands": list(e.get("bands") or [])})
    return out


def _with_group(req):
    """The whole library's group data with the request's group in (added,
    or replacing the group of its id) and its pool entries merged into
    their families' pools — the data a save would leave behind, and what
    the group checker runs on. Returns it with the group's cleaned id."""
    group_ = req.get("group")
    if not isinstance(group_, dict):
        raise ValueError("group must be a JSON object")
    gid = group_.get("id")
    if not isinstance(gid, str) or not gid:
        raise ValueError("the group needs an id")
    data = room_groups.load(_groups_dir())
    old = data["groups"].get(gid) or {}
    entry = _clean_entry(group_)
    # name the file in the checker's messages: the file it lives in, else
    # the one the request saves it to
    entry["_file"] = old.get("_file") or req.get("file") or "new group"
    data["groups"][gid] = entry
    for e in _pool_entries(req.get("pool")):
        fam = e["family"]
        entries = [p for p in (data["pools"].get(fam) or [])
                   if not (isinstance(p, dict) and p.get("group") == gid)]
        entries.append({"group": gid, "bands": e["bands"],
                        "_file": "luxury.json"})
        data["pools"][fam] = entries
    return data, gid


def check_group(req):
    """POST /api/rooms/group/check: the group checker's verdict — the whole
    library with the request's group and pool entries in, exactly the
    check ``python -m worldgen library groups`` runs. Nothing is written:
    a group with errors stays a draft in the page, it just cannot be
    saved."""
    _need_modules()
    data, _gid = _with_group(req)
    group_ = req.get("group") or {}
    return {"errors": room_groups.check(data, _lib()),
            "accessDerived": fixed_rooms.group_constraints(
                {"pieces": group_.get("pieces") or []}, _lib())}


def _group_file_name(name):
    """A groups file name: lower case words separated by dots, .json."""
    if not isinstance(name, str) \
            or not re.fullmatch(r"[a-z0-9]+(?:\.[a-z0-9]+)*\.json", name):
        raise ValueError(f"bad group file name {name!r}")
    return name


def _read_groups_raw(fname):
    """One groups file as stored, ready to edit and write back."""
    with open(os.path.join(_groups_dir(), fname), "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"{fname} is not a JSON object")
    return raw


def _write_groups_file(fname, raw):
    """One groups file written the way the rooms are written: the previous
    file copied to library/groups/.backup/<file> first (the loaders list
    only top-level *.json, so the backup folder never loads), then a temp
    file replaced into place, indent 2, one trailing newline."""
    path = os.path.join(_groups_dir(), fname)
    backup = os.path.join(_groups_dir(), ".backup", fname)
    os.makedirs(os.path.dirname(backup), exist_ok=True)
    shutil.copyfile(path, backup)
    fd, tmp = tempfile.mkstemp(dir=_groups_dir(), prefix=".tmp-",
                               suffix=f"-{fname}")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(raw, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return backup


def save_group(req):
    """POST /api/rooms/group/save: one group written into the file it lives
    in — a new group into the file the request names (a family's group
    file, or luxury.json for a group made from the luxury section, whose
    pool entries travel with it) — only when the whole library passes the
    group checker with it in, the file on disk is still the one the page
    loaded, and the id is not another file's. A group made or changed by
    the save carries "source": "hand" — the converter keeps it as it is.
    The reply lists the stored
    rooms that use the group and the room checker's verdict: a group save
    never edits a room file, and the rooms keep the pieces they were
    composed with."""
    _need_modules()
    group_ = req.get("group")
    if not isinstance(group_, dict):
        raise ValueError("group must be a JSON object")
    gid = group_.get("id")
    stored = room_groups.load(_groups_dir())
    existing = stored["groups"].get(gid)
    if isinstance(existing, dict) and "_load_error" in existing:
        existing = None
    if existing is not None:
        fname = existing.get("_file")
        target = _group_file_name(req.get("file")) if req.get("file") else fname
        if target != fname:
            raise SaveError([f"group {gid!r} already lives in {fname}: a "
                             "new group cannot take its id"])
    else:
        if not isinstance(gid, str) or not gid:
            raise ValueError("the group needs an id")
        fname = _group_file_name(req.get("file"))
    path = os.path.join(_groups_dir(), fname or "")
    if not os.path.isfile(path):
        raise LookupError(f"no group file {fname!r}")
    if req.get("hash") != _file_hash(path):
        raise SaveError([f"{fname} changed on disk since the page loaded "
                         "it: reload and save again"])
    data, gid = _with_group(req)
    errors = room_groups.check(data, _lib())
    if errors:
        raise SaveError(errors)
    raw = _read_groups_raw(fname)
    clean = _clean_entry(group_)
    # A group made or changed here is hand work: it carries the marker the
    # converter keeps verbatim. An unchanged save keeps what it had.
    old = next((e for e in (raw.get("groups") or [])
                if isinstance(e, dict) and e.get("id") == gid), None)
    bare = {k: v for k, v in clean.items() if k != "source"}
    old_bare = ({k: v for k, v in old.items() if k != "source"}
                if isinstance(old, dict) else None)
    if old_bare != bare:
        clean["source"] = "hand"
    groups_list = raw.get("groups")
    if not isinstance(groups_list, list):
        raise ValueError(f"{fname} holds no groups list")
    for i, e in enumerate(groups_list):
        if isinstance(e, dict) and e.get("id") == gid:
            groups_list[i] = clean
            break
    else:
        groups_list.append(clean)
    raw["groups"] = groups_list
    pools = _pool_entries(req.get("pool"))
    if pools:
        raw_pools = raw.get("pools")
        if not isinstance(raw_pools, dict):
            raw_pools = {}
            raw["pools"] = raw_pools
        for e in pools:
            entries = [p for p in (raw_pools.get(e["family"]) or [])
                       if not (isinstance(p, dict) and p.get("group") == gid)]
            entries.append({"group": gid, "bands": e["bands"]})
            raw_pools[e["family"]] = entries
    _write_groups_file(fname, raw)
    return {"ok": True, "group": gid, "file": fname,
            "hash": _file_hash(path),
            "roomsUsing": _rooms_using(gid),
            "roomErrors": fixed_rooms.check(fixed_rooms.load(_rooms_dir()),
                                            data, _lib())}


def save_recipe(req):
    """POST /api/rooms/recipe/save: one recipe written into the group file
    it lives in, only when the whole library passes the group checker with
    it in and the file on disk is still the one the page loaded. The page
    marks the hand work: an entry it added carries "source": "hand", and a
    recipe it changed beyond adding entries is "hand" whole — the converter
    keeps both."""
    _need_modules()
    recipe = req.get("recipe")
    if not isinstance(recipe, dict):
        raise ValueError("recipe must be a JSON object")
    lid = recipe.get("layout")
    if not isinstance(lid, str) or not lid:
        raise ValueError("the recipe needs a layout")
    stored = room_groups.load(_groups_dir())
    existing = stored["recipes"].get(lid)
    fname = existing.get("_file") if isinstance(existing, dict) else None
    if fname is None:
        fname = _group_file_name(req.get("file"))
    path = os.path.join(_groups_dir(), fname or "")
    if not os.path.isfile(path):
        raise LookupError(f"no group file {fname!r}")
    if req.get("hash") != _file_hash(path):
        raise SaveError([f"{fname} changed on disk since the page loaded "
                         "it: reload and save again"])
    clean = _clean_entry(recipe)
    data = dict(stored)
    data["recipes"] = dict(stored["recipes"], **{lid: clean})
    errors = room_groups.check(data, _lib())
    if errors:
        raise SaveError(errors)
    raw = _read_groups_raw(fname)
    recipes_list = raw.get("recipes")
    if not isinstance(recipes_list, list):
        raise ValueError(f"{fname} holds no recipes list")
    for i, e in enumerate(recipes_list):
        if isinstance(e, dict) and e.get("layout") == lid:
            recipes_list[i] = clean
            break
    else:
        recipes_list.append(clean)
    raw["recipes"] = recipes_list
    _write_groups_file(fname, raw)
    return {"ok": True, "recipe": lid, "file": fname,
            "hash": _file_hash(path)}


def delete_group(req):
    """POST /api/rooms/group/delete: remove a group nothing uses. Any
    recipe, luxury pool or stored room that names it refuses the delete,
    saying which."""
    _need_modules()
    gid = req.get("id")
    if not isinstance(gid, str) or not gid:
        raise ValueError("the group id is required")
    data = room_groups.load(_groups_dir())
    g = data["groups"].get(gid)
    if not isinstance(g, dict) or "_load_error" in g:
        raise LookupError(f"no group {gid!r}")
    fname = g.get("_file")
    path = os.path.join(_groups_dir(), fname or "")
    if not os.path.isfile(path):
        raise LookupError(f"no group file {fname!r}")
    users = [f"recipe {r.get('layout')!r} of {r.get('family')!r}"
             for r in sorted(data["recipes"].values(),
                             key=lambda r: str(r.get("layout")))
             if isinstance(r, dict)
             for e in (r.get("groups") or [])
             if isinstance(e, dict) and e.get("group") == gid]
    pools = [f"the luxury pool of {fam!r}"
             for fam in sorted((data.get("pools") or {}), key=str)
             for e in ((data.get("pools") or {}).get(fam) or [])
             if isinstance(e, dict) and e.get("group") == gid]
    rooms = _rooms_using(gid)
    if users or pools or rooms:
        raise SaveError([f"group {gid!r} is used by "
                         + ", ".join(users + pools
                                     + [f"room {r.get('id')!r}" for r in rooms])])
    if req.get("hash") != _file_hash(path):
        raise SaveError([f"{fname} changed on disk since the page loaded "
                         "it: reload and delete again"])
    raw = _read_groups_raw(fname)
    raw["groups"] = [e for e in (raw.get("groups") or [])
                     if not (isinstance(e, dict) and e.get("id") == gid)]
    _write_groups_file(fname, raw)
    return {"ok": True, "group": gid, "file": fname}


# ------------------------------------------------------------------ saving

# a family file name: lower case words separated by dots (no path parts)
_FAM_RE = re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)*\Z")


class SaveError(ValueError):
    """A save the checker (or the stale-file guard) refused: ``errors``
    holds its sentences."""

    def __init__(self, errors):
        super().__init__("; ".join(errors[:3])
                         + ("..." if len(errors) > 3 else ""))
        self.errors = list(errors)


def _family_path(family):
    """The family's rooms file path, from a validated family name."""
    if not isinstance(family, str) or not _FAM_RE.match(family):
        raise ValueError(f"bad family name {family!r}")
    return os.path.join(_rooms_dir(), family + ".json")


def _file_hash(path):
    """The sha256 of a file's bytes, as the page's stale-file guard (an
    mtime is too fine for JavaScript numbers)."""
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _clean_room(room):
    """A room as it is stored: no bookkeeping keys, no per-room errors."""
    return {k: v for k, v in room.items()
            if not k.startswith("_") and k != "errors"}


def _write_family(family, rooms):
    """One family's rooms written the way the generator writes them: sorted
    by id, indent 2, one trailing newline, through a temp file replaced into
    place. The previous file is copied to library/rooms/.backup/<family>.json
    first (one backup per family; no loader reads that folder). Returns the
    backup path."""
    path = _family_path(family)
    backup = os.path.join(_rooms_dir(), ".backup", family + ".json")
    os.makedirs(os.path.dirname(backup), exist_ok=True)
    shutil.copyfile(path, backup)
    fd, tmp = tempfile.mkstemp(dir=_rooms_dir(), prefix=".tmp-",
                               suffix=f"-{family}.json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"rooms": sorted(rooms, key=lambda r: r.get("id") or "")},
                      fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return backup


def check_rooms(req):
    """POST /api/rooms/check: the fixed-room checker's verdict on the rooms
    the page holds (the live check while a layout is edited), as plain
    sentences, with each room derived first — size, sizeBand, sleeps, doors
    and stretch worked out from its pieces by the one derivation. Nothing is
    written and no family has to be complete."""
    _need_modules()
    rooms = req.get("rooms")
    if not isinstance(rooms, list):
        rooms = [req["room"]] if isinstance(req.get("room"), dict) else []
    groups, lib = room_groups.load(_groups_dir()), _lib()
    derived = []
    for r in rooms if isinstance(rooms, list) else []:
        if not isinstance(r, dict):
            continue
        d = fixed_rooms.derive(_clean_room(r), groups, lib)
        # the room's access constraints ride along for the plan to draw
        # faintly; the underscore keeps them out of any saved file
        d["_access"] = fixed_rooms.access_constraints(
            d.get("pieces") or [], d, lib, groups)
        derived.append(d)
    return {"errors": fixed_rooms.check(derived, groups, lib), "derived": derived}


def save(req):
    """POST /api/rooms/save: one family's rooms as the page holds them,
    written only when the whole family passes the generator's own checker
    and the file on disk is still the one the page loaded (its sha256).
    The previous file is backed up and the new one written atomically,
    sorted by id, in the generator's formatting — an unchanged save writes
    identical bytes."""
    _need_modules()
    family = req.get("family")
    path = _family_path(family)
    if not os.path.isfile(path):
        raise LookupError(f"no rooms file for family {family!r}")
    if req.get("hash") != _file_hash(path):
        raise SaveError([f"{family}.json changed on disk since the page "
                         "loaded it: reload the family and save again"])
    rooms = req.get("rooms")
    if not isinstance(rooms, list) or not rooms:
        raise ValueError("a family file needs a list with at least one room")
    rooms = [_clean_room(r) for r in rooms if isinstance(r, dict)]
    if len(rooms) != len(req.get("rooms") or []):
        raise ValueError("every room must be a JSON object")
    for r in rooms:
        if r.get("family") != family:
            raise ValueError(f"room {r.get('id')!r} does not belong to "
                             f"family {family!r}")
    # every room derived before it is checked or written, so the file always
    # holds true worked-out fields
    groups, lib = room_groups.load(_groups_dir()), _lib()
    rooms = [fixed_rooms.derive(r, groups, lib) for r in rooms]
    errors = fixed_rooms.check(rooms, groups, lib)
    if errors:
        raise SaveError(errors)
    _write_family(family, rooms)
    return {"ok": True, "family": family, "rooms": len(rooms),
            "hash": _file_hash(path)}


# ------------------------------------------------------------- regenerating

# how many seeds "regenerate this room" composes a recipe under
REGEN_SEEDS = 8


def regenerate(room_id):
    """POST /api/rooms/regenerate: candidate re-laid-out rooms for one room
    — its recipe composed at its clearance and style under the generator's
    own rules (the seed script's compose_recipe, with the roomy sibling
    setting the grand cap), seeds 1 to REGEN_SEEDS. Every candidate stays in
    the room's size band, none equals a shipped room of the family (or
    another candidate) after any turn or mirror, and each carries the
    description and wealth a full generation would write. Layouts only: the
    page merges the pick into the room, keeping its id and edited fields."""
    _need_modules()
    g = _generate_rooms_mod()
    room = _find_room(room_id)
    fam, clearance, style = room.get("family"), room.get("clearance"), \
        room.get("style")
    data = room_groups.load(_groups_dir())
    recipe = data["recipes"].get(room.get("recipe"))
    if not isinstance(recipe, dict):
        raise LookupError(f"no recipe {room.get('recipe')!r}")
    roomy = None
    # a hand recipe of a family with its own band table composes with the
    # band pinned (the generator's own rule), so its candidates are composed
    # that way too; every other recipe composes as before, band unpinned
    band = (room.get("sizeBand")
            if recipe.get("source") == "hand"
            and fixed_rooms.family_bands(fam, _lib()) else None)
    if clearance == "grand" and fam in room_composer.PRIVATE_FAMILIES:
        sibs, _ = g.compose_recipe(recipe, fam, data, "roomy", style, 1,
                                   size_band=band)
        roomy = sibs[0] if sibs else None
    seen = {g.canonical(r) for r in fixed_rooms.load(_rooms_dir())
            if isinstance(r, dict) and r.get("family") == fam}
    out = []
    for seed in range(1, REGEN_SEEDS + 1):
        cands, _reason = g.compose_recipe(recipe, fam, data, clearance,
                                          style, seed, roomy=roomy,
                                          size_band=band)
        for cand in cands:
            key = g.canonical(cand)
            if key in seen or cand.get("sizeBand") != room.get("sizeBand"):
                continue
            seen.add(key)
            elite = (cand.get("clearance") == "grand"
                     and g.uses_elite_piece(cand, data["groups"]))
            cand["wealth"] = (["elite"] if elite
                              else g.wealth_for(clearance, style))
            cand["description"] = g.describe(cand)
            # a placeholder id unique in the list: the page replaces the
            # room's layout, never its id
            cand["id"] = f"{fam}.{cand['sizeBand']}.draft{len(out)}." \
                         f"{clearance}.{style}"
            out.append(cand)
    return {"family": fam, "room": room_id, "candidates": out}


# a family regeneration: one job at a time, like worldgen_editor's
_job = None
_lock = threading.Lock()


class JobBusyError(Exception):
    """A family regeneration is already running; one at a time."""


def job():
    """The running or finished family regeneration as the page polls it
    (None when there has been none): status, family, error, and once done
    the diff by id with the before and after rooms. The generated rooms
    stay server-side — nothing is written until apply_regen."""
    with _lock:
        if not _job:
            return None
        return {k: v for k, v in _job.items() if k != "rooms"}


def start_regen_family(family):
    """POST /api/rooms/regenerate/family: regenerate one family in a
    background thread through the generator's own generate() (hand rooms
    kept, edited fields preserved), one job at a time. The diff lands in
    job(); apply writes it, discard drops it."""
    _need_modules()
    global _job
    path = _family_path(family)
    if not os.path.isfile(path):
        raise LookupError(f"no rooms file for family {family!r}")
    with _lock:
        if _job and _job.get("status") == "running":
            raise JobBusyError(f"already regenerating {_job.get('family')!r}; "
                               "wait for it or discard it")
        j = {"status": "running", "family": family, "hash": _file_hash(path)}
        _job = j
    threading.Thread(target=_run_regen, args=(j,), daemon=True).start()
    return {k: v for k, v in j.items()}


def _run_regen(j):
    """The job thread: generate the family, keep the diff. SystemExit is
    caught too — generate() refuses to return rooms that fail its checker."""
    try:
        g = _generate_rooms_mod()
        out, _drops = g.generate([j["family"]], rooms_dir=_rooms_dir(),
                                 groups_dir=_groups_dir(),
                                 lib_dir=str(LIBRARY_DIR))
        old = [{k: v for k, v in r.items() if not k.startswith("_")}
               for r in fixed_rooms.load(_rooms_dir())
               if r.get("_file") == j["family"] + ".json"]
        with _lock:
            if _job is not j:
                return                          # discarded meanwhile
            j.update({"status": "done", "diff": _diff(old, out[j["family"]]),
                      "rooms": out[j["family"]]})
    except (Exception, SystemExit) as e:
        with _lock:
            if _job is j:
                j.update({"status": "error", "error": str(e)})


def _diff(old, new):
    """What a regeneration did, by id: added, removed and changed rooms,
    each entry carrying the before and after rooms (None where absent)."""
    oi = {r.get("id"): r for r in old}
    ni = {r.get("id"): r for r in new}
    out = []
    for rid in sorted(set(oi) | set(ni)):
        a, b = oi.get(rid), ni.get(rid)
        if a is None:
            out.append({"op": "added", "id": rid, "before": None, "after": b})
        elif b is None:
            out.append({"op": "removed", "id": rid, "before": a, "after": None})
        elif a != b:
            out.append({"op": "changed", "id": rid, "before": a, "after": b})
    return out


def apply_regen():
    """POST /api/rooms/regenerate/apply: write the finished job's family
    through the same save path — checker first, backup, atomic write — and
    clear the job. Refused when the file changed on disk since the job ran."""
    _need_modules()
    global _job
    with _lock:
        if not _job or _job.get("status") != "done":
            raise ValueError("no finished family regeneration to apply")
        family, rooms, hash_ = _job["family"], _job["rooms"], _job["hash"]
    if _file_hash(_family_path(family)) != hash_:
        raise SaveError([f"{family}.json changed on disk since the "
                         "regeneration started: reload the family and "
                         "regenerate again"])
    errors = fixed_rooms.check(rooms, room_groups.load(_groups_dir()), _lib())
    if errors:
        raise SaveError(errors)
    _write_family(family, rooms)
    with _lock:
        if _job and _job.get("family") == family:
            _job = None
    return {"ok": True, "family": family, "rooms": len(rooms)}


def discard_regen():
    """POST /api/rooms/regenerate/discard: throw the job away; nothing was
    written. A running job stops mattering the moment it is discarded."""
    global _job
    with _lock:
        if not _job:
            raise ValueError("no family regeneration to discard")
        _job = None
    return {"ok": True}


# ---------------------------------------------------------------- sprites

def sprite(band, object_id):
    """(webp bytes, "image/webp") for a shipped sprite. Both arguments are
    validated against the band's own index.json keys, so ``..``, slashes and
    unknown ids are all refused."""
    _need_modules()
    if not isinstance(object_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+",
                                                          object_id or ""):
        raise ValueError(f"bad object id {object_id!r}")
    index = library_art.load_index(band, root=_sprites_dir())
    if not index:
        raise ValueError(f"unknown art band {band!r}")
    if object_id not in index:
        raise ValueError(f"no sprite {object_id!r} in band {band!r}")
    path = library_art.sprite_path(band, object_id, root=_sprites_dir())
    if not os.path.isfile(path):
        raise ValueError(f"no sprite file for {object_id!r} in band {band!r}")
    with open(path, "rb") as fh:
        return fh.read(), "image/webp"


def _need_modules():
    if not MODULES:
        raise ValueError("the world generator's modules are unavailable: "
                         + getattr(sys.modules[__name__], "IMPORT_ERROR", ""))
