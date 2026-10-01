# -*- coding: utf-8 -*-
"""Pre-run environment check (--check-env).

Air-gapped servers often have a minimal Python, a build without zlib, or a console that cannot print Hangul.
Reports what would block the analysis before it starts. Makes no network calls.
"""

import os
import platform
import sys
import tempfile
from .i18n import T

# All standard modules the analyzer imports
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
        add(T("envcheck.run.01"), True, T("envcheck.run.02") % ver)
    elif v >= (3, 6):
        add(T("envcheck.run.01"), True, T("envcheck.run.03") % ver, fatal=False)
    else:
        add(T("envcheck.run.01"), False, T("envcheck.run.04") % ver)

    missing = []
    for m in STDLIB:
        try:
            __import__(m)
        except Exception:
            missing.append(m)
    add(T("envcheck.run.05"), not missing, T("envcheck.run.06") % ", ".join(missing) if missing else T("envcheck.run.07") % len(STDLIB))

    # unzipping needs zlib (some minimal Python builds lack it)
    try:
        import zlib  # noqa: F401  (existence check only)
        add(T("envcheck.run.08"), True, T("envcheck.run.09"))
    except Exception:
        add(T("envcheck.run.08"), False, T("envcheck.run.10"),
            fatal=False)

    enc = (getattr(sys.stdout, "encoding", None) or "").lower()
    try:
        (T("sev.critical") + " \u25a0 \u2500 \u2191 \u2193").encode(enc or "ascii")
        add(T("envcheck.run.12"), True, enc or "-")
    except Exception:
        add(T("envcheck.run.12"), False, T("envcheck.run.13") % (enc or "unknown"), fatal=False)

    target = out_dir or tempfile.gettempdir()
    try:
        fd, p = tempfile.mkstemp(dir=target if os.path.isdir(target) else None)
        os.close(fd)
        os.remove(p)
        add(T("envcheck.run.14"), True, target)
    except Exception as exc:
        add(T("envcheck.run.14"), False, T("envcheck.run.dir_err") % (target, exc))

    add(T("envcheck.run.15"), True, T("envcheck.run.16"))

    print(T("envcheck.run.17"))
    print("  %s / %s %s" % (platform.python_implementation(), platform.system(), platform.release()))
    print(T("envcheck.run.18") % sys.executable)
    print("")
    for status, name, detail in rows:
        print("  [%s] %-18s %s" % (status, name, detail))
    print("")
    print(T("envcheck.run.19") % (T("envcheck.run.20") if ok else T("envcheck.run.21")))
    return 0 if ok else 1
