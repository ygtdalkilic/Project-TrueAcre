"""Dynamic settings: every deployment-tunable limit is read from its environment variable.

Settings are read when a module is imported, so each check runs in a fresh interpreter.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OVERRIDES = {  # variable -> (value to set, expression that reads it back)
    "TRUEACRE_LOGIN_LIMIT": ("3", "auth.LOGIN_LIMIT.limit"),
    "TRUEACRE_UPLOAD_LIMIT": ("4", "datasets.UPLOAD_LIMIT.limit"),
    "TRUEACRE_EXPLAIN_LIMIT": ("5", "scores.EXPLAIN_LIMIT.limit"),
    "TRUEACRE_USDA_LIMIT": ("6", "usda.IMPORT_LIMIT.limit"),
    "TRUEACRE_MAX_UPLOAD_MB": ("7", "datasets.MAX_UPLOAD_BYTES // (1024 * 1024)"),
    "TRUEACRE_MAX_UPLOAD_ROWS": ("8", "datasets.MAX_ROWS"),
    "TRUEACRE_USDA_TIMEOUT": ("9.5", "usda.TIMEOUT"),
    "TRUEACRE_LLM_TIMEOUT": ("10.5", "explain.TIMEOUT"),
}


def test_limits_read_the_environment():
    probe = ("import json; from api import auth, datasets, scores, usda; from engine import explain; "
             f"print(json.dumps([{', '.join(expr for _, expr in OVERRIDES.values())}]))")
    env = {**os.environ, **{name: value for name, (value, _) in OVERRIDES.items()}}
    out = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == [float(value) for value, _ in OVERRIDES.values()]
