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
| `knownBy` | For a secret portal: the characters who know it and use it, by name. |

**An object pad must be something you can stand on.** Its template's `walkability` has to be
above 0: a rug, a trapdoor, a stair tile, a barrel at 0.2. An object with walkability 0 blocks
its cells, so nobody can step onto it. The mod warns about this in the game's DevTools console.

Names are matched without regard to case. A portal whose object or region isn't on the map is
skipped, with one console warning.

## How it behaves

- **Anyone who steps onto a `from` end goes through:** the player, NPCs and hostiles. Nothing
  else is needed. The game's own `teleport` moves them, so the player gets the normal transition,
  and the GM sees the usual "was teleported to …" event.
- **No bouncing.** Arrivals land beside the far end, not on it. Someone already standing on a
  pad has to step off and back on to use it again, and that includes a game loaded with someone
  standing on one.
- **Walks route through portals on their own.** That covers GM `MOVE_TO` and other beats,
  schedules, followers and hostiles chasing the player. A walk uses a portal (or a chain of
  them: floor 1 → 2 → 3) whenever that's shorter than walking. In testing, a grave-moth swarm the
  GM sent after the player followed them back through a two-way portal.
- **The GM is told** about every portal in a "Passages" prompt section, for example
  `- Cellar stairs: Kitchen trapdoor in Inn Kitchen <-> Cellar ladder`. It never needs to
  pathfind itself. It writes `MOVE_TO "Cellar"`, and characters walk through.
- Characters attached to another (`attach`) ride along instead of using pads.

## Secret doors and passages

Until a secret portal is discovered:

- **Only the player and its `knownBy` characters trigger it.** Anyone else crosses the pad as
  ordinary floor.
- **Only `knownBy` characters route walks through it.** The player's own click-to-walk ignores
  it, so the route doesn't give it away.
- **The GM sees it in a separate "Secret passages" list**, with who knows it. It's told to hint
  at it through play and not to state it outright. The GM can still send a `knownBy` character
  through it, for example a smuggler slipping away.

It's **discovered** when the player goes through it, or when the GM issues
`{"call": "portal_reveal", "name": "Smugglers' tunnel"}`. The GM is told to do that when the
player finds it by searching or is shown it. From then on it's an ordinary passage for everyone.
The discovered state is saved with the game (`arpgMods.portalState`).

## Cost

The game's own search for a long walk takes about 25 ms on a 96×96 map. Checking portal routes
adds about 3 ms to that, and nothing measurable to short walks. Routes between portal ends are
cached for 2 seconds.

## Ideas not built yet

- A per-portal `"who": "routed"` option. The pad would then fire only for characters whose walk
  uses it, plus the player, so passers-by in a busy room don't fall through.
- A per-portal option to keep hostiles out (a warded door).
- Locked portals tied to an item or a variable.
