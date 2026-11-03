"""Mine our own model output for room contents. Standard library only.

Reads:
- every out/*/llm/*p3*.json (the "result" field: rooms with name/purpose,
  furniture lines with template/room/count/hint, plus any unit/upper copy);
- every plan JSON under fixtures/ (the same shapes inside each building,
  including unit/upper nesting).

Prints, per room-purpose keyword (matched from each room's name and purpose
text against the purpose vocabulary below), the furniture templates that
appear and how often, and the hints used with them. Rooms that match nothing
are listed under "(other)". Ends with the bed-scatter stat: furniture lines
that place more than one bed at a time with a hint of "corner" or no hint.
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

GEN = Path(__file__).resolve().parent.parent

# canonical purpose -> substrings that identify it in a room's name/purpose
PURPOSE_MATCHERS = [
    ("bedroom", ("bed", "sleep", "chamber", "quarter", "lodging")),
    ("dormitory", ("dorm", "barrack", "bunk")),
    ("kitchen", ("kitchen", "cook", "bake", "brew")),
    ("dining", ("dining", "dinner", "meal", "eat", "feast")),
    ("common_room", ("common", "hall", "tavern", "inn", "lounge", "parlour",
                     "parlor", "recreation", "drinking")),
    ("shop", ("shop", "store", "market", "stall", "merchant", "trade")),
    ("workshop", ("workshop", "craft", "artisan", "weav", "carpent", "cooper",
                  "tann", "cobbler", "workshop", "workroom")),
    ("forge", ("forge", "smith", "anvil")),
    ("storage", ("storage", "storeroom", "pantry", "cellar", "larder",
                 "granary", "warehouse", "shed", "vault")),
    ("office", ("office", "study", "scribe", "clerk", "admin", "counting")),
    ("washroom", ("wash", "bath", "latrine", "toilet", "privy")),
    ("laundry", ("laundry",)),
    ("chapel", ("chapel", "shrine", "church", "pray", "altar", "temple")),
    ("classroom", ("class", "school", "lesson", "teach")),
    ("ward", ("ward", "sick", "infirm", "hospital", "medic", "heal",
              "apothe", "surgery")),
    ("cell", ("cell", "jail", "prison", "holding")),
    ("bridge", ("bridge", "cockpit", "helm", "command deck", "nav")),
    ("laboratory", ("lab", "alchem", "research", "experim")),
    ("library", ("library", "book", "archive", "scroll")),
    ("guardroom", ("guard", "watch", "checkpoint", "gatehouse")),
    ("gym", ("gym", "exercise", "training")),
    ("stable", ("stable", "barn", "livestock", "kennel", "byre")),
    ("mill", ("mill", "grind")),
]


def purpose_of(room):
    text = f"{room.get('name', '')} {room.get('purpose', '')}".lower()
    for purpose, matchers in PURPOSE_MATCHERS:
        if any(m in text for m in matchers):
            return purpose
    return "(other)"


def collect_buildings(node, rooms, furn):
    if isinstance(node, list):
        for item in node:
            collect_buildings(item, rooms, furn)
        return
    if not isinstance(node, dict):
        return
    if "rooms" in node and "furniture" in node:
        rooms.extend(node.get("rooms") or [])
        furn.extend(node.get("furniture") or [])
    for key in ("unit", "upper", "parts", "wings", "buildings"):
        if node.get(key):
            collect_buildings(node[key], rooms, furn)


def load_p3_replies():
    rooms, furn = [], []
    files = sorted(GEN.glob("out/*/llm/*p3*.json"))
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        result = data.get("result")
        if isinstance(result, dict):
            collect_buildings(result, rooms, furn)
    return files, rooms, furn


def load_fixtures():
    rooms, furn = [], []
    files = sorted(GEN.glob("fixtures/**/*.json"))
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(data, dict) and "buildings" in data:
            collect_buildings(data["buildings"], rooms, furn)
    return files, rooms, furn


def mine(label, rooms, furn):
    by_room = defaultdict(list)
    for line in furn:
        if isinstance(line, dict) and line.get("room"):
            by_room[line["room"]].append(line)

    grouped = defaultdict(lambda: {"rooms": 0, "names": [], "templates": Counter(),
                                   "hints": Counter()})
    for room in rooms:
        if not isinstance(room, dict):
            continue
        purpose = purpose_of(room)
        entry = grouped[purpose]
        entry["rooms"] += 1
        entry["names"].append(room.get("name", "?"))
        for line in by_room.get(room.get("name", ""), []):
            entry["templates"][line.get("template", "?")] += line.get("count", 1) or 1
            hint = line.get("hint") or "(none)"
            for atom in str(hint).split("+"):
                entry["hints"][atom.strip()] += 1

    print(f"\n=== {label}: {len(rooms)} rooms, {len(furn)} furniture lines ===")
    for purpose, entry in sorted(grouped.items(), key=lambda kv: -kv[1]["rooms"]):
        print(f"\n[{purpose}] rooms: {entry['rooms']}")
        for tpl, n in entry["templates"].most_common(12):
            print(f"    {n:>4}  {tpl}")
        top_hints = ", ".join(f"{h} ({n})" for h, n in entry["hints"].most_common(8))
        print(f"    hints: {top_hints}")


def bed_scatter(label, furn):
    bed_re = re.compile(r"bed|cot|bunk|pallet|hammock|straw", re.I)
    multi = [l for l in furn if isinstance(l, dict) and bed_re.search(str(l.get("template", "")))
             and (l.get("count") or 1) > 1]
    corner = [l for l in multi if "corner" in str(l.get("hint") or "")]
    nohint = [l for l in multi if not l.get("hint")]
    wall = [l for l in multi if "wall" in str(l.get("hint") or "")]
    print(f"\n=== {label}: bed lines with count > 1: {len(multi)} ===")
    print(f"    hint 'corner': {len(corner)}   no hint: {len(nohint)}   "
          f"any 'wall:' hint: {len(wall)}   total beds in them: "
          f"{sum(l.get('count', 1) for l in multi)}")


def main():
    p3_files, p3_rooms, p3_furn = load_p3_replies()
    fx_files, fx_rooms, fx_furn = load_fixtures()
    print(f"p3 replies: {len(p3_files)} files; fixture plans: {len(fx_files)} files")

    mine("out p3 replies", p3_rooms, p3_furn)
    mine("fixture plans", fx_rooms, fx_furn)
    bed_scatter("out p3 replies", p3_furn)
    bed_scatter("fixture plans", fx_furn)


if __name__ == "__main__":
    main()
