#!/usr/bin/env python3
"""Fill a scenario copy's missing images from existing ones (test helper).

Anywhere RPG 1.0's New Game screen keeps "Begin Adventure" disabled until every
image the scenario needs exists, and each missing image takes minutes on
ComfyUI. This tool copies a scenario (zip or folder) and fills each missing
image with a byte copy of an existing image of the same kind (sprite, portrait,
item or perk), chosen by word overlap between the owner texts.

Test copies only: the input and the donors are never modified, and the output
is refused inside the presets folder or the Steam install.
"""

import argparse
import json
import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass

DEFAULT_PRESETS = r"E:\Misc Projects\Anywhere RPG builds\1.0-build26557354\resources\presets"

STOPWORDS = {
    "the", "and", "with", "for", "from", "that", "this", "his", "her",
    "their", "its", "are", "was", "has", "have", "into", "who", "which",
}

_WORD_SPLIT = re.compile(r"[^a-z]+")


class UsageError(Exception):
    """Bad input or a refused output; the message is printed and the tool exits 2."""


@dataclass(frozen=True)
class Owner:
    id: str
    kind: str          # sprite | portrait | item | perk
    name: str
    name_words: frozenset
    all_words: frozenset


@dataclass
class Donor:
    owner: Owner
    source: int        # 0 = the scenario's own media, then each donor/preset folder in order
    label: str         # "scenario", "donor <folder>" or "preset <folder>"
    image_rel: str     # media/<id>/<id>-<kind>.webp inside the source
    read: object       # callable () -> bytes
    used: bool = False


def _s(value):
    return value if isinstance(value, str) else ""


def _clean_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value)
    return text or None


def _word_set(*texts):
    words = set()
    for text in texts:
        for word in _WORD_SPLIT.split(text.lower()):
            if len(word) >= 3 and word not in STOPWORDS:
                words.add(word)
    return words


def _make_owner(obj, kind, owner_id=None):
    if not isinstance(obj, dict):
        return None
    oid = owner_id if owner_id is not None else _clean_id(obj.get("id"))
    if oid is None:
        return None
    name = _s(obj.get("name"))
    texts = [_s(obj.get("description")), _s(obj.get("physicalDescription")),
             _s(obj.get("gender"))]
    npc_template = obj.get("npcTemplate")
    if isinstance(npc_template, dict):
        if not name:
            name = _s(npc_template.get("name"))
        texts += [_s(npc_template.get("description")),
                  _s(npc_template.get("physicalDescription"))]
    name_words = _word_set(name)
    all_words = name_words | _word_set(*texts)
    return Owner(oid, kind, name, frozenset(name_words), frozenset(all_words))


def collect_owners(data):
    """Every owner New Game checks, in discovery order, deduped by (id, kind)."""
    if not isinstance(data, dict):
        return []
    owners = []
    seen = set()

    def add(owner):
        if owner is None:
            return
        key = (owner.id, owner.kind)
        if key not in seen:
            seen.add(key)
            owners.append(owner)

    def items(key):
        value = data.get(key)
        return value if isinstance(value, list) else []

    for obj in items("objectTemplates"):
        if isinstance(obj, dict) and not obj.get("sheet") and not obj.get("door"):
            add(_make_owner(obj, "sprite"))

    for entity in items("entities"):
        if not isinstance(entity, dict) or entity.get("type") not in ("npc", "player"):
            continue
        npc_template = entity.get("npcTemplate")
        template_id = (_clean_id(npc_template.get("id"))
                       if isinstance(npc_template, dict) else None)
        add(_make_owner(entity, "portrait", owner_id=template_id))

    for key in ("npcTemplates", "hostileNpcTemplates"):
        for template in items(key):
            add(_make_owner(template, "portrait"))

    for item in items("itemTemplates"):
        if not isinstance(item, dict):
            continue
        add(_make_owner(item, "item"))
        perks = item.get("perks")
        if isinstance(perks, list):
            for perk in perks:
                add(_make_owner(perk, "perk"))

    def walk_perks(node):
        add(_make_owner(node, "perk"))
        children = node.get("children") if isinstance(node, dict) else None
        if isinstance(children, list):
            for child in children:
                walk_perks(child)

    for tree in items("perkTrees"):
        if isinstance(tree, dict):
            walk_perks(tree.get("root"))

    return owners


def _load_json_scenario(raw, source):
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise UsageError(f"{source}: scenario.json is not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise UsageError(f"{source}: scenario.json is not a JSON object")
    return data


class FolderScenario:
    form = "folder"

    def __init__(self, path):
        self.path = path
        scenario_json = os.path.join(path, "scenario.json")
        if not os.path.isfile(scenario_json):
            raise UsageError(f"{path} has no scenario.json")
        with open(scenario_json, "rb") as f:
            self.data = _load_json_scenario(f.read(), path)
        self.owners = collect_owners(self.data)

    def close(self):
        pass

    def has_image(self, owner_id, kind):
        path = os.path.join(self.path, "media", owner_id, f"{owner_id}-{kind}.webp")
        return os.path.isfile(path) and os.path.getsize(path) > 0

    def read_image(self, owner_id, kind):
        path = os.path.join(self.path, "media", owner_id, f"{owner_id}-{kind}.webp")
        with open(path, "rb") as f:
            return f.read()


class ZipScenario:
    form = "zip"

    def __init__(self, path):
        self.path = path
        try:
            self._zip = zipfile.ZipFile(path, "r")
        except (OSError, zipfile.BadZipFile) as exc:
            raise UsageError(f"cannot read zip {path}: {exc}")
        try:
            try:
                raw = self._zip.read("scenario.json")
            except KeyError:
                raise UsageError(f"{path} has no scenario.json at its root")
            self.data = _load_json_scenario(raw, path)
            self.owners = collect_owners(self.data)
        except Exception:
            self._zip.close()
            raise

    def close(self):
        self._zip.close()

    def has_image(self, owner_id, kind):
        name = f"media/{owner_id}/{owner_id}-{kind}.webp"
        info = self._zip.getinfo(name) if name in self._zip.namelist() else None
        return info is not None and info.file_size > 0

    def read_image(self, owner_id, kind):
        return self._zip.read(f"media/{owner_id}/{owner_id}-{kind}.webp")


def _refuse_bad_output(in_path, out_path, presets_dir):
    if os.path.exists(out_path):
        raise UsageError(f"output already exists: {out_path}")
    out_r = os.path.normcase(os.path.realpath(out_path))
    in_r = os.path.normcase(os.path.realpath(in_path))
    if out_r == in_r or out_r.startswith(in_r + os.sep):
        raise UsageError(f"output must not be the input or inside it: {out_path}")
    if presets_dir:
        presets_r = os.path.normcase(os.path.realpath(presets_dir))
        if out_r == presets_r or out_r.startswith(presets_r + os.sep):
            raise UsageError(f"output must not be inside the presets folder: {out_path}")
    if any(part.lower() == "steamapps" for part in out_r.split(os.sep)):
        raise UsageError(f"output must not be inside a steamapps folder: {out_path}")


def _load_donor_folder(path):
    if not os.path.isdir(path):
        return None
    if not os.path.isfile(os.path.join(path, "scenario.json")):
        return None
    if not os.path.isdir(os.path.join(path, "media")):
        return None
    try:
        return FolderScenario(path)
    except UsageError:
        return None


def _donors_from(scenario, source, label):
    donors = []
    for owner in scenario.owners:
        if not scenario.has_image(owner.id, owner.kind):
            continue
        donors.append(Donor(
            owner=owner,
            source=source,
            label=label,
            image_rel=f"media/{owner.id}/{owner.id}-{owner.kind}.webp",
            read=lambda sc=scenario, o=owner: sc.read_image(o.id, o.kind),
        ))
    return donors


def _build_donors(scenario, donor_dirs, presets_dir):
    donors = list(_donors_from(scenario, 0, "scenario"))
    source = 0
    for path in donor_dirs:
        folder = _load_donor_folder(path)
        if folder is None:
            continue
        source += 1
        name = os.path.basename(os.path.normpath(path))
        donors += _donors_from(folder, source, f"donor {name}")
    if presets_dir and os.path.isdir(presets_dir):
        for name in sorted(os.listdir(presets_dir)):
            folder = _load_donor_folder(os.path.join(presets_dir, name))
            if folder is None:
                continue
            source += 1
            donors += _donors_from(folder, source, f"preset {name}")
    return donors


def _word_score(target, donor):
    score = 0
    for word in target.all_words & donor.all_words:
        target_weight = 2 if word in target.name_words else 1
        donor_weight = 2 if word in donor.name_words else 1
        score += target_weight * donor_weight
    return score


def _choose_donor(target, candidates):
    best = None
    best_key = None
    for donor in candidates:
        score = _word_score(target, donor.owner)
        key = (-score, 1 if donor.used else 0, donor.source, donor.image_rel)
        if best is None or key < best_key:
            best, best_key = donor, key
    if best is None:
        return None, 0
    return best, -best_key[0]


def _write_folder_output(scenario, out_path, fills):
    shutil.copytree(scenario.path, out_path)
    for target, donor in fills:
        folder = os.path.join(out_path, "media", target.id)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, f"{target.id}-{target.kind}.webp"), "wb") as f:
            f.write(donor.read())


def _write_zip_output(scenario, out_path, fills):
    filled = {f"media/{t.id}/{t.id}-{t.kind}.webp": d.read() for t, d in fills}
    with zipfile.ZipFile(scenario.path, "r") as zin:
        member_names = {info.filename for info in zin.infolist()}
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                data = filled.get(info.filename)
                if data is None:
                    data = zin.read(info.filename)
                zout.writestr(info, data)
            for name in sorted(set(filled) - member_names):
                zout.writestr(name, filled[name])


def run(args):
    in_path = args.input
    is_zip = in_path.lower().endswith(".zip")
    if is_zip:
        if not os.path.isfile(in_path):
            raise UsageError(f"input zip not found: {in_path}")
    elif not os.path.isdir(in_path):
        raise UsageError(f"input not found: {in_path}")
    _refuse_bad_output(in_path, args.output, args.presets)
    scenario = ZipScenario(in_path) if is_zip else FolderScenario(in_path)
    try:
        missing = [o for o in scenario.owners if not scenario.has_image(o.id, o.kind)]
        by_kind = {}
        for donor in _build_donors(scenario, args.donor, args.presets):
            by_kind.setdefault(donor.owner.kind, []).append(donor)
        fills = []
        unfilled = 0
        for target in missing:
            donor, score = _choose_donor(target, by_kind.get(target.kind, []))
            if donor is None:
                unfilled += 1
                print(f"UNFILLED {target.kind} {target.id} ({target.name}): "
                      f"no {target.kind} images anywhere")
                continue
            donor.used = True
            fills.append((target, donor))
            print(f"filled {target.kind} {target.id} ({target.name}) <- {donor.label}: "
                  f"{donor.owner.id} ({donor.owner.name}) [score {score}]")
        if not args.dry_run:
            if is_zip:
                _write_zip_output(scenario, args.output, fills)
            else:
                _write_folder_output(scenario, args.output, fills)
        print(f"{len(missing)} missing, {len(fills)} filled, {unfilled} unfilled "
              f"-> {args.output}")
        return 1 if unfilled else 0
    finally:
        scenario.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="fill_test_images.py",
        description="Copy a scenario and fill its missing images from existing "
                    "ones (test helper).")
    parser.add_argument("input", help="scenario .zip (scenario.json at the zip root) "
                                      "or scenario folder")
    parser.add_argument("-o", "--output", required=True,
                        help="copy to write (same form as the input; must not exist)")
    parser.add_argument("--donor", action="append", default=[], metavar="DIR",
                        help="scenario folder to copy images from (repeatable)")
    parser.add_argument("--presets", default=DEFAULT_PRESETS, metavar="DIR",
                        help="1.0 presets folder (default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan without writing anything")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except UsageError as exc:
        print(f"fill_test_images: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
