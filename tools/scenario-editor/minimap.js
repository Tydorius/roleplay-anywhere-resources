"use strict";
// Overview map for the Scenario Editor: the current level's plane (every plane side by side for the
// overview) drawn small, a frame for what the main view shows, and click or drag to move the main
// view there. The map image is cached and only redrawn after invalidate() or setPlane(), so panning
// the main view costs one image copy. World y grows north.

(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Minimap = factory();
})(typeof self !== "undefined" ? self : this, function () {

  class Minimap {
    /** canvas: the element to draw on. onJump(x, y) is called with the world point clicked or dragged over. */
    constructor(canvas, {onJump} = {}) {
      this.canvas = canvas; this.onJump = onJump || (() => {});
      this.scn = null; this.colors = null; this.cache = null; this.dirty = true; this.key = "";
      this.plane = null; this.down = false;
      this._down = e => {
        if (!this.scn || e.button !== 0) return;
        e.preventDefault();
        if (canvas.setPointerCapture) canvas.setPointerCapture(e.pointerId);
        this.down = true; this._jump(e);
      };
      this._move = e => { if (this.down) this._jump(e); };
      this._up = () => { this.down = false; };
      canvas.addEventListener("pointerdown", this._down);
      canvas.addEventListener("pointermove", this._move);
      canvas.addEventListener("pointerup", this._up);
      canvas.addEventListener("pointercancel", this._up);
    }

    setScenario(scn, colors) { this.scn = scn; this.colors = colors; this.dirty = true; }
    invalidate() { this.dirty = true; }

    /** Shows only this plane, an inclusive [x0, y0, x1, y1] of world cells; null for every plane
     *  side by side. The main view sets it to the level it is showing. */
    setPlane(plane) {
      const p = plane && plane.length === 4 ? plane : null;
      const same = !p === !this.plane && (!p || (p[0] === this.plane[0] && p[1] === this.plane[1]
        && p[2] === this.plane[2] && p[3] === this.plane[3]));
      if (same) return;
      this.plane = p; this.dirty = true;
    }

    /** The inclusive world rect shown: the set plane, or everything from 0,0. */
    _bounds() {
      if (this.plane) return this.plane;
      const [w, h] = Minimap.extent(this.scn);
      return [0, 0, w - 1, h - 1];
    }

    destroy() {
      const c = this.canvas;
      c.removeEventListener("pointerdown", this._down); c.removeEventListener("pointermove", this._move);
      c.removeEventListener("pointerup", this._up); c.removeEventListener("pointercancel", this._up);
    }

    _pixel(e) {
      const r = this.canvas.getBoundingClientRect ? this.canvas.getBoundingClientRect() : {left: 0, top: 0};
      return [e.clientX - r.left, e.clientY - r.top];
    }

    _jump(e) {
      const b = this._bounds(), gw = b[2] - b[0] + 1, gh = b[3] - b[1] + 1;
      const t = Minimap.fit(gw, gh, this.canvas.clientWidth, this.canvas.clientHeight, 4);
      t.ox -= b[0] * t.scale;
      const [px, py] = this._pixel(e);
      const [x, y] = Minimap.toWorld(t, b[3] + 1, px, py);
      this.onJump(Math.max(b[0], Math.min(b[2] + 1, x)), Math.max(b[1], Math.min(b[3] + 1, y)));
    }

    /** view: {x0, y0, x1, y1}, the world rectangle the main view shows (fractional cells, y up). */
    render(view) {
      const c = this.canvas, dpr = globalThis.devicePixelRatio || 1;
      const w = c.clientWidth, h = c.clientHeight;
      const bw = Math.round(w * dpr), bh = Math.round(h * dpr);
      if (c.width !== bw || c.height !== bh) { c.width = bw; c.height = bh; this.dirty = true; }
      const ctx = c.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      if (!this.scn) return;
      const b = this._bounds(), gw = b[2] - b[0] + 1, gh = b[3] - b[1] + 1;
      const t = Minimap.fit(gw, gh, w, h, 4); t.ox -= b[0] * t.scale;
      const key = `${bw}x${bh}`;
      if (this.dirty || !this.cache || this.key !== key) { this._build(t, w, h, dpr, b); this.key = key; this.dirty = false; }
      ctx.drawImage(this.cache, 0, 0, w, h);
      if (!view) return;
      const x0 = Math.max(b[0], view.x0), x1 = Math.min(b[2] + 1, view.x1), y0 = Math.max(b[1], view.y0), y1 = Math.min(b[3] + 1, view.y1);
      if (x1 <= x0 || y1 <= y0) return;
      const [ax, ay] = Minimap.toCanvas(t, b[3] + 1, x0, y1), [bx, by] = Minimap.toCanvas(t, b[3] + 1, x1, y0);
      ctx.fillStyle = "rgba(224, 161, 0, 0.15)"; ctx.fillRect(ax, ay, bx - ax, by - ay);
      ctx.strokeStyle = "#e0a100"; ctx.lineWidth = 1.5; ctx.strokeRect(ax, ay, bx - ax, by - ay);
    }

    _build(t, w, h, dpr, b) {
      const off = this.cache || document.createElement("canvas");
      off.width = Math.round(w * dpr); off.height = Math.round(h * dpr);
      const g = off.getContext("2d"), scn = this.scn, col = this.colors, [gw, gh] = scn.gridSize, s = t.scale;
      const top = b[3] + 1;                     // the world y at the drawing's top edge
      const onPlane = r => !this.plane || !(r[2] < b[0] || r[0] > b[2] || r[3] < b[1] || r[1] > b[3]);
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, w, h);
      const P = (x, y) => Minimap.toCanvas(t, top, x, y);
      let [x, y] = this.plane ? P(b[0], b[3] + 1) : P(0, gh);
      g.fillStyle = col.ground(scn.defaultTile || {});
      g.fillRect(x, y, (this.plane ? b[2] - b[0] + 1 : gw) * s, (this.plane ? b[3] - b[1] + 1 : gh) * s);
      const regs = [...(scn.regions || [])].sort((a, b) => b.size[0] * b.size[1] - a.size[0] * a.size[1]);
      for (const r of regs) {
        if (!onPlane([r.position[0], r.position[1], r.position[0] + r.size[0] - 1, r.position[1] + r.size[1] - 1])) continue;
        [x, y] = P(r.position[0], r.position[1] + r.size[1]);
        g.fillStyle = col.ground(r); g.fillRect(x, y, r.size[0] * s, r.size[1] * s);
      }
      g.lineWidth = 1;
      for (const r of regs) {
        if (!r.wall) continue;
        if (!onPlane([r.position[0], r.position[1], r.position[0] + r.size[0] - 1, r.position[1] + r.size[1] - 1])) continue;
        [x, y] = P(r.position[0], r.position[1] + r.size[1]);
        g.strokeStyle = col.wall(r); g.strokeRect(x + .5, y + .5, Math.max(0, r.size[0] * s - 1), Math.max(0, r.size[1] * s - 1));
      }
      for (const e of scn.entities || []) {
        if (e.type === "object") continue;
        const c = col.person(e);
        if (!c || !onPlane([e.pos[0], e.pos[1], e.pos[0], e.pos[1]])) continue;
        [x, y] = P(e.pos[0] + .5, e.pos[1] + .5);
        g.fillStyle = c; g.fillRect(x - 1, y - 1, 2, 2);
      }
      this.cache = off;
    }

    /** [width, height] from 0,0 that holds the map and any 1.0 floors (`pocket` regions) laid out beside it. */
    static extent(scn) {
      let [w, h] = scn.gridSize;
      for (const r of scn.regions || []) if (r.pocket && r.position && r.size) {
        w = Math.max(w, r.position[0] + r.size[0]); h = Math.max(h, r.position[1] + r.size[1]);
      }
      return [w, h];
    }

    /** The largest scale at which a gridW × gridH map fits the canvas less `pad` px a side, centred. */
    static fit(gridW, gridH, canvasW, canvasH, pad = 0) {
      const scale = Math.max(0, Math.min((canvasW - 2 * pad) / gridW, (canvasH - 2 * pad) / gridH));
      return {scale, ox: (canvasW - gridW * scale) / 2, oy: (canvasH - gridH * scale) / 2};
    }
    static toCanvas(t, gridH, x, y) { return [t.ox + x * t.scale, t.oy + (gridH - y) * t.scale]; }
    static toWorld(t, gridH, px, py) { return [(px - t.ox) / t.scale, gridH - (py - t.oy) / t.scale]; }
  }

  return Minimap;
});
