"use strict";
// Scenario Editor page: state, saving, undo, references, the side panels and the inspector. The map
// itself is in mapview.js and the map edits in mapops.js. The scenario lives in S.scn and is changed
// only through edit() or a live drag, which record every change so it can be undone.
// Coordinates: [0,0] is the bottom-left cell and y grows north.

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const remember = (k, v) => { try { localStorage.setItem(k, v); } catch {} };
const recall = k => { try { return localStorage.getItem(k); } catch { return null; } };

const S = {
  sources: [], source: "", scn: null, media: new Set(), editable: false,
  undo: [], redo: [], tx: null, savedAt: 0, version: 0,
  sels: [],               // [{kind: "region" | "entity" | "template", id}]; the last one is shown in the inspector
  problems: [], checking: 0,
  view: {s: 8, ox: 0, oy: 0},
  layers: {}, sprites: new Map(), tab: "map",
};

const LAYERS = [
  {key: "areas", label: "Open areas", color: "#7aa36b"},
  {key: "walled", label: "Buildings and rooms", color: "#9b8566"},
  {key: "objects", label: "Objects", color: "#8a7d6b"},
  {key: "npcs", label: "NPCs", color: "#3d7fd6"},
  {key: "hostiles", label: "Hostiles", color: "#d0443a"},
  {key: "player", label: "Player", color: "#e0a100"},
];
const GROUND = {
  grass: "#7fa865", undergrowth: "#5f8a4b", dirt: "#a88b62", mud: "#7d6648", sand: "#d8c38f", gravel: "#a6a39a", rock: "#8c8a84",
  snow: "#e8eef0", cobblestone: "#9a958b", "flagstone-light": "#c8c2b4", "flagstone-dark": "#827c72", asphalt: "#5b5d60",
  concrete: "#a7a7a2", floorboards: "#b78a58", parquet: "#a5713f", "tile-marble": "#e3e0d8", "tile-slate": "#6d737a",
  "tile-ceramic": "#d9d4c8", "tile-ceramic-turquoise": "#6fb6b0", "carpet-red": "#9b3b36", "carpet-blue": "#3c5a8f",
  "carpet-green": "#41704a", "metal-deck": "#7c838a", "tech-panel": "#5d6b78", "bio-mold": "#6c7a3e", "bio-slime-purple": "#7a4f8f",
  "crystals-green": "#4fa37a", "crystals-purple": "#8661b3", "crystals-red": "#b3485a",
};
const GROUND_BASE = {grass: "#7fa865", dirt: "#a88b62", gravel: "#a6a39a", wood: "#b78a58", stone: "#9a958b"};
const WALL = {wood: "#5b3d22", brick: "#8a3b2a", stone: "#4c4a46", steel: "#3d4f5f"};

// ---------------------------------------------------------------- server
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  const ct = r.headers.get("Content-Type") || "";
  const body = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(body.error || body || r.statusText);
  return body;
}
function toast(msg) {
  const t = $("toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 3500);
}
const q = () => "source=" + encodeURIComponent(S.source);

async function loadSources(select) {
  S.sources = (await api("/api/scenarios")).sources;
  const sel = $("source");
  sel.innerHTML = S.sources.map(s => `<option value="${esc(s.id)}">${esc(s.label)}</option>`).join("")
    || `<option value="">No scenarios yet: open a zip</option>`;
  const want = select || S.source || recall("editor.source");
  if (want && S.sources.some(s => s.id === want)) sel.value = want;
  if (sel.value !== S.source) await openSource(sel.value);
}

async function openSource(id) {
  if (dirty() && !confirm("Discard unsaved changes?")) { $("source").value = S.source; return; }
  S.source = id; remember("editor.source", id);
  S.scn = null; S.sels = []; S.undo = []; S.redo = []; S.version = S.savedAt = 0; S.sprites.clear(); S.problems = [];
  if (!id) { minimapScenario(); render(); return; }
  const r = await api("/api/scenario?" + q());
  S.scn = r.scenario; S.media = new Set(r.media); S.editable = r.editable;
  minimapScenario(); renderToolOpts(); fit(); render(); inspect(); fillFind(); check();
  if (S.tab === "images") showImages();
}

async function refreshMedia() {
  if (!S.source) return;
  const r = await api("/api/scenario?" + q());
  S.media = new Set(r.media); S.sprites.clear(); minimap.invalidate(); draw(); inspect();
}

async function save() {
  if (!S.editable || !dirty()) return;
  await api("/api/scenario?" + q(), {method: "POST", body: JSON.stringify(S.scn)});
  S.savedAt = S.version; render(); toast("Saved");
}

// ---------------------------------------------------------------- editing and undo
// edit(label, fn): fn changes the scenario only through set(obj, key, value) and splice(arr, ...), so
// the whole change undoes as one step.
function edit(label, fn) {
  if (!S.editable) { toast("Read only: copy it to a workspace to edit"); return false; }
  const tx = S.tx = {label, ops: []};
  try { fn(); } catch (e) { undoOps(tx.ops); S.tx = null; toast(e.message); return false; }
  S.tx = null;
  if (!tx.ops.length) return false;
  S.undo.push(tx); S.redo = []; S.version = ++editCounter; S.undo.at(-1).version = S.version;
  changed();
  return true;
}
let editCounter = 0;
function set(obj, key, value) {
  const had = Object.prototype.hasOwnProperty.call(obj, key);
  S.tx.ops.push({obj, key, had, old: obj[key]});
  if (value === undefined) delete obj[key]; else obj[key] = value;
}
function undoOps(ops) {
  for (let i = ops.length - 1; i >= 0; i--) {
    const o = ops[i];
    if (o.had) o.obj[o.key] = o.old; else delete o.obj[o.key];
  }
}
function undo() {
  const tx = S.undo.pop(); if (!tx) return;
  for (const o of tx.ops) { o.new = o.obj[o.key]; o.newHad = Object.prototype.hasOwnProperty.call(o.obj, o.key); }
  undoOps(tx.ops); S.redo.push(tx);
  S.version = S.undo.at(-1)?.version || 0; toast("Undid: " + tx.label); changed();
}
function redo() {
  const tx = S.redo.pop(); if (!tx) return;
  for (const o of tx.ops) { const v = o.obj[o.key], h = Object.prototype.hasOwnProperty.call(o.obj, o.key);
    if (o.newHad) o.obj[o.key] = o.new; else delete o.obj[o.key]; o.new = v; o.newHad = h; }
  S.undo.push(tx); S.version = tx.version; toast("Redid: " + tx.label); changed();
}
const dirty = () => S.version !== S.savedAt;
function changed() {
  S.sels = S.sels.filter(t => byId(t.id));      // an undo can take away what was selected
  minimap.invalidate(); render(); inspect(); fillFind(); check();
}

// A live edit follows the pointer: each liveApply() undoes the last attempt and tries again from the
// starting state, and endLive() records the final one as a single undo step. An attempt that
// returns {error} is dropped and the last good one is put back.
function beginLive(label) {
  if (!S.editable) { toast("Read only: copy it to a workspace to edit"); return false; }
  S.live = {label, ops: [], good: null};
  return true;
}
function liveApply(fn) {
  const L = S.live;
  if (!L) return null;
  undoOps(L.ops); L.ops = [];
  S.tx = L;
  let res;
  try { res = fn(); } catch (e) { res = {error: e.message}; } finally { S.tx = null; }
  if (res?.error) {
    undoOps(L.ops); L.ops = [];
    if (L.good) { S.tx = L; try { L.good(); } finally { S.tx = null; } }
  } else L.good = fn;
  draw();
  return res;
}
function endLive() {
  const L = S.live; S.live = null;
  if (!L || !L.ops.length) { draw(); return; }
  S.version = ++editCounter;
  S.undo.push({label: L.label, ops: L.ops, version: S.version}); S.redo = [];
  changed();
}
function cancelLive() {
  const L = S.live; S.live = null;
  if (L) undoOps(L.ops);
  draw();
}

// ---------------------------------------------------------------- lookups and references
const regions = () => S.scn?.regions || [];
const entities = () => S.scn?.entities || [];
const byId = id => regions().find(r => r.id === id) || entities().find(e => e.id === id)
  || (S.scn?.objectTemplates || []).find(t => t.id === id) || (S.scn?.itemTemplates || []).find(t => t.id === id)
  || (S.scn?.hostileNpcTemplates || []).find(t => t.id === id) || null;
const objTpl = id => (S.scn.objectTemplates || []).find(t => t.id === id);
const area = r => r.size[0] * r.size[1];
const inRect = (r, x, y) => x >= r.position[0] && y >= r.position[1] && x < r.position[0] + r.size[0] && y < r.position[1] + r.size[1];
const contains = (o, i) => o.position[0] <= i.position[0] && o.position[1] <= i.position[1]
  && i.position[0] + i.size[0] <= o.position[0] + o.size[0] && i.position[1] + i.size[1] <= o.position[1] + o.size[1];
const entKind = e => e.type === "object" ? "objects" : e.type === "player" ? "player" : e.hostile ? "hostiles" : "npcs";
const regionLayer = r => r.wall ? "walled" : "areas";
const entSize = e => e.size || objTpl(e.templateId)?.size || [1, 1];
const label = o => o ? (o.name || o.title || o.id) : "(missing)";

// Everything that refers to a thing by id or by name: [{text, id (to jump to), detail}]
function usedBy(id) {
  const out = [], scn = S.scn, r = regions().find(x => x.id === id);
  if (r) {
    for (const e of entities()) (e.schedule || []).forEach(b => {
      if (b.location === r.name) out.push({id: e.id, text: e.name, detail: `${b.start}–${b.end} ${b.role}`});
    });
    for (const c of scn.calendar || []) if (c.location === r.name) out.push({id: null, text: c.name, detail: "calendar event"});
    for (const t of scn.hostileNpcTemplates || []) if (t.regionId === id) out.push({id: t.id, text: t.name, detail: "hostile type, spawns here"});
  }
  const ot = (scn.objectTemplates || []).find(t => t.id === id);
  if (ot) {
    for (const e of entities()) if (e.type === "object" && e.templateId === id) out.push({id: e.id, text: e.name, detail: "placed"});
    for (const t of scn.objectTemplates) for (const ef of t.startingEffects || []) for (const es of ef.endState || [])
      if (es.templateId === id) out.push({id: t.id, text: t.name, detail: `effect: ${ef.desc || es.type}`});
  }
  const it = (scn.itemTemplates || []).find(t => t.id === id);
  if (it) {
    for (const e of entities()) {
      const stacks = [...(e.inventory || []), ...Object.values(e.equipment || {}), ...((e.merchant || {}).stock || [])];
      const n = stacks.filter(s => s && s.templateId === id).length;
      if (n) out.push({id: e.id, text: e.name, detail: "carries it"});
    }
    for (const t of [...(scn.objectTemplates || []), ...(scn.hostileNpcTemplates || [])]) {
      if ((t.lootPoolIds || []).includes(id)) out.push({id: t.id, text: t.name, detail: "loot"});
      for (const ef of t.startingEffects || []) for (const es of ef.endState || [])
        if (es.item?.name === it.name) out.push({id: t.id, text: t.name, detail: `effect: ${ef.desc || es.type}`});
    }
  }
  const ht = (scn.hostileNpcTemplates || []).find(t => t.id === id);
  if (ht) for (const e of entities()) if (e.templateId === id) out.push({id: e.id, text: e.name, detail: "placed"});
  return out;
}

// ---------------------------------------------------------------- selection
const primary = () => S.sels.at(-1) || null;
function select(sel, centerOn = false) {
  S.sels = sel ? [sel] : []; draw(); inspect();
  if (centerOn && sel) {
    const o = byId(sel.id);
    if (o?.position) center(o.position[0] + o.size[0] / 2, o.position[1] + o.size[1] / 2, 6);
    else if (o?.pos) center(o.pos[0], o.pos[1]);
  }
}
function jump(id) {
  const o = byId(id);
  if (!o) return;
  if (o.position) select({kind: "region", id}, true);
  else if (o.pos) select({kind: "entity", id}, true);
  else select({kind: "template", id});
}

// ---------------------------------------------------------------- side panels
function buildLayers() {
  let saved = {};
  try { saved = JSON.parse(recall("editor.layers") || "{}"); } catch {}
  for (const l of LAYERS) S.layers[l.key] = {lock: !!saved[l.key]?.lock, hide: !!saved[l.key]?.hide};
  $("layers").querySelector("tbody").innerHTML = LAYERS.map(l => `<tr>
    <td><span class="swatch" style="background:${l.color}"></span>${esc(l.label)}</td>
    <td class="c"><input type="checkbox" data-k="${l.key}" data-f="lock" ${S.layers[l.key].lock ? "checked" : ""}></td>
    <td class="c"><input type="checkbox" data-k="${l.key}" data-f="hide" ${S.layers[l.key].hide ? "checked" : ""}></td></tr>`).join("");
  $("layers").onchange = e => {
    const {k, f} = e.target.dataset;
    S.layers[k][f] = e.target.checked; remember("editor.layers", JSON.stringify(S.layers));
    if (S.layers[k][f]) S.sels = S.sels.filter(t => layerOf(t) !== k);
    minimap.invalidate(); draw(); inspect();
  };
}
function layerOf(sel) {
  const o = byId(sel.id);
  return !o ? null : sel.kind === "region" ? regionLayer(o) : sel.kind === "entity" ? entKind(o) : null;
}

let checkTimer = 0;
function check() {
  clearTimeout(checkTimer);
  if (!S.scn) return renderProblems();
  checkTimer = setTimeout(async () => {
    const n = ++S.checking;
    try {
      const r = await api("/api/check?" + q(), {method: "POST", body: JSON.stringify(S.scn)});
      if (n === S.checking) { S.problems = r.problems; renderProblems(); }
    } catch (e) { toast("Check failed: " + e.message); }
  }, 400);
}
function renderProblems() {
  const box = $("problems");
  if (!S.scn) { box.innerHTML = `<p class="hint">Open a scenario to check it.</p>`; return; }
  const n = lv => S.problems.filter(p => p.level === lv).length;
  const show = S.problems.filter(p => p.level === "error" || (p.level === "warning" && $("showWarnings").checked)
    || (p.level === "info" && $("showInfo").checked));
  box.innerHTML = `<div class="sum">${n("error")} errors · ${n("warning")} warnings · ${n("info")} notes</div>`
    + (show.length ? show.map((p, i) => `<button class="problem ${p.level}" data-i="${i}">
        <span class="lv">${p.level === "error" ? "Error" : p.level === "warning" ? "Warning" : "Note"}</span>${esc(p.msg)}</button>`).join("")
      : `<p class="hint">Nothing to show.</p>`);
  box.querySelectorAll(".problem").forEach(b => b.onclick = () => {
    const p = show[+b.dataset.i], id = p.refs.find(r => byId(r));
    if (id) jump(id);
  });
}
$("showWarnings").onchange = $("showInfo").onchange = renderProblems;

// ---------------------------------------------------------------- inspector
function field(lbl, html) { return `<label class="field"><span>${esc(lbl)}</span>${html}</label>`; }
function facts(rows) { return `<dl class="facts">${rows.filter(Boolean).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>`; }
function refsHtml(list, empty) {
  if (!list.length) return `<p class="note">${esc(empty)}</p>`;
  return `<div class="refs">${list.map((r, i) => `<button class="ref" data-ref="${i}">${esc(r.text)} <small>${esc(r.detail)}</small></button>`).join("")}</div>`;
}
function bindRefs(root, list) {
  root.querySelectorAll("[data-ref]").forEach(b => b.onclick = () => { const r = list[+b.dataset.ref]; if (r.id) jump(r.id); });
}
const picUrl = (id, kind) => S.media.has(`media/${id}/${id}-${kind}.webp`)
  ? `/media?${q()}&id=${encodeURIComponent(id)}&file=${encodeURIComponent(id + "-" + kind + ".webp")}` : null;
const ro = () => S.editable ? "" : "readonly";

function inspect() {
  const box = $("inspector"), p = primary();
  const o = p && byId(p.id);
  if (!S.scn || !o) { box.innerHTML = `<p class="hint">${S.scn ? "Click something on the map to see it here." : ""}</p>`; return; }
  if (S.sels.length > 1) return inspectMany(box);
  if (p.kind === "region") return inspectRegion(box, o);
  if (p.kind === "template") return inspectTemplate(box, o);
  if (o.type === "object") return inspectObject(box, o);
  return inspectPerson(box, o);
}

function inspectMany(box) {
  const items = S.sels.map(t => byId(t.id)).filter(Boolean);
  const n = k => items.filter(k).length;
  box.innerHTML = `<div class="kind">Selection</div><h3>${items.length} selected</h3>
    ${facts([["Regions", n(o => o.position)], ["Objects", n(o => o.type === "object")], ["People", n(o => o.type === "npc" || o.type === "player")]])}
    <p class="note">Drag any selected object or person to move them all; arrows nudge (Shift: 5 cells); R turns the objects; Delete removes them.</p>
    <div class="refs">${items.map((o, i) => `<button class="ref" data-i="${i}">${esc(o.name)}</button>`).join("")}</div>`;
  box.querySelectorAll("[data-i]").forEach(b => b.onclick = () => jump(items[+b.dataset.i].id));
}

function inspectRegion(box, r) {
  const refs = usedBy(r.id);
  const inside = regions().filter(c => c !== r && contains(r, c));
  const people = entities().filter(e => e.type !== "object" && inRect(r, e.pos[0], e.pos[1])).length;
  const objs = entities().filter(e => e.type === "object" && inRect(r, e.pos[0], e.pos[1])).length;
  const parent = regions().filter(p => p !== r && contains(p, r) && !(contains(r, p) && p.id > r.id)).sort((a, b) => area(a) - area(b))[0];
  box.innerHTML = `<div class="kind">${r.wall ? "Walled region" : "Open area"}${r.hostile ? " · hostile" : ""}</div>
    <h3>${esc(r.name)}</h3>
    ${field("Name", `<div class="row"><input type="text" id="fName" value="${esc(r.name)}" ${ro()} style="flex:1"><button id="fRename" ${S.editable ? "" : "disabled"}>Rename</button></div>`)}
    <p class="note">Renaming also updates every schedule and calendar event that names this region.</p>
    ${field("Description", `<textarea id="fDesc" ${ro()}>${esc(r.description || "")}</textarea>`)}
    ${facts([
      ["Inside", parent ? `<button class="linkish" data-jump="${esc(parent.id)}">${esc(parent.name)}</button>` : "the open map"],
      ["Position", `${r.position.join(", ")}`], ["Size", `${r.size.join(" × ")}`],
      ["Ground", esc([r.ground, r.groundTexture].filter(Boolean).join(" · ") || "—")],
      r.wall && ["Wall", esc(r.wall)], r.wall && ["Doors", esc((r.openings || []).map(c => `[${c}]`).join(" ") || "none: sealed")],
      ["Ambience", esc(typeof r.ambience === "string" ? r.ambience : [r.ambience?.day, r.ambience?.night && "night: " + r.ambience.night].filter(Boolean).join(" · ") || "—")],
      ["Contains", `${inside.length} regions · ${objs} objects · ${people} people`],
    ])}
    <div class="kind">Used by</div>${refsHtml(refs, "Nothing names this region.")}`;
  bindRefs(box, refs);
  box.querySelectorAll("[data-jump]").forEach(b => b.onclick = () => jump(b.dataset.jump));
  $("fRename").onclick = () => renameRegion(r, $("fName").value);
  $("fName").onkeydown = e => { if (e.key === "Enter") renameRegion(r, $("fName").value); };
  $("fDesc").onchange = () => edit(`Edit description of ${r.name}`, () => set(r, "description", $("fDesc").value));
}

function renameRegion(r, name) {
  name = name.trim();
  if (!name || name === r.name) return;
  if (regions().some(o => o !== r && o.name === name)) return toast(`Another region is already called "${name}"`);
  const old = r.name;
  let n = 0;
  edit(`Rename ${old} to ${name}`, () => {
    set(r, "name", name);
    for (const e of entities()) for (const b of e.schedule || []) if (b.location === old) { set(b, "location", name); n++; }
    for (const c of S.scn.calendar || []) if (c.location === old) { set(c, "location", name); n++; }
  });
  toast(`Renamed; ${n} schedule and calendar entr${n === 1 ? "y" : "ies"} updated`);
}

function inspectPerson(box, e) {
  const pic = picUrl(e.id, "portrait");
  const where = regions().filter(r => inRect(r, e.pos[0], e.pos[1])).sort((a, b) => area(a) - area(b))[0];
  const tpl = e.templateId && byId(e.templateId);
  box.innerHTML = `<div class="kind">${e.type === "player" ? "Player" : e.hostile ? "Hostile NPC" : "NPC"}${tpl ? " · " + esc(tpl.name) : ""}</div>
    <h3>${esc(e.name)}</h3>
    ${pic ? `<img class="pic" src="${pic}" alt="">` : `<p class="note">No portrait yet; the game makes one, or add one in Images.</p>`}
    ${field("Name", `<input type="text" id="fName" value="${esc(e.name)}" ${ro()}>`)}
    ${field("Description (the GM sees this)", `<textarea id="fDesc" ${ro()}>${esc(e.description || "")}</textarea>`)}
    ${facts([
      ["Stands at", `${e.pos.join(", ")}${where ? ` in <button class="linkish" data-jump="${esc(where.id)}">${esc(where.name)}</button>` : ""}`],
      ["Sprite", esc(e.animationId || "—")], ["Gender", esc(e.gender || "—")], ["Level", esc(e.level ?? "—")],
      e.stance && ["Stance", esc(e.stance)], e.merchant && ["Merchant", "yes"],
    ])}
    ${(e.schedule || []).length ? `<div class="kind">Schedule</div><table class="sched">${e.schedule.map(b => {
      const r = regions().find(x => x.name === b.location);
      return `<tr><td class="t">${esc(b.start)}–${esc(b.end)}</td><td>${esc(b.role)}</td><td>${r
        ? `<button class="linkish" data-jump="${esc(r.id)}">${esc(b.location)}</button>` : `<span style="color:var(--bad)">${esc(b.location)} (no such region)</span>`}</td></tr>`;
    }).join("")}</table>` : ""}`;
  box.querySelectorAll("[data-jump]").forEach(b => b.onclick = () => jump(b.dataset.jump));
  $("fName").onchange = () => {
    const v = $("fName").value.trim();
    if (v) edit(`Rename ${e.name} to ${v}`, () => set(e, "name", v));
  };
  $("fDesc").onchange = () => edit(`Edit description of ${e.name}`, () => set(e, "description", $("fDesc").value));
}

function inspectObject(box, e) {
  const t = objTpl(e.templateId);
  const placed = entities().filter(o => o.templateId === e.templateId).length;
  const where = regions().filter(r => inRect(r, e.pos[0], e.pos[1])).sort((a, b) => area(a) - area(b))[0];
  const pic = t && picUrl(t.id, "sprite");
  box.innerHTML = `<div class="kind">Object</div><h3>${esc(e.name)}</h3>
    ${pic ? `<img class="pic" src="${pic}" alt="">` : ""}
    ${field("Name", `<input type="text" id="fName" value="${esc(e.name)}" ${ro()}>`)}
    <div class="row" style="margin-bottom:10px"><button id="fRotL" ${S.editable ? "" : "disabled"} title="Shift+R">Turn left</button><button id="fRotR" ${S.editable ? "" : "disabled"} title="R">Turn right</button></div>
    ${facts([
      ["Type", t ? `<button class="linkish" data-tpl="${esc(t.id)}">${esc(t.name)}</button> (${placed} placed)` : `<span style="color:var(--bad)">missing template</span>`],
      ["Position", e.pos.join(", ") + (where ? ` in <button class="linkish" data-jump="${esc(where.id)}">${esc(where.name)}</button>` : "")],
      ["Size", entSize(e).join(" × ") + (e.rot ? ` · turned ${e.rot * 90}°` : "")], ["HP", `${e.hp ?? "—"} / ${e.maxHp ?? "—"}`],
      ["Holds", `${(e.inventory || []).length} item stack${(e.inventory || []).length === 1 ? "" : "s"}`],
    ])}`;
  box.querySelectorAll("[data-jump]").forEach(b => b.onclick = () => jump(b.dataset.jump));
  box.querySelectorAll("[data-tpl]").forEach(b => b.onclick = () => select({kind: "template", id: b.dataset.tpl}));
  $("fRotL").onclick = () => rotateSelection(3); $("fRotR").onclick = () => rotateSelection(1);
  $("fName").onchange = () => {
    const v = $("fName").value.trim();
    if (v) edit(`Rename ${e.name} to ${v}`, () => set(e, "name", v));
  };
}

function inspectTemplate(box, t) {
  const refs = usedBy(t.id), kind = t.id.split("_")[0];
  const pic = picUrl(t.id, kind === "otpl" ? "sprite" : kind === "itpl" ? "item" : "x");
  const walk = t.walkability ?? 0;
  box.innerHTML = `<div class="kind">${kind === "otpl" ? "Object type" : kind === "itpl" ? "Item" : kind === "htpl" ? "Hostile type" : "Template"}</div>
    <h3>${esc(t.name)}</h3>
    ${pic ? `<img class="pic" src="${pic}" alt="">` : ""}
    ${facts([
      t.size && ["Size", t.size.join(" × ")],
      kind === "otpl" && ["Movement", walk <= 0 ? "blocks" : walk >= 1 ? "walk over" : `slows (${walk})`],
      t.forSleep && ["Sleep", "can be slept on"], t.craftStation && ["Crafting", "station"],
      t.tags && ["Tags", esc(t.tags.join(", "))], t.description && ["About", esc(t.description)],
    ])}
    <div class="kind">Used by</div>${refsHtml(refs, "Nothing uses this.")}`;
  bindRefs(box, refs);
}

// ---------------------------------------------------------------- top bar, tabs, keys
function render() {
  const has = !!S.scn;
  $("undo").disabled = !S.undo.length; $("redo").disabled = !S.redo.length;
  $("undo").title = S.undo.length ? `Undo: ${S.undo.at(-1).label} (Ctrl+Z)` : "Undo (Ctrl+Z)";
  $("redo").title = S.redo.length ? `Redo: ${S.redo.at(-1).label} (Ctrl+Y)` : "Redo (Ctrl+Y)";
  $("dirty").hidden = !dirty();
  $("save").disabled = !(S.editable && dirty());
  $("readonly").hidden = !has || S.editable;
  $("toWork").hidden = !has || S.editable;
  const dl = $("download");
  dl.classList.toggle("off", !(has && S.editable && !dirty()));
  dl.title = dirty() ? "Save first, then download" : "Download this workspace as a zip for New Game → Import";
  dl.href = has && S.editable ? "/api/export?" + q() : "#";
  draw(); renderProblems();
}

function fillFind() {
  const names = [...regions().map(r => r.name), ...entities().filter(e => e.type !== "object").map(e => e.name)];
  $("findList").innerHTML = [...new Set(names)].sort().map(n => `<option value="${esc(n)}">`).join("");
}
function find() {
  const v = $("find").value.trim().toLowerCase();
  if (!v || !S.scn) return;
  const hit = regions().find(r => r.name.toLowerCase() === v) || entities().find(e => e.name.toLowerCase() === v)
    || regions().find(r => r.name.toLowerCase().includes(v)) || entities().find(e => e.name.toLowerCase().includes(v));
  if (hit) jump(hit.id); else toast("No match");
}
$("find").onkeydown = e => { if (e.key === "Enter") find(); };
$("find").oninput = e => { if (!e.inputType || e.inputType === "insertReplacementText") find(); };  // picked from the list

function showImages() {
  remember("gallery.source", S.source);   // the gallery page opens the scenario it last showed
  $("images").src = "/gallery";
}
function setTab(t) {
  if (t === S.tab) return;
  S.tab = t;
  $("tabMap").classList.toggle("on", t === "map"); $("tabImages").classList.toggle("on", t === "images");
  $("mapView").hidden = t !== "map"; $("images").hidden = t !== "images";
  if (t === "images") showImages(); else { $("images").src = "about:blank"; refreshMedia().catch(() => {}); draw(); }
}
$("tabMap").onclick = () => setTab("map");
$("tabImages").onclick = () => setTab("images");

$("source").onchange = () => openSource($("source").value).catch(e => toast(e.message));
$("openZip").onclick = () => $("zipFile").click();
$("zipFile").onchange = async () => {
  const f = $("zipFile").files[0]; $("zipFile").value = "";
  if (!f) return;
  try { const r = await api("/api/import", {method: "POST", body: f}); await loadSources(r.source); toast("Opened as a workspace"); }
  catch (e) { toast(e.message); }
};
$("toWork").onclick = async () => {
  try { const r = await api("/api/workspace?" + q(), {method: "POST"}); S.savedAt = S.version; await loadSources(r.source); toast("Copied to a workspace"); }
  catch (e) { toast(e.message); }
};
$("save").onclick = () => save().catch(e => toast(e.message));
$("undo").onclick = undo; $("redo").onclick = redo;
document.addEventListener("keydown", e => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName);
  const mod = e.ctrlKey || e.metaKey;
  if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); save().catch(err => toast(err.message)); }
  else if (typing) return;
  else if (mod && e.key.toLowerCase() === "z" && !e.shiftKey) { e.preventDefault(); undo(); }
  else if (mod && (e.key.toLowerCase() === "y" || (e.key.toLowerCase() === "z" && e.shiftKey))) { e.preventDefault(); redo(); }
});
window.addEventListener("beforeunload", e => { if (dirty()) { e.preventDefault(); e.returnValue = ""; } });

buildLayers();
loadSources().catch(e => toast(e.message));
