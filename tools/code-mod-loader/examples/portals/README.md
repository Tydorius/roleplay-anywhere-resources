# Portals

Doors, stairs, trapdoors and teleporters that link parts of the map the grid doesn't connect:
separate floors built side by side, a cellar placed off to one side of the map, a magic mirror.
A scenario carries them in its own `scenario.json`.

## Format

```json
"arpgMods": {
  "portals": [
    {"name": "Cellar stairs", "from": {"object": "Kitchen trapdoor"}, "to": {"object": "Cellar ladder"}, "twoWay": true},
    {"name": "Ferry", "from": {"region": "North Dock"}, "to": {"region": "South Dock"}, "twoWay": true},
    {"name": "Mirror", "from": {"cell": [10, 4]}, "to": {"cell": [80, 70]}},
    {"name": "Smugglers' tunnel", "from": {"object": "Straw pallet 8"}, "to": {"cell": [62, 12]},
     "twoWay": true, "secret": true, "knownBy": ["Marrow Jack", "Bran Hollyoak"]}
  ]
}
```

| Field | Meaning |
|---|---|
| `name` | What the GM calls it. |
| `from` | Where you step to use it: `{"object": "<object name>"}`, `{"region": "<region name>"}` or `{"cell": [x, y]}`. |
| `to` | Where you come out. An object or cell: on a free cell beside it. A region: anywhere inside it. |
| `twoWay` | `true` also makes the `to` end lead back to the `from` end. |
| `enabled` | `false` turns the portal off. |
| `secret` | `true` makes it a secret door or passage until it's discovered. See below. |
| `knownBy` | The characters who know it from the start, by name. Without this list, an ordinary portal is common knowledge. With it, only they (and the player) know it. |

Optional settings for every portal in the scenario go in `arpgMods.portalSettings`:

| Field | Meaning |
|---|---|
| `stealthWords` | Extra words that mean "sneaking" in this scenario, such as a skill or spell name like `"Shadowstep"`. See "Who knows what". |

**An object pad must be something you can stand on.** Its template's `walkability` has to be
above 0: a rug, a trapdoor, a stair tile, a barrel at 0.2. An object with walkability 0 blocks
its cells, so nobody can step onto it. The mod warns about this in the game's DevTools console.

Names are matched without regard to case. A portal whose object or region isn't on the map is
skipped, with one console warning.

## How it behaves

- **The player goes through any pad they step onto.** The game's own `teleport` moves them, so
  they get the normal transition, and the GM sees the usual "was teleported to …" event.
- **NPCs go through only when their walk was planned through the portal.** That covers GM
  `MOVE_TO` and other beats, schedules, followers and hostiles chasing the player. A character
  wandering across a pad treats it as ordinary floor. (In the first play-test, a moth swarm on
  its leisure schedule drifted onto the 2×2 Sunken tomb and fell through to the inn. This rule
  stops that.)
- **No bouncing.** Arrivals land beside the far end, not on it. Someone already standing on a
  pad has to step off and back on to use it again, and that includes a game loaded with someone
  standing on one.
- **Walks take a portal only if the walker knows it,** and only when that's shorter than walking.
  Chains of portals (floor 1 → 2 → 3) work. In testing, a grave-moth swarm the GM sent after the
  player followed them back through a two-way portal.
- **The GM is told** about every portal in a "Passages" prompt section, for example
  `- Cellar stairs: Kitchen trapdoor in Inn Kitchen <-> Cellar ladder`. It's told to send
  people through with `MOVE_TO` and never with its own `teleport`, and never to send anyone back
  through a one-way (`-> (one way)`) passage. In the first play-test the GM narrated "climbing
  back up" a one-way chute with a teleport. The new wording is meant to stop that, but it hasn't
  been re-tested.
- Characters attached to another (`attach`) ride along instead of using pads.

## Who knows what

Knowledge is tracked per character for **secret portals** and for **portals with a `knownBy`
list**. Ordinary portals without a list are common knowledge.

| Who | Learns it how |
|---|---|
| `knownBy` characters | Know it from the start. |
| The player | Ordinary portal: always. Secret portal: by stepping onto it, or through the GM's `{"call": "portal_reveal", "name": "Smugglers' tunnel"}`. Until then, the player's own click-to-walk ignores it, so the route doesn't give it away. |
| Onlookers | NPCs within 6 cells of either end, in the same room, when someone uses it openly. Each gets a memory such as *"Saw Wren Ashdown slip through a hidden way at Straw pallet 8 in Woodcutter's Cabin and vanish."* The GM sees that memory whenever the onlooker is near the player, so gossip can come up in play. |
| Anyone else | Only when the GM issues `{"call": "portal_tell", "name": "Smugglers' tunnel", "target": "Alys Sedge"}` (gossip, a bribe, a confession). They get a memory of it too. |

Knowledge never spreads by itself. The barmaid who saw you use the trapdoor knows it, but the
skeletons in the keep don't.

**Nobody sees a sneaking traveller.** The engine has no stealth state of its own. Scenarios
define their own skills: Thornbury and College of Wizardry have "Stealth", UC Berkeley doesn't.
So the mod reads stealth from words, which works in any scenario. A traveller counts as sneaking
when any of these hold:

- Their most recent action in the last 15 game minutes was stealthy, and its roll didn't fail.
  The action counts as stealthy when its text, or the skill the GM rolled, contains a stealth
  word: *stealth, sneak, hide, conceal, unseen, invisible, creep, skulk, prowl, lurk,
  camouflage, tiptoe, silently*. This applies to the player only.
- Their current action contains a stealth word, for example "sneaking along the wall".
- One of their status effects does, for example "Hidden in the shadows".

A scenario with its own stealth vocabulary can add words through `portalSettings.stealthWords`.

**Secret portals** are listed to the GM in a separate "Secret passages" section until the player
knows them, with who knows each one. The GM is told to hint and not to state them outright.
After the player learns one, it moves to the ordinary Passages list. It still shows who knows
it, because it isn't common knowledge.

All of this is saved with the game in `arpgMods.portalState`: `discovered` for the player and
`known` for characters.

## Cost

The game's own search for a long walk takes about 25 ms on a 96×96 map. Checking portal routes
adds about 3 ms to that, and nothing measurable to short walks. Routes between portal ends are
cached for 2 seconds.

## Ideas not built yet

- Onlookers with a perception skill ("Observation") spotting even a sneaking traveller.
- A per-portal option to keep hostiles out (a warded door).
- Locked portals tied to an item or a variable.
