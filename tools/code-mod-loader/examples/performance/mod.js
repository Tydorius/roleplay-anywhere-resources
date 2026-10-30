// performance: two easy wins that grow with map size.
//
// 1. Movement-grid cache. The game builds its whole movement grid (map-sized arrays plus a
//    pass over every object) from scratch for each small question, such as "is this cell
//    walkable?", for every character, every frame: about 570 times a second on Thornbury.
//    Grids are never changed after they're built, so a recent one is reused. It's rebuilt
//    when it's older than 0.1 s, the walls change (regionsRev), or objects are added or
//    removed.
//
// 2. View culling. Phaser draws every object on the map every frame (6,700 on Thornbury)
//    although the screen shows a few percent of it. The game's camera is told to skip what
//    is well outside the view, re-checked every few frames and at once when the view jumps.
(() => {
  const arpg = globalThis.__arpg;
  arpg.registerMod('performance');

  // --- 1. Movement-grid cache -------------------------------------------------------------

  const NAV_MAX_AGE_MS = 100;
  const navCache = new WeakMap(); // world → {stamp, grids: Map(key → {at, grid})}
  const now = () => (globalThis.performance?.now ? globalThis.performance.now() : Date.now());

  // What the grid depends on besides time: the walls, their doorways and the set of objects.
  // Doorways count because the game's door-carving adds one to a region and immediately tests a
  // step through it; a grid from before the new door would wrongly say no.
  function stampOf(world) {
    let objects = 0, doors = 0;
    for (const e of world.entities ?? []) if (e.type === 'object' && !e.dead && !e.attachment) objects++;
    for (const r of world.regions ?? []) if (r.wall) doors += r.openings?.length ?? 0;
    return `${world.regionsRev ?? 0}:${objects}:${doors}`;
  }

  // The left-out entity only changes the grid when it's an object (characters never block).
  const keyOf = (entity, wallsOnly) => `${entity?.type === 'object' ? entity.id : ''}|${wallsOnly ? 1 : 0}`;

  let stats = { built: 0, reused: 0 };

  arpg.setNavCache({
    get(world, entity, wallsOnly) {
      let c = navCache.get(world);
      const t = now();
      // Checked on every request (a few hundred counts, far cheaper than a grid).
      if (c && stampOf(world) !== c.stamp) {
        navCache.delete(world); // walls, doorways or objects changed: start over
        c = null;
      }
      const hit = c?.grids.get(keyOf(entity, wallsOnly));
      if (hit && t - hit.at <= NAV_MAX_AGE_MS) {
        stats.reused++;
        return hit.grid;
      }
      return null;
    },
    put(world, entity, wallsOnly, grid) {
      let c = navCache.get(world);
      if (!c) navCache.set(world, (c = { stamp: stampOf(world), grids: new Map() }));
      c.grids.set(keyOf(entity, wallsOnly), { at: now(), grid });
      stats.built++;
    },
  });

  // Each grid also remembers its wall answers between cells (see the edge-memo patch). Path
  // searches ask the same ones over and over, and each answer loops over every walled region.
  arpg.memoEdges = true;

  // --- 2. View culling for the game's camera ----------------------------------------------

  const CULL_EVERY = 10; // frames
  const MARGIN = 160; // world pixels kept around the view (labels, shadows, walls sticking out)
  const STATIC_DEPTH = 10; // ground and lighting layers below this never move
  const ENTITY_KIDS = 12; // containers this small are one character or object and its label

  const staticBounds = new WeakMap();
  const scratch = { x: 0, y: 0, width: 0, height: 0 };
  const culledByUs = new WeakSet();

  function boundsOf(o, cache) {
    if (cache) {
      const b = staticBounds.get(o);
      if (b) return b;
    }
    let b = null;
    try {
      const g = o.getBounds ? o.getBounds(scratch) : null;
      if (g && (g.width || g.height)) b = { x: g.x, y: g.y, width: g.width, height: g.height };
    } catch {
      b = null;
    }
    if (b && cache) staticBounds.set(o, b);
    return b;
  }

  const overlaps = (b, v) => !(b.x > v.right || b.x + b.width < v.left || b.y > v.bottom || b.y + b.height < v.top);

  // Sets or clears this camera's "ignore" bit, but never touches one the game set itself.
  function show(o, id, visible) {
    const ours = culledByUs.has(o);
    if (!ours && (o.cameraFilter & id)) return;
    if (visible) {
      if (ours) {
        o.cameraFilter &= ~id;
        culledByUs.delete(o);
      }
    } else if (!ours) {
      o.cameraFilter |= id;
      culledByUs.add(o);
    }
  }

  function cullMain(scene, cam) {
    const wv = cam.worldView;
    const v = { left: wv.x - MARGIN, right: wv.right + MARGIN, top: wv.y - MARGIN, bottom: wv.bottom + MARGIN };
    const id = cam.id;
    for (const o of scene.children.list) {
      const kids = o.type === 'Container' ? o.list ?? [] : null;
      if (kids && kids.length <= ENTITY_KIDS && o.depth >= STATIC_DEPTH && (o.x || o.y)) {
        // A character or object (and its label): its position is enough.
        show(o, id, o.x >= v.left && o.x <= v.right && o.y >= v.top && o.y <= v.bottom);
      } else if (kids && o.depth >= STATIC_DEPTH && !o.x && !o.y) {
        // A wall run: a container at 0,0 whose pieces sit at their map positions. Static.
        const b = boundsOf(o, true);
        show(o, id, !b || overlaps(b, v));
      } else if (kids && o.depth < STATIC_DEPTH) {
        // A static ground layer: cull its tiles one by one.
        for (const k of kids) {
          const b = boundsOf(k, true);
          show(k, id, !b || overlaps(b, v));
        }
      } else {
        const b = boundsOf(o, o.depth < STATIC_DEPTH);
        show(o, id, !b || overlaps(b, v));
      }
    }
  }

  // Undo everything (when the scene is left, or for measuring).
  function uncull(scene, cam) {
    const id = cam.id;
    for (const o of scene.children.list) {
      if (culledByUs.has(o)) show(o, id, true);
      if (o.type === 'Container') for (const k of o.list ?? []) if (culledByUs.has(k)) show(k, id, true);
    }
  }

  let attached = null;
  let enabled = true;
  if (typeof globalThis.setInterval === 'function') globalThis.setInterval(() => {
    const scene = globalThis.__vivScene;
    if (!scene || scene === attached || !scene.events) return;
    attached = scene;
    let frame = 0;
    let last = null;
    scene.events.on('postupdate', () => {
      const cam = scene.cameras?.main;
      if (!cam || !enabled) return;
      const wv = cam.worldView;
      // Cull every few frames, and straight away when the view jumps or zooms.
      const jumped = !last || Math.abs(wv.centerX - last.x) > MARGIN / 2 || Math.abs(wv.centerY - last.y) > MARGIN / 2 || wv.width !== last.w;
      if (!jumped && frame++ % CULL_EVERY !== 0) return;
      cam.preRender();
      last = { x: cam.worldView.centerX, y: cam.worldView.centerY, w: cam.worldView.width };
      try {
        cullMain(scene, cam);
      } catch (e) {
        console.error('[arpg performance] culling failed', e);
      }
    });
  }, 500);

  arpg.performance = {
    stats: () => ({ ...stats }),
    resetStats: () => (stats = { built: 0, reused: 0 }),
    setCulling(on) {
      enabled = !!on;
      if (!on && attached?.cameras?.main) uncull(attached, attached.cameras.main);
    },
    cullMain,
    uncull,
  };
})();
