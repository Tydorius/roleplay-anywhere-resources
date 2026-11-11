// node --test tests/*.test.mjs   (from tools/code-mod-loader)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import vm from 'node:vm';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { parseArgs, libraryPaths, gameVersion, bundledMods, resolveMods, defaultModsDir, PATCHES, patchBundle } from '../patch.mjs';
import { loadWithSight } from './game-1.0-sight.mjs';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

test('parseArgs takes a command, mod names and --game', () => {
  assert.deepEqual(parseArgs([]), { cmd: 'status', game: null, names: [] });
  assert.deepEqual(parseArgs(['add', 'lorebooks', '--game', 'E:\\Games\\Anywhere RPG', 'lights']),
    { cmd: 'add', game: 'E:\\Games\\Anywhere RPG', names: ['lorebooks', 'lights'] });
  assert.throws(() => parseArgs(['install', '--gmae', 'x']), /unknown argument: --gmae/);
});

test('libraryPaths reads every library from libraryfolders.vdf', () => {
  const vdf = `"libraryfolders"
{
	"0"
	{
		"path"		"C:\\\\Program Files (x86)\\\\Steam"
		"apps"
		{
			"228980"		"672897464"
		}
	}
	"1"
	{
		"path"		"D:\\\\SteamLibrary"
	}
	"2"
	{
		"path"		"/home/me/.local/share/Steam"
	}
}`;
  assert.deepEqual(libraryPaths(vdf), ['C:\\Program Files (x86)\\Steam', 'D:\\SteamLibrary', '/home/me/.local/share/Steam']);
});

test('gameVersion reads 1.0\'s build flags and 0.18\'s constant before the log levels', () => {
  assert.equal(gameVersion('const _T={release:"release",demo:"demo"},eb=_T.release;function D7(e){return eb===e}' +
    'const Xd=!1,gJ=D7(_T.release),Vs=D7(_T.demo),vJ=!0,ke=Vs&&vJ,AJ=!0,yJ=!0,tb="1.0",hs="en",d1="auto";'), '1.0');
  assert.equal(gameVersion('const WI=!1,Z9=!0,KI="0.18",Bg={},KC={error:0,warn:1,info:2};'), '0.18');
  assert.equal(gameVersion('a$="1.2.3",b={},c={error:0,warn:1}'), '1.2.3');
  assert.equal(gameVersion('KI="0.18",Bg={x:1},KC={error:0,warn:1}'), null);
  assert.equal(gameVersion('const x={release:"release",demo:"demo"},y=1;'), null);
});

test('portals, floors and performance are retired; the rest stay bundled', () => {
  const avail = bundledMods();
  assert.deepEqual(avail, ['lights', 'lorebooks', 'memory-add', 'region-groups', 'smooth-edges', 'wall-aware-perception']);
});

test('add with no names (or "all") takes every bundled mod but the samples', () => {
  const avail = bundledMods();
  const all = resolveMods([], avail);
  assert.ok(!all.includes('memory-add'));
  assert.equal(all.length, avail.length - 1);
  assert.deepEqual(resolveMods(['all'], avail), all);
  assert.deepEqual(resolveMods(['all', 'memory-add'], avail), [...all, 'memory-add']);
  assert.deepEqual(resolveMods(['lights', 'lorebooks', 'lights'], avail), ['lights', 'lorebooks']);
  assert.throws(() => resolveMods(['portals'], avail), /no bundled mod named "portals"/);
});

test('the code-mods folder follows each system\'s conventions', () => {
  assert.equal(defaultModsDir('win32', { APPDATA: 'C:\\Users\\me\\AppData\\Roaming' }, 'C:\\Users\\me'),
    path.join('C:\\Users\\me\\AppData\\Roaming', 'Anywhere RPG', 'code-mods'));
  assert.equal(defaultModsDir('darwin', {}, '/Users/me'),
    path.join('/Users/me', 'Library', 'Application Support', 'Anywhere RPG', 'code-mods'));
  assert.equal(defaultModsDir('linux', {}, '/home/me'), path.join('/home/me', '.config', 'Anywhere RPG', 'code-mods'));
  assert.equal(defaultModsDir('linux', { XDG_CONFIG_HOME: '/cfg' }, '/home/me'), path.join('/cfg', 'Anywhere RPG', 'code-mods'));
});

test('the 0.18-only patches are gone', () => {
  const names = PATCHES.map(p => p.name);
  assert.deepEqual(names, ['api-registry', 'config-reader', 'world-create', 'pathfinder', 'region-arrival',
    'region-destination', 'region-same-room', 'sim-tick', 'perception', 'line-of-sight', 'sight-blockers',
    'gm-prompt', 'liquid-canvas', 'ground-fade']);
});

// Shapes copied from the 1.0 bundle (index-BrLojUrw.js), cut down to what each anchor needs.
const WORLD_CREATE = 'function cc(e,t=!1){Rk(e);const n=t?e:Ude(e),i={saveVersion:12,regions:n.regions,' +
  'entities:n.entities,player:n.player,weatherKinds:n.weatherKinds,imageSettings:n.imageSettings};if(UN(i),n.doorsHung=!0,!t){' +
  'i.player&&(i.player.money=n.startingCurrency),zde(i);for(const o of i.entities)Pr(o)&&jM(o);Tk(i,n.unbounded)}return i}';
const GM_PROMPT = 'function JB(e,t=or()){const{head:n,sections:i,tail:o}=OCe(e,t),g=[];return{sections:[...n,...g,...i,...o]}}';
const PERCEPTION = 'function yu(e,t,n,i=wn){return fn(t,n)<=i}function Yw(e,t,n=wn){return yu(e,Be(e),t,n)}';

function runPatched(code, scope) {
  const patch = name => PATCHES.find(p => p.name === name);
  let out = code;
  for (const name of ['world-create', 'gm-prompt', 'perception']) {
    const p = patch(name);
    if ([...out.matchAll(p.find)].length === 1) out = out.replace(p.find, p.replace);
  }
  const ctx = vm.createContext({ ...scope, console });
  ctx.globalThis = ctx;
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'runtime/loader.js'), 'utf8'), ctx);
  vm.runInContext(`function __arpgPathOrig(){return null}${out}`, ctx);
  return ctx;
}

test('world-create hands mods the finished world and copies arpgMods onto it', () => {
  const calls = [];
  const ctx = runPatched(WORLD_CREATE, {
    Rk() {}, Ude: s => JSON.parse(JSON.stringify(s)), UN() {}, zde() {}, Pr: () => false, jM() {},
    Tk: (w, u) => { w.unbounded = u ?? null; },
  });
  ctx.__arpg.onWorldCreate((w, s, editing) => calls.push([w.unbounded, s.name, editing]));
  const scenario = { name: 'Thornbury', regions: [], player: { name: 'P' }, startingCurrency: 5, entities: [],
    imageSettings: {}, arpgMods: { lorebooks: [{ keys: ['ale'] }] } };
  const w = vm.runInContext('cc', ctx)({ ...scenario, entities: [] });
  assert.deepEqual(JSON.parse(JSON.stringify(w.arpgMods)), scenario.arpgMods);
  assert.equal(w.player.money, 5, 'the new-game setup still runs before the hook');
  const preview = vm.runInContext('cc', ctx)({ ...scenario, entities: [] }, true);
  assert.equal(preview.player.money, undefined);
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [[null, 'Thornbury', false], [null, 'Thornbury', true]]);
});

test('gm-prompt passes the context limits through, and mod sections reach the build', () => {
  const ctx = runPatched(GM_PROMPT, {
    or: () => ({ worldChars: 2000 }),
    OCe: (_w, l) => ({ head: [], sections: [{ kind: 'world', title: '', content: `limit ${l.worldChars}` }], tail: [] }),
  });
  const seen = [];
  ctx.__arpg.onPrompt((parts, _w, limits) => {
    seen.push(limits.worldChars);
    parts.sections.push({ kind: 'lore', title: 'Lore:', content: 'x'.repeat(limits.worldChars / 100) });
  });
  const JB = vm.runInContext('JB', ctx);
  assert.deepEqual(JSON.parse(JSON.stringify(JB({}).sections.map(s => s.kind))), ['world', 'lore']);
  assert.equal(JB({}, { worldChars: 500 }).sections[1].content.length, 5);
  assert.deepEqual(seen, [2000, 500]);
});

test('perception still reports the game\'s answer to onPerceive (no clash with 1.0\'s parameter names)', () => {
  const ctx = runPatched(PERCEPTION, { wn: 14, fn: (a, b) => Math.abs(a.x - b.x), Be: w => w.player });
  const seen = [];
  ctx.__arpg.onPerceive((_w, a, b, range, _s, answer) => { seen.push([b.x, range, answer]); return b.x !== 3; });
  const Yw = vm.runInContext('Yw', ctx);
  const world = { player: { x: 0 } };
  assert.equal(Yw(world, { x: 3 }), false);
  assert.equal(Yw(world, { x: 10 }), true);
  assert.equal(Yw(world, { x: 20 }), true);
  assert.deepEqual(seen, [[3, 14, true], [10, 14, true], [20, 14, false]]);
});

test('line-of-sight and sight-blockers hand mods 1.0\'s own sight test', () => {
  const ctx = loadWithSight([]);
  assert.equal(ctx.__arpg.game.lineClear, ctx.yN);
  assert.equal(ctx.__arpg.game.sightBlockers, ctx.Ob);
  const world = {
    regions: [{ position: [0, 0], size: [10, 10], wall: 'stone', openings: [[9, 5, 'e']] }],
    entities: [],
  };
  assert.equal(ctx.__arpg.lineOfSight(world, [5.5, 5.5], [12.5, 5.5]), true, 'through the doorway');
  assert.equal(ctx.__arpg.lineOfSight(world, [5.5, 2.5], [12.5, 2.5]), false);
  const door = { type: 'object', pos: [10, 5], size: [0, 1], objectTemplate: { door: 'door' } };
  world.entities = [door];
  assert.equal(ctx.__arpg.lineOfSight(world, [5.5, 5.5], [12.5, 5.5]), false, 'a shut door blocks');
  door.heldOpen = true;
  assert.equal(ctx.__arpg.lineOfSight(world, [5.5, 5.5], [12.5, 5.5]), true, 'held open');
  door.heldOpen = false;
  door.objectTemplate = { door: 'bars' };
  assert.equal(ctx.__arpg.lineOfSight(world, [5.5, 5.5], [12.5, 5.5]), true, 'bars are see-through');
});

// The pristine 1.0 snapshot, where it exists on this machine (it isn't in the repo).
const BUNDLE_10 = process.env.ARPG_BUNDLE_10 ??
  'E:/Misc Projects/Anywhere RPG builds/1.0-build26557354/resources/app/dist/assets/index-BrLojUrw.js';

test('every patch matches exactly once on the 1.0 bundle', { skip: !fs.existsSync(BUNDLE_10) && 'no 1.0 bundle here' }, () => {
  const src = fs.readFileSync(BUNDLE_10, 'utf8');
  assert.equal(gameVersion(src), '1.0');
  for (const p of PATCHES) assert.equal([...src.matchAll(p.find)].length, 1, p.name);
  const out = patchBundle(src);
  assert.ok(out.startsWith('/*arpg-modloader*/'));
  // Still valid JavaScript as a module (an injected local must never clash with a minified name).
  const tmp = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'arpg-')), 'bundle.mjs');
  try {
    fs.writeFileSync(tmp, out);
    execFileSync(process.execPath, ['--check', tmp], { stdio: 'pipe' });
  } finally {
    fs.rmSync(path.dirname(tmp), { recursive: true, force: true });
  }
});

test('install then uninstall on a copy of 1.0, with 0.18 leftovers', { skip: !fs.existsSync(BUNDLE_10) && 'no 1.0 bundle here' }, () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'arpg-game-'));
  try {
    const dist = path.join(tmp, 'game', 'resources', 'app', 'dist');
    fs.mkdirSync(path.join(dist, 'assets'), { recursive: true });
    const bundle = path.join(dist, 'assets', 'index-BrLojUrw.js');
    fs.copyFileSync(BUNDLE_10, bundle);
    const html = '<!doctype html>\n<html>\n  <head>\n    <script type="module" crossorigin src="./assets/index-BrLojUrw.js"></script>\n  </head>\n</html>\n';
    fs.writeFileSync(path.join(dist, 'index.html'), html);
    // What a 0.18 install leaves behind once Steam updates the game to 1.0.
    fs.writeFileSync(path.join(dist, 'index.html.arpg-orig'), html.replace('index-BrLojUrw', 'index-DSU_zx7g'));
    fs.writeFileSync(path.join(dist, 'assets', 'index-DSU_zx7g.js.arpg-orig'), '// 0.18');
    const env = { ...process.env, APPDATA: path.join(tmp, 'appdata'), XDG_CONFIG_HOME: path.join(tmp, 'appdata'), HOME: tmp };
    const mods = path.join(tmp, 'appdata', 'Anywhere RPG', 'code-mods');
    for (const m of ['portals', 'memory-add']) {
      fs.mkdirSync(path.join(mods, m), { recursive: true });
      fs.writeFileSync(path.join(mods, m, 'mod.js'), `// ${m}`);
    }
    if (process.platform === 'darwin') return; // macOS keeps code-mods under ~/Library, which HOME already covers
    const run = cmd => execFileSync(process.execPath, [path.join(ROOT, 'patch.mjs'), cmd, '--game', path.join(tmp, 'game')],
      { env, encoding: 'utf8' });

    const out = run('install');
    assert.match(out, /Anywhere RPG 1\.0\)/);
    assert.doesNotMatch(out, /warning/);
    assert.match(out, /skipped: portals/);
    assert.match(out, /stale backup.*index-DSU_zx7g/);
    const page = fs.readFileSync(path.join(dist, 'index.html'), 'utf8');
    assert.match(page, /arpg-mods\/loader\.js[\s\S]*arpg-mods\/memory-add\.js[\s\S]*index-BrLojUrw/);
    assert.doesNotMatch(page, /portals/);
    assert.equal(fs.readFileSync(path.join(dist, 'index.html.arpg-orig'), 'utf8'), html, 'the backup is 1.0\'s page now');
    assert.ok(fs.readFileSync(bundle, 'utf8').startsWith('/*arpg-modloader*/'));

    run('uninstall');
    assert.equal(fs.readFileSync(path.join(dist, 'index.html'), 'utf8'), html);
    assert.equal(fs.readFileSync(bundle, 'utf8'), fs.readFileSync(BUNDLE_10, 'utf8'));
    assert.deepEqual(fs.readdirSync(dist).sort(), ['assets', 'index.html']);
    assert.deepEqual(fs.readdirSync(path.join(dist, 'assets')), ['index-BrLojUrw.js']);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('uninstall after a game update leaves the new files alone', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'arpg-game-'));
  try {
    const dist = path.join(tmp, 'game', 'resources', 'app', 'dist');
    fs.mkdirSync(path.join(dist, 'assets'), { recursive: true });
    const html = '<script type="module" crossorigin src="./assets/index-New1.js"></script>\n';
    fs.writeFileSync(path.join(dist, 'index.html'), html);
    fs.writeFileSync(path.join(dist, 'index.html.arpg-orig'), html.replace('New1', 'Old0'));
    fs.writeFileSync(path.join(dist, 'assets', 'index-New1.js'), 'const tb="9.9";');
    fs.writeFileSync(path.join(dist, 'assets', 'index-Old0.js.arpg-orig'), '// old');
    execFileSync(process.execPath, [path.join(ROOT, 'patch.mjs'), 'uninstall', '--game', path.join(tmp, 'game')],
      { env: { ...process.env, APPDATA: path.join(tmp, 'appdata'), XDG_CONFIG_HOME: path.join(tmp, 'appdata'), HOME: tmp }, encoding: 'utf8' });
    assert.equal(fs.readFileSync(path.join(dist, 'index.html'), 'utf8'), html);
    assert.deepEqual(fs.readdirSync(dist).sort(), ['assets', 'index.html']);
    assert.deepEqual(fs.readdirSync(path.join(dist, 'assets')), ['index-New1.js']);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});
