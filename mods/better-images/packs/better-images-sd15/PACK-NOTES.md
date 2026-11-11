# Better Images: SD1.5

Any Stable Diffusion 1.5 checkpoint at 512 px for every image type: runs on small GPUs, but follows descriptions the least closely of these packs.

**Status:** Checked in Anywhere RPG 1.0 with `dreamshaper_8` and `realisticVisionV60B1_v60B1VAE`: all four image types generate at 512 px, with map objects and items cut out. Limits: on both, map objects come out as front or perspective views, not top-down (SD1.5 doesn't follow the overhead framing), and a photo model such as Realistic Vision draws modern photographs. A painterly checkpoint (DreamShaper 8) suits the game; for top-down map objects, use another pack if your GPU allows.

## Model files (standard Comfy-Org names)

- `models/checkpoints/v1-5-pruned-emaonly-fp16.safetensors`

## Background removal (sprites and items)

Uses the `Image Rembg (Remove Background)` node from **WAS Node Suite (was-node-suite-comfyui)**. Install it with ComfyUI Manager. Without it every sprite and item request fails.

## Model menus (Anywhere RPG 1.0)

Options -> AI Images has a menu for portraits, icons (items and perks) and object sprites (map objects; new in 1.0). Each starts on the file this pack names: leave it, or pick another SD1.5 model. A model of another family fails or comes out as noise. After switching from another pack, check them again: a pick left from that pack stays, and if this pack's loader lists it too, it is used.

## Different filenames?

Run `python setup_image_mod.py --detect http://<comfyui>:8188` from the bundle folder, or edit the `*_name` values in `comfyui/*.json`. A missing name, with no model picked in the menus, makes the game fall back to the first model on ComfyUI's list.
