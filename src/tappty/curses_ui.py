"""A curses renderer for a Session -- run a hosted program in a plain terminal.

The Session's Terminal is a FIXED 80x24 model (the program stays sealed in its era).
This renderer draws a VIEWPORT into it: the whole thing when the real terminal is big
enough, a cursor-following sub-rectangle when it's smaller, and a full redraw on
resize. Resize never touches the model or the program -- it's purely render-side
(see docs/DESIGN.md). Path is VT52 -> our grid -> curses -> host-native;
curses/terminfo handles whatever terminal the user is actually on.
"""


def viewport(model_w, model_h, screen_w, screen_h, cx, cy, status=1):
    """The visible sub-rectangle of the (model_w x model_h) grid inside an
    (screen_w x screen_h) terminal, keeping the cursor (cx, cy) in view. Returns
    (ox, oy, vw, vh): the top-left model offset and the view size. Reserves `status`
    rows at the bottom for a status line when the terminal is taller than the view."""
    avail_h = max(1, screen_h - status)
    vw = min(model_w, max(1, screen_w))
    vh = min(model_h, avail_h)
    ox = 0 if vw >= model_w else min(max(0, cx - vw // 2), model_w - vw)
    oy = 0 if vh >= model_h else min(max(0, cy - vh // 2), model_h - vh)
    return ox, oy, vw, vh


def _feed(session, ch):
    import curses

    if ch in (curses.KEY_ENTER, 10, 13):
        session.feed_key("\r")
    elif ch in (curses.KEY_BACKSPACE, 127, 8):
        session.feed_key("\b")
    elif 32 <= ch < 127:
        session.feed_key(chr(ch))
    # arrows / function keys: ignored (our programs are line-oriented)


def run(session, runner, title="tapterm", refresh_ms=50):
    import curses

    def _main(stdscr):
        curses.curs_set(1)
        stdscr.nodelay(True)
        stdscr.timeout(refresh_ms)
        try:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_GREEN, -1)
            attr = curses.color_pair(1)
        except curses.error:
            attr = 0

        session.run_in_thread(runner)
        finishing = False
        while True:
            sh, sw = stdscr.getmaxyx()
            term = session.term
            rows = term.rows_text()
            ox, oy, vw, vh = viewport(term.cols, term.rows, sw, sh, term.cx, term.cy)
            stdscr.erase()
            for y in range(vh):
                seg = rows[oy + y][ox : ox + vw]
                try:
                    stdscr.addstr(y, 0, seg, attr)
                except curses.error:
                    pass
            if sh > vh:  # status line
                partial = vw < term.cols or vh < term.rows
                tag = (
                    f" {title}  {term.cols}x{term.rows}"
                    + (f" view@{ox},{oy} [partial]" if partial else "")
                    + (" [done -- press a key]" if session.done else "")
                    + " "
                )
                try:
                    stdscr.addstr(vh, 0, tag[: max(0, sw - 1)], curses.A_REVERSE)
                except curses.error:
                    pass
            scy, scx = term.cy - oy, term.cx - ox  # place the hardware cursor
            if 0 <= scy < vh and 0 <= scx < vw:
                try:
                    stdscr.move(scy, scx)
                except curses.error:
                    pass
            stdscr.refresh()

            ch = stdscr.getch()
            if session.done and not finishing:  # one last draw, then wait
                finishing = True
                stdscr.nodelay(False)
                continue
            if finishing and ch != -1:
                return
            if ch in (-1, curses.KEY_RESIZE):
                continue
            if ch == 29:  # Ctrl-] : force quit
                return
            _feed(session, ch)

    try:
        curses.wrapper(_main)
    finally:
        session.stop()  # owning renderer: stop the hosted source on quit
