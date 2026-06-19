"""tappty -- a small instrumented-terminal toolkit.

Host a program -- a subprocess on a pseudo-terminal, or any in-process runner -- in a
fixed-size character Terminal, observe and control it through a uniform set of taps (in
process) or a socket bus (out of process), and render it in a curses (CUI) or pygame
(GUI) window. Several sessions tile into one window via the compositor.

The pieces are decoupled: the Source produces bytes, the Terminal models the glass, the
Session fans output to observers and routes input back, and a renderer is just one more
observer/controller. That is what lets an AI watch and drive the same session a human
sees.

Quick start::

    from tappty import Session, Terminal, PtySource, curses_ui
    sess = Session(Terminal())
    sess.source = PtySource(["bash"])
    sess.claim_control("local", "human")
    curses_ui.run(sess, None, title="bash")

Or just use the ``tapterm`` command-line program (see tappty.cli).

Public API:
    Terminal                        -- the fixed-size character grid model (VT52 spirit)
    PyteTerminal                    -- full-ANSI/VT100+ backend (the `ansi` extra; pyte)
    Session                         -- hosts a Source; exposes observe taps + control
    Source, PtySource, EngineSource -- byte producers (pty subprocess / in-process runner)
    CastSource                      -- replay a recorded asciinema .cast session
    PipeSource, ConPtySource        -- non-pty pipes (any OS) / Windows ConPTY (pywinpty)
    BusServer, BusClient            -- out-of-process observe/control over a unix socket
    curses_ui, pygame_ui            -- renderers; each: run(session, runner, title=...)
    compositor                      -- multi-panel single-window dashboard
"""

from tappty import compositor, curses_ui, pygame_ui
from tappty.bus import BusClient, BusServer
from tappty.pyte_terminal import PyteTerminal
from tappty.session import Session
from tappty.source import CastSource, ConPtySource, EngineSource, PipeSource, PtySource, Source
from tappty.terminal import Terminal

__version__ = "0.1.0"

__all__ = [
    "Terminal",
    "PyteTerminal",
    "Session",
    "Source",
    "PtySource",
    "EngineSource",
    "CastSource",
    "PipeSource",
    "ConPtySource",
    "BusServer",
    "BusClient",
    "curses_ui",
    "pygame_ui",
    "compositor",
    "__version__",
]
