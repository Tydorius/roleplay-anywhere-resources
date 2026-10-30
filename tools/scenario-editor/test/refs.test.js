"use strict";
// Tests for refs.js. Every test builds its own small scenario; nothing is shared.

const test = require("node:test");
const assert = require("node:assert/strict");
const Refs = require("../refs.js");
const Schedule = require("../schedule.js");

const {findRefs, forceDelete, previewDelete, renameEverywhere, findMentions, replaceMentions} = Refs;

const set = (o, k, v) => { if (v === undefined) delete o[k]; else o[k] = v; };

function reg(id, name, position, size, extra) {
  return Object.assign({id, name, position, size}, extra || {});
}
function block(start, end, location, role) {
  return {start, end, location, role};
}
function npc(id, name, schedule, extra) {
  return Object.assign({id, type: "npc", name, pos: [0, 0], schedule: schedule || []}, extra || {});
}
function player(id, name, schedule, extra) {
  return Object.assign({id, type: "player", name, pos: [0, 0], schedule: schedule || []}, extra || {});
}
function obj(id, name, pos, size, templateId, extra) {
  return Object.assign({id, type: "object", name, pos, size, templateId, inventory: [], statusEffects: []}, extra || {});
}
function stack(id, count, templateId) {
  return {id, count, templateId};
}
function baseScn(over) {
  return Object.assign({
    playerId: "pc",
    worldBackground: "",
    narrativeRules: [],
    regions: [],
    entities: [],
    objectTemplates: [],
    itemTemplates: [],
    hostileNpcTemplates: [],
    calendar: [],
    quests: []
  }, over || {});
}
function millScn() {
  return baseScn({
    regions: [
      reg("rVillage", "Village", [0, 0], [20, 20]),
      reg("rMill", "Mill", [2, 2], [4, 4]),
      reg("rMarket", "Market", [8, 2], [4, 4])
    ],
    entities: [
      npc("n1", "Miller", [
        block("00:00", "07:00", "Village", "sleep"),
        block("07:00", "12:00", "Mill", "work"),
        block("12:00", "13:00", "Village", "leisure"),
        block("13:00", "20:00", "Market", "work"),
        block("20:00", "00:00", "Village", "leisure")
      ])
    ]
  });
}
function templatesScn() {
  return baseScn({
    regions: [reg("r1", "Village", [0, 0], [20, 20])],
    itemTemplates: [{id: "itCoin", name: "Coin"}, {id: "itKey", name: "Key"}],
    objectTemplates: [
      {id: "otBarrel", name: "Barrel", lootPoolIds: ["itCoin"]},
      {id: "otChest", name: "Chest", lootPoolIds: ["itKey"], startingEffects: [
        {desc: "Rots away", endState: [
          {type: "spawnEntity", templateId: "otBarrel"},
          {type: "spawnItemOnSelf", item: {name: "Coin", quality: 1}}
        ]},
        {desc: "Burns", endState: [{type: "spawnEntity", templateId: "otBarrel"}]}
      ]}
    ],
    entities: [
      obj("eBarrel1", "Barrel", [1, 1], [1, 1], "otBarrel"),
      obj("eBarrel2", "Barrel", [2, 1], [1, 1], "otBarrel"),
      obj("eChest", "Chest", [3, 1], [1, 1], "otChest")
    ]
  });
}
function itemsScn() {
  return baseScn({
    regions: [reg("r1", "Village", [0, 0], [20, 20])],
    itemTemplates: [{id: "itCoin", name: "Coin"}, {id: "itKey", name: "Key"}],
    objectTemplates: [
      {id: "otBarrel", name: "Barrel", lootPoolIds: ["itCoin", "itKey"]},
      {id: "otShrine", name: "Shrine", startingEffects: [
        {desc: "Blesses", endState: [
          {type: "spawnItemOnSelf", item: {name: "Coin", quality: 2}},
          {type: "spawnItemOnSelf", item: {name: "Key", quality: 1}}
        ]}
      ]}
    ],
    hostileNpcTemplates: [{id: "h1", name: "Wolves", regionId: "r1", lootPoolIds: ["itCoin"]}],
    entities: [
      npc("n1", "Trader", [block("00:00", "00:00", "Village", "leisure")], {
        inventory: [stack("s1", 3, "itCoin"), stack("s2", 2, "itKey")],
        equipment: {hand: stack("s3", 1, "itCoin"), head: stack("s4", 1, "itKey")},
        merchant: {stock: [stack("s5", 5, "itCoin"), stack("s6", 1, "itKey")]}
      })
    ]
  });
}
function freezeArrays(value) {
  if (Array.isArray(value)) {
    for (const item of value) freezeArrays(item);
    return Object.freeze(value);
  }
  if (value && typeof value === "object") {
    for (const key of Object.keys(value)) freezeArrays(value[key]);
  }
  return value;
}

// ---- region deletion ----

test("deleting a region removes one schedule block and the previous block takes over", () => {
  const scn = millScn();
  const rep = forceDelete(scn, ["rMill"], {}, set);
  const miller = scn.entities.find(e => e.id === "n1");
  assert.ok(miller);
  assert.equal(miller.schedule.length, 4);
  assert.equal(miller.schedule[0].end, "12:00");
  assert.deepEqual(miller.schedule[1], block("12:00", "13:00", "Village", "leisure"));
  const names = scn.regions.map(r => r.name);
  assert.deepEqual(Schedule.validate(miller.schedule, names), []);
  assert.ok(!scn.regions.some(r => r.id === "rMill"));
  assert.deepEqual(rep.removed, [{id: "rMill", name: "Mill", kind: "region"}]);
  assert.ok(rep.changed.some(c => c.ownerId === "n1"));
});

test("a person whose every block is at the region ends with an empty schedule and a warning", () => {
  const scn = baseScn({
    regions: [reg("rVillage", "Village", [0, 0], [20, 20]), reg("rMill", "Mill", [2, 2], [4, 4])],
    entities: [npc("n1", "Miller", [
      block("00:00", "08:00", "Mill", "sleep"),
      block("08:00", "16:00", "Mill", "work"),
      block("16:00", "00:00", "Mill", "leisure")
    ])]
  });
  const rep = forceDelete(scn, ["rMill"], {}, set);
  const miller = scn.entities.find(e => e.id === "n1");
  assert.deepEqual(miller.schedule, []);
  assert.ok(rep.warnings.some(w => w.includes("Miller")));
  assert.ok(rep.changed.some(c => c.ownerId === "n1"));
});

test("scheduleMode move sends the blocks to the replacement region", () => {
  const scn = millScn();
  const rep = forceDelete(scn, ["rMill"], {scheduleMode: "move", replacementRegionId: "rMarket"}, set);
  const miller = scn.entities.find(e => e.id === "n1");
  assert.deepEqual(miller.schedule.map(b => b.location),
    ["Village", "Market", "Village", "Market", "Village"]);
  assert.equal(miller.schedule[1].start, "07:00");
  assert.equal(miller.schedule[1].end, "12:00");
  assert.ok(rep.changed.some(c => c.ownerId === "n1" && c.what.includes("Market")));
});

test("a calendar event at the region loses only its location", () => {
  const scn = millScn();
  scn.calendar = [{id: "ev1", name: "Festival", location: "Mill", missedConsequence: "The fair leaves."}];
  const rep = forceDelete(scn, ["rMill"], {}, set);
  const ev = scn.calendar[0];
  assert.equal(ev.name, "Festival");
  assert.equal(ev.missedConsequence, "The fair leaves.");
  assert.ok(!("location" in ev));
  assert.ok(rep.changed.some(c => c.ownerId === "ev1"));
});

test("a hostile type is rehomed and its placed npc's blocks move whatever scheduleMode says", () => {
  const scn = millScn();
  scn.hostileNpcTemplates = [{id: "h1", name: "Wolves", regionId: "rMill", lootPoolIds: []}];
  scn.entities.push(npc("w1", "Wolf", [
    block("00:00", "12:00", "Mill", "sleep"),
    block("12:00", "00:00", "Market", "work")
  ], {templateId: "h1", hostile: true}));
  const rep = forceDelete(scn, ["rMill"], {replacementRegionId: "rMarket", scheduleMode: "remove"}, set);
  assert.equal(scn.hostileNpcTemplates[0].regionId, "rMarket");
  assert.ok(rep.changed.some(c => c.ownerId === "h1"));
  const wolf = scn.entities.find(e => e.id === "w1");
  assert.equal(wolf.schedule[0].location, "Market");
  assert.equal(wolf.schedule[0].start, "00:00");
  assert.equal(wolf.schedule[1].location, "Market");
});

test("without a replacement the hostile type is deleted and its npc kept without templateId", () => {
  const scn = millScn();
  scn.hostileNpcTemplates = [{id: "h1", name: "Wolves", regionId: "rMill", lootPoolIds: []}];
  scn.entities.push(npc("w1", "Wolf", [
    block("00:00", "12:00", "Village", "sleep"),
    block("12:00", "00:00", "Mill", "work")
  ], {templateId: "h1", hostile: true}));
  const rep = forceDelete(scn, ["rMill"], {}, set);
  assert.deepEqual(scn.hostileNpcTemplates, []);
  const wolf = scn.entities.find(e => e.id === "w1");
  assert.ok(wolf);
  assert.ok(!("templateId" in wolf));
  assert.equal(wolf.hostile, true);
  assert.ok(rep.removed.some(r => r.id === "h1" && r.kind === "hostileType"));
  assert.ok(!rep.removed.some(r => r.id === "w1"));
  assert.ok(rep.changed.some(c => c.ownerId === "w1"));
  assert.equal(wolf.schedule.length, 1);
  assert.equal(wolf.schedule[0].location, "Village");
});

test("region contents are kept by default", () => {
  const scn = millScn();
  scn.regions.push(reg("rCell", "Cell", [3, 3], [1, 1]));
  scn.entities.push(obj("o1", "Barrel", [3, 3], [1, 1], "otBarrel"));
  const rep = forceDelete(scn, ["rMill"], {}, set);
  assert.ok(scn.regions.some(r => r.id === "rCell"));
  assert.ok(scn.entities.some(e => e.id === "o1"));
  assert.equal(rep.removed.length, 1);
});

test("deleteContents removes inner regions and objects but never people", () => {
  const scn = millScn();
  scn.regions.push(reg("rCell", "Cell", [3, 3], [1, 1]));
  scn.entities.push(obj("o1", "Barrel", [3, 3], [1, 1], "otBarrel"));
  scn.entities.push(npc("n2", "Villager", [block("00:00", "00:00", "Mill", "leisure")], {pos: [3, 3]}));
  const rep = forceDelete(scn, ["rMill"], {deleteContents: true}, set);
  assert.ok(!scn.regions.some(r => r.id === "rCell"));
  assert.ok(!scn.entities.some(e => e.id === "o1"));
  assert.ok(scn.entities.some(e => e.id === "n2"));
  const kinds = rep.removed.map(r => r.kind).sort();
  assert.deepEqual(kinds, ["object", "region", "region"]);
});

test("a replacement that is itself being deleted is treated as no replacement", () => {
  const scn = millScn();
  const rep = forceDelete(scn, ["rMill", "rMarket"], {replacementRegionId: "rMarket", scheduleMode: "move"}, set);
  assert.ok(rep.warnings.some(w => w.includes("replacement")));
  const miller = scn.entities.find(e => e.id === "n1");
  // "move" had no replacement left, so both the Mill and Market blocks were removed:
  // [Village, Village, Village] with the second block extended to 20:00.
  assert.equal(miller.schedule.length, 3);
  assert.equal(miller.schedule[0].end, "12:00");
  assert.equal(miller.schedule[1].end, "20:00");
  assert.ok(rep.warnings.some(w => w.includes("Miller")));
  assert.ok(!scn.regions.some(r => r.id === "rMarket"));
});

test("move without a replacement falls back to remove with a warning", () => {
  const scn = millScn();
  const rep = forceDelete(scn, ["rMill"], {scheduleMode: "move"}, set);
  const miller = scn.entities.find(e => e.id === "n1");
  assert.equal(miller.schedule.length, 4);
  assert.equal(miller.schedule[0].end, "12:00");
  assert.ok(rep.warnings.some(w => w.includes("instead of moving")));
});

// ---- object type deletion ----

test("object type delete removes its placed objects and keeps the others", () => {
  const scn = templatesScn();
  const rep = forceDelete(scn, ["otBarrel"], {}, set);
  assert.ok(!scn.entities.some(e => e.id === "eBarrel1" || e.id === "eBarrel2"));
  assert.ok(scn.entities.some(e => e.id === "eChest"));
  assert.ok(!scn.objectTemplates.some(t => t.id === "otBarrel"));
  assert.ok(rep.removed.some(r => r.id === "otBarrel" && r.kind === "objectType"));
  assert.equal(rep.removed.filter(r => r.kind === "object").length, 2);
});

test("object type delete strips only the matching endState entries; the effects stay", () => {
  const scn = templatesScn();
  forceDelete(scn, ["otBarrel"], {}, set);
  const chest = scn.objectTemplates.find(t => t.id === "otChest");
  assert.equal(chest.startingEffects.length, 2);
  const rots = chest.startingEffects[0];
  assert.equal(rots.desc, "Rots away");
  assert.deepEqual(rots.endState, [{type: "spawnItemOnSelf", item: {name: "Coin", quality: 1}}]);
  const burns = chest.startingEffects[1];
  assert.equal(burns.desc, "Burns");
  assert.deepEqual(burns.endState, []);
});

// ---- item type deletion ----

test("item type delete removes only the matching inventory stacks", () => {
  const scn = itemsScn();
  const rep = forceDelete(scn, ["itCoin"], {}, set);
  const trader = scn.entities[0];
  assert.deepEqual(trader.inventory, [stack("s2", 2, "itKey")]);
  assert.ok(rep.changed.some(c => c.ownerId === "n1" && c.what.includes("inventory")));
});

test("item type delete removes the matching merchant stock stacks", () => {
  const scn = itemsScn();
  const rep = forceDelete(scn, ["itCoin"], {}, set);
  const trader = scn.entities[0];
  assert.deepEqual(trader.merchant.stock, [stack("s6", 1, "itKey")]);
  assert.ok(rep.changed.some(c => c.ownerId === "n1" && c.what.includes("merchant")));
});

test("item type delete deletes the equipment slots that held it", () => {
  const scn = itemsScn();
  const rep = forceDelete(scn, ["itCoin"], {}, set);
  const trader = scn.entities[0];
  assert.ok(!("hand" in trader.equipment));
  assert.deepEqual(trader.equipment.head, stack("s4", 1, "itKey"));
  assert.ok(rep.changed.some(c => c.ownerId === "n1" && c.what.includes("unequipped")));
});

test("item type delete removes its id from every loot pool", () => {
  const scn = itemsScn();
  const rep = forceDelete(scn, ["itCoin"], {}, set);
  assert.deepEqual(scn.objectTemplates.find(t => t.id === "otBarrel").lootPoolIds, ["itKey"]);
  assert.deepEqual(scn.hostileNpcTemplates.find(t => t.id === "h1").lootPoolIds, []);
  assert.ok(!scn.itemTemplates.some(t => t.id === "itCoin"));
  assert.ok(rep.changed.some(c => c.ownerId === "otBarrel"));
  assert.ok(rep.changed.some(c => c.ownerId === "h1"));
});

test("item type delete removes the spawnItemOnSelf entries for its name", () => {
  const scn = itemsScn();
  const rep = forceDelete(scn, ["itCoin"], {}, set);
  const shrine = scn.objectTemplates.find(t => t.id === "otShrine");
  assert.equal(shrine.startingEffects.length, 1);
  assert.deepEqual(shrine.startingEffects[0].endState,
    [{type: "spawnItemOnSelf", item: {name: "Key", quality: 1}}]);
  assert.ok(rep.changed.some(c => c.ownerId === "otShrine"));
});

// ---- player ----

test("the player is never deleted", () => {
  const scn = millScn();
  scn.entities.push(player("pc", "Hero", [
    block("00:00", "07:00", "Mill", "sleep"),
    block("07:00", "00:00", "Village", "work")
  ]));
  const rep = forceDelete(scn, ["pc"], {}, set);
  assert.ok(scn.entities.some(e => e.id === "pc"));
  assert.ok(!rep.removed.some(r => r.id === "pc"));
  assert.ok(rep.warnings.some(w => w.includes("Hero") || /player/i.test(w)));
});

// ---- previewDelete ----

test("previewDelete leaves the scenario unchanged and matches forceDelete's report", () => {
  const scn = millScn();
  scn.entities[0].inventory = [stack("s1", 3, "itCoin")];
  scn.itemTemplates = [{id: "itCoin", name: "Coin"}];
  const before = JSON.stringify(scn);
  const preview = previewDelete(scn, ["rMill", "itCoin"], {});
  assert.equal(JSON.stringify(scn), before);
  const live = structuredClone(scn);
  const rep = forceDelete(live, ["rMill", "itCoin"], {}, set);
  assert.equal(JSON.stringify(preview), JSON.stringify(rep));
});

// ---- renameEverywhere ----

test("renameEverywhere renames a region's schedule and calendar references and counts them", () => {
  const scn = millScn();
  scn.calendar = [
    {id: "ev1", name: "Festival", location: "Mill"},
    {id: "ev2", name: "Market day", location: "Market"}
  ];
  const res = renameEverywhere(scn, "rMill", "Old Mill", set);
  assert.equal(res.count, 2);
  assert.equal(scn.entities[0].schedule[1].location, "Old Mill");
  assert.equal(scn.calendar[0].location, "Old Mill");
  assert.equal(scn.calendar[1].location, "Market");
  assert.equal(scn.regions.find(r => r.id === "rMill").name, "Old Mill");
});

test("renameEverywhere refuses a duplicate region name without changing anything", () => {
  const scn = millScn();
  const before = JSON.stringify(scn);
  const res = renameEverywhere(scn, "rMill", "Market", set);
  assert.ok(res.error);
  assert.equal(JSON.stringify(scn), before);
});

test("renameEverywhere refuses a duplicate item type name", () => {
  const scn = itemsScn();
  const before = JSON.stringify(scn);
  const res = renameEverywhere(scn, "itKey", "Coin", set);
  assert.ok(res.error);
  assert.equal(JSON.stringify(scn), before);
});

test("renameEverywhere refuses an empty name", () => {
  const scn = millScn();
  const before = JSON.stringify(scn);
  const res = renameEverywhere(scn, "rMill", "   ", set);
  assert.ok(res.error);
  assert.equal(JSON.stringify(scn), before);
});

test("renameEverywhere renames an item's spawnItemOnSelf names", () => {
  const scn = itemsScn();
  const res = renameEverywhere(scn, "itCoin", "Gold Coin", set);
  assert.equal(res.count, 1);
  const shrine = scn.objectTemplates.find(t => t.id === "otShrine");
  assert.equal(shrine.startingEffects[0].endState[0].item.name, "Gold Coin");
  assert.equal(shrine.startingEffects[0].endState[1].item.name, "Key");
  assert.equal(scn.itemTemplates.find(t => t.id === "itCoin").name, "Gold Coin");
  assert.deepEqual(scn.objectTemplates.find(t => t.id === "otBarrel").lootPoolIds, ["itCoin", "itKey"]);
});

test("renameEverywhere on an npc changes only its own name", () => {
  const scn = millScn();
  const res = renameEverywhere(scn, "n1", "Baker", set);
  assert.equal(res.count, 0);
  assert.equal(scn.entities[0].name, "Baker");
});

// ---- findMentions ----

test("findMentions matches whole words only", () => {
  const text = "The Mill stands. Millie and the Millstone serve the Mill. (Mill)";
  const scn = baseScn({worldBackground: text});
  const ms = findMentions(scn, "Mill");
  assert.equal(ms.length, 3);
  const starts = ms.map(m => m.start);
  assert.deepEqual(starts, starts.slice().sort((a, b) => a - b));
  for (const m of ms) assert.equal(text.slice(m.start, m.start + 4), "Mill");
  assert.ok(ms[0].before.endsWith("The "));
  assert.ok(ms[ms.length - 1].after.startsWith(")"));
});

test("findMentions is case-sensitive", () => {
  const text = "the mill is old. The Mill is new.";
  const scn = baseScn({worldBackground: text});
  const ms = findMentions(scn, "Mill");
  assert.equal(ms.length, 1);
  assert.equal(ms[0].start, text.indexOf("The Mill") + 4);
});

test("findMentions escapes regex characters in the name", () => {
  const text = "Visit St. Ann (old) today. Skip Stx Ann (old) and xSt. Ann (old).";
  const scn = baseScn({worldBackground: text});
  const ms = findMentions(scn, "St. Ann (old)");
  assert.equal(ms.length, 1);
  assert.equal(ms[0].start, text.indexOf("St. Ann (old)"));
  assert.ok(ms[0].after.startsWith(" today"));
});

test("findMentions walks nested quest strings with a readable field path", () => {
  const scn = baseScn({
    quests: [{title: "Find the Grail", objectives: [{root: {text: "Return the Grail to the shrine"}}]}]
  });
  const ms = findMentions(scn, "Grail");
  assert.equal(ms.length, 2);
  assert.equal(ms[0].field, "quests[0].title");
  assert.equal(ms[1].field, "quests[0].objectives[0].root.text");
  assert.equal(ms[1].container, scn.quests[0].objectives[0].root);
  assert.equal(ms[1].key, "text");
  assert.equal(ms[1].ownerId, null);
});

test("findMentions never searches names, ids or schedule locations", () => {
  const scn = millScn();
  const ms = findMentions(scn, "Mill");
  assert.deepEqual(ms, []);
});

test("excludeOwnerId skips that owner's fields", () => {
  const scn = baseScn({
    regions: [reg("r1", "Village", [0, 0], [5, 5])],
    entities: [
      npc("a", "Alice", [], {description: "Alice saw the Mill burn"}),
      npc("b", "Bob", [], {description: "Bob rebuilt the Mill"})
    ]
  });
  assert.equal(findMentions(scn, "Mill").length, 2);
  const only = findMentions(scn, "Mill", {excludeOwnerId: "a"});
  assert.deepEqual(only.map(m => m.ownerId), ["b"]);
});

test("before and after carry at most 30 characters of context", () => {
  const text = "-".repeat(40) + "Mill" + "-".repeat(40);
  const scn = baseScn({worldBackground: text});
  const ms = findMentions(scn, "Mill");
  assert.equal(ms.length, 1);
  assert.equal(ms[0].start, 40);
  assert.equal(ms[0].before, "-".repeat(30));
  assert.equal(ms[0].after, "-".repeat(30));
});

test("results follow the documented field order", () => {
  const scn = baseScn({
    worldBackground: "Zed",
    narrativeRules: ["Zed"],
    regions: [reg("r1", "Village", [0, 0], [5, 5], {description: "Zed"})],
    entities: [npc("n1", "Ann", [], {
      description: "Zed", mindset: "Zed", physicalDescription: "Zed", memories: [{t: 1, text: "Zed"}]
    })],
    objectTemplates: [{id: "ot1", name: "Crate", description: "Zed"}],
    itemTemplates: [{id: "it1", name: "Coin", description: "Zed"}],
    hostileNpcTemplates: [{id: "h1", name: "Wolf", description: "Zed"}],
    calendar: [{id: "ev1", name: "Zed fest", missedConsequence: "Zed left"}],
    quests: [["Zed"]]
  });
  const ms = findMentions(scn, "Zed");
  assert.deepEqual(ms.map(m => [m.ownerId, m.field]), [
    [null, "worldBackground"],
    [null, "narrativeRules[0]"],
    ["r1", "description"],
    ["n1", "description"],
    ["n1", "mindset"],
    ["n1", "physicalDescription"],
    ["n1", "memories[0].text"],
    ["ot1", "description"],
    ["it1", "description"],
    ["h1", "description"],
    ["ev1", "name"],
    ["ev1", "missedConsequence"],
    [null, "quests[0][0]"]
  ]);
});

// ---- replaceMentions ----

test("replaceMentions replaces both mentions in one string", () => {
  const scn = baseScn({worldBackground: "Mill and Mill"});
  const ms = findMentions(scn, "Mill");
  assert.equal(ms.length, 2);
  const n = replaceMentions(ms, "Mill", "Windmill", set);
  assert.equal(n, 2);
  assert.equal(scn.worldBackground, "Windmill and Windmill");
});

test("replaceMentions can replace a subset of the mentions", () => {
  const scn = baseScn({worldBackground: "Mill and Mill"});
  const ms = findMentions(scn, "Mill");
  const n = replaceMentions([ms[1]], "Mill", "Sawmill", set);
  assert.equal(n, 1);
  assert.equal(scn.worldBackground, "Mill and Sawmill");
});

test("replaceMentions skips mentions whose text no longer matches", () => {
  const scn = baseScn({worldBackground: "Mill a Mill b Mill"});
  const ms = findMentions(scn, "Mill");
  set(scn, "worldBackground", "Xill a Mill b Mill");
  const n = replaceMentions(ms, "Mill", "Windmill", set);
  assert.equal(n, 2);
  assert.equal(scn.worldBackground, "Xill a Windmill b Windmill");
});

// ---- the setter rule ----

test("every change goes through the supplied setter", () => {
  const scn = millScn();
  let calls = 0;
  const counting = (o, k, v) => { calls++; set(o, k, v); };
  forceDelete(scn, ["rMill"], {}, counting);
  assert.equal(calls, 2);
});

test("forceDelete succeeds on a deep copy whose arrays are frozen", () => {
  const fixture = millScn();
  fixture.regions.push(reg("rCell", "Cell", [3, 3], [1, 1]));
  fixture.entities.push(npc("w1", "Wolf", [block("00:00", "00:00", "Mill", "sleep")], {pos: [3, 3]}));
  const frozen = freezeArrays(structuredClone(fixture));
  assert.throws(() => frozen.regions.push({}));
  const rep = forceDelete(frozen, ["rMill"], {deleteContents: true}, set);
  assert.ok(rep.removed.some(r => r.id === "rCell"));
  assert.ok(!frozen.regions.some(r => r.id === "rCell"));
  assert.ok(frozen.entities.some(e => e.id === "w1"));
  assert.deepEqual(frozen.entities.find(e => e.id === "w1").schedule, []);
});

// ---- findRefs ----

test("findRefs lists schedule, calendar and hostile-home references to a region", () => {
  const scn = millScn();
  scn.calendar = [
    {id: "ev1", name: "Festival", location: "Mill"},
    {id: "ev2", name: "Fair", location: "Market"}
  ];
  scn.hostileNpcTemplates = [{id: "h1", name: "Wolves", regionId: "rMill", lootPoolIds: []}];
  const refs = findRefs(scn, "rMill");
  assert.deepEqual(refs.map(r => r.kind), ["schedule", "calendar", "hostileHome"]);
  assert.equal(refs[0].ownerId, "n1");
  assert.equal(refs[0].detail, "07:00–12:00 work");
  assert.equal(refs[1].ownerId, "ev1");
  assert.equal(refs[2].ownerId, "h1");
});

test("findRefs lists placed objects and effect spawns for an object type", () => {
  const scn = templatesScn();
  const refs = findRefs(scn, "otBarrel");
  assert.deepEqual(refs.map(r => r.kind), ["placed", "placed", "effectSpawn", "effectSpawn"]);
  assert.equal(refs[0].ownerId, "eBarrel1");
  assert.equal(refs[2].ownerId, "otChest");
});

test("findRefs lists every kind of item reference", () => {
  const scn = itemsScn();
  const refs = findRefs(scn, "itCoin");
  assert.deepEqual(refs.map(r => r.kind),
    ["carried", "equipped", "stock", "loot", "loot", "effectItem"]);
  assert.equal(refs[0].detail, "x3");
  assert.equal(refs[1].detail, "hand");
  assert.equal(refs[3].ownerId, "otBarrel");
  assert.equal(refs[4].ownerId, "h1");
  assert.equal(refs[5].ownerId, "otShrine");
});

test("findRefs lists placed npcs for a hostile type and nothing for unknown ids", () => {
  const scn = millScn();
  scn.hostileNpcTemplates = [{id: "h1", name: "Wolves", regionId: "rVillage", lootPoolIds: []}];
  scn.entities.push(npc("w1", "Wolf", [block("00:00", "00:00", "Village", "sleep")], {templateId: "h1"}));
  assert.deepEqual(findRefs(scn, "h1").map(r => r.kind), ["placed"]);
  assert.deepEqual(findRefs(scn, "nope"), []);
  assert.deepEqual(findRefs(scn, "n1"), []);
});

// ---- entity deletion ----

test("deleting an npc leaves free text that mentions them alone", () => {
  const scn = millScn();
  scn.entities.push(npc("n2", "Ann", [], {
    description: "Ann watches the Miller work",
    memories: [{t: 1, text: "The Miller lied"}]
  }));
  const rep = forceDelete(scn, ["n1"], {}, set);
  assert.ok(!scn.entities.some(e => e.id === "n1"));
  const ann = scn.entities.find(e => e.id === "n2");
  assert.equal(ann.description, "Ann watches the Miller work");
  assert.equal(ann.memories[0].text, "The Miller lied");
  assert.deepEqual(rep.removed, [{id: "n1", name: "Miller", kind: "npc"}]);
});

test("an unknown id is skipped with a warning", () => {
  const scn = millScn();
  const rep = forceDelete(scn, ["ghost"], {}, set);
  assert.deepEqual(rep.removed, []);
  assert.ok(rep.warnings.some(w => w.includes("ghost")));
  assert.equal(scn.regions.length, 3);
});

test("deleting an object entity removes it and nothing else", () => {
  const scn = templatesScn();
  const rep = forceDelete(scn, ["eBarrel1"], {}, set);
  assert.ok(!scn.entities.some(e => e.id === "eBarrel1"));
  assert.equal(scn.entities.length, 2);
  assert.deepEqual(rep.removed, [{id: "eBarrel1", name: "Barrel", kind: "object"}]);
  assert.deepEqual(rep.changed, []);
});
