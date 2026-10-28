# Better Images: Qwen-Image

Qwen-Image (20B) for every image type: the most literal prompt-follower, but slow (20 steps); best on a big GPU.

## Model files (standard Comfy-Org names)

- `models/diffusion_models/qwen_image_2512_fp8_e4m3fn.safetensors`
- `models/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors`
- `models/vae/qwen_image_vae.safetensors`

## Background removal (sprites and items)

Uses the `Image Rembg (Remove Background)` node from **WAS Node Suite (was-node-suite-comfyui)**. Install it with ComfyUI Manager. Without it every sprite and item request fails.

## Different filenames?

Run `python setup_image_mod.py --detect http://<comfyui>:8188` from the bundle folder, or edit the `*_name` values in `comfyui/*.json`. A missing name makes the game fall back to the first model on ComfyUI's list for sprites.
