"""Library interface for the generator: what the Scenario Editor drives.

Three calls cover the editor's needs:

- ``generate(idea, provider, ...)`` runs the model phases P1-P5 and builds
  the scenario, writing settings.json (the choices, see settings.py),
  plan.json, spec.json/spec.py, metrics.json, the llm/ call logs, the
  scenario zip and (with Pillow) preview.png;
- ``relayout(plan_path, ...)`` lays a saved plan out again with no model
  calls — the "Re-roll layout" button;
- ``estimate(idea_or_plan)`` reports the calls, tokens and minutes a
  generation is expected to take, from the measured runs.

``progress`` receives a dict before every model call and at each later
stage: ``{"phase": "P3", "label": "building 3/10: Wok Nine", "calls": 5,
"tokens": 1234}``. ``cancel`` is a callable checked between model calls and
before layout; a true return raises :class:`Cancelled`. Both functions
return the summary dict that the CLI prints as its last JSON line.
"""
import json
import os
import re
import subprocess
import sys
import time

import worldgen
from . import phases
from .phases import Cancelled  # noqa: F401 - callers catch worldgen.api.Cancelled

VENDOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")

# measured full runs (brief 010): 13-18 calls, 100-150k tokens, 20-35 minutes;
# brief 013's batched P5 (one call per zone plus the player) and the three P6
# systems calls widen it
MEASURED_CALLS = (25, 35)
MEASURED_TOKENS = (200000, 320000)
MEASURED_MINUTES = (30, 55)
TOKENS_PER_CALL = 8500       # prompt + completion, across the phases
TOKENS_PER_MINUTE = 4500     # streaming reasoning models on a good day


def _check_extensions(extensions):
    """Unknown extension ids fail fast with the valid list."""
    from .extensions import IDS
    unknown = sorted(set(extensions or ()) - set(IDS))
    if unknown:
        raise ValueError(f"unknown extension(s) {unknown}; valid: {list(IDS)}")
    return tuple(extensions or ())


def generate(idea, provider=None, extensions=(), seed=1, out_dir="out/world",
             progress=None, cancel=None, providers_path=None, client=None,
             emit=None, frame=None, questionnaire=None, cast=True, library=True):
    """Run the model phases on ``idea`` and build the scenario in ``out_dir``.

    ``provider`` names an entry in providers.json; tests may pass a
    pre-built ``client`` instead (it is used as-is). ``frame`` is an approved
    World Frame from :func:`frame` (every phase gets it in place of the bare
    idea); a ``questionnaire`` ``{"mode", "answers", "population"}`` without
    a frame runs P0 first. Both are kept on plan.json, so a re-roll never
    asks again. Raises llm.LLMError for an unusable provider,
    phases.PhaseError when P0/P1/P2 cannot be salvaged, and Cancelled when
    ``cancel()`` turns true. Returns the summary dict."""
    extensions = _check_extensions(extensions)
    if client is None:
        from . import llm
        kwargs = {"providers_path": providers_path} if providers_path else {}
        client = llm.Client(provider, log_dir=os.path.join(out_dir, "llm"), **kwargs)
    _write_settings(out_dir, idea, seed, extensions, library, frame, questionnaire,
                    getattr(client, "model", None), emit)
    t0 = time.time()
    plan, stats = phases.run_phases(idea, client, extensions=extensions, library=library,
                                    progress=progress, cancel=cancel,
                                    frame=frame, questionnaire=questionnaire, cast=cast)
    if extensions:
        plan["extensions"] = sorted(set(plan.get("extensions", [])) | set(extensions))
    phases.write_plan(plan, os.path.join(out_dir, "plan.json"))
    minutes = round((time.time() - t0) / 60.0, 1)
    _phase_report(client, stats, minutes, emit)
    return _layout_and_build(plan, seed=seed, out_dir=out_dir,
                             extra_exts=extensions,
                             gen=(client, stats, minutes, idea),
                             progress=progress, cancel=cancel, emit=emit)


def _write_settings(out_dir, idea, seed, extensions, library, frame, questionnaire, model,
                    emit=None):
    """settings.json in the run folder, before the first model call, so even a
    run that fails leaves the choices behind for someone to look at. Never
    fails the run."""
    from . import settings
    try:
        os.makedirs(out_dir, exist_ok=True)
        data = settings.from_run(idea, seed, extensions, library, frame=frame,
                                 questionnaire=questionnaire,
                                 model=model if isinstance(model, str) else None)
        settings.write(os.path.join(out_dir, settings.FILE_NAME), data)
    except (OSError, ValueError) as e:
        if emit:
            emit(f"WARN  settings.json not written: {e}")


def frame(mode, idea="", answers=None, population=None, clarify=None,
          provider=None, providers_path=None, client=None, log_dir=None,
          progress=None, cancel=None, notes=""):
    """P0, the World Frame, as its own step (brief 013 change 2). Long mode
    without ``clarify`` runs the clarifying turn and returns
    ``{"questions": [...], "frame": None}``; call again with the answers as
    ``clarify`` (``[{"question", "answer"}]``, or ``[]`` to skip the turn)
    to get ``{"questions": [], "frame": {...}}``. Every other mode frames in
    one call. ``notes`` is the form's "Other instructions or requests" text,
    kept verbatim on the frame. Returns the dict with the frame's phase stats
    under ``"stats"``."""
    if client is None:
        from . import llm
        kwargs = {"providers_path": providers_path} if providers_path else {}
        if log_dir:
            kwargs["log_dir"] = log_dir
        client = llm.Client(provider, **kwargs)
    frm, questions_out, stats = phases.run_frame(
        client, mode, answers=answers, idea=idea, population=population,
        clarify=clarify, progress=progress, cancel=cancel, notes=notes)
    return {"frame": frm, "questions": questions_out, "stats": stats}


def relayout(plan_path, seed=1, extensions=(), out_dir=None, progress=None,
             cancel=None, emit=None):
    """Lay out a saved plan (plan.json) again and rebuild the scenario. No
    model calls happen: a different seed re-places the same world. Returns
    the summary dict; raises Cancelled when ``cancel()`` turns true."""
    extensions = _check_extensions(extensions)
    if out_dir is None:
        out_dir = os.path.join("out",
                               os.path.splitext(os.path.basename(plan_path))[0])
    with open(plan_path, "r", encoding="utf-8") as f:
        plan_data = json.load(f)
    return _layout_and_build(plan_data, seed=seed, out_dir=out_dir,
                             extra_exts=tuple(extensions or ()),
                             progress=progress, cancel=cancel, emit=emit)


def estimate(idea_or_plan):
    """Expected calls, tokens and minutes for one generation. ``idea_or_plan``
    is an idea string, a plan dict, or a path to a plan.json. A plan pins the
    call count exactly (P1, P1b when it has a cast, P2's two, P5, one per building,
    one per zone, plus retries); an idea gets the midpoints of the measured
    runs."""
    plan = None
    if isinstance(idea_or_plan, dict):
        plan = idea_or_plan
    elif isinstance(idea_or_plan, str) and os.path.exists(idea_or_plan):
        with open(idea_or_plan, "r", encoding="utf-8") as f:
            plan = json.load(f)
    if plan is None:
        return {"calls": _mid(MEASURED_CALLS), "calls_range": list(MEASURED_CALLS),
                "tokens": _mid(MEASURED_TOKENS), "tokens_range": list(MEASURED_TOKENS),
                "minutes": _mid(MEASURED_MINUTES), "minutes_range": list(MEASURED_MINUTES),
                "basis": "measured full runs (an idea gives no plan to count)"}
    zones = plan.get("zones") or []
    buildings = sum(len(z.get("buildings") or []) for z in zones)
    # a sameAs compound part copies another part's P3 design: no call for it
    same_as = sum(1 for c in (plan.get("compounds") or []) if isinstance(c, dict)
                  for p in (c.get("parts") or [])
                  if isinstance(p, dict) and p.get("sameAs"))
    p3_calls = max(0, buildings - same_as)
    # P5 batches: one call per zone with buildings, plus the player's own call
    p5_calls = sum(1 for z in zones if z.get("buildings")) + 1
    # with a cast it's one call per ten people in the zone instead
    households = (plan.get("cast") or {}).get("households") or []
    p1b_calls = 1 if households else 0
    if households:
        zone_of = {b.get("name"): z.get("name") for z in zones
                   for b in z.get("buildings") or []}
        people = {}
        for h in households:
            zone = zone_of.get(h.get("home"))
            people[zone] = people.get(zone, 0) + len(h.get("members") or [])
        p5_calls = sum(-(-n // phases.P5_BATCH) for n in people.values()) + 1
    p0_calls = 1 if (plan.get("frame") or plan.get("questionnaire")) else 0
    # P1 and P2's two, then the three P6 calls at the end
    calls = p0_calls + p1b_calls + 3 + p3_calls + len(zones) + p5_calls + 3
    retries = 6                          # the most a measured run needed
    tokens = TOKENS_PER_CALL * calls
    return {"calls": calls, "calls_range": [calls, calls + retries],
            "tokens": tokens, "tokens_range": [tokens, TOKENS_PER_CALL * (calls + retries)],
            "minutes": round(tokens / float(TOKENS_PER_MINUTE), 1),
            "minutes_range": [round(tokens / float(TOKENS_PER_MINUTE), 1),
                              round(TOKENS_PER_CALL * (calls + retries) / float(TOKENS_PER_MINUTE), 1)],
            "basis": f"plan {plan.get('name', '')!r}: "
                     + (f"{p0_calls} P0 call + " if p0_calls else "")
                     + ("P1, P1b, P2 x2" if p1b_calls else "P1, P2 x2")
                     + f" + {p3_calls} buildings ({same_as} sameAs copies "
                       f"skipped) + {len(zones)} zones + {p5_calls} people calls "
                       f"+ 3 systems calls (+ retries)"}


def _mid(pair):
    return (pair[0] + pair[1]) // 2


def _populations_summary(spec):
    """The native populations by region: which template spawns how many of
    what in which region, plus the totals and how many members start in
    place."""
    from worldgen import populations
    pops = spec.get("nativePopulations") or []
    return {
        "templates": len(pops),
        "creatures": populations.creature_count(pops),
        "placed": populations.placed_count(pops),
        "regions": [{"template": p.get("name"), "region": h.get("region"),
                     "count": h.get("count")}
                    for p in pops for h in p.get("homes") or []],
    }


# ------------------------------------------------------------------ build

def _layout_and_build(plan_data, seed, out_dir, extra_exts=(), gen=None,
                      progress=None, cancel=None, emit=None):
    """Layout, checks, spec, then the vendored builder, validator and
    renderer. ``gen`` carries the generate-run context (client, stats,
    minutes, idea) for the summary; relayout passes None."""
    from .extensions import expand
    exts = expand(set(plan_data.get("extensions", [])) | set(extra_exts or ()))
    _progress(progress, "layout", "placing roads, zones, buildings and people", gen)
    if cancel is not None and cancel():
        raise Cancelled("cancelled before layout")
    t0 = time.time()
    world = worldgen.run(plan_data, seed=seed, extensions=exts)
    spec = worldgen.build_spec(world, plan_data)
    os.makedirs(out_dir, exist_ok=True)
    from worldgen import spec_writer as sw
    sw.write_spec(out_dir, spec)
    from worldgen import checks as checks_mod
    checks_mod.write_metrics(os.path.join(out_dir, "metrics.json"), world.metrics)
    _summary_text(world, spec, seed, emit)

    _progress(progress, "build", "building and validating the scenario", gen)
    builder = os.path.join(VENDOR_DIR, "build_scenario.py")
    validator = os.path.join(VENDOR_DIR, "validate_scenario.py")
    renderer = os.path.join(VENDOR_DIR, "render_map.py")
    folder_name = spec["folderName"] + ".scenario"
    zip_name = folder_name + ".zip"
    built = os.path.join(out_dir, folder_name)
    zip_path = os.path.join(out_dir, zip_name)

    rc_build, _ = _run([sys.executable, builder, os.path.join(out_dir, "spec.py"),
                        "--out", out_dir], emit)
    mods_issues = []
    doors = {}
    if rc_build == 0 and os.path.isdir(built):
        # every world ships finished, extensions or not: the door kinds and
        # door objects (and the native floor data when there are storeys)
        from worldgen import mods as mods_mod
        mods_mod.finish_scenario(built, spec)
        _emit(emit, f"native doors, floor data and mods written into {built} "
                    "(re-zipped)")
        mods_issues = checks_mod.check_scenario_mods(
            os.path.join(built, "scenario.json"), spec)
        for issue in mods_issues:
            _emit(emit, "ERROR " + issue)
        from worldgen import native
        with open(os.path.join(built, "scenario.json"), "r", encoding="utf-8") as f:
            doors = native.door_counts(json.load(f))
    if rc_build == 0 and os.path.isdir(built):
        from worldgen import library_art
        n_art = library_art.attach_sprites(built, plan_data)
        if n_art:
            _emit(emit, f"{n_art} shipped library sprite(s) attached to {built} (re-zipped)")
    rc_val, val_out = 0, ""
    if rc_build == 0 and os.path.exists(zip_path):
        rc_val, val_out = _run([sys.executable, validator, zip_path], emit)
    if rc_build == 0 and os.path.isdir(built):
        _run([sys.executable, renderer, built, os.path.join(out_dir, "preview.png"),
              "--cell", "8"], emit)

    dropped = world.metrics.get("errors", {}).get("dropped", [])
    failed = rc_build != 0 or rc_val != 0 or bool(mods_issues) or bool(dropped)
    if failed:
        _emit(emit, "FAILED: see tool output above")
    summary = _summary_dict(world, spec, plan_data, seed, zip_path, out_dir,
                            failed, rc_val, val_out, gen,
                            round((time.time() - t0) / 60.0, 1))
    summary["doors"] = doors          # the shipped door objects, by kind
    summary["extensions"] = sorted(exts)
    _progress(progress, "done",
              f"{'FAILED:' if failed else 'built'} {spec['name']}", gen)
    return summary


def _summary_dict(world, spec, plan_data, seed, zip_path, out_dir, failed,
                  rc_val, val_out, gen, layout_minutes):
    """The JSON summary line: everything a collection script or the editor
    wants to know about one finished build."""
    m = re.search(r"(\d+) error\(s\),\s*(\d+) warning\(s\)", val_out or "")
    n_err = int(m.group(1)) if m else (1 if rc_val else 0)
    n_warn = int(m.group(2)) if m else 0
    rooms = world.metrics.get("rooms", {})
    ents = world.metrics.get("entrances", {})
    unplaced = world.metrics.get("objects", {}).get("unplaced", [])
    if gen is not None:
        client, stats, minutes, idea = gen
        calls, retries, tokens = client.calls, client.retries, client.tokens["total"]
        dropped_model = len(stats["dropped"])
    else:
        client = None
        calls, retries, tokens, dropped_model, minutes, idea = 0, 0, 0, 0, layout_minutes, None
    nat = spec.get("nativeNature") or {}
    water = world.metrics.get("water") or {}
    depths = {}
    draws = {}
    for reg in water.get("regions") or []:
        depths[reg.get("depth")] = depths.get(reg.get("depth"), 0) + 1
        draws[reg.get("draw")] = draws.get(reg.get("draw"), 0) + 1
    return {
        "ok": not failed and n_err == 0,
        "provider": client.provider if client else None,
        "model": client.model if client else None, "idea": idea,
        "out": os.path.abspath(out_dir),
        "zip": os.path.basename(zip_path) if os.path.exists(zip_path) else None,
        "seed": seed, "grid": f"{world.grid[0]}x{world.grid[1]}",
        "calls": calls, "retries": retries,
        "minutes": minutes, "tokens": tokens,
        "zones": len(world.zones_by_name), "buildings": len(world.buildings),
        "templates": len(plan_data.get("templates", [])),
        "npcs": len(world.characters) - 1,
        "objects_placed": sum(len(t.get("placements", [])) for t in spec["objectTemplates"]),
        "unplaced": len(unplaced), "fallbacks": len(world.fallbacks),
        "dropped": dropped_model,
        "validator_errors": n_err, "validator_warnings": n_warn,
        "rooms_reachable": f"{rooms.get('reachable')}/{rooms.get('total')}",
        "entrances_from_road": f"{ents.get('reachable_from_road')}/{ents.get('total')}",
        "reachability": world.metrics.get("reachability"),
        "map_warnings": world.metrics.get("map_warnings", []),
        "locks": {
            "rooms": [{"room": e.get("room"), "keys": e.get("holders")}
                      for e in ((spec.get("nativeLocks") or {}).get("locks") or [])],
            "theft_buildings": len((spec.get("nativeLocks") or {}).get("theft") or []),
        },
        "secret_doors": len(spec.get("nativeSecrets") or []),
        "nature": {
            "natural_regions": len(nat.get("shape") or []),
            "water_regions": len(nat.get("water") or []),
            "water_deep": depths.get("deep", 0),
            "water_shallow": depths.get("shallow", 0),
            "water_rivers": draws.get("river", 0),
            "water_pools": draws.get("pool", 0),
            "water_surfaces_dropped": len(water.get("dropped") or []),
            "vehicles": len(nat.get("vehicles") or {}),
        },
        "populations": _populations_summary(spec),
        "stairs": world.metrics.get("stairs") or {"dropped": 0, "ruined": 0},
    }


# ------------------------------------------------------------------ output

def _progress(progress, phase, label, gen):
    if progress is None:
        return
    event = {"phase": phase, "label": label, "calls": 0, "tokens": 0}
    if gen is not None:
        event["calls"] = gen[0].calls
        event["tokens"] = gen[0].tokens["total"]
    progress(event)


def _emit(emit, text):
    if emit is not None:
        emit(text)


def _phase_report(client, stats, minutes, emit):
    """The after-phases block the CLI prints (calls, retries, per-phase
    timings, dropped entries)."""
    if emit is None:
        return
    lines = ["", "=" * 64,
             f"phases done: {client.calls} calls, {client.retries} retries, "
             f"{minutes} min, {client.tokens['total']} tokens "
             f"({client.tokens['prompt']} prompt + {client.tokens['completion']} completion)"]
    for entry in stats["phase_log"]:
        lines.append(f"  {entry['phase']:<24} {entry['seconds']:>7.1f}s  "
                     f"{entry['retries']} retries  {entry['tokens']} tokens")
    if stats["dropped"]:
        lines.append(f"dropped/fixed entries ({len(stats['dropped'])}):")
        for what, why in stats["dropped"]:
            lines.append(f"  - {what}: {why}")
    lines.append("=" * 64)
    emit("\n".join(lines))


def _summary_text(world, spec, seed, emit):
    """The after-build block the CLI prints (world shape and check totals)."""
    if emit is None:
        return
    rooms = world.metrics.get("rooms", {})
    ents = world.metrics.get("entrances", {})
    lines = ["", "=" * 64,
             f"{spec['name']}  seed {seed}  grid {world.grid[0]}x{world.grid[1]}",
             f"zones {len(world.zones_by_name)}  roads {len(world.roads)}  "
             f"buildings {len(world.buildings)}  regions {len(spec['regions'])}"]
    n_objects = sum(len(t.get('placements', [])) for t in spec['objectTemplates'])
    lines.append(f"objects placed {n_objects}  characters {len(world.characters)}")
    lines.append(f"rooms reachable {rooms.get('reachable')}/{rooms.get('total')}  "
                 f"entrances from road {ents.get('reachable_from_road')}/{ents.get('total')}  "
                 f"reachability {world.metrics.get('reachability')}")
    unplaced = world.metrics.get("objects", {}).get("unplaced", [])
    dropped = world.metrics.get("errors", {}).get("dropped", [])
    if dropped:
        lines.append(f"ERRORS: dropped planned content ({len(dropped)}):")
        for e in dropped:
            lines.append(f"  - {e['what']}: {e['reason']}")
    if unplaced:
        lines.append(f"unplaced ({len(unplaced)}):")
        for u in unplaced[:8]:
            lines.append(f"  - {u['what']}: {u['reason']}")
        if len(unplaced) > 8:
            lines.append(f"  ... and {len(unplaced) - 8} more")
    if world.fallbacks:
        lines.append(f"hint fallbacks: {len(world.fallbacks)}")
    lines.append(f"doors clear: {world.metrics.get('doors_clear')}  "
                 f"walkways clear: {world.metrics.get('walkways_clear')}  "
                 f"region overlaps: {len(world.metrics.get('region_overlaps', []))}")
    locks = (spec.get("nativeLocks") or {})
    if locks.get("locks") or locks.get("theft"):
        lines.append(f"locked rooms {len(locks.get('locks') or [])}  "
                     f"theft buildings {len(locks.get('theft') or [])}")
        for entry in locks.get("locks") or []:
            held = ", ".join(entry.get("holders") or []) or "nobody (a cell)"
            lines.append(f"  - {entry['room']}: {held}")
    secrets = spec.get("nativeSecrets") or []
    if secrets:
        lines.append(f"secret doors {len(secrets)}")
        for entry in secrets:
            known = ", ".join(entry.get("knownBy") or []) or "nobody"
            where = " and ".join(entry.get("between") or [])
            lines.append(f"  - {where}: {known}")
    nat = spec.get("nativeNature") or {}
    if nat.get("shape") or nat.get("water") or nat.get("vehicles"):
        water = world.metrics.get("water") or {}
        deep = sum(1 for x in water.get("regions") or [] if x.get("depth") == "deep")
        rivers = sum(1 for x in water.get("regions") or [] if x.get("draw") == "river")
        lines.append(f"natural regions {len(nat.get('shape') or [])}  "
                     f"water {len(nat.get('water') or [])} "
                     f"({deep} deep, {rivers} river)  "
                     f"vehicles {len(nat.get('vehicles') or {})}")
        for gone in water.get("dropped") or []:
            lines.append(f"  - {gone['name']}: {gone['reason']}")
    pops = spec.get("nativePopulations") or []
    if pops:
        from worldgen import populations as populations_mod
        n_regions = sum(len(p.get("homes") or []) for p in pops)
        lines.append(f"populations: {populations_mod.creature_count(pops)} "
                     f"creatures in {n_regions} regions "
                     f"({len(pops)} templates), "
                     f"{populations_mod.placed_count(pops)} placed at the start")
        for p in pops:
            homes = ", ".join(f"{h['region']} x{h['count']}"
                              for h in p.get("homes") or [])
            lines.append(f"  - {p['name']}: {homes}")
    fl = world.metrics.get("floors") or {}
    if fl.get("floors"):
        lines.append(f"upper storeys {fl['floors']}  portal pairs {fl['portals']}  "
                     f"floors checks: {'ok' if not fl.get('issues') else fl['issues']}")
    st = world.metrics.get("stairs") or {}
    if st.get("dropped") or st.get("ruined"):
        lines.append(f"stairs to nowhere dropped {st.get('dropped', 0)}  "
                     f"ruined stairs kept {st.get('ruined', 0)}")
    for w in world.metrics.get("map_warnings", []):
        lines.append(f"warning: {w}")
    lines.append("=" * 64)
    emit("\n".join(lines))


def _run(cmd, emit):
    _emit(emit, "$ " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    if out:
        _emit(emit, out)
    return p.returncode, out
