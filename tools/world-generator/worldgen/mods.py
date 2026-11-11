"""Finish a built scenario for shipping: the 1.0-native floor data and any
game-mod data.

The external builder writes its own flat-map scenario.json and zips the
folder. After it runs, the pipeline finishes the shipped scenario from the
spec: the ``nativeFloors`` the floors extension laid out (each upper storey
a region with ``pocket: {anchor, level}``, each stair or passage pair's
objects pointing at each other, the build-time fiction doors stripped from
the sealed storeys' borders, and gridSize back to the play area the floors
sit outside), the spec's ``arpgMods`` when another extension filled one
(lights), and the void-zone slabs hardened to walkability 0 (the spec
carried them as passable so the builder's flat walk could cross them). Then
it re-zips, so the shipped folder and zip both carry the finished scenario.
(The builder is never edited.)
"""
import json
import os
import zipfile


def _seal_floors(scn, sealed):
    """Strip the build-time fiction doors from the built scenario: every
    opening on a sealed storey's outer border goes. The rooms' interior
    doors stay; the stairs and passages (portals, in 1.0) are the storeys'
    only ways in and out."""
    from .model import Rect

    by_name = {r.get("name"): r for r in scn.get("regions", [])}
    ring = set()
    for name in sealed:
        area = by_name.get(name)
        if area is None:
            continue
        x, y = area.get("position", (0, 0))
        w, h = area.get("size", (0, 0))
        r = Rect(x, y, w, h)
        ring |= {(cx, cy) for cx in range(r.x, r.x + r.w) for cy in (r.y, r.y1)}
        ring |= {(cx, cy) for cx in (r.x, r.x1) for cy in range(r.y + 1, r.y1)}
    for r in scn.get("regions", []):
        r["openings"] = [list(c) for c in (r.get("openings") or [])
                         if tuple(c) not in ring]


def _harden_boundary(scn):
    """Void-zone slabs ship as they play: the spec declared them passable
    (passableAtBuild) so the builder's flat reachability walk could cross
    them; walkability 0 seals them here, and the tinted ground under them
    shows through. There is no world-edge slab any more: 1.0 floors are
    planes of their own, so nothing has to be sealed off from them."""
    for t in scn.get("objectTemplates") or []:
        if " Void Slab " in t.get("name", ""):
            t["walkability"] = 0.0


def finish_scenario(scenario_dir, spec):
    """Finish <scenario_dir>/scenario.json for shipping — the native floor
    data (pockets, portal links, the seal, the play-area gridSize), the
    spec's arpgMods when it has one, hardened void slabs — and rebuild the
    zip beside the folder. Returns the zip's path."""
    scn_path = os.path.join(scenario_dir, "scenario.json")
    with open(scn_path, "r", encoding="utf-8") as f:
        scn = json.load(f)
    if spec.get("arpgMods"):
        scn["arpgMods"] = spec["arpgMods"]
    native = spec.get("nativeFloors") or {}
    if native.get("floors"):
        by_name = {r.get("name"): r for r in scn.get("regions", [])}

        def region(name):
            r = by_name.get(name)
            if r is None:
                raise ValueError(f"nativeFloors names region {name!r}, "
                                 "which the built scenario does not have")
            return r

        # each storey becomes a 1.0 floor: its own plane, hanging off its
        # ground region at its level
        for fl in native["floors"]:
            region(fl["region"])["pocket"] = {
                "anchor": region(fl["anchor"])["id"],
                "level": fl["level"],
            }
        _seal_floors(scn, native.get("seal") or [])
        # each stair or passage pair links as the game's own "Link Portal":
        # both objects point at each other
        objs = {e.get("name"): e for e in scn.get("entities", [])
                if e.get("type") == "object"}

        def obj(name):
            e = objs.get(name)
            if e is None:
                raise ValueError(f"nativeFloors names object entity {name!r}, "
                                 "which the built scenario does not have")
            return e

        for pair in native.get("portals") or []:
            a, b = obj(pair["a"]), obj(pair["b"])
            a["portal"] = {"to": b["id"]}
            b["portal"] = {"to": a["id"]}
        # gridSize is the play area; the floors sit outside it, 1.0-style
        scn["gridSize"] = list(native.get("grid") or scn.get("gridSize"))
    _harden_boundary(scn)
    with open(scn_path, "w", encoding="utf-8") as f:
        json.dump(scn, f, ensure_ascii=False, indent=1)
    zip_path = scenario_dir.rstrip("\\/") + ".zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _dirs, files in os.walk(scenario_dir):
            for fn in files:
                full = os.path.join(base, fn)
                z.write(full, os.path.relpath(full, scenario_dir).replace(os.sep, "/"))
    return zip_path
