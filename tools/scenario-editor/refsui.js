"use strict";
// Reference safety in the Scenario Editor: deleting (plainly, or with Shift+Delete "anyway"),
// renaming everywhere, and offering to update free text that mentions an old name. The logic is in
// refs.js; this file is the dialogs around it.

// ---------------------------------------------------------------- dialog
/** Shows a modal; buttons: [{label, value, primary}]. Resolves to the value clicked, or null. */
function openDialog(title, bodyHtml, buttons, onOpen) {
  const dlg = $("dlg");
  dlg.innerHTML = `<form><h3>${esc(title)}</h3><div class="dlg-body">${bodyHtml}</div>
    <div class="dlg-buttons">${buttons.map((b, i) => `<button type="button" data-btn="${i}" class="${b.primary ? "primary" : ""}">${esc(b.label)}</button>`).join("")}</div></form>`;
  // Resolve from the buttons themselves: a dialog's "close" event can arrive late in a background tab.
  return new Promise(resolve => {
    let done = false;
    const finish = v => { if (done) return; done = true; if (dlg.open) dlg.close(); resolve(v); };
    dlg.querySelectorAll("[data-btn]").forEach(b => b.onclick = () => finish(buttons[+b.dataset.btn].value ?? null));
    dlg.querySelector("form").onsubmit = ev => { ev.preventDefault(); const p = buttons.find(b => b.primary); finish(p ? p.value : null); };
    dlg.oncancel = ev => { ev.preventDefault(); finish(null); };
    dlg.onclose = () => finish(null);
    dlg.showModal();
    onOpen?.(dlg);
  });
}

// ---------------------------------------------------------------- delete
const KIND_WORD = {region: "region", object: "object", npc: "person", objectType: "object type", itemType: "item",
  hostileType: "hostile type"};

/** Delete: removes what nothing uses. If something is used, offers "Delete anyway" (force). */
async function deleteThings(sels, force) {
  const ids = sels.map(t => t.id).filter(id => byId(id));
  if (!ids.length || !S.editable) return;
  if (ids.includes(S.scn.playerId)) return toast("The player can't be deleted");
  const used = ids.filter(id => Refs.findRefs(S.scn, id).length);
  if (!used.length && !force) {
    const label = ids.length === 1 ? `Delete ${byId(ids[0]).name}` : `Delete ${ids.length} things`;
    edit(label, () => Refs.forceDelete(S.scn, ids, {}, set));
    S.sels = []; inspect(); draw();
    return;
  }
  return forceDeleteDialog(ids);
}

async function forceDeleteDialog(ids) {
  const regs = ids.map(byId).filter(o => o?.position);
  const firstParent = regs.length ? MapOps.parentOf(S.scn, regs[0]) : null;
  const opts = {replacementRegionId: firstParent && !ids.includes(firstParent.id) ? firstParent.id : null, scheduleMode: "remove", deleteContents: false};
  const regionChoices = [...regions()].filter(r => !ids.includes(r.id)).sort((a, b) => a.name.localeCompare(b.name));
  const what = ids.length === 1 ? `"${byId(ids[0]).name}"` : `${ids.length} things`;
  const body = `
    <p class="note">Only what can't exist without ${esc(what)} is deleted. Everything else that uses it gets the smallest change that keeps it working.</p>
    ${regs.length ? `
      ${field("Schedule blocks there", `<select id="fdMode"><option value="remove">Remove those blocks: the block before takes over the time</option>
        <option value="move">Move those blocks to the replacement region</option></select>`)}
      ${field("Replacement region (for hostile types that live there, and moved blocks)", `<select id="fdRepl"><option value="">none</option>${regionChoices.map(r =>
        `<option value="${esc(r.id)}" ${r.id === opts.replacementRegionId ? "selected" : ""}>${esc(r.name)}</option>`).join("")}</select>`)}
      <label class="check"><input type="checkbox" id="fdContents"> Also delete the rooms and objects inside (people are never deleted)</label>` : ""}
    <div id="fdPreview" class="fd-preview"></div>`;
  const preview = () => {
    const rep = Refs.previewDelete(S.scn, ids, opts);
    const removed = rep.removed.map(r => `<li><b>Delete</b> ${esc(KIND_WORD[r.kind] || r.kind)} ${esc(r.name)}</li>`).join("");
    const changed = rep.changed.map(c => `<li>${esc(c.ownerName || "Scenario")}: ${esc(c.what)}</li>`).join("");
    $("fdPreview").innerHTML = `<div class="kind">What will happen</div><ul>${removed}${changed}</ul>
      ${rep.warnings.length ? `<div class="note warn">${rep.warnings.map(esc).join("<br>")}</div>` : ""}`;
    return rep;
  };
  const choice = await openDialog(`Delete ${what} anyway?`, body,
    [{label: "Cancel", value: null}, {label: "Delete", value: "go", primary: true}], dlg => {
      const sync = () => {
        if ($("fdMode")) opts.scheduleMode = $("fdMode").value;
        if ($("fdRepl")) opts.replacementRegionId = $("fdRepl").value || null;
        if ($("fdContents")) opts.deleteContents = $("fdContents").checked;
        preview();
      };
      dlg.querySelectorAll("select, input").forEach(el => el.onchange = sync);
      sync();
    });
  if (choice !== "go") return;
  let rep;
  edit(`Delete ${what} and fix what used it`, () => { rep = Refs.forceDelete(S.scn, ids, opts, set); });
  S.sels = []; inspect(); draw();
  if (rep) toast(`Deleted ${rep.removed.length}, changed ${rep.changed.length}${rep.warnings.length ? `, ${rep.warnings.length} warning${rep.warnings.length === 1 ? "" : "s"}` : ""}`);
}

// ---------------------------------------------------------------- rename
/** Renames anything, updating structured references, then offers to update free-text mentions. */
async function renameThing(o, name) {
  name = (name || "").trim();
  const old = o.name;
  if (!name || name === old) { inspect(); return; }
  let res;
  edit(`Rename ${old} to ${name}`, () => {
    res = Refs.renameEverywhere(S.scn, o.id, name, set);
    if (res.error) throw new Error(res.error);
  });
  if (!res || res.error) { inspect(); return; }
  if (res.count) toast(`Renamed; ${res.count} reference${res.count === 1 ? "" : "s"} updated`);
  await offerMentions(old, name, o.id);
}

/** Lists whole-word mentions of the old name in free text, with a checkbox each, and replaces the ticked ones. */
async function offerMentions(old, name, ownerId) {
  const found = Refs.findMentions(S.scn, old);
  if (!found.length) return;
  const body = `<p class="note">"${esc(old)}" still appears as a whole word in ${found.length} place${found.length === 1 ? "" : "s"} of free text.
    Tick the ones that mean what you renamed, and they'll say "${esc(name)}" instead. Words that only contain it, like a longer name, aren't listed.</p>
    <label class="check"><input type="checkbox" id="mnAll" checked> All</label>
    <div class="mentions">${found.map((m, i) => `<label class="mention"><input type="checkbox" data-m="${i}" checked>
      <span><small>${esc(m.ownerName || "Scenario")} · ${esc(m.field)}</small>
      <span>…${esc(m.before)}<mark>${esc(old)}</mark>${esc(m.after)}…</span></span></label>`).join("")}</div>`;
  const choice = await openDialog("Update mentions too?", body,
    [{label: "Leave the text alone", value: null}, {label: "Replace ticked", value: "go", primary: true}], dlg => {
      $("mnAll").onchange = () => dlg.querySelectorAll("[data-m]").forEach(c => c.checked = $("mnAll").checked);
    });
  if (choice !== "go") return;
  const picked = [...$("dlg").querySelectorAll("[data-m]:checked")].map(c => found[+c.dataset.m]);
  if (!picked.length) return;
  let n = 0;
  edit(`Update ${picked.length} mention${picked.length === 1 ? "" : "s"} of ${old}`, () => { n = Refs.replaceMentions(picked, old, name, set); });
  toast(`Updated ${n} mention${n === 1 ? "" : "s"}`);
}
