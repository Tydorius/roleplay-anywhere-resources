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


def main(argv=None):
    ap = argparse.ArgumentParser(prog="worldgen")
    sub = ap.add_subparsers(dest="command", required=True)
    lay = sub.add_parser("layout", help="lay out a merged plan and build the scenario")
    lay.add_argument("--plan", required=True)
    lay.add_argument("--out", required=True)
    lay.add_argument("--seed", type=int, default=1)
    lay.add_argument("--ext", action="append", default=[], choices=list(IDS),
                     help="enable a mod extension, off by default (repeatable; "
                          "floors implies portals; also read from plan.json)")
    gen = sub.add_parser("generate", help="run the model phases on an idea and build the scenario")
    gen.add_argument("--idea", required=True)
    gen.add_argument("--provider", required=True)
    gen.add_argument("--out", required=True)
    gen.add_argument("--seed", type=int, default=1)
    gen.add_argument("--providers", default=None, help="providers.json path (default: repo root)")
    gen.add_argument("--no-library", dest="library", action="store_false",
                     help="furnish every room with the model (the old method) instead of "
                          "the room library")
    gen.add_argument("--ext", action="append", default=[], choices=list(IDS),
                     help="enable a mod extension, off by default (repeatable; "
                          "floors implies portals; recorded in plan.json)")
    chk = sub.add_parser("check-provider",
                         help="send one tiny request and report the model and latency")
    chk.add_argument("name", help="provider name from providers.json")
    chk.add_argument("--providers", default=None, help="providers.json path (default: repo root)")
    lib = sub.add_parser("library", help="check the room library and report its coverage")
    lib.add_argument("action", choices=["check"], help="check: validate every library file")
    lib.add_argument("--path", default=None, help="library folder (default: library/)")
    lib.add_argument("--coverage", action="store_true",
                     help="also list room slots that no object can fill")
    args = ap.parse_args(argv)

    if args.command == "library":
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

    try:
        if args.command == "layout":
            summary = api.relayout(args.plan, seed=args.seed, extensions=args.ext,
                                   out_dir=args.out, progress=_print_event, emit=print)
        else:
            summary = api.generate(args.idea, provider=args.provider,
                                   extensions=args.ext, seed=args.seed, library=args.library,
                                   out_dir=args.out, progress=_print_event,
                                   providers_path=args.providers, emit=print)
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
