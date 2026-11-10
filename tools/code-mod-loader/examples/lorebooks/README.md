# Lorebooks

For Anywhere RPG 1.0 (code-mod loader 2.0.0). The 0.18 version is on the `0.18` branch.

Keyword-triggered lore for the GM, carried inside the scenario itself, so players install one
zip. Each turn the mod looks at what's happening near the player and adds the matching entries
to the GM prompt, under "Lore". It adds nothing else, so a large lorebook costs only what's
relevant at the moment.

## Format

Add an `arpgMods` key at the top level of `scenario.json`:

```json
"arpgMods": {
  "lorebookBudget": 2000,
  "lorebooks": {
    "College History": {
      "entries": [
        {"keys": ["Archmage Vellan", "Vellan"], "content": "Vellan founded the college in the year of ash.", "priority": 10},
        {"keys": ["Sundering"], "secondaryKeys": ["war", "battle"], "content": "The Sundering war split the realm."},
        {"constant": true, "content": "Magic is illegal outside the college walls."}
      ]
    },
    "Tavern Gossip": { "entries": [ ... ] }
  }
}
```

| Field | Meaning |
|---|---|
| `lorebookBudget` | Most characters of lore added per turn. Default 2000, and never more than the game's world background limit for the player's tier (Options → Context limits): 650 Free, 900 Silver, 1800 Sapphire, 3600 Obsidian and Custom service. Entries that don't fit are skipped. |
| `lorebooks.<name>` | One book. `"enabled": false` turns off the whole book. |
| `keys` | Words or names that trigger the entry. Case-insensitive, whole words only, so `Vel` won't match `Vellan`. |
| `secondaryKeys` | Optional. When set, at least one of these must also appear. |
| `content` | The text the GM sees. Write it as plain facts. |
| `constant` | `true` sends the entry every turn, with no keys needed. Use it sparingly. |
| `priority` | Higher goes first when the budget is tight. Constants always go first. |
| `stickyMinutes` | How many game minutes the entry stays after its last mention. Default 10. |
| `enabled` | `false` turns the entry off. |

SillyTavern World Info names work too: `key`, `keysecondary`, `order` and `disable`, plus an
`entries` object keyed by uid. So an exported World Info book can be pasted in as one book.

## What triggers an entry

The mod scans the parts of the GM prompt that describe the present:
- nearby characters, objects and the scene,
- the party and the tracked quest,
- events since the GM's last turn (what the player said and did),
- the current time and place,
- the GM's own last response.

It skips the full list of regions and the far-away characters, because otherwise every entry
would trigger all the time. It also skips what is in other rooms or on other floors, and the
player's own description.

## Context limits

When the GM prompt is too long, the game rebuilds it with smaller limits, and the Lore section
shrinks with the world background. If it is still too long, the game cuts every long section to
an equal share, keeping its first lines. So constants and high-priority entries, which go first,
survive. The section is never dropped while it has an entry.

## Behaviour

- The lorebooks are copied onto the world when a **new game** starts, so they're saved with it.
  Games started before the mod was installed have no lorebooks.
- A game without the mod ignores `arpgMods`. Check this with a real import before relying on it.
- Debugging: `__arpg.lore.last` lists the entries injected last time and why (`key "…"`,
  `sticky` or `constant`). The game's console (backtick key) has `dumpLastPrompt`, which shows
  the "Lore" section as the GM received it.

Not yet checked: whether the in-game World editor keeps `arpgMods` when it saves or exports a
scenario.
