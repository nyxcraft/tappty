"""The composable TerminalPanel backings: a panel observes + controls its program
the same way whether it's backed by an in-process Session or a REMOTE session over
the bus. (The pygame draw is verified by eye; this pins the data contract.)
See [[sbterm-instrumentation]]."""

import os
import tempfile
import threading
import time

from tappty.bus import BusServer
from tappty.compositor import BusBacking, SessionBacking
from tappty.session import Session


def _wait(pred, t=4.0):
    end = time.time() + t
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.04)
    return False


def test_session_backing_observe_and_control():
    done, got = threading.Event(), []

    def runner(emit, readline):
        emit("HELLO\r\n")
        got.append(readline().strip())
        done.set()

    s = Session()
    s.run_in_thread(runner)
    b = SessionBacking(s)
    assert _wait(lambda: b.grid()["rows"][0].startswith("HELLO"))  # observe
    assert not b.has_stick()  # typing alone won't grab
    b.feed_key("x")  # ignored (no stick)
    b.toggle_stick()  # explicit grab
    assert b.has_stick()
    for ch in "PING\r":  # now control works
        b.feed_key(ch)
    assert done.wait(3) and got == ["PING"]


def test_bus_backing_observe_and_control():
    done, got = threading.Event(), []

    def runner(emit, readline):
        emit("READY\r\n")
        got.append(readline().strip())
        emit("DONE\r\n")
        done.set()

    s = Session()
    sock = os.path.join(tempfile.mkdtemp(), "s")
    srv = BusServer(s, sock).start()
    s.run_in_thread(runner)

    b = BusBacking(sock, name="panel", role="human")  # a REMOTE panel
    assert _wait(lambda: any("READY" in r for r in b.grid()["rows"])), "no remote frame"
    # the panel already holds the stick: as a controller it claimed control at HELLO and,
    # being first, became the driver. focus() is a no-op (control is explicit, via F2).
    b.focus()
    time.sleep(0.2)
    for ch in "PONG\r":  # control over the bus
        b.feed_key(ch)
    assert done.wait(4) and got == ["PONG"]
    assert _wait(lambda: any("DONE" in r for r in b.grid()["rows"]))  # frame updated
    b.close()
    srv.stop()
