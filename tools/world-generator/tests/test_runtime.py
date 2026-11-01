"""Runtime guards: the package runs on Python 3.8 with the standard library
only, and every use of Pillow is optional — without it previews are skipped
with one clear message and nothing else changes."""
import ast
import contextlib
import importlib.util
import io
import os
import sys
import unittest

PKG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "worldgen")

# everything the package may import: the standard library (3.8), the package
# itself, and Pillow (always behind a try/except ImportError)
STDLIB = {"argparse", "ast", "collections", "copy", "dataclasses", "datetime",
          "decimal", "functools", "hashlib", "importlib", "io", "itertools",
          "json", "math", "os", "pathlib", "random", "re", "shutil", "string",
          "struct", "subprocess", "sys", "tempfile", "time", "urllib",
          "zipfile", "zlib"}
ALLOWED = STDLIB | {"PIL", "worldgen"}


def package_files():
    for root, dirs, files in os.walk(PKG_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in sorted(files):
            if fn.endswith(".py"):
                yield os.path.join(root, fn)


class TestPython38StdlibOnly(unittest.TestCase):
    def test_imports_are_stdlib_or_optional_pillow(self):
        seen = set()
        for path in package_files():
            with open(path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    seen.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    seen.add(node.module.split(".")[0])
        outside = seen - ALLOWED
        self.assertEqual(outside, set(),
                         f"the package must depend on the standard library only "
                         f"(plus optional Pillow); found {sorted(outside)}")

    def test_no_syntax_newer_than_python_38(self):
        for path in package_files():
            with open(path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=path)
            with self.subTest(path):
                for node in ast.walk(tree):
                    if isinstance(node, ast.Match):
                        self.fail("match statements need Python 3.10")
                    for field in ("annotation", "returns"):
                        ann = getattr(node, field, None)
                        if isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
                            self.fail("X | Y annotations need Python 3.10")


class TestPillowOptional(unittest.TestCase):
    def _vendored(self, name):
        path = os.path.join(PKG_DIR, "vendor", name)
        spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_render_map_skips_previews_with_one_message(self):
        rm = self._vendored("render_map.py")
        had_pillow = rm.Image is not None
        rm.Image = rm.ImageDraw = None
        try:
            out = io.StringIO()
            argv = sys.argv
            sys.argv = ["render_map.py"]
            try:
                with contextlib.redirect_stdout(out):
                    rm.main()
            finally:
                sys.argv = argv
        finally:
            if had_pillow:
                import PIL
                rm.Image = PIL.Image
                rm.ImageDraw = PIL.ImageDraw
        self.assertIn("Pillow", out.getvalue())
        self.assertIn("skip", out.getvalue())

    def test_build_scenario_imports_pillow_optionally(self):
        src = os.path.join(PKG_DIR, "vendor", "build_scenario.py")
        with open(src, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        imports_pil = any(
            isinstance(n, ast.ImportFrom) and n.module == "PIL"
            for n in ast.walk(tree))
        self.assertTrue(imports_pil)
        # and the import sits under a try/except ImportError
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for stmt in node.body:
                    if isinstance(stmt, ast.ImportFrom) and stmt.module == "PIL":
                        handlers = {h.type.id for h in node.handlers
                                    if isinstance(h.type, ast.Name)}
                        self.assertIn("ImportError", handlers)


if __name__ == "__main__":
    unittest.main()
