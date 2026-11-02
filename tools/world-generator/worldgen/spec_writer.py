"""Turn the laid-out plan into a builder spec: a JSON-serialisable dict in the
name-based format of the vendored build_scenario.py (guide section 10), written
out as both spec.json and spec.py (`SPEC = json.loads(...)`).
"""
import json

GROUND_MAP = {"grass": ("grass", "grass"), "dirt": ("dirt", "dirt"),
              "gravel": ("gravel", "gravel"), "stone": ("stone", "rock"),
              "wood": ("wood", "floorboards")}
OUT_AMBIENCE = {"day": "nature_outdoors", "night": "crickets"}

ANIMATIONS = {  # role keyword -> (male, female); fallback casual-*
    "innkeeper": ("chef-man", "chef-woman"),
    "smith": ("blacksmith-man", "blacksmith-woman"),
    "blacksmith": ("blacksmith-man", "blacksmith-woman"),
    "weaver": ("casual-man", "casual-woman"),
    "farmer": ("farmer-man", "farmer-woman"),
    "traveler": ("adventurer-man", "adventurer-woman"),
    "traveller": ("adventurer-man", "adventurer-woman"),
    "child": ("child", "child"),
    "old": ("old-man", "old-woman"),
}


def _ground_pair(key):
    return GROUND_MAP.get(key, ("dirt", "dirt"))


def _loot_map(world):
    """{region full name: (design, room base name)} for every placed room —
    a building's own rooms, its stamped unit copies (ground and upper) and
    its designed upper storeys — so a placement's pool resolves through the
    furniture line, the room, the building and the template default."""
    out = {}

    def add(design, rooms):
        for room in rooms:
            out[room.full_name] = (design, room.base_name)

    for b in world.buildings:
        bl = b.layout
        add(bl.design, bl.rooms)
        if getattr(bl.design, "units", None):
            for uo in getattr(bl, "unit_outs", []) or []:
                add(bl.design.units.design, uo.layout.rooms)
        for f in getattr(b, "floors", []) or []:
            add(f.layout.design, f.layout.rooms)
            if getattr(f.layout.design, "units", None):
                for uo in getattr(f.layout, "unit_outs", []) or []:
                    add(f.layout.design.units.design, uo.layout.rooms)
    return out


def _placements(world, plan):
    """{template name: [entry per placement]} where an entry is the position
    list, or a dict {"pos", "inventory"} when the placement draws a starting
    inventory from its pool. The draw is seeded by the world seed and the
    placement's name, so the same seed reproduces it and copied units
    differ."""
    from . import loot as loot_mod

    rooms = _loot_map(world)
    items_by_name = {it.name: it for it in plan.items}
    setting = plan.extras.get("loot", "normal")
    out = {}
    for o in world.objects:
        region = world.regions_by_name.get(o.region)
        pos = o.pos
        if region is not None and region.wall:
            inset = 1
            pos = [o.region, pos[0] - region.rect.x - inset, pos[1] - region.rect.y - inset]
        else:
            pos = [pos[0], pos[1]]
        entries = out.setdefault(o.template, [])
        pool = plan.loot_pools.get(loot_mod.resolve_pool(
            rooms.get(o.region), o.template, plan.loot_pools, world.templates))
        inv = loot_mod.draw_inventory(
            pool, items_by_name,
            f"{world.seed}|{o.template}|{len(entries) + 1}", setting) if pool else []
        entries.append({"pos": pos, "inventory": [[n, c] for (n, c) in inv]} if inv else pos)
    return out


def build_spec(world, plan):
    builder_doors = {f.region_name: list(f.builder_door)
                     for f in getattr(world, "floors", []) or []
                     if f.builder_door is not None}
    regions = []
    for r in world.regions:
        out = {
            "name": r.name,
            "description": r.description or r.name,
            "ground": r.ground,
            "groundTexture": r.ground_texture,
            "position": [r.rect.x, r.rect.y],
            "size": [r.rect.w, r.rect.h],
            "ambience": r.ambience or ({"day": "quiet_indoor"} if r.wall else OUT_AMBIENCE),
        }
        if r.wall:
            out["wall"] = r.wall
            doors = [list(d) for d in sorted(r.doors)]
            if not doors and r.name in builder_doors:
                # the flat-map builder needs one way into every walled region;
                # on a sealed upper storey that door is a build-time fiction —
                # inject_arpg_mods strips it, and the stairs are the real way in
                doors = [builder_doors[r.name]]
            out["doors"] = doors
        if getattr(r, "ground_color", None):
            out["groundColor"] = r.ground_color
        if getattr(r, "wall_color", None):
            out["wallColor"] = r.wall_color
        if getattr(r, "group", None):
            out["regionGroup"] = r.group
        regions.append(out)

    # object templates with placements; room positions are written room-relative
    by_template = _placements(world, plan)

    object_templates = []
    for t in plan.templates:
        spec_t = {
            "name": t.name,
            "size": list(t.size),
            # passableAtBuild: the boundary slab must let the builder's reachability
            # walk cross the strip; inject_arpg_mods hardens it back to 0 in the
            # shipped scenario, where nothing may cross
            "walkability": 1.0 if t.extras.get("passableAtBuild") else t.walkability,
            "description": t.description or t.name,
            "physicalDescription": t.physicalDescription or t.name,
            "tags": t.tags or ["filler"],
            "heightM": t.extras.get("heightM", 1),
            "maxHp": t.extras.get("maxHp", 50),
        }
        if t.for_sleep:
            spec_t["forSleep"] = True
        if t.extras.get("craftStation"):
            spec_t["craftStation"] = True
        light = t.extras.get("light")
        if "lights" in getattr(world, "extensions", ()):
            from .extensions.lights import light_for
            light = light_for(t)
        if isinstance(light, (int, float)) and not isinstance(light, bool) and light > 0:
            spec_t["light"] = light
        if "money" in t.extras:
            spec_t["money"] = t.extras["money"]
        # the template's DEFAULT pool only (not the union of its placements'
        # pools): the game draws lootPoolIds again on later searches, and a
        # union would let one store's shelves spawn another's goods then —
        # the per-placement variety lives in the drawn starting inventories
        pool = plan.loot_pools.get(t.extras.get("lootPool", "") or "")
        if pool is not None:
            spec_t["lootPool"] = list(pool.items)
        if t.name in by_template:
            spec_t["placements"] = by_template[t.name]
        object_templates.append(spec_t)

    def character(c):
        ent = {
            "name": c.name,
            "gender": c.gender,
            "pos": _char_pos(world, c),
            "level": c.person.extras.get("level", 2),
            "animationId": animation_for(c),
            "description": c.person.description or c.name,
            "physicalDescription": c.person.physicalDescription or c.name,
            "voiceProfile": voice_for(c),
            "schedule": c.schedule,
        }
        if c.is_player:
            ent.pop("level")
        if c.person.extras.get("animationId"):
            ent["animationId"] = c.person.extras["animationId"]
        if c.person.extras.get("inventory"):
            ent["inventory"] = list(c.person.extras["inventory"])
        if c.person.extras.get("equipment"):
            ent["equipment"] = dict(c.person.extras["equipment"])
        if "innkeeper" in (c.person.role or "").lower() or "merchant" in (c.person.role or "").lower():
            ent["merchant"] = {}
        return ent

    extras = plan.extras
    dg, dtex = getattr(world, "default_ground", None) or ("grass", "grass")
    default_tile = {"name": "Meadow" if dg == "grass" else dg.capitalize(),
                    "ground": dg, "groundTexture": dtex,
                    "ambience": OUT_AMBIENCE}
    if getattr(world, "void_default", False):
        # every zone is void: the map's own tile is the out-of-bounds void
        from .extensions.floors import BOUNDARY_COLOR
        default_tile = {"name": "Void", "ground": "stone",
                        "groundTexture": "rock", "groundColor": BOUNDARY_COLOR,
                        "ambience": OUT_AMBIENCE}
    # the calendar points at regions by name; a building the layout could not
    # place no longer exists, so its entries go with it (logged like other
    # dropped planned content)
    region_names = {r["name"] for r in regions}
    calendar = []
    for c in extras.get("calendar", []):
        if isinstance(c, dict) and c.get("location") not in region_names:
            world.metrics.setdefault("errors", {}).setdefault("dropped", []).append(
                {"what": f"calendar '{c.get('name')}'",
                 "reason": f"location '{c.get('location')}' did not make it onto "
                           "the map"})
        else:
            calendar.append(c)

    spec = {
        "name": plan.name,
        "folderName": plan.name.replace(" ", "-"),
        "seed": str(world.seed),
        "worldBackground": plan.worldBackground,
        "narrativeRules": extras.get("narrativeRules", []),
        "narrativeFlavor": extras.get("narrativeFlavor", "adaptive"),
        "difficulty": extras.get("difficulty", "medium"),
        "xpMultiplier": extras.get("xpMultiplier", 1),
        "gridSize": [world.grid[0], world.grid[1]],
        "defaultTile": default_tile,
        "weatherKinds": extras.get("weatherKinds", ["clear", "rain", "fog"]),
        # genre-neutral fallbacks: no copper pennies in a cyberpunk world, and
        # the game's rule is base 3 each plus exactly 10 points (a 25 total)
        "currency": extras.get("currency", {"name": "Coin",
                                            "description": "The common coin of the region.",
                                            "format": "5 coins"}),
        "startingCurrency": extras.get("startingCurrency", 5),
        "attributes": extras.get("attributes", {"strength": 5, "dexterity": 5, "intellect": 5,
                                                "perception": 5, "charisma": 5}),
        "skills": extras.get("skills", {}),
        "variables": extras.get("variables", []),
        "perkTrees": extras.get("perkTrees", []),
        "calendar": calendar,
        "quests": extras.get("quests", []),
        "regions": regions,
        "objectTemplates": object_templates,
        "itemTemplates": [
            {"name": it.name, "type": it.type, "quality": it.quality,
             "value": it.value, "description": it.description,
             "physicalDescription": it.physicalDescription}
            for it in plan.items
        ],
        "npcs": [character(c) for c in world.characters if not c.is_player],
        "player": character(world.player),
    }
    arpg_mods = {}
    if getattr(world, "floors", None):
        from .extensions import floors
        arpg_mods.update(floors.arpg_mods(world))
    if "lights" in getattr(world, "extensions", ()):
        from .extensions import lights
        arpg_mods.update(lights.arpg_mods(world))
    if arpg_mods:
        spec["arpgMods"] = arpg_mods
    return spec


def _char_pos(world, c):
    region = world.regions_by_name.get(c.region)
    pos = c.pos
    if region is not None and region.wall:
        return [region.name, pos[0] - region.rect.x - 1, pos[1] - region.rect.y - 1]
    return [pos[0], pos[1]]


def animation_for(c):
    role = (c.person.role or "").lower()
    for key, (m, f) in ANIMATIONS.items():
        if key in role:
            return m if c.gender == "male" else f
    return "casual-man" if c.gender == "male" else "casual-woman"


def voice_for(c):
    gender = "Male" if c.gender == "male" else "Female"
    age = ["Senior"] if (c.person.role or "").lower().startswith("old") else ["Adult"]
    return {"gender": gender, "age": age, "pitch": ["Average"], "tags": []}


def write_spec(out_dir, spec):
    import os
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=1)
    payload = json.dumps(spec, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "spec.py"), "w", encoding="utf-8") as f:
        f.write('"""Builder spec generated by the worldgen layout pipeline."""\n')
        f.write("import json\n\n")
        f.write('SPEC = json.loads(r"""\n' + payload + '\n""")\n')
    return payload
