# Population: design

Status: build step 1 done (schedules and the room cap), the rest is design only (2026-11-03).
Target: the world generator in this folder, plus one small new code mod.

## Why

The world's headcount is an arbitrary number chosen before the world exists.

- The dialog's resident count (20-40 by default, 5-60 allowed) goes into P1, and P1 plans homes to
  fit it. It even sets the building cap (12 + n/3, at most 28).
- Nothing matches people to places. P5 is told "about N people", so a smithy gets a smith only if
  the model happens to write one, and a building nobody works in reads the same as a busy one.
- Families are luck. Nothing asks for children or elders, so most people are working adults.
- Everyone keeps the same hours, in the same rooms (see "Where people are during the day").

What Michael wants instead: the map decides how many people it needs, some roles stay unfilled on
purpose, and an unfilled role is a story hook, not a gap. Busy maps are fine. The limit that
matters is how much the GM has to read at once.

**Goals**
- Decide who lives and works where after the buildings exist.
- Let a building be staffed, visited now and then, vacant or abandoned, and let that change how it
  looks.
- Build families in from the start.
- Cap people per room, not per world.
- Support real people who are off-stage: the rest of a cyberpunk city, a caravan every 3 months.
- Keep the plain path playable with no mods, as every extension does.

## What the GM actually reads

From `_reference/engine_schema_findings.md` Q8 and the 0.18 bundle (`Vn=14`).

| Who | What the GM gets each turn |
|---|---|
| NPCs within 14 cells of the player **and** in the same walled room (outdoors: within 14 cells) | A full entry: name, stance, merchant, level, description, HP, what they carry, distance, activity |
| Everyone else | One short line in the region tree: name, stance, merchant, activity |
| Anyone with a queued action, or awaiting the GM | Detail, wherever they are |
| Memories and mindset | The nearest 1-5 NPCs, by subscription tier |

Scheduled walking is engine logic with no model call.

So an extra NPC elsewhere costs one short line. A crowded room costs a full entry per person, every
turn the player stands in it. That's why the cap below is per room.

Hostiles are `type: "npc"` entities too, spawned from a template at 1-6 per region. The generator
writes none yet. When it does, they count towards the cap.

## Where people are during the day

Measured on recent worlds: the most people in any 40×40 window, by the centre of their scheduled
region.

| World | People | Asleep | At work | Evening |
|---|---|---|---|---|
| Gullwick (live-015-couples-3) | 32 | 18 | 19 | **32** |
| Gullwick (live-015-couples-2) | 47 | 35 | 29 | **47** |
| Bramblewick | 30 | 7 | 8 | **30** |

The cause is in `schedule.py`:
- `social_spot` sends everyone to the common room of the first inn it finds, whichever zone they
  live in.
- `work_location` puts all of a building's staff in its entrance room.
- Every person keeps the same hours: work 06:00-18:00, leisure 18:00-22:00, sleep 22:00-06:00.

Fixing this is the cheapest and most valuable part of the design, and it needs no model calls.

## How it fits the generator

```
P0 frame
P1 world         the zones and buildings, as today
P1b cast  (new)  every building's status, the households, the roles, the visits
P2 catalogue
P3 interiors     see each building's status, so an abandoned smithy looks abandoned
P4 zones
P5 people        fill the cast's slots instead of "about N people"
P6 systems       get the hooks; write the clocks' rules
layout           code: rooms, beds, then schedules under the room cap
```

P1b writes the fields the pipeline already uses: `residents` and `couples` on each home. So beds,
P3's bed check, sleep assignment and couples all keep working unchanged.

## Choosing how many people

The dialog gets a checkbox beside the resident count: **Let the map decide** (on by default). A
fixed range stays available as an override. Short guidance sits under it:

> A hamlet is about 10-20 people, a village 20-45, one city block 30-60. Busy maps are fine: the
> generator spreads people out so no room gets crowded.

- **Let the map decide:** P1 plans the place with no population target, and P1b sizes the cast.
- **Fixed range:** P1 plans for it as today, and P1b must land inside it, leaving roles unfilled
  when it has to.

Each zone gets a guiding budget by kind and size, passed to P1b as a range. It's there to stop
100-person villages, not to protect the GM (the room cap does that). Starting numbers, to tune
from live runs:

| Zone | People |
|---|---|
| Hamlet, farmstead, outpost | 8-20 |
| Village, estate, compound | 20-45 |
| Town quarter, city block, station deck | 30-60 |
| Wilds, fields, harbour with no homes | 0-6, living elsewhere |

**Cost:** about 10k tokens per batch of ten people (measured: Gullwick's second batch took the run
from 104,742 to 115,395). `P5_ZONE_BATCHES` (4) caps a zone at 40 people today and must follow the
budget. Off-stage people cost the same to write as anyone else.

## P1b: the cast

One short model call. It sees the frame, every zone and every building's kind and purpose, and
replies with a status for each building, the households, and any visits and unlocks.

```json
{
  "buildings": [
    {"name": "Brannoc's Cottage", "status": "home"},
    {"name": "The Spent Sail", "status": "staffed",
     "roles": [{"role": "innkeeper", "shift": "evening", "sells": true, "home": "Innkeepers' House"},
               {"role": "cook", "shift": "day"}]},
    {"name": "The Old Forge", "status": "occasional", "why": "no smith since the plague; the caravan's smith works it when he's here",
     "roles": [{"role": "travelling smith", "sells": true, "presence": "visit", "visit": "The Salt Caravan"}]},
    {"name": "Chandler's Shop", "status": "vacant", "why": "the chandler died; the lease is open",
     "roles": [{"role": "chandler", "sells": true, "presence": "unlock", "unlock": "Estate Standing"}]},
    {"name": "The Watchtower", "status": "abandoned", "why": "the coast watch was disbanded a generation ago"}
  ],
  "households": [
    {"home": "Brannoc's Cottage", "couples": 1,
     "members": [{"kind": "adult", "role": "fisher", "work": "Herring Strand"},
                 {"kind": "adult", "role": "net-mender", "work": "Brannoc's Cottage"},
                 {"kind": "child"}, {"kind": "child"}, {"kind": "elder"}]}
  ],
  "visits": [{"name": "The Salt Caravan", "everyDays": 90, "stayDays": 5, "from": "On the Road"}],
  "unlocks": [{"variable": "Estate Standing", "at": 60}],
  "offstage": [{"place": "The Upper Stacks", "people": 6, "why": "corporate tenants the player will only meet by going up"}]
}
```

### Building status

| Status | Meaning | What P3 does |
|---|---|---|
| `home` | A household lives here | As today |
| `staffed` | Open, with people working it | As today |
| `occasional` | Worked now and then by a visitor | Kept usable, a little dusty, tools put away |
| `vacant` | Closed but sound, waiting for someone | Clean, empty shelves, no stock |
| `abandoned` | Left to rot | Ruined: cold hearths, broken furniture, no beds or loot |

Buildings are never cut from the plan for being unstaffed. They're flavour and story hooks: the
abandoned smithy stays on the map, and the run-down estate has something to rebuild.

- A status goes into P3's building line, with a sentence on what it means, plus the `why`.
- `abandoned` and `vacant` buildings have no residents, so P3's bed check doesn't apply.
- With the room library, status picks the condition: `abandoned` is `ruined`, `vacant` is `worn`.
- Every `why` goes to P6c as a hook, so quests can grow from them: who owned the shop, why the
  watch left, what it would take to reopen it.

### Households

Each home lists its members by kind: `adult`, `child` or `elder`. Roles attach to adults, and
children and elders stay home by day. `residents` and `couples` come from the list.

**The rule P1b is checked against:** at least a third of a world's homes hold more than adults, so
a village isn't all working adults. Worlds where that's wrong (a ship's crew, a barracks) are
exempt when the frame says so.

### Roles

A role has a `shift` (`day`, `evening` or `night`, default `day`), an optional `home`, `sells`, and
a `presence`: `resident` (default), `visit`, `unlock` or `offstage`.

`sells: true` writes `merchant: {}` on the person. Today `spec_writer` only does that when the role
contains "innkeeper" or "merchant", so bakers and smiths can't trade. The game stocks a merchant by
itself (`gen_merchant_stock`).

Not every role gets filled. The prompt says so, and the budget forces the choice.

### Checks

`check_p1b`: every building has a status; every home has members; `2 × couples ≤ adults`; a role's
building exists; a `visit` or `unlock` it names exists; `everyDays` is 7-365; the total sits in the
budget or the fixed range. `sanitize_p1b` treats a building with no status as `staffed` when it
has a work purpose and `home` when P1 gave it residents, and logs it.

If P1b produces nothing, the run carries on as today.

## P5: filling the slots

Each zone batch lists its open slots instead of "about N people": the household members and roles
still unmade. Follow-up batches run until they're filled (the mechanism from 2204a95).

- `check_p5` gains: each person claims a slot, by `home` and `role`.
- A slot still unfilled after the retries is dropped with a log line, and its building keeps its
  status. No world fails over a missing cook.
- The bed-bound rule from 0d7f4f3 stays as the backstop. Without a cast it behaves as it does now.
- Household kinds carry into the plan as `kind`, so a later relationships mod can read them, along
  with `partner`.

## Schedules under the room cap

All of this is code, after layout, and it costs no tokens.

**Hours.** `shift` sets the blocks: `day` as today; `evening` works 14:00-22:00 and sleeps
00:00-08:00; `night` works 22:00-06:00 and sleeps 08:00-16:00. Children and elders have no work
block, and spend it at home or nearby.

**Work.** Staff spread over their workplace's rooms rather than all standing in the entrance room.

**Evenings.** Each person gets one evening place, seeded, from what's near their home: the nearest
inn in their zone, home, or the open ground outside. A void zone has no outside. Visiting a
neighbour's home waits for the relationships mod, which knows who is welcome where.

**The cap.** `ROOM_CAP = 8` to start, in one constant. It's a judgement call: the game sets no such
limit, and live play should tune it. For every schedule block:
- A walled room holds at most `ROOM_CAP` people at any hour.
- An outdoor region holds at most `ROOM_CAP` per 615 cells (one 14-cell circle), at least
  `ROOM_CAP`.
- Over the cap, the extra people move to their next choice, or stay home. Open-ground workers
  spill into the zone's buildings first.

A sleeping room is limited by its beds instead, so a barracks can hold more than the cap at night.
The Problems panel lists it as a note.

**The Scenario Editor** gets a new check: it warns when a room passes the cap at any hour, naming
the hour. The check reads schedules the way the generator writes them, so hand edits get the same
warning.

## Off-stage people

A place the player rarely or never goes, with real named people in it. The GM knows they exist, at
one short line each, and nothing else costs anything.

**An off-stage region** is a small walled region with no door, tucked in a corner of the map, with
a name like "The Upper Stacks" or "On the Road". Its people have all-day schedules there, and it
needs no beds (the game's own spawned NPCs use an all-day `leisure` block).

- It's marked `offstage` in the plan, so the reachability checks skip it.
- The Scenario Editor's sealed and unreachable warnings need the same exception.

This works in the unmodded game, and it covers the dense-city case by itself: daily schedules that
never change need nothing more.

## Visits and unlocks

### The clock

The game's schedules repeat daily, and its calendar recurs only daily or weekly. So a caravan every
3 months needs a day counter in a global variable, the approach Sundered Boundary used for Tian
Dazhu's breath. Checked against the bundle:
- Values accumulate as floats and are clamped, not rounded, so 1/24 per hour works.
- A `critical` fires by chance per game minute while in its zone, also across time skips. At the
  maximum of 20 a minute it fires within minutes.
- It resets the value to `initial` and tells the GM with a story line.
- A status appears on entering a zone. Leaving one logs that it ended.
- The low zone is tested first.

So one variable can run the whole cycle:

```json
{"name": "Salt Caravan", "emoji": "🐪", "type": "number", "value": 20, "initial": 0,
 "min": 0, "max": 90, "ratePerHour": 0.041667,
 "lowZone":  {"threshold": 5,  "effectDesc": "The Salt Caravan is in town", "emoji": "🐪"},
 "highZone": {"threshold": 90, "effectDesc": "The Salt Caravan is due", "emoji": "🛤️"},
 "critical": {"zone": "high", "chancePerMinute": 20,
              "description": "Bells on the coast road: the Salt Caravan rolls in."}}
```

The value climbs one a day. At 90 the critical fires and resets it to 0: arrival. It stays in the
low zone for 5 days, then climbs out: departure. A weekly market needs no variable, just a
`recurrence: "weekly"` calendar entry.

Every variable is sent to the GM each turn, so a world gets at most 3 clocks.

### Unlocks

An unlock is a progress variable with no rate, raised by the GM with `var_delta` ("Estate
Standing"). It uses a **high zone with no critical**, because a critical would reset the player's
progress. Reaching the threshold shows a status such as "Word has spread: a chandler would come",
and that's the trigger.

### Bringing someone on stage

The obvious way doesn't work. The GM has no action that changes a schedule, and a time skip moves
every NPC to their scheduled location. A real NPC teleported into town would be pulled straight
back off-stage. So there are two paths:

| | **With the `visits` mod** | **Plain game** |
|---|---|---|
| Who | Real NPCs, created at build, waiting off-stage | Written into the GM's rules, not on the map |
| Arrival | The mod swaps their schedule to the town one and moves them | The GM uses `spawn_npc_near` at the place (a spawned NPC stays where it appears) |
| Departure | The mod swaps it back | The GM uses `destroy_entity` |
| Between visits | They keep their memories and inventory | They're gone. A new spawn is a new NPC under the same name |
| Relies on the GM | No | Yes |

This follows the rule for every extension: **Visits** is a toggle, off by default.

**The `visits` code mod** (`code-mod-loader`) reads `arpgMods.visits`:

```json
[{"name": "The Salt Caravan", "variable": "Salt Caravan", "zone": "low",
  "people": ["Hask the Smith", "Oda Vell"], "away": "On the Road",
  "town": {"Hask the Smith": [{"start": "08:00", "end": "18:00", "location": "The Old Forge Forge Floor", "role": "work"}]}}]
```

A per-tick check, like the portals mod's, compares each entry's zone with the variable. An unlock
is the same entry with `"zone": "high"` and no way back. Saves keep the state because it's derived
from the variable.

**Without the mod,** P6a writes a rule per clock, for example: "When the Salt Caravan arrives, spawn
Hask the Smith at The Old Forge; when it leaves, remove him." P5 still writes the visitor's
description, which goes in the rule.

## Running a shop

Michael's example: the player reaches a threshold and someone comes to run a shop, or the player
moves in and runs it.

- **Someone comes:** an unlock, as above, with `sells: true`.
- **The player runs it:** the notes show `merchant` only as a flag on NPCs, and no player-run shop.
  In the plain game the GM can narrate it with `transfer_item` and `currency_delta`, and P6a can
  write that as a rule for a `vacant` shop. Anything firmer is a future mod, and it belongs with
  ownership in the relationships mod (`_reference/mod_roadmap.md`).

## Checks and tests

- `check_p1b` and `sanitize_p1b` with mocked replies: good, missing status, bad couples, unknown
  visit.
- P3 sees status, and `abandoned` and `vacant` skip the bed check.
- P5 fills slots across batches and drops an unfilled one with a log line.
- Schedules: no room over `ROOM_CAP` at any hour across all fixtures; shifts produce the right
  blocks; nobody's evening spot is in another zone.
- Fixtures have no cast, so they must build as before, with the new evenings and the cap applied.
- `sells` writes `merchant`.
- Off-stage regions pass reachability and carry people with no beds.
- `visits` mod: schedule swap on both zone changes, across a time skip and a save and reload.

## Live checks before building on them

The bundle reading supports these, but none has been played.
1. **Start value:** the clock above starts at `value: 20` with `initial: 0`, so the caravan isn't
   in town on day 1. Our notes say to set `value` to `initial`. If the game insists, the caravan
   starts the game in town.
2. **The status pill:** a zone's status sits on the player. Check that it reads well, and that a
   visible counter isn't a spoiler.
3. **A plain-path visit:** does the GM reliably spawn and remove someone from the rule alone?
4. **A sealed region:** does a doorless region with people in it stay quiet in play, with no
   "no path" log noise?

## Measuring it

Before and after, on Gullwick and Bramblewick: worst room headcount by hour, worst 14-cell circle
outdoors, tokens in P1b and P5, and the share of homes with children or elders. Target: no room
over the cap, and P1b under about 10k tokens.

## Build order

1. **Schedules and the room cap.** Code only: shifts default to `day`, evenings spread, staff
   spread, cap applied, editor check. Worth shipping alone.
2. **`sells`** from a simple rule, then from the cast.
3. **P1b cast, with statuses and households,** feeding P3 and P5. Dialog checkbox.
4. **Off-stage regions.** Generator and editor exceptions.
5. **Live checks 1-4** on a hand-made scenario.
6. **Clocks and unlocks in P6,** with the plain path.
7. **The `visits` mod and the extension toggle.**
8. **Crowd tuning:** budgets, `ROOM_CAP`, `P5_ZONE_BATCHES`, from live runs.

Steps 1-2 and step 3 can each go to GLM as a brief. Step 7 touches the game, so it needs a live test
by hand.

## Open questions for Michael

1. **Default:** should "Let the map decide" start ticked? This design assumes yes.
2. **`ROOM_CAP`:** start at 8, or higher for busy taverns? It only needs one number to change.
3. **Ambient crowds:** hostile templates can have `attacksOnSight: false`, which might give nameless
   passers-by in a dense city, at up to 6 a region. Worth testing, or are named people enough?
