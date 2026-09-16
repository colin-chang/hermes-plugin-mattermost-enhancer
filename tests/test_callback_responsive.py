"""Pytest wrapper for the isolated callback responsiveness regression harness."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_callback_responsive_regression():
    script = Path(__file__).with_name("callback_responsive_check.py")
    result = subprocess.run([sys.executable, str(script)], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
