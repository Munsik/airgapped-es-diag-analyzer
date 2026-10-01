#!/usr/bin/env bash
# Build a standalone executable (esdiag) for servers without Python. Optional.
#
# Only the build machine needs PyInstaller (an internet-connected environment). The result runs without Python.
#
# Important: a Linux binary runs only on the glibc version of the build OS or newer.
#            Build on the same OS as the target server, or an older one (for a RHEL 8 target, build on RHEL 8).
#            A Windows build must be made on Windows (no cross build). On Windows, write the --add-data
#            separator as ';' instead of ':'.
#
#   bash tools/build_binary.sh          # writes dist/esdiag
#   ./dist/esdiag bundle.zip --html report.html
set -euo pipefail
cd "$(dirname "$0")/.."
# Use a build-only virtual environment so the system Python is left alone (PEP 668 environments).
python3 -m venv build/venv
build/venv/bin/python -m pip install --quiet --upgrade pip pyinstaller
# The message catalogs are data files, not modules: they must be added explicitly or the binary cannot print text.
build/venv/bin/python -m PyInstaller --onefile --clean --name esdiag \
  --distpath dist --workpath build/pyinstaller --specpath build \
  --collect-submodules esdiag \
  --add-data "$PWD/esdiag/i18n/ko.txt:esdiag/i18n" \
  --add-data "$PWD/esdiag/i18n/en.txt:esdiag/i18n" \
  analyze.py
echo "wrote dist/esdiag"
echo "Build environment glibc: $(ldd --version 2>/dev/null | head -1 || echo unknown)"
