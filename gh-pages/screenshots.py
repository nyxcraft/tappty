#!/usr/bin/env python3
"""Regenerate the documentation gallery images by running the examples headless.

Each example takes `--snapshot PATH`, which renders with the SDL dummy driver and writes a PNG
instead of opening a window. We run each in its own subprocess (so a demo's animation thread
can't linger between shots) and drop the byproduct text dump, leaving just docs/media/<name>.png.
These PNGs are committed; the Pages build only copies them.

    pip install 'tappty[gui,ansi]'
    python gh-pages/screenshots.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "docs" / "media"

# (example file, output PNG stem, seconds to render before the snapshot)
SHOTS = [
    ("color_chart.py", "color_chart", 2.0),
    ("matrix_rain.py", "matrix_rain", 2.0),
    ("mission_control.py", "mission_control", 2.5),
]


def main() -> int:
    MEDIA.mkdir(parents=True, exist_ok=True)
    for script, stem, seconds in SHOTS:
        out = MEDIA / f"{stem}.png"
        print(f"rendering {script} -> {out.relative_to(ROOT)}")
        subprocess.run(
            [sys.executable, str(ROOT / "examples" / script),
             "--snapshot", str(out), "--seconds", str(seconds)],
            check=True,
        )
        byproduct = MEDIA / stem  # pygame_ui writes a text screen-dump beside the PNG
        if byproduct.exists():
            byproduct.unlink()
    print(f"done -> {MEDIA.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
