# 014: furniture source research for the room library

Status: complete (2026-11-03). Drafts for the room library's first content, gathered from
public game data, tabletop map-making resources and our own past model replies. Everything lives
in `library-seed/`; a later brief turns the drafts into real library files.

Licence rule used throughout: facts only (names, categories, footprints, which rooms an object
belongs in, layout patterns). No source text is copied; `note` fields paraphrase in a few words
of our own.

## Sources

Every source below was opened during this run. `entries` counts the draft entries in
`objects.draft.json` that cite the source (filled in by change 2).

| id | Source | Licence | Entries | Good for |
|---|---|---|---|---|
| rimworld-wiki | RimWorld Wiki: Furniture | CC BY-SA 3.0 (share-alike) | 34 | The only game source whose sizes match our cells exactly (bed 1×2, table 2×2, couch 2×1, shelf 2×1). About 50 usable entries across beds, tables, seats, lamps and shelving; its production-buildings page adds work stations (fabrication bench, tailor bench, butcher table, research bench, hydroponics basin, fermenting barrel, smelter — no sizes stated there). |
| df-wiki | Dwarf Fortress Wiki: Furniture | GFDL & MIT, dual (one option share-alike) | 12 | The medieval object list: anvil, armor stand, barrel, bed, bin, bucket, cabinet, chain, chest, coffin, millstone, quern, statue, table, throne, traction bench, weapon rack, window. ~25 entries, all 1×1 in game, so we take names, not sizes. |
| cdda-furniture | CDDA `furniture_and_terrain/` JSON | CC BY-SA 3.0 (share-alike) | 105 | The deepest modern/post-apocalyptic list: 12 beds, 19 seats, 63 storage pieces, plumbing (bathtub, shower, sink, toilet, water heater), appliances (oven, fridge/cooling unit, washing machine, dryer, dishwasher, furnace), hearths (fireplace, wood stove, brazier, clay oven, fire barrel), work tools (drill press, lathe, table saw, forge, anvil, kiln, still), medical (lab bench, IV pole, exam chair, autoclave, fume hood), recreation (pool table, arcade machine, treadmill, piano, pipe organ), counters and tables. ~150 household-usable names; no sizes (all one tile), flags give room membership. |
| cdda-mapgen | CDDA `mapgen/` JSON | CC BY-SA 3.0 (share-alike) | 2 | Room layout patterns for change 3: 98 house variants (bungalows, duplexes, two-story modern) place furniture by room type. |
| pz-pfans | PZFans wiki furniture category | unknown | 1 | ~327 modern furniture item names (only page 1 of 6 itemised openly). Names only; page 1 showed paintings and misc decor, so it contributed the fridge alias and little else. |
| pa-fandom | Prison Architect wiki Objects template | unknown | 63 | Institutional furniture names by use: cell (bed, bunk bed, toilet), office (office desk, chair, filing cabinet), canteen (dining tables, serving table), common room (TV, sofa, arcade cabinet), infirmary (medical bed, morgue slab), laundry (machine, laundry basket), chapel (altar, pews), classroom (school desk, blackboard), gym (weight bench, treadmill, punching bag), workshop (press, saw, carpenter table), decorative (painting, fountain, coat stand). ~90 usable names. Read through the wiki's API (the HTML pages block fetching). |
| kenney-furniture | Kenney Furniture Kit | CC0 | 3 | Clean permissive-licence category names (table, chair, bed). The pack page itemises nothing; cited on the three universal basics whose names it tags. |
| dnd-srd | D&D SRD 5.1, equipment tables | CC BY 4.0 | 10 | Medieval gear that doubles as furnishings: bedroll, blanket, bucket, barrel, basket, chest, ladder, lamp, lantern, candle, torch, tent, iron pot, mirror, sack. The PDF itself will not render in the fetch tool (unsupported content type); the item names were cross-checked against D&D Beyond's Free Rules equipment page (opened; no licence stated on that page). Facts only. |
| wikipedia-furniture | Wikipedia: List of furniture types | CC BY-SA 4.0 (share-alike) | 48 | ~160 cross-band names and the cleanest category taxonomy (seating single/multiple, sleeping, tables, storage, religious, entertainment). Good for aliases and category boundaries. |
| tabletop-2mt | 2-Minute Tabletop furniture assets | CC BY-NC 4.0 | 0 | Confirms medieval fantasy room sets exist as a category (300 assets); the tag page itemises no names, so no entries cite it. Names only, nothing copied. |
| local-replies | Our own P3 replies and fixture plans | own (no restriction) | 23 | `out/*/llm/*p3*.json` (68 files) and `fixtures/*.json` (19 plans): what our models actually put in each room. Merged in change 4 (see "Our own output"). |

Licence concerns:

- Four sources are share-alike (rimworld-wiki, cdda-furniture, cdda-mapgen, wikipedia-furniture)
  and one is dual with a share-alike option (df-wiki). All five are used for facts only in these
  drafts — names, sizes, categories, room membership — which are not copyrightable expression.
  If a later brief ever copies a share-alike list wholesale, that library file carries the
  licence; the `shareAlike` flag in `sources.json` marks them for that decision.
- tabletop-2mt is non-commercial. Names and categories only; nothing copied. If we ever want the
  art itself, that source is out.
- pz-pfans and pa-fandom state no licence. Facts only, never text.

## Objects

`library-seed/objects.draft.json` holds **183 entries in 37 categories**, merged across the
sources above. Duplicates were merged into one entry with every source listed (a bed cites
RimWorld, Dwarf Fortress, Wikipedia and Kenney); shape changes stayed separate (straw pallet,
single bed, double bed, four-poster, bunk, hammock, hospital bed, crib). Change 4 added four
entries our models used (grain sack, firewood stack, hay bale, plywood barricade) and gave 19
entries the aliases our replies call them by ("lidded chest", "tallow candle", "battery
lantern", "guard bunk", "straw bed" and so on).

- Sizes are north-facing footprints. RimWorld-sized pieces (beds, tables, couch, shelf, dresser,
  bookcase) carry its sizes; everything else uses the design's size guide with `"sizeGuessed":
  true` (138 of 179 entries — almost every source outside RimWorld is a one-tile game).
- `back` is `north` for pieces with a front (bed, wardrobe, stove, desk, throne), `null` for
  frontless ones (barrel, round table, rug, brazier).
- `wealth` splits shape variants: the pallet is poor, the single bed modest-to-wealthy, the
  four-poster elite.
- `names` carries band overrides where the noun changes (`bed`/`bunk`, `sink`/`galley sink`,
  `workbench`/`fabrication bench`, `treadmill`/`gravity treadmill`).

Coverage (`*` entries count towards every band). The v1 scope categories (bed, seats, tables,
storage, hearths/stoves, work, lights, washing, counters, shelves, decor) each have at least one
entry per band except the scifi hearth (see Gaps):

```
category       count  medieval  industrial  modern  scifi
appliance      15     0         2           14      5
barrel         2      1         2           1       1
barricade      1      0         0           1       0
basket         2      1         1           2       0
bath           3      1         1           2       1
bed            9      7         8           7       5
bench          4      2         3           3       1
bin            2      0         0           2       1
board          3      0         1           3       1
cabinet        10     3         5           9       3
chair          11     4         5           9       3
chest          4      2         2           3       1
coffin         1      1         1           1       0
console        2      0         0           1       2
counter        4      2         4           4       1
decor          9      5         6           9       4
desk           4      1         2           3       1
entertainment  12     1         5           10      1
gym            5      1         1           5       1
hay            1      1         1           1       0
hearth         5      2         4           3       0
light          7      3         4           4       1
medical        5      0         0           5       4
pallet         1      0         1           1       0
rack           6      3         3           6       0
religious      3      3         2           2       0
sack           1      1         1           1       0
security       1      0         0           1       0
shelf          4      1         2           4       1
sink           3      1         2           2       2
sofa           3      0         2           3       0
stove          6      2         1           2       1
table          8      6         6           7       5
toilet         2      1         1           1       1
utility        1      0         1           1       0
wood           1      1         1           1       0
work           22     11        14          11      5
```

`check_drafts.py` (standard library only) validates the draft: parse, unique ids, allowed values
for `bands`, `wealth`, `back`, part materials and purposes, and every `sources` id exists in
`sources.json`. Current run: **PASS** (183 entries, 37 categories; 22 purposes referencing all
37 categories).

Merge notes worth review:

- Several entries read one source object as a relative of ours and say so in `note` (CDDA's
  airplane seat becomes the pilot seat; Wikipedia's commode becomes the chamber pot; the sewing
  table becomes the sewing machine). These are the loosest merges — flag any that feel wrong.
- `pz-pfans` and `tabletop-2mt` contributed almost nothing because their open pages itemise
  almost nothing; both stay in `sources.json` for a later, deeper pass.
- Fantasy-only work stations (alchemy bench) have no public-source backing here and were left
  out rather than invented; they belong in the Gaps list for the content brief.

## Purposes

`library-seed/purposes.draft.json` covers **22 purposes**: the design's first 10 (bedroom,
kitchen, dining, common_room, shop, workshop, storage, office, washroom, dormitory) plus forge,
chapel, classroom, ward, cell, bridge, laboratory, library, laundry, guardroom, gym and
greenhouse (greenhouse exists only because RimWorld's hydroponics basin needs a home). Each
purpose lists its `core` categories (almost always present) and `extra` ones (sometimes, or
richer rooms), and binds every category to the roles the design's layouts use (`sleep`,
`work.primary`, `work.secondary`, `seat`, `seat.many`, `table`, `cook`, `heat`, `wash`,
`storage.small`, `storage.big`, `light.small`, `light.big`, `service`, `display`,
`entertainment`, `medical`, `decor.floor`).

Where the core/extra split comes from:

- Prison Architect's room requirements give the tightest cores: cell = bed + toilet, office =
  desk + chair + filing cabinet, kitchen = cooker + fridge + sink, dormitory = bunk + toilet,
  ward = medical bed. [pa-fandom]
- CDDA's house mapgen and furniture families give the looser extras: dressers and nightstands
  in bedrooms, entertainment centers and coffee tables in living rooms, furnaces and water
  heaters in basements. [cdda-furniture, cdda-mapgen]
- Wikipedia's category taxonomy settled the storage split (cupboards small, wardrobes and
  shelving big) and the dining extras (sideboards, display cabinets). [wikipedia-furniture]

`layout-notes.md` records, per purpose, the arrangement facts the sources show — beds lined
along one wall in shared bedrooms, L-shaped kitchen appliance clusters, washroom fixtures in a
wall line, pews in rows facing the altar, library bookcases shoulder to shoulder along every
wall. Its opening caveat matters: CDDA's house mapgen resolves furniture glyphs through
palettes we did not open, so we take positional patterns (wall-hugging furniture, corner
clusters, clear centres), not glyph identities; and the Prison Architect pairings come from its
wiki's object lists and room-requirement snippets rather than a fully open page.

`check_drafts.py` now also verifies that every category named in `purposes.draft.json` (in
`core`, `extra` and `roles`) exists in `objects.draft.json`: 22 purposes, all 33 categories
referenced, **PASS**.

## Our own output

`library-seed/mine_local.py` reads every `out/*/llm/*p3*.json` and every plan under `fixtures/`,
groups rooms by purpose keyword (from each room's name and purpose text), and prints the
templates and hints per group. Its full output is kept at `reports/014-mine-local-output.txt`.
The run: **68 p3 reply files (199 rooms, 755 furniture lines) and 19 fixture plans (423 rooms,
1372 furniture lines)**.

What our models actually do, against the sources:

- **Bedrooms** (76 p3 rooms, 105 fixture rooms) are stool + candle + bed + wall shelf + chest.
  Wardrobes, nightstands and dressers — the bedroom set every public source has — almost never
  appear. Storage in model bedrooms is a wall shelf and a chest, not a wardrobe.
- **Kitchens hold beds**: 16 straw-mattress beds in p3 kitchens, 59 straw beds in fixture
  kitchens. The models keep furnishing the medieval multi-use hall (sleep by the hearth) even
  when the plan gives the building separate rooms. The sources split sleep out of the kitchen.
- **Shops double as stockrooms**: the top shop-room templates are storage barrels, grain sacks,
  crates and shelving, with the service counter only in the middle of the list. Prison
  Architect's shop is counter-first with stock behind it.
- **One seat everywhere**: the wooden stool is the most-placed template in every group (116 in
  p3 bedrooms, 255 in fixture kitchens). The library's wealth-graded seat list gives the
  variety the models don't ask for.
- **Candles are already wealth-graded**: tallow candle, rushlight candle and candle stub are
  three separate model templates for the same object — exactly what the library does with one
  entry, wealth tiers and condition words.
- **The scattered beds are real, but not via "corner"**: p3 replies have 41 bed lines with
  count > 1 (102 beds); 0 use `corner` and 0 have no hint, but only 7 of 41 carry a `wall:`
  hint — the rest are rows, `beside:` and `center`, so multi-bed lines mostly miss the wall.
  Fixtures: 68 lines (158 beds), 5 `corner`, 0 unhinted, 27 with `wall:`.
- **Templates no public source had**: plywood barricade (zombie-setting boarding-up) is the
  only category with no public backing, added on local evidence alone. Grain sacks, firewood
  stacks and hay bales turned out to have public sources once checked (SRD sack, CDDA wood
  stash, PA hay bale) and were merged with both listed.

Merged into the drafts as source `local-replies` (licence "own"): four new entries (sack.grain,
wood.stack, hay.bale, barricade.plywood) and 19 entries extended with model aliases, from
"gurney" and "storage locker" to "tallow candle" and "guard bunk". `check_drafts.py` still
passes.

## Gaps

Categories or bands where nothing usable was found:

- **scifi heating**: no hearth-family entry for the scifi band (the coverage table's hearth
  row is the one v1-scope zero). RimWorld's torches and stoves don't translate; a scifi heat
  source needs inventing in the content brief.
- **scifi beyond name overrides**: most scifi coverage is a `names.scifi` override on a
  universal entry (bunk, galley sink, fabrication bench). Only console, appliance.server and
  work.hydroponics are scifi-shaped objects. A starship-focused source pass is still needed.
- **medieval medical**: the ward purpose has no medieval objects beyond a pallet and a screen.
  Dwarf Fortress's traction bench is in the source list but was never drafted.
- **Fantasy work stations**: alchemy bench, scribe's desk and similar genre-only pieces have
  no public-source backing in this survey (the tabletop art packs don't itemise names), so
  they were left out rather than invented.
- **Laundry small pieces**: ironing board (PA lists one) and drying rack were never drafted;
  the laundry purpose binds only machines, baskets and sinks.
- **Carryables that are almost furniture**: bucket, iron pot and lamp exist in the sources but
  sit between P2's item list and the room library; they need a placement decision.
- **Dwarf Fortress extras**: armor stand, animal trap, chain and rope are in the DF list and
  undrafted.
- **Two sources yielded nothing**: pz-pfans (page 1 of 6 open) and tabletop-2mt (no itemised
  names). Both are placeholders for a later, deeper pass.
