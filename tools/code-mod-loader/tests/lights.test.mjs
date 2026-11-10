// node --test   (from tools/code-mod-loader)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

function load() {
  const ctx = vm.createContext({ console: { info() {}, error() {}, warn() {} } });
  ctx.globalThis = ctx;
  for (const f of ['runtime/loader.js', 'examples/lights/mod.js']) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, f), 'utf8'), ctx, { filename: f });
  }
  return ctx.__arpg.lights;
}

const hex = c => (c == null ? null : `#${c.toString(16).padStart(6, '0')}`);

// Light sources from the shipped scenarios: name, description → kind, colour (null = the kind's own).
const SHIPPED = [
  ['Hearth', 'stone hearth with glowing embers', 'fire', null],
  ['Iron brazier', 'ornate iron basin on tripod legs', 'fire', null],
  ['Candle stand', 'Wrought iron stand with melting wax candle', 'candle', null],
  ['Lamppost', 'Tall black iron lamp with glowing glass', 'lantern', null],
  ['Campfire ring', 'Ring of grey stones with orange fire', 'fire', '#ff8a30'],
  ['Tallow candle', 'Small yellowish tallow candle, dripping wax, white background', 'candle', null],
  ['Oil lamp', 'Brass oil lamp, glass chimney, small flickering flame', 'lantern', null],
  ['Rusty lantern', 'Rusted iron lantern, cracked glass, dim candle', 'lantern', null],
  ['Meditation Stone', 'Flat smooth stone etched with glowing arcane runes, mystical atmosphere', 'magic', null],
  ['Kitchen Oven', 'Heavy cast-iron medieval oven, glowing embers, rustic stone kitchen setting', 'fire', null],
  ['Lamppost', 'Ornate wrought iron lamppost emitting a soft magical blue glow', 'magic', '#6fa0ff'],
  ['Catacombs Brazier', 'Heavy iron basin with flickering violet flames, gothic stone pedestal', 'fire', '#b070ff'],
  ['Black Candle', 'Tapered black wax candle, ornate silver holder, flickering violet flame', 'candle', '#b070ff'],
  ['Glowing mushroom', 'Bioluminescent neon blue mushroom inside a cast iron alchemy cauldron', 'magic', '#6fa0ff'],
  ['Glowing Moss', 'Bioluminescent neon green moss inside a rustic wooden ingredient barrel', 'magic', '#6dff8a'],
  ['Glowing Root', 'Luminous neon-blue tuber root glowing softly inside a clay pot', 'magic', '#6fa0ff'],
  ['Iron Lantern', 'Ornate gothic iron lantern with a glowing magical blue flame', 'lantern', '#6fa0ff'],
  ['Ever-burning Ember', 'Glowing charcoal fragment pulsing with orange heat, ornate silver holder', 'ember', null],
  ['Spectral Shard', 'Glowing translucent crystal fragment pulsing with eerie ghostly blue light', 'magic', '#6fa0ff'],
  ['Computer workstation', 'Desk with dual monitors and keyboard', 'screen', null],
  ['Lamppost', 'Black Victorian-style street lamp, glowing warm bulb', 'electric', '#ffd29a'],
  ['Small flashlight', 'small silver plastic flashlight', 'electric', null],
  ['Espresso machine', 'Silver industrial espresso maker', 'plain', null],
  ['Neon sign', 'Buzzing pink sign over the bar door', 'neon', null],
];

test('the shipped scenarios’ light sources get sensible kinds and colours', () => {
  const lights = load();
  for (const [name, physicalDescription, kind, colour] of SHIPPED) {
    const got = lights.classify({ name, physicalDescription });
    assert.deepEqual([got.kind, hex(got.color)], [kind, colour], name + ': ' + physicalDescription);
  }
});

test('scenario entries by id or name override the classifier', () => {
  const lights = load();
  const world = { arpgMods: { lights: { templates: {
    otpl_a: 'electric',
    'Old Stove': { kind: 'magic', color: '#00ff00', radius: 2, flicker: 0, particles: false },
  } } } };
  assert.equal(lights.profileFor({ id: 'otpl_a', name: 'Hearth' }, world).kind, 'electric');
  const p = lights.profileFor({ id: 'otpl_b', name: 'Old Stove' }, world);
  assert.deepEqual([p.kind, p.color, p.radius, p.amp, p.particles], ['magic', 0x00ff00, 2, 0, null]);
  const off = { arpgMods: { lights: { auto: false } } };
  assert.equal(lights.profileFor({ id: 'x', name: 'Hearth' }, off), null, 'auto off: unlisted sources keep the game’s look');
  const noParticles = { arpgMods: { lights: { particles: false } } };
  assert.equal(lights.profileFor({ id: 'x', name: 'Hearth' }, noParticles).particles, null);
});

test('the glowing template is the object’s own, or the brightest thing carried', () => {
  const { sourceTemplate } = load();
  const hearth = { id: 'otpl_h', name: 'Hearth', light: 0.8 };
  assert.equal(sourceTemplate({ objectTemplate: hearth }), hearth);
  const torch = { id: 'itpl_t', name: 'Torch', light: 0.6 };
  const candle = { id: 'itpl_c', name: 'Candle', light: 0.2 };
  const npc = { type: 'npc', equipment: { hand: { template: candle } }, inventory: [{ template: torch }, { template: { light: 0 } }] };
  assert.equal(sourceTemplate(npc), torch);
  assert.equal(sourceTemplate({ type: 'player', equipment: { hand: { template: candle } }, inventory: [{ template: torch }] }), candle, 'a player’s pack does not glow');
  assert.equal(sourceTemplate({ equipment: {}, inventory: [] }), null);
});

test('motions stay within their swing and differ between lights', () => {
  const { KINDS, motion } = load();
  const fire = { ...KINDS.fire };
  let lo = Infinity, hi = -Infinity;
  for (let t = 0; t < 20; t += 0.013) {
    const m = motion(fire, t, 0.3);
    lo = Math.min(lo, m.i);
    hi = Math.max(hi, m.i);
  }
  assert.ok(lo >= 1 - fire.amp - 1e-9 && hi <= 1 + fire.amp + 1e-9, `${lo}..${hi}`);
  assert.ok(hi - lo > fire.amp, 'a fire visibly flickers');
  assert.notEqual(motion(fire, 1, 0.1).i, motion(fire, 1, 0.7).i);
  assert.deepEqual({ ...motion({ ...KINDS.electric }, 3, 0.5) }, { i: 1, r: 1 });
  const neon = { ...KINDS.neon };
  const drops = Array.from({ length: 4000 }, (_, k) => motion(neon, k / neon.speed, 0.2).i).filter(i => i < 1).length;
  assert.ok(drops > 40 && drops < 300, `neon drops out now and then (${drops} of 4000)`);
});

// A stand-in for Phaser's Light: plain setters and an RGB colour, as in Phaser 3.90.
function fakeLight(intensity, radius) {
  return {
    x: 100, y: 200, intensity, radius,
    color: { r: 1, g: 0.75, b: 0.47, set(r, g, b) { Object.assign(this, { r, g, b }); } },
    setIntensity(v) { this.intensity = v; return this; },
    setRadius(v) { this.radius = v; return this; },
    setColor(rgb) { this.color.set(((rgb >> 16) & 255) / 255, ((rgb >> 8) & 255) / 255, (rgb & 255) / 255); return this; },
  };
}

function fakeScene(entities) {
  const entityLights = new Map();
  for (const e of entities) entityLights.set(e.id, { light: fakeLight(1, 180), gx: 0, gy: 0 });
  return { world: { entities }, entityLights };
}

const hearthEntity = () => ({ id: 'obj_h', type: 'object', name: 'Hearth', pos: [3, 4],
  objectTemplate: { id: 'otpl_h', name: 'Hearth', light: 0.8 } });

test('each frame works from the game’s values and never compounds its own', () => {
  const lights = load();
  const scene = fakeScene([hearthEntity()]);
  const L = scene.entityLights.get('obj_h').light;
  const fire = lights.KINDS.fire;
  lights.applyFrame(scene, 1000);
  const first = L.radius;
  assert.ok(Math.abs(first / (180 * fire.radius) - 1) <= fire.amp * 0.35 + 1e-9);
  // The game didn't re-sync this frame: the base is still 180, not last frame's output.
  lights.applyFrame(scene, 1000);
  assert.equal(L.radius, first);
  // The game re-synced with a new reach setting: that becomes the base.
  L.setRadius(100);
  lights.applyFrame(scene, 1000);
  assert.ok(Math.abs(L.radius / (100 * fire.radius) - 1) <= fire.amp * 0.35 + 1e-9);
  assert.equal(hex(Math.round(L.color.r * 255) << 16 | Math.round(L.color.g * 255) << 8 | Math.round(L.color.b * 255)), hex(fire.color));
});

test('turning the mod off puts the game’s light back', () => {
  const lights = load();
  const scene = fakeScene([hearthEntity()]);
  const L = scene.entityLights.get('obj_h').light;
  lights.applyFrame(scene, 1234);
  assert.notEqual(L.radius, 180);
  lights.setEnabled(false);
  assert.deepEqual([L.intensity, L.radius, L.color.r, L.color.g, L.color.b], [1, 180, 1, 0.75, 0.47]);
  lights.applyFrame(scene, 2000);
  assert.equal(L.radius, 180, 'stays off');
});

test('a scenario can turn the mod off', () => {
  const lights = load();
  const scene = fakeScene([hearthEntity()]);
  scene.world.arpgMods = { lights: false };
  lights.applyFrame(scene, 1000);
  assert.equal(scene.entityLights.get('obj_h').light.radius, 180);
});

test('fires get an emitter that follows the light and goes when the light does', () => {
  const lights = load();
  const scene = fakeScene([hearthEntity()]);
  const made = [];
  scene.textures = { exists: () => true };
  scene.depthForY = y => 50 + (100 - y);
  scene.add = { particles(x, y, key, cfg) {
    const e = { x, y, cfg, emitting: true, destroyed: false,
      setPosition(a, b) { this.x = a; this.y = b; return this; },
      setDepth(d) { this.depth = d; return this; },
      destroy() { this.destroyed = true; } };
    made.push(e);
    return e;
  } };
  lights.applyFrame(scene, 1000);
  assert.equal(made.length, 1);
  assert.equal(made[0].depth, 50 + 96 + 0.001, 'sorted with the hearth’s row');
  assert.deepEqual(JSON.parse(JSON.stringify(lights.report().map(r => [r.kind, r.particles]))), [["fire", true]]);
  scene.entityLights.delete('obj_h');
  lights.applyFrame(scene, 1100);
  assert.ok(made[0].destroyed);
  assert.equal(lights.report().length, 0);
});

// A sprite with Phaser's tint API (setTint stores tintTopLeft).
const fakeSprite = tint => ({ tintTopLeft: tint, setTint(c) { this.tintTopLeft = c; return this; } });

function wallScene() {
  // A hearth at (100,200), a bed 60 px away behind a wall, and a chair 60 px away in the open.
  const hearth = hearthEntity();
  const bed = { id: 'obj_bed', type: 'object', name: 'Bed', pos: [3, 2] };
  const chair = { id: 'obj_chair', type: 'object', name: 'Chair', pos: [5, 4] };
  const scene = fakeScene([hearth]);
  scene.world.entities.push(bed, chair);
  const lamp = scene.entityLights.get(hearth.id);
  Object.assign(lamp, { gx: 100, gy: 200 });
  const views = new Map([
    [bed.id, { entity: bed, container: { x: 100, y: 260 }, sprite: fakeSprite(0xcccccc) }],
    [chair.id, { entity: chair, container: { x: 160, y: 200 }, sprite: fakeSprite(0xcccccc) }],
  ]);
  scene.views = views;
  scene.lights = { ambientColor: { r: 0.2, g: 0.2, b: 0.3 }, lights: [lamp.light] };
  scene.wallCasterSegments = () => 'walls';
  scene.losBlocked = (lx, ly, x, y) => y > 230; // a wall runs along y = 230
  return { scene, bed: views.get(bed.id).sprite, chair: views.get(chair.id).sprite };
}

test('a lamp behind a wall no longer lights an object, and the game\u2019s tint comes back', () => {
  const lights = load();
  const { scene, bed, chair } = wallScene();
  lights.applyFrame(scene, 1000);
  assert.equal(chair.tintTopLeft, 0xcccccc, 'in the open: untouched');
  const [r, g, b] = [(bed.tintTopLeft >> 16) & 255, (bed.tintTopLeft >> 8) & 255, bed.tintTopLeft & 255];
  assert.ok(r < 0xcc * 0.5 && g < 0xcc * 0.5, `behind the wall: darker (${bed.tintTopLeft.toString(16)})`);
  assert.ok(b > r, 'the warm lamp is what was taken out, so what is left is the cooler ambient');
  // The game re-tints the next frame: that's the new base, not compounded.
  const first = bed.tintTopLeft;
  bed.setTint(0xcccccc);
  lights.applyFrame(scene, 1000);
  assert.equal(bed.tintTopLeft, first);
  // The wall goes: the game's tint is put back.
  scene.losBlocked = () => false;
  scene.wallCasterSegments = () => 'new walls';
  lights.applyFrame(scene, 1000);
  assert.equal(bed.tintTopLeft, 0xcccccc);
});

test('occlusion can be turned off per scenario, and turning the mod off restores tints', () => {
  const lights = load();
  let { scene, bed } = wallScene();
  scene.world.arpgMods = { lights: { occlusion: false } };
  lights.applyFrame(scene, 1000);
  assert.equal(bed.tintTopLeft, 0xcccccc);
  ({ scene, bed } = wallScene());
  lights.applyFrame(scene, 1000);
  assert.notEqual(bed.tintTopLeft, 0xcccccc);
  lights.setEnabled(false);
  assert.equal(bed.tintTopLeft, 0xcccccc);
});

test('the shadow pass sees the steady look, so flicker never forces a shadow redraw', () => {
  const lights = load();
  const scene = fakeScene([hearthEntity()]);
  const L = scene.entityLights.get('obj_h').light;
  const steady = [1 * lights.KINDS.fire.intensity, 180 * lights.KINDS.fire.radius];
  const afterRadii = [];
  for (const t of [1000, 1137, 1290, 1411, 2011]) {
    L.setIntensity(1); // what syncEntityLight does every frame
    L.setRadius(180);
    lights.beforeShadows(scene, t);
    assert.deepEqual([L.intensity, L.radius], steady, `t=${t}`);
    lights.afterShadows(scene, t);
    afterRadii.push(L.radius);
  }
  assert.ok(new Set(afterRadii).size > 1, 'the flicker moves the radius after the shadows');
});

test('the wrapper hands the shadow pass steady values and passes its result through', () => {
  const lights = load();
  const scene = fakeScene([hearthEntity()]);
  const L = scene.entityLights.get('obj_h').light;
  const seen = [];
  scene.drawPointShadows = () => { seen.push([L.intensity, L.radius]); return 'drawn'; };
  lights.attach(scene);
  const steady = [1 * lights.KINDS.fire.intensity, 180 * lights.KINDS.fire.radius];
  for (let i = 0; i < 3; i++) {
    L.setIntensity(1);
    L.setRadius(180);
    assert.equal(scene.drawPointShadows(), 'drawn');
  }
  assert.deepEqual(seen, [steady, steady, steady]);
  assert.ok(lights.stats().frames >= 3);
  assert.ok(lights.stats().msPerFrame >= 0);
});

test('a lamp the mod enlarges stops short of the next plane', () => {
  const lights = load();
  const scene = fakeScene([hearthEntity()]);
  scene.world.arpgMods = { lights: { templates: { Hearth: { kind: 'fire', radius: 10, flicker: 0 } } } };
  const L = scene.entityLights.get('obj_h').light;
  lights.applyFrame(scene, 1000);
  assert.equal(L.radius, 736);
  L.setRadius(900); // the player's own reach, above the cap
  lights.applyFrame(scene, 1000);
  assert.equal(L.radius, 900, 'the game’s own reach is left alone');
});

test('a lamp on another plane never lights a sprite there', () => {
  const lights = load();
  const { scene, bed, chair } = wallScene();
  scene.losBlocked = () => false;
  scene.world.regions = [{ id: 'rgn_up', position: [40, 0], size: [10, 10], pocket: { anchor: 'rgn_x', level: 1 } }];
  scene.world.regionsRev = 1;
  scene.world.entities.find(e => e.id === 'obj_bed').pos = [41, 2]; // its view stays at (100, 260)
  assert.equal(lights.planeOf(scene.world, [41, 2]), 'rgn_up');
  assert.equal(lights.planeOf(scene.world, [3, 4]), '');
  assert.equal(lights.planeOf(scene.world, undefined), null);
  lights.applyFrame(scene, 1000);
  assert.ok(bed.tintTopLeft < 0xcccccc, `another plane: darker (${bed.tintTopLeft.toString(16)})`);
  assert.equal(chair.tintTopLeft, 0xcccccc, 'same plane, no wall: untouched');
  const plain = wallScene();
  plain.scene.losBlocked = () => false;
  lights.applyFrame(plain.scene, 1000);
  assert.equal(plain.bed.tintTopLeft, 0xcccccc, 'without regions the bed is untouched');
});

test('culled sprites are skipped', () => {
  const lights = load();
  const { scene, bed } = wallScene();
  scene.views.get('obj_bed').container.visible = false; // off screen, or inside another entity
  const calls = [];
  const los = scene.losBlocked;
  scene.losBlocked = (...args) => { calls.push(args); return los(...args); };
  lights.applyFrame(scene, 1000);
  assert.equal(bed.tintTopLeft, 0xcccccc);
  assert.ok(!calls.some(args => args[3] === 260), 'no wall test for the bed’s position');
});

test('lamps off screen keep the steady look', () => {
  const lights = load();
  const scene = fakeScene([hearthEntity()]);
  scene.cameras = { main: { worldView: { x: 5000, y: 5000, right: 5800, bottom: 5600 } } };
  lights.applyFrame(scene, 1234);
  const L = scene.entityLights.get('obj_h').light;
  assert.equal(L.radius, 180 * lights.KINDS.fire.radius);
  assert.equal(L.intensity, lights.KINDS.fire.intensity);
});
