// node --test   (from tools/code-mod-loader)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

function load({ withSearch = true } = {}) {
  const ctx = vm.createContext({ console: { info() {}, error() {}, warn() {} } });
  ctx.globalThis = ctx;
  for (const f of ['runtime/loader.js', 'examples/wall-aware-perception/mod.js']) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, f), 'utf8'), ctx, { filename: f });
  }
  if (withSearch) ctx.__arpg.pathOriginal = search; // as if a path search already ran
  return ctx.__arpg;
}

// Stand-in for the game's A* with {maxCost, wallsOnly}: 4-way BFS over non-wall cells.
function search(world, from, to, _mover, opts) {
  const k = c => `${c[0]},${c[1]}`;
  const s = [Math.round(from[0]), Math.round(from[1])], g = [Math.round(to[0]), Math.round(to[1])];
  world.searches = (world.searches ?? 0) + 1;
  const dist = new Map([[k(s), 0]]);
  const queue = [s];
  while (queue.length) {
    const c = queue.shift();
    if (k(c) === k(g)) return Array(dist.get(k(c))).fill(c);
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const n = [c[0] + dx, c[1] + dy];
      if (world.walls.has(k(n)) || dist.has(k(n)) || n[0] < 0 || n[1] < 0 || n[0] >= 40 || n[1] >= 20) continue;
      const d = dist.get(k(c)) + 1;
      if (d > opts.maxCost) continue;
      dist.set(k(n), d);
      queue.push(n);
    }
  }
  return null;
}

// Two walled rooms side by side (x 0–9 and 11–20, y 0–19), a wall at x = 10 with one doorway.
function makeWorld(doorY) {
  const walls = new Set();
  for (let y = 0; y < 20; y++) if (y !== doorY) walls.add(`10,${y}`);
  const player = { type: 'player', name: 'Wren', pos: [8, 2], size: [1, 1] };
  return {
    walls,
    activeRealSecs: 0,
    player,
    entities: [player],
    regions: [
      { name: 'West Hall', position: [0, 0], size: [10, 20], wall: 'stone' },
      { name: 'East Hall', position: [11, 0], size: [10, 20], wall: 'stone' },
    ],
  };
}

const npc = (name, pos) => ({ type: 'npc', name, pos, size: [1, 1] });

test('someone 4 cells away behind a wall, with the door far off, is not noticed', () => {
  const arpg = load();
  const world = makeWorld(18);
  const skeleton = npc('Skeleton', [12, 2]);
  assert.equal(arpg.perceive(world, world.player, skeleton, 14), false);
  assert.equal(arpg.perceive(world, skeleton, world.player, 14), false, 'either argument order');
});

test('an open doorway close by lets them notice each other', () => {
  const arpg = load();
  const world = makeWorld(3);
  assert.equal(arpg.perceive(world, world.player, npc('Skeleton', [12, 2]), 14), true);
});

test('the same walled room, or both outdoors, needs no search', () => {
  const arpg = load();
  const world = makeWorld(18);
  assert.equal(arpg.perceive(world, world.player, npc('Hal', [2, 15]), 14), true);
  world.regions = [];
  assert.equal(arpg.perceive(world, world.player, npc('Hal', [12, 2]), 14), true, 'outdoors: nothing to block');
  assert.equal(world.searches, undefined);
});

test('checks that do not involve the player are left alone', () => {
  const arpg = load();
  const world = makeWorld(18);
  assert.equal(arpg.perceive(world, npc('A', [8, 2]), npc('B', [12, 2]), 14), true);
});

test('objects behind a wall are not noticed either', () => {
  const arpg = load();
  const world = makeWorld(18);
  const chest = { type: 'object', name: 'Chest', pos: [12, 2], size: [1, 1] };
  assert.equal(arpg.perceive(world, world.player, chest, 14), false);
});

test('answers are reused until the map regions change', () => {
  const arpg = load();
  const world = makeWorld(18);
  const skeleton = npc('Skeleton', [12, 2]);
  arpg.perceive(world, world.player, skeleton, 14);
  world.activeRealSecs = 60;
  arpg.perceive(world, world.player, skeleton, 14);
  assert.equal(world.searches, 1);
  skeleton.pos = [12, 3];
  arpg.perceive(world, world.player, skeleton, 14);
  assert.equal(world.searches, 2, 'a new cell is a new question');
  world.regionsRev = 1; // e.g. the GM's spawn_region
  arpg.perceive(world, world.player, skeleton, 14);
  assert.equal(world.searches, 3);
});

test('without the game search yet, the game keeps its own answer', () => {
  const arpg = load({ withSearch: false });
  const world = makeWorld(18);
  assert.equal(arpg.perceive(world, world.player, npc('Skeleton', [12, 2]), 14), true);
});

test('the patched game hands over its path search, so it works from the first tick', () => {
  const arpg = load({ withSearch: false });
  const world = makeWorld(18);
  assert.equal(arpg.perceive(world, world.player, npc('Skeleton', [12, 2]), 14, search), false);
  assert.equal(arpg.pathOriginal, search);
});
