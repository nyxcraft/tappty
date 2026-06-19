"""A fixed-size character terminal (the UI-agnostic core).

Models an 80x24 glass terminal in the VT52 spirit: printable text advances the
cursor with wrap + scroll, the usual control chars work (CR/LF/BS/FF/TAB), and a
handful of VT52 escape sequences (home/erase/direct cursor) are honored for
programs that use them. No rendering or GUI dependency lives here; a renderer just
reads .grid (or .snapshot()) and feeds keystrokes. Thread-safe: the program thread
writes while the render thread reads.
"""

import threading


class Terminal:
    def __init__(self, cols=80, rows=24, scrollback=5000):
        if cols < 1 or rows < 1:  # a 0/negative grid would crash on the first write
            raise ValueError(f"cols and rows must be >= 1 (got {cols}x{rows})")
        self.cols, self.rows = cols, rows
        self.grid = [[" "] * cols for _ in range(rows)]
        self.cx = self.cy = 0
        self.lock = threading.RLock()
        self.dirty = True
        self._esc = ""  # pending escape sequence ("" = not in one)
        # lines that have scrolled off the top -- the hardcopy "paper roll" a
        # period TTY (ASR-33 / DECwriter) left in your lap. Glass terminals of the
        # DECWAR era had none; this is purely a viewing aid for re-reading what
        # already crossed the screen, so it stays inside the display-only rule.
        self.scrollback = []
        self.max_scrollback = scrollback

    # ---- output (called by the hosted program) ----
    def write(self, text):
        with self.lock:
            for ch in text:
                self._putc(ch)
            self.dirty = True

    def clear(self):
        with self.lock:  # RLock -> safe even though the form-feed path holds it via write()
            for row in self.grid:
                row[:] = [" "] * self.cols
            self.cx = self.cy = 0

    def _newline(self):
        self.cx = 0
        self.cy += 1
        if self.cy >= self.rows:  # scroll up one line
            self.scrollback.append(self.grid.pop(0))  # keep it on the paper roll
            if len(self.scrollback) > self.max_scrollback:
                del self.scrollback[: len(self.scrollback) - self.max_scrollback]
            self.grid.append([" "] * self.cols)
            self.cy = self.rows - 1

    def _putc(self, ch):
        if self._esc:
            self._esc += ch
            self._handle_esc()
            return
        if ch == "\x1b":
            self._esc = "\x1b"
        elif ch == "\n":
            self._newline()
        elif ch == "\r":
            self.cx = 0
        elif ch == "\b":
            self.cx = max(0, self.cx - 1)
        elif ch == "\f":
            self.clear()
        elif ch == "\t":
            self.cx = min(self.cols - 1, (self.cx // 8 + 1) * 8)
        elif ord(ch) >= 32:
            if self.cx >= self.cols:
                self._newline()
            self.grid[self.cy][self.cx] = ch
            self.cx += 1
        # other control chars: ignore

    def _handle_esc(self):
        s = self._esc
        if len(s) < 2:
            return
        c = s[1]
        if c == "H":  # cursor home
            self.cx = self.cy = 0
        elif c == "J":  # erase to end of screen
            for x in range(self.cx, self.cols):
                self.grid[self.cy][x] = " "
            for y in range(self.cy + 1, self.rows):
                self.grid[y][:] = [" "] * self.cols
        elif c == "K":  # erase to end of line
            for x in range(self.cx, self.cols):
                self.grid[self.cy][x] = " "
        elif c == "Y":  # direct cursor address
            if len(s) < 4:
                return  # need row + col bytes
            self.cy = min(self.rows - 1, max(0, ord(s[2]) - 32))
            self.cx = min(self.cols - 1, max(0, ord(s[3]) - 32))
        elif c in "ABCD":  # cursor up/down/right/left
            self.cy -= c == "A"
            self.cy += c == "B"
            self.cx += c == "C"
            self.cx -= c == "D"
            self.cx = min(self.cols - 1, max(0, self.cx))
            self.cy = min(self.rows - 1, max(0, self.cy))
        self._esc = ""  # sequence consumed

    # ---- view (called by a renderer) ----
    def snapshot(self):
        """The whole screen as text -- exact content, no deps. How an observer reads it."""
        with self.lock:
            return "\n".join("".join(row) for row in self.grid)

    def rows_text(self):
        with self.lock:
            return ["".join(row) for row in self.grid]

    def max_scroll(self):
        return len(self.scrollback)

    def view_rows(self, offset=0):
        """`rows` lines of the display, scrolled back `offset` lines into the paper
        roll. offset 0 = the live screen; offset N = N lines older (clamped to the
        scrollback length). The hosted program never sees this -- it always writes
        to the live grid; this only changes what the renderer shows."""
        with self.lock:
            if offset <= 0:
                return ["".join(row) for row in self.grid]
            offset = min(offset, len(self.scrollback))
            combined = self.scrollback + self.grid
            end = len(combined) - offset
            window = combined[end - self.rows : end]
            return ["".join(row) for row in window]
