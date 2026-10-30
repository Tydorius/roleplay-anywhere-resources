# Roleplay Anywhere resources

Community resources for Anywhere RPG (Roleplay Anywhere).

| Folder | What it is |
|---|---|
| [`mods/better-images`](mods/better-images) | ComfyUI image-generation mods for Anywhere RPG: better workflows and prompts per image type, background removal for map objects and items, a setup script that adapts them to your ComfyUI's model files, and an **Image Gallery** page for viewing and regenerating any scenario image. |
| [`tools/scenario-editor`](tools/scenario-editor) | A **Scenario Editor** in your browser: move, resize and draw regions, place objects and people, add doors, check the scenario against the game's real map rules as you go, and download a zip for **New Game → Import…**. It includes the Image Gallery as its Images tab. |
| [`mods/voices`](mods/voices) | NPC voices on a Custom (OpenAI-compatible) speech endpoint: a voice list that matches characters by gender and age, GM delivery cues like `(sighs)`, and a small Drama 3 / Qwen3-TTS proxy that stops runaway clips. Also documents how the game picks voices. |
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
