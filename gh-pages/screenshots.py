#!/usr/bin/env python3
"""Regenerate the documentation gallery images.

Two kinds of shot, all rendered headless under the SDL dummy driver and written to
docs/media/<name>.png (which are committed; the Pages build only copies them):

  * the in-process examples (examples/*.py --snapshot), and
  * the bundled recordings (examples/recordings/*.cast) replayed via `tapterm --play` -- so the
    shots of real programs (nyancat, cbonsai) regenerate from the committed casts, with the
    programs themselves NOT required.

Each runs in its own subprocess; the byproduct text dump beside the PNG is removed.

    pip install 'tappty[gui,ansi]'
    python gh-pages/screenshots.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "docs" / "media"
ENV = {**os.environ, "SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy",
       "PYGAME_HIDE_SUPPORT_PROMPT": "1"}

# (example file, PNG stem, seconds to render before the snapshot)
SHOTS = [
    ("color_chart.py", "color_chart", 2.0),
    ("matrix_rain.py", "matrix_rain", 2.0),
    ("mission_control.py", "mission_control", 2.5),
]

# (recording under examples/recordings/, PNG stem) -- replayed to a frame via the CLI
CAST_SHOTS = [
    ("nyancat.cast", "nyancat"),
    ("cbonsai.cast", "cbonsai"),
]


def _drop_byproduct(stem):
    byproduct = MEDIA / stem  # pygame_ui writes a text screen-dump beside the PNG
    if byproduct.exists():
        byproduct.unlink()


def main() -> int:
    MEDIA.mkdir(parents=True, exist_ok=True)
    for script, stem, seconds in SHOTS:
        print(f"rendering {script} -> docs/media/{stem}.png")
        subprocess.run(
            [sys.executable, str(ROOT / "examples" / script),
             "--snapshot", str(MEDIA / f"{stem}.png"), "--seconds", str(seconds)],
            check=True, env=ENV,
        )
        _drop_byproduct(stem)
    for cast, stem in CAST_SHOTS:
        print(f"replaying {cast} -> docs/media/{stem}.png")
        subprocess.run(
            [sys.executable, "-m", "tappty.cli", "--play",
             str(ROOT / "examples" / "recordings" / cast),
             "--gui", "--exit-when-done", "--snapshot", str(MEDIA / stem)],
            check=True, env=ENV,
        )
        _drop_byproduct(stem)
    print(f"done -> {MEDIA.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
