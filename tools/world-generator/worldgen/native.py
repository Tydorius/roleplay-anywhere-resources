"""Anywhere RPG 1.0 door objects on a built scenario: a Python port of the
Scenario Editor's own doorway rules (world10.js), so the generator ships what
the game plays — a doorway with no door object is an open gap, and the game
adds no doors to imported scenarios.

Doorways come from openings on walled regions: an opening crossed from a cell
inside a walled region to the cell outside is a doorway only when every walled
region whose wall the crossing splits opens its side of it. A door object is
an object entity from one of the four door templates, sitting zero-wide on
the wall line; the doorway's room (the smallest region the wall splits) picks
the kind from its `door` field ("door" when missing, "none" leaves it open).
Coordinates: [0,0] is the bottom-left cell, y grows north.
"""
import random
import re
import time

DOOR_KINDS = ("door", "bars", "gate", "curtain")
DOOR_NAMES = {"door": "Door", "bars": "Barred door",
              "gate": "Gate", "curtain": "Curtain"}
# a side's step to the next cell
STEP = {"n": (0, 1), "e": (1, 0), "s": (0, -1), "w": (-1, 0)}


# ---------------------------------------------------------------- geometry

def _rect(region):
    x, y = region.get("position", (0, 0))
    w, h = region.get("size", (1, 1))
    return (x, y, x + w - 1, y + h - 1)


def _in_rect(r, x, y):
    return r[0] <= x <= r[2] and r[1] <= y <= r[3]


def _side_between(a, b):
    """The side pointing from cell a to the adjacent cell b."""
    if b[0] == a[0] + 1:
        return "e"
    if b[0] == a[0] - 1:
        return "w"
    if b[1] == a[1] + 1:
        return "n"
    return "s"


# ------------------------------------------------- openings and doorways

def opening_sides(region, o):
    """Which sides of the region's border the opening ``o`` (an ``[x, y]``
    cell) opens: nothing off the rectangle; the edge sides the cell sits on
    (a corner has two); just the entry's own third value when it has one and
    it is among them."""
    r = _rect(region)
    if not _in_rect(r, o[0], o[1]):
        return []
    sides = []
    if o[1] == r[3]:
        sides.append("n")
    if o[0] == r[2]:
        sides.append("e")
    if o[1] == r[1]:
        sides.append("s")
    if o[0] == r[0]:
        sides.append("w")
    return [o[2]] if len(o) > 2 and o[2] in sides else sides


def opens(region, cell, side):
    """Whether the region has an opening at ``cell`` that opens ``side``."""
    for g in region.get("openings") or []:
        if g[0] == cell[0] and g[1] == cell[1] \
                and side in opening_sides(region, g):
            return True
    return False


def doorways(scn):
    """Every doorway in the scenario, as the game works it out: an opening on
    a walled region's border, crossed from a cell inside it to the cell
    outside, where every walled region holding exactly one of the two cells
    opens its side of the crossing (a door in one wall but not the other is
    no doorway). Entries are ``{"cell", "out", "room", "key"}``: cell is the
    one inside the room, room is the smallest region the wall splits (the
    first wins a tie), and the key is ``"<x>,<y>,x|y"`` from the lower cell
    and the crossing's axis."""
    walled = [r for r in scn.get("regions", []) if r.get("wall")]
    out, seen = [], set()
    for o in walled:
        for g in o.get("openings") or []:
            for side in opening_sides(o, g):
                cell = (g[0], g[1])
                beyond = (cell[0] + STEP[side][0], cell[1] + STEP[side][1])
                r = _rect(o)
                if not _in_rect(r, *cell) or _in_rect(r, *beyond):
                    continue
                lo = cell if (cell < beyond) else beyond
                axis = "x" if cell[0] != beyond[0] else "y"
                key = f"{lo[0]},{lo[1]},{axis}"
                if key in seen:
                    continue
                split = [w for w in walled
                         if _in_rect(_rect(w), *cell)
                         != _in_rect(_rect(w), *beyond)]
                crossed = True
                for w in split:
                    inside = _in_rect(_rect(w), *cell)
                    c, other = (cell, beyond) if inside else (beyond, cell)
                    if not opens(w, c, _side_between(c, other)):
                        crossed = False
                        break
                if not crossed:
                    continue
                seen.add(key)
                room = split[0]

                def area(w):
                    sw, sh = w.get("size") or (1, 1)
                    return sw * sh

                for w in split[1:]:
                    if area(w) < area(room):
                        room = w
                inside = _in_rect(_rect(room), *cell)
                out.append({"cell": cell if inside else beyond,
                            "out": beyond if inside else cell,
                            "room": room, "key": key})
    return out


# ---------------------------------------------------------------- door objects

def is_door(scn, e):
    """Whether e is an object entity placed from one of the door templates."""
    if not e or e.get("type") != "object":
        return False
    t = next((t for t in scn.get("objectTemplates") or []
              if t.get("id") == e.get("templateId")), None)
    return t is not None and t.get("door") in DOOR_KINDS


def door_cells(e):
    """The two cells a door object separates (one apart in x or y), lower
    one first."""
    pos = e["pos"]
    if (e.get("size") or [1, 0])[0] == 0:
        return [(pos[0] - 1, pos[1]), (pos[0], pos[1])]
    return [(pos[0], pos[1] - 1), (pos[0], pos[1])]


def door_key_of(e):
    """The doorway key of a door object: "<x>,<y>,x|y" from its lower cell
    and crossing axis."""
    a, b = door_cells(e)
    return f"{a[0]},{a[1]},{'x' if a[0] != b[0] else 'y'}"


def doors_by_key(scn):
    """The scenario's door objects, keyed by the doorway they sit on."""
    m = {}
    for e in scn.get("entities") or []:
        if is_door(scn, e):
            m.setdefault(door_key_of(e), []).append(e)
    return m


def door_counts(scn):
    """How many door objects of each kind the scenario carries (kinds with
    none left out)."""
    tpl = {t.get("id"): t for t in scn.get("objectTemplates") or []}
    out = {}
    for e in scn.get("entities") or []:
        t = tpl.get(e.get("templateId")) or {}
        if e.get("type") == "object" and t.get("door") in DOOR_KINDS:
            out[t["door"]] = out.get(t["door"], 0) + 1
    return out


def door_placement(dw):
    """Where a door object sits on a doorway: on the wall line, zero-wide
    along it (``rot`` 1 with size ``[0, 1]`` when the crossing runs along x)."""
    cell, out = dw["cell"], dw["out"]
    rot = 1 if cell[0] != out[0] else 0
    return {"pos": [max(cell[0], out[0]), max(cell[1], out[1])],
            "rot": rot, "size": [0, 1] if rot else [1, 0]}


# ---------------------------------------------------------------- ids and names

_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def _b36(n):
    s = ""
    while True:
        n, r = divmod(n, 36)
        s = _B36[r] + s
        if n == 0:
            return s


class Ids:
    """The vendored builder's id shape, ``<prefix>_<base36 ms>_<base36
    counter>_<rand>``, with each id kept unique against the scenario."""

    def __init__(self, scn):
        self.taken = {e.get("id") for e in scn.get("entities") or []}
        self.taken |= {t.get("id") for t in scn.get("objectTemplates") or []}
        self.rng = random.Random(str(scn.get("name") or "worldgen-doors"))
        self.stamp = _b36(int(time.time() * 1000))
        self.n = 10

    def __call__(self, prefix):
        while True:
            self.n += 1
            rand = "".join(self.rng.choice(_B36) for _ in range(4))
            i = f"{prefix}_{self.stamp}_{_b36(self.n)}_{rand}"
            if i not in self.taken:
                self.taken.add(i)
                return i


def next_name(base, names):
    """``base N`` with the next number not used by any name in ``names``
    (a bare ``base`` counts as 1)."""
    n = 0
    pat = re.compile(r"\A" + re.escape(base) + r" ([0-9]+)\Z")
    for nm in names:
        m = pat.match(nm) if isinstance(nm, str) else None
        if m:
            n = max(n, int(m.group(1)))
        if nm == base:
            n = max(n, 1)
    return f"{base} {n + 1}"


# ---------------------------------------------------------------- hanging

def door_template(scn, kind, ids):
    """The kind's one door template (by kind and English name), created on
    first use."""
    name = DOOR_NAMES[kind]
    t = next((t for t in scn.get("objectTemplates") or []
              if t.get("door") == kind and t.get("name") == name), None)
    if t is not None:
        return t
    t = {"id": ids("otpl"), "name": name, "size": [1, 0], "walkability": 1,
         "door": kind, "heightM": 2.1, "maxHp": 60}
    scn.setdefault("objectTemplates", []).append(t)
    return t


def hang_door(scn, dw, kind, ids):
    """Hang a door object of ``kind`` on doorway ``dw``, named after its
    template ("Door 2")."""
    tpl = door_template(scn, kind, ids)
    place = door_placement(dw)
    e = {"id": ids("obj"), "type": "object",
         "name": next_name(tpl["name"],
                           [o.get("name") for o in scn.get("entities") or []]),
         "pos": place["pos"], "size": place["size"], "hp": 60, "maxHp": 60,
         "inventory": [], "statusEffects": [], "templateId": tpl["id"]}
    if place["rot"]:
        e["rot"] = place["rot"]
    scn.setdefault("entities", []).append(e)
    return e


def hang_doors(scn):
    """Hang a door object on every doorway without one, of the doorway's
    room's own kind ("door" by default, "none" left open), and return how
    many were hung."""
    have = doors_by_key(scn)
    ids = Ids(scn)
    hung = 0
    for dw in doorways(scn):
        kind = dw["room"].get("door") or "door"
        if kind == "none" or have.get(dw["key"]):
            continue
        hang_door(scn, dw, kind, ids)
        hung += 1
    return hung
