"""The coding examples in examples/ run and exercise the API (headless, core-only).

These are the API teaching examples (vs the runnable showpieces in demos/, smoke-tested in
test_demos_smoke.py). They need no GUI or extras, so they run in the core test job.
"""

import os
import subprocess
import sys

import pytest

EXAMPLES = os.path.join(os.path.dirname(__file__), os.pardir, "examples")


def _run(name):
    return subprocess.run(
        [sys.executable, os.path.join(EXAMPLES, name)],
        capture_output=True, text=True, timeout=30, check=True,
    ).stdout


def test_observe_tap():
    out = _run("observe_tap.py")
    assert "stream" in out and "CLOSED" in out and "hello from the program" in out


def test_custom_source():
    out = _run("custom_source.py")
    assert "one" in out and "two" in out and "three" in out


@pytest.mark.skipif(os.name == "nt", reason="bus_capture uses a Unix-domain socket")
def test_bus_capture():
    out = _run("bus_capture.py")
    assert "HELLO" in out and "NEAT" in out
