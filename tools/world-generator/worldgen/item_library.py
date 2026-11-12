"""The item library: carried items (game ``itemTemplates``), one JSON file per
group under ``library/items/``. The format is the item library brief's; the
bands are the room library's four. An item has ``looks`` and one look (one
image) can cover several bands, which is the one way items differ from room
objects.

  load(items_dir)   -> {id: item}, each item carrying its file in "_file"
  check(items)      -> [error, ...], plain sentences starting with the item id
  coverage(items)   -> per band: items, looks, per-category counts
  looks_for_band / name_for / description_for -> the band's look and text
"""
import json
import os
import re

from .library import LIB_DIR

ITEMS_DIR = os.path.join(LIB_DIR, "items")
BANDS = ("medieval", "industrial", "modern", "scifi")   # the room library's four
CATEGORIES = ("food", "drink", "medicine", "tool", "weapon", "armour", "clothing",
              "jewellery", "document", "key", "money", "light", "container",
              "material", "trinket", "tech", "magic")
TYPES = ("misc", "consumable", "material", "wieldable", "head", "face", "torso",
         "innerTorso", "pants", "gloves", "boots", "necklace", "ring")
QUALITIES = ("common", "uncommon", "rare", "epic", "legendary")
GROUPS = ("food_drink", "medicine", "tools", "weapons_armour", "clothing",
          "jewellery_trinkets", "documents_keys_money", "light_containers",
          "materials", "tech", "magic")
SOURCES = ("harvest", "authored")
ID_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")     # <category>.<name>, one dot
BANNED_PHYSICAL = ("icon", "background")            # "white background" included
MAX_PHYSICAL = 300


def expand_bands(bands):
    """["*"] -> every band; anything else stays as-is (a broken value -> [])."""
    return list(BANDS) if bands == ["*"] else list(bands or [])


def load(items_dir=None):
    """Every ``library/items/*.json`` as {id: item}, sorted by file name. A
    missing folder is an empty library. A file that isn't valid JSON becomes
    a "!<file>" entry carrying ``_load_error``, which ``check`` reports. The second item with an id keeps a
    ``_dupe_files`` list on the first, which ``check`` reports."""
    folder = items_dir or ITEMS_DIR
    items = {}
    if not os.path.isdir(folder):
        return items
    for f in sorted(os.path.join(folder, n) for n in os.listdir(folder)
                    if n.endswith(".json")):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as e:
            # an unreadable file must fail the check, never vanish from it
            name = os.path.basename(f)
            items["!" + name] = {"_file": name, "_load_error": str(e)}
            continue
        for it in ((data or {}).get("items") or []):
            if not isinstance(it, dict):
                continue
            iid = it.get("id")
            it["_file"] = os.path.basename(f)
            if iid in items:
                first = items[iid]
                dupes = first.setdefault("_dupe_files", [first.get("_file")])
                dupes.append(it["_file"])
                continue
            items[iid] = it
    return items


# ------------------------------------------------------------------ checks

def _bands_ok(bands):
    return bands == ["*"] or (isinstance(bands, list) and bands
                              and all(b in BANDS for b in bands)
                              and len(set(bands)) == len(bands))


def _check_band_text(iid, what, mapping, item_bands, err):
    if not isinstance(mapping, dict) or not mapping:
        err(f"{what} must be an object with \"*\" or every band the item has")
        return
    for k in mapping:
        if k != "*" and k not in BANDS:
            err(f"{what} has unknown band {k!r}")
    missing = [b for b in item_bands if b not in mapping]
    if missing and "*" not in mapping:
        err(f"{what} needs \"*\" or an entry for every band (missing {' '.join(missing)})")
    for k, v in mapping.items():
        if not isinstance(v, str) or not v.strip():
            err(f"{what}.{k} must be a non-empty string")


def _check_item(iid, it, errors):
    def err(msg):
        errors.append(f"{iid}: {msg}")

    if "_load_error" in it:
        errors.append(f"{it['_file']}: can't be read ({it['_load_error']})")
        return
    files = it.get("_dupe_files")
    if files:
        if len(set(files)) == 1:
            err(f"id appears twice in {files[0]}")
        else:
            err(f"id appears in {' and '.join(sorted(set(files)))}")
    if not isinstance(iid, str) or not ID_RE.match(iid):
        err("id must be <category>.<name>, lower case, letters, digits and "
            "underscores, one dot")
    cat = it.get("category")
    if cat not in CATEGORIES:
        err(f"unknown category {cat!r}")
    elif isinstance(iid, str) and "." in iid and not iid.startswith(cat + "."):
        err(f"id must start with its category {cat!r}")
    if it.get("type") not in TYPES:
        err(f"unknown type {it.get('type')!r}")
    if it.get("quality") not in QUALITIES:
        err(f"unknown quality {it.get('quality')!r}")
    price = it.get("price")
    if not isinstance(price, int) or isinstance(price, bool) or not 1 <= price <= 6:
        err("price must be 1-6")
    bands = it.get("bands")
    item_bands_ok = _bands_ok(bands)
    if not item_bands_ok:
        err(f"bands must be [\"*\"] or a list of {', '.join(BANDS)}")
    item_bands = expand_bands(bands)
    _check_band_text(iid, "names", it.get("names"), item_bands, err)
    _check_band_text(iid, "description", it.get("description"), item_bands, err)
    looks = it.get("looks")
    if not isinstance(looks, list) or not looks:
        err("looks must be a list with at least one look")
        return
    seen = {}
    for look in looks:
        key = look.get("key") if isinstance(look, dict) else None
        if not isinstance(key, str) or not key:
            err(f"look {key!r} needs a short key")
            key = repr(key)
        elif key in seen:
            err(f"look key {key!r} repeats")
        else:
            seen[key] = look
        lbands = look.get("bands") if isinstance(look, dict) else None
        if not _bands_ok(lbands):
            err(f"look {key}: bands must be [\"*\"] or a list of {', '.join(BANDS)}")
            continue
        covered = expand_bands(lbands)
        for b in ([b for b in covered if item_bands_ok and b not in item_bands]):
            err(f"look {key} covers band {b} which the item doesn't have")
        physical = look.get("physical")
        if not isinstance(physical, str) or not physical.strip():
            err(f"look {key} needs a physical sentence")
        else:
            if len(physical) >= MAX_PHYSICAL:
                err(f"look {key} physical is {len(physical)} characters "
                    f"(under {MAX_PHYSICAL})")
            for word in BANNED_PHYSICAL:
                if re.search(r"\b" + word + r"\b", physical, re.I):
                    err(f"look {key} physical mentions {word!r} "
                        "(the object alone, no background)")
    if item_bands_ok:
        for band in item_bands:
            covering = [k for k, look in seen.items()
                        if band in expand_bands(look.get("bands"))]
            if not covering:
                err(f"no look covers band {band}")
            elif len(covering) > 1:
                names = ", ".join(covering[:-1]) + " and " + covering[-1]
                err(f"looks {names} all cover band {band}")
    srcs = it.get("sources")
    if not isinstance(srcs, list) or not srcs or any(s not in SOURCES for s in srcs):
        err(f"sources must list {' and/or '.join(SOURCES)}")


def check(items):
    """Every rule of the format the code can check, as plain sentences."""
    errors = []
    for iid, it in sorted(items.items(), key=lambda kv: str(kv[0])):
        if isinstance(it, dict):
            _check_item(iid, it, errors)
        else:
            errors.append(f"{iid}: an item must be a JSON object")
    return errors


# ------------------------------------------------------------------ use

def looks_for_band(item, band):
    """The one look that covers ``band``, or None."""
    for look in item.get("looks") or []:
        if isinstance(look, dict) and band in expand_bands(look.get("bands")):
            return look
    return None


def name_for(item, band):
    names = item.get("names") or {}
    return names.get(band) or names.get("*") or item.get("id", "")


def description_for(item, band):
    texts = item.get("description") or {}
    return texts.get(band) or texts.get("*") or ""


# ------------------------------------------------------------------ coverage

def coverage(items):
    """Per band: how many items and looks serve it and the items per category,
    plus the looks that cover two or more bands (the shared images)."""
    bands = {b: {"items": 0, "looks": 0, "categories": {}} for b in BANDS}
    shared = total_looks = 0
    for it in items.values():
        for b in expand_bands(it.get("bands")):
            bands[b]["items"] += 1
            cat = it.get("category")
            bands[b]["categories"][cat] = bands[b]["categories"].get(cat, 0) + 1
        for look in it.get("looks") or []:
            covered = expand_bands(look.get("bands"))
            total_looks += 1
            if len(covered) >= 2:
                shared += 1
            for b in covered:
                if b in bands:
                    bands[b]["looks"] += 1
    return {"items": len(items), "looks": total_looks, "shared_looks": shared,
            "bands": bands}


def report(items, out=print):
    """The coverage table for ``python -m worldgen library items --coverage``."""
    c = coverage(items)
    out(f"  {c['items']} items, {c['looks']} looks, {c['shared_looks']} covering "
        f"two or more bands")
    for b in BANDS:
        d = c["bands"][b]
        cats = ", ".join(f"{k} {v}" for k, v in
                         sorted(d["categories"].items(), key=lambda kv: (-kv[1], str(kv[0]))))
        out(f"  {b}: {d['items']} items, {d['looks']} looks" + (f" ({cats})" if cats else ""))
