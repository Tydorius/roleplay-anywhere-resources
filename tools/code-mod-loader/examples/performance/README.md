# Performance

Two easy wins whose payoff grows with map size. No settings.

## 1. Movement-grid cache

The game builds its whole movement grid from scratch for every small question. The grid is a
map-sized array plus a pass over every object. Even "is this one cell walkable?" or "may this
character take this step?" rebuilds it, for every character, every frame. On Thornbury that's
about **570 rebuilds a second**. The simulation is tied to the frame rate, much like physics
frames in other engines, so the cost grows with frame rate × characters × map area × objects.

A grid is never changed after it's built, so this mod reuses a recent one. It's rebuilt when:
- it's older than **0.1 s**, or
- the walls change (the game's `regionsRev`), or
- objects are added or removed (checked at most every 0.1 s).

Only the grid-building is cached. The simulation still steps every frame, so movement stays
smooth.

Two patches serve this. `nav-cache-get` and `nav-cache-put` let the grid's constructor return a
recent grid instead of building a new one.

The validity check runs on every request: wall revision, doorway count and object count. The
game's door-carving adds a doorway to a region and immediately tests a step through it, and a
grid from before the new door would wrongly say no.

**Wall memo** (patch `edge-memo`). Once grids were cached, the top cost became the grid's wall
test between two cells. It loops over every walled region on the map, and path searches call it
for each step they consider: about 18% of CPU on Thornbury. Each grid now remembers its answers.
They can't change, because a grid's walls are fixed when it's built and the cache drops grids
when walls or doorways change. The patch is inert unless this mod sets `__arpg.memoEdges`.

## 2. View culling

Phaser draws every object on the map every frame, whether or not it's on screen. On Thornbury
that's about 6,700 objects, including 870 name-plate Graphics, the expensive kind, while the
screen shows about 4% of the map. This mod tells the game's camera to skip anything well outside
the view, with 160 px of margin for labels and shadows:

- **Characters and objects** are tested by position.
- **Ground and wall tiles** are tested by bounds, measured once and cached, since they never
  move.
- **Full-map layers**, such as lighting, are always kept.

It re-checks every 10 frames, and immediately when the view jumps or zooms (a teleport, a load,
a god-mode pan). Anything the game itself had hidden from the camera is left alone.

## Measured

**On Thornbury, with the mod:**
- **Movement grids:** 10.6 built a second and 1,519.5 reused. Without the mod, every one of
  those would have been a full rebuild.
- **The game camera's drawing time:** about 6 ms a frame, down from about 20 ms.
- **CPU profile:** grid building disappeared from it. The wall test then topped it, hence the
  wall memo, which isn't measured in game yet.

**Culling, tested live before it became this mod,** in alternating runs:

| Main camera | Frame rate |
|---|---|
| Normal | 26.1, 26.6, 27.5 fps |
| Culled to view | 37.6, 33.4, 31.6 fps |

With culling, drawing costs about the same on a big map as on a small one, because only what's
on screen is drawn.

`__arpg.performance.stats()` reports grids built vs reused. `__arpg.performance.setCulling(false)`
turns culling off, for comparison.

## Not done (bigger jobs)

- **Baking the static ground** (3,600 image tiles on Thornbury) into a few large textures.
  It would need re-baking whenever the map changes.
- **True GPU instancing.** Phaser 3 already batches sprites that share a texture into one draw
  call; what's left is per-object work, which culling removes for anything off screen.
  Instancing proper would mean another engine version.
