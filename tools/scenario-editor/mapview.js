"use strict";
// Map view of the Scenario Editor: drawing, the tools, and what the pointer and keyboard do on the
// map. Edits go through MapOps (mapops.js) inside edit() or a live drag (beginLive/liveApply/endLive
// in editor.js), so every change undoes as one step. World y grows north; screen y grows down.

const cv = $("map"), ctx = cv.getContext("2d");
const H = () => S.scn.gridSize[1];
const sx = x => S.view.ox + x * S.view.s;
const sy = y => S.view.oy + (H() - y) * S.view.s;
const wx = px => (px - S.view.ox) / S.view.s;
const wy = py => H() - (py - S.view.oy) / S.view.s;

const TOOLS = [
  {id: "select", key: "v", label: "Select", icon: "⬚",
    hint: "Click to select (again for what's underneath; Shift adds). Drag a selected thing to move it, a selected region by its centre handle, or its edge to resize (Alt: only its own wall). Shift+drag selects everything wholly inside a box. Arrows nudge, R rotates objects."},
  {id: "region", key: "b", label: "Region", icon: "▭", hint: "Name it below, then drag a rectangle on the map."},
  {id: "object", key: "o", label: "Object", icon: "▣", hint: "Pick a type below, then click the map to place it (repeat for more). R turns it first."},
  {id: "npc", key: "n", label: "NPC", icon: "●", hint: "Name them below, then click the map. They start with a schedule of the region they stand in."},
  {id: "door", key: "d", label: "Door", icon: "⌧", hint: "Click a cell on a walled region's outer row or column to add or remove a door. A shared wall gets doors on both sides."},
  {id: "measure", key: "m", label: "Measure", icon: "⟷", hint: "Drag to measure. A selected hostile shows its 7-cell aggro and 14-cell give-up rings."},
];
Object.assign(S, {tool: "select", hover: null, hoverEdge: null, placeTpl: recall("editor.placeTpl") || "", placeRot: 0,
  measure: null, box: null, drawRect: null, clip: null, space: false, msg: ""});

function fit() {
  if (!S.scn) return;
  const r = cv.getBoundingClientRect(), [w, h] = S.scn.gridSize;
  S.view.s = Math.max(1, Math.min((r.width - 20) / w, (r.height - 20) / h));
  S.view.ox = (r.width - w * S.view.s) / 2; S.view.oy = (r.height - h * S.view.s) / 2;
}
function center(x, y, minScale = 14) {
  const r = cv.getBoundingClientRect();
  S.view.s = Math.max(S.view.s, minScale);
  S.view.ox = r.width / 2 - (x + .5) * S.view.s;
  S.view.oy = r.height / 2 - (H() - y - .5) * S.view.s;
  draw();
}

function sprite(tid) {
  const file = `${tid}-sprite.webp`;
  if (!S.media.has(`media/${tid}/${file}`)) return null;
  let img = S.sprites.get(tid);
  if (!img) {
    img = new Image(); img.onload = () => draw();
    img.src = `/media?${q()}&id=${encodeURIComponent(tid)}&file=${encodeURIComponent(file)}`;
    S.sprites.set(tid, img);
  }
  return img.complete && img.naturalWidth ? img : null;
}

const groundColor = g => g.groundColor || GROUND[g.groundTexture] || GROUND_BASE[g.ground] || "#8aa16f";
const wallColor = g => g.wallColor || WALL[g.wall] || WALL.wood;
const personColor = e => { const k = entKind(e); return S.layers[k]?.hide ? null : LAYERS.find(l => l.key === k).color; };
const selColor = () => getComputedStyle(document.documentElement).getPropertyValue("--sel").trim() || "#e0a100";

// ---------------------------------------------------------------- drawing
function drawObject(e, X, Y, w, h, s, alpha = 1) {
  const img = s >= 4 && sprite(e.templateId), t = objTpl(e.templateId) || {};
  ctx.globalAlpha = alpha;
  if (img) {
    const rot = e.rot || 0, cw = w * s, ch = h * s;
    ctx.save(); ctx.translate(X + cw / 2, Y + ch / 2); ctx.rotate(rot * Math.PI / 2);   // quarter turns, clockwise on screen
    const iw = rot % 2 ? ch : cw, ih = rot % 2 ? cw : ch;
    ctx.drawImage(img, -iw / 2, -ih / 2, iw, ih); ctx.restore();
  } else {
    ctx.fillStyle = (t.walkability ?? 0) <= 0 ? "rgba(70,55,40,.75)" : "rgba(120,100,70,.4)";
    ctx.fillRect(X + 1, Y + 1, w * s - 2, h * s - 2);
  }
  ctx.globalAlpha = 1;
}

function drawWalls(g, s) {
  const [x0, y0] = g.position, x1 = x0 + g.size[0] - 1, y1 = y0 + g.size[1] - 1;
  const door = new Set((g.openings || []).map(c => c[0] + "," + c[1]));
  ctx.strokeStyle = wallColor(g); ctx.lineWidth = Math.max(1.5, s * .2); ctx.lineCap = "square";
  ctx.beginPath();
  for (let x = x0; x <= x1; x++) {
    if (!door.has(x + "," + y0)) { ctx.moveTo(sx(x), sy(y0)); ctx.lineTo(sx(x + 1), sy(y0)); }
    if (!door.has(x + "," + y1)) { ctx.moveTo(sx(x), sy(y1 + 1)); ctx.lineTo(sx(x + 1), sy(y1 + 1)); }
  }
  for (let y = y0; y <= y1; y++) {
    if (!door.has(x0 + "," + y)) { ctx.moveTo(sx(x0), sy(y)); ctx.lineTo(sx(x0), sy(y + 1)); }
    if (!door.has(x1 + "," + y)) { ctx.moveTo(sx(x1 + 1), sy(y)); ctx.lineTo(sx(x1 + 1), sy(y + 1)); }
  }
  ctx.stroke();
  if (s >= 8) {
    ctx.fillStyle = "rgba(255,255,255,.35)";
    for (const [x, y] of g.openings || []) ctx.fillRect(sx(x) + s * .3, sy(y + 1) + s * .3, s * .4, s * .4);
  }
}

const gripAt = r => [sx(r.position[0] + r.size[0] / 2), sy(r.position[1] + r.size[1] / 2)];

function draw() {
  const dpr = window.devicePixelRatio || 1, R = cv.getBoundingClientRect();
  if (cv.width !== Math.round(R.width * dpr) || cv.height !== Math.round(R.height * dpr)) {
    cv.width = Math.round(R.width * dpr); cv.height = Math.round(R.height * dpr);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, R.width, R.height);
  if (!S.scn) { minimap.render(null); return; }
  const s = S.view.s, [gw, gh] = S.scn.gridSize, L = S.layers;
  ctx.fillStyle = groundColor(S.scn.defaultTile || {});
  ctx.fillRect(sx(0), sy(gh), gw * s, gh * s);

  const regs = [...regions()].sort((a, b) => area(b) - area(a));
  for (const g of regs) {
    if (L[regionLayer(g)].hide) continue;
    const X = sx(g.position[0]), Y = sy(g.position[1] + g.size[1]);
    ctx.fillStyle = groundColor(g); ctx.fillRect(X, Y, g.size[0] * s, g.size[1] * s);
    if (g.hostile) { ctx.fillStyle = "rgba(208,68,58,.16)"; ctx.fillRect(X, Y, g.size[0] * s, g.size[1] * s); }
  }
  if (s >= 6) {
    ctx.strokeStyle = "rgba(0,0,0,.08)"; ctx.lineWidth = 1; ctx.beginPath();
    const x0 = Math.max(0, Math.floor(wx(0))), x1 = Math.min(gw, Math.ceil(wx(R.width)));
    const y0 = Math.max(0, Math.floor(wy(R.height))), y1 = Math.min(gh, Math.ceil(wy(0)));
    for (let x = x0; x <= x1; x++) { ctx.moveTo(sx(x) + .5, sy(y0)); ctx.lineTo(sx(x) + .5, sy(y1)); }
    for (let y = y0; y <= y1; y++) { ctx.moveTo(sx(x0), sy(y) + .5); ctx.lineTo(sx(x1), sy(y) + .5); }
    ctx.stroke();
  }
  if (!L.objects.hide) for (const e of entities()) {
    if (e.type !== "object") continue;
    const [w, h] = entSize(e);
    drawObject(e, sx(e.pos[0]), sy(e.pos[1] + h), w, h, s);
  }
  if (!L.walled.hide) for (const g of regs) if (g.wall) drawWalls(g, s);
  for (const e of entities()) {
    const k = entKind(e);
    if (k === "objects" || L[k].hide) continue;
    ctx.beginPath(); ctx.arc(sx(e.pos[0] + .5), sy(e.pos[1] + .5), Math.max(2.5, s * .38), 0, Math.PI * 2);
    ctx.fillStyle = LAYERS.find(l => l.key === k).color; ctx.fill();
    ctx.lineWidth = 1.5; ctx.strokeStyle = "rgba(0,0,0,.55)"; ctx.stroke();
  }
  if (s >= 5) {
    const fs = Math.min(14, Math.max(10, s * .9)), used = [];
    ctx.font = `${fs}px system-ui, sans-serif`; ctx.textBaseline = "top";
    for (const g of [...regs].reverse()) {          // smallest first, so a room keeps the corner it shares with its building
      if (L[regionLayer(g)].hide || g.size[0] * s < 50) continue;
      const tx = sx(g.position[0]) + 4, w = ctx.measureText(g.name).width;
      let ty = sy(g.position[1] + g.size[1]) + 3;
      while (used.some(u => tx < u[0] + u[2] && u[0] < tx + w && Math.abs(u[1] - ty) < fs + 2)) ty += fs + 3;
      if (ty > sy(g.position[1]) - fs) continue;    // no room left inside the region
      used.push([tx, ty, w]);
      ctx.lineWidth = 3; ctx.strokeStyle = "rgba(0,0,0,.55)"; ctx.strokeText(g.name, tx, ty);
      ctx.fillStyle = "#fff"; ctx.fillText(g.name, tx, ty);
    }
  }
  drawSelection(s);
  drawToolOverlay(s);
  minimap.render({x0: wx(0), y0: wy(R.height), x1: wx(R.width), y1: wy(0)});
}

function drawSelection(s) {
  const col = selColor();
  ctx.strokeStyle = col; ctx.lineWidth = 3; ctx.setLineDash([6, 4]);
  for (const sel of S.sels) {
    if (sel.kind === "template") continue;
    const o = byId(sel.id);
    if (!o) continue;
    if (sel.kind === "region") ctx.strokeRect(sx(o.position[0]), sy(o.position[1] + o.size[1]), o.size[0] * s, o.size[1] * s);
    else { const [w, h] = o.type === "object" ? entSize(o) : [1, 1]; ctx.strokeRect(sx(o.pos[0]) - 2, sy(o.pos[1] + h) - 2, w * s + 4, h * s + 4); }
  }
  ctx.setLineDash([]);
  const p = primary(), o = p && byId(p.id);
  if (S.tool === "select" && p?.kind === "region" && o && S.sels.length === 1 && !S.layers[regionLayer(o)].lock) {
    const [gx, gy] = gripAt(o);                       // the move handle
    ctx.beginPath(); ctx.arc(gx, gy, 8, 0, Math.PI * 2); ctx.fillStyle = col; ctx.fill();
    ctx.lineWidth = 2; ctx.strokeStyle = "rgba(0,0,0,.6)"; ctx.stroke();
    ctx.fillStyle = "#000"; ctx.fillRect(gx - 4, gy - .75, 8, 1.5); ctx.fillRect(gx - .75, gy - 4, 1.5, 8);
    if (S.hoverEdge) {
      const r = MapOps.rect(o), X0 = sx(r[0]), X1 = sx(r[2] + 1), Y0 = sy(r[1]), Y1 = sy(r[3] + 1);
      const seg = {w: [X0, Y1, X0, Y0], e: [X1, Y1, X1, Y0], s: [X0, Y0, X1, Y0], n: [X0, Y1, X1, Y1]}[S.hoverEdge];
      ctx.lineWidth = 5; ctx.strokeStyle = col; ctx.beginPath(); ctx.moveTo(seg[0], seg[1]); ctx.lineTo(seg[2], seg[3]); ctx.stroke();
    }
  }
  // aggro rings around a selected hostile
  if (o && p.kind === "entity" && o.type === "npc" && (o.hostile || o.stance === "hostile")) {
    for (const [rad, dash] of [[7, []], [14, [8, 6]]]) {
      ctx.beginPath(); ctx.arc(sx(o.pos[0] + .5), sy(o.pos[1] + .5), rad * s, 0, Math.PI * 2);
      ctx.setLineDash(dash); ctx.lineWidth = 2; ctx.strokeStyle = "rgba(208,68,58,.85)"; ctx.stroke();
    }
    ctx.setLineDash([]);
  }
}

function drawToolOverlay(s) {
  const h = S.hover, col = selColor();
  if (S.box) {
    const [x0, y0, x1, y1] = normRect(S.box.a, S.box.b);
    ctx.fillStyle = "rgba(224,161,0,.12)"; ctx.fillRect(sx(x0), sy(y1 + 1), (x1 - x0 + 1) * s, (y1 - y0 + 1) * s);
    ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.strokeRect(sx(x0), sy(y1 + 1), (x1 - x0 + 1) * s, (y1 - y0 + 1) * s);
  }
  if (S.tool === "region" && (S.drawRect || h)) {
    const [x0, y0, x1, y1] = S.drawRect ? normRect(S.drawRect.a, S.drawRect.b) : [h[0], h[1], h[0], h[1]];
    ctx.fillStyle = "rgba(224,161,0,.18)"; ctx.fillRect(sx(x0), sy(y1 + 1), (x1 - x0 + 1) * s, (y1 - y0 + 1) * s);
    ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.strokeRect(sx(x0), sy(y1 + 1), (x1 - x0 + 1) * s, (y1 - y0 + 1) * s);
    if (S.drawRect) label2(`${x1 - x0 + 1} × ${y1 - y0 + 1}`, sx(x1 + 1) + 6, sy(y1 + 1));
  }
  if (S.tool === "object" && h) {
    const t = objTpl(S.placeTpl);
    if (t) {
      const size = S.placeRot % 2 ? [t.size[1], t.size[0]] : t.size.slice();
      const ghost = {templateId: t.id, rot: S.placeRot || undefined};
      drawObject(ghost, sx(h[0]), sy(h[1] + size[1]), size[0], size[1], s, .6);
      ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.strokeRect(sx(h[0]), sy(h[1] + size[1]), size[0] * s, size[1] * s);
    }
  }
  if (S.tool === "npc" && h) {
    ctx.beginPath(); ctx.arc(sx(h[0] + .5), sy(h[1] + .5), Math.max(3, s * .38), 0, Math.PI * 2);
    ctx.globalAlpha = .6; ctx.fillStyle = LAYERS.find(l => l.key === "npcs").color; ctx.fill(); ctx.globalAlpha = 1;
  }
  if (S.tool === "door" && h) {
    const w = doorRegionAt(h);
    ctx.strokeStyle = w ? col : "rgba(179,38,30,.8)"; ctx.lineWidth = 2;
    ctx.strokeRect(sx(h[0]) + 1, sy(h[1] + 1) + 1, s - 2, s - 2);
  }
  if (S.measure) {
    const {a, b} = S.measure, dx = b[0] - a[0], dy = b[1] - a[1];
    ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.moveTo(sx(a[0]), sy(a[1])); ctx.lineTo(sx(b[0]), sy(b[1])); ctx.stroke(); ctx.setLineDash([]);
    const cells = Math.max(Math.abs(Math.floor(b[0]) - Math.floor(a[0])), Math.abs(Math.floor(b[1]) - Math.floor(a[1])));
    label2(`${Math.hypot(dx, dy).toFixed(1)} cells (${cells} steps, ~${Math.round(Math.hypot(dx, dy) * 2)} m)`, sx(b[0]) + 8, sy(b[1]) - 8);
  }
}
function label2(text, x, y) {
  ctx.font = "12px system-ui, sans-serif"; ctx.textBaseline = "top";
  const w = ctx.measureText(text).width + 10;
  ctx.fillStyle = "rgba(0,0,0,.72)"; ctx.fillRect(x, y, w, 18);
  ctx.fillStyle = "#fff"; ctx.fillText(text, x + 5, y + 3);
}
const normRect = (a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];

// ---------------------------------------------------------------- hit testing
function stackAt(x, y) {
  const L = S.layers, out = [];
  for (const e of entities()) {
    if (e.type === "object" || e.pos[0] !== x || e.pos[1] !== y) continue;
    const k = entKind(e); if (!L[k].lock && !L[k].hide) out.push({kind: "entity", id: e.id});
  }
  if (!L.objects.lock && !L.objects.hide) for (const e of entities()) {
    if (e.type !== "object") continue;
    const [w, h] = entSize(e);
    if (x >= e.pos[0] && y >= e.pos[1] && x < e.pos[0] + w && y < e.pos[1] + h) out.push({kind: "entity", id: e.id});
  }
  regions().filter(r => inRect(r, x, y) && !L[regionLayer(r)].lock && !L[regionLayer(r)].hide)
    .sort((a, b) => area(a) - area(b)).forEach(r => out.push({kind: "region", id: r.id}));
  return out;
}
function selectedEntityAt(c) {
  for (const sel of S.sels) {
    const o = sel.kind === "entity" && byId(sel.id);
    if (!o || S.layers[entKind(o)].lock) continue;
    const [w, h] = o.type === "object" ? entSize(o) : [1, 1];
    if (c[0] >= o.pos[0] && c[1] >= o.pos[1] && c[0] < o.pos[0] + w && c[1] < o.pos[1] + h) return o;
  }
  return null;
}
function selectedRegion() {
  const p = primary(), o = p?.kind === "region" && S.sels.length === 1 && byId(p.id);
  return o && !S.layers[regionLayer(o)].lock ? o : null;
}
function edgeUnder(pt) {
  const r = selectedRegion();
  return r ? MapOps.edgeAt(r, pt[0], pt[1], 5 / S.view.s) : null;
}
function onGrip(px, py) {
  const r = selectedRegion();
  if (!r) return false;
  const [gx, gy] = gripAt(r);
  return Math.hypot(px - gx, py - gy) <= 11;
}
/** The walled region a door click at cell c is for: the selected one if c is on its edge, else the
 *  smallest unlocked walled region with c on its edge. */
function doorRegionAt(c) {
  if (S.layers.walled.lock || S.layers.walled.hide) return null;
  const p = primary(), sel = p?.kind === "region" && byId(p.id);
  if (sel?.wall && MapOps.onEdge(MapOps.rect(sel), c)) return sel;
  return regions().filter(r => r.wall && MapOps.onEdge(MapOps.rect(r), c)).sort((a, b) => area(a) - area(b))[0] || null;
}

// ---------------------------------------------------------------- editing helpers
/** Moves everything selected by (dx, dy): regions with their contents, then loose entities. */
function moveSelection(dx, dy) {
  const regs = S.sels.filter(t => t.kind === "region").map(t => byId(t.id)).filter(Boolean);
  const top = regs.filter(r => !regs.some(o => o !== r && MapOps.containsRect(MapOps.rect(o), MapOps.rect(r))));
  const covered = e => top.some(r => MapOps.containsRect(MapOps.rect(r), MapOps.rect(e)));
  const ents = S.sels.filter(t => t.kind === "entity").map(t => byId(t.id)).filter(e => e && !covered(e));
  // shorten the move so every region and entity stays on the map, then move them all by that
  const [gw, gh] = S.scn.gridSize;
  for (const o of [...top, ...ents]) {
    const r = MapOps.rect(o);
    dx = Math.max(-r[0], Math.min(gw - 1 - r[2], dx)); dy = Math.max(-r[1], Math.min(gh - 1 - r[3], dy));
  }
  for (const r of top) { const res = MapOps.moveRegion(S.scn, r, dx, dy, set); if (res.error) return res; }
  if (ents.length) MapOps.moveEntities(S.scn, ents, dx, dy, set);
  return {dx, dy};
}

function placeHere(c) {
  if (S.tool === "object") {
    const t = objTpl(S.placeTpl);
    if (!t) return toast("Pick an object type in the panel on the left first");
    let placed;
    edit(`Place ${t.name}`, () => {
      placed = MapOps.placeObject(S.scn, t, c[0], c[1], set);
      if (S.placeRot) {      // turn it, then put its footprint back where the ghost showed it
        MapOps.rotateObject(S.scn, placed, S.placeRot, set);
        set(placed, "pos", [Math.min(S.scn.gridSize[0] - placed.size[0], c[0]), Math.min(S.scn.gridSize[1] - placed.size[1], c[1])]);
      }
    });
    if (placed) { S.sels = [{kind: "entity", id: placed.id}]; inspect(); draw(); }
  } else if (S.tool === "npc") {
    let name = $("tName")?.value.trim();
    if (!name) name = prompt("Name for the new NPC?")?.trim();
    if (!name) return;
    let res;
    edit(`Add ${name}`, () => { res = MapOps.placeNpc(S.scn, {name, gender: $("tGender")?.value}, c[0], c[1], set); if (res.error) throw new Error(res.error); });
    if (res?.npc) { if ($("tName")) $("tName").value = ""; S.sels = [{kind: "entity", id: res.npc.id}]; inspect(); draw(); }
  } else if (S.tool === "door") {
    const r = doorRegionAt(c);
    if (!r) return toast("Click a cell on the outer row or column of a walled region");
    let res;
    edit(`Door at [${c}]`, () => { res = MapOps.toggleDoor(S.scn, r, c, set); if (res.error) throw new Error(res.error); });
    if (res && !res.error) S.msg = `${res.added ? "Added" : "Removed"} a door: ${res.regions.join(", ")}`;
  }
}

function drawRegionDone(a, b) {
  const name = $("tName")?.value.trim() || prompt("Name for the new region?")?.trim();
  if (!name) return;
  let res;
  edit(`Add region ${name}`, () => {
    res = MapOps.createRegion(S.scn, a, b, {name, wall: $("tWall")?.value || undefined, hostile: $("tHostile")?.checked}, set);
    if (res.error) throw new Error(res.error);
  });
  if (res?.region) { $("tName").value = ""; S.sels = [{kind: "region", id: res.region.id}]; inspect(); draw(); }
}

function deleteSelection() {
  if (!S.sels.length) return;
  const blocked = [], ids = [];
  for (const sel of S.sels) {
    const o = byId(sel.id);
    if (!o || sel.kind === "template") continue;
    if (o.id === S.scn.playerId) { blocked.push(`${o.name} is the player`); continue; }
    const refs = sel.kind === "region" ? usedBy(o.id) : [];
    if (refs.length) blocked.push(`${o.name} is used by ${refs.length} thing${refs.length === 1 ? "" : "s"} (see "Used by")`);
    else ids.push(o.id);
  }
  if (blocked.length) {
    toast(`Not deleted: ${blocked.join("; ")}. Change those first.`);
    if (S.sels.length === 1) inspect();
    return;
  }
  edit(ids.length === 1 ? `Delete ${byId(ids[0]).name}` : `Delete ${ids.length} things`, () => MapOps.remove(S.scn, ids, set));
  S.sels = []; inspect(); draw();
}

function rotateSelection(q) {
  const objs = S.sels.map(t => byId(t.id)).filter(o => o?.type === "object" && !S.layers.objects.lock);
  if (!objs.length) return;
  edit(objs.length === 1 ? `Turn ${objs[0].name}` : `Turn ${objs.length} objects`, () => objs.forEach(o => MapOps.rotateObject(S.scn, o, q, set)));
}

function copySelection() {
  const r = selectedRegion();
  if (r) { S.clip = {kind: "region", data: MapOps.copyRegion(S.scn, r)}; return toast(`Copied ${r.name} with its rooms and objects`); }
  const objs = S.sels.map(t => byId(t.id)).filter(o => o?.type === "object");
  if (objs.length) { S.clip = {kind: "objects", data: objs.map(o => JSON.parse(JSON.stringify(o)))}; return toast(`Copied ${objs.length} object${objs.length === 1 ? "" : "s"}`); }
  toast("Select a region or objects to copy");
}
function paste() {
  if (!S.clip) return toast("Nothing copied yet");
  const at = S.hover || [0, 0];
  if (S.clip.kind === "region") {
    let res;
    edit("Paste region", () => { res = MapOps.pasteRegion(S.scn, S.clip.data, at[0], at[1], set); if (res.error) throw new Error(res.error); });
    if (res?.region) { S.sels = [{kind: "region", id: res.region.id}]; inspect(); draw(); }
  } else {
    const base = S.clip.data[0].pos, made = [];
    edit(`Paste ${S.clip.data.length} object${S.clip.data.length === 1 ? "" : "s"}`, () => {
      for (const o of S.clip.data) {
        const t = objTpl(o.templateId);
        if (!t) continue;
        const e = MapOps.placeObject(S.scn, t, at[0] + o.pos[0] - base[0], at[1] + o.pos[1] - base[1], set);
        if (o.rot) { MapOps.rotateObject(S.scn, e, o.rot, set); set(e, "pos", [at[0] + o.pos[0] - base[0], at[1] + o.pos[1] - base[1]]); }
        made.push(e);
      }
    });
    S.sels = made.map(e => ({kind: "entity", id: e.id})); inspect(); draw();
  }
}

// ---------------------------------------------------------------- pointer
let drag = null;
function cellOf(e) { const r = cv.getBoundingClientRect(); return [Math.floor(wx(e.clientX - r.left)), Math.floor(wy(e.clientY - r.top))]; }
function ptOf(e) { const r = cv.getBoundingClientRect(); return [wx(e.clientX - r.left), wy(e.clientY - r.top)]; }
const onMap = c => c[0] >= 0 && c[1] >= 0 && c[0] < S.scn.gridSize[0] && c[1] < H();
const clampCell = c => [Math.max(0, Math.min(S.scn.gridSize[0] - 1, c[0])), Math.max(0, Math.min(H() - 1, c[1]))];

cv.addEventListener("contextmenu", e => e.preventDefault());
cv.addEventListener("pointerdown", e => {
  if (!S.scn) return;
  cv.setPointerCapture(e.pointerId);
  const c = cellOf(e), pt = ptOf(e), r = cv.getBoundingClientRect();
  const base = {x: e.clientX, y: e.clientY, ox: S.view.ox, oy: S.view.oy, start: c, moved: false, shift: e.shiftKey};
  if (e.button === 2) { setTool("select"); S.drawRect = S.measure = null; draw(); return; }
  if (e.button === 1 || S.space) { drag = {...base, mode: "pan"}; return; }
  if (e.button !== 0) return;
  if (S.tool === "select") {
    const edge = edgeUnder(pt);
    if (edge && S.editable) {
      const reg = selectedRegion();
      if (beginLive(`Resize ${reg.name}`)) drag = {...base, mode: "resize", region: reg, edge, follow: !e.altKey};
      return;
    }
    const grab = onGrip(e.clientX - r.left, e.clientY - r.top) || (!e.shiftKey && selectedEntityAt(c));
    if (grab && S.editable) {
      if (beginLive(S.sels.length === 1 ? `Move ${byId(S.sels[0].id).name}` : `Move ${S.sels.length} things`)) drag = {...base, mode: "move"};
      return;
    }
    drag = {...base, mode: e.shiftKey ? "box" : "pan"};
    return;
  }
  if (S.tool === "region") { drag = {...base, mode: "draw"}; S.drawRect = {a: clampCell(c), b: clampCell(c)}; draw(); return; }
  if (S.tool === "measure") { drag = {...base, mode: "measure"}; S.measure = {a: pt, b: pt}; draw(); return; }
  drag = {...base, mode: "pan"};          // object, npc, door: a click acts, a drag pans
});

cv.addEventListener("pointermove", e => {
  if (!S.scn) return;
  const c = cellOf(e), pt = ptOf(e), r = cv.getBoundingClientRect();
  const was = S.hover;
  S.hover = onMap(c) ? c : null;
  $("coords").textContent = (S.hover ? `${c[0]}, ${c[1]}` : "") + (S.msg ? `  ·  ${S.msg}` : "");
  if (!drag) {
    const edge = S.tool === "select" ? edgeUnder(pt) : null;
    const grip = S.tool === "select" && onGrip(e.clientX - r.left, e.clientY - r.top);
    cv.style.cursor = edge ? (edge === "e" || edge === "w" ? "ew-resize" : "ns-resize")
      : grip || (S.tool === "select" && selectedEntityAt(c)) ? "move" : S.tool === "select" ? "default" : "crosshair";
    if (edge !== S.hoverEdge || S.tool !== "select" || String(was) !== String(S.hover)) { S.hoverEdge = edge; draw(); }
    return;
  }
  const dxp = e.clientX - drag.x, dyp = e.clientY - drag.y;
  if (!drag.moved && Math.hypot(dxp, dyp) < 4) return;
  drag.moved = true;
  if (drag.mode === "pan") { cv.classList.add("panning"); S.view.ox = drag.ox + dxp; S.view.oy = drag.oy + dyp; draw(); return; }
  if (drag.mode === "move") {
    const dx = c[0] - drag.start[0], dy = c[1] - drag.start[1];
    const res = liveApply(() => moveSelection(dx, dy));
    S.msg = res?.error ? res.error : `moved ${dx}, ${dy}`;
  } else if (drag.mode === "resize") {
    const ed = drag.edge, to = ed === "e" ? Math.round(pt[0]) - 1 : ed === "w" ? Math.round(pt[0]) : ed === "n" ? Math.round(pt[1]) - 1 : Math.round(pt[1]);
    const res = liveApply(() => MapOps.resizeRegion(S.scn, drag.region, ed, to, set, drag.follow && !e.altKey));
    S.msg = res?.error ? res.error : `${drag.region.size[0]} × ${drag.region.size[1]}`;
  } else if (drag.mode === "box") S.box = {a: clampCell(drag.start), b: clampCell(c)};
  else if (drag.mode === "draw") S.drawRect.b = clampCell(c);
  else if (drag.mode === "measure") S.measure.b = pt;
  $("coords").textContent = `${c[0]}, ${c[1]}` + (S.msg ? `  ·  ${S.msg}` : "");
  draw();
});

function endDrag(e, cancelled) {
  if (!drag) return;
  const d = drag; drag = null; cv.classList.remove("panning");
  const c = cellOf(e);
  if (d.mode === "move" || d.mode === "resize") {
    S.msg = "";
    if (cancelled || !d.moved) cancelLive(); else endLive();
    if (!cancelled && !d.moved && onMap(c)) clickSelect(c, e.shiftKey);   // a press without a drag is a click
    return;
  }
  if (cancelled) { S.box = S.drawRect = null; draw(); return; }
  if (d.mode === "box") {
    const b = S.box && normRect(S.box.a, S.box.b); S.box = null;
    if (b) boxSelect(b);
    draw(); return;
  }
  if (d.mode === "draw") {
    const rr = S.drawRect; S.drawRect = null; draw();
    if (rr && (rr.a[0] !== rr.b[0] || rr.a[1] !== rr.b[1])) drawRegionDone(rr.a, rr.b);
    else toast("Drag a rectangle to draw a region");
    return;
  }
  if (d.mode === "measure" || d.moved || !onMap(c)) return;
  if (S.tool === "select") return clickSelect(c, e.shiftKey);
  placeHere(c);
}
cv.addEventListener("pointerup", e => endDrag(e, false));
cv.addEventListener("pointercancel", e => endDrag(e, true));
cv.addEventListener("pointerleave", () => { if (!drag && S.hover) { S.hover = null; draw(); } });

function clickSelect(c, add) {
  const stack = stackAt(c[0], c[1]);
  if (!stack.length) { if (!add) select(null); return; }
  if (add) {                                     // Shift+click adds or removes the topmost thing
    const t = stack[0], i = S.sels.findIndex(s => s.id === t.id);
    if (i >= 0) S.sels.splice(i, 1); else S.sels.push(t);
    draw(); inspect(); return;
  }
  const p = primary(), i = p ? stack.findIndex(t => t.id === p.id) : -1;
  select(stack[(i + 1) % stack.length]);         // click again for what's underneath
}

function boxSelect(b) {
  const L = S.layers, picked = [];
  const within = r => r[0] >= b[0] && r[1] >= b[1] && r[2] <= b[2] && r[3] <= b[3];
  for (const e of entities()) if (!L[entKind(e)].lock && !L[entKind(e)].hide && within(MapOps.rect(e.type === "object" ? {pos: e.pos, size: entSize(e)} : e))) picked.push({kind: "entity", id: e.id});
  for (const r of regions()) if (!L[regionLayer(r)].lock && !L[regionLayer(r)].hide && within(MapOps.rect(r))) picked.push({kind: "region", id: r.id});
  S.sels = picked;
  inspect();
  toast(picked.length ? `${picked.length} selected` : "Nothing wholly inside the box");
}

cv.addEventListener("wheel", e => {
  if (!S.scn) return;
  e.preventDefault();
  const r = cv.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
  const x = wx(px), y = wy(py), f = Math.exp(-e.deltaY * .0015);
  S.view.s = Math.min(80, Math.max(1, S.view.s * f));
  S.view.ox = px - x * S.view.s; S.view.oy = py - (H() - y) * S.view.s; draw();
}, {passive: false});
new ResizeObserver(() => draw()).observe(cv);

// ---------------------------------------------------------------- tools panel
function setTool(id) {
  if (!TOOLS.some(t => t.id === id)) return;
  S.tool = id; S.drawRect = null; if (id !== "measure") S.measure = null;
  document.querySelectorAll("#tools button").forEach(b => b.classList.toggle("on", b.dataset.tool === id));
  renderToolOpts(); draw();
}
function buildTools() {
  $("tools").innerHTML = TOOLS.map(t => `<button data-tool="${t.id}" title="${esc(t.label)} (${t.key.toUpperCase()})"><span aria-hidden="true">${t.icon}</span> ${esc(t.label)}</button>`).join("");
  $("tools").onclick = e => { const b = e.target.closest("button"); if (b) setTool(b.dataset.tool); };
  setTool("select");
}
function renderToolOpts() {
  const t = TOOLS.find(x => x.id === S.tool), box = $("toolOpts");
  let html = `<p class="note">${esc(t.hint)}</p>`;
  if (S.tool === "region") html += `
    <label class="field"><span>Name</span><input type="text" id="tName" placeholder="e.g. Blacksmith"></label>
    <div class="row2"><label class="field"><span>Walls</span><select id="tWall"><option value="">none (open area)</option>
      <option>wood</option><option>brick</option><option>stone</option><option>steel</option></select></label>
    <label class="check"><input type="checkbox" id="tHostile"> Hostile</label></div>`;
  if (S.tool === "npc") html += `
    <label class="field"><span>Name</span><input type="text" id="tName" placeholder="e.g. Mara the baker"></label>
    <label class="field"><span>Gender</span><select id="tGender"><option value="female">female</option><option value="male">male</option></select></label>`;
  if (S.tool === "object") {
    html += `<input type="search" id="tFilter" placeholder="Filter types" style="width:100%;margin-bottom:6px">
      <select id="tTpl" size="9" style="width:100%"></select>
      <p class="note" id="tTplInfo"></p>`;
  }
  box.innerHTML = html;
  if (S.tool === "object") {
    const fill = () => {
      const f = $("tFilter").value.trim().toLowerCase();
      const list = (S.scn?.objectTemplates || []).filter(t => !f || t.name.toLowerCase().includes(f)).sort((a, b) => a.name.localeCompare(b.name));
      $("tTpl").innerHTML = list.map(t => `<option value="${esc(t.id)}" ${t.id === S.placeTpl ? "selected" : ""}>${esc(t.name)} (${t.size.join("×")})</option>`).join("");
      info();
    };
    const info = () => {
      const t = objTpl(S.placeTpl);
      $("tTplInfo").textContent = t ? `${t.size.join(" × ")} · ${(t.walkability ?? 0) <= 0 ? "blocks movement" : (t.walkability >= 1 ? "walk over" : "slows")}${t.forSleep ? " · bed" : ""}${S.placeRot ? ` · turned ${S.placeRot * 90}°` : ""}` : "No type picked.";
    };
    $("tFilter").oninput = fill;
    $("tTpl").onchange = () => { S.placeTpl = $("tTpl").value; S.placeRot = 0; remember("editor.placeTpl", S.placeTpl); info(); draw(); };
    renderToolOpts.info = info;
    fill();
  }
}

// ---------------------------------------------------------------- keyboard
document.addEventListener("keydown", e => {
  if (S.tab !== "map" || !S.scn) return;
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName);
  if (typing) return;
  const mod = e.ctrlKey || e.metaKey, k = e.key.toLowerCase();
  if (e.key === " ") { S.space = true; cv.style.cursor = "grab"; e.preventDefault(); return; }
  if (mod && k === "c") { e.preventDefault(); copySelection(); return; }
  if (mod && k === "v") { e.preventDefault(); paste(); return; }
  if (mod) return;
  if (e.key === "Escape") {
    if (drag) { cancelLive(); drag = null; S.box = S.drawRect = null; draw(); return; }
    if (S.tool !== "select") return setTool("select");
    return select(null);
  }
  if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); return deleteSelection(); }
  const arrows = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1]};
  if (arrows[e.key] && S.sels.length) {
    e.preventDefault();
    const n = e.shiftKey ? 5 : 1, [dx, dy] = arrows[e.key];
    edit(`Nudge ${S.sels.length === 1 ? byId(S.sels[0].id)?.name : S.sels.length + " things"}`, () => {
      const res = moveSelection(dx * n, dy * n); if (res.error) throw new Error(res.error);
    });
    return;
  }
  if (k === "r") {
    if (S.tool === "object") { S.placeRot = (S.placeRot + (e.shiftKey ? 3 : 1)) % 4; renderToolOpts.info?.(); draw(); }
    else rotateSelection(e.shiftKey ? 3 : 1);
    return;
  }
  if (k === "f") { const p = primary(); if (p) jump(p.id); else { fit(); draw(); } return; }
  const tool = TOOLS.find(t => t.key === k);
  if (tool) setTool(tool.id);
});
document.addEventListener("keyup", e => { if (e.key === " ") { S.space = false; cv.style.cursor = ""; } });
window.addEventListener("blur", () => { S.space = false; });

// ---------------------------------------------------------------- minimap
const minimap = new Minimap($("minimap"), {onJump: (x, y) => center(x - .5, y - .5, 0)});
function minimapScenario() {
  minimap.setScenario(S.scn, {ground: groundColor, wall: wallColor, person: personColor});
}

buildTools();
