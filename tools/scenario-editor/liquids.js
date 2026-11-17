"use strict";
// Liquids and natural shapes as Anywhere RPG 1.0 reads them, kept apart from the page so they can be tested
// with node. Nothing here touches the DOM. Coordinates: [0,0] is the bottom-left cell, y grows north, and a
// blob mask's row 0 is the region's lowest y (position[1]).
// The blob maths is the game's own Hhe(id, w, h), ported bit for bit; the golden test fixture beside this file
// was produced by running that code. scenario_checks.py ports the same functions for the map checks.

(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Liquids = factory();
})(typeof self !== "undefined" ? self : this, function () {

  const MAX_MEDIA = 8;       // the game's own media lists have at most 8 entries, and it adds no more
  const ORGANIC_MIN = 5;     // a blob is only drawn from 5 x 5 up
  const NEW_COLOR = "#3a6d8a";  // the medium the game appends for an unknown surface

  /** The two media every scenario without an `unbounded` key gets (deep water you can't cross, shallow water
   *  you wade through). Frozen: the game never edits the list in place, and neither do we. */
  const DEFAULT_MEDIA = Object.freeze([
    Object.freeze({name: "deep water", walk: "no", color: "#24506e", flows: true}),
    Object.freeze({name: "shallow water", walk: "slow", color: "#3f7f90", flows: true}),
  ]);

  /** "organic" as the import reads a region's `shape` (trimmed, any case; "natural" is the same word), or
   *  undefined when the game draws a rectangle. */
  function normShape(v) {
    if (typeof v !== "string") return undefined;
    v = v.trim().toLowerCase();
    return v === "organic" || v === "natural" ? "organic" : undefined;
  }

  /** The `surface` the import keeps: trimmed, lowercased, cut to 40 characters, or undefined (no surface). */
  function normSurface(v) {
    if (typeof v !== "string") return undefined;
    v = v.trim().toLowerCase().slice(0, 40);
    return v || undefined;
  }

  const size2 = r => Array.isArray(r && r.size) && r.size.length === 2 ? r.size : null;

  /** A region is drawn and treated as a blob: shape organic, no wall, no pocket, and at least 5 x 5. */
  function isOrganic(region) {
    const s = size2(region);
    return !!s && normShape(region.shape) === "organic" && !region.wall && region.pocket === undefined
      && Math.min(s[0], s[1]) >= ORGANIC_MIN;
  }

  /** A liquid region the game draws as a river: at least three times as long as it is wide, and at most 12
   *  cells wide. Everything else fills its rectangle (or blob) as a pool. */
  function isRiver(region) {
    const s = size2(region);
    if (!s) return false;
    const mn = Math.min(s[0], s[1]), mx = Math.max(s[0], s[1]);
    return mx >= 3 * mn && mn <= 12;
  }

  // ---------------------------------------------------------------- the game's blob (Hhe), bit for bit
  function rng(seed) {
    let t = seed >>> 0;
    return () => {
      t |= 0; t = t + 1831565813 | 0;
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

  /** The blob's centre cell forced on, then only the 1s the centre reaches across (4-connected) survive.
   *  Returns how many cells were reached. */
  function keepCentre(p, w, h) {
    const c = Math.floor(h / 2) * w + Math.floor(w / 2);
    p[c] = 1;
    const seen = new Uint8Array(w * h);
    const todo = [c];
    seen[c] = 1;
    let n = 0;
    while (todo.length) {
      const i = todo.pop();
      n++;
      const x = i % w, y = (i / w) | 0;
      for (const [ok, j] of [[x > 0, i - 1], [x < w - 1, i + 1], [y > 0, i - w], [y < h - 1, i + w]])
        if (ok && !seen[j] && p[j]) { seen[j] = 1; todo.push(j); }
    }
    for (let i = 0; i < p.length; i++) if (p[i] && !seen[i]) p[i] = 0;
    return n;
  }

  const FILL = .7, P = 3, U0 = .4;

  function blob(id, w, h) {
    const i = rng(hash(`organic:${id}`)),
      o = [2 + Math.floor(i() * 2), 4 + Math.floor(i() * 2), 7],   // base radius, in cells, of the 3 harmonics
      g = o.map(() => i() * Math.PI * 2),                          // each harmonic's phase
      r = [.5, .3, .2],                                            // each harmonic's weight
      m = u => o.reduce((c, f, l) => c + r[l] * Math.sin(f * u + g[l]), 0);  // the wobble along angle u
    let s = 1 / 0, a = -1 / 0;
    for (let u = 0; u < 360; u++) { const c = m(u / 360 * Math.PI * 2); s = Math.min(s, c); a = Math.max(a, c); }
    const p = new Uint8Array(w * h);
    for (let u = U0; ; u *= .8) {   // shrink until the blob is at least 70% filled, keeping its centre
      p.fill(0);
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
        const d = (x + .5) / w * 2 - 1, A = (y + .5) / h * 2 - 1,
          f = Math.pow(Math.pow(Math.abs(d), P) + Math.pow(Math.abs(A), P), 1 / P),
          v = (m(Math.atan2(A, d)) - s) / (a - s || 1);
        f <= 1 - u * v && (p[y * w + x] = 1);
      }
      if (keepCentre(p, w, h) >= FILL * w * h || u < .02) return p;
    }
  }

  const masks = new Map();
  /** The blob a region with `id` fills in a w x h rectangle: Uint8Array, 1 = inside, [y * w + x], row 0 the
   *  lowest. Cached by id|w|h (the same mask is handed out every time; don't write into it). */
  function blobMask(id, w, h) {
    const key = `${id}|${w}|${h}`;
    let p = masks.get(key);
    if (!p) masks.set(key, p = blob(String(id), w, h));
    return p;
  }

  // ---------------------------------------------------------------- cells and runs
  /** The region's cells as horizontal runs {x, y, w, h} in map coordinates: the blob's cells when organic
   *  (runs of h 1, one per stretch of set cells per row), else one run for the whole rectangle. */
  function cellRuns(region) {
    const [px, py] = region.position, s = size2(region) || [1, 1], w = s[0], h = s[1];
    if (!isOrganic(region)) return [{x: px, y: py, w, h}];
    const p = blobMask(region.id, w, h), out = [];
    for (let y = 0; y < h; y++) {
      let x = 0;
      while (x < w) {
        if (!p[y * w + x]) { x++; continue; }
        let x1 = x + 1;
        while (x1 < w && p[y * w + x1]) x1++;
        out.push({x: px + x, y: py + y, w: x1 - x, h: 1});
        x = x1;
      }
    }
    return out;
  }

  // ---------------------------------------------------------------- media and resolution
  /** {list, defaults}: the game's liquid list. `defaults` is true when the scenario has no `unbounded` (the
   *  two built-in waters). `list` is null when `unbounded` exists without a `profile.media` array: the game
   *  fails to load the scenario as soon as any region has a surface. */
  function mediaList(scn) {
    if (!scn || scn.unbounded == null) return {list: DEFAULT_MEDIA, defaults: true};
    const prof = scn.unbounded.profile;
    const media = prof && typeof prof === "object" ? prof.media : undefined;
    return {list: Array.isArray(media) ? media : null, defaults: false};
  }

  /** One step of the game's resolution against the working list `media` (which it may append to):
   *  {medium, added}, or null when the list is full and nothing matched. */
  function pick(media, surf, shortSide) {
    let m = media.find(e => e && e.name === surf);
    if (m) return {medium: m, added: false};
    const near = media.filter(e => typeof (e && e.name) === "string" && (e.name.includes(surf) || surf.includes(e.name)));
    if (near.length) {
      const want = shortSide <= 3 ? "slow" : "no";   // a narrow stream is waded, a wide one isn't
      m = near.find(e => e.walk === want) || near[0];
      return {medium: m, added: false};
    }
    if (media.length < MAX_MEDIA) {
      m = {name: surf, walk: "no", color: NEW_COLOR, flows: true};
      media.push(m);
      return {medium: m, added: true};
    }
    return null;
  }

  /** The surface a region's import keeps (unwalled, not a floor, non-empty), as a normalised string. */
  function keptSurface(r) {
    if (!r || r.wall || r.pocket !== undefined || !size2(r)) return undefined;
    return normSurface(r.surface);
  }

  /** {media, byRegion}: everything the game works out for the scenario's liquids, regions in order.
   *  `media` is the list after any additions (null when the scenario's list is broken). `byRegion` maps a
   *  region id to {medium, kind: "pool"|"river", added}, or to null when the surface is ignored; only
   *  regions with a surface the game keeps get an entry. */
  function resolveAll(scn) {
    const byRegion = new Map();
    const {list} = mediaList(scn);
    const regions = Array.isArray(scn && scn.regions) ? scn.regions : [];
    if (list === null) {   // broken list: the game fails as soon as a region has a surface; nothing resolves
      for (const r of regions) { const s = keptSurface(r); if (s) byRegion.set(r.id, null); }
      return {media: null, byRegion};
    }
    const media = list.slice();   // the game works on a copy: later regions see what earlier ones added
    for (const r of regions) {
      const surf = keptSurface(r);
      if (!surf) continue;
      const got = pick(media, surf, Math.min(r.size[0], r.size[1]));
      byRegion.set(r.id, got && {medium: got.medium, kind: isRiver(r) ? "river" : "pool", added: got.added});
    }
    return {media, byRegion};
  }

  /** How a medium is drawn: "molten" (glow, lava art), "deep" (walk no, deep water art), "shallow" (the
   *  animated shallow water art), or null when it has neither flows nor glow: flat colour, no shader. */
  function liquidKind(medium) {
    if (!medium || !(medium.flows || medium.glow)) return null;
    return medium.glow ? "molten" : medium.walk === "no" ? "deep" : "shallow";
  }

  /** A fresh wadeable water medium: "water", or "water 2", "water 3"… when the name is already taken. */
  function newMedium(existingNames) {
    const taken = new Set(existingNames);
    let name = "water", n = 1;
    while (taken.has(name)) name = `water ${++n}`;
    return {name, walk: "slow", color: "#3f7f90", flows: true};
  }

  /** Renames a medium of the scenario's own list and every region `surface` that names it (trimmed,
   *  any case), all through `set` so it is one undo step. Returns the regions renamed. The built-in
   *  waters are never written: a scenario without `unbounded` keeps them, so only surfaces move. */
  function renameMedium(scn, oldName, newName, set) {
    const from = normSurface(oldName), to = normSurface(newName);
    if (!from || !to || from === to) return [];
    const {list, defaults} = mediaList(scn);
    if (list && !defaults) for (const m of list)
      if (m && typeof m.name === "string" && normSurface(m.name) === from) set(m, "name", to);
    const out = [];
    for (const r of Array.isArray(scn && scn.regions) ? scn.regions : [])
      if (r && normSurface(r.surface) === from) { set(r, "surface", to); out.push(r); }
    return out;
  }

  // ---------------------------------------------------------------- the Water toggle
  /** The scenario's water media: every medium of its list whose name contains "water", whatever its
   *  walk. The built-in pair when the scenario has no list of its own; nothing when the list is
   *  broken (the game fails on any surface long before water matters). */
  function waterMedia(scn) {
    const {list, defaults} = mediaList(scn);
    if (list === null) return [];
    if (defaults) return DEFAULT_MEDIA.slice();
    return list.filter(m => m && typeof m.name === "string" && m.name.toLowerCase().includes("water"));
  }

  /** Whether a surface names one of the scenario's water media (the exact name, trimmed, any case):
   *  what the region inspector's Water checkbox is checked on. "lava" is not water. */
  function isWater(surface, scn) {
    const s = normSurface(surface);
    if (!s) return false;
    return waterMedia(scn).some(m => normSurface(m.name) === s);
  }

  /** What ticking Water writes on an open region {surface, shape}: the shallow water medium's name
   *  when the short side is 3 cells or less (waded), else the deep one's — the scenario's own names
   *  when it has its own water media, the built-in pair when it hasn't — and shape "organic" from
   *  5 x 5 up when the region carries no shape yet (shape undefined: leave the shape alone). */
  function waterFor(region, scn) {
    const water = waterMedia(scn);
    const s = size2(region) || [1, 1], short = Math.min(s[0], s[1]);
    const shallow = water.find(m => m.walk === "slow") || DEFAULT_MEDIA[1];
    const deep = water.find(m => m.walk === "no") || DEFAULT_MEDIA[0];
    return {
      surface: (short <= 3 ? shallow : deep).name,
      shape: !normShape(region.shape) && short >= ORGANIC_MIN ? "organic" : undefined,
    };
  }

  /** What unticking Water clears: the surface always, and the shape only when the toggle is the one
   *  that set it (the editor remembers that; `toggleSet`) and it is still the organic shape the
   *  toggle wrote. The result carries `shape` only when it must go — a shape set by hand survives. */
  function waterOff(region, toggleSet) {
    return toggleSet && normShape(region.shape) === "organic"
      ? {surface: undefined, shape: undefined} : {surface: undefined};
  }

  return {DEFAULT_MEDIA, MAX_MEDIA, ORGANIC_MIN, NEW_COLOR, normShape, normSurface, isOrganic, isRiver,
    blobMask, cellRuns, mediaList, resolveAll, liquidKind, newMedium, renameMedium,
    waterMedia, isWater, waterFor, waterOff};
});
