"""Room library build step 4: the library in the model phases.

With the room library on (the default), P1 also gives the setting's band and
each building's wealth and condition; P3 picks a building recipe (a suite) and
each room's purpose instead of writing furniture, or is skipped when the
building's kind matches exactly one suite; and code expands every room into
ordinary furniture lines and templates before plan.json is written. So a plan
made with the library is a plain plan: a re-roll never reads the library, and
the layout code places it like any other. Unit buildings keep the old P3.

Everything here is called from ``phases.run_phases`` when ``library`` is true.
"""
import random
import re

from . import library as lib_mod
from .library_rooms import Templates, compile_room

SLEEP_FAMILIES = ("bedroom", "bedroom.master", "dormitory", "hut")
BAND_WALL = {"medieval": "wood", "industrial": "brick", "modern": "brick", "scifi": "steel"}
BAND_GROUND = {"medieval": "packed earth", "industrial": "floorboards", "modern": "tiles",
               "scifi": "deck plating"}
SPARE_PURPOSES = ("guest_room",)    # beds for travellers, not residents
SHARE_BAND = {"small": "small", "medium": "medium", "large": "large"}
SIZE_ORDER = ("tiny", "small", "medium", "large")
# the building packer splits one footprint into at most five rooms before it
# starts dropping everything (measured: 5 rooms place all 33 pieces of an inn,
# 6 rooms drop 34 of 40); more rooms belong in a unit building
MAX_ROOMS = 5


def load():
    """The shipped library (a fresh load each run keeps tests independent)."""
    return lib_mod.load(lib_mod.LIB_DIR)


# ------------------------------------------------------------------ P1

def band_of(lib, setting):
    """The setting's band: P1's own when it gave a valid one, else read from
    its genre, era and technology words through the alias list."""
    s = setting or {}
    if s.get("band") in lib.bands:
        return s["band"]
    text = " ".join(str(s.get(k, "")) for k in ("genre", "era", "technology")).lower()
    aliases = lib.vocab.get("bandAliases", {})
    for word in sorted(aliases, key=len, reverse=True):
        if word in text:
            return aliases[word]
    for band in lib.bands:
        if band in text:
            return band
    return "medieval"


def sanitize_p1(p1, lib, log):
    """Default the library fields P1 adds: setting.band and genre, and each
    building's wealth and condition."""
    s = p1.setdefault("setting", {})
    band = band_of(lib, s)
    if s.get("band") != band:
        log.append(("P1 setting", f"band {s.get('band')!r} -> {band!r}"))
        s["band"] = band
    if not isinstance(s.get("genre"), str) or not s["genre"].strip():
        s["genre"] = band
    for z in p1.get("zones") or []:
        for b in z.get("buildings") or []:
            if b.get("wealth") not in lib.tiers:
                if b.get("wealth") is not None:
                    log.append((f"building {b.get('name')}", f"wealth {b['wealth']!r} -> 'modest'"))
                b["wealth"] = "modest"
            if b.get("condition") not in lib.vocab["conditions"]:
                if b.get("condition") is not None:
                    log.append((f"building {b.get('name')}",
                                f"condition {b['condition']!r} -> 'kept'"))
                b["condition"] = "kept"
    return p1


# ------------------------------------------------------------------ suites

def _kind_words(kind):
    k = str(kind or "").lower().strip()
    return {k, k.split()[-1]} if k else set()


def suite_candidates(lib, b, band):
    """Suites that suit a P1 building: its band, size class and residents."""
    r = b.get("residents") if isinstance(b.get("residents"), int) else 0
    out = []
    for s in sorted(lib.suites.values(), key=lambda s: s["id"]):
        if band not in s.get("bands", []):
            continue
        if b.get("sizeClass") and b["sizeClass"] not in s.get("sizeClasses", []):
            continue
        lo, hi = s.get("residents", [0, 0])
        if r and not lo <= r <= max(hi, lo):
            continue
        out.append(s)
    return out


def suite_by_kind(lib, b, band):
    """The one suite whose kinds name this building's kind, or None when
    none or several do (then P3 chooses)."""
    words = _kind_words(b.get("kind"))
    hits = [s for s in suite_candidates(lib, b, band)
            if words & {k.lower() for k in s.get("kinds", [])}]
    return hits[0] if len(hits) == 1 else None


def can_skip_p3(b, compound_parts, notes=""):
    """A building that can take a suite as it is: no units, not part of a
    compound, and not named in the user's own instructions."""
    if b.get("units") or b.get("name") in compound_parts:
        return False
    return not (notes and str(b.get("name", "")).lower() in notes.lower())


def trim_rooms(lib, design, b, limit=MAX_ROOMS):
    """Cut a design to ``limit`` rooms: the entrance room, then rooms for the
    sleepers (a master bedroom per couple, bedrooms for the rest), then the
    others in order. Connections to cut rooms go, and a room left without a
    way in is joined to the entrance room."""
    rooms = design.get("rooms") or []
    if len(rooms) <= limit:
        return design
    entry = (design.get("entrance") or {}).get("room") or rooms[0]["name"]
    residents = b.get("residents") if isinstance(b.get("residents"), int) else 0
    couples = b.get("couples") if isinstance(b.get("couples"), int) else 0
    fam = {r["name"]: lib.family_of(r.get("use")) for r in rooms}
    order = [r["name"] for r in rooms if r["name"] == entry]
    masters = [r["name"] for r in rooms if fam[r["name"]] == "bedroom.master"][:couples]
    singles = residents - 2 * len(masters)
    others = [r["name"] for r in rooms if fam[r["name"]] in ("bedroom", "dormitory", "hut")
              and r.get("use") not in SPARE_PURPOSES][:1 if singles > 0 else 0]
    for n in masters + others + [r["name"] for r in rooms]:
        if n not in order:
            order.append(n)
    keep = set(order[:limit])
    design["rooms"] = [r for r in rooms if r["name"] in keep]
    design["connections"] = [c for c in design.get("connections") or []
                             if c[0] in keep and c[1] in keep]
    linked = {entry}
    grew = True
    while grew:
        grew = False
        for a, c in design["connections"]:
            if (a in linked) != (c in linked):
                linked |= {a, c}
                grew = True
    for r in design["rooms"]:
        if r["name"] not in linked:
            design["connections"].append([entry, r["name"]])
            linked.add(r["name"])
    return design


def design_from_suite(suite, b, band, rng):
    """A P3-shaped design made from a suite, for a building that skips P3."""
    rooms = [{"name": r["name"], "share": r["share"], "use": r["purpose"],
              "purpose": r["purpose"].replace("_", " ")} for r in suite["rooms"]]
    return {"name": b["name"], "wall": BAND_WALL.get(band, "wood"),
            "ground": BAND_GROUND.get(band, "wood"),
            "rooms": rooms,
            "connections": [list(c) for c in suite.get("connections", [])],
            "entrance": {"room": suite["entrance"]["room"],
                         "side": rng.choice(("north", "south", "east", "west"))},
            "furniture": [], "yard": None, "suite": suite["id"]}


def suite_lines(lib, b, band):
    """P3's list of fitting suites: ``id | Room (purpose, share); ...``."""
    lines = []
    for s in suite_candidates(lib, b, band)[:12]:
        rooms = "; ".join(f"{r['name']} ({r['purpose']}, {r['share']})" for r in s["rooms"])
        lines.append(f"- {s['id']} | {rooms}")
    return "\n".join(lines) or "(none fits; design the rooms yourself)"


def purpose_line(lib):
    return ", ".join(sorted(lib.vocab["purposes"]))


def units_line(b):
    """P3's line on a unit building: shared rooms plus ONE copy, by purpose."""
    u = b.get("units")
    if not isinstance(u, dict) or not u.get("count"):
        return "none"
    per = u.get("residents") if isinstance(u.get("residents"), int) else 0
    who = f", {per} resident(s) in each" if per else ""
    return (f"THIS BUILDING REPEATS UNITS: {u['count']} copies of one "
            f"'{u.get('name', 'Apartment')}'{who}. Give the building's SHARED rooms in "
            "\"rooms\" and ONE copy in \"unit\": {\"rooms\", \"connections\", \"entrance\"}, "
            "its rooms with a \"use\" like any other. Code stamps every copy, furnishes it "
            "with a bed per resident and gives each its own door.")


def default_unit(b):
    """A unit design for a unit building whose P3 reply gave none: one room
    whose purpose fits the building (an inn's guest room, a ship's cabin)."""
    u = b.get("units") or {}
    name = str(u.get("name") or "Room")
    words = f"{b.get('kind', '')} {name}".lower()
    if any(w in words for w in ("inn", "hotel", "motel", "tavern", "lodg", "guest")):
        use = "guest_room"
    elif any(w in words for w in ("cabin", "berth", "bunk", "crew", "barrack")):
        use = "crew_quarters"
    elif any(w in words for w in ("cell", "brig")):
        use = "cell"
    elif any(w in words for w in ("ward", "patient")):
        use = "ward"
    else:
        use = "bedroom"
    return {"rooms": [{"name": name, "share": "medium", "use": use, "purpose": name.lower()}],
            "connections": [], "entrance": {"room": name, "side": "south"}, "furniture": []}


# ------------------------------------------------------------------ P3 reply

def check_p3(d, building_name, lib, units=None):
    """Errors in a library P3 reply (rooms with purposes, no furniture). A
    unit building's "unit" copy is checked the same way when it is given; a
    missing one gets ``default_unit``."""
    errors = []
    if units and isinstance(d, dict) and isinstance(d.get("unit"), dict) \
            and d["unit"].get("rooms"):
        for e in check_p3(dict(d["unit"]), building_name, lib):
            errors.append("unit: " + e)
    return errors + _check_rooms(d, building_name, lib)


def _check_rooms(d, building_name, lib):
    errors = []
    if not isinstance(d, dict):
        return ["reply is not a JSON object"]
    suite = d.get("suite")
    if suite not in (None, "", "none") and suite not in lib.suites:
        errors.append(f"suite {suite!r} is not one of the listed suites")
    rooms = d.get("rooms")
    if not rooms and suite in lib.suites:
        return errors
    if not isinstance(rooms, list) or not 1 <= len(rooms) <= MAX_ROOMS:
        return errors + [f"rooms: 1 to {MAX_ROOMS} rooms, each {{name, share, use, purpose}}"]
    names = []
    for r in rooms:
        if not isinstance(r, dict) or not isinstance(r.get("name"), str) or not r["name"].strip():
            errors.append("each room needs a name")
            continue
        if r["name"] in names:
            errors.append(f"room {r['name']!r} repeats")
        names.append(r["name"])
        if r.get("use") not in lib.vocab["purposes"]:
            errors.append(f"room {r['name']!r}: use {r.get('use')!r} is not in the purpose list")
    for c in d.get("connections") or []:
        if not (isinstance(c, list) and len(c) == 2 and c[0] in names and c[1] in names):
            errors.append(f"connection {c} names a room that isn't in rooms")
    e = d.get("entrance") if isinstance(d.get("entrance"), dict) else {}
    if e.get("room") not in names:
        errors.append("entrance.room must be one of the rooms")
    return errors


def fill_from_suite(d, lib, b, band, rng):
    """A reply that names a suite but leaves out its rooms takes the suite's."""
    suite = lib.suites.get(d.get("suite"))
    if suite and not d.get("rooms"):
        base = trim_rooms(lib, design_from_suite(suite, b, band, rng), b)
        for k in ("rooms", "connections", "entrance"):
            d[k] = base[k]
    return d


# ------------------------------------------------------------------ expansion

# storage-furniture words a pool name may trail with ("Kitchen shelf" for a
# kitchen pool): ignored when a pool name is matched against a room purpose
ORDER_WORDS = ("shelf", "shelves", "sideboard", "cupboard", "chest", "cabinet",
               "locker", "crate", "box", "barrel")

_WORD_RE = re.compile(r"[^a-z0-9]+")


def _words(text):
    return [w for w in _WORD_RE.split(str(text or "").lower()) if w]


def pool_for_purpose(purpose, pools):
    """The plan pool a room of this purpose draws from: the pool whose name
    matches the purpose, case-insensitively, ignoring order words ("Kitchen
    shelf" matches "kitchen") — an exact-name match first, else the
    alphabetical first of the names containing the purpose as whole words
    ("Bakehouse Store" holds "bakehouse", "Workshop" does not hold "shop").
    None when no pool matches, so the line keeps no pool."""
    pwords = _words(purpose)
    if not pwords:
        return None
    exact, contains = [], []
    for name in sorted((str(n) for n in pools), key=lambda n: (n.lower(), n)):
        ws = _words(name)
        trimmed = list(ws)
        while trimmed and trimmed[-1] in ORDER_WORDS:
            trimmed.pop()
        if trimmed == pwords:
            exact.append(name)
        elif any(ws[i:i + len(pwords)] == pwords
                 for i in range(len(ws) - len(pwords) + 1)):
            contains.append(name)
    if exact:
        return exact[0]
    return contains[0] if contains else None


def _room_band(lib, family, share):
    """The size band a room's share asks for, nearest one its family has."""
    want = SHARE_BAND.get(share, "medium")
    have = {b for l in lib.layouts_for(family) for b in l["sizeBands"]}
    if not have:
        return None
    return min(have, key=lambda b: (abs(SIZE_ORDER.index(b) - SIZE_ORDER.index(want)),
                                    SIZE_ORDER.index(b)))


def _sleepers(lib, rooms, residents, couples):
    """{room name: (singles, couples)}: one couple to each master bedroom,
    the other residents shared over the single-bed rooms, a spare bed or two
    in each guest room."""
    fam = {r["name"]: lib.family_of(r.get("use")) for r in rooms}
    masters = [r["name"] for r in rooms if fam[r["name"]] == "bedroom.master"]
    singles_rooms = [r["name"] for r in rooms
                     if fam[r["name"]] in ("bedroom", "dormitory", "hut")
                     and r.get("use") not in SPARE_PURPOSES]
    out = {r["name"]: (0, 0) for r in rooms}
    placed_couples = min(couples, len(masters))
    for name in masters[:placed_couples]:
        out[name] = (0, 1)
    left = max(0, residents - 2 * placed_couples)
    if singles_rooms:
        for i in range(left):
            name = singles_rooms[i % len(singles_rooms)]
            s, c = out[name]
            out[name] = (s + 1, c)
    for r in rooms:
        if r.get("use") in SPARE_PURPOSES:
            out[r["name"]] = (2 if r.get("share") == "large" else 1, 0)
    return out


def ensure_sleep_room(design, b, lib, log):
    """A home whose rooms have nowhere to sleep gets a bedroom off its
    entrance room, so the residents P1 promised have beds."""
    residents = b.get("residents") if isinstance(b.get("residents"), int) else 0
    if residents <= 0:
        return
    if any(lib.family_of(r.get("use")) in SLEEP_FAMILIES for r in design["rooms"]):
        return
    couples = b.get("couples") if isinstance(b.get("couples"), int) else 0
    use = "master_bedroom" if couples and residents <= 2 else "bedroom"
    name = "Bedroom"
    while any(r["name"] == name for r in design["rooms"]):
        name += " 2"
    design["rooms"].append({"name": name, "share": "medium", "use": use, "purpose": "sleeping"})
    entry = (design.get("entrance") or {}).get("room") or design["rooms"][0]["name"]
    design.setdefault("connections", []).append([entry, name])
    log.append((f"building {b['name']}", f"added {name}: {residents} residents had no bedroom"))


def expand_unit(lib, registry, design, b, band, genre, seed, log, pools=()):
    """Furnish a unit building's one copy from the library: its rooms by
    purpose, with the copy's residents as single sleepers."""
    unit = design.get("unit")
    if not isinstance(unit, dict) or not unit.get("rooms"):
        design["unit"] = unit = default_unit(b)
    u = b.get("units") or {}
    per = u.get("residents") if isinstance(u.get("residents"), int) else 0
    copy = {"name": f"{b['name']} unit", "residents": per, "couples": 0,
            "wealth": b.get("wealth"), "condition": b.get("condition")}
    unit.setdefault("furniture", [])
    expand_design(lib, registry, unit, copy, band, genre, seed, log,
                  ensure_beds=per > 0, pools=pools)
    return design


def drops_at_layout(design, b, registry):
    """How many pieces the building packer would drop from this design: the
    layout code's own measure (it grows a building to the 28x22 cap, splits
    rooms into annexes, then drops pieces). Unit buildings size by their
    copies and never drop this way, so they count 0."""
    from .layout_building import _resolve_plan
    from .library_rooms import object_templates
    from .model import _parse_building
    if b.get("units"):
        return 0
    bd = _parse_building(dict(b), {b["name"]: design})
    return len(_resolve_plan(bd, object_templates(registry))[4])


def expand_fitting(lib, registry, design, b, band, genre, seed, log, ensure_beds=True,
                   pools=()):
    """``expand_design``, then again compactly (each room's smallest layout,
    no optional pieces) when the full version would overflow the building."""
    keep = list(design.get("furniture") or [])
    expand_design(lib, registry, design, b, band, genre, seed, log, ensure_beds,
                  pools=pools)
    lost = drops_at_layout(design, b, registry)
    if lost:
        after = lost
        n = len(design["rooms"])
        while True:
            design["furniture"] = list(keep)
            expand_design(lib, registry, design, b, band, genre, seed, log, ensure_beds=False,
                          compact=True, pools=pools)
            after = drops_at_layout(design, b, registry)
            if not after or len(design["rooms"]) <= 2:
                break
            # still over: give up a room (the least needed, by trim_rooms' order)
            trim_rooms(lib, design, b, limit=len(design["rooms"]) - 1)
        cut = n - len(design["rooms"])
        log.append((f"building {b['name']}",
                    f"furnished compactly: the full rooms would drop {lost} piece(s) at the "
                    f"building cap" + (f"; {cut} room(s) left out" if cut else "")
                    + (f"; {after} still drop" if after else "")))
    return design


def used_templates(designs):
    """Template names any design's furniture (unit copies included) uses."""
    used = set()
    for d in designs:
        for f in (d.get("furniture") or []) + ((d.get("unit") or {}).get("furniture") or []):
            used.add(f.get("template"))
    return used


def expand_design(lib, registry, design, b, band, genre, seed, log, ensure_beds=True,
                  compact=False, pools=()):
    """Turn a library design's rooms into furniture lines (appended to
    ``design["furniture"]``) and record each room's layout. Rooms without a
    library ``use`` keep whatever furniture the design already has. A line
    whose object is a container gets the room's purpose pool from ``pools``
    (the plan's pool names), so it draws a starting inventory."""
    rng = random.Random(f"{seed}|library|{b['name']}")
    pool_names = {str(n) for n in pools if n}
    if ensure_beds:
        ensure_sleep_room(design, b, lib, log)
    residents = b.get("residents") if isinstance(b.get("residents"), int) else 0
    couples = b.get("couples") if isinstance(b.get("couples"), int) else 0
    sleepers = _sleepers(lib, design["rooms"], residents, couples)
    tier = b.get("wealth") if b.get("wealth") in lib.tiers else "modest"
    cond = b.get("condition") if b.get("condition") in lib.vocab["conditions"] else "kept"
    overrides = design.get("wealth") if isinstance(design.get("wealth"), dict) else {}
    used = {}
    for r in design["rooms"]:
        use = r.get("use")
        fam = lib.family_of(use)
        if fam is None:
            continue
        sb = _room_band(lib, fam, "small" if compact else r.get("share"))
        pool = [l for l in sorted(lib.layouts_for(fam), key=lambda l: l["id"])
                if sb in l["sizeBands"]]
        if not pool:
            log.append((f"building {b['name']}", f"room {r['name']}: no {fam} layout"))
            continue
        lay = rng.choice(pool)
        room_tier = overrides.get(r["name"]) if overrides.get(r["name"]) in lib.tiers else tier
        singles, cpl = sleepers.get(r["name"], (0, 0))
        comp = compile_room(lib, registry, use, tuple(lay["minInterior"]), band, room_tier, cond,
                            rng, singles=singles, couples=cpl, room=r["name"], grow=False,
                            genre=genre, layout=lay, optional=not compact)
        for g in comp.gaps:
            log.append((f"building {b['name']}", f"room {r['name']}: {g}"))
        for f in comp.furniture:
            line = {"template": f.template, "room": f.room, "count": f.count, "hint": f.hint}
            if pool_names and registry.is_container(f.template):
                pool = pool_for_purpose(use, pool_names)
                if pool:
                    line["lootPool"] = pool
            design.setdefault("furniture", []).append(line)
        used[r["name"]] = lay["id"]
        if not r.get("purpose"):
            r["purpose"] = use.replace("_", " ")
    design["libraryLayouts"] = used
    return design


def registry_for(lib, seed, taken):
    """The world's library templates, named apart from P2's own."""
    return Templates(lib, seed, taken=taken)
