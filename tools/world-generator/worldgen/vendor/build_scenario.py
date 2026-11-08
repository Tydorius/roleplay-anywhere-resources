"""Build a Roleplay Anywhere (Anywhere RPG) scenario from a name-based spec.

Usage:
    python worldgen/vendor/build_scenario.py <spec.py> [--out <dir>] [--no-zip]

A spec is a Python file defining SPEC (a dict). Everything is referenced by
*name* (regions, item templates, object templates); this script assigns ids,
resolves references, computes door openings, spawns hostile instances,
converts portraits to the game's media layout, validates the result and
writes <Name>.scenario/ (scenario.json + media/) plus <Name>.scenario.zip.

See SCENARIO_AUTHORING_GUIDE.md for the spec format and the engine rules.
"""
import argparse
import importlib.util
import json
import os
import random
import shutil
import sys
import time
import zipfile

try:
    from PIL import Image
except ImportError:  # portraits are skipped without Pillow
    Image = None

# ---------------------------------------------------------------- ids

_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def _b36(n):
    s = ""
    while True:
        n, r = divmod(n, 36)
        s = _B36[r] + s
        if n == 0:
            return s


class Ids:
    """Mimics the game's id shape: <prefix>_<base36 ms>_<base36 counter>_<rand>."""

    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.stamp = _b36(int(time.time() * 1000))
        self.n = 10

    def __call__(self, prefix):
        self.n += 1
        rand = "".join(self.rng.choice(_B36) for _ in range(4))
        return f"{prefix}_{self.stamp}_{_b36(self.n)}_{rand}"


# ---------------------------------------------------------------- helpers

def load_spec(path):
    spec = importlib.util.spec_from_file_location("scenario_spec", path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, os.path.dirname(os.path.abspath(path)))
    spec.loader.exec_module(mod)
    return mod.SPEC


def rect(pos, size):
    x, y = pos
    w, h = size
    return x, y, x + w - 1, y + h - 1


def cells(pos, size):
    x0, y0, x1, y1 = rect(pos, size)
    return {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}


def contains(outer, inner):
    ox0, oy0, ox1, oy1 = outer
    ix0, iy0, ix1, iy1 = inner
    return ox0 <= ix0 and oy0 <= iy0 and ix1 <= ox1 and iy1 <= oy1


def disjoint(a, b):
    return a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1]


def on_edge(r, c):
    x0, y0, x1, y1 = r
    x, y = c
    return x0 <= x <= x1 and y0 <= y <= y1 and (x in (x0, x1) or y in (y0, y1))


def to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


SIDES = ("north", "south", "east", "west")


def door_cell(r, side, offset=None):
    """A perimeter cell of rect r on the given side (y grows northward)."""
    x0, y0, x1, y1 = r
    if side in ("north", "south"):
        x = x0 + (offset if offset is not None else (x1 - x0) // 2)
        return [x, y1 if side == "north" else y0]
    y = y0 + (offset if offset is not None else (y1 - y0) // 2)
    return [x1 if side == "east" else x0, y]


# ---------------------------------------------------------------- build

class Builder:
    def __init__(self, spec, spec_dir):
        self.s = spec
        self.dir = spec_dir
        self.ids = Ids(spec.get("seed", spec["name"]))
        self.rng = random.Random(spec.get("seed", spec["name"]))
        self.errors = []
        self.warnings = []
        self.portraits = {}  # entity id -> source image path

    def err(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    # -- regions ---------------------------------------------------------
    def build_regions(self):
        W, H = self.s["gridSize"]
        regions = []
        self.region_by_name = {}
        for r in self.s["regions"]:
            if r["name"] in self.region_by_name:
                self.err(f"duplicate region name {r['name']!r}")
            rr = rect(r["position"], r["size"])
            if rr[0] < 0 or rr[1] < 0 or rr[2] >= W or rr[3] >= H:
                self.err(f"region {r['name']!r} out of bounds {rr}")
            out = {"id": self.ids("rgn"), "name": r["name"], "description": r.get("description", "")}
            if r.get("wall"):
                out["wall"] = r["wall"]
            out["ground"] = r.get("ground", "dirt")
            out["groundTexture"] = r.get("groundTexture", "dirt")
            out["openings"] = []
            out["position"] = list(r["position"])
            out["size"] = list(r["size"])
            out["ambience"] = r.get("ambience", {"day": "quiet_indoor" if r.get("wall") else "nature_outdoors"})
            for k in ("groundColor", "wallColor"):
                if r.get(k):
                    out[k] = r[k]
            if r.get("hostile"):
                out["hostile"] = True
            out["_rect"] = rr
            out["_doors"] = r.get("doors", [])
            regions.append(out)
            self.region_by_name[r["name"]] = out
        # nesting: each pair is nested or disjoint
        for i, a in enumerate(regions):
            for b in regions[i + 1:]:
                ra, rb = a["_rect"], b["_rect"]
                if not (disjoint(ra, rb) or contains(ra, rb) or contains(rb, ra)):
                    self.err(f"regions overlap without nesting: {a['name']!r} {ra} / {b['name']!r} {rb}")
        # parent = smallest strictly-larger container
        for r in regions:
            parents = [p for p in regions if p is not r and contains(p["_rect"], r["_rect"]) and p["_rect"] != r["_rect"]]
            r["_parent"] = min(parents, key=lambda p: (p["size"][0] * p["size"][1])) if parents else None
        self.regions = regions
        self._openings()

    def _openings(self):
        """Doors. Spec doors are ['north'|'south'|'east'|'west'] or [x, y] cells or
        (side, offset). A door cell is recorded on every walled region whose edge it
        sits on (building and the room behind it), like the game's own exports.
        Walled rooms that share a wall with a walled sibling get a connecting door."""
        walled = [r for r in self.regions if r.get("wall")]

        def add(cell):
            hit = False
            for r in walled:
                if on_edge(r["_rect"], cell) and cell not in r["openings"]:
                    r["openings"].append(cell)
                    hit = True
            return hit

        for r in walled:
            for d in r["_doors"]:
                if isinstance(d, str):
                    cell = door_cell(r["_rect"], d)
                elif isinstance(d, (tuple, list)) and len(d) == 2 and isinstance(d[0], str):
                    cell = door_cell(r["_rect"], d[0], d[1])
                else:
                    cell = list(d)
                if not on_edge(r["_rect"], cell):
                    self.err(f"door {cell} not on the wall of {r['name']!r}")
                add(cell)
        # connect walled siblings sharing a wall segment
        for i, a in enumerate(walled):
            for b in walled[i + 1:]:
                if a["_parent"] is not b["_parent"]:
                    continue
                for cell in self._shared_wall_cells(a["_rect"], b["_rect"]):
                    add(cell)
        for r in walled:
            if not r["openings"]:
                self.warn(f"walled region {r['name']!r} has no door")

    @staticmethod
    def _shared_wall_cells(a, b):
        """Door between two rooms that touch. Adjacent rooms (edges one apart) each
        have their own wall line, so the door is a facing pair of cells — exactly
        what the game's exports contain. Rooms sharing one wall line get one cell."""
        ax0, ay0, ax1, ay1 = a
        bx0, by0, bx1, by1 = b
        for (ea, eb, horiz) in ((ay1, by0, True), (by1, ay0, True), (ax1, bx0, False), (bx1, ax0, False)):
            if eb - ea in (0, 1):
                if horiz:
                    lo, hi = max(ax0, bx0) + 1, min(ax1, bx1) - 1
                    if hi >= lo:
                        x = (lo + hi) // 2
                        return [[x, ea], [x, eb]] if eb != ea else [[x, ea]]
                else:
                    lo, hi = max(ay0, by0) + 1, min(ay1, by1) - 1
                    if hi >= lo:
                        y = (lo + hi) // 2
                        return [[ea, y], [eb, y]] if eb != ea else [[ea, y]]
        return []

    def at(self, p, label):
        """A cell: [x, y], or ["Region name", dx, dy] counted from the region's first
        walkable cell (inside the wall ring for walled regions)."""
        if not (p and isinstance(p[0], str)):
            return list(p)
        r = self.region_by_name.get(p[0])
        if not r:
            self.err(f"{label}: unknown region {p[0]!r}")
            return [0, 0]
        x0, y0, x1, y1 = r["_rect"]
        inset = 1 if r.get("wall") else 0
        c = [x0 + inset + p[1], y0 + inset + p[2]]
        if not (x0 + inset <= c[0] <= x1 - inset and y0 + inset <= c[1] <= y1 - inset):
            self.err(f"{label}: {p} lands outside {p[0]!r} at {c}")
        return c

    def region_rect(self, name):
        r = self.region_by_name.get(name)
        if not r:
            self.err(f"unknown region {name!r}")
            return None
        return r["_rect"]

    # -- templates -------------------------------------------------------
    def build_items(self):
        self.item_by_name = {}
        out = []
        for it in self.s.get("itemTemplates", []):
            t = {"id": self.ids("itpl"), "name": it["name"], "type": it.get("type", "misc"),
                 "quality": it.get("quality", "common"), "description": it.get("description", ""),
                 "physicalDescription": it.get("physicalDescription", it["name"] + ", white background"),
                 "value": it.get("value", 1)}
            for k in ("light", "attributeBonus", "skillBonus"):
                if k in it:
                    t[k] = it[k]
            if it.get("perks"):
                t["perks"] = [self._perk(p, "ipk", item=True) for p in it["perks"]]
            if it["name"] in self.item_by_name:
                self.err(f"duplicate item template {it['name']!r}")
            self.item_by_name[it["name"]] = t
            out.append(t)
        self.items = out

    def item_ref(self, name, count=1):
        t = self.item_by_name.get(name)
        if not t:
            self.err(f"unknown item template {name!r}")
            return None
        return {"id": self.ids("it"), "count": count, "templateId": t["id"]}

    def inventory(self, entries):
        inv = []
        for e in entries or []:
            name, count = (e, 1) if isinstance(e, str) else (e[0], e[1])
            ref = self.item_ref(name, count)
            if ref:
                inv.append(ref)
        return inv

    def equipment(self, eq):
        out = {}
        for slot, name in (eq or {}).items():
            ref = self.item_ref(name)
            if ref:
                out[slot] = ref
        return out

    def build_objects(self):
        self.obj_by_name = {}
        out = []
        for o in self.s.get("objectTemplates", []):
            t = {"id": self.ids("otpl"), "name": o["name"],
                 "physicalDescription": o.get("physicalDescription", o["name"]),
                 "size": list(o.get("size", [1, 1])), "walkability": o.get("walkability", 0),
                 "forSleep": o.get("forSleep", False), "description": o.get("description", ""),
                 "craftStation": o.get("craftStation", False), "maxHp": o.get("maxHp", 50),
                 "tags": o.get("tags", ["filler"]), "heightM": o.get("heightM", 1)}
            if "money" in o:  # a tier 0..5 (0 = nothing), not an amount
                if not 0 <= o["money"] <= 5:
                    self.err(f"object {o['name']!r}: template money is a tier 0-5, got {o['money']}")
                t["money"] = o["money"]
            if o.get("lootPool"):
                t["lootPoolIds"] = [self.item_by_name[n]["id"] for n in o["lootPool"] if n in self.item_by_name]
                for n in o["lootPool"]:
                    if n not in self.item_by_name:
                        self.err(f"object {o['name']!r}: unknown loot item {n!r}")
            for k in ("light", "startingEffects"):
                if k in o:
                    t[k] = o[k]
            self.obj_by_name[o["name"]] = (t, o)
            out.append(t)
        self.objects = out

    def build_hostile_templates(self):
        self.htpl = []
        for h in self.s.get("hostileNpcTemplates", []):
            reg = self.region_by_name.get(h["region"])
            if not reg:
                self.err(f"hostile {h['name']!r}: unknown region {h['region']!r}")
                continue
            if not reg.get("hostile"):
                self.warn(f"hostile {h['name']!r} lives in non-hostile region {h['region']!r}")
            t = {"id": self.ids("htpl"), "name": h["name"], "description": h.get("description", ""),
                 "gender": h.get("gender", "male"), "regionId": reg["id"], "count": h.get("count", 2),
                 "animationId": h["animationId"], "physicalDescription": h.get("physicalDescription", h["name"]),
                 "voiceProfile": h.get("voiceProfile", {"gender": "Male", "age": ["Adult"], "pitch": ["Deeper"], "tags": ["Villain"]}),
                 "level": h.get("level", 3), "money": h.get("money", 1),  # tier 1..5
                 "lootPoolIds": [self.item_by_name[n]["id"] for n in h.get("lootPool", []) if n in self.item_by_name]}
            if h.get("spriteColor"):
                t["spriteColor"] = h["spriteColor"]
            self.htpl.append((t, h))

    def _perk(self, p, prefix, item=False):
        out = {"id": self.ids(prefix), "name": p["name"], "description": p["description"],
               "type": p.get("type", "passive"),
               "children": [self._perk(c, prefix, item) for c in p.get("children", [])],
               "physicalDescription": p.get("physicalDescription", p["name"] + " icon")}
        if item:
            out["learned"] = True
        return out

    # -- entities --------------------------------------------------------
    def build_entities(self):
        W, H = self.s["gridSize"]
        self.claimed = {}
        # character cells are reserved up front so scattered filler never lands on them
        for n in self.s.get("npcs", []) + [self.s["player"]]:
            n["pos"] = self.at(n["pos"], n["name"])
        self.reserved = {tuple(n["pos"]) for n in self.s.get("npcs", []) + [self.s["player"]]}
        ents = []
        # objects
        for name, (t, o) in self.obj_by_name.items():
            for i, pl in enumerate(o.get("placements", []), 1):
                if isinstance(pl, dict):
                    pos, extra = pl["pos"], pl
                else:
                    pos, extra = pl, {}
                pos = self.at(pos, f"{name} #{i}")
                # "rot": quarter turns clockwise; the game draws the sprite turned
                # and the placed object's size is the turned footprint
                rot = int(extra.get("rot", 0) or 0) % 4
                size = [t["size"][1], t["size"][0]] if rot % 2 else t["size"]
                for c in cells(pos, size):
                    if c in self.reserved:
                        self.err(f"{name} #{i} covers a character's starting cell {c}")
                self._claim(cells(pos, size), f"{name} #{i}", W, H)
                e = {"id": self.ids("obj"), "type": "object", "name": f"{name} {i}", "pos": list(pos),
                     "size": list(size), "hp": t["maxHp"], "maxHp": t["maxHp"],
                     "inventory": self.inventory(extra.get("inventory")), "statusEffects": [],
                     "templateId": t["id"]}
                if "money" in extra:
                    e["money"] = extra["money"]
                if rot:
                    e["rot"] = rot
                ents.append(e)
        # scattered filler: {"scatter": [{"region": name, "count": n}]} drops n copies on
        # free cells of an open region (never inside nested walled rooms or on doors' approach)
        for name, (t, o) in self.obj_by_name.items():
            n = len(o.get("placements", []))
            for sc in o.get("scatter", []):
                rr = self.region_rect(sc["region"])
                if not rr:
                    continue
                avoid = [self.region_rect(a) for a in sc.get("avoid", [])]
                for _ in range(sc["count"]):
                    pos = self._free_rect(rr, t["size"], avoid=[a for a in avoid if a])
                    if pos is None:
                        self.warn(f"scatter {name!r}: region {sc['region']!r} is full")
                        break
                    n += 1
                    self._claim(cells(pos, t["size"]), f"{name} #{n}", W, H)
                    ents.append({"id": self.ids("obj"), "type": "object", "name": f"{name} {n}", "pos": pos,
                                 "size": list(t["size"]), "hp": t["maxHp"], "maxHp": t["maxHp"],
                                 "inventory": [], "statusEffects": [], "templateId": t["id"]})
        # characters
        npc_specs = list(self.s.get("npcs", []))
        names = set()
        for n in npc_specs + [self.s["player"]]:
            if n["name"] in names:
                self.err(f"duplicate character name {n['name']!r}")
            names.add(n["name"])
        for n in npc_specs:
            ents.append(self._character(n, "npc", W, H))
        player = self._character(self.s["player"], "player", W, H)
        ents.append(player)
        # hostile spawns
        for t, h in self.htpl:
            rr = self.region_rect(h["region"])
            for k in range(1, t["count"] + 1):
                pos = self._free_cell(rr)
                e = {"id": self.ids("npc"), "type": "npc", "name": f"{t['name']} {k}",
                     "description": t["description"], "gender": t["gender"], "hostile": True,
                     "pos": pos, "size": [1, 1], "hp": 100, "maxHp": 100,
                     "schedule": [{"start": "00:00", "end": "00:00", "location": h["region"], "role": "leisure"}],
                     "animationId": t["animationId"], "physicalDescription": t["physicalDescription"],
                     "voiceProfile": t["voiceProfile"], "level": t["level"], "money": t["money"],
                     "stance": "hostile", "inventory": [], "statusEffects": [], "templateId": t["id"]}
                if t.get("spriteColor"):
                    e["spriteColor"] = t["spriteColor"]
                if t["lootPoolIds"]:
                    e["inventory"].append({"id": self.ids("it"), "count": 1,
                                           "templateId": self.rng.choice(t["lootPoolIds"])})
                ents.append(e)
        self.entities = ents
        self.player = player
        self._check_sleep()
        self._check_reach(W, H)

    def _claim(self, cs, label, W, H):
        if not hasattr(self, "_wall_cells"):
            self._wall_cells = {}
            for r in self.regions:
                if r.get("wall"):
                    x0, y0, x1, y1 = r["_rect"]
                    for x in range(x0, x1 + 1):
                        for y in range(y0, y1 + 1):
                            if x in (x0, x1) or y in (y0, y1):
                                self._wall_cells[(x, y)] = r["name"]
        for c in cs:
            if c in self._wall_cells:
                self.err(f"{label} sits on the wall of {self._wall_cells[c]!r} at {c}")
            if not (0 <= c[0] < W and 0 <= c[1] < H):
                self.err(f"{label} out of bounds at {c}")
            elif c in self.claimed:
                self.err(f"{label} overlaps {self.claimed[c]} at {c}")
            else:
                self.claimed[c] = label

    def _free_rect(self, rr, size, margin=1, avoid=()):
        """A position whose footprint (plus a 1-cell walking margin) is unclaimed and
        clear of walled sub-regions, door cells and any `avoid` rects (paths)."""
        x0, y0, x1, y1 = rr
        w, h = size
        inner = [r["_rect"] for r in self.regions if r.get("wall") and contains(rr, r["_rect"])] + list(avoid)
        doors = {tuple(c) for r in self.regions for c in r["openings"]}
        for _ in range(400):
            x = self.rng.randint(x0, x1 - w + 1)
            y = self.rng.randint(y0, y1 - h + 1)
            fp = (x - margin, y - margin, x + w - 1 + margin, y + h - 1 + margin)
            ok = all((cx, cy) not in self.claimed and (cx, cy) not in doors and (cx, cy) not in self.reserved
                     for cx in range(fp[0], fp[2] + 1) for cy in range(fp[1], fp[3] + 1))
            if ok and not any(not disjoint(fp, i) for i in inner):
                return [x, y]
        return None

    def _free_cell(self, rr):
        x0, y0, x1, y1 = rr
        inner = [r["_rect"] for r in self.regions if r.get("wall") and r["_rect"] != rr and contains(rr, r["_rect"])]
        for _ in range(500):
            c = (self.rng.randint(x0 + 1, max(x0 + 1, x1 - 1)), self.rng.randint(y0 + 1, max(y0 + 1, y1 - 1)))
            if any(contains(i, (c[0], c[1], c[0], c[1])) for i in inner):
                continue  # keep spawns out of buildings nested in the region
            if c not in self.claimed and c not in self._wall_cells:
                self.claimed[c] = "hostile spawn"
                return list(c)
        self.err(f"no free cell in {rr}")
        return [x0, y0]

    def _character(self, n, kind, W, H):
        prefix = "player" if kind == "player" else "npc"
        e = {"id": self.ids(prefix), "type": kind, "name": n["name"], "gender": n.get("gender", "female"),
             "description": n["description"]}
        if n.get("hostile"):
            e["hostile"] = True
        e["pos"] = list(n["pos"])
        e["size"] = [1, 1]
        e["hp"] = n.get("hp", 100)
        e["maxHp"] = n.get("maxHp", 100)
        e["schedule"] = n["schedule"]
        e["animationId"] = n["animationId"]
        e["physicalDescription"] = n["physicalDescription"]
        e["voiceProfile"] = n["voiceProfile"]
        if kind == "npc":
            e["level"] = n.get("level", 3)
            if "money" in n:
                e["money"] = n["money"]
            if n.get("stance"):
                e["stance"] = n["stance"]
        if n.get("spriteColor"):
            e["spriteColor"] = n["spriteColor"]
        e["inventory"] = self.inventory(n.get("inventory"))
        e["statusEffects"] = n.get("statusEffects", [])
        if n.get("merchant") is not None:
            e["merchant"] = n["merchant"]
        # GM-facing secrets: sent to the GM only while this NPC is near the player;
        # the player sees them only by opening the NPC's panel.
        if n.get("gm"):
            e["mindset"] = n["gm"]
        if n.get("memories"):
            e["memories"] = [{"t": 0, "text": m} for m in n["memories"]]
        if kind == "player" or n.get("equipment"):
            e["equipment"] = self.equipment(n.get("equipment"))
        self._claim({tuple(n["pos"])}, n["name"], W, H)
        self._check_schedule(n)
        if n.get("portrait"):
            p = n["portrait"] if os.path.isabs(n["portrait"]) else os.path.join(self.dir, n["portrait"])
            if os.path.exists(p):
                self.portraits[e["id"]] = (p, n.get("portraitCrop"))
            else:
                self.err(f"portrait for {n['name']!r} not found: {p}")
        return e

    def _check_schedule(self, n):
        sch = n["schedule"]
        total = 0
        for i, b in enumerate(sch):
            if b["location"] not in self.region_by_name:
                self.err(f"{n['name']!r} schedule: unknown region {b['location']!r}")
            if b["role"] not in ("work", "leisure", "sleep"):
                self.err(f"{n['name']!r} schedule: bad role {b['role']!r}")
            s, en = to_min(b["start"]), to_min(b["end"])
            total += (en - s) % 1440
            nxt = sch[(i + 1) % len(sch)]
            if b["end"] != nxt["start"]:
                self.err(f"{n['name']!r} schedule gap/overlap: {b['end']} -> {nxt['start']}")
        if total != 1440 and not (len(sch) == 1 and sch[0]["start"] == sch[0]["end"]):
            self.err(f"{n['name']!r} schedule covers {total} min, not 24h")

    def _check_reach(self, W, H):
        """Flood-fill from the player through door openings and walkable cells, then
        flag characters, rooms and furniture nobody can walk to."""
        doors = {tuple(c) for r in self.regions for c in r["openings"]}
        blocked = {c for c in self._wall_cells if c not in doors}
        tpl = {t["id"]: t for t in self.objects}
        objs = [e for e in self.entities if e["type"] == "object"]
        for e in objs:
            if tpl[e["templateId"]].get("walkability", 0) == 0:
                blocked.update(cells(e["pos"], e["size"]))
        start = tuple(self.player["pos"])
        seen, todo = {start}, [start]
        while todo:
            x, y = todo.pop()
            for c in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= c[0] < W and 0 <= c[1] < H and c not in seen and c not in blocked:
                    seen.add(c)
                    todo.append(c)
        for e in self.entities:
            if e["type"] in ("npc", "player") and tuple(e["pos"]) not in seen:
                self.err(f"{e['name']!r} starts at {e['pos']}, which cannot be reached on foot")
        for r in self.regions:
            if r.get("wall"):
                x0, y0, x1, y1 = r["_rect"]
                inside = [(x, y) for x in range(x0 + 1, x1) for y in range(y0 + 1, y1)]
                if inside and not any(c in seen for c in inside):
                    self.err(f"room {r['name']!r} cannot be reached on foot")
        for e in objs:
            x0, y0 = e["pos"]
            w, h = e["size"]
            ring = [(x, y) for x in range(x0 - 1, x0 + w + 1) for y in range(y0 - 1, y0 + h + 1)
                    if not (x0 <= x < x0 + w and y0 <= y < y0 + h)]
            if not any(c in seen for c in ring):
                self.warn(f"{e['name']} at {e['pos']} has no reachable cell beside it")

    def _check_sleep(self):
        beds = []
        for e in self.entities:
            if e["type"] == "object":
                t = next(t for t in self.objects if t["id"] == e["templateId"])
                if t["forSleep"]:
                    beds.append(rect(e["pos"], e["size"]))
        for n in self.s.get("npcs", []) + [self.s["player"]]:
            for b in n["schedule"]:
                if b["role"] == "sleep":
                    rr = self.region_rect(b["location"])
                    if rr and not any(contains(rr, bd) for bd in beds):
                        self.err(f"{n['name']!r} sleeps in {b['location']!r} which has no forSleep object")

    # -- systems ---------------------------------------------------------
    def build_systems(self):
        s = self.s
        self.perk_trees = [{"name": t["name"], "root": self._perk(t["root"], "perk")} for t in s.get("perkTrees", [])]
        cal = []
        for c in s.get("calendar", []):
            if c["location"] not in self.region_by_name:
                self.err(f"calendar {c['name']!r}: unknown region {c['location']!r}")
            start = c.get("day", 0) * 86400 + to_min(c["start"]) * 60
            cal.append({"id": self.ids("cal"), "name": c["name"], "location": c["location"],
                        "startSecs": start, "durationSecs": int(c["hours"] * 3600),
                        "missedConsequence": c.get("missedConsequence", ""),
                        "recurrence": c.get("recurrence", "none"), "attendedInstances": []})
        self.calendar = cal
        self.quests = []
        for q in s.get("quests", []):
            self.quests.append({"id": self.ids("q"), "title": q["title"],
                                "objectives": [{"id": self.ids("qo"), "root": self._qnode(o)} for o in q["objectives"]],
                                "status": q.get("status", "active")})

    def _qnode(self, o, primary=True):
        if isinstance(o, str):
            o = {"text": o}
        return {"id": self.ids("qt"), "text": o["text"], "type": o.get("type", "bool"),
                "target": o.get("target", 1), "current": o.get("current", 0),
                "prerequisites": [self._qnode(p) for p in o.get("prerequisites", [])],
                "primary": o.get("primary", primary)}

    # -- output ----------------------------------------------------------
    def scenario(self):
        s = self.s
        regions = [{k: v for k, v in r.items() if not k.startswith("_")} for r in self.regions]
        dt = dict(s["defaultTile"])
        dt = {"id": self.ids("tile"), **dt}
        return {
            "id": self.ids("scn"), "name": s["name"], "worldBackground": s["worldBackground"],
            "gridSize": list(s["gridSize"]), "defaultTile": dt, "regions": regions,
            "itemTemplates": self.items, "narrativeRules": s.get("narrativeRules", []),
            "narrativeFlavor": s.get("narrativeFlavor", "adaptive"), "difficulty": s.get("difficulty", "medium"),
            "xpMultiplier": s.get("xpMultiplier", 1), "currency": s["currency"],
            "startingCurrency": s.get("startingCurrency", 0), "variables": s.get("variables", []),
            "attributes": s["attributes"], "skills": [{"name": k, "level": v, "xp": 0} for k, v in s.get("skills", {}).items()],
            "perkTrees": self.perk_trees, "calendar": self.calendar, "quests": self.quests,
            "createdAt": int(time.time() * 1000), "stancesAuthored": True,
            "weatherKinds": s.get("weatherKinds", ["clear", "rain", "fog"]), "language": s.get("language", "en"),
            "imageSettings": s.get("imageSettings", {"promptFormat": "", "models": {}}),
            "objectTemplates": self.objects, "hostileNpcTemplates": [t for t, _ in self.htpl],
            "entities": self.entities, "playerId": self.player["id"],
        }

    def write(self, out_dir, make_zip=True):
        name = self.s.get("folderName", self.s["name"].replace(" ", "-"))
        root = os.path.join(out_dir, name + ".scenario")
        if os.path.exists(root):
            shutil.rmtree(root)
        os.makedirs(os.path.join(root, "media"))
        scn = self.scenario()
        with open(os.path.join(root, "scenario.json"), "w", encoding="utf-8") as f:
            json.dump(scn, f, ensure_ascii=False, indent=1)
        n = 0
        for eid, (src, crop) in self.portraits.items():
            if Image is None:
                self.warn("Pillow missing; portraits skipped")
                break
            d = os.path.join(root, "media", eid)
            os.makedirs(d)
            portrait_webp(src, os.path.join(d, f"{eid}-portrait.webp"), crop)
            n += 1
        zpath = None
        if make_zip:
            zpath = root + ".zip"
            with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
                for base, _, files in os.walk(root):
                    for fn in files:
                        full = os.path.join(base, fn)
                        z.write(full, os.path.relpath(full, root).replace(os.sep, "/"))
        return root, zpath, n


def portrait_webp(src, dst, crop=None, size=512):
    """Square head-and-shoulders crop. crop = (cx, top, side) as fractions of the
    source width/height/width; default keeps the upper-centre of a portrait."""
    im = Image.open(src).convert("RGB")
    W, H = im.size
    cx, top, side = crop or (0.5, 0.03, 0.8)
    s = int(min(W, H) * side) if side <= 1 else int(side)
    x0 = max(0, min(W - s, int(W * cx - s / 2)))
    y0 = max(0, min(H - s, int(H * top)))
    im.crop((x0, y0, x0 + s, y0 + s)).resize((size, size), Image.LANCZOS).save(dst, "WEBP", quality=88)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--out", help="output dir (default: spec's folder)")
    ap.add_argument("--no-zip", action="store_true")
    a = ap.parse_args()
    spec = load_spec(a.spec)
    b = Builder(spec, os.path.dirname(os.path.abspath(a.spec)))
    b.build_regions()
    b.build_items()
    b.build_objects()
    b.build_hostile_templates()
    b.build_entities()
    b.build_systems()
    for w in b.warnings:
        print("WARN ", w)
    if b.errors:
        for e in b.errors:
            print("ERROR", e)
        print(f"{len(b.errors)} error(s); nothing written.")
        sys.exit(1)
    root, z, n = b.write(a.out or os.path.dirname(os.path.abspath(a.spec)), not a.no_zip)
    ents = b.entities
    print(f"wrote {root}  ({len(b.regions)} regions, {sum(e['type']=='object' for e in ents)} objects, "
          f"{sum(e['type']=='npc' for e in ents)} npcs, {n} portraits)")
    if z:
        print(f"zip   {z}")


if __name__ == "__main__":
    main()
