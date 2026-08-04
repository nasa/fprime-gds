"""test_json_js.py:

Runs the Node-based unit tests for the GDS frontend SaferParser (flask/static/js/json.js) under pytest.

@author mstarch
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _node_major():
    """Return the major version of node on PATH, or 0 when node is unavailable or unusable"""
    if shutil.which("node") is None:
        return 0
    try:
        version = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=30).stdout
        return int(version.strip().lstrip("v").split(".")[0])
    except (ValueError, OSError, subprocess.SubprocessError):
        return 0


# GitHub Actions sets CI=true; treat only explicit affirmative values as CI
IS_CI = os.environ.get("CI", "").lower() in ("true", "1")


# Skip locally without a suitable node, but fail on CI so the JS suite cannot silently stop running
@pytest.mark.skipif(_node_major() < 18 and not IS_CI, reason="node >= 18 with node:test is required")
def test_safer_parser_js():
    """Run the node --test suite for json.js and assert it passes"""
    assert _node_major() >= 18, "node >= 18 is required on CI runners"
    test_file = Path(__file__).parent / "json.test.mjs"
    result = subprocess.run(
        ["node", "--test", str(test_file)], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, f"node --test failed:\n{result.stdout}\n{result.stderr}"
