"""Smoke test for the arcade draw path.

Like the pygame smoke test, this drives the *real* renderer -- arcade_ui.run -- to
completion via its max_seconds/exit_when_done cap, so every draw/snapshot path executes.
Determinism comes from CastSource: a tiny recorded session replays instantly, so there is
no live subprocess and the final screen is fixed.

Unlike pygame's pure-software SDL `dummy` driver, arcade needs a real OpenGL context (a
display, or headless EGL). So the module skips when arcade is absent, and each test skips
when no GL context can be created -- it never fails for lack of a display.
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


def _cast(path):
    """A 3-line asciicast v2 recording; returns its path as a str."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"version": 2, "width": 80, "height": 24}) + "\n")
        # includes non-ASCII to exercise the renderer's Unicode glyph path
        for t, data in [(0.0, "SMOKE TEST ✓\r\n"), (0.01, "row two café\r\n"), (0.02, "done> ")]:
            f.write(json.dumps([t, "o", data]) + "\n")
    return str(path)


def test_arcade_ui_draws(tmp_path):
    """arcade_ui.run executes its full draw loop and renders the recorded screen."""
    if not _gl_available():
        pytest.skip("no GL context (needs a display or headless EGL)")

    from tappty import arcade_ui
    from tappty.session import Session
    from tappty.source import CastSource
    from tappty.terminal import Terminal

    cast = _cast(tmp_path / "ui.cast")
    snap = str(tmp_path / "ui_snap")
    sess = Session(Terminal(80, 24), source=CastSource(cast, speed=1000.0))

    # exit_when_done ends it ~1s after the recording finishes; max_seconds is a hard cap so
    # a regression can never hang the suite.
    arcade_ui.run(
        sess, None, title="smoke", snapshot_path=snap, exit_when_done=True, fps=20, max_seconds=3
    )

    # the draw loop ran (no exception) and the right data flowed through to the snapshot
    assert os.path.exists(snap) and os.path.exists(snap + ".png")
    text = open(snap, encoding="utf-8").read()
    assert "SMOKE TEST" in text
    assert "row two" in text
    assert os.path.getsize(snap + ".png") > 0
