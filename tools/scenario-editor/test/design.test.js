"use strict";
// node --test      (from tools/scenario-editor)
const test = require("node:test");
const assert = require("node:assert/strict");
const D = require("../design.js");

// The generator's room fixture (tests/test_room.py) — Bed 1x2, Table 2x1, Stool 1x1, Chest 2x2 —
// plus the solid pieces the boxed-in tests need, in a walled 11x9 region with three openings.
function world() {
  return {
    gridSize: [30, 30], defaultTile: {ground: "grass"},
    objectTemplates: [
      {id: "bed", name: "Bed", size: [1, 2]},
      {id: "table", name: "Table", size: [2, 1]},
      {id: "stool", name: "Stool", size: [1, 1]},
      {id: "chest", name: "Chest", size: [2, 2]},
      {id: "board", name: "Board", size: [2, 1], walkability: 0.2},
      {id: "crate", name: "Crate", size: [1, 1], walkability: 0},
      {id: "shelf", name: "Shelf", size: [5, 1], walkability: 0},
    ],
    regions: [
      {id: "home", name: "Home", wall: "wood", position: [5, 5], size: [11, 9],
        openings: [[10, 5], [10, 13], [15, 8]]},
    ],
    entities: [
      {id: "pat", type: "player", name: "Pat", pos: [7, 7], size: [1, 1]},
      {id: "old", type: "object", name: "Old Chest", pos: [13, 11], size: [2, 2], templateId: "chest"},
    ],
  };
}
const R = (s, id) => s.regions.find(r => r.id === id);
const sizeOf = (s, id) => s.objectTemplates.find(t => t.id === id).size;

function footprint(pos, size) {
  const out = [];
  for (let x = pos[0]; x < pos[0] + size[0]; x++)
    for (let y = pos[1]; y < pos[1] + size[1]; y++) out.push([x, y]);
  return out;
}

// The engine's own flood, hand-rolled here to check placements against it.
function flood(rect, covered, doors) {
  const walk = k => {
    const [x, y] = k.split(",").map(Number);
    return x >= rect[0] && y >= rect[1] && x <= rect[2] && y <= rect[3] && !covered.has(k);
  };
  const seen = new Set(), todo = [];
  for (const d of doors) { const k = d.join(","); if (walk(k)) { seen.add(k); todo.push(k); } }
  while (todo.length) {
    const [x, y] = todo.pop().split(",").map(Number);
    for (const k of [x + 1 + "," + y, x - 1 + "," + y, x + "," + (y + 1), x + "," + (y - 1)])
      if (walk(k) && !seen.has(k)) { seen.add(k); todo.push(k); }
  }
  return seen;
}
const ring = (pos, size) => {
  const out = [];
  for (let x = pos[0] - 1; x <= pos[0] + size[0]; x++)
    for (let y = pos[1] - 1; y <= pos[1] + size[1]; y++)
      if (x < pos[0] || x >= pos[0] + size[0] || y < pos[1] || y >= pos[1] + size[1]) out.push(x + "," + y);
  return out;
};

// ---------------------------------------------------------------- the room

test("every placement is inside the room, off the walkways, the entities and each other", () => {
  const s = world();
  const out = D.furnish(s, R(s, "home"), [
    {templateId: "bed", count: 3, hint: "wall:n"},
    {templateId: "table", count: 2, hint: "center"},
    {templateId: "stool", count: 6, hint: "around:Table"},
    {templateId: "chest", count: 2, hint: "corner"},
  ]);
  assert.deepEqual(out.failures, []);
  assert.equal(out.placements.length, 13);
  const rect = [5, 5, 15, 13];
  const reserved = D.reserveWalkways(rect, [[10, 5], [10, 13], [15, 8]]).reserved;
  const blocked = new Set([...footprint([7, 7], [1, 1]), ...footprint([13, 11], [2, 2])]
    .map(c => c.join(",")));
  const seen = new Set();
  for (const p of out.placements) {
    for (const [x, y] of footprint(p.pos, sizeOf(s, p.templateId))) {
      const k = x + "," + y;
      assert.ok(x >= rect[0] && y >= rect[1] && x <= rect[2] && y <= rect[3],
        p.templateId + " at " + p.pos + " is outside the room");
      assert.ok(!reserved.has(k), p.templateId + " at " + p.pos + " blocks a door/walkway");
      assert.ok(!blocked.has(k), p.templateId + " at " + p.pos + " covers an existing entity");
      assert.ok(!seen.has(k), p.templateId + " at " + p.pos + " overlaps another piece");
      seen.add(k);
    }
  }
});

test("around:Table puts the stools in a ring round the table", () => {
  const s = world();
  s.regions[0] = {id: "home", name: "Home", wall: "wood", position: [0, 0], size: [12, 9],
    openings: [[5, 0], [6, 8]]};
  s.entities = [];
  const out = D.furnish(s, R(s, "home"), [
    {templateId: "table", count: 1, hint: "center"},
    {templateId: "stool", count: 6, hint: "around:Table"},
  ]);
  assert.deepEqual(out.failures, []);
  const table = out.placements.find(p => p.templateId === "table");
  const stools = out.placements.filter(p => p.templateId === "stool").map(p => p.pos);
  assert.ok(table, "the table placed");
  assert.equal(stools.length, 6);
  const near = stools.filter(p =>
    Math.max(Math.abs(p[0] - table.pos[0]), Math.abs(p[1] - table.pos[1])) <= 2);
  assert.ok(near.length >= 4, "stools " + JSON.stringify(stools) +
    " not around the table at " + JSON.stringify(table.pos));
});

test("a full room reports a failure with the count that did fit", () => {
  const s = world();
  s.regions[0] = {id: "small", name: "Small", wall: "wood", position: [5, 5], size: [5, 5],
    openings: [[7, 5], [7, 9]]};
  s.entities = [];
  const out = D.furnish(s, R(s, "small"), [{templateId: "chest", count: 12, hint: "corner"}]);
  assert.equal(out.failures.length, 1);
  const f = out.failures[0];
  assert.equal(f.templateId, "chest");
  assert.equal(f.wanted, 12);
  assert.ok(f.placed < 12);
  assert.equal(f.placed, out.placements.length, "the failure reports the count that did fit");
  assert.ok(out.fallbacks.some(x => /could not be fully met/.test(x.reason)));
});

test("an unknown template is a failure with that reason", () => {
  const s = world();
  const out = D.furnish(s, R(s, "home"), [{templateId: "sofa", count: 1}]);
  assert.deepEqual(out.failures, [{templateId: "sofa", placed: 0, wanted: 1, reason: "unknown template"}]);
  assert.deepEqual(out.placements, []);
});

test("symmetric pairs never share a cell, across room widths 7 to 11", () => {
  for (let w = 7; w <= 11; w++) {
    const s = world();
    s.regions[0] = {id: "hall", name: "Hall", wall: "wood", position: [0, 0], size: [w, 5],
      openings: [[0, 2]]};
    s.entities = [];
    const out = D.furnish(s, R(s, "hall"), [{templateId: "board", count: 2, hint: "symmetric"}]);
    assert.equal(out.placements.length, 2, "width " + w);
    const cells = [];
    for (const p of out.placements)
      for (const c of footprint(p.pos, [2, 1])) cells.push(c.join(","));
    assert.equal(new Set(cells).size, cells.length, "width " + w + " shares a cell: " +
      JSON.stringify(out.placements));
  }
});

test("symmetric places a mirrored pair when the mirror is clear of the piece", () => {
  const s = world();
  s.regions[0] = {id: "hall", name: "Hall", wall: "wood", position: [0, 0], size: [9, 5],
    openings: [[4, 0]]};
  s.entities = [];
  const out = D.furnish(s, R(s, "hall"), [{templateId: "board", count: 2, hint: "wall:w+symmetric"}]);
  assert.deepEqual(out.failures, []);
  assert.equal(out.placements.length, 2);
  const [a, b] = out.placements.map(p => p.pos);
  assert.equal(a[0], 0, "the first board stands on the west wall");
  // the second is the first turned about the room's centre: x0 + x1 - (w - 1), y0 + y1 - (h - 1)
  assert.deepEqual([a[0] + b[0], a[1] + b[1]], [0 + 8 - 1, 0 + 4 - 0]);
});

test("furnish is deterministic and never mutates the scenario", () => {
  const items = [
    {templateId: "bed", count: 3, hint: "wall:n"},
    {templateId: "table", count: 2, hint: "center"},
    {templateId: "stool", count: 6, hint: "around:Table"},
    {templateId: "chest", count: 2, hint: "corner"},
  ];
  const a = world(), b = world();
  const before = JSON.stringify(a);
  const outA = D.furnish(a, a.regions[0], items);
  assert.equal(JSON.stringify(a), before, "the scenario changed");
  assert.deepEqual(outA, D.furnish(b, b.regions[0], items));
});

test("a room inside the building contributes no floor cells", () => {
  const s = world();
  s.regions = [
    {id: "house", name: "House", wall: "wood", position: [0, 0], size: [11, 9], openings: [[5, 8]]},
    {id: "parlour", name: "Parlour", wall: "wood", position: [3, 2], size: [5, 5], openings: [[5, 2]]},
  ];
  s.entities = [];
  const out = D.furnish(s, s.regions[0], [
    {templateId: "chest", count: 1, hint: "center"},
    {templateId: "stool", count: 4, hint: "wall:e"},
  ]);
  assert.deepEqual(out.failures, []);
  assert.ok(out.placements.length > 0);
  const inner = [3, 2, 7, 6];                        // the parlour's rect
  for (const p of out.placements)
    for (const [x, y] of footprint(p.pos, sizeOf(s, p.templateId)))
      assert.ok(!(x >= inner[0] && y >= inner[1] && x <= inner[2] && y <= inner[3]),
        p.templateId + " at " + p.pos + " sits inside the inner room");
});

// ---------------------------------------------------------------- boxed-in

test("a solid piece boxed in behind a sealed row is re-placed where the door reaches it", () => {
  const s = world();
  s.regions = [{id: "shed", name: "Shed", wall: "wood", position: [0, 0], size: [5, 8],
    openings: [[2, 0]]}];
  s.entities = [{id: "junk", type: "object", name: "Junk Wall", pos: [0, 3], size: [5, 1],
    templateId: "shelf"}];
  const out = D.furnish(s, s.regions[0], [{templateId: "crate", count: 1, hint: "corner"}]);
  assert.deepEqual(out.failures, []);
  assert.equal(out.placements.length, 1);
  const p = out.placements[0];
  assert.ok(p.pos[1] <= 2, "the crate stayed in the half the wall seals off: " + JSON.stringify(p.pos));
  const covered = new Set(footprint([0, 3], [5, 1]).map(c => c.join(",")));
  const seen = flood([0, 0, 4, 7], covered, [[2, 0]]);
  assert.ok(ring(p.pos, [1, 1]).some(k => seen.has(k)),
    "the crate at " + JSON.stringify(p.pos) + " is sealed off from the door");
});

test("a solid piece with nowhere unboxed to go is dropped with the boxed-in failure", () => {
  const s = world();
  s.regions = [{id: "hall", name: "Hall", wall: "wood", position: [0, 0], size: [5, 12],
    openings: [[2, 0]]}];
  s.entities = [{id: "jam", type: "object", name: "Jam", pos: [0, 1], size: [5, 1],
    templateId: "shelf"}];
  const out = D.furnish(s, s.regions[0], [{templateId: "shelf", count: 1}]);
  assert.deepEqual(out.placements, [], "every free spot is sealed off behind the jam");
  assert.deepEqual(out.failures,
    [{templateId: "shelf", placed: 0, wanted: 1, reason: "no placement that keeps the room walkable"}]);
});

// ---------------------------------------------------------------- sealing (the fifth divergence)

test("a solid row across a room never strands the floor behind it", () => {
  const s = world();
  s.regions = [{id: "hall", name: "Hall", wall: "wood", position: [0, 0], size: [3, 6],
    openings: [[1, 0]]}];
  s.entities = [];
  // a 3x1 solid wall-piece fills the hall's width; only the row against the north wall leaves
  // nothing stranded behind it
  const out = D.furnish(s, s.regions[0], [{templateId: "bar", count: 1}]);
  s.objectTemplates.push({id: "bar", name: "Bar", size: [3, 1], walkability: 0});
  const withBar = D.furnish(s, s.regions[0], [{templateId: "bar", count: 1}]);
  assert.deepEqual(withBar.placements.map(p => p.pos), [[0, 5]], JSON.stringify(withBar));
  assert.deepEqual(withBar.failures, []);
  assert.deepEqual(out.failures, [{templateId: "bar", placed: 0, wanted: 1,
    reason: "unknown template"}]);
});

test("solid pieces place freely on a floor with no doorways", () => {
  const s = world();
  s.regions = [{id: "field", name: "Field", position: [0, 0], size: [8, 8], openings: []}];
  s.entities = [];
  const out = D.furnish(s, s.regions[0], [{templateId: "crate", count: 6, hint: "corner"}]);
  assert.deepEqual(out.failures, []);
  assert.equal(out.placements.length, 6);
});

test("nothing is placed on the cell outside a nested room's door", () => {
  const s = world();
  s.regions = [
    {id: "house", name: "House", wall: "wood", position: [0, 0], size: [11, 9], openings: []},
    {id: "parlour", name: "Parlour", wall: "wood", position: [3, 2], size: [5, 5], openings: [[7, 4, "e"]]},
  ];
  s.entities = [];
  const out = D.furnish(s, s.regions[0], [
    {templateId: "crate", count: 12}, {templateId: "crate", count: 12}]);
  assert.deepEqual(out.failures, [], JSON.stringify(out.failures));
  // [8, 4] is the step off the parlour's east door; every crate avoids it
  for (const p of out.placements)
    assert.ok(!(p.pos[0] === 8 && p.pos[1] === 4), "a crate blocks the parlour door: " + p.pos);
  assert.equal(out.placements.length, 24);
});


// ---------------------------------------------------------------- the hint parser

test("parseHint: wall:<side> keeps a piece against a wall", () => {
  const h = D.parseHint("wall:n");
  assert.deepEqual(h.walls, ["n"]);
  assert.equal(D.constrained(h), true);
});

test("parseHint: far, side and near name the walls relative to the door", () => {
  for (const side of ["far", "side", "near"]) {
    const h = D.parseHint("wall:" + side);
    assert.deepEqual(h.walls, [side]);
    assert.equal(D.constrained(h), true);
  }
});

test("parseHint: row:<side> keeps a piece along a wall", () => {
  const h = D.parseHint("row:e");
  assert.equal(h.row, "e");
  assert.equal(D.constrained(h), true);
});

test("parseHint: corner", () => {
  assert.equal(D.parseHint("corner").corner, true);
});

test("parseHint: center", () => {
  const h = D.parseHint("center");
  assert.equal(h.center, true);
  assert.equal(D.constrained(h), true);
});

test("parseHint: near_door", () => {
  assert.equal(D.parseHint("near_door").nearDoor, true);
});

test("parseHint: away_from_door", () => {
  assert.equal(D.parseHint("away_from_door").awayFromDoor, true);
});

test("parseHint: symmetric", () => {
  assert.equal(D.parseHint("symmetric").symmetric, true);
});

test("parseHint: beside:<ref> and around:<ref> take a template reference", () => {
  assert.equal(D.parseHint("around:Trestle table").around, "Trestle table");
  assert.equal(D.parseHint("beside:Clay hearth").beside, "Clay hearth");
});

test("parseHint: tokens join with +", () => {
  const h = D.parseHint("wall:n+center");
  assert.deepEqual(h.walls, ["n"]);
  assert.equal(h.center, true);
});

test("parseHint: unknown tokens mean unconstrained", () => {
  const h = D.parseHint("on the ceiling");
  assert.deepEqual(h.unknown, ["on the ceiling"]);
  assert.equal(D.constrained(h), false);
  const w = D.parseHint("wall:diagonal");
  assert.deepEqual(w.unknown, ["wall:diagonal"]);
  assert.equal(D.constrained(w), false);
});

test("parseHint: wall:any and the empty hint carry nothing", () => {
  const h = D.parseHint("wall:any");
  assert.deepEqual(h.unknown, []);
  assert.equal(D.constrained(h), false);
  assert.equal(D.constrained(D.parseHint("")), false);
  assert.equal(D.constrained(D.parseHint(undefined)), false);
});

// ---------------------------------------------------------------- bad items

test("malformed items are failures, never a throw", () => {
  const s = world();
  const out = D.furnish(s, R(s, "home"), [
    {count: 1},
    {templateId: "stool", count: 0},
    {templateId: "stool", count: 13},
    {templateId: "stool", count: 1, hint: 7},
    "junk",
    {templateId: "stool", count: 2},
  ]);
  assert.equal(out.failures.length, 5);
  for (const f of out.failures) assert.equal(typeof f.reason, "string");
  assert.equal(out.placements.length, 2, "the one good item still places");
  assert.ok(out.placements.every(p => p.templateId === "stool"));
});

test("more than twelve items fail the extras", () => {
  const s = world();
  const items = [];
  for (let i = 0; i < 13; i++) items.push({templateId: "stool", count: 1});
  const out = D.furnish(s, R(s, "home"), items);
  assert.equal(out.failures.length, 1);
  assert.equal(out.failures[0].reason, "too many items (at most 12)");
  assert.equal(out.placements.length, 12);
});
