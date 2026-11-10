// node --test tests/*.test.mjs   (from tools/code-mod-loader)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

// A stand-in for the zod schemas the game's registry entries carry.
const schema = shape => ({
  shape,
  pick: keys => schema(Object.fromEntries(Object.keys(keys).map(k => [k, shape[k]]))),
  extend: more => schema({ ...shape, ...more }),
});

function load() {
  const ctx = vm.createContext({ console: { info() {}, error() {}, warn() {} } });
  ctx.globalThis = ctx;
  for (const f of ['runtime/loader.js', 'examples/memory-add/mod.js']) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, f), 'utf8'), ctx, { filename: f });
  }
  const arpg = ctx.__arpg;
  // What the api-registry patch does once the game builds its registry.
  arpg.api = {
    flavor_text: { schema: schema({ text: 'string' }) },
    hp_delta: { schema: schema({ target: 'entity', amount: 'number' }) },
  };
  return arpg;
}

test('memory_add registers once the game hands over its registry', () => {
  const arpg = load();
  assert.deepEqual([...arpg.mods], ['memory-add']);
  assert.deepEqual([...arpg.calls], ['memory_add']);
  assert.deepEqual(Object.keys(arpg.api.memory_add.schema.shape), ['target', 'text']);
});

test('its header goes after the entity-state calls', () => {
  const arpg = load();
  const order = JSON.stringify(['header_health', 'header_entity_state', 'header_party', 'header_threads']);
  const list = JSON.parse(arpg.cfg('overseer/api-actions/ordered-api-calls.json', () => order));
  assert.deepEqual(list, ['header_health', 'header_entity_state', 'header_memory', 'header_party', 'header_threads']);
  assert.match(arpg.cfg('overseer/api-actions/header_memory.txt', () => ''), /"call":"memory_add"/);
});

test('appends a sentence to 1.0\'s prose memory, once', () => {
  const run = load().api.memory_add.run;
  const npc = { type: 'npc', name: 'Alys' };
  assert.equal(run({}, { target: npc, text: '  The traveller   saved my brother ' }), null);
  assert.equal(npc.memory, 'The traveller saved my brother.');
  npc.memory = 'Alys runs the Hound\'s Tooth. ' + npc.memory;
  assert.equal(run({}, { target: npc, text: 'I promised them free ale for life!' }), null);
  assert.equal(run({}, { target: npc, text: 'I promised them free ale for life!' }), null);
  assert.equal(npc.memory, 'Alys runs the Hound\'s Tooth. The traveller saved my brother. I promised them free ale for life!');
  assert.equal(npc.memories, undefined, '1.0 migrates the old memories list away; never write it');
});

test('rejects non-characters and empty text', () => {
  const run = load().api.memory_add.run;
  assert.match(run({}, { target: { type: 'object', name: 'Barrel' }, text: 'x' }), /must be a character/);
  assert.match(run({}, { target: { type: 'npc', name: 'Alys' }, text: '   ' }), /needs text/);
});
