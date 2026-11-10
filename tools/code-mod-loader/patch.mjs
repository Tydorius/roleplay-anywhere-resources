#!/usr/bin/env node
// Code-mod loader patcher for Anywhere RPG.
//
//   node patch.mjs status          [--game <install dir>]
//   node patch.mjs add [mods…]     [--game <install dir>]   (copy bundled mods in, then install)
//   node patch.mjs remove <mods…>  [--game <install dir>]
//   node patch.mjs install         [--game <install dir>]   (re-run after adding mods or a game update)
//   node patch.mjs uninstall       [--game <install dir>]
//
// It patches the installed renderer bundle by matching code content (never
// minified names), adds the loader and every mod in the code-mods folder
// to index.html, and keeps the untouched originals as *.arpg-orig beside them.
// Without --game it looks for the game in every Steam library.

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const EXAMPLES = path.join(HERE, 'examples');
const MARKER = '/*arpg-modloader*/';
const ORIG = '.arpg-orig';
// This loader's release (README's version table), and the game version its patches were built
// against. main supports Anywhere RPG 1.0 only; the 0.18 loader stays on the 0.18 branch.
const LOADER_VERSION = '2.0.0';
const TESTED = '1.0';
// memory-add only shows how to add a GM call, so "add" with no names leaves it out.
const SAMPLES = new Set(['memory-add']);
// Retired on main because Anywhere RPG 1.0 does them natively; they stay on the 0.18 branch.
// A copy left in the code-mods folder from 0.18 is skipped (it calls APIs that 2.0 removed).
export const RETIRED = new Set(['portals', 'floors', 'performance']);

// Where your code mods live; install copies them into the game. On Windows it sits beside the
// game's own mods folder, elsewhere in the usual per-user config folder.
export function defaultModsDir(platform = process.platform, env = process.env, home = os.homedir()) {
  if (platform === 'win32') return path.join(env.APPDATA ?? path.join(home, 'AppData', 'Roaming'), 'Anywhere RPG', 'code-mods');
  if (platform === 'darwin') return path.join(home, 'Library', 'Application Support', 'Anywhere RPG', 'code-mods');
  return path.join(env.XDG_CONFIG_HOME || path.join(home, '.config'), 'Anywhere RPG', 'code-mods');
}
const MODS_DIR = defaultModsDir();

// Each patch: a regex that must match exactly once in the bundle, and its replacement.
export const PATCHES = [
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
      `function ${fn}(${arg}){const __arpgH=globalThis.__arpg&&globalThis.__arpg.cfg;` +
      `return __arpgH?__arpgH(${arg},()=>__arpgCfgOrig(${arg})):__arpgCfgOrig(${arg})}` +
      `function __arpgCfgOrig(${arg}){${flag}||${log}.warn("config",\`getConfigFile before loadConfig`,
  },
  {
    name: 'world-create',
    // The scenario → world builder copies fields one by one, so extra scenario keys would be
    // lost. Its tail is `imageSettings:n.imageSettings};if(…,!editing){…new-game setup…}return world}`.
    // Hand mods the finished world and its scenario just before it returns.
    find: /imageSettings:([\w$]+)\.imageSettings\};(if\([^{}]{0,200},!([\w$]+)\)\{[^{}]{0,400}\})return ([\w$]+)\}/g,
    replace: (_m, scn, setup, flag, world) =>
      `imageSettings:${scn}.imageSettings};${setup}globalThis.__arpg&&globalThis.__arpg.worldCreated&&` +
      `globalThis.__arpg.worldCreated(${world},${scn},${flag});return ${world}}`,
  },
  {
    name: 'pathfinder',
    // The grid A* that every walk uses (GM beats, schedules, followers). Renamed and
    // wrapped so mods can route through places the grid doesn't connect.
    find: /function ([\w$]+)\(([\w$]+),([\w$]+),([\w$]+),([\w$]+),([\w$]+)=\{\}\)\{(?=const [\w$]+=\5\?\[Math\.round\(\3\[0\]\),Math\.round\(\3\[1\]\)\])/g,
    replace: (_m, fn, t, from, dest, ent, opts) =>
      `function ${fn}(${t},${from},${dest},${ent},${opts}={}){const __arpgH=globalThis.__arpg&&globalThis.__arpg.path;` +
      `return __arpgH?__arpgH(${t},${from},${dest},${ent},${opts},__arpgPathOrig):__arpgPathOrig(${t},${from},${dest},${ent},${opts})}` +
      `function __arpgPathOrig(${t},${from},${dest},${ent},${opts}={}){`,
  },
  {
    name: 'region-arrival',
    // "Is this cell in that region?" for arrivals and destination picking: the innermost region
    // at the cell must be that very region. Mods may also accept another piece of the same region.
    find: /function ([\w$]+)\(([\w$]+),([\w$]+),([\w$]+)\)\{return ([\w$]+)\(\2,\4\)===\3\}/g,
    replace: (_m, fn, t, region, cell, innermost) =>
      `function ${fn}(${t},${region},${cell}){const __arpgR=${innermost}(${t},${cell});` +
      `return __arpgR===${region}||!!(globalThis.__arpg&&globalThis.__arpg.sameRegion&&globalThis.__arpg.sameRegion(${t},__arpgR,${region}))}`,
  },
  {
    name: 'region-destination',
    // Picks a standing spot inside a region for a mover (MOVE_TO, schedules, teleports). Mods may
    // swap the region for another piece of it, such as the one nearest the mover.
    find: /function ([\w$]+)\(([\w$]+),([\w$]+),([\w$]+),([\w$]+)\)\{(?=const [\w$]+=new [\w$]+\(\2,\4\),[\w$]+=[\w$]+\(\2,\4\),[\w$]+=Math\.floor\(\3\.size\[0\]\/4\))/g,
    replace: (_m, fn, t, region, mover, rng) =>
      `function ${fn}(${t},${region},${mover},${rng}){` +
      `if(globalThis.__arpg&&globalThis.__arpg.pieceFor)${region}=globalThis.__arpg.pieceFor(${t},${region},${mover})??${region};`,
  },
  {
    name: 'region-same-room',
    // The GM prompt's "in the same space as the player" test compares walled rooms by identity.
    find: /const ([\w$]+)=([\w$]+)\(([\w$]+),([\w$]+)\(([\w$]+)\)\),([\w$]+)=([\w$]+)=>\2\(\3,\4\(\7\)\)===\1/g,
    replace: (_m, room, walled, t, cellOf, player, test, other) =>
      `const ${room}=${walled}(${t},${cellOf}(${player})),${test}=${other}=>{const __arpgG=${walled}(${t},${cellOf}(${other}));` +
      `return __arpgG===${room}||!!(globalThis.__arpg&&globalThis.__arpg.sameRegion&&globalThis.__arpg.sameRegion(${t},__arpgG,${room}))}`,
  },
  {
    name: 'sim-tick',
    // The start of each unpaused simulation step.
    find: /\.moving=!1;if\(([\w$]+)\.paused\)\{([\w$]+)\(\1\);return\}/g,
    replace: (_m, world, idle) =>
      `.moving=!1;if(${world}.paused){${idle}(${world});return}globalThis.__arpg&&globalThis.__arpg.tick&&globalThis.__arpg.tick(${world});`,
  },
  {
    name: 'perception',
    // The "within notice range" test (straight-line distance only) behind the player's
    // vicinity events, which NPC actions reach the GM, and the prompt's nearby lists.
    // Identified as the distance function that the player-relative wrapper right after it calls.
    find: /function ([\w$]+)\(([\w$]+),([\w$]+),([\w$]+),([\w$]+)=([\w$]+)\)\{return ([\w$]+)\(\3,\4\)<=\5\}(?=function [\w$]+\([\w$]+,[\w$]+,[\w$]+=\6\)\{return \1\()/g,
    // Mods see the game's answer and may change it either way. Hands them the game's own
    // path search too (__arpgPathOrig, from the pathfinder patch).
    replace: (_m, fn, t, a, b, range, def, dist) =>
      `function ${fn}(${t},${a},${b},${range}=${def}){const __arpgN=${dist}(${a},${b})<=${range};` +
      `return globalThis.__arpg&&globalThis.__arpg.perceive?globalThis.__arpg.perceive(${t},${a},${b},${range},__arpgPathOrig,__arpgN):__arpgN}`,
  },
  {
    name: 'line-of-sight',
    // 1.0 stealth's line-of-sight test: a grid walk from one continuous point to another that
    // walls and shut doors stop (open doorways, bars and gates don't). Identified as the
    // boolean wrapper over the walk function it names.
    find: /function ([\w$]+)\(([\w$]+),([\w$]+),([\w$]+)\)\{return ([\w$]+)\(\2,\3,\4\)>=1\}(?=function \5\([\w$]+,[\w$]+,\{walls:[\w$]+,shut:[\w$]+\}\))/g,
    // Mods get the test itself, as __arpg.game.lineClear (see the loader's lineOfSight).
    replace: (_m, fn) =>
      `globalThis.__arpg&&globalThis.__arpg.game&&(globalThis.__arpg.game.lineClear=${fn});${_m}`,
  },
  {
    name: 'sight-blockers',
    // The blockers that test takes: the world's wall regions plus the door edges nobody is
    // holding open. Identified by its scan of the world's entities for shut, sight-blocking
    // doors (bars and gates are see-through).
    find: /function ([\w$]+)\(([\w$]+)\)\{const ([\w$]+)=new Set;for\(const ([\w$]+) of \2\.entities\)\{if\(![\w$]+\(\4\)\|\|\4\.dead\|\|![\w$]+\[\4\.objectTemplate\.door\]\|\|[\w$]+\(\2,\4\)\)continue;(?=[^]{0,120}?return\{walls:[\w$]+\(\2\),shut:\3\}\})/g,
    // Mods get the builder, as __arpg.game.sightBlockers (see the loader's sightBlockers).
    replace: (_m, fn) =>
      `globalThis.__arpg&&globalThis.__arpg.game&&(globalThis.__arpg.game.sightBlockers=${fn});${_m}`,
  },
  {
    name: 'gm-prompt',
    // Where the GM prompt's head/sections/tail are built, from the world and the context limits
    // in force. Mods may add sections. The game rebuilds the prompt with lower limits while it is
    // over the character budget, so this runs once per attempt.
    find: /const\{head:([\w$]+),sections:([\w$]+),tail:([\w$]+)\}=([\w$]+)\(([\w$]+),([\w$]+)\)/g,
    replace: (_m, head, sections, tail, build, world, limits) =>
      `const{head:${head},sections:${sections},tail:${tail}}=` +
      `(globalThis.__arpg&&globalThis.__arpg.prompt?globalThis.__arpg.prompt(${build}(${world},${limits}),${world},${limits}):${build}(${world},${limits}))`,
  },
];

export function parseArgs(argv) {
  const out = { cmd: argv[0] ?? 'status', game: null, names: [] };
  for (let i = 1; i < argv.length; i++) {
    if (argv[i] === '--game') out.game = argv[++i];
    else if (argv[i].startsWith('-')) throw new Error(`unknown argument: ${argv[i]}`);
    else out.names.push(argv[i]);
  }
  return out;
}

// Steam's own folders for this system. Each holds steamapps/libraryfolders.vdf, which lists
// every library (other drives included).
function steamRoots() {
  const home = os.homedir();
  if (process.platform === 'win32') {
    const roots = [];
    try {
      const out = execFileSync('reg', ['query', 'HKCU\\Software\\Valve\\Steam', '/v', 'SteamPath'],
        { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
      const m = out.match(/SteamPath\s+REG_SZ\s+(.+)/);
      if (m) roots.push(m[1].trim());
    } catch { /* no Steam key: fall back to the default folder */ }
    roots.push('C:\\Program Files (x86)\\Steam');
    return roots;
  }
  if (process.platform === 'darwin') return [path.join(home, 'Library', 'Application Support', 'Steam')];
  return [
    path.join(home, '.steam', 'steam'),
    path.join(home, '.local', 'share', 'Steam'),
    path.join(home, '.var', 'app', 'com.valvesoftware.Steam', '.local', 'share', 'Steam'),
  ];
}

// The "path" entries of a libraryfolders.vdf, whose backslashes are doubled.
export function libraryPaths(vdf) {
  return [...vdf.matchAll(/"path"\s+"((?:[^"\\]|\\.)*)"/g)].map(m => m[1].replace(/\\\\/g, '\\'));
}

// The first Steam library that holds a real install of the game.
function findGame() {
  const seen = new Set();
  for (const root of steamRoots()) {
    const libs = [root];
    try {
      libs.push(...libraryPaths(fs.readFileSync(path.join(root, 'steamapps', 'libraryfolders.vdf'), 'utf8')));
    } catch { /* this Steam folder doesn't exist */ }
    for (const lib of libs) {
      const game = path.join(lib, 'steamapps', 'common', 'Anywhere RPG');
      const key = process.platform === 'win32' ? path.resolve(game).toLowerCase() : path.resolve(game);
      if (seen.has(key)) continue;
      seen.add(key);
      if (distOf(game)) return game;
    }
  }
  throw new Error('could not find Anywhere RPG in your Steam libraries; pass --game "<install folder>"');
}

// The renderer's folder: resources/app/dist, or the same inside a macOS .app bundle.
function distOf(game) {
  const dirs = [path.join(game, 'resources', 'app', 'dist')];
  try {
    for (const d of fs.readdirSync(game)) {
      if (d.endsWith('.app')) dirs.push(path.join(game, d, 'Contents', 'Resources', 'app', 'dist'));
    }
  } catch { /* not a folder */ }
  return dirs.find(d => fs.existsSync(path.join(d, 'index.html')));
}

function locate(game) {
  const dist = distOf(game);
  if (!dist) throw new Error(`not an Anywhere RPG install (no resources/app/dist/index.html under ${game})`);
  const html = path.join(dist, 'index.html');
  // The live page, never the backup: the patched page keeps the bundle's tag, and after a game
  // update the backup still names the old build's bundle.
  const m = fs.readFileSync(html, 'utf8').match(/<script type="module" crossorigin src="\.\/assets\/(index-[\w-]+\.js)"><\/script>/);
  if (!m) throw new Error('could not find the main bundle in index.html');
  return { game, dist, html, bundle: path.join(dist, 'assets', m[1]), modsOut: path.join(dist, 'arpg-mods') };
}

// The game's version, a string constant. 1.0 keeps it among the build flags that follow the
// release/demo table ({release:"release",demo:"demo"},…,tb="1.0",hs="en"); 0.18 kept it just
// before the log levels (KI="0.18",Bg={},KC={error:0,…).
export function gameVersion(src) {
  const m = src.match(/\{release:"release",demo:"demo"\}[^"]{0,400}?[,;][\w$]+="(\d+\.\d+(?:\.\d+)?)"/) ??
    src.match(/[\w$]+="(\d+\.\d+(?:\.\d+)?)",[\w$]+=\{\},[\w$]+=\{error:0,warn:1/);
  return m ? m[1] : null;
}

// The mods that ship in examples/, each a folder with a mod.js.
export function bundledMods() {
  return fs.readdirSync(EXAMPLES, { withFileTypes: true })
    .filter(d => d.isDirectory() && fs.existsSync(path.join(EXAMPLES, d.name, 'mod.js')))
    .map(d => d.name)
    .sort();
}

// Turns the names given to "add" into bundled mod names. No names, or "all", means every
// bundled mod except the samples.
export function resolveMods(names, avail) {
  const out = new Set();
  for (const n of names.length ? names : ['all']) {
    if (n === 'all') for (const m of avail) { if (!SAMPLES.has(m)) out.add(m); }
    else if (avail.includes(n)) out.add(n);
    else throw new Error(`no bundled mod named "${n}" (bundled: ${avail.join(', ')})`);
  }
  return [...out];
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

export function patchBundle(src) {
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

// Splits the mods in the code-mods folder into the ones to load and the retired ones to skip.
export function splitRetired(mods) {
  return { load: mods.filter(m => !RETIRED.has(m)), retired: mods.filter(m => RETIRED.has(m)) };
}

// Backups of bundles a game update has since replaced (index-<old hash>.js.arpg-orig).
function dropStaleBackups(loc) {
  const dir = path.dirname(loc.bundle);
  for (const f of fs.readdirSync(dir)) {
    if (f.endsWith('.js' + ORIG) && !fs.existsSync(path.join(dir, f.slice(0, -ORIG.length)))) {
      fs.rmSync(path.join(dir, f));
      console.log(`removed a stale backup from an older game build: ${f}`);
    }
  }
}

function install(loc) {
  dropStaleBackups(loc);
  const bundleSrc = originalOf(loc.bundle);
  const patched = patchBundle(bundleSrc);

  const htmlCur = fs.readFileSync(loc.html, 'utf8');
  if (!htmlCur.includes('arpg-mods/')) fs.writeFileSync(loc.html + ORIG, htmlCur);
  const htmlSrc = fs.readFileSync(loc.html + ORIG, 'utf8');

  fs.rmSync(loc.modsOut, { recursive: true, force: true });
  fs.mkdirSync(loc.modsOut, { recursive: true });
  fs.copyFileSync(path.join(HERE, 'runtime', 'loader.js'), path.join(loc.modsOut, 'loader.js'));
  const { load: mods, retired } = splitRetired(listMods());
  for (const m of mods) fs.copyFileSync(path.join(MODS_DIR, m, 'mod.js'), path.join(loc.modsOut, `${m}.js`));

  // Classic scripts run before the module bundle, so the loader and every mod
  // have registered before the game builds its registry.
  const tags = ['loader', ...mods].map(n => `    <script src="./arpg-mods/${n}.js"></script>`).join('\n');
  const html = htmlSrc.replace(/(\s*)<script type="module"/, `\n${tags}$1<script type="module"`);

  fs.writeFileSync(loc.bundle, patched);
  fs.writeFileSync(loc.html, html);
  console.log(`installed: ${path.basename(loc.bundle)} patched (${PATCHES.map(p => p.name).join(', ')})`);
  console.log(`mods (${MODS_DIR}): ${mods.length ? mods.join(', ') : '(none)'}`);
  if (retired.length) {
    console.log(`skipped: ${retired.join(', ')}. Anywhere RPG 1.0 does these natively, so they're retired ` +
      `(they stay on the 0.18 branch). Delete them with: node patch.mjs remove ${retired.join(' ')}`);
  }
}

function uninstall(loc) {
  // A backup goes back only over a file this patcher changed. After a game update the file is
  // already the game's own, and the backup belongs to the older build, so it's just deleted.
  const patched = [[loc.bundle, t => t.includes(MARKER)], [loc.html, t => t.includes('arpg-mods/')]];
  for (const [f, isPatched] of patched) {
    if (!fs.existsSync(f + ORIG)) continue;
    if (isPatched(fs.readFileSync(f, 'utf8'))) fs.copyFileSync(f + ORIG, f);
    fs.rmSync(f + ORIG);
  }
  dropStaleBackups(loc);
  fs.rmSync(loc.modsOut, { recursive: true, force: true });
  console.log('uninstalled: original files restored');
}

function status(loc) {
  const patched = fs.readFileSync(loc.bundle, 'utf8').includes(MARKER);
  console.log(`bundle: ${path.basename(loc.bundle)} — ${patched ? 'patched' : 'original'}`);
  console.log(`mods folder: ${MODS_DIR}`);
  console.log(`mods found: ${listMods().join(', ') || '(none)'}`);
  const { retired } = splitRetired(listMods());
  if (retired.length) console.log(`retired on 1.0, skipped by install: ${retired.join(', ')} (node patch.mjs remove ${retired.join(' ')})`);
  const missing = bundledMods().filter(m => !listMods().includes(m));
  if (missing.length) console.log(`bundled but not installed: ${missing.join(', ')} (node patch.mjs add <name>)`);
  if (!patched) {
    const src = fs.readFileSync(loc.bundle, 'utf8');
    for (const p of PATCHES) console.log(`  anchor ${p.name}: ${[...src.matchAll(p.find)].length} match(es)`);
  }
}

// Copies bundled mods into the code-mods folder (replacing older copies), then installs.
function add(loc, names) {
  const mods = resolveMods(names, bundledMods());
  fs.mkdirSync(MODS_DIR, { recursive: true });
  for (const m of mods) {
    const dest = path.join(MODS_DIR, m);
    fs.rmSync(dest, { recursive: true, force: true });
    fs.cpSync(path.join(EXAMPLES, m), dest, { recursive: true });
  }
  console.log(`added: ${mods.join(', ')}`);
  install(loc);
}

// Deletes mods from the code-mods folder, then installs what's left.
function remove(loc, names) {
  if (!names.length) throw new Error('name the mods to remove, e.g. "remove lights"');
  for (const m of names) {
    const dir = path.join(MODS_DIR, m);
    if (!fs.existsSync(path.join(dir, 'mod.js'))) throw new Error(`"${m}" is not installed (installed: ${listMods().join(', ') || 'none'})`);
    fs.rmSync(dir, { recursive: true, force: true });
  }
  console.log(`removed: ${names.join(', ')}`);
  install(loc);
}

const USAGE = `usage: node patch.mjs <command> [mods…] [--game "<install dir>"]
  status              is the game patched, which mods are installed, do the anchors still match
  add [mods…]         copy bundled mods into the code-mods folder and install (no names: all but ${[...SAMPLES].join(', ')})
  remove <mods…>      delete mods from the code-mods folder and install the rest
  install             patch (or re-patch) and copy in the mods already in the code-mods folder
  uninstall           restore the game's original files`;

function main() {
  const args = parseArgs(process.argv.slice(2));
  const run = { install, uninstall, status, add, remove }[args.cmd];
  if (!run) throw new Error(`unknown command: ${args.cmd}\n${USAGE}`);
  if (args.names.length && !['add', 'remove'].includes(args.cmd)) throw new Error(`unknown argument: ${args.names[0]}\n${USAGE}`);
  const loc = locate(args.game ?? findGame());
  const version = gameVersion(fs.readFileSync(loc.bundle, 'utf8'));
  console.log(`code-mod loader ${LOADER_VERSION}`);
  console.log(`game: ${loc.game} (Anywhere RPG ${version ?? 'version unknown'})`);
  if (version !== TESTED) {
    console.log(`warning: this loader and its mods are for Anywhere RPG ${TESTED}, not ${version ?? 'this version'}. ` +
      'For 0.18, use the 0.18 branch or the v0.18-final release. Install goes ahead only if every patch ' +
      'anchor still matches; play-test before relying on it.');
  }
  run(loc, args.names);
}

// Run as a script, not when the tests import the helpers.
const self = fs.realpathSync(fileURLToPath(import.meta.url));
const invoked = process.argv[1] && fs.existsSync(process.argv[1]) ? fs.realpathSync(process.argv[1]) : '';
if (process.platform === 'win32' ? self.toLowerCase() === invoked.toLowerCase() : self === invoked) {
  try {
    main();
  } catch (e) {
    console.error(`error: ${e.message}`);
    process.exit(1);
  }
}
