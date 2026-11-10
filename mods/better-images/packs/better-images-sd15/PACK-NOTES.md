# Better Images: SD1.5

Any Stable Diffusion 1.5 checkpoint at 512 px for every image type: runs on small GPUs, but follows descriptions the least closely of these packs.

## Model files (standard Comfy-Org names)

- `models/checkpoints/v1-5-pruned-emaonly-fp16.safetensors`

## Background removal (sprites and items)

Uses the `Image Rembg (Remove Background)` node from **WAS Node Suite (was-node-suite-comfyui)**. Install it with ComfyUI Manager. Without it every sprite and item request fails.

## Model menus (Anywhere RPG 1.0)

Options -> AI Images has a menu for portraits, icons (items and perks) and object sprites (map objects; new in 1.0). Each starts on the file this pack names: leave it, or pick another SD1.5 model. A model of another family fails or comes out as noise.

## Different filenames?

Run `python setup_image_mod.py --detect http://<comfyui>:8188` from the bundle folder, or edit the `*_name` values in `comfyui/*.json`. A missing name, with no model picked in the menus, makes the game fall back to the first model on ComfyUI's list.
