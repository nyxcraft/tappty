"""The instrumentation bus over a Unix socket: an out-of-process client observes a
Session's screen and injects input. Short tmpdir socket paths (AF_UNIX has a ~108
char limit)."""

import os
import tempfile
import threading
import time

from tappty.bus import BusClient, BusServer
from tappty.session import Session


def _sock():
    return os.path.join(tempfile.mkdtemp(), "s")


def test_stop_unsubscribes_session_taps():
    """start() registers 3 Session taps; stop() must remove them so a stopped server
    doesn't linger as a stale observer on a long-lived Session."""
    s = Session()
    base = (len(s._stream_obs), len(s._frame_obs), len(s._event_obs))
    srv = BusServer(s, _sock()).start()
    assert (len(s._stream_obs), len(s._frame_obs), len(s._event_obs)) == tuple(n + 1 for n in base)
    srv.stop()
    assert (len(s._stream_obs), len(s._frame_obs), len(s._event_obs)) == base


def test_stop_drops_clients_and_releases_the_stick():
    """stop() must close accepted client connections and release any stick they held."""
    s = Session()
    s.run_in_thread(lambda emit, readline: readline())  # keep the session alive
    path = _sock()
    srv = BusServer(s, path).start()
    c = BusClient(path).connect()
    c.hello("ai", "bot")
    assert c.wait_for("OK", 2)
    assert s.driver == "bot"  # the controller holds the stick
    srv.stop()
    assert srv._conns == {}  # client connection state cleared
    assert s.driver is None  # its claimed stick was released
    c.close()


def test_stop_before_start_is_safe_and_restartable():
    s = Session()
    path = _sock()
    srv = BusServer(s, path)
    srv.stop()  # before start(): no socket yet -> must not raise
    srv.start()
    srv.stop()
    srv.start()  # restart after stop(): taps re-registered, not doubled
    assert len(s._stream_obs) == 1
    srv.stop()


def test_stop_wakes_a_pending_cmd_capture():
    """A CMD blocked waiting for the next prompt must be woken by stop(), not linger to
    cmd_timeout. Observed server-side: the capture is removed promptly after stop()."""

    def runner(emit, readline):
        readline()  # consume the CMD input, then never prompt again
        time.sleep(30)

    s = Session()
    path = _sock()
    srv = BusServer(s, path, cmd_timeout=30).start()  # long timeout: would linger 30s
    s.run_in_thread(runner)
    c = BusClient(path).connect()
    c.hello("ai", "bot")
    assert c.wait_for("OK", 2)
    time.sleep(0.2)
    c.send("CMD", "go")  # raw send: the CMD thread will block on the capture event
    time.sleep(0.3)
    assert len(srv._captures) == 1  # one capture in flight
    srv.stop()
    end = time.monotonic() + 3  # woken capture is removed well before cmd_timeout (30s)
    while srv._captures and time.monotonic() < end:
        time.sleep(0.02)
    assert srv._captures == []
    c.close()


def test_stop_does_not_deliver_partial_output_as_a_clean_resp():
    """A CMD interrupted by stop() must not report its partial output as a clean result
    (cap.ev is reused for both 'reached prompt' and 'shutdown' -> needs the cancelled flag)."""

    def runner(emit, readline):
        readline()  # the CMD input
        emit("partial output")  # produced, but no next prompt follows
        time.sleep(30)

    s = Session()
    path = _sock()
    srv = BusServer(s, path, cmd_timeout=30).start()
    s.run_in_thread(runner)
    c = BusClient(path).connect()
    c.hello("ai", "bot")
    assert c.wait_for("OK", 2)
    time.sleep(0.2)

    result = {}

    def do_cmd():
        try:
            result["text"] = c.cmd("go", timeout=2)  # clean result -> text; else None/raises
        except TimeoutError:
            result["timeout"] = True

    t = threading.Thread(target=do_cmd, daemon=True)
    t.start()
    time.sleep(0.3)  # let the CMD capture "partial output" and block on the event
    srv.stop()
    t.join(timeout=4)
    assert not t.is_alive()
    # interrupted -> the client either saw timeout, or got no RESP (None); never a clean
    # RESP carrying the partial text.
    assert result.get("timeout") or result.get("text") is None
    assert "partial output" not in (result.get("text") or "")
    c.close()


def test_stop_does_not_relabel_an_already_completed_capture():
    """If a capture reached a real prompt before stop() runs, stop() must not cancel it
    (the completion-then-shutdown race), so its result stays clean."""
    from tappty.bus import _Capture

    s = Session()
    srv = BusServer(s, _sock()).start()
    cap = _Capture()
    srv._captures.append(cap)
    srv._on_event("WAIT", {})  # the command reached a real prompt first
    assert cap.completed is True
    srv.stop()  # shutdown lands afterwards
    assert cap.cancelled is False  # not relabelled -> _h_cmd reports it clean
    assert cap.completed is True


def test_stop_cancels_an_incomplete_capture():
    """A capture still waiting when stop() runs is cancelled (the interrupted case)."""
    from tappty.bus import _Capture

    s = Session()
    srv = BusServer(s, _sock()).start()
    cap = _Capture()
    srv._captures.append(cap)
    srv.stop()  # shutdown before any prompt
    assert cap.cancelled is True
    assert cap.completed is False


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
