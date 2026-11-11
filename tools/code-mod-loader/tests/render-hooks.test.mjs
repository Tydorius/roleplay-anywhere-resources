// node --test tests/*.test.mjs   (from tools/code-mod-loader)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { PATCHES, patchBundle } from '../patch.mjs';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const byName = name => PATCHES.find(p => p.name === name);

// Shapes copied from the 1.0 bundle (index-BrLojUrw.js), cut down to what each anchor needs:
// the liquid overlay's chunk painter, and the scene's groundOwners().
const LIQUID = 'function build(t,n,i){const o=Z+nl*2,g=()=>{const A=document.createElement("canvas");' +
  'return A.width=A.height=o*Wn,A.getContext("2d")},r=g(),m=g();m.fillStyle="rgb(128, 128, 0)",' +
  'm.fillRect(0,0,o*Wn,o*Wn);const c=A=>{const f=document.createElement("canvas");f.width=f.height=Z*Wn;' +
  'const v=f.getContext("2d");return v.filter=`blur(${q3e}px)`,v.drawImage(A.canvas,-nl*Wn,-nl*Wn),f},' +
  'h=`terrain-overlay:${en(n)}:x`;return{c,r,m,h}}';
const GROUND = 'function groundOwners(o){return o.map((a,p)=>{const u=z3e(a);' +
  'return{id:a.id,cell:a.position,size:a.size,depth:2+p,fade:u?GFe(u,a.size):null,alpha:IO}})}';

// Applies one patch to a shape, loads the loader, and returns the context.
function runPatched(code, name, scope) {
  const p = byName(name);
  assert.equal([...code.matchAll(p.find)].length, 1, `${name} matches the shape exactly once`);
  const ctx = vm.createContext(scope);
  ctx.globalThis = ctx;
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'runtime/loader.js'), 'utf8'), ctx);
  vm.runInContext(code.replace(p.find, p.replace), ctx);
  return ctx;
}

// A canvas stub whose 2D context records its filter, fills and every drawImage.
function stubDocument() {
  return {
    createElement() {
      const cv = { width: 0, height: 0 };
      const ctx = { filter: 'none', fillStyle: 'none', canvas: cv, fills: [], draws: [] };
      ctx.fillRect = (...args) => ctx.fills.push(args);
      ctx.drawImage = (...args) => ctx.draws.push(args);
      cv.getContext = () => ctx;
      return cv;
    },
  };
}

const quietConsole = () => {
  const warns = [];
  return { console: { info() {}, error() {}, warn: (...a) => warns.push(a) }, warns };
};

function liquidCtx(extra = {}) {
  return runPatched(LIQUID, 'liquid-canvas', {
    console, Z: 32, nl: 2, Wn: 12, q3e: 7, en: c => c.join(','),
    document: stubDocument(), ...extra,
  });
}

function groundCtx(extra = {}) {
  // The game caches the fade per mask: the same mask must get the same array back.
  const fades = new Map();
  const GFe = (mask, size) => {
    if (!fades.has(mask)) fades.set(mask, new Float32Array((size[0] + 1) * (size[1] + 1)));
    return fades.get(mask);
  };
  const ctx = runPatched(GROUND, 'ground-fade', { console, IO: 1, z3e: r => r.mask ?? null, GFe, ...extra });
  ctx.F32 = vm.runInContext('Float32Array', ctx); // the loader's realm, so instanceof holds
  ctx.GFe = GFe;
  return ctx;
}

const buildChunk = (ctx, unbounded = null) => vm.runInContext('build', ctx)(unbounded, [3, 4], 0);
const blurred = chunk => chunk.c(chunk.r).getContext().filter;
const groundOwners = (ctx, regions) => vm.runInContext('groundOwners', ctx)(regions);
const masked = () => ({ id: 'r1', position: [0, 0], size: [3, 2], mask: new Uint8Array(6) });

test('liquid-canvas: with no hook the blur and the crop are the game\'s own', () => {
  const ctx = liquidCtx();
  const chunk = buildChunk(ctx);
  assert.equal(chunk.r.canvas.width, 432, 'the painted canvases are (chunkCells+margin*2)*cellPx');
  assert.equal(chunk.m.canvas.height, 432);
  const tile = chunk.c(chunk.r);
  assert.equal(tile.width, 384, 'the blurred copy is chunkCells*cellPx');
  assert.equal(tile.getContext().filter, 'blur(7px)');
  assert.deepEqual(tile.getContext().draws, [[chunk.r.canvas, -24, -24]], 'drawn from the margin corner');
});

test('liquid-canvas: the payload the hooks get, and a returned number overrides the blur', () => {
  const ctx = liquidCtx();
  const seen = [];
  ctx.__arpg.onLiquidCanvas(p => { seen.push(p); return 12; });
  const unbounded = { deep: true };
  const chunk = buildChunk(ctx, unbounded);
  assert.equal(blurred(chunk), 'blur(12px)');
  assert.equal(seen.length, 1, 'one chunk, one call');
  const [p] = seen;
  assert.equal(p.color, chunk.r, 'the colour canvas');
  assert.equal(p.flow, chunk.m, 'the flow map');
  assert.deepEqual(
    { cellPx: p.cellPx, margin: p.margin, chunkCells: p.chunkCells, chunk: p.chunk, unbounded: p.unbounded, blur: p.blur },
    { cellPx: 12, margin: 2, chunkCells: 32, chunk: [3, 4], unbounded, blur: 7 });
});

test('liquid-canvas: the canvases the hooks get are the live, painted ones', () => {
  const ctx = liquidCtx();
  ctx.__arpg.onLiquidCanvas(p => { p.color.fillStyle = '#204020'; p.color.fillRect(0, 0, 12, 12); });
  const chunk = buildChunk(ctx);
  assert.equal(chunk.r.fillStyle, '#204020');
  assert.deepEqual(chunk.r.fills, [[0, 0, 12, 12]]);
});

test('liquid-canvas: only a finite number ≥ 0 overrides the blur', () => {
  for (const bad of [-3, Infinity, NaN, '12', null]) {
    const ctx = liquidCtx();
    ctx.__arpg.onLiquidCanvas(() => bad);
    assert.equal(blurred(buildChunk(ctx)), 'blur(7px)', `${bad} leaves the game's radius`);
  }
  const ctx = liquidCtx();
  ctx.__arpg.onLiquidCanvas(() => 0);
  assert.equal(blurred(buildChunk(ctx)), 'blur(0px)', '0 is a valid override');
});

test('liquid-canvas: a throwing hook is ignored and warned once', () => {
  const { console, warns } = quietConsole();
  const ctx = liquidCtx({ console });
  ctx.__arpg.onLiquidCanvas(() => { throw new Error('boom'); });
  assert.equal(blurred(buildChunk(ctx)), 'blur(7px)');
  assert.equal(blurred(buildChunk(ctx)), 'blur(7px)');
  assert.equal(warns.length, 1, 'once per hook, not once per chunk');
  assert.match(String(warns[0][0]), /liquid-canvas hook failed/);
});

test('liquid-canvas: higher order runs later and has the last word on the blur', () => {
  const ctx = liquidCtx();
  ctx.__arpg.onLiquidCanvas(() => 9, { order: 5 }); // registered first, runs last
  ctx.__arpg.onLiquidCanvas(() => 4, { order: 1 });
  assert.equal(blurred(buildChunk(ctx)), 'blur(9px)');
});

test('ground-fade: with no hook the game\'s own fade comes back', () => {
  const ctx = groundCtx();
  const region = masked();
  const rows = groundOwners(ctx, [region]);
  assert.equal(rows[0].fade, ctx.GFe(region.mask, [3, 2]), 'the very array the game built');
  assert.equal(rows[0].fade.length, 12, '(w+1)*(h+1) vertices');
});

test('ground-fade: a Float32Array of the right length replaces the fade', () => {
  const ctx = groundCtx();
  const region = masked();
  const seen = [];
  const mine = new ctx.F32(12);
  ctx.__arpg.onGroundFade((r, mask, def) => { seen.push([r, mask, def]); return mine; });
  assert.equal(groundOwners(ctx, [region])[0].fade, mine);
  assert.deepEqual(seen.map(([r, m]) => [r, m]), [[region, region.mask]]);
  assert.equal(seen[0][2], ctx.GFe(region.mask, [3, 2]), 'the game\'s fade is the fallback argument');
});

test('ground-fade: a wrong-length array is ignored', () => {
  const ctx = groundCtx();
  const region = masked();
  ctx.__arpg.onGroundFade(() => new ctx.F32(13));
  assert.equal(groundOwners(ctx, [region])[0].fade, ctx.GFe(region.mask, [3, 2]), 'the default stands');
});

test('ground-fade: a plain rectangle (null mask) never reaches the hooks', () => {
  const ctx = groundCtx();
  let called = 0;
  ctx.__arpg.onGroundFade(() => { called++; });
  const rows = groundOwners(ctx, [{ id: 'r2', position: [0, 0], size: [4, 4] }]);
  assert.equal(rows[0].fade, null);
  assert.equal(called, 0);
});

test('ground-fade: lower order runs first, and the first valid array wins', () => {
  const ctx = groundCtx();
  const first = new ctx.F32(12), second = new ctx.F32(12);
  ctx.__arpg.onGroundFade(() => second, { order: 5 }); // registered first, runs last
  ctx.__arpg.onGroundFade(() => first, { order: 1 });
  assert.equal(groundOwners(ctx, [masked()])[0].fade, first);
});

test('ground-fade: a throwing hook falls back to the default and is warned once', () => {
  const { console, warns } = quietConsole();
  const ctx = groundCtx({ console });
  const region = masked();
  ctx.__arpg.onGroundFade(() => { throw new Error('bad mask'); });
  assert.equal(groundOwners(ctx, [region])[0].fade, ctx.GFe(region.mask, [3, 2]));
  groundOwners(ctx, [region]);
  assert.equal(warns.length, 1);
  assert.match(String(warns[0][0]), /ground-fade hook failed/);
});

// The pristine 1.0 snapshot, where it exists on this machine (it isn't in the repo).
const BUNDLE_10 = process.env.ARPG_BUNDLE_10 ??
  'E:/Misc Projects/Anywhere RPG builds/1.0-build26557354/resources/app/dist/assets/index-BrLojUrw.js';

test('liquid-canvas and ground-fade match exactly once on the 1.0 bundle, and patch it', { skip: !fs.existsSync(BUNDLE_10) && 'no 1.0 bundle here' }, () => {
  const src = fs.readFileSync(BUNDLE_10, 'utf8');
  for (const name of ['liquid-canvas', 'ground-fade']) {
    assert.equal([...src.matchAll(byName(name).find)].length, 1, name);
  }
  const out = patchBundle(src);
  assert.match(out, /__arpg\.liquidCanvas\(\{color:[\w$]+,flow:[\w$]+,cellPx:[\w$]+,margin:[\w$]+,chunkCells:[\w$]+,chunk:[\w$]+,unbounded:[\w$]+,blur:[\w$]+\}\)/);
  assert.match(out, /globalThis\.__arpg\.groundFade\(/);
  assert.match(out, /blur\(\$\{__arpgB\}px\)/, 'the blur reads the hook-set radius');
});
