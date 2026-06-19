"""The sbterm instrumentation bus on Session: the three observe taps (raw stream /
grid frame / events) and the control path, over the Source seam. A tiny fake
runner stands in for the engine; threading.Events keep it deterministic.
See [[sbterm-instrumentation]]."""

import threading

from tappty.session import Session
from tappty.source import EngineSource


def test_bus_taps_observe_and_control():
    waited, closed = threading.Event(), threading.Event()
    stream, frames, events = [], [], []

    def runner(emit, readline):  # a minimal "program"
        emit("HELLO\r\n")
        line = readline()  # blocks -> fires WAIT
        emit(f"GOT {line.strip()}\r\n")

    s = Session()
    s.on_stream(stream.append)  # tap 1
    s.on_frame(lambda: frames.append(1))  # tap 2

    def ev(name, info):  # tap 3
        events.append(name)
        if name == "WAIT":
            waited.set()
        if name == "CLOSED":
            closed.set()

    s.on_event(ev)

    s.run_in_thread(runner)

    assert waited.wait(3), "WAIT never fired"
    assert "HELLO" in "".join(stream)  # tap 1 saw the raw output
    assert s.snapshot()["rows"][0].startswith("HELLO")  # tap 2 grid reflects it
    assert frames  # tap 2 fired

    s.send_input("WORLD\n")  # control
    assert closed.wait(3), "program never finished"
    assert "GOT WORLD" in "".join(stream)
    assert events[0] == "WAIT" and events[-1] == "CLOSED"
    assert s.done is True


def test_bell_event_from_output():
    rang = threading.Event()
    s = Session()
    s.on_event(lambda name, info: rang.set() if name == "BELL" else None)
    # drive the source callback directly: a program that emits a BELL then ends
    s.run_in_thread(lambda emit, readline: emit("ding\a"))
    assert rang.wait(3)


def test_engine_source_routes_input_to_program():
    got = []
    done = threading.Event()

    def runner(emit, readline):
        got.append(readline().strip())
        done.set()

    src = EngineSource(runner)
    s = Session(source=src)
    s.start()
    s.send_input("PING\n")
    assert done.wait(3) and got == ["PING"]
