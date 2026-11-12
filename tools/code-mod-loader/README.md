# Code-mod loader 2.3.0

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
| 2.3.0 | 2026-11-11 | Seven new patches for hidden entities, drawn walls and per-walker doors: `onHidden` takes an entity off screen and out of pointer hits, `onWallRegions` rewrites the regions walls are drawn from (drawing only, never walking), `onDoor` decides per character which doors block walking and door swing (and can gate an unlocked door onto the door list), `onDoorway` filters the GM's doorway list, and `hasMechanic` is the game's own status test. |
| 2.2.0 | 2026-11-10 | Two new render patches, liquid-canvas and ground-fade, add the `onLiquidCanvas` and `onGroundFade` hooks: mods can repaint a water/road chunk's colour and flow canvases (and override its blur radius) and reshape the fade at a region's ground edges. |
| 2.1.0 | 2026-11-10 | Two new patches, line-of-sight and sight-blockers, give mods 1.0 stealth's own line-of-sight test (`lineOfSight`, `sightBlockers`) and `planeOf`; wall-aware perception answers with it and region groups never span two floors and take 1.0's doors off the joints between pieces. Both mods are ported to 1.0. |
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
- `examples/wall-aware-perception` stops the player and NPCs noticing each other through walls,
  answering with 1.0 stealth's own line of sight. See
  [its README](examples/wall-aware-perception/README.md). **Works on 1.0.**
- `examples/region-groups` makes touching rectangles with the same name act as one region, so
  you can build L-shaped houses or a forest wrapped round a village. See
  [its README](examples/region-groups/README.md). **Works on 1.0.**
- `examples/smooth-edges` takes the cell-grid steps off water and road shores (diagonal corner
  cuts, rounded ends) and fades natural region ground along its true outline. See
  [its README](examples/smooth-edges/README.md). **Works on 1.0.**
- `examples/lorebooks` adds keyword-triggered lore that a scenario carries in its own
  `scenario.json`. See [its README](examples/lorebooks/README.md) for the format.
  **Works on 1.0.**

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
| `resources/app/dist/assets/index-*.js` | Twenty-one small patches, each found by its content (see the next table). |
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
| `line-of-sight` | 1.0 stealth's line-of-sight test through walls and shut doors | `__arpg.lineOfSight`. |
| `sight-blockers` | The walls and shut doors that test takes | `__arpg.sightBlockers`. |
| `gm-prompt` | Where the GM prompt's head, sections and tail are built from the world and the context limits | `onPrompt`. |
| `liquid-canvas` | The liquid overlay painter, between painting a chunk's two canvases and blurring them into the tile | `onLiquidCanvas`. |
| `ground-fade` | The region ground fade in the scene's groundOwners() | `onGroundFade`. |
| `wall-regions` | The wall-edge builder every wall-drawing path uses (walls, wall-caster shadows, door info, the minimap) | `__arpg.wallRegions` (`onWallRegions`): rewrite the regions walls are drawn from. Drawing only — the simulation never calls this builder, so where anyone can walk never changes. |
| `entity-hidden` | The scene's per-entity sprite sync, at its off-screen cull | `__arpg.hidden` (`onHidden`): take an entity off screen, with its label, shadows and light. |
| `pointer-hits` | The pointer hit test behind hover, click, select and the context menu | `__arpg.hidden` again: a hidden entity can't be hovered or clicked. |
| `door-list` | The shared list of doors that may stop someone (only locked doors reach it) | `__arpg.doorGated` (`onDoor`): gate more doors onto the list. |
| `door-pass-nav` | The per-walker door pass test at the end of the movement grid builder | `__arpg.doorPasses` (`onDoor`): decide, per walker, which doors become blocked edges for walking. |
| `door-pass-swing` | The door swing test ("does this person hold it open?"; shut doors block sight) | `__arpg.doorPasses` again: the same per-walker say for door swing. |
| `gm-doorways` | The GM's doorway list, behind the GM prompt's door details | `__arpg.doorwayShown` (`onDoorway`): drop doorways from the GM's list. |

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
| `onLiquidCanvas(payload => number \| undefined, {order})` | Runs when a water/road chunk's two canvases are fully painted, before they are blurred into the tile. Repaint them, and return a finite number ≥ 0 to override this chunk's blur radius. See [Liquid canvases and ground fades](#liquid-canvases-and-ground-fades). |
| `onGroundFade((region, mask, def) => Float32Array \| undefined, {order})` | Runs when the game fades a region's ground at its edges. Return a `Float32Array` of `def.length` to replace the fade — the same array for the same mask, or the ground is rebuilt every sync. See [Liquid canvases and ground fades](#liquid-canvases-and-ground-fades). |
| `onHidden((world, entity) => boolean, {order})` | Runs per entity per frame, in the scene's sprite sync and the pointer hit test. Return true to hide the entity: it is drawn nowhere (no container, label, shadows or light) and can't be hovered, clicked or selected. Keep it cheap. |
| `onWallRegions((regions, world) => regions, {order})` | Runs before wall edges are derived, for every wall-drawing path (walls, wall-caster shadows, door info, the minimap). Return an array of regions to replace the list (each hook gets the previous hook's result; `world` is the last world the loader has seen), anything else to keep it. This only changes what is drawn, never where anyone can walk. |
| `onDoor({gated(world, door) => boolean, passes(world, door, walker, native) => boolean \| undefined}, {order})` | Decides doors per character. `gated` puts an otherwise-unlocked door on the list of doors that may stop someone. `passes` answers, per walker, whether a door passes — walking (the movement grid's shut doors) and door swing (shut doors block sight) ask the same question — where `native` is the answer so far (the game's own: unlocked, or the walker's keys open it). Return a boolean to replace it, `undefined` to keep it. `walker` is unset for queries that aren't walks. |
| `onDoorway((world, doorway) => boolean, {order})` | Filters the GM's doorway list (each doorway is `{crossings, room, doors}`). Return false to drop a doorway from the GM prompt's door details; anything else keeps it. |
| `hasMechanic(entity, type)` | The game's own status test: does the entity carry a mechanic of this type? A door is locked exactly when `hasMechanic(door, "locked")`. |
| `sightBlockers(world)` | The walls and shut doors 1.0's own sight test takes (the world's wall regions, plus the door edges nobody holds open). Building it scans every entity, so hold on to the result when testing many lines. |
| `lineOfSight(world, from, to, blockers?)` | 1.0 stealth's line-of-sight test: walls and shut doors block, bars, gates and open doorways don't. Points are continuous (an entity's centre is `[pos[0]+size[0]/2, pos[1]+size[1]/2]`); pass `blockers` when testing many lines. |
| `planeOf(world, point)` | The plane a point is on: the pocket region (a floor or cellar) containing it, or `null` on the main map. |
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

### Liquid canvases and ground fades

Two hooks reshape how 1.0 draws water shores and the edges of region ground.

**`onLiquidCanvas(payload => number | undefined, {order})`** — the game paints each 32×32-cell
chunk of water and roads (with a 2-cell margin) on two canvases, then blurs and crops a copy of
each into the tile. The hook runs between the painting and the blur, once per chunk, and
`payload` holds:

- `color` and `flow` — the two canvases as 2D contexts, `(chunkCells + margin*2) * cellPx`
  square (432px on 1.0). `color` is the colour layer, transparent off the liquid and roads;
  `flow` starts filled `rgb(128, 128, 0)`, and its R/G holds the flow vector (128, 128 = none)
  and B the liquid kind.
- `cellPx` (12), `margin` (2), `chunkCells` (32) — the grid the chunk was painted on.
- `chunk` — the chunk's tile `[cx, cy]`; `unbounded` — the world's own flag; `blur` — the
  game's blur radius (7).
- **Coordinates:** cell `(v, y)` has v = x and **y up**, both counted from the chunk's own
  corner and running from `-margin` to `chunkCells + margin - 1`. It is the `cellPx` square at
  pixel `((v + margin) * cellPx, (chunkCells + margin - 1 - y) * cellPx)` — **canvas rows run
  top-down while y runs up.**

Return a finite number ≥ 0 to override this chunk's blur radius; the highest-`order` hook that
returns one has the last word. Repainting costs nothing extra: whatever is on the two canvases
is what gets blurred into the tile.

**`onGroundFade((region, mask, def) => Float32Array | undefined, {order})`** — each region's
ground art is faded at its edges with one alpha per vertex. `mask` is the region's `Uint8Array`
cell mask (`[row*w + x]`, row 0 = the region's **lowest** y; null never reaches the hook), and
`def` is the game's own fade. Return a `Float32Array` of `def.length` — `(w+1)*(h+1)` values —
to replace it; the lowest-`order` hook that returns a valid one wins.

- **Vertex orientation:** vertex `(sx, my)` at index `my*(w+1) + sx` is the point x = sx,
  **y = h − my** in region-local cells, so vertex row 0 is the **top** edge.
- **The identity rule:** the game compares the fade by identity and refills the ground tile
  whenever it changes, so **return the same array for the same mask** (build it once, cache it
  keyed by mask) or the ground is rebuilt on every sync.

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
