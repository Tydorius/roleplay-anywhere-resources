"use strict";
// The furnish engine: places furniture in one region the way the world generator lays out a
// room. The caller says what to place and roughly where (the hint vocabulary parsed here); the
// engine decides the exact cells and returns them. The scenario itself is never touched.
//
// Ported from the generator's worldgen/layout_room.py and worldgen/hints.py, with this editor's
// deliberate differences: no randomness (the relative "side" wall and the corner order follow
// fixed rules, named at their sites), no turning (a piece's footprint is its template's size as
// it is), the game's thin-wall room (walls are lines on the region's border, every cell of a
// walled region stands, the usable rectangle is the region's full rect and a doorway cell is the
// opening itself), around:/beside: references resolve by template id first, then by name, and
// solid furniture may not strand floor the doors reached before it was placed (see
// sealedCells) — the generator only moves pieces that end up boxed in behind such a wall.
//
// splitRooms, in the buildings section below, ports the generator's building layout
// (worldgen/layout_building.py): one footprint rectangle split into rooms along a connection
// tree. Like furnish, it never touches the scenario.

(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./mapops.js"));
  else root.Design = factory(root.MapOps);
})(typeof self !== "undefined" ? self : this, function (MapOps) {

  const SIDES = ["n", "e", "s", "w"];      // the game's side letters (openings carry them too)
  const REL = ["far", "side", "near"];     // walls relative to the room's main door
  const OPPOSITE = {n: "s", s: "n", e: "w", w: "e"};
  const PERPENDICULAR = {n: ["e", "w"], s: ["e", "w"], e: ["n", "s"], w: ["n", "s"]};
  // The generator rolls a die to order the two perpendicular walls of a relative "side" hint;
  // there is no rng here, so they go in this fixed order instead (see resolveSide).
  const SIDE_ORDER = ["w", "s", "e", "n"];

  const key = (x, y) => x + "," + y;
  const dist = (a, b) => Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]);

  function addCells(set, pos, size) {
    for (let x = pos[0]; x < pos[0] + size[0]; x++)
      for (let y = pos[1]; y < pos[1] + size[1]; y++) set.add(key(x, y));
  }

  /** The one-wide ring of cells around a footprint: where a person could stand beside it. */
  function ring(pos, size) {
    const out = new Set();
    for (let x = pos[0] - 1; x <= pos[0] + size[0]; x++)
      for (let y = pos[1] - 1; y <= pos[1] + size[1]; y++)
        if (x < pos[0] || x >= pos[0] + size[0] || y < pos[1] || y >= pos[1] + size[1]) out.add(key(x, y));
    return out;
  }

  // ---------------------------------------------------------------- hints

  /** Parse a hint string; never throws. Tokens join with "+"; unknown tokens land in .unknown
   *  and carry no constraint (anywhere free). The vocabulary: wall:<side> and row:<side> (a side
   *  is n, e, s, w, or far/side/near measured against the room's main door), corner, center,
   *  near_door, away_from_door, beside:<ref>, around:<ref>, symmetric. */
  function parseHint(text) {
    const h = {raw: typeof text === "string" ? text : "", walls: [], row: null, corner: false,
      center: false, beside: null, around: null, nearDoor: false, awayFromDoor: false,
      symmetric: false, unknown: []};
    for (let token of h.raw.split("+")) {
      token = token.trim();
      if (!token) continue;
      const c = token.indexOf(":");
      const k = (c < 0 ? token : token.slice(0, c)).trim();
      const v = (c < 0 ? "" : token.slice(c + 1)).trim();
      if (k === "wall") {
        if (SIDES.indexOf(v) !== -1 || REL.indexOf(v) !== -1) h.walls.push(v);
        else if (v !== "any") h.unknown.push(token);         // wall:any means unconstrained
      } else if (k === "row" && (SIDES.indexOf(v) !== -1 || REL.indexOf(v) !== -1)) h.row = v;
      else if (k === "beside" && v) h.beside = v;
      else if (k === "around" && v) h.around = v;
      else if (token === "corner") h.corner = true;
      else if (token === "center") h.center = true;
      else if (token === "near_door") h.nearDoor = true;
      else if (token === "away_from_door") h.awayFromDoor = true;
      else if (token === "symmetric") h.symmetric = true;
      else h.unknown.push(token);
    }
    return h;
  }

  /** False when the hint carries no usable constraint (anywhere free). */
  function constrained(h) {
    return !!(h.walls.length || h.row || h.corner || h.center || h.beside || h.around ||
      h.nearDoor || h.awayFromDoor || h.symmetric);
  }

  // ---------------------------------------------------------------- the room

  /** The wall of `rect` a cell sits on ("n" and so on), or null when it is not on the border. */
  function doorSide(rect, cell) {
    if (cell[1] === rect[1]) return "s";
    if (cell[1] === rect[3]) return "n";
    if (cell[0] === rect[0]) return "w";
    if (cell[0] === rect[2]) return "e";
    return null;
  }

  /** Port of the generator's reserve_walkways under the game's wall model: every doorway cell
   *  (an opening is already one step from outside) plus a spine connecting them — a centre row
   *  in wide rooms, a centre column in tall ones, with a branch from each door to the spine.
   *  Keeps the walls free for furniture while no placement can cut one door off from another;
   *  a single door reserves only its own cell. */
  function reserveWalkways(rect, doors) {
    const inner = doors.slice();
    const reserved = new Set(inner.map(p => key(p[0], p[1])));
    if (inner.length >= 2) {
      const w = rect[2] - rect[0] + 1, h = rect[3] - rect[1] + 1;
      const xs = inner.map(p => p[0]), ys = inner.map(p => p[1]);
      if (w >= h) {
        const sy = rect[1] + Math.floor((h - 1) / 2);
        for (let x = Math.min(...xs); x <= Math.max(...xs); x++) reserved.add(key(x, sy));
        for (const [x, y] of inner)
          for (let yy = Math.min(y, sy); yy <= Math.max(y, sy); yy++) reserved.add(key(x, yy));
      } else {
        const sx = rect[0] + Math.floor((w - 1) / 2);
        for (let y = Math.min(...ys); y <= Math.max(...ys); y++) reserved.add(key(sx, y));
        for (const [x, y] of inner)
          for (let xx = Math.min(x, sx); xx <= Math.max(x, sx); xx++) reserved.add(key(xx, y));
      }
    }
    return {reserved, inner};
  }

  // ---------------------------------------------------------------- furnish

  /** Place furniture in one region. items: [{templateId, count (1-12, at most 12 items), hint?}].
   *  Returns {placements: [{templateId, pos: [x, y]}] in placement order, failures:
   *  [{templateId, placed, wanted, reason}], fallbacks: [{templateId, reason}]}. Bad items are
   *  failures; nothing is thrown and nothing in `scn` is changed. */
  function furnish(scn, region, items) {
    const templates = scn && Array.isArray(scn.objectTemplates) ? scn.objectTemplates : [];
    const byId = new Map(templates.map(t => [t && t.id, t]));
    const regions = scn && Array.isArray(scn.regions) ? scn.regions : [];
    const entities = scn && Array.isArray(scn.entities) ? scn.entities : [];
    const failures = [];

    const valid = [];
    (Array.isArray(items) ? items : []).forEach((it, i) => {
      const bad = reason => failures.push({
        templateId: it && typeof it === "object" ? it.templateId : undefined,
        placed: 0, wanted: 0, reason});
      if (i >= 12) return bad("too many items (at most 12)");
      if (!it || typeof it !== "object") return bad("missing templateId");
      if (typeof it.templateId !== "string" || !it.templateId) return bad("missing templateId");
      if (!Number.isInteger(it.count) || it.count < 1 || it.count > 12)
        return bad("count must be between 1 and 12");
      if (it.hint !== undefined && typeof it.hint !== "string") return bad("hint must be a string");
      const tmpl = byId.get(it.templateId);
      if (!tmpl) return failures.push(
        {templateId: it.templateId, placed: 0, wanted: it.count, reason: "unknown template"});
      valid.push({templateId: it.templateId, count: it.count, hint: it.hint || "", tmpl,
        size: Array.isArray(tmpl.size) ? tmpl.size : [1, 1]});
    });

    // ---- the room under the game's wall model
    const rect = region && (Array.isArray(region.position) || Array.isArray(region.pos))
      ? MapOps.rect(region) : null;
    if (!rect) {                               // no room to place in
      for (const f of valid)
        failures.push({templateId: f.templateId, placed: 0, wanted: f.count,
          reason: "room interior too small"});
      return {placements: [], failures, fallbacks: []};
    }
    // floor cells: the region's rect minus every cell of the regions nested inside it (those
    // belong to the inner room, not this floor)
    const nested = MapOps.contents({regions, entities}, region).regions.map(MapOps.rect);
    const floor = new Set();
    for (let x = rect[0]; x <= rect[2]; x++)
      for (let y = rect[1]; y <= rect[3]; y++)
        if (!nested.some(r => MapOps.inRect(r, x, y))) floor.add(key(x, y));

    // existing entities block placement: an object covers its size, a person one cell
    const blocked = new Set();
    for (const e of entities) {
      if (!e || !Array.isArray(e.pos)) continue;
      const s = e.type === "object" && Array.isArray(e.size) ? e.size : [1, 1];
      for (let x = e.pos[0]; x < e.pos[0] + s[0]; x++)
        for (let y = e.pos[1]; y < e.pos[1] + s[1]; y++)
          if (MapOps.inRect(rect, x, y)) blocked.add(key(x, y));
    }

    // every doorway on this floor, plus the spine connecting them: an opening that is a floor
    // cell is its own doorway cell; an opening of a room nested in this floor belongs to that
    // room, so the cell people step onto here is the one just outside it
    const doors = [];
    const addDoor = c => { if (!doors.some(d => d[0] === c[0] && d[1] === c[1])) doors.push(c); };
    for (const r of regions) {
      if (!Array.isArray(r.openings)) continue;
      for (const o of r.openings) {
        if (!Array.isArray(o) || !MapOps.inRect(rect, o[0], o[1])) continue;
        if (floor.has(key(o[0], o[1]))) { addDoor([o[0], o[1]]); continue; }
        if (!Array.isArray(r.position) || !Array.isArray(r.size)) continue;
        const q = MapOps.rect(r);
        let outs = [];
        if (o[1] === q[3]) outs.push(["n", [o[0], o[1] + 1]]);
        if (o[0] === q[2]) outs.push(["e", [o[0] + 1, o[1]]]);
        if (o[1] === q[1]) outs.push(["s", [o[0], o[1] - 1]]);
        if (o[0] === q[0]) outs.push(["w", [o[0] - 1, o[1]]]);
        if (o.length > 2 && outs.some(s => s[0] === o[2])) outs = outs.filter(s => s[0] === o[2]);
        for (const [, c] of outs) if (floor.has(key(c[0], c[1]))) addDoor(c);
      }
    }
    const reserved = reserveWalkways(rect, doors).reserved;
    // far/near/side are measured from the region's first opening; a region with no opening
    // treats the relative sides as any of the four walls
    const mainDoor = Array.isArray(region.openings) && Array.isArray(region.openings[0])
      ? [region.openings[0][0], region.openings[0][1]] : null;
    const nearSide = mainDoor ? doorSide(rect, mainDoor) : null;
    const center = [rect[0] + (rect[2] - rect[0]) / 2, rect[1] + (rect[3] - rect[1]) / 2];

    const allPositions = size => {
      const out = [];
      for (let x = rect[0]; x <= rect[2] - size[0] + 1; x++)
        for (let y = rect[1]; y <= rect[3] - size[1] + 1; y++) out.push([x, y]);
      return out;
    };
    const byLex = (a, b) => a[0] - b[0] || a[1] - b[1];
    const byCenter = (a, b) => dist(a, center) - dist(b, center);
    const doorDist = p => doors.reduce((m, d) => Math.min(m, dist(p, d)), Infinity);

    function resolveSide(side) {
      if (SIDES.indexOf(side) !== -1) return [side];
      if (nearSide === null) return ["n", "e", "s", "w"];
      if (side === "far") return [OPPOSITE[nearSide]];
      if (side === "near") return [nearSide];
      // The generator rolls which perpendicular wall comes first; the fixed rule here: the
      // first of the two in SIDE_ORDER (w, s, e, n) is tried first, the other is the fallback.
      const [a, b] = PERPENDICULAR[nearSide];
      return SIDE_ORDER.indexOf(a) < SIDE_ORDER.indexOf(b) ? [a, b] : [b, a];
    }

    const mirror = (pos, size) => [rect[2] - (pos[0] - rect[0]) - (size[0] - 1),
                                   rect[3] - (pos[1] - rect[1]) - (size[1] - 1)];

    function wallFilter(side, size) {
      const out = [];
      for (const [x, y] of allPositions(size)) {
        if (side === "n" && y + size[1] - 1 === rect[3]) out.push([x, y]);
        else if (side === "s" && y === rect[1]) out.push([x, y]);
        else if (side === "w" && x === rect[0]) out.push([x, y]);
        else if (side === "e" && x + size[0] - 1 === rect[2]) out.push([x, y]);
      }
      return out;
    }

    function corners(size) {
      const pts = [[rect[0], rect[1]], [rect[2] - size[0] + 1, rect[1]],
        [rect[0], rect[3] - size[1] + 1], [rect[2] - size[0] + 1, rect[3] - size[1] + 1]];
      if (!mainDoor) return pts;
      // The generator rolls a corner order; the fixed rule here: farthest from the main door
      // first (and the room's natural order when there is no door).
      return pts.slice().sort((a, b) => dist(b, mainDoor) - dist(a, mainDoor));
    }

    function ringAround(fp, size) {
      const out = [];
      for (let ax = fp[0] - 1; ax <= fp[0] + fp[2]; ax++)
        for (let ay = fp[1] - 1; ay <= fp[1] + fp[3]; ay++) {
          if (ax >= fp[0] && ax < fp[0] + fp[2] && ay >= fp[1] && ay < fp[1] + fp[3]) continue;
          if (ax >= rect[0] && ay >= rect[1] && ax + size[0] - 1 <= rect[2] && ay + size[1] - 1 <= rect[3])
            out.push([ax, ay]);
        }
      return out;
    }

    function nearFootprint(fp, size) {
      const out = [];
      for (const [x, y] of allPositions(size)) {
        const dx = Math.max(fp[0] - (x + size[0] - 1), x - (fp[0] + fp[2] - 1), 0);
        const dy = Math.max(fp[1] - (y + size[1] - 1), y - (fp[1] + fp[3] - 1), 0);
        if (Math.max(dx, dy) <= 1) out.push([x, y]);
      }
      return out;
    }

    /** A hint reference resolves to a template by id first, then by exact name. */
    const resolveRef = ref => byId.get(ref) || templates.find(t => t && t.name === ref) || null;
    const placedOf = (ref, placed) => {
      const t = resolveRef(ref);
      return t ? placed.filter(p => p.templateId === t.id) : [];
    };

    /** Candidate positions for a hint, best first; an empty list with a reason means the hint's
     *  target was missing. */
    function orderedCandidates(hint, size, placed) {
      if (hint.around !== null) {
        const targets = placedOf(hint.around, placed);
        if (!targets.length) return {pos: [], reason: "around:" + hint.around + " not placed yet"};
        const out = [], seen = new Set();
        for (const t of targets)
          for (const p of ringAround([t.pos[0], t.pos[1], t.size[0], t.size[1]], size)) {
            const k = key(p[0], p[1]);
            if (!seen.has(k)) { seen.add(k); out.push(p); }
          }
        return {pos: out, reason: null};
      }
      if (hint.beside !== null) {
        const targets = placedOf(hint.beside, placed);
        if (!targets.length) return {pos: [], reason: "beside:" + hint.beside + " not placed yet"};
        const out = [], seen = new Set();
        for (const t of targets)
          for (const p of nearFootprint([t.pos[0], t.pos[1], t.size[0], t.size[1]], size)) {
            const k = key(p[0], p[1]);
            if (!seen.has(k)) { seen.add(k); out.push(p); }
          }
        out.sort((a, b) => dist(a, targets[0].pos) - dist(b, targets[0].pos));
        return {pos: out, reason: null};
      }
      let pos = allPositions(size);
      let isConstrained = false;
      for (const side of hint.walls) {
        const wpos = wallFilter(side, size);
        if (wpos.length) { pos = wpos; isConstrained = true; break; }
      }
      if (hint.row) {
        const rpos = wallFilter(hint.row, size);
        if (rpos.length) { pos = rpos.slice().sort(byLex); isConstrained = true; }
      }
      if (hint.corner) {
        const cs = corners(size);
        const inPos = cs.filter(p => pos.some(q => q[0] === p[0] && q[1] === p[1]));
        pos = inPos.length ? inPos : cs;
        isConstrained = true;
      }
      if (isConstrained) {
        if (hint.center) pos = pos.slice().sort(byCenter);
        else if (hint.nearDoor) pos = pos.slice().sort((a, b) => doorDist(a) - doorDist(b));
        else if (hint.awayFromDoor) pos = pos.slice().sort((a, b) => doorDist(b) - doorDist(a));
        return {pos, reason: null};
      }
      if (hint.center) pos = pos.slice().sort(byCenter);
      else if (hint.nearDoor) pos = pos.slice().sort((a, b) => doorDist(a) - doorDist(b));
      else if (hint.awayFromDoor) pos = pos.slice().sort((a, b) => doorDist(b) - doorDist(a));
      return {pos, reason: null};
    }

    /** Every cell of the footprint is floor, unoccupied and unreserved. */
    function legalInto(occ, pos, size) {
      if (pos[0] < rect[0] || pos[1] < rect[1] ||
          pos[0] + size[0] - 1 > rect[2] || pos[1] + size[1] - 1 > rect[3]) return false;
      for (let x = pos[0]; x < pos[0] + size[0]; x++)
        for (let y = pos[1]; y < pos[1] + size[1]; y++) {
          const k = key(x, y);
          if (!floor.has(k) || occ.has(k) || reserved.has(k)) return false;
        }
      return true;
    }

    /** One full placement pass over every valid item. */
    function placeAll(banned) {
      const placed = [];                        // {templateId, pos, size} in placement order
      const occ = new Set(blocked);
      const solidCovered = new Set(blocked);    // what the flood walks round: entities + solids
      const fails = [], falls = [];

      /** A solid piece may only land where it strands no more floor than a nook. */
      const sealsFloor = (item, pos) => {
        if (!isSolid({templateId: item.templateId})) return false;
        const trial = new Set(solidCovered);
        addCells(trial, pos, item.size);
        return stranded(trial) > SEAL_TOLERANCE;
      };

      const tryPositions = (item, hint, positions, budget) => {
        const size = item.size;
        let count = 0, sealSkips = 0, otherSkips = 0;
        for (const pos of positions) {
          if (count >= budget) break;
          if (banned.has(item.templateId + "@" + pos[0] + "," + pos[1]) ||
              !legalInto(occ, pos, size)) { otherSkips++; continue; }
          if (sealsFloor(item, pos)) { sealSkips++; continue; }   // the cell was free; keeping the
                                                                  // floor walkable ruled it out
          if (hint.symmetric && count + 2 <= budget) {
            const m = mirror(pos, size);
            // the mirror of a piece near the middle can overlap it
            if ((m[0] !== pos[0] || m[1] !== pos[1]) &&
                !banned.has(item.templateId + "@" + m[0] + "," + m[1]) &&
                legalInto(occ, m, size) && !sealsFloor(item, m) &&
                (m[0] > pos[0] + size[0] - 1 || pos[0] > m[0] + size[0] - 1 ||
                 m[1] > pos[1] + size[1] - 1 || pos[1] > m[1] + size[1] - 1)) {
              for (const p of [pos, m]) {
                addCells(occ, p, size);
                placed.push({templateId: item.templateId, pos: p, size});
                if (isSolid({templateId: item.templateId})) addCells(solidCovered, p, size);
              }
              count += 2;
              continue;
            }
          }
          addCells(occ, pos, size);
          placed.push({templateId: item.templateId, pos, size});
          if (isSolid({templateId: item.templateId})) addCells(solidCovered, pos, size);
          count += 1;
        }
        return {count, sealSkips, otherSkips};
      };

      // a piece goes after the one it stands beside or around, so chairs never look for a table
      // that is not down yet (the generator orders its library rooms this way; here every item
      // is), then by descending footprint area
      const depOf = (i, seen) => {
        const h = parseHint(valid[i].hint);
        const ref = h.around || h.beside;
        if (!ref || seen.indexOf(valid[i].templateId) !== -1) return 0;
        const t = resolveRef(ref);
        if (!t) return 0;
        let best = -1;
        valid.forEach((g, j) => {
          if (g.templateId === t.id)
            best = Math.max(best, depOf(j, seen.concat([valid[i].templateId])));
        });
        return 1 + best;
      };
      const area = i => valid[i].size[0] * valid[i].size[1];
      const depth = valid.map((f, i) => depOf(i, []));
      const order = valid.map((f, i) => i).sort((a, b) => depth[a] - depth[b] || area(b) - area(a));

      for (const i of order) {
        const f = valid[i];
        const hint = parseHint(f.hint);
        // far/side/near mean real walls: resolve them against the main door
        if (hint.walls.some(w => REL.indexOf(w) !== -1))
          hint.walls = hint.walls.flatMap(w => resolveSide(w));
        if (hint.row && REL.indexOf(hint.row) !== -1) hint.row = resolveSide(hint.row)[0];
        let {pos: cands, reason} = orderedCandidates(hint, f.size, placed);
        const anywhere = allPositions(f.size);
        if (!cands.length) {
          falls.push({templateId: f.templateId, reason: reason || "no candidate positions"});
          cands = anywhere;
        }
        const tries = hint.symmetric ? cands.slice().sort(byCenter) : cands;
        let last = tryPositions(f, hint, tries, f.count);
        let count = last.count;
        if (count < f.count && constrained(hint)) {
          falls.push({templateId: f.templateId,
            reason: "hint '" + f.hint + "' could not be fully met"});
          last = tryPositions(f, hint, anywhere, f.count - count);
          count += last.count;
        }
        if (count < f.count)
          fails.push({templateId: f.templateId, placed: count, wanted: f.count,
            // cells were free, but a solid piece on any of them would have walled floor off
            reason: last.sealSkips ? "no placement that keeps the room walkable"
                                   : "no free cell in the room"});
      }
      return {placed, failures: fails, fallbacks: falls};
    }

    const isSolid = p => {
      const t = byId.get(p.templateId);
      return !!t && t.walkability <= 0;
    };
    /** Everything solid: the existing entities plus the solid pieces among `placements`. */
    function solidCover(placements) {
      const covered = new Set(blocked);
      for (const p of placements) if (isSolid(p)) addCells(covered, p.pos, p.size);
      return covered;
    }
    /** The floor cells the doors reach, walking round `covered` cells. */
    function reach(covered) {
      const walkable = k => floor.has(k) && !covered.has(k);
      const seen = new Set(), todo = [];
      for (const d of doors) {
        const k = key(d[0], d[1]);
        if (walkable(k) && !seen.has(k)) { seen.add(k); todo.push(k); }
      }
      while (todo.length) {
        const [x, y] = todo.pop().split(",").map(Number);
        for (const k of [key(x + 1, y), key(x - 1, y), key(x, y + 1), key(x, y - 1)])
          if (walkable(k) && !seen.has(k)) { seen.add(k); todo.push(k); }
      }
      return seen;
    }

    /** Solid pieces whose surrounding ring no flooded cell touches: sealed off from every door.
     *  Existing entities are obstacles in the flood but are never banned or moved. A floor with
     *  no doorways (an open area) checks nothing: there is nothing to be sealed off from. */
    function boxedPositions(placements) {
      if (!doors.length) return [];
      const seen = reach(solidCover(placements));
      return placements.filter(p => {
        if (!isSolid(p)) return false;
        for (const k of ring(p.pos, p.size)) if (seen.has(k)) return false;
        return true;
      });
    }

    /** The generator's check stops at pieces boxed in: a solid piece that walls off part of the
     *  floor is itself reachable, so it never trips it. This editor goes one further (the fifth
     *  divergence, see the header): a solid piece may only go where the doors keep reaching the
     *  free floor they reached before furnishing, give or take a furniture nook
     *  (SEAL_TOLERANCE cells). */
    const SEAL_TOLERANCE = 2;
    const openBefore = doors.length ? reach(new Set(blocked)) : new Set();
    /** How many once-reachable free cells `covered` (existing entities + solid placements) now
     *  strands. */
    function stranded(covered) {
      if (!doors.length) return 0;
      const seen = reach(covered);
      let n = 0;
      for (const k of openBefore) if (!covered.has(k) && !seen.has(k)) n++;
      return n;
    }

    // Up to eight passes: ban and re-place whatever ends up boxed in (passes 1-7); on the last
    // pass relocate each boxed piece to the nearest free position where it neither boxes itself
    // in nor strands floor, and drop, with a failure, only what has nowhere to go. (Placement
    // itself never strands floor — see sealsFloor — so the bans only ever answer for pieces
    // boxed in behind walls that were already there.)
    const banned = new Set();
    let pass = null;
    for (let attempt = 0; attempt < 8; attempt++) {
      pass = placeAll(banned);
      const boxed = boxedPositions(pass.placed);
      if (!boxed.length) break;
      if (attempt < 7) {
        for (const p of boxed) banned.add(p.templateId + "@" + p.pos[0] + "," + p.pos[1]);
        continue;
      }
      const keep = pass.placed.filter(p => boxed.indexOf(p) === -1);
      const covered = new Set(blocked);
      for (const p of keep) addCells(covered, p.pos, p.size);
      const sorted = boxed.slice().sort((a, b) =>
        a.templateId < b.templateId ? -1 : a.templateId > b.templateId ? 1
        : a.pos[0] - b.pos[0] || a.pos[1] - b.pos[1]);
      for (const p of sorted) {
        let moved = null;
        for (const cand of allPositions(p.size).sort(byCenter)) {
          if (!legalInto(covered, cand, p.size)) continue;
          const extra = {templateId: p.templateId, pos: cand, size: p.size};
          const trial = keep.concat([extra]);
          if (!boxedPositions(trial).some(q => q.templateId === p.templateId &&
              q.pos[0] === cand[0] && q.pos[1] === cand[1]) &&
              stranded(solidCover(trial)) <= SEAL_TOLERANCE) {
            moved = cand; break;
          }
        }
        if (moved) {
          keep.push({templateId: p.templateId, pos: moved, size: p.size});
          addCells(covered, moved, p.size);
        } else {
          pass.failures.push({templateId: p.templateId, placed: 0, wanted: 1,
            reason: "no placement that keeps the room walkable"});
        }
      }
      pass.placed = keep;
    }

    return {
      placements: pass.placed.map(p => ({templateId: p.templateId, pos: [p.pos[0], p.pos[1]]})),
      failures: failures.concat(pass.failures),
      fallbacks: pass.fallbacks,
    };
  }

  // ---------------------------------------------------------------- buildings

  // Ported from the generator's worldgen/layout_building.py (_connection_tree, _room_rects,
  // _strip_split, _divide_children) with _sizes_mins and _weighted_sizes from
  // worldgen/layout_map.py and shared_wall_cells from worldgen/model.py, under this editor's
  // deliberate differences: everything is deterministic (the Python's rng goes unused along this
  // path — layout_rooms' rng never touches room splitting — and halves round up where Python's
  // round takes the even side); a room's need is its share, a weight defaulting to 1 (one share
  // is one minimum room, 3 x 3), not its furniture; walls are thin lines, so strip depths drop
  // the generator's two wall columns and touching rooms share the wall line between them, making
  // every door a facing pair of cells, one in each room. A footprint that cannot give every room
  // its minimums is refused with a workable size, never answered with a wrong layout.

  const MIN_SIDE = 3;      // every room of the split is at least this many cells on each side
  const SHARE_AREA = 9;    // one share of weight is one minimum room (3 x 3 cells)

  /** Integer sizes proportional to `weights`, summing to `total`, each at least `minSize` where
   *  the total allows it (the generator's _weighted_sizes; ties go to the first). */
  function weightedSizes(total, weights, minSize) {
    const tw = weights.reduce((a, b) => a + b, 0) || 1;
    const sizes = weights.map(w => Math.max(1, Math.round(total * w / tw)));
    const sum = () => sizes.reduce((a, b) => a + b, 0);
    while (sum() < total) sizes[sizes.indexOf(Math.min(...sizes))]++;
    while (sum() > total && Math.max(...sizes) > 1) sizes[sizes.indexOf(Math.max(...sizes))]--;
    if (total >= weights.length * minSize)
      for (let k = 0; k < weights.length * 2; k++) {
        const short = sizes.findIndex(s => s < minSize);
        if (short < 0) break;
        const tall = sizes.indexOf(Math.max(...sizes));
        if (sizes[tall] <= minSize) break;
        sizes[tall]--;           // one cell at a time, from the tallest to the shortest
        sizes[short]++;
      }
    return sizes;
  }

  /** weightedSizes, then a pass topping up the sizes below their own minimums from those with
   *  room to spare (the generator's _sizes_mins). */
  function sizesMins(total, weights, mins) {
    const n = weights.length;
    mins = mins.map(m => Math.min(m, Math.max(1, total - n + 1)));
    const sizes = weightedSizes(total, weights, mins.length ? Math.min(...mins) : 1);
    for (let k = 0; k < n * 2; k++) {
      const short = sizes.findIndex((s, i) => s < mins[i]);
      if (short < 0) break;
      let tall = 0;
      for (let i = 1; i < n; i++) if (sizes[i] - mins[i] > sizes[tall] - mins[tall]) tall = i;
      if (sizes[tall] <= mins[tall]) break;
      const move = Math.min(sizes[tall] - mins[tall], mins[short] - sizes[short]);
      sizes[tall] -= move;
      sizes[short] += move;
    }
    return sizes;
  }

  /** The strip depth at which a strip of `span` cells holds `area` cells: the generator's
   *  _depth_for drops two columns for its wall cells, but walls are lines here. */
  const depthFor = (area, span) => Math.ceil(area / Math.max(1, span));

  /** Cut a strip of `size` cells off the inclusive rect along side ("n", "e", "s" or "w"):
   *  [strip, rest]. */
  function stripSplit(rect, side, size) {
    size = Math.max(1, size);
    if (side === "s") return [[rect[0], rect[1], rect[2], rect[1] + size - 1],
                              [rect[0], rect[1] + size, rect[2], rect[3]]];
    if (side === "n") return [[rect[0], rect[3] - size + 1, rect[2], rect[3]],
                              [rect[0], rect[1], rect[2], rect[3] - size]];
    if (side === "w") return [[rect[0], rect[1], rect[0] + size - 1, rect[3]],
                              [rect[0] + size, rect[1], rect[2], rect[3]]];
    return [[rect[2] - size + 1, rect[1], rect[2], rect[3]],
            [rect[0], rect[1], rect[2] - size, rect[3]]];
  }

  /** Rooms as a parent -> children tree from the connection list, rooted at the entrance room
   *  (the generator's _connection_tree, already deterministic: connection order, then room
   *  order). Rooms with no connections hang off the root so every room stays reachable. */
  function connectionTree(names, connections, entranceRoom) {
    const root = names.includes(entranceRoom) ? entranceRoom : names[0];
    const adj = new Map(names.map(n => [n, new Set()]));
    for (const [a, b] of connections)
      if (adj.has(a) && adj.has(b) && a !== b) { adj.get(a).add(b); adj.get(b).add(a); }
    const children = new Map(names.map(n => [n, []]));
    const seen = new Set([root]), frontier = [root];
    while (frontier.length) {
      const node = frontier.shift();
      const next = names.filter(n => adj.get(node).has(n) && !seen.has(n));
      for (const n of next) { seen.add(n); children.get(node).push(n); }
      frontier.push(...next);
    }
    for (const n of names)                 // orphans hang off the root
      if (!seen.has(n)) children.get(root).push(n);
    return {children, root};
  }

  /** The facing door cells between two touching rooms: one cell in each room's outer row or
   *  column, at the midpoint of the shared stretch and inset one cell from the corners (the
   *  generator's shared_wall_cells — under thin walls, rooms one cell apart share the wall line
   *  between them, so every door is such a pair). [] when they do not touch. */
  function sharedWallCells(a, b) {
    if (a[3] + 1 === b[1]) {                       // a sits below b
      const lo = Math.max(a[0], b[0]) + 1, hi = Math.min(a[2], b[2]) - 1;
      if (hi >= lo) { const x = Math.floor((lo + hi) / 2); return [[x, a[3]], [x, b[1]]]; }
    } else if (b[3] + 1 === a[1]) {                // b sits below a
      const lo = Math.max(a[0], b[0]) + 1, hi = Math.min(a[2], b[2]) - 1;
      if (hi >= lo) { const x = Math.floor((lo + hi) / 2); return [[x, a[1]], [x, b[3]]]; }
    } else if (a[2] + 1 === b[0]) {                // a sits west of b
      const lo = Math.max(a[1], b[1]) + 1, hi = Math.min(a[3], b[3]) - 1;
      if (hi >= lo) { const y = Math.floor((lo + hi) / 2); return [[a[2], y], [b[0], y]]; }
    } else if (b[2] + 1 === a[0]) {                // b sits west of a
      const lo = Math.max(a[1], b[1]) + 1, hi = Math.min(a[3], b[3]) - 1;
      if (hi >= lo) { const y = Math.floor((lo + hi) / 2); return [[a[0], y], [b[2], y]]; }
    }
    return [];
  }

  /** The entrance cell on the rect's side: the middle cell of that edge (the generator's
   *  _entrance_cell). */
  function entranceCell(rect, side) {
    if (side === "n") return [rect[0] + Math.floor((rect[2] - rect[0]) / 2), rect[3]];
    if (side === "s") return [rect[0] + Math.floor((rect[2] - rect[0]) / 2), rect[1]];
    if (side === "w") return [rect[0], rect[1] + Math.floor((rect[3] - rect[1]) / 2)];
    return [rect[2], rect[1] + Math.floor((rect[3] - rect[1]) / 2)];
  }

  /** Split a footprint rectangle into rooms the way the generator lays out a building (see the
   *  section comment). `rect` is [x0, y0, x1, y1] inclusive; `rooms` [{name, share?}] (share a
   *  positive number, default 1); `connections` [[nameA, nameB]] (default: each room to the
   *  first); `entrance` {room, side} (default: the first room, "s"). Returns {rooms:
   *  [{name, rect}], doors: [[roomA, roomB, cellInsideA, cellInsideB]], entrance: [room, cell]}
   *  — the rooms tile the rect exactly, every touching pair carries a facing door pair inset
   *  one cell from the corners, the entrance cell lies on the footprint's named side — or
   *  {error} naming a workable footprint. Never mutates its arguments. */
  function splitRooms(rect, rooms, connections, entrance) {
    if (!Array.isArray(rect) || rect.length !== 4 || !rect.every(Number.isInteger) ||
        rect[2] < rect[0] || rect[3] < rect[1])
      return {error: "rect must be [x0, y0, x1, y1] with x1 >= x0 and y1 >= y0"};
    if (!Array.isArray(rooms) || !rooms.length)
      return {error: "rooms must be a non-empty list of {name, share?}"};
    const names = [];
    for (const r of rooms) {
      if (!r || typeof r !== "object" || Array.isArray(r))
        return {error: "a room must be an object {name, share?}"};
      if (typeof r.name !== "string" || !r.name) return {error: "every room needs a name"};
      if (names.includes(r.name)) return {error: 'two rooms are called "' + r.name + '"'};
      if (r.share !== undefined && (!Number.isFinite(r.share) || r.share <= 0))
        return {error: 'the share of "' + r.name + '" must be a positive number'};
      names.push(r.name);
    }
    let conns = connections;
    if (conns === undefined) conns = names.slice(1).map(n => [names[0], n]);
    if (!Array.isArray(conns)) return {error: "connections must be a list of [nameA, nameB]"};
    for (const c of conns) {
      if (!Array.isArray(c) || c.length !== 2 || !c.every(x => typeof x === "string"))
        return {error: "a connection is a pair of room names"};
      const off = c.find(x => !names.includes(x));
      if (off !== undefined)
        return {error: 'a connection names "' + off + '", which is not one of the rooms'};
    }
    const ent = entrance === undefined ? {} : entrance;
    if (!ent || typeof ent !== "object" || Array.isArray(ent))
      return {error: "entrance must be {room, side}"};
    const entRoom = ent.room === undefined ? names[0] : ent.room;
    const side = ent.side === undefined ? "s" : ent.side;
    if (!SIDES.includes(side)) return {error: "the entrance side is one of " + SIDES.join(", ")};
    if (!names.includes(entRoom))
      return {error: 'the entrance room "' + entRoom + '" is not one of the rooms'};

    const W = rect[2] - rect[0] + 1, H = rect[3] - rect[1] + 1;
    const tooSmall = min => "the " + W + "x" + H + " footprint cannot give every room " + MIN_SIDE +
      " cells on each side" + (min ? "; these shares need at least " + min[0] + "x" + min[1] +
      " cells" : "");
    if (names.length === 1) {
      if (W < MIN_SIDE || H < MIN_SIDE) return {error: tooSmall([MIN_SIDE, MIN_SIDE])};
      return {rooms: [{name: names[0], rect: rect.slice()}], doors: [],
              entrance: [names[0], entranceCell(rect, side)]};
    }

    const {children, root} = connectionTree(names, conns, entRoom);
    const needs = new Map(rooms.map(r =>
      [r.name, {area: (r.share === undefined ? 1 : r.share) * SHARE_AREA}]));
    const weights = new Map();               // a room's weight is its subtree's total need
    const weigh = n => {
      if (weights.has(n)) return weights.get(n);
      let w = needs.get(n).area;
      for (const k of children.get(n) || []) w += weigh(k);
      weights.set(n, w);
      return w;
    };
    weigh(root);

    /** Guillotine strips down the tree (the generator's _room_rects): every room's strip is cut
     *  along the entrance side of its rect, its children fill the remainder side by side. */
    const layout = fp => {
      const placements = new Map();
      (function assign(node, crect) {
        const kids = children.get(node) || [];
        if (!kids.length) { placements.set(node, crect); return; }
        const vert = side === "s" || side === "n";
        const span = vert ? crect[2] - crect[0] + 1 : crect[3] - crect[1] + 1;
        const axis = vert ? crect[3] - crect[1] + 1 : crect[2] - crect[0] + 1;
        const ownNeed = needs.get(node).area;
        // the strip holds this room, the rest the children: deep enough for their subtree areas
        const restMin = Math.max(MIN_SIDE, depthFor(weights.get(node) - ownNeed, span));
        const lo = Math.min(Math.max(MIN_SIDE, depthFor(ownNeed, span)), axis - 1);
        const hi = Math.max(lo, axis - Math.min(restMin, axis - 1));
        let size = Math.round(axis * ownNeed / weights.get(node));
        if (kids.length === 1)
          // a chain: the strip stays near the depth its own need asks and the tail takes the
          // rest, instead of proportional bands starving the last room into a sliver
          size = Math.min(size, Math.max(lo, depthFor(ownNeed, span) + 2));
        const [strip, rest] = stripSplit(crect, side, Math.max(lo, Math.min(size, hi)));
        placements.set(node, strip);
        const along = vert ? rest[2] - rest[0] + 1 : rest[3] - rest[1] + 1;
        const deep = vert ? rest[3] - rest[1] + 1 : rest[2] - rest[0] + 1;
        const sizes = sizesMins(along, kids.map(k => weights.get(k)),
          kids.map(k => Math.min(Math.max(MIN_SIDE, depthFor(weights.get(k), deep)), along)));
        let pos = 0;
        for (let i = 0; i < kids.length; i++) {
          assign(kids[i], vert
            ? [rest[0] + pos, rest[1], rest[0] + pos + sizes[i] - 1, rest[3]]
            : [rest[0], rest[1] + pos, rest[2], rest[1] + pos + sizes[i] - 1]);
          pos += sizes[i];
        }
      })(root, fp.slice());
      return placements;
    };

    const placements = layout(rect);
    const fits = p => names.every(n => { const r = p.get(n);
      return r && r[2] - r[0] + 1 >= MIN_SIDE && r[3] - r[1] + 1 >= MIN_SIDE; });
    if (!fits(placements)) {
      // name a workable size: the hard floor (3 cells a side, the tree's depth) grown until the
      // split honours every room's minimums — height first, then width, both capped for sanity
      const spanOf = n => { const kids = children.get(n) || [];
        return kids.length ? Math.max(MIN_SIDE, kids.reduce((s, k) => s + spanOf(k), 0)) : MIN_SIDE; };
      const depthOf = n => { const kids = children.get(n) || [];
        return MIN_SIDE + Math.max(0, ...kids.map(depthOf)); };
      const vert = side === "s" || side === "n";
      const span0 = spanOf(root), depth0 = depthOf(root);
      const grow = Math.max(0, Math.min(3 * Math.ceil(weights.get(root) / SHARE_AREA) + 24,
        200 - Math.max(span0, depth0)));
      let min = null;
      outer:
      for (let d = depth0; d <= depth0 + grow; d++)
        for (let a = span0; a <= span0 + grow; a++) {
          const w = vert ? a : d, h = vert ? d : a;
          if (fits(layout([0, 0, w - 1, h - 1]))) { min = [w, h]; break outer; }
        }
      return {error: tooSmall(min)};
    }

    const out = names.map(n => ({name: n, rect: placements.get(n).slice()}));
    const doors = [];
    for (let i = 0; i < out.length; i++)
      for (let j = i + 1; j < out.length; j++) {
        const pair = sharedWallCells(out[i].rect, out[j].rect);
        if (pair.length) doors.push([out[i].name, out[j].name, pair[0], pair[1]]);
      }
    return {rooms: out, doors, entrance: [root, entranceCell(rect, side)]};
  }

  return {furnish, splitRooms, parseHint, constrained, reserveWalkways};
});
