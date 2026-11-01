"""The world generator without the command line: questions in a terminal window.

Started by the launchers beside it (``Start World Generator.bat``,
``Start World Generator.command``, ``start-world-generator.sh``), or with
``python launcher.py``. When no provider is set up yet it asks for one and
writes ``providers.json`` (the same file the CLI and the Scenario Editor use),
then asks for an idea and the extensions, and builds the world into ``out/``.
It can also re-roll the layout of a world made earlier, with no model calls.

Python 3.8+, standard library only. The api key is typed hidden and never
printed or logged.
"""
import datetime
import getpass
import json
import os
import random
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from worldgen import api, llm, phases  # noqa: E402
from worldgen.extensions import REGISTRY, expand  # noqa: E402

EXAMPLE_PATH = os.path.join(HERE, "providers.example.json")
OUT_ROOT = os.path.join(HERE, "out")
GAME_VERSION = "0.18"


class Launcher:
    """One interactive session. ``inp``/``out``/``secret`` are swappable so
    the tests can script it; ``client`` replaces the provider in tests."""

    def __init__(self, inp=input, out=print, secret=None, providers_path=llm.PROVIDERS_PATH,
                 example_path=EXAMPLE_PATH, out_root=OUT_ROOT, client=None):
        self.inp, self.out = inp, out
        self.secret = secret or (getpass.getpass if sys.stdin.isatty() else inp)
        self.providers_path, self.example_path = providers_path, example_path
        self.out_root, self.client = out_root, client

    # ------------------------------------------------------------ asking
    def ask(self, prompt, default=None):
        hint = f" [{default}]" if default not in (None, "") else ""
        reply = self.inp(f"{prompt}{hint}: ").strip()
        return reply if reply else (default if default is not None else "")

    def yes(self, prompt, default=False):
        reply = self.inp(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        return default if not reply else reply.startswith("y")

    def choose(self, prompt, options, default=1):
        """options: list of labels; returns the 0-based index."""
        for i, label in enumerate(options, 1):
            self.out(f"  {i}) {label}")
        while True:
            reply = self.ask(prompt, str(default))
            if reply.isdigit() and 1 <= int(reply) <= len(options):
                return int(reply) - 1
            self.out(f"  Type a number from 1 to {len(options)}.")

    # ------------------------------------------------------------ providers
    def _read(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def ready_providers(self):
        """Names of providers with a base URL, a model and a real key."""
        data = self._read(self.providers_path) or {}
        return [name for name, cfg in data.items()
                if not name.startswith("_") and isinstance(cfg, dict)
                and cfg.get("base_url") and cfg.get("model")
                and cfg.get("api_key") and cfg.get("api_key") != llm.PLACEHOLDER_KEY]

    def save_provider(self, name, entry):
        """Add or replace one entry, keeping the others; written atomically."""
        data = self._read(self.providers_path)
        if data is None:
            data = {"_readme": ["Providers for the world generator (written by its launcher).",
                                "This file holds your api keys: keep it private."]}
        data[name] = entry
        tmp = self.providers_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.providers_path)

    def setup_provider(self):
        """Ask for one provider and save it. Returns its name, or None."""
        presets = {k: v for k, v in (self._read(self.example_path) or {}).items()
                   if not k.startswith("_") and isinstance(v, dict)}
        names = list(presets)
        self.out("")
        self.out("The generator calls a language model through your own account and key")
        self.out("(or a model server on your own machine), never the game's subscription.")
        self.out("Which provider?")
        labels = [f"{n}: {re.split(r'[(;]', presets[n].get('_comment', ''))[0].strip().rstrip('.') or presets[n]['base_url']}"
                  for n in names] + ["another OpenAI-compatible server"]
        i = self.choose("Number", labels)
        preset = presets[names[i]] if i < len(names) else {}
        name = names[i] if i < len(names) else ""
        while True:
            name = self.ask("A short name for it", name or "my-provider")
            if re.match(r"^[A-Za-z0-9][A-Za-z0-9 _-]*$", name):
                break
            self.out("  Letters, digits, spaces, - and _ only.")
        old = (self._read(self.providers_path) or {}).get(name)
        old = old if isinstance(old, dict) else {}
        base_url = self.ask("Base URL", old.get("base_url") or preset.get("base_url"))
        model = self.ask("Model", old.get("model") or preset.get("model"))
        local = preset.get("api_key") == "none"
        keep = old.get("api_key") not in (None, "", llm.PLACEHOLDER_KEY)
        if local:
            self.out("A local server ignores the key; press Enter to leave it as \"none\".")
        elif keep:
            self.out("Press Enter to keep the key already saved for it.")
        key = self.secret("API key (typing is hidden): ").strip()
        key = key or (old.get("api_key") if keep else "") or ("none" if local else "")
        if not (base_url and model and key):
            self.out("Not saved: the base URL, model and key are all needed.")
            return None
        self.save_provider(name, {"base_url": base_url.rstrip("/"), "api_key": key, "model": model,
                                  "max_tokens": old.get("max_tokens") or preset.get("max_tokens") or 16000})
        self.out(f"Saved \"{name}\" to {self.providers_path}")
        if self.yes("Send it one tiny test request now?", True):
            self.test_provider(name)
        return name

    def test_provider(self, name=None):
        ready = self.ready_providers()
        if not ready:
            self.out("No provider is set up yet.")
            return False
        if name is None:
            name = ready[self.choose("Which provider?", ready)] if len(ready) > 1 else ready[0]
        self.out(f"Asking {name} for a one-word reply...")
        try:
            report = llm.check_provider(name, self.providers_path)
        except llm.LLMError as e:
            report = {"ok": False, "error": str(e)}
        if report["ok"]:
            self.out(f"OK: {report['model']} answered in {report['seconds']}s.")
            return True
        self.out(f"That didn't work: {report['error']}")
        self.out("Check the URL, model and key (choose \"Set up a provider\" to change them).")
        return False

    # ------------------------------------------------------------ worlds
    def pick_extensions(self, given=()):
        self.out("")
        self.out("Extensions add features that need code mods from ../code-mod-loader")
        self.out("installed in the game. All off makes a world for the plain game.")
        chosen = set(given)
        for e in REGISTRY:
            if e.id in expand(chosen):
                self.out(f"  {e.title}: on (needed by {', '.join(sorted(x for x in chosen if e.id in expand([x]) and x != e.id))})")
                continue
            self.out(f"  {e.title}: {e.description}")
            self.out(f"    Needs the {' + '.join(e.mods)} mod{'s' if len(e.mods) > 1 else ''}; "
                     f"{e.as_dict()['withoutMod']}.")
            if self.yes(f"  Turn on {e.title}?"):
                chosen.add(e.id)
        return sorted(expand(chosen))

    def _out_dir(self, label):
        slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:30] or "world"
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        return os.path.join(self.out_root, f"{slug}-{stamp}")

    def _progress(self, e):
        tail = f"  ({e['calls']} calls, {e['tokens']:,} tokens)" if e.get("calls") else ""
        self.out(f"  {e.get('phase')}: {e.get('label')}{tail}")

    def _run(self, start, out_dir):
        """Runs ``start(progress, emit)`` with the build log going to a file;
        returns the summary or None. Ctrl+C stops it."""
        os.makedirs(out_dir, exist_ok=True)
        log_path = os.path.join(out_dir, "launcher.log")
        with open(log_path, "w", encoding="utf-8") as log:
            def emit(text):
                log.write(str(text) + "\n")
                if str(text).startswith("ERROR"):
                    self.out("  " + str(text))
            try:
                summary = start(self._progress, emit)
            except KeyboardInterrupt:
                self.out("Stopped.")
                return None
            except (llm.LLMError, phases.PhaseError) as e:
                self.out(f"The model calls failed: {e}")
                self.out(f"Every call's prompt and reply is in {os.path.join(out_dir, 'llm')}")
                return None
        self.report(summary, log_path)
        return summary

    def report(self, summary, log_path):
        self.out("")
        if not summary.get("zip"):
            self.out(f"The build failed. Details: {log_path}")
            return
        zip_path = os.path.join(summary["out"], summary["zip"])
        state = "Done" if summary["ok"] else f"Built with {summary['validator_errors']} problem(s)"
        self.out(f"{state}: {summary['zones']} zones, {summary['buildings']} buildings, "
                 f"{summary['npcs']} people, map {summary['grid']}.")
        self.out(f"  {zip_path}")
        self.out("Import it in Anywhere RPG with New Game > Import..., or open it in the")
        self.out("Scenario Editor to look it over first.")
        if not summary["ok"]:
            self.out(f"  Build log: {log_path}")

    def new_world(self):
        ready = self.ready_providers()
        if self.client is None and not ready:
            self.out("No provider is set up yet.")
            if not self.setup_provider():
                return None
            ready = self.ready_providers()
        provider = None
        if self.client is None:
            provider = ready[self.choose("Which provider?", ready)] if len(ready) > 1 else ready[0]
        self.out("")
        self.out("Describe the world in one line, e.g. \"a fogbound harbour town of smugglers\".")
        idea = ""
        while not idea:
            idea = self.ask("Idea")
        exts = self.pick_extensions()
        seed = self.ask("Seed (the same idea and seed give the same layout)", "1")
        seed = int(seed) if seed.isdigit() else 1
        est = api.estimate(idea)
        self.out("")
        self.out(f"About {est['calls']} model calls, ~{est['tokens']:,} tokens and "
                 f"{est['minutes_range'][0]}-{est['minutes_range'][1]} minutes, on your key.")
        if not self.yes("Start?", True):
            return None
        out_dir = self._out_dir(idea)
        self.out(f"Working in {out_dir}  (Ctrl+C stops it)")
        return self._run(lambda progress, emit: api.generate(
            idea, provider=provider, extensions=exts, seed=seed, out_dir=out_dir,
            progress=progress, providers_path=self.providers_path, client=self.client,
            emit=emit), out_dir)

    def saved_worlds(self):
        """(label, plan path) for worlds in out/, newest first."""
        found = []
        if os.path.isdir(self.out_root):
            for d in os.listdir(self.out_root):
                plan = os.path.join(self.out_root, d, "plan.json")
                if os.path.isfile(plan):
                    found.append((os.path.getmtime(plan), d, plan))
        found.sort(reverse=True)
        return [(d, plan) for _t, d, plan in found]

    def reroll(self):
        worlds = self.saved_worlds()
        if not worlds:
            self.out(f"No saved worlds in {self.out_root} yet.")
            return None
        self.out("Which world? The same world is placed again, with no model calls.")
        label, plan = worlds[self.choose("Number", [w[0] for w in worlds[:15]])]
        seed = self.ask("New seed", str(random.randint(2, 9999)))
        seed = int(seed) if seed.isdigit() else 2
        out_dir = self._out_dir(re.sub(r"-\d{8}-\d{6}$", "", label) + f"-seed{seed}")
        return self._run(lambda progress, emit: api.relayout(
            plan, seed=seed, out_dir=out_dir, progress=progress, emit=emit), out_dir)

    # ------------------------------------------------------------ menu
    def main(self):
        self.out(f"Anywhere RPG world generator (built for Anywhere RPG {GAME_VERSION})")
        if self.client is None and not self.ready_providers():
            self.out("")
            self.out("First, set up the model provider the generator will use.")
            if not self.setup_provider():
                return 1
        actions = [("Make a new world from an idea", self.new_world),
                   ("Re-roll the layout of a world made earlier (no model calls)", self.reroll),
                   ("Set up a provider (add or change one)", self.setup_provider),
                   ("Test a provider", self.test_provider),
                   ("Open the output folder", self.open_out),
                   ("Quit", None)]
        while True:
            self.out("")
            ready = self.ready_providers()
            self.out(f"Providers: {', '.join(ready) or 'none set up'}")
            i = self.choose("What next?", [a[0] for a in actions])
            if actions[i][1] is None:
                return 0
            actions[i][1]()

    def open_out(self):
        os.makedirs(self.out_root, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(self.out_root)
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", self.out_root])
        except OSError:
            pass
        self.out(self.out_root)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    try:
        sys.exit(Launcher().main())
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(0)
