#!/usr/bin/env python3
"""tappty demo — an ANSI color & SGR-attribute chart.

Hosts a tiny in-process program (an EngineSource) that prints a color and
attribute chart, so you can watch tappty render SGR. No external program needed.

    pip install 'tappty[gui,ansi]'
    python demos/color_chart.py                  # open the green-phosphor window
    python demos/color_chart.py --snapshot c.png # render headless, write c.png instead
"""
from __future__ import annotations

import argparse

CSI = "\x1b["


def runner(emit, readline):
    """An EngineSource program: print the chart, then wait for a keypress."""
    emit(CSI + "2J" + CSI + "H")
    emit("  tappty — SGR color & attributes\r\n\r\n")

    emit("  foreground   ")
    for c in range(8):
        emit(f"{CSI}3{c}m ██ {CSI}0m")
    emit("\r\n  (bold)       ")
    for c in range(8):
        emit(f"{CSI}1;3{c}m ██ {CSI}0m")
    emit("\r\n\r\n")

    emit("  background   ")
    for c in range(8):
        emit(f"{CSI}4{c}m    {CSI}0m")
    emit("\r\n\r\n")

    emit("  attributes   ")
    emit(f"{CSI}1mbold{CSI}0m  {CSI}3mitalic{CSI}0m  {CSI}4munderline{CSI}0m  ")
    emit(f"{CSI}9mstrike{CSI}0m  {CSI}5mblink{CSI}0m  {CSI}7m reverse {CSI}0m\r\n\r\n")

    emit("  256-color    ")
    for i in range(16, 16 + 42):  # a slice of the 6x6x6 cube
        emit(f"{CSI}48;5;{i}m {CSI}0m")
    emit("\r\n\r\n")

    emit("  Uncolored text stays phosphor green — color appears only\r\n")
    emit("  where the program asks for it.\r\n\r\n  press a key to exit › ")
    readline()


def main():
    ap = argparse.ArgumentParser(description="tappty color/SGR chart demo")
    ap.add_argument("--snapshot", metavar="PNG", help="render headless and write a PNG")
    ap.add_argument("--seconds", type=float, default=2.0, help="snapshot render-time cap")
    args = ap.parse_args()

    if args.snapshot:  # must precede the pygame import
        import os

        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

    from tappty import Session, pygame_ui
    from tappty.pyte_terminal import PyteTerminal
    from tappty.source import EngineSource

    session = Session(PyteTerminal(64, 22), source=EngineSource(runner))
    if args.snapshot:
        base = args.snapshot[:-4] if args.snapshot.endswith(".png") else args.snapshot
        pygame_ui.run(session, None, title="tappty color chart",
                      snapshot_path=base, max_seconds=args.seconds)
    else:
        pygame_ui.run(session, None, title="tappty color chart")


if __name__ == "__main__":
    main()
