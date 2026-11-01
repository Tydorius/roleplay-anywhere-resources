# Wall-aware perception

Stops the player and NPCs from noticing each other through walls.

## The problem

The game decides "within notice range" by **straight-line distance alone**: 14 cells to come
into range, 16 to drop out. There's no line-of-sight check anywhere in the game. That one test
drives several things:

- **"X is now in player vicinity" events.** For a hostile they're marked urgent and wake the GM
  at once. That's how a skeleton five cells away behind a long wall "noticed" you: the GM was
  told it was in your vicinity, and nothing mentioned the wall.
- **Which NPC actions, speech and item hand-overs reach the GM** as events.
- **The GM prompt's lists** of nearby busy characters and nearby objects.

The game's other perception checks already handle walls:
- **Hostile lock-on**, a monster starting to chase you on its own, needs a walking path of 8
  steps or less.
- **The GM's full detail on a character** needs the same walled room.

## The rule with this mod

When the player is one of the two, they notice each other only if they're within that same
straight-line range **and** at least one of these holds:

- **They're in the same walled room**, or both are outdoors. Unwalled areas, such as a camp
  inside a forest, don't block anything.
- **One could walk to the other within the range,** counting walls and doorways but not
  furniture. That's the same kind of walking test as the game's hostile lock-on. An open
  doorway nearby still lets people notice each other; a long wall doesn't.

Checks between two NPCs, or between NPCs and objects, are left as the game does them.

## Checked in the game

From the Inn Common Room in the Thornbury test save:
- **Still noticed:**
  - Alys and Hal, in the same room.
  - Margery in the kitchen, through the doorway.
  - Tobias, Gareth and Linnet, just outside the front door.
- **No longer noticed:**
  - Nell, in the Farmhouse Byre 13 cells away behind walls.
  - Rosamund, while inside the walled Market Hall Stalls.
  - A few objects in walled-off rooms.

Once Rosamund walked outside, 12 steps away through the front door, she came back into range,
as she should.

## Cost

Each answer is one capped walking search (at most 15 steps). Answers are cached by cell pair
until the map's regions change (the game's `regionsRev`), so after the first few seconds the
checks are close to free. A cold check of every entity on the 96×96 Thornbury map took 5 ms,
and 1.6 ms warm.

Needs the loader's `perception` patch, which also hands mods the game's own path search.
