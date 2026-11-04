"""P1b, the cast: who lives and works in the world, decided before anyone is
named. Every building gets a status, every home its household, and each member
of a household becomes one slot for P5 to name. `residents` and `couples` are
written back onto the plan, so beds and sleep work as they always have."""
import re

STATUSES = ("home", "staffed", "occasional", "vacant", "abandoned")
UNPEOPLED = ("occasional", "vacant", "abandoned")     # nobody lives or works here
KINDS = ("adult", "child", "elder")
SHIFTS = ("day", "evening", "night")
MAX_CAST = 120          # about 10k tokens per ten people, so a ceiling on the bill
FAMILY_SHARE = 3        # at least one home in three holds more than adults

# what P3 and the later phases read about a building that isn't simply in use
STATUS_NOTES = {
    "occasional": "worked only now and then by a visitor: usable, a little dusty, tools put away",
    "vacant": "closed but sound, waiting for someone: clean, empty shelves, no stock, nobody's beds",
    "abandoned": "left to rot: ruined, cold hearths, broken furniture, no beds, nothing worth taking",
}

# a guide against 100-person villages. The room cap protects the GM, so these
# only need to be sensible
TOWN_WORD = re.compile(r"\b(town|quarter|block|city|district|station|deck|port|mall|strip|market)\b")
VILLAGE_WORD = re.compile(r"\b(village|estate|compound|castle|keep|fort|abbey|monastery|campus|"
                          r"hospital|ship)\b")
TOWN_PEOPLE, VILLAGE_PEOPLE, HAMLET_PEOPLE, NO_HOMES_PEOPLE = (30, 60), (20, 45), (8, 20), (0, 6)


def _text(v):
    return isinstance(v, str) and bool(v.strip())


def _whole(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_home(b):
    return isinstance(b.get("units"), dict) or (_whole(b.get("residents")) and b["residents"] > 0)


def _unit_room(b):
    """The beds of a unit building, or None for an ordinary one."""
    u = b.get("units")
    if not isinstance(u, dict):
        return None
    count, per = u.get("count"), u.get("residents")
    return (count if _whole(count) else 0) * (per if _whole(per) else 0)


def zone_people(zone):
    """The guiding range for one zone, by its kind and whether it has homes."""
    if not any(_is_home(b) for b in zone.get("buildings") or []):
        return NO_HOMES_PEOPLE
    kind = str(zone.get("kind") or "").lower()
    if TOWN_WORD.search(kind):
        return TOWN_PEOPLE
    if VILLAGE_WORD.search(kind):
        return VILLAGE_PEOPLE
    return HAMLET_PEOPLE


def budget(p1, fixed=None):
    """(lo, hi, strict): the people the cast should hold. A range the user set
    is firm at both ends; the map's own budget only stops a world running over."""
    if fixed is not None:
        return fixed[0], fixed[1], True
    ranges = [zone_people(z) for z in p1["zones"]]
    return (min(MAX_CAST, sum(r[0] for r in ranges)),
            min(MAX_CAST, sum(r[1] for r in ranges)), False)


def budget_line(lo, hi, strict):
    if strict:
        return (f"the user asked for {lo}-{hi} people in all, so land inside that, leaving "
                "buildings unstaffed when you have to.")
    return (f"about {lo}-{hi} people in all, and never more than {hi}. Fewer is fine when the "
            "place is meant to be empty.")


def _names(p1):
    return ({b["name"]: b for z in p1["zones"] for b in z["buildings"]},
            {z["name"] for z in p1["zones"]})


def _member_errors(m, ctx, buildings, zones, status):
    if not isinstance(m, dict):
        return [f"{ctx}: must be an object"]
    errors = []
    kind = m.get("kind")
    if kind not in KINDS:
        errors.append(f"{ctx}.kind: one of {list(KINDS)}, not {kind!r}")
    if kind != "adult":
        return errors
    if not _text(m.get("role")):
        errors.append(f"{ctx}.role: required for an adult")
    work = m.get("work")
    if work not in buildings and work not in zones:
        errors.append(f"{ctx}.work: must be a building or zone from the list, not {work!r}")
    elif status.get(work) in UNPEOPLED:
        errors.append(f"{ctx}.work: {work!r} is {status[work]}, so nobody works there")
    if m.get("shift", "day") not in SHIFTS:
        errors.append(f"{ctx}.shift: one of {list(SHIFTS)}, not {m.get('shift')!r}")
    if not isinstance(m.get("sells", False), bool):
        errors.append(f"{ctx}.sells: true or false")
    return errors


def _status_errors(rows, buildings):
    errors, status = [], {}
    for i, b in enumerate(rows):
        if not isinstance(b, dict) or b.get("name") not in buildings:
            errors.append(f"buildings[{i}]: not a building from the list")
        elif b.get("status") not in STATUSES:
            errors.append(f"buildings[{i}].status: one of {list(STATUSES)}, not {b.get('status')!r}")
        else:
            status[b["name"]] = b["status"]
            if b["status"] in UNPEOPLED and not _text(b.get("why")):
                errors.append(f"buildings[{i}].why: say why {b['name']!r} is {b['status']}")
    errors += [f"buildings: {n!r} has no status" for n in buildings if n not in status]
    return errors, status


def check_p1b(d, p1, lo, hi, strict):
    if not isinstance(d, dict):
        return ["P1b: the reply is not a JSON object"]
    buildings, zones = _names(p1)
    rows = d.get("buildings")
    if not isinstance(rows, list):
        return ["buildings: required, one entry per building"]
    errors, status = _status_errors(rows, buildings)
    houses = d.get("households")
    if not isinstance(houses, list):
        return errors + ["households: required, a list"]
    homes, family, working, beds = set(), set(), set(), {}
    for i, h in enumerate(houses):
        ctx = f"households[{i}]"
        if not isinstance(h, dict) or h.get("home") not in buildings:
            errors.append(f"{ctx}.home: must be a building from the list")
            continue
        home = h["home"]
        if status.get(home) in UNPEOPLED:
            errors.append(f"{ctx}.home: {home!r} is {status[home]}, so nobody lives there")
        members = h.get("members")
        if not isinstance(members, list) or not members:
            errors.append(f"{ctx}.members: required, a non-empty list")
            continue
        for j, m in enumerate(members):
            errors.extend(_member_errors(m, f"{ctx}.members[{j}]", buildings, zones, status))
        people = [m for m in members if isinstance(m, dict)]
        adults = sum(1 for m in people if m.get("kind") == "adult")
        couples = h.get("couples", 0)
        if not _whole(couples) or couples < 0 or 2 * couples > adults:
            errors.append(f"{ctx}.couples: at most half the {adults} adult(s), not {couples!r}")
        homes.add(home)
        beds[home] = beds.get(home, 0) + len(people)
        if any(m.get("kind") != "adult" for m in people):
            family.add(home)
        working.update(m.get("work") for m in people if m.get("kind") == "adult")
    for n, s in status.items():
        if s == "staffed" and n not in working:
            errors.append(f"{n!r} is staffed but no household member works there")
    for n, k in beds.items():
        room = _unit_room(buildings[n])
        if room is not None and k > room:
            errors.append(f"{n!r} beds {room} across its copies, not {k}")
    total = sum(beds.values())
    if strict and not lo <= total <= hi:
        errors.append(f"the cast holds {total} people; it must be {lo}-{hi}")
    elif total > hi:
        errors.append(f"the cast holds {total} people; the most here is {hi}")
    if homes and len(family) * FAMILY_SHARE < len(homes) and not _text(d.get("noFamilies")):
        errors.append(f"only {len(family)} of {len(homes)} homes hold children or elders; at "
                      "least a third should, or say why not in noFamilies")
    return errors[:12]


def _clean_member(m, home, buildings, zones, status, log):
    if not isinstance(m, dict):
        return None
    kind = m.get("kind") if m.get("kind") in KINDS else "adult"
    if kind != "adult":
        return {"kind": kind}
    work = m.get("work")
    if (work not in buildings and work not in zones) or status.get(work) in UNPEOPLED:
        log.append((f"household of {home}", f"work {work!r} -> {home!r}"))
        work = home
    out = {"kind": "adult", "role": m["role"] if _text(m.get("role")) else "villager", "work": work}
    if m.get("shift") in SHIFTS and m["shift"] != "day":
        out["shift"] = m["shift"]
    if isinstance(m.get("sells"), bool):
        out["sells"] = m["sells"]
    return out


def sanitize_p1b(d, p1, hi, log):
    """A usable cast from whatever came back, or None when nobody is in it and
    the run should carry on without one."""
    if not isinstance(d, dict):
        return None
    buildings, zones = _names(p1)
    status, why = {}, {}
    for b in d.get("buildings") or []:
        if isinstance(b, dict) and b.get("name") in buildings and b.get("status") in STATUSES:
            status[b["name"]] = b["status"]
            if _text(b.get("why")):
                why[b["name"]] = b["why"].strip()
    for n, b in buildings.items():
        if n not in status:
            status[n] = "home" if _is_home(b) else "staffed"
            log.append((f"building {n}", f"no status from P1b -> {status[n]}"))
    houses, total, beds = [], 0, {}
    for h in d.get("households") or []:
        if not isinstance(h, dict) or h.get("home") not in buildings:
            log.append(("households", f"dropped one with home "
                                      f"{h.get('home') if isinstance(h, dict) else h!r}"))
            continue
        home = h["home"]
        if status[home] in UNPEOPLED:
            log.append((f"household of {home}", f"dropped: the building is {status[home]}"))
            continue
        members = [c for c in (_clean_member(m, home, buildings, zones, status, log)
                               for m in h.get("members") or []) if c]
        room = _unit_room(buildings[home])
        if room is not None:
            members = members[:max(0, room - beds.get(home, 0))]
        if total + len(members) > hi:
            log.append((f"household of {home}", f"dropped: the cast is capped at {hi}"))
            continue
        if not members:
            continue
        adults = sum(1 for m in members if m["kind"] == "adult")
        couples = h.get("couples", 0)
        couples = min(couples, adults // 2) if _whole(couples) and couples > 0 else 0
        houses.append({"home": home, "couples": couples, "members": members})
        total += len(members)
        beds[home] = beds.get(home, 0) + len(members)
    if not houses:
        return None
    return {"status": status, "why": why, "households": houses}


def apply_cast(p1, cast):
    """Write the cast onto the plan: each building's status, and the residents
    and couples the rest of the pipeline reads."""
    for z in p1["zones"]:
        for b in z["buildings"]:
            name = b["name"]
            b["status"] = cast["status"][name]
            if name in cast["why"]:
                b["why"] = cast["why"][name]
            if isinstance(b.get("units"), dict):
                continue
            own = [h for h in cast["households"] if h["home"] == name]
            b.pop("residents", None)
            b.pop("couples", None)
            if own:
                b["residents"] = sum(len(h["members"]) for h in own)
                couples = sum(h["couples"] for h in own)
                if couples:
                    b["couples"] = couples


def slots_of(cast):
    """One open place per household member, numbered, for P5 to name."""
    out = []
    for house, h in enumerate(cast["households"]):
        for m in h["members"]:
            out.append(dict(m, slot=len(out) + 1, home=h["home"], house=house))
    return out


def next_batch(slots, size):
    """The next call's slots: whole households up to ``size``, so couples are
    named together. A household bigger than that goes alone, in its own batch."""
    batch = []
    for house in dict.fromkeys(s["house"] for s in slots):
        members = [s for s in slots if s["house"] == house]
        if batch and len(batch) + len(members) > size:
            break
        batch += members
    return batch


def slot_lines(batch):
    lines = []
    for s in batch:
        if s["kind"] == "adult":
            shift = f", {s['shift']} shift" if s.get("shift") else ""
            lines.append(f"- slot {s['slot']}: home {s['home']}, adult, {s['role']}, "
                         f"works at {s['work']}{shift}")
        else:
            lines.append(f"- slot {s['slot']}: home {s['home']}, {s['kind']}, at home by day")
    return "\n".join(lines)


def quota_line(batch):
    return (f"exactly these {len(batch)} people, one per slot. Each entry carries \"slot\": its "
            "number. Code fills in home and work, and an adult's role, so leave those out; a "
            "child's or elder's \"role\" says who they are (\"the fisher's daughter\").\n"
            + slot_lines(batch))


def fill_slots(d, batch):
    """Fill each person in a P5 reply from their slot, in place. Returns what
    was wrong: a slot that isn't open, or one nobody took."""
    people = d.get("npcs") if isinstance(d, dict) else None
    if not isinstance(people, list):
        return []
    open_slots = {s["slot"]: s for s in batch}
    errors, seen = [], set()
    for i, p in enumerate(people):
        if not isinstance(p, dict):
            continue
        s = open_slots.get(p.get("slot"))
        if s is None or s["slot"] in seen:
            errors.append(f"npcs[{i}].slot: {p.get('slot')!r} is not an open slot")
            continue
        seen.add(s["slot"])
        p["home"], p["kind"] = s["home"], s["kind"]
        if s["kind"] == "adult":
            p["role"], p["work"] = s["role"], s["work"]
            for key in ("shift", "sells"):
                if key in s:
                    p[key] = s[key]
        else:
            p["work"], p["sells"] = s["home"], False
            if not _text(p.get("role")):
                p["role"] = s["kind"]
    errors += [f"slot {n}: nobody took it" for n in open_slots if n not in seen]
    return errors
