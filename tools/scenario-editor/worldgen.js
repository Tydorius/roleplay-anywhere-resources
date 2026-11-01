"use strict";
// World generation in the Scenario Editor: the "New world from an idea…" dialog and the
// "Re-roll layout" button. The backend (worldgen_editor.py) drives the standalone generator
// in ../world-generator; each result opens here as a new workspace, with plan.json kept
// beside it so it can be re-rolled. The generator needs your own model provider and key.

const WG_PHASES = {P1: "World plan", P2: "Prop catalogue", P3: "Buildings", P4: "Zones",
                   P5: "People", layout: "Placing everything", build: "Building the scenario"};

let wgMeta = null;      // {providers, hasProvidersFile, providersPath, extensions}, from /api/worldgen/meta
let wgEstimateTimer = 0;

const wgNum = n => Number(n || 0).toLocaleString("en-US");
const wgSeedOf = el => { const s = parseInt(el.value, 10); return Number.isFinite(s) ? s : 1; };

/** openDialog whose primary button first runs `onGo(dlg)`: it returns the form values
 * (and the dialog proceeds), or null to stay open (a toast said why). The values must be
 * read at click time — the next dialog replaces this one's DOM. */
function wgFormDialog(title, bodyHtml, onGo, onOpen) {
  let picked = null;
  const promise = openDialog(title, bodyHtml,
    [{label: "Cancel", value: null}, {label: title.startsWith("Re-roll") ? "Re-roll" : "Generate world", value: "go", primary: true}],
    dlg => {
      onOpen?.(dlg);
      const go = dlg.querySelector(".dlg-buttons .primary");
      const orig = go.onclick;
      go.onclick = () => { picked = onGo(dlg); if (picked !== null) orig(); };
      const origSubmit = dlg.querySelector("form").onsubmit;   // Enter does the same as the button
      dlg.querySelector("form").onsubmit = ev => { ev.preventDefault(); picked = onGo(dlg); if (picked !== null) origSubmit(ev); };
    });
  return {promise, picked: () => picked};
}

// ---------------------------------------------------------------- New world from an idea…
async function newWorldDialog() {
  wgMeta = await api("/api/worldgen/meta");
  const form = wgFormDialog("New world from an idea…", wgFormHtml(), dlg => {
    const idea = $("wgIdea").value.trim();
    if (!idea) { toast("Type the idea first"); return null; }
    return {
      idea,
      provider: $("wgProvider").value,
      seed: wgSeedOf($("wgSeed")),
      extensions: [...dlg.querySelectorAll("[data-ext]:checked")].map(cb => cb.dataset.ext),
    };
  }, dlg => wgBindForm(dlg));
  const value = await form.promise;   // openDialog resolves to the clicked value itself
  if (value !== "go") return;
  try {
    const r = await api("/api/worldgen/generate", {method: "POST", body: JSON.stringify(form.picked())});
    await wgTrackJob(r.job, "Generating the world…");
  } catch (e) { toast(e.message); }
}

function wgFormHtml() {
  return `
    ${field("The idea, in one line",
            `<textarea id="wgIdea" rows="2" placeholder="a fogbound harbour town of smugglers"></textarea>`,
            "What the world contains; the model describes it, deterministic code places it.")}
    <div class="wg-row">
      ${field("Provider", `<select id="wgProvider">${wgProviderOptions()}</select>`)}
      ${field("Seed", `<input type="number" id="wgSeed" value="1" min="0" step="1">`,
              "Same idea and seed, same world.")}
    </div>
    <details class="wg-prov">
      <summary>Provider settings — your own key, never the game's subscription</summary>
      <div class="wg-row">
        ${field("Name", `<input type="text" id="wgProvName" placeholder="zai">`)}
        ${field("Model", `<input type="text" id="wgProvModel" placeholder="glm-5.3-flash">`)}
      </div>
      ${field("Base URL", `<input type="text" id="wgProvUrl" placeholder="https://api.z.ai/api/paas/v4">`)}
      ${field("API key", `<input type="password" id="wgProvKey" placeholder="sk-…" autocomplete="off">`,
              "Stored in the generator's providers.json (gitignored); only its last four characters ever come back to this page.")}
      <button type="button" id="wgProvSave">Save provider</button>
    </details>
    <div class="wg-exts">
      <span class="wg-exts-title">Extensions</span>
      <span class="note">All off: the plain world imports and plays in the unmodded game.</span>
      ${wgMeta.extensions.map(e => `
        <label class="check"><input type="checkbox" data-ext="${esc(e.id)}"> ${esc(e.title)}</label>
        <span class="note">needs ${e.mods.map(m => `<b>${esc(m)}</b>`).join(" + ")} game mod${e.mods.length > 1 ? "s" : ""} — the world won't work right without ${e.mods.length > 1 ? "them" : "it"}</span>`).join("")}
    </div>
    <div class="note" id="wgEstimate"></div>`;
}

function wgBindForm(dlg) {
  const estimate = () => {
    clearTimeout(wgEstimateTimer);
    wgEstimateTimer = setTimeout(async () => {
      const idea = $("wgIdea").value.trim();
      if (!idea) { $("wgEstimate").textContent = ""; return; }
      try {
        const e = (await api("/api/worldgen/estimate?idea=" + encodeURIComponent(idea))).estimate;
        $("wgEstimate").textContent =
          `About ${e.calls} model calls (${e.calls_range[0]}–${e.calls_range[1]} with retries) · `
          + `~${wgNum(e.tokens)} tokens · ${e.minutes_range[0]}–${e.minutes_range[1]} minutes. Your key, your cost.`;
      } catch { $("wgEstimate").textContent = ""; }
    }, 400);
  };
  $("wgIdea").oninput = estimate;
  dlg.querySelectorAll("[data-ext]").forEach(cb => cb.onchange = () => {
    // floors needs portals (its stairs are portals): turning floors on turns portals on too
    const ext = wgMeta.extensions.find(x => x.id === cb.dataset.ext);
    if (cb.checked) for (const need of ext?.requires || []) {
      const el = dlg.querySelector(`[data-ext="${CSS.escape(need)}"]`);
      if (el && !el.checked) { el.checked = true; toast(`${ext.title} also needs the ${need} extension — both are on`); }
    }
    // and turning portals off turns floors off, so floors never runs without its stairs
    if (!cb.checked) for (const other of wgMeta.extensions) {
      if (!(other.requires || []).includes(cb.dataset.ext)) continue;
      const el = dlg.querySelector(`[data-ext="${CSS.escape(other.id)}"]`);
      if (el && el.checked) { el.checked = false; toast(`${other.title} needs ${ext?.title || cb.dataset.ext} — both are off`); }
    }
  });
  $("wgProvSave").onclick = async () => {
    try {
      const r = await api("/api/worldgen/providers", {method: "POST", body: JSON.stringify({
        name: $("wgProvName").value, model: $("wgProvModel").value,
        base_url: $("wgProvUrl").value, api_key: $("wgProvKey").value, max_tokens: 16000})});
      wgMeta.providers = r.providers;
      $("wgProvider").innerHTML = wgProviderOptions();
      $("wgProvKey").value = "";
      toast("Provider saved");
    } catch (e) { toast(e.message); }
  };
  estimate();
}

function wgProviderOptions() {
  return wgMeta.providers.length
    ? wgMeta.providers.map(p => `<option value="${esc(p.name)}">${esc(p.name)}${p.model ? " · " + esc(p.model) : ""}${p.ready ? "" : " (no key set)"}</option>`).join("")
    : `<option value="">none configured — add one below</option>`;
}

// ---------------------------------------------------------------- job progress
/** Polls the running job, showing each phase; resolves with the finished job (or null
 * when it was cancelled), after dealing with the result. */
async function wgTrackJob(first, title) {
  const j = await new Promise(resolve => {
    let result = null;
    // Resolve from the poll and from openDialog's own promise, never from the "close" event:
    // a dialog's close event can arrive late, or not at all, in a background tab.
    openDialog(title, `<div class="wg-prog" id="wgProg"></div>`,
      [{label: "Cancel", value: "cancel"}], dlg => {
        wgRenderProgress($("wgProg"), first);
        (async () => {                       // the poll loop; stops when the dialog is gone
          while (dlg.open && !result) {
            await new Promise(r => setTimeout(r, 1500));
            let j = null;
            try { j = (await api("/api/worldgen/job")).job; } catch { continue; }
            if (!j || j.id !== first.id) continue;
            wgRenderProgress($("wgProg"), j);
            if (j.state !== "running") { result = j; dlg.close(); resolve(j); }
          }
        })();
      }).then(() => {
        if (result) return;                  // finished: the poll already handed the job on
        // the user closed the dialog (Cancel button or Esc): ask the backend to stop
        api("/api/worldgen/cancel", {method: "POST"}).catch(() => {});
        (async () => {
          let j = null;
          for (;;) {
            j = null;
            try { j = (await api("/api/worldgen/job")).job; } catch {}
            if (!j || j.id !== first.id || j.state !== "running") break;
            await new Promise(r => setTimeout(r, 700));
          }
          // a job can finish before the cancel lands: report how it really ended
          resolve(j && j.id === first.id ? j : null);
        })();
      });
  });
  if (j) await wgFinished(j);
  else toast("Generation cancelled");
  return j;
}

function wgRenderProgress(el, j) {
  const name = WG_PHASES[j.phase] || (j.phase === "done" ? "Done" : j.phase);
  const counts = j.kind === "reroll"
    ? "" : `<div class="wg-counts">${j.calls} call${j.calls === 1 ? "" : "s"} so far · ${wgNum(j.tokens)} tokens</div>`;
  el.innerHTML = `
    <div class="wg-phase">${esc(name)}</div>
    <div class="wg-label">${esc(j.label || "")}</div>
    ${counts}
    ${j.kind === "reroll" ? `<p class="note">No model calls: the same world, placed again from its saved plan.</p>` : ""}`;
}

async function wgFinished(j) {
  if (j.state === "done" && j.source) {
    await loadSources(j.source);
    const s = j.summary || {};
    toast(`Built ${s.npcs ?? "?"} people in ${s.buildings ?? "?"} buildings — opened as a workspace`);
  } else if (j.state === "failed") {
    await openDialog("The generation failed", `
      <p class="note warn">${esc(j.error || "unknown error")}</p>
      <p class="note">Every model call is logged with its prompt and reply:<br>
        <code>${esc(j.logDir || j.outDir || "")}</code></p>`,
      [{label: "Close", value: null, primary: true}]);
  } else {
    toast("Generation cancelled");
  }
}

// ---------------------------------------------------------------- re-roll layout
async function rerollDialog() {
  let info;
  try { info = await api("/api/worldgen/plan?source=" + encodeURIComponent(S.source)); }
  catch (e) { toast(e.message); return; }
  if (!info.has) return;
  const ext = info.extensions.length
    ? `Keeps this world's extensions (${info.extensions.join(", ")}).` : "This world uses no mod extensions.";
  const form = wgFormDialog("Re-roll layout", `
      <p class="note">A fresh layout of the same world from its saved plan — no model calls, a few
        seconds. It opens as a new workspace; this one stays as it is. ${esc(ext)}</p>
      ${field("New seed", `<input type="number" id="wgRrSeed" value="${1 + Math.floor(Math.random() * 9999)}" min="0" step="1">`,
              "A different seed places everything differently.")}`,
    dlg => ({seed: wgSeedOf($("wgRrSeed"))}));
  const value = await form.promise;   // openDialog resolves to the clicked value itself
  if (value !== "go") return;
  try {
    const r = await api("/api/worldgen/reroll?source=" + encodeURIComponent(S.source),
                        {method: "POST", body: JSON.stringify(form.picked())});
    await wgTrackJob(r.job, "Re-rolling the layout…");
  } catch (e) { toast(e.message); }
}

async function updateRerollButton() {
  const b = $("reroll");
  if (!S.source.startsWith("work/")) { b.hidden = true; return; }
  try { b.hidden = !(await api("/api/worldgen/plan?source=" + encodeURIComponent(S.source))).has; }
  catch { b.hidden = true; }
}

$("newWorld").onclick = () => newWorldDialog().catch(e => toast(e.message));
$("reroll").onclick = () => rerollDialog().catch(e => toast(e.message));
updateRerollButton();
