"""The synchronous CMD verb (send a line, get its output up to the next input
prompt) and the INFO `waiting` flag -- the two primitives the dogfood session
showed an AI driver needs. See [[sbterm-instrumentation]]."""

import os
import tempfile
import time

from tappty.bus import BusClient, BusServer
from tappty.session import Session


def _sock():
    return os.path.join(tempfile.mkdtemp(), "s")


def test_cmd_returns_command_output():
    def runner(emit, readline):
        emit("READY\r\n")
        while True:
            line = readline()
            if line.strip() == "quit":
                break
            emit(f"got {line.strip()}\r\n")

    s = Session()
    path = _sock()
    srv = BusServer(s, path).start()
    s.run_in_thread(runner)
    c = BusClient(path).connect()
    c.hello(role="ai", name="a")
    c.wait_for("OK", 2)
    time.sleep(0.3)  # let the program reach its first prompt

    resp = c.cmd("hello there")  # synchronous: returns the output
    assert resp is not None and "got hello there" in resp
    resp2 = c.cmd("again")
    assert "got again" in resp2
    c.cmd("quit")
    c.close()
    srv.stop()


def test_info_reports_waiting_flag():
    def runner(emit, readline):
        emit("PROMPT\r\n")
        readline()  # blocks here -> waiting becomes True

    s = Session()
    path = _sock()
    srv = BusServer(s, path).start()
    s.run_in_thread(runner)
    c = BusClient(path).connect()
    c.hello(role="ai", name="a")
    c.wait_for("OK", 2)

    c.send("INFO")
    info = None
    end = time.time() + 3
    while time.time() < end:  # poll until the program is blocked
        c.send("INFO")
        info = c.wait_for("INFO", 1)
        if info and info.get("waiting"):
            break
        time.sleep(0.1)
    assert info is not None and info["waiting"] is True
    c.close()
    srv.stop()
