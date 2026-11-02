"""Post-layout checks: overlap and containment, reachability on a walkability
grid (every room from its entrance, every entrance from a road; the stair
portals count as connections), walkways and doors clear, density, and
unplaced pieces with reasons. With the floors extension: floor areas the
size of their ground region, storeys sealed (no opening on their outer
border), portal ends that exist, walkable stairs, upper rooms reachable from
their stairs, and nothing in an opening. Results go to metrics.json (the
pipeline writes the dict; run_checks returns it).

The walkability model mirrors build_scenario.py exactly: the outer ring of a
walled region is wall except at door openings, and walkability-0 objects block.
"""
from .model import Rect, shared_wall_cells


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


def walkability_grid(world, openings):
    """(blocked_cells, door_cells) over the whole map."""
    W, H = world.grid
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
            w, h = t.size
            blocked |= {(x, y) for x in range(o.pos[0], o.pos[0] + w)
                        for y in range(o.pos[1], o.pos[1] + h)}
    return blocked, doors


def flood(world, starts, blocked, jumps=None):
    """Cells reachable from `starts`: four-way through unblocked cells, plus
    any jump edges (stair portals), which connect two cells directly."""
    W, H = world.grid
    seen = set(s for s in starts if 0 <= s[0] < W and 0 <= s[1] < H and s not in blocked)
    todo = list(seen)
    while todo:
        x, y = todo.pop()
        nxt = ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
        if jumps:
            nxt += tuple(jumps.get((x, y), ()))
        for c in nxt:
            if 0 <= c[0] < W and 0 <= c[1] < H and c not in seen and c not in blocked:
                seen.add(c)
                todo.append(c)
    return seen


def portal_jumps(world):
    """{cell: [cells]} for the two ends of every stair portal: stepping onto
    a stair is stepping onto the stair it pairs with (the portals mod)."""
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


def _shared_storey_doors(world, openings):
    """{storey region name: {cells}} — the doors between touching storeys
    (a compound's wall walks), the only openings allowed on a storey's
    border."""
    from .extensions.floors import shared_storey_doors
    floors = getattr(world, "floors", []) or []
    return shared_storey_doors({f.region_name: f.rect for f in floors},
                               {f.region_name: openings.get(f.region_name, set())
                                for f in floors})


def _floors_checks(world, blocked):
    """Issues with the placed upper storeys: floor areas the size of their
    `above` region, no opening on a storey's outer border (a wall-walk door
    shared with another storey excepted), portal ends that exist and belong
    to one portal each, walkable stairs in separate cells, upper rooms
    reachable from their stairs (openings block, as in the game mod), and
    nothing sitting in an opening."""
    issues = []
    names = object_entity_names(world)
    name_set = {n.lower() for n in names.values()}
    regions = {r.name: r for r in world.regions}
    region_set = {n.lower() for n in regions}
    openings = compute_openings(world)
    keep = _shared_storey_doors(world, openings)

    def obj_footprints():
        for o in world.objects:
            t = world.templates[o.template]
            w, h = t.size
            yield o, {(x, y) for x in range(o.pos[0], o.pos[0] + w)
                      for y in range(o.pos[1], o.pos[1] + h)}

    for f in getattr(world, "floors", []):
        above = regions.get(f.above)
        if above is None:
            issues.append(f"{f.region_name}: above region {f.above!r} does not exist")
        elif (f.rect.w, f.rect.h) != (above.rect.w, above.rect.h):
            issues.append(f"{f.region_name} is {f.rect.w}x{f.rect.h} but sits over "
                          f"{f.above} at {above.rect.w}x{above.rect.h}")
        # sealed: no opening on the outer border of the storey's floor area
        # except a wall-walk door it shares with another storey
        ring = _ring(f.rect)
        part_names = [f.region_name] + [r.full_name for r in f.layout.rooms
                                        if r.full_name != f.region_name]
        for name in part_names:
            hit = (openings.get(name, set()) & ring) - keep.get(f.region_name, set())
            if hit:
                issues.append(f"{name} has an exterior opening at {sorted(hit)}; "
                              f"its only ways in and out are its stairs")
        if f.stair_down is None and f.stair_up is None:
            if not keep.get(f.region_name):
                issues.append(f"{f.region_name} has no stairs and no door to "
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
        # upper rooms reachable from this storey's stairs, openings blocked
        starts = [ref[1] for ref in (f.stair_down, f.stair_up) if ref is not None]
        if starts:
            blocked2 = set(blocked)
            if f.opening_rect is not None:
                blocked2 |= f.opening_rect.cells()
            seen = flood(world, starts, blocked2)
            for room in f.layout.rooms:
                if not (room.rect.interior().cells() & seen):
                    issues.append(f"{room.base_name} on {f.region_name} is not "
                                  f"reachable from the stairs")
        # a storey with stairs both down and up has two separate stairs
        if f.stair_down is not None and f.stair_up is not None \
                and f.stair_down[1] == f.stair_up[1]:
            issues.append(f"{f.region_name}: its stairs down and up share one cell")
        if f.opening_rect is not None:
            cells = f.opening_rect.cells()
            for o, fp in obj_footprints():
                if fp & cells:
                    issues.append(f"{names.get(o, o.template)} sits in the opening "
                                  f"{f.opening_name}")
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
    # the boundary: everything east of the play area. One region spans the
    # strip and the band behind it, tinted the void's colour (so the band's
    # gaps read as empty dark and the storeys as the only lit things there),
    # unwalled; the strip's first SEPARATOR_WIDTH cells are sealed by the
    # slab object, which covers them exactly. Nothing else may sit in the
    # strip, and every storey nests east of the slab, inside the region.
    if list(getattr(world, "floors", []) or []):
        from .extensions.floors import (BOUNDARY_COLOR, BOUNDARY_NAME, SEPARATOR_WIDTH,
                                        SLAB_NAME)
        from .model import Rect as _Rect
        b = next((r for r in world.regions if r.name == BOUNDARY_NAME), None)
        if b is None:
            issues.append(f"no {BOUNDARY_NAME} region east of the play area")
        else:
            if b.rect.y != 0 or b.rect.h != world.grid[1] \
                    or b.rect.x1 != world.grid[0] - 1:
                issues.append(f"{BOUNDARY_NAME} is {b.rect.w}x{b.rect.h} at "
                              f"({b.rect.x},{b.rect.y}); it must span the map's height "
                              f"{world.grid[1]} and reach its east edge")
            if b.wall:
                issues.append(f"{BOUNDARY_NAME} is walled; the slab, not walls, seals it")
            if b.ground_color != BOUNDARY_COLOR:
                issues.append(f"{BOUNDARY_NAME} is tinted {b.ground_color!r}, not the "
                              f"void's {BOUNDARY_COLOR}")
            slab = world.templates.get(SLAB_NAME)
            placed = [o for o in world.objects if o.template == SLAB_NAME]
            strip = _Rect(b.rect.x, 0, SEPARATOR_WIDTH, world.grid[1])
            if slab is None:
                issues.append(f"no {SLAB_NAME} object to seal {BOUNDARY_NAME}")
            else:
                if slab.walkability > 0:
                    issues.append(f"{SLAB_NAME} must block every cell it covers")
                if not placed:
                    issues.append(f"{SLAB_NAME} is never placed")
                for o in placed:
                    if o.pos != (strip.x, strip.y) \
                            or slab.size != (strip.w, strip.h):
                        issues.append(f"{SLAB_NAME} must cover the strip exactly")
            for f in world.floors:
                if f.rect.x < strip.x1 + 1 or f.rect.x1 > b.rect.x1:
                    issues.append(f"{f.region_name} does not sit east of the slab, "
                                  f"inside {BOUNDARY_NAME}")
            for r in world.regions:
                if r is not b and strip.contains_rect(r.rect) and r.rect != strip:
                    issues.append(f"{r.name} sits inside the world's edge strip")
            for o, fp in obj_footprints():
                if o.template != SLAB_NAME and fp & strip.cells():
                    issues.append(f"{names.get(o, o.template)} sits inside the "
                                  f"world's edge strip")
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


def check_scenario_mods(scenario_path, arpg_mods):
    """Issues with the built scenario.json against what the generator laid
    out: arpgMods must be present and match exactly, and every upper storey
    must be sealed — no opening on its floor area's outer border."""
    import json
    with open(scenario_path, "r", encoding="utf-8") as f:
        scn = json.load(f)
    issues = []
    if "arpgMods" not in scn:
        return ["built scenario.json has no arpgMods"]
    got = scn["arpgMods"]
    if got != arpg_mods:
        bad = [k for k in set(got) | set(arpg_mods) if got.get(k) != arpg_mods.get(k)]
        issues += [f"built scenario.json arpgMods.{k} does not match the spec"
                   for k in sorted(bad)]
    by_name = {r.get("name"): r for r in scn.get("regions", [])}
    # the lights mod finds its templates by exact name, and lights only those the game lights
    lit = {t.get("name"): t for t in scn.get("objectTemplates", [])}
    for name in ((arpg_mods.get("lights") or {}).get("templates") or {}):
        if name not in lit:
            issues.append(f"arpgMods.lights names {name!r}, which is not an object template")
        elif not lit[name].get("light"):
            issues.append(f"arpgMods.lights gives {name!r} a kind, but its light is 0")
    # the wall-walk doors between touching storeys are the one opening a
    # storey's border may keep
    from .extensions.floors import shared_storey_doors
    from .model import Rect as _Rect2
    _rects, _ops = {}, {}
    for f in arpg_mods.get("floors") or []:
        area = by_name.get(f.get("area"))
        if area is not None:
            x, y = area.get("position", (0, 0))
            w, h = area.get("size", (0, 0))
            _rects[f.get("area")] = _Rect2(x, y, w, h)
            _ops[f.get("area")] = {tuple(c) for c in area.get("openings") or []}
    keep = shared_storey_doors(_rects, _ops)
    for f in arpg_mods.get("floors") or []:
        area = by_name.get(f.get("area"))
        if area is None:
            issues.append(f"built scenario.json has no region {f.get('area')!r}")
            continue
        x, y = area.get("position", (0, 0))
        w, h = area.get("size", (0, 0))
        ring = {(cx, cy) for cx in range(x, x + w) for cy in (y, y + h - 1)}
        ring |= {(cx, cy) for cx in (x, x + w - 1) for cy in range(y, y + h)}
        allowed = ring & keep.get(f.get("area"), set())
        for r in scn.get("regions", []):
            hit = {tuple(c) for c in r.get("openings") or ()} & ring - allowed
            if hit:
                issues.append(f"{r.get('name')!r} keeps an exterior opening at "
                              f"{sorted(hit)} on {f.get('area')!r}")
        # interior doors: a walled room inside a storey keeps at least one opening.
        # The seal must take the storey's border only — a strip that reaches the
        # rooms turns every upper floor into sealed boxes nobody can walk between.
        ax, ay = area.get("position", (0, 0))
        aw, ah = area.get("size", (0, 0))
        for r in scn.get("regions", []):
            if not r.get("wall") or r.get("name") == f.get("area"):
                continue
            rx, ry = r.get("position", (0, 0))
            rw, rh = r.get("size", (0, 0))
            if not (rx > ax and ry > ay and rx + rw < ax + aw and ry + rh < ay + ah):
                continue   # not strictly inside this storey
            if not r.get("openings"):
                issues.append(f"{r.get('name')!r} is sealed inside {f.get('area')!r}; "
                              f"the seal must take the storey's border only")
    if arpg_mods.get("floors"):
        import os
        from .extensions.floors import (BOUNDARY_COLOR, BOUNDARY_NAME, SEPARATOR_WIDTH,
                                        SLAB_NAME)
        b = by_name.get(BOUNDARY_NAME)
        if b is None:
            issues.append(f"built scenario.json has no region {BOUNDARY_NAME!r}")
        else:
            if b.get("wall") or b.get("openings"):
                issues.append(f"{BOUNDARY_NAME!r} must be an open region sealed by "
                              f"the slab, not walls")
            if b.get("groundColor") != BOUNDARY_COLOR:
                issues.append(f"{BOUNDARY_NAME!r} lost its {BOUNDARY_COLOR} tint")
        slab = next((t for t in scn.get("objectTemplates", [])
                     if t.get("name") == SLAB_NAME), None)
        if slab is None:
            issues.append(f"built scenario.json has no {SLAB_NAME!r} template")
        else:
            if slab.get("walkability", 0) != 0:
                issues.append(f"{SLAB_NAME!r} kept its build-time passability; "
                              f"in play it must block")
            if b is not None and list(slab.get("size", [])) != \
                    [SEPARATOR_WIDTH, b.get("size", [0, 0])[1]]:
                issues.append(f"{SLAB_NAME!r} is {slab.get('size')} but the strip is "
                              f"{[SEPARATOR_WIDTH, b.get('size', [0, 0])[1]]}; the slab "
                              f"must cover it exactly (a stale first-pass size from the "
                              f"growth loop)")
            ent = next((e for e in scn.get("entities", [])
                        if e.get("templateId") == slab.get("id")), None)
            if ent is None:
                issues.append(f"{SLAB_NAME!r} is never placed in the built scenario")
            elif b is not None and (list(ent.get("pos", [])) != list(b.get("position", []))
                                    or list(ent.get("size", [])) != list(slab.get("size", []))):
                issues.append(f"{SLAB_NAME!r} is placed at {ent.get('pos')} "
                              f"{ent.get('size')}, not covering the strip")
            sprite = os.path.join(os.path.dirname(scenario_path), "media",
                                  slab["id"], f"{slab['id']}-sprite.webp")
            if not os.path.exists(sprite):
                issues.append(f"{SLAB_NAME!r} has no sprite beside the built scenario")
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


def run_checks(world):
    openings = compute_openings(world)
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
        t = world.templates[o.template]
        w, h = t.size
        for cx in range(o.pos[0], o.pos[0] + w):
            for cy in range(o.pos[1], o.pos[1] + h):
                if (cx, cy) in claimed:
                    obj_overlaps.append(f"{o.template} at {o.pos} overlaps {claimed[(cx, cy)]}")
                else:
                    claimed[(cx, cy)] = f"{o.template} at {o.pos}"
    out_of_bounds = [f"{o.template} at {o.pos}" for o in world.objects
                     if not (0 <= o.pos[0] < world.grid[0] and 0 <= o.pos[1] < world.grid[1])]

    # ---- reachability: every room from the player's start, every entrance
    # from a road. The stair portals count as connections: a sealed upper
    # storey is reached through its stairs, exactly as the game mod plays it.
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
            w, h = t.size
            solid |= {(x, y) for x in range(o.pos[0], o.pos[0] + w)
                      for y in range(o.pos[1], o.pos[1] + h)}
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
        "doors_clear": not blocked_doors,
        "blocked_door_cells": [list(c) for c in blocked_doors],
        "walkways_clear": not blocked_walkways,
        "blocked_walkway_cells": [list(c) for c in blocked_walkways],
        "region_overlaps": overlaps,
        "object_overlaps": obj_overlaps[:20],
        "objects_out_of_bounds": out_of_bounds,
        "characters": {"total": len(world.characters), "issues": char_issues},
        "floors": floors_metrics,
        "compounds": {"compounds": len(getattr(world, "compounds", []) or []),
                      "issues": [f"{w}: {r}" for (w, r) in compound_issues]},
    }
    world.metrics = metrics
    return metrics


def write_metrics(path, metrics):
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=1)
