"""CLI: python -m worldgen layout|generate|check-provider|library ...

A thin wrapper over ``worldgen/api.py`` (the library the Scenario Editor
drives). ``layout`` re-lays-out a saved plan with no model calls; ``generate``
runs the model phases on an idea and builds the scenario; both print a
one-line JSON summary as their last line, for collection scripts.
The builder, validator and renderer live vendored in ``worldgen/vendor/``.
"""
import argparse
import json
import os
import sys

from worldgen import api
from worldgen.extensions import IDS, expand_notes


def _print_event(e):
    """One progress event as a CLI line."""
    tail = ""
    if "calls" in e:
        tail = f"  [{e['calls']} calls, {e['tokens']} tokens]"
    print(f"[{e.get('phase')}] {e.get('label')}{tail}")


def _generate_args(args):
    """generate()'s world arguments from --idea and the rest, or from a
    --settings file with any flags given on top. ValueError when unusable."""
    if args.settings:
        from worldgen import settings as settings_mod
        s = settings_mod.read(args.settings)
        print(f"settings: {args.settings} ({s['mode']} form"
              f"{', with its World Frame' if s.get('frame') else ''})")
        return {"idea": args.idea if args.idea is not None else s["idea"],
                "seed": args.seed if args.seed is not None else s["seed"],
                "extensions": tuple(sorted(set(s["extensions"]) | set(args.ext))),
                "library": s["library"] if args.library is None else args.library,
                "frame": s.get("frame"),
                "questionnaire": settings_mod.questionnaire(s)}
    if not args.idea:
        raise ValueError("give --idea, or --settings with a world settings file")
    return {"idea": args.idea, "seed": 1 if args.seed is None else args.seed,
            "extensions": args.ext, "library": args.library is not False}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="worldgen")
    sub = ap.add_subparsers(dest="command", required=True)
    lay = sub.add_parser("layout", help="lay out a merged plan and build the scenario")
    lay.add_argument("--plan", required=True)
    lay.add_argument("--out", required=True)
    lay.add_argument("--seed", type=int, default=1)
    lay.add_argument("--ext", action="append", default=[], choices=list(IDS),
                     help="enable an extension, off by default (repeatable; "
                          "also read from plan.json)")
    gen = sub.add_parser("generate", help="run the model phases on an idea and build the scenario")
    gen.add_argument("--idea", default=None,
                     help="the world in one line (or give --settings)")
    gen.add_argument("--settings", default=None,
                     help="a world settings file (settings.json from a run folder, or one "
                          "exported from the Scenario Editor): its idea, answers, frame, seed, "
                          "extensions and room-library choice; --idea, --seed, --ext and "
                          "--no-library still override it")
    gen.add_argument("--provider", required=True)
    gen.add_argument("--out", required=True)
    gen.add_argument("--seed", type=int, default=None, help="layout seed (default 1)")
    gen.add_argument("--providers", default=None, help="providers.json path (default: repo root)")
    gen.add_argument("--no-library", dest="library", action="store_false", default=None,
                     help="furnish every room with the model (the old method) instead of "
                          "the room library")
    gen.add_argument("--ext", action="append", default=[], choices=list(IDS),
                     help="enable an extension, off by default (repeatable; "
                          "recorded in plan.json)")
    chk = sub.add_parser("check-provider",
                         help="send one tiny request and report the model and latency")
    chk.add_argument("name", help="provider name from providers.json")
    chk.add_argument("--providers", default=None, help="providers.json path (default: repo root)")
    lib = sub.add_parser("library", help="check the room and item libraries and report coverage")
    lib.add_argument("action", choices=["check", "items"],
                     help="check: validate every room library file; "
                          "items: validate every library/items file")
    lib.add_argument("--path", default=None, help="library folder (default: library/)")
    lib.add_argument("--coverage", action="store_true",
                     help="also list room slots that no object can fill, or the "
                          "item library's coverage table")
    args = ap.parse_args(argv)

    if args.command == "library":
        if args.action == "items":
            from worldgen import item_library as item_mod
            items_dir = os.path.join(args.path, "items") if args.path else None
            items = item_mod.load(items_dir)
            errors = item_mod.check(items)
            for e in errors:
                print("ERROR " + e)
            print(f"items: {len(items)} items, {len(errors)} error(s)")
            if not errors and args.coverage:
                item_mod.report(items)
            return 1 if errors else 0
        from worldgen import library as library_mod
        lb = library_mod.load(args.path or library_mod.LIB_DIR)
        errors, warnings = library_mod.check(lb)
        gaps = library_mod.coverage(lb) if args.coverage else None
        library_mod.report(lb, errors, warnings, gaps)
        return 1 if errors else 0

    if getattr(args, "ext", None):
        _full, notes = expand_notes(args.ext)
        for note in notes:
            print(note)

    if args.command == "check-provider":
        from worldgen import llm
        kwargs = {"providers_path": args.providers} if args.providers else {}
        try:
            report = llm.check_provider(args.name, **kwargs)
        except llm.LLMError as e:
            print(f"FAILED: {e}")
            return 1
        if report["ok"]:
            served = f" (served: {report['served_model']})" if report.get("served_model") else ""
            tokens = f", {report['tokens']} tokens" if report.get("tokens") is not None else ""
            print(f"provider {report['provider']}: model {report['model']}{served}, "
                  f"{report['seconds']}s{tokens}, reply: {report['reply']!r}")
            return 0
        print(f"FAILED: {report['error']}")
        return 1

    if args.command == "generate":
        try:
            run = _generate_args(args)
        except ValueError as e:
            print(f"FAILED: {e}")
            return 2

    try:
        if args.command == "layout":
            summary = api.relayout(args.plan, seed=args.seed, extensions=args.ext,
                                   out_dir=args.out, progress=_print_event, emit=print)
        else:
            summary = api.generate(provider=args.provider, out_dir=args.out,
                                   progress=_print_event, providers_path=args.providers,
                                   emit=print, **run)
    except api.Cancelled:
        print("CANCELLED")
        return 1
    except Exception as e:
        from worldgen import llm, phases
        if not isinstance(e, (llm.LLMError, phases.PhaseError)):
            raise
        print(f"FAILED: {e}")
        print(json.dumps({"ok": False, "provider": getattr(args, "provider", None),
                          "idea": getattr(args, "idea", None), "error": str(e)},
                         ensure_ascii=False))
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
