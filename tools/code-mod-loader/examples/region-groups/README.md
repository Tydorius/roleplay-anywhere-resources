# Region groups (shapes beyond rectangles)

The game's regions are **rectangles only**. A region is a `position` plus a `size`, and every
"is this cell in it?" check is a rectangle test. This mod lets several rectangles that share a
name act as **one region**, so you can build:

- **A forest wrapped round a village,** as four strips all named "The Forest".
- **An L-shaped house,** as two walled rectangles named "Manor".
- **A U-shaped hall round a courtyard,** as three walled rectangles.

For Anywhere RPG 1.0.

## How pieces join

Rectangles with the **same name** (ignoring case) that **touch or overlap** form one region.
Touching means sharing an edge or a corner. Joining is transitive, so the north and south forest
strips are one region through the side strips.

Same-name rectangles that don't touch stay separate, so two "Bedroom"s in different houses
aren't merged. There are no settings.

## Floors

1.0's floors and cellars are pocket regions placed off the main map, and a region on a floor
lies inside its pocket's rectangle. A group never spans two floors: same-name pieces that
touch across the main map and a floor stay separate, and a pocket region named like a touching
main-map region doesn't join it either. A mover on another floor is sent to the region the
game picked, not to a "nearest" piece measured across planes — 1.0 walks it there through its
stairs.

## Natural shapes

The world generator's "natural" regions carry `shape: "organic"` (only unwalled, non-floor
regions at least 5×5; walled regions and floors are always plain rectangles), and the game
treats cells of the rectangle outside a smooth blob as outside the region. A natural-shaped
piece joins a group **by its rectangle**, like any piece: blobs are inset from their
rectangles, so strips that overlap a little as rectangles rarely touch as blobs, and joining
by blob would split a forest wrapped round a village. Arriving still follows the blob, because
the patched arrival test asks the game which region a cell is in, and the game answers with
the blob.

## What changes

| | The game alone | With this mod |
|---|---|---|
| Where you are ("you're in The Forest") | ✅ already works | unchanged |
| `MOVE_TO "The Forest"`, schedules, teleports | Always the **first** piece in the file | The piece **nearest** whoever is moving |
| Arriving | Only that first piece counts | **Any** piece counts |
| The GM's full detail on people "in the same space" | Each walled piece is a separate room | Walled pieces are **one room** |
| Wall-aware perception | Separate rooms | One room |
| The GM's region list | The name once per piece | The name once, listing everyone in any piece |

## Walls between walled pieces

The game draws a wall along each walled rectangle's whole border. For an L-shaped house, list
the cells of the **shared edge as openings on both pieces**, so no wall runs through the middle
of the room. An opening is `[x, y, side]`, the side (`"n"`, `"s"`, `"e"` or `"w"`) pointing
from the cell towards the outside. Each piece lists its own border cells on that edge:

```json
{"name": "Tithe Barn", "wall": "wood", "position": [70, 34], "size": [10, 4],
 "openings": [[74, 34, "s"], [70, 37, "n"], [71, 37, "n"], [72, 37, "n"], [73, 37, "n"]]},
{"name": "Tithe Barn", "wall": "wood", "position": [70, 38], "size": [4, 5],
 "openings": [[70, 38, "s"], [71, 38, "s"], [72, 38, "s"], [73, 38, "s"]]}
```

Here `[74, 34, "s"]` is the front door. The rest is the joint between the hall and the wing.
The side matters: on import a two-element `[x, y]` opens every outer side of that cell, so a
corner cell of the joint would open two walls, one of them to the outside. Give each joint
cell its side.

## Doors between pieces (1.0)

1.0 hangs a door object on **every** doorway when it builds a world, so the joint between
pieces would get a row of shut doors across the middle of the room — they also block 1.0's
own stealth line of sight. The mod takes those doors off as the world is built (the pieces
are one room) and keeps every other door: front doors, doors to rooms nested inside a piece,
doors between pieces of different groups.

Two known limits:

- A save started before this mod was installed keeps its joint doors. Remove them in god
  mode, or start a new game.
- If the GM later changes a piece's walls (`wall_change`), 1.0 hangs doors on that piece's
  doorways again.

## Patches

Three small, content-anchored patches, each inert without this mod:

- **`region-destination`:** where a mover is sent inside a region.
- **`region-arrival`:** "is this cell in that region?".
- **`region-same-room`:** the GM prompt's "same space as the player" test.

The game's other uses of rooms, such as shadows and the interior view, still see the real
rectangles.
