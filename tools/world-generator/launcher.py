"""The world generator without the command line: questions in a terminal window.

Started by the launchers beside it (``Start World Generator.bat``,
``Start World Generator.command``, ``start-world-generator.sh``), or with
``python launcher.py``. When no provider is set up yet it asks for one and
writes ``providers.json`` (the same file the CLI and the Scenario Editor use).
"Make a new world" then asks how much framing to do - a quick idea, or the
short / medium / long questionnaire from ``worldgen/questions.json`` - shows
the World Frame P0 wrote for a use / edit / redo choice, and builds the world
into ``out/``. It can also re-roll the layout of a world made earlier, with no
model calls.

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
from worldgen import settings as settings_mod  # noqa: E402
from worldgen.extensions import REGISTRY, expand  # noqa: E402

EXAMPLE_PATH = os.path.join(HERE, "providers.example.json")
OUT_ROOT = os.path.join(HERE, "out")
GAME_VERSION = "0.18"
# provider settings kept when the launcher saves a provider
OPTIONAL_FIELDS = ("timeout", "rate_limit_wait", "max_output", "extra_body")


class Launcher:
    """One interactive session. ``inp``/``out``/``secret`` are swappable so
    the tests can script it; ``client`` replaces the provider in tests."""

    def __init__(self, inp=input, out=print, secret=None, providers_path=llm.PROVIDERS_PATH,
                 example_path=EXAMPLE_PATH, out_root=OUT_ROOT, client=None):
        self.inp, self.out = inp, out
        self.secret = secret or (getpass.getpass if sys.stdin.isatty() else inp)
        self.providers_path, self.example_path = providers_path, example_path
        self.out_root, self.client = out_root, client
        self._provider = None     # the provider picked for this session's calls

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
        entry = {"base_url": base_url.rstrip("/"), "api_key": key, "model": model,
                 "max_tokens": old.get("max_tokens") or preset.get("max_tokens") or 16000}
        # the preset's (or the saved entry's) optional settings come along:
        # a provider's output cap and extra request fields, its waits
        for k in OPTIONAL_FIELDS:
            v = old.get(k) if k in old else preset.get(k)
            if v is not None:
                entry[k] = v
        self.save_provider(name, entry)
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
    MODE_LABELS = ("Quick - one idea, the model frames it",
                   "Short questionnaire - 7 questions",
                   "Medium questionnaire - 14 questions",
                   "Long - 14 questions, then the model asks up to 5 more")

    def ask_question(self, q):
        """One question: numbered options plus Other, Enter to skip. A
        ``multi`` question takes up to that many numbers. Returns
        {"choices": [...], "other": "..."} or None when skipped."""
        if q.get("free"):
            text = self.ask(f"{q['prompt']} (free text, Enter to skip)")
            return {"choices": [], "other": text} if text else None
        self.out("")
        for i, opt in enumerate(q["options"], 1):
            self.out(f"  {i}) {opt}")
        other_n = len(q["options"]) + 1
        self.out(f"  {other_n}) Other")
        multi = q.get("multi", 1)
        picks = []
        while len(picks) < multi:
            tail = f" (pick up to {multi}, Enter to stop)" if multi > 1 and picks \
                else (" (Enter to skip)" if not picks else "")
            reply = self.ask(q["prompt"] + tail)
            if not reply:
                break
            if reply.isdigit() and int(reply) == other_n:
                text = self.ask("Your own answer")
                if text:
                    return {"choices": picks, "other": text}
            elif reply.isdigit() and 1 <= int(reply) <= len(q["options"]):
                label = q["options"][int(reply) - 1]
                if label not in picks:
                    picks.append(label)
            else:
                self.out(f"  Type a number from 1 to {other_n}.")
        return {"choices": picks, "other": ""} if picks else None

    def ask_questions(self, mode):
        from worldgen import questions as questions_mod
        answers = {}
        self.out("")
        self.out(f"The {mode} questionnaire - Enter skips any question.")
        for q in questions_mod.form_questions(mode):
            answer = self.ask_question(q)
            if answer is not None:
                answers[q["id"]] = answer
        return answers

    def ask_clarifications(self, questions):
        """The model's own questions (long mode): the same numbered UI, the
        answer recorded as the question/answer pair P0 wants back."""
        out = []
        for q in questions:
            self.out("")
            for i, opt in enumerate(q["options"], 1):
                self.out(f"  {i}) {opt}")
            other_n = len(q["options"]) + 1
            self.out(f"  {other_n}) Other")
            reply = self.ask(q["question"] + " (Enter to skip)")
            if not reply:
                continue
            if reply.isdigit() and int(reply) == other_n:
                text = self.ask("Your own answer")
                if text:
                    out.append({"question": q["question"], "answer": text})
            elif reply.isdigit() and 1 <= int(reply) <= len(q["options"]):
                out.append({"question": q["question"],
                            "answer": q["options"][int(reply) - 1]})
            else:
                self.out(f"  Type a number from 1 to {other_n}.")
        return out

    def ask_population(self):
        from worldgen import questions as questions_mod
        default, lo_min, hi_max = questions_mod.population_limits()
        reply = self.ask(f"Residents (a range like {default[0]}-{default[1]}; "
                         f"{lo_min}-{hi_max} allowed)")
        m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", reply)
        one = re.match(r"^\s*(\d+)\s*$", reply)
        pair = [int(m.group(1)), int(m.group(2))] if m else \
            ([int(one.group(1)), int(one.group(1))] if one else None)
        return questions_mod.sanitize_population(pair)

    def _frame_call(self, mode, idea, answers, population, out_dir, clarify=None, notes=""):
        return api.frame(mode, idea=idea, answers=answers, population=population,
                         clarify=clarify, notes=notes,
                         provider=None if self.client else self._provider,
                         providers_path=self.providers_path, client=self.client,
                         log_dir=os.path.join(out_dir, "llm"))

    def frame_flow(self, mode, idea, answers, population, out_dir, notes=""):
        """P0 and the use / edit / redo choice. Returns the frame or None."""
        from worldgen.phases import frame_brief
        clarify = None
        if mode == "long":
            first = self._frame_call(mode, idea, answers, population, out_dir, notes=notes)
            if first["questions"]:
                self.out("")
                self.out("The model has questions of its own (Enter skips one).")
                clarify = self.ask_clarifications(first["questions"])
        try:
            frame = self._frame_call(mode, idea, answers, population, out_dir,
                                     clarify=clarify, notes=notes)["frame"]
        except (llm.LLMError, phases.PhaseError) as e:
            self.out(f"Framing the world failed: {e}")
            return None
        while True:
            self.out("")
            self.out("THE WORLD FRAME")
            for line in frame_brief(frame, population).splitlines():
                self.out(line)
            i = self.choose("Use this frame?",
                            ["Use it as shown", "Edit the summary",
                             "Try again (another model call)"])
            if i == 0:
                return frame
            if i == 1:
                new = self.ask("New summary (one paragraph)")
                if new:
                    frame["summary"] = new
            else:
                try:
                    frame = self._frame_call(mode, idea, answers, population,
                                             out_dir, clarify=clarify, notes=notes)["frame"]
                except (llm.LLMError, phases.PhaseError) as e:
                    self.out(f"Framing the world failed: {e}")
                    return None

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
        self.settings_note(summary["out"])

    def settings_note(self, out_dir):
        path = os.path.join(out_dir, settings_mod.FILE_NAME)
        if os.path.isfile(path):
            self.out(f"Your choices for this world: {path}")
            self.out("  Send that file to share them (no API key is in it); "
                     "\"Make a new world from a settings file\" runs it again.")

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
        self._provider = provider
        self.out("")
        mode = ("quick", "short", "medium", "long")[
            self.choose("How much framing before the build?", list(self.MODE_LABELS))]
        idea = ""
        if mode == "quick":
            self.out("Describe the world in one line, e.g. "
                     "\"a fogbound harbour town of smugglers\".")
            while not idea:
                idea = self.ask("Idea")
        else:
            idea = self.ask("Idea (a line helps; Enter to go straight to the questions)")
        answers = self.ask_questions(mode)
        population = self.ask_population()
        label = idea or next((a.get("other") for a in answers.values()
                              if a.get("other")), "") or "world"
        out_dir = self._out_dir(label)
        self.out(f"Working in {out_dir}  (Ctrl+C stops it)")
        frame = self.frame_flow(mode, idea, answers, population, out_dir)
        if frame is None:
            return None
        exts = self.pick_extensions()
        library = self.yes("Furnish rooms from the room library? (No: the model furnishes "
                           "every room, the old method)", True)
        seed = self.ask("Seed (the same idea and seed give the same layout)", "1")
        seed = int(seed) if seed.isdigit() else 1
        est = api.estimate(idea or "a small world")
        self.out("")
        self.out(f"About {est['calls']} model calls, ~{est['tokens']:,} tokens and "
                 f"{est['minutes_range'][0]}-{est['minutes_range'][1]} minutes, on your key.")
        if not self.yes("Start?", True):
            return None
        return self._start_world(idea, provider, exts, seed, out_dir, frame, library,
                                 {"mode": mode, "answers": answers, "population": population})

    def _start_world(self, idea, provider, exts, seed, out_dir, frame, library, questionnaire):
        return self._run(lambda progress, emit: api.generate(
            idea, provider=provider, extensions=exts, seed=seed, out_dir=out_dir,
            progress=progress, providers_path=self.providers_path, client=self.client,
            emit=emit, frame=frame, library=library, questionnaire=questionnaire), out_dir)

    def _pick_provider(self):
        """The provider for a run (setting one up when none is), or False."""
        ready = self.ready_providers()
        if self.client is None and not ready:
            self.out("No provider is set up yet.")
            if not self.setup_provider():
                return False
            ready = self.ready_providers()
        if self.client is not None:
            return None
        return ready[self.choose("Which provider?", ready)] if len(ready) > 1 else ready[0]

    def world_from_settings(self):
        """A new world from a settings file someone saved or sent: the same
        idea, answers and choices, and their World Frame when the file has one."""
        self.out("")
        self.out("A settings file is the settings.json in a world's folder under")
        self.out(f"{self.out_root}, or one exported from the Scenario Editor.")
        path = self.ask("Path to the settings file (you can drag the file here)").strip().strip('"\'')
        if not path:
            return None
        try:
            s = settings_mod.read(os.path.expanduser(path))
        except settings_mod.SettingsError as e:
            self.out(f"Can't use that file: {e}")
            return None
        self.out("")
        self.out(f"  Form: {s['mode']}" + (f", {len(s['answers'])} answer(s)" if s["answers"] else ""))
        if s["idea"]:
            self.out(f"  Idea: {s['idea'][:200]}")
        if s["notes"]:
            self.out(f"  Other instructions: {s['notes'][:200]}" + ("..." if len(s["notes"]) > 200 else ""))
        pop = s["population"]
        self.out(f"  Residents: {'the map decides' if pop == 'map' else f'{pop[0]}-{pop[1]}'}")
        self.out(f"  Seed {s['seed']}; extensions: {', '.join(s['extensions']) or 'none'}; "
                 f"room library: {'on' if s['library'] else 'off'}")
        if s.get("model"):
            self.out(f"  Made with the model {s['model']}")
        provider = self._pick_provider()
        if provider is False:
            return None
        self._provider = provider
        out_dir = self._out_dir(settings_mod.label(s))
        self.out(f"Working in {out_dir}  (Ctrl+C stops it)")
        frame = s.get("frame")
        if frame and not self.yes("Use the World Frame saved in the file? (No: frame the "
                                  "world again, one more model call)", True):
            frame = None
        if frame is None:
            frame = self.frame_flow(s["mode"], s["idea"], s["answers"], s["population"],
                                    out_dir, notes=s["notes"])
            if frame is None:
                return None
        seed = self.ask("Seed (the same idea and seed give the same layout)", str(s["seed"]))
        seed = int(seed) if seed.isdigit() else s["seed"]
        if not self.yes("Start?", True):
            return None
        return self._start_world(s["idea"], provider, tuple(s["extensions"]), seed, out_dir,
                                 frame, s["library"], settings_mod.questionnaire(s)
                                 or {"mode": s["mode"], "answers": {},
                                     "population": s["population"]})

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
                   ("Make a new world from a settings file", self.world_from_settings),
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
