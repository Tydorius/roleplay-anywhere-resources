#!/usr/bin/env python3
"""Scenario Editor for Anywhere RPG: edit a scenario's map, people, objects and schedules by hand,
see problems as you go, and download a zip for New Game -> Import.

    python scenario_editor.py                # opens http://127.0.0.1:8766 in your browser
    python scenario_editor.py --port 9000 --no-browser
    python scenario_editor.py --store PATH   # the game's data folder, if it isn't in the usual place

Standard library only. It runs on the Image Gallery's code (mods/better-images/image_gallery.py,
loaded as a library, never changed): the same workspaces, zip import and export, and ComfyUI image
jobs. The gallery's own page is the editor's Images tab, and the gallery still runs on its own.

What it writes: scenario.json in a workspace (mods/better-images/gallery-scenarios/), with the
previous version copied to mods/better-images/gallery-backups/ first. It never edits the game's
New Game staging area or a save; copy those to a workspace first.
"""
import argparse
import json
import shutil
import sys
import webbrowser
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
import urllib.parse

HERE = Path(__file__).resolve().parent
GALLERY = HERE.parent.parent / "mods" / "better-images"
sys.path.insert(0, str(GALLERY))
import image_gallery as ig  # noqa: E402

import scenario_checks  # noqa: E402

STATIC = {"/": ("editor.html", "text/html; charset=utf-8"),
          "/editor.js": ("editor.js", "text/javascript; charset=utf-8"),
          "/mapview.js": ("mapview.js", "text/javascript; charset=utf-8"),
          "/mapops.js": ("mapops.js", "text/javascript; charset=utf-8"),
          "/minimap.js": ("minimap.js", "text/javascript; charset=utf-8"),
          "/inspector.js": ("inspector.js", "text/javascript; charset=utf-8"),
          "/schedule.js": ("schedule.js", "text/javascript; charset=utf-8"),
          "/refs.js": ("refs.js", "text/javascript; charset=utf-8"),
          "/refsui.js": ("refsui.js", "text/javascript; charset=utf-8"),
          "/editor.css": ("editor.css", "text/css; charset=utf-8")}


def scenario_sources(store):
    """Workspaces and the New Game staging area (saves are games in progress, not scenarios)."""
    return [{"id": s["id"], "label": s["label"], "editable": s["id"].startswith("work/")}
            for s in ig.sources(store) if s["id"] == "staging" or s["id"].startswith("work/")]


def save_scenario(src, body):
    if not src["id"].startswith("work/"):
        raise ValueError("only workspaces can be saved; copy this one to a workspace first")
    scn = json.loads(body)
    for k in ("name", "gridSize", "regions", "entities", "playerId"):
        if k not in scn:
            raise ValueError(f"not saved: the scenario has no {k!r}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = ig.BACKUPS / src["id"].replace("/", "_") / stamp
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src["data"], dest / "scenario.json")
    tmp = src["data"].with_suffix(".json.tmp")
    tmp.write_text(json.dumps(scn, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(src["data"])
    return str(dest)


class Handler(ig.Handler):
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path in STATIC:
                name, ctype = STATIC[u.path]
                return self.send(200, (HERE / name).read_bytes(), ctype)
            if u.path == "/gallery":
                return self.send(200, ig.PAGE.read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/meta":
                return self.send(200, scenario_checks.meta())
            if u.path == "/api/scenarios":
                return self.send(200, {"sources": scenario_sources(self.store)})
            if u.path == "/api/scenario":
                src = self.source(q)
                return self.send(200, {"scenario": json.loads(src["data"].read_text("utf-8")),
                                       "media": sorted(scenario_checks.media_of(src["dir"])),
                                       "editable": src["id"].startswith("work/")})
        except (LookupError, ValueError, KeyError, OSError) as e:
            return self.send(400, {"error": str(e)})
        return super().do_GET()

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path == "/api/scenario":
                return self.send(200, {"ok": True, "backup": save_scenario(self.source(q), self.body())})
            if u.path == "/api/check":
                src = self.source(q)
                scn = json.loads(self.body())
                return self.send(200, {"problems": scenario_checks.check(scn, scenario_checks.media_of(src["dir"]))})
        except (LookupError, ValueError, KeyError, OSError) as e:
            return self.send(400, {"error": str(e)})
        return super().do_POST()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--store", type=Path, default=ig.default_store(), help="the game's data folder")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    if not a.store.is_dir():
        sys.exit(f"No Anywhere RPG data folder at {a.store} (use --store)")
    Handler.store = a.store
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"Scenario Editor on {url}  (data: {a.store})  Ctrl+C to stop")
    if not a.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
