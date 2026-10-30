# Floors (Z-levels)

Upper floors, cellars and galleries on a game whose maps are one flat grid.

The engine has a single tile grid per scenario. Changing that would mean rewriting the
renderer, the map format and the editor. So this mod **emulates** extra floors:

1. **Build each extra floor as its own walled region** somewhere free on the map, the same
   size as the room it sits above. It can sit anywhere: off to one side, or in an empty field.
2. **Link the floors with stairs**, using the [portals](../portals/README.md) mod. Walks route
   up and down through them on their own.
3. **Declare the floor** so the game treats the two areas as stacked:

```json
"arpgMods": {
  "floors": [
    {"name": "Weary Hound upstairs", "area": "Weary Hound Gallery",
     "above": "Inn Common Room", "openings": ["Gallery well"]}
  ],
  "portals": [
    {"name": "Gallery stairs", "from": {"cell": [38, 38]}, "to": {"cell": [14, 35]}, "twoWay": true}
  ]
}
```

| Field | Meaning |
|---|---|
| `name` | For the GM and for warnings. |
| `area` | The region that *is* this floor. |
| `above` | The region directly below it. The two line up corner to corner: the area's top-left cell sits over the top-left cell of `above`. |
| `openings` | Regions inside the area with no floor, such as a stairwell, an atrium or a gallery over a hall. **Give each a wall and no doorways**, so it works as a railing and nobody walks into it. |
| `view` | Optional. How the room below looks through the openings: `{"blur": 0.6, "brightness": 0.8}` are the defaults. `blur` is the softening (0 turns it off; around 1 or more starts to look like frosted glass). `brightness` is a multiplier (1 means no darkening). |

Floors stack: a floor's `above` can itself be another floor's `area`.

## What it does

- **People on different floors notice each other only through an opening.** One must be within
  2 cells of the opening upstairs, and the other within 2 cells of the spot directly under it,
  within the usual 14-cell range. Everyone else on another floor doesn't count, even if the two
  areas sit next to each other on the flat map. Without this, the neighbours of a gallery built
  in a field would be "in your vicinity".
- **The GM is told the layout**, for example *"Weary Hound Gallery is the floor directly above
  Inn Common Room; openings to look down through: Gallery well"*. It's also told who can be seen
  through an opening right now: *"Gareth Stone: below, in Inn Common Room"*, or *"…: above, at
  Weary Hound Gallery"*.
- **Each opening shows the room below on screen,** slightly softened and darkened, as if at a distance. This uses an extra
  Phaser camera lined up with the opening, so it follows panning and zoom and shows the real,
  live room: people walking about, lighting, everything.

It runs after other perception mods (`order: 10`), so wall-aware perception can't block a view
through an opening.

## Checked in the game

On the Thornbury test map, a 16×6 gallery was placed in a field and declared above the
Weary Hound common room, with a 6×2 railed well.
- **Getting there:** the stairs portal took the player up.
- **The view below:** at the railing, the well showed the common room's stools and Gareth
  Stone. The first setting looked like frosted glass, so the default was eased to a slight
  softening and 20% darker.
- **Perception:**
  - Gareth, under the well, was seen.
  - Hal, by the door, wasn't.
  - The four villagers living next to the gallery on the flat map were no longer counted as
    nearby.
- **Routing:** Hal, sent to the gallery, routed via the stairs.

## Limits

- **You can't see up.** From below, nothing is drawn of the floor above. The GM is still told
  who's looking down.
- **Only one floor at a time.** You only see the floor directly below an opening, not two down.
- **No minimap integration.** The extra floor shows on the minimap where it sits on the flat
  map.
- **The game's own region naming** places the floor inside whatever region surrounds it on the
  flat map (here, Market Ward). The Storeys section tells the GM how to read that.
