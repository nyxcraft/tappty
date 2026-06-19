"""A live pygame renderer for a Session -- a green-phosphor VT52-style window.

Renders the Terminal grid in a monospace font (green on near-black), forwards
keystrokes to the Session, and runs the hosted program in a background thread.
Optionally writes a text snapshot of the screen to a file each second, so an
automated observer can watch the same session the human sees. The renderer is just
an adapter over the UI-agnostic core; an arcade renderer would implement the same shape.
"""

import os

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FG = (90, 255, 130)  # phosphor green
BG = (6, 20, 8)


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
    import pygame

    pygame.init()
    cols, rows = session.term.cols, session.term.rows
    font = pygame.font.Font(FONT_PATH if os.path.exists(FONT_PATH) else None, font_size)
    # a true character grid: fixed cell = monospace advance x line height, and each
    # glyph pre-rendered once and blitted at its exact cell (no whole-row drift).
    cw = font.size("M")[0]
    chh = font.get_linesize()
    glyphs = {}  # lazily-rendered cache (any Unicode glyph)

    def glyph(ch):
        if ch == " " or not ch.isprintable():
            return None  # space + control chars: nothing to draw
        g = glyphs.get(ch)
        if g is None:
            g = font.render(ch, True, FG)
            glyphs[ch] = g
        return g

    screen = pygame.display.set_mode((cols * cw, rows * chh))
    pygame.display.set_caption(title)

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
                    e_f12 = True  # save a screenshot PNG
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
        for y, line in enumerate(session.term.view_rows(scroll)):
            base_y = y * chh
            for x, ch in enumerate(line):
                g = glyph(ch)  # render-on-demand; space/ctrl -> None
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
            except Exception:  # snapshots are best-effort -- never kill the render loop
                pass
            e_f12 = False
        if snapshot_path and frame % fps == 0:
            try:
                with open(snapshot_path, "w") as f:
                    f.write(session.term.snapshot())
                pygame.image.save(screen, snapshot_path + ".png")  # pixels, for review
            except Exception:  # snapshots are best-effort -- never kill the render loop
                pass
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
    pygame.quit()
