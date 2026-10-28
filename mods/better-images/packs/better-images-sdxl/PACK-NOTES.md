# Better Images: SDXL

Any SDXL checkpoint at 1024 px for every image type (the game's default workflow is SD1.5 at 512 px). Pick checkpoints per type in Options -> AI Images.

## Model files (standard Comfy-Org names)

- `models/checkpoints/sd_xl_base_1.0.safetensors`

## Background removal (sprites and items)

Uses the `Image Rembg (Remove Background)` node from **WAS Node Suite (was-node-suite-comfyui)**. Install it with ComfyUI Manager. Without it every sprite and item request fails.

## Different filenames?

Run `python setup_image_mod.py --detect http://<comfyui>:8188` from the bundle folder, or edit the `*_name` values in `comfyui/*.json`. A missing name makes the game fall back to the first model on ComfyUI's list for sprites.
