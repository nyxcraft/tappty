#!/usr/bin/env bash
# Build BOTH PyPI distributions this repo publishes, into dist/, then validate them.
#
#   tappty   the real package -- the library + the `tapterm` command   (root pyproject.toml)
#   tapterm  a thin alias that ships no code and just depends on tappty (packaging/tapterm/)
#
# `python -m build` builds one project per pyproject.toml, so the shim is built separately
# into the same dist/. After this passes, publish everything with:  twine upload dist/*
set -euo pipefail
cd "$(dirname "$0")/.."                          # repo root

# tappty's version is single-sourced from src/tappty/__init__.py (the root pyproject reads it
# dynamically). The tapterm alias has its own pyproject, so guard it against drift: its version
# and its `tappty>=` pin must both match.
VER=$(python3 -c "import re,pathlib; print(re.search(r'__version__ = \"([^\"]+)\"', pathlib.Path('src/tappty/__init__.py').read_text()).group(1))")
grep -q "version = \"$VER\"" packaging/tapterm/pyproject.toml \
  || { echo "ERROR: tapterm alias version != tappty $VER" >&2; exit 1; }
grep -q "tappty>=$VER" packaging/tapterm/pyproject.toml \
  || { echo "ERROR: tapterm alias 'tappty>=' pin != $VER" >&2; exit 1; }
echo "version $VER consistent across tappty + the tapterm alias"

rm -rf dist build ./*.egg-info src/*.egg-info
python3 -m build                                 # dist/tappty-*.{whl,tar.gz}
python3 -m build packaging/tapterm --outdir dist # dist/tapterm-*.{whl,tar.gz}
python3 -m twine check dist/*

echo
echo "Built distributions:"
ls -1 dist/
