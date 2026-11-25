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
from .model import kind_phrases_hit

SLEEP_FAMILIES = ("bedroom", "bedroom.master", "dormitory", "hut")
BAND_WALL = {"medieval": "wood", "industrial": "brick", "modern": "brick", "scifi": "steel"}
BAND_GROUND = {"medieval": "packed earth", "industrial": "floorboards", "modern": "tiles",
               "scifi": "deck plating"}
SPARE_PURPOSES = ("guest_room",)    # beds for travellers, not residents
# purposes whose rooms sleep guests and lodgers rather than residents: with
# none assigned they still take the family's usual occupancy, so the beds
# are always furnished (design 8.1g)
GUEST_PURPOSES = ("dormitory", "guest_room", "barracks", "crew_quarters",
                  "servants_room")
# the wing purposes that serve the building rather than the household
# (rl-12): the parts standing for them sleep in the staff's own wing
SERVICE_PURPOSES = ("servants", "kitchen_storage", "stables")
SHARE_BAND = {"small": "small", "medium": "medium", "large": "large"}
# kinds whose upper storey is a hayloft, not a bedroom floor (design 8.1g):
# the "hayloft" purpose (barn family, purposeFit keeps it to hay storage)
LOFT_KINDS = ("barn", "byre", "stable", "stables", "livery")
# the families of the farm families' buildings: a building or wing of only
# these families never gains a bed, a bedroom or a sleep room — its residents
# sleep in the farmhouse. The sci-fi vat-farm room is the greenhouse family's
# recipe and the gene-bank room the granary family's, so each is covered by
# its family here rather than by its name
FARM_FAMILIES = ("barn", "stable", "dairy", "granary", "pigsty", "henhouse",
                 "greenhouse")
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
    none or several do (then P3 chooses). When several match, the most
    specific one wins — the matched phrase with the most words ("dairy
    farm" the farm suite over the farmhouse's "farm"), like
    ``building_by_kind``; a tie names no winner."""
    words = _kind_words(b.get("kind"))
    best, best_len, tie = None, 0, False
    for s in suite_candidates(lib, b, band):
        hit = max((len(k.split()) for k in s.get("kinds", [])
                   if isinstance(k, str) and k.lower() in words), default=0)
        if not hit:
            continue
        if hit > best_len:
            best, best_len, tie = s, hit, False
        elif hit == best_len:
            tie = True
    return None if tie else best


def building_by_kind(lib, kind, band):
    """The building recipe whose kinds name this kind: whole-word matches on
    the kind and its last word, like ``suite_by_kind``. When several recipes
    match, the most specific one wins — the matched phrase with the most words
    ("coaching inn" beats "inn"); a tie names no winner. None when nothing
    matches, and then the building stays a flat suite."""
    words = _kind_words(kind)
    best, best_len, tie = None, 0, False
    for r in sorted(lib.buildings.values(), key=lambda r: str(r.get("id"))):
        if band not in (r.get("bands") or []):
            continue
        hit = max((len(k.split()) for k in r.get("kinds") or []
                   if isinstance(k, str) and k.lower() in words), default=0)
        if not hit:
            continue
        if hit > best_len:
            best, best_len, tie = r, hit, False
        elif hit == best_len:
            tie = True
    return None if tie else best


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


# --------------------------------------------------------- wings (rl-10, 8.3)
# A building recipe's wings become part designs: the rooms the wing lists,
# split over its floors, with the P1 building the wing stands for flowing
# through (its residents and condition, and its own room names where a wing
# room shares their purpose family)


def _stepped_tier(lib, tier, offset):
    """The tier ``offset`` steps from ``tier`` — down for a negative offset,
    never past either end of the ladder."""
    tiers = lib.tiers
    i = tiers.index(tier) if tier in tiers else 0
    return tiers[max(0, min(i + offset, len(tiers) - 1))]


def wing_wealth_tier(lib, wing, tier):
    """The tier a wing furnishes at (design 8.3): the tier its ``wealth``
    names, else the building's stepped by its offset — a wing that keeps
    quiet steps with its purpose's default (servants two down, stables two
    down, barracks and kitchen storage one down)."""
    spec = lib_mod.wing_wealth(wing)
    if spec is None or spec == "building":
        return tier
    if isinstance(spec, str):
        return spec if spec in lib.tiers else tier
    return _stepped_tier(lib, tier, int(spec))


def wing_floor_rooms(lib, wing, storeys):
    """The wing's rooms over its floors, {floor: [room dicts]}: the ground
    keeps the entrance room and every room that is neither a bedchamber nor
    the hayloft; the bedchambers fill the upper storeys from storey 2 up (the
    bigger share below), and the hayloft sits on the top one, under the roof.
    The entrance room's last-connected bedchamber stays down when it would
    otherwise be alone there (the keepers by the door, the guests upstairs);
    a one-storey wing keeps every room it lists; an upper storey left with
    nothing takes a chamber, or a store room when the wing sleeps nobody."""
    rooms = list(wing.get("rooms") or [])
    if storeys <= 1 or not rooms:
        return {1: list(rooms)}
    entry = (wing.get("entrance") or {}).get("room") or rooms[0]["name"]
    fam = {r["name"]: lib.family_of(r.get("purpose")) for r in rooms}
    beds = [r for r in rooms if fam[r["name"]] in SLEEP_FAMILIES]
    lofts = [r for r in rooms if r.get("purpose") == "hayloft"]
    down = {id(r) for r in rooms if r not in beds and r not in lofts}
    entry_room = next((r for r in rooms if r["name"] == entry), rooms[0])
    down.add(id(entry_room))          # the wing's door opens into it
    if len(down) == 1 and beds:
        # its own keeper stays by the door: the last bedchamber the entrance
        # room connects to (else the last one listed)
        adj = {c[0] if c[1] == entry else c[1] for c in wing.get("connections") or []}
        pick = next((r for r in reversed(beds) if r["name"] in adj), None) \
            or (beds[-1] if beds else None)
        if pick is not None and id(pick) not in down:
            down.add(id(pick))
    ground = [r for r in rooms if id(r) in down]
    up = [r for r in rooms if id(r) not in down]
    up_beds = [r for r in up if fam[r["name"]] in SLEEP_FAMILIES]
    floors = {1: ground}
    n = storeys - 1
    counts = [len(up_beds) // n + (1 if i < len(up_beds) % n else 0)
              for i in range(n)]
    i = 0
    for f in range(2, storeys + 1):
        floors[f] = up_beds[i:i + counts[f - 2]]
        i += counts[f - 2]
    floors[storeys].extend(r for r in up if r not in up_beds)   # the lofts, on top
    for f in range(2, storeys + 1):
        if floors[f]:
            continue
        use = "bedroom" if wing.get("sleeps") != "none" else "storage"
        base = "Chamber" if use == "bedroom" else "Store room"
        name, k = base, 2
        while any(r["name"] == name for fl in floors.values() for r in fl):
            name, k = f"{base} {k}", k + 1
        floors[f] = [{"name": name, "share": "small", "purpose": use}]
    return floors


def wing_design(lib, wing, name, b, band, cap, kind=""):
    """The BuildingDesign of one wing recipe (rl-10): rooms by purpose and
    share from the wing, split over its floors within ``cap`` (the height
    rules' cap for the building's kind where it stands, and the four the
    assembler lays), its wealth the P1 building ``b`` it stands for with the
    wing's design-8.3 offset applied, its residents and condition ``b``'s own.
    A wing room whose purpose family matches a room of ``b`` takes ``b``'s
    name for it (each of ``b``'s names once), so a P1 part keeps its named
    rooms where the recipe has a wing for them."""
    from .model import BuildingDesign, RoomSpec, UpperStorey
    storeys = max(1, min(int(wing.get("storeys") or 1), cap, 4))
    floors = wing_floor_rooms(lib, wing, storeys)

    # the reconciliation, once: {wing room name -> the P1 room's name}
    rename, taken = {}, set()
    if b is not None:
        for f in sorted(floors):
            for r in floors[f]:
                fam = lib.family_of(r.get("purpose"))
                if fam is None:
                    continue
                named = next((o.name for o in b.rooms
                              if o.name not in taken
                              and lib.family_of(o.use) == fam), None)
                if named is not None:
                    taken.add(named)
                    rename[r["name"]] = named

    # the wing's room names unique over all its floors (rl-19): a room the
    # reconciliation renamed must not take a name another floor's room holds,
    # or the sleepers of both storeys merge into one
    names_taken = set()
    for f in sorted(floors):
        for r in floors[f]:
            want = rename.get(r["name"], r["name"])
            if want in names_taken:
                base, k = want, 2
                while f"{base} {k}" in names_taken:
                    k += 1
                rename[r["name"]] = want = f"{base} {k}"
            names_taken.add(want)

    def spec(r):
        use = r.get("purpose") or ""
        return RoomSpec(name=rename.get(r["name"], r["name"]),
                        share=r.get("share") or "medium",
                        purpose=use.replace("_", " "), use=use)

    ground = [spec(r) for r in floors.get(1, [])]
    uppers = [UpperStorey(storey=f, rooms=[spec(r) for r in floors.get(f, [])])
              for f in range(2, storeys + 1)]
    # the connections the ground still names (uppers slot by share alone);
    # a room the split left unreachable joins the entrance room
    names = {r.name for r in ground}
    entry = rename.get((wing.get("entrance") or {}).get("room"), "") or \
        (ground[0].name if ground else "")
    conn = []
    for c in wing.get("connections") or []:
        a, d = rename.get(c[0], c[0]), rename.get(c[1], c[1])
        if a in names and d in names and a != d and [a, d] not in conn:
            conn.append([a, d])
    linked = {entry}
    grew = True
    while grew:
        grew = False
        for a, d in conn:
            if (a in linked) != (d in linked):
                linked |= {a, d}
                grew = True
    for r in ground:
        if r.name not in linked:
            conn.append([entry, r.name])
            linked.add(r.name)
    tier = wing_wealth_tier(lib, wing,
                            b.wealth if b is not None and b.wealth in lib.tiers
                            else "modest")
    return BuildingDesign(
        name=name, kind=kind or (b.kind if b is not None else "house"),
        size_class=b.size_class if b is not None else "small",
        wall=BAND_WALL.get(band, "wood"), ground=BAND_GROUND.get(band, "wood"),
        storeys=storeys, couples=b.couples if b is not None else 0,
        residents=b.residents if b is not None else 0,
        wealth=tier, condition=(b.condition if b is not None else "") or "kept",
        status=b.status if b is not None else "",
        upper=uppers, rooms=ground, connections=conn,
        entrance_room=entry, entrance_side=wing.get("entry") or "south",
        stairs_room=entry if storeys > 1 else "",
        furniture=[], loot_pool=b.loot_pool if b is not None else "")


def split_wing_sleepers(lib, designs, wingmap, sources, notes, label):
    """rl-12: the compound's sleeper budget over its wings by role. Every
    wing design starts holding its own part's residents (an unmatched wing
    the gate's), so each part's counts come off first, then go where their
    role sleeps: the traveller beds the P1 lodging promised to the wing that
    sleeps guests, the servants' and stable hands' beds to the wing that
    sleeps staff, the household to the wing that sleeps residents — a part
    whose own wing declares its sleeping and has the beds keeps its counts,
    and a role with no wing to receive it falls back over the others, never
    into a farm wing, whose buildings sleep nobody (rl-15's rule, its note
    unchanged). A compound with no wing that sleeps anyone keeps its counts
    where they were. One line notes the split, one per farm building."""
    def rooms_of(d):
        return list(d.rooms) + [r for u in d.upper for r in u.rooms]

    def all_farm(d):
        rooms = rooms_of(d)
        return bool(rooms) and all(lib.family_of(r.use) in FARM_FAMILIES
                                   for r in rooms)

    def has_bed(d):
        return any(lib.family_of(r.use) in SLEEP_FAMILIES for r in rooms_of(d))

    def guest_beds(src):
        """The traveller beds a P1 part promises: its lodging's unit count."""
        from .phases import LODGING_WORDS
        u = getattr(src, "units", None)
        if u is None or not getattr(u, "count", 0):
            return 0
        if kind_phrases_hit(src.kind, LODGING_WORDS) or \
                kind_phrases_hit(u.name, LODGING_WORDS):
            return int(u.count)
        return 0

    def plural(n, word):
        # "staff" is its own plural; the other role words take the s
        return f"{n} {word}" + ("" if n == 1 or word == "staff" else "s")

    staff_wing = next((n for n in designs
                       if wingmap.get(n, {}).get("sleeps") == "staff"), None)
    guest_wing = next((n for n in designs
                       if wingmap.get(n, {}).get("sleeps") == "guests"), None)
    home_wing = next((n for n in designs
                      if wingmap.get(n, {}).get("sleeps") == "residents"),
                     guest_wing)
    if home_wing is None:
        home_wing = next((n for n in designs if has_bed(designs[n])), None)

    # (source wing, role, residents, couples, guests, destination or None to
    # stay where the part put them)
    moves = []
    for name, d in designs.items():
        src = sources.get(name)
        if src is None:
            continue
        g = guest_beds(src)
        r, c = int(src.residents or 0), int(src.couples or 0)
        if not g and not r and not c:
            continue
        wing = wingmap.get(name) or {}
        if g:
            dest = name if wing.get("sleeps") == "guests" else guest_wing
            moves.append((name, "guests", 0, 0, g, dest))
        if not r and not c:
            continue
        if wing.get("purpose") in SERVICE_PURPOSES and not all_farm(d):
            dest = name if wing.get("sleeps") == "staff" else staff_wing
            moves.append((name, "staff", r, c, 0, dest))
        else:
            dest = name if wing.get("sleeps") == "residents" and has_bed(d) \
                else home_wing
            moves.append((name, "household", r, c, 0, dest))
    if not moves:
        return

    # every wing's counts came off its own part (an unmatched wing's from the
    # gate's): the moves hand them back by role below
    kept = {name: (d.residents, d.couples) for name, d in designs.items()}
    for d in designs.values():
        d.residents = d.couples = d.guests = 0
    roles = {name: [] for name in designs}
    restored = set()
    for name, role, r, c, g, dest in moves:
        if dest is None:
            # nowhere receives this role: the counts stay where they were
            if name not in restored:
                restored.add(name)
                kr, kc = kept[name]
                designs[name].residents += kr
                designs[name].couples += kc
            continue
        d = designs[dest]
        d.residents += r
        d.couples += c
        d.guests += g
        if g:
            roles[dest].append(plural(g, "guest"))
        if role == "staff" and r:
            roles[dest].append(plural(r, "staff"))
        if role == "household" and r:
            roles[dest].append(plural(r, "resident"))
        if c:
            roles[dest].append(plural(c, "couple"))
        if role == "household" and dest != name and all_farm(designs[name]):
            notes.append((label,
                          f"residents of {name} sleep elsewhere: farm building"))
    if any(r for r in roles.values()):
        notes.append((label, "sleepers: " + ", ".join(
            f"{name} {', '.join(r)}" for name, r in roles.items() if r)))


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


def _guest_defaults(lib):
    """{family: (singles, couples)} — the composer's default sleepers, the
    maximum over each family's recipes, cached on the library for the run."""
    cached = getattr(lib, "guest_defaults", None)
    if cached is None:
        from . import room_groups as RG
        from .room_composer import _default_sleepers
        data = RG.load()
        cached = {}
        for recipe in data["recipes"].values():
            fam = recipe.get("family")
            occ = _default_sleepers(recipe, data["groups"])
            if fam not in cached or occ > cached[fam]:
                cached[fam] = occ
        # a dormitory is a shared room (barracks and crew quarters are the
        # same family): its recipes count bunks one per sleeper, so the
        # composer's floor of one would hand an empty dormitory a single
        # bed — a shared room never sleeps fewer than two
        if cached.get("dormitory", (0, 0)) < (2, 0):
            cached["dormitory"] = (2, 0)
        lib.guest_defaults = cached
    return cached


def _sleepers(lib, rooms, residents, couples, guests=0):
    """{room name: (singles, couples)}: one couple to each master bedroom,
    the other residents shared over the single-bed rooms, a spare bed or two
    in each guest room — and the traveller beds a lodging promised (rl-12)
    shared over those guest rooms on top of the beds they always furnish, so
    the building sleeps who it said it would. A room for guests or lodgers
    that no residents were assigned to takes the family's usual occupancy —
    the beds are always furnished."""
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
    spare = []
    for r in rooms:
        if r.get("use") in SPARE_PURPOSES:
            out[r["name"]] = (2 if r.get("share") == "large" else 1, 0)
            spare.append(r["name"])
        elif out[r["name"]] == (0, 0) and r.get("use") in GUEST_PURPOSES:
            out[r["name"]] = _guest_defaults(lib).get(fam[r["name"]], (1, 0))
    for i in range(max(0, int(guests or 0)
                       - sum(out[name][0] for name in spare))):
        if not spare:
            break
        name = spare[i % len(spare)]
        s, c = out[name]
        out[name] = (s + 1, c)
    return out


def ensure_sleep_room(design, b, lib, log):
    """A home whose rooms have nowhere to sleep gets a bedroom off its
    entrance room, so the residents P1 promised have beds — unless every room
    is of the farm families, whose buildings never take beds: the residents
    sleep in the farmhouse, and a compound moves the count there itself."""
    residents = b.get("residents") if isinstance(b.get("residents"), int) else 0
    if residents <= 0:
        return
    if any(lib.family_of(r.get("use")) in SLEEP_FAMILIES for r in design["rooms"]):
        return
    if design["rooms"] and all(lib.family_of(r.get("use")) in FARM_FAMILIES
                               for r in design["rooms"]):
        log.append((f"building {b['name']}",
                    f"residents of {b['name']} sleep elsewhere: farm building"))
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


def dorm_room_specs(n):
    """The dormitory rooms sleeping ``n`` bunks: one room up to eight sleepers,
    two (ceil/floor) past that."""
    caps = [n] if n <= 8 else [(n + 1) // 2, n // 2]
    return [{"name": "Dormitory" if not k else f"Dormitory {k + 1}",
             "share": "large" if cap > 4 else "medium",
             "use": "dormitory", "purpose": "bunks for the night"}
            for k, cap in enumerate(caps)]


def ensure_dorm_room(design, b, lib, log):
    """A building whose bunks became a dormitory (P1's ``dormitory`` count)
    sleeps all its residents in dormitory rooms: the design's own stay, else
    rooms planted off the entrance; either way no bedroom competes for the
    sleepers, so they all reach the bunks."""
    n = b.get("dormitory")
    if not isinstance(n, int) or n <= 0:
        return
    fam = {r["name"]: lib.family_of(r.get("use")) for r in design["rooms"]}
    if not any(f == "dormitory" for f in fam.values()):
        entry = (design.get("entrance") or {}).get("room") or design["rooms"][0]["name"]
        for spec in dorm_room_specs(n):
            name = spec["name"]
            while any(r["name"] == name for r in design["rooms"]):
                name += " 2"
            design["rooms"].append(dict(spec, name=name))
            design.setdefault("connections", []).append([entry, name])
            log.append((f"building {b['name']}",
                        f"added {name} for {n} bunks: the bunks are one room"))
    for r in list(design["rooms"]):
        f = fam.get(r["name"])
        if f in SLEEP_FAMILIES and f != "dormitory" \
                and r.get("use") not in SPARE_PURPOSES:
            design["rooms"].remove(r)
            design["connections"] = [c for c in design.get("connections") or []
                                     if r["name"] not in c]


def ensure_dorm_upper(design, b, lib, registry, band, genre, seed, log):
    """A dormitory building the floors extension took to two storeys sleeps
    its bunks on the upper one: the storey spec the floors machinery places,
    furnished by the library, above the ground floor's common rooms. An
    upper storey the model already gave with a sleep room keeps its own."""
    n = b.get("dormitory")
    if not isinstance(n, int) or n <= 0:
        return
    for u in design.get("upper") or []:
        if isinstance(u, dict) and any(
                lib.family_of(r.get("use")) == "dormitory"
                for r in u.get("rooms") or [] if isinstance(r, dict)):
            return
    upper = {"rooms": dorm_room_specs(n), "connections": [], "furniture": []}
    copy = {"name": b["name"], "residents": n, "couples": 0,
            "wealth": b.get("wealth"), "condition": b.get("condition")}
    expand_design(lib, registry, upper, copy, band, genre, seed, log,
                  ensure_beds=False)
    design.setdefault("upper", []).append(
        {"storey": 2, "rooms": upper["rooms"], "connections": [],
         "furniture": upper["furniture"]})
    log.append((f"building {b['name']}",
                f"added an upper storey for the {n} bunks over the ground rooms"))


def ensure_loft_upper(design, b, lib, registry, band, genre, seed, log):
    """A barn the floors extension took to two storeys gets a hayloft on the
    upper one (design 8.1g): hay storage — the ``barn`` purpose — never beds.
    An upper storey the design already carries keeps its own rooms."""
    if not kind_phrases_hit(b.get("kind"), LOFT_KINDS):
        return
    if any(isinstance(u, dict) and (u.get("rooms") or [])
           for u in design.get("upper") or []):
        return
    upper = {"rooms": [{"name": "Hayloft", "share": "large", "use": "hayloft",
                        "purpose": "hay storage"}],
             "connections": [], "furniture": []}
    copy = {"name": b["name"], "residents": 0, "couples": 0,
            "wealth": b.get("wealth"), "condition": b.get("condition")}
    expand_design(lib, registry, upper, copy, band, genre, seed, log,
                  ensure_beds=False)
    design.setdefault("upper", []).append(
        {"storey": 2, "rooms": upper["rooms"], "connections": [],
         "furniture": upper["furniture"]})
    log.append((f"building {b['name']}",
                "added a hayloft over the ground rooms (hay storage, not beds)"))


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
    """Template names any design's furniture (unit copies and upper storeys
    included) uses."""
    used = set()
    for d in designs:
        lines = (d.get("furniture") or []) \
            + ((d.get("unit") or {}).get("furniture") or [])
        for u in d.get("upper") or []:
            if isinstance(u, dict):
                lines += u.get("furniture") or []
        for f in lines:
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
        ensure_dorm_room(design, b, lib, log)
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
