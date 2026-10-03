#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checks for the Elasticsearch 9.5 baseline (0.14.1): merge policy defaults by version, the columnar, logsdb_columnar and
vectordb_document index modes, and the monitoring plugin deprecation. No external bundle needed (synthetic data).
Every case runs in both languages.

    python3 tests/test_es95.py
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from esdoctor.engine import analyze  # noqa: E402
from esdoctor.i18n import set_lang  # noqa: E402
from esdoctor.model import Severity  # noqa: E402
from esdoctor.settings_kb import default_for  # noqa: E402
from test_logsdb import Bundle, GB, M, w  # noqa: E402

FAILS, N = [], [0]


def check(name, cond, detail=""):
    N[0] += 1
    if not cond:
        FAILS.append(name + (" - " + str(detail) if detail else ""))


def findings(res):
    return dict((f.id, f) for f in res.findings)


def rows_of(f):
    return (f.evidence or {}).get("rows", []) if f else []


class _Ctx(object):
    def __init__(self, version, ds=None, modes=None):
        self.version_tuple = version
        self._ds = ds or {}
        self._modes = modes or {}

    def data_stream_of(self, name):
        return self._ds.get(name)

    def index_mode(self, name):
        return self._modes.get(name)


def unit():
    old, new = _Ctx((9, 4, 4)), _Ctx((9, 5, 3), ds={".ds-logs-a-1": {"name": "logs-a"}})
    check("segments_per_tier 10 before 9.5", default_for("index.merge.policy.segments_per_tier", old) == "10")
    check("segments_per_tier 8 from 9.5", default_for("index.merge.policy.segments_per_tier", new) == "8")
    check("floor_segment 2mb before 9.5", default_for("index.merge.policy.floor_segment", old) == "2mb")
    check("floor_segment 16mb from 9.5", default_for("index.merge.policy.floor_segment", new) == "16mb")
    check("max_merge_at_once 16 from 9.5", default_for("index.merge.policy.max_merge_at_once", new) == "16")
    check("max_merged_segment 100gb for a data stream index",
          default_for("index.merge.policy.max_merged_segment", new, index=".ds-logs-a-1") == "100gb")
    check("max_merged_segment 5gb for a plain index",
          default_for("index.merge.policy.max_merged_segment", new, index="plain") == "5gb")
    check("max_merged_segment 5gb before 8.11",
          default_for("index.merge.policy.max_merged_segment", _Ctx((8, 10, 0), ds={"x": {}}), index="x") == "5gb")
    modes = _Ctx((9, 5, 3), modes={"c": "columnar", "lc": "logsdb_columnar", "l": "logsdb", "s": "standard", "v": "vectordb_document"})
    for idx, want in (("c", "best_compression"), ("lc", "best_compression"), ("l", "best_compression"), ("s", None), ("v", None)):
        check("codec default for mode %s" % idx, default_for("index.codec", modes, index=idx) == want,
              default_for("index.codec", modes, index=idx))


def build(root, version="9.5.3"):
    b = Bundle(version=version)
    b.index("std-big", 200 * GB, M)
    b.index("col-big", 200 * GB, M, mode="columnar")
    b.index(".ds-logs-c-default-2026.10.01-000001", 200 * GB, M, mode="logsdb_columnar")
    b.stream("logs-c-default", [".ds-logs-c-default-2026.10.01-000001"], index_mode="logsdb_columnar")
    b.index(".ds-logs-s-default-2026.10.01-000001", GB, M, mode="standard")
    b.stream("logs-s-default", [".ds-logs-s-default-2026.10.01-000001"], index_mode="standard")
    b.index("vec-auto", GB, M, mode="vectordb_document")
    b.index("vec-custom", GB, M, mode="vectordb_document")
    b.index("std-preload", GB, M)
    b.settings["col-big"]["settings"]["index"]["mapping"] = {"source": {"mode": "columnar_stored"}}
    b.settings["vec-auto"]["settings"]["index"]["store"] = {"preload": ["vex", "veq", "veb", "cenivf"]}
    b.settings["vec-custom"]["settings"]["index"]["store"] = {"preload": ["vex", "vec"]}
    b.settings["std-preload"]["settings"]["index"]["store"] = {"preload": ["nvd", "dvd"]}
    b.settings["std-big"]["settings"]["index"]["merge"] = {"policy": {"segments_per_tier": "10"}}
    b.settings["col-big"]["settings"]["index"]["codec"] = "best_compression"
    b.write(root)
    w(root, "cluster_settings.json", {"persistent": {"xpack": {"monitoring": {"collection": {"enabled": "true"}}}},
                                      "transient": {}, "defaults": {}})


def run_lang(lang, tmp):
    set_lang(lang)
    pre = "[%s] " % lang
    root = os.path.join(tmp, "b95-" + lang)
    build(root)
    res = analyze(root)
    check(pre + "no rule errors", not res.errors, [e["rule"] for e in res.errors])
    f = findings(res)

    d6 = [r[0] for r in rows_of(f.get("DISK-006"))]
    check(pre + "DISK-006 flags the standard index", "std-big" in d6, d6)
    check(pre + "DISK-006 skips columnar and logsdb_columnar", "col-big" not in d6
          and ".ds-logs-c-default-2026.10.01-000001" not in d6, d6)

    d7 = dict((r[0], r[1]) for r in rows_of(f.get("DISK-007")))
    check(pre + "DISK-007 lists columnar_stored", "columnar_stored" in d7.get("col-big", ""), d7)

    i13 = [r[0] for r in rows_of(f.get("IDX-013"))]
    check(pre + "IDX-013 skips logsdb_columnar", "logs-c-default" not in i13, i13)
    check(pre + "IDX-013 still lists a standard logs data stream", "logs-s-default" in i13, i13)

    p8 = [r[0] for r in rows_of(f.get("PERF-008"))]
    check(pre + "PERF-008 skips the vectordb_document default preload", "vec-auto" not in p8, p8)
    check(pre + "PERF-008 lists custom preloads", "vec-custom" in p8 and "std-preload" in p8, p8)

    s6 = dict(((r[0], r[2]), r) for r in rows_of(f.get("SET-006")))
    check(pre + "SET-006: segments_per_tier 10 is a change on 9.5 (default 8)",
          ("index.merge.policy.segments_per_tier", "10") in s6, sorted(s6))
    check(pre + "SET-006: best_compression on a columnar index is the mode default",
          ("index.codec", "best_compression") not in s6, sorted(s6))

    o7 = f.get("OPS-007")
    check(pre + "OPS-007 notes the 9.5 monitoring plugin deprecation", o7 is not None and "10.0" in o7.observed,
          o7 and o7.observed)
    v1 = f.get("VER-001")
    check(pre + "no VER-001 on a 9.5 cluster", v1 is None or v1.severity == Severity.OK, v1 and v1.observed)


def run_old(tmp):
    set_lang("en")
    root = os.path.join(tmp, "b94")
    build(root, version="9.4.4")
    f = findings(analyze(root))
    s6 = dict(((r[0], r[2]), r) for r in rows_of(f.get("SET-006")))
    check("9.4: segments_per_tier 10 is the default", ("index.merge.policy.segments_per_tier", "10") not in s6, sorted(s6))
    o7 = f.get("OPS-007")
    check("9.4: no deprecation note", o7 is not None and "10.0" not in o7.observed, o7 and o7.observed)


def main():
    tmp = tempfile.mkdtemp()
    try:
        unit()
        for lang in ("ko", "en"):
            run_lang(lang, tmp)
        run_old(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        set_lang("ko")
    for f in FAILS:
        print("FAIL " + f)
    print("9.5 baseline checks: %d run, %d failed" % (N[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
