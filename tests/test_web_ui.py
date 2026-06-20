"""The web renderer: the frame/key bridge (pure) and a real HTTP+WebSocket round-trip.

The bridge logic (RLE color frames, logical-key routing) is tested without a server. The
integration test runs the actual `web_ui.run` and drives it from a real `websockets` client,
so the HTTP page, the WS handler, and the keystroke->program->frame path all execute. It
skips when the `web` extra (`websockets`) isn't installed.
"""

import json

from tappty import web_ui
from tappty.session import Session
from tappty.source import Source
from tappty.terminal import Terminal


class _Rec(Source):  # records input that reaches the program
    def __init__(self):
        self.got = []

    def start(self, *a):
        pass

    def send_input(self, t):
        self.got.append(t)


def test_frame_json_is_rle_runs_with_hex_colors():
    from tappty.pyte_terminal import PyteTerminal

    p = PyteTerminal(20, 2)
    sess = Session(p)
    p.write("\x1b[31mRED\x1b[0m hi")
    fr = json.loads(web_ui._frame_json(sess))
    assert fr["t"] == "frame" and fr["cx"] >= 0 and len(fr["rows"]) == 2
    run0 = fr["rows"][0][0]  # [col, text, fg_hex, bg_hex]
    assert run0[0] == 0 and run0[1] == "RED" and run0[2] == "cd0000"  # red fg
    assert all(len(run[2]) == 6 and len(run[3]) == 6 for row in fr["rows"] for run in row)


def test_handle_key_routes_raw_vs_line():
    # raw mode: printable, named, and ctrl keys all go through as bytes
    rec = _Rec()
    s = Session(Terminal(20, 2), source=rec)
    s.claim_control("web-1", "human")
    s.raw_keys = True
    for k in ("x", "up", "ctrl-c", "enter"):
        web_ui._handle_key(s, "web-1", json.dumps({"t": "key", "k": k}))
    assert rec.got == ["x", "\x1b[A", "\x03", "\r"]

    # line mode: only printable + enter/backspace; specials are ignored
    rec2 = _Rec()
    s2 = Session(Terminal(20, 2), source=rec2)
    s2.claim_control("web-1", "human")  # line mode (raw_keys False by default)
    for k in ("h", "up", "i", "enter"):  # the "up" must be dropped
        web_ui._handle_key(s2, "web-1", json.dumps({"t": "key", "k": k}))
    # h, i echoed+buffered locally; Enter sends the assembled line
    assert rec2.got == ["hi\n"]


def test_handle_key_ignores_malformed():
    rec = _Rec()
    s = Session(Terminal(20, 2), source=rec)
    s.claim_control("web-1", "human")
    s.raw_keys = True
    for bad in ("not json", json.dumps({"t": "nope"}), json.dumps({"t": "key"})):
        web_ui._handle_key(s, "web-1", bad)  # must not raise
    assert rec.got == []


def _free_port():
    import socket

    for _ in range(20):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        s.close()
        s2 = socket.socket()
        try:
            s2.bind(("127.0.0.1", p + 1))  # web_ui uses port and port+1
            s2.close()
            return p
        except OSError:
            s2.close()
    return p


def test_web_ui_refuses_non_loopback_without_allow_remote():
    import pytest

    s = Session(Terminal(80, 24))
    with pytest.raises(ValueError):
        web_ui.run(s, None, host="0.0.0.0")  # would expose an unauthenticated terminal


def test_web_ui_rejects_cross_origin_websocket():
    """A site the user merely visits must not be able to drive the terminal (CSWSH): a forged
    cross-origin WS is closed before it touches the session; the page's own origin is accepted."""
    import pytest

    pytest.importorskip("websockets")
    import threading
    import time
    import urllib.request

    from websockets.exceptions import ConnectionClosed
    from websockets.sync.client import connect

    from tappty.source import EngineSource

    sess = Session(Terminal(80, 24), source=EngineSource(lambda emit, readline: emit("hi")))
    port = _free_port()
    th = threading.Thread(
        target=web_ui.run,
        kwargs=dict(session=sess, runner=None, port=port, max_seconds=2),
        daemon=True,
    )
    th.start()
    deadline = time.time() + 3
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1).read()
            break
        except OSError:
            time.sleep(0.1)

    try:
        evil = connect(f"ws://127.0.0.1:{port + 1}/", origin="http://evil.example")
        with pytest.raises(ConnectionClosed):
            evil.recv(timeout=2)  # rejected -> closed, no frame
        evil.close()

        ok = connect(f"ws://127.0.0.1:{port + 1}/", origin=f"http://127.0.0.1:{port}")
        assert json.loads(ok.recv(timeout=2))["t"] == "frame"  # same origin -> served
        ok.close()
    finally:
        th.join(timeout=6)


def test_web_ui_serves_and_round_trips():
    import pytest

    pytest.importorskip("websockets")
    import threading
    import time
    import urllib.request

    from websockets.sync.client import connect

    from tappty.source import EngineSource

    def runner(emit, readline):
        emit("READY> ")
        while True:
            line = readline()
            emit("\r\n" + line.strip().upper() + "\r\n> ")

    sess = Session(Terminal(80, 24), source=EngineSource(runner))
    port = _free_port()
    th = threading.Thread(
        target=web_ui.run,
        kwargs=dict(session=sess, runner=None, port=port, max_seconds=2),
        daemon=True,
    )
    th.start()

    page = None
    deadline = time.time() + 3
    while time.time() < deadline:
        try:
            page = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1).read().decode()
            break
        except OSError:
            time.sleep(0.1)
    assert page and "<canvas" in page and str(port + 1) in page

    c = connect(f"ws://127.0.0.1:{port + 1}/")
    try:
        f0 = json.loads(c.recv())
        assert f0["t"] == "frame" and len(f0["rows"]) == 24
        for ch in "hi":
            c.send(json.dumps({"t": "key", "k": ch}))
        c.send(json.dumps({"t": "key", "k": "enter"}))
        got = ""
        for _ in range(40):  # collect frames until the program's echo appears (bounded)
            try:
                fr = json.loads(c.recv(timeout=0.2))
                got = "\n".join("".join(run[1] for run in row) for row in fr["rows"])
                if "HI" in got:
                    break
            except TimeoutError:
                pass
        assert "HI" in got  # the keystrokes reached the program and its output came back
    finally:
        c.close()
        th.join(timeout=6)
