# Lights

Gives each light source a kind, so it has its own colour, size and motion, and stops lamp light
from reaching objects and characters through walls. It works on existing scenarios with no
changes; scenarios can fine-tune it.

No bundle patch: it wraps one method on the live game scene.

## What the game already does

The game lights the map with Phaser's Light2D and its own soft shaders:
- Every object or carried item whose template has `light` > 0 gets a point light, brighter at
  night.
- Lamps cast wall shadows on the floor.
- Characters and objects get a drop shadow away from their strongest lamp.

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

The whole pass costs about 0.09 ms a frame on Thornbury (217 sprites, 22 lamps).

Limits:
- It tests the object's centre. A big object half round a corner is all-or-nothing.
- Wall sprites themselves aren't adjusted: the far face of a wall can still pick up a lamp's
  glow.

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
```

## How it hooks in

The game's frame does two things in order:
1. `syncEntities` sets every lamp's intensity and radius, and every sprite's tint.
2. `drawPointShadows` draws the lamps' wall shadows.

The mod wraps `drawPointShadows` on the scene instance, so its changes land between the two. The
wall shadows follow the flicker, and nothing compounds: a value the game wrote this frame is
taken as the new base. If a game update renames `drawPointShadows`, `entityLights`, `views` or
`losBlocked`, the mod simply never attaches and the game looks as it did.
