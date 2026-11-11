# fill_test_images.py

Test helper for Anywhere RPG 1.0 live testing. The New Game screen keeps
"Begin Adventure" disabled until every image a scenario needs exists, and each
missing image waits minutes on ComfyUI. This tool copies a scenario (zip or
folder) and fills each missing image with a byte copy of an existing image of
the same kind (`sprite` / `portrait` / `item` / `perk`), chosen by word overlap
between the owner texts. **Test copies only**: it never modifies its input or
any donor, and it refuses to write into the presets folder or the Steam
install.

## Command

```
python tools/code-mod-loader/tests/tools/fill_test_images.py INPUT -o OUTPUT [--donor DIR ...] [--presets DIR] [--dry-run]
```

- `INPUT`: a scenario `.zip` (with `scenario.json` at the zip root) or a
  scenario folder. `OUTPUT` has the same form (zip in → zip out, folder in →
  folder out) and must not exist yet.
- `--donor DIR`: extra scenario folder to copy images from (repeatable).
- `--presets DIR`: the 1.0 presets folder; every subfolder with a
  `scenario.json` and `media/` is a donor source (default: the installed
  build's `resources\presets`, skipped quietly when absent).
- `--dry-run`: print the plan without writing anything.

Donors are preferred in this order: the scenario's own media, then `--donor`
folders, then presets. Donor images never cross kinds. Word overlap picks the
donor (words from `name` count double on both sides); ties prefer an unused
donor, then the earlier source, then the alphabetically lower path, so runs are
deterministic. Only the base `<ownerId>-sprite.webp` is checked and copied —
never the `-normal` / `-outline-*` variants.

Exit status: `0` when nothing is unfilled, `1` when something is (the copy is
still written), `2` on bad input or a refused output path.

## Example

```
$ python tools/code-mod-loader/tests/tools/fill_test_images.py ~/scen/thornbury-edit.zip -o ~/scen/thornbury-edit-filled.zip
filled portrait htpl_x (Grey Wolf) <- preset thornbury: htpl_y (Wolf) [score 4]
1 missing, 1 filled, 0 unfilled -> ~/scen/thornbury-edit-filled.zip
```

Run the tests from the repository root:

```
python -m unittest discover -s tools/code-mod-loader/tests/tools -v
```
