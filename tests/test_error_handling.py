"""Error-path behavior: child exit codes, observer isolation, runner-failure surfacing,
CMD timeout signaling, and PTY spawn cleanup."""

import os
import sys
import tempfile
import threading
import time

import pytest

from tappty.bus import BusClient, BusServer
from tappty.cli import main
from tappty.session import Session
from tappty.source import PtySource
from tappty.terminal import Terminal


# ---- child exit-code propagation through `tapterm --headless` ----------------
def test_headless_propagates_pty_exit_code():
    assert main(["--headless", "--", "sh", "-c", "exit 7"]) == 7


def test_headless_propagates_pipe_exit_code():
    assert main(["--no-pty", "--headless", "--", "sh", "-c", "exit 9"]) == 9


def test_headless_success_is_zero():
    assert main(["--headless", "--", "sh", "-c", "exit 0"]) == 0


# ---- terminal dimension validation ------------------------------------------
def test_terminal_rejects_nonpositive_dimensions():
    with pytest.raises(ValueError):
        Terminal(cols=0)
    with pytest.raises(ValueError):
        Terminal(rows=0)


def test_cli_rejects_nonpositive_dimensions():
    with pytest.raises(SystemExit):  # argparse rejects --cols 0 before running anything
        main(["--cols", "0", "--headless", "--", "true"])


# ---- API guards from the focused reviews ------------------------------------
def test_bus_send_rejects_non_string_payload():
    from tappty.bus import BusClient

    c = BusClient("unused-path")  # not connected: the type check fires before any socket use
    with pytest.raises(TypeError):
        c.send("KEY", 123)


def test_renderers_reject_nonpositive_fps():
    from tappty import compositor, pygame_ui

    with pytest.raises(ValueError):  # checked before any pygame import
        pygame_ui.run(None, None, fps=0)
    with pytest.raises(ValueError):
        compositor.run([], fps=0)


@pytest.mark.skipif(sys.platform != "linux", reason="X11/Wayland display heuristic is Linux-only")
def test_default_mode_is_cui_without_a_display(monkeypatch):
    import tappty.cli as cli

    monkeypatch.setattr(cli, "_have_pygame", lambda: True)
    for var in ("DISPLAY", "WAYLAND_DISPLAY", "SDL_VIDEODRIVER"):
        monkeypatch.delenv(var, raising=False)
    assert cli._default_mode() == "cui"  # headless -> don't pick a GUI that would fail
    monkeypatch.setenv("DISPLAY", ":0")
    assert cli._default_mode() == "gui"


# ---- observer failure isolation ---------------------------------------------
def test_observer_exception_is_isolated():
    sess = Session(Terminal(80, 24))
    state = {"good": 0, "errors": 0}

    def bad():
        raise RuntimeError("boom")

    def good():
        state["good"] += 1

    sess.on_frame(bad)  # registered first -> raises during fan-out
    sess.on_frame(good)  # must still be called despite the one above
    sess.on_event(
        lambda n, i: state.__setitem__("errors", state["errors"] + 1) if n == "ERROR" else None
    )

    sess.run_blocking(lambda emit, readline: emit("hello"))
    assert sess.term.rows_text()[0].startswith("hello")  # output still rendered
    assert state["good"] >= 1  # the good observer ran anyway
    assert state["errors"] >= 1  # and the failure left an ERROR breadcrumb


def test_session_stop_unblocks_a_blocked_engine_runner():
    started = threading.Event()

    def runner(emit, readline):
        emit("READY")
        started.set()
        readline()  # blocks here until stop() unwinds it
        emit("got input")  # must NOT run after a stop

    sess = Session(Terminal(80, 24))
    sess.run_in_thread(runner)
    assert started.wait(2)
    sess.stop()
    sess.source.thread.join(timeout=2)
    assert not sess.source.thread.is_alive()  # the blocked runner was unwound
    assert "got input" not in sess.term.rows_text()[0]  # unwound, not fed a fake line


def test_run_blocking_reraises_runner_exception():
    seen = []

    def bad_runner(emit, readline):
        emit("partial")
        raise ValueError("runner failed")

    sess = Session(Terminal(80, 24))
    sess.on_event(lambda n, i: seen.append(n))
    with pytest.raises(ValueError, match="runner failed"):
        sess.run_blocking(bad_runner)
    assert "ERROR" in seen  # observers were told too
    assert sess.term.rows_text()[0].startswith("partial")  # output before the failure stuck


# ---- bus CMD timeout signaling ----------------------------------------------
def test_cmd_timeout_is_signaled():
    def runner(emit, readline):
        readline()  # consume the CMD's input...
        emit("partial output")  # ...emit, but never block on input again -> no WAIT
        time.sleep(2)

    s = Session()
    sock = os.path.join(tempfile.mkdtemp(), "s")
    srv = BusServer(s, sock, cmd_timeout=0.4).start()  # short timeout for the test
    s.run_in_thread(runner)

    c = BusClient(sock).connect()
    c.hello("ai", "bot")  # first controller -> holds the stick
    assert c.wait_for("OK", 3)
    time.sleep(0.2)  # let the runner reach its readline
    c.send("CMD", "go")
    resp = c.wait_for("RESP", 3)
    assert resp is not None
    assert resp.get("timeout") is True  # distinguishable from a clean completion
    assert "partial output" in resp.get("text", "")  # partial output is still returned
    c.close()
    srv.stop()


# ---- PTY spawn cleanup on Popen failure -------------------------------------
def test_pty_spawn_failure_cleans_up_and_raises():
    src = PtySource(["/nonexistent/definitely-not-a-real-binary-xyz"])

    def noop(*a):
        return None

    with pytest.raises(OSError):  # FileNotFoundError is an OSError
        src.start(noop, noop, noop)
    assert src.master is None  # the pty master fd was closed, not leaked
