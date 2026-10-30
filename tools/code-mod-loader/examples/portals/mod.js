// portals: doors, stairs and teleporters between parts of the map the grid doesn't connect.
//
// scenario.json:
//   "arpgMods": {
//     "portals": [
//       {"name": "Cellar stairs", "from": {"object": "Kitchen trapdoor"}, "to": {"object": "Cellar ladder"}, "twoWay": true},
//       {"name": "Ferry", "from": {"region": "North Dock"}, "to": {"region": "South Dock"}, "twoWay": true},
//       {"name": "Mirror", "from": {"cell": [10, 4]}, "to": {"cell": [80, 70]}},
//       {"name": "Smugglers' tunnel", "from": {"object": "Loose flagstone"}, "to": {"object": "Old well"},
//        "twoWay": true, "secret": true, "knownBy": ["Marrow Jack"]}
//     ]
//   }
//
// The player goes through any pad they step onto. NPCs go through only when their walk
// was planned through the portal (GM beats, schedules, followers), so the GM just uses
// MOVE_TO and nobody falls through one by wandering. Only those who know a portal route
// through it: everyone for an ordinary one; for a secret one (or one with a knownBy list),
// its knownBy characters, onlookers who saw it used, and anyone the GM's portal_tell
// names. The player knows a secret one after using it or the GM's portal_reveal.
(() => {
  const arpg = globalThis.__arpg;
  arpg.registerMod('portals');

  const REFRESH_SECS = 2; // real seconds before names are looked up again
  const MAX_PROMPT_LINES = 30;

  const key = c => `${c[0]},${c[1]}`;
  const cellOf = pos => [Math.round(pos[0]), Math.round(pos[1])];
  const cheb = (a, b) => Math.max(Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1]));
  const same = (a, b) => String(a ?? '').trim().toLowerCase() === String(b ?? '').trim().toLowerCase();

  function rectCells(pos, size) {
    const out = [];
    for (let x = pos[0]; x < pos[0] + size[0]; x++) for (let y = pos[1]; y < pos[1] + size[1]; y++) out.push([x, y]);
    return out;
  }

  function innermostRegion(world, c) {
    let best = null;
    for (const r of world.regions ?? []) {
      const [x, y] = r.position, [w, h] = r.size;
      if (c[0] < x || c[1] < y || c[0] >= x + w || c[1] >= y + h) continue;
      if (!best || w * h < best.size[0] * best.size[1]) best = r;
    }
    return best;
  }

  const warned = new Set();
  function warnOnce(msg) {
    if (warned.has(msg)) return;
    warned.add(msg);
    console.warn(`[arpg portals] ${msg}`);
  }

  // One end of a portal: the cells that trigger it, where travellers land, and its description.
  function resolveEnd(world, spec, id) {
    let cells, target, label;
    if (Array.isArray(spec?.cell)) {
      const c = [Math.round(spec.cell[0]), Math.round(spec.cell[1])];
      cells = [c];
      target = { entity: { pos: c, size: [1, 1] } };
      label = innermostRegion(world, c)?.name ?? `cell ${key(c)}`;
    } else if (spec?.object) {
      const obj = world.entities?.find(e => e.type === 'object' && !e.dead && same(e.name, spec.object));
      if (!obj) return null;
      cells = rectCells(cellOf(obj.pos), obj.size ?? [1, 1]);
      target = { entity: obj };
      const r = innermostRegion(world, cells[0]);
      label = r ? `${obj.name} in ${r.name}` : obj.name;
    } else if (spec?.region) {
      const r = world.regions?.find(x => same(x.name, spec.region));
      if (!r) return null;
      cells = rectCells(r.position, r.size);
      target = { region: r };
      label = r.name;
    } else {
      return null;
    }
    const sum = cells.reduce((a, c) => [a[0] + c[0], a[1] + c[1]], [0, 0]);
    const center = [Math.round(sum[0] / cells.length), Math.round(sum[1] / cells.length)];
    return { id, cells, set: new Set(cells.map(key)), target, label, center };
  }

  const portalName = (p, i) => p.name || `Portal ${i + 1}`;
  const lower = s => String(s ?? '').trim().toLowerCase();

  // Who knows which portal. Saved with the game in arpgMods.portalState:
  //   discovered: {portal index: true}         the player knows it
  //   known:      {portal index: [names...]}   characters who learned it in play
  const portalState = world => (world.arpgMods.portalState ??= {});
  const playerKnows = (world, i) => !!world.arpgMods?.portalState?.discovered?.[i];
  function discover(world, i) {
    (portalState(world).discovered ??= {})[i] = true;
    cache.delete(world);
  }
  // Returns true when `name` didn't know the portal before.
  function learn(world, i, name) {
    const list = ((portalState(world).known ??= {})[i] ??= []);
    if (list.some(n => same(n, name))) return false;
    list.push(String(name).trim());
    cache.delete(world);
    return true;
  }

  function edgesOf(world) {
    const edges = [];
    (world.arpgMods?.portals ?? []).forEach((p, i) => {
      if (!p || p.enabled === false) return;
      const name = portalName(p, i);
      const secret = !!p.secret && !playerKnows(world, i);
      // A portal without a knownBy list is common knowledge, unless it's secret.
      const everyone = !p.secret && !Array.isArray(p.knownBy);
      const knownByNames = [...(Array.isArray(p.knownBy) ? p.knownBy : []), ...(world.arpgMods?.portalState?.known?.[i] ?? [])]
        .map(n => String(n).trim()).filter((n, k, all) => n && all.findIndex(m => same(m, n)) === k);
      const knownBy = new Set(knownByNames.map(lower));
      const a = resolveEnd(world, p.from, `${i}:from`);
      const b = resolveEnd(world, p.to, `${i}:to`);
      if (!a || !b) return warnOnce(`"${name}": ${!a ? 'from' : 'to'} end not found on this map`);
      for (const [end, spec] of [[a, p.from], [b, p.twoWay ? p.to : null]]) {
        if (spec?.object && end.target.entity.objectTemplate && !(end.target.entity.objectTemplate.walkability > 0)) {
          warnOnce(`"${name}": "${spec.object}" blocks movement, so nobody can step on it; give its template a walkability above 0`);
        }
      }
      const restricted = !everyone;
      const player = !p.secret || playerKnows(world, i);
      edges.push({ id: `${i}>`, portal: i, name, secret, restricted, everyone, player, knownBy, knownByNames, from: a, to: b });
      if (p.twoWay) edges.push({ id: `${i}<`, portal: i, name, secret, restricted, everyone, player, knownBy, knownByNames, from: b, to: a });
    });
    return edges;
  }

  const knows = (edge, entity) =>
    entity?.type === 'player' ? edge.player : edge.everyone || edge.knownBy.has(lower(entity?.name));

  // NPCs within this many cells of either end, in the same room, see someone use a portal.
  const WITNESS_RANGE = 6;
  // The engine has no stealth state; scenarios bring their own skills ("Stealth",
  // "Street Smarts"...). So sneaking is read from words in what the GM resolved.
  const STEALTH_WORDS = /\b(stealth\w*|sneak\w*|hid(e|es|ing|den)|conceal\w*|unseen|unnoticed|invisib\w*|creep\w*|skulk\w*|prowl\w*|lurk\w*|camouflag\w*|tiptoe\w*|silently)\b/i;
  const STEALTH_MINUTES = 15;

  // Whether the traveller is sneaking: a stealthy status or current action, or for the
  // player, a stealthy action (by its words or its roll's skill) in the last few game
  // minutes whose roll didn't fail.
  function sneaking(world, entity) {
    const extra = (world.arpgMods?.portalSettings?.stealthWords ?? []).map(w => String(w).trim()).filter(Boolean);
    const stealthy = text => !!text && (STEALTH_WORDS.test(text) || extra.some(w => String(text).toLowerCase().includes(w.toLowerCase())));
    if ((entity.statusEffects ?? []).some(s => stealthy(s?.desc))) return true;
    if (stealthy(entity.activity?.summary)) return true;
    if (entity.type !== 'player') return false;
    const now = world.gameTimeSecs ?? 0;
    const history = world.overseerHistory ?? [];
    for (let k = history.length - 1; k >= 0; k--) {
      const turn = history[k];
      if (now - (turn.t ?? 0) > STEALTH_MINUTES * 60) break;
      if (!turn.playerAction) continue;
      let response = turn.response;
      if (typeof response === 'string') {
        try { response = JSON.parse(response); } catch { response = null; }
      }
      const roll = response?.roll;
      if (roll && /fail/i.test(String(roll.outcome ?? ''))) return false;
      return stealthy(turn.playerAction) || stealthy(roll?.relevant_skill);
    }
    return false;
  }

  // When a restricted portal is used openly, onlookers learn it and remember what they saw.
  function witnesses(world, traveller, edge, landed) {
    if (sneaking(world, traveller)) return;
    const spots = [edge.from.center, landed].map(c => ({ c, room: innermostRegion(world, c) }));
    const where = edge.from.label;
    for (const e of world.entities ?? []) {
      if (e.type !== 'npc' || e.dead || e === traveller || knows(edge, e)) continue;
      const c = cellOf(e.pos);
      const saw = spots.find(s => cheb(s.c, c) <= WITNESS_RANGE && innermostRegion(world, c) === s.room);
      if (!saw || !learn(world, edge.portal, e.name)) continue;
      const text = saw === spots[0]
        ? `Saw ${traveller.name} slip through a hidden way at ${where} and vanish.`
        : `Saw ${traveller.name} appear out of nowhere by ${edge.to.label}.`;
      e.memories = [...(e.memories ?? []), { t: world.gameTimeSecs ?? 0, text }];
    }
  }

  // Resolved portals per world, refreshed every few seconds so moved or destroyed objects count.
  const cache = new WeakMap();
  function state(world) {
    const now = world.activeRealSecs ?? 0;
    let s = cache.get(world);
    if (!s || now - s.at > REFRESH_SECS || now < s.at) {
      s = { at: now, edges: edgesOf(world), legs: new Map() };
      cache.set(world, s);
    }
    return s;
  }

  const nearest = (cells, c) => cells.reduce((b, x) => (cheb(x, c) < cheb(b, c) ? x : b), cells[0]);

  // Cheapest chain of portals from start to goal, by walked cells. Returns the first
  // portal to take and its total cost, or null when no chain beats `limit`.
  function route(world, start, goal, entity, opts, next, limit) {
    const { legs } = state(world);
    const edges = state(world).edges.filter(e => knows(e, entity));
    const leg = (a, b) => {
      if (a[0] === b[0] && a[1] === b[1]) return 0;
      const k = `${key(a)}>${key(b)}`;
      if (!legs.has(k)) {
        const p = next(world, a, b, entity, opts);
        legs.set(k, p ? p.length : Infinity);
      }
      return legs.get(k);
    };
    let best = { cost: limit, first: null };
    const dist = new Map(); // edge id → {cost, first}
    const frontier = [];
    for (const e of edges) {
      const pad = nearest(e.from.cells, start);
      if (cheb(start, pad) + 1 >= best.cost) continue;
      const c = leg(start, pad) + 1;
      if (c < best.cost) frontier.push({ e, cost: c, first: e });
    }
    while (frontier.length) {
      frontier.sort((a, b) => a.cost - b.cost);
      const cur = frontier.shift();
      if (cur.cost >= best.cost) break;
      if (dist.has(cur.e.id) && dist.get(cur.e.id) <= cur.cost) continue;
      dist.set(cur.e.id, cur.cost);
      const exit = cur.e.to.center;
      if (cur.cost + cheb(exit, goal) < best.cost) {
        const total = cur.cost + leg(exit, goal);
        if (total < best.cost) best = { cost: total, first: cur.first };
      }
      for (const f of edges) {
        if (f === cur.e || f.from.id === cur.e.to.id) continue; // no stepping straight back
        const pad = nearest(f.from.cells, exit);
        if (cur.cost + cheb(exit, pad) + 1 >= best.cost) continue;
        const c = cur.cost + leg(exit, pad) + 1;
        if (c < best.cost && !(dist.has(f.id) && dist.get(f.id) <= c)) frontier.push({ e: f, cost: c, first: cur.first });
      }
    }
    return best.first ? best : null;
  }

  const pending = new WeakMap(); // entity → id of the portal its current walk heads for
  const lastZone = new WeakMap(); // entity → id of the portal end it stood on last tick

  arpg.onPath((world, from, dest, entity, opts, next) => {
    const direct = next(world, from, dest, entity, opts);
    if (!entity || entity.attachment || opts?.wallsOnly || opts?.maxCost !== undefined) return direct;
    if (!state(world).edges.length) return direct;
    const start = cellOf(from);
    const r = route(world, start, cellOf(dest), entity, opts, next, direct ? direct.length : Infinity);
    if (!r) {
      pending.delete(entity);
      return direct;
    }
    pending.set(entity, r.first.id);
    return next(world, start, nearest(r.first.from.cells, start), entity, opts) ?? direct;
  });

  function travel(world, entity, edge, edges) {
    pending.delete(entity);
    const err = arpg.api?.teleport?.run(world, { entity, target: edge.to.target });
    if (err) return warnOnce(`"${edge.name}": ${err}`);
    if (entity.type === 'player' && !edge.player) discover(world, edge.portal);
    const landed = cellOf(entity.pos);
    if (edge.restricted) witnesses(world, entity, edge, landed);
    lastZone.set(entity, edges.find(e => e.from.set.has(key(landed)))?.from.id ?? null);
  }

  // The player goes through any pad they step onto (finding a secret one that way).
  // NPCs only go through when their walk was planned through that portal, so nobody
  // falls through one by wandering across it.
  arpg.onTick(world => {
    const { edges } = state(world);
    if (!edges.length) return;
    for (const e of world.entities ?? []) {
      if ((e.type !== 'npc' && e.type !== 'player') || e.dead || e.attachment) continue;
      const k = key(cellOf(e.pos));
      const here = edges.filter(x => x.from.set.has(k));
      const zone = here[0]?.from.id ?? null;
      if (!lastZone.has(e)) {
        lastZone.set(e, zone); // a game loaded with someone standing on a pad doesn't fire it
        continue;
      }
      const wanted = here.find(x => x.id === pending.get(e));
      const stepped = e.type === 'player' && here.length && zone !== lastZone.get(e);
      if (wanted || stepped) travel(world, e, wanted ?? here[0], edges);
      else lastZone.set(e, zone);
    }
  });

  arpg.onPrompt((parts, world) => {
    const { edges } = state(world);
    if (!edges.length) return;
    if (arpg.promptBudgets) {
      for (const kind of ['passages', 'secret_passages']) if (!(kind in arpg.promptBudgets)) arpg.promptBudgets[kind] = 1e6;
    }
    const open = [], secret = [];
    for (const e of edges) {
      if (e.id.endsWith('<')) continue;
      const twoWay = edges.some(x => x.id === `${e.portal}<`);
      const who = e.restricted ? ` (known to: ${[...(e.player ? ['the player'] : []), ...e.knownByNames].join(', ') || 'nobody yet'})` : '';
      const line = `- ${e.name}: ${e.from.label} ${twoWay ? '<->' : '-> (one way)'} ${e.to.label}${who}`;
      (e.secret ? secret : open).push(line);
    }
    if (open.length) {
      parts.sections.push({
        kind: 'passages',
        title: 'Passages. A character who steps onto one end comes out at the other. To send someone through, MOVE_TO a place beyond it and they walk through it themselves; never use teleport for this, and never send anyone back through a one-way passage. Passage names are not entities to target. Only those who know a passage use it:',
        content: open.slice(0, MAX_PROMPT_LINES).join('\n'),
      });
    }
    if (secret.length) {
      parts.sections.push({
        kind: 'secret_passages',
        title: 'Secret passages the player has not found. Hint at them through play; never state them outright. Only those who know one can use it. When the player finds one by searching or is shown it, call portal_reveal; when a character tells another, call portal_tell:',
        content: secret.slice(0, MAX_PROMPT_LINES).join('\n'),
      });
    }
  });

  arpg.addApiHeader('header_portals', [
    '-- Secret passages --',
    '{"call":"portal_reveal","name":"passage name"} // the player found or was shown a secret passage',
    '{"call":"portal_tell","name":"passage name","target":"character name"} // someone who knows a secret passage told this character (gossip, a bribe, a confession). Only then can they use it',
  ].join('\n'), 'header_movement');

  // Portals whose knowledge is tracked per character: secret ones and those with a knownBy list.
  const findRestricted = (world, name) =>
    (world.arpgMods?.portals ?? []).findIndex((p, n) => p && (p.secret || Array.isArray(p.knownBy)) && same(portalName(p, n), name));

  arpg.addCall('portal_reveal', api => ({
    // Reuse the game's plain text field type for the name.
    schema: api.flavor_text.schema.extend({ name: api.flavor_text.schema.shape.text }).omit({ text: true }),
    run(world, { name }) {
      const i = findRestricted(world, name);
      if (i < 0 || !world.arpgMods.portals[i].secret) return `no secret passage named "${name}"`;
      discover(world, i);
      return null;
    },
  }));

  arpg.addCall('portal_tell', api => ({
    // An entity field the engine resolves from a name, plus the passage name.
    schema: api.hp_delta.schema.pick({ target: true }).extend({ name: api.flavor_text.schema.shape.text }),
    run(world, { name, target }) {
      const i = findRestricted(world, name);
      if (i < 0) return `no secret passage named "${name}"`;
      if (target.type === 'player') return discover(world, i), null;
      if (target.type !== 'npc') return 'portal_tell target must be a character';
      if (learn(world, i, target.name)) {
        target.memories = [...(target.memories ?? []), { t: world.gameTimeSecs ?? 0, text: `Learned of a hidden way: ${portalName(world.arpgMods.portals[i], i)}.` }];
      }
      return null;
    },
  }));

  arpg.portals = { edgesOf, route, state };
})();
