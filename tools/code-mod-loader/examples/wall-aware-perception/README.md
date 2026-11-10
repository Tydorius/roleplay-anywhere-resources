# Wall-aware perception

Stops the player and NPCs from noticing each other through walls. For Anywhere RPG 1.0.

## What 1.0 already does

1.0's own stealth handles much of seeing already. Its line-of-sight test walks a line that
walls and shut doors stop, while open doorways, bars and gates don't; vision cones, light
level and a sneaking state decide who spots whom. Floors and cellars are separate planes,
reached by stairs, ladders and hatches. And the GM prompt's "Characters in same space as
player" list already needs both to be in the same walled room.

## The problem that remains

Several things still measure **straight-line distance alone**, with no walls in between:

- **"X is now in player vicinity" events** (the 14-cell notice range). For a hostile that has
  noticed the player they're urgent, and they wake the GM at once.
- **Which NPC actions and item hand-overs reach the GM** as events.
- **The objects listed in the GM prompt**: in the same space, elsewhere nearby, and the
  "Strewn about" scenery.
- **Who counts as in the same space as the player when both are outdoors.**

So a skeleton five cells away behind a long wall still "noticed" you: the GM was told it was
in your vicinity, and nothing mentioned the wall.

## The rule with this mod

Two characters within that same range notice each other only if they're on the same floor
**and** one of these holds:

- **They're in the same walled room**, or in pieces of one region-groups room. Then they're
  noticed, with no line to walk.
- **Otherwise 1.0 stealth's own line-of-sight test decides.** Walls, shut doors and drawn
  curtains block; open doorways, bars and gates don't. Both outdoors is no exception: a house
  between them blocks.

A floor or cellar away is out of range entirely, since nobody notices anyone across planes.
The rule holds for every pair, not just ones involving the player.

## Sneaking

Sneaking isn't involved: this answers "can the player perceive X", and 1.0's stealth already
decides who has noticed whom.

## Cost

One line-of-sight test per pair per simulation step; answers are reused within the step and
across the game's prompt rebuilds.

## Checked in the game

Not yet checked on 1.0.

Needs the loader's `perception`, `line-of-sight` and `sight-blockers` patches.
