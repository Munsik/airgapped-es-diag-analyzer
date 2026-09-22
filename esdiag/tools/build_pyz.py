#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""단일 파일 배포본(esdiag.pyz) 생성. 표준 라이브러리 zipapp 만 사용한다.

    python3 tools/build_pyz.py            # dist/esdiag.pyz 생성
    python3 esdiag.pyz 번들.zip --html report.html

.pyz 는 Python 인터프리터로 실행하는 zip 파일이다. 폐쇄망에는 이 파일 하나만 반입하면 된다.
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
    print("생성: %s (esdiag %s, %.0f KB)" % (target, esdiag.__version__, os.path.getsize(target) / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
