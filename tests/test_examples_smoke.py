"""Smoke test for the bundled demos in examples/.

Each example takes `--snapshot PATH --seconds N`, rendering headless under the SDL dummy
driver and writing a PNG. We run each in a subprocess and assert it produces a non-empty
PNG -- so the demos in the docs gallery can't silently rot when the API changes. Skips
when the gui/ansi backends aren't installed (same as the other GUI smoke tests).
"""

import os
import subprocess
import sys

import pytest

pytest.importorskip("pygame")  # skip the whole module without the gui extra

EXAMPLES = os.path.join(os.path.dirname(__file__), os.pardir, "examples")
ENV = {**os.environ, "SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy",
       "PYGAME_HIDE_SUPPORT_PROMPT": "1"}


@pytest.mark.parametrize(
    "script, needs_pyte",
    [("color_chart.py", True), ("matrix_rain.py", False), ("mission_control.py", True)],
)
def test_example_renders_a_png_headless(tmp_path, script, needs_pyte):
    if needs_pyte:
        pytest.importorskip("pyte")  # color demos need the full-ANSI backend
    out = tmp_path / (script + ".png")
    subprocess.run(
        [sys.executable, os.path.join(EXAMPLES, script),
         "--snapshot", str(out), "--seconds", "1"],
        check=True, timeout=90, env=ENV,
    )
    assert out.exists() and out.stat().st_size > 0
