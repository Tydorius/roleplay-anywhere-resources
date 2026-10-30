"use strict";
// node --test test/      (from tools/scenario-editor)
const test = require("node:test");
const assert = require("node:assert/strict");
const M = require("../mapops.js");
const Minimap = require("../minimap.js");

const set = (o, k, v) => { if (v === undefined) delete o[k]; else o[k] = v; };
const snap = o => JSON.stringify(o);

// A 30 × 30 map: a house split into two walled rooms with a door between them and one outside,
// a table in the kitchen, a person in the hall, and a field off to the side.
function world() {
  return {
    gridSize: [30, 30], defaultTile: {ground: "grass", groundTexture: "grass", ambience: {day: "nature_outdoors"}},
    regions: [
      {id: "house", name: "House", wall: "wood", ground: "wood", groundTexture: "floorboards", position: [2, 2], size: [10, 6], openings: [[6, 2]]},
      {id: "kitchen", name: "Kitchen", wall: "wood", position: [2, 2], size: [5, 6], openings: [[6, 2], [6, 4]]},
      {id: "hall", name: "Hall", wall: "wood", position: [7, 2], size: [5, 6], openings: [[7, 4]]},
      {id: "field", name: "Field", position: [15, 15], size: [10, 10], openings: []},
    ],
    entities: [
      {id: "table", type: "object", name: "Table 1", pos: [3, 3], size: [2, 1], templateId: "t", inventory: [], statusEffects: []},
      {id: "pc", type: "player", name: "Pat", pos: [9, 5], size: [1, 1], inventory: [], statusEffects: []},
      {id: "cow", type: "npc", name: "Cow", pos: [20, 20], size: [1, 1], inventory: [], statusEffects: []},
    ],
  };
}
const R = (s, id) => s.regions.find(r => r.id === id);
const E = (s, id) => s.entities.find(e => e.id === id);

test("moveRegion moves the region with its rooms, doors and contents", () => {
  const s = world(), res = M.moveRegion(s, R(s, "house"), 3, 1, set);
  assert.deepEqual(res, {dx: 3, dy: 1});
  assert.deepEqual(R(s, "house").position, [5, 3]);
  assert.deepEqual(R(s, "kitchen").position, [5, 3]);
  assert.deepEqual(R(s, "hall").position, [10, 3]);
  assert.deepEqual(R(s, "kitchen").openings, [[9, 3], [9, 5]]);
  assert.deepEqual(E(s, "table").pos, [6, 4]);
  assert.deepEqual(E(s, "pc").pos, [12, 6]);
  assert.deepEqual(E(s, "cow").pos, [20, 20], "things outside stay put");
});

test("moveRegion is shortened at the map edge", () => {
  const s = world();
  assert.deepEqual(M.moveRegion(s, R(s, "house"), -5, 0, set), {dx: -2, dy: 0});
  assert.deepEqual(R(s, "house").position, [0, 2]);
});

test("moveRegion refuses a partial overlap and changes nothing", () => {
  const s = world(), before = snap(s);
  const res = M.moveRegion(s, R(s, "field"), -10, -10, set);   // field would cut through the house
  assert.ok(res.error);
  assert.equal(snap(s), before);
});

test("moveRegion may move a region wholly inside another", () => {
  const s = world();
  s.regions.push({id: "shed", name: "Shed", position: [0, 20], size: [3, 3], openings: []});
  assert.deepEqual(M.moveRegion(s, R(s, "shed"), 16, -3, set), {dx: 16, dy: -3});
  assert.equal(M.parentOf(s, R(s, "shed")).id, "field");
});

test("moveEntities moves a group by one shared, shortened amount", () => {
  const s = world(), ents = [E(s, "table"), E(s, "cow")];
  assert.deepEqual(M.moveEntities(s, ents, 0, 20, set), {dx: 0, dy: 9});
  assert.deepEqual(E(s, "table").pos, [3, 12]);
  assert.deepEqual(E(s, "cow").pos, [20, 29]);
});

test("rotateObject turns about the centre cell and swaps the footprint", () => {
  const s = world(), t = E(s, "table");                        // pos [3,3] size [2,1]: centre cell [3,3]
  M.rotateObject(s, t, 1, set);
  assert.deepEqual([t.pos, t.size, t.rot], [[3, 3], [1, 2], 1]);
  const big = {id: "b", type: "object", pos: [10, 10], size: [3, 1]}; // centre [11,10]
  s.entities.push(big);
  M.rotateObject(s, big, 1, set);
  assert.deepEqual([big.pos, big.size], [[11, 9], [1, 3]]);
});

test("rotateObject: four turns come back, and rot is dropped at 0", () => {
  const s = world(), t = E(s, "table"), start = snap(t);
  for (let i = 0; i < 4; i++) M.rotateObject(s, t, 1, set);
  assert.equal(snap(t), start);
  assert.ok(!("rot" in t));
  M.rotateObject(s, t, -1, set);
  assert.equal(t.rot, 3);
});

test("rotateObject keeps the footprint on the map and ignores people", () => {
  const s = world(), o = {id: "o", type: "object", pos: [29, 0], size: [1, 3]};
  s.entities.push(o);
  M.rotateObject(s, o, 1, set);
  assert.deepEqual([o.pos, o.size], [[27, 1], [3, 1]]);
  assert.equal(M.rotateObject(s, E(s, "cow"), 1, set), false);
});

test("resizeRegion moves the shared wall: the neighbouring room follows", () => {
  const s = world();
  const res = M.resizeRegion(s, R(s, "kitchen"), "e", 7, set);
  assert.ok(!res.error);
  assert.deepEqual([R(s, "kitchen").size, R(s, "hall").position, R(s, "hall").size], [[6, 6], [8, 2], [4, 6]]);
  assert.deepEqual(R(s, "house").size, [10, 6], "the building's outline doesn't change");
});

test("resizeRegion: the doors between them move with the wall", () => {
  const s = world();
  M.resizeRegion(s, R(s, "kitchen"), "e", 7, set);
  assert.ok(R(s, "kitchen").openings.some(c => c[0] === 7 && c[1] === 4));
  assert.ok(R(s, "hall").openings.some(c => c[0] === 8 && c[1] === 4));
});

test("resizeRegion on an outer wall moves the building's wall too", () => {
  const s = world();
  M.resizeRegion(s, R(s, "kitchen"), "n", 9, set);
  assert.deepEqual(R(s, "kitchen").size, [5, 8]);
  assert.deepEqual(R(s, "house").size, [10, 8]);
});

test("resizeRegion of a building takes its rooms on that wall along", () => {
  const s = world();
  assert.ok(!M.resizeRegion(s, R(s, "house"), "n", 5, set).error);
  assert.deepEqual([R(s, "house").size, R(s, "kitchen").size, R(s, "hall").size], [[10, 4], [5, 4], [5, 4]]);
});

test("resizeRegion with follow off moves only its own edge", () => {
  const s = world(), before = snap(s);
  const res = M.resizeRegion(s, R(s, "kitchen"), "e", 7, set, false);   // would cut into the hall
  assert.ok(res.error);
  assert.equal(snap(s), before);
  assert.ok(!M.resizeRegion(s, R(s, "kitchen"), "e", 5, set, false).error);
  assert.deepEqual([R(s, "kitchen").size, R(s, "hall").position], [[4, 6], [7, 2]]);
});

test("resizeRegion refuses too small and off the map", () => {
  const s = world(), before = snap(s);
  assert.ok(M.resizeRegion(s, R(s, "kitchen"), "e", 2, set).error, "walled: at least 2 wide");
  assert.ok(M.resizeRegion(s, R(s, "field"), "n", 30, set).error);
  assert.equal(snap(s), before);
  assert.ok(!M.resizeRegion(s, R(s, "field"), "e", 15, set).error, "open: 1 wide is fine");
});

test("resizeRegion moves doors left off the edge onto it, without duplicates", () => {
  const s = world();
  R(s, "field").wall = "stone";
  R(s, "field").openings = [[24, 18], [24, 20]];
  M.resizeRegion(s, R(s, "field"), "e", 22, set);
  assert.deepEqual(R(s, "field").openings, [[22, 18], [22, 20]]);
  R(s, "field").openings = [[17, 24], [18, 24]];
  M.resizeRegion(s, R(s, "field"), "w", 18, set);
  assert.deepEqual(R(s, "field").openings, [[18, 24]]);
});

test("edgeAt finds the nearest outline edge within the tolerance", () => {
  const r = {position: [2, 2], size: [3, 4]};                   // lines x=2, x=5, y=2, y=6
  assert.equal(M.edgeAt(r, 2.1, 4, .3), "w");
  assert.equal(M.edgeAt(r, 4.9, 4, .3), "e");
  assert.equal(M.edgeAt(r, 3.5, 6.2, .3), "n");
  assert.equal(M.edgeAt(r, 3.5, 1.8, .3), "s");
  assert.equal(M.edgeAt(r, 3.5, 4, .3), null);
  assert.equal(M.edgeAt(r, 9, 4, .3), null);
});

test("toggleDoor on an outer wall adds the door to the room and the building", () => {
  const s = world();
  const res = M.toggleDoor(s, R(s, "kitchen"), [2, 4], set);
  assert.equal(res.added, true);
  assert.ok(R(s, "kitchen").openings.some(c => c[0] === 2 && c[1] === 4));
  assert.ok(R(s, "house").openings.some(c => c[0] === 2 && c[1] === 4));
});

test("toggleDoor between rooms adds a facing pair, and toggling again removes it", () => {
  const s = world(), before = snap(s);
  M.toggleDoor(s, R(s, "kitchen"), [6, 6], set);
  assert.ok(R(s, "kitchen").openings.some(c => c[0] === 6 && c[1] === 6));
  assert.ok(R(s, "hall").openings.some(c => c[0] === 7 && c[1] === 6));
  const res = M.toggleDoor(s, R(s, "kitchen"), [6, 6], set);
  assert.equal(res.added, false);
  assert.equal(snap(s), before);
});

test("toggleDoor on a corner opens both outer sides", () => {
  const s = world();
  const res = M.toggleDoor(s, R(s, "kitchen"), [2, 7], set);    // north-west corner of kitchen and house
  assert.equal(res.added, true);
  assert.deepEqual(new Set(res.regions), new Set(["Kitchen", "House"]));
  assert.equal(M.doorSet(s, R(s, "kitchen"), [2, 7]).length, 2);
});

test("toggleDoor refuses open areas and cells off the edge", () => {
  const s = world(), before = snap(s);
  assert.ok(M.toggleDoor(s, R(s, "field"), [15, 15], set).error);
  assert.ok(M.toggleDoor(s, R(s, "kitchen"), [4, 4], set).error);
  assert.equal(snap(s), before);
});

test("createRegion: any two corners, ground from where it's drawn", () => {
  const s = world();
  const {region} = M.createRegion(s, [24, 24], [18, 20], {name: "Barn", wall: "wood"}, set);
  assert.deepEqual([region.position, region.size, region.openings], [[18, 20], [7, 5], []]);
  assert.match(region.id, /^rgn_/);
  assert.equal(s.regions.at(-1), region);
  const {region: pond} = M.createRegion(s, [16, 16], [17, 17], {name: "Pond"}, set);
  assert.equal(M.parentOf(s, pond).id, "field");
});

test("createRegion refuses bad names, overlaps, tiny walls and the map edge", () => {
  const s = world(), before = snap(s);
  assert.ok(M.createRegion(s, [20, 20], [22, 22], {name: "  "}, set).error);
  assert.ok(M.createRegion(s, [20, 20], [22, 22], {name: "Field"}, set).error);
  assert.ok(M.createRegion(s, [10, 10], [16, 16], {name: "Cross"}, set).error);
  assert.ok(M.createRegion(s, [20, 20], [20, 22], {name: "Thin", wall: "wood"}, set).error);
  assert.ok(M.createRegion(s, [28, 28], [30, 30], {name: "Out"}, set).error);
  assert.equal(snap(s), before);
});

test("placeObject copies the template, numbers the name and clamps to the map", () => {
  const s = world();
  s.entities.push({id: "c9", type: "object", name: "Cot 9", pos: [0, 0], size: [1, 2], templateId: "cot"});
  const eff = {desc: "blooming", type: "progressive", durationSecs: 60};
  const tpl = {id: "cot", name: "Cot", size: [1, 2], maxHp: 12, startingEffects: [eff]};
  const e = M.placeObject(s, tpl, 29, 29, set);
  assert.equal(e.name, "Cot 10");
  assert.deepEqual([e.pos, e.size, e.hp, e.maxHp, e.inventory, e.templateId], [[29, 28], [1, 2], 12, 12, [], "cot"]);
  assert.equal(e.statusEffects.length, 1);
  assert.deepEqual({...e.statusEffects[0], id: "x"}, {id: "x", def: eff, appliedAt: 28800, source: "template"});
  assert.notEqual(e.statusEffects[0].def, eff, "the effect is a copy");
});

test("placeNpc starts them in the region they stand in", () => {
  const s = world();
  assert.ok(M.placeNpc(s, {name: ""}, 20, 20, set).error);
  const {npc} = M.placeNpc(s, {name: "Mara", gender: "female"}, 16, 16, set);
  assert.deepEqual(npc.schedule, [{start: "00:00", end: "00:00", location: "Field", role: "leisure"}]);
  assert.deepEqual([npc.size, npc.inventory, npc.statusEffects, npc.animationId], [[1, 1], [], [], "casual-woman"]);
});

test("copyRegion and pasteRegion: new ids and names, objects but no people", () => {
  const s = world();
  const clip = M.copyRegion(s, R(s, "house"));
  const {region} = M.pasteRegion(s, clip, 2, 12, set);
  assert.equal(region.name, "House 2");
  const pasted = s.regions.filter(r => r.position[1] === 12);
  assert.equal(pasted.length, 3);
  assert.equal(new Set(s.regions.map(r => r.id)).size, s.regions.length, "ids are unique");
  assert.equal(new Set(s.regions.map(r => r.name)).size, s.regions.length, "names are unique");
  const kitchen2 = pasted.find(r => r.name.startsWith("Kitchen"));
  assert.deepEqual(kitchen2.openings, [[6, 12], [6, 14]]);
  const objs = s.entities.filter(e => e.pos[1] === 13);
  assert.deepEqual(objs.map(e => [e.name, e.pos]), [["Table 2", [3, 13]]]);
  assert.equal(s.entities.filter(e => e.type !== "object").length, 2, "nobody was copied");
});

test("pasteRegion refuses a partial overlap and changes nothing", () => {
  const s = world(), clip = M.copyRegion(s, R(s, "house")), before = snap(s);
  assert.ok(M.pasteRegion(s, clip, 20, 12, set).error);
  assert.equal(snap(s), before);
});

test("remove drops entities and regions by id", () => {
  const s = world();
  M.remove(s, ["table", "field"], set);
  assert.ok(!E(s, "table") && !R(s, "field"));
  assert.equal(s.entities.length, 2);
});

test("nextName counts past the highest number", () => {
  assert.equal(M.nextName("Cot", ["Cot 2", "Cot 9", "Cotton 40"]), "Cot 10");
  assert.equal(M.nextName("Hall", ["Hall"]), "Hall 2");
  assert.equal(M.nextName("Bed (big)", []), "Bed (big) 1");
});

test("resizeMap grows away from the anchor and moves everything with it", () => {
  const s = world();                                            // 30 × 30
  assert.deepEqual(M.resizeMap(s, 40, 36, {h: "e", v: "n"}, set), {dx: 10, dy: 6});
  assert.deepEqual(s.gridSize, [40, 36]);
  assert.deepEqual(R(s, "house").position, [12, 8]);
  assert.deepEqual(R(s, "kitchen").openings, [[16, 8], [16, 10]]);
  assert.deepEqual(E(s, "cow").pos, [30, 26]);
});

test("resizeMap: south-west anchor adds cells north and east and moves nothing", () => {
  const s = world(), before = snap(s.regions) + snap(s.entities);
  assert.deepEqual(M.resizeMap(s, 50, 45, {h: "w", v: "s"}, set), {dx: 0, dy: 0});
  assert.equal(snap(s.regions) + snap(s.entities), before);
  assert.deepEqual(s.gridSize, [50, 45]);
});

test("resizeMap: centre anchor splits the new cells, odd ones to the far side", () => {
  const s = world();
  assert.deepEqual(M.resizeMap(s, 35, 31, {h: "c", v: "c"}, set), {dx: 2, dy: 0});
  assert.deepEqual(M.anchorShift({gridSize: [30, 30]}, 20, 24, {h: "c", v: "c"}), {dx: -5, dy: -3});
});

test("resizeMap can shrink when everything still fits", () => {
  const s = world();                                            // things reach x 24, y 24
  assert.deepEqual(M.resizeMap(s, 26, 26, {h: "w", v: "s"}, set), {dx: 0, dy: 0});
  assert.deepEqual(s.gridSize, [26, 26]);
  const t = world();                                            // trimming 2 off the west and south
  assert.deepEqual(M.resizeMap(t, 28, 28, {h: "e", v: "n"}, set), {dx: -2, dy: -2});
  assert.deepEqual(R(t, "house").position, [0, 0]);
});

test("resizeMap refuses to cut anything off, names it, and changes nothing", () => {
  const s = world(), before = snap(s);
  const res = M.resizeMap(s, 20, 20, {h: "w", v: "s"}, set);
  assert.ok(res.error);
  assert.deepEqual(new Set(res.outside), new Set(["Field", "Cow"]));
  assert.equal(snap(s), before);
  assert.ok(M.resizeMap(s, 4, 30, {h: "w", v: "s"}, set).error, "too small");
});

test("usedBounds covers every region and entity", () => {
  assert.deepEqual(M.usedBounds(world()), [2, 2, 24, 24]);
});

// ---------------------------------------------------------------- minimap helpers
test("Minimap.fit centres the grid at the largest scale", () => {
  assert.deepEqual(Minimap.fit(100, 50, 200, 200, 0), {scale: 2, ox: 0, oy: 50});
  assert.deepEqual(Minimap.fit(50, 100, 200, 200, 0), {scale: 2, ox: 50, oy: 0});
  assert.equal(Minimap.fit(100, 50, 200, 200, 10).scale, 1.8);
});

test("Minimap.toCanvas and toWorld are inverses, with y flipped", () => {
  const t = Minimap.fit(100, 50, 200, 200, 4);
  assert.deepEqual(Minimap.toCanvas(t, 50, 0, 0), [t.ox, t.oy + 50 * t.scale]);
  assert.deepEqual(Minimap.toCanvas(t, 50, 100, 50), [t.ox + 100 * t.scale, t.oy]);
  for (const [x, y] of [[0, 0], [12.5, 40], [100, 50], [3, 7]]) {
    const [px, py] = Minimap.toCanvas(t, 50, x, y), [bx, by] = Minimap.toWorld(t, 50, px, py);
    assert.ok(Math.abs(bx - x) < 1e-9 && Math.abs(by - y) < 1e-9);
  }
});
