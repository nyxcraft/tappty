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
(engine/cast) emits real characters and leaves `encoding` None (no decode). See docs/DESIGN.md.
"""

import contextlib
import json
import os
import queue
import struct
import threading

MAX_CAST_DIM = 1000  # clamp untrusted .cast width/height (grid alloc = cols*rows cells)
MAX_CAST_LINE = 1 << 20  # max bytes per .cast line read (untrusted-input guard)
MAX_CAST_FILE = 16 << 20  # max .cast file size for the unstreamable v1 path (json.load all)
_TTYREC_HEADER = struct.Struct("<III")  # ttyrec record header: sec, usec, length (LE uint32)
MAX_TTYREC_CHUNK = 1 << 24  # max bytes per ttyrec record (untrusted-input guard)


def _cast_dim(value, default):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(MAX_CAST_DIM, n))


_STOP = object()  # sentinel EngineSource.stop() pushes to unblock a runner in readline()


class _StopRunner(BaseException):
    """Raised inside a runner (via readline) when EngineSource.stop() is called, to unwind it
    cleanly. A BaseException so a runner's `except Exception` can't accidentally swallow it."""


class Source:
    # The wire encoding of this source's raw output, or None if it already emits text.
    # A byte source sets it (e.g. "utf-8"); the Session reads it to decode bytes -> screen
    # characters while keeping the stream tap byte-lossless. None => emit-as-text, no decode.
    encoding = None
    # Exit status after on_exit (None until then): the hosted program's return code for a
    # subprocess source, or None for sources without one (engine / cast).
    returncode = None
    # The exception that ended the program, if any (else None). Session.run_blocking()
    # re-raises it; observers get an ERROR event. Set by sources that run user code.
    error = None

    def start(self, on_output, on_wait, on_exit):
        raise NotImplementedError

    def send_input(self, text):
        raise NotImplementedError

    def stop(self):
        pass

    def _pump(self, read_one, on_output, on_exit, reap=None):
        """The standard reader loop for a subprocess/pty source, on a daemon thread: pull
        chunks from read_one() until it returns "" (EOF), forward each to on_output, then
        reap the child's exit status (if `reap` is given) and fire on_exit. read_one() owns
        its own EOF/error handling and returns "" to stop. Sets self.thread; the caller must
        have set self._running = True. Used by the pty/pipe/ConPTY sources."""

        def reader():
            try:
                while self._running:
                    chunk = read_one()
                    if not chunk:
                        break
                    on_output(chunk)
            finally:
                if reap is not None:
                    with contextlib.suppress(Exception):  # reap the child's exit status
                        self.returncode = reap()
                self._running = False
                on_exit()

        self.thread = threading.Thread(target=reader, daemon=True)
        self.thread.start()


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
            line = self._inq.get()
            if line is _STOP:  # stop() asked us to unwind
                raise _StopRunner
            return line

        def go():
            try:
                self.runner(on_output, readline)
            except _StopRunner:
                pass  # clean stop() -- not an error
            except BaseException as e:  # capture so run_blocking() can re-raise / observers see it
                self.error = e
            finally:
                on_exit()

        self.thread = threading.Thread(target=go, daemon=True)
        self.thread.start()

    def send_input(self, text):
        self._inq.put(text)

    def stop(self):
        # Unblock a runner waiting in readline() so Session.stop()/join() returns promptly.
        # A runner busy elsewhere (compute/sleep) can't be force-stopped; its thread is a
        # daemon and won't block process exit.
        self._inq.put(_STOP)


class PtySource(Source):
    """Hosts an arbitrary external program on a real pseudo-terminal. The child's raw
    output bytes are forwarded to on_output as a byte-transparent latin-1 str -- lossless,
    so a *stream* observer sees exactly the program's bytes; the Session decodes them to
    characters for the *screen* using `encoding` (default UTF-8). send_input encodes
    keystrokes with the same `encoding`. on_exit fires when the child ends; on_wait is NOT
    fired -- a pty gives no readline boundary, so an observer reads the stream/grid instead.
    This is what lets you observe+control any terminal program (e.g. real SIMH/TOPS-10);
    pair with the VT52 `Terminal` for period children or `PyteTerminal` (--ansi) for modern
    ANSI. See docs/DESIGN.md."""

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
        try:
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
        except BaseException:  # spawn failed (e.g. command not found) -> don't leak pty fds
            with contextlib.suppress(OSError):
                os.close(slave)
            with contextlib.suppress(OSError):
                os.close(self.master)
            self.master = None
            raise
        os.close(slave)
        self._running = True

        def read_one():
            try:
                data = os.read(self.master, 4096)
            except OSError:
                return ""  # master closed
            return data.decode("latin-1")  # raw bytes, lossless (Session decodes)

        self._pump(read_one, on_output, on_exit, reap=self._reap)

    def _reap(self):
        # Reap the child; escalate to SIGKILL if it ignores the SIGTERM from stop(), so a shell
        # that traps TERM (or sits in raw mode) can't be left running with returncode stuck None.
        try:
            return self.proc.wait(timeout=2)
        except Exception:
            with contextlib.suppress(Exception):
                self.proc.kill()
                return self.proc.wait(timeout=2)
            return None

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


class _ReplaySource(Source):
    """Shared machinery for sources that *replay* a recording: a daemon thread emits the
    recorded output events with their original timing (scaled by `speed`, idle gaps optionally
    capped by `idle_time_limit`; `loop=True` repeats until stop()), so a recording streams
    through the exact same Terminal/Session/renderer path a live program would -- which also
    makes a render reproducible (no live subprocess). Input is ignored (you can't type into the
    past) and on_wait never fires (a recording has no input boundary). Subclasses set
    `.width`/`.height` (so the caller can size the Terminal) and implement `_events()` ->
    iterable of `(abs_seconds_from_start, data)`. See docs/DESIGN.md."""

    def __init__(self, path, speed=1.0, idle_time_limit=None, loop=False):
        self.path = path
        self.speed = speed if speed and speed > 0 else 1.0
        self.idle_time_limit = idle_time_limit
        self.loop = loop
        self.thread = None
        self._running = False
        self._wake = threading.Event()  # set by stop() to interrupt an idle sleep
        self.width, self.height = 80, 24

    def _events(self):
        """Yield (abs_time, data) for each output event; abs_time = seconds from start."""
        raise NotImplementedError

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


class CastSource(_ReplaySource):
    """Replays a recorded asciinema .cast session through the normal pipeline.

    A *text* source (emits characters; no decode). The recorded width/height are exposed on
    `.width`/`.height` so the caller can size the Terminal first.

    Supported formats: asciicast v2 (newline-delimited JSON: a header object
    `{"version": 2, "width": .., "height": ..}` then `[time, code, data]` events, where code
    "o" is terminal output -- the only kind replayed; "i"/"m"/"r" are skipped -- and time is
    seconds from the start) and compact v1 (`{"version": 1, "width", "height", "stdout":
    [[delay, data], ...]}`). See docs/DESIGN.md."""

    def __init__(self, path, speed=1.0, idle_time_limit=None, loop=False):
        super().__init__(path, speed, idle_time_limit, loop)
        self.version = 2
        self._events_v1 = None  # set when the file is (compact/pretty) v1
        self._read_header()

    def _read_header(self):
        with open(self.path, encoding="utf-8") as f:
            first = f.readline(MAX_CAST_LINE)  # bounded: untrusted file
        try:
            head = json.loads(first)
        except ValueError:
            head = None
        if isinstance(head, dict) and head.get("version", 0) >= 2 and "stdout" not in head:
            self.version = int(head["version"])  # v2 (or later): stream lines
            self.width = _cast_dim(head.get("width"), 80)  # clamp untrusted dimensions
            self.height = _cast_dim(head.get("height"), 24)
            return
        # v1 is one JSON object loaded whole (unstreamable) -> cap the file size so an
        # untrusted v1 recording can't drive unbounded allocation.
        if os.path.getsize(self.path) > MAX_CAST_FILE:
            raise ValueError(
                f"v1 .cast file exceeds {MAX_CAST_FILE} bytes; refusing to load it whole "
                "(v1 is unstreamable -- re-record as asciicast v2 for large sessions)"
            )
        with open(self.path, encoding="utf-8") as f:
            doc = json.load(f)
        self.version = 1
        self.width = _cast_dim(doc.get("width"), 80)
        self.height = _cast_dim(doc.get("height"), 24)
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
            f.readline(MAX_CAST_LINE)
            while True:
                line = f.readline(MAX_CAST_LINE)  # bounded per-event read
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, list) and len(ev) >= 3 and ev[1] == "o":
                    yield float(ev[0]), ev[2]


class TtyrecSource(_ReplaySource):
    """Replays a `.ttyrec` recording (the ttyrec / termrec / NetHack / IPBT format).

    A *byte* source: the file is a flat sequence of records, each a header of three
    little-endian uint32 -- seconds, microseconds, payload length -- followed by that many raw
    output bytes. Those bytes are decoded to the screen per `encoding` (UTF-8 by default; pass
    `encoding="cp437"` for old DOS recordings). ttyrec carries no dimensions, so `.width` /
    `.height` stay the 80x24 default -- size the Terminal yourself if the recording needs it.
    See docs/DESIGN.md."""

    def __init__(self, path, speed=1.0, idle_time_limit=None, loop=False, encoding="utf-8"):
        super().__init__(path, speed, idle_time_limit, loop)
        self.encoding = encoding  # ttyrec payloads are raw bytes -> decode for the screen

    def _events(self):
        with open(self.path, "rb") as f:
            base = None
            while True:
                header = f.read(_TTYREC_HEADER.size)
                if len(header) < _TTYREC_HEADER.size:
                    break  # clean EOF (or a truncated trailing header)
                sec, usec, length = _TTYREC_HEADER.unpack(header)
                if length > MAX_TTYREC_CHUNK:
                    raise ValueError(f"ttyrec record claims {length} bytes (> cap); refusing")
                payload = f.read(length)
                if len(payload) < length:
                    break  # truncated tail
                t = sec + usec / 1_000_000
                if base is None:
                    base = t
                yield t - base, payload.decode("latin-1")  # byte-transparent; Session decodes


class AnsSource(_ReplaySource):
    """Plays an ANSI / BBS art file (`.ans`): CP437 bytes interleaved with ANSI escapes, with
    an optional SAUCE metadata record (and comment block) at the end.

    A *text* source. It strips the SAUCE record / comment block / DOS EOF marker (`0x1A`),
    decodes CP437 -- so the high-byte glyphs (box-drawing, shaded blocks) become Unicode while
    the escapes pass through untouched -- and emits the art, which renders through the
    full-ANSI backend (use `--ansi`). With `baud` set (characters/second) it draws progressively
    for the retro modem-speed effect; by default the whole screen appears at once. SAUCE's
    recorded width/height land on `.width` / `.height` (default 80x24). See docs/DESIGN.md."""

    def __init__(self, path, speed=1.0, idle_time_limit=None, loop=False, baud=None,
                 charset="cp437"):
        super().__init__(path, speed, idle_time_limit, loop)
        self.baud = baud
        self._charset = charset
        self._content = self._load()

    def _load(self):
        with open(self.path, "rb") as f:
            data = f.read()
        # SAUCE: a 128-byte record at EOF beginning b"SAUCE00", optionally preceded by a COMNT
        # block of N 64-byte comment lines. Strip it (and read the canvas width/height).
        if len(data) >= 128 and data[-128:-121] == b"SAUCE00":
            sauce = data[-128:]
            width = int.from_bytes(sauce[96:98], "little")  # TInfo1: characters per row
            height = int.from_bytes(sauce[98:100], "little")  # TInfo2: number of rows
            if width:
                self.width = _cast_dim(width, self.width)
            if height:
                self.height = _cast_dim(height, self.height)
            comments = sauce[104]  # number of 64-byte comment lines in a COMNT block
            trailer = 128 + (5 + comments * 64 if comments else 0)
            data = data[:-trailer]
        eof = data.find(b"\x1a")  # DOS EOF marker: the art ends here
        if eof != -1:
            data = data[:eof]
        return data.decode(self._charset, errors="replace")

    def _events(self):
        if self.baud and self.baud > 0:  # draw progressively, char by char
            for i, ch in enumerate(self._content):
                yield i / self.baud, ch
        else:  # the whole screen at once
            yield 0.0, self._content


_3A_NAMES = {"black": 0, "red": 1, "green": 2, "yellow": 3,
             "blue": 4, "magenta": 5, "cyan": 6, "white": 7}


def _3a_spec_sgr(spec, fg):
    """A .3a color spec (ANSI name like `green`/`bright-red`, an 8-bit decimal, or a 6-hex RGB)
    -> the SGR parameters for a foreground (`fg=True`) or background. None if unrecognized."""
    base = 30 if fg else 40
    if spec.startswith("bright-"):
        n = _3A_NAMES.get(spec[7:])
        return str(base + 60 + n) if n is not None else None
    if spec in _3A_NAMES:
        return str(base + _3A_NAMES[spec])
    if spec.isdigit():
        return f"{38 if fg else 48};5;{int(spec)}"
    if len(spec) == 6:
        try:
            r, g, b = (int(spec[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return None
        return f"{38 if fg else 48};2;{r};{g};{b}"
    return None


def _3a_builtin_colmap():
    """The 17 predefined .3a color names -> SGR parameter string ('' = default)."""
    m = {"_": ""}
    for i in range(8):
        m[str(i)] = str(30 + i)  # 0-7 -> 30-37
    for i, name in enumerate("89abcdef"):
        m[name] = str(90 + i)  # 8-f -> 90-97 (bright)
    return m


class ThreeASource(_ReplaySource):
    """Plays a `.3a` animated-ASCII-art file (the DomesticMoth/asciimoth format).

    A `.3a` file is UTF-8 text: an `@3a` header block of `key value` lines (`delay <ms>`,
    `loop yes|no`, `colors yes|no`, custom `col <name> fg:.. bg:..`; `;;` comments) and an
    `@body` block of frames separated by blank lines. With `colors yes`, each frame is rows of
    text interleaved with equal-length rows of color-name characters (`0`-`7`/`8`-`f`/`_` =
    ANSI 30-37/90-97/default, plus any `col`-defined names). A *text* source: it renders each
    frame as positioned, SGR-colored output and steps at the `delay`. `--loop` (or `loop yes`)
    repeats it. Channel "pinning" isn't supported. See docs/DESIGN.md."""

    def __init__(self, path, speed=1.0, idle_time_limit=None, loop=False):
        super().__init__(path, speed, idle_time_limit, loop)
        self.delay_ms = 100
        self.frame_delays = {}
        self.colors_on = False
        self.colmap = _3a_builtin_colmap()
        self.frames = []  # list of (text_rows, color_rows|None)
        self._parse(loop)

    def _parse(self, loop_arg):
        lines = open(self.path, encoding="utf-8", errors="replace").read().split("\n")
        body_at = next((i for i, ln in enumerate(lines) if ln.strip() == "@body"), len(lines))
        header = lines[1:body_at] if lines and lines[0].strip() == "@3a" else lines[:body_at]
        loop_hdr = False
        for ln in header:
            s = ln.strip()
            if not s or s.startswith(";;"):
                continue
            key, _, val = s.partition(" ")
            val = val.strip()
            if key == "delay":
                parts = val.split()
                if parts and parts[0].isdigit():
                    self.delay_ms = int(parts[0])
                for p in parts[1:]:  # frame:ms overrides
                    fr, _, ms = p.partition(":")
                    if fr.isdigit() and ms.isdigit():
                        self.frame_delays[int(fr)] = int(ms)
            elif key == "loop":
                loop_hdr = val.lower() in ("yes", "true", "1")
            elif key == "colors":
                self.colors_on = val.lower() in ("yes", "true", "1")
            elif key == "col":
                bits = val.split()
                if bits:
                    sgr = []
                    for b in bits[1:]:
                        which, _, spec = b.partition(":")
                        s = _3a_spec_sgr(spec, which == "fg")
                        if s:
                            sgr.append(s)
                    self.colmap[bits[0]] = ";".join(sgr)
        self.loop = bool(self.loop) or loop_hdr or bool(loop_arg)

        frame, w, h = [], 80, 24
        for ln in lines[body_at + 1:] + [""]:  # trailing "" flushes the last frame
            # only a truly empty line separates frames -- a row of spaces is screen content
            if ln.rstrip("\r") == "" or ln.startswith("@"):
                if frame:
                    rows = [r.rstrip("\r") for r in frame]
                    if self.colors_on:
                        text, color = rows[0::2], rows[1::2]
                    else:
                        text, color = rows, None
                    self.frames.append((text, color))
                    w = max(w, max((len(r) for r in text), default=0))
                    h = max(h, len(text))
                    frame = []
            else:
                frame.append(ln)
        self.width, self.height = _cast_dim(w, 80), _cast_dim(h, 24)

    def _render(self, text_rows, color_rows):
        # Position each row absolutely (CUP) and clear to end of line -- never emit newlines, so
        # a full-height frame can't scroll content off the top.
        out = []
        for i, row in enumerate(text_rows):
            out.append(f"\x1b[{i + 1};1H")
            crow = color_rows[i] if color_rows else ""
            cur = None
            for j, ch in enumerate(row):
                sgr = self.colmap.get(crow[j] if j < len(crow) else "_", "")
                if sgr != cur:
                    out.append(("\x1b[0;" + sgr + "m") if sgr else "\x1b[0m")
                    cur = sgr
                out.append(ch)
            out.append("\x1b[0m\x1b[K")
        out.append(f"\x1b[{len(text_rows) + 1};1H\x1b[J")  # clear rows a taller frame left behind
        return "".join(out)

    def _events(self):
        t = 0.0
        for i, (text_rows, color_rows) in enumerate(self.frames):
            yield t, self._render(text_rows, color_rows)
            t += self.frame_delays.get(i, self.delay_ms) / 1000.0


def replay_source(path, speed=1.0, idle_time_limit=None, loop=False):
    """Pick the replay Source for a recording/art file by extension: `.ttyrec` -> `TtyrecSource`,
    `.ans` -> `AnsSource`, `.3a` -> `ThreeASource`, else (`.cast`, ...) -> `CastSource`."""
    ext = os.path.splitext(path)[1].lower()
    cls = {".ttyrec": TtyrecSource, ".ans": AnsSource, ".3a": ThreeASource}.get(ext, CastSource)
    return cls(path, speed=speed, idle_time_limit=idle_time_limit, loop=loop)


class PipeSource(Source):
    """Hosts an external program over plain pipes -- no pseudo-terminal. Cross-platform
    (POSIX and Windows) and zero extra deps: subprocess.Popen, a reader thread forwarding
    stdout (+stderr) to on_output, and send_input -> stdin. This is the "non-pty Source"
    (`--no-pty`) -- use it where a pty isn't available or isn't wanted. Caveat: with
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

        def read_one():
            data = self.proc.stdout.read(4096)  # raw (bufsize=0): returns what's ready, b"" at EOF
            return data.decode("latin-1")  # raw bytes, lossless (Session decodes)

        self._pump(read_one, on_output, on_exit, reap=lambda: self.proc.wait(timeout=2))

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
    extra (pywinpty) and Windows 10 / Server 2019+. See docs/DESIGN.md.

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

        def read_one():
            if not self.proc.isalive():
                return ""
            try:
                return self.proc.read(4096)  # pywinpty returns str (already decoded)
            except EOFError:
                return ""

        self._pump(read_one, on_output, on_exit, reap=self.proc.wait)

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
