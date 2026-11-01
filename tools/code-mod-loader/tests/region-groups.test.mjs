// node --test   (from tools/code-mod-loader)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

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
