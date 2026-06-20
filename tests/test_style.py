"""SGR styling: the color palette, default->phosphor, reverse, and run-length grouping.

Pure logic shared by the terminal backends and the GUI renderers -- no deps, no display.
"""

from tappty import style


def test_default_color_is_none_so_renderer_uses_phosphor():
    assert style.rgb("default") is None
    assert style.rgb("") is None


def test_named_bright_and_bold_colors():
    assert style.rgb("red") == (205, 0, 0)
    assert style.rgb("brightred") == (255, 0, 0)
    assert style.rgb("red", bold=True) == (255, 0, 0)  # bold brightens a base color
    assert style.rgb("brown") == (205, 205, 0)  # pyte names yellow "brown"
    assert style.rgb("brightblack") == (127, 127, 127)


def test_hex_colors_from_256_and_truecolor():
    assert style.rgb("ff8700") == (255, 135, 0)
    assert style.rgb("000000") == (0, 0, 0)
    assert style.rgb("zzzzzz") is None  # not valid hex -> None (renderer uses phosphor)


def test_resolve_default_to_phosphor_then_reverse_swaps():
    plain = style.default_cell("x")
    assert style.resolve(plain) == (style.FG, style.BG)
    rev = plain._replace(reverse=True)
    assert style.resolve(rev) == (style.BG, style.FG)  # inverse video
    assert style.resolve(plain, (1, 2, 3), (4, 5, 6)) == ((1, 2, 3), (4, 5, 6))  # custom defaults


def test_char_width_wide_zero_and_normal():
    assert style.char_width("A") == 1
    assert style.char_width("é") == 1  # precomposed Latin -> one column
    assert style.char_width("日") == 2  # CJK ideograph (East-Asian Wide)
    assert style.char_width("Ａ") == 2  # fullwidth Latin
    assert style.char_width("👍") == 2  # single-code-point emoji (pyte reports it W)
    assert style.char_width("́") == 0  # combining acute accent hangs off the prev cell
    assert style.char_width("‍") == 0  # ZWJ (a format char) takes no column
    assert style.char_width("") == 0  # pyte's empty wide-glyph continuation cell


def _c(
    char,
    fg="default",
    bg="default",
    bold=False,
    italic=False,
    underline=False,
    strike=False,
    blink=False,
    reverse=False,
):
    return style.Cell(char, fg, bg, bold, italic, underline, strike, blink, reverse)


def test_runs_group_consecutive_same_style():
    row = [_c("R", "red"), _c("E", "red"), _c("D", "red"), _c(" "), _c("G", "green")]
    runs = style.runs(row)  # (x, text, fg, bg, bold, italic, underline, strike, blink)
    assert runs[0] == (0, "RED", (205, 0, 0), style.BG, False, False, False, False, False)
    assert runs[1] == (3, " ", style.FG, style.BG, False, False, False, False, False)
    assert runs[2] == (4, "G", (0, 205, 0), style.BG, False, False, False, False, False)


def test_encode_row_is_rle_with_hex_and_attr_bits():
    row = [_c("R", "red"), _c("E", "red"), _c(" "), _c("x", "blue", italic=True, underline=True)]
    enc = style.encode_row(row)  # runs: [col, text, fg_hex, bg_hex, bold, italic, underline, ...]
    assert len(enc) == 3
    assert enc[0] == [0, "RE", "cd0000", style.hex_rgb(style.BG), 0, 0, 0, 0, 0]
    assert enc[2] == [3, "x", "0000ee", style.hex_rgb(style.BG), 0, 1, 1, 0, 0]


def test_runs_break_on_attributes_and_carry_them():
    row = [
        _c("a"),
        _c("b", italic=True),
        _c("c", underline=True),
        _c("d", strike=True),
        _c("e", blink=True),
    ]
    runs = style.runs(row)
    assert len(runs) == 5  # same color, but each attribute forces a separate run
    assert runs[1] == (1, "b", style.FG, style.BG, False, True, False, False, False)
    assert runs[2] == (2, "c", style.FG, style.BG, False, False, True, False, False)
    assert runs[3] == (3, "d", style.FG, style.BG, False, False, False, True, False)
    assert runs[4] == (4, "e", style.FG, style.BG, False, False, False, False, True)
