# arpg-worldgen

A standalone world generator for **Anywhere RPG / Roleplay Anywhere**: you give
it a one-line idea (or answer a short questionnaire that frames the world
first), a language model describes the world, and deterministic
code places everything — **models describe, code places**. The model decides
what the world contains (zones, buildings, rooms, furniture, people, rules and
quests); the layout engine decides exactly where it all sits, checks that every
room is reachable, and writes a ready-to-import scenario zip.

It runs on Python 3.8+ with the standard library only (Pillow is optional,
just for map previews), and the scenario builder, validator and preview
renderer are vendored — nothing outside this folder is needed.

**Game version:** being ported to Anywhere RPG 1.0. Its only contract with the game is the
scenario format. It still writes the 0.18 form, which 1.0 reads unchanged, and its validator already
follows 1.0's rules (see `worldgen/vendor/README.md`). It now writes 1.0's own floors, doors,
locks, liquids and populations. The `region-groups` and `lights` extensions still need the
code-mod loader mods.

**Native populations:** every world also ships the game's own nameless creatures as
`npcTemplates` (chosen in `worldgen/populations.py`): livestock (sheep, cows, goats or pigs)
graze regions whose names or zone kinds read as pasture, paddock, pen or fold; chickens and
ducks keep the farmyards and the yards of farms; rats nest in cellars, stores, warehouses,
granaries, sewers and docks; crows settle the crop plots; townsfolk cross a market, square or
plaza of an urban or town zone in a period-fitting sprite (peasant in fantasy or history,
casual in the present day); and two of the town watch patrol a town's main street unless the
cast already has a guard, watch or police of its own. Counts grow with the region's area
(livestock 2-5, vermin 2-3, crowds 3-5), no population spawns where the player starts, and the
whole world holds at most 20 creatures — the largest counts trim first. The choice is
deterministic given the run's seed.

> **Still in progress:** layout improvements are under way. Maps can come out long and wide,
> with empty ground in places and squeezed furniture. A world's `plan.json` holds everything
> the model wrote, so `layout --plan` (or **Re-roll layout…** in the editor) builds it again
> under a new seed, or after a fix, with no model calls.

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
- **Make a new world:** pick how much framing to do — a **quick** one-line idea, or the
  **short** (7 questions), **medium** (14) or **long** (14 plus the model's own clarifying
  questions) questionnaire — then the resident count, the World Frame P0 wrote (use it, edit
  its summary, or have another try), the extensions and the estimate. Progress shows as it
  goes; Ctrl+C stops it. The world lands in `out/<idea>-<time>/`
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
   OpenRouter, OpenAI, DeepSeek, Ollama, LM Studio, llama-swap.
3. Set the `model` to one your endpoint serves.
4. Check it: `python -m worldgen check-provider zai` — one tiny request,
   reports the model and latency.

`providers.json` is gitignored. Keys are never printed or logged. Local
servers (Ollama, LM Studio, llama-swap) ignore the key but the field must
exist — leave `"none"`.

Two optional settings handle providers with their own rules:

- `"max_output"`: the most output tokens the provider accepts. The catalogue
  phase asks for 32000 and doubles a cut-off reply up to 65536, so a provider
  with a smaller limit answers HTTP 400 without this. The OpenAI preset sets
  16384 for gpt-4o.
- `"extra_body"`: extra request fields sent with every call. The DeepSeek
  preset uses it for thinking: `{"thinking": {"type": "enabled"}}`, or
  `"disabled"` for faster, cheaper replies.

## Commands

```
python -m worldgen generate --idea "a fogbound harbour town of smugglers" \
    --provider zai --out out/harbour --seed 1
python -m worldgen layout --plan out/harbour/plan.json --out out/harbour2 --seed 2
python -m worldgen check-provider zai
python -m unittest          # the test suite
```

- `generate` runs the model phases (P0 the world frame, P1 world plan, P2 items
  then the prop catalogue, P3 one call per building, P4 one per zone, P5 people in batches,
  P6 rules, perks and the story clock) and builds the scenario. The last line
  is a JSON summary.
- **The room library** furnishes ordinary rooms by default: P3 picks each room's
  purpose (or is skipped when a building recipe fits its kind) and code furnishes the
  room from [`library/`](library) — fewer tokens, and beds, tables and chairs set out
  properly. `--no-library` (or unticking **Use room library** in the editor, or
  answering no in the launcher) is the old method, the model furnishing every room.
  With the library, P2's catalogue is only for the outside (feature props, yard props,
  filler), and unit buildings (an inn's guest rooms, flats) are furnished from it too; only
  buildings with upper storeys under the floors extension keep the old P3. See
  [ROOM_LIBRARY_DESIGN.md](ROOM_LIBRARY_DESIGN.md).
- `layout` re-places a saved plan with a new seed and **no model calls** —
  re-roll the map, keep the world.
- Each run writes `settings.json`, `plan.json`, `spec.json`, `metrics.json`, the llm call
  logs, `<Name>.scenario.zip` and (with Pillow) `preview.png`.

### Settings files: sharing a world's choices

Every run saves `settings.json` in its folder under `out/`, before the first model call, so
a failed run has one too. It holds the choices: the idea, the questionnaire mode and
answers, other instructions, residents, seed, extensions, the room-library choice and the
approved World Frame. It never holds a provider, URL or API key, only the model's name as
a note. Send it to someone, or ask for theirs, to run the same world:

```
python -m worldgen generate --settings out/<run>/settings.json --provider zai --out out/again
```

`--idea`, `--seed`, `--ext` and `--no-library` still override the file. With a frame in the
file there is no framing call. In the launcher, **Make a new world from a settings file**
does the same; in the Scenario Editor, **Export settings…** and **Import settings…** in the
New world dialog write and read the same format.

To look into a world that came out wrong (too few buildings, say), the whole run folder is
more use than the settings alone: `llm/01-p1.json` is the world plan's prompt and reply,
where the building count is decided. Zip the folder (the `.scenario.zip` can stay out); no
key is in any of it.

Programs (like the Scenario Editor) drive the same thing through
`worldgen/api.py`: `generate()`, `relayout()`, `estimate()`, `frame()` and the
question bank, with progress events and cancellation.

## The World Frame: questionnaires, population and systems

A one-line idea is enough, but a short questionnaire shapes the whole world
before the map is planned. **P0** turns the mode, the answers and the idea
into a **frame** — genre, premise, reality, setting, tone, conflict, the
player's role, themes, constraints and a 80-150-word summary — shown for a
use / edit / redo choice before anything is built. Every later phase (P1-P6)
gets the approved frame in place of the bare idea, and it lands on
`plan.json`, so a re-roll never asks again.

- **quick**: the idea alone; one P0 call expands it into a frame.
- **short**: seven questions (kind of world, the extraordinary, tone, who the
  player is, what drives the story, what you mostly do, anything to avoid).
- **medium**: those seven plus seven deeper ones (stakes, power, where power
  comes from, growth, danger, time pressure, inspirations).
- **long**: the medium fourteen, then a clarifying turn — the model asks up
  to five questions of its own about real ambiguities (cozy *and* deadly:
  which wins?), you answer, and the final P0 call takes both.

The bank lives in `worldgen/questions.json` as plain data: edit it to change a
question's wording or options without touching code. Every question records
the frame fields it `feeds`, `multi` caps how many options may be picked, and
`free` questions take text only. **Other** and **skip** never appear in the
bank — the UIs add them. `questions.py` checks the bank on load (ids unique,
options non-empty, the population range sane), so a malformed edit fails
loudly.

Beside every form sits the **resident count**, defaulting to 20-40 (the
game's own default) and allowed 5-60. P1 plans enough homes and lodgings to
bed them (a building may carry `residents: n`, and a unit building's count is
units x residents), P3 must give each promise real beds, and P5 people the
place in batches — one call per zone with buildings, at most ten people each
and more calls while the zone's promised residents aren't all made, the roster
carried forward so names never repeat, then the player in a call of their own
from the frame's role, carrying 2-5 starting items from the catalogue. Below
the asked-for range the run tops up with further batches rather than failing.
With no resident count set, a plan whose P1 promised residents houses nobody
past its beds.

Each person gets a sleep room of their own at layout: a couple shares a double
bed, a home naming one unit copy sleeps in that copy, and everyone else fills
the home's beds. Beds in guest rooms and wards are **spare**: they need no
owner, P5 doesn't count them as homes, and they stay empty unless a home runs
out of its own beds.

**P1b, the cast**, runs straight after P1 on any `generate` run. It gives every
building a status (`home`, `staffed`, `occasional`, `vacant` or `abandoned`, with
a `why` for the shut ones) and lists the households, adults with a role, a
workplace, a shift and whether they sell, plus children and elders who stay home
by day. It writes `residents` and `couples` back onto the plan, so beds work as
before. Later phases see each shut building's state and story in its building
line, so P3 furnishes it that way and the quests can use it. P5 then names one
person per slot, and code fills in the facts. The dialog's **Let the map decide**
(population `"map"`) sizes the cast from each zone's kind; a range the user sets
is firm. If P1b produces nothing, the run carries on without a cast.

A person's role also picks their in-game sprite from Anywhere RPG 1.0's character
sheets — an innkeeper, a town guard or a nurse gets that role's own sprites — and
a role with no match keeps the plain casual one.

### Getting more buildings

With **Let the map decide** ticked (the editor's default), P1 plans to the base cap
of 12 buildings, and in testing models planned 6 to 12. The wild zones around the
settlement keep their full size, so a small plan can leave a few buildings in a
map of open ground and props. To get more:

1. **Set a resident count.** Untick **Let the map decide** in the editor; the
   launcher always asks for one. The cap becomes 12 plus one for every 3 residents
   at the middle of the range, up to 28: a 20-40 range allows 22.
2. **Ask in Other instructions or requests** (in the editor), which goes word for word to the world
   plan. For example: "Give every household its own separate house. Plan at least
   12 family houses as well as the inn, shops and workplaces. Put nearly every
   building in one large village zone, and keep any forest, farmland or wild zones
   small." Name any place you must have, such as a harbour, or its zone may come
   back empty.

In a test of the world plan alone (one fishing-village idea, Cydonia 24B, Gemma 4
31B and Gemma 4 12B, two tries each, November 2026), plans averaged 8 buildings
with **Let the map decide**, 11 with a 20-40 count, and 15 with the count and the
instruction above. Models follow it differently: the Gemmas planned 15-16 homes,
Cydonia 8 and 10.

A house for every household is realistic, but a house for every person only works
for small casts, because of the cap. **Re-roll layout…** places the same buildings
again, so it can't add any; generate again instead.

Everyone's day is then planned together. Staff spread over their workplace's
rooms, each person gets a seeded evening place near home (the nearest inn in
their zone, home, or the ground outside), and no walled room holds more than
`ROOM_CAP` (8) people awake at any hour, nor open ground more than that per
14-cell circle: the GM reads everyone in a room in full, every turn. A person
may carry `"shift": "evening"` or `"night"`. People leave early enough to reach
work as their shift begins, and someone whose job is a whole open zone gets a
small post round a stall. See [POPULATION_DESIGN.md](POPULATION_DESIGN.md).

Who sells is decided in `worldgen/sellers.py`. A person's `"sells"` in the plan
decides; without one, a trade in their role sells (a baker, a smith, a vendor,
not an apprentice), and every working shop or inn gets at least one seller, its
owner or keeper first. Sellers are written as `merchant: {}`, and the game stocks
them itself. The player never sells.

The game prices what it stocks on a fixed scale: it tells its model that one coin
is about a US dollar and that a worker earns about 3000 a month, whatever the
currency's own description says. P2 prices the catalogue on that scale, and the
player's purse is at least `MIN_PURSE` (100).

**P6, the systems**, runs after the people in three calls — 6a rules and
economy (narrative rules, flavor and difficulty, a currency whose format
names a digit, a 25-point attribute spread, about 18 skills, weather from the
game's ten, 4-8 variables with a countdown whenever the answers ask for time
pressure), 6b three perk trees of 5-8 perks, and 6c the story clock (recurring
calendar obligations plus 2-4 one-off events in the first week, and 1-2
starting quests whose steps name real places and people). A call that still
fails after retries falls back for that part alone and the log says so — it
never fails the world. Plans from before P6 keep building with genre-neutral
defaults (the Coin, an even 25-point spread).

## Cost and time

From measured runs: **25–35 model calls, 200–320k tokens, 30–55 minutes**
per world (a reasoning-friendly `max_tokens` of 16000 is preset; flash-tier
models are cheap — expect cents on a typical API plan; P2's two calls start at
32000, because the catalogue often passes 16000). A reply that runs out of budget
never counts: it goes again with twice the budget, and a run that keeps only a
cut-off reply says so in its dropped list. `estimate()` reports
these numbers; for a saved plan it counts the calls exactly (P0 when the plan
carries a frame, P1 and P2's two, one call per building and zone, the people
batches and the three systems calls).

### Slow models and free models

Choosing a model? [MODEL_RESULTS.md](MODEL_RESULTS.md) has test results for 22 models,
local and free, including complete worlds built by six of them.

Small models can finish a world, but they take longer and some need room to do it.
A 27B model on a Mac Studio took 3.5 hours; hosted free models took 35 minutes to
2.5 hours and two to four times the tokens.

- **`timeout`** in a provider's `providers.json` entry is the seconds allowed for
  one reply (default 1800). Replies aren't streamed, so nothing arrives until the
  model has finished: a local model at 19 tokens a second needs about 30 minutes
  for a long reply. The local presets set 3600.
- **`rate_limit_wait`** is how long one request waits out a busy provider, in
  seconds (default 900). A 429 or 5xx reply is tried again after a pause, longer
  each time, and the progress line says so. If the wait runs out the run stops
  with an error that names the provider, since the model never saw the request.
  Free models can stay rate-limited upstream for hours, whatever your own quota.
- Slips that a retry would only delete are mended in code and listed under
  "dropped/fixed": a hint outside the vocabulary, a yard the plan doesn't have,
  furniture nested in its rooms, too many starting items, residents on a unit
  building. Code also writes the couples' `partner` fields from the cast.

## Extensions (all off by default)

The default path needs **no game mods**: the zip imports and plays in the
unmodded game. Each extension opts in with `--ext <id>` (repeatable); the
ones that need the matching mods from `../code-mod-loader` (this repository)
installed in the game say so:

| Extension | What it adds | Game mods needed |
|---|---|---|
| `floors` | Upper storeys on buildings — bedrooms and halls upstairs, reached by stairs: Anywhere RPG 1.0's own floors, playable unmodded | none |
| `region-groups` | A zone may wrap around the map and still act as one region | `region-groups` |
| `lights` | Each light source gets a kind (candle, torch, hearth fire, ember, lantern, electric, neon, screen, magic) and, where the setting calls for it, a colour, written as `arpgMods.lights` | `lights` |

The `portals` extension is gone: its stairs were portal pads, and 1.0's own
floors link stairs natively. A settings file or `plan.json` from an older
generator may still name `portals` (or the `floors` mod); the retired id is
dropped with no error, and such a world rebuilds as 1.0 native floors.

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
storeys are floors of their own, and a walkable wall gets its wall-walk
storey 2 wherever both ends have one — joined to each end's storey by a
linked passage pair (planes cannot share a door in 1.0), so the towers and
the gatehouse meet along the walk upstairs. With floors off, a compound is
ground floor only and plays in the unmodded game.

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
vocabulary of slots, flags and counts (no genre words in the layout code). The
genre proofs are `fixtures/modern-quarter.plan.json` (a six-storey block of 24
flats, a parking strip of shops, a park), `fixtures/starship-decks.plan.json`
(an all-void ship with a three-deck crew block) and the hospital
`fixtures/hospital-spine.plan.json`.

**Repeated units.** A building may carry
`"units": {"name": "Apartment", "count": 12, "perStorey": 4, "residents": 2,
"numbering": "plain|storey"}`. P3 designs **one** nested `unit` (its rooms,
connections and furniture) plus the building's shared rooms; code lays the
shared rooms round a corridor spine that runs to the entrance edge and
stamps the unit copies down both sides of it, mirrored so each copy's door
faces the corridor (the builder's own auto-connect pair). Copies are named
`Apartment 4` plainly or `Room 204` by storey. The 28x22 footprint cap
applies to the unit, not the block: the building's length follows from the
count. Each copy gets a bed for every resident its own furniture doesn't
already sleep, and
`BuildingLayout.residents` reports the total for the population work. Proven
by `fixtures/apartment-block.plan.json`.

**Taller buildings.** `storeys` runs 1-6 for a unit building or a compound
part (3 otherwise). A unit building's upper storeys repeat the ground stamp —
corridor and stair positions identical, numbering continuing — with no
per-storey design; each storey is laid out as its own 1.0 floor, so a stack
of any height fits beside the map.

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
ground tinted the boundary colour, the game's own out-of-bounds void look
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

## Item templates and loot pools

Brief 012f gave P2 a second job, now a call of its own that runs first (so the
furniture catalogue can name default pools, and a world that loses this call
still builds, with empty containers): **30-60 setting items** (`{name, type, quality, value, description,
physicalDescription}`, the guide's type and quality lists) and named
**`lootPools`** — lists of item names as specific as the setting needs, by room
kind (a bathroom pool, a galley pool) and by building or store kind (a clothing
store's pool, a sporting goods store's pool, each kiosk its own). One item may
sit in many pools, others in only one, and each pool may carry a `weights` map
item -> relative chance to make some of its items rarer on top of the quality
weighting. Pools are written by the model per setting; code only validates
them (pools name real items, every reference names a real pool, types and
qualities come from the lists, values are positive).

**Where a container's pool comes from** — most specific wins:

1. the P3 furniture line's `lootPool` (this shelf in this store);
2. the room's `lootPool` (every container in this bathroom);
3. the building's `lootPool` (the whole sporting goods store);
4. the object template's default `lootPool`.

So one "Store shelf" template holds clothes in one shop and baseball bats in
the next. Unit copies inherit the unit design's pools.

**Starting inventories.** When code places a container it draws 0-3 items from
its pool, weighted common-over-rare and seeded by the world seed and the
placement's name — the same seed re-rolls the same inventories while every
copied unit differs from its siblings. A per-plan `"loot": "none|sparse|
normal|rich"` setting scales the counts (default `normal`). The spec writes
each object template's `lootPoolIds` as its **declared default only**, never
the union of its placements' pools: the game redraws `lootPoolIds` on later
searches, and a union would let one store's shelves spawn another's goods
then — the per-store variety lives in the drawn starting inventories, which
are per placement. A world with no items still builds, with empty containers.

One pool per genre, as a plan writes them:

```json
"lootPools": {
  "Bathroom cabinet": {"items": ["Mouthwash", "Razor", "Aspirin bottle"]},
  "Crew locker": {"items": ["Ration pack", "Wrench", "Data chip"],
                  "weights": {"Data chip": 0.4}},
  "Ward medicine": {"items": ["Bandage roll", "Thermometer", "Morphine ampoule"],
                    "weights": {"Morphine ampoule": 0.2}}
}
```

## Ways out and ways through

A building's design gives it one entrance, and a spine's only door to the outside
is its gate. After the buildings stand, `worldgen/exits.py` adds side doors until
every room is within `EXIT_REACH` (24 cells, 48 m) of a door to open ground, and
any complex of two or more parts has at least two ways out. It stops at four new
doors, or sooner if no door would shorten the longest walk. It prefers a public
room when one will do. A walled enclosure keeps its walls, and a void zone has no
ground to step onto. `metrics.json` lists what it added under `side_exits`.

Outdoors, a solid prop keeps one free cell from other solid props where there is
room, so a row of stalls has ways through. It may never join two separate
obstacles, wherever it goes. `open_cells_cut_off` in `metrics.json` counts free
cells nobody can walk to, by the game's own wall rule.

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
