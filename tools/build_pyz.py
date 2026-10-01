#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the single-file distribution (esdiag.pyz) with the standard library zipapp only.

    python3 tools/build_pyz.py            # writes dist/esdiag.pyz
    python3 esdiag.pyz bundle.zip --html report.html

A .pyz is a zip file that the Python interpreter runs. An air-gapped site only needs this one file.
The message catalogs (esdiag/i18n/*.txt) are copied in with the package and read with pkgutil.
"""

import os
import shutil
import sys
import tempfile
import zipapp

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
import esdiag  # noqa: E402

MAIN = '''# -*- coding: utf-8 -*-
import sys
import analyze
sys.exit(analyze.main())
'''


def main():
    dist = os.path.join(ROOT, "dist")
    os.makedirs(dist, exist_ok=True)
    stage = tempfile.mkdtemp()
    try:
        shutil.copytree(os.path.join(ROOT, "esdiag"), os.path.join(stage, "esdiag"),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy(os.path.join(ROOT, "analyze.py"), stage)
        with open(os.path.join(stage, "__main__.py"), "w", encoding="utf-8") as fh:
            fh.write(MAIN)
        target = os.path.join(dist, "esdiag.pyz")
        zipapp.create_archive(stage, target, interpreter="/usr/bin/env python3", compressed=True)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    print("wrote %s (esdiag %s, %.0f KB)" % (target, esdiag.__version__, os.path.getsize(target) / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
