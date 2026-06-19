"""A live arcade renderer for a Session -- a green-phosphor VT52-style window.

The arcade (pyglet/OpenGL) twin of `pygame_ui`: the same `run(session, runner, ...)`
shape, the same green-on-near-black character grid, scrollback, snapshots, and owning
teardown. Having two graphical renderers that share nothing but the Session contract is
the point -- a renderer is just an adapter over the UI-agnostic core.

`arcade` is the `arcade` extra and is imported lazily (the window class is built on first
`run()`), so `import tappty` and `import tappty.arcade_ui` work with arcade absent. Each
row is drawn as a single pooled `arcade.Text` (cheap, and a monospace font keeps the
columns aligned), with the cursor and scrollback bar drawn as primitives.
"""

import logging
import os

log = logging.getLogger(__name__)

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FG = (90, 255, 130)  # phosphor green
BG = (6, 20, 8)

# Monospace families to try by name when the bundled DejaVu path is absent (a
# non-monospace fallback would misalign the grid, so we look hard before giving up).
_MONO_FALLBACKS = ("DejaVu Sans Mono", "Liberation Mono", "Consolas", "Courier New", "monospace")

_WINDOW_CLASS = None  # the arcade.Window subclass, built once arcade is importable


def _load_mono_font():
    """Register the bundled DejaVu Sans Mono if present, else find a system monospace
    family. Returns the family name to pass to `arcade.Text`, or None for arcade's default
    (which is not monospace -- a last resort)."""
    import arcade
    import pyglet

    if os.path.exists(FONT_PATH):
        try:
            arcade.load_font(FONT_PATH)
            return "DejaVu Sans Mono"
        except Exception as e:  # unreadable/odd font file -- fall through to system fonts
            log.debug("load_font(%s) failed: %s", FONT_PATH, e)
    for name in _MONO_FALLBACKS:
        try:
            if pyglet.font.have_font(name):
                return name
        except Exception:
            pass
    return None


def _cell_metrics(font_name, font_size):
    """The monospace cell size (advance width, line height) in pixels. Needs a live GL
    context (glyph layout), so call this only after the window exists."""
    import arcade
    import pyglet

    probe = arcade.Text("M" * 10, 0, 0, FG, font_size, font_name=font_name)
    cw = probe.content_width / 10.0
    try:
        pf = pyglet.font.load(font_name, font_size)
        chh = pf.ascent - pf.descent  # descent is negative, so this is the full line height
    except Exception:
        chh = probe.content_height
    return max(1.0, cw), max(1.0, chh)


def _write_text_snapshot(path, session):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(session.term.snapshot())
    except OSError as e:  # snapshots are best-effort -- never kill the render loop
        log.debug("snapshot write failed: %s", e)


def _save_png(w, h, path):
    import arcade

    try:
        arcade.get_image(0, 0, w, h).save(path)
    except Exception as e:  # best-effort, like the text snapshot
        log.debug("PNG snapshot failed: %s", e)


def _window_class():
    """Build (once) and return the arcade.Window subclass. Deferred so the arcade import
    stays lazy -- a class can't subclass arcade.Window until arcade is imported."""
    global _WINDOW_CLASS
    if _WINDOW_CLASS is not None:
        return _WINDOW_CLASS

    import arcade

    class _TerminalWindow(arcade.Window):
        def __init__(
            self, session, title, snapshot_path, font_size, exit_when_done, fps, max_seconds
        ):
            self.session = session
            cols, rows = session.term.cols, session.term.rows
            # Provisional size to get a GL context; the exact grid size needs glyph metrics,
            # which need that context -- so measure, then resize.
            est_cw, est_chh = font_size * 0.62, font_size * 1.3
            super().__init__(
                max(1, int(cols * est_cw)),
                max(1, int(rows * est_chh)),
                title,
                update_rate=1.0 / fps,
                draw_rate=1.0 / fps,  # arcade asserts draw_rate >= update_rate
            )
            self.background_color = BG
            self._cols, self._rows = cols, rows
            self._snapshot_path = snapshot_path
            self._exit_when_done = exit_when_done
            self._max_seconds = max_seconds
            self._scroll = 0
            self._page = max(1, rows - 1)
            self._t = 0.0  # seconds since start (drives blink, snapshots, the cap)
            self._done_t = 0.0
            self._last_snap = -1.0
            self._want_png = False
            self._font = _load_mono_font()
            self._cw, self._chh = _cell_metrics(self._font, font_size)
            self.set_size(int(cols * self._cw), int(rows * self._chh))
            # one reused Text per row (monospace -> a whole row is one string), plus the
            # inverted scrollback tag; pooled so we don't build Text objects per frame.
            self._row_text = [
                arcade.Text("", 0, 0, FG, font_size, font_name=self._font, anchor_y="top")
                for _ in range(rows)
            ]
            self._tag_text = arcade.Text(
                "", 0, 0, BG, font_size, font_name=self._font, anchor_y="top"
            )

        def on_update(self, dt):
            self._t += dt
            if self._snapshot_path and self._t - self._last_snap >= 1.0:
                self._last_snap = self._t
                _write_text_snapshot(self._snapshot_path, self.session)
                self._want_png = True  # captured next on_draw (needs the GL framebuffer)
            if self.session.done:
                self._done_t += dt
                if self._exit_when_done and self._done_t > 1.0:
                    self.close()
            if self._max_seconds is not None and self._t >= self._max_seconds:
                self.close()  # hard cap (scripting/tests)

        def on_draw(self):
            self.clear()
            term = self.session.term
            for r, line in enumerate(term.view_rows(self._scroll)):
                t = self._row_text[r]
                t.text = line or " "  # arcade.Text dislikes an empty string
                t.x = 0
                t.y = self.height - r * self._chh
                t.color = FG
                t.draw()
            if self._scroll == 0:
                if int(self._t * 2) % 2 == 0:  # blink ~1 Hz (live only)
                    left = term.cx * self._cw
                    top = self.height - term.cy * self._chh
                    arcade.draw_lrbt_rectangle_outline(
                        left, left + self._cw, top - self._chh, top, FG, 1
                    )
            else:  # scrollback indicator on the last row (inverted: BG on FG)
                y = self.height - (self._rows - 1) * self._chh
                arcade.draw_lrbt_rectangle_filled(0, self.width, y - self._chh, y, FG)
                self._tag_text.text = (
                    f" -- SCROLLBACK {self._scroll}/{term.max_scroll()} (PgDn / type to resume) "
                )
                self._tag_text.x, self._tag_text.y, self._tag_text.color = 0, y, BG
                self._tag_text.draw()
            if self._want_png:
                self._want_png = False
                _save_png(
                    self.width,
                    self.height,
                    (self._snapshot_path + ".png") if self._snapshot_path else "/tmp/tapterm.png",
                )

        def on_text(self, text):  # printable input; Enter/Backspace arrive via on_key_press
            if text and text.isprintable():
                self._scroll = 0  # any typing snaps back to live
                for ch in text:
                    self.session.feed_key(ch)

        def on_key_press(self, symbol, modifiers):
            k = arcade.key
            if symbol in (k.RETURN, k.NUM_ENTER):
                self._scroll = 0
                self.session.feed_key("\r")
            elif symbol == k.BACKSPACE:
                self._scroll = 0
                self.session.feed_key("\b")
            elif symbol == k.F12:
                self._want_png = True  # save a screenshot
            elif symbol == k.PAGEUP:
                self._scroll = min(self.session.term.max_scroll(), self._scroll + self._page)
            elif symbol == k.PAGEDOWN:
                self._scroll = max(0, self._scroll - self._page)
            elif symbol == k.BRACKETRIGHT and (modifiers & k.MOD_CTRL):
                self.close()  # Ctrl-] : force quit (parity with the curses UI)

        def on_mouse_scroll(self, x, y, sx, sy):  # wheel up = back into the paper roll
            self._scroll = max(0, min(self.session.term.max_scroll(), self._scroll + sy))

    _WINDOW_CLASS = _TerminalWindow
    return _WINDOW_CLASS


def _build_window(
    session,
    title="tapterm",
    snapshot_path=None,
    font_size=18,
    exit_when_done=False,
    fps=30,
    max_seconds=None,
):
    """Construct the terminal window (arcade must be importable). Factored out of `run` so
    a test can pump `on_update`/`on_draw` by hand instead of entering arcade's event loop."""
    import pyglet

    # pyglet (arcade's backend) probes an audio driver at import; on a host with no sound
    # server (e.g. WSLg after its audio service drops out) that probe blocks ~55s before the
    # window can open. We never play audio, so force the silent driver before importing arcade.
    pyglet.options["audio"] = ("silent",)
    return _window_class()(
        session, title, snapshot_path, font_size, exit_when_done, fps, max_seconds
    )


def run(
    session,
    runner,
    title="tapterm",
    snapshot_path=None,
    font_size=18,
    exit_when_done=False,
    fps=30,
    max_seconds=None,
):
    if fps < 1:
        raise ValueError("fps must be >= 1")
    import arcade

    window = _build_window(
        session, title, snapshot_path, font_size, exit_when_done, fps, max_seconds
    )
    session.run_in_thread(runner)  # start the hosted program
    try:
        arcade.run()  # blocks until the window closes (done/cap/Ctrl-]/the close button)
    finally:
        if snapshot_path:  # final snapshot
            _write_text_snapshot(snapshot_path, session)
        session.stop()  # owning renderer: stop the hosted source when the window closes
        try:
            window.close()
        except Exception:
            pass
