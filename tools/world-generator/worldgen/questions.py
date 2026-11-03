"""The World Frame question bank: plain data in ``questions.json``, loaded and
checked here so the launcher, the editor dialog and the P0 prompt all see the
same questions, options and feeds.

Every question can be skipped, and every question has an implicit **Other**
choice with free text — the bank records neither; the UI adds them. A
``free`` question takes text only. ``multi`` allows up to that many choices.

The population range sits beside every form, quick included: a default of
20-40 residents (the game's own default) clamped to the bank's allowed range.

An answer is ``{question id: {"choices": [...], "other": "text"}}`` — the
chosen option labels (empty for Other-only or skipped) and any free text.
"""
import json
import os

BANK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "questions.json")

MODES = ("quick", "short", "medium", "long")
MAX_OTHER_CHARS = 400          # free text is a steer, not an essay
MAX_NOTES_CHARS = 6000         # "Other instructions" may hold a plot outline


def sanitize_notes(notes):
    """The form's "Other instructions or requests" box: plain text, trimmed,
    capped at MAX_NOTES_CHARS; "" when empty or not text."""
    return notes.strip()[:MAX_NOTES_CHARS] if isinstance(notes, str) else ""


def _check_bank(bank, path):
    """Fail loudly on a malformed bank: modes, ids, options, feeds."""
    if not isinstance(bank, dict):
        raise ValueError(f"{path}: the bank must be a JSON object")
    pop = bank.get("population")
    if not (isinstance(pop, dict) and isinstance(pop.get("default"), list)
            and len(pop["default"]) == 2
            and all(isinstance(v, int) for v in pop["default"])
            and isinstance(pop.get("min"), int) and isinstance(pop.get("max"), int)
            and pop["min"] <= min(pop["default"]) <= max(pop["default"]) <= pop["max"]):
        raise ValueError(f"{path}: population needs default [lo, hi] inside min..max")
    ids = set()
    for section in ("short", "medium"):
        questions = bank.get(section)
        if not isinstance(questions, list) or not questions:
            raise ValueError(f"{path}: {section} must be a non-empty list of questions")
        for q in questions:
            if not isinstance(q, dict) or not isinstance(q.get("id"), str) \
                    or not q["id"].strip():
                raise ValueError(f"{path}: every {section} question needs an id")
            if q["id"] in ids:
                raise ValueError(f"{path}: question id {q['id']!r} used twice")
            ids.add(q["id"])
            if not isinstance(q.get("prompt"), str) or not q["prompt"].strip():
                raise ValueError(f"{path}: question {q['id']!r} needs a prompt")
            options = q.get("options", [])
            if not q.get("free"):
                if not isinstance(options, list) or not options \
                        or not all(isinstance(o, str) and o.strip() for o in options):
                    raise ValueError(f"{path}: question {q['id']!r} needs options"
                                     f" (or \"free\": true)")
            if "Other" in options:
                raise ValueError(f"{path}: question {q['id']!r} lists 'Other'; it is implicit")
            multi = q.get("multi", 1)
            if not isinstance(multi, int) or multi < 1:
                raise ValueError(f"{path}: question {q['id']!r}: multi must be 1 or more")
            if not isinstance(q.get("feeds"), list) or not q["feeds"]:
                raise ValueError(f"{path}: question {q['id']!r} needs a feeds list")
    return bank


def load_bank(path=BANK_PATH):
    """The parsed and checked question bank."""
    with open(path, "r", encoding="utf-8") as f:
        return _check_bank(json.load(f), path)


def form_questions(mode, path=BANK_PATH):
    """The questions of one form: ``quick`` asks none, ``short`` is the seven,
    ``medium`` and ``long`` are those seven plus the seven deeper ones (long
    adds a clarifying model turn in P0, not more questions)."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; use one of {list(MODES)}")
    if mode == "quick":
        return []
    bank = load_bank(path)
    questions = list(bank["short"])
    if mode in ("medium", "long"):
        questions += list(bank["medium"])
    return questions


def population_limits(path=BANK_PATH):
    """(default [lo, hi], min, max) from the bank."""
    pop = load_bank(path)["population"]
    return list(pop["default"]), pop["min"], pop["max"]


def sanitize_population(pair=None, path=BANK_PATH):
    """A resident range as [lo, hi]: the default when nothing usable was
    given, clamped to the bank's allowed range, low before high."""
    default, lo_min, hi_max = population_limits(path)
    if isinstance(pair, (list, tuple)) and len(pair) == 2:
        try:
            lo, hi = int(pair[0]), int(pair[1])
        except (TypeError, ValueError):
            return list(default)
    else:
        return list(default)
    lo, hi = max(lo_min, min(hi_max, lo)), max(lo_min, min(hi_max, hi))
    return [min(lo, hi), max(lo, hi)]


def sanitize_answers(mode, answers, path=BANK_PATH):
    """Keep only what this form can carry: known question ids, choices from
    that question's options only (Other never appears as a choice — its text
    lives in ``other``), the multi cap, free text trimmed to a steer. A
    skipped question simply has no entry."""
    questions = {q["id"]: q for q in form_questions(mode, path)}
    out = {}
    for qid, answer in (answers or {}).items():
        q = questions.get(qid)
        if q is None:
            continue
        if not isinstance(answer, dict):
            answer = {"choices": [answer] if isinstance(answer, str) else [], "other": ""}
        options = q.get("options", [])
        cap = q.get("multi", 1)
        choices = []
        for c in (answer.get("choices") or []):
            if isinstance(c, str) and c in options and c not in choices:
                choices.append(c)
            if len(choices) >= cap:
                break
        other = answer.get("other")
        other = other.strip()[:MAX_OTHER_CHARS] if isinstance(other, str) else ""
        if choices or other:
            out[qid] = {"choices": choices, "other": other}
    return out


def answer_line(q, answer):
    """One question's answers as prompt text: the chosen options, an Other
    note, or 'skipped' — so P0 sees exactly what the user picked."""
    answer = answer if isinstance(answer, dict) else {}
    bits = list(answer.get("choices") or [])
    other = (answer.get("other") or "").strip()
    if other:
        bits.append(f"Other: {other}")
    return f"{q['prompt']} " + ("; ".join(bits) if bits else "(skipped)")


def render_answers(mode, answers, path=BANK_PATH):
    """The whole form as prompt lines, in the bank's order (empty for quick)."""
    lines = []
    for q in form_questions(mode, path):
        lines.append(f"- {answer_line(q, (answers or {}).get(q['id'], {}))}")
    return lines
