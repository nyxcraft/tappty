"""The bytes/characters split: a byte source's output is RAW bytes on the stream tap
(lossless) and DECODED characters on the screen. The Session does the decode (per the
source's `encoding`, default UTF-8); the terminal backends stay encoding-agnostic."""

import os
import sys

import pytest

from tappty.session import Session
from tappty.source import PipeSource, PtySource
from tappty.terminal import Terminal


@pytest.mark.skipif(os.name == "nt", reason="PtySource is POSIX-only (pty/termios)")
def test_pty_screen_decoded_stream_raw():
    src = PtySource([sys.executable, "-c", "print('café')"])
    sess = Session(Terminal(80, 24), source=src)
    chunks = []
    sess.on_stream(lambda t: chunks.append(t))
    sess.run_blocking()

    assert any("café" in r for r in sess.term.rows_text())  # screen: decoded characters
    raw = "".join(chunks).encode("latin-1")  # stream: recover exact bytes
    assert b"caf\xc3\xa9" in raw  # é as its two UTF-8 bytes, undecoded


@pytest.mark.skipif(os.name == "nt", reason="PtySource is POSIX-only (pty/termios)")
def test_partial_multibyte_is_flushed_on_exit():
    # the stream ends on a lone UTF-8 lead byte: the held byte must be flushed at EOF
    src = PtySource([sys.executable, "-c", "import os; os.write(1, b'A'); os.write(1, b'\\xc3')"])
    sess = Session(Terminal(80, 24), source=src)
    sess.run_blocking()
    row = sess.term.rows_text()[0]
    assert row[0] == "A"
    assert "�" in row  # the incomplete sequence became U+FFFD on the final flush


def test_pipe_screen_decoded_stream_raw():
    src = PipeSource([sys.executable, "-c", "print('café')"])
    sess = Session(Terminal(80, 24), source=src)
    chunks = []
    sess.on_stream(lambda t: chunks.append(t))
    sess.run_blocking()

    assert any("café" in r for r in sess.term.rows_text())
    assert b"caf\xc3\xa9" in "".join(chunks).encode("latin-1")


def test_latin1_encoding_is_byte_transparent_on_screen():
    """encoding='latin-1' keeps the screen byte-transparent too (the old behavior): the
    UTF-8 bytes of é render as two cells (mojibake), not one decoded character."""
    src = PipeSource([sys.executable, "-c", "print('café')"], encoding="latin-1")
    sess = Session(Terminal(80, 24), source=src)
    sess.run_blocking()
    assert any("cafÃ©" in r for r in sess.term.rows_text())


def test_engine_source_text_passes_through_undecoded():
    """A text source (no `encoding`) is not decoded -- its characters reach the screen as-is."""
    sess = Session(Terminal(80, 24))
    sess.run_blocking(lambda emit, readline: emit("café ✓"))  # EngineSource: real text
    assert sess.term.rows_text()[0].startswith("café ✓")
