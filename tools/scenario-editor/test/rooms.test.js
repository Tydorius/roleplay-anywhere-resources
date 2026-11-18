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


// ------------------------------------------------------------- hand work (rl-04b)

const ROOM = {
  id: "bedroom.small.a.tight.flush", family: "bedroom", sizeBand: "small",
  clearance: "tight", style: "flush", wealth: ["poor", "modest"],
  size: [5, 3], sleeps: {singles: 1, couples: 0},
  pieces: [
    {role: "sleep", size: [1, 2], at: [0, 0], group: "g.bed", back: "north"},
    {role: "bedside", size: [1, 1], at: [1, 0], group: "g.bed"},
    {role: "storage.big", size: [1, 2], at: [4, 0], group: "g.chest", back: "east"},
  ],
  doors: {north: [2, 3], south: [0, 1, 2, 3, 4], west: [2], east: [2]},
  stretch: {}, outdoor: false, symmetric: false,
  recipe: "bedroom.small.a", description: "A room.",
};

test("letterAt finds a room id's letter after the family parts and the band", () => {
  assert.equal(R.letterAt("bedroom.small.a.tight.flush", 1), "a");
  assert.equal(R.letterAt("bedroom.master.small.b.tight.flush", 2), "b");
  assert.equal(R.letterAt("bedroom.master.small.a.tight.flush", 1), null);  // wrong part count
  assert.equal(R.letterAt("", 1), null);
  assert.equal(R.letterAt(null, 1), null);
});

test("nextLetter takes the first free letter, newId the next free id of a group", () => {
  assert.equal(R.nextLetter(["a", "b"]), "c");
  assert.equal(R.nextLetter([]), "a");
  assert.equal(R.nextLetter("abcdefghijklmnopqrstuvwxyz".split("")), null);
  const ids = ["bedroom.master.small.a.tight.flush",
               "bedroom.master.small.b.tight.flush",
               "bedroom.master.large.a.tight.flush",     // another band: not this group
               "bedroom.small.a.tight.flush"];           // another family: never counted
  assert.equal(R.newId("bedroom.master", "small", "tight", "flush", ids),
               "bedroom.master.small.c.tight.flush");
  assert.equal(R.newId("bedroom", "small", "tight", "flush",
                       ["bedroom.small.a.tight.flush"]),
               "bedroom.small.b.tight.flush");
});

test("cloneRoom copies a room under a new id as hand work, without bookkeeping", () => {
  const copy = R.cloneRoom({...ROOM, errors: ["room 'x': something"]},
                           "bedroom.small.z.tight.flush");
  const want = JSON.parse(JSON.stringify(ROOM));
  want.id = "bedroom.small.z.tight.flush";
  want.source = "hand";                 // and no errors key: the bookkeeping is gone
  assert.deepEqual(copy, want);
});

test("turnGroup turns one group a clockwise quarter about its own box", () => {
  const out = R.turnGroup(ROOM, 0);                   // the bed and its bedside
  assert.deepEqual(out.pieces[0], {role: "sleep", size: [2, 1], at: [0, 0],
                                   group: "g.bed", back: "east"});
  assert.deepEqual(out.pieces[1], {role: "bedside", size: [1, 1], at: [1, 1],
                                   group: "g.bed"});
  assert.deepEqual(out.pieces[2], ROOM.pieces[2], "the chest keeps its place");
  assert.deepEqual(R.turnGroup(ROOM, 9).pieces, ROOM.pieces);   // no such group: unchanged
  assert.notEqual(out, ROOM, "a new room, not a mutation");
  assert.deepEqual(ROOM.pieces[0].size, [1, 2], "the input stands");
});

test("moveGroup shifts one group whole, removeGroup takes its pieces out", () => {
  const moved = R.moveGroup(ROOM, 0, 2, 1);
  assert.deepEqual(moved.pieces[0].at, [2, 1]);
  assert.deepEqual(moved.pieces[1].at, [3, 1]);
  assert.deepEqual(moved.pieces[2].at, [4, 0], "the chest stays");
  assert.deepEqual(ROOM.pieces[0].at, [0, 0], "the input stands");
  const gone = R.removeGroup(ROOM, 1);
  assert.deepEqual(gone.pieces.map(p => p.group), ["g.bed", "g.bed"]);
  assert.deepEqual(R.removeGroup(ROOM, 0).pieces.map(p => p.group), ["g.chest"]);
});

test("groupForm shifts a definition to the origin keeping sizes, backs and optionals", () => {
  const form = R.groupForm({pieces: [
    {role: "seat", size: [2, 1], at: [3, 4], back: "north"},
    {role: "table.small", size: [1, 1], at: [4, 5], optional: true},
  ]});
  assert.deepEqual(form, [
    {role: "seat", size: [2, 1], at: [0, 0], back: "north"},
    {role: "table.small", size: [1, 1], at: [1, 1], optional: true},
  ]);
  assert.deepEqual(R.groupForm({}), []);
  assert.deepEqual(R.groupForm({pieces: [{role: "x", size: [1, 1], at: [2, 2]}]}),
                   [{role: "x", size: [1, 1], at: [0, 0]}]);
});

test("addGroup stamps a definition's pieces in at x, y under its group id", () => {
  const out = R.addGroup(ROOM, {id: "g.seat", pieces: [
    {role: "seat", size: [2, 1], at: [3, 4], back: "north"},
  ]}, 2, 2);
  assert.equal(out.pieces.length, 4);
  assert.deepEqual(out.pieces[3], {role: "seat", size: [2, 1], at: [2, 2],
                                   back: "north", group: "g.seat"});
  assert.deepEqual(ROOM.pieces.length, 3, "the input stands");
});

test("growRoom rides wall-bound groups out and shifts the rest", () => {
  const north = R.growRoom(ROOM, "north", 1);
  assert.deepEqual(north.size, [5, 4]);
  assert.deepEqual(north.pieces[0].at, [0, 0], "the north-backed bed rides its wall");
  assert.deepEqual(north.pieces[1].at, [1, 1]);
  assert.deepEqual(north.pieces[2].at, [4, 1], "the east-backed chest shifts with the far wall");
  const south = R.growRoom(ROOM, "south", 1);
  assert.deepEqual(south.size, [5, 4]);
  assert.deepEqual(south.pieces.map(p => p.at), ROOM.pieces.map(p => p.at));
  const west = R.growRoom(ROOM, "west", 2);
  assert.deepEqual(west.size, [7, 3]);
  assert.deepEqual(west.pieces.map(p => p.at),
                   [[2, 0], [3, 0], [6, 0]], "nothing backs west: everything shifts");
});

test("shrinkRoom refuses a line a piece or the filler stands on", () => {
  const south = R.shrinkRoom(ROOM, "south", 1);
  assert.deepEqual(south.size, [5, 2]);
  assert.deepEqual(south.pieces.map(p => p.at), ROOM.pieces.map(p => p.at));
  assert.equal(R.shrinkRoom(ROOM, "east", 1), null);   // the chest hugs the east wall
  assert.equal(R.shrinkRoom(ROOM, "north", 1), null);  // the bed hugs the north wall
  const rug = JSON.parse(JSON.stringify(ROOM));
  rug.filler = {at: [1, 2], size: [2, 1]};
  assert.equal(R.shrinkRoom(rug, "south", 1), null);   // the filler stands on the south line
  const low = JSON.parse(JSON.stringify(ROOM));        // one piece off every wall
  low.pieces = [{role: "seat", size: [1, 1], at: [1, 1], group: "g.s", back: "north"}];
  const north = R.shrinkRoom(low, "north", 1);
  assert.deepEqual(north.size, [5, 2]);
  assert.deepEqual(north.pieces[0].at, [1, 0], "the rest shifts up with the wall");
  const west = R.shrinkRoom(low, "west", 1);
  assert.deepEqual(west.size, [4, 3]);
  assert.deepEqual(west.pieces[0].at, [0, 1]);
});

test("mergeLayout takes a candidate's layout but keeps the id and edited fields", () => {
  const room = {...JSON.parse(JSON.stringify(ROOM)),
                edited: ["description"], description: "Mine, not the generator's."};
  const cand = {size: [6, 4], sizeBand: "small",
                sleeps: {singles: 0, couples: 1}, pieces: [], doors: {}, stretch: {},
                wealth: ["wealthy", "elite"], description: "A generated room."};
  const out = R.mergeLayout(room, cand);
  assert.equal(out.id, ROOM.id);
  assert.deepEqual(out.size, [6, 4]);
  assert.deepEqual(out.sleeps, {singles: 0, couples: 1});
  assert.deepEqual(out.wealth, ["wealthy", "elite"], "an unedited field follows the candidate");
  assert.equal(out.description, "Mine, not the generator's.", "an edited field keeps its hand value");
  assert.equal(out.source, "hand");
  assert.equal(out.errors, undefined);
  const fresh = R.mergeLayout(ROOM, cand);
  assert.equal(fresh.description, "A generated room.", "with no edits the candidate's text lands");
});

test("setField flags a hand field edited, resetField drops the flag", () => {
  const room = JSON.parse(JSON.stringify(ROOM));
  R.setField(room, "retired", true);
  assert.equal(room.retired, true);
  assert.deepEqual(room.edited, ["retired"]);
  R.setField(room, "description", "By hand.");
  R.setField(room, "description", "By hand, again.");   // no double flag
  assert.deepEqual(room.edited, ["retired", "description"]);
  R.resetField(room, "retired");
  assert.deepEqual(room.edited, ["description"]);
  assert.equal(room.retired, true, "the value stands until regeneration");
  R.resetField(room, "description");
  assert.equal(room.edited, undefined);
});

test("parseCells outlines the cells the checker's messages name", () => {
  const room = JSON.parse(JSON.stringify(ROOM));
  room.filler = {at: [1, 1], size: [2, 1]};
  const cells = R.parseCells(room, [
    "3 dead floor cell(s) (first at 2,0): more than 1 cells from every piece",
    "room 'bedroom.small.a.tight.flush': door cell west 1 blocked by a piece",
    "room 'bedroom.small.a.tight.flush': piece 'sleep' at [0, 0] of group 'sleep.bedside' has no free reached cell among its access cells [[3, 2], [4, 1]] (needs 1)",
    "room 'bedroom.small.a.tight.flush': filler at [1, 1] is off centre",
    "room 'bedroom.small.a.tight.flush': stretch x 2 runs through a piece",
    "room 'bedroom.small.a.tight.flush': 9 dead floor cell(s) (first at 9,9)",
  ]);
  const want = [[0, 0], [0, 1],          // the bed piece at 0,0, door cell west 1
                [1, 1], [2, 1],          // the filler at 1,1
                [3, 2], [4, 1],          // the named access cells
                [2, 0], [2, 2]];         // dead floor at 2,0, the stretch column x 2
  const got = cells.map(c => c.join(",")).sort();
  assert.deepEqual(got, want.map(c => c.join(",")).sort());
  assert.deepEqual(R.parseCells(ROOM, []), []);
  assert.deepEqual(R.parseCells(ROOM, null), []);
});

test("removableGids lists the recipe's optional groups and the family's pool", () => {
  const data = {recipes: [{layout: "bedroom.small.a", groups: [
    {group: "g.bed", kind: "anchor"},
    {group: "g.desk", kind: "optional"},
    {group: "g.bed2", kind: "repeatable"},
  ]}], pool: [{group: "g.lux"}, {group: "g.lux2"}]};
  assert.deepEqual([...R.removableGids(ROOM, data)], ["g.desk", "g.lux", "g.lux2"]);
  assert.deepEqual([...R.removableGids({...ROOM, recipe: "no.such"}, data)],
                   ["g.lux", "g.lux2"]);
  assert.deepEqual([...R.removableGids(ROOM, {})], []);
});

test("shortRole takes the last word for washroom fixtures and shared first words", () => {
  assert.equal(R.shortRole("wash.toilet", ["wash.toilet"]), "toilet");   // never "wash"
  assert.equal(R.shortRole("wash.basin", ["wash.toilet", "wash.basin"]), "basin");
  // two storage roles in one room are told apart by their last word
  assert.equal(R.shortRole("storage.big", ["storage.big", "storage.small"]), "big");
  assert.equal(R.shortRole("storage.small", ["storage.big", "storage.small"]), "small");
  // sleep beside sleep.couple: the bare role keeps its only word
  assert.equal(R.shortRole("sleep", ["sleep", "sleep.couple"]), "sleep");
  assert.equal(R.shortRole("sleep.couple", ["sleep", "sleep.couple"]), "couple");
  // the same role twice is not ambiguous
  assert.equal(R.shortRole("storage.big", ["storage.big", "storage.big"]), "storage");
  // without the room's roles the wash rule stands, the rest keep the first word
  assert.equal(R.shortRole("wash.bath"), "bath");
  assert.equal(R.shortRole("storage.big"), "storage");
});

test("addGroupSections orders removed, recipe, pool and the rest", () => {
  const all = [
    {id: "g.bed", file: "bedroom.json", pieces: []},
    {id: "g.desk", file: "bedroom.json", pieces: []},
    {id: "g.fire", file: "bedroom.json", pieces: []},
    {id: "g.lux", file: "luxury.json", pieces: []},
    {id: "g.other", file: "washroom.json", pieces: []},
  ];
  const groupsData = {
    recipes: [{layout: "L", groups: [{group: "g.bed", kind: "anchor"},
                                     {group: "g.desk", kind: "optional"},
                                     {group: "g.fire", kind: "optional"}]}],
    pool: [{group: "g.lux", bands: ["medium"]}],
  };
  const start = {recipe: "L", pieces: [{group: "g.bed", at: [0, 0]},
                                       {group: "g.fire", at: [2, 0]}]};
  const draft = {recipe: "L", pieces: [{group: "g.bed", at: [0, 0]}]};
  const sections = R.addGroupSections(all, draft, start, groupsData);
  assert.deepEqual(sections.map(s => s.title),
                   ["Removed from this room", "The recipe's groups",
                    "The family's luxury pool", "All other groups"]);
  assert.deepEqual(sections[0].rows.map(r => r.gid), ["g.fire"]);
  // groups already in the room stay listed: a second instance is how a
  // repeatable group gets another go
  assert.deepEqual(sections[1].rows.map(r => r.gid), ["g.bed", "g.desk"]);
  assert.deepEqual(sections[2].rows.map(r => r.gid), ["g.lux"]);
  assert.deepEqual(sections[3].rows.map(r => r.gid), ["g.other"]);
  assert.deepEqual(sections[1].rows[0].file, "bedroom.json");
});

test("addGroupSections keeps a group to its first section and drops empty ones", () => {
  const all = [{id: "g.x", file: "f.json", pieces: []},
               {id: "g.y", file: "f.json", pieces: []}];
  const groupsData = {recipes: [{layout: "L", groups: [{group: "g.x", kind: "anchor"}]}],
                      pool: [{group: "g.x"}]};                    // pool names it too: recipe wins
  const sections = R.addGroupSections(all, {recipe: "L", pieces: []}, {pieces: []}, groupsData);
  assert.deepEqual(sections.map(s => s.title), ["The recipe's groups", "All other groups"]);
  assert.deepEqual(sections[0].rows.map(r => r.gid), ["g.x"]);
  assert.deepEqual(sections[1].rows.map(r => r.gid), ["g.y"]);
});

test("firstFreeSpot scans reading order and skips blocked cells", () => {
  const room = {size: [4, 3], pieces: [
    {role: "sleep", size: [2, 1], at: [0, 0]},
    {role: "seat", size: [1, 1], at: [1, 1]},
  ]};
  const two = {id: "g", pieces: [{role: "seat", size: [2, 1], at: [0, 0]}]};
  assert.deepEqual(R.firstFreeSpot(room, two), [2, 0]);           // row 0 after the bed
  const one = {id: "g", pieces: [{role: "seat", size: [1, 1], at: [0, 0]}]};
  assert.deepEqual(R.firstFreeSpot(room, one), [2, 0]);
  assert.deepEqual(R.firstFreeSpot({...room, pieces: [
    {role: "sleep", size: [4, 1], at: [0, 0]},
    {role: "sleep", size: [4, 1], at: [0, 2]},
  ]}, one), [0, 1]);                                              // the middle row
  assert.deepEqual(R.firstFreeSpot({size: [1, 1], pieces: []}, two), null);   // too small
  assert.deepEqual(R.firstFreeSpot(room, {id: "g", pieces: []}), null);       // nothing to place
});

test("filterGroupRows searches the id and the piece roles", () => {
  const rows = [{gid: "sleep.bed.big", file: "a.json", pieces: [{role: "sleep"}]},
                {gid: "wash.basin", file: "b.json", pieces: [{role: "wash.basin"}]}];
  assert.deepEqual(R.filterGroupRows(rows, ""), rows);
  assert.deepEqual(R.filterGroupRows(rows, "BED"), rows.slice(0, 1));   // id, case-insensitive
  assert.deepEqual(R.filterGroupRows(rows, "basin"), rows.slice(1));   // the role
  assert.deepEqual(R.filterGroupRows(rows, "toilet"), []);
});

test("layoutChanged sees any layout field differ", () => {
  const a = {size: [3, 3], pieces: [{role: "x"}], doors: {north: [0]}, stretch: {x: [1]}};
  const same = JSON.parse(JSON.stringify(a));
  assert.equal(R.layoutChanged(a, same), false);
  for (const change of [
    r => r.size = [4, 3],
    r => r.pieces.push({role: "y"}),
    r => r.doors = {south: [1]},
    r => r.stretch = {y: [0]},
    r => r.filler = {at: [0, 0], size: [1, 1]},
  ]) {
    const b = JSON.parse(JSON.stringify(a));
    change(b);
    assert.equal(R.layoutChanged(a, b), true);
  }
});

test("a ring cell's mark cycles none -> mandatory -> limited", () => {
  assert.equal(R.cycleAccessState(undefined), "mandatory");
  assert.equal(R.cycleAccessState("none"), "mandatory");
  assert.equal(R.cycleAccessState("mandatory"), "limited");
  assert.equal(R.cycleAccessState("limited"), "none");
});

test("marksFromAccess and accessFromMarks round-trip hand access entries", () => {
  const access = [
    {cells: [[1, 2]], need: 1, replaces: [0]},           // one cell: mandatory
    {cells: [[0, 3], [1, 3]], need: 1, replaces: [0]},   // a choice: limited
  ];
  const marks = R.marksFromAccess(access);
  assert.deepEqual(marks, {"1,2": "mandatory",
                           "0,3": "limited", "1,3": "limited"});
  const pieces = [{role: "sleep", size: [2, 2], at: [0, 0]}];
  assert.deepEqual(R.accessFromMarks(marks, pieces), access);
});

test("accessFromMarks joins each mark to the piece it stands nearest", () => {
  const pieces = [{role: "sleep", size: [2, 2], at: [0, 0]},
                  {role: "seat", size: [1, 1], at: [3, 0]}];
  assert.deepEqual(R.accessFromMarks({"2,1": "limited", "4,1": "mandatory"}, pieces), [
    {cells: [[2, 1]], need: 1, replaces: [0]},   // leans on the bed
    {cells: [[4, 1]], need: 1, replaces: [1]},   // leans on the seat
  ]);
  assert.deepEqual(R.accessFromMarks({}, pieces), []);
});
