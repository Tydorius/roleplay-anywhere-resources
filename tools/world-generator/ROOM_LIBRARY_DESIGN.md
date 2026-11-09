# Room library: design

Status (2026-11-07): the library's data and checker exist, but the generator doesn't use them
yet. Built so far:
- the vocabulary (`library/library.json`) and the authoring rules (`library/AUTHORING.md`);
- `worldgen/library.py`: the loader, the checker, the text fill and a coverage report, run with
  `python -m worldgen library check --coverage`;
- default content written by Claude agents from the `library-seed/` drafts: 320 object types,
  204 layouts in 26 families, 72 purposes, 85 suites across the four bands, and every material
  class x band x wealth tier.

Step 1 is built too (2026-11-07): `layout_room` turns any template with a `back`, and
`wall:`/`row:` take `far`, `side` and `near`, measured from the room's door nearest the building
entrance. The turn reaches the scenario as `rot` plus the turned size. Templates without a `back`
(everything the model writes today) never turn, so the plain route is unchanged. Still to check
by hand: that `rot` in an imported scenario survives into play.

Step 3 is built too (2026-11-07), in `worldgen/library_rooms.py`:
- `compile_room` turns a layout into today's `FurniturePlan` lines. It picks a layout that fits
  the interior, fills each slot from the purpose's bindings (an id prefix such as `rack.weapon`
  or a category, with neighbouring wealth tiers as a fallback), counts beds from singles and
  couples, adds `minWealth` slots by tier, and adds each grow slot once while the room has space.
- `Templates` holds one template per object, band, wealth and condition, named for play
  ("Oak bed"), with its text filled from an RNG keyed by the template.
- `furnish_room` compiles and places a room. When a piece can't be placed it leaves the optional
  slots out, then redraws a couple of times and keeps the best result.
- `layout_need` gives the building packer a room's size from the layout's `minInterior`. Wiring
  it into `room_needs` is part of step 4.

Measured: every one of the 204 layouts lays out at its smallest and largest interior, door on
each wall, in all four bands at poor and elite, with every piece placed (13,056 rooms). Library
rooms (pieces with a `back`) also keep the cell past each door's threshold clear, place a piece
after the one it stands beside or around, and move a corner piece to a wall when the corners
are taken. A couple's slot only takes a bed that sleeps two, and a single's slot one that sleeps
one.

Step 4 is built too (2026-11-07), and the library is now **on by default**, with a toggle back
to the old method (`--no-library`, **Use room library** in the editor dialog, a question in the
launcher; `api.generate(library=False)`). In `worldgen/library_plan.py`:
- P1 gets an add-on asking for `setting.band`, `setting.genre` and each building's `wealth` and
  `condition`; code defaults anything missing (the band from the genre and era words).
- An ordinary building whose kind matches exactly one suite skips P3. Otherwise P3 runs
  `p3-library.txt`: the fitting suites and the purpose list, no catalogue, and rooms come back with
  a `use` from the list.
- Code expands each room into furniture lines from its layout (chosen by the room's share) and
  adds the library templates to the plan, so `plan.json` is a plain plan and a re-roll needs no
  library. Beds follow the cast: a couple to each master bedroom, the rest over the bedrooms,
  spare beds in guest rooms; a home with nowhere to sleep gets a bedroom.
- Unit buildings, and buildings with upper storeys under the floors extension, keep the old P3.
- P2 still writes the whole catalogue (step 5 cuts it down), and grow slots aren't used yet,
  because the room's final size isn't known when the plan is written.

Step 5 is partly built (2026-11-08):
- Unit buildings go through the library P3 too. It plans the shared rooms plus ONE unit copy
  with a purpose per room, code furnishes the copy (a bed per resident), and a reply with no
  copy gets one fitting room (an inn's guest room, a ship's cabin). Only a building with upper
  storeys under the floors extension still takes the old P3.
- When no building needs the old P3, P2 gets an add-on (`prompts/library/p2-catalogue.txt`):
  the catalogue is for the outside only (feature props, yard props, filler, outdoor lights), so it
  no longer writes indoor furniture that would go unplaced. The double-bed check applies only to
  old-P3 buildings.
- **At most five rooms per library building.** The building packer splits one footprint into
  five rooms and then collapses: a measured inn placed all 33 pieces in five rooms and dropped
  34 of 40 in six. A live run hit it when a hamlet's inn took the eight-room coaching-inn suite,
  overflowed the 28x22 cap and failed the build. Suites are trimmed to five rooms when used (the
  entrance room, then rooms for the sleepers, then the rest, reconnecting any room cut off), and
  P3 is told 1 to 5 rooms; many rooms of one kind belong in a unit building.
- **Compact when it would overflow.** Code measures each library building with the layout's own
  sizing (`_resolve_plan`) before writing the plan. If it would drop pieces, the rooms are
  furnished again with their smallest layouts and no optional pieces, and if it still doesn't
  fit, the least-needed room is left out. Every suite now furnishes with nothing dropped.
  Library templates that end up unused stay out of the plan.
- Found on the way (not fixed): when an overflowing building splits rooms into annexes, a
  character's start cell can land on a piece of furniture and fail the build. The old method can
  hit it too, with an oversized P3 design.
- **Reuse first.** Three picks in four take an object the world already uses when one fits, so a
  village's cottages share their beds and the game draws fewer sprites (41 library templates
  down to 33 in the live world below).
- **Live check (2026-11-08)**, the hamlet on Magnum-Diamond 24B with the library on: built with 0
  unplaced pieces and 0 validator errors, 456 objects in 25 reachable rooms. P2's catalogue held
  12 outdoor templates and nothing indoor. Two of four buildings skipped P3, and the inn went
  through the library as a unit building (a guest-room copy). P2's own token count is no guide
  with a model this terse (it took a retry this time); P3 per building is as measured above.
- Not built yet: the gap call and the user library with duplicate merging. With the ordered
  fallbacks in `purposes.json`, every required slot already has an object in every band, so
  there is nothing for a gap call to ask for yet; it becomes useful once the library is grown
  by hand or by users.

See "Open items from authoring" at the end.

Target: the world generator in this folder.

## Why

The model spends most of a run furnishing ordinary rooms. Per-phase token totals from four live
runs (`out/*/llm/*.json`):

| Run | Total tokens | P3 interiors | P2 catalogue |
|---|---|---|---|
| Run-down estate (2026-11-02) | 343k | 53.7% | 15.9% |
| Small castle (2026-11-01) | 229k | 66.8% | 15.6% |
| Ashvale (live-013) | 316k | 46.5% | 18.5% |
| Zombie town (live-013) | 310k | 43.8% | 14.2% |

A P3 reply is small: the Old Hall's was 3.8k characters, 3 rooms and 13 furniture lines. It
still cost 8.8k tokens, because most of the cost is reasoning plus the whole catalogue pasted
into every prompt. Most P3 retries come from two kinds of mistake: hint typos
(`beside:<Trestle table>`, a template that doesn't exist) and bed counts that don't match the
residents. The free-form hints also allow "Bed ×3, corner", which scatters beds around the room.

The library replaces most of that work with choices from a list. The model says what a building
and its rooms are for; code picks a known-good layout, fills it with objects for the setting,
turns each piece to face the right way and writes the descriptions. The model still writes
purpose-built rooms (the still, the chapel) the way it does today.

**Goals**
- Cut P3 tokens sharply and P2's template tokens (target: about half a run's total; to be
  measured, see "Measuring it").
- Rooms that read as rooms: a bed against a wall with nightstands beside it and a wardrobe in a
  corner, not three beds in random places.
- No combinatorial growth: each object is written once, each material table once per genre band.
- A library users can grow: whatever the model makes is saved for the next run.

**Not goals (v1)**
- Items and loot pools. P2 still writes those. An item library is a later step and would use the
  same text-template approach.
- Outdoor props, P4 dressing and P5 people.
- Changing the Scenario Editor. It may read the library later (see open questions), without
  changing it.

## How it fits the generator

It changes how the scenario data is made, not what the game reads. The output is plain 0.18
scenario data (templates, placed objects, `rot`), so **it needs no game mod**, and worlds made
with it play in the unmodded game.

It is a run option, **Use room library**, beside the extension toggles in the editor dialog and
the launcher. It isn't an extension in the `extensions/` sense, because it needs no game mod. The
old everything-from-the-model route stays as it is, for comparing tokens and for settings the
library doesn't cover. Default off until it is measured; see open questions.

The rule "models describe, code places" still holds. The library just moves more of the
describing into data.

## Concepts

### Genre band

Each object and sprite belongs to one of four bands. A setting maps to one band; specific
genres don't get bands of their own.

| Band | Covers |
|---|---|
| `medieval` | fantasy, ancient, classical, dark ages |
| `industrial` | steampunk, Victorian, Western, dieselpunk |
| `modern` | present day, near future, post-apocalyptic, zombie |
| `scifi` | cyberpunk, space opera, starships, stations |

P1 picks the band from a fixed list (a new `setting.band` field). It also writes free-text
`setting.genre` ("fantasy", "cyberpunk"), which genre-only objects use (see `onlyGenres` below).

Post-apocalyptic is the modern band with the condition turned down, not a band of its own.

### Wealth

Four tiers: `poor`, `modest`, `wealthy`, `elite`. P1 gives each building a `wealth` (default
`modest`). A room may differ from its building: the servants' room in a manor is `poor`.

Wealth picks materials, and decides whether optional slots and shape variants appear.

### Condition

Four steps: `ruined`, `worn`, `kept` (default), `pristine`. Condition is separate from wealth: a
rich house can be in ruins, which is the run-down estate. P1 sets it per building or per zone;
the zombie town is `worn` to `ruined` throughout.

This is not the game's item `quality` (common to legendary). The library never uses that word.

### Room purpose and size band

A **purpose** is what a room is for: `bedroom`, `kitchen`, `dining`, `common_room`, `office`,
`workshop`, `shop`, `storage`, `washroom`, `dormitory`, `forge`, `chapel`, `classroom`, `ward`,
and so on. The list is data (`purposes.json`), so users can add to it.

A **size band** (`tiny`, `small`, `medium`, `large`) is the room's interior area. Code decides it,
never the model.

## Library data

Everything is JSON under `library/`. A user library in the same layout overlays the default one
(see "Growing the library").

```
library/
  objects/<category>.json     object types, grouped by category
  materials.json              material class x band x wealth -> materials and colours
  conditions.json             condition words per material class
  layouts/<purpose-family>.json   room layouts made of slots
  purposes.json               purpose -> layout families + role bindings
  suites.json                 building recipes: rooms, purposes, connections
  sprites/<band>/<object id>.webp  shipped art, plus index.json per band
  library.json                version, band aliases, the wealth and condition lists
```

### Object types

An object type is what a thing *does*: its size, whether it's solid, whether people sleep on it,
which edge is its back. Its looks come from the band, materials and condition at fill time.

```json
{
  "id": "bed.single",
  "category": "bed",
  "size": [1, 2],
  "walkability": 0,
  "forSleep": true,
  "light": 0,
  "tags": ["bed", "furniture"],
  "back": "north",
  "wealth": ["modest", "wealthy"],
  "bands": ["*"],
  "onlyGenres": [],
  "names": {"*": "bed", "scifi": "bunk"},
  "parts": {"frame": "wood", "cover": "fabric"},
  "partsByBand": {"scifi": {"frame": "metal", "cover": "synthetic"}},
  "text": {
    "description": "{A:condition} {frame} {noun} with {cover.color} {cover} covers.",
    "physical": "Top-down view of a single {noun}, {frame} frame, {cover.color} {cover} blanket, headboard at the top."
  },
  "container": false,
  "lootPool": null,
  "sprites": {"medieval": {"file": "sprites/medieval/bed.single.png",
                           "fixed": {"frame": "dark oak", "cover": "red wool", "cover.color": "red"}}}
}
```

- **Size is the north-facing size**: the size with the back edge at the top. A bed is `[1, 2]`.
- **`back`** is the edge that goes against a wall or faces away from what the piece serves:
  headboard, wardrobe back, the cold side of a forge. Usually `north`. `null` means the piece has
  no front (barrel, round table, tree) and never needs a turn.
- **Shape changes are separate objects.** A straw pallet, a single bed, a double bed and a
  four-poster are four objects in category `bed`, each with a wealth range. Material only
  changes the text; a real difference in shape is a different object with its own sprite.
- **`bands`** limits an object to some bands (`["scifi"]` for a cyberdeck). **`onlyGenres`**
  narrows it further by `setting.genre` (an alchemy bench is `medieval` +
  `onlyGenres: ["fantasy"]`).
- **`names`** gives the noun per band ("hearth", "cooking range", "galley unit"). `*` is the
  fallback. Without it, a medieval noun ends up in a scifi room ("a polymer hearth").
- **`parts`** name the material classes the text uses (`frame: wood`). `partsByBand` overrides
  them per band.
- **`container`** and **`lootPool`** carry over to the game template the way P2's do today.

### Materials

`materials.json` is keyed by material class, then band, then wealth. **It is shared by every
object**, which is what keeps growth additive: a new object needs no new material text, and a new
material reaches every object that uses its class.

```json
{
  "wood": {
    "medieval": {
      "poor":    [{"name": "rough pine", "colors": ["pale", "grey-brown"]}],
      "modest":  [{"name": "ash", "colors": ["honey"]}, {"name": "pine", "colors": ["pale"]}],
      "wealthy": [{"name": "oak", "colors": ["golden-brown"]}],
      "elite":   [{"name": "carved walnut", "colors": ["dark brown"]}]
    },
    "modern": {"poor": [{"name": "particleboard", "colors": ["beige", "white"]}]}
  },
  "fabric": {"medieval": {"poor": [{"name": "straw-stuffed sacking", "colors": ["dun"]}]}}
}
```

A missing cell falls back to the next wealth tier toward `modest`, then to the band's `*` entry,
and is reported once per run.

Classes for v1: `wood`, `metal`, `stone`, `fabric`, `leather`, `glass`, `ceramic`, `synthetic`,
`plant`.

### Conditions

`conditions.json` gives condition words per material class, with a general fallback: metal
`ruined` is "rusted-through", wood `ruined` is "rotting", fabric `worn` is "threadbare". `kept`
adds no word, so most descriptions stay short.

### Text fill

Code fills an object's `description` and `physicalDescription` from `text` when it adds the
object's template to the world. No model call.

| Token | Fills with |
|---|---|
| `{noun}` | `names[band]`, else `names["*"]` |
| `{frame}`, `{cover}` … | the material picked for that part |
| `{frame.color}` | one of that material's colours |
| `{condition}` | the condition word for the main part's class (empty when `kept`) |
| `{A:…}` | the same with "a" or "an" in front, chosen from the first word that remains |

- After filling, a small grammar pass collapses double spaces and drops an empty "with … covers"
  clause when a part has no material.
- Choices are made from the run's seeded RNG, keyed by the template, so a re-roll gives the same
  text.
- **One template per (object, band, wealth, condition) in use**, not one per placed piece. A
  village of `modest` cottages shares one "bed" template; an elite manor adds its own. This keeps
  the template count, and so the game's sprite generation, small.
- **When an object has a shipped sprite for the band**, the sprite's `fixed` materials and
  colours win, so the text matches the art. The variables vary freely only when the game draws
  the sprite itself from `physicalDescription`.

### Layouts and slots

A layout is a set of slots: positions relative to the room's walls and doors, never fixed cells.
Code carves the room and places its doors before furnishing, so a layout can't know cells ahead
of time.

```json
{
  "id": "workshop.medium.a",
  "family": "workshop",
  "sizeBands": ["medium"],
  "minInterior": [4, 4],
  "maxInterior": [7, 6],
  "slots": [
    {"id": "store",  "role": "storage.small",   "size": [1, 1], "anchor": "row:far", "count": [3, 5], "back": "wall"},
    {"id": "main",   "role": "work.primary",    "size": [2, 2], "anchor": "center"},
    {"id": "second", "role": "work.secondary",  "size": [2, 1], "anchor": "wall:side", "back": "wall"},
    {"id": "seat",   "role": "seat",            "size": [1, 1], "anchor": "beside:second", "optional": true},
    {"id": "lamp",   "role": "light.small",     "size": [1, 1], "anchor": "corner", "minWealth": "modest"}
  ],
  "grow": [
    {"role": "storage.small", "anchor": "row:far"},
    {"role": "decor.floor",   "anchor": "corner"}
  ]
}
```

- **`role`** says what the slot is for. A purpose binds roles to object categories (below), so
  one workshop layout serves a forge, a carpenter's shop and a fabricator bay.
- **`size`** is the north-facing size the slot takes. It is matched against an object's size in
  either orientation.
- **`count`** is a number, a `[min, max]` range, `"couples"` or `"singles"`. Bed slots use the
  last two, and code fills them from P1's `residents` and `couples`, so the bed-count check stops
  being a model job (see "Beds and sleepers").
- **`optional`** slots are dropped first when the room is tight. **`minWealth`** slots appear only
  at that wealth or above: an elite bedroom gets a vanity and a rug.
- **`grow`** slots are added in order, while space remains, when a room comes out bigger than the
  layout needs. This handles the empty-floor problem without the model.
- **`back: "wall"`** turns the piece so its back is against the wall it stands on. Without it, a
  piece with a back faces into the room.

**Anchors** are the existing room hint vocabulary (`wall:<side>`, `row:<side>`, `corner`,
`center`, `beside:`, `around:`, `near_door`, `away_from_door`, `symmetric`), plus three relative
sides resolved inside `layout_room` once the doors are known:

| New anchor | Means |
|---|---|
| `far` (`wall:far`, `row:far`) | the wall farthest from the room's main door |
| `side` (`wall:side`) | a wall at right angles to the main door's wall |
| `near` (`wall:near`) | the door's own wall, beside the door |

`beside:` and `around:` name slot ids in a layout. Code rewrites them to template names when it
compiles the layout into today's `FurniturePlan` lines, so the placer itself only gains the three
new sides and rotation (see "Orientation").

Each purpose family needs about 3–5 variants per size band, so rooms don't all look alike. On top
of that, code mirrors the layout and picks which of two equal walls to use at random.

### Purposes

`purposes.json` binds each purpose to layout families and fills each role with categories, in
order of preference:

```json
{
  "forge": {
    "families": ["workshop"],
    "roles": {
      "work.primary":   ["forge"],
      "work.secondary": ["quench_trough", "anvil"],
      "storage.small":  ["tool_rack", "crate"],
      "seat":           ["stool"]
    }
  },
  "carpentry": {
    "families": ["workshop"],
    "roles": {"work.primary": ["workbench"], "work.secondary": ["lathe", "sawhorse"],
              "storage.small": ["timber_rack", "crate"]}
  }
}
```

Role names shared by many purposes (`seat`, `light.small`, `storage.small`, `decor.floor`) get
default bindings in `purposes.json["*"]`, so each purpose lists only what it changes.

**Picking an object for a slot:** take the role's categories in order. Keep objects allowed in the
band (and genre) whose wealth range includes the room's wealth and whose size fits the slot in
either orientation. Pick one with the seeded RNG. No match at all is a library gap (see "Gaps").

### Suites

A suite is a building recipe: rooms with purposes and shares, connections, and the entrance room.
It is the multiple-choice answer for ordinary buildings.

```json
{
  "id": "cottage.family",
  "kinds": ["cottage", "farmhouse", "croft", "house"],
  "bands": ["medieval", "industrial"],
  "sizeClasses": ["small", "medium"],
  "residents": [2, 6],
  "rooms": [
    {"name": "Main room", "purpose": "common_room", "share": "large"},
    {"name": "Bedroom",   "purpose": "bedroom",     "share": "medium"}
  ],
  "connections": [["Main room", "Bedroom"]],
  "entrance": {"room": "Main room"}
}
```

Room names are defaults. P3 may rename them ("The Smithy") without changing their purpose.

## Orientation

Checked in the 0.18 bundle (`index-DSU_zx7g.js`), 2026-11-03:

- A placed object can carry `rot`, 0–3 quarter turns, left out when 0.
- The sprite is drawn at the template's own size, then turned `rot × 90°` clockwise on screen.
  The outline, drop shadow and lamp shadow turn with it. **One sprite per template covers all four
  turns.**
- The placed object's `size` is the turned footprint. The game's own rotate swaps `[w, h]` for odd
  turns.
- The game draws north at the top of the screen, so with art drawn back-at-the-top:
  `rot` 0 = back north, 1 = east, 2 = south, 3 = west.
- God mode has rotate-left/right keys, and saves keep `rot`. The Scenario Editor already writes
  `rot` the same way (`tools/scenario-editor/mapops.js`, `rotateObject`).
- **Not yet checked:** that `rot` in an imported scenario survives into play. Step 1 of the build
  order checks this with a one-object scenario.

What the generator does with it (built 2026-11-07, `worldgen/layout_room.py`):

- A piece with a `back` placed by `wall:` or `row:` stands with its back to that wall, and in a
  `corner` with its back to one of the corner's two walls. So `back: "wall"` on a slot is what
  every wall slot gets anyway.
- For `around:<slot>` (chairs at a table), each piece faces the target.
- Anywhere else it tries the unturned footprint first, then the quarter turn, so a turnable
  1×2 piece fits narrow rooms far more often.
- A piece with no `back` keeps `rot` 0 and places exactly as before.
- `ObjectOut.rot` carries the turn; the spec writer adds `"rot"` to the placement entry, and the
  vendored builder writes `rot` and the turned `size` on the placed object.

The model never reasons about rotation.

## Beds and sleepers

Checked in the 0.18 bundle, 2026-11-03:
- **The game has no bed capacity and no bed ownership.** At bedtime an NPC takes the nearest sleep
  object in its scheduled room whose best spot nobody else has claimed.
- **Where the sleeper lies depends on walkability.** A walkable cell on the bed is the spot. For a
  bed with walkability 0, the game falls back to a free cell beside the bed, so the sleeper lies
  on the floor.

Rules for the library (brief 015 makes the generator follow them on the plain route; the editor's
checks already count capacity this way):
- **Capacity:** a sleep object at least 2 cells in both directions sleeps 2. Anything narrower
  sleeps 1, including a turned 2×1. Objects declare it through their size: `bed.double` and
  `bed.fourposter` are 2×2.
- **Sleep objects have walkability 0.3**, so people lie on them, as the game's own big beds do
  (0.3–0.4).
- **Couples:** each couple gets one double bed, in a bedroom where nobody else sleeps, because the
  game can't keep partners together otherwise. Children and others sleep in other rooms when the
  building has them.
- **Every wealth tier has a double**: a straw-stuffed double for `poor`, a carved four-poster for
  `elite`. A couple is a household fact, not a wealth one.
- **Layouts:** a `bedroom.master` family with one `couples` bed slot (nightstands beside it,
  storage in a corner), and the ordinary bedroom and dormitory families with `singles` slots. A
  home's suite picks one master bedroom per couple.
- **Sleep belongs in bedrooms.** Brief 014's mining found our models put beds in kitchens and
  halls (16 in P3 replies, 59 in fixtures), the medieval sleep-by-the-hearth habit. Kitchen and
  common-room layouts have no bed slots; a suite for a one-room hut uses a `hut.single_room`
  layout with a sleeping corner instead.

Who is a couple comes from P1 (`couples` on a home) and P5 (`partner`), kept in `plan.json`. The
scenario format has no relationship field; a future relationships mod would carry it (see
`_reference/mod_roadmap.md` in the scenarios folder).

## Pipeline changes

| Phase | Today | With the library |
|---|---|---|
| P1 world | zones, buildings, residents | adds `setting.band` (fixed list), `setting.genre`, and per building `wealth` and `condition` |
| P2 catalogue | 12–30 templates + items + loot pools | templates come from the library. P2 is asked only for items, loot pools, and objects for features the library can't match (see "Gaps") |
| P3 interiors | rooms, connections, every furniture line with hints | **picks**: a suite id (or none), each room's purpose from the list, optional renames and wealth overrides. Free-form furniture only for rooms marked `custom` |
| Placement | hints from the model | hints compiled from layout slots, plus `far`/`side`/`near` and rotation |
| Spec writer | no `rot` | writes `rot` and the turned size |

### P3 with the library (`p3-library.txt`)

The prompt shows:
- the building line;
- the suites whose `kinds`, band, size class and residents fit, as `id | rooms`;
- the purpose list.

It no longer shows the full catalogue: a `custom` room gets just the categories, plus its own
free furniture lines as today.

```json
{"name": "Old Hall", "suite": "manor.hall",
 "rooms": [{"name": "Great Hall", "purpose": "common_room"},
           {"name": "Kitchen", "purpose": "kitchen"},
           {"name": "Pantry", "purpose": "storage"},
           {"name": "Muniment Room", "purpose": "custom", "furniture": [ ... today's lines ... ]}],
 "wealth": {"Pantry": "modest"},
 "yard": null}
```

**Skipping P3.** A building whose kind matches exactly one suite, with no units, no compound slot
and no "Other instructions" note naming it, can skip P3: code takes the suite as it is. That is the
fourth peasant cottage. The rule lives in one function, so it is easy to tune, and the plan records
which buildings were skipped.

### Room sizing

Today `room_needs` sizes a room from its furniture lines. With a layout, a room's need is the
layout's `minInterior` (plus walkway). When code carves a room larger than the layout's
`maxInterior`, it moves to the next size band's layout for the same purpose; within the range,
`grow` slots fill the space.

### Re-roll and plan.json

`plan.json` stores the **expanded** design (the compiled furniture lines with object ids, the
filled templates, the chosen layout ids) plus the library version. `layout --plan` re-rolls from
that and never re-reads the library, so a later library change never changes a saved world.

## Gaps and growing the library

When a role, purpose or outdoor feature has no object for the band and wealth:

1. **Widen first:** try the next wealth tier, then the band's `*` objects, then any category the
   role lists further down.
2. **Then ask the model, in one batch per run:** after P3, every gap goes into one P2-style call
   that asks for **new looks of existing object types first** (a name and text template for a
   band), and new object types only when nothing fits. New object types must give `category`,
   `size`, `walkability`, `back` and `parts`. Code checks those fields like any template.
3. **Save what it made** to the user library (`library-user/`, same layout), tagged with the
   run and date, so the next run finds it.

**Duplicates.** Before saving, code merges near-duplicates: same category and size, and names
equal after lower-casing, stripping punctuation and dropping material words ("Trestle table",
"trestle table", "oak trestle table"). Merged entries keep both names as aliases.

The user library is never written inside `library/`, so updating the generator never touches a
user's additions. A `library` command lists, validates and prunes it.

## Art

Sprites are optional. With no sprite, the game draws one at Start Game from
`physicalDescription`, which the text fill already writes.

Shipped sprites (built 2026-11-09):
- one per object per band: 862 in all (180 medieval, 236 industrial, 244 modern, 202 sci-fi),
  about 42 MB of RGBA WebP with transparent backgrounds, every one reviewed by hand;
- drawn top-down (a few tall pieces at a steep three-quarter angle so they read), back edge at the
  top, at the north-facing size;
- `sprites/<band>/index.json` records, per object, the materials and `physical` text the art was
  drawn from and `reviewed`. A template that uses a sprite pins those materials and takes that
  text, so the words match the picture, and every tier of the object shares the one sprite
  (`worldgen/library_art.py`, `Templates.get`);
- after a build, `attach_sprites` copies each used sprite to `media/<template id>/<template
  id>-sprite.webp` in the scenario and rebuilds the zip, so the game shows it instead of drawing
  its own.

How they were made: `library-seed/make_art_scenarios.py` writes one scenario per band holding every
object once (modest tier, kept condition) with a manifest back to the library. Those are opened
in the Scenario Editor's image tab, generated on ComfyUI and kept or regenerated by hand; then
`library-seed/pull_art.py <band> --kept` copies the kept images into `sprites/<band>/` as
reviewed. Without `--kept` it pulls the newest ComfyUI results unreviewed, for a trial.
Prompts that kept failing were reworded: pale, white or clear parts are cut out by the
background remover, so they were darkened or rimmed; words like "tall" or "standing" give side
views.

Wealth differences that change the shape are separate objects with their own sprites. Material
differences within one object share the band's sprite. That is the trade-off for keeping the art
at one sprite per object per band.

## Default library v1 (scope)

Enough to cover the buildings in our fixtures and live runs:

- **Object types:** about 120 in about 30 categories (beds ×4 shapes, seats, tables, storage,
  hearths and stoves, work stations, lights, washing, counters and shelves, decor).
- **Purposes:** the 10 most common first: bedroom, kitchen, dining, common_room, shop, workshop,
  storage, office, washroom, dormitory. Then forge, chapel, classroom, ward, cell, bridge or
  cockpit.
- **Layouts:** 3 size bands × 3–5 variants for each of the first 10 families, about 120.
- **Suites:** about 10 per band.
- **Materials and conditions:** all nine classes × four bands × four tiers. A few hundred short
  entries.

### Seeding from existing sources

The first lists come from work that already exists, not from scratch.

**Public sources** (brief 014, a GLM research run with web search):
- **Game furniture lists** on public wikis and open data:
  - RimWorld (sizes match our cells: a bed is 1×2);
  - Dwarf Fortress (every piece is 1×1; take the list, not the sizes);
  - Cataclysm: Dark Days Ahead (open JSON data with a large modern and post-apocalyptic furniture
    list, plus room layouts in its map generation files);
  - Project Zomboid and Prison Architect for modern rooms.
- **Tabletop map making:** asset-pack catalogues for Dungeondraft and similar tools, the D&D 5e
  SRD equipment lists (CC BY 4.0), and furnishing guides. One 5 ft square ≈ one cell.
- **Open asset kits** such as Kenney's furniture kits (CC0), for names and categories.

**Our own output:**
- 68 P3 replies in `out/*/llm/*p3*.json`;
- 19 fixture plans covering medieval, modern, cyberpunk, starship, hospital and zombie settings.

These show what our models actually put in each kind of room.

**Licence rules:**
- **Take facts, not text.** Facts are object names, categories, footprints, which rooms an object
  belongs in, and layout patterns. Our descriptions come from our own text templates, never from
  a source's wording.
- **Record where each entry came from.** Every draft entry lists its source ids, and
  `sources.json` records each source's URL and licence.
- **Copy share-alike data only knowingly.** If we ever copy share-alike data wholesale (CC BY-SA,
  as with CDDA and most wikis), that part of the library carries the licence. The research run
  flags those sources so we decide case by case.
- **Use public pages and repositories only.** Nothing is extracted from a game install, and
  nothing downloaded is run.

The research produces drafts in `library-seed/` that brief 2's loader and validator then turn
into real library files.

## Checks and tests

- **Schema validator** for every library file: ids unique, categories exist, every slot role
  bound for every purpose that uses the layout, text tokens all resolvable.
- **Every layout lays out**: at its `minInterior` and `maxInterior`, with doors on each wall, with
  no failures and full walkability, for each band at each wealth tier.
- **Coverage report**: per band and wealth, which roles have no object. This drives the authoring
  work and the gap call.
- **Rotation**: unit tests for the back-to-wall turn, `around` facing, turned footprints, and
  `rot` plus the turned size in the written spec.
- **No regression on the plain route**: with the option off, every existing test and fixture build
  is unchanged.
- The fixtures are hand-written plans, so they can't show the token savings. Per the standing rule,
  **one live run after any phase change**.

## Measuring it

Run the same three ideas (a medieval village, the zombie town, a cyberpunk block) with the option
off and on, same provider and model. Compare per-phase tokens from the call logs, P3 retry counts,
layout failures and fallbacks, and the play-test look of a few rooms.

The token target is a guess until this is done. P2's items and loot pools aren't touched, so P2's
saving is only its template share.

**First measurement (2026-11-07, step 4).** The fishing-hamlet idea on Magnum-Diamond 24B (Q4,
local), seed 1, the library off and on at the same time. Each run planned its own hamlet, so the
whole-run totals compare different worlds; per building is the fair figure.

| | Library off | Library on |
|---|---|---|
| Calls / tokens, whole run | 17 / 64,854 | 16 / 53,726 |
| Ordinary buildings | 5, all through P3 | 3: 2 through P3, 1 skipped (a suite fit) |
| P3 tokens for them | 18,186 (3,637 a building) | 3,949 (1,975 a call, 1,316 a building) |
| P1 tokens | 3,600 | 3,947 (the add-on) |
| Unplaced pieces, validator errors | 0, 0 | 0, 0 |

So P3 costs about half as much per call, and about a third as much per building once skips are
counted. The inn was a unit building in both runs and took the old P3. Magnum ignored P1's
add-on, so the band came from the era word and every building defaulted to modest and kept. In
the library world the rooms read as rooms (a double bed in the master bedroom, a row of beds in the
children's room), but they are sparse: grow slots aren't used yet, and the building still carves
long, thin rooms.

## Build order

Sized for GLM briefs: 3–4 changes each, with Claude checking each one.

0. **Source research (brief 014).** Furniture lists from public sources and our own past replies,
   drafted into `library-seed/` with sources and licences. No generator code changes, so it can
   run alongside step 1.
1. **Rotation and anchors.**
   - Import test that `rot` survives.
   - `layout_room` tries four turns and supports `back`, `far`, `side` and `near`.
   - The spec writer emits `rot`.
   - This helps the plain route even before any library exists.
2. **Schema and loader.**
   - The `library/` file layout, the validator, the text fill with grammar pass, and the
     materials and conditions tables.
   - Turning brief 014's `library-seed/` drafts into library files that pass the validator.
3. **First layouts and purposes.** The 10 common families with slots compiled to
   `FurniturePlan`, `grow` slots, the "sleepers" count, room sizing from `minInterior`, and the
   layout and coverage tests.
4. **P3 with the library.** `setting.band`, `wealth` and `condition` in P1; `p3-library.txt` and
   its contract; suites; skipping P3; the expanded design in `plan.json`; the option in the
   launcher and the editor dialog.
5. **P2 cut down, and gaps.** The library supplies templates; the gap call; the user library with
   duplicate merging; the `library` command.
6. **Default library content.** Fill the four bands to the v1 scope, using the coverage report.
7. **Art.** Done: shipped sprites for every object in all four bands (see Art).

Measure after step 4, the first point where tokens change.

## Open questions for Michael

1. **Default on or off?** Decided 2026-11-07: on, with a toggle back to the old method.
2. **Four wealth tiers and four conditions**, or do you want a fifth tier (royal or corporate
   elite)?
3. **Where the user library lives:** next to the generator (`library-user/`, simple, travels with
   the folder) or in a per-user app folder (survives reinstalling the generator).
4. **Scenario Editor:** should it read the library later (an object palette for hand-built maps)?
   That would be a read-only import, without changing the editor's own data.
5. **Items:** a P2 item library using the same text templates would remove most of P2's remaining
   cost. Do it after v1, or fold it in?

## Open items from authoring (2026-11-07)

The agents that wrote the default library asked for these. None is built yet.

- **Anchors:** `wall:opposite`, the side wall facing a `wall:side` piece, so two rows of pews,
  beds or shelves don't land on the same wall. Also rows that face another slot (pews towards an
  altar, desks towards a board), and `between:door+<slot>` for a shop counter between the door
  and the stock.
- **Roles:** animal feed (stables use `storage.bulk`), a reading table, a filing cabinet, a
  reception desk apart from `counter.serve`, and a clinic's instrument trolley.
- **Material classes:** paper or card (a cardboard box, a map, a canvas) and wax.
- **Text fill:** code now makes a fixed "a"/"an" agree with the word after it, drops a colour
  that the material name already contains ("chrome chrome-plated"), and collapses a repeated word
  ("marble marble altar"). `partsByBand` merges over `parts`.
- **Coverage:** with ordered fallbacks in `purposes.json` (a medieval "control room" gets a map
  table, a cramped sci-fi kitchen an appliance), every required slot has some object in every
  band. About 1,900 slot x tier cells are filled only from a neighbouring wealth tier.
