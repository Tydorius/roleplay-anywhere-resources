# Voices: EARS + Drama 3

Ships `tts/custom-tts-config.json`, the voice list for the **Custom** speech service. With it, each NPC gets the voice that best fits its `voiceProfile` (gender, then age), not a random one. See the [voices README](../../README.md) for how matching works and how to adapt the list to your own server.

## Options → AI Speech

| Setting | Value |
|---|---|
| Speech service | Custom |
| Custom speech URL | your server, e.g. `http://127.0.0.1:8020/v1` |
| Custom speech model | `drama3` |
| Male / Female / Other voice ids | ignored while this pack is enabled |

## Voices

The voice ids are the names used in the registry of [`server/voices_service.py`](../../server/voices_service.py). The EARS speaker ids show which reference recording each voice is built from.

| Game age | Male | Female |
|---|---|---|
| Child | toby (synthetic) | lily (synthetic) |
| Teen | finn (synthetic), jessie (p019), casey (p031) | maya (synthetic), mia (p041), tessa (p043) |
| Adult | orion (p009), dash (p004), cole (p016), riley (p019), theo (p031), marcus (p023), victor (p039), dom (p038), sam (p046), grant (p007) | juno (p011), ruby (p028), zoe (p035), nora (p041), ivy (p043), ava (p003), stella (p014), iris (p012), cleo (p029), diane (p006) |
| MiddleAged | grant (p007), walter (p025), arthur (p065) | diane (p006), margot (p002), bea (p032) |
| Senior | arthur (p065) | bea (p032), eleanor (p021) |

- `orion` is the fallback narrator.
- jessie, casey, mia and tessa reuse the recordings of riley, theo, nora and ivy. They are the youngest adult speakers in EARS, listed again under Teen.
- The synthetic voices are Qwen3-TTS VoiceDesign voices built from a text description. EARS has no speakers under 18.
- `pitch` is left empty on every voice, so the matcher doesn't use pitch yet.
