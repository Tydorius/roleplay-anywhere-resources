#!/usr/bin/env node
// Code-mod loader patcher for Anywhere RPG.
//
//   node patch.mjs status    [--game <install dir>]
//   node patch.mjs install   [--game <install dir>]   (re-run after adding mods or a game update)
//   node patch.mjs uninstall [--game <install dir>]
//
// It patches the installed renderer bundle by matching code content (never
// minified names), adds the loader and every mod in %APPDATA%\Anywhere RPG\code-mods
// to index.html, and keeps the untouched originals as *.arpg-orig beside them.

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MARKER = '/*arpg-modloader*/';
const ORIG = '.arpg-orig';
const DEFAULT_GAME = 'D:\\SteamLibrary\\steamapps\\common\\Anywhere RPG';
const MODS_DIR = path.join(process.env.APPDATA ?? path.join(os.homedir(), 'AppData', 'Roaming'), 'Anywhere RPG', 'code-mods');

// Each patch: a regex that must match exactly once in the bundle, and its replacement.
const PATCHES = [
  {
    name: 'api-registry',
    // The GM's api-call registry is the object literal whose first key is flavor_text.
    find: /const ([\w$]+)=\{flavor_text:/g,
    replace: (_m, name) => `const ${name}=(globalThis.__arpg??={}).api={flavor_text:`,
  },
  {
    name: 'config-reader',
    // The config-file getter, found by its own warning text. It is renamed and
    // wrapped so mods can add or rewrite prompt/config files.
    find: /function ([\w$]+)\(([\w$]+)\)\{([\w$]+)\|\|([\w$]+)\.warn\("config",`getConfigFile before loadConfig/g,
    replace: (_m, fn, arg, flag, log) =>
      `function ${fn}(${arg}){const h=globalThis.__arpg&&globalThis.__arpg.cfg;` +
      `return h?h(${arg},()=>__arpgCfgOrig(${arg})):__arpgCfgOrig(${arg})}` +
      `function __arpgCfgOrig(${arg}){${flag}||${log}.warn("config",\`getConfigFile before loadConfig`,
  },
  {
    name: 'world-create',
    // The scenario → world builder copies fields one by one, so extra scenario keys
    // would be lost. Hand mods the new world and its scenario just before it returns.
    find: /imageSettings:([\w$]+)\.imageSettings\};return ([\w$]+)\|\|\(([\w$]+)\.player&&/g,
    replace: (_m, scn, flag, world) =>
      `imageSettings:${scn}.imageSettings};globalThis.__arpg&&globalThis.__arpg.worldCreated&&` +
      `globalThis.__arpg.worldCreated(${world},${scn},${flag});return ${flag}||(${world}.player&&`,
  },
  {
    name: 'prompt-budgets',
    // Per-kind character budgets for GM prompt sections. A kind missing from the table
    // is kept whole but tagged "(0 more lines omitted)", so mods add their own kinds here.
    find: /const ([\w$]+)=\{world:(\d+),rules:/g,
    replace: (_m, name, world) => `const ${name}=(globalThis.__arpg??={}).promptBudgets={world:${world},rules:`,
  },
  {
    name: 'gm-prompt',
    // Where the GM prompt's head/sections/tail are taken for rendering; mods may add sections.
    find: /const\{head:([\w$]+),sections:([\w$]+),tail:([\w$]+)\}=([\w$]+)\(([\w$]+)\)/g,
    replace: (_m, head, sections, tail, build, world) =>
      `const{head:${head},sections:${sections},tail:${tail}}=` +
      `(globalThis.__arpg&&globalThis.__arpg.prompt?globalThis.__arpg.prompt(${build}(${world}),${world}):${build}(${world}))`,
  },
];

function parseArgs(argv) {
  const out = { cmd: argv[0] ?? 'status', game: DEFAULT_GAME };
  for (let i = 1; i < argv.length; i++) {
    if (argv[i] === '--game') out.game = argv[++i];
    else throw new Error(`unknown argument: ${argv[i]}`);
  }
  return out;
}

function locate(game) {
  const dist = path.join(game, 'resources', 'app', 'dist');
  const html = path.join(dist, 'index.html');
  if (!fs.existsSync(html)) throw new Error(`not an Anywhere RPG install (no ${html})`);
  const source = fs.existsSync(html + ORIG) ? fs.readFileSync(html + ORIG, 'utf8') : fs.readFileSync(html, 'utf8');
  const m = source.match(/<script type="module" crossorigin src="\.\/assets\/(index-[\w-]+\.js)"><\/script>/);
  if (!m) throw new Error('could not find the main bundle in index.html');
  return { dist, html, bundle: path.join(dist, 'assets', m[1]), modsOut: path.join(dist, 'arpg-mods') };
}

// Returns the bundle's original text, refreshing the backup when the game has
// replaced the file (an update or Steam's "Verify integrity").
function originalOf(file) {
  const cur = fs.readFileSync(file, 'utf8');
  if (!cur.includes(MARKER)) {
    fs.writeFileSync(file + ORIG, cur);
    return cur;
  }
  if (!fs.existsSync(file + ORIG)) throw new Error(`${file} is patched but its backup is missing`);
  return fs.readFileSync(file + ORIG, 'utf8');
}

function patchBundle(src) {
  let out = src;
  for (const p of PATCHES) {
    const hits = [...out.matchAll(p.find)].length;
    if (hits !== 1) throw new Error(`patch "${p.name}" matched ${hits} times (expected 1); the game build changed, update patch.mjs`);
    out = out.replace(p.find, p.replace);
  }
  return MARKER + '\n' + out;
}

function listMods() {
  if (!fs.existsSync(MODS_DIR)) return [];
  return fs.readdirSync(MODS_DIR, { withFileTypes: true })
    .filter(d => d.isDirectory() && fs.existsSync(path.join(MODS_DIR, d.name, 'mod.js')))
    .map(d => d.name)
    .sort();
}

function install(loc) {
  const bundleSrc = originalOf(loc.bundle);
  const patched = patchBundle(bundleSrc);

  const htmlCur = fs.readFileSync(loc.html, 'utf8');
  if (!htmlCur.includes('arpg-mods/')) fs.writeFileSync(loc.html + ORIG, htmlCur);
  const htmlSrc = fs.readFileSync(loc.html + ORIG, 'utf8');

  fs.rmSync(loc.modsOut, { recursive: true, force: true });
  fs.mkdirSync(loc.modsOut, { recursive: true });
  fs.copyFileSync(path.join(HERE, 'runtime', 'loader.js'), path.join(loc.modsOut, 'loader.js'));
  const mods = listMods();
  for (const m of mods) fs.copyFileSync(path.join(MODS_DIR, m, 'mod.js'), path.join(loc.modsOut, `${m}.js`));

  // Classic scripts run before the module bundle, so the loader and every mod
  // have registered before the game builds its registry.
  const tags = ['loader', ...mods].map(n => `    <script src="./arpg-mods/${n}.js"></script>`).join('\n');
  const html = htmlSrc.replace(/(\s*)<script type="module"/, `\n${tags}$1<script type="module"`);

  fs.writeFileSync(loc.bundle, patched);
  fs.writeFileSync(loc.html, html);
  console.log(`installed: ${path.basename(loc.bundle)} patched (${PATCHES.map(p => p.name).join(', ')})`);
  console.log(`mods (${MODS_DIR}): ${mods.length ? mods.join(', ') : '(none)'}`);
}

function uninstall(loc) {
  for (const f of [loc.bundle, loc.html]) {
    if (fs.existsSync(f + ORIG)) {
      fs.copyFileSync(f + ORIG, f);
      fs.rmSync(f + ORIG);
    }
  }
  fs.rmSync(loc.modsOut, { recursive: true, force: true });
  console.log('uninstalled: original files restored');
}

function status(loc) {
  const patched = fs.readFileSync(loc.bundle, 'utf8').includes(MARKER);
  console.log(`bundle: ${path.basename(loc.bundle)} — ${patched ? 'patched' : 'original'}`);
  console.log(`mods folder: ${MODS_DIR}`);
  console.log(`mods found: ${listMods().join(', ') || '(none)'}`);
  if (!patched) {
    const src = fs.readFileSync(loc.bundle, 'utf8');
    for (const p of PATCHES) console.log(`  anchor ${p.name}: ${[...src.matchAll(p.find)].length} match(es)`);
  }
}

try {
  const args = parseArgs(process.argv.slice(2));
  const loc = locate(args.game);
  const run = { install, uninstall, status }[args.cmd];
  if (!run) throw new Error(`unknown command: ${args.cmd}`);
  run(loc);
} catch (e) {
  console.error(`error: ${e.message}`);
  process.exit(1);
}
