"""Cell styling shared by the terminal backends and the GUI renderers.

A `Cell` is one character plus its SGR attributes (foreground, background, bold, reverse), as
the full-ANSI `PyteTerminal` reports them; the VT52 `Terminal`, which has no color, reports
every cell with the *default* style. `rgb()` maps a pyte color (a name, or a 6-hex string from
256-color / truecolor) to an (r, g, b), returning None for "default" so a renderer substitutes
its own phosphor color. That is how the green-phosphor identity survives the addition of color:
uncolored text stays green, and real color appears only where a program asks for it.

No dependencies -- safe to import anywhere (used by terminal.py, pyte_terminal.py, and the
pygame/arcade renderers).
"""

from collections import namedtuple

# Phosphor defaults -- the look both GUI renderers share; a "default" color resolves to these.
FG = (90, 255, 130)
BG = (6, 20, 8)

Cell = namedtuple("Cell", "char fg bg bold reverse")

# The 8 ANSI colors (xterm-ish RGB) and their bright variants. pyte names yellow "brown".
# Bold brightens a base color, as most terminals do.
_BASE = {
    "black": (0, 0, 0),
    "red": (205, 0, 0),
    "green": (0, 205, 0),
    "brown": (205, 205, 0),
    "blue": (0, 0, 238),
    "magenta": (205, 0, 205),
    "cyan": (0, 205, 205),
    "white": (229, 229, 229),
}
_BRIGHT = {
    "black": (127, 127, 127),
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "brown": (255, 255, 0),
    "blue": (92, 92, 255),
    "magenta": (255, 0, 255),
    "cyan": (0, 255, 255),
    "white": (255, 255, 255),
}


def default_cell(char):
    """A Cell with no color -- what the VT52 `Terminal` reports for every cell."""
    return Cell(char, "default", "default", False, False)


def rgb(color, bold=False):
    """(r, g, b) for a pyte color, or None for 'default' (the renderer fills in its own
    phosphor color). `color` is a name ('red', 'brightred', 'brown' = yellow) or a 6-hex
    string ('ff8700', from 256-color/truecolor). `bold` brightens a base color, as terminals do."""
    if not color or color == "default":
        return None
    if color.startswith("bright"):
        return _BRIGHT.get(color[6:])
    if color in _BASE:
        return (_BRIGHT if bold else _BASE)[color]
    if len(color) == 6:  # 256-color / truecolor, stored by pyte as a hex string
        try:
            return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
        except ValueError:
            return None
    return None


def resolve(cell, fg_default=FG, bg_default=BG):
    """A cell's concrete (fg_rgb, bg_rgb) for drawing: 'default' -> the renderer's phosphor
    colors, then `reverse` swaps the two (inverse video). bold is already folded into fg."""
    fg = rgb(cell.fg, cell.bold) or fg_default
    bg = rgb(cell.bg) or bg_default
    if cell.reverse:
        fg, bg = bg, fg
    return fg, bg


def runs(row, fg_default=FG, bg_default=BG):
    """Group a row of Cells into maximal runs that share one resolved (fg, bg), for a renderer
    that draws a run of same-styled cells as a single string. Yields (x, text, fg_rgb, bg_rgb)."""
    out = []
    start, buf, key = 0, [], None
    for x, cell in enumerate(row):
        fg, bg = resolve(cell, fg_default, bg_default)
        if key is None or (fg, bg) == key:
            if key is None:
                start, key = x, (fg, bg)
            buf.append(cell.char)
        else:
            out.append((start, "".join(buf), key[0], key[1]))
            start, buf, key = x, [cell.char], (fg, bg)
    if buf:
        out.append((start, "".join(buf), key[0], key[1]))
    return out
