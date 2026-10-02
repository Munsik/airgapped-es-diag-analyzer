#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checks for the fixes from the official documentation audit (0.14.0). No external bundle needed (synthetic data).

Covers JVM-002 (compressed oops flag first, 26/30GB only without the flag), CLU-007 (10 data nodes), DISK-006 (time_series
included), IDX-013 (cluster.logsdb.enabled), CLU-015 (closed and partially mounted indices), DISK-007 (mapping _source
disabled), SHD-010 (Warning only past the heap), MAP-006 (nested default by index version), the max_headroom conditions,
SYS-001/003 in development mode, and the context-dependent settings defaults. Both languages.

    python3 tests/test_doc_audit.py
"""
import copy
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from esdiag.context import Context  # noqa: E402
from esdiag.engine import analyze  # noqa: E402
from esdiag.i18n import set_lang  # noqa: E402
from esdiag.loader import Bundle as Loader  # noqa: E402
from esdiag.model import Severity  # noqa: E402
from esdiag.report import html as html_report  # noqa: E402
from esdiag.report import text as text_report  # noqa: E402
from esdiag.settings_kb import compare, default_for  # noqa: E402
from esdiag.thresholds import merge  # noqa: E402
from test_logsdb import Bundle, GB, M, w  # noqa: E402

FAILS, N = [], [0]


def check(name, cond, detail=""):
    N[0] += 1
    if not cond:
        FAILS.append(name + (" - " + str(detail) if detail else ""))


def load(root, rel):
    with open(os.path.join(root, rel)) as fh:
        return json.load(fh)


def findings(res):
    return dict((f.id, f) for f in res.findings)


def nodes_edit(root, fn_info=None, fn_stats=None):
    ni, ns = load(root, "nodes.json"), load(root, "nodes_stats.json")
    for nid in ni["nodes"]:
        if fn_info:
            fn_info(ni["nodes"][nid])
        if fn_stats:
            fn_stats(ns["nodes"][nid])
    w(root, "nodes.json", ni)
    w(root, "nodes_stats.json", ns)


def clone_data_nodes(root, total):
    ni, ns = load(root, "nodes.json"), load(root, "nodes_stats.json")
    src = [k for k, v in ni["nodes"].items() if v["name"] == "hot-1"][0]
    k = 0
    while len([v for v in ni["nodes"].values() if any(r.startswith("data") for r in v["roles"])]) < total:
        nid = "clone%02dXXXXXXXXXXXXXXXX" % k
        ni["nodes"][nid] = dict(copy.deepcopy(ni["nodes"][src]), name="hot-c%d" % k)
        ns["nodes"][nid] = dict(copy.deepcopy(ns["nodes"][src]), name="hot-c%d" % k)
        k += 1
    w(root, "nodes.json", ni)
    w(root, "nodes_stats.json", ns)


def base(root, version="9.4.4"):
    b = Bundle(version=version)
    b.index("app-std", 60 * GB, M, node="hot-1")
    b.index("metrics-tsds", 60 * GB, M, mode="time_series", node="hot-1")
    b.index("logs-x-default-ldb", 60 * GB, M, mode="logsdb", node="hot-1")
    b.index("closed-1", GB, M, pri=3, node="hot-1")
    b.index("partial-frozen-1", GB, M, partial=True, node="frozen-1")
    b.index("new-nested", GB, M, node="hot-1")
    b.index("old-nested", GB, M, node="hot-1")
    b.index("synth", GB, M, node="hot-1")
    b.settings["new-nested"]["settings"]["index"]["version"] = {"created": "9050000"}
    b.settings["old-nested"]["settings"]["index"]["version"] = {"created": "8520000"}
    b.settings["synth"]["settings"]["index"]["mapping"] = {"source": {"mode": "synthetic"}}
    b.stream("logs-app-default", ["app-std"])
    b.write(root)
    w(root, "cluster_stats.json", {"indices": {"count": 8, "mappings": {"total_deduplicated_mapping_size_in_bytes": 10 ** 6}}})
    ns = load(root, "nodes_stats.json")
    for st in ns["nodes"].values():
        st.setdefault("os", {})["mem"] = {"total_in_bytes": 16 * GB}
    w(root, "nodes_stats.json", ns)
    nested = lambda n: dict(("n%02d" % i, {"type": "nested", "properties": {"a": {"type": "keyword"}}}) for i in range(n))
    w(root, "mapping.json", {
        "app-std": {"mappings": {"_source": {"enabled": False}, "properties": {"f": {"type": "keyword"}}}},
        "new-nested": {"mappings": {"properties": nested(85)}},
        "old-nested": {"mappings": {"properties": nested(45)}}})
    w(root, "cat/cat_indices.txt",
      "health status index            uuid pri rep docs.count\n"
      "green  open   app-std          u1     1   1       1000\n"
      "       close  closed-1         u2     3   1           \n")
    w(root, "cluster_health.json", {"cluster_name": "c1", "status": "green", "number_of_nodes": 3,
                                    "number_of_data_nodes": 3, "active_primary_shards": 10, "active_shards": 20,
                                    "unassigned_shards": 0})
    return b


def run_lang(lang, tmp):
    set_lang(lang)
    pre = "[%s] " % lang

    # ---- main bundle
    root = os.path.join(tmp, "a-" + lang)
    base(root)
    hot1 = None

    def fi(n):
        if n["name"] == "hot-1":
            n["jvm"]["using_compressed_ordinary_object_pointers"] = "false"
        elif n["name"] == "warm-1":
            n["jvm"]["mem"]["heap_max_in_bytes"] = 28 * GB
        elif n["name"] == "frozen-1":
            n["jvm"]["mem"]["heap_max_in_bytes"] = 31 * GB
            n["jvm"]["using_compressed_ordinary_object_pointers"] = "true"
    nodes_edit(root, fi, lambda s: s["jvm"]["mem"].update(heap_max_in_bytes={"warm-1": 28 * GB, "frozen-1": 31 * GB}.get(
        s["name"], s["jvm"]["mem"]["heap_max_in_bytes"])))
    ni = load(root, "nodes.json")
    for n in ni["nodes"].values():
        if n["name"] == "warm-1":
            n["jvm"].pop("using_compressed_ordinary_object_pointers", None)
    w(root, "nodes.json", ni)
    w(root, "cluster_settings.json", {"persistent": {"cluster": {"logsdb": {"enabled": "false"}}},
                                      "transient": {}})
    res = analyze(root)
    check(pre + "no rule errors", not res.errors, [e["rule"] + ": " + e["error"].strip().splitlines()[-1] for e in res.errors])
    f = findings(res)

    j2 = f.get("JVM-002")
    check(pre + "JVM-002 warning from the oops flag", j2 is not None and j2.severity == Severity.WARNING)
    check(pre + "JVM-002 names hot-1 (flag false) and warm-1 (no flag, 28GB)", j2 is not None and
          "hot-1" in j2.observed and "warm-1" in j2.observed, j2 and j2.observed)
    check(pre + "JVM-002 skips frozen-1 (31GB but flag true)", j2 is not None and "frozen-1" not in j2.observed)

    d6 = f.get("DISK-006")
    names = [r[0] for r in (d6.evidence["rows"] if d6 else [])]
    check(pre + "DISK-006 includes time_series", "metrics-tsds" in names, names)
    check(pre + "DISK-006 skips logsdb", "logs-x-default-ldb" not in names, names)

    d7 = f.get("DISK-007")
    check(pre + "DISK-007 warning from the mapping _source.enabled false", d7 is not None and d7.severity == Severity.WARNING
          and d7.evidence["rows"][0][0] == "app-std", d7 and d7.evidence["rows"])

    m6 = f.get("MAP-006")
    rows6 = dict((r[0], r[2]) for r in (m6.evidence["rows"] if m6 else []))
    check(pre + "MAP-006 uses 100 for a 9.3+ index and 50 for an older one",
          rows6.get("new-nested") == 100 and rows6.get("old-nested") == 50, rows6)

    # ---- CLU-007 at 10 data nodes
    for total, expect in ((9, False), (10, True)):
        r = os.path.join(tmp, "dm%d-%s" % (total, lang))
        base(r)
        clone_data_nodes(r, total)
        nodes_edit(r, lambda n: n.update(roles=[x for x in n["roles"] if x != "master"] if not n["name"].startswith("hot-c") else n["roles"]))
        nodes_edit(r, lambda n: n.update(roles=n["roles"] + ["master"]) if n["name"] in ("hot-1", "warm-1", "frozen-1") else None)
        got = "CLU-007" in findings(analyze(r))
        check(pre + "CLU-007 with %d data nodes: %s" % (total, expect), got == expect)

    try:
        text_report.console(res) + text_report.markdown(res) + html_report.render(res)
        check(pre + "reports render", True)
    except Exception as exc:  # noqa: BLE001
        check(pre + "reports render", False, repr(exc))


def run_variants(tmp):
    set_lang("en")
    root = os.path.join(tmp, "v")
    base(root)
    f = findings(analyze(root))
    i13 = f.get("IDX-013")
    check("IDX-013 raised for the standard logs stream", i13 is not None)
    w(root, "cluster_settings.json", {"persistent": {"cluster.logsdb.enabled": "false"}, "transient": {}})
    i13 = findings(analyze(root)).get("IDX-013")
    check("IDX-013 shows cluster.logsdb.enabled", i13 is not None and "cluster.logsdb.enabled = false" in i13.observed,
          i13 and i13.observed)

    # CLU-015: 20 active shards; closed-1 (3 x 2 = 6) and the partial mount (1) are not counted, so 13 against 2 x limit
    w(root, "cluster_settings.json", {"persistent": {"cluster.max_shards_per_node": "7"}, "transient": {}})
    c15 = findings(analyze(root)).get("CLU-015")
    check("CLU-015 counts open, non-frozen shards only", c15 is not None and c15.observed.startswith("13"), c15 and c15.observed)

    # DISK-007 Info for synthetic only
    m = load(root, "mapping.json")
    m["app-std"]["mappings"].pop("_source")
    w(root, "mapping.json", m)
    d7 = findings(analyze(root)).get("DISK-007")
    check("DISK-007 Info for synthetic _source", d7 is not None and d7.severity == Severity.INFO
          and [r[0] for r in d7.evidence["rows"]] == ["synth"], d7 and (d7.severity, d7.evidence["rows"]))

    # SHD-010: between 50% and 100% of the heap → Info, past the heap → Warning
    for over, sev in ((4 * GB, Severity.INFO), (9 * GB, Severity.WARNING)):
        nodes_edit(root, fn_stats=lambda s: s.setdefault("indices", {}).update(mappings={"total_estimated_overhead_in_bytes": over}))
        s10 = findings(analyze(root)).get("SHD-010")
        check("SHD-010 %s" % sev, s10 is not None and s10.severity == sev, s10 and s10.severity)

    # max_headroom: 4TB disk, defaults report 150GB. Not set → 96.3%; watermark set explicitly → 90%; 8.4 → 90%
    def ctx_for(settings, version="9.4.4"):
        r = os.path.join(tmp, "wm")
        if os.path.exists(r):
            shutil.rmtree(r)
        base(r, version=version)
        w(r, "cluster_settings.json", settings)
        w(r, "cluster_settings_defaults.json", {"defaults": {
            "cluster.routing.allocation.disk.watermark.high.max_headroom": "150gb",
            "cluster.routing.allocation.disk.watermark.high": "90%"}})
        return Context(Loader(r), merge({}))
    tb = 4096 * GB
    v = ctx_for({"persistent": {}, "transient": {}}).watermark_used_pct("high", tb)
    check("headroom applies when the watermark is not set", v is not None and abs(v - (1 - 150.0 / 4096) * 100) < 0.01, v)
    v = ctx_for({"persistent": {"cluster.routing.allocation.disk.watermark.high": "90%"}, "transient": {}}).watermark_used_pct("high", tb)
    check("headroom ignored when the watermark is set explicitly", v is not None and abs(v - 90.0) < 0.01, v)
    v = ctx_for({"persistent": {}, "transient": {}}, version="8.4.3").watermark_used_pct("high", tb)
    check("headroom ignored before 8.5", v is not None and abs(v - 90.0) < 0.01, v)
    v = ctx_for({"persistent": {"cluster.routing.allocation.disk.watermark.high": "90%",
                                "cluster.routing.allocation.disk.watermark.high.max_headroom": "100gb"},
                 "transient": {}}).watermark_used_pct("high", tb)
    check("explicit headroom still applies", v is not None and abs(v - (1 - 100.0 / 4096) * 100) < 0.01, v)

    # SYS in development mode: Critical drops to Warning
    r = os.path.join(tmp, "dev")
    base(r)
    nodes_edit(r, lambda n: n.update(transport_address="127.0.0.1:9300"))
    w(r, "syscalls/proc-limit.txt", "Limit                     Soft Limit           Hard Limit           Units     \n"
                                    "Max processes             1024                 1024                 processes \n"
                                    "Max open files            4096                 4096                 files     \n")
    w(r, "syscalls/sysctl.txt", "vm.max_map_count = 65530\n")
    f = findings(analyze(r))
    check("dev mode: SYS-001 Warning", f.get("SYS-001") is not None and f["SYS-001"].severity == Severity.WARNING,
          f.get("SYS-001") and f["SYS-001"].severity)
    check("dev mode: SYS-003 Warning", f.get("SYS-003") is not None and f["SYS-003"].severity == Severity.WARNING,
          f.get("SYS-003") and f["SYS-003"].severity)

    # settings defaults that depend on the context
    ctx = Context(Loader(root), merge({}))
    hot = [n for n in ctx.nodes if n.name == "hot-1"][0]
    hot.info.setdefault("os", {})["allocated_processors"] = 16
    check("write queue default 12000 on 9.2+ with 16 processors",
          default_for("thread_pool.write.queue_size", ctx, node=hot) == "12000")
    check("12000 is not reported as a change",
          compare("thread_pool.write.queue_size", "12000", default=default_for("thread_pool.write.queue_size", ctx, node=hot))[0] is False)
    check("nested default by index version",
          default_for("index.mapping.nested_fields.limit", ctx, index="new-nested") == "100"
          and default_for("index.mapping.nested_fields.limit", ctx, index="old-nested") == "50")
    check("breaker total default 95%", default_for("indices.breaker.total.limit", ctx) == "95%")
    hot.info.setdefault("settings", {})["indices.breaker.total.use_real_memory"] = "false"
    check("breaker total default 70% without real memory", default_for("indices.breaker.total.limit", ctx) == "70%")
    fz = [n for n in ctx.nodes if n.name == "frozen-1"][0]
    check("recovery default on a dedicated frozen node with 16GB", default_for("indices.recovery.max_bytes_per_sec", ctx, node=fz) == "90mb")
    check("recovery default on a hot node", default_for("indices.recovery.max_bytes_per_sec", ctx, node=hot) == "40mb")
    check("transport.compress is static", compare("transport.compress", "true")[2]["kind"] == "static")
    check("source-based default is labeled", compare("search.low_level_cancellation", "false")[4] == "Elasticsearch source")


def main():
    tmp = tempfile.mkdtemp()
    try:
        for lang in ("ko", "en"):
            run_lang(lang, tmp)
        run_variants(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        set_lang("ko")
    for f in FAILS:
        print("FAIL " + f)
    print("doc audit checks: %d run, %d failed" % (N[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
