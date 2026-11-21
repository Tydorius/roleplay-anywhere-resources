#!/usr/bin/env python3
"""Parallel runner for the world-generator test suite.

`python -m unittest discover -s tests` is the reference run; this runner
gives the same answer faster.  It finds the same modules with unittest's
own loader, runs each one (or each TestCase class of a slow one) as a
`python -m unittest <name>` child process, starts the longest jobs first,
and fails unless the jobs ran exactly the number of tests the loader
counts for the whole suite.

Python 3.8+, standard library only.  Run it from this folder:

    python run_tests.py                                # whole suite
    python run_tests.py -j 8                           # eight workers
    python run_tests.py test_assembler                 # one module
    python run_tests.py test_assembler.TestStoreys     # one class
    python run_tests.py --record                       # rewrite tests/durations.json
"""

import argparse
import json
import locale
import os
import re
import subprocess
import sys
import threading
import time
import unittest
from queue import Empty, Queue

ROOT = os.path.dirname(os.path.abspath(__file__))
DURATIONS_PATH = os.path.join(ROOT, "tests", "durations.json")

# A module whose recorded duration reaches this many seconds is split into
# one job per TestCase class, so one slow module cannot stretch the whole
# batch.  Measured on the full suite: the median module runs 4s, the third
# slowest 6.5 min, and two modules (test_room_library_gen, 17.7 min;
# test_recipe_compounds, 12.8 min) stand 2-3x above everything else — the
# line sits between the crowd and those two.
SPLIT_THRESHOLD = 600.0

# Jobs that truly cannot share the machine (a fixed port, say) run alone,
# after the parallel batch.  Keep empty: give a test its own temp folder
# instead whenever that is possible.
SERIAL_JOBS = ()


class Job(object):
    """One `python -m unittest <name>` child process."""

    def __init__(self, name, module, expected, split):
        self.name = name        # test_x or test_x.ClassName
        self.module = module    # the module the job belongs to
        self.expected = expected
        self.split = split      # one class of a module split by duration


class Result(object):
    def __init__(self, job, duration, output):
        self.job = job
        self.duration = duration
        self.output = output
        self.status = "error"   # ok | failed | error
        self.tests_ran = None
        self.failures = 0
        self.errors = 0
        self.note = None


# ---------------------------------------------------------------- loading

def _iter_tests(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            for test in _iter_tests(item):
                yield test
        else:
            yield item


def suite_modules():
    """The module names `discover -s tests` runs, in discovery order."""
    suite = unittest.defaultTestLoader.discover("tests")
    names = []
    for test in _iter_tests(suite):
        module = type(test).__module__
        if module not in names:
            names.append(module)
    return names, suite


def count_tests(name):
    suite = unittest.defaultTestLoader.loadTestsFromName(name)
    return sum(1 for _ in _iter_tests(suite))


def module_classes(module):
    """The `module.ClassName` job names for a module, in collection order."""
    suite = unittest.defaultTestLoader.loadTestsFromName(module)
    names = []
    for test in _iter_tests(suite):
        full = module + "." + type(test).__name__
        if full not in names:
            names.append(full)
    return names


def load_durations():
    try:
        with open(DURATIONS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return {name: float(t) for name, t in data.items() if isinstance(t, (int, float))}


def module_duration(module, durations):
    """A module's time: its own entry, else the sum of its class entries."""
    if module in durations:
        return durations[module]
    total, have = 0.0, False
    for key, value in durations.items():
        if key.startswith(module + "."):
            total += value
            have = True
    return total if have else None


# ------------------------------------------------------------------ jobs

def resolve_selection(args, modules):
    """Turn name arguments into {module: set of class names} (empty: all).

    Modules are named as discovery imports them (`test_x`); a class is
    `test_x.TestY`.
    """
    selected = {}
    classes_cache = {}
    for arg in args:
        # a whole module, named exactly
        if arg in modules:
            selected.setdefault(arg, set())
            continue
        # a class inside a named module: test_x.TestY
        parents = [m for m in modules if arg.startswith(m + ".")]
        if len(parents) > 1:
            _usage_error("ambiguous name %r matches %s" % (arg, ", ".join(parents)))
        if parents:
            module = parents[0]
            classes_cache.setdefault(module, module_classes(module))
            if arg not in classes_cache[module]:
                _usage_error("no test class %r in %s" % (arg[len(module) + 1:], module))
            selected.setdefault(module, set()).add(arg)
            continue
        # bare names: test_x, or test_x.TestY
        mods = [m for m in modules if m == arg or m.endswith("." + arg)]
        if len(mods) == 1:
            selected.setdefault(mods[0], set())
            continue
        if len(mods) > 1:
            _usage_error("ambiguous name %r matches %s" % (arg, ", ".join(mods)))
        if "." in arg:
            head, cls = arg.rsplit(".", 1)
            mods = [m for m in modules if m == head or m.endswith("." + head)]
            if len(mods) == 1:
                full = mods[0] + "." + cls
                classes_cache.setdefault(mods[0], module_classes(mods[0]))
                if full not in classes_cache[mods[0]]:
                    _usage_error("no test class %r in %s" % (cls, mods[0]))
                selected.setdefault(mods[0], set()).add(full)
                continue
            if len(mods) > 1:
                _usage_error("ambiguous name %r matches %s" % (arg, ", ".join(mods)))
        _usage_error("no module or class named %r (modules look like test_x)" % arg)
    return selected


def build_jobs(args_names, durations):
    """Enumerate jobs, check them against the loader, order longest first."""
    modules, suite = suite_modules()
    suite_total = sum(1 for _ in _iter_tests(suite))
    selected = resolve_selection(args_names, modules) if args_names else None

    jobs = []
    split_modules = set()
    for module in modules:
        if selected is not None and module not in selected:
            continue
        duration = module_duration(module, durations)
        classes = module_classes(module)
        split = len(classes) > 1 and (
            (selected is not None and selected[module])
            or (duration is not None and duration >= SPLIT_THRESHOLD))
        if split:
            split_modules.add(module)
            wanted = selected[module] if selected and selected[module] else None
            for cls in classes:
                if wanted is None or cls in wanted:
                    jobs.append(Job(cls, module, count_tests(cls), True))
        else:
            jobs.append(Job(module, module, count_tests(module), False))

    expected = sum(job.expected for job in jobs)
    if expected != suite_total and selected is None:
        # With a selection the loader's whole-suite count no longer applies;
        # without one the jobs must add up to the reference run exactly.
        _usage_error("enumeration mismatch: jobs count %d tests, the loader "
                     "counts %d" % (expected, suite_total))

    # longest first; a job missing from durations.json runs with the first wave
    def order(job):
        t = durations.get(job.name)
        return (0, 0.0) if t is None else (1, -t)
    jobs.sort(key=order)
    return jobs, suite_total, split_modules


# ---------------------------------------------------------------- running

class Pool(object):
    """Worker threads that each run one child process at a time."""

    def __init__(self, workers, timeout_secs):
        self.workers = workers
        self.timeout_secs = timeout_secs
        self.job_q = Queue()
        self.done_q = Queue()
        self.stop = threading.Event()
        self.active = set()
        self.active_lock = threading.Lock()
        self.threads = []

    def run(self, jobs):
        for job in jobs:
            self.job_q.put(job)
        for _ in range(min(self.workers, len(jobs))):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            self.threads.append(t)
        return self.done_q

    def _worker(self):
        while not self.stop.is_set():
            try:
                job = self.job_q.get_nowait()
            except Empty:
                return
            self.done_q.put(self._run_one(job))

    def _run_one(self, job):
        cmd = [sys.executable, "-m", "unittest", job.name]
        env = dict(os.environ)
        # the package root and tests/ itself, so a module imports the same
        # way a child of `discover -s tests` would
        paths = [ROOT, os.path.join(ROOT, "tests")]
        if env.get("PYTHONPATH"):
            paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(paths)
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        start = time.monotonic()
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, env=env,
                                creationflags=creationflags)
        with self.active_lock:
            self.active.add(proc)
        try:
            try:
                out, _ = proc.communicate(timeout=self.timeout_secs)
                timed_out = False
            except subprocess.TimeoutExpired:
                self._kill(proc)
                out, _ = proc.communicate()
                timed_out = True
        finally:
            with self.active_lock:
                self.active.discard(proc)
        duration = time.monotonic() - start
        encoding = locale.getpreferredencoding(False) or "utf-8"
        text = out.decode(encoding, errors="replace")
        return parse_result(job, text, proc.returncode, duration, timed_out, self.timeout_secs)

    def _kill(self, proc):
        try:
            proc.kill()
        except OSError:
            pass

    def kill_active(self):
        with self.active_lock:
            procs = list(self.active)
        for proc in procs:
            self._kill(proc)


_RAN = re.compile(r"^Ran (\d+) tests? in ", re.M)
# not "expected failures=2"
_COUNTS = re.compile(r"(?<!expected )(failures|errors|skipped)=(\d+)")


def parse_result(job, text, returncode, duration, timed_out, timeout_secs):
    result = Result(job, duration, text)
    ran = _RAN.search(text)
    if ran:
        result.tests_ran = int(ran.group(1))
    # the verdict is the last line unittest prints; scan from the end so a
    # test that prints OK or FAILED mid-run cannot win
    verdict = None
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped.startswith("OK") or stripped.startswith("SKIPPED"):
            verdict = "ok"
            break
        if stripped.startswith("FAILED"):
            verdict = "failed"
            for key, value in _COUNTS.findall(stripped):
                if key == "failures":
                    result.failures = int(value)
                elif key == "errors":
                    result.errors = int(value)
            break
    if timed_out:
        result.status = "error"
        result.errors = 1
        result.note = "timed out after %.0f minutes" % (timeout_secs / 60.0)
    elif verdict == "failed":
        result.status = "failed"
    elif verdict == "ok" and returncode == 0 and result.tests_ran is not None:
        result.status = "ok"
    else:
        result.status = "error"
        result.errors = 1
        result.note = "no unittest summary (exit code %s)" % returncode
    return result


# ------------------------------------------------------------------ main

def _usage_error(message):
    sys.stderr.write("run_tests.py: %s\n" % message)
    raise SystemExit(2)


def collect(pool, jobs, total):
    """Print a line per job as it finishes; return the results."""
    results = []
    width = max((len(job.name) for job in jobs), default=0)
    try:
        for done in range(1, total + 1):
            result = pool.done_q.get()
            results.append(result)
            ran = "?" if result.tests_ran is None else str(result.tests_ran)
            print("[%2d/%d] %-6s %8.1fs %5s tests  %s"
                  % (done, total, result.status.upper(), result.duration, ran,
                     result.job.name.ljust(width)), flush=True)
    except KeyboardInterrupt:
        pool.stop.set()
        pool.kill_active()
        time.sleep(0.2)
        pool.kill_active()
        raise SystemExit(130)
    return results


def record_durations(durations, results, split_modules):
    for result in results:
        if result.tests_ran is None:
            continue  # crashed or timed out: keep the last good figure
        durations[result.job.name] = round(result.duration, 1)
    # a module is keyed either by itself or by its classes, never both, so
    # the split decision and the ordering stay in sync
    for module in {r.job.module for r in results}:
        if module in split_modules:
            durations.pop(module, None)
        else:
            for name in [n for n in durations if n.startswith(module + ".")]:
                del durations[name]
    tmp = DURATIONS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(durations, f, sort_keys=True, indent=1)
        f.write("\n")
    os.replace(tmp, DURATIONS_PATH)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the world-generator tests in parallel. "
                    "`python -m unittest discover -s tests` stays the reference.")
    parser.add_argument("names", nargs="*",
                        help="optional module or class names, e.g. test_assembler")
    parser.add_argument("-j", "--jobs", type=int, default=None,
                        help="worker count (default: CPU count minus 2)")
    parser.add_argument("--record", action="store_true",
                        help="rewrite tests/durations.json with the measured times")
    parser.add_argument("--timeout", type=float, default=30.0, metavar="MINUTES",
                        help="kill a job that runs longer (default: 30)")
    args = parser.parse_args(argv)

    started = time.monotonic()
    os.chdir(ROOT)
    durations = load_durations()

    jobs, suite_total, split_modules = build_jobs(args.names, durations)
    if not jobs:
        _usage_error("no tests selected")

    parallel = [job for job in jobs if job.name not in SERIAL_JOBS]
    serial = [job for job in jobs if job.name in SERIAL_JOBS]

    default_workers = max(1, (os.cpu_count() or 4) - 2)
    workers = default_workers if args.jobs is None else args.jobs
    if workers < 1:
        _usage_error("-j must be at least 1")
    workers = min(workers, len(parallel) or 1)
    timeout_secs = args.timeout * 60.0

    expected_total = sum(job.expected for job in jobs)
    print("%d tests in %d jobs (%d workers, timeout %.0f min)"
          % (expected_total, len(jobs), workers, args.timeout), flush=True)

    pool = Pool(workers, timeout_secs)
    pool.run(parallel)
    results = collect(pool, parallel, len(parallel))
    try:
        for job in serial:
            result = pool._run_one(job)
            results.append(result)
            print("[ser] %-6s %8.1fs %5s tests  %s"
                  % (result.status.upper(), result.duration,
                     "?" if result.tests_ran is None else result.tests_ran,
                     job.name), flush=True)
    except KeyboardInterrupt:
        pool.kill_active()
        raise SystemExit(130)

    ran_total = sum(r.tests_ran or 0 for r in results)
    failures = sum(r.failures for r in results)
    errors = sum(r.errors for r in results)
    bad = [r for r in results if r.status != "ok"]

    if bad:
        print()
        for result in bad:
            banner = "-------- %s: %s --------" % (result.job.name, result.status)
            print(banner)
            if result.note:
                print(result.note)
            print(result.output.rstrip())
            print("-" * len(banner))
        print()

    wall = time.monotonic() - started
    print("Ran %d tests in %.1fs" % (ran_total, wall), flush=True)
    print()
    if failures or errors or bad:
        print("FAILED (failures=%d, errors=%d)" % (failures, errors))
        code = 1
    else:
        print("OK")
        code = 0
    if ran_total != suite_total and not args.names:
        print("TEST COUNT MISMATCH: jobs ran %d tests, the loader counts %d"
              % (ran_total, suite_total))
        code = 1

    if args.record:
        record_durations(durations, results, split_modules)
    return code


if __name__ == "__main__":
    sys.exit(main())
