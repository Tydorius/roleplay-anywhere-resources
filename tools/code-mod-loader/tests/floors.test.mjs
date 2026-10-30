// node --test   (from tools/code-mod-loader)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

// Loaded in the installer's (alphabetical) order, so floors comes before wall-aware.
function load() {
  const warnings = [];
  const ctx = vm.createContext({ console: { info() {}, error() {}, warn: m => warnings.push(m) } });
  ctx.globalThis = ctx;
  for (const f of ['runtime/loader.js', 'examples/floors/mod.js', 'examples/wall-aware-perception/mod.js']) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, f), 'utf8'), ctx, { filename: f });
  }
  ctx.__arpg.pathOriginal = search;
  return { arpg: ctx.__arpg, warnings };
}

// Walls-only stand-in for the game's search; a wall at x = 10 seals the gallery off.
function search(world, from, to, _m, opts) {
  const k = c => `${c[0]},${c[1]}`;
  const s = [Math.round(from[0]), Math.round(from[1])], g = [Math.round(to[0]), Math.round(to[1])];
  const dist = new Map([[k(s), 0]]);
  const queue = [s];
  while (queue.length) {
    const c = queue.shift();
    if (k(c) === k(g)) return Array(dist.get(k(c))).fill(c);
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const n = [c[0] + dx, c[1] + dy];
      if (n[0] === 10 || n[0] < 0 || n[1] < 0 || n[0] >= 40 || n[1] >= 20 || dist.has(k(n))) continue;
      const d = dist.get(k(c)) + 1;
      if (d > (opts?.maxCost ?? Infinity)) continue;
      dist.set(k(n), d);
      queue.push(n);
    }
  }
  return null;
}

// Gallery x 0–9 (upstairs) over the Hall x 20–29; the Well is a 2×2 hole at gallery [4,2].
function makeWorld() {
  const player = { type: 'player', name: 'Wren', pos: [3, 2], size: [1, 1] };
  return {
    player,
    entities: [player],
    regionsRev: 0,
    regions: [
      { name: 'Gallery', position: [0, 0], size: [10, 6], wall: 'wood' },
      { name: 'Well', position: [4, 2], size: [2, 2], wall: 'wood' },
      { name: 'Hall', position: [20, 0], size: [10, 6], wall: 'stone' },
    ],
    arpgMods: { floors: [{ name: 'Upstairs', area: 'Gallery', above: 'Hall', openings: ['Well'] }] },
  };
}

const npc = (name, pos, extra = {}) => ({ type: 'npc', name, pos, size: [1, 1], ...extra });

test('at the railing you see someone under the opening, and they see you', () => {
  const { arpg } = load();
  const world = makeWorld();
  const alys = npc('Alys', [24, 3]); // directly under the well
  assert.equal(arpg.perceive(world, world.player, alys, 14, search, false), true);
  assert.equal(arpg.perceive(world, alys, world.player, 14, search, false), true);
});

test('away from the railing, or away from the spot below, nobody is seen', () => {
  const { arpg } = load();
  const world = makeWorld();
  world.player.pos = [9, 5]; // far corner of the gallery
  assert.equal(arpg.perceive(world, world.player, npc('Alys', [24, 3]), 14, search, true), false);
  world.player.pos = [3, 2];
  assert.equal(arpg.perceive(world, world.player, npc('Hal', [29, 5]), 14, search, true), false);
});

test('someone outside, close on the flat map but not below, is never noticed from upstairs', () => {
  const { arpg } = load();
  const world = makeWorld();
  assert.equal(arpg.perceive(world, world.player, npc('Farmer', [12, 2]), 14, search, true), false);
});

test('people on the same storey are left to the other rules', () => {
  const { arpg } = load();
  const world = makeWorld();
  world.player.pos = [21, 1];
  assert.equal(arpg.perceive(world, world.player, npc('Alys', [24, 3]), 14, search, true), true);
  assert.equal(arpg.perceive(world, world.player, npc('Alys', [24, 3]), 14, search, false), false);
});

test('the GM learns the floor layout and who is visible through the opening', () => {
  const { arpg } = load();
  const world = makeWorld();
  world.entities.push(npc('Alys', [24, 3], { activity: { summary: 'polishing the bar' } }), npc('Hal', [29, 5]));
  arpg.promptBudgets = {};
  const parts = { head: [], sections: [], tail: [] };
  arpg.prompt(parts, world);
  const byKind = Object.fromEntries(parts.sections.map(s => [s.kind, s.content]));
  assert.equal(byKind.floors, '- Gallery is the floor directly above Hall; openings to look down through: Well');
  assert.equal(byKind.other_floor, '- Alys (polishing the bar): below, in Hall');
  assert.ok(arpg.promptBudgets.floors >= 1e6 && arpg.promptBudgets.other_floor >= 1e6);
});

test('from below, the GM hears who is looking down', () => {
  const { arpg } = load();
  const world = makeWorld();
  world.player.pos = [24, 3];
  world.entities.push(npc('Watcher', [3, 3]));
  const parts = { head: [], sections: [], tail: [] };
  arpg.prompt(parts, world);
  assert.equal(parts.sections.find(s => s.kind === 'other_floor').content, '- Watcher: above, at Gallery');
});

test('a floor whose regions are missing is skipped with a warning', () => {
  const { arpg, warnings } = load();
  const world = makeWorld();
  world.arpgMods.floors[0].above = 'Attic';
  assert.equal(arpg.floors.floorsOf(world).length, 0);
  assert.match(warnings[0], /"Attic" not found/);
});
