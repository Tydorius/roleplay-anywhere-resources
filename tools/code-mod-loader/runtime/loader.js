// Anywhere RPG code-mod loader. Runs before the game bundle, which hands it the
// api-call registry (`api`) and routes every config/prompt file read through `cfg`.
(() => {
  const pendingCalls = [];
  const cfgHooks = [];
  const worldHooks = [];
  const promptHooks = [];
  const tickHooks = [];
  const pathHooks = [];
  const perceiveHooks = [];
  const liquidCanvasHooks = [];
  const groundFadeHooks = [];
  const hiddenHooks = [];
  const wallRegionsHooks = [];
  const doorHooks = [];
  const doorwayHooks = [];
  let api = null;

  // A broken mod must never take the game down with it.
  function runHooks(kind, hooks, args) {
    for (const hook of hooks) {
      try {
        hook(...args);
      } catch (e) {
        console.error(`[arpg] ${kind} hook failed`, e);
      }
    }
  }

  // The render hooks run per chunk and per sync, so a failing one is logged once, not on
  // every call.
  function warnOnce(kind, hook, err) {
    if (hook.arpgWarned) return;
    hook.arpgWarned = true;
    console.warn(`[arpg] ${kind} hook failed`, err);
  }

  function addCall(name, build) {
    if (!api) return void pendingCalls.push([name, build]);
    try {
      api[name] = build(api);
      arpg.calls.push(name);
    } catch (e) {
      console.error(`[arpg] api call ${name} failed to register`, e);
    }
  }

  // The game's own status test (`locked`, `phasing`, …): does the entity carry a mechanic of
  // this type? Reimplemented from the bundle's status-effect scan.
  function hasMechanic(entity, type) {
    return !!(entity?.statusEffects ?? []).some(s => s.def?.mechanics?.some(m => m.type === type));
  }

  const arpg = {
    version: 2,
    mods: [],
    calls: [],
    cfgSeen: new Set(),
    // Filled in by the patched bundle with 1.0's own sight helpers (`lineClear`, `sightBlockers`).
    game: {},
    // The last world the loader has seen: set on world creation and on every tick and prompt
    // dispatch, before hooks run. The wallRegions dispatcher passes it to its hooks.
    lastWorld: null,
    get api() { return api; },
    set api(v) {
      api = v;
      for (const [name, build] of pendingCalls.splice(0)) addCall(name, build);
    },
    // hook(path, readOriginal) → string to use, or undefined to keep the original.
    cfg(path, readOriginal) {
      arpg.cfgSeen.add(path);
      let value;
      let read = false;
      const original = () => (read ? value : ((read = true), (value = readOriginal())));
      let out;
      for (const hook of cfgHooks) {
        const r = hook(path, () => (out !== undefined ? out : original()));
        if (r !== undefined) out = r;
      }
      return out !== undefined ? out : original();
    },
    // Called by the game when it builds a world from a scenario (a new game, or the
    // World editor's preview when `editing` is true).
    // Mod data in the scenario's `arpgMods` key is copied onto the world (and so into saves).
    worldCreated(world, scenario, editing) {
      arpg.lastWorld = world;
      if (scenario && scenario.arpgMods && typeof scenario.arpgMods === 'object') {
        world.arpgMods = JSON.parse(JSON.stringify(scenario.arpgMods));
      }
      runHooks('world', worldHooks, [world, scenario, !!editing]);
    },
    // Called at the start of every unpaused simulation step.
    tick(world) {
      arpg.lastWorld = world;
      runHooks('tick', tickHooks, [world]);
    },
    // Called whenever the game asks whether two entities are within notice range; `answer` is
    // the game's own (straight-line distance). Hooks run in order, each seeing the answer so
    // far; one returning a boolean replaces it.
    perceive(world, a, b, range, search, answer = true) {
      if (search) arpg.pathOriginal = search;
      let current = answer;
      for (const hook of perceiveHooks) {
        try {
          const r = hook(world, a, b, range, search ?? arpg.pathOriginal, current);
          if (typeof r === 'boolean') current = r;
        } catch (err) {
          console.error('[arpg] perceive hook failed', err);
        }
      }
      return current;
    },
    // Called for every path search. Hooks are chained; the last `next` is the game's A*.
    path(world, from, dest, entity, opts, original) {
      arpg.pathOriginal = original; // for debugging: the game's own search
      let next = (...a) => original(...a);
      for (const hook of pathHooks) {
        const inner = next;
        next = (w, f, d, e, o) => {
          try {
            return hook(w, f, d, e, o, inner);
          } catch (err) {
            console.error('[arpg] path hook failed', err);
            return inner(w, f, d, e, o);
          }
        };
      }
      return next(world, from, dest, entity, opts);
    },
    // Called by the game with the GM prompt's {head, sections, tail} before rendering, and the
    // context limits it was built with. While the prompt is over the character budget, the game
    // rebuilds it with lower limits, so this can run several times for one GM turn.
    prompt(parts, world, limits) {
      arpg.lastWorld = world;
      runHooks('prompt', promptHooks, [parts, world, limits ?? null]);
      return parts;
    },
    // Called by the game once a liquid/road chunk's two canvases (the colour layer and the
    // flow map) are fully painted, before each is blurred and cropped into the tile. Hooks may
    // repaint either canvas; one returning a finite number ≥ 0 overrides this chunk's blur
    // radius, the last override winning. Returns that radius, or undefined to keep the game's.
    liquidCanvas(payload) {
      let blur;
      for (const hook of liquidCanvasHooks) {
        try {
          const r = hook(payload);
          if (typeof r === 'number' && Number.isFinite(r) && r >= 0) blur = r;
        } catch (e) {
          warnOnce('liquid-canvas', hook, e);
        }
      }
      return blur;
    },
    // Called by the game when it fades a region's ground at its edges: `mask` is the region's
    // Uint8Array cell mask (row 0 = the region's lowest y), `def` the game's own Float32Array
    // of vertex alphas. The first hook returning a Float32Array of `def.length` replaces it;
    // the game refills the ground whenever the array changes by identity, so a hook must
    // return the same array for the same mask.
    groundFade(region, mask, def) {
      for (const hook of groundFadeHooks) {
        try {
          const r = hook(region, mask, def);
          if (r instanceof Float32Array && def && r.length === def.length) return r;
        } catch (e) {
          warnOnce('ground-fade', hook, e);
        }
      }
      return def;
    },
    // Called by the scene's sprite sync and pointer hit test for every entity: is this entity
    // hidden (off screen, unhoverable, unclickable)? True if any hook says so. Runs per entity
    // per frame, so with no hooks it answers without looping.
    hidden(world, entity) {
      if (!hiddenHooks.length) return false;
      for (const hook of hiddenHooks) {
        try {
          if (hook(world, entity)) return true;
        } catch (e) {
          warnOnce('hidden', hook, e);
        }
      }
      return false;
    },
    // Called by the wall-edge builder with the region list every wall-drawing path uses (walls,
    // wall-caster shadows, door info, the minimap). Each hook gets the previous hook's regions
    // and the last world the loader has seen; one returning an array replaces them, anything
    // else (or a throw) is skipped. Only what is drawn changes, never where anyone can walk.
    wallRegions(regions) {
      let out = regions;
      for (const hook of wallRegionsHooks) {
        try {
          const r = hook(out, arpg.lastWorld);
          if (Array.isArray(r)) out = r;
        } catch (e) {
          warnOnce('wall-regions', hook, e);
        }
      }
      return out;
    },
    // Called while the shared door list is built: true puts this (possibly unlocked) door on
    // the list of doors that may stop someone.
    doorGated(world, door) {
      for (const hook of doorHooks) {
        if (!hook.gated) continue;
        try {
          if (hook.gated(world, door)) return true;
        } catch (e) {
          warnOnce('door', hook, e);
        }
      }
      return false;
    },
    // The per-walker door pass test both call sites share (the movement grid's shut doors and
    // the swing test). `native` starts as the game's own answer — the door has no `locked`
    // mechanic, or the walker's keys open it (`keyPass`, called only when locked) — and each
    // hook may replace it: a boolean wins, anything else keeps the answer so far.
    doorPasses(world, door, walker, keyPass) {
      let current = !hasMechanic(door, 'locked') || keyPass();
      for (const hook of doorHooks) {
        if (!hook.passes) continue;
        try {
          const r = hook.passes(world, door, walker, current);
          if (typeof r === 'boolean') current = r;
        } catch (e) {
          warnOnce('door', hook, e);
        }
      }
      return current;
    },
    // Called for each doorway of the GM's doorway list: false drops it (its doors stay out of
    // the GM prompt's door details). True with no hooks.
    doorwayShown(world, doorway) {
      for (const hook of doorwayHooks) {
        try {
          if (hook(world, doorway) === false) return false;
        } catch (e) {
          warnOnce('doorway', hook, e);
        }
      }
      return true;
    },
    // The mod-facing API.
    registerMod(name) { arpg.mods.push(name); },
    addCall,
    onConfig(hook) { cfgHooks.push(hook); },
    // hook(world, scenario, editing): copy scenario data onto the world. World fields are saved.
    onWorldCreate(hook) { worldHooks.push(hook); },
    // hook({head, sections, tail}, world, limits): each part is a list of {kind, title, content}.
    // `limits` are the context limits this build uses (historyTurns, worldChars, …); scale your
    // section with them so it shrinks when the game does. See the README's prompt-section rules.
    onPrompt(hook) { promptHooks.push(hook); },
    // hook(world): runs every simulation step, so keep it cheap.
    onTick(hook) { tickHooks.push(hook); },
    // hook(world, from, dest, entity, opts, next) → list of cells to walk, or null.
    // `next` is the game's own search (or the next mod's); call it for plain grid paths.
    onPath(hook) { pathHooks.push(hook); },
    // hook(world, a, b, range, search, answer) → true or false to replace `answer` (whether
    // a and b notice each other so far), anything else to leave it. `search` is the game's
    // own path search, as `next` is for onPath. Runs very often: keep it cheap.
    // `order` (default 0) sorts hooks: higher runs later and has the last word.
    onPerceive(hook, { order = 0 } = {}) {
      hook.arpgOrder = order;
      perceiveHooks.push(hook);
      perceiveHooks.sort((x, y) => x.arpgOrder - y.arpgOrder);
    },
    // hook(payload): a liquid/road chunk's canvases, both fully painted, as 2D contexts —
    // `color` and `flow` ((chunkCells+margin*2)*cellPx square; the flow map's R/G is the flow
    // vector and B the liquid kind). The payload also carries `cellPx`, `margin`,
    // `chunkCells`, `chunk` (the chunk's tile [cx, cy]), `unbounded` and `blur` (the game's own
    // radius). Cell (v, y) — v = x, y up, both from the chunk's own corner, running from
    // -margin to chunkCells+margin-1 — is the cellPx square at pixel
    // ((v+margin)*cellPx, (chunkCells+margin-1-y)*cellPx): canvas rows run top-down while y
    // runs up. Return a finite number ≥ 0 to override this chunk's blur radius; `order`
    // (default 0) sorts hooks, higher running later and having the last word.
    onLiquidCanvas(hook, { order = 0 } = {}) {
      hook.arpgOrder = order;
      liquidCanvasHooks.push(hook);
      liquidCanvasHooks.sort((x, y) => x.arpgOrder - y.arpgOrder);
    },
    // hook(region, mask, def) → Float32Array of def.length to replace a region's ground fade,
    // or anything else to keep it. `mask` is the region's Uint8Array cell mask (row 0 = the
    // region's lowest y); the fade holds one alpha per ground vertex, where vertex (sx, my) —
    // index my*(w+1)+sx — is the point x = sx, y = h-my in region cells (row 0 is the top
    // edge). Return the same array for the same mask or the ground is rebuilt every sync. The
    // first valid result wins; `order` (default 0) sorts hooks, lower running first.
    onGroundFade(hook, { order = 0 } = {}) {
      hook.arpgOrder = order;
      groundFadeHooks.push(hook);
      groundFadeHooks.sort((x, y) => x.arpgOrder - y.arpgOrder);
    },
    // hook(world, entity) → truthy to hide the entity: the scene's sprite sync treats it as
    // off screen (no container, label, shadows or light) and the pointer hit test skips it, so
    // it can't be hovered, clicked or selected. Runs per entity per frame: keep it cheap.
    // `order` (default 0) sorts hooks, higher running later.
    onHidden(hook, { order = 0 } = {}) {
      hook.arpgOrder = order;
      hiddenHooks.push(hook);
      hiddenHooks.sort((x, y) => x.arpgOrder - y.arpgOrder);
    },
    // hook(regions, world) → regions: rewrite the wall regions every wall-drawing path uses
    // (walls, wall-caster shadows, door info, the minimap), before the wall edges are derived.
    // Each hook gets the previous hook's regions and the last world the loader has seen;
    // return an array to replace them, anything else to keep them. This only changes what is
    // drawn, never where anyone can walk. `order` (default 0) sorts hooks, higher running
    // later.
    onWallRegions(hook, { order = 0 } = {}) {
      hook.arpgOrder = order;
      wallRegionsHooks.push(hook);
      wallRegionsHooks.sort((x, y) => x.arpgOrder - y.arpgOrder);
    },
    // {gated(world, door) → boolean, passes(world, door, walker, native) → boolean|undefined},
    // deciding doors per character. `gated` puts an otherwise-unlocked door on the list of
    // doors that may stop someone; `passes` decides, per walker, whether a door passes —
    // walking (the movement grid's shut doors) and door swing (shut doors block sight) ask the
    // same question — where `native` is the answer so far (the game's own: unlocked, or the
    // walker's keys open it). Return a boolean to replace it, undefined to keep it. `walker`
    // is unset for queries that aren't walks. `order` (default 0) sorts hooks, higher running
    // later and having the last word.
    onDoor(hook, { order = 0 } = {}) {
      hook.arpgOrder = order;
      doorHooks.push(hook);
      doorHooks.sort((x, y) => x.arpgOrder - y.arpgOrder);
    },
    // hook(world, doorway) → false to drop the doorway from the GM's list (each doorway is
    // `{crossings, room, doors}`); anything else keeps it. `order` (default 0) sorts hooks.
    onDoorway(hook, { order = 0 } = {}) {
      hook.arpgOrder = order;
      doorwayHooks.push(hook);
      doorwayHooks.sort((x, y) => x.arpgOrder - y.arpgOrder);
    },
    // Adds a header file to the GM's api-call list, after `after` (a header name) or at the end.
    addApiHeader(name, text, after) {
      const dir = 'overseer/api-actions/';
      cfgHooks.push((path, original) => {
        if (path === `${dir}${name}.txt`) return text;
        if (path !== `${dir}ordered-api-calls.json`) return undefined;
        let list;
        try { list = JSON.parse(original()); } catch { return undefined; }
        if (list.includes(name)) return undefined;
        const at = after ? list.indexOf(after) : -1;
        list.splice(at >= 0 ? at + 1 : list.length, 0, name);
        return JSON.stringify(list);
      });
    },
    // The game's own status test: does the entity carry a mechanic of this type? A door is
    // locked exactly when hasMechanic(door, "locked").
    hasMechanic,
    // The walls and shut doors 1.0's own sight test takes (the world's wall regions, plus the
    // door edges nobody holds open). Building it scans every entity, so hold on to the result
    // when testing many lines. undefined when the patched bundle hasn't supplied the builder.
    sightBlockers(world) {
      return typeof arpg.game.sightBlockers === 'function' ? arpg.game.sightBlockers(world) : undefined;
    },
    // 1.0 stealth's line-of-sight test: walls and shut doors block, bars, gates and open
    // doorways don't. Points are continuous (an entity's centre is
    // [pos[0]+size[0]/2, pos[1]+size[1]/2]); pass `blockers` when testing many lines, since
    // building them scans every entity. undefined when the test or the blockers can't be had.
    lineOfSight(world, from, to, blockers) {
      if (typeof arpg.game.lineClear !== 'function') return undefined;
      const list = blockers ?? arpg.sightBlockers(world);
      return list === undefined ? undefined : !!arpg.game.lineClear(from, to, list);
    },
    // The plane a point is on: 1.0's floors and cellars are pocket regions off the main map,
    // and two points on different planes are never near each other. null = the main map.
    planeOf(world, point) {
      if (!world || !point) return null;
      for (const r of world.regions ?? []) {
        if (!r.pocket) continue;
        const [x, y] = r.position, [w, h] = r.size;
        if (point[0] >= x && point[1] >= y && point[0] < x + w && point[1] < y + h) return r;
      }
      return null;
    },
  };

  const prior = globalThis.__arpg;
  globalThis.__arpg = arpg;
  if (prior && prior.api) arpg.api = prior.api;
  if (prior && prior.game) Object.assign(arpg.game, prior.game);
  console.info('[arpg] code-mod loader ready');
})();
