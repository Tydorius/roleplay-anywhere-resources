# Roleplay Anywhere resources

Community resources for Anywhere RPG (Roleplay Anywhere).

> **Game version:** everything here was built and tested against **Anywhere RPG 0.18**. Updates can
> change the config files and code these resources depend on, so check each folder's README for
> what to re-check after an update.

> **Last update for 0.18.** The world settings files (save, export and import a world's choices)
> are the final update to these mods and tools for Anywhere RPG 0.18. The 0.18 versions stay on the
> [`0.18` branch](https://github.com/Tydorius/roleplay-anywhere-resources/tree/0.18) and in the
> final 0.18 release, [`v0.18-final`](https://github.com/Tydorius/roleplay-anywhere-resources/releases/tag/v0.18-final).
> From here on, `main` is updated for **Anywhere RPG 1.0**, currently on Steam's alpha track. If you
> play 0.18, use the `0.18` branch or that release.

> **Not carried over to 1.0.** Anywhere RPG 1.0 now does these natively, so they stay on the
> `0.18` branch and in `v0.18-final` only:
> - **Portals** → 1.0's own portals (objects linked end to end; god mode's Link Portal).
> - **Floors** (emulated upper storeys) → 1.0's floors (separate levels reached by stairs, ladders
>   or hatches). Not carried over: seeing the floor below through a gallery or well.
> - **Performance** → 1.0 culls off-screen art and caches the movement grid itself.
> - **World generator `floors` and `portals` extensions** → the generator writes 1.0's native floors
>   and stairs instead, so multi-storey worlds need no mods.

| Folder | What it is |
|---|---|
| [`mods/better-images`](mods/better-images) | ComfyUI image-generation mods for Anywhere RPG: better workflows and prompts per image type, background removal for map objects and items, a setup script that adapts them to your ComfyUI's model files, and an **Image Gallery** page for viewing and regenerating any scenario image. |
| [`tools/scenario-editor`](tools/scenario-editor) | A **Scenario Editor** in your browser: move, resize and draw regions, place objects and people, add doors, check the scenario against the game's real map rules as you go, and download a zip for **New Game → Import…**. It includes the Image Gallery as its Images tab. |
| [`tools/world-generator`](tools/world-generator) | A standalone **world generator**: a one-line idea in, a ready-to-import scenario zip out — model phases describe the world (zones, buildings, rooms, people), deterministic code places it and checks reachability. Bring your own OpenAI-compatible provider and key. Double-click `Start World Generator.bat` (or the `.command` / `.sh`): it asks for your provider the first time, then for an idea. The Scenario Editor drives it too, through its **New world…** dialog. Layout improvements are still in progress. |
| [`mods/voices`](mods/voices) | NPC voices on a Custom (OpenAI-compatible) speech endpoint: a voice list that matches characters by gender and age, GM delivery cues like `(sighs)`, and a small Drama 3 / Qwen3-TTS proxy that stops runaway clips. Also documents how the game picks voices. |
| [`tools/code-mod-loader`](tools/code-mod-loader) | A **code-mod loader** (2.1.0, for Anywhere RPG 1.0) that adds JavaScript mods to the game, with a `memory-add` sample. Wall-aware perception and non-rectangular regions work on 1.0; lorebooks and flickering, coloured lights are being ported. Install by double-clicking `install.cmd` (or `./install.sh`); needs Node.js 18+. |
| [`scenarios/sundered-boundary-forgotten-village`](scenarios/sundered-boundary-forgotten-village) | **The Sundered Boundary: The Forgotten Village**, a xianxia "weakest village" scenario with all images included. Import the `.scenario.zip` from **New Game → Import…**. |
| [`scenarios/sundered-boundary-royal-masquerade`](scenarios/sundered-boundary-royal-masquerade) | **The Sundered Boundary: Royal Masquerade**, an otome-isekai academy scenario with all images included. Import the `.scenario.zip` from **New Game → Import…**. |

### Mod packs

Copy a pack folder into the game's mods folder (`%APPDATA%\Anywhere RPG\mods` on Windows) and enable
it in **Options → Mods**. See the [Better Images README](mods/better-images) for details.

| Pack | Model |
|---|---|
| [`better-images-flux2-klein`](mods/better-images/packs/better-images-flux2-klein) | Flux.2 [klein] 9B (recommended) |
| [`better-images-flux1`](mods/better-images/packs/better-images-flux1) | Flux.1 [dev] / [schnell] |
| [`better-images-qwen-image`](mods/better-images/packs/better-images-qwen-image) | Qwen-Image |
| [`better-images-sdxl`](mods/better-images/packs/better-images-sdxl) | any SDXL checkpoint |
| [`better-images-sdxl-portraits`](mods/better-images/packs/better-images-sdxl-portraits) | SDXL / Illustrious, portraits only (add-on) |
| [`better-images-sd15`](mods/better-images/packs/better-images-sd15) | any SD1.5 checkpoint |

Licensed under the Mozilla Public License 2.0 (see `LICENSE`).
