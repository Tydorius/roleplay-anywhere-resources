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
| Adult | orion (p009), dash (p004), cole (p016), riley (p019), theo (p031), marcus (p023), victor (p039), dom (p038), sam (p046), grant (p007), owen (p017), reid (p022), jerome (p010) | juno (p011), ruby (p028), zoe (p035), nora (p041), ivy (p043), ava (p003), stella (p014), iris (p012), cleo (p029), diane (p006), renee (p024), holly (p063), dana (p070) |
| MiddleAged | grant (p007), owen (p017), reid (p022), jerome (p010), walter (p025), frank (p054), glen (p077), arthur (p065), harold (p087), wes (p090), lloyd (p097), nigel (p008) | diane (p006), renee (p024), holly (p063), dana (p070), margot (p002), joan (p015), linda (p018), gloria (p098), bea (p032), ruth (p033), carol (p047), vera (p093) |
| Senior | arthur (p065), harold (p087), wes (p090), lloyd (p097), nigel (p008), ezra (synthetic) | bea (p032), ruth (p033), carol (p047), vera (p093), eleanor (p021), edith (p084) |

How EARS age brackets map to the game's age groups:

- 36-45 counts as Adult and MiddleAged.
- 46-55 counts as MiddleAged.
- 56-65 counts as MiddleAged and Senior.
- 66 and over counts as Senior.

- `orion` is the fallback narrator.
- jessie, casey, mia and tessa reuse the recordings of riley, theo, nora and ivy. They are the youngest adult speakers in EARS, listed again under Teen.
- The synthetic voices are Qwen3-TTS VoiceDesign voices built from a text description. EARS has no speakers under 18 and no male speakers over 65, so ezra is synthetic too.
- nigel (p008) is the only British English speaker in that age range. He is tagged `British`, which gives him an edge for characters with that tag.
- EARS p101 (male, 46-55) has no Rainbow Passage recordings, so it could not be used.
- `pitch` is left empty on every voice, so the matcher doesn't use pitch yet.
