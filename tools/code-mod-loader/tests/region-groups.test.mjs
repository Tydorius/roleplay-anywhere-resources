// node --test   (from tools/code-mod-loader)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { PATCHES } from '../patch.mjs';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

function load() {
  const ctx = vm.createContext({ console: { info() {}, error() {}, warn() {} } });
  ctx.globalThis = ctx;
  for (const f of ['runtime/loader.js', 'examples/region-groups/mod.js']) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, f), 'utf8'), ctx, { filename: f });
  }
  return ctx.__arpg;
}

const r = (name, position, size, extra = {}) => ({ name, position, size, ...extra });

// A village ringed by four forest strips, an L-shaped house, and two unrelated bedrooms.
function world() {
  return {
    regionsRev: 0,
    regions: [
      r('The Forest', [0, 0], [40, 5]),
      r('The Forest', [0, 35], [40, 5]),
      r('The Forest', [0, 5], [5, 30]),
      r('The Forest', [35, 5], [5, 30]),
      r('Manor', [10, 10], [10, 4], { wall: 'stone' }),
      r('Manor', [10, 14], [4, 8], { wall: 'stone' }),
      r('Bedroom', [11, 11], [2, 2], { wall: 'wood' }),
      r('Bedroom', [25, 25], [2, 2], { wall: 'wood' }),
    ],
  };
}

test('touching same-name rectangles form one region; separate ones do not', () => {
  const arpg = load();
  const w = world();
  const [n, s, west, east, wingA, wingB, bed1, bed2] = w.regions;
  assert.equal(arpg.sameRegion(w, n, s), true, 'north and south strips join through the side strips');
  assert.equal(arpg.sameRegion(w, west, east), true);
  assert.equal(arpg.sameRegion(w, wingA, wingB), true, 'the two wings of the L');
  assert.equal(arpg.sameRegion(w, bed1, bed2), false, 'two bedrooms in different places');
  assert.equal(arpg.sameRegion(w, n, wingA), false);
  assert.equal(arpg.sameRegion(w, null, n), false);
});

test('a mover is sent to the nearest piece', () => {
  const arpg = load();
  const w = world();
  const [north, south, , east] = w.regions;
  assert.equal(arpg.pieceFor(w, north, { pos: [20, 38] }), south);
  assert.equal(arpg.pieceFor(w, north, { pos: [38, 20] }), east);
  assert.equal(arpg.pieceFor(w, north, { pos: [20, 2] }), north);
  assert.equal(arpg.pieceFor(w, north, undefined), north, 'no mover: unchanged');
  assert.equal(arpg.pieceFor(w, w.regions[6], { pos: [26, 26] }), w.regions[6], 'not grouped: unchanged');
});

test('groups are worked out again when the map changes', () => {
  const arpg = load();
  const w = world();
  const [n, s] = w.regions;
  assert.equal(arpg.sameRegion(w, n, s), true);
  w.regions = w.regions.filter((x, i) => i !== 2 && i !== 3); // drop the side strips
  w.regionsRev = 1;
  assert.equal(arpg.sameRegion(w, n, s), false);
});

test("the GM's region list shows a grouped name once, with everyone in it", () => {
  const arpg = load();
  const w = world();
  const content = [
    '- The Forest (20m N): Wolf (hostile)',
    '  - Woodcutter\'s Hut',
    '- The Forest',
    '- The Forest (30m E): Brigand (hostile), Marrow Jack',
    '- Manor',
    '- Manor (6m SW): Steward',
    '  - Bedroom',
    '- Bedroom',
  ].join('\n');
  const parts = { head: [], sections: [{ kind: 'regions', title: 'Regions:', content }], tail: [] };
  arpg.prompt(parts, w);
  assert.equal(parts.sections[0].content, [
    '- The Forest (20m N): Wolf (hostile), Brigand (hostile), Marrow Jack',
    '  - Woodcutter\'s Hut',
    '- Manor (6m SW): Steward',
    '  - Bedroom',
    '- Bedroom',
  ].join('\n'));
});

test('pieces on different planes never join', () => {
  const arpg = load();
  const w = {
    regionsRev: 0,
    regions: [
      r('Tower', [10, 10], [4, 4], { wall: 'stone' }),                          // the main map
      r('Tower Loft', [14, 10], [6, 6], { pocket: { anchor: 'x', level: 1 } }), // the floor
      r('Tower', [14, 10], [3, 3], { wall: 'stone' }), // inside the loft, touching the first
      r('Hall', [15, 10], [3, 3], { wall: 'stone' }),
      r('Hall', [15, 13], [3, 3], { wall: 'stone' }),
      r('Cellar', [20, 20], [4, 4], { wall: 'stone' }),
      r('Cellar', [24, 20], [6, 6], { wall: 'stone', pocket: { anchor: 'x', level: -1 } }),
    ],
  };
  const [tower, loft, towerUp, hallA, hallB, cellar, cellarPocket] = w.regions;
  assert.equal(arpg.sameRegion(w, tower, towerUp), false, 'touching rectangles, different planes');
  assert.equal(arpg.sameRegion(w, hallA, hallB), true, 'two touching pieces inside the loft');
  assert.equal(arpg.sameRegion(w, cellar, cellarPocket), false, 'a pocket named like a touching region');
  assert.equal(arpg.regionGroups.planeOfRegion(w, loft), loft, 'a pocket is its own plane');
  assert.equal(arpg.regionGroups.planeOfRegion(w, towerUp), loft, 'a piece inside it is on the loft');
  assert.equal(arpg.regionGroups.planeOfRegion(w, tower), null, 'the main map');
});

test('a mover on another floor goes to the region the game picked', () => {
  const arpg = load();
  const w = {
    regionsRev: 0,
    regions: [
      r('The Forest', [0, 0], [10, 5]),
      r('The Forest', [0, 5], [10, 5]),
      r('Loft', [50, 0], [8, 8], { pocket: { anchor: 'hall', level: 1 } }),
    ],
  };
  const [north, south] = w.regions;
  const upInLoft = { pos: [52, 3], size: [1, 1] };
  assert.equal(arpg.pieceFor(w, north, upInLoft), north, 'the piece the game picked stands');
  assert.equal(arpg.pieceFor(w, south, upInLoft), south, 'whichever piece it picked');
  assert.equal(arpg.pieceFor(w, north, { pos: [5, 9], size: [1, 1] }), south, 'on the main map: nearest');
});

test('a natural-shaped piece joins by its rectangle', () => {
  const arpg = load();
  const w = {
    regionsRev: 0,
    regions: [
      r('The Forest', [0, 0], [10, 10], { shape: 'organic' }),
      r('The Forest', [10, 0], [10, 10]),
    ],
  };
  assert.equal(arpg.sameRegion(w, w.regions[0], w.regions[1]), true, 'one group despite the blob');
});

// 1.0's own region code, from the bundle: `Qe` is cut down to the rectangle test and
// `sameSpace` is a wrapper around the expression the region-same-room patch anchors on; the
// rest is 1.0's, verbatim.
const REGIONS_1_0 =
  'function Qe(e,t){return t[0]>=e.position[0]&&t[1]>=e.position[1]&&t[0]<e.position[0]+e.size[0]&&t[1]<e.position[1]+e.size[1]}' +
  'function et(e){return e.size[0]*e.size[1]}' +
  'function Yn(e,t){let n=null;for(const i of e.regions)Qe(i,t)&&(!n||et(i)<et(n))&&(n=i);return n}' +
  'function hN(e,t,n){return Yn(e,n)===t}' +
  'function fs(e,t){let n=null;for(const i of e.regions)i.wall&&Qe(i,t)&&(!n||et(i)<et(n))&&(n=i);return n}' +
  'function Pe(e){return[Math.floor(e.pos[0]+e.size[0]/2),Math.floor(e.pos[1]+e.size[1]/2)]}' +
  'function sameSpace(e,n,o){const A=fs(e,Pe(n)),f=se=>fs(e,Pe(se))===A;return f(o)}';

test('the real 1.0 arrival and same-room tests accept any piece', () => {
  const ctx = vm.createContext({ console: { info() {}, error() {}, warn() {} } });
  ctx.globalThis = ctx;
  for (const f of ['runtime/loader.js', 'examples/region-groups/mod.js']) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, f), 'utf8'), ctx, { filename: f });
  }
  let src = REGIONS_1_0;
  for (const name of ['region-arrival', 'region-same-room']) {
    const p = PATCHES.find(q => q.name === name);
    assert.equal([...src.matchAll(p.find)].length, 1, `${name} matches the 1.0 region code`);
    src = src.replace(p.find, p.replace);
  }
  vm.runInContext(src, ctx, { filename: 'game-1.0-regions' });
  const { hN, sameSpace } = vm.runInContext('({ hN, sameSpace })', ctx);

  const barn = (position, size) => ({ name: 'Tithe Barn', position, size, wall: 'timber' });
  const world = { regionsRev: 0, regions: [barn([70, 34], [10, 4]), barn([70, 38], [4, 5]), barn([90, 34], [10, 4])] };
  const at = (x, y) => ({ pos: [x, y], size: [1, 1] });
  assert.equal(hN(world, world.regions[0], [71, 40]), true, 'arriving in the wing counts for the hall');
  assert.equal(sameSpace(world, at(78, 35), at(71, 41)), true, 'the L is one room');
  assert.equal(hN(world, world.regions[2], [71, 40]), false, 'the separate barn: not arrived at');
  assert.equal(sameSpace(world, at(98, 35), at(71, 41)), false, 'the separate barn: not one room');

  const planes = {
    regionsRev: 0,
    regions: [
      r('Tower', [10, 10], [4, 4], { wall: 'stone' }),
      r('Tower Loft', [14, 10], [6, 6], { pocket: { anchor: 'x', level: 1 } }),
      r('Tower', [14, 10], [3, 3], { wall: 'stone' }),
    ],
  };
  assert.equal(hN(planes, planes.regions[2], [11, 11]), false, 'a floor away');
  assert.equal(hN(planes, planes.regions[0], [15, 11]), false, 'either way round');
});
