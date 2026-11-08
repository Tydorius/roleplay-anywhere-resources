"""The room library (ROOM_LIBRARY_DESIGN.md): load it, check it, fill object text.

The library is plain JSON under ``library/``; ``library/library.json`` holds the
fixed vocabulary every other file is checked against, and ``library/AUTHORING.md``
the format. Nothing here changes how a world is built yet: the generator's plain
route doesn't read the library. This module is what the later build steps
(layout compiling, P3 with the library) load it through.

  load(path)          -> Library
  check(lib)          -> (errors, warnings), lists of strings
  coverage(lib)       -> gaps: rooms whose slots no object can fill
  fill_text(...)      -> an object's description and physical text for a setting
"""
import json
import os
import re
from collections import Counter, defaultdict, deque

LIB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "library")
SOURCES_PATH = os.path.join(os.path.dirname(LIB_DIR), "library-seed", "sources.json")
SIDES = ("north", "east", "south", "west")
REL_SIDES = ("far", "side", "near")
SHARES = ("small", "medium", "large")
SIZE_CLASSES = ("hut", "small", "medium", "large", "hall")   # P1 building sizeClass
SLEEP_FAMILIES = ("bedroom", "bedroom.master", "dormitory", "hut")
MAX_SLOT_SHARE = 0.4          # slots may cover at most this much of the interior
ID_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
TOKEN_RE = re.compile(r"\{([^{}]+)\}")
OBJECT_FIELDS = ("id", "category", "size", "walkability", "forSleep", "light", "back",
                 "wealth", "bands", "names", "parts", "text", "container", "sources")


class Library:
    """Everything loaded from one library folder."""

    def __init__(self, path):
        self.path = path
        self.vocab = {}
        self.objects = {}        # id -> object
        self.object_files = {}   # id -> file
        self.materials = {}
        self.conditions = {}
        self.layouts = {}        # id -> layout
        self.layout_files = {}
        self.purposes = {}
        self.suites = {}
        self.suite_files = {}
        self.load_errors = []

    # ---- vocabulary shortcuts
    @property
    def bands(self):
        return self.vocab.get("bands", [])

    @property
    def tiers(self):
        return self.vocab.get("wealth", [])

    def family_of(self, purpose):
        return self.vocab.get("purposes", {}).get(purpose)

    def layouts_for(self, family):
        return [l for l in self.layouts.values() if l.get("family") == family]


def _read(path, errors):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        errors.append(f"{os.path.relpath(path)}: cannot read: {e}")
        return None


def _json_files(folder):
    if not os.path.isdir(folder):
        return []
    return sorted(os.path.join(folder, n) for n in os.listdir(folder) if n.endswith(".json"))


def load(path=LIB_DIR):
    """Load a library folder. Unreadable files land in ``lib.load_errors``;
    duplicate ids are kept first-wins and reported by ``check``."""
    lib = Library(path)
    e = lib.load_errors
    lib.vocab = _read(os.path.join(path, "library.json"), e) or {}
    lib.dupes = []
    for f in _json_files(os.path.join(path, "objects")):
        for o in ((_read(f, e) or {}).get("objects") or []):
            if not isinstance(o, dict):
                e.append(f"{os.path.basename(f)}: an object is not a JSON object")
                continue
            oid = o.get("id")
            if oid in lib.objects:
                lib.dupes.append(f"object id {oid!r} in {os.path.basename(f)} and "
                                 f"{os.path.basename(lib.object_files[oid])}")
                continue
            lib.objects[oid] = o
            lib.object_files[oid] = f
    for name in ("materials", "conditions", "purposes"):
        p = os.path.join(path, name + ".json")
        if os.path.exists(p):
            setattr(lib, name, _read(p, e) or {})
    for f in _json_files(os.path.join(path, "layouts")):
        for l in ((_read(f, e) or {}).get("layouts") or []):
            lid = l.get("id") if isinstance(l, dict) else None
            if lid in lib.layouts:
                lib.dupes.append(f"layout id {lid!r} in {os.path.basename(f)} and "
                                 f"{os.path.basename(lib.layout_files[lid])}")
                continue
            lib.layouts[lid] = l
            lib.layout_files[lid] = f
    for f in _json_files(os.path.join(path, "suites")):
        for s in ((_read(f, e) or {}).get("suites") or []):
            sid = s.get("id") if isinstance(s, dict) else None
            if sid in lib.suites:
                lib.dupes.append(f"suite id {sid!r} in {os.path.basename(f)} and "
                                 f"{os.path.basename(lib.suite_files[sid])}")
                continue
            lib.suites[sid] = s
            lib.suite_files[sid] = f
    return lib


# ------------------------------------------------------------------ checks

def _size_ok(v, lo=1, hi=40):
    return (isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) and lo <= x <= hi
                                                       for x in v))


def _fits(piece, space):
    """True when a [w, h] piece fits a [w, h] space in either orientation."""
    (pw, ph), (sw, sh) = piece, space
    return (pw <= sw and ph <= sh) or (ph <= sw and pw <= sh)


def _object_parts(o, band):
    parts = dict(o.get("parts") or {})
    parts.update((o.get("partsByBand") or {}).get(band) or {})
    return parts


def _check_object(lib, o, sources, err, warn):
    oid = o.get("id")
    where = f"object {oid}"
    for k in OBJECT_FIELDS:
        if k not in o:
            err(f"{where}: missing {k}")
    if not isinstance(oid, str) or not ID_RE.match(oid):
        err(f"{where}: id must be <category>.<name>, lower case")
    cats = lib.vocab.get("categories", {})
    cat = o.get("category")
    if cat not in cats:
        err(f"{where}: unknown category {cat!r}")
    elif isinstance(oid, str) and not oid.startswith(cat + "."):
        warn(f"{where}: id doesn't start with its category {cat!r}")
    if not _size_ok(o.get("size"), hi=8):
        err(f"{where}: size must be [w, h], 1-8 cells")
    w = o.get("walkability")
    if not isinstance(w, (int, float)) or not 0 <= w <= 1:
        err(f"{where}: walkability must be 0-1")
    if o.get("forSleep") is True and isinstance(w, (int, float)) and not 0.2 <= w <= 0.4:
        err(f"{where}: a sleep object has walkability 0.3, not {w}")
    if o.get("forSleep") not in (True, False):
        err(f"{where}: forSleep must be true or false")
    light = o.get("light")
    if not isinstance(light, (int, float)) or not 0 <= light <= 1:
        err(f"{where}: light must be 0-1")
    if o.get("back") not in SIDES + (None,):
        err(f"{where}: back must be a side or null")
    tiers = o.get("wealth")
    if not isinstance(tiers, list) or not tiers or any(t not in lib.tiers for t in tiers):
        err(f"{where}: wealth must be a non-empty list of {lib.tiers}")
    bands = o.get("bands")
    if bands != ["*"] and (not isinstance(bands, list) or not bands
                           or any(b not in lib.bands for b in bands)):
        err(f"{where}: bands must be [\"*\"] or a list of {lib.bands}")
    names = o.get("names")
    if not isinstance(names, dict) or "*" not in names:
        err(f"{where}: names needs a \"*\" noun")
    elif any(k != "*" and k not in lib.bands for k in names):
        err(f"{where}: names has an unknown band")
    classes = lib.vocab.get("materialClasses", [])
    for part, cls in (o.get("parts") or {}).items():
        if cls not in classes:
            err(f"{where}: part {part} has unknown material class {cls!r}")
    for band, over in (o.get("partsByBand") or {}).items():
        if band not in lib.bands:
            err(f"{where}: partsByBand has unknown band {band!r}")
        for part, cls in (over or {}).items():
            if cls not in classes:
                err(f"{where}: partsByBand.{band}.{part} has unknown class {cls!r}")
    text = o.get("text") or {}
    for key in ("description", "physical"):
        t = text.get(key)
        if not isinstance(t, str) or not t.strip():
            err(f"{where}: text.{key} missing")
            continue
        for band in (lib.bands if bands == ["*"] else (bands or [])):
            parts = _object_parts(o, band)
            for tok in TOKEN_RE.findall(t):
                base = tok.split(":", 1)[1] if tok.startswith("A:") else tok
                base = base.split(".", 1)[0] if base.endswith(".color") else base
                if base not in ("noun", "condition") and base not in parts:
                    err(f"{where}: text.{key} token {{{tok}}} has no part in band {band}")
                    break
    if not isinstance(o.get("container"), bool):
        err(f"{where}: container must be true or false")
    if o.get("lootPool") not in (None,):
        warn(f"{where}: lootPool should be null (pools are written per run)")
    srcs = o.get("sources")
    if not isinstance(srcs, list) or not srcs:
        err(f"{where}: sources must list at least one source id")
    elif sources is not None and any(s not in sources for s in srcs):
        err(f"{where}: unknown source in {srcs}")


def _check_materials(lib, err, warn):
    classes = lib.vocab.get("materialClasses", [])
    for cls, by_band in lib.materials.items():
        if cls.startswith("_"):
            continue
        if cls not in classes:
            err(f"materials: unknown class {cls!r}")
            continue
        for band, by_tier in (by_band or {}).items():
            if band != "*" and band not in lib.bands:
                err(f"materials.{cls}: unknown band {band!r}")
                continue
            for tier, entries in (by_tier or {}).items():
                if tier not in lib.tiers:
                    err(f"materials.{cls}.{band}: unknown tier {tier!r}")
                    continue
                if not isinstance(entries, list) or not entries:
                    err(f"materials.{cls}.{band}.{tier}: needs at least one material")
                    continue
                for m in entries:
                    c = m.get("colors") if isinstance(m, dict) else None
                    if not isinstance(m, dict) or not isinstance(m.get("name"), str) \
                            or not isinstance(c, list) or not c or not all(isinstance(x, str) for x in c):
                        err(f"materials.{cls}.{band}.{tier}: each entry is {{name, colors}}")
    for cls in classes:
        for band in lib.bands:
            for tier in lib.tiers:
                if not ((lib.materials.get(cls) or {}).get(band) or {}).get(tier):
                    warn(f"materials: no {cls} for {band} {tier} (falls back)")


def _check_conditions(lib, err):
    conds = lib.vocab.get("conditions", [])
    classes = lib.vocab.get("materialClasses", [])
    if lib.conditions and "*" not in lib.conditions:
        err("conditions: needs a \"*\" fallback")
    for cls, words in lib.conditions.items():
        if cls.startswith("_"):
            continue
        if cls != "*" and cls not in classes:
            err(f"conditions: unknown class {cls!r}")
        for c in conds:
            if not isinstance((words or {}).get(c), str):
                err(f"conditions.{cls}: missing {c}")
        if (words or {}).get("kept", "") != "":
            err(f"conditions.{cls}: kept must be \"\"")


def _anchor_errors(anchor, slot_ids, lib):
    """The anchor's problems (empty when it's in the vocabulary)."""
    bad = []
    for tok in (anchor or "").split("+"):
        tok = tok.strip()
        key, _, val = tok.partition(":")
        if key == "wall" and val in SIDES + REL_SIDES + ("any",):
            continue
        if key == "row" and val in SIDES + REL_SIDES:
            continue
        if key in ("beside", "around"):
            if val not in slot_ids:
                bad.append(f"{tok} names no slot")
            continue
        if tok in ("corner", "center", "near_door", "away_from_door", "symmetric"):
            continue
        bad.append(f"unknown anchor {tok!r}")
    return bad


def _count_max(count):
    if isinstance(count, int):
        return count
    if isinstance(count, list):
        return count[1]
    if count in ("singles", "couples"):
        return 2
    return 1


def _check_layout(lib, l, err, warn):
    lid = l.get("id")
    where = f"layout {lid}"
    if not isinstance(lid, str) or not ID_RE.match(lid):
        err(f"{where}: id must be <family>.<size band>.<letter>")
    fam = l.get("family")
    if fam not in lib.vocab.get("families", {}):
        err(f"{where}: unknown family {fam!r}")
    bands = lib.vocab.get("sizeBands", {})
    sbs = l.get("sizeBands")
    if not isinstance(sbs, list) or not sbs or any(b not in bands or b.startswith("_") for b in sbs):
        err(f"{where}: sizeBands must list size bands")
        sbs = []
    mn, mx = l.get("minInterior"), l.get("maxInterior")
    if not _size_ok(mn) or not _size_ok(mx):
        err(f"{where}: minInterior and maxInterior must be [w, h]")
        return
    if mn[0] > mx[0] or mn[1] > mx[1]:
        err(f"{where}: minInterior is bigger than maxInterior")
    area = mn[0] * mn[1]
    if sbs and not any(bands[b][0] <= area <= bands[b][1] or
                       bands[b][0] <= mx[0] * mx[1] <= bands[b][1] for b in sbs):
        warn(f"{where}: interior {mn}-{mx} is outside its size bands {sbs}")
    roles = lib.vocab.get("roles", {})
    slots = l.get("slots") or []
    if not slots:
        err(f"{where}: no slots")
    ids = [s.get("id") for s in slots]
    for d, n in Counter(ids).items():
        if n > 1:
            err(f"{where}: slot id {d!r} repeats")
    used = 0
    for s in slots:
        sw = f"{where} slot {s.get('id')}"
        role = s.get("role")
        if role not in roles:
            err(f"{sw}: unknown role {role!r}")
        if not _size_ok(s.get("size"), hi=12):
            err(f"{sw}: size must be [w, h]")
            continue
        if not _fits(s["size"], mn):
            err(f"{sw}: size {s['size']} doesn't fit minInterior {mn}")
        for b in _anchor_errors(s.get("anchor"), set(ids) - {s.get("id")}, lib):
            err(f"{sw}: {b}")
        count = s.get("count", 1)
        if count == "singles" and role != "sleep":
            err(f"{sw}: count \"singles\" is for role sleep")
        elif count == "couples" and role != "sleep.couple":
            err(f"{sw}: count \"couples\" is for role sleep.couple")
        elif not (isinstance(count, int) and count >= 1) and not (
                isinstance(count, list) and len(count) == 2 and all(isinstance(x, int) for x in count)
                and 0 <= count[0] <= count[1] and count[1] >= 1) and count not in ("singles", "couples"):
            err(f"{sw}: bad count {count!r}")
        n = _count_max(count)
        if (s.get("anchor") or "").startswith("row:") and n * min(s["size"]) > min(mn):
            err(f"{sw}: a row of {n} x {min(s['size'])} doesn't fit the interior's "
                f"shorter side {min(mn)}")
        if s.get("minWealth") is not None and s["minWealth"] not in lib.tiers:
            err(f"{sw}: unknown minWealth {s['minWealth']!r}")
        if s.get("back") not in (None, "wall"):
            err(f"{sw}: back must be \"wall\" or left out")
        if not s.get("optional") and s.get("minWealth") in (None, "poor"):
            used += n * s["size"][0] * s["size"][1]
    if used > MAX_SLOT_SHARE * area:
        err(f"{where}: required slots cover {used} of {area} interior cells at minInterior "
            f"(at most {int(MAX_SLOT_SHARE * area)})")
    for g in l.get("grow") or []:
        if g.get("role") not in roles:
            err(f"{where} grow: unknown role {g.get('role')!r}")
        for b in _anchor_errors(g.get("anchor"), set(ids), lib):
            err(f"{where} grow: {b}")
        if g.get("size") is not None and not _size_ok(g.get("size"), hi=12):
            err(f"{where} grow: size must be [w, h]")
    fam_sleep = fam in SLEEP_FAMILIES
    has_sleep = any(s.get("role") in ("sleep", "sleep.couple") for s in slots)
    if fam_sleep and not has_sleep:
        err(f"{where}: a {fam} layout needs a sleep slot")
    if fam in ("kitchen", "dining", "common_room") and has_sleep:
        err(f"{where}: no sleep slots in a {fam}")


def _layout_roles(l):
    return {s.get("role") for s in (l.get("slots") or []) + (l.get("grow") or [])}


def _check_purposes(lib, err, warn):
    cats = lib.vocab.get("categories", {})
    roles = lib.vocab.get("roles", {})
    vocab_purposes = lib.vocab.get("purposes", {})
    for p, entry in lib.purposes.items():
        if p.startswith("_"):
            continue
        if p != "*" and p not in vocab_purposes:
            err(f"purposes: unknown purpose {p!r}")
        for role, cs in ((entry or {}).get("roles") or {}).items():
            if role not in roles:
                err(f"purposes.{p}: unknown role {role!r}")
            if not isinstance(cs, list) or not cs:
                err(f"purposes.{p}.{role}: needs a list of categories")
                continue
            for c in cs:
                if "." in c:
                    if not any(binding_matches(c, o) for o in lib.objects.values()):
                        err(f"purposes.{p}.{role}: no object id matches {c!r}")
                elif c not in cats:
                    err(f"purposes.{p}.{role}: unknown category {c!r}")
    if not lib.purposes:
        return
    defaults = ((lib.purposes.get("*") or {}).get("roles") or {})
    for p, fam in vocab_purposes.items():
        if p not in lib.purposes:
            err(f"purposes: {p} has no entry")
            continue
        bound = set(defaults) | set(((lib.purposes.get(p) or {}).get("roles") or {}))
        for l in lib.layouts_for(fam):
            for role in sorted(_layout_roles(l) - bound - {None}):
                err(f"purposes.{p}: role {role} (layout {l.get('id')}) is not bound")


def _check_suite(lib, s, err, warn):
    sid = s.get("id")
    where = f"suite {sid}"
    if not isinstance(sid, str) or not ID_RE.match(sid):
        err(f"{where}: id must be <kind>.<variant>")
    kinds = s.get("kinds")
    if not isinstance(kinds, list) or not kinds or not all(isinstance(k, str) and k == k.lower()
                                                           for k in kinds):
        err(f"{where}: kinds must be lower-case building kinds")
    bands = s.get("bands")
    if not isinstance(bands, list) or not bands or any(b not in lib.bands for b in bands):
        err(f"{where}: bands must list bands")
    scs = s.get("sizeClasses")
    if not isinstance(scs, list) or not scs or any(c not in SIZE_CLASSES for c in scs):
        err(f"{where}: sizeClasses must list {SIZE_CLASSES}")
    r = s.get("residents")
    if not (isinstance(r, list) and len(r) == 2 and all(isinstance(x, int) for x in r)
            and 0 <= r[0] <= r[1]):
        err(f"{where}: residents must be [min, max]")
        r = [0, 0]
    if s.get("wealth") is not None and (not isinstance(s["wealth"], list) or
                                        any(t not in lib.tiers for t in s["wealth"])):
        err(f"{where}: wealth must list tiers")
    rooms = s.get("rooms") or []
    if not 1 <= len(rooms) <= 8:
        err(f"{where}: one to eight rooms")
    names = [x.get("name") for x in rooms]
    for d, n in Counter(names).items():
        if n > 1:
            err(f"{where}: room name {d!r} repeats")
    for x in rooms:
        p = x.get("purpose")
        if p != "custom" and p not in lib.vocab.get("purposes", {}):
            err(f"{where}: room {x.get('name')} has unknown purpose {p!r}")
        if x.get("share") not in SHARES:
            err(f"{where}: room {x.get('name')} share must be one of {SHARES}")
    adj = defaultdict(set)
    for c in s.get("connections") or []:
        if not (isinstance(c, list) and len(c) == 2 and c[0] in names and c[1] in names):
            err(f"{where}: connection {c} names a missing room")
            continue
        adj[c[0]].add(c[1])
        adj[c[1]].add(c[0])
    start = (s.get("entrance") or {}).get("room")
    if start not in names:
        err(f"{where}: entrance room {start!r} is not a room")
    else:
        seen, q = {start}, deque([start])
        while q:
            for nb in adj[q.popleft()] - seen:
                seen.add(nb)
                q.append(nb)
        for n in names:
            if n not in seen:
                err(f"{where}: room {n} can't be reached from the entrance")
    sleeps = [x for x in rooms if lib.family_of(x.get("purpose")) in SLEEP_FAMILIES]
    if r[1] > 0 and not sleeps:
        err(f"{where}: {r[1]} residents but no room to sleep in")
    if r[1] == 0 and sleeps:
        warn(f"{where}: nobody lives here but it has bedrooms")


def check(lib, sources_path=SOURCES_PATH):
    """(errors, warnings) for the whole library."""
    errors, warnings = list(lib.load_errors), []
    errors += getattr(lib, "dupes", [])
    err, warn = errors.append, warnings.append
    for key in ("bands", "wealth", "conditions", "materialClasses", "categories", "roles",
                "families", "purposes", "anchors", "sizeBands"):
        if key not in lib.vocab:
            err(f"library.json: missing {key}")
    for p, fam in lib.vocab.get("purposes", {}).items():
        if fam not in lib.vocab.get("families", {}):
            err(f"library.json: purpose {p} names unknown family {fam!r}")
    sources = None
    if sources_path and os.path.exists(sources_path):
        with open(sources_path, "r", encoding="utf-8") as f:
            sources = {s["id"] for s in json.load(f)}
    for o in lib.objects.values():
        _check_object(lib, o, sources, err, warn)
    _check_materials(lib, err, warn)
    _check_conditions(lib, err)
    for l in lib.layouts.values():
        _check_layout(lib, l, err, warn)
        if lib.layout_files.get(l.get("id")) and \
                os.path.basename(lib.layout_files[l["id"]])[:-5] != l.get("family"):
            warn(f"layout {l.get('id')}: family {l.get('family')} in "
                 f"{os.path.basename(lib.layout_files[l['id']])}")
    _check_purposes(lib, err, warn)
    for s in lib.suites.values():
        _check_suite(lib, s, err, warn)
    for fam in lib.vocab.get("families", {}):
        if lib.layouts and not lib.layouts_for(fam):
            warn(f"family {fam} has no layouts")
    return errors, warnings


# ------------------------------------------------------------------ coverage

def binding_matches(entry, obj):
    """A purpose binding entry names a category ("rack") or an object id or
    id prefix ("rack.weapon"), which picks out pieces a category lumps together."""
    if "." in entry:
        oid = obj.get("id") or ""
        return oid == entry or oid.startswith(entry + ".")
    return obj.get("category") == entry


def candidates(lib, purpose, role, size, band, tier):
    """Objects that can fill a slot of ``role`` and ``size`` in a ``purpose``
    room of ``band`` at ``tier``, in the role's category order."""
    entry = ((lib.purposes.get(purpose) or {}).get("roles") or {}).get(role)
    if entry is None:
        entry = ((lib.purposes.get("*") or {}).get("roles") or {}).get(role) or []
    out = []
    for cat in entry:
        for o in lib.objects.values():
            if not binding_matches(cat, o):
                continue
            if o.get("bands") != ["*"] and band not in (o.get("bands") or []):
                continue
            if tier not in (o.get("wealth") or []):
                continue
            if size is not None and _size_ok(o.get("size"), hi=8) and not _fits(o["size"], size):
                continue
            if _size_ok(o.get("size"), hi=8):
                small = min(o["size"]) < 2
                if role == "sleep.couple" and small:
                    continue      # a couple's bed sleeps two
                if role in ("sleep", "sleep.child", "cell.bed", "med.bed") and not small:
                    continue      # a single's bed sleeps one
            out.append(o)
    return out


def coverage(lib):
    """Gaps in required slots (optional ones are simply left out of a room):
    [(purpose, band, tier, layout id, slot id, role, size, widened)].
    ``widened`` is True when another wealth tier would fill it (a soft gap)."""
    gaps = []
    for purpose, fam in sorted(lib.vocab.get("purposes", {}).items()):
        for l in sorted(lib.layouts_for(fam), key=lambda l: l.get("id")):
            for s in l.get("slots") or []:
                if s.get("optional"):
                    continue
                for band in lib.bands:
                    for tier in lib.tiers:
                        if s.get("minWealth") and lib.tiers.index(tier) < lib.tiers.index(s["minWealth"]):
                            continue
                        if candidates(lib, purpose, s.get("role"), s.get("size"), band, tier):
                            continue
                        widened = any(candidates(lib, purpose, s.get("role"), s.get("size"), band, t)
                                      for t in lib.tiers if t != tier)
                        gaps.append((purpose, band, tier, l.get("id"), s.get("id"),
                                     s.get("role"), s.get("size"), widened))
    return gaps


# ------------------------------------------------------------------ text fill

def _material(lib, cls, band, tier, rng):
    """(name, colour) for a material class: the tier, then tiers toward modest,
    then any tier of the band, then the band's \"*\" entry."""
    by_band = (lib.materials.get(cls) or {})
    order = [tier] + sorted((t for t in lib.tiers if t != tier),
                            key=lambda t: abs(lib.tiers.index(t) - lib.tiers.index("modest")))
    for b in (band, "*"):
        for t in order:
            entries = ((by_band.get(b) or {}).get(t)) or []
            if entries:
                m = rng.choice(entries)
                return m["name"], rng.choice(m.get("colors") or [""])
    return cls, ""


def _condition_word(lib, cls, condition):
    words = lib.conditions.get(cls) or lib.conditions.get("*") or {}
    return words.get(condition, "") if condition != "kept" else ""


def _article(word):
    w = word.lower()
    if w.startswith(("hour", "honest", "heir")):
        return "an"
    if w.startswith(("uni", "use", "eu", "one", "ewe")):
        return "a"
    return "an" if w[:1] in "aeiou" else "a"


def fill_text(lib, obj, band, tier, condition, rng):
    """{"description", "physical", "materials"} for an object in a setting.
    ``rng`` is a random.Random seeded by the caller, so a re-roll repeats it."""
    parts = _object_parts(obj, band)
    picks = {p: _material(lib, cls, band, tier, rng) for p, cls in sorted(parts.items())}
    main = next(iter(parts.values()), "*")
    cond = _condition_word(lib, main, condition)
    noun = (obj.get("names") or {}).get(band) or (obj.get("names") or {}).get("*") or obj.get("id")

    def fill(text):
        def sub(m):
            tok = m.group(1)
            if tok.startswith("A:"):
                # "a"/"an" agreeing with whatever word comes next once filled
                return "\x00" + sub(re.match(r"(.*)", tok[2:]))
            if tok == "noun":
                return noun
            if tok == "condition":
                return cond
            if tok.endswith(".color"):
                name, colour = picks.get(tok[:-6], ("", ""))
                # "chrome chrome-plated steel": the material already says it
                return "" if colour and colour.lower() in name.lower() else colour
            return picks.get(tok, (tok, ""))[0]
        s = TOKEN_RE.sub(sub, text)
        s = re.sub(r"\x00\s*(\S+)", lambda m: _article(m.group(1)) + " " + m.group(1), s)
        s = re.sub(r"\s{2,}", " ", s.replace("\x00", ""))
        # "marble marble altar", "polished polished walnut": a word the fill repeated
        s = re.sub(r"\b(\w[\w-]*) \1\b", r"\1", s, flags=re.I)
        # a fixed "a"/"an" written before a token agrees with what filled it
        s = re.sub(r"\b([Aa]n?) ([A-Za-z][\w-]*)",
                   lambda m: (_article(m.group(2)) if m.group(1).islower()
                              else _article(m.group(2)).capitalize()) + " " + m.group(2), s)
        s = re.sub(r"\s+([,.;:])", r"\1", re.sub(r"\s{2,}", " ", s)).strip()
        return s[:1].upper() + s[1:]

    text = obj.get("text") or {}
    return {"description": fill(text.get("description", "")),
            "physical": fill(text.get("physical", "")),
            "materials": {p: v[0] for p, v in picks.items()}}


# ------------------------------------------------------------------ report

def report(lib, errors, warnings, gaps=None, out=print):
    """Print a short summary for the ``library`` command."""
    out(f"library {lib.path}")
    out(f"  {len(lib.objects)} objects, {len(lib.layouts)} layouts, {len(lib.suites)} suites, "
        f"{len([p for p in lib.purposes if not p.startswith('_')])} purposes")
    by_band = Counter()
    for o in lib.objects.values():
        for b in (lib.bands if o.get("bands") == ["*"] else o.get("bands") or []):
            by_band[b] += 1
    out("  objects per band: " + ", ".join(f"{b} {by_band[b]}" for b in lib.bands))
    out(f"  {len(errors)} error(s), {len(warnings)} warning(s)")
    for e in errors:
        out("ERROR " + e)
    if gaps is not None:
        hard = [g for g in gaps if not g[7]]
        out(f"  coverage: {len(gaps)} slot gaps, {len(hard)} with no object at any tier")
        by = Counter((g[0], g[1], g[5]) for g in hard)
        for (purpose, band, role), n in sorted(by.items()):
            out(f"GAP {purpose} {band} {role} ({n})")
