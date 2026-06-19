"""The instrumentation bus over TCP (the cross-platform / Windows transport): same
contract as the Unix-socket bus, addressed by a (host, port) tuple. Port 0 lets the OS
pick a free port; the client connects to the actually-bound port. See docs/WINDOWS.md."""

import threading

from tappty.bus import BusClient, BusServer
from tappty.session import Session


def test_tcp_snapshot_and_control():
    waited, closed = threading.Event(), threading.Event()

    def runner(emit, readline):
        emit("HELLO\r\n")
        line = readline()
        emit(f"GOT {line.strip()}\r\n")

    s = Session()
    s.on_event(
        lambda n, i: waited.set() if n == "WAIT" else (closed.set() if n == "CLOSED" else None)
    )
    srv = BusServer(s, ("127.0.0.1", 0)).start()  # OS-assigned port
    host, port = srv.addr  # the actual bound (host, port)
    s.run_in_thread(runner)
    assert waited.wait(3)

    c = BusClient((host, port)).connect()
    c.hello("controller", "tester")
    frame = c.snap()  # observe the screen over TCP
    assert frame and frame["rows"][0].startswith("HELLO")

    c.line("WORLD")  # control it over TCP
    assert closed.wait(3)
    frame2 = c.snap()
    assert any(r.startswith("GOT WORLD") for r in frame2["rows"])
    c.close()
    srv.stop()
