"""A full-ANSI terminal backend -- a drop-in for the VT52 `Terminal`.

`Terminal` (terminal.py) models a VT52-spirit glass with zero dependencies -- right for
the 1970s programs tappty was born hosting, wrong for anything that speaks modern
ANSI/VT100+ (colors, cursor addressing, line/char edits, scroll regions). `PyteTerminal`
wraps the `pyte` library (an in-process VTxxx emulator) behind the *same read interface* a
Session and the renderers use -- `cols`/`rows`/`cx`/`cy`/`write()`/`snapshot()`/
`rows_text()`/`view_rows()`/`max_scroll()` -- so it slots in wherever a `Terminal` goes
(`Session(PyteTerminal())`, `tapterm --ansi`) with nothing else changing.

This is the "b-full" backend the design always anticipated (DESIGN.md), and the
prerequisite for hosting a Windows ConPTY, which emits VT100+ rather than VT52
(see docs/WINDOWS.md).

`pyte` is an optional dependency (the `ansi` extra) imported lazily in __init__, so
`import tappty` works without it. pyte is LGPLv3 -- fine as a separately-installed,
optional backend. Thread-safe like `Terminal` (the program thread writes while a render
thread reads). Text handling matches the VT52 `Terminal`: the incoming str is fed as code
points and rendered as written. It is encoding-agnostic -- the Session decodes a byte
source's raw bytes to characters before calling write(), so this backend just renders the
text it's handed (Unicode included). Scrollback is kept too (via `HistoryScreen`), so
`view_rows(offset)`/`max_scroll()` behave like the VT52 model's paper roll.
"""

import threading


class PyteTerminal:
    def __init__(self, cols=80, rows=24, scrollback=5000):
        import pyte

        if cols < 1 or rows < 1:
            raise ValueError(f"cols and rows must be >= 1 (got {cols}x{rows})")
        self.cols, self.rows = cols, rows
        self.lock = threading.RLock()
        self.dirty = True
        # HistoryScreen accumulates scrolled-off lines in `.history.top` automatically as
        # the program scrolls -- the scrollback "paper roll", read non-mutatingly below.
        self._screen = pyte.HistoryScreen(cols, rows, history=scrollback)
        self._stream = pyte.Stream(self._screen)  # parses full ANSI on a code-point str

    # cursor position mirrors the VT52 Terminal's plain cx/cy attributes (read-only here)
    @property
    def cx(self):
        return self._screen.cursor.x

    @property
    def cy(self):
        return self._screen.cursor.y

    # ---- output (called by the hosted program, via the Session) ----
    def write(self, text):
        # The incoming str is treated as code points -- exactly how the VT52 `Terminal`
        # treats it -- so text renders as written (e.g. "café"). The Session has already
        # decoded a byte source's bytes to characters, so this just renders text.
        with self.lock:
            self._stream.feed(text)
            self.dirty = True

    def clear(self):
        with self.lock:
            self._screen.reset()

    # ---- view (called by a renderer) ----
    def snapshot(self):
        """The whole screen as text -- exact content, no deps. How an observer reads it."""
        with self.lock:
            return "\n".join(self._screen.display)

    def rows_text(self):
        with self.lock:
            return list(self._screen.display)

    def _line_text(self, line):
        """Stringify a history line (a column->Char mapping) to a full-width row."""
        return "".join(line[x].data for x in range(self.cols))

    def max_scroll(self):
        return len(self._screen.history.top)  # scrolled-off lines available

    def view_rows(self, offset=0):
        """`rows` lines scrolled back `offset` into the history (0 = the live screen),
        without disturbing the live grid -- same contract as Terminal.view_rows."""
        with self.lock:
            display = list(self._screen.display)
            if offset <= 0:
                return display
            top = [self._line_text(ln) for ln in self._screen.history.top]
            offset = min(offset, len(top))
            combined = top + display
            end = len(combined) - offset
            return combined[end - self.rows : end]
