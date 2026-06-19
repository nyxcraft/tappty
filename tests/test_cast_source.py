"""CastSource: replay an asciinema .cast recording through the Session/Terminal pipeline."""

import json
import time

import pytest

import tappty.source as source_mod
from tappty.session import Session
from tappty.source import CastSource
from tappty.terminal import Terminal


def _write_v2(path, header, events):
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(header) + "\n")
        for e in events:
            f.write(json.dumps(e) + "\n")


def test_v1_cast_file_size_is_capped(tmp_path, monkeypatch):
    """The unstreamable v1 path (whole-file json.load) refuses oversized files."""
    monkeypatch.setattr(source_mod, "MAX_CAST_FILE", 50)  # tiny cap for the test
    p = tmp_path / "big_v1.cast"
    p.write_text(
        json.dumps({"version": 1, "width": 80, "height": 24, "stdout": [[0.0, "x" * 200]]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="exceeds"):
        CastSource(str(p))


def test_v2_replays_output_into_grid(tmp_path):
    p = tmp_path / "demo.cast"
    _write_v2(
        p,
        {"version": 2, "width": 80, "height": 24},
        [
            [0.00, "o", "hello "],
            [0.01, "i", "ZZZ"],  # input events must NOT render
            [0.02, "o", "cast\r\n"],
            [0.03, "o", "line two\r\n"],
        ],
    )
    cast = CastSource(str(p), speed=50.0)  # fast-forward so the test is quick
    term = Terminal(cast.width, cast.height)
    sess = Session(term, source=cast)
    events = []
    sess.on_event(lambda name, info: events.append(name))
    sess.run_blocking()  # plays to completion, joins the thread

    rows = term.rows_text()
    assert rows[0].startswith("hello cast")
    assert rows[1].startswith("line two")
    assert "ZZZ" not in "".join(rows)  # the "i" event was skipped
    assert "CLOSED" in events  # on_exit fired -> session closed


def test_header_dims_size_the_terminal(tmp_path):
    p = tmp_path / "wide.cast"
    _write_v2(p, {"version": 2, "width": 100, "height": 30}, [[0.0, "o", "x"]])
    cast = CastSource(str(p), speed=100.0)
    assert (cast.width, cast.height) == (100, 30)


def test_v1_compact_recording(tmp_path):
    p = tmp_path / "v1.cast"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(
            {"version": 1, "width": 80, "height": 24, "stdout": [[0.0, "AB"], [0.01, "CD\r\n"]]}, f
        )
    cast = CastSource(str(p), speed=100.0)
    assert cast.version == 1
    term = Terminal(cast.width, cast.height)
    sess = Session(term, source=cast)
    sess.run_blocking()
    assert term.rows_text()[0].startswith("ABCD")


def test_speed_scales_duration(tmp_path):
    p = tmp_path / "timed.cast"
    _write_v2(
        p,
        {"version": 2, "width": 80, "height": 24},
        [
            [0.0, "o", "a"],
            [0.2, "o", "b"],
            [0.4, "o", "c"],
        ],
    )
    # at speed=20 the 0.4s recording should take ~0.02s -- comfortably under 0.2s
    cast = CastSource(str(p), speed=20.0)
    sess = Session(Terminal(cast.width, cast.height), source=cast)
    t0 = time.monotonic()
    sess.run_blocking()
    assert time.monotonic() - t0 < 0.2
    assert sess.term.rows_text()[0].startswith("abc")


def test_loop_and_stop(tmp_path):
    p = tmp_path / "loop.cast"
    _write_v2(p, {"version": 2, "width": 80, "height": 24}, [[0.0, "o", "X"]])
    cast = CastSource(str(p), speed=1000.0, loop=True)
    sess = Session(Terminal(cast.width, cast.height), source=cast)
    sess.start()
    assert cast.thread.is_alive()  # looping -> still running
    cast.stop()
    cast.thread.join(timeout=2.0)
    assert not cast.thread.is_alive()  # stop() ends the loop


def test_session_stop_stops_the_source(tmp_path):
    """Session.stop() stops the hosted source and joins its thread (the owning-renderer
    teardown path), using a cast whose long idle gap would otherwise keep it alive."""
    p = tmp_path / "idle.cast"
    _write_v2(
        p, {"version": 2, "width": 80, "height": 24}, [[0.0, "o", "hi"], [3600.0, "o", "later"]]
    )
    sess = Session(Terminal(80, 24), source=CastSource(str(p), speed=1.0))
    sess.start()
    time.sleep(0.1)
    assert sess.source.thread.is_alive()  # waiting out the 1-hour gap
    sess.stop()
    assert not sess.source.thread.is_alive()  # stop() woke + joined it


def test_stop_interrupts_long_idle_gap(tmp_path):
    """stop() must wake a thread sleeping a long inter-event gap, not wait it out."""
    p = tmp_path / "idle.cast"
    _write_v2(
        p,
        {"version": 2, "width": 80, "height": 24},
        [
            [0.0, "o", "start"],
            [3600.0, "o", "an hour later"],  # 1-hour gap at speed 1.0
        ],
    )
    cast = CastSource(str(p), speed=1.0)
    sess = Session(Terminal(80, 24), source=cast)
    sess.start()
    time.sleep(0.2)  # first event emits; thread now sleeping
    t0 = time.monotonic()
    cast.stop()
    cast.thread.join(timeout=2.0)
    assert not cast.thread.is_alive()  # woke promptly instead of waiting the hour
    assert time.monotonic() - t0 < 1.0
