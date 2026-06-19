"""The instrumentation bus over a Unix-domain socket *or* TCP: lets an out-of-process
client (an AI, a logger, a remote renderer) attach to a Session to observe its screen
and inject input -- the externalized form of the in-process taps. One server = one
Session; N clients. Newline-delimited messages, payloads JSON (debuggable with
socat, trivial for an AI). The address is a filesystem path (Unix-domain socket, POSIX)
or a (host, port) tuple (TCP -- works anywhere, including Windows where AF_UNIX is
absent; see docs/WINDOWS.md). See [[sbterm-instrumentation]].

Protocol
  client -> server
    HELLO <json>     identify {role, name}            -> OK
    SNAP             request the current grid          -> FRAME <json>
    INFO             session info                      -> INFO <json>
    SUB              subscribe to pushed OUT/FRAME/EVENT-> OK
    LINE <text>      inject a line (rest-of-line literal)
    KEY  <json-str>  inject raw keystrokes (json-encoded so ctrl chars survive)
  server -> client
    OK / FRAME <json> / INFO <json>
    OUT <json-str>   pushed raw output chunk      (tap 1, if subscribed)
    FRAME <json>     pushed on grid change         (tap 2, if subscribed)
    EVENT <json>     {name: WAIT|BELL|CLOSED, ...} (tap 3, if subscribed)
"""

import contextlib
import json
import os
import queue
import socket
import threading
from dataclasses import dataclass, field

_AF_UNIX = getattr(socket, "AF_UNIX", None)  # absent on Windows


def _resolve(addr):
    """(family, address) for a bus endpoint. A (host, port) tuple -> TCP (works anywhere,
    incl. Windows); anything else is a filesystem path -> Unix-domain socket (POSIX)."""
    if isinstance(addr, (tuple, list)):
        return socket.AF_INET, (addr[0], int(addr[1]))
    return _AF_UNIX, addr


@dataclass
class _Conn:
    """Per-connection state held by the server."""

    name: str  # talking-stick identity (unique per connection)
    lock: threading.Lock = field(default_factory=threading.Lock)  # serializes sends
    sub: bool = False  # subscribed to pushed OUT/FRAME/EVENT?
    role: str = "observer"  # observer | human | ai | ...
    claimed: bool = False  # did THIS conn claim the stick? (only then may disconnect drop it)


@dataclass
class _Capture:
    """An in-flight CMD capture: output collected until the next WAIT."""

    buf: list = field(default_factory=list)  # output chunks since the command was sent
    ev: threading.Event = field(default_factory=threading.Event)  # set on the next WAIT


class BusServer:
    def __init__(self, session, path):
        self.session = session
        self.path = path  # filesystem path (Unix) or (host, port) (TCP)
        self._conns = {}  # conn -> _Conn
        self._lock = threading.RLock()
        self._sock = None
        self._family = None
        self.addr = None  # resolved bind address after start()
        self._running = False
        self._captures = []  # active CMD captures (_Capture)

    def start(self):
        self._family, addr = _resolve(self.path)
        if self._family == _AF_UNIX:  # Unix socket: ensure dir, clear a stale node
            d = os.path.dirname(addr)
            if d:
                os.makedirs(d, exist_ok=True)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(addr)
        self._sock = socket.socket(self._family, socket.SOCK_STREAM)
        if self._family != _AF_UNIX:  # TCP: reuse the port promptly across restarts
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(addr)
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
            for cap in self._captures:
                cap.buf.append(text)
        self._push("OUT", text)

    def _on_event(self, name, info):  # tap 3: WAIT closes CMD captures
        if name == "WAIT":
            with self._lock:
                for cap in self._captures:
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
                self._conns[conn] = _Conn(name=f"c{id(conn) & 0xFFFFFF}")
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        try:
            f = conn.makefile("r")
            for line in f:
                line = line.rstrip("\n")
                if line:
                    verb, _, payload = line.partition(" ")
                    self._handle(conn, verb.upper(), payload)
        except OSError:
            pass
        finally:
            self._drop(conn)

    def _handle(self, conn, verb, payload):
        st = self._conns.get(conn)
        if st is None:
            return
        if verb == "HELLO":
            info = {}
            with contextlib.suppress(ValueError):
                info = json.loads(payload) if payload else {}
            name = info.get("name", st.name)
            st.role = info.get("role", "observer")
            if st.role != "observer":  # a controller registers for the stick
                if self.session.has_controller(name):  # keep stick identities unique per
                    name = f"{name}#{st.name}"  # conn (st.name is this conn's c-id)
                self.session.claim_control(name, st.role)
                st.claimed = True  # only THEN may disconnect drop it
            st.name = name
            self._send(conn, "OK", {"name": st.name, "driver": self.session.driver})
        elif verb == "SNAP":
            self._send(conn, "FRAME", self.session.snapshot())
        elif verb == "INFO":
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
        elif verb == "CMD":  # synchronous: send a line, return its
            if not self.session.has_control(st.name):  # output up to the next WAIT
                self._send(conn, "DENIED", {"driver": self.session.driver})
            else:
                cap = _Capture()
                with self._lock:
                    self._captures.append(cap)
                try:
                    self.session.echo(payload)
                    self.session.send_input(payload + "\n", by=st.name)
                    cap.ev.wait(timeout=8)
                finally:
                    with self._lock:
                        if cap in self._captures:
                            self._captures.remove(cap)
                self._send(conn, "RESP", {"text": "".join(cap.buf)})
        elif verb == "SUB":
            st.sub = True
            self._send(conn, "OK", {})
        elif verb == "TAKE":
            ok = self.session.take(st.name)
            self._send(conn, "OK" if ok else "DENIED", {"driver": self.session.driver})
        elif verb == "RELEASE":
            self.session.release(st.name)
            self._send(conn, "OK", {"driver": self.session.driver})
        elif verb == "LINE":
            if self.session.has_control(st.name):
                self.session.echo(payload)  # show the command so a watcher sees it
                self.session.send_input(payload + "\n", by=st.name)
            else:
                self._send(conn, "DENIED", {"driver": self.session.driver})
        elif verb == "KEY":
            if self.session.has_control(st.name):
                with contextlib.suppress(ValueError):
                    for c in json.loads(payload) if payload else "":
                        self.session.feed_key(c, by=st.name, auto_take=False)
            else:
                self._send(conn, "DENIED", {"driver": self.session.driver})

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
        with contextlib.suppress(OSError):
            self._sock.close()
        if self._family == _AF_UNIX and isinstance(self.path, str):
            with contextlib.suppress(OSError):
                os.unlink(self.path)


class BusClient:
    """Minimal client: a background reader puts every (verb, payload) message on
    `inbox`; `snap()`/`info()` are synchronous request/replies; `line()`/`key()`
    inject input. An AI controller typically subscribes and drains `inbox`."""

    def __init__(self, path):
        self.path = path
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
            for line in self._f:
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
        self.sock.sendall((verb + (" " + payload if payload else "") + "\n").encode())

    def hello(self, role="observer", name="client"):
        self.send("HELLO", json.dumps({"role": role, "name": name}))

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
        """Send a command and get back exactly its output (up to the program's next
        input prompt) -- the synchronous primitive for driving/testing over the bus."""
        self.send("CMD", line)
        r = self.wait_for("RESP", timeout)
        return r.get("text") if isinstance(r, dict) else None

    def close(self):
        with contextlib.suppress(OSError):
            self.sock.close()
