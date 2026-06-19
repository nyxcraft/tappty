"""A terminal Session: hosts a program (a Source) with its terminal I/O wired to a
Terminal model, and exposes the instrumentation bus -- the observe/control contract
every client (a renderer, an AI, a logger) speaks.

Observe taps (subscribe to taste):
  on_stream(cb(text))      -- tap 1: RAW program output, pre-render (byte-lossless via a
                              latin-1 transport, temporal) -- the program's exact bytes
  on_frame(cb())           -- tap 2: the grid changed; call snapshot() to read it. The grid
                              is the output DECODED to characters (per the source's encoding)
  on_event(cb(name, info)) -- tap 3: WAIT (blocked on input), BELL, CLOSED
Control:
  send_input(text)         -- inject input into the program
  feed_key(ch)/feed_text   -- interactive keystrokes (local echo + line buffer)

The Source (engine, pty, ...) supplies the bytes; the Session fans them out to the
Terminal and the taps, and routes control back to the Source. A renderer is just a
client of this contract; an external socket front-end (later) registers socket-backed
taps + forwards input through the same methods. See [[sbterm-instrumentation]].
"""

import codecs
import threading

from tappty.source import EngineSource
from tappty.terminal import Terminal


class Session:
    def __init__(self, terminal=None, source=None):
        self.term = terminal or Terminal()
        self.source = source
        self.done = False
        self._line = []  # interactive keystroke -> line buffer
        self._stream_obs = []
        self._frame_obs = []
        self._event_obs = []
        self._lock = threading.RLock()
        self._controllers = {}  # name -> role ('human'|'ai'|...)
        self.driver = None  # name holding the talking stick (keyboard)
        self.waiting = False  # True while the program is blocked on input
        self._wire = None  # source's wire encoding (None = already text)
        self._decoder = None  # incremental decoder: raw bytes -> screen text

    # ---- observe taps ------------------------------------------------------
    def on_stream(self, cb):
        self._stream_obs.append(cb)
        return cb

    def on_frame(self, cb):
        self._frame_obs.append(cb)
        return cb

    def on_event(self, cb):
        self._event_obs.append(cb)
        return cb

    def snapshot(self):
        """The current grid + cursor (tap 2 payload)."""
        return {
            "rows": self.term.rows_text(),
            "cx": self.term.cx,
            "cy": self.term.cy,
            "cols": self.term.cols,
            "rows_n": self.term.rows,
        }

    # ---- Source callbacks (bytes in from the program) ----------------------
    def _output(self, raw):
        # `raw` is the program's output exactly as the source produced it: for a byte
        # source, a byte-transparent latin-1 str (so the stream tap is lossless). The
        # screen gets it decoded to characters per the source's wire encoding; observers
        # watching the stream get the raw bytes. (Called only on the source thread, so the
        # incremental decoder is accessed single-threaded.)
        for cb in list(self._stream_obs):  # tap 1: RAW program output (lossless, temporal)
            cb(raw)
        text = self._decoder.decode(raw.encode("latin-1")) if self._decoder else raw
        if text:
            with self._lock:
                self.term.write(text)  # screen: decoded characters
        for cb in list(self._frame_obs):  # tap 2: "something changed"
            cb()
        if "\a" in raw:  # BELL
            self._event("BELL")

    def _wait(self):
        self.waiting = True  # program is blocked for input
        self._event("WAIT")

    def _exit(self):
        self.done = True
        self._event("CLOSED")

    def _event(self, name, **info):
        for cb in list(self._event_obs):
            cb(name, info)

    # ---- the talking stick (control arbitration) ---------------------------
    def _set_driver(self, name):
        if self.driver != name:
            self.driver = name
            self._event("DRIVER", who=name)

    def claim_control(self, name, role="ai"):
        """Register a controller. The first one to claim becomes the driver (the
        launcher's player); later claims don't preempt -- they must take()."""
        self._controllers[name] = role
        if self.driver is None:
            self._set_driver(name)
        return name

    def take(self, name):
        """Grab the stick. You-privileged: a human/interactive controller can preempt
        anyone; an AI can take only from a free stick or another non-human."""
        if name not in self._controllers:
            return False
        cur = self.driver
        if cur is None or cur == name:
            self._set_driver(name)
            return True
        if self._controllers[name] in ("human", "interactive"):
            self._set_driver(name)
            return True
        if self._controllers.get(cur) not in ("human", "interactive"):
            self._set_driver(name)
            return True
        return False  # AI can't preempt a human

    def release(self, name):
        if self.driver == name:
            self.driver = None
            self._event("DRIVER", who=None)

    def drop_controller(self, name):
        """A controller disconnected/died -> auto-release the stick if it held it."""
        self._controllers.pop(name, None)
        self.release(name)

    def has_control(self, name):
        return self.driver == name

    def has_controller(self, name):
        """Is `name` a currently-registered controller? (Used by the bus to keep each
        connection's stick identity unique.)"""
        return name in self._controllers

    # ---- control -----------------------------------------------------------
    def send_input(self, text, by=None):
        """Inject input. `by=None` is trusted/internal; a named controller's input is
        applied only while it holds the stick. Returns whether it was applied."""
        applied = by is None or self.driver == by
        if applied and self.source is not None:
            self.waiting = False  # the program will resume on this input
            self.source.send_input(text)
        return applied

    def echo(self, text):
        """Show an injected command on the terminal (and to all observers), so a watcher
        sees what a remote controller 'typed' -- input via send_input/LINE isn't echoed by
        the program, unlike a locally-typed key. The text is synthetic (already characters),
        so it goes to the screen as-is and to the stream tap re-encoded to the wire form, to
        stay consistent with raw program output (without disturbing the program's decoder)."""
        s = text + "\r\n"
        raw = s.encode(self._wire, "replace").decode("latin-1") if self._wire else s
        for cb in list(self._stream_obs):  # stream: bytes (consistent with program output)
            cb(raw)
        with self._lock:
            self.term.write(s)  # screen: characters, as-is
        for cb in list(self._frame_obs):
            cb()

    def _echo_local(self, text):
        """Write locally-echoed keystrokes to the grid and notify FRAME observers, so a
        remote renderer/logger sees typed characters immediately (not only when later
        program output happens to fire a frame). Stream taps are not fed -- local echo is
        not program output, so on_stream stays a faithful record of the program's bytes."""
        with self._lock:
            self.term.write(text)
        for cb in list(self._frame_obs):
            cb()

    def feed_key(self, ch, by="local", auto_take=True):
        """An interactive keystroke: local echo + assemble a line, sending on Enter.
        `by` attributes it to a controller (default the local human at this session's
        own window); auto_take=True means typing implicitly grabs the stick (the local
        human preempts). A remote controller passes by=<name>, auto_take=False (it
        already TOOK the stick). Only the stick-holder's keys register -- the shared
        line buffer is safe since exactly one driver types at a time."""
        if auto_take:  # solo terminal: typing grabs the stick
            if by == "local" and "local" not in self._controllers:
                self.claim_control("local", "human")
            if self.driver != by:
                self.take(by)
        if not self.has_control(by):  # otherwise only the stick-holder types
            return
        if ch in ("\r", "\n"):
            self._echo_local("\r\n")
            self.send_input("".join(self._line) + "\n", by=by)
            self._line = []
        elif ch in ("\b", "\x7f"):
            if self._line:
                self._line.pop()
                self._echo_local("\b \b")
        elif ch.isprintable():
            self._line.append(ch)
            self._echo_local(ch)  # local echo (fans out a frame)

    def feed_text(self, s, **kw):
        for ch in s:
            self.feed_key(ch, **kw)

    # ---- lifecycle ---------------------------------------------------------
    def start(self):
        # Source.encoding formalizes the wire convention: a byte source (pty/pipe) gives its
        # wire encoding to decode raw bytes by for the screen; a text source leaves it None
        # (output is already characters, passed through). See Source in source.py.
        self._wire = self.source.encoding
        self._decoder = (
            codecs.getincrementaldecoder(self._wire)(errors="replace") if self._wire else None
        )
        self.source.start(self._output, self._wait, self._exit)

    def run_in_thread(self, runner=None):
        """Start the hosted program. A bare runner(emit, readline) is wrapped as an
        EngineSource (back-compat with the renderers/launchers)."""
        if runner is not None:
            self.source = EngineSource(runner)
        self.start()

    def run_blocking(self, runner=None):
        if runner is not None:
            self.source = EngineSource(runner)
        self.start()
        thread = getattr(self.source, "thread", None)
        if thread is not None:
            thread.join()
