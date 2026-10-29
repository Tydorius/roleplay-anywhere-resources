# Voices: Delivery Cues

This pack adds one paragraph to the GM's scene rules (`overseer/scene_dsl.txt`). The paragraph lets the GM end a spoken line with a cue in round brackets, for example `Fine, I'll do it. (sighs)`. A Fish Audio Drama 3 endpoint performs the cue instead of reading it aloud. The cue also appears in the speech bubble.

Allowed cues: (sighs) (chuckles) (laughs) (gasps) (whispering) (excitedly) (nervously) (angrily) (sobbing) (screams)

**You need a server that guards against runaway clips**, such as [`server/voices_service.py`](../../server/voices_service.py). On a plain Drama 3 endpoint, a cued line occasionally turns into about a minute of repeated or garbled audio. The [voices README](../../README.md#delivery-cues) explains why cues use round brackets, why they go at the end of the line, and gives the test numbers.

## After a game update

This file replaces the game's `overseer/scene_dsl.txt` as a whole. To update it:

1. Copy the new default file from the game's `resources/config/default/overseer/` folder.
2. Re-insert the paragraph that starts `SAY_TO "text" is performed aloud`. Put it just above the line that starts "Never write two consecutive lines to the *player*".
