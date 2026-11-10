// memory-add: lets the GM write a memory straight onto a character (Character panel →
// Memories). Anywhere RPG 1.0 keeps a character's memory as one prose text, `entity.memory`,
// which its memory fold condenses to the "character memory words" limit; this appends a sentence.
(() => {
  const arpg = globalThis.__arpg;
  arpg.registerMod('memory-add');

  arpg.addApiHeader('header_memory', [
    '-- Character memory --',
    '{"call":"memory_add","target":"character name","text":"one past-tense sentence, from their point of view"} ' +
      '// only for what this character would never forget: a promise, a betrayal, a secret learned, a life saved. ' +
      'The engine records routine memories on its own, so never repeat ordinary events',
  ].join('\n'), 'header_entity_state');

  arpg.addCall('memory_add', api => {
    // Reuse the game's own field types: an entity name the engine resolves, and plain text.
    const schema = api.hp_delta.schema.pick({ target: true }).extend({ text: api.flavor_text.schema.shape.text });
    return {
      schema,
      run(world, { target, text }) {
        if (target.type !== 'npc') return 'memory_add target must be a character';
        let line = String(text).trim().replace(/\s+/g, ' ').slice(0, 300);
        if (!line) return 'memory_add needs text';
        if (!/[.!?…]$/.test(line)) line += '.';
        const prior = typeof target.memory === 'string' ? target.memory.trim() : '';
        if (prior.includes(line)) return null;
        target.memory = prior ? `${prior} ${line}` : line;
        return null;
      },
    };
  });
})();
