"""Data model for the merged P1-P5 plan (see DESIGN.md) and shared geometry helpers.

The plan is the one JSON object produced by merging every phase's parsed output:
P1 zones/roads, P2 templates, P3 building designs, P4 zone dressing (attached to
each zone), P5 people. Field names follow the DESIGN.md contracts exactly; the
only merging choices are that P4 dressing lives under ``zones[i].dressing`` and
P3 designs live in a top-level ``buildings`` list keyed by building name.
"""
import copy
import dataclasses
import re
from dataclasses import dataclass, field


# ------------------------------------------------------------------ geometry

@dataclass(frozen=True)
class Rect:
    """A grid rectangle. [0,0] is bottom-left, y grows north; (x, y) is the
    bottom-left cell and x1/y1 the inclusive top-right cell."""

    x: int
    y: int
    w: int
    h: int

    @property
    def x1(self):
        return self.x + self.w - 1

    @property
    def y1(self):
        return self.y + self.h - 1

    def contains_rect(self, other):
        return (self.x <= other.x and self.y <= other.y
                and other.x1 <= self.x1 and other.y1 <= self.y1)

    def contains_cell(self, c):
        x, y = c
        return self.x <= x <= self.x1 and self.y <= y <= self.y1

    def cells(self):
        return {(x, y) for x in range(self.x, self.x1 + 1) for y in range(self.y, self.y1 + 1)}

    def interior(self, n=1):
        return Rect(self.x + n, self.y + n, max(1, self.w - 2 * n), max(1, self.h - 2 * n))

    def intersects(self, other):
        """True only on real area overlap; rects that merely touch an edge do not intersect."""
        return not (self.x1 < other.x or other.x1 < self.x
                    or self.y1 < other.y or other.y1 < self.y)

    def gap(self, other):
        """Cell distance between the rects: 0 when touching, negative when overlapping."""
        dx = max(other.x - self.x1, self.x - other.x1, 0)
        dy = max(other.y - self.y1, self.y - other.y1, 0)
        if dx == 0 and dy == 0:
            return -min(self._overlap_len(self.x, self.x1, other.x, other.x1),
                        self._overlap_len(self.y, self.y1, other.y, other.y1))
        return max(dx, dy)

    @staticmethod
    def _overlap_len(a0, a1, b0, b1):
        return min(a1, b1) - max(a0, b0) + 1

    def shifted(self, dx, dy):
        return Rect(self.x + dx, self.y + dy, self.w, self.h)

    def center(self):
        return (self.x + (self.w - 1) / 2.0, self.y + (self.h - 1) / 2.0)

    def as_tuple(self):
        return (self.x, self.y, self.w, self.h)


def door_inner_cell(rect, cell):
    """The interior cell just inside a door cell on the rect's ring."""
    x, y = cell
    if x == rect.x:
        return (x + 1, y)
    if x == rect.x1:
        return (x - 1, y)
    if y == rect.y:
        return (x, y + 1)
    if y == rect.y1:
        return (x, y - 1)
    return (x, y)


SIDE_DX_DY = {  # outward step of each side
    "north": (0, 1),
    "south": (0, -1),
    "east": (1, 0),
    "west": (-1, 0),
}

OPPOSITE_SIDE = {"north": "south", "south": "north", "east": "west", "west": "east"}


def shared_wall_cells(a, b):
    """Door cell(s) between two touching walled rects, mirroring the builder's
    own rule: adjacent rooms (edges one cell apart) get a facing pair of cells,
    rooms sharing one wall line get a single cell. [] when they do not touch."""
    at = a.as_tuple()
    bt = b.as_tuple()
    ax0, ay0, ax1, ay1 = at[0], at[1], at[0] + at[2] - 1, at[1] + at[3] - 1
    bx0, by0, bx1, by1 = bt[0], bt[1], bt[0] + bt[2] - 1, bt[1] + bt[3] - 1
    for (ea, eb, horiz) in ((ay1, by0, True), (by1, ay0, True), (ax1, bx0, False), (bx1, ax0, False)):
        if eb - ea in (0, 1):
            if horiz:
                lo, hi = max(ax0, bx0) + 1, min(ax1, bx1) - 1
                if hi >= lo:
                    xm = (lo + hi) // 2
                    return [(xm, ea), (xm, eb)] if eb != ea else [(xm, ea)]
            else:
                lo, hi = max(ay0, by0) + 1, min(ay1, by1) - 1
                if hi >= lo:
                    ym = (lo + hi) // 2
                    return [(ea, ym), (eb, ym)] if eb != ea else [(ea, ym)]
    return []


# ------------------------------------------------------------------ plan

VALID_SHARES = ("small", "medium", "large")
VALID_SIZE_CLASSES = ("hut", "small", "medium", "large", "hall")
VALID_ZONE_SIZES = ("small", "medium", "large", "huge")

# the guide's item vocabulary (section 6.1)
ITEM_TYPES = ("wieldable", "head", "face", "necklace", "innerTorso", "torso",
              "gloves", "pants", "boots", "ring", "consumable", "misc", "material")
ITEM_QUALITIES = ("common", "uncommon", "rare", "epic", "legendary")
LOOT_SETTINGS = ("none", "sparse", "normal", "rich")


@dataclass
class ItemTemplate:
    """One findable thing (guide section 6.1): type, quality and value come
    from the game's lists; physicalDescription ends with 'white background'."""
    name: str
    type: str = "misc"
    quality: str = "common"
    value: float = 1
    description: str = ""
    physicalDescription: str = ""


@dataclass
class LootPool:
    """A named list of item names a container draws from, with optional
    per-item weights on top of the quality weighting."""
    name: str
    items: list = field(default_factory=list)
    weights: dict = field(default_factory=dict)


@dataclass
class RoomSpec:
    name: str
    share: str = "small"
    purpose: str = ""
    loot_pool: str = ""      # every container in this room draws here


@dataclass
class FurniturePlan:
    template: str
    room: str
    count: int = 1
    hint: str = ""
    loot_pool: str = ""      # this line's copies draw here (most specific)


@dataclass
class UnitSpec:
    """Repeating units inside one building (P1 field, P3 "unit" design):
    the unit is designed once and stamped by code, so the model never plans
    Apartment 1 to 12 one by one."""
    name: str = "Apartment"
    count: int = 1              # total units across the building's storeys
    per_storey: int = 0         # units per storey (0: count spread over storeys)
    residents: int = 0          # beds inside each unit
    numbering: str = "plain"    # plain ("Apartment 4") | storey ("Room 204")
    design: object = None       # BuildingDesign of one unit (P3 "unit")


@dataclass
class BuildingDesign:
    """P3 output for one building, plus the P1 entry it refines."""
    name: str
    kind: str = "house"
    size_class: str = "small"
    purpose: str = ""
    wall: str = "wood"
    ground: str = "wood"
    storeys: int = 1                                   # 1-3 (floors extension)
    stairs_room: str = ""                              # ground room the stair rises from
    units: object = None                               # UnitSpec when it repeats units
    upper: list = field(default_factory=list)          # [UpperStorey]
    rooms: list = field(default_factory=list)          # [RoomSpec]
    connections: list = field(default_factory=list)    # [[roomA, roomB]]
    entrance_room: str = ""
    entrance_side: str = "south"
    furniture: list = field(default_factory=list)      # [FurniturePlan]
    yard: object = None                                # YardSpec or None
    yard_props: list = field(default_factory=list)     # [PropPlan]
    loot_pool: str = ""                                # the whole building's pool


@dataclass
class OpeningSpec:
    """A hole in an upper floor you can look down through."""
    over_room: str = ""      # ground room name the opening sits above
    kind: str = "gallery"    # gallery|atrium|stairwell


@dataclass
class UpperStorey:
    """One extra storey of a multi-storey building (floors extension)."""
    storey: int = 2
    rooms: list = field(default_factory=list)          # [RoomSpec]
    connections: list = field(default_factory=list)    # [[roomA, roomB]]
    furniture: list = field(default_factory=list)      # [FurniturePlan]
    opening: object = None                              # OpeningSpec or None


@dataclass
class YardSpec:
    kind: str = "yard"
    side: str = "back"   # front|back|left|right


@dataclass
class PropPlan:
    template: str
    count: int = 1
    hint: str = ""


@dataclass
class FillerPlan:
    template: str
    density: str = "low"   # low|medium|high


@dataclass
class Dressing:
    paths: str = "dirt"   # none|dirt|cobble|paved
    props: list = field(default_factory=list)   # [PropPlan]
    filler: list = field(default_factory=list)  # [FillerPlan]


@dataclass
class Zone:
    name: str
    kind: str = "field"
    size_class: str = "medium"
    description: str = ""
    ground: str = "grass"
    adjacentTo: list = field(default_factory=list)
    buildings: list = field(default_factory=list)  # [BuildingDesign]
    outdoor: list = field(default_factory=list)    # short feature names from P1
    dressing: Dressing = field(default_factory=Dressing)
    arrangement: str = ""   # optional: around_green|along_street|scattered|fields
    compounds: list = field(default_factory=list)  # [Compound] placed in this zone
    exterior: str = ""      # optional: "void" = no walkable open ground


# ------------------------------------------------------------------ compounds

VALID_ARRANGEMENTS = ("around_green", "along_street", "scattered", "fields")
COMPOUND_SHAPES = {"enclosure", "row", "spine", "cluster"}
COMPOUND_WALLS = ("walkable", "solid", "none")
COURTYARD_SIZES = ("small", "medium", "large")
CORNERS = ("nw", "ne", "sw", "se")
SIDE_WORDS = ("north", "south", "east", "west")
ROW_FRONTS = ("street", "parking", "walkway", "none")
SPINE_AXES = ("ns", "ew")
HUB_POSITIONS = ("center", "start", "end")


@dataclass
class CompoundPart:
    """One part of a compound: a building from the zone's own buildings list,
    placed by its slot. ``at`` is the model's slot string; the kind and the
    pieces are parsed and validated with the plan."""
    building: str
    at: str = ""
    gate: bool = False
    linked: bool = False      # row: butt against the previous part (a door joins them)
    same_as: str = ""         # copy another part building's P3 design
    slot_kind: str = ""   # corner | edge | inside | attached | row | spine | spine_end | hub
    corner: str = ""      # nw|ne|sw|se (corner)
    side: str = ""        # north|south|east|west (edge, inside, attached);
                          # left|right (spine); start|end (spine_end)
    offset: str = ""      # start|center|end (edge)
    host: str = ""        # host part building (attached)
    index: int = -1       # slot order (row, spine left/right)


@dataclass
class Compound:
    """Several connected structures placed as one block: the parts are
    existing buildings of one zone; code adds the walls between them."""
    name: str
    zone: str
    shape: str = "enclosure"
    courtyard: str = "medium"
    walls: str = "walkable"
    parts: list = field(default_factory=list)   # [CompoundPart]
    frontage: str = "south"   # row: the side the entrances face
    front: str = "none"       # row: street|parking|walkway|none strip in front
    axis: str = "ns"          # spine: ns|ew
    spine_width: int = 3      # spine: 3-5 (cluster: 0, no corridor at all)
    hub_pos: str = "center"   # spine: where the hub part sits


@dataclass
class Road:
    a: str   # zone name
    b: str   # zone name
    kind: str = "dirt"


SLEEP_WORDS = ("bed", "bunk", "cot", "pallet", "hammock")

# ------------------------------------------------------------------ zone kinds

SETTLEMENT_WORDS = ("village", "town", "city", "district", "quarter", "street",
                    "market", "hamlet", "square", "borough", "ward", "precinct",
                    "suburb", "downtown", "sprawl", "centre", "center", "row",
                    "block", "strip", "commercial", "residential", "industrial",
                    "neighbourhood", "neighborhood", "enclave")
AGRICULTURAL_WORDS = ("farmland", "farm", "field", "fields", "orchard", "meadow",
                      "pasture", "pastureland", "cropland", "plantation",
                      "vineyard", "grange", "acreage", "arable", "homestead",
                      "ranch", "smallholding")
WATER_WORDS = ("river", "lake", "sea", "ocean", "pond", "pool", "creek", "brook",
               "stream", "bay", "cove", "coast", "shore", "beach", "water",
               "waterfront", "harbor", "harbour", "lagoon", "estuary", "delta")
WILD_WORDS = ("forest", "wood", "woods", "woodland", "marsh", "swamp", "moor",
              "heath", "fen", "bog", "jungle", "thicket", "grove", "copse",
              "park", "wilderness", "wilds", "scrub", "barrens", "steppe",
              "tundra", "savanna", "green")
URBAN_WORDS = ("city", "district", "quarter", "street", "market", "borough",
               "ward", "precinct", "downtown", "sprawl", "row", "block",
               "strip", "commercial", "residential", "industrial",
               "neighbourhood", "neighborhood", "metropolitan")


def _kind_words(kind):
    return set(re.findall(r"[a-z]+", (kind or "").lower()))


def zone_class(zone):
    """The zone's map class from its kind: settlement, agricultural, wild
    (the default open country) or water."""
    words = _kind_words(zone.kind)
    if words & set(SETTLEMENT_WORDS):
        return "settlement"
    if words & set(AGRICULTURAL_WORDS):
        return "agricultural"
    if words & set(WATER_WORDS):
        return "water"
    return "wild"


def is_urban_zone(zone):
    """A settlement that reads as a town/city district (alleys, tight blocks)
    rather than a village or hamlet (wide lanes, yards)."""
    return zone_class(zone) == "settlement" and bool(_kind_words(zone.kind) & set(URBAN_WORDS))


GREEN_LIKE_WORDS = ("green", "common")


def green_feature_name(zone):
    """The around_green centre's region name: the zone's own outdoor feature
    when one is named like a green or common, else "<Zone> Green"."""
    for feature in getattr(zone, "outdoor", None) or []:
        words = set(re.findall(r"[a-z]+", str(feature).lower()))
        if words & set(GREEN_LIKE_WORDS):
            return " ".join(w.capitalize() for w in str(feature).split())
    return f"{zone.name} Green"


TOWN_WORDS = ("town", "borough", "suburb", "burg")


def is_town_zone(zone):
    """A settlement between the two: a town, not yet a city district."""
    return zone_class(zone) == "settlement" and bool(_kind_words(zone.kind) & set(TOWN_WORDS))


def building_coverage_target(zone, setting=None):
    """The share of a settlement zone's cells its buildings should cover:
    packed blocks for a dense setting or city-like kinds, loose ground for
    villages, towns in between."""
    if (setting or {}).get("density") == "dense" or is_urban_zone(zone):
        return 0.52
    if is_town_zone(zone):
        return 0.30
    return 0.16


def is_sleep_name(name, tags=()):
    """True for names/tags of things a person sleeps on: beds, cots, bunks,
    pallets, hammocks (a "Straw Bed" needs no bed tag to count)."""
    n = (name or "").lower()
    if any(w in n for w in SLEEP_WORDS):
        return True
    return any(w in (t or "").lower() for t in tags or () for w in SLEEP_WORDS)


def bed_capacity(template):
    """How many sleepers one sleep object holds: at least 2 cells in both
    directions sleeps 2 (a double bed), anything narrower sleeps 1 — a 2x1
    single bed turned on its side included."""
    w, h = template.size
    return 2 if min(w, h) >= 2 else 1


@dataclass
class ObjectTemplate:
    name: str
    size: tuple = (1, 1)
    walkability: float = 0.0
    description: str = ""
    physicalDescription: str = ""
    tags: list = field(default_factory=list)
    rule: str = ""
    extras: dict = field(default_factory=dict)  # forSleep, craftStation, light, ...

    @property
    def for_sleep(self):
        v = self.extras.get("forSleep")
        if v is not None:
            return bool(v)
        return is_sleep_name(self.name, self.tags)


@dataclass
class Person:
    name: str
    gender: str = "female"
    role: str = "villager"
    home: str = ""
    work: str = ""
    description: str = ""
    physicalDescription: str = ""
    extras: dict = field(default_factory=dict)


@dataclass
class Plan:
    name: str = "Generated World"
    worldBackground: str = ""
    setting: dict = field(default_factory=dict)
    mapSize: str = "small"
    zones: list = field(default_factory=list)      # [Zone]
    roads: list = field(default_factory=list)      # [Road]
    templates: list = field(default_factory=list)  # [ObjectTemplate]
    items: list = field(default_factory=list)      # [ItemTemplate]
    loot_pools: dict = field(default_factory=dict) # {name: LootPool}
    npcs: list = field(default_factory=list)       # [Person]
    player: Person = None
    compounds: list = field(default_factory=list)  # [Compound]
    extras: dict = field(default_factory=dict)     # currency, attributes, skills, ...

    def template(self, name):
        for t in self.templates:
            if t.name == name:
                return t
        raise KeyError(f"unknown object template {name!r}")


# ------------------------------------------------------------------ parsing

def _require(d, key, ctx):
    if key not in d:
        raise ValueError(f"{ctx}: missing required field {key!r}")
    return d[key]


def _parse_roomspec(d):
    return RoomSpec(name=_require(d, "name", "room"),
                    share=d.get("share", "small"),
                    purpose=d.get("purpose", ""),
                    loot_pool=d.get("lootPool", "") or "")


def _parse_storeys(d, top=3):
    """The P1 storey count, clamped to 1..top (junk counts as one storey).
    ``top`` is 6 for unit buildings and compound parts, 3 otherwise."""
    try:
        s = int(d.get("storeys", 1) or 1)
    except (TypeError, ValueError):
        return 1
    return max(1, min(top, s))


def _parse_units(d, g, name):
    """UnitSpec from the P1 "units" field, with the P3 "unit" design that
    furnishes one copy. Raises ValueError on a bad field."""
    u = d.get("units")
    if not u:
        return None
    if not isinstance(u, dict):
        raise ValueError(f"building {name!r}: units must be an object")
    count = int(u.get("count", 1) or 1)
    per_storey = int(u.get("perStorey", 0) or 0)
    residents = int(u.get("residents", 0) or 0)
    numbering = u.get("numbering", "plain")
    if count < 1:
        raise ValueError(f"building {name!r}: units.count must be at least 1")
    if per_storey < 0 or per_storey > count:
        raise ValueError(f"building {name!r}: units.perStorey must be 0 "
                         f"(spread) or 1..count")
    if residents < 0 or residents > 8:
        raise ValueError(f"building {name!r}: units.residents must be 0..8")
    if numbering not in ("plain", "storey"):
        raise ValueError(f"building {name!r}: bad units.numbering {numbering!r} "
                         f"(use plain or storey)")
    ud = g.get("unit")
    if isinstance(ud, dict):
        rooms = [_parse_roomspec(r) for r in ud.get("rooms", []) if isinstance(r, dict)]
        if not rooms:
            rooms = [RoomSpec(name="Room", share="medium")]
        design = BuildingDesign(
            name=u.get("name", "Apartment"), kind="unit",
            rooms=rooms,
            connections=[list(c) for c in ud.get("connections", [])],
            entrance_room=ud.get("entrance", {}).get("room", rooms[0].name),
            entrance_side=ud.get("entrance", {}).get("side", "south"),
            furniture=[FurniturePlan(template=f.get("template"), room=f.get("room", ""),
                                     count=int(f.get("count", 1)), hint=f.get("hint", ""),
                                     loot_pool=f.get("lootPool", "") or "")
                       for f in ud.get("furniture", []) if isinstance(f, dict)],
            loot_pool=ud.get("lootPool", "") or "")
    else:
        design = BuildingDesign(name=u.get("name", "Apartment"), kind="unit",
                                rooms=[RoomSpec(name="Room", share="medium")])
    return UnitSpec(name=u.get("name", "Apartment"), count=count,
                    per_storey=per_storey, residents=residents,
                    numbering=numbering, design=design)


def _parse_upper(specs, storeys, ground_rooms):
    """[UpperStorey] from a design's "upper" entries, in storey order, keeping
    only storeys 2..storeys."""
    out = []
    for u in specs:
        if not isinstance(u, dict):
            continue
        try:
            s = int(u.get("storey", 2))
        except (TypeError, ValueError):
            continue
        if not 2 <= s <= storeys:
            continue
        op = u.get("opening")
        if isinstance(op, dict) and op.get("over_room") in ground_rooms:
            opening = OpeningSpec(over_room=op["over_room"],
                                  kind=op.get("kind", "gallery"))
        else:
            opening = None
        out.append(UpperStorey(
            storey=s,
            rooms=[_parse_roomspec(r) for r in u.get("rooms", []) if isinstance(r, dict)],
            connections=[list(c) for c in u.get("connections", [])],
            furniture=[FurniturePlan(template=f.get("template"), room=f.get("room", ""),
                                     count=int(f.get("count", 1)), hint=f.get("hint", ""),
                                     loot_pool=f.get("lootPool", "") or "")
                       for f in u.get("furniture", [])],
            opening=opening))
    out.sort(key=lambda u: u.storey)
    return out


def _parse_building(d, designs):
    name = _require(d, "name", "building")
    yard = None
    if d.get("yard"):
        yard = YardSpec(kind=d["yard"].get("kind", "yard"), side=d["yard"].get("side", "back"))
    g = designs.get(name)
    if g is None:
        # a P1 building with no P3 design: one room, no connections
        g = {"rooms": [{"name": "Hall", "share": "medium", "purpose": d.get("purpose", "")}],
             "connections": [], "entrance": {"room": "Hall", "side": "south"},
             "furniture": [], "yard_props": []}
    rooms = [_parse_roomspec(r) for r in g.get("rooms", [])]
    units = _parse_units(d, g, name)
    # parsed to 6 and clamped after the compounds are known: a unit building
    # or a compound part may rise to 6, everything else to 3
    storeys = _parse_storeys(d, 6)
    upper = _parse_upper(g.get("upper", []), storeys,
                         {r.name for r in rooms}) if storeys > 1 else []
    stairs_room = ""
    if storeys > 1:
        st = g.get("stairs")
        if isinstance(st, dict) and st.get("room") in {r.name for r in rooms}:
            stairs_room = st["room"]
        elif units:
            stairs_room = "Corridor"   # the spine the stairs rise from
    design = BuildingDesign(
        name=name, kind=d.get("kind", "house"), size_class=d.get("sizeClass", "small"),
        purpose=d.get("purpose", ""), wall=g.get("wall", "wood"), ground=g.get("ground", "wood"),
        storeys=max(1 + len(upper), storeys) if units else 1 + len(upper),
        stairs_room=stairs_room if upper else "",
        upper=upper,
        units=units,
        rooms=rooms,
        connections=[list(c) for c in g.get("connections", [])],
        entrance_room=g.get("entrance", {}).get("room", rooms[0].name if rooms else "Hall"),
        entrance_side=g.get("entrance", {}).get("side", "south"),
        furniture=[FurniturePlan(template=f.get("template"), room=f.get("room", ""),
                                 count=int(f.get("count", 1)), hint=f.get("hint", ""),
                                 loot_pool=f.get("lootPool", "") or "")
                   for f in g.get("furniture", [])],
        yard=yard,
        yard_props=[PropPlan(template=p.get("template"), count=int(p.get("count", 1)),
                             hint=p.get("hint", "")) for p in (g.get("yard") or {}).get("props", [])],
        loot_pool=(g.get("lootPool") or d.get("lootPool") or ""),
    )
    if design.size_class not in VALID_SIZE_CLASSES:
        raise ValueError(f"building {name!r}: bad sizeClass {design.size_class!r}")
    return design


def _parse_slot(at, ctx):
    """Parse one slot string into its kind and pieces. Raises ValueError
    naming ``ctx`` (the compound and part) on anything outside the
    vocabulary. An empty ``at`` is a row part in plan order."""
    if at == "":
        return ("row", {"index": -1})
    if not isinstance(at, str) or ":" not in at:
        raise ValueError(f"{ctx}: bad slot {at!r} (use corner:<nw|ne|sw|se>, "
                         f"edge:<north|south|east|west>:<start|center|end>, inside:<center|north|south|east|west>, "
                         f"attached:<part>:<north|south|east|west>, row:<index>, "
                         f"spine:<left|right>:<index>, spine:end:<start|end> "
                         f"or spine:hub)")
    bits = at.split(":")
    kind = bits[0]
    if kind == "corner" and len(bits) == 2 and bits[1] in CORNERS:
        return ("corner", {"corner": bits[1]})
    if kind == "edge" and len(bits) == 3 and bits[1] in SIDE_WORDS \
            and bits[2] in ("start", "center", "end"):
        return ("edge", {"side": bits[1], "offset": bits[2]})
    if kind == "inside" and len(bits) == 2 \
            and bits[1] in (("center",) + SIDE_WORDS):
        return ("inside", {"side": "" if bits[1] == "center" else bits[1]})
    if kind == "attached" and len(bits) == 3 and bits[2] in SIDE_WORDS:
        return ("attached", {"host": bits[1], "side": bits[2]})
    if kind == "row" and len(bits) == 2 and bits[1].isdigit():
        return ("row", {"index": int(bits[1])})
    if kind == "spine" and len(bits) == 2 and bits[1] == "hub":
        return ("hub", {})
    if kind == "spine" and len(bits) == 3 and bits[1] == "end" \
            and bits[2] in ("start", "end"):
        return ("spine_end", {"side": bits[2]})
    if kind == "spine" and len(bits) == 3 and bits[1] in ("left", "right") \
            and bits[2].isdigit():
        return ("spine", {"side": bits[1], "index": int(bits[2])})
    raise ValueError(f"{ctx}: bad slot {at!r}")


ENCLOSURE_SLOTS = ("corner", "edge", "inside", "attached")
LINE_SLOTS = ("row", "attached", "spine", "spine_end", "hub")


def _parse_compounds(data, zone_by_name, building_zone):
    """[Compound] from the plan's top-level list, validated against the
    zones: every part is a building of the compound's own zone, no slot is
    used twice, gates are edge parts only (at most two), an attached part
    names a host that exists and does not loop, and the shape's own fields
    (row frontage and front, spine axis and width, one hub at most) hold."""
    out = []
    seen_names = set()
    for c in data.get("compounds", []) or []:
        if not isinstance(c, dict):
            raise ValueError("compounds: entries must be objects")
        name = _require(c, "name", "compound")
        ctx = f"compound {name!r}"
        if name in seen_names:
            raise ValueError(f"{ctx}: name used twice")
        seen_names.add(name)
        zone = _require(c, "zone", ctx)
        if zone not in zone_by_name:
            raise ValueError(f"{ctx}: unknown zone {zone!r}")
        shape = c.get("shape", "enclosure")
        if shape not in COMPOUND_SHAPES:
            raise ValueError(f"{ctx}: bad shape {shape!r} (use enclosure, row, "
                             f"spine or cluster)")
        courtyard = c.get("courtyard", "medium")
        if courtyard not in COURTYARD_SIZES:
            raise ValueError(f"{ctx}: bad courtyard {courtyard!r} "
                             f"(use small, medium or large)")
        walls = c.get("walls", "walkable")
        if walls not in COMPOUND_WALLS:
            raise ValueError(f"{ctx}: bad walls {walls!r} "
                             f"(use walkable, solid or none)")
        frontage = c.get("frontage", "south")
        front = c.get("front", "none")
        axis = c.get("axis", "ns")
        hub_pos = c.get("hub", "center")
        spine_width = c.get("spineWidth", 3)
        if shape == "row":
            if frontage not in SIDE_WORDS:
                raise ValueError(f"{ctx}: bad frontage {frontage!r}")
            if front not in ROW_FRONTS:
                raise ValueError(f"{ctx}: bad front {front!r} "
                                 f"(use street, parking, walkway or none)")
        if shape in ("spine", "cluster"):
            if axis not in SPINE_AXES:
                raise ValueError(f"{ctx}: bad axis {axis!r} (use ns or ew)")
            if hub_pos not in HUB_POSITIONS:
                raise ValueError(f"{ctx}: bad hub {hub_pos!r} "
                                 f"(use center, start or end)")
            if shape == "cluster":
                spine_width = 0
            else:
                try:
                    spine_width = int(spine_width)
                except (TypeError, ValueError):
                    raise ValueError(f"{ctx}: bad spineWidth {spine_width!r}")
                if not 3 <= spine_width <= 5:
                    raise ValueError(f"{ctx}: spineWidth must be 3-5 "
                                     f"(cluster is spineWidth 0)")
        parts = c.get("parts", []) or []
        if not isinstance(parts, list) or not parts:
            raise ValueError(f"{ctx}: parts must be a non-empty list")
        allowed = ENCLOSURE_SLOTS if shape == "enclosure" else LINE_SLOTS
        parsed, slots, gates = [], set(), []
        for p in parts:
            if not isinstance(p, dict):
                raise ValueError(f"{ctx}: parts entries must be objects")
            bname = _require(p, "building", f"{ctx} part")
            pctx = f"{ctx} part {bname!r}"
            at = p.get("at", "")
            kind, fields = _parse_slot(at, pctx)
            if kind not in allowed:
                raise ValueError(f"{pctx}: slot {at!r} does not fit shape "
                                 f"{shape!r}")
            if at and at in slots:
                raise ValueError(f"{pctx}: slot {at!r} used twice in {name!r}")
            slots.add(at)
            if bname not in building_zone:
                raise ValueError(f"{pctx}: unknown building {bname!r}")
            if building_zone[bname] != zone:
                raise ValueError(f"{pctx}: building {bname!r} is a building of "
                                 f"{building_zone[bname]!r}, not {zone!r}")
            if p.get("gate"):
                if shape != "enclosure" or kind != "edge":
                    raise ValueError(f"{pctx}: only an enclosure edge part "
                                     f"can be the gate")
                gates.append(bname)
            same_as = p.get("sameAs", "")
            if same_as:
                if not isinstance(same_as, str) or not same_as:
                    raise ValueError(f"{pctx}: sameAs must name a part building")
                if same_as == bname:
                    raise ValueError(f"{pctx}: sameAs cannot name itself")
            parsed.append(CompoundPart(building=bname, at=at,
                                       gate=bool(p.get("gate")),
                                       linked=bool(p.get("linked")),
                                       same_as=same_as,
                                       slot_kind=kind, **fields))
        if len(gates) > 2:
            raise ValueError(f"{ctx}: at most two gates, got {len(gates)}")
        if shape in ("spine", "cluster") and len(gates) > 0:
            raise ValueError(f"{ctx}: a {shape} takes no gate parts")
        hubs = [p for p in parsed if p.slot_kind == "hub"]
        if len(hubs) > 1:
            raise ValueError(f"{ctx}: at most one hub part, got {len(hubs)}")
        if shape == "cluster" and not hubs:
            raise ValueError(f"{ctx}: a cluster needs a hub part at spine:hub")
        if shape == "row":
            have = [p for p in parsed if p.slot_kind == "row" and p.index >= 0]
            idxs = [p.index for p in have]
            if len(set(idxs)) != len(idxs):
                raise ValueError(f"{ctx}: row indices used twice")
            # parts with no at keep plan order after the indexed ones
            nexts = (max(idxs) + 1) if idxs else 0
            for p in parsed:
                if p.slot_kind == "row" and p.index < 0:
                    p.index = nexts
                    nexts += 1
        by_building = {p.building: p for p in parsed}
        for p in parsed:
            if p.slot_kind != "attached":
                continue
            pctx = f"{ctx} part {p.building!r}"
            if p.host not in by_building:
                raise ValueError(f"{pctx}: attached host {p.host!r} is not a "
                                 f"part of {name!r}")
            walk, seen = p.host, set()
            while walk in by_building and by_building[walk].slot_kind == "attached":
                if walk in seen:
                    raise ValueError(f"{pctx}: attached parts form a cycle "
                                     f"through {walk!r}")
                seen.add(walk)
                walk = by_building[walk].host
        for p in parsed:
            if not p.same_as:
                continue
            pctx = f"{ctx} part {p.building!r}"
            if p.same_as not in by_building:
                raise ValueError(f"{pctx}: sameAs target {p.same_as!r} is not a "
                                 f"part of {name!r}")
            if by_building[p.same_as].same_as:
                raise ValueError(f"{pctx}: sameAs target {p.same_as!r} itself "
                                 f"uses sameAs; name the design's owner")
        out.append(Compound(name=name, zone=zone, shape=shape,
                            courtyard=courtyard, walls=walls, parts=parsed,
                            frontage=frontage, front=front, axis=axis,
                            spine_width=spine_width, hub_pos=hub_pos))
    return out


def _parse_items(data):
    """([ItemTemplate], {name}) from the plan's top-level "items": types,
    qualities and positive values enforced, names unique."""
    out, names = [], set()
    for it in data.get("items", []) or []:
        if not isinstance(it, dict):
            raise ValueError("items: entries must be objects")
        name = _require(it, "name", "item")
        if name in names:
            raise ValueError(f"duplicate item name {name!r}")
        type_ = it.get("type", "misc")
        quality = it.get("quality", "common")
        value = it.get("value", 1)
        if type_ not in ITEM_TYPES:
            raise ValueError(f"item {name!r}: bad type {type_!r} "
                             f"(use one of the guide's item types)")
        if quality not in ITEM_QUALITIES:
            raise ValueError(f"item {name!r}: bad quality {quality!r}")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"item {name!r}: value must be a positive number, "
                             f"not {value!r}")
        names.add(name)
        out.append(ItemTemplate(name=name, type=type_, quality=quality,
                                value=float(value),
                                description=it.get("description", ""),
                                physicalDescription=it.get("physicalDescription", "")))
    return out, names


def _parse_loot_pools(data, item_names):
    """{name: LootPool} from "lootPools" (an object keyed by pool name or a
    list of {name, items, weights}); every pooled name must be a real item."""
    raw = data.get("lootPools") or {}
    entries = []
    if isinstance(raw, dict):
        for name, v in raw.items():
            body = v if isinstance(v, dict) else {"items": v}
            entries.append({"name": name, **body})
    elif isinstance(raw, list):
        entries = [e for e in raw if isinstance(e, dict)]
    out = {}
    for p in entries:
        name = p.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("lootPools: every pool needs a name")
        if name in out:
            raise ValueError(f"duplicate loot pool {name!r}")
        names = p.get("items", [])
        if not isinstance(names, list) or not names:
            raise ValueError(f"loot pool {name!r}: items must be a non-empty list "
                             f"of item names")
        bad = sorted({n for n in names if n not in item_names})
        if bad:
            raise ValueError(f"loot pool {name!r} names unknown item(s) {bad}")
        weights = p.get("weights") or {}
        if not isinstance(weights, dict):
            raise ValueError(f"loot pool {name!r}: weights must be an object "
                             f"item -> relative chance")
        for k, v in weights.items():
            if k not in set(names) or isinstance(v, bool) \
                    or not isinstance(v, (int, float)) or v <= 0:
                raise ValueError(f"loot pool {name!r}: bad weight {k!r}: {v!r}")
        out[name] = LootPool(name=name, items=list(names), weights=dict(weights))
    return out


def _check_pool_refs(zones, templates, pools):
    """Every lootPool reference in the merged plan names a real pool: on a
    building, a room, a furniture line (unit designs and upper storeys
    included) or an object template's default."""
    def check(ref, ctx):
        if ref and ref not in pools:
            raise ValueError(f"{ctx}: unknown loot pool {ref!r}")

    def check_design(d, where):
        check(d.loot_pool, f"building {where}")
        for r in d.rooms:
            check(r.loot_pool, f"room {r.name} in {where}")
        for f in d.furniture:
            check(f.loot_pool, f"{f.template} in {where}")

    for z in zones:
        for b in z.buildings:
            check_design(b, b.name)
            for u in b.upper:
                for r in u.rooms:
                    check(r.loot_pool, f"room {r.name} in {b.name} floor {u.storey}")
                for f in u.furniture:
                    check(f.loot_pool, f"{f.template} in {b.name} floor {u.storey}")
            if b.units is not None:
                check_design(b.units.design, f"unit of {b.name}")
    for t in templates:
        check(t.extras.get("lootPool", ""), f"template {t.name}")


def parse_plan(data):
    """Parse the merged plan dict into a Plan."""
    designs = {}
    for g in data.get("buildings", []):
        designs[g["name"]] = g
    zones = []
    for z in data.get("zones", []):
        name = _require(z, "name", "zone")
        dressing_data = z.get("dressing", {})
        dressing = Dressing(
            paths=dressing_data.get("paths", "dirt"),
            props=[PropPlan(template=p.get("template"), count=int(p.get("count", 1)),
                            hint=p.get("hint", "")) for p in dressing_data.get("props", [])],
            filler=[FillerPlan(template=f.get("template"), density=f.get("density", "low"))
                    for f in dressing_data.get("filler", [])],
        )
        arrangement = z.get("arrangement", "")
        if arrangement and arrangement not in VALID_ARRANGEMENTS:
            raise ValueError(f"zone {name!r}: bad arrangement {arrangement!r} "
                             f"(use around_green, along_street, scattered or fields)")
        exterior = z.get("exterior", "")
        if exterior not in ("", "void"):
            raise ValueError(f"zone {name!r}: bad exterior {exterior!r} "
                             f"(use void)")
        zone = Zone(
            name=name, kind=z.get("kind", "field"), size_class=z.get("sizeClass", "medium"),
            description=z.get("description", ""), ground=z.get("ground", "grass"),
            adjacentTo=list(z.get("adjacentTo", [])),
            buildings=[_parse_building(b, designs) for b in z.get("buildings", [])],
            outdoor=list(z.get("outdoor", [])),
            dressing=dressing,
            arrangement=arrangement,
            exterior=exterior,
        )
        if zone.size_class not in VALID_ZONE_SIZES:
            raise ValueError(f"zone {name!r}: bad sizeClass {zone.size_class!r}")
        zones.append(zone)
    names = {z.name for z in zones}
    for z in zones:
        for n in z.adjacentTo:
            if n not in names:
                raise ValueError(f"zone {z.name!r}: adjacentTo unknown zone {n!r}")
    zone_by_name = {z.name: z for z in zones}
    building_zone = {b.name: z.name for z in zones for b in z.buildings}
    compounds = _parse_compounds(data, zone_by_name, building_zone)
    for c in compounds:
        zone_by_name[c.zone].compounds.append(c)
    # a part of a compound may rise to 6 storeys; everything else keeps 3
    part_names = {p.building for c in compounds for p in c.parts}
    for z in zones:
        for b in z.buildings:
            if b.storeys <= 3 or b.units or b.name in part_names:
                continue
            b.upper = [u for u in b.upper if u.storey <= 3]
            b.storeys = 1 + len(b.upper)
        # sameAs copies another part's P3 design (rooms, furniture, uppers):
        # P3 furnishes the design once, the parts share it
        by_name = {b.name: b for b in z.buildings}
        for c in z.compounds:
            for p in c.parts:
                if not p.same_as or p.same_as not in by_name:
                    continue
                own, src = by_name[p.building], by_name[p.same_as]
                if own is src:
                    continue
                b = dataclasses.replace(copy.deepcopy(src), name=own.name,
                                        kind=own.kind, purpose=own.purpose,
                                        size_class=own.size_class,
                                        storeys=own.storeys, units=own.units,
                                        yard=own.yard, yard_props=own.yard_props)
                by_name[p.building] = b
                z.buildings[z.buildings.index(own)] = b
    # two buildings stamping units of the same name ("Apartment 1" in both
    # walk-ups) would give the builder duplicate regions: each building's
    # copies take its name in front ("Dogwood Walk-Up Apartment 1")
    unit_names = {}
    for z in zones:
        for b in z.buildings:
            if b.units is not None:
                unit_names.setdefault(b.units.name, []).append(b)
    for shared in unit_names.values():
        if len(shared) < 2:
            continue
        for b in shared:
            b.units = dataclasses.replace(b.units, name=f"{b.name} {b.units.name}")
    templates = []
    for t in data.get("templates", []):
        extras = {k: v for k, v in t.items()
                  if k in ("forSleep", "craftStation", "light", "lightKind", "lightColor",
                           "money", "maxHp", "heightM", "passableAtBuild", "lootPool")}
        size = t.get("size", [1, 1])
        templates.append(ObjectTemplate(
            name=_require(t, "name", "template"), size=(int(size[0]), int(size[1])),
            walkability=float(t.get("walkability", 0)),
            description=t.get("description", ""), physicalDescription=t.get("physicalDescription", ""),
            tags=list(t.get("tags", [])), rule=t.get("rule", ""), extras=extras))
    seen, dupes = set(), set()
    for t in templates:
        (dupes if t.name in seen else seen).add(t.name)
    if dupes:
        raise ValueError(f"duplicate template names: {sorted(dupes)}")

    items, item_names = _parse_items(data)
    loot_pools = _parse_loot_pools(data, item_names)
    loot_setting = data.get("loot", "normal")
    if loot_setting not in LOOT_SETTINGS:
        raise ValueError(f"loot must be one of {list(LOOT_SETTINGS)}, "
                         f"not {loot_setting!r}")
    _check_pool_refs(zones, templates, loot_pools)

    def person(d):
        return Person(name=_require(d, "name", "person"), gender=d.get("gender", "female"),
                      role=d.get("role", "villager"), home=d.get("home", ""), work=d.get("work", ""),
                      description=d.get("description", ""), physicalDescription=d.get("physicalDescription", ""),
                      extras={k: v for k, v in d.items()
                              if k in ("animationId", "level", "inventory", "equipment")})

    npcs = [person(n) for n in data.get("npcs", [])]
    player = person(data.get("player", {"name": "Player"}))
    extras = {k: v for k, v in data.items()
              if k in ("currency", "attributes", "skills", "narrativeRules", "weatherKinds",
                       "narrativeFlavor", "difficulty", "xpMultiplier", "startingCurrency",
                       "variables", "perkTrees", "calendar", "quests", "loot")}
    return Plan(name=data.get("name", "Generated World"),
                worldBackground=data.get("worldBackground", ""),
                setting=data.get("setting", {}), mapSize=data.get("mapSize", "small"),
                zones=zones, roads=[Road(a=r.get("from"), b=r.get("to"), kind=r.get("kind", "dirt"))
                                    for r in data.get("roads", [])],
                templates=templates, items=items, loot_pools=loot_pools,
                npcs=npcs, player=player, compounds=compounds,
                extras=extras)
