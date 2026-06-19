"""Program *sources* for a Session: something that produces terminal output and
consumes input. The bus, Terminal, observe-taps, and control are identical no
matter where the bytes come from -- only the Source differs:

  * EngineSource  -- an in-process runner: a `runner(emit, readline)` callable.
  * PtySource     -- an external program on a pseudo-terminal (POSIX).
  * PipeSource    -- an external program over plain pipes, no pty (any OS).
  * ConPtySource  -- an external program on a Windows pseudo-console (ConPTY, pywinpty).
  * CastSource    -- replay of a recorded asciinema .cast session (no live program).

A Source is driven by three callbacks supplied at start():
  on_output(text) -- the program emitted output (pre-render)
  on_wait()       -- the program is blocked waiting for input ("your turn")
  on_exit()       -- the program ended
and accepts input via send_input(text).

Bytes vs text (see Source.encoding): a *byte source* (pty/pipe/ConPTY) reads raw bytes
and hands them up as a byte-transparent latin-1 str -- lossless on the stream tap -- and
declares the wire `encoding` the Session decodes by for the screen. A *text source*
(engine/cast) emits real characters and leaves `encoding` None (no decode). See
[[sbterm-instrumentation]].
"""

import json
import os
import queue
import threading


class Source:
    # The wire encoding of this source's raw output, or None if it already emits text.
    # A byte source sets it (e.g. "utf-8"); the Session reads it to decode bytes -> screen
    # characters while keeping the stream tap byte-lossless. None => emit-as-text, no decode.
    encoding = None

    def start(self, on_output, on_wait, on_exit):
        raise NotImplementedError

    def send_input(self, text):
        raise NotImplementedError

    def stop(self):
        pass


class EngineSource(Source):
    """Wraps a runner(emit, readline) -- our interpreter / bot / monitor. `emit`
    output is forwarded to on_output; the first thing the program does when it wants
    input is call readline, which fires on_wait() and blocks until send_input()
    supplies a line; on_exit() fires when the runner returns (or raises)."""

    def __init__(self, runner):
        self.runner = runner
        self._inq = queue.Queue()
        self.thread = None

    def start(self, on_output, on_wait, on_exit):
        def readline():
            on_wait()  # program is now blocked for input
            return self._inq.get()

        def go():
            try:
                self.runner(on_output, readline)
            finally:
                on_exit()

        self.thread = threading.Thread(target=go, daemon=True)
        self.thread.start()

    def send_input(self, text):
        self._inq.put(text)


class PtySource(Source):
    """Hosts an arbitrary external program on a real pseudo-terminal. The child's raw
    output bytes are forwarded to on_output as a byte-transparent latin-1 str -- lossless,
    so a *stream* observer sees exactly the program's bytes; the Session decodes them to
    characters for the *screen* using `encoding` (default UTF-8). send_input encodes
    keystrokes with the same `encoding`. on_exit fires when the child ends; on_wait is NOT
    fired -- a pty gives no readline boundary, so an observer reads the stream/grid instead.
    This is what lets you observe+control any terminal program (e.g. real SIMH/TOPS-10);
    pair with the VT52 `Terminal` for period children or `PyteTerminal` (--ansi) for modern
    ANSI. See [[sbterm-instrumentation]]."""

    def __init__(self, argv, cwd=None, env=None, size=(24, 80), encoding="utf-8"):
        self.argv = list(argv)
        self.cwd = cwd
        self.env = env
        self.size = size
        self.encoding = encoding  # wire encoding: Session decodes the screen by it
        self.master = None
        self.proc = None
        self.thread = None
        self._running = False

    def start(self, on_output, on_wait, on_exit):
        import fcntl
        import pty
        import struct
        import subprocess
        import termios

        self.master, slave = pty.openpty()
        rows, cols = self.size
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass
        self.proc = subprocess.Popen(
            self.argv,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=self.cwd,
            env=self.env,
            start_new_session=True,
            close_fds=True,
        )
        os.close(slave)
        self._running = True

        def reader():
            try:
                while self._running:
                    try:
                        data = os.read(self.master, 4096)
                    except OSError:
                        break
                    if not data:
                        break
                    on_output(data.decode("latin-1"))  # raw bytes, lossless (Session decodes)
            finally:
                self._running = False
                on_exit()

        self.thread = threading.Thread(target=reader, daemon=True)
        self.thread.start()

    def send_input(self, text):
        if self.master is not None:
            try:
                os.write(self.master, text.encode(self.encoding, "replace"))
            except OSError:
                pass

    def stop(self):
        self._running = False
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass
        if self.master is not None:
            try:
                os.close(self.master)
            except OSError:
                pass


class CastSource(Source):
    """Replays a recorded asciinema .cast session through the normal pipeline.

    What it does: emits the recorded output events with their original timing (scaled by
    `speed`, idle gaps optionally capped by `idle_time_limit`; `loop=True` repeats until
    stop()), so a recording streams through the exact same Terminal/Session/renderer path a
    live program would -- which also makes a render reproducible (no live subprocess). It is
    a text source (emits characters; no decode). Input is ignored (you can't type into the
    past) and on_wait is not fired (a recording has no input boundary). The recorded
    width/height are exposed on `.width`/`.height` so the caller can size the Terminal first.

    Supported formats: asciicast v2 (newline-delimited JSON: a header object
    `{"version": 2, "width": .., "height": ..}` then `[time, code, data]` events, where code
    "o" is terminal output -- the only kind replayed; "i"/"m"/"r" are skipped -- and time is
    seconds from the start) and compact v1 (`{"version": 1, "width", "height", "stdout":
    [[delay, data], ...]}`). See [[sbterm-instrumentation]]."""

    def __init__(self, path, speed=1.0, idle_time_limit=None, loop=False):
        self.path = path
        self.speed = speed if speed and speed > 0 else 1.0
        self.idle_time_limit = idle_time_limit
        self.loop = loop
        self.thread = None
        self._running = False
        self._wake = threading.Event()  # set by stop() to interrupt an idle sleep
        self.version = 2
        self.width, self.height = 80, 24
        self._events_v1 = None  # set when the file is (compact/pretty) v1
        self._read_header()

    def _read_header(self):
        with open(self.path, encoding="utf-8") as f:
            first = f.readline()
        try:
            head = json.loads(first)
        except ValueError:
            head = None
        if isinstance(head, dict) and head.get("version", 0) >= 2 and "stdout" not in head:
            self.version = int(head["version"])  # v2 (or later): stream lines
            self.width = int(head.get("width", 80))
            self.height = int(head.get("height", 24))
            return
        with open(self.path, encoding="utf-8") as f:  # v1: the file is one object
            doc = json.load(f)
        self.version = 1
        self.width = int(doc.get("width", 80))
        self.height = int(doc.get("height", 24))
        self._events_v1 = doc.get("stdout", [])  # [[delay, data], ...]

    def _events(self):
        """Yield (abs_time, data) for each *output* event, abs_time = seconds from start."""
        if self._events_v1 is not None:  # v1: delays are relative
            t = 0.0
            for item in self._events_v1:
                if item:
                    t += float(item[0])
                    yield t, item[1]
            return
        with open(self.path, encoding="utf-8") as f:  # v2: skip header, stream
            f.readline()
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, list) and len(ev) >= 3 and ev[1] == "o":
                    yield float(ev[0]), ev[2]

    def start(self, on_output, on_wait, on_exit):
        def play():
            try:
                while self._running:
                    prev = 0.0
                    for t, data in self._events():
                        if not self._running:
                            return
                        gap = t - prev
                        if self.idle_time_limit is not None and gap > self.idle_time_limit:
                            gap = self.idle_time_limit  # cap a long pause
                        delay = gap / self.speed
                        if delay > 0 and self._wake.wait(delay):
                            return  # stop() interrupted the wait
                        prev = t
                        on_output(data)
                    if not self.loop:
                        break
            finally:
                self._running = False
                on_exit()

        self._running = True
        self._wake.clear()
        self.thread = threading.Thread(target=play, daemon=True)
        self.thread.start()

    def send_input(self, text):
        pass  # a recording can't be typed into

    def stop(self):
        self._running = False
        self._wake.set()  # wake a thread sleeping between events


class PipeSource(Source):
    """Hosts an external program over plain pipes -- no pseudo-terminal. Cross-platform
    (POSIX and Windows) and zero extra deps: subprocess.Popen, a reader thread forwarding
    stdout (+stderr) to on_output, and send_input -> stdin. This is the "non-pty Source"
    of docs/WINDOWS.md -- use it where a pty isn't available or isn't wanted. Caveat: with
    no tty the child detects it is not interactive, so many programs block-buffer output
    and skip prompts/raw mode; it suits cooperative, line-oriented programs. Output is
    forwarded raw (byte-transparent latin-1, lossless on the stream tap); the Session decodes
    it for the screen per `encoding` (default UTF-8). on_wait is not fired (no readline
    boundary, like PtySource)."""

    def __init__(self, argv, cwd=None, env=None, encoding="utf-8"):
        self.argv = list(argv)
        self.cwd = cwd
        self.env = env
        self.encoding = encoding  # wire encoding: Session decodes the screen by it
        self.proc = None
        self.thread = None
        self._running = False

    def start(self, on_output, on_wait, on_exit):
        import subprocess

        self.proc = subprocess.Popen(
            self.argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=self.cwd,
            env=self.env,
            bufsize=0,
        )
        self._running = True

        def reader():
            try:
                while self._running:
                    data = self.proc.stdout.read(4096)  # raw (bufsize=0): returns what's ready
                    if not data:
                        break
                    on_output(data.decode("latin-1"))  # raw bytes, lossless (Session decodes)
            finally:
                self._running = False
                on_exit()

        self.thread = threading.Thread(target=reader, daemon=True)
        self.thread.start()

    def send_input(self, text):
        if self.proc is not None and self.proc.stdin is not None:
            try:
                self.proc.stdin.write(text.encode(self.encoding, "replace"))
                self.proc.stdin.flush()
            except (OSError, ValueError):
                pass

    def stop(self):
        self._running = False
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass


class ConPtySource(Source):
    """Hosts an external program on a Windows pseudo-console (ConPTY) via pywinpty -- the
    Windows counterpart to PtySource. The child's output (already ANSI/VT100+, as ConPTY
    emits) is forwarded to on_output; pair this with `PyteTerminal` (`tapterm --ansi`) to
    render it, since the VT52 Terminal can't. send_input writes to the console; on_exit
    fires when the child ends; on_wait is not fired (no readline boundary). Needs the 'win'
    extra (pywinpty) and Windows 10 / Server 2019+ -- see docs/WINDOWS.md.

    NOTE: written against the pywinpty `PtyProcess` API and structurally mirrors PtySource,
    but it is UNTESTED from the POSIX dev environment (no ConPTY, and pywinpty does not
    install off-Windows). Treat as provisional until exercised on real Windows."""

    def __init__(self, argv, cwd=None, env=None, size=(24, 80)):
        self.argv = list(argv)
        self.cwd = cwd
        self.env = env
        self.size = size
        self.proc = None
        self.thread = None
        self._running = False

    def start(self, on_output, on_wait, on_exit):
        from winpty import PtyProcess  # pip install 'tappty[win]'  (pywinpty)

        rows, cols = self.size
        self.proc = PtyProcess.spawn(
            self.argv, cwd=self.cwd, env=self.env, dimensions=(rows, cols)
        )
        self._running = True

        def reader():
            try:
                while self._running and self.proc.isalive():
                    try:
                        data = self.proc.read(4096)  # pywinpty returns str (already decoded)
                    except EOFError:
                        break
                    if not data:
                        break
                    on_output(data)
            finally:
                self._running = False
                on_exit()

        self.thread = threading.Thread(target=reader, daemon=True)
        self.thread.start()

    def send_input(self, text):
        if self.proc is not None:
            try:
                self.proc.write(text)
            except (OSError, EOFError):
                pass

    def stop(self):
        self._running = False
        if self.proc is not None:
            try:
                self.proc.terminate(force=True)
            except Exception:
                pass
