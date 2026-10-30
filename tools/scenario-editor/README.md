# Scenario Editor

Edit an Anywhere RPG scenario by hand after the game (or a script) has generated it: look over the
map, find problems, fix names and descriptions, and download a zip for **New Game → Import…**.

**Early version.** The map editing works: move, resize, draw, place, doors and delete. The object,
NPC and schedule editors come next.

## Start it

Double-click the launcher for your system in this folder. It opens the editor in your browser at
`http://127.0.0.1:8766`; close the launcher's window to stop it.

| System | Launcher |
|---|---|
| Windows | `Start Scenario Editor.bat` |
| macOS | `Start Scenario Editor.command` |
| Linux | `start-scenario-editor.sh` |

It needs Python 3.8 or newer, and nothing else. From a terminal: `python scenario_editor.py`.

## Works with the Image Gallery

The editor runs on the [Image Gallery](../../mods/better-images)'s code and leaves the gallery itself
unchanged. The gallery still works on its own.
- **Same workspaces.** A scenario you open in one shows up in the other.
- **Images tab.** This is the gallery's own page, open on the same scenario: regenerate images
  through ComfyUI, then keep or discard them.

## What it does now

- **Open** a scenario zip as a workspace (**Open zip…**), or copy the game's current New Game into
  one (**Copy to workspace**). The game's own folders are only read.
- **Map:** the regions, walls and doors as the game builds them, plus objects (with their sprites,
  turned the way they face) and people. Drag empty space to pan (or Space+drag anywhere), scroll to
  zoom, and click to select. Click again to pick the next thing underneath, and Shift+click to add
  to the selection. A minimap in the corner shows where you are; click or drag on it to go there.
- **Moving things only moves what's already selected.** Click first, then drag. A drag that starts
  on anything else pans the map, so a slip of the mouse never moves the furniture.
- **Tools** (the strip at the top of the map, or the key in brackets):
  - **Select (V):**
    - drag a selected object or person to move it;
    - drag a selected region by its round centre handle (its rooms, doors, objects and people come
      along);
    - drag a selected region's edge to resize it. Walls it shares follow: its building's wall, and
      the next room's wall, so rooms that split a building stay split. Hold Alt to move only its
      own edge.
    - Shift+drag selects everything wholly inside a box.
  - **Region (B):** name it, choose walls or none and whether it's hostile, then drag a rectangle.
  - **Object (O):** pick a type, then click to place one (click again for more). R turns it first.
  - **NPC (N):** name them and click. They start with an all-day schedule in the region they stand in.
  - **Door (D):** click a cell on a walled region's outer row or column. A door on a shared wall is
    added to both sides, the way the game's own editor does it.
  - **Measure (M):** drag to measure in cells and metres. Selecting a hostile shows its 7-cell
    aggro ring and 14-cell give-up ring.
- **Keys:**
  - arrows nudge the selection (Shift+arrow: 5 cells);
  - R and Shift+R turn objects;
  - Delete removes the selection;
  - Ctrl+C and Ctrl+V copy a region (with its rooms and objects) or objects, and paste them where
    the pointer is;
  - F centres the selection;
  - Esc cancels a drag or goes back to Select, and so does a right-click.
- **Nothing breaks the map.** A move, resize, new region or paste that would leave two regions
  partly overlapping is refused, and so is anything that would leave the map.
- **Delete is safe.** A region that schedules, calendar events or hostile types use is not deleted;
  "Used by" lists what to change first. Deleting a region leaves its rooms and objects where they
  are. The player can't be deleted.
- **Layers:** lock a layer so clicks go through it, or hide it.
- **Problems:** the scenario is checked after every change (`scenario_checks.py`). Click a problem
  to jump to it.
- **Inspector:** details of what you selected, and everything that uses it, each one clickable.
- **Rename a region:** every schedule and calendar event that names it is updated as well.
- **Undo and redo** (Ctrl+Z, Ctrl+Y), with a whole drag as one step. **Save** (Ctrl+S) and
  **Download zip**. Each save first backs up the previous `scenario.json` to
  `mods/better-images/gallery-backups/`.

## Tests

```
node --test
```

Run this from this folder. It tests the map operations (`mapops.js`) and the minimap's coordinate
helpers. It needs Node 18 or newer and nothing else.

## Checks on their own

```
python scenario_checks.py My-Scenario.scenario.zip
```

This checks a zip, a folder or a `scenario.json` against the rules the game actually uses. The exit
code is 1 if there are errors.
