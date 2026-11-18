"use strict";
// node --test test/      (from tools/scenario-editor)
const test = require("node:test");
const assert = require("node:assert/strict");
const R = require("../rooms.js");

const ROLES = {"seat.lounge": "#ea8a6c", seat: "#b8860b", "table.dining": "#6c6cbe", "*": "#9e9e9e"};

test("roleColor takes the first prefix that names the role, else the default", () => {
  assert.equal(R.roleColor(ROLES, "seat"), "#b8860b");            // not seat.lounge: seat comes later
  assert.equal(R.roleColor(ROLES, "seat.long"), "#b8860b");       // a "seat." child, not the exact one
  assert.equal(R.roleColor(ROLES, "seat.lounge"), "#ea8a6c");     // the exact prefix wins
  assert.equal(R.roleColor(ROLES, "table.dining"), "#6c6cbe");
  assert.equal(R.roleColor(ROLES, "table.small"), "#9e9e9e");     // no table prefix listed
  assert.equal(R.roleColor(ROLES, "wash"), "#9e9e9e");
  assert.equal(R.roleColor(ROLES, ""), "#9e9e9e");
});

test("darker multiplies each channel and clamps, truncating like the sheet", () => {
  assert.equal(R.darker("#ff0000", 0.5), "#7f0000");   // int(255 * 0.5), as the sheet's _darker
  assert.equal(R.darker("#6c6cbe", 0.55), "#3b3b68");
  assert.equal(R.darker("#102030", 3), "#306090");
  assert.equal(R.darker("#ffffff", 0), "#000000");
});

test("shortRole keeps the role's first word", () => {
  assert.equal(R.shortRole("sleep.couple"), "sleep");
  assert.equal(R.shortRole("bedside"), "bedside");
  assert.equal(R.shortRole(""), "");
});

test("filterRooms applies band, clearance, style, tier and search", () => {
  const rooms = [
    {id: "bed.a", sizeBand: "medium", clearance: "tight", style: "flush",
     wealth: ["poor", "modest"], description: "a plain room"},
    {id: "bed.b", sizeBand: "large", clearance: "roomy", style: "open",
     wealth: ["wealthy", "elite"], description: "a grand suite"},
    {id: "bed.c", sizeBand: "medium", clearance: "roomy", style: "flush",
     wealth: ["modest", "wealthy"], description: "a plain room"},
  ];
  assert.deepEqual(R.filterRooms(rooms, {}), rooms);
  assert.deepEqual(R.filterRooms(rooms, {band: "medium"}), [rooms[0], rooms[2]]);
  assert.deepEqual(R.filterRooms(rooms, {clearance: "roomy"}), [rooms[1], rooms[2]]);
  assert.deepEqual(R.filterRooms(rooms, {style: "open"}), [rooms[1]]);
  assert.deepEqual(R.filterRooms(rooms, {tier: "wealthy"}), [rooms[1], rooms[2]]);
  assert.deepEqual(R.filterRooms(rooms, {search: "GRAND"}), [rooms[1]]);       // description, case-insensitive
  assert.deepEqual(R.filterRooms(rooms, {search: "bed."}), rooms);              // id substring
  assert.deepEqual(R.filterRooms(rooms, {band: "large", tier: "poor"}), []);
});

test("fitPlan centres the biggest cell that fits", () => {
  assert.deepEqual(R.fitPlan(7, 5, 400, 300, 26), {cell: 49, ox: 29, oy: 28});
  const wide = R.fitPlan(20, 3, 200, 100, 10);   // width-bound
  assert.equal(wide.cell, 9);
  assert.equal(wide.ox, 10);
  assert.deepEqual(R.fitPlan(300, 2, 200, 100, 10), {cell: 1, ox: -50, oy: 49});  // wider than the box: clips
});

test("doorCells walks the sides in north/south/east/west order", () => {
  assert.deepEqual(R.doorCells({doors: {north: [0, 2], west: [1]}}),
                   [{side: "north", k: 0}, {side: "north", k: 2}, {side: "west", k: 1}]);
  assert.deepEqual(R.doorCells({}), []);
  assert.deepEqual(R.doorCells(), []);
});

test("stretchLines fills in the missing axes", () => {
  assert.deepEqual(R.stretchLines({stretch: {x: [3]}}), {x: [3], y: []});
  assert.deepEqual(R.stretchLines({}), {x: [], y: []});
});

test("groupBoxes clusters touching pieces of one group, as fixed_rooms.instances does", () => {
  const room = {pieces: [
    {role: "sleep", at: [0, 0], size: [1, 2], group: "g"},
    {role: "bedside", at: [1, 0], size: [1, 1], group: "g"},       // touches the bed
    {role: "seat", at: [5, 0], size: [2, 1], group: "g"},          // same group, apart: its own instance
    {role: "storage", at: [0, 3], size: [1, 1], group: "h"},
  ]};
  assert.deepEqual(R.groupBoxes(room), [
    {gid: "g", indices: [0, 1], box: [0, 0, 2, 2]},
    {gid: "g", indices: [2], box: [5, 0, 2, 1]},
    {gid: "h", indices: [3], box: [0, 3, 1, 1]},
  ]);
  // a corner touch shares an edge for the generator's _touch, so it clusters
  assert.deepEqual(R.groupBoxes({pieces: [
    {at: [0, 0], size: [1, 1], group: "a"},
    {at: [1, 1], size: [1, 1], group: "a"},
  ]}), [{gid: "a", indices: [0, 1], box: [0, 0, 2, 2]}]);
  // pieces without a group share one gid (undefined), so touching ones still
  // cluster — exactly what fixed_rooms.instances does with its None gid
  assert.deepEqual(R.groupBoxes({pieces: [
    {at: [0, 0], size: [1, 1]}, {at: [1, 0], size: [1, 1]},
  ]}), [{gid: undefined, indices: [0, 1], box: [0, 0, 2, 1]}]);
  assert.equal(R.groupBoxes({pieces: [
    {at: [0, 0], size: [1, 1]}, {at: [3, 0], size: [1, 1]},
  ]}).length, 2);
});

test("pieceAt finds the topmost piece on a cell", () => {
  const room = {pieces: [
    {at: [0, 0], size: [2, 1]},
    {at: [0, 1], size: [1, 1]},
  ]};
  assert.equal(R.pieceAt(room, 1, 0), 0);
  assert.equal(R.pieceAt(room, 0, 1), 1);
  assert.equal(R.pieceAt(room, 5, 5), -1);
  assert.equal(R.pieceAt({}, 0, 0), -1);
});
