"""A live pygame renderer for a Session -- a green-phosphor VT52-style window.

Renders the Terminal grid in a monospace font (green on near-black), forwards
keystrokes to the Session, and runs the hosted program in a background thread.
Optionally writes a text snapshot of the screen to a file each second, so an
automated observer can watch the same session the human sees. The renderer is just
an adapter over the UI-agnostic core; an arcade renderer would implement the same shape.
"""

import logging
import os

from tappty import keys, style

log = logging.getLogger(__name__)

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FG = style.FG  # phosphor green -- the "default" SGR color resolves to this
BG = style.BG


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
    import pygame

    pygame.init()
    cols, rows = session.term.cols, session.term.rows
    font = pygame.font.Font(FONT_PATH if os.path.exists(FONT_PATH) else None, font_size)
    # a true character grid: fixed cell = monospace advance x line height, and each
    # glyph pre-rendered once and blitted at its exact cell (no whole-row drift).
    cw = font.size("M")[0]
    chh = font.get_linesize()
    glyphs = {}  # lazily-rendered cache, keyed by (char, fg, bold, italic, underline)

    has_strike = hasattr(font, "set_strikethrough")  # pygame-ce >= 2.1.3

    def glyph(ch, fg, bold, italic, underline, strike):
        if ch == " " or not ch.isprintable():
            return None  # space + control chars: nothing to draw
        key = (ch, fg, bold, italic, underline, strike)
        g = glyphs.get(key)
        if g is None:
            if len(glyphs) > 4000:  # bound the cache across many colors/glyphs/attrs
                glyphs.clear()
            font.set_bold(bold)
            font.set_italic(italic)
            font.set_underline(underline)
            if has_strike:
                font.set_strikethrough(strike)
            g = font.render(ch, True, fg)
            glyphs[key] = g
        return g

    screen = pygame.display.set_mode((cols * cw, rows * chh))
    pygame.display.set_caption(title)

    # raw-mode key translation (full-TUI input): a pygame keycode -> VT bytes
    raw_special = {
        pygame.K_UP: "up", pygame.K_DOWN: "down", pygame.K_LEFT: "left",
        pygame.K_RIGHT: "right", pygame.K_HOME: "home", pygame.K_END: "end",
        pygame.K_PAGEUP: "pageup", pygame.K_PAGEDOWN: "pagedown",
        pygame.K_INSERT: "insert", pygame.K_DELETE: "delete", pygame.K_RETURN: "enter",
        pygame.K_KP_ENTER: "enter", pygame.K_BACKSPACE: "backspace", pygame.K_TAB: "tab",
        pygame.K_ESCAPE: "escape",
    }
    for _i in range(1, 13):
        raw_special[getattr(pygame, f"K_F{_i}")] = f"f{_i}"

    def raw_key(e):
        name = raw_special.get(e.key)
        if name is not None:
            return keys.KEYS[name]
        return e.unicode or None  # printable, or a control char (Ctrl-letter, etc.)

    session.run_in_thread(runner)  # start the hosted program
    clock = pygame.time.Clock()
    running, frame, done_frames = True, 0, 0
    scroll = 0  # lines back into the paper roll
    page = max(1, rows - 1)
    while running:
        e_f12 = False
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.MOUSEWHEEL:  # wheel up = back into history
                scroll = max(0, min(session.term.max_scroll(), scroll + e.y))
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_F12:
                    e_f12 = True  # save a screenshot PNG (always local)
                elif session.raw_keys:  # full-TUI mode: forward keystrokes raw
                    data = raw_key(e)
                    if data is not None:
                        scroll = 0
                        session.send_key(data)
                elif e.key == pygame.K_PAGEUP:
                    scroll = min(session.term.max_scroll(), scroll + page)
                elif e.key == pygame.K_PAGEDOWN:
                    scroll = max(0, scroll - page)
                elif e.key == pygame.K_RETURN:
                    scroll = 0  # any typing snaps back to live
                    session.feed_key("\r")
                elif e.key == pygame.K_BACKSPACE:
                    scroll = 0
                    session.feed_key("\b")
                elif e.unicode and e.unicode.isprintable():
                    scroll = 0
                    session.feed_key(e.unicode)
        screen.fill(BG)
        blink_on = (frame // max(1, fps // 2)) % 2 == 0  # blink toggles ~1 Hz
        for y, row in enumerate(session.term.cells(scroll)):
            base_y = y * chh
            for x, cell in enumerate(row):
                fg, bg = style.resolve(cell, FG, BG)  # "default" -> phosphor; reverse swaps
                if bg != BG:  # fill only non-default backgrounds (screen is already BG)
                    pygame.draw.rect(screen, bg, (x * cw, base_y, cw, chh))
                if cell.blink and not blink_on:  # blinking cell on its hidden phase
                    continue
                g = glyph(cell.char, fg, cell.bold, cell.italic, cell.underline, cell.strike)
                if g is not None:
                    screen.blit(g, (x * cw, base_y))
        if scroll == 0:
            if (frame // 15) % 2 == 0:  # blinking block cursor (live only)
                pygame.draw.rect(
                    screen, FG, (session.term.cx * cw, session.term.cy * chh, cw, chh), 1
                )
        else:  # scrollback indicator on last row
            tag = f" -- SCROLLBACK {scroll}/{session.term.max_scroll()} (PgDn / type to resume) "
            ind = font.render(tag, True, BG, FG)
            screen.blit(ind, (0, (rows - 1) * chh))
        pygame.display.flip()
        if e_f12:  # F12 (or auto) -> save a PNG
            try:
                pygame.image.save(
                    screen, snapshot_path + ".png" if snapshot_path else "/tmp/tapterm.png"
                )
            except Exception as e:  # snapshots are best-effort -- never kill the render loop
                log.debug("PNG snapshot failed: %s", e)
            e_f12 = False
        if snapshot_path and frame % fps == 0:
            try:
                with open(snapshot_path, "w") as f:
                    f.write(session.term.snapshot())
                pygame.image.save(screen, snapshot_path + ".png")  # pixels, for review
            except Exception as e:  # snapshots are best-effort -- never kill the render loop
                log.debug("snapshot write failed: %s", e)
        clock.tick(fps)
        frame += 1
        if session.done:  # program ended
            done_frames += 1
            if exit_when_done and done_frames > fps:
                running = False
        if max_seconds is not None and frame >= max_seconds * fps:
            running = False  # hard cap (scripting/tests)
    if snapshot_path:  # final snapshot
        try:
            with open(snapshot_path, "w") as f:
                f.write(session.term.snapshot())
        except OSError:
            pass
    session.stop()  # owning renderer: stop the hosted source when the window closes
    pygame.quit()
