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

  return {furnish, parseHint, constrained, reserveWalkways};
});
