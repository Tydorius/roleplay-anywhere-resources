// node --test tests/*.test.mjs   (from tools/code-mod-loader)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadWithSight } from './game-1.0-sight.mjs';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const MODS = ['examples/region-groups/mod.js', 'examples/wall-aware-perception/mod.js'];

// The loader and the mod only, without 1.0's sight code: what an unpatched game leaves them.
function loadWithoutSight() {
  const ctx = vm.createContext({ console: { info() {}, error() {}, warn() {} } });
  ctx.globalThis = ctx;
  for (const f of ['runtime/loader.js', 'examples/wall-aware-perception/mod.js']) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, f), 'utf8'), ctx, { filename: f });
  }
  return ctx;
}

const npc = (name, pos) => ({ type: 'npc', name, pos, size: [1, 1] });
const addEnt = (world, e) => (world.entities.push(e), e);
const perceive = (ctx, world, a, b) => ctx.__arpg.perceive(world, a, b, 14, undefined, true);

// Two walled halls side by side sharing the x = 9 | 10 edge, one doorway at doorY listed on
// both sides of it.
function twoRooms(doorY = 18) {
  const player = { type: 'player', name: 'Wren', pos: [8, 2], size: [1, 1] };
  return {
    regionsRev: 0,
    activeRealSecs: 0,
    gameTimeSecs: 0,
    player,
    entities: [player],
    regions: [
      { name: 'West Hall', position: [0, 0], size: [10, 20], wall: 'stone', openings: [[9, doorY, 'e']] },
      { name: 'East Hall', position: [10, 0], size: [10, 20], wall: 'stone', openings: [[10, doorY, 'w']] },
    ],
  };
}

test('someone behind the shared wall, with the door far off, is not noticed', () => {
  const ctx = loadWithSight(MODS);
  const world = twoRooms();
  const skeleton = addEnt(world, npc('Skeleton', [11, 2]));
  assert.equal(perceive(ctx, world, world.player, skeleton), false);
  assert.equal(perceive(ctx, world, skeleton, world.player), false, 'either argument order');
});

test('a doorway lets them see each other, until the door on it is shut', () => {
  const ctx = loadWithSight(MODS);
  const world = twoRooms(2);
  const skeleton = addEnt(world, npc('Skeleton', [11, 2]));
  assert.equal(perceive(ctx, world, world.player, skeleton), true, 'through the open doorway');
  const door = addEnt(world, { type: 'object', pos: [10, 2], size: [0, 1], objectTemplate: { door: 'door' } });
  world.activeRealSecs = 1; // answers last one step
  assert.equal(perceive(ctx, world, world.player, skeleton), false, 'a shut door blocks');
  door.heldOpen = true;
  world.activeRealSecs = 2;
  assert.equal(perceive(ctx, world, world.player, skeleton), true, 'held open');
  door.heldOpen = false;
  door.objectTemplate = { door: 'bars' };
  world.activeRealSecs = 3;
  assert.equal(perceive(ctx, world, world.player, skeleton), true, 'bars are see-through');
});

test('one walled room is one room, even with a walled closet between the two', () => {
  const ctx = loadWithSight(MODS);
  const world = twoRooms();
  world.regions.push({ name: 'Closet', position: [3, 6], size: [2, 2], wall: 'wood' });
  world.player.pos = [2, 7];
  const hal = addEnt(world, npc('Hal', [6, 7]));
  let lineCalls = 0;
  const orig = ctx.__arpg.game.lineClear;
  ctx.__arpg.game.lineClear = (...args) => (lineCalls++, orig(...args));
  assert.equal(perceive(ctx, world, world.player, hal), true);
  assert.equal(lineCalls, 0, 'no line walked inside one room');
});

// Two touching walled pieces named "Tithe Barn" form an L; the joint cells (y = 3 | 4, x 0–3)
// are openings on both pieces, 'n' on the north piece and 's' on the south one.
function barn() {
  const player = { type: 'player', name: 'Wren', pos: [8, 1], size: [1, 1] };
  return {
    regionsRev: 0,
    activeRealSecs: 0,
    gameTimeSecs: 0,
    player,
    entities: [player],
    regions: [
      { name: 'Tithe Barn', position: [0, 0], size: [10, 4], wall: 'timber',
        openings: [[0, 3, 'n'], [1, 3, 'n'], [2, 3, 'n'], [3, 3, 'n']] },
      { name: 'Tithe Barn', position: [0, 4], size: [4, 6], wall: 'timber',
        openings: [[0, 4, 's'], [1, 4, 's'], [2, 4, 's'], [3, 4, 's']] },
    ],
  };
}

test('an L-shaped region-groups room sees round its corner; two mere rooms do not', () => {
  const world = barn();
  const ostler = addEnt(world, npc('Ostler', [1, 8]));
  const withGroups = loadWithSight(MODS);
  assert.equal(perceive(withGroups, world, world.player, ostler), true, 'the pieces are one room');
  const withoutGroups = loadWithSight(['examples/wall-aware-perception/mod.js']);
  assert.equal(perceive(withoutGroups, world, world.player, ostler), false, 'the straight line leaves the L');
});

test('both outdoors is no shortcut: a house between them blocks', () => {
  const ctx = loadWithSight(MODS);
  const player = { type: 'player', name: 'Wren', pos: [2, 5], size: [1, 1] };
  const world = {
    regionsRev: 0,
    activeRealSecs: 0,
    gameTimeSecs: 0,
    player,
    entities: [player],
    regions: [{ name: 'House', position: [5, 0], size: [4, 10], wall: 'stone', openings: [] }],
  };
  const hal = addEnt(world, npc('Hal', [12, 5]));
  assert.equal(perceive(ctx, world, player, hal), false, 'the house walls it off');
  world.regions = [];
  world.regionsRev = 1;
  assert.equal(perceive(ctx, world, player, hal), true, 'with no house');
});

test('a floor or cellar is another plane: no noticing across planes', () => {
  const ctx = loadWithSight(MODS);
  const player = { type: 'player', name: 'Wren', pos: [18, 3], size: [1, 1] };
  const world = {
    regionsRev: 0,
    activeRealSecs: 0,
    gameTimeSecs: 0,
    player,
    entities: [player],
    regions: [{ name: 'Loft', position: [20, 0], size: [8, 8], pocket: { anchor: 'hall', level: 1 } }],
  };
  const imp = addEnt(world, npc('Imp', [21, 3]));
  assert.equal(perceive(ctx, world, player, imp), false, 'the main map and the loft');
  player.pos = [21, 5];
  assert.equal(perceive(ctx, world, player, imp), true, 'both up in the loft');
});

test('an object behind the wall is not noticed either', () => {
  const ctx = loadWithSight(MODS);
  const world = twoRooms();
  const chest = addEnt(world, { type: 'object', name: 'Chest', pos: [11, 2], size: [1, 1] });
  assert.equal(perceive(ctx, world, world.player, chest), false);
});

test("it never turns the game's no into a yes", () => {
  const ctx = loadWithSight(MODS);
  const world = twoRooms();
  const hal = addEnt(world, npc('Hal', [2, 15])); // one room with the player
  assert.equal(ctx.__arpg.perceive(world, world.player, hal, 14, undefined, false), false);
});

test('answers are reused within a step, and asked again the next', () => {
  const ctx = loadWithSight(MODS);
  const world = twoRooms(2); // they see each other through the doorway
  const skeleton = addEnt(world, npc('Skeleton', [11, 2]));
  let lines = 0, blockers = 0;
  const lineClear = ctx.__arpg.game.lineClear, gameBlockers = ctx.__arpg.game.sightBlockers;
  ctx.__arpg.game.lineClear = (...args) => (lines++, lineClear(...args));
  ctx.__arpg.game.sightBlockers = (...args) => (blockers++, gameBlockers(...args));
  for (let i = 0; i < 3; i++) assert.equal(perceive(ctx, world, world.player, skeleton), true);
  assert.equal(lines, 1, 'the same question answered once');
  assert.equal(blockers, 1, 'the blockers built once');
  world.activeRealSecs = 1; // the next simulation step
  assert.equal(perceive(ctx, world, world.player, skeleton), true);
  assert.equal(lines, 2, 'asked again next step');
  assert.equal(blockers, 2);
  world.activeRealSecs = 2;
  addEnt(world, { type: 'object', pos: [10, 2], size: [0, 1], objectTemplate: { door: 'door' } });
  assert.equal(perceive(ctx, world, world.player, skeleton), false, 'a door shut between steps');
  assert.equal(lines, 3);
});

test('without the sight patches the game\'s answer stands, but planes still split', () => {
  const ctx = loadWithoutSight();
  const world = twoRooms();
  world.regions.push({ name: 'Loft', position: [20, 0], size: [8, 8], pocket: { anchor: 'hall', level: 1 } });
  const skeleton = addEnt(world, npc('Skeleton', [11, 2]));
  assert.equal(perceive(ctx, world, world.player, skeleton), true, 'no line test to be had');
  const imp = addEnt(world, npc('Imp', [21, 3]));
  assert.equal(perceive(ctx, world, world.player, imp), false, 'planes need no sight code');
});

test('two NPCs behind the wall are split as well', () => {
  const ctx = loadWithSight(MODS);
  const world = twoRooms();
  const alys = addEnt(world, npc('Alys', [7, 2]));
  const hal = addEnt(world, npc('Hal', [11, 2]));
  assert.equal(perceive(ctx, world, alys, hal), false, 'the rule holds for every pair, not just the player');
});
