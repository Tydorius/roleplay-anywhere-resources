"use strict";
// The Rooms tab: browse the generator's fixed-room library read-only (rl-04a).
// The plan canvas, list, filters, look sprites and the groups page live here;
// every fetch goes to rooms_editor.py's /api/rooms/* endpoints, which never
// write a file. Pure helpers (no DOM) are exported for node --test; the page
// wiring at the bottom runs only in a browser. Plan coordinates match the
// stored rooms: [0,0] is the north-west cell, x grows east, y grows south.

(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Rooms = factory();
})(typeof self !== "undefined" ? self : this, function () {

  // ------------------------------------------------------------ pure helpers

  /** A role's colour from the meta palette: the first prefix that names it
   * (exact or "prefix." child) wins — the server sends the prefixes in
   * specificity order — else the "*" default. */
  function roleColor(roles, role) {
    role = String(role || "");
    for (const prefix of Object.keys(roles || {})) {
      if (prefix === "*") continue;
      if (role === prefix || role.slice(0, prefix.length + 1) === prefix + ".")
        return roles[prefix];
    }
    return (roles || {})["*"] || "#9e9e9e";
  }

  /** A css colour multiplied by `f` (darker for f < 1), truncating like the
   * room sheets' own _darker so both render the same shade. */
  function darker(hex, f) {
    const n = parseInt(String(hex).replace("#", ""), 16);
    const c = v => Math.max(0, Math.min(255, Math.floor(v * f)));
    return "#" + ((c(n >> 16 & 255) << 16) | (c(n >> 8 & 255) << 8) | c(n & 255))
      .toString(16).padStart(6, "0");
  }

  /** The short label for a role on the plan: its first word ("sleep.couple" -> "sleep"). */
  function shortRole(role) { return String(role || "").split(".")[0]; }

  /** The rooms the current filters keep: size band, clearance, style, wealth
   * tier (the room serves it) and a case-insensitive search over id and
   * description. Empty filter values keep everything. */
  function filterRooms(rooms, f) {
    f = f || {};
    const q = String(f.search || "").trim().toLowerCase();
    return (rooms || []).filter(r => {
      if (f.band && r.sizeBand !== f.band) return false;
      if (f.clearance && r.clearance !== f.clearance) return false;
      if (f.style && r.style !== f.style) return false;
      if (f.tier && !(r.wealth || []).includes(f.tier)) return false;
      if (q && !(String(r.id || "").toLowerCase().includes(q)
                 || String(r.description || "").toLowerCase().includes(q))) return false;
      return true;
    });
  }

  /** The plan's cell size and top-left offset fitting a w x h room in a
   * cw x ch box with `pad` pixels spare, centred; the cell is at least 1. */
  function fitPlan(w, h, cw, ch, pad) {
    const cell = Math.max(1, Math.floor(Math.min((cw - 2 * pad) / w, (ch - 2 * pad) / h)));
    return {cell, ox: Math.round((cw - w * cell) / 2), oy: Math.round((ch - h * cell) / 2)};
  }

  /** The room's door cells as [{side, k}] in north/south/east/west order. */
  function doorCells(room) {
    const d = (room || {}).doors || {};
    const out = [];
    for (const side of ["north", "south", "east", "west"])
      for (const k of d[side] || []) out.push({side, k});
    return out;
  }

  /** The room's stretch lines as {x: [], y: []} (missing axes become empty). */
  function stretchLines(room) {
    const st = (room || {}).stretch || {};
    return {x: st.x || [], y: st.y || []};
  }

  function rectOf(p) {
    const at = p && p.at, size = p && p.size;
    return Array.isArray(at) && at.length === 2 && Array.isArray(size) && size.length === 2
      ? [at[0], at[1], size[0], size[1]] : null;
  }

  // fixed_rooms._touch: two rects share an edge, corner touch included
  function touch(a, b) {
    const gx = Math.max(b[0] - (a[0] + a[2]), a[0] - (b[0] + b[2]));
    const gy = Math.max(b[1] - (a[1] + a[3]), a[1] - (b[1] + b[3]));
    return (gx <= 0 && gy === 0) || (gy <= 0 && gx === 0);
  }

  /** The placed group instances, as fixed_rooms.instances sees them: pieces
   * of one group id that touch edge to edge form one entry
   * {gid, box: [x, y, w, h], indices: [piece indexes]}. */
  function groupBoxes(room) {
    const pieces = (room || {}).pieces || [];
    const out = [];
    const used = new Array(pieces.length).fill(false);
    for (let i = 0; i < pieces.length; i++) {
      if (used[i] || rectOf(pieces[i]) === null) continue;
      const gid = pieces[i].group;
      used[i] = true;
      const cluster = [i];
      let grew = true;
      while (grew) {
        grew = false;
        for (let j = 0; j < pieces.length; j++) {
          if (used[j] || pieces[j].group !== gid || rectOf(pieces[j]) === null) continue;
          if (cluster.some(k => touch(rectOf(pieces[k]), rectOf(pieces[j])))) {
            used[j] = true;
            cluster.push(j);
            grew = true;
          }
        }
      }
      const rects = cluster.map(k => rectOf(pieces[k]));
      const x0 = Math.min(...rects.map(r => r[0])), y0 = Math.min(...rects.map(r => r[1]));
      out.push({gid, indices: cluster,
                box: [x0, y0,
                      Math.max(...rects.map(r => r[0] + r[2])) - x0,
                      Math.max(...rects.map(r => r[1] + r[3])) - y0]});
    }
    return out;
  }

  /** The topmost piece index covering cell (x, y), or -1. */
  function pieceAt(room, x, y) {
    const pieces = (room || {}).pieces || [];
    for (let i = pieces.length - 1; i >= 0; i--) {
      const r = rectOf(pieces[i]);
      if (r && x >= r[0] && x < r[0] + r[2] && y >= r[1] && y < r[1] + r[3]) return i;
    }
    return -1;
  }

  // ------------------------------------------------------------ page wiring

  const RM = {meta: null, inited: false, family: "", rooms: [], familyErrors: [],
              view: [], sel: null, room: null, turned: null, turn: 0, mirror: 0,
              look: "", lookData: null, sprites: new Map(), groupsMode: false,
              groupsCache: {}, hover: -1, seq: 0,
              filters: {band: "", clearance: "", style: "", tier: "", search: ""}};

  function page() { return typeof document !== "undefined" && document.getElementById("rmPlan"); }

  if (page()) {
    api("/api/rooms/meta").then(m => {
      RM.meta = m;
      if (!m.present) return;
      $("tabRooms").hidden = false;
      $("tabRooms").onclick = () => { setTab("rooms"); roomsInit(); };
    }).catch(() => {});   // no library: the tab stays hidden, the editor works as today
  }

  function roomsInit() {
    if (RM.inited || !RM.meta) return;
    RM.inited = true;
    const fams = RM.meta.families || [];
    $("rmFamily").innerHTML = fams.map(f =>
      `<option value="${esc(f.family)}">${esc(f.family)} (${f.rooms} room${f.rooms === 1 ? "" : "s"}${f.errors ? `, ${f.errors} error${f.errors === 1 ? "" : "s"}` : ""})</option>`).join("");
    $("rmFamily").onchange = () => { RM.family = $("rmFamily").value; RM.filters.band = ""; loadFamily(); };
    $("rmLook").innerHTML = `<option value="">Plan colours</option>`
      + (RM.meta.bands || []).map(b => `<option value="${esc(b)}">${esc(b)}</option>`).join("");
    $("rmLook").onchange = () => { RM.look = $("rmLook").value; loadRoom(); };
    const fill = (id, label, values) => {
      $(id).innerHTML = `<option value="">${label}</option>`
        + values.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
    };
    fill("rmClearance", "All clearances", RM.meta.clearances || []);
    fill("rmStyle", "All styles", RM.meta.styles || []);
    fill("rmTier", "All tiers", RM.meta.tiers || []);
    for (const id of ["rmBand", "rmClearance", "rmStyle", "rmTier"])
      $(id).onchange = () => { RM.filters[id.slice(2).toLowerCase()] = $(id).value; renderList(); loadRoom(); };
    $("rmSearch").oninput = () => { RM.filters.search = $("rmSearch").value; renderList(); loadRoom(); };
    $("rmTurnL").onclick = () => turnBy(-1);
    $("rmTurnR").onclick = () => turnBy(1);
    $("rmMirror").onclick = () => { RM.mirror = RM.mirror ? 0 : 1; syncToolbar(); loadRoom(); };
    $("rmGroupsBtn").onclick = toggleGroups;
    document.addEventListener("keydown", e => {
      if (S.tab !== "rooms" || RM.groupsMode) return;
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName)) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        moveSel(e.key === "ArrowDown" ? 1 : -1);
      }
    });
    const plan = $("rmPlan");
    plan.onmousemove = onHover;
    plan.onmouseleave = () => { RM.hover = -1; $("rmTip").hidden = true; drawPlan(); };
    if (typeof ResizeObserver !== "undefined")
      new ResizeObserver(() => drawPlan()).observe(plan.parentElement);
    window.addEventListener("resize", drawPlan);
    RM.family = fams.length ? fams[0].family : "";
    $("rmFamily").value = RM.family;
    loadFamily();
  }

  function moveSel(step) {
    if (!RM.view.length) return;
    const i = RM.view.findIndex(r => r.id === RM.sel);
    const next = RM.view[Math.min(RM.view.length - 1, Math.max(0, (i < 0 ? 0 : i + step)))];
    if (next && next.id !== RM.sel) { RM.sel = next.id; renderList(); loadRoom(); }
    const row = document.querySelector(".rm-row.on");
    if (row) row.scrollIntoView({block: "nearest"});
  }

  async function loadFamily() {
    if (!RM.family) return;
    const seq = ++RM.seq;
    try {
      const d = await api("/api/rooms/family?family=" + encodeURIComponent(RM.family));
      if (seq !== RM.seq) return;
      RM.rooms = d.rooms || [];
      RM.familyErrors = d.errors || [];
      const bands = [...new Set(RM.rooms.map(r => r.sizeBand).filter(Boolean))];
      $("rmBand").innerHTML = `<option value="">All bands</option>`
        + bands.map(b => `<option value="${esc(b)}">${esc(b)}</option>`).join("");
      RM.filters.band = "";
      if (!RM.rooms.some(r => r.id === RM.sel)) RM.sel = (RM.rooms[0] || {}).id || null;
      renderList();
      loadRoom();
    } catch (e) { toast(e.message); }
  }

  function renderList() {
    RM.view = filterRooms(RM.rooms, RM.filters);
    if (!RM.view.some(r => r.id === RM.sel)) RM.sel = (RM.view[0] || {}).id || null;
    const box = $("rmList");
    box.innerHTML = (RM.familyErrors.length
      ? `<div class="rm-errs">${RM.familyErrors.map(m =>
          `<div class="problem error">${esc(m)}</div>`).join("")}</div>` : "")
      + (RM.view.length ? RM.view.map(r =>
          `<button type="button" class="rm-row${r.id === RM.sel ? " on" : ""}" data-id="${esc(r.id)}" title="${esc(r.id)}">`
          + `<span class="id">${esc(r.id)}</span>`
          + `<span class="meta">${r.size ? r.size[0] + "×" + r.size[1] : "?"} · ${(r.pieces || []).length}</span>`
          + ((r.errors || []).length ? `<span class="bad" title="${(r.errors || []).length} checker message${(r.errors || []).length === 1 ? "" : "s"}">!</span>` : "")
          + `</button>`).join("")
        : `<p class="rm-norooms">No rooms match these filters.</p>`);
    for (const b of box.querySelectorAll(".rm-row"))
      b.onclick = () => { if (RM.sel !== b.dataset.id) { RM.sel = b.dataset.id; renderList(); loadRoom(); } };
  }

  async function loadRoom() {
    syncToolbar();
    if (!RM.sel) {
      RM.room = RM.turned = RM.lookData = null;
      drawPlan(); renderDetails(); renderSiblings();
      return;
    }
    const seq = ++RM.seq;
    const qs = `id=${encodeURIComponent(RM.sel)}&turn=${RM.turn}&mirror=${RM.mirror}`;
    try {
      const turned = await api("/api/rooms/room?" + qs);
      if (seq !== RM.seq) return;
      RM.turned = turned;
      RM.room = RM.rooms.find(r => r.id === RM.sel) || turned;
      RM.lookData = null;
      if (RM.look) {
        const lk = await api(`/api/rooms/look?${qs}&band=${encodeURIComponent(RM.look)}`);
        if (seq !== RM.seq) return;
        RM.lookData = lk;
        for (const e of lk.look || []) if (e) spriteImg(e.object);
      }
      drawPlan(); renderDetails(); renderSiblings();
    } catch (e) { toast(e.message); }
  }

  function turnBy(step) {
    RM.turn = (RM.turn + step + 4) % 4;
    syncToolbar();
    loadRoom();
  }

  function syncToolbar() {
    $("rmTurns").textContent = RM.turn * 90 + "°";
    $("rmMirror").classList.toggle("on", !!RM.mirror);
    for (const id of ["rmTurnL", "rmTurnR", "rmMirror"]) $(id).disabled = !RM.sel;
  }

  function spriteImg(oid) {
    const key = RM.look + "|" + oid;
    if (!RM.sprites.has(key)) {
      const img = new Image();
      img.onload = () => { if (RM.lookData) drawPlan(); };
      img.src = "/api/rooms/sprite?band=" + encodeURIComponent(RM.look)
              + "&object=" + encodeURIComponent(oid);
      RM.sprites.set(key, img);
    }
    return RM.sprites.get(key);
  }

  // ------------------------------------------------------------ drawing

  function cssVar(name, fallback) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  }

  function drawPlan() {
    const cvs = $("rmPlan");
    if (!cvs || RM.groupsMode) return;
    const dpr = window.devicePixelRatio || 1;
    const cw = cvs.clientWidth, ch = cvs.clientHeight;
    if (!cw || !ch) return;
    cvs.width = Math.round(cw * dpr); cvs.height = Math.round(ch * dpr);
    const ctx = cvs.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cw, ch);
    if (!RM.turned) return;
    const room = RM.turned;
    const [w, h] = room.size || [1, 1];
    const {cell, ox, oy} = fitPlan(w, h, cw, ch, 26);
    const line = cssVar("--line", "#dddbd3"), muted = cssVar("--muted", "#6b6a64");
    // floor grid
    ctx.fillStyle = cssVar("--panel", "#fff");
    ctx.fillRect(ox, oy, w * cell, h * cell);
    ctx.strokeStyle = line;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = 1; x < w; x++) { ctx.moveTo(ox + x * cell + .5, oy); ctx.lineTo(ox + x * cell + .5, oy + h * cell); }
    for (let y = 1; y < h; y++) { ctx.moveTo(ox, oy + y * cell + .5); ctx.lineTo(ox + w * cell, oy + y * cell + .5); }
    ctx.stroke();
    ctx.strokeStyle = muted;
    ctx.strokeRect(ox - .5, oy - .5, w * cell + 1, h * cell + 1);
    // open-style filler: hatched, as the room sheets draw it
    const f = room.filler;
    if (f && f.at && f.size) {
      const fx = ox + f.at[0] * cell, fy = oy + f.at[1] * cell;
      const fw = f.size[0] * cell, fh = f.size[1] * cell;
      ctx.strokeStyle = muted;
      ctx.setLineDash([]);
      ctx.strokeRect(fx + .5, fy + .5, fw - 1, fh - 1);
      ctx.beginPath();
      for (let d = 0; d < fw + fh; d += 6) {
        ctx.moveTo(Math.min(fx + fw, fx + d), Math.max(fy, fy + d - fh));
        ctx.lineTo(Math.max(fx, fx + d - fh), Math.min(fy + fh, fy + d));
      }
      ctx.stroke();
    }
    // pieces
    const pieces = room.pieces || [];
    const look = (RM.lookData && RM.lookData.look) || [];
    ctx.font = `${Math.min(11, Math.max(9, cell - 3))}px ui-monospace, Consolas, monospace`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    for (let i = 0; i < pieces.length; i++) {
      const p = pieces[i];
      const r = rectOf(p);
      if (!r) continue;
      const [x, y, pw, ph] = r;
      const px = ox + x * cell, py = oy + y * cell, PW = pw * cell, PH = ph * cell;
      const rgb = roleColor(RM.meta.roles, p.role);
      const entry = look[i];
      const img = entry && entry.object ? spriteImg(entry.object) : null;
      if (img && img.complete && img.naturalWidth) {
        // the sprite turned so the object's back faces the piece's wall
        ctx.save();
        ctx.translate(px + PW / 2, py + PH / 2);
        ctx.rotate((entry.rot || 0) * Math.PI / 2);
        const dw = entry.rot % 2 ? PH : PW, dh = entry.rot % 2 ? PW : PH;
        ctx.drawImage(img, -dw / 2, -dh / 2, dw, dh);
        ctx.restore();
      } else {
        ctx.fillStyle = rgb;
        ctx.fillRect(px, py, PW, PH);
        ctx.strokeStyle = darker(rgb, .55);
        ctx.setLineDash([]);
        ctx.strokeRect(px + .5, py + .5, PW - 1, PH - 1);
      }
      // the thicker back edge (on top of the sprite too)
      if (p.back) {
        const lw = Math.max(2, Math.round(cell / 5));
        ctx.fillStyle = darker(rgb, .45);
        if (p.back === "north") ctx.fillRect(px, py, PW, lw);
        else if (p.back === "south") ctx.fillRect(px, py + PH - lw, PW, lw);
        else if (p.back === "west") ctx.fillRect(px, py, lw, PH);
        else if (p.back === "east") ctx.fillRect(px + PW - lw, py, lw, PH);
      }
      if (!RM.look && PW >= 30 && PH >= 14) {
        ctx.fillStyle = darker(rgb, .35);
        ctx.fillText(shortRole(p.role), px + PW / 2, py + PH / 2);
      }
    }
    // thin group outlines
    ctx.strokeStyle = muted;
    ctx.setLineDash([]);
    ctx.lineWidth = 1;
    for (const g of groupBoxes(room)) {
      ctx.strokeRect(ox + g.box[0] * cell - 1.5, oy + g.box[1] * cell - 1.5,
                     g.box[2] * cell + 3, g.box[3] * cell + 3);
    }
    // stretch lines: an empty line can be inserted at that seam
    ctx.setLineDash([5, 5]);
    ctx.beginPath();
    for (const v of stretchLines(room).x) {
      ctx.moveTo(ox + v * cell + .5, oy); ctx.lineTo(ox + v * cell + .5, oy + h * cell);
    }
    for (const v of stretchLines(room).y) {
      ctx.moveTo(ox, oy + v * cell + .5); ctx.lineTo(ox + w * cell, oy + v * cell + .5);
    }
    ctx.stroke();
    ctx.setLineDash([]);
    // doors: green marks straddling the wall
    ctx.fillStyle = "#2f9e44";
    for (const {side, k} of doorCells(room)) {
      const c = Math.max(4, Math.round(cell / 2));
      if (side === "north") ctx.fillRect(ox + k * cell + cell / 4, oy - 3, c, 6);
      else if (side === "south") ctx.fillRect(ox + k * cell + cell / 4, oy + h * cell - 3, c, 6);
      else if (side === "west") ctx.fillRect(ox - 3, oy + k * cell + cell / 4, 6, c);
      else ctx.fillRect(ox + w * cell - 3, oy + k * cell + cell / 4, 6, c);
    }
    // hovered piece
    if (RM.hover >= 0 && pieces[RM.hover]) {
      const r = rectOf(pieces[RM.hover]);
      if (r) {
        ctx.strokeStyle = cssVar("--sel", "#e0a100");
        ctx.lineWidth = 2;
        ctx.strokeRect(ox + r[0] * cell - 1, oy + r[1] * cell - 1, r[2] * cell + 2, r[3] * cell + 2);
      }
    }
  }

  function onHover(e) {
    if (!RM.turned) return;
    const cvs = $("rmPlan");
    const rect = cvs.getBoundingClientRect();
    const cw = cvs.clientWidth, ch = cvs.clientHeight;
    const [w, h] = RM.turned.size || [1, 1];
    const {cell, ox, oy} = fitPlan(w, h, cw, ch, 26);
    const x = Math.floor((e.clientX - rect.left - ox) / cell);
    const y = Math.floor((e.clientY - rect.top - oy) / cell);
    const i = (x >= 0 && y >= 0 && x < w && y < h) ? pieceAt(RM.turned, x, y) : -1;
    RM.hover = i;
    drawPlan();
    const tip = $("rmTip");
    if (i < 0) { tip.hidden = true; return; }
    const p = RM.turned.pieces[i];
    const r = rectOf(p);
    const entry = RM.lookData && RM.lookData.look[i];
    tip.innerHTML =
      `<b>${esc(p.role || "?")}</b>${p.optional ? " · optional" : ""}<br>`
      + (p.group ? `${esc(p.group)}<br>` : "")
      + (r ? `${r[2]}×${r[3]}` : "")
      + (p.back ? ` · back ${esc(p.back)}` : "")
      + (RM.look ? `<br>${entry && entry.object ? "object " + esc(entry.object)
                                             : "no sprite in " + esc(RM.look)}` : "");
    tip.hidden = false;
    const wrap = cvs.parentElement;   // the canvas fills the wrap, so its coords are the wrap's
    tip.style.left = Math.max(4, Math.min(e.clientX - rect.left + 14,
                                           wrap.clientWidth - tip.offsetWidth - 6)) + "px";
    tip.style.top = Math.max(4, Math.min(e.clientY - rect.top + 12,
                                         wrap.clientHeight - tip.offsetHeight - 6)) + "px";
  }

  // ------------------------------------------------------------ details

  function renderDetails() {
    const box = $("rmDetails");
    if (!RM.room) { box.innerHTML = `<p class="hint">Pick a room on the left.</p>`; return; }
    const r = RM.room;
    const dt = (k, v) => v === undefined || v === null || v === "" ? "" : `<dt>${k}</dt><dd>${v}</dd>`;
    const sleeps = r.sleeps
      ? [r.sleeps.singles ? `${r.sleeps.singles} single${r.sleeps.singles === 1 ? "" : "s"}` : "",
         r.sleeps.couples ? `${r.sleeps.couples} couple${r.sleeps.couples === 1 ? "" : "s"}` : ""]
          .filter(Boolean).join(" · ") || "nobody" : "";
    const errs = r.errors || [];
    box.innerHTML =
      `<h3>${esc(r.id || "")}</h3>`
      + `<dl class="rm-facts">`
      + dt("Recipe", esc(r.recipe || ""))
      + dt("Size", r.size ? `${r.size[0]}×${r.size[1]}${r.sizeBand ? ` (${esc(r.sizeBand)})` : ""}` : "")
      + dt("Clearance", esc(r.clearance || ""))
      + dt("Style", esc(r.style || ""))
      + dt("Wealth", esc((r.wealth || []).join(" · ")))
      + dt("Sleeps", esc(sleeps))
      + dt("Symmetric", r.symmetric ? "yes" : "no")
      + dt("Outdoor", r.outdoor ? "yes" : "no")
      + dt("Family", esc(r.family || ""))
      + `</dl>`
      + (r.description ? `<p class="rm-desc">${esc(r.description)}</p>` : "")
      + (errs.length ? `<div class="rm-errs">${errs.map(m =>
          `<div class="problem error">${esc(m)}</div>`).join("")}</div>` : "");
  }

  // ------------------------------------------------------------ siblings

  function renderSiblings() {
    const box = $("rmSiblings");
    box.innerHTML = "";
    if (!RM.room || !RM.room.recipe) return;
    const sibs = RM.rooms.filter(r => r.recipe === RM.room.recipe);
    for (const r of sibs) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "rm-sib" + (r.id === RM.sel ? " on" : "");
      b.title = r.id;
      const cvs = document.createElement("canvas");
      b.appendChild(cvs);
      const small = document.createElement("small");
      small.textContent = `${r.clearance || ""} · ${r.style || ""}`;
      b.appendChild(small);
      b.onclick = () => { if (RM.sel !== r.id) { RM.sel = r.id; renderList(); loadRoom(); } };
      box.appendChild(b);
      drawMini(cvs, r);
    }
  }

  /** A small role-coloured plan on a fresh canvas (siblings, group cards). */
  function drawMini(cvs, room) {
    const pieces = (room.pieces || []).map(rectOf).filter(Boolean);
    const w = Math.max(1, ...pieces.map(r => r[0] + r[2]));
    const h = Math.max(1, ...pieces.map(r => r[1] + r[3]));
    const cell = Math.min(12, Math.max(3, Math.floor(Math.min(116 / w, 64 / h))));
    const dpr = window.devicePixelRatio || 1;
    cvs.width = Math.round(w * cell * dpr); cvs.height = Math.round(h * cell * dpr);
    cvs.style.width = w * cell + "px"; cvs.style.height = h * cell + "px";
    const ctx = cvs.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = cssVar("--bg", "#f4f3ef");
    ctx.fillRect(0, 0, w * cell, h * cell);
    for (const p of room.pieces || []) {
      const r = rectOf(p);
      if (!r) continue;
      const rgb = roleColor(RM.meta.roles, p.role);
      const px = r[0] * cell, py = r[1] * cell, PW = r[2] * cell, PH = r[3] * cell;
      ctx.fillStyle = rgb;
      ctx.fillRect(px, py, PW, PH);
      if (p.back) {
        const lw = Math.max(1, Math.round(cell / 5));
        ctx.fillStyle = darker(rgb, .45);
        if (p.back === "north") ctx.fillRect(px, py, PW, lw);
        else if (p.back === "south") ctx.fillRect(px, py + PH - lw, PW, lw);
        else if (p.back === "west") ctx.fillRect(px, py, lw, PH);
        else if (p.back === "east") ctx.fillRect(px + PW - lw, py, lw, PH);
      }
    }
  }

  // ------------------------------------------------------------ groups view

  function toggleGroups() {
    RM.groupsMode = !RM.groupsMode;
    $("rmGroupsBtn").classList.toggle("on", RM.groupsMode);
    $("rmGroupsBtn").setAttribute("aria-pressed", RM.groupsMode ? "true" : "false");
    $("rmToolbar").hidden = RM.groupsMode;
    $("rmPlan").parentElement.hidden = RM.groupsMode;
    $("rmSiblings").hidden = RM.groupsMode;
    $("rmGroupsPage").hidden = !RM.groupsMode;
    if (RM.groupsMode) renderGroups();
    else drawPlan();
  }

  async function renderGroups() {
    if (!RM.groupsCache[RM.family]) {
      try { RM.groupsCache[RM.family] = await api("/api/rooms/groups?family=" + encodeURIComponent(RM.family)); }
      catch (e) { toast(e.message); return; }
    }
    const d = RM.groupsCache[RM.family];
    const pageEl = $("rmGroupsPage");
    pageEl.innerHTML = "";
    const recipes = document.createElement("section");
    recipes.innerHTML = `<h3>Recipes — ${esc(RM.family)}</h3>`;
    for (const r of d.recipes || []) {
      const card = document.createElement("div");
      card.className = "rm-recipe";
      const bands = (r.sizeBands || []).map(b => `<span class="rm-kbadge">${esc(b)}</span>`).join("");
      card.innerHTML = `<div class="rm-rline"><b>${esc(r.layout || "")}</b>`
        + `<span class="kinds">${bands}</span>`
        + `<span class="note">${(r.groups || []).length} groups</span></div>`;
      const cards = document.createElement("div");
      cards.className = "rm-gcards";
      for (const e of r.groups || []) {
        const g = (d.groups || {})[e.group];
        const gc = document.createElement("div");
        gc.className = "rm-gcard";
        const badges = [`<span class="rm-kbadge">${esc(e.kind || "?")}</span>`
                        + (e.count !== undefined ? `<span class="rm-kbadge">×${esc(e.count)}</span>` : "")
                        + (e.minWealth ? `<span class="rm-kbadge">from ${esc(e.minWealth)}</span>` : "")].join("");
        gc.innerHTML = `<div class="kinds">${badges}</div><div class="gname">${esc(e.group)}</div>`;
        if (g) {
          const cvs = document.createElement("canvas");
          gc.insertBefore(cvs, gc.firstChild);
          drawMini(cvs, {pieces: g.pieces || []});
        }
        cards.appendChild(gc);
      }
      card.appendChild(cards);
      recipes.appendChild(card);
    }
    pageEl.appendChild(recipes);
    const pool = document.createElement("section");
    pool.innerHTML = `<h3>Luxury pool — ${esc(RM.family)}</h3>`;
    for (const e of d.pool || []) {
      const line = document.createElement("div");
      line.className = "rm-poolline";
      line.innerHTML = `<span class="gname">${esc(e.group || "")}</span>`
        + (e.kind || []).map(k => `<span class="rm-kbadge luxury">${esc(k)}</span>`).join("")
        + (e.bands || []).map(b => `<span class="rm-kbadge">${esc(b)}</span>`).join("");
      pool.appendChild(line);
    }
    if (!(d.pool || []).length) pool.innerHTML += `<p class="note">No luxury groups for this family.</p>`;
    pageEl.appendChild(pool);
  }

  return {roleColor, darker, shortRole, filterRooms, fitPlan, doorCells, stretchLines,
          groupBoxes, pieceAt, rectOf};
});
