"use strict";
// The Rooms tab: browse the generator's fixed-room library (rl-04a) and work
// rooms by hand (rl-04b) — edit flags in the details panel, lay a room out
// by dragging whole groups, duplicate or new rooms, and regenerate one room
// or a whole family. The plan canvas, list, filters, look sprites and the
// groups page live here; every fetch goes to rooms_editor.py's /api/rooms/*
// endpoints, which check before they write (a family is saved only when it
// passes fixed_rooms.check; layout edits are never saved while they fail).
// Pure helpers (no DOM) are exported for node --test; the page wiring at the
// bottom runs only in a browser. Plan coordinates match the stored rooms:
// [0,0] is the north-west cell, x grows east, y grows south.

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

  /** The short label for a role on the plan: its most telling word — the
   * first ("sleep.couple" -> "sleep"), but the last for washroom fixtures
   * ("wash.toilet" -> "toilet"; they would all read "wash") and wherever
   * another, different role in the same room shares the first word
   * ("storage.big" beside "storage.small" -> "big"). The same rule as
   * worldgen/room_palette.py's short_role, which the room sheets use. */
  function shortRole(role, roles) {
    role = String(role || "");
    const words = role.split(".");
    const last = words[words.length - 1];
    if (words.length > 1 && words[0] === "wash") return last;
    if (roles !== undefined && roles !== null) {
      const first = words[0];
      for (const other of new Set(roles))
        if (other !== role && String(other || "").split(".")[0] === first)
          return last;
    }
    return words[0];
  }

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

  // ------------------------------------------------------------ hand work

  const LETTERS = "abcdefghijklmnopqrstuvwxyz";
  // the fields a person may set by hand (fixed_rooms.EDITABLE_FIELDS)
  const EDITABLE = ["wealth", "description", "symmetric", "retired"];
  // which side a piece's back faces after one clockwise quarter turn
  // (fixed_rooms.TURN); the server's fixed_rooms.rotate stays the only full
  // room turn — this map just turns one group's backs in the layout editor
  const TURN_SIDES = {north: "east", east: "south", south: "west", west: "north"};

  function deep(obj) { return JSON.parse(JSON.stringify(obj)); }

  /** A room id's letter — its bit after the family parts and the band
   * ("bedroom.master.small.a.tight.flush" with 2 family parts -> "a"), or
   * null when the id is not shaped that way. */
  function letterAt(id, nparts) {
    const bits = String(id || "").split(".");
    if (bits.length !== nparts + 4) return null;
    return bits[nparts + 1];
  }

  /** The first letter of LETTERS not already used. */
  function nextLetter(used) {
    const taken = new Set(used || []);
    for (const c of LETTERS) if (!taken.has(c)) return c;
    return null;
  }

  /** The next free id of a family's band, clearance and style, given the
   * family's room ids (a hand room never reuses a shipped letter). */
  function newId(family, band, clearance, style, ids) {
    const nparts = String(family || "").split(".").length;
    const used = (ids || []).filter(id => {
      const bits = String(id || "").split(".");
      return bits.length === nparts + 4 && bits.slice(0, nparts).join(".") === family
        && bits[nparts] === band && bits[nparts + 2] === clearance
        && bits[nparts + 3] === style;
    }).map(id => letterAt(id, nparts));
    const ch = nextLetter(used);
    return ch ? `${family}.${band}.${ch}.${clearance}.${style}` : null;
  }

  /** A hand copy of a room under a new id: everything carried over as it
   * stands (its edited flags too — the values came with it), the source
   * marked "hand" so regeneration never touches it again. */
  function cloneRoom(room, id) {
    const copy = deep(room);
    copy.id = id;
    copy.source = "hand";
    delete copy.errors;
    return copy;
  }

  /** The group instance gi turned a clockwise quarter about its own box
   * (backs turn with it); the turned box keeps its north-west corner, so a
   * non-square group may now reach past the room — the live checker says
   * so and the user drags it back. */
  function turnGroup(room, gi) {
    const out = deep(room);
    const groups = groupBoxes(out);
    const g = groups[gi];
    if (!g) return out;
    const [bx, by, bw, bh] = g.box;
    for (const i of g.indices) {
      const p = out.pieces[i];
      const [x, y, pw, ph] = rectOf(p);
      p.at = [bx + (bh - (y - by) - ph), by + (x - bx)];
      p.size = [ph, pw];
      if (p.back) p.back = TURN_SIDES[p.back] || p.back;
    }
    return out;
  }

  /** The group instance gi shifted whole by (dx, dy) cells. */
  function moveGroup(room, gi, dx, dy) {
    const out = deep(room);
    const g = groupBoxes(out)[gi];
    if (!g) return out;
    for (const i of g.indices) {
      const p = out.pieces[i];
      p.at = [p.at[0] + dx, p.at[1] + dy];
    }
    return out;
  }

  /** The room without the group instance gi's pieces. */
  function removeGroup(room, gi) {
    const out = deep(room);
    const g = groupBoxes(out)[gi];
    if (!g) return out;
    out.pieces = out.pieces.filter((_, i) => !g.indices.includes(i));
    return out;
  }

  /** A group definition's pieces in minimal integer form: shifted so the
   * top-left piece cell is [0, 0], sizes and backs kept. */
  function groupForm(def) {
    const pieces = ((def || {}).pieces || []).map(rectOf).filter(Boolean);
    if (!pieces.length) return [];
    const x0 = Math.min(...pieces.map(r => r[0])), y0 = Math.min(...pieces.map(r => r[1]));
    return deep(((def || {}).pieces) || []).map(p => {
      const q = {role: p.role, size: [...(p.size || [1, 1])],
                 at: [(p.at || [0, 0])[0] - x0, (p.at || [0, 0])[1] - y0]};
      if (p.back) q.back = p.back;
      if (p.optional) q.optional = true;
      return q;
    });
  }

  /** The room with a group definition's pieces placed (top-left at [x, y]),
   * their group id stamped on. */
  function addGroup(room, def, x, y) {
    const out = deep(room);
    const gid = def.id || def.group;
    for (const p of groupForm(def))
      out.pieces.push(Object.assign({}, p,
                                    {group: gid, at: [p.at[0] + (x || 0), p.at[1] + (y || 0)]}));
    return out;
  }

  /** The room grown by n lines on one side: wall-bound groups ride their
   * walls out (the composer's own _grown rule), everything else shifts with
   * the far wall, and the filler moves with the middle. */
  function growRoom(room, side, n) {
    const out = deep(room);
    const axis = side === "north" || side === "south" ? 1 : 0;
    out.size[axis] += n;
    const shift = side === "north" || side === "west";
    if (shift) {
      for (const p of out.pieces || []) {
        const rides = p.back === side && p.at[axis] === 0;
        if (!rides) p.at[axis] += n;
      }
      if (out.filler && out.filler.at) out.filler.at[axis] += n;
    }
    return out;
  }

  /** The room shrunk by n lines on one side, or null when a piece or the
   * filler stands on the lines that would go. */
  function shrinkRoom(room, side, n) {
    const [w, h] = (room || {}).size || [1, 1];
    const axis = side === "north" || side === "south" ? 1 : 0;
    if ((room.size || [1, 1])[axis] - n < 1) return null;
    for (const p of (room || {}).pieces || []) {
      const r = rectOf(p);
      if (!r) continue;
      if (side === "north" && r[1] < n) return null;
      if (side === "south" && r[1] + r[3] > h - n) return null;
      if (side === "west" && r[0] < n) return null;
      if (side === "east" && r[0] + r[2] > w - n) return null;
    }
    const f = (room || {}).filler;
    if (f && f.at && f.size) {
      if (side === "north" && f.at[1] < n) return null;
      if (side === "south" && f.at[1] + f.size[1] > h - n) return null;
      if (side === "west" && f.at[0] < n) return null;
      if (side === "east" && f.at[0] + f.size[0] > w - n) return null;
    }
    const out = deep(room);
    out.size[axis] -= n;
    const shift = side === "north" || side === "west";
    if (shift) {
      for (const p of out.pieces || []) p.at[axis] -= n;
      if (out.filler && out.filler.at) out.filler.at[axis] -= n;
    }
    return out;
  }

  /** The room re-laid out from a regeneration candidate: the layout fields
   * come from the candidate, the identity stays, and the fields in the
   * room's edited list keep their hand values (the generator's own rule for
   * surviving rooms). The room is marked source "hand" from here on. */
  function mergeLayout(room, cand) {
    const out = deep(room);
    const edited = new Set(out.edited || []);
    for (const k of ["size", "sizeBand", "sleeps", "pieces", "doors", "stretch"]) {
      if (cand[k] !== undefined) out[k] = deep(cand[k]);
      else delete out[k];
    }
    if (cand.filler) out.filler = deep(cand.filler);
    else delete out.filler;
    for (const k of EDITABLE)
      if (!edited.has(k) && cand[k] !== undefined) out[k] = deep(cand[k]);
    out.source = "hand";
    delete out.errors;
    return out;
  }

  /** Set one hand field and flag it edited. */
  function setField(room, field, value) {
    room[field] = value;
    if (!(room.edited || []).includes(field)) room.edited = [...(room.edited || []), field];
    return room;
  }

  /** Drop a field's hand flag: the value itself stands until the family is
   * next regenerated. */
  function resetField(room, field) {
    room.edited = (room.edited || []).filter(f => f !== field);
    if (!room.edited.length) delete room.edited;
    return room;
  }

  /** The checker messages' offending cells, to outline on the plan: dead
   * floor ("first at x,y"), blocked or cut-off door cells, a piece nobody
   * can reach ("piece 'role' at [x, y]"), the filler ("filler at [x, y]")
   * and stretch lines that break. Only cells inside the room are kept. */
  function parseCells(room, msgs) {
    const [w, h] = ((room || {}).size) || [0, 0];
    const cells = new Set();
    const add = (x, y) => { if (x >= 0 && y >= 0 && x < w && y < h) cells.add(x + "," + y); };
    for (const m of msgs || []) {
      let mm;
      if ((mm = /\(first at (\d+),(\d+)\)/.exec(m))) add(+mm[1], +mm[2]);
      if ((mm = /door cell (north|south|east|west) (\d+)/.exec(m))) {
        const k = +mm[2];
        if (mm[1] === "north") add(k, 0);
        else if (mm[1] === "south") add(k, h - 1);
        else if (mm[1] === "west") add(0, k);
        else add(w - 1, k);
      }
      if ((mm = /piece '[^']*' at \[(\d+), (\d+)\]/.exec(m))) {
        const p = (room.pieces || []).find(q => {
          const r = rectOf(q);
          return r && r[0] === +mm[1] && r[1] === +mm[2];
        });
        const r = p && rectOf(p);
        if (r) for (let x = r[0]; x < r[0] + r[2]; x++) for (let y = r[1]; y < r[1] + r[3]; y++) add(x, y);
      }
      if ((mm = /filler at \[(\d+), (\d+)\]/.exec(m)) && room.filler && room.filler.size) {
        for (let x = +mm[1]; x < +mm[1] + room.filler.size[0]; x++)
          for (let y = +mm[2]; y < +mm[2] + room.filler.size[1]; y++) add(x, y);
      }
      if ((mm = /stretch ([xy]) (\d+)/.exec(m))) {
        if (mm[1] === "x") for (let y = 0; y < h; y++) add(+mm[2], y);
        else for (let x = 0; x < w; x++) add(x, +mm[2]);
      }
    }
    return [...cells].map(s => s.split(",").map(Number));
  }

  /** The group ids a person may take out of a room of this recipe: the
   * recipe's optional groups and the family's luxury pool (an anchor,
   * required or repeatable group is the recipe's business). */
  function removableGids(room, groupsData) {
    const data = groupsData || {};
    const recipe = (data.recipes || []).find(r => r.layout === (room || {}).recipe);
    const out = new Set();
    for (const e of (recipe && recipe.groups) || [])
      if (e.kind === "optional") out.add(e.group);
    for (const e of data.pool || []) out.add(e.group);
    return out;
  }

  /** A room's group ids, each once. */
  function groupGids(room) {
    return [...new Set(((room || {}).pieces || []).map(p => p && p.group).filter(Boolean))];
  }

  /** The add-group dialog's sections, in order: the groups this room has
   * lost since editing began (the first place to look — putting one back),
   * the recipe's groups of any kind, the family's luxury pool, and every
   * other group in the library. A group shows in the first section it fits
   * and only there; each row carries the file the group lives in. Empty
   * sections are left out. `startRoom` is the room as editing began (the
   * stored room), `room` the draft being laid out. */
  function addGroupSections(all, room, startRoom, groupsData) {
    const data = groupsData || {};
    const now = new Set(groupGids(room)), then = new Set(groupGids(startRoom));
    const recipe = (data.recipes || []).find(r => r.layout === (room || {}).recipe);
    const info = new Map((all || []).map(g => [g.id, {gid: g.id, file: g.file,
                                                      pieces: g.pieces || []}]));
    const sections = [];
    const seen = new Set();
    const take = (title, gids) => {
      const rows = [];
      for (const gid of gids)
        if (info.has(gid) && !seen.has(gid)) { seen.add(gid); rows.push(info.get(gid)); }
      if (rows.length) sections.push({title, rows});
    };
    take("Removed from this room",
         [...info.keys()].filter(gid => then.has(gid) && !now.has(gid)));
    take("The recipe's groups",
         (((recipe && recipe.groups) || []).map(e => e.group)).filter(Boolean));
    take("The family's luxury pool",
         ((data.pool || []).map(e => e.group)).filter(Boolean));
    take("All other groups", [...info.keys()]);
    return sections;
  }

  /** The rows the add-group dialog's search keeps: the id or any piece
   * role matches, case-insensitively. */
  function filterGroupRows(rows, q) {
    q = String(q || "").trim().toLowerCase();
    if (!q) return rows || [];
    return (rows || []).filter(r =>
      String(r.gid || "").toLowerCase().includes(q)
      || (r.pieces || []).some(p => String(p.role || "").toLowerCase().includes(q)));
  }

  /** The first free spot a group definition fits in: the first cell in
   * reading order where every piece lands inside the room on cells no
   * piece stands on, or null when no spot fits (the group then lands in
   * the top-left corner as before and the live checker shows the
   * overlap). */
  function firstFreeSpot(room, def) {
    const pieces = groupForm(def);
    if (!pieces.length) return null;
    const [w, h] = ((room || {}).size) || [0, 0];
    const gw = Math.max(...pieces.map(p => p.at[0] + p.size[0]));
    const gh = Math.max(...pieces.map(p => p.at[1] + p.size[1]));
    const taken = [];
    for (const p of (room || {}).pieces || []) { const r = rectOf(p); if (r) taken.push(r); }
    const over = (x, y) => pieces.some(p => taken.some(r =>
      r[0] < x + p.at[0] + p.size[0] && x + p.at[0] < r[0] + r[2]
      && r[1] < y + p.at[1] + p.size[1] && y + p.at[1] < r[1] + r[3]));
    for (let y = 0; y + gh <= h; y++)
      for (let x = 0; x + gw <= w; x++)
        if (!over(x, y)) return [x, y];
    return null;
  }

  /** Whether one of a room's layout fields differs between two states of
   * the same room — any such edit is hand work: the room is marked source
   * "hand" so a family regeneration keeps it as it stands. */
  function layoutChanged(a, b) {
    const pick = r => ["size", "pieces", "doors", "stretch", "filler"]
      .map(k => JSON.stringify((r || {})[k] === undefined ? null : (r || {})[k])).join("|");
    return pick(a) !== pick(b);
  }

  // ------------------------------------------------------------ page wiring

  const RM = {meta: null, inited: false, family: "", rooms: [], familyErrors: [],
              hash: "", dirty: false, edit: null, actions: null,
              view: [], sel: null, room: null, turned: null, turn: 0, mirror: 0,
              look: "", lookData: null, sprites: new Map(), groupsMode: false,
              groupsCache: {}, allCache: null, recipeEdits: {}, hover: -1, seq: 0,
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
    $("rmFamily").onchange = async () => {
      const next = $("rmFamily").value;
      if (next === RM.family) return;
      if (!await guardDirty()) { $("rmFamily").value = RM.family; return; }
      if (RM.edit) endEdit(false);
      RM.family = next;
      RM.filters.band = "";
      loadFamily();
    };
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
    plan.onmousedown = onPlanDown;
    plan.onmouseleave = () => { RM.hover = -1; $("rmTip").hidden = true; drawPlan(); };
    document.addEventListener("mousemove", onPlanMove);
    document.addEventListener("mouseup", onPlanUp);
    if (typeof ResizeObserver !== "undefined")
      new ResizeObserver(() => drawPlan()).observe(plan.parentElement);
    window.addEventListener("resize", drawPlan);
    buildActions();
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
      RM.hash = d.hash || "";
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
          `<button type="button" class="rm-row${r.id === RM.sel ? " on" : ""}${r.retired ? " rm-isretired" : ""}" data-id="${esc(r.id)}" title="${esc(r.id)}">`
          + `<span class="id">${esc(r.id)}</span>`
          + `<span class="meta">${r.size ? r.size[0] + "×" + r.size[1] : "?"} · ${(r.pieces || []).length}`
          + (r.source === "hand" ? ` · <span class="rm-hand" title="laid out or edited by hand; regeneration keeps it as it is">hand</span>` : "")
          + (r.retired ? ` · <span class="rm-retired" title="retired: skipped by world generation, its id never reused">retired</span>` : "")
          + `</span>`
          + ((r.errors || []).length ? `<span class="bad" title="${(r.errors || []).length} checker message${(r.errors || []).length === 1 ? "" : "s"}">!</span>` : "")
          + `</button>`).join("")
        : `<p class="rm-norooms">No rooms match these filters.</p>`);
    for (const b of box.querySelectorAll(".rm-row"))
      b.onclick = () => { if (RM.sel !== b.dataset.id) { RM.sel = b.dataset.id; renderList(); loadRoom(); } };
  }

  async function loadRoom() {
    syncToolbar();
    syncActions();
    if (!RM.sel) {
      RM.room = RM.turned = RM.lookData = null;
      drawPlan(); renderDetails(); renderSiblings();
      return;
    }
    // unturned and unmirrored, the page's own copy is the room to draw —
    // it may hold unsaved hand work the server has not seen yet
    if (!RM.turn && !RM.mirror && !RM.edit) {
      RM.room = RM.rooms.find(r => r.id === RM.sel) || null;
      RM.turned = RM.room;
      RM.lookData = null;
      if (RM.look && !RM.dirty) await fetchLook();
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
      if (RM.look && !RM.dirty) {
        const lk = await api(`/api/rooms/look?${qs}&band=${encodeURIComponent(RM.look)}`);
        if (seq !== RM.seq) return;
        RM.lookData = lk;
        for (const e of lk.look || []) if (e) spriteImg(e.object);
      }
      drawPlan(); renderDetails(); renderSiblings();
    } catch (e) { toast(e.message); }
  }

  async function fetchLook() {
    const seq = RM.seq;
    const qs = `id=${encodeURIComponent(RM.sel)}&turn=0&mirror=0`;
    try {
      const lk = await api(`/api/rooms/look?${qs}&band=${encodeURIComponent(RM.look)}`);
      if (seq !== RM.seq || RM.sel !== lk.room) return;
      RM.lookData = lk;
      for (const e of lk.look || []) if (e) spriteImg(e.object);
      drawPlan();
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
    // the preview turn applies to the stored room, so it stays off while a
    // layout is being edited
    for (const id of ["rmTurnL", "rmTurnR", "rmMirror"]) $(id).disabled = !RM.sel || !!RM.edit;
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
    const room = RM.edit ? RM.edit.room : RM.turned;
    if (!room) return;
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
    const pieceRoles = pieces.map(p => p.role);
    const look = (RM.lookData && !RM.edit && RM.lookData.look) || [];
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
        ctx.fillText(shortRole(p.role, pieceRoles), px + PW / 2, py + PH / 2);
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
    // the layout editor: offending cells the checker named, outlined red,
    // and the selected group picked out
    if (RM.edit) {
      ctx.strokeStyle = "#c92a2a";
      ctx.lineWidth = 2;
      for (const c of RM.edit.cells) {
        ctx.strokeRect(ox + c[0] * cell + .5, oy + c[1] * cell + .5, cell - 1, cell - 1);
      }
      const g = RM.edit.sel >= 0 ? groupBoxes(room)[RM.edit.sel] : null;
      if (g) {
        ctx.strokeStyle = cssVar("--sel", "#e0a100");
        ctx.lineWidth = 2.5;
        ctx.strokeRect(ox + g.box[0] * cell - 2, oy + g.box[1] * cell - 2,
                       g.box[2] * cell + 4, g.box[3] * cell + 4);
      }
    }
  }

  /** The plan cell under an event, or null off the room. */
  function planCell(e) {
    const room = RM.edit ? RM.edit.room : RM.turned;
    if (!room) return null;
    const cvs = $("rmPlan");
    const rect = cvs.getBoundingClientRect();
    const cw = cvs.clientWidth, ch = cvs.clientHeight;
    const [w, h] = room.size || [1, 1];
    const {cell, ox, oy} = fitPlan(w, h, cw, ch, 26);
    const x = Math.floor((e.clientX - rect.left - ox) / cell);
    const y = Math.floor((e.clientY - rect.top - oy) / cell);
    return (x >= 0 && y >= 0 && x < w && y < h) ? {x, y} : null;
  }

  function onHover(e) {
    if (RM.edit && RM.edit.drag) return;
    const room = RM.edit ? RM.edit.room : RM.turned;
    if (!room) return;
    const c = planCell(e);
    const i = c ? pieceAt(room, c.x, c.y) : -1;
    RM.hover = i;
    drawPlan();
    const tip = $("rmTip");
    if (i < 0) { tip.hidden = true; return; }
    const p = room.pieces[i];
    const r = rectOf(p);
    const entry = RM.lookData && !RM.edit && RM.lookData.look[i];
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
    if (!RM.room && !RM.edit) { box.innerHTML = `<p class="hint">Pick a room on the left.</p>`; return; }
    const r = RM.edit ? RM.edit.room : RM.room;
    if (!r) { box.innerHTML = `<p class="hint">Pick a room on the left.</p>`; return; }
    const dt = (k, v) => v === undefined || v === null || v === "" ? "" : `<dt>${k}</dt><dd>${v}</dd>`;
    const sleeps = r.sleeps
      ? [r.sleeps.singles ? `${r.sleeps.singles} single${r.sleeps.singles === 1 ? "" : "s"}` : "",
         r.sleeps.couples ? `${r.sleeps.couples} couple${r.sleeps.couples === 1 ? "" : "s"}` : ""]
          .filter(Boolean).join(" · ") || "nobody" : "";
    const edited = r.edited || [];
    const reset = field => edited.includes(field)
      ? `<button type="button" class="linkish rm-reset" data-reset="${field}" `
        + `title="Drop the hand flag: the generated value returns at the next regeneration">reset</button>`
      : `<span class="rm-reset-off" title="not hand-set"></span>`;
    const errs = RM.edit ? RM.edit.errors : (r.errors || []);
    box.innerHTML =
      `<h3>${esc(r.id || "")}</h3>`
      + `<p class="rm-flags">`
      + (r.source === "hand" ? `<span class="rm-hand" title="laid out or edited by hand; regeneration keeps it as it is">hand</span>` : "")
      + (r.retired ? ` <span class="rm-retired" title="retired: skipped by world generation, its id never reused">retired</span>` : "")
      + (edited.length ? ` <span class="rm-editflag" title="hand-set fields kept on regeneration: ${esc(edited.join(", "))}">edited: ${esc(edited.join(", "))}</span>` : "")
      + `</p>`
      + `<dl class="rm-facts">`
      + dt("Recipe", esc(r.recipe || ""))
      + dt("Size", r.size ? `${r.size[0]}×${r.size[1]}${r.sizeBand ? ` (${esc(r.sizeBand)})` : ""}` : "")
      + dt("Clearance", esc(r.clearance || ""))
      + dt("Style", esc(r.style || ""))
      + dt("Sleeps", esc(sleeps))
      + dt("Outdoor", r.outdoor ? "yes" : "no")
      + dt("Family", esc(r.family || ""))
      + `</dl>`
      + `<div class="rm-editfields">`
      + `<div class="rm-field"><span class="k">Wealth ${reset("wealth")}</span><span class="v">`
      + (RM.meta.tiers || []).map(t =>
          `<label class="inline"><input type="checkbox" data-tier="${esc(t)}"${(r.wealth || []).includes(t) ? " checked" : ""}>${esc(t)}</label>`).join("")
      + `</span></div>`
      + `<div class="rm-field"><span class="k">Description ${reset("description")}</span><span class="v">`
      + `<textarea data-fld="description" rows="3" spellcheck="false">${esc(r.description || "")}</textarea>`
      + `</span></div>`
      + `<div class="rm-field"><span class="k">Symmetric ${reset("symmetric")}</span><span class="v">`
      + `<label class="inline"><input type="checkbox" data-flag="symmetric"${r.symmetric ? " checked" : ""}> pieces mirror across a centre line</label>`
      + `</span></div>`
      + `<div class="rm-field"><span class="k">Retired ${reset("retired")}</span><span class="v">`
      + `<label class="inline"><input type="checkbox" data-flag="retired"${r.retired ? " checked" : ""}> keep the id, skip the room in world generation</label>`
      + `</span></div>`
      + `</div>`
      + (errs.length ? `<div class="rm-errs">${errs.map(m =>
          `<div class="problem error">${esc(m)}</div>`).join("")}</div>`
        : (RM.edit ? `<p class="note">This layout passes the checker.</p>` : ""))
      + (RM.edit && RM.edit.drag ? `<p class="note">Dragging…</p>` : "");
    wireDetails(r);
  }

  /** The details panel's own inputs: wealth tick boxes, the description,
   * the symmetric and retired flags, and each field's reset link. */
  function wireDetails(r) {
    const box = $("rmDetails");
    for (const cb of box.querySelectorAll("[data-tier]")) {
      cb.onchange = () => {
        const tiers = [...box.querySelectorAll("[data-tier]")].filter(c => c.checked)
          .map(c => c.dataset.tier);
        setField(r, "wealth", tiers);
        markDirty();
        if (RM.edit) checkSoon();
      };
    }
    const ta = box.querySelector('[data-fld="description"]');
    if (ta) ta.onchange = () => {
      setField(r, "description", ta.value);
      markDirty();
      if (RM.edit) checkSoon();
    };
    for (const cb of box.querySelectorAll("[data-flag]")) {
      cb.onchange = () => {
        setField(r, cb.dataset.flag, cb.checked);
        markDirty();
        renderList();
        if (RM.edit) checkSoon();
      };
    }
    for (const b of box.querySelectorAll("[data-reset]")) {
      b.onclick = () => {
        resetField(r, b.dataset.reset);
        markDirty();
        renderDetails();
      };
    }
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

  /** A small role-coloured plan on a fresh canvas (siblings, group cards).
   * A group's own wall shows too: "back" is the thick north edge of the
   * whole group, "corner" the north and west edges. */
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
    if (room.wall === "back" || room.wall === "corner") {
      const lw = Math.max(2, Math.round(cell / 3));
      ctx.fillStyle = cssVar("--ink", "#3a3934");
      ctx.fillRect(0, 0, w * cell, lw);
      if (room.wall === "corner") ctx.fillRect(0, 0, lw, h * cell);
    }
  }

  // ------------------------------------------------------------ groups view

  function toggleGroups() {
    RM.groupsMode = !RM.groupsMode;
    $("rmGroupsBtn").classList.toggle("on", RM.groupsMode);
    $("rmGroupsBtn").setAttribute("aria-pressed", RM.groupsMode ? "true" : "false");
    $("rmToolbar").hidden = RM.groupsMode;
    if (RM.actions) RM.actions.hidden = RM.groupsMode;
    $("rmPlan").parentElement.hidden = RM.groupsMode;
    $("rmSiblings").hidden = RM.groupsMode;
    $("rmGroupsPage").hidden = !RM.groupsMode;
    if (RM.groupsMode) renderGroups();
    else drawPlan();
  }

  async function renderGroups() {
    const d = await groupsData();
    if (!d) return;
    const pageEl = $("rmGroupsPage");
    pageEl.innerHTML = "";
    const head = document.createElement("div");
    head.className = "rm-ghead";
    head.innerHTML = `<button type="button" data-a="new" title="A group written by hand into one of the group files; the converter keeps it">New group…</button>`;
    head.querySelector('[data-a="new"]').onclick = newGroupDialog;
    pageEl.appendChild(head);
    const recipes = document.createElement("section");
    recipes.innerHTML = `<h3>Recipes — ${esc(RM.family)}</h3>`;
    for (const r0 of d.recipes || []) {
      const r = RM.recipeEdits[r0.layout] || r0;
      const card = document.createElement("div");
      card.className = "rm-recipe";
      const bands = (r.sizeBands || []).map(b => `<span class="rm-kbadge">${esc(b)}</span>`).join("");
      card.innerHTML = `<div class="rm-rline"><b>${esc(r.layout || "")}</b>`
        + `<span class="kinds">${bands}</span>`
        + (r.source === "hand" ? `<span class="rm-hand" title="changed by hand; the converter keeps this recipe as it is">hand</span>` : "")
        + `<span class="note">${(r.groups || []).length} groups</span></div>`;
      const cards = document.createElement("div");
      cards.className = "rm-gcards";
      (r.groups || []).forEach((e, i) => {
        const g = (d.groups || {})[e.group];
        const gc = document.createElement("div");
        gc.className = "rm-gcard";
        gc.title = "Edit this group";
        const badges = [`<span class="rm-kbadge">${esc(e.kind || "?")}</span>`
                        + (e.count !== undefined ? `<span class="rm-kbadge">×${esc(e.count)}</span>` : "")
                        + (e.minWealth ? `<span class="rm-kbadge">from ${esc(e.minWealth)}</span>` : "")
                        + (e.source === "hand" ? `<span class="rm-kbadge hand">hand</span>` : "")].join("");
        gc.innerHTML = `<div class="kinds">${badges}</div><div class="gname">${esc(e.group)}</div>`;
        if (g) {
          const cvs = document.createElement("canvas");
          gc.insertBefore(cvs, gc.firstChild);
          drawMini(cvs, {pieces: g.pieces || [], wall: g.wall});
        }
        gc.onclick = () => openGroupEditor(e.group);
        if (e.kind !== "anchor") {
          const del = document.createElement("button");
          del.type = "button";
          del.className = "rm-x";
          del.title = "Take this group out of the recipe (the anchor stays)";
          del.textContent = "✕";
          del.onclick = ev => { ev.stopPropagation(); removeRecipeEntry(r0, i); };
          gc.appendChild(del);
        }
        cards.appendChild(gc);
      });
      const add = document.createElement("button");
      add.type = "button";
      add.className = "rm-gcard rm-gadd";
      add.textContent = "+ Add group";
      add.title = "Add any group in the library to this recipe";
      add.onclick = () => addRecipeEntryDialog(r0);
      cards.appendChild(add);
      card.appendChild(cards);
      if (RM.recipeEdits[r0.layout]) {
        const bar = document.createElement("div");
        bar.className = "rm-rsave";
        bar.innerHTML = `<span class="note">unsaved</span>`
          + `<button type="button" class="primary" data-a="save">Save recipe</button>`
          + `<button type="button" data-a="undo">Discard</button>`;
        bar.querySelector('[data-a="save"]').onclick = () => saveRecipe(r0.layout);
        bar.querySelector('[data-a="undo"]').onclick = () => {
          delete RM.recipeEdits[r0.layout];
          renderGroups();
        };
        card.appendChild(bar);
      }
      recipes.appendChild(card);
    }
    pageEl.appendChild(recipes);
    const pool = document.createElement("section");
    pool.innerHTML = `<h3>Luxury pool — ${esc(RM.family)}</h3>`;
    for (const e of d.pool || []) {
      const line = document.createElement("div");
      line.className = "rm-poolline";
      line.title = "Edit this group";
      line.innerHTML = `<span class="gname">${esc(e.group || "")}</span>`
        + (e.kind || []).map(k => `<span class="rm-kbadge luxury">${esc(k)}</span>`).join("")
        + (e.bands || []).map(b => `<span class="rm-kbadge">${esc(b)}</span>`).join("");
      line.onclick = () => openGroupEditor(e.group);
      pool.appendChild(line);
    }
    if (!(d.pool || []).length) pool.innerHTML += `<p class="note">No luxury groups for this family.</p>`;
    pageEl.appendChild(pool);
  }

  /** Edit one recipe in the page: the first change forks the recipe into
   * RM.recipeEdits, the cards render the draft, and Save writes it. */
  function withRecipeDraft(r0, fn) {
    const draft = RM.recipeEdits[r0.layout] || (RM.recipeEdits[r0.layout] = deep(r0));
    fn(draft);
    renderGroups();
  }

  /** An entry taken out: the recipe's own hand work, so the whole recipe
   * is marked "hand" — the converter cannot put the entry back. */
  function removeRecipeEntry(r0, i) {
    if (((r0.groups || [])[i] || {}).kind === "anchor")
      return toast("the recipe's anchor group stays");
    withRecipeDraft(r0, d => {
      d.groups.splice(i, 1);
      d.source = "hand";
    });
  }

  /** An entry put in: any group in the library, optional or required. Only
   * the entry is marked "hand" — the recipe stays the converter's. */
  async function addRecipeEntryDialog(r0) {
    const all = await allGroupsData();
    if (!all) return;
    const gid = await pickGroupDialog([{title: "Every group",
                                        rows: all.map(g => ({gid: g.id, file: g.file,
                                                             pieces: g.pieces || []}))}]);
    if (!gid) return;
    const kind = await openDialog(`Add ${gid}`,
      `<p>What kind of entry in <b>${esc(r0.layout)}</b>?</p>`,
      [{label: "Optional", value: "optional", primary: true},
       {label: "Required", value: "required"}]);
    if (!kind) return;
    withRecipeDraft(r0, d => {
      d.groups = [...(d.groups || []),
                  {group: gid, kind, count: 1, source: "hand"}];
    });
  }

  async function saveRecipe(layout) {
    const draft = RM.recipeEdits[layout];
    const d = await groupsData();
    if (!draft || !d) return;
    try {
      const out = await api("/api/rooms/recipe/save", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({recipe: draft, hash: (d.hashes || {})[draft.file]})});
      delete RM.recipeEdits[layout];
      invalidateGroupCaches();
      toast(`Recipe ${layout} saved into ${out.file} — the previous file is in library/groups/.backup`);
      renderGroups();
    } catch (e) { toast(e.message); }
  }

  // ---------------------------------------------------------- group editor

  /** A new group, empty or as a copy of one in the library. */
  async function newGroupDialog() {
    const choice = await openDialog("New group",
      `<p>A group written by hand into one of the group files — the converter keeps it as it is.</p>`,
      [{label: "Empty", value: "empty", primary: true},
       {label: "Copy a group…", value: "copy"}]);
    if (choice === "empty") return groupEditorDialog({isNew: true, group: null});
    if (choice !== "copy") return;
    const all = await allGroupsData();
    if (!all) return;
    const gid = await pickGroupDialog([{title: "Copy which group?",
                                        rows: all.map(g => ({gid: g.id, file: g.file,
                                                             pieces: g.pieces || []}))}]);
    if (!gid) return;
    let g;
    try { g = await api("/api/rooms/group?id=" + encodeURIComponent(gid)); }
    catch (e) { return toast(e.message); }
    groupEditorDialog({isNew: true, group: g, copyOf: gid});
  }

  async function openGroupEditor(gid) {
    let g;
    try { g = await api("/api/rooms/group?id=" + encodeURIComponent(gid)); }
    catch (e) { return toast(e.message); }
    groupEditorDialog({isNew: false, group: g});
  }

  /** The group editor: a modal over the groups view. The group's pieces
   * with their roles, sizes, backs and wealth floors; the wall; the luxury
   * kind; a new group's id, file and pool entries. The group checker runs
   * live — a draft with errors cannot be saved — and saving writes the
   * file it lives in (the previous copy in .backup), leaving the stored
   * rooms untouched but listing them. */
  async function groupEditorDialog(state) {
    const dlg = $("dlg");
    const from = state.group;
    const isNew = state.isNew;
    const file0 = isNew ? (from ? from.file : RM.family + ".json") : from.file;
    const group = deep(from || {});
    delete group.errors;
    for (const k of ["file", "hash", "recipes", "pools", "rooms", "usedBy"]) delete group[k];
    if (isNew) {
      delete group.id;
      delete group.source;
    }
    const st = {group, file: file0, isNew, hash: null, errors: [], timer: 0, seq: 0,
                pool: isNew && file0 === "luxury.json" ? {} : null};
    const hashes = async () => {
      const d = await groupsData();
      return (d && d.hashes) || {};
    };
    st.hash = (await hashes())[st.file] || "";
    const walls = RM.meta.walls || ["back", "corner", "none"];
    const lkinds = RM.meta.luxuryKinds || [];
    const sides = ["", ...(RM.meta.sides || ["north", "south", "east", "west"])];
    const wealths = ["", "wealthy", "elite"];
    const roles = RM.meta.roleNames || [];
    const fams = (RM.meta.families || []).map(f => f.family);
    const bands = Object.keys(RM.meta.sizeBands || {});

    const pieceRow = (p, i) => {
      const sel = (opts, val) => opts.map(o =>
        `<option value="${esc(o)}"${o === val ? " selected" : ""}>${esc(o || "—")}</option>`).join("");
      return `<tr data-p="${i}">`
        + `<td><select data-f="role">${sel(roles, p.role)}</select></td>`
        + `<td class="num"><input data-f="w" type="number" min="1" max="9" value="${p.size?.[0] ?? 1}"></td>`
        + `<td class="num"><input data-f="h" type="number" min="1" max="9" value="${p.size?.[1] ?? 1}"></td>`
        + `<td class="num"><input data-f="x" type="number" min="0" max="30" value="${p.at?.[0] ?? 0}"></td>`
        + `<td class="num"><input data-f="y" type="number" min="0" max="30" value="${p.at?.[1] ?? 0}"></td>`
        + `<td><select data-f="back">${sel(sides, p.back || "")}</select></td>`
        + `<td><label class="rm-chk"><input data-f="optional" type="checkbox"${p.optional ? " checked" : ""}>opt</label></td>`
        + `<td><select data-f="minWealth">${sel(wealths, p.minWealth || "")}</select></td>`
        + `<td><button type="button" class="rm-x" data-f="del" title="Take this piece out">✕</button></td>`
        + `</tr>`;
    };

    const build = () => {
      const g = st.group;
      const lux = st.file === "luxury.json";
      dlg.innerHTML = `<form><h3>${isNew ? "New group" : "Group " + esc(g.id || "")}</h3>`
        + `<div class="dlg-body rm-gedit">`
        + `<div class="rm-gfields">`
        + `<label>Id <input data-g="id" type="text" value="${esc(g.id || "")}"${isNew ? "" : " readonly"}></label>`
        + `<label>File <select data-g="file"${isNew ? "" : " disabled"}>`
        + fams.map(f => `<option value="${esc(f + ".json")}"${st.file === f + ".json" ? " selected" : ""}>${esc(f + ".json")}</option>`).join("")
        + `<option value="luxury.json"${st.file === "luxury.json" ? " selected" : ""}>luxury.json</option>`
        + `</select></label>`
        + `<label>Family <select data-g="family">`
        + fams.map(f => `<option value="${esc(f)}"${g.family === f ? " selected" : ""}>${esc(f)}</option>`).join("")
        + `</select></label>`
        + `<label>Wall <select data-g="wall">`
        + walls.map(w => `<option value="${esc(w)}"${g.wall === w ? " selected" : ""}>${esc(w)}</option>`).join("")
        + `</select></label>`
        + (lux ? `<label>Kind <select data-g="kind"><option value="">—</option>`
                + lkinds.map(k => `<option value="${esc(k)}"${g.kind === k ? " selected" : ""}>${esc(k)}</option>`).join("")
                + `</select></label>` : "")
        + `<span class="note">${esc((g.use || []).join(", "))}</span>`
        + `<canvas class="rm-gplan"></canvas>`
        + `</div>`
        + `<div class="rm-gpieces"><button type="button" data-a="addpiece">+ Add piece</button>`
        + `<table><thead><tr><th>role</th><th>w</th><th>h</th><th>x</th><th>y</th><th>back</th><th></th><th>from</th><th></th></tr></thead>`
        + `<tbody>${(g.pieces || []).map(pieceRow).join("")}</tbody></table></div>`
        + (st.pool ? `<fieldset class="rm-gpool"><legend>Luxury pool</legend>`
          + fams.map(f => `<label class="rm-chk"><input type="checkbox" data-fam="${esc(f)}"${st.pool[f] ? " checked" : ""}>${esc(f)}</label>`).join("")
          + `<div class="kinds">bands: `
          + bands.map(b => `<label class="rm-chk"><input type="checkbox" data-band="${esc(b)}"${bands.length === 1 ? " checked" : ""}>${esc(b)}</label>`).join("")
          + `</div></fieldset>` : "")
        + `<div class="rm-gerrs"></div>`
        + `</div>`
        + `<div class="dlg-buttons">`
        + (isNew ? "" : `<button type="button" data-a="delete">Delete…</button>`)
        + `<span class="spacer"></span>`
        + `<button type="button" data-btn="cancel">Cancel</button>`
        + `<button type="button" class="primary" data-a="save" disabled>Save</button>`
        + `</div></form>`;
      wire();
    };

    const errs = msgs => {
      const box = dlg.querySelector(".rm-gerrs");
      if (box) box.innerHTML = (msgs || []).map(m => `<div class="problem error">${esc(m)}</div>`).join("");
      const save = dlg.querySelector('[data-a="save"]');
      if (save) save.disabled = !!(msgs || []).length || !st.group.id;
    };

    const draw = () => {
      const cvs = dlg.querySelector(".rm-gplan");
      if (cvs) drawMini(cvs, {pieces: st.group.pieces || [], wall: st.group.wall});
    };

    const collectPool = root => {
      if (!st.pool) return [];
      const on = [...root.querySelectorAll("[data-band]")].filter(b => b.checked).map(b => b.dataset.band);
      return [...root.querySelectorAll("[data-fam]")].filter(f => f.checked)
        .map(f => ({family: f.dataset.fam, bands: on}));
    };

    const checkSoon = () => {
      clearTimeout(st.timer);
      st.timer = setTimeout(async () => {
        if (!st.group.id) { st.errors = []; errs([]); return; }
        const seq = ++st.seq;
        try {
          const d = await api("/api/rooms/group/check", {method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({group: st.group, file: st.file, pool: collectPool(dlg)})});
          if (seq !== st.seq) return;
          st.errors = d.errors || [];
          errs(st.errors);
        } catch (e) { if (seq === st.seq) errs([e.message]); }
      }, 300);
    };

    const wire = () => {
      dlg.querySelectorAll("[data-g]").forEach(el => {
        const f = el.dataset.g;
        el.onchange = () => {
          if (f === "file") {
            st.file = el.value;
            st.hash = "";
            st.pool = st.isNew && st.file === "luxury.json" ? {} : null;
            if (!st.pool && st.group.kind !== undefined && st.file !== "luxury.json") delete st.group.kind;
            build();
            void hashes().then(h => { st.hash = h[st.file] || ""; });
          } else if (f === "kind") {
            if (el.value) st.group.kind = el.value; else delete st.group.kind;
          } else if (f === "id") {
            st.group.id = el.value.trim();
          } else {
            st.group[f] = el.value;
          }
          draw();
          checkSoon();
        };
      });
      dlg.querySelectorAll("[data-p]").forEach(tr => {
        const p = st.group.pieces[+tr.dataset.p];
        tr.querySelectorAll("[data-f]").forEach(el => {
          const f = el.dataset.f;
          const h = () => {
            if (f === "role") p.role = el.value;
            else if (f === "back") { if (el.value) p.back = el.value; else delete p.back; }
            else if (f === "minWealth") { if (el.value) p.minWealth = el.value; else delete p.minWealth; }
            else if (f === "optional") { if (el.checked) p.optional = true; else delete p.optional; }
            else if (f === "w") p.size = [+el.value || 1, p.size?.[1] ?? 1];
            else if (f === "h") p.size = [p.size?.[0] ?? 1, +el.value || 1];
            else if (f === "x") p.at = [+el.value || 0, p.at?.[1] ?? 0];
            else if (f === "y") p.at = [p.at?.[0] ?? 0, +el.value || 0];
            else if (f === "del") { st.group.pieces.splice(st.group.pieces.indexOf(p), 1); build(); }
            draw();
            checkSoon();
          };
          if (f === "del") el.onclick = h;
          else el.onchange = h;
        });
      });
      dlg.querySelector('[data-a="addpiece"]').onclick = () => {
        st.group.pieces = [...(st.group.pieces || []),
                           {role: roles[0] || "seat", size: [1, 1], at: [0, 0]}];
        build();
        checkSoon();
      };
      dlg.querySelector('[data-btn="cancel"]').onclick = () => finish();
      dlg.querySelector("form").onsubmit = ev => ev.preventDefault();
      dlg.oncancel = ev => { ev.preventDefault(); finish(); };
      dlg.querySelector('[data-a="save"]').onclick = saveGroup;
      const del = dlg.querySelector('[data-a="delete"]');
      if (del) del.onclick = deleteGroup;
      draw();
      errs(st.errors);
    };

    async function saveGroup() {
      if (!st.group.id || st.errors.length) return;
      if (!st.hash) st.hash = ((await hashes())[st.file]) || "";
      const r = await fetch("/api/rooms/group/save", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({group: st.group, file: st.isNew ? st.file : undefined,
                              hash: st.hash, pool: collectPool(dlg)})});
      const body = await r.json().catch(() => ({}));
      if (!r.ok) return errs(body.errors || [body.error || "the save was refused"]);
      invalidateGroupCaches();
      RM.recipeEdits = {};
      savedPanel(body);
    }

    /** What a save leaves behind: the file and backup line, the stored
     * rooms still carrying the old pieces (open one, or regenerate its
     * family) and the room checker's verdict on them. */
    function savedPanel(body) {
      const rooms = body.roomsUsing || [];
      const fams_ = [...new Set(rooms.map(r => r.family))];
      dlg.innerHTML = `<form><h3>Group saved</h3><div class="dlg-body">`
        + `<p><b>${esc(body.group)}</b> is in <b>${esc(body.file)}</b> — the previous file is in library/groups/.backup.</p>`
        + (rooms.length
          ? `<p>${rooms.length} stored room${rooms.length === 1 ? "" : "s"} still hold${rooms.length === 1 ? "s" : ""} this group's pieces:</p>`
            + `<ul class="rm-roomsusing">` + rooms.map((r, i) =>
                `<li><button type="button" class="linkish" data-open="${i}">${esc(r.id)}</button> (${esc(r.family)})</li>`).join("") + `</ul>`
            + `<p class="note">The rooms keep the pieces they were composed with — regenerate a family to re-lay them out.</p>`
            + fams_.map(f => `<button type="button" data-regen="${esc(f)}">Regenerate ${esc(f)}</button>`).join(" ")
          : `<p class="note">No stored room uses this group.</p>`)
        + ((body.roomErrors || []).length
          ? `<div class="rm-gerrs">${body.roomErrors.map(m => `<div class="problem error">${esc(m)}</div>`).join("")}</div>` : "")
        + `</div><div class="dlg-buttons"><button type="button" class="primary" data-btn="close">Close</button></div></form>`;
      dlg.querySelectorAll("[data-open]").forEach(b =>
        b.onclick = () => { finish(); openRoomById(rooms[+b.dataset.open].id, rooms[+b.dataset.open].family); });
      dlg.querySelectorAll("[data-regen]").forEach(b =>
        b.onclick = async () => { finish(); await openFamily(b.dataset.regen); regenFamily(); });
      dlg.querySelector('[data-btn="close"]').onclick = () => { finish(); renderGroups(); };
      dlg.oncancel = ev => { ev.preventDefault(); finish(); renderGroups(); };
    }

    /** The delete confirm, drawn into the same dialog (there is only the
     * one): a refusal lists what uses the group and returns to the
     * editor; a delete drops it from its file. */
    function deleteGroup() {
      dlg.innerHTML = `<form><h3>Delete group</h3><div class="dlg-body">`
        + `<p>Delete <b>${esc(st.group.id)}</b> from <b>${esc(st.file)}</b>?</p>`
        + `<p class="note">Only a group no recipe, luxury pool or stored room names can go.</p>`
        + `<div class="rm-gerrs"></div></div>`
        + `<div class="dlg-buttons"><button type="button" data-btn="back">Keep it</button>`
        + `<button type="button" class="primary" data-a="yes">Delete</button></div></form>`;
      const errs2 = msgs => dlg.querySelector(".rm-gerrs").innerHTML =
        (msgs || []).map(m => `<div class="problem error">${esc(m)}</div>`).join("");
      dlg.oncancel = ev => { ev.preventDefault(); finish(); renderGroups(); };
      dlg.querySelector('[data-btn="back"]').onclick = () => { build(); dlg.showModal(); };
      dlg.querySelector('[data-a="yes"]').onclick = async () => {
        const btn = dlg.querySelector('[data-a="yes"]');
        btn.disabled = true;
        const r = await fetch("/api/rooms/group/delete", {method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({id: st.group.id, hash: st.hash})});
        const body = await r.json().catch(() => ({}));
        btn.disabled = false;
        if (!r.ok) return errs2(body.errors || [body.error || "the delete was refused"]);
        invalidateGroupCaches();
        RM.recipeEdits = {};
        finish();
        toast(`Group ${st.group.id} deleted from ${body.file}`);
        renderGroups();
      };
    }

    let closed = false;
    function finish() {
      clearTimeout(st.timer);
      st.seq++;
      if (!closed) { closed = true; if (dlg.open) dlg.close(); }
      dlg.oncancel = dlg.onclose = null;
    }

    build();
    dlg.onclose = () => finish();
    dlg.showModal();
    checkSoon();
  }

  /** Leave the groups view for one stored room: its family, its id. */
  async function openRoomById(id, family) {
    if (RM.groupsMode) toggleGroups();
    if (family && family !== RM.family) {
      $("rmFamily").value = family;
      RM.family = family;
      await loadFamily();
    }
    RM.sel = id;
    renderList();
    loadRoom();
  }

  /** Point the family select at `family` and load it (a group save's
   * "regenerate the family" ends up here). */
  async function openFamily(family) {
    if (RM.groupsMode) toggleGroups();
    if (family && family !== RM.family) {
      $("rmFamily").value = family;
      RM.family = family;
      await loadFamily();
    }
  }

  // ------------------------------------------------------------ hand work

  /** The action bar above the plan: save (with the unsaved chip), the
   * layout editor, duplicate, new, and the two regenerations. */
  function buildActions() {
    const bar = document.createElement("div");
    bar.className = "rm-actions";
    bar.innerHTML =
      `<button type="button" class="primary" data-act="save" title="Write this family's rooms (checked first; the previous file is backed up)" disabled>Save</button>`
      + `<span class="rm-dirty" hidden>Unsaved changes</span>`
      + `<span class="spacer"></span>`
      + `<button type="button" data-act="edit" title="Move, turn, add or remove groups and resize the room">Edit layout</button>`
      + `<button type="button" data-act="dup" title="A hand copy of this room under the next free id">Duplicate</button>`
      + `<button type="button" data-act="new" title="A hand room starting from a recipe's anchor group">New…</button>`
      + `<button type="button" data-act="regen" title="Compose this room's recipe again (seeds 1-8) and pick a new layout">Regenerate…</button>`
      + `<button type="button" data-act="regenfam" title="Run the generator on this family and review the diff before anything is written">Regenerate family</button>`
      + `<span class="rm-job" hidden></span>`;
    $("rmToolbar").after(bar);
    RM.actions = bar;
    const act = (name, fn) => bar.querySelector(`[data-act="${name}"]`).onclick = () => fn();
    act("save", saveFamily);
    act("edit", startEdit);
    act("dup", duplicateRoom);
    act("new", newRoomDialog);
    act("regen", regenerateRoom);
    act("regenfam", regenFamily);
    syncActions();
  }

  function syncActions() {
    if (!RM.actions) return;
    RM.actions.querySelector(".rm-dirty").hidden = !RM.dirty;
    RM.actions.querySelector('[data-act="save"]').disabled = !RM.dirty;
    const editing = !!RM.edit;
    for (const name of ["edit", "dup", "regen", "regenfam"])
      RM.actions.querySelector(`[data-act="${name}"]`).disabled = editing || !RM.sel;
    RM.actions.querySelector('[data-act="new"]').disabled = editing;
    $("rmGroupsBtn").disabled = editing;
  }

  /** Ask before unsaved hand work is left behind (a family switch or a
   * regeneration); on discard the family reloads from disk. */
  async function guardDirty() {
    if (!RM.dirty) return true;
    const choice = await openDialog("Unsaved changes",
      `<p><b>${esc(RM.family)}</b> has unsaved hand work. Leave without saving?</p>`,
      [{label: "Stay", value: "stay", primary: true},
       {label: "Discard changes", value: "discard"}]);
    if (choice !== "discard") return false;
    RM.dirty = false;
    await loadFamily();
    return true;
  }

  async function saveFamily() {
    if (!RM.dirty || !RM.family) return;
    try {
      const r = await fetch("/api/rooms/save", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({family: RM.family, hash: RM.hash, rooms: RM.rooms})});
      const body = await r.json().catch(() => ({}));
      if (!r.ok) { saveRefused(body); return; }
      RM.dirty = false;
      toast(`Saved ${body.rooms} rooms — the previous file is in library/rooms/.backup`);
      await loadFamily();
    } catch (e) { toast(e.message); }
    syncActions();
  }

  function saveRefused(body) {
    const errs = body && body.errors || [];
    openDialog("Not saved",
      `<p class="problem error">${esc((body && body.error) || "the save was refused")}</p>`
      + (errs.length > 1
        ? `<div class="rm-errs">${errs.map(m => `<div class="problem error">${esc(m)}</div>`).join("")}</div>`
        : ""),
      [{label: "Close", value: "close", primary: true}]);
  }

  // ------------------------------------------------------------ edit mode

  function startEdit() {
    if (!RM.room || RM.edit) return;
    RM.turn = RM.mirror = 0;
    syncToolbar();
    // RM.room is the stored room; the draft in edit.room diverges from it
    // until Done, so it doubles as the "as editing began" state
    RM.edit = {room: deep(RM.room), orig: RM.room, errors: [], cells: [],
               timer: 0, seq: 0, sel: -1, drag: null};
    $("rmPlan").classList.add("editing");
    $("rmSiblings").hidden = true;
    buildEditOps();
    renderDetails();
    drawPlan();
    syncActions();
    checkSoon();
  }

  function endEdit(keep) {
    const edit = RM.edit;
    if (!edit) return;
    clearTimeout(edit.timer);
    RM.edit = null;
    const ops = $("rmEditOps");
    if (ops) ops.remove();
    $("rmPlan").classList.remove("editing");
    $("rmSiblings").hidden = false;
    if (keep) {
      // a changed layout is hand work: the room is marked source "hand" so
      // a family regeneration keeps it as it stands
      if (layoutChanged(edit.orig, edit.room)) edit.room.source = "hand";
      const i = RM.rooms.findIndex(r => r.id === edit.room.id);
      if (i >= 0) RM.rooms[i] = edit.room;
      markDirty();
      toast((edit.errors || []).length
        ? "kept as a draft in the page — it does not check yet, so it cannot be saved"
        : "layout kept — save to write it");
    }
    renderList();
    loadRoom();
    syncActions();
  }

  function markDirty() {
    RM.dirty = true;
    syncActions();
  }

  /** The layout editor's own bar, under the toolbar: group operations, the
   * four sides' grow/shrink, and Done/Cancel. */
  function buildEditOps() {
    const bar = document.createElement("div");
    bar.className = "rm-editops";
    bar.id = "rmEditOps";
    const side = (s, label, title, fn) =>
      `<button type="button" data-side="${s}${label < 0 ? "-" : "+"}" title="${title}">${s.toUpperCase()}${label < 0 ? "−" : "+"}</button>`;
    bar.innerHTML =
      `<button type="button" data-e="turn" title="Turn the selected group a clockwise quarter (its backs turn)">Turn group ⟳</button>`
      + `<button type="button" data-e="del" title="Remove the selected optional or luxury group">Remove group</button>`
      + `<button type="button" data-e="add" title="Add one of the recipe's optional groups or a luxury pool group">Add group…</button>`
      + `<span class="rm-eosep"></span>`
      + side("n", -1, "Shrink one row on the north") + side("n", 1, "Grow one row on the north")
      + side("w", -1, "Shrink one column on the west") + side("w", 1, "Grow one column on the west")
      + side("e", -1, "Shrink one column on the east") + side("e", 1, "Grow one column on the east")
      + side("s", -1, "Shrink one row on the south") + side("s", 1, "Grow one row on the south")
      + `<span class="spacer"></span>`
      + `<button type="button" class="primary" data-e="done">Done</button>`
      + `<button type="button" data-e="cancel">Cancel</button>`;
    $("rmToolbar").after(bar);
    bar.querySelector('[data-e="turn"]').onclick = turnSelGroup;
    bar.querySelector('[data-e="del"]').onclick = removeSelGroup;
    bar.querySelector('[data-e="add"]').onclick = addGroupDialog;
    for (const b of bar.querySelectorAll("[data-side]")) {
      const [s, sign] = [b.dataset.side[0], b.dataset.side.endsWith("-")];
      b.onclick = () => (sign ? shrinkSide : growSide)(s);
    }
    bar.querySelector('[data-e="done"]').onclick = () => endEdit(true);
    bar.querySelector('[data-e="cancel"]').onclick = () => endEdit(false);
    syncEditOps();
  }

  function syncEditOps() {
    const ops = $("rmEditOps");
    if (!ops || !RM.edit) return;
    const g = RM.edit.sel >= 0 ? groupBoxes(RM.edit.room)[RM.edit.sel] : null;
    ops.querySelector('[data-e="turn"]').disabled = !g;
    ops.querySelector('[data-e="del"]').disabled = !g
      || !removableGids(RM.edit.room, RM.groupsCache[RM.family] || {}).has(
          (RM.edit.room.pieces || [])[g.indices[0]]?.group);
  }

  function onPlanDown(e) {
    if (!RM.edit || e.button !== 0) return;
    const c = planCell(e);
    if (!c) return;
    const i = pieceAt(RM.edit.room, c.x, c.y);
    if (i < 0) { RM.edit.sel = -1; drawPlan(); syncEditOps(); return; }
    const gi = groupBoxes(RM.edit.room).findIndex(g => g.indices.includes(i));
    if (gi < 0) return;
    e.preventDefault();
    RM.edit.sel = gi;
    RM.edit.drag = {gi, from: c, orig: deep(RM.edit.room)};
    drawPlan();
    syncEditOps();
  }

  function onPlanMove(e) {
    const d = RM.edit && RM.edit.drag;
    if (!d) return;
    const c = planCell(e);
    if (!c) return;
    const dx = c.x - d.from.x, dy = c.y - d.from.y;
    RM.edit.room = moveGroup(d.orig, d.gi, dx, dy);
    drawPlan();
  }

  function onPlanUp() {
    if (RM.edit && RM.edit.drag) {
      RM.edit.drag = null;
      renderDetails();
      checkSoon();
    }
  }

  /** The live checker, debounced: derive the room's worked-out fields on
   * the server (the one derivation), outline the cells its messages name. */
  function checkSoon() {
    if (!RM.edit) return;
    clearTimeout(RM.edit.timer);
    RM.edit.timer = setTimeout(runCheck, 250);
  }

  async function runCheck() {
    if (!RM.edit) return;
    const seq = ++RM.edit.seq;
    try {
      const d = await api("/api/rooms/check", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({rooms: [RM.edit.room]})});
      if (!RM.edit || seq !== RM.edit.seq) return;
      RM.edit.errors = d.errors || [];
      const derived = (d.derived || [])[0];
      if (derived) takeDerived(RM.edit.room, derived);
      RM.edit.cells = parseCells(RM.edit.room, RM.edit.errors);
      syncEditOps();
      renderDetails();
      drawPlan();
    } catch (e) { toast(e.message); }
  }

  /** The server's derived fields back into the page's room, in place so
   * the key order (and so the saved file's) stays as the generator's. */
  function takeDerived(room, derived) {
    for (const k of ["size", "sizeBand", "sleeps", "doors", "stretch"])
      room[k] = derived[k];
  }

  function growSide(s) {
    if (!RM.edit) return;
    const room = RM.edit.room;
    const band = (RM.meta.sizeBands || {})[room.sizeBand];
    const [w, h] = room.size || [1, 1];
    const ns = s === "n" || s === "s";
    const area = (w + (ns ? 0 : 1)) * (h + (ns ? 1 : 0));
    if (band && area > band[1])
      return toast(`that would leave the ${room.sizeBand} band (${band[0]}-${band[1]} cells)`);
    RM.edit.room = growRoom(room, {n: "north", w: "west", e: "east", s: "south"}[s], 1);
    checkSoon(); drawPlan();
  }

  function shrinkSide(s) {
    if (!RM.edit) return;
    const room = RM.edit.room;
    const band = (RM.meta.sizeBands || {})[room.sizeBand];
    const [w, h] = room.size || [1, 1];
    if (w < 2 || h < 2) return toast("the room cannot shrink further");
    const ns = s === "n" || s === "s";
    const area = (w - (ns ? 0 : 1)) * (h - (ns ? 1 : 0));
    if (band && area < band[0])
      return toast(`that would leave the ${room.sizeBand} band (${band[0]}-${band[1]} cells)`);
    const next = shrinkRoom(room, {n: "north", w: "west", e: "east", s: "south"}[s], 1);
    if (!next) return toast("something stands on that edge");
    RM.edit.room = next;
    checkSoon(); drawPlan();
  }

  function turnSelGroup() {
    if (!RM.edit || RM.edit.sel < 0) return;
    RM.edit.room = turnGroup(RM.edit.room, RM.edit.sel);
    checkSoon(); drawPlan();
  }

  function removeSelGroup() {
    if (!RM.edit || RM.edit.sel < 0) return;
    RM.edit.room = removeGroup(RM.edit.room, RM.edit.sel);
    RM.edit.sel = -1;
    checkSoon(); drawPlan(); syncEditOps();
  }

  async function addGroupDialog() {
    if (!RM.edit) return;
    const d = await groupsData();
    const all = await allGroupsData();
    if (!d || !all) return;
    const sections = addGroupSections(all, RM.edit.room, RM.edit.orig, d);
    if (!sections.length) return toast("no group in the library to add");
    const gid = await pickGroupDialog(sections);
    if (!gid) return;
    const def = all.find(g => g.id === gid);
    const spot = firstFreeSpot(RM.edit.room, def) || [1, 1];
    RM.edit.room = addGroup(RM.edit.room, def, spot[0], spot[1]);
    checkSoon();
    drawPlan();
  }

  /** The add-group picker: the sections in their order under headings, a
   * search over ids and roles, and every row carrying its own mini plan
   * and the file the group lives in. Resolves with the picked group id. */
  function pickGroupDialog(sections) {
    const dlg = $("dlg");
    const row = r => `<button type="button" class="rm-pickrow" data-g="${esc(r.gid)}"><canvas></canvas>`
      + `<span class="gname">${esc(r.gid)}</span><span class="note">${esc(r.file || "")}</span></button>`;
    const render = q => {
      pick.innerHTML = sections.map(s => {
        const rows = filterGroupRows(s.rows, q);
        return rows.length ? `<h4>${esc(s.title)}</h4>` + rows.map(row).join("") : "";
      }).join("");
      for (const b of pick.querySelectorAll(".rm-pickrow")) {
        const r = sections.flatMap(s => s.rows).find(x => x.gid === b.dataset.g);
        drawMini(b.querySelector("canvas"), {pieces: r.pieces});
        b.onclick = () => finish(b.dataset.g);
      }
    };
    dlg.innerHTML = `<form><h3>Add a group</h3><div class="dlg-body">`
      + `<input type="search" class="rm-gsearch" placeholder="Search id or role" autocomplete="off">`
      + `<div class="rm-pick"></div></div>`
      + `<div class="dlg-buttons"><button type="button" data-btn="cancel">Cancel</button></div></form>`;
    const pick = dlg.querySelector(".rm-pick");
    const search = dlg.querySelector(".rm-gsearch");
    return new Promise(resolve => {
      let done = false;
      const finish = v => { if (done) return; done = true; if (dlg.open) dlg.close(); resolve(v); };
      search.oninput = () => render(search.value);
      dlg.querySelector('[data-btn="cancel"]').onclick = () => finish(null);
      dlg.querySelector("form").onsubmit = ev => { ev.preventDefault(); finish(null); };
      dlg.oncancel = ev => { ev.preventDefault(); finish(null); };
      dlg.onclose = () => finish(null);
      render("");
      dlg.showModal();
      search.focus();
    });
  }

  async function groupsData() {
    if (!RM.groupsCache[RM.family]) {
      try {
        RM.groupsCache[RM.family] = await api("/api/rooms/groups?family="
                                              + encodeURIComponent(RM.family));
      } catch (e) { toast(e.message); return null; }
    }
    return RM.groupsCache[RM.family];
  }

  /** Every group in the library (the allgroups endpoint), cached until a
   * group or recipe save changes the files. */
  async function allGroupsData() {
    if (!RM.allCache) {
      try { RM.allCache = await api("/api/rooms/allgroups"); }
      catch (e) { toast(e.message); return null; }
    }
    return (RM.allCache && RM.allCache.groups) || [];
  }

  /** Drop the groups and all-groups caches: a group or recipe save changed
   * the files, so the next view rebuilds them from disk. */
  function invalidateGroupCaches() {
    RM.allCache = null;
    RM.groupsCache = {};
  }

  // ------------------------------------------------------ duplicate and new

  function duplicateRoom() {
    if (!RM.room) return;
    const id = newId(RM.family, RM.room.sizeBand, RM.room.clearance,
                     RM.room.style, RM.rooms.map(r => r.id));
    if (!id) return toast("no free id letter for this band, clearance and style");
    const copy = cloneRoom(RM.room, id);
    RM.rooms.push(copy);
    RM.rooms.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    RM.sel = id;
    markDirty();
    renderList();
    loadRoom();
    toast("duplicated as a hand room");
  }

  async function newRoomDialog() {
    const d = await groupsData();
    if (!d) return;
    const recipes = (d.recipes || []).filter(r => {
      const anchor = (r.groups || [])[0];
      return anchor && (d.groups || {})[anchor.group];
    });
    if (!recipes.length) return toast("no recipe with a placeable anchor group");
    const body =
      `<p class="note">A hand room starts from a recipe's anchor group alone, in the
       smallest room that holds it; everything else is yours to add.</p>`
      + `<div class="rm-form"><label class="inline">Recipe <select id="rmNewRecipe">`
      + recipes.map(r => `<option value="${esc(r.layout)}">${esc(r.layout)}</option>`).join("")
      + `</select></label>`
      + `<label class="inline">Clearance <select id="rmNewClearance">`
      + (RM.meta.clearances || []).map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join("")
      + `</select></label>`
      + `<label class="inline">Style <select id="rmNewStyle">`
      + (RM.meta.styles || []).map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join("")
      + `</select></label></div>`;
    if ((await openDialog("New hand room", body,
                          [{label: "Create", value: "ok", primary: true},
                           {label: "Cancel", value: null}])) !== "ok") return;
    const recipe = recipes.find(r => r.layout === $("rmNewRecipe").value);
    const clearance = $("rmNewClearance").value;
    const style = $("rmNewStyle").value;
    if (!recipe || !clearance || !style) return;
    const anchor = (d.groups || {})[(recipe.groups || [])[0].group];
    const room = roomFromAnchor(anchor, recipe, clearance, style);
    if (!room) return toast("the anchor group has no pieces");
    if (RM.edit) endEdit(false);
    RM.rooms.push(room);
    RM.rooms.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    RM.sel = room.id;
    markDirty();
    renderList();
    loadRoom();
    startEdit();
    toast("new hand room — drag the group, grow the room, add more");
  }

  /** The smallest starting room for an anchor group: its pieces as they
   * stand plus one free row and column, with every field the format needs
   * (the worked-out ones are placeholders until the first live check
   * derives them). */
  function roomFromAnchor(anchor, recipe, clearance, style) {
    const pieces = groupForm(anchor).map(p => Object.assign({}, p, {group: anchor.id}));
    if (!pieces.length) return null;
    const rects = pieces.map(rectOf).filter(Boolean);
    const w = Math.max(...rects.map(r => r[0] + r[2])) + 1;
    const h = Math.max(...rects.map(r => r[1] + r[3])) + 1;
    const bands = RM.meta.sizeBands || {};
    let band = null;
    for (const [name, rng] of Object.entries(bands))
      if (rng[0] <= w * h && w * h <= rng[1]) { band = name; break; }
    if (!band) band = w * h <= 11 ? "tiny" : w * h <= 24 ? "small" : w * h <= 48 ? "medium" : "large";
    const id = newId(RM.family, band, clearance, style, RM.rooms.map(r => r.id));
    if (!id) { toast("no free id letter for this band, clearance and style"); return null; }
    const wealth = ((RM.meta.wealthFor || {})[clearance] || {})[style] || (RM.meta.tiers || []).slice(0, 2);
    return {id, family: RM.family, sizeBand: band, clearance, style,
            wealth: [...wealth], size: [w, h],
            sleeps: {singles: 0, couples: 0}, pieces,
            doors: {north: [], south: [], west: [], east: []},
            stretch: {x: [], y: []}, outdoor: false, symmetric: false,
            recipe: recipe.layout || "", description: "A hand room.",
            source: "hand"};
  }

  // ------------------------------------------------------------ regenerate

  async function regenerateRoom() {
    if (!RM.room) return;
    if (RM.dirty && !(await guardDirty())) return;
    toast("composing candidates…");
    let d;
    try {
      d = await api("/api/rooms/regenerate", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({id: RM.sel})});
    } catch (e) { return toast(e.message); }
    const cands = d.candidates || [];
    if (!cands.length)
      return toast("no new layout for this recipe: every candidate duplicates a shipped room");
    const pick = await pickDialog(cands);
    if (pick === null || pick === undefined) return;
    const merged = mergeLayout(RM.room, cands[pick]);
    const i = RM.rooms.findIndex(r => r.id === merged.id);
    if (i >= 0) RM.rooms[i] = merged;
    markDirty();
    renderList();
    loadRoom();
    toast("layout replaced — the room is a hand room now; save to write it");
  }

  /** The candidate picker: small plans; a click picks, Cancel (or Esc)
   * keeps the room as it is. */
  function pickDialog(cands) {
    const dlg = $("dlg");
    dlg.innerHTML = `<form><h3>Pick a new layout</h3><div class="dlg-body"><div class="rm-cands">`
      + cands.map((c, i) => `<button type="button" class="rm-cand" data-i="${i}" title="${esc(c.description || "")}"></button>`).join("")
      + `</div></div><div class="dlg-buttons"><button type="button" data-btn="cancel">Cancel</button></div></form>`;
    return new Promise(resolve => {
      let done = false;
      const finish = v => { if (done) return; done = true; if (dlg.open) dlg.close(); resolve(v); };
      dlg.querySelectorAll(".rm-cand").forEach(b => {
        const c = cands[+b.dataset.i];
        const cvs = document.createElement("canvas");
        b.appendChild(cvs);
        drawMini(cvs, c);
        const small = document.createElement("small");
        small.textContent = `${c.size[0]}×${c.size[1]} · ${(c.pieces || []).length} pieces`;
        b.appendChild(small);
        b.onclick = () => finish(+b.dataset.i);
      });
      dlg.querySelector('[data-btn="cancel"]').onclick = () => finish(null);
      dlg.querySelector("form").onsubmit = ev => { ev.preventDefault(); finish(null); };
      dlg.oncancel = ev => { ev.preventDefault(); finish(null); };
      dlg.onclose = () => finish(null);
      dlg.showModal();
    });
  }

  async function regenFamily() {
    if (!RM.family) return;
    if (RM.dirty && !(await guardDirty())) return;
    if (RM.edit) endEdit(false);
    let started;
    try {
      started = await api("/api/rooms/regenerate/family", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({family: RM.family})});
    } catch (e) { return toast(e.message); }
    const chip = RM.actions.querySelector(".rm-job");
    const btn = RM.actions.querySelector('[data-act="regenfam"]');
    btn.disabled = true;
    chip.hidden = false;
    chip.textContent = `regenerating ${RM.family}…`;
    try {
      let job = (started && started.job) || null;
      for (;;) {
        if (!job || job.status !== "running") break;
        await new Promise(r => setTimeout(r, 1000));
        const d = await api("/api/rooms/job");
        job = d.job;
      }
      chip.hidden = true;
      if (!job) return;
      if (job.status === "error") return toast("regeneration failed: " + (job.error || "?"));
      await showFamilyDiff(job);
    } catch (e) {
      chip.hidden = true;
      toast(e.message);
    } finally {
      btn.disabled = false;
      syncActions();
    }
  }

  /** The diff of a family regeneration, before/after plans per id; Apply
   * writes it (through the save path: checker, backup, atomic write),
   * Discard throws it away — nothing is written before Apply. */
  async function showFamilyDiff(job) {
    const diff = job.diff || [];
    const counts = {added: 0, removed: 0, changed: 0};
    for (const e of diff) counts[e.op] = (counts[e.op] || 0) + 1;
    const body =
      `<p class="note">${counts.added} added · ${counts.removed} removed · ${counts.changed} changed`
      + (RM.dirty ? ` — you have unsaved changes; applying reloads the family from disk` : "")
      + `. Hand rooms are kept as they are.</p>`
      + (diff.length ? `<div class="rm-diff">` + diff.map((e, i) =>
          `<div class="rm-diffrow ${e.op}"><span class="rm-op">${e.op}</span>`
          + `<span class="id" title="${esc(e.id)}">${esc(e.id)}</span>`
          + `<span class="rm-chgpair" data-i="${i}"></span></div>`).join("") + `</div>`
        : `<p class="note">Nothing changes: the family regenerates to exactly what it holds.</p>`);
    const choice = await openDialog(`Regenerate ${job.family}`, body,
      [{label: "Apply", value: "apply", primary: true},
       {label: "Discard", value: "discard"}],
      dlg => {
        const mini = room => {
          const cvs = document.createElement("canvas");
          drawMini(cvs, room);
          return cvs;
        };
        dlg.querySelectorAll(".rm-chgpair").forEach(el => {
          const e = diff[+el.dataset.i];
          if (e.before) el.appendChild(mini(e.before));
          if (e.before && e.after) el.appendChild(Object.assign(document.createElement("span"),
                                                   {className: "arrow", textContent: "→"}));
          if (e.after) el.appendChild(mini(e.after));
        });
      });
    if (choice === "apply") {
      try {
        const r = await api("/api/rooms/regenerate/apply", {method: "POST",
          headers: {"Content-Type": "application/json"}, body: "{}"});
        toast(`regenerated ${r.rooms} rooms written (previous file backed up)`);
        RM.dirty = false;
        await loadFamily();
      } catch (e) { toast(e.message); }
    } else {
      try { await api("/api/rooms/regenerate/discard", {method: "POST",
        headers: {"Content-Type": "application/json"}, body: "{}"}); }
      catch (e) { /* the job is gone either way for the page */ }
    }
  }

  return {roleColor, darker, shortRole, filterRooms, fitPlan, doorCells, stretchLines,
          groupBoxes, pieceAt, rectOf, LETTERS, EDITABLE, letterAt, nextLetter, newId,
          cloneRoom, TURN_SIDES, turnGroup, moveGroup, removeGroup, groupForm, addGroup,
          growRoom, shrinkRoom, mergeLayout, setField, resetField, parseCells,
          removableGids, groupGids, addGroupSections, filterGroupRows, firstFreeSpot,
          layoutChanged};
});
