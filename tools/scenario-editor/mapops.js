"use strict";
// Map edits for the Scenario Editor, kept apart from the page so they can be tested with node.
// Every function that changes the scenario takes `set(obj, key, value)`, which the page records for
// undo. Nothing here touches the DOM. Coordinates: [0,0] is the bottom-left cell, y grows north.
// Rules follow the game's own World editing mode: walls are thin lines on a walled region's border,
// and a door ("opening") is a cell of the region's own outer row or column.

(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.MapOps = factory();
})(typeof self !== "undefined" ? self : this, function () {

  // ---------------------------------------------------------------- geometry
  /** Inclusive [x0, y0, x1, y1] of a region ({position, size}) or an entity ({pos, size}). */
  function rect(o) {
    const p = o.position || o.pos, s = o.size || [1, 1];
    return [p[0], p[1], p[0] + s[0] - 1, p[1] + s[1] - 1];
  }
  const inRect = (r, x, y) => x >= r[0] && y >= r[1] && x <= r[2] && y <= r[3];
  const containsRect = (o, i) => o[0] <= i[0] && o[1] <= i[1] && i[2] <= o[2] && i[3] <= o[3];
  const disjoint = (a, b) => a[2] < b[0] || b[2] < a[0] || a[3] < b[1] || b[3] < a[1];
  const sameRect = (a, b) => a[0] === b[0] && a[1] === b[1] && a[2] === b[2] && a[3] === b[3];
  /** Two rectangles that are neither apart nor one inside the other: never allowed between regions. */
  const partial = (a, b) => !(disjoint(a, b) || containsRect(a, b) || containsRect(b, a));
  const onEdge = (r, c) => inRect(r, c[0], c[1]) && (c[0] === r[0] || c[0] === r[2] || c[1] === r[1] || c[1] === r[3]);
  const eqCell = (a, b) => a[0] === b[0] && a[1] === b[1];
  const clone = o => JSON.parse(JSON.stringify(o));

  /** The perimeter cell of r nearest to c (by city-block distance, first found wins ties). */
  function nearestEdgeCell(r, c) {
    const x = Math.min(r[2], Math.max(r[0], c[0])), y = Math.min(r[3], Math.max(r[1], c[1]));
    if (onEdge(r, [x, y])) return [x, y];
    const opts = [[r[0], y], [r[2], y], [x, r[1]], [x, r[3]]];
    let best = opts[0], bd = Infinity;
    for (const o of opts) { const d = Math.abs(o[0] - x) + Math.abs(o[1] - y); if (d < bd) { bd = d; best = o; } }
    return best;
  }

  /** Doors moved onto the region's (new) edge, duplicates removed, as the game does after a resize. */
  function snapOpenings(region) {
    const r = rect(region), out = [];
    for (const o of region.openings || []) {
      const c = onEdge(r, o) ? [o[0], o[1]] : nearestEdgeCell(r, o);
      if (!out.some(d => eqCell(d, c))) out.push(c);
    }
    return out;
  }

  /** Regions strictly inside `region` (not itself), and entities standing wholly inside it. */
  function contents(scn, region) {
    const r = rect(region);
    const regions = scn.regions.filter(o => o !== region && containsRect(r, rect(o))
      && !(sameRect(r, rect(o)) && scn.regions.indexOf(o) < scn.regions.indexOf(region)));
    const entities = scn.entities.filter(e => containsRect(r, rect(e)));
    return {regions, entities};
  }

  /** The smallest region that contains `region`, or null. */
  function parentOf(scn, region) {
    const r = rect(region);
    let best = null;
    for (const o of scn.regions) {
      if (o === region || !containsRect(rect(o), r)) continue;
      if (sameRect(rect(o), r) && scn.regions.indexOf(o) > scn.regions.indexOf(region)) continue;
      if (!best || o.size[0] * o.size[1] < best.size[0] * best.size[1]) best = o;
    }
    return best;
  }

  /** The smallest region at cell (x, y), or null. */
  function regionAt(scn, x, y) {
    let best = null;
    for (const o of scn.regions) if (inRect(rect(o), x, y) && (!best || o.size[0] * o.size[1] < best.size[0] * best.size[1])) best = o;
    return best;
  }

  /** null if the proposed rectangles (Map region -> rect) keep every pair of regions nested or apart,
   *  else a message naming the first clash. Regions not in the map keep their current rectangle. */
  function nestingProblem(scn, proposed) {
    const rs = scn.regions, R = o => proposed.get(o) || rect(o);
    for (const a of proposed.keys()) for (const b of rs) {
      if (a === b) continue;
      if (partial(R(a), R(b))) return `"${a.name}" would partly overlap "${b.name}"`;
    }
    return null;
  }

  function inGrid(scn, r) {
    return r[0] >= 0 && r[1] >= 0 && r[2] < scn.gridSize[0] && r[3] < scn.gridSize[1];
  }

  // ---------------------------------------------------------------- ids and names
  let counter = 0;
  /** A new id in the game's style: prefix_<base36 ms>_<base36 counter>_<random>. */
  function newId(prefix) {
    const rand = Math.random().toString(36).slice(2, 6).padEnd(4, "0");
    return `${prefix}_${Date.now().toString(36)}_${(counter++).toString(36)}_${rand}`;
  }

  /** `base N` with the next number not used by any name in `names` (e.g. "Cot 10" after "Cot 9"). */
  function nextName(base, names) {
    let n = 0;
    const re = new RegExp("^" + base.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + " (\\d+)$");
    for (const nm of names) { const m = re.exec(nm); if (m) n = Math.max(n, +m[1]); if (nm === base) n = Math.max(n, 1); }
    return `${base} ${n + 1}`;
  }

  // ---------------------------------------------------------------- moving
  /** Moves a region with everything inside it (rooms, doors, objects, people) by (dx, dy), shortened
   *  so it stays on the map. Returns {dx, dy} actually moved, or {error} without changing anything. */
  function moveRegion(scn, region, dx, dy, set) {
    const r = rect(region), [gw, gh] = scn.gridSize;
    dx = Math.max(-r[0], Math.min(gw - 1 - r[2], dx));
    dy = Math.max(-r[1], Math.min(gh - 1 - r[3], dy));
    if (!dx && !dy) return {dx: 0, dy: 0};
    const inside = contents(scn, region), moved = [region, ...inside.regions];
    const proposed = new Map(moved.map(o => { const q = rect(o); return [o, [q[0] + dx, q[1] + dy, q[2] + dx, q[3] + dy]]; }));
    const err = nestingProblem(scn, proposed);
    if (err) return {error: err};
    for (const o of moved) {
      set(o, "position", [o.position[0] + dx, o.position[1] + dy]);
      set(o, "openings", (o.openings || []).map(c => [c[0] + dx, c[1] + dy]));
    }
    for (const e of inside.entities) set(e, "pos", [e.pos[0] + dx, e.pos[1] + dy]);
    return {dx, dy};
  }

  /** Moves entities together by (dx, dy), shortened so all stay on the map. Returns {dx, dy}. */
  function moveEntities(scn, ents, dx, dy, set) {
    const [gw, gh] = scn.gridSize;
    for (const e of ents) {
      const r = rect(e);
      dx = Math.max(-r[0], Math.min(gw - 1 - r[2], dx));
      dy = Math.max(-r[1], Math.min(gh - 1 - r[3], dy));
    }
    if (dx || dy) for (const e of ents) set(e, "pos", [e.pos[0] + dx, e.pos[1] + dy]);
    return {dx, dy};
  }

  /** Turns an object by quarter turns, as the game does: `rot` 0-3 (left out when 0), the footprint's
   *  width and height swap on odd turns, and it turns about its centre cell, kept on the map. */
  function rotateObject(scn, e, quarters, set) {
    const p = ((Math.round(quarters) % 4) + 4) % 4;
    if (!p || e.type !== "object") return false;
    const size = e.size || [1, 1];
    const centre = [e.pos[0] + Math.floor((size[0] - 1) / 2), e.pos[1] + Math.floor((size[1] - 1) / 2)];
    const ns = p % 2 ? [size[1], size[0]] : [size[0], size[1]];
    const rot = ((e.rot || 0) + p) % 4;
    let x = centre[0] - Math.floor((ns[0] - 1) / 2), y = centre[1] - Math.floor((ns[1] - 1) / 2);
    x = Math.max(0, Math.min(scn.gridSize[0] - ns[0], x));
    y = Math.max(0, Math.min(scn.gridSize[1] - ns[1], y));
    set(e, "rot", rot || undefined);
    set(e, "size", ns);
    set(e, "pos", [x, y]);
    return true;
  }

  // ---------------------------------------------------------------- resizing
  const EDGE = {w: 0, s: 1, e: 2, n: 3};            // index into an inclusive rect
  const OPPOSITE = {w: "e", e: "w", s: "n", n: "s"};

  /** Moves one edge of a region ("n", "s", "e" or "w") to the cell line `to` (for "e" the new last
   *  column, for "w" the new first column, and so on).
   *  With follow (the default), walls it shares follow: a containing region whose same edge is on
   *  the same line moves with it, so do the rooms inside it whose same edge is on that line, and a
   *  neighbouring room whose facing edge touches or shares the line moves too, so rooms that split a
   *  building stay split. follow: false moves only its own.
   *  Returns {changed: [regions]} or {error} without changing anything. */
  function resizeRegion(scn, region, edge, to, set, follow = true) {
    const i = EDGE[edge];
    if (i === undefined) return {error: "bad edge"};
    const r = rect(region), from = r[i];
    if (to === from) return {changed: []};
    const proposed = new Map();
    const put = (o, k, v) => { const q = (proposed.get(o) || rect(o)).slice(); q[k] = v; proposed.set(o, q); };
    put(region, i, to);
    if (follow) {
      const along = i % 2 === 0 ? [1, 3] : [0, 2];     // the span of the edge
      const overlapsSpan = q => !(q[along[1]] < r[along[0]] || r[along[1]] < q[along[0]]);
      for (const o of scn.regions) {
        if (o === region) continue;
        const q = rect(o);
        if (containsRect(q, r) && q[i] === from) put(o, i, to);   // the building's wall
      }
      for (const o of contents(scn, region).regions) if (rect(o)[i] === from) put(o, i, to);   // its rooms on that wall
      const oi = EDGE[OPPOSITE[edge]], step = i < 2 ? -1 : 1;     // facing edge is one cell outward or on the line
      const p = parentOf(scn, region);
      for (const o of scn.regions) {
        if (o === region || parentOf(scn, o) !== p || !o.wall !== !region.wall) continue;
        const q = rect(o);
        if (!overlapsSpan(q)) continue;
        if (q[oi] === from + step) put(o, oi, to + step);
        else if (q[oi] === from) put(o, oi, to);
      }
    }
    for (const [o, q] of proposed) {
      const minSize = o.wall ? 2 : 1;
      if (q[2] - q[0] + 1 < minSize || q[3] - q[1] + 1 < minSize) return {error: `"${o.name}" would be too small`};
      if (!inGrid(scn, q)) return {error: `"${o.name}" would leave the map`};
    }
    const err = nestingProblem(scn, proposed);
    if (err) return {error: err};
    for (const [o, q] of proposed) {
      set(o, "position", [q[0], q[1]]);
      set(o, "size", [q[2] - q[0] + 1, q[3] - q[1] + 1]);
      set(o, "openings", snapOpenings({position: [q[0], q[1]], size: [q[2] - q[0] + 1, q[3] - q[1] + 1], openings: o.openings}));
    }
    return {changed: [...proposed.keys()]};
  }

  /** Which edge of the region's outline a point (in fractional cell units) is within `tol` cells of,
   *  or null. Used to start a resize drag. */
  function edgeAt(region, x, y, tol) {
    const r = rect(region), X0 = r[0], Y0 = r[1], X1 = r[2] + 1, Y1 = r[3] + 1;
    const inX = x >= X0 - tol && x <= X1 + tol, inY = y >= Y0 - tol && y <= Y1 + tol;
    const near = [["w", Math.abs(x - X0), inY], ["e", Math.abs(x - X1), inY], ["s", Math.abs(y - Y0), inX], ["n", Math.abs(y - Y1), inX]]
      .filter(([, d, ok]) => ok && d <= tol).sort((a, b) => a[1] - b[1]);
    return near.length ? near[0][0] : null;
  }

  // ---------------------------------------------------------------- doors
  /** The (region, inside cell) pairs that must all list a door so a person can walk from `cell` out
   *  through `region`'s border: the region itself, a building whose wall is on the same line, and a
   *  neighbouring room on the other side (its facing cell). */
  function doorSet(scn, region, cell) {
    const r = rect(region), out = [];
    const dirs = [];
    if (cell[0] === r[0]) dirs.push([-1, 0]);
    if (cell[0] === r[2]) dirs.push([1, 0]);
    if (cell[1] === r[1]) dirs.push([0, -1]);
    if (cell[1] === r[3]) dirs.push([0, 1]);
    for (const [dx, dy] of dirs) {
      const n = [cell[0] + dx, cell[1] + dy];
      if (n[0] < 0 || n[1] < 0 || n[0] >= scn.gridSize[0] || n[1] >= scn.gridSize[1]) continue;
      for (const w of scn.regions) {
        if (!w.wall) continue;
        const q = rect(w), a = inRect(q, cell[0], cell[1]), b = inRect(q, n[0], n[1]);
        if (a === b) continue;
        const inner = a ? cell : n;
        if (!out.some(t => t.region === w && eqCell(t.cell, inner))) out.push({region: w, cell: inner});
      }
    }
    return out;
  }

  /** Adds or removes a door at a cell on a walled region's edge, keeping the whole passage consistent
   *  (doorSet). Returns {added: bool, regions: [names]} or {error}. */
  function toggleDoor(scn, region, cell, set) {
    if (!region.wall) return {error: `"${region.name}" has no walls`};
    if (!onEdge(rect(region), cell)) return {error: "A door has to be on the region's outer row or column"};
    const has = (region.openings || []).some(c => eqCell(c, cell));
    const pairs = doorSet(scn, region, cell);
    if (!pairs.length) pairs.push({region, cell});
    const touched = new Map();
    for (const {region: w, cell: c} of pairs) {
      const list = (touched.get(w) || w.openings || []).slice();
      const at = list.findIndex(d => eqCell(d, c));
      if (has && at >= 0) list.splice(at, 1);
      if (!has && at < 0) list.push([c[0], c[1]]);
      touched.set(w, list);
    }
    for (const [w, list] of touched) set(w, "openings", list);
    return {added: !has, regions: [...touched.keys()].map(w => w.name)};
  }

  // ---------------------------------------------------------------- creating
  /** A new region from cell a to cell b (any two opposite corners). props: {name, wall, hostile}.
   *  Ground and ambience come from the region it is drawn inside. Returns {region} or {error}. */
  function createRegion(scn, a, b, props, set) {
    const q = [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
    const name = (props.name || "").trim();
    if (!name) return {error: "A region needs a name"};
    if (scn.regions.some(o => o.name === name)) return {error: `Another region is already called "${name}"`};
    if (!inGrid(scn, q)) return {error: "The region would leave the map"};
    if (props.wall && (q[2] - q[0] < 1 || q[3] - q[1] < 1)) return {error: "A walled region needs at least 2 × 2 cells"};
    const region = {id: newId("rgn"), name, description: props.description || ""};
    if (props.wall) region.wall = props.wall;
    const temp = {position: [q[0], q[1]], size: [q[2] - q[0] + 1, q[3] - q[1] + 1]};
    for (const o of scn.regions) if (partial(rect(o), q)) return {error: `It would partly overlap "${o.name}"`};
    const parent = scn.regions.filter(o => containsRect(rect(o), q)).sort((m, n) => m.size[0] * m.size[1] - n.size[0] * n.size[1])[0];
    const base = parent || scn.defaultTile || {};
    region.ground = props.wall && !parent?.wall ? "wood" : base.ground || "dirt";
    region.groundTexture = props.wall && !parent?.wall ? "floorboards" : base.groundTexture || "dirt";
    region.openings = [];
    region.position = temp.position;
    region.size = temp.size;
    region.ambience = props.wall ? {day: "quiet_indoor"} : clone(base.ambience || {day: "nature_outdoors"});
    if (props.hostile) region.hostile = true;
    set(scn, "regions", [...scn.regions, region]);
    return {region};
  }

  /** Places a copy of an object template with its footprint's bottom-left at (x, y), kept on the map. */
  function placeObject(scn, tpl, x, y, set) {
    const size = (tpl.size || [1, 1]).slice();
    x = Math.max(0, Math.min(scn.gridSize[0] - size[0], x));
    y = Math.max(0, Math.min(scn.gridSize[1] - size[1], y));
    const e = {id: newId("obj"), type: "object", name: nextName(tpl.name, scn.entities.map(o => o.name)),
      pos: [x, y], size, hp: tpl.maxHp ?? 50, maxHp: tpl.maxHp ?? 50, inventory: [],
      statusEffects: (tpl.startingEffects || []).map(def => ({id: newId("se"), def: clone(def), appliedAt: 28800, source: "template"})),
      templateId: tpl.id};
    set(scn, "entities", [...scn.entities, e]);
    return e;
  }

  /** Places a new NPC at (x, y). props: {name, gender}. Their schedule starts as "here all day" in
   *  the region they stand in. Returns {npc} or {error}. */
  function placeNpc(scn, props, x, y, set) {
    const name = (props.name || "").trim();
    if (!name) return {error: "An NPC needs a name"};
    const gender = props.gender === "male" ? "male" : "female";
    const here = regionAt(scn, x, y);
    const npc = {id: newId("npc"), type: "npc", name, gender, description: props.description || "",
      pos: [x, y], size: [1, 1], hp: 100, maxHp: 100,
      schedule: here ? [{start: "00:00", end: "00:00", location: here.name, role: "leisure"}] : [],
      animationId: gender === "male" ? "casual-man" : "casual-woman", physicalDescription: props.physicalDescription || "",
      voiceProfile: {gender: gender === "male" ? "Male" : "Female", age: ["Adult"]}, level: 1, money: 0,
      inventory: [], statusEffects: []};
    set(scn, "entities", [...scn.entities, npc]);
    return {npc};
  }

  /** Removes entities and regions by id. Doesn't check references; the page does that first. */
  function remove(scn, ids, set) {
    const gone = new Set(ids);
    if (scn.entities.some(e => gone.has(e.id))) set(scn, "entities", scn.entities.filter(e => !gone.has(e.id)));
    if (scn.regions.some(r => gone.has(r.id))) set(scn, "regions", scn.regions.filter(r => !gone.has(r.id)));
  }

  // ---------------------------------------------------------------- copy and paste
  /** A region with the rooms and objects inside it, for pasting elsewhere. People are left out. */
  function copyRegion(scn, region) {
    const inside = contents(scn, region);
    return {origin: region.position.slice(), regions: [region, ...inside.regions].map(clone),
      entities: inside.entities.filter(e => e.type === "object").map(clone)};
  }

  /** Pastes a copyRegion() clip with its bottom-left at (x, y): new ids, new names ("Kitchen 2"),
   *  everything moved. Returns {region} (the outermost) or {error}. */
  function pasteRegion(scn, clip, x, y, set) {
    const dx = x - clip.origin[0], dy = y - clip.origin[1];
    const names = scn.regions.map(r => r.name), regs = [];
    for (const r of clip.regions) {
      const n = clone(r);
      n.id = newId("rgn");
      n.name = nextName(r.name.replace(/ \d+$/, ""), names); names.push(n.name);
      n.position = [r.position[0] + dx, r.position[1] + dy];
      n.openings = (r.openings || []).map(c => [c[0] + dx, c[1] + dy]);
      if (!inGrid(scn, rect(n))) return {error: "The copy would leave the map"};
      regs.push(n);
    }
    for (const n of regs) for (const o of scn.regions) if (partial(rect(o), rect(n))) return {error: `The copy would partly overlap "${o.name}"`};
    const enames = scn.entities.map(e => e.name), ents = clip.entities.map(e => {
      const n = clone(e);
      n.id = newId("obj"); n.pos = [e.pos[0] + dx, e.pos[1] + dy];
      n.name = nextName(e.name.replace(/ \d+$/, ""), enames); enames.push(n.name);
      for (const s of n.statusEffects || []) s.id = newId("se");
      for (const s of n.inventory || []) s.id = newId("it");
      return n;
    });
    set(scn, "regions", [...scn.regions, ...regs]);
    set(scn, "entities", [...scn.entities, ...ents]);
    return {region: regs[0]};
  }

  return {rect, inRect, containsRect, disjoint, partial, onEdge, nearestEdgeCell, snapOpenings, contents, parentOf,
    regionAt, nestingProblem, newId, nextName, moveRegion, moveEntities, rotateObject, resizeRegion, edgeAt, doorSet,
    toggleDoor, createRegion, placeObject, placeNpc, remove, copyRegion, pasteRegion};
});
