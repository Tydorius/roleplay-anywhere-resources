# Secret passages

A door in a wall can be secret. Until a character knows it, it's a wall to them: they can't
walk through it and it doesn't swing open for them. Until the player knows it, it's drawn as
solid wall, can't be hovered or clicked, and is left out of the GM's doorway lines. Knowledge
is per character: some know a secret door from the start, the player can find it by standing
near it, anyone can be shown or told, and onlookers who see it used learn it too.

## Marking a door secret

Give the door object the game's own `concealed` status effect — the same mechanic behind
invisible characters:

```json
{ "id": "d1", "def": { "desc": "secret passage", "emoji": "🕳️", "type": "constant",
  "mechanics": [{ "type": "concealed" }] }, "appliedAt": 28800 }
```

Then describe it in the scenario's `arpgMods`:

```json
"arpgMods": {
  "secretPassages": {
    "passages": {
      "d1": { "knownBy": ["Alys Sedge"], "hint": "a draught behind the bookcase", "findChance": 0.25 }
    },
    "settings": { "findChance": 0.25, "findRange": 2, "onlookerRange": 6 }
  }
}
```

| Field | Meaning |
|---|---|
| `passages` | Per door, keyed by the door's entity id. All of it is optional: a door with the effect and no entry is a secret nobody knows. |
| `knownBy` | Characters who know it from the start, by name. Names with no character on the map are skipped, with a warning in the console. |
| `hint` | Told to the GM privately, and to the player in the log line when they find the door. |
| `findChance` | The chance per approach of the player noticing this door (default `settings.findChance`, then 0.25). |
| `settings.findChance` | The default find chance. |
| `settings.findRange` | How close, in cells, the player must get to roll (default 2). |
| `settings.onlookerRange` | How far, in cells, an onlooker can be and still see a use (default 6). |

A secret door combines with `locked`: knowing the door opens the wall for you, and the key
still opens the lock on top of that.

## Who knows what

Knowledge is tracked per character, saved with the game in `arpgMods.secretPassages.known`
(entity ids, resolved from `knownBy` once at world creation, never on a loaded save).

| Who | Learns it how |
|---|---|
| `knownBy` characters | Know it from the start. |
| The player | By standing within `findRange` cells of the door with line of sight to it: one `findChance` roll per approach, a fresh one after moving `findRange + 2` cells away. By watching someone who knows use it. By the GM's `secret_reveal`. The log says `You found a hidden door: <door>.` and adds the hint when there is one. |
| Onlookers | Any living character within `onlookerRange` cells of the door, on the same floor, with line of sight to it, when someone who knows it walks through it. An NPC remembers *"Saw \<user\> slip through a hidden door at \<door\>."*; the player's log says `You saw <user> slip through a hidden door: <door>.` |
| Anyone else | Only through the GM's `secret_reveal` (someone shows or tells them). An NPC remembers *"Learned of the hidden door at \<door\>."* |

Knowledge never spreads by itself. The barmaid who saw you use the bookcase door knows it;
the guards upstairs don't.

## The GM's part

- A private "Secret passages" section lists the secret doors near the player — who knows
  each, whether the player does, and the hint — with the instruction to hint and never state
  them outright. It shrinks with the context limits.
- `{"call": "secret_reveal", "door": "door name", "target": "character name (optional, default the player)"}`
  when the player searches the right spot, or someone shows or tells a character.
- To make a passage public to everyone, remove its "secret passage" effect with the game's
  own `status_remove`: the door becomes an ordinary door.

## Without this mod

The `concealed` effect alone just draws the door at 35% opacity. It still works, still lets
everyone through, and the GM still sees it — harmless, just not secret.

## Scope

Doors in walls only. Secret portals (trapdoors, tunnels between floors) are planned once
this has been play-tested.
