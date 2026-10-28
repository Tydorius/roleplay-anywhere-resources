# Better Images for Anywhere RPG (ComfyUI)

Anywhere RPG's built-in ComfyUI workflow is Stable Diffusion 1.5 at 512 px, and its image prompts
are written for that model. On the newer models most people run, that gives mushy or garish map
objects and icons, and **map objects (sprites) and items keep their background**: the Official
image service removes it on its server, but the ComfyUI path never does.

These mod packs replace the workflow and prompts for each image type.

| Pack | Image types | Models | Speed |
|---|---|---|---|
| `better-images-flux2-klein` | all | Flux.2 [klein] 9B | fast (4 steps) |
| `better-images-qwen-image` | all | Qwen-Image | slow (20 steps), most literal |
| `better-images-sdxl` | all | any SDXL checkpoint, 1024 px | medium |
| `better-images-sdxl-portraits` | portraits only (add-on) | an SDXL / Illustrious checkpoint | medium |

Each pack's `PACK-NOTES.md` lists the exact files it expects and where they go.

## Install

1. Copy one or more folders from `packs/` into the game's mods folder:
   - **Windows:** `%APPDATA%\Anywhere RPG\mods`
   - **Other systems:** open it from **Options → Mods → Open mods folder** in the game.
2. In **Options → Mods**, enable **one** main pack. To keep anime-style portraits with Flux or Qwen
   props, also enable `sdxl-portraits` **after** it.
3. In **Options → AI Images**, set the image service to ComfyUI and check the model menus:
   - With the Flux or Qwen pack they list your *diffusion models* instead of checkpoints.
   - Choose the model each image type should use.
4. Sprites and items need a background-removal node. The packs use **WAS Node Suite**'s
   `Image Rembg (Remove Background)`; install it with ComfyUI Manager.

## Your files are named differently?

The packs use the standard Comfy-Org filenames. If yours differ (subfolders, fp8/bf16 variants,
SwarmUI layouts), let the setup script read your ComfyUI and rewrite the packs:

```
python setup_image_mod.py --detect http://127.0.0.1:8188
python setup_image_mod.py --detect http://127.0.0.1:8188 --install
```

The script needs only the Python standard library. With `--detect` it only *reads* ComfyUI's model
lists; it does not queue any work.
- `--packs flux2-klein sdxl-portraits` writes only the packs you name.
- `--remover ben2|rembg|none` picks the background remover (`ben2` needs ComfyUI-RMBG).
- `--out DIR` writes the packs elsewhere.

**Why the names matter:** the game has no model menu for map objects. It uses the file named in
the sprite workflow, and if that file is missing, the first model on ComfyUI's list, which may not
even be an image model.

## How it plugs into the game

All of this is standard Anywhere RPG modding; nothing in the game's own files is changed.
- **Workflows:** the game uses `comfyui/comfyui-workflow-<kind>.json` per image type (portrait,
  sprite, item, perk).
- **Slots:** node titles containing `<input>=PROMPT|WIDTH|HEIGHT|SEED|MODEL` mark what the game
  fills in. A `UNETLoader` titled `unet_name=MODEL` makes the model menu list diffusion models.
- **Prompts:** `prompts/img_<kind>.txt` is the prompt, with `${DESC}` replaced by the description.
  **Sprites receive only the object's description, not its name.**

## Writing good descriptions for scenario authors

The generator never sees the object's name, so describe the thing in a way that can't be misread.
For example, "bed of roses" can come out as a frame of roses. "Square garden plot of dark soil
planted with pale pink rose bushes, low stone edging" works. Describe one object in one colour
scheme, with no "red or blue" choices.
