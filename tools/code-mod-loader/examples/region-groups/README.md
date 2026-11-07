# Region groups (shapes beyond rectangles)

The game's regions are **rectangles only**. A region is a `position` plus a `size`, and every
"is this cell in it?" check is a rectangle test. This mod lets several rectangles that share a
name act as **one region**, so you can build:

- **A forest wrapped round a village,** as four strips all named "The Forest".
- **An L-shaped house,** as two walled rectangles named "Manor".
- **A U-shaped hall round a courtyard,** as three walled rectangles.

## How pieces join

Rectangles with the **same name** (ignoring case) that **touch or overlap** form one region.
Touching means sharing an edge or a corner. Joining is transitive, so the north and south forest
strips are one region through the side strips.

Same-name rectangles that don't touch stay separate, so two "Bedroom"s in different houses
aren't merged. There are no settings.

## What changes

| | The game alone | With this mod |
|---|---|---|
| Where you are ("you're in The Forest") | ✅ already works | unchanged |
| `MOVE_TO "The Forest"`, schedules, teleports | Always the **first** piece in the file | The piece **nearest** whoever is moving |
| Arriving | Only that first piece counts | **Any** piece counts |
| The GM's full detail on people "in the same space" | Each walled piece is a separate room | Walled pieces are **one room** |
| Wall-aware perception and portal onlookers | Separate rooms | One room |
| The GM's region list | The name once per piece | The name once, listing everyone in any piece |

## Walls between walled pieces

The game draws a wall along each walled rectangle's whole border. For an L-shaped house, list
the cells of the **shared edge as openings on both pieces**, so no wall runs through the middle
of the room. Each piece lists its own border cells on that edge:

```json
{"name": "Tithe Barn", "wall": "wood", "position": [70, 34], "size": [10, 4],
 "openings": [[74, 34], [70, 37], [71, 37], [72, 37], [73, 37]]},
{"name": "Tithe Barn", "wall": "wood", "position": [70, 38], "size": [4, 5],
 "openings": [[70, 38], [71, 38], [72, 38], [73, 38]]}
```

Here `[74, 34]` is the front door. The rest is the joint between the hall and the wing.

## Patches

Three small, content-anchored patches, each inert without this mod:

- **`region-destination`:** where a mover is sent inside a region.
- **`region-arrival`:** "is this cell in that region?".
- **`region-same-room`:** the GM prompt's "same space as the player" test.

The game's other uses of rooms, such as shadows and the interior view, still see the real
rectangles.
