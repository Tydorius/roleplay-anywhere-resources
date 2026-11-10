"""World settings files: everything a person chose for one world, in one small
JSON file they can send to someone else, who loads it to run the same world.

The launcher, the CLI and the Scenario Editor all read and write this format,
and every generation writes one as ``settings.json`` in its run folder. It
holds the form (mode, idea, questionnaire answers, notes, residents), the
build choices (seed, extensions, room library) and, when there is one, the
approved World Frame, so a re-run can skip framing. The model name is kept as
a note only. No provider name, URL or API key is ever written.

  data = settings.make(mode="short", idea="a mill town", answers={...}, seed=3)
  settings.write(path, data)
  data = settings.read(path)        # checked; raises SettingsError when unusable
"""
import json
import os
from datetime import datetime

from . import questions as questions_mod
from .extensions import REGISTRY, expand

KIND = "anywhere-rpg-world-settings"
VERSION = 1
FILE_NAME = "settings.json"
MAX_BYTES = 300_000
MAX_IDEA_CHARS = 2000


class SettingsError(ValueError):
    """A settings file that can't be used, with a message for the person."""


def make(mode="quick", idea="", answers=None, population=None, notes="", seed=1,
         extensions=(), library=True, frame=None, clarify=None, model=None):
    """A settings dict, checked the same way a loaded file is."""
    data = {"kind": KIND, "version": VERSION,
            "saved": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": mode, "idea": idea or "", "answers": answers or {},
            "population": population, "notes": notes or "", "seed": seed,
            "extensions": list(extensions or ()), "library": bool(library)}
    if frame:
        data["frame"] = frame
    if clarify:
        data["clarify"] = clarify
    if model:
        data["model"] = str(model)
    return check(data)


def from_run(idea, seed, extensions, library, frame=None, questionnaire=None, model=None):
    """The settings of one generate() call."""
    q = questionnaire or {}
    return make(mode=q.get("mode") or "quick", idea=idea, answers=q.get("answers"),
                population=q.get("population"), notes=q.get("notes") or "", seed=seed,
                extensions=extensions, library=library, frame=frame, model=model)


def check(data):
    """A clean copy of a settings dict, or SettingsError saying what is wrong.
    Unknown questions and options are dropped the way the forms drop them;
    an unknown extension or a wrong type is an error."""
    if not isinstance(data, dict):
        raise SettingsError("a settings file holds one JSON object")
    if data.get("kind") != KIND:
        raise SettingsError("this isn't a world settings file (it has no "
                            f"\"kind\": \"{KIND}\")")
    try:
        version = int(data.get("version", 0))
    except (TypeError, ValueError):
        version = 0
    if version < 1:
        raise SettingsError("the settings file has no usable \"version\"")
    if version > VERSION:
        raise SettingsError(f"the settings file is version {version}, newer than this "
                            f"generator reads ({VERSION}); update the generator")
    mode = str(data.get("mode") or "quick").strip()
    if mode not in questions_mod.MODES:
        raise SettingsError(f"unknown mode {mode!r}; use one of {list(questions_mod.MODES)}")
    idea = data.get("idea") or ""
    if not isinstance(idea, str):
        raise SettingsError("\"idea\" must be text")
    answers = data.get("answers") or {}
    if not isinstance(answers, dict):
        raise SettingsError("\"answers\" must be an object of question id -> answer")
    try:
        seed = int(data.get("seed", 1))
    except (TypeError, ValueError):
        raise SettingsError("\"seed\" must be a whole number")
    exts = data.get("extensions") or []
    if not isinstance(exts, list) or not all(isinstance(e, str) for e in exts):
        raise SettingsError("\"extensions\" must be a list of extension ids")
    unknown = sorted(set(exts) - {e.id for e in REGISTRY})
    if unknown:
        raise SettingsError(f"unknown extension(s) {unknown}; this generator has "
                            f"{sorted(e.id for e in REGISTRY)}")
    frame = data.get("frame")
    if frame is not None and not (isinstance(frame, dict)
                                  and isinstance(frame.get("summary"), str)):
        raise SettingsError("\"frame\" must be a World Frame object with a summary")
    clarify = data.get("clarify") or []
    if not isinstance(clarify, list) or not all(
            isinstance(c, dict) and isinstance(c.get("question"), str)
            and isinstance(c.get("answer"), str) for c in clarify):
        raise SettingsError("\"clarify\" must be a list of {question, answer}")
    out = {"kind": KIND, "version": VERSION, "saved": str(data.get("saved") or ""),
           "mode": mode, "idea": idea.strip()[:MAX_IDEA_CHARS],
           "answers": questions_mod.sanitize_answers(mode, answers),
           "population": questions_mod.sanitize_population(data.get("population")),
           "notes": questions_mod.sanitize_notes(data.get("notes")),
           "seed": seed, "extensions": sorted(expand(exts)),
           "library": bool(data.get("library", True))}
    if not (out["idea"] or out["answers"] or frame):
        raise SettingsError("the settings have no idea, no answers and no frame: "
                            "nothing to build a world from")
    if frame is not None:
        out["frame"] = frame
    if clarify:
        out["clarify"] = clarify
    if isinstance(data.get("model"), str) and data["model"]:
        out["model"] = data["model"][:200]
    return out


def questionnaire(data):
    """The generate() questionnaire for checked settings (None for a quick
    world with no answers, as the CLI's plain --idea runs have)."""
    if data["mode"] == "quick" and not data["answers"] and not data["notes"]:
        return None
    q = {"mode": data["mode"], "answers": data["answers"], "population": data["population"]}
    if data["notes"]:
        q["notes"] = data["notes"]
    return q


def label(data):
    """A short name for the world, for folder names and lists."""
    frame = data.get("frame") or {}
    text = data.get("idea") or frame.get("premise") or next(
        (a.get("other") for a in data.get("answers", {}).values() if a.get("other")), "")
    return (text or "world").strip()


def dumps(data):
    return json.dumps(check(data), indent=1, ensure_ascii=False) + "\n"


def loads(text):
    if isinstance(text, bytes):
        text = text.decode("utf-8-sig")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise SettingsError(f"the settings file is larger than {MAX_BYTES // 1000} kB")
    try:
        data = json.loads(text)
    except ValueError as e:
        raise SettingsError(f"the settings file isn't valid JSON: {e}")
    return check(data)


def write(path, data):
    text = dumps(data)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)
    return path


def read(path):
    try:
        with open(path, "rb") as f:
            return loads(f.read())
    except OSError as e:
        raise SettingsError(f"cannot read {path}: {e}")
