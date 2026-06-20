"""A curses renderer for a Session -- run a hosted program in a plain terminal.

The Session's Terminal is a FIXED 80x24 model (the program stays sealed in its era).
This renderer draws a VIEWPORT into it: the whole thing when the real terminal is big
enough, a cursor-following sub-rectangle when it's smaller, and a full redraw on
resize. Resize never touches the model or the program -- it's purely render-side
(see docs/DESIGN.md). Path is VT52 -> our grid -> curses -> host-native;
curses/terminfo handles whatever terminal the user is actually on.

SGR color: when the terminal supports it, each cell is drawn in its `cells()` color (a
`PyteTerminal` via `--ansi`); a "default" foreground stays phosphor green, and a colorless
terminal falls back to its own default foreground.
"""

from tappty import style


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


DEFAULT_FG = 2  # curses.COLOR_GREEN -- the phosphor color a "default" foreground resolves to

_IDX = {  # pyte base color name -> curses color index (0-7), matching curses.COLOR_*
    "black": 0, "red": 1, "green": 2, "brown": 3,
    "blue": 4, "magenta": 5, "cyan": 6, "white": 7,
}
# (rgb, index, bright) for the 16 ANSI colors, to approximate a 256/truecolor hex to nearest.
_ANSI16 = [(style.rgb(n), i, False) for n, i in _IDX.items()] + [
    (style.rgb("bright" + n), i, True) for n, i in _IDX.items()
]


def _curses_color(name):
    """A pyte color name -> (curses index 0-7, is_bright), or None for 'default'/unknown.
    A 256-color/truecolor hex string approximates to the nearest ANSI-16 color."""
    if not name or name == "default":
        return None
    if name.startswith("bright"):
        i = _IDX.get(name[6:])
        return (i, True) if i is not None else None
    if name in _IDX:
        return (_IDX[name], False)
    rgb = style.rgb(name)
    if rgb is None:
        return None
    r, g, b = rgb
    _, i, bright = min(
        _ANSI16, key=lambda e: (e[0][0] - r) ** 2 + (e[0][1] - g) ** 2 + (e[0][2] - b) ** 2
    )
    return (i, bright)


def _cell_style(cell, colors=16):
    """Pure: a `style.Cell` -> (fg_index, bg_index_or_None, want_bold, reverse) for `colors`
    available colors. fg 'default' -> green (phosphor); a bright/bold foreground uses index+8
    when colors>=16, else the base index + want_bold (A_BOLD); bg 'default' -> None (the
    terminal's own default background)."""
    fg = _curses_color(cell.fg)
    if fg is None:
        fi, bright = DEFAULT_FG, cell.bold
    else:
        fi, base_bright = fg
        bright = base_bright or cell.bold
    want_bold = False
    if bright:
        if colors >= 16:
            fi += 8
        else:
            want_bold = True
    bg = _curses_color(cell.bg)
    if bg is None:
        bi = None
    else:
        bi, bg_bright = bg
        if bg_bright and colors >= 16:
            bi += 8
    return fi, bi, want_bold, cell.reverse


def _raw_bytes(curses, ch):
    """Translate a curses getch() code to the bytes to send the program in raw mode
    (arrows/function keys -> VT sequences; control bytes pass through), or None to drop it."""
    from tappty import keys

    special = {
        curses.KEY_UP: "up", curses.KEY_DOWN: "down", curses.KEY_LEFT: "left",
        curses.KEY_RIGHT: "right", curses.KEY_HOME: "home", curses.KEY_END: "end",
        curses.KEY_NPAGE: "pagedown", curses.KEY_PPAGE: "pageup",
        curses.KEY_IC: "insert", curses.KEY_DC: "delete", curses.KEY_BTAB: "backtab",
    }
    name = special.get(ch)
    if name is not None:
        return keys.KEYS[name]
    if curses.KEY_F0 + 1 <= ch <= curses.KEY_F0 + 12:  # F1..F12 (KEY_F0 is a constant)
        return keys.KEYS[f"f{ch - curses.KEY_F0}"]
    if ch in (curses.KEY_ENTER, 10, 13):
        return "\r"
    if ch in (curses.KEY_BACKSPACE, 127, 8):
        return "\x7f"
    if 0 <= ch < 256:  # printable + control bytes (Ctrl-A..Z = 1..26, Tab=9, Esc=27)
        return chr(ch)
    return None


def _feed(session, ch):
    import curses

    if session.raw_keys:  # full-TUI mode: forward keystrokes raw, no echo/line buffer
        data = _raw_bytes(curses, ch)
        if data is not None:
            session.send_key(data)
        return
    if ch in (curses.KEY_ENTER, 10, 13):
        session.feed_key("\r")
    elif ch in (curses.KEY_BACKSPACE, 127, 8):
        session.feed_key("\b")
    elif 32 <= ch < 127:
        session.feed_key(chr(ch))
    # arrows / function keys: ignored in line mode (our programs are line-oriented)


def run(session, runner, title="tapterm", refresh_ms=50):
    import curses

    def _main(stdscr):
        curses.curs_set(1)
        stdscr.nodelay(True)
        stdscr.timeout(refresh_ms)
        if session.raw_keys:
            curses.raw()  # deliver Ctrl-C/Z/\ to the program instead of raising signals
        use_color = False
        default_bg = -1
        colors = 0
        max_pairs = 0
        pairs = {}  # (fg_index, bg_index) -> allocated curses pair number
        try:
            curses.start_color()
            use_color = curses.has_colors()
        except curses.error:
            use_color = False
        if use_color:
            try:
                curses.use_default_colors()  # lets bg = -1 mean the terminal's own background
            except curses.error:
                default_bg = curses.COLOR_BLACK
            colors = curses.COLORS
            max_pairs = curses.COLOR_PAIRS

        def cell_attr(cell):
            """The curses attribute for one styled cell: its color pair (lazily allocated,
            capped at COLOR_PAIRS) plus A_BOLD / A_REVERSE / A_UNDERLINE / A_ITALIC as needed."""
            a = 0
            if cell.underline:
                a |= curses.A_UNDERLINE
            if cell.italic:
                a |= getattr(curses, "A_ITALIC", 0)  # A_ITALIC is ncurses-6 / not everywhere
            if cell.blink:
                a |= curses.A_BLINK  # curses has no strikethrough attr, so strike is dropped here
            if not use_color:  # colorless terminal: attributes only, default foreground
                return a | (curses.A_BOLD if cell.bold else 0)
            fi, bi, want_bold, rev = _cell_style(cell, colors)
            bg = default_bg if bi is None else bi
            key = (fi, bg)
            pair = pairs.get(key)
            if pair is None:
                pair = len(pairs) + 1  # pair 0 is reserved (default)
                if pair < max_pairs:
                    try:
                        curses.init_pair(pair, fi, bg)
                        pairs[key] = pair
                    except curses.error:
                        pair = 0
                else:
                    pair = 0  # out of pairs -> terminal default
            a |= curses.color_pair(pair)
            if want_bold:
                a |= curses.A_BOLD
            if rev:
                a |= curses.A_REVERSE
            return a

        session.run_in_thread(runner)
        finishing = False
        while True:
            sh, sw = stdscr.getmaxyx()
            term = session.term
            grid = term.cells()
            ox, oy, vw, vh = viewport(term.cols, term.rows, sw, sh, term.cx, term.cy)
            stdscr.erase()
            for y in range(vh):
                row = grid[oy + y][ox : ox + vw]
                attrs = [cell_attr(c) for c in row]
                x = 0
                while x < len(row):  # draw maximal same-attribute runs in one addstr
                    a = attrs[x]
                    x2 = x + 1
                    while x2 < len(row) and attrs[x2] == a:
                        x2 += 1
                    try:
                        stdscr.addstr(y, x, "".join(c.char for c in row[x:x2]), a)
                    except curses.error:
                        pass
                    x = x2
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
