# Voices: Delivery Cues

This pack adds one paragraph to the GM's scene rules (`overseer/scene_dsl.txt`). The paragraph lets the GM end a spoken line with a cue in round brackets, for example `Fine, I'll do it. (sighs)`. A Fish Audio Drama 3 endpoint performs the cue instead of reading it aloud. The cue also appears in the speech bubble.

Allowed cues: (sighs) (chuckles) (laughs) (gasps) (whispering) (excitedly) (nervously) (angrily) (sobbing) (screams)

**You need a server that guards against runaway clips**, such as [`server/voices_service.py`](../../server/voices_service.py). On a plain Drama 3 endpoint, a cued line occasionally turns into about a minute of repeated or garbled audio. The [voices README](../../README.md#delivery-cues) explains why cues use round brackets, why they go at the end of the line, and gives the test numbers.

**Game version:** Anywhere RPG 1.0. The file is 1.0's default `overseer/scene_dsl.txt` plus the cue paragraph. The 0.18 version of this pack is on the repository's `0.18` branch.

## After a game update

This file replaces the game's `overseer/scene_dsl.txt` as a whole. **Re-check it after every game update.** An out-of-date copy silently undoes whatever the update changed in that file. For example, the 0.18 copy would remove three of 1.0's changes: objects as `MOVE_TO` actors, the `${TAKE_VERBS}` / `${ITEM_VERBS}` placeholders that add STEAL, and `range: 0` at a vehicle's controls.

The script does the check:

```bash
python mods/voices/tools/rebase_delivery_cues.py "<your Anywhere RPG install folder>"
```

- **Up to date:** the pack still matches the game's default plus the cue paragraph.
- **Out of date:** the script prints the difference. Run it again with `--write` to rebuild the pack, then copy the pack into your mods folder again.

To do it by hand:

1. Copy the new default file from the game's `resources/config/default/overseer/` folder.
2. Re-insert the paragraph that starts `SAY_TO "text" is performed aloud`. Put it just above the line that starts "Never write two consecutive lines to the *player*".

To check that the game uses the pack, play one GM turn. Then open the newest `*-request-*.txt` in the game's `logs/overseer/` folder. It should contain the cue paragraph and no leftover `${...}` placeholders.
