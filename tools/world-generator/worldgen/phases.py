"""The model phases P1-P5 (see DESIGN.md): each call gets only the context it
needs, its reply is checked against the contract, violations go back to the
model on a retry, and entries that are still bad after the retries are
dropped and logged rather than losing the whole phase.

The merged result is a plan dict in the shape of ``fixtures/village.json``
(P4 dressing lives under ``zones[i].dressing``, P3 designs in a top-level
``buildings`` list), ready for ``worldgen.run``.
"""
import json
import os
import re
import string
import time

from . import hints as hints_mod
from .model import (COMPOUND_SHAPES, COMPOUND_SHAPES_KNOWN, COMPOUND_WALLS,
                    COURTYARD_SIZES, VALID_ARRANGEMENTS, is_sleep_name as _sleeps)

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")

SIDES = ("north", "south", "east", "west")
DENSITY = ("sparse", "normal", "dense")
MAP_SIZES = ("small", "medium", "large")
ZONE_SIZES = ("small", "medium", "large", "huge")
BUILDING_SIZES = ("hut", "small", "medium", "large", "hall")
SHARES = ("small", "medium", "large")
WALLS = ("wood", "brick", "stone", "steel")
PATH_KINDS = ("none", "dirt", "cobble", "paved")
YARD_SIDES = ("front", "back", "left", "right")
FILL_DENSITY = ("low", "medium", "high")

MAX_BUILDINGS = 12      # across the whole P1 plan
MAX_BUILDINGS_COMPOUNDS = 16   # the cap when the plan uses compounds
MAX_TEMPLATE_SIDE = 4   # cells; a tree is 3x3 at most
MAX_COUNT = 12          # one furniture/prop line
MAX_ERRORS = 12         # cap on the error list fed back to the model


class PhaseError(Exception):
    pass


class Cancelled(Exception):
    """Raised between model calls when a run's cancel callback turns true."""


# ------------------------------------------------------------------ prompts

def _template(name):
    path = os.path.join(PROMPTS_DIR, name + ".txt")
    with open(path, "r", encoding="utf-8") as f:
        return string.Template(f.read())


def _rules():
    with open(os.path.join(PROMPTS_DIR, "rules.txt"), "r", encoding="utf-8") as f:
        return f.read().strip()


def _ext_fragments(name, exts):
    """The enabled extensions' fragments for one phase prompt, in a stable
    order. An extension without a fragment for the phase adds nothing."""
    from .extensions import expand
    out = []
    for ext in sorted(expand(exts)):
        path = os.path.join(PROMPTS_DIR, "ext", ext, name + ".txt")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                out.append(f.read().strip())
    return "\n\n".join(out)


def assemble_prompt(name, exts=(), **kw):
    """One phase prompt: the template substituted, then the enabled
    extensions' fragments appended. Without extensions this is exactly the
    template on its own."""
    body = _template(name).substitute(rules=_rules(), **kw)
    frag = _ext_fragments(name, exts)
    return body if not frag else body + "\n\n" + frag


def _setting_line(p1):
    s = p1.get("setting", {}) or {}
    bits = [f"{k}: {s.get(k)}" for k in ("era", "technology", "density", "climate") if s.get(k)]
    bg = (p1.get("worldBackground") or "").strip()
    head = f"{p1.get('name', 'the world')} - " + ", ".join(bits)
    return head + ("\n" + bg if bg else "")


def _zone_line(zone):
    z = f"{zone.get('name')} ({zone.get('kind')}, {zone.get('sizeClass')}, ground {zone.get('ground')})"
    desc = (zone.get("description") or "").strip()
    return z + (f": {desc}" if desc else "")


def _building_line(b):
    y = ""
    if isinstance(b.get("yard"), dict) and b["yard"]:
        y = f", yard ({b['yard'].get('kind', 'yard')} on the {b['yard'].get('side', 'back')})"
    s = f", {b['storeys']} storeys" if _check_int(b.get("storeys")) and b["storeys"] > 1 else ""
    return f"{b.get('name')} - {b.get('kind')}, {b.get('sizeClass')}{s}: {b.get('purpose', '')}{y}"


def _catalogue_lines(templates):
    return "\n".join(f"- {t['name']} | {t['size'][0]}x{t['size'][1]} | {t.get('rule', '')}"
                     for t in templates)


# ------------------------------------------------- compounds in the raw plan

def _slot_bits(part):
    at = part.get("at") or ""
    return at.split(":") if isinstance(at, str) else []


def _perimeter_cycle(parts):
    """The perimeter parts of an enclosure in walk order (south, east,
    north-reversed, west-reversed), corners first and last on their sides,
    edge parts between them start -> center -> end."""
    corners, edges = {}, {}
    for p in parts:
        bits = _slot_bits(p)
        if bits[:1] == ["corner"] and len(bits) == 2:
            corners[bits[1]] = p
        elif bits[:1] == ["edge"] and len(bits) == 3:
            edges.setdefault(bits[1], []).append(p)
    rank = {"start": 0, "center": 1, "end": 2}

    def edge_rank(p):
        bits = _slot_bits(p)
        return (rank.get(bits[2] if len(bits) > 2 else "", 1), p.get("building", ""))

    side_corners = {"south": ("sw", "se"), "west": ("sw", "nw"),
                    "north": ("nw", "ne"), "east": ("se", "ne")}
    cycle = []
    for side, rev in (("south", False), ("east", False),
                      ("north", True), ("west", True)):
        first, last = side_corners[side]
        seq = ([corners[first]] if first in corners else []) + \
            sorted(edges.get(side, ()), key=edge_rank) + \
            ([corners[last]] if last in corners else [])
        for p in (reversed(seq) if rev else seq):
            if p not in cycle:
                cycle.append(p)
    return cycle


def _compound_line(compounds, zone, building):
    """P3's one line on a part's slot and neighbours, so its entrance, inner
    doors and stairs make sense inside the structure."""
    comp = next((c for c in compounds if isinstance(c, dict)
                 and c.get("zone") == zone.get("name")
                 and any(isinstance(p, dict) and p.get("building") == building["name"]
                         for p in (c.get("parts") or []))), None)
    if comp is None:
        return "none; this building stands on its own"
    parts = [p for p in comp["parts"] if isinstance(p, dict)]
    part = next(p for p in parts if p.get("building") == building["name"])
    bits = _slot_bits(part)
    walls_kind = comp.get("walls", "walkable")
    walls = "" if walls_kind == "none" else \
        " (the walls are walkable upstairs)" if walls_kind == "walkable" else ""
    if bits[:1] == ["corner"]:
        facing = {"nw": ("west", "north"), "ne": ("east", "north"),
                  "sw": ("west", "south"), "se": ("east", "south")}.get(bits[1])
        slot = f"corner slot {bits[1].upper()}; walls join it on the {facing[0]} and the {facing[1]}"
    elif bits[:1] == ["edge"]:
        along = ("west", "east") if bits[1] in ("south", "north") else ("south", "north")
        slot = f"set in the {bits[1]} wall ({bits[2]}); walls join it on the {along[0]} and the {along[1]}"
        if part.get("gate"):
            slot += "; it is the GATE, walked through on both faces"
    elif bits[:1] == ["inside"]:
        slot = "standing in the courtyard" + \
               (f" towards the {bits[1]}" if len(bits) == 2 and bits[1] != "center" else "") + \
               "; no walls touch it, the gate's path leads to its door"
    else:   # attached (or junk, which check_p1 will have flagged)
        slot = f"attached to {bits[1] if len(bits) > 1 else '?'}" + \
               (f" on its {bits[2]} side, sharing that wall" if len(bits) > 2 else "")
    cycle = _perimeter_cycle(parts)
    neighbours = ""
    if part in cycle and len(cycle) > 1:
        i = cycle.index(part)
        beside = [cycle[i - 1]["building"], cycle[(i + 1) % len(cycle)]["building"]]
        neighbours = "; next along the walls: " + ", ".join(beside)
    return f"part of {comp.get('name', 'the compound')}: {slot}{walls}{neighbours}"


def compound_errors(compounds, zone_names, building_zone):
    """Structural errors in a raw P1 compounds list: shape, slots, unknown or
    foreign buildings, duplicate slots, gate rules, attached hosts that are
    missing or loop. Mirrors the plan parser's own validation so the model
    gets its mistakes back on a retry."""
    errors = []
    names = set()
    for i, c in enumerate(compounds):
        ctx = f"compounds[{i}]"
        if not isinstance(c, dict):
            errors.append(f"{ctx}: must be an object")
            continue
        name = c.get("name")
        if not _is_str(name):
            errors.append(f"{ctx}: name required")
            name = f"compounds[{i}]"
            ctx = name
        elif name in names:
            errors.append(f"{ctx}: name {name!r} used twice")
        else:
            names.add(name)
            ctx = f"compound {name!r}"
        zone = c.get("zone")
        if zone not in zone_names:
            errors.append(f"{ctx}: zone {zone!r} is not a zone of this plan")
        shape = c.get("shape", "enclosure")
        if shape in COMPOUND_SHAPES_KNOWN:
            errors.append(f"{ctx}: shape {shape!r} is not implemented; use enclosure")
        elif shape not in COMPOUND_SHAPES:
            errors.append(f"{ctx}: shape must be enclosure, not {shape!r}")
        if c.get("courtyard", "medium") not in COURTYARD_SIZES:
            errors.append(f"{ctx}: courtyard must be small, medium or large")
        if c.get("walls", "walkable") not in COMPOUND_WALLS:
            errors.append(f"{ctx}: walls must be walkable, solid or none")
        parts = c.get("parts")
        if not isinstance(parts, list) or not parts:
            errors.append(f"{ctx}: parts must be a non-empty list")
            continue
        slots, gates, hosts = set(), [], {}
        for j, p in enumerate(parts):
            pctx = f"{ctx} part {j + 1}"
            if not isinstance(p, dict):
                errors.append(f"{pctx}: must be an object")
                continue
            bname = p.get("building")
            pctx = f"{ctx} part {bname!r}" if _is_str(bname) else pctx
            if bname not in building_zone:
                errors.append(f"{pctx}: building {bname!r} is not in the plan")
            elif zone in zone_names and building_zone[bname] != zone:
                errors.append(f"{pctx}: building {bname!r} belongs to zone "
                              f"{building_zone[bname]!r}, not {zone!r}")
            at = p.get("at", "")
            bits = at.split(":") if isinstance(at, str) else []
            ok = (bits[:1] == ["corner"] and len(bits) == 2 and bits[1] in ("nw", "ne", "sw", "se")) or \
                 (bits[:1] == ["edge"] and len(bits) == 3 and bits[1] in SIDES
                  and bits[2] in ("start", "center", "end")) or \
                 (bits[:1] == ["inside"] and len(bits) == 2
                  and bits[1] in ("center",) + SIDES) or \
                 (bits[:1] == ["attached"] and len(bits) == 3 and bits[2] in SIDES)
            if not ok:
                errors.append(f"{pctx}: bad slot {at!r} (corner:<nw|ne|sw|se>, "
                              f"edge:<side>:<start|center|end>, inside:<center|side> "
                              f"or attached:<part>:<side>)")
                continue
            if at in slots:
                errors.append(f"{pctx}: slot {at!r} used twice in {name!r}")
            slots.add(at)
            if p.get("gate"):
                if bits[0] != "edge":
                    errors.append(f"{pctx}: only an edge part can be the gate")
                gates.append(bname)
            if bits[0] == "attached":
                hosts[bname] = bits[1]
            elif _is_str(bname):
                hosts[bname] = None
        if len(gates) > 2:
            errors.append(f"{ctx}: at most two gates, got {len(gates)}")
        for bname, host in hosts.items():
            if host is not None and host not in hosts:
                errors.append(f"{ctx} part {bname!r}: attached host {host!r} "
                              f"is not a part of {name!r}")
        for bname in hosts:
            walk, seen = bname, set()
            while walk in hosts and hosts[walk] is not None:
                if walk in seen:
                    errors.append(f"{ctx} part {bname!r}: attached parts form a cycle")
                    break
                seen.add(walk)
                walk = hosts[walk]
    return errors


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40] or "x"


# ------------------------------------------------------------- tiny helpers

def _is_str(v):
    return isinstance(v, str) and bool(v.strip())


def _enum(d, key, allowed, ctx, errors):
    v = d.get(key)
    if v not in allowed:
        errors.append(f"{ctx}: {key} must be one of {list(allowed)}, not {v!r}")


def _check_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def hint_errors(hint, templates=None, buildings=None):
    """Violations of the placement-hint vocabulary: unknown tokens and
    beside:/around:/behind:/front: references that do not exist. ``beside:``
    names a template indoors and a building outdoors; when both pools are
    given, either match accepts it."""
    if not isinstance(hint, str) or not hint.strip():
        return []
    h = hints_mod.parse(hint)
    errors = [f"hint {hint!r}: unknown token {t!r} (use the placement vocabulary only)"
              for t in h.unknown]
    if h.beside:
        in_t = templates is not None and h.beside in templates
        in_b = buildings is not None and h.beside in buildings
        if templates is not None or buildings is not None:
            if not in_t and not in_b:
                kind = "template or building" if templates is not None and buildings is not None \
                    else ("template" if templates is not None else "building")
                errors.append(f"hint {hint!r}: {kind} {h.beside!r} does not exist")
    if h.around and templates is not None and h.around not in templates:
        errors.append(f"hint {hint!r}: template {h.around!r} does not exist")
    if h.building_ref and buildings is not None and h.building_ref not in buildings:
        errors.append(f"hint {hint!r}: building {h.building_ref!r} does not exist")
    return errors


def _prop_errors(props, ctx, templates, buildings=None, max_count=MAX_COUNT):
    errors = []
    names = set()
    for i, p in enumerate(props):
        if not isinstance(p, dict):
            errors.append(f"{ctx}[{i}]: must be an object")
            continue
        name = p.get("template")
        if name not in templates:
            errors.append(f"{ctx}[{i}]: template {name!r} is not in the catalogue")
        c = p.get("count", 1)
        if not _check_int(c) or not 1 <= c <= max_count:
            errors.append(f"{ctx}[{i}]: count must be a whole number 1..{max_count}, not {c!r}")
        errors.extend(hint_errors(p.get("hint", ""), templates=templates, buildings=buildings))
        if name in names:
            errors.append(f"{ctx}[{i}]: template {name!r} listed twice; merge the counts")
        names.add(name)
    return errors


# ---------------------------------------------------------- P1 world plan

def check_p1(d, floors=False):
    errors = []
    if not isinstance(d, dict):
        return ["P1: the reply is not a JSON object"]
    if not _is_str(d.get("worldBackground")):
        errors.append("worldBackground: required, a sentence or more")
    s = d.get("setting")
    if not isinstance(s, dict):
        errors.append("setting: required object {era, technology, density, climate}")
    else:
        for k in ("era", "technology", "climate"):
            if not _is_str(s.get(k)):
                errors.append(f"setting.{k}: required, a short phrase")
        _enum(s, "density", DENSITY, "setting", errors)
    _enum(d, "mapSize", MAP_SIZES, "P1", errors)
    zones = d.get("zones")
    if not isinstance(zones, list) or not zones:
        return errors + ["zones: required, a list of 2-4 zones"]
    if len(zones) > 6:
        errors.append(f"zones: {len(zones)} is too many; use 2-4")
    znames = set()
    for i, z in enumerate(zones):
        ctx = f"zones[{i}]"
        if not isinstance(z, dict):
            errors.append(f"{ctx}: must be an object")
            continue
        if not _is_str(z.get("name")):
            errors.append(f"{ctx}.name: required")
        elif z["name"] in znames:
            errors.append(f"{ctx}.name: {z['name']!r} used twice")
        else:
            znames.add(z["name"])
        if not _is_str(z.get("kind")):
            errors.append(f"{ctx}.kind: required, free text (village, forest, ...)")
        _enum(z, "sizeClass", ZONE_SIZES, ctx, errors)
        if not _is_str(z.get("description")):
            errors.append(f"{ctx}.description: required, one sentence")
        if not _is_str(z.get("ground")):
            errors.append(f"{ctx}.ground: required (grass|dirt|gravel|stone)")
        arrangement = z.get("arrangement", "")
        if arrangement not in ("",) + VALID_ARRANGEMENTS:
            errors.append(f"{ctx}.arrangement: must be one of "
                          f"{list(VALID_ARRANGEMENTS)}, not {arrangement!r}")
        adj = z.get("adjacentTo", [])
        if not isinstance(adj, list):
            errors.append(f"{ctx}.adjacentTo: must be a list of zone names")
        if not isinstance(z.get("outdoor", []), list):
            errors.append(f"{ctx}.outdoor: must be a list of short feature names")
        bl = z.get("buildings", [])
        if not isinstance(bl, list):
            errors.append(f"{ctx}.buildings: must be a list")
    total = sum(len(z.get("buildings", []) or []) for z in zones if isinstance(z, dict))
    compounds = [c for c in (d.get("compounds") or []) if isinstance(c, dict)]
    cap = MAX_BUILDINGS_COMPOUNDS if compounds else MAX_BUILDINGS
    if total > cap:
        errors.append(f"buildings: {total} in total is too many; at most {cap}"
                      f"{' with compounds' if compounds else ''}")
    zn = {z.get("name") for z in zones if isinstance(z, dict) and _is_str(z.get("name"))}
    bz = {b.get("name"): z.get("name") for z in zones if isinstance(z, dict)
          for b in (z.get("buildings") or []) if isinstance(b, dict)}
    errors.extend(compound_errors(d.get("compounds") or [], zn, bz))
    bnames = set()
    for z in zones:
        if not isinstance(z, dict):
            continue
        for j, b in enumerate(z.get("buildings", []) or []):
            ctx = f"building {b.get('name') or j} in {z.get('name')}"
            if not isinstance(b, dict):
                errors.append(f"{ctx}: must be an object")
                continue
            if not _is_str(b.get("name")):
                errors.append(f"{ctx}: name required")
            elif b["name"] in bnames:
                errors.append(f"{ctx}: name {b['name']!r} used twice in the plan")
            else:
                bnames.add(b["name"])
            if not _is_str(b.get("kind")):
                errors.append(f"{ctx}: kind required")
            _enum(b, "sizeClass", BUILDING_SIZES, ctx, errors)
            if floors and "storeys" in b:
                s = b["storeys"]
                if not _check_int(s) or not 1 <= s <= 3:
                    errors.append(f"{ctx}: storeys must be a whole number 1..3, not {s!r}")
            if not _is_str(b.get("purpose")):
                errors.append(f"{ctx}: purpose required, one phrase")
            y = b.get("yard")
            if y is not None:
                if not isinstance(y, dict):
                    errors.append(f"{ctx}: yard must be null or an object")
                else:
                    _enum(y, "side", YARD_SIDES, f"{ctx}.yard", errors)
    for i, r in enumerate(d.get("roads", []) or []):
        if not isinstance(r, dict):
            errors.append(f"roads[{i}]: must be an object")
            continue
        f, t = r.get("from"), r.get("to")
        if f not in znames:
            errors.append(f"roads[{i}].from: unknown zone {f!r}")
        if t not in znames:
            errors.append(f"roads[{i}].to: unknown zone {t!r}")
        if f == t and f is not None:
            errors.append(f"roads[{i}]: from and to are the same zone")
    for z in zones:
        if not isinstance(z, dict):
            continue
        for n in z.get("adjacentTo", []) or []:
            if n not in znames:
                errors.append(f"zone {z.get('name')!r}: adjacentTo unknown zone {n!r}")
    return errors[:MAX_ERRORS]


def sanitize_p1(d, log, floors=False):
    """Drop bad zones/buildings/roads and default bad enums; log each change."""
    d["name"] = d.get("name") if _is_str(d.get("name")) else "Generated World"
    s = d.get("setting") if isinstance(d.get("setting"), dict) else {}
    s["density"] = s.get("density") if s.get("density") in DENSITY else "normal"
    d["setting"] = s
    if d.get("mapSize") not in MAP_SIZES:
        log.append(("P1 mapSize", f"{d.get('mapSize')!r} -> 'small'"))
        d["mapSize"] = "small"
    zones = []
    for z in d.get("zones", []) or []:
        if not isinstance(z, dict) or not _is_str(z.get("name")):
            log.append(("zone", "dropped: no name"))
            continue
        if z.get("sizeClass") not in ZONE_SIZES:
            log.append((f"zone {z['name']}", f"sizeClass {z.get('sizeClass')!r} -> 'medium'"))
            z["sizeClass"] = "medium"
        if z.get("arrangement", "") not in ("",) + VALID_ARRANGEMENTS:
            log.append((f"zone {z['name']}",
                        f"arrangement {z.get('arrangement')!r} dropped"))
            z.pop("arrangement", None)
        z["adjacentTo"] = [n for n in (z.get("adjacentTo") or [])
                           if isinstance(n, str) and n != z["name"]]
        z.setdefault("outdoor", [])
        z.setdefault("buildings", [])
        zones.append(z)
    names = {z["name"] for z in zones}
    for z in zones:
        z["adjacentTo"] = [n for n in z["adjacentTo"] if n in names and n != z["name"]]
    roads = []
    for r in d.get("roads", []) or []:
        if isinstance(r, dict) and r.get("from") in names and r.get("to") in names \
                and r["from"] != r["to"]:
            roads.append({"from": r["from"], "to": r["to"], "kind": r.get("kind", "dirt")})
        else:
            log.append((f"road {r.get('from')}-{r.get('to')}", "dropped: bad endpoints"))
    d["roads"] = roads
    # one pass across zones so the building cap is global; compounds raise
    # it, since a compound's towers and gatehouse are buildings too
    seen, total = set(), 0
    for z in zones:
        keep = []
        for b in z.get("buildings", []) or []:
            if not isinstance(b, dict) or not _is_str(b.get("name")) or b["name"] in seen:
                log.append((f"building {b.get('name') if isinstance(b, dict) else b}",
                            "dropped from P1: bad or duplicate name"))
                continue
            if b.get("sizeClass") not in BUILDING_SIZES:
                log.append((f"building {b['name']}",
                            f"sizeClass {b.get('sizeClass')!r} -> 'small'"))
                b["sizeClass"] = "small"
            if floors:
                if not _check_int(b.get("storeys", 1)) or not 1 <= b.get("storeys", 1) <= 3:
                    log.append((f"building {b['name']}",
                                f"storeys {b.get('storeys')!r} -> 1"))
                    b["storeys"] = 1
            else:
                b.pop("storeys", None)
            if isinstance(b.get("yard"), dict) and b["yard"].get("side") not in YARD_SIDES:
                b["yard"]["side"] = "back"
            seen.add(b["name"])
            keep.append(b)
        z["buildings"] = keep
    zn = {z["name"] for z in zones}
    bz = {b["name"]: z["name"] for z in zones for b in z["buildings"]}
    compounds = []
    for c in d.get("compounds") or []:
        label = f"compound {c.get('name')}" if isinstance(c, dict) and _is_str(c.get("name")) \
            else "compound"
        if not isinstance(c, dict) or compound_errors([c], zn, bz):
            log.append((label, "dropped from P1: bad structure"))
            continue
        compounds.append(c)
    cap = MAX_BUILDINGS_COMPOUNDS if compounds else MAX_BUILDINGS
    part_names = {p.get("building") for c in compounds
                  for p in (c.get("parts") or []) if isinstance(p, dict)}
    while sum(len(z["buildings"]) for z in zones) > cap:
        # loose buildings go over the cap before any compound part does
        victim = None
        for z in reversed(zones):
            for b in reversed(z["buildings"]):
                if b["name"] not in part_names:
                    victim = (z, b)
                    break
            if victim:
                break
        if victim is None:
            for z in reversed(zones):
                if z["buildings"]:
                    victim = (z, z["buildings"][-1])
                    break
        z, b = victim
        z["buildings"].remove(b)
        log.append((f"building {b['name']}",
                    f"dropped from P1: over the {cap}-building cap"))
    # a compound missing any of its parts is gone with it
    alive = {b["name"] for z in zones for b in z["buildings"]}
    kept = []
    for c in compounds:
        missing = [p.get("building") for p in (c.get("parts") or [])
                   if isinstance(p, dict) and p.get("building") not in alive]
        if missing:
            log.append((f"compound {c.get('name')}",
                        f"dropped from P1: part building(s) {', '.join(map(str, missing))} "
                        f"did not survive"))
        else:
            kept.append(c)
    d["compounds"] = kept
    d["zones"] = zones
    return d


# -------------------------------------------------------- P2 prop catalogue

def check_p2(d):
    errors = []
    if not isinstance(d, dict) or not isinstance(d.get("templates"), list) \
            or not d["templates"]:
        return ["P2: the reply must be {\"templates\": [...]}, a non-empty list"]
    if len(d["templates"]) > 40:
        errors.append(f"templates: {len(d['templates'])} is too many; use 12-30")
    seen = set()
    for i, t in enumerate(d["templates"]):
        ctx = f"templates[{i}]"
        if not isinstance(t, dict):
            errors.append(f"{ctx}: must be an object")
            continue
        if not _is_str(t.get("name")):
            errors.append(f"{ctx}.name: required")
        elif t["name"] in seen:
            errors.append(f"{ctx}.name: {t['name']!r} used twice")
        else:
            seen.add(t["name"])
        size = t.get("size")
        if not (isinstance(size, list) and len(size) == 2
                and all(_check_int(v) and 1 <= v <= MAX_TEMPLATE_SIDE for v in size)):
            errors.append(f"{ctx}.size: two whole numbers 1..{MAX_TEMPLATE_SIDE} (cells), not {size!r}")
        w = t.get("walkability")
        if not isinstance(w, (int, float)) or isinstance(w, bool) or not 0 <= float(w) <= 1:
            errors.append(f"{ctx}.walkability: a number 0..1, not {w!r}")
        if "forSleep" in t and not isinstance(t["forSleep"], bool):
            errors.append(f"{ctx}.forSleep: true or false, not {t['forSleep']!r}")
        for k in ("description", "physicalDescription", "rule"):
            if not _is_str(t.get(k)):
                errors.append(f"{ctx}.{k}: required, one sentence ({'concrete placement guideline' if k == 'rule' else 'in-world'})")
        if not isinstance(t.get("tags", []), list):
            errors.append(f"{ctx}.tags: must be a list of short tags")
    return errors[:MAX_ERRORS]


def sanitize_p2(d, log):
    out, seen = [], set()
    for t in d.get("templates", []) or []:
        if not isinstance(t, dict) or not _is_str(t.get("name")) or t["name"] in seen:
            log.append((f"template {t.get('name') if isinstance(t, dict) else t}",
                        "dropped: bad or duplicate name"))
            continue
        size = t.get("size")
        if not (isinstance(size, list) and len(size) == 2
                and all(_check_int(v) and 1 <= v <= MAX_TEMPLATE_SIDE for v in size)):
            fixed = [min(MAX_TEMPLATE_SIDE, max(1, v)) if _check_int(v) else 1
                     for v in (size if isinstance(size, list) and len(size) == 2 else [1, 1])]
            log.append((f"template {t['name']}", f"size {size!r} -> {fixed}"))
            t["size"] = fixed
        w = t.get("walkability")
        if not isinstance(w, (int, float)) or isinstance(w, bool) or not 0 <= float(w) <= 1:
            log.append((f"template {t['name']}", f"walkability {w!r} -> 0"))
            t["walkability"] = 0.0
        if not isinstance(t.get("forSleep"), bool):
            if "forSleep" in t:
                log.append((f"template {t['name']}",
                            f"forSleep {t['forSleep']!r} -> {_sleeps(t['name'], t.get('tags'))}"))
            t["forSleep"] = _sleeps(t["name"], t.get("tags"))
        if not isinstance(t.get("tags", []), list):
            t["tags"] = []
        _sanitize_light(t, log)
        for k in ("description", "physicalDescription", "rule"):
            if not _is_str(t.get(k)):
                t[k] = {"description": t["name"], "physicalDescription": t["name"],
                        "rule": "place anywhere free"}[k]
        seen.add(t["name"])
        out.append(t)
    d["templates"] = out
    return d


def _sanitize_light(t, log):
    """``light`` is a strength 0..1 (clamped; anything else dropped). The
    lights extension's ``lightKind`` must be one of its kinds and
    ``lightColor`` a #rrggbb colour; a bad one is dropped, never retried."""
    from .extensions.lights import COLOR_RE, KINDS
    v = t.get("light")
    if v is not None:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if not 0 <= v <= 1:
                log.append((f"template {t['name']}", f"light {v!r} -> {min(1, max(0, v))}"))
                t["light"] = min(1, max(0, v))
        else:
            log.append((f"template {t['name']}", f"light {v!r} dropped"))
            del t["light"]
    kind = t.get("lightKind")
    if kind is not None:
        k = kind.strip().lower() if isinstance(kind, str) else None
        if k in KINDS:
            t["lightKind"] = k
        else:
            log.append((f"template {t['name']}", f"lightKind {kind!r} dropped"))
            del t["lightKind"]
    color = t.get("lightColor")
    if color is not None and not (isinstance(color, str) and COLOR_RE.match(color)):
        log.append((f"template {t['name']}", f"lightColor {color!r} dropped"))
        del t["lightColor"]


# --------------------------------------------------------- P3 one building

OPENING_KINDS = ("gallery", "atrium", "stairwell")


def check_p3(d, building_name, templates, has_yard, storeys=None):
    """``storeys`` is the building's P1 storey count with the floors
    extension enabled (None when it is off, so upper/stairs are ignored)."""
    errors = []
    ctx = f"building {building_name}"
    if not isinstance(d, dict):
        return [f"{ctx}: the reply is not a JSON object"]
    if d.get("name") != building_name:
        errors.append(f"{ctx}: reply name must be exactly {building_name!r}, not {d.get('name')!r}")
    _enum(d, "wall", WALLS, ctx, errors)
    if not _is_str(d.get("ground")):
        errors.append(f"{ctx}.ground: required, one or two words")
    rooms = d.get("rooms")
    if not isinstance(rooms, list) or not rooms:
        errors.append(f"{ctx}.rooms: required, 1-4 rooms")
        rooms = []
    rnames = set()
    for i, r in enumerate(rooms):
        if not isinstance(r, dict) or not _is_str(r.get("name")):
            errors.append(f"{ctx}.rooms[{i}].name: required")
            continue
        if r["name"] in rnames:
            errors.append(f"{ctx}.rooms[{i}].name: {r['name']!r} used twice")
        else:
            rnames.add(r["name"])
        _enum(r, "share", SHARES, f"{ctx}.room {r['name']}", errors)
    for i, c in enumerate(d.get("connections", []) or []):
        if not (isinstance(c, list) and len(c) == 2 and all(x in rnames for x in c)):
            errors.append(f"{ctx}.connections[{i}]: must be two room names that exist, not {c!r}")
    e = d.get("entrance")
    if not isinstance(e, dict):
        errors.append(f"{ctx}.entrance: required {{room, side}}")
    else:
        if e.get("room") not in rnames:
            errors.append(f"{ctx}.entrance.room: must be one of the rooms")
        _enum(e, "side", SIDES, f"{ctx}.entrance", errors)
    furn = d.get("furniture", [])
    if not isinstance(furn, list):
        errors.append(f"{ctx}.furniture: must be a list")
    else:
        for i, f in enumerate(furn):
            if not isinstance(f, dict):
                errors.append(f"{ctx}.furniture[{i}]: must be an object")
                continue
            if f.get("template") not in templates:
                errors.append(f"{ctx}.furniture[{i}]: template {f.get('template')!r} is not in the catalogue")
            if f.get("room") not in rnames:
                errors.append(f"{ctx}.furniture[{i}]: room {f.get('room')!r} is not one of the rooms")
            c = f.get("count", 1)
            if not _check_int(c) or not 1 <= c <= MAX_COUNT:
                errors.append(f"{ctx}.furniture[{i}]: count must be 1..{MAX_COUNT}, not {c!r}")
            errors.extend(hint_errors(f.get("hint", ""), templates=templates))
    y = d.get("yard")
    if y is not None:
        if not isinstance(y, dict) or not isinstance(y.get("props", []), list):
            errors.append(f"{ctx}.yard: null or {{\"props\": [...]}}")
        else:
            if not has_yard:
                errors.append(f"{ctx}.yard: this building has no yard in the plan; reply null")
            errors.extend(_prop_errors(y.get("props", []), f"{ctx}.yard.props", templates,
                                       max_count=MAX_COUNT))
    if storeys is not None and storeys > 1:
        st = d.get("stairs")
        if not isinstance(st, dict) or st.get("room") not in rnames:
            errors.append(f"{ctx}.stairs: required {{\"room\": ...}} naming a ground "
                          f"room, not {st!r}")
        errors.extend(_upper_errors(d.get("upper", []), rnames, templates, storeys, ctx))
    return errors[:MAX_ERRORS]


def _upper_errors(upper, ground_rooms, templates, storeys, ctx):
    """Contract violations in a P3 reply's "upper" storeys."""
    errors = []
    if not isinstance(upper, list):
        return [f"{ctx}.upper: must be a list of storey objects"]
    seen = set()
    for i, u in enumerate(upper):
        uctx = f"{ctx}.upper[{i}]"
        if not isinstance(u, dict):
            errors.append(f"{uctx}: must be an object")
            continue
        s = u.get("storey")
        if not _check_int(s) or not 2 <= s <= storeys:
            errors.append(f"{uctx}.storey: a whole number 2..{storeys}, not {s!r}")
        elif s in seen:
            errors.append(f"{uctx}.storey: floor {s} listed twice")
        else:
            seen.add(s)
        rooms = u.get("rooms")
        if not isinstance(rooms, list) or not rooms:
            errors.append(f"{uctx}.rooms: required, 1-4 rooms")
            rooms = []
        rnames = set()
        for j, r in enumerate(rooms):
            if not isinstance(r, dict) or not _is_str(r.get("name")):
                errors.append(f"{uctx}.rooms[{j}].name: required")
                continue
            if r["name"] in rnames:
                errors.append(f"{uctx}.rooms[{j}].name: {r['name']!r} used twice")
            else:
                rnames.add(r["name"])
            _enum(r, "share", SHARES, f"{uctx}.room {r['name']}", errors)
        for k, c in enumerate(u.get("connections", []) or []):
            if not (isinstance(c, list) and len(c) == 2 and all(x in rnames for x in c)):
                errors.append(f"{uctx}.connections[{k}]: must be two of this storey's "
                              f"room names, not {c!r}")
        furn = u.get("furniture", [])
        if not isinstance(furn, list):
            errors.append(f"{uctx}.furniture: must be a list")
        else:
            for k, f in enumerate(furn):
                if not isinstance(f, dict):
                    errors.append(f"{uctx}.furniture[{k}]: must be an object")
                    continue
                if f.get("template") not in templates:
                    errors.append(f"{uctx}.furniture[{k}]: template {f.get('template')!r} "
                                  f"is not in the catalogue")
                if f.get("room") not in rnames:
                    errors.append(f"{uctx}.furniture[{k}]: room {f.get('room')!r} is not "
                                  f"one of this storey's rooms")
                c = f.get("count", 1)
                if not _check_int(c) or not 1 <= c <= MAX_COUNT:
                    errors.append(f"{uctx}.furniture[{k}]: count must be 1..{MAX_COUNT}, not {c!r}")
                errors.extend(hint_errors(f.get("hint", ""), templates=templates))
        op = u.get("opening")
        if op is not None:
            if not isinstance(op, dict):
                errors.append(f"{uctx}.opening: null or {{\"over_room\", \"kind\"}}")
            else:
                if op.get("over_room") not in ground_rooms:
                    errors.append(f"{uctx}.opening.over_room: must be a ground room name, "
                                  f"not {op.get('over_room')!r}")
                _enum(op, "kind", OPENING_KINDS, f"{uctx}.opening", errors)
    return errors


def sanitize_p3(d, building_name, templates, log, storeys=None):
    """``storeys`` is the building's P1 storey count with floors enabled
    (None when it is off, so upper/stairs are stripped)."""
    d["name"] = building_name
    if d.get("wall") not in WALLS:
        log.append((f"building {building_name}", f"wall {d.get('wall')!r} -> 'wood'"))
        d["wall"] = "wood"
    if not _is_str(d.get("ground")):
        d["ground"] = "wood"
    rooms = [r for r in (d.get("rooms") or [])
             if isinstance(r, dict) and _is_str(r.get("name"))]
    if not rooms:
        log.append((f"building {building_name}", "no usable rooms; using one 'Hall' room"))
        rooms = [{"name": "Hall", "share": "medium", "purpose": d.get("ground", "") or "hall"}]
    rnames = []
    for r in rooms:
        if r["name"] in rnames:
            log.append((f"building {building_name}", f"room {r['name']!r} renamed duplicate"))
            r["name"] = r["name"] + " 2"
        rnames.append(r["name"])
        if r.get("share") not in SHARES:
            r["share"] = "medium"
    d["rooms"] = rooms
    d["connections"] = [c for c in (d.get("connections") or [])
                        if isinstance(c, list) and len(c) == 2
                        and c[0] in rnames and c[1] in rnames and c[0] != c[1]]
    e = d.get("entrance") if isinstance(d.get("entrance"), dict) else {}
    if e.get("room") not in rnames:
        e["room"] = rnames[0] if rnames else ""
    if e.get("side") not in SIDES:
        e["side"] = "south"
    d["entrance"] = e
    furn = []
    for f in (d.get("furniture") or []):
        if not isinstance(f, dict) or f.get("template") not in templates or f.get("room") not in rnames:
            log.append((f"building {building_name}",
                        f"furniture {f.get('template') if isinstance(f, dict) else f!r} dropped: "
                        "unknown template or room"))
            continue
        if not _check_int(f.get("count", 1)) or not 1 <= f["count"] <= MAX_COUNT:
            f["count"] = 1
        if hint_errors(f.get("hint", ""), templates=templates):
            log.append((f"building {building_name}",
                        f"furniture {f['template']} hint {f.get('hint')!r} -> ''"))
            f["hint"] = ""
        furn.append(f)
    d["furniture"] = furn
    y = d.get("yard")
    if isinstance(y, dict):
        props = []
        for p in (y.get("props") or []):
            if isinstance(p, dict) and p.get("template") in templates \
                    and not hint_errors(p.get("hint", ""), templates=templates):
                p.setdefault("count", 1)
                if not _check_int(p.get("count")) or not 1 <= p.get("count") <= MAX_COUNT:
                    p["count"] = 1
                props.append(p)
            else:
                log.append((f"building {building_name}",
                            f"yard prop {p.get('template') if isinstance(p, dict) else p!r} dropped"))
        y["props"] = props
    else:
        d["yard"] = None
    d["upper"], d["stairs"] = _sanitize_upper(d, building_name, rnames, templates, log, storeys)
    return d


def _sanitize_upper(d, building_name, ground_rooms, templates, log, storeys):
    """(upper list, stairs) cleaned against the floors contract. Without the
    extension, or for a single-storey building, both come back empty."""
    if storeys is None or storeys < 2:
        if storeys is None and ("upper" in d or "stairs" in d):
            log.append((f"building {building_name}",
                        "upper/stairs dropped: the floors extension is off"))
        return [], None
    ground_rooms = set(ground_rooms)
    st = d.get("stairs")
    if isinstance(st, dict) and st.get("room") in ground_rooms:
        stairs = {"room": st["room"]}
    else:
        if st is not None:
            log.append((f"building {building_name}",
                        f"stairs {st!r} dropped: not a ground room name"))
        stairs = None
    out, seen = [], set()
    for u in (d.get("upper") or []):
        label = f"upper storey {u.get('storey')!r} of {building_name}"
        if not isinstance(u, dict) or not _check_int(u.get("storey")) \
                or not 2 <= u["storey"] <= storeys or u["storey"] in seen:
            log.append((f"building {building_name}",
                        f"{label} dropped: bad or duplicate storey (building has {storeys})"))
            continue
        rooms, names = [], []
        for r in (u.get("rooms") or []):
            if not isinstance(r, dict) or not _is_str(r.get("name")):
                continue
            if r["name"] in names:
                log.append((f"building {building_name}",
                            f"room {r['name']!r} in {label} renamed duplicate"))
                r["name"] = r["name"] + " 2"
            names.append(r["name"])
            if r.get("share") not in SHARES:
                r["share"] = "medium"
            rooms.append(r)
        if not rooms:
            log.append((f"building {building_name}", f"{label} dropped: no usable rooms"))
            continue
        connections = [c for c in (u.get("connections") or [])
                       if isinstance(c, list) and len(c) == 2
                       and c[0] in names and c[1] in names and c[0] != c[1]]
        furn = []
        for f in (u.get("furniture") or []):
            if not isinstance(f, dict) or f.get("template") not in templates or f.get("room") not in names:
                log.append((f"building {building_name}",
                            f"furniture {f.get('template') if isinstance(f, dict) else f!r} "
                            f"in {label} dropped: unknown template or room"))
                continue
            if not _check_int(f.get("count", 1)) or not 1 <= f["count"] <= MAX_COUNT:
                f["count"] = 1
            if hint_errors(f.get("hint", ""), templates=templates):
                log.append((f"building {building_name}",
                            f"furniture {f['template']} hint {f.get('hint')!r} -> ''"))
                f["hint"] = ""
            furn.append(f)
        op = u.get("opening")
        if isinstance(op, dict) and op.get("over_room") in ground_rooms \
                and op.get("kind") in OPENING_KINDS:
            opening = {"over_room": op["over_room"], "kind": op["kind"]}
        else:
            if op is not None:
                log.append((f"building {building_name}",
                            f"opening {op if not isinstance(op, dict) else op.get('over_room')!r} "
                            f"in {label} dropped: bad over_room or kind"))
            opening = None
        seen.add(u["storey"])
        out.append({"storey": u["storey"], "rooms": rooms, "connections": connections,
                    "furniture": furn, "opening": opening})
    return out, stairs


# ------------------------------------------------------------- P4 one zone

def check_p4(d, zone_name, templates, building_names):
    errors = []
    ctx = f"zone {zone_name}"
    if not isinstance(d, dict):
        return [f"{ctx}: the reply is not a JSON object"]
    _enum(d, "paths", PATH_KINDS, ctx, errors)
    props = d.get("props", [])
    if not isinstance(props, list):
        errors.append(f"{ctx}.props: must be a list")
    else:
        errors.extend(_prop_errors(props, f"{ctx}.props", templates,
                                   buildings=set(building_names), max_count=40))
    filler = d.get("filler", [])
    if not isinstance(filler, list):
        errors.append(f"{ctx}.filler: must be a list")
    else:
        for i, f in enumerate(filler):
            if not isinstance(f, dict):
                errors.append(f"{ctx}.filler[{i}]: must be an object")
                continue
            if f.get("template") not in templates:
                errors.append(f"{ctx}.filler[{i}]: template {f.get('template')!r} is not in the catalogue")
            _enum(f, "density", FILL_DENSITY, f"{ctx}.filler[{i}]", errors)
    return errors[:MAX_ERRORS]


def sanitize_p4(d, templates, log, zone_name, buildings=()):
    buildings = set(buildings)
    if d.get("paths") not in PATH_KINDS:
        log.append((f"zone {zone_name}", f"paths {d.get('paths')!r} -> 'dirt'"))
        d["paths"] = "dirt"
    props = []
    for p in (d.get("props") or []):
        if isinstance(p, dict) and p.get("template") in templates \
                and not hint_errors(p.get("hint", ""), templates=templates,
                                    buildings=buildings):
            if not _check_int(p.get("count", 1)) or not 1 <= p["count"] <= 40:
                p["count"] = 1
            props.append(p)
        else:
            log.append((f"zone {zone_name}",
                        f"prop {p.get('template') if isinstance(p, dict) else p!r} dropped"))
    d["props"] = props
    filler = []
    for f in (d.get("filler") or []):
        if isinstance(f, dict) and f.get("template") in templates and f.get("density") in FILL_DENSITY:
            filler.append(f)
        else:
            log.append((f"zone {zone_name}",
                        f"filler {f.get('template') if isinstance(f, dict) else f!r} dropped"))
    d["filler"] = filler
    return d


# ----------------------------------------------------------------- P5 people

def check_p5(d, buildings, zones, bedded=None):
    errors = []
    if not isinstance(d, dict):
        return ["P5: the reply is not a JSON object"]
    people = d.get("npcs")
    if not isinstance(people, list) or not people:
        errors.append("npcs: required, a non-empty list")
        people = []
    for i, p in enumerate(people):
        errors.extend(_person_errors(p, f"npcs[{i}]", buildings, zones, bedded))
    errors.extend(_person_errors(d.get("player"), "player", buildings, zones, bedded))
    return errors[:MAX_ERRORS]


def _person_errors(p, ctx, buildings, zones, bedded=None):
    if not isinstance(p, dict):
        return [f"{ctx}: must be an object"]
    errors = []
    if not _is_str(p.get("name")):
        errors.append(f"{ctx}.name: required")
    if p.get("gender") not in ("male", "female"):
        errors.append(f"{ctx}.gender: 'male' or 'female', not {p.get('gender')!r}")
    if not _is_str(p.get("role")):
        errors.append(f"{ctx}.role: required, their trade or place")
    if buildings and p.get("home") not in buildings:
        errors.append(f"{ctx}.home: must be a building from the list, not {p.get('home')!r}")
    if bedded and p.get("home") not in bedded:
        errors.append(f"{ctx}.home: {p.get('home')!r} has no bed; homes need a bed "
                      "(a real bed, in the furniture)")
    if p.get("work") not in buildings | zones:
        errors.append(f"{ctx}.work: must be a building or zone from the lists, not {p.get('work')!r}")
    for k in ("description", "physicalDescription"):
        if not _is_str(p.get(k)):
            errors.append(f"{ctx}.{k}: required, one sentence")
    return errors


def sanitize_p5(d, buildings, zones, log, bedded=()):
    bedded = [b for b in bedded if b in set(buildings)]
    npcs = []
    for p in (d.get("npcs") or []):
        errs = _person_errors(p, f"npc {p.get('name') if isinstance(p, dict) else p!r}",
                              set(buildings), set(zones))
        if errs:
            log.append((f"npc {p.get('name') if isinstance(p, dict) else p!r}",
                        "dropped: " + "; ".join(errs[:3])))
            continue
        if bedded and p["home"] not in bedded:
            log.append((f"npc {p['name']}",
                        f"home {p['home']!r} has no bed -> re-homed to {bedded[0]!r}"))
            p["home"] = bedded[0]
        npcs.append(p)
    d["npcs"] = npcs
    player = d.get("player") if isinstance(d.get("player"), dict) else {}
    if not _is_str(player.get("name")):
        player["name"] = "The Traveller"
    if player.get("gender") not in ("male", "female"):
        player["gender"] = "female"
    if not _is_str(player.get("role")):
        player["role"] = "traveller"
    if buildings and player.get("home") not in buildings:
        log.append(("player", f"home {player.get('home')!r} -> {buildings[0]!r}"))
        player["home"] = buildings[0]
    if bedded and player.get("home") not in bedded:
        log.append(("player", f"home {player['home']!r} has no bed -> re-homed to {bedded[0]!r}"))
        player["home"] = bedded[0]
    if player.get("work") not in set(buildings) | set(zones):
        player["work"] = player["home"] or (zones[0] if zones else "")
    for k in ("description", "physicalDescription"):
        if not _is_str(player.get(k)):
            player[k] = "A traveller with a reason to stay."
    d["player"] = player
    return d


# ------------------------------------------------------------------ the run

def run_phases(idea, client, extensions=(), progress=None, cancel=None):
    """Run P1-P5 with `client`. Returns (plan_dict, stats). Raises PhaseError
    when a structural phase (P1, P2) cannot be salvaged, Cancelled when
    ``cancel()`` turns true between calls. ``extensions`` adds the enabled
    mod extensions' prompt fragments and contract checks. ``progress`` gets
    one dict per model call, before it is made:
    ``{"phase": "P3", "label": "building 3/10: The Old Mill", "calls": 5,
    "tokens": 1234}`` — ``calls`` counts the call about to happen."""
    from .extensions import expand
    exts = expand(extensions)
    floors = "floors" in exts
    stats = {"phase_log": [], "dropped": []}

    def call(phase, tname, event=None, **kw):
        if cancel is not None and cancel():
            raise Cancelled(f"cancelled before the {phase} call")
        if progress is not None:
            progress({"phase": (event or (phase.upper(), tname))[0],
                      "label": (event or (phase.upper(), tname))[1],
                      "calls": client.calls + 1,
                      "tokens": client.tokens["total"]})
        t0 = time.time()
        before = (client.retries, client.tokens["total"])
        result = client.call(phase, "You generate scenario data for a map RPG. "
                              "You reply with one JSON object and nothing else.",
                              assemble_prompt(tname, exts, **kw),
                              validate=kw.pop("_validate", None))
        stats["phase_log"].append({
            "phase": phase,
            "seconds": round(time.time() - t0, 1),
            "retries": client.retries - before[0],
            "tokens": client.tokens["total"] - before[1],
        })
        return result

    # ---- P1: the world plan
    p1 = call("p1", "p1-world", event=("P1", "the world plan"), idea=idea,
              _validate=lambda x: check_p1(x, floors=floors))
    if p1 is None:
        raise PhaseError("P1 produced no JSON at all")
    p1 = sanitize_p1(p1, stats["dropped"], floors=floors)
    if not p1["zones"]:
        raise PhaseError("P1 produced no usable zones")

    # ---- P2: the prop catalogue
    setting_line = _setting_line(p1)
    zone_lines = "\n".join(
        f"- {_zone_line(z)}\n"
        f"  buildings: {'; '.join(_building_line(b) for b in z['buildings']) or 'none'}\n"
        f"  outdoor features: {', '.join(map(str, z.get('outdoor') or [])) or 'none'}"
        for z in p1["zones"])
    p2 = call("p2", "p2-catalogue", event=("P2", "the prop catalogue"),
              setting_line=setting_line, zone_lines=zone_lines, _validate=check_p2)
    if p2 is None:
        raise PhaseError("P2 produced no JSON at all")
    p2 = sanitize_p2(p2, stats["dropped"])
    if not p2["templates"]:
        raise PhaseError("P2 produced no usable templates")
    templates = p2["templates"]
    tnames = {t["name"] for t in templates}
    catalogue = _catalogue_lines(templates)

    # ---- P3: one call per building
    designs = []
    n_buildings = sum(len(z["buildings"]) for z in p1["zones"])
    seen_buildings = 0
    for z in p1["zones"]:
        keep = []
        for b in z["buildings"]:
            seen_buildings += 1
            zl = _zone_line(z)
            d = call(f"p3-{slug(b['name'])}", "p3-building",
                     event=("P3", f"building {seen_buildings}/{n_buildings}: {b['name']}"),
                     setting_line=setting_line, zone_line=zl,
                     building_line=_building_line(b), catalogue_lines=catalogue,
                     compound_line=_compound_line(p1.get("compounds") or [], z, b),
                     building_name=b["name"],
                     _validate=lambda x, n=b["name"], y=bool(b.get("yard")),
                     s=(b.get("storeys", 1) if floors else None):
                     check_p3(x, n, tnames, y, storeys=s))
            if d is None:
                stats["dropped"].append((f"building {b['name']}",
                                         "dropped: P3 produced no JSON, keeping the P1 shell"))
                keep.append(b)   # parse_plan furnishes a one-room fallback
                continue
            designs.append(sanitize_p3(d, b["name"], tnames, stats["dropped"],
                                       storeys=(b.get("storeys", 1) if floors else None)))
            keep.append(b)
        z["buildings"] = keep

    # ---- P4: one call per zone
    building_names = [b["name"] for z in p1["zones"] for b in z["buildings"]]
    n_zones = len(p1["zones"])
    for i, z in enumerate(p1["zones"], 1):
        blines = "\n".join(f"- {_building_line(b)}" for b in z["buildings"]) or "- none"
        d = call(f"p4-{slug(z['name'])}", "p4-zone",
                 event=("P4", f"zone {i}/{n_zones}: {z['name']}"),
                 setting_line=setting_line, zone_line=_zone_line(z),
                 building_lines=blines, catalogue_lines=catalogue,
                 _validate=lambda x, n=z["name"]: check_p4(x, n, tnames, building_names))
        if d is None:
            stats["dropped"].append((f"zone {z['name']}", "dressing: no JSON, using dirt paths"))
            z["dressing"] = {"paths": "dirt", "props": [], "filler": []}
        else:
            z["dressing"] = sanitize_p4(d, tnames, stats["dropped"], z["name"],
                                        building_names)

    # ---- P5: people
    zlines = "\n".join(f"- {_zone_line(z)}" for z in p1["zones"])
    blines = "\n".join(f"- {_building_line(b)}" for b in
                       (b for z in p1["zones"] for b in z["buildings"]))
    zone_names = [z["name"] for z in p1["zones"]]
    # homes need a placed-able bed: the builder requires a forSleep object
    # wherever a person sleeps
    bed_templates = {t["name"] for t in templates
                     if t.get("forSleep") or _sleeps(t["name"], t.get("tags"))}
    design_by_name = {b["name"]: b for b in designs}

    def _has_bed(design):
        lines = list(design.get("furniture") or [])
        for u in design.get("upper") or []:
            lines += u.get("furniture") or []
        return any(f.get("template") in bed_templates for f in lines)

    bedded = [b["name"] for b in (bb for z in p1["zones"] for bb in z["buildings"])
              if _has_bed(design_by_name.get(b["name"], {}))]
    p5 = call("p5", "p5-people", event=("P5", "people and schedules"),
              setting_line=setting_line, zone_lines=zlines, building_lines=blines,
              _validate=lambda x: check_p5(x, set(building_names), set(zone_names),
                                           set(bedded)))
    if p5 is None:
        stats["dropped"].append(("people", "P5 produced no JSON; using a default player"))
        p5 = {"npcs": [], "player": {}}
    else:
        p5 = sanitize_p5(p5, building_names, zone_names, stats["dropped"], bedded)

    plan = {
        "name": p1.get("name", "Generated World"),
        "worldBackground": p1.get("worldBackground", ""),
        "setting": p1.get("setting", {}),
        "mapSize": p1.get("mapSize", "small"),
        "zones": p1["zones"],
        "roads": p1.get("roads", []),
        "templates": templates,
        "buildings": designs,
        "npcs": p5["npcs"],
        "player": p5["player"],
    }
    return plan, stats


def write_plan(plan, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=1, ensure_ascii=False)
