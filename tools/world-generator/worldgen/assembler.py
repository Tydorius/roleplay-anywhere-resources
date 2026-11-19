"""The room assembler: one-storey library buildings placed from the room
library's own rooms.

A qualifying design (every room carrying a library ``use`` that maps to a
family, one storey, no units, not a compound part) is assembled instead of
cut from a footprint: each room is an active stored room of its family (or,
for a family with none stored, composed live the way the room generator
does), picked for the building's wealth, the room's share and its assigned
sleepers. Rooms are placed along the connection tree — the entrance room
first, every child against a free side of its parent with a door candidate
of each lining up across the shared wall — then the outline is closed to a
rectangle with stretch lines and filler rooms. The result goes back to the
pipeline in the shapes ``layout_building`` returns, each room's furniture
pre-placed at the fixed cells the room's pieces name, so nothing downstream
changes.

Any failure picks the whole building back to the old method and records why
in ``out.fallbacks``: a world never fails because of the assembler. Off (the
default) the module is dormant and the pipeline runs exactly as before.
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
from .model import FurniturePlan, Rect, is_urban_zone

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


class _Fallback(Exception):
    """Assembly failed: the building goes back to the old method."""


class _Placed:
    """One room of the assembly: the oriented fixed-room dict, its rect (the
    room's floor plus its wall ring) and the door cells opened on its ring."""

    def __init__(self, name, room, rect, synthetic=False):
        self.name = name
        self.room = room            # the fixed-room dict, already oriented
        self.rect = rect            # Rect of the floor plus its wall ring
        self.synthetic = synthetic  # a passage or filler, not a design room
        self.doors = set()          # ring cells opened as doors (absolute)


class _Assembly:
    def __init__(self, design, side):
        self.design = design
        self.side = side            # the entrance side asked for
        self.rooms = []             # [_Placed] in placement order
        self.pairs = []             # [[cellA, cellB]] facing door pairs
        self.entrance = None        # (x, y) on the bounding ring
        self.lines = []             # [FurniturePlan] the assembled furniture
        self.layouts = {}           # room name -> RoomLayout in local cells


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
        parts = set()
        for c in getattr(plan, "compounds", None) or []:
            for p in getattr(c, "parts", None) or []:
                name = p.get("name") if isinstance(p, dict) else getattr(p, "name", "")
                if name:
                    parts.add(name)
        self.compound_parts = parts
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
        self.cache = {}          # (name, entrance_side) -> _Assembly | None
        self.fallbacks = {}      # building name -> reason
        self.injected = set()    # template names already in the plan
        self.sleepers = {}       # design room name -> (singles, couples)
        self._clearances = {}    # (design name, family) -> clearance
        self._pools = {}         # (family, clearance, band, sleepers) -> [rooms]


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


def footprint(design, templates=None):
    """The (w, h) an assembled building takes, or None when the assembler is
    off or the design does not qualify. ``building_footprint`` calls this
    first so the map, the packer and the layout agree."""
    asm = _assembly_for(design)
    if asm is None:
        return None
    _inject_templates(templates)
    return (max(p.rect.x1 for p in asm.rooms) + 1,
            max(p.rect.y1 for p in asm.rooms) + 1)


def build(design, origin, templates=None):
    """The assembled BuildingLayout at ``origin``, or None (the caller falls
    back to the old method)."""
    asm = _assembly_for(design)
    if asm is None:
        return None
    _inject_templates(templates)
    return _building_layout(asm, origin)


def fallback_note(name):
    """(label, reason) when a building fell back to the old method."""
    if _context is None or name not in _context.fallbacks:
        return None
    return (f"building {name}", f"room assembler fell back: {_context.fallbacks[name]}")


# ------------------------------------------------------------------ qualifying

def _qualifies(design):
    if _context is None:
        return False
    if getattr(design, "units", None) or design.storeys > 1 or design.upper:
        return False
    if design.name in _context.compound_parts or not design.rooms:
        return False
    if all(r.use and _context.lib.family_of(r.use) is not None
           for r in design.rooms):
        return True
    # a library plan names a purpose the library has no family for: the old
    # method takes the building and the run says why. A plan with no use keys
    # at all is a model plan, not a fallback — nothing was taken from it.
    if any(r.use for r in design.rooms):
        bad = next(r for r in design.rooms
                   if not (r.use and _context.lib.family_of(r.use) is not None))
        _context.fallbacks.setdefault(
            design.name, f"room {bad.name}: purpose {bad.use or '(none)'} "
                         f"is not in the library")
    return False


def _assembly_for(design):
    """The cached assembly for this design and entrance side, or None with
    the reason recorded: one per building, whatever asks first (the map's
    measurement or the placement itself)."""
    if not _qualifies(design):
        return None
    ctx = _context
    key = (design.name, design.entrance_side)
    if key in ctx.cache:
        return ctx.cache[key]
    asm, reason = None, None
    try:
        asm = _assemble(ctx, design)
    except _Fallback as e:
        reason = str(e)
    except Exception as e:             # a bug never fails the world build
        reason = f"{type(e).__name__}: {e}"
    if asm is None:
        ctx.fallbacks.setdefault(design.name, reason or "no assembly")
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


def _room_pool(ctx, design, spec, family, tier, rng):
    """The variant rooms one design room may take, best first. Fixed families
    read their stored rooms; every other family composes live the way
    ``generate_rooms`` does. ([rooms], reason)."""
    band = _band_for_share(ctx, family, spec.share)
    singles, couples = ctx.sleepers.get(spec.name, (0, 0))
    if any(r.get("family") == family for r in FR.active(ctx.rooms)):
        pool = [r for r in FR.active(ctx.rooms)
                if r.get("family") == family
                and r.get("clearance") == clearance_of(ctx, design, family)
                and tier in (r.get("wealth") or [])
                and r.get("sizeBand") == band
                and _sleeps_ok(r, singles, couples)]
        if not pool:
            return [], (f"no {family} room of band {band} at "
                        f"{clearance_of(ctx, design, family)} {tier} "
                        f"sleeping {singles} single and {couples} coupled")
        pool = [r for r in pool if _furnishable(ctx, spec, r, tier)]
        if not pool:
            return [], (f"no {family} room of band {band} at "
                        f"{clearance_of(ctx, design, family)} {tier} whose "
                        f"pieces all pick objects")
        pool.sort(key=lambda r: (_spare_beds(r, singles, couples), r.get("id", "")))
        flush = [r for r in pool if r.get("style") == "flush"]
        return flush or pool, None
    recipes = [r for r in sorted(ctx.groups["recipes"].values(),
                                 key=lambda r: str(r.get("layout") or ""))
               if r.get("family") == family]
    if not recipes:
        return [], f"no {family} room stored and no recipe to compose one"
    clearance = clearance_of(ctx, design, family)
    key = (family, clearance, band, tier, singles, couples)
    if key in ctx._pools:
        return ctx._pools[key], None
    rng.shuffle(recipes)
    reason = f"no {family} recipe composed a {band} room"
    out, sizes = [], set()
    for recipe in recipes[:5]:
        # one seed per family, not per room: the world keeps its variety, and
        # buildings of the same family reuse what was composed
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
            out.append(r)
            sizes.add(tuple(r["size"]))
        if len(out) >= 8:
            break
    if not out and reason == f"no {family} recipe composed a {band} room":
        reason = f"no {family} recipe composed a {band} room that furnishes"
    if out:
        ctx._pools[key] = out
        return out, None
    return [], reason


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
    side, so the entrance room keeps its outside wall there. The library's
    sides name the grid the rooms use: south and east are the high edges."""
    if side == "south":
        return rect.y1 > entry_rect.y1
    if side == "north":
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
                limit=CANDIDATES_PER_ROOM):
    """Every way one room can stand against its parent — variant,
    orientation, side and door-candidate pairing — best first: smallest
    footprint growth, then the fewest hole cells left beside it, then the
    most sides standing against something. [(key, child, seam)]."""
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


def _passage_candidates(placed, entry, side_s, parent, pool,
                        limit=PASSAGE_CANDIDATES):
    """The last resort for one room: a 1-cell passage out of the parent and
    the child on its far end, best first. [(key, [passage, child], [seam,
    seam])]."""
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
                                       passage, pool, limit=1):
                    bbox = _bbox(placed + [passage, hit[1]])
                    covered = sum(q.rect.w * q.rect.h
                                  for q in placed + [passage]) \
                        + hit[1].rect.w * hit[1].rect.h
                    out.append(((bbox.w * bbox.h, bbox.w * bbox.h - covered),
                                [passage, hit[1]], [seam, hit[2]]))
    out.sort(key=lambda c: c[0])
    return out[:limit]


# ------------------------------------------------------------------ assembling

def _assemble(ctx, design):
    rng = random.Random(f"{ctx.world_seed}|assembler|{design.name}")
    ctx.sleepers = library_plan._sleepers(
        ctx.lib, [{"name": r.name, "use": r.use} for r in design.rooms],
        design.residents, design.couples)
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
            if _side_offsets(o, design.entrance_side):
                turns.append(o)
        if len(turns) >= 12:
            break
    if not turns:
        raise _Fallback(f"no {root} room with a door on its "
                        f"{design.entrance_side} wall")
    for e0 in turns[:12]:
        try:
            return _place_rooms(ctx, design, pools, children, root, e0,
                                tier, cond)
        except _Fallback as e:
            failures.append(str(e))
    raise _Fallback(failures[0] if failures else "no assembly")


def _place_rooms(ctx, design, pools, children, root, entry_room, tier, cond):
    """Place every room of the tree from a given entrance-room orientation,
    close the outline, and furnish: the finished _Assembly.

    Placement is a bounded best-first search: partial placements queue by
    their hole cells and footprint, each room takes its few best candidates
    against its parent (a 1-cell corridor only when none fits), the complete
    placements that surface first are the tightest ones, and the outline
    closes on them until one closes clean — a greedy placement would happily
    paint a later room into a corner, or leave a strip nothing can fill."""
    side = design.entrance_side
    entry = _Placed(root, entry_room,
                    Rect(0, 0, entry_room["size"][0] + 2, entry_room["size"][1] + 2))

    def holes_of(placed):
        bbox = _bbox(placed)
        covered = sum(p.rect.w * p.rect.h for p in placed)
        return bbox.w * bbox.h - covered, bbox.w * bbox.h

    def leaf_key(placed):
        holes, area = holes_of(placed)
        touching = sum(_contact(placed[:i], p, _bbox(placed[:i + 1]))
                       for i, p in enumerate(placed) if i)
        return (holes, area, -touching)

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
        cands = _candidates(placed, entry, side, parent, pools[name])
        expanded += 1
        for (_ck, child, seam) in cands:
            push(placed + [child], pairs + [seam], names + [name], rest)
        if cands:
            continue    # the corridor is the last resort, not a sibling branch
        for (_pk, rooms, seams) in _passage_candidates(placed, entry, side,
                                                       parent, pools[name]):
            push(placed + rooms, pairs + seams, names + [None, name], rest)
    if not leaves:
        first = children[root][0] if children[root] else "?"
        raise _Fallback(f"room {first}: no placement against {root}")
    leaves.sort(key=lambda l: l[0])
    reasons = []
    for (_key, placed, pairs, names) in leaves[:LEAF_TRIES]:
        try:
            return _finish_assembly(ctx, design, side, placed, pairs, names,
                                    tier, cond, pools)
        except _Fallback as e:
            reasons.append(str(e))
    raise _Fallback(reasons[0] if reasons else "no placement closed cleanly")


def _finish_assembly(ctx, design, side, placed, pairs, names, tier, cond,
                     pools=None):
    """Close one complete placement to a rectangle, open its doors and
    furnish it: the finished _Assembly. Works on copies of the placed rooms:
    a leaf that fails after stretching must not bend the ones after it."""
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
    # from the coordinates
    box = _bbox(placed)
    if box.x or box.y:
        dx, dy = -box.x, -box.y
        for p in placed:
            p.rect = Rect(p.rect.x + dx, p.rect.y + dy, p.rect.w, p.rect.h)
        asm.pairs = [[(cx + dx, cy + dy) for (cx, cy) in pair]
                     for pair in asm.pairs]

    # ---- close the outline to a rectangle: stretch lines first, then
    # filler rooms for whatever is left
    _bbox_, holes = _holes(placed)
    if holes:
        _stretch_close(placed, entry, side, holes)
        _bbox_, holes = _holes(placed)
    if holes and pools:
        _variant_close(placed, entry, side, holes, pools, tier)
        _bbox_, holes = _holes(placed)
    if holes:
        _fill_holes(ctx, asm, placed, holes)
        _bbox_, holes = _holes(placed)
    if holes:
        raise _Fallback(f"{len(holes)} hole cell(s) left that no stretch or "
                        f"filler closes")

    # ---- the door cells every seam opened, and the entrance itself
    for pair in asm.pairs:
        for cell in pair:
            owner = next((p for p in placed if _owns_ring(p, cell)), None)
            if owner is not None:
                owner.doors.add(cell)
    for p in placed:
        if not p.doors and p is not entry:
            raise _Fallback(f"room {p.name} ended up with no door")
    offsets = _side_offsets(entry.room, side)
    if not offsets:
        raise _Fallback(f"the entrance room's {side} wall has no free cell")
    if side in ("north", "south"):
        mid = (_bbox_.w - 1) // 2
    else:
        mid = (_bbox_.h - 1) // 2
    k = min(offsets, key=lambda k: abs(k - mid))
    asm.entrance = _ring_cell(entry.rect, side, k)
    entry.doors.add(asm.entrance)

    asm.layouts, asm.lines = _furnish_assembly(ctx, design, asm, tier, cond)
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
    """The wall cell of door offset ``k`` on one side of a placed room."""
    if side == "north":
        return (rect.x + 1 + k, rect.y)
    if side == "south":
        return (rect.x + 1 + k, rect.y1)
    if side == "west":
        return (rect.x, rect.y + 1 + k)
    return (rect.x1, rect.y + 1 + k)


def _free_name(asm, base):
    names = {p.name for p in asm.rooms} | {r.name for r in asm.design.rooms}
    name, k = base, 2
    while name in names:
        name = f"{base} {k}"
        k += 1
    return name


# ------------------------------------------------------------------ closing

def _holes(placed):
    """The bounding box and the cells of it no room covers."""
    bbox = _bbox(placed)
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
    grows, so a strip two cells deep takes two lines."""
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
                        if _crosses_entrance_line(entry.rect, side_s, rect2):
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


def _variant_close(placed, entry, side_s, holes, pools, tier):
    """Swap a room for a larger variant of its own family when a strip of
    holes one or two cells deep runs along one of its edges (design 8.1
    step 4: 'a larger variant'): the room grows into the strip, every other
    edge — and the seams opened on them — staying where they were. The
    room's own band first; a stored room one band up, same clearance, wealth
    and sleep count, when the band holds no bigger variant."""
    ctx = _context

    def bigger(p, size):
        room2 = next((o for v in pools.get(p.name, []) for o in _orientations(v)
                      if tuple(o["size"]) == size), None)
        if room2 is not None or ctx is None:
            return room2
        fam, cl = p.room.get("family"), p.room.get("clearance")
        singles, couples = ctx.sleepers.get(p.name, (0, 0))
        for r in FR.active(ctx.rooms):
            if (r.get("family") == fam and r.get("clearance") == cl
                    and tier in (r.get("wealth") or [])
                    and _sleeps_ok(r, singles, couples)
                    and tuple(r["size"]) == size):
                return r
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
                if _crosses_entrance_line(entry.rect, side_s, rect2):
                    continue
                p.room, p.rect = room2, rect2
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


def _fill_holes(ctx, asm, placed, holes):
    """Fill what is left of the outline: a composed storage room when one
    fits the hole's floor exactly, else an empty store, closet or passage;
    each takes a door pair with whatever it touches."""
    for hole in _hole_rects(holes):
        if hole.w < MIN_SPAN or hole.h < MIN_SPAN:
            continue
        iw, ih = hole.w - 2, hole.h - 2
        filler = None
        if iw >= FURNISHED_FILLER - 2 and ih >= FURNISHED_FILLER - 2:
            filler = _compose_filler(ctx, asm.design.name, iw, ih)
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


def _compose_filler(ctx, building, iw, ih):
    """A storage room composed to exactly fit a hole's floor, or None."""
    area = iw * ih
    band = None
    for name, span in sorted((ctx.lib.vocab.get("sizeBands") or {}).items()):
        if not str(name).startswith("_") and isinstance(span, list) \
                and span[0] <= area <= span[1]:
            band = name
    if band is None:
        return None
    recipes = [r for r in sorted(ctx.groups["recipes"].values(),
                                 key=lambda r: str(r.get("layout") or ""))
               if r.get("family") == "storage"]
    if not recipes:
        return None
    for recipe in recipes:
        rooms, _why = RC.compose(recipe, ctx.groups, "tight", "flush",
                                 f"{ctx.world_seed}|assembler|{building}|filler",
                                 size_band=band)
        for room in rooms:
            if room["size"] == [iw, ih]:
                return room
    return None


def _filler_seam(placed, block):
    """A door pair between a filler and whatever it touches, nearest the
    middle of the shared span."""
    best = None
    for p in placed:
        if p is block:
            continue
        for side in ("north", "south", "east", "west"):
            facing = OPPOSITE[side]
            if not _side_offsets(p.room, side) \
                    or not _side_offsets(block.room, facing):
                continue
            for op in _side_offsets(p.room, side):
                for oc in _side_offsets(block.room, facing):
                    if side == "south" and p.rect.y1 + 1 == block.rect.y:
                        cell = (p.rect.x + 1 + op, p.rect.y1)
                        far = (block.rect.x + 1 + oc, block.rect.y)
                    elif side == "north" and p.rect.y == block.rect.y1 + 1:
                        cell = (p.rect.x + 1 + op, p.rect.y)
                        far = (block.rect.x + 1 + oc, block.rect.y1)
                    elif side == "east" and p.rect.x1 + 1 == block.rect.x:
                        cell = (p.rect.x1, p.rect.y + 1 + op)
                        far = (block.rect.x, block.rect.y + 1 + oc)
                    elif side == "west" and p.rect.x == block.rect.x1 + 1:
                        cell = (p.rect.x, p.rect.y + 1 + op)
                        far = (block.rect.x1, block.rect.y + 1 + oc)
                    else:
                        continue
                    if not _span_ok(p.rect, block.rect, cell, side):
                        continue
                    cx = (min(p.rect.x, block.rect.x)
                          + max(p.rect.x1, block.rect.x1)) // 2
                    cy = (min(p.rect.y, block.rect.y)
                          + max(p.rect.y1, block.rect.y1)) // 2
                    key = (abs(cell[0] - cx) + abs(cell[1] - cy), op, oc)
                    if best is None or key < best[0]:
                        best = (key, [cell, far])
    return None if best is None else best[1]


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

    # an object facing the piece's way first, at every tier; only then one
    # that just covers its cells
    for fits, rot in ((exact, rot_for), (covers, covers_rot)):
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
    to ``origin`` (its bottom-left cell)."""
    ox, oy = origin
    w = max(p.rect.x1 for p in asm.rooms) + 1
    h = max(p.rect.y1 for p in asm.rooms) + 1
    design = dataclasses.replace(asm.design, furniture=list(asm.lines))
    b = BuildingLayout(design, Rect(ox, oy, w, h))
    b.assembled = True
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
