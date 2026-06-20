"""Record a live Session to a terminal-session recording file.

A `Recorder` is an observe-tap: attach it to a Session and, as the hosted program runs, it
writes the program's output stream -- with timing -- to an asciinema `.cast` (v2) or a
`.ttyrec` file. Those are the same formats `CastSource` / `TtyrecSource` replay, so anything
you record here plays back through tappty (and `.cast` plugs into the asciinema ecosystem).

Use it as a context manager around a run, or call `start()` / `close()` yourself:

    rec = Recorder(session, "session.cast")
    rec.start()
    ...                       # run the session (a renderer, the bus, headless, ...)
    rec.close()

The format is taken from the path extension (`.ttyrec` -> ttyrec, anything else -> cast)
unless you pass `fmt="cast"` / `fmt="ttyrec"`. See docs/DESIGN.md.
"""

from __future__ import annotations

import codecs
import json
import os
import struct
import threading
import time

_TTYREC_HEADER = struct.Struct("<III")  # sec, usec, length (little-endian uint32)


class Recorder:
    def __init__(self, session, path, fmt=None):
        self.session = session
        self.path = path
        self.fmt = fmt or ("ttyrec" if os.path.splitext(path)[1].lower() == ".ttyrec" else "cast")
        if self.fmt not in ("cast", "ttyrec"):
            raise ValueError(f"unknown recording format {self.fmt!r} (use 'cast' or 'ttyrec')")
        self._file = None
        self._t0 = None
        self._decoder = None  # cast: incremental UTF-8 decode (handles multibyte split chunks)
        self._lock = threading.Lock()  # on_stream runs on the source thread; close() on another

    def start(self):
        self._t0 = time.monotonic()
        if self.fmt == "ttyrec":
            self._file = open(self.path, "wb")
        else:
            self._file = open(self.path, "w", encoding="utf-8")
            self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            header = {
                "version": 2,
                "width": self.session.term.cols,
                "height": self.session.term.rows,
                "timestamp": int(time.time()),
            }
            self._file.write(json.dumps(header) + "\n")
        self.session.on_stream(self._on_stream)
        return self

    def _on_stream(self, raw):
        # `raw` is the program's output as the source produced it: a byte-transparent latin-1
        # str for a byte source (so re-encode latin-1 to recover the exact bytes), or real text
        # for a text source (engine/cast) -- encode UTF-8 to get bytes either way.
        data = (
            raw.encode("latin-1")
            if getattr(self.session.source, "encoding", None)
            else raw.encode("utf-8")
        )
        t = time.monotonic() - self._t0
        with self._lock:
            if self._file is None:
                return
            if self.fmt == "ttyrec":
                sec = int(t)
                self._file.write(_TTYREC_HEADER.pack(sec, int((t - sec) * 1_000_000), len(data)))
                self._file.write(data)
            else:
                text = self._decoder.decode(data)
                if text:
                    self._file.write(json.dumps([round(t, 6), "o", text]) + "\n")

    def close(self):
        self.session.off_stream(self._on_stream)
        with self._lock:
            if self._file is None:
                return
            if self._decoder is not None:  # flush any bytes held back mid-multibyte
                tail = self._decoder.decode(b"", final=True)
                if tail:
                    self._file.write(
                        json.dumps([round(time.monotonic() - self._t0, 6), "o", tail]) + "\n"
                    )
            self._file.close()
            self._file = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()


_ANSI_IDX = {
    "black": 0,
    "red": 1,
    "green": 2,
    "brown": 3,
    "blue": 4,
    "magenta": 5,
    "cyan": 6,
    "white": 7,
}


def _sgr_color(name, base):
    """SGR parameter for a pyte color name at `base` (30 fg / 40 bg), or None to leave the
    default. Bright names use the 90-97 / 100-107 range; a 256-color/truecolor hex (no ANSI-16
    name) is dropped to default -- ANSI art is a 16-color medium."""
    if not name or name == "default":
        return None
    if name.startswith("bright"):
        idx = _ANSI_IDX.get(name[6:])
        return base + 60 + idx if idx is not None else None
    idx = _ANSI_IDX.get(name)
    return base + idx if idx is not None else None


def _ansi_codes(cell):
    codes = []
    for flag, code in (
        (cell.bold, 1),
        (cell.italic, 3),
        (cell.underline, 4),
        (cell.blink, 5),
        (cell.reverse, 7),
        (cell.strike, 9),
    ):
        if flag:
            codes.append(code)
    for name, base in ((cell.fg, 30), (cell.bg, 40)):
        param = _sgr_color(name, base)
        if param is not None:
            codes.append(param)
    return codes


def export_ansi(session, path):
    """Export the session's current screen as an ANSI-art `.ans` file: each cell's color and
    attributes as an SGR escape, each glyph encoded back to CP437 (non-CP437 glyphs -> '?').
    A *screen snapshot* (no timing), readable by `AnsSource` and ANSI-art tools (DESIGN.md)."""
    out = bytearray()
    prev = None
    for r, row in enumerate(session.term.cells()):
        if r:
            out += b"\r\n"
        for cell in row:
            codes = _ansi_codes(cell)
            if codes != prev:  # re-emit SGR only when the style changes (reset + new attrs)
                out += b"\x1b[" + b";".join(str(c).encode() for c in [0, *codes]) + b"m"
                prev = codes
            out += cell.char.encode("cp437", errors="replace")
    out += b"\x1b[0m\x1a"  # reset + DOS EOF marker
    with open(path, "wb") as f:
        f.write(bytes(out))


_PYTE_3A = {
    "black": 0,
    "red": 1,
    "green": 2,
    "brown": 3,
    "blue": 4,
    "magenta": 5,
    "cyan": 6,
    "white": 7,
}
_3A_HEX = "0123456789abcdef"


def _3a_name(cell):
    """A cell's foreground -> a .3a color-name char (`0`-`7`/`8`-`f`/`_`). Background and
    256/truecolor are not representable by the 16 built-in names, so they fall back to default."""
    fg = cell.fg
    if not fg or fg == "default":
        return "_"
    base = _PYTE_3A.get(fg[6:] if fg.startswith("bright") else fg)
    if base is None:
        return "_"
    return _3A_HEX[base + 8] if fg.startswith("bright") else _3A_HEX[base]


def export_3a(session, path):
    """Export the session's current screen as a single-frame `.3a` animated-ASCII-art file:
    a text row + an equal-length color-name row per screen row, under a minimal `@3a`/`@body`
    header. Readable by `ThreeASource`. (One frame -- recording an animation is future work.)
    Foreground color only; see `_3a_name`."""
    body = []
    for row in session.term.cells():
        body.append("".join(cell.char or " " for cell in row))
        body.append("".join(_3a_name(cell) for cell in row))
    content = "@3a\ncolors yes\n\n@body\n" + "\n".join(body) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
