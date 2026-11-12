"""Post-layout checks: overlap and containment, reachability on a walkability
grid (every room from its entrance, every entrance from a road; the stair
portals count as connections), walkways and doors clear, density, and
unplaced pieces with reasons. With the floors extension: floor areas the
size of their ground region, storeys sealed (no opening on their outer
border), portal ends that exist, walkable stairs, upper rooms reachable from
their stairs, and the 1.0 layout — every storey its own plane east of the
play area, 24 cells apart. Results go to metrics.json (the pipeline writes
the dict; run_checks returns it).

The walkability model mirrors build_scenario.py exactly: the outer ring of a
walled region is wall except at door openings, and walkability-0 objects block.
"""
from .layout_room import object_cells
from .model import Rect, shared_wall_cells
from .phases import RUIN_WORDS, STAIR_WORDS, ruined_building, stair_furniture_name


def _ring(rect):
    return {c for c in rect.cells() if c[0] in (rect.x, rect.x1) or c[1] in (rect.y, rect.y1)}


def compute_openings(world):
    """All door cells per region name: explicit doors plus the builder's
    auto-connect between touching walled siblings with the same parent."""
    openings = {r.name: set(r.doors) for r in world.regions}
    walled = [r for r in world.regions if r.wall]
    for i, a in enumerate(walled):
        for b in walled[i + 1:]:
            if a.parent != b.parent:
                continue
            for cell in shared_wall_cells(a.rect, b.rect):
                openings[a.name].add(cell)
                openings[b.name].add(cell)
    # an explicit door cell counts for every walled region whose edge it is on
    for r in world.regions:
        for cell in list(r.doors):
            for w in walled:
                if w.rect.contains_cell(cell) and cell in _ring(w.rect):
                    openings[w.name].add(cell)
    return openings


def _base_grid(world, openings):
    """(blocked_cells, door_cells) of the built shapes alone: the walls of
    walled regions (minus their doorways) and walkability-0 objects."""
    blocked = set()
    doors = set()
    for r in world.regions:
        if r.wall:
            ring = _ring(r.rect)
            doors |= openings[r.name]
            blocked |= (ring - openings[r.name])
    for o in world.objects:
        t = world.templates[o.template]
        if t.walkability <= 0:
            blocked |= object_cells(world, o)
    return blocked, doors


def walkability_grid(world, openings):
    """(blocked_cells, door_cells) over the whole map: walls, solid objects
    and deep water. Shallow water is waded — walk "slow" — so it stays
    walkable; deep water has walk "no" and blocks like a wall."""
    from . import native
    blocked, doors = _base_grid(world, openings)
    blocked |= native.deep_cells(world)
    return blocked, doors


def _planes(world):
    """The rects a cell may exist on: the map (the play area) and, when the
    floors extension ran, every storey plane east of it — 1.0 floors sit
    outside gridSize, but their cells are as real as the map's."""
    planes = [Rect(0, 0, world.grid[0], world.grid[1])]
    planes += [f.rect for f in getattr(world, "floors", []) or []]
    return planes


def on_a_plane(world, cell):
    """Whether `cell` sits on the map or one of the storey planes."""
    return any(p.contains_cell(cell) for p in _planes(world))


def flood(world, starts, blocked, jumps=None):
    """Cells reachable from `starts`: four-way through unblocked cells, plus
    any jump edges (stair portals), which connect two cells directly. A cell
    off the map counts while it sits on a storey plane."""
    planes = _planes(world)

    def exists(c):
        return any(p.contains_cell(c) for p in planes)

    seen = set(s for s in starts if exists(s) and s not in blocked)
    todo = list(seen)
    while todo:
        x, y = todo.pop()
        nxt = ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
        if jumps:
            nxt += tuple(jumps.get((x, y), ()))
        for c in nxt:
            if exists(c) and c not in seen and c not in blocked:
                seen.add(c)
                todo.append(c)
    return seen


def portal_jumps(world):
    """{cell: [cells]} for the two ends of every linked pair (stairs, wall-walk
    passages): stepping onto a pad is stepping onto the pad it pairs with —
    the game's own portals."""
    ends = {n: o.pos for o, n in object_entity_names(world).items()}
    out = {}
    for p in getattr(world, "portals", None) or []:
        a = ends.get((p.get("from") or {}).get("object"))
        b = ends.get((p.get("to") or {}).get("object"))
        if a is None or b is None:
            continue
        out.setdefault(a, []).append(b)
        out.setdefault(b, []).append(a)
    return out


def dropped_failures(failures):
    """The failures that mean planned content was dropped: a building with no
    space in its zone, a zone that never placed, a storey reduced to
    single-storey, a compound (or part of one) nobody can walk to. These are
    errors, not notes — the command exits non-zero."""
    out = []
    for (what, reason) in failures:
        if (what.startswith("building ") and reason == "no space in zone") \
                or (what.startswith("zone ") and reason == "not placed") \
                or (what.startswith("floors of ") and "single-storey" in reason) \
                or (what.startswith("compound ") and "not reachable" in reason):
            out.append((what, reason))
    return out


def object_entity_names(world):
    """{object: builder entity name} — "<template> <i>" numbered per template
    in placement order, exactly as build_scenario.py names object entities."""
    counts, names = {}, {}
    for o in world.objects:
        counts[o.template] = counts.get(o.template, 0) + 1
        names[o] = f"{o.template} {counts[o.template]}"
    return names


def _gap(a, b):
    """Cells between two rects (0 if they touch or overlap), measured like a
    king moves — the same rule the game's own floor layout keeps."""
    return max(0, b.x - a.x1 - 1, a.x - b.x1 - 1, b.y - a.y1 - 1, a.y - b.y1 - 1)


def _floors_checks(world, blocked):
    """Issues with the placed upper storeys: floor areas the size of their
    `above` region, no opening on a storey's outer border, portal ends that
    exist and belong to one portal each, walkable stairs in separate cells,
    upper rooms reachable from their stairs, and the 1.0 layout itself —
    every storey its own plane, east of the play area, none closer than
    FLOOR_GAP cells to the map or each other."""
    issues = []
    names = object_entity_names(world)
    name_set = {n.lower() for n in names.values()}
    regions = {r.name: r for r in world.regions}
    region_set = {n.lower() for n in regions}
    openings = compute_openings(world)
    floors = list(getattr(world, "floors", []) or [])

    for f in floors:
        above = regions.get(f.above)
        if above is None:
            issues.append(f"{f.region_name}: above region {f.above!r} does not exist")
        elif (f.rect.w, f.rect.h) != (above.rect.w, above.rect.h):
            issues.append(f"{f.region_name} is {f.rect.w}x{f.rect.h} but sits over "
                          f"{f.above} at {above.rect.w}x{above.rect.h}")
        # sealed: no opening at all on the outer border of the storey's
        # floor area — its only ways in and out are its stairs and passages
        ring = _ring(f.rect)
        part_names = [f.region_name] + [r.full_name for r in f.layout.rooms
                                        if r.full_name != f.region_name]
        for name in part_names:
            hit = openings.get(name, set()) & ring
            if hit:
                issues.append(f"{name} has an exterior opening at {sorted(hit)}; "
                              f"its only ways in and out are its stairs")
        if f.stair_down is None and f.stair_up is None and not f.passages:
            issues.append(f"{f.region_name} has no stairs and no passage to "
                          f"another storey; nobody can reach it")
        for label, ref in (("stair down", f.stair_down),
                           ("stair up", f.stair_up),
                           ("stair below's up stair", f.stair_below_up)):
            if ref is None:
                continue   # the top storey has no stair up
            t = world.templates.get(ref[0])
            if t is None:
                issues.append(f"{f.region_name}: its {label} template {ref[0]!r} is missing")
            elif t.walkability <= 0:
                issues.append(f"{f.region_name}: its {label} ({ref[0]}) is not walkable")
        for ref in f.passages:
            t = world.templates.get(ref[0])
            if t is None:
                issues.append(f"{f.region_name}: its passage template {ref[0]!r} is missing")
            elif t.walkability <= 0:
                issues.append(f"{f.region_name}: its passage ({ref[0]}) is not walkable")
        # upper rooms reachable from this storey's stairs
        starts = [ref[1] for ref in (f.stair_down, f.stair_up) if ref is not None]
        if starts:
            seen = flood(world, starts, set(blocked))
            for room in f.layout.rooms:
                if not (room.rect.interior().cells() & seen):
                    issues.append(f"{room.base_name} on {f.region_name} is not "
                                  f"reachable from the stairs")
        # a storey with stairs both down and up has two separate stairs
        if f.stair_down is not None and f.stair_up is not None \
                and f.stair_down[1] == f.stair_up[1]:
            issues.append(f"{f.region_name}: its stairs down and up share one cell")
    # the 1.0 layout: every floor its own plane, east of the play area
    # (first at the map's width + FLOOR_GAP), FLOOR_GAP cells apart
    from .extensions.floors import FLOOR_GAP
    for i, f in enumerate(floors):
        if _gap(f.rect, Rect(0, 0, world.grid[0], world.grid[1])) < FLOOR_GAP:
            issues.append(f"{f.region_name} sits less than {FLOOR_GAP} cells east of "
                          f"the play area; the game lays floors out {FLOOR_GAP} cells "
                          f"beyond the map")
        for g in floors[i + 1:]:
            if _gap(f.rect, g.rect) < FLOOR_GAP:
                issues.append(f"{f.region_name} and {g.region_name} are less than "
                              f"{FLOOR_GAP} cells apart; each floor is a plane of its own")
    # every portal edge is its own pad: no object or cell may be the end of
    # more than one portal, from either side
    seen_ends = {}
    for p in getattr(world, "portals", []):
        for end in ("from", "to"):
            ref = p.get(end) or {}
            target = (ref.get("object") or ref.get("region") or "")
            if ref.get("object") and target.lower() not in name_set:
                issues.append(f"portal {p.get('name')!r}: object {target!r} does not exist")
            elif ref.get("region") and target.lower() not in region_set:
                issues.append(f"portal {p.get('name')!r}: region {target!r} does not exist")
            elif not target:
                issues.append(f"portal {p.get('name')!r}: {end} end names nothing")
            if ref.get("object"):
                key = ("object", target.lower())
            elif ref.get("region"):
                key = ("region", target.lower())
            elif ref.get("cell") is not None:
                key = ("cell", tuple(ref["cell"]))
            else:
                continue
            if key in seen_ends:
                issues.append(f"portal {p.get('name')!r}: its {end} end {target or key[1]!r} "
                              f"is already the {seen_ends[key]} end of another portal")
            else:
                seen_ends[key] = end
    return issues


def _compound_checks(world, from_player):
    """Issues with the placed compounds: every part's and every wall
    corridor's interior is reachable on foot, and so is the courtyard (a
    sealed courtyard means the gate never opened)."""
    issues = []
    for comp in getattr(world, "compounds", []) or []:
        if not (comp.courtyard.interior().cells() & from_player):
            issues.append((f"compound {comp.name}", "courtyard not reachable"))
        for b in comp.parts:
            if not (b.layout.rect.interior().cells() & from_player):
                issues.append((f"compound {comp.name} part {b.layout.design.name}",
                               "not reachable"))
        for c in comp.corridors:
            if c.rect.w < 3 or c.rect.h < 3:
                continue
            if not (c.rect.interior().cells() & from_player):
                issues.append((f"compound {comp.name} wall {c.name}", "not reachable"))
    return issues


def _ruined_at(scn, pos):
    """Whether `pos` sits inside a region the built scenario itself calls a
    ruin (a ruin word in its name or description) — a stair there may rise
    to a collapsed floor."""
    px, py = pos if isinstance(pos, (list, tuple)) and len(pos) == 2 \
        else (None, None)
    if not isinstance(px, int) or not isinstance(py, int):
        return False
    for r in scn.get("regions", []):
        x, y = r.get("position") or (None, None)
        w, h = r.get("size") or (0, 0)
        if not (isinstance(x, int) and isinstance(y, int)):
            continue
        if x <= px < x + w and y <= py < y + h and (
                RUIN_WORDS.search(r.get("name") or "")
                or RUIN_WORDS.search(r.get("description") or "")):
            return True
    return False


def check_scenario_mods(scenario_path, spec):
    """Issues with the built scenario.json against what the generator laid
    out: the arpgMods the spec carries (lights) must match exactly; every
    storey region must carry the right pocket; every linked pair's objects
    must point at each other; no sealed storey may keep an opening on its
    outer border; the floors must sit outside gridSize, FLOOR_GAP cells
    apart; every doorway whose room is not "none" must carry a door object,
    and no door object may sit anywhere but on a doorway; no stair-named
    object ships without a portal, unless it rises in a ruin. Locks: every key
    opens a region that exists, and every room the spec locked has doors.
    Nature: the natural shapes, water surfaces and vehicle fields landed on
    the built scenario, and nobody stands on deep water.
    Populations: every native population's home region exists, its sprite is
    one the game knows, and it landed on the built scenario. Members: every
    member entity's templateId names a built npcTemplate, its npcHome is one
    of that template's homes, it stands inside that home region, no home holds
    more members than its count, and every member the spec placed landed."""
    import json
    from . import native
    with open(scenario_path, "r", encoding="utf-8") as f:
        scn = json.load(f)
    issues = []
    # doors first, so the check runs for every world, floors or not
    doorway_keys = {dw["key"] for dw in native.doorways(scn)}
    doors = native.doors_by_key(scn)
    for dw in native.doorways(scn):
        if dw["room"].get("door", "door") == "none":
            continue
        if not doors.get(dw["key"]):
            issues.append(f"doorway {dw['key']} into "
                          f"{dw['room'].get('name')!r} has no door object")
    for key, on_key in doors.items():
        if key not in doorway_keys:
            issues.append(f"door object {on_key[0].get('name')!r} at "
                          f"{on_key[0].get('pos')} sits on no doorway")
    # no stairs to nowhere: a stair-named object linked to no portal leads
    # nowhere (the code places the real, linked stairs), unless it rises in
    # a region the scenario itself calls a ruin
    stair_templates = {t.get("id") for t in scn.get("objectTemplates") or []
                       if STAIR_WORDS.search(t.get("name") or "")}
    if stair_templates:
        ruin_stairs = set(((spec or {}).get("nativeStairs") or {}).get("ruined") or [])
        for e in scn.get("entities") or []:
            if e.get("type") != "object" \
                    or e.get("templateId") not in stair_templates \
                    or isinstance(e.get("portal"), dict):
                continue
            if e.get("name") not in ruin_stairs and not _ruined_at(scn, e.get("pos")):
                issues.append(f"stair object {e.get('name')!r} at "
                              f"{e.get('pos')} leads nowhere (no portal)")
    # 1.0 locks and keys: every key opens a region that exists, and every
    # room the spec locked carries doors to lock
    region_ids = {r.get("id") for r in scn.get("regions", [])}
    for t in scn.get("itemTemplates") or []:
        if t.get("opens") is not None and t.get("opens") not in region_ids:
            issues.append(f"key {t.get('name')!r} opens {t.get('opens')!r}, "
                          f"which is no region")
    for entry in ((spec or {}).get("nativeLocks") or {}).get("locks") or []:
        room = next((r for r in scn.get("regions", [])
                     if r.get("name") == entry.get("room")), None)
        if room is None:
            issues.append(f"locked room {entry.get('room')!r} is no region "
                          f"of the built scenario")
        elif not native.region_doors(scn, room):
            issues.append(f"locked room {entry.get('room')!r} has no doors")
    # 1.0 nature: the natural shapes, water surfaces and vehicle fields the
    # spec chose landed on the built scenario, and nothing that cannot swim
    # stands on deep water
    nature = (spec or {}).get("nativeNature") or {}
    if nature:
        from .vendor import scenario_checks as vendor
        by_name = {r.get("name"): r for r in scn.get("regions", [])}
        for name in nature.get("shape") or []:
            area = by_name.get(name)
            if area is None:
                issues.append(f"natural shape names region {name!r}, which "
                              f"the built scenario does not have")
            elif area.get("shape") not in ("natural", "organic"):
                issues.append(f"region {name!r} ships without its natural shape")
        for name in nature.get("water") or []:
            area = by_name.get(name)
            if area is None:
                issues.append(f"water surface names region {name!r}, which "
                              f"the built scenario does not have")
            elif area.get("surface") != "water":
                issues.append(f"region {name!r} ships without its water surface")
        for name, fields in (nature.get("vehicles") or {}).items():
            t = next((t for t in scn.get("objectTemplates") or []
                      if t.get("name") == name), None)
            if t is None:
                issues.append(f"vehicle {name!r} is no object template "
                              f"of the built scenario")
                continue
            for k, v in fields.items():
                if t.get(k) != v:
                    issues.append(f"vehicle {name!r} lost its {k} in the build")
        tpl = {t.get("id"): t for t in scn.get("objectTemplates") or []}
        wet = vendor.liquid_cells(scn, scn.get("regions") or [])
        for e in scn.get("entities") or []:
            if e.get("type") == "object":
                t = tpl.get(e.get("templateId")) or {}
                if t.get("vehicle"):
                    continue  # a boat is meant to sit on water
                hit = set(vendor.footprint(e, tpl)) & wet
                if hit:
                    issues.append(f"object {e.get('name')!r} stands on deep "
                                  f"water at {sorted(hit)[:4]}")
            elif e.get("type") in ("npc", "player") and \
                    tuple(e.get("pos") or ()) in wet:
                issues.append(f"{e.get('name')!r} starts on deep water")
    # 1.0 populations: every home region the spec names exists in the built
    # scenario, every sprite is one the game knows, and each template landed
    # on the built scenario with its homes resolved to the region ids
    pops = (spec or {}).get("nativePopulations") or []
    if pops:
        from .vendor import scenario_checks as vendor
        by_name = {r.get("name"): r for r in scn.get("regions", [])}
        built = {t.get("name"): t for t in scn.get("npcTemplates") or []}
        for p in pops:
            label = f"population {p.get('name')!r}"
            for h in p.get("homes") or []:
                if h.get("region") not in by_name:
                    issues.append(f"{label} names home region "
                                  f"{h.get('region')!r}, which the built "
                                  f"scenario does not have")
            if p.get("animationId") not in vendor.ANIMATIONS:
                issues.append(f"{label} plays unknown sprite "
                              f"{p.get('animationId')!r}")
            t = built.get(p.get("name"))
            if t is None:
                issues.append(f"{label} did not land on the built scenario")
                continue
            homes = {h.get("regionId"): h.get("count")
                     for h in t.get("homes") or []}
            for h in p.get("homes") or []:
                area = by_name.get(h.get("region"))
                if area is not None and \
                        homes.get(area.get("id")) != h.get("count"):
                    issues.append(f"{label} lost its home in "
                                  f"{h.get('region')!r} on the build")
        # the members the homes start with: every member entity belongs to a
        # built template, its npcHome is one of that template's homes, it
        # stands inside that home region, no home holds more members than its
        # count, and each member the spec placed landed on the build
        tpl_by_id = {t.get("id"): t for t in scn.get("npcTemplates") or []}
        region_by_id = {r.get("id"): r for r in scn.get("regions", [])}

        def holds(area, pos):
            x, y = (area or {}).get("position", (0, 0))
            w, h = (area or {}).get("size", (0, 0))
            return isinstance(pos, (list, tuple)) and len(pos) == 2 and \
                x <= pos[0] < x + w and y <= pos[1] < y + h

        landed = set()
        per_home = {}
        for e in scn.get("entities") or []:
            if e.get("type") != "npc" or not e.get("templateId"):
                continue
            label = f"population member {e.get('name')!r}"
            t = tpl_by_id.get(e.get("templateId"))
            if t is None:
                issues.append(f"{label} carries templateId "
                              f"{e.get('templateId')!r}, which is no built "
                              f"npcTemplate")
                continue
            rid = e.get("npcHome")
            homes = {h.get("regionId"): h.get("count")
                     for h in t.get("homes") or []}
            if rid not in homes:
                issues.append(f"{label} has npcHome {rid!r}, which is not a "
                              f"home of {t.get('name')!r}")
                continue
            if not holds(region_by_id.get(rid), e.get("pos")):
                issues.append(f"{label} stands at {e.get('pos')}, outside its "
                              f"home region "
                              f"{(region_by_id.get(rid) or {}).get('name')!r}")
            landed.add((e.get("templateId"), rid, tuple(e.get("pos") or ())))
            key = (e.get("templateId"), rid)
            per_home[key] = per_home.get(key, 0) + 1
        for (tid, rid), n in sorted(per_home.items(), key=lambda kv: str(kv[0])):
            t = tpl_by_id.get(tid) or {}
            count = next((h.get("count") for h in t.get("homes") or []
                          if h.get("regionId") == rid), 0)
            if n > count:
                issues.append(f"home {(region_by_id.get(rid) or {}).get('name')!r} "
                              f"holds {n} members of {t.get('name')!r}, more "
                              f"than its count {count}")
        for p in pops:
            t = built.get(p.get("name"))
            if t is None:
                continue     # reported above: it did not land
            for h in p.get("homes") or []:
                area = by_name.get(h.get("region"))
                if area is None:
                    continue  # reported above: no such region
                for cell in h.get("members") or []:
                    if (t.get("id"), area.get("id"), tuple(cell)) not in landed:
                        issues.append(f"population {p.get('name')!r} member at "
                                      f"{list(cell)} in {h.get('region')!r} did "
                                      f"not land on the built scenario")
    arpg_mods = (spec or {}).get("arpgMods")
    got = scn.get("arpgMods")
    if arpg_mods:
        if got != arpg_mods:
            bad = [k for k in set(got or {}) | set(arpg_mods)
                   if (got or {}).get(k) != arpg_mods.get(k)]
            issues += [f"built scenario.json arpgMods.{k} does not match the spec"
                       for k in sorted(bad)]
        # the lights mod finds its templates by exact name, and lights only those the game lights
        lit = {t.get("name"): t for t in scn.get("objectTemplates", [])}
        for name in ((arpg_mods.get("lights") or {}).get("templates") or {}):
            if name not in lit:
                issues.append(f"arpgMods.lights names {name!r}, which is not an object template")
            elif not lit[name].get("light"):
                issues.append(f"arpgMods.lights gives {name!r} a kind, but its light is 0")
    elif isinstance(got, dict) and ("floors" in got or "portals" in got):
        issues.append("built scenario.json has arpgMods.floors/portals; 1.0 floors "
                      "are native (pockets and portals), not a game mod")
    native = (spec or {}).get("nativeFloors") or {}
    if not native.get("floors"):
        return issues
    from .extensions.floors import FLOOR_GAP
    by_name = {r.get("name"): r for r in scn.get("regions", [])}
    gw, gh = (scn.get("gridSize") or [0, 0])[:2]
    rects = {}
    for fl in native["floors"]:
        area = by_name.get(fl["region"])
        if area is None:
            issues.append(f"built scenario.json has no region {fl['region']!r}")
            continue
        x, y = area.get("position", (0, 0))
        w, h = area.get("size", (0, 0))
        rects[fl["region"]] = (x, y, x + w - 1, y + h - 1)
        anchor = by_name.get(fl["anchor"])
        pocket = area.get("pocket")
        if not isinstance(pocket, dict):
            issues.append(f"{fl['region']!r} carries no pocket; the game reads it "
                          f"as an ordinary region")
        elif anchor is None:
            issues.append(f"{fl['region']!r} is anchored at {fl['anchor']!r}, "
                          f"which the built scenario does not have")
        elif pocket != {"anchor": anchor.get("id"), "level": fl["level"]}:
            issues.append(f"{fl['region']!r} has pocket {pocket}, not the laid-out "
                          f"{{anchor: {fl['anchor']!r}, level: {fl['level']}}}")
        # 1.0 floors are planes beside the map, not on it
        if x < gw + FLOOR_GAP or y < 0:
            issues.append(f"{fl['region']!r} at ({x},{y}) does not sit {FLOOR_GAP} cells "
                          f"east of the play area")
    names = list(rects)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = rects[a], rects[b]
            g = max(0, bx0 - ax1 - 1, ax0 - bx1 - 1, by0 - ay1 - 1, ay0 - by1 - 1)
            if g < FLOOR_GAP:
                issues.append(f"{a!r} and {b!r} are {g} cells apart, not {FLOOR_GAP}; "
                              f"each floor is a plane of its own")
    # every linked pair points both ways, at the laid-out ends
    objs = {e.get("name"): e for e in scn.get("entities", [])
            if e.get("type") == "object"}
    for pair in native.get("portals") or []:
        a, b = objs.get(pair["a"]), objs.get(pair["b"])
        for (side, e, other) in ((pair["a"], a, pair["b"]), (pair["b"], b, pair["a"])):
            if e is None:
                issues.append(f"built scenario.json has no object entity {side!r} "
                              f"to link a portal on")
                continue
            other_e = objs.get(other)
            if not isinstance(e.get("portal"), dict) or \
                    e["portal"].get("to") != (other_e or {}).get("id"):
                issues.append(f"{side!r} does not point its portal at {other!r}")
    # sealed: no opening on a sealed storey's border, and its inner rooms
    # keep their doors (the seal must take the border only — a strip that
    # reaches the rooms turns every upper floor into sealed boxes)
    for name in native.get("seal") or []:
        area = by_name.get(name)
        if area is None:
            continue
        x, y = area.get("position", (0, 0))
        w, h = area.get("size", (0, 0))
        ring = {(cx, cy) for cx in range(x, x + w) for cy in (y, y + h - 1)}
        ring |= {(cx, cy) for cx in (x, x + w - 1) for cy in range(y, y + h)}
        for r in scn.get("regions", []):
            hit = {tuple(c) for c in r.get("openings") or ()} & ring
            if hit:
                issues.append(f"{r.get('name')!r} keeps an exterior opening at "
                              f"{sorted(hit)} on {name!r}")
        for r in scn.get("regions", []):
            if not r.get("wall") or r.get("name") == name:
                continue
            rx, ry = r.get("position", (0, 0))
            rw, rh = r.get("size", (0, 0))
            if not (rx > x and ry > y and rx + rw < x + w and ry + rh < y + h):
                continue   # not strictly inside this storey
            if not r.get("openings"):
                issues.append(f"{r.get('name')!r} is sealed inside {name!r}; "
                              f"the seal must take the storey's border only")
    return issues


CONTENT_KINDS = ("building", "compound", "yard", "field", "square")


def _zone_fill(world):
    """{zone name: {area, content, ratio}} — how much of a zone's ground its
    content claims: buildings, compound blocks (courtyards included), yards,
    fields and the green, each with one lot ring round it. Wild zones with no
    content measure 0; a built-up zone below about 0.45 is mostly empty ground."""
    out = {}
    for zn, pieces in world.zone_pieces.items():
        zone_cells = set()
        for p in pieces:
            zone_cells |= p.cells()
        content = set()
        for r in world.regions:
            if r.parent != zn or r.kind not in CONTENT_KINDS:
                continue
            content |= {(x, y) for x in range(r.rect.x - 1, r.rect.x1 + 2)
                        for y in range(r.rect.y - 1, r.rect.y1 + 2)}
        content &= zone_cells
        area = len(zone_cells)
        out[zn] = {"area": area, "content": len(content),
                   "ratio": round(len(content) / float(area), 3) if area else 0.0}
    return out


def _cut_off_cells(world, openings, jumps):
    """Free cells inside a region that nobody can walk to from the start, by
    the game's own rule rather than the builder's: walls are thin lines on a
    walled region's border, a step across one needs the cell inside it to be an
    opening, and every other cell of a room can be stood on. Objects that are
    solid block their cells. (scenario_checks.py's Walls is the reference.)"""
    solid = set()
    for o in world.objects:
        t = world.templates[o.template]
        if t.walkability <= 0:
            solid |= object_cells(world, o)
    inside = {}
    for r in world.regions:
        if r.wall:
            for c in r.rect.cells():
                inside.setdefault(c, set()).add(r.name)

    def can_step(a, b):
        ia, ib = inside.get(a, set()), inside.get(b, set())
        return all(a in openings[n] for n in ia - ib) and all(b in openings[n] for n in ib - ia)

    start = world.player.pos if isinstance(world.player.pos, tuple) else tuple(world.player.pos)
    seen, todo = {start}, [start]
    while todo:
        c = todo.pop()
        x, y = c
        steps = [n for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
                 if on_a_plane(world, n) and n not in solid and can_step(c, n)]
        for n in steps + list(jumps.get(c, ())):
            if n not in seen:
                seen.add(n)
                todo.append(n)
    cells = set()
    for r in world.regions:
        cells |= r.rect.cells()
    # the strips a building leaves between its flats are behind walls on every
    # side, with nothing in them: nobody is meant to stand there
    for r in world.regions:
        rooms = [c.rect.cells() for c in world.regions if c.parent == r.name]
        if r.wall and rooms:
            cells -= r.rect.cells() - set().union(*rooms)
    return sorted(cells - solid - seen)


def _drop_dead_stairs(world):
    """No stairs to nowhere: furniture named for a stair but linked to no
    portal goes — the floors code places the real, linked stairs — and a
    ruined building keeps its stair, which may rise to a collapsed floor.
    Every later metric sees the final object set. Returns the counts for the
    run summary."""
    ends = set()
    for p in getattr(world, "portals", None) or []:
        ends.add((p.get("from") or {}).get("object"))
        ends.add((p.get("to") or {}).get("object"))
    names = object_entity_names(world)
    building_of = {}
    for b in world.buildings:
        for layout in [b.layout] + [f.layout for f in getattr(b, "floors", []) or []]:
            for r in layout.rooms:
                building_of[r.full_name] = b
            for uo in getattr(layout, "unit_outs", []) or []:
                for r in uo.layout.rooms:
                    building_of[r.full_name] = b
    keep, dropped, ruined, ruin_kept = [], 0, 0, []
    for o in world.objects:
        if not stair_furniture_name(o.template) or names[o] in ends:
            keep.append(o)
            continue
        b = building_of.get(o.region)
        if b is not None and ruined_building(b.layout.design):
            ruined += 1
            keep.append(o)
            ruin_kept.append(o)
        else:
            dropped += 1
            world.failures.append(
                (f"stair {o.template} in {o.region}",
                 "dropped: it leads nowhere (the code places the real stairs)"))
    world.objects[:] = keep
    # the kept ruin stairs by the builder's entity name (numbered after the
    # drops), so the shipped-scenario check knows them even when only the
    # building's status, not any name, says it is a ruin
    final = object_entity_names(world)
    world.ruined_stairs = sorted(final[o] for o in ruin_kept)
    return {"dropped": dropped, "ruined": ruined}


def run_checks(world):
    from . import native
    # no stairs to nowhere first, so every metric below sees the final set
    stairs = _drop_dead_stairs(world)
    openings = compute_openings(world)
    # the water view is refreshed first, with the characters now placed: deep
    # water that would cut them off drops its surface before it blocks
    water = native.final_water(world, refresh=True)
    blocked, doors = walkability_grid(world, openings)

    # ---- overlap and containment (the builder's nesting rule)
    overlaps = []
    regions = world.regions
    for i, a in enumerate(regions):
        for b in regions[i + 1:]:
            if a.rect.intersects(b.rect) and not a.rect.contains_rect(b.rect) and not b.rect.contains_rect(a.rect):
                overlaps.append(f"{a.name} / {b.name}")
    obj_overlaps = []
    claimed = {}
    for o in world.objects:
        for cell in sorted(object_cells(world, o)):
            if cell in claimed:
                obj_overlaps.append(f"{o.template} at {o.pos} overlaps {claimed[cell]}")
            else:
                claimed[cell] = f"{o.template} at {o.pos}"
    out_of_bounds = [f"{o.template} at {o.pos}" for o in world.objects
                     if not on_a_plane(world, o.pos)]

    # ---- reachability: every room from the player's start, every entrance
    # from a road. The linked stair and passage pads count as connections:
    # a sealed upper storey is reached through its stairs, exactly as the
    # game's own portals play it.
    player = world.player
    jumps = portal_jumps(world)
    from_player = flood(world, [player.pos], blocked, jumps) if player else set()
    road_cells = set()
    for road in world.roads:
        road_cells |= road.cells()
    from_road = flood(world, road_cells, blocked, jumps)

    rooms_total = rooms_ok = 0
    unreachable_rooms = []
    for r in world.regions:
        if not r.wall or not r.is_room:
            continue
        rooms_total += 1
        inter = r.rect.interior().cells()
        if inter & from_player:
            rooms_ok += 1
        else:
            unreachable_rooms.append(r.name)

    # ---- compounds: every part, wall corridor and courtyard is walkable
    compound_issues = _compound_checks(world, from_player) \
        if getattr(world, "compounds", None) else []
    world.failures.extend(compound_issues)
    entrances_total = entrances_ok = 0
    unreachable_entrances = []
    for b in world.buildings:
        bl = b.layout
        entrances_total += 1
        dx, dy = {"north": (0, 1), "south": (0, -1), "east": (1, 0), "west": (-1, 0)}[bl.entrance_side]
        approach = (bl.entrance_door[0] + dx, bl.entrance_door[1] + dy)
        if approach in from_road or bl.entrance_door in from_road:
            entrances_ok += 1
        else:
            unreachable_entrances.append(bl.design.name)

    # ---- doors and walkways clear of blocking objects
    solid = set()
    for o in world.objects:
        t = world.templates[o.template]
        if t.walkability <= 0:
            solid |= object_cells(world, o)
    blocked_doors = sorted(doors & solid)
    # a walkway is blocked only by accident: intentional wall objects (a
    # compound's solid walls) stand on their own ground, not on a path
    intentional = set(getattr(world, "solid_walls", ()) or ())
    blocked_walkways = sorted((world.reserved & solid) - intentional)

    # ---- density
    room_density = {}
    for b in world.buildings:
        for room in b.layout.rooms:
            if not world.regions_by_name[room.full_name].is_room:
                continue
            n = sum(1 for o in world.objects if o.region == room.full_name)
            area = room.rect.interior().w * room.rect.interior().h
            room_density[room.full_name] = round(n / area, 3) if area else 0
    zone_density = {}
    for zn, zr in world.zones_by_name.items():
        n = sum(1 for o in world.objects if o.region == zn)
        zone_density[zn] = round(100.0 * n / (zr.w * zr.h), 2)

    # building coverage per zone that carries buildings (settlement zones are
    # sized to hit a target share: packed districts, loose villages)
    building_coverage = {}
    for zn, zr in world.zones_by_name.items():
        pieces = world.zone_pieces.get(zn) or [zr]
        area = sum(p.w * p.h for p in pieces)
        b_area = getattr(world, "zone_building_area", {}).get(zn, 0)
        if not b_area:
            b_area = sum(b.layout.rect.w * b.layout.rect.h for b in world.buildings
                         if any(p.contains_rect(b.layout.rect) for p in pieces))
        if area and b_area:
            building_coverage[zn] = round(100.0 * b_area / area, 1)

    # ---- every cell someone could stand on, not just one per room
    cut_off = _cut_off_cells(world, openings, jumps) if player else []

    # ---- characters reachable and on free cells
    char_issues = []
    for c in world.characters:
        if c.pos in blocked or c.pos not in from_player:
            char_issues.append(f"{c.name} at {c.pos} not reachable")

    # ---- upper storeys, their stairs portals and openings
    floors_metrics = {
        "floors": len(getattr(world, "floors", []) or []),
        "portals": len(getattr(world, "portals", []) or []),
        "issues": _floors_checks(world, blocked) if getattr(world, "floors", None) else [],
    }

    dropped = dropped_failures(world.failures)
    dropped_set = set(dropped)
    notes = [(w, r) for (w, r) in world.failures if (w, r) not in dropped_set]

    metrics = {
        "grid": list(world.grid),
        "seed": world.seed,
        "map_warnings": list(getattr(world, "map_warnings", [])),
        "regions": len(world.regions),
        "rooms": {"total": rooms_total, "reachable": rooms_ok, "unreachable": unreachable_rooms},
        "entrances": {"total": entrances_total, "reachable_from_road": entrances_ok,
                      "unreachable": unreachable_entrances},
        "reachability": (rooms_ok / rooms_total if rooms_total else 1.0) *
                        (entrances_ok / entrances_total if entrances_total else 1.0),
        "errors": {"dropped": [{"what": w, "reason": r} for (w, r) in dropped]},
        "objects": {"placed": len(world.objects),
                    "unplaced": [{"what": w, "reason": r} for (w, r) in notes]},
        "hint_fallbacks": [{"what": w, "reason": r} for (w, r) in getattr(world, "fallbacks", [])],
        "density": {"rooms": room_density, "outdoor_per_100_cells": zone_density,
                    "building_coverage": building_coverage},
        "zone_fill": _zone_fill(world),
        "open_cells_cut_off": {"total": len(cut_off), "cells": [list(c) for c in cut_off[:20]]},
        "side_exits": [{"building": n, "room": r, "cell": list(c)}
                       for (n, r, c) in getattr(world, "side_exits", [])],
        "doors_clear": not blocked_doors,
        "blocked_door_cells": [list(c) for c in blocked_doors],
        "walkways_clear": not blocked_walkways,
        "blocked_walkway_cells": [list(c) for c in blocked_walkways],
        "region_overlaps": overlaps,
        "object_overlaps": obj_overlaps[:20],
        "objects_out_of_bounds": out_of_bounds,
        "characters": {"total": len(world.characters), "issues": char_issues},
        "floors": floors_metrics,
        "stairs": stairs,
        "water": native.water_metrics(world, water),
        "compounds": {"compounds": len(getattr(world, "compounds", []) or []),
                      "issues": [f"{w}: {r}" for (w, r) in compound_issues]},
    }
    world.metrics = metrics
    return metrics


def write_metrics(path, metrics):
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=1)
