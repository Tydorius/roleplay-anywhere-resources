"use strict";
// Scenario Editor page: state, saving, undo, references and the side panels. The inspector is in
// inspector.js, the map in mapview.js, the map edits in mapops.js and schedule logic in schedule.js. The scenario lives in S.scn and is changed
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
  if (!S.meta) S.meta = await api("/api/meta");
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
const REF_WORD = {schedule: "", calendar: "calendar event", hostileHome: "hostile type, spawns here", placed: "placed",
  effectSpawn: "effect spawns it", carried: "carries it", equipped: "wears it", stock: "sells it", loot: "loot", effectItem: "effect makes it"};
function usedBy(id) {
  return Refs.findRefs(S.scn, id).map(r => ({id: r.ownerId, kind: r.kind, text: r.ownerName || "",
    detail: [REF_WORD[r.kind], r.detail !== r.ownerName ? r.detail : null].filter(Boolean).join(" · ")}));
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

function showImages(find) {
  remember("gallery.source", S.source);   // the gallery page opens the scenario it last showed
  const fr = $("images");
  fr.onload = () => {                     // narrow the gallery to one thing by typing into its search box
    const box = find && fr.contentDocument?.getElementById("search");
    if (box) { box.value = find; box.dispatchEvent(new Event("input")); }
  };
  fr.src = "/gallery";
}
/** Opens the Images tab showing only the images whose name or description matches `find`. */
function openImages(find) { if (S.tab === "images") showImages(find); else setTab("images", find); }
function setTab(t, find) {
  if (t === S.tab) return;
  S.tab = t;
  $("tabMap").classList.toggle("on", t === "map"); $("tabImages").classList.toggle("on", t === "images");
  $("mapView").hidden = t !== "map"; $("images").hidden = t !== "images";
  if (t === "images") showImages(find); else { $("images").src = "about:blank"; refreshMedia().catch(() => {}); draw(); }
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
$("download").onclick = e => {
  const n = S.problems.filter(p => p.level === "error").length;
  if (n && !confirm(`The Problems panel lists ${n} error${n === 1 ? "" : "s"}; the game may refuse this scenario or play it badly. Download anyway?`)) e.preventDefault();
};
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
