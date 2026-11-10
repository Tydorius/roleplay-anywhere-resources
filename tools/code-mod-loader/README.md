# Code-mod loader 2.0.0

Adds JavaScript mods to Anywhere RPG, beyond what config packs can do: for example new GM API
calls, or changes to the prompts the game builds. It works like BepInEx does for Unity games,
but for this Electron app. A patcher makes two small changes to the installed renderer bundle and
loads your mod scripts before the game starts.

**Game version:** built for **Anywhere RPG 1.0** (Steam alpha build 26557354, bundle
`index-BrLojUrw.js`). The patcher prints the game's version and warns if it isn't 1.0. On another
version it still installs only when every patch anchor matches exactly once; otherwise it stops and
changes nothing. **Playing 0.18?** Use loader 1.0.0 from the
[`0.18` branch](https://github.com/Tydorius/roleplay-anywhere-resources/tree/0.18) or the
[`v0.18-final`](https://github.com/Tydorius/roleplay-anywhere-resources/releases/tag/v0.18-final) release.

| Version | Date | Changes |
|---|---|---|
| 2.0.0 | 2026-11-10 | For Anywhere RPG 1.0 only. Reads 1.0's version; fixes the `world-create` and `gm-prompt` patches for 1.0; `onPrompt` hooks now get the context limits; drops the `prompt-budgets`, `nav-cache-get/put`, `edge-memo` and `nav-grid` patches with the `promptBudgets`, `setNavCache` and `onNav` APIs; retires the portals, floors and performance mods (1.0 does them natively); `memory-add` writes 1.0's prose memory. |
| 1.0.0 | 2026-11-01 | First release, for Anywhere RPG 0.18: the loader, seven mods (lorebooks, portals, wall-aware perception, floors, performance, region groups, lights) and one-step install. |

> **Not carried over to 1.0.** Anywhere RPG 1.0 now does these natively, so they stay on the
> `0.18` branch and in `v0.18-final` only:
> - **Portals** → 1.0's own portals (objects linked end to end; god mode's Link Portal).
> - **Floors** (emulated upper storeys) → 1.0's floors (separate levels reached by stairs, ladders
>   or hatches). Not carried over: seeing the floor below through a gallery or well.
> - **Performance** → 1.0 culls off-screen art and caches the movement grid itself.
> - **World generator `floors` and `portals` extensions** → the generator writes 1.0's native floors
>   and stairs instead, so multi-storey worlds need no mods.

## Install

You need [Node.js](https://nodejs.org/) 18 or later. Close the game first.

| System | Install every mod | Undo |
|---|---|---|
| Windows | double-click `install.cmd` | double-click `uninstall.cmd` |
| Linux / macOS | `./install.sh` | `./uninstall.sh` |

That copies every bundled mod except the `memory-add` sample into your code-mods folder and
patches the game. To pick mods, name them: `install.cmd lorebooks lights`. The game is found
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
  gives the GM a `memory_add` call that appends a sentence to a character's memory, shown in that
  character's panel under Memories. **Works on 1.0.**
- `examples/lights` gives each light source a kind: candles flicker small and warm, hearths
  throw embers, bulbs hold steady, arcane crystals pulse blue. It also stops lamp light reaching
  objects and characters through walls, or from another floor. It works on existing scenarios
  as they are. **Works on 1.0.** See [its README](examples/lights/README.md).

**Being ported to 1.0.** These three still install and load, but they were written and
play-tested on 0.18. Each gets its own port session; until then they may not work as described:
- `examples/lorebooks` adds keyword-triggered lore that a scenario carries in its own
  `scenario.json`. See [its README](examples/lorebooks/README.md) for the format.
- `examples/wall-aware-perception` stops the player and NPCs noticing each other through walls.
  The game only measures straight-line distance for its general notice range. See
  [its README](examples/wall-aware-perception/README.md).
- `examples/region-groups` makes touching rectangles with the same name act as one region, so
  you can build L-shaped houses or a forest wrapped round a village. See
  [its README](examples/region-groups/README.md).

Tests: `node --test tests/*.test.mjs` in this folder. One test patches the real 1.0 bundle when it
finds a copy (set `ARPG_BUNDLE_10` to its path); otherwise it's skipped.

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
| `resources/app/dist/assets/index-*.js` | Ten small patches, each found by its content (see the next table). |
| `resources/app/dist/index.html` | `<script>` tags for `arpg-mods/loader.js` and each mod, placed before the game bundle. |
| `resources/app/dist/arpg-mods/` | The loader and the copied mods. |

The bundle patches. Each must match exactly once, or install stops and changes nothing.

| Patch | Where | What mods get |
|---|---|---|
| `api-registry` | The GM's API-call registry (the object literal starting `{flavor_text:`) | `__arpg.api`, so `addCall` can add calls. |
| `config-reader` | The config-file getter (found by its `getConfigFile before loadConfig` warning) | Every prompt/config read goes through `__arpg.cfg` (`onConfig`, `addApiHeader`). |
| `world-create` | The end of the scenario → world builder, after the new-game setup | `__arpg.worldCreated`: copies the scenario's `arpgMods` onto the world (and so into saves), then runs `onWorldCreate`. |
| `pathfinder` | The grid A* inside one plane | `onPath`. |
| `region-arrival` | "Is this cell in that region?" (the innermost region at the cell) | `__arpg.sameRegion`. |
| `region-destination` | Picking a standing spot inside a region | `__arpg.pieceFor`. |
| `region-same-room` | The GM prompt's "same walled room as the player" test | `__arpg.sameRegion`. |
| `sim-tick` | The start of each unpaused simulation step | `onTick`. |
| `perception` | The straight-line "within notice range" test (14 cells) | `onPerceive`. |
| `gm-prompt` | Where the GM prompt's head, sections and tail are built from the world and the context limits | `onPrompt`. |

## Writing a mod

A mod is a plain script that runs before the game bundle. It uses `globalThis.__arpg`:

| API | Purpose |
|---|---|
| `registerMod(name)` | Lists the mod in `__arpg.mods`. |
| `addCall(name, api => ({schema, run}))` | Adds a GM API call. `schema` is a zod object. Fields whose schema is described as `entity`, `entity?`, `region` or `place` are resolved from names to game objects for you. The easiest way to get one is to reuse another call's field, e.g. `api.hp_delta.schema.pick({target:true})`. `run(world, args)` returns `null` on success, or an error string, which the GM log shows as `rejected: …`. |
| `addApiHeader(name, text, after?)` | Describes a call to the GM. It adds `overseer/api-actions/<name>.txt` and slots it into `ordered-api-calls.json` after the header named `after`. |
| `onConfig((path, readOriginal) => string \| undefined)` | Rewrites any config/prompt file as the game reads it. Return `undefined` to leave the file alone. |
| `onWorldCreate((world, scenario, editing) => void)` | Runs when a scenario becomes a world. Use it to copy your own scenario keys (put them under `arpgMods`) onto the world. World fields are saved with the game. |
| `onPrompt(({head, sections, tail}, world, limits) => void)` | Edits the GM prompt. Each part is a list of `{kind, title, content}`; push your own sections. `limits` are the context limits this build uses. See [Prompt sections on 1.0](#prompt-sections-on-10) for how the game trims. |
| `onTick(world => void)` | Runs at the start of every unpaused simulation step, so keep it cheap. |
| `onPath((world, from, dest, entity, opts, next) => cells \| null)` | Wraps the game's grid pathfinder, which every walk uses. `next(...)` runs the plain search. Return the cells to walk, excluding the start cell. `entity` is unset for queries that aren't walks. In 1.0 this search stays inside one plane (the main map or one floor); walks between floors go through 1.0's portals, which are routed above it. |
| `onPerceive((world, a, b, range, search, answer) => boolean \| undefined, {order})` | Runs whenever the game asks whether `a` and `b` are within notice range. `answer` is the answer so far, starting from the game's straight-line test. Return a boolean to replace it, or nothing to leave it. Hooks with a higher `order` run later and have the last word. `search` is the game's path search. |
| `api` | The live registry, once the game has built it. |

Removed in 2.0.0: `promptBudgets` (1.0 has no per-kind budget table), and `onNav` and
`setNavCache` (1.0 rewrote its movement grid, caches it itself and makes it plane-aware). The mods
that used them stay on the `0.18` branch.

### Prompt sections on 1.0

1.0 has no per-kind budgets. Instead, going by the 1.0 bundle:
1. The prompt is built from the **Context limits** in force (per tier: recent turns, story summary
   words, detailed characters, names listed, world background characters and so on). `onPrompt`
   runs on that build and gets those `limits`.
2. If the whole prompt is over the character budget (the Custom service's character budget, or
   the Official tier's), the game rebuilds it up to ten times with lower limits, each step closer
   to, then below, the tier's defaults. **Your hook runs again on each rebuild** with the lower
   `limits`, so build your section afresh each time and size it from `limits` (for example a
   share of `limits.worldChars`) so it shrinks along with the game's own sections.
3. If it's still over, every section longer than an equal share is cut to that share. It keeps
   its first lines and ends with `(+N more)`. Mod sections are cut like any other. (The game's
   `record`, `turns` and `events` kinds keep their title line and their last lines instead.)
4. A section is dropped only when its `content` is empty. Nothing is tagged "omitted" when it fits,
   and a new kind needs no registration.
5. When trimming happened and the player has set their own Context limits, the game shows a
   one-time "context trimmed" notice (`sim.overseer.contextTrimmed`).

So keep mod sections short, put the most important lines first, and scale them with `limits`.

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
