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

rm -rf dist build ./*.egg-info src/*.egg-info
python3 -m build                                 # dist/tappty-*.{whl,tar.gz}
python3 -m build packaging/tapterm --outdir dist # dist/tapterm-*.{whl,tar.gz}
python3 -m twine check dist/*

echo
echo "Built distributions:"
ls -1 dist/
