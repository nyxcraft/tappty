"""The instrumentation bus over a Unix-domain socket *or* TCP: lets an out-of-process
client (an AI, a logger, a remote renderer) attach to a Session to observe its screen
and inject input -- the externalized form of the in-process taps. One server = one
Session; N clients. Newline-delimited messages, payloads JSON (debuggable with
socat, trivial for an AI). The address is a filesystem path (Unix-domain socket, POSIX)
or a (host, port) tuple (TCP -- works anywhere, including Windows where AF_UNIX is absent).

Protocol
  client -> server
    HELLO <json>     identify {role, name, token?}     -> OK | DENIED
    SNAP             request the current grid           -> FRAME <json>
    INFO             session info                       -> INFO <json>
    SUB              subscribe to pushed OUT/FRAME/EVENT -> OK
    LINE <text>      inject a line (rest-of-line literal; needs the stick)
    CMD  <text>      send a line, get its output to the next prompt -> RESP <json>
    KEY  <json-str>  inject raw keystrokes (json-encoded string so ctrl chars survive)
    TAKE / RELEASE   grab / drop the talking stick      -> OK | DENIED
  server -> client
    OK / FRAME <json> / INFO <json> / DENIED <json>
    RESP <json>      {text, timeout, truncated, cancelled} -- reply to CMD
    OUT <json-str>   pushed raw output chunk      (tap 1, if subscribed)
    FRAME <json>     pushed on grid change         (tap 2, if subscribed)
    EVENT <json>     {name: WAIT|BELL|CLOSED|DRIVER|ERROR, ...} (tap 3, if subscribed)

Security: the bus is a terminal control plane and TRUSTED-LOCAL by default -- a connected
client gets terminal read/write as the tappty user. Unix socket is owner-only (0600 file),
TCP is loopback-only unless allow_remote=True, an optional non-empty `token` gates HELLO,
and frames/captures are bounded. It is not transport security (no TLS). The full model and
rationale are canonical in docs/DESIGN.md §8.
"""

import contextlib
import hmac
import json
import os
import queue
import socket
import stat
import threading
from dataclasses import dataclass, field

_AF_UNIX = getattr(socket, "AF_UNIX", None)  # absent on Windows
MAX_FRAME = 65536  # max bytes per protocol line (oversized -> drop the connection)
MAX_CAPTURE = 1 << 20  # max bytes a single CMD capture will buffer (1 MiB)


def _is_loopback(host):
    return host in ("127.0.0.1", "::1", "localhost")


def _resolve(addr):
    """(family, address) for a bus endpoint. A (host, port) tuple -> TCP (works anywhere,
    incl. Windows); anything else is a filesystem path -> Unix-domain socket (POSIX)."""
    if isinstance(addr, (tuple, list)):
        return socket.AF_INET, (addr[0], int(addr[1]))
    if _AF_UNIX is None:  # e.g. Windows -- fail clearly instead of at socket() creation
        raise ValueError(
            "Unix-domain socket paths are unavailable on this platform (no AF_UNIX); "
            "use a (host, port) tuple for TCP instead"
        )
    return _AF_UNIX, addr


@dataclass
class _Conn:
    """Per-connection state held by the server."""

    name: str  # talking-stick identity (unique per connection)
    lock: threading.Lock = field(default_factory=threading.Lock)  # serializes sends
    sub: bool = False  # subscribed to pushed OUT/FRAME/EVENT?
    role: str = "observer"  # observer | human | ai | ...
    claimed: bool = False  # did THIS conn claim the stick? (only then may disconnect drop it)
    authed: bool = False  # passed the token check? (always True when no token is required)


@dataclass
class _Capture:
    """An in-flight CMD capture: output collected until the next WAIT."""

    buf: list = field(default_factory=list)  # output chunks since the command was sent
    ev: threading.Event = field(default_factory=threading.Event)  # set on WAIT/CLOSED or stop()
    size: int = 0  # bytes buffered so far (capped at MAX_CAPTURE)
    truncated: bool = False  # hit the cap and dropped output?
    completed: bool = False  # reached a real prompt (WAIT/CLOSED) -> output is a clean result
    cancelled: bool = False  # woken by stop() before completing -> output is not a clean result


class BusServer:
    def __init__(self, session, path, cmd_timeout=8.0, token=None, allow_remote=False):
        if token is not None and (not isinstance(token, str) or token == ""):
            # an empty token would authenticate clients that send no token at all
            raise ValueError("token must be a non-empty string (or None for no auth)")
        self.session = session
        self.path = path  # filesystem path (Unix) or (host, port) (TCP)
        self.cmd_timeout = cmd_timeout  # seconds a CMD waits for the next prompt (WAIT)
        self.token = token  # optional shared secret required in HELLO (None = no auth)
        self.allow_remote = allow_remote  # permit binding a non-loopback TCP host
        self._conns = {}  # conn -> _Conn
        self._lock = threading.RLock()
        self._sock = None
        self._family = None
        self.addr = None  # resolved bind address after start()
        self._running = False
        self._captures = []  # active CMD captures (_Capture)
        # verb -> handler(conn, st, payload). HELLO is handled before the auth gate (below),
        # so it is deliberately not in the table; unknown verbs are ignored.
        self._handlers = {
            "SNAP": self._h_snap,
            "INFO": self._h_info,
            "CMD": self._h_cmd,
            "SUB": self._h_sub,
            "TAKE": self._h_take,
            "RELEASE": self._h_release,
            "LINE": self._h_line,
            "KEY": self._h_key,
        }

    def start(self):
        # Restartable: start() registers Session taps and binds; stop() detaches the taps,
        # drops clients, and closes the socket -- so start()/stop() cycles are clean. A
        # second start() while already running is a no-op (avoids double-registering taps).
        if self._running:
            return self
        self._family, addr = _resolve(self.path)
        if self._family == _AF_UNIX:
            d = os.path.dirname(addr)
            if d and not os.path.isdir(d):  # create a private parent dir (don't touch others')
                os.makedirs(d, exist_ok=True)
                with contextlib.suppress(OSError):
                    os.chmod(d, 0o700)
            if os.path.lexists(addr):  # only unlink a stale SOCKET, never a real file
                if not stat.S_ISSOCK(os.lstat(addr).st_mode):
                    raise FileExistsError(
                        f"{addr!r} exists and is not a socket; refusing to unlink"
                    )
                os.unlink(addr)
        elif not self.allow_remote and not _is_loopback(addr[0]):
            raise ValueError(
                f"refusing to bind the bus to non-loopback host {addr[0]!r}: the bus is "
                "unauthenticated; pass allow_remote=True (and ideally token=) to expose it"
            )
        self._sock = socket.socket(self._family, socket.SOCK_STREAM)
        if self._family != _AF_UNIX:  # TCP: reuse the port promptly across restarts
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(addr)
        if self._family == _AF_UNIX:  # owner-only connect (filesystem auth)
            with contextlib.suppress(OSError):
                os.chmod(addr, 0o600)
        self._sock.listen(8)
        self.addr = self._sock.getsockname()  # TCP with port 0 -> the actual bound port
        self._running = True
        self.session.on_stream(self._on_stream)
        self.session.on_frame(self._push_frame)
        self.session.on_event(self._on_event)
        threading.Thread(target=self._accept, daemon=True).start()
        return self

    def _on_stream(self, text):  # tap 1: feed CMD captures + push OUT
        with self._lock:
            for cap in self._captures:  # hard-cap the buffer so a chatty program can't OOM us
                room = MAX_CAPTURE - cap.size
                if len(text) <= room:
                    cap.buf.append(text)
                    cap.size += len(text)
                else:
                    if room > 0:  # keep what fits, drop the rest
                        cap.buf.append(text[:room])
                        cap.size = MAX_CAPTURE
                    cap.truncated = True
        self._push("OUT", text)

    def _on_event(self, name, info):  # tap 3: WAIT/CLOSED close CMD captures
        if name in ("WAIT", "CLOSED"):  # next prompt OR the program ended -> the command is done
            with self._lock:
                for cap in self._captures:
                    cap.completed = True  # reached a real prompt (vs cancelled by stop())
                    cap.ev.set()
        self._push("EVENT", {"name": name, **info})

    # ---- connections ----
    def _accept(self):
        while self._running:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            with self._lock:
                # authed up-front when no token is required -> default behavior unchanged
                self._conns[conn] = _Conn(
                    name=f"c{id(conn) & 0xFFFFFF}", authed=self.token is None
                )
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        try:
            f = conn.makefile("r")
            while self._running:
                line = f.readline(MAX_FRAME + 1)  # bounded read: no unbounded-line DoS
                if not line:
                    break
                if len(line) > MAX_FRAME:  # oversized frame -> refuse + drop
                    break
                line = line.rstrip("\n")
                if line:
                    verb, _, payload = line.partition(" ")
                    self._handle(conn, verb.upper(), payload)
        except OSError:
            pass
        finally:
            self._drop(conn)

    def _handle(self, conn, verb, payload):
        # HELLO authenticates (and is allowed pre-auth); every other verb requires a conn
        # that has passed the token gate; then dispatch through the per-verb table.
        st = self._conns.get(conn)
        if st is None:
            return
        if verb == "HELLO":
            self._h_hello(conn, st, payload)
        elif not st.authed:  # a token is required and this conn hasn't presented it
            self._send(conn, "DENIED", {"error": "unauthenticated"})
        else:
            handler = self._handlers.get(verb)  # unknown verbs are ignored (forward-compatible)
            if handler is not None:
                handler(conn, st, payload)

    def _h_hello(self, conn, st, payload):
        if payload:
            try:
                info = json.loads(payload)
            except ValueError:  # invalid JSON (e.g. "HELLO {") -> deny, don't fall through
                self._send(conn, "DENIED", {"error": "malformed HELLO (invalid JSON)"})
                self._drop(conn)
                return
        else:
            info = {}  # bare HELLO -> anonymous observer
        if not isinstance(info, dict):  # valid JSON but not an object: 123/[]/"x"
            self._send(conn, "DENIED", {"error": "malformed HELLO (expected a JSON object)"})
            self._drop(conn)
            return
        if self.token is not None:
            tok = info.get("token")
            # require a string token (so JSON 123 can't match the token "123")
            if not (isinstance(tok, str) and hmac.compare_digest(tok, self.token)):
                self._send(conn, "DENIED", {"error": "authentication required"})
                self._drop(conn)
                return
        st.authed = True
        name = info.get("name")  # ignore a non-string name; keep this conn's unique default
        if isinstance(name, str):
            st_name = name
        else:
            st_name = st.name
        role = info.get("role", "observer")
        st.role = role if isinstance(role, str) else "observer"
        if st.role != "observer":  # a controller registers for the stick
            if self.session.has_controller(st_name):  # keep stick identities unique per conn
                st_name = f"{st_name}#{st.name}"  # (st.name is this conn's c-id)
            self.session.claim_control(st_name, st.role)
            st.claimed = True  # only THEN may disconnect drop it
        st.name = st_name
        self._send(conn, "OK", {"name": st.name, "driver": self.session.driver})

    def _h_snap(self, conn, st, payload):
        self._send(conn, "FRAME", self.session.snapshot())

    def _h_info(self, conn, st, payload):
        self._send(
            conn,
            "INFO",
            dict(
                self.session.snapshot(),
                done=self.session.done,
                driver=self.session.driver,
                waiting=self.session.waiting,
            ),
        )

    def _h_cmd(self, conn, st, payload):  # synchronous: send a line, return output to next WAIT
        if not self.session.has_control(st.name):
            self._send(conn, "DENIED", {"driver": self.session.driver})
            return
        cap = _Capture()
        with self._lock:
            self._captures.append(cap)
        try:
            self.session.echo(payload)
            self.session.send_input(payload + "\n", by=st.name)
            cap.ev.wait(timeout=self.cmd_timeout)  # woken by WAIT/CLOSED, stop(), or timeout
        finally:
            with self._lock:
                if cap in self._captures:
                    self._captures.remove(cap)
        # `completed` (a real prompt) is the only thing that makes a clean result; a capture
        # cancelled by stop() -- or one that just timed out -- is reported timeout=True so its
        # partial output isn't mistaken for a finished command. `truncated` flags cap drops.
        done = cap.completed and not cap.cancelled
        self._send(
            conn,
            "RESP",
            {
                "text": "".join(cap.buf),
                "timeout": not done,
                "truncated": cap.truncated,
                "cancelled": cap.cancelled,
            },
        )

    def _h_sub(self, conn, st, payload):
        st.sub = True
        self._send(conn, "OK", {})

    def _h_take(self, conn, st, payload):
        ok = self.session.take(st.name)
        self._send(conn, "OK" if ok else "DENIED", {"driver": self.session.driver})

    def _h_release(self, conn, st, payload):
        self.session.release(st.name)
        self._send(conn, "OK", {"driver": self.session.driver})

    def _h_line(self, conn, st, payload):
        if not self.session.has_control(st.name):
            self._send(conn, "DENIED", {"driver": self.session.driver})
            return
        self.session.echo(payload)  # show the command so a watcher sees it
        self.session.send_input(payload + "\n", by=st.name)

    def _h_key(self, conn, st, payload):
        if not self.session.has_control(st.name):
            self._send(conn, "DENIED", {"driver": self.session.driver})
            return
        try:
            keys = json.loads(payload) if payload else ""
        except ValueError:
            return
        if not isinstance(keys, str):  # KEY payload must be a JSON string of keystrokes
            return  # (a number/array/object is ignored, not iterated as stray "keys")
        for c in keys:
            self.session.feed_key(c, by=st.name, auto_take=False)

    # ---- outbound ----
    def _send(self, conn, verb, payload):
        st = self._conns.get(conn)
        if st is None:
            return
        data = (verb + " " + json.dumps(payload) + "\n").encode()
        with st.lock:
            try:
                conn.sendall(data)
            except OSError:
                self._drop(conn)

    def _push(self, verb, payload):
        for conn in list(self._conns):
            st = self._conns.get(conn)
            if st is not None and st.sub:
                self._send(conn, verb, payload)

    def _push_frame(self):
        snap = self.session.snapshot()
        for conn in list(self._conns):
            st = self._conns.get(conn)
            if st is not None and st.sub:
                self._send(conn, "FRAME", snap)

    def _drop(self, conn):
        with self._lock:
            st = self._conns.pop(conn, None)
        if st is not None and st.claimed:  # only a conn that claimed frees the stick --
            self.session.drop_controller(st.name)  # never drop a same-named observer's
        with contextlib.suppress(OSError):
            conn.close()

    def stop(self):
        self._running = False
        self.session.off_stream(self._on_stream)  # detach the taps start() registered, so a
        self.session.off_frame(self._push_frame)  # stopped server doesn't linger as a stale
        self.session.off_event(self._on_event)  # observer on a long-lived Session
        with self._lock:  # wake any CMD blocked on a capture so stop() is prompt
            for cap in self._captures:
                if not cap.completed:  # don't relabel one that already reached a prompt
                    cap.cancelled = True
                cap.ev.set()
        for conn in list(self._conns):  # close client sockets + release their claimed sticks
            self._drop(conn)
        if self._sock is not None:  # may be None if stop() is called before start()
            with contextlib.suppress(OSError):
                self._sock.close()
            self._sock = None  # clear so the stopped state is unambiguous
        if self._family == _AF_UNIX and isinstance(self.path, str):
            with contextlib.suppress(OSError):
                os.unlink(self.path)


class BusClient:
    """Minimal client: a background reader puts every (verb, payload) message on
    `inbox`; `snap()`/`info()` are synchronous request/replies; `line()`/`key()`
    inject input.

    Single-consumer: `wait_for()` drains `inbox` until a matching verb, discarding
    intervening messages -- best used for one request/reply at a time before subscribing,
    not for concurrent callers or overlapping requests. A subscriber MUST drain `inbox`
    (it is unbounded); an abandoned subscription accumulates pushed messages in memory."""

    def __init__(self, path, token=None):
        self.path = path
        self.token = token  # presented in HELLO when the server requires one
        self.inbox = queue.Queue()
        self.sock = None

    def connect(self):
        family, addr = _resolve(self.path)
        self.sock = socket.socket(family, socket.SOCK_STREAM)
        self.sock.connect(addr)
        self._f = self.sock.makefile("r")
        threading.Thread(target=self._read, daemon=True).start()
        return self

    def _read(self):
        try:
            while True:
                line = self._f.readline(MAX_FRAME + 1)  # bounded both ways (symmetry w/ server)
                if not line:
                    break
                if len(line) > MAX_FRAME:  # oversized frame from the server -> bail
                    break
                line = line.rstrip("\n")
                if not line:
                    continue
                verb, _, payload = line.partition(" ")
                try:
                    data = json.loads(payload) if payload else None
                except ValueError:
                    data = payload
                self.inbox.put((verb.upper(), data))
        except OSError:
            pass

    def send(self, verb, payload=""):
        if not isinstance(payload, str):  # low-level string-frame API
            raise TypeError("bus payload must be a str")
        if "\n" in payload or "\r" in payload:  # newlines would inject extra frames
            raise ValueError("bus payloads must not contain newlines")
        self.sock.sendall((verb + (" " + payload if payload else "") + "\n").encode())

    def hello(self, role="observer", name="client"):
        msg = {"role": role, "name": name}
        if self.token is not None:
            msg["token"] = self.token
        self.send("HELLO", json.dumps(msg))

    def sub(self):
        self.send("SUB")

    def take(self):
        self.send("TAKE")

    def release(self):
        self.send("RELEASE")

    def line(self, text):
        self.send("LINE", text)

    def key(self, text):
        self.send("KEY", json.dumps(text))

    def wait_for(self, verb, timeout=3.0):
        """Drain the inbox until a message of `verb` arrives (or timeout). Intervening
        messages are discarded -- best used for request/reply before subscribing."""
        import time

        end = time.monotonic() + timeout
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                return None
            try:
                v, d = self.inbox.get(timeout=remaining)
            except queue.Empty:
                return None
            if v == verb:
                return d

    def snap(self, timeout=3.0):
        self.send("SNAP")
        return self.wait_for("FRAME", timeout)

    def cmd(self, line, timeout=9.0):
        """Send a command and get back exactly its output (up to the program's next input
        prompt) -- the synchronous primitive for driving/testing over the bus. Raises
        TimeoutError if the command didn't reach the next prompt (so partial output isn't
        mistaken for a clean result)."""
        self.send("CMD", line)
        r = self.wait_for("RESP", timeout)
        if not isinstance(r, dict):
            return None
        if r.get("timeout"):
            raise TimeoutError("CMD did not reach the next prompt within the server timeout")
        return r.get("text")

    def close(self):
        with contextlib.suppress(OSError):
            self.sock.close()
