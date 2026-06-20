# tappty examples

Runnable, self-contained demos — each is a single file you can read top to bottom
and run after a `pip install`. They're all **in-process** (an `EngineSource`), so
none of them needs an external program.

| Demo | What it shows | Run |
|---|---|---|
| [color_chart.py](color_chart.py) | SGR color + attributes — bold/italic/underline/strike/blink/reverse and a 256-color strip | `python examples/color_chart.py` |
| [matrix_rain.py](matrix_rain.py) | green-phosphor "digital rain" on the dependency-free VT52 backend | `python examples/matrix_rain.py` |
| [mission_control.py](mission_control.py) | the compositor — four live sessions tiled in one window | `python examples/mission_control.py` |

Install the matching extra first:

```sh
pip install 'tappty[gui,ansi]'   # color_chart / mission_control (pygame + pyte)
pip install 'tappty[gui]'        # matrix_rain (pygame only; no color backend needed)
```

Each demo also takes `--snapshot PATH`: instead of opening a window it renders
headless (SDL dummy driver) and writes a PNG. That's exactly how the
[documentation gallery](../docs/gallery.md) images are produced —
`gh-pages/screenshots.py` runs these same files with `--snapshot`.

`recordings/` holds short `.cast` sessions of real ANSI programs (`nyancat`, `cbonsai`),
recorded with `tapterm --record` and replayable with **zero dependencies**:

```sh
tapterm --play examples/recordings/nyancat.cast
```
