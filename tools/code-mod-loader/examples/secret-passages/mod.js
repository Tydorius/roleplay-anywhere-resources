// secret-passages: doors in walls that are wall until a character knows them.
//
// scenario.json:
//   "arpgMods": {
//     "secretPassages": {
//       "passages": {
//         "<door id>": {"knownBy": ["Alys Sedge"], "hint": "a draught behind the bookcase", "findChance": 0.25}
//       },
//       "settings": {"findChance": 0.25, "findRange": 2, "onlookerRange": 6}
//     }
//   }
//
// A door is secret while it carries a `concealed` mechanic — the status effect the game
// already understands, {"def": {"desc": "secret passage", "emoji": "🕳️", "type": "constant",
// "mechanics": [{"type": "concealed"}]}}. Everything in `secretPassages` is optional: a
// door with the effect and no entry is a secret nobody knows.
//
// Until a character knows a secret door it is wall to them: they can't walk through it and
// it doesn't swing open for them (the lock rule still applies on top). Until the player
// knows it, it's drawn as wall, can't be hovered or clicked, and is left out of the GM's
// doorway lines. Knowledge is per character: `knownBy` from the start, the player by a find
// roll beside it or by watching it used, anyone by being shown or told (the GM's
// secret_reveal), onlookers by seeing it used. Removing the effect (the GM's own
// status_remove) makes the door public. Knowledge is saved with the game in
// world.arpgMods.secretPassages.known: {"<door id>": [entity ids]}.
(() => {
  const arpg = globalThis.__arpg;
  arpg.registerMod('secret-passages');

  const REFRESH_MS = 1000;  // wall state is re-checked at most this often
  const NEAR_CELLS = 3;     // a knower this close to a secret door is watched crossing it
  const PROMPT_RANGE = 20;  // secret doors listed to the GM: within this many cells
  const DEFAULTS = { findChance: 0.25, findRange: 2, onlookerRange: 6 };

  const same = (a, b) => String(a ?? '').trim().toLowerCase() === String(b ?? '').trim().toLowerCase();
  const num = (v, d) => (Number.isFinite(Number(v)) ? Number(v) : d);
  const centre = e => [e.pos[0] + (e.size?.[0] ?? 1) / 2, e.pos[1] + (e.size?.[1] ?? 1) / 2];
  const cheb = (a, b) => Math.max(Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1]));
  const isCharacter = e => e?.type === 'npc' || e?.type === 'player';

  // A door: a zero-wide object on a wall edge. Vertical is size [0, n]: the crossing runs
  // between [x-1, y] and [x, y]; horizontal [n, 0] between [x, y-1] and [x, y]. Its
  // midpoint sits on the edge between the two cells.
  const isDoor = e => e?.type === 'object' && !!e.objectTemplate?.door && !e.dead;
  const isSecretDoor = e => isDoor(e) && arpg.hasMechanic(e, 'concealed');

  function crossing(d) {
    const [x, y] = d.pos;
    return d.size[0] === 0 ? [[x - 1, y], [x, y]] : [[x, y - 1], [x, y]];
  }
  const midpoint = d => (d.size[0] === 0 ? [d.pos[0], d.pos[1] + 0.5] : [d.pos[0] + 0.5, d.pos[1]]);

  // Which side of a door's crossing a point (or a cell's centre) is on: 0 or 1.
  function side(d, p) {
    return d.size[0] === 0 ? (p[0] < d.pos[0] ? 0 : 1) : (p[1] < d.pos[1] ? 0 : 1);
  }

  const inside = (r, c) =>
    c[0] >= r.position[0] && c[1] >= r.position[1] &&
    c[0] < r.position[0] + r.size[0] && c[1] < r.position[1] + r.size[1];

  // The wall openings a hidden door's crossing appears as: on every walled region whose
  // rectangle contains exactly one of the two crossing cells, the inside cell plus the side
  // towards the other cell, as a "x,y,side" key.
  function openingsOf(world, door) {
    const [a, b] = crossing(door);
    const out = [];
    for (const r of world.regions ?? []) {
      if (!r.wall) continue;
      const hasA = inside(r, a), hasB = inside(r, b);
      if (hasA === hasB) continue;
      const cell = hasA ? a : b, other = hasA ? b : a;
      const dir = other[0] > cell[0] ? 'e' : other[0] < cell[0] ? 'w' : other[1] > cell[1] ? 'n' : 's';
      out.push([r, `${cell[0]},${cell[1]},${dir}`]);
    }
    return out;
  }

  const data = world => world.arpgMods?.secretPassages;
  const hintOf = (world, id) => data(world)?.passages?.[id]?.hint;

  function settingsOf(world) {
    const s = data(world)?.settings ?? {};
    return {
      findChance: num(s.findChance, DEFAULTS.findChance),
      findRange: num(s.findRange, DEFAULTS.findRange),
      onlookerRange: num(s.onlookerRange, DEFAULTS.onlookerRange),
    };
  }

  function knownOf(world, id) {
    return data(world)?.known?.[id] ?? [];
  }
  const knows = (world, id, e) => isCharacter(e) && knownOf(world, id).includes(e.id);

  // Returns true when `e` didn't know the door before. All learning flows through here.
  function learn(world, id, e) {
    const sp = data(world) ?? ((world.arpgMods ??= {}).secretPassages = {});
    const list = ((sp.known ??= {})[id] ??= []);
    if (list.includes(e.id)) return false;
    list.push(e.id);
    refresh(world, true); // knowledge changed, signature or not
    return true;
  }

  function log(world, text) {
    world.logCounter = (world.logCounter ?? 0) + 1;
    world.log?.push({ id: world.logCounter, t: world.gameTimeSecs ?? 0, type: 'mechanic', text });
  }

  // Appends a sentence the way the memory-add sample does: 1.0 keeps a character's memory
  // as one prose string.
  function remember(e, text) {
    const prior = typeof e.memory === 'string' ? e.memory.trim() : '';
    e.memory = prior ? `${prior} ${text}` : text;
  }

  // The player learning a door, by roll, by watching a use, or through the GM: the log
  // line, plus the hint when the scenario wrote one.
  function playerFinds(world, door) {
    if (!learn(world, door.id, world.player)) return false;
    const hint = hintOf(world, door.id);
    log(world, `You found a hidden door: ${door.name}.${hint ? ` ${hint}` : ''}`);
    return true;
  }

  // Per world: the secret doors (Map id → door), the ones hidden from the player, and the
  // wall openings to draw shut for those. Rebuilt on world creation, on every knowledge
  // change, and from onTick at most once a second when the signature of secret door ids
  // has changed (an effect removed, a door died); the hooks only ever read it.
  const cache = new WeakMap();
  const sameSet = (a, b) => a.size === b.size && [...a].every(x => b.has(x));

  function refresh(world, force = false) {
    const secret = new Map();
    for (const e of world.entities ?? []) if (isSecretDoor(e)) secret.set(e.id, e);
    const sig = [...secret.keys()].join(',');
    let entry = cache.get(world);
    if (!entry) cache.set(world, (entry = { sig, secret, hidden: new Set(), close: new Map(), built: false }));
    if (!force && entry.built && entry.sig === sig) return entry;
    entry.sig = sig;
    entry.secret = secret;
    const pid = world.player?.id;
    const known = data(world)?.known ?? {};
    const hidden = new Set();
    for (const id of secret.keys()) if (!pid || !(known[id] ?? []).includes(pid)) hidden.add(id);
    const close = new Map(); // region → Set of "x,y,side" openings to leave out
    for (const id of hidden) for (const [r, key] of openingsOf(world, secret.get(id))) {
      if (!close.has(r)) close.set(r, new Set());
      close.get(r).add(key);
    }
    // Walls are cached on world.regionsRev: bump it (and redraw) when a door stops or
    // starts being drawn as wall for the player.
    if (entry.built && !sameSet(hidden, entry.hidden)) {
      world.regionsRev = (world.regionsRev ?? 0) + 1;
      globalThis.window?.__vivScene?.markWallsDirty?.();
    }
    entry.hidden = hidden;
    entry.close = close;
    entry.built = true;
    return entry;
  }

  arpg.onHidden((world, entity) => !!cache.get(world)?.hidden.has(entity.id));

  // The regions walls are drawn from, with the hidden doors' openings drawn shut: a
  // shallow copy per region that has one to close, everything else as it came.
  arpg.onWallRegions((regions, world) => {
    const close = cache.get(world)?.close;
    if (!close?.size) return regions; // nothing hidden: the same list
    let copied = false;
    const out = regions.map(r => {
      const drop = close.get(r);
      if (!drop || !Array.isArray(r.openings)) return r;
      const kept = r.openings.filter(o => !drop.has(`${o[0]},${o[1]},${o[2]}`));
      if (kept.length === r.openings.length) return r;
      copied = true;
      return { ...r, openings: kept };
    });
    return copied ? out : regions;
  });

  arpg.onDoor({
    gated: (world, door) => isSecretDoor(door),
    passes: (world, door, walker, native) => {
      if (!isSecretDoor(door)) return undefined;
      return walker && knows(world, door.id, walker) ? undefined : false;
    },
  });

  arpg.onDoorway((world, doorway) => {
    const hidden = cache.get(world)?.hidden;
    return !(hidden?.size && (doorway.doors ?? []).some(d => hidden.has(d.id)));
  });

  const warned = new Set();
  arpg.onWorldCreate(world => {
    const sp = data(world);
    // A loaded save already carries `known`; resolving knownBy again would double it.
    if (sp && sp.known === undefined) {
      const known = (sp.known = {});
      for (const [id, def] of Object.entries(sp.passages ?? {})) {
        for (const name of Array.isArray(def?.knownBy) ? def.knownBy : []) {
          const e = (world.entities ?? []).find(x => isCharacter(x) && same(x.name, name));
          if (!e) {
            const msg = `knownBy "${name}" (door ${id}): no character with that name`;
            if (!warned.has(msg)) {
              warned.add(msg);
              console.warn(`[arpg secret-passages] ${msg}`);
            }
            continue;
          }
          (known[id] ??= []).push(e.id);
        }
      }
    }
    refresh(world);
  });

  // Discovery state per world: which doors the player has already rolled for this
  // approach, and the last cell of each knower near a secret door (to see crossings).
  const runtime = new WeakMap();
  function runtimeOf(world) {
    let rt = runtime.get(world);
    if (!rt) runtime.set(world, (rt = { approach: new Set(), lastCells: new Map() }));
    return rt;
  }

  let lastPass = -Infinity;
  arpg.onTick(world => {
    const now = performance.now();
    if (now - lastPass < REFRESH_MS) return;
    lastPass = now;
    const entry = refresh(world);
    if (!entry.secret.size) return;
    const rt = runtimeOf(world);
    const set = settingsOf(world);
    const blockers = arpg.sightBlockers(world);

    // Passive: once per approach, the player within findRange and in sight of a secret
    // door they don't know rolls to find it.
    const player = world.player;
    if (player && !player.dead && player.pos) {
      const pc = centre(player);
      const plane = arpg.planeOf(world, pc);
      for (const [id, door] of entry.secret) {
        if (!entry.hidden.has(id)) continue;
        const mid = midpoint(door);
        const dist = cheb(pc, mid);
        if (dist > set.findRange + 2) rt.approach.delete(id); // gone clear: a new approach may roll
        if (dist > set.findRange || arpg.planeOf(world, mid) !== plane || rt.approach.has(id)) continue;
        if (arpg.lineOfSight(world, pc, mid, blockers) === false) continue; // no sight: not this pass
        rt.approach.add(id);
        const chance = num(data(world)?.passages?.[id]?.findChance, set.findChance);
        if (arpg.secretPassages.random() < chance) playerFinds(world, door);
      }
    }

    // Onlookers: a knower who crosses a secret door's line while moving has used it, and
    // everyone near who can see the door learns it.
    const next = new Map();
    for (const e of world.entities ?? []) {
      if (!isCharacter(e) || e.dead || !e.pos) continue;
      const c = centre(e);
      let watched = false;
      for (const [id, door] of entry.secret) {
        if (!knows(world, id, e)) continue;
        const mid = midpoint(door);
        if (cheb(c, mid) > NEAR_CELLS || arpg.planeOf(world, c) !== arpg.planeOf(world, mid)) continue;
        watched = true;
        const prev = rt.lastCells.get(e.id);
        if (prev && e.moving && side(door, prev) !== side(door, c)) seenUsed(world, e, door, blockers, set.onlookerRange);
      }
      if (watched) next.set(e.id, [Math.floor(c[0]), Math.floor(c[1])]);
    }
    rt.lastCells = next;
  });

  // Everyone near a use, in sight of the door, learns it: NPCs remember what they saw,
  // the player is told in the log.
  function seenUsed(world, user, door, blockers, onlookerRange) {
    const mid = midpoint(door);
    const plane = arpg.planeOf(world, mid);
    for (const e of world.entities ?? []) {
      if (!isCharacter(e) || e.dead || !e.pos || e === user || knows(world, door.id, e)) continue;
      const c = centre(e);
      if (cheb(c, mid) > onlookerRange || arpg.planeOf(world, c) !== plane) continue;
      if (arpg.lineOfSight(world, c, mid, blockers) === false) continue;
      if (e === world.player) {
        log(world, `You saw ${user.name} slip through a hidden door: ${door.name}.`);
        playerFinds(world, door);
      } else if (learn(world, door.id, e)) {
        remember(e, `Saw ${user.name} slip through a hidden door at ${door.name}.`);
      }
    }
  }

  arpg.addApiHeader('header_secrets', [
    '{"call":"secret_reveal","door":"door name","target":"character name (optional, default the player)"} ' +
      '// the player searched the right spot, or someone showed or told a character a hidden door',
    'To make a passage public to everyone, remove its "secret passage" effect with status_remove.',
  ].join('\n'), 'header_entity_state');

  arpg.addCall('secret_reveal', api => ({
    // The door and the target are plain names, resolved inside run: the engine's entity
    // resolver is for characters a call targets, and a door is easier to check by hand.
    schema: api.flavor_text.schema.omit({ text: true }).extend({
      door: api.flavor_text.schema.shape.text,
      target: api.flavor_text.schema.shape.text.optional(),
    }),
    run(world, { door, target }) {
      const d = (world.entities ?? []).find(e => same(e.name, door));
      if (!d) return `secret_reveal: nothing named "${door}" on the map`;
      if (!isDoor(d)) return `secret_reveal: "${door}" is not a door`;
      if (!arpg.hasMechanic(d, 'concealed')) return `secret_reveal: "${door}" is not a secret door`;
      const who = target === undefined
        ? world.player
        : (world.entities ?? []).find(e => isCharacter(e) && same(e.name, target));
      if (!who) return `secret_reveal: no character named "${target}"`;
      if (who === world.player) playerFinds(world, d);
      else if (learn(world, d.id, who)) remember(who, `Learned of the hidden door at ${d.name}.`);
      return null; // already known is not an error
    },
  }));

  const DIRECTIONS = ['E', 'NE', 'N', 'NW', 'W', 'SW', 'S', 'SE'];
  arpg.onPrompt((parts, world, limits) => {
    const entry = cache.get(world) ?? refresh(world);
    if (!entry.secret.size || !world.player?.pos) return;
    const pc = centre(world.player);
    const plane = arpg.planeOf(world, pc);
    const names = new Map((world.entities ?? []).filter(isCharacter).map(e => [e.id, e.name]));
    const lines = [];
    for (const [id, door] of entry.secret) {
      const mid = midpoint(door);
      const dx = mid[0] - pc[0], dy = mid[1] - pc[1];
      const dist = Math.hypot(dx, dy);
      if (dist > PROMPT_RANGE || arpg.planeOf(world, mid) !== plane) continue;
      const dir = DIRECTIONS[(Math.round(Math.atan2(dy, dx) / (Math.PI / 4)) + 8) % 8];
      const by = (data(world)?.known?.[id] ?? [])
        .filter(who => who !== world.player.id)
        .map(who => names.get(who) ?? who);
      const hint = hintOf(world, id);
      lines.push({
        dist,
        line: `- ${door.name} (${Math.round(dist)} m ${dir}): known by ${by.length ? by.join(', ') : 'nobody'}; ` +
          `player: ${entry.hidden.has(id) ? "doesn't know" : 'knows'}${hint ? `; hint: ${hint}` : ''}`,
      });
    }
    lines.sort((a, b) => a.dist - b.dist);
    // At most a sixth of the world-characters limit, whole lines only; the game drops the
    // section when the content is empty, and rebuilds the prompt (running this again) with
    // lower limits while it is over budget.
    const cap = Math.max(200, Math.floor((limits?.worldChars ?? 2000) / 6));
    const kept = [];
    let used = 0;
    for (const { line } of lines) {
      const cost = line.length + (kept.length ? 1 : 0);
      if (used + cost > cap) break;
      kept.push(line);
      used += cost;
    }
    parts.sections.push({
      kind: 'secrets',
      title: 'Secret passages (private — hint, never state them outright):',
      content: kept.join('\n'),
    });
  });

  arpg.secretPassages = { refresh, learn, knows, playerFinds, crossing, midpoint, side, openingsOf, random: Math.random };
})();
