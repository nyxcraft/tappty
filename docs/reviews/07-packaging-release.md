# Packaging and release review

## Scope

Reviewed `pyproject.toml`, extras, public imports, entry points, README install/test
guidance, CI shape, and release claims.

No high-severity findings. The package uses a standard `src` layout, has a console script,
and optional dependencies are imported lazily enough that `import tappty` works without
pygame, pyte, or pywinpty installed.

## Findings

### Medium: GUI extra and CI-tested GUI dependency differ

Evidence:

- `pyproject.toml` declares `gui = ["pygame"]` (`pyproject.toml:25`).
- CI installs `pygame-ce` directly instead of the declared GUI extra
  (`.github/workflows/ci.yml:36`).
- README tells users to install `tappty[gui]` (`README.md:18`).

Impact:

The dependency users get from the published extra is not exactly what CI verifies. If
`pygame` and `pygame-ce` differ by Python version, wheel availability, or behavior, release
confidence is weaker than the green CI run suggests.

Recommendation:

Choose one dependency story. Either declare `gui = ["pygame-ce"]` and test `.[gui]`, or keep
`pygame` and have CI install `.[dev,ansi,gui]`. If both are supported, document and test both
explicitly.

### Medium: README test instructions describe a partial test run

Evidence:

README's test block installs only `.[dev]` before `pytest` (`README.md:92`). Without optional
deps, `test_pyte_terminal` and `test_gui_smoke` skip.

Impact:

Contributors can unknowingly miss the ANSI and GUI draw paths.

Recommendation:

Document quick and full commands separately:

```sh
pip install -e '.[dev]'
pytest

pip install -e '.[dev,ansi,gui]'
pytest
```

Adjust the full command to match the final `gui` dependency choice.

### Low: platform classifiers are conservative but narrower than docs

Evidence:

`pyproject.toml` lists only `Operating System :: POSIX` (`pyproject.toml:19`), while README
and Windows docs describe cross-platform pieces and a provisional Windows path.

Impact:

This is probably correct until Windows is verified. It does mean package metadata
understates the cross-platform core.

Recommendation:

Keep POSIX-only until a Windows job passes. After that, add appropriate Windows classifiers
and update README wording from provisional to verified.

### Low: release URLs assume the GitHub remote exists

Evidence:

`pyproject.toml` points Homepage and Source at `https://github.com/nkissebe/tappty`
(`pyproject.toml:33`), while handoff docs still list pushing the remote/CI as future work.

Impact:

If published before the remote exists, package metadata will send users to a dead link.

Recommendation:

Create/push the remote before publishing, or remove URLs until the repository exists.

## Positive notes

- `PYTHONPATH=src python3 -c "import tappty; print(tappty.__version__)"` succeeded without
  optional dependencies in the system environment.
- The console script is declared correctly (`pyproject.toml:30`).
- The CI matrix covers Python 3.9 through 3.13 on Ubuntu (`.github/workflows/ci.yml:23`).
