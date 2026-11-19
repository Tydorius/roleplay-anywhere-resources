"""Compare the room assembler with the old footprint method (--room-assembler).

Three passes, same seed each:

- every plan in ``fixtures/`` built with the switch off and on: which
  buildings qualify, whether the layouts differ, and the reachability the
  world's checks report. The raw fixtures are model plans (no room names a
  library purpose), so the expectation is: nothing qualifies, nothing moves.
- every suite in the room library as a one-storey building (the same
  skipped-P3 shape the fit test uses): the old method's footprint and room
  sizes against the assembler's, whether it assembled or fell back (and why),
  and whether every room stays reachable from the entrance.
- every suite with rooms to sleep in as a two-storey building (the sleep
  rooms upstairs, the stairs rising from the entrance room), plus the
  lodging suites with a settlement's worth of guest rooms upstairs: the old
  method's floors extension against the assembler's storey partitions —
  footprint, rooms per storey, and reachability per storey.

Printed as tables; exit code 0 when the assembled footprints are the same
size or smaller on average than the old method's.
"""
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.dirname(HERE)
sys.path.insert(0, GEN)

import worldgen
from worldgen import assembler
from worldgen import library_plan
from worldgen import layout_building
from worldgen import model
from worldgen.model import Rect
from worldgen.extensions import floors as floors_ext
from worldgen.library_rooms import object_templates

FIXTURES = os.path.join(GEN, "fixtures")
SEED = 1
BAND_ERA = {"medieval": "medieval", "industrial": "industrial",
            "modern": "modern", "scifi": "scifi"}
SLEEP_PURPOSES = ("bedroom", "master_bedroom", "guest_room", "dormitory",
                  "servants_room", "nursery", "crew_quarters", "barracks")
LODGING_IDS = ("inn.coaching", "hotel.railway", "boardinghouse.lodging",
               "flophouse.dormitory", "capsulehotel.scifi")
LODGING_BEDS = 5          # a medium settlement's worth of upstairs rooms


def fingerprint(world):
    """What the layout produced: regions, templates, objects, entrances."""
    regions = sorted((r.name, r.parent, r.rect.x, r.rect.y, r.rect.w, r.rect.h)
                     for r in world.regions)
    objects = sorted((o.region, o.pos, o.template) for o in world.objects)
    templates = sorted(world.templates)
    entrances = sorted((b.layout.design.name, b.layout.entrance_door)
                       for b in world.buildings)
    return (regions, objects, templates, entrances)


def uses_in(plan_data):
    """Rooms that name a library purpose (``use``), per plan."""
    n = 0
    for b in plan_data.get("buildings", []):
        n += sum(1 for r in b.get("rooms", []) if r.get("use"))
    return n


def compare_fixtures(out):
    print("== fixtures (raw plans; switch off vs on, seed %d) ==" % SEED)
    buildings = 0
    assembled = 0
    moved = []
    for name in sorted(os.listdir(FIXTURES)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(FIXTURES, name)
        data = json.load(open(path, encoding="utf-8"))
        if "zones" not in data:
            continue
        off = worldgen.run(data, seed=SEED)
        on = worldgen.run(data, seed=SEED, room_assembler=True)
        same = fingerprint(off) == fingerprint(on)
        buildings += len(on.buildings)
        assembled += sum(1 for b in on.buildings
                         if getattr(b.layout, "assembled", False))
        if not same:
            moved.append(name)
        print(f"{name}: {len(on.buildings)} building(s), {uses_in(data)} room(s) "
              f"with a library purpose; reach off {off.metrics['reachability']:.2f} "
              f"on {on.metrics['reachability']:.2f}; layouts "
              f"{'identical' if same else 'DIFFER'}")
    print(f"fixtures totals: {buildings} building(s), {assembled} assembled, "
          f"{len(moved)} plan(s) whose layout moved")
    return moved


def suite_rows():
    """(band, sid, b, design dict, parsed building, template registry)."""
    lib = library_plan.load()
    for sid, s in sorted(lib.suites.items()):
        band = s["bands"][0]
        lo, hi = s["residents"]
        couples = 1 if any(r["purpose"] == "master_bedroom" for r in s["rooms"]) else 0
        b = {"name": sid, "kind": s["kinds"][0], "sizeClass": s["sizeClasses"][0],
             "residents": max(lo, min(hi, 2 + couples)), "couples": couples,
             "wealth": "modest", "condition": "kept"}
        d = library_plan.trim_rooms(
            lib, library_plan.design_from_suite(s, b, band, random.Random(SEED)), b)
        d["furniture"] = []
        d["wealth"] = b["wealth"]
        d["condition"] = b["condition"]
        reg = library_plan.registry_for(lib, "compare", taken=set())
        library_plan.expand_fitting(lib, reg, d, b, band, None, "compare", [])
        bd = model._parse_building(dict(b), {b["name"]: d})
        yield band, sid, b, d, bd, reg


def reach(layout):
    """Rooms reachable from the entrance through the door pairs, over total."""
    rooms = layout.rooms

    def owner(cell):
        for i, r in enumerate(rooms):
            if r.rect.contains_cell(cell):
                return i
        return None

    edges = {i: set() for i in range(len(rooms))}
    for a, b in layout.door_pairs:
        ia, ib = owner(a), owner(b)
        if ia is not None and ib is not None:
            edges[ia].add(ib)
            edges[ib].add(ia)
    start = next((i for i, r in enumerate(rooms)
                  if r.base_name == layout.entrance_room.base_name), None)
    if start is None:
        return 0, len(rooms)
    seen, queue = {start}, [start]
    while queue:
        for n in edges[queue.pop(0)]:
            if n not in seen:
                seen.add(n)
                queue.append(n)
    return len(seen), len(rooms)


def room_sizes(layout):
    return " ".join("{} {}x{}".format(r.base_name, r.rect.w, r.rect.h)
                    for r in layout.rooms)


def old_layout(bd, reg):
    templates = object_templates(reg)
    w, h = layout_building.building_footprint(bd, templates)
    layout = layout_building.layout_building(bd, (0, 0), random.Random(SEED),
                                             templates)
    return w, h, layout


def compare_suites(out):
    print("== suites (every library suite as a one-storey building; "
          f"wealth modest, seed {SEED}) ==")
    rows = list(suite_rows())
    old = {}
    for band, sid, b, d, bd, reg in rows:
        w, h, layout = old_layout(bd, reg)
        old[sid] = (w, h, layout)
    reasons = {}
    asm_fp = {}
    asm_rooms = {}
    for band in sorted(BAND_ERA):
        plan_data = {"name": "compare",
                     "setting": {"era": BAND_ERA[band], "technology": "iron",
                                 "density": "normal", "climate": "mild"},
                     "zones": [{"name": "Z", "kind": "village",
                                "sizeClass": "medium", "adjacentTo": [],
                                "outdoor": [], "buildings": [],
                                "dressing": {"paths": "dirt", "props": [],
                                             "filler": []}}],
                     "roads": [], "templates": [], "buildings": [],
                     "npcs": [], "player": {"name": "The Comparer"}}
        plan = model.parse_plan(plan_data)
        ctx = assembler.activate(plan, plan_data, "compare", {})
        try:
            for b_band, sid, b, d, bd, reg in rows:
                if b_band != band:
                    continue
                fp = assembler.footprint(bd)
                if fp is None:
                    reasons[sid] = ctx.fallbacks.get(sid, "does not qualify")
                else:
                    asm_fp[sid] = fp
                    asm_rooms[sid] = assembler.build(bd, (0, 0))
        finally:
            assembler.deactivate()
    asm_areas, old_areas_asm = [], []
    ok_avg = True
    for band, sid, b, d, bd, reg in rows:
        w, h, layout = old[sid]
        r_old, t_old = reach(layout)
        head = f"{band} {sid}"
        print(f"{head}: old {w}x{h}={w * h} rooms {room_sizes(layout)} "
              f"reach {r_old}/{t_old}")
        if sid in asm_fp:
            aw, ah = asm_fp[sid]
            a_layout = asm_rooms[sid]
            r_new, t_new = reach(a_layout)
            print(f"{' ' * len(head)}  asm {aw}x{ah}={aw * ah} "
                  f"rooms {room_sizes(a_layout)} "
                  f"reach {r_new}/{t_new} assembled")
            asm_areas.append(aw * ah)
            old_areas_asm.append(w * h)
        else:
            print(f"{' ' * len(head)}  asm fell back: {reasons[sid]}")
    n = len(rows)
    if asm_areas:
        mean_old = sum(old_areas_asm) / len(old_areas_asm)
        mean_asm = sum(asm_areas) / len(asm_areas)
        ok_avg = mean_asm <= mean_old
        print(f"suite totals: {n} suite(s), {len(asm_areas)} assembled, "
              f"{n - len(asm_areas)} fell back")
        print(f"footprint area (assembled suites): old avg {mean_old:.0f} cells, "
              f"assembler avg {mean_asm:.0f} cells "
              f"({(mean_asm - mean_old) / mean_old * 100:+.0f}% on average)")
        why = {}
        for reason in reasons.values():
            key = reason.split(":")[0]
            why[key] = why.get(key, 0) + 1
        for key, count in sorted(why.items(), key=lambda kv: -kv[1]):
            print(f"  fell back: {key} ({count})")
    else:
        print(f"suite totals: {n} suite(s), 0 assembled")
    return ok_avg


def suite_rows_2storey():
    """(band, sid, b, design dict, parsed building, template registry) —
    every suite with a room to sleep in (besides the entrance room) as a
    two-storey building: the sleep rooms move upstairs, the rest stay down,
    and the stairs rise from the entrance room. The lodging suites get a
    second row whose upper storey carries a settlement's worth of guest
    rooms."""
    lib = library_plan.load()
    for sid, s in sorted(lib.suites.items()):
        band = s["bands"][0]
        lo, hi = s["residents"]
        couples = 1 if any(r["purpose"] == "master_bedroom" for r in s["rooms"]) else 0
        entry = (s.get("entrance") or {}).get("room") or s["rooms"][0]["name"]
        sleep = [r for r in s["rooms"] if r["purpose"] in SLEEP_PURPOSES
                 and r["name"] != entry]
        if not sleep:
            continue
        for label, upstairs in [(sid, sleep)] + (
                [(f"{sid}+lodging", _lodging_upper(sleep))]
                if sid in LODGING_IDS else []):
            ground = [r for r in s["rooms"] if r not in sleep]
            suite = dict(s, rooms=ground)
            b = {"name": label, "kind": s["kinds"][0],
                 "sizeClass": s["sizeClasses"][0],
                 "residents": max(lo, min(hi, 2 + couples)), "couples": couples,
                 "wealth": "modest", "condition": "kept", "storeys": 2}
            d = library_plan.trim_rooms(
                lib, library_plan.design_from_suite(suite, b, band,
                                                    random.Random(SEED)), b)
            # the parsed design carries the upper storeys and the stairs room
            # (model._parse_building reads both off the design, not the
            # building entry)
            d["stairs"] = {"room": entry}
            d["upper"] = [{"storey": 2,
                           "rooms": [{"name": r["name"], "share": r["share"],
                                      "use": r["purpose"],
                                      "purpose": r["purpose"].replace("_", " ")}
                                     for r in upstairs],
                           "connections": []}]
            d["furniture"] = []
            d["wealth"] = b["wealth"]
            d["condition"] = b["condition"]
            reg = library_plan.registry_for(lib, "compare", taken=set())
            library_plan.expand_fitting(lib, reg, d, b, band, None, "compare", [])
            bd = model._parse_building(dict(b), {b["name"]: d})
            yield band, label, b, d, bd, reg


def _lodging_upper(sleep):
    """The lodging row's upstairs: the suite's own sleep rooms padded with
    small guest rooms to a medium settlement's worth."""
    rooms = list(sleep)
    n = len(rooms)
    k = 1
    while n < LODGING_BEDS:
        name = f"Guest Room {k}"
        if not any(r["name"] == name for r in rooms):
            rooms.append({"name": name, "share": "small",
                          "purpose": "guest_room"})
            n += 1
        k += 1
    return rooms


def _storey_lines(layout, label):
    """"ground N rooms reach r/t, upper N rooms reach r/t" for a layout whose
    upper storeys ride along, plus the upper layouts themselves."""
    r, t = reach(layout)
    lines = [f"ground {len(layout.rooms)} rooms reach {r}/{t}"]
    ups = []
    for i in range(len(getattr(layout.design, "upper") or [])):
        up = None
        if getattr(layout, "assembled", False):
            up = assembler.upper_layout(layout, i,
                                        Rect(0, 0, layout.rect.w, layout.rect.h))
        if up is None:
            up = layout_building.layout_rooms(
                floors_ext._upper_design(layout.design,
                                         layout.design.upper[i], label),
                Rect(0, 0, layout.rect.w, layout.rect.h),
                random.Random(SEED), None,
                furniture=layout.design.upper[i].furniture)
        r2, t2 = reach(up)
        lines.append(f"upper {len(up.rooms)} rooms reach {r2}/{t2}")
        ups.append(up)
    return ", ".join(lines), ups


def compare_suites_2storey(out):
    print("== suites as two-storey buildings (sleep rooms upstairs, stairs "
          f"from the entrance room; wealth modest, seed {SEED}) ==")
    rows = list(suite_rows_2storey())
    old = {}
    for band, sid, b, d, bd, reg in rows:
        templates = object_templates(reg)
        w, h = layout_building.building_footprint(bd, templates)
        layout = layout_building.layout_building(bd, (0, 0), random.Random(SEED),
                                                 templates)
        old[sid] = (w, h, layout)
    reasons = {}
    asm_fp = {}
    asm_rooms = {}
    for band in sorted(BAND_ERA):
        plan_data = {"name": "compare",
                     "setting": {"era": BAND_ERA[band], "technology": "iron",
                                 "density": "normal", "climate": "mild"},
                     "zones": [{"name": "Z", "kind": "village",
                                "sizeClass": "medium", "adjacentTo": [],
                                "outdoor": [], "buildings": [],
                                "dressing": {"paths": "dirt", "props": [],
                                             "filler": []}}],
                     "roads": [], "templates": [], "buildings": [],
                     "npcs": [], "player": {"name": "The Comparer"}}
        plan = model.parse_plan(plan_data)
        ctx = assembler.activate(plan, plan_data, "compare", {})
        try:
            for b_band, sid, b, d, bd, reg in rows:
                if b_band != band:
                    continue
                fp = assembler.footprint(bd)
                if fp is None:
                    reasons[sid] = ctx.fallbacks.get(sid, "does not qualify")
                else:
                    asm_fp[sid] = fp
                    asm_rooms[sid] = assembler.build(bd, (0, 0))
        finally:
            assembler.deactivate()
    asm_areas, old_areas_asm = [], []
    for band, sid, b, d, bd, reg in rows:
        w, h, layout = old[sid]
        old_line, _ups = _storey_lines(layout, sid)
        head = f"{band} {sid}"
        print(f"{head}: old {w}x{h}={w * h} {old_line}")
        if sid in asm_fp:
            aw, ah = asm_fp[sid]
            a_layout = asm_rooms[sid]
            asm_line, _a_ups = _storey_lines(a_layout, sid)
            print(f"{' ' * len(head)}  asm {aw}x{ah}={aw * ah} {asm_line} "
                  f"assembled")
            asm_areas.append(aw * ah)
            old_areas_asm.append(w * h)
        else:
            print(f"{' ' * len(head)}  asm fell back: {reasons[sid]}")
    n = len(rows)
    built = len(asm_areas)
    print(f"two-storey totals: {n} building(s), {built} assembled, "
          f"{n - built} fell back")
    if asm_areas:
        mean_old = sum(old_areas_asm) / len(old_areas_asm)
        mean_asm = sum(asm_areas) / len(asm_areas)
        print(f"footprint area (assembled): old avg {mean_old:.0f} cells, "
              f"assembler avg {mean_asm:.0f} cells "
              f"({(mean_asm - mean_old) / mean_old * 100:+.0f}% on average)")
        why = {}
        for reason in reasons.values():
            key = reason.split(":")[0]
            why[key] = why.get(key, 0) + 1
        for key, count in sorted(why.items(), key=lambda kv: -kv[1]):
            print(f"  fell back: {key} ({count})")


def main():
    moved = compare_fixtures(sys.stdout)
    ok_avg = compare_suites(sys.stdout)
    compare_suites_2storey(sys.stdout)
    if moved or not ok_avg:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
