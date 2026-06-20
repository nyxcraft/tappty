#!/usr/bin/env python3
"""Regenerate the documentation gallery images.

Two kinds of shot, all rendered headless under the SDL dummy driver and written to
docs/media/<name>.png (which are committed; the Pages build only copies them):

  * the in-process demos (demos/*.py --snapshot), and
  * the bundled recordings (demos/recordings/*.cast) replayed via `tapterm --play` -- so the
    shots of real programs (nyancat, cbonsai) regenerate from the committed casts, with the
    programs themselves NOT required.

It also renders the gallery's "in motion" clip (docs/media/nyancat.mp4) straight from a cast via
`tapterm --render` (needs the `video` extra or a system ffmpeg).

Each runs in its own subprocess; the byproduct text dump beside the PNG is removed.

    pip install 'tappty[gui,ansi,video]'
    python gh-pages/screenshots.py
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "docs" / "media"
ENV = {**os.environ, "SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy",
       "PYGAME_HIDE_SUPPORT_PROMPT": "1"}


def _have(mod):
    return importlib.util.find_spec(mod) is not None

# (example file, PNG stem, seconds to render before the snapshot)
SHOTS = [
    ("color_chart.py", "color_chart", 2.0),
    ("matrix_rain.py", "matrix_rain", 2.0),
    ("mission_control.py", "mission_control", 2.5),
]
if shutil.which("vim") or shutil.which("vi"):  # drive_vim's still is captured live; needs vim
    SHOTS.append(("drive_vim.py", "drive_vim", 5.0))

# (recording under demos/recordings/, PNG stem) -- replayed to a frame via the CLI
CAST_SHOTS = [
    ("nyancat.cast", "nyancat"),
    ("cbonsai.cast", "cbonsai"),
]

# (recording, movie file, fps, zoom) -- ANSI recordings rendered to a clip via the CLI. nyancat
# becomes an animated GIF so the gallery's "in motion" clip moves on the docs site AND on GitHub
# (which renders <img> but strips <video>).
MOVIES = [
    ("nyancat.cast", "nyancat.gif", 12, 0.5),
    ("drive_vim.cast", "drive_vim.mp4", 12, 0.6),  # the bundled cast replays without vim
]


def _drop_byproduct(stem):
    byproduct = MEDIA / stem  # pygame_ui writes a text screen-dump beside the PNG
    if byproduct.exists():
        byproduct.unlink()


def _render_matrix_movie(out="matrix.mp4", seconds=5.0, fps=15, zoom=0.5):
    """The digital-rain demo speaks VT52 on the dependency-free Terminal, which pyte (the default
    render backend) can't replay. So record the live demo to a throwaway cast, then render it
    through the VT52 backend (`terminal=Terminal`). Each run is a fresh, random rain."""
    import sys
    import tempfile
    import time

    from tappty import Recorder, Session, Terminal, render_video
    from tappty.source import EngineSource

    sys.path.insert(0, str(ROOT / "demos"))
    from matrix_rain import runner

    fd, tmp = tempfile.mkstemp(suffix=".cast")
    os.close(fd)
    try:
        sess = Session(Terminal(80, 24), source=EngineSource(runner))
        rec = Recorder(sess, tmp)
        rec.start()
        sess.run_in_thread()
        time.sleep(seconds)
        rec.close()  # stop recording before stop()'s join, so it doesn't over-record
        sess.stop()
        render_video(tmp, str(MEDIA / out), fps=fps, zoom=zoom, tail=0.3, terminal=Terminal)
    finally:
        os.remove(tmp)


def main() -> int:
    MEDIA.mkdir(parents=True, exist_ok=True)
    for script, stem, seconds in SHOTS:
        print(f"rendering {script} -> docs/media/{stem}.png")
        subprocess.run(
            [sys.executable, str(ROOT / "demos" / script),
             "--snapshot", str(MEDIA / f"{stem}.png"), "--seconds", str(seconds)],
            check=True, env=ENV,
        )
        _drop_byproduct(stem)
    for cast, stem in CAST_SHOTS:
        print(f"replaying {cast} -> docs/media/{stem}.png")
        subprocess.run(
            [sys.executable, "-m", "tappty.cli", "--play",
             str(ROOT / "demos" / "recordings" / cast),
             "--gui", "--exit-when-done", "--snapshot", str(MEDIA / stem)],
            check=True, env=ENV,
        )
        _drop_byproduct(stem)
    for cast, movie, fps, zoom in MOVIES:
        print(f"rendering {cast} -> docs/media/{movie}")
        subprocess.run(
            [sys.executable, "-m", "tappty.cli", "--play",
             str(ROOT / "demos" / "recordings" / cast),
             "--render", str(MEDIA / movie), "--fps", str(fps), "--zoom", str(zoom)],
            check=True, env=ENV,
        )
    print("rendering digital-rain demo -> docs/media/matrix.mp4")
    _render_matrix_movie()
    if _have("playwright") and _have("websockets") and _have("pyte"):
        print("screenshotting the web renderer in a browser -> docs/media/web_demo.png")
        subprocess.run(
            [sys.executable, str(ROOT / "demos" / "web_demo.py"),
             "--shot", str(MEDIA / "web_demo.png")],
            check=True, env=ENV,
        )
    else:
        print("skipping web_demo.png (needs playwright + the web/ansi extras)")
    print(f"done -> {MEDIA.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
