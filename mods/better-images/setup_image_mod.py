#!/usr/bin/env python3
"""Better Images for Anywhere RPG: writes ComfyUI mod packs, one per model family.

    python setup_image_mod.py                      # rewrite packs/ with standard Comfy-Org filenames
    python setup_image_mod.py --detect URL         # match model files on that ComfyUI and write packs/ to fit
    python setup_image_mod.py --detect URL --install            # ...and copy them into the game's mods folder
    python setup_image_mod.py --detect URL --remover rembg      # pick the background remover (see REMOVERS)

Standard library only. --detect only reads from ComfyUI (GET /object_info); it never queues work.

How the game uses a pack (Anywhere RPG, ComfyUI image service):
  * comfyui/comfyui-workflow-<kind>.json is used for kind = portrait | sprite | item | perk,
    else comfyui/comfyui-workflow.json.
  * Node titles containing <input>=PROMPT|WIDTH|HEIGHT|SEED|MODEL mark the inputs the game fills.
    WIDTH/HEIGHT scale from the largest value in the file by the requested aspect.
  * MODEL drives the per-kind model menu (Options -> AI Images): portrait and icon (items, perks).
    Sprites have no menu: they use the file named here, or the FIRST model on the list if it is
    missing. Run --detect so that name exists.
  * prompts/img_<kind>.txt is the prompt, with ${DESC} = the thing's physicalDescription.
"""
import argparse, json, os, re, shutil, sys, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKS_DIR = HERE / "packs"
KINDS = ("sprite", "item", "perk", "portrait")
BASE = 1024
# Sprites and items need a transparent background; the Official image service removes it
# server-side, ComfyUI does not.
CUTOUT_KINDS = ("sprite", "item")

# ---------------------------------------------------------------- background removers
# node: ComfyUI class; pack: where it comes from; default model; how to wire it.
REMOVERS = {
    "rembg": {"node": "Image Rembg (Remove Background)",
              "pack": "WAS Node Suite (was-node-suite-comfyui)",
              "build": lambda img: {"class_type": "Image Rembg (Remove Background)", "inputs": {
                  "images": img, "transparency": True, "model": "isnet-general-use",
                  "post_processing": False, "only_mask": False, "alpha_matting": False,
                  "alpha_matting_foreground_threshold": 240, "alpha_matting_background_threshold": 10,
                  "alpha_matting_erode_size": 10, "background_color": "none"}}},
    "ben2": {"node": "RMBG", "pack": "ComfyUI-RMBG (1038lab)",
             "build": lambda img: {"class_type": "RMBG", "inputs": {
                 "image": img, "model": "BEN2", "sensitivity": 1.0, "process_res": 1024, "mask_blur": 0,
                 "mask_offset": 0, "invert_output": False, "refine_foreground": False,
                 "background": "Alpha", "background_color": "#222222"}}},
    "none": {"node": None, "pack": None, "build": None},
}
DEFAULT_REMOVER = "rembg"

# ---------------------------------------------------------------- prompts
NATURAL = {  # for models with an LLM text encoder (Flux.2, Qwen-Image): plain sentences
    "sprite": "A single game map prop seen from directly overhead in a straight-down orthographic top-down "
              "view: ${DESC}. The object is centered and isolated on a plain white background with nothing "
              "else around it. Hand-painted fantasy RPG asset, natural muted colours, soft even lighting, "
              "no cast shadow, no text.",
    "item": "A single inventory item icon: ${DESC}. The object is centered and isolated on a plain white "
            "background, shown whole with a clean silhouette. Detailed painted fantasy RPG item illustration, "
            "natural colours, soft studio lighting, no text.",
    "perk": "A square fantasy RPG ability icon: ${DESC}. One bold central emblem, painterly style, strong rim "
            "lighting, dark vignette background, no text or letters.",
    "portrait": "Painted fantasy RPG character portrait, head and shoulders, looking at the viewer, detailed "
                "face, soft painterly lighting, simple muted background, no text. ${DESC}",
}
TAGS = {  # for SDXL / Illustrious checkpoints (CLIP encoders): short tag-style phrases
    "sprite": "top-down view, overhead, game asset, single object, isolated, centered, white background, "
              "hand-painted, fantasy rpg prop, ${DESC}",
    "item": "game item icon, single object, isolated, centered, white background, detailed painting, "
            "fantasy rpg, ${DESC}",
    "perk": "fantasy rpg skill icon, single emblem, centered, painterly, rim lighting, dark vignette, ${DESC}",
    # Illustrious-family checkpoints drift into NSFW and multi-view sheets without explicit
    # "solo", clothing and rating tags; plain SDXL ignores the tags it doesn't know.
    "portrait": "masterpiece, best quality, solo, portrait, upper body, looking at viewer, fully clothed, "
                "detailed face, simple background, general, safe, ${DESC}",
}
SDXL_NEG = {
    "sprite": "perspective, isometric, side view, horizon, landscape, scenery, room, multiple objects, collage, "
              "sprite sheet, pixel art, cast shadow, person",
    "item": "multiple objects, collage, hands, person, scenery, table, cast shadow",
    "perk": "letters, words, user interface, screenshot, photo",
    # The game's portrait prompt can't say whether it is a man or a woman, so the packs name every
    # "more than one person" tag; image_gallery.py adds the exact subject per character.
    "portrait": "nsfw, nude, nipples, cleavage, underwear, lewd, ahegao, multiple views, character sheet, "
                "reference sheet, expression sheet, comic, grid, collage, multiple people, two people, 2girls, "
                "2boys, multiple girls, multiple boys, group, crowd, bad anatomy, bad hands, extra fingers, "
                "missing fingers, extra limbs, cropped head",
}
SDXL_NEG_COMMON = "text, watermark, signature, logo, frame, border, blurry, lowres, jpeg artifacts, worst quality, low quality"

# ---------------------------------------------------------------- model families
# Each "files" role: standard Comfy-Org filename, the loader node/input listing it, and the
# regex --detect matches against that list (case-insensitive, first hit wins, order = preference).
FAMILIES = {
    "flux2-klein": {
        "title": "Better Images: Flux.2 klein",
        "summary": "Flux.2 [klein] 9B for every image type: 4 steps, about 15 s per image on a fast GPU. "
                   "Follows long descriptions closely.",
        "kinds": KINDS,
        "prompts": NATURAL,
        "files": {
            "unet": ("flux-2-klein-9b.safetensors", "UNETLoader", "unet_name",
                     [r"flux-?2-klein-9b(?!.*base)", r"flux-?2-klein(?!.*base)"]),
            "clip": ("qwen_3_8b.safetensors", "CLIPLoader", "clip_name", [r"qwen_?3_8b"]),
            "vae": ("flux2-vae.safetensors", "VAELoader", "vae_name", [r"flux2-vae"]),
        },
        "folders": {"unet": "models/diffusion_models", "clip": "models/text_encoders", "vae": "models/vae"},
        "graph": "flux2",
    },
    "qwen-image": {
        "title": "Better Images: Qwen-Image",
        "summary": "Qwen-Image (20B) for every image type: the most literal prompt-follower, but slow "
                   "(20 steps); best on a big GPU.",
        "kinds": KINDS,
        "prompts": NATURAL,
        "files": {
            "unet": ("qwen_image_2512_fp8_e4m3fn.safetensors", "UNETLoader", "unet_name",
                     [r"qwen_image_2512", r"qwen_image(?!_edit)(?!.*layered)"]),
            "clip": ("qwen_2.5_vl_7b_fp8_scaled.safetensors", "CLIPLoader", "clip_name", [r"qwen_2\.5_vl_7b"]),
            "vae": ("qwen_image_vae.safetensors", "VAELoader", "vae_name", [r"qwen_image_vae"]),
        },
        "folders": {"unet": "models/diffusion_models", "clip": "models/text_encoders", "vae": "models/vae"},
        "graph": "qwen",
    },
    "flux1": {
        "title": "Better Images: Flux.1",
        "summary": "Flux.1 [dev] or [schnell] for every image type: 20 steps (use 4 for schnell). Good prompt "
                   "following; slower than Flux.2 klein.",
        "kinds": KINDS,
        "prompts": NATURAL,
        "files": {
            "unet": ("flux1-dev.safetensors", "UNETLoader", "unet_name",
                     [r"flux1-dev", r"flux1-schnell", r"flux1", r"flux\.1"]),
            "clip_l": ("clip_l.safetensors", "DualCLIPLoader", "clip_name1", [r"clip_l"]),
            "t5": ("t5xxl_fp16.safetensors", "DualCLIPLoader", "clip_name2", [r"t5xxl_fp16", r"t5xxl"]),
            "vae": ("ae.safetensors", "VAELoader", "vae_name", [r"(^|/)ae\.safetensors", r"flux.*ae"]),
        },
        "folders": {"unet": "models/diffusion_models", "clip_l": "models/text_encoders",
                    "t5": "models/text_encoders", "vae": "models/vae"},
        "graph": "flux1",
    },
    "sdxl": {
        "title": "Better Images: SDXL",
        "summary": "Any SDXL checkpoint at 1024 px for every image type (the game's default workflow is "
                   "SD1.5 at 512 px). Pick checkpoints per type in Options -> AI Images.",
        "kinds": KINDS,
        "prompts": TAGS,
        "files": {
            "ckpt": ("sd_xl_base_1.0.safetensors", "CheckpointLoaderSimple", "ckpt_name",
                     [r"juggernaut.*xl", r"sd_xl_base", r"xl"]),
        },
        "folders": {"ckpt": "models/checkpoints"},
        "graph": "sdxl",
    },
    "sdxl-portraits": {
        "title": "Better Images: SDXL portraits (add-on)",
        "summary": "Portraits only, from an SDXL / Illustrious checkpoint, for an anime look. Load it AFTER "
                   "another pack. These models follow the game's prose descriptions loosely (age, clothing); "
                   "the Flux and Qwen packs follow them closely.",
        "kinds": ("portrait",),
        "prompts": TAGS,
        "files": {
            "ckpt": ("sd_xl_base_1.0.safetensors", "CheckpointLoaderSimple", "ckpt_name",
                     [r"illustrious", r"xl"]),
        },
        "folders": {"ckpt": "models/checkpoints"},
        "graph": "sdxl",
    },
    "sd15": {
        "title": "Better Images: SD1.5",
        "summary": "Any Stable Diffusion 1.5 checkpoint at 512 px for every image type: runs on small GPUs, "
                   "but follows descriptions the least closely of these packs.",
        "kinds": KINDS,
        "prompts": TAGS,
        "files": {
            "ckpt": ("v1-5-pruned-emaonly-fp16.safetensors", "CheckpointLoaderSimple", "ckpt_name",
                     [r"v1-5", r"sd_?1\.?5", r"sd15"]),
        },
        "folders": {"ckpt": "models/checkpoints"},
        "graph": "sdxl",
        "base": 512,
        "ksampler": {"steps": 25, "cfg": 7.0},
    },
}

SIZE_TITLE = "width=WIDTH height=HEIGHT"


def _size(base=BASE):
    return {"width": base, "height": base}


def graph_flux2(f, kind, fam):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": f["unet"], "weight_dtype": "default"},
              "_meta": {"title": "Load Diffusion Model unet_name=MODEL"}},
        "10": {"class_type": "CLIPLoader", "inputs": {"clip_name": f["clip"], "type": "flux2", "device": "default"},
               "_meta": {"title": "Load Text Encoder"}},
        "11": {"class_type": "VAELoader", "inputs": {"vae_name": f["vae"]}, "_meta": {"title": "Load VAE"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["10", 0]},
              "_meta": {"title": "Positive text=PROMPT"}},
        "3": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["2", 0]},
              "_meta": {"title": "Empty negative"}},
        "12": {"class_type": "CFGGuider", "inputs": {"model": ["1", 0], "positive": ["2", 0],
                                                      "negative": ["3", 0], "cfg": 1.0},
               "_meta": {"title": "CFG Guider"}},
        "4": {"class_type": "EmptyFlux2LatentImage", "inputs": {**_size(), "batch_size": 1},
              "_meta": {"title": "Empty Latent " + SIZE_TITLE}},
        "13": {"class_type": "Flux2Scheduler", "inputs": {"steps": 4, **_size()},
               "_meta": {"title": "Flux2 Scheduler " + SIZE_TITLE}},
        "14": {"class_type": "RandomNoise", "inputs": {"noise_seed": 0}, "_meta": {"title": "Noise noise_seed=SEED"}},
        "15": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}, "_meta": {"title": "Sampler"}},
        "5": {"class_type": "SamplerCustomAdvanced",
              "inputs": {"noise": ["14", 0], "guider": ["12", 0], "sampler": ["15", 0], "sigmas": ["13", 0],
                         "latent_image": ["4", 0]}, "_meta": {"title": "Sample"}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["11", 0]},
              "_meta": {"title": "VAE Decode"}},
    }


def graph_flux1(f, kind, fam):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": f["unet"], "weight_dtype": "default"},
              "_meta": {"title": "Load Diffusion Model unet_name=MODEL"}},
        "10": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": f["clip_l"], "clip_name2": f["t5"],
                                                          "type": "flux", "device": "default"},
               "_meta": {"title": "Load Text Encoders"}},
        "11": {"class_type": "VAELoader", "inputs": {"vae_name": f["vae"]}, "_meta": {"title": "Load VAE"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["10", 0]},
              "_meta": {"title": "Positive text=PROMPT"}},
        "12": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["2", 0], "guidance": 3.5},
               "_meta": {"title": "Guidance"}},
        "3": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["2", 0]},
              "_meta": {"title": "Empty negative"}},
        "4": {"class_type": "EmptySD3LatentImage", "inputs": {**_size(), "batch_size": 1},
              "_meta": {"title": "Empty Latent " + SIZE_TITLE}},
        "5": {"class_type": "KSampler",
              "inputs": {"seed": 0, "steps": 20, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
                         "denoise": 1, "model": ["1", 0], "positive": ["12", 0], "negative": ["3", 0],
                         "latent_image": ["4", 0]}, "_meta": {"title": "KSampler seed=SEED"}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["11", 0]},
              "_meta": {"title": "VAE Decode"}},
    }


def graph_qwen(f, kind, fam):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": f["unet"], "weight_dtype": "default"},
              "_meta": {"title": "Load Diffusion Model unet_name=MODEL"}},
        "10": {"class_type": "CLIPLoader", "inputs": {"clip_name": f["clip"], "type": "qwen_image", "device": "default"},
               "_meta": {"title": "Load Text Encoder"}},
        "11": {"class_type": "VAELoader", "inputs": {"vae_name": f["vae"]}, "_meta": {"title": "Load VAE"}},
        "12": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.1},
               "_meta": {"title": "Shift"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["10", 0]},
              "_meta": {"title": "Positive text=PROMPT"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["10", 0]},
              "_meta": {"title": "Negative"}},
        "4": {"class_type": "EmptySD3LatentImage", "inputs": {**_size(), "batch_size": 1},
              "_meta": {"title": "Empty Latent " + SIZE_TITLE}},
        "5": {"class_type": "KSampler",
              "inputs": {"seed": 0, "steps": 20, "cfg": 2.5, "sampler_name": "euler", "scheduler": "simple",
                         "denoise": 1, "model": ["12", 0], "positive": ["2", 0], "negative": ["3", 0],
                         "latent_image": ["4", 0]}, "_meta": {"title": "KSampler seed=SEED"}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["11", 0]},
              "_meta": {"title": "VAE Decode"}},
    }


def graph_sdxl(f, kind, fam):
    ks = {"steps": 28, "cfg": 5.5, **fam.get("ksampler", {})}
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": f["ckpt"]},
              "_meta": {"title": "Load Checkpoint ckpt_name=MODEL"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["1", 1]},
              "_meta": {"title": "Positive text=PROMPT"}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": f"{SDXL_NEG[kind]}, {SDXL_NEG_COMMON}", "clip": ["1", 1]},
              "_meta": {"title": "Negative"}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {**_size(fam.get("base", BASE)), "batch_size": 1},
              "_meta": {"title": "Empty Latent Image " + SIZE_TITLE}},
        "5": {"class_type": "KSampler",
              "inputs": {"seed": 0, "steps": ks["steps"], "cfg": ks["cfg"], "sampler_name": "dpmpp_2m", "scheduler": "karras",
                         "denoise": 1, "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
                         "latent_image": ["4", 0]}, "_meta": {"title": "KSampler seed=SEED"}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
              "_meta": {"title": "VAE Decode"}},
    }


GRAPHS = {"flux2": graph_flux2, "flux1": graph_flux1, "qwen": graph_qwen, "sdxl": graph_sdxl}


def workflow(fam, files, kind, remover):
    wf = GRAPHS[fam["graph"]](files, kind, fam)
    image = ["6", 0]
    rm = REMOVERS[remover]
    if kind in CUTOUT_KINDS and rm["build"]:
        wf["8"] = {**rm["build"](image), "_meta": {"title": "Remove background"}}
        image = ["8", 0]
    wf["7"] = {"class_type": "SaveImage", "inputs": {"images": image, "filename_prefix": f"anywhere-rpg-{kind}"},
               "_meta": {"title": "Save Image"}}
    return wf


# ---------------------------------------------------------------- detection
def comfy_info(url):
    with urllib.request.urlopen(url.rstrip("/") + "/object_info", timeout=60) as r:
        return json.load(r)


def options(info, node, inp):
    spec = info.get(node, {}).get("input", {})
    spec = spec.get("required", {}).get(inp) or spec.get("optional", {}).get(inp)
    if not spec:
        return []
    if isinstance(spec[0], list):
        return spec[0]
    return (spec[1] or {}).get("options", []) if len(spec) > 1 else []


def detect(info, fam):
    """Returns ({role: filename}, [missing roles])."""
    found, missing = {}, []
    for role, (std, node, inp, patterns) in fam["files"].items():
        names = options(info, node, inp)
        hit = std if std in names else None
        for pat in patterns:
            if hit:
                break
            hit = next((n for n in names if re.search(pat, n, re.I)), None)
        if hit:
            found[role] = hit
        else:
            found[role] = std
            missing.append(role)
    return found, missing


def pick_remover(info, wanted):
    if wanted:
        return wanted
    for name, rm in REMOVERS.items():
        if rm["node"] and rm["node"] in info:
            return name
    return "none"


# ---------------------------------------------------------------- writing
def notes(key, fam, files, remover, detected_from=None):
    rm = REMOVERS[remover]
    lines = [f"# {fam['title']}", "", fam["summary"], "",
             "## Model files" + (f" (detected on {detected_from})" if detected_from else " (standard Comfy-Org names)"), ""]
    for role, name in files.items():
        lines.append(f"- `{fam['folders'][role]}/{name}`")
    lines += ["", "## Background removal (sprites and items)", ""]
    if rm["node"]:
        lines.append(f"Uses the `{rm['node']}` node from **{rm['pack']}**. Install it with ComfyUI Manager. "
                     "Without it every sprite and item request fails.")
    else:
        lines.append("None: sprites and items keep their white background.")
    if "portrait" not in fam["kinds"] or len(fam["kinds"]) < 4:
        lines += ["", "## Load order", "", "Add-on: in Options -> Mods put it **after** the main pack."]
    lines += ["", "## Different filenames?", "",
              "Run `python setup_image_mod.py --detect http://<comfyui>:8188` from the bundle folder, or edit the "
              "`*_name` values in `comfyui/*.json`. A missing name makes the game fall back to the first model "
              "on ComfyUI's list for sprites.", ""]
    return "\n".join(lines)


def write_pack(key, fam, files, remover, detected_from=None, dest=PACKS_DIR):
    out = dest / f"better-images-{key}"
    if out.exists():
        shutil.rmtree(out)
    (out / "comfyui").mkdir(parents=True)
    (out / "prompts").mkdir()
    for kind in fam["kinds"]:
        (out / "comfyui" / f"comfyui-workflow-{kind}.json").write_text(
            json.dumps(workflow(fam, files, kind, remover), indent=2) + "\n", "utf-8")
        (out / "prompts" / f"img_{kind}.txt").write_text(fam["prompts"][kind] + "\n", "utf-8")
    if len(fam["kinds"]) == len(KINDS):  # whole pack: also replace the catch-all workflow
        (out / "comfyui" / "comfyui-workflow.json").write_text(
            json.dumps(workflow(fam, files, "perk", remover), indent=2) + "\n", "utf-8")
    dep = REMOVERS[remover]["pack"]
    (out / "mod-info.json").write_text(json.dumps({
        "title": fam["title"],
        "description": fam["summary"] + (f" Needs {dep} for background removal." if dep and
                                          set(fam["kinds"]) & set(CUTOUT_KINDS) else "")}, indent=2) + "\n", "utf-8")
    (out / "PACK-NOTES.md").write_text(notes(key, fam, files, remover, detected_from), "utf-8")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--detect", metavar="URL", help="ComfyUI address to read model lists from")
    ap.add_argument("--remover", choices=sorted(REMOVERS), help=f"background remover (default: {DEFAULT_REMOVER}, "
                    "or with --detect the first one installed)")
    ap.add_argument("--packs", nargs="+", choices=sorted(FAMILIES), default=sorted(FAMILIES))
    ap.add_argument("--out", type=Path, default=PACKS_DIR, help="where to write the packs (default: ./packs)")
    ap.add_argument("--install", action="store_true", help="copy the packs into the game's mods folder")
    ap.add_argument("--mods-dir", type=Path, help="the game's mods folder (default: per-OS Anywhere RPG location)")
    a = ap.parse_args()

    info = comfy_info(a.detect) if a.detect else None
    remover = pick_remover(info, a.remover) if info else (a.remover or DEFAULT_REMOVER)
    if info and REMOVERS[remover]["node"] and REMOVERS[remover]["node"] not in info:
        print(f"! {remover}: node '{REMOVERS[remover]['node']}' is not installed on {a.detect}")
    written = []
    for key in a.packs:
        fam = FAMILIES[key]
        if info:
            files, missing = detect(info, fam)
        else:
            files, missing = {r: v[0] for r, v in fam["files"].items()}, []
        out = write_pack(key, fam, files, remover, a.detect, a.out)
        written.append(out)
        state = f"MISSING {', '.join(missing)} (kept standard name)" if missing else "ok"
        print(f"{out.name:34} {state:12} " + ", ".join(f"{r}={n}" for r, n in files.items()))
    print(f"background remover: {remover}")

    if a.install:
        mods = a.mods_dir or {
            "win32": Path(os.environ.get("APPDATA", "")) / "Anywhere RPG" / "mods",
            "darwin": Path.home() / "Library" / "Application Support" / "Anywhere RPG" / "mods",
        }.get(sys.platform, Path.home() / ".config" / "Anywhere RPG" / "mods")
        mods.mkdir(parents=True, exist_ok=True)
        for out in written:
            dst = mods / out.name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(out, dst)
            print("installed", dst)
        print("Enable the pack(s) in Options -> Mods, then check Options -> AI Images.")


if __name__ == "__main__":
    main()
