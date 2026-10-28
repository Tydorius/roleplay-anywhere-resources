#!/usr/bin/env python3
"""Image Gallery for Anywhere RPG: every image in a scenario or save on one page, with a
Regenerate button on each that draws a new one on your ComfyUI.

    python image_gallery.py                  # opens http://127.0.0.1:8765 in your browser
    python image_gallery.py --port 9000 --no-browser
    python image_gallery.py --store PATH     # the game's data folder, if it isn't in the usual place

Standard library only. Pick a model family and model per image type on the page; the choice is
kept in image_gallery.settings.json next to this file. The page only listens on 127.0.0.1.

Each Regenerate is queued on ComfyUI straight away; the page follows it there (waiting, generating,
done) and shows the result to keep or discard.

What it writes: media/<id>/<id>-<kind>.webp in the New Game staging area or a save, the same file
the game writes, plus a copy of the image it replaced in gallery-backups/. The game reads images
when it loads, so reload the scenario (or the save) to see new ones.
"""
import argparse, base64, json, os, random, re, shutil, sys, threading, time, urllib.error
import urllib.parse, urllib.request, uuid, webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import setup_image_mod as sim

HERE = Path(__file__).resolve().parent
PAGE = HERE / "image_gallery.html"
SETTINGS = HERE / "image_gallery.settings.json"
BACKUPS = HERE / "gallery-backups"

# id prefix -> image kind, for things the game draws an image for
PREFIX_KIND = {"otpl": "sprite", "itpl": "item", "npc": "portrait", "player": "portrait",
               "perk": "perk", "ipk": "perk"}
IMAGE_RE = re.compile(r"^(?P<id>[A-Za-z0-9_]+)-(?P<kind>sprite|item|portrait|perk)\.(webp|png)$")
ID_RE = re.compile(r"^[A-Za-z0-9_]+$")
NATURAL_FAMILIES = {"flux1", "flux2-klein", "qwen-image"}
# Checkpoints trained on booru tags: they count people as 1girl / 2girls, not "one woman".
ANIME_RE = re.compile(r"illustrious|pony|noob|anima|animagine|wai|hassaku|nova|furry|anything|counterfeit|meina", re.I)

# Portrait subject per prompt style: positive goes in front of the prompt, negative is added to
# the workflow's negative (families with no negative, Flux, use the positive only).
SUBJECTS = {
    "anime": {
        "pos": {"woman": "1girl, solo", "man": "1boy, solo", "girl": "1girl, solo", "boy": "1boy, solo",
                "person": "solo", "creature": "no humans, solo, creature focus"},
        "neg": {"woman": "2girls, multiple girls, 1boy, multiple boys, group",
                "man": "2boys, multiple boys, 1girl, multiple girls, group",
                "girl": "2girls, multiple girls, 1boy, multiple boys, group",
                "boy": "2boys, multiple boys, 1girl, multiple girls, group",
                "person": "2girls, 2boys, multiple girls, multiple boys, group",
                "creature": "1girl, 1boy, humans, multiple animals"},
    },
    "tags": {
        "pos": {"woman": "one woman, solo", "man": "one man, solo", "girl": "one girl, solo", "boy": "one boy, solo",
                "person": "one person, solo", "creature": "one creature, solo, animal focus"},
        "neg": {"woman": "two women, multiple women, man, group, crowd, twins",
                "man": "two men, multiple men, woman, group, crowd, twins",
                "girl": "two girls, multiple girls, boy, group, crowd, twins",
                "boy": "two boys, multiple boys, girl, group, crowd, twins",
                "person": "two people, multiple people, group, crowd, twins",
                "creature": "person, people, human, multiple animals, pack, herd"},
    },
    "natural": {
        "pos": {"woman": "One woman, alone in the frame.", "man": "One man, alone in the frame.",
                "girl": "One girl, alone in the frame.", "boy": "One boy, alone in the frame.",
                "person": "One person, alone in the frame.",
                "creature": "One creature, alone in the frame, no people."},
        "neg": {"woman": "two women, multiple people", "man": "two men, multiple people",
                "girl": "two girls, multiple people", "boy": "two boys, multiple people",
                "person": "two people, multiple people", "creature": "people, multiple animals"},
    },
}
SUBJECT_NOUNS = ("auto", "woman", "man", "girl", "boy", "person", "creature", "none")

_lock = threading.Lock()
_info_cache = {}
# Generation jobs, by ComfyUI prompt id. Kept until the image is kept or discarded, so a reloaded
# page picks them up again; lost when this program stops.
JOBS = {}
_jobs_lock = threading.Lock()
LOST_AFTER = 5  # polls with the job neither queued nor in ComfyUI's history


# ---------------------------------------------------------------- settings and store
def default_store():
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", "")) / "Anywhere RPG"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Anywhere RPG"
    return Path.home() / ".config" / "Anywhere RPG"


def load_settings():
    s = {"comfy": "http://127.0.0.1:8188", "remover": "auto",
         "kinds": {k: {"family": "flux2-klein", "files": {}} for k in sim.KINDS}}
    if SETTINGS.exists():
        try:
            saved = json.loads(SETTINGS.read_text("utf-8"))
            s.update({k: v for k, v in saved.items() if k in ("comfy", "remover")})
            for k, v in (saved.get("kinds") or {}).items():
                if k in s["kinds"] and isinstance(v, dict):
                    s["kinds"][k] = {"family": v.get("family", "flux2-klein"), "files": dict(v.get("files") or {})}
        except (ValueError, OSError):
            pass
    return s


def save_settings(s):
    SETTINGS.write_text(json.dumps(s, indent=2) + "\n", "utf-8")


def sources(store):
    """[{id, label, dir, data}]: the New Game staging area and every save that has images."""
    out = []
    st = store / "staging"
    if (st / "scenario.json").exists():
        out.append({"id": "staging", "dir": st, "data": st / "scenario.json",
                    "label": "New Game: " + scenario_name(st / "scenario.json", "name")})
    saves = store / "saves"
    if saves.is_dir():
        for d in sorted(p for p in saves.iterdir() if p.is_dir() and (p / "media").is_dir()):
            data = [f for f in d.glob("*.json") if not f.name.endswith(".meta.json")]
            data = max(data, key=lambda f: f.stat().st_mtime) if data else None
            name = scenario_name(data, "scenarioName") if data else "?"
            out.append({"id": "saves/" + d.name, "dir": d, "data": data, "label": f"Save {d.name}: {name}"})
    return out


def scenario_name(path, key):
    try:
        return str(json.loads(path.read_text("utf-8")).get(key) or path.parent.name)
    except (ValueError, OSError):
        return path.parent.name


def find_source(store, sid):
    return next((s for s in sources(store) if s["id"] == sid), None)


# ---------------------------------------------------------------- what needs an image
def index_things(o, out):
    if isinstance(o, dict):
        i = o.get("id")
        if isinstance(i, str) and i.split("_")[0] in PREFIX_KIND and i not in out:
            out[i] = o
        for v in o.values():
            index_things(v, out)
    elif isinstance(o, list):
        for v in o:
            index_things(v, out)


def describe(kind, o):
    """The text the game puts in ${DESC}."""
    if kind == "portrait":
        g = o.get("gender")
        who = f"{o.get('name', '')} ({g})" if g else o.get("name", "")
        return f"{who}: {o.get('physicalDescription') or o.get('description') or ''}".strip()
    return o.get("physicalDescription") or o.get("description") or o.get("name") or ""


def subject_noun(o):
    anim = (o.get("animationId") or "").lower()
    if anim and not re.search(r"(man|woman|boy|girl|child|kid|person|human)$", anim):
        return "creature"
    ages = {a.lower() for a in ((o.get("voiceProfile") or {}).get("age") or [])}
    young = bool(ages) and ages <= {"child", "kid", "teen"}
    g = (o.get("gender") or "").lower()
    if g == "female":
        return "girl" if young else "woman"
    if g == "male":
        return "boy" if young else "man"
    return "person"


def list_items(src):
    data = json.loads(src["data"].read_text("utf-8")) if src["data"] else {}
    things = {}
    index_things(data, things)
    media = src["dir"] / "media"
    on_disk = {}
    if media.is_dir():
        for d in media.iterdir():
            if d.is_dir():
                for f in d.iterdir():
                    m = IMAGE_RE.match(f.name)
                    if m and m["id"] == d.name:
                        on_disk[d.name] = (m["kind"], f)
    sizes = {t["id"]: t.get("size") for t in data.get("objectTemplates", []) if isinstance(t, dict)}
    fmt = ((data.get("imageSettings") or {}).get("promptFormat") or "").strip()
    items = []
    for i in sorted(set(things) | set(on_disk)):
        o = things.get(i, {})
        kind = on_disk[i][0] if i in on_disk else PREFIX_KIND[i.split("_")[0]]
        f = on_disk.get(i, (None, None))[1]
        size = sizes.get(i) or o.get("size") or [1, 1]
        items.append({
            "id": i, "kind": kind, "name": o.get("name") or i, "desc": describe(kind, o),
            "aspect": round((size[0] + 0.5) / (size[1] + 0.5), 4) if kind == "sprite" else 1,
            "subject": subject_noun(o) if kind == "portrait" else None,
            "file": f.name if f else None, "mtime": int(f.stat().st_mtime) if f else 0,
            "known": i in things,
        })
    return {"items": items, "promptFormat": fmt}


# ---------------------------------------------------------------- ComfyUI
def comfy(url, path, body=None, timeout=60):
    req = urllib.request.Request(url.rstrip("/") + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def object_info(url, refresh=False):
    with _lock:
        if refresh or url not in _info_cache:
            _info_cache[url] = json.loads(comfy(url, "/object_info"))
        return _info_cache[url]


def model_menu(url, refresh=False):
    info = object_info(url, refresh)
    fams = {}
    for key, fam in sim.FAMILIES.items():
        detected, missing = sim.detect(info, fam)
        roles = []
        for role, (std, node, inp, pats) in fam["files"].items():
            names = sim.options(info, node, inp)
            hits = [n for n in names if any(re.search(p, n, re.I) for p in pats)]
            roles.append({"role": role, "folder": fam["folders"][role], "detected": detected[role],
                          "options": hits + [n for n in names if n not in hits], "matches": len(hits)})
        fams[key] = {"title": fam["title"].replace("Better Images: ", ""), "summary": fam["summary"],
                     "kinds": list(fam["kinds"]), "roles": roles, "missing": missing,
                     "loaderInstalled": all(fam["files"][r][1] in info for r in fam["files"])}
    removers = {k: bool(v["node"] and v["node"] in info) for k, v in sim.REMOVERS.items()}
    removers["none"] = True
    return {"families": fams, "removers": removers, "autoRemover": sim.pick_remover(info, None)}


def prompt_style(family, model):
    if family in NATURAL_FAMILIES:
        return "natural"
    return "anime" if ANIME_RE.search(model or "") else "tags"


def snap_size(base, aspect):
    snap = lambda v: max(128, round(v / 64) * 64)
    if aspect == 1:
        return base, base
    return (base, snap(base / aspect)) if aspect > 1 else (snap(base * aspect), base)


def build(req, settings, url):
    kind, family = req["kind"], req["family"]
    fam = sim.FAMILIES[family]
    if kind not in fam["kinds"]:
        raise ValueError(f"{family} has no {kind} workflow")
    info = object_info(url)
    detected, _ = sim.detect(info, fam)
    files = {r: (req.get("files") or {}).get(r) or detected[r] for r in fam["files"]}
    remover = settings.get("remover") or "auto"
    remover = sim.pick_remover(info, None) if remover == "auto" else remover
    wf = sim.workflow(fam, files, kind, remover)

    prompt = fam["prompts"][kind].replace("${DESC}", req["desc"])
    fmt = (req.get("promptFormat") or "").strip()
    if fmt and kind != "sprite":  # the world's prompt format, applied as the game does
        prompt = prompt.join(fmt.split("${prompt}")) if "${prompt}" in fmt else f"{fmt} {prompt}"
    negative_extra = ""
    if kind == "portrait":
        noun = req.get("subject") or "auto"
        if noun == "auto":
            noun = req.get("autoSubject") or "person"
        if noun != "none":
            style = SUBJECTS[prompt_style(family, files[next(iter(fam["files"]))])]
            prompt = f"{style['pos'][noun]}{' ' if family in NATURAL_FAMILIES else ', '}{prompt}"
            negative_extra = style["neg"][noun]

    base = max(v for n in wf.values() for k, v in n["inputs"].items() if k in ("width", "height"))
    w, h = snap_size(base, float(req.get("aspect") or 1))
    seed = random.randrange(10 ** 12)
    vals = {"PROMPT": prompt, "WIDTH": w, "HEIGHT": h, "SEED": seed}
    negative = ""
    for node in wf.values():  # fill <input>=TOKEN slots from node titles, as the game does
        title = node.get("_meta", {}).get("title", "")
        for inp, tok in re.findall(r"(\w+)=(\w+)", title):
            if tok in vals:
                node["inputs"][inp] = vals[tok]
        if title == "Negative":
            parts = [p for p in (node["inputs"]["text"], negative_extra) if p]
            node["inputs"]["text"] = negative = ", ".join(parts)
    return wf, {"prompt": prompt, "negative": negative, "seed": seed, "width": w, "height": h,
                "files": files, "remover": remover}


def submit(req, settings):
    """Queues one image on ComfyUI and returns the job; poll_jobs() follows it from there."""
    url = settings["comfy"]
    wf, meta = build(req, settings, url)
    try:
        r = json.loads(comfy(url, "/prompt", {"prompt": wf, "client_id": "anywhere-rpg-gallery-" + uuid.uuid4().hex[:8]}))
    except urllib.error.HTTPError as e:
        raise RuntimeError("ComfyUI refused the workflow: " + e.read().decode("utf-8", "replace")[:1500])
    job = {"pid": r["prompt_id"], "url": url, "source": req["source"], "id": req["id"], "kind": req["kind"],
           "state": "pending", "position": None, "submitted": time.time(), "started": None, "finished": None,
           "error": None, "meta": meta, "png": None, "misses": 0}
    with _jobs_lock:
        for old in [j for j in JOBS.values() if j["source"] == job["source"] and j["id"] == job["id"]]:
            JOBS.pop(old["pid"], None)  # one job per image; a newer one replaces an unreviewed result
        JOBS[job["pid"]] = job
    return public(job)


def public(job):
    now = time.time()
    end = job["finished"] or now
    return {**{k: job[k] for k in ("pid", "source", "id", "kind", "state", "position", "error", "meta")},
            "waited": round((job["started"] or end) - job["submitted"]),
            "elapsed": round(end - job["started"]) if job["started"] else 0}


def poll_jobs():
    """Updates every unfinished job from ComfyUI's queue and history. Returns ComfyUI queue totals."""
    with _jobs_lock:
        active = [j for j in JOBS.values() if j["state"] in ("pending", "running")]
    totals = {}
    for url in {j["url"] for j in active}:
        q = json.loads(comfy(url, "/queue"))
        running = {e[1] for e in q.get("queue_running", [])}
        pending = sorted(q.get("queue_pending", []), key=lambda e: e[0])
        position = {e[1]: n + 1 for n, e in enumerate(pending)}
        totals = {"running": len(running), "pending": len(pending)}
        for j in (j for j in active if j["url"] == url):
            if j["pid"] in running:
                if j["state"] != "running":
                    j["state"], j["started"], j["position"] = "running", time.time(), None
            elif j["pid"] in position:
                j["state"], j["position"] = "pending", position[j["pid"]]
            else:
                finish(j)
    return totals


def finish(j):
    try:
        hist = json.loads(comfy(j["url"], f"/history/{j['pid']}")).get(j["pid"])
    except urllib.error.URLError:
        return
    j["started"] = j["started"] or time.time()
    if not hist:
        j["misses"] += 1
        if j["misses"] >= LOST_AFTER:
            j["state"], j["error"], j["finished"] = "error", "ComfyUI dropped this job (restarted or cleared?)", time.time()
        return
    status = hist.get("status", {})
    imgs = [i for o in hist.get("outputs", {}).values() for i in o.get("images", []) if i.get("type") == "output"]
    if status.get("status_str") == "error" or not imgs:
        msgs = [m[1].get("exception_message", "") for m in status.get("messages", []) if m[0] == "execution_error"]
        interrupted = any(m[0] == "execution_interrupted" for m in status.get("messages", []))
        j["error"] = ("Cancelled" if interrupted else "ComfyUI error: " + ("; ".join(msgs) or "no image produced"))
        j["state"], j["finished"] = "error", time.time()
        return
    q = urllib.parse.urlencode({k: imgs[0][k] for k in ("filename", "subfolder", "type")})
    j["png"] = comfy(j["url"], "/view?" + q, timeout=120)
    j["state"], j["finished"] = "done", time.time()


def cancel(pid):
    with _jobs_lock:
        j = JOBS.get(pid)
    if not j:
        return
    if j["state"] == "pending":
        comfy(j["url"], "/queue", {"delete": [pid]})
    elif j["state"] == "running":
        comfy(j["url"], "/interrupt", {"prompt_id": pid})  # only stops this job, not someone else's
    with _jobs_lock:
        JOBS.pop(pid, None)


# ---------------------------------------------------------------- writing images
def image_path(src, iid, kind):
    if not ID_RE.match(iid) or kind not in sim.KINDS:
        raise ValueError("bad id or kind")
    return src["dir"] / "media" / iid / f"{iid}-{kind}.webp"


def backup_and_clear(src, iid, kind):
    """Moves the current image to gallery-backups/ and deletes files the game derived from it
    (sprite normal map and outlines), so they are rebuilt from the new image."""
    folder = image_path(src, iid, kind).parent
    if not folder.is_dir():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUPS / src["id"].replace("/", "_") / stamp
    moved = None
    for f in folder.iterdir():
        if f.is_file() and (f.name.startswith(f"{iid}-{kind}.") or f.name.startswith(f"{iid}-{kind}-")):
            if IMAGE_RE.match(f.name):
                dest.mkdir(parents=True, exist_ok=True)
                moved = shutil.move(str(f), dest / f.name)
            else:
                f.unlink()
    return moved


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    store = None

    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype="application/json"):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def source(self, q):
        src = find_source(self.store, (q.get("source") or [""])[0])
        if not src:
            raise LookupError("unknown source")
        return src

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path == "/":
                return self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/state":
                return self.send(200, {
                    "settings": load_settings(), "store": str(self.store),
                    "sources": [{"id": s["id"], "label": s["label"]} for s in sources(self.store)],
                    "kinds": list(sim.KINDS), "subjects": list(SUBJECT_NOUNS)})
            if u.path == "/api/models":
                return self.send(200, model_menu(load_settings()["comfy"], refresh="refresh" in q))
            if u.path == "/api/items":
                return self.send(200, list_items(self.source(q)))
            if u.path == "/api/jobs":
                try:
                    totals, err = poll_jobs(), None
                except urllib.error.URLError as e:
                    totals, err = {}, f"can't reach ComfyUI: {e.reason}"
                with _jobs_lock:
                    jobs = [public(j) for j in JOBS.values()]
                return self.send(200, {"jobs": jobs, "comfyQueue": totals, "error": err})
            if u.path == "/api/result":
                j = JOBS.get(q["pid"][0])
                if not j or not j["png"]:
                    raise LookupError("no image for that job")
                return self.send(200, j["png"], "image/png")
            if u.path == "/media":
                src = self.source(q)
                iid, name = q["id"][0], q["file"][0]
                m = IMAGE_RE.match(name)
                if not (ID_RE.match(iid) and m and m["id"] == iid):
                    raise ValueError("bad file")
                f = src["dir"] / "media" / iid / name
                return self.send(200, f.read_bytes(), "image/webp" if name.endswith(".webp") else "image/png")
            return self.send(404, {"error": "not found"})
        except (LookupError, ValueError, KeyError, OSError) as e:
            return self.send(400, {"error": str(e)})
        except urllib.error.URLError as e:
            return self.send(502, {"error": f"can't reach ComfyUI: {e.reason}"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path == "/api/settings":
                s = load_settings()
                new = json.loads(self.body())
                if "comfy" in new:
                    s["comfy"] = str(new["comfy"]).strip().rstrip("/")
                if new.get("remover") in ("auto", *sim.REMOVERS):
                    s["remover"] = new["remover"]
                for k, v in (new.get("kinds") or {}).items():
                    if k in s["kinds"] and v.get("family") in sim.FAMILIES:
                        s["kinds"][k] = {"family": v["family"], "files": {r: n for r, n in (v.get("files") or {}).items()
                                                                          if r in sim.FAMILIES[v["family"]]["files"] and n}}
                save_settings(s)
                return self.send(200, s)
            if u.path == "/api/submit":
                req = json.loads(self.body())
                if req.get("family") not in sim.FAMILIES or req.get("kind") not in sim.KINDS:
                    raise ValueError("bad family or kind")
                if not find_source(self.store, req.get("source", "")) or not ID_RE.match(req.get("id", "")):
                    raise ValueError("bad source or id")
                return self.send(200, submit(req, load_settings()))
            if u.path == "/api/forget":
                with _jobs_lock:
                    JOBS.pop(q["pid"][0], None)
                return self.send(200, {"ok": True})
            if u.path == "/api/cancel":
                cancel(q["pid"][0])
                return self.send(200, {"ok": True})
            if u.path in ("/api/save", "/api/delete"):
                src = self.source(q)
                iid, kind = q["id"][0], q["kind"][0]
                path = image_path(src, iid, kind)
                data = self.body() if u.path == "/api/save" else None
                if data is not None and not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
                    raise ValueError("expected a WebP image")
                with _lock:
                    backup = backup_and_clear(src, iid, kind)
                    if data is not None:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(data)
                    elif path.parent.is_dir() and not any(path.parent.iterdir()):
                        path.parent.rmdir()
                return self.send(200, {"ok": True, "backup": str(backup) if backup else None})
            return self.send(404, {"error": "not found"})
        except (LookupError, ValueError, KeyError, OSError) as e:
            return self.send(400, {"error": str(e)})
        except urllib.error.URLError as e:
            return self.send(502, {"error": f"can't reach ComfyUI: {e.reason}"})
        except RuntimeError as e:
            return self.send(502, {"error": str(e)})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--store", type=Path, default=default_store(), help="the game's data folder")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    if not a.store.is_dir():
        sys.exit(f"No Anywhere RPG data folder at {a.store} (use --store)")
    Handler.store = a.store
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"Image Gallery on {url}  (data: {a.store})  Ctrl+C to stop")
    if not a.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
