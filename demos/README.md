# tappty demos

Runnable showpieces — single-file apps you run to *see* a feature in action. Most are
**in-process** (an `EngineSource`), so they need no external program; `drive_vim` hosts a real
`vim` to show off observe-and-control. (For coding-level examples of how to build on the API,
see [`../examples/`](../examples/).)

| Demo | What it shows | Run |
|---|---|---|
| [color_chart.py](color_chart.py) | SGR color + attributes — bold/italic/underline/strike/blink/reverse and a 256-color strip | `python demos/color_chart.py` |
| [matrix_rain.py](matrix_rain.py) | green-phosphor "digital rain" on the dependency-free VT52 backend | `python demos/matrix_rain.py` |
| [mission_control.py](mission_control.py) | the compositor — four live sessions tiled in one window | `python demos/mission_control.py` |
| [drive_vim.py](drive_vim.py) | a program driving a real terminal app — an autopilot types into live `vim` over the control tap | `python demos/drive_vim.py` |

Install the matching extra first:

```sh
pip install 'tappty[gui,ansi]'   # color_chart / mission_control / drive_vim (pygame + pyte)
pip install 'tappty[gui]'        # matrix_rain (pygame only; no color backend needed)
```

`drive_vim` also needs `vim` (or `vi`) on your PATH. To watch a closed loop that **reads the
screen and decides what to type**, see [`../examples/watch_and_drive.py`](../examples/watch_and_drive.py).

Each demo also takes `--snapshot PATH`: instead of opening a window it renders
headless (SDL dummy driver) and writes a PNG. That's exactly how the
[documentation gallery](../docs/GALLERY.md) images are produced —
`gh-pages/screenshots.py` runs these same files with `--snapshot`.

`recordings/` holds short `.cast` sessions — real ANSI programs (`nyancat`, `cbonsai`) and the
autopilot-driven `vim` (`drive_vim.cast`) — recorded with `tapterm --record` and replayable with
**zero dependencies**:

```sh
tapterm --play demos/recordings/nyancat.cast
tapterm --play demos/recordings/drive_vim.cast
```
