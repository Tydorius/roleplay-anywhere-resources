"use strict";
// node --test test/      (from tools/scenario-editor)
const test = require("node:test");
const assert = require("node:assert/strict");
const M = require("../mapops.js");
const W = require("../world10.js");

const set = (o, k, v) => { if (v === undefined) delete o[k]; else o[k] = v; };
const snap = o => JSON.stringify(o);

const R = (s, id) => s.regions.find(r => r.id === id);
const E = (s, id) => s.entities.find(e => e.id === id);

// A 24 × 24 map with a walled house (with ground of its own), an open field and a bare shed.
function floorWorld() {
  return {
    gridSize: [24, 24],
    regions: [
      {id: "house", name: "House", wall: "wood", ground: "plank", groundTexture: "planks", position: [4, 4], size: [6, 6], openings: []},
      {id: "field", name: "Field", position: [14, 4], size: [6, 6], openings: []},
      {id: "shed", name: "Shed", wall: "wood", position: [4, 12], size: [4, 4], openings: []},
    ],
    entities: [],
  };
}

// A 24 × 24 map with a 6 × 6 house at [4, 4] and one door out on its south wall.
function doorWorld() {
  return {
    gridSize: [24, 24],
    regions: [
      {id: "house", name: "House", wall: "wood", position: [4, 4], size: [6, 6], openings: [[6, 4]]},
    ],
    entities: [], objectTemplates: [], itemTemplates: [],
  };
}

// The same house split into two rooms: a 2 × 6 west room and a 4 × 4 east room, with the outer door
// at [6, 4] and a matching pair of openings on the shared wall at y = 7.
function splitWorld() {
  return {
    gridSize: [24, 24],
    regions: [
      {id: "house", name: "House", wall: "wood", position: [4, 4], size: [6, 6], openings: [[6, 4]]},
      {id: "west", name: "West room", wall: "wood", position: [4, 4], size: [2, 6], openings: [[5, 7]]},
      {id: "east", name: "East room", wall: "wood", position: [6, 6], size: [4, 4], openings: [[6, 7]]},
    ],
    entities: [], objectTemplates: [],
  };
}

// A 0.18-style scenario: hostileNpcTemplates with regionId and count, alongside one 1.0 template.
function legacyWorld() {
  return {
    gridSize: [10, 10],
    regions: [
      {id: "crypt", name: "Crypt", wall: "stone", position: [0, 0], size: [6, 6], openings: []},
      {id: "field", name: "Field", position: [0, 0], size: [10, 10], openings: []},
    ],
    entities: [
      {id: "z1", type: "npc", name: "Zombie 1", templateId: "h1", pos: [1, 1], size: [1, 1], inventory: [], statusEffects: []},
      {id: "z2", type: "npc", name: "Zombie 2", templateId: "h1", npcHome: "field", pos: [2, 1], size: [1, 1], inventory: [], statusEffects: []},
      {id: "d1", type: "npc", name: "Deer 1", templateId: "h2", pos: [8, 8], size: [1, 1], inventory: [], statusEffects: []},
      {id: "g1", type: "npc", name: "Ghost 1", templateId: "h3", pos: [1, 8], size: [1, 1], inventory: [], statusEffects: []},
    ],
    hostileNpcTemplates: [
      {id: "h1", name: "Zombie", animationId: "zombie", gender: "male", level: 2, money: 5, lootPoolIds: ["lp1"], regionId: "crypt", count: 3},
      {id: "h2", name: "Deer", animationId: "deer", gender: "female", attacksOnSight: false, regionId: "field"},
      {id: "h3", name: "Ghost", stance: "skittish"},
    ],
    npcTemplates: [{id: "n0", name: "Villager", stance: "neutral", homes: [{regionId: "field", count: 1}]}],
  };
}

// ---------------------------------------------------------------- floors
test("nextFloorSpot starts past the map and steps past each floor", () => {
  const s = floorWorld();
  assert.deepEqual(W.nextFloorSpot(s), [48, 0]);
  const {region: a} = W.addFloor(s, R(s, "house"), {name: "Attic", level: 1}, set);
  assert.deepEqual(a.position, [48, 0]);
  assert.deepEqual(W.nextFloorSpot(s), [78, 0]);
});

test("addFloor lays a floor east of the map, sized after the building", () => {
  const s = floorWorld();
  const {region} = W.addFloor(s, R(s, "house"), {name: "Attic", level: 1}, set);
  assert.match(region.id, /^rgn_/);
  assert.deepEqual(region, {id: region.id, name: "Attic", description: "", wall: "wood",
    ground: "plank", groundTexture: "planks", openings: [], position: [48, 0], size: [6, 6],
    ambience: {day: "quiet_indoor"}, pocket: {anchor: "house", level: 1}});
  assert.equal(s.regions.at(-1), region);
  assert.equal(M.isFloor(region), true);
  const {region: shed} = W.addFloor(s, R(s, "shed"), {name: "Shed loft", level: 1}, set);
  assert.deepEqual([shed.ground, shed.groundTexture], ["wood", "floorboards"], "defaults without a ground");
  assert.deepEqual(W.floorsOf(s, R(s, "shed")), [shed]);
});

test("floorsOf sorts by level and keeps to one building", () => {
  const s = floorWorld();
  W.addFloor(s, R(s, "house"), {name: "Attic", level: 1}, set);
  W.addFloor(s, R(s, "house"), {name: "Loft", level: 2, size: [8, 4]}, set);
  W.addFloor(s, R(s, "shed"), {name: "Shed loft", level: 1}, set);
  const {region: cellar} = W.addFloor(s, R(s, "house"), {name: "Cellar", level: -1}, set);
  assert.deepEqual(cellar.position, [138, 0], "past the shed loft's east edge at 114");
  assert.deepEqual(W.floorsOf(s, R(s, "house")).map(r => r.name), ["Cellar", "Attic", "Loft"]);
});

test("addFloor refuses bad buildings, names, levels and sizes", () => {
  const s = floorWorld();
  assert.ok(W.addFloor(s, R(s, "field"), {name: "Meadow", level: 1}, set).error, "no walls");
  assert.ok(W.addFloor(s, R(s, "house"), {name: "  "}, set).error, "empty name");
  assert.ok(W.addFloor(s, R(s, "house"), {name: "Field", level: 1}, set).error, "name taken");
  assert.ok(W.addFloor(s, R(s, "house"), {name: "Attic", level: 0}, set).error, "level 0");
  assert.ok(W.addFloor(s, R(s, "house"), {name: "Attic", level: 1.5}, set).error, "not whole");
  W.addFloor(s, R(s, "house"), {name: "Attic", level: 1}, set);
  const before = snap(s);
  assert.ok(W.addFloor(s, R(s, "house"), {name: "Loft", level: 1}, set).error, "level taken");
  assert.ok(W.addFloor(s, R(s, "house"), {name: "Loft", level: 2, size: [1, 6]}, set).error, "too narrow");
  assert.ok(W.addFloor(s, R(s, "house"), {name: "Loft", level: 2, size: [33, 6]}, set).error, "too wide");
  assert.ok(W.addFloor(s, R(s, "house"), {name: "Loft", level: 2, size: [6, 40]}, set).error, "too tall");
  assert.equal(snap(s), before, "every refusal changed nothing");
});

test("setFloorLevel moves a floor, refusing 0 and taken levels", () => {
  const s = floorWorld();
  const {region: a} = W.addFloor(s, R(s, "house"), {name: "Attic", level: 1}, set);
  W.addFloor(s, R(s, "house"), {name: "Loft", level: 2}, set);
  const old = a.pocket;
  assert.deepEqual(W.setFloorLevel(s, a, 3, set), {});
  assert.deepEqual(a.pocket, {anchor: "house", level: 3});
  assert.notEqual(a.pocket, old, "a fresh pocket object");
  const before = snap(s);
  assert.ok(W.setFloorLevel(s, a, 2, set).error, "the loft is there");
  assert.ok(W.setFloorLevel(s, a, 0, set).error);
  assert.equal(snap(s), before);
});

// ---------------------------------------------------------------- openings and doorways
test("openingSides: a corner opens both sides, a third value picks one", () => {
  const house = {position: [4, 4], size: [6, 6]};          // rect [4,4] to [9,9]
  assert.deepEqual(W.openingSides(house, [4, 4]), ["s", "w"]);
  assert.deepEqual(W.openingSides(house, [4, 4, "w"]), ["w"]);
  assert.deepEqual(W.openingSides(house, [4, 4, "n"]), ["s", "w"], "a side it isn't on opens nothing");
  assert.deepEqual(W.openingSides(house, [6, 4]), ["s"]);
  assert.deepEqual(W.openingSides(house, [9, 9]), ["n", "e"]);
  assert.deepEqual(W.openingSides(house, [10, 4]), [], "off the rectangle");
});

test("doorways: a south-wall opening gives the doorway and its door placement", () => {
  const s = doorWorld();
  const dws = W.doorways(s);
  assert.equal(dws.length, 1);
  const dw = dws[0];
  assert.deepEqual([dw.cell, dw.out, dw.key], [[6, 4], [6, 3], "6,3,y"]);
  assert.equal(dw.room.id, "house");
  assert.deepEqual(W.doorPlacement(dw), {pos: [6, 4], rot: 0, size: [1, 0]});
});

test("a west-wall opening gives a vertical door", () => {
  const s = doorWorld();
  set(R(s, "house"), "openings", [[4, 6]]);
  const dw = W.doorways(s)[0];
  assert.deepEqual([dw.cell, dw.out, dw.key], [[4, 6], [3, 6], "3,6,x"]);
  assert.deepEqual(W.doorPlacement(dw), {pos: [4, 6], rot: 1, size: [0, 1]});
  const d = W.hangDoor(s, dw, "door", set);
  assert.deepEqual([d.pos, d.size, d.rot], [[4, 6], [0, 1], 1]);
  assert.equal(W.doorKeyOf(d), "3,6,x");
});

test("a shared wall with matching openings is one doorway, its room the smaller side", () => {
  const s = splitWorld();
  const dws = W.doorways(s);
  assert.equal(dws.length, 2, "the outer door and the shared wall");
  const shared = dws.filter(d => d.key === "5,7,x");
  assert.equal(shared.length, 1, "the pair counts once");
  assert.deepEqual([shared[0].cell, shared[0].out], [[5, 7], [6, 7]]);
  assert.equal(shared[0].room.id, "west", "2 × 6 beats 4 × 4");
  assert.equal(dws.find(d => d.key === "6,3,y").room.id, "house");
});

test("an opening on one side of a wall only is no doorway", () => {
  const s = splitWorld();
  set(R(s, "east"), "openings", []);
  const dws = W.doorways(s);
  assert.equal(dws.length, 1);
  assert.equal(dws[0].key, "6,3,y");
});

// ---------------------------------------------------------------- door objects
test("hangDoor places a zero-width door object with 60 hp", () => {
  const s = doorWorld();
  const dw = W.doorways(s)[0];
  const d = W.hangDoor(s, dw, "door", set);
  assert.deepEqual({...d, id: "x"}, {id: "x", type: "object", name: "Door 1", pos: [6, 4], size: [1, 0],
    hp: 60, maxHp: 60, inventory: [], statusEffects: [], templateId: d.templateId});
  assert.ok(!("rot" in d), "no rot when it lies along x");
  assert.equal(W.doorKeyOf(d), dw.key);
  assert.equal(s.entities.at(-1), d);
  assert.deepEqual(s.objectTemplates.map(t => [t.door, t.name]), [["door", "Door"]]);
  assert.deepEqual({...s.objectTemplates[0], id: "x"},
    {id: "x", name: "Door", size: [1, 0], walkability: 1, door: "door", heightM: 2.1, maxHp: 60});
  assert.equal(W.doorTemplate(s, "door", set), s.objectTemplates[0], "found, not remade");
});

test("isDoor knows only the four door templates", () => {
  const s = doorWorld();
  s.objectTemplates.push({id: "tbl", name: "Table"});
  s.entities.push({id: "t1", type: "object", name: "Table 1", pos: [5, 6], size: [1, 1], templateId: "tbl"});
  s.entities.push({id: "n1", type: "npc", name: "Kim", pos: [5, 6], size: [1, 1]});
  s.entities.push({id: "odd", type: "object", name: "Odd", pos: [5, 6], size: [1, 1], templateId: "nope"});
  assert.equal(W.isDoor(s, E(s, "t1")), false);
  assert.equal(W.isDoor(s, E(s, "n1")), false);
  assert.equal(W.isDoor(s, E(s, "odd")), false);
  const d = W.hangDoor(s, W.doorways(s)[0], "curtain", set);
  assert.equal(W.isDoor(s, d), true);
});

test("hangAllDoors hangs one door per doorway and names them after the template", () => {
  const s = splitWorld();
  assert.equal(W.hangAllDoors(s, set), 2);
  assert.deepEqual(s.entities.map(d => [d.name, d.pos, d.size, d.rot ?? 0]),
    [["Door 1", [6, 4], [1, 0], 0], ["Door 2", [6, 7], [0, 1], 1]]);
  assert.equal(W.hangAllDoors(s, set), 0, "nothing left to hang");
  assert.deepEqual([...W.doorsByKey(s).keys()].sort(), ["5,7,x", "6,3,y"]);
  assert.deepEqual(W.strayDoors(s), []);
  assert.equal(W.regionDoorways(s, R(s, "west")).length, 1);
  assert.equal(W.regionDoorways(s, R(s, "east")).length, 0, "the shared doorway's room is the west room");
});

test("setRegionDoorKind re-templates doors, and none takes them off", () => {
  const s = splitWorld();
  W.hangAllDoors(s, set);
  W.setRegionDoorKind(s, R(s, "west"), "gate", set);
  assert.equal(R(s, "west").door, "gate");
  const gate = W.regionDoors(s, R(s, "west"))[0];
  assert.equal(gate.name, "Gate 1");
  assert.equal(gate.templateId, W.doorTemplate(s, "gate", set).id);
  W.setRegionDoorKind(s, R(s, "west"), "none", set);
  assert.equal(R(s, "west").door, "none");
  assert.equal(W.regionDoors(s, R(s, "west")).length, 0);
  assert.equal(W.hangAllDoors(s, set), 0, "the none room stays open");
  assert.equal(s.entities.length, 1, "the outer door stays");
});

test("strayDoors finds doors whose doorway is gone", () => {
  const s = splitWorld();
  W.hangAllDoors(s, set);
  set(R(s, "house"), "openings", []);
  const strays = W.strayDoors(s);
  assert.equal(strays.length, 1);
  assert.deepEqual(strays[0].pos, [6, 4], "the outer door");
});

test("regionDoors splits door objects by which side of the wall they sit on", () => {
  const s = splitWorld();
  W.hangAllDoors(s, set);
  const [outer, shared] = s.entities;
  assert.deepEqual(W.regionDoors(s, R(s, "house")), [outer]);
  assert.deepEqual(W.regionDoors(s, R(s, "west")), [shared]);
  assert.deepEqual(W.regionDoors(s, R(s, "east")), [shared]);
});

// ---------------------------------------------------------------- locks and keys
test("setLocked locks and unlocks every door of a region", () => {
  const s = doorWorld(), house = R(s, "house");
  assert.deepEqual(W.setLocked(s, house, true, set), {error: "House has no doors to lock; hang doors first"});
  const d = W.hangDoor(s, W.doorways(s)[0], "door", set);
  assert.deepEqual(W.setLocked(s, house, true, set), {count: 1});
  assert.equal(W.isLocked(d), true);
  assert.equal(W.regionLocked(s, house), true);
  const fx = d.statusEffects[0];
  assert.match(fx.id, /^se_/);
  assert.deepEqual({...fx, id: "x"}, {id: "x", appliedAt: 28800,
    def: {desc: "locked", emoji: "🔒", type: "constant", mechanics: [{type: "locked"}]}});
  assert.deepEqual(W.setLocked(s, house, false, set), {count: 1});
  assert.equal(W.regionLocked(s, house), false);
  assert.deepEqual(d.statusEffects, []);
});

test("setLocked counts only the doors it changes", () => {
  const s = doorWorld();
  set(R(s, "house"), "openings", [[6, 4], [4, 6]]);
  W.hangAllDoors(s, set);
  const [a] = W.regionDoors(s, R(s, "house"));
  set(a, "statusEffects", [{id: "se_old", def: {mechanics: [{type: "locked"}]}, appliedAt: 0}]);
  assert.equal(W.regionLocked(s, R(s, "house")), false, "one of two is locked");
  assert.deepEqual(W.setLocked(s, R(s, "house"), true, set), {count: 1});
  assert.equal(W.regionLocked(s, R(s, "house")), true);
});

test("keyTemplate, giveKey, takeKey and keyHolders", () => {
  const s = doorWorld();
  s.entities.push({id: "pc", type: "player", name: "Pat", pos: [12, 12], size: [1, 1], inventory: [], statusEffects: []});
  s.entities.push({id: "ai", type: "npc", name: "Ash", pos: [13, 12], size: [1, 1], inventory: [], statusEffects: []});
  const house = R(s, "house"), pc = E(s, "pc"), ai = E(s, "ai");
  const key = W.keyTemplate(s, house, set);
  assert.match(key.id, /^itpl_/);
  assert.deepEqual({...key, id: "x"},
    {id: "x", name: "House key", description: "", type: "misc", quality: "common", opens: "house"});
  assert.equal(W.keyTemplate(s, house, set), key, "found, not remade");
  W.giveKey(s, house, pc, set);
  W.giveKey(s, house, pc, set);
  assert.equal(pc.inventory.length, 1, "no second key for a holder");
  assert.deepEqual({...pc.inventory[0], id: "x"}, {id: "x", templateId: key.id, count: 1});
  assert.deepEqual(W.keyHolders(s, house), [pc]);
  W.giveKey(s, house, ai, set);
  assert.deepEqual(W.keyHolders(s, house), [pc, ai]);
  pc.inventory.push({id: "it_dupe", templateId: key.id, count: 1});
  pc.inventory.push({id: "it_bread", templateId: "bread", count: 2});
  W.takeKey(s, house, pc, set);
  assert.deepEqual(pc.inventory, [{id: "it_bread", templateId: "bread", count: 2}], "every key, nothing else");
  assert.deepEqual(W.keyHolders(s, house), [ai]);
});

// ---------------------------------------------------------------- portals
test("linkPortal pairs both ends and unlinks the old partners first", () => {
  const s = doorWorld();
  const mk = (id, x) => ({id, type: "object", name: `P${id}`, pos: [x, 20], size: [1, 1], inventory: [], statusEffects: []});
  const a = mk("pa", 1), b = mk("pb", 2), c = mk("pc2", 3);
  s.entities.push(a, b, c);
  assert.deepEqual(W.linkPortal(s, a, b, set), {});
  assert.deepEqual(a.portal, {to: "pb"});
  assert.deepEqual(b.portal, {to: "pa"});
  assert.equal(W.portalPartner(s, a), b);
  assert.equal(W.portalPartner(s, c), null);
  assert.deepEqual(W.linkPortal(s, a, c, set), {});
  assert.deepEqual(a.portal, {to: "pc2"});
  assert.deepEqual(c.portal, {to: "pa"});
  assert.ok(!b.portal, "the old partner is unlinked");
  W.unlinkPortal(s, a, set);
  assert.ok(!a.portal && !c.portal);
});

test("unlinkPortal leaves a partner that points elsewhere", () => {
  const s = doorWorld();
  const a = {id: "pa", type: "object", name: "A", pos: [1, 20], size: [1, 1], inventory: [], statusEffects: [], portal: {to: "pb"}};
  const b = {id: "pb", type: "object", name: "B", pos: [2, 20], size: [1, 1], inventory: [], statusEffects: [], portal: {to: "other"}};
  s.entities.push(a, b);
  W.unlinkPortal(s, a, set);
  assert.ok(!a.portal);
  assert.deepEqual(b.portal, {to: "other"});
});

test("linkPortal refuses itself, non-objects and doors", () => {
  const s = doorWorld();
  const a = {id: "pa", type: "object", name: "A", pos: [1, 20], size: [1, 1], inventory: [], statusEffects: []};
  const npc = {id: "n1", type: "npc", name: "Kim", pos: [5, 6], size: [1, 1], inventory: [], statusEffects: []};
  const door = W.hangDoor(s, W.doorways(s)[0], "door", set);
  s.entities.push(a, npc);
  const before = snap(s);
  assert.ok(W.linkPortal(s, a, a, set).error);
  assert.ok(W.linkPortal(s, a, npc, set).error);
  assert.ok(W.linkPortal(s, a, door, set).error);
  assert.equal(snap(s), before);
});

// ---------------------------------------------------------------- NPC types
test("npcTypes, homesOf and stanceOf read both forms", () => {
  const s = legacyWorld();
  const [villager, zombie, deer, ghost] = W.npcTypes(s);
  assert.deepEqual([villager.id, zombie.id, deer.id, ghost.id], ["n0", "h1", "h2", "h3"]);
  assert.equal(W.isLegacy(s, zombie), true);
  assert.equal(W.isLegacy(s, villager), false);
  assert.deepEqual(W.homesOf(zombie), [{regionId: "crypt", count: 3}]);
  assert.deepEqual(W.homesOf(deer), [{regionId: "field", count: 0}], "a missing count is 0");
  assert.deepEqual(W.homesOf(ghost), []);
  assert.deepEqual(W.homesOf(villager), [{regionId: "field", count: 1}]);
  assert.equal(W.stanceOf(s, zombie), "hostile");
  assert.equal(W.stanceOf(s, deer), "neutral");
  assert.equal(W.stanceOf(s, ghost), "skittish");
  assert.equal(W.stanceOf(s, villager), "neutral");
  assert.equal(W.stanceOf(s, {name: "Plain"}), "neutral", "a 1.0 type without a stance");
});

test("convertToNpcTemplates does the game's conversion", () => {
  const s = legacyWorld();
  assert.equal(W.convertToNpcTemplates(s, set), 3);
  assert.ok(!("hostileNpcTemplates" in s));
  assert.deepEqual(s.npcTemplates.map(t => t.id), ["n0", "h1", "h2", "h3"], "after any existing ones");
  const [, zombie, deer, ghost] = s.npcTemplates;
  assert.deepEqual(zombie, {id: "h1", name: "Zombie", animationId: "zombie", gender: "male",
    level: 2, money: 5, lootPoolIds: ["lp1"], stance: "hostile", homes: [{regionId: "crypt", count: 3}]});
  assert.deepEqual(deer, {id: "h2", name: "Deer", animationId: "deer", gender: "female",
    stance: "neutral", homes: [{regionId: "field", count: 0}]});
  assert.deepEqual(ghost, {id: "h3", name: "Ghost", stance: "skittish", homes: []});
  assert.equal(W.isLegacy(s, zombie), false);
  assert.equal(E(s, "z1").npcHome, "crypt");
  assert.equal(E(s, "z2").npcHome, "field", "an npcHome is kept");
  assert.equal(E(s, "d1").npcHome, "field");
  assert.ok(!("npcHome" in E(s, "g1")), "no regionId, no npcHome");
  assert.equal(W.convertToNpcTemplates(s, set), 0);
});

test("convertToNpcTemplates leaves a scenario without legacy types alone", () => {
  const s = doorWorld(), before = snap(s);
  assert.equal(W.convertToNpcTemplates(s, set), 0);
  assert.equal(snap(s), before);
});

test("setHomes keeps one home on a legacy type and converts for more", () => {
  const s = legacyWorld();
  const zombie = W.npcTypes(s)[1];
  const t = W.setHomes(s, zombie, [{regionId: "field", count: 2}], set);
  assert.equal(t, zombie);
  assert.equal(zombie.regionId, "field");
  assert.equal(zombie.count, 2);
  assert.equal(W.isLegacy(s, zombie), true, "one home still fits the old form");

  const s2 = legacyWorld();
  const z2 = W.npcTypes(s2)[1];
  const c = W.setHomes(s2, z2, [{regionId: "crypt", count: 1}, {regionId: "field", count: 2}], set);
  assert.equal(c.id, "h1");
  assert.equal(W.isLegacy(s2, c), false);
  assert.deepEqual(c.homes, [{regionId: "crypt", count: 1}, {regionId: "field", count: 2}]);
  assert.ok(!("hostileNpcTemplates" in s2), "the whole scenario converted");

  const s3 = legacyWorld();
  const villager = W.npcTypes(s3)[0];
  assert.equal(W.setHomes(s3, villager, [{regionId: "crypt", count: 5}], set), villager);
  assert.deepEqual(villager.homes, [{regionId: "crypt", count: 5}]);
});

test("setStance takes only the three stances", () => {
  const s = legacyWorld();
  const villager = W.npcTypes(s)[0];
  assert.deepEqual(W.setStance(s, villager, "hostile", set), {});
  assert.equal(villager.stance, "hostile");
  const before = snap(s);
  assert.ok(W.setStance(s, villager, "angry", set).error);
  assert.equal(snap(s), before);
});

test("addNpcType joins a legacy scenario in its own form", () => {
  const s = legacyWorld();
  delete s.npcTemplates;                                   // nothing 1.0 yet
  const {template} = W.addNpcType(s, {name: "Rat", animationId: "rat", gender: "female",
    stance: "hostile", regionId: "crypt", count: 2}, set);
  assert.match(template.id, /^htpl_/);
  assert.equal(s.hostileNpcTemplates.at(-1), template);
  assert.deepEqual({...template, id: "x"}, {id: "x", name: "Rat", description: "", physicalDescription: "",
    animationId: "rat", gender: "female", stance: "hostile", level: 1, money: 0, lootPoolIds: [],
    regionId: "crypt", count: 2});
});

test("addNpcType uses 1.0 homes otherwise", () => {
  const s = legacyWorld();                                 // it has npcTemplates already
  const {template} = W.addNpcType(s, {name: "Cat", animationId: "cat", gender: "male",
    stance: "neutral", regionId: "crypt", count: 1}, set);
  assert.match(template.id, /^ntpl_/);
  assert.equal(s.npcTemplates.at(-1), template);
  assert.ok(!("regionId" in template) && !("count" in template));
  assert.deepEqual(template.homes, [{regionId: "crypt", count: 1}]);

  const s2 = doorWorld();                                  // neither list
  const {template: t2} = W.addNpcType(s2, {name: "Dog", animationId: "dog", gender: "female",
    stance: "skittish", regionId: "house", count: 1}, set);
  assert.equal(s2.npcTemplates.length, 1);
  assert.deepEqual(t2.homes, [{regionId: "house", count: 1}]);
});

test("addNpcType refuses empty and used names", () => {
  const s = legacyWorld(), before = snap(s);
  assert.ok(W.addNpcType(s, {name: "  "}, set).error);
  assert.ok(W.addNpcType(s, {name: "Zombie"}, set).error, "used by a legacy type");
  assert.ok(W.addNpcType(s, {name: "Villager"}, set).error, "used by a 1.0 type");
  assert.equal(snap(s), before);
});
