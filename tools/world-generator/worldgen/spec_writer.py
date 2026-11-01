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
    by_template = {}
    for o in world.objects:
        t = world.templates[o.template]
        pos = o.pos
        region = world.regions_by_name.get(o.region)
        if region is not None and region.wall:
            inset = 1
            pos = [o.region, pos[0] - region.rect.x - inset, pos[1] - region.rect.y - inset]
        else:
            pos = [pos[0], pos[1]]
        by_template.setdefault(o.template, []).append(pos)

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
        for k in ("money", "lootPool"):
            if k in t.extras:
                spec_t[k] = t.extras[k]
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
        if "innkeeper" in (c.person.role or "").lower() or "merchant" in (c.person.role or "").lower():
            ent["merchant"] = {}
        return ent

    extras = plan.extras
    dg, dtex = getattr(world, "default_ground", None) or ("grass", "grass")
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
        "defaultTile": {"name": "Meadow" if dg == "grass" else dg.capitalize(),
                        "ground": dg, "groundTexture": dtex,
                        "ambience": OUT_AMBIENCE},
        "weatherKinds": extras.get("weatherKinds", ["clear", "rain", "fog"]),
        "currency": extras.get("currency", {"name": "Copper penny",
                                            "description": "The village's small coin.",
                                            "format": "5 pennies"}),
        "startingCurrency": extras.get("startingCurrency", 5),
        "attributes": extras.get("attributes", {"strength": 5, "dexterity": 4, "intellect": 4,
                                                "perception": 5, "charisma": 5}),
        "skills": extras.get("skills", {}),
        "regions": regions,
        "objectTemplates": object_templates,
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
