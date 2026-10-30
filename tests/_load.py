"""Load a script from a skill folder (the folder names have hyphens), and run one as a CLI."""

import importlib.util
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")


def load(folder, name):
    path = os.path.join(ROOT, folder, name + ".py")
    spec = importlib.util.spec_from_file_location("nse_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(folder, name, args, cwd):
    """(exit code, stdout, stderr) of python3 <skill>/<name>.py args, run in cwd."""
    # Behave like Windows, where a pipe's default encoding (cp1252) has no rupee sign: each tool
    # must switch its own output to UTF-8. PYTHONSAFEPATH keeps the working folder off sys.path.
    env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONSAFEPATH="1")
    p = subprocess.run([sys.executable, "-s", os.path.join(ROOT, folder, name + ".py")] + list(args),
                       cwd=cwd, capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)
    return p.returncode, p.stdout, p.stderr
