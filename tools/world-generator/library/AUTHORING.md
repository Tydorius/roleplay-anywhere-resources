# Writing room library files

The rules every library file follows. The design and the reasons are in
[`../ROOM_LIBRARY_DESIGN.md`](../ROOM_LIBRARY_DESIGN.md). The fixed vocabulary (bands, wealth
tiers, conditions, material classes, size bands, categories, roles, layout families, purposes and
anchors) is in [`library.json`](library.json). Use only names from it. If something you need is
missing, use the nearest name and list the gap in your report: never invent one.

All files are UTF-8 JSON, two-space indented, with no comments. A key starting with `_` (such as
`_readme`) is ignored by the loader.

## Shared rules

- **Sizes are in cells.** One cell is about 1.5 m (5 ft). A size is `[w, h]` with the piece's back
  at the top (north): a single bed is `[1, 2]`, a double `[2, 2]`, a wardrobe `[2, 1]`.
- **Bands** are `medieval`, `industrial`, `modern`, `scifi`. **Wealth** tiers are `poor`,
  `modest`, `wealthy`, `elite`. **Conditions** are `ruined`, `worn`, `kept`, `pristine`.
- **Write your own words.** Names, categories and sizes are facts and may come from the seed
  drafts in `../library-seed/`. Descriptions are always new text.
- Keep every entry useful in play: the game's GM reads descriptions, and the game draws each
  object's sprite from its `physical` text.

## Objects: `objects/<group>.json`

```json
{
  "objects": [
    {
      "id": "bed.single",
      "category": "bed",
      "size": [1, 2],
      "walkability": 0.3,
      "forSleep": true,
      "light": 0,
      "back": "north",
      "wealth": ["modest", "wealthy"],
      "bands": ["*"],
      "onlyGenres": [],
      "names": {"*": "bed", "scifi": "bunk"},
      "parts": {"frame": "wood", "cover": "fabric"},
      "partsByBand": {"scifi": {"frame": "metal", "cover": "synthetic"}},
      "tags": ["bed", "furniture"],
      "container": false,
      "lootPool": null,
      "text": {
        "description": "{A:condition} {frame} {noun} made up with {cover.color} {cover} covers.",
        "physical": "Top-down view of a single {noun}: {frame.color} {frame} frame, {cover.color} {cover} blanket, pillow at the top."
      },
      "aliases": ["cot"],
      "sources": ["rimworld-wiki"]
    }
  ]
}
```

- **`id`** is `<category>.<name>`, lower case, dots and underscores only, unique across the whole
  library.
- **`category`** from `library.json`.
- **`walkability`**: 0 for solid furniture, 0.3 for anything slept on, 1 for things you walk over
  (rugs, mats, floor markings), 0.5–0.8 for low clutter you can step past.
- **`forSleep`**: true only for things slept on. A sleep object at least `[2, 2]` sleeps two;
  anything narrower sleeps one.
- **`light`**: 0 unless it gives light. A candle about 0.2, a lamp or lantern 0.4–0.6, a
  hearth 0.8–1.0. Tag it `light`.
- **`back`**: `north` for anything with a front and a back (beds, wardrobes, desks, stoves, shelves,
  altars). `null` for pieces with no front (barrels, round tables, rugs, statues, crates).
- **`wealth`**: the tiers it suits. A shape that only the rich own (a four-poster) is `wealthy` and
  `elite`. Most plain furniture spans two or three tiers.
- **`bands`**: `["*"]` for all four bands, or a list. **`onlyGenres`** narrows further by the free
  setting genre, such as `["fantasy"]` for an alchemy bench. Usually empty.
- **`names`**: the noun per band, with `*` as the fallback. Give a band its own noun whenever the
  thing has a different name there ("hearth", "cast-iron range", "galley unit").
- **`parts`**: part name to material class (from `materialClasses`). One to three parts.
  **`partsByBand`** overrides parts per band.
- **`text.description`** is one in-world sentence. **`text.physical`** is a top-down view for the
  sprite, with the back edge at the top of the image. Tokens:
  - `{noun}`: the band's name;
  - `{<part>}`: the material picked for that part (for example "oak");
  - `{<part>.color}`: one of that material's colours;
  - `{condition}`: the condition word, empty when the condition is `kept`;
  - `{A:<token>}`: "a" or "an" plus that token, agreeing with the first word that follows once
    filled, so `{A:condition}` gives "a worn" or, when the condition is empty, agrees with the
    next word. Use it for every article before a token (`{A:noun}`, `{A:frame}`), never a fixed
    "a" or "an", because nouns and materials change by band.
- **`container`**: true for things that hold loot (chests, cupboards, shelves of goods).
  `lootPool` stays `null` (pools are written per run).
- **`sources`**: the ids from `../library-seed/sources.json` that the entry's facts came from, or
  `["claude-authored"]` for a new entry.

Shape changes are separate objects: a straw pallet, a single bed, a double and a four-poster are
four objects. Material changes are not: an oak table and a pine table are one object.

## Items: `items/<group>.json`

Carried things (game `itemTemplates`: loot, tools, food, clothing), one JSON file per group. The
groups are `food_drink`, `medicine`, `tools`, `weapons_armour`, `clothing`, `jewellery_trinkets`,
`documents_keys_money`, `light_containers`, `materials`, `tech`, `magic`.

```json
{
  "_note": "Food and drink.",
  "items": [
    {
      "id": "drink.wine_bottle",
      "category": "drink",
      "type": "consumable",
      "bands": ["*"],
      "onlyGenres": [],
      "quality": "common",
      "price": 2,
      "names": {"*": "bottle of wine"},
      "description": {"*": "A corked bottle of red wine."},
      "looks": [
        {"key": "glass", "bands": ["*"],
         "physical": "A dark green glass wine bottle with a cork stopper and a plain tan paper label"}
      ],
      "tags": ["drink", "alcohol"],
      "aliases": ["Wine bottle", "Bottle of red wine"],
      "sources": ["harvest"]
    }
  ]
}
```

- **`id`** is `<category>.<name>` (one dot), unique across all item files. **`category`** is one of
  `food`, `drink`, `medicine`, `tool`, `weapon`, `armour`, `clothing`, `jewellery`, `document`,
  `key`, `money`, `light`, `container`, `material`, `trinket`, `tech`, `magic`.
- **`type`** is the game's item type: `misc`, `consumable`, `material`, `wieldable`, `head`,
  `face`, `torso`, `innerTorso`, `pants`, `gloves`, `boots`, `necklace`, `ring`. Food, drink and
  medicine are `consumable`; weapons and hand tools are `wieldable`; worn things use their slot.
- **`bands`** and **`onlyGenres`** work like an object's. **`quality`** is `common`, `uncommon`,
  `rare`, `epic` or `legendary` (most are common). **`price`** is 1–6, relative within a band:
  1 trifle, 2 cheap, 3 ordinary, 4 dear, 5 costly, 6 treasure.
- **`names`** and **`description`** work like an object's, but there is no token filling: plain
  text per band, `*` as the fallback. Give a band its own name when the thing is called
  differently there ("ale jug" / "beer bottle" / "beer can").
- **`looks`** is what makes items different from objects: one entry per image. `key` is short
  (`glass`, `steel`, `holo`), unique within the item. Each look's `bands` is `["*"]` (every band
  the item has, so a medieval-only sword's one look is `["*"]`) or a list, and **together the looks cover exactly the item's bands, each band once** (the checker
  enforces it: a gap and an overlap are both errors).
  - A look that covers two or more bands must describe something that really looks the same in
    each of them (a loaf, an apple, a rope, a wine bottle, a gold ring). When in doubt, split.
  - **`physical`** is the image prompt, one sentence, the object alone: shape, colours,
    materials, one or two details. No background, no "icon", no camera words, no people or
    hands, no text or lettering, no scenery, and under 300 characters.
  - The gallery draws on white and cuts the background out, so white, clear or very pale objects
    lose parts. Give such things colour: "pale blue-tinted glass", "cream linen with brown
    stitching", "grey steel".
- **`tags`** are free lower-case words. **`aliases`** are the harvest names this entry stands
  for, exact spelling, so a later step can map a model's invented item to a library one.
  **`sources`** is `["harvest"]` or `["authored"]`.

One shape = one item: a dagger, a short sword and a longsword are three items. A material or
colour change is not: an oak staff and an ash staff are one item.

To check the files (and see the coverage table):

    python -m worldgen library items --coverage

To write the art-review scenarios (one per set: `shared` holds every look covering two or more
bands, `medieval`/`industrial`/`modern`/`scifi` hold their single-band looks) into the gallery
folder, then pull back the images a person kept:

    python library-seed/make_item_art_scenarios.py
    python library-seed/pull_item_art.py <set> --kept

Kept images land in `library/item-sprites/<item id>.<look key>.webp`, with the set's entries in
`library/item-sprites/index.json`.

## Materials: `materials.json`

```json
{
  "wood": {
    "medieval": {
      "poor":    [{"name": "rough pine", "colors": ["pale", "grey-brown"]}],
      "modest":  [{"name": "ash", "colors": ["honey"]}],
      "wealthy": [{"name": "oak", "colors": ["golden-brown"]}],
      "elite":   [{"name": "carved walnut", "colors": ["dark brown"]}]
    }
  }
}
```

Every material class × band × wealth tier gets one to four materials, each with one to three
colours. A material name is a short phrase that reads well before a noun ("rough pine bed").

## Conditions: `conditions.json`

```json
{
  "*":     {"ruined": "wrecked", "worn": "worn", "kept": "", "pristine": "spotless"},
  "wood":  {"ruined": "rotting", "worn": "scuffed", "kept": "", "pristine": "polished"}
}
```

One adjective per material class and condition, with `*` as the fallback. `kept` is always `""`.

## Size bands per family: `library.json` → `familySizeBands`

```json
{
  "bedroom": {
    "bands": [
      {"name": "narrow", "cells": [8, 14], "aspect": [2.5, 3.5], "maxFloorPerPiece": 2},
      {"name": "tiny",   "cells": [1, 11]},
      {"name": "small",  "cells": [12, 24]},
      {"name": "medium", "cells": [25, 48]},
      {"name": "large",  "cells": [49, 400]}
    ]
  },
  "privy": {
    "maxFloorPerPiece": 2,
    "bands": [
      {"name": "stall", "cells": [2, 4]},
      {"name": "small", "cells": [5, 8]}
    ]
  }
}
```

- A family listed here uses **only its own bands** — in layouts' and recipes' `sizeBands`, in room
  ids (`bedroom.narrow.a.tight.flush`) and in every check. Every other family shares `sizeBands`.
- A room's band is the **first entry whose cell range — and aspect range, when given — holds it**,
  so list the pickier band first: a 5×2 bedroom (10 cells, 5:2) reads `narrow`, not `tiny`.
- **`aspect`** is `[lo, hi]` (hi at most 4): the long side may read `lo`–`hi` times the short. A
  band's own window may stretch past the family's usual 2-to-1 cap — that is how a 5:2 servants'
  room stands — but only inside the band.
- **`maxFloorPerPiece`** (the family's, or a band's overriding it) caps a room's free floor cells
  per placed piece at any clearance: a privy with one toilet and 15 free cells is rejected.
- The composer **never pads a room up to a band**. A recipe that cannot reach its band at a
  clearance ships no room there and the generator prints why.
- Recipes (and luxury pool entries) must name bands **of their own family** — a bedroom recipe
  naming `stall` is an error, and so is a bedroom recipe still naming `tiny` after the family's
  table drops it.

**Closets** (`closet` family) follow the reach-in rule on top: bands `reach` (1–2 cells, a lined
cupboard) and `walkin` (3–4); doors on **one side only**; a walk-in needs a door on that side, a
reach-in needs no door cell and no free floor at all — its pieces are used from the doorway.

## Layouts: `layouts/<family>.json`

```json
{
  "layouts": [
    {
      "id": "bedroom.small.a",
      "family": "bedroom",
      "sizeBands": ["small"],
      "minInterior": [3, 4],
      "maxInterior": [5, 5],
      "slots": [
        {"id": "bed",   "role": "sleep",       "size": [1, 2], "anchor": "wall:far",  "count": "singles", "back": "wall"},
        {"id": "side",  "role": "bedside",     "size": [1, 1], "anchor": "beside:bed"},
        {"id": "store", "role": "storage.big", "size": [2, 1], "anchor": "wall:side", "back": "wall"},
        {"id": "chest", "role": "storage.small", "size": [1, 1], "anchor": "corner", "optional": true},
        {"id": "lamp",  "role": "light.small", "size": [1, 1], "anchor": "corner", "minWealth": "modest"}
      ],
      "grow": [
        {"role": "decor.floor", "size": [1, 1], "anchor": "corner"},
        {"role": "seat", "size": [1, 1], "anchor": "beside:store"}
      ]
    }
  ]
}
```

- **`id`** is `<family>.<size band>.<letter>`, unique.
- **`family`** is the file's family from `library.json`. **`sizeBands`** are the bands the layout
  serves, always from the shared `library.json` → `sizeBands` table (a family's own bands — see
  [Size bands per family](#size-bands-per-family-libraryjson--familysizebands) — belong to its
  recipes and rooms, not its layouts).
- **`minInterior`** and **`maxInterior`** are the interior `[w, h]` it works in, the wall ring
  excluded. The layout must work at `minInterior` with the door on any wall.
- **Slots:**
  - `id` unique within the layout; `beside:` and `around:` name these ids.
  - `role` from `library.json`.
  - `size` is the north-facing size of the piece the slot takes.
  - `anchor` from `library.json` → `anchors`, combined with `+` when needed.
  - `count`: a whole number, `[min, max]`, `"singles"` (one per single sleeper) or `"couples"` (one
    per couple). Only `sleep` slots use `"singles"`, only `sleep.couple` uses `"couples"`.
  - `optional: true` slots are dropped first when the room is tight.
  - `minWealth` makes a slot appear only at that tier or above.
  - `back: "wall"` turns the piece so its back is against its wall. Leave it out for pieces
    that face into the room or have no back.
- **`grow`** slots are added in order while space remains, in rooms bigger than `minInterior`.
- **Fit rules** (the checker enforces them):
  - at `minInterior`, the slots' total area, counting each `count` at its maximum and `singles` and
    `couples` as 2, is at most 40% of the interior area, so people can walk;
  - every slot fits inside `minInterior` in some orientation;
  - a `row:` slot's count times its width fits along the shorter interior side;
  - `beside:` and `around:` point at slots in the same layout.
- **Sleep:** bedroom layouts use `sleep` with `"singles"`, `bedroom.master` uses one
  `sleep.couple` with `"couples"`, dormitories use rows of `sleep` with `"singles"`. Kitchens,
  dining rooms and common rooms never have sleep slots. A `hut` has one sleeping corner.
- **Wash:** a `washroom` holds all three fixtures — toilet, bath and basin — a `privy` is the
  toilet alone (it may keep a basin, never a bath) and a `bath` room the bath (never a toilet);
  `fixed_rooms.py` checks the pairing. The privy family is also the outhouse: a latrine, a
  garderobe, a water closet — the assembler places those as outbuildings later, by era and
  wealth.
- **Variety:** 2–4 layouts per size band a family really uses (a dormitory has no tiny band, a
  washroom no large one). Make variants genuinely different: a different wall for the main
  piece, a centred versus a wall-hugging arrangement, an L versus a straight run.
- The layout is generic. The purpose binds roles to categories, so one workshop layout serves a
  forge and a fabricator bay.

## Access: `library.json` → `roleAccess`

A piece of furniture is only furniture if a person can stand somewhere to use it. Each role
carries an access rule in `library.json`'s `roleAccess` table, and the rules resolve to
**access cells** — the cells someone must be able to reach to use the piece:

- `both-long` — every long side needs its own cell (all four sides when the piece is square
  and stands free): a double bed standing free.
- `one-long` — one of the long sides is enough: single beds, child beds, sickbeds, cell beds.
- `front` — the side opposite the piece's `back`; any one side when it has no back: seats,
  chests, wardrobes, shelves, displays, bedides.
- `any` — any one side: tables and desks.
- `none` — nothing: lights, decor and optional pieces (an optional piece is never a
  constraint, whatever its role).

Every role in `roles` must carry one of the five; `library check` and `library groups` flag a
missing entry. A rule may carry a `relax` — `{"wealth": ["poor"], "clearance": ["tight"],
"to": "one-long"}` — that applies only when a room's `wealth` is exactly the relax's tiers
and its clearance one of its own (a room for poor and modest must satisfy modest). The
shipped relax is `sleep.couple` (both-long) dropping to one-long for a poor, tight room.

The rules resolve to constraints of cells, each `{"cells": [[x, y], ...], "need": n}`:

- A **mandatory** constraint is one cell with `need` 1 — that cell must stand free and
  reached. A **limited** constraint is a choice of cells with `need` 1 — one of them is
  enough.
- Each side contributes one cell: the side's **foot end**, the end away from the piece's
  `back` (a bed is entered at the foot); the side's middle cell when there is no back — of
  two middle cells the lower-left one, the western of a horizontal pair, the southern of a
  vertical. `front` uses the middle cell of the side opposite the back.
- **A bed lying lengthwise** — its `back` on one of its long sides — is used from the
  opposite long side alone, one limited constraint over that side's cells, whatever its
  rule says. A double bed lying lengthwise keeps this at every wealth.
- **A bedside locks a bed side:** a bedside standing beside a one-long bed's head on one
  long side makes that side's foot cell mandatory and drops the constraint on the other long
  side entirely (each sleeper gets in on their own side).
- **Seats:** a seat's front is its access cell, and a seat whose own group holds no table,
  desk, counter, game table, work surface or control to face must `back` a wall — the
  checker rejects a lone seat facing nothing.
- Cells covered by a piece of the same group drop out of a constraint; a constraint emptied
  that way stays and fails — the group would be blocking its own use.

A room's checker needs each constraint to keep its `need` of cells inside the room, free of
furniture and the open style's filler, and reached from a door. Access cells are
constraints, not space: they may overlap another group's access cells, the clearance gap
between groups and the ring around an open filler — but never furniture, walls or the
filler itself. The composer works the same rule from its own side: a candidate placement
that breaks a constraint is rejected the way an unreachable piece is.

**Reach-in closets** turn the rule around: their pieces' access cells lie outside the room,
and those cells — all on one side — are the closet's door cells. `derive()` writes them into
`doors`, the checker requires at least one door cell for every closet (reach-in and walk-in
alike), and every shelf, store and utility piece in a reach-in backs the wall opposite its
door.

## Groups: `groups/<family>.json`

Furniture groups are the fixed clusters the layouts describe through their `beside:`/`around:`
anchors — a bed with its bedside tables, a table with its chairs — moving as one piece. Each
file holds the family's groups and one recipe per layout, naming the groups it needs.

```json
{
  "groups": [
    {
      "id": "sleep.couple.bedside2",
      "family": "bedroom.master",
      "wall": "back",
      "use": ["south"],
      "pieces": [
        {"role": "sleep.couple", "size": [2, 2], "at": [1, 0], "back": "north"},
        {"role": "bedside", "size": [1, 1], "at": [0, 0]},
        {"role": "bedside", "size": [1, 1], "at": [3, 0]}
      ]
    }
  ],
  "recipes": [
    {
      "layout": "bedroom.master.small.a",
      "family": "bedroom.master",
      "sizeBands": ["small"],
      "groups": [
        {"group": "sleep.couple.bedside2", "kind": "anchor", "count": "couples"},
        {"group": "light.small.single", "kind": "optional"}
      ]
    }
  ]
}
```

- **Groups:** `id` is unique across all files. `wall` is `back` (against a wall), `corner`
  (two walls) or `none` (stands free). `use` lists the sides people stand or sit at. `pieces`
  never overlap and touch edge to edge as one shape. They are placed north-facing: `at` is a
  cell offset from the group's top left, `size` is the placed footprint (a piece turned onto
  the east or west side carries its turned size), and a wall-bound piece backs `north` on
  row 0. A piece may be `optional` or carry a `minWealth`.
- **Access:** a group's usability derives from its pieces' roles (see the Access section);
  a hand group may also carry `"access"` — a list of `{"cells": [[x, y], ...], "need": n,
  "replaces": [piece indexes]}` entries in group coordinates standing in for the derived
  constraints of the pieces `replaces` names. The cells must lie in the ring around the
  group (its bounding box grown by one cell on every side), off its own furniture and off
  the walls its `wall` stands on, and `need` may not top the cell count. Only hand work may
  carry `access` — the group needs `"source": "hand"` — and the converter never writes one.
- **Recipes:** one per layout, with `layout`, `family` and `sizeBands` copied from it. Each
  entry names a `group` with a `kind` — `anchor` (exactly one, the layout's main piece),
  `required`, `optional` or `repeatable` (as many as fit) — plus the source slot's `count`
  and `minWealth` when it had them.
- The files are generated from the layouts by `library-seed/layouts_to_groups.py` and may be
  hand-edited afterwards. `python -m worldgen library groups` checks them; the rules above
  are what it enforces.
- Hand work carries `"source": "hand"` — on a group, a whole recipe, or a single recipe entry —
  and the converter keeps whatever bears it verbatim (a converted group that would take a hand
  group's id is dropped instead), so re-running the seed never sweeps a hand edit away. The
  checker accepts `hand` and no other source.
- `groups/luxury.json` is hand-authored — the converter never writes or deletes it. Its groups
  follow the rules above with every piece carrying a `minWealth` of `wealthy` or `elite`, and
  its `pools` map names each private family's groups with the size bands they suit: at grand
  clearance the composer offers the family's pool as extra optional furniture, each group only
  in the bands its entry lists. Every pool group also carries a `kind` — one or more of
  `seating`, `hearth`, `work`, `decor`, `display`, `books` and `storage` — which the composer's
  grand-room limits count it against (the fireplace seating is both `hearth` and `seating`).
  The checker holds pools to the same account — the groups must exist, the family, bands and
  kind must be known, and every piece must carry the wealth.

## Rooms: `rooms/<family>.json`

Fixed rooms are composed furniture: whole rooms of placed groups — a bed with its
bedside, a chest, a lamp — checked and turned as one shape. There is no wall ring: every
cell is floor, the walls are the room's edges, and a wall-bound piece stands flush against
the edge it backs. Each file holds the family's rooms, one per size band, clearance and
style the composer found a clear layout for.

```json
{
  "id": "bedroom.small.1.tight",
  "family": "bedroom",
  "sizeBand": "small",
  "clearance": "tight",
  "style": "flush",
  "wealth": ["poor", "modest"],
  "size": [6, 3],
  "sleeps": {"singles": 1, "couples": 0},
  "pieces": [
    {"role": "light.small", "size": [1, 1], "at": [0, 0], "group": "light.small.single"},
    {"role": "bedside", "size": [1, 1], "at": [2, 0], "group": "sleep.bedside.storage.small.opt"},
    {"role": "sleep", "size": [1, 2], "at": [3, 0], "back": "north", "group": "sleep.bedside.storage.small.opt"},
    {"role": "seat", "size": [1, 1], "at": [5, 0], "group": "storage.big.seat.opt", "optional": true},
    {"role": "storage.small", "size": [1, 1], "at": [2, 1], "group": "sleep.bedside.storage.small.opt", "optional": true},
    {"role": "storage.big", "size": [1, 2], "at": [5, 1], "back": "east", "group": "storage.big.seat.opt"},
    {"role": "decor.floor", "size": [1, 1], "at": [0, 2], "group": "decor.floor.single.bedroom", "optional": true}
  ],
  "doors": {"north": [1, 4], "south": [1, 2, 3, 4], "west": [1]},
  "stretch": {"x": [0, 1, 2, 3, 4, 5], "y": [3]},
  "outdoor": false,
  "symmetric": false,
  "recipe": "bedroom.small.a",
  "description": "A small bedroom room (6x3) of 4 furniture groups at tight spacing."
}
```

- **Room:** `id` is unique across all files. `clearance` is `tight`, `roomy` or `grand`
  (1, 2 or 3 clear cells kept between groups); `style` is `flush` or `open`. `wealth`
  lists the tiers the room furnishes. `size` is the room in cells and `sizeBand` must fit
  its area. `sleeps` counts the beds, `outdoor` and `symmetric` flag what they name,
  `recipe` names the source recipe and `description` is one sentence.
- **Pieces:** each is a group's piece placed into the room — `role`, `size` and `at`
  cell, `back` on a wall-bound piece (flush against that edge, facing in), `group` naming
  the group it came from, `optional` when the room still works without it. Pieces never
  overlap, and every piece keeps its access constraints satisfied — each needs its `need`
  of cells (from the role's `roleAccess` rule, or the group's hand `access` list) inside
  the room, free of furniture and reached from a door. Lights, decor and optional pieces
  carry no constraints.
- **Doors:** per side, the cell offsets along that wall that can take one — free edge
  cells only, on at least two sides, every door opening into one connected free area.
- **Stretch:** `x` columns and `y` rows where an empty line can be inserted to grow the
  room; each line must sit clear of pieces and leave the room valid once inserted.
- **Open style:** the roomier variant records a `filler` — the clear middle's `at` and
  `size`, at least 2x2.
- The files are composed from the group recipes by `worldgen/room_composer.py` and may be
  hand-edited afterwards. `python -m worldgen library rooms` checks them; the rules above
  are what it enforces. `worldgen.fixed_rooms.rotate` turns a stored room to any side —
  four quarter turns return it unchanged.
- **Hand work:** a room may carry `"source": "hand"` (a person made or re-laid it out),
  `"edited": [...]` (the fields of `wealth`, `description`, `symmetric`, `retired` a person
  set, kept on regeneration) and `"retired": true` (out of use but kept in the file, so its
  id's letter is never reused). Regenerating a family keeps a hand or retired room exactly as
  it stands and drops any generated room equal to it after a turn or mirror; world generation
  and the assembler skip retired rooms (`worldgen.fixed_rooms.active`).
- **Two-sleeper bedrooms:** `bedroom.json` carries the composer's second pass — the same
  recipes composed for `sleeps {"singles": 2}` (two beds, each on its own access cells),
  under the same rules and the same dedupe, their ids continuing the letter sequence. A
  `description` says "for two" only of these rooms; a hand room or an older room that
  happens to sleep two keeps its own description untouched.
- **The assembler:** one-storey library buildings can be placed from these rooms whole
  (`--room-assembler`, `worldgen/assembler.py`). What helps it place a family: door offsets
  on three or four sides (a room with doors on one side can only end a wing), stretch lines
  for growing into a leftover strip, and a variant one cell up in each axis at the same
  clearance and wealth — without one, a strip beside the room can force the building back
  to the old method. The assembler never gives a family up for want of a stored room: when
  every stored room misses (band, clearance, wealth tier, sleepers or furnishings) it
  composes candidates from the family's recipes on the spot — the same checks as the
  generator — and tries the family's neighbouring band one step larger, then one smaller,
  before falling back. A stored room that fits always comes first, so good coverage of a
  family's bands and sleeper counts is what keeps buildings on the library's own rooms.

## Purposes: `purposes.json`

```json
{
  "*": {"roles": {"seat": ["chair", "stool"], "light.small": ["light"], "decor.floor": ["rug", "plant", "statue", "decor"]}},
  "forge": {
    "roles": {
      "work.primary":   ["forge"],
      "work.secondary": ["anvil", "workbench"],
      "work.tool":      ["rack"],
      "work.material":  ["firewood", "crate"]
    }
  }
}
```

Every purpose in `library.json` gets an entry. Each role binds to categories in order of
preference. `*` holds the defaults a purpose inherits. A purpose must bind every role that its
family's layouts use, directly or through `*`. A binding may also name object ids
(`["hearth.fireplace", "hearth.holo_fire"]`) to pin exact objects: `heat` is any heater (radiator,
brazier, woodstove) while `hearth` is the fireplace people gather around, bound by id so the
outdoor fire pits stay out.

## Suites: `suites/<band>.json`

```json
{
  "suites": [
    {
      "id": "cottage.family",
      "kinds": ["cottage", "farmhouse", "croft", "house"],
      "bands": ["medieval", "industrial"],
      "sizeClasses": ["small", "medium"],
      "residents": [2, 6],
      "wealth": ["poor", "modest"],
      "rooms": [
        {"name": "Main room", "purpose": "living_room", "share": "large"},
        {"name": "Bedroom",   "purpose": "master_bedroom", "share": "medium"},
        {"name": "Loft",      "purpose": "bedroom", "share": "small"}
      ],
      "connections": [["Main room", "Bedroom"], ["Main room", "Loft"]],
      "entrance": {"room": "Main room"}
    }
  ]
}
```

- **`id`** is `<kind>.<variant>`, unique across all suites.
- **`kinds`**: the P1 building kinds it answers, lower case ("inn", "tavern", "smithy").
- **`sizeClasses`**: the P1 building sizes `hut`, `small`, `medium`, `large`, `hall`. **`residents`**: `[min, max]` sleepers,
  `[0, 0]` for a workplace nobody sleeps in.
- **`rooms`**: one to eight rooms (a one-room hut is fine). `purpose` from `library.json`; `share` is `small`, `medium` or
  `large` (its part of the floor). Beds for the residents must exist: one `master_bedroom` per
  couple the building usually holds, `bedroom` or `dormitory` rooms for the rest.
- **`connections`**: pairs of room names; every room must be reachable from the entrance room.
- Name rooms the way the setting would ("Taproom", "Galley", "Crew bunks").
