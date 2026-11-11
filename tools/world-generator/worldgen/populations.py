"""Anywhere RPG 1.0 native populations: the nameless livestock, vermin, crowds
and patrols of a laid-out world, written as the game's own ``npcTemplates``
(``world10.js`` ``addNpcType``). The generator names no character for them: the
game spawns ``count`` of a template in each of its home regions and respawns
them, so a farm has sheep in its pasture, a cellar has rats and a town square
has a few townsfolk. Each population costs the GM attention, so the whole world
holds at most ``CAP`` creatures and the chooser trims the largest counts first.

A population is chosen from the planned world — the regions' names and kinds,
the zones' kinds, the cast's roles and the player's start — and is deterministic
given the run's seed. Home regions ride the spec by name (the builder drops
unknown keys, so the ids only exist once it has run); the finisher resolves
them against the built scenario. Livestock and vermin are skittish, crowds and
patrols neutral; every population plays a sprite from
``scenario_checks.ANIMATIONS``.
"""
import random
import re

CAP = 20  # creatures the whole world may hold

# whole words of a region's name (or its zone's kind) that make grazing ground:
# sheep, cows, goats or pigs. The crop plots the layout stamps (kind "field")
# are arable and take crows instead, so they never graze stock.
GRAZING_WORDS = frozenset(
    "pasture pastures paddock paddocks pen pens fold folds field fields".split())
# a farmyard by name, or any yard of an agricultural zone (a farm)
FARMYARD_WORDS = frozenset("farmyard farmyards".split())
# where rats nest, by whole words of the region's OWN name (a room's base name
# without its building's, so a shop's bedrooms never match through the shop's
# name): a meal store, a cellar
RAT_WORDS = frozenset(
    "cellar cellars store stores storeroom storerooms storehouse storehouses "
    "warehouse warehouses granary granaries sewer sewers dock docks".split())
# ... but on a building or zone "store" is a shop, not a storeroom
SHOP_STORE_WORDS = frozenset("store stores".split())
# rats nest in at most this many places, the biggest first, one per building,
# so vermin never eat the whole creature cap
RAT_HOMES = 3
# the ground townsfolk cross, by whole words of the name or of the zone's kind
CROWD_WORDS = frozenset(
    "market markets square squares plaza plazas".split())
# a named character with one of these role words is the place's own watch
GUARD_ROLE = re.compile(r"\b(guard|watch|police)")
# setting words that read as here-and-now: the townsfolk take a casual sprite
MODERN_WORDS = re.compile(
    r"\b(present|contemporary|modern|cyberpunk|scifi|sci-fi|future|futuristic|"
    r"space|starship|near.future|post.apocalyptic|zombie)\b")
# bands the room library reads as fantasy or historical (see library_plan)
PERIOD_BANDS = ("medieval", "industrial")

# one template per kind and region type, in the order the spec lists them:
# sprite None means a person pair picked for the period and gender
CATALOG = {
    "Sheep": ("sheep", "A small flock of sheep grazing the grass.",
              "A woolly sheep with a dark, gentle face."),
    "Cows": ("cow", "A small herd of cattle grazing the ground.",
             "A placid dairy cow, brown and white."),
    "Goats": ("goat", "A few goats browsing the rough grass.",
              "A lean goat with stubby horns and a wise look."),
    "Pigs": ("pig", "A few pigs rooting the soft ground.",
             "A plump pink pig with a curly tail."),
    "Chickens": ("chicken", "A brood of chickens scratching the yard.",
                 "A plump hen with a red comb."),
    "Ducks": ("duck", "A small flock of ducks waddling the yard.",
              "A white duck with an orange bill."),
    "Rats": ("rat", "Rats that nest in the stores and scavenge what they can.",
             "A lean brown rat with a bald tail."),
    "Crows": ("crow", "Crows that settled on the crops to steal the seed.",
              "A black crow with a sharp beak."),
    "Townsfolk": (None, "The townsfolk passing through on their errands.",
                  "A townsperson in everyday clothes."),
    "Town watch": (None, "The town watch, walking their beat.",
                   "A guard of the town watch, keeping the peace."),
}
GRAZING_KINDS = ("Sheep", "Cows", "Goats", "Pigs")
YARD_KINDS = ("Chickens", "Ducks")
NEUTRAL_KINDS = ("Townsfolk", "Town watch")


def _words(text):
    """The whole lowercase words of a name or kind."""
    return set(re.findall(r"[a-z]+", (text or "").lower()))


def _by_area(region, low, high, per):
    """A count that grows with the region's area: ``low`` up to ``high``, one
    more for every ``per`` cells."""
    area = region.rect.w * region.rect.h
    return max(low, min(high, low + area // per))


def _is_period(plan):
    """Whether the setting reads as fantasy or historical (the townsfolk take a
    peasant sprite) rather than here-and-now (a casual one). The band is the
    library's own reading; without it the era and technology words decide, and
    an unreadable setting is period, as the library's own default is medieval."""
    setting = plan.setting or {}
    band = setting.get("band")
    if band:
        return band in PERIOD_BANDS
    text = " ".join(str(setting.get(k, "")) for k in ("genre", "era", "technology"))
    return not MODERN_WORDS.search(text.lower())


def _gender_id(base, gender):
    """The pair id for a gender; anything but male takes the -woman sheet."""
    return f"{base}-man" if gender == "male" else f"{base}-woman"


def choose(world, plan, water=None):
    """The world's native populations, as template dicts ready for the spec:
    ``{name, description, physicalDescription, animationId, gender, stance,
    level, money, lootPoolIds, homes}`` with every home a ``{region, count}``
    naming its region by name (the ids only exist once the builder has run).
    Deterministic given the run's seed."""
    rng = random.Random(f"{world.seed}|populations")
    zones = {z.name: z for z in plan.zones}
    if water is None:
        from . import native
        water = native.final_water(world)
    wet = set(water)
    start = tuple(world.player.pos) if world.player is not None else None
    holds_start = {r.name for r in world.regions
                   if start is not None and r.rect.contains_cell(start)}

    def zone_of(r):
        """The plan zone a region belongs to (a zone region names its group)."""
        if r.kind == "zone":
            return zones.get(r.group or r.name)
        return zones.get(r.parent) if r.parent else None

    def has_guard():
        return any(GUARD_ROLE.search((c.person.role or "").lower())
                   for c in world.characters)

    def free(r):
        """A region the player does not start in and no water covers."""
        return r.name not in holds_start and r.name not in wet

    entries = []       # {"kind", "region", "count"} in world order
    taken = set()      # one population per region
    rat_spots = []     # rat candidates, settled after the walk

    def add(kind, region, count):
        taken.add(region.name)
        entries.append({"kind": kind, "region": region.name, "count": count})

    for r in world.regions:
        if r.name in taken or not free(r):
            continue
        zone = zone_of(r)
        zone_words = _words(zone.kind) if zone is not None else set()
        urban = zone is not None and _urban(zone)
        # livestock: grazing animals on pasture-named (or pasture-kind) open
        # ground, yard stock in a farmyard or a farm's yard
        if r.kind in ("zone", "square", "yard"):
            if _words(r.name) & GRAZING_WORDS or \
                    (r.kind == "zone" and zone_words & GRAZING_WORDS):
                add(rng.choice(GRAZING_KINDS), r, _by_area(r, 2, 5, 60))
                continue
            if _words(r.name) & FARMYARD_WORDS or (
                    r.kind == "yard" and zone is not None
                    and _zone_class(zone) == "agricultural"):
                add(rng.choice(YARD_KINDS), r, _by_area(r, 2, 5, 60))
                continue
        if r.kind in ("room", "building", "zone"):
            own = _own_words(world, r)
            if r.kind != "room":
                own -= SHOP_STORE_WORDS
            if own & RAT_WORDS:
                rat_spots.append(r)
                continue
        if r.kind == "field":     # the arable crop plots
            add("Crows", r, 2 + (1 if r.rect.w * r.rect.h >= 80 else 0))
            continue
        if urban and r.kind in ("zone", "square") and \
                (_words(r.name) & CROWD_WORDS or
                 (r.kind == "zone" and zone_words & CROWD_WORDS)):
            add("Townsfolk", r, _by_area(r, 3, 5, 200))

    # rats: one nest per building (or zone), the biggest RAT_HOMES of them
    nested = set()
    for r in sorted(rat_spots, key=lambda r: -(r.rect.w * r.rect.h)):
        if len(nested) >= RAT_HOMES:
            break
        key = _building_key(world, r)
        if key in nested:
            continue
        nested.add(key)
        add("Rats", r, 2 + (1 if r.rect.w * r.rect.h >= 24 else 0))

    # the town watch: two guards on the main street (or the square) of every
    # urban or town zone, only when the cast has no guard of its own
    if not has_guard():
        for z in plan.zones:
            if not _urban(z):
                continue
            street = world.regions_by_name.get(f"{z.name} Path")
            if street is None or street.parent != z.name:
                street = next((r for r in world.regions
                               if r.kind == "square" and r.parent == z.name), None)
            if street is not None and street.name not in taken and free(street):
                add("Town watch", street, 2)

    _trim_to_cap(entries)
    return _templates(entries, rng, plan)


def _own_words(world, r):
    """The whole words of a region's own name: a room's name carries its
    building's in front ("Harrow's Store Master Bedroom"), so that prefix is
    cut off before the words are read."""
    name = r.name
    if r.parent and name.startswith(r.parent + " "):
        name = name[len(r.parent) + 1:]
    return _words(name)


def _building_key(world, r):
    """The building a region belongs to (its topmost building ancestor, an
    upper storey counted as its ground building), or the region itself."""
    key, cur = r.name, r
    while cur is not None:
        if cur.kind == "building":
            key = cur.name
        cur = world.regions_by_name.get(cur.parent) if cur.parent else None
    return re.sub(r"\s*\([^)]*\)$", "", key)


def _urban(zone):
    from .model import is_town_zone, is_urban_zone
    return is_urban_zone(zone) or is_town_zone(zone)


def _zone_class(zone):
    from .model import zone_class
    return zone_class(zone)


def _trim_to_cap(entries):
    """Hold the whole world to CAP creatures, trimming the largest counts
    first; a count trimmed to nothing drops its region (and a kind nobody
    keeps drops its template)."""
    while sum(e["count"] for e in entries) > CAP:
        biggest = max(entries, key=lambda e: e["count"])  # ties: the first
        biggest["count"] -= 1
        if biggest["count"] <= 0:
            entries.remove(biggest)


def _templates(entries, rng, plan):
    """The surviving entries as one template per kind (the catalog's order),
    each with its homes by region name and a gender drawn from the run's seed."""
    by_kind = {}
    for e in entries:
        by_kind.setdefault(e["kind"], []).append(
            {"region": e["region"], "count": e["count"]})
    period = _is_period(plan)
    out = []
    for name, (anim, desc, phys) in CATALOG.items():
        homes = by_kind.get(name)
        if not homes:
            continue
        gender = rng.choice(("male", "female"))
        if anim is None:      # a person sprite, period-fitting
            if name == "Town watch":
                base = "town-guard" if period else "police"
                if not period:  # here-and-now: the watch is the police
                    desc = "Police officers walking their beat."
                    phys = "A police officer in uniform, keeping the peace."
            else:
                base = "peasant" if period else "casual"
            anim = _gender_id(base, gender)
        out.append({"name": name, "description": desc,
                    "physicalDescription": phys, "animationId": anim,
                    "gender": gender,
                    "stance": "neutral" if name in NEUTRAL_KINDS else "skittish",
                    "level": 1, "money": 0, "lootPoolIds": [],
                    "homes": homes})
    return out


def creature_count(populations):
    """How many creatures the populations spawn across their homes."""
    return sum(h.get("count", 0) for p in populations or []
               for h in p.get("homes") or [])
