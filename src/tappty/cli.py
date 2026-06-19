"""tapterm -- host a program on a pseudo-terminal and render it in a terminal UI.

    tapterm                      # host your $SHELL (GUI if pygame is installed, else CUI)
    tapterm -- python3 -i        # host a specific command (everything after -- is argv)
    tapterm --cui -- bash        # force the curses character UI (this terminal)
    tapterm --gui -- bash        # force the pygame green-phosphor window
    tapterm --headless -- ls     # run to completion, print the final screen (scripting)

tapterm is a thin front-end over tappty: it wraps the command in a PtySource, hosts it
in a Session (the observe/control core), and hands the Session to a renderer. The CUI
(curses) works anywhere; the GUI (pygame) needs the optional 'gui' extra.
"""

import argparse
import importlib.util
import os
import sys

from tappty.session import Session
from tappty.source import PtySource
from tappty.terminal import Terminal


def _have_pygame():
    return importlib.util.find_spec("pygame") is not None


def _have_pyte():
    return importlib.util.find_spec("pyte") is not None


def _default_mode():
    """GUI when pygame is installed (the showcase), else the always-available CUI."""
    return "gui" if _have_pygame() else "cui"


def _make_terminal(ap, ansi, cols, rows):
    """The VT52 Terminal, or the full-ANSI PyteTerminal when --ansi is given."""
    if ansi:
        if not _have_pyte():
            ap.error(
                "the full-ANSI backend (--ansi, and required for the Windows ConPTY "
                "path) needs pyte: install it with  pip install 'tappty[ansi]'"
            )
        from tappty.pyte_terminal import PyteTerminal

        return PyteTerminal(cols=cols, rows=rows)
    return Terminal(cols=cols, rows=rows)


def _make_source(no_pty, cmd, rows, cols):
    """Pick how to host the command: plain pipes (--no-pty, cross-platform), a ConPTY on
    Windows, or a real pty on POSIX."""
    if no_pty:
        from tappty.source import PipeSource

        return PipeSource(cmd)
    if os.name == "nt":  # Windows pseudo-console
        from tappty.source import ConPtySource

        return ConPtySource(cmd, size=(rows, cols))
    return PtySource(cmd, size=(rows, cols))


def build_parser():
    ap = argparse.ArgumentParser(
        prog="tapterm",
        description="Host a program on a pseudo-terminal and render it (CUI or GUI).",
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--cui",
        dest="mode",
        action="store_const",
        const="cui",
        help="curses character UI, in the current terminal",
    )
    mode.add_argument(
        "--gui",
        dest="mode",
        action="store_const",
        const="gui",
        help="pygame green-phosphor window (needs the 'gui' extra)",
    )
    mode.add_argument(
        "--headless",
        dest="mode",
        action="store_const",
        const="headless",
        help="run to completion, print the final screen, then exit",
    )
    ap.add_argument("--title", default=None, help="window / status-line title")
    ap.add_argument("--cols", type=int, default=80, help="terminal columns (default 80)")
    ap.add_argument("--rows", type=int, default=24, help="terminal rows (default 24)")
    ap.add_argument(
        "--snapshot",
        default=None,
        help="GUI: mirror the screen to this text file each second; "
        "headless: write the final screen here",
    )
    ap.add_argument(
        "--exit-when-done",
        action="store_true",
        help="GUI: close the window when the hosted program exits",
    )
    ap.add_argument(
        "--cast",
        default=None,
        help="replay an asciinema .cast recording instead of hosting a command "
        "(sizes the terminal to the recording)",
    )
    ap.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="--cast: replay speed multiplier (default 1.0; e.g. 2 = twice as fast)",
    )
    ap.add_argument(
        "--loop",
        action="store_true",
        help="--cast: loop the recording (GUI/CUI; ignored when --headless)",
    )
    ap.add_argument(
        "--ansi",
        action="store_true",
        help="use the full-ANSI/VT100+ terminal backend (needs the 'ansi' extra: "
        "pyte) instead of the built-in VT52 model -- for programs that emit "
        "modern ANSI (color, cursor addressing); required to host most "
        "Windows console programs faithfully",
    )
    ap.add_argument(
        "--no-pty",
        dest="no_pty",
        action="store_true",
        help="host the command over plain pipes instead of a pseudo-terminal "
        "(cross-platform incl. Windows; no tty, best for line-oriented "
        "programs). Default uses a pty -- ConPTY on Windows",
    )
    ap.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="the program to host (prefix with --), e.g. tapterm -- bash",
    )
    return ap


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)

    mode = a.mode or _default_mode()

    # ConPTY (the default Windows pty path) emits VT100+, which the VT52 grid renders as
    # escape soup -- so force the full-ANSI backend whenever that path is in play.
    ansi = a.ansi or (os.name == "nt" and not a.no_pty and not a.cast)

    if a.cast:  # replay a recording instead of hosting a command
        from tappty.source import CastSource

        src = CastSource(a.cast, speed=a.speed, loop=a.loop and mode != "headless")
        term = _make_terminal(ap, ansi, src.width, src.height)  # size to the recording
        sess = Session(term, source=src)
        title = a.title or ("tapterm :: cast:" + os.path.basename(a.cast))
    else:
        cmd = a.command
        if cmd and cmd[0] == "--":  # the conventional argv separator
            cmd = cmd[1:]
        if not cmd:  # no command -> behave like a terminal: host a shell
            cmd = [os.environ.get("SHELL", "/bin/sh")]
        term = _make_terminal(ap, ansi, a.cols, a.rows)
        sess = Session(term)
        sess.source = _make_source(a.no_pty, cmd, a.rows, a.cols)
        title = a.title or ("tapterm :: " + os.path.basename(cmd[0]))

    if mode == "headless":
        sess.run_blocking()  # runs until the hosted program exits (EOF on pty)
        out = term.snapshot()
        if a.snapshot:
            with open(a.snapshot, "w") as f:
                f.write(out)
        print(out)
        return 0

    sess.claim_control("local", "human")  # a human is at the keyboard -> default driver
    if mode == "cui":
        from tappty import curses_ui

        curses_ui.run(sess, None, title=title)
    else:  # gui
        if not _have_pygame():
            ap.error(
                "--gui needs pygame: install it with  pip install 'tappty[gui]'  "
                "(or run with --cui)"
            )
        from tappty import pygame_ui

        pygame_ui.run(
            sess, None, title=title, snapshot_path=a.snapshot, exit_when_done=a.exit_when_done
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
