#!/usr/bin/env python3
"""tappty demo — green-phosphor "digital rain".

A tiny in-process animation (an EngineSource) drawn on the dependency-free VT52
`Terminal`: columns of half-width katakana fall down the screen. It needs no
external program and no color backend — just the phosphor green the terminal
already renders.

    pip install 'tappty[sdl]'
    python demos/matrix_rain.py                  # open the window (Ctrl-] to quit)
    python demos/matrix_rain.py --snapshot r.png # render a frame headless, write r.png
"""
from __future__ import annotations

import argparse
import random
import time

# ASCII glyphs only, so every cell renders in the default monospace font (no missing-glyph
# boxes) and every column stays one cell wide.
GLYPHS = "0123456789ABCDEFGHJKLMNPQRSTUVWXYZ#@%&*+=<>:.|/"
TRAIL = 9


def runner(emit, readline, cols=80, rows=24):
    """Forever: advance each column's drop and repaint the screen in place."""
    drops = [random.randint(-rows, 0) for _ in range(cols)]
    while True:
        grid = [[" "] * cols for _ in range(rows)]
        for x in range(cols):
            head = drops[x]
            for t in range(TRAIL):
                y = head - t
                if 0 <= y < rows:
                    grid[y][x] = random.choice(GLYPHS)
            drops[x] += 1
            if drops[x] - TRAIL > rows:
                drops[x] = random.randint(-rows, 0)
        # VT52 cursor-address each row (ESC Y row col), so the full-width rows don't
        # trip auto-wrap into spurious newlines.
        frame = "".join(
            "\x1bY" + chr(32 + y) + chr(32) + "".join(grid[y]) for y in range(rows)
        )
        emit(frame)
        time.sleep(0.07)


def main():
    ap = argparse.ArgumentParser(description="tappty phosphor digital-rain demo")
    ap.add_argument("--snapshot", metavar="PNG", help="render headless and write a PNG")
    ap.add_argument("--seconds", type=float, default=2.0, help="snapshot render-time cap")
    args = ap.parse_args()

    if args.snapshot:
        import os

        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

    from tappty import Session, Terminal, pygame_ui
    from tappty.source import EngineSource

    session = Session(Terminal(80, 24), source=EngineSource(runner))
    if args.snapshot:
        base = args.snapshot[:-4] if args.snapshot.endswith(".png") else args.snapshot
        pygame_ui.run(session, None, title="tappty digital rain",
                      snapshot_path=base, max_seconds=args.seconds)
    else:
        pygame_ui.run(session, None, title="tappty digital rain")


if __name__ == "__main__":
    main()
