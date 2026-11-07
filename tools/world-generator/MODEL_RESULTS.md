# World generator model test results

Tested in November 2026 on the generator as of PR #7. The one bug these runs found is fixed in PR #8 (see the notes).

Two tests, both on one small fishing hamlet:

1. **Complete worlds:** six models each built the whole world alone, three times, the way you'd run the generator yourself. Start here if you're choosing a model.
2. **One prompt at a time:** 15 local models and 7 tested earlier answered all 11 generator prompts, each from the same hand-picked earlier results, so each prompt is a fair comparison on its own.

## Read this first

- **One hamlet.** A town, a station or a castle may favour different models.
- **Few tries.** Three worlds per model in the first test, one try per prompt in the second. Small differences, such as a few retries, could be luck.
- **Quality notes are one reviewer's judgement** (Claude, the AI assistant that ran the tests), from reading samples of each model's output.
- **Speed isn't reported.** The local models ran at the same time on one machine, so timings mean nothing.
- **Local settings:** llama.cpp b11712, 32k context per request, 8-bit KV cache, each model's recommended sampling where it has one. All were run on a Mac Studio (M3 Ultra), not on a consumer GPU, so whether a model fits a given card is estimated from its file size.
- **Plain output only.** No forced JSON or grammar was used.

## Complete worlds

Each model built the hamlet three times from the one-line idea, with no questionnaire and no resident count, so the model decided how many people live there. All 18 worlds ran at once.

| Model | File (GB) | Worlds built (of 3) | Calls failed (all 3) | Retries (all 3) | Tokens per world | Buildings | People | Notes |
|---|---|---|---|---|---|---|---|---|
| Gemma 4 31B (Q8) | 35.0 | 3 | 0 | 4 | 101k (91–121k) | 7 | 22–30 | Cleanest and cheapest. Reuses one design for identical cottages. Too big for a consumer card at Q8. |
| Deckard 31B (Q4) | 18.7 | 3 | 0 | 9 | 133k (121–148k) | 7–8 | 22–29 | No failed calls and well-furnished buildings. Should fit a 24 GB card. |
| Magnum-Diamond 24B (Q4) | 14.3 | 3 | 4 | 35 | 103k (82–143k) | 5–7 | 11–12 | All built, with the smallest casts. |
| Cydonia 24B (Q4) | 14.3 | 3 | 5 | 36 | 129k (104–147k) | 5–7 | 13–18 | All built, but more retries than in the prompt test, and one villager named "Torben Torben". |
| Gemma 4 12B (Q4) | 7.1 | 3 | 1 | 11 | 199k (188–216k) | 5–7 | 11–32 | All built, at about twice the tokens of the 31B. |
| Ministral 3 14B (Q4) | 8.2 | 2 | 7 | 39 | 155k (142–181k) | 6–8 | 18–22 | One world lost to a generator bug, since fixed (see notes). Followed the idea closely. |

- **The prompt test's ranking held.** The same models came out on top, and none failed outright. The two 24B tunes and Ministral needed far more retries working alone, as expected without hand-picked inputs.
- **A failed call doesn't lose the world.** Every world with failed calls still built, minus the failed piece.
- **Following the idea:** the idea asked for "a widowed net-mender". Ministral and Magnum kept a widowed villager in all three worlds, Cydonia and Gemma 12B in one, and Gemma 31B and Deckard in none.
- **Names repeat.** Four of the 18 worlds were called Frosthaven, three of them by Ministral. Elara, Finn, Silas and Kael came up again and again.
- **Template text leaked** into the outdoor-prop rules in one Cydonia world and one Deckard world (`behind:<building>`). The map still built.

## One prompt at a time: local models

| Model | File (GB) | Rounds failed (of 11) | Calls failed | Retries | Buildings (of 7) | Total tokens | Notes |
|---|---|---|---|---|---|---|---|
| Magnum-Diamond 24B (Q4) | 14.3 | 0 | 0 | 9 | 7 | 96,496 | Cheapest overall, but plain writing. |
| Cydonia 24B (Q4) | 14.3 | 0 | 0 | 7 | 7 | 102,278 | Best roleplay tune: passes everything at low cost. |
| Gemma 4 31B (Q8) | 35.0 | 0 | 0 | 0 | 7 | 102,658 | Cleanest run of the new set. Too big for a consumer card at Q8. |
| Deckard 31B (Q4) | 18.7 | 0 | 0 | 3 | 7 | 117,367 | Fullest buildings of the local models (108 pieces). Should fit a 24 GB card. |
| GPT-OSS 20B (MXFP4) | 12.1 | 0 | 0 | 7 | 7 | 139,694 | Reliable; left one placeholder value in P6a. |
| Gemma 4 26B-A4B (Q4) | 16.9 | 0 | 0 | 2 | 7 | 180,977 | Solid, about twice Deckard's tokens. |
| Gemma 4 12B (Q4) | 7.1 | 0 | 0 | 4 | 7 | 198,259 | Capable for its size, with no failed calls. |
| Ternary Bonsai 2 27B (Q2) | 7.6 | 0 | 0 | 3 | 7 | 321,157 | Works, at 3x the tokens. Very slow under load. |
| Ornith 1.5 9B (Q4) | 5.8 | 0 | 0 | 11 | 7 | 388,096 | Most specific writing, highest token use of the new set. |
| Ministral 3 14B (Q4) | 8.2 | 0 | 1 | 10 | 7 | 120,867 | Strongest writing for its cost. One failed call. |
| Mistral Small 3.2 24B (Q4) | 14.3 | 0 | 2 | 10 | 6 | 184,454 | Plain writing. Ran away on P2 items (see notes). |
| Mistral Nemo 12B (Q4) | 7.5 | 0 | 7 | 23 | 3 | 149,147 | Not reliable enough to use alone. |
| Wayfarer 2 12B (Q4) | 7.5 | 0 | 11 | 28 | 5 | 270,993 | Good prose, poor structure. Not reliable alone. |
| Mag-Mell 12B (Q4) | 7.5 | 1 | 5 | 23 | 5 | 152,925 | Failed P1. Not reliable alone. |
| Rocinante-X 12B (Q4) | 7.5 | 1 | 9 | 24 | 3 | 191,301 | Failed P2. Not reliable alone. |

## One prompt at a time: earlier results, for comparison

Deckard Q8 ran locally with 128k context. The others ran on OpenRouter's free tier, so their settings were the host's, and their retries include some rate-limit trouble.

| Model | File (GB) | Rounds failed (of 11) | Calls failed | Retries | Buildings (of 7) | Total tokens | Notes |
|---|---|---|---|---|---|---|---|
| Deckard 31B (Q8, 128k context) | 32.6 | 0 | 0 | 0 | 7 | 100,549 | The earlier baseline, run alone. |
| Flint v1.0 | - | 0 | 0 | 4 | 7 | 293,833 | OpenRouter free tier. |
| Nemotron 3.5 Lightning | - | 0 | 0 | 5 | 7 | 327,130 | OpenRouter free tier. |
| Nemotron 3 Nano Omni 30B | - | 0 | 1 | 6 | 6 | 273,434 | OpenRouter free tier. |
| North Mini Code | - | 0 | 1 | 14 | 7 | 354,742 | OpenRouter free tier. |
| Xing 4.0 29B | - | 0 | 2 | 11 | 6 | 366,648 | OpenRouter free tier. |
| LFM 2.5 2.6B | - | 0 | 11 | 27 | 4 | 413,371 | OpenRouter free tier. |

Stock Gemma 4 26B and 31B on OpenRouter's free tier are left out: they returned rate-limit errors (429) on every round, so they were never really tested there. The same models ran locally without trouble.

## Terms

- **Rounds failed:** the generator stopped because a required prompt never gave a usable reply.
- **Calls failed:** a call ran out of retries. In most rounds the generator carries on without that piece, such as a missing building.
- **Retries:** extra attempts after a reply failed the generator's checks.
- **Buildings:** in the prompt test, how many of the seven given buildings came through the checks. In the complete worlds, how many the model planned itself.
- **Worlds built:** the run finished with a scenario file you can load.

## Notes on individual results

- **Ministral's lost world:** all 25 calls succeeded, then the final build rejected 11 pieces of furniture in the inn's guest rooms as sitting on walls, and wrote no scenario. Re-laying the same plan on other seeds failed the same way. The cause was partly the model and mostly the generator. Ministral listed the inn's four guest rooms one by one, beside the single guest-room design the generator copies, and the layout then squeezed all seven rooms into a space one guest room wide. Since PR #8 the generator drops numbered copies like these, and stacks entrance rooms in rows when they don't fit side by side. The same plan now builds with no errors. In four other solo worlds, re-laid with the fix, unplaced furniture fell from 5, 7, 8 and 28 pieces to 0, 0, 1 and 6.
- **Complete-world timing:** the 24B and 14B worlds took 1.6–2.8 hours each, and the Gemma and Deckard worlds 5.5–6.6 hours, but all 18 shared the Mac with a side test, so these say nothing about speed on your own machine.
- Four calls hit a 2-hour request limit while all 15 models shared the Mac: P2 items on Bonsai, Mistral Small and Wayfarer, and one P3 building on Bonsai. Those timed-out attempts aren't counted as retries, because the load caused them.
- **Mistral Small:** after its timeout on P2 items, both retries ran to the 32k context limit (30,988 tokens each) and the call failed. That's the model running away, not the load, so it stays in the table. A separate rerun on the idle Mac passed first time with 62 items in 6,091 tokens, so this failure doesn't happen every time.
- **Wayfarer:** its retry on P2 items passed, and a rerun on the idle Mac also passed first time.
