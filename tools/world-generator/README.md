# arpg-worldgen

A standalone world generator for **Anywhere RPG / Roleplay Anywhere**: you give
it a one-line idea, a language model describes the world, and deterministic
code places everything — **models describe, code places**. The model decides
what the world contains (zones, buildings, rooms, furniture, people); the
layout engine decides exactly where it all sits, checks that every room is
reachable, and writes a ready-to-import scenario zip.

It runs on Python 3.8+ with the standard library only (Pillow is optional,
just for map previews), and the scenario builder, validator and preview
renderer are vendored — nothing outside this folder is needed.

**Game version:** built for Anywhere RPG 0.18. Its only contract with the game is the
0.18 scenario format; the Floors, Portals and Region groups extensions also need the 0.18
code-mod loader mods.

## Set up a provider

The model calls go through **your own** OpenAI-compatible provider and key;
nothing uses the game's built-in subscription.

1. Copy `providers.example.json` to `providers.json` (same folder).
2. Fill in your key for the preset you want (or add your own entry — any
   `/chat/completions` endpoint works). Presets: z.ai (api and coding plan),
   OpenRouter, OpenAI, Ollama, LM Studio, llama-swap.
3. Set the `model` to one your endpoint serves.
4. Check it: `python -m worldgen check-provider zai` — one tiny request,
   reports the model and latency.

`providers.json` is gitignored. Keys are never printed or logged. Local
servers (Ollama, LM Studio, llama-swap) ignore the key but the field must
exist — leave `"none"`.

## Commands

```
python -m worldgen generate --idea "a fogbound harbour town of smugglers" \
    --provider zai --out out/harbour --seed 1
python -m worldgen layout --plan out/harbour/plan.json --out out/harbour2 --seed 2
python -m worldgen check-provider zai
python -m unittest          # the test suite
```

- `generate` runs the model phases (P1 world plan, P2 prop catalogue, P3 one
  call per building, P4 one per zone, P5 people) and builds the scenario.
  The last line is a JSON summary.
- `layout` re-places a saved plan with a new seed and **no model calls** —
  re-roll the map, keep the world.
- Each run writes `plan.json`, `spec.json`, `metrics.json`, the llm call logs,
  `<Name>.scenario.zip` and (with Pillow) `preview.png`.

Programs (like the Scenario Editor) drive the same thing through
`worldgen/api.py`: `generate()`, `relayout()`, `estimate()`, with progress
events and cancellation.

## Cost and time

From measured runs: **13–18 model calls, 100–150k tokens, 20–35 minutes**
per world (a reasoning-friendly `max_tokens` of 16000 is preset; flash-tier
models are cheap — expect cents on a typical API plan). `estimate()` reports
these numbers; for a saved plan it counts the calls exactly.

## Extensions (all off by default)

The default path needs **no game mods**: the zip imports and plays in the
unmodded game. Each extension opts in with `--ext <id>` (repeatable) and
needs the matching mods from `../code-mod-loader` (this repository) installed
in the game:

| Extension | What it adds | Game mods needed |
|---|---|---|
| `floors` | Upper storeys on buildings — bedrooms and halls upstairs, stair portals, in a lit band beyond a dark world's edge | `portals`, `floors` |
| `portals` | Two-way portal pads linking two cells | `portals` |
| `region-groups` | A zone may wrap around the map and still act as one region | `region-groups` |

`floors` needs `portals` (its stairs are portals): enabling floors turns
portals on with it. Example:
`python -m worldgen generate --idea "…" --provider zai --out out/x --ext floors`.

## Import the zip

1. Start Anywhere RPG and open the scenario/import screen.
2. Pick the generated `<Name>.scenario.zip` from your `out/` folder.
3. Play. Portraits are generated in-game on first import (or add your own
   media); everything else — map, buildings, furniture, NPCs with daily
   schedules — is in the zip.
