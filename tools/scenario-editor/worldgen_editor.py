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
from worldgen import questions as wgquestions  # noqa: E402
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


# ---------------------------------------------------------------- question bank
def question_bank():
    """The generator's question bank for the dialog: both forms' questions
    (the long form asks the medium ones, then a clarifying model turn) and the
    population limits, as plain data."""
    default, lo, hi = wgquestions.population_limits()
    return {"modes": list(wgquestions.MODES),
            "short": wgquestions.form_questions("short"),
            "medium": wgquestions.form_questions("medium"),
            "population": {"default": default, "min": lo, "max": hi}}


def _checked_provider(provider):
    """The provider entry for ``provider`` (a ready one, or a 400)."""
    entries = providers()
    if not entries:
        raise ValueError("no provider is configured yet: add one first (your own key, "
                         "not the game's subscription)")
    entry = next((e for e in entries if e["name"] == str(provider or "").strip()), None)
    if entry is None:
        raise ValueError(f"unknown provider {provider!r} (configured: "
                         + ", ".join(e["name"] for e in entries) + ")")
    if not entry["ready"]:
        raise ValueError(f"provider {provider!r} has no usable key yet — open Provider settings")
    return entry


def _clean_clarify(clarify):
    """The clarifying answers of the long form: [{question, answer}], both
    non-empty strings, at most five."""
    if clarify is None:
        return None
    out = []
    for c in clarify:
        if not isinstance(c, dict):
            continue
        q = str(c.get("question") or "").strip()
        a = str(c.get("answer") or "").strip()
        if q and a:
            out.append({"question": q, "answer": a})
    return out[:5]           # [] = the user skipped every question: frame now


def _checked_questionnaire(questionnaire):
    """A questionnaire {mode, answers, population} cleaned by the generator's
    own rules (known questions and options only, the population clamped)."""
    if questionnaire is None:
        return None
    if not isinstance(questionnaire, dict):
        raise ValueError("the questionnaire must be an object {mode, answers, population}")
    mode = str(questionnaire.get("mode") or "quick").strip()
    if mode not in wgquestions.MODES:
        raise ValueError(f"unknown mode {mode!r}; use one of {list(wgquestions.MODES)}")
    out = {"mode": mode,
           "answers": wgquestions.sanitize_answers(mode, questionnaire.get("answers")),
           "population": wgquestions.sanitize_population(questionnaire.get("population"))}
    notes = wgquestions.sanitize_notes(questionnaire.get("notes"))
    if notes:
        out["notes"] = notes
    return out


# ---------------------------------------------------------------- jobs
_job = None          # the one job dict; None when nothing has run yet
_lock = threading.Lock()
_PUBLIC = ("id", "kind", "state", "phase", "label", "idea", "calls", "tokens",
           "started", "finished", "error", "outDir", "logDir", "source", "summary",
           "frame", "questions", "draft")


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


def start_generate(idea, provider, extensions=(), seed=1, frame=None, questionnaire=None,
                   draft=None):
    """Start a full generation (model phases + layout + build) for ``idea``,
    with an approved World Frame and its questionnaire kept on the plan.
    ``draft`` names the saved dialog draft, which records the run."""
    idea = str(idea or "").strip()
    questionnaire = _checked_questionnaire(questionnaire)
    if not idea and (frame is None and questionnaire is None):
        raise ValueError("type the idea first")
    if frame is not None and not (isinstance(frame, dict)
                                  and isinstance(frame.get("summary"), str)):
        raise ValueError("the frame must be the approved World Frame object")
    entry = _checked_provider(provider)
    unknown = sorted(set(extensions or ()) - {e["id"] for e in extension_registry()})
    if unknown:
        raise ValueError(f"unknown extension(s) {unknown}")
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        raise ValueError("the seed must be a whole number")

    draft = _checked_draft_id(draft) if draft else None
    out_dir = _fresh_out_dir(idea or (questionnaire or {}).get("mode") or "world")
    exts = tuple(extensions or ())

    def target(update, j):
        update(outDir=str(out_dir), logDir=str(out_dir / "llm"))
        out_dir.mkdir(parents=True, exist_ok=True)
        if draft:
            _merge_draft(draft, {"run": {"job": j["id"], "outDir": str(out_dir),
                                         "started": j["started"]}})
        summary = wgapi.generate(
            idea, provider=entry["name"], extensions=exts, seed=seed, out_dir=str(out_dir),
            frame=frame, questionnaire=questionnaire,
            progress=lambda e: update(phase=e.get("phase"), label=e.get("label"),
                                      calls=e.get("calls", 0), tokens=e.get("tokens", 0)),
            cancel=lambda: j["cancelRequested"])
        sid = _to_workspace(out_dir, summary, Path(out_dir) / "plan.json")
        update(source=sid, summary=summary)
        if draft:
            _merge_draft(draft, {"run": {"job": j["id"], "outDir": str(out_dir),
                                         "started": j["started"], "source": sid}})

    return _start("generate", {"label": "new world", "idea": idea or None, "draft": draft},
                  target)


# ---------------------------------------------------------------- the frame job
def start_frame(mode, idea="", answers=None, population=None, provider=None, clarify=None,
                notes="", draft=None):
    """Start P0 (the World Frame) as its own short job. In long mode without
    ``clarify`` the job ends with ``questions`` (the clarifying turn) and no
    frame; send them back answered as ``clarify`` to get the frame. ``frame``
    on the finished job is what "Generate" then builds with. The result is
    also written into the saved ``draft``, so a page refresh loses nothing."""
    mode = str(mode or "quick").strip()
    if mode not in wgquestions.MODES:
        raise ValueError(f"unknown mode {mode!r}; use one of {list(wgquestions.MODES)}")
    idea = str(idea or "").strip()
    if mode == "quick" and not idea:
        raise ValueError("quick mode needs the idea first")
    entry = _checked_provider(provider)
    answers = wgquestions.sanitize_answers(mode, answers)
    population = wgquestions.sanitize_population(population)
    clarify = _clean_clarify(clarify)
    notes = wgquestions.sanitize_notes(notes)
    draft = _checked_draft_id(draft) if draft else None
    out_dir = _fresh_out_dir("frame-" + (idea or mode))

    def target(update, j):
        update(outDir=str(out_dir), logDir=str(out_dir / "llm"))
        out_dir.mkdir(parents=True, exist_ok=True)
        r = wgapi.frame(mode, idea=idea, answers=answers, population=population,
                        clarify=clarify, notes=notes, provider=entry["name"],
                        log_dir=str(out_dir / "llm"),
                        progress=lambda e: update(phase=e.get("phase"), label=e.get("label"),
                                                  calls=e.get("calls", 0),
                                                  tokens=e.get("tokens", 0)))
        update(frame=r["frame"], questions=r["questions"], label="the world frame")
        if draft:
            # new questions clear the old answers; a frame clears the questions
            _merge_draft(draft, {
                "frame": r["frame"], "framedMode": mode if r["frame"] else None,
                "summary": (r["frame"] or {}).get("summary"),
                "questions": r["questions"] or None,
                "clarifyAnswers": None if r["questions"] else
                _read_draft(draft).get("clarifyAnswers")})

    return _start("frame", {"label": f"the {mode} frame", "idea": idea or None, "draft": draft},
                  target)


# ---------------------------------------------------------------- drafts
# The dialog's state (form, answers, the model's questions, the frame) saved
# as out/drafts/<id>.json, so a refresh or a closed dialog can bring it back.
_draft_lock = threading.Lock()
MAX_DRAFT_BYTES = 200_000


def _drafts_dir():
    return OUT_ROOT / "drafts"


def _checked_draft_id(draft_id):
    draft_id = str(draft_id or "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", draft_id):
        raise ValueError(f"bad draft id {draft_id!r}")
    return draft_id


def _read_draft(draft_id):
    path = _drafts_dir() / f"{_checked_draft_id(draft_id)}.json"
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _merge_draft(draft_id, fields):
    """Merge ``fields`` into the draft (None removes a key) and stamp it."""
    with _draft_lock:
        d = _read_draft(draft_id)
        for k, v in fields.items():
            if v is None:
                d.pop(k, None)
            else:
                d[k] = v
        d["id"] = draft_id
        d["saved"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        text = json.dumps(d, indent=1, ensure_ascii=False)
        if len(text.encode("utf-8")) > MAX_DRAFT_BYTES:
            raise ValueError("the draft is too large to save")
        _drafts_dir().mkdir(parents=True, exist_ok=True)
        tmp = _drafts_dir() / f"{draft_id}.json.tmp"
        tmp.write_text(text, "utf-8")
        tmp.replace(_drafts_dir() / f"{draft_id}.json")
        return d


# what the page may save; the frame and the run are the server's to write
_DRAFT_FORM_KEYS = ("mode", "idea", "answers", "notes", "population", "provider", "seed",
                    "extensions", "summary", "clarifyAnswers")


def save_draft(draft_id, form):
    if not isinstance(form, dict):
        raise ValueError("the draft must be an object")
    fields = {k: form.get(k) for k in _DRAFT_FORM_KEYS if k in form}
    if form.get("clearFrame"):     # the form changed under the frame: drop it
        fields.update(frame=None, framedMode=None, questions=None, clarifyAnswers=None,
                      summary=None)
    return _merge_draft(_checked_draft_id(draft_id), fields)


def get_draft(draft_id):
    d = _read_draft(draft_id)
    if not d:
        raise LookupError(f"no draft {draft_id!r}")
    return d


def delete_draft(draft_id):
    path = _drafts_dir() / f"{_checked_draft_id(draft_id)}.json"
    if not path.is_file():
        raise LookupError(f"no draft {draft_id!r}")
    path.unlink()


def list_drafts():
    """The saved drafts, newest first, as one-line summaries."""
    out = []
    for path in (_drafts_dir().glob("*.json") if _drafts_dir().is_dir() else ()):
        try:
            d = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        frame = d.get("frame") or {}
        title = (d.get("idea") or frame.get("premise") or "").strip() or "(no idea text)"
        run = d.get("run") or {}
        out.append({"id": path.stem, "saved": d.get("saved", ""), "mode": d.get("mode", "quick"),
                    "title": title[:120], "framed": bool(frame),
                    "questions": bool(d.get("questions")),
                    "generated": bool(run.get("source")),
                    "running": bool(run) and not run.get("source")})
    out.sort(key=lambda d: d["saved"], reverse=True)
    return out


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
