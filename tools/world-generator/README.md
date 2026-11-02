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
0.18 scenario format; the extensions also need the 0.18 code-mod loader mods.

## Start it

Double-click the launcher for your system in this folder. It asks its questions in a terminal
window, so there are no commands to type.

| System | Launcher |
|---|---|
| Windows | `Start World Generator.bat` |
| macOS | `Start World Generator.command` |
| Linux | `start-world-generator.sh` |

It needs Python 3.8 or newer, and nothing else.

- **The first time**, it sets up your model provider: pick a preset (z.ai, OpenRouter, OpenAI,
  Ollama, LM Studio, llama-swap) or any other OpenAI-compatible server, confirm the URL and
  model, and type your key (hidden). It saves them to `providers.json` and can send one tiny
  test request.
- **Make a new world:** type a one-line idea, turn extensions on or off, and confirm the
  estimate. Progress shows as it goes; Ctrl+C stops it. The world lands in `out/<idea>-<time>/`
  as a `.scenario.zip` for **New Game → Import…** (or **Open zip…** in the Scenario Editor).
- **Re-roll a world** made earlier: the same world placed again under a new seed, with no model
  calls.
- **Set up or test a provider** any time from the same menu.

The Scenario Editor's **New world…** dialog does the same in your browser, and opens the result
for editing.

## Set up a provider by hand

The model calls go through **your own** OpenAI-compatible provider and key;
nothing uses the game's built-in subscription. The launcher writes this file for you; to do it
by hand:

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
| `lights` | Each light source gets a kind (candle, torch, hearth fire, ember, lantern, electric, neon, screen, magic) and, where the setting calls for it, a colour, written as `arpgMods.lights` | `lights` |

`floors` needs `portals` (its stairs are portals): enabling floors turns
portals on with it.

Light strengths (`light`, 0.2 to 1.0) are plain game data, asked for on every
run: they are what the unmodded game lights at night. The `lights` extension
adds the kinds and colours on top. Without the `lights` mod installed, a world
built with it simply looks plain. Plans made before light strengths were asked
for have none, so re-rolling one adds no lamps; generate it again instead.

Example:
`python -m worldgen generate --idea "…" --provider zai --out out/x --ext floors`.

## Compounds and zone arrangements

One place built from several connected structures — four towers joined by
walls with a keep inside, a walled monastery, a fenced compound — is a
**compound**. The model names the parts as ordinary buildings of one zone,
then lists them in a top-level `compounds` entry with a slot each; code adds
the walls, the doors and the courtyard. The same vocabulary describes a
castle, a monastery, a prison or a walled campus: code knows only geometry.

```json
{"compounds": [
  {"name": "Ashvale Castle", "zone": "Castle Rise",
   "shape": "enclosure", "courtyard": "small|medium|large",
   "walls": "walkable|solid|none",
   "parts": [
     {"building": "NW Tower",   "at": "corner:nw"},
     {"building": "Gatehouse",  "at": "edge:south:center", "gate": true},
     {"building": "Keep",       "at": "inside:north"},
     {"building": "Chapel",     "at": "attached:Keep:east"}
   ]}]}
```

- Slots: `corner:<nw|ne|sw|se>`, `edge:<side>:<start|center|end>` (at most
  two marked `gate`), `inside:<center|side>` and `attached:<part>:<side>`.
- A zone may also set `"arrangement"`: `around_green` (one open green, its
  centre props on it, buildings facing it on every side with the largest at
  the head opposite the road — no side streets), `along_street`, `scattered`,
  or `fields` (fenced crop plots, the buildings gathered at the road-side
  corner). A zone too small for its green falls back to the usual street.
- With compounds the plan's building cap rises from 12 to 16 — towers and
  gatehouses are buildings. P3 is told each part's slot and neighbours, so
  entrances, inner doors and stairs make sense inside the structure.

What code does with it (`worldgen/layout_compound.py`): the parts keep their
P3 designs (rooms, furniture, storeys) and are placed on the enclosure's
perimeter and courtyard as **one block** the zone's other buildings pack
around. `walkable` walls are 3-wide single-room corridors whose end doors
come from the builder's auto-connect (parts and walls nest under one
unwalled compound region, so nothing outside the compound grows a door into
it); `solid` walls are 1-thick walkability-0 object strips. The gate (marked
or the edge part nearest a road mouth) gets an outside entrance and a
courtyard door, and 1-wide courtyard paths run gate → inside parts; nothing
of the zone dresses inside the walls. With `floors` on, each part's upper
storeys sit in the band **in the compound's ground arrangement** — storeys
at the same level touch where their ground regions touch, and a walkable
wall gets its wall-walk storey 2 wherever both ends have one, so the towers
and the gatehouse join along the walk upstairs. With floors off, a compound
is ground floor only and plays in the unmodded game.

The feasibility answers behind those choices are in
`reports/012-feasibility.md`, each pinned by builder specs in
`tests/test_compound_feasibility.py`: doors between parts come from the
unwalled compound region (the courtyard is a named region and strangers
cannot auto-connect in); a 1-cell wall interior builds, walks and passes
every check, so walkable walls are 3 wide; solid strips block without any
passability trick; touching upper storeys auto-connect, and the floors seal
keeps those shared doors while stripping the fiction ones. The end-to-end
proof is `fixtures/ashvale-compound.plan.json` — four 3-storey towers, a
gatehouse and a keep in a walled compound, the village `around_green`, the
farm in `fields` — which builds and validates with zero errors and full
reachability in all four combinations of `floors` and `region-groups`
(renders in `out/012-*.png`).

## Units, storeys, rows, spines and void zones

Brief 012e added the shapes modern and interior worlds need, all in the same
vocabulary of slots, flags and counts (no genre words in the layout code).

**Repeated units.** A building may carry
`"units": {"name": "Apartment", "count": 12, "perStorey": 4, "residents": 2,
"numbering": "plain|storey"}`. P3 designs **one** nested `unit` (its rooms,
connections and furniture) plus the building's shared rooms; code lays the
shared rooms round a corridor spine that runs to the entrance edge and
stamps the unit copies down both sides of it, mirrored so each copy's door
faces the corridor (the builder's own auto-connect pair). Copies are named
`Apartment 4` plainly or `Room 204` by storey. The 28x22 footprint cap
applies to the unit, not the block: the building's length follows from the
count. One bed per resident is stamped inside each copy, and
`BuildingLayout.residents` reports the total for the population work. Proven
by `fixtures/apartment-block.plan.json`.

**Taller buildings.** `storeys` runs 1-6 for a unit building or a compound
part (3 otherwise). A unit building's upper storeys repeat the ground stamp —
corridor and stair positions identical, numbering continuing — with no
per-storey design. In the `floors` band a stack taller than the play area's
height wraps into columns; a block whose ground entrance faces east has its
storeys' build-time doors flipped west onto the boundary strip, so the
builder's flat walk still reaches every storey.

**A row of parts** (`"shape": "row"`, `"frontage": "north|south|east|west"`,
`"front": "street|parking|walkway|none"`) lines parts up side by side facing
the frontage, `linked` neighbours butting (the builder joins them with a
door) and the rest one clear cell apart — the builder would open a door
between any two butted siblings, so strangers keep the gap. `parking` paves
the front strip and fills it with parked-vehicle slots from the plan's own
catalogue (registered as intentional solids); slots are `row:<index>` or the
plan's order. A row part may itself carry `units` (a terrace of identical
houses is one part), and `sameAs` copies another part's whole P3 design so
P3 runs once for a strip of identical shops (`fixtures/shop-strip.plan.json`).

**A spine** (`"shape": "spine"`, `"axis": "ns|ew"`, `"spineWidth": 3-5`) is a
code-made walled corridor with parts butted along it at
`spine:<left|right>:<index>`, end caps at `spine:end:<start|end>`, and an
optional hub part (`spine:hub`, at `"hub": "center|start|end"`) whose
outward entrance gates the block — every part auto-connects to the spine.
`cluster` is the `spineWidth: 0` special case: no corridor, the parts packed
round the hub. Wings branch further with `attached:<part>:<side>` off any
part. The hospital proof is `fixtures/hospital-spine.plan.json` — a station
hub at the corridor's foot, two wards of six one-bed rooms.

**Void zones** (`"exterior": "void"` on a zone) turn everything outside the
zone's walled regions into out of bounds: walkability-0 slab objects over
ground tinted the boundary colour, exactly the World's Edge treatment
(`passableAtBuild` so the build-time walk crosses, hardened to 0 by
`inject_arpg_mods` — it plays in the unmodded game). Filler, props and paths
never land there. Roads to and from a void zone become walled corridor
tubes (a mouth too thin for an interior is widened to 3), and each zone with
a gated compound gets a connector arm from the tube to its gate — a
clearance-routed 3-wide corridor, split along the zone and compound borders
it crosses so every piece nests under what contains it, with facing doors on
every seam cell. A plan whose zones are **all** void gets a void default
tile, so no walkable open ground survives anywhere. The proof is
`fixtures/ship-void.plan.json` — six compartments on a spine, a dock, and a
tube between: every walkable cell of the map is inside a walled region
(`tests/test_void.py`).

## How zones are sized

A zone's ground follows what stands on it, not its size class alone. A zone
with buildings or compounds is sized by its **content fit** — the buildings
facing each other across the street, their yards and lot spacing, the green
and its ring, the crop plots — scaled a little by `sizeClass` (1.0x for
small up to about 1.15x) and with room to dress. The size class is no floor:
a `huge` zone holding a hamlet is hamlet-sized, because the model chooses
`huge` for castles and hamlets alike. Wild and water zones with nothing in
them keep their nominal size. The band packer never stretches a built-up
zone beyond about 1.3x its target along its band; the spare length goes to a
neighbouring wild zone or the map margin, so no built zone trails empty
ground. `metrics.json` carries a `zone_fill` entry per zone — its area, the
area its content claims (buildings, compound blocks, yards, fields, the
green, one lot ring each) and the ratio — and a built-up zone below about
0.45 is mostly empty.

The two special ground shapes follow the same rule. An `around_green` green
is sized from the buildings ringing it (a few buildings, a small green and a
tight ring of lots) and leans toward its road mouths, so the entry arms run
through the frontage instead of across empty grass; it is named for the
zone's own green- or common-like outdoor feature (else "<Zone> Green") and
is grass underfoot. A wild zone with no buildings gets **one track** joining
its road mouths — or no path at all when it has fewer than two — never
streets running the zone's length beside empty ground. The Ashvale fixture
(`out/012c-*.png`) shows the result: the castle compound covers 57% of
Castle Rise, the village green carries buildings on three sides, and every
built zone fills at least 0.57.

## Import the zip

1. Start Anywhere RPG and open the scenario/import screen.
2. Pick the generated `<Name>.scenario.zip` from your `out/` folder.
3. Play. Portraits are generated in-game on first import (or add your own
   media); everything else — map, buildings, furniture, NPCs with daily
   schedules — is in the zip.
