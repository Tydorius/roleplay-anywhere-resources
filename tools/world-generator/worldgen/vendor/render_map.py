"""Render a scenario.json (or a .scenario folder) to a PNG preview for eyeballing layouts.

Usage: python worldgen/vendor/render_map.py <scenario.json|folder> [out.png] [--cell 8]

Regions are outlined (walls thick, hostile red), door openings yellow, objects grey,
NPCs blue, hostiles red, the player green. y grows upward like the game.
Also writes <out>-portraits.png: a contact sheet of every portrait in media/.
"""
import json
import os
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:  # previews are skipped without Pillow; the rest of the
    Image = ImageDraw = None  # pipeline works without it


def main():
    if Image is None:
        print("Pillow is not installed; map previews are skipped "
              "(optional: pip install Pillow)")
        return
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    cell = int(sys.argv[sys.argv.index("--cell") + 1]) if "--cell" in sys.argv else 8
    src = args[0]
    root = src if os.path.isdir(src) else os.path.dirname(src)
    path = os.path.join(src, "scenario.json") if os.path.isdir(src) else src
    out = args[1] if len(args) > 1 and not args[1].isdigit() else os.path.join(root, "map-preview.png")
    s = json.load(open(path, encoding="utf-8"))
    W, H = s["gridSize"]
    img = Image.new("RGB", (W * cell, H * cell), (60, 80, 50))
    d = ImageDraw.Draw(img)

    def box(x, y, w, h):  # grid rect -> image rect (flip y)
        return [x * cell, (H - y - h) * cell, (x + w) * cell - 1, (H - y) * cell - 1]

    tex = {"grass": (70, 95, 55), "undergrowth": (45, 70, 40), "dirt": (110, 90, 60), "mud": (90, 75, 50),
           "rock": (120, 115, 105), "gravel": (130, 125, 110), "cobblestone": (140, 135, 120), "sand": (190, 170, 120),
           "flagstone-light": (165, 160, 150), "flagstone-dark": (95, 95, 100), "tile-marble": (200, 195, 185),
           "floorboards": (140, 105, 70), "parquet": (125, 90, 60), "carpet-red": (130, 45, 45), "carpet-blue": (50, 60, 120),
           "carpet-green": (50, 95, 60), "tile-slate": (85, 90, 100), "tile-ceramic": (175, 175, 165), "metal-deck": (110, 115, 120),
           "concrete": (150, 150, 145)}
    regions = sorted(s["regions"], key=lambda r: -(r["size"][0] * r["size"][1]))
    for r in regions:
        fill = tex.get(r.get("groundTexture"), (150, 130, 100) if r.get("wall") else (100, 110, 80))
        d.rectangle(box(*r["position"], *r["size"]), fill=fill,
                    outline=(200, 40, 40) if r.get("hostile") else (30, 30, 30), width=3 if r.get("wall") else 1)
    for r in regions:
        for ox, oy in r.get("openings", []):
            d.rectangle(box(ox, oy, 1, 1), fill=(240, 220, 60))
    tags = {t["id"]: t.get("tags", []) for t in s.get("objectTemplates", [])}
    for e in s["entities"]:
        x, y = e["pos"]
        w, h = e["size"]
        if e["type"] == "object":
            plant = "plant" in tags.get(e.get("templateId"), ())
            d.rectangle(box(x, y, w, h), fill=(30, 55, 30) if plant else (85, 85, 85), outline=(40, 40, 40))
    for e in s["entities"]:
        if e["type"] != "object":
            col = (60, 220, 60) if e["type"] == "player" else (220, 50, 50) if e.get("hostile") else (70, 140, 255)
            d.ellipse(box(*e["pos"], 1, 1), fill=col)
    for r in regions:
        x, y = r["position"]
        d.text((x * cell + 2, (H - y - r["size"][1]) * cell + 1), r["name"][:22], fill=(255, 255, 255))
    img.save(out)
    print("map", out)

    media = os.path.join(root, "media")
    names = {e["id"]: e["name"] for e in s["entities"]}
    ports = []
    if os.path.isdir(media):
        for eid in sorted(os.listdir(media)):
            f = os.path.join(media, eid, f"{eid}-portrait.webp")
            if os.path.exists(f):
                ports.append((names.get(eid, eid), f))
    if ports:
        t = 160
        cols = 6
        sheet = Image.new("RGB", (cols * t, ((len(ports) + cols - 1) // cols) * (t + 14)), (20, 20, 20))
        sd = ImageDraw.Draw(sheet)
        for i, (n, f) in enumerate(ports):
            im = Image.open(f).convert("RGB").resize((t, t))
            x, y = (i % cols) * t, (i // cols) * (t + 14)
            sheet.paste(im, (x, y))
            sd.text((x + 2, y + t), n[:24], fill=(230, 230, 230))
        p = os.path.splitext(out)[0] + "-portraits.png"
        sheet.save(p)
        print("portraits", p)


if __name__ == "__main__":
    main()
