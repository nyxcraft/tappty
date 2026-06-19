"""PyteTerminal: the full-ANSI backend, drop-in for the VT52 Terminal.

These exercise sequences the VT52 `Terminal` cannot handle (SGR color, CSI cursor
addressing, erase-in-display, UTF-8), and confirm it presents the same read interface a
Session/renderer needs. Skips if `pyte` (the `ansi` extra) isn't installed.
"""

import pytest

pytest.importorskip("pyte")

from tappty.pyte_terminal import PyteTerminal
from tappty.session import Session
from tappty.source import EngineSource
from tappty.terminal import Terminal


def test_sgr_color_is_parsed_not_printed():
    """ANSI color codes affect attributes, not text -- the VT52 model would print them."""
    t = PyteTerminal(40, 5)
    t.write("\x1b[31;1mRED\x1b[0m done")
    assert t.rows_text()[0].startswith("RED done")
    # the VT52 Terminal, by contrast, leaves the escape bytes mangling the line
    v = Terminal(40, 5)
    v.write("\x1b[31;1mRED\x1b[0m done")
    assert "RED done" not in v.rows_text()[0]


def test_csi_cursor_addressing():
    t = PyteTerminal(40, 6)
    t.write("\x1b[3;5Hhi")  # row 3, col 5 (1-based) -> y=2, x=4
    assert t.rows_text()[2][4:6] == "hi"
    assert (t.cx, t.cy) == (6, 2)  # cursor advanced past "hi"


def test_erase_in_display():
    t = PyteTerminal(20, 3)
    t.write("aaaa\r\nbbbb\r\ncccc")
    t.write("\x1b[H\x1b[2J")  # home + clear whole screen
    assert t.snapshot().strip() == ""
    assert (t.cx, t.cy) == (0, 0)


def test_unicode_text_renders_as_written():
    """Text is treated as code points (like the VT52 Terminal): EngineSource/CastSource
    Unicode renders as written -- it is NOT re-encoded as latin-1 bytes."""
    t = PyteTerminal(20, 2)
    t.write("café — ok")  # plain Python text, em dash included
    assert t.rows_text()[0].startswith("café — ok")


def test_drop_in_read_interface_matches_terminal():
    """Same attributes/methods a Session.snapshot() and the renderers read."""
    t = PyteTerminal(80, 24)
    for name in ("cols", "rows", "cx", "cy"):
        assert isinstance(getattr(t, name), int)
    for meth in ("write", "snapshot", "rows_text", "view_rows", "max_scroll", "clear"):
        assert callable(getattr(t, meth))


def test_scrollback_paper_roll():
    """Scrolled-off lines are kept and viewable via view_rows(offset)/max_scroll(), without
    disturbing the live screen -- same contract as the VT52 Terminal's scrollback."""
    t = PyteTerminal(12, 3)  # 3 visible rows
    for i in range(8):
        t.write(f"line{i}\r\n")  # several lines scroll off the top
    assert t.max_scroll() >= 5
    assert t.view_rows(0) == t.rows_text()  # offset 0 = the live screen
    assert not any("line0" in r for r in t.view_rows(0))  # line0 is off the live screen
    top = t.view_rows(t.max_scroll())  # scroll to the very top of history
    assert top[0].startswith("line0")
    assert len(top) == 3  # always returns `rows` lines


def test_as_session_backend():
    """A Session driving PyteTerminal renders an ANSI-emitting program correctly."""

    def runner(emit, readline):
        emit("\x1b[2;1Hsecond line\x1b[1;1Hfirst")

    sess = Session(PyteTerminal(80, 24), source=EngineSource(runner))
    sess.run_blocking()
    snap = sess.snapshot()
    assert snap["rows"][0].startswith("first")
    assert snap["rows"][1].startswith("second line")
    assert snap["cols"] == 80 and snap["rows_n"] == 24
