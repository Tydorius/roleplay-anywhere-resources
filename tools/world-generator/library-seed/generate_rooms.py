"""Generate the first fixed rooms into library/rooms/<family>.json: every
recipe of the bedroom, master bedroom, washroom, privy, bath, closet,
courtyard, garden and yard families composed at each clearance
(tight/roomy/grand) in each style the family takes (flush/open; the outdoor
families flush alone, their rooms having no walls to open against), seed 1,
keeping the best room of each. The bedroom family also
composes its recipes for two singles (its two-bed rooms, described as "for
two"), under the same rules and the same shape dedupe, their ids continuing
the letter sequence. A hand recipe of a
family with its own familySizeBands table composes once per band it names,
the band pinned (a band its furniture cannot reach produces no room — the
composer never pads a room up to one), and its optional "wealth" list
overrides the clearance's tiers. A grand private room keeps the roomy gap, joins its
family's luxury pool (one group of each luxury kind at most) and must carry
a luxury group, more pieces than the roomy room of the same recipe and style
and an area of at most GRAND_AREA_RATIO times it (one placing an elite-only
piece is tagged elite alone), or it is dropped with a reason. Two rooms that
are the same after any turn or mirror
are one room; the survivor is the one that comes first in recipe, clearance
and style order, which is the one with the lower id. Ids are
<family>.<sizeBand>.<letter>.<clearance>.<style>, stable between runs and
between regenerations: a room whose shape is already shipped keeps its id,
and a new room takes the next free letter of its family, band, clearance
and style.

Hand work survives regeneration: a room with "source": "hand" (one a person
made or re-laid out) or "retired": true (one a person took out of use; it
stays so its id is never reused) is kept exactly as it stands, its id's
letter stays taken and a generated room equal to it after any turn or mirror
is dropped in its favour; a generated room whose id survives keeps the
values of the fields in its "edited" list (wealth, description, symmetric,
retired). With no hand work in the files the output is exactly what a fresh
generation writes.

  python library-seed/generate_rooms.py [family ...]

Prints a table (per family: recipes, rooms kept, rooms dropped and why, the
size range per band) and writes each family's rooms sorted by id with stable
formatting; a room whose shape is already shipped keeps its id, so running
the generator twice changes nothing.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.dirname(HERE)
sys.path.insert(0, GEN)

from worldgen import fixed_rooms as FR      # noqa: E402
from worldgen import library as WL          # noqa: E402
from worldgen import room_composer as RC    # noqa: E402
from worldgen import room_groups as RG      # noqa: E402

FAMILIES = ("bedroom", "bedroom.master", "washroom", "privy", "bath", "closet",
            "courtyard", "garden", "yard")
SEED = 1
CLEARANCES = ("tight", "roomy", "grand")
STYLES = ("flush", "open")


def styles_for(fam):
    """The styles a family composes in: an outdoor family keeps the flush
    style, the open middle being a wall-room idea."""
    return ("flush",) if FR.is_outdoor_family(fam) else STYLES
# a grand private room carries so much furniture that no piece stands over
# more than this many cells of floor (the shipped grand rooms assert it)
GRAND_MAX_CELLS_PER_PIECE = 8
ROOMS_DIR = os.path.join(GEN, "library", "rooms")

# how a role reads in a room's description, the first matching prefix wins
NOUNS = (
    ("sleep.couple", "double bed"),
    ("sleep.child", "child's bed"),
    ("sleep", "bed"),
    ("med.bed", "bed"),
    ("cell.bed", "bed"),
    ("bedside", None),
    ("storage.big", "wardrobe"),
    ("storage.small", "chest"),
    ("storage.cold", "icebox"),
    ("storage.bulk", "sack"),
    ("shelving", "shelf"),
    ("utility", "utility stand"),
    ("wash.bath", "bathtub"),
    ("wash.basin", "washbasin"),
    ("wash.toilet", "privy"),
    ("seat.lounge", "armchair"),
    ("seat.long", "bench"),
    ("seat.state", "throne"),
    ("seat", "chair"),
    ("table.small", "small table"),
    ("table", "table"),
    ("desk", "desk"),
    ("counter", "counter"),
    ("light.big", "lamp"),
    ("light.small", "lamp"),
    ("light", "lamp"),
    ("heat", "stove"),
    ("fuel", "fuel bin"),
    ("coat", "coat rack"),
    ("waste", "waste bucket"),
    ("decor.floor", "floor rug"),
    ("decor.feature", "centrepiece"),
    ("animal", "trough"),
    ("grow", "plant bed"),
    ("decor", "decoration"),
)
FAMILY_NOUNS = {"bedroom": "bedroom", "bedroom.master": "master bedroom",
                "washroom": "washroom", "privy": "privy", "bath": "bath room",
                "closet": "closet", "courtyard": "courtyard",
                "garden": "garden", "yard": "yard"}
BAND_ADJECTIVES = {"tiny": "cramped", "small": "small", "medium": "mid-sized",
                   "large": "spacious", "stall": "stall", "reach": "reach-in",
                   "walkin": "walk-in"}
# the roles a family is about: an instance of these is the instance's name
# (the bed and its bedside read as "bed") and is mentioned first
FAMILY_ROLES = {"bedroom": ("sleep",), "bedroom.master": ("sleep",),
                "washroom": ("wash",), "privy": ("wash",), "bath": ("wash",),
                "closet": ("storage", "shelving", "utility"),
                "courtyard": ("decor.feature",), "garden": ("grow",),
                "yard": ("animal", "storage")}
MAX_MENTIONS = 4      # furniture groups named in one description
LETTERS = "abcdefghijklmnopqrstuvwxyz"


def _noun(role):
    for prefix, noun in NOUNS:
        if role == prefix or role.startswith(prefix + "."):
            return noun
    return role.replace(".", " ")


def _article(noun):
    return "an" if noun[0] in "aeiou" else "a"


def _family_role(room, role):
    return any(role == p or role.startswith(p + ".")
               for p in FAMILY_ROLES.get(room["family"], ()))


def _instance_noun(room, inst):
    """An instance's name: its biggest piece, a tie going to the family's
    own pieces (the basin, not the chest beside it)."""
    best = None
    for i in inst["indices"]:
        p = room["pieces"][i]
        rank = (p["size"][0] * p["size"][1], 1 if _family_role(room, p["role"])
                else 0)
        if best is None or rank > best[0]:
            best = (rank, p["role"])
    return _noun(best[1]) if best else None


def _placement(room, inst, first_wall):
    """Where an instance stands: a corner, a wall (opposite the first
    wall-bound group when it is the facing wall), or the open middle."""
    x, y, w, h = inst["box"]
    W, H = room["size"]
    on = {"north": y == 0, "south": y + h == H,
          "west": x == 0, "east": x + w == W}
    walls = [s for s in FR.SIDES if on[s]]
    if {"north", "south"} & set(walls) and {"east", "west"} & set(walls):
        ns = "north" if "north" in walls else "south"
        ew = "west" if "west" in walls else "east"
        return f"in the {ns}{ew} corner"
    if walls:
        side = walls[0]
        if first_wall and FR.OPPOSITE[side] == first_wall:
            return "opposite"
        return f"against the {side} wall"
    return "in the open middle" if room["style"] == "open" \
        else "in the middle of the room"


def describe(room):
    """One sentence built from the room's pieces and layout, no model calls."""
    w, h = room["size"]
    head = FAMILY_NOUNS.get(room["family"], room["family"])
    sleeps = room.get("sleeps") or {}
    if room["family"] == "bedroom" and not sleeps.get("couples"):
        if sleeps.get("singles", 0) == 1:
            head = "single " + head
        elif sleeps.get("singles", 0) == 2 and room.get("_fortwo"):
            head = head + " for two"
    adjs = []
    band = BAND_ADJECTIVES.get(room["sizeBand"])
    if band:
        adjs.append(band)
    if 2 * min(w, h) <= max(w, h):
        adjs.append("narrow")
    if adjs:
        head = ", ".join(adjs) + " " + head
    phrases = []
    first_wall = None
    insts = sorted(FR.instances(room),
                   key=lambda i: (0 if any(_family_role(room, room["pieces"][n]["role"])
                                           for n in i["indices"]) else 1,
                                  i["box"][1], i["box"][0]))
    for n, inst in enumerate(insts):
        noun = _instance_noun(room, inst)
        if noun is None or len(phrases) >= MAX_MENTIONS:
            continue
        where = _placement(room, inst, first_wall)
        x, y, w2, h2 = inst["box"]
        for side, on in (("north", y == 0), ("south", y + h2 == room["size"][1]),
                         ("west", x == 0), ("east", x + w2 == room["size"][0])):
            if on and first_wall is None:
                first_wall = side
        phrases.append((noun if not n else f"{_article(noun)} {noun}") + " " + where)
    if room["style"] == "open" and phrases:
        phrases.append("open floor in the middle")
    if not phrases:
        return f"A {head}."
    body = (", ".join(phrases[:-1]) + ", and " + phrases[-1]
            if len(phrases) > 2 else ", ".join(phrases))
    return f"A {head}, {body}."


def wealth_for(clearance, style):
    """The wealth tiers a room serves: the style's by default, roomy flush
    rooms also the wealthy, grand rooms only the wealthy and elite."""
    if clearance == "grand" or style == "open":
        return ["wealthy", "elite"]
    return ["poor", "modest"] + (["wealthy"] if clearance == "roomy" else [])


def uses_elite_piece(room, gdefs):
    """Whether the room places a group with an elite-only piece (minWealth
    elite on any of its pieces): a grand room like that serves the elite
    alone. Placed pieces carry no minWealth, so the group definitions are
    the place to look."""
    for p in room["pieces"]:
        g = gdefs.get(p.get("group")) or {}
        if any(isinstance(q, dict) and q.get("minWealth") == "elite"
               for q in g.get("pieces") or []):
            return True
    return False


def canonical(room):
    """The room's shape in its lowest-sorting orientation (four turns and
    the mirror), so two rooms equal after any turn or mirror share a key."""
    sigs = []
    for mirror in (False, True):
        for turn in range(4):
            t = FR.rotate(room, turn, mirror)
            sigs.append((tuple(t["size"]),
                         tuple(sorted((p["role"], p["at"][0], p["at"][1],
                                       p["size"][0], p["size"][1],
                                       p.get("back"))
                                      for p in t["pieces"]))))
    return min(sigs)


def _finalize(room, rid, elite=False):
    """A room in the shipped field order, with its id, wealth tiers and
    description. A grand room placing an elite-only piece serves the elite
    alone. A recipe's "wealth" override (stashed on the room as "_wealth")
    beats the clearance's tiers."""
    wealth = room.pop("_wealth", None) or wealth_for(room["clearance"],
                                                     room["style"])
    out = {"id": rid, "family": room["family"], "sizeBand": room["sizeBand"],
           "clearance": room["clearance"], "style": room["style"],
           "wealth": (["elite"] if elite else wealth),
           "size": room["size"], "sleeps": room["sleeps"],
           "pieces": room["pieces"], "doors": room["doors"],
           "stretch": room["stretch"]}
    if room["style"] == "open":
        out["filler"] = room["filler"]
    out.update({"outdoor": FR.is_outdoor_family(room["family"]),
                "symmetric": room["symmetric"],
                "recipe": room["recipe"], "description": describe(room)})
    return out


def _shipped_rooms(fam, rooms_dir=None):
    """The family's stored rooms as shipped (only rooms with a readable id):
    the hand and retired ones the generator keeps verbatim, and the ones
    whose edited fields it preserves."""
    path = os.path.join(rooms_dir or ROOMS_DIR, f"{fam}.json")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            rooms = json.load(fh)["rooms"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    return [r for r in rooms
            if isinstance(r, dict) and isinstance(r.get("id"), str)]


def _shipped_ids(fam, rooms_dir=None):
    """canonical shape -> id for the family's shipped generated rooms (hand
    and retired rooms keep their ids by being kept, so a generated room never
    takes one), so a room that still exists keeps its id across a
    regeneration (a changed rule drops rooms without renaming the
    survivors)."""
    return {canonical(r): r["id"] for r in _shipped_rooms(fam, rooms_dir)
            if r.get("source") != "hand" and not r.get("retired")}


def compose_recipe(recipe, fam, data, clearance, style, seed, roomy=None,
                   size_band=None, sleepers=None):
    """One recipe composed at a clearance and style under this generator's
    own rules: the grand-private area cap from the roomy sibling (``roomy``),
    then the luxury-pool, more-furniture and cells-per-piece filters. Returns
    (rooms, reason), ``reason`` naming the rule that left nothing.
    ``size_band`` pins the composition to one band (a hand recipe's own);
    ``sleepers`` overrides the family's default sleeper count (the bedroom's
    two-single pass). A recipe's "wealth" list rides the rooms out as
    "_wealth" for _finalize. The editor's "regenerate this room" calls this,
    so its candidates come from the same rules a full generation runs."""
    cap = None
    if clearance == "grand" and fam in RC.PRIVATE_FAMILIES and roomy is not None:
        cap = math.ceil(RC.GRAND_AREA_RATIO * roomy["size"][0] * roomy["size"][1])
    rooms, reason = RC.compose(recipe, data, clearance, style, seed,
                               max_area=cap, size_band=size_band,
                               sleepers=sleepers)
    if not rooms:
        return rooms, reason
    if clearance == "grand" and fam in RC.PRIVATE_FAMILIES:
        # a grand private room spends its space on furniture: it keeps a
        # luxury group and more pieces than the roomy room of the same
        # recipe and style (one that deduplicates to the roomy room is
        # caught by the shape dedup in generate)
        pool = {e.get("group") for e in (data.get("pools", {}).get(fam) or [])
                if isinstance(e, dict)}
        rooms = [r for r in rooms
                 if any(p.get("group") in pool for p in r["pieces"])]
        if not rooms:
            return rooms, "grand: no luxury group fits"
        if roomy is None:
            return [], "grand: no roomy room to better"
        rooms = [r for r in rooms if len(r["pieces"]) > len(roomy["pieces"])]
        if not rooms:
            return rooms, "grand: no more furniture than the roomy room"
        rooms = [r for r in rooms
                 if r["size"][0] * r["size"][1]
                 <= GRAND_MAX_CELLS_PER_PIECE * len(r["pieces"])]
        if not rooms:
            return rooms, ("grand: more than "
                           f"{GRAND_MAX_CELLS_PER_PIECE} cells of floor per piece")
    wealth = recipe.get("wealth")
    if wealth:
        for r in rooms:
            r["_wealth"] = list(wealth)
    if sleepers:
        # the two-sleeper pass marks its rooms: describe says "for two" of
        # them alone, never of a shipped room that happens to sleep two
        for r in rooms:
            r["_fortwo"] = True
    return rooms, None


def _guaranteed_roles(recipe, groups):
    """The roles a recipe always places: every non-optional piece of its
    anchor and required groups, and of repeatables whose count starts above
    zero. Optional groups never place at tight, so they guarantee nothing."""
    roles = set()
    for e in recipe.get("groups") or []:
        if not isinstance(e, dict) or e.get("kind") == "optional":
            continue
        count = e.get("count", 1)
        if e.get("kind") == "repeatable" and not (
                isinstance(count, int) and count >= 1
                or isinstance(count, list) and count and count[0] >= 1):
            continue
        for p in (groups.get(e.get("group")) or {}).get("pieces") or []:
            if isinstance(p, dict) and not p.get("optional"):
                roles.add(p.get("role"))
    return roles


def generate(families=FAMILIES, seed=SEED, rooms_dir=None, groups_dir=None,
             lib_dir=None):
    """The families' fixed rooms as ({family: [room, ...]}, drops), the rooms
    sorted by id and passing the fixed-room checker, the drops as
    (layout, clearance, style, reason) per family. A room whose canonical
    shape is already shipped under the same family, band, clearance and
    style keeps its shipped id; new rooms take the next free letter. Rooms
    marked "source": "hand" or "retired" are kept verbatim (their letters
    staying taken, generated duplicates of them dropped), and a surviving
    generated room keeps the fields in its "edited" list. The folder
    arguments default to the shipped library; the editor points them at its
    own. Deterministic per seed."""
    data = RG.load(groups_dir)
    lib = WL.load(lib_dir or WL.LIB_DIR)
    gdefs = data["groups"]
    out, all_drops = {}, {}
    for fam in families:
        recipes = sorted((r for r in data["recipes"].values()
                          if r.get("family") == fam),
                         key=lambda r: str(r.get("layout")))
        shipped = _shipped_rooms(fam, rooms_dir)
        # hand and retired rooms are kept exactly as they stand: never
        # regenerated, never removed, their ids' letters staying taken and
        # their shapes ahead of every generated duplicate
        keep = [r for r in shipped
                if r.get("source") == "hand" or r.get("retired")]
        edits = {r["id"]: r for r in shipped
                 if r.get("edited") and r.get("source") != "hand"
                 and not r.get("retired")}
        kept = []
        seen = {canonical(r) for r in keep}
        drops = []          # (layout, clearance, style, reason)

        def run_recipes(sleepers=None):
            """One composition pass over the family's recipes, every clearance
            and style. Pass None for the family's default sleepers; pass
            (2, 0) for the bedroom's two-single rooms (with a fresh roomy
            map, so a grand two-bed room must best its own roomy sibling,
            not the one-bed one)."""
            for recipe in recipes:
                # a wash family's recipe must be able to give the room its
                # fixtures (fixed_rooms.WASH_FAMILY_RULES); the old
                # toilet-and-basin washroom tinies now belong to the privy
                need = FR.WASH_FAMILY_RULES.get(fam, ((), ()))[0]
                missing = set(need) - _guaranteed_roles(recipe, gdefs)
                if missing:
                    names = ", ".join(sorted(missing))
                    drops.append((recipe["layout"], None, None,
                                  f"a {fam} needs a toilet, a bath and a basin "
                                  f"(see privy); this recipe gives no {names}"))
                    continue
                # a hand recipe of a family with its own band table composes
                # once per band it names, the band pinned (no padding to reach
                # it); every other recipe composes as before, its band wherever
                # the furniture lands
                hand_bands = (recipe.get("sizeBands") or []) \
                    if recipe.get("source") == "hand" and FR.family_bands(fam) \
                    else [None]
                roomy_rooms = {}   # style -> the kept roomy room (the grand sibling)
                for band in hand_bands:
                    for clearance in CLEARANCES:
                        for style in styles_for(fam):
                            rooms, reason = compose_recipe(
                                recipe, fam, data, clearance, style, seed,
                                roomy=roomy_rooms.get(style), size_band=band,
                                sleepers=sleepers)
                            if not rooms:
                                drops.append((recipe["layout"], clearance, style,
                                              reason))
                                continue
                            # the best room of the recipe that no earlier one kept:
                            # two rooms equal after any turn or mirror are one room,
                            # so a recipe whose best is taken falls to its next-best
                            best = next((r for r in rooms if canonical(r) not in seen),
                                        None)
                            if best is None:
                                drops.append((recipe["layout"], clearance, style,
                                              "every candidate duplicates an earlier "
                                              "room"))
                                continue
                            seen.add(canonical(best))
                            if clearance == "roomy":
                                roomy_rooms[style] = best
                            kept.append(best)

        run_recipes()
        # the bedroom family also composes its recipes for two singles — the
        # two-bed rooms a shared bedroom or a children's loft asks for — at
        # the bands they fit, under the same rules and the same dedupe; the
        # one-bed rooms are already in ``seen``, so they keep their ids and
        # the new rooms continue the letter sequence
        if fam == "bedroom":
            run_recipes(sleepers=(2, 0))
        shipped_ids = _shipped_ids(fam, rooms_dir)
        letters = {}        # group -> letters already on this run's ids
        # an id is <family>.<band>.<letter>.<clearance>.<style>, and the
        # family itself may hold dots (bedroom.master), so the letter sits
        # after as many family parts as the family has
        nparts = len(fam.split("."))
        # every shipped room's letter stays taken in its band, clearance and
        # style — kept, hand, retired or dropped alike — so a new room (a new
        # recipe's, or one a changed rule remade) takes the next free letter
        # and never shifts a shipped id onto a different room
        for r in shipped:
            bits = r["id"].split(".")
            if len(bits) == nparts + 4 and bits[nparts + 1] in LETTERS:
                letters.setdefault((bits[nparts], bits[nparts + 2],
                                    bits[nparts + 3]), set()).add(
                    bits[nparts + 1])
        rooms = []
        for room in kept:
            group = (room["sizeBand"], room["clearance"], room["style"])
            used = letters.setdefault(group, set())
            rid = shipped_ids.get(canonical(room))
            if rid is not None:
                # its own shipped letter is in ``used`` (seeded above); what
                # would disqualify the id is any other part drifting
                bits = rid.split(".")
                if len(bits) != nparts + 4 or bits[:nparts] != fam.split(".") \
                        or bits[nparts] != room["sizeBand"] \
                        or bits[nparts + 2] != room["clearance"] \
                        or bits[nparts + 3] != room["style"] \
                        or bits[nparts + 1] not in LETTERS:
                    rid = None
            if rid is None:
                ch = next(c for c in LETTERS if c not in used)
                rid = f"{fam}.{room['sizeBand']}.{ch}." \
                      f"{room['clearance']}.{room['style']}"
            used.add(rid.split(".")[nparts + 1])
            elite = (room["clearance"] == "grand"
                     and uses_elite_piece(room, gdefs))
            out_room = _finalize(room, rid, elite)
            old = edits.get(rid)
            if old is not None:
                # a surviving room keeps the fields a person set on it
                for f in old["edited"]:
                    if f in old:
                        out_room[f] = old[f]
                out_room["edited"] = list(old["edited"])
            rooms.append(out_room)
        rooms.extend(keep)
        rooms.sort(key=lambda r: r["id"])
        errors = FR.check(rooms, data, lib)
        if errors:
            raise SystemExit("generated rooms do not check: "
                             + "; ".join(errors))
        out[fam] = rooms
        all_drops[fam] = drops
    return out, all_drops


def _drop_reasons(drops):
    """(total, [(count, reason-without-the-room-name), ...]) for the table."""
    reasons = {}
    for _, _, _, reason in drops:
        reasons[reason] = reasons.get(reason, 0) + 1
    return sum(reasons.values()), sorted(reasons.items(), key=lambda kv: -kv[1])


def _band_ranges(rooms, fam=None):
    """Each band's size range, as 'band w0xh0-w1xh1' sorted smallest first:
    a family with its own band table in table order, else the shared bands
    by area."""
    bands = {}
    for r in rooms:
        bands.setdefault(r["sizeBand"], []).append(tuple(r["size"]))
    order = [b["name"] for b in FR.family_bands(fam)]
    out = []
    for band in sorted(bands, key=(lambda b: order.index(b) if b in order
                                   else len(order)) if order
                       else lambda b: FR.BANDS.get(b, (0, 0))[0]):
        sizes = sorted(set(bands[band]))
        lo = "x".join(str(n) for n in min(sizes))
        hi = "x".join(str(n) for n in max(sizes))
        out.append(f"{band} {lo}-{hi}")
    return out


def report(families, generated, drops_by_family):
    """The generation table: per family the recipes, rooms kept, rooms
    dropped (and why) and the size range per band."""
    data = RG.load()
    widths = (14, 8, 6, 8)
    print(f"{'family':<{widths[0]}} {'recipes':>{widths[1]}} "
          f"{'kept':>{widths[2]}} {'dropped':>{widths[3]}}  sizes")
    for fam in families:
        recipes = sum(1 for r in data["recipes"].values()
                      if r.get("family") == fam)
        total, reasons = _drop_reasons(drops_by_family[fam])
        why = "; ".join(f"{n} {reason}" for n, reason in reasons) or "-"
        ranges = ", ".join(_band_ranges(generated[fam], fam)) or "-"
        print(f"{fam:<{widths[0]}} {recipes:>{widths[1]}} "
              f"{len(generated[fam]):>{widths[2]}} {total:>{widths[3]}}  {ranges}")
        if total:
            print(f"{'':<{widths[0]}} dropped: {why}")


def main(argv):
    fams = argv or list(FAMILIES)
    for fam in fams:
        if fam not in FAMILIES:
            print(f"unknown family {fam!r}; one of {', '.join(FAMILIES)}")
            return 2
    generated, drops_by_family = generate(fams)
    os.makedirs(ROOMS_DIR, exist_ok=True)
    for fam in fams:
        path = os.path.join(ROOMS_DIR, f"{fam}.json")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"rooms": generated[fam]}, fh, indent=2,
                      ensure_ascii=False)
            fh.write("\n")
        print(f"wrote {os.path.relpath(path, GEN)} "
              f"({len(generated[fam])} rooms)")
    report(fams, generated, drops_by_family)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
