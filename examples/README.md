# tappty examples

Coding-level examples — short, commented programs that show **how to build on the tappty API**.
For runnable showpieces you just watch (color, digital rain, the compositor), see
[`../demos/`](../demos/).

All of these are in-process and headless — no GUI, no external program — so they run with just
the core install (`pip install tappty`):

| Example | Shows |
|---|---|
| [observe_tap.py](observe_tap.py) | the observe contract — `on_stream` / `on_frame` / `on_event` |
| [custom_source.py](custom_source.py) | writing your own `Source` (the start / send_input / stop contract) |
| [bus_capture.py](bus_capture.py) | driving a session over the bus — send a command, capture its output |
| [watch_and_drive.py](watch_and_drive.py) | a closed loop: watch the output, decide, and type back (a bot that binary-searches a guessing game) |

```sh
python examples/observe_tap.py
python examples/custom_source.py
python examples/bus_capture.py
python examples/watch_and_drive.py
```

For an open-loop counterpart you can *watch* (an autopilot typing a fixed script into real `vim`),
see [`../demos/drive_vim.py`](../demos/drive_vim.py).

More worked examples (replay to a PNG, watch headlessly, the full bus round-trip) are in the
[programming reference](../docs/REFERENCE.md).
