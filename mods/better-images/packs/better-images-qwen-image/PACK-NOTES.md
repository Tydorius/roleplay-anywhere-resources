# Better Images: Qwen-Image

Qwen-Image (20B) for every image type: the most literal prompt-follower, but slow (20 steps); best on a big GPU.

## Model files (standard Comfy-Org names)

- `models/diffusion_models/qwen_image_2512_fp8_e4m3fn.safetensors`
- `models/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors`
- `models/vae/qwen_image_vae.safetensors`

## Background removal (sprites and items)

Uses the `Image Rembg (Remove Background)` node from **WAS Node Suite (was-node-suite-comfyui)**. Install it with ComfyUI Manager. Without it every sprite and item request fails.

## Model menus (Anywhere RPG 1.0)

Options -> AI Images has a menu for portraits, icons (items and perks) and object sprites (map objects; new in 1.0). Each starts on the file this pack names: leave it, or pick another Qwen-Image model. A model of another family fails or comes out as noise. After switching from another pack, check them again: a pick left from that pack stays, and if this pack's loader lists it too, it is used.

## Different filenames?

Run `python setup_image_mod.py --detect http://<comfyui>:8188` from the bundle folder, or edit the `*_name` values in `comfyui/*.json`. A missing name, with no model picked in the menus, makes the game fall back to the first model on ComfyUI's list.
