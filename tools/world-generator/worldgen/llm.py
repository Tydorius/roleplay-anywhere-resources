"""OpenAI-compatible chat-completions client, standard library only (urllib).

Providers come from ``providers.json`` at the repository root (gitignored):
each entry has ``base_url``, ``api_key``, ``model`` and ``max_tokens``, and may
set ``timeout`` (seconds to wait for one reply) and ``rate_limit_wait`` (seconds
to wait out a busy provider per request). Keys are never logged, printed or
written to a call record.

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
import socket
import time
import urllib.error
import urllib.request

PROVIDERS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "providers.json")
# seconds for one reply, unless the provider sets "timeout". Replies aren't
# streamed, so nothing arrives until the model finishes: a 27B model at 19
# tokens/s spent 27 minutes on one catalogue reply, which 600 would have failed
# three times over, ending the run
REQUEST_TIMEOUT = 1800
# a provider that answers 429 or 5xx is waited out, up to this many seconds per
# request unless it sets "rate_limit_wait". Free models are often rate-limited
# upstream: three instant retries ended a run in half a second, before the model
# saw a word, with an error that read as if the model had failed
RATE_LIMIT_WAIT = 900
BUSY_CODES = (408, 429, 500, 502, 503, 504)
BUSY_FIRST_PAUSE, BUSY_LONGEST_PAUSE = 5, 120   # seconds, doubling between them
MAX_TOKENS_CEILING = 65536   # how far a reply cut off at the budget may double it
# phases whose reply can't fit the provider's usual budget. P2's catalogue hit
# 16000 in half the live runs, reasoning included, and came back cut off
PHASE_BUDGETS = {"p2": 32000, "p2-items": 32000}


class LLMError(Exception):
    pass


class HTTPStatusError(LLMError):
    """The provider answered with an error status."""

    def __init__(self, message, code, retry_after=None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


class ProviderBusy(LLMError):
    """The provider stayed rate-limited or down past the wait. It ends the run:
    the model was never asked, so nothing downstream can be salvaged."""


def _retry_after(headers):
    """A Retry-After header in seconds; the date form counts as absent."""
    try:
        return max(0, int((headers or {}).get("Retry-After", "")))
    except (TypeError, ValueError):
        return None


def _seconds(cfg, key):
    """A provider's optional seconds setting, or None when it isn't set."""
    v = cfg.get(key)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
        raise LLMError(f"provider setting {key!r} must be a number of seconds, not {v!r}")
    return v


def _scrub(value):
    """``value`` with lone surrogates removed from its strings, in place for
    lists and dicts. A model can write one as a JSON escape; it parses, then
    can't be written as UTF-8, which crashed a run 77 minutes in."""
    if isinstance(value, str):
        return value.encode("utf-8", "ignore").decode("utf-8")
    if isinstance(value, list):
        value[:] = [_scrub(v) for v in value]
    elif isinstance(value, dict):
        for k in list(value):
            item = _scrub(value.pop(k))
            value[_scrub(k)] = item
    return value

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
        error = f"the reply is not valid JSON: {e.msg} (line {e.lineno})"
    # deeply nested replies (perk trees) sometimes close their brackets in
    # the wrong order, the same way on every retry: rebalance them and let
    # the phase's own checks judge the result
    try:
        return json.loads(repair_brackets(t[start:end + 1])), None
    except json.JSONDecodeError:
        return None, error


def repair_brackets(t):
    """Rebalance ``{ } [ ]`` outside strings: a closer that does not match
    the innermost open bracket closes the open ones down to its match (or is
    dropped when nothing open matches it), and missing closers are added at
    the end."""
    out, stack, in_str, esc = [], [], False, False
    opener = {"}": "{", "]": "["}
    closer = {"{": "}", "[": "]"}
    for ch in t:
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if opener[ch] not in stack:
                continue
            while stack[-1] != opener[ch]:
                out.append(closer[stack.pop()])
            stack.pop()
        out.append(ch)
    out.extend(closer[c] for c in reversed(stack))
    return "".join(out)


class Client:
    """One provider, one run. ``call()`` never raises on model/contract
    failures; it returns the parsed object from the last attempt that
    produced JSON (even when a contract check failed on it, so the caller can
    drop just the bad entries), or None when no attempt parsed. Transport
    errors are retried like any other failure, except ProviderBusy, which
    ends the run once the wait runs out."""

    last_cut = False   # the last call ended on a reply that ran out of budget
    last_error = None  # why the last attempt got no reply, for the run's error
    timeout = None           # seconds for one reply; None is REQUEST_TIMEOUT
    rate_limit_wait = None   # seconds to wait out a busy provider; None is RATE_LIMIT_WAIT
    on_wait = None     # called about once a second during a wait; may raise to stop it

    def __init__(self, provider, providers_path=PROVIDERS_PATH, log_dir=None):
        cfg = load_provider(provider, providers_path)
        self.provider = provider
        self.base_url = cfg["base_url"].rstrip("/")
        self.model = cfg["model"]
        self.max_tokens = int(cfg.get("max_tokens", 16000))
        self.timeout = _seconds(cfg, "timeout")
        self.rate_limit_wait = _seconds(cfg, "rate_limit_wait")
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
        budget = max(self.max_tokens, PHASE_BUDGETS.get(phase, 0))
        cut = False
        self.last_error = None
        for attempt in range(1, max_retries + 2):
            if attempt > 1:
                self.retries += 1
            try:
                raw, usage = self._request(messages, budget)
                transport_error = None
            except ProviderBusy as e:
                record["attempts"].append({
                    "attempt": attempt, "messages": [dict(m) for m in messages],
                    "raw_reply": "", "parsed": None, "errors": [str(e)], "usage": {},
                    "max_tokens": budget})
                record["seconds"] = round(time.time() - t0, 3)
                self.seconds += record["seconds"]
                self._write_log(phase, record)
                raise
            except LLMError as e:
                raw, usage, transport_error = "", {}, str(e)
            # a reply that ran out of budget, whether it's empty (a reasoning
            # model thinking past it) or stops mid-item: the bracket repair
            # would close the stump into valid JSON and lose the rest, so it
            # never counts, and the same messages go again with twice the budget
            cut = not transport_error and (
                usage.get("finish") == "length"
                or int(usage.get("completion", 0) or 0) >= budget)
            parsed, parse_error = extract_json(raw)
            parsed = _scrub(parsed)
            self.last_error = transport_error
            errors = []
            if transport_error:
                errors.append(f"the request failed: {transport_error}")
            elif cut:
                errors.append(f"the reply was cut off at the {budget}-token limit")
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
                "max_tokens": budget,
            })
            for k in ("prompt", "completion", "total"):
                record["tokens"][k] += int(usage.get(k, 0) or 0)
            if not errors:
                result, ok = parsed, True
                break
            if attempt <= max_retries and cut:
                budget = min(budget * 2, MAX_TOKENS_CEILING)
            elif attempt <= max_retries:
                messages = messages + [
                    {"role": "assistant", "content": raw or "(no reply)"},
                    {"role": "user", "content":
                     "Your reply had problems:\n- " + "\n- ".join(errors)
                     + "\nReply again with ONE corrected JSON object and nothing else."},
                ]
        self.last_cut = cut and not ok
        record["seconds"] = round(time.time() - t0, 3)
        record["ok"] = ok
        record["result"] = result if ok else last_parsed
        self.seconds += record["seconds"]
        for k in ("prompt", "completion", "total"):
            self.tokens[k] += record["tokens"][k]
        self._write_log(phase, record)
        return record["result"]

    def _request(self, messages, max_tokens=None):
        """One reply, waiting out a busy provider: a 429 or 5xx is tried again
        after a pause (the provider's Retry-After when it's longer), until
        the wait runs out and ProviderBusy ends the run."""
        limit = RATE_LIMIT_WAIT if self.rate_limit_wait is None else self.rate_limit_wait
        waited, pause = 0, BUSY_FIRST_PAUSE
        while True:
            try:
                return self._post(messages, max_tokens)
            except HTTPStatusError as e:
                if e.code not in BUSY_CODES:
                    raise
                if waited >= limit:
                    raise ProviderBusy(
                        f"{self.model} on provider {self.provider!r} stayed busy or "
                        f"rate-limited (HTTP {e.code}) for {round(waited / 60, 1)} minutes, so "
                        f"the model never answered. That is the provider, not the model: try "
                        f"again later, pick another model, or raise \"rate_limit_wait\" in "
                        f"providers.json. Last reply: {str(e)[:200]}")
                length = min(max(pause, e.retry_after or 0), BUSY_LONGEST_PAUSE)
                self._wait(length, e.code, waited, limit)
                waited += length
                pause = min(pause * 2, BUSY_LONGEST_PAUSE)

    def _wait(self, length, code, waited, limit):
        """Sleep ``length`` seconds in short steps, so ``on_wait`` can report
        the wait and a cancelled run needn't sit it out."""
        left, first = length, True
        while left > 0:
            if self.on_wait is not None:
                self.on_wait({"code": code, "pause": length, "waited": waited,
                              "limit": limit, "first": first})
            first = False
            step = min(1, left)
            time.sleep(step)
            left -= step

    def _post(self, messages, max_tokens=None):
        """POST /chat/completions. Returns (content, usage); raises LLMError."""
        body = json.dumps({"model": self.model, "messages": messages,
                           "max_tokens": max_tokens or self.max_tokens}).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/chat/completions", data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self._api_key})
        timeout = self.timeout or REQUEST_TIMEOUT
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:500]
            except Exception:
                pass
            raise HTTPStatusError(f"HTTP {e.code}: {detail or e.reason}", e.code,
                                  _retry_after(e.headers))
        except urllib.error.URLError as e:
            raise LLMError(f"cannot reach the provider: {e.reason}")
        except (ValueError, KeyError) as e:
            raise LLMError(f"malformed provider response: {e}")
        except (TimeoutError, socket.timeout):
            raise LLMError(f"no reply within {timeout}s; a slow model may need a bigger "
                           f"\"timeout\" in providers.json")
        except OSError as e:
            # a dropped connection: retried like any failed request
            raise LLMError(f"the connection failed: {e!r}")
        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise LLMError("the response has no choices[0].message.content")
        usage = data.get("usage") or {}
        u = {"prompt": usage.get("prompt_tokens"),
             "completion": usage.get("completion_tokens"),
             "total": usage.get("total_tokens"),
             "finish": data["choices"][0].get("finish_reason")}
        return content, {k: v for k, v in u.items() if v is not None}

    # -------------------------------------------------------------- logging

    def _write_log(self, phase, record):
        if not self.log_dir:
            return
        os.makedirs(self.log_dir, exist_ok=True)
        slug = re.sub(r"[^a-z0-9-]+", "-", phase.lower()).strip("-")
        path = os.path.join(self.log_dir, f"{self.calls:02d}-{slug or 'call'}.json")
        tmp = path + ".tmp"
        # raw replies keep what the model sent, lone surrogates included
        with open(tmp, "w", encoding="utf-8", errors="backslashreplace") as f:
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
        busy = (" (the provider is rate-limited or busy right now; a run waits this out, "
                "but on a free model it can last hours)") if e.code in BUSY_CODES else ""
        return {"ok": False, "provider": name, "model": cfg["model"],
                "error": f"HTTP {e.code}{busy}: {detail or e.reason}"}
    except urllib.error.URLError as e:
        return {"ok": False, "provider": name, "model": cfg["model"],
                "error": f"cannot reach the provider: {e.reason}"}
    except OSError as e:
        # a read timeout (TimeoutError / socket.timeout) or a dropped connection
        return {"ok": False, "provider": name, "model": cfg["model"],
                "error": f"no reply within {CHECK_TIMEOUT}s ({e or type(e).__name__}); a local "
                         f"server may be busy with another request or still loading the model"}
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
