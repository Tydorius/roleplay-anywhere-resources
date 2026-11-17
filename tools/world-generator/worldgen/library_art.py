"""Shipped sprites for room-library objects (ROOM_LIBRARY_DESIGN.md, "Art").

Sprites live in ``library/sprites/<band>/<object id>.webp`` with an
``index.json`` per band: for each object, the materials and physical text the
art was drawn from, so a template that uses the sprite describes what is drawn,
and whether a person has reviewed it.

``attach_sprites`` puts a built scenario's sprites in place: every object
template whose plan template carries a ``sprite`` gets
``media/<template id>/<template id>-sprite.webp``, and the zip is rebuilt. The
game then shows the shipped art instead of drawing its own.

Item art works the same way (``attach_item_art``): a plan item carrying a
``library`` link (item id, look key and optional tint) gets the shipped
``library/item-sprites/<item>.<look>.webp`` at
``media/<template id>/<template id>-item.webp``, recoloured by ``recolour``
when the link asks for a tint.
"""
import json
import os
import shutil
import zipfile

from .library import LIB_DIR
from .library_items import TINTS

SPRITES_DIR = os.path.join(LIB_DIR, "sprites")
ITEM_SPRITES_DIR = os.path.join(LIB_DIR, "item-sprites")


def load_index(band, root=SPRITES_DIR):
    """{object id: entry} for a band ({} when it has no sprites)."""
    path = os.path.join(root, band, "index.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f).get("objects", {})


def sprite_path(band, object_id, root=SPRITES_DIR):
    return os.path.join(root, band, object_id + ".webp")


def attach_sprites(scenario_dir, plan_data, root=os.path.dirname(LIB_DIR)):
    """Copy shipped sprites into a built scenario and rebuild its zip.
    Returns how many were attached."""
    want = {t["name"]: t["sprite"] for t in plan_data.get("templates", [])
            if t.get("sprite")}
    if not want:
        return 0
    scn_path = os.path.join(scenario_dir, "scenario.json")
    with open(scn_path, "r", encoding="utf-8") as f:
        scn = json.load(f)
    n = 0
    for t in scn.get("objectTemplates", []):
        rel = want.get(t.get("name"))
        if not rel:
            continue
        src = os.path.join(root, rel)
        if not os.path.exists(src):
            continue
        d = os.path.join(scenario_dir, "media", t["id"])
        os.makedirs(d, exist_ok=True)
        shutil.copyfile(src, os.path.join(d, f"{t['id']}-sprite.webp"))
        n += 1
    if n:
        zip_path = scenario_dir.rstrip("\\/") + ".zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for base, _dirs, files in os.walk(scenario_dir):
                for fn in files:
                    full = os.path.join(base, fn)
                    z.write(full, os.path.relpath(full, scenario_dir).replace(os.sep, "/"))
    return n


# ------------------------------------------------------------------ items

def item_sprite_path(item_id, look, root=ITEM_SPRITES_DIR):
    return os.path.join(root, f"{item_id}.{look}.webp")


def recolour(src, dst, tint):
    """Recolour a sprite's strongly coloured pixels toward ``tint`` (one of
    ``library_items.TINTS``): the hue is replaced where the tint names one,
    saturation and value are scaled where it names those, and pixels with
    alpha 0 or HSV saturation at or below 0.25 (greys, pages, metal,
    highlights) keep their colour. Returns True; without Pillow the file is
    copied unchanged and False comes back, so the variant keeps its art.
    Band maths only — a world may recolour dozens of sprites."""
    spec = TINTS.get(tint)
    if spec is None:
        raise ValueError(f"unknown tint {tint!r}; use one of {sorted(TINTS)}")
    try:
        from PIL import Image, ImageChops
    except ImportError:
        shutil.copyfile(src, dst)
        return False
    img = Image.open(src).convert("RGBA")
    h, s, v = img.convert("HSV").split()
    a = img.getchannel("A")
    # the coloured pixels: any alpha, HSV saturation over 0.25 (S/255 > 0.25)
    mask = ImageChops.multiply(a.point(lambda x: 255 if x > 0 else 0),
                               s.point(lambda x: 255 if x > 63 else 0))
    out_h, out_s, out_v = h, s, v
    if "hue" in spec:
        hue8 = int(round(spec["hue"] * 255 / 360.0))
        out_h = Image.composite(h.point(lambda _x: hue8), h, mask)
    if "sat" in spec:
        out_s = Image.composite(s.point(lambda x: int(x * spec["sat"])), s, mask)
    if "val" in spec:
        out_v = Image.composite(v.point(lambda x: int(x * spec["val"])), v, mask)
    out = Image.merge("HSV", (out_h, out_s, out_v)).convert("RGB")
    out.putalpha(a)
    out.save(dst, "WEBP", quality=90)
    return True


def attach_item_art(scenario_dir, plan_data, root=os.path.dirname(LIB_DIR)):
    """Copy shipped item sprites into a built scenario and rebuild its zip,
    mirroring ``attach_sprites``: every item template whose plan item carries
    a ``library`` link gets ``media/<template id>/<template id>-item.webp``,
    recoloured when the link's tint is set. A missing source image is
    skipped without an error. Returns (attached, recoloured)."""
    want = {it["name"]: it["library"] for it in plan_data.get("items", [])
            if isinstance(it, dict) and isinstance(it.get("library"), dict)}
    if not want:
        return 0, 0
    scn_path = os.path.join(scenario_dir, "scenario.json")
    with open(scn_path, "r", encoding="utf-8") as f:
        scn = json.load(f)
    n = tinted = 0
    for t in scn.get("itemTemplates", []):
        lib = want.get(t.get("name"))
        if not lib:
            continue
        src = os.path.join(root, "library", "item-sprites",
                           f"{lib.get('item')}.{lib.get('look')}.webp")
        if not os.path.exists(src):
            continue
        d = os.path.join(scenario_dir, "media", t["id"])
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, f"{t['id']}-item.webp")
        if lib.get("tint"):
            if recolour(src, dst, lib["tint"]):
                tinted += 1
        else:
            shutil.copyfile(src, dst)
        n += 1
    if n:
        zip_path = scenario_dir.rstrip("\\/") + ".zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for base, _dirs, files in os.walk(scenario_dir):
                for fn in files:
                    full = os.path.join(base, fn)
                    z.write(full, os.path.relpath(full, scenario_dir).replace(os.sep, "/"))
    return n, tinted
