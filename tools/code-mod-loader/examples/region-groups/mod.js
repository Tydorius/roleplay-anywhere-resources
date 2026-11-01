// region-groups: shapes other than rectangles, made of same-name rectangles.
//
// The game's regions are rectangles only. Give several rectangles the same name and let them
// touch or overlap (a forest wrapped round a village as four strips, an L-shaped house as two
// walled rectangles, a U-shaped hall round a courtyard), and this mod makes them act as one:
//
// - MOVE_TO, schedules and teleports to that name go to the piece nearest the mover (the game
//   always used the first piece with the name).
// - Reaching any piece counts as arriving there.
// - Walled pieces are one room for the GM's "in the same space" detail, and for the
//   wall-aware perception mod.
// - The GM's region list shows the name once.
//
// Pieces only join when they touch or overlap, directly or through other pieces, so separate
// rooms that merely share a name ("Bedroom" in two houses) stay separate. No settings.
//
// Walls between two walled pieces: list the shared edge's cells as openings on both pieces,
// or the game draws a wall down the middle of the room.
(() => {
  const arpg = globalThis.__arpg;
  arpg.registerMod('region-groups');

  const sameName = (a, b) => String(a ?? '').trim().toLowerCase() === String(b ?? '').trim().toLowerCase();

  // Rectangles that overlap or share an edge or a corner.
  function touching(a, b) {
    const [ax, ay] = a.position, [aw, ah] = a.size, [bx, by] = b.position, [bw, bh] = b.size;
    return ax <= bx + bw && bx <= ax + aw && ay <= by + bh && by <= ay + ah;
  }

  // region → its group (an array of pieces, shared by them all); only multi-piece groups.
  const cache = new WeakMap();
  function groupsOf(world) {
    const regions = world.regions ?? [];
    const rev = `${world.regionsRev ?? 0}:${regions.length}`;
    const hit = cache.get(world);
    if (hit && hit.rev === rev) return hit.groupOf;
    const groupOf = new Map();
    const byName = new Map();
    for (const r of regions) {
      const k = String(r.name ?? '').trim().toLowerCase();
      if (!k) continue;
      if (!byName.has(k)) byName.set(k, []);
      byName.get(k).push(r);
    }
    for (const pieces of byName.values()) {
      if (pieces.length < 2) continue;
      // Connected components of touching pieces.
      const seen = new Set();
      for (const start of pieces) {
        if (seen.has(start)) continue;
        const group = [start];
        seen.add(start);
        for (let i = 0; i < group.length; i++) {
          for (const p of pieces) {
            if (!seen.has(p) && touching(group[i], p)) {
              seen.add(p);
              group.push(p);
            }
          }
        }
        if (group.length > 1) for (const p of group) groupOf.set(p, group);
      }
    }
    cache.set(world, { rev, groupOf });
    return groupOf;
  }

  // Whether two regions are pieces of one group region.
  arpg.sameRegion = (world, a, b) => {
    if (!a || !b) return false;
    if (a === b) return true;
    if (!sameName(a.name, b.name)) return false;
    const g = groupsOf(world).get(a);
    return !!g && g.includes(b);
  };

  // The piece of `region`'s group nearest the mover (or the region itself).
  arpg.pieceFor = (world, region, mover) => {
    const g = region && groupsOf(world).get(region);
    if (!g || !mover?.pos) return region;
    const [mx, my] = mover.pos;
    let best = region, bestD = Infinity;
    for (const p of g) {
      const [x, y] = p.position, [w, h] = p.size;
      const dx = Math.max(x - mx, 0, mx - (x + w - 1));
      const dy = Math.max(y - my, 0, my - (y + h - 1));
      const d = dx * dx + dy * dy;
      if (d < bestD) {
        bestD = d;
        best = p;
      }
    }
    return best;
  };

  // The GM's region list ("regions" section) has one line per rectangle, indented by nesting:
  //   "  - Name (hostile) (12m NE): Alys, Hal"
  // Keep the first line of each group; move the people listed on the others onto it.
  const LINE = /^(\s*)- (.+?)( \(hostile\))?(?: \(([^)]*)\): (.*))?$/;
  function mergeRegionLines(content, world) {
    const groupNames = new Set();
    for (const g of groupsOf(world).values()) groupNames.add(String(g[0].name).trim().toLowerCase());
    if (!groupNames.size) return content;
    const lines = content.split('\n');
    const first = new Map(); // name → index of its kept line
    const extra = new Map(); // index → extra "who's there" text
    const out = [];
    lines.forEach(line => {
      const m = LINE.exec(line);
      const key = m && m[2].trim().toLowerCase();
      if (!m || !groupNames.has(key)) return out.push(line);
      if (!first.has(key)) {
        first.set(key, out.length);
        return out.push(line);
      }
      if (m[5]) {
        const i = first.get(key);
        extra.set(i, [...(extra.get(i) ?? []), { dist: m[4], who: m[5] }]);
      }
    });
    for (const [i, more] of extra) {
      const m = LINE.exec(out[i]);
      // Lines with nobody listed carry no distance either; take both from the first piece that has people.
      out[i] = m[5] ? `${out[i]}, ${more.map(x => x.who).join(', ')}` :
        `${m[1]}- ${m[2]}${m[3] ?? ''} (${more[0].dist}): ${more.map(x => x.who).join(', ')}`;
    }
    return out.join('\n');
  }

  arpg.onPrompt((parts, world) => {
    if (!groupsOf(world).size) return;
    for (const s of [...parts.head, ...parts.sections, ...parts.tail]) {
      if (s.kind === 'regions' && typeof s.content === 'string') s.content = mergeRegionLines(s.content, world);
    }
  });

  arpg.regionGroups = { groupsOf, mergeRegionLines, touching };
})();
