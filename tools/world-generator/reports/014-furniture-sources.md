# 014: furniture source research for the room library

Status: in progress (2026-11-03). Drafts for the room library's first content, gathered from
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
| cdda-mapgen | CDDA `mapgen/` JSON | CC BY-SA 3.0 (share-alike) | 1 | Room layout patterns for change 3: 98 house variants (bungalows, duplexes, two-story modern) place furniture by room type. |
| pz-pfans | PZFans wiki furniture category | unknown | 1 | ~327 modern furniture item names (only page 1 of 6 itemised openly). Names only; page 1 showed paintings and misc decor, so it contributed the fridge alias and little else. |
| pa-fandom | Prison Architect wiki Objects template | unknown | 62 | Institutional furniture names by use: cell (bed, bunk bed, toilet), office (office desk, chair, filing cabinet), canteen (dining tables, serving table), common room (TV, sofa, arcade cabinet), infirmary (medical bed, morgue slab), laundry (machine, laundry basket), chapel (altar, pews), classroom (school desk, blackboard), gym (weight bench, treadmill, punching bag), workshop (press, saw, carpenter table), decorative (painting, fountain, coat stand). ~90 usable names. Read through the wiki's API (the HTML pages block fetching). |
| kenney-furniture | Kenney Furniture Kit | CC0 | 3 | Clean permissive-licence category names (table, chair, bed). The pack page itemises nothing; cited on the three universal basics whose names it tags. |
| dnd-srd | D&D SRD 5.1, equipment tables | CC BY 4.0 | 9 | Medieval gear that doubles as furnishings: bedroll, blanket, bucket, barrel, basket, chest, ladder, lamp, lantern, candle, torch, tent, iron pot, mirror, sack. The PDF itself will not render in the fetch tool (unsupported content type); the item names were cross-checked against D&D Beyond's Free Rules equipment page (opened; no licence stated on that page). Facts only. |
| wikipedia-furniture | Wikipedia: List of furniture types | CC BY-SA 4.0 (share-alike) | 48 | ~160 cross-band names and the cleanest category taxonomy (seating single/multiple, sleeping, tables, storage, religious, entertainment). Good for aliases and category boundaries. |
| tabletop-2mt | 2-Minute Tabletop furniture assets | CC BY-NC 4.0 | 0 | Confirms medieval fantasy room sets exist as a category (300 assets); the tag page itemises no names, so no entries cite it. Names only, nothing copied. |

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

`library-seed/objects.draft.json` holds **179 entries in 33 categories**, merged across the
sources above. Duplicates were merged into one entry with every source listed (a bed cites
RimWorld, Dwarf Fortress, Wikipedia and Kenney); shape changes stayed separate (straw pallet,
single bed, double bed, four-poster, bunk, hammock, hospital bed, crib).

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
hearth         5      2         4           3       0
light          7      3         4           4       1
medical        5      0         0           5       4
pallet         1      0         1           1       0
rack           6      3         3           6       0
religious      3      3         2           2       0
security       1      0         0           1       0
shelf          4      1         2           4       1
sink           3      1         2           2       2
sofa           3      0         2           3       0
stove          6      2         1           2       1
table          8      6         6           7       5
toilet         2      1         1           1       1
utility        1      0         1           1       0
work           22     11        14          11      5
```

`check_drafts.py` (standard library only) validates the draft: parse, unique ids, allowed values
for `bands`, `wealth`, `back`, part materials and purposes, and every `sources` id exists in
`sources.json`. Current run: **PASS**.

Merge notes worth review:

- Several entries read one source object as a relative of ours and say so in `note` (CDDA's
  airplane seat becomes the pilot seat; Wikipedia's commode becomes the chamber pot; the sewing
  table becomes the sewing machine). These are the loosest merges — flag any that feel wrong.
- `pz-pfans` and `tabletop-2mt` contributed almost nothing because their open pages itemise
  almost nothing; both stay in `sources.json` for a later, deeper pass.
- Fantasy-only work stations (alchemy bench) have no public-source backing here and were left
  out rather than invented; they belong in the Gaps list for the content brief.

## Purposes

(filled by change 3)

## Our own output

(filled by change 4)

## Gaps

(filled at the end)
