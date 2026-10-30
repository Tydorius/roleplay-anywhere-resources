// portals: doors, stairs and teleporters between parts of the map the grid doesn't connect.
//
// scenario.json:
//   "arpgMods": {
//     "portals": [
//       {"name": "Cellar stairs", "from": {"object": "Kitchen trapdoor"}, "to": {"object": "Cellar ladder"}, "twoWay": true},
//       {"name": "Ferry", "from": {"region": "North Dock"}, "to": {"region": "South Dock"}, "twoWay": true},
//       {"name": "Mirror", "from": {"cell": [10, 4]}, "to": {"cell": [80, 70]}}
//     ]
//   }
//
// Anyone who steps onto a `from` end comes out beside the `to` end. Walks route through
// portals on their own (GM beats, schedules, followers), so the GM just uses MOVE_TO.
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

  function edgesOf(world) {
    const edges = [];
    (world.arpgMods?.portals ?? []).forEach((p, i) => {
      if (!p || p.enabled === false) return;
      const name = p.name || `Portal ${i + 1}`;
      const a = resolveEnd(world, p.from, `${i}:from`);
      const b = resolveEnd(world, p.to, `${i}:to`);
      if (!a || !b) return warnOnce(`"${name}": ${!a ? 'from' : 'to'} end not found on this map`);
      for (const [end, spec] of [[a, p.from], [b, p.twoWay ? p.to : null]]) {
        if (spec?.object && end.target.entity.objectTemplate && !(end.target.entity.objectTemplate.walkability > 0)) {
          warnOnce(`"${name}": "${spec.object}" blocks movement, so nobody can step on it; give its template a walkability above 0`);
        }
      }
      edges.push({ id: `${i}>`, portal: i, name, from: a, to: b });
      if (p.twoWay) edges.push({ id: `${i}<`, portal: i, name, from: b, to: a });
    });
    return edges;
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
    const { edges, legs } = state(world);
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
    if (err) warnOnce(`"${edge.name}": ${err}`);
    const landed = cellOf(entity.pos);
    lastZone.set(entity, edges.find(e => e.from.set.has(key(landed)))?.from.id ?? null);
  }

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
      if (wanted || (here.length && zone !== lastZone.get(e))) travel(world, e, wanted ?? here[0], edges);
      else lastZone.set(e, zone);
    }
  });

  arpg.onPrompt((parts, world) => {
    const { edges } = state(world);
    if (!edges.length) return;
    if (arpg.promptBudgets && !('passages' in arpg.promptBudgets)) arpg.promptBudgets.passages = 1e6;
    const lines = [];
    for (const e of edges) {
      if (e.id.endsWith('<')) continue;
      const twoWay = edges.some(x => x.id === `${e.portal}<`);
      lines.push(`- ${e.name}: ${e.from.label} ${twoWay ? '<->' : '->'} ${e.to.label}`);
    }
    parts.sections.push({
      kind: 'passages',
      title: 'Passages (stepping onto one end brings a character out at the other; MOVE_TO a place beyond one and they walk through it on their own):',
      content: lines.slice(0, MAX_PROMPT_LINES).join('\n'),
    });
  });

  arpg.portals = { edgesOf, route, state };
})();
