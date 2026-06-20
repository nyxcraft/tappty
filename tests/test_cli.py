"""tapterm CLI: xterm-style arguments and the regular-terminal vs instrument defaults.

The interactive-default tests stub out `_run_mode` (so no real renderer/window runs) and inspect
what main() built: whether keystrokes are raw and which terminal backend was chosen.
"""

import os

import pytest

from tappty import cli

pty_only = pytest.mark.skipif(os.name == "nt", reason="hosts a command on a POSIX pty")
needs_pyte = pytest.mark.skipif(
    not cli._have_pyte(), reason="the real-terminal default needs pyte"
)


@pty_only
def test_e_runs_command_like_dashdash(capsys):
    assert cli.main(["--headless", "-e", "echo", "hi-from-e"]) == 0
    assert "hi-from-e" in capsys.readouterr().out


@pty_only
def test_cwd_runs_in_directory(tmp_path, capsys):
    assert cli.main(["--headless", "-cd", str(tmp_path), "--", "sh", "-c", "pwd"]) == 0
    out = capsys.readouterr().out
    assert str(tmp_path) in out or os.path.realpath(str(tmp_path)) in out


def _capture_build(monkeypatch):
    """Run main() with a stubbed renderer; return the (raw, terminal-class-name) it built."""
    seen = {}

    def fake_run_mode(ap, a, sess, term, mode, title):
        seen["raw"] = a.raw
        seen["term"] = type(term).__name__
        seen["cols"], seen["rows"] = term.cols, term.rows
        seen["exit_when_done"] = a.exit_when_done
        return 0

    monkeypatch.setattr(cli, "_run_mode", fake_run_mode)
    return seen


@pty_only
@needs_pyte
def test_interactive_is_a_real_terminal_by_default(monkeypatch):
    seen = _capture_build(monkeypatch)
    cli.main(["--cui", "--", "true"])
    assert seen["raw"] is True
    assert seen["term"] == "PyteTerminal"  # full-ANSI backend
    assert seen["exit_when_done"] is True  # closes on exit, like xterm


@pty_only
def test_cooked_is_line_oriented_vt52(monkeypatch):
    seen = _capture_build(monkeypatch)
    cli.main(["--cui", "--cooked", "--", "true"])
    assert seen["raw"] is False
    assert seen["term"] == "Terminal"  # the VT52 instrument grid
    assert seen["exit_when_done"] is False  # instrument mode holds the view


@pty_only
def test_hold_keeps_an_interactive_session_open(monkeypatch):
    seen = _capture_build(monkeypatch)
    cli.main(["--cui", "-hold", "--", "true"])
    assert seen["exit_when_done"] is False


@pty_only
def test_geometry_overrides_cols_rows(monkeypatch):
    seen = _capture_build(monkeypatch)
    cli.main(["--cui", "--cooked", "-geometry", "100x30", "--", "true"])
    assert (seen["cols"], seen["rows"]) == (100, 30)


def test_bad_geometry_errors_cleanly(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["-geometry", "not-a-size", "--", "true"])
    assert e.value.code == 2
    assert "COLSxROWS" in capsys.readouterr().err
