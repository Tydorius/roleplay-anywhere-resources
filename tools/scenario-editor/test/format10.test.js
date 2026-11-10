"use strict";
// Anywhere RPG 1.0 data through the editor's edits: floors (pocket regions) beside the map, portals, sided
// openings, door objects, npcTemplates with homes, keys and the open world stay intact, and nothing on a floor is
// pulled onto the map.   node --test test/      (from tools/scenario-editor)
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const M = require("../mapops.js");
const Refs = require("../refs.js");
const Minimap = require("../minimap.js");

const set = (o, k, v) => { if (v === undefined) delete o[k]; else o[k] = v; };

// A 30 × 20 map with a house (a sided door and a gate kind) and a loft floor 24 cells east of the map,
// joined by portal stairs; a sheep template homed in the yard; a key to the house; an open world.
function world() {
  return {
    name: "T", gridSize: [30, 20], playerId: "pc",
    unbounded: {seed: 7, profile: {media: [{name: "creek", walk: "slow", color: "#4f7a6e"}], lowEdges: []}, areas: [{record: {id: "0,-1"}}]},
    regions: [
      {id: "yard", name: "Yard", position: [0, 0], size: [30, 20], openings: []},
      {id: "house", name: "House", wall: "wood", position: [4, 4], size: [6, 6], openings: [[6, 4, "s"]], door: "gate", doorColor: "#8a5a2b", takingIsTheft: true},
      {id: "pond", name: "Pond", position: [20, 4], size: [6, 6], openings: [], shape: "organic", surface: "creek"},
      {id: "loft", name: "Loft", wall: "wood", position: [54, 0], size: [8, 6], openings: [], pocket: {anchor: "house", level: 1}},
    ],
    objectTemplates: [{id: "otpl_stair", name: "Stair", size: [1, 1], walkability: 1}, {id: "otpl_gate", name: "Gate", size: [1, 0], walkability: 1, door: "gate"}],
    itemTemplates: [{id: "itpl_key", name: "House key", type: "misc", quality: "common", opens: "house"}],
    npcTemplates: [{id: "ntpl_sheep", name: "Sheep", animationId: "sheep", stance: "skittish", homes: [{regionId: "yard", count: 3}, {regionId: "house", count: 1}]}],
    entities: [
      {id: "pc", type: "player", name: "Pat", pos: [2, 2], size: [1, 1], inventory: [], statusEffects: []},
      {id: "up", type: "object", name: "Stair up", templateId: "otpl_stair", pos: [7, 7], size: [1, 1], portal: {to: "down"}, inventory: [], statusEffects: []},
      {id: "down", type: "object", name: "Stair down", templateId: "otpl_stair", pos: [56, 2], size: [1, 1], portal: {to: "up"}, inventory: [], statusEffects: []},
      {id: "gate", type: "object", name: "Gate 1", templateId: "otpl_gate", pos: [6, 4], size: [1, 0], inventory: [], statusEffects: []},
      {id: "maid", type: "npc", name: "Maid", pos: [57, 3], size: [1, 1], npcHome: "house", inventory: [], statusEffects: []},
    ],
  };
}
const by = (w, id) => w.regions.find(r => r.id === id) || w.entities.find(e => e.id === id);

test("planes: the map and each floor; extent reaches the floors", () => {
  const w = world();
  assert.deepEqual(M.planes(w), [[0, 0, 29, 19], [54, 0, 61, 5]]);
  assert.deepEqual(M.extent(w), [62, 20]);
  assert.deepEqual(Minimap.extent(w), [62, 20]);
  assert.deepEqual(M.planeAt(w, 55, 1), [54, 0, 61, 5]);
  assert.equal(M.planeAt(w, 40, 1), null);
});

test("moving a house keeps its door's side; things on a floor stay on the floor", () => {
  const w = world();
  assert.deepEqual(M.moveRegion(w, by(w, "house"), 2, 1, set), {dx: 2, dy: 1});
  assert.deepEqual(by(w, "house").openings, [[8, 5, "s"]]);
  assert.deepEqual(by(w, "gate").pos, [8, 5]);                       // the zero-wide door object moved with it
  M.moveEntities(w, [by(w, "maid")], 50, 50, set);
  assert.deepEqual(by(w, "maid").pos, [61, 5]);                      // stopped at the loft's corner, not the map's
  const rot = M.placeObject(w, w.objectTemplates[0], 60, 5, set);
  assert.deepEqual(rot.pos, [60, 5]);
});

test("a floor moves anywhere clear of the map and other floors", () => {
  const w = world();
  assert.match(M.moveRegion(w, by(w, "loft"), -40, 0, set).error, /would cover the map/);
  assert.deepEqual(M.moveRegion(w, by(w, "loft"), 4, 3, set), {dx: 4, dy: 3});
  assert.deepEqual(by(w, "down").pos, [60, 5]);
  assert.match(M.resizeRegion(w, by(w, "loft"), "w", 20, set).error, /would cover the map/);
});

test("a room on the floor can't be resized off it", () => {
  const w = world();
  w.regions.push({id: "closet", name: "Closet", wall: "wood", position: [58, 1], size: [3, 3], openings: [[58, 2]]});
  assert.match(M.resizeRegion(w, by(w, "closet"), "e", 70, set).error, /would leave its floor/);
  assert.deepEqual(M.resizeRegion(w, by(w, "closet"), "e", 61, set).changed.map(r => r.id), ["closet"]);
});

test("growing the map pushes the floors east, keeping their gap; usedBounds ignores them", () => {
  const w = world();
  assert.deepEqual(M.usedBounds(w), [0, 0, 29, 19]);
  M.resizeMap(w, 50, 20, {h: "w", v: "s"}, set);
  assert.deepEqual(by(w, "loft").position, [74, 0]);
  assert.deepEqual(by(w, "down").pos, [76, 2]);
  assert.deepEqual(by(w, "maid").pos, [77, 3]);
  assert.deepEqual(by(w, "house").openings, [[6, 4, "s"]]);
});

test("toggling a sided door removes every entry for that cell; resizing keeps a side that still fits", () => {
  const w = world(), h = by(w, "house");
  h.openings.push([4, 4, "w"]);
  M.toggleDoor(w, h, [4, 4], set);
  assert.deepEqual(h.openings, [[6, 4, "s"]]);
  M.resizeRegion(w, h, "e", 10, set, false);
  assert.deepEqual(h.openings, [[6, 4, "s"]]);
});

test("pasting a copy drops portal links, and a floor can't be pasted", () => {
  const w = world();
  const clip = M.copyRegion(w, by(w, "house"));
  M.pasteRegion(w, clip, 12, 12, set);
  const copy = w.entities.find(e => e.name === "Stair up 2");
  assert.ok(copy && !("portal" in copy));
  assert.match(M.pasteRegion(w, M.copyRegion(w, by(w, "loft")), 10, 10, set).error, /not the floor itself/);
});

test("references: homes, npcHome, floors, keys and portals", () => {
  const w = world();
  const kinds = Refs.findRefs(w, "house").map(r => r.kind).sort();
  assert.deepEqual(kinds, ["floorOf", "hostileHome", "key", "npcHome"]);
  assert.deepEqual(Refs.findRefs(w, "down").map(r => r.ownerId), ["up"]);
  assert.deepEqual(Refs.findRefs(w, "ntpl_sheep"), []);
});

test("deleting a house with no replacement unlinks what pointed at it and keeps the sheep's other home", () => {
  const w = world();
  Refs.forceDelete(w, ["house"], {}, set);
  assert.deepEqual(w.npcTemplates[0].homes, [{regionId: "yard", count: 3}]);
  assert.ok(!("npcHome" in by(w, "maid")));
  assert.deepEqual(by(w, "loft").pocket, {level: 1});
  assert.ok(!("opens" in w.itemTemplates[0]));
});

test("deleting into a replacement moves homes, floors and keys there", () => {
  const w = world();
  w.regions.push({id: "barn", name: "Barn", wall: "wood", position: [12, 12], size: [5, 5], openings: [[12, 13]]});
  Refs.forceDelete(w, ["house"], {replacementRegionId: "barn"}, set);
  assert.deepEqual(w.npcTemplates[0].homes, [{regionId: "yard", count: 3}, {regionId: "barn", count: 1}]);
  assert.equal(by(w, "maid").npcHome, "barn");
  assert.equal(by(w, "loft").pocket.anchor, "barn");
  assert.equal(w.itemTemplates[0].opens, "barn");
});

test("deleting one end of a portal unlinks the other; npcTemplates can be renamed and deleted", () => {
  const w = world();
  Refs.forceDelete(w, ["down"], {}, set);
  assert.ok(!("portal" in by(w, "up")));
  assert.deepEqual(Refs.renameEverywhere(w, "ntpl_sheep", "Ewe", set), {count: 0});
  assert.equal(w.npcTemplates[0].name, "Ewe");
  Refs.forceDelete(w, ["ntpl_sheep"], {}, set);
  assert.deepEqual(w.npcTemplates, []);
  assert.ok(!("hostileNpcTemplates" in w));
});

test("a 1.0 preset keeps every key through edits and a JSON round trip", (t) => {
  const file = String.raw`E:\Misc Projects\Anywhere RPG builds\1.0-build26557354\resources\presets\uc-berkeley\scenario.json`;
  if (!fs.existsSync(file)) return t.skip("the 1.0 build snapshot isn't on this machine");
  const w = JSON.parse(fs.readFileSync(file, "utf8"));
  const before = JSON.parse(JSON.stringify(w));
  const r = w.regions.find(g => g.wall && g.openings.length);
  const moved = M.moveRegion(w, r, 1, 0, set);                       // there and back again changes nothing
  if (!moved.error && moved.dx) M.moveRegion(w, r, -moved.dx, 0, set);
  Refs.renameEverywhere(w, r.id, r.name, set);
  assert.deepEqual(JSON.parse(JSON.stringify(w)), before);
  assert.deepEqual(w.unbounded, before.unbounded);
});
