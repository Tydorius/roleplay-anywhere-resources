# Vendored scenario tools

The three tools in this folder are vendored so the generator is self-contained:
the pipeline never touches anything outside this repository.

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

They are invoked by relative path (`worldgen/vendor/<tool>.py`), in-process
imports are not used. To pick up an upstream change, copy the file here and
re-apply the notes above; see `SCENARIO_AUTHORING_GUIDE.md` in the source
repository for the spec format.
