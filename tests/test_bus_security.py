"""Bus hardening: token auth, loopback-only TCP, newline-frame injection, safe socket
unlink, and CMD timeout raising."""

import json
import os
import tempfile
import time

import pytest

from tappty.bus import BusClient, BusServer
from tappty.session import Session


def _sock():
    return os.path.join(tempfile.mkdtemp(), "s")


def test_token_required_rejects_unauthed_and_accepts_authed():
    s = Session()
    s.run_in_thread(lambda e, r: r())  # keep the session alive
    path = _sock()
    srv = BusServer(s, path, token="sesame").start()

    bad = BusClient(path).connect()  # no token -> HELLO denied
    bad.hello("ai", "bot")
    assert bad.wait_for("DENIED", 2) is not None

    sneaky = BusClient(path).connect()  # a command without auth -> denied
    sneaky.send("SNAP")
    assert sneaky.wait_for("DENIED", 2) is not None

    good = BusClient(path, token="sesame").connect()  # correct token -> works
    good.hello("ai", "bot")
    assert good.wait_for("OK", 2) is not None
    assert good.snap() is not None

    bad.close()
    sneaky.close()
    good.close()
    srv.stop()


def test_refuses_non_loopback_tcp_bind():
    s = Session()
    with pytest.raises(ValueError, match="non-loopback"):
        BusServer(s, ("0.0.0.0", 0)).start()  # would expose to all interfaces


def test_empty_token_is_rejected():
    # an empty token would let a client that sends no token authenticate
    with pytest.raises(ValueError, match="non-empty"):
        BusServer(Session(), _sock(), token="")


def test_hello_rejects_invalid_json():
    s = Session()
    s.run_in_thread(lambda e, r: r())
    path = _sock()
    srv = BusServer(s, path).start()
    c = BusClient(path).connect()
    c.send("HELLO", "{")  # invalid JSON -> DENIED, not a silent anonymous observer
    assert c.wait_for("DENIED", 2) is not None
    c.close()
    srv.stop()


def test_hello_rejects_non_object_json():
    s = Session()
    s.run_in_thread(lambda e, r: r())
    path = _sock()
    srv = BusServer(s, path).start()
    c = BusClient(path).connect()
    c.send("HELLO", "123")  # valid JSON, but not an object -> DENIED, not a crash
    assert c.wait_for("DENIED", 2) is not None
    c.close()
    srv.stop()


def test_numeric_token_does_not_match_string_token():
    # a JSON number 123 must NOT satisfy a string token "123"
    s = Session()
    s.run_in_thread(lambda e, r: r())
    path = _sock()
    srv = BusServer(s, path, token="123").start()
    c = BusClient(path).connect()
    c.send("HELLO", json.dumps({"role": "ai", "name": "x", "token": 123}))
    assert c.wait_for("DENIED", 2) is not None
    c.close()
    srv.stop()


def test_line_payload_rejects_newline():
    s = Session()
    s.run_in_thread(lambda e, r: r())
    path = _sock()
    srv = BusServer(s, path).start()
    c = BusClient(path).connect()
    c.hello("ai", "bot")
    assert c.wait_for("OK", 2)
    with pytest.raises(ValueError, match="newline"):
        c.line("ls\nTAKE")  # a newline would inject a second (TAKE) frame
    c.close()
    srv.stop()


def test_start_refuses_to_unlink_a_regular_file():
    s = Session()
    path = _sock()
    with open(path, "w") as f:
        f.write("important")  # a real file where the socket would go
    with pytest.raises(FileExistsError):
        BusServer(s, path).start()
    assert os.path.exists(path)  # not deleted
    with open(path) as f:
        assert f.read() == "important"


def test_cmd_raises_on_timeout():
    def runner(emit, readline):
        readline()  # consume the CMD input, then never block on input again
        emit("partial")
        time.sleep(2)

    s = Session()
    path = _sock()
    srv = BusServer(s, path, cmd_timeout=0.4).start()
    s.run_in_thread(runner)
    c = BusClient(path).connect()
    c.hello("ai", "bot")
    assert c.wait_for("OK", 2)
    time.sleep(0.2)
    with pytest.raises(TimeoutError):
        c.cmd("go", timeout=3)
    c.close()
    srv.stop()


def test_cmd_capture_is_hard_capped(monkeypatch):
    import tappty.bus as bus_mod

    monkeypatch.setattr(bus_mod, "MAX_CAPTURE", 10)  # tiny cap for the test

    def runner(emit, readline):
        readline()  # the CMD input
        emit("X" * 100)  # one chunk far over the cap
        readline()  # next prompt -> closes the capture

    s = Session()
    path = _sock()
    srv = BusServer(s, path).start()
    s.run_in_thread(runner)
    c = BusClient(path).connect()
    c.hello("ai", "bot")
    assert c.wait_for("OK", 2)
    time.sleep(0.2)
    c.send("CMD", "go")
    resp = c.wait_for("RESP", 3)
    assert resp["truncated"] is True  # the cap was hit
    assert len(resp["text"]) <= 10  # hard cap honored even on a big final chunk
    c.close()
    srv.stop()


def test_key_ignores_non_string_payload():
    s = Session()
    s.run_in_thread(lambda e, r: r())
    path = _sock()
    srv = BusServer(s, path).start()
    c = BusClient(path).connect()
    c.hello("human", "h")  # first controller -> holds the stick
    assert c.wait_for("OK", 2)
    c.send("KEY", "123")  # JSON number -> ignored (not iterated as stray "keys")
    c.send("KEY", json.dumps(["a", "b"]))  # JSON array -> ignored
    time.sleep(0.2)
    assert c.snap() is not None  # connection still alive (no crash)
    assert s.term.rows_text()[0].strip() == ""  # nothing was typed
    c.close()
    srv.stop()
