"""Composable terminal panels + a single-window compositor.

A TerminalPanel is a draw-into-rect widget over a *pluggable backing*:
  * SessionBacking -- an in-process Session (its live Terminal + input), OR
  * BusBacking     -- a REMOTE session over the bus socket (FRAME snapshots in,
                      keystrokes out) -- so sessions in other processes tile too.
Both present the same tiny interface (grid() -> {rows,cx,cy,cols,rows_n};
feed_key(ch); focus(); close()), so a panel doesn't care where its bytes come from.

Each terminal tile supports mouse PAN + ZOOM: wheel zooms (font size), left-drag pans
the viewport, right-click resets to fit + cursor-follow. A panel is equally an
EMBEDDABLE widget (drop one into any pygame app) and a tile in the Compositor (keys
route to the focused tile = the talking stick per tile). See docs/DESIGN.md.
"""

import logging
import os
import queue
import threading
from collections import deque

log = logging.getLogger(__name__)

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FG = (90, 255, 130)
BG = (6, 12, 10)
FOCUS = (120, 255, 160)
IDLE = (40, 60, 50)
ZMIN, ZMAX = 6, 40


def _font(size):
    import pygame

    return pygame.font.Font(FONT_PATH if os.path.exists(FONT_PATH) else None, size)


def clamp_view(cols, rows_n, fit_c, fit_r, ox, oy):
    """A pan offset clamped to keep the visible window inside the model. Returns
    (ox, oy, vw, vh)."""
    vw, vh = min(cols, fit_c), min(rows_n, fit_r)
    ox = max(0, min(int(ox), cols - vw))
    oy = max(0, min(int(oy), rows_n - vh))
    return ox, oy, vw, vh


# ---- draw-into-rect widgets ------------------------------------------------
def _expand(row_runs, cols):
    """A row's RLE runs (`style.encode_row`) -> a per-column list of
    (ch, fg_rgb, bg_rgb, bold, italic, underline, strike, blink); None for unset columns."""
    line = [None] * cols
    for run in row_runs:
        col, text, fg_hex, bg_hex, bold, italic, underline, strike, blink = run
        fg = (int(fg_hex[0:2], 16), int(fg_hex[2:4], 16), int(fg_hex[4:6], 16))
        bg = (int(bg_hex[0:2], 16), int(bg_hex[2:4], 16), int(bg_hex[4:6], 16))
        for i, ch in enumerate(text):
            c = col + i
            if 0 <= c < cols:
                line[c] = (
                    ch,
                    fg,
                    bg,
                    bool(bold),
                    bool(italic),
                    bool(underline),
                    bool(strike),
                    bool(blink),
                )
    return line


def draw_terminal(surface, rect, grid, font, glyphs, pan=None, blink_on=True):
    """Draw a styled grid dict (its `cells` runs) into the tile, in full SGR color. pan=None
    follows the cursor (fit view); a (ox, oy) pan shows that region (clamped). Returns
    (ox, oy, vw, vh, cw, chh)."""
    import pygame

    from tappty import style
    from tappty.curses_ui import viewport

    x0, y0, w, h = rect
    cw, chh = font.size("M")[0], font.get_linesize()
    cols = grid.get("cols", 80)
    cells = grid.get("cells") or []
    rows_n = grid.get("rows_n", len(cells))
    fit_c, fit_r = max(1, w // cw), max(1, h // chh)
    if pan is None:
        ox, oy, vw, vh = viewport(
            cols, rows_n, fit_c, fit_r, grid.get("cx", 0), grid.get("cy", 0), 0
        )
    else:
        ox, oy, vw, vh = clamp_view(cols, rows_n, fit_c, fit_r, pan[0], pan[1])
    has_strike = hasattr(font, "set_strikethrough")
    for yy in range(vh):
        line = _expand(cells[oy + yy], cols) if 0 <= oy + yy < len(cells) else []
        base = y0 + yy * chh
        for xx in range(vw):
            cell = line[ox + xx] if ox + xx < len(line) else None
            if cell is None:
                continue
            ch, fg, bg, bold, italic, underline, strike, blink = cell
            px = x0 + xx * cw
            if bg != style.BG:  # fill only non-default backgrounds
                pygame.draw.rect(surface, bg, (px, base, cw, chh))
            if (blink and not blink_on) or ch == " " or not ch.isprintable():
                continue
            key = (ch, fg, bold, italic, underline, strike)
            g = glyphs.get(key)
            if g is None:  # render-on-demand per glyph + style
                font.set_bold(bold)
                font.set_italic(italic)
                font.set_underline(underline)
                if has_strike:
                    font.set_strikethrough(strike)
                g = font.render(ch, True, fg)
                glyphs[key] = g
            surface.blit(g, (px, base))
    return ox, oy, vw, vh, cw, chh


# ---- pluggable panel backings ----------------------------------------------
class SessionBacking:
    """Back a panel with an in-process Session (its live Terminal + input). The local
    operator only types while it explicitly HOLDS the stick (no auto-grab on typing);
    toggle_stick() grabs/releases it. This is a NON-OWNING view: it doesn't start or stop
    the session (close() is a no-op), since the same session may outlive the panel or be
    driven elsewhere. Call session.stop() yourself if the panel owns the program."""

    def __init__(self, session, op="local"):
        self.session = session
        self.op = op  # the local operator's controller name

    def grid(self):
        return self.session.snapshot()

    def feed_key(self, ch):
        self.session.feed_key(ch, by=self.op, auto_take=False)  # type only if holding

    def has_stick(self):
        return self.session.has_control(self.op)

    def toggle_stick(self):
        if self.has_stick():
            self.session.release(self.op)  # give it back (to the AI, etc.)
        else:
            self.session.claim_control(self.op, "human")
            self.session.take(self.op)  # explicitly grab it

    def focus(self):
        pass  # focus never grabs control

    def close(self):
        pass  # non-owning: leave the session running (see class docstring)


class BusBacking:
    """Back a panel with a REMOTE session over the bus socket. Subscribes for FRAME
    snapshots (kept as the latest grid) and forwards keystrokes as KEY. focus() does NOT
    grab control (it's a no-op) -- control is taken explicitly via toggle_stick() (the
    compositor binds it to F2). Lets the compositor tile sessions that run in other
    processes."""

    def __init__(self, socket_path, name="panel", role="human", token=None):
        from tappty.bus import BusClient

        self.name = name
        self.client = BusClient(socket_path, token=token).connect()
        self.client.hello(role=role, name=name)
        self.client.sub()
        self.client.send("SNAP")
        # placeholder until the first FRAME/SNAP arrives (styled `cells`, like a real frame)
        self._frame = {
            "rows": [""] * 24,
            "cells": [[] for _ in range(24)],
            "cx": 0,
            "cy": 0,
            "cols": 80,
            "rows_n": 24,
        }
        self._pending = deque(maxlen=240)  # frames awaiting paced replay
        self._driver = None  # who holds the remote stick (tracked)
        self._run = True
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self):
        while self._run:
            try:
                v, d = self.client.inbox.get(timeout=0.3)
            except queue.Empty:
                continue
            except Exception:
                break
            if v == "FRAME" and isinstance(d, dict):
                self._pending.append(d)  # queue for paced replay (see grid())
            elif isinstance(d, dict):
                if v == "OK" and "name" in d:  # adopt the server-assigned (unique) name
                    self.name = d["name"]
                if d.get("name") == "DRIVER":
                    self._driver = d.get("who")
                elif "driver" in d:  # OK/DENIED/INFO replies
                    self._driver = d["driver"]

    def grid(self):
        # Replay queued frames a few per render tick instead of jumping straight to the
        # newest, so the remote program's output scrolls in like a live terminal. Drain
        # ~1/6 of the backlog each tick (min 1): smooth when idle, catching up under load.
        q = self._pending
        for _ in range(max(1, len(q) // 6)):
            if not q:
                break
            self._frame = q.popleft()
        return self._frame

    def feed_key(self, ch):
        self.client.key(ch)  # server gates on holding the stick

    def has_stick(self):
        return self._driver == self.name

    def toggle_stick(self):
        self.client.release() if self.has_stick() else self.client.take()

    def focus(self):
        pass  # focus never grabs control

    def close(self):
        self._run = False
        self.client.close()


# ---- draw context (font/glyph atlas cache, shared across panels) -----------
class DrawCtx:
    def __init__(self):
        self.gfont = _font(14)
        self._atlas = {}
        self._fm = {}
        self._fit = {}

    def atlas(self, size):
        size = max(ZMIN, min(ZMAX, int(size)))
        if size not in self._atlas:
            self._atlas[size] = (_font(size), {})  # glyphs rendered lazily in draw_terminal
        return self._atlas[size]

    def _metrics(self, size):
        if size not in self._fm:
            f = _font(size)
            self._fm[size] = (f.size("M")[0], f.get_linesize())
        return self._fm[size]

    def fit_size(self, w, h, cols=80, rows=24):
        """Largest font size at which the whole `cols`x`rows` model fits in the tile."""
        key = (w, h, cols, rows)  # cache per tile size AND grid size (not just the tile)
        if key not in self._fit:
            best = ZMIN
            for s in range(ZMIN, ZMAX + 1):
                cw, chh = self._metrics(s)
                if cols * cw <= w and rows * chh <= h:
                    best = s
                else:
                    break
            self._fit[key] = best
        return self._fit[key]


# ---- panels ----------------------------------------------------------------
class TerminalPanel:
    kind = "term"

    def __init__(self, backing, rect, title=""):
        self.backing, self.rect, self.title = backing, rect, title
        self.zoom = None  # None = fit (whole 80x24 visible); else font size
        self.pan = [0, 0]  # viewport offset in cells (when zoomed in)
        self._cw = self._chh = 1
        self._fit = ZMIN

    def draw(self, surface, ctx, blink_on=True):
        # default = the largest font at which the FULL grid fits the tile; zoom in from
        # there magnifies a region and pan moves it. Use the backing's actual dimensions
        # (a cast/terminal need not be 80x24) so the fit font size is right.
        grid = self.backing.grid()
        self._fit = ctx.fit_size(
            self.rect[2], self.rect[3], grid.get("cols", 80), grid.get("rows_n", 24)
        )
        font, glyphs = ctx.atlas(self.zoom or self._fit)
        ox, oy, vw, vh, cw, chh = draw_terminal(
            surface, self.rect, grid, font, glyphs, self.pan, blink_on
        )
        self._cw, self._chh = cw, chh
        self.pan = [ox, oy]  # store the clamped offset

    def feed_key(self, ch):
        self.backing.feed_key(ch)

    def focus(self):
        self.backing.focus()

    def close(self):
        self.backing.close()

    def toggle_stick(self):
        self.backing.toggle_stick()

    def has_stick(self):
        return self.backing.has_stick()

    # ---- mouse view controls ----
    def zoom_by(self, notches):
        base = self.zoom or self._fit
        self.zoom = max(self._fit, min(ZMAX, base + notches * 2))  # fit = fully zoomed out

    def pan_px(self, dx, dy):
        self.pan = [
            self.pan[0] - dx / max(1, self._cw),  # grab-drag the content
            self.pan[1] - dy / max(1, self._chh),
        ]

    def reset(self):
        self.zoom, self.pan = None, [0, 0]


def _hit(panels, pos):
    for i, p in enumerate(panels):
        x, y, w, h = p.rect
        if x <= pos[0] < x + w and y <= pos[1] < y + h:
            return i, p
    return None, None


# ---- the compositor --------------------------------------------------------
def run(
    panels,
    title="tappty dashboard",
    size=(1280, 720),
    fps=10,
    snapshot_path=None,
    max_seconds=None,
):
    if fps < 1:
        raise ValueError("fps must be >= 1")
    import pygame

    pygame.init()
    screen = pygame.display.set_mode(size)
    pygame.display.set_caption(title)
    ctx = DrawCtx()
    term_ix = [i for i, p in enumerate(panels) if p.kind == "term"]
    focus = term_ix[0] if term_ix else None
    if focus is not None:
        panels[focus].focus()
    dragging = None
    clock = pygame.time.Clock()
    running, frame = True, 0
    while running:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.MOUSEWHEEL:
                i, p = _hit(panels, pygame.mouse.get_pos())
                if p is not None and p.kind == "term":
                    focus = i
                    p.focus()
                    p.zoom_by(e.y)
            elif e.type == pygame.MOUSEBUTTONDOWN:
                i, p = _hit(panels, e.pos)
                if p is not None and p.kind == "term":
                    focus = i
                    p.focus()
                    if e.button == 1:
                        dragging = p
                    elif e.button == 3:
                        p.reset()
            elif e.type == pygame.MOUSEBUTTONUP:
                dragging = None
            elif e.type == pygame.MOUSEMOTION:
                if dragging is not None and e.buttons[0]:
                    dragging.pan_px(e.rel[0], e.rel[1])
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    running = False
                elif e.key == pygame.K_TAB and term_ix:
                    focus = (
                        term_ix[(term_ix.index(focus) + 1) % len(term_ix)]
                        if focus in term_ix
                        else term_ix[0]
                    )
                    panels[focus].focus()
                elif e.key == pygame.K_F2 and focus is not None and panels[focus].kind == "term":
                    panels[focus].toggle_stick()  # explicit take/give control
                elif focus is not None:
                    panels[focus].feed_key(
                        "\r"
                        if e.key == pygame.K_RETURN
                        else "\b"
                        if e.key == pygame.K_BACKSPACE
                        else e.unicode
                    )
        screen.fill(BG)
        blink_on = (frame // max(1, fps // 2)) % 2 == 0  # blink phase, ~1 Hz
        for i, p in enumerate(panels):
            p.draw(screen, ctx, blink_on)
            col = FOCUS if i == focus else IDLE
            pygame.draw.rect(screen, col, p.rect, 1)
            label = p.title
            if p.kind == "term":
                label += (
                    "  [F2: " + ("YOU have control" if p.has_stick() else "take control") + "]"
                )
                if p.zoom:
                    label += f"  zoom {p.zoom}"
            if label:
                screen.blit(ctx.gfont.render(label, True, col), (p.rect[0] + 4, p.rect[1] - 16))
        pygame.display.flip()
        if snapshot_path and frame % max(1, fps) == 0:
            try:
                pygame.image.save(screen, snapshot_path + ".png")
            except Exception as e:  # snapshots are best-effort -- never kill the render loop
                log.debug("dashboard snapshot failed: %s", e)
        clock.tick(fps)
        frame += 1
        if max_seconds is not None and frame >= max_seconds * fps:
            running = False
    for p in panels:
        p.close()
    pygame.quit()
