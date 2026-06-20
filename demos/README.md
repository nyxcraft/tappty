# tappty demos

Runnable showpieces — single-file apps you run to *see* a feature in action. Each is
**in-process** (an `EngineSource`), so none needs an external program. (For coding-level
examples of how to build on the API, see [`../examples/`](../examples/).)

| Demo | What it shows | Run |
|---|---|---|
| [color_chart.py](color_chart.py) | SGR color + attributes — bold/italic/underline/strike/blink/reverse and a 256-color strip | `python demos/color_chart.py` |
| [matrix_rain.py](matrix_rain.py) | green-phosphor "digital rain" on the dependency-free VT52 backend | `python demos/matrix_rain.py` |
| [mission_control.py](mission_control.py) | the compositor — four live sessions tiled in one window | `python demos/mission_control.py` |

Install the matching extra first:

```sh
pip install 'tappty[gui,ansi]'   # color_chart / mission_control (pygame + pyte)
pip install 'tappty[gui]'        # matrix_rain (pygame only; no color backend needed)
```

Each demo also takes `--snapshot PATH`: instead of opening a window it renders
headless (SDL dummy driver) and writes a PNG. That's exactly how the
[documentation gallery](../docs/GALLERY.md) images are produced —
`gh-pages/screenshots.py` runs these same files with `--snapshot`.

`recordings/` holds short `.cast` sessions of real ANSI programs (`nyancat`, `cbonsai`),
recorded with `tapterm --record` and replayable with **zero dependencies**:

```sh
tapterm --play demos/recordings/nyancat.cast
```
