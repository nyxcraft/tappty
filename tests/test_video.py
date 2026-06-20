"""Smoke test for rendering a recording to a video file.

Drives the full path -- replay a tiny `.cast`, rasterize with pygame, pipe to ffmpeg -- and
asserts a non-empty file comes out. Skips without the gui/ansi backends or ffmpeg.
"""

import json
import os

import pytest

pytest.importorskip("pygame")
pytest.importorskip("pyte")

from tappty.video import _ffmpeg_exe, render_video

needs_ffmpeg = pytest.mark.skipif(_ffmpeg_exe() is None, reason="ffmpeg not installed")


def _tiny_cast(path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"version": 2, "width": 20, "height": 4}) + "\n")
        f.write(json.dumps([0.0, "o", "\x1b[31mhello\x1b[0m"]) + "\n")
        f.write(json.dumps([0.3, "o", "\r\nworld"]) + "\n")
    return str(path)


@needs_ffmpeg
def test_render_video_writes_a_file(tmp_path):
    out = tmp_path / "out.mp4"
    render_video(_tiny_cast(tmp_path / "t.cast"), str(out), fps=10, max_seconds=1.0)
    assert out.exists() and out.stat().st_size > 0


@needs_ffmpeg
def test_render_video_crop_and_zoom(tmp_path):
    out = tmp_path / "out.gif"
    render_video(
        _tiny_cast(tmp_path / "t.cast"),
        str(out),
        fps=8,
        max_seconds=1.0,
        crop=(0, 0, 10, 2),
        zoom=2.0,
    )
    assert out.exists() and out.stat().st_size > 0


@needs_ffmpeg
@pytest.mark.skipif(os.name == "nt", reason="hosts the command on a POSIX pty")
def test_render_live_command_to_video(tmp_path):
    # --render with a command (no --play): host it, record it, render it -- one step.
    from tappty import cli

    out = tmp_path / "live.mp4"
    rc = cli.main(["--render", str(out), "--fps", "10", "--", "printf", "hello"])
    assert rc == 0 and out.exists() and out.stat().st_size > 0
