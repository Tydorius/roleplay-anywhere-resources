"""Mark which item sprites recolour well in library/item-sprites/index.json.

``library_art.recolour`` shifts only a sprite's strongly coloured pixels, so
a recolour reads clearly when the colour is most of the drawing and shares
one hue (books, bottles, cloth, potions, gems), and not when the pixels are
mostly grey or the hue is spread over the wheel. For every sprite this
measures, among the pixels with alpha, the share with HSV saturation over
0.25 and the circular standard deviation of those pixels' hue, then writes
``"tintable": true|false`` (share >= 0.30 and std <= 25 degrees) into the
sprite's index entry, keeping every other field.

  python library-seed/mark_tintable.py [--dir DIR]

Prints the totals and the 20 most and least tintable ids, ranked by share
then hue concentration, for a person to sanity-check.
"""
import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.dirname(HERE)
sys.path.insert(0, GEN)

from worldgen.library import LIB_DIR      # noqa: E402

ITEM_SPRITES_DIR = os.path.join(LIB_DIR, "item-sprites")
SAT_MIN = 0.25          # HSV saturation above this makes a pixel "coloured"
SHARE_MIN = 0.30        # coloured pixels must be at least this share of the drawing
STD_MAX = 25.0          # degrees of circular standard deviation of their hue


def measure(path):
    """(share of coloured pixels, circular standard deviation of their hue in
    degrees) for one sprite, from band histograms: no per-pixel loop."""
    from PIL import Image, ImageChops
    img = Image.open(path).convert("RGBA")
    h, s, v = img.convert("HSV").split()
    a = img.getchannel("A")
    total = img.size[0] * img.size[1]
    alpha_n = sum(a.histogram()[1:])
    if not alpha_n:
        return 0.0, 0.0
    # the coloured pixels: any alpha, HSV saturation over SAT_MIN
    mask = ImageChops.multiply(a.point(lambda x: 255 if x > 0 else 0),
                               s.point(lambda x: 255 if x > 63 else 0))
    n = mask.histogram()[255]
    if not n:
        return 0.0, 0.0
    # multiply parks every unmasked pixel at hue 0: take those back out of
    # bucket 0 so only the coloured pixels are counted
    hist = ImageChops.multiply(h, mask).histogram()
    hist[0] -= total - n
    cos = sin = 0.0
    for i, c in enumerate(hist):
        if not c:
            continue
        theta = math.radians((i + 0.5) * 360.0 / 256.0)
        cos += c * math.cos(theta)
        sin += c * math.sin(theta)
    r = math.hypot(cos, sin) / n
    if r >= 1.0:
        std = 0.0
    elif r <= 0.0:
        std = float("inf")
    else:
        std = math.degrees(math.sqrt(-2.0 * math.log(r)))
    return n / float(alpha_n), std


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=ITEM_SPRITES_DIR,
                    help="the item-sprites folder (default: the library's)")
    a = ap.parse_args()
    try:
        import PIL      # noqa: F401
    except ImportError:
        sys.exit("Pillow is required to measure the sprites")
    idx_path = os.path.join(a.dir, "index.json")
    index = {}
    if os.path.exists(idx_path):
        with open(idx_path, "r", encoding="utf-8") as f:
            index = json.load(f)
    rows = []
    for fn in sorted(os.listdir(a.dir)):
        if not fn.endswith(".webp"):
            continue
        key = fn[:-len(".webp")]
        share, std = measure(os.path.join(a.dir, fn))
        entry = index.setdefault(key, {})
        entry["tintable"] = bool(share >= SHARE_MIN and std <= STD_MAX)
        rows.append((key, share, std, entry["tintable"]))
    with open(idx_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(dict(sorted(index.items())), f, indent=1, ensure_ascii=False)
        f.write("\n")
    n_yes = sum(1 for r in rows if r[3])
    print(f"{len(rows)} sprites measured: {n_yes} tintable, "
          f"{len(rows) - n_yes} not")
    ranked = sorted(rows, key=lambda r: (-r[1], r[2]))
    print("most tintable:")
    for key, share, std, _ in ranked[:20]:
        print(f"  {key}: share {share:.2f}, hue std {std:.0f} deg")
    print("least tintable:")
    for key, share, std, _ in reversed(ranked[-20:]):
        print(f"  {key}: share {share:.2f}, hue std {std:.0f} deg")


if __name__ == "__main__":
    main()
