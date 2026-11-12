"use strict";
// node --test test/      (from tools/scenario-editor)
const test = require("node:test");
const assert = require("node:assert/strict");
const M = require("../mapops.js");

// A 30 × 30 map with the mapops fixture's house and field, plus a floor east of it (the game lays
// floors out 24 cells past the map) holding a room and a bed, and a portal end on each level.
function world() {
  return {
    gridSize: [30, 30], defaultTile: {ground: "grass", groundTexture: "grass"},
    regions: [
      {id: "house", name: "House", wall: "wood", position: [2, 2], size: [10, 6], openings: [[6, 2]]},
      {id: "field", name: "Field", position: [15, 15], size: [10, 10], openings: []},
      {id: "up", name: "House upstairs", pocket: {anchor: "house", level: 1}, position: [54, 0], size: [10, 6], openings: []},
      {id: "attic", name: "Attic", wall: "wood", position: [55, 1], size: [4, 3], openings: []},
    ],
    entities: [
      {id: "table", type: "object", name: "Table 1", pos: [3, 3], size: [2, 1], templateId: "t"},
      {id: "bed", type: "object", name: "Bed 1", pos: [56, 2], size: [2, 1], templateId: "t"},
      {id: "cow", type: "npc", name: "Cow", pos: [20, 20], size: [1, 1]},
    ],
  };
}
const R = (s, id) => s.regions.find(r => r.id === id);
const E = (s, id) => s.entities.find(e => e.id === id);

test("levelRect: the map, a floor, and null for the overview or an unknown id", () => {
  const s = world();
  assert.deepEqual(M.levelRect(s, ""), [0, 0, 29, 29]);
  assert.deepEqual(M.levelRect(s, "up"), [54, 0, 63, 5]);
  assert.equal(M.levelRect(s, "*"), null);
  assert.equal(M.levelRect(s, "house"), null, "only a floor's own id names a level");
  assert.equal(M.levelRect(s, "nope"), null);
});

test("levelOf: the map, a floor, a room inside it, an object inside that", () => {
  const s = world();
  assert.equal(M.levelOf(s, R(s, "house")), "");
  assert.equal(M.levelOf(s, R(s, "field")), "");
  assert.equal(M.levelOf(s, E(s, "table")), "");
  assert.equal(M.levelOf(s, E(s, "cow")), "");
  assert.equal(M.levelOf(s, R(s, "up")), "up", "a floor region is on its own level");
  assert.equal(M.levelOf(s, R(s, "attic")), "up", "a room region inside the floor");
  assert.equal(M.levelOf(s, E(s, "bed")), "up", "an object inside the floor");
});

test("onLevel: everything on the overview, only its own things on a level", () => {
  const s = world();
  assert.equal(M.onLevel(s, "*", R(s, "house")), true);
  assert.equal(M.onLevel(s, "*", R(s, "attic")), true);
  assert.equal(M.onLevel(s, "", R(s, "house")), true);
  assert.equal(M.onLevel(s, "", R(s, "up")), false);
  assert.equal(M.onLevel(s, "up", E(s, "bed")), true);
  assert.equal(M.onLevel(s, "up", E(s, "table")), false);
  assert.equal(M.onLevel(s, "up", R(s, "attic")), true);
  assert.equal(M.onLevel(s, "up", R(s, "field")), false);
});

test("levelExtent: the plane to fit, or everything from 0,0 for the overview", () => {
  const s = world();
  assert.deepEqual(M.levelExtent(s, ""), [0, 0, 29, 29]);
  assert.deepEqual(M.levelExtent(s, "up"), [54, 0, 63, 5]);
  assert.deepEqual(M.levelExtent(s, "*"), [0, 0, 63, 29]);
  assert.deepEqual(M.levelExtent(s, "nope"), [0, 0, 29, 29], "an unknown id falls back to the map");
});
