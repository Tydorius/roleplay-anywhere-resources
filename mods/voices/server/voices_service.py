#!/usr/bin/env python3
"""
voices-service - OpenAI-compatible TTS endpoint with a named voice registry,
in front of an mlx-audio server running Fish Audio Drama 3 (voice cloning)
and Qwen3-TTS VoiceDesign (voices described in plain English).

POST /v1/audio/speech  {"model": "drama3", "input": "...", "voice": "orion",
                        "response_format": "mp3"|"wav"}
    -> audio bytes, generated in the named voice
GET  /v1/audio/voices   -> registry
GET  /health

Delivery cues: "(sighs)" or "[sighs]" (one or two words) in the input. Drama 3
voices get them as "[sighs]" moved to the end of the line: a cue at the start
of a line ran away 8/15 times, at the end 0/15. qwen_voicedesign voices get
them removed from the text and added to the voice description, since that
engine reads them aloud.

Length guard: Drama 3 sometimes runs away on a line (repeats or garbage up to
the token cap, worst with cues). Each clip is measured against an expected
length (3s + 0.6s/word + 2s/cue) and generation is capped just above it; an
over-long clip is regenerated up to twice without its cues, and the shortest
attempt is returned if all three fail.

Configuration (environment variables):
  VOICES_REGISTRY        path to the registry JSON (see voices.example.json)
  VOICES_BACKEND         mlx-audio speech URL (default http://localhost:8000/v1/audio/speech)
  VOICES_BACKEND_MODEL   Drama 3 model id (default mlx-community/fish-audio-drama-3-4bit)

Run: uvicorn voices_service:app --host 0.0.0.0 --port 8020
"""
import json
import math
import os
import pathlib
import re
import sys
import urllib.request

import miniaudio
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

BACKEND = os.environ.get("VOICES_BACKEND", "http://localhost:8000/v1/audio/speech")
BACKEND_MODEL = os.environ.get("VOICES_BACKEND_MODEL", "mlx-community/fish-audio-drama-3-4bit")
REGISTRY_PATH = pathlib.Path(os.environ.get("VOICES_REGISTRY", "voices.json"))

CUE_RE = re.compile(r"[\[(]\s*([A-Za-z]+(?: [A-Za-z]+)?)\s*[\])]")
# Audio tokens per second of output, used to turn a length limit into max_tokens.
# Drama 3: the backend's 1200-token default caps clips at 55.7s.
TOKENS_PER_SEC = {"drama3": 21.6, "qwen_voicedesign": 12.5}
BASE_SECS, SECS_PER_WORD, SECS_PER_CUE = 3.0, 0.6, 2.0

app = FastAPI(title="voices-service")


class SpeechRequest(BaseModel):
    model: str = "drama3"
    input: str
    voice: str = "orion"
    response_format: str = "mp3"
    speed: float = 1.0


def _registry():
    return {v["voice"]: v for v in json.loads(REGISTRY_PATH.read_text())}


def _log(msg):
    print(f"voices-service: {msg}", file=sys.stderr, flush=True)


def _split_cues(text):
    """Return (text without cues, list of lowercase cues)."""
    cues = [c.lower() for c in CUE_RE.findall(text)]
    plain = re.sub(r"\s+", " ", CUE_RE.sub(" ", text)).strip()
    return plain, cues


def _duration(audio):
    d = miniaudio.decode(audio)
    return d.num_frames / d.sample_rate


def _payload(v, text, response_format, max_tokens):
    plain, cues = _split_cues(text)
    if v.get("engine") == "qwen_voicedesign":
        instruct = v["voice_description"]
        if cues:
            instruct = f"{instruct}. Delivery: {', '.join(cues)}"
        return {
            "model": v["model"],
            "input": plain or text,
            "instruct": instruct,
            "response_format": response_format,
            "max_tokens": max_tokens,
        }
    return {
        "model": BACKEND_MODEL,
        "input": " ".join([plain] + [f"[{c}]" for c in cues]).strip(),
        "ref_audio": v["ref_audio"],
        "ref_text": v["ref_text"] and pathlib.Path(v["ref_text"]).read_text().strip(),
        "response_format": response_format,
        "max_tokens": max_tokens,
    }


def _generate(payload):
    r = urllib.request.Request(BACKEND, data=json.dumps(payload).encode(),
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=600) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise HTTPException(502, f"backend error: {e.read().decode(errors='replace')[:300]}")


@app.get("/health")
def health():
    return {"status": "ok", "voices": len(_registry())}


@app.get("/v1/audio/voices")
def voices():
    return {"voices": list(_registry().values())}


@app.post("/v1/audio/speech")
def speech(req: SpeechRequest):
    reg = _registry()
    if req.voice not in reg:
        raise HTTPException(400, f"unknown voice '{req.voice}'. "
                                 f"available: {', '.join(sorted(reg))}")
    v = reg[req.voice]
    engine = v.get("engine", "drama3")
    plain, cues = _split_cues(req.input)
    limit = BASE_SECS + SECS_PER_WORD * len(plain.split()) + SECS_PER_CUE * len(cues)
    # Cap tokens a little above the limit so a runaway stops early but still reads as over.
    max_tokens = min(1200, math.ceil((limit + 2) * TOKENS_PER_SEC.get(engine, 21.6)))

    # Retries drop the cues: plain lines run away far less often, and a second cued
    # try recovers only about half the time at ~6s each, enough for the game to
    # drop the line as stale.
    retry = plain if cues and plain else req.input
    attempts = [req.input, retry, retry]
    best = None
    for i, text in enumerate(attempts):
        audio = _generate(_payload(v, text, req.response_format, max_tokens))
        secs = _duration(audio)
        if secs <= limit:
            if i:
                _log(f"{req.voice}: attempt {i + 1} ok ({secs:.1f}s <= {limit:.1f}s)")
            break
        _log(f"{req.voice}: attempt {i + 1} too long ({secs:.1f}s > {limit:.1f}s): {req.input[:60]!r}")
        if best is None or secs < best[1]:
            best = (audio, secs)
    else:
        audio = best[0]
    media = "audio/mpeg" if req.response_format == "mp3" else "audio/wav"
    return Response(content=audio, media_type=media)
