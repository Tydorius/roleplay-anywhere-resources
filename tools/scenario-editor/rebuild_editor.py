"""Redesign one building of a generated world in plain language: one model
call edits that building's design in the saved plan (the user's instruction
rides in the prompt), a relayout rebuilds the world from the edited plan with
no further calls, and the result is staged with a compact preview. The
workspace itself is only replaced when the stage is applied; a discarded
stage never touched it.

The rebuild runs as a job in its own slot (separate from the chat turn and
the world-generation slots, so none blocks another). The model call goes
through the generator's client (worldgen/llm.py) with the generator's own
P3 prompt — rebuilt from plan.json with the same setting, zone, building,
catalogue, pool, units and compound lines the original run sent — plus one
instruction line. The reply is checked with the generator's own check_p3 and
cleaned by sanitize_p3, both bound to that building exactly as the original
run derived them from the plan.

Two zone kinds ride the same pipeline. redress_zone sends the zone's own P4
lines (setting, zone, its buildings, catalogue) and writes the checked
dressing back into that zone's ``dressing``. populate_zone sends the P5 zone
batch's lines (story, zone, its buildings with free-bed notes computed from
the plan's designs, the roster of the plan's people, a quota from the plan's
beds) and appends the checked people to the plan's npcs — the people a plan
already names are never removed or renamed.

apply_staged() swaps the workspace over: the old scenario.json and media
backed up under the gallery's backups, the new build's scenario and media
written in, images carried onto the new ids BY NAME (a rebuild re-ids
everything; names are the stable key), and the edited plan.json copied over
the workspace's. The provider's api key never appears in a job, a stage or
a log.
"""
import json
import random
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

import worldgen_editor as wg          # puts the gallery and generator on sys.path
import image_gallery as ig            # noqa: E402  (the backups root)
from worldgen import api as wgapi     # noqa: E402
from worldgen import cast as wgcast   # noqa: E402  (the shifts a person may name)
from worldgen import llm as wgllm     # noqa: E402
from worldgen import native as wgnative   # noqa: E402
from worldgen import phases as wgphases   # noqa: E402
from worldgen.extensions import expand as expand_extensions  # noqa: E402
from worldgen.model import bed_capacity, is_sleep_name, is_spare_room  # noqa: E402

KINDS = ("building", "redress_zone", "populate_zone")
MAX_INSTRUCTION = 1000
# what every generator phase call sends as the system prompt
SYSTEM = ("You generate scenario data for a map RPG. "
          "You reply with one JSON object and nothing else.")
# each kind's one instruction line, appended to the phase prompt
INSTRUCTION_LINES = {
    "building": "The user wants this building redesigned as follows — obey it: {}",
    "redress_zone": "The user wants this zone's outdoor dressing redone as "
                    "follows — obey it: {}",
    "populate_zone": "The user wants people added to this zone as follows — "
                     "obey it: add to the people made so far, never remove or "
                     "rename them: {}",
}


class JobBusyError(RuntimeError):
    pass


class _Cancelled(Exception):
    """A rebuild whose cancel was requested; ends the job as cancelled."""


# ---------------------------------------------------------------- the plan
def _read_plan(plan_path):
    try:
        plan = json.loads(Path(plan_path).read_text("utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"cannot read the saved plan: {e}")
    if not isinstance(plan, dict) or not isinstance(plan.get("buildings"), list):
        raise ValueError("the saved plan carries no buildings list")
    return plan


def _find_building(plan, name):
    """(zone, plan entry) of one building, by exact name."""
    for z in plan.get("zones") or []:
        for b in z.get("buildings") or []:
            if isinstance(b, dict) and b.get("name") == name:
                return z, b
    names = [str(b.get("name")) for z in plan.get("zones") or []
             for b in z.get("buildings") or [] if isinstance(b, dict)]
    raise ValueError(f"no building named {name!r} in the plan "
                     f"(buildings: {', '.join(names) or 'none'})")


def _find_zone(plan, name):
    """One zone of the plan, by exact name."""
    for z in plan.get("zones") or []:
        if isinstance(z, dict) and z.get("name") == name:
            return z
    names = [str(z.get("name")) for z in plan.get("zones") or []
             if isinstance(z, dict)]
    raise ValueError(f"no zone named {name!r} in the plan "
                     f"(zones: {', '.join(names) or 'none'})")


def _p3_context(plan, zone, b):
    """The P3 inputs for one building, all derived from the saved plan: the
    same setting, zone, building, catalogue, pool, units and compound lines
    the original run sent, and the template/pool/storey/unit facts its checks
    were bound to."""
    exts = expand_extensions(plan.get("extensions") or ())
    templates = [t for t in plan.get("templates") or [] if isinstance(t, dict)]
    pools = plan.get("lootPools") or {}
    return {
        "exts": exts,
        "setting_line": wgphases._setting_line(plan, plan.get("frame")),
        "zone_line": wgphases._zone_line(zone),
        "building_line": wgphases._building_line(b),
        "catalogue_lines": wgphases._catalogue_lines(templates),
        "pool_lines": wgphases._pool_lines(pools),
        "compound_line": wgphases._compound_line(plan.get("compounds") or [], zone, b),
        "units_line": wgphases._units_line(b),
        "templates": {t["name"] for t in templates},
        "pools": set(pools),
        "beds": {t["name"]: bed_capacity(tuple(t["size"])) for t in templates
                 if t.get("forSleep") or is_sleep_name(t["name"], t.get("tags"))},
        # the floors extension gates upper storeys, as in the original run
        "storeys": b.get("storeys", 1) if "floors" in exts else None,
        "units": b.get("units"),
    }


def _p3_prompt(ctx, building_name, instruction):
    """The generator's own assembled p3-building prompt plus the one
    instruction line that carries what the user asked for."""
    return wgphases.assemble_prompt(
        "p3-building", ctx["exts"],
        setting_line=ctx["setting_line"], zone_line=ctx["zone_line"],
        building_line=ctx["building_line"], catalogue_lines=ctx["catalogue_lines"],
        compound_line=ctx["compound_line"], units_line=ctx["units_line"],
        pool_lines=ctx["pool_lines"], building_name=building_name,
        _append=INSTRUCTION_LINES["building"].format(instruction))


# ---------------------------------------------------------------- P4, P5
def _p4_context(plan, zone):
    """The P4 inputs for one zone, all derived from the saved plan: the same
    setting, zone, building and catalogue lines the original run's P4 call
    sent (phases.py ~3306-3323), and the template/building name sets its
    checks were bound to."""
    templates = [t for t in plan.get("templates") or [] if isinstance(t, dict)]
    return {
        "exts": expand_extensions(plan.get("extensions") or ()),
        "setting_line": wgphases._setting_line(plan, plan.get("frame")),
        "zone_line": wgphases._zone_line(zone),
        # P4's building lines: one per building of THIS zone, "- none" for a
        # wild one, as the original run joined them
        "building_lines": "\n".join(f"- {wgphases._building_line(b)}"
                                    for b in zone.get("buildings") or []
                                    if isinstance(b, dict)) or "- none",
        "catalogue_lines": wgphases._catalogue_lines(templates),
        "templates": {t["name"] for t in templates},
        # every building name of the plan: a prop's behind:/front:/beside:
        # hint may name any of them
        "buildings": {b.get("name") for z in plan.get("zones") or []
                      for b in z.get("buildings") or [] if isinstance(b, dict)},
    }


def _p4_prompt(ctx, instruction):
    """The generator's own assembled p4-zone prompt plus the one instruction
    line that carries what the user asked for."""
    return wgphases.assemble_prompt(
        "p4-zone", ctx["exts"],
        setting_line=ctx["setting_line"], zone_line=ctx["zone_line"],
        building_lines=ctx["building_lines"], catalogue_lines=ctx["catalogue_lines"],
        _append=INSTRUCTION_LINES["redress_zone"].format(instruction))


def _p5_context(plan, zone):
    """The P5 inputs for one zone's people batch, all derived from the saved
    plan: the same story, zone, zone-names, building-lines-with-bed-notes,
    roster and quota lines the original run's zone batch sent (phases.py
    ~3325-3451), and the bed accounting its notes and checks were bound to
    (~3330-3362) — recomputed from the plan's own designs, with the zone's
    existing people as the taken beds."""
    templates = [t for t in plan.get("templates") or [] if isinstance(t, dict)]
    bed_templates = {t["name"]: bed_capacity(tuple(t["size"])) for t in templates
                     if t.get("forSleep") or is_sleep_name(t["name"], t.get("tags"))}
    design_by_name = {d.get("name"): d for d in plan.get("buildings") or []
                      if isinstance(d, dict)}
    # a sameAs compound part sleeps what the part it copies beds
    same_as = {p.get("building"): p.get("sameAs")
               for c in plan.get("compounds") or [] if isinstance(c, dict)
               for p in (c.get("parts") or [])
               if isinstance(p, dict) and p.get("sameAs") and p.get("building")}

    def design_of(b):
        return design_by_name.get(b.get("name")) \
            or design_by_name.get(same_as.get(b.get("name"), ""))

    def beds_of(b):
        """A building's sleeper capacity, as the original run computed it: a
        unit building stamps one single bed per resident per copy; a plain
        one holds what its design beds."""
        if isinstance(b.get("units"), dict) and wgphases._check_int(b["units"].get("count")):
            per = b["units"].get("residents", 0)
            return b["units"]["count"] * (per if wgphases._check_int(per) else 0)
        src = design_of(b)
        return wgphases.design_beds(src, bed_templates) if src else 0

    def home_beds_of(b):
        """How many of a building's beds are homes: all but the spare ones
        (an inn's guest rooms), though the residents the plan promised it
        always count."""
        total = beds_of(b)
        src = design_of(b)
        if isinstance(b.get("units"), dict):
            rooms = [r for r in ((src or {}).get("unit") or {}).get("rooms") or []
                     if isinstance(r, dict)]
            spare = total if is_spare_room(str(b["units"].get("name", ""))) or (
                rooms and all(is_spare_room(str(r.get("name", "")), str(r.get("purpose", "")))
                              for r in rooms)) else 0
        else:
            spare = wgphases.design_spare_beds(src, bed_templates) if src else 0
        promised = b["residents"] if wgphases._check_int(b.get("residents")) else 0
        return min(total, max(total - spare, promised))

    buildings = [b for z in plan.get("zones") or []
                 for b in z.get("buildings") or [] if isinstance(b, dict)]
    beds = {b.get("name"): beds_of(b) for b in buildings}
    home_beds = {b.get("name"): home_beds_of(b) for b in buildings}
    homes_taken = {}
    roster = [p for p in plan.get("npcs") or [] if isinstance(p, dict)]
    for p in roster:
        homes_taken[p.get("home")] = homes_taken.get(p.get("home"), 0) + 1

    def bed_note(name):
        """The building lines' bed note, as the original run wrote it."""
        got, homes = beds.get(name, 0), home_beds.get(name, 0)
        if not got:
            return ", no beds"
        free = max(0, homes - homes_taken.get(name, 0))
        note = f", sleeps {homes} ({free} spots free)" if homes else ", no home beds"
        if got > homes:
            note += f", plus {got - homes} spare bed(s) for guests or patients, nobody's home"
        return note

    # the couples each home still owes, after the pairs the plan's own people
    # already form (the original run's couples_left)
    owed = {b.get("name"): b["couples"] for b in buildings
            if wgphases._check_int(b.get("couples")) and b["couples"] > 0}
    for p in roster:
        if p.get("partner") and p.get("home") in owed:
            owed[p["home"]] -= 0.5
    couples_left = {h: int(n) for h, n in owed.items() if n >= 1}

    zbuildings = [b for b in zone.get("buildings") or [] if isinstance(b, dict)]
    zbeds = sum(beds.get(b.get("name"), 0) for b in zbuildings)
    zliving = sum(homes_taken.get(b.get("name"), 0) for b in zbuildings)
    zfree = sum(max(0, home_beds.get(b.get("name"), 0)
                    - homes_taken.get(b.get("name"), 0)) for b in zbuildings)
    names = {p.get("name") for p in roster if isinstance(p.get("name"), str)}
    player = plan.get("player")
    if isinstance(player, dict) and isinstance(player.get("name"), str):
        names.add(player["name"])       # names are unique across the whole plan
    return {
        "exts": expand_extensions(plan.get("extensions") or ()),
        "story_line": wgphases._setting_line(plan, plan.get("frame"))
                      + wgphases._notes_block((plan.get("frame") or {}).get("notes")),
        "zone_line": wgphases._zone_line(zone),
        "zone_names_line": ", ".join(str(z.get("name"))
                                     for z in plan.get("zones") or []
                                     if isinstance(z, dict)),
        # the zone's buildings with their bed notes; the other zones' homes
        # stay off — a populate call homes its people in the zone itself
        "building_lines": "\n".join(
            f"- {wgphases._building_line(b)}{bed_note(b.get('name'))}"
            for b in zbuildings) or "- none",
        "roster_block": "\n".join(
            ["PEOPLE MADE SO FAR (they exist; never repeat a name or take a "
             "taken bed):"]
            + [f"- {p.get('name')}, {p.get('role', '?')}, sleeps at {p.get('home', '?')}"
               for p in roster]) if roster else "",
        "quota_line": (f"exactly the people the user's instruction below asks "
                       f"for: this zone's buildings hold {zbeds} bed(s) "
                       f"({zfree} home bed(s) free), {zliving} people live "
                       f"here now; the new people are in addition to them, "
                       f"never replacements"),
        "buildings": {b.get("name") for b in buildings},
        "zones": {z.get("name") for z in plan.get("zones") or []
                  if isinstance(z, dict)},
        "zone_buildings": {b.get("name") for b in zbuildings},
        "bedded": sorted(n for n, k in beds.items() if k > 0),
        "bedded_zone": [b.get("name") for b in zbuildings
                        if beds.get(b.get("name"), 0) > 0],
        "names": names,
        "couples": couples_left,
        # as in the original run, the free-spot map only binds a plan that
        # promised residents (its beds are the population); re-homing stays
        # inside the zone
        "bed_bound": any(wgphases._check_int(b.get("residents")) for b in buildings),
        "free": {b.get("name"): max(0, home_beds.get(b.get("name"), 0)
                                    - homes_taken.get(b.get("name"), 0))
                 for b in zbuildings if home_beds.get(b.get("name"), 0) > 0},
    }


def _p5_prompt(ctx, instruction):
    """The generator's own assembled p5-people prompt — the zone batch's
    lines — plus the one instruction line that carries what the user asked
    for."""
    return wgphases.assemble_prompt(
        "p5-people", ctx["exts"],
        setting_line=ctx["story_line"], zone_line=ctx["zone_line"],
        zone_names_line=ctx["zone_names_line"], building_lines=ctx["building_lines"],
        roster_block=ctx["roster_block"], quota_line=ctx["quota_line"],
        _append=INSTRUCTION_LINES["populate_zone"].format(instruction))


# ---------------------------------------------------------------- the preview
def preview(old_scenario, new_scenario, metrics=None, extra=None):
    """A compact JSON-able diff of the workspace's scenario and the rebuilt
    one: region, npc and object-template names added and removed (a rename
    shows as both), npcs/objects/doors before and after, and the new build's
    headline metrics when they are given. ``extra`` merges the kind-specific
    facts into the preview: redress shows the old and new dressing prop
    counts per template, populate the npc names added (removals are always
    empty)."""
    def names(items, key="name"):
        return {i.get(key) for i in items or [] if isinstance(i, dict)}

    def npc_names(scn):
        return names([e for e in scn.get("entities") or []
                      if isinstance(e, dict) and e.get("type") == "npc"])

    def doors(scn):
        return sum(wgnative.door_counts(scn).values())

    def count(scn, type_):
        return sum(1 for e in scn.get("entities") or []
                   if isinstance(e, dict) and e.get("type") == type_)

    out = {
        "regions": _diff(names(old_scenario.get("regions")),
                         names(new_scenario.get("regions"))),
        "npcNames": _diff(npc_names(old_scenario), npc_names(new_scenario)),
        "objectTemplateNames": _diff(names(old_scenario.get("objectTemplates")),
                                     names(new_scenario.get("objectTemplates"))),
        "counts": {"npcs": [count(old_scenario, "npc"), count(new_scenario, "npc")],
                   "objects": [count(old_scenario, "object"),
                               count(new_scenario, "object")],
                   "doors": [doors(old_scenario), doors(new_scenario)]},
    }
    if extra:
        out.update(extra)
    if metrics is not None:
        out["metrics"] = {"reachability": metrics.get("reachability"),
                          "dropped": len((metrics.get("errors") or {})
                                         .get("dropped") or [])}
    return out


def _diff(old, new):
    return {"added": sorted(n for n in new - old if n),
            "removed": sorted(n for n in old - new if n)}


def _built_dir(out_dir):
    """The relayout's built scenario folder, or None when it built none."""
    for d in sorted(Path(out_dir).glob("*.scenario")):
        if (d / "scenario.json").is_file():
            return d
    return None


def _prop_counts(dressing):
    """One dressing's props as template -> total count, from which the
    preview's old/new pair is made."""
    out = {}
    for p in (dressing or {}).get("props") or []:
        if isinstance(p, dict) and isinstance(p.get("template"), str):
            out[p["template"]] = out.get(p["template"], 0) + (p.get("count", 1) or 0)
    return out


# ---------------------------------------------------------------- the kinds
def _building_spec(plan, target, instruction):
    """The building kind: one P3-shaped call redesigns one building, and the
    sanitized design replaces that building's entry in the plan copy."""
    zone, b = _find_building(plan, target)
    if not any(isinstance(d, dict) and d.get("name") == target
               for d in plan["buildings"]):
        raise ValueError(f"the plan carries no interior design for {target!r} "
                         "(a copied or fallback building); rebuild one of the rest")
    ctx = _p3_context(plan, zone, b)

    def validate(x):
        # the original run's own binding: this building's yard, storeys,
        # units, pools, beds, residents and couples from the plan
        return wgphases.check_p3(
            x, target, ctx["templates"], bool(b.get("yard")),
            storeys=ctx["storeys"], units=ctx["units"], pools=ctx["pools"],
            beds=ctx["beds"], residents=b.get("residents"), couples=b.get("couples"))

    def absorb(edited, d, dropped):
        design = wgphases.sanitize_p3(d, target, ctx["templates"], dropped,
                                      storeys=ctx["storeys"],
                                      units=ctx["units"] or False,
                                      pools=ctx["pools"],
                                      ruined=wgphases.ruined_building(b))
        for i, old in enumerate(edited["buildings"]):
            if isinstance(old, dict) and old.get("name") == target:
                edited["buildings"][i] = design
                break

    return {"phase": "P3", "label": f"redesigning {target}",
            "done": f"rebuilt {target}",
            "call": f"rebuild-p3-{wgphases.slug(target)}",
            "user": _p3_prompt(ctx, target, instruction),
            "validate": validate, "absorb": absorb, "stage": "building"}


def _redress_spec(plan, target, instruction):
    """The redress_zone kind: one P4-shaped call redoes one zone's outdoor
    dressing, written back into that zone of the plan copy."""
    zone = _find_zone(plan, target)
    ctx = _p4_context(plan, zone)

    def validate(x):
        # the original run's own binding: the catalogue's template names and
        # every building name (a hint's behind:/front:/beside: names one)
        return wgphases.check_p4(x, target, ctx["templates"], ctx["buildings"])

    def absorb(edited, d, dropped):
        design = wgphases.sanitize_p4(d, ctx["templates"], dropped, target,
                                      ctx["buildings"])
        for z in edited.get("zones") or []:
            if isinstance(z, dict) and z.get("name") == target:
                z["dressing"] = design
                break
        old, new = _prop_counts(zone.get("dressing")), _prop_counts(design)
        return {"dressingProps": {t: [old.get(t, 0), new.get(t, 0)]
                                  for t in sorted(set(old) | set(new))}}

    return {"phase": "P4", "label": f"redressing {target}",
            "done": f"redressed {target}",
            "call": f"rebuild-p4-{wgphases.slug(target)}",
            "user": _p4_prompt(ctx, instruction),
            "validate": validate, "absorb": absorb, "stage": "zone"}


def _populate_spec(plan, target, instruction):
    """The populate_zone kind: one P5-shaped call adds people to one zone.
    The people the plan already names are never touched — the new ones are
    checked against every name in the plan and appended after them."""
    zone = _find_zone(plan, target)
    if not zone.get("buildings"):
        raise ValueError(f"the zone {target!r} has no buildings; a populate "
                         "call homes its people in the zone's own buildings")
    ctx = _p5_context(plan, zone)
    if not ctx["bedded_zone"]:
        raise ValueError(f"no building of {target!r} has a bed; a populate "
                         "call homes its people in the zone's own buildings")

    def validate(x):
        # the original zone batch's own binding (phases.py ~3533): every
        # building and zone of the plan, its bedded buildings, the whole
        # plan's names and the couples its homes still owe...
        errors = wgphases.check_p5(x, ctx["buildings"], ctx["zones"],
                                   set(ctx["bedded"]), need=("npcs",),
                                   roster=ctx["names"], couples=ctx["couples"])
        # ...plus this call's own rules: the new people live in THIS zone,
        # and a shift, when one is named, is a real shift
        people = x.get("npcs") if isinstance(x, dict) else None
        if isinstance(people, list):
            for i, p in enumerate(people):
                if not isinstance(p, dict):
                    continue
                if p.get("home") not in ctx["zone_buildings"]:
                    errors.append(f"npcs[{i}].home: must be a building of "
                                  f"{target}, not {p.get('home')!r}")
                if p.get("shift") is not None and p.get("shift") not in wgcast.SHIFTS:
                    errors.append(f"npcs[{i}].shift: one of "
                                  f"{list(wgcast.SHIFTS)}, not {p.get('shift')!r}")
        return errors

    def absorb(edited, d, dropped):
        made = wgphases.sanitize_p5(d, sorted(ctx["buildings"]),
                                    sorted(ctx["zones"]), dropped,
                                    ctx["bedded_zone"], need=("npcs",),
                                    taken=ctx["names"], couples=ctx["couples"],
                                    free=dict(ctx["free"]) if ctx["bed_bound"] else None)
        if not made.get("npcs"):
            detail = "; ".join(f"{where}: {reason}" for where, reason in dropped) \
                or "the reply named nobody"
            raise RuntimeError(f"every person the model made was dropped: {detail}")
        edited.setdefault("npcs", []).extend(made["npcs"])
        return {"npcs": {"added": [p["name"] for p in made["npcs"]], "removed": []}}

    return {"phase": "P5", "label": f"peopling {target}",
            "done": f"peopled {target}",
            "call": f"rebuild-p5-{wgphases.slug(target)}",
            "user": _p5_prompt(ctx, instruction),
            "validate": validate, "absorb": absorb, "stage": "zone"}


SPECS = {"building": _building_spec, "redress_zone": _redress_spec,
         "populate_zone": _populate_spec}


# ---------------------------------------------------------------- jobs
_job = None          # the one rebuild job; None when nothing has run yet
_staged = None       # the un-applied result of the last finished rebuild
_lock = threading.Lock()
_PUBLIC = ("id", "kind", "state", "phase", "label", "source", "target", "provider",
           "model", "calls", "tokens", "seconds", "seed", "preview", "outDir",
           "started", "finished", "error")


def job():
    with _lock:
        return {k: _job.get(k) for k in _PUBLIC} if _job else None


def staged():
    with _lock:
        return dict(_staged) if _staged else None


def discard():
    """Clear the stage; the workspace was never touched by it. The staged
    build's out dir is left where it is."""
    global _staged
    with _lock:
        if _staged is None:
            raise ValueError("nothing is staged")
        _staged = None
    return {"ok": True}


def cancel():
    with _lock:
        if _job is None or _job["state"] != "running":
            raise ValueError("no rebuild is running")
        _job["cancelRequested"] = True
        return {k: _job.get(k) for k in _PUBLIC}


def _start(fields, target):
    """Start ``target(update, job_dict)`` in the rebuild's own job thread (the
    chat turn and world generation keep slots of their own)."""
    global _job, _staged
    with _lock:
        if _job is not None and _job["state"] == "running":
            raise JobBusyError("a rebuild is already running")
        _staged = None       # an un-applied stage never survives a new rebuild
        j = {"id": f"rebuild-{int(time.time() * 1000)}", "kind": "rebuild",
             "state": "running", "phase": "starting", "label": "", "source": None,
             "target": None, "provider": None, "model": None, "calls": 0,
             "tokens": 0, "seconds": 0.0, "seed": None, "preview": None,
             "outDir": None,
             "started": datetime.now().strftime("%H:%M:%S"), "finished": None,
             "error": None, "cancelRequested": False}
        j.update(fields)
        _job = j
    threading.Thread(target=_run, args=(j, target), daemon=True).start()
    return job()


def _run(j, target):
    def update(**kw):
        with _lock:
            j.update(kw)

    try:
        target(update, j)
        update(state="done")
    except (wgapi.Cancelled, _Cancelled) as e:
        update(state="cancelled", error=str(e) or "cancelled")
    except Exception as e:
        update(state="failed", error=f"{type(e).__name__}: {e}")
    finally:
        update(finished=datetime.now().strftime("%H:%M:%S"))


def _call(client, phase, system, user, validate, j):
    """One client.call beside a cancel watch (a model reply can take minutes
    and cannot be cut short), like the chat turn's helper. Returns the parsed
    design."""
    out = {}

    def run():
        try:
            out["parsed"] = client.call(phase, system, user, validate=validate)
        except BaseException as e:     # re-raised on the job thread below
            out["error"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    while t.is_alive():
        if j["cancelRequested"]:
            raise _Cancelled("the rebuild was cancelled")
        t.join(0.1)
    if j["cancelRequested"]:
        raise _Cancelled("the rebuild was cancelled")
    if "error" in out:
        raise out["error"]
    return out.get("parsed")


def _fresh_out_dir(ws_name):
    """A fresh out dir under the generator's out/ root."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root = wg.OUT_ROOT / f"rebuild-{ws_name}-{stamp}"
    d, i = root, 2
    while d.exists():
        d, i = root.with_name(root.name + f"-{i}"), i + 1
    return d


def start(source, provider, kind, target, instruction, seed=None):
    """Start one rebuild of ``kind`` on ``target`` per ``instruction`` using
    ``provider``: building redesigns one building (a building name, case-exact
    in the workspace's plan), redress_zone redoes one zone's outdoor dressing
    and populate_zone adds people to one zone (both take a zone name). Then
    relayout the edited plan (a fresh seed unless one is given) and stage the
    result. Everything is validated up front, so a bad request never starts
    the job."""
    kind = str(kind or "")
    if kind not in KINDS:
        raise ValueError(f"unknown rebuild kind {kind!r}; this pipeline does {list(KINDS)}")
    ws = wg._workspace_dir(source)
    if not ws:
        raise ValueError("unknown workspace: a rebuild works on an editable work/ "
                         "workspace (copy the scenario to a workspace first)")
    plan_path = ws / "plan.json"
    if not plan_path.is_file():
        raise ValueError("this workspace has no saved plan (only generated worlds have one)")
    target = str(target or "")
    instruction = str(instruction or "").strip()
    if not 1 <= len(instruction) <= MAX_INSTRUCTION:
        raise ValueError(f"the instruction must be 1-{MAX_INSTRUCTION} characters")
    if seed is not None:
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            raise ValueError("the seed must be a whole number")
    plan = _read_plan(plan_path)
    spec = SPECS[kind](plan, target, instruction)
    entry = wg._checked_provider(provider)
    out_dir = _fresh_out_dir(ws.name)
    try:
        client = wgllm.Client(entry["name"], log_dir=str(out_dir / "llm"))
    except wgllm.LLMError as e:
        raise ValueError(str(e))
    sid = str(source or "")

    def target_fn(update, j):
        global _staged
        update(outDir=str(out_dir), target=target,
               label=spec["label"], phase=spec["phase"])
        out_dir.mkdir(parents=True, exist_ok=True)
        d = _call(client, spec["call"], SYSTEM, spec["user"], spec["validate"], j)
        update(model=client.model, calls=client.calls,
               tokens=client.tokens["total"], seconds=round(client.seconds, 1))
        if d is None:
            raise RuntimeError(client.last_error or "the model produced no design JSON")
        dropped = []
        edited = json.loads(json.dumps(plan))    # the workspace's plan is never touched
        extra = spec["absorb"](edited, d, dropped)
        edited_path = out_dir / "plan.json"
        wgphases.write_plan(edited, str(edited_path))
        use_seed = seed if seed is not None else random.randrange(1, 2 ** 31)
        update(seed=use_seed, phase="layout",
               label=f"re-placing the world with seed {use_seed}")
        wgapi.relayout(str(edited_path), seed=use_seed, out_dir=str(out_dir),
                       progress=lambda e: update(phase=e.get("phase"),
                                                 label=e.get("label")),
                       cancel=lambda: j["cancelRequested"])
        built = _built_dir(out_dir)
        if built is None:
            raise RuntimeError(f"the relayout built no scenario; its output is in {out_dir}")
        old_scn = json.loads((ws / "scenario.json").read_text("utf-8"))
        new_scn = json.loads((built / "scenario.json").read_text("utf-8"))
        try:
            metrics = json.loads((out_dir / "metrics.json").read_text("utf-8"))
        except (OSError, ValueError):
            metrics = None
        pv = preview(old_scn, new_scn, metrics, extra)
        with _lock:
            _staged = {"source": sid, "workspace": str(ws), "out_dir": str(out_dir),
                       "plan_path": str(edited_path), "built_dir": str(built),
                       "preview": pv, "seed": use_seed, spec["stage"]: target}
        update(preview=pv, label=spec["done"])

    return _start({"provider": entry["name"], "source": sid, "target": target},
                  target_fn)


# ---------------------------------------------------------------- applying
def apply_staged():
    """Replace the workspace with the staged rebuild: back up its scenario and
    media, write the new build in, carry images onto the new ids by name, copy
    the edited plan over, clear the stage. Returns
    ``{applied, carried, backup}``."""
    global _staged
    with _lock:
        st = dict(_staged) if _staged else None
    if st is None:
        raise ValueError("nothing is staged to apply")
    ws = Path(st["workspace"])
    if not (ws / "scenario.json").is_file():
        raise ValueError(f"the workspace is gone: {ws}")
    built = Path(st["built_dir"])
    if not (built / "scenario.json").is_file():
        raise ValueError(f"the staged build is gone: {built}")
    if not Path(st["plan_path"]).is_file():
        raise ValueError(f"the staged plan is gone: {st['plan_path']}")
    old_scn = json.loads((ws / "scenario.json").read_text("utf-8"))
    new_scn = json.loads((built / "scenario.json").read_text("utf-8"))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = ig.BACKUPS / st["source"].replace("/", "_") / f"{stamp}-rebuild"
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ws / "scenario.json", backup / "scenario.json")
    if (ws / "media").is_dir():
        shutil.copytree(ws / "media", backup / "media")
    (ws / "scenario.json").write_bytes((built / "scenario.json").read_bytes())
    if (ws / "media").exists():
        shutil.rmtree(ws / "media")
    if (built / "media").is_dir():
        shutil.copytree(built / "media", ws / "media")
    carried = _carry_images(old_scn, new_scn, backup / "media", ws / "media")
    shutil.copyfile(st["plan_path"], ws / "plan.json")
    with _lock:
        _staged = None
    return {"applied": True, "carried": carried, "backup": str(backup)}


def _carry_images(old_scenario, new_scenario, old_media, new_media):
    """Copy the backup's images onto the new ids, matched by name and kind
    (entities' portraits, object templates' sprites, item templates' items):
    a rebuild re-ids everything, names are the stable key. Returns how many
    files landed."""
    old_ids = _named_ids(old_scenario)
    carried = 0
    for kind, name, new_id in _wanted_ids(new_scenario):
        old_id = old_ids.get((kind, name))
        if not old_id or not isinstance(new_id, str):
            continue
        folder = Path(old_media) / old_id
        if not folder.is_dir():
            continue
        for f in sorted(folder.iterdir()):
            m = re.fullmatch(re.escape(old_id) + r"-(sprite|item|portrait|perk)\."
                             r"(webp|png)", f.name)
            if not m or m.group(1) != kind:
                continue
            dst = Path(new_media) / new_id
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dst / f"{new_id}-{kind}.{m.group(2)}")
            carried += 1
    return carried


def _named_ids(scn):
    """(kind, name) -> id for everything the scenario draws an image of."""
    out = {}
    for e in scn.get("entities") or []:
        if (isinstance(e, dict) and e.get("type") in ("npc", "player")
                and isinstance(e.get("name"), str)):
            out.setdefault(("portrait", e["name"]), e.get("id"))
    for key, kind in (("objectTemplates", "sprite"), ("itemTemplates", "item")):
        for t in scn.get(key) or []:
            if isinstance(t, dict) and isinstance(t.get("name"), str):
                out.setdefault((kind, t["name"]), t.get("id"))
    return out


def _wanted_ids(scn):
    """[(kind, name, id)] of the new scenario's image subjects."""
    out = []
    for e in scn.get("entities") or []:
        if (isinstance(e, dict) and e.get("type") in ("npc", "player")
                and isinstance(e.get("name"), str)):
            out.append(("portrait", e["name"], e.get("id")))
    for key, kind in (("objectTemplates", "sprite"), ("itemTemplates", "item")):
        for t in scn.get(key) or []:
            if isinstance(t, dict) and isinstance(t.get("name"), str):
                out.append((kind, t["name"], t.get("id")))
    return out
