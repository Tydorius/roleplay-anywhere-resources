// Anywhere RPG code-mod loader. Runs before the game bundle, which hands it the
// api-call registry (`api`) and routes every config/prompt file read through `cfg`.
(() => {
  const pendingCalls = [];
  const cfgHooks = [];
  const worldHooks = [];
  const promptHooks = [];
  let api = null;

  // A broken mod must never take the game down with it.
  function runHooks(kind, hooks, args) {
    for (const hook of hooks) {
      try {
        hook(...args);
      } catch (e) {
        console.error(`[arpg] ${kind} hook failed`, e);
      }
    }
  }

  function addCall(name, build) {
    if (!api) return void pendingCalls.push([name, build]);
    try {
      api[name] = build(api);
      arpg.calls.push(name);
    } catch (e) {
      console.error(`[arpg] api call ${name} failed to register`, e);
    }
  }

  const arpg = {
    version: 1,
    mods: [],
    calls: [],
    cfgSeen: new Set(),
    get api() { return api; },
    set api(v) {
      api = v;
      for (const [name, build] of pendingCalls.splice(0)) addCall(name, build);
    },
    // hook(path, readOriginal) → string to use, or undefined to keep the original.
    cfg(path, readOriginal) {
      arpg.cfgSeen.add(path);
      let value;
      let read = false;
      const original = () => (read ? value : ((read = true), (value = readOriginal())));
      let out;
      for (const hook of cfgHooks) {
        const r = hook(path, () => (out !== undefined ? out : original()));
        if (r !== undefined) out = r;
      }
      return out !== undefined ? out : original();
    },
    // Called by the game when it builds a world from a scenario (a new game, or the
    // World editor's preview when `editing` is true).
    worldCreated(world, scenario, editing) { runHooks('world', worldHooks, [world, scenario, !!editing]); },
    // Called by the game with the GM prompt's {head, sections, tail} before rendering.
    prompt(parts, world) {
      runHooks('prompt', promptHooks, [parts, world]);
      return parts;
    },
    // The mod-facing API.
    registerMod(name) { arpg.mods.push(name); },
    addCall,
    onConfig(hook) { cfgHooks.push(hook); },
    // hook(world, scenario, editing): copy scenario data onto the world. World fields are saved.
    onWorldCreate(hook) { worldHooks.push(hook); },
    // hook({head, sections, tail}, world): each part is a list of {kind, title, content}.
    // The game trims known kinds to a budget; a new kind is not trimmed, so keep it short.
    onPrompt(hook) { promptHooks.push(hook); },
    // Adds a header file to the GM's api-call list, after `after` (a header name) or at the end.
    addApiHeader(name, text, after) {
      const dir = 'overseer/api-actions/';
      cfgHooks.push((path, original) => {
        if (path === `${dir}${name}.txt`) return text;
        if (path !== `${dir}ordered-api-calls.json`) return undefined;
        let list;
        try { list = JSON.parse(original()); } catch { return undefined; }
        if (list.includes(name)) return undefined;
        const at = after ? list.indexOf(after) : -1;
        list.splice(at >= 0 ? at + 1 : list.length, 0, name);
        return JSON.stringify(list);
      });
    },
  };

  const prior = globalThis.__arpg;
  globalThis.__arpg = arpg;
  if (prior && prior.api) arpg.api = prior.api;
  console.info('[arpg] code-mod loader ready');
})();
