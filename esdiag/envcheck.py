# -*- coding: utf-8 -*-
"""실행 환경 사전 점검(--check-env).

폐쇄망 서버는 최소 설치 Python 이거나 zlib 이 빠진 빌드, 한글 출력이 안 되는 콘솔 등이 흔하다.
분석 전에 막히는 지점을 미리 알려 준다. 외부 통신 없음.
"""

import os
import platform
import sys
import tempfile

# 분석기가 import 하는 표준 모듈 전체
STDLIB = ["argparse", "collections", "datetime", "fnmatch", "html", "io", "json", "math", "os", "re",
          "sys", "tempfile", "traceback", "zipfile"]


def run(out_dir=None):
    rows, ok = [], True

    def add(name, passed, detail, fatal=True):
        nonlocal ok
        if not passed and fatal:
            ok = False
        rows.append(("OK  " if passed else ("FAIL" if fatal else "WARN"), name, detail))

    v = sys.version_info
    ver = "%d.%d.%d" % v[:3]
    if v >= (3, 8):
        add("Python 버전", True, "%s (실행 검증 범위)" % ver)
    elif v >= (3, 6):
        add("Python 버전", True, "%s (동작 가능하나 실행 미검증 — 3.8 이상 권장)" % ver, fatal=False)
    else:
        add("Python 버전", False, "%s — Python 3.6 이상이 필요합니다" % ver)

    missing = []
    for m in STDLIB:
        try:
            __import__(m)
        except Exception:
            missing.append(m)
    add("표준 라이브러리", not missing, "누락: %s" % ", ".join(missing) if missing else "%d개 모두 사용 가능" % len(STDLIB))

    # zip 압축 해제에는 zlib 이 필요(최소 빌드 Python 에서 빠지는 경우가 있음)
    try:
        import zlib  # noqa: F401  (존재 여부 확인용)
        add("zlib (zip 해제)", True, "사용 가능")
    except Exception:
        add("zlib (zip 해제)", False, "없음 — zip 번들을 직접 읽을 수 없습니다. 번들을 압축 해제한 디렉터리를 입력하십시오.",
            fatal=False)

    enc = (getattr(sys.stdout, "encoding", None) or "").lower()
    try:
        "치명 ■ ─ ↑ ↓ —".encode(enc or "ascii")
        add("콘솔 인코딩", True, enc or "-")
    except Exception:
        add("콘솔 인코딩", False, "%s — 콘솔에서 한글·기호가 깨질 수 있습니다. PYTHONIOENCODING=utf-8 을 지정하거나 "
                                  "--html/--md 파일 출력을 사용하십시오(파일은 항상 UTF-8)." % (enc or "unknown"), fatal=False)

    target = out_dir or tempfile.gettempdir()
    try:
        fd, p = tempfile.mkstemp(dir=target if os.path.isdir(target) else None)
        os.close(fd)
        os.remove(p)
        add("출력 경로 쓰기", True, target)
    except Exception as exc:
        add("출력 경로 쓰기", False, "%s — %s" % (target, exc))

    add("외부 네트워크", True, "사용하지 않음(점검 불필요)")

    print("esdiag 실행 환경 점검")
    print("  %s / %s %s" % (platform.python_implementation(), platform.system(), platform.release()))
    print("  실행 파일: %s" % sys.executable)
    print("")
    for status, name, detail in rows:
        print("  [%s] %-18s %s" % (status, name, detail))
    print("")
    print("  결과: %s" % ("실행 가능" if ok else "실행 불가 — FAIL 항목을 먼저 해결하십시오"))
    return 0 if ok else 1
