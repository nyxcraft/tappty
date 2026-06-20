"""Recording (write) + .ttyrec replay (read), and the record -> replay round trip.

Uses an in-process EngineSource so it runs everywhere (no pty, no display): a runner emits
known text, a Recorder writes it to .cast / .ttyrec, and TtyrecSource replays it back.
"""

import json
import struct

import pytest

from tappty import (
    AnsSource,
    Recorder,
    Session,
    ThreeASource,
    TtyrecSource,
    export_3a,
    export_ansi,
    replay_source,
)
from tappty.source import CastSource, EngineSource
from tappty.terminal import Terminal


def _sauce(width, height):
    """A minimal 128-byte SAUCE record: width at offset 96, height at 98, 0 comments."""
    s = bytearray(128)
    s[0:7] = b"SAUCE00"
    s[96:98] = struct.pack("<H", width)
    s[98:100] = struct.pack("<H", height)
    return bytes(s)


def _emit_runner(emit, readline):
    emit("Hello, recorder!\r\n")
    emit("line two\r\n")  # runner returns -> source exits -> run_blocking() returns


def _record(path, fmt=None):
    sess = Session(Terminal(80, 24), source=EngineSource(_emit_runner))
    rec = Recorder(sess, str(path), fmt=fmt).start()  # tap before the source runs
    sess.run_blocking()
    rec.close()
    return sess


def test_recorder_writes_valid_asciicast_v2(tmp_path):
    out = tmp_path / "session.cast"
    _record(out)
    lines = out.read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    assert header["version"] == 2 and header["width"] == 80 and header["height"] == 24
    events = [json.loads(line) for line in lines[1:] if line]
    assert all(ev[1] == "o" and isinstance(ev[0], (int, float)) for ev in events)
    text = "".join(ev[2] for ev in events)
    assert "Hello, recorder!" in text and "line two" in text


def test_record_then_replay_round_trip_ttyrec(tmp_path):
    out = tmp_path / "session.ttyrec"
    _record(out)
    assert out.read_bytes()[:12]  # has at least one record header

    # replay the recording back through a fresh session and read the screen
    replay = Session(Terminal(80, 24), source=TtyrecSource(str(out)))
    replay.run_blocking()
    screen = replay.term.snapshot()
    assert "Hello, recorder!" in screen and "line two" in screen


def test_ttyrec_source_reads_handcrafted_file(tmp_path):
    # Build a ttyrec by hand: each record is (sec, usec, len) little-endian + payload bytes.
    records = [(0.0, b"abc"), (0.5, b"\r\ndef")]
    blob = b"".join(
        struct.pack("<III", int(t), int((t - int(t)) * 1_000_000), len(d)) + d
        for t, d in records
    )
    path = tmp_path / "hand.ttyrec"
    path.write_bytes(blob)

    sess = Session(Terminal(80, 24), source=TtyrecSource(str(path), speed=1000.0))
    sess.run_blocking()
    screen = sess.term.snapshot()
    assert "abc" in screen and "def" in screen


def test_replay_source_dispatches_by_extension(tmp_path):
    cast = tmp_path / "r.cast"
    cast.write_text('{"version": 2, "width": 80, "height": 24}\n', encoding="utf-8")
    tty = tmp_path / "r.ttyrec"
    tty.write_bytes(struct.pack("<III", 0, 0, 2) + b"hi")
    ans = tmp_path / "r.ans"
    ans.write_bytes(b"hi\x1a")
    assert isinstance(replay_source(str(cast)), CastSource)
    assert isinstance(replay_source(str(tty)), TtyrecSource)
    assert isinstance(replay_source(str(ans)), AnsSource)


def test_ans_source_strips_sauce_and_decodes_cp437(tmp_path):
    pytest.importorskip("pyte")  # ANSI art needs the full-ANSI backend to render
    from tappty import PyteTerminal

    # red "RED " then green box-drawing (cp437 C9 CD BB = ╔ ═ ╗), a DOS EOF, then SAUCE.
    art = b"\x1b[31mRED \x1b[32m\xc9\xcd\xbb\x1b[0m"
    path = tmp_path / "art.ans"
    path.write_bytes(art + b"\x1a" + _sauce(40, 25))

    src = AnsSource(str(path))
    assert src.width == 40 and src.height == 25  # read from SAUCE TInfo1/TInfo2
    assert "SAUCE" not in src._content  # trailer stripped

    sess = Session(PyteTerminal(src.width, src.height), source=src)
    sess.run_blocking()
    assert "╔═╗" in sess.term.rows_text()[0]  # CP437 high-bytes decoded to Unicode glyphs


def test_export_ansi_round_trips_color(tmp_path):
    pytest.importorskip("pyte")
    from tappty import PyteTerminal

    out = tmp_path / "screen.ans"
    sess = Session(
        PyteTerminal(20, 2),
        source=EngineSource(lambda emit, readline: emit("\x1b[31mHELLO\x1b[0m")),
    )
    sess.run_blocking()
    export_ansi(sess, str(out))
    assert out.read_bytes().endswith(b"\x1a")  # DOS EOF marker

    back = Session(PyteTerminal(20, 2), source=AnsSource(str(out)))
    back.run_blocking()
    assert back.term.rows_text()[0].startswith("HELLO")
    assert back.term.cells()[0][0].fg == "red"  # color survived export -> re-read


def test_replay_source_dispatches_3a(tmp_path):
    p = tmp_path / "x.3a"
    p.write_text("@3a\n\n@body\nhi\n", encoding="utf-8")
    assert isinstance(replay_source(str(p)), ThreeASource)


def test_three_a_source_plays_colored_frames(tmp_path):
    pytest.importorskip("pyte")
    from tappty import PyteTerminal

    # two frames, each a text row + an equal-length color row (1=red 2=green; 4=blue 5=magenta)
    a3 = "@3a\ndelay 30\ncolors yes\n;; a comment\n\n@body\nAB\n12\n\nXY\n45\n"
    path = tmp_path / "anim.3a"
    path.write_text(a3, encoding="utf-8")

    src = ThreeASource(str(path))
    assert len(src.frames) == 2 and src.delay_ms == 30 and src.colors_on
    sess = Session(PyteTerminal(src.width, src.height), source=src)
    sess.run_blocking()
    assert sess.term.rows_text()[0].startswith("XY")  # the last frame is what remains
    assert sess.term.cells()[0][0].fg == "blue" and sess.term.cells()[0][1].fg == "magenta"


def test_export_3a_round_trips_color(tmp_path):
    pytest.importorskip("pyte")
    from tappty import PyteTerminal

    out = tmp_path / "s.3a"
    sess = Session(
        PyteTerminal(12, 2),
        source=EngineSource(lambda emit, readline: emit("\x1b[33mHI\x1b[0m")),  # yellow fg
    )
    sess.run_blocking()
    export_3a(sess, str(out))
    assert "@3a" in out.read_text() and "colors yes" in out.read_text()

    back = Session(PyteTerminal(12, 2), source=ThreeASource(str(out)))
    back.run_blocking()
    assert back.term.rows_text()[0].startswith("HI")
    assert back.term.cells()[0][0].fg == "brown"  # pyte names yellow "brown"; it survived
