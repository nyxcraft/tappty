"""Headless smoke test for the pygame draw path.

The GUI is normally "verified by eye, not in CI" (it needs a display). This drives the
*real* renderers -- pygame_ui.run and the compositor -- to completion under the SDL
`dummy` video driver (no window, no display), so every blit/draw/flip path actually
executes in CI wherever pygame is installed. Determinism comes from CastSource: a tiny
recorded session replays instantly, so there's no live subprocess and the final screen
is fixed. The module skips entirely when pygame isn't installed.
"""

import json
import os

# Must be set before pygame initializes a video/audio backend.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pytest

pytest.importorskip("pygame")  # skip the whole module if the gui extra is absent

from tappty import compositor, pygame_ui
from tappty.session import Session
from tappty.source import CastSource
from tappty.terminal import Terminal


def _cast(path):
    """A 3-line asciicast v2 recording; returns its path as a str."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"version": 2, "width": 80, "height": 24}) + "\n")
        # includes non-ASCII to exercise the renderers' lazy Unicode glyph path
        for t, data in [(0.0, "SMOKE TEST ✓\r\n"), (0.01, "row two café\r\n"), (0.02, "done> ")]:
            f.write(json.dumps([t, "o", data]) + "\n")
    return str(path)


def test_pygame_ui_draws_headless(tmp_path):
    """pygame_ui.run executes its full draw loop and renders the recorded screen."""
    cast = _cast(tmp_path / "ui.cast")
    snap = str(tmp_path / "ui_snap")
    sess = Session(Terminal(80, 24), source=CastSource(cast, speed=1000.0))

    # exit_when_done ends it ~1s after the recording finishes; max_seconds is a hard cap
    # so a regression can never hang CI.
    pygame_ui.run(
        sess, None, title="smoke", snapshot_path=snap, exit_when_done=True, fps=20, max_seconds=3
    )

    # the draw loop ran (no exception) and the right data flowed through to the snapshot
    assert os.path.exists(snap) and os.path.exists(snap + ".png")
    text = open(snap, encoding="utf-8").read()
    assert "SMOKE TEST" in text
    assert "row two" in text
    assert os.path.getsize(snap + ".png") > 0


def test_compositor_draws_headless(tmp_path):
    """The compositor tiles + draws two live-backed panels through its full draw path."""
    left = Session(Terminal(80, 24), source=CastSource(_cast(tmp_path / "l.cast"), speed=1000.0))
    right = Session(Terminal(80, 24), source=CastSource(_cast(tmp_path / "r.cast"), speed=1000.0))
    left.start()
    right.start()  # compositor doesn't start sources

    snap = str(tmp_path / "comp_snap")
    panels = [
        compositor.TerminalPanel(compositor.SessionBacking(left), (10, 24, 620, 680), "left"),
        compositor.TerminalPanel(compositor.SessionBacking(right), (650, 24, 620, 680), "right"),
    ]
    compositor.run(
        panels, title="smoke", size=(1280, 720), fps=10, snapshot_path=snap, max_seconds=1
    )

    # run() returned (every panel drew) and a frame was saved
    assert os.path.exists(snap + ".png")
    assert os.path.getsize(snap + ".png") > 0
