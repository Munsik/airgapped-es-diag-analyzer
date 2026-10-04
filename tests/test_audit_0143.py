#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checks for the fixes from the zero-base logic audit (0.14.3). No external bundle needed (synthetic data).

Covers transient over persistent settings, failure store write and lifecycle handling, API error bodies treated as missing, the comparison base (a later baseline is refused),
restart-aware deltas (DIF-005, DIF-006, DIF-007), DIF-013 gating the other trend rules, DIF-001 with an unknown status,
DIF-008 on used bytes and tier membership, DIF-009 minimum volume, DIF-012 with skipped rules, the time-based merge policy
by the @timestamp mapping, the gz log tail, rolled JSON logs, the bottleneck scope of a coordinating-only node, OVS-001 shrink
factors, MAP-004 on rolled-over indices and container detection for OS-001. Both languages where text is involved.

    python3 tests/test_audit_0143.py
"""
import copy
import gzip
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from esdoctor import diff as D  # noqa: E402
from esdoctor.bottleneck import _tier_scope  # noqa: E402
from esdoctor.context import Context  # noqa: E402
from esdoctor.engine import analyze  # noqa: E402
from esdoctor.i18n import set_lang  # noqa: E402
from esdoctor.loader import Bundle as Loader  # noqa: E402
from esdoctor.mapsum import summarize  # noqa: E402
from esdoctor.model import Finding, Severity  # noqa: E402
from esdoctor.rules.runtime import _es_log_files  # noqa: E402
from esdoctor.settings_kb import default_for  # noqa: E402
from esdoctor.thresholds import merge  # noqa: E402
from test_logsdb import Bundle, GB, M, w  # noqa: E402

FAILS, N = [], [0]
T = merge({})


def check(name, cond, detail=""):
    N[0] += 1
    if not cond:
        FAILS.append(name + (" - " + str(detail) if detail else ""))


def ids(fs):
    return dict((f.id, f) for f in fs)


def ctx_of(root):
    return Context(Loader(root), merge({}))


def build(root, collected="2026-10-01T00:00:00Z", fn=None, uuid="u-1"):
    b = Bundle(version="9.4.4")
    b.index("plain", GB, M)
    b.write(root)
    w(root, "manifest.json", {"diagVersion": "9.4.1", "collectionDate": collected,
                              "diagnosticInputs": "DiagnosticInputs: {, diagType='api', mode='full'}"})
    w(root, "version.json", {"cluster_name": "c1", "cluster_uuid": uuid, "version": {"number": "9.4.4"}})
    if fn:
        ns = json.load(open(os.path.join(root, "nodes_stats.json")))
        for i, nid in enumerate(sorted(ns["nodes"])):
            fn(i, ns["nodes"][nid])
        w(root, "nodes_stats.json", ns)


def settings_and_loader(tmp):
    root = os.path.join(tmp, "set")
    build(root)
    w(root, "cluster_settings.json", {"persistent": {"cluster": {"routing": {"allocation": {"enable": "none"}}}},
                                      "transient": {"cluster": {"routing": {"allocation": {"enable": "all"}}}},
                                      "defaults": {}})
    w(root, "licenses.json", {"error": {"type": "security_exception", "reason": "denied"}, "status": 403})
    c = ctx_of(root)
    check("transient wins over persistent", c.setting("cluster.routing.allocation.enable") == "all",
          c.setting("cluster.routing.allocation.enable"))
    check("setting source reports transient", c.setting_source("cluster.routing.allocation.enable") == "transient",
          c.setting_source("cluster.routing.allocation.enable"))
    check("an API error body reads as missing", Loader(root).json("licenses.json") is None)
    check("a normal body is kept", Loader(root).json("version.json") is not None)


def failure_store(tmp):
    root = os.path.join(tmp, "fs")
    b = Bundle(version="9.4.4")
    fs_old, fs_new = ".fs-logs-a-default-2026.09.01-000001", ".fs-logs-a-default-2026.09.08-000002"
    for x in (".ds-logs-a-default-2026.09.01-000001", fs_old, fs_new):
        b.index(x, GB, M)
    b.stream("logs-a-default", [".ds-logs-a-default-2026.09.01-000001"])
    b.data_streams[-1]["failure_store"] = {"enabled": True, "indices": [
        {"index_name": fs_old, "managed_by": "Data stream lifecycle"},
        {"index_name": fs_new, "managed_by": "Data stream lifecycle"}]}
    b.write(root)
    c = ctx_of(root)
    check("failure store write index is a write target", fs_new in c.write_targets(), sorted(c.write_targets()))
    check("older failure store index is rolled over", c.rolled_over(fs_old) and not c.rolled_over(fs_new))
    check("failure store indices are managed by data stream lifecycle", c.dlm_managed(fs_old) and c.dlm_managed(fs_new))
    check("failure store indices are user data", not c.is_system_index(fs_new))


def mapping_and_merge():
    s = summarize([("a", {"mappings": {"properties": {"@timestamp": {"type": "date"}}}}),
                   ("b", {"mappings": {"properties": {"@timestamp": {"type": "keyword"}}}}),
                   ("c", {"mappings": {"properties": {"x": {"type": "long"}}}}),
                   ("d", {"mappings": {"properties": {"@timestamp": {"type": "date", "index": False, "doc_values": False}}}})])
    check("indexed @timestamp date is time-based", s["a"]["timestamp"] is True)
    check("keyword @timestamp is not time-based", s["b"]["timestamp"] is False)
    check("no @timestamp is not time-based", s["c"]["timestamp"] is False)
    check("@timestamp without index or doc values is not time-based", s["d"]["timestamp"] is False)

    class _C(object):
        version_tuple = (9, 4, 4)
        mapping_summary = s
        nodes = []

        def data_stream_of(self, name):
            return None

        def index_mode(self, name):
            return None
    k = "index.merge.policy.max_merged_segment"
    check("plain index with @timestamp uses the time-based 100gb", default_for(k, _C(), index="a") == "100gb", default_for(k, _C(), index="a"))
    check("index without @timestamp keeps 5gb", default_for(k, _C(), index="c") == "5gb", default_for(k, _C(), index="c"))


def logs(tmp):
    root = os.path.join(tmp, "logs")
    os.makedirs(os.path.join(root, "logs"))
    lines = ["line %06d" % i for i in range(200000)]
    with gzip.open(os.path.join(root, "logs", "c1-2026-09-30-1.log.gz"), "wt") as fh:
        fh.write("\n".join(lines) + "\nLAST LINE\n")
    with gzip.open(os.path.join(root, "logs", "c1-2026-09-30-1.json.gz"), "wt") as fh:
        fh.write("{}\n")
    with gzip.open(os.path.join(root, "logs", "c1_audit-2026-09-30-1.json.gz"), "wt") as fh:
        fh.write("{}\n")
    w(root, "nodes.json", {"nodes": {}})
    b = Loader(root)
    files = b.log_files()
    check("rolled .json.gz logs are listed", any(f.endswith("c1_audit-2026-09-30-1.json.gz") for f in files), files)
    kept = _es_log_files(files)
    check("a rolled .json.gz with a matching .log.gz is not counted twice",
          not any(f.endswith("c1-2026-09-30-1.json.gz") for f in kept), kept)
    text = b.read_log([f for f in files if f.endswith(".log.gz")][0], max_bytes=4096)
    check("gz log read returns the tail", text.rstrip().endswith("LAST LINE") and "line 000000" not in text, text[-40:])


def bottleneck(tmp):
    class _N(object):
        def __init__(self, name, data):
            self.name, self.is_data = name, data

    class _C(object):
        nodes = [_N("coord", False), _N("hot-1", True), _N("warm-1", True)]
        data_nodes = nodes[1:]

        def tier_of(self, n):
            return {"hot-1": "hot", "warm-1": "warm"}.get(n.name)
    scope = _tier_scope(_C(), {"coord"})
    check("a coordinating-only symptom node widens the scope to every data node", scope == {"coord", "hot-1", "warm-1"}, scope)


def diffs(tmp):
    t = merge({})
    a, b = os.path.join(tmp, "d-a"), os.path.join(tmp, "d-b")

    def before(i, s):
        s["jvm"]["uptime_in_millis"] = 10 ** 10
        s["thread_pool"]["write"] = {"rejected": 500, "queue": 0}
        s["breakers"] = {"request": {"tripped": 5}}
        s["jvm"]["gc"] = {"collectors": {"old": {"collection_count": 50, "collection_time_in_millis": 5000}}}

    def after(i, s):
        before(i, s)
        if i == 0:                                   # restarted 1 hour ago, counters from 0
            s["jvm"]["uptime_in_millis"] = 3600000
            s["thread_pool"]["write"]["rejected"] = 40
            s["breakers"]["request"]["tripped"] = 2
            s["jvm"]["gc"]["collectors"]["old"]["collection_count"] = 3
        else:
            s["jvm"]["uptime_in_millis"] = 10 ** 10 + 2 * 3600000
    build(a, "2026-10-01T00:00:00Z", before)
    build(b, "2026-10-01T02:00:00Z", after)
    ca, cb = ctx_of(a), ctx_of(b)
    hours = D._elapsed_hours(ca, cb)
    r5 = ids(D.r_rejections_delta(ca, cb, hours, t))
    check("restarted node: rejections since restart are new (DIF-005)", "DIF-005" in r5 and "DIF-004" not in r5, list(r5))
    if "DIF-005" in r5:
        rows = r5["DIF-005"].evidence["rows"]
        check("restarted node delta is its whole current value", rows and rows[0][4] == "40", rows)
    r7 = ids(D.r_breaker_delta(ca, cb, hours, t))
    check("restarted node: breaker trips since restart (DIF-007)", "DIF-007" in r7, list(r7))
    r6 = ids(D.r_gc_delta(ca, cb, hours, t))
    check("restarted node: old GC since restart (DIF-006)", "DIF-006" in r6, list(r6))

    # A different cluster: only DIF-013
    c2 = os.path.join(tmp, "d-c")
    build(c2, "2026-10-01T02:00:00Z", after, uuid="u-2")
    _s, fs = D.compare(ca, ctx_of(c2), t)
    check("different cluster returns DIF-013 alone", [f.id for f in fs] == ["DIF-013"], [f.id for f in fs])
    # _na_ uuid is ignored
    c3 = os.path.join(tmp, "d-na")
    build(c3, "2026-10-01T02:00:00Z", after, uuid="_na_")
    check("_na_ uuid is not a different cluster", not D.r_cluster_identity(ca, ctx_of(c3), hours, t))

    # DIF-001 with an unknown status
    cx = ctx_of(b)
    cx.health = dict(cx.health, status=None)
    check("unknown status is not a change (DIF-001)", not D.r_status_change(ca, cx, hours, t))

    # errors are recorded, not swallowed
    errs = []
    orig = D.DIFF_RULES[:]
    try:
        def boom(*_a):
            raise RuntimeError("x")
        boom.__name__ = "r_boom"
        D.DIFF_RULES.append(boom)
        D.compare(ca, cb, t, errors=errs)
    finally:
        D.DIFF_RULES[:] = orig
    check("a failing trend rule is recorded in errors", [e["rule"] for e in errs] == ["diff.r_boom"], errs)

    # DIF-012: a finding whose rule was skipped is not resolved
    f = Finding("SNP-003", "ops", Severity.WARNING, "x")
    f.rule = "ops.r_snapshots"
    check("skipped rule is not counted as resolved", not D._finding_delta([f], [], ["ops.r_snapshots"]))
    check("a rule that ran and found nothing is resolved", bool(D._finding_delta([f], [], [])))


def disk_projection(tmp):
    t = merge({})
    a, b = os.path.join(tmp, "p-a"), os.path.join(tmp, "p-b")

    def before(i, s):
        s["fs"]["total"] = {"total_in_bytes": 1000 * GB, "available_in_bytes": 500 * GB, "free_in_bytes": 500 * GB}

    def resized(i, s):
        # disk doubled, used bytes unchanged
        s["fs"]["total"] = {"total_in_bytes": 2000 * GB, "available_in_bytes": 1500 * GB, "free_in_bytes": 1500 * GB}
    build(a, "2026-10-01T00:00:00Z", before)
    build(b, "2026-10-02T00:00:00Z", resized)
    f = ids(D.r_disk_projection(ctx_of(a), ctx_of(b), 24.0, t)).get("DIF-008")
    rows = (f.evidence or {}).get("rows", []) if f else []
    check("a resized disk is not growth (DIF-008)", f is not None and f.severity == Severity.INFO
          and all(r[3].startswith("0") for r in rows if r[3] != "-"), rows)

    # membership change: warm-1 leaves the data role in the current bundle
    c = os.path.join(tmp, "p-c")
    build(c, "2026-10-02T00:00:00Z", lambda i, s: s["fs"]["total"].update(available_in_bytes=100 * GB) if i == 0 else None)
    ni = json.load(open(os.path.join(c, "nodes.json")))
    ns = json.load(open(os.path.join(c, "nodes_stats.json")))
    for nid in list(ni["nodes"]):
        if ni["nodes"][nid]["name"] == "warm-1":
            ni["nodes"].pop(nid)
            ns["nodes"].pop(nid)
    # a new hot node joins
    ni["nodes"]["node09XXXXXXXXXXXXXXXXX"] = dict(copy.deepcopy(list(ni["nodes"].values())[0]), name="hot-9", host="hot-9")
    ns["nodes"]["node09XXXXXXXXXXXXXXXXX"] = dict(copy.deepcopy(list(ns["nodes"].values())[0]), name="hot-9")
    w(c, "nodes.json", ni)
    w(c, "nodes_stats.json", ns)
    f = ids(D.r_disk_projection(ctx_of(a), ctx_of(c), 24.0, t)).get("DIF-008")
    check("a tier whose membership changed is not rated (DIF-008)", f is not None and f.severity == Severity.INFO,
          f and f.observed)


def skew(tmp):
    t = merge({})
    a, b = os.path.join(tmp, "s-a"), os.path.join(tmp, "s-b")

    def mk(add):
        def fn(i, s):
            s["jvm"]["uptime_in_millis"] = 10 ** 10 + add * 1000
            s.setdefault("indices", {}).setdefault("indexing", {})["index_total"] = 10 ** 6 + (add * (10 if i == 0 else 1) if add else 0)
        return fn
    build(a, "2026-10-01T00:00:00Z", mk(0))
    build(b, "2026-10-01T01:00:00Z", mk(100))       # a handful of documents in an hour
    ca, cb = ctx_of(a), ctx_of(b)
    for n in ca.nodes + cb.nodes:
        n.roles = ["data_hot"]
    f = ids(D.r_throughput(ca, cb, 1.0, t)).get("DIF-009")
    check("a quiet tier is not rated as skewed (DIF-009)", f is None or f.severity == Severity.INFO, f and f.observed)


def engine_base(tmp):
    a, b = os.path.join(tmp, "e-a"), os.path.join(tmp, "e-b")
    build(a, "2026-10-01T00:00:00Z")
    build(b, "2026-10-02T00:00:00Z")
    try:
        analyze(a, baseline=b)
        check("a baseline collected later is refused", False)
    except ValueError:
        check("a baseline collected later is refused", True)
    res = analyze(b, baseline=a)
    check("normal order compares", res.diff_summary is not None and not res.errors, res.errors)


def rules(tmp, lang):
    set_lang(lang)
    pre = "[%s] " % lang
    b = Bundle(version="9.4.4")
    b.index("wide-16", 9 * GB, M, pri=16)
    ds = [".ds-logs-a-default-2026.09.01-000001", ".ds-logs-a-default-2026.09.02-000002"]
    for x in ds:
        b.index(x, GB, M)
    b.stream("logs-a-default", ds)
    root = os.path.join(tmp, "r-" + lang)
    b.write(root)
    fields = dict(("f%03d" % i, {"type": "keyword"}) for i in range(98))
    w(root, "mapping.json", dict((x, {"mappings": {"properties": fields}}) for x in ds))
    st = json.load(open(os.path.join(root, "settings.json")))
    for x in ds:
        st[x]["settings"]["index"]["mapping"] = {"total_fields": {"limit": "100"}}
    w(root, "settings.json", st)
    ns = json.load(open(os.path.join(root, "nodes_stats.json")))
    for nid, s in ns["nodes"].items():
        # host load average seen inside a container that has a CPU quota, with almost no CPU use
        s["os"] = {"cpu": {"percent": 1, "load_average": {"15m": 8.0}},
                   "cgroup": {"cpu": {"cfs_quota_micros": 400000}}}
    w(root, "nodes_stats.json", ns)
    res = analyze(root)
    check(pre + "no rule errors", not res.errors, [e["rule"] for e in res.errors])
    f = ids(res.findings)
    o1 = f.get("OVS-001")
    rows = (o1.evidence or {}).get("rows", []) if o1 else []
    row = [r for r in rows if r[0] == "wide-16"]
    check(pre + "OVS-001 recommends a factor of the primary count (16 -> 4, not 3)", row and row[0][5] == 4, rows)
    m4 = f.get("MAP-004")
    names = [r[0] for r in ((m4.evidence or {}).get("rows", []) if m4 else [])]
    check(pre + "MAP-004 skips the rolled-over backing index", ds[0] not in names, names)
    check(pre + "MAP-004 keeps the write index", ds[1] in names, names)
    o = f.get("OS-001")
    check(pre + "OS-001 does not warn on a container with a CPU quota and low CPU",
          o is None or o.severity in (Severity.INFO, Severity.OK), o and o.observed)


def main():
    tmp = tempfile.mkdtemp()
    try:
        set_lang("en")
        settings_and_loader(tmp)
        failure_store(tmp)
        mapping_and_merge()
        logs(tmp)
        bottleneck(tmp)
        diffs(tmp)
        disk_projection(tmp)
        skew(tmp)
        engine_base(tmp)
        for lang in ("ko", "en"):
            rules(tmp, lang)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        set_lang("ko")
    for f in FAILS:
        print("FAIL " + f)
    print("audit 0.14.3 checks: %d run, %d failed" % (N[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
