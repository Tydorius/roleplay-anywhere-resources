# Better Images: Flux.1

Flux.1 [dev] or [schnell] for every image type: 20 steps (use 4 for schnell). Good prompt following; slower than Flux.2 klein.

## Model files (standard Comfy-Org names)

- `models/diffusion_models/flux1-dev.safetensors`
- `models/text_encoders/clip_l.safetensors`
- `models/text_encoders/t5xxl_fp16.safetensors`
- `models/vae/ae.safetensors`

## Background removal (sprites and items)

Uses the `Image Rembg (Remove Background)` node from **WAS Node Suite (was-node-suite-comfyui)**. Install it with ComfyUI Manager. Without it every sprite and item request fails.

## Different filenames?

Run `python setup_image_mod.py --detect http://<comfyui>:8188` from the bundle folder, or edit the `*_name` values in `comfyui/*.json`. A missing name makes the game fall back to the first model on ComfyUI's list for sprites.
