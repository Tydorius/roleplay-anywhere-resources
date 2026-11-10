// region-groups: shapes other than rectangles, made of same-name rectangles (Anywhere RPG 1.0).
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
// rooms that merely share a name ("Bedroom" in two houses) stay separate. A group never spans
// two planes: 1.0's floors and cellars are pocket regions off the main map, so same-name
// pieces on different floors never join, and a mover on another floor goes to the region the
// game picked (1.0 walks it there through its stairs), not to a "nearest" piece measured
// across planes. A natural-shaped piece ("organic") joins by its rectangle like any piece —
// blobs are inset from their rectangles, so joining by blob would split a forest wrapped round
// a village — while arriving still follows the blob, the game's own contains test answering
// with it. No settings.
//
// Walls between two walled pieces: list the shared edge's cells as openings on both pieces,
// each with its side ("n", "s", "e" or "w"), or the game draws a wall down the middle of the
// room.
(() => {
  const arpg = globalThis.__arpg;
  arpg.registerMod('region-groups');

  const sameName = (a, b) => String(a ?? '').trim().toLowerCase() === String(b ?? '').trim().toLowerCase();

  // Rectangles that overlap or share an edge or a corner.
  function touching(a, b) {
    const [ax, ay] = a.position, [aw, ah] = a.size, [bx, by] = b.position, [bw, bh] = b.size;
    return ax <= bx + bw && bx <= ax + aw && ay <= by + bh && by <= ay + ah;
  }

  // The plane a region lives on: the pocket region itself when it is a floor or cellar, the
  // pocket holding its centre when it's a piece on one, null on the main map.
  function planeOfRegion(world, r) {
    if (!r) return null;
    if (r.pocket) return r;
    return arpg.planeOf(world, [r.position[0] + r.size[0] / 2, r.position[1] + r.size[1] / 2]);
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
      // Each piece's plane, once per rebuild; connected components of touching pieces on one plane.
      const plane = new Map(pieces.map(p => [p, planeOfRegion(world, p)]));
      const seen = new Set();
      for (const start of pieces) {
        if (seen.has(start)) continue;
        const group = [start];
        seen.add(start);
        for (let i = 0; i < group.length; i++) {
          for (const p of pieces) {
            if (!seen.has(p) && plane.get(p) === plane.get(group[i]) && touching(group[i], p)) {
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
    // A mover on another plane goes to the region the game picked: 1.0 walks it there through
    // its stairs, and "nearest" measured across planes would be wrong.
    const c = [mover.pos[0] + (mover.size?.[0] ?? 1) / 2, mover.pos[1] + (mover.size?.[1] ?? 1) / 2];
    if (arpg.planeOf(world, c) !== planeOfRegion(world, region)) return region;
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

  // The innermost walled room at a cell: the walled region with the smallest area whose
  // rectangle contains it. Walled regions are never natural-shaped in 1.0, so the rectangle
  // test is exact.
  function walledRoomAt(world, cell) {
    let room = null;
    for (const r of world.regions ?? []) {
      const [x, y] = r.position, [w, h] = r.size;
      if (r.wall && cell[0] >= x && cell[1] >= y && cell[0] < x + w && cell[1] < y + h &&
          (!room || w * h < room.size[0] * room.size[1])) room = r;
    }
    return room;
  }

  // Take the door objects off the joints between pieces of one group: a door sits on one cell
  // edge, so the two rooms it separates are the innermost walled rooms at the two cells
  // either side of it. Everything else — a door to a room nested inside a piece, between
  // pieces of different groups, or on a piece's outer wall — stays. Returns how many went.
  function removeJointDoors(world) {
    const entities = world.entities ?? [];
    let removed = 0;
    for (let i = entities.length - 1; i >= 0; i--) {
      const e = entities[i];
      if (e.type !== 'object' || !e.objectTemplate?.door || e.dead) continue;
      const [x, y] = e.pos;
      const cells = e.size[0] === 0 ? [[x - 1, y], [x, y]] : [[x, y - 1], [x, y]];
      const ra = walledRoomAt(world, cells[0]), rb = walledRoomAt(world, cells[1]);
      if (ra && rb && ra !== rb && arpg.sameRegion(world, ra, rb)) {
        entities.splice(i, 1);
        removed++;
      }
    }
    return removed;
  }

  // 1.0 hangs a door object on every doorway of every walled region when it builds a world,
  // including the openings an author lists along the joint between two pieces of one group —
  // the pieces are one room, and a row of shut doors across their middle blocks 1.0's own
  // stealth line of sight. This takes those doors off. It runs from onWorldCreate, at the very
  // end of 1.0's scenario → world builder, after the game has hung its doors — for played
  // worlds and for the editor's throwaway preview worlds alike (the preview should show the
  // room as one). Known limits: if the GM later changes a piece's walls (`wall_change`), 1.0
  // re-hangs doors on that piece's doorways and this does not run again; and saves made before
  // this mod was installed keep their joint doors (remove them in god mode, or start a new
  // game).
  arpg.onWorldCreate(world => {
    const n = removeJointDoors(world);
    if (n) console.info(`[region-groups] took ${n} doors off the joints between region pieces`);
  });

  arpg.regionGroups = { groupsOf, mergeRegionLines, touching, planeOfRegion, removeJointDoors };
})();
