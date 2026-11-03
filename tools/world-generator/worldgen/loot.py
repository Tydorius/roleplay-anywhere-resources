"""Starting inventories drawn per container placement.

A pool is chosen for each placement at spec-writing time (most specific
wins: the furniture line, the room, the building, the template's default),
and the draw itself is seeded by the world seed and the placement's name —
so re-rolling the same seed reproduces the same inventories while every
copied unit differs from its siblings.
"""
import random

# how much more often a common item turns up than a rare one, on top of any
# per-pool weights
QUALITY_WEIGHT = {"common": 50.0, "uncommon": 20.0, "rare": 6.0,
                  "epic": 2.0, "legendary": 1.0}

# items drawn per placement under each plan "loot" setting (the base game
# draws 0-3)
COUNT_RANGE = {"none": (0, 0), "sparse": (0, 2), "normal": (0, 3), "rich": (1, 4)}


def resolve_pool(region, template_name, pools, templates):
    """The pool name one placement draws from: the furniture line that placed
    it in this room, else the room's own pool, else the building's, else the
    template's default. ``region`` is (design, room base name) or None."""
    design, base = region if region else (None, "")
    if design is not None:
        for f in design.furniture:
            if f.room == base and f.template == template_name and f.loot_pool:
                return f.loot_pool
        for r in design.rooms:
            if r.name == base and r.loot_pool:
                return r.loot_pool
        if getattr(design, "loot_pool", ""):
            return design.loot_pool
    t = templates.get(template_name)
    return (t.extras.get("lootPool", "") if t is not None else "") or ""


def draw_inventory(pool, items_by_name, seed_key, setting="normal"):
    """[(item name, count), ...] for one placement: 0-3 draws (scaled by the
    plan's loot setting), each pick weighted by quality and the pool's own
    weights, duplicates merged into counts."""
    lo, hi = COUNT_RANGE.get(setting, COUNT_RANGE["normal"])
    if pool is None or not pool.items or hi <= 0:
        return []
    rng = random.Random(seed_key)
    n = rng.randint(lo, hi)
    names, weights = [], []
    for name in pool.items:
        it = items_by_name.get(name)
        if it is None:
            continue
        w = QUALITY_WEIGHT.get(it.quality, 1.0) * float(pool.weights.get(name, 1.0) or 1.0)
        names.append(name)
        weights.append(max(w, 0.0001))
    if not names or n <= 0:
        return []
    counts = {}
    for _ in range(n):
        pick = rng.choices(names, weights=weights)[0]
        counts[pick] = counts.get(pick, 0) + 1
    return sorted(counts.items())
