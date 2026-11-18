"""Convert the room layouts (library/layouts/*.json) into furniture groups
(library/groups/<family>.json): the fixed clusters a layout describes through
its beside:/around: anchors, plus one recipe per layout naming the groups it
needs. Run from anywhere: python library-seed/layouts_to_groups.py

Hand work survives: a group or a whole recipe with "source": "hand" in an
existing file is kept verbatim (a converted group that would take a hand
group's id is dropped, with a note), and a recipe entry with
"source": "hand" is kept on the converted recipe it sat on. luxury.json is
never written, and its ids, like hand ids, are never handed to a converted
group.

How a layout becomes groups
---------------------------
* The root of a group is a slot whose anchor has no beside:/around: token;
  every slot or grow entry pointing beside: or around: at a slot joins that
  slot's group (transitively — pointing at a child of a group joins the same
  group). The root sits at (0, 0) and the group is laid out north-facing:
  the root's wall becomes north, the group's canonical orientation.
* wall is "back" when the root leans on a wall (back "wall", or a wall:/row:
  anchor) or any member slot has back "wall"; else "corner" when the root's
  anchor has "corner"; else "none". Wall-bound pieces get back "north" and
  sit on row 0. A slot on an east or west wall is turned (its footprint
  swaps); door-relative anchors (far/side/near) keep the size as written,
  the canonical reading of a [k, 1] counter or desk.
* beside:X children touch X's left and right (relative to X's back): one
  piece by default, both sides with +symmetric or a count above one. A child
  of a slot that repeats gets ceil(child count / slot count) pieces per
  group, capped at two (one a side); wider count ranges collapse and are
  noted. Free children turn to run across the target's end; wall-bound
  children keep their footprint on the back line.
* around:X children sit on the sides of X not against the group's wall,
  spread evenly, their count at maximum (divided by the target's count when
  it repeats). Pieces on the east and west sides are turned: every size in
  the files is the placed footprint.
* Grow entries pointing beside: or around: at a slot join that group as
  optional pieces (carrying any minWealth); other grow entries become
  one-piece optional groups. Offsets are normalised so each group's bounding
  box starts at (0, 0).

use, kinds, ids
---------------
* use (the sides people stand or sit at) is computed from the root. The
  table below started from the design's — sleep pieces take their long open
  sides (a bed climbed into from beside, not the side against the wall or
  taken by a bedside), tables (and a coffin, stood around) take every open
  side, seats take the side you sit down from, pieces you face take the
  front (south, canonical). Everything else (bedsides, lamps, decor) has
  none.
* The recipe's anchor is the group of the family's main piece (MAIN_ROLE
  below — the design's list rule per family), falling back to the first
  slot; a main piece that was optional still anchors, noted. Then kinds:
  optional for optional:true slots and grow groups; repeatable for slots
  with a count above one, row: anchors, and singles/couples in dormitories
  and wards; required for the rest.
* Ids are <root role>.<suffix>, the suffix naming the pieces in placement
  order (a lone piece is <role>.single, e.g. storage.big.single), optional
  pieces marked .opt. Groups with the same family, wall, use and pieces
  share an id; a base id taken by another family gets the family appended.
"""
import json
import os

SEED = os.path.dirname(os.path.abspath(__file__))
LIBRARY = os.path.join(SEED, "..", "library")
SIDES = ("north", "east", "south", "west")

# The slot whose group anchors a family's recipes: the family's main piece,
# falling back to the first slot (None = always the first slot).
MAIN_ROLE = {
    "bedroom": "sleep",
    "bedroom.master": "sleep.couple",
    "cell": "cell.bed",
    "chapel": "altar",
    "classroom": "teach",
    "clinic": "med.station",
    "common_room": "counter.serve",     # the bar; living rooms fall back
    "control": "control",
    "dining": "table.dining",
    "dormitory": "sleep",
    "greenhouse": "grow",
    "guardroom": "weapons",
    "gym": "exercise",
    "hut": "sleep",
    "kitchen": "cook",
    "laboratory": "work.primary",
    "library": "books",
    "laundry": "laundry.wash",
    "office": "desk",
    "passage": None,
    "shop": "counter.serve",
    "stable": "animal",
    "storage": "shelving",
    "ward": "med.bed",
    "washroom": "wash.toilet",
    "workshop": "work.primary",
}

# use, from the root's role. Sleep pieces: their long open sides. Tables
# (and a coffin, stood around): every open side. Seats: the side you sit
# down from. The front list: pieces you stand in front of, which face south
# (the wall side of a back group). work.* joins the front list.
USE_SLEEP = ("sleep", "sleep.couple", "sleep.child", "med.bed", "cell.bed")
USE_TABLE = ("table.dining", "table.small", "table.work", "game", "coffin")
USE_SEAT = ("seat", "seat.long", "seat.lounge", "seat.state")
USE_FRONT = (
    "altar", "animal", "bake", "books", "coat", "computer", "control", "cook",
    "counter.prep", "counter.serve", "desk", "display", "devotion", "exercise",
    "fuel", "grow", "heat", "laundry.dry", "laundry.wash", "lectern",
    "med.station", "med.supply", "music", "radio", "screen", "security",
    "server", "shelving", "storage.big", "storage.bulk", "storage.cold",
    "storage.small", "teach", "utility", "wash.basin", "wash.bath",
    "wash.toilet", "waste", "weapons",
)


def _tokens(anchor):
    return [t.strip() for t in (anchor or "").split("+") if t.strip()]


def _count_max(count):
    if isinstance(count, int):
        return count
    if isinstance(count, list):
        return count[1]
    if count in ("singles", "couples"):
        return 2
    return 1


def _target(entry):
    """("beside"|"around", slot id) when the anchor points at a slot."""
    for tok in _tokens(entry.get("anchor")):
        if tok.startswith("beside:") or tok.startswith("around:"):
            kind, _, sid = tok.partition(":")
            return kind, sid
    return None


class _Group:
    """A group under construction: pieces in placement order, offsets
    relative to the root at (0, 0) until normalised."""

    def __init__(self, family, wall):
        self.family = family
        self.wall = wall
        self.pieces = []
        self.use = []

    def rect(self, i):
        p = self.pieces[i]
        return p["at"][0], p["at"][1], p["size"][0], p["size"][1]

    def free(self, x, y, w, h):
        for i in range(len(self.pieces)):
            px, py, pw, ph = self.rect(i)
            if x < px + pw and px < x + w and y < py + ph and py < y + h:
                return False
        return True

    def add(self, role, size, x, y, back=False, optional=False, min_wealth=None):
        p = {"role": role, "size": list(size), "at": [x, y]}
        if back:
            p["back"] = "north"
        if optional:
            p["optional"] = True
        if min_wealth:
            p["minWealth"] = min_wealth
        self.pieces.append(p)
        return len(self.pieces) - 1


def _root_size(slot):
    """The root's footprint in the group's north-facing frame: a slot on an
    east or west wall (wall: or row:) is turned, its footprint swaps."""
    w, h = slot.get("size") or [1, 1]
    for tok in _tokens(slot.get("anchor")):
        if tok in ("wall:west", "wall:east", "row:west", "row:east"):
            return [h, w]
    return [w, h]


def _group_wall(root, members):
    toks = _tokens(root.get("anchor"))
    if root.get("back") == "wall":
        return "back"
    if any(t.startswith("wall:") or t.startswith("row:") for t in toks):
        return "back"
    if any(m.get("back") == "wall" for m in members):
        return "back"
    if "corner" in toks:
        return "corner"
    return "none"


def _name(entry):
    return entry.get("id") or entry.get("role")


def _place_beside(g, t_idx, child, t_slot, notes, lid):
    """One or two children touching the target's left and right, stacking
    down the group when a side is taken. Returns (first piece, placed)."""
    tx, ty, tw, th = g.rect(t_idx)
    wall_child = child.get("back") == "wall"
    sw, sh = child.get("size") or [1, 1]
    cw, ch = (sw, sh) if wall_child else (sh, sw)
    cmax = _count_max(child.get("count", 1))
    tmax = max(1, _count_max(t_slot.get("count", 1)))
    symmetric = "symmetric" in _tokens(child.get("anchor"))
    n = 2 if symmetric else max(1, min(2, -(-cmax // tmax)))
    if cmax > n * tmax:
        notes.append(f"{lid}: {_name(child)} count {child.get('count', 1)} "
                     f"beside {tmax} {_name(t_slot)}(s) collapses to {n} a group")
    # a corner group's west is its second wall: grow east first
    sides = ("east", "west") if g.wall == "corner" else ("west", "east")
    placed, first = 0, None
    for side in sides:
        if placed >= n:
            break
        x = tx - cw if side == "west" else tx + tw
        ys = (0,) if wall_child else range(ty, ty + max(
            p["at"][1] + p["size"][1] for p in g.pieces) + 2)
        for y in ys:
            if g.free(x, y, cw, ch):
                i = g.add(child["role"], [cw, ch], x, y, back=wall_child,
                          optional=bool(child.get("_grow")),
                          min_wealth=child.get("minWealth"))
                first = i if first is None else first
                placed += 1
                break
    if placed < n:
        notes.append(f"{lid}: {_name(child)} has no free cell beside "
                     f"{_name(t_slot)}; {n - placed} piece(s) dropped")
    return first, placed


def _spread(m, cnt):
    """cnt indices spread over m candidates: the middle for one, the ends
    out for more (candidates are start positions, cnt <= m)."""
    if cnt >= m:
        return list(range(m))
    if cnt == 1:
        return [(m - 1) // 2]
    return sorted({round(i * (m - 1) / (cnt - 1)) for i in range(cnt)})


def _place_around(g, t_idx, child, t_slot, notes, lid):
    """Children on the target's open sides, spread evenly, count at maximum
    (per copy when the target repeats). East and west pieces are turned.
    Returns (first piece, placed)."""
    tx, ty, tw, th = g.rect(t_idx)
    sw, sh = child.get("size") or [1, 1]
    cmax = _count_max(child.get("count", 1))
    tmax = max(1, _count_max(t_slot.get("count", 1)))
    n = cmax if tmax == 1 else max(1, -(-cmax // tmax))
    if g.wall == "corner":
        blocked = ("north", "west")
    elif g.wall == "back":
        blocked = ("north",)
    else:
        blocked = ()
    spots = []
    if "north" not in blocked:
        spots += [("north", x, ty - sh, sw, sh) for x in range(0, tw - sw + 1)]
    if "south" not in blocked:
        spots += [("south", x, ty + th, sw, sh) for x in range(0, tw - sw + 1)]
    if "east" not in blocked:
        spots += [("east", tx + tw, ty + y, sh, sw) for y in range(0, th - sw + 1)]
    if "west" not in blocked:
        spots += [("west", tx - sh, ty + y, sh, sw) for y in range(0, th - sw + 1)]
    by_side = {}
    for s in spots:
        if g.free(s[1], s[2], s[3], s[4]):
            by_side.setdefault(s[0], []).append(s)
    if not by_side:
        notes.append(f"{lid}: {_name(child)} has no free side around "
                     f"{_name(t_slot)}; dropped")
        return None, 0
    # greedy even spread: each piece to the side with the most room left,
    # north before south before the ends on ties
    rank = {"north": 0, "south": 1, "east": 2, "west": 3}
    take = {side: 0 for side in by_side}
    for _ in range(n):
        side = min(by_side, key=lambda s: (-(len(by_side[s]) - take[s]), rank[s]))
        if len(by_side[side]) - take[side] <= 0:
            break
        take[side] += 1
    placed, first = 0, None
    for side in sorted(take, key=lambda s: rank[s]):
        cand = by_side[side]
        for i in _spread(len(cand), take[side]):
            _, x, y, w, h = cand[i]
            pi = g.add(child["role"], [w, h], x, y,
                       optional=bool(child.get("_grow")),
                       min_wealth=child.get("minWealth"))
            first = pi if first is None else first
            placed += 1
    if placed < n:
        notes.append(f"{lid}: {_name(child)} around {_name(t_slot)} only fits "
                     f"{placed} of {n}; the rest dropped")
    return first, placed


def _use(g, root=0):
    """The sides people stand or sit at, from the root piece."""
    p = g.pieces[root]
    role, (rw, rh), (rx, ry) = p["role"], p["size"], p["at"]

    def touched(side):
        if side == "north":
            strip = [(cx, ry - 1) for cx in range(rx, rx + rw)]
        elif side == "south":
            strip = [(cx, ry + rh) for cx in range(rx, rx + rw)]
        elif side == "east":
            strip = [(rx + rw, cy) for cy in range(ry, ry + rh)]
        else:
            strip = [(rx - 1, cy) for cy in range(ry, ry + rh)]
        for i, q in enumerate(g.pieces):
            if i == root or q.get("optional"):
                continue
            qx, qy, qw, qh = q["at"][0], q["at"][1], q["size"][0], q["size"][1]
            if any(qx <= cx < qx + qw and qy <= cy < qy + qh for cx, cy in strip):
                return True
        return False

    if g.wall == "corner":
        walled = ("north", "west")
    elif g.wall == "back":
        walled = ("north",)
    else:
        walled = ()
    if role in USE_SLEEP:
        lengths = {"north": rw, "east": rh, "south": rw, "west": rh}
        return [s for s in SIDES
                if lengths[s] >= 2 and s not in walled and not touched(s)]
    if role in USE_TABLE:
        return [s for s in SIDES if s not in walled and not touched(s)]
    if role in USE_SEAT or role in USE_FRONT or role.startswith("work."):
        return ["south"]
    return []


def _normalise(g):
    min_x = min(p["at"][0] for p in g.pieces)
    min_y = min(p["at"][1] for p in g.pieces)
    for p in g.pieces:
        p["at"] = [p["at"][0] - min_x, p["at"][1] - min_y]


def convert_layout(layout):
    """One layout -> {"groups": [...], "recipe": {...}, "notes": [...]}.
    Groups are complete except for "id" (assigned by convert_all, which
    deduplicates); recipe entries carry their group's index in "group"."""
    notes = []
    lid = layout.get("id")
    family = layout.get("family")
    slots = list(layout.get("slots") or [])
    grows = list(layout.get("grow") or [])
    by_id = {s["id"]: s for s in slots}

    def root_of(sid):
        """The slot's group root: follow beside:/around: to the end (the
        seen-set only guards a cycle the layout checker doesn't rule out)."""
        seen = set()
        cur = sid
        while True:
            seen.add(cur)
            t = _target(by_id.get(cur) or {})
            if not t or t[1] not in by_id or t[1] in seen:
                return cur
            cur = t[1]

    order, children = [], {}
    for s in slots:
        r = root_of(s["id"])
        if r == s["id"]:
            if r not in children:
                children[r] = []
                order.append(r)
        else:
            children.setdefault(r, []).append(s)

    # the anchor: the family's main piece, else the first slot
    main = MAIN_ROLE.get(family)
    anchor = next((s for s in slots if s.get("role") == main), None)
    if anchor is None and slots:
        anchor = slots[0]
    if anchor and anchor.get("optional"):
        notes.append(f"{lid}: optional slot {anchor['id']} anchors the recipe")

    groups, piece_of = [], {}
    for rid in order:
        root = by_id[rid]
        members = children.get(rid) or []
        g = _Group(family, _group_wall(root, members))
        g.add(root["role"], _root_size(root), 0, 0, back=root.get("back") == "wall")
        piece_of[rid] = 0
        for child in members:
            kind, tsid = _target(child)
            if tsid not in piece_of:
                notes.append(f"{lid}: {_name(child)} points at {tsid!r}, "
                             f"which placed no piece; dropped")
                continue
            placer = _place_beside if kind == "beside" else _place_around
            first, _n = placer(g, piece_of[tsid], child, by_id[tsid], notes, lid)
            if first is not None:
                piece_of[child["id"]] = first
        g.use = _use(g)
        _normalise(g)
        groups.append(g)
    group_index = {rid: i for i, rid in enumerate(order)}

    # grow entries: joins first (optional pieces in a slot's group), then
    # the standalone one-piece optional groups
    grow_alone = []
    for entry in grows:
        if not entry.get("size"):
            notes.append(f"{lid}: grow {entry.get('role')} has no size; "
                         f"using [1, 1]")
        t = _target(entry)
        if not (t and t[1] in by_id):
            grow_alone.append(entry)
            continue
        rid = root_of(t[1])
        if rid not in group_index:
            notes.append(f"{lid}: grow {entry.get('role')} points into a "
                         f"beside/around cycle; dropped")
            continue
        g = groups[group_index[rid]]
        entry = dict(entry, _grow=True)
        placer = _place_beside if t[0] == "beside" else _place_around
        placer(g, piece_of.get(t[1], 0), entry, by_id[t[1]], notes, lid)
        g.use = _use(g)
        _normalise(g)
    for entry in grow_alone:
        g = _Group(family, _group_wall(entry, []))
        g.add(entry["role"], _root_size(entry), 0, 0,
              back=entry.get("back") == "wall",
              optional=True, min_wealth=entry.get("minWealth"))
        g.use = _use(g)
        _normalise(g)
        groups.append(g)

    def kind_of(slot):
        if slot is anchor:
            return "anchor"
        if slot.get("optional"):
            return "optional"
        if (_count_max(slot.get("count", 1)) > 1
                or any(t.startswith("row:") for t in _tokens(slot.get("anchor")))
                or (slot.get("count") in ("singles", "couples")
                    and family in ("dormitory", "ward"))):
            return "repeatable"
        return "required"

    entries = []
    for i, rid in enumerate(order):
        slot = by_id[rid]
        e = {"group": i, "kind": kind_of(slot)}
        if slot.get("count", 1) != 1:
            e["count"] = slot["count"]
        if slot.get("minWealth"):
            e["minWealth"] = slot["minWealth"]
        entries.append(e)
    for j, entry in enumerate(grow_alone):
        e = {"group": len(order) + j, "kind": "optional"}
        if entry.get("minWealth"):
            e["minWealth"] = entry["minWealth"]
        entries.append(e)
    recipe = {"layout": lid, "family": family,
              "sizeBands": list(layout.get("sizeBands") or []), "groups": entries}
    return {"groups": groups, "recipe": recipe, "notes": notes}


def _group_key(g):
    return (g.family, g.wall, tuple(g.use),
            tuple((p["role"], tuple(p["size"]), tuple(p["at"]),
                   p.get("back"), p.get("optional"), p.get("minWealth"))
                  for p in g.pieces))


def _suffix(g):
    if len(g.pieces) == 1:
        return "single"
    parts = []
    for p in g.pieces[1:]:
        role = p["role"] + (".opt" if p.get("optional") else "")
        if parts and parts[-1][0] == role:
            parts[-1][1] += 1
        else:
            parts.append([role, 1])
    return ".".join(r + (str(n) if n > 1 else "") for r, n in parts)


def read_hand(path):
    """The hand material one existing groups file holds, for the converter
    to keep: its groups and whole recipes with "source": "hand", verbatim,
    plus the source-"hand" entries of every other recipe.
    {"groups": [...], "recipes": {layout: recipe}, "entries": {layout:
    [entry, ...]}} — or None when the file is missing, unreadable or holds
    no hand work at all."""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    hand = {"groups": [g for g in raw.get("groups") or []
                       if isinstance(g, dict) and g.get("source") == "hand"],
            "recipes": {}, "entries": {}}
    for r in raw.get("recipes") or []:
        if not isinstance(r, dict):
            continue
        lid = r.get("layout")
        if r.get("source") == "hand":
            hand["recipes"][lid] = r
        else:
            entries = [e for e in (r.get("groups") or [])
                       if isinstance(e, dict) and e.get("source") == "hand"]
            if entries:
                hand["entries"][lid] = entries
    return hand if any(hand.values()) else None


def convert_all(layouts, hand=None, reserved=()):
    """{family: [layout, ...]} -> ({family: file dict}, [notes]). Same-family
    groups with the same wall, use and pieces share an id; a base id taken
    by another family gets the family appended, and one held by hand work
    or the luxury file (``reserved``) drops the converted group — a note
    says so. ``hand`` ({family: what read_hand found}) keeps hand groups and
    whole hand recipes verbatim and hand entries on the converted recipes
    they sat on. Deterministic: families, layouts and pieces are handled in
    a fixed order."""
    hand = hand or {}
    notes = []
    files = {}
    seen = {}       # group key -> id (within a family)
    fixed = set(reserved)   # ids no converted group may take (hand, luxury)
    for keep in hand.values():
        for g in (keep or {}).get("groups") or []:
            if isinstance(g, dict) and g.get("id"):
                fixed.add(g["id"])
    taken = set(fixed)      # every id, across all files, hand ones included
    for family in sorted(layouts):
        keep = hand.get(family) or {}
        hand_groups = keep.get("groups") or []
        hand_recipes = keep.get("recipes") or {}
        hand_entries = keep.get("entries") or {}
        groups_out, recipes_out = [], []
        for layout in sorted(layouts[family], key=lambda l: str(l.get("id"))):
            lid = layout.get("id")
            r = convert_layout(layout)
            notes += r["notes"]
            ids = []
            for g in r["groups"]:
                key = _group_key(g)
                if key in seen:
                    ids.append(seen[key])
                    continue
                base = f"{g.pieces[0]['role']}.{_suffix(g)}"
                if base in fixed:
                    # the id belongs to a hand group (or the luxury file):
                    # that one stands, this converted one is dropped
                    notes.append(f"{lid}: converted group {base!r} shares "
                                 f"a hand group's id; dropped")
                    seen[key] = base
                    ids.append(base)
                    continue
                gid = base
                if gid in taken:
                    gid = f"{base}.{family}"
                    extra = 0
                    while gid in taken:
                        extra += 1
                        gid = f"{base}.{family}{extra}"
                seen[key] = gid
                taken.add(gid)
                ids.append(gid)
                groups_out.append({"id": gid, "family": g.family, "wall": g.wall,
                                   "use": list(g.use), "pieces": g.pieces})
            if lid in hand_recipes:
                recipes_out.append(hand_recipes[lid])    # verbatim, always
                continue
            recipe = dict(r["recipe"])
            recipe["groups"] = [dict(e, group=ids[e["group"]])
                                for e in r["recipe"]["groups"]]
            recipe["groups"] += [dict(e) for e in hand_entries.get(lid) or []]
            recipes_out.append(recipe)
        groups_out += [dict(g) for g in hand_groups]
        covered = {l.get("id") for l in layouts[family]}
        recipes_out += [hand_recipes[l] for l in sorted(hand_recipes, key=str)
                        if l not in covered]
        files[family] = {"groups": groups_out, "recipes": recipes_out}
    return files, notes


def main():
    layouts = {}
    layouts_dir = os.path.join(LIBRARY, "layouts")
    for name in sorted(os.listdir(layouts_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(layouts_dir, name), "r", encoding="utf-8") as fh:
            for layout in (json.load(fh) or {}).get("layouts") or []:
                layouts.setdefault(layout.get("family"), []).append(layout)

    # the use and anchor tables must name real roles
    with open(os.path.join(LIBRARY, "library.json"), "r", encoding="utf-8") as fh:
        roles = set((json.load(fh) or {}).get("roles") or [])
    known = roles | {"work.primary"}
    for role in sorted(set(USE_SLEEP + USE_TABLE + USE_FRONT)
                       | {r for r in MAIN_ROLE.values() if r}):
        if role not in known:
            print(f"WARNING: {role} in the conversion tables names no role")

    # the hand work the existing files hold (kept verbatim), and every id
    # the converter may not hand out: hand groups' and the luxury file's
    groups_dir = os.path.join(LIBRARY, "groups")
    hand, reserved = {}, set()
    if os.path.isdir(groups_dir):
        for name in sorted(os.listdir(groups_dir)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(groups_dir, name)
            if name == "luxury.json":          # never written, never renamed
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        raw = json.load(fh)
                    reserved.update(g.get("id") for g in raw.get("groups") or []
                                    if isinstance(g, dict))
                except (OSError, ValueError, AttributeError):
                    pass
                continue
            h = read_hand(path)
            if h:
                hand[name[:-5]] = h
                reserved.update(g.get("id") for g in h["groups"]
                                if isinstance(g.get("id"), str))

    files, notes = convert_all(layouts, hand, reserved)
    os.makedirs(groups_dir, exist_ok=True)
    total_g = total_r = total_hg = total_hr = total_he = 0
    for family in sorted(files):
        path = os.path.join(groups_dir, family + ".json")
        # newline="\n": the files are LF on every platform, so running the
        # converter on the shipped files writes their very bytes back
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(files[family], fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        n, m = len(files[family]["groups"]), len(files[family]["recipes"])
        hg = len((hand.get(family) or {}).get("groups") or [])
        hr = len((hand.get(family) or {}).get("recipes") or {})
        he = sum(len(v) for v in ((hand.get(family) or {}).get("entries")
                                  or {}).values())
        total_g += n
        total_r += m
        total_hg += hg
        total_hr += hr
        total_he += he
        print(f"{family}: {n} groups, {m} recipes"
              + (f" ({hg} hand group(s), {hr} hand recipe(s), "
                 f"{he} hand entr(ies) kept)" if hg or hr or he else ""))
    print(f"wrote {len(files)} files: {total_g} groups, {total_r} recipes, "
          f"{total_hg} hand group(s), {total_hr} hand recipe(s), "
          f"{total_he} hand entr(ies), {len(notes)} note(s)")
    for note in notes:
        print("note: " + note)


if __name__ == "__main__":
    main()
