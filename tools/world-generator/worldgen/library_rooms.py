"""Room library build step 3: compile a library layout into furniture lines.

A room's purpose, band, wealth, condition, interior size and sleepers in; out
come today's ``FurniturePlan`` lines plus the object templates they use, so
``layout_room`` places library rooms with no change. Nothing in the plain route
calls this yet; step 4 (P3 with the library) will.

  registry = Templates(lib, seed)
  room = compile_room(lib, registry, "bedroom", (5, 4), "medieval", "modest",
                      "kept", rng, singles=2)
  room.layout_id, room.furniture, registry.templates()
"""
import random
from dataclasses import dataclass, field

from .library import binding_matches, fill_text
from .model import FurniturePlan

GROW_SHARE = 0.35        # grow slots are added while furniture covers less than this


def _fits(piece, space):
    (pw, ph), (sw, sh) = piece, space
    return (pw <= sw and ph <= sh) or (ph <= sw and pw <= sh)


def size_band(lib, interior):
    """The size band ("tiny".."large") of an interior [w, h]."""
    area = interior[0] * interior[1]
    for name, rng_ in lib.vocab.get("sizeBands", {}).items():
        if not name.startswith("_") and rng_[0] <= area <= rng_[1]:
            return name
    return "large"


def pick_layout(lib, purpose, interior, rng):
    """A layout of the purpose's family that fits the interior: one whose
    min-max range holds it, else the largest whose minimum fits (its grow
    slots fill the rest). None when even the smallest is too big."""
    fam = lib.family_of(purpose)
    pool = sorted(lib.layouts_for(fam), key=lambda l: l["id"])
    fits_min = [l for l in pool if _fits(l["minInterior"], interior)]
    if not fits_min:
        return None
    within = [l for l in fits_min if _fits(interior, l["maxInterior"])]
    if within:
        return rng.choice(within)
    biggest = max(l["maxInterior"][0] * l["maxInterior"][1] for l in fits_min)
    return rng.choice([l for l in fits_min
                       if l["maxInterior"][0] * l["maxInterior"][1] == biggest])


def sleeps_right(role, obj):
    """A couple's bed sleeps two (at least 2x2) and a single's sleeps one;
    every other role takes any object."""
    if role == "sleep.couple":
        return min(obj["size"]) >= 2
    if role in ("sleep", "sleep.child", "cell.bed", "med.bed"):
        return min(obj["size"]) < 2
    return True


def pick_object(lib, purpose, role, size, band, tier, rng, genre=None):
    """(object, widened): the first bound category with an object for the
    band and tier that fits ``size``; failing that, the nearest other tier.
    (None, False) is a gap."""
    roles = ((lib.purposes.get(purpose) or {}).get("roles") or {})
    cats = roles.get(role)
    if cats is None:
        cats = ((lib.purposes.get("*") or {}).get("roles") or {}).get(role) or []
    tiers = lib.tiers
    order = [tier] + sorted((t for t in tiers if t != tier),
                            key=lambda t: abs(tiers.index(t) - tiers.index(tier)))
    for i, t in enumerate(order):
        for cat in cats:
            objs = [o for o in sorted(lib.objects.values(), key=lambda o: o["id"])
                    if binding_matches(cat, o)
                    and (o["bands"] == ["*"] or band in o["bands"])
                    and t in o["wealth"]
                    and (size is None or _fits(o["size"], size))
                    and sleeps_right(role, o)
                    and (not o.get("onlyGenres") or (genre or "") in o["onlyGenres"])]
            if objs:
                return rng.choice(objs), i > 0
    return None, False


class Templates:
    """The world's library templates: one per (object, band, wealth,
    condition) in use, named for play ("Oak bed"), text filled once from an
    RNG keyed by the template so a re-roll writes the same words."""

    def __init__(self, lib, seed=1, taken=()):
        self.lib = lib
        self.seed = seed
        self.by_key = {}           # (object id, band, tier, condition) -> template dict
        self.names = set(taken)    # names already used (P2's own templates included)

    def get(self, obj, band, tier, condition):
        key = (obj["id"], band, tier, condition)
        if key in self.by_key:
            return self.by_key[key]
        rng = random.Random(f"{self.seed}|{'|'.join(key)}")
        text = fill_text(self.lib, obj, band, tier, condition, rng)
        noun = (obj.get("names") or {}).get(band) or obj["names"]["*"]
        main = next(iter(text["materials"].values()), "")
        base = f"{main} {noun}" if main and main.lower() not in noun.lower() else noun
        base = base[:1].upper() + base[1:]
        name, n = base, 2
        while name in self.names:
            name, n = f"{base} {n}", n + 1
        self.names.add(name)
        t = {"name": name, "size": list(obj["size"]), "walkability": obj["walkability"],
             "forSleep": bool(obj.get("forSleep")), "light": obj.get("light", 0),
             "description": text["description"], "physicalDescription": text["physical"],
             "tags": list(obj.get("tags") or [obj["category"]]),
             "libraryId": obj["id"]}
        if obj.get("back"):
            t["back"] = obj["back"]
        self.by_key[key] = t
        return t

    def templates(self):
        return list(self.by_key.values())


@dataclass
class CompiledRoom:
    layout_id: str = None
    furniture: list = field(default_factory=list)   # [FurniturePlan]
    gaps: list = field(default_factory=list)        # [str] slots no object could fill
    widened: list = field(default_factory=list)     # [str] slots filled from another tier


def _count(slot, rng, singles, couples):
    c = slot.get("count", 1)
    if c == "singles":
        return singles
    if c == "couples":
        return couples
    if isinstance(c, list):
        return rng.randint(c[0], c[1])
    return int(c)


def compile_room(lib, registry, purpose, interior, band, tier, condition, rng,
                 singles=0, couples=0, room="Room", optional=True, grow=True,
                 genre=None, layout=None):
    """The furniture lines for one room from a library layout (``layout`` to
    force one). Optional slots go in unless ``optional`` is False (the caller
    drops them when the room comes out tight); each grow slot is added once,
    in order, while the furniture covers less than GROW_SHARE of a bigger room."""
    out = CompiledRoom()
    lay = layout or pick_layout(lib, purpose, interior, rng)
    if lay is None:
        out.gaps.append(f"no {lib.family_of(purpose)} layout fits {list(interior)}")
        return out
    out.layout_id = lay["id"]
    tiers = lib.tiers
    names = {}          # slot id -> template name
    used = 0

    def add(slot, count, label, required=True):
        nonlocal used
        if count <= 0:
            return
        obj, widened = pick_object(lib, purpose, slot.get("role"), slot.get("size"),
                                   band, tier, rng, genre)
        if obj is None:
            # an optional or grow slot with nothing to fill it is just left out
            if required:
                out.gaps.append(f"{label}: no {slot.get('role')} for {band} {tier}")
            return
        if widened:
            out.widened.append(f"{label}: {obj['id']}")
        t = registry.get(obj, band, tier, condition)
        if slot.get("id"):
            names[slot["id"]] = t["name"]
        hint = "+".join(t for t in (_rewrite(tok, names)
                                    for tok in (slot.get("anchor") or "").split("+")) if t)
        out.furniture.append(FurniturePlan(template=t["name"], room=room, count=count, hint=hint))
        used += count * obj["size"][0] * obj["size"][1]

    for s in lay.get("slots") or []:
        if s.get("minWealth") and tiers.index(tier) < tiers.index(s["minWealth"]):
            continue
        if s.get("optional") and not optional:
            continue
        add(s, _count(s, rng, singles, couples), f"{lay['id']}.{s.get('id')}",
            required=not s.get("optional"))
    area = interior[0] * interior[1]
    if grow and area > lay["minInterior"][0] * lay["minInterior"][1]:
        # each grow slot once, in order, while the furniture leaves room
        for g in lay.get("grow") or []:
            size = g.get("size") or [1, 1]
            if used + size[0] * size[1] <= GROW_SHARE * area:
                add(g, 1, f"{lay['id']}.grow", required=False)
    return out


def _rewrite(token, names):
    """beside:/around: name slot ids in a layout and template names in a hint."""
    key, _, val = token.partition(":")
    if key in ("beside", "around") and val in names:
        return f"{key}:{names[val]}"
    if key in ("beside", "around"):
        return ""          # the target slot was left out: no constraint
    return token


def layout_need(layout):
    """(interior area, narrowest side) a room needs to hold this layout: what
    ``room_needs`` gives the building packer for a library room."""
    w, h = layout["minInterior"]
    return w * h, min(w, h)


def object_templates(registry):
    """The registry's templates as ``ObjectTemplate`` for the placer."""
    from .model import ObjectTemplate
    out = {}
    for t in registry.templates():
        extras = {"forSleep": t["forSleep"], "light": t.get("light", 0)}
        if t.get("back"):
            extras["back"] = t["back"]
        out[t["name"]] = ObjectTemplate(name=t["name"], size=tuple(t["size"]),
                                        walkability=t["walkability"],
                                        description=t["description"],
                                        physicalDescription=t["physicalDescription"],
                                        tags=list(t["tags"]), extras=extras)
    return out


FURNISH_DRAWS = 3


def furnish_room(lib, registry, purpose, rect, doors, band, tier, condition, rng,
                 singles=0, couples=0, room="Room", genre=None, main_door=None,
                 extra_templates=None):
    """Compile a library room and place it: (CompiledRoom, RoomLayout).
    When pieces can't all be placed it leaves out the optional slots, then
    tries a few fresh draws (another layout variant, other objects), and
    keeps the best try. ``extra_templates`` are templates already in the
    world that the room's lines may share."""
    from .layout_room import layout_room
    inter = rect.interior()
    interior = (inter.w, inter.h)
    best = None
    for draw in range(FURNISH_DRAWS):
        for optional in (True, False):
            sub = random.Random(f"{rng.random()}|{draw}|{optional}")
            comp = compile_room(lib, registry, purpose, interior, band, tier, condition, sub,
                                singles=singles, couples=couples, room=room, genre=genre,
                                optional=optional)
            if comp.layout_id is None:
                return comp, None
            tmpls = dict(extra_templates or {})
            tmpls.update(object_templates(registry))
            out = layout_room(rect, doors, comp.furniture, tmpls, sub, main_door=main_door)
            lost = sum(1 for _f in out.failures)
            if best is None or lost < best[0]:
                best = (lost, comp, out)
            if not out.failures:
                return comp, out
    return best[1], best[2]
