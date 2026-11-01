"""OpenAI-compatible chat-completions client, standard library only (urllib).

Providers come from ``providers.json`` at the repository root (gitignored):
each entry has ``base_url``, ``api_key``, ``model`` and ``max_tokens``. Keys
are never logged, printed or written to a call record.

Every phase call goes through :func:`Client.call`, which extracts one JSON
object from the reply, checks it against a contract, and on bad JSON or a
failed check retries (twice by default) with the error fed back to the model.
Each call is logged to ``<log_dir>/NN-<phase>.json`` with the messages, the
raw replies, the parsed result, durations, token usage and the errors. These
are reasoning models: the provider's ``max_tokens`` is always sent, and only
``message.content`` is read.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

PROVIDERS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "providers.json")
REQUEST_TIMEOUT = 600   # seconds; one reasoning reply can take minutes


class LLMError(Exception):
    pass

PLACEHOLDER_KEY = "YOUR_API_KEY"   # the example file's stand-in for a real key


def load_provider(name, path=PROVIDERS_PATH):
    """One provider's config from providers.json. Never prints the key."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        raise LLMError(
            f"cannot read providers file {path}: {e}\n"
            f"copy providers.example.json to providers.json and fill in your key")
    entry = data.get(name)
    if not isinstance(entry, dict):
        known = ", ".join(sorted(list_providers(path))) or "none"
        raise LLMError(f"provider {name!r} not in {path} (configured: {known})")
    for key in ("base_url", "api_key", "model"):
        if not entry.get(key):
            raise LLMError(f"provider {name!r}: missing {key}")
    if entry["api_key"] == PLACEHOLDER_KEY:
        raise LLMError(f"provider {name!r}: api_key is still the example "
                       f"placeholder; put your real key in {path}")
    return entry


def list_providers(path=PROVIDERS_PATH):
    """The configured provider names (entries starting with '_' are notes)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    return [k for k, v in data.items()
            if not k.startswith("_") and isinstance(v, dict)]


def extract_json(text):
    """(object, error). One JSON object per reply: code fences are stripped
    and the outermost ``{...}`` is taken, so plain, fenced and chatter-wrapped
    replies all parse."""
    if text is None or not text.strip():
        return None, "the reply is empty"
    t = text.strip()
    m = re.search(r"```[a-zA-Z]*\s*(.*?)```", t, re.DOTALL)
    if m and "{" in m.group(1):
        t = m.group(1).strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None, "the reply contains no JSON object"
    try:
        return json.loads(t[start:end + 1]), None
    except json.JSONDecodeError as e:
        return None, f"the reply is not valid JSON: {e.msg} (line {e.lineno})"


class Client:
    """One provider, one run. ``call()`` never raises on model/contract
    failures; it returns the parsed object from the last attempt that
    produced JSON (even when a contract check failed on it, so the caller can
    drop just the bad entries), or None when no attempt parsed. Transport
    errors are retried like any other failure."""

    def __init__(self, provider, providers_path=PROVIDERS_PATH, log_dir=None):
        cfg = load_provider(provider, providers_path)
        self.provider = provider
        self.base_url = cfg["base_url"].rstrip("/")
        self.model = cfg["model"]
        self.max_tokens = int(cfg.get("max_tokens", 16000))
        self._api_key = cfg["api_key"]
        self.log_dir = log_dir
        self.calls = 0
        self.retries = 0
        self.tokens = {"prompt": 0, "completion": 0, "total": 0}
        self.seconds = 0.0

    # ------------------------------------------------------------ one call

    def call(self, phase, system, user, validate=None, max_retries=2):
        """Run one phase call. ``validate(parsed) -> [errors]``; an empty
        list accepts the result. Returns the accepted object, or the last
        parsed object when checks kept failing (the caller drops bad
        entries), or None when no attempt produced JSON."""
        self.calls += 1
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        record = {"phase": phase, "model": self.model, "attempts": [],
                  "result": None, "ok": False, "seconds": 0.0,
                  "tokens": {"prompt": 0, "completion": 0, "total": 0}}
        t0 = time.time()
        result, last_parsed, ok = None, None, False
        for attempt in range(1, max_retries + 2):
            if attempt > 1:
                self.retries += 1
            try:
                raw, usage = self._request(messages)
                transport_error = None
            except LLMError as e:
                raw, usage, transport_error = "", {}, str(e)
            parsed, parse_error = extract_json(raw)
            errors = []
            if transport_error:
                errors.append(f"the request failed: {transport_error}")
            elif parse_error:
                errors.append(parse_error)
            elif validate is not None:
                errors = [str(e) for e in validate(parsed)]
            if parsed is not None:
                last_parsed = parsed
            record["attempts"].append({
                "attempt": attempt,
                "messages": [dict(m) for m in messages],
                "raw_reply": raw,
                "parsed": parsed,
                "errors": errors,
                "usage": usage,
            })
            for k in ("prompt", "completion", "total"):
                record["tokens"][k] += int(usage.get(k, 0) or 0)
            if not errors:
                result, ok = parsed, True
                break
            if attempt <= max_retries:
                messages = messages + [
                    {"role": "assistant", "content": raw or "(no reply)"},
                    {"role": "user", "content":
                     "Your reply had problems:\n- " + "\n- ".join(errors)
                     + "\nReply again with ONE corrected JSON object and nothing else."},
                ]
        record["seconds"] = round(time.time() - t0, 3)
        record["ok"] = ok
        record["result"] = result if ok else last_parsed
        self.seconds += record["seconds"]
        for k in ("prompt", "completion", "total"):
            self.tokens[k] += record["tokens"][k]
        self._write_log(phase, record)
        return record["result"]

    def _request(self, messages):
        """POST /chat/completions. Returns (content, usage); raises LLMError."""
        body = json.dumps({"model": self.model, "messages": messages,
                           "max_tokens": self.max_tokens}).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/chat/completions", data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self._api_key})
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:500]
            except Exception:
                pass
            raise LLMError(f"HTTP {e.code}: {detail or e.reason}")
        except urllib.error.URLError as e:
            raise LLMError(f"cannot reach the provider: {e.reason}")
        except (ValueError, KeyError) as e:
            raise LLMError(f"malformed provider response: {e}")
        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise LLMError("the response has no choices[0].message.content")
        usage = data.get("usage") or {}
        u = {"prompt": usage.get("prompt_tokens"),
             "completion": usage.get("completion_tokens"),
             "total": usage.get("total_tokens")}
        return content, {k: v for k, v in u.items() if v is not None}

    # -------------------------------------------------------------- logging

    def _write_log(self, phase, record):
        if not self.log_dir:
            return
        os.makedirs(self.log_dir, exist_ok=True)
        slug = re.sub(r"[^a-z0-9-]+", "-", phase.lower()).strip("-")
        path = os.path.join(self.log_dir, f"{self.calls:02d}-{slug or 'call'}.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=1, ensure_ascii=False)
        os.replace(tmp, path)


CHECK_TIMEOUT = 60        # seconds; the check request is one tiny call
CHECK_MAX_TOKENS = 1024   # reasoning models think before they answer "ok"


def check_provider(name, providers_path=PROVIDERS_PATH):
    """Send one tiny request through a provider and report what answered.

    Returns a report dict (``ok``, ``provider``, ``model``, ``seconds``,
    ``reply`` on success; ``error`` on failure). The api key is never part
    of the report."""
    cfg = load_provider(name, providers_path)
    base_url = cfg["base_url"].rstrip("/")
    body = json.dumps({"model": cfg["model"],
                       "messages": [{"role": "user",
                                     "content": "Reply with exactly: ok"}],
                       "max_tokens": CHECK_MAX_TOKENS}).encode("utf-8")
    req = urllib.request.Request(
        base_url + "/chat/completions", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + cfg["api_key"]})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=CHECK_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        return {"ok": False, "provider": name, "model": cfg["model"],
                "error": f"HTTP {e.code}: {detail or e.reason}"}
    except urllib.error.URLError as e:
        return {"ok": False, "provider": name, "model": cfg["model"],
                "error": f"cannot reach the provider: {e.reason}"}
    except (ValueError, KeyError) as e:
        return {"ok": False, "provider": name, "model": cfg["model"],
                "error": f"malformed provider response: {e}"}
    seconds = round(time.time() - t0, 2)
    report = {"ok": True, "provider": name, "model": cfg["model"],
              "seconds": seconds}
    if isinstance(data.get("model"), str):
        report["served_model"] = data["model"]
    try:
        reply = (data["choices"][0]["message"].get("content") or "").strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        reply = ""
    report["reply"] = reply[:80]
    usage = data.get("usage") or {}
    if usage.get("total_tokens") is not None:
        report["tokens"] = usage["total_tokens"]
    return report
