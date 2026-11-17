// node --test tests/*.test.mjs   (from tools/code-mod-loader)
// Third-party pack support: the foreign anchors (SMAQ's edited shapes), the manifest
// helpers, conflict detection, and — where the real files exist on this machine — a full
// pack → install → pack-remove → uninstall round-trip against the real 1.2 build.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import vm from 'node:vm';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import {
  PATCHES, patchBundle, parseManifest, resolvePackMods, sha256,
  overlapWarnings, scanModCalls, semanticOverlaps, inertPackMods, treeOf, sameTree,
  defaultPacksDir,
} from '../patch.mjs';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

// Applies one patch by name, trying the stock anchor and then the pack's edited shape
// (the same choice patchBundle makes).
function applyPatch(code, name) {
  const p = PATCHES.find(q => q.name === name);
  const variants = [[p.find, p.replace], ...(p.foreignFind ? [[p.foreignFind, p.foreignReplace]] : [])];
  for (const [find, replace] of variants) {
    if ([...code.matchAll(find)].length === 1) return code.replace(find, replace);
  }
  throw new Error(`anchor ${name} did not match`);
}

function runPatched(code, scope) {
  const ctx = vm.createContext({ ...scope, console });
  ctx.globalThis = ctx;
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'runtime/loader.js'), 'utf8'), ctx);
  vm.runInContext(`function __arpgPathOrig(){return null}${code}`, ctx);
  return ctx;
}

// Shapes copied from the stock 1.2 bundle (index-DUXqcKgD.js) and from SMAQ's replacement
// file for the same build, cut down to what each anchor needs. Both keep the 1.2 minified
// names (Lu/fA) so the stock and fog shapes differ only in the pack's own edit.
const PERCEPTION_STOCK = 'function Lu(e,t,n,i=Tn){return un(t,n)<=i}function fA(e,t,n=Tn){return Lu(e,Be(e),t,n)}';
const PERCEPTION_FOG = 'function Lu(e,t,n,i=Tn){return un(t,n)<=i&&(t!==e.player||CodexWorldVisible(e,n))}function fA(e,t,n=Tn){return Lu(e,Be(e),t,n)}';
const POINTER_FOG = 'class Scene{hitsAtPointer(n){const r=[];' +
  'for(const g of this.world.entities){if(e0(this.world,g)||!CodexWorldVisible(this.world,g))continue;r.push(g)}return r}}';

test('the perception anchors match the stock shape and SMAQ\'s fog shape, and nothing twice', () => {
  const stock = PATCHES.find(p => p.name === 'perception');
  assert.equal([...PERCEPTION_STOCK.matchAll(stock.find)].length, 1);
  assert.equal([...PERCEPTION_STOCK.matchAll(stock.foreignFind)].length, 0);
  assert.equal([...PERCEPTION_FOG.matchAll(stock.find)].length, 0);
  assert.equal([...PERCEPTION_FOG.matchAll(stock.foreignFind)].length, 1);
});

test('the pointer-hits anchors match the stock shape and SMAQ\'s fog shape', () => {
  const pointer = PATCHES.find(p => p.name === 'pointer-hits');
  assert.equal([...POINTER_FOG.matchAll(pointer.foreignFind)].length, 1);
  assert.equal([...POINTER_FOG.matchAll(pointer.find)].length, 0);
});

test('perception composes: SMAQ\'s fog answer is the seed onPerceive hooks start from', () => {
  const ctx = runPatched(applyPatch(PERCEPTION_FOG, 'perception'), {
    Tn: 14, un: (a, b) => Math.abs(a.x - b.x), Be: w => w.player,
    CodexWorldVisible: (w, b) => b.visited === true,
  });
  const seen = [];
  ctx.__arpg.onPerceive((_w, _a, b, _range, _s, answer) => { seen.push([b.x, answer]); });
  const fA = vm.runInContext('fA', ctx);
  const world = { player: { x: 0 } };
  // The player, asking about a cell still in fog, is told no even within range.
  assert.equal(fA(world, { x: 3, visited: false }), false);
  assert.equal(fA(world, { x: 3, visited: true }), true);
  // With no hooks of ours, the fog answer stands on its own.
  assert.deepEqual(seen, [[3, false], [3, true]]);
  // A hook still has the last word, either way.
  ctx.__arpg.onPerceive((_w, _a, b) => b.x !== 3, { order: 1 });
  assert.equal(fA(world, { x: 3, visited: true }), false);
});

test('pointer-hits composes: ghosted, fog-hidden and mod-hidden entities are all skipped', () => {
  const ctx = runPatched(applyPatch(POINTER_FOG, 'pointer-hits'), {
    e0: (w, g) => g.ghosted === true,
    CodexWorldVisible: (w, g) => g.visited !== false,
  });
  const world = { entities: [
    { id: 'plain' }, { id: 'ghost', ghosted: true }, { id: 'fog', visited: false },
  ] };
  const scene = vm.runInContext('new Scene', ctx);
  scene.world = world;
  // The vm returns its own realm's arrays; spread them into ours before deepEqual.
  assert.deepEqual([...scene.hitsAtPointer().map(g => g.id)], ['plain']);
  ctx.__arpg.onHidden((_w, g) => g.id === 'plain');
  assert.deepEqual([...scene.hitsAtPointer().map(g => g.id)], []);
});

test('the fog shapes chain under the same patches that the stock shapes do', () => {
  // A base with both of SMAQ's edits and nothing else our anchors would find: only the
  // two variant patches apply, which is exactly the composition on the real files.
  const out = applyPatch(PERCEPTION_FOG, 'perception') + applyPatch(POINTER_FOG, 'pointer-hits');
  assert.match(out, /CodexWorldVisible/);
  assert.match(out, /__arpg\.perceive/);
  assert.match(out, /__arpg\.hidden/);
});

const MANIFEST = {
  title: 'Sequesters Modded Additions and QOL', shortName: 'SMAQ', version: '2026.11.15.4',
  gameBuild: 26671108, sharedGameFile: 'resources/app/dist/assets/index-DUXqcKgD.js',
  stockSha256: 'a'.repeat(64), rendererSha256: 'b'.repeat(64),
  excluded: ['pocket-realms'],
  mods: [
    { id: 'passive-slots', files: ['mod-info.json', 'prompts/passive-slots.mjs'] },
    { id: 'inventory-tabs', files: ['mod-info.json', 'prompts/inventory-tabs.mjs'] },
    { id: 'pocket-realms', files: ['mod-info.json'] },
  ],
};

test('parseManifest wants the fields a pack install depends on', () => {
  assert.equal(parseManifest(MANIFEST), MANIFEST);
  for (const k of ['title', 'shortName', 'version', 'gameBuild', 'sharedGameFile', 'stockSha256', 'rendererSha256', 'mods']) {
    assert.throws(() => parseManifest({ ...MANIFEST, [k]: undefined }), new RegExp(`no ${k}`));
  }
  assert.throws(() => parseManifest({ ...MANIFEST, mods: [{ id: 'x' }] }), /mod "x" needs an id and its files/);
});

test('resolvePackMods: no ids means everything shipped minus the excluded, unknown ids are named', () => {
  assert.deepEqual(resolvePackMods([], MANIFEST), ['passive-slots', 'inventory-tabs']);
  assert.deepEqual(resolvePackMods(['inventory-tabs', 'passive-slots', 'inventory-tabs'], MANIFEST), ['inventory-tabs', 'passive-slots']);
  assert.throws(() => resolvePackMods(['pocket-realms'], MANIFEST), /no mod named "pocket-realms" in this pack \(available: passive-slots, inventory-tabs\)/);
});

test('scanModCalls reads the call and header names a mod registers', () => {
  const src = `
    __arpg.addCall('memory_add', api => ({ schema: null, run() {} }));
    __arpg.addCall("hp_delta", api => ({ schema: null, run() {} }));
    __arpg.addApiHeader('memory_add', 'text');
    __arpg.addCall(dynamicName, api => ({}));
  `;
  assert.deepEqual(scanModCalls(src), { calls: ['memory_add', 'hp_delta'], headers: ['memory_add'] });
});

test('overlapWarnings flags edits beside an anchor and passes a designed composition through', () => {
  const PREFIX = 'x'.repeat(300), SUFFIX = 'y'.repeat(300);
  const stock = PREFIX + PERCEPTION_STOCK + SUFFIX;
  // The fog edit replaces the anchor text itself, flanks untouched: composed, no warning.
  const composed = PREFIX + PERCEPTION_FOG + SUFFIX;
  assert.deepEqual(overlapWarnings(stock, composed), []);
  // An extra edit inside the flanks: flagged.
  const beside = PREFIX + PERCEPTION_FOG + 'CodexWorldRender()' + SUFFIX;
  assert.deepEqual(overlapWarnings(stock, beside), ['patch "perception" sits beside the pack\'s own edits; both are applied — play-test this area']);
});

test('semanticOverlaps names the known code-mod / pack-mod pairs', () => {
  assert.deepEqual(semanticOverlaps(['wall-aware-perception'], ['exploration-fog']),
    ['"wall-aware-perception" and "exploration-fog" both change who notices whom: hooks see the pack\'s answer first — play-test them together']);
  assert.deepEqual(semanticOverlaps(['lights'], ['exploration-fog']), []);
  assert.deepEqual(semanticOverlaps(['wall-aware-perception'], ['inventory-tabs']), []);
});

test('inertPackMods finds config mods whose .mjs needs a pack game file', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'arpg-packs-'));
  try {
    fs.mkdirSync(path.join(tmp, 'with-mjs', 'prompts'), { recursive: true });
    fs.writeFileSync(path.join(tmp, 'with-mjs', 'prompts', 'a.mjs'), 'export const x = 1;');
    fs.mkdirSync(path.join(tmp, 'text-only', 'prompts'), { recursive: true });
    fs.writeFileSync(path.join(tmp, 'text-only', 'prompts', 'b.txt'), 'prompt');
    fs.mkdirSync(path.join(tmp, 'no-prompts'), { recursive: true });
    assert.deepEqual(inertPackMods(tmp), ['with-mjs']);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('treeOf and sameTree compare an installed pack mod against its incoming copy', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'arpg-tree-'));
  try {
    const a = path.join(tmp, 'a'), b = path.join(tmp, 'b');
    for (const dir of [a, b]) {
      fs.mkdirSync(path.join(dir, 'prompts'), { recursive: true });
      fs.writeFileSync(path.join(dir, 'mod-info.json'), '{}');
      fs.writeFileSync(path.join(dir, 'prompts', 'x.mjs'), 'same');
    }
    assert.deepEqual(treeOf(a), ['mod-info.json', 'prompts/x.mjs']);
    assert.equal(sameTree(a, b), true);
    assert.equal(sameTree(a, path.join(tmp, 'missing')), false);
    fs.writeFileSync(path.join(b, 'prompts', 'x.mjs'), 'different');
    assert.equal(sameTree(a, b), false);
    fs.writeFileSync(path.join(b, 'prompts', 'x.mjs'), 'same');
    fs.writeFileSync(path.join(b, 'prompts', 'extra.txt'), '');
    assert.equal(sameTree(a, b), false, 'an extra file differs too');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('defaultPacksDir sits beside the code-mods folder in the game\'s config home', () => {
  assert.equal(defaultPacksDir('win32', { APPDATA: 'C:\\Users\\me\\AppData\\Roaming' }, 'C:\\Users\\me'),
    path.join('C:\\Users\\me\\AppData\\Roaming', 'Anywhere RPG', 'mods'));
  assert.equal(defaultPacksDir('darwin', {}, '/Users/me'),
    path.join('/Users/me', 'Library', 'Application Support', 'Anywhere RPG', 'mods'));
  assert.equal(defaultPacksDir('linux', { XDG_CONFIG_HOME: '/cfg' }, '/home/me'),
    path.join('/cfg', 'Anywhere RPG', 'mods'));
});

// The real 1.2 bundle and the real SMAQ release, where they exist on this machine.
const SMAQ_DIR = process.env.ARPG_SMAQ_DIR ??
  'C:/Users/Michael/Downloads/AnywhereRPG-Mods/SMAQ-Sequesters-Modded-Additions-and-QOL-alpha-26671108.4';
const BUNDLE_12 = process.env.ARPG_BUNDLE_12 ??
  'D:/SteamLibrary/steamapps/common/Anywhere RPG/resources/app/dist/assets/index-DUXqcKgD.js';
const HAVE_REAL = fs.existsSync(path.join(SMAQ_DIR, 'MANIFEST.json')) && fs.existsSync(BUNDLE_12);

test('the real SMAQ manifest checks out and its file chains under our patches', { skip: !HAVE_REAL && 'no SMAQ release or 1.2 bundle here' }, () => {
  const manifest = parseManifest(JSON.parse(fs.readFileSync(path.join(SMAQ_DIR, 'MANIFEST.json'), 'utf8')));
  const stock = fs.readFileSync(BUNDLE_12, 'utf8');
  const renderer = fs.readFileSync(path.join(SMAQ_DIR, ...manifest.sharedGameFile.split('/')), 'utf8');
  assert.equal(sha256(stock), manifest.stockSha256);
  assert.equal(sha256(renderer), manifest.rendererSha256);
  const out = patchBundle(renderer);
  assert.ok(out.startsWith('/*arpg-modloader*/'));
  assert.match(out, /CodexWorldVisible/, 'the pack runtime is still in place');
  // The designed compositions (fog) must not read as accidental overlaps.
  for (const w of overlapWarnings(stock, renderer)) assert.doesNotMatch(w, /perception|pointer-hits/);
  // Still valid JavaScript as a module (an injected local must never clash with a minified name).
  const tmp = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'arpg-')), 'bundle.mjs');
  try {
    fs.writeFileSync(tmp, out);
    execFileSync(process.execPath, ['--check', tmp], { stdio: 'pipe' });
  } finally {
    fs.rmSync(path.dirname(tmp), { recursive: true, force: true });
  }
});

test('pack, pack-remove and uninstall round-trip on a copy of 1.2 with the real SMAQ files', { skip: !HAVE_REAL && 'no SMAQ release or 1.2 bundle here' }, () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'arpg-game-'));
  try {
    const dist = path.join(tmp, 'game', 'resources', 'app', 'dist');
    fs.mkdirSync(path.join(dist, 'assets'), { recursive: true });
    const bundle = path.join(dist, 'assets', 'index-DUXqcKgD.js');
    fs.copyFileSync(BUNDLE_12, bundle);
    const html = '<!doctype html>\n<html>\n  <head>\n    <script type="module" crossorigin src="./assets/index-DUXqcKgD.js"></script>\n  </head>\n</html>\n';
    fs.writeFileSync(path.join(dist, 'index.html'), html);
    const env = { ...process.env, APPDATA: path.join(tmp, 'appdata'), XDG_CONFIG_HOME: path.join(tmp, 'appdata'), HOME: tmp };
    const packs = path.join(tmp, 'appdata', 'Anywhere RPG', 'mods');
    const mods = path.join(tmp, 'appdata', 'Anywhere RPG', 'code-mods');
    fs.mkdirSync(path.join(mods, 'memory-add'), { recursive: true });
    fs.writeFileSync(path.join(mods, 'memory-add', 'mod.js'), "__arpg.registerMod('memory-add')");
    if (process.platform === 'darwin') return; // macOS keeps code-mods under ~/Library, which HOME already covers
    const run = (cmd, ...names) => execFileSync(process.execPath,
      [path.join(ROOT, 'patch.mjs'), cmd, ...names, '--game', path.join(tmp, 'game')], { env, encoding: 'utf8' });
    // patch.mjs reports failures on stderr ("error: …"), which execFileSync keeps off .message.
    const runFail = (cmd, ...names) => {
      try { run(cmd, ...names); } catch (e) { return `${e.stderr}\n${e.message}`; }
      assert.fail(`expected "patch.mjs ${cmd} ${names.join(' ')}" to fail`);
    };

    const out = run('pack', SMAQ_DIR, 'passive-slots', 'inventory-tabs');
    assert.match(out, /Anywhere RPG 1\.2\)/);
    assert.doesNotMatch(out, /warning: this loader/);
    assert.match(out, /pack: Sequesters Modded Additions and QOL 2026\.11\.15\.4 \(build 26671108\) — mods: passive-slots, inventory-tabs/);
    assert.match(out, /pack base: Sequesters Modded Additions and QOL/);
    const live = fs.readFileSync(bundle, 'utf8');
    assert.ok(live.startsWith('/*arpg-modloader*/'));
    assert.match(live, /CodexWorldVisible/, 'the pack runtime is layered under our patches');
    assert.equal(fs.readFileSync(bundle + '.arpg-orig', 'utf8'), fs.readFileSync(BUNDLE_12, 'utf8'), 'stock kept');
    assert.ok(fs.existsSync(bundle + '.arpg-pack') && fs.existsSync(bundle + '.arpg-pack.json'));
    assert.ok(fs.existsSync(path.join(packs, 'passive-slots', 'prompts', 'passive-slots.mjs')));
    assert.ok(fs.existsSync(path.join(packs, 'inventory-tabs', 'mod-info.json')));
    const page = fs.readFileSync(path.join(dist, 'index.html'), 'utf8');
    assert.match(page, /arpg-mods\/memory-add\.js/);

    // An unknown mod id changes nothing.
    assert.match(runFail('pack', SMAQ_DIR, 'no-such-mod'), /no mod named "no-such-mod"/);
    assert.equal(fs.existsSync(path.join(packs, 'no-such-mod')), false);

    // A release for another build is refused before any write: same pack, but its manifest
    // names a stock the installed game doesn't have.
    const badPack = path.join(tmp, 'pack-bad');
    fs.mkdirSync(path.join(badPack, 'resources', 'app', 'dist', 'assets'), { recursive: true });
    fs.copyFileSync(path.join(SMAQ_DIR, 'resources', 'app', 'dist', 'assets', 'index-DUXqcKgD.js'),
      path.join(badPack, 'resources', 'app', 'dist', 'assets', 'index-DUXqcKgD.js'));
    fs.writeFileSync(path.join(badPack, 'MANIFEST.json'),
      JSON.stringify({ ...JSON.parse(fs.readFileSync(path.join(SMAQ_DIR, 'MANIFEST.json'), 'utf8')), stockSha256: '0'.repeat(64) }));
    assert.match(runFail('pack', badPack, 'passive-slots'), /don't match the stock it was made from/);
    assert.equal(fs.existsSync(bundle + '.arpg-pack.json'), true, 'the good layer is untouched');

    const st = run('status');
    assert.match(st, /bundle: index-DUXqcKgD\.js — patched/);
    assert.match(st, /pack: Sequesters Modded Additions and QOL 2026\.11\.15\.4 \(build 26671108\) — mods: passive-slots, inventory-tabs/);

    run('pack-remove', 'passive-slots');
    assert.equal(fs.existsSync(path.join(packs, 'passive-slots')), false);
    assert.ok(fs.existsSync(path.join(packs, 'inventory-tabs')));
    assert.deepEqual(JSON.parse(fs.readFileSync(bundle + '.arpg-pack.json', 'utf8')).mods, ['inventory-tabs']);

    run('pack-remove');
    assert.equal(fs.existsSync(bundle + '.arpg-pack'), false);
    assert.equal(fs.existsSync(bundle + '.arpg-pack.json'), false);
    assert.equal(fs.existsSync(path.join(packs, 'inventory-tabs')), false);
    assert.ok(fs.readFileSync(bundle, 'utf8').startsWith('/*arpg-modloader*/'), 'the loader is back on stock');

    run('uninstall');
    assert.equal(fs.readFileSync(bundle, 'utf8'), fs.readFileSync(BUNDLE_12, 'utf8'));
    assert.equal(fs.readFileSync(path.join(dist, 'index.html'), 'utf8'), html);
    assert.deepEqual(fs.readdirSync(dist).sort(), ['assets', 'index.html']);
    assert.deepEqual(fs.readdirSync(path.join(dist, 'assets')), ['index-DUXqcKgD.js']);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});
