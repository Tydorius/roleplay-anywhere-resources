"""World generation behind the Scenario Editor: drives the standalone generator
in ../world-generator through its library API (worldgen/api.py) and puts each
result in a new editor workspace, with plan.json kept beside it for re-rolls.

One job runs at a time, in a background thread — a generation holds model calls
for half an hour. The generator itself stays standalone: it is only imported
(never changed) and still runs on its own from the command line.

Provider settings live in the generator's providers.json. Keys are never sent
back to the browser in full: the list shows names, models and the last four
characters of each key at most.
"""
import json
import re
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
GALLERY = HERE.parent.parent / "mods" / "better-images"
WORLDGEN_DIR = HERE.parent / "world-generator"
for _p in (str(GALLERY), str(WORLDGEN_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import image_gallery as ig  # noqa: E402  (the editor's workspaces and zip import)
from worldgen import api as wgapi  # noqa: E402
from worldgen import llm as wgllm  # noqa: E402
from worldgen.extensions import registry as extension_registry  # noqa: E402

PROVIDERS_JSON = Path(wgllm.PROVIDERS_PATH)   # tools/world-generator/providers.json
OUT_ROOT = WORLDGEN_DIR / "out"


class JobBusyError(RuntimeError):
    pass


# ---------------------------------------------------------------- providers
def _read_providers():
    try:
        return json.loads(PROVIDERS_JSON.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _key_hint(key):
    key = str(key or "")
    if not key or key == wgllm.PLACEHOLDER_KEY:
        return None
    return "\u2026" + key[-4:] if len(key) >= 8 else "(short key set)"


def providers():
    """The configured providers as [{name, model, ready, keyHint}], or None when
    providers.json does not exist yet. The api key never appears in full."""
    data = _read_providers()
    if data is None:
        return None
    out = []
    for name, cfg in sorted(data.items()):
        if name.startswith("_") or not isinstance(cfg, dict):
            continue
        key = str(cfg.get("api_key") or "")
        ready = bool(cfg.get("base_url") and cfg.get("model") and key
                     and key != wgllm.PLACEHOLDER_KEY)
        out.append({"name": name, "model": cfg.get("model") or "",
                    "ready": ready, "keyHint": _key_hint(key)})
    return out


def meta():
    ps = providers()
    return {"providers": ps or [], "hasProvidersFile": ps is not None,
            "providersPath": str(PROVIDERS_JSON),
            "extensions": extension_registry()}


def save_provider(name, base_url, api_key, model, max_tokens):
    """Add or update one entry in the generator's providers.json (creating the
    file if needed). An empty api_key keeps the stored one, so the browser never
    has to send a key back. Returns providers()."""
    name = str(name or "").strip()
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9 _-]*$", name):
        raise ValueError("provider name: letters, digits, space, - or _ (and not empty)")
    data = _read_providers()
    if data is None:
        data = {"_readme": ["Providers for the world generator (written by the Scenario Editor).",
                            "Keys are never sent back to the browser in full."]}
    old = data.get(name) if isinstance(data.get(name), dict) else {}
    entry = {"base_url": str(base_url or "").strip().rstrip("/"),
             "api_key": str(api_key or "").strip() or str(old.get("api_key") or ""),
             "model": str(model or "").strip(),
             "max_tokens": _int_or(max_tokens, old.get("max_tokens", 16000))}
    for k, what in (("base_url", "the base URL"), ("model", "the model"),
                    ("api_key", "the API key (the first time you add the provider)")):
        if not entry[k]:
            raise ValueError(f"{what} is required")
    data[name] = entry
    PROVIDERS_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROVIDERS_JSON.with_name(PROVIDERS_JSON.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
    tmp.replace(PROVIDERS_JSON)
    return providers()


def _int_or(value, fallback):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


# ---------------------------------------------------------------- estimate
def estimate(idea):
    idea = str(idea or "").strip()
    if not idea:
        raise ValueError("type the idea first")
    return wgapi.estimate(idea)


# ---------------------------------------------------------------- jobs
_job = None          # the one job dict; None when nothing has run yet
_lock = threading.Lock()
_PUBLIC = ("id", "kind", "state", "phase", "label", "idea", "calls", "tokens",
           "started", "finished", "error", "outDir", "logDir", "source", "summary")


def job():
    with _lock:
        return {k: _job.get(k) for k in _PUBLIC} if _job else None


def cancel():
    with _lock:
        if _job is None or _job["state"] != "running":
            raise ValueError("no job is running")
        _job["cancelRequested"] = True
        return {k: _job.get(k) for k in _PUBLIC}


def _start(kind, fields, target):
    """Start ``target(update, job_dict)`` in the one job thread. Returns the new
    job; raises JobBusyError while another job is running."""
    global _job
    with _lock:
        if _job is not None and _job["state"] == "running":
            raise JobBusyError("a world generation job is already running")
        j = {"id": f"{kind}-{int(time.time() * 1000)}", "kind": kind,
             "state": "running", "phase": "starting", "label": "", "idea": None,
             "calls": 0, "tokens": 0,
             "started": datetime.now().strftime("%H:%M:%S"), "finished": None,
             "error": None, "outDir": None, "logDir": None, "source": None,
             "summary": None, "cancelRequested": False}
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
    except wgapi.Cancelled as e:
        update(state="cancelled", error=str(e) or "cancelled")
    except Exception as e:
        update(state="failed", error=f"{type(e).__name__}: {e}")
    finally:
        update(finished=datetime.now().strftime("%H:%M:%S"))


def _slug(text, n=30):
    return re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-")[:n].lower() or "world"


def _fresh_out_dir(label):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    d, i = OUT_ROOT / f"{stamp}-{_slug(label)}", 2
    while d.exists():
        d, i = OUT_ROOT / f"{stamp}-{_slug(label)}-{i}", i + 1
    return d


def _to_workspace(out_dir, summary, plan_path):
    """Import the built zip as a new editor workspace and copy ``plan_path``
    beside it, so Re-roll layout works there too. Returns the source id."""
    zip_name = summary.get("zip") if isinstance(summary, dict) else None
    zip_path = Path(out_dir) / zip_name if zip_name else None
    if not zip_path or not zip_path.is_file():
        raise RuntimeError(f"the run built no zip; its output is in {out_dir}")
    sid = ig.import_zip(zip_path.read_bytes())
    ws = Path(ig.WORK) / sid[len("work/"):]
    shutil.copyfile(plan_path, ws / "plan.json")
    return sid


def start_generate(idea, provider, extensions=(), seed=1):
    """Start a full generation (model phases + layout + build) for ``idea``."""
    idea = str(idea or "").strip()
    if not idea:
        raise ValueError("type the idea first")
    entries = providers()
    if not entries:
        raise ValueError("no provider is configured yet: add one first (your own key, "
                         "not the game's subscription)")
    provider = str(provider or "").strip()
    entry = next((e for e in entries if e["name"] == provider), None)
    if entry is None:
        raise ValueError(f"unknown provider {provider!r} (configured: "
                         + ", ".join(e["name"] for e in entries) + ")")
    if not entry["ready"]:
        raise ValueError(f"provider {provider!r} has no usable key yet — open Provider settings")
    unknown = sorted(set(extensions or ()) - {e["id"] for e in extension_registry()})
    if unknown:
        raise ValueError(f"unknown extension(s) {unknown}")
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        raise ValueError("the seed must be a whole number")

    out_dir = _fresh_out_dir(idea)
    exts = tuple(extensions or ())

    def target(update, j):
        update(outDir=str(out_dir), logDir=str(out_dir / "llm"))
        out_dir.mkdir(parents=True, exist_ok=True)
        summary = wgapi.generate(
            idea, provider=provider, extensions=exts, seed=seed, out_dir=str(out_dir),
            progress=lambda e: update(phase=e.get("phase"), label=e.get("label"),
                                      calls=e.get("calls", 0), tokens=e.get("tokens", 0)),
            cancel=lambda: j["cancelRequested"])
        sid = _to_workspace(out_dir, summary, Path(out_dir) / "plan.json")
        update(source=sid, summary=summary)

    return _start("generate", {"label": "new world", "idea": idea}, target)


def _workspace_dir(source_id):
    """The folder of a work/ source id, without touching the game's store (the
    gallery's find_source needs a real store even for workspace ids)."""
    sid = str(source_id or "")
    if not sid.startswith("work/") or "/" in sid[len("work/"):]:
        return None
    d = Path(ig.WORK) / sid[len("work/"):]
    return d if (d / "scenario.json").is_file() else None


def start_reroll(source_id, seed=1):
    """Re-place a workspace's saved plan with a new seed: no model calls, a new
    layout of the same world in a fresh workspace."""
    ws = _workspace_dir(source_id)
    if not ws:
        raise LookupError("unknown workspace")
    plan_path = ws / "plan.json"
    if not plan_path.is_file():
        raise ValueError("this workspace has no saved plan (only generated worlds have one)")
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        raise ValueError("the seed must be a whole number")
    out_dir = _fresh_out_dir("reroll-" + ws.name)

    def target(update, j):
        update(outDir=str(out_dir),
               label=f"re-rolling {ws.name} with seed {seed}")
        out_dir.mkdir(parents=True, exist_ok=True)
        summary = wgapi.relayout(str(plan_path), seed=seed, out_dir=str(out_dir),
                                 progress=lambda e: update(phase=e.get("phase"), label=e.get("label")),
                                 cancel=lambda: j["cancelRequested"])
        sid = _to_workspace(out_dir, summary, plan_path)
        update(source=sid, summary=summary)

    return _start("reroll", {"label": ws.name}, target)


def plan_info(source_id):
    """Whether a source has a saved plan, and which extensions it was generated
    with (a re-roll keeps them)."""
    ws = _workspace_dir(source_id)
    plan = ws / "plan.json" if ws else None
    if not plan or not plan.is_file():
        return {"has": False, "extensions": []}
    try:
        exts = json.loads(plan.read_text("utf-8")).get("extensions") or []
    except (OSError, ValueError):
        exts = []
    return {"has": True, "extensions": exts, "planPath": str(plan)}
