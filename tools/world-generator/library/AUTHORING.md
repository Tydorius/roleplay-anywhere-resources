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
  serves (`library.json` → `sizeBands`, by interior area).
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
- **Variety:** 2–4 layouts per size band a family really uses (a dormitory has no tiny band, a
  washroom no large one). Make variants genuinely different: a different wall for the main
  piece, a centred versus a wall-hugging arrangement, an L versus a straight run.
- The layout is generic. The purpose binds roles to categories, so one workshop layout serves a
  forge and a fabricator bay.

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
family's layouts use, directly or through `*`.

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
