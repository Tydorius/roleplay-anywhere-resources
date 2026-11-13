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
// The whole dialog is saved as a draft on the server (out/drafts/), so a refresh or a
// closed dialog loses nothing: "Saved drafts" at the top brings one back.

const WG_PHASES = {P0: "The world frame", P1: "World plan", P2: "Prop catalogue", P3: "Buildings", P4: "Zones",
                   P5: "People", P6: "Rules, perks, story", layout: "Placing everything", build: "Building the scenario"};
const WG_MODE_LABEL = {quick: "Quick — one idea", short: "Short — 7 questions",
                       medium: "Medium — 14 questions", long: "Long — 14 + the model asks more"};

let wgMeta = null;      // {providers, hasProvidersFile, providersPath, extensions}, from /api/worldgen/meta
let wgBank = null;      // {modes, short, medium, population}, from /api/worldgen/questions
let wgFrame = null;     // the approved frame of the open dialog (its summary may have been edited)
let wgFramedMode = null;
let wgClarifyQuestions = null;   // the long form's clarifying questions, while unanswered
let wgClarify = null;            // [{question, answer}] once answered ([] = all skipped)
let wgFrameBusy = false;
let wgEstimateTimer = 0;
let wgDraftId = null;            // the open dialog's draft (out/drafts/<id>.json)
let wgDraftTimer = 0;
let wgDialog = null;             // the open dialog element, for the draft saver

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
  wgFrame = null; wgFramedMode = null; wgClarifyQuestions = null; wgClarify = null;
  wgDraftId = null;
  let drafts = [];
  try { drafts = (await api("/api/worldgen/drafts")).drafts; } catch {}
  const form = wgFormDialog("New world from an idea…", wgFormHtml(drafts), dlg => {
    const idea = $("wgIdea").value.trim();
    const mode = wgModeOf(dlg);
    if (mode === "quick" && !idea) { toast("Type the idea first"); return null; }
    if (!wgFrame) { wgNeedFrame(); return null; }
    if ($("wgSummary").value.trim()) wgFrame.summary = $("wgSummary").value.trim();
    wgSaveDraftNow();
    return {
      idea,
      provider: $("wgProvider").value,
      seed: wgSeedOf($("wgSeed")),
      extensions: [...dlg.querySelectorAll("[data-ext]:checked")].map(cb => cb.dataset.ext),
      library: $("wgLibrary").checked,
      item_library: $("wgItemLibrary").checked,
      frame: wgFrame,
      questionnaire: {mode, answers: wgAnswers(dlg), population: wgPopulation(dlg),
                      notes: $("wgNotes").value.trim()},
      draft: wgDraftId,
    };
  }, dlg => wgBindForm(dlg));
  const value = await form.promise;   // openDialog resolves to the clicked value itself
  wgDialog = null;
  if (value !== "go") return;
  try {
    const r = await api("/api/worldgen/generate", {method: "POST", body: JSON.stringify(form.picked())});
    await wgTrackJob(r.job, "Generating the world…");
  } catch (e) { toast(e.message); }
}

/** Generate pressed with no frame yet: say why, in the dialog, where Frame it is. */
function wgNeedFrame() {
  const msg = wgClarifyQuestions
    ? "Answer the model's questions (or skip them), then press Frame it again under them."
    : "Frame the world first: press Frame it and read the frame.";
  $("wgFrameStatus").textContent = msg;
  $("wgFrameStatus").classList.add("warn");
  (wgClarifyQuestions ? $("wgFrameBtn2") : $("wgFrameBtn"))?.scrollIntoView({block: "center", behavior: "smooth"});
  toast(msg);
}

/** Generate looks off until a frame exists, but stays clickable so a press says why. */
function wgUpdateGo() {
  const go = wgDialog?.querySelector(".dlg-buttons .primary");
  if (!go) return;
  go.classList.toggle("wg-wait", !wgFrame);
  go.title = wgFrame ? "" : (wgClarifyQuestions ? "Answer the model's questions and Frame it again first"
                                                : "Frame the world first");
}

function wgFormHtml(drafts) {
  const pop = wgBank.population;
  const state = d => d.generated ? "generated" : d.running ? "generating" : d.framed ? "framed"
    : d.questions ? "model asked questions" : "not framed";
  return `
    ${drafts.length ? `<div class="wg-drafts">
      <select id="wgDraftPick">${drafts.map(d => `<option value="${esc(d.id)}">${esc(d.saved)} · ${esc(d.title.slice(0, 60))} (${esc(d.mode)}, ${esc(state(d))})</option>`).join("")}</select>
      <button type="button" id="wgDraftLoad">Resume draft</button>
      <button type="button" id="wgDraftDel" title="Delete the chosen draft">Delete</button>
    </div>` : ""}
    <div class="wg-settings-file">
      <button type="button" id="wgExport" title="Download this form, and its frame once framed, as a small JSON file">Export settings…</button>
      <button type="button" id="wgImport" title="Fill this form from a settings file someone sent you">Import settings…</button>
      <input type="file" id="wgImportFile" accept=".json,application/json" hidden>
      <span class="note">A small file of these choices to send someone (no API key in it). The generator also saves one as settings.json in every run's folder.</span>
    </div>
    <div class="wg-modes">${wgBank.modes.map(m =>
      `<button type="button" class="wg-mode${m === "quick" ? " on" : ""}" data-mode="${esc(m)}">${esc(WG_MODE_LABEL[m] || m)}</button>`).join("")}</div>
    ${field("The idea, in one line",
            `<textarea id="wgIdea" rows="2" placeholder="a fogbound harbour town of smugglers"></textarea>`,
            "Everything for the quick form; a steer beside the questionnaires.")}
    <div id="wgQuestions"></div>
    ${field("Other instructions or requests",
            `<textarea id="wgNotes" rows="4" placeholder="anything the boxes above don't cover: a plot outline, places or people you want, house rules…"></textarea>`,
            "Optional. Sent word for word to the frame, the world plan, the people and the story phases.")}
    ${field("Residents",
            `<label class="check"><input type="checkbox" id="wgPopMap" checked> Let the map decide</label>
             <div class="wg-pop"><input type="number" id="wgPopLo" value="${pop.default[0]}" min="${pop.min}" max="${pop.max}" step="1" disabled> <span class="note">to</span> <input type="number" id="wgPopHi" value="${pop.default[1]}" min="${pop.min}" max="${pop.max}" step="1" disabled></div>`,
            `A hamlet is about 10–20 people, a village 20–45, one city block 30–60. Busy maps are fine: people are spread out so no room gets crowded. Untick to set your own number (${pop.min}–${pop.max}).`)}
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
    ${field("Room library",
            `<label class="check"><input type="checkbox" id="wgLibrary" checked> Use room library</label>`,
            "Rooms are furnished from the generator's room library: fewer tokens, and beds, tables and chairs set out properly. Untick for the old method, where the model furnishes every room.")}
    ${field("Item library",
            `<label class="check"><input type="checkbox" id="wgItemLibrary" checked> Use item library</label>`,
            "Containers are stocked from the generator's item library of reviewed item art: the model fills loot pools from a menu, recolours variants for local flavour, and only plot items get a picture of their own. Untick and the model invents every item.")}
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
  if ($("wgPopMap").checked) return "map";
  const clamp = v => Math.min(wgBank.population.max, Math.max(wgBank.population.min, v));
  const lo = clamp(parseInt($("wgPopLo").value, 10) || wgBank.population.default[0]);
  const hi = clamp(parseInt($("wgPopHi").value, 10) || wgBank.population.default[1]);
  return [lo, Math.max(lo, hi)];
}

/** The checkbox and the two number boxes it switches off. */
function wgSetPopMap(on) {
  $("wgPopMap").checked = on;
  $("wgPopLo").disabled = $("wgPopHi").disabled = on;
}

// ---------------------------------------------------------------- Frame it
function wgSetStatus(text, warn = false) {
  $("wgFrameStatus").textContent = text;
  $("wgFrameStatus").classList.toggle("warn", warn);
}

function wgResetFrame() {
  const had = wgFrame || wgClarifyQuestions;
  wgFrame = null; wgFramedMode = null; wgClarifyQuestions = null; wgClarify = null;
  if ($("wgFrameBox")) {
    $("wgFrameBox").hidden = true;
    $("wgClarifyBox").hidden = true;
    $("wgFrameBtn").textContent = "Frame it";
    wgSetStatus("P0 turns your answers into the World Frame every later phase follows. Frame it, read it, then generate.");
  }
  wgUpdateGo();
  if (had && wgDraftId) api("/api/worldgen/draft?id=" + wgDraftId,
    {method: "POST", body: JSON.stringify({clearFrame: true})}).catch(() => {});
}

/** The long form's clarifying questions, with their own Frame it button underneath. */
function wgShowClarify(questions, answers) {
  wgClarifyQuestions = questions;
  const box = $("wgClarifyBox");
  box.hidden = false;
  $("wgFrameBox").hidden = true;
  box.innerHTML = `<div class="wg-q-prompt">The model asks — answer what you care about (or skip them all), then Frame it again below</div>`
    + questions.map((q, i) => `
      <div class="wg-q" data-cq="${i}">
        <div class="wg-q-prompt">${esc(q.question)}</div>
        <div class="wg-chips" data-multi="1">
          ${q.options.map((o, k) => `<button type="button" class="wg-chip" data-i="${k}">${esc(o)}</button>`).join("")}
          <button type="button" class="wg-chip wg-other" data-i="other">Other</button>
          <input type="text" class="wg-other-text" hidden placeholder="your own answer">
        </div>
      </div>`).join("")
    + `<div class="wg-framebar"><button type="button" id="wgFrameBtn2" class="primary">Frame it again</button>
         <span class="note">with these answers — then Generate world comes alive</span></div>`;
  wgBindChips(box);
  for (const a of answers || []) {            // a resumed draft's answers
    const i = questions.findIndex(q => q.question === a.question);
    const chips = box.querySelector(`[data-cq="${i}"] .wg-chips`);
    if (chips) wgSetChoice(chips, questions[i].options, [a.answer]);
  }
  $("wgFrameBtn2").onclick = () => $("wgFrameBtn").onclick();
  $("wgFrameBtn").textContent = "Frame it again";
  wgSetStatus(`The model has ${questions.length} question${questions.length === 1 ? "" : "s"} of its own — answer them below, then press Frame it again under them.`, true);
  wgUpdateGo();
}

function wgShowFrame(frame, summary) {
  wgFrame = frame; wgClarifyQuestions = null;
  $("wgClarifyBox").hidden = true;
  $("wgFrameBox").hidden = false;
  $("wgFrameView").innerHTML = `<summary>The whole frame</summary>${wgFrameDetails(frame)}`;
  $("wgSummary").value = summary || frame.summary || "";
  wgSetStatus("This frame shapes every later phase. Edit the summary if you like, then Generate world.");
  $("wgFrameBtn").textContent = "Frame it again";
  wgUpdateGo();
}

/** Tick the chips whose labels are in `values`; anything else goes in Other. */
function wgSetChoice(chips, options, values, other = "") {
  const extra = [];
  for (const v of values || []) {
    const i = options.indexOf(v);
    if (i >= 0) chips.querySelector(`.wg-chip[data-i="${i}"]`)?.classList.add("on");
    else if (v) extra.push(v);
  }
  const text = [other, ...extra].filter(Boolean).join("; ");
  if (text) {
    chips.querySelector(".wg-other").classList.add("on");
    const t = chips.querySelector(".wg-other-text");
    t.hidden = false; t.value = text;
  }
}

async function wgFrameIt(dlg) {
  if (wgFrameBusy) return;
  const mode = wgModeOf(dlg);
  const idea = $("wgIdea").value.trim();
  if (mode === "quick" && !idea) return toast("Type the idea first");
  wgFrameBusy = true;
  const btns = [$("wgFrameBtn"), $("wgFrameBtn2")].filter(Boolean);
  btns.forEach(b => { b.disabled = true; b.textContent = "Framing…"; });
  wgSaveDraftNow();
  try {
    const body = {mode, idea, answers: wgAnswers(dlg), population: wgPopulation(dlg),
                  notes: $("wgNotes").value.trim(), provider: $("wgProvider").value, draft: wgDraftId};
    if (wgClarify) body.clarify = wgClarify;   // [] when every question was skipped
    const r = await api("/api/worldgen/frame", {method: "POST", body: JSON.stringify(body)});
    wgSetStatus("Framing…");
    await wgFrameResult(await wgPollFrame(r.job, dlg), mode);
  } catch (e) {
    wgSetStatus(e.message, true);
  } finally {
    wgFrameBusy = false;
    btns.forEach(b => { if (b.isConnected) { b.disabled = false; if (b.textContent === "Framing…") b.textContent = "Frame it again"; } });
    if ($("wgFrameBtn").textContent === "Framing…") $("wgFrameBtn").textContent = "Frame it";
  }
}

async function wgFrameResult(j, mode) {
  if (j && j.state === "failed") return wgSetStatus(j.error || "framing failed", true);
  if (!j) return wgSetStatus("framing stopped", true);
  if ((j.questions || []).length) {
    wgClarify = null;
    wgShowClarify(j.questions);
  } else if (j.frame) {
    wgFramedMode = mode;
    wgShowFrame(j.frame);
  } else {
    wgSetStatus("the model returned no frame — try again", true);
  }
}

// ---------------------------------------------------------------- drafts
const wgNewDraftId = () => "d-" + new Date().toISOString().replace(/\D/g, "").slice(0, 14)
  + "-" + Math.random().toString(36).slice(2, 6);

/** The dialog as a draft: what the page owns (the server writes the frame and the run). */
function wgDraftState(dlg) {
  const s = {mode: wgModeOf(dlg), idea: $("wgIdea").value, answers: wgAnswers(dlg),
             notes: $("wgNotes").value, population: wgPopulation(dlg), provider: $("wgProvider").value,
             seed: wgSeedOf($("wgSeed")),
             extensions: [...dlg.querySelectorAll("[data-ext]:checked")].map(cb => cb.dataset.ext),
             library: $("wgLibrary").checked,
             item_library: $("wgItemLibrary").checked};
  if (wgFrame) s.summary = $("wgSummary").value;
  if (wgClarifyQuestions) s.clarifyAnswers = wgClarifyAnswers(dlg);
  return s;
}

function wgSaveDraftNow() {
  clearTimeout(wgDraftTimer);
  const dlg = wgDialog;
  if (!dlg || !dlg.open) return;
  const s = wgDraftState(dlg);
  // nothing typed or picked yet: no draft worth keeping
  if (!wgDraftId && !s.idea.trim() && !s.notes.trim() && !Object.keys(s.answers).length) return;
  wgDraftId ||= wgNewDraftId();
  api("/api/worldgen/draft?id=" + wgDraftId, {method: "POST", body: JSON.stringify(s)}).catch(() => {});
}

function wgSaveDraftSoon() {
  clearTimeout(wgDraftTimer);
  wgDraftTimer = setTimeout(wgSaveDraftNow, 800);
}

/** Fill the dialog from a saved draft; picks up its frame job if that is still running. */
async function wgResumeDraft(dlg, id) {
  const d = (await api("/api/worldgen/draft?id=" + encodeURIComponent(id))).draft;
  wgResetFrame();
  wgDraftId = d.id;
  const mode = d.mode || "quick";
  dlg.querySelectorAll(".wg-mode").forEach(x => x.classList.toggle("on", x.dataset.mode === mode));
  wgRenderQuestions(dlg, mode);
  $("wgIdea").value = d.idea || "";
  $("wgNotes").value = d.notes || "";
  wgSetPopMap(!Array.isArray(d.population));
  if (Array.isArray(d.population)) { $("wgPopLo").value = d.population[0]; $("wgPopHi").value = d.population[1]; }
  if (d.provider && [...$("wgProvider").options].some(o => o.value === d.provider)) $("wgProvider").value = d.provider;
  if (d.seed != null) $("wgSeed").value = d.seed;
  dlg.querySelectorAll("[data-ext]").forEach(cb => cb.checked = (d.extensions || []).includes(cb.dataset.ext));
  if (d.library != null) $("wgLibrary").checked = !!d.library;
  if (d.item_library != null) $("wgItemLibrary").checked = !!d.item_library;
  dlg.querySelectorAll(".wg-q[data-q]").forEach(box => {
    const q = wgQuestionById(box.dataset.q), a = (d.answers || {})[box.dataset.q];
    if (!q || !a) return;
    if (q.free) box.querySelector(".wg-other-text").value = a.other || "";
    else wgSetChoice(box.querySelector(".wg-chips"), q.options, a.choices, a.other);
  });
  if (d.frame) { wgFramedMode = d.framedMode || mode; wgShowFrame(d.frame, d.summary); }
  else if (d.questions) wgShowClarify(d.questions, d.clarifyAnswers);
  const run = d.run;
  if (run) wgSetStatus(run.source ? `Already generated from this draft (${run.started}); it opened as a workspace. Generate again for another world.`
                                  : `A generation from this draft started at ${run.started}.`);
  $("wgIdea").oninput();
  // its frame job may still be running (the page was refreshed mid-frame)
  const j = (await api("/api/worldgen/job")).job;
  if (j && j.kind === "frame" && j.draft === d.id && j.state === "running") {
    wgSetStatus("Framing… (picked up the running job)");
    await wgFrameResult(await wgPollFrame(j, dlg), mode);
  }
  toast("Draft resumed");
}

/** Quietly polls the frame job while the dialog stays open (no second dialog):
 * resolves with the finished job, or null when it was replaced or the dialog closed.
 * Closing the dialog leaves the job running: it writes its result into the draft. */
function wgPollFrame(first, dlg) {
  return new Promise(resolve => {
    let result = null;
    const tick = setInterval(async () => {
      if (!dlg.open) { clearInterval(tick); return resolve(null); }
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
    ["Your other instructions", f.notes],
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

/** Download the dialog's choices (and the frame, once framed) as a world settings file. */
async function wgExportSettings(dlg) {
  const form = wgDraftState(dlg);
  if (wgFrame) form.frame = wgFrame;
  const s = (await api("/api/worldgen/settings/export", {method: "POST", body: JSON.stringify(form)})).settings;
  const words = (s.idea || s.frame?.premise || s.mode).toLowerCase().replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "").slice(0, 40) || "world";
  const url = URL.createObjectURL(new Blob([JSON.stringify(s, null, 1) + "\n"], {type: "application/json"}));
  const a = Object.assign(document.createElement("a"), {href: url, download: `world-settings-${words}.json`});
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast(s.frame ? "Settings exported, with the frame" : "Settings exported");
}

/** Fill the dialog from a settings file: it becomes a new draft, resumed like any other. */
async function wgImportSettings(dlg, file) {
  let data;
  try { data = JSON.parse(await file.text()); }
  catch { throw new Error(`${file.name} isn't a JSON file`); }
  const d = (await api("/api/worldgen/settings/import", {method: "POST", body: JSON.stringify({settings: data})})).draft;
  await wgResumeDraft(dlg, d.id);
  const from = d.imported?.model ? ` (made with ${d.imported.model})` : "";
  toast(`Settings imported${from}${d.frame ? ", with its frame" : ""}`);
}

function wgBindForm(dlg) {
  wgDialog = dlg;
  wgRenderQuestions(dlg, "quick");
  wgUpdateGo();
  $("wgExport").onclick = () => wgExportSettings(dlg).catch(e => toast(e.message));
  $("wgImport").onclick = () => $("wgImportFile").click();
  $("wgImportFile").onchange = ev => {
    const file = ev.target.files[0];
    ev.target.value = "";
    if (file) wgImportSettings(dlg, file).catch(e => toast(e.message));
  };
  // every edit lands in the draft a moment later
  dlg.addEventListener("input", wgSaveDraftSoon);
  dlg.addEventListener("change", wgSaveDraftSoon);
  dlg.addEventListener("click", ev => { if (ev.target.closest(".wg-chip, .wg-mode")) wgSaveDraftSoon(); });
  if ($("wgDraftLoad")) {
    $("wgDraftLoad").onclick = () => wgResumeDraft(dlg, $("wgDraftPick").value).catch(e => toast(e.message));
    $("wgDraftDel").onclick = async () => {
      const id = $("wgDraftPick").value;
      if (!confirm("Delete this draft?")) return;
      try {
        await api("/api/worldgen/draft?id=" + encodeURIComponent(id), {method: "POST", body: JSON.stringify({delete: true})});
        if (id === wgDraftId) wgDraftId = null;
        $("wgDraftPick").querySelector(`option[value="${CSS.escape(id)}"]`)?.remove();
        if (!$("wgDraftPick").options.length) $("wgDraftPick").parentElement.remove();
        toast("Draft deleted");
      } catch (e) { toast(e.message); }
    };
  }
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
    if (wgClarifyQuestions) wgClarify = wgClarifyAnswers(dlg);   // [] skips them all
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
  $("wgPopMap").onchange = e => wgSetPopMap(e.target.checked);
  $("wgIdea").oninput = estimate;
  dlg.querySelectorAll("[data-ext]").forEach(cb => cb.onchange = () => {
    // an extension that requires another turns it on too (none does since
    // portals was retired; the rule stays for future extensions)
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

/** After a refresh: a generation or re-roll still running gets its progress dialog back. */
async function wgReattach() {
  let j = null;
  try { j = (await api("/api/worldgen/job")).job; } catch { return; }
  if (!j || j.state !== "running") return;
  if (j.kind === "generate") await wgTrackJob(j, "Generating the world…");
  else if (j.kind === "reroll") await wgTrackJob(j, "Re-rolling the layout…");
  else if (j.kind === "frame") toast("A world frame is being made — New world… → Resume draft picks it up");
}

$("newWorld").onclick = () => newWorldDialog().catch(e => toast(e.message));
$("reroll").onclick = () => rerollDialog().catch(e => toast(e.message));
updateRerollButton();
wgReattach();
