"""The room library behind the Scenario Editor's Rooms tab (rl-04a): the
generator's fixed rooms, groups and sprites, read only — no endpoint here
writes any file. The generator in ../world-generator stays standalone: it is
only imported (never changed), like worldgen_editor.py.

The library folder is the module variable LIBRARY_DIR (the shipped
``../world-generator/library``); tests point it at a temp copy. When the
generator's modules cannot be imported, or the library has no rooms,
``present()`` is false, the Rooms tab stays hidden and the editor works as
today.

  meta()                    -> {present, families, roles, bands, ...}
  family(family)            -> the family's rooms, each with its errors
  room(id, turn, mirror)    -> one room turned and mirrored (preview only)
  groups(family)            -> the family's recipes, groups and luxury pool
  look(id, band, turn, mirror) -> per piece the object and sprite the world
                               generator would place, and the sprite's turn
  sprite(band, object)      -> (webp bytes, content type)
"""
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORLDGEN_DIR = HERE.parent / "world-generator"
if str(WORLDGEN_DIR) not in sys.path:
    sys.path.insert(0, str(WORLDGEN_DIR))

# The shipped library; tests point this at a temp copy. Everything below
# takes the folder from here, so a swapped library is used throughout.
LIBRARY_DIR = WORLDGEN_DIR / "library"

try:
    from worldgen import fixed_rooms, library as lib_mod, library_art, room_groups
    from worldgen.library_rooms import purpose_for_family
    from worldgen.room_palette import DEFAULT_ROLE, ROLES, css as role_css
    MODULES = True
except Exception as _e:                                    # pragma: no cover
    fixed_rooms = lib_mod = library_art = room_groups = None
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
            "tiers": list(_lib().tiers) if MODULES else []}


def _bands():
    """The item-art bands that ship a sprite index (sorted)."""
    return sorted(os.path.basename(os.path.dirname(p)) for p in _sprite_indexes())


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
    return {"family": family, "rooms": list(by_id.values()), "errors": loose}


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
    maths. Preview only: nothing is stored."""
    _need_modules()
    t, m = _turn_mirror(turn, mirror)
    return fixed_rooms.rotate(_find_room(room_id), t, m)


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
    """The family's recipes as loaded, every group those recipes name with
    its pieces, and the family's luxury pool entries with their size bands
    and luxury kinds."""
    _need_modules()
    data = room_groups.load(_groups_dir())
    recipes = sorted((_plain(r) for r in data["recipes"].values()
                      if r.get("family") == family),
                     key=lambda r: str(r.get("layout")))
    named = {e.get("group") for r in recipes for e in (r.get("groups") or [])
             if isinstance(e, dict)}
    out_groups = {gid: _plain(data["groups"][gid]) for gid in sorted(named, key=str)
                  if isinstance(data["groups"].get(gid), dict)}
    pool = []
    for e in data["pools"].get(family) or []:
        entry = _plain(e)
        g = data["groups"].get(entry.get("group")) or {}
        entry["kind"] = list(room_groups.luxury_kinds(g))
        pool.append(entry)
    return {"family": family, "recipes": recipes, "groups": out_groups,
            "pool": pool}


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
