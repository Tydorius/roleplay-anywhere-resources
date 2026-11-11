"use strict";
// Liquids and natural shapes as Anywhere RPG 1.0 reads them: the blob mask matches the golden fixture from
// the game's own code, surfaces resolve against unbounded.profile.media (or the built-in waters) with the
// game's appends and 8-entry limit, and rivers, pools and blobs give the right cells.
//   node --test test/liquids.test.js      (from tools/scenario-editor)
const test = require("node:test");
const assert = require("node:assert/strict");
const L = require("../liquids.js");
const FIXTURE = require("./organic-blobs-1.0.json");

const media = (...names) => names.map(name => ({name, walk: "yes", color: "#4f7a6e"}));
const scn = (regions, unbounded) => ({name: "T", gridSize: [30, 20], regions, ...(unbounded === undefined ? {} : {unbounded})});

test("blobMask matches every case of the 1.0 golden fixture", () => {
  for (const c of FIXTURE.cases) {
    const m = L.blobMask(c.id, c.w, c.h);
    assert.equal(m.length, c.w * c.h);
    for (let y = 0; y < c.h; y++)
      assert.equal(Array.from(m.slice(y * c.w, y * c.w + c.w)).join(""), c.rows[y], `${c.id} ${c.w}x${c.h} row ${y}`);
  }
});

test("normShape and normSurface as the import reads them", () => {
  assert.equal(L.normShape("organic"), "organic");
  assert.equal(L.normShape(" Natural "), "organic");           // the world generator's word, same thing
  assert.equal(L.normShape("ORGANIC"), "organic");
  assert.equal(L.normShape("blob"), undefined);
  assert.equal(L.normShape(5), undefined);
  assert.equal(L.normSurface("  Creek "), "creek");
  assert.equal(L.normSurface("Deep Water"), "deep water");
  assert.equal(L.normSurface("x".repeat(45)).length, 40);      // cut to 40 characters
  assert.equal(L.normSurface("   "), undefined);
  assert.equal(L.normSurface(7), undefined);
});

test("isOrganic: shape organic (or natural), no wall, no pocket, at least 5 x 5", () => {
  const r = (shape, size, extra) => ({id: "region_pond", position: [0, 0], size, shape, ...extra});
  assert.equal(L.isOrganic(r("organic", [5, 5])), true);
  assert.equal(L.isOrganic(r("natural", [6, 9])), true);
  assert.equal(L.isOrganic(r(" ORGANIC ", [5, 40])), true);
  assert.equal(L.isOrganic(r("organic", [4, 9])), false);      // too small
  assert.equal(L.isOrganic(r("organic", [5, 5], {wall: "wood"})), false);
  assert.equal(L.isOrganic(r("organic", [5, 5], {pocket: {anchor: "a", level: 1}})), false);
  assert.equal(L.isOrganic(r("round", [9, 9])), false);
});

test("isRiver at its boundaries", () => {
  const river = size => L.isRiver({size});
  assert.equal(river([3, 9]), true);      // exactly 3 x the width
  assert.equal(river([9, 3]), true);
  assert.equal(river([3, 8]), false);     // one cell short
  assert.equal(river([13, 40]), false);   // too wide to be a river, however long
  assert.equal(river([12, 36]), true);    // 12 wide is still a river
  assert.equal(river([4, 11]), false);
  assert.equal(river([1, 3]), true);
  assert.equal(river([6, 6]), false);
});

test("cellRuns: one run for a rectangle, the blob's cells when organic", () => {
  assert.deepEqual(L.cellRuns({position: [2, 3], size: [4, 2]}), [{x: 2, y: 3, w: 4, h: 2}]);
  const pond = {id: "r_lake", position: [5, 7], size: [12, 8], shape: "organic"};
  const runs = L.cellRuns(pond);
  const mask = L.blobMask("r_lake", 12, 8);
  let cells = 0;
  for (const r of runs) {
    assert.equal(r.h, 1);
    cells += r.w;
  }
  // the same cell count as the mask, and each run sits on a stretch of set cells in its row
  assert.equal(cells, Array.from(mask).reduce((n, v) => n + v, 0));
  for (const r of runs) {
    const y = r.y - 7;
    assert.ok(Array.from(mask.slice(y * 12 + r.x - 5, y * 12 + r.x - 5 + r.w)).every(v => v === 1), `run ${JSON.stringify(r)}`);
  }
});

test("mediaList: the built-in waters without unbounded, the scenario's list with it, null when broken", () => {
  assert.deepEqual(L.mediaList({}), {list: L.DEFAULT_MEDIA, defaults: true});
  const own = {seed: 1, profile: {media: media("creek"), lowEdges: []}};
  assert.deepEqual(L.mediaList(scn([], own)), {list: own.profile.media, defaults: false});
  assert.deepEqual(L.mediaList(scn([], {seed: 1})), {list: null, defaults: false});
  assert.deepEqual(L.mediaList(scn([], {profile: {media: "creek"}})), {list: null, defaults: false});
});

test("resolveAll: an exact name wins, walled regions and floors are skipped", () => {
  const deep = {name: "deep water", walk: "no", color: "#24506e", flows: true};
  const w = scn([
    {id: "a", position: [0, 0], size: [6, 6], surface: "deep water"},
    {id: "b", position: [0, 0], size: [6, 6], surface: "deep water", wall: "wood"},
    {id: "c", position: [54, 0], size: [6, 6], surface: "deep water", pocket: {anchor: "a", level: 1}},
    {id: "d", position: [0, 0], size: [6, 6]},                              // no surface
  ], {seed: 1, profile: {media: [deep]}});
  const {media: list, byRegion} = L.resolveAll(w);
  assert.equal(list.length, 1);
  assert.deepEqual([...byRegion.keys()], ["a"]);
  assert.deepEqual(byRegion.get("a"), {medium: deep, kind: "pool", added: false});
});

test("resolveAll: a substring match prefers slow for a narrow stream, no for a wide one", () => {
  const shallow = {name: "shallow water", walk: "slow", color: "#3f7f90", flows: true};
  const deep = {name: "deep water", walk: "no", color: "#24506e", flows: true};
  const cases = [[3, 9, shallow], [3, 8, shallow], [5, 5, deep], [4, 40, deep]];
  for (const [w, h, want] of cases) {
    const r = L.resolveAll(scn([{id: "s", position: [0, 0], size: [w, h], surface: "water"}],
      {seed: 1, profile: {media: [shallow, deep]}}));
    assert.equal(r.byRegion.get("s").medium, want, `${w}x${h}`);
    assert.deepEqual(r.media, [shallow, deep]);   // nothing appended
  }
});

test("resolveAll: an unknown surface is appended, and later regions find it by name", () => {
  const w = scn([
    {id: "a", position: [0, 0], size: [6, 6], surface: "ink"},
    {id: "b", position: [0, 0], size: [6, 6], surface: "ink"},
  ], {seed: 1, profile: {media: media("creek")}});
  const {media: list, byRegion} = L.resolveAll(w);
  assert.deepEqual(list.map(m => m.name), ["creek", "ink"]);
  assert.deepEqual(list[1], {name: "ink", walk: "no", color: L.NEW_COLOR, flows: true});
  assert.equal(byRegion.get("a").added, true);
  assert.deepEqual(byRegion.get("b"), {medium: list[1], kind: "pool", added: false});
});

test("resolveAll: with the list at 8 entries the surface is ignored", () => {
  const w = scn([{id: "a", position: [0, 0], size: [6, 6], surface: "ink"}],
    {seed: 1, profile: {media: media("m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8")}});
  const {media: list, byRegion} = L.resolveAll(w);
  assert.equal(list.length, L.MAX_MEDIA);
  assert.equal(byRegion.get("a"), null);
});

test("resolveAll: a scenario without unbounded gets the built-in waters", () => {
  const w = scn([{id: "a", position: [0, 0], size: [6, 6], surface: "Shallow Water"}]);   // trimmed and lowercased
  const {media: list, byRegion} = L.resolveAll(w);
  assert.equal(list.length, 2);
  assert.equal(byRegion.get("a").medium, L.DEFAULT_MEDIA[1]);
  assert.equal(byRegion.get("a").kind, "pool");
});

test("resolveAll: a broken media list resolves nothing", () => {
  const {media, byRegion} = L.resolveAll(scn([{id: "a", position: [0, 0], size: [6, 6], surface: "ink"}], {seed: 1}));
  assert.equal(media, null);
  assert.equal(byRegion.get("a"), null);
});

test("liquidKind: molten for glow, deep for walk no, shallow otherwise, flat without flows or glow", () => {
  assert.equal(L.liquidKind({walk: "no", flows: true}), "deep");
  assert.equal(L.liquidKind({walk: "slow", flows: true}), "shallow");
  assert.equal(L.liquidKind({walk: "slow", glow: true}), "molten");
  assert.equal(L.liquidKind({walk: "no", glow: true, flows: true}), "molten");
  assert.equal(L.liquidKind({walk: "no"}), null);                 // cliff rock: flat colour, no shader
  assert.equal(L.liquidKind({walk: "no", flows: 1}), "deep");     // a truthy flows still animates
});

test("newMedium: water, water 2, water 3...", () => {
  assert.deepEqual(L.newMedium([]), {name: "water", walk: "slow", color: "#3f7f90", flows: true});
  assert.equal(L.newMedium(["water"]).name, "water 2");
  assert.equal(L.newMedium(["water", "water 2"]).name, "water 3");
  assert.equal(L.newMedium(["water 2"]).name, "water");
});
