"use strict";
// node --test test/      (from tools/scenario-editor)
const test = require("node:test");
const assert = require("node:assert/strict");
const W = require("../world10.js");

const set = (o, k, v) => { if (v === undefined) delete o[k]; else o[k] = v; };
const snap = o => JSON.stringify(o);

const R = (s, id) => s.regions.find(r => r.id === id);
const E = (s, id) => s.entities.find(e => e.id === id);

// A 24 × 24 map with a 6 × 6 house at [4, 4], one door out on its south wall, and two people.
function secretWorld() {
  const s = {
    gridSize: [24, 24],
    regions: [
      {id: "house", name: "House", wall: "wood", position: [4, 4], size: [6, 6], openings: [[6, 4]]},
    ],
    entities: [
      {id: "pc", type: "player", name: "Pat", pos: [12, 12], size: [1, 1], inventory: [], statusEffects: []},
      {id: "ai", type: "npc", name: "Ash", pos: [13, 12], size: [1, 1], inventory: [], statusEffects: []},
    ],
    objectTemplates: [], itemTemplates: [],
  };
  W.hangAllDoors(s, set);
  return s;
}
const doorOf = s => s.entities.find(e => W.isDoor(s, e));

// ---------------------------------------------------------------- on and off
test("setSecret on adds the concealed effect the mod reads, and only once", () => {
  const s = secretWorld(), d = doorOf(s);
  assert.equal(W.isSecret(d), false);
  W.setSecret(s, d, true, set);
  assert.equal(W.isSecret(d), true);
  assert.equal(d.statusEffects.filter(W.isSecretFx).length, 1);
  const fx = d.statusEffects.at(-1);
  assert.match(fx.id, /^se_/);
  assert.deepEqual({...fx, id: "x"}, {id: "x", appliedAt: 28800,
    def: {desc: "secret passage", emoji: "🕳️", type: "constant", mechanics: [{type: "concealed"}]}});
  assert.equal(W.isSecretFx({def: {mechanics: [{type: "locked"}]}}), false, "a lock isn't a secret");
  const before = snap(d);
  W.setSecret(s, d, true, set);
  assert.equal(snap(d), before, "already secret: nothing changes");
  W.setSecret(s, d, false, set);
  assert.equal(W.isSecret(d), false);
  assert.deepEqual(d.statusEffects, []);
});

test("setSecret off takes the mod data with it, empty parents and all", () => {
  const s = secretWorld(), d = doorOf(s);
  W.setSecret(s, d, true, set);
  W.setSecretInfo(s, d, {knownBy: ["Pat"], hint: "a draught", findChance: 0.25}, set);
  assert.deepEqual(s.arpgMods, {secretPassages: {passages: {[d.id]: {knownBy: ["Pat"], hint: "a draught", findChance: 0.25}}}});
  W.setSecret(s, d, false, set);
  assert.ok(!("arpgMods" in s), "the emptied objects come off");
  assert.deepEqual(W.secretInfo(s, d), {knownBy: [], hint: "", findChance: null});
});

test("setSecret off keeps secretPassages settings and unrelated mods", () => {
  const s = secretWorld(), d = doorOf(s);
  W.setSecret(s, d, true, set);
  W.setSecretInfo(s, d, {knownBy: ["Ash"]}, set);
  s.arpgMods.secretPassages.settings = {findChance: 0.3};
  s.arpgMods.otherMod = {x: 1};
  W.setSecret(s, d, false, set);
  assert.deepEqual(s.arpgMods, {secretPassages: {settings: {findChance: 0.3}}, otherMod: {x: 1}});
});

test("a locked secret door keeps its lock when the secret is toggled", () => {
  const s = secretWorld(), d = doorOf(s);
  W.setLocked(s, R(s, "house"), true, set);
  assert.equal(W.isLocked(d), true);
  W.setSecret(s, d, true, set);
  assert.equal(d.statusEffects.length, 2, "the lock and the secret side by side");
  assert.equal(W.isLocked(d) && W.isSecret(d), true);
  W.setSecret(s, d, false, set);
  assert.equal(W.isSecret(d), false);
  assert.equal(W.isLocked(d), true, "the lock stays");
  assert.equal(d.statusEffects.length, 1);
});

// ---------------------------------------------------------------- setSecretInfo
test("setSecretInfo writes the entry and cleans what it's given", () => {
  const s = secretWorld(), d = doorOf(s);
  W.setSecret(s, d, true, set);
  W.setSecretInfo(s, d, {knownBy: ["  Pat ", "", "  "], hint: "  a draught behind the bookcase  ", findChance: 0.25}, set);
  assert.deepEqual(s.arpgMods.secretPassages.passages[d.id],
    {knownBy: ["Pat"], hint: "a draught behind the bookcase", findChance: 0.25});
  W.setSecretInfo(s, d, {knownBy: ["Pat"], hint: "   ", findChance: 1.5}, set);
  assert.deepEqual(s.arpgMods.secretPassages.passages[d.id], {knownBy: ["Pat"]}, "a blank hint and a 1.5 chance drop");
  W.setSecretInfo(s, d, {knownBy: ["Pat"], findChance: 0}, set);
  assert.deepEqual(s.arpgMods.secretPassages.passages[d.id], {knownBy: ["Pat"]}, "0 is no chance at all: dropped");
  W.setSecretInfo(s, d, {knownBy: ["Pat"], findChance: 1}, set);
  assert.deepEqual(s.arpgMods.secretPassages.passages[d.id], {knownBy: ["Pat"], findChance: 1}, "1 finds it every approach");
  W.setSecretInfo(s, d, {knownBy: [], hint: "", findChance: null}, set);
  assert.ok(!("arpgMods" in s), "nothing left: the entry and its parents come off");
  assert.deepEqual(W.secretInfo(s, d), {knownBy: [], hint: "", findChance: null});
});

test("setSecretInfo makes the arpgMods path when there is none", () => {
  const s = secretWorld(), d = doorOf(s);
  W.setSecretInfo(s, d, {hint: "scratch marks"}, set);
  assert.deepEqual(s.arpgMods, {secretPassages: {passages: {[d.id]: {hint: "scratch marks"}}}});
  W.setSecretInfo(s, d, {hint: "  "}, set);
  assert.ok(!("arpgMods" in s));
});

// ---------------------------------------------------------------- secretProblems
test("secretProblems: passages data on an id that isn't a secret door", () => {
  const s = secretWorld(), d = doorOf(s);
  s.arpgMods = {secretPassages: {passages: {}}};
  s.arpgMods.secretPassages.passages.gone = {hint: "stale"};
  assert.deepEqual(W.secretProblems(s), [`Secret passage data names "gone", which isn't on the map.`]);
  delete s.arpgMods.secretPassages.passages.gone;
  W.setSecretInfo(s, E(s, "pc"), {hint: "not a door"}, set);        // a person, not a door
  assert.deepEqual(W.secretProblems(s), [`"Pat" has secret passage data but isn't a secret door.`]);
  delete s.arpgMods.secretPassages.passages.pc;
  W.setSecretInfo(s, d, {hint: "no effect yet"}, set);              // a door without the effect
  assert.deepEqual(W.secretProblems(s), [`"Door 1" has secret passage data but isn't a secret door.`]);
});

test("secretProblems: a knownBy name no character has", () => {
  const s = secretWorld(), d = doorOf(s);
  W.setSecret(s, d, true, set);
  W.setSecretInfo(s, d, {knownBy: ["Pat", "Alys Sedge", "Ash"]}, set);
  assert.deepEqual(W.secretProblems(s), [`"Door 1": nobody called "Alys Sedge" is on the map.`]);
  assert.deepEqual(W.secretProblems(s, d), [`"Door 1": nobody called "Alys Sedge" is on the map.`], "the door's own problems");
  assert.deepEqual(W.secretProblems(s, E(s, "pc")), [], "another door's problems stay out");
});

test("secretProblems: a secret door on no doorway", () => {
  const s = secretWorld(), d = doorOf(s);
  W.setSecret(s, d, true, set);
  set(R(s, "house"), "openings", []);                              // its doorway is gone
  assert.deepEqual(W.secretProblems(s), [`"Door 1" is a secret door on no doorway; the game removes it.`]);
  assert.deepEqual(W.secretProblems(s, d), [`"Door 1" is a secret door on no doorway; the game removes it.`]);
});

test("secretProblems: a sound secret passage says nothing", () => {
  const s = secretWorld(), d = doorOf(s);
  W.setSecret(s, d, true, set);
  W.setSecretInfo(s, d, {knownBy: ["Pat"], hint: "a draught", findChance: 0.25}, set);
  assert.deepEqual(W.secretProblems(s), []);
  assert.deepEqual(W.secretProblems(s, d), []);
});
