// smooth-edges: water and roads lose their cell-grid steps, and natural region edges fade
// along their true outline instead of the rectangle's.
//
// 1.0 paints each liquid or road cell as an opaque 12x12 square on a per-chunk canvas (the flow
// map beside it already carries the liquid kind two cells past every shore, so it is left
// untouched), then blurs the colour layer by 7 px and crops it into the tile. The water shader
// masks water by that canvas's alpha and draws shore foam where alpha passes 0.5, so the stepped
// shores come straight from the squares. Region ground fades the same way: one alpha per ground
// vertex, each the blurred mean of its touching cells, so a rounded organic shape gets a blocky
// rim and an edge cut by water a ragged one.
//
// No bundle patch. Two render hooks do the work:
// - onLiquidCanvas: read the chunk's cell grid once (a single getImageData, sampled at cell
//   centres, colours compared exactly so water, roads and different liquids each keep their own
//   edges), then marching-squares over every 2x2 block — a convex corner is cut diagonally, a
//   concave corner filled, a one-cell-wide end rounded (a half-cell circle). The blur drops to
//   5 px: with the steps gone, less smear is needed to look soft.
// - onGroundFade: when the region's mask is exactly 1.0's own organic blob (reproduced
//   bit-exactly here), the fade follows the blob's continuous outline; otherwise the region was
//   cut by water, and the cut fades by a signed distance to it (marching squares at 0.5, so
//   corners cut diagonally). Vertices the mask doesn't touch keep the game's own fade, so
//   rectangles keep their normal edge blend.
//
// Walkability never changes: the game decides it per cell, and this only redraws.
//
// Scenario data (`arpgMods['smooth-edges']`, optional; `false` turns the mod off for that
// scenario):
//   { shores: true,   // diagonal cuts and rounded ends on water and roads
//     ground: true,   // fades along the true outline
//     blur: 5 }       // the chunk blur radius, with the steps gone
(() => {
  const arpg = globalThis.__arpg;
  arpg.registerMod('smooth-edges');

  // --- 1.0's organic blob, bit-exactly ---------------------------------------------------------
  //
  // A natural-shaped region's mask is the game's Hhe(id, w, h): three sine harmonics on the
  // angle, squashed into the rectangle by a p-norm (p = 3), shrunk until the blob keeps the
  // centre connected over 70% of the rectangle. The golden masks in
  // tests/fixtures/organic-blobs-1.0.json pin this port; don't reshape the arithmetic.

  function rng(seed) {
    let t = seed >>> 0;
    return () => {
      t |= 0, t = t + 1831565813 | 0;
      let n = Math.imul(t ^ t >>> 15, 1 | t);
      n = n + Math.imul(n ^ n >>> 7, 61 | n) ^ n;
      return ((n ^ n >>> 14) >>> 0) / 4294967296;
    };
  }
  function hash(s) {
    let t = 0;
    for (let n = 0; n < s.length; n++) t = t * 31 + s.charCodeAt(n) | 0;
    return t >>> 0;
  }
  const FILL = .7, P = 3, U0 = .4;

  // Set the centre cell, flood-fill 4-connected from it over cells that are 1, clear every 1 the
  // fill never reached, and return how many cells it did reach.
  function keepCentre(p, w, h) {
    const start = (h >> 1) * w + (w >> 1);
    p[start] = 1;
    const seen = new Uint8Array(w * h);
    const stack = [start];
    seen[start] = 1;
    let reached = 0;
    while (stack.length) {
      const i = stack.pop();
      reached++;
      const x = i % w;
      if (x > 0 && p[i - 1] && !seen[i - 1]) { seen[i - 1] = 1; stack.push(i - 1); }
      if (x + 1 < w && p[i + 1] && !seen[i + 1]) { seen[i + 1] = 1; stack.push(i + 1); }
      if (i >= w && p[i - w] && !seen[i - w]) { seen[i - w] = 1; stack.push(i - w); }
      if (i + w < w * h && p[i + w] && !seen[i + w]) { seen[i + w] = 1; stack.push(i + w); }
    }
    for (let i = 0; i < w * h; i++) if (p[i] && !seen[i]) p[i] = 0;
    return reached;
  }

  // The blob, plus what its continuous shape needs: the final u and v(θ), the normalised
  // radius 1 - u*v(θ) of the outline at each angle.
  const shapeCache = new Map();
  function blobShape(id, w, h) {
    const key = `${id}|${w}|${h}`;
    let shape = shapeCache.get(key);
    if (shape) return shape;
    const i = rng(hash(`organic:${id}`)),
      o = [2 + Math.floor(i() * 2), 4 + Math.floor(i() * 2), 7],
      g = o.map(() => i() * Math.PI * 2), r = [.5, .3, .2],
      m = u => o.reduce((c, f, l) => c + r[l] * Math.sin(f * u + g[l]), 0);
    let lo = 1 / 0, hi = -1 / 0;
    for (let u = 0; u < 360; u++) {
      const c = m(u / 360 * Math.PI * 2);
      lo = Math.min(lo, c), hi = Math.max(hi, c);
    }
    const v = u => (m(u) - lo) / (hi - lo || 1);
    const cells = new Uint8Array(w * h);
    let u = U0;
    for (;; u *= .8) {
      cells.fill(0);
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
        const d = (x + .5) / w * 2 - 1, A = (y + .5) / h * 2 - 1,
          f = Math.pow(Math.pow(Math.abs(d), P) + Math.pow(Math.abs(A), P), 1 / P);
        f <= 1 - u * v(Math.atan2(A, d)) && (cells[y * w + x] = 1);
      }
      if (keepCentre(cells, w, h) >= FILL * w * h || u < .02) break;
    }
    shape = { cells, u, v };
    shapeCache.set(key, shape);
    return shape;
  }
  const blob = (id, w, h) => blobShape(String(id), w, h).cells;

  // --- The ground fade --------------------------------------------------------------------------
  //
  // One alpha per ground vertex: vertex (sx, my) at index my*(w+1)+sx is the point x = sx,
  // y = h - my in region cells, so vertex row 0 is the rectangle's top edge while row 0 of the
  // mask is the region's lowest y. The game's own fade (the `def` the hook receives) is the
  // mean of each vertex's four touching cells, then a 3x3 box blur over the vertex grid.

  function defaultFade(mask, w, h) {
    const vw = w + 1, vh = h + 1;
    const mean = new Float32Array(vw * vh);
    for (let my = 0; my <= h; my++) for (let sx = 0; sx <= w; sx++) {
      let sum = 0;
      for (const cy of [h - my - 1, h - my]) if (cy >= 0 && cy < h)
        for (const cx of [sx - 1, sx]) if (cx >= 0 && cx < w) sum += mask[cy * w + cx] ? 1 : 0;
      mean[my * vw + sx] = sum / 4;
    }
    const out = new Float32Array(vw * vh);
    for (let my = 0; my <= h; my++) for (let sx = 0; sx <= w; sx++) {
      let sum = 0;
      for (let j = my - 1; j <= my + 1; j++) if (j >= 0 && j <= h)
        for (let i = sx - 1; i <= sx + 1; i++) if (i >= 0 && i <= w) sum += mean[j * vw + i];
      out[my * vw + sx] = sum / 9;
    }
    return out;
  }

  const smoothstep = (e0, e1, x) => {
    const t = Math.max(0, Math.min(1, (x - e0) / (e1 - e0)));
    return t * t * (3 - 2 * t);
  };

  // Mark the vertices within 3 cells of a cell of value `want`. A reshaped fade only changes
  // these, so deep-inside and far-outside vertices keep the game's values.
  function nearCells(mask, w, h, want, flags) {
    for (let cy = 0; cy < h; cy++) for (let cx = 0; cx < w; cx++) {
      if ((mask[cy * w + cx] ? 1 : 0) !== want) continue;
      for (let my = h - cy - 4; my <= h - cy + 3; my++) {
        if (my < 0 || my > h) continue;
        for (let sx = cx - 3; sx <= cx + 4; sx++)
          if (sx >= 0 && sx <= w) flags[my * (w + 1) + sx] = 1;
      }
    }
    return flags;
  }

  const distSeg = (px, py, x1, y1, x2, y2) => {
    const dx = x2 - x1, dy = y2 - y1, l2 = dx * dx + dy * dy;
    const t = l2 ? Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / l2)) : 0;
    return Math.hypot(px - x1 - t * dx, py - y1 - t * dy);
  };

  // The contour segments through one block of four cell centres (a b / c d), as midpoints
  // relative to the block's corner: crossing on an edge wherever its two centres differ, a
  // corner cut where one differs from the other three, and a fixed pairing at the saddle.
  function blockSegments(a, b, c, d) {
    const cross = [a !== b, a !== c, b !== d, c !== d];
    const n = cross[0] + cross[1] + cross[2] + cross[3];
    if (!n) return [];
    const M = [[.5, 0], [0, .5], [1, .5], [.5, 1]]; // midpoints of ab, ac, bd, cd
    if (n === 2) {
      const k = cross.map((x, i) => x ? i : -1).filter(i => i >= 0);
      return [[M[k[0]], M[k[1]]]];
    }
    return a === d ? [[M[0], M[1]], [M[2], M[3]]] : [[M[0], M[2]], [M[1], M[3]]];
  }

  // The signed distance, in cells, from the vertex (sx, y) to the mask's boundary: marching
  // squares at 0.5 over the cell centres, brute-forced over the blocks within 3 cells.
  // Cells outside the rectangle count as empty, so the rectangle's own rim is a boundary too.
  // Positive inside, the sign from the four cells the vertex touches.
  function signedDistance(mask, w, h, sx, y) {
    const val = (cx, cy) => (cx < 0 || cy < 0 || cx >= w || cy >= h ? 0 : mask[cy * w + cx] ? 1 : 0);
    const px = sx - .5, py = y - .5; // where the vertex sits among the cell centres
    let best = Infinity;
    for (let r = Math.max(-1, y - 4); r <= Math.min(h - 1, y + 3); r++)
      for (let c = Math.max(-1, sx - 4); c <= Math.min(w - 1, sx + 3); c++) {
        for (const [[x1, y1], [x2, y2]] of blockSegments(val(c, r), val(c + 1, r), val(c, r + 1), val(c + 1, r + 1)))
          best = Math.min(best, distSeg(px, py, c + x1, r + y1, c + x2, r + y2));
      }
    let sum = 0;
    for (const cy of [y - 1, y]) for (const cx of [sx - 1, sx]) sum += val(cx, cy);
    return sum >= 2 ? best : -best;
  }

  // Any mask that isn't the plain organic shape: a region cut by water. The cut edge fades by
  // its signed distance; the rest of the fade is the game's own.
  function maskFade(mask, w, h, def) {
    const n = (w + 1) * (h + 1);
    const out = new Float32Array(def && def.length === n ? def : defaultFade(mask, w, h));
    const band = nearCells(mask, w, h, 0, new Uint8Array(n));
    for (let my = 0; my <= h; my++) for (let sx = 0; sx <= w; sx++) {
      if (!band[my * (w + 1) + sx]) continue;
      out[my * (w + 1) + sx] = smoothstep(-.75, .75, signedDistance(mask, w, h, sx, h - my));
    }
    return out;
  }

  // A plain organic region: the fade follows the blob's continuous outline. g is the gap to the
  // outline, (1 - u*v(θ)) - f in normalised units, scaled to cells by min(w, h)/2.
  function organicFade(id, w, h) {
    const { cells, u, v } = blobShape(String(id), w, h);
    const n = (w + 1) * (h + 1);
    const out = defaultFade(cells, w, h);
    const near0 = nearCells(cells, w, h, 0, new Uint8Array(n));
    const near1 = nearCells(cells, w, h, 1, new Uint8Array(n));
    const scale = Math.min(w, h) / 2;
    for (let my = 0; my <= h; my++) for (let sx = 0; sx <= w; sx++) {
      const k = my * (w + 1) + sx;
      if (!near0[k] || !near1[k]) continue; // only the band around the outline moves
      const X = sx / w * 2 - 1, Y = (h - my) / h * 2 - 1;
      const f = Math.pow(Math.pow(Math.abs(X), P) + Math.pow(Math.abs(Y), P), 1 / P);
      out[k] = smoothstep(-.75, .75, ((1 - u * v(Math.atan2(Y, X))) - f) * scale);
    }
    return out;
  }

  // --- The shores -------------------------------------------------------------------------------
  //
  // One pass over the cell grid, marching squares per cell corner over the 2x2 block around
  // it: both orthogonal neighbours of another colour makes a convex corner to cut, both of this
  // colour a concave corner to fill (only into an empty cell — never over another liquid), and
  // a cell with at most one same-colour neighbour is a one-cell-wide end, rounded with a
  // half-cell circle instead of cut. Every op stays inside one cell's 12x12 square.

  function shoreOps(grid) {
    const rows = grid.length, cols = rows ? grid[0].length : 0;
    const ops = [];
    if (!cols) return ops;
    const at = (c, r) => (c < 0 || r < 0 || c >= cols || r >= rows ? 0 : grid[r][c]);
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
      const color = grid[r][c];
      if (!color) continue;
      let arms = 0; // same-colour orthogonal neighbours: 0 or 1 means a one-cell-wide end
      if (at(c - 1, r) === color) arms++;
      if (at(c + 1, r) === color) arms++;
      if (at(c, r - 1) === color) arms++;
      if (at(c, r + 1) === color) arms++;
      for (const [ex, ey] of [[1, 1], [-1, 1], [1, -1], [-1, -1]]) {
        const x = c + (ex > 0 ? 1 : 0), y = r + (ey > 0 ? 1 : 0); // the corner, in cells
        const o1 = at(c + ex, r), o2 = at(c, r + ey), diagonal = at(c + ex, r + ey);
        if (o1 !== color && o2 !== color) {
          ops.push(arms <= 1 ? { op: 'round', x, y, dx: ex, dy: ey, color }
            : { op: 'cut', x, y, dx: -ex, dy: -ey });
        } else if (o1 === color && o2 === color && !diagonal) {
          ops.push({ op: 'fill', x, y, dx: ex, dy: ey, color }); // the empty diagonal's corner
        }
      }
    }
    return ops;
  }

  function paintShores(ctx, grid, cellPx) {
    const ops = shoreOps(grid);
    const half = cellPx / 2;
    const prev = ctx.globalCompositeOperation;
    const css = c => `rgb(${(c >> 16) & 255},${(c >> 8) & 255},${c & 255})`;
    const triangle = (x, y, dx, dy) => {
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x + dx * half, y);
      ctx.lineTo(x, y + dy * half);
      ctx.closePath();
      ctx.fill();
    };
    // Clears first, paints after: at a corner the block is either cut or filled, never both,
    // so the order only keeps one op from eating another's paint. A round op's (dx, dy) points
    // from the cell's centre to its corner, so the corner square and the quarter circle reach
    // back from the corner into the cell, against it.
    ctx.globalCompositeOperation = 'destination-out';
    for (const o of ops) if (o.op === 'cut') triangle(o.x * cellPx, o.y * cellPx, o.dx, o.dy);
    for (const o of ops) if (o.op === 'round') {
      const x = o.x * cellPx + Math.min(0, -o.dx * half), y = o.y * cellPx + Math.min(0, -o.dy * half);
      ctx.fillRect(x, y, half, half);
    }
    ctx.globalCompositeOperation = 'source-over';
    for (const o of ops) if (o.op === 'round') {
      const x = o.x * cellPx - o.dx * half, y = o.y * cellPx - o.dy * half; // the cell's centre
      const a0 = o.dx > 0 ? (o.dy > 0 ? 0 : -Math.PI / 2) : (o.dy > 0 ? Math.PI / 2 : Math.PI);
      ctx.fillStyle = css(o.color);
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.arc(x, y, half, a0, a0 + Math.PI / 2);
      ctx.closePath();
      ctx.fill();
    }
    for (const o of ops) if (o.op === 'fill') {
      ctx.fillStyle = css(o.color);
      triangle(o.x * cellPx, o.y * cellPx, o.dx, o.dy);
    }
    ctx.globalCompositeOperation = prev;
    return ops;
  }

  // --- Hooks, toggle, stats ---------------------------------------------------------------------

  const now = () => (typeof globalThis.performance?.now === 'function' ? globalThis.performance.now() : Date.now());

  const KEY = 'arpg.smooth-edges.enabled';
  let enabled = true;
  try { enabled = globalThis.localStorage?.getItem(KEY) !== '0'; } catch { }

  // The live scene's world carries the scenario's settings; away from a scene the defaults apply.
  function settingsOf() {
    let world = null;
    try { world = globalThis.__vivScene?.world; } catch { }
    const raw = world?.arpgMods?.['smooth-edges'];
    if (raw === false) return null;
    const s = raw && typeof raw === 'object' ? raw : {};
    const blur = typeof s.blur === 'number' && Number.isFinite(s.blur) && s.blur >= 0 ? s.blur : 5;
    return { shores: s.shores !== false, ground: s.ground !== false, blur };
  }

  let chunks = 0, chunkMs = 0, fades = 0, fadeMs = 0;

  arpg.onLiquidCanvas(payload => {
    if (!enabled) return;
    const settings = settingsOf();
    if (!settings?.shores) return;
    const mark = now();
    try {
      const { color, cellPx, margin, chunkCells } = payload;
      const n = chunkCells + margin * 2, side = n * cellPx;
      const img = color?.getImageData?.(0, 0, side, side);
      if (img?.data) {
        const half = cellPx >> 1;
        const grid = [];
        for (let r = 0; r < n; r++) {
          const row = new Array(n);
          for (let c = 0; c < n; c++) {
            const k = ((r * cellPx + half) * img.width + c * cellPx + half) * 4;
            row[c] = img.data[k + 3] === 0 ? 0 : (img.data[k] << 16) | (img.data[k + 1] << 8) | img.data[k + 2];
          }
          grid.push(row);
        }
        paintShores(color, grid, cellPx);
      }
    } finally {
      chunks++; chunkMs += now() - mark;
    }
    return settings.blur;
  });

  // The renderer refills the ground tile whenever the fade array changes identity, so each mask
  // gets its fade built once and the same array back every sync.
  const fadeCache = new WeakMap();

  arpg.onGroundFade((region, mask, def) => {
    if (!enabled) return;
    const settings = settingsOf();
    if (!settings?.ground) return;
    let out = fadeCache.get(mask);
    if (out) return out;
    const mark = now();
    try {
      const w = region?.size?.[0], h = region?.size?.[1];
      if (!Number.isInteger(w) || !Number.isInteger(h) || mask?.length !== w * h) return;
      let plain = typeof region.id === 'string' || typeof region.id === 'number';
      if (plain) {
        const cells = blob(String(region.id), w, h);
        for (let k = 0; k < mask.length; k++) if (mask[k] !== cells[k]) { plain = false; break; }
        out = plain ? organicFade(String(region.id), w, h) : maskFade(mask, w, h, def);
      } else {
        out = maskFade(mask, w, h, def);
      }
      if (def && out.length !== def.length) out = undefined; // the loader would reject it anyway
    } finally {
      fades++; fadeMs += now() - mark;
    }
    if (out) fadeCache.set(mask, out);
    return out;
  });

  // A toggle has to rebuild what is already on screen: the water tiles are the terrain layer's,
  // dropped and cleared the way the layer's own drop does and rebuilt by its sync; the ground
  // tiles by the scene's own syncGroundTiles. Every access is guarded.
  function rebuild() {
    let scene = null;
    try { scene = globalThis.__vivScene; } catch { }
    if (!scene) return;
    try {
      const layer = scene.terrainLayer, tiles = layer?.tiles;
      if (layer && tiles) {
        // drop(tile) destroys one tile's image and removes its texture; every tile goes, then
        // the map is emptied so sync builds them all again.
        for (const tile of [...tiles.values()]) {
          try { if (typeof layer.drop === 'function') layer.drop(tile); } catch { }
        }
        try { tiles.clear?.(); } catch { }
        try { if (typeof layer.sync === 'function') layer.sync(scene.world); } catch { }
      }
    } catch { }
    try { scene.syncGroundTiles?.(); } catch { }
  }

  function setEnabled(on) {
    enabled = !!on;
    try { globalThis.localStorage?.setItem(KEY, enabled ? '1' : '0'); } catch { }
    rebuild();
  }

  arpg.smoothEdges = {
    shoreOps,
    paintShores,
    organicFade,
    maskFade,
    defaultFade,
    blob,
    setEnabled,
    isEnabled: () => enabled,
    stats: () => ({
      chunks,
      msPerChunk: chunks ? chunkMs / chunks : 0,
      fades,
      msPerFade: fades ? fadeMs / fades : 0,
    }),
    resetStats() { chunks = chunkMs = fades = fadeMs = 0; },
  };
})();
