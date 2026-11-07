// node --test   (from tools/code-mod-loader)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

function load() {
  const warnings = [];
  const ctx = vm.createContext({ console: { info() {}, error() {}, warn: m => warnings.push(m) } });
  ctx.globalThis = ctx;
  for (const f of ['runtime/loader.js', 'examples/portals/mod.js']) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, f), 'utf8'), ctx, { filename: f });
  }
  const arpg = ctx.__arpg;
  // Just enough of a zod object schema for addCall builders to succeed.
  const fakeSchema = { extend() { return this; }, omit() { return this; }, pick() { return this; }, shape: { text: {} } };
  // Stand-in for the game's teleport call: land on the cell east of the target.
  arpg.api = {
    flavor_text: { schema: fakeSchema },
    hp_delta: { schema: fakeSchema },
    teleport: {
      run(world, { entity, target }) {
        if (target.region) {
          const r = target.region;
          entity.pos = [r.position[0] + Math.floor(r.size[0] / 2), r.position[1] + Math.floor(r.size[1] / 2)];
        } else {
          const t = target.entity;
          entity.pos = [t.pos[0] + (t.size?.[0] ?? 1), t.pos[1]];
        }
        entity.walk = undefined;
        world.teleports = (world.teleports ?? 0) + 1;
        return null;
      },
    },
  };
  return { arpg, warnings };
}

// Grid world with full-height walls at the given x columns.
function makeWorld({ width = 30, height = 10, walls = [10], objects = {}, portals = [] } = {}) {
  const entities = Object.entries(objects).map(([name, pos]) => ({ type: 'object', name, pos, size: [1, 1] }));
  const player = { type: 'player', name: 'Hero', pos: [1, 1] };
  entities.push(player);
  return {
    world: {
      gridSize: [width, height],
      regions: [{ name: 'West Room', position: [0, 0], size: [walls[0], height] }],
      entities,
      activeRealSecs: 0,
      arpgMods: { portals },
      blocked: new Set(walls.flatMap(x => Array.from({ length: height }, (_, y) => `${x},${y}`))),
    },
    player,
  };
}

// Stand-in for the game's A*: 8-way BFS, path excludes the start cell.
function bfs(world, from, dest) {
  const s = [Math.round(from[0]), Math.round(from[1])], g = [Math.round(dest[0]), Math.round(dest[1])];
  const k = c => `${c[0]},${c[1]}`;
  if (k(s) === k(g)) return [];
  const ok = c => c[0] >= 0 && c[1] >= 0 && c[0] < world.gridSize[0] && c[1] < world.gridSize[1] && !world.blocked.has(k(c));
  if (!ok(g)) return null;
  const prev = new Map([[k(s), null]]);
  const queue = [s];
  while (queue.length) {
    const c = queue.shift();
    if (k(c) === k(g)) {
      const out = [];
      for (let x = c; x && k(x) !== k(s); x = prev.get(k(x))) out.unshift(x);
      return out;
    }
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
      const n = [c[0] + dx, c[1] + dy];
      if ((dx || dy) && ok(n) && !prev.has(k(n))) {
        prev.set(k(n), c);
        queue.push(n);
      }
    }
  }
  return null;
}

const cellKey = p => `${p[0]},${p[1]}`;
const cellar = { name: 'Cellar stairs', from: { object: 'Trapdoor' }, to: { object: 'Ladder' }, twoWay: true };

test('a walk to an unconnected room heads for the portal', () => {
  const { arpg } = load();
  const { world, player } = makeWorld({ objects: { Trapdoor: [8, 5], Ladder: [12, 5] }, portals: [cellar] });
  const p = arpg.path(world, [1, 1], [18, 8], player, {}, bfs);
  assert.equal(cellKey(p.at(-1)), '8,5');
});

test('stepping onto the pad moves you beside the other end, without bouncing back', () => {
  const { arpg } = load();
  const { world, player } = makeWorld({ objects: { Trapdoor: [8, 5], Ladder: [12, 5] }, portals: [cellar] });
  arpg.tick(world); // first sight
  player.pos = [8, 5];
  arpg.tick(world);
  assert.equal(cellKey(player.pos), '13,5');
  arpg.tick(world);
  assert.equal(world.teleports, 1);
  player.pos = [12, 5]; // walks onto the ladder: back up
  arpg.tick(world);
  assert.equal(cellKey(player.pos), '9,5');
  assert.equal(world.teleports, 2);
});

test('someone already standing on a pad when the game loads stays put', () => {
  const { arpg } = load();
  const { world, player } = makeWorld({ objects: { Trapdoor: [8, 5], Ladder: [12, 5] }, portals: [cellar] });
  player.pos = [8, 5];
  arpg.tick(world);
  arpg.tick(world);
  assert.equal(world.teleports, undefined);
});

test('a shorter plain walk wins over a portal', () => {
  const { arpg } = load();
  const { world, player } = makeWorld({ objects: { Trapdoor: [8, 5], Ladder: [12, 5] }, portals: [cellar] });
  const p = arpg.path(world, [1, 1], [4, 4], player, {}, bfs);
  assert.equal(cellKey(p.at(-1)), '4,4');
});

test('chains portals across several rooms', () => {
  const { arpg } = load();
  const { world, player } = makeWorld({
    walls: [10, 20],
    objects: { T1: [8, 5], L1: [12, 5], T2: [18, 5], L2: [22, 5] },
    portals: [
      { name: 'First', from: { object: 'T1' }, to: { object: 'L1' } },
      { name: 'Second', from: { object: 'T2' }, to: { object: 'L2' } },
    ],
  });
  assert.equal(cellKey(arpg.path(world, [1, 1], [28, 8], player, {}, bfs).at(-1)), '8,5');
  arpg.tick(world);
  player.pos = [8, 5];
  arpg.tick(world);
  assert.equal(cellKey(player.pos), '13,5');
  assert.equal(cellKey(arpg.path(world, player.pos, [28, 8], player, {}, bfs).at(-1)), '18,5');
});

test('a one-way portal is never used backwards', () => {
  const { arpg } = load();
  const { world, player } = makeWorld({
    objects: { Trapdoor: [8, 5], Ladder: [12, 5] },
    portals: [{ name: 'Chute', from: { object: 'Trapdoor' }, to: { object: 'Ladder' } }],
  });
  player.pos = [15, 5];
  assert.equal(arpg.path(world, player.pos, [2, 2], player, {}, bfs), null);
});

test('region and cell ends work', () => {
  const { arpg } = load();
  const { world, player } = makeWorld({
    portals: [{ name: 'Mirror', from: { cell: [5, 5] }, to: { region: 'West Room' } }],
  });
  world.regions.push({ name: 'East Room', position: [11, 0], size: [19, 10] });
  world.arpgMods.portals.push({ name: 'Gate', from: { region: 'East Room' }, to: { cell: [3, 3] } });
  arpg.tick(world);
  player.pos = [5, 5];
  arpg.tick(world);
  assert.equal(cellKey(player.pos), '5,5', 'lands in the middle of West Room');
});

test('a walk queries plain paths without an entity untouched', () => {
  const { arpg } = load();
  const { world } = makeWorld({ objects: { Trapdoor: [8, 5], Ladder: [12, 5] }, portals: [cellar] });
  assert.equal(arpg.path(world, [1, 1], [18, 8], undefined, {}, bfs), null);
  assert.equal(arpg.path(world, [1, 1], [18, 8], { type: 'npc' }, { maxCost: 50 }, bfs), null);
});

test('attached characters ride along instead of using pads', () => {
  const { arpg } = load();
  const { world, player } = makeWorld({ objects: { Trapdoor: [8, 5], Ladder: [12, 5] }, portals: [cellar] });
  player.attachment = { to: 'x' };
  arpg.tick(world);
  player.pos = [8, 5];
  arpg.tick(world);
  assert.equal(world.teleports, undefined);
});

test('missing ends are skipped with one warning', () => {
  const { arpg, warnings } = load();
  const { world } = makeWorld({ objects: { Trapdoor: [8, 5] }, portals: [cellar] });
  arpg.tick(world);
  arpg.tick(world);
  assert.equal(arpg.portals.edgesOf(world).length, 0);
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /Cellar stairs.*to end not found/);
});

const tunnel = { name: "Smugglers' tunnel", from: { object: 'Trapdoor' }, to: { object: 'Ladder' }, twoWay: true, secret: true, knownBy: ['Marrow Jack'] };

function secretWorld() {
  const made = makeWorld({ objects: { Trapdoor: [8, 5], Ladder: [12, 5] }, portals: [tunnel] });
  const jack = { type: 'npc', name: 'Marrow Jack', pos: [2, 2] };
  const townsman = { type: 'npc', name: 'Hal Sedge', pos: [3, 3] };
  made.world.entities.push(jack, townsman);
  return { ...made, jack, townsman };
}

test('only those in the know route walks through an undiscovered secret portal', () => {
  const { arpg } = load();
  const { world, player, jack, townsman } = secretWorld();
  assert.equal(cellKey(arpg.path(world, jack.pos, [18, 8], jack, {}, bfs).at(-1)), '8,5');
  assert.equal(arpg.path(world, townsman.pos, [18, 8], townsman, {}, bfs), null);
  assert.equal(arpg.path(world, player.pos, [18, 8], player, {}, bfs), null, "the player's own walks don't give it away");
});

test('an NPC wandering across an ordinary pad stays put; one whose walk uses it goes through', () => {
  const { arpg } = load();
  const { world } = makeWorld({ objects: { Trapdoor: [8, 5], Ladder: [12, 5] }, portals: [cellar] });
  const moth = { type: 'npc', name: 'Moth swarm', pos: [7, 5] };
  world.entities.push(moth);
  arpg.tick(world);
  moth.pos = [8, 5];
  arpg.tick(world);
  assert.equal(cellKey(moth.pos), '8,5', 'wandered on: nothing happens');
  moth.pos = [2, 2];
  arpg.tick(world);
  arpg.path(world, moth.pos, [18, 8], moth, {}, bfs); // a planned walk through the portal
  moth.pos = [8, 5];
  arpg.tick(world);
  assert.equal(cellKey(moth.pos), '13,5');
});

test('the player finds a secret portal by using it; only nearby onlookers learn it too', () => {
  const { arpg } = load();
  const { world, player, townsman } = secretWorld();
  const farmer = { type: 'npc', name: 'Godric Thorne', pos: [1, 9] };
  world.entities.push(farmer);
  townsman.pos = [5, 5]; // 3 cells from the trapdoor, same room
  arpg.tick(world);
  player.pos = [8, 5];
  arpg.tick(world);
  assert.equal(cellKey(player.pos), '13,5');
  assert.equal(world.arpgMods.portalState.discovered[0], true);
  assert.deepEqual([...world.arpgMods.portalState.known[0]], ['Hal Sedge']);
  assert.match(townsman.memories[0].text, /Saw Hero slip through a hidden way at Trapdoor/);
  assert.equal(farmer.memories, undefined, 'too far away to see it');
  assert.equal(cellKey(arpg.path(world, player.pos, [2, 2], player, {}, bfs).at(-1)), '12,5', 'the player now routes through it');
  assert.equal(cellKey(arpg.path(world, townsman.pos, [18, 8], townsman, {}, bfs).at(-1)), '8,5', 'so does the onlooker');
  assert.equal(arpg.path(world, farmer.pos, [18, 8], farmer, {}, bfs), null, 'but not the farmer');
});

// The player uses the secret trapdoor in front of Hal; returns whether Hal learned it.
function watchedUse(setup) {
  const { arpg } = load();
  const { world, player, townsman } = secretWorld();
  townsman.pos = [5, 5];
  world.gameTimeSecs = 10 * 3600;
  world.overseerHistory = [];
  setup(world, player);
  arpg.tick(world);
  player.pos = [8, 5];
  arpg.tick(world);
  assert.equal(cellKey(player.pos), '13,5', 'the player still goes through');
  return !!world.arpgMods.portalState.known?.[0]?.includes('Hal Sedge');
}

const turn = (t, playerAction, roll) => ({ t, playerAction, events: [], response: roll ? { roll } : { plaus: { verdict: 'trivial' } } });

test('nobody sees a player who just sneaked successfully', () => {
  const sneaked = (w, roll) => w.overseerHistory.push(turn(w.gameTimeSecs - 120, '(Creep toward the cabin)', roll));
  assert.equal(watchedUse(w => sneaked(w, { relevant_skill: 'Stealth', outcome: 'major_success' })), false);
  assert.equal(watchedUse(w => sneaked(w, null)), false, 'judged trivial: still sneaking');
  assert.equal(watchedUse(w => sneaked(w, { relevant_skill: 'Stealth', outcome: 'failure' })), true, 'a failed roll is seen');
});

test('stealth is read from the roll skill, statuses, the current action and scenario words', () => {
  const roll = skill => w => w.overseerHistory.push(turn(w.gameTimeSecs - 60, '(Go to the pallet)', { relevant_skill: skill, outcome: 'success' }));
  assert.equal(watchedUse(roll('Stealth')), false);
  assert.equal(watchedUse(roll('Street Smarts')), true, 'not a stealth skill');
  assert.equal(watchedUse((w, p) => { p.statusEffects = [{ desc: 'Hidden in the shadows' }]; }), false);
  assert.equal(watchedUse((w, p) => { p.activity = { summary: 'sneaking along the wall' }; }), false);
  assert.equal(watchedUse(w => {
    w.arpgMods.portalSettings = { stealthWords: ['Shadowstep'] };
    roll('Shadowstep')(w);
  }), false);
});

test('an old sneak no longer hides the player', () => {
  assert.equal(watchedUse(w => w.overseerHistory.push(turn(w.gameTimeSecs - 20 * 60, '(Sneak in)', null))), true);
  assert.equal(watchedUse(w => {
    w.overseerHistory.push(turn(w.gameTimeSecs - 5 * 60, '(Sneak in)', null));
    w.overseerHistory.push(turn(w.gameTimeSecs - 60, '(Wave at Hal)', null));
  }), true, 'the latest action counts');
});

test('unwalled areas do not block the view; walls do', () => {
  const { arpg } = load();
  const { world, player, townsman } = secretWorld();
  // The trapdoor sits in an unwalled camp; Hal stands just outside it, 3 cells away.
  world.regions.push({ name: 'Camp', position: [6, 3], size: [4, 4] });
  townsman.pos = [5, 5];
  // Godric is as close, but behind the walls of a shed.
  const godric = { type: 'npc', name: 'Godric Thorne', pos: [7, 8] };
  world.entities.push(godric);
  world.regions.push({ name: 'Shed', position: [6, 8], size: [3, 2], wall: 'wood' });
  arpg.tick(world);
  player.pos = [8, 5];
  arpg.tick(world);
  const known = [...world.arpgMods.portalState.known[0]];
  assert.ok(known.includes('Hal Sedge'));
  assert.ok(!known.includes('Godric Thorne'));
});

test('portal_reveal tells the player only; portal_tell tells one character', () => {
  const { arpg } = load();
  const { world, player, townsman } = secretWorld();
  assert.match(arpg.api.portal_reveal.run(world, { name: 'Front door' }), /no secret passage/);
  assert.equal(arpg.api.portal_reveal.run(world, { name: "smugglers' TUNNEL" }), null);
  assert.equal(cellKey(arpg.path(world, player.pos, [18, 8], player, {}, bfs).at(-1)), '8,5');
  assert.equal(arpg.path(world, townsman.pos, [18, 8], townsman, {}, bfs), null);
  assert.equal(arpg.api.portal_tell.run(world, { name: "Smugglers' tunnel", target: townsman }), null);
  assert.equal(cellKey(arpg.path(world, townsman.pos, [18, 8], townsman, {}, bfs).at(-1)), '8,5');
  assert.match(townsman.memories.at(-1).text, /Learned of a hidden way: Smugglers' tunnel/);
});

test('an ordinary portal with a knownBy list is known only to those characters', () => {
  const { arpg } = load();
  const ferry = { name: 'Ferry', from: { object: 'Trapdoor' }, to: { object: 'Ladder' }, knownBy: ['Hal Sedge'] };
  const { world, player } = makeWorld({ objects: { Trapdoor: [8, 5], Ladder: [12, 5] }, portals: [ferry] });
  const hal = { type: 'npc', name: 'Hal Sedge', pos: [2, 2] };
  const moth = { type: 'npc', name: 'Moth swarm', pos: [3, 3] };
  world.entities.push(hal, moth);
  assert.equal(cellKey(arpg.path(world, hal.pos, [18, 8], hal, {}, bfs).at(-1)), '8,5');
  assert.equal(arpg.path(world, moth.pos, [18, 8], moth, {}, bfs), null);
  assert.equal(cellKey(arpg.path(world, player.pos, [18, 8], player, {}, bfs).at(-1)), '8,5', 'not secret: the player knows it');
});

test('the GM hears about secret passages separately until they are found', () => {
  const { arpg } = load();
  const { world } = secretWorld();
  arpg.promptBudgets = {};
  const before = { head: [], sections: [], tail: [] };
  arpg.prompt(before, world);
  assert.deepEqual(before.sections.map(s => s.kind), ['secret_passages']);
  assert.equal(before.sections[0].content, "- Smugglers' tunnel: Trapdoor in West Room <-> Ladder (known to: Marrow Jack)");
  arpg.api.portal_reveal.run(world, { name: "Smugglers' tunnel" });
  const after = { head: [], sections: [], tail: [] };
  arpg.prompt(after, world);
  assert.deepEqual(after.sections.map(s => s.kind), ['passages']);
});

test('the GM is told about the passages', () => {
  const { arpg } = load();
  const { world } = makeWorld({ objects: { Trapdoor: [8, 5], Ladder: [12, 5] }, portals: [cellar] });
  arpg.promptBudgets = {};
  const parts = { head: [], sections: [], tail: [] };
  arpg.prompt(parts, world);
  assert.equal(parts.sections[0].kind, 'passages');
  assert.equal(parts.sections[0].content, '- Cellar stairs: Trapdoor in West Room <-> Ladder');
  assert.ok(arpg.promptBudgets.passages >= 1e6);
});
