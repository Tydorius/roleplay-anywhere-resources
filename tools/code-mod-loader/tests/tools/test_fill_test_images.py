"""Tests for fill_test_images.py.

Every test builds its scenarios in a TemporaryDirectory and points --presets at
a temp folder, so the real 1.0 presets are never read.
"""

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fill_test_images as fti


def run_tool(args):
    """Run the tool in-process; return (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = fti.main(list(args))
    return code, out.getvalue(), err.getvalue()


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def write_image(root, owner_id, kind, data=b"FAKE-WEBP"):
    folder = os.path.join(root, "media", owner_id)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, f"{owner_id}-{kind}.webp"), "wb") as f:
        f.write(data)


def make_scenario(root, data, images=()):
    """Create a scenario folder: scenario.json plus media images.

    images: iterable of (owner_id, kind, bytes); bytes b"" writes an empty file.
    """
    os.makedirs(root, exist_ok=True)
    os.makedirs(os.path.join(root, "media"), exist_ok=True)
    write_json(os.path.join(root, "scenario.json"), data)
    for owner_id, kind, blob in images:
        write_image(root, owner_id, kind, blob)
    return root


def make_zip(path, data, members):
    """Create a scenario zip: scenario.json at the root plus members."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("scenario.json", json.dumps(data))
        for name, blob in members:
            z.writestr(name, blob)
    return path


def hash_tree(root):
    """relpath -> sha256 for every file under root."""
    result = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            with open(path, "rb") as f:
                result[os.path.relpath(path, root)] = hashlib.sha256(f.read()).hexdigest()
    return result


class FillTestImagesTests(unittest.TestCase):
    def tempdir(self):
        return tempfile.TemporaryDirectory()

    def test_missing_list_follows_the_rules(self):
        with self.tempdir() as tmp:
            data = {
                "objectTemplates": [
                    {"id": "obj_sheet", "name": "Big Sheet", "sheet": {"frames": 4}},
                    {"id": "obj_door", "name": "Door", "door": {"locked": True}},
                    {"id": "obj_ok", "name": "Barrel"},
                    {"id": "obj_missing", "name": "Crate"},
                    {"id": "obj_variant", "name": "Torch"},
                ],
                "entities": [
                    {"id": "ent_1", "type": "npc", "name": "Entity One",
                     "npcTemplate": {"id": "tpl_1", "name": "Template One"}},
                    {"id": "ent_2", "type": "player", "name": "Entity Two"},
                    {"id": "ent_3", "type": "zombie", "name": "Entity Three"},
                ],
                "npcTemplates": [
                    {"id": "tpl_2", "name": "Villager"},
                    {"id": "tpl_empty", "name": "Empty Portrait"},
                    {"id": "tpl_1", "name": "Duplicate of the entity-owned template"},
                ],
                "hostileNpcTemplates": [{"id": "host_1", "name": "Bandit"}],
                "itemTemplates": [
                    {"id": "item_1", "name": "Sword"},
                    {"id": "item_2", "name": "Shield",
                     "perks": [{"id": "perk_a", "name": "Block"}]},
                ],
                "perkTrees": [
                    {"root": {"id": "perk_r", "name": "Root Perk", "children": [
                        {"id": "perk_c1", "name": "Child One", "children": [
                            {"id": "perk_g1", "name": "Grandchild"}]},
                        {"id": "perk_c2", "name": "Child Two"},
                    ]}},
                ],
            }
            inp = make_scenario(os.path.join(tmp, "in"), data, [
                ("tpl_empty", "portrait", b""),
            ])
            # A sprite variant alone does not make the base sprite present.
            write_image(inp, "obj_variant", "sprite-normal", b"VARIANT")

            presets = os.path.join(tmp, "presets")  # empty: no donors anywhere
            os.makedirs(presets)
            out = os.path.join(tmp, "out")
            code, stdout, stderr = run_tool([inp, "-o", out, "--presets", presets])

            self.assertEqual(code, 1)
            self.assertEqual(stderr, "")
            reported = {}
            for line in stdout.splitlines():
                if not line.startswith("UNFILLED"):
                    continue
                parts = line.split()
                self.assertEqual(parts[0], "UNFILLED")
                self.assertTrue(line.endswith(f": no {parts[1]} images anywhere"), line)
                reported[parts[2]] = parts[1]
            expected = {
                "obj_ok": "sprite", "obj_missing": "sprite", "obj_variant": "sprite",
                "tpl_1": "portrait", "ent_2": "portrait", "tpl_2": "portrait",
                "tpl_empty": "portrait", "host_1": "portrait",
                "item_1": "item", "item_2": "item",
                "perk_a": "perk", "perk_r": "perk", "perk_c1": "perk",
                "perk_g1": "perk", "perk_c2": "perk",
            }
            self.assertEqual(reported, expected)
            # Sheet/door objects and other entity types are never checked.
            for silent in ("obj_sheet", "obj_door", "ent_3"):
                self.assertNotIn(silent, stdout)
            # The entity-owned npcTemplate id is reported once, not twice.
            self.assertEqual(stdout.count("tpl_1"), 1)
            self.assertIn(f"15 missing, 0 filled, 15 unfilled -> {out}", stdout)
            # The copy is still written when something is unfilled.
            self.assertTrue(os.path.isfile(os.path.join(out, "scenario.json")))

    def test_kinds_never_cross(self):
        with self.tempdir() as tmp:
            inp = make_scenario(os.path.join(tmp, "in"), {
                "npcTemplates": [
                    {"id": "p_x", "name": "Grey Wolf"},
                    {"id": "p_d", "name": "Some Person"},
                ],
                "itemTemplates": [{"id": "i_1", "name": "Thing",
                                   "perks": [{"id": "k_z", "name": "Power"}]}],
            }, [
                ("p_d", "portrait", b"PERSON"),
                ("i_1", "item", b"THING"),
            ])
            presets = os.path.join(tmp, "presets")  # no perk donors anywhere
            os.makedirs(presets)
            out = os.path.join(tmp, "out")
            code, stdout, _ = run_tool([inp, "-o", out, "--presets", presets])

            self.assertEqual(code, 1)
            self.assertIn("UNFILLED perk k_z (Power): no perk images anywhere", stdout)
            self.assertNotIn("filled perk", stdout)
            self.assertFalse(os.path.exists(os.path.join(out, "media", "k_z")))
            # The portrait is still filled from the only portrait donor.
            self.assertIn(
                "filled portrait p_x (Grey Wolf) <- scenario: p_d (Some Person) [score 0]",
                stdout)
            self.assertIn(f"2 missing, 1 filled, 1 unfilled -> {out}", stdout)

    def test_word_matching_picks_wolf_over_baker(self):
        with self.tempdir() as tmp:
            inp = make_scenario(os.path.join(tmp, "in"), {
                "npcTemplates": [{"id": "htpl_x", "name": "Grey Wolf",
                                  "description": "A grey wolf prowls the woods"}],
            })
            presets = os.path.join(tmp, "presets")
            make_scenario(os.path.join(presets, "thornbury"), {
                "npcTemplates": [{"id": "htpl_y", "name": "Wolf",
                                  "description": "A wild wolf"}],
            }, [("htpl_y", "portrait", b"WOLF-DONOR")])
            make_scenario(os.path.join(presets, "millbrook"), {
                "npcTemplates": [{"id": "htpl_b", "name": "Baker",
                                  "description": "Villager who bakes bread"}],
            }, [("htpl_b", "portrait", b"BAKER-DONOR")])
            out = os.path.join(tmp, "out")
            code, stdout, _ = run_tool([inp, "-o", out, "--presets", presets])

            self.assertEqual(code, 0)
            self.assertIn(
                "filled portrait htpl_x (Grey Wolf) <- preset thornbury: "
                "htpl_y (Wolf) [score 4]", stdout)
            with open(os.path.join(out, "media", "htpl_x",
                                   "htpl_x-portrait.webp"), "rb") as f:
                self.assertEqual(f.read(), b"WOLF-DONOR")

    def test_any_donor_of_the_kind_when_no_shared_words(self):
        with self.tempdir() as tmp:
            inp = make_scenario(os.path.join(tmp, "in"), {
                "itemTemplates": [{"id": "t_sword", "name": "Rusty Sword"}],
            })
            presets = os.path.join(tmp, "presets")
            make_scenario(os.path.join(presets, "alpha"), {
                "itemTemplates": [{"id": "d_pot", "name": "Healing Potion",
                                   "description": "Restores health"}],
            }, [("d_pot", "item", b"POTION")])
            out = os.path.join(tmp, "out")
            code, stdout, _ = run_tool([inp, "-o", out, "--presets", presets])

            self.assertEqual(code, 0)
            self.assertIn(
                "filled item t_sword (Rusty Sword) <- preset alpha: "
                "d_pot (Healing Potion) [score 0]", stdout)
            with open(os.path.join(out, "media", "t_sword",
                                   "t_sword-item.webp"), "rb") as f:
                self.assertEqual(f.read(), b"POTION")

    def test_own_media_wins_tie_against_preset(self):
        with self.tempdir() as tmp:
            inp = make_scenario(os.path.join(tmp, "in"), {
                "npcTemplates": [
                    {"id": "own_t", "name": "Grey Wolf"},
                    {"id": "own_d", "name": "Wolf"},
                ],
            }, [("own_d", "portrait", b"OWN")])
            presets = os.path.join(tmp, "presets")
            make_scenario(os.path.join(presets, "thornbury"), {
                "npcTemplates": [{"id": "pre_d", "name": "Wolf"}],
            }, [("pre_d", "portrait", b"PRESET")])
            out = os.path.join(tmp, "out")
            code, stdout, _ = run_tool([inp, "-o", out, "--presets", presets])

            self.assertEqual(code, 0)
            self.assertIn(
                "filled portrait own_t (Grey Wolf) <- scenario: own_d (Wolf) [score 4]",
                stdout)
            with open(os.path.join(out, "media", "own_t",
                                   "own_t-portrait.webp"), "rb") as f:
                self.assertEqual(f.read(), b"OWN")

    def test_input_and_donors_unchanged(self):
        with self.tempdir() as tmp:
            presets = os.path.join(tmp, "presets")
            preset = make_scenario(os.path.join(presets, "thornbury"), {
                "npcTemplates": [{"id": "dn", "name": "Donor"}],
            }, [("dn", "portrait", b"DONOR")])
            presets_before = hash_tree(preset)

            # Folder input: hash every file before and after the run.
            inp = make_scenario(os.path.join(tmp, "in"), {
                "npcTemplates": [{"id": "n_miss", "name": "Needs Portrait"},
                                 {"id": "n_have", "name": "Has Portrait"}],
            }, [("n_have", "portrait", b"HAVE")])
            with open(os.path.join(inp, "media", "notes.txt"), "w") as f:
                f.write("stray file")
            before = hash_tree(inp)
            code, stdout, _ = run_tool([inp, "-o", os.path.join(tmp, "out"),
                                        "--presets", presets])
            self.assertEqual(code, 0)
            self.assertEqual(hash_tree(inp), before)
            self.assertEqual(hash_tree(preset), presets_before)

            # Zip input: hash the whole file before and after the run.
            zpath = make_zip(os.path.join(tmp, "in.zip"), {
                "npcTemplates": [{"id": "n_miss", "name": "Needs Portrait"}],
            }, [("media/n_have/n_have-portrait.webp", b"HAVE")])
            with open(zpath, "rb") as f:
                zip_before = hashlib.sha256(f.read()).hexdigest()
            code, stdout, _ = run_tool([zpath, "-o", os.path.join(tmp, "out.zip"),
                                        "--presets", presets])
            self.assertEqual(code, 0)
            with open(zpath, "rb") as f:
                self.assertEqual(hashlib.sha256(f.read()).hexdigest(), zip_before)

    def test_zip_in_zip_out(self):
        with self.tempdir() as tmp:
            zpath = make_zip(os.path.join(tmp, "in.zip"), {
                "objectTemplates": [{"id": "obj_ok", "name": "Barrel"}],
                "npcTemplates": [
                    {"id": "n1", "name": "New One"},
                    {"id": "e_empty", "name": "Empty File"},
                ],
            }, [
                ("media/", b""),
                ("media/obj_ok/obj_ok-sprite.webp", b"OK-SPRITE"),
                ("media/e_empty/e_empty-portrait.webp", b""),
                ("notes.txt", b"keep me"),
            ])
            presets = os.path.join(tmp, "presets")
            make_scenario(os.path.join(presets, "thornbury"), {
                "npcTemplates": [{"id": "dn", "name": "Person"}],
            }, [("dn", "portrait", b"DONOR-BYTES")])
            out = os.path.join(tmp, "out.zip")
            code, stdout, _ = run_tool([zpath, "-o", out, "--presets", presets])

            self.assertEqual(code, 0)
            with zipfile.ZipFile(out) as z:
                names = z.namelist()
                for name in ("scenario.json", "media/",
                             "media/obj_ok/obj_ok-sprite.webp",
                             "media/e_empty/e_empty-portrait.webp",
                             "notes.txt", "media/n1/n1-portrait.webp"):
                    self.assertIn(name, names)
                self.assertEqual(z.read("media/n1/n1-portrait.webp"), b"DONOR-BYTES")
                self.assertEqual(z.read("media/e_empty/e_empty-portrait.webp"),
                                 b"DONOR-BYTES")
                self.assertEqual(z.read("media/obj_ok/obj_ok-sprite.webp"), b"OK-SPRITE")
                self.assertEqual(z.read("notes.txt"), b"keep me")
                with zipfile.ZipFile(zpath) as zin:
                    self.assertEqual(z.read("scenario.json"), zin.read("scenario.json"))
            self.assertIn(f"2 missing, 2 filled, 0 unfilled -> {out}", stdout)

    def test_refusals(self):
        with self.tempdir() as tmp:
            presets = os.path.join(tmp, "presets")
            make_scenario(os.path.join(presets, "thornbury"),
                          {"npcTemplates": [{"id": "dn", "name": "Person"}]},
                          [("dn", "portrait", b"D")])
            presets_before = hash_tree(presets)
            inp = make_scenario(os.path.join(tmp, "in"),
                                {"npcTemplates": [{"id": "n1", "name": "One"}]},
                                [("n1", "portrait", b"N")])
            inp_before = hash_tree(inp)

            def refuse(out):
                code, stdout, stderr = run_tool([inp, "-o", out, "--presets", presets])
                self.assertEqual(code, 2, stderr)
                self.assertEqual(stdout, "")
                self.assertTrue(stderr.strip())
                self.assertEqual(hash_tree(inp), inp_before)
                self.assertEqual(hash_tree(presets), presets_before)

            # OUTPUT already exists.
            exists_out = os.path.join(tmp, "exists-out")
            os.makedirs(exists_out)
            refuse(exists_out)
            self.assertEqual(os.listdir(exists_out), [])

            # OUTPUT resolves to INPUT.
            refuse(inp)
            # OUTPUT lies inside INPUT.
            refuse(os.path.join(inp, "child-out"))
            self.assertFalse(os.path.exists(os.path.join(inp, "child-out")))
            # OUTPUT lies inside the presets folder.
            refuse(os.path.join(presets, "stolen"))
            # OUTPUT lies inside a steamapps folder.
            steam = os.path.join(tmp, "steamapps", "common")
            os.makedirs(steam)
            refuse(os.path.join(steam, "out"))

    def test_bad_input_exits_two(self):
        with self.tempdir() as tmp:
            presets = os.path.join(tmp, "presets")
            os.makedirs(presets)

            # Folder without scenario.json.
            no_json = os.path.join(tmp, "nojson")
            os.makedirs(no_json)
            code, _, stderr = run_tool([no_json, "-o", os.path.join(tmp, "o1"),
                                        "--presets", presets])
            self.assertEqual(code, 2)
            self.assertTrue(stderr.strip())

            # Zip without scenario.json at its root.
            zpath = os.path.join(tmp, "nojson.zip")
            with zipfile.ZipFile(zpath, "w") as z:
                z.writestr("sub/scenario.json", "{}")
            code, _, stderr = run_tool([zpath, "-o", os.path.join(tmp, "o2.zip"),
                                        "--presets", presets])
            self.assertEqual(code, 2)
            self.assertTrue(stderr.strip())

            # Nonexistent input.
            code, _, stderr = run_tool([os.path.join(tmp, "ghost"),
                                        "-o", os.path.join(tmp, "o3"),
                                        "--presets", presets])
            self.assertEqual(code, 2)
            self.assertTrue(stderr.strip())

            for name in ("o1", "o2.zip", "o3"):
                self.assertFalse(os.path.exists(os.path.join(tmp, name)))

    def test_dry_run_writes_nothing(self):
        with self.tempdir() as tmp:
            inp = make_scenario(os.path.join(tmp, "in"), {
                "npcTemplates": [{"id": "own_t", "name": "Grey Wolf"},
                                 {"id": "own_d", "name": "Wolf"}],
            }, [("own_d", "portrait", b"OWN")])
            presets = os.path.join(tmp, "presets")
            os.makedirs(presets)
            out = os.path.join(tmp, "out")
            code, stdout, _ = run_tool([inp, "-o", out, "--presets", presets,
                                        "--dry-run"])
            self.assertEqual(code, 0)
            self.assertIn(
                "filled portrait own_t (Grey Wolf) <- scenario: own_d (Wolf) [score 4]",
                stdout)
            self.assertIn(f"1 missing, 1 filled, 0 unfilled -> {out}", stdout)
            self.assertFalse(os.path.exists(out))

    def test_donor_dir_and_base_sprite_only(self):
        with self.tempdir() as tmp:
            inp = make_scenario(os.path.join(tmp, "in"), {
                "objectTemplates": [{"id": "t_torch", "name": "Torch"}],
            })
            donor = make_scenario(os.path.join(tmp, "donors", "props"), {
                "objectTemplates": [{"id": "d_barrel", "name": "Barrel"}],
            }, [("d_barrel", "sprite", b"BASE")])
            # The donor has sprite variants; only the base file may be copied.
            write_image(donor, "d_barrel", "sprite-normal", b"NORMAL")
            write_image(donor, "d_barrel", "sprite-outline-0", b"OUTLINE")
            presets = os.path.join(tmp, "presets")
            os.makedirs(presets)
            out = os.path.join(tmp, "out")
            code, stdout, _ = run_tool([inp, "-o", out, "--donor", donor,
                                        "--presets", presets])

            self.assertEqual(code, 0)
            self.assertIn(
                "filled sprite t_torch (Torch) <- donor props: d_barrel (Barrel) [score 0]",
                stdout)
            target_dir = os.path.join(out, "media", "t_torch")
            self.assertEqual(os.listdir(target_dir), ["t_torch-sprite.webp"])
            with open(os.path.join(target_dir, "t_torch-sprite.webp"), "rb") as f:
                self.assertEqual(f.read(), b"BASE")


if __name__ == "__main__":
    unittest.main()
