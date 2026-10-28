# Better Images: SDXL portraits (add-on)

Portraits only, from an SDXL / Illustrious checkpoint, for an anime look. Load it AFTER another pack. These models follow the game's prose descriptions loosely (age, clothing); the Flux and Qwen packs follow them closely.

## Model files (standard Comfy-Org names)

- `models/checkpoints/sd_xl_base_1.0.safetensors`

## Background removal (sprites and items)

Uses the `Image Rembg (Remove Background)` node from **WAS Node Suite (was-node-suite-comfyui)**. Install it with ComfyUI Manager. Without it every sprite and item request fails.

## Load order

Add-on: in Options -> Mods put it **after** the main pack.

## Different filenames?

Run `python setup_image_mod.py --detect http://<comfyui>:8188` from the bundle folder, or edit the `*_name` values in `comfyui/*.json`. A missing name makes the game fall back to the first model on ComfyUI's list for sprites.
