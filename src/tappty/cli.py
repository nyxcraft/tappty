"""tapterm -- host a program on a pseudo-terminal and render it in a terminal UI.

    tapterm                      # a regular terminal: your $SHELL, full-ANSI + raw keys
    tapterm -e vim file          # xterm-style: run a command instead of the shell
    tapterm -- python3 -i        # the same, via the argv separator (after -- is argv)
    tapterm -geometry 100x30     # xterm-style size (also --cols/--rows); -T/-title for the title
    tapterm --gui                # force the pygame green-phosphor window
    tapterm --cooked -- bash     # line-oriented instrument mode (local echo, VT52 grid)
    tapterm --headless -- ls     # run to completion, print the final screen (scripting)

tapterm is a thin front-end over tappty: it wraps the command in a PtySource, hosts it in a
Session (the observe/control core), and hands the Session to a renderer. The CUI (curses) works
anywhere; the GUI (pygame, the 'sdl' extra) also needs a display, so the default mode is GUI only
when both are present, else CUI.

An interactive session behaves like a real terminal: the full-ANSI backend (pyte, the 'ansi'
extra) plus raw key forwarding, so the shell's colors, line-editing, arrow keys and full-screen
apps all work, and the window closes when the program exits (xterm's -hold keeps it open). Pass
--cooked for the line-oriented instrument default instead (local echo + line editing on the VT52
grid -- what the observe/bus capture primitives expect).
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


def _parse_geometry(ap, spec):
    """xterm-style geometry COLSxROWS with an optional +X+Y window offset we don't honor
    (tappty doesn't place windows). Returns (cols, rows)."""
    import re

    m = re.match(r"^(\d+)x(\d+)(?:[+-]\d+[+-]\d+)?$", spec, re.IGNORECASE)
    if not m or int(m.group(1)) < 1 or int(m.group(2)) < 1:
        ap.error("--geometry wants COLSxROWS, e.g. 100x30 (an optional +X+Y offset is ignored)")
    return int(m.group(1)), int(m.group(2))


def _have_pygame():
    return importlib.util.find_spec("pygame") is not None


def _have_pyte():
    return importlib.util.find_spec("pyte") is not None


def _have_arcade():
    return importlib.util.find_spec("arcade") is not None


def _have_websockets():
    return importlib.util.find_spec("websockets") is not None


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


def _make_source(ap, no_pty, cmd, rows, cols, cwd=None):
    """Pick how to host the command: plain pipes (--no-pty, cross-platform), a ConPTY on
    Windows, or a real pty on POSIX."""
    if no_pty:
        from tappty.source import PipeSource

        return PipeSource(cmd, cwd=cwd)
    if os.name == "nt":  # Windows pseudo-console
        if not _have_winpty():
            ap.error(
                "hosting a command on Windows uses ConPTY, which needs pywinpty: install "
                "it with  pip install 'tappty[win]'  (or use --no-pty to host over plain "
                "pipes, which needs no extra)"
            )
        from tappty.source import ConPtySource

        return ConPtySource(cmd, cwd=cwd, size=(rows, cols))
    return PtySource(cmd, cwd=cwd, size=(rows, cols))


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
        help="pygame green-phosphor window (needs the 'sdl' extra)",
    )
    mode.add_argument(
        "--arcade",
        dest="mode",
        action="store_const",
        const="arcade",
        help="arcade green-phosphor window (needs the 'gl' extra; a GL display)",
    )
    mode.add_argument(
        "--web",
        dest="mode",
        action="store_const",
        const="web",
        help="serve the terminal in a browser over a websocket (needs the 'web' extra)",
    )
    mode.add_argument(
        "--headless",
        dest="mode",
        action="store_const",
        const="headless",
        help="run to completion, print the final screen, then exit",
    )
    ap.add_argument(
        "--title",
        "-T",
        "-title",
        default=None,
        help="window / status-line title (xterm: -T / -title)",
    )
    ap.add_argument(
        "--geometry",
        "-geometry",
        "-g",
        default=None,
        metavar="COLSxROWS",
        help="terminal size, xterm-style (e.g. 100x30; a trailing +X+Y offset is "
        "ignored). Overrides --cols / --rows",
    )
    ap.add_argument(
        "--cwd",
        "-cd",
        default=None,
        metavar="DIR",
        help="run the hosted program in this working directory (xterm: -cd)",
    )
    ap.add_argument(
        "-hold",
        "--hold",
        dest="hold",
        action="store_true",
        help="keep the window open after the program exits (xterm: -hold). A "
        "regular-terminal session closes on exit unless you pass this; the "
        "--cooked instrument mode always holds",
    )
    ap.add_argument(
        "--cooked",
        "--line",
        dest="cooked",
        action="store_true",
        help="line-oriented instrument mode: local echo + line editing on the "
        "VT52 grid, instead of the default regular-terminal behavior (full-ANSI "
        "+ raw keys). What the observe / bus-capture primitives expect",
    )
    ap.add_argument(
        "-e",
        "--exec",
        dest="exec_cmd",
        nargs=argparse.REMAINDER,
        default=None,
        metavar="CMD",
        help="run CMD (with its args) instead of your shell, "
        "xterm-style -- everything after -e is the command (same as after --)",
    )
    ap.add_argument(
        "--port",
        type=_positive_int,
        default=8023,
        help="--web: HTTP port for the page (the websocket uses PORT+1); default 8023",
    )
    ap.add_argument("--cols", type=_positive_int, default=80, help="terminal columns (default 80)")
    ap.add_argument("--rows", type=_positive_int, default=24, help="terminal rows (default 24)")
    ap.add_argument(
        "--snapshot",
        default=None,
        help="GUI/arcade: mirror the screen to this text file each second (ignored by "
        "--cui/--web); headless: write the final screen here",
    )
    ap.add_argument(
        "--exit-when-done",
        action="store_true",
        help="GUI/CUI/web: close (don't wait for a final keypress) when the hosted program exits",
    )
    ap.add_argument(
        "--play",
        "--cast",
        dest="play",
        default=None,
        metavar="FILE",
        help="replay a recording instead of hosting a command: .cast (asciinema), .ttyrec, "
        ".ans ANSI art, or .3a animated ASCII art -- auto-detected by extension. The full-ANSI "
        "backend is used automatically (recordings are VT100+); a .cast/.ans is sized to the "
        "recording. Needs the 'ansi' extra",
    )
    ap.add_argument(
        "--record",
        default=None,
        metavar="FILE",
        help="record the session's output as it runs, to FILE -- .cast (asciinema v2) or "
        ".ttyrec by extension; replay it later with --play",
    )
    ap.add_argument(
        "--render",
        default=None,
        metavar="FILE",
        help="with --play: render the recording to a video file (.mp4 / .webm / .gif / ...) "
        "via ffmpeg, instead of displaying it. Needs the 'sdl' + 'ansi' extras and ffmpeg "
        "(or  pip install 'tappty[video]'  for a bundled ffmpeg)",
    )
    ap.add_argument(
        "--fps", type=_positive_int, default=30, help="--render: output frame rate (default 30)"
    )
    ap.add_argument(
        "--font-size",
        dest="font_size",
        type=_positive_int,
        default=18,
        help="--render: glyph size in points -- the size/zoom control (default 18)",
    )
    ap.add_argument(
        "--zoom",
        type=float,
        default=1.0,
        help="--render: scale the finished frame, e.g. 2 for a crisp 2x video",
    )
    ap.add_argument(
        "--font",
        default=None,
        metavar="TTF",
        help="--render: a .ttf font file to render with (default: DejaVu Sans Mono)",
    )
    ap.add_argument(
        "--crop",
        default=None,
        metavar="COL,ROW,COLS,ROWS",
        help="--render: render only this grid region (area of interest)",
    )
    ap.add_argument(
        "--seconds",
        type=float,
        default=None,
        metavar="N",
        help="--render of a live command (no --play): stop after N seconds "
        "(needed for programs that don't exit on their own, e.g. cmatrix)",
    )
    ap.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="--play: replay speed multiplier (default 1.0; e.g. 2 = twice as fast)",
    )
    ap.add_argument(
        "--loop",
        action="store_true",
        help="--play: loop the recording (ignored under --headless)",
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
        "work. An interactive session is already raw by default; --cooked switches to "
        "line-buffered input with local echo",
    )
    ap.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="the program to host (prefix with --), e.g. tapterm -- bash",
    )
    return ap


def _run_mode(ap, a, sess, term, mode, title):
    """Run the chosen renderer/headless mode for a built session; returns the exit code."""
    if mode == "headless":
        sess.run_blocking()  # runs until the hosted program exits (EOF on pty)
        out = term.snapshot()
        if a.snapshot:
            snap = a.snapshot.lower()
            if snap.endswith(".ans"):  # export the screen as ANSI art
                from tappty.recorder import export_ansi

                export_ansi(sess, a.snapshot)
            elif snap.endswith(".3a"):  # export as a single-frame .3a
                from tappty.recorder import export_3a

                export_3a(sess, a.snapshot)
            else:
                with open(a.snapshot, "w") as f:
                    f.write(out)
        print(out)
        return sess.source.returncode or 0  # propagate the child's exit code (None -> 0)

    sess.raw_keys = a.raw  # raw keystrokes for full-screen TUIs (no echo/line-edit)
    if mode == "web":  # a server: browser clients claim their own control, not a local human
        if not _have_websockets():
            ap.error(
                "--web needs the websockets library: install it with  pip install "
                "'tappty[web]'  (or use --gui / --cui / --headless)"
            )
        from tappty import web_ui

        web_ui.run(sess, None, title=title, port=a.port, exit_when_done=a.exit_when_done)
        return 0

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

        curses_ui.run(sess, None, title=title, exit_when_done=a.exit_when_done)
    elif mode == "arcade":
        if not _have_arcade():
            ap.error(
                "--arcade needs the arcade library: install it with  pip install "
                "'tappty[gl]'  (or use --gui for the pygame window, --cui, or --headless)"
            )
        from tappty import arcade_ui

        arcade_ui.run(
            sess, None, title=title, snapshot_path=a.snapshot, exit_when_done=a.exit_when_done
        )
    else:  # gui
        if not _have_pygame():
            ap.error(
                "--gui needs pygame: install it with  pip install 'tappty[sdl]'  "
                "(or run with --cui)"
            )
        from tappty import pygame_ui

        pygame_ui.run(
            sess, None, title=title, snapshot_path=a.snapshot, exit_when_done=a.exit_when_done
        )
    return 0


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)

    if a.geometry:  # xterm-style COLSxROWS overrides --cols/--rows
        a.cols, a.rows = _parse_geometry(ap, a.geometry)
    if a.exec_cmd is not None:  # xterm -e CMD ...: route it through the same path as `-- CMD`
        a.command = ["--", *a.exec_cmd]

    mode = a.mode or _default_mode()

    # An interactive session should feel like a real terminal: full-ANSI rendering + raw key
    # forwarding (the shell's colors, line-editing, arrows and full-screen apps), and the window
    # closes when the program exits, like xterm. --cooked keeps the line-oriented instrument
    # default (local echo on the VT52 grid). The ANSI backend needs pyte; without it we fall back
    # to that instrument default rather than fail.
    interactive = not a.play and not a.render and mode in ("gui", "cui", "arcade", "web")
    terminalish = interactive and not a.cooked and _have_pyte()
    if terminalish:
        a.raw = True
        if not a.hold:
            a.exit_when_done = True

    if a.render:  # render to a video file, no display
        crop = None
        if a.crop:
            try:
                crop = tuple(int(x) for x in a.crop.split(","))
                if len(crop) != 4:
                    raise ValueError
            except ValueError:
                ap.error("--crop wants four integers: COL,ROW,COLS,ROWS")
        recording, tmp = a.play, None
        if not recording:  # no --play: host the command live, record it, then render that
            import tempfile
            import time

            cmd = a.command[1:] if a.command and a.command[0] == "--" else a.command
            if not cmd:
                cmd = [os.environ.get("SHELL", "/bin/sh")]
            sess = Session(_make_terminal(ap, False, a.cols, a.rows))  # term unused (taps raw)
            sess.source = _make_source(ap, a.no_pty, cmd, a.rows, a.cols, cwd=a.cwd)
            fd, recording = tempfile.mkstemp(suffix=".cast")
            os.close(fd)
            tmp = recording
            from tappty.recorder import Recorder

            rec = Recorder(sess, recording).start()
            if a.seconds:  # timed capture, for programs that never exit
                sess.start()
                time.sleep(a.seconds)
                sess.stop()
            else:  # record until the program exits on its own
                sess.run_blocking()
            rec.close()
        from tappty.video import render_video

        try:
            out = render_video(
                recording,
                a.render,
                fps=a.fps,
                font_size=a.font_size,
                font_path=a.font,
                zoom=a.zoom,
                speed=a.speed,
                crop=crop,
            )
        except RuntimeError as exc:  # missing ffmpeg / encode failure -> clean message
            ap.error(str(exc))
        finally:
            if tmp:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        print(f"rendered -> {out}")
        return 0

    # Replayed recordings (.cast/.ttyrec/.ans) are VT100+, as is the default Windows ConPTY
    # path -- the VT52 grid would render them as escape soup, so force the full-ANSI backend
    # whenever a recording is replayed, ConPTY is hosting, or we're acting as a real terminal.
    ansi = a.ansi or bool(a.play) or (os.name == "nt" and not a.no_pty) or terminalish

    if a.play:  # replay a recording instead of hosting a command
        from tappty.source import replay_source

        src = replay_source(a.play, speed=a.speed, loop=a.loop and mode != "headless")
        term = _make_terminal(ap, ansi, src.width, src.height)  # size to the recording
        sess = Session(term, source=src)
        title = a.title or ("tapterm :: play:" + os.path.basename(a.play))
    else:
        cmd = a.command
        if cmd and cmd[0] == "--":  # the conventional argv separator
            cmd = cmd[1:]
        if not cmd:  # no command -> behave like a terminal: host a shell
            cmd = [os.environ.get("SHELL", "/bin/sh")]
        term = _make_terminal(ap, ansi, a.cols, a.rows)
        sess = Session(term)
        sess.source = _make_source(ap, a.no_pty, cmd, a.rows, a.cols, cwd=a.cwd)
        title = a.title or ("tapterm :: " + os.path.basename(cmd[0]))

    recorder = None
    if a.record:  # tap the output stream before the source starts, so nothing is missed
        from tappty.recorder import Recorder

        recorder = Recorder(sess, a.record).start()
    try:
        return _run_mode(ap, a, sess, term, mode, title)
    finally:
        if recorder is not None:
            recorder.close()


if __name__ == "__main__":
    sys.exit(main())
