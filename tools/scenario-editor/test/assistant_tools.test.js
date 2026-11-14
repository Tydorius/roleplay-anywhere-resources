"use strict";
// node --test test/      (from tools/scenario-editor)
const test = require("node:test");
const assert = require("node:assert/strict");
const T = require("../assistant_tools.js");
const M = require("../mapops.js");
const Refs = require("../refs.js");
const Schedule = require("../schedule.js");
const World10 = require("../world10.js");
const Design = require("../design.js");

const set = (o, k, v) => { if (v === undefined) delete o[k]; else o[k] = v; };
const snap = o => JSON.stringify(o);

// A 30 × 30 map: a house split into a kitchen and a hall, a walled inn, and a field off to the
// side. Mara works at the inn and sleeps at the house; the cow stays in the field all day.
function world() {
  return {
    name: "Test Valley", gridSize: [30, 30],
    defaultTile: {ground: "grass", groundTexture: "grass", ambience: {day: "nature_outdoors"}},
    worldBackground: "A quiet valley.",
    regions: [
      {id: "house", name: "House", wall: "wood", ground: "wood", groundTexture: "floorboards", position: [2, 2], size: [10, 6], openings: [[6, 2]]},
      {id: "kitchen", name: "Kitchen", wall: "wood", position: [2, 2], size: [5, 6], openings: [[6, 4]], description: "Smells of stew"},
      {id: "hall", name: "Hall", wall: "wood", position: [7, 2], size: [5, 6], openings: [[7, 4]]},
      {id: "inn", name: "Inn", wall: "brick", position: [15, 2], size: [8, 5], openings: [[18, 2]]},
      {id: "field", name: "Field", position: [15, 15], size: [10, 10], openings: [], description: "Golden wheat"},
    ],
    entities: [
      {id: "table", type: "object", name: "Table 1", pos: [3, 3], size: [2, 1], templateId: "tpl_table", inventory: [], statusEffects: []},
      {id: "pc", type: "player", name: "Pat", pos: [9, 5], size: [1, 1], inventory: [], statusEffects: []},
      {id: "cow", type: "npc", name: "Cow", gender: "female", pos: [20, 20], size: [1, 1], inventory: [], statusEffects: [],
        description: "A dairy cow", schedule: [{start: "00:00", end: "00:00", location: "Field", role: "leisure"}]},
      {id: "mara", type: "npc", name: "Mara", gender: "female", pos: [16, 3], size: [1, 1], inventory: [], statusEffects: [], mindset: "Counts every coin",
        schedule: [
          {start: "08:00", end: "18:00", location: "Inn", role: "work"},
          {start: "18:00", end: "22:00", location: "Inn", role: "leisure"},
          {start: "22:00", end: "08:00", location: "House", role: "sleep"},
        ]},
    ],
    playerId: "pc",
    objectTemplates: [
      {id: "tpl_table", name: "Table", size: [2, 1], maxHp: 20, tags: ["furniture"], lootPoolIds: ["itpl_bread"]},
      {id: "tpl_barrel", name: "Barrel", size: [1, 1], maxHp: 15, tags: [], lootPoolIds: []},
      {id: "tpl_stool", name: "Stool", size: [1, 1], maxHp: 10, tags: ["furniture"], lootPoolIds: []},
      {id: "tpl_stairs", name: "Stairs", size: [1, 1], walkability: 1, maxHp: 50, tags: [], lootPoolIds: []},
    ],
    itemTemplates: [{id: "itpl_bread", name: "Bread", type: "food", quality: "common", value: 1, description: "A crusty loaf"}],
    npcTemplates: [{id: "ntpl_bandit", name: "Bandit", description: "A highway robber", homes: [{regionId: "field", count: 2}]}],
    calendar: [{id: "cal_market", name: "Market day", day: 2, location: "Field"}],
  };
}

// Enough regions and templates to cross both summary caps; the geography doesn't matter to summary.
function bigWorld() {
  const s = world();
  s.regions = [];
  for (let i = 1; i <= 160; i++)
    s.regions.push({id: "r" + i, name: "R" + i, position: [(i % 10) * 3, Math.floor(i / 10) * 3], size: [2, 2], openings: []});
  s.objectTemplates = [];
  for (let i = 1; i <= 90; i++) s.objectTemplates.push({id: "t" + i, name: "T" + i, size: [1, 1]});
  return s;
}

const R = (s, id) => s.regions.find(r => r.id === id);
const E = (s, id) => s.entities.find(e => e.id === id);
const names = s => s.regions.map(r => r.name);

// ---------------------------------------------------------------- summary
test("summary is bounded, JSON round-trips, and stays small", () => {
  const s = bigWorld(), sum = T.summary(s);
  assert.equal(sum.regions.length, 151, "150 entries plus the tail");
  assert.equal(sum.regions.at(-1), "... and 10 more");
  assert.equal(sum.objectTemplates.length, 80);
  assert.deepEqual(JSON.parse(JSON.stringify(sum)), sum, "JSON round-trips");
  const len = JSON.stringify(sum).length;
  assert.ok(len < 9000, len + " characters");
});

test("summary: home is the night block's region, else the all-day one, else where they stand", () => {
  const sum = T.summary(world());
  assert.equal(sum.name, "Test Valley");
  assert.deepEqual(sum.gridSize, [30, 30]);
  assert.equal(sum.npcs.find(n => n.name === "Mara").home, "House", "the sleep block's region");
  assert.equal(sum.npcs.find(n => n.name === "Cow").home, "Field", "the all-day block's region");
  assert.deepEqual(sum.player, {id: "pc", name: "Pat"});
  assert.deepEqual(sum.entities, {object: 1, npc: 2, player: 1});
  assert.equal(sum.itemTemplates, 1);
  assert.equal(sum.npcTemplates, 1);
});

// ---------------------------------------------------------------- find
test("find matches names and descriptions, case-insensitively", () => {
  const s = world();
  const res = T.TOOLS.find.run(s, {query: "STEW"}, set);
  assert.equal(res.ok, true);
  assert.deepEqual(res.data.matches, [{id: "kitchen", kind: "region", name: "Kitchen"}]);
  assert.deepEqual(T.TOOLS.find.run(s, {query: "house"}, set).data.matches.map(m => m.id), ["house"]);
  assert.deepEqual(T.TOOLS.find.run(s, {query: "mara"}, set).data.matches, [{id: "mara", kind: "npc", name: "Mara"}]);
  assert.deepEqual(T.TOOLS.find.run(s, {query: "loaf"}, set).data.matches, [{id: "itpl_bread", kind: "itemTemplate", name: "Bread"}]);
  assert.deepEqual(T.TOOLS.find.run(s, {query: "robber"}, set).data.matches, [{id: "ntpl_bandit", kind: "npcTemplate", name: "Bandit"}]);
});

test("find is capped at 20 matches", () => {
  const res = T.TOOLS.find.run(bigWorld(), {query: "r"}, set);
  assert.equal(res.ok, true);
  assert.equal(res.data.matches.length, 20);
  assert.ok(res.data.matches.every(m => m.kind === "region"));
});

// ---------------------------------------------------------------- freeCell
test("freeCell scans the interior from the centre, skipping covered and taken cells", () => {
  const s = world();
  const field = R(s, "field");                       // open 10 × 10 at [15,15]; the cow is on [20,20]
  assert.deepEqual(T.freeCell(s, field, new Set()), [19, 19]);
  assert.deepEqual(T.freeCell(s, field, new Set(["19,19"])), [20, 19]);
  const kitchen = R(s, "kitchen");                   // walled 5 × 6 at [2,2]: every cell stands; the table covers [3,3]-[4,3]
  assert.deepEqual(T.freeCell(s, kitchen, new Set()), [4, 4]);
  const shed = {id: "shed", name: "Shed", wall: "wood", position: [26, 26], size: [2, 2], openings: []};
  assert.deepEqual(T.freeCell(s, shed, new Set()), [26, 26], "walls are lines: every cell of a walled room stands");
});

// ---------------------------------------------------------------- add_npcs
test("add_npcs: happy path places valid NPCs with round-the-clock schedules", () => {
  const s = world();
  const res = T.TOOLS.add_npcs.run(s, {npcs: [
    {name: "Gil", gender: "male", homeRegionId: "inn", workRegionId: "field", shift: "day", description: "A farmhand"},
    {name: "Ada", homeRegionId: "inn", workRegionId: "kitchen", shift: "evening"},
  ]}, set);
  assert.equal(res.ok, true);
  assert.equal(res.data.createdIds.length, 2);
  for (const id of res.data.createdIds) {
    const npc = E(s, id);
    assert.ok(npc, "the entity exists");
    assert.match(npc.id, /^npc_/);
    assert.deepEqual(Schedule.validate(npc.schedule, names(s)), [], npc.name + "'s schedule is valid");
    assert.ok(npc.schedule.every(b => names(s).includes(b.location)), "every block names a region");
  }
  const gil = E(s, res.data.createdIds[0]);
  assert.equal(gil.description, "A farmhand");
  assert.deepEqual(gil.schedule, [
    {start: "08:00", end: "18:00", location: "Field", role: "work"},
    {start: "18:00", end: "22:00", location: "Inn", role: "leisure"},
    {start: "22:00", end: "08:00", location: "Inn", role: "sleep"},
  ], "the work block carries the work region's name, not its id");
  assert.deepEqual(E(s, res.data.createdIds[1]).schedule[0], {start: "15:00", end: "23:00", location: "Kitchen", role: "work"});
  const inInn = s.entities.filter(e => M.inRect(M.rect(R(s, "inn")), e.pos[0], e.pos[1]));
  assert.equal(new Set(inInn.map(e => e.pos.join(","))).size, inInn.length, "nobody in the inn shares a cell");
});

test("add_npcs: a night shift wraps past midnight", () => {
  const s = world();
  const res = T.TOOLS.add_npcs.run(s, {npcs: [{name: "Niko", homeRegionId: "inn", workRegionId: "field", shift: "night"}]}, set);
  assert.equal(res.ok, true);
  const npc = E(s, res.data.createdIds[0]);
  assert.deepEqual(npc.schedule, [
    {start: "22:00", end: "06:00", location: "Field", role: "work"},
    {start: "06:00", end: "14:00", location: "Inn", role: "sleep"},
    {start: "14:00", end: "22:00", location: "Inn", role: "leisure"},
  ]);
  assert.deepEqual(Schedule.validate(npc.schedule, names(s)), []);
});

test("add_npcs: no two NPCs share a cell", () => {
  const s = world();
  const res = T.TOOLS.add_npcs.run(s, {npcs: [1, 2, 3].map(i => ({name: "W" + i, homeRegionId: "field"}))}, set);
  assert.equal(res.ok, true);
  const cells = res.data.createdIds.map(id => E(s, id).pos.join(","));
  assert.equal(new Set(cells).size, 3);
  assert.ok(!cells.includes("20,20"), "not on the cow");
  assert.equal(E(s, res.data.createdIds[0]).schedule.length, 1, "no work region: one all-day block at home");
});

test("add_npcs rejects duplicate names, full regions and unknown ids", () => {
  const s = world();
  const dup = T.TOOLS.add_npcs.run(s, {npcs: [{name: "Mara", homeRegionId: "inn"}]}, set);
  assert.equal(dup.ok, false);
  assert.match(dup.error, /Mara/);
  const twins = T.TOOLS.add_npcs.run(s, {npcs: [{name: "Twin", homeRegionId: "inn"}, {name: "Twin", homeRegionId: "inn"}]}, set);
  assert.equal(twins.ok, true, "the first one is placed");
  assert.equal(twins.data.createdIds.length, 1);
  assert.equal(twins.data.errors.length, 1, "the second is rejected");
  s.regions.push({id: "shed", name: "Shed", wall: "wood", position: [26, 26], size: [2, 2], openings: []});
  s.entities.push({id: "crate_a", type: "object", pos: [26, 26], size: [2, 1], inventory: [], statusEffects: []},
                  {id: "crate_b", type: "object", pos: [26, 27], size: [2, 1], inventory: [], statusEffects: []});
  const full = T.TOOLS.add_npcs.run(s, {npcs: [{name: "Ghost", homeRegionId: "shed"}]}, set);
  assert.equal(full.ok, false);
  assert.match(full.error, /no free cell/);
  const work = T.TOOLS.add_npcs.run(s, {npcs: [{name: "H", homeRegionId: "inn", workRegionId: "nope"}]}, set);
  assert.equal(work.ok, false);
  assert.match(work.error, /nope/);
});

// ---------------------------------------------------------------- update_npc
test("update_npc accepts each whitelisted field and validates it", () => {
  const s = world();
  const run = args => T.TOOLS.update_npc.run(s, args, set);
  assert.equal(run({id: "mara", description: "The innkeeper"}).ok, true);
  assert.equal(E(s, "mara").description, "The innkeeper");
  assert.equal(run({id: "mara", physicalDescription: "Tall and tired"}).ok, true);
  assert.equal(E(s, "mara").physicalDescription, "Tall and tired");
  assert.equal(run({id: "mara", mindset: "Wants to see the sea"}).ok, true);
  assert.equal(E(s, "mara").mindset, "Wants to see the sea");
  assert.equal(run({id: "mara", stance: "fleeing"}).ok, true);
  assert.equal(E(s, "mara").stance, "fleeing");
  assert.equal(run({id: "mara", stance: "angry"}).ok, false);
  assert.equal(run({id: "mara", merchant: true}).ok, true);
  assert.deepEqual(E(s, "mara").merchant, {});
  assert.equal(run({id: "mara", merchant: false}).ok, true);
  assert.ok(!("merchant" in E(s, "mara")));
  const sched = Schedule.makeAllDay("Inn");
  assert.equal(run({id: "mara", schedule: sched}).ok, true);
  assert.deepEqual(E(s, "mara").schedule, sched);
  const broken = run({id: "mara", schedule: [{start: "08:00", end: "12:00", location: "Inn", role: "work"}]});
  assert.equal(broken.ok, false);
  assert.match(broken.error, /schedule/);
  const unknown = run({id: "mara", mood: "cheerful"});
  assert.equal(unknown.ok, false);
  assert.match(unknown.error, /mood/);
});

// ---------------------------------------------------------------- remove_npc, remove_object
test("remove_npc deletes through Refs.forceDelete, repairing links", () => {
  const s = world();
  s.entities.push({id: "gate", type: "object", name: "Gate", pos: [17, 3], size: [1, 1], templateId: "tpl_barrel",
    inventory: [], statusEffects: [], portal: {to: "cow"}});
  const before = Refs.previewDelete(s, ["cow"], {});
  assert.equal(before.removed.length, 1);
  assert.equal(before.changed.length, 1, "the gate's link to the cow is repaired");
  const res = T.TOOLS.remove_npc.run(s, {id: "cow"}, set);
  assert.equal(res.ok, true);
  assert.ok(!E(s, "cow"), "the npc is gone");
  assert.ok(!E(s, "gate").portal, "the other end of the link is gone too");
  const after = Refs.previewDelete(s, ["cow"], {});
  assert.deepEqual(after.removed, []);
  assert.equal(after.warnings.length, 1, "the id names nothing now");
});

test("remove_object deletes and unlinks a portal partner", () => {
  const s = world();
  E(s, "table").portal = {to: "stair"};
  s.entities.push({id: "stair", type: "object", name: "Stair", pos: [16, 3], size: [1, 1], templateId: "tpl_barrel",
    inventory: [], statusEffects: [], portal: {to: "table"}});
  const res = T.TOOLS.remove_object.run(s, {id: "stair"}, set);
  assert.equal(res.ok, true);
  assert.ok(!E(s, "stair"));
  assert.ok(!E(s, "table").portal, "the table no longer leads anywhere");
});

// ---------------------------------------------------------------- edit_texts
test("edit_texts applies good edits and reports per-edit errors", () => {
  const s = world();
  const res = T.TOOLS.edit_texts.run(s, {edits: [
    {id: "scenario", field: "worldBackground", value: "  A loud valley.  "},
    {id: "kitchen", field: "worldBackground", value: "regions have no such field"},
    {id: "cow", field: "description", value: "Moo"},
  ]}, set);
  assert.equal(res.ok, true);
  assert.equal(s.worldBackground, "A loud valley.", "trimmed");
  assert.equal(E(s, "cow").description, "Moo");
  assert.ok(!("worldBackground" in R(s, "kitchen")), "the bad edit changed nothing");
  assert.equal(res.data.applied.length, 2);
  assert.equal(res.data.errors.length, 1);

  const lengths = T.TOOLS.edit_texts.run(s, {edits: [
    {id: "scenario", field: "narrativeFlavor", value: "x".repeat(4001)},
    {id: "field", field: "description", value: "y".repeat(4000)},
  ]}, set);
  assert.equal(lengths.ok, true);
  assert.ok(!("narrativeFlavor" in s), "over the cap: reported, not applied");
  assert.equal(R(s, "field").description.length, 4000, "at the cap: applied");
  assert.equal(lengths.data.errors.length, 1);

  assert.equal(T.TOOLS.edit_texts.run(s, {edits: [{id: "nope", field: "description", value: "x"}]}, set).ok, false);
  assert.equal(T.TOOLS.edit_texts.run(s, {edits: Array.from({length: 11}, () => ({id: "field", field: "description", value: "x"}))}, set).ok, false, "cap 10");
});

// ---------------------------------------------------------------- place_objects
test("place_objects places the count on distinct free cells", () => {
  const s = world();
  const res = T.TOOLS.place_objects.run(s, {templateId: "tpl_barrel", regionId: "field", count: 3}, set);
  assert.equal(res.ok, true);
  assert.equal(res.data.placed.length, 3);
  const cells = res.data.placed.map(p => p.cell.join(","));
  assert.equal(new Set(cells).size, 3, "cells are distinct");
  for (const p of res.data.placed) {
    const covered = s.entities.filter(e => e.pos[0] <= p.cell[0] && p.cell[0] < e.pos[0] + (e.size?.[0] || 1)
      && e.pos[1] <= p.cell[1] && p.cell[1] < e.pos[1] + (e.size?.[1] || 1));
    assert.deepEqual(covered, [E(s, p.id)], JSON.stringify(p.cell) + " is free of everything else");
  }
  assert.ok(res.data.placed.every(p => p.name.startsWith("Barrel")), "named after the template");
  const walled = T.TOOLS.place_objects.run(s, {templateId: "tpl_barrel", regionId: "kitchen", count: 2}, set);
  assert.equal(walled.ok, true);
  for (const p of walled.data.placed)
    assert.ok(p.cell[0] >= 2 && p.cell[0] <= 6 && p.cell[1] >= 2 && p.cell[1] <= 7, "every cell of the walled room stands");
});

// ---------------------------------------------------------------- create_room
test("create_room builds a walled room with a hung door on the middle of its south edge", () => {
  const s = world();
  const res = T.TOOLS.create_room.run(s, {name: "Closet", x: 2, y: 20, w: 6, h: 5, wall: "wood"}, set);
  assert.equal(res.ok, true);
  const reg = R(s, res.data.regionId);
  assert.equal(reg.wall, "wood");
  assert.deepEqual(reg.position, [2, 20]);
  assert.deepEqual(reg.size, [6, 5]);
  assert.deepEqual(reg.openings, [[4, 20]], "one opening at the middle of the south edge");
  assert.deepEqual(res.data.doors, [[4, 20]]);
  const dw = World10.doorways(s).find(d => d.room === reg);
  assert.ok(dw, "the opening makes a doorway");
  const door = s.entities.find(e => World10.isDoor(s, e));
  assert.ok(door, "a door object was hung");
  assert.equal(World10.doorKeyOf(door), dw.key, "it hangs on the new doorway");
  assert.equal(door.name, "Door 1");
  assert.deepEqual(R(s, "house").openings, [[6, 2]], "no neighbour shares the wall line: nothing else opens");
});

test("create_room opens both sides of a shared wall and lands several doors", () => {
  const s = world();
  const res = T.TOOLS.create_room.run(s, {name: "Stable", x: 23, y: 2, w: 4, h: 4, wall: "wood", doors: ["w"]}, set);
  assert.equal(res.ok, true);
  const reg = R(s, res.data.regionId);
  assert.deepEqual(reg.openings, [[23, 3]], "the door at the middle of the west edge");
  assert.ok(R(s, "inn").openings.some(c => c[0] === 22 && c[1] === 3), "the inn opens its facing cell too");
  const dw = World10.doorways(s).find(d => d.room === reg);
  assert.ok(dw, "the shared wall is a doorway");
  assert.ok(s.entities.some(e => World10.isDoor(s, e) && World10.doorKeyOf(e) === dw.key), "with a door object on it");

  const two = T.TOOLS.create_room.run(s, {name: "Shop", x: 2, y: 12, w: 7, h: 6, wall: "brick", doors: ["n", "e"]}, set);
  assert.equal(two.ok, true);
  const shop = R(s, two.data.regionId);
  assert.deepEqual(shop.openings, [[5, 17], [8, 14]], "n lands mid-north-edge, e mid-east-edge");
  assert.deepEqual(two.data.doors, [[5, 17], [8, 14]]);
  assert.equal(s.entities.filter(e => World10.isDoor(s, e)).length, 3, "every doorway got a door object");
});

test("create_room: an open area gets no doors; overlaps and off-map rooms are refused", () => {
  const s = world();
  const open = T.TOOLS.create_room.run(s, {name: "Yard", x: 15, y: 26, w: 5, h: 3}, set);
  assert.equal(open.ok, true);
  const reg = R(s, open.data.regionId);
  assert.ok(!reg.wall);
  assert.deepEqual(reg.openings, []);
  assert.deepEqual(open.data.doors, []);
  assert.equal(s.entities.filter(e => World10.isDoor(s, e)).length, 0, "no door objects anywhere");
  const before = s.regions.length;
  const overlap = T.TOOLS.create_room.run(s, {name: "X", x: 20, y: 3, w: 6, h: 4, wall: "wood"}, set);
  assert.equal(overlap.ok, false);
  assert.match(overlap.error, /overlap/);
  const away = T.TOOLS.create_room.run(s, {name: "X", x: 27, y: 2, w: 6, h: 3, wall: "wood"}, set);
  assert.equal(away.ok, false);
  assert.match(away.error, /leave the map/);
  assert.equal(s.regions.length, before, "the refused rooms changed nothing");
});

// ---------------------------------------------------------------- create_building
test("create_building raises a walled building split into rooms, doors and an entrance", () => {
  const s = world();
  const res = T.TOOLS.create_building.run(s, {name: "Tannery", x: 1, y: 12, w: 14, h: 9, wall: "wood",
    rooms: [{name: "Foyer", share: 2}, {name: "Workshop"}, {name: "Store"}],
    connections: [["Foyer", "Workshop"], ["Foyer", "Store"]], entrance: {room: "Foyer", side: "s"}}, set);
  assert.equal(res.ok, true, res.error);
  const b = R(s, res.data.buildingId);
  assert.equal(b.wall, "wood");
  assert.deepEqual(b.position, [1, 12]);
  assert.deepEqual(b.size, [14, 9]);
  assert.equal(res.data.roomIds.length, 3);
  assert.equal(s.regions.length, 9, "four new regions on top of the five the world started with");
  const rooms = res.data.roomIds.map(id => R(s, id));
  assert.deepEqual(M.contents(s, b).regions.map(r => r.id).sort(), res.data.roomIds.slice().sort(),
    "the three rooms sit inside the building");
  const byName = Object.fromEntries(rooms.map(r => [r.name, r]));
  for (const r of [b, ...rooms]) {
    assert.ok(M.containsRect(M.rect(b), M.rect(r)), r.name + " stays inside the footprint");
    assert.equal(r.wall, "wood", r.name + " carries the building's wall");
  }
  assert.ok(rooms.every(r => !r.description), "a room's description is empty");
  const dws = World10.doorways(s);
  const crossing = (ra, rb) => dws.some(d =>
    (M.inRect(M.rect(ra), d.cell[0], d.cell[1]) && M.inRect(M.rect(rb), d.out[0], d.out[1])) ||
    (M.inRect(M.rect(rb), d.cell[0], d.cell[1]) && M.inRect(M.rect(ra), d.out[0], d.out[1])));
  for (const [a, c] of [["Foyer", "Workshop"], ["Foyer", "Store"], ["Workshop", "Store"]])
    assert.ok(crossing(byName[a], byName[c]), a + " and " + c + " share no doorway");
  const south = dws.find(d => d.cell[0] === d.out[0] && d.cell[1] === 12 && d.out[1] === 11);
  assert.ok(south, "the entrance crosses the building's south wall");
  assert.ok(M.inRect(M.rect(byName.Foyer), south.cell[0], south.cell[1]), "through the Foyer");
  assert.equal(res.data.doors, 4, "three shared walls and the entrance");
  const have = World10.doorsByKey(s);
  const ours = dws.filter(d => d.room === b || rooms.includes(d.room));
  assert.equal(ours.length, 4, "every doorway belongs to the new building");
  for (const d of ours) assert.ok((have.get(d.key) || []).length, "a door object hangs on " + d.key);
  for (const e of s.entities.filter(e => World10.isDoor(s, e)))
    assert.ok(M.inRect(M.rect(b), e.pos[0], e.pos[1]), "a door object's cell left the footprint");
});

test("create_building refuses collisions, overlaps and undoable footprints with nothing added", () => {
  const s = world();
  const before = s.regions.length;
  const base = {x: 1, y: 12, w: 14, h: 9, wall: "wood", rooms: [{name: "Hall"}, {name: "Store"}]};
  const buildingClash = T.TOOLS.create_building.run(s, {...base, name: "Inn"}, set);
  assert.equal(buildingClash.ok, false);
  assert.match(buildingClash.error, /Inn/);
  const roomClash = T.TOOLS.create_building.run(s, {...base, name: "Tannery"}, set);
  assert.equal(roomClash.ok, false, "a room of the building is called Hall, like the world's region");
  assert.match(roomClash.error, /Hall/);
  const overlap = T.TOOLS.create_building.run(s, {...base, name: "Tannery",
    rooms: [{name: "Shop"}, {name: "Store"}], x: 18, y: 3, w: 8, h: 5}, set);
  assert.equal(overlap.ok, false);
  assert.match(overlap.error, /overlap/);
  const offMap = T.TOOLS.create_building.run(s, {...base, name: "Tannery",
    rooms: [{name: "Shop"}, {name: "Store"}], x: 26, y: 2, w: 14, h: 9}, set);
  assert.equal(offMap.ok, false);
  assert.match(offMap.error, /leave the map/);
  const small = T.TOOLS.create_building.run(s, {...base, name: "Tannery",
    rooms: [{name: "Shop"}, {name: "Store"}, {name: "Yard"}], w: 6, h: 5}, set);
  assert.equal(small.ok, false, "the footprint cannot honour the minimum room sizes");
  assert.match(small.error, /at least \d+x\d+/);
  assert.equal(s.regions.length, before, "no refusal added a region");
});

test("create_building: the bad-input matrix", () => {
  const s = world();
  const before = s.regions.length;
  const good = {name: "Tannery", x: 1, y: 12, w: 14, h: 9, wall: "wood",
    rooms: [{name: "Hall", share: 2}, {name: "Workshop"}, {name: "Store"}],
    connections: [["Hall", "Workshop"], ["Hall", "Store"]], entrance: {room: "Hall", side: "s"}};
  const cases = [
    [{...good, entrance: {room: "Hall", side: "north"}}, /side/],
    [{...good, entrance: {room: "Hall", side: 3}}, /side/],
    [{...good, entrance: {room: "Attic", side: "s"}}, /Attic/],
    [{...good, entrance: "south"}, /entrance/],
    [{...good, connections: [["Hall", "Attic"]]}, /Attic/],
    [{...good, connections: [["Hall"]]}, /connection/],
    [{...good, rooms: []}, /rooms/],
    [{...good, rooms: Array.from({length: 9}, (_, i) => ({name: "R" + i}))}, /rooms/],
    [{...good, rooms: [{name: "Hall"}, {name: "Hall"}]}, /Hall/],
    [{...good, rooms: [{name: "Hall"}, {name: "X".repeat(41)}]}, /40/],
    [{...good, rooms: [{name: "Hall"}, {name: "S", share: 0}]}, /share/],
    [{...good, wall: "glass"}, /wall/],
    [{...good, w: 0}, /w must/],
  ];
  for (const [args, pattern] of cases) {
    const res = T.TOOLS.create_building.run(s, args, set);
    assert.equal(res.ok, false, snap(args).slice(0, 90));
    assert.match(res.error, pattern);
  }
  assert.equal(s.regions.length, before, "nothing was added");
});

// ---------------------------------------------------------------- furnish_region
test("furnish_region places what the engine works out, named after the template", () => {
  const s = world();
  const items = [
    {templateId: "tpl_table", count: 1, hint: "wall:n"},
    {templateId: "tpl_stool", count: 4, hint: "around:Table"},
  ];
  const res = T.TOOLS.furnish_region.run(s, {regionId: "inn", items}, set);
  assert.equal(res.ok, true);
  assert.deepEqual(res.data.failures, []);
  assert.deepEqual(res.data.fallbacks, []);
  const w = world(), want = Design.furnish(w, R(w, "inn"), items);
  assert.deepEqual(want.failures, []);
  assert.equal(res.data.placed.length, want.placements.length);
  res.data.placed.forEach((p, i) => {
    assert.equal(p.cell.join(","), want.placements[i].pos.join(","), "placement " + i + " matches the engine");
    const e = E(s, p.id);
    assert.equal(e.templateId, want.placements[i].templateId);
    assert.deepEqual(e.pos, want.placements[i].pos);
  });
  assert.equal(res.data.placed[0].cell[1], 6, "the table stands against the north wall");
  assert.deepEqual(res.data.placed.map(p => p.name), ["Table 2", "Stool 1", "Stool 2", "Stool 3", "Stool 4"],
    "copies are named after the template");
});

test("furnish_region: an over-full request partly succeeds; unknown ids are refused", () => {
  const s = world();
  s.regions.push({id: "shed", name: "Shed", wall: "wood", position: [26, 26], size: [2, 2], openings: []});
  const full = T.TOOLS.furnish_region.run(s, {regionId: "shed", items: [{templateId: "tpl_barrel", count: 12}]}, set);
  assert.equal(full.ok, true, "partial success");
  assert.equal(full.data.placed.length, 4, "a 2x2 shed holds four barrels");
  assert.equal(full.data.failures.length, 1);
  assert.equal(full.data.failures[0].placed, 4);
  assert.equal(full.data.failures[0].wanted, 12);
  assert.match(full.data.failures[0].reason, /no free cell/);
  assert.match(full.summary, /placed 4 of 12/);
  const noRegion = T.TOOLS.furnish_region.run(s, {regionId: "nope", items: [{templateId: "tpl_barrel", count: 1}]}, set);
  assert.equal(noRegion.ok, false);
  const noTpl = T.TOOLS.furnish_region.run(s, {regionId: "inn", items: [{templateId: "nope", count: 1}]}, set);
  assert.equal(noTpl.ok, false);
  assert.match(noTpl.error, /unknown template/);
});

// ---------------------------------------------------------------- clear_region
test("clear_region removes the clutter, keeping and counting doors and portal ends", () => {
  const s = world();
  T.TOOLS.place_objects.run(s, {templateId: "tpl_barrel", regionId: "inn", count: 3}, set);
  const door = World10.hangDoor(s, World10.doorways(s).find(d => d.room === R(s, "inn")), "door", set);
  const stairs = s.objectTemplates.find(t => t.id === "tpl_stairs");
  const low = M.placeObject(s, stairs, 16, 4, set);
  const high = M.placeObject(s, stairs, 20, 16, set);
  World10.linkPortal(s, low, high, set);
  const templates = s.objectTemplates.length;
  const pre = T.preview(s, {tool: "clear_region", args: {regionId: "inn"}});
  assert.ok(pre.includes("Barrel 1") && pre.includes("Barrel 3"), "the preview names the barrels");
  assert.ok(pre.includes("Door 1") && pre.includes("Stairs 1"), "and what it would keep");
  const res = T.TOOLS.clear_region.run(s, {regionId: "inn"}, set);
  assert.equal(res.ok, true);
  assert.equal(s.entities.filter(e => e.name.startsWith("Barrel")).length, 0, "the barrels are gone");
  assert.equal(res.data.report.removed.length, 3);
  assert.ok(E(s, door.id) && E(s, low.id), "the door and the portal end stay");
  assert.equal(res.data.kept.length, 2);
  assert.deepEqual(res.data.kept.map(k => k.why).sort(), ["door", "portal end"]);
  assert.ok(E(s, "mara"), "people stay");
  assert.ok(E(s, "table"), "objects outside the region stay");
  assert.equal(World10.portalPartner(s, high), low, "the far stair and its link stay");
  assert.equal(s.objectTemplates.length, templates, "templates stay");
});

test("clear_region with what \"clutter\" takes the doors and stairs too", () => {
  const s = world();
  T.TOOLS.place_objects.run(s, {templateId: "tpl_barrel", regionId: "inn", count: 1}, set);
  const door = World10.hangDoor(s, World10.doorways(s).find(d => d.room === R(s, "inn")), "door", set);
  const pre = T.preview(s, {tool: "clear_region", args: {regionId: "inn", what: "clutter"}});
  assert.ok(pre.includes("Door 1"), "the preview lists the door among the removals");
  const res = T.TOOLS.clear_region.run(s, {regionId: "inn", what: "clutter"}, set);
  assert.equal(res.ok, true);
  assert.equal(s.entities.filter(e => e.name.startsWith("Barrel") || e.name.startsWith("Door")).length, 0);
  assert.deepEqual(res.data.kept, []);
  assert.ok(E(s, "mara"), "people still stay");
  assert.ok(!E(s, door.id), "the door object is gone");
});

// ---------------------------------------------------------------- add_level, link_portal
test("add_level adds a floor, with linked stairs when asked", () => {
  const s = world();
  const res = T.TOOLS.add_level.run(s, {buildingId: "inn", stairsTemplateId: "tpl_stairs"}, set);
  assert.equal(res.ok, true);
  const floor = R(s, res.data.floorId);
  assert.ok(floor, "the floor region exists");
  assert.equal(floor.pocket.anchor, "inn");
  assert.equal(floor.pocket.level, res.data.floorLevel);
  assert.equal(res.data.floorLevel, 1, "the first free level");
  assert.equal(floor.name, "Inn, floor 1");
  assert.equal(floor.wall, "brick");
  assert.equal(res.data.stairIds.length, 2);
  const [a, b] = res.data.stairIds.map(id => E(s, id));
  assert.ok(a && b, "both stair objects exist");
  assert.deepEqual([a.name, b.name], ["Stairs 1", "Stairs 2"]);
  assert.ok(M.inRect(M.rect(R(s, "inn")), a.pos[0], a.pos[1]), "one stair in the building");
  assert.ok(M.inRect(M.rect(floor), b.pos[0], b.pos[1]), "one on the new floor");
  assert.equal(World10.portalPartner(s, a), b);
  assert.equal(World10.portalPartner(s, b), a);
  assert.match(res.summary, /linked stairs/);

  const plain = T.TOOLS.add_level.run(s, {buildingId: "house"}, set);
  assert.equal(plain.ok, true);
  const loft = R(s, plain.data.floorId);
  assert.ok(loft && loft.pocket.anchor === "house" && loft.pocket.level === 1);
  assert.equal(loft.name, "House, floor 1");
  assert.ok(!plain.data.stairIds, "no stairs placed");
  assert.match(plain.summary, /unreachable until stairs/);
  const open = T.TOOLS.add_level.run(s, {buildingId: "field"}, set);
  assert.equal(open.ok, false);
  assert.match(open.error, /walls/);
});

test("link_portal pairs two objects and refuses a door", () => {
  const s = world();
  const barrel = M.placeObject(s, s.objectTemplates.find(t => t.id === "tpl_barrel"), 20, 16, set);
  const res = T.TOOLS.link_portal.run(s, {aId: "table", bId: barrel.id}, set);
  assert.equal(res.ok, true);
  assert.equal(World10.portalPartner(s, E(s, "table")), barrel);
  assert.equal(World10.portalPartner(s, barrel), E(s, "table"));
  assert.match(res.summary, /Table 1/);
  assert.match(res.summary, /Barrel 1/);
  const door = World10.hangDoor(s, World10.doorways(s).find(d => d.room === R(s, "inn")), "door", set);
  const refused = T.TOOLS.link_portal.run(s, {aId: door.id, bId: barrel.id}, set);
  assert.equal(refused.ok, false);
  assert.match(refused.error, /door/i);
});

// ---------------------------------------------------------------- rename_thing
test("rename_thing renames a region and the blocks and events that name it", () => {
  const s = world();
  const res = T.TOOLS.rename_thing.run(s, {id: "field", name: "Meadow"}, set);
  assert.equal(res.ok, true);
  assert.equal(R(s, "field").name, "Meadow");
  assert.equal(E(s, "cow").schedule[0].location, "Meadow");
  assert.equal(s.calendar[0].location, "Meadow");
  assert.equal(res.data.mentions, 2, "the cow's block and the calendar event");
  assert.equal(T.TOOLS.rename_thing.run(s, {id: "field", name: "House"}, set).ok, false, "duplicate name");
  assert.equal(T.TOOLS.rename_thing.run(s, {id: "field", name: "   "}, set).ok, false, "empty name");
  assert.equal(T.TOOLS.rename_thing.run(s, {id: "cow", name: "Bessie"}, set).ok, true);
  assert.equal(E(s, "cow").name, "Bessie");
});

// ---------------------------------------------------------------- registry shape and bad input
test("promptLines lists the registry; the destructive tools are flagged and lines stay short", () => {
  assert.deepEqual(Object.keys(T.TOOLS), ["find", "get_region", "get_person", "list_object_templates", "edit_texts",
    "add_npcs", "update_npc", "remove_npc", "remove_object", "place_objects", "create_room", "create_building",
    "furnish_region", "clear_region", "add_level", "link_portal", "rename_thing",
    "rebuild_building", "redress_zone", "populate_zone"]);
  const lines = T.promptLines();
  assert.equal(lines.length, Object.keys(T.TOOLS).length);
  for (const l of lines) {
    assert.match(l, /^\S+ — .+ — .+$/);
    assert.ok(l.length < 400, l.split(" — ")[0] + " is " + l.length + " characters");
  }
  assert.match(lines.find(l => l.startsWith("furnish_region")), /wall:<side>/, "the hint vocabulary is on the line");
  assert.deepEqual(Object.keys(T.TOOLS).filter(k => T.TOOLS[k].destructive), ["remove_npc", "remove_object", "clear_region"]);
});

// ---------------------------------------------------------------- the server tools
test("the rebuild tools are server tools: flagged, kind-mapped, args checked, never local", () => {
  const server = Object.keys(T.TOOLS).filter(k => T.TOOLS[k].server);
  assert.deepEqual(server, ["rebuild_building", "redress_zone", "populate_zone"]);
  assert.deepEqual(server.map(k => T.TOOLS[k].kind), ["building", "redress_zone", "populate_zone"]);
  assert.deepEqual(server.map(k => T.TOOLS[k].targetArg), ["building", "zone", "zone"]);
  assert.ok(server.every(k => !T.TOOLS[k].destructive), "their dialog is the confirmation");
  const lines = T.promptLines();
  for (const name of server)
    assert.match(lines.find(l => l.startsWith(name)), /exact name/, name + " says the target is exact");
  // good args answer that the work happens on the server — run is never the rebuild itself
  const s = world();
  for (const [name, args] of [
    ["rebuild_building", {building: "Inn", instruction: "a warmer taproom"}],
    ["rebuild_building", {building: "Inn", instruction: "a warmer taproom", seed: 7}],
    ["redress_zone", {zone: "Field", instruction: "market stalls"}],
    ["populate_zone", {zone: "Field", instruction: "two farmhands", quota: 2}],
  ]) {
    const res = T.TOOLS[name].run(s, args, set);
    assert.equal(res.ok, false, name);
    assert.match(res.error, /server/, name);
  }
  assert.deepEqual(s, world(), "nothing local was touched");
});

test("preview words the destructive actions from a previewDelete report", () => {
  const s = world();
  assert.equal(T.preview(s, {tool: "find", args: {query: "x"}}), null, "not destructive");
  assert.match(T.preview(s, {tool: "remove_npc", args: {id: "cow"}}), /^Remove "Cow" \(npc\)\.$/);
  assert.equal(T.preview(s, {tool: "remove_npc", args: {id: "nope"}}), null, "nothing to remove");
});

test("every tool answers {ok: false, error} on bad input and never throws", () => {
  const s = world();
  const cases = [
    ["find", {}], ["find", {query: ""}], ["find", {query: 7}],
    ["get_region", {}], ["get_region", {id: "nope"}], ["get_region", {id: 4}],
    ["get_person", {}], ["get_person", {id: "nope"}], ["get_person", {id: "table"}],
    ["edit_texts", {}], ["edit_texts", {edits: []}], ["edit_texts", {edits: 3}],
    ["add_npcs", {}], ["add_npcs", {npcs: []}], ["add_npcs", {npcs: "x"}],
    ["add_npcs", {npcs: [{name: "A", homeRegionId: "nope"}]}],
    ["add_npcs", {npcs: [{name: "A", homeRegionId: "inn", shift: "dawn"}]}],
    ["add_npcs", {npcs: [{name: "A", homeRegionId: "inn", gender: "robot"}]}],
    ["update_npc", {}], ["update_npc", {id: "nope", description: "x"}], ["update_npc", {id: "cow", nope: 1}],
    ["update_npc", {id: "cow", description: 5}],
    ["remove_npc", {}], ["remove_npc", {id: "nope"}], ["remove_npc", {id: "table"}],
    ["remove_object", {}], ["remove_object", {id: "cow"}],
    ["place_objects", {}], ["place_objects", {templateId: "tpl_barrel", regionId: "field", count: 0}],
    ["place_objects", {templateId: "tpl_barrel", regionId: "field", count: 11}],
    ["place_objects", {templateId: "tpl_barrel", regionId: "field", count: 1.5}],
    ["place_objects", {templateId: "nope", regionId: "field", count: 1}],
    ["place_objects", {templateId: "tpl_barrel", regionId: "nope", count: 1}],
    ["rename_thing", {}], ["rename_thing", {id: "nope", name: "X"}], ["rename_thing", {id: "field"}],
    ["create_room", {}], ["create_room", {name: "X"}], ["create_room", {name: "X", x: 0, y: 0, w: 0, h: 5}],
    ["create_room", {name: "X", x: 0, y: 0, w: 5, h: 41}], ["create_room", {name: "X", x: 0, y: 0, w: 1.5, h: 5}],
    ["create_room", {name: "X", x: 0, y: 0, w: 3, h: 3, wall: "glass"}],
    ["create_room", {name: "X", x: 0, y: 0, w: 3, h: 3, wall: "wood", doors: "s"}],
    ["create_room", {name: "X", x: 0, y: 0, w: 3, h: 3, wall: "wood", doors: ["s", "s"]}],
    ["create_room", {name: "X", x: 0, y: 0, w: 3, h: 3, doors: ["s"]}],
    ["furnish_region", {}], ["furnish_region", {regionId: "inn"}],
    ["furnish_region", {regionId: "nope", items: [{templateId: "tpl_barrel", count: 1}]}],
    ["furnish_region", {regionId: "inn", items: [{templateId: "tpl_barrel", count: 0}]}],
    ["furnish_region", {regionId: "inn", items: [{templateId: "tpl_barrel", count: 13}]}],
    ["furnish_region", {regionId: "inn", items: [{templateId: "tpl_barrel", count: 1, hint: 5}]}],
    ["furnish_region", {regionId: "inn", items: [{templateId: "tpl_barrel", count: 1, hint: "x".repeat(81)}]}],
    ["furnish_region", {regionId: "inn", items: Array.from({length: 13}, () => ({templateId: "tpl_barrel", count: 1}))}],
    ["clear_region", {}], ["clear_region", {regionId: "nope"}], ["clear_region", {regionId: "inn", what: "all"}],
    ["add_level", {}], ["add_level", {buildingId: "nope"}], ["add_level", {buildingId: "field"}],
    ["add_level", {buildingId: "inn", stairsTemplateId: "nope"}], ["add_level", {buildingId: "inn", level: 0.5}],
    ["add_level", {buildingId: "inn", name: 5}],
    ["link_portal", {}], ["link_portal", {aId: "table"}], ["link_portal", {aId: "nope", bId: "table"}],
    ["link_portal", {aId: "cow", bId: "table"}],
    ["rebuild_building", {}], ["rebuild_building", {building: "Inn"}],
    ["rebuild_building", {building: "Inn", instruction: ""}],
    ["rebuild_building", {building: 4, instruction: "x"}],
    ["rebuild_building", {building: "Inn", instruction: "x", seed: "later"}],
    ["rebuild_building", {building: "Inn", instruction: "x".repeat(1001)}],
    ["redress_zone", {}], ["redress_zone", {zone: "Field"}],
    ["redress_zone", {zone: "Field", instruction: "x", seed: 1.5}],
    ["populate_zone", {}], ["populate_zone", {zone: "Field", instruction: "x", quota: "two"}],
  ];
  for (const [name, args] of cases) {
    let res;
    assert.doesNotThrow(() => { res = T.TOOLS[name].run(s, args, set); }, name + " " + snap(args));
    assert.equal(res.ok, false, name + " " + snap(args));
    assert.ok(typeof res.error === "string" && res.error.length > 0, name + " says why");
  }
  for (const name of Object.keys(T.TOOLS))
    assert.doesNotThrow(() => T.TOOLS[name].run(s, null, set), name + " with null args");
});
