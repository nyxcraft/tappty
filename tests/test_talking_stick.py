"""Control arbitration -- the talking stick: one driver at a time, you-privileged
preemption (a human can take from an AI; an AI can't take from a human), and
auto-release when a controller drops. See docs/DESIGN.md."""

import os
import tempfile
import time

from tappty.bus import BusClient, BusServer
from tappty.session import Session
from tappty.source import Source


class _Rec(Source):  # records what input reaches the program
    def __init__(self):
        self.got = []

    def start(self, *a):
        pass

    def send_input(self, t):
        self.got.append(t)


def test_stick_policy():
    s = Session()
    s.claim_control("ai1", "ai")
    assert s.driver == "ai1"  # first claim = driver
    s.claim_control("ai2", "ai")
    assert s.driver == "ai1"  # claim doesn't preempt
    assert s.take("ai2") and s.driver == "ai2"  # ai can take from ai
    s.claim_control("human", "human")
    assert s.take("human") and s.driver == "human"  # human preempts
    assert s.take("ai1") is False and s.driver == "human"  # ai CAN'T preempt human
    s.release("human")
    assert s.driver is None
    assert s.take("ai1") and s.driver == "ai1"  # free stick -> anyone
    s.drop_controller("ai1")
    assert s.driver is None  # disconnect auto-releases


def test_input_gating():
    rec = _Rec()
    s = Session(source=rec)
    s.claim_control("a", "ai")
    assert s.send_input("x\n", by="a") and rec.got == ["x\n"]  # driver -> applied
    s.claim_control("b", "ai")
    assert s.send_input("y\n", by="b") is False  # non-driver -> denied
    assert rec.got == ["x\n"]
    assert s.send_input("z\n") and rec.got == ["x\n", "z\n"]  # by=None trusted/internal


def test_claim_control_unique_suffix_is_atomic_dedup():
    # The bus needs a per-connection-unique stick name without a check-then-claim race: a
    # unique_suffix is appended (under one lock) only when the name is already taken.
    s = Session()
    a = s.claim_control("bot", "ai", unique_suffix="#c1")
    b = s.claim_control("bot", "ai", unique_suffix="#c2")
    assert a == "bot" and b == "bot#c2" and a != b  # distinct identities
    assert s.driver == a  # the first claimant stays the driver


def test_send_key_is_raw_stick_gated_and_unechoed():
    from tappty.terminal import Terminal

    rec = _Rec()
    s = Session(Terminal(20, 2), source=rec)
    s.claim_control("drv", "ai")  # first claim -> driver
    # raw bytes reach the program verbatim -- no line buffering, no newline appended
    assert s.send_key("\x1b[A", by="drv", auto_take=False) is True
    assert rec.got == ["\x1b[A"]
    # and NOT echoed to the screen (unlike feed_key): the program redraws itself
    assert s.term.rows_text()[0].strip() == ""
    # gated like other input: a non-driver's raw key is dropped
    s.claim_control("other", "ai")
    assert s.send_key("x", by="other", auto_take=False) is False
    assert rec.got == ["\x1b[A"]


def test_socket_arbitration():
    def runner(emit, readline):
        emit("READY\r\n")
        while True:
            line = readline()
            if line.strip() == "QUIT":
                break
            emit(f"echo {line.strip()}\r\n")

    s = Session()
    path = os.path.join(tempfile.mkdtemp(), "s")
    srv = BusServer(s, path).start()
    s.run_in_thread(runner)

    a = BusClient(path).connect()
    a.hello(role="ai", name="a")
    assert a.wait_for("OK", 2)
    b = BusClient(path).connect()
    b.hello(role="ai", name="b")
    assert b.wait_for("OK", 2)
    assert s.driver == "a"  # a claimed first -> default driver

    a.sub()
    time.sleep(0.2)
    b.line("nope")
    assert b.wait_for("DENIED", 2) is not None  # b isn't the driver
    b.take()
    assert b.wait_for("OK", 2) is not None and s.driver == "b"  # ai-from-ai allowed

    b.line("hi")  # now b drives
    saw, end = False, time.monotonic() + 3
    while time.monotonic() < end and not saw:
        try:
            v, d = a.inbox.get(timeout=end - time.monotonic())
        except Exception:
            break
        if v == "OUT" and isinstance(d, str) and "echo hi" in d:
            saw = True
    assert saw, "subscribed observer never saw b's output"
    b.line("QUIT")
    a.close()
    b.close()
    srv.stop()
