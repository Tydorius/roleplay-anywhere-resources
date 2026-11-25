"""Draw every room of a family as a grid of small plans in one PNG:
pieces are colored boxes with a thin line along their back side and, when
the box is big enough for it, the role's plan label (the shared short_role
rule: the most telling word — "toilet", not "wash"), the open style's
filler is hatched, door cells are marked on the walls, and each plan
carries its id and size underneath on two lines — the family on the first,
the rest of the id with the size on the second — so no label runs into the
next plan.

  python library-seed/room_sheet.py <family> [--out <png>]

The default output is library-seed/sheets/<family>.png.
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.dirname(HERE)
sys.path.insert(0, GEN)

from worldgen.room_palette import (ROLES, DEFAULT_ROLE, color as _color,  # noqa: E402
                                   short_role as _short_role)


CELL = 32               # pixels per room cell (big enough for a piece label)
PAD = 6                 # breathing room around a plan
CAPTION = 30            # pixels under a plan for the two label lines
LINE = 13               # pixels per label line
GAP = 14                # between grid cells
LABEL_FONT = 9          # the piece labels' own size, tried against the box
BORDER = (70, 70, 70)
FLOOR = (252, 250, 246)
FILLER = (150, 150, 150)
DOOR = (46, 125, 50)


def _darker(rgb, f=0.55):
    return tuple(int(c * f) for c in rgb)


def _font(size=10):
    for name in ("consola.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _label_lines(room):
    """The plan's label on two lines: the family on the first, the rest of
    the id with the size on the second — one line would run into the next
    plan's label."""
    parts = room["id"].split(".")
    fam = ".".join(parts[:-4])
    rest = ".".join(parts[-4:])
    return (fam, f"{rest}  {room['size'][0]}x{room['size'][1]}")


def _draw_plan(draw, room, ox, oy, font, lfont):
    """One room plan at (ox, oy): floor, pieces, filler, doors."""
    w, h = room["size"]
    draw.rectangle((ox, oy, ox + w * CELL - 1, oy + h * CELL - 1),
                   fill=FLOOR, outline=BORDER, width=1)
    filler = room.get("filler")
    if filler:
        fx, fy = filler["at"]
        fw, fh = filler["size"]
        x0, y0 = ox + fx * CELL, oy + fy * CELL
        x1, y1 = x0 + fw * CELL - 1, y0 + fh * CELL - 1
        draw.rectangle((x0, y0, x1, y1), outline=FILLER, width=1)
        for d in range(0, fw * CELL + fh * CELL, 5):
            draw.line((max(x0, x1 - d), min(y1, y0 + d),
                       min(x1, x0 + d), max(y0, y1 - d)), fill=FILLER)
    roles = [p.get("role") for p in room["pieces"]]
    for p in room["pieces"]:
        x, y = p["at"]
        pw, ph = p["size"]
        rgb = _color(p["role"])
        x0, y0 = ox + x * CELL, oy + y * CELL
        x1, y1 = x0 + pw * CELL - 1, y0 + ph * CELL - 1
        draw.rectangle((x0, y0, x1, y1), fill=rgb, outline=_darker(rgb))
        back, lw = p.get("back"), 2
        if back == "north":
            draw.rectangle((x0, y0, x1, y0 + lw - 1), fill=_darker(rgb))
        elif back == "south":
            draw.rectangle((x0, y1 - lw + 1, x1, y1), fill=_darker(rgb))
        elif back == "west":
            draw.rectangle((x0, y0, x0 + lw - 1, y1), fill=_darker(rgb))
        elif back == "east":
            draw.rectangle((x1 - lw + 1, y0, x1, y1), fill=_darker(rgb))
        # the role's label when the box has room for it (a 1-cell bath
        # reads "bath"; a piece too small keeps its colour alone)
        label = _short_role(p["role"], roles)
        if label:
            tw = draw.textlength(label, font=lfont)
            bw, bh = x1 - x0 + 1, y1 - y0 + 1
            if tw <= bw - 2 and bh >= LABEL_FONT + 1:
                draw.text((x0 + (bw - tw) // 2, y0 + (bh - LABEL_FONT) // 2),
                          label, font=lfont, fill=_darker(rgb, 0.35))
    for side, cells in room.get("doors", {}).items():
        for c in cells:
            if side in ("north", "south"):
                x = ox + c * CELL + CELL // 4
                y = oy - 2 if side == "north" else oy + h * CELL - 3
                draw.rectangle((x, y, x + CELL // 2, y + 4), fill=DOOR)
            else:
                x = ox - 2 if side == "west" else ox + w * CELL - 3
                y = oy + c * CELL + CELL // 4
                draw.rectangle((x, y, x + 4, y + CELL // 2), fill=DOOR)
    for i, text in enumerate(_label_lines(room)):
        tw = draw.textlength(text, font=font)
        draw.text((ox + (w * CELL - tw) // 2, oy + h * CELL + 4 + i * LINE),
                  text, font=font, fill=(40, 40, 40))


def render(family, out):
    """The family's rooms as one grid PNG; returns how many rooms it drew."""
    with open(os.path.join(GEN, "library", "rooms", f"{family}.json"),
              encoding="utf-8") as fh:
        rooms = json.load(fh)["rooms"]
    font = _font()
    lfont = _font(LABEL_FONT)
    labels = [_label_lines(r) for r in rooms]
    plan = max(r["size"][0] for r in rooms) * CELL
    # a cell is as wide as the plan or the widest label line, whichever is
    # more, so no label ever runs into the next cell
    widest = max(font.getlength(t) for ls in labels for t in ls)
    cell_w = int(max(plan, widest)) + 2 * PAD
    cell_h = (max(r["size"][1] for r in rooms) * CELL
              + 2 * PAD + CAPTION)
    cols = 6
    rows = -(-len(rooms) // cols)
    img = Image.new("RGB", (cols * cell_w + GAP, rows * cell_h + GAP),
                    "white")
    draw = ImageDraw.Draw(img)
    for n, room in enumerate(rooms):
        w, h = room["size"]
        ox = (n % cols) * cell_w + PAD + (plan - w * CELL) // 2
        oy = (n // cols) * cell_h + PAD
        _draw_plan(draw, room, ox, oy, font, lfont)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out)
    return len(rooms)


def main(argv):
    family, out = None, None
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--out" and args:
            out = args.pop(0)
        elif family is None:
            family = a
        else:
            print(f"unexpected argument {a!r}")
            return 2
    if not family:
        print("usage: python library-seed/room_sheet.py <family> "
              "[--out <png>]")
        return 2
    src = os.path.join(GEN, "library", "rooms", f"{family}.json")
    if not os.path.isfile(src):
        print(f"no rooms for family {family!r} in library\\rooms")
        return 2
    out = out or os.path.join(HERE, "sheets", f"{family}.png")
    n = render(family, out)
    print(f"wrote {os.path.relpath(out, GEN)} ({n} rooms)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
