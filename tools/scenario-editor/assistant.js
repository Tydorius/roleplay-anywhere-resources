"use strict";
// The Assistant pane: chat with your own model about the open scenario, and watch it edit. Every
// tool action runs in this page through edit(), one undo step per action, so the map, inspector
// and Problems panel update exactly as hand edits do; destructive actions ask first. The tool set
// lives in assistant_tools.js; the conversation happens server-side (assistant_editor.py): a send
// posts the transcript with a freshly built summary of the scenario, polls the job, runs the
// reply's actions and, when anything ran, feeds their results back for one more turn — at most
// AS_MAX_ROUNDS turns per request. The transcript lives in memory only. The rebuild tools are
// the exception to "runs in this page": they go to the server as a job, which the pane polls and
// whose staged result it offers to apply or discard.

const A = {
  open: false, provider: "",
  messages: [],              // the transcript sent to the model: [{role, content}]
  rounds: 0, running: false, stopped: false,
  calls: 0, tokens: 0, lastSeconds: 0,
  meta: null,                // /api/assistant/meta: {providers, ...}
};

const AS_MAX_ROUNDS = 8;       // model turns per request, its own acting turns included
const AS_POLL_MS = 1200;
const AS_TOOL_LINE = 400;      // the server refuses a longer tool line
const AS_RESULTS_CHARS = 6000; // stay well under the server's per-message limit
const AS_INPUT_CHARS = 6000;   // and an over-long ask is refused before it joins the transcript
const AS_REBUILD_POLL_MS = 1500;  // the rebuild job's poll; the chat turn keeps its own
const AS_PREVIEW_LINES = 20;      // diff lines the rebuild dialog lists before a "+N more"

/** The tool list for the prompt, each line cut to the server's limit. The cut lands in the
 *  description's tail, never in the arguments, which come first in the line. */
const asPromptLines = () => AssistantTools.promptLines().map(l => l.slice(0, AS_TOOL_LINE));

// ---------------------------------------------------------------- the pane
function asTogglePane(force) {
  A.open = force !== undefined ? !!force : !A.open;
  $("assistantPane").hidden = !A.open;
  $("mapView").classList.toggle("with-as", A.open);
  $("asToggle").classList.toggle("on", A.open);
  if (A.open) {
    asLoadMeta().catch(() => {});   // a provider may have been set up since the last look
    $("asInput").focus();
  }
}

/** Fills the provider picker (ready providers only), keeps the remembered choice, shows the model
 *  name, and the hint into the New world… dialog when nothing is configured. */
async function asLoadMeta() {
  A.meta = await api("/api/assistant/meta");
  const ready = (A.meta.providers || []).filter(p => p.ready);
  $("asProvider").innerHTML = ready.length
    ? ready.map(p => `<option value="${esc(p.name)}">${esc(p.name)}${p.model ? " · " + esc(p.model) : ""}</option>`).join("")
    : `<option value="">no provider</option>`;
  const want = recall("editor.assistant.provider");
  if (want && ready.some(p => p.name === want)) $("asProvider").value = want;
  asPickProvider();
  $("asHint").hidden = !!ready.length;
}

/** Takes the picker's choice: remembers it and labels the model. */
function asPickProvider() {
  A.provider = $("asProvider").value || "";
  if (A.provider) remember("editor.assistant.provider", A.provider);
  $("asModel").textContent = ((A.meta?.providers || []).find(p => p.name === A.provider) || {}).model || "";
}

// ---------------------------------------------------------------- transcript
function asScroll() { const log = $("asLog"); log.scrollTop = log.scrollHeight; }

/** One transcript card: `cls` one of user / assistant / action / err. */
function asCard(cls, who, text) {
  const d = document.createElement("div");
  d.className = "as-card " + cls;
  d.innerHTML = (who ? `<span class="who">${esc(who)}</span>` : "") + esc(text ?? "");
  $("asLog").append(d);
  asScroll();
  return d;
}

function asMeter() {
  $("asMeter").textContent = A.calls
    ? (A.stopped ? "stopped · " : "") + `${A.calls} model call${A.calls === 1 ? "" : "s"} · `
      + `${A.tokens.toLocaleString("en-US")} tokens · last reply ${A.lastSeconds}s`
    : (A.stopped ? "stopped" : "");
}

/** Empties the conversation and the session meter (Clear, and a source switch). */
function asClear() {
  A.messages = []; A.rounds = 0; A.stopped = false;
  A.calls = 0; A.tokens = 0; A.lastSeconds = 0;
  $("asLog").innerHTML = `<p class="hint">Ask in your own words — the assistant answers, and its edits land here as undoable steps.</p>`;
  asMeter();
}

/** The composer while a turn runs: input and Send off, Stop in their place. */
function asBusy(on) {
  A.running = on;
  $("asSend").disabled = on;
  $("asInput").disabled = on;
  $("asStop").hidden = !on;
}

// ---------------------------------------------------------------- a request and its turns
async function asUserSend() {
  if (A.running) return toast("The assistant is already working — Stop it first");
  if (!S.scn || !S.editable) return toast("Read only: copy the scenario to a workspace first, then ask the assistant");
  if (!A.provider) return toast("No model provider — pick one at the top of the pane");
  const text = $("asInput").value.trim();
  if (!text) return;
  if (text.length > AS_INPUT_CHARS)
    return toast(`That message is ${text.length.toLocaleString("en-US")} characters — keep it under ${AS_INPUT_CHARS.toLocaleString("en-US")}`);
  $("asInput").value = "";
  A.messages.push({role: "user", content: text});
  asCard("user", "You", text);
  await asConversation();
}

/** Turns until the model stops acting: each turn's actions run here first, then their results go
 *  back for one more turn — unless nothing ran, a turn failed, the user pressed Stop, or
 *  AS_MAX_ROUNDS turns have passed. */
async function asConversation() {
  A.rounds = 0; A.stopped = false;
  asBusy(true);
  try {
    while (A.rounds < AS_MAX_ROUNDS) {
      A.rounds++;
      const j = await asTurn();
      if (!j) break;                              // it never started, was stopped, or the slot was taken
      if (j.state !== "done") {
        if (!A.stopped) asCard("err", null, j.error || ("the turn was " + j.state));
        break;                                    // Stop: the last reply stays up; the meter says the rest
      }
      A.calls += j.calls || 0; A.tokens += j.tokens || 0; A.lastSeconds = j.seconds || 0;
      A.messages.push({role: "assistant", content: asAssistantContent(j)});
      asCard("assistant", "Assistant", j.reply || "(no reply text)");
      asMeter();
      const results = [];
      for (const a of j.actions || []) {
        if (A.stopped) break;
        results.push(await asRunAction(a));
      }
      if (A.stopped || !results.length) break;    // a plain answer: the conversation is done
      // the outcomes go into the transcript even at the round cap, so the next
      // request's model knows what its last actions did
      const msg = asToolResultsMessage(results);
      A.messages.push({role: "user", content: msg});
      asCard("action", null, msg.length > 300 ? msg.slice(0, 300) + "…" : msg);
      if (A.rounds >= AS_MAX_ROUNDS) { asCard("action", null, "stopped after " + AS_MAX_ROUNDS + " rounds"); break; }
    }
  } finally {
    asBusy(false);
    asMeter();
  }
}

/** One model turn: posts the transcript with a freshly built summary of the scenario (the model
 *  must see it as it is now), then polls the job. Resolves with the finished job, or null when
 *  it never started, was stopped, or another page took the slot. */
async function asTurn() {
  let first;
  try {
    first = (await api("/api/assistant/turn", {method: "POST", body: JSON.stringify({
      source: S.source,
      provider: A.provider,
      messages: asWindow(),
      tools: asPromptLines(),
      scenarioSummary: JSON.stringify(AssistantTools.summary(S.scn)),
    })})).job;
  } catch (e) { asCard("err", null, e.message); return null; }
  return asPoll(first);
}

/** The messages to send: the newest that fit the server's limits, starting on a user message.
 *  The scenario summary is rebuilt every turn, so the old turns the window drops carry nothing
 *  the model still needs. */
function asWindow() {
  const maxN = A.meta?.maxMessages || 60, maxChars = 60000;   // margin under the server's 80,000
  const out = [];
  let chars = 0;
  for (let i = A.messages.length - 1; i >= 0; i--) {
    const m = A.messages[i], len = (m.content || "").length;
    if (out.length >= maxN || chars + len > maxChars) break;
    out.unshift(m);
    chars += len;
  }
  while (out.length > 1 && out[0].role !== "user") out.shift();
  return out;
}

/** What the model said, the way it said it: the JSON it replied with, kept under the server's
 *  per-message limit. Its own turns in the transcript must follow the protocol too, or later
 *  replies start imitating the prose. */
function asAssistantContent(j) {
  let s;
  try { s = JSON.stringify({reply: j.reply || "", actions: j.actions || []}); } catch { s = ""; }
  if (s.length > 7800) {
    try { s = JSON.stringify({reply: (j.reply || "").slice(0, 3000),
      actions: (j.actions || []).map(a => ({tool: a.tool, args: {}}))}); } catch { s = '{"reply":"","actions":[]}'; }
  }
  return s;
}

/** Polls the job with a thinking card up; resolves with the finished job, or null when it
 *  disappeared from the slot (another page's turn replaced it). */
async function asPoll(first) {
  const think = asCard("assistant", "Assistant", "thinking…");
  try {
    for (;;) {
      let j = null;
      try { j = (await api("/api/assistant/job")).job; } catch {}
      if (!j || j.id !== first.id) return null;
      if (j.state !== "running") return j;
      await new Promise(r => setTimeout(r, AS_POLL_MS));
    }
  } finally { think.remove(); }
}

// ---------------------------------------------------------------- actions
/** Runs one of the model's actions against the open scenario — one undo step — and cards the
 *  outcome. Destructive tools ask first. Returns the result the follow-up turn reports. */
async function asRunAction(a) {
  const name = a && typeof a === "object" && !Array.isArray(a) && typeof a.tool === "string" && a.tool
    ? a.tool : "(no tool)";
  const args = a && typeof a === "object" && !Array.isArray(a) && a.args && typeof a.args === "object"
    && !Array.isArray(a.args) ? a.args : null;
  const tool = AssistantTools.TOOLS[name];
  if (!tool || !args) return asActionDone(name, tool ? "args must be an object" : "unknown tool", false);
  if (!S.editable || !S.scn) return asActionDone(name, "read only: copy the scenario to a workspace first", false);
  if (tool.server) return asRunRebuild(name, tool, args);
  if (tool.destructive) {
    const text = AssistantTools.preview(S.scn, {tool: name, args})
      || `Run ${name} with ${JSON.stringify(args)}.`;
    const choice = await openDialog("The assistant asks to make a destructive change",
      `<p class="note">${esc(text)}</p>`,
      [{label: "Skip", value: null}, {label: "Apply", value: "go", primary: true}]);
    if (choice !== "go") return asActionDone(name, "skipped", false);
  }
  let res = null, thrown = null;
  edit("AI: " + name, () => {
    try { res = tool.run(S.scn, args, set); }
    catch (e) { thrown = e.message; throw e; }     // edit() rolls the partial change back
    if (!res || !res.ok) {                         // a reported failure must change nothing
      thrown = (res && res.error) || "the tool failed"; res = null;
      throw new Error(thrown);
    }
  });
  if (thrown) return asActionDone(name, thrown, false);
  const first = Array.isArray(res.data?.createdIds) ? res.data.createdIds[0] : null;
  if (first && byId(first)) select({kind: "entity", id: first}, true);   // show what it made
  return asActionDone(name, res.summary || "done", true, res);
}

/** Cards one action's outcome and returns what the follow-up turn reports about it. */
function asActionDone(name, text, ok, res) {
  const d = document.createElement("div");
  d.className = "as-card action" + (ok ? "" : " err");
  d.innerHTML = `<span class="who">${ok ? "action" : "action failed"}</span><b>${esc(name)}</b> ${esc(text)}`;
  $("asLog").append(d);
  asScroll();
  return ok && res ? {tool: name, ok: true, summary: res.summary || text, data: res.data}
                   : {tool: name, ok: false, error: text};
}

/** The follow-up user message reporting every action's outcome, compact enough for the server's
 *  per-message limit: the summaries alone when the full results (fetched data included) don't
 *  fit, then whole entries dropped rather than a cut mid-JSON. */
function asToolResultsMessage(results) {
  const slim = r => r.ok ? {tool: r.tool, ok: true, summary: r.summary} : r;
  let body = "";
  try { body = JSON.stringify(results); } catch {}
  if (body.length <= AS_RESULTS_CHARS) return "Tool results: " + body;
  try { body = JSON.stringify(results.map(slim)); } catch { body = ""; }
  if (body.length <= AS_RESULTS_CHARS) return "Tool results: " + body;
  const out = [];
  for (let i = 0; i < results.length; i++) {
    if (JSON.stringify([...out, slim(results[i])]).length > AS_RESULTS_CHARS) {
      out.push({tool: "(more)", ok: true, summary: (results.length - i) + " results not shown"});
      break;
    }
    out.push(slim(results[i]));
  }
  return "Tool results: " + JSON.stringify(out);
}

// ---------------------------------------------------------------- the server tools (rebuilds)
/** One server tool: the model call and the relayout happen on the server, in the rebuild's own
 *  job slot — this page only starts the job, polls it and shows the staged preview to apply or
 *  discard. A refused start (no plan, unknown name) or a failed job is the tool's error result;
 *  applying replaces the whole workspace, so the open source is reloaded after it. Returns the
 *  result the follow-up turn reports. */
async function asRunRebuild(name, tool, args) {
  let instruction = typeof args.instruction === "string" ? args.instruction : "";
  if (name === "populate_zone" && Number.isInteger(args.quota))
    instruction += " (quota: about " + args.quota + " people)";   // the wire carries instruction only
  let first = null;
  try {
    first = (await api("/api/assistant/rebuild", {method: "POST", body: JSON.stringify({
      source: S.source,
      provider: A.provider,
      kind: tool.kind,
      target: args[tool.targetArg],
      instruction,
      seed: args.seed,
    })})).job;
  } catch (e) { return asActionDone(name, e.message, false); }
  const card = asCard("action", null, "");
  const progress = t => { card.innerHTML = `<span class="who">action</span><b>${esc(name)}</b> ${esc(t)}`; };
  progress("rebuilding…");
  let done = null, stopped = false, lost = false;
  try {
    for (;;) {
      if (A.stopped) { stopped = true; break; }        // Stop ends the wait; the job runs on
      let j = null;
      try { j = (await api("/api/assistant/rebuild")).job; } catch {}
      if (!j || j.id !== first.id) { lost = true; break; }
      if (j.state !== "running") { done = j; break; }
      progress("rebuilding — " + (j.label || j.phase || ""));
      await new Promise(r => setTimeout(r, AS_REBUILD_POLL_MS));
    }
  } finally { card.remove(); }
  if (stopped) return asActionDone(name, "stopped waiting — the rebuild keeps running on the server, where its result stays staged", false);
  if (lost) return asActionDone(name, "the rebuild job left its slot before finishing", false);
  if (done.state !== "done") return asActionDone(name, done.error || ("the rebuild was " + done.state), false);
  return asRebuildDecide(name, done);
}

/** The finished rebuild: its staged preview as a dialog — Apply replaces the open scenario (and
 *  reloads it), Discard (or Esc) leaves everything as it is. */
async function asRebuildDecide(name, j) {
  const pv = j.preview || {};
  const lines = asPreviewLines(pv), shown = lines.slice(0, AS_PREVIEW_LINES);
  const more = lines.length - shown.length;
  const lead = (j.label || "The rebuild is staged")
    + (j.seed != null ? " — the world was re-placed with seed " + j.seed : "")
    + ". Applying replaces the whole open scenario with the rebuilt one; discarding keeps this one.";
  const choice = await openDialog("Apply rebuild", `
    <p class="note">${esc(lead)}</p>
    <div class="fd-preview"><ul>${shown.map(l => `<li>${esc(l)}</li>`).join("")}</ul></div>
    ${more > 0 ? `<p class="note">+${more} more change${more === 1 ? "" : "s"}…</p>` : ""}`,
    [{label: "Discard", value: null}, {label: "Apply", value: "apply", primary: true}]);
  if (choice !== "apply") {
    try { await api("/api/assistant/rebuild/discard", {method: "POST"}); }
    catch (e) { return asActionDone(name, "the discard failed: " + e.message, false); }
    return asActionDone(name, "discarded — the open scenario was never touched", true,
      {summary: "discarded: the rebuild was not applied, the scenario is unchanged", data: {discarded: true}});
  }
  let out = null;
  try { out = await api("/api/assistant/rebuild/apply", {method: "POST"}); }
  catch (e) { return asActionDone(name, "the apply failed: " + e.message, false); }
  try { await openSource(S.source); }                 // the workspace is the new build now
  catch (e) { asCard("err", null, "applied, but reloading the scenario failed: " + e.message); }
  const what = asPreviewSummary(pv);
  const summary = "applied" + (what ? ": " + what : "") + "; " + (out.carried || 0) + " image"
    + (out.carried === 1 ? "" : "s") + " carried over; the previous scenario is backed up at " + out.backup;
  return asActionDone(name, summary, true,
    {summary, data: {applied: true, carried: out.carried, backup: out.backup, preview: pv}});
}

/** The staged preview as one line per change: names added and removed (a rename shows as both),
 *  dressing props re-counted, and the headline counts and reachability. */
function asPreviewLines(pv) {
  const out = [];
  const delta = (what, d) => {
    for (const n of (d && d.added) || []) out.push("+ " + what + " \"" + n + "\"");
    for (const n of (d && d.removed) || []) out.push("- " + what + " \"" + n + "\"");
  };
  delta("region", pv.regions);
  delta("person", pv.npcNames);
  delta("object template", pv.objectTemplateNames);
  for (const [t, pair] of Object.entries(pv.dressingProps || {}))
    out.push("~ dressing prop \"" + t + "\": " + pair[0] + " → " + pair[1]);
  for (const [k, v] of Object.entries(pv.counts || {}))
    if (Array.isArray(v)) out.push(k + ": " + v[0] + " → " + v[1]);
  if (pv.metrics && pv.metrics.reachability !== undefined)
    out.push("reachability: " + Math.round(pv.metrics.reachability * 100) + "%"
      + (pv.metrics.dropped ? ", " + pv.metrics.dropped + " object(s) dropped" : ""));
  return out;
}

/** The same preview as one clause, for the result card the follow-up turn reads. */
function asPreviewSummary(pv) {
  const bits = [];
  if (pv.regions) bits.push(pv.regions.added.length + " region" + (pv.regions.added.length === 1 ? "" : "s")
    + " added, " + pv.regions.removed.length + " removed");
  for (const [k, v] of Object.entries(pv.counts || {}))
    if (Array.isArray(v)) bits.push(k + " " + v[0] + " → " + v[1]);
  if (pv.metrics && pv.metrics.reachability !== undefined)
    bits.push("reachability " + Math.round(pv.metrics.reachability * 100) + "%");
  return bits.join(", ");
}

// ---------------------------------------------------------------- reattach, source switches
/** After a refresh: a turn still running is picked up — the pane opens, the composer waits, and
 *  the reply and its actions land when it ends (the transcript itself is gone with the old page,
 *  so there is nothing to continue from). */
async function asReattach() {
  let j = null;
  try { j = (await api("/api/assistant/job")).job; } catch { return; }
  if (!j || j.state !== "running") return;
  asTogglePane(true);
  asCard("action", null, "picked up the turn that was already running");
  asBusy(true);
  const done = await asPoll(j);
  asBusy(false);
  if (!done) return;
  if (done.state !== "done") { asCard("err", null, done.error || ("the turn was " + done.state)); return; }
  A.calls += done.calls || 0; A.tokens += done.tokens || 0; A.lastSeconds = done.seconds || 0;
  asCard("assistant", "Assistant", done.reply || "(no reply text)");
  if (done.source && S.source && done.source !== S.source) {
    asCard("err", null, "the actions were not run: this turn belongs to " + done.source);
    asMeter();
    return;
  }
  for (const a of done.actions || []) await asRunAction(a);
  asMeter();
}

// The transcript belongs to the scenario it started on: switching sources starts it over — and
// never happens mid-turn, which would aim the model's remaining actions at another scenario.
// Reloading the same source mid-turn is fine: that is what applying a rebuild does.
const asOpenSource = openSource;
openSource = async id => {
  if (A.running && id !== S.source) { toast("The assistant is working — stop it before switching scenarios"); $("source").value = S.source; return; }
  const before = S.source;
  await asOpenSource(id);
  if (S.source !== before) { asClear(); asCheckPlan(); }
};

/** Whether the open source can be rebuilt at all: the server tools need a saved plan, and only a
 *  world the generator made carries one, so a note beside the composer says so when it is
 *  missing. Checked once per source switch, like the re-roll button. */
let asPlanCheck = 0;
async function asCheckPlan() {
  const mine = ++asPlanCheck;
  let missing = false;
  if (S.source.startsWith("work/")) {
    try { missing = !(await api("/api/worldgen/plan?source=" + encodeURIComponent(S.source))).has; }
    catch { missing = false; }
  }
  if (mine === asPlanCheck) $("asPlanNote").hidden = !missing;
}

// ---------------------------------------------------------------- wiring
$("asToggle").onclick = () => asTogglePane();
$("asClose").onclick = () => asTogglePane(false);
$("asClear").onclick = () => { if (A.running) toast("Stop the turn first"); else asClear(); };
$("asProvider").onchange = asPickProvider;
$("asSend").onclick = () => asUserSend();
$("asInput").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); asUserSend(); } };
$("asStop").onclick = () => {
  if (!A.running) return;
  A.stopped = true;
  api("/api/assistant/cancel", {method: "POST"}).catch(() => {});   // already ended: the poll resolves anyway
  asMeter();
};
$("asHintOpen").onclick = () => newWorldDialog().catch(e => toast(e.message));
asClear();
asLoadMeta().catch(() => {});
asReattach();
