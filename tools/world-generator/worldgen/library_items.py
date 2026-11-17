"""The item library as P2's item menu.

With the item library on, the items call picks from a menu instead of
inventing every item: ``menu`` filters the library to the world's band and
genre, ``menu_lines`` renders it for the prompt, and ``expand`` turns the
model's JSON reply into full item templates plus cleaned loot pools. A menu
pick or a recoloured variant carries a ``library`` link (item id, look key,
tint) beside the usual fields: like an object template's ``sprite`` it lives
on the plan only — ``library_art.attach_item_art`` reads it from plan.json
and ships the image, and the scenario's ``itemTemplates`` never see it. New
plot items are the model's own and stay as they came, with ``plot`` set.
"""
import json
import os
import random
import re

from .item_library import (description_for, expand_bands, looks_for_band,
                           name_for)
from .library import LIB_DIR

ITEM_SPRITES_DIR = os.path.join(LIB_DIR, "item-sprites")

# how each tint recolours a sprite: "hue" is the target hue in degrees on the
# colour wheel, "sat" and "val" scale the coloured pixels' saturation and
# value (library_art.recolour applies them). Brown and black are darkening
# mixes rather than plain hue swaps.
TINTS = {
    "red": {"hue": 0},
    "orange": {"hue": 30},
    "yellow": {"hue": 60},
    "green": {"hue": 120},
    "teal": {"hue": 180},
    "blue": {"hue": 240},
    "purple": {"hue": 285},
    "pink": {"hue": 330},
    "brown": {"hue": 30, "sat": 0.8, "val": 0.65},
    "black": {"sat": 0.25, "val": 0.35},
}

# price 1-6, the library's scale, to value on the game's (1 coin is about a
# US dollar; the game's own everyday wares run 15-50)
VALUE = {1: 2, 2: 8, 3: 30, 4: 120, 5: 500, 6: 2500}
JITTER = 0.15             # the seeded wiggle either way on the table's value


def value_for(price, seed_key):
    """The table's value for ``price`` with +-15% seeded jitter, rounded and
    never below 1: the same key always gives the same number."""
    base = VALUE.get(price, VALUE[1])
    rng = random.Random(seed_key)
    return max(1, round(base * rng.uniform(1 - JITTER, 1 + JITTER)))


# ------------------------------------------------------------------ menu

def _sprites_index(sprites_dir):
    path = os.path.join(sprites_dir or ITEM_SPRITES_DIR, "index.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def menu(items, band, genre, sprites_dir=None):
    """The menu entries for ``band``: every library item whose bands include
    it, keeping only those whose ``onlyGenres`` (when set) has a word in
    ``genre``. Each entry is {"name", "item", "look", "tintable"} with the
    name capitalised for the band and "tintable" from the item-sprites index
    (false when the sprite has no entry). Two items sharing a band name keep
    the first by id, quietly."""
    index = _sprites_index(sprites_dir)
    g = (genre or "").lower()
    entries, seen = [], set()
    for iid in sorted(items, key=str):
        it = items[iid]
        if not isinstance(it, dict) or "_load_error" in it:
            continue
        if not isinstance(it.get("id"), str):
            continue
        if band not in expand_bands(it.get("bands")):
            continue
        words = it.get("onlyGenres") or []
        if words and not any(re.search(r"\b" + re.escape(str(w).lower()) + r"\b", g)
                             for w in words):
            continue
        look = looks_for_band(it, band)
        if look is None:
            continue
        name = name_for(it, band)
        name = name[:1].upper() + name[1:]
        if name.casefold() in seen:
            continue
        seen.add(name.casefold())
        art = index.get(f"{it['id']}.{look['key']}") or {}
        entries.append({"name": name, "item": it, "look": look,
                        "tintable": bool(art.get("tintable"))})
    return entries


def menu_lines(entries):
    """One prompt line per entry: name | category | price, with a recolour
    mark on the tintable ones."""
    return [f"- {e['name']} | {e['item']['category']} | price {e['item']['price']}"
            + (" | recolourable" if e["tintable"] else "")
            for e in entries]


# ------------------------------------------------------------------ expand

def _library_template(entry, band, seed):
    it, look = entry["item"], entry["look"]
    return {
        "name": entry["name"],
        "type": it.get("type", "misc"),
        "quality": it.get("quality", "common"),
        "value": value_for(it.get("price", 1), f"{seed}|{entry['name']}"),
        "description": description_for(it, band),
        "physicalDescription": f"{look['physical']}, white background",
        "library": {"item": it["id"], "look": look["key"], "tint": None},
    }


def _variant_template(entry, variant, band, seed):
    it, look = entry["item"], entry["look"]
    described = variant["description"] or description_for(it, band)
    return {
        "name": variant["name"],
        "type": it.get("type", "misc"),
        "quality": it.get("quality", "common"),
        "value": value_for(it.get("price", 1), f"{seed}|{variant['name']}"),
        "description": described,
        "physicalDescription": f"{variant['tint']}-coloured "
                               f"{look['physical']}, white background",
        "library": {"item": it["id"], "look": look["key"], "tint": variant["tint"]},
    }


def expand(reply, entries, band, seed, log):
    """(items, pools) from the reply the library-mode items call made.

    The reply is {"lootPools": {pool: {"items": [names], "weights": {}}},
    "variants": [{"from", "name", "tint", "description"}], "items": [new
    plot items]}. Every pool entry resolves to a plot item, a variant or a
    menu name (in that order, case-insensitive); anything else, and a pool
    left empty, is dropped with a log line. Each distinct library entry or
    variant a pool uses becomes one template; plot items are kept as given
    (the same field checks ``check_p2_items`` makes) even when no pool names
    them, since P5 and the quests use them. Templates come back sorted by
    name, and the pools keep only the resolvable entries and their weights.
    """
    # phases imports the world's modules broadly; take it lazily so this
    # module can sit under it without a cycle
    from .phases import _pool_entries, check_p2_items
    reply = reply if isinstance(reply, dict) else {}
    by_key = {e["name"].casefold(): e for e in entries}

    # -- the new plot items: P2's own field checks, one item at a time
    plot = []
    for it in reply.get("items") or []:
        if not isinstance(it, dict):
            continue
        errs = [e.replace("items[0].", "")
                for e in check_p2_items({"items": [it]})
                if not e.startswith(("lootPools", "loot pool"))]
        if errs:
            log.append(("items", f"item {it.get('name')!r} dropped: {errs[0]}"))
            continue
        it.pop("library", None)          # a new item is never a library item
        it["plot"] = True
        plot.append(it)
    plot_by_key = {it["name"].casefold(): it for it in plot}

    # -- the variants: a recoloured menu item under a new name
    variants = {}
    for v in reply.get("variants") or []:
        if not isinstance(v, dict):
            continue
        name, frm, tint = v.get("name"), v.get("from"), v.get("tint")
        if not isinstance(name, str) or not name.strip():
            log.append(("items", f"variant {name!r} dropped: it needs a name"))
            continue
        base = by_key.get(frm.casefold()) if isinstance(frm, str) else None
        if base is None:
            log.append(("items", f"variant {name!r} dropped: "
                                 f"{frm!r} is not on the menu"))
            continue
        if tint not in TINTS:
            log.append(("items", f"variant {name!r} dropped: tint {tint!r} is not "
                                 f"one of {sorted(TINTS)}"))
            continue
        if name.casefold() in by_key or name.casefold() in plot_by_key \
                or name.casefold() in variants:
            log.append(("items", f"variant {name!r} dropped: the name is already used"))
            continue
        described = v.get("description")
        variants[name.casefold()] = {
            "name": name, "entry": base, "tint": tint,
            "description": described if isinstance(described, str) and described.strip()
            else "",
        }

    # -- the pools: every entry must be a plot item, a variant or a menu name
    templates = {}          # casefold key -> template, built the first time used
    pools = {}
    for (pname, p) in _pool_entries(reply.get("lootPools")):
        if not isinstance(pname, str) or not pname.strip():
            continue
        raw = p.get("items", []) if isinstance(p, dict) else []
        keep = []
        for n in (raw if isinstance(raw, list) else []):
            key = n.casefold() if isinstance(n, str) else None
            if key in plot_by_key:
                keep.append(plot_by_key[key]["name"])
            elif key in variants:
                if key not in templates:
                    templates[key] = _variant_template(
                        variants[key]["entry"], variants[key], band, seed)
                keep.append(templates[key]["name"])
            elif key in by_key:
                if key not in templates:
                    templates[key] = _library_template(by_key[key], band, seed)
                keep.append(templates[key]["name"])
            else:
                log.append(("items", f"{pname}: {n} is not on the menu"))
        if not keep:
            log.append(("items", f"{pname}: dropped, no menu, variant or plot items left"))
            continue
        resolved = {n.casefold(): n for n in keep}
        weights = {}
        raw_weights = p.get("weights") if isinstance(p, dict) else None
        if isinstance(raw_weights, dict):
            for k, w in raw_weights.items():
                if isinstance(k, str) and k.casefold() in resolved \
                        and not isinstance(w, bool) \
                        and isinstance(w, (int, float)) and w > 0:
                    weights[resolved[k.casefold()]] = w
        pools[pname] = {"items": keep, "weights": weights}

    items = plot + list(templates.values())
    items.sort(key=lambda t: t["name"])
    return items, pools
