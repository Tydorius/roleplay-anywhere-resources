"use strict";
// Editing logic for Anywhere RPG 1.0 floors, portals, door objects, locks and keys, and NPC types,
// kept apart from the page so they can be tested with node. Every function that changes the scenario
// takes `set(obj, key, value)`, which the page records for undo; value === undefined deletes the key,
// and arrays are always replaced with new ones, never edited in place. Nothing here touches the DOM.
// Coordinates: [0,0] is the bottom-left cell, y grows north. Rules follow the game's own 1.0 code:
// doorways come from openings on both sides of a wall, door objects sit zero-wide on the wall line,
// and 0.18 hostileNpcTemplates convert into 1.0 npcTemplates with homes.

(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./mapops.js"));
  else root.World10 = factory(root.MapOps);
})(typeof self !== "undefined" ? self : this, function (MapOps) {

  // ---------------------------------------------------------------- shared bits
  const DOOR_KINDS = ["door", "bars", "gate", "curtain"];
  const DOOR_NAMES = {door: "Door", bars: "Barred door", gate: "Gate", curtain: "Curtain"};
  const STANCES = ["neutral", "skittish", "hostile"];
  const STEP = {n: [0, 1], e: [1, 0], s: [0, -1], w: [-1, 0]};   // a side's step to the next cell
  // What a 0.18 template with attacksOnSight: false becomes: it never starts a fight, so "neutral".
  const PASSIVE_STANCE = "neutral";

  const eqCell = (a, b) => a[0] === b[0] && a[1] === b[1];
  /** The side ("n", "e", "s" or "w") pointing from cell a to the adjacent cell b. */
  const sideBetween = (a, b) => b[0] === a[0] + 1 ? "e" : b[0] === a[0] - 1 ? "w" : b[1] === a[1] + 1 ? "n" : "s";
  const objectTemplates = scn => scn.objectTemplates || [];
  const itemTemplates = scn => scn.itemTemplates || [];

  // ---------------------------------------------------------------- floors
  /** The floors of a building (regions with `pocket.anchor` pointing at it), sorted by level. */
  function floorsOf(scn, building) {
    return scn.regions.filter(r => MapOps.isFloor(r) && r.pocket.anchor === building.id)
      .sort((a, b) => a.pocket.level - b.pocket.level);
  }

  /** Where a new floor goes: 24 cells east of whichever is furthest east, the map's edge or another
   *  floor's east edge. So `[gridSize[0] + 24, 0]` when there are no floors yet. */
  function nextFloorSpot(scn) {
    let x = scn.gridSize[0];
    for (const r of scn.regions) if (MapOps.isFloor(r)) x = Math.max(x, r.position[0] + r.size[0]);
    return [x + MapOps.FLOOR_GAP, 0];
  }

  /** The level rules addFloor and setFloorLevel share, as an error message or null. */
  function levelProblem(scn, building, floor, level) {
    if (!Number.isInteger(level) || level === 0) return "A floor's level is a whole number other than 0";
    if (building && floorsOf(scn, building).some(f => f !== floor && f.pocket.level === level))
      return `"${building.name}" already has a floor at level ${level}`;
    return null;
  }

  /** Adds a floor of `building`: a region with `pocket: {anchor, level}`, laid out beside the map.
   *  props: {name, level, size}. Returns {region} or {error}. */
  function addFloor(scn, building, props, set) {
    if (!building.wall) return {error: `"${building.name}" has no walls`};
    const name = (props.name || "").trim();
    if (!name) return {error: "A region needs a name"};
    if (scn.regions.some(o => o.name === name)) return {error: `Another region is already called "${name}"`};
    const err = levelProblem(scn, building, undefined, props.level);
    if (err) return {error: err};
    const size = (props.size || [Math.min(building.size[0], 32), Math.min(building.size[1], 32)]).slice();
    if (size[0] < 2 || size[0] > 32 || size[1] < 2 || size[1] > 32)
      return {error: "A floor is between 2 and 32 cells on each side"};
    const region = {id: MapOps.newId("rgn"), name, description: "", wall: building.wall,
      ground: building.ground || "wood", groundTexture: building.groundTexture || "floorboards",
      openings: [], position: nextFloorSpot(scn), size,
      ambience: {day: "quiet_indoor"}, pocket: {anchor: building.id, level: props.level}};
    set(scn, "regions", [...scn.regions, region]);
    return {region};
  }

  /** Moves a floor to another level of its building, as a fresh `pocket`. Returns {} or {error}. */
  function setFloorLevel(scn, floor, level, set) {
    const building = scn.regions.find(r => r.id === floor.pocket.anchor) || null;
    const err = levelProblem(scn, building, floor, level);
    if (err) return {error: err};
    set(floor, "pocket", {anchor: floor.pocket.anchor, level});
    return {};
  }

  // ---------------------------------------------------------------- portals
  /** The object entity a portal leads to, or null. */
  function portalPartner(scn, e) {
    return e && e.portal ? (scn.entities.find(o => o.id === e.portal.to) || null) : null;
  }

  /** Deletes a's portal, and the partner's too when it points back at a. */
  function unlinkPortal(scn, a, set) {
    if (!a || !a.portal) return;
    const p = portalPartner(scn, a);
    set(a, "portal", undefined);
    if (p && p.portal && p.portal.to === a.id) set(p, "portal", undefined);
  }

  /** Links two object entities as a portal pair, the game's "Link Portal": both ends point at each
   *  other, and any old links come off first. Returns {} or {error}. */
  function linkPortal(scn, a, b, set) {
    if (a === b) return {error: "A portal needs two different ends"};
    for (const e of [a, b]) {
      if (!e || e.type !== "object") return {error: "Only objects can be portal ends"};
      if (isDoor(scn, e)) return {error: "A door can't be a portal"};
    }
    unlinkPortal(scn, a, set);
    unlinkPortal(scn, b, set);
    set(a, "portal", {to: b.id});
    set(b, "portal", {to: a.id});
    return {};
  }

  // ---------------------------------------------------------------- openings and doorways
  /** Which sides of `region`'s border the opening `o` (a `[x, y]` cell) opens: none at all off the
   *  rectangle; the edge sides the cell sits on (a corner has two); just the entry's own third value
   *  when it has one and it is among them. */
  function openingSides(region, o) {
    const r = MapOps.rect(region);
    if (!MapOps.inRect(r, o[0], o[1])) return [];
    const sides = [];
    if (o[1] === r[3]) sides.push("n");
    if (o[0] === r[2]) sides.push("e");
    if (o[1] === r[1]) sides.push("s");
    if (o[0] === r[0]) sides.push("w");
    return o.length > 2 && sides.includes(o[2]) ? [o[2]] : sides;
  }

  /** Whether `region` has an opening at `cell` that opens `side`. */
  const opens = (region, cell, side) =>
    (region.openings || []).some(g => eqCell(g, cell) && openingSides(region, g).includes(side));

  /** Every doorway in the scenario, as the game works them out: an opening on a walled region's
   *  border, crossed from a cell inside it to the cell outside, where every walled region holding
   *  exactly one of the two cells opens its side of the crossing. A door in one wall but not the
   *  other is no doorway. Entries are {cell, out, room, key}: cell is the one inside room, room is
   *  the smallest region the wall splits (the first wins a tie), and the key is "<x>,<y>,x|y" from
   *  the lower cell and the crossing's axis. */
  function doorways(scn) {
    const walled = scn.regions.filter(r => r.wall), list = [], seen = new Set();
    for (const o of walled) for (const g of o.openings || []) for (const side of openingSides(o, g)) {
      const cell = [g[0], g[1]], beyond = [cell[0] + STEP[side][0], cell[1] + STEP[side][1]];
      const r = MapOps.rect(o);
      if (!MapOps.inRect(r, cell[0], cell[1]) || MapOps.inRect(r, beyond[0], beyond[1])) continue;
      const lo = cell[0] < beyond[0] || cell[1] < beyond[1] ? cell : beyond;
      const key = `${lo[0]},${lo[1]},${cell[0] !== beyond[0] ? "x" : "y"}`;
      if (seen.has(key)) continue;
      const insideOf = w => MapOps.inRect(MapOps.rect(w), cell[0], cell[1]);
      const split = walled.filter(w => insideOf(w) !== MapOps.inRect(MapOps.rect(w), beyond[0], beyond[1]));
      const crossed = (w, c) => opens(w, c, sideBetween(c, c === cell ? beyond : cell));
      if (!split.every(w => crossed(w, insideOf(w) ? cell : beyond))) continue;
      seen.add(key);
      const room = split.reduce((m, w) => w.size[0] * w.size[1] < m.size[0] * m.size[1] ? w : m);
      const inside = MapOps.inRect(MapOps.rect(room), cell[0], cell[1]);
      list.push({cell: inside ? cell : beyond, out: inside ? beyond : cell, room, key});
    }
    return list;
  }

  // ---------------------------------------------------------------- door objects
  /** Whether e is an object entity placed from one of the four door templates. */
  function isDoor(scn, e) {
    if (!e || e.type !== "object") return false;
    const t = objectTemplates(scn).find(t => t.id === e.templateId);
    return !!t && DOOR_KINDS.includes(t.door);
  }

  /** The two cells a door object separates (one apart in x or y), lower one first. */
  const doorCells = e => (e.size || [1, 0])[0] === 0
    ? [[e.pos[0] - 1, e.pos[1]], [e.pos[0], e.pos[1]]]
    : [[e.pos[0], e.pos[1] - 1], [e.pos[0], e.pos[1]]];

  /** The doorway key of a door object: "<x>,<y>,x|y" from its lower cell and crossing axis. */
  function doorKeyOf(e) {
    const [a, b] = doorCells(e);
    return `${a[0]},${a[1]},${a[0] !== b[0] ? "x" : "y"}`;
  }

  /** Where a door object sits on a doorway: on the wall line, zero-wide along it. */
  function doorPlacement(dw) {
    const rot = dw.cell[0] !== dw.out[0] ? 1 : 0;
    return {pos: [Math.max(dw.cell[0], dw.out[0]), Math.max(dw.cell[1], dw.out[1])], rot, size: rot ? [0, 1] : [1, 0]};
  }

  /** The scenario's door objects, keyed by the doorway they sit on. */
  function doorsByKey(scn) {
    const m = new Map();
    for (const e of scn.entities) if (isDoor(scn, e)) {
      const k = doorKeyOf(e);
      if (!m.has(k)) m.set(k, []);
      m.get(k).push(e);
    }
    return m;
  }

  /** Finds the kind's one door template (by kind and English name), creating it on first use. */
  function doorTemplate(scn, kind, set) {
    const name = DOOR_NAMES[kind];
    let t = objectTemplates(scn).find(t => t.door === kind && t.name === name);
    if (t) return t;
    t = {id: MapOps.newId("otpl"), name, size: [1, 0], walkability: 1, door: kind, heightM: 2.1, maxHp: 60};
    set(scn, "objectTemplates", [...objectTemplates(scn), t]);
    return t;
  }

  /** Hangs a door object of `kind` on doorway dw, named after its template ("Door 2"). */
  function hangDoor(scn, dw, kind, set) {
    const tpl = doorTemplate(scn, kind, set), {pos, rot, size} = doorPlacement(dw);
    const e = {id: MapOps.newId("obj"), type: "object",
      name: MapOps.nextName(tpl.name, scn.entities.map(o => o.name)),
      pos, size, hp: 60, maxHp: 60, inventory: [], statusEffects: [], templateId: tpl.id};
    if (rot) e.rot = rot;
    set(scn, "entities", [...scn.entities, e]);
    return e;
  }

  /** Puts a doorway's doors into a state: kind "none" takes them off, another kind moves the ones
   *  there onto that kind's template (with new names) or hangs one when there are none. */
  function setDoorwayKind(scn, dw, kind, set) {
    const doors = doorsByKey(scn).get(dw.key) || [];
    if (kind === "none") {
      if (doors.length) set(scn, "entities", scn.entities.filter(e => !doors.includes(e)));
      return;
    }
    const tpl = doorTemplate(scn, kind, set), names = scn.entities.map(e => e.name);
    for (const d of doors) {
      const name = MapOps.nextName(tpl.name, names);
      set(d, "templateId", tpl.id);
      set(d, "name", name);
      names.push(name);
    }
    if (!doors.length) hangDoor(scn, dw, kind, set);
  }

  /** The doorways into a region: the ones whose room it is. */
  const regionDoorways = (scn, region) => doorways(scn).filter(d => d.room === region);

  /** Sets a region's door kind on the region itself and on each of its doorways. */
  function setRegionDoorKind(scn, region, kind, set) {
    set(region, "door", kind);
    for (const dw of regionDoorways(scn, region)) setDoorwayKind(scn, dw, kind, set);
  }

  /** Hangs a door on every doorway without one, of the room's own kind ("door" by default), leaving
   *  "none" rooms open. Returns how many were hung. */
  function hangAllDoors(scn, set) {
    const have = doorsByKey(scn);
    let hung = 0;
    for (const dw of doorways(scn)) {
      const kind = dw.room.door ?? "door";
      if (kind === "none" || (have.get(dw.key) || []).length) continue;
      hangDoor(scn, dw, kind, set);
      hung++;
    }
    return hung;
  }

  /** Door objects that no longer sit on any doorway (its openings are gone). */
  function strayDoors(scn) {
    const keys = new Set(doorways(scn).map(d => d.key));
    return scn.entities.filter(e => isDoor(scn, e) && !keys.has(doorKeyOf(e)));
  }

  // ---------------------------------------------------------------- locks and keys
  /** A region's doors: the door objects whose two cells its wall splits (exactly one is inside it). */
  function regionDoors(scn, region) {
    const r = MapOps.rect(region);
    return scn.entities.filter(e => isDoor(scn, e)
      && doorCells(e).filter(c => MapOps.inRect(r, c[0], c[1])).length === 1);
  }

  /** Any status effect whose mechanics hold a "locked" entry counts as a lock. */
  const isLock = fx => !!(fx && fx.def && Array.isArray(fx.def.mechanics) && fx.def.mechanics.some(m => m && m.type === "locked"));
  const isLocked = e => (e.statusEffects || []).some(isLock);

  /** True when a region has doors and every one of them is locked. */
  const regionLocked = (scn, region) => {
    const doors = regionDoors(scn, region);
    return doors.length > 0 && doors.every(isLocked);
  };

  /** Locks or unlocks every door of a region; doors already in the wanted state stay as they are.
   *  Returns {count: doors changed} or {error} when it has no doors. */
  function setLocked(scn, region, locked, set) {
    const doors = regionDoors(scn, region);
    if (!doors.length) return {error: `${region.name} has no doors to lock; hang doors first`};
    let count = 0;
    for (const d of doors) {
      if (locked && !isLocked(d)) {
        set(d, "statusEffects", [...(d.statusEffects || []), {id: MapOps.newId("se"),
          def: {desc: "locked", emoji: "🔒", type: "constant", mechanics: [{type: "locked"}]}, appliedAt: 28800}]);
        count++;
      } else if (!locked && isLocked(d)) {
        set(d, "statusEffects", (d.statusEffects || []).filter(fx => !isLock(fx)));
        count++;
      }
    }
    return {count};
  }

  /** Finds the region's key item template, creating it on first use. */
  function keyTemplate(scn, region, set) {
    let t = itemTemplates(scn).find(t => t.opens === region.id);
    if (t) return t;
    t = {id: MapOps.newId("itpl"), name: `${region.name} key`, description: "",
      type: "misc", quality: "common", opens: region.id};
    set(scn, "itemTemplates", [...itemTemplates(scn), t]);
    return t;
  }

  /** Every item template that opens `region`. */
  const keysTo = (scn, region) => itemTemplates(scn).filter(t => t.opens === region.id);

  /** The people (npc or player) carrying a key to the region. */
  const keyHolders = (scn, region) => {
    const ids = new Set(keysTo(scn, region).map(t => t.id));
    return scn.entities.filter(e => (e.type === "npc" || e.type === "player")
      && (e.inventory || []).some(s => ids.has(s.templateId)));
  };

  /** Puts the region's key in someone's inventory, unless they already hold one. */
  function giveKey(scn, region, person, set) {
    const keys = keysTo(scn, region);
    if ((person.inventory || []).some(s => keys.some(t => t.id === s.templateId))) return;
    const tpl = keyTemplate(scn, region, set);
    set(person, "inventory", [...(person.inventory || []), {id: MapOps.newId("it"), templateId: tpl.id, count: 1}]);
  }

  /** Takes every key to the region out of someone's inventory. */
  function takeKey(scn, region, person, set) {
    const ids = new Set(keysTo(scn, region).map(t => t.id));
    const kept = (person.inventory || []).filter(s => !ids.has(s.templateId));
    if (kept.length !== (person.inventory || []).length) set(person, "inventory", kept);
  }

  // ---------------------------------------------------------------- NPC types
  /** Every NPC type: 1.0's npcTemplates first, then any 0.18 hostileNpcTemplates. */
  const npcTypes = scn => [...(scn.npcTemplates || []), ...(scn.hostileNpcTemplates || [])];

  /** Whether t is one of the 0.18 hostileNpcTemplates. */
  const isLegacy = (scn, t) => (scn.hostileNpcTemplates || []).includes(t);

  /** An NPC type's homes, in either form. */
  function homesOf(t) {
    if (Array.isArray(t.homes)) return t.homes;
    return t.regionId != null ? [{regionId: t.regionId, count: t.count ?? 0}] : [];
  }

  /** The stance the game will use for the type. */
  function stanceOf(scn, t) {
    if (isLegacy(scn, t)) return t.stance ?? (t.attacksOnSight === false ? PASSIVE_STANCE : "hostile");
    return t.stance ?? "neutral";
  }

  /** Turns every 0.18 hostileNpcTemplate into a 1.0 npcTemplate (same id, after any existing ones),
   *  gives their homeless NPCs an npcHome, and drops the old list. Returns how many were converted. */
  function convertToNpcTemplates(scn, set) {
    const conv = [];
    for (const t of scn.hostileNpcTemplates || []) {
      const c = {...t, stance: stanceOf(scn, t), homes: homesOf(t)};
      delete c.regionId; delete c.count; delete c.attacksOnSight;
      conv.push(c);
      if (t.regionId != null) for (const e of scn.entities)
        if (e.type === "npc" && e.templateId === t.id && e.npcHome === undefined) set(e, "npcHome", t.regionId);
    }
    if (conv.length) {
      set(scn, "npcTemplates", [...(scn.npcTemplates || []), ...conv]);
      set(scn, "hostileNpcTemplates", undefined);
    }
    return conv.length;
  }

  /** Sets an NPC type's homes. A legacy type can take one home as it is; any other number converts
   *  the scenario first. Returns the template now holding the homes. */
  function setHomes(scn, t, homes, set) {
    if (!isLegacy(scn, t)) { set(t, "homes", homes); return t; }
    if (homes.length === 1) {
      set(t, "regionId", homes[0].regionId);
      set(t, "count", homes[0].count);
      return t;
    }
    convertToNpcTemplates(scn, set);
    const c = (scn.npcTemplates || []).find(n => n.id === t.id);
    set(c, "homes", homes);
    return c;
  }

  /** Sets an NPC type's stance. */
  function setStance(scn, t, stance, set) {
    if (!STANCES.includes(stance)) return {error: `A stance is "neutral", "skittish" or "hostile"`};
    set(t, "stance", stance);
    return {};
  }

  /** Adds an NPC type in the scenario's own form: a 0.18 entry while it only has
   *  hostileNpcTemplates, a 1.0 one (with homes) otherwise. Returns {template} or {error}. */
  function addNpcType(scn, props, set) {
    const name = (props.name || "").trim();
    if (!name) return {error: "An NPC type needs a name"};
    if (npcTypes(scn).some(t => t.name === name)) return {error: `An NPC type is already called "${name}"`};
    if ((scn.hostileNpcTemplates || []).length && !(scn.npcTemplates || []).length) {
      const t = {id: MapOps.newId("htpl"), name, description: "", physicalDescription: "",
        animationId: props.animationId, gender: props.gender, stance: props.stance,
        level: 1, money: 0, lootPoolIds: [], regionId: props.regionId, count: props.count};
      set(scn, "hostileNpcTemplates", [...scn.hostileNpcTemplates, t]);
      return {template: t};
    }
    const t = {id: MapOps.newId("ntpl"), name, description: "", physicalDescription: "",
      animationId: props.animationId, gender: props.gender, stance: props.stance,
      level: 1, money: 0, lootPoolIds: [], homes: [{regionId: props.regionId, count: props.count}]};
    set(scn, "npcTemplates", [...(scn.npcTemplates || []), t]);
    return {template: t};
  }

  return {floorsOf, nextFloorSpot, addFloor, setFloorLevel, portalPartner, linkPortal, unlinkPortal,
    openingSides, doorways, doorKeyOf, doorPlacement, isDoor, doorsByKey, doorTemplate, hangDoor,
    setDoorwayKind, regionDoorways, setRegionDoorKind, hangAllDoors, strayDoors, regionDoors,
    isLocked, regionLocked, setLocked, keyTemplate, keyHolders, giveKey, takeKey,
    npcTypes, isLegacy, homesOf, stanceOf, convertToNpcTemplates, setHomes, setStance, addNpcType};
});
