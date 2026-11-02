"use strict";
// World generation in the Scenario Editor: the "New world from an idea…" dialog and the
// "Re-roll layout" button. The backend (worldgen_editor.py) drives the standalone generator
// in ../world-generator; each result opens here as a new workspace, with plan.json kept
// beside it so it can be re-rolled. The generator needs your own model provider and key.
//
// The dialog frames the world before building it: pick a mode (quick idea, or the short /
// medium / long questionnaire from the generator's question bank), answer with option chips,
// "Frame it" runs P0 as a short job (the long form adds the model's clarifying questions),
// and the frame's summary is editable before "Generate world" starts the full job.

const WG_PHASES = {P0: "The world frame", P1: "World plan", P2: "Prop catalogue", P3: "Buildings", P4: "Zones",
                   P5: "People", P6: "Rules, perks, story", layout: "Placing everything", build: "Building the scenario"};
const WG_MODE_LABEL = {quick: "Quick — one idea", short: "Short — 7 questions",
                       medium: "Medium — 14 questions", long: "Long — 14 + the model asks more"};

let wgMeta = null;      // {providers, hasProvidersFile, providersPath, extensions}, from /api/worldgen/meta
let wgBank = null;      // {modes, short, medium, population}, from /api/worldgen/questions
let wgFrame = null;     // the approved frame of the open dialog (its summary may have been edited)
let wgFramedMode = null;
let wgClarifyQuestions = null;   // the long form's clarifying questions, while unanswered
let wgClarify = [];              // [{question, answer}] once answered
let wgFrameBusy = false;
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
  wgBank = await api("/api/worldgen/questions");
  wgFrame = null; wgFramedMode = null; wgClarifyQuestions = null; wgClarify = [];
  const form = wgFormDialog("New world from an idea…", wgFormHtml(), dlg => {
    const idea = $("wgIdea").value.trim();
    const mode = wgModeOf(dlg);
    if (mode === "quick" && !idea) { toast("Type the idea first"); return null; }
    if (!wgFrame) { toast("Frame the world first — press Frame it"); return null; }
    if ($("wgSummary").value.trim()) wgFrame.summary = $("wgSummary").value.trim();
    return {
      idea,
      provider: $("wgProvider").value,
      seed: wgSeedOf($("wgSeed")),
      extensions: [...dlg.querySelectorAll("[data-ext]:checked")].map(cb => cb.dataset.ext),
      frame: wgFrame,
      questionnaire: {mode, answers: wgAnswers(dlg), population: wgPopulation(dlg)},
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
  const pop = wgBank.population;
  return `
    <div class="wg-modes">${wgBank.modes.map(m =>
      `<button type="button" class="wg-mode${m === "quick" ? " on" : ""}" data-mode="${esc(m)}">${esc(WG_MODE_LABEL[m] || m)}</button>`).join("")}</div>
    ${field("The idea, in one line",
            `<textarea id="wgIdea" rows="2" placeholder="a fogbound harbour town of smugglers"></textarea>`,
            "Everything for the quick form; a steer beside the questionnaires.")}
    <div id="wgQuestions"></div>
    <div class="wg-row">
      ${field("Residents",
              `<div class="wg-pop"><input type="number" id="wgPopLo" value="${pop.default[0]}" min="${pop.min}" max="${pop.max}" step="1"> <span class="note">to</span> <input type="number" id="wgPopHi" value="${pop.default[1]}" min="${pop.min}" max="${pop.max}" step="1"></div>`,
              `How many people live there (${pop.min}–${pop.max}).`)}
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
        <span class="note">needs ${e.mods.map(m => `<b>${esc(m)}</b>`).join(" + ")} game mod${e.mods.length > 1 ? "s" : ""} — ${esc(e.withoutMod)}</span>`).join("")}
    </div>
    <div class="wg-framebar">
      <button type="button" id="wgFrameBtn">Frame it</button>
      <span class="note" id="wgFrameStatus">P0 turns your answers into the World Frame every later phase follows. Frame it, read it, then generate.</span>
    </div>
    <div class="wg-clarity" id="wgClarifyBox" hidden></div>
    <div class="wg-frame" id="wgFrameBox" hidden>
      ${field("The summary — edit it freely", `<textarea id="wgSummary" rows="4"></textarea>`)}
      <details class="wg-frame-view" id="wgFrameView"></details>
    </div>
    <div class="note" id="wgEstimate"></div>`;
}

// ---------------------------------------------------------------- the questions
const wgModeOf = dlg => dlg.querySelector(".wg-mode.on")?.dataset.mode || "quick";

function wgFormQuestions(mode) {
  return mode === "quick" ? [] : wgBank[mode === "long" ? "medium" : mode] || [];
}

function wgRenderQuestions(dlg, mode) {
  const el = $("wgQuestions");
  el.innerHTML = mode === "quick"
    ? `<p class="note">Quick: the idea is everything — the model frames it.</p>`
    : `<div class="wg-qlist">${wgFormQuestions(mode).map(wgQuestionHtml).join("")}</div>`;
  wgBindChips(el);
}

function wgQuestionHtml(q) {
  return `
    <div class="wg-q" data-q="${esc(q.id)}">
      <div class="wg-q-prompt">${esc(q.prompt)}${(q.multi || 1) > 1 ? ` <small class="note">(pick up to ${q.multi})</small>` : ""}</div>
      ${q.free
        ? `<textarea class="wg-other-text" rows="2" placeholder="in your own words (optional)"></textarea>`
        : `<div class="wg-chips" data-multi="${q.multi || 1}">
            ${q.options.map((o, i) => `<button type="button" class="wg-chip" data-i="${i}">${esc(o)}</button>`).join("")}
            <button type="button" class="wg-chip wg-other" data-i="other">Other</button>
            <input type="text" class="wg-other-text" hidden placeholder="your own answer">
          </div>`}
    </div>`;
}

/** Option chips inside `root`: single questions switch, multi questions cap at
 * their limit, Other reveals its text box. Clicking a chip again unticks it. */
function wgBindChips(root) {
  root.querySelectorAll(".wg-chips").forEach(box => {
    const multi = +(box.dataset.multi || 1);
    const otherText = box.querySelector(".wg-other-text");
    box.querySelectorAll(".wg-chip").forEach(ch => ch.onclick = () => {
      if (ch.classList.contains("on")) {
        ch.classList.remove("on");
      } else {
        if (multi === 1) box.querySelectorAll(".wg-chip.on").forEach(c => c.classList.remove("on"));
        else if (box.querySelectorAll(".wg-chip.on").length >= multi)
          return toast(`Up to ${multi} picks — untick one first`);
        ch.classList.add("on");
      }
      if (otherText) otherText.hidden = !box.querySelector(".wg-other.on");
    });
  });
}

function wgQuestionById(id) {
  return [...wgBank.short, ...wgBank.medium].find(q => q.id === id);
}

/** The answers of the form's questions: {question id: {choices: [labels], other}}. */
function wgAnswers(dlg) {
  const answers = {};
  dlg.querySelectorAll(".wg-q[data-q]").forEach(box => {
    const q = wgQuestionById(box.dataset.q);
    if (!q) return;
    if (q.free) {
      const t = box.querySelector(".wg-other-text").value.trim();
      if (t) answers[q.id] = {choices: [], other: t};
      return;
    }
    const chips = box.querySelector(".wg-chips");
    const choices = [...chips.querySelectorAll(".wg-chip.on:not(.wg-other)")]
      .map(c => q.options[+c.dataset.i]).filter(o => o);
    const other = chips.querySelector(".wg-other-text").value.trim();
    if (choices.length || other) answers[q.id] = {choices, other};
  });
  return answers;
}

function wgPopulation(dlg) {
  const clamp = v => Math.min(wgBank.population.max, Math.max(wgBank.population.min, v));
  const lo = clamp(parseInt($("wgPopLo").value, 10) || wgBank.population.default[0]);
  const hi = clamp(parseInt($("wgPopHi").value, 10) || wgBank.population.default[1]);
  return [lo, Math.max(lo, hi)];
}

// ---------------------------------------------------------------- Frame it
function wgResetFrame() {
  wgFrame = null; wgFramedMode = null; wgClarifyQuestions = null; wgClarify = [];
  if ($("wgFrameBox")) {
    $("wgFrameBox").hidden = true;
    $("wgClarifyBox").hidden = true;
    $("wgFrameBtn").textContent = "Frame it";
    $("wgFrameStatus").textContent =
      "P0 turns your answers into the World Frame every later phase follows. Frame it, read it, then generate.";
  }
}

async function wgFrameIt(dlg) {
  if (wgFrameBusy) return;
  const mode = wgModeOf(dlg);
  const idea = $("wgIdea").value.trim();
  if (mode === "quick" && !idea) return toast("Type the idea first");
  wgFrameBusy = true;
  const btn = $("wgFrameBtn");
  btn.disabled = true; btn.textContent = "Framing…";
  try {
    const body = {mode, idea, answers: wgAnswers(dlg), population: wgPopulation(dlg),
                  provider: $("wgProvider").value};
    if (wgClarify.length) body.clarify = wgClarify;
    const r = await api("/api/worldgen/frame", {method: "POST", body: JSON.stringify(body)});
    const j = await wgPollFrame(r.job, dlg);
    if (j && j.state === "failed") { $("wgFrameStatus").textContent = j.error || "framing failed"; return; }
    if (!j) { $("wgFrameStatus").textContent = "framing stopped"; return; }
    if ((j.questions || []).length) {
      wgClarifyQuestions = j.questions; wgClarify = [];
      const box = $("wgClarifyBox");
      box.hidden = false;
      box.innerHTML = `<div class="wg-q-prompt">The model asks — answer what you care about, then Frame it again</div>`
        + j.questions.map((q, i) => `
          <div class="wg-q" data-cq="${i}">
            <div class="wg-q-prompt">${esc(q.question)}</div>
            <div class="wg-chips" data-multi="1">
              ${q.options.map((o, k) => `<button type="button" class="wg-chip" data-i="${k}">${esc(o)}</button>`).join("")}
              <button type="button" class="wg-chip wg-other" data-i="other">Other</button>
              <input type="text" class="wg-other-text" hidden placeholder="your own answer">
            </div>
          </div>`).join("");
      wgBindChips(box);
      $("wgFrameStatus").textContent = `The model has ${j.questions.length} question${j.questions.length === 1 ? "" : "s"} of its own.`;
    } else if (j.frame) {
      wgFrame = j.frame; wgFramedMode = mode; wgClarifyQuestions = null; wgClarify = [];
      $("wgClarifyBox").hidden = true;
      $("wgFrameBox").hidden = false;
      $("wgFrameView").innerHTML = `<summary>The whole frame</summary>${wgFrameDetails(j.frame)}`;
      $("wgSummary").value = j.frame.summary || "";
      $("wgFrameStatus").textContent = "This frame shapes every later phase. Edit the summary if you like, then Generate world.";
      btn.textContent = "Frame it again";
    } else {
      $("wgFrameStatus").textContent = "the model returned no frame — try again";
    }
  } catch (e) {
    $("wgFrameStatus").textContent = e.message;
  } finally {
    wgFrameBusy = false;
    btn.disabled = false;
    if (btn.textContent === "Framing…") btn.textContent = "Frame it";
  }
}

/** Quietly polls the frame job while the dialog stays open (no second dialog):
 * resolves with the finished job, or null when it was cancelled or replaced. */
function wgPollFrame(first, dlg) {
  return new Promise(resolve => {
    let result = null;
    const tick = setInterval(async () => {
      if (!dlg.open) {                       // the form was closed: stop the job
        api("/api/worldgen/cancel", {method: "POST"}).catch(() => {});
        clearInterval(tick); return resolve(null);
      }
      let j = null;
      try { j = (await api("/api/worldgen/job")).job; } catch { return; }
      if (!j || j.id !== first.id) { clearInterval(tick); return resolve(null); }
      if (j.state !== "running") { result = j; clearInterval(tick); resolve(j); return; }
      $("wgFrameStatus").textContent = `Framing… ${j.label || ""}`.trim();
    }, 1200);
  });
}

function wgFrameDetails(f) {
  const g = f.genre || {};
  const rows = [
    ["Genre", [g.primary, ...(g.influences || [])].filter(Boolean).join("; ")],
    ["Premise", f.premise], ["Reality", f.reality],
    ["Setting", f.setting && [f.setting.era, f.setting.technology, f.setting.climate].filter(Boolean).join(", ")],
    ["Tone", f.tone], ["Conflict", f.conflict], ["You play", f.playerRole],
    [(f.themes || []).length === 1 ? "Theme" : "Themes", (f.themes || []).join("; ")],
    [(f.constraints || []).length === 1 ? "Constraint" : "Constraints", (f.constraints || []).join("; ")],
    ["The framer left open", (f.unresolved || []).join("; ")],
  ];
  return `<dl class="facts">${rows.filter(([, v]) => v).map(([k, v]) =>
    `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>`;
}

/** The clarifying answers of the long form: the picked option or the Other
 * text of each model question, skipped ones left out. */
function wgClarifyAnswers(dlg) {
  const out = [];
  dlg.querySelectorAll("[data-cq]").forEach(box => {
    const q = (wgClarifyQuestions || [])[+box.dataset.cq];
    if (!q) return;
    const chips = box.querySelector(".wg-chips");
    const picked = chips.querySelector(".wg-chip.on:not(.wg-other)");
    const other = chips.querySelector(".wg-other-text").value.trim();
    const answer = picked ? q.options[+picked.dataset.i] : other;
    if (answer) out.push({question: q.question, answer});
  });
  return out;
}

function wgBindForm(dlg) {
  wgRenderQuestions(dlg, "quick");
  dlg.querySelectorAll(".wg-mode").forEach(b => b.onclick = () => {
    dlg.querySelectorAll(".wg-mode").forEach(x => x.classList.remove("on"));
    b.classList.add("on");
    const mode = b.dataset.mode;
    wgRenderQuestions(dlg, mode);
    if (wgFramedMode && wgFramedMode !== mode) {
      wgResetFrame();
      toast("The frame was made for another form — Frame it again");
    }
  });
  $("wgFrameBtn").onclick = () => {
    if (wgClarifyQuestions) wgClarify = wgClarifyAnswers(dlg);
    wgFrameIt(dlg);
  };
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
