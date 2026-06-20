"""Smoke test for the bundled demos in demos/.

Each demo takes `--snapshot PATH --seconds N`, rendering headless under the SDL dummy
driver and writing a PNG. We run each in a subprocess and assert it produces a non-empty
PNG -- so the demos in the docs gallery can't silently rot when the API changes. Skips
when the gui/ansi backends aren't installed (same as the other GUI smoke tests).
"""

import os
import shutil
import subprocess
import sys

import pytest

pytest.importorskip("pygame")  # skip the whole module without the gui extra

DEMOS = os.path.join(os.path.dirname(__file__), os.pardir, "demos")
ENV = {
    **os.environ,
    "SDL_VIDEODRIVER": "dummy",
    "SDL_AUDIODRIVER": "dummy",
    "PYGAME_HIDE_SUPPORT_PROMPT": "1",
}


@pytest.mark.parametrize(
    "script, needs_pyte, needs_vim",
    [
        ("color_chart.py", True, False),
        ("matrix_rain.py", False, False),
        ("mission_control.py", True, False),
        ("drive_vim.py", True, True),
    ],
)
def test_demo_renders_a_png_headless(tmp_path, script, needs_pyte, needs_vim):
    if needs_pyte:
        pytest.importorskip("pyte")  # color demos need the full-ANSI backend
    if needs_vim and not (shutil.which("vim") or shutil.which("vi")):
        pytest.skip("drive_vim needs vim/vi on PATH")
    out = tmp_path / (script + ".png")
    subprocess.run(
        [sys.executable, os.path.join(DEMOS, script), "--snapshot", str(out), "--seconds", "1"],
        check=True,
        timeout=90,
        env=ENV,
    )
    assert out.exists() and out.stat().st_size > 0


def test_web_demo_screenshots_a_browser(tmp_path):
    # web_demo serves the web renderer and drives a real headless browser to screenshot it.
    pytest.importorskip("pyte")
    pytest.importorskip("websockets")
    pytest.importorskip("playwright")
    try:  # skip cleanly where Chromium isn't installed/launchable (e.g. bare CI)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            p.chromium.launch(args=["--no-sandbox"]).close()
    except Exception as e:
        pytest.skip(f"chromium not launchable: {e}")
    out = tmp_path / "web.png"
    subprocess.run(
        [sys.executable, os.path.join(DEMOS, "web_demo.py"), "--shot", str(out), "--port", "8771"],
        check=True,
        timeout=120,
        env=ENV,
    )
    assert out.exists() and out.stat().st_size > 0
