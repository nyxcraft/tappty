"""tapterm -- host a program on a pseudo-terminal and render it in a terminal UI.

    tapterm                      # host your $SHELL (GUI if pygame + a display, else CUI)
    tapterm -- python3 -i        # host a specific command (everything after -- is argv)
    tapterm --cui -- bash        # force the curses character UI (this terminal)
    tapterm --gui -- bash        # force the pygame green-phosphor window
    tapterm --headless -- ls     # run to completion, print the final screen (scripting)

tapterm is a thin front-end over tappty: it wraps the command in a PtySource, hosts it
in a Session (the observe/control core), and hands the Session to a renderer. The CUI
(curses) works anywhere; the GUI (pygame, the 'gui' extra) also needs a display, so the
default mode is GUI only when both are present, else CUI.
"""

import argparse
import importlib.util
import os
import sys

from tappty.session import Session
from tappty.source import PtySource
from tappty.terminal import Terminal


def _positive_int(s):
    v = int(s)
    if v < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return v


def _have_pygame():
    return importlib.util.find_spec("pygame") is not None


def _have_pyte():
    return importlib.util.find_spec("pyte") is not None


def _have_arcade():
    return importlib.util.find_spec("arcade") is not None


def _have_curses():
    # The stdlib `curses` *package* wrapper ships even on Windows, but it's useless without
    # the `_curses` C extension -- absent on stock Windows, supplied by `windows-curses`. So
    # probe `_curses` (the real dependency), not the `curses` wrapper, which find_spec would
    # report present on Windows.
    return importlib.util.find_spec("_curses") is not None


def _have_winpty():
    return importlib.util.find_spec("winpty") is not None  # pywinpty's import name


def _display_available():
    """Is a GUI display reachable? Windows and macOS have a native GUI (no X11 DISPLAY);
    other POSIX (Linux/BSD) needs X/Wayland (or a forced SDL driver) -- over SSH/cron there
    is none, so fall back to CUI."""
    if os.name == "nt" or sys.platform == "darwin":
        return True
    return bool(
        os.environ.get("DISPLAY")
        or os.environ.get("WAYLAND_DISPLAY")
        or os.environ.get("SDL_VIDEODRIVER")
    )


def _default_mode():
    """GUI when pygame is installed AND a display is available (the showcase), else the
    always-available CUI. Avoids picking GUI on a headless box where it would just fail
    (an explicit --gui still tries, and fails clearly)."""
    return "gui" if _have_pygame() and _display_available() else "cui"


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


def _make_source(ap, no_pty, cmd, rows, cols):
    """Pick how to host the command: plain pipes (--no-pty, cross-platform), a ConPTY on
    Windows, or a real pty on POSIX."""
    if no_pty:
        from tappty.source import PipeSource

        return PipeSource(cmd)
    if os.name == "nt":  # Windows pseudo-console
        if not _have_winpty():
            ap.error(
                "hosting a command on Windows uses ConPTY, which needs pywinpty: install "
                "it with  pip install 'tappty[win]'  (or use --no-pty to host over plain "
                "pipes, which needs no extra)"
            )
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
        "--arcade",
        dest="mode",
        action="store_const",
        const="arcade",
        help="arcade green-phosphor window (needs the 'arcade' extra; a GL display)",
    )
    mode.add_argument(
        "--headless",
        dest="mode",
        action="store_const",
        const="headless",
        help="run to completion, print the final screen, then exit",
    )
    ap.add_argument("--title", default=None, help="window / status-line title")
    ap.add_argument("--cols", type=_positive_int, default=80, help="terminal columns (default 80)")
    ap.add_argument("--rows", type=_positive_int, default=24, help="terminal rows (default 24)")
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
        "--raw",
        action="store_true",
        help="forward keystrokes raw -- arrows/function keys/Ctrl-combos go straight to "
        "the program, no local echo or line-editing -- so full-screen TUIs (vim, htop) "
        "work. Pair with --ansi. Without it, input is line-buffered with local echo",
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
        sess.source = _make_source(ap, a.no_pty, cmd, a.rows, a.cols)
        title = a.title or ("tapterm :: " + os.path.basename(cmd[0]))

    if mode == "headless":
        sess.run_blocking()  # runs until the hosted program exits (EOF on pty)
        out = term.snapshot()
        if a.snapshot:
            with open(a.snapshot, "w") as f:
                f.write(out)
        print(out)
        return sess.source.returncode or 0  # propagate the child's exit code (None -> 0)

    sess.raw_keys = a.raw  # raw keystrokes for full-screen TUIs (no echo/line-edit)
    sess.claim_control("local", "human")  # a human is at the keyboard -> default driver
    if mode == "cui":
        if not _have_curses():
            ap.error(
                "--cui needs the curses library, which the Python standard library does "
                "not ship on Windows: install it with  pip install 'tappty[win]'  (or "
                "pip install windows-curses), or use --gui for a window or --headless to "
                "just run and print"
            )
        from tappty import curses_ui

        curses_ui.run(sess, None, title=title)
    elif mode == "arcade":
        if not _have_arcade():
            ap.error(
                "--arcade needs the arcade library: install it with  pip install "
                "'tappty[arcade]'  (or use --gui for the pygame window, --cui, or --headless)"
            )
        from tappty import arcade_ui

        arcade_ui.run(
            sess, None, title=title, snapshot_path=a.snapshot, exit_when_done=a.exit_when_done
        )
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
