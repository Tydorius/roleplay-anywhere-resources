# Better Images: Flux.2 klein

Flux.2 [klein] 9B for every image type: 4 steps, about 15 s per image on a fast GPU. Follows long descriptions closely.

## Model files (standard Comfy-Org names)

- `models/diffusion_models/flux-2-klein-9b.safetensors`
- `models/text_encoders/qwen_3_8b.safetensors`
- `models/vae/flux2-vae.safetensors`

## Background removal (sprites and items)

Uses the `Image Rembg (Remove Background)` node from **WAS Node Suite (was-node-suite-comfyui)**. Install it with ComfyUI Manager. Without it every sprite and item request fails.

## Model menus (Anywhere RPG 1.0)

Options -> AI Images has a menu for portraits, icons (items and perks) and object sprites (map objects; new in 1.0). Each starts on the file this pack names: leave it, or pick another Flux.2 klein model. A model of another family fails or comes out as noise. After switching from another pack, check them again: a pick left from that pack stays, and if this pack's loader lists it too, it is used.

## Different filenames?

Run `python setup_image_mod.py --detect http://<comfyui>:8188` from the bundle folder, or edit the `*_name` values in `comfyui/*.json`. A missing name, with no model picked in the menus, makes the game fall back to the first model on ComfyUI's list.
