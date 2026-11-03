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
| rimworld-wiki | RimWorld Wiki: Furniture | CC BY-SA 3.0 (share-alike) | 0 | The only game source whose sizes match our cells exactly (bed 1×2, table 2×2, couch 2×1, shelf 2×1). About 50 usable entries across beds, tables, seats, lamps and shelving. |
| df-wiki | Dwarf Fortress Wiki: Furniture | GFDL & MIT, dual (one option share-alike) | 0 | The medieval object list: anvil, armor stand, barrel, bed, bin, bucket, cabinet, chain, chest, coffin, millstone, quern, statue, table, throne, traction bench, weapon rack, window. ~25 entries, all 1×1 in game, so we take names, not sizes. |
| cdda-furniture | CDDA `furniture_and_terrain/` JSON | CC BY-SA 3.0 (share-alike) | 0 | The deepest modern/post-apocalyptic list: 12 beds, 19 seats, 63 storage pieces, plumbing (bathtub, shower, sink, toilet, water heater), appliances (oven, fridge/cooling unit, washing machine, dryer, dishwasher, furnace), work tools (drill press, lathe, table saw, forge, anvil, kiln), counters and tables. ~150 household-usable names; no sizes (all one tile), flags give room membership. |
| cdda-mapgen | CDDA `mapgen/` JSON | CC BY-SA 3.0 (share-alike) | 0 | Room layout patterns for change 3: 98 house variants (bungalows, duplexes, two-story modern) place furniture by room type. |
| pz-pfans | PZFans wiki furniture category | unknown | 0 | ~327 modern furniture item names (only page 1 of 6 itemised openly). Names only. |
| pa-fandom | Prison Architect wiki Objects template | unknown | 0 | Institutional furniture names by use: cell (bed, bunk bed, toilet), office (office desk, chair, filing cabinet), canteen (dining tables, serving table), common room (TV, sofa, phone booth, arcade cabinet), infirmary (medical bed, morgue slab), laundry (machine, ironing board), chapel (altar, pews), classroom (school desk, blackboard). ~90 usable names. Read through the wiki's API (the HTML pages block fetching). |
| kenney-furniture | Kenney Furniture Kit | CC0 | 0 | Clean permissive-licence category names (table, chair, bed). The pack page itemises nothing; used for category naming only. |
| dnd-srd | D&D SRD 5.1, equipment tables | CC BY 4.0 | 0 | Medieval gear that doubles as furnishings: bedroll, blanket, bucket, barrel, basket, chest, ladder, lamp, lantern, candle, torch, tent, iron pot, mirror, sack. The PDF itself will not render in the fetch tool (unsupported content type); the item names were cross-checked against D&D Beyond's Free Rules equipment page (opened; no licence stated on that page). Facts only. |
| wikipedia-furniture | Wikipedia: List of furniture types | CC BY-SA 4.0 (share-alike) | 0 | ~160 cross-band names and the cleanest category taxonomy (seating single/multiple, sleeping, tables, storage, religious, entertainment). Good for aliases and category boundaries. |
| tabletop-2mt | 2-Minute Tabletop furniture assets | CC BY-NC 4.0 | 0 | Confirms medieval fantasy room sets exist as a category (300 assets); the tag page itemises no names. Names only, nothing copied. |

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

(filled by change 2)

## Purposes

(filled by change 3)

## Our own output

(filled by change 4)

## Gaps

(filled at the end)
