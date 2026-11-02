# Brief 012 feasibility: compound structures

Each answer below is proven by a hand-written builder spec in
`tests/test_compound_feasibility.py`, run through the vendored builder
(`worldgen/vendor/build_scenario.py`) and validator in-process. The specs
mirror the arrangement the compound layout builds, so the answers are about
the real pipeline, not a sketch.

## 1. Doors between parts — an unwalled compound region holding the parts

The builder auto-connects walled regions whose edges are 0 or 1 apart when
they share a parent (the smallest strictly larger containing region), with a
facing pair of door cells when each part keeps its own wall line. Both
candidates work at the builder level:

- parts as sibling buildings directly in the zone (parent = the zone
  region), and
- parts held by an unwalled compound region (parent = that region).

Both get the door pair on the shared wall, recorded on the part and the room
behind it, and both build and validate with zero errors.

**Pick: the unwalled compound region.** Three reasons:

1. The courtyard gets its own named region (the compound's grounds), which
   the layout can tint with the zone's ground and which the checks can walk.
2. Compound parts and the zone's other buildings stop auto-connecting when
   they touch: with the zone as parent, a cottage pressed against a tower
   wall during packing would grow a door into the castle. The compound
   region bounds the auto-connect family to the compound's own parts.
3. The compound region is one rect the zone places as a block, which is
   exactly the "one block" rule the brief asks for.

The door leads into rooms on both sides when the room behind the shared
wall spans the door cell. The builder puts the door at the middle of the
parts' overlap on the shared edge; a 3-thick wall corridor meets a part
along 3 rows/cols, so the door sits at the corridor's middle line, one cell
in from the part's perimeter edge. That cell is on the outermost room's
wall, and the room layouts cut full-width/full-height strips, so the cell
one further in is that room's interior — the door opens straight into the
room. `test_touching_parts_auto_connect_both_ways` asserts this on both
sides of both end doors, including the two doors a gate part carries
(outside entrance plus courtyard door).

## 2. Thin walkable walls — 1-cell interior works

A walled corridor with outer width 3 (a 1-cell interior) builds, validates,
is reached, and is walked end to end: `test_one_cell_interior_builds_...`
joins two parts with an 11-long corridor and asserts every walkway cell is
in the builder's flood, and that the corridor's ring blocks everywhere
except its two end doors. A 2-cell interior (outer width 4) works too
(`test_two_cell_interior_also_works`), so either is available.

`MIN_SIDE = 4` never applies: it floors room *layouts inside a building*;
wall corridors are laid out as single-room walled regions directly by the
compound layout, not through `layout_rooms`.

**Pick: the 1-cell interior (outer width 3).** It reads as a wall on the
map, leaves the courtyard as large as possible, and the wall walk upstairs
is exactly the 1-wide parapet walk the brief describes.

## 3. Solid walls — a walkability-0 object strip works

A curtain wall as 1-thick walkability-0 object strips (one object per run,
the World's Edge slab trick without the sprite and without
`passableAtBuild`): builds and validates clean, blocks every cell it covers
in the builder's walk, never claims a wall cell of the walled parts it runs
between (they sit adjacent, not overlapping), and the parts behind it stay
reachable through their own doors. `test_strips_block_and_parts_stay_...`
boxes the gap between two parts shut and walks both parts' rooms from
outside; a strip overlapping any part's wall would have been a builder
`_claim` error, and there are none.

No passability trick is needed: unlike the boundary slab (which seals
storeys the flat walk must reach through their build-time doors), a solid
compound wall only ever seals ground, and the gate part provides the way
through, so the builder's walk passes around it.

## 4. Upper storeys that touch — connect at build; the seal needs narrowing

Two storeys placed touching in the east band (same size as their ground
regions, same relative arrangement, one cell apart) auto-connect: their
shared parent is the boundary region ("The Edge of the World" spans the
strip and the band), so the builder joins them with a facing-pair door on
the shared wall — the wall-walk door. `test_touching_storeys_auto_connect_...`
asserts the door cells on both storeys, and
`test_each_storey_maps_to_its_own_building` asserts the floors `arpgMods`
payload still maps each storey area to its own ground building.

The sealed-storey machinery is the one gap. `_seal_floors` strips **every**
opening on a storey's border, so it takes the build-time fiction doors
(their job) and the shared wall-walk door with them (a problem: upstairs,
the towers would never join along the walk). Same for the matching checks
(`checks._floors_checks` and the built-scenario ring check in
`check_scenario_mods`), which flag any border opening.

`test_seal_strips_the_fiction_doors` pins today's behaviour, including the
stripped shared door. **Change 4 narrows the seal and those checks to the
fiction doors**: an opening on a storey's border survives when the cell, or
a 4-neighbour of it, is an opening on another storey's border — that is a
real door between two storeys and ships; everything else on the border
(the fiction doors opening onto the slab) is sealed away as today. The
test's last two assertions flip when that lands.

## What the answers pick for the layout

- Parts and wall corridors nest under one unwalled compound region; the
  compound region is the block the zone places.
- Walkable walls are 3-wide single-room corridors; their end doors come
  from the builder's auto-connect, which the room layouts guarantee open
  into rooms.
- Solid walls are 1-thick walkability-0 object strips, one object per run,
  between the parts on the perimeter line.
- Compound storeys sit in the floors band in the compound's ground
  arrangement; the wall walk above a walkable wall appears when both parts
  it joins have a storey 2, and the seal keeps the inter-storey doors.
