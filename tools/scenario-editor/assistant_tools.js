"use strict";
// Tool registry for the Scenario Editor's assistant pane: the fixed set of actions a model may
// take on the open scenario, kept apart from the page so it can be tested with node. A tool never
// throws on bad input: it answers {ok: false, error} so the message can be shown and fed back to
// the model. Every change goes through the caller's set(obj, key, value), arrays replaced with new
// ones, never spliced in place. TOOLS is the single source of truth for what the pane can do;
// promptLines() renders it for the system prompt and preview() words the destructive ones.

(function (root, factory) {
  if (typeof module === "object" && module.exports)
    module.exports = factory(require("./mapops.js"), require("./refs.js"), require("./schedule.js"));
  else root.AssistantTools = factory(root.MapOps, root.Refs, root.Schedule);
})(typeof self !== "undefined" ? self : this, function (MapOps, Refs, Schedule) {

  const MAX_REGIONS = 150;       // summary caps, so the report stays prompt-sized
  const MAX_TEMPLATES = 80;
  const MAX_FIND = 20;
  // A shift's working hours; "none" (or no work region) stays home all day.
  const SHIFTS = {day: ["08:00", "18:00"], evening: ["15:00", "23:00"], night: ["22:00", "06:00"]};

  const isStr = v => typeof v === "string";
  const bad = error => ({ok: false, error});
  const region = (scn, id) => (scn.regions || []).find(r => r.id === id) || null;
  const entity = (scn, id) => (scn.entities || []).find(e => e.id === id) || null;
  const regionNames = scn => new Set((scn.regions || []).map(r => r.name));

  /** An entity's footprint [w, h]: an object covers its own size or, missing that, its template's;
   *  people are 1 x 1. */
  function footprint(scn, e) {
    if (e.type !== "object") return [1, 1];
    if (Array.isArray(e.size) && e.size.length === 2) return e.size;
    const t = (scn.objectTemplates || []).find(x => x.id === e.templateId);
    return Array.isArray(t && t.size) ? t.size : [1, 1];
  }

  /** Whether any entity's footprint covers the cell (a zero-wide door covers nothing). */
  const occupied = (scn, x, y) => (scn.entities || []).some(e => {
    if (!Array.isArray(e.pos)) return false;
    const [w, h] = footprint(scn, e);
    return x >= e.pos[0] && x < e.pos[0] + w && y >= e.pos[1] && y < e.pos[1] + h;
  });

  // ---------------------------------------------------------------- free cells
  /** A deterministic free cell [x, y] in `reg`, nearest the centre first. Walls are thin lines on
   *  the region's border, not cells, so every cell of a walled room stands; doorway cells (any
   *  region's openings) are skipped so nothing placed here blocks a door, as are cells an entity
   *  covers and `taken` ("x,y"). null when the region has none left. */
  function freeCell(scn, reg, taken) {
    const r = MapOps.rect(reg);
    const doors = new Set();
    for (const o of scn.regions || []) for (const g of o.openings || []) doors.add(g[0] + "," + g[1]);
    const cx = (r[0] + r[2]) / 2, cy = (r[1] + r[3]) / 2, cells = [];
    for (let y = r[1]; y <= r[3]; y++) for (let x = r[0]; x <= r[2]; x++) {
      const dx = x - cx, dy = y - cy;
      cells.push([dx * dx + dy * dy, y, x]);
    }
    cells.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
    for (const [, y, x] of cells)
      if (!occupied(scn, x, y) && !doors.has(x + "," + y) && !(taken && taken.has(x + "," + y)))
        return [x, y];
    return null;
  }

  // ---------------------------------------------------------------- summary
  /** The region an NPC calls home: the one their sleep block (or single all-day block) names, else
   *  the region they stand in. Its name, or null. */
  function homeOf(scn, e) {
    const sch = Array.isArray(e.schedule) ? e.schedule : [];
    const night = sch.find(b => b && b.role === "sleep" && isStr(b.location) && b.location);
    if (night) return night.location;
    if (sch.length === 1 && sch[0].start === sch[0].end && isStr(sch[0].location)) return sch[0].location;
    const here = Array.isArray(e.pos) ? MapOps.regionAt(scn, e.pos[0], e.pos[1]) : null;
    return here ? here.name : null;
  }

  /** A compact, JSON-serializable report of the scenario's state for the model: names, ids and
   *  counts only, the big lists capped (regions with a "... and N more" tail). Descriptions and
   *  schedules are left for the tools to fetch. */
  function summary(scn) {
    const regions = [];
    for (const r of scn.regions || []) {
      if (regions.length === MAX_REGIONS) { regions.push("... and " + (scn.regions.length - MAX_REGIONS) + " more"); break; }
      const e = {id: r.id, name: r.name, size: Array.isArray(r.size) ? r.size[0] + "x" + r.size[1] : "1x1"};
      if (r.wall) e.wall = r.wall;                        // the wall material; absent means open
      if (r.pocket && typeof r.pocket === "object") e.level = r.pocket.level;
      regions.push(e);
    }
    const counts = {};
    for (const e of scn.entities || []) counts[e.type] = (counts[e.type] || 0) + 1;
    const player = entity(scn, scn.playerId);
    return {
      name: isStr(scn.name) ? scn.name : "",
      gridSize: scn.gridSize,
      regions,
      npcs: (scn.entities || []).filter(e => e.type === "npc")
        .map(e => ({id: e.id, name: e.name, home: homeOf(scn, e)})),
      player: player ? {id: player.id, name: player.name} : null,
      objectTemplates: (scn.objectTemplates || []).slice(0, MAX_TEMPLATES).map(t => ({id: t.id, name: t.name})),
      itemTemplates: (scn.itemTemplates || []).length,
      npcTemplates: Refs.npcTypes(scn).length,
      entities: counts,
    };
  }

  // ---------------------------------------------------------------- schedules for new NPCs
  /** A valid round-the-clock schedule: the shift's work block at the work region's name, the rest
   *  of the day split sleep and leisure at home (a night shift sleeps in the morning). No work
   *  region, or shift "none": one all-day block at home. */
  function buildSchedule(home, work, shift) {
    if (!work || shift === "none") return Schedule.makeAllDay(home.name);
    const [ws, we] = SHIFTS[shift], blocks = [{start: ws, end: we, location: work.name, role: "work"}];
    if (shift === "day") {
      blocks.push({start: we, end: "22:00", location: home.name, role: "leisure"});
      blocks.push({start: "22:00", end: ws, location: home.name, role: "sleep"});
    } else if (shift === "evening") {
      blocks.push({start: we, end: "07:00", location: home.name, role: "sleep"});
      blocks.push({start: "07:00", end: ws, location: home.name, role: "leisure"});
    } else {
      blocks.push({start: we, end: "14:00", location: home.name, role: "sleep"});
      blocks.push({start: "14:00", end: ws, location: home.name, role: "leisure"});
    }
    return blocks;
  }

  /** One registry entry. run never sees null args (and answers, never throws). */
  function tool(name, args, desc, destructive, run) {
    return {name, args, desc, destructive: !!destructive, run: (scn, a, set) => run(scn, a || {}, set)};
  }

  // ---------------------------------------------------------------- the registry
  const TOOLS = {
    find: tool("find", "{query: string}",
      "Find regions, entities and templates whose name or description contains the query, case-insensitive; up to 20 matches with their ids.",
      false, (scn, args) => {
        if (!isStr(args.query) || !args.query.trim()) return bad("find needs a non-empty query string");
        const q = args.query.trim().toLowerCase(), out = [];
        const hit = (id, kind, name, desc) => {
          if (out.length >= MAX_FIND) return;
          if ((name || "").toLowerCase().includes(q) || (isStr(desc) && desc.toLowerCase().includes(q)))
            out.push({id, kind, name});
        };
        for (const r of scn.regions || []) hit(r.id, "region", r.name, r.description);
        for (const e of scn.entities || []) hit(e.id, e.type, e.name, e.description);
        for (const t of scn.objectTemplates || []) hit(t.id, "objectTemplate", t.name, t.description);
        for (const t of scn.itemTemplates || []) hit(t.id, "itemTemplate", t.name, t.description);
        for (const t of Refs.npcTypes(scn)) hit(t.id, "npcTemplate", t.name, t.description);
        return {ok: true, summary: out.length + " match" + (out.length === 1 ? "" : "es") + " for \"" + args.query.trim() + "\"",
          data: {query: args.query.trim(), matches: out}};
      }),

    get_region: tool("get_region", "{id: string}",
      "One region's fields, doors, floor level and the entities inside it, grouped by kind.",
      false, (scn, args) => {
        if (!isStr(args.id)) return bad("get_region needs an id string");
        const r = region(scn, args.id);
        if (!r) return bad("no region has id \"" + args.id + "\"");
        const inside = {};
        for (const e of MapOps.contents(scn, r).entities)
          (inside[e.type] = inside[e.type] || []).push({id: e.id, name: e.name});
        const out = {id: r.id, name: r.name, description: isStr(r.description) ? r.description : "",
          wall: r.wall || null, ground: r.ground ?? null, groundTexture: r.groundTexture ?? null,
          position: r.position, size: r.size, openings: r.openings || [],
          level: r.pocket && typeof r.pocket === "object" ? r.pocket.level : 0, entities: inside};
        for (const k of ["hostile", "ambience", "surface", "door"])
          if (r[k] !== undefined) out[k] = r[k];
        const n = Object.values(inside).reduce((a, l) => a + l.length, 0);
        return {ok: true,
          summary: "Region \"" + r.name + "\": " + r.size[0] + "x" + r.size[1] + (r.wall ? ", walled" : ", open") + ", " + n + " entities inside",
          data: {region: out}};
      }),

    get_person: tool("get_person", "{id: string}",
      "Every field of one NPC, schedule blocks included.",
      false, (scn, args) => {
        if (!isStr(args.id)) return bad("get_person needs an id string");
        const e = entity(scn, args.id);
        if (!e || e.type !== "npc") return bad("no npc has id \"" + args.id + "\"");
        return {ok: true, summary: "NPC \"" + e.name + "\"", data: {npc: e}};
      }),

    list_object_templates: tool("list_object_templates", "{}",
      "The object templates (up to 80): id, name, footprint, tags and loot pool item names.",
      false, scn => {
        const itemName = id => { const t = (scn.itemTemplates || []).find(i => i.id === id); return t ? t.name : id; };
        const templates = (scn.objectTemplates || []).slice(0, MAX_TEMPLATES).map(t => ({
          id: t.id, name: t.name, size: Array.isArray(t.size) ? t.size : [1, 1],
          tags: Array.isArray(t.tags) ? t.tags : [], lootPool: (t.lootPoolIds || []).map(itemName)}));
        return {ok: true, summary: templates.length + " object template" + (templates.length === 1 ? "" : "s"), data: {templates}};
      }),

    edit_texts: tool("edit_texts", "{edits: [{id, field, value}]} (up to 10)",
      "Set text fields: id \"scenario\" takes worldBackground or narrativeFlavor, a region takes description, an NPC takes description, physicalDescription or mindset. Values are trimmed, max 4000 characters; a bad edit is reported and the rest still apply.",
      false, (scn, args, set) => {
        if (!Array.isArray(args.edits) || !args.edits.length) return bad("edit_texts needs edits: [{id, field, value}]");
        if (args.edits.length > 10) return bad("at most 10 edits per edit_texts action");
        const applied = [], errors = [];
        args.edits.forEach((ed, i) => {
          const fail = msg => errors.push({index: i, error: msg});
          if (!ed || typeof ed !== "object" || Array.isArray(ed)) return fail("an edit must be an object {id, field, value}");
          if (!isStr(ed.id)) return fail("an edit needs an id");
          if (!isStr(ed.field)) return fail("an edit needs a field");
          if (!isStr(ed.value)) return fail("the value must be a string");
          const value = ed.value.trim();
          if (value.length > 4000) return fail("the value is longer than 4000 characters");
          let target = null, allowed = null, what = null;
          if (ed.id === "scenario") { target = scn; allowed = ["worldBackground", "narrativeFlavor"]; what = "the scenario"; }
          else {
            const r = region(scn, ed.id);
            if (r) { target = r; allowed = ["description"]; what = "region \"" + r.name + "\""; }
            else {
              const e = entity(scn, ed.id);
              if (!e) return fail("nothing in the scenario has id \"" + ed.id + "\"");
              if (e.type !== "npc") return fail("\"" + e.name + "\" is not an npc");
              target = e; allowed = ["description", "physicalDescription", "mindset"]; what = "npc \"" + e.name + "\"";
            }
          }
          if (!allowed.includes(ed.field)) return fail(what + " has no editable field \"" + ed.field + "\"");
          set(target, ed.field, value);
          applied.push({id: ed.id, field: ed.field});
        });
        if (!applied.length) return bad(errors.map(e => e.error).join("; "));
        return {ok: true,
          summary: "updated " + applied.length + " text" + (applied.length === 1 ? "" : "s") + (errors.length ? ", " + errors.length + " failed" : ""),
          data: {applied, errors}};
      }),

    add_npcs: tool("add_npcs", "{npcs: [{name, gender, homeRegionId, workRegionId?, shift?, description?, physicalDescription?}]} (up to 10)",
      "Create NPCs in their home region with a round-the-clock schedule: the shift's work block at the work region (day 08:00-18:00, evening 15:00-23:00, night 22:00-06:00), the rest sleep and leisure at home. Shift none, or no work region, keeps them home all day.",
      false, (scn, args, set) => {
        if (!Array.isArray(args.npcs) || !args.npcs.length) return bad("add_npcs needs npcs: [{name, ...}]");
        if (args.npcs.length > 10) return bad("at most 10 npcs per add_npcs action");
        const created = [], errors = [];
        args.npcs.forEach((n, i) => {
          const fail = msg => errors.push({index: i, error: msg});
          if (!n || typeof n !== "object" || Array.isArray(n)) return fail("an npc must be an object");
          if (!isStr(n.name) || !n.name.trim()) return fail("an npc needs a name");
          const name = n.name.trim();
          if ((scn.entities || []).some(e => e.name === name)) return fail("another entity is already called \"" + name + "\"");
          if (n.gender !== undefined && n.gender !== "male" && n.gender !== "female") return fail("gender must be \"male\" or \"female\"");
          for (const k of ["description", "physicalDescription"])
            if (n[k] !== undefined && !isStr(n[k])) return fail(k + " must be a string");
          if (!isStr(n.homeRegionId)) return fail("an npc needs a homeRegionId");
          const home = region(scn, n.homeRegionId);
          if (!home) return fail("no region has id \"" + n.homeRegionId + "\"");
          const shift = n.shift === undefined ? "day" : n.shift;
          if (!(shift in SHIFTS) && shift !== "none") return fail("shift must be day, evening, night or none");
          let work = null;
          if (n.workRegionId !== undefined) {
            if (!isStr(n.workRegionId)) return fail("workRegionId must be a region id");
            work = region(scn, n.workRegionId);
            if (!work) return fail("no region has id \"" + n.workRegionId + "\"");
          }
          const blocks = buildSchedule(home, work, shift);
          const problems = Schedule.validate(blocks, regionNames(scn));
          if (problems.length) return fail("the schedule would be invalid: " + problems.map(p => p.msg).join("; "));
          const cell = freeCell(scn, home, null);
          if (!cell) return fail("the region \"" + home.name + "\" has no free cell");
          const res = MapOps.placeNpc(scn, {name, gender: n.gender, description: n.description,
            physicalDescription: n.physicalDescription}, cell[0], cell[1], set);
          if (res.error) return fail(res.error);
          set(res.npc, "schedule", blocks);
          created.push(res.npc.id);
        });
        if (!created.length) return bad(errors.map(e => e.error).join("; "));
        return {ok: true,
          summary: "added " + created.length + " npc" + (created.length === 1 ? "" : "s") + (errors.length ? ", " + errors.length + " failed" : ""),
          data: {createdIds: created, errors}};
      }),

    update_npc: tool("update_npc", "{id, description?, physicalDescription?, mindset?, stance?, merchant?, schedule?}",
      "Change one NPC's whitelisted fields. stance is hostile, neutral or fleeing; merchant is true or false; schedule replaces the whole day and must chain round the clock, naming exact region names.",
      false, (scn, args, set) => {
        if (!isStr(args.id)) return bad("update_npc needs an id string");
        const e = entity(scn, args.id);
        if (!e || e.type !== "npc") return bad("no npc has id \"" + args.id + "\"");
        const EDITABLE = ["description", "physicalDescription", "mindset", "stance", "merchant", "schedule"];
        const unknown = Object.keys(args).filter(k => k !== "id" && !EDITABLE.includes(k));
        if (unknown.length) return bad("unknown field" + (unknown.length === 1 ? "" : "s") + ": " + unknown.join(", "));
        const texts = {};
        for (const k of ["description", "physicalDescription", "mindset"])
          if (args[k] !== undefined) {
            if (!isStr(args[k])) return bad(k + " must be a string");
            const v = args[k].trim();
            if (v.length > 4000) return bad(k + " is longer than 4000 characters");
            texts[k] = v;
          }
        if (args.stance !== undefined && !["hostile", "neutral", "fleeing"].includes(args.stance))
          return bad("stance must be hostile, neutral or fleeing");
        if (args.merchant !== undefined && typeof args.merchant !== "boolean")
          return bad("merchant must be true or false");
        let blocks = null;
        if (args.schedule !== undefined) {
          if (!Array.isArray(args.schedule) || !args.schedule.length) return bad("schedule must be a non-empty array of blocks");
          if (!args.schedule.every(b => b && typeof b === "object" && !Array.isArray(b)))
            return bad("each schedule block must be an object");
          blocks = args.schedule.map(b => ({start: b.start, end: b.end, location: b.location, role: b.role}));
          const problems = Schedule.validate(blocks, regionNames(scn));
          if (problems.length) return bad("the schedule is invalid: " + problems.map(p => p.msg).join("; "));
        }
        const fields = [];
        for (const [k, v] of Object.entries(texts)) { set(e, k, v); fields.push(k); }
        if (args.stance !== undefined) { set(e, "stance", args.stance); fields.push("stance"); }
        if (args.merchant !== undefined) {
          if (args.merchant && e.merchant === undefined) set(e, "merchant", {});
          if (!args.merchant) set(e, "merchant", undefined);
          fields.push("merchant");
        }
        if (blocks) { set(e, "schedule", blocks); fields.push("schedule"); }
        return {ok: true, summary: "updated " + e.name + ": " + fields.join(", "), data: {id: e.id, fields}};
      }),

    remove_npc: tool("remove_npc", "{id: string}",
      "Delete an NPC for good, repairing everything that referred to it.",
      true, (scn, args, set) => {
        if (!isStr(args.id)) return bad("remove_npc needs an id string");
        const e = entity(scn, args.id);
        if (!e || e.type !== "npc") return bad("no npc has id \"" + args.id + "\"");
        const report = Refs.forceDelete(scn, [args.id], {}, set);
        return {ok: true, summary: "removed the npc \"" + e.name + "\"", data: {report}};
      }),

    remove_object: tool("remove_object", "{id: string}",
      "Delete a placed object for good, repairing everything that referred to it.",
      true, (scn, args, set) => {
        if (!isStr(args.id)) return bad("remove_object needs an id string");
        const e = entity(scn, args.id);
        if (!e || e.type !== "object") return bad("no object has id \"" + args.id + "\"");
        const report = Refs.forceDelete(scn, [args.id], {}, set);
        return {ok: true, summary: "removed the object \"" + e.name + "\"", data: {report}};
      }),

    place_objects: tool("place_objects", "{templateId, regionId, count} (count 1 to 10)",
      "Place copies of an object template in a region, each on its own free cell near the centre.",
      false, (scn, args, set) => {
        if (!isStr(args.templateId)) return bad("place_objects needs a templateId string");
        if (!isStr(args.regionId)) return bad("place_objects needs a regionId string");
        const count = args.count === undefined ? 1 : args.count;
        if (!Number.isInteger(count) || count < 1 || count > 10) return bad("count must be a whole number from 1 to 10");
        const tpl = (scn.objectTemplates || []).find(t => t.id === args.templateId);
        if (!tpl) return bad("no object template has id \"" + args.templateId + "\"");
        const reg = region(scn, args.regionId);
        if (!reg) return bad("no region has id \"" + args.regionId + "\"");
        const taken = new Set(), placed = [];
        for (let i = 0; i < count; i++) {
          const cell = freeCell(scn, reg, taken);
          if (!cell) break;
          const e = MapOps.placeObject(scn, tpl, cell[0], cell[1], set);
          const [w, h] = footprint(scn, e);
          for (let y = e.pos[1]; y < e.pos[1] + h; y++) for (let x = e.pos[0]; x < e.pos[0] + w; x++) taken.add(x + "," + y);
          placed.push({id: e.id, name: e.name, cell: e.pos.slice()});
        }
        if (!placed.length) return bad("the region \"" + reg.name + "\" has no free cell");
        return {ok: true,
          summary: "placed " + placed.length + " of " + count + " " + tpl.name + (placed.length === 1 ? "" : "s") + " in \"" + reg.name + "\"" + (placed.length < count ? " (the region is full)" : ""),
          data: {placed, templateId: tpl.id, regionId: reg.id}};
      }),

    rename_thing: tool("rename_thing", "{id, name}",
      "Rename a region, entity or template, updating every schedule block and calendar event that names it.",
      false, (scn, args, set) => {
        if (!isStr(args.id)) return bad("rename_thing needs an id string");
        if (!isStr(args.name)) return bad("rename_thing needs a name string");
        const name = args.name.trim();
        if (!name) return bad("the new name is empty");
        const thing = region(scn, args.id) || entity(scn, args.id)
          || (scn.objectTemplates || []).find(t => t.id === args.id)
          || (scn.itemTemplates || []).find(t => t.id === args.id)
          || Refs.npcTypes(scn).find(t => t.id === args.id);
        if (!thing) return bad("nothing in the scenario has id \"" + args.id + "\"");
        const clash = [...(scn.regions || []), ...(scn.entities || []), ...(scn.objectTemplates || []),
          ...(scn.itemTemplates || []), ...Refs.npcTypes(scn)].some(o => o !== thing && o.name === name);
        if (clash) return bad("something is already called \"" + name + "\"");
        const res = Refs.renameEverywhere(scn, args.id, name, set);
        if (res.error) return bad(res.error);
        return {ok: true,
          summary: "renamed to \"" + name + "\"" + (res.count ? ", " + res.count + " mention" + (res.count === 1 ? "" : "s") + " updated" : ""),
          data: {id: args.id, name, mentions: res.count}};
      }),
  };

  // ---------------------------------------------------------------- prompt and confirm text
  /** One line per tool for the system prompt: "name — args — one-line description". */
  function promptLines() {
    return Object.keys(TOOLS).map(name => name + " — " + TOOLS[name].args + " — " + TOOLS[name].desc);
  }

  /** A short plain-language description of what a destructive action will do, for a confirm
   *  dialog; null when there is nothing to confirm (the tool isn't destructive, or its id names
   *  nothing). action: {tool, args} as the model sends it. */
  function preview(scn, action) {
    const t = action && TOOLS[action.tool];
    if (!t || !t.destructive) return null;
    if (t.name !== "remove_npc" && t.name !== "remove_object") return null;
    const id = action.args && action.args.id;
    if (!isStr(id)) return null;
    const report = Refs.previewDelete(scn, [id], {});
    if (!report.removed.length) return null;
    const what = report.removed.map(r => "\"" + r.name + "\" (" + r.kind + ")").join(", ");
    const notes = [...report.changed.map(c => c.ownerName + ": " + c.what), ...report.warnings];
    return "Remove " + what + (notes.length ? ". Also: " + notes.join("; ") : ".");
  }

  return {summary, freeCell, TOOLS, promptLines, preview};
});
