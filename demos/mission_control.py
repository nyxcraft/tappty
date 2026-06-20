#!/usr/bin/env python3
"""tappty demo — "mission control": four live sessions tiled in one window.

Shows the compositor. Each tile is its own hosted program (an EngineSource),
running independently; the compositor draws them all and routes input/focus.
Two tiles are reused straight from the other examples (the color chart and the
digital rain), the other two are a live log tail and a clock — all in-process,
no external programs.

    pip install 'tappty[sdl,ansi]'
    python demos/mission_control.py                  # open the window
    python demos/mission_control.py --snapshot m.png # render headless, write m.png
"""

from __future__ import annotations

import argparse
import random
import time

import color_chart  # sibling demo (demos/ is on sys.path when run directly)
import matrix_rain

LOG_LINES = [
    ("\x1b[32m", "INFO ", "accepted connection from 10.0.{}.{}"),
    ("\x1b[32m", "INFO ", "served GET /api/v1/items in {}ms"),
    ("\x1b[36m", "DEBUG", "cache hit for session {}"),
    ("\x1b[33m", "WARN ", "slow query took {}ms"),
    ("\x1b[31m", "ERROR", "upstream {} timed out"),
]


def log_runner(emit, readline):
    """A colored, scrolling log tail."""
    while True:
        color, level, msg = random.choice(LOG_LINES)
        filled = msg.format(*[random.randint(2, 250) for _ in range(msg.count("{}"))])
        emit(f"{color}{level}\x1b[0m  {filled}\r\n")
        time.sleep(0.3)


def clock_runner(emit, readline):
    """A clock plus a couple of sweeping bars."""
    emit("\x1b[2J")
    i = 0
    while True:
        cpu = "█" * (i % 24)
        mem = "█" * ((i * 2) % 24)
        emit("\x1b[H")
        emit(f"\x1b[1m   {time.strftime('%H:%M:%S')}\x1b[0m\r\n\r\n")
        emit(f"   cpu  \x1b[32m{cpu:<24}\x1b[0m\r\n\r\n")
        emit(f"   mem  \x1b[33m{mem:<24}\x1b[0m\r\n")
        i += 1
        time.sleep(0.4)


def build_panels():
    from tappty import PyteTerminal, Session, Terminal, compositor
    from tappty.source import EngineSource

    # Each terminal is sized to what its program draws (the color chart is ~64 wide; the rain
    # runner assumes 80x24); the compositor scales each tile to fit.
    specs = [
        (
            Session(PyteTerminal(64, 22), source=EngineSource(color_chart.runner)),
            (10, 10, 625, 345),
            "color",
        ),
        (
            Session(Terminal(80, 24), source=EngineSource(matrix_rain.runner)),
            (645, 10, 625, 345),
            "rain",
        ),
        (
            Session(PyteTerminal(64, 18), source=EngineSource(log_runner)),
            (10, 365, 625, 345),
            "log",
        ),
        (
            Session(PyteTerminal(40, 12), source=EngineSource(clock_runner)),
            (645, 365, 625, 345),
            "status",
        ),
    ]
    panels = []
    for session, rect, title in specs:
        session.start()  # the compositor draws sessions, it doesn't start them
        panels.append(compositor.TerminalPanel(compositor.SessionBacking(session), rect, title))
    return panels


def main():
    ap = argparse.ArgumentParser(description="tappty compositor 'mission control' demo")
    ap.add_argument("--snapshot", metavar="PNG", help="render headless and write a PNG")
    ap.add_argument("--seconds", type=float, default=2.5, help="snapshot render-time cap")
    args = ap.parse_args()

    if args.snapshot:
        import os

        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

    from tappty import compositor

    panels = build_panels()
    if args.snapshot:
        base = args.snapshot[:-4] if args.snapshot.endswith(".png") else args.snapshot
        compositor.run(
            panels,
            title="tappty mission control",
            size=(1280, 720),
            snapshot_path=base,
            max_seconds=args.seconds,
        )
    else:
        compositor.run(panels, title="tappty mission control", size=(1280, 720))


if __name__ == "__main__":
    main()
