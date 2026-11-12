"""Finish a built scenario for shipping: the 1.0-native floor data, the
door objects on every doorway, and any game-mod data.

The external builder writes its own flat-map scenario.json and zips the
folder. After it runs, the pipeline finishes the shipped scenario from the
spec: the ``nativeFloors`` the floors extension laid out (each upper storey
a region with ``pocket: {anchor, level}``, each stair or passage pair's
objects pointing at each other, the build-time fiction doors stripped from
the sealed storeys' borders, and gridSize back to the play area the floors
sit outside), the ``nativeDoors`` door kinds written onto the walled regions
and a door object hung on every doorway that has none (of the doorway's
room's kind — a doorway with no door object is an open gap in 1.0, and the
game adds no doors to imported scenarios), the ``nativeLocks`` rooms locked
with their keys handed out and the theft buildings flagged, the
``nativeSecrets`` doorways hidden (every door object of the doorway carries
the game's own concealed effect, and who knows it lands in
``arpgMods.secretPassages``, merged into any arpgMods already there), the
``nativeNature`` shapes and surfaces on the regions and vehicle fields on
the templates, the ``nativePopulations`` written as the game's own
``npcTemplates`` (one per kind, their home regions resolved to the ids the
build assigned, and each home's members written in as npc entities at their
chosen cells — the same by-name carry, for the same reason), the spec's
``arpgMods`` when
another extension filled one (lights), and the void-zone slabs hardened to
walkability 0 (the spec carried them as passable so the builder's flat walk
could cross them). Then it re-zips, so the shipped folder and zip both carry
the finished scenario. (The builder is never edited.)
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
    # each walled region records the door kind the generator chose for it
    # (the builder drops unknown region keys, so the kinds came by name),
    # then every doorway left open gets its door object — after the seal, so
    # no door lands on a fiction opening stripped from a storey's border
    from . import native as native_mod
    if spec.get("nativeDoors"):
        by_name = {r.get("name"): r for r in scn.get("regions", [])}
        for name, kind in spec["nativeDoors"].items():
            area = by_name.get(name)
            if area is not None:
                area["door"] = kind
    native_mod.hang_doors(scn)
    # then the locks and keys, onto the hung doors: the rooms the generator
    # locked get every door of theirs locked, their key handed to the chosen
    # holders, and the theft buildings their flag — all by name, since the
    # ids only exist now
    locks = spec.get("nativeLocks") or {}
    if locks.get("locks") or locks.get("theft"):
        by_name = {r.get("name"): r for r in scn.get("regions", [])}
        people = {e.get("name"): e for e in scn.get("entities", [])
                  if e.get("type") in ("npc", "player")}
        ids = native_mod.Ids(scn)
        for entry in locks.get("locks") or []:
            room = by_name.get(entry.get("room"))
            if room is None or not native_mod.region_doors(scn, room):
                continue
            native_mod.set_locked(scn, room, True, ids)
            for holder in entry.get("holders") or []:
                person = people.get(holder)
                if person is not None:
                    native_mod.give_key(scn, room, person, ids)
        for name in locks.get("theft") or []:
            area = by_name.get(name)
            if area is not None:
                area["takingIsTheft"] = True
    # then the secret doors, onto the same hung doors: every doorway the
    # generator hid gets each of its door objects the concealed effect and a
    # passages entry saying who knows it (once per door object — a wider
    # doorway has more than one), merged into the arpgMods the scenario may
    # already carry and into the spec's, so the shipped-scenario check still
    # compares like for like
    secrets = spec.get("nativeSecrets") or []
    if secrets:
        by_name = {r.get("name"): r for r in scn.get("regions", [])}
        ids = native_mod.Ids(scn)
        for entry in secrets:
            first = by_name.get((entry.get("between") or [None])[0])
            second = by_name.get((entry.get("between") or [None, None])[1])
            if first is None or second is None:
                continue
            known = list(entry.get("knownBy") or [])
            for door in native_mod.doors_between(scn, first, second):
                native_mod.set_secret(scn, door, ids)
                native_mod.add_secret_data(scn, door, known)
                spec.setdefault("arpgMods", {}).setdefault(
                    "secretPassages", {}).setdefault(
                    "passages", {})[door["id"]] = {"knownBy": known}
    # the same by-name trick for the nature pass: the shapes and surfaces on
    # the regions, the vehicle fields on the object templates — surface only
    # on unwalled regions, which is the only place the game keeps it
    nature = spec.get("nativeNature") or {}
    if nature.get("shape") or nature.get("water") or nature.get("vehicles"):
        by_name = {r.get("name"): r for r in scn.get("regions", [])}
        for name in nature.get("shape") or []:
            area = by_name.get(name)
            if area is not None:
                area["shape"] = "natural"
        for name in nature.get("water") or []:
            area = by_name.get(name)
            if area is not None and not area.get("wall"):
                area["surface"] = "water"
        templates = {t.get("name"): t for t in scn.get("objectTemplates", [])}
        for name, fields in (nature.get("vehicles") or {}).items():
            t = templates.get(name)
            if t is not None:
                t.update(fields)
    # the native populations become the game's own npcTemplates: one per kind
    # the generator chose, its homes resolved to the built regions' ids (a
    # home whose region the build dropped goes with it; the checks report it).
    # The members the spec placed start in the scenario too: one npc entity
    # per member at its cell, numbered per template across the world — the
    # game counts them toward their home's count and tops it up after deaths,
    # so the world opens with its creatures already there
    if spec.get("nativePopulations"):
        by_name = {r.get("name"): r for r in scn.get("regions", [])}
        ids = native_mod.Ids(scn)
        for p in spec["nativePopulations"]:
            homes = [{"regionId": by_name[h["region"]]["id"], "count": h["count"]}
                     for h in p.get("homes") or [] if h.get("region") in by_name]
            if not homes:
                continue
            tpl_id = ids("ntpl")
            scn.setdefault("npcTemplates", []).append({
                "id": tpl_id, "name": p.get("name"),
                "description": p.get("description", ""),
                "physicalDescription": p.get("physicalDescription", ""),
                "animationId": p.get("animationId"), "gender": p.get("gender"),
                "stance": p.get("stance"), "level": p.get("level", 1),
                "money": p.get("money", 0),
                "lootPoolIds": list(p.get("lootPoolIds") or []),
                "homes": homes})
            n = 0
            for h in p.get("homes") or []:
                area = by_name.get(h.get("region"))
                for cell in h.get("members") or []:
                    n += 1
                    scn.setdefault("entities", []).append({
                        "id": ids("npc"), "type": "npc",
                        "name": f"{p.get('name')} {n}",
                        "description": p.get("description", ""),
                        "gender": p.get("gender"),
                        "pos": list(cell), "size": [1, 1],
                        "hp": 100, "maxHp": 100,
                        "animationId": p.get("animationId"),
                        "physicalDescription": p.get("physicalDescription", ""),
                        "level": p.get("level", 1), "stance": p.get("stance"),
                        "npcHome": area["id"], "inventory": [],
                        "statusEffects": [], "templateId": tpl_id})
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
