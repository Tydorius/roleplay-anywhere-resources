// wall-aware-perception: the player and others notice each other through walls no more.
//
// The game decides "within notice range" by straight-line distance alone (14 cells). That
// drives the "X is now in player vicinity" events (urgent ones for hostiles, which wake the
// GM), which NPC actions and speech reach the GM, and the prompt's lists of nearby busy
// characters and objects. So a skeleton five cells away behind a long wall still "noticed"
// the player.
//
// With this mod, two things within that range notice each other only if 1.0's own stealth
// line-of-sight test says one can see the other: walls and shut doors block, open doorways,
// bars and gates don't. Two things in one walled room (or in pieces of one region-groups
// room) can always see each other, so no line is walked; both outdoors is no shortcut, since
// a house between them blocks. A floor or cellar is another plane: things on different
// planes never notice each other. Sneaking is not involved — this answers "can the player
// perceive X", and the game's stealth already decides who has noticed whom.
(() => {
  const arpg = globalThis.__arpg;
  arpg.registerMod('wall-aware-perception');

  const CACHE_MAX = 20000; // answers kept per world before starting over

  // An entity's centre, the continuous point the game's own sight tests walk from and to,
  // and the cell it falls in.
  const centre = e => [e.pos[0] + (e.size?.[0] ?? 1) / 2, e.pos[1] + (e.size?.[1] ?? 1) / 2];
  const cellOf = p => [Math.floor(p[0]), Math.floor(p[1])];

  // Innermost walled region containing a cell (the game's own room test); null outdoors.
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

  // Doors open and shut and people move, so an answer lasts one simulation step; within a
  // step (and across the game's prompt rebuilds) the same question is answered once.
  const cache = new WeakMap(); // world → {stamp, blockers, answers: Map}

  function clearLine(world, from, to) {
    const stamp = `${world.regionsRev ?? 0}|${world.activeRealSecs ?? 0}|${world.gameTimeSecs ?? 0}`;
    let c = cache.get(world);
    if (!c || c.stamp !== stamp || c.answers.size > CACHE_MAX) {
      c = { stamp, blockers: arpg.sightBlockers(world), answers: new Map() };
      cache.set(world, c);
    }
    const k = `${from}>${to}`;
    if (!c.answers.has(k)) c.answers.set(k, arpg.lineOfSight(world, from, to, c.blockers));
    return c.answers.get(k);
  }

  arpg.onPerceive((world, a, b, range, search, answer) => {
    if (!answer) return; // only ever takes a "yes" away
    if (!a?.pos || !b?.pos || a === b) return;
    const ca = centre(a), cb = centre(b);
    if (arpg.planeOf(world, ca) !== arpg.planeOf(world, cb)) return false; // a floor or cellar away
    const ra = walledRoom(world, cellOf(ca)), rb = walledRoom(world, cellOf(cb));
    if (ra && (ra === rb || arpg.sameRegion?.(world, ra, rb))) return true; // one walled room, no line to walk
    // As in stealth, the line runs from the other one to the player.
    const clear = b === world.player ? clearLine(world, ca, cb)
      : a === world.player ? clearLine(world, cb, ca)
      : clearLine(world, ca, cb);
    return typeof clear === 'boolean' ? clear : undefined; // no sight test to be had: keep the game's answer
  });

  arpg.perception = { walledRoom, centre };
})();
