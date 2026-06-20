"""Tap a session: watch a program's output, frame changes, and events as they happen.

A `Session` exposes three observe taps, and every consumer -- a renderer, a socket logger, an
automated driver -- attaches the same way:

    on_stream(cb(chunk))      raw program output, pre-render
    on_frame(cb())            the screen changed (redraw hint)
    on_event(cb(name, info))  WAIT / BELL / CLOSED / DRIVER / ERROR

Here we host a tiny in-process program and print what each tap sees. Runnable with just the
core install (no extras, no display):  python examples/observe_tap.py
"""
from tappty import Session, Terminal
from tappty.source import EngineSource


def program(emit, readline):
    """The hosted 'program': prints two lines, then returns (which ends the session)."""
    emit("hello from the program\r\n")
    emit("second line\r\n")


def main():
    sess = Session(Terminal(80, 24), source=EngineSource(program))

    frames = []
    sess.on_stream(lambda chunk: print(f"  stream  {chunk!r}"))
    sess.on_frame(lambda: frames.append(1))
    sess.on_event(lambda name, info: print(f"  event   {name} {info}"))

    sess.run_blocking()  # host the program to completion on this thread

    print(f"\n{len(frames)} frame notifications; "
          f"row 0 of the screen is now {sess.term.rows_text()[0].strip()!r}")


if __name__ == "__main__":
    main()
