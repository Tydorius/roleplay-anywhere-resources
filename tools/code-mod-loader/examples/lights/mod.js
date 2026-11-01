// lights: light sources with a kind. A candle flickers small and warm, a hearth flickers big and
// throws embers, an electric bulb holds steady and white, and an arcane crystal pulses blue.
//
// The game already lights the map (Phaser's Light2D with its own soft shaders). Every object or
// carried item whose template has `light` > 0 gets a point light, and lamps cast wall shadows.
// But every lamp is the same orange (0xFFC078), with one radius (the lampReach setting), and
// none of them move. This mod gives each light a kind, a colour, a size and a motion.
//
// No bundle patch. Each frame the game sets every lamp's intensity and radius, then draws the
// lamps' wall shadows (drawPointShadows). The mod wraps that method on the live scene, so its
// changes land in between, and the shadows flicker along with the light.
//
// Scenario data (`arpgMods.lights`, optional; `false` turns the mod off for that scenario):
//   { auto: true,         // classify unlisted light sources by name and description
//     particles: true,    // embers and motes
//     occlusion: true,    // walls block lamp light on objects and characters (see occlude)
//     templates: { "<template id or exact name>": "fire" | {kind, color, radius, intensity,
//                  flicker, particles} } }
(() => {
  const arpg = globalThis.__arpg;
  arpg.registerMod('lights');

  // radius and intensity multiply the game's own values. motion: flame (layered flicker),
  // pulse (slow sine), steady, or stutter (steady with rare dropouts). amp: how far it swings.
  const KINDS = {
    candle:   { color: 0xffb45a, radius: 0.6,  intensity: 1.0,  motion: 'flame',  amp: 0.16, speed: 9,   particles: null },
    torch:    { color: 0xff9a3c, radius: 1.0,  intensity: 1.05, motion: 'flame',  amp: 0.24, speed: 7,   particles: 'embers' },
    fire:     { color: 0xff8030, radius: 1.3,  intensity: 1.1,  motion: 'flame',  amp: 0.28, speed: 5,   particles: 'fire' },
    ember:    { color: 0xff6a22, radius: 0.75, intensity: 0.9,  motion: 'pulse',  amp: 0.22, speed: 1.1, particles: null },
    lantern:  { color: 0xffc173, radius: 1.0,  intensity: 1.0,  motion: 'flame',  amp: 0.07, speed: 5,   particles: null },
    electric: { color: 0xfff1dc, radius: 1.15, intensity: 1.15, motion: 'steady', amp: 0,    speed: 0,   particles: null },
    neon:     { color: 0xff4fd8, radius: 0.9,  intensity: 1.1,  motion: 'stutter', amp: 0.8, speed: 8,   particles: null },
    screen:   { color: 0x9cc8ff, radius: 0.55, intensity: 0.9,  motion: 'pulse',  amp: 0.05, speed: 2.3, particles: null },
    magic:    { color: 0x8fb4ff, radius: 1.0,  intensity: 1.05, motion: 'pulse',  amp: 0.25, speed: 1.4, particles: 'motes' },
    plain:    { color: null,     radius: 1.0,  intensity: 1.0,  motion: 'steady', amp: 0,    speed: 0,   particles: null },
  };

  // Words that point at a kind. Name hits weigh 2, description hits 1, any weak word 0.5, so
  // "Lamppost … glowing warm bulb" is electric while "Lamppost … glowing glass" stays a lantern.
  const WORDS = {
    fire:     ['hearth', 'fireplace', 'campfire', 'bonfire', 'brazier', 'oven', 'forge', 'furnace',
               'kiln', 'fire pit', 'firepit', 'pyre', 'stove', 'flames'],
    torch:    ['torch', 'sconce'],
    candle:   ['candle', 'candelabra', 'candlestick', 'wick', 'taper'],
    ember:    ['ember', 'embers', 'coal', 'charcoal'],
    lantern:  ['lantern', 'oil lamp', 'gas lamp', 'lamplight'],
    electric: ['bulb', 'electric', 'flashlight', 'led', 'fluorescent', 'streetlight', 'spotlight',
               'floodlight', 'headlight', 'battery'],
    screen:   ['monitor', 'monitors', 'screen', 'workstation', 'computer', 'television', 'tv', 'terminal',
               'hologram', 'display'],
    magic:    ['arcane', 'magic', 'magical', 'mana', 'rune', 'runes', 'ethereal', 'spectral', 'enchanted',
               'bioluminescent', 'ghostly', 'moonstone', 'crystal', 'wisp', 'luminous'],
  };
  const WEAK = { lantern: ['lamp', 'lamppost'], magic: ['glowing', 'glow', 'pulsing'], fire: ['fire', 'flame'] };
  const ORDER = ['fire', 'torch', 'candle', 'ember', 'lantern', 'electric', 'screen', 'magic'];

  // A colour word counts only next to a light word ("violet flames", "blue light", "glowing blue
  // crystal", "neon green moss"), so "black candle" and "white background" don't recolour.
  const COLOURS = {
    red: 0xff4a3a, crimson: 0xff3048, orange: 0xff8a30, amber: 0xffb040, gold: 0xffcc55, golden: 0xffcc55,
    yellow: 0xffe066, warm: 0xffd29a, green: 0x6dff8a, emerald: 0x40e080, teal: 0x40e0d0, cyan: 0x5ff0ff,
    blue: 0x6fa0ff, azure: 0x7fb8ff, violet: 0xb070ff, purple: 0xa05cff, pink: 0xff70c8, magenta: 0xff50e0,
    silver: 0xdfe6ff, pale: 0xe8eeff, cold: 0xcfe0ff, icy: 0xb8e4ff,
  };
  const LIGHT_NOUNS = 'glow|glows|glowing|flame|flames|fire|light|lights|ember|embers|radiance|aura|bulb|sheen|hue|luminescence';
  const COLOUR_RE = new RegExp(
    `\\b(?:(${Object.keys(COLOURS).join('|')})\\s+(?:[a-z-]+\\s+)?(?:${LIGHT_NOUNS})\\b|` +
    `(?:glowing|neon|luminous|shimmering)[\\s-]+(${Object.keys(COLOURS).join('|')})\\b)`);

  const has = (text, word) => new RegExp(`\\b${word.replace(/ /g, '\\s+')}\\b`).test(text);

  // → {kind, color} for a template ({name, description, physicalDescription}), or null.
  function classify(template) {
    if (!template) return null;
    const name = String(template.name ?? '').toLowerCase();
    const desc = `${template.physicalDescription ?? ''} ${template.description ?? ''}`.toLowerCase();
    const score = {};
    for (const kind of ORDER) {
      let s = 0;
      for (const w of WORDS[kind] ?? []) s += (has(name, w) ? 2 : 0) + (has(desc, w) ? 1 : 0);
      if ((WEAK[kind] ?? []).some(w => has(name, w) || has(desc, w))) s += 0.5;
      score[kind] = s;
    }
    if (has(name, 'neon')) score.neon = 3; // in a description "neon" is just a colour word
    let kind = 'plain';
    let best = 0;
    for (const k of [...ORDER, 'neon']) if ((score[k] ?? 0) > best) { best = score[k]; kind = k; }
    const m = `${name} ${desc}`.match(COLOUR_RE);
    const color = m ? COLOURS[m[1] ?? m[2]] : null;
    return { kind, color };
  }

  const parseColor = c => (typeof c === 'number' ? c : typeof c === 'string' && /^#?[0-9a-f]{6}$/i.test(c) ? parseInt(c.replace('#', ''), 16) : null);

  // The scenario's settings, with defaults. null = the mod is off for this world.
  function settingsOf(world) {
    const raw = world?.arpgMods?.lights;
    if (raw === false) return null;
    const s = raw && typeof raw === 'object' ? raw : {};
    return { auto: s.auto !== false, particles: s.particles !== false, occlusion: s.occlusion !== false,
      templates: s.templates ?? {} };
  }

  // The full look for one light source template: the kind's preset, then the classifier's colour,
  // then anything the scenario sets.
  function profileFor(template, settings) {
    if (!template) return null;
    let entry = settings.templates[template.id] ?? settings.templates[template.name];
    if (typeof entry === 'string') entry = { kind: entry };
    const auto = !entry && settings.auto ? classify(template) : null;
    if (!entry && !auto) return null;
    const kind = KINDS[entry?.kind] ? entry.kind : auto?.kind ?? 'plain';
    const p = { kind, ...KINDS[kind] };
    if (auto?.color != null) p.color = auto.color;
    if (entry) {
      const c = parseColor(entry.color);
      if (c != null) p.color = c;
      for (const k of ['radius', 'intensity']) if (typeof entry[k] === 'number') p[k] = entry[k];
      if (typeof entry.flicker === 'number') p.amp = entry.flicker;
      if (entry.particles !== undefined) p.particles = entry.particles || null;
    }
    if (!settings.particles) p.particles = null;
    return p;
  }

  // The template that makes an entity glow: its own (objects), or its brightest equipped or
  // carried item (as the game sums them).
  function sourceTemplate(entity) {
    let best = entity?.objectTemplate?.light > 0 ? entity.objectTemplate : null;
    const consider = t => { if (t?.light > 0 && (!best || t.light > best.light)) best = t; };
    for (const it of Object.values(entity?.equipment ?? {})) consider(it?.template);
    for (const it of entity?.inventory ?? []) consider(it?.template);
    return best;
  }

  // A stable 0..1 number per light, so two candles side by side don't flicker in step.
  function seedOf(id) {
    let h = 2166136261;
    for (const ch of String(id)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
    return (h >>> 0) / 4294967296;
  }
  const hash01 = n => { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };

  // → {i, r}: multipliers for intensity and radius at time t (seconds).
  function motion(p, t, seed) {
    const ph = seed * 6.2832;
    switch (p.motion) {
      case 'flame': {
        const w = p.speed;
        const n = 0.55 * Math.sin(w * t + ph) + 0.3 * Math.sin(2.71 * w * t + ph * 2.3) +
          0.15 * Math.sin(6.13 * w * t + ph * 4.1);
        return { i: 1 + p.amp * n, r: 1 + p.amp * 0.35 * n };
      }
      case 'pulse': {
        const n = Math.sin(p.speed * t + ph);
        return { i: 1 + p.amp * n, r: 1 + p.amp * 0.25 * n };
      }
      case 'stutter': {
        const slot = Math.floor(t * p.speed);
        return { i: hash01(slot + seed * 1000) < 0.035 ? 1 - p.amp : 1, r: 1 };
      }
      default:
        return { i: 1, r: 1 };
    }
  }

  // --- Particles ------------------------------------------------------------------------------

  const DOT = 'arpg-lights-dot';

  function ensureDot(scene) {
    if (scene.textures.exists(DOT)) return;
    const c = scene.textures.createCanvas(DOT, 16, 16);
    const ctx = c.getContext();
    const g = ctx.createRadialGradient(8, 8, 0, 8, 8, 8);
    g.addColorStop(0, 'rgba(255,255,255,1)');
    g.addColorStop(0.4, 'rgba(255,255,255,0.6)');
    g.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 16, 16);
    c.refresh();
  }

  const shade = (rgb, k) => {
    const ch = s => Math.max(0, Math.min(255, Math.round(((rgb >> s) & 255) * k)));
    return (ch(16) << 16) | (ch(8) << 8) | ch(0);
  };

  function emitterConfig(style, color) {
    const add = 'ADD';
    if (style === 'fire') return {
      lifespan: { min: 600, max: 1300 }, speedY: { min: -38, max: -14 }, speedX: { min: -8, max: 8 },
      x: { min: -10, max: 10 }, scale: { start: 0.38, end: 0 }, alpha: { start: 0.95, end: 0 },
      tint: [0xffe08a, color, shade(color, 0.7)], blendMode: add, frequency: 70, quantity: 1,
    };
    if (style === 'embers') return {
      lifespan: { min: 450, max: 900 }, speedY: { min: -30, max: -10 }, speedX: { min: -6, max: 6 },
      x: { min: -3, max: 3 }, scale: { start: 0.28, end: 0 }, alpha: { start: 0.9, end: 0 },
      tint: [0xffd27a, color], blendMode: add, frequency: 160, quantity: 1,
    };
    if (style === 'motes') return {
      lifespan: { min: 1400, max: 2400 }, speed: { min: 3, max: 12 }, angle: { min: 0, max: 360 },
      x: { min: -12, max: 12 }, y: { min: -12, max: 12 }, scale: { start: 0.3, end: 0 },
      alpha: { start: 0.85, end: 0 }, tint: [color, 0xffffff], blendMode: add, frequency: 260, quantity: 1,
    };
    return null;
  }

  // --- The per-frame pass ---------------------------------------------------------------------

  const RESOLVE_MS = 1000; // re-read who carries what about once a second
  const VIEW_MARGIN = 200;
  const states = new Map(); // entity id → state (one scene at a time)
  let enabled = true;
  let lastResolve = -Infinity;
  let frames = 0;

  function restore(st) {
    const L = st.light;
    if (st.baseI !== undefined && L.intensity === st.outI) L.setIntensity(st.baseI);
    if (st.baseR !== undefined && L.radius === st.outR) L.setRadius(st.baseR);
    if (st.origColor) L.color.set(st.origColor[0], st.origColor[1], st.origColor[2]);
    st.emitter?.destroy();
  }

  function clear() {
    for (const st of states.values()) restore(st);
    for (const [sprite, t] of tinted) untint(sprite, t);
    states.clear();
    lastResolve = -Infinity;
  }

  // scene: the game's WorldScene (entityLights: id → {light, gx, gy}); nowMs: a clock.
  function applyFrame(scene, nowMs) {
    const lights = scene.entityLights;
    const settings = enabled ? settingsOf(scene.world) : null;
    if (!lights || !settings) return void (states.size && clear());
    frames++;

    // The game removes a light when its source dies or stops glowing.
    for (const [id, st] of states) {
      if (lights.get(id)?.light !== st.light) {
        st.emitter?.destroy();
        states.delete(id);
      }
    }

    let byId = null;
    if (nowMs - lastResolve >= RESOLVE_MS) {
      lastResolve = nowMs;
      byId = new Map((scene.world?.entities ?? []).map(e => [e.id, e]));
    }

    const t = nowMs / 1000;
    const cam = scene.cameras?.main?.worldView;
    for (const [id, rec] of lights) {
      const L = rec.light;
      let st = states.get(id);
      if (!st) {
        st = { light: L, seed: seedOf(id), profile: undefined, srcId: undefined };
        states.set(id, st);
        byId ??= new Map((scene.world?.entities ?? []).map(e => [e.id, e]));
      }
      if (byId) {
        const entity = byId.get(id);
        const src = sourceTemplate(entity);
        if (src?.id !== st.srcId || st.profile === undefined) {
          st.srcId = src?.id;
          st.profile = profileFor(src, settings);
          st.emitter?.destroy();
          st.emitter = null;
          if (st.origColor) L.color.set(st.origColor[0], st.origColor[1], st.origColor[2]);
        }
        st.entity = entity;
      }
      const p = st.profile;
      if (!p) continue;

      // The game sets intensity and radius each time it syncs the entity. A value that isn't
      // the one written last frame is a fresh base from the game; never compound on our own.
      if (L.intensity !== st.outI) st.baseI = L.intensity;
      if (L.radius !== st.outR) st.baseR = L.radius;
      const m = motion(p, t, st.seed);
      L.setIntensity(st.baseI * p.intensity * m.i);
      L.setRadius(st.baseR * p.radius * m.r);
      st.outI = L.intensity;
      st.outR = L.radius;
      if (p.color != null) {
        st.origColor ??= [L.color.r, L.color.g, L.color.b];
        L.setColor(p.color);
      }

      if (p.particles && scene.add?.particles && scene.textures) {
        if (!st.emitter) {
          const cfg = emitterConfig(p.particles, p.color ?? 0xffc078);
          if (cfg) {
            ensureDot(scene);
            st.emitter = scene.add.particles(L.x, L.y, DOT, cfg);
          }
        }
        if (st.emitter) {
          const lift = p.particles === 'motes' ? 0 : -6;
          st.emitter.setPosition(L.x, L.y + lift);
          const row = st.entity?.pos?.[1];
          if (row != null && scene.depthForY) st.emitter.setDepth(scene.depthForY(row) + 0.001);
          const inView = !cam || (L.x > cam.x - VIEW_MARGIN && L.x < cam.right + VIEW_MARGIN &&
            L.y > cam.y - VIEW_MARGIN && L.y < cam.bottom + VIEW_MARGIN);
          if (st.emitter.emitting !== inView) st.emitter.emitting = inView;
        }
      }
    }
    if (settings.occlusion) occlude(scene, cam);
  }

  // --- Walls stop lamp light on objects and characters ----------------------------------------
  //
  // The game's lamp shadows are a dark layer drawn under everything that stands. They shade the
  // floor behind a wall, but the light shader still lights any object or character in a lamp's
  // reach, wall or not: a bed in the next room glows from the hearth. Each frame, a sprite that a
  // wall hides from a lamp gets its tint scaled, per colour channel, by (the light it should get)
  // / (the light the shader gives it), which takes out just that lamp's share and colour.

  const LIGHT_HEIGHT = 90; // px: the game's default light height (lightHeightPx)
  const tinted = new Map(); // sprite → {base: the game's tint, out: ours}
  let losCache = new Map();
  let losWalls = null;

  const channels = c => [((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255];
  const packed = ([r, g, b]) => (Math.round(r * 255) << 16) | (Math.round(g * 255) << 8) | Math.round(b * 255);

  // How strongly a light reaches a point, as the shader works it out for a surface facing up.
  function reach(L, x, y) {
    const d2 = (L.x - x) ** 2 + (L.y - y) ** 2;
    const att = 1 - d2 / (L.radius * L.radius);
    return att <= 0 ? 0 : att * L.intensity * LIGHT_HEIGHT / Math.sqrt(d2 + LIGHT_HEIGHT * LIGHT_HEIGHT);
  }

  function untint(sprite, t) {
    if (sprite.tintTopLeft === t.out) sprite.setTint(t.base);
    tinted.delete(sprite);
  }

  function occlude(scene, cam) {
    const views = scene.views;
    const lamps = scene.entityLights;
    if (!views || !lamps || typeof scene.losBlocked !== 'function') return;
    const walls = scene.wallCasterSegments?.();
    if (walls !== losWalls) { losWalls = walls; losCache = new Map(); }

    const amb = scene.lights?.ambientColor;
    const base = amb ? [amb.r, amb.g, amb.b] : [0, 0, 0];
    const lampLights = new Set([...lamps.values()].map(r => r.light));
    const others = (scene.lights?.lights ?? []).filter(L => !lampLights.has(L)); // sun or moon
    const near = [...lamps.entries()].filter(([, r]) => !cam ||
      (r.light.x > cam.x - r.light.radius && r.light.x < cam.right + r.light.radius &&
       r.light.y > cam.y - r.light.radius && r.light.y < cam.bottom + r.light.radius));
    const seen = new Set();

    for (const view of views.values()) {
      const e = view.entity;
      const box = view.container;
      if (!e || !box || !near.length) continue;
      const x = box.x, y = box.y;
      if (cam && (x < cam.x - VIEW_MARGIN || x > cam.right + VIEW_MARGIN ||
        y < cam.y - VIEW_MARGIN || y > cam.bottom + VIEW_MARGIN)) continue;

      let total = null, blocked = null;
      for (const [id, rec] of near) {
        const k = reach(rec.light, x, y);
        if (k <= 0.002 || id === e.id) continue;
        const key = `${id}|${rec.gx},${rec.gy}|${x},${y}`;
        let hidden = losCache.get(key);
        if (hidden === undefined) losCache.set(key, (hidden = !!scene.losBlocked(rec.gx, rec.gy, x, y)));
        if (!hidden) continue;
        const c = rec.light.color;
        blocked ??= [0, 0, 0];
        blocked[0] += c.r * k; blocked[1] += c.g * k; blocked[2] += c.b * k;
      }
      if (blocked) {
        total = [...base];
        for (const L of [...others, ...near.map(([, r]) => r.light)]) {
          const k = reach(L, x, y);
          if (k > 0) { total[0] += L.color.r * k; total[1] += L.color.g * k; total[2] += L.color.b * k; }
        }
      }
      for (const sprite of [view.sprite, view.charSprite]) {
        if (!sprite?.setTint) continue;
        let t = tinted.get(sprite);
        if (!blocked) { if (t) untint(sprite, t); continue; }
        // The game re-tints each sync; a tint that isn't ours is its new base.
        if (!t || sprite.tintTopLeft !== t.out) t = { base: sprite.tintTopLeft };
        const keep = total.map((v, i) => (v > 1e-6 ? Math.max(0, v - blocked[i]) / v : 1));
        sprite.setTint(packed(channels(t.base).map((v, i) => v * keep[i])));
        t.out = sprite.tintTopLeft;
        tinted.set(sprite, t);
        seen.add(sprite);
      }
    }
    for (const [sprite, t] of tinted) if (!seen.has(sprite)) untint(sprite, t);
  }

  // --- Attach to the live scene ---------------------------------------------------------------

  const now = () => (globalThis.performance?.now ? globalThis.performance.now() : Date.now());
  let attached = null;

  function attach(scene) {
    if (scene.__arpgLights) return;
    scene.__arpgLights = true;
    const draw = scene.drawPointShadows;
    scene.drawPointShadows = function (...args) {
      try {
        applyFrame(this, now());
      } catch (e) {
        console.error('[arpg lights] frame failed', e);
      }
      return draw.apply(this, args);
    };
    scene.events?.once?.('shutdown', () => { states.clear(); lastResolve = -Infinity; });
  }

  if (typeof globalThis.setInterval === 'function') globalThis.setInterval(() => {
    const scene = globalThis.__vivScene;
    if (!scene || scene === attached || typeof scene.drawPointShadows !== 'function') return;
    attached = scene;
    states.clear();
    lastResolve = -Infinity;
    attach(scene);
  }, 500);

  arpg.lights = {
    KINDS,
    classify,
    profileFor: (template, world) => profileFor(template, settingsOf(world) ?? settingsOf({})),
    sourceTemplate,
    motion,
    applyFrame,
    attach,
    setEnabled(on) { enabled = !!on; if (!on) clear(); },
    // What each lit entity on the map became, for checking the classifier in game.
    report() {
      return [...states.entries()].map(([id, st]) => ({
        id, name: st.entity?.name, source: st.srcId, kind: st.profile?.kind ?? null,
        color: st.profile?.color != null ? `#${st.profile.color.toString(16).padStart(6, '0')}` : null,
        particles: !!st.emitter,
      }));
    },
    stats: () => ({ frames, lights: states.size }),
  };
})();
