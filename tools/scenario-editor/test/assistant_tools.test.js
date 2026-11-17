"use strict";
// node --test test/      (from tools/scenario-editor)
const test = require("node:test");
const assert = require("node:assert/strict");
const T = require("../assistant_tools.js");
const M = require("../mapops.js");
const Refs = require("../refs.js");
const Schedule = require("../schedule.js");

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
test("promptLines lists the registry; only the remove tools are destructive", () => {
  assert.deepEqual(Object.keys(T.TOOLS), ["find", "get_region", "get_person", "list_object_templates", "edit_texts",
    "add_npcs", "update_npc", "remove_npc", "remove_object", "place_objects", "rename_thing"]);
  const lines = T.promptLines();
  assert.equal(lines.length, Object.keys(T.TOOLS).length);
  for (const l of lines) assert.match(l, /^\S+ — .+ — .+$/);
  assert.deepEqual(Object.keys(T.TOOLS).filter(k => T.TOOLS[k].destructive), ["remove_npc", "remove_object"]);
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
