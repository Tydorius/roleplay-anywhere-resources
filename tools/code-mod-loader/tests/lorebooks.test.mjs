// node --test   (from tools/code-mod-loader)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

// A fresh sandbox with the loader and the lorebooks mod, as the game page would run them.
function load() {
  const ctx = vm.createContext({ console: { info() {}, error() {} } });
  ctx.globalThis = ctx;
  for (const f of ['runtime/loader.js', 'examples/lorebooks/mod.js']) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, f), 'utf8'), ctx, { filename: f });
  }
  return ctx.__arpg;
}

const scenario = {
  arpgMods: {
    lorebookBudget: 400,
    lorebooks: {
      College: {
        entries: [
          { keys: ['Vellan', 'Archmage'], content: 'Archmage Vellan founded the college.', priority: 5 },
          { keys: ['Sundering'], secondaryKeys: ['war'], content: 'The Sundering war split the realm.' },
          { constant: true, content: 'Magic is illegal outside the walls.' },
          { keys: ['Hidden'], content: 'Never shown.', enabled: false },
        ],
      },
      Tavern: {
        // SillyTavern World Info shape
        entries: {
          0: { uid: 0, key: ['Rusty Flagon'], content: 'The Rusty Flagon waters its ale.', order: 1 },
          1: { uid: 1, key: ['Mira'], content: 'Mira is a spy.', disable: true },
        },
      },
    },
  },
};

function world(extra = {}) {
  const w = { gameTimeSecs: 8 * 3600, overseerHistory: [] };
  return { ...w, ...extra };
}

function parts(nearby, regions = '') {
  return {
    head: [{ kind: 'world', title: 'World background:', content: 'A college of wizards.' }],
    sections: [
      { kind: 'characters', title: 'Characters:', content: nearby },
      { kind: 'regions', title: 'Regions:', content: regions },
    ],
    tail: [{ kind: 'events', title: 'Events:', content: '' }, { kind: 'now', title: 'Now:', content: '08:00' }],
  };
}

function lore(p) {
  return p.sections.find(s => s.kind === 'lore')?.content ?? '';
}

test('reads both entry shapes and skips disabled entries', () => {
  const arpg = load();
  const entries = arpg.lore.entriesOf(scenario.arpgMods);
  // Spread into a local array: arrays from the vm sandbox have another realm's prototype.
  assert.deepEqual([...entries.map(e => e.content)], [
    'Archmage Vellan founded the college.',
    'The Sundering war split the realm.',
    'Magic is illegal outside the walls.',
    'The Rusty Flagon waters its ale.',
  ]);
});

test('matches whole words, case-insensitively, in any script', () => {
  const { mentions } = load().lore;
  assert.equal(mentions('the archmage nods', 'Archmage'), true);
  assert.equal(mentions('Vellanor waves', 'Vellan'), false);
  assert.equal(mentions('(Vellan) waves', 'Vellan'), true);
  assert.equal(mentions('Zoë smiles', 'Zoë'), true);
  assert.equal(mentions('Zoëlle smiles', 'Zoë'), false);
});

test('the world keeps the scenario lorebooks, separately from the scenario', () => {
  const arpg = load();
  const w = world();
  arpg.worldCreated(w, scenario, false);
  assert.equal(Object.keys(w.arpgMods.lorebooks).length, 2);
  assert.notEqual(w.arpgMods, scenario.arpgMods);
});

test('injects constant entries and keyword matches near the player only', () => {
  const arpg = load();
  const w = world();
  arpg.worldCreated(w, scenario, false);
  const p = arpg.prompt(parts('- Archmage Vellan (neutral)', '- Rusty Flagon'), w);
  const text = lore(p);
  assert.match(text, /Archmage Vellan founded/);
  assert.match(text, /illegal outside/);
  assert.doesNotMatch(text, /Rusty Flagon/, 'the full region list is not scanned');
  assert.equal(p.sections.at(-1).kind, 'lore');
});

test('secondary keys must also appear', () => {
  const arpg = load();
  const w = world();
  arpg.worldCreated(w, scenario, false);
  assert.doesNotMatch(lore(arpg.prompt(parts('talk of the Sundering'), w)), /Sundering war/);
  assert.match(lore(arpg.prompt(parts('the Sundering war'), w)), /Sundering war/);
});

test('an entry stays for its sticky window after the last mention', () => {
  const arpg = load();
  const w = world();
  arpg.worldCreated(w, scenario, false);
  arpg.prompt(parts('Vellan'), w);
  w.gameTimeSecs += 9 * 60;
  assert.match(lore(arpg.prompt(parts('nobody'), w)), /Vellan founded/);
  assert.equal(arpg.lore.last.find(l => l.id.startsWith('College#0')).why, 'sticky');
  w.gameTimeSecs += 2 * 60;
  assert.doesNotMatch(lore(arpg.prompt(parts('nobody'), w)), /Vellan founded/);
});

test('the budget keeps constants first, then higher priority', () => {
  const arpg = load();
  const w = world();
  arpg.worldCreated(w, scenario, false);
  w.arpgMods.lorebookBudget = 80;
  const text = lore(arpg.prompt(parts('Vellan at the Rusty Flagon'), w));
  assert.match(text, /illegal outside/);
  assert.match(text, /Vellan founded/);
  assert.doesNotMatch(text, /waters its ale/);
});

test('the last GM turn is scanned too', () => {
  const arpg = load();
  const w = world({ overseerHistory: [{ response: { scene: { actions: [{ actor: 'Guard', action: 'SAY_TO', text: 'Off to the Rusty Flagon' }] } } }] });
  arpg.worldCreated(w, scenario, false);
  assert.match(lore(arpg.prompt(parts('nobody'), w)), /waters its ale/);
});

test('worlds without lorebooks are left alone', () => {
  const arpg = load();
  const w = world();
  arpg.worldCreated(w, {}, false);
  const p = arpg.prompt(parts('Vellan'), w);
  assert.equal(w.arpgMods, undefined);
  assert.equal(lore(p), '');
});

test('a failing mod hook does not break the prompt', () => {
  const arpg = load();
  arpg.onPrompt(() => { throw new Error('boom'); });
  const p = parts('x');
  assert.equal(arpg.prompt(p, world()), p);
});
