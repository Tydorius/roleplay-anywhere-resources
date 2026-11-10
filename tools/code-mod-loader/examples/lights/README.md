# Lights

Gives each light source a kind, so it has its own colour, size and motion, and stops lamp light
from reaching objects and characters through walls. It works on existing scenarios with no
changes; scenarios can fine-tune it.

No bundle patch: it wraps one method on the live game scene.

**Game version:** Anywhere RPG 1.0 (Steam alpha build 26557354), with code-mod loader 2.0.0. The
0.18 version is on the [`0.18` branch](https://github.com/Tydorius/roleplay-anywhere-resources/tree/0.18).

## What the game already does

The game lights the map with Phaser's Light2D and its own soft shaders:
- Every object, equipped item or item an NPC carries whose template has `light` > 0 gets a point light, brighter at
  night.
- Lamps cast wall shadows on the floor.
- Characters and objects get a drop shadow away from their strongest lamp.
- Water and other liquids have their own light shader, which takes each lamp's colour and
  flicker as they are. The mod leaves water alone.

But every lamp is the same orange (`#FFC078`), with one radius (the *Lamp reach* setting), and
none of them move. The global look (night ambient, night hue, moon strength, lamp brightness and
reach) is in **Options → Graphics**.

## Kinds

| Kind | Looks like | Size | Motion | Particles |
|------|------------|------|--------|-----------|
| `candle` | warm amber | 0.6× | small fast flicker | none |
| `torch` | orange | 1.0× | strong flicker | embers |
| `fire` | deep orange | 1.3× | big slow flicker | fire embers |
| `ember` | red-orange | 0.75× | slow glow | none |
| `lantern` | soft gold | 1.0× | faint flicker | none |
| `electric` | warm white | 1.15× | steady | none |
| `neon` | pink | 0.9× | steady, drops out now and then | none |
| `screen` | cool blue | 0.55× | faint shimmer | none |
| `magic` | pale blue | 1.0× | slow pulse | drifting motes |
| `plain` | the game's own | 1.0× | steady | none |

Size and brightness multiply the game's own values, so the Options sliders still work.

### Automatic classification

Light sources a scenario doesn't list are classified by their template's name and description.
A word in the name counts twice as much as one in the description:

| Words | Kind |
|-------|------|
| hearth, brazier, campfire, oven | fire |
| candle | candle |
| lantern, oil lamp | lantern |
| bulb, electric, flashlight | electric |
| monitor, workstation | screen |
| arcane, mana, rune, crystal, bioluminescent | magic |

A bare "lamp" or "lamppost" leans lantern, but its description decides:
- "glowing warm bulb" → electric
- "magical blue glow" → magic

A colour word counts only next to a light word. So "violet flames", "ghostly blue light",
"glowing blue crystal" and "neon-green moss" recolour, but "black candle" and "white background"
don't. The test suite checks every light source in Thornbury, College of Wizardry and UC
Berkeley.

## Walls block lamp light on objects and characters

The game's lamp shadows are a dark layer drawn *under* everything that stands. They shade the
floor behind a wall correctly. But the light shader lights any object or character within a
lamp's reach, wall or not, so a bed in the next room glowed from the kitchen hearth.

Each frame, every object or character on screen near a lamp is tested with the game's own wall
line-of-sight check (`losBlocked`, the one its drop shadows use). When a wall hides a lamp from
it, its tint is scaled per colour channel by (light it should get) ÷ (light the shader gives it).
That takes out just that lamp's share and colour, and keeps the ambient light, the moonlight
and any lamps it can see. Answers are cached until the walls change.

Sprites that 1.0 has culled (off screen, or inside another entity) are skipped.

The whole mod costs about 0.3 ms a frame on 1.0, measured at night in Downpour Block (151 lamps,
115 sprites on screen, 23 of them darkened by a wall). On 0.18 it was 0.09 ms on Thornbury (22
lamps).

Limits:
- It tests the object's centre. A big object half round a corner is all-or-nothing.
- Wall sprites themselves aren't adjusted: the far face of a wall can still pick up a lamp's
  glow.

## Lamps and floors

1.0's floors and cellars are planes: separate areas of the same grid, laid out past the main
map's edge, at least 24 cells (768 px) apart. Phaser's light shader doesn't know about planes, so
a lamp would light anything within its reach, on any plane. Two rules keep each plane's light
its own:
- A lamp the mod enlarges never reaches more than 736 px, short of the next plane. (If you set
  *Lamp reach* above that yourself, the game's own reach is left alone.)
- A lamp on another plane counts as hidden, like a lamp behind a wall, so its light is taken off
  that plane's objects and characters.

The floor itself can't be adjusted that way: with *Lamp reach* above 768 px, a lamp on one plane
can still tint the ground at the edge of the next.

## Scenario settings (optional)

```json
"arpgMods": {
  "lights": {
    "auto": true,
    "particles": true,
    "occlusion": true,
    "templates": {
      "otpl_hearth": "fire",
      "Iron Lantern": { "kind": "lantern", "color": "#6fa8ff", "radius": 1.2,
                        "intensity": 1.0, "flicker": 0.1, "particles": "motes" }
    }
  }
}
```

- `templates` keys are template ids or exact template names. A value is a kind name, or an object
  whose fields override the kind's preset.
- `flicker` is how far the light swings (0 = steady). `particles` is `"fire"`, `"embers"`,
  `"motes"` or `false`.
- `auto: false` leaves unlisted sources looking as they do in the plain game.
- `"lights": false` turns the mod off for that scenario.

## Debugging

```js
__arpg.lights.report()          // each lit entity: kind, colour, particles
__arpg.lights.setEnabled(false) // compare with the plain game; true to turn it back on
__arpg.lights.classify({ name: 'Lamppost', physicalDescription: 'glowing warm bulb' })
__arpg.lights.stats()           // frames, lamps, and msPerFrame: the mod's own time per frame
__arpg.lights.resetStats()      // start timing afresh
```

## How it hooks in

The game's frame does two things in order:
1. `syncEntities` sets every lamp's intensity and radius, and every sprite's tint. It does this
   every frame, for every lamp.
2. `drawPointShadows` draws the lamps' wall shadows.

1.0 redraws the lamp shadows only when something changed: it keeps a signature of every lamp's
position, radius and intensity (`pointShadowSig`). A full redraw costs about 6.7 ms with 151
lamps, so a lamp that flickers before the shadows are drawn would cost that every frame.

So the mod wraps `drawPointShadows` on the scene instance and works in two steps around it:
1. Before the shadows: each lamp gets its kind's colour and steady size and brightness. The
   signature doesn't change from frame to frame, and the shadows aren't redrawn (in the
   Downpour Block check, 1 redraw in 180 frames, caused by a wall change).
2. After the shadows: lamps on screen flicker or pulse, particles follow their lamp, and walls
   and floors take lamp light off objects and characters. Lamps off screen stay steady.

The shadows therefore hold still while the light flickers. Nothing compounds: a value the game
wrote this frame is taken as the new base. Water needs nothing: 1.0 lights liquids with its own
shader, which reads the same lamps. If a game update renames `drawPointShadows`,
`entityLights`, `views` or `losBlocked`, the mod simply never attaches and the game looks as it
did.
