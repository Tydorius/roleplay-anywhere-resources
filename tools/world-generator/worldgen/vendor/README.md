# Vendored scenario tools

The tools in this folder are vendored so the generator is self-contained:
the pipeline never touches anything outside this repository.

- `scenario_checks.py` is an **exact copy** of `tools/scenario-editor/scenario_checks.py` (Anywhere RPG
  1.0's value lists and map rules). `validate_scenario.py` imports its lists and 1.0 rules from it:
  floors beside the map (`pocket` regions), `[x, y, side]` openings, `npcTemplates` with homes and the
  renamed sprites. Copy the editor's file here after changing it; `tests/test_vendor_checks.py` fails
  while the two differ. `build_scenario.py` doesn't emit any 1.0 feature yet.

- Source: the `_tools/` folder of the Roleplay Anywhere Scenarios workspace
  on Michael's machine (files `build_scenario.py`, `validate_scenario.py`,
  `render_map.py`).
- Vendored: 2026-11-01, brief 010.
- `build_scenario.py` includes the local change that carries a region's
  `groundColor`/`wallColor` through to the built `scenario.json`.
- Local changes made while vendoring, and nothing else:
  - `render_map.py` treats Pillow as optional: without it the script prints one
    clear message and exits 0 instead of crashing on `from PIL import ...`.
  - the usage strings name `worldgen/vendor/…` instead of `_tools/…`.
  - `render_map.py` draws a zero-wide object (a 1.0 door, `size [1, 0]` or `[0, 1]`) as a bar on its wall
    line. Pillow refuses a zero-height rectangle, so every world with doors lost its preview (2026-11-11).

They are invoked by relative path (`worldgen/vendor/<tool>.py`), in-process
imports are not used. To pick up an upstream change, copy the file here and
re-apply the notes above; see `SCENARIO_AUTHORING_GUIDE.md` in the source
repository for the spec format.
