// node --test tests/*.test.mjs   (from tools/code-mod-loader)
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
  for (const f of ['runtime/loader.js', 'examples/smooth-edges/mod.js']) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, f), 'utf8'), ctx, { filename: f });
  }
  return ctx;
}

const fixture = JSON.parse(fs.readFileSync(path.join(ROOT, 'tests/fixtures/organic-blobs-1.0.json'), 'utf8'));
const pond = fixture.cases.find(c => c.id === 'region_pond' && c.w === 9 && c.h === 7);
const pondMask = () => {
  const m = new Uint8Array(pond.w * pond.h);
  for (let y = 0; y < pond.h; y++) for (let x = 0; x < pond.w; x++) m[y * pond.w + x] = +pond.rows[y][x];
  return m;
};

// The game's own fade, from its documented recipe: each vertex the mean of its four touching
// cells (outside the rectangle counting 0), then a 3x3 box blur over the vertex grid with
// out-of-range vertices skipped but the divisor still 9.
function gameDefault(mask, w, h) {
  const W = w + 1, H = h + 1;
  const mean = new Float32Array(W * H);
  for (let my = 0; my < H; my++) for (let sx = 0; sx < W; sx++) {
    let sum = 0;
    for (const cy of [h - my - 1, h - my]) if (cy >= 0 && cy < h)
      for (const cx of [sx - 1, sx]) if (cx >= 0 && cx < w) sum += mask[cy * w + cx] ? 1 : 0;
    mean[my * W + sx] = sum / 4;
  }
  const out = new Float32Array(W * H);
  for (let my = 0; my < H; my++) for (let sx = 0; sx < W; sx++) {
    let sum = 0;
    for (let j = Math.max(0, my - 1); j <= Math.min(h, my + 1); j++)
      for (let i = Math.max(0, sx - 1); i <= Math.min(w, sx + 1); i++) sum += mean[j * W + i];
    out[my * W + sx] = sum / 9;
  }
  return out;
}

function assertSameFade(a, b, msg) {
  assert.equal(a.length, b.length, msg);
  for (let k = 0; k < a.length; k++) assert.equal(a[k], b[k], `${msg} [${k}]`);
}

// A raster canvas stand-in for the 2D context: fillRect and path fills composite on pixel
// centres exactly the two ways the mod uses them (source-over with an opaque fill,
// destination-out), arcs sampled into the polygon.
function rasterCanvas(w, h) {
  const data = new Uint8ClampedArray(w * h * 4);
  let path = [];
  const inside = (poly, x, y) => {
    const px = x + .5, py = y + .5;
    let inn = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, yi] = poly[i], [xj, yj] = poly[j];
      if ((yi > py) !== (yj > py) && px < (xj - xi) * (py - yi) / (yj - yi) + xi) inn = !inn;
    }
    return inn;
  };
  const plot = (x, y, keep, rgb) => {
    const i = (y * w + x) * 4;
    if (keep) { data[i] = rgb[0]; data[i + 1] = rgb[1]; data[i + 2] = rgb[2]; data[i + 3] = 255; }
    else data[i] = data[i + 1] = data[i + 2] = data[i + 3] = 0;
  };
  const rgb = () => {
    const m = /^rgb\((\d+),(\d+),(\d+)\)$/.exec(String(api.fillStyle));
    return m ? [+m[1], +m[2], +m[3]] : [0, 0, 0];
  };
  const api = {
    canvas: { width: w, height: h },
    fillStyle: '#000000',
    globalCompositeOperation: 'source-over',
    beginPath() { path = []; },
    moveTo(x, y) { path = [[x, y]]; },
    lineTo(x, y) { path.push([x, y]); },
    arc(x, y, r, a0, a1) {
      for (let k = 0; k <= 24; k++) {
        const a = a0 + (a1 - a0) * k / 24;
        path.push([x + r * Math.cos(a), y + r * Math.sin(a)]);
      }
    },
    closePath() { },
    fill() {
      const keep = this.globalCompositeOperation !== 'destination-out';
      const c = rgb();
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++)
        if (inside(path, x, y)) plot(x, y, keep, c);
    },
    fillRect(rx, ry, rw, rh) {
      const keep = this.globalCompositeOperation !== 'destination-out';
      const c = rgb();
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
        const px = x + .5, py = y + .5;
        if (px >= rx && px < rx + rw && py >= ry && py < ry + rh) plot(x, y, keep, c);
      }
    },
    getImageData(x, y, ww, hh) {
      const out = new Uint8ClampedArray(ww * hh * 4);
      for (let r = 0; r < hh; r++) for (let c = 0; c < ww; c++)
        out.set(data.subarray(((y + r) * w + x + c) * 4, ((y + r) * w + x + c) * 4 + 4), (r * ww + c) * 4);
      return { width: ww, height: hh, data: out };
    },
    alpha(x, y) { return data[(y * w + x) * 4 + 3]; },
    color(x, y) {
      const i = (y * w + x) * 4;
      return (data[i] << 16) | (data[i + 1] << 8) | data[i + 2];
    },
  };
  return api;
}

const K = 0x3366cc, KRGB = `rgb(${(K >> 16) & 255},${(K >> 8) & 255},${K & 255})`;

function liquidPayload(chunkCells, margin, color) {
  const cellPx = 12;
  return {
    color: color ?? { getImageData: (x, y, w, h) => ({ width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }) },
    flow: {}, cellPx, margin, chunkCells, chunk: [0, 0], unbounded: null, blur: 7,
  };
}

test('the organic blob matches 1.0’s own golden masks', () => {
  const se = load().__arpg.smoothEdges;
  for (const c of fixture.cases) {
    const got = se.blob(c.id, c.w, c.h);
    assert.equal(got.length, c.w * c.h, c.id);
    for (let y = 0; y < c.h; y++) for (let x = 0; x < c.w; x++)
      assert.equal(got[y * c.w + x], +c.rows[y][x], `${c.id} ${c.w}x${c.h} cell (${x},${y})`);
  }
});

test('a single liquid cell becomes a rounded dot inside its own square', () => {
  const se = load().__arpg.smoothEdges;
  const cv = rasterCanvas(36, 36);
  cv.fillStyle = KRGB;
  cv.fillRect(12, 12, 12, 12); // what the game painted for cell (1,1)
  se.paintShores(cv, [[0, 0, 0], [0, K, 0], [0, 0, 0]], 12);
  let outside = 0;
  for (let y = 0; y < 36; y++) for (let x = 0; x < 36; x++)
    if (cv.alpha(x, y) && !(x >= 12 && x < 24 && y >= 12 && y < 24)) outside++;
  assert.equal(outside, 0, 'nothing painted outside the cell’s own 12x12 square');
  assert.equal(cv.alpha(12, 12), 0, 'the corner is cleared');
  assert.equal(cv.alpha(13, 13), 0, 'past the half-cell circle');
  assert.equal(cv.alpha(14, 14), 255, 'inside the circle');
  assert.equal(cv.alpha(18, 18), 255, 'the centre keeps its colour');
  assert.equal(cv.color(18, 18), K);
  assert.equal(cv.alpha(12, 18), 255, 'the circle meets the cell edge');
});

test('the liquid hook reshapes the painted canvas and returns the sharper blur', () => {
  const ctx = load();
  const chunkCells = 2, margin = 1;
  const color = rasterCanvas(48, 48);
  color.fillStyle = KRGB;
  color.fillRect(24, 12, 12, 12); // cell (2,1) of the 4x4 grid, painted by the game
  const blur = ctx.__arpg.liquidCanvas(liquidPayload(chunkCells, margin, color));
  assert.equal(blur, 5, 'the mod’s blur replaces the game’s 7');
  let outside = 0;
  for (let y = 0; y < 48; y++) for (let x = 0; x < 48; x++)
    if (color.alpha(x, y) && !(x >= 24 && x < 36 && y >= 12 && y < 24)) outside++;
  assert.equal(outside, 0);
  assert.equal(color.alpha(24, 12), 0);
  assert.equal(color.alpha(30, 18), 255);
  assert.equal(ctx.__arpg.smoothEdges.stats().chunks, 1);
});

test('an L-shaped area gets its concave corner filled', () => {
  const se = load().__arpg.smoothEdges;
  const ops = se.shoreOps([[K, K, 0], [K, 0, 0]]);
  const fills = ops.filter(o => o.op === 'fill');
  assert.equal(fills.length, 1);
  assert.equal(JSON.stringify(fills.map(o => [o.x, o.y, o.dx, o.dy, o.color])),
    JSON.stringify([[1, 1, 1, 1, K]]));
  // the free ends of both arms are rounded, not left square
  assert.ok(ops.some(o => o.op === 'round' && o.x === 2 && o.y === 0));
  assert.ok(ops.some(o => o.op === 'round' && o.x === 0 && o.y === 2));
});

test('a checkerboard diagonal gets no fill', () => {
  const se = load().__arpg.smoothEdges;
  const ops = se.shoreOps([[K, 0], [0, K]]);
  assert.equal(ops.filter(o => o.op === 'fill').length, 0,
    'the two orthogonal neighbours differ, so nothing is filled');
  // each diagonal cell still has its shared corner reshaped inside its own square
  assert.ok(ops.some(o => o.op === 'round' && o.x === 1 && o.y === 1 && o.dx === -1 && o.dy === -1));
  assert.ok(ops.some(o => o.op === 'round' && o.x === 1 && o.y === 1 && o.dx === 1 && o.dy === 1));
});

test('an organic region fades along its continuous outline', () => {
  const se = load().__arpg.smoothEdges;
  const fade = se.organicFade('region_pond', 9, 7);
  const W = 10, mid = 3; // the middle vertex row
  assert.ok(fade[mid * W + 4] > 0.95, `about 1 at the centre (${fade[mid * W + 4]})`);
  for (const [sx, my] of [[0, 0], [9, 0], [0, 7], [9, 7]])
    assert.ok(fade[my * W + sx] < 0.05, `about 0 at corner (${sx},${my}) (${fade[my * W + sx]})`);
  // no staircase: along the middle row the alpha moves one way on each side of the centre
  for (let sx = 0; sx < 4; sx++)
    assert.ok(fade[mid * W + sx + 1] >= fade[mid * W + sx] - 1e-9, `left half rises at ${sx}`);
  for (let sx = 4; sx < 9; sx++)
    assert.ok(fade[mid * W + sx + 1] <= fade[mid * W + sx] + 1e-9, `right half falls at ${sx}`);
  let crossed = false; // the 0.5 contour is crossed between two vertices, not on a flat run
  for (let sx = 4; sx < 9; sx++)
    if (fade[mid * W + sx] > 0.5 && fade[mid * W + sx + 1] < 0.5) crossed = true;
  assert.ok(crossed);
});

test('a full rectangle keeps the game’s default fade everywhere', () => {
  const se = load().__arpg.smoothEdges;
  const w = 6, h = 4, mask = new Uint8Array(w * h).fill(1);
  const def = gameDefault(mask, w, h);
  assert.ok(def.some(x => x > 0 && x < 1), 'the default does fade at the rim');
  assertSameFade(se.maskFade(mask, w, h, def), def, 'with the game’s fade passed in');
  assertSameFade(se.maskFade(mask, w, h), def, 'and computed from the mask alone');
  assertSameFade(se.defaultFade(mask, w, h), def, 'the mod’s default is the game’s recipe');
});

test('a mask cut by water fades along the cut, and keeps the default at an uncut rim', () => {
  const se = load().__arpg.smoothEdges;
  const w = 9, h = 7;
  const cut = new Uint8Array(w * h).fill(1); // a full rectangle with one cell bitten out
  cut[4 * w + 4] = 0;
  const def = gameDefault(cut, w, h);
  const fade = se.maskFade(cut, w, h, def);
  // the vertices on the bite's corners are still mostly ground
  const at = (sx, y) => fade[(h - y) * (w + 1) + sx];
  assert.ok(at(4, 4) > 0.6 && at(4, 4) < 1, `bite corner ${at(4, 4)}`);
  assert.ok(at(4, 5) > 0.6 && at(4, 5) < 1, `bite corner ${at(4, 5)}`);
  assert.notEqual(fade[3 * 10 + 4], def[3 * 10 + 4], 'a vertex on the bite moves');
  // the rim the bite never touches keeps the game's fade, so the rectangle's blend stands
  assert.equal(fade[3 * 10], def[3 * 10], 'an untouched rim vertex');
  assertSameFade(new Float32Array([fade[0], fade[9], fade[7 * 10], fade[7 * 10 + 9]]),
    new Float32Array([def[0], def[9], def[7 * 10], def[7 * 10 + 9]]), 'the corners');
});

test('the same mask gets the same fade array back, routed by what it is', () => {
  const ctx = load();
  const F32 = vm.runInContext('Float32Array', ctx);
  const se = ctx.__arpg.smoothEdges;
  const region = { id: 'region_pond', position: [0, 0], size: [9, 7] };
  const def = new F32(80);
  const plain = pondMask();
  const a = ctx.__arpg.groundFade(region, plain, def);
  const b = ctx.__arpg.groundFade(region, plain, def);
  assert.equal(a, b, 'cached by mask');
  assert.notEqual(a, def);
  assertSameFade(a, se.organicFade('region_pond', 9, 7), 'a plain organic mask takes the analytic fade');
  const cut = plain.slice();
  cut[4 * 9 + 4] = 0;
  const c = ctx.__arpg.groundFade(region, cut, def);
  assert.equal(c, ctx.__arpg.groundFade(region, cut, def), 'cut masks cache too');
  assertSameFade(c, se.maskFade(cut, 9, 7, def), 'a cut mask takes the distance fade');
});

test('with the mod off both hooks leave the game’s drawing alone', () => {
  const ctx = load();
  const se = ctx.__arpg.smoothEdges;
  const F32 = vm.runInContext('Float32Array', ctx);
  const def = new F32(80);
  const region = { id: 'region_pond', position: [0, 0], size: [9, 7] };
  se.setEnabled(false);
  assert.equal(se.isEnabled(), false);
  assert.equal(ctx.__arpg.liquidCanvas(liquidPayload(32, 2)), undefined, 'no blur override');
  assert.equal(ctx.__arpg.groundFade(region, pondMask(), def), def, 'the game’s fade stands');
  se.setEnabled(true);
  assert.equal(ctx.__arpg.liquidCanvas(liquidPayload(32, 2)), 5, 'on again: the sharper blur');
});

test('a scenario can turn the whole mod, or one half of it, off', () => {
  const ctx = load();
  const F32 = vm.runInContext('Float32Array', ctx);
  const def = new F32(80);
  const region = { id: 'region_pond', position: [0, 0], size: [9, 7] };
  ctx.__vivScene = { world: { arpgMods: { 'smooth-edges': false } } };
  assert.equal(ctx.__arpg.liquidCanvas(liquidPayload(32, 2)), undefined);
  assert.equal(ctx.__arpg.groundFade(region, pondMask(), def), def);
  ctx.__vivScene.world.arpgMods['smooth-edges'] = { shores: false };
  assert.equal(ctx.__arpg.liquidCanvas(liquidPayload(32, 2)), undefined, 'shores off');
  assert.notEqual(ctx.__arpg.groundFade(region, pondMask(), def), def, 'ground still on');
  ctx.__vivScene.world.arpgMods['smooth-edges'] = { blur: 2 };
  assert.equal(ctx.__arpg.liquidCanvas(liquidPayload(32, 2)), 2, 'the scenario’s blur');
  ctx.__vivScene.world.arpgMods['smooth-edges'] = { ground: false };
  assert.equal(ctx.__arpg.groundFade(region, pondMask(), def), def, 'ground off');
});

test('stats count the chunks and fades, and reset', () => {
  const ctx = load();
  const F32 = vm.runInContext('Float32Array', ctx);
  const def = new F32(80);
  ctx.__arpg.liquidCanvas(liquidPayload(32, 2));
  ctx.__arpg.groundFade({ id: 'region_pond', position: [0, 0], size: [9, 7] }, pondMask(), def);
  const s = ctx.__arpg.smoothEdges.stats();
  assert.equal(JSON.stringify(Object.keys(s)), JSON.stringify(['chunks', 'msPerChunk', 'fades', 'msPerFade']));
  assert.ok(s.chunks >= 1 && s.fades >= 1 && s.msPerChunk >= 0 && s.msPerFade >= 0);
  ctx.__arpg.smoothEdges.resetStats();
  const z = ctx.__arpg.smoothEdges.stats();
  assert.ok(z.chunks === 0 && z.msPerChunk === 0 && z.fades === 0 && z.msPerFade === 0);
});

test('a toggle rebuilds the live scene’s water and ground tiles', () => {
  const ctx = load();
  const se = ctx.__arpg.smoothEdges;
  const calls = [];
  const tiles = new Map([['terrain-overlay:3,4:x', {}]]);
  ctx.__vivScene = {
    world: {},
    terrainLayer: {
      tiles,
      drop() { calls.push('drop'); },
      sync(world) { calls.push(['sync', world]); },
    },
    syncGroundTiles() { calls.push('ground'); },
  };
  se.setEnabled(false);
  assert.deepEqual(calls, ['drop', ['sync', ctx.__vivScene.world], 'ground']);
  assert.equal(tiles.size, 0, 'the tiles were cleared');
  // a scene without the pieces is left alone
  ctx.__vivScene = {};
  se.setEnabled(true);
});
