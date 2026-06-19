"""PipeSource (non-pty, cross-platform) and the structure of ConPtySource (Windows)."""

import sys

import pytest

from tappty.session import Session
from tappty.source import ConPtySource, PipeSource
from tappty.terminal import Terminal


def test_pipe_source_captures_output():
    src = PipeSource([sys.executable, "-c", "print('pipe line one'); print('pipe line two')"])
    sess = Session(Terminal(80, 24), source=src)
    events = []
    sess.on_event(lambda name, info: events.append(name))
    sess.run_blocking()  # reads to EOF (child exits -> flush), joins thread
    rows = sess.term.rows_text()
    assert rows[0].startswith("pipe line one")
    assert rows[1].startswith("pipe line two")
    assert "CLOSED" in events


def test_pipe_source_send_input():
    src = PipeSource(
        [
            sys.executable,
            "-u",
            "-c",
            "import sys; line=sys.stdin.readline(); print('echo:'+line.strip())",
        ]
    )
    sess = Session(Terminal(80, 24), source=src)
    sess.start()
    sess.send_input("hello\n")  # by=None -> trusted; pipe buffers until child reads
    src.thread.join(timeout=5)
    assert not src.thread.is_alive()
    assert any("echo:hello" in r for r in sess.term.rows_text())


def test_conpty_source_defined_and_import_guarded():
    """ConPtySource is defined everywhere (module import is safe off-Windows); only start()
    touches pywinpty, which is absent here -> a clear ImportError, not an import-time crash."""
    src = ConPtySource(["cmd"])
    with pytest.raises(ImportError):
        src.start(lambda t: None, lambda: None, lambda: None)
