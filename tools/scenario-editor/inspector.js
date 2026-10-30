"use strict";
// Inspector of the Scenario Editor: the right-hand panel that shows and edits whatever is selected.
// Forms are described as field lists (see formHtml) and every change goes through edit(), so each
// one is a single undo step. Lists of the game's values come from /api/meta (scenario_checks.py).

// ---------------------------------------------------------------- small builders
function field(lbl, html, hint) {
  return `<label class="field"><span>${esc(lbl)}</span>${html}${hint ? `<small class="note">${esc(hint)}</small>` : ""}</label>`;
}
function facts(rows) { return `<dl class="facts">${rows.filter(Boolean).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>`; }
function refsHtml(list, empty, attr = "ref") {
  if (!list.length) return `<p class="note">${esc(empty)}</p>`;
  return `<div class="refs">${list.map((r, i) => `<button class="ref" data-${attr}="${i}">${esc(r.text)} <small>${esc(r.detail || "")}</small></button>`).join("")}</div>`;
}
function bindRefs(root, list, attr = "ref") {
  root.querySelectorAll(`[data-${attr}]`).forEach(b => b.onclick = () => { const r = list[+b.getAttribute(`data-${attr}`)]; if (r?.id) jump(r.id); });
}
function bindJumps(root) { root.querySelectorAll("[data-jump]").forEach(b => b.onclick = () => jump(b.dataset.jump)); }
const picUrl = (id, kind) => S.media.has(`media/${id}/${id}-${kind}.webp`)
  ? `/media?${q()}&id=${encodeURIComponent(id)}&file=${encodeURIComponent(id + "-" + kind + ".webp")}` : null;
const dis = () => S.editable ? "" : "disabled";
const linkTo = o => o ? `<button class="linkish" data-jump="${esc(o.id)}">${esc(o.name)}</button>` : "—";
const section = (title, body, open = true) => `<details class="sec" ${open ? "open" : ""}><summary>${esc(title)}</summary>${body}</details>`;

// ---------------------------------------------------------------- forms
// A field: {key, label, type, options, min, max, step, optional, hint, placeholder}
//   key may be a path ("voiceProfile.age"). Types: text, textarea, number, select, check, color,
//   multi (checkboxes over options, value is an array). optional: an empty value removes the key.
//   options: [value, ...] or [[value, label], ...].
const getPath = (o, k) => k.split(".").reduce((v, p) => v?.[p], o);
function setPath(o, k, v) {
  const parts = k.split("."), last = parts.pop();
  let cur = o;
  for (const p of parts) { if (!cur[p] || typeof cur[p] !== "object") set(cur, p, {}); cur = cur[p]; }
  set(cur, last, v);
}
const opts = list => list.map(o => Array.isArray(o) ? o : [o, o]);

function formHtml(prefix, obj, defs) {
  return defs.map(d => {
    const id = `${prefix}-${d.key.replace(/\./g, "-")}`, v = getPath(obj, d.key);
    const common = `id="${id}" data-key="${esc(d.key)}" ${dis()}`;
    let input;
    if (d.type === "textarea") input = `<textarea ${common} rows="${d.rows || 3}" placeholder="${esc(d.placeholder || "")}">${esc(v ?? "")}</textarea>`;
    else if (d.type === "number") input = `<input type="number" ${common} value="${esc(v ?? "")}" min="${d.min ?? ""}" max="${d.max ?? ""}" step="${d.step ?? 1}" placeholder="${esc(d.placeholder || "")}">`;
    else if (d.type === "select") input = `<select ${common}>${d.optional ? `<option value="">${esc(d.none || "—")}</option>` : ""}${opts(d.options).map(([val, lbl]) =>
      `<option value="${esc(val)}" ${String(v ?? "") === String(val) ? "selected" : ""}>${esc(lbl)}</option>`).join("")}</select>`;
    else if (d.type === "check") return `<label class="check"><input type="checkbox" ${common} ${v ? "checked" : ""}> ${esc(d.label)}</label>`;
    else if (d.type === "color") input = `<div class="row"><input type="color" ${common} value="${esc(v || "#888888")}">${v ? "" : `<small class="note">not set</small>`}${v && S.editable ? `<button type="button" class="mini" data-clear="${esc(d.key)}">Clear</button>` : ""}</div>`;
    else if (d.type === "multi") {
      const have = new Set(v || []);
      input = `<div class="multi" ${common}>${opts(d.options).map(([val, lbl]) =>
        `<label><input type="checkbox" value="${esc(val)}" ${have.has(val) ? "checked" : ""} ${dis()}> ${esc(lbl)}</label>`).join("")}</div>`;
    } else input = `<input type="text" ${common} value="${esc(v ?? "")}" placeholder="${esc(d.placeholder || "")}">`;
    return field(d.label, input, d.hint);
  }).join("");
}

function wireForm(root, prefix, obj, defs, what, after) {
  for (const d of defs) {
    const el = root.querySelector(`#${prefix}-${d.key.replace(/\./g, "-")}`);
    if (!el) continue;
    const commit = value => {
      if (d.validate) { const err = d.validate(value); if (err) { toast(err); inspect(); return; } }
      if (d.rename) return renameThing(obj, value);
      edit(`${d.label} of ${what()}`, () => { if (d.apply) d.apply(value); else setPath(obj, d.key, value); after?.(value); });
    };
    if (d.type === "multi") {
      el.onchange = () => commit([...el.querySelectorAll("input:checked")].map(i => i.value));
      continue;
    }
    el.onchange = () => {
      let v = d.type === "check" ? el.checked : el.value;
      if (d.type === "number") v = v === "" ? undefined : Math.min(d.max ?? Infinity, Math.max(d.min ?? -Infinity, Number(v)));
      if (d.type === "text" || d.type === "textarea" || !d.type) v = d.trim === false ? v : v.trim();
      if (d.optional && (v === "" || v === undefined || v === false)) v = undefined;
      if (d.type === "check" && d.dropFalse && !v) v = undefined;
      if ((d.required || (d.type === "number" && !d.optional)) && (v === undefined || v === "" || Number.isNaN(v))) {
        toast(`${d.label} can't be empty`); inspect(); return;
      }
      commit(v);
    };
  }
  root.querySelectorAll("[data-clear]").forEach(b => b.onclick = () =>
    edit(`Clear ${b.dataset.clear} of ${what()}`, () => setPath(obj, b.dataset.clear, undefined)));
}

/** A button that opens the Images tab on this one picture, to regenerate it or browse for your own. */
function imageButton(name, kind) {
  return `<div class="row" style="margin-bottom:10px"><button class="mini" data-img="${esc(name)}">${kind === "portrait" ? "Portrait" : kind === "sprite" ? "Sprite" : "Image"}…</button>
    <small class="note">Regenerate it, or use your own picture.</small></div>`;
}
document.addEventListener("click", e => { const b = e.target.closest?.("[data-img]"); if (b) openImages(b.dataset.img); });

// ---------------------------------------------------------------- dispatch
function inspect() {
  inspectBody();
  const p = primary(), o = p && byId(p.id);
  if (S.editable && o && S.sels.length >= 1 && o.id !== S.scn?.playerId) {
    const bar = document.createElement("div");
    bar.className = "del-bar";
    bar.innerHTML = `<button class="mini" id="iDel">Delete${S.sels.length > 1 ? ` ${S.sels.length}` : ""}</button>
      <small class="note">Shift+Delete removes it even if something uses it, fixing what did.</small>`;
    $("inspector").appendChild(bar);
    $("iDel").onclick = ev => deleteThings(S.sels, ev.shiftKey);
  }
}
function inspectBody() {
  const box = $("inspector"), p = primary();
  const o = p && byId(p.id);
  if (!S.scn) { box.innerHTML = ""; return; }
  if (!o) return inspectBrowse(box);
  if (S.sels.length > 1) return inspectMany(box);
  if (p.kind === "region") return inspectRegion(box, o);
  if (p.kind === "template") {
    const kind = o.id.split("_")[0];
    if (kind === "otpl") return inspectObjectType(box, o);
    if (kind === "htpl") return inspectHostileType(box, o);
    return inspectTemplate(box, o);
  }
  if (o.type === "object") return inspectObject(box, o);
  return inspectPerson(box, o);
}

// Nothing selected: lists to find things by name.
function inspectBrowse(box) {
  const tab = S.browse || "types";
  const lists = {
    types: ["Object types", (S.scn.objectTemplates || []).map(t => ({id: t.id, name: t.name,
      detail: `${entities().filter(e => e.templateId === t.id).length} placed`}))],
    hostile: ["Hostile types", (S.scn.hostileNpcTemplates || []).map(t => ({id: t.id, name: t.name,
      detail: `${byId(t.regionId)?.name || "no region"} · ${t.count || 1}`}))],
    people: ["People", entities().filter(e => e.type !== "object" && !e.templateId).map(e => ({id: e.id, name: e.name,
      detail: e.type === "player" ? "player" : e.hostile ? "hostile" : ""}))],
    regions: ["Regions", regions().map(r => ({id: r.id, name: r.name, detail: `${r.wall ? "walled" : "open"}${r.hostile ? " · hostile" : ""}`}))],
  };
  const [, items] = lists[tab], f = (S.browseFilter || "").toLowerCase();
  const shown = items.filter(i => !f || i.name.toLowerCase().includes(f)).sort((a, b) => a.name.localeCompare(b.name));
  box.innerHTML = `<div class="kind">Browse</div>
    <div class="tabs small">${Object.entries(lists).map(([k, [lbl, l]]) => `<button data-tab="${k}" class="${k === tab ? "on" : ""}">${esc(lbl)} <small>${l.length}</small></button>`).join("")}</div>
    <input type="search" id="bFilter" placeholder="Filter" value="${esc(S.browseFilter || "")}" style="width:100%;margin:8px 0">
    ${tab === "types" && S.editable ? `<button id="bNewType" style="margin-bottom:8px">New object type…</button>` : ""}
    <div class="refs">${shown.map(i => `<button class="ref" data-id="${esc(i.id)}">${esc(i.name)} <small>${esc(i.detail)}</small></button>`).join("") || `<p class="note">Nothing here.</p>`}</div>`;
  box.querySelectorAll("[data-tab]").forEach(b => b.onclick = () => { S.browse = b.dataset.tab; inspect(); });
  box.querySelectorAll("[data-id]").forEach(b => b.onclick = () => jump(b.dataset.id));
  $("bFilter").oninput = () => { S.browseFilter = $("bFilter").value; const pos = $("bFilter").selectionStart; inspect(); $("bFilter").focus(); $("bFilter").setSelectionRange(pos, pos); };
  if ($("bNewType")) $("bNewType").onclick = newObjectType;
}

function inspectMany(box) {
  const items = S.sels.map(t => byId(t.id)).filter(Boolean);
  const n = k => items.filter(k).length;
  const objs = items.filter(o => o.type === "object"), tpls = [...new Set(objs.map(o => o.templateId))];
  box.innerHTML = `<div class="kind">Selection</div><h3>${items.length} selected</h3>
    ${facts([["Regions", n(o => o.position)], ["Objects", objs.length], ["People", n(o => o.type === "npc" || o.type === "player")]])}
    ${objs.length ? field("Change the type of the selected objects", `<select id="mSwap" ${dis()}><option value="">—</option>${typeOptions()}</select>`,
      tpls.length === 1 ? `All are "${objTpl(tpls[0])?.name}".` : `${tpls.length} different types.`) : ""}
    <p class="note">Drag any selected object or person to move them all; arrows nudge (Shift: 5 cells); R turns the objects; Delete removes them.</p>
    <div class="refs">${items.map((o, i) => `<button class="ref" data-i="${i}">${esc(o.name)}</button>`).join("")}</div>`;
  box.querySelectorAll("[data-i]").forEach(b => b.onclick = () => jump(items[+b.dataset.i].id));
  if ($("mSwap")) $("mSwap").onchange = () => swapType(objs, $("mSwap").value);
}

// ---------------------------------------------------------------- regions
function inspectRegion(box, r) {
  const M = S.meta, refs = usedBy(r.id);
  const inside = regions().filter(c => c !== r && contains(r, c));
  const people = entities().filter(e => e.type !== "object" && inRect(r, e.pos[0], e.pos[1])).length;
  const objs = entities().filter(e => e.type === "object" && inRect(r, e.pos[0], e.pos[1]));
  const parent = MapOps.parentOf(S.scn, r);
  const amb = typeof r.ambience === "string" ? {day: r.ambience} : (r.ambience || {});
  const defs = [
    {key: "description", label: "Description", type: "textarea", hint: "Shown to the player in the region panel. The GM only sees region names."},
    {key: "hostile", label: "Hostile: dangerous territory where hostile types spawn", type: "check", dropFalse: true},
    {key: "wall", label: "Walls", type: "select", optional: true, none: "none (open area)", options: M.walls},
    {key: "ground", label: "Ground (footsteps)", type: "select", options: M.ground},
    {key: "groundTexture", label: "Ground texture", type: "select", optional: true, options: M.textures},
    {key: "groundColor", label: "Ground tint", type: "color", optional: true},
    ...(r.wall ? [{key: "wallColor", label: "Wall tint", type: "color", optional: true}] : []),
  ];
  const sleepers = new Set(), beds = objs.filter(o => objTpl(o.templateId)?.forSleep).length;
  for (const e of entities()) for (const b of e.schedule || []) if (b.location === r.name && b.role === "sleep" && !e.templateId) sleepers.add(e.id);
  box.innerHTML = `<div class="kind">${r.wall ? "Walled region" : "Open area"}${r.hostile ? " · hostile" : ""}</div>
    <h3>${esc(r.name)}</h3>
    ${field("Name", `<div class="row"><input type="text" id="fName" value="${esc(r.name)}" ${dis()} style="flex:1"><button id="fRename" ${dis()}>Rename</button></div>`,
      "Renaming also updates every schedule and calendar event that names this region.")}
    ${formHtml("rg", r, defs)}
    <div class="row2">${field("Ambience by day", `<select id="fAmbDay" ${dis()}><option value="">—</option>${M.ambience.map(a => `<option ${amb.day === a ? "selected" : ""}>${a}</option>`).join("")}</select>`)}
    ${field("At night", `<select id="fAmbNight" ${dis()}><option value="">same</option>${M.ambience.map(a => `<option ${amb.night === a ? "selected" : ""}>${a}</option>`).join("")}</select>`)}</div>
    ${facts([
      ["Inside", parent ? linkTo(parent) : "the open map"],
      ["Position", r.position.join(", ")], ["Size", r.size.join(" × ")],
      ["Contains", `${inside.length} regions · ${objs.length} objects · ${people} people`],
      sleepers.size || beds ? ["Beds", `<span class="${beds < sleepers.size ? "bad" : ""}">${beds} for ${sleepers.size} sleeper${sleepers.size === 1 ? "" : "s"}</span>`] : null,
    ])}
    ${r.wall ? section(`Doors (${(r.openings || []).length})`, (r.openings || []).length
      ? `<div class="refs">${r.openings.map((c, i) => `<div class="door"><span>[${c.join(", ")}]</span>${S.editable ? `<button class="mini" data-door="${i}" title="Remove this door and its other side">Remove</button>` : ""}</div>`).join("")}</div>`
      : `<p class="note warn">No doors: nobody can get in. Use the Door tool (D) to add one.</p>`) : ""}
    ${section("Who is here when", occupancyHtml(r))}
    ${section(`Used by (${refs.length})`, refsHtml(refs, "Nothing names this region."), refs.length > 0 && refs.length < 12)}`;
  bindRefs(box, refs); bindJumps(box);
  wireForm(box, "rg", r, defs, () => r.name);
  $("fRename").onclick = () => renameThing(r, $("fName").value);
  $("fName").onkeydown = e => { if (e.key === "Enter") renameThing(r, $("fName").value); };
  const setAmb = () => {
    const day = $("fAmbDay").value, night = $("fAmbNight").value;
    edit(`Ambience of ${r.name}`, () => set(r, "ambience", day ? (night ? {day, night} : {day}) : undefined));
  };
  $("fAmbDay").onchange = $("fAmbNight").onchange = setAmb;
  box.querySelectorAll("[data-door]").forEach(b => b.onclick = () => {
    const c = r.openings[+b.dataset.door];
    edit(`Remove door at [${c}]`, () => MapOps.toggleDoor(S.scn, r, c, set));
  });
  wireOccupancy(box);
}

// A strip of 24 hours: how many people are in the region in each hour, by role.
const ROLE_COLOR = {work: "#3d7fd6", leisure: "#4fa37a", sleep: "#8661b3"};
function occupancyHtml(r) {
  const people = entities().filter(e => e.type !== "object" && !e.templateId);
  const hours = Schedule.occupancy(people, r.name);
  const max = Math.max(1, ...hours.map(h => h.length));
  if (!hours.some(h => h.length)) return `<p class="note">No one's schedule brings them here.</p>`;
  return `<div class="occ">${hours.map((h, i) => {
    const by = role => h.filter(p => p.role === role).length;
    const bar = ["sleep", "work", "leisure"].map(role => by(role) ? `<i style="height:${by(role) / max * 100}%;background:${ROLE_COLOR[role]}"></i>` : "").join("");
    return `<button class="hr" data-hour="${i}" title="${String(i).padStart(2, "0")}:00 — ${h.length ? esc(h.map(p => `${p.name} (${p.role})`).join(", ")) : "nobody"}">${bar}</button>`;
  }).join("")}</div><div class="occ-axis"><span>0</span><span>6</span><span>12</span><span>18</span><span>24</span></div>
  <div class="legend">${Object.entries(ROLE_COLOR).map(([k, c]) => `<span><i style="background:${c}"></i>${k}</span>`).join("")}</div>
  <div id="occList" class="refs"></div>`;
}
function wireOccupancy(box) {
  const p = primary(), r = p && byId(p.id);
  box.querySelectorAll(".occ .hr").forEach(b => b.onclick = () => {
    const people = entities().filter(e => e.type !== "object" && !e.templateId);
    const h = Schedule.occupancy(people, r.name)[+b.dataset.hour];
    $("occList").innerHTML = `<small class="note">${String(b.dataset.hour).padStart(2, "0")}:00–${String(+b.dataset.hour + 1).padStart(2, "0")}:00</small>`
      + (h.map(x => `<button class="ref" data-jump="${esc(x.id)}">${esc(x.name)} <small>${esc(x.role)}</small></button>`).join("") || `<p class="note">Nobody.</p>`);
    bindJumps($("occList"));
  });
}

// ---------------------------------------------------------------- objects
function typeOptions(selected) {
  return [...(S.scn.objectTemplates || [])].sort((a, b) => a.name.localeCompare(b.name))
    .map(t => `<option value="${esc(t.id)}" ${t.id === selected ? "selected" : ""}>${esc(t.name)} (${t.size.join("×")})</option>`).join("");
}

function swapType(objs, tid) {
  const t = objTpl(tid);
  if (!t) return;
  edit(objs.length === 1 ? `Change ${objs[0].name} to ${t.name}` : `Change ${objs.length} objects to ${t.name}`, () => {
    for (const o of objs) {
      set(o, "templateId", t.id);
      set(o, "size", (o.rot || 0) % 2 ? [t.size[1], t.size[0]] : t.size.slice());
      set(o, "maxHp", t.maxHp ?? o.maxHp); set(o, "hp", t.maxHp ?? o.hp);
      set(o, "statusEffects", (t.startingEffects || []).map(def => ({id: MapOps.newId("se"), def: JSON.parse(JSON.stringify(def)), appliedAt: 28800, source: "template"})));
      set(o, "pos", [Math.min(o.pos[0], S.scn.gridSize[0] - o.size[0]), Math.min(o.pos[1], S.scn.gridSize[1] - o.size[1])]);
    }
  });
}

function inspectObject(box, e) {
  const t = objTpl(e.templateId);
  const placed = entities().filter(o => o.templateId === e.templateId).length;
  const where = regions().filter(r => inRect(r, e.pos[0], e.pos[1])).sort((a, b) => area(a) - area(b))[0];
  const pic = t && picUrl(t.id, "sprite");
  const defs = [
    {key: "name", label: "Name", required: true, rename: true},
    {key: "hp", label: "HP", type: "number", min: 0, max: e.maxHp ?? 9999},
  ];
  box.innerHTML = `<div class="kind">Object</div><h3>${esc(e.name)}</h3>
    ${pic ? `<img class="pic" src="${pic}" alt="">` : ""}
    ${t ? imageButton(t.name, "sprite") : ""}
    ${formHtml("ob", e, defs)}
    ${field("Type", `<div class="row"><select id="oType" ${dis()} style="flex:1">${typeOptions(e.templateId)}</select>${t ? `<button id="oEditType" class="mini">Edit type</button>` : ""}</div>`,
      t ? `${placed} placed. Changing the type swaps this one only; editing the type changes all ${placed}.` : "Its type is missing.")}
    <div class="row" style="margin-bottom:10px"><button id="fRotL" ${dis()} title="Shift+R">Turn left</button><button id="fRotR" ${dis()} title="R">Turn right</button></div>
    ${facts([
      ["Position", e.pos.join(", ") + (where ? ` in ${linkTo(where)}` : "")],
      ["Size", entSize(e).join(" × ") + (e.rot ? ` · turned ${e.rot * 90}°` : "")],
      (e.statusEffects || []).length && ["Effects", esc(e.statusEffects.map(s => `${s.def?.emoji || ""} ${s.def?.desc || "effect"}`).join(", "))],
    ])}
    ${section(`Holds (${(e.inventory || []).length})`, stacksHtml("inv", e.inventory || []), (e.inventory || []).length > 0)}`;
  bindJumps(box);
  wireForm(box, "ob", e, defs, () => e.name);
  $("oType").onchange = () => swapType([e], $("oType").value);
  if ($("oEditType")) $("oEditType").onclick = () => select({kind: "template", id: t.id});
  $("fRotL").onclick = () => rotateSelection(3); $("fRotR").onclick = () => rotateSelection(1);
  wireStacks(box, "inv", e, "inventory");
}

function inspectObjectType(box, t) {
  const M = S.meta, placed = entities().filter(o => o.templateId === t.id), refs = usedBy(t.id);
  const pic = picUrl(t.id, "sprite"), items = itemOptions();
  const placedList = placed.map(o => ({id: o.id, text: o.name, detail: o.pos.join(", ")}));
  const defs = [
    {key: "name", label: "Name", required: true, rename: true, validate: v => (S.scn.objectTemplates || []).some(o => o !== t && o.name === v) ? `Another object type is already called "${v}"` : null},
    {key: "description", label: "Description", type: "textarea", rows: 2},
    {key: "physicalDescription", label: "Looks (for the image)", type: "textarea", rows: 2, hint: "The image service draws the sprite from this."},
    {key: "walkability", label: "Movement", type: "number", min: 0, max: 1, step: .1, hint: "0 blocks the cell, 1 can be walked over, between slows."},
    {key: "forSleep", label: "Can be slept on", type: "check"},
    {key: "craftStation", label: "Crafting station", type: "check"},
    {key: "light", label: "Light", type: "number", min: 0, max: 1, step: .1, optional: true},
    {key: "heightM", label: "Height (m)", type: "number", min: 0, max: 50, step: .1, optional: true},
    {key: "maxHp", label: "Max HP", type: "number", min: 1, max: 100000},
    {key: "money", label: "Money tier (0–5)", type: "number", min: 0, max: 5, optional: true, hint: "1 pocket change … 5 a month's wages, rolled per object."},
    {key: "tags", label: "Tags (schedules use them to find places)", type: "multi", options: [...new Set([...M.objectTags, ...(t.tags || [])])]},
    {key: "lootPoolIds", label: "Loot", type: "multi", options: items},
  ];
  box.innerHTML = `<div class="kind">Object type</div><h3>${esc(t.name)}</h3>
    ${pic ? `<img class="pic" src="${pic}" alt="">` : `<p class="note">No sprite yet; the game draws one when it starts.</p>`}
    ${imageButton(t.name, "sprite")}
    <p class="note warn">Changes here apply to all ${placed.length} placed.</p>
    <div class="row2">${field("Width", `<input type="number" id="tW" min="1" max="20" value="${t.size[0]}" ${dis()}>`)}${field("Height", `<input type="number" id="tH" min="1" max="20" value="${t.size[1]}" ${dis()}>`)}</div>
    ${formHtml("ot", t, defs)}
    ${section(`Placed (${placed.length})`, refsHtml(placedList, "None placed.", "placed"), placed.length > 0 && placed.length < 12)}
    ${section(`Used by (${refs.filter(r => r.kind !== "placed").length})`, refsHtml(refs.filter(r => r.kind !== "placed"), "Nothing else refers to it."), false)}`;
  bindRefs(box, refs.filter(r => r.kind !== "placed")); bindRefs(box, placedList, "placed");
  wireForm(box, "ot", t, defs, () => t.name, () => {
    if (t.maxHp) for (const o of placed) if ((o.maxHp ?? 0) !== t.maxHp) { set(o, "maxHp", t.maxHp); set(o, "hp", Math.min(o.hp ?? t.maxHp, t.maxHp)); }
  });
  const resize = () => {
    const w = Math.max(1, Math.min(20, +$("tW").value | 0)), h = Math.max(1, Math.min(20, +$("tH").value | 0));
    if (w === t.size[0] && h === t.size[1]) return;
    edit(`Size of ${t.name}`, () => {
      set(t, "size", [w, h]);
      for (const o of placed) {
        const sz = (o.rot || 0) % 2 ? [h, w] : [w, h];
        set(o, "size", sz);
        set(o, "pos", [Math.min(o.pos[0], S.scn.gridSize[0] - sz[0]), Math.min(o.pos[1], S.scn.gridSize[1] - sz[1])]);
      }
    });
  };
  $("tW").onchange = $("tH").onchange = resize;
}

function newObjectType() {
  const name = prompt("Name for the new object type?")?.trim();
  if (!name) return;
  if ((S.scn.objectTemplates || []).some(t => t.name === name)) return toast(`An object type called "${name}" already exists`);
  const t = {id: MapOps.newId("otpl"), name, description: "", physicalDescription: "", size: [1, 1], walkability: 0,
    forSleep: false, craftStation: false, maxHp: 50, heightM: 1, tags: [], lootPoolIds: []};
  edit(`New object type ${name}`, () => set(S.scn, "objectTemplates", [...(S.scn.objectTemplates || []), t]));
  S.placeTpl = t.id; remember("editor.placeTpl", t.id);
  select({kind: "template", id: t.id});
}

// ---------------------------------------------------------------- items carried (inventory, merchant stock)
function itemOptions() {
  return [...(S.scn.itemTemplates || [])].sort((a, b) => a.name.localeCompare(b.name)).map(t => [t.id, `${t.name} (${t.type})`]);
}
function stacksHtml(prefix, stacks) {
  const rows = stacks.map((s, i) => {
    const t = byId(s.templateId);
    return `<div class="stack"><span>${t ? esc(t.name) : `<span class="bad">missing item</span>`}</span>
      <input type="number" min="1" max="999" value="${s.count ?? 1}" data-${prefix}-count="${i}" ${dis()}>
      ${S.editable ? `<button class="mini" data-${prefix}-del="${i}" title="Remove">×</button>` : ""}</div>`;
  }).join("");
  return `${rows || `<p class="note">Nothing.</p>`}
    ${S.editable ? `<div class="row"><select id="${prefix}-add" style="flex:1"><option value="">Add an item…</option>${itemOptions().map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("")}</select></div>` : ""}`;
}
function wireStacks(box, prefix, owner, path) {
  const list = () => getPath(owner, path) || [];
  const put = (label, next) => edit(`${label} (${owner.name})`, () => setPath(owner, path, next));
  box.querySelectorAll(`[data-${prefix}-count]`).forEach(inp => inp.onchange = () => {
    const i = +inp.dataset[`${prefix}Count`], next = list().map((s, j) => j === i ? {...s, count: Math.max(1, +inp.value | 0)} : s);
    put("Item count", next);
  });
  box.querySelectorAll(`[data-${prefix}-del]`).forEach(b => b.onclick = () => put("Remove item", list().filter((_, j) => j !== +b.dataset[`${prefix}Del`])));
  const add = box.querySelector(`#${prefix}-add`);
  if (add) add.onchange = () => { if (add.value) put("Add item", [...list(), {id: MapOps.newId("it"), count: 1, templateId: add.value}]); };
}

// ---------------------------------------------------------------- people
function inspectPerson(box, e) {
  const M = S.meta, pic = picUrl(e.id, "portrait");
  const where = regions().filter(r => inRect(r, e.pos[0], e.pos[1])).sort((a, b) => area(a) - area(b))[0];
  const tpl = e.templateId && byId(e.templateId);
  const ident = [
    {key: "name", label: "Name", required: true, rename: true},
    {key: "gender", label: "Gender", type: "select", options: ["female", "male"]},
    {key: "description", label: "Description (the GM sees this when they're near)", type: "textarea", rows: 3, hint: "Personality, wants, relationships. 15–60 words."},
    {key: "physicalDescription", label: "Looks (for the portrait)", type: "textarea", rows: 2},
    {key: "mindset", label: "Mindset (GM notes)", type: "textarea", rows: 2, optional: true, hint: "Only visible if the player opens their panel. The least visible place for secrets."},
  ];
  const look = [
    {key: "animationId", label: "Sprite", type: "select", options: M.animations},
    {key: "spriteColor", label: "Sprite colour", type: "color", optional: true},
    {key: "level", label: "Level", type: "number", min: 1, max: 20},
    {key: "money", label: "Money", type: "number", min: 0, max: 1000000, optional: true},
  ];
  const attitude = e.type === "player" ? [] : [
    {key: "hostile", label: "Hostile", type: "check", dropFalse: true},
    {key: "stance", label: "Stance", type: "select", optional: true, none: "default", options: ["hostile", "neutral", "fleeing"],
      hint: "hostile attacks on sight; a hostile without a stance waits to be provoked."},
  ];
  const voice = [
    {key: "voiceProfile.gender", label: "Voice", type: "select", options: ["Female", "Male"]},
    {key: "voiceProfile.age", label: "Age", type: "multi", options: M.ages},
    {key: "voiceProfile.pitch", label: "Pitch", type: "multi", options: M.pitch},
    {key: "voiceProfile.tags", label: "Accent and style", type: "multi", options: [...new Set([...M.voiceTags, ...(e.voiceProfile?.tags || [])])]},
  ];
  box.innerHTML = `<div class="kind">${e.type === "player" ? "Player" : e.hostile ? "Hostile NPC" : "NPC"}${tpl ? ` · ${linkTo(tpl)}` : ""}</div>
    <h3>${esc(e.name)}</h3>
    ${pic ? `<img class="pic" src="${pic}" alt="">` : `<p class="note">No portrait yet; the game makes one when it starts.</p>`}
    ${imageButton(e.name, "portrait")}
    ${facts([["Stands at", `${e.pos.join(", ")}${where ? ` in ${linkTo(where)}` : ""}`]])}
    ${formHtml("pi", e, ident)}
    ${section("Schedule", `<div id="schedBox"></div>`, e.type !== "player")}
    ${section("Look and level", formHtml("pl", e, look) + formHtml("pa", e, attitude), false)}
    ${section("Voice", formHtml("pv", e, voice), false)}
    ${e.type === "player" ? "" : section(`Merchant`, `<label class="check"><input type="checkbox" id="pMerchant" ${e.merchant ? "checked" : ""} ${dis()}> Sells things</label>
      ${e.merchant ? `<p class="note">Stock the game should start with; leave it empty to let the game make it up.</p>${stacksHtml("stk", e.merchant.stock || [])}` : ""}`, !!e.merchant)}
    ${section(`Carries (${(e.inventory || []).length})`, stacksHtml("inv", e.inventory || []), false)}
    ${section("Equipment", equipmentHtml(e), false)}
    ${section(`Memories (${(e.memories || []).length})`, memoriesHtml(e), false)}`;
  bindJumps(box);
  const what = () => e.name;
  wireForm(box, "pi", e, ident, what); wireForm(box, "pl", e, look, what); wireForm(box, "pa", e, attitude, what); wireForm(box, "pv", e, voice, what);
  if ($("pMerchant")) $("pMerchant").onchange = () => edit(`Merchant (${e.name})`, () => set(e, "merchant", $("pMerchant").checked ? {} : undefined));
  wireStacks(box, "inv", e, "inventory");
  if (e.merchant) wireStacks(box, "stk", e, "merchant.stock");
  wireEquipment(box, e); wireMemories(box, e);
  renderSchedule(e);
}

function equipmentHtml(e) {
  const eq = e.equipment || {}, items = S.scn.itemTemplates || [];
  const fits = slot => items.filter(t => t.type === slot || (t.type === "wieldable" && /^wieldable/.test(slot)));
  return S.meta.slots.map(slot => {
    const cur = eq[slot]?.templateId, list = fits(slot);
    if (!list.length && !cur) return "";
    return field(slot.replace(/1$/, " (main hand)").replace(/2$/, " (off hand)"), `<select data-slot="${slot}" ${dis()}><option value="">—</option>${list.map(t =>
      `<option value="${esc(t.id)}" ${t.id === cur ? "selected" : ""}>${esc(t.name)}</option>`).join("")}</select>`);
  }).join("") || `<p class="note">The scenario has no wearable items.</p>`;
}
function wireEquipment(box, e) {
  box.querySelectorAll("[data-slot]").forEach(sel => sel.onchange = () => {
    const slot = sel.dataset.slot, v = sel.value;
    edit(`Equip ${slot} (${e.name})`, () => {
      const eq = {...(e.equipment || {})};
      if (v) eq[slot] = {id: MapOps.newId("it"), count: 1, templateId: v}; else delete eq[slot];
      set(e, "equipment", eq);
    });
  });
}
function memoriesHtml(e) {
  const ms = e.memories || [];
  return ms.map((m, i) => `<div class="mem"><textarea data-mem="${i}" rows="2" ${dis()}>${esc(m.text)}</textarea>${S.editable ? `<button class="mini" data-memdel="${i}">×</button>` : ""}</div>`).join("")
    + (S.editable ? `<button id="memAdd" class="mini">Add a memory</button>` : "") + `<p class="note">Things they already know when the game starts.</p>`;
}
function wireMemories(box, e) {
  const put = (label, next) => edit(`${label} (${e.name})`, () => set(e, "memories", next.length ? next : undefined));
  box.querySelectorAll("[data-mem]").forEach(t => t.onchange = () => put("Edit memory", (e.memories || []).map((m, i) => i === +t.dataset.mem ? {...m, text: t.value} : m)));
  box.querySelectorAll("[data-memdel]").forEach(b => b.onclick = () => put("Remove memory", (e.memories || []).filter((_, i) => i !== +b.dataset.memdel)));
  if ($("memAdd")) $("memAdd").onclick = () => { put("Add memory", [...(e.memories || []), {t: 0, text: "New memory"}]); };
}

// ---------------------------------------------------------------- schedule editor
// A 24-hour bar of blocks (drag a boundary to move it, click a block to edit it) above a table.
function renderSchedule(e) {
  const box = $("schedBox");
  if (!box) return;
  const sch = e.schedule || [], names = regions().map(r => r.name);
  const problems = sch.length ? Schedule.validate(sch, names) : [];
  const sel = Math.min(S.schedSel ?? 0, Math.max(0, sch.length - 1));
  if (!sch.length) {
    box.innerHTML = `<p class="note">No schedule. ${S.editable ? `<button id="sAllDay" class="mini">Stay where they stand all day</button>` : ""}</p>`;
    if ($("sAllDay")) $("sAllDay").onclick = () => {
      const r = MapOps.regionAt(S.scn, e.pos[0], e.pos[1]);
      if (!r) return toast("They aren't standing in a region");
      edit(`Schedule of ${e.name}`, () => set(e, "schedule", Schedule.makeAllDay(r.name)));
    };
    return;
  }
  let segs = [];
  try { segs = Schedule.segments(sch); } catch (err) { /* a malformed time: the table and the problems below still show */ }
  const bar = segs.map(s => {
    const b = sch[s.index];
    return `<div class="seg ${s.index === sel ? "on" : ""}" data-b="${s.index}" style="left:${s.from / 14.4}%;width:${(s.to - s.from) / 14.4}%;background:${ROLE_COLOR[b.role] || "#888"}"
      title="${esc(b.start)}–${esc(b.end)} ${esc(b.role)} · ${esc(b.location)}"><span>${esc(b.location)}</span></div>`;
  }).join("");
  // a handle at each block's end, i.e. the boundary with the next block (not for an all-day block)
  const handles = Schedule.isAllDay(sch) || !segs.length ? "" : sch.map((b, i) => `<div class="bnd" data-i="${i}" style="left:${Schedule.toMin(b.end) / 14.4}%" title="${esc(b.end)}"></div>`).join("");
  const b = sch[sel], opt = (list, v) => list.map(x => `<option ${x === v ? "selected" : ""}>${esc(x)}</option>`).join("");
  box.innerHTML = `<div class="sbar" id="sBar">${bar}${handles}</div>
    <div class="occ-axis"><span>0</span><span>6</span><span>12</span><span>18</span><span>24</span></div>
    <div class="sblock">
      <div class="row2">${field("From", `<input type="text" value="${esc(b.start)}" disabled>`)}${field("To", `<input type="text" value="${esc(b.end)}" disabled>`)}
      ${field("Doing", `<select id="sRole" ${dis()}>${opt(S.meta.roles, b.role)}</select>`)}</div>
      ${field("Where", `<select id="sLoc" ${dis()}>${names.includes(b.location) ? "" : `<option selected>${esc(b.location)}</option>`}${opt([...names].sort(), b.location)}</select>`)}
      <div class="row">${S.editable ? `<button id="sSplit" class="mini">Split in two</button><button id="sDel" class="mini" ${sch.length < 2 ? "disabled" : ""}>Remove</button><button id="sGo" class="mini">Show on map</button>` : ""}</div>
    </div>
    <table class="sched">${sch.map((x, i) => `<tr class="${i === sel ? "on" : ""}" data-row="${i}"><td class="t">${esc(x.start)}–${esc(x.end)}</td>
      <td><i class="dotc" style="background:${ROLE_COLOR[x.role] || "#888"}"></i>${esc(x.role)}</td><td>${esc(x.location)}</td></tr>`).join("")}</table>
    ${problems.length ? `<div class="note warn">${problems.map(p => esc(p.msg)).join("<br>")}</div>` : ""}
    <p class="note">Drag a line on the bar to move the time between two blocks (15-minute steps).</p>`;
  const put = (label, next) => edit(`${label} (${e.name})`, () => set(e, "schedule", next));
  box.querySelectorAll(".seg, [data-row]").forEach(el => el.onclick = () => { S.schedSel = +(el.dataset.b ?? el.dataset.row); renderSchedule(e); });
  if (S.editable) {
    $("sRole").onchange = () => put("Schedule role", Schedule.setBlock(sch, sel, {role: $("sRole").value}));
    $("sLoc").onchange = () => put("Schedule place", Schedule.setBlock(sch, sel, {location: $("sLoc").value}));
    $("sSplit").onclick = () => {
      const from = Schedule.toMin(b.start), len = Schedule.isAllDay(sch) ? 1440 : (Schedule.toMin(b.end) - from + 1440) % 1440;
      const next = Schedule.split(sch, sel, from + Math.round(len / 2 / Schedule.STEP) * Schedule.STEP);
      if (next.length === sch.length) return toast("That block is too short to split");
      put("Split schedule block", next);
    };
    $("sDel").onclick = () => { put("Remove schedule block", Schedule.remove(sch, sel)); S.schedSel = Math.max(0, sel - 1); };
  }
  if ($("sGo")) $("sGo").onclick = () => { const r = regions().find(x => x.name === b.location); if (r) jump(r.id); };
  // the bar is redrawn while dragging, so follow the pointer on the window rather than the handle
  box.querySelectorAll(".bnd").forEach(h => h.onpointerdown = ev => {
    if (!S.editable || !beginLive(`Schedule times (${e.name})`)) return;
    ev.preventDefault();
    const i = +h.dataset.i, rect = $("sBar").getBoundingClientRect(), start = e.schedule;
    const move = mv => {
      const minute = Math.round((mv.clientX - rect.left) / rect.width * 1440);
      liveApply(() => set(e, "schedule", Schedule.setBoundary(start, i, Math.max(0, Math.min(1440, minute)))));
      renderSchedule(e);
    };
    const done = () => {
      window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", done); window.removeEventListener("pointercancel", done);
      endLive();
    };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", done); window.addEventListener("pointercancel", done);
  });
}

// ---------------------------------------------------------------- hostile types and other templates
function inspectHostileType(box, t) {
  const M = S.meta, placed = entities().filter(e => e.templateId === t.id);
  const regs = [...regions()].sort((a, b) => (b.hostile ? 1 : 0) - (a.hostile ? 1 : 0) || a.name.localeCompare(b.name));
  const defs = [
    {key: "name", label: "Name", required: true, rename: true},
    {key: "description", label: "Description (the GM sees this)", type: "textarea", rows: 3},
    {key: "physicalDescription", label: "Looks (for the portrait)", type: "textarea", rows: 2},
    {key: "regionId", label: "Lives in (spawns and respawns here)", type: "select", options: regs.map(r => [r.id, `${r.name}${r.hostile ? " ☠" : ""}`])},
    {key: "count", label: "How many", type: "number", min: 1, max: 6},
    {key: "gender", label: "Gender", type: "select", options: ["female", "male"]},
    {key: "animationId", label: "Sprite", type: "select", options: M.animations},
    {key: "spriteColor", label: "Sprite colour", type: "color", optional: true},
    {key: "level", label: "Level", type: "number", min: 1, max: 20},
    {key: "money", label: "Money tier (0–5)", type: "number", min: 0, max: 5},
    {key: "attacksOnSight", label: "Attacks on sight", type: "check"},
    {key: "lootPoolIds", label: "Loot", type: "multi", options: itemOptions()},
  ];
  box.innerHTML = `<div class="kind">Hostile type</div><h3>${esc(t.name)}</h3>
    <p class="note">The game spawns this many in its region at the start and respawns them. The ones already placed are listed below.</p>
    ${formHtml("ht", t, defs)}
    ${section(`Placed (${placed.length})`, refsHtml(placed.map(e => ({id: e.id, text: e.name, detail: e.pos.join(", ")})), "None placed."), true)}`;
  bindRefs(box, placed.map(e => ({id: e.id})));
  wireForm(box, "ht", t, defs, () => t.name);
}

function inspectTemplate(box, t) {
  const refs = usedBy(t.id), kind = t.id.split("_")[0];
  const pic = picUrl(t.id, kind === "itpl" ? "item" : "x");
  box.innerHTML = `<div class="kind">${kind === "itpl" ? "Item" : "Template"}</div>
    <h3>${esc(t.name)}</h3>
    ${pic ? `<img class="pic" src="${pic}" alt="">` : ""}
    ${kind === "itpl" ? imageButton(t.name, "item") : ""}
    ${facts([t.type && ["Type", esc(t.type)], t.quality && ["Quality", esc(t.quality)], t.value != null && ["Value", esc(t.value)], t.description && ["About", esc(t.description)]])}
    <div class="kind">Used by</div>${refsHtml(refs, "Nothing uses this.")}`;
  bindRefs(box, refs);
}
