"use strict";
// Reference repair for the Scenario Editor: keeps a scenario coherent when regions, entities or
// templates are force-deleted or renamed, and finds whole-word mentions in free text. Every change
// to scenario data goes through the caller's set(obj, key, value) callback (value === undefined
// deletes the key); arrays are always replaced with new ones, never mutated in place.

(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./schedule.js"));
  else root.Refs = factory(root.Schedule);
})(typeof self !== "undefined" ? self : this, function (Schedule) {

  function isPerson(e) {
    return !!e && (e.type === "npc" || e.type === "player");
  }

  function rectInside(ax, ay, aw, ah, bx, by, bw, bh) {
    return ax >= bx && ay >= by && ax + aw <= bx + bw && ay + ah <= by + bh;
  }

  // Region a is inside region b when a's rectangle lies wholly within b's.
  function regionInside(a, b) {
    return rectInside(a.position[0], a.position[1], a.size[0], a.size[1],
      b.position[0], b.position[1], b.size[0], b.size[1]);
  }

  // An entity is inside a region when its whole footprint fits; people are 1 x 1.
  function entityInside(e, r) {
    const w = e.type === "object" && Array.isArray(e.size) ? e.size[0] : 1;
    const h = e.type === "object" && Array.isArray(e.size) ? e.size[1] : 1;
    return rectInside(e.pos[0], e.pos[1], w, h, r.position[0], r.position[1], r.size[0], r.size[1]);
  }

  function escapeRegExp(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function plainSet(o, k, v) {
    if (v === undefined) delete o[k];
    else o[k] = v;
  }

  function blocksLabel(n) {
    return n + (n === 1 ? " schedule block" : " schedule blocks");
  }

  function findRefs(scn, id) {
    const out = [];
    const region = (scn.regions || []).find(r => r.id === id);
    if (region) {
      for (const ent of scn.entities || []) {
        if (!isPerson(ent) || !Array.isArray(ent.schedule)) continue;
        for (const b of ent.schedule) {
          if (b.location === region.name)
            out.push({kind: "schedule", ownerId: ent.id, ownerName: ent.name,
              detail: b.start + "–" + b.end + " " + b.role});
        }
      }
      for (const ev of scn.calendar || []) {
        if (ev.location === region.name)
          out.push({kind: "calendar", ownerId: ev.id, ownerName: ev.name, detail: ev.name});
      }
      for (const t of scn.hostileNpcTemplates || []) {
        if (t.regionId === id)
          out.push({kind: "hostileHome", ownerId: t.id, ownerName: t.name, detail: t.name});
      }
      return out;
    }
    const objectType = (scn.objectTemplates || []).find(t => t.id === id);
    if (objectType) {
      for (const ent of scn.entities || []) {
        if (ent.type === "object" && ent.templateId === id)
          out.push({kind: "placed", ownerId: ent.id, ownerName: ent.name, detail: ent.name});
      }
      for (const t of scn.objectTemplates || []) {
        for (const eff of t.startingEffects || []) {
          for (const e of eff.endState || []) {
            if (e.templateId === id)
              out.push({kind: "effectSpawn", ownerId: t.id, ownerName: t.name,
                detail: eff.desc != null ? eff.desc : "endState"});
          }
        }
      }
      return out;
    }
    const itemType = (scn.itemTemplates || []).find(t => t.id === id);
    if (itemType) {
      for (const ent of scn.entities || []) {
        for (const st of ent.inventory || []) {
          if (st.templateId === id)
            out.push({kind: "carried", ownerId: ent.id, ownerName: ent.name, detail: "x" + st.count});
        }
        const eq = ent.equipment;
        if (eq && typeof eq === "object") {
          for (const slot of Object.keys(eq)) {
            if (eq[slot] && eq[slot].templateId === id)
              out.push({kind: "equipped", ownerId: ent.id, ownerName: ent.name, detail: slot});
          }
        }
        const stock = ent.merchant && ent.merchant.stock;
        for (const st of stock || []) {
          if (st.templateId === id)
            out.push({kind: "stock", ownerId: ent.id, ownerName: ent.name, detail: "x" + st.count});
        }
      }
      for (const t of (scn.objectTemplates || []).concat(scn.hostileNpcTemplates || [])) {
        if (Array.isArray(t.lootPoolIds) && t.lootPoolIds.indexOf(id) !== -1)
          out.push({kind: "loot", ownerId: t.id, ownerName: t.name, detail: "lootPoolIds"});
      }
      for (const t of scn.objectTemplates || []) {
        for (const eff of t.startingEffects || []) {
          for (const e of eff.endState || []) {
            if (e.type === "spawnItemOnSelf" && e.item && e.item.name === itemType.name)
              out.push({kind: "effectItem", ownerId: t.id, ownerName: t.name,
                detail: eff.desc != null ? eff.desc : "endState"});
          }
        }
      }
      return out;
    }
    const hostileType = (scn.hostileNpcTemplates || []).find(t => t.id === id);
    if (hostileType) {
      for (const ent of scn.entities || []) {
        if (ent.type === "npc" && ent.templateId === id)
          out.push({kind: "placed", ownerId: ent.id, ownerName: ent.name, detail: ent.name});
      }
      return out;
    }
    return [];
  }

  function forceDelete(scn, ids, opts, set) {
    opts = opts || {};
    const report = {removed: [], changed: [], warnings: []};
    const scheduleMode = opts.scheduleMode === "move" ? "move" : "remove";
    const deleteContents = opts.deleteContents === true;
    let replacementId = opts.replacementRegionId != null ? opts.replacementRegionId : null;
    if (replacementId != null) {
      const rep = (scn.regions || []).find(r => r.id === replacementId);
      if (!rep) replacementId = null;
      else if ((ids || []).indexOf(replacementId) !== -1) {
        report.warnings.push("replacement region " + rep.name +
          " is itself being deleted; treating it as no replacement");
        replacementId = null;
      }
    }

    function noteChanged(owner, what) {
      report.changed.push({ownerId: owner.id, ownerName: owner.name, what: what});
    }

    function removeEntity(ent, kind) {
      set(scn, "entities", scn.entities.filter(e => e.id !== ent.id));
      report.removed.push({id: ent.id, name: ent.name, kind: kind});
    }

    // Replaces every block whose location equals `from` with a copy at `to`; returns how many.
    function moveBlocks(ent, from, to) {
      let n = 0;
      const next = ent.schedule.map(b => {
        if (b.location !== from) return b;
        n++;
        return Object.assign({}, b, {location: to});
      });
      if (n > 0) set(ent, "schedule", next);
      return n;
    }

    // Removes every block at `name` with Schedule.remove, highest index first, so the block
    // before each removed block takes over its time.
    function removeBlocks(ent, name) {
      let sch = ent.schedule;
      const hits = [];
      for (let i = 0; i < sch.length; i++) if (sch[i].location === name) hits.push(i);
      if (!hits.length) return;
      for (let k = hits.length - 1; k >= 0; k--) sch = Schedule.remove(sch, hits[k]);
      if (sch.length === 1 && sch[0].location === name) {
        set(ent, "schedule", []);
        noteChanged(ent, "schedule emptied (every block was at " + name + ")");
        report.warnings.push("every schedule block of " + ent.name +
          " was at " + name + "; the schedule is now empty");
        return;
      }
      set(ent, "schedule", sch);
      noteChanged(ent, "removed " + blocksLabel(hits.length) + " at " + name);
    }

    // Strips matching endState entries from one template's effects; the effects themselves stay.
    function stripEndState(t, match, say) {
      const effs = t.startingEffects;
      if (!Array.isArray(effs)) return;
      for (let i = 0; i < effs.length; i++) {
        const eff = effs[i];
        const es = eff.endState;
        if (!Array.isArray(es)) continue;
        let n = 0;
        for (const e of es) if (match(e)) n++;
        if (!n) continue;
        const label = eff.desc != null ? "\"" + eff.desc + "\"" : "effect #" + (i + 1);
        set(eff, "endState", es.filter(e => !match(e)));
        report.changed.push({ownerId: t.id, ownerName: t.name, what: say(n) + " from " + label});
      }
    }

    function deleteObjectType(ot) {
      set(scn, "objectTemplates", scn.objectTemplates.filter(t => t.id !== ot.id));
      report.removed.push({id: ot.id, name: ot.name, kind: "objectType"});
      for (const ent of scn.entities.slice()) {
        if (ent.type === "object" && ent.templateId === ot.id) removeEntity(ent, "object");
      }
      for (const t of scn.objectTemplates) {
        stripEndState(t, e => e.templateId === ot.id,
          n => "removed " + n + (n === 1 ? " endState spawn" : " endState spawns") + " of " + ot.name);
      }
    }

    function deleteItemType(it) {
      const name = it.name;
      set(scn, "itemTemplates", scn.itemTemplates.filter(t => t.id !== it.id));
      report.removed.push({id: it.id, name: name, kind: "itemType"});
      for (const ent of scn.entities.slice()) {
        if (Array.isArray(ent.inventory)) {
          const next = ent.inventory.filter(s => s.templateId !== it.id);
          if (next.length !== ent.inventory.length) {
            const n = ent.inventory.length - next.length;
            set(ent, "inventory", next);
            noteChanged(ent, "removed " + n + (n === 1 ? " inventory stack" : " inventory stacks") + " of " + name);
          }
        }
        const eq = ent.equipment;
        if (eq && typeof eq === "object") {
          const slots = Object.keys(eq).filter(s => eq[s] && eq[s].templateId === it.id);
          for (const s of slots) set(eq, s, undefined);
          if (slots.length) noteChanged(ent, "unequipped " + name + " from " + slots.join(", "));
        }
        const merchant = ent.merchant;
        if (merchant && Array.isArray(merchant.stock)) {
          const next = merchant.stock.filter(s => s.templateId !== it.id);
          if (next.length !== merchant.stock.length) {
            const n = merchant.stock.length - next.length;
            set(merchant, "stock", next);
            noteChanged(ent, "removed " + n + (n === 1 ? " merchant stock stack" : " merchant stock stacks") + " of " + name);
          }
        }
      }
      for (const t of scn.objectTemplates.concat(scn.hostileNpcTemplates)) {
        if (!Array.isArray(t.lootPoolIds)) continue;
        const next = t.lootPoolIds.filter(x => x !== it.id);
        if (next.length !== t.lootPoolIds.length) {
          set(t, "lootPoolIds", next);
          noteChanged(t, "removed " + name + " from the loot pool");
        }
      }
      for (const t of scn.objectTemplates) {
        stripEndState(t,
          e => e.type === "spawnItemOnSelf" && e.item && e.item.name === name,
          n => "removed " + n + (n === 1 ? " spawnItemOnSelf entry" : " spawnItemOnSelf entries") + " of " + name);
      }
    }

    function deleteHostileType(ht) {
      set(scn, "hostileNpcTemplates", scn.hostileNpcTemplates.filter(t => t.id !== ht.id));
      report.removed.push({id: ht.id, name: ht.name, kind: "hostileType"});
      for (const ent of scn.entities) {
        if (ent.type === "npc" && ent.templateId === ht.id) {
          set(ent, "templateId", undefined);
          noteChanged(ent, "templateId removed; now an ordinary hostile");
        }
      }
    }

    function deleteRegion(region) {
      if (replacementId === region.id) {
        report.warnings.push("replacement region " + region.name +
          " is itself being deleted; treating it as no replacement");
        replacementId = null;
      }
      const repl = replacementId != null
        ? ((scn.regions || []).find(r => r.id === replacementId) || null) : null;
      const name = region.name;
      let innerRegions = [];
      let innerObjects = [];
      if (deleteContents) {
        innerRegions = (scn.regions || []).filter(r => r !== region && regionInside(r, region));
        innerObjects = (scn.entities || []).filter(e => e.type === "object" && entityInside(e, region));
      }
      set(scn, "regions", scn.regions.filter(r => r.id !== region.id));
      report.removed.push({id: region.id, name: name, kind: "region"});

      // Hostile types homed here: rehome onto the replacement, or delete the type outright.
      // People whose schedule was moved by a rehome are excluded from the general pass below.
      const handled = new Set();
      for (const t of scn.hostileNpcTemplates.slice()) {
        if (t.regionId !== region.id) continue;
        if (repl) {
          set(t, "regionId", repl.id);
          noteChanged(t, "home region moved to " + repl.name);
          for (const ent of scn.entities) {
            if (ent.type !== "npc" || ent.templateId !== t.id || !Array.isArray(ent.schedule)) continue;
            const n = moveBlocks(ent, name, repl.name);
            if (n > 0) {
              noteChanged(ent, "moved " + blocksLabel(n) + " to " + repl.name);
              handled.add(ent.id);
            }
          }
        } else {
          deleteHostileType(t);
        }
      }

      for (const ent of scn.entities) {
        if (!isPerson(ent) || !Array.isArray(ent.schedule) || handled.has(ent.id)) continue;
        const hits = ent.schedule.filter(b => b.location === name).length;
        if (!hits) continue;
        if (scheduleMode === "move" && repl) {
          noteChanged(ent, "moved " + blocksLabel(moveBlocks(ent, name, repl.name)) + " to " + repl.name);
        } else {
          if (scheduleMode === "move")
            report.warnings.push("no replacement region for " + name + "; removed " + ent.name +
              "'s schedule blocks instead of moving them");
          removeBlocks(ent, name);
        }
      }

      for (const ev of scn.calendar || []) {
        if (ev.location === name) {
          set(ev, "location", undefined);
          noteChanged(ev, "location removed; the event now happens anywhere");
        }
      }

      if (deleteContents) {
        for (const child of innerRegions) {
          if ((scn.regions || []).some(r => r.id === child.id)) deleteRegion(child);
        }
        for (const o of innerObjects) {
          if ((scn.entities || []).some(e => e.id === o.id)) removeEntity(o, "object");
        }
      }
    }

    function processId(id, warnMissing) {
      const region = (scn.regions || []).find(x => x.id === id);
      if (region) { deleteRegion(region); return true; }
      const ent = (scn.entities || []).find(x => x.id === id);
      if (ent) {
        if (ent.id === scn.playerId) {
          report.warnings.push("refusing to delete the player " + ent.name);
          return true;
        }
        removeEntity(ent, ent.type === "object" ? "object" : "npc");
        return true;
      }
      const ot = (scn.objectTemplates || []).find(x => x.id === id);
      if (ot) { deleteObjectType(ot); return true; }
      const it = (scn.itemTemplates || []).find(x => x.id === id);
      if (it) { deleteItemType(it); return true; }
      const ht = (scn.hostileNpcTemplates || []).find(x => x.id === id);
      if (ht) { deleteHostileType(ht); return true; }
      if (warnMissing) report.warnings.push("nothing in the scenario has id " + id);
      return false;
    }

    for (const id of ids || []) processId(id, true);
    return report;
  }

  function previewDelete(scn, ids, opts) {
    return forceDelete(structuredClone(scn), ids, opts, plainSet);
  }

  function renameEverywhere(scn, id, newName, set) {
    const trimmed = typeof newName === "string" ? newName.trim() : "";
    if (!trimmed) return {error: "the new name is empty"};

    const region = (scn.regions || []).find(r => r.id === id);
    if (region) {
      if ((scn.regions || []).some(r => r.id !== id && r.name === trimmed))
        return {error: "a region is already named " + trimmed};
      const old = region.name;
      let count = 0;
      for (const ent of scn.entities || []) {
        if (!isPerson(ent) || !Array.isArray(ent.schedule)) continue;
        let n = 0;
        const next = ent.schedule.map(b => {
          if (b.location !== old) return b;
          n++;
          return Object.assign({}, b, {location: trimmed});
        });
        if (n > 0) { set(ent, "schedule", next); count += n; }
      }
      for (const ev of scn.calendar || []) {
        if (ev.location === old) { set(ev, "location", trimmed); count++; }
      }
      set(region, "name", trimmed);
      return {count: count};
    }

    const itemType = (scn.itemTemplates || []).find(t => t.id === id);
    if (itemType) {
      if ((scn.itemTemplates || []).some(t => t.id !== id && t.name === trimmed))
        return {error: "an item type is already named " + trimmed};
      const old = itemType.name;
      let count = 0;
      for (const t of scn.objectTemplates || []) {
        for (const eff of t.startingEffects || []) {
          const es = eff.endState;
          if (!Array.isArray(es)) continue;
          const match = e => e.type === "spawnItemOnSelf" && e.item && e.item.name === old;
          let n = 0;
          for (const e of es) if (match(e)) n++;
          if (!n) continue;
          set(eff, "endState", es.map(e => match(e)
            ? Object.assign({}, e, {item: Object.assign({}, e.item, {name: trimmed})}) : e));
          count += n;
        }
      }
      set(itemType, "name", trimmed);
      return {count: count};
    }

    const ent = (scn.entities || []).find(e => e.id === id);
    if (ent) { set(ent, "name", trimmed); return {count: 0}; }
    const ot = (scn.objectTemplates || []).find(t => t.id === id);
    if (ot) { set(ot, "name", trimmed); return {count: 0}; }
    const ht = (scn.hostileNpcTemplates || []).find(t => t.id === id);
    if (ht) { set(ht, "name", trimmed); return {count: 0}; }
    return {error: "nothing in the scenario has id " + id};
  }

  function findMentions(scn, name, options) {
    options = options || {};
    const out = [];
    const re = new RegExp("(?<![\\p{L}\\p{N}_])" + escapeRegExp(name) + "(?![\\p{L}\\p{N}_])", "gu");
    const excluded = options.excludeOwnerId != null;

    function scan(container, key, ownerId, ownerName, field) {
      if (excluded && ownerId === options.excludeOwnerId) return;
      const str = container == null ? undefined : container[key];
      if (typeof str !== "string") return;
      for (const m of str.matchAll(re)) {
        const start = m.index;
        out.push({
          container: container, key: key, ownerId: ownerId, ownerName: ownerName, field: field,
          start: start,
          before: str.slice(Math.max(0, start - 30), start),
          after: str.slice(start + name.length, start + name.length + 30)
        });
      }
    }

    scan(scn, "worldBackground", null, null, "worldBackground");
    const rules = scn.narrativeRules;
    if (Array.isArray(rules))
      for (let i = 0; i < rules.length; i++) scan(rules, i, null, null, "narrativeRules[" + i + "]");
    for (const r of scn.regions || []) scan(r, "description", r.id, r.name, "description");
    for (const e of scn.entities || []) {
      scan(e, "description", e.id, e.name, "description");
      scan(e, "mindset", e.id, e.name, "mindset");
      scan(e, "physicalDescription", e.id, e.name, "physicalDescription");
      const mem = e.memories;
      if (Array.isArray(mem))
        for (let i = 0; i < mem.length; i++) scan(mem[i], "text", e.id, e.name, "memories[" + i + "].text");
    }
    const types = (scn.objectTemplates || []).concat(scn.itemTemplates || [], scn.hostileNpcTemplates || []);
    for (const t of types) {
      scan(t, "description", t.id, t.name, "description");
      scan(t, "physicalDescription", t.id, t.name, "physicalDescription");
    }
    for (const ev of scn.calendar || []) {
      scan(ev, "name", ev.id, ev.name, "name");
      scan(ev, "missedConsequence", ev.id, ev.name, "missedConsequence");
    }
    (function walk(node, path) {
      if (Array.isArray(node)) {
        for (let i = 0; i < node.length; i++) {
          if (typeof node[i] === "string") scan(node, i, null, null, path + "[" + i + "]");
          else walk(node[i], path + "[" + i + "]");
        }
      } else if (node && typeof node === "object") {
        for (const k of Object.keys(node)) {
          const v = node[k];
          if (typeof v === "string") scan(node, k, null, null, path + "." + k);
          else walk(v, path + "." + k);
        }
      }
    })(scn.quests, "quests");
    return out;
  }

  function replaceMentions(mentions, oldName, newName, set) {
    let count = 0;
    const groups = [];
    const byContainer = new Map();
    for (const m of mentions || []) {
      let byKey = byContainer.get(m.container);
      if (!byKey) { byKey = new Map(); byContainer.set(m.container, byKey); }
      let g = byKey.get(m.key);
      if (!g) {
        g = {container: m.container, key: m.key, starts: []};
        byKey.set(m.key, g);
        groups.push(g);
      }
      g.starts.push(m.start);
    }
    for (const g of groups) {
      const str = g.container == null ? undefined : g.container[g.key];
      if (typeof str !== "string") continue;
      let text = str;
      // Highest start first, so earlier offsets stay valid while lengths change.
      for (const start of g.starts.slice().sort((a, b) => b - a)) {
        if (text.slice(start, start + oldName.length) !== oldName) continue;
        text = text.slice(0, start) + newName + text.slice(start + oldName.length);
        count++;
      }
      if (text !== str) set(g.container, g.key, text);
    }
    return count;
  }

  return {findRefs, forceDelete, previewDelete, renameEverywhere, findMentions, replaceMentions};
});
