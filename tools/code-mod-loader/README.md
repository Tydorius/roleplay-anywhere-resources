# Code-mod loader (prototype)

Adds JavaScript mods to Anywhere RPG, beyond what config packs can do: for example new GM API
calls, or changes to the prompts the game builds. It works like BepInEx does for Unity games,
but for this Electron app. A patcher makes two small changes to the installed renderer bundle and
loads your mod scripts before the game starts.

Requires Node 18 or later. Close the game before running the patcher.

```bash
node patch.mjs status      # is the game patched, which mods were found, do the anchors still match
node patch.mjs install     # patch (or re-patch) and copy in the mods
node patch.mjs uninstall   # restore the original files
```

`--game "<install dir>"` overrides the default `D:\SteamLibrary\steamapps\common\Anywhere RPG`.

## Installing a mod

Mods live in `%APPDATA%\Anywhere RPG\code-mods\<mod name>\mod.js`, beside the game's own `mods`
folder for config packs. Copy a mod folder there, then run `node patch.mjs install` again. The
patcher copies mods into the game, so **re-run install after adding, changing or removing a mod**.

Example: `examples/memory-add` gives the GM a `memory_add` call. It writes a memory onto a
character, and the memory shows in that character's panel under Memories.

## After a game update or "Verify integrity"

Steam puts the original files back, so the mods stop loading. Run `node patch.mjs install`
again. If the update changed the code the patcher anchors on, install stops with
`patch "<name>" matched N times` and changes nothing. Then the anchors in `patch.mjs` need
updating.

## What the patcher changes

All the original files are kept as `*.arpg-orig` beside the patched ones.

| File | Change |
|---|---|
| `resources/app/dist/assets/index-*.js` | The GM's API-call registry (the object literal starting `{flavor_text:`) is also stored as `__arpg.api`. The config-file getter (found by its `getConfigFile before loadConfig` warning) is wrapped so every prompt/config read goes through `__arpg.cfg`. |
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
| `api` | The live registry, once the game has built it. |

## Debugging

Launch with `"Anywhere RPG.exe" --remote-debugging-port=9222`, then open `chrome://inspect` in
Chrome or Edge to get DevTools for the game window. `__arpg.mods`, `__arpg.calls` and
`__arpg.cfgSeen` (every config path read so far) show what loaded. The game's own console
(backtick key) has `dumpLastPrompt`, which shows the last prompt sent to the GM.
