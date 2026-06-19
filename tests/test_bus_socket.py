"""The instrumentation bus over a Unix socket: an out-of-process client observes a
Session's screen and injects input. Short tmpdir socket paths (AF_UNIX has a ~108
char limit). See [[sbterm-instrumentation]]."""

import os
import tempfile
import threading
import time

from tappty.bus import BusClient, BusServer
from tappty.session import Session


def _sock():
    return os.path.join(tempfile.mkdtemp(), "s")


def test_socket_snapshot_and_control():
    waited, closed = threading.Event(), threading.Event()

    def runner(emit, readline):
        emit("HELLO\r\n")
        line = readline()
        emit(f"GOT {line.strip()}\r\n")

    s = Session()
    s.on_event(
        lambda n, i: waited.set() if n == "WAIT" else (closed.set() if n == "CLOSED" else None)
    )
    path = _sock()
    srv = BusServer(s, path).start()
    s.run_in_thread(runner)
    assert waited.wait(3)  # program blocked for input

    c = BusClient(path).connect()
    c.hello("controller", "tester")
    frame = c.snap()  # observe the screen over the socket
    assert frame and frame["rows"][0].startswith("HELLO")

    c.line("WORLD")  # control it over the socket
    assert closed.wait(3)
    frame2 = c.snap()
    assert any(r.startswith("GOT WORLD") for r in frame2["rows"])
    c.close()
    srv.stop()


def test_socket_subscription_pushes_output_and_events():
    def runner(emit, readline):
        emit("READY\r\n")
        while True:
            line = readline()
            if line.strip() == "QUIT":
                break
            emit(f"echo {line.strip()}\r\n")

    s = Session()
    path = _sock()
    srv = BusServer(s, path).start()
    s.run_in_thread(runner)

    c = BusClient(path).connect()
    c.hello("controller")
    c.sub()  # subscribe to pushes
    time.sleep(0.2)  # let SUB register before we trigger output
    c.line("hi")

    saw_out = saw_event = False
    end = time.monotonic() + 3
    while time.monotonic() < end and not (saw_out and saw_event):
        try:
            v, d = c.inbox.get(timeout=end - time.monotonic())
        except Exception:
            break
        if v == "OUT" and isinstance(d, str) and "echo hi" in d:
            saw_out = True
        if v == "EVENT" and isinstance(d, dict) and d.get("name") == "WAIT":
            saw_event = True
    assert saw_out, "did not receive pushed OUT for 'echo hi'"
    assert saw_event, "did not receive pushed WAIT event"
    c.line("QUIT")
    c.close()
    srv.stop()


def test_observer_disconnect_does_not_drop_a_same_named_controller():
    """An observer that happens to pick a live controller's name must not release that
    controller's talking stick when it disconnects (only a conn that claimed may drop it)."""
    s = Session()
    s.run_in_thread(lambda emit, readline: readline())  # block so the session stays alive
    path = _sock()
    srv = BusServer(s, path).start()

    ctrl = BusClient(path).connect()
    ctrl.hello("ai", "bot")
    assert ctrl.wait_for("OK", 3)
    assert s.driver == "bot"  # controller 'bot' holds the stick

    obs = BusClient(path).connect()
    obs.hello("observer", "bot")  # same name, observer
    assert obs.wait_for("OK", 3)
    obs.close()
    time.sleep(0.3)  # let the server process the disconnect
    assert s.driver == "bot"  # observer's drop did NOT free bot's stick
    ctrl.close()
    srv.stop()


def test_duplicate_controller_names_get_distinct_identities():
    """Two controllers requesting the same name must get distinct stick identities, so the
    single-typist invariant holds and one's disconnect can't orphan the other."""
    s = Session()
    s.run_in_thread(lambda emit, readline: readline())  # block so the session stays alive
    path = _sock()
    srv = BusServer(s, path).start()

    a = BusClient(path).connect()
    a.hello("ai", "bot")
    na = a.wait_for("OK", 3)["name"]
    b = BusClient(path).connect()
    b.hello("ai", "bot")
    nb = b.wait_for("OK", 3)["name"]

    assert na == "bot" and nb != na  # the second 'bot' got a unique identity
    assert s.has_controller(na) and s.has_controller(nb)
    assert s.driver in (na, nb)  # one identity drives, not a shared name
    a.close()
    b.close()
    srv.stop()
