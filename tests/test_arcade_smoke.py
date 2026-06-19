"""Smoke test for the arcade draw path.

Like the pygame smoke test, this drives the *real* renderer -- arcade_ui.run -- to
completion via its max_seconds/exit_when_done cap, so every draw/snapshot path executes.
Determinism comes from CastSource: a tiny recorded session replays instantly, so there is
no live subprocess and the final screen is fixed.

Two arcade-specific constraints shape this as a *single* test:
  * arcade needs a real OpenGL context (a display, or headless EGL), unlike pygame's
    pure-software SDL `dummy` driver -- so it skips when no GL context can be created.
  * pyglet's global event loop does not cleanly re-run, so `arcade.run()` is called once
    per process. The recording therefore mixes default (phosphor) cells with SGR
    color/bold/reverse/background, exercising the plain *and* color run-length paths in one
    window. (The default-vs-color logic itself is unit-tested in test_style / test_term /
    test_pyte_terminal without a display.)
"""

import json
import os

import pytest

pytest.importorskip("arcade")  # skip the whole module without the arcade extra


def _gl_available():
    """True if a GL context/window can be created here (a display or headless EGL)."""
    import pyglet

    pyglet.options["audio"] = ("silent",)  # don't block on an absent sound server
    import arcade

    try:
        w = arcade.Window(120, 80, "probe")
        w.close()
        return True
    except Exception:
        return False


def test_arcade_ui_draws(tmp_path):
    """arcade_ui.run executes its full draw loop -- including the SGR color run-length path --
    and renders the recorded screen."""
    if not _gl_available():
        pytest.skip("no GL context (needs a display or headless EGL)")
    pytest.importorskip("pyte")  # SGR color needs the full-ANSI backend

    from tappty import arcade_ui
    from tappty.pyte_terminal import PyteTerminal
    from tappty.session import Session
    from tappty.source import CastSource

    cast = tmp_path / "ui.cast"
    # default (phosphor) cells + SGR color/bold/reverse/background + non-ASCII
    line1 = "SMOKE ✓ \x1b[31mRED\x1b[0m \x1b[1;32mGREEN\x1b[0m\r\n"
    line2 = "\x1b[7mREV\x1b[0m \x1b[44mBLUEBG\x1b[0m café done> "
    with open(cast, "w", encoding="utf-8") as f:
        f.write(json.dumps({"version": 2, "width": 80, "height": 24}) + "\n")
        f.write(json.dumps([0.0, "o", line1]) + "\n")
        f.write(json.dumps([0.01, "o", line2]) + "\n")
    snap = str(tmp_path / "ui_snap")
    sess = Session(PyteTerminal(80, 24), source=CastSource(str(cast), speed=1000.0))

    # exit_when_done ends it ~1s after the recording finishes; max_seconds is a hard cap so a
    # regression can never hang the suite.
    arcade_ui.run(
        sess, None, title="smoke", snapshot_path=snap, exit_when_done=True, fps=20, max_seconds=3
    )

    # the draw loop ran (no exception) and the right data flowed through to the snapshot
    assert os.path.exists(snap) and os.path.exists(snap + ".png")
    text = open(snap, encoding="utf-8").read()
    assert "SMOKE" in text and "RED" in text and "GREEN" in text and "BLUEBG" in text
    assert os.path.getsize(snap + ".png") > 0
