#!/usr/bin/env python3
"""tappty demo -- a *program* driving a real terminal app (vim).

No human touches the keyboard. An "autopilot" controller holds tappty's talking stick and types
into a live `vim` over the *control* tap, while every renderer/observer watches the same session
over the *observe* tap. That is the whole point of tappty -- observe **and** control -- made
obvious: text appears as if typed by a ghost, then ex-commands run and the cursor jumps around.

The autopilot here is an in-process thread for simplicity, but it only calls `send_input` -- the
exact same control primitive the bus relays for a *remote* bot, so this is faithfully "another
program driving the terminal." Because the autopilot registered as an `ai` controller, a human
watching in the GUI can just press a key to **take the stick** and drive vim themselves (the
arbitration in `Session.take`); the autopilot is then locked out until it's free again.

    pip install 'tappty[sdl,ansi]'
    python demos/drive_vim.py                  # watch the autopilot drive vim in a window
    python demos/drive_vim.py --snapshot r.png # render a frame headless, write r.png

Needs `vim` (or `vi`) on PATH.
"""
from __future__ import annotations

import argparse
import os
import shutil
import threading
import time

COLS, ROWS = 80, 24

# (seconds to pause first, keystrokes to send). \x1b = Esc, \r = Enter. Sent raw to vim over the
# control tap, exactly as a keyboard would -- vim does its own echo and editing.
SCRIPT = [
    (1.4, "i"),                                              # enter insert mode
    (0.5, "tappty is driving this vim session.\r"),
    (0.5, "No human is at the keyboard;\r"),
    (0.5, "every keystroke arrives over the control tap.\r"),
    (0.8, "\x1b"),                                           # back to normal mode
    (0.8, ":set number\r"),                                  # show line numbers
    (0.9, "gg"),                                             # jump to the top
    (0.7, "yyp"),                                            # duplicate the first line
    (0.9, "G"),                                              # jump to the bottom
    (0.6, "o"),                                              # open a new line below
    (0.4, "-- fin.\x1b"),                                    # type, back to normal
    (1.3, ":q!\r"),                                          # quit, discarding the buffer
]


def vim_argv():
    """vim with no config / swap / viminfo, so the demo is predictable on any box."""
    vim = shutil.which("vim") or shutil.which("vi")
    return [vim, "-u", "NONE", "-N", "-n", "-i", "NONE"] if vim else None


def build_session(cols=COLS, rows=ROWS):
    """A Session hosting vim on a pty, full-ANSI backend, raw keys, with the autopilot holding the
    stick. Shared with the docs tooling so the recorded cast/video come from this same setup."""
    from tappty import Session
    from tappty.pyte_terminal import PyteTerminal
    from tappty.source import PtySource

    argv = vim_argv()
    if argv is None:
        raise SystemExit("drive_vim needs vim (or vi) on PATH -- install it and retry")
    env = {**os.environ, "TERM": "xterm-256color"}  # so vim emits ANSI pyte understands
    sess = Session(PyteTerminal(cols, rows), source=PtySource(argv, size=(rows, cols), env=env))
    sess.raw_keys = True                       # full-TUI: keystrokes go straight to vim
    sess.claim_control("autopilot", "ai")      # the "other program" takes the talking stick
    return sess


def drive(sess, script=SCRIPT):
    """Type the scripted keystrokes into the hosted app over the control tap."""
    for pause, keys in script:
        time.sleep(pause)
        sess.send_input(keys, by="autopilot")  # stick-gated; applies while autopilot drives


def main():
    ap = argparse.ArgumentParser(description="tappty demo: a program driving vim")
    ap.add_argument("--snapshot", metavar="PNG", help="render headless and write a PNG")
    ap.add_argument("--seconds", type=float, default=5.0, help="snapshot render-time cap")
    args = ap.parse_args()

    if args.snapshot:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

    sess = build_session()
    from tappty import pygame_ui

    # The autopilot drives from its own thread while the renderer paints the live screen.
    threading.Thread(target=drive, args=(sess,), daemon=True).start()
    if args.snapshot:
        base = args.snapshot[:-4] if args.snapshot.endswith(".png") else args.snapshot
        pygame_ui.run(sess, None, title="tappty :: driving vim", snapshot_path=base,
                      max_seconds=args.seconds, exit_when_done=True)
    else:
        pygame_ui.run(sess, None, title="tappty :: driving vim", exit_when_done=True)


if __name__ == "__main__":
    main()
