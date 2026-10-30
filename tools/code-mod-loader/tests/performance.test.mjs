// node --test   (from tools/code-mod-loader)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

function load() {
  let clock = 0;
  const ctx = vm.createContext({ console: { info() {}, error() {}, warn() {} }, performance: { now: () => clock } });
  ctx.globalThis = ctx;
  for (const f of ['runtime/loader.js', 'examples/performance/mod.js']) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, f), 'utf8'), ctx, { filename: f });
  }
  return { arpg: ctx.__arpg, advance: ms => (clock += ms) };
}

const world = () => ({
  regionsRev: 0,
  entities: [
    { id: 'o1', type: 'object', name: 'Table' },
    { id: 'n1', type: 'npc', name: 'Hal' },
  ],
});

// What the patched constructor does: ask for a cached grid, or build and offer one.
function build(arpg, w, entity, wallsOnly) {
  const hit = arpg.navGet(w, entity, wallsOnly);
  if (hit) return hit;
  const grid = { built: Symbol('grid') };
  arpg.navPut(w, entity, wallsOnly, grid);
  return grid;
}

test('a recent grid is reused, whichever character asks', () => {
  const { arpg } = load();
  const w = world();
  const a = build(arpg, w, w.entities[1], false);
  assert.equal(build(arpg, w, w.entities[1], false), a);
  assert.equal(build(arpg, w, undefined, false), a, 'characters never change the grid');
  assert.notEqual(build(arpg, w, undefined, true), a, 'walls-only grids are kept apart');
  assert.notEqual(build(arpg, w, w.entities[0], false), a, 'leaving out an object changes it');
  assert.deepEqual({ ...arpg.performance.stats() }, { built: 3, reused: 2 });
});

test('grids older than a tenth of a second are rebuilt', () => {
  const { arpg, advance } = load();
  const w = world();
  const a = build(arpg, w, undefined, false);
  advance(90);
  assert.equal(build(arpg, w, undefined, false), a);
  advance(20);
  assert.notEqual(build(arpg, w, undefined, false), a);
});

test('new walls, a new doorway or a new object start the cache over at once', () => {
  const { arpg } = load();
  const w = world();
  w.regions = [{ name: 'Hut', wall: 'wood', openings: [[1, 1]] }];
  const a = build(arpg, w, undefined, false);
  w.regionsRev = 1;
  const b = build(arpg, w, undefined, false);
  assert.notEqual(b, a);
  w.regions[0].openings.push([2, 1]); // the game's door-carving, then an immediate step test
  const c = build(arpg, w, undefined, false);
  assert.notEqual(c, b);
  w.entities.push({ id: 'o2', type: 'object', name: 'Crate' });
  assert.notEqual(build(arpg, w, undefined, false), c);
});

// A minimal Phaser-like scene for the culling.
function scene() {
  const tile = (x, y) => ({ type: 'Image', getBounds: () => ({ x, y, width: 192, height: 192 }), cameraFilter: 0 });
  const ground = { type: 'Container', depth: 1, list: [tile(0, 0), tile(2000, 2000)], cameraFilter: 0 };
  const near = { type: 'Container', depth: 20, x: 100, y: 100, list: [{}, {}], cameraFilter: 0 };
  const far = { type: 'Container', depth: 20, x: 2500, y: 2500, list: [{}, {}], cameraFilter: 0 };
  const hiddenByGame = { type: 'Container', depth: 20, x: 2500, y: 2600, list: [{}], cameraFilter: 1 };
  const lighting = { type: 'RenderTexture', depth: 9, getBounds: () => ({ x: 0, y: 0, width: 3072, height: 3072 }), cameraFilter: 0 };
  const cam = { id: 1, worldView: { x: 0, y: 0, right: 400, bottom: 300, width: 400, height: 300, centerX: 200, centerY: 150 } };
  return { s: { children: { list: [ground, near, far, hiddenByGame, lighting] } }, cam, ground, near, far, hiddenByGame, lighting };
}

test('the game camera skips what is far outside the view', () => {
  const { arpg } = load();
  const { s, cam, ground, near, far, lighting } = scene();
  arpg.performance.cullMain(s, cam);
  assert.equal(ground.list[0].cameraFilter, 0);
  assert.equal(ground.list[1].cameraFilter, 1);
  assert.equal(near.cameraFilter, 0);
  assert.equal(far.cameraFilter, 1);
  assert.equal(lighting.cameraFilter, 0, 'full-map layers stay');
});

test('things come back as the view moves, and the game\'s own hidden objects stay hidden', () => {
  const { arpg } = load();
  const { s, cam, far, hiddenByGame } = scene();
  arpg.performance.cullMain(s, cam);
  Object.assign(cam.worldView, { x: 2300, y: 2300, right: 2700, bottom: 2700 });
  arpg.performance.cullMain(s, cam);
  assert.equal(far.cameraFilter, 0);
  assert.equal(hiddenByGame.cameraFilter, 1, 'not ours to show');
  arpg.performance.uncull(s, cam);
  assert.equal(hiddenByGame.cameraFilter, 1);
});
