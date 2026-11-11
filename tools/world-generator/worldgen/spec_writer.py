"""Turn the laid-out plan into a builder spec: a JSON-serialisable dict in the
name-based format of the vendored build_scenario.py (guide section 10), written
out as both spec.json and spec.py (`SPEC = json.loads(...)`).
"""
import json
import re

from .sellers import sellers as sellers_of
from .vendor.scenario_checks import ANIMATIONS as KNOWN_ANIMATIONS

GROUND_MAP = {"grass": ("grass", "grass"), "dirt": ("dirt", "dirt"),
              "gravel": ("gravel", "gravel"), "stone": ("stone", "rock"),
              "wood": ("wood", "floorboards")}
OUT_AMBIENCE = {"day": "nature_outdoors", "night": "crickets"}

# Role keywords -> 1.0 sprite: `base` names a -man/-woman pair or one id both
# genders share. Every id must exist in scenario_checks.ANIMATIONS; a base whose
# id doesn't falls back to casual-*. More specific entries come first, so
# "town guard" wins over "guard" and tavern staff over "maid".
ANIMATIONS = [
    (("innkeeper", "tavern keeper", "barkeep"), "innkeeper"),
    (("barmaid", "waiter", "waitress"), "waiter"),
    (("cook", "chef", "baker"), "chef"),
    (("butcher",), "butcher"),
    (("smith", "blacksmith"), "blacksmith"),
    (("farmer", "farmhand", "farm hand", "farm worker", "shepherd"), "farmer"),
    (("fisher", "fisherman", "fisherwoman"), "fisher"),
    (("hunter",), "hunter"),
    (("miner",), "miner"),
    (("pirate",), "pirate"),
    (("merchant", "shopkeeper", "trader", "peddler"), "merchant"),
    (("maid", "chambermaid", "servant", "butler"), "servant"),
    (("noble", "lord", "lady"), "noble"),
    (("king", "queen"), "royalty"),
    (("security guard",), "security-guard"),
    (("town guard", "watchman", "guard"), "town-guard"),
    (("soldier",), "soldier"),
    (("knight",), "knight"),
    (("archer",), "archer"),
    (("priest", "priestess", "clergyman", "clergywoman", "clergy"), "clergy"),
    (("cleric",), "cleric"),
    (("monk", "nun"), "monk"),
    (("healer",), "healer"),
    (("doctor",), "doctor"),
    (("nurse",), "nurse"),
    (("scholar",), "scholar"),
    (("professor",), "professor"),
    (("scientist",), "scientist"),
    (("wizard student",), "wizard-student"),
    (("student",), "student"),
    (("mage", "wizard"), "mage"),
    (("witch",), "witch"),
    (("necromancer",), "necromancer"),
    (("druid",), "druid"),
    (("bard", "minstrel"), "bard"),
    (("jester",), "jester"),
    (("beggar",), "beggar"),
    (("prisoner",), "prisoner"),
    (("thief", "rogue"), "rogue"),
    (("assassin",), "assassin"),
    (("detective",), "detective"),
    (("police", "policeman", "policewoman"), "police"),
    (("officer",), "officer"),
    (("sailor", "captain"), "sailor"),
    (("mechanic",), "mechanic"),
    (("janitor",), "janitor"),
    (("office worker", "office"), "office"),
    (("hacker",), "hacker"),
    (("astronaut",), "astronaut"),
    (("firefighter",), "firefighter"),
    (("cowboy",), "cowboy"),
    (("samurai",), "samurai"),
    (("ninja",), "ninja"),
    (("viking",), "viking"),
    (("traveler", "traveller", "adventurer"), "adventurer"),
    (("peasant", "villager"), "peasant"),
    (("labourer", "laborer", "worker"), "worker"),
    (("weaver",), "casual"),  # 1.0 has no weaver sheet; it stays on the casual pair
    (("child",), "child"),
    (("old",), "old"),
]


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
        rot = getattr(o, "rot", 0) or 0
        if inv or rot:
            entry = {"pos": pos}
            if inv:
                entry["inventory"] = [[n, c] for (n, c) in inv]
            if rot:
                entry["rot"] = rot
            entries.append(entry)
        else:
            entries.append(pos)
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

    sellers = sellers_of(world)

    def character(c):
        ent = {
            "name": c.name,
            "gender": c.gender,
            "pos": _char_pos(world, c),
            "level": c.person.extras.get("level", 2),
            "animationId": animation_for(c),
            "description": c.person.description or c.name,
            "physicalDescription": physical_for(c),
            "voiceProfile": voice_for(c),
            "schedule": c.schedule,
        }
        if c.is_player:
            ent.pop("level")
        if c.person.extras.get("animationId"):
            ent["animationId"] = c.person.extras["animationId"]
        inventory = list(c.person.extras.get("inventory") or [])
        equipment = {}
        # plans saved before slot checks may name a slot the game lacks
        # ("weapon"): map it, or carry the item when there is no free slot
        from .phases import EQUIP_SLOTS, SLOT_ALIASES
        for slot, item in (c.person.extras.get("equipment") or {}).items():
            real = slot if slot in EQUIP_SLOTS else SLOT_ALIASES.get(str(slot).lower())
            if real is None or real in equipment:
                inventory.append([item, 1])
            else:
                equipment[real] = item
        if inventory:
            ent["inventory"] = inventory
        if equipment:
            ent["equipment"] = equipment
        if c.person.name in sellers:
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
        "startingCurrency": extras.get("startingCurrency", 100),
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


def _kind(c):
    return (c.person.extras or {}).get("kind")


def _gender_id(base, gender):
    """The pair id for a gender; anything but male takes the -woman sheet."""
    return f"{base}-man" if gender == "male" else f"{base}-woman"


def animation_for(c):
    if _kind(c) == "child":
        return "child"
    if _kind(c) == "elder":
        return _gender_id("old", c.gender)
    role = (c.person.role or "").lower()
    for keywords, base in ANIMATIONS:
        if any(re.search(rf"\b{re.escape(kw)}s?\b", role) for kw in keywords):
            animation = base if base in KNOWN_ANIMATIONS else _gender_id(base, c.gender)
            if animation in KNOWN_ANIMATIONS:
                return animation
            break  # a base with no 1.0 sheet falls back to casual, not to a later entry
    return _gender_id("casual", c.gender)


def physical_for(c):
    """The portrait prompt. A child's or an elder's own description rarely says
    how old they are, and the portraits came out as adults until it did."""
    text = c.person.physicalDescription or c.name
    if _kind(c) == "child":
        return f"A young child, under twelve years old, with a child's small round face. {text}"
    if _kind(c) == "elder":
        word = "man" if c.gender == "male" else "woman"
        return f"Very old {word}, about eighty, deeply wrinkled, white hair. {text}"
    return text


def voice_for(c):
    gender = "Male" if c.gender == "male" else "Female"
    if _kind(c) == "child":
        return {"gender": gender, "age": ["Child"], "pitch": ["Brighter"], "tags": []}
    old = _kind(c) == "elder" or (c.person.role or "").lower().startswith("old")
    return {"gender": gender, "age": ["Senior"] if old else ["Adult"], "pitch": ["Average"],
            "tags": []}


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
