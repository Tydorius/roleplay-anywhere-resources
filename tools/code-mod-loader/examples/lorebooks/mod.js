// lorebooks: keyword-triggered lore for the GM, carried inside the scenario file.
//
// scenario.json:
//   "arpgMods": {
//     "lorebookBudget": 2000,                       // optional, characters per turn
//     "lorebooks": {
//       "College History": {
//         "entries": [
//           {"keys": ["Vellan", "Archmage"], "content": "...", "priority": 10},
//           {"keys": ["Sundering"], "secondaryKeys": ["war", "battle"], "content": "..."},
//           {"constant": true, "content": "Magic is illegal outside the college walls."}
//         ]
//       }
//     }
//   }
//
// SillyTavern World Info field names (key, keysecondary, disable, order, and an
// "entries" object keyed by uid) are accepted too.
(() => {
  const arpg = globalThis.__arpg;
  arpg.registerMod('lorebooks');

  const DEFAULT_BUDGET = 2000;
  const DEFAULT_STICKY_MINUTES = 10;
  // Prompt sections that describe what is happening near the player right now.
  // The full region list and far-away characters are left out, or everything would match.
  const SCAN_KINDS = new Set(['scene', 'characters', 'objects', 'party', 'quest', 'events', 'now']);

  const list = v => (Array.isArray(v) ? v : typeof v === 'string' && v.trim() ? [v] : []);

  function normalizeEntry(raw, book, index) {
    const keys = list(raw.keys ?? raw.key).map(String).filter(k => k.trim());
    const content = String(raw.content ?? '').trim();
    return {
      id: `${book}#${raw.uid ?? raw.id ?? index}`,
      book,
      keys,
      secondaryKeys: list(raw.secondaryKeys ?? raw.keysecondary).map(String).filter(k => k.trim()),
      content,
      constant: !!raw.constant,
      enabled: raw.enabled !== false && raw.disable !== true,
      priority: Number(raw.priority ?? raw.order ?? 0) || 0,
      stickyMinutes: Number(raw.stickyMinutes ?? DEFAULT_STICKY_MINUTES),
    };
  }

  // All usable entries from an `arpgMods` block.
  function entriesOf(mods) {
    const out = [];
    for (const [book, def] of Object.entries(mods?.lorebooks ?? {})) {
      if (!def || def.enabled === false) continue;
      const raw = Array.isArray(def.entries) ? def.entries : Object.values(def.entries ?? {});
      raw.forEach((r, i) => {
        if (!r || typeof r !== 'object') return;
        const e = normalizeEntry(r, book, i);
        if (e.enabled && e.content && (e.constant || e.keys.length)) out.push(e);
      });
    }
    return out;
  }

  const escape = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const keyCache = new Map();
  // Case-insensitive whole-word match; "word" means letters and digits in any script.
  function mentions(text, key) {
    let re = keyCache.get(key);
    if (!re) {
      re = new RegExp(`(?<![\\p{L}\\p{N}])${escape(key.trim())}(?![\\p{L}\\p{N}])`, 'iu');
      keyCache.set(key, re);
    }
    return re.test(text);
  }

  // Picks the entries to inject. `state` maps entry id → game second it last matched.
  function select(entries, text, nowSecs, state, budget) {
    const hits = [];
    for (const e of entries) {
      let why = null;
      if (e.constant) why = 'constant';
      else {
        const key = e.keys.find(k => mentions(text, k));
        const secondaryOk = !e.secondaryKeys.length || e.secondaryKeys.some(k => mentions(text, k));
        if (key && secondaryOk) {
          why = `key "${key}"`;
          state[e.id] = nowSecs;
        } else if (state[e.id] !== undefined && nowSecs - state[e.id] <= e.stickyMinutes * 60) {
          why = 'sticky';
        }
      }
      if (why) hits.push({ e, why });
    }
    hits.sort((a, b) => (b.e.constant - a.e.constant) || (b.e.priority - a.e.priority));
    const chosen = [];
    let used = 0;
    for (const h of hits) {
      const cost = h.e.content.length + 3;
      if (used + cost > budget) continue;
      chosen.push(h);
      used += cost;
    }
    return chosen;
  }

  function scanText(parts, world) {
    const sections = [...parts.head, ...parts.sections, ...parts.tail].filter(s => SCAN_KINDS.has(s.kind));
    const lastTurn = world.overseerHistory?.length ? JSON.stringify(world.overseerHistory[world.overseerHistory.length - 1]) : '';
    return [...sections.map(s => s.content), lastTurn].join('\n');
  }

  arpg.onWorldCreate((world, scenario) => {
    if (scenario?.arpgMods) world.arpgMods = JSON.parse(JSON.stringify(scenario.arpgMods));
  });

  arpg.onPrompt((parts, world) => {
    const mods = world.arpgMods;
    const entries = entriesOf(mods);
    if (!entries.length) return;
    const state = (mods.lorebookState ??= {});
    const budget = Number(mods.lorebookBudget) > 0 ? Number(mods.lorebookBudget) : DEFAULT_BUDGET;
    // The mod enforces its own budget; this only stops the game's trimmer from
    // tagging an unknown section kind with "(0 more lines omitted)".
    if (arpg.promptBudgets && !('lore' in arpg.promptBudgets)) arpg.promptBudgets.lore = 1e6;
    const chosen = select(entries, scanText(parts, world), world.gameTimeSecs ?? 0, state, budget);
    arpg.lore.last = chosen.map(({ e, why }) => ({ book: e.book, id: e.id, why }));
    if (!chosen.length) return;
    parts.sections.push({
      kind: 'lore',
      title: 'Lore (established facts about what is in play now; use them, never contradict them):',
      content: chosen.map(({ e }) => `- ${e.content}`).join('\n'),
    });
  });

  arpg.lore = { entriesOf, select, mentions, last: [] };
})();
