"""Validate the library-seed drafts. Standard library only.

Checks that objects.draft.json parses, that ids are unique, that every field
uses the allowed values from ROOM_LIBRARY_DESIGN.md, and that every entry's
sources exist in sources.json. Prints the category x band coverage table and
the per-source citation counts. Exits 1 on any error.

When purposes.draft.json is present (change 3), also checks that every
category it names exists in objects.draft.json.
"""

import json
import sys
from collections import Counter
from pathlib import Path

SEED = Path(__file__).resolve().parent

BANDS = ["medieval", "industrial", "modern", "scifi"]
WEALTH = ["poor", "modest", "wealthy", "elite"]
MATERIALS = ["wood", "metal", "stone", "fabric", "leather", "glass",
             "ceramic", "synthetic", "plant"]
PURPOSES = ["bedroom", "kitchen", "dining", "common_room", "shop", "workshop",
            "storage", "office", "washroom", "dormitory", "forge", "chapel",
            "classroom", "ward", "cell", "bridge", "laboratory", "library",
            "laundry", "guardroom", "gym", "greenhouse"]

REQUIRED = ["id", "category", "size", "walkability", "forSleep", "light",
            "back", "wealth", "bands", "names", "parts", "purposes", "sources"]


def load(name):
    with open(SEED / name, encoding="utf-8") as fh:
        return json.load(fh)


def check_objects(objs, source_ids):
    errors = []
    dupes = [i for i, c in Counter(o.get("id") for o in objs).items() if c > 1]
    for d in dupes:
        errors.append(f"duplicate id: {d}")
    for o in objs:
        oid = o.get("id", "<no id>")
        for key in REQUIRED:
            if key not in o:
                errors.append(f"{oid}: missing field '{key}'")
        size = o.get("size")
        if not (isinstance(size, list) and len(size) == 2
                and all(isinstance(v, int) and v >= 1 for v in size)):
            errors.append(f"{oid}: bad size {size!r}")
        bad_bands = [b for b in o.get("bands", []) if b not in BANDS + ["*"]]
        if bad_bands:
            errors.append(f"{oid}: bad bands {bad_bands}")
        if o.get("back") not in ("north", None):
            errors.append(f"{oid}: back must be 'north' or null")
        bad_wealth = [w for w in o.get("wealth", []) if w not in WEALTH]
        if bad_wealth:
            errors.append(f"{oid}: bad wealth {bad_wealth}")
        walk = o.get("walkability")
        if not (isinstance(walk, (int, float)) and 0 <= walk <= 1):
            errors.append(f"{oid}: bad walkability {walk!r}")
        light = o.get("light")
        if not (isinstance(light, (int, float)) and light >= 0):
            errors.append(f"{oid}: bad light {light!r}")
        if not isinstance(o.get("forSleep"), bool):
            errors.append(f"{oid}: forSleep must be true or false")
        names = o.get("names")
        if not (isinstance(names, dict) and names.get("*")
                and all(isinstance(k, str) and v for k, v in names.items())):
            errors.append(f"{oid}: names must be a non-empty map with a '*' entry")
        bad_name_keys = [k for k in names if k != "*" and k not in BANDS]
        if bad_name_keys:
            errors.append(f"{oid}: bad names keys {bad_name_keys}")
        parts = o.get("parts", {})
        if not isinstance(parts, dict):
            errors.append(f"{oid}: parts must be a map")
        bad_parts = [v for v in parts.values() if v not in MATERIALS]
        if bad_parts:
            errors.append(f"{oid}: bad part materials {bad_parts}")
        bad_purposes = [p for p in o.get("purposes", []) if p not in PURPOSES]
        if bad_purposes:
            errors.append(f"{oid}: unknown purposes {bad_purposes}")
        bad_sources = [s for s in o.get("sources", []) if s not in source_ids]
        if bad_sources:
            errors.append(f"{oid}: unknown sources {bad_sources}")
        if "aliases" in o and not all(isinstance(a, str) for a in o["aliases"]):
            errors.append(f"{oid}: aliases must be strings")
        if "note" in o and not isinstance(o["note"], str):
            errors.append(f"{oid}: note must be a string")
        if "sizeGuessed" in o and not isinstance(o["sizeGuessed"], bool):
            errors.append(f"{oid}: sizeGuessed must be true or false")
    return errors


def coverage(objs):
    cats = sorted({o["category"] for o in objs})
    rows = []
    for cat in cats:
        members = [o for o in objs if o["category"] == cat]
        row = [cat, str(len(members))]
        for band in BANDS:
            n = sum(1 for o in members
                    if "*" in o["bands"] or band in o["bands"])
            row.append(str(n))
        rows.append(row)
    return rows


def main():
    errors = []
    sources = load("sources.json")
    source_ids = {s["id"] for s in sources}
    objs = load("objects.draft.json")
    errors += check_objects(objs, source_ids)

    print(f"objects: {len(objs)} entries, "
          f"{len({o['category'] for o in objs})} categories")

    table = coverage(objs)
    widths = [max(len(r[i]) for r in table + [["category", "count"] + BANDS])
              for i in range(6)]
    header = ["category", "count"] + BANDS
    print("  ".join(h.ljust(w) for h, w in zip(header, widths)))
    for row in table:
        print("  ".join(v.ljust(w) for v, w in zip(row, widths)))

    print("\nsource citations:")
    counts = Counter(s for o in objs for s in o["sources"])
    for s in sources:
        print(f"  {s['id']}: {counts.get(s['id'], 0)}")

    purposes_file = SEED / "purposes.draft.json"
    if purposes_file.exists():
        purposes = load("purposes.draft.json")
        known = {o["category"] for o in objs}
        used = set()
        for purpose, body in purposes.items():
            for kind in ("core", "extra"):
                for cat in body.get(kind, []):
                    used.add(cat)
        missing = sorted(used - known)
        if missing:
            errors.append(f"purposes name unknown categories: {missing}")
        else:
            print(f"\npurposes: {len(purposes)} purposes, "
                  f"{len(used)} categories referenced, all present")

    if errors:
        print("\nFAIL:")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    print("\nPASS")


if __name__ == "__main__":
    main()
