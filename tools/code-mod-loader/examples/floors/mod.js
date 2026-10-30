// floors: upper (or lower) storeys on a map that has only one flat grid.
//
// Build each extra storey as its own walled region somewhere free on the map, the same size
// as the room it sits above, and link the storeys with portals (stairs). Then declare it:
//
//   "arpgMods": {
//     "floors": [
//       {"name": "Weary Hound upstairs", "area": "Weary Hound Gallery",
//        "above": "Inn Common Room", "openings": ["Gallery well"]}
//     ]
//   }
//
// `area` and `above` line up corner to corner: the area's top-left cell is directly over the
// top-left cell of `above`. `openings` are regions inside the area with no floor (a stairwell,
// an atrium, a gallery over a hall). Nobody can walk into one. Leave it unwalled for an open
// drop; walls make a full-height parapet that hides much of the view.
//
// - People on different storeys notice each other only through an opening: one at or near
//   the railing, the other in the room below, under or near the opening.
// - The GM is told what is above what, and who can be seen through an opening.
// - On screen, each opening shows the room below it, blurred and darkened.
(() => {
  const arpg = globalThis.__arpg;
  arpg.registerMod('floors');

  // How the room below looks through an opening: a slight softening, as at a distance, and
  // a little darker. A floor can override either with "view": {"blur": 0.6, "brightness": 0.8}.
  const VIEW = { blur: 0.6, brightness: 0.8 };
  const RAIL_REACH = 2; // cells from an opening at which someone upstairs can look down
  const UNDER_REACH = 2; // cells around the spot under an opening that can be seen from above
  const CELL_PX = 32; // the game's cell size in pixels (gt)

  const cellOf = pos => [Math.round(pos[0]), Math.round(pos[1])];
  const same = (a, b) => String(a ?? '').trim().toLowerCase() === String(b ?? '').trim().toLowerCase();
  const inside = (c, r, pad = 0) =>
    c[0] >= r.position[0] - pad && c[1] >= r.position[1] - pad &&
    c[0] < r.position[0] + r.size[0] + pad && c[1] < r.position[1] + r.size[1] + pad;

  const warned = new Set();
  function warnOnce(msg) {
    if (warned.has(msg)) return;
    warned.add(msg);
    console.warn(`[arpg floors] ${msg}`);
  }

  // Resolved floors per world, keyed by the region revision so map edits are picked up.
  const cache = new WeakMap();
  function floorsOf(world) {
    const defs = world.arpgMods?.floors;
    if (!Array.isArray(defs) || !defs.length) return [];
    const rev = world.regionsRev ?? 0;
    const hit = cache.get(world);
    if (hit && hit.rev === rev && hit.defs === defs) return hit.floors;
    const region = name => world.regions?.find(r => same(r.name, name));
    const floors = [];
    defs.forEach((d, i) => {
      const name = d?.name || `Floor ${i + 1}`;
      const area = region(d?.area), below = region(d?.above);
      if (!area || !below) return warnOnce(`"${name}": ${!area ? `area "${d?.area}"` : `"${d?.above}"`} not found on this map`);
      const openings = (d.openings ?? []).map(n => region(n) ?? (warnOnce(`"${name}": opening "${n}" not found`), null)).filter(Boolean);
      // Cell offset from this storey down to the room below.
      const offset = [below.position[0] - area.position[0], below.position[1] - area.position[1]];
      const num = (v, dflt) => (typeof v === 'number' && v >= 0 ? v : dflt);
      const view = { blur: num(d.view?.blur, VIEW.blur), brightness: num(d.view?.brightness, VIEW.brightness) };
      floors.push({ name, area, below, openings, offset, view });
    });
    cache.set(world, { rev, defs, floors });
    return floors;
  }

  const floorAt = (floors, c) => floors.find(f => inside(c, f.area)) ?? null;
  const down = (f, c) => [c[0] + f.offset[0], c[1] + f.offset[1]];
  const up = (f, c) => [c[0] - f.offset[0], c[1] - f.offset[1]];

  // Whether someone upstairs on floor f and someone in the room below see each other.
  function throughOpening(f, upper, lower, range) {
    const uc = cellOf(upper.pos), lc = cellOf(lower.pos);
    const under = up(f, lc); // where the lower one would be, on the upstairs grid
    for (const o of f.openings) {
      if (!inside(uc, o, RAIL_REACH) || !inside(under, o, UNDER_REACH)) continue;
      if (Math.hypot(uc[0] - under[0], uc[1] - under[1]) <= range) return true;
    }
    return false;
  }

  // Which of the pair is upstairs on which floor, if they're on different storeys.
  function storeys(floors, a, b) {
    const ac = cellOf(a.pos), bc = cellOf(b.pos);
    const fa = floorAt(floors, ac), fb = floorAt(floors, bc);
    if (fa === fb) return null;
    if (fa && inside(bc, fa.below)) return { floor: fa, upper: a, lower: b };
    if (fb && inside(ac, fb.below)) return { floor: fb, upper: b, lower: a };
    return { floor: null };
  }

  arpg.onPerceive((world, a, b, range, _search, answer) => {
    const floors = floorsOf(world);
    if (!floors.length || !a?.pos || !b?.pos) return;
    const s = storeys(floors, a, b);
    if (!s) return; // same storey: leave it to the game and other mods
    return s.floor ? throughOpening(s.floor, s.upper, s.lower, range) : false;
  }, { order: 10 }); // after same-storey rules such as wall-aware perception

  // An opening has no floor: nobody walks into it, whether or not it has a wall round it.
  arpg.onNav((world, grid) => {
    for (const f of floorsOf(world)) {
      for (const o of f.openings) {
        const [x0, y0] = o.position, [w, h] = o.size;
        for (let x = Math.max(0, x0); x < Math.min(grid.w, x0 + w); x++) {
          for (let y = Math.max(0, y0); y < Math.min(grid.h, y0 + h); y++) grid.blocked[y * grid.w + x] = 1;
        }
      }
    }
  });

  // --- The GM ---------------------------------------------------------------------------

  const describe = e => {
    const what = [e.stance, e.activity?.summary].filter(Boolean).join(', ');
    return `${e.name}${what ? ` (${what})` : ''}`;
  };

  arpg.onPrompt((parts, world) => {
    const floors = floorsOf(world);
    if (!floors.length) return;
    if (arpg.promptBudgets) {
      for (const kind of ['floors', 'other_floor']) if (!(kind in arpg.promptBudgets)) arpg.promptBudgets[kind] = 1e6;
    }
    parts.sections.push({
      kind: 'floors',
      title: 'Storeys (the map is flat, so upper floors are drawn as separate areas; treat them as stacked):',
      content: floors.map(f => `- ${f.area.name} is the floor directly above ${f.below.name}` +
        (f.openings.length ? `; openings to look down through: ${f.openings.map(o => o.name).join(', ')}` : '')).join('\n'),
    });
    const player = world.player ?? world.entities?.find(e => e.type === 'player');
    if (!player) return;
    const seen = [];
    for (const e of world.entities ?? []) {
      if (e === player || e.dead || e.type !== 'npc') continue;
      const s = storeys(floors, player, e);
      if (!s?.floor || !throughOpening(s.floor, s.upper, s.lower, 14)) continue;
      const where = s.upper === player ? `below, in ${s.floor.below.name}` : `above, at ${s.floor.area.name}`;
      seen.push(`- ${describe(e)}: ${where}`);
    }
    if (seen.length) {
      parts.sections.push({
        kind: 'other_floor',
        title: 'Seen through an opening between floors (they can see and hear the player too, from a distance):',
        content: seen.slice(0, 20).join('\n'),
      });
    }
  });

  // --- The view below an opening --------------------------------------------------------

  // Each opening gets two extra cameras over it, drawn after the game's own:
  //   below: the room under the opening, softened and darkened;
  //   top:   this floor again, minus its ground and lighting layers, so walls, railings,
  //          people and labels at the opening's edge stay on top of the view below.
  // The game draws ground at depth 1 to 9 (region floors, then full-map lighting layers at
  // 8.9 to 9.5); walls, objects and characters start at 10.
  const ABOVE_FLOOR_DEPTH = 10;
  const views = new WeakMap(); // scene → Map(opening region → {below, top})

  // Phaser doesn't skip off-screen objects, so every extra camera would otherwise draw the
  // whole map (600+ containers, about as long as the game's own camera takes), dropping the
  // frame rate to a third. So each floor camera is told to ignore everything outside its small
  // view, re-checked every few frames as people move. `floorless` also drops the ground and
  // lighting layers (for the top camera).
  const CULL_EVERY = 10; // frames
  const CULL_MARGIN = 96; // world pixels around the view, so people walking in don't pop
  const bigBounds = new WeakMap(); // static layer → its bounds, measured once
  const scratch = { x: 0, y: 0, width: 0, height: 0 };

  function overlaps(o, v) {
    let b;
    // People and objects are small containers that move: their position is enough.
    if (o.type === 'Container' && (o.list?.length ?? 0) <= 12 && o.depth >= ABOVE_FLOOR_DEPTH) {
      return o.x >= v.left && o.x <= v.right && o.y >= v.top && o.y <= v.bottom;
    }
    b = bigBounds.get(o);
    if (!b) {
      try {
        const g = o.getBounds ? o.getBounds(scratch) : null;
        b = g ? { x: g.x, y: g.y, width: g.width, height: g.height } : null;
      } catch {
        b = null;
      }
      if (!b || (!b.width && !b.height)) return true; // can't tell: draw it
      bigBounds.set(o, b);
    }
    return !(b.x > v.right || b.x + b.width < v.left || b.y > v.bottom || b.y + b.height < v.top);
  }

  function cull(scene, cam, floorless) {
    const wv = cam.worldView;
    const v = { left: wv.x - CULL_MARGIN, right: wv.right + CULL_MARGIN, top: wv.y - CULL_MARGIN, bottom: wv.bottom + CULL_MARGIN };
    for (const o of scene.children.list) {
      const skip = (floorless && o.depth < ABOVE_FLOOR_DEPTH) || !overlaps(o, v);
      if (skip) o.cameraFilter |= cam.id;
      else o.cameraFilter &= ~cam.id;
    }
  }

  function syncViews(scene) {
    const world = scene.world;
    const main = scene.cameras?.main;
    if (!world || !main) return;
    let mine = views.get(scene);
    if (!mine) views.set(scene, (mine = new Map()));
    const live = new Set();
    for (const f of floorsOf(world)) {
      for (const o of f.openings) {
        live.add(o);
        let pair = mine.get(o);
        // The opening's rectangle in world pixels, then on screen (the game's y axis is flipped).
        const x0 = scene.sx(o.position[0]), x1 = scene.sx(o.position[0] + o.size[0]);
        const yTop = scene.sy(o.position[1]), yBottom = scene.sy(o.position[1] + o.size[1]);
        const wv = main.worldView;
        const sx0 = (x0 - wv.x) * main.zoom + main.x, sx1 = (x1 - wv.x) * main.zoom + main.x;
        const sy0 = (Math.min(yTop, yBottom) - wv.y) * main.zoom + main.y, sy1 = (Math.max(yTop, yBottom) - wv.y) * main.zoom + main.y;
        const cx0 = Math.max(main.x, Math.floor(sx0)), cx1 = Math.min(main.x + main.width, Math.ceil(sx1));
        const cy0 = Math.max(main.y, Math.floor(sy0)), cy1 = Math.min(main.y + main.height, Math.ceil(sy1));
        const onScreen = cx1 - cx0 > 1 && cy1 - cy0 > 1;
        if (!onScreen) {
          if (pair) {
            pair.below.setVisible(false);
            pair.top.setVisible(false);
          }
          continue;
        }
        if (!pair) {
          const below = scene.cameras.add(cx0, cy0, cx1 - cx0, cy1 - cy0, false, `arpg-below-${o.name}`);
          if (below.postFX) {
            // Phaser's blur: quality 0 (low), 1px offsets, a short 2-step pass.
            if (f.view.blur > 0) below.postFX.addBlur(0, 1, 1, f.view.blur, 0xffffff, 2);
            if (f.view.brightness !== 1) below.postFX.addColorMatrix().brightness(f.view.brightness);
          }
          const top = scene.cameras.add(cx0, cy0, cx1 - cx0, cy1 - cy0, false, `arpg-above-${o.name}`);
          top.transparent = true;
          pair = { below, top, frames: 0 };
          mine.set(o, pair);
        }
        const appearing = !pair.below.visible; // cull at once, not up to CULL_EVERY frames later
        // The world point at the centre of the visible part of the opening.
        const mid = main.getWorldPoint((cx0 + cx1) / 2, (cy0 + cy1) / 2);
        for (const cam of [pair.below, pair.top]) {
          cam.setVisible(true);
          cam.setViewport(cx0, cy0, cx1 - cx0, cy1 - cy0);
          cam.setZoom(main.zoom);
        }
        pair.top.centerOn(mid.x, mid.y);
        pair.below.centerOn(mid.x + f.offset[0] * CELL_PX, mid.y - f.offset[1] * CELL_PX); // a storey down
        if (appearing || pair.frames++ % CULL_EVERY === 0) {
          pair.below.preRender(); // bring worldView up to date before culling against it
          pair.top.preRender();
          cull(scene, pair.below, false);
          cull(scene, pair.top, true);
        }
      }
    }
    for (const [o, pair] of mine) {
      if (!live.has(o)) {
        scene.cameras.remove(pair.below);
        scene.cameras.remove(pair.top);
        mine.delete(o);
      }
    }
  }

  // The scene is replaced when a game loads; attach to whichever one is current.
  let attached = null;
  if (typeof globalThis.setInterval === 'function') globalThis.setInterval(() => {
    const scene = globalThis.__vivScene;
    if (!scene || scene === attached || !scene.events) return;
    attached = scene;
    scene.events.on('postupdate', () => {
      try {
        syncViews(scene);
      } catch (e) {
        warnOnce(`view below failed: ${e.message}`);
      }
    });
  }, 500);

  arpg.floors = { floorsOf, storeys, throughOpening };
})();
