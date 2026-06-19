"""PtySource (b-lite): host an arbitrary external program on a pseudo-terminal and
observe + control it through the Source seam -- the basis for driving real
SIMH/TOPS-10 (or any CLI) via the bus. See [[sbterm-instrumentation]]."""

import sys
import threading

from tappty.source import PtySource


def test_pty_source_observe_and_control():
    child = (
        "import sys\n"
        "print('READY', flush=True)\n"
        "for line in sys.stdin:\n"
        "    s = line.strip()\n"
        "    if s == 'quit':\n"
        "        break\n"
        "    print('echo', s, flush=True)\n"
    )
    out, ready, echoed, ended = [], threading.Event(), threading.Event(), threading.Event()

    def on_output(t):
        out.append(t)
        joined = "".join(out)
        if "READY" in joined:
            ready.set()
        if "echo hi" in joined:
            echoed.set()

    src = PtySource([sys.executable, "-c", child])
    src.start(on_output, lambda: None, ended.set)
    assert ready.wait(6), "child never started"
    src.send_input("hi\n")  # control it over the pty
    assert echoed.wait(6), "did not observe the child's echo"
    src.send_input("quit\n")
    assert ended.wait(6), "child did not exit / on_exit never fired"
    src.stop()
