"use strict";
// The Water toggle of the region inspector, as pure decisions in liquids.js: ticking writes the
// scenario's own water name (shallow at 3 cells short side or less, deep above that, the built-in
// pair without a list of its own) plus an organic shape from 5 x 5 when the region had none;
// unticking clears the surface and only a shape the toggle itself set — a shape set by hand
// survives. isWater says what the checkbox is checked on.
//   node --test test/water-toggle.test.js      (from tools/scenario-editor)
const test = require("node:test");
const assert = require("node:assert/strict");
const L = require("../liquids.js");

const media = (name, walk) => ({name, walk, color: "#4f7a6e", flows: true});
const scn = (regions, unbounded) => ({name: "T", gridSize: [30, 20], regions, ...(unbounded === undefined ? {} : {unbounded})});
const region = (size, extra) => ({id: "region_pond", position: [0, 0], size, ...extra});

test("waterFor: shallow at a short side of 3, deep from 4 up", () => {
  assert.equal(L.waterFor(region([3, 9]), scn([])).surface, "shallow water");
  assert.equal(L.waterFor(region([9, 3]), scn([])).surface, "shallow water");
  assert.equal(L.waterFor(region([4, 4]), scn([])).surface, "deep water");
  assert.equal(L.waterFor(region([12, 8]), scn([])).surface, "deep water");
});

test("waterFor: shape organic from 5 x 5 when the region has none, never below or over a shape", () => {
  assert.equal(L.waterFor(region([5, 5]), scn([])).shape, "organic");
  assert.equal(L.waterFor(region([6, 9]), scn([])).shape, "organic");
  assert.equal(L.waterFor(region([4, 6]), scn([])).shape, undefined, "too small for a blob");
  assert.equal(L.waterFor(region([3, 9]), scn([])).shape, undefined);
  assert.equal(L.waterFor(region([6, 6], {shape: "organic"}), scn([])).shape, undefined, "already shaped");
  assert.equal(L.waterFor(region([6, 6], {shape: "round"}), scn([])).shape, "organic",
    "the game reads no such shape: the region is shapeless to it");
});

test("waterFor and isWater use the scenario's own water media when it has them", () => {
  const own = scn([region([6, 6])],
    {seed: 1, profile: {media: [media("murky water", "no"), media("wading water", "slow"),
                                media("lava", "no"), media("dry flats", "yes")], lowEdges: []}});
  const w = L.waterFor(region([6, 6]), own);
  assert.equal(w.surface, "murky water");                        // its deep water, not the built-in name
  assert.equal(L.waterFor(region([3, 9]), own).surface, "wading water");
  assert.equal(L.isWater("murky water", own), true);
  assert.equal(L.isWater("wading water", own), true);
  assert.equal(L.isWater("deep water", own), false, "the built-in name is not in its list");
  assert.equal(L.isWater("lava", own), false, "its name carries no water");
  assert.equal(L.isWater("dry flats", own), false);
});

test("isWater against the built-in pair and against junk", () => {
  const defaults = scn([]);
  assert.equal(L.isWater("deep water", defaults), true);
  assert.equal(L.isWater("  SHALLOW water ", defaults), true);
  assert.equal(L.isWater("shallow water", scn([region([6, 6])])), true, "checked without regions too");
  assert.equal(L.isWater("lava", defaults), false);
  assert.equal(L.isWater("", defaults), false);
  assert.equal(L.isWater(undefined, defaults), false);
  assert.equal(L.isWater("deep water", scn([], {seed: 1, profile: {lowEdges: []}})), false,
    "a broken list has no water: nothing is checked");
});

test("waterOff: the surface always goes, a shape only the toggle set", () => {
  const shaped = region([6, 6], {surface: "deep water", shape: "organic"});
  const off = L.waterOff(shaped, true);
  assert.equal(off.surface, undefined);
  assert.ok("shape" in off, "the toggle set this shape: it goes with the water");
  assert.ok(!("shape" in L.waterOff(shaped, false)), "a hand-set shape survives the untick");
  assert.ok(!("shape" in L.waterOff(region([6, 6], {surface: "deep water"}), true)),
    "nothing was set: nothing to clear");
  assert.ok(!("shape" in L.waterOff(region([6, 6], {surface: "deep water", shape: "round"}), true)),
    "the shape moved on since the tick: leave it");
});

test("a full tick and untick through a recording set(), one shape cycle", () => {
  // the wiring the inspector does, driven only by the pure decisions
  const r = region([7, 6]);
  const marked = new Set(), ops = [];
  const set = (o, k, v) => { ops.push([k, v]); if (v === undefined) delete o[k]; else o[k] = v; };
  const on = L.waterFor(r, scn([]));
  set(r, "surface", on.surface);
  if (on.shape !== undefined) { set(r, "shape", on.shape); marked.add(r.id); }
  assert.deepEqual(ops, [["surface", "deep water"], ["shape", "organic"]]);
  const off = L.waterOff(r, marked.has(r.id));
  set(r, "surface", off.surface);
  if ("shape" in off) set(r, "shape", undefined);
  assert.deepEqual(r, {id: "region_pond", position: [0, 0], size: [7, 6]},
    "back to the bare region: the toggle's own shape went with it");
});
