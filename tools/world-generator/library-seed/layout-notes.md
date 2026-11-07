# Layout notes (draft)

Short factual notes on how the surveyed sources arrange each room purpose, in our own words.
Facts and patterns only; no source text or ASCII maps are reproduced. Source ids refer to
`sources.json`.

Caveat that applies throughout: CDDA's house mapgen resolves its furniture glyphs through
external palette files we did not open, so what we take from `cdda-mapgen` is the positional
pattern (furniture flush against walls, clusters in corners, runs along one wall, centres kept
clear), not the identity of every glyph. Prison Architect's item-per-room pairings below come
from its wiki's object lists and the room-requirements snippets quoted in search results, not
from a page we could open directly.

## bedroom

- Beds stand flush against a wall, and shared bedrooms line several beds along one wall.
  Room centres stay clear. [cdda-mapgen]
- A cell is furnished with just a bed and a toilet, both against walls. [pa-fandom]
- The bedroom set in the sources is bed, wardrobe or dresser, a small side table, and a
  light. [cdda-furniture, rimworld-wiki]

## kitchen

- Counters, stove and fridge form an L-shaped cluster that wraps a corner, with a straight
  run along one wall behind it. [cdda-mapgen]
- The working set is cooker, fridge and sink, all against walls, with the table and seats
  kept out of the appliance run. [pa-fandom]

## dining

- Dining tables are set apart from the serving counter; the counter stands against a wall
  and the tables fill the middle in a regular grid. [pa-fandom]
- Sideboards and display cabinets stand against the wall behind or beside the table, never
  in the walking area. [wikipedia-furniture]

## common_room

- The multi-seat piece sits centred on one wall with single seats near the corners;
  entertainment pieces face the seating. [cdda-mapgen]
- Common rooms pair a screen or game machine with seating; large rooms repeat the
  seating group. [pa-fandom]

## shop

- The counter sits between the door and the stock, with display shelves along the walls
  and racks beside the counter. [cdda-furniture, pa-fandom]
- Refrigerated or secured goods get their own unit behind or beside the counter. [pa-fandom]

## workshop

- The workbench stands against a wall with tool storage (rack or cabinet) on the same wall
  or directly behind it; heavy machines occupy the far end. [cdda-furniture]
- Workshop machinery in the sources is a set of separate single pieces, so layouts slot
  each machine individually rather than as one combined station. [cdda-furniture]

## storage

- Shelving stands in rows with an aisle; heavy and stacked goods fill a corner block. [cdda-mapgen]
- Bins and small containers cluster at the ends of the shelving rows. [cdda-furniture]

## office

- The desk faces into the room from against a wall or window wall, with the filing cabinet
  and shelves within reach on the same wall. [pa-fandom]
- Office sets in the sources pair the desk with a dedicated chair and cabinet; extras are a
  coat rack, plant and drinks machine by the door. [pa-fandom]

## washroom

- Toilet and sinks stand in a line against one wall; the tub or shower occupies the far
  corner or the opposite wall. [cdda-mapgen]
- The set is toilet, sink and bath or shower, all wall-hugging. [cdda-furniture]

## dormitory

- Bunks stand in rows along the walls with a footlocker or locker beside each bed. [pa-fandom]
- CDDA's shared sleeping furniture goes up to a triple berth, one tile wide, meant to be
  lined up in rows. [cdda-furniture]

## forge

- Forge, anvil and bellows are separate pieces in the sources; the forge goes against the
  wall, the anvil beside it, the fuel and quench water within a step. [cdda-furniture]

## chapel

- The altar stands at the far end from the door; pews, long one-tile-deep benches, sit in
  rows facing it. [pa-fandom]
- Candles or torches line the side walls. [rimworld-wiki]

## classroom

- The board hangs on the wall farthest from the door; school desks, one tile each, are
  written to be repeated, which reads as rows facing the board. [pa-fandom, rimworld-wiki]

## ward

- Hospital beds stand in a row with a privacy curtain between them; the medicine cabinet
  and washing point sit against the wall behind the beds. [cdda-furniture]

## cell

- Bed and toilet only, both against walls, with the bed as far from the door as the cell
  allows. [pa-fandom]

## bridge

- Consoles stand against the outer walls facing inward; the flight seat faces the main
  console. [cdda-furniture]

## laboratory

- Lab benches run along the walls, with the fume hood at the end of a bench run and the
  scanner or microscope pieces against a side wall. [cdda-furniture]

## library

- Bookcases stand shoulder to shoulder along every wall; reading tables with chairs sit
  by the window side. [wikipedia-furniture, df-wiki]

## laundry

- Machines stand in a row against one wall with the basin at the end of the row; baskets
  sit beside the machines. [pa-fandom]

## guardroom

- Lockers line one wall with the weapon rack beside them; a table with chairs fills the
  middle for briefings. [df-wiki, pa-fandom]

## gym

- Machines and benches stand in rows facing one direction, with the weight racks against
  the wall behind. [pa-fandom, cdda-furniture]

## greenhouse

- The hydroponics basin is the single growing unit in the sources, written to be repeated,
  which reads as a grid of basins with an aisle. [rimworld-wiki]
