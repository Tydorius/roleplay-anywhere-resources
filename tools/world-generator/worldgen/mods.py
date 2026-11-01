"""Inject the game-mod data into a built scenario.

The external builder knows nothing of arpgMods: it writes its own fixed
scenario.json and zips the folder. After it runs, the pipeline splices the
spec's ``arpgMods`` into that scenario.json, hardens the boundary (the spec
carried the world-edge slab as passable and one build-time door per storey
so the builder's flat-map walk could cross the strip and reach the storeys;
in play the stairs portals are the storeys' only ways in and nothing crosses
the slab), writes the slab's sprite, and re-zips, so the shipped folder and
zip both carry the floors and portals the generator laid out. (The builder
is never edited.)
"""
import json
import os
import zipfile

from .extensions.floors import BOUNDARY_COLOR, SLAB_NAME


def _seal_floors(scn):
    """Strip every opening on an upper storey's outer border from the built
    scenario: the spec's build-time doors go, the rooms' interior doors
    stay, and the stairs portals become the storeys' only ways in and out."""
    by_name = {r.get("name"): r for r in scn.get("regions", [])}
    ring = set()
    for f in (scn.get("arpgMods") or {}).get("floors") or []:
        area = by_name.get(f.get("area"))
        if area is None:
            continue
        x, y = area.get("position", (0, 0))
        w, h = area.get("size", (0, 0))
        ring |= {(cx, cy) for cx in range(x, x + w) for cy in (y, y + h - 1)}
        ring |= {(cx, cy) for cx in (x, x + w - 1) for cy in range(y, y + h)}
    for r in scn.get("regions", []):
        r["openings"] = [list(c) for c in (r.get("openings") or [])
                         if tuple(c) not in ring]


def _harden_boundary(scn, scenario_dir):
    """The boundary slab ships as it plays: blocking, and carrying a sprite
    the colour of the out-of-bounds void. The spec declared it passable so
    the builder's reachability walk could cross the strip; walkability 0
    seals it here. The sprite is a flat solid-colour WebP the game stretches
    over the whole footprint — with its east edge inset half a cell, so the
    black stops short of the storey walls it touches: the strip's ground
    tint (the same colour) fills that half cell and renders under the walls
    instead of bleeding onto their floors."""
    slab = next((t for t in scn.get("objectTemplates", [])
                 if t.get("name") == SLAB_NAME), None)
    if slab is None:
        return
    slab["walkability"] = 0.0
    w, h = slab.get("size", (24, 100))
    media = os.path.join(scenario_dir, "media", slab["id"])
    os.makedirs(media, exist_ok=True)
    path = os.path.join(media, f"{slab['id']}-sprite.webp")
    rgb = tuple(int(BOUNDARY_COLOR[i:i + 2], 16) for i in (1, 3, 5))
    px, inset = w * 8, 4  # 8 px per cell; half a cell of transparent east edge
    try:
        from PIL import Image
        img = Image.new("RGBA", (px, h * 8), (0, 0, 0, 0))
        img.paste(rgb + (255,), (0, 0, px - inset, h * 8))
        img.save(path, "WEBP", lossless=True)
    except ImportError:
        # no Pillow: a PNG under the .webp name still decodes (the reader
        # sniffs bytes, not extensions), and a solid colour has no artefacts
        import struct
        import zlib
        with open(path, "wb") as f:
            def chunk(tag, data):
                f.write(tag + data)
                f.write(struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
            f.write(b"\x89PNG\r\n\x1a\n")
            chunk(b"IHDR", struct.pack(">IIBBBBB", px, h * 8, 8, 6, 0, 0, 0))
            row = b"\x00" + bytes(rgb + (255,)) * (px - inset) + b"\x00\x00\x00\x00" * inset
            chunk(b"IDAT", zlib.compress(row * (h * 8), 9))
            chunk(b"IEND", b"")


def inject_arpg_mods(scenario_dir, arpg_mods):
    """Write ``arpgMods`` into <scenario_dir>/scenario.json, seal the upper
    storeys, harden and illustrate the boundary slab, and rebuild the zip
    beside the folder. Returns the zip's path."""
    scn_path = os.path.join(scenario_dir, "scenario.json")
    with open(scn_path, "r", encoding="utf-8") as f:
        scn = json.load(f)
    scn["arpgMods"] = arpg_mods
    _seal_floors(scn)
    _harden_boundary(scn, scenario_dir)
    with open(scn_path, "w", encoding="utf-8") as f:
        json.dump(scn, f, ensure_ascii=False, indent=1)
    zip_path = scenario_dir.rstrip("\\/") + ".zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _dirs, files in os.walk(scenario_dir):
            for fn in files:
                full = os.path.join(base, fn)
                z.write(full, os.path.relpath(full, scenario_dir).replace(os.sep, "/"))
    return zip_path
