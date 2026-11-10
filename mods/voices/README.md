# Voices for Anywhere RPG (Custom speech endpoint)

Anywhere RPG can voice NPC dialogue through any OpenAI-compatible `/v1/audio/speech` server: in **Options → AI Speech**, set the speech service to **Custom**. In its simplest setup the game picks a random voice from three comma-separated lists (Male, Female, Other).

The engine can do much more than that. This folder covers:

| Folder | What it is |
|---|---|
| [`packs/voices-ears-drama3`](packs/voices-ears-drama3) | A voice list that matches each NPC to a voice by gender and age (Child to Senior), not at random. |
| [`packs/voices-delivery-cues`](packs/voices-delivery-cues) | Lets the GM add delivery cues such as `(sighs)` to spoken lines. |
| [`server/`](server) | A small OpenAI-compatible proxy with a named voice registry. It runs over [mlx-audio](https://github.com/Blaizzy/mlx-audio) with Fish Audio Drama 3 and Qwen3-TTS, and guards against runaway clips. |
| [`tools/rebase_delivery_cues.py`](tools/rebase_delivery_cues.py) | Checks the cue pack against your game's default `scene_dsl.txt`, and rebuilds it after a game update. |

**Game version:** built for Anywhere RPG 1.0. The voice-picking rules below were worked out from
version 0.16's config files and code and tested against a live server. They were re-checked on
1.0, and these parts are unchanged: the voice matcher, the text filter, `tts/custom-tts-config.json`
and `voiceProfile`. `voices-delivery-cues` was rebuilt on 1.0's `overseer/scene_dsl.txt`, plus its
one paragraph. It was tested in the live 1.0 game. The 0.18 version is on the `0.18` branch.

**After every game update, re-check the cue pack.** It replaces the game's whole `scene_dsl.txt`,
so an old copy silently undoes whatever the update changed in that file. Run:

```bash
python mods/voices/tools/rebase_delivery_cues.py "C:/Program Files (x86)/Steam/steamapps/common/Anywhere RPG"
```

It says whether the pack is still the game's default plus the cue paragraph. If not, it shows the
difference. Add `--write` to rebuild the pack, then copy the pack into your mods folder again.

## How the game picks a voice

Each speech service has a voice list in the game's `resources/config/default/tts/` folder: `official-tts-config.json`, `official-obsidian-tts-config.json` and `custom-tts-config.json`. A mod replaces one of these by shipping a file at the same path. The game's own `tts/README.txt` describes the format.

To choose a speaker's voice, the game goes through these steps in order:

1. **A voice pinned on the character.** It is stored on the entity as a map from service name to voice id:
   ```json
   "voiceIds": { "Custom": "walter" }
   ```
   - The service names are `Custom`, `Official` and `Official (Obsidian)`.
   - You can write this into a scenario's `scenario.json`; import keeps it.
   - You can also set it in god mode, with the character's **Voice** dropdown.
   - Changing a character's gender clears it.
2. **Profile matching**, when the service's config file lists voices. Every voice with `allowed_for_matching: true` is scored against the character's `voiceProfile`:
   - Gender must match.
   - If the voice has `required_tags`, the character must carry one of them.
   - **age:** an exact age group (Child, Teen, Adult, MiddleAged, Senior) scores 4, the neighbouring group 2, anything further 0.
   - **pitch:** scored the same way on Deeper, Average and Brighter.
   - **tags:** each tag that matches adds 3.

   The highest score wins, and ties are broken at random. A voice with an empty `age` or `pitch` list is neutral on that axis. Characters without a profile are matched as gender + Adult.
3. **The Options lists**, but only when `custom-tts-config.json` has no voices. Voices are picked at random by gender.

Once a voice is chosen, it is saved on the character, so each NPC keeps the same voice for the whole save. The exception is monsters spawned from enemy templates: they can't be pinned and always go through matching.

**Language (1.0).** Matching only considers voices whose `language` equals the game's language
code, for example `en` for English. If the list has no voice at all for that language, 1.0 turns
speech off and shows a warning. If it has voices for the language but none of the speaker's gender,
1.0 warns that the service has no male (or female) voices for the language. The
`voices-ears-drama3` list has 26 male and 27 female voices, all `en`, so neither warning appears in
English. To play in another language, add voices with that language code.

### Writing your own voice list

Copy [`packs/voices-ears-drama3`](packs/voices-ears-drama3) and edit `tts/custom-tts-config.json`:

- **`id`**: the exact string your server accepts as `voice`.
- **`gender`**: `Male` or `Female`.
- **`age`**: one or more of `Child Teen Adult MiddleAged Senior`. Keep this list tight: a voice that lists many ages competes with every age it lists, so matching becomes less exact.
- **`pitch`** (optional): `Deeper Average Brighter`.
- **`tags`** (optional): accent or style words that raise the score, for example `British`, `Southern`, `Villain` or `Whispering`. You can also invent new tags; the character generator then starts using them.
- **`required_tags`**: for a voice only some characters should get, for example a growly voice limited to `["Demonic"]`.
- **`allowed_for_matching: false`**: the voice is never picked automatically, but you can still choose it by hand in god mode.
- **`default_narrators.en`**: the voice used when nothing matches.

Restart the game after editing; mod files load at startup.

### Scenarios

A pinned `voiceIds` value only works on a server that has that id. In scenarios you share, give every NPC a good `voiceProfile` instead, because that works with every speech service. Keep pins for your own copies.

## Delivery cues

Fish Audio Drama 3 performs bracketed cues such as `[sighs]` or `[laughs]` instead of reading them. Two things get in the way.

**The game removes most punctuation.** Before sending a line to a Custom endpoint, the game deletes every character except letters, digits, spaces and the following: `- ' / . , ; : ! ? ( ) —`. So:

- `[sighs]` arrives as the bare word `sighs`, and it is read aloud.
- `*sighs*` loses its asterisks the same way. The game keeps asterisks only for the Official (Obsidian) service.
- `(sighs)` arrives intact. That is why the cue pack uses round brackets, and why the server converts them to `[sighs]`.

**Drama 3 "runs away" more often with cues.** A runaway is a clip that repeats itself or turns to garbage until it hits the token cap, which is about 55 s at mlx-audio's default of 1200 tokens. Where the cue sits matters more than anything else:

| Placement (15 lines each: 5 cues, 3 voices) | Runaways |
|---|---|
| Cue at the start of the line | 8 / 15 |
| Cue at the start of the second sentence | 4 to 6 / 15 |
| Cue at the end of the first sentence | 3 / 15 |
| **Cue at the end of the line** | **0 / 15** |
| No cue | 1 / 15 |

Changing the sampling settings did not help: repetition penalty 1.2, top_p 0.7 and temperature 0.4 gave 8 to 12 runaways out of 15.

So the cue pack asks the GM to put cues at the end of the line, and the server moves any cue there anyway. The server also guards each clip's length:

- **Limit:** 3 s + 0.6 s per word + 2 s per cue. Generation is capped just above it, using Drama 3's rate of 21.4 audio tokens per second and Qwen VoiceDesign's 12.4.
- **Retries:** an over-long clip is regenerated without its cues, up to twice.
- **Cost:** in testing, about 1 in 6 cued lines needed one extra generation of about 2 s. The worst case was about 14 s.

This matters because the game drops a voice clip that hasn't started within 5 s after its speech bubble ends.

Qwen3-TTS VoiceDesign voices read cues aloud. For those voices the server removes the cue from the text and adds it to the voice description instead.

## The reference setup

- **Backend:** an [mlx-audio](https://github.com/Blaizzy/mlx-audio) server on an Apple Silicon Mac. It serves `mlx-community/fish-audio-drama-3-4bit` for cloned voices and `mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit` for described voices. A short line takes about 1 to 3 s once the models are loaded.
- **Cloned voices:** each one is cloned from a reference clip of about 60 s. The clip is one speaker from the [EARS dataset](https://github.com/facebookresearch/ears_dataset) reading the Rainbow Passage (parts 1 to 5, joined with 250 ms gaps, 48 kHz mono), plus its exact transcript.
- **Described voices:** children and young teens are Qwen VoiceDesign voices, defined by a plain-English description, because EARS speakers are all adults.
- **The proxy:** [`server/voices_service.py`](server/voices_service.py) maps each voice name to its reference clip or description. It reads the registry on every request, so edits take effect without a restart. See [`voices.example.json`](server/voices.example.json) for one entry of each kind.
- **Not handled:** the game sends a `speed` value, but neither engine uses it.

The reference clips are not included. To use the same voice ids, build your own clips from EARS with the speaker ids listed in the pack's PACK-NOTES.

### Licences

- **EARS:** CC BY-NC 4.0, so voices cloned from it are for non-commercial use.
- **Fish Audio Drama 3:** the Fish Audio Community License. Read it before any commercial use.
