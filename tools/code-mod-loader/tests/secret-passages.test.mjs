// node --test   (from tools/code-mod-loader)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

const clock = { ms: 0 };

// A fresh sandbox with the loader and the secret-passages mod, as the game page would run
// them. `performance` drives the once-a-second discovery pass; the two sight helpers stand
// in for what the patched bundle supplies.
function load() {
  const ctx = vm.createContext({
    console: { info() {}, error() {}, warn() {} },
    performance: { now: () => clock.ms },
  });
  ctx.globalThis = ctx;
  for (const f of ['runtime/loader.js', 'examples/secret-passages/mod.js']) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, f), 'utf8'), ctx, { filename: f });
  }
  return ctx.__arpg;
}

// The GM call is registered once the api registry exists; the stub carries the one field
// type the mod reuses (plain text).
function withApi(arpg) {
  const field = { optional() { return field; } };
  const schema = { shape: { text: field }, omit() { return schema; }, extend() { return schema; } };
  arpg.api = { flavor_text: { schema } };
}

// Line of sight from an observer's centre to a door's midpoint. `clear` decides.
function withSight(arpg, clear = () => true) {
  arpg.game.sightBlockers = () => [];
  arpg.game.lineClear = (from, to) => clear(from, to);
}

const effect = () => ({
  def: { desc: 'secret passage', emoji: '🕳️', type: 'constant', mechanics: [{ type: 'concealed' }] },
  appliedAt: 28800,
});

const secretDoor = () => ({
  id: 'd1', name: 'Bookcase door', type: 'object',
  objectTemplate: { door: 'door' }, pos: [15, 11], size: [0, 1],
  statusEffects: [effect()],
});

// Two rooms side by side with a vertical secret door between them at [15, 11]: its
// crossing [[14, 11], [15, 11]] is the Hall's "e" opening at [14, 11] and the Study's "w"
// opening at [15, 11]. The Hall's west opening is an ordinary door's.
function make(passages = { d1: { hint: 'a draught behind the bookcase' } }, settings, more = []) {
  const player = { id: 'p1', name: 'Wren', type: 'player', pos: [12, 11], size: [1, 1] };
  const alys = { id: 'n1', name: 'Alys', type: 'npc', pos: [16, 11], size: [1, 1], memory: '' };
  const bran = { id: 'n2', name: 'Bran', type: 'npc', pos: [17, 12], size: [1, 1], memory: '' };
  const front = {
    id: 'd0', name: 'Front door', type: 'object',
    objectTemplate: { door: 'door' }, pos: [10, 11], size: [0, 1],
  };
  const world = {
    regionsRev: 7,
    regions: [
      { name: 'Hall', position: [10, 10], size: [5, 4], wall: 'stone', openings: [[14, 11, 'e'], [10, 11, 'w']] },
      { name: 'Study', position: [15, 10], size: [5, 4], wall: 'stone', openings: [[15, 11, 'w']] },
      { name: 'Meadow', position: [30, 30], size: [6, 6] },
    ],
    entities: [secretDoor(), front, player, alys, bran, ...more],
    player,
    log: [],
    logCounter: 0,
    gameTimeSecs: 28800,
  };
  const scenario = { arpgMods: { secretPassages: { passages } } };
  if (settings) scenario.arpgMods.secretPassages.settings = settings;
  return { world, scenario, player, alys, bran, door: world.entities[0], front };
}

function setup(arpg, passages, settings, more) {
  const m = make(passages, settings, more);
  arpg.worldCreated(m.world, m.scenario, false);
  return m;
}

const knownBy = (world, id) => [...(world.arpgMods?.secretPassages?.known?.[id] ?? [])];
const logTexts = world => [...world.log.map(l => l.text)];
const parts = () => ({ head: [], sections: [], tail: [] });
const secrets = p => p.sections.find(s => s.kind === 'secrets');

test('world creation resolves knownBy names to entity ids, skipping unknown ones', () => {
  const arpg = load();
  const m = setup(arpg, { d1: { knownBy: ['Alys', 'Nobody Else', 'Bran'] } });
  assert.deepEqual(knownBy(m.world, 'd1'), ['n1', 'n2']);
});

test('a world that already carries known (a save) resolves nothing again', () => {
  const arpg = load();
  const m = make({ d1: { knownBy: ['Alys'] } });
  m.world.arpgMods = { secretPassages: { passages: m.scenario.arpgMods.secretPassages.passages, known: { d1: ['p1'] } } };
  arpg.worldCreated(m.world, {}, false);
  assert.deepEqual(knownBy(m.world, 'd1'), ['p1']);
});

test('an unknown secret door is hidden, its openings drawn shut, its doorway left out', () => {
  const arpg = load();
  const m = setup(arpg);
  const [hall, study, meadow] = m.world.regions;
  assert.equal(arpg.hidden(m.world, m.door), true);
  assert.equal(arpg.hidden(m.world, m.front), false, 'an ordinary door shows');
  const regions = arpg.wallRegions(m.world.regions);
  assert.notEqual(regions, m.world.regions);
  assert.notEqual(regions[0], hall, 'a region with an opening to close is a copy');
  assert.notEqual(regions[1], study);
  assert.equal(regions[0].name, 'Hall', 'the copy keeps the region');
  assert.deepEqual([...regions[0].openings], [[10, 11, 'w']], 'the secret opening goes, the front door stays');
  assert.deepEqual([...regions[1].openings], [], 'the Study side closes too');
  assert.equal(regions[2], meadow, 'a region with nothing to close passes through');
  assert.equal(arpg.doorwayShown(m.world, { crossings: [], room: study, doors: [m.door] }), false);
  assert.equal(arpg.doorwayShown(m.world, { crossings: [], room: hall, doors: [m.front] }), true);
});

test('a secret door the player knows shows: same region list, same doorway', () => {
  const arpg = load();
  const m = setup(arpg, { d1: { knownBy: ['Wren'] } });
  assert.equal(arpg.hidden(m.world, m.door), false);
  assert.equal(arpg.wallRegions(m.world.regions), m.world.regions);
  assert.equal(arpg.doorwayShown(m.world, { crossings: [], room: null, doors: [m.door] }), true);
});

test('with no secret doors the region list is the same array', () => {
  const arpg = load();
  const m = make({});
  m.door.statusEffects.length = 0;
  arpg.worldCreated(m.world, m.scenario, false);
  assert.equal(arpg.hidden(m.world, m.door), false);
  assert.equal(arpg.wallRegions(m.world.regions), m.world.regions);
});

test('a horizontal secret door closes its opening on both rooms too', () => {
  const arpg = load();
  const south = { name: 'Kitchen', position: [10, 16], size: [5, 4], wall: 'brick', openings: [[12, 19, 'n']] };
  const north = { name: 'Pantry', position: [10, 20], size: [5, 4], wall: 'brick', openings: [[12, 20, 's']] };
  const hatch = {
    id: 'h1', name: 'Hatch', type: 'object',
    objectTemplate: { door: 'door' }, pos: [12, 20], size: [1, 0],
    statusEffects: [effect()],
  };
  const player = { id: 'p1', name: 'Wren', type: 'player', pos: [11, 17], size: [1, 1] };
  const world = { regionsRev: 0, regions: [south, north], entities: [hatch, player], player, log: [] };
  arpg.worldCreated(world, { arpgMods: { secretPassages: {} } }, false);
  const regions = arpg.wallRegions(world.regions);
  assert.deepEqual([...regions[0].openings], []);
  assert.deepEqual([...regions[1].openings], []);
});

test('a secret door is gated and passes only for characters who know it', () => {
  const arpg = load();
  const m = setup(arpg, { d1: { knownBy: ['Alys'] } });
  assert.equal(arpg.doorGated(m.world, m.door), true);
  assert.equal(arpg.doorGated(m.world, m.front), false, 'an ordinary door is not gated');
  assert.equal(arpg.doorPasses(m.world, m.door, m.alys, () => true), true, 'a knower keeps the native answer');
  assert.equal(arpg.doorPasses(m.world, m.door, m.bran, () => true), false, 'shut for a non-knower');
  assert.equal(arpg.doorPasses(m.world, m.door, undefined, () => true), false, 'no walker: shut');
  assert.equal(arpg.doorPasses(m.world, m.front, m.bran, () => true), true, 'an ordinary door is left alone');
});

test('a known secret door that is also locked still needs the key', () => {
  const arpg = load();
  const m = setup(arpg, { d1: { knownBy: ['Alys'] } });
  m.door.statusEffects.push({
    def: { desc: 'locked', emoji: '🔒', type: 'constant', mechanics: [{ type: 'locked' }] },
    appliedAt: 28800,
  });
  assert.equal(arpg.doorPasses(m.world, m.door, m.alys, () => false), false, 'a knower without a key: native false stands');
  assert.equal(arpg.doorPasses(m.world, m.door, m.alys, () => true), true, 'a knower with a key passes');
  assert.equal(arpg.doorPasses(m.world, m.door, m.bran, () => true), false, 'a non-knower stays shut');
});

test('in range and in sight, the player finds the door on a good roll', () => {
  const arpg = load();
  withSight(arpg);
  const m = setup(arpg, { d1: { hint: 'a draught behind the bookcase', findChance: 0.5 } });
  arpg.secretPassages.random = () => 0.4;
  m.player.pos = [13, 11]; // centre 1.5 cells from the door's midpoint [15, 11.5]
  arpg.tick(m.world);
  assert.deepEqual(knownBy(m.world, 'd1'), ['p1']);
  assert.deepEqual(logTexts(m.world), ['You found a hidden door: Bookcase door. a draught behind the bookcase']);
  assert.ok(m.world.log[0].id > 0 && m.world.log[0].type === 'mechanic');
});

test('out of range: no roll', () => {
  const arpg = load();
  withSight(arpg);
  const m = setup(arpg);
  let rolls = 0;
  arpg.secretPassages.random = () => { rolls++; return 0; };
  m.player.pos = [11, 11]; // centre 3.5 cells away, findRange is 2
  clock.ms += 1000;
  arpg.tick(m.world);
  assert.equal(rolls, 0);
  assert.deepEqual(knownBy(m.world, 'd1'), []);
});

test('without line of sight nothing rolls; with it, the approach rolls', () => {
  const arpg = load();
  withSight(arpg, () => false);
  const m = setup(arpg);
  let rolls = 0;
  arpg.secretPassages.random = () => { rolls++; return 0; };
  m.player.pos = [13, 11];
  clock.ms += 1000;
  arpg.tick(m.world);
  assert.equal(rolls, 0, 'a wall between: no roll');
  withSight(arpg);
  clock.ms += 1000;
  arpg.tick(m.world);
  assert.equal(rolls, 1, 'sight restored: the same approach rolls');
  assert.deepEqual(knownBy(m.world, 'd1'), ['p1'], 'a roll of 0 finds it');
});

test('one roll per approach, a new one after leaving and coming back', () => {
  const arpg = load();
  withSight(arpg);
  const m = setup(arpg);
  let rolls = 0;
  arpg.secretPassages.random = () => { rolls++; return 0.9; }; // always misses
  m.player.pos = [13, 11];
  arpg.tick(m.world);
  clock.ms += 1000;
  arpg.tick(m.world);
  assert.equal(rolls, 1, 'the second pass in the same approach does not roll');
  assert.deepEqual(knownBy(m.world, 'd1'), []);
  m.player.pos = [8, 11]; // centre 6.5 cells away, past findRange + 2: the approach resets
  clock.ms += 1000;
  arpg.tick(m.world);
  assert.equal(rolls, 1, 'out of range: still no roll');
  m.player.pos = [13, 11];
  clock.ms += 1000;
  arpg.tick(m.world);
  assert.equal(rolls, 2, 'a new approach rolls again');
});

test('onlookers learn a door they see used; out of range or behind a wall they do not', () => {
  const arpg = load();
  withSight(arpg, from => from[0] < 18); // Dorn (centre x 18.5) is behind a wall
  const dorn = { id: 'n3', name: 'Dorn', type: 'npc', pos: [18, 11], size: [1, 1], memory: '' };
  const cory = { id: 'n4', name: 'Cory', type: 'npc', pos: [30, 30], size: [1, 1], memory: '' };
  const m = setup(arpg, { d1: { knownBy: ['Alys'], hint: 'a draught behind the bookcase' } }, undefined, [dorn, cory]);
  m.alys.pos = [14, 11]; // west of the door, half a cell from its midpoint
  arpg.tick(m.world); // first pass: records her cell, no crossing yet
  m.alys.pos = [15, 11]; // east of the door
  m.alys.moving = true;
  clock.ms += 1000;
  arpg.tick(m.world);
  assert.deepEqual(knownBy(m.world, 'd1'), ['n1', 'p1', 'n2'], 'the player and Bran learn, in order');
  assert.deepEqual(logTexts(m.world), [
    'You saw Alys slip through a hidden door: Bookcase door.',
    'You found a hidden door: Bookcase door. a draught behind the bookcase',
  ]);
  assert.equal(m.bran.memory, 'Saw Alys slip through a hidden door at Bookcase door.');
  assert.equal(dorn.memory, '', 'behind a wall: no memory');
  assert.equal(cory.memory, '', 'out of onlooker range: no memory');
  assert.equal(m.alys.memory, '', 'the user already knew it');
});

test('a knower who crosses without moving did not use it', () => {
  const arpg = load();
  withSight(arpg);
  const m = setup(arpg, { d1: { knownBy: ['Alys'] } });
  m.alys.pos = [14, 11];
  arpg.tick(m.world);
  m.alys.pos = [15, 11]; // not moving: the game slid her, or the GM moved her
  clock.ms += 1000;
  arpg.tick(m.world);
  assert.deepEqual(knownBy(m.world, 'd1'), ['n1'], 'nobody else learns');
});

test('secret_reveal teaches the player by default', () => {
  const arpg = load();
  withApi(arpg);
  const m = setup(arpg);
  assert.equal(arpg.api.secret_reveal.run(m.world, { door: 'Bookcase door' }), null);
  assert.deepEqual(knownBy(m.world, 'd1'), ['p1']);
  assert.deepEqual(logTexts(m.world), ['You found a hidden door: Bookcase door. a draught behind the bookcase']);
  assert.equal(arpg.wallRegions(m.world.regions), m.world.regions, 'no longer hidden');
  assert.equal(arpg.api.secret_reveal.run(m.world, { door: 'Bookcase door' }), null, 'already known: no error');
  assert.equal(m.world.log.length, 1, 'and nothing logged again');
});

test('secret_reveal teaches a named NPC, and rejects bad arguments', () => {
  const arpg = load();
  withApi(arpg);
  const m = setup(arpg);
  assert.equal(arpg.api.secret_reveal.run(m.world, { door: 'Bookcase door', target: 'Bran' }), null);
  assert.equal(m.bran.memory, 'Learned of the hidden door at Bookcase door.');
  assert.deepEqual(knownBy(m.world, 'd1'), ['n2']);
  assert.match(arpg.api.secret_reveal.run(m.world, { door: 'Alys' }), /is not a door/);
  assert.match(arpg.api.secret_reveal.run(m.world, { door: 'Front door' }), /is not a secret door/);
  assert.match(arpg.api.secret_reveal.run(m.world, { door: 'No such door' }), /nothing named/);
  assert.match(arpg.api.secret_reveal.run(m.world, { door: 'Bookcase door', target: 'Nobody' }), /no character named/);
});

test('removing the secret-passage effect makes the door public after the next refresh', () => {
  const arpg = load();
  withSight(arpg);
  const m = setup(arpg);
  assert.equal(arpg.hidden(m.world, m.door), true);
  const rev = m.world.regionsRev;
  m.door.statusEffects.length = 0; // the GM's status_remove
  clock.ms += 1000;
  arpg.tick(m.world);
  assert.equal(arpg.hidden(m.world, m.door), false);
  assert.equal(arpg.doorGated(m.world, m.door), false);
  assert.equal(arpg.doorPasses(m.world, m.door, m.bran, () => true), true, 'an ordinary door again');
  assert.equal(arpg.wallRegions(m.world.regions), m.world.regions);
  assert.equal(m.world.regionsRev, rev + 1, 'the walls are redrawn');
});

const farDoor = () => ({
  id: 'd2', name: 'Cellar hatch', type: 'object',
  objectTemplate: { door: 'door' }, pos: [18, 11], size: [0, 1],
  statusEffects: [effect()],
});

test('the GM section lists nearby secret doors nearest first, with who knows them', () => {
  const arpg = load();
  const m = setup(arpg, { d1: { hint: 'a draught behind the bookcase' }, d2: { knownBy: ['Bran'] } }, undefined, [farDoor()]);
  const p = parts();
  arpg.prompt(p, m.world, { worldChars: 2000 });
  assert.equal(secrets(p).title, 'Secret passages (private — hint, never state them outright):');
  assert.deepEqual([...secrets(p).content.split('\n')], [
    "- Bookcase door (3 m E): known by nobody; player: doesn't know; hint: a draught behind the bookcase",
    "- Cellar hatch (6 m E): known by Bran; player: doesn't know",
  ]);
});

test('a door the player knows says so', () => {
  const arpg = load();
  const m = setup(arpg, { d1: { knownBy: ['Wren', 'Alys'], hint: 'a draught behind the bookcase' } });
  const p = parts();
  arpg.prompt(p, m.world, { worldChars: 2000 });
  assert.equal(secrets(p).content,
    '- Bookcase door (3 m E): known by Alys; player: knows; hint: a draught behind the bookcase');
});

test('the section keeps whole lines up to a share of the world limit', () => {
  const arpg = load();
  const m = setup(arpg, { d1: { hint: 'a draught behind the bookcase' }, d2: { hint: 'y'.repeat(100) } },
    undefined, [farDoor()]);
  const roomy = arpg.prompt(parts(), m.world, { worldChars: 2000 });
  assert.equal([...secrets(roomy).content.split('\n')].length, 2);
  const tight = arpg.prompt(parts(), m.world, { worldChars: 1200 }); // cap 200 characters
  const lines = [...secrets(tight).content.split('\n')];
  assert.equal(lines.length, 1, 'the second line does not fit and is cut whole');
  assert.match(lines[0], /Bookcase door/);
  assert.ok(secrets(tight).content.length <= 200);
  const huge = setup(arpg, { d1: { hint: 'x'.repeat(180) } });
  const lone = arpg.prompt(parts(), huge.world, { worldChars: 100 }); // cap is never below 200
  assert.equal(secrets(lone).content, '', 'a single line longer than the cap is dropped');
  assert.ok(secrets(lone), 'the section itself is still there for the game to drop');
});

test('nothing near the player: empty content', () => {
  const arpg = load();
  const m = setup(arpg);
  m.player.pos = [60, 60];
  const p = parts();
  arpg.prompt(p, m.world, { worldChars: 2000 });
  assert.ok(secrets(p));
  assert.equal(secrets(p).content, '');
});
