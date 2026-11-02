"""Library interface for the generator: what the Scenario Editor drives.

Three calls cover the editor's needs:

- ``generate(idea, provider, ...)`` runs the model phases P1-P5 and builds
  the scenario, writing plan.json, spec.json/spec.py, metrics.json, the
  llm/ call logs, the scenario zip and (with Pillow) preview.png;
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

# measured full runs (brief 010): 13-18 calls, 100-150k tokens, 20-35 minutes
MEASURED_CALLS = (13, 18)
MEASURED_TOKENS = (100000, 150000)
MEASURED_MINUTES = (20, 35)
TOKENS_PER_CALL = 8500       # prompt + completion, across P1-P5
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
             emit=None, frame=None, questionnaire=None):
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
    t0 = time.time()
    plan, stats = phases.run_phases(idea, client, extensions=extensions,
                                    progress=progress, cancel=cancel,
                                    frame=frame, questionnaire=questionnaire)
    if extensions:
        plan["extensions"] = sorted(set(plan.get("extensions", [])) | set(extensions))
    phases.write_plan(plan, os.path.join(out_dir, "plan.json"))
    minutes = round((time.time() - t0) / 60.0, 1)
    _phase_report(client, stats, minutes, emit)
    return _layout_and_build(plan, seed=seed, out_dir=out_dir,
                             extra_exts=extensions,
                             gen=(client, stats, minutes, idea),
                             progress=progress, cancel=cancel, emit=emit)


def frame(mode, idea="", answers=None, population=None, clarify=None,
          provider=None, providers_path=None, client=None, log_dir=None,
          progress=None, cancel=None):
    """P0, the World Frame, as its own step (brief 013 change 2). Long mode
    without ``clarify`` runs the clarifying turn and returns
    ``{"questions": [...], "frame": None}``; call again with the answers as
    ``clarify`` (``[{"question", "answer"}]``) to get ``{"questions": [],
    "frame": {...}}``. Every other mode frames in one call. Returns the dict
    with the frame's phase stats under ``"stats"``."""
    if client is None:
        from . import llm
        kwargs = {"providers_path": providers_path} if providers_path else {}
        if log_dir:
            kwargs["log_dir"] = log_dir
        client = llm.Client(provider, **kwargs)
    frm, questions_out, stats = phases.run_frame(
        client, mode, answers=answers, idea=idea, population=population,
        clarify=clarify, progress=progress, cancel=cancel)
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
    call count exactly (P1 + P2 + P5, one per building, one per zone, plus
    retries); an idea gets the midpoints of the measured runs."""
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
    calls = 3 + p3_calls + len(zones)   # P1, P2, P5 + P3 per own design + P4 per zone
    retries = 6                          # the most a measured run needed
    tokens = TOKENS_PER_CALL * calls
    return {"calls": calls, "calls_range": [calls, calls + retries],
            "tokens": tokens, "tokens_range": [tokens, TOKENS_PER_CALL * (calls + retries)],
            "minutes": round(tokens / float(TOKENS_PER_MINUTE), 1),
            "minutes_range": [round(tokens / float(TOKENS_PER_MINUTE), 1),
                              round(TOKENS_PER_CALL * (calls + retries) / float(TOKENS_PER_MINUTE), 1)],
            "basis": f"plan {plan.get('name', '')!r}: 3 phase calls "
                     f"+ {p3_calls} buildings ({same_as} sameAs copies skipped) "
                     f"+ {len(zones)} zones (+ retries)"}


def _mid(pair):
    return (pair[0] + pair[1]) // 2


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
    if rc_build == 0 and spec.get("arpgMods") and os.path.isdir(built):
        from worldgen import mods as mods_mod
        mods_mod.inject_arpg_mods(built, spec["arpgMods"])
        _emit(emit, f"arpgMods injected into {built} (re-zipped)")
        mods_issues = checks_mod.check_scenario_mods(
            os.path.join(built, "scenario.json"), spec["arpgMods"])
        for issue in mods_issues:
            _emit(emit, "ERROR " + issue)
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
    fl = world.metrics.get("floors") or {}
    if fl.get("floors"):
        lines.append(f"upper storeys {fl['floors']}  stair portals {fl['portals']}  "
                     f"floors checks: {'ok' if not fl.get('issues') else fl['issues']}")
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
