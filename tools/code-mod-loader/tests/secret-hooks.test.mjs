// node --test tests/*.test.mjs   (from tools/code-mod-loader)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import vm from 'node:vm';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { PATCHES, patchBundle } from '../patch.mjs';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const byName = name => PATCHES.find(p => p.name === name);

// Shapes copied from the 1.0 bundle (index-BrLojUrw.js), cut down to what each anchor needs:
// the wall-edge builder's head, the scene's sprite sync and pointer hit test, the shared door
// list's builder, the movement grid's per-walker door loop, the door swing test, and the GM's
// doorway list.
const WALLS = 'function zc(e){const t=new Map,n=new Map,i=new Map,o=new Map,g=new Map(e.map(m=>[m,!!m.wall]));' +
  'return{regions:e,walled:[...g.values()]}}';
const SYNC = 'function sync(){const l=this.viewRect(),d=1;let A=0;const culled=[];' +
  'for(const P of this.world.entities){const B=this.ensureView(P),U=this.sx(P.pos[0]+P.size[0]/2),' +
  'z=this.sy(P.pos[1]+P.size[1]/2);const k=P.size[0]*d/2,j=P.size[1]*d/2;' +
  'if(U+k<l.x||U-k>l.right||z+j<l.y||z-j>l.bottom){A++,B.container.setVisible(!1),B.overhead.setVisible(!1),' +
  'this.syncEntityLight(P,U,z),culled.push(P);continue}' +
  'B.container.setVisible(!0),B.overhead.setVisible(!0)}return{A,culled}}';
const HITS = 'function hitsAtPointer(n){const i={x:n.x,y:n.y},r=[];' +
  'for(const m of this.world.entities){if(Cv(this.world,m))continue;r.push({entity:m,over:!0})}return r}';
const DOOR_LIST = 'function nfe(e,t,n,i){var g,r;xn.n=0,xn.doors.length=0;const o=[yi(e)];' +
  'for(const m of o)fr(m.position[0]),fr(m.position[1]),fr(m.size[0]),fr(m.size[1]);' +
  'if(!t){for(const m of e.entities)if(!(m.dead||m===n||m===i||m.type!=="object"||m.attachment)){' +
  'if((g=m.objectTemplate)!=null&&g.door){dt(m,"locked")&&xn.doors.push(m);continue}' +
  'fr(Math.floor(m.pos[0])),fr(Math.floor(m.pos[1])),fr(m.size[0]),fr(m.size[1])}}return xn.doors}';
const NAV = 'class Yt{constructor(t,n,r){this.shutDoors=[];const a=null;' +
  'if(this.fp=a,n&&!r){const u=Pb(n);for(const c of xn.doors)C1(t,u,c)||this.shutDoors.push(c)}}}';
const SWING = 'function Pfe(e,t,n){if(n.dead||n.type!=="npc"&&n.type!=="player")return!1;' +
  'const i=0;return!dt(t,"locked")||C1(e,Pb(n),t)}';
const DOORWAYS = 'function KB(e,t,n,i){const o=Pe(t);let g=kfe(e,n,o);' +
  'n||(g=g.filter(s=>qe(s.crossings[0].cell,o)<=wn));return g}';

// Applies each patch to its shape, loads the loader, and returns the context.
function loadShapes(shapes, scope, { loader = true } = {}) {
  const ctx = vm.createContext({ console: { info() {}, error() {}, warn() {} }, ...scope });
  ctx.globalThis = ctx;
  if (loader) vm.runInContext(fs.readFileSync(path.join(ROOT, 'runtime/loader.js'), 'utf8'), ctx, { filename: 'runtime/loader.js' });
  for (const [code, name] of shapes) {
    const p = byName(name);
    assert.equal([...code.matchAll(p.find)].length, 1, `${name} matches its shape exactly once`);
    vm.runInContext(code.replace(p.find, p.replace), ctx, { filename: name });
  }
  return ctx;
}

const runPatched = (code, name, scope, opts) => loadShapes([[code, name]], scope, opts);
// Arrays the patched code builds inside the vm belong to that realm; copy them out before
// deepEqual (strict deep-equality compares prototypes).
const host = a => [...a];
const loaderCtx = (scope = {}) => {
  const ctx = vm.createContext({ console: { info() {}, error() {}, warn() {} }, ...scope });
  ctx.globalThis = ctx;
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'runtime/loader.js'), 'utf8'), ctx, { filename: 'runtime/loader.js' });
  return ctx;
};
const quiet = () => {
  const warns = [];
  return { console: { info() {}, error() {}, warn: (...a) => warns.push(a) }, warns };
};

// The game's own dt: a locked door carries the "locked" mechanic.
const dt = (e, t) => !!(e.statusEffects ?? []).some(s => s.def?.mechanics?.some(m => m.type === t));
const LOCKED = () => [{ def: { mechanics: [{ type: 'locked' }] } }];
const door = (name, { locked = false } = {}) => ({
  type: 'object', name, pos: [10, 5], size: [0, 1],
  objectTemplate: { door: 'door' }, statusEffects: locked ? LOCKED() : [],
});
const person = (name, keys) => ({ type: 'player', name, keys });
// The game's own key test stand-in: a walker's key templates are door names.
const Pb = n => n.keys, C1 = (_t, keys, d) => keys.includes(d.name);

test('wall-regions: no loader and no hooks leave the regions alone', () => {
  const regions = [{ wall: 'stone' }, {}];
  for (const opts of [{ loader: false }, {}]) {
    const ctx = runPatched(WALLS, 'wall-regions', {}, opts);
    const out = vm.runInContext('zc', ctx)(regions);
    assert.equal(out.regions, regions, JSON.stringify(opts));
    assert.deepEqual(host(out.walled), [true, false]);
  }
  const ctx = runPatched(WALLS, 'wall-regions', {});
  assert.equal(ctx.__arpg.wallRegions(regions), regions, 'the dispatcher returns them unchanged');
});

test('wall-regions: hooks chain in order, a throwing or non-array one is skipped, and the world is the last seen', () => {
  const { console, warns } = quiet();
  const ctx = runPatched(WALLS, 'wall-regions', { console });
  const world = { regions: [] };
  ctx.__arpg.worldCreated(world, {}, false);
  const seen = [];
  ctx.__arpg.onWallRegions((r, w) => { seen.push(w); return [...r, 'b']; }, { order: 1 });
  ctx.__arpg.onWallRegions(() => { throw new Error('boom'); }, { order: 2 });
  ctx.__arpg.onWallRegions(r => r.length, { order: 3 }); // not an array: skipped
  ctx.__arpg.onWallRegions(r => [...r, 'a'], { order: 5 }); // registered last, runs last
  const out = vm.runInContext('zc', ctx)(['x']);
  assert.deepEqual(out.regions, ['x', 'b', 'a']);
  assert.equal(seen[0], world, 'the hook gets the last world the loader has seen');
  assert.equal(warns.length, 1, 'the throwing hook is warned once');
  assert.match(String(warns[0][0]), /wall-regions hook failed/);
});

test('entity-hidden: the off-screen cull stands, and a hidden hook takes an on-screen entity off it', () => {
  const ctx = runPatched(SYNC, 'entity-hidden', {});
  const vis = [];
  const lights = [];
  const scene = {
    world: { entities: [] },
    viewRect: () => ({ x: 0, right: 100, y: 0, bottom: 100 }),
    sx: x => x, sy: y => y,
    syncEntityLight: (...a) => lights.push(a),
    ensureView: () => ({ container: { setVisible: v => vis.push(v) }, overhead: { setVisible() {} } }),
  };
  const sync = vm.runInContext('sync', ctx);
  const near = { pos: [10, 10], size: [2, 2] }, far = { pos: [500, 10], size: [2, 2] };
  scene.world.entities = [near, far];
  assert.deepEqual(host(sync.call(scene).culled), [far], 'only the off-screen entity');
  assert.deepEqual(vis, [true, false], 'near shown, far hidden');
  assert.deepEqual(lights.map(l => l[0]), [far], 'the light sync runs in the cull branch');

  const asked = [];
  ctx.__arpg.onHidden((w, e) => { asked.push([w, e]); return e.secret; });
  near.secret = true;
  assert.deepEqual(host(sync.call(scene).culled), [near, far], 'the hidden on-screen entity is culled too');
  assert.equal(asked[0][0], scene.world, 'the hook gets the scene\'s world');
  assert.equal(asked[0][1], near);
});

test('pointer-hits: the game\'s own skip stands, and a hidden hook skips more', () => {
  const ctx = runPatched(HITS, 'pointer-hits', { Cv: (w, e) => !!e.ghosted });
  const plain = { pos: [1, 1] }, ghost = { pos: [2, 2], ghosted: true }, secret = { pos: [3, 3] };
  const scene = { world: { entities: [plain, ghost, secret] } };
  const hitsAtPointer = vm.runInContext('hitsAtPointer', ctx);
  assert.deepEqual(host(hitsAtPointer.call(scene, { x: 1, y: 1 }).map(h => h.entity)), [plain, secret],
    'the ghosted one is skipped, the others hit');
  ctx.__arpg.onHidden((_w, e) => e === secret);
  assert.deepEqual(host(hitsAtPointer.call(scene, { x: 1, y: 1 }).map(h => h.entity)), [plain], 'the hidden one is not hit');
});

test('door-list: locked doors make the list; a gated hook adds an unlocked one', () => {
  const xn = { doors: [], n: 0 };
  const scope = { xn, yi: () => ({ position: [0, 0], size: [1, 1] }), fr: () => {}, dt };
  const world = {
    entities: [
      door('plain', { locked: false }),
      { ...door('chest', { locked: false }), objectTemplate: {} }, // not a door
      door('shut', { locked: true }),
    ],
  };
  for (const opts of [{ loader: false }, {}]) {
    const ctx = runPatched(DOOR_LIST, 'door-list', scope, opts);
    assert.deepEqual(vm.runInContext('nfe', ctx)(world, null, null, null), [world.entities[2]], JSON.stringify(opts));
  }
  const { console, warns } = quiet();
  const ctx = runPatched(DOOR_LIST, 'door-list', { ...scope, console });
  const gated = [];
  ctx.__arpg.onDoor({
    gated: (w, d) => { gated.push([w, d]); return d === world.entities[0]; },
    passes: () => { throw new Error('never asked'); }, // the list test never asks
  });
  assert.deepEqual(vm.runInContext('nfe', ctx)(world, null, null, null), [world.entities[0], world.entities[2]]);
  assert.deepEqual(gated, [[world, world.entities[0]]],
    'the unlocked door is offered; a locked one never needs asking, and the chest never is');
  assert.equal(warns.length, 0);
});

test('door-pass-nav: no hooks give the game\'s key rule, and the game\'s own guards still hold', () => {
  const xn = { doors: [] };
  const ctx = runPatched(NAV, 'door-pass-nav', { xn, Pb, C1 });
  const Yt = vm.runInContext('Yt', ctx);
  const world = {};
  const brass = door('brass', { locked: true }), iron = door('iron', { locked: true });
  xn.doors = [brass, iron];
  assert.deepEqual(host(new Yt(world, person('Wren', ['brass'])).shutDoors), [iron], 'the key opens brass');
  assert.deepEqual(host(new Yt(world, person('Hal', [])).shutDoors), [brass, iron], 'no keys: both shut');
  assert.deepEqual(host(new Yt(world, person('Wren', ['brass']), true).shutDoors), [], 'a query (third flag set) never asks');
  assert.deepEqual(host(new Yt(world, null).shutDoors), [], 'no walker: never asks');
});

test('door-pass-nav: a gated unlocked door reaches the hooks, which decide per walker', () => {
  const xn = { doors: [] };
  const ctx = loadShapes([[DOOR_LIST, 'door-list'], [NAV, 'door-pass-nav']],
    { xn, yi: () => ({ position: [0, 0], size: [1, 1] }), fr: () => {}, dt, Pb, C1 });
  const secret = door('secret'); // unlocked: only a hook can put it on the list
  const iron = door('iron', { locked: true });
  const world = { entities: [secret, iron] };
  ctx.__arpg.onDoor({
    gated: (_w, d) => d === secret,
    passes: (_w, d, walker) => (d === secret ? walker?.name === 'Wren' : undefined),
  });
  vm.runInContext('nfe', ctx)(world, null, null, null); // builds xn.doors
  assert.deepEqual(xn.doors, [secret, iron], 'the gated door is on the list');
  const Yt = vm.runInContext('Yt', ctx);
  assert.deepEqual(host(new Yt(world, person('Wren', [])).shutDoors), [iron], 'Wren knows the secret door');
  assert.deepEqual(host(new Yt(world, person('Hal', ['iron'])).shutDoors), [secret], 'Hal does not, but holds the iron key');
});

test('door-pass-nav: a passes hook that returns undefined leaves the key rule alone', () => {
  const xn = { doors: [] };
  const ctx = runPatched(NAV, 'door-pass-nav', { xn, Pb, C1 });
  const brass = door('brass', { locked: true });
  xn.doors = [brass];
  ctx.__arpg.onDoor({ passes: () => undefined });
  const Yt = vm.runInContext('Yt', ctx);
  assert.deepEqual(host(new Yt({}, person('Wren', ['brass'])).shutDoors), []);
  assert.deepEqual(host(new Yt({}, person('Hal', [])).shutDoors), [brass]);
});

test('door-pass-nav: the key test runs only for a locked door', () => {
  const xn = { doors: [] };
  let asked = 0;
  const C1count = (...a) => (asked++, C1(...a));
  const ctx = runPatched(NAV, 'door-pass-nav', { xn, Pb, C1: C1count });
  const open = door('open'), shut = door('shut', { locked: true });
  xn.doors = [open, shut];
  const Yt = vm.runInContext('Yt', ctx);
  assert.deepEqual(host(new Yt({}, person('Wren', ['shut'])).shutDoors), []);
  assert.equal(asked, 1, 'only the locked door asked for its key');
});

test('door-pass-swing: with no loader, and with no hooks, the game\'s answer stands', () => {
  const world = {};
  for (const opts of [{ loader: false }, {}]) {
    const ctx = runPatched(SWING, 'door-pass-swing', { dt, Pb, C1 }, opts);
    const Pfe = vm.runInContext('Pfe', ctx);
    const label = JSON.stringify(opts);
    assert.equal(Pfe(world, door('iron', { locked: true }), person('Wren', ['brass'])), false, `locked, no key ${label}`);
    assert.equal(Pfe(world, door('brass', { locked: true }), person('Wren', ['brass'])), true, `locked, keyed ${label}`);
    assert.equal(Pfe(world, door('any'), person('Wren', ['brass'])), true, `unlocked ${label}`);
    assert.equal(Pfe(world, door('any'), { type: 'object', keys: [] }), false, `not a person ${label}`);
    assert.equal(Pfe(world, door('any'), { ...person('Ghost', []), dead: true }), false, `dead ${label}`);
  }
});

test('door-pass-swing: the key test runs only for a locked door', () => {
  let asked = 0;
  const C1count = (...a) => (asked++, C1(...a));
  const ctx = runPatched(SWING, 'door-pass-swing', { dt, Pb, C1: C1count });
  const Pfe = vm.runInContext('Pfe', ctx);
  const world = {}, wren = person('Wren', []);
  assert.equal(Pfe(world, door('open'), wren), true);
  assert.equal(Pfe(world, door('brass', { locked: true }), wren), false);
  assert.equal(asked, 1, 'only the locked door asked for its key');
});

test('door-pass-swing: a passes hook opens a door for one person and shuts it for another', () => {
  const ctx = runPatched(SWING, 'door-pass-swing', { dt, Pb, C1 });
  const Pfe = vm.runInContext('Pfe', ctx);
  const world = {};
  const secret = door('secret', { locked: true });
  ctx.__arpg.onDoor({ passes: (_w, d, walker) => (d === secret ? walker?.name === 'Wren' : undefined) });
  assert.equal(Pfe(world, secret, person('Wren', [])), true, 'Wren holds it open without a key');
  assert.equal(Pfe(world, secret, person('Hal', [])), false, 'Hal does not');
  const open = door('open'); // unlocked, but the hook shuts it
  ctx.__arpg.onDoor({ passes: (_w, d) => (d === open ? false : undefined) }, { order: 5 });
  assert.equal(Pfe(world, open, person('Wren', [])), false);
});

test('gm-doorways: every doorway stands, until a hook drops one', () => {
  const hall = { crossings: [{ cell: [9, 5] }], room: 'hall', doors: [] };
  const cell = { crossings: [{ cell: [3, 1] }], room: 'cell', doors: [{ name: 'secret' }] };
  const scope = { Pe: () => ({ x: 0, y: 0 }), kfe: () => [hall, cell], qe: () => 0, wn: 14 };
  for (const opts of [{ loader: false }, {}]) {
    const ctx = runPatched(DOORWAYS, 'gm-doorways', scope, opts);
    assert.deepEqual(vm.runInContext('KB', ctx)({}, { pos: [1, 1] }, null, 10), [hall, cell], JSON.stringify(opts));
  }
  const ctx = runPatched(DOORWAYS, 'gm-doorways', scope);
  const asked = [];
  ctx.__arpg.onDoorway((w, d) => { asked.push([w, d]); return d.doors.length === 0; });
  assert.deepEqual(vm.runInContext('KB', ctx)({}, { pos: [1, 1] }, null, 10), [hall]);
  assert.deepEqual(asked, [[{}, hall], [{}, cell]], 'each doorway is offered with the world');
});

// The dispatchers themselves, where the patched shapes above only cover one call site each.
test('hidden with no hooks is false', () => {
  const ctx = loaderCtx();
  assert.equal(ctx.__arpg.hidden({}, {}), false);
});

test('doorPasses: the native answer, then each hook in order', () => {
  const ctx = loaderCtx();
  const world = {}, wren = person('Wren', []);
  let keyAsked = 0;
  const keyPass = () => (keyAsked++, false);
  assert.equal(ctx.__arpg.doorPasses(world, door('open'), wren, keyPass), true, 'unlocked: the key is never asked');
  assert.equal(keyAsked, 0);
  assert.equal(ctx.__arpg.doorPasses(world, door('shut', { locked: true }), wren, keyPass), false, 'locked: keyPass()');
  assert.equal(keyAsked, 1);
  ctx.__arpg.onDoor({ passes: () => undefined });
  assert.equal(ctx.__arpg.doorPasses(world, door('shut', { locked: true }), wren, keyPass), false, 'undefined keeps it');
  assert.equal(keyAsked, 2);
  ctx.__arpg.onDoor({ passes: () => false }, { order: 1 });
  ctx.__arpg.onDoor({ passes: (_w, _d, walker, native) => walker?.name === 'Wren' ? true : native }, { order: 5 });
  assert.equal(ctx.__arpg.doorPasses(world, door('open'), wren, keyPass), true);
  assert.equal(ctx.__arpg.doorPasses(world, door('open'), person('Hal', []), keyPass), false,
    'higher order runs later and has the last word');
  assert.equal(ctx.__arpg.doorPasses(world, door('shut', { locked: true }), undefined, keyPass), false,
    'an unset walker passes through');
});

test('doorGated and doorwayShown', () => {
  const ctx = loaderCtx();
  const world = {}, theDoor = door('secret');
  assert.equal(ctx.__arpg.doorGated(world, theDoor), false, 'no hooks: nothing is gated');
  ctx.__arpg.onDoor({ gated: (_w, d) => d === theDoor });
  assert.equal(ctx.__arpg.doorGated(world, theDoor), true);
  assert.equal(ctx.__arpg.doorGated(world, door('other')), false);

  assert.equal(ctx.__arpg.doorwayShown(world, {}), true, 'no hooks: every doorway is shown');
  const order = [];
  ctx.__arpg.onDoorway((_w, d) => { order.push(['first', d]); return undefined; }, { order: 1 });
  ctx.__arpg.onDoorway((_w, d) => { order.push(['second', d]); return false; }, { order: 5 });
  assert.equal(ctx.__arpg.doorwayShown(world, 'd1'), false);
  assert.deepEqual(order, [['first', 'd1'], ['second', 'd1']], 'lower order runs first');
});

test('hasMechanic matches the game\'s own dt', () => {
  const ctx = loaderCtx();
  for (const e of [door('a'), door('b', { locked: true }), { statusEffects: [] },
    { statusEffects: [{ def: { mechanics: [{ type: 'phasing' }] } }] }, {}]) {
    assert.equal(ctx.__arpg.hasMechanic(e, 'locked'), dt(e, 'locked'), JSON.stringify(e.statusEffects));
  }
});

test('lastWorld follows world creation, ticks and prompts', () => {
  const ctx = loaderCtx();
  const a = { tick: true }, b = { tick: true }, c = { prompt: true };
  ctx.__arpg.worldCreated(a, {}, false);
  assert.equal(ctx.__arpg.lastWorld, a);
  ctx.__arpg.tick(b);
  assert.equal(ctx.__arpg.lastWorld, b);
  ctx.__arpg.prompt({ head: [], sections: [], tail: [] }, c, {});
  assert.equal(ctx.__arpg.lastWorld, c);
});

test('hidden and doorway hooks survive a thrower, warned once', () => {
  const { console, warns } = quiet();
  const ctx = loaderCtx({ console });
  ctx.__arpg.onHidden(() => { throw new Error('boom'); });
  ctx.__arpg.onHidden(() => true);
  assert.equal(ctx.__arpg.hidden({}, {}), true);
  assert.equal(ctx.__arpg.hidden({}, {}), true);
  ctx.__arpg.onDoorway(() => { throw new Error('boom'); });
  assert.equal(ctx.__arpg.doorwayShown({}, {}), true);
  assert.equal(ctx.__arpg.doorwayShown({}, {}), true);
  ctx.__arpg.onDoor({ gated: () => { throw new Error('boom'); }, passes: () => { throw new Error('boom'); } });
  assert.equal(ctx.__arpg.doorGated({}, {}), false);
  assert.equal(ctx.__arpg.doorPasses({}, door('open'), null, () => true), true);
  assert.equal(ctx.__arpg.doorPasses({}, door('open'), null, () => true), true);
  assert.equal(warns.length, 3, 'one per hook');
  for (const w of warns) assert.match(String(w[0]), /hook failed$/);
});

// The pristine 1.0 snapshot, where it exists on this machine (it isn't in the repo).
const BUNDLE_10 = process.env.ARPG_BUNDLE_10 ??
  'E:/Misc Projects/Anywhere RPG builds/1.0-build26557354/resources/app/dist/assets/index-BrLojUrw.js';
const NAMES = ['wall-regions', 'entity-hidden', 'pointer-hits', 'door-list', 'door-pass-nav', 'door-pass-swing', 'gm-doorways'];

test('the secret-passage anchors match exactly once on the 1.0 bundle, and the patched bundle still parses', { skip: !fs.existsSync(BUNDLE_10) && 'no 1.0 bundle here' }, () => {
  const src = fs.readFileSync(BUNDLE_10, 'utf8');
  for (const name of NAMES) assert.equal([...src.matchAll(byName(name).find)].length, 1, name);
  const out = patchBundle(src);
  const count = re => [...out.matchAll(re)].length;
  assert.equal(count(/globalThis\.__arpg\.wallRegions\(/g), 1, 'wallRegions asked once');
  assert.equal(count(/globalThis\.__arpg\.hidden\(this\.world,[\w$]+\)/g), 2, 'hidden asked in the sync and the pointer test');
  assert.equal(count(/globalThis\.__arpg\.doorGated\(/g), 1, 'doorGated asked once');
  assert.equal(count(/globalThis\.__arpg\.doorPasses\(/g), 2, 'doorPasses asked at both call sites');
  assert.equal(count(/globalThis\.__arpg\.doorwayShown\(/g), 1, 'doorwayShown asked once');
  // Still valid JavaScript as a module (an injected local must never clash with a minified name).
  const tmp = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'arpg-')), 'bundle.mjs');
  try {
    fs.writeFileSync(tmp, out);
    execFileSync(process.execPath, ['--check', tmp], { stdio: 'pipe' });
  } finally {
    fs.rmSync(path.dirname(tmp), { recursive: true, force: true });
  }
});
