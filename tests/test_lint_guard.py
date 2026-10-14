"""Pyflakes errors that are always runtime bugs fail the suite, not just the linter.

2026-10-14: a function-local import below an earlier use made `offensive_weights`
local to the whole function, so the prospective engine report raised
UnboundLocalError on its first graded row and every later step of the task
(ESPN freezes, trending, win-probability capture) stopped. ruff's F823 flagged
it, but among ~800 style warnings nobody saw it.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_no_undefined_names_or_locals_used_before_assignment():
    ruff = shutil.which("ruff") or str(Path(sys.executable).with_name("ruff"))
    if not Path(ruff).exists():
        pytest.skip("ruff not installed")
    result = subprocess.run([ruff, "check", "--select", "F821,F823", "--output-format", "concise", "src", "config", "scripts"],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout
