"""Pull art-review sprites from ComfyUI into library/sprites/<band>/.

The Scenario Editor's image tab queues each sprite on ComfyUI with a tag naming
its workspace and template id. This reads those results straight from
ComfyUI's history (so it works before anyone has kept them in the gallery),
maps each template back to its library object through the art scenario's
manifest, and writes ``<object id>.webp`` plus ``index.json`` (the materials and
physical text the art was drawn from, and ``reviewed``).

  python library-seed/pull_art.py <band> [--comfy URL] [--art DIR] [--work DIR]
                                         [--reviewed] [--kept]

With --kept it copies the images kept in the gallery workspace's media folder
instead (the ones a person approved), marks them reviewed, and rewrites the
band's index from scratch. Otherwise the newest ComfyUI result per template wins. Without --reviewed every entry is marked
reviewed: false, so a later pass knows a person still has to look at it.
"""
import argparse
import io
import json
import os
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(GEN))
sys.path.insert(0, GEN)

from worldgen.library_art import SPRITES_DIR  # noqa: E402


def get(url, timeout=120):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("band")
    ap.add_argument("--comfy", default="http://10.0.0.139:8188")
    ap.add_argument("--art", default=r"E:\Misc Projects\Roleplay Anywhere Scenarios\_library-art")
    ap.add_argument("--work", default=os.path.join(REPO, "mods", "better-images", "gallery-scenarios"))
    ap.add_argument("--reviewed", action="store_true")
    ap.add_argument("--kept", action="store_true")
    a = ap.parse_args()
    if a.kept:
        return pull_kept(a)
    from PIL import Image

    band = a.band
    ws = f"Library-Art-{band.title()}"
    with open(os.path.join(a.work, ws, "scenario.json"), encoding="utf-8") as f:
        names = {t["id"]: t["name"] for t in json.load(f)["objectTemplates"]}
    with open(os.path.join(a.art, band, "manifest.json"), encoding="utf-8") as f:
        manifest = {m["template"]: m for m in json.load(f)["objects"]}
    hist = json.loads(get(a.comfy + "/history?max_items=5000"))
    newest = {}
    for pid, e in hist.items():
        tag = (e.get("prompt", [None] * 4)[3] or {}).get("anywhere_rpg_gallery") or {}
        if tag.get("source") != f"work/{ws}" or tag.get("kind") != "sprite":
            continue
        if e.get("status", {}).get("status_str") == "error":
            continue
        imgs = [i for o in e.get("outputs", {}).values() for i in o.get("images", [])
                if i.get("type") == "output"]
        if not imgs:
            continue
        stamp = max((m[1].get("timestamp", 0) for m in e.get("status", {}).get("messages", [])),
                    default=0)
        if tag["id"] not in newest or stamp > newest[tag["id"]][0]:
            newest[tag["id"]] = (stamp, pid, imgs[0])
    out = os.path.join(SPRITES_DIR, band)
    os.makedirs(out, exist_ok=True)
    idx_path = os.path.join(out, "index.json")
    index = {}
    if os.path.exists(idx_path):
        with open(idx_path, encoding="utf-8") as f:
            index = json.load(f).get("objects", {})
    pulled = missing = 0
    for tid, (_stamp, pid, img) in sorted(newest.items()):
        m = manifest.get(names.get(tid))
        if m is None:
            missing += 1
            continue
        q = urllib.parse.urlencode({k: img[k] for k in ("filename", "subfolder", "type")})
        png = get(a.comfy + "/view?" + q)
        im = Image.open(io.BytesIO(png))
        im = im.convert("RGBA")
        im.save(os.path.join(out, m["object"] + ".webp"), "WEBP", quality=90, method=6)
        index[m["object"]] = {"template": m["template"], "tier": m["tier"],
                              "condition": m["condition"], "materials": m["materials"],
                              "physical": m["physical"], "comfyPrompt": pid,
                              "reviewed": bool(a.reviewed)}
        pulled += 1
    with open(idx_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"band": band, "objects": dict(sorted(index.items()))}, f, indent=1,
                  ensure_ascii=False)
        f.write("\n")
    print(f"{band}: {pulled} sprites pulled into {out} ({len(manifest)} objects in the "
          f"manifest, {missing} results with no manifest entry)")


def pull_kept(a):
    """Copy the workspace's kept sprites into the library as reviewed."""
    import shutil
    band = a.band
    ws = os.path.join(a.work, f"Library-Art-{band.title()}")
    with open(os.path.join(ws, "scenario.json"), encoding="utf-8") as f:
        tmpls = json.load(f)["objectTemplates"]
    with open(os.path.join(a.art, band, "manifest.json"), encoding="utf-8") as f:
        manifest = {m["template"]: m for m in json.load(f)["objects"]}
    out = os.path.join(SPRITES_DIR, band)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    index, missing = {}, []
    for t in tmpls:
        m = manifest.get(t["name"])
        src = os.path.join(ws, "media", t["id"], f"{t['id']}-sprite.webp")
        if m is None or not os.path.exists(src):
            missing.append(t["name"])
            continue
        shutil.copyfile(src, os.path.join(out, m["object"] + ".webp"))
        index[m["object"]] = {"template": m["template"], "tier": m["tier"],
                              "condition": m["condition"], "materials": m["materials"],
                              "physical": m["physical"], "reviewed": True}
    with open(os.path.join(out, "index.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"band": band, "objects": dict(sorted(index.items()))}, f, indent=1,
                  ensure_ascii=False)
        f.write("\n")
    print(f"{band}: {len(index)} kept sprites copied into {out}; {len(missing)} without one"
          + (": " + ", ".join(missing) if missing else ""))


if __name__ == "__main__":
    main()
