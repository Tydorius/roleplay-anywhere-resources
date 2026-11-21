"""The room assembler: library buildings placed from the room library's own
rooms — one storey or a simple rectangle of two or three.

A qualifying design (every room of every storey carrying a library ``use``
that maps to a family — a compound part qualifies the same way; a unit
building only when its copies all fit upstairs over shared ground rooms) is
assembled instead of cut from a footprint: each room is an active stored
room of its family (or, for a family with none stored, composed live the
way the room generator does), picked for the building's wealth, the room's
share and its assigned sleepers. Rooms are placed along the connection
tree — the entrance room first, every child against a free side of its
parent with a door candidate of each lining up across the shared wall —
then the outline is closed to a rectangle with stretch lines and filler
rooms.

A wing ask (``wing_footprint`` / ``wing_build``) assembles the same design
inside a target rectangle instead of its natural one: the placement search
stays inside the target, the leaves closest to filling it close first, and
the strip between the rooms and the target's edge is a hole the closers
fill like any other. Doors may be pinned to the target's ring — the
entrance to a side and offset, extra outward doors wherever another wing
or a courtyard will meet this one — and the pins are resolved before the
rooms furnish, so no piece stands on a pinned cell or blocks its approach.
A pin no room can open falls the entrance back to the free pick (recorded)
or the whole ask back to the caller (the reason recorded); a target the
closers cannot meet reports the rectangle the wing grew to instead.

A multi-storey design reserves its ground stair cell first (the stairs room
when the plan names one, else the entrance room), then partitions each
upper storey inside the ground outline (design 8.1f): a corridor band
across the short axis, centred on the stair below, the storey's rooms
slotted along both sides and closed to their slots the way the ground
closes. The storeys ride the ground layout (``upper_asm``) until the floors
extension asks for them — by then the assembler has stepped aside, so
``upper_layout`` converts them without a context.

The result goes back to the pipeline in the shapes ``layout_building``
returns, each room's furniture pre-placed at the fixed cells the room's
pieces name, so nothing downstream changes. Any failure picks the whole
building back to the old method and records why in ``out.fallbacks``: a
world never fails because of the assembler. Off (the default) the module
is dormant and the pipeline runs exactly as before.
"""
import dataclasses
import random

from . import fixed_rooms as FR
from . import library_plan
from . import library_rooms
from . import room_composer as RC
from . import room_groups as RG
from .layout_building import BuildingLayout, RoomOut, _connection_tree
from .layout_room import TURN_SIDES, RoomLayout, turned
from .model import FurniturePlan, Rect, is_urban_zone, settlement_size

# a room's share names the shared size band it asks for; a family with bands
# of its own takes its band nearest that shared band's centre — one table for
# every family (families without their own bands use the shared name itself)
SHARE_BAND = {"small": "small", "medium": "medium", "large": "large"}
# the clearance a wealth tier buys, the inverse of room_composer.WEALTH; the
# gap a room then keeps is room_composer.gap_for (a grand private room stays
# roomy) — the clearance rule the composer already ships
TIER_CLEARANCE = {tier: clearance
                  for clearance, tiers in RC.WEALTH.items() for tier in tiers}
CLEARANCE_ORDER = ("tight", "roomy", "grand")
OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}
# a hole narrower than this cannot hold a walled room, so a placement that
# would leave one beside it is rejected (and filled another way)
MIN_SPAN = 3
# a hole this big in both directions gets a real composed room when one fits
# the hole's floor exactly, before falling back to an empty store
FURNISHED_FILLER = 5
# the search keeps each room's best placements (a passage counts as one) and
# this many complete placements, then closes the outline on the best ones
# until one closes clean
CANDIDATES_PER_ROOM = 4
PASSAGE_CANDIDATES = 2
MAX_LEAVES = 16       # complete placements to collect before closing
SEARCH_NODES = 90     # room placements to expand while looking for them
LEAF_TRIES = 8
# a building with upper storeys tries every leaf the search collected: its
# ground outline is the outline the storeys partition, and the tightest
# placements — the ones tried first — are also the ones most likely to
# strand a strip no closer fills, so stopping half way down the list ships
# a thinner outline whose partition starves one side of its corridor
STOREY_LEAF_TRIES = MAX_LEAVES


class _Fallback(Exception):
    """Assembly failed: the building goes back to the old method. A pinned
    door that cannot be honoured raises with ``pinned`` set, so a run whose
    every leaf fails says why the pin was refused, not why one leaf's
    outline could not close."""

    pinned = False


class _NoRoom(_Fallback):
    """A storey's split drew but cannot seat a single one of its rooms —
    the cue for the one-sided gallery, unlike a split that seated its rooms
    and only failed to close (rl-12b)."""


class _SplitMiss(Exception):
    """A size-first split's slot could not take a room of its planned width:
    the next ranked split gets its chance before the equal tiles do."""


def _pin_refused(msg):
    """A _Fallback that names a pinned door the ask cannot honour."""
    fail = _Fallback(msg)
    fail.pinned = True
    return fail



class _Placed:
    """One room of the assembly: the oriented fixed-room dict, its rect (the
    room's floor plus its wall ring) and the door cells opened on its ring."""

    def __init__(self, name, room, rect, synthetic=False):
        self.name = name
        self.room = room            # the fixed-room dict, already oriented
        self.rect = rect            # Rect of the floor plus its wall ring
        self.synthetic = synthetic  # a passage or filler, not a design room
        self.doors = set()          # ring cells opened as doors (absolute)


class _Storey:
    """One upper storey's finished partition, in the ground assembly's own
    cells: its placed rooms (the corridor or landing first), the door pairs
    between them, the stair cells the floors extension places, and the
    storey's own design and furniture — everything ``upper_layout`` needs to
    re-originate the storey onto its plane once the assembler has stepped
    aside."""

    def __init__(self, storey, design, rooms, pairs, down, up, layouts, lines,
                 notes):
        self.storey = storey        # 2..n
        self.design = design        # the storey's BuildingDesign (its own rooms)
        self.rooms = rooms          # [_Placed], the corridor or landing first
        self.pairs = pairs          # [[cellA, cellB]] facing door pairs
        self.down = down            # (x, y) the stair from below lands
        self.up = up                # (x, y) the stair to the storey above (top: None)
        self.layouts = layouts      # room name -> RoomLayout in storey cells
        self.lines = lines          # [FurniturePlan] the storey's furniture
        self.notes = notes          # [(who, what)] the run's notes, kept until
                                    # every storey stands before they are told


class _Assembly:
    def __init__(self, design, side):
        self.design = design
        self.side = side            # the entrance side asked for
        self.rooms = []             # [_Placed] in placement order
        self.pairs = []             # [[cellA, cellB]] facing door pairs
        self.entrance = None        # (x, y) on the bounding ring
        self.lines = []             # [FurniturePlan] the assembled furniture
        self.layouts = {}           # room name -> RoomLayout in local cells
        self.stair_cell = None      # (x, y) the ground stair, or None (one storey)
        self.uppers = []            # [_Storey], one per upper storey
        self.notes = []             # [(who, what)] this assembly's notes, kept
                                    # until the building stands


def _pin_of(target, pin):
    """A pinned door as (side, offset): given that way, or as an exact
    (x, y) cell on the target's ring (a corner cell cannot open a door and
    is the caller's mistake to ask for)."""
    side = pin[0]
    if isinstance(side, str):
        return (side, int(pin[1]))
    x, y = pin
    w, h = target
    if y == 0 and 0 < x < w - 1:
        return ("north", x - 1)
    if y == h - 1 and 0 < x < w - 1:
        return ("south", x - 1)
    if x == 0 and 0 < y < h - 1:
        return ("west", y - 1)
    if x == w - 1 and 0 < y < h - 1:
        return ("east", y - 1)
    raise ValueError(f"door pin {pin} is not on the target ring")


class _Wing:
    """One wing ask: the target rectangle the rooms must tile, and the doors
    pinned to its ring — the entrance (side, offset) plus any extra outward
    doors where another wing or a courtyard will meet this one. ``None``
    entrance pins a free pick; the pins are absolute cells of the target
    rect once resolved."""

    def __init__(self, target, entrance=None, doors=()):
        self.target = (int(target[0]), int(target[1]))
        self.entrance = _pin_of(self.target, entrance) if entrance else None
        self.doors = tuple(_pin_of(self.target, d) for d in doors)

    def key(self):
        """The cache's wing half: same design and sides, different ask."""
        return (self.target, self.entrance, self.doors)

    def ring(self):
        return Rect(0, 0, self.target[0], self.target[1])


class _Context:
    """Everything one build needs: the library, the world's template registry
    and the assembled buildings, cached per entrance side so the map's
    measurements and the build itself agree."""

    def __init__(self, plan, plan_data, world_seed, world_templates):
        self.lib = library_plan.load()
        self.groups = RG.load()
        self.rooms = FR.load()
        setting = plan.setting if isinstance(plan.setting, dict) else {}
        self.band = library_plan.band_of(self.lib, setting)
        self.genre = setting.get("genre")
        self.setting = setting
        self.world_seed = world_seed
        self.plan_data = plan_data
        self.world_templates = world_templates
        self.pool_names = set(plan.loot_pools or {})
        self.zone_of = {b.name: z for z in plan.zones for b in z.buildings}
        parts = {}
        for c in getattr(plan, "compounds", None) or []:
            cname = c.get("name") if isinstance(c, dict) else getattr(c, "name", "")
            for p in getattr(c, "parts", None) or []:
                name = (p.get("building") if isinstance(p, dict)
                        else getattr(p, "building", ""))
                if name and cname:
                    parts[name] = cname
        self.compound_of = parts   # part building name -> its compound's
        self.registry = library_rooms.Templates(
            self.lib, world_seed,
            taken={t["name"] for t in plan_data.get("templates", [])
                   if isinstance(t, dict)})
        for t in plan_data.get("templates", []):
            # a template a previous assembler run placed: adopt it under its
            # recorded key, so a re-roll keeps the same names
            key = t.get("libraryKey")
            if isinstance(t, dict) and isinstance(key, list) and len(key) == 4 \
                    and tuple(key) not in self.registry.by_key \
                    and t.get("name") not in self.registry.by_name:
                self.registry.by_key[tuple(key)] = t
                self.registry.by_name[t["name"]] = t
                self.registry.names.add(t["name"])
        self.cache = {}          # (name, entrance_side, compound, wing) ->
                                  # _Assembly | None; the wing half is None for
                                  # a plain assembly, else its target and pins
        self.fallbacks = {}      # building name -> reason
        self.spot_built = {}     # building name -> [(room name, note)]
        self.storey_notes = {}   # (name, entrance_side) -> [(room, note)] the
                                  # partition notes of the assembly that side
                                  # shipped — a discarded side's closets are
                                  # not this building's story
        self.injected = set()    # template names already in the plan
        self.block_designs = {}  # building name -> the wing design a block
                                 # recipe stands it for (rl-10), or None
        self.sleepers = {}       # design room name -> (singles, couples)
        self.slot_asking = False  # a storey slot is walking its ask ladder:
                                  # its speculative pools note nothing
        self._clearances = {}    # (design name, family) -> clearance
        self._pools = {}         # (family, clearance, band, sleepers, fit) -> [rooms]
        self._size_catalogues = {}  # (design, family, tier, use, share, ask) ->
                                    # ((w, h, door sides), ...) a family's sizes
        self._filler_rooms = {}  # (recipe, band, clearance, style, seed) ->
                                 # compose's rooms; every hole of one band in
                                 # one building asks the same recipes at the
                                 # same seed, so the first hole pays for all
        self._filler_none = set()  # (building, iw, ih) asks that found no
                                   # room: never composed again


# ------------------------------------------------------------------ the switch

_context = None


def activate(plan, plan_data, world_seed, world_templates):
    """Turn the assembler on for one build; ``deactivate`` after it."""
    global _context
    _context = _Context(plan, plan_data, world_seed, world_templates)
    return _context


def deactivate():
    global _context
    _context = None


def active():
    return _context


def _block_design(ctx, design):
    """The wing design a block-shape building recipe stands this single
    building for (rl-10): the recipe's one wing is the building's whole
    design — its rooms by purpose and share, the storeys the height rules
    allow, the building's own wealth, loot and name. None when the kind
    names no block recipe (compound parts and unit buildings never qualify:
    a compound's wings come through the compound, a unit stamps copies), so
    the design stands as the plan drew it."""
    if getattr(design, "units", None) or ctx.compound_of.get(design.name):
        return None
    if design.name in ctx.block_designs:
        return ctx.block_designs[design.name]
    wing = None
    if design.kind:
        recipe = library_plan.building_by_kind(ctx.lib, design.kind, ctx.band)
        if recipe is not None and recipe.get("shape") == "block":
            entries = [e for e in recipe.get("wings") or []
                       if isinstance(e, dict)]
            wing = ctx.lib.wings.get(entries[0].get("wing")) \
                if entries else None
    if wing is None:
        ctx.block_designs[design.name] = None
    else:
        from .phases import _storey_cap
        zone = ctx.zone_of.get(design.name)
        cap = _storey_cap(ctx.band, design.kind,
                          settlement_size(zone.kind) if zone is not None
                          else "hamlet")
        ctx.block_designs[design.name] = library_plan.wing_design(
            ctx.lib, wing, design.name, design, ctx.band, cap, design.kind)
    return ctx.block_designs[design.name]


def footprint(design, templates=None):
    """The (w, h) an assembled building takes, or None when the assembler is
    off or the design does not qualify. ``building_footprint`` calls this
    first so the map, the packer and the layout agree."""
    if _context is not None:
        design = _block_design(_context, design) or design
    asm = _assembly_for(design)
    if asm is None:
        return None
    _inject_templates(templates)
    return (max(p.rect.x1 for p in asm.rooms) + 1,
            max(p.rect.y1 for p in asm.rooms) + 1)


def build(design, origin, templates=None):
    """The assembled BuildingLayout at ``origin``, or None (the caller falls
    back to the old method)."""
    if _context is not None:
        design = _block_design(_context, design) or design
    asm = _assembly_for(design)
    if asm is None:
        return None
    _inject_templates(templates)
    return _building_layout(asm, origin)


def wing_footprint(design, target, entrance=None, doors=(), templates=None):
    """The (w, h) the design takes assembled inside the target rectangle
    (w, h) — the target itself when the closers fill it, the smaller
    rectangle the wing grew to when they cannot (a note says so; the caller
    decides whether the rectangle it got is one it can use) — or None with
    the reason recorded. ``entrance`` and each of ``doors`` pin a door to
    the target's ring: (side, offset), or an exact (x, y) cell."""
    asm = _assembly_for(design, wing=_Wing(target, entrance, doors))
    if asm is None:
        return None
    _inject_templates(templates)
    box = _bbox(asm.rooms)   # the rooms need not touch the target's origin
    return (box.w, box.h)


def wing_build(design, origin, target, entrance=None, doors=(), templates=None):
    """The assembled BuildingLayout at ``origin``, inside the target
    rectangle with its pinned doors opened — or None, the reason recorded,
    the caller falling back to its own method."""
    asm = _assembly_for(design, wing=_Wing(target, entrance, doors))
    if asm is None:
        return None
    _inject_templates(templates)
    return _building_layout(asm, origin)


def fallback_note(name):
    """(label, reason) when a building fell back to the old method."""
    if _context is None or name not in _context.fallbacks:
        return None
    return (f"building {name}", f"room assembler fell back: {_context.fallbacks[name]}")


def spot_notes(name, side=None):
    """[(label, note)] for the rooms of a building composed on the spot — and,
    for the entrance side the building shipped on, its storeys' partition
    notes: the run's notes carry them, never its fallbacks."""
    if _context is None:
        return []
    out = [(f"room {room} in building {name}", note)
           for (room, note) in _context.spot_built.get(name, [])]
    out += [(f"room {room} in building {name}", note)
            for (room, note) in (_context.storey_notes.get((name, side))
                                 or [])]
    return out


# ------------------------------------------------------------------ qualifying

def _qualifies(design):
    """Whether the assembler takes this design: a simple rectangle of one to
    four storeys whose every room — the ground's and each upper storey's —
    carries a library ``use`` that maps to a family. A compound part
    qualifies the same way (the compound's own code lays it out through
    ``layout_building`` like any building); a unit building qualifies when
    its copies all fit upstairs over its shared ground rooms (rl-06b): the
    assembler lays the ground and the floors extension stamps the unit
    storeys over it."""
    if _context is None:
        return False
    if not design.rooms:
        return False
    storey_rooms = [(1, r) for r in design.rooms] + \
                   [(getattr(s, "storey", i + 2), r)
                    for i, s in enumerate(design.upper or []) for r in s.rooms]
    if all(r.use and _context.lib.family_of(r.use) is not None
           for (_n, r) in storey_rooms):
        if getattr(design, "units", None):
            # the copies stamp every storey the old way, so a ground the
            # assembler tiles with shared rooms only works when none of them
            # is owed a place downstairs
            from .layout_building import units_per_storey
            return design.storeys in (2, 3) and not design.upper and \
                design.units.count <= units_per_storey(design) * (design.storeys - 1)
        # storeys 2-4 walk their upper specs; a storeys key beyond them (or an
        # empty storey) leaves a floor the partition has nothing to place on
        return design.storeys == 1 or (
            design.storeys <= 4 and len(design.upper or []) == design.storeys - 1
            and all(s.rooms for s in design.upper))
    # a library plan names a purpose the library has no family for: the old
    # method takes the building and the run says why. A plan with no use keys
    # at all is a model plan, not a fallback — nothing was taken from it.
    if any(r.use for (_n, r) in storey_rooms):
        n, bad = next((n, r) for (n, r) in storey_rooms
                      if not (r.use and _context.lib.family_of(r.use) is not None))
        where = f"room {bad.name}" if n == 1 else f"storey {n} room {bad.name}"
        _context.fallbacks.setdefault(
            design.name, f"{where}: purpose {bad.use or '(none)'} "
                         f"is not in the library")
    return False


def _assembly_for(design, wing=None):
    """The cached assembly for this design and entrance side — a wing's
    target and pins are part of the key, so one building can stand as a
    plain assembly and as wings of different asks — or None with the reason
    recorded: one per ask, whatever asks first (the map's measurement or
    the placement itself)."""
    if not _qualifies(design):
        return None
    ctx = _context
    if wing is not None and wing.entrance is not None \
            and wing.entrance[0] != design.entrance_side:
        # the pin says which side the wing is entered from: assemble the
        # design turned that way, the way the compound turns its parts
        design = dataclasses.replace(design, entrance_side=wing.entrance[0])
    key = (design.name, design.entrance_side, ctx.compound_of.get(design.name),
           wing.key() if wing is not None else None)
    if key in ctx.cache:
        return ctx.cache[key]
    asm, reason = None, None
    try:
        asm = _assemble(ctx, design, wing)
    except _Fallback as e:
        reason = str(e)
    except Exception as e:             # a bug never fails the world build
        reason = f"{type(e).__name__}: {e}"
    if asm is None:
        ctx.fallbacks.setdefault(design.name, reason or "no assembly")
        ctx.spot_built.pop(design.name, None)
        ctx.storey_notes.pop((design.name, design.entrance_side), None)
    else:
        ctx.fallbacks.pop(design.name, None)
    ctx.cache[key] = asm
    return asm


# ------------------------------------------------------------------ room picks

def _clearance_for(ctx, design, family):
    """The room's clearance: the wealth tier's step, one up for a common
    room, one down in a crowded setting, never below tight (design section
    5). The gap that buys is always room_composer.gap_for."""
    tier = design.wealth if design.wealth in ctx.lib.tiers else "modest"
    i = CLEARANCE_ORDER.index(TIER_CLEARANCE.get(tier, "tight"))
    if family not in RC.PRIVATE_FAMILIES:
        i += 1
    if _crowded(ctx, design):
        i -= 1
    return CLEARANCE_ORDER[max(0, min(i, len(CLEARANCE_ORDER) - 1))]


def _crowded(ctx, design):
    """A dense setting, an urban zone or a ship/station world keeps its rooms
    tight whatever their wealth."""
    if ctx.setting.get("density") == "dense":
        return True
    zone = ctx.zone_of.get(design.name)
    if zone is not None and is_urban_zone(zone):
        return True
    words = " ".join(str(ctx.setting.get(k) or "")
                     for k in ("genre", "era")).lower()
    return "ship" in words or "station" in words


def _band_for_share(ctx, family, share):
    """The family's band a share asks for: its own band nearest the shared
    band of that name (by centre area), or the shared name itself."""
    fam_bands = FR.family_bands(family, ctx.lib)
    want = SHARE_BAND.get(share, "medium")
    if not fam_bands:
        return want
    shared = (ctx.lib.vocab.get("sizeBands") or {}).get(want) or [12, 24]
    centre = (shared[0] + shared[1]) / 2.0

    def key(b):
        lo, hi = b["cells"]
        return (abs((lo + hi) / 2.0 - centre), fam_bands.index(b))

    return min(fam_bands, key=key)["name"]


def _sleeps_ok(room, singles, couples):
    s = room.get("sleeps") or {}
    return s.get("singles", 0) >= singles and s.get("couples", 0) >= couples


def _spare_beds(room, singles, couples):
    s = room.get("sleeps") or {}
    return (s.get("singles", 0) - singles) + (s.get("couples", 0) - couples)


def _composed_sleeps_ok(room, singles, couples):
    """A composed room's pieces against the sleepers it is owed: a couple's
    bed (a sleep.couple piece) sleeps two, every other sleep piece one —
    the same rule ``sleeps_right`` binds objects with. A composed room
    carries no ``sleeps`` count, so the pieces are the count."""
    cap, couple_beds = 0, 0
    for p in room.get("pieces") or []:
        role = p.get("role")
        if role == "sleep.couple":
            cap += 2
            couple_beds += 1
        elif role in ("sleep", "sleep.child", "med.bed", "cell.bed"):
            cap += 1
    return couple_beds >= couples and cap >= singles + 2 * couples


def _furnishable(ctx, spec, room, tier):
    """Whether every required piece of a variant picks an object at this
    band and tier: a variant that cannot be furnished must not enter a
    placement — the building would only fall back after placing it."""
    purpose = library_rooms.purpose_for_family(ctx.lib, room.get("family")) \
        or spec.use or "storage"
    rng = random.Random(0)
    for piece in room.get("pieces") or []:
        if piece.get("optional"):
            continue
        obj, _rot, _found, _reason = _pick_for(ctx, purpose, piece, tier, rng)
        if obj is None:
            return False
    return True


def _band_order(ctx, family, share_band):
    """The share's band first, then the family's neighbouring band one step
    larger and one step smaller, both by cell area — the tolerance a room gets
    before the assembler gives the building up. Families with bands of their
    own (library.json familySizeBands) walk those; every other family walks
    the shared bands."""
    fam_bands = FR.family_bands(family, ctx.lib)
    ordered = fam_bands or [{"name": n, "cells": c} for n, c in FR.BANDS.items()]
    ordered = sorted(ordered, key=lambda b: (b["cells"][0], b["cells"][1]))
    names = [b["name"] for b in ordered]
    if share_band not in names:
        return [share_band]
    i = names.index(share_band)
    out = [share_band]
    if i + 1 < len(names):
        out.append(names[i + 1])
    if i > 0:
        out.append(names[i - 1])
    return out


def _fit_rules(ctx, purpose):
    """(requires, forbids) — the role lists library.json's ``purposeFit``
    table names for a purpose, or empty ones: a purpose the table leaves out
    may use any recipe."""
    fit = (ctx.lib.vocab.get("purposeFit") or {}).get(purpose) or {}
    return tuple(fit.get("requires") or ()), tuple(fit.get("forbids") or ())


def _roles_fit(required, forbidden, roles):
    """A room's roles against one purpose's rules: nothing forbidden, and at
    least one piece carrying a required role (a required role is always a
    recipe's anchor, so one piece is one counter, one bulk store)."""
    return not (set(roles) & set(forbidden)) and \
        (not required or bool(set(roles) & set(required)))


def _room_roles(room):
    """The roles a stored room's pieces carry."""
    return {p.get("role") for p in room.get("pieces") or []}


def _recipe_roles(ctx, recipe):
    """The roles a recipe's pieces carry, every group's — a recipe names its
    groups, the groups table carries the pieces."""
    table = ctx.groups.get("groups") or {}
    return {piece.get("role")
            for grp in recipe.get("groups") or []
            for piece in (table.get(grp.get("group")) or {}).get("pieces") or []}


def _compose_pool(ctx, spec, family, tier, band, clearance, singles, couples,
                  recipes, rng, req=(), forb=()):
    """A few composed variants of the family's recipes at one band, or
    (None, why) — the live path ``generate_rooms`` takes, shared by families
    without stored rooms and stored families whose rooms all miss. The cache
    key carries the purpose's fit rules: a living room and a taproom share a
    family but never a pool."""
    if not recipes:
        return None, f"no {family} room stored and no recipe to compose one"
    key = (family, clearance, band, tier, singles, couples, req, forb)
    if key in ctx._pools:
        return ctx._pools[key], None
    rng.shuffle(recipes)
    reason = f"no {family} recipe composed a {band} room"
    out, sizes = [], set()
    for i, recipe in enumerate(recipes):
        # one seed per family, not per room: the world keeps its variety, and
        # buildings of the same family reuse what was composed — the first
        # five recipes fill the pool, and only a pool still empty walks on,
        # stopping at the first recipe that composes: a family whose smaller
        # band only one late recipe composes still yields it, without
        # walking every recipe for every band (rl-12b)
        if i >= 5 and out:
            break
        rooms, why = RC.compose(recipe, ctx.groups, clearance, "flush",
                                f"{ctx.world_seed}|assembler|{family}",
                                size_band=band, sleepers=(singles, couples))
        if not rooms:
            reason = why
            continue
        # a few recipes' worth of variants, so the placement has both size
        # parities to close the outline with — one recipe alone can leave
        # every leaf with a strip no room fits
        for r in rooms:
            if tuple(r["size"]) in sizes or not _furnishable(ctx, spec, r, tier):
                continue
            if (singles or couples) and \
                    not _composed_sleeps_ok(r, singles, couples):
                reason = f"no {family} recipe composed a {band} room " \
                         f"sleeping {singles} single and {couples} couple"
                continue
            out.append(r)
            sizes.add(tuple(r["size"]))
        if len(out) >= 8:
            break
    if not out and reason == f"no {family} recipe composed a {band} room":
        reason = f"no {family} recipe composed a {band} room that furnishes"
    if out:
        ctx._pools[key] = out
        return out, None
    return None, reason


class _NoUse:
    """A spec with no ``use``: _furnishable's check for a room a closer grows."""
    use = None


def _deep_pool(ctx, room, name, tier, req, forb):
    """The family's every recipe at a placed room's own band — the recipes
    the capped walk never composed — asked for only by a closing that wants a
    variant neither the pool nor the stored rooms hold (rl-12b): a storey
    that seats its rooms but cannot close may still grow one into a strip
    the first five recipes cannot shape."""
    fam, cl = room.get("family"), room.get("clearance")
    band = room.get("sizeBand")
    if fam is None or cl is None or band is None:
        return []
    singles, couples = ctx.sleepers.get(name, (0, 0))
    key = (fam, cl, band, tier, singles, couples, tuple(req), tuple(forb),
           "deep")
    if key in ctx._pools:
        return ctx._pools[key]
    recipes = [r for r in sorted(ctx.groups["recipes"].values(),
                                 key=lambda r: str(r.get("layout") or ""))
               if r.get("family") == fam
               and _roles_fit(req, forb, _recipe_roles(ctx, r))]
    spec = _NoUse()
    out, sizes = [], set()
    for recipe in recipes:
        rooms, _why = RC.compose(recipe, ctx.groups, cl, "flush",
                                 f"{ctx.world_seed}|assembler|{fam}",
                                 size_band=band, sleepers=(singles, couples))
        for r in rooms or []:
            if tuple(r["size"]) in sizes or not _furnishable(ctx, spec, r, tier):
                continue
            if (singles or couples) and \
                    not _composed_sleeps_ok(r, singles, couples):
                continue
            out.append(r)
            sizes.add(tuple(r["size"]))
        if len(out) >= 8:
            break
    ctx._pools[key] = out
    return out


def _room_pool(ctx, design, spec, family, tier, rng):
    """The variant rooms one design room may take, best first. The
    purposeFit table's rules apply to both stores (a living room never takes
    a taproom counter, a taproom always does). Each band of
    the family — the share's band, then one step larger, then one smaller —
    offers its stored rooms first and, for a family whose stored rooms all
    miss (band, clearance, wealth, sleepers, furnishings), candidates
    composed live from its recipes the same way; the first band that yields a
    room wins, and a room built on the spot for a family with stored rooms is
    noted. ([rooms], reason)."""
    share = _band_for_share(ctx, family, spec.share)
    singles, couples = ctx.sleepers.get(spec.name, (0, 0))
    clearance = clearance_of(ctx, design, family)
    req, forb = _fit_rules(ctx, spec.use)
    recipes = [r for r in sorted(ctx.groups["recipes"].values(),
                                 key=lambda r: str(r.get("layout") or ""))
               if r.get("family") == family
               and _roles_fit(req, forb, _recipe_roles(ctx, r))]
    stored = [r for r in FR.active(ctx.rooms) if r.get("family") == family
              and _roles_fit(req, forb, _room_roles(r))]
    reason = None
    for band in _band_order(ctx, family, share):
        missed = None
        if stored:
            fits = [r for r in stored
                    if r.get("clearance") == clearance
                    and tier in (r.get("wealth") or [])
                    and r.get("sizeBand") == band
                    and _sleeps_ok(r, singles, couples)]
            if fits:
                pool = [r for r in fits if _furnishable(ctx, spec, r, tier)]
                if pool:
                    pool.sort(key=lambda r: (_spare_beds(r, singles, couples),
                                             r.get("id", "")))
                    flush = [r for r in pool if r.get("style") == "flush"]
                    return flush or pool, None
                missed = (f"no {family} room of band {band} at {clearance} "
                          f"{tier} whose pieces all pick objects")
            else:
                missed = (f"no {family} room of band {band} at {clearance} "
                          f"{tier} sleeping {singles} single and "
                          f"{couples} coupled")
            reason = reason or missed
        composed, why = _compose_pool(ctx, spec, family, tier, band, clearance,
                                      singles, couples, recipes, rng,
                                      req=req, forb=forb)
        if composed:
            if stored and not ctx.slot_asking \
                    and not any(room == spec.name
                                for room, _note in
                                ctx.spot_built.get(design.name, [])):
                # the assembly retries a placement several times, so the
                # same room pools again: one note per room
                ctx.spot_built.setdefault(design.name, []).append(
                    (spec.name,
                     f"{family} room built on the spot at band {band} "
                     f"({missed or 'no stored room fits'})"))
            return composed, None
        reason = reason or why
    return [], reason or f"no {family} recipe composed a {share} room"


def clearance_of(ctx, design, family):
    """The cached clearance for one room of the build (clearances are asked
    for repeatedly while a building assembles)."""
    key = (design.name, family)
    if key not in ctx._clearances:
        ctx._clearances[key] = _clearance_for(ctx, design, family)
    return ctx._clearances[key]


# ------------------------------------------------------------------ placement

def _orientations(room):
    """The room's four turns, then the same mirrored (``rotate`` keeps every
    one of them valid)."""
    return [FR.rotate(room, q) for q in range(4)] + \
           [FR.rotate(room, q, mirror=True) for q in range(4)]


def _side_offsets(room, side):
    return list((room.get("doors") or {}).get(side) or [])


def _plan_side(side):
    """The wall name a plan side (model.Rect's compass: north is high y)
    picks out of the rooms' own door lists and this module's edges, which
    name low y north and high y south. The two agree on east and west and
    swap north and south."""
    return {"north": "south", "south": "north"}.get(side, side)


def _bbox(placed):
    return Rect(min(p.rect.x for p in placed), min(p.rect.y for p in placed),
                max(p.rect.x1 for p in placed) - min(p.rect.x for p in placed) + 1,
                max(p.rect.y1 for p in placed) - min(p.rect.y for p in placed) + 1)


def _overlaps(placed, rect):
    for p in placed:
        q = p.rect
        if not (rect.x + rect.w <= q.x or q.x + q.w <= rect.x
                or rect.y + rect.h <= q.y or q.y + q.h <= rect.y):
            return True
    return False


def _crosses_entrance_line(entry_rect, side, rect):
    """No room may stand further out than the entrance room on the entrance
    side, so the entrance room keeps its outside wall there. ``side`` is the
    plan's compass (north is high y), as it is everywhere a side leaves or
    enters this module; only the rooms' own door lists and the inner seam
    naming keep the edges' names."""
    if side == "north":
        return rect.y1 > entry_rect.y1
    if side == "south":
        return rect.y < entry_rect.y
    if side == "east":
        return rect.x1 > entry_rect.x1
    return rect.x < entry_rect.x


def _gaps_beside(placed, rect):
    """The empty spans beside the rect along each axis, between it and the
    nearest room that shares its other axis ((west, east), (north, south));
    unbounded where nothing stands beside it yet."""
    out = []
    for axis in ("x", "y"):
        lo, hi = -10 ** 9, 10 ** 9
        for p in placed:
            q = p.rect
            shares_other = (not (q.y + q.h <= rect.y or q.y >= rect.y + rect.h)) \
                if axis == "x" else \
                (not (q.x + q.w <= rect.x or q.x >= rect.x + rect.w))
            if not shares_other:
                continue
            near = (q.x + q.w <= rect.x and q.x + q.w > lo) if axis == "x" \
                else (q.y + q.h <= rect.y and q.y + q.h > lo)
            far = (q.x >= rect.x + rect.w and q.x < hi) if axis == "x" \
                else (q.y >= rect.y + rect.h and q.y < hi)
            if near:
                lo = q.x + q.w if axis == "x" else q.y + q.h
            if far:
                hi = q.x if axis == "x" else q.y
        out.append((rect.x - lo if axis == "x" else rect.y - lo,
                    hi - rect.x1 - 1 if axis == "x" else hi - rect.y1 - 1))
    return out


def _sliver(placed, rect):
    """True when a gap 1-2 cells wide would be left beside the rect: too
    narrow for any room or filler, so the placement is refused."""
    (west, east), (north, south) = _gaps_beside(placed, rect)
    return any(1 <= g <= MIN_SPAN - 1 for g in (west, east, north, south))


def _span_ok(a, b, cell, side):
    """A door cell strictly inside the shared wall span, the way
    ``shared_wall_cells`` picks its pair (the ends are corner walls).
    ``side`` is the side of ``a`` that ``b`` stands against."""
    if side == "south":        # b stands south of a
        if b.y != a.y1 + 1:
            return False
        lo, hi = max(a.x, b.x) + 1, min(a.x1, b.x1) - 1
        return cell[1] == a.y1 and lo <= cell[0] <= hi
    if side == "north":        # b stands north of a
        if a.y != b.y1 + 1:
            return False
        lo, hi = max(a.x, b.x) + 1, min(a.x1, b.x1) - 1
        return cell[1] == a.y and lo <= cell[0] <= hi
    if side == "east":         # b stands east of a
        if b.x != a.x1 + 1:
            return False
        lo, hi = max(a.y, b.y) + 1, min(a.y1, b.y1) - 1
        return cell[0] == a.x1 and lo <= cell[1] <= hi
    if a.x != b.x1 + 1:        # west
        return False
    lo, hi = max(a.y, b.y) + 1, min(a.y1, b.y1) - 1
    return cell[0] == a.x and lo <= cell[1] <= hi


def _seam_cells(parent, child, side, op, oc):
    """The facing door pair across a seam, or None when the aligned cells
    fall outside the shared span."""
    if side == "south":
        cell = (parent.rect.x + 1 + op, parent.rect.y1)
        far = (child.rect.x + 1 + oc, child.rect.y)
    elif side == "north":
        cell = (parent.rect.x + 1 + op, parent.rect.y)
        far = (child.rect.x + 1 + oc, child.rect.y1)
    elif side == "east":
        cell = (parent.rect.x1, parent.rect.y + 1 + op)
        far = (child.rect.x, child.rect.y + 1 + oc)
    else:
        cell = (parent.rect.x, parent.rect.y + 1 + op)
        far = (child.rect.x1, child.rect.y + 1 + oc)
    if not _span_ok(parent.rect, child.rect, cell, side):
        return None
    return [cell, far]


def _candidates(placed, entry, side_s, parent, pool, allow_slivers=False,
                limit=CANDIDATES_PER_ROOM, bounds=None):
    """Every way one room can stand against its parent — variant,
    orientation, side and door-candidate pairing — best first: smallest
    footprint growth, then the fewest hole cells left beside it, then the
    most sides standing against something. [(key, child, seam)]. A wing
    passes its target as ``bounds``: a room that spills out of it is no
    candidate at all."""
    out = []
    for variant in pool:
        for crm in _orientations(variant):
            w, h = crm["size"]
            for side in ("south", "east", "north", "west"):
                facing = OPPOSITE[side]
                p_offs = sorted(_side_offsets(parent.room, side))
                c_offs = sorted(_side_offsets(crm, facing))
                for op in p_offs:
                    for oc in c_offs:
                        if side == "south":
                            x, y = parent.rect.x + op - oc, parent.rect.y1 + 1
                        elif side == "north":
                            x, y = parent.rect.x + op - oc, parent.rect.y - h - 2
                        elif side == "east":
                            x, y = parent.rect.x1 + 1, parent.rect.y + op - oc
                        else:
                            x, y = parent.rect.x - w - 2, parent.rect.y + op - oc
                        rect = Rect(x, y, w + 2, h + 2)
                        if bounds is not None and not bounds.contains_rect(rect):
                            continue
                        if _overlaps(placed, rect):
                            continue
                        if entry is not None and \
                                _crosses_entrance_line(entry.rect, side_s, rect):
                            continue
                        if not allow_slivers and _sliver(placed, rect):
                            continue
                        cand = _Placed(None, crm, rect)
                        seam = _seam_cells(parent, cand, side, op, oc)
                        if seam is None:
                            continue
                        bbox = _bbox(placed + [cand])
                        covered = sum(q.rect.w * q.rect.h for q in placed) \
                            + rect.w * rect.h
                        # holes before footprint, the same order the leaves
                        # are ranked by: the search must meet the flush
                        # placements first or every leaf it collects needs
                        # closing work
                        key = (bbox.w * bbox.h - covered, bbox.w * bbox.h,
                               -_contact(placed, cand, bbox),
                               abs(op - (parent.rect.w - 2) // 2), x, y)
                        out.append((key, cand, seam))
    out.sort(key=lambda c: c[0])
    # the same room variant reached by equal door pairings lands on the same
    # cells: keep one of each (variant id, rect)
    seen, dedup = set(), []
    for (key, cand, seam) in out:
        mark = (cand.room.get("id"), cand.rect.x, cand.rect.y,
                cand.rect.w, cand.rect.h)
        if mark in seen:
            continue
        seen.add(mark)
        dedup.append((key, cand, seam))
    return dedup[:limit]


def _contact(placed, cand, bbox):
    """How many of the candidate's four sides stand against a placed room or
    the bounding box edge: sides that leave no hole beside them."""
    r = cand.rect
    n = 0
    for side, line in (("north", r.y), ("south", r.y1),
                       ("west", r.x), ("east", r.x1)):
        if ((side == "north" and line == bbox.y)
                or (side == "south" and line == bbox.y1)
                or (side == "west" and line == bbox.x)
                or (side == "east" and line == bbox.x1)):
            n += 1
            continue
        for p in placed:
            q = p.rect
            if not (q.x + q.w <= r.x or q.x >= r.x + r.w
                    or q.y + q.h <= r.y or q.y >= r.y + r.h):
                n += 1
                break
    return n


def _passage_room(length, horizontal=False):
    """A 1-cell passage as a fixed-room dict: no pieces, every edge cell a
    door candidate. Runs along y (into a parent's north or south wall) or
    along x (into its east or west wall)."""
    if horizontal:
        return {"size": [length, 1], "pieces": [], "family": "passage",
                "clearance": "tight", "style": "flush",
                "sleeps": {"singles": 0, "couples": 0},
                "doors": {"west": [0], "east": [0],
                          "north": list(range(length)),
                          "south": list(range(length))}}
    return {"size": [1, length], "pieces": [], "family": "passage",
            "clearance": "tight", "style": "flush",
            "sleeps": {"singles": 0, "couples": 0},
            "doors": {"north": [0], "south": [0],
                      "west": list(range(length)), "east": list(range(length))}}


def _passage_candidates(placed, entry, side_s, parent, pool, bounds=None,
                        limit=PASSAGE_CANDIDATES):
    """The last resort for one room: a 1-cell passage out of the parent and
    the child on its far end, best first. [(key, [passage, child], [seam,
    seam])]. A wing's target bounds the passage and the room on its far end
    the same way."""
    out = []
    for length in (1, 2, 3):
        for side in ("south", "east", "north", "west"):
            crm = _passage_room(length, horizontal=side in ("east", "west"))
            w, h = crm["size"]
            for op in sorted(_side_offsets(parent.room, side)):
                if side == "south":
                    x, y = parent.rect.x + op, parent.rect.y1 + 1
                elif side == "north":
                    x, y = parent.rect.x + op, parent.rect.y - h - 2
                elif side == "east":
                    x, y = parent.rect.x1 + 1, parent.rect.y + op
                else:
                    x, y = parent.rect.x - w - 2, parent.rect.y + op
                prect = Rect(x, y, w + 2, h + 2)
                if bounds is not None and not bounds.contains_rect(prect):
                    continue
                if _overlaps(placed, prect):
                    continue
                if entry is not None and \
                        _crosses_entrance_line(entry.rect, side_s, prect):
                    continue
                passage = _Placed(None, crm, prect, synthetic=True)
                seam = _seam_cells(parent, passage, side, op, 0)
                if seam is None:
                    continue
                for hit in _candidates(placed + [passage], entry, side_s,
                                       passage, pool, bounds=bounds, limit=1):
                    bbox = _bbox(placed + [passage, hit[1]])
                    covered = sum(q.rect.w * q.rect.h
                                  for q in placed + [passage]) \
                        + hit[1].rect.w * hit[1].rect.h
                    out.append(((bbox.w * bbox.h, bbox.w * bbox.h - covered),
                                [passage, hit[1]], [seam, hit[2]]))
    out.sort(key=lambda c: c[0])
    return out[:limit]


# ------------------------------------------------------------------ assembling

def _assemble(ctx, design, wing=None):
    rng = random.Random(f"{ctx.world_seed}|assembler|{design.name}")
    # the sleeper counts cover every floor (rl-12): a sleeping wing's
    # bedchambers sit upstairs, and the traveller beds its lodging promised
    # reach the guest rooms wherever the wing put them
    sleep_rooms = [{"name": r.name, "use": r.use} for r in design.rooms]
    sleep_rooms += [{"name": r.name, "use": r.use}
                    for s in design.upper or [] for r in s.rooms]
    # rl-19: names are unique over a building's storeys by the time they get
    # here; a duplicate that slips through still must not crash, only note
    # that its rooms share one bed count
    dup_names = sorted({q["name"] for q in sleep_rooms
                        if sum(1 for o in sleep_rooms
                               if o["name"] == q["name"]) > 1})
    ctx.sleepers = library_plan._sleepers(
        ctx.lib, sleep_rooms, design.residents, design.couples,
        getattr(design, "guests", 0) or 0)
    tier = design.wealth if design.wealth in ctx.lib.tiers else "modest"
    cond = design.condition if design.condition in ctx.lib.vocab["conditions"] \
        else "kept"
    pools = {}
    for r in design.rooms:
        fam = ctx.lib.family_of(r.use)
        pool, reason = _room_pool(ctx, design, r, fam, tier, rng)
        if not pool:
            raise _Fallback(f"room {r.name}: {reason}")
        pools[r.name] = pool

    children, root = _connection_tree(design)
    if root not in children:
        raise _Fallback("the design has no rooms")

    # the entrance room first: every variant's orientations with a door on
    # the entrance side, round-robin across the variants — the first
    # variant's every turn before the second's none, or a house whose floor
    # comes in one height only would never meet its matching bedrooms —
    # until one assembles all the way through
    failures = []
    turns = []
    for r in range(8):
        for variant in pools[root]:
            o = _orientations(variant)[r]
            if not _side_offsets(o, _plan_side(design.entrance_side)):
                continue
            if wing is not None and (o["size"][0] + 2 > wing.target[0]
                                     or o["size"][1] + 2 > wing.target[1]):
                continue    # the entrance room alone spills out of the target
            turns.append(o)
        if len(turns) >= 12:
            break
    if not turns:
        raise _Fallback(f"no {root} room with a door on its "
                        f"{design.entrance_side} wall"
                        + (f" that fits a {wing.target[0]}x{wing.target[1]} "
                           f"target" if wing is not None else ""))
    for e0 in turns[:12]:
        try:
            asm = _place_rooms(ctx, design, pools, children, root, e0,
                               tier, cond, wing)
            if design.upper:
                _build_uppers(ctx, design, asm, tier, cond)
            for dup in dup_names:
                asm.notes.append(
                    (dup, f"room {dup!r} on more than one storey of building "
                          f"{design.name}: those rooms share one bed count"))
            # the storey notes belong to the assembly this entrance side
            # ships, not merged across sides: a closet one side's copy took
            # is not a room the placed building lost
            ctx.storey_notes[(design.name, design.entrance_side)] = \
                list(asm.notes)
            return asm
        except _Fallback as e:
            failures.append(str(e))
    raise _Fallback(failures[0] if failures else "no assembly")


def _wing_bounds(wing, entry_rect, side):
    """The target's frame around an entry room placed at (0, 0): flush with
    the target's entrance-side edge — the search's entrance line keeps every
    other room on the inward side of it — and centred along that edge, so
    the rooms can grow both ways along it the way the plain search grows
    around the entry."""
    tw, th = wing.target
    if side in ("north", "south"):
        ex = (tw - entry_rect.w) // 2
        if side == "north":
            return Rect(-ex, -(th - entry_rect.h), tw, th)
        return Rect(-ex, 0, tw, th)
    ey = (th - entry_rect.h) // 2
    if side == "east":
        return Rect(-(tw - entry_rect.w), -ey, tw, th)
    return Rect(0, -ey, tw, th)


def _place_rooms(ctx, design, pools, children, root, entry_room, tier, cond,
                 wing=None):
    """Place every room of the tree from a given entrance-room orientation,
    close the outline, and furnish: the finished _Assembly.

    Placement is a bounded best-first search: partial placements queue by
    their hole cells and footprint, each room takes its few best candidates
    against its parent (a 1-cell corridor only when none fits), the complete
    placements that surface first are the tightest ones, and the outline
    closes on them until one closes clean — a greedy placement would happily
    paint a later room into a corner, or leave a strip nothing can fill. A
    wing bounds the whole search by its target rectangle and closes the
    leaves that fill it first; a pinned entrance is honoured strictly first
    (a leaf that cannot open it fails) and only then relaxed to the free
    pick, so a pin one leaf cannot serve does not hide one that can."""
    side = design.entrance_side
    entry = _Placed(root, entry_room,
                    Rect(0, 0, entry_room["size"][0] + 2, entry_room["size"][1] + 2))
    bounds = _wing_bounds(wing, entry.rect, side) if wing is not None else None

    def holes_of(placed):
        bbox = _bbox(placed)
        covered = sum(p.rect.w * p.rect.h for p in placed)
        return bbox.w * bbox.h - covered, bbox.w * bbox.h

    def leaf_key(placed):
        holes, area = holes_of(placed)
        touching = sum(_contact(placed[:i], p, _bbox(placed[:i + 1]))
                       for i, p in enumerate(placed) if i)
        # a wing's closest leaves first: the closers can fill a hole inside
        # the target, but no closer grows a wing onto the target's edge —
        # a constant 0 for the plain assembly, whose order stands
        miss = 0
        if wing is not None:
            bb = _bbox(placed)
            miss = 0 if (bb.w, bb.h) == wing.target else 1
        return (miss, holes, area, -touching)

    # (holes, footprint, counter): the counter keeps the sort from comparing
    # the payloads, and pops equal placements in insertion order. The queue
    # stays in the hundreds, so sorting it before each pop is cheap
    tick = [0]

    def push(placed, pairs, names, todo):
        holes, area = holes_of(placed)
        tick[0] += 1
        queue.append(((holes, area, tick[0]), placed, pairs, names, todo))

    queue = []
    push([entry], [], [root], list(children[root]))
    leaves = []      # [(key, placed, pairs, names)] complete placements
    expanded = 0
    while queue and len(leaves) < MAX_LEAVES and expanded < SEARCH_NODES:
        queue.sort(key=lambda item: item[0])
        (_key, placed, pairs, names, todo) = queue.pop(0)
        if not todo:
            leaves.append((leaf_key(placed), placed, pairs, names))
            continue
        name = todo[0]
        rest = todo[1:] + list(children.get(name, []))
        # the queue's rooms carry no names yet (the search hands them over in
        # ``names``); the parent is the placed room the tree means
        parent = next((p for p, n in zip(placed, names)
                       if n == _parent_of(children, name, root)), None)
        if parent is None:
            continue
        cands = _candidates(placed, entry, side, parent, pools[name],
                            bounds=bounds)
        expanded += 1
        for (_ck, child, seam) in cands:
            push(placed + [child], pairs + [seam], names + [name], rest)
        if cands:
            continue    # the corridor is the last resort, not a sibling branch
        for (_pk, rooms, seams) in _passage_candidates(placed, entry, side,
                                                       parent, pools[name],
                                                       bounds=bounds):
            push(placed + rooms, pairs + seams, names + [None, name], rest)
    if not leaves:
        first = children[root][0] if children[root] else "?"
        raise _Fallback(f"room {first}: no placement against {root}")
    leaves.sort(key=lambda l: l[0])
    reasons, pin_reasons = [], []
    tries = leaves[:STOREY_LEAF_TRIES if design.upper else LEAF_TRIES]
    relaxations = ((False, True) if wing is not None and wing.entrance
                   else (False,))
    for relax in relaxations:
        for (_key, placed, pairs, names) in tries:
            try:
                return _finish_assembly(ctx, design, side, placed, pairs,
                                        names, tier, cond, pools, wing=wing,
                                        relax_entrance=relax)
            except _Fallback as e:
                # a pin no leaf honoured is the ask's own failure; an
                # outline that would not close is one leaf's
                (pin_reasons if e.pinned else reasons).append(str(e))
    raise _Fallback(pin_reasons[0] if pin_reasons else
                    (reasons[0] if reasons else "no placement closed cleanly"))


def _finish_assembly(ctx, design, side, placed, pairs, names, tier, cond,
                     pools=None, wing=None, relax_entrance=False):
    """Close one complete placement to a rectangle, open its doors and
    furnish it: the finished _Assembly. Works on copies of the placed rooms:
    a leaf that fails after stretching must not bend the ones after it. A
    wing closes against its target rectangle and opens its pinned doors on
    the target's ring before anything furnishes; ``relax_entrance`` is the
    second pass over the leaves, where an entrance pin no leaf honoured
    takes the free pick and says so."""
    asm = _Assembly(design, side)
    placed = [_Placed(n, p.room, p.rect, p.synthetic)
              for (p, n) in zip(placed, names)]
    entry = placed[0]
    asm.rooms.extend(placed)
    for p in placed:        # the passages the search had to add
        if p.name is None:
            p.name = _free_name(asm, "Passage")
    asm.pairs.extend(pairs)
    # the search may hang rooms north or west of the entrance room (a room
    # taller than it cannot stand beside it without crossing its entrance
    # wall): shift the whole assembly to (0, 0) before anything derives
    # from the coordinates. A wing shifts its target frame there instead —
    # the rooms stand somewhere inside it, and the pins and the closing
    # address the frame's own cells
    if wing is not None:
        frame = _wing_bounds(wing, entry.rect, side)
        dx, dy = -frame.x, -frame.y
    else:
        box = _bbox(placed)
        dx, dy = -box.x, -box.y
    if dx or dy:
        for p in placed:
            p.rect = Rect(p.rect.x + dx, p.rect.y + dy, p.rect.w, p.rect.h)
        asm.pairs = [[(cx + dx, cy + dy) for (cx, cy) in pair]
                     for pair in asm.pairs]

    # ---- the door cells the search's seams opened, recorded before any
    # closer runs: a stretch line or a larger variant that would shift an
    # open seam off its door candidates is refused (_seams_survive), not
    # silently sealed shut
    for pair in asm.pairs:
        for cell in pair:
            owner = next((p for p in placed if _owns_ring(p, cell)), None)
            if owner is not None:
                owner.doors.add(cell)

    # ---- close the outline to a rectangle: stretch lines first, then
    # filler rooms for whatever is left. A wing closes against its target
    # first — the strip between the rooms and the target's edge is a hole
    # like any other — and only when the target cannot be met closes what
    # the rooms do cover to their own bounding box, saying which rectangle
    # that is: the caller decides whether the one it got is one it can use
    target = wing.ring() if wing is not None else None

    def close(box):
        _bbox_, holes = _holes(placed, box)
        if holes:
            _stretch_close(placed, entry, side, holes)
            _bbox_, holes = _holes(placed, box)
        if holes and pools:
            _variant_close(placed, entry, side, holes, pools, tier,
                           {r.name: _fit_rules(ctx, r.use)
                            for r in design.rooms})
            _bbox_, holes = _holes(placed, box)
        if holes:
            _fill_holes(ctx, asm, placed, holes, tier)
            _bbox_, holes = _holes(placed, box)
        return _bbox_, holes

    _bbox_, holes = close(target)
    if target is not None:
        # the closers are a pass each over moving ground: a hole that cannot
        # seam against its strict-walled neighbours seams fine against a
        # filler the pass before placed, so the passes repeat while they
        # still close cells of the target
        for _ in range(3):
            if not holes:
                break
            _bbox_, left = close(target)
            if not left or len(left) >= len(holes):
                holes = left
                break
            holes = left
        if holes:
            # the target cannot be met: close what the rooms do cover
            # instead — the wing reports the rectangle it grew to, and the
            # caller decides whether the one it got is one it can use
            _bbox_, holes = close(None)
    if holes:
        raise _Fallback(f"{len(holes)} hole cell(s) left that no stretch or "
                        f"filler closes")
    if target is not None:
        # the salvage pass may have finished the target after all (its
        # fillers stand on covered ground): say the wing missed only when a
        # cell of the target is truly still open
        _tbox, open_cells = _holes(placed, target)
        if open_cells:
            asm.notes.append((design.entrance_room,
                              f"the wing fills {_bbox_.w}x{_bbox_.h} of the "
                              f"{target.w}x{target.h} target"))

    # ---- the door cells the fillers' seams opened (the search's own were
    # recorded before the closers ran), and the entrance itself
    for pair in asm.pairs:
        for cell in pair:
            owner = next((p for p in placed if _owns_ring(p, cell)), None)
            if owner is not None:
                owner.doors.add(cell)
    for p in placed:
        if not p.doors and p is not entry:
            raise _Fallback(f"room {p.name} ended up with no door")
    if wing is None:
        offsets = _side_offsets(entry.room, _plan_side(side))
        if not offsets:
            raise _Fallback(f"the entrance room's {side} wall has no free cell")
        # the middle cell of the entry room's own wall — the cell the plain
        # builder's entrance pick opens. The offsets count the wall's
        # non-corner cells, so the middle sits (span - 3) // 2 into them
        if side in ("north", "south"):
            mid = (entry.rect.w - 3) // 2
        else:
            mid = (entry.rect.h - 3) // 2
        k = min(offsets, key=lambda k: abs(k - mid))
        asm.entrance = _ring_cell(entry.rect, side, k)
        entry.doors.add(asm.entrance)
    else:
        # a wing's doors sit on the target's ring and are opened before
        # anything furnishes, so no piece stands on a pinned cell or blocks
        # the walkway in front of it; every pin must land in a room a walk
        # from the entrance reaches, or this leaf cannot serve the ask
        reached = _reached_rooms(placed, asm.pairs, entry)
        if wing.entrance is not None:
            pside, pk = wing.entrance
            cell = _ring_cell(wing.ring(), pside, pk)
            owner = _pin_owner(placed, cell)
            if owner is not None and owner in reached:
                asm.entrance = cell
                owner.doors.add(cell)
            elif relax_entrance:
                pick = _free_entrance(placed, wing.ring(), side)
                if pick is None:
                    raise _Fallback(f"the {side} wall has no room that can "
                                    f"open the wing's entrance")
                asm.entrance, owner = pick
                owner.doors.add(asm.entrance)
                asm.notes.append((design.entrance_room,
                                  f"the pinned {pside} entrance at offset "
                                  f"{pk} could not be opened; the free pick "
                                  f"at {asm.entrance} stands"))
            else:
                raise _pin_refused(f"the pinned entrance on the {pside} wall "
                                   f"at offset {pk} has no room that can "
                                   f"open it")
        else:
            pick = _free_entrance(placed, wing.ring(), side)
            if pick is None:
                raise _Fallback(f"the {side} wall has no room that can open "
                                f"the wing's entrance")
            asm.entrance, owner = pick
            owner.doors.add(asm.entrance)
        for (dside, dk) in wing.doors:
            cell = _ring_cell(wing.ring(), dside, dk)
            owner = _pin_owner(placed, cell)
            if owner is None or owner not in reached:
                raise _pin_refused(f"the pinned {dside} door at offset {dk} "
                                   f"has no room that can open it")
            owner.doors.add(cell)

    # ---- the ground stair the upper storeys grow from (design 8.1f: the
    # stair sits inside the hall, corridor or entrance room, never on an
    # access cell, a door cell or a piece)
    stair = None
    if design.storeys > 1:
        stair = _reserve_stair(ctx, asm, placed, entry, tier)
        asm.stair_cell = stair

    asm.layouts, asm.lines = _furnish_assembly(ctx, design, asm, tier, cond)
    if stair is not None:
        # the furnisher's access cells keep the stair's own cell clear too
        owner = next((p for p in placed
                      if p.rect.interior().contains_cell(stair)), None)
        if owner is not None and owner.name in asm.layouts:
            asm.layouts[owner.name].reserved.add(stair)
    return asm


def _parent_of(children, name, root):
    for parent, kids in children.items():
        if name in kids:
            return parent
    return root


def _owns_ring(p, cell):
    r = p.rect
    x, y = cell
    return r.contains_cell(cell) and (x in (r.x, r.x1) or y in (r.y, r.y1))


def _ring_cell(rect, side, k):
    """The wall cell of door offset ``k`` on one side of a placed room —
    the plan's compass, north the high edge of ``rect``."""
    if side == "north":
        return (rect.x + 1 + k, rect.y1)
    if side == "south":
        return (rect.x + 1 + k, rect.y)
    if side == "west":
        return (rect.x, rect.y + 1 + k)
    return (rect.x1, rect.y + 1 + k)


def _pin_owner(placed, cell):
    """The room whose ring holds a pinned door cell and has a door candidate
    there, or None: a pin is only honoured on a cell the room can open."""
    for p in placed:
        if not _owns_ring(p, cell):
            continue
        s, k = _offset_of(p, cell)
        if s is not None and k in _side_offsets(p.room, s):
            return p
    return None


def _free_entrance(placed, ring, side):
    """A wing's free entrance pick: the door candidate nearest the middle of
    the target's entrance-side edge, on whatever room stands there (the
    entrance room usually, a filler when the wing closed one in front of
    it). (cell, owner), or None when no room on the edge can open one."""
    mid = (ring.w - 1) // 2 if side in ("north", "south") \
        else (ring.h - 1) // 2
    best = None
    for p in placed:
        at_edge = (p.rect.y1 == ring.y1 if side == "north"
                   else p.rect.y == ring.y if side == "south"
                   else p.rect.x == ring.x if side == "west"
                   else p.rect.x1 == ring.x1)
        if not at_edge:
            continue
        for k in _side_offsets(p.room, _plan_side(side)):
            cell = _ring_cell(p.rect, side, k)
            at = cell[0] if side in ("north", "south") else cell[1]
            key = (abs(at - mid), cell[0], cell[1])
            if best is None or key < best[0]:
                best = (key, cell, p)
    return None if best is None else (best[1], best[2])


def _reached_rooms(placed, pairs, entry):
    """The rooms a walk from the entrance room reaches over the open door
    pairs — a pinned door that lands anywhere else opens into dead space."""
    seen, queue = {id(entry)}, [entry]
    while queue:
        p = queue.pop()
        for pair in pairs:
            if not (_owns_ring(p, pair[0]) or _owns_ring(p, pair[1])):
                continue
            for q in placed:
                if q is not p and id(q) not in seen \
                        and (_owns_ring(q, pair[0]) or _owns_ring(q, pair[1])):
                    seen.add(id(q))
                    queue.append(q)
    return {p for p in placed if id(p) in seen}


def _free_name(asm, base):
    names = {p.name for p in asm.rooms} | {r.name for r in asm.design.rooms}
    name, k = base, 2
    while name in names:
        name = f"{base} {k}"
        k += 1
    return name


# ------------------------------------------------------------------ closing

def _holes(placed, box=None):
    """The bounding box (``box`` when the caller knows the outline the rooms
    must tile — a storey partition's rooms can all stop short of one edge
    together, and their own bbox would hide the strip) and the cells of it no
    room covers."""
    bbox = box if box is not None else _bbox(placed)
    filled = set()
    for p in placed:
        r = p.rect
        filled |= {(x, y) for x in range(r.x, r.x + r.w) for y in range(r.y, r.y + r.h)}
    return bbox, {(x, y) for x in range(bbox.x, bbox.x + bbox.w)
                  for y in range(bbox.y, bbox.y + bbox.h)} - filled


def _hole_rects(holes):
    """Holes cut into rectangles, biggest first (a greedy sweep from each
    top-left cell: as wide as the row runs, then as deep as every row of
    that width runs)."""
    out = []
    left = set(holes)
    while left:
        x0, y0 = min(left)
        w = 1
        while (x0 + w, y0) in left:
            w += 1
        h = 1
        while all((x0 + dx, y0 + h) in left for dx in range(w)):
            h += 1
        out.append(Rect(x0, y0, w, h))
        left -= {(x0 + dx, y0 + dy) for dx in range(w) for dy in range(h)}
    out.sort(key=lambda r: (-r.w * r.h, r.x, r.y))
    return out


def _stretch_close(placed, entry, side_s, holes):
    """Grow rooms into the holes by their own stretch lines: a valid line
    widens the room a cell into a hole beside it (either edge of the axis),
    without moving any door seam already opened. Repeats while anything
    grows, so a strip two cells deep takes two lines. ``entry`` may be None
    (a storey partition has no entrance line to keep)."""
    ctx = _context
    for _ in range(4):
        grew = False
        for p in list(placed):
            if p.synthetic:
                continue
            for axis in ("x", "y"):
                for line in sorted((p.room.get("stretch") or {}).get(axis) or []):
                    if FR.stretch_ok(p.room, axis, line,
                                     ctx.groups if ctx else None,
                                     ctx.lib if ctx else None) is not None:
                        continue
                    room2 = FR._insert_line(p.room, axis, line)
                    w, h = room2["size"]
                    for shift in (0, 1):    # grow the far edge, or the near one
                        if axis == "x":
                            rect2 = Rect(p.rect.x - shift, p.rect.y, w + 2, h + 2)
                            grown = {(rect2.x if shift else p.rect.x1 + 1, y)
                                     for y in range(p.rect.y, p.rect.y1 + 1)}
                        else:
                            rect2 = Rect(p.rect.x, p.rect.y - shift, w + 2, h + 2)
                            grown = {(x, rect2.y if shift else p.rect.y1 + 1)
                                     for x in range(p.rect.x, p.rect.x1 + 1)}
                        if not grown or not grown <= holes:
                            continue
                        if _overlaps([q for q in placed if q is not p], rect2):
                            continue
                        if entry is not None and \
                                _crosses_entrance_line(entry.rect, side_s, rect2):
                            continue
                        keep = (p.room, p.rect)
                        p.room, p.rect = room2, rect2
                        if not _seams_survive(p):
                            p.room, p.rect = keep
                            continue
                        holes -= grown
                        grew = True
                        break
                    else:
                        continue
                    break        # the room grew: its other lines moved with it
        if not grew:
            break


def _variant_close(placed, entry, side_s, holes, pools, tier, rules=None,
                   deep=False):
    """Swap a room for a larger variant of its own family when a strip of
    holes one or two cells deep runs along one of its edges (design 8.1
    step 4: 'a larger variant'): the room grows into the strip, every other
    edge — and the seams opened on them — staying where they were. The room's
    own band first; a stored room one band up, same clearance, wealth, sleep
    count and purpose fit (``rules``: name -> (requires, forbids), the
    purposeFit table's lists) when the band holds no bigger variant; and,
    for the pinned narrow gallery alone (``deep``), the later recipes
    ``_deep_pool`` composes — a slot's menu stays its pool's first five,
    the gallery's last resort may reach past them. ``entry`` may be None
    (a storey partition has no entrance line to keep)."""
    ctx = _context

    def bigger(p, size):
        room2 = next((o for v in pools.get(p.name, []) for o in _orientations(v)
                      if tuple(o["size"]) == size), None)
        if room2 is not None or ctx is None:
            return room2
        req, forb = (rules or {}).get(p.name) or ((), ())
        fam, cl = p.room.get("family"), p.room.get("clearance")
        singles, couples = ctx.sleepers.get(p.name, (0, 0))
        for r in FR.active(ctx.rooms):
            if (r.get("family") == fam and r.get("clearance") == cl
                    and tier in (r.get("wealth") or [])
                    and _sleeps_ok(r, singles, couples)
                    and _roles_fit(req, forb, _room_roles(r))
                    and tuple(r["size"]) == size):
                return r
        if deep:
            return next((o for v in _deep_pool(ctx, p.room, p.name, tier,
                                               req, forb)
                         for o in _orientations(v)
                         if tuple(o["size"]) == size), None)
        return None

    for p in list(placed):
        if p.synthetic or p.name not in pools:
            continue
        w, h = p.room["size"]
        for axis in ("y", "x"):
            for sign in (-1, -2, 1, 2):
                nw, nh = (w, h + abs(sign)) if axis == "y" else (w + abs(sign), h)
                if axis == "y" and sign < 0:      # grow north (the low edge)
                    strip = {(x, p.rect.y + sign)
                             for x in range(p.rect.x, p.rect.x1 + 1)}
                    rect2 = Rect(p.rect.x, p.rect.y + sign, nw + 2, nh + 2)
                elif axis == "y":                 # grow south (the high edge)
                    strip = {(x, p.rect.y1 + sign)
                             for x in range(p.rect.x, p.rect.x1 + 1)}
                    rect2 = Rect(p.rect.x, p.rect.y, nw + 2, nh + 2)
                elif sign < 0:                    # grow west
                    strip = {(p.rect.x + sign, y)
                             for y in range(p.rect.y, p.rect.y1 + 1)}
                    rect2 = Rect(p.rect.x + sign, p.rect.y, nw + 2, nh + 2)
                else:                             # grow east
                    strip = {(p.rect.x1 + sign, y)
                             for y in range(p.rect.y, p.rect.y1 + 1)}
                    rect2 = Rect(p.rect.x, p.rect.y, nw + 2, nh + 2)
                if not strip <= holes:
                    continue
                room2 = bigger(p, (nw, nh))
                if room2 is None:
                    continue
                if _overlaps([q for q in placed if q is not p], rect2):
                    continue
                if entry is not None and \
                        _crosses_entrance_line(entry.rect, side_s, rect2):
                    continue
                keep = (p.room, p.rect)
                p.room, p.rect = room2, rect2
                if not _seams_survive(p):
                    # the bigger variant's furniture stands where an open
                    # seam's door candidate was: the swap would seal it
                    p.room, p.rect = keep
                    continue
                holes -= strip
                w, h = nw, nh


def _seams_survive(p):
    """Every door cell the room already carries is still a door candidate of
    the stretched room at the same cell (an inserted line must not shift a
    seam that is already open)."""
    for cell in p.doors:
        side, k = _offset_of(p, cell)
        if side is None or k not in _side_offsets(p.room, side):
            return False
    return True


def _offset_of(p, cell):
    """(side, offset) of a ring cell on the placed room, or (None, None)."""
    r = p.rect
    x, y = cell
    if y == r.y and r.x < x < r.x1:
        return "north", x - r.x - 1
    if y == r.y1 and r.x < x < r.x1:
        return "south", x - r.x - 1
    if x == r.x and r.y < y < r.y1:
        return "west", y - r.y - 1
    if x == r.x1 and r.y < y < r.y1:
        return "east", y - r.y - 1
    return None, None


def _fill_holes(ctx, asm, placed, holes, tier):
    """Fill what is left of the outline: a stored or composed storage room
    when one fits the hole's floor exactly, else an empty store, closet or
    passage; each takes a door pair with whatever it touches."""
    for hole in _hole_rects(holes):
        if hole.w < MIN_SPAN or hole.h < MIN_SPAN:
            continue
        iw, ih = hole.w - 2, hole.h - 2
        filler = None
        if iw >= FURNISHED_FILLER - 2 and ih >= FURNISHED_FILLER - 2:
            filler = _compose_filler(ctx, asm.design.name, iw, ih, tier)
        if filler is None:
            filler = _empty_room(iw, ih, "storage")
        big = filler.get("family") == "storage" or hole.w * hole.h >= 18
        name = _free_name(asm, "Store" if big else
                          ("Passage" if min(hole.w, hole.h) <= MIN_SPAN
                           else "Closet"))
        block = _Placed(name, filler, Rect(hole.x, hole.y, hole.w, hole.h),
                        synthetic=True)
        seam = _filler_seam(placed, block)
        if seam is None:
            continue                # the hole stays; the caller reports it
        asm.rooms.append(block)
        placed.append(block)
        asm.pairs.append(seam)


def _empty_room(w, h, family):
    """A room with no furniture: every edge cell a door candidate."""
    return {"size": [w, h], "pieces": [], "family": family,
            "clearance": "tight", "style": "flush",
            "sleeps": {"singles": 0, "couples": 0},
            "doors": {"north": list(range(w)), "south": list(range(w)),
                      "west": list(range(h)), "east": list(range(h))}}


def _stored_filler(ctx, iw, ih, tier, band):
    """An active stored storage room whose floor is exactly (iw, ih) — turned
    once when only the sideways size fits — picked by the pools' rules:
    tight clearance, the tier among its wealth bands, the hole's own size
    band, every required piece furnishing, flush rooms first, id last."""
    fits = [r for r in FR.active(ctx.rooms)
            if r.get("family") == "storage"
            and r.get("clearance") == "tight"
            and tier in (r.get("wealth") or [])
            and r.get("sizeBand") == band
            and (r.get("size") == [iw, ih] or r.get("size") == [ih, iw])
            and _furnishable(ctx, _NoUse(), r, tier)]
    if not fits:
        return None
    fits.sort(key=lambda r: (_spare_beds(r, 0, 0), r.get("id", "")))
    flush = [r for r in fits if r.get("style") == "flush"]
    room = (flush or fits)[0]
    if room["size"] == [ih, iw]:
        room = FR.rotate(room, 1)
    return room


def _compose_filler(ctx, building, iw, ih, tier):
    """A filler for a hole's floor: an active stored storage room of exactly
    that size in either rotation first, else one composed to fit, else None.
    The compose results are cached on the context: every hole of one band in
    one building asks the same recipes at the same seed, and an ask that
    found no room never composes again. The returned room is shared, not
    copied — placed rooms are never mutated, only re-derived or turned."""
    if (building, iw, ih) in ctx._filler_none:
        return None
    area = iw * ih
    band = None
    for name, span in sorted((ctx.lib.vocab.get("sizeBands") or {}).items()):
        if not str(name).startswith("_") and isinstance(span, list) \
                and span[0] <= area <= span[1]:
            band = name
    if band is None:
        return None
    stored = _stored_filler(ctx, iw, ih, tier, band)
    if stored is not None:
        return stored
    seed = f"{ctx.world_seed}|assembler|{building}|filler"
    for rid, recipe in sorted(ctx.groups["recipes"].items(),
                              key=lambda kv: str(kv[1].get("layout") or "")):
        if recipe.get("family") != "storage":
            continue
        key = (rid, band, "tight", "flush", seed)
        rooms = ctx._filler_rooms.get(key)
        if rooms is None:
            rooms, _why = RC.compose(recipe, ctx.groups, "tight", "flush",
                                     seed, size_band=band)
            ctx._filler_rooms[key] = rooms
        for room in rooms:
            if room["size"] == [iw, ih]:
                return room
    ctx._filler_none.add((building, iw, ih))
    return None


def _filler_seam(placed, block):
    """A door pair between a filler and whatever it touches: two facing
    cells in one column (or row) of the rooms' shared span, nearest its
    middle — the same cell the builder's own auto-connect opens, so the
    walkways the filler's furniture keeps clear and the door the builder
    gives it always agree."""
    best = None
    for p in placed:
        if p is block:
            continue
        for side in ("north", "south", "east", "west"):
            facing = OPPOSITE[side]
            if not _side_offsets(p.room, side) \
                    or not _side_offsets(block.room, facing):
                continue
            if side in ("south", "north"):
                lo, hi = max(p.rect.x, block.rect.x) + 1, \
                    min(p.rect.x1, block.rect.x1) - 1
            else:
                lo, hi = max(p.rect.y, block.rect.y) + 1, \
                    min(p.rect.y1, block.rect.y1) - 1
            if hi < lo:
                continue
            mid = (lo + hi) // 2
            for at in range(lo, hi + 1):
                if side in ("south", "north"):
                    op, oc = at - p.rect.x - 1, at - block.rect.x - 1
                else:
                    op, oc = at - p.rect.y - 1, at - block.rect.y - 1
                if op not in _side_offsets(p.room, side) \
                        or oc not in _side_offsets(block.room, facing):
                    continue
                if side == "south" and p.rect.y1 + 1 == block.rect.y:
                    cell, far = (at, p.rect.y1), (at, block.rect.y)
                elif side == "north" and p.rect.y == block.rect.y1 + 1:
                    cell, far = (at, p.rect.y), (at, block.rect.y1)
                elif side == "east" and p.rect.x1 + 1 == block.rect.x:
                    cell, far = (p.rect.x1, at), (block.rect.x, at)
                elif side == "west" and p.rect.x == block.rect.x1 + 1:
                    cell, far = (p.rect.x, at), (block.rect.x1, at)
                else:
                    continue
                if not _span_ok(p.rect, block.rect, cell, side):
                    continue
                key = (abs(at - mid), TURN_SIDES.index(side), at)
                if best is None or key < best[0]:
                    best = (key, [cell, far])
    return None if best is None else best[1]


# ------------------------------------------------------------------ storeys

def corridor_width(ctx, design):
    """The corridor floor one partition gives its storey: a single cell when
    the building's shared rooms sit at tight clearance, two when any wealth
    or room buys a step up (design 8.1f)."""
    return 1 if _clearance_for(ctx, design, None) == "tight" else 2


def _stair_candidates(p):
    """A room's cells a stair may take: inside the walls, never on a door
    cell, an access cell or a cell one of its pieces covers."""
    from .layout_room import reserve_walkways
    cells = set(p.rect.interior().cells())
    reserved, _inner = reserve_walkways(p.rect, sorted(p.doors))
    for piece in p.room.get("pieces") or []:
        px, py = piece.get("at") or [0, 0]
        w, h = piece.get("size") or [1, 1]
        cells -= {(p.rect.x + 1 + px + dx, p.rect.y + 1 + py + dy)
                  for dx in range(int(w)) for dy in range(int(h))}
    return cells - reserved


def _nearest(cells, centre):
    return min(cells, key=lambda c: (abs(c[0] - centre[0]) + abs(c[1] - centre[1]),
                                     c[1], c[0]))


def _reserve_stair(ctx, asm, placed, entry, tier):
    """The ground cell the stairs rise from, reserved before anything
    furnishes it: the design's stairs room when the ground has it, then the
    entrance room, then the other rooms (synthetics last) — always inside a
    room, and nearest the building's middle, so the upper storeys can centred
    their corridors on it. When no room can take it, one stretch line into
    the entrance room buys the cell and the outline fills back to a
    rectangle; nothing works, and _Fallback takes the whole building."""
    box = _bbox(placed)
    centre = (box.x + box.w // 2, box.y + box.h // 2)
    order = []
    stairs = next((p for p in placed if p.name == asm.design.stairs_room), None)
    if stairs is not None:
        order.append(stairs)
    if entry not in order:
        order.append(entry)
    order += [p for p in placed if p not in order and not p.synthetic]
    order += [p for p in placed if p.synthetic]
    for p in order:
        cells = _stair_candidates(p)
        if cells:
            return _nearest(cells, centre)
    return _stretch_for_stair(ctx, asm, placed, entry, centre, tier)


def _stretch_for_stair(ctx, asm, placed, entry, centre, tier):
    """The rescue when no room had a free cell: the entrance room takes one
    of its stretch lines, growing a cell out of the outline (never on the
    entrance side — its door stays where it is), and the new strip fills so
    the building keeps its simple rectangle. The cell the line buys is the
    stair's; no line works -> _Fallback."""
    for axis in ("x", "y"):
        for line in sorted((entry.room.get("stretch") or {}).get(axis) or []):
            if FR.stretch_ok(entry.room, axis, line, ctx.groups, ctx.lib) is not None:
                continue
            room2 = FR._insert_line(entry.room, axis, line)
            w, h = room2["size"]
            for shift, direction in ((0, "south" if axis == "y" else "east"),
                                     (1, "north" if axis == "y" else "west")):
                if direction == _plan_side(asm.side):
                    continue        # the entrance wall stays where it is
                if axis == "x":
                    rect2 = Rect(entry.rect.x - shift, entry.rect.y, w + 2, h + 2)
                else:
                    rect2 = Rect(entry.rect.x, entry.rect.y - shift, w + 2, h + 2)
                if _overlaps([q for q in placed if q is not entry], rect2):
                    continue
                keep = (entry.room, entry.rect)
                entry.room, entry.rect = room2, rect2
                if not _seams_survive(entry):
                    entry.room, entry.rect = keep
                    continue
                # the outline grew by the line: fill the new strip so the
                # building stays a rectangle, and the fillers' seams open
                _box, holes = _holes(placed)
                if holes:
                    _fill_holes(ctx, asm, placed, holes, tier)
                    _box, holes = _holes(placed)
                    if holes:
                        raise _Fallback("the stretch line for the stairs left "
                                        "a hole no filler closes")
                for pair in asm.pairs:
                    for cell in pair:
                        owner = next((p for p in placed if _owns_ring(p, cell)), None)
                        if owner is not None:
                            owner.doors.add(cell)
                cells = _stair_candidates(entry)
                if cells:
                    return _nearest(cells, centre)
                raise _Fallback("the stretched entrance room still has no "
                                "cell for the stairs")
    raise _Fallback("no cell for the stairs and no stretch line buys one")


def _corridor_bands(rect, horizontal, width, anchor, k_a, k_b):
    """(corridor Rect, band A Rect or None, band B Rect or None) for one
    partition of ``rect``: the corridor band runs the long way, its floor
    ``width`` cells wide, sitting on ``anchor`` (the stair this storey grows
    from — a cell of the corridor's floor) and clamped so every side band
    with rooms to hold keeps its wall pair and a floor row; where the anchor
    allows a slide the side bands come out as even as it can make them. A
    band with none sits flush against the outline's edge instead (a loft's
    corridor). Band A is the north (or west) side. None when the outline is
    too shallow."""
    min_a = MIN_SPAN if k_a else 0
    min_b = MIN_SPAN if k_b else 0
    if horizontal:
        lo, hi = rect.y + min_a, rect.y1 - width - 1 - min_b
        if lo > hi:
            return None
        # every position whose floor holds the anchor, the most even split
        # of the two bands first
        spots = range(max(lo, anchor[1] - width), min(hi, anchor[1] - 1) + 1)
        if not spots:
            spots = [min(max(anchor[1] - 1, lo), hi)]
        elif not k_a and not k_b:
            spots = [min(max(anchor[1] - width, lo), hi)]
        elif not k_b:
            spots = [hi]         # no rooms south: flush against the south edge
        elif not k_a:
            spots = [lo]
        y0 = min(spots, key=lambda p: abs((p - rect.y)
                                          - (rect.y1 - (p + width + 1))))
        return (Rect(rect.x, y0, rect.w, width + 2),
                Rect(rect.x, rect.y, rect.w, y0 - rect.y) if k_a else None,
                Rect(rect.x, y0 + width + 2, rect.w,
                     rect.y1 - (y0 + width + 2) + 1) if k_b else None)
    lo, hi = rect.x + min_a, rect.x1 - width - 1 - min_b
    if lo > hi:
        return None
    spots = range(max(lo, anchor[0] - width), min(hi, anchor[0] - 1) + 1)
    if not spots:
        spots = [min(max(anchor[0] - 1, lo), hi)]
    elif not k_a and not k_b:
        spots = [min(max(anchor[0] - width, lo), hi)]
    elif not k_b:
        spots = [hi]
    elif not k_a:
        spots = [lo]
    x0 = min(spots, key=lambda p: abs((p - rect.x)
                                      - (rect.x1 - (p + width + 1))))
    return (Rect(x0, rect.y, width + 2, rect.h),
            Rect(rect.x, rect.y, x0 - rect.x, rect.h) if k_a else None,
            Rect(x0 + width + 2, rect.y, rect.x1 - (x0 + width + 2) + 1, rect.h)
            if k_b else None)


def _slot_tiles(band, k, horizontal):
    """One band's slot tiles along the long axis: [Rect], or None when the
    band is too short for that many slots (a band with no rooms still tiles,
    as one slot)."""
    k = max(1, k)
    span = band.w if horizontal else band.h
    if span < MIN_SPAN * k:
        return None
    base_w, rem = divmod(span, k)
    out, pos = [], 0
    for i in range(k):
        w = base_w + (1 if i < rem else 0)
        if horizontal:
            out.append(Rect(band.x + pos, band.y, w, band.h))
        else:
            out.append(Rect(band.x, band.y + pos, band.w, w))
        pos += w
    return out


def _share_key(spec):
    """A band's specs go to their slots biggest share first, as the ground
    gives its biggest rooms the biggest spans."""
    return -{"large": 3, "medium": 2, "small": 1}.get(spec.share, 2)


def _oriented_sizes(rooms):
    """A pool's distinct oriented sizes: (width, height, sides-with-doors)
    for every turn of every room, the door sides turned along — the turns
    a slot may sit a room in, without composing anything."""
    out = set()
    for r in rooms:
        for o in _orientations(r):
            fw, fh = o["size"]
            sides = frozenset(s for s, cells in (o.get("doors") or {}).items()
                              if cells)
            if sides:
                out.add((int(fw), int(fh), sides))
    return sorted(out, key=lambda e: (e[0], e[1], sorted(e[2])))


def _family_sizes(ctx, design, spec, family, tier, ask):
    """The family's size catalogue at one sleeper ask, cached on ctx per
    (design, family, tier, use, share, ask): the distinct oriented sizes of
    the rooms its pool could give — the first band of the share's band order
    with stored fits, else a pool an earlier slot of the run already
    composed. Never composes a room to build it: the sizes come from the
    stored rooms and the composed pools the run already has."""
    singles, couples = ask
    key = (design.name, family, tier, spec.use, spec.share, singles, couples)
    if key in ctx._size_catalogues:
        return ctx._size_catalogues[key]
    clearance = clearance_of(ctx, design, family)
    req, forb = _fit_rules(ctx, spec.use)
    stored = [r for r in FR.active(ctx.rooms) if r.get("family") == family
              and _roles_fit(req, forb, _room_roles(r))]
    entries = ()
    for band in _band_order(ctx, family,
                            _band_for_share(ctx, family, spec.share)):
        fits = [r for r in stored
                if r.get("clearance") == clearance
                and tier in (r.get("wealth") or [])
                and r.get("sizeBand") == band
                and _sleeps_ok(r, singles, couples)]
        if fits:
            entries = tuple(_oriented_sizes(fits))
            break
        pool = ctx._pools.get((family, clearance, band, tier, singles,
                               couples, req, forb))
        if pool:
            entries = tuple(_oriented_sizes(pool))
            break
    ctx._size_catalogues[key] = entries
    return entries


def _catalogue_widths(entries, facing, sh, horizontal, sealable=False):
    """The distinct widths along the band, walls in, a catalogue's rooms
    could take turned so a door candidate faces ``facing`` in a band whose
    floor is ``sh`` cells across: a size that fits neither rotation is
    dropped, and a rotation without a door on the corridor side never
    offers its width. ``sealable`` (the split's view) also drops a turn
    that would leave a sliver of 1 to MIN_SPAN - 1 cells of the band's
    depth behind the room — no closer can seal one that thin, so a width
    only depth-short turns offer would roll the split back at the closing
    step instead of missing cleanly here."""
    widths = set()
    for fw, fh, sides in entries:
        if facing not in sides:
            continue
        along, across = (fw, fh) if horizontal else (fh, fw)
        if across > sh:
            continue
        if sealable and 1 <= sh - across <= MIN_SPAN - 1:
            continue
        widths.add(along + 2)
    return sorted(widths)


def _ask_ladder(singles, couples):
    """Every smaller ask, the fullest first — the ladder a storey slot walks
    before it gives a room up (rl-12)."""
    return sorted(((a, b) for a in range(singles + 1)
                   for b in range(couples + 1)),
                  key=lambda ab: (-(ab[0] + 2 * ab[1]), -ab[0], -ab[1]))


def _spec_widths(ctx, design, spec, family, tier, facing, sh, horizontal):
    """One spec's candidate widths for a band: (width, 0) for every width
    its family's full-ask catalogue could door onto the corridor at this
    depth. A family that cannot seat the full ask in this band offers no
    width at all — no split exists and the band keeps its equal tiles,
    whose own ask ladder (rl-12) seats what it can with its notes: a split
    never trades beds for tightness. Only sealable turns offer their
    widths: a room depth-short of the band leaves a sliver no closer
    seals. [] when nothing fits the band."""
    singles, couples = ctx.sleepers.get(spec.name, (0, 0))
    entries = _family_sizes(ctx, design, spec, family, tier,
                            (singles, couples))
    return [(w, 0) for w in _catalogue_widths(entries, facing, sh,
                                              horizontal, sealable=True)]


def _band_splits(span, widths_per_room, keep=8):
    """The exact split of one band (the 1D dynamic program of the layout
    research, section 3.4): each room takes one width of its own family's
    catalogue — a (width, beds lost) pair, so a width that gives beds up
    can still lose to one that seats them — the widths tiling side by
    side, every room keeping its own wall ring, so they cover at most
    ``span`` cells and leave the rest as slack. The program runs over
    (cells used, rooms placed) and keeps the best few completions per
    state, best first by: beds lost, least slack, no sliver of 1 to
    MIN_SPAN - 1 cells, order closest to the plan's (the widths follow
    the shares), then the widths themselves, so the result stays
    deterministic. [(widths, slack)], best first; [] when no widths
    fit."""
    k = len(widths_per_room)

    def score(c):
        lost, used, dev, widths = c
        slack = span - used
        return (lost, slack, 1 if 0 < slack < MIN_SPAN else 0, dev, widths)

    # best[j][i]: the best few (beds lost, cells used, order deviation,
    # widths) placements of rooms j.. starting at cell i
    best = [[[] for _ in range(span + 1)] for _ in range(k + 1)]
    for i in range(span + 1):
        best[k][i] = [(0, 0, 0, ())]
    for j in range(k - 1, -1, -1):
        for i in range(span, -1, -1):
            out = []
            for w, lost in widths_per_room[j]:
                if i + w > span:        # the room would run past the band
                    continue
                for tail_lost, used, dev, tail in best[j + 1][i + w]:
                    out.append((lost + tail_lost, used + w,
                                dev + (1 if tail and w < tail[0] else 0),
                                (w,) + tail))
            out.sort(key=score)
            best[j][i] = out[:keep]
    return [(widths, span - used)
            for _lost, used, _dev, widths in best[0][0]]


def _slots_from_widths(band, widths, slack, horizontal):
    """The slot tiles one split hands _fill_slot: a slot per room of the
    width its family asked, side by side with each keeping its own walls,
    the split's slack added to the last slot for the closers to grow into."""
    out, pos = [], 0
    for j, w in enumerate(widths):
        tile = w + (slack if j == len(widths) - 1 else 0)
        if horizontal:
            out.append(Rect(band.x + pos, band.y, tile, band.h))
        else:
            out.append(Rect(band.x, band.y + pos, band.w, tile))
        pos += w
    return out


def _ranked_splits(ctx, design, specs, band, facing, horizontal, tier):
    """One band's size-first splits, best first: every spec's family offers
    the widths its catalogue could door onto the corridor at this band's
    depth, and the exact DP packs one width per room into the band's span.
    [] when any family has no width that fits the band at all — no split
    exists and the band keeps its equal tiles."""
    span = band.w if horizontal else band.h
    sh = (band.h - 2) if horizontal else (band.w - 2)
    widths_per_room = []
    for spec in sorted(specs, key=_share_key):
        widths = _spec_widths(ctx, design, spec, ctx.lib.family_of(spec.use),
                              tier, facing, sh, horizontal)
        if not widths:
            return []
        widths_per_room.append(widths)
    return _band_splits(span, widths_per_room)


def _size_first_band(ctx, design, sasm, placed, pools, spec_list, band,
                     facing, horizontal, tier, rng, storey):
    """One band filled size-first (rl-16): the ranked splits hand each spec
    a slot of its planned width and _fill_slot picks a pool room of exactly
    that size; a slot no room of the size doors onto the corridor rolls the
    band back — placed rooms, seams, pools and notes — and the next split
    takes its turn. True when a split seated the band; False after the
    ranked list runs out, when the caller falls back to the equal tiles
    (the rl-12 smaller-bedroom and closet fallbacks live inside _fill_slot
    either way)."""
    splits = _ranked_splits(ctx, design, spec_list, band, facing,
                            horizontal, tier)
    for widths, slack in splits:
        mark = (len(placed), len(sasm.pairs), len(sasm.notes), dict(pools))
        slots = _slots_from_widths(band, widths, slack, horizontal)
        try:
            for j, spec in enumerate(sorted(spec_list, key=_share_key)):
                room, pool, seam = _fill_slot(ctx, design, sasm, spec,
                                              slots[j], facing, horizontal,
                                              tier, rng, storey,
                                              target=widths[j] - 2)
                placed.append(room)
                if pool:
                    pools[room.name] = pool
                sasm.pairs.append(seam)
            return True
        except _SplitMiss:
            del placed[mark[0]:]
            del sasm.pairs[mark[1]:]
            del sasm.notes[mark[2]:]
            pools.clear()
            pools.update(mark[3])
    if splits:
        sasm.notes.append(
            (f"storey {storey}",
             "no size-first split could door its rooms onto the corridor: "
             "equal slots instead"))
    return False


def _fill_slot(ctx, design, sasm, spec, slot, facing, horizontal, tier, rng,
               storey, target=None):
    """One slot of a storey partition. A spec's pool room goes in turned so
    a door candidate faces the corridor, flush to the slot's corridor-facing
    edge and its low long edge, biggest clean fit first (a strip 1-2 cells
    wide beside it is refused while anything clean remains); when no room
    sleeping everyone the spec was asked to take fits the slot, a bedroom
    that sleeps fewer goes in before anything is given up (rl-12: the
    residents reach the upper rooms, and the slot fits what it fits), noted;
    a spec of None, or a pool with nothing that fits at all, becomes a
    closet or store, recorded in the run's notes. ``target`` (rl-16) fills
    the slot size-first instead: the ask ladder walks as ever, but only a
    room of exactly that many floor cells along the long axis goes in, and
    no room of the width doors the corridor raises _SplitMiss for the next
    ranked split — never a closet. (the _Placed room, its pool, its slot
    leftover) — the leftover is what the closing steps grow into."""
    sw = (slot.w - 2) if horizontal else (slot.h - 2)   # along the long axis
    sh = (slot.h - 2) if horizontal else (slot.w - 2)
    if spec is not None:
        fam = ctx.lib.family_of(spec.use)
        singles, couples = ctx.sleepers.get(spec.name, (0, 0))
        # every smaller ask, the fullest first — the room itself outranks the
        # beds: a bedroom sleeping some of its people beats a closet
        saved = ctx.sleepers.get(spec.name)
        ctx.slot_asking = True
        try:
            for ask in _ask_ladder(singles, couples):
                ctx.sleepers[spec.name] = ask
                pool, _reason = _room_pool(ctx, design, spec, fam, tier, rng)
                for allow_slivers in (False, True):
                    best = None
                    for variant in pool or []:
                        for o in _orientations(variant):
                            if not _side_offsets(o, facing):
                                continue
                            fw, fh = o["size"]
                            # the room stands fw on X and fh on Y whatever the
                            # slot's long axis, so a vertical slot measures its
                            # cross axis against fw — the placement below does
                            # not turn the pair
                            along, across = (fw, fh) if horizontal else (fh, fw)
                            if along > sw or across > sh:
                                continue
                            if target is not None and along != target:
                                continue
                            if not allow_slivers and \
                                    (1 <= sw - along <= MIN_SPAN - 1
                                     or 1 <= sh - across <= MIN_SPAN - 1):
                                continue
                            if facing == "south":
                                rect2 = Rect(slot.x, slot.y1 - fh - 1,
                                             fw + 2, fh + 2)
                            elif facing == "north":
                                rect2 = Rect(slot.x, slot.y, fw + 2, fh + 2)
                            elif facing == "east":
                                rect2 = Rect(slot.x1 - fw - 1, slot.y,
                                             fw + 2, fh + 2)
                            else:
                                rect2 = Rect(slot.x, slot.y, fw + 2, fh + 2)
                            room = _Placed(spec.name, o, rect2)
                            seam = _filler_seam([sasm.rooms[0]], room)
                            if seam is None:
                                continue
                            key = (-(fw * fh),
                                   0 if along == sw and across == sh else 1,
                                   variant.get("id", ""))
                            if best is None or key < best[0]:
                                best = (key, room, seam)
                    if best is not None:
                        (_key, room, seam) = best
                        if ask != (singles, couples):
                            sasm.notes.append(
                                (spec.name,
                                 f"storey {storey} slot sleeps "
                                 f"{ask[0] + 2 * ask[1]} of the "
                                 f"{singles + 2 * couples} asked of it: no "
                                 f"larger {fam} room fits"))
                        return room, pool or [], seam
        finally:
            ctx.slot_asking = False
            if saved is None:
                ctx.sleepers.pop(spec.name, None)
            else:
                ctx.sleepers[spec.name] = saved
        if target is not None:
            # size-first: the split planned this slot around one width of
            # the family's catalogue, and no room of it doors the corridor —
            # the next ranked split takes its turn, never a closet
            raise _SplitMiss(f"storey {storey}: no {fam} room of the planned "
                             f"width doors the corridor")
        if pool:
            why = f"no {fam} room of the pool fits"
        else:
            why = f"the {fam} pool is empty"
        sasm.notes.append(
            (spec.name, f"storey {storey} slot took a closet instead: {why}"))
    else:
        sasm.notes.append(
            (f"storey {storey}", "an empty slot became a "
             f"{'store' if sw * sh >= 12 else 'closet'}"))
    iw, ih = slot.w - 2, slot.h - 2
    big = iw * ih >= 12
    filler = _empty_room(iw, ih, "storage")
    room = _Placed(_free_name(sasm, "Store" if big else "Closet"), filler,
                   Rect(slot.x, slot.y, slot.w, slot.h), synthetic=True)
    seam = _filler_seam([sasm.rooms[0]], room)
    if seam is None:
        raise _Fallback(f"storey {storey}: a slot not even a closet can door")
    return room, [], seam


def partition_storey(ctx, design, rooms, rect, anchor, tier, cond, storey):
    """Lay one upper storey inside ``rect`` — any rectangle in the ground
    assembly's cells, so wings will call it per wing — by partition (design
    8.1f): a corridor band across the outline's short axis, its floor one
    cell at tight clearance and two otherwise, running the long way and
    centred on ``anchor``, the stair this storey grows from; the storey's
    ``rooms`` ([RoomSpec]) slot along the two sides, ceil(n/2) on the deeper
    side (odd counts give the shallower side the bigger slots), each turned
    so a door candidate faces the band and closed to its slot the way the
    ground closes — stretch lines, larger variants, closets and stores; a
    slot nothing fits becomes a closet or store, recorded in the run's
    notes. The stair from below lands in the band nearest ``anchor``; a
    storey above gets its stair about three cells along. A storey of one
    room whose outline the partition cannot slot (a gatehouse's or tower's
    thin upper floor) takes the room over the whole outline instead, the
    stair its only way in. Returns the finished ``_Storey``; any failure
    raises _Fallback and the caller gives the whole building back to the old
    method."""
    if len(rooms) == 1:
        try:
            return _corridor_storey(ctx, design, rooms, rect, anchor, tier,
                                    cond, storey)
        except _Fallback:
            return _one_room_storey(ctx, design, rooms[0], rect, anchor, tier,
                                    cond, storey)
    return _corridor_storey(ctx, design, rooms, rect, anchor, tier, cond, storey)


def _one_room_storey(ctx, design, spec, rect, anchor, tier, cond, storey):
    """A storey of one room in an outline no corridor partition can slot
    (rl-15: a 2-storey gatehouse's upper floor): the room itself, turned
    whichever way fits and sited over ``anchor`` — the stair from below must
    land inside it, never on its furniture — then closed to the outline the
    way the ground closes. The stair is the room's only way in, so it needs
    no door of its own; a storey above still gets its stair about three
    cells along. Raises _Fallback when no room of the family fits the
    outline over the stair or the holes will not close."""
    from .model import RoomSpec
    rng = random.Random(f"{ctx.world_seed}|assembler|{design.name}|"
                        f"storey{storey}")
    fam = ctx.lib.family_of(spec.use)
    pool, why = _room_pool(ctx, design, spec, fam, tier, rng)
    if not pool:
        raise _Fallback(f"storey {storey}: {why}")
    # the placement to beat: the most outline filled, then the first place
    # it fits — so what is left over gathers on one side for the closers
    best = None
    for variant in pool:
        for o in _orientations(variant):
            fw, fh = o["size"]
            if fw + 2 > rect.w or fh + 2 > rect.h:
                continue
            for x in range(rect.x, rect.x1 - fw):
                for y in range(rect.y, rect.y1 - fh):
                    room = _Placed(spec.name, o, Rect(x, y, fw + 2, fh + 2))
                    if anchor not in _stair_candidates(room):
                        continue
                    key = ((fw + 2) * (fh + 2), variant.get("id", ""), x, y)
                    if best is None or key > best[0]:
                        best = (key, room)
    if best is None:
        raise _Fallback(f"storey {storey}: no {fam} room fits the outline "
                        f"over the stair")
    room = best[1]
    sdesign = dataclasses.replace(design, name=f"{design.name} (floor {storey})",
                                  rooms=[], connections=[], entrance_room="",
                                  furniture=[])
    sasm = _Assembly(sdesign, design.entrance_side)
    sasm.rooms.append(room)
    placed, pools = [room], {room.name: pool}

    # ---- close to the outline: the same steps a slot closes with — fillers
    # first (a strip too narrow for anything, then stretch lines and larger
    # variants for what they cannot shape, and fillers again after each
    _box, holes = _holes(placed, rect)
    for closer in ("fill", "stretch", "fill", "variant", "fill"):
        if not holes:
            break
        if closer == "fill":
            _fill_holes(ctx, sasm, placed, holes, tier)
        elif closer == "stretch":
            _stretch_close(placed, None, None, holes)
        elif pools:
            _variant_close(placed, None, None, holes, pools, tier,
                           {room.name: _fit_rules(ctx, spec.use)})
        _box, holes = _holes(placed)
    if holes:
        raise _Fallback(f"storey {storey}: {len(holes)} hole cell(s) no "
                        f"stretch or filler closes")

    # ---- the doors the fillers' seams opened, and the design the storey
    # reports (the room itself needs no door: the stair is its way in)
    for pair in sasm.pairs:
        for cell in pair:
            owner = next((p for p in placed if _owns_ring(p, cell)), None)
            if owner is not None:
                owner.doors.add(cell)
    for p in placed:
        if not p.doors and p is not room:
            raise _Fallback(f"storey {storey}: room {p.name} ended up "
                            f"with no door")
    sdesign.rooms = [spec if p is room
                     else RoomSpec(name=p.name, purpose="storage")
                     for p in placed]
    sdesign.connections = [[_room_label(placed, pair[0]), _room_label(placed, pair[1])]
                           for pair in sasm.pairs]
    sdesign.entrance_room = room.name

    sasm.layouts, sasm.lines = _furnish_assembly(ctx, sdesign, sasm, tier, cond)

    # ---- the stairs: from below at the anchor, still clear of the furniture
    # the closers may have moved or swapped; to the storey above about three
    # cells along, never beside the first
    cands = _stair_candidates(room)
    if anchor not in cands:
        raise _Fallback(f"storey {storey}: no cell over the stair stays "
                        f"clear for it")
    down = anchor
    up = None
    if storey < design.storeys:
        far = [c for c in cands
               if max(abs(c[0] - down[0]), abs(c[1] - down[1])) >= 2]
        if not far:
            raise _Fallback(f"storey {storey}: no second cell in the room "
                            f"for its up stair")
        up = min(far, key=lambda c: (abs(max(abs(c[0] - down[0]),
                                             abs(c[1] - down[1])) - 3),
                                     c[1], c[0]))
    return _Storey(storey, sdesign, placed, sasm.pairs, down, up,
                   sasm.layouts, sasm.lines, sasm.notes)


def _corridor_storey(ctx, design, rooms, rect, anchor, tier, cond, storey):
    """``partition_storey``'s partition proper (design 8.1f); the dispatcher
    above decides when a storey takes it. The two-sided split goes first —
    a storey that laid out two-sided keeps exactly its layout — and only a
    split that cannot seat a single room of the storey gives every room to
    the deeper side, the corridor flush against the outline's other edge:
    a gallery over the front of a range too shallow for rooms either side
    (rl-12)."""
    horizontal = rect.w >= rect.h          # the corridor runs the long way
    # ---- the slot counts: the side of the anchor holding more outline
    # takes the extra slot of an odd count (odd counts give the shorter
    # side the smaller room, and the anchor side is the read on which side
    # a storey's big rooms belong)
    n = len(rooms)
    if horizontal:
        share_a, share_b = anchor[1] - rect.y, rect.y1 - anchor[1] + 1
    else:
        share_a, share_b = anchor[0] - rect.x, rect.x1 - anchor[0] + 1
    if share_a >= share_b:
        k_a, k_b = -(-n // 2), n // 2
    else:
        k_a, k_b = n // 2, -(-n // 2)
    one_sided = (n, 0) if share_a >= share_b else (0, n)
    try:
        return _lay_split(ctx, design, rooms, rect, anchor, tier, cond,
                          storey, horizontal, k_a, k_b)
    except _NoRoom:
        # a split that seated its rooms but failed to close keeps failing —
        # the next outline is tried, exactly as before, and a square-ish
        # outline keeps its landing
        if one_sided == (k_a, k_b):
            raise
        try:
            st = _lay_split(ctx, design, rooms, rect, anchor, tier, cond,
                            storey, horizontal, *one_sided)
        except _NoRoom:
            st = None
        tight = None
        if corridor_width(ctx, design) > 1:
            # a corridor one cell narrower buys the band the depth to seat
            # a room the wider gallery could not (rl-12b)
            try:
                tight = _lay_split(ctx, design, rooms, rect, anchor, tier,
                                   cond, storey, horizontal, *one_sided,
                                   width=1)
            except _Fallback:
                tight = None
        if tight is not None and (st is None or
                                  _seated(tight) > _seated(st)):
            return tight
        if st is not None:
            return st
        raise _NoRoom(f"storey {storey}: no room of the storey fits any slot")


def _seated(st):
    """How many of the storey's asked-for rooms a partition actually seated
    (the corridor and the closets a failed slot became are none of them)."""
    return sum(1 for p in st.rooms if not p.synthetic)


def _lay_split(ctx, design, rooms, rect, anchor, tier, cond, storey,
               horizontal, k_a, k_b, width=None):
    """One partition of a storey's outline at the split (k_a, k_b): the
    corridor band over the stair, its slots filled and closed, the stairs
    and the furnishing — everything the split's storey owes. ``width``
    pins the corridor; None draws the design's width, falling back to one
    cell on an outline too shallow for it."""
    from .model import RoomSpec
    rng = random.Random(f"{ctx.world_seed}|assembler|{design.name}|"
                        f"storey{storey}")
    bands = None
    for w in ((width,) if width is not None
              else (corridor_width(ctx, design), 1)):
        bands = _corridor_bands(rect, horizontal, w, anchor, k_a, k_b)
        if bands is not None:
            break
    if bands is None:
        raise _NoRoom(f"storey {storey}: the outline is too shallow to "
                      f"partition around a corridor")
    corr_rect, band_a, band_b = bands
    pinned = width == 1        # the gallery retry's narrow corridor, not a
    width = (corr_rect.h - 2) if horizontal else (corr_rect.w - 2)  # fallback

    # the corridor itself (a landing on a square-ish outline, a corridor on
    # a long one): an empty room, door candidates on its two long sides and
    # none on its ends or its flush edge — a storey's border is sealed
    if horizontal:
        corr_room = _empty_room(rect.w - 2, width, "passage")
        corr_room["doors"]["west"] = []
        corr_room["doors"]["east"] = []
        if band_b is None:
            corr_room["doors"]["south"] = []
        if band_a is None:
            corr_room["doors"]["north"] = []
    else:
        corr_room = _empty_room(width, rect.h - 2, "passage")
        corr_room["doors"]["north"] = []
        corr_room["doors"]["south"] = []
        if band_b is None:
            corr_room["doors"]["east"] = []
        if band_a is None:
            corr_room["doors"]["west"] = []
    long_dim, short_dim = max(rect.w, rect.h), min(rect.w, rect.h)
    base = "Landing" if long_dim <= 1.5 * short_dim else "Corridor"
    sdesign = dataclasses.replace(design, name=f"{design.name} (floor {storey})",
                                  rooms=[], connections=[], entrance_room="",
                                  furniture=[])
    sasm = _Assembly(sdesign, design.entrance_side)
    corr = _Placed(_free_name(sasm, base), corr_room, corr_rect, synthetic=True)
    sasm.rooms.append(corr)

    # ---- the slots: each band's, biggest slot to the biggest share — the
    # size-first splits first (rl-16: the slots follow the rooms the pool
    # could give, not the other way round), the equal tiles only where no
    # split could seat the band
    if horizontal:
        sides = [(band_a, "south", k_a), (band_b, "north", k_b)]
    else:
        sides = [(band_a, "east", k_a), (band_b, "west", k_b)]
    sides = [s for s in sides if s[0] is not None]

    ordered = sorted(rooms, key=lambda r: (_share_key(r), r.name))
    placed, pools = [corr], {}
    taken = 0
    for band, facing, k in sides:
        spec_list = ordered[taken:taken + k]
        taken += k
        if len(spec_list) == k and _size_first_band(ctx, design, sasm, placed,
                                                    pools, spec_list, band,
                                                    facing, horizontal, tier,
                                                    rng, storey):
            continue
        slot_list = _slot_tiles(band, k, horizontal)
        if slot_list is None:
            raise _Fallback(f"storey {storey}: the outline is too short to "
                            f"slot its rooms along the corridor")
        by_area = sorted(slot_list, key=lambda s: (s.w - 2) * (s.h - 2),
                         reverse=True)
        for slot, spec in zip(by_area, sorted(spec_list, key=_share_key)):
            room, pool, seam = _fill_slot(ctx, design, sasm, spec, slot, facing,
                                          horizontal, tier, rng, storey)
            placed.append(room)
            if pool:
                pools[room.name] = pool
            sasm.pairs.append(seam)
        for slot in by_area[len(spec_list):]:       # the band's empty slots
            room, _pool, seam = _fill_slot(ctx, design, sasm, None, slot, facing,
                                           horizontal, tier, rng, storey)
            placed.append(room)
            sasm.pairs.append(seam)
    sasm.rooms.extend(placed[1:])       # the corridor is already in

    # ---- the door cells the slots' seams opened, recorded before the
    # closers run so a stretch or a larger variant cannot shift one off its
    # door candidates and seal the room shut (_seams_survive)
    for pair in sasm.pairs:
        for cell in pair:
            owner = next((p for p in placed if _owns_ring(p, cell)), None)
            if owner is not None:
                owner.doors.add(cell)

    # ---- close to the outline: a slot's leftover strip takes its closet or
    # store first — a stretch line that grows a room part way into the strip
    # would strand a strip too narrow for anything — then stretch lines and
    # larger variants for whatever the fillers cannot shape, and fillers
    # again after each
    _box, holes = _holes(placed, rect)
    for closer in ("fill", "stretch", "fill", "variant", "fill"):
        if not holes:
            break
        if closer == "fill":
            _fill_holes(ctx, sasm, placed, holes, tier)
        elif closer == "stretch":
            _stretch_close(placed, None, None, holes)
        elif pools:
            _variant_close(placed, None, None, holes, pools, tier,
                           {r.name: _fit_rules(ctx, r.use) for r in rooms},
                           deep=pinned)
        _box, holes = _holes(placed)
    if holes:
        raise _Fallback(f"storey {storey}: {len(holes)} hole cell(s) no "
                        f"stretch or filler closes")
    if not any(not p.synthetic for p in placed):
        raise _NoRoom(f"storey {storey}: no room of the storey fits any slot")

    # ---- the doors the fillers' seams opened (the slots' own were recorded
    # before the closers ran), and the design the storey reports
    for pair in sasm.pairs:
        for cell in pair:
            owner = next((p for p in placed if _owns_ring(p, cell)), None)
            if owner is not None:
                owner.doors.add(cell)
    for p in placed:
        if not p.doors and p is not corr:
            raise _Fallback(f"storey {storey}: room {p.name} ended up "
                            f"with no door")
    spec_by_name = {r.name: r for r in rooms}
    sdesign.rooms = [spec_by_name.get(p.name)
                     or RoomSpec(name=p.name,
                                 purpose="a way through" if p is corr
                                 else "storage")
                     for p in placed]
    sdesign.connections = [[_room_label(placed, pair[0]), _room_label(placed, pair[1])]
                           for pair in sasm.pairs]
    sdesign.entrance_room = corr.name

    sasm.layouts, sasm.lines = _furnish_assembly(ctx, sdesign, sasm, tier, cond)

    # ---- the stairs: from below at the anchor itself whenever the band's
    # floor holds it (the stair template is walkable, so a walkway over the
    # cell is no conflict — the walkway is exactly how the stair is reached),
    # else the nearest floor cell; to the storey above about three cells
    # along, never beside the first
    floor_cells = set(corr_rect.interior().cells())
    down = anchor if anchor in floor_cells \
        else _nearest(sorted(floor_cells), anchor)
    up = None
    if storey < design.storeys:
        far = [c for c in floor_cells
               if max(abs(c[0] - down[0]), abs(c[1] - down[1])) >= 2]
        if not far:
            raise _Fallback(f"storey {storey}: no second cell in the corridor "
                            f"for its up stair")
        up = min(far, key=lambda c: (abs(max(abs(c[0] - down[0]),
                                             abs(c[1] - down[1])) - 3),
                                     c[1], c[0]))
    return _Storey(storey, sdesign, placed, sasm.pairs, down, up,
                   sasm.layouts, sasm.lines, sasm.notes)


def _room_label(placed, cell):
    """The name of the room whose ring holds a seam cell."""
    owner = next((p for p in placed if _owns_ring(p, cell)), None)
    return owner.name if owner is not None else ""


def _build_uppers(ctx, design, asm, tier, cond):
    """Every upper storey's partition, chained on the stair cells: the
    ground stair anchors storey 2's corridor, and each storey's up stair
    anchors the next. Any failure raises _Fallback — the whole building
    goes back rather than ship a storey the ground cannot vouch for, and
    the notes a failed attempt left die with it."""
    box = _bbox(asm.rooms)
    anchor = asm.stair_cell
    made = []
    for i, spec in enumerate(design.upper):
        st = partition_storey(ctx, design, spec.rooms,
                              Rect(0, 0, box.w, box.h), anchor, tier, cond, i + 2)
        made.append(st)
        anchor = st.up
    asm.uppers.extend(made)
    for st in made:
        asm.notes.extend(st.notes)


# ------------------------------------------------------------------ furniture

def _pick_for(ctx, purpose, piece, tier, rng):
    """The library object for one fixed-room piece at the piece's exact cells:
    ``pick_object``'s choice when its turned footprint covers them (and its
    back turns to the piece's back), else the same binding searched for an
    exact fit, nearest tier first. (object dict, rot, reason) — nothing is
    registered, so a pool may ask without placing. A piece that faces nowhere
    may take its object either way round."""
    from .library import binding_matches
    lib = ctx.lib
    role = piece.get("role")
    size = list(piece.get("size") or [1, 1])
    back = piece.get("back") if piece.get("back") in TURN_SIDES else None

    def exact(obj):
        if back:
            # an object that faces the way the piece asks is preferred, but
            # one that merely covers its cells (no facing of its own) will do
            return tuple(turned(obj["size"], TURN_SIDES.index(back))) == tuple(size)
        return tuple(obj["size"]) == tuple(size) \
            or tuple(turned(obj["size"], 1)) == tuple(size)

    def rot_for(obj):
        if back:
            return TURN_SIDES.index(back)
        return 0 if tuple(obj["size"]) == tuple(size) else 1

    obj, _widened = library_rooms.pick_object(lib, purpose, role, size, ctx.band,
                                              tier, rng, ctx.genre,
                                              prefer=ctx.registry.used_ids())
    if obj is not None and exact(obj):
        return obj, rot_for(obj), tier, None
    cats = ((lib.purposes.get(purpose) or {}).get("roles") or {}).get(role)
    if cats is None:
        cats = ((lib.purposes.get("*") or {}).get("roles") or {}).get(role) or []
    tiers = lib.tiers
    order = [tier] + sorted((t for t in tiers if t != tier),
                            key=lambda t: abs(tiers.index(t) - tiers.index(tier)))
    def covers(obj):
        # the piece's cells whatever way the object faces: a bath set end-on
        # to the wall when every bath object backs on its long side
        return tuple(obj["size"]) == tuple(size) \
            or tuple(turned(obj["size"], 1)) == tuple(size)

    def covers_rot(obj):
        return 0 if tuple(obj["size"]) == tuple(size) else 1

    def within(obj):
        # a flat piece — a run along a wall: a counter, a bench — takes a
        # shorter run of the same binding at the piece's low end when no
        # object covers its cells outright (a four-wide counter piece has no
        # four-wide object; a three-wide counter serves the same ale)
        ow, oh = obj["size"]
        return min(size) == 1 and ((ow <= size[0] and oh <= size[1])
                                   or (oh <= size[0] and ow <= size[1]))

    def within_rot(obj):
        ow, oh = obj["size"]
        if back:
            return TURN_SIDES.index(back)
        return 0 if (ow <= size[0] and oh <= size[1]) else 1

    # an object facing the piece's way first, at every tier; only then one
    # that just covers its cells; and last a shorter one inside a flat piece
    for fits, rot in ((exact, rot_for), (covers, covers_rot),
                      (within, within_rot)):
        for t in order:
            for cat in cats:
                objs = [o for o in sorted(lib.objects.values(), key=lambda o: o["id"])
                        if binding_matches(cat, o)
                        and (o["bands"] == ["*"] or ctx.band in o["bands"])
                        and t in o["wealth"]
                        and library_rooms.sleeps_right(role, o)
                        and (not o.get("onlyGenres")
                             or (ctx.genre or "") in o["onlyGenres"])
                        and fits(o)]
                if objs:
                    facing = [o for o in objs if o.get("back")]
                    group = facing or objs
                    reuse = [o for o in group if o["id"] in ctx.registry.used_ids()]
                    pool = reuse if reuse and rng.random() < library_rooms.REUSE_SHARE \
                        else group
                    obj = rng.choice(pool)
                    return obj, rot(obj), t, None
    return None, 0, tier, f"no {role} object of size {size} for {ctx.band} {tier}"


def _pick_exact(ctx, purpose, piece, tier, cond, rng):
    """(template dict, rot, reason): the registered template of the object
    ``_pick_for`` chose, registered at the tier it was found at."""
    obj, rot, found, reason = _pick_for(ctx, purpose, piece, tier, rng)
    if obj is None:
        return None, 0, reason
    return ctx.registry.get(obj, ctx.band, found, cond), rot, None


def _furnish_assembly(ctx, design, asm, tier, cond):
    """Every room's placed furniture: pieces at their fixed cells with their
    facings, one furniture line per placed piece. A required piece no object
    fills falls the whole building back; an optional one is left out."""
    from .layout_room import reserve_walkways
    layouts, lines = {}, []
    for p in asm.rooms:
        use = next((r.use for r in design.rooms if r.name == p.name), None)
        if use is None:
            use = library_rooms.purpose_for_family(ctx.lib, p.room.get("family")) \
                or "storage"
        # the room's pieces come from its family's own recipes, so their
        # roles bind under the family's purpose (a mill's workshop floor
        # binds its workbench under workshop, not mill)
        pick_purpose = library_rooms.purpose_for_family(ctx.lib, p.room.get("family")) \
            or use
        layout = RoomLayout()
        for piece in p.room.get("pieces") or []:
            rng = random.Random(f"{ctx.world_seed}|assembler|{design.name}|"
                                f"{p.name}|{piece.get('role')}")
            tmpl, rot, reason = _pick_exact(ctx, pick_purpose, piece, tier, cond, rng)
            if tmpl is None:
                if piece.get("optional"):
                    continue
                raise _Fallback(f"room {p.name}: {reason}")
            px, py = piece.get("at") or [0, 0]
            pos = (p.rect.x + 1 + px, p.rect.y + 1 + py)
            layout.placements.append((tmpl["name"], pos))
            if rot:
                layout.turns[(tmpl["name"], pos)] = rot
            pool = ""
            if ctx.registry.is_container(tmpl["name"]):
                pool = library_plan.pool_for_purpose(use, ctx.pool_names) or ""
            lines.append(FurniturePlan(template=tmpl["name"], room=p.name,
                                       count=1, loot_pool=pool))
        layout.reserved, _inner = reserve_walkways(p.rect, sorted(p.doors))
        layouts[p.name] = layout
    return layouts, lines


# ------------------------------------------------------------------ the layout

def _inject_templates(templates=None):
    """The templates the assemblies picked, into the world and the plan, once
    each: the plan dict also carries the registry key, so a re-roll of a
    built plan keeps the same template names. ``templates`` is the dict the
    caller is laying out with (the map measures with its own copy), and the
    names must exist there too, the way the old furniture path adds its own."""
    ctx = _context
    if ctx is None:
        return
    fresh = {t["name"] for t in ctx.registry.templates()} - ctx.injected
    if not fresh:
        return
    from .model import ObjectTemplate
    for key, t in ctx.registry.by_key.items():
        if t["name"] not in fresh or t["name"] in ctx.injected:
            continue
        extras = {"forSleep": t["forSleep"], "light": t.get("light", 0)}
        if t.get("back"):
            extras["back"] = t["back"]
        ot = ObjectTemplate(
            name=t["name"], size=tuple(t["size"]), walkability=t["walkability"],
            description=t["description"], physicalDescription=t["physicalDescription"],
            tags=list(t["tags"]), extras=extras)
        if ctx.world_templates is not None and t["name"] not in ctx.world_templates:
            ctx.world_templates[t["name"]] = ot
        if templates is not None and t["name"] not in templates:
            templates[t["name"]] = ot
        ctx.plan_data.setdefault("templates", []).append(dict(t, libraryKey=list(key)))
        ctx.injected.add(t["name"])


def _building_layout(asm, origin):
    """The assembly as the ``BuildingLayout`` the pipeline expects, shifted
    to ``origin`` (its bottom-left cell). The upper storeys ride along as
    partitions (``upper_asm``) and the ground stair cell with them, for the
    floors extension to collect when it runs."""
    ox, oy = origin
    box = _bbox(asm.rooms)   # a wing's rooms need not touch the target's origin
    w, h = box.w, box.h
    design = dataclasses.replace(asm.design, furniture=list(asm.lines))
    b = BuildingLayout(design, Rect(ox, oy, w, h))
    b.assembled = True
    b.stair_cell = (asm.stair_cell[0] + ox, asm.stair_cell[1] + oy) \
        if asm.stair_cell else None
    b.upper_asm = asm.uppers
    if getattr(design, "units", None):
        # a unit building the assembler took houses all its copies upstairs
        # (that is what qualified it): the stamping the floors extension
        # does per storey carries them
        from .layout_building import units_per_storey
        b.residents = units_per_storey(design) * (design.storeys - 1) \
            * design.units.residents
    b.furniture = list(asm.lines)
    for p in asm.rooms:
        room = RoomOut(p.name, Rect(p.rect.x + ox, p.rect.y + oy,
                                    p.rect.w, p.rect.h))
        room.doors = {(x + ox, y + oy) for (x, y) in p.doors}
        layout = asm.layouts[p.name]
        moved = RoomLayout()
        for (tname, pos) in layout.placements:
            moved.placements.append((tname, (pos[0] + ox, pos[1] + oy)))
        for ((tname, pos), rot) in layout.turns.items():
            moved.turns[(tname, (pos[0] + ox, pos[1] + oy))] = rot
        moved.reserved = {(x + ox, y + oy) for (x, y) in layout.reserved}
        room.furniture = moved
        b.rooms.append(room)
    b.door_pairs = [[(c[0] + ox, c[1] + oy) for c in pair] for pair in asm.pairs]
    b.entrance_side = asm.side
    b.entrance_door = (asm.entrance[0] + ox, asm.entrance[1] + oy)
    b.dropped = []
    return b


def upper_layout(bl, index, rect):
    """The assembled upper storey ``index`` (0-based over the design's
    uppers) as the ``BuildingLayout`` the floors extension consumes, its
    partition re-originated onto ``rect`` (the storey's plane, the size of
    the ground's) with the stair cells recorded on the layout. None when the
    ground was not assembled or the index is past its storeys — the caller
    lays the storey out its own way. Context-free by design: the floors
    extension runs after the assembler has stepped aside."""
    uppers = getattr(bl, "upper_asm", None) or []
    if not 0 <= index < len(uppers):
        return None
    st = uppers[index]
    ox, oy = rect.x, rect.y
    w = max(p.rect.x1 for p in st.rooms) + 1
    h = max(p.rect.y1 for p in st.rooms) + 1
    design = dataclasses.replace(st.design, furniture=list(st.lines))
    b = BuildingLayout(design, Rect(ox, oy, w, h))
    b.assembled = True
    b.furniture = list(st.lines)
    for p in st.rooms:
        room = RoomOut(p.name, Rect(p.rect.x + ox, p.rect.y + oy,
                                    p.rect.w, p.rect.h))
        room.doors = {(x + ox, y + oy) for (x, y) in p.doors}
        layout = st.layouts[p.name]
        moved = RoomLayout()
        for (tname, pos) in layout.placements:
            moved.placements.append((tname, (pos[0] + ox, pos[1] + oy)))
        for ((tname, pos), rot) in layout.turns.items():
            moved.turns[(tname, (pos[0] + ox, pos[1] + oy))] = rot
        moved.reserved = {(x + ox, y + oy) for (x, y) in layout.reserved}
        room.furniture = moved
        b.rooms.append(room)
    b.door_pairs = [[(c[0] + ox, c[1] + oy) for c in pair] for pair in st.pairs]
    b.entrance_side = bl.entrance_side
    # the build-time door over the ground door: the storey is sealed, and
    # finish_scenario strips this cell again in the shipped scenario
    if b.entrance_side == "north":
        b.entrance_door = (ox + w // 2, oy + h - 1)
    elif b.entrance_side == "south":
        b.entrance_door = (ox + w // 2, oy)
    elif b.entrance_side == "west":
        b.entrance_door = (ox, oy + h // 2)
    else:
        b.entrance_door = (ox + w - 1, oy + h // 2)
    b.dropped = []
    b.stair_down_cell = (st.down[0] + ox, st.down[1] + oy) if st.down else None
    b.stair_up_cell = (st.up[0] + ox, st.up[1] + oy) if st.up else None
    return b
