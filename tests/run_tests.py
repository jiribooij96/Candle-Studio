#!/usr/bin/env python3
"""Run the Candle Studio tests in Blender (background mode).

    python3 tests/run_tests.py              # everything (about 3 minutes)
    python3 tests/run_tests.py shapes ui    # just these tests
    python3 tests/run_tests.py -v ui        # also show each check

Finds Blender on PATH or in the usual install places; set BLENDER=/path/to/blender
to pick one. Each test runs in a throwaway Blender profile and output folder,
so your own Blender settings and add-ons are never touched.
"""

import glob
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PLACES = ["/Applications/Blender.app/Contents/MacOS/Blender",
          *sorted(glob.glob(r"C:\Program Files\Blender Foundation\Blender*\blender.exe"), reverse=True),
          "/snap/bin/blender"]


def find_blender():
    found = os.environ.get("BLENDER") or shutil.which("blender")
    found = found or next((p for p in PLACES if os.path.exists(p)), None)
    if not found:
        sys.exit("Blender not found: set BLENDER=/path/to/blender")
    return found


def main():
    args = sys.argv[1:]
    verbose = "-v" in args
    wanted = [a for a in args if a != "-v"]
    tests = sorted(glob.glob(os.path.join(HERE, "test_*.py")))
    if wanted:
        tests = [t for t in tests if os.path.basename(t)[5:-3] in wanted]
        if not tests:
            sys.exit("no such test; choose from: " + ", ".join(
                os.path.basename(t)[5:-3] for t in sorted(glob.glob(os.path.join(HERE, "test_*.py")))))
    blender = find_blender()
    print(f"Blender: {blender}\n")
    failed = []
    for test in tests:
        name = os.path.basename(test)[5:-3]
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            for kind in ("CONFIG", "SCRIPTS", "EXTENSIONS", "DATAFILES"):
                env[f"BLENDER_USER_{kind}"] = os.path.join(tmp, "profile", kind.lower())
            out = os.path.join(tmp, "out")
            t0 = time.time()
            run = subprocess.run([blender, "-b", "--factory-startup", "--python-exit-code", "1",
                                  "--python-expr", "import sys; sys.dont_write_bytecode = True",
                                  "--python", test, "--", out],
                                 env=env, capture_output=True, text=True)
        log = run.stdout + run.stderr
        ok = run.returncode == 0
        print(f"{'PASS' if ok else 'FAIL'}  {name:10s} {time.time() - t0:5.0f} s")
        shown = [line for line in log.splitlines()
                 if verbose or line.startswith("FAIL") or "Error" in line or "Traceback" in line]
        for line in shown:
            print("      " + line)
        if not ok:
            failed.append(name)
            if not shown:
                print("\n".join("      " + line for line in log.splitlines()[-30:]))
    print(f"\n{len(tests) - len(failed)} of {len(tests)} passed" + (f"; failed: {', '.join(failed)}" if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
