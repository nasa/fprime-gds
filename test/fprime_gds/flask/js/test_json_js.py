"""test_json_js.py:

Runs the Node-based unit tests for the GDS frontend SaferParser (flask/static/js/json.js) under pytest.

@author mstarch
"""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not available")
def test_safer_parser_js():
    """Run the node --test suite for json.js and assert it passes"""
    test_file = Path(__file__).parent / "json.test.mjs"
    result = subprocess.run(
        ["node", "--test", str(test_file)], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, f"node --test failed:\n{result.stdout}\n{result.stderr}"
