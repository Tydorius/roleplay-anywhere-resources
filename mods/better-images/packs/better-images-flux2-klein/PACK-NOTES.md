# Better Images: Flux.2 klein

Flux.2 [klein] 9B for every image type: 4 steps, about 15 s per image on a fast GPU. Follows long descriptions closely.

## Model files (standard Comfy-Org names)

- `models/diffusion_models/flux-2-klein-9b.safetensors`
- `models/text_encoders/qwen_3_8b.safetensors`
- `models/vae/flux2-vae.safetensors`

## Background removal (sprites and items)

Uses the `Image Rembg (Remove Background)` node from **WAS Node Suite (was-node-suite-comfyui)**. Install it with ComfyUI Manager. Without it every sprite and item request fails.

## Different filenames?

Run `python setup_image_mod.py --detect http://<comfyui>:8188` from the bundle folder, or edit the `*_name` values in `comfyui/*.json`. A missing name makes the game fall back to the first model on ComfyUI's list for sprites.
