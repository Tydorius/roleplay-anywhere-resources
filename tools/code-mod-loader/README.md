# Code-mod loader 1.0.0

Adds JavaScript mods to Anywhere RPG, beyond what config packs can do: for example new GM API
calls, or changes to the prompts the game builds. It works like BepInEx does for Unity games,
but for this Electron app. A patcher makes two small changes to the installed renderer bundle and
loads your mod scripts before the game starts.

**Game version:** built and play-tested against **Anywhere RPG 0.18** (bundle `index-DSU_zx7g.js`).
The patcher prints the game's version and warns if it isn't 0.18. On another version it still
installs only when every patch anchor matches exactly once; otherwise it stops and changes nothing.

| Version | Date | Changes |
|---|---|---|
| 1.0.0 | 2026-11-01 | First release, for Anywhere RPG 0.18: the loader, seven mods (lorebooks, portals, wall-aware perception, floors, performance, region groups, lights) and one-step install. |

## Install

You need [Node.js](https://nodejs.org/) 18 or later. Close the game first.

| System | Install every mod | Undo |
|---|---|---|
| Windows | double-click `install.cmd` | double-click `uninstall.cmd` |
| Linux / macOS | `./install.sh` | `./uninstall.sh` |

That copies every bundled mod except the `memory-add` sample into your code-mods folder and
patches the game. To pick mods, name them: `install.cmd portals floors lights`. The game is found
in any of your Steam libraries; if it lives somewhere else, add `--game "<install folder>"`.

The same from a terminal:

```bash
node patch.mjs status              # game version, patched or not, which mods are installed
node patch.mjs add [mods…]         # copy bundled mods in (none named: all but memory-add), then install
node patch.mjs remove <mods…>      # take mods out, then install the rest
node patch.mjs install             # patch (or re-patch) with whatever is in the code-mods folder
node patch.mjs uninstall           # restore the original files
```

Every command takes `--game "<install folder>"`.

Linux and macOS: the patcher and scripts are written for them, but so far they have only been
run on Windows.

## Your own mods

Mods live in a code-mods folder, one folder per mod with a `mod.js` in it:

| System | Folder |
|---|---|
| Windows | `%APPDATA%\Anywhere RPG\code-mods`, beside the game's own `mods` folder for config packs |
| macOS | `~/Library/Application Support/Anywhere RPG/code-mods` |
| Linux | `~/.config/Anywhere RPG/code-mods` (or under `$XDG_CONFIG_HOME`) |

Put a mod folder there, then run `node patch.mjs install` again. The patcher copies mods into the
game, so **re-run install after adding, changing or removing a mod**.

## Bundled mods

`add`, `install.cmd` and `install.sh` take these from `examples/`:
- `examples/memory-add` is a sample for mod writers, so it's only installed when you name it. It
  gives the GM a `memory_add` call that writes a memory onto a character, shown in that
  character's panel under Memories. The GM hasn't yet been seen using it in a real turn.
- `examples/lorebooks` adds keyword-triggered lore that a scenario carries in its own
  `scenario.json`. See [its README](examples/lorebooks/README.md) for the format.
- `examples/portals` adds doors, stairs and teleporters between parts of the map. Walks route
  through them on their own, and the GM is told about them. See
  [its README](examples/portals/README.md).
- `examples/wall-aware-perception` stops the player and NPCs noticing each other through walls.
  The game only measures straight-line distance. See [its README](examples/wall-aware-perception/README.md).
- `examples/floors` emulates upper floors, cellars and galleries on the flat map. Floors notice
  each other only through openings, and each opening shows the room below. See
  [its README](examples/floors/README.md).
- `examples/performance` caches the game's movement grid (it was rebuilt about 570 times a
  second) and stops the game drawing things far off screen. See
  [its README](examples/performance/README.md).
- `examples/region-groups` makes touching rectangles with the same name act as one region, so
  you can build L-shaped houses or a forest wrapped round a village. See
  [its README](examples/region-groups/README.md).
- `examples/lights` gives each light source a kind: candles flicker small and warm, hearths
  throw embers, bulbs hold steady, arcane crystals pulse blue. It also stops lamp light reaching
  objects and characters through walls. It works on existing scenarios as they are. See
  [its README](examples/lights/README.md).

Tests: `node --test` in this folder.

## After a game update or "Verify integrity"

Steam puts the original files back, so the mods stop loading. Run `node patch.mjs install`
again, or use the shortcut scripts beside it. Both work from any folder and pass extra arguments
such as `--game` through:

- Windows: double-click `reinstall.cmd`. The window stays open so you can read the result.
- Linux/macOS: `./reinstall.sh`.

If the update changed the code the patcher anchors on, install stops with
`patch "<name>" matched N times` and changes nothing. Then the anchors in `patch.mjs` need
updating, and the mods need play-testing on the new version.

## What the patcher changes

All the original files are kept as `*.arpg-orig` beside the patched ones.

| File | Change |
|---|---|
| `resources/app/dist/assets/index-*.js` | The GM's API-call registry (the object literal starting `{flavor_text:`) is also stored as `__arpg.api`. The config-file getter (found by its `getConfigFile before loadConfig` warning) is wrapped so every prompt/config read goes through `__arpg.cfg`. The scenario → world builder calls `__arpg.worldCreated` before it returns. That call copies the scenario's `arpgMods` onto the world, and so into saves. The grid pathfinder is wrapped by `__arpg.path`, and the movement grid calls `__arpg.nav` as it's built. Each unpaused simulation step starts with `__arpg.tick`. The straight-line "within notice range" test hands its answer to `__arpg.perceive`, which returns the final one. The GM prompt's parts go through `__arpg.prompt` before they're rendered. |
| `resources/app/dist/index.html` | `<script>` tags for `arpg-mods/loader.js` and each mod, placed before the game bundle. |
| `resources/app/dist/arpg-mods/` | The loader and the copied mods. |

## Writing a mod

A mod is a plain script that runs before the game bundle. It uses `globalThis.__arpg`:

| API | Purpose |
|---|---|
| `registerMod(name)` | Lists the mod in `__arpg.mods`. |
| `addCall(name, api => ({schema, run}))` | Adds a GM API call. `schema` is a zod object. Fields whose schema is described as `entity`, `entity?`, `region` or `place` are resolved from names to game objects for you. The easiest way to get one is to reuse another call's field, e.g. `api.hp_delta.schema.pick({target:true})`. `run(world, args)` returns `null` on success, or an error string, which the GM log shows as `rejected: …`. |
| `addApiHeader(name, text, after?)` | Describes a call to the GM. It adds `overseer/api-actions/<name>.txt` and slots it into `ordered-api-calls.json` after the header named `after`. |
| `onConfig((path, readOriginal) => string \| undefined)` | Rewrites any config/prompt file as the game reads it. Return `undefined` to leave the file alone. |
| `onWorldCreate((world, scenario, editing) => void)` | Runs when a scenario becomes a world. Use it to copy your own scenario keys (put them under `arpgMods`) onto the world. World fields are saved with the game. |
| `onPrompt(({head, sections, tail}, world) => void)` | Edits the GM prompt. Each part is a list of `{kind, title, content}`. The game trims its own kinds to a budget, but a new kind isn't trimmed, so limit your own size. |
| `onNav((world, grid) => void)` | Runs whenever the game builds its movement grid, which every walk, path search and collision uses. Set `grid.blocked[y * grid.w + x] = 1` to make a cell impassable. It's rebuilt for every search, so keep it cheap. |
| `setNavCache({get, put})` | Lets one mod supply a cache for the movement grid. `get(world, entity, wallsOnly)` returns a grid or null; `put(world, entity, wallsOnly, grid)` is offered each new one. Grids are read-only after they're built. |
| `onTick(world => void)` | Runs at the start of every unpaused simulation step, so keep it cheap. |
| `onPath((world, from, dest, entity, opts, next) => cells \| null)` | Wraps the game's grid pathfinder, which every walk uses. `next(...)` runs the plain search. Return the cells to walk, excluding the start cell. `entity` is unset for queries that aren't walks. |
| `onPerceive((world, a, b, range, search, answer) => boolean \| undefined, {order})` | Runs whenever the game asks whether `a` and `b` are within notice range. `answer` is the answer so far, starting from the game's straight-line test. Return a boolean to replace it, or nothing to leave it. Hooks with a higher `order` run later and have the last word. `search` is the game's path search. |
| `api` | The live registry, once the game has built it. |
| `promptBudgets` | The game's per-kind character budgets for prompt sections, scaled by the text-service tier. When you add a section kind, add a budget for it too. Without one, the game tags your section with "(0 more lines omitted)". |

## Debugging

Launch with `"Anywhere RPG.exe" --remote-debugging-port=9222`, then open `chrome://inspect` in
Chrome or Edge to get DevTools for the game window. `__arpg.mods`, `__arpg.calls` and
`__arpg.cfgSeen` (every config path read so far) show what loaded. The game's own console
(backtick key) has `dumpctx`, which prints the last prompt sent to the GM.

Every AI call is also written to `<install dir>/logs/`, which is usually easier:
`overseer/turnNNNN-aiNNNN-request-*.txt` is each GM turn's full prompt and the matching
`-response-*.txt` is its reply, while `anywhere-rpg-ai.log` has every call (GM, images, TTS) with
prompt and response. `dumpctx` only holds the single most recent call, and a later TTS or image
call overwrites it.
