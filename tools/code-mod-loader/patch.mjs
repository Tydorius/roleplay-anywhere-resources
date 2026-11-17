#!/usr/bin/env node
// Code-mod loader patcher for Anywhere RPG.
//
//   node patch.mjs status            [--game <install dir>]
//   node patch.mjs add [mods…]       [--game <install dir>]   (copy bundled mods in, then install)
//   node patch.mjs remove <mods…>    [--game <install dir>]
//   node patch.mjs pack <dir> [ids…] [--game <install dir>]   (third-party pack: replacement game
//                                    file + its config mods, layered under the loader's patches)
//   node patch.mjs pack-remove [ids…] [--game <install dir>]  (take pack mods out; no ids: all)
//   node patch.mjs install           [--game <install dir>]   (re-run after adding mods or a game update)
//   node patch.mjs uninstall         [--game <install dir>]
//
// It patches the installed renderer bundle by matching code content (never
// minified names), adds the loader and every mod in the code-mods folder
// to index.html, and keeps the untouched originals as *.arpg-orig beside them.
// Without --game it looks for the game in every Steam library.
//
// Third-party packs (SMAQ is the first) ship their own replacement game file plus
// config mods. Their file is kept as an *.arpg-pack base layered under the loader's
// patches, so both coexist: stock → pack's file → the loader's patches.

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const EXAMPLES = path.join(HERE, 'examples');
const MARKER = '/*arpg-modloader*/';
const ORIG = '.arpg-orig';
const PACK = '.arpg-pack';
// This loader's release (README's version table), and the game version its patches were built
// against. main supports Anywhere RPG 1.0+; the 0.18 loader stays on the 0.18 branch.
const LOADER_VERSION = '2.4.0';
const TESTED = '1.2';
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

// The game's own mods folder (config packs), where a third-party pack's mods go.
export function defaultPacksDir(platform = process.platform, env = process.env, home = os.homedir()) {
  if (platform === 'win32') return path.join(env.APPDATA ?? path.join(home, 'AppData', 'Roaming'), 'Anywhere RPG', 'mods');
  if (platform === 'darwin') return path.join(home, 'Library', 'Application Support', 'Anywhere RPG', 'mods');
  return path.join(env.XDG_CONFIG_HOME || path.join(home, '.config'), 'Anywhere RPG', 'mods');
}
const MODS_DIR = defaultModsDir();
const PACKS_DIR = defaultPacksDir();

export function sha256(text) {
  return crypto.createHash('sha256').update(text).digest('hex');
}

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
    // SMAQ's exploration fog edits this very test before the player-relative wrapper, keeping
    // only answers about cells the player has explored: `…<=range&&(a!==t.player||CodexWorldVisible(t,b))`.
    // The fog answer becomes the seed our hooks start from, so both compose.
    foreignFind: /function ([\w$]+)\(([\w$]+),([\w$]+),([\w$]+),([\w$]+)=([\w$]+)\)\{return ([\w$]+)\(\3,\4\)<=\5&&\(\3!==\2\.player\|\|CodexWorldVisible\(\2,\4\)\)\}(?=function [\w$]+\([\w$]+,[\w$]+,[\w$]+=\6\)\{return \1\()/g,
    foreignReplace: (_m, fn, t, a, b, range, def, dist) =>
      `function ${fn}(${t},${a},${b},${range}=${def}){const __arpgN=${dist}(${a},${b})<=${range}&&(${a}!==${t}.player||CodexWorldVisible(${t},${b}));` +
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
  {
    name: 'liquid-canvas',
    // The liquid overlay painter (one 32×32-cell chunk of water and roads, plus a 2-cell margin).
    // It paints two canvases — the colour layer and a flow map (R/G = flow, B = liquid kind) —
    // then blurs a cropped copy of each into the tile. Right before that blur, mods get both
    // canvases and may override the blur radius (the closure that crops is rewritten to read a
    // local set from the hook's return instead of the game's constant).
    find: /build\(([\w$]+),([\w$]+),([\w$]+)\)\{const ([\w$]+)=([\w$]+)\+([\w$]+)\*2,([\w$]+)=\(\)=>\{[^{}]*\},([\w$]+)=\7\(\),([\w$]+)=\7\(\);([^]{0,1500}?)const ([\w$]+)=([\w$]+)=>\{const ([\w$]+)=document\.createElement\("canvas"\);\13\.width=\13\.height=\5\*([\w$]+);const ([\w$]+)=\13\.getContext\("2d"\);return \15\.filter=`blur\(\$\{([\w$]+)\}px\)`,\15\.drawImage\(\12\.canvas,-\6\*\14,-\6\*\14\),\13\},([\w$]+)=`terrain-overlay:/g,
    replace: (_m, t, n, i, o, cells, margin, mk, color, flow, mid, blurFn, src, f, px, v, blur, key) =>
      `build(${t},${n},${i}){const ${o}=${cells}+${margin}*2,${mk}=()=>{const __arpgCv=document.createElement("canvas");` +
      `return __arpgCv.width=__arpgCv.height=${o}*${px},__arpgCv.getContext("2d")},${color}=${mk}(),${flow}=${mk}();${mid}` +
      `const __arpgB=globalThis.__arpg&&globalThis.__arpg.liquidCanvas` +
      `?globalThis.__arpg.liquidCanvas({color:${color},flow:${flow},cellPx:${px},margin:${margin},chunkCells:${cells},chunk:${n},unbounded:${t},blur:${blur}})??${blur}:${blur};` +
      `const ${blurFn}=${src}=>{const ${f}=document.createElement("canvas");${f}.width=${f}.height=${cells}*${px};` +
      `const ${v}=${f}.getContext("2d");return ${v}.filter=\`blur(\${__arpgB}px)\`,` +
      `${v}.drawImage(${src}.canvas,-${margin}*${px},-${margin}*${px}),${f}},${key}=\`terrain-overlay:`,
  },
  {
    name: 'ground-fade',
    // The region ground fade, in the scene's groundOwners(): each region's ground art is faded
    // at its edges with a cached Float32Array of vertex alphas. Mods may replace that array
    // (the same mask must always return the same array, or the ground is refilled every sync).
    find: /fade:([\w$]+)\?([\w$]+)\(\1,([\w$]+)\.size\):null,alpha:/g,
    replace: (_m, mask, fade, region) =>
      `fade:${mask}?(globalThis.__arpg&&globalThis.__arpg.groundFade` +
      `?globalThis.__arpg.groundFade(${region},${mask},${fade}(${mask},${region}.size))` +
      `:${fade}(${mask},${region}.size)):null,alpha:`,
  },
  {
    name: 'wall-regions',
    // The wall-edge builder every wall-drawing path uses (the ground, buildWalls,
    // buildTexturedWalls, wall-caster shadows, door info and the minimap): each walled
    // region's openings decide which edges are drawn. The simulation never calls it, so a
    // mod may rewrite the region list first (drop an opening and its wall is drawn whole) —
    // that changes what is drawn, never where anyone can walk.
    find: /function ([\w$]+)\(([\w$]+)\)\{(?=const [\w$]+=new Map,[\w$]+=new Map,[\w$]+=new Map,[\w$]+=new Map,[\w$]+=new Map\(\2\.map\()/g,
    replace: (_m, fn, regions) =>
      `function ${fn}(${regions}){` +
      `${regions}=globalThis.__arpg&&globalThis.__arpg.wallRegions?globalThis.__arpg.wallRegions(${regions}):${regions};`,
  },
  {
    name: 'entity-hidden',
    // The scene's per-entity sprite sync. Its off-screen test hides the container, the overhead
    // label, both shadows and the light, then skips the entity. Mods may take an entity off
    // screen the same way, per world (identified by the camera-rect cull that ends at the
    // entity's own light sync).
    find: /if\(([\w$]+)\+([\w$]+)<([\w$]+)\.x\|\|\1-\2>\3\.right\|\|([\w$]+)\+([\w$]+)<\3\.y\|\|\4-\5>\3\.bottom\)\{([^]{0,250}?this\.syncEntityLight\(([\w$]+),\1,\4\))/g,
    replace: (_m, x, halfW, rect, y, halfH, culled, ent) =>
      `if(${x}+${halfW}<${rect}.x||${x}-${halfW}>${rect}.right||${y}+${halfH}<${rect}.y||${y}-${halfH}>${rect}.bottom` +
      `||globalThis.__arpg&&globalThis.__arpg.hidden(this.world,${ent})){${culled}`,
  },
  {
    name: 'pointer-hits',
    // The pointer hit test behind hover, click, select and the context menu: the scene's
    // entities that its own hidden (ghosted) test skips. Mods hide an entity from the pointer
    // the same way.
    find: /for\(const ([\w$]+) of this\.world\.entities\)\{if\(([\w$]+)\(this\.world,\1\)\)continue;/g,
    replace: (_m, ent, ghosted) =>
      `for(const ${ent} of this.world.entities){` +
      `if(${ghosted}(this.world,${ent})||globalThis.__arpg&&globalThis.__arpg.hidden(this.world,${ent}))continue;`,
    // SMAQ's fog also hides unexplored entities from the pointer: `…||!CodexWorldVisible(this.world,g))continue;`.
    // The two conditions stack — an entity needs to pass both to stay hoverable.
    foreignFind: /for\(const ([\w$]+) of this\.world\.entities\)\{if\(([\w$]+)\(this\.world,\1\)\|\|!CodexWorldVisible\(this\.world,\1\)\)continue;/g,
    foreignReplace: (_m, ent, ghosted) =>
      `for(const ${ent} of this.world.entities){` +
      `if(${ghosted}(this.world,${ent})||!CodexWorldVisible(this.world,${ent})||globalThis.__arpg&&globalThis.__arpg.hidden(this.world,${ent}))continue;`,
  },
  {
    name: 'door-list',
    // The shared list of doors that may stop someone: only locked doors reach it. A mod may
    // gate more doors onto the list (they then reach the per-walker pass test and, shut, the
    // sight blockers). Identified as the door push in the world's region/entity scan, anchored
    // on its function's head to capture the world.
    find: /function ([\w$]+)\(([\w$]+),([\w$]+),([\w$]+),([\w$]+)\)\{([^]{0,450}?)if\(\(([\w$]+)=([\w$]+)\.objectTemplate\)!=null&&\7\.door\)\{([\w$]+)\(\8,"locked"\)&&([\w$]+)\.doors\.push\(\8\);continue\}/g,
    replace: (_m, fn, world, b, c, d, mid, tpl, ent, locked, cache) =>
      `function ${fn}(${world},${b},${c},${d}){${mid}` +
      `if((${tpl}=${ent}.objectTemplate)!=null&&${tpl}.door){` +
      `(${locked}(${ent},"locked")||globalThis.__arpg&&globalThis.__arpg.doorGated(${world},${ent}))&&${cache}.doors.push(${ent});continue}`,
  },
  {
    name: 'door-pass-nav',
    // The per-walker door pass test at the end of the movement grid builder: every door on the
    // shared list whose key the walker doesn't hold becomes a shut door (a blocked edge) for
    // that walker. Mods get the same say per walker; the game's own key test is handed in as a
    // callback. Identified by its scan of the shared door list into this.shutDoors.
    find: /([\w$]+)&&(!?[\w$]+)\)\{const ([\w$]+)=([\w$]+)\(\1\);for\(const ([\w$]+) of ([\w$]+)\.doors\)([\w$]+)\(([\w$]+),\3,\5\)\|\|this\.shutDoors\.push\(\5\)\}/g,
    replace: (_m, walker, notFlag, keys, keysOf, door, cache, keyOpens, world) =>
      `${walker}&&${notFlag}){const ${keys}=${keysOf}(${walker});` +
      `for(const ${door} of ${cache}.doors)` +
      `(globalThis.__arpg?globalThis.__arpg.doorPasses(${world},${door},${walker},()=>${keyOpens}(${world},${keys},${door})):${keyOpens}(${world},${keys},${door}))` +
      `||this.shutDoors.push(${door})}`,
  },
  {
    name: 'door-pass-swing',
    // The door swing test: does person `n` hold door `t` open? A door nobody holds open blocks
    // sight and passage through its doorway. Shares the doorPasses dispatcher with
    // door-pass-nav, so a mod's per-walker answer covers walking and swing alike. Identified by
    // its person guard head and locked-or-key tail.
    find: /function ([\w$]+)\(([\w$]+),([\w$]+),([\w$]+)\)\{if\(\4\.dead\|\|\4\.type!=="npc"&&\4\.type!=="player"\)return!1;([^]{0,600}?)return!([\w$]+)\(\3,"locked"\)\|\|([\w$]+)\(\2,([\w$]+)\(\4\),\3\)\}/g,
    replace: (_m, fn, world, door, person, mid, locked, keyOpens, keysOf) =>
      `function ${fn}(${world},${door},${person}){` +
      `if(${person}.dead||${person}.type!=="npc"&&${person}.type!=="player")return!1;${mid}` +
      `return globalThis.__arpg?globalThis.__arpg.doorPasses(${world},${door},${person},()=>${keyOpens}(${world},${keysOf}(${person}),${door}))` +
      `:!${locked}(${door},"locked")||${keyOpens}(${world},${keysOf}(${person}),${door})}`,
  },
  {
    name: 'gm-doorways',
    // The GM's doorway list (each doorway its crossings, room and door entities), behind the
    // GM prompt's door details. Mods may drop a doorway from it. Identified by the build call
    // ahead of the near-doorway distance filter.
    find: /let ([\w$]+)=([\w$]+)\(([\w$]+),([\w$]+),([\w$]+)\);(?=[\w$]+\|\|\(\1=\1\.filter\([\w$]+=>[\w$]+\([\w$]+\.crossings\[0\]\.cell,[\w$]+\)<=)/g,
    replace: (_m, list, build, world, who, rooms) =>
      `let ${list}=${build}(${world},${who},${rooms});` +
      `if(globalThis.__arpg)${list}=${list}.filter(d=>globalThis.__arpg.doorwayShown(${world},d));`,
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

// The pack layer recorded beside the bundle, when a third-party pack is installed.
function readPackMeta(loc) {
  const metaFile = loc.bundle + PACK + '.json';
  if (!fs.existsSync(metaFile)) return null;
  try {
    return JSON.parse(fs.readFileSync(metaFile, 'utf8'));
  } catch (e) {
    throw new Error(`${path.basename(metaFile)} is unreadable (${e.message}); fix it or remove it`);
  }
}

// Returns the text to patch and the pristine stock it came from. With a pack layer
// recorded, the pack's replacement file is the base and the loader's patches chain on
// top of it; without one, the base is the stock bundle. The stock backup is refreshed
// when the game has replaced an unpatched file (an update or Steam's "Verify
// integrity") — but never silently past a recorded pack.
function baseOf(loc) {
  const cur = fs.readFileSync(loc.bundle, 'utf8');
  const meta = readPackMeta(loc);
  const origFile = loc.bundle + ORIG;
  const packFile = loc.bundle + PACK;

  if (!cur.includes(MARKER)) {
    const curSha = sha256(cur);
    if (!meta) {
      if (cur.includes('CodexWorldVisible')) {
        console.log('warning: the game file looks like a mod pack\'s replacement and no pack layer is recorded here. ' +
          'It was taken as the base anyway, so uninstalling would restore THIS file, not the game\'s own. Prefer restoring ' +
          'the original (Steam -> Properties -> Installed Files -> Verify integrity) and running "pack <folder>".');
      }
      fs.writeFileSync(origFile, cur);
    } else if (curSha === meta.stockSha256) {
      fs.writeFileSync(origFile, cur); // the game put its own file back
    } else if (curSha !== meta.rendererSha256) {
      throw new Error(`the game files changed underneath ${meta.shortName} ${meta.version} (a game update?). Take the old ` +
        'pack layer out first — node patch.mjs pack-remove — then re-run pack with a release for the new build');
    }
  }
  if (!fs.existsSync(origFile)) throw new Error(`${path.basename(loc.bundle)} is patched but its stock backup is missing`);
  const stock = fs.readFileSync(origFile, 'utf8');
  if (!meta) return { stock, base: stock, meta: null };

  if (!fs.existsSync(packFile)) throw new Error(`the pack layer is incomplete (${path.basename(packFile)} is missing); re-run "pack <folder>" or "pack-remove"`);
  const pack = fs.readFileSync(packFile, 'utf8');
  if (sha256(pack) !== meta.rendererSha256) throw new Error(`${path.basename(packFile)} fails its recorded hash; re-run "pack <folder>"`);
  if (sha256(stock) !== meta.stockSha256) throw new Error(`the stock backup fails ${meta.shortName}'s recorded stock hash; restore the game files (Steam -> Verify integrity) and re-run "pack <folder>"`);
  return { stock, base: pack, meta };
}

// A third-party pack's MANIFEST.json (SMAQ is the first): the replacement game file it
// ships, the stock it was built from, and the config mods it adds.
export function parseManifest(obj, from = 'MANIFEST.json') {
  const need = ['title', 'shortName', 'version', 'gameBuild', 'sharedGameFile', 'stockSha256', 'rendererSha256', 'mods'];
  for (const k of need) if (!obj?.[k]) throw new Error(`${from}: no ${k}; not a pack this loader knows`);
  if (!Array.isArray(obj.mods) || !obj.mods.length) throw new Error(`${from}: lists no mods`);
  for (const m of obj.mods) {
    if (!m.id || !Array.isArray(m.files) || !m.files.length) throw new Error(`${from}: mod "${m.id ?? '?'}" needs an id and its files`);
  }
  return obj;
}

// The pack's mod ids to install: the names given, or every mod the manifest ships minus
// the ones its author excluded.
export function resolvePackMods(ids, manifest) {
  const excluded = new Set(manifest.excluded ?? []);
  const avail = manifest.mods.map(m => m.id).filter(id => !excluded.has(id));
  if (!ids.length) return avail;
  for (const id of ids) if (!avail.includes(id)) throw new Error(`no mod named "${id}" in this pack (available: ${avail.join(', ')})`);
  return [...new Set(ids)];
}

export function patchBundle(src) {
  let out = src;
  for (const p of PATCHES) {
    const hits = [...out.matchAll(p.find)].length;
    if (hits === 1) { out = out.replace(p.find, p.replace); continue; }
    // A pack's replacement file already edited this site: try the anchor for the edited shape.
    if (p.foreignFind) {
      const foreign = [...out.matchAll(p.foreignFind)].length;
      if (foreign === 1) { out = out.replace(p.foreignFind, p.foreignReplace); continue; }
      if (foreign > 1) throw new Error(`patch "${p.name}" matched ${foreign} times on the pack's edited shape (expected 1); the pack's build changed, update patch.mjs`);
    }
    throw new Error(`patch "${p.name}" matched ${hits} times (expected 1); the game build changed, update patch.mjs`);
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

// ---- conflict detection -----------------------------------------------------------------
// Hard failures (a patch anchor not matching, a hash check) throw and change nothing.
// These are the softer findings install reports before it writes.

// Which of our patch sites sit beside the pack's own edits: the anchor's flanking text
// differs between the stock and the pack's file. The anchors still matched exactly once
// (the install guard); this only says where to play-test.
export function overlapWarnings(stock, base) {
  const out = [];
  const K = 128;
  const ctx = (src, m) => src.slice(Math.max(0, m.index - K), m.index) + '\0' +
    src.slice(m.index + m[0].length, m.index + m[0].length + K);
  for (const p of PATCHES) {
    const sm = [...stock.matchAll(p.find)][0];
    if (!sm) continue;
    const fm = [...base.matchAll(p.find)][0] ?? (p.foreignFind ? [...base.matchAll(p.foreignFind)][0] : undefined);
    if (!fm) continue;
    if (ctx(stock, sm) !== ctx(base, fm)) out.push(`patch "${p.name}" sits beside the pack's own edits; both are applied — play-test this area`);
  }
  return out;
}

// Static scan of a mod.js for the names it registers. Mod writers pass string literals,
// so a miss only means the scan can't see it.
export function scanModCalls(src) {
  const calls = [], headers = [];
  for (const m of src.matchAll(/addCall\(\s*(['"])([\w.-]+)\1/g)) calls.push(m[2]);
  for (const m of src.matchAll(/addApiHeader\(\s*(['"])([\w.-]+)\1/g)) headers.push(m[2]);
  return { calls, headers };
}

function codeModWarnings() {
  const out = [];
  const seenCalls = new Map(), seenHeaders = new Map();
  for (const mod of listMods()) {
    const { calls, headers } = scanModCalls(fs.readFileSync(path.join(MODS_DIR, mod, 'mod.js'), 'utf8'));
    for (const n of calls) {
      if (seenCalls.has(n)) out.push(`GM call "${n}" is registered by mods ${seenCalls.get(n)} and ${mod}; the later one overwrites the first at runtime`);
      else seenCalls.set(n, mod);
    }
    for (const n of headers) {
      if (seenHeaders.has(n)) out.push(`api header "${n}" is added by mods ${seenHeaders.get(n)} and ${mod}`);
      else seenHeaders.set(n, mod);
    }
  }
  return out;
}

// Every file under dir, as relative paths, to compare an installed pack mod against its
// incoming copy.
export function treeOf(dir, base = dir) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...treeOf(p, base));
    else out.push(path.relative(base, p).split(path.sep).join('/'));
  }
  return out.sort();
}

export function sameTree(a, b) {
  const da = fs.existsSync(a) ? treeOf(a) : [];
  const db = fs.existsSync(b) ? treeOf(b) : [];
  if (da.length !== db.length || da.some((f, i) => f !== db[i])) return false;
  return da.every(f => fs.readFileSync(path.join(a, f)).equals(fs.readFileSync(path.join(b, f))));
}

function titleCollisions() {
  const out = [], titles = new Map();
  if (!fs.existsSync(PACKS_DIR)) return out;
  for (const d of fs.readdirSync(PACKS_DIR, { withFileTypes: true })) {
    if (!d.isDirectory()) continue;
    const info = path.join(PACKS_DIR, d.name, 'mod-info.json');
    if (!fs.existsSync(info)) continue;
    let title = null;
    try { title = JSON.parse(fs.readFileSync(info, 'utf8')).title ?? null; } catch { continue; }
    if (!title) continue;
    if (titles.has(title) && titles.get(title) !== d.name) out.push(`two mods share the title "${title}": ${titles.get(title)} and ${d.name}`);
    else titles.set(title, d.name);
  }
  return out;
}

// Config mods with prompts/*.mjs only run through a pack's patched game file; the stock
// game never reads .mjs from a config pack. Without a pack layer they sit inert.
export function inertPackMods(packsDir = PACKS_DIR) {
  if (!fs.existsSync(packsDir)) return [];
  const out = [];
  for (const d of fs.readdirSync(packsDir, { withFileTypes: true })) {
    if (!d.isDirectory()) continue;
    const prompts = path.join(packsDir, d.name, 'prompts');
    if (!fs.existsSync(prompts)) continue;
    if (treeOf(prompts).some(f => f.endsWith('.mjs'))) out.push(d.name);
  }
  return out.sort();
}

// Places where one of our code mods and a pack mod both get a say. The loader's hooks
// run with the pack's answer as their starting point, so both apply; this is a play-test
// hint, not a failure.
export function semanticOverlaps(codeMods, packMods) {
  const out = [];
  const pairs = [
    ['wall-aware-perception', ['exploration-fog'], 'who notices whom'],
  ];
  for (const [ours, theirs, area] of pairs) {
    const hit = theirs.find(m => packMods.includes(m));
    if (codeMods.includes(ours) && hit) out.push(`"${ours}" and "${hit}" both change ${area}: hooks see the pack's answer first — play-test them together`);
  }
  return out;
}

function conflictWarnings({ stock, base, meta, mods }) {
  const out = [];
  if (meta) {
    out.push(...overlapWarnings(stock, base));
    const missing = meta.mods.filter(id => !fs.existsSync(path.join(PACKS_DIR, id, 'mod-info.json')));
    if (missing.length) out.push(`pack mods missing from ${PACKS_DIR}: ${missing.join(', ')} (re-run "pack <folder>" to restore them)`);
    out.push(...semanticOverlaps(mods, meta.mods));
  } else {
    const inert = inertPackMods();
    if (inert.length) out.push(`these config mods carry .mjs code that needs a pack's game file, and no pack layer is installed: ${inert.join(', ')} (they sit inert; run "pack <folder>")`);
  }
  out.push(...codeModWarnings());
  out.push(...titleCollisions());
  return out;
}

// Backups of bundles a game update has since replaced (index-<old hash>.js.arpg-orig,
// and the pack layer beside them).
function dropStaleBackups(loc) {
  const dir = path.dirname(loc.bundle);
  for (const f of fs.readdirSync(dir)) {
    if (f.endsWith('.js' + ORIG) && !fs.existsSync(path.join(dir, f.slice(0, -ORIG.length)))) {
      fs.rmSync(path.join(dir, f));
      console.log(`removed a stale backup from an older game build: ${f}`);
    }
    if (f.endsWith('.js' + PACK) && !fs.existsSync(path.join(dir, f.slice(0, -PACK.length)))) {
      fs.rmSync(path.join(dir, f));
      fs.rmSync(path.join(dir, f + '.json'), { force: true });
      console.log(`removed a stale pack layer from an older game build: ${f} — re-run "pack <folder>" with a release for the new build to restore it`);
    }
    if (f.endsWith('.js' + PACK + '.json') && !fs.existsSync(path.join(dir, f.slice(0, -'.json'.length)))) {
      // the bundle's pack backup is gone; its metadata follows it (force: the
      // branch above may already have removed it, earlier in this same listing)
      fs.rmSync(path.join(dir, f), { force: true });
    }
  }
}

function install(loc) {
  dropStaleBackups(loc);
  const { stock, base, meta } = baseOf(loc);
  const patched = patchBundle(base);

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
  if (meta) console.log(`pack base: ${meta.title} ${meta.version} — the loader's patches are layered over the pack's game file`);
  console.log(`mods (${MODS_DIR}): ${mods.length ? mods.join(', ') : '(none)'}`);
  if (retired.length) {
    console.log(`skipped: ${retired.join(', ')}. Anywhere RPG 1.0 does these natively, so they're retired ` +
      `(they stay on the 0.18 branch). Delete them with: node patch.mjs remove ${retired.join(' ')}`);
  }
  for (const w of conflictWarnings({ stock, base, meta, mods })) console.log(`warning: ${w}`);
}

function uninstall(loc) {
  const meta = readPackMeta(loc);
  // A backup goes back only over a file this patcher changed. After a game update the file is
  // already the game's own, and the backup belongs to the older build, so it's just deleted.
  const patched = [[loc.bundle, t => t.includes(MARKER)], [loc.html, t => t.includes('arpg-mods/')]];
  for (const [f, isPatched] of patched) {
    if (!fs.existsSync(f + ORIG)) continue;
    if (isPatched(fs.readFileSync(f, 'utf8'))) fs.copyFileSync(f + ORIG, f);
    fs.rmSync(f + ORIG);
  }
  fs.rmSync(loc.bundle + PACK, { force: true });
  fs.rmSync(loc.bundle + PACK + '.json', { force: true });
  dropStaleBackups(loc);
  fs.rmSync(loc.modsOut, { recursive: true, force: true });
  console.log('uninstalled: original files restored');
  if (meta) {
    const left = (meta.mods ?? []).filter(id => fs.existsSync(path.join(PACKS_DIR, id, 'mod-info.json')));
    if (left.length) console.log(`note: ${meta.shortName}'s mod folders remain in ${PACKS_DIR} (${left.join(', ')}); they sit inert ` +
      `without the pack's game file. Remove them with: node patch.mjs pack-remove ${left.join(' ')}`);
  }
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

  const meta = readPackMeta(loc);
  if (meta) {
    const present = meta.mods.filter(id => fs.existsSync(path.join(PACKS_DIR, id, 'mod-info.json')));
    const gone = meta.mods.filter(id => !present.includes(id));
    console.log(`packs folder: ${PACKS_DIR}`);
    console.log(`pack: ${meta.title} ${meta.version} (build ${meta.gameBuild}) — mods: ${present.join(', ') || '(none)'}`);
    if (gone.length) console.log(`  pack mods missing from the packs folder: ${gone.join(', ')} (re-run "pack <folder>")`);
  } else {
    const inert = inertPackMods();
    if (inert.length) console.log(`inert config mods (${PACKS_DIR}, they need a pack's game file and none is installed): ${inert.join(', ')}`);
  }

  if (patched) {
    try {
      const { stock, base, meta: layer } = baseOf(loc);
      for (const w of conflictWarnings({ stock, base, meta: layer, mods: splitRetired(listMods()).load })) {
        console.log(`warning: ${w}`);
      }
    } catch (e) {
      console.log(`error: ${e.message}`);
    }
  } else {
    const src = fs.readFileSync(loc.bundle, 'utf8');
    for (const p of PATCHES) {
      let hits = [...src.matchAll(p.find)].length;
      if (!hits && p.foreignFind) hits = [...src.matchAll(p.foreignFind)].length;
      console.log(`  anchor ${p.name}: ${hits} match(es)`);
    }
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

// Installs a third-party pack (SMAQ is the first): its replacement game file becomes a
// base layer under the loader's patches, and its config mods go into the game's own mods
// folder. Names narrow the mods; no names means every mod the pack ships (minus its
// excluded list). Nothing is written until every check has passed.
function pack(loc, names) {
  const [dir, ...ids] = names;
  if (!dir) throw new Error('pass the pack folder, e.g. "pack <folder> [mod-ids…]"');
  const manifest = parseManifest(JSON.parse(fs.readFileSync(path.join(dir, 'MANIFEST.json'), 'utf8')), path.join(dir, 'MANIFEST.json'));
  const rendererFile = path.join(dir, ...manifest.sharedGameFile.split('/'));
  if (!fs.existsSync(rendererFile)) throw new Error(`${manifest.sharedGameFile} is missing from the pack folder`);
  const renderer = fs.readFileSync(rendererFile, 'utf8');
  if (sha256(renderer) !== manifest.rendererSha256) {
    throw new Error(`the pack's ${manifest.sharedGameFile} fails its MANIFEST hash; the download is incomplete or modified`);
  }
  // Fail before writing anything if the loader's anchors can't chain over the pack's file.
  patchBundle(renderer);

  // The installed game files must be the build this pack was made from.
  const cur = fs.readFileSync(loc.bundle, 'utf8');
  if (cur.includes(MARKER) && !fs.existsSync(loc.bundle + ORIG)) {
    throw new Error(`${path.basename(loc.bundle)} is patched but its stock backup is missing`);
  }
  const stock = cur.includes(MARKER) ? fs.readFileSync(loc.bundle + ORIG, 'utf8') : cur;
  if (sha256(stock) !== manifest.stockSha256) {
    throw new Error(`this ${manifest.shortName} release is for game build ${manifest.gameBuild}, and the game's files don't match ` +
      'the stock it was made from (a game update, or the pack file already copied in by hand?). Restore the game\'s own file ' +
      '(Steam -> Properties -> Installed Files -> Verify integrity) and retry');
  }
  const existing = readPackMeta(loc);
  if (existing && existing.shortName !== manifest.shortName) {
    throw new Error(`another pack's game file is already layered in (${existing.title} ${existing.version}); take it out first: node patch.mjs pack-remove`);
  }
  const chosen = resolvePackMods(ids, manifest);
  for (const id of chosen) {
    if (!fs.existsSync(path.join(dir, 'mods', id, 'mod-info.json'))) throw new Error(`the pack folder has no mods/${id}/mod-info.json`);
  }

  if (!cur.includes(MARKER)) fs.writeFileSync(loc.bundle + ORIG, stock);
  fs.writeFileSync(loc.bundle + PACK, renderer);
  fs.writeFileSync(loc.bundle + PACK + '.json', JSON.stringify({
    title: manifest.title, shortName: manifest.shortName, version: manifest.version,
    gameBuild: manifest.gameBuild, stockSha256: manifest.stockSha256, rendererSha256: manifest.rendererSha256,
    packDir: path.resolve(dir), mods: chosen,
  }, null, 2) + '\n');
  fs.mkdirSync(PACKS_DIR, { recursive: true });
  for (const id of chosen) {
    const src = path.join(dir, 'mods', id), dest = path.join(PACKS_DIR, id);
    if (fs.existsSync(dest) && !sameTree(src, dest)) console.log(`warning: replacing "${id}" in ${PACKS_DIR} (its files differ from the pack's)`);
    fs.rmSync(dest, { recursive: true, force: true });
    fs.cpSync(src, dest, { recursive: true });
  }
  console.log(`pack: ${manifest.title} ${manifest.version} (build ${manifest.gameBuild}) — mods: ${chosen.join(', ')}`);
  console.log('enable the pack\'s mods in the game under Options -> Mods, then restart the game');
  install(loc);
}

// Takes pack mods out of the game's mods folder. With no ids, the whole pack goes: its
// mods and its game-file layer, leaving the loader on the stock bundle.
function packRemove(loc, names) {
  const meta = readPackMeta(loc);
  if (!meta) throw new Error(`no pack layer is installed (no ${path.basename(loc.bundle + PACK + '.json')} beside the bundle)`);
  const ids = names.length ? names : meta.mods;
  for (const id of ids) {
    if (!meta.mods.includes(id)) throw new Error(`"${id}" is not one of this pack's mods (${meta.mods.join(', ')})`);
  }
  for (const id of ids) fs.rmSync(path.join(PACKS_DIR, id), { recursive: true, force: true });
  if (names.length) {
    meta.mods = meta.mods.filter(id => !names.includes(id));
    fs.writeFileSync(loc.bundle + PACK + '.json', JSON.stringify(meta, null, 2) + '\n');
    console.log(`removed from ${PACKS_DIR}: ${names.join(', ')}`);
    install(loc);
    return;
  }
  fs.rmSync(loc.bundle + PACK, { force: true });
  fs.rmSync(loc.bundle + PACK + '.json', { force: true });
  console.log(`removed the ${meta.shortName} layer: the loader is back on the stock game file`);
  install(loc);
}

const USAGE = `usage: node patch.mjs <command> [names…] [--game "<install dir>"]
  status                is the game patched, which mods are installed, do the anchors still match
  add [mods…]           copy bundled mods into the code-mods folder and install (no names: all but ${[...SAMPLES].join(', ')})
  remove <mods…>        delete mods from the code-mods folder and install the rest
  pack <dir> [ids…]     layer a third-party pack's game file under the loader's patches and copy its
                        config mods into the game's mods folder (no ids: every mod the pack ships)
  pack-remove [ids…]    take pack mods out of the game's mods folder (no ids: the whole pack)
  install               patch (or re-patch) and copy in the mods already in the code-mods folder
  uninstall             restore the game's original files`;

function main() {
  const args = parseArgs(process.argv.slice(2));
  const run = { install, uninstall, status, add, remove, pack, 'pack-remove': packRemove }[args.cmd];
  if (!run) throw new Error(`unknown command: ${args.cmd}\n${USAGE}`);
  if (args.names.length && !['add', 'remove', 'pack', 'pack-remove'].includes(args.cmd)) throw new Error(`unknown argument: ${args.names[0]}\n${USAGE}`);
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
