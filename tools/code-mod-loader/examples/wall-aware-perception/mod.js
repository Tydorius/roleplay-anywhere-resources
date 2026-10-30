// wall-aware-perception: the player and others notice each other through walls no more.
//
// The game decides "within notice range" by straight-line distance alone (14 cells, 16 to
// drop out). That drives the "X is now in player vicinity" events (urgent ones for hostiles,
// which wake the GM), which NPC actions and speech reach the GM, and the prompt's lists of
// nearby busy characters and objects. So a skeleton five cells away behind a long wall
// still "noticed" the player.
//
// With this mod, two things within that range notice each other only if they're in the same
// walled room (or both outdoors), or one could walk to the other within the range, counting
// walls and doorways but not furniture. The same walking test as the game's own hostile
// lock-on. Only checks involving the player are changed.
(() => {
  const arpg = globalThis.__arpg;
  arpg.registerMod('wall-aware-perception');

  const CACHE_MAX = 20000; // answers kept per world before starting over

  const cellOf = pos => [Math.round(pos[0]), Math.round(pos[1])];
  const centerCell = e => cellOf([e.pos[0] + ((e.size?.[0] ?? 1) - 1) / 2, e.pos[1] + ((e.size?.[1] ?? 1) - 1) / 2]);

  // Innermost walled region containing a cell; null outdoors. Unwalled areas don't block sight.
  function walledRoom(world, c) {
    let best = null;
    for (const r of world.regions ?? []) {
      if (!r.wall) continue;
      const [x, y] = r.position, [w, h] = r.size;
      if (c[0] < x || c[1] < y || c[0] >= x + w || c[1] >= y + h) continue;
      if (!best || w * h < best.size[0] * best.size[1]) best = r;
    }
    return best;
  }

  // The walls-only answer for two cells only changes when the map's regions do, which the
  // game counts in world.regionsRev. So answers are kept until then.
  const cache = new WeakMap(); // world → {rev, answers: Map}

  function reachable(world, from, to, mover, range, search) {
    if (!search) return true; // no path search to ask; keep the game's answer
    const rev = world.regionsRev ?? 0;
    let c = cache.get(world);
    if (!c || c.rev !== rev || c.answers.size > CACHE_MAX) cache.set(world, (c = { rev, answers: new Map() }));
    const k = `${from}>${to}>${range}`;
    if (!c.answers.has(k)) {
      const path = search(world, from, to, mover, { maxCost: range + 1, wallsOnly: true });
      c.answers.set(k, path !== null);
    }
    return c.answers.get(k);
  }

  arpg.onPerceive((world, a, b, range, search, answer) => {
    if (!answer) return; // only ever takes a "yes" away
    const player = world.player ?? world.entities?.find(e => e.type === 'player');
    if (!player || (a !== player && b !== player) || a === b) return true;
    const other = a === player ? b : a;
    if (!other?.pos) return true;
    const pc = centerCell(player), oc = centerCell(other);
    if (walledRoom(world, pc) === walledRoom(world, oc)) return true;
    return reachable(world, oc, pc, other.type === 'object' ? undefined : other, range, search);
  });

  arpg.perception = { walledRoom };
})();
