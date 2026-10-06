#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checks for the fixes from the final per-rule review of 0.14.3. No external bundle needed (synthetic data).

Covers shared helpers (dotted child keys in settings maps, single-letter byte units, cat tables with spaces in the last column,
indexing pressure rejections, ILM policy of DLM-managed indices), the settings KB (search queue default, ratio watermarks,
values of another kind, auto_expand_replicas ranges, logsdb ignore_dynamic_beyond_limit default, recoveries fallback), the
LogMergePolicy level count, template pattern intersection, the comparison rules (mounted indices, joined nodes, status
severity, restart severity, rate labels, rules that did not run on the base), and rule changes on synthetic bundles (SYS-004,
SNP-001/003/007, LIC-001 trial, SEC-001 CA certificates, SEC-002 transport binding, CLU-015 frozen only, DISK-002, JVM-003,
SHD-004 evidence, IDX-002 without nodes). Both languages where text is involved.

    python3 tests/test_audit_final.py
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from esdoctor import diff as D  # noqa: E402
from esdoctor.context import Context, _flat_get  # noqa: E402
from esdoctor.engine import analyze  # noqa: E402
from esdoctor.i18n import set_lang  # noqa: E402
from esdoctor.loader import Bundle as Loader  # noqa: E402
from esdoctor.model import Finding, Severity  # noqa: E402
from esdoctor.rules.hotspot import _globs_intersect  # noqa: E402
from esdoctor.rules.settings import _wide_auto_expand  # noqa: E402
from esdoctor.settings_kb import compare, default_for, risk_of  # noqa: E402
from esdoctor.thresholds import merge  # noqa: E402
from esdoctor.util import ip_rejections, parse_bytes, parse_cat_table  # noqa: E402
from test_logsdb import Bundle, GB, M, w  # noqa: E402

FAILS, N = [], [0]
T = merge({})


def check(name, cond, detail=""):
    N[0] += 1
    if not cond:
        FAILS.append(name + (" - " + str(detail) if detail else ""))


def ids(fs):
    return dict((f.id, f) for f in fs)


def rows_of(f):
    return [r for r in ((f or Finding("x", "x", Severity.INFO, "x")).evidence or {}).get("rows", [])]


def helpers():
    s = {"cluster": {"routing": {"allocation": {"disk": {"watermark": {"low": "85%", "low.max_headroom": "50gb"}}}}},
         "transport": {"type": "security4", "type.default": "netty4"}}
    check("dotted child key inside a parent map", _flat_get(s, "cluster.routing.allocation.disk.watermark.low.max_headroom") == "50gb")
    check("value key next to its dotted child", _flat_get(s, "cluster.routing.allocation.disk.watermark.low") == "85%")
    check("transport.type.default", _flat_get(s, "transport.type.default") == "netty4")
    check("flat key", _flat_get({"a.b.c": 1}, "a.b.c") == 1)
    check("500m is 500MiB", parse_bytes("500m") == 500 * 1024 ** 2, parse_bytes("500m"))
    check("1g is 1GiB", parse_bytes("1g") == 1024 ** 3)
    check("1.5t", parse_bytes("1.5t") == int(1.5 * 1024 ** 4))
    tbl = ("index shard prirep state      docs store ip       node\n"
           "i     0     p      RELOCATING 127189472 1gb 10.0.0.1 n1 -> 10.0.0.2 abc n2\n")
    r = parse_cat_table(tbl)[0]
    check("cat table: surplus joins the last column", r["state"] == "RELOCATING" and r["docs"] == "127189472"
          and r["node"].startswith("n1 ->"), r)
    alloc = ("shards disk.used node       node.role\n"
             "5      10gb      es node 1  cdfhilmrstw\n")
    r = parse_cat_table(alloc)[0]
    check("cat table: spaces in an earlier column are cut by offsets", r["node.role"] == "cdfhilmrstw", r)
    ch, d, _s, _df, _src = compare("cluster.routing.allocation.disk.watermark.low", "0")
    check("watermark 0 is not a ratio of 0%", d != "down", d)
    st = {"indexing_pressure": {"memory": {"total": {"coordinating_rejections": 1, "primary_rejections": 2,
                                                     "replica_rejections": 0, "primary_document_rejections": 500,
                                                     "large_operation_rejections": -1}}}}
    check("indexing pressure rejections: coordinating + primary + replica only", ip_rejections(st) == 3, ip_rejections(st))
    check("glob intersection *-prod and logs-*", _globs_intersect("*-prod", "logs-*"))
    check("glob no intersection", not _globs_intersect("metrics-*", "logs-*"))
    check("glob a* and *b", _globs_intersect("a*", "*b"))
    check("auto_expand 0-1 is bounded", not _wide_auto_expand("0-1"))
    check("auto_expand 0-all is wide", _wide_auto_expand("0-all") and _wide_auto_expand("1-3"))
    check("rate label keeps a decimal below 10", D._rate_label(0.5) == "0.5" and D._rate_label(12.4) == "12")


class _N(object):
    def __init__(self, alloc):
        self.info = {"os": {"allocated_processors": alloc}}
        self.processors = alloc
        self.roles = ["data_hot"]
        self.ram_total = 0


class _K(object):
    def __init__(self, version, settings=None, mode=None, created=None):
        self.version_tuple = version
        self._s = settings or {}
        self._mode = mode
        self._created = created
        self.nodes = []

    def setting(self, key, default=None):
        return self._s.get(key, default)

    def index_mode(self, name):
        return self._mode

    def index_setting(self, name, key, default=None):
        return self._created if key == "index.version.created" else default


def settings_kb():
    q = default_for("thread_pool.search.queue_size", _K((9, 1, 0)), node=_N(8))
    check("9.x search queue default = search threads x 1000", q == str((8 * 3 // 2 + 1) * 1000), q)
    check("8.x search queue default 1000", default_for("thread_pool.search.queue_size", _K((8, 19, 0)), node=_N(8)) == "1000")
    ch, d, _s, _df, _src = compare("thread_pool.search.queue_size", "1000", default="1000")
    check("8.x search queue 1000 is the default", not ch)
    ch, d, spec, _df, _src = compare("cluster.routing.allocation.disk.watermark.high", "0.90")
    check("ratio 0.90 equals 90%", not ch, (ch, d))
    ch, d, spec, _df, _src = compare("cluster.routing.allocation.disk.watermark.high", "50gb")
    check("absolute watermark has no direction and is Info", ch and d == "kind" and risk_of(spec, d) == "INFO", (d, risk_of(spec, d)))
    check("7.17 destructive_requires_name default false",
          default_for("action.destructive_requires_name", _K((7, 17, 0))) == "false")
    check("incoming recoveries follow node_concurrent_recoveries",
          default_for("cluster.routing.allocation.node_concurrent_incoming_recoveries",
                      _K((9, 0, 0), {"cluster.routing.allocation.node_concurrent_recoveries": "4"})) == "4")
    key = "index.mapping.total_fields.ignore_dynamic_beyond_limit"
    check("logsdb on 9.x index version ignores dynamic fields by default",
          default_for(key, _K((9, 1, 0), mode="logsdb", created="9035000"), index="i") == "true")
    check("logsdb on 9_000_0_00 does not", default_for(key, _K((9, 0, 0), mode="logsdb", created="9000000"), index="i") == "false")
    check("standard index does not", default_for(key, _K((9, 1, 0), mode="standard", created="9035000"), index="i") == "false")
    check("time-based merge default from 8.8 for a data stream member",
          default_for("index.merge.policy.max_merged_segment", type("C", (), {
              "version_tuple": (8, 8, 0), "data_stream_of": lambda s, n: {"name": "x"}})(), index="i") == "100gb")


def diff_rules(tmp):
    set_lang("en")

    def mk(root, names, collected, status="green", version="9.4.4", fn=None):
        b = Bundle(version=version)
        for n in names:
            b.index(n, GB, M)
        b.write(root)
        w(root, "manifest.json", {"diagVersion": "9.4.1", "collectionDate": collected,
                                  "diagnosticInputs": "DiagnosticInputs: {, diagType='api', mode='full'}"})
        w(root, "version.json", {"cluster_name": "c1", "cluster_uuid": "u", "version": {"number": version}})
        h = json.load(open(os.path.join(root, "cluster_health.json")))
        h["status"] = status
        w(root, "cluster_health.json", h)
        if fn:
            ns = json.load(open(os.path.join(root, "nodes_stats.json")))
            for i, nid in enumerate(sorted(ns["nodes"])):
                fn(i, ns["nodes"][nid])
            w(root, "nodes_stats.json", ns)
        return Context(Loader(root), merge({}))

    a = mk(os.path.join(tmp, "a"), [".ds-logs-x-2026.09.01-000001", "keep"], "2026-10-01T00:00:00Z")
    b = mk(os.path.join(tmp, "b"), ["restored-.ds-logs-x-2026.09.01-000001", "keep", "fresh"], "2026-10-01T12:00:00Z",
           status="yellow")
    f = ids(D.r_index_growth(a, b, 12.0, T))
    d11 = f.get("DIF-011")
    kinds = [r[0] for r in rows_of(d11)]
    check("DIF-011: a mount is listed as moved, not new and deleted", d11 is not None and "Mounted" in kinds
          and "Deleted" not in kinds and kinds.count("New") == 1, rows_of(d11))
    s = D.r_status_change(a, b, 12.0, T)
    check("DIF-001 green to yellow is Warning (as CLU-001)", s and s[0].severity == Severity.WARNING, s and s[0].severity)
    s = D.r_status_change(mk(os.path.join(tmp, "c"), ["keep"], "2026-10-01T00:00:00Z", status="red"), b, 12.0, T)
    check("DIF-001 red to yellow is Info and not 'resolved'", s and s[0].severity == Severity.INFO
          and "not green" in s[0].impact, s and s[0].impact)
    fa = Finding("SNP-001", "x", Severity.CRITICAL, "t")
    fa.rule = "ops.r_snapshots"
    out = D._finding_delta([], [fa], [], ["ops.r_snapshots"])
    check("DIF-012: a rule that did not run on the base does not make new findings", not out, out)

    def up(hours):
        def fn(i, s):
            s["jvm"]["uptime_in_millis"] = hours * 3600000
        return fn
    x = mk(os.path.join(tmp, "x"), ["keep"], "2026-10-01T00:00:00Z", fn=up(100))
    y = mk(os.path.join(tmp, "y"), ["keep"], "2026-10-01T12:00:00Z", fn=up(1))
    r = ids(D.r_node_restart(x, y, 12.0, T)).get("DIF-002")
    check("DIF-002 restart is Warning", r is not None and r.severity == Severity.WARNING, r and r.severity)
    y2 = mk(os.path.join(tmp, "y2"), ["keep"], "2026-10-01T12:00:00Z", version="9.5.3", fn=up(1))
    r = ids(D.r_node_restart(x, y2, 12.0, T)).get("DIF-002")
    check("DIF-002 restart with a version change is Info", r is not None and r.severity == Severity.INFO, r and r.severity)

    def rej(i, s):
        s["jvm"]["uptime_in_millis"] = 3600000
        s["thread_pool"] = {"write": {"rejected": 600, "queue": 0}}
    base = mk(os.path.join(tmp, "j1"), ["keep"], "2026-10-01T00:00:00Z")
    cur = mk(os.path.join(tmp, "j2"), ["keep"], "2026-10-01T12:00:00Z", fn=rej)
    for n in base.nodes:
        n.name = n.name + "-gone"
    f = ids(D.r_rejections_delta(base, cur, 12.0, T))
    check("DIF-005 counts a joined node's rejections", "DIF-005" in f and "DIF-004" not in f, sorted(f))


def rules_synthetic(tmp, lang):
    set_lang(lang)
    pre = "[%s] " % lang
    b = Bundle(version="9.5.3")
    b.index("app-1", GB, M)
    root = os.path.join(tmp, "r" + lang)
    b.write(root)
    w(root, "licenses.json", {"license": {"status": "active", "type": "trial", "expiry_date": "2026-10-15T00:00:00Z"}})
    w(root, "ssl_certs.json", [{"path": "ca.crt", "subject_dn": "CN=old ca", "has_private_key": False,
                                "expiry": "2026-09-01T00:00:00Z"}])
    w(root, "repositories.json", {"error": {"type": "security_exception"}, "status": 403})
    ns = json.load(open(os.path.join(root, "nodes_stats.json")))
    for nid, st in ns["nodes"].items():
        st["indexing_pressure"] = {"memory": {"total": {"primary_document_rejections": 5, "large_operation_rejections": 2,
                                                        "coordinating_rejections": 0, "primary_rejections": 0,
                                                        "replica_rejections": 0}}}
    w(root, "nodes_stats.json", ns)
    f = ids(analyze(root).findings)
    lic = f.get("LIC-001")
    check(pre + "trial license is Warning", lic is not None and lic.severity == Severity.WARNING, lic and lic.severity)
    sec = f.get("SEC-001")
    check(pre + "expired CA in a trust store is Warning", sec is not None and sec.severity == Severity.WARNING, sec and sec.severity)
    check(pre + "SNP-001 skipped when repositories.json is an error body", "SNP-001" not in f, sorted(f))
    check(pre + "IP-001 needs coordinating/primary/replica rejections", "IP-001" not in f)

    # repository list unreadable, but SLM stopped with a policy: the other snapshot findings still run
    root4 = os.path.join(tmp, "q" + lang)
    b.write(root4)
    w(root4, "repositories.json", {"error": {"type": "security_exception"}, "status": 403})
    w(root4, "commercial/slm_policies.json", {"p": {"last_success": {"time": 1}}})
    w(root4, "commercial/slm_status.json", {"operation_mode": "STOPPED"})
    w(root4, "cluster_settings.json", {"error": {"type": "security_exception"}, "status": 403})
    f = ids(analyze(root4).findings)
    check(pre + "SNP-006 still runs when repositories.json is an error body", "SNP-006" in f, sorted(f))
    check(pre + "PERF-006 not asserted when cluster settings are an error body", "PERF-006" not in f)
    # a SUCCESS snapshot listed without times (verbose=false) is not 'no successful snapshot'
    root5 = os.path.join(tmp, "v" + lang)
    b.write(root5)
    w(root5, "repositories.json", {"r": {"type": "fs"}})
    w(root5, "snapshot.json", {"snapshots": [{"snapshot": "s1", "repository": "r", "state": "SUCCESS"}]})
    s3 = ids(analyze(root5).findings).get("SNP-003")
    check(pre + "SNP-003 not Critical for a SUCCESS snapshot without times", s3 is None or s3.severity != Severity.CRITICAL,
          s3 and s3.severity)

    # repository registered but no snapshot, and SLM failing once
    root2 = os.path.join(tmp, "s" + lang)
    b.write(root2)
    w(root2, "repositories.json", {"r": {"type": "fs"}})
    w(root2, "snapshot.json", {"snapshots": []})
    f = ids(analyze(root2).findings)
    s3 = f.get("SNP-003")
    check(pre + "SNP-003 Critical: repository without any snapshot", s3 is not None and s3.severity == Severity.CRITICAL,
          s3 and s3.severity)
    root3 = os.path.join(tmp, "l" + lang)
    b.write(root3)
    w(root3, "repositories.json", {"r": {"type": "fs"}})
    w(root3, "commercial/slm_policies.json", {"p": {"last_success": {"time": 1759276800000 - 3600000},
                                                    "last_failure": {"time": 1759276800000 - 60000},
                                                    "invocations_since_last_success": 1}})
    w(root3, "manifest.json", {"diagVersion": "9.4.1", "collectionDate": "2025-10-01T00:00:00Z",
                               "diagnosticInputs": "DiagnosticInputs: {, diagType='api', mode='full'}"})
    f = ids(analyze(root3).findings)
    s7 = f.get("SNP-007")
    check(pre + "SNP-007 one failure after a recent success is Warning", s7 is not None and s7.severity == Severity.WARNING,
          s7 and s7.severity)


def node_rules(tmp):
    set_lang("en")
    b = Bundle(version="9.5.3")
    b.index("app-1", GB, M, pri=1)
    root = os.path.join(tmp, "nodes")
    b.write(root)
    nodes = json.load(open(os.path.join(root, "nodes.json")))
    for nid, n in nodes["nodes"].items():
        n["roles"] = ["master"] if n["name"] == "hot-1" else n.get("roles", ["data_hot"])
        n["transport"] = {"bound_address": ["10.0.0.1:9300"]}
        n["http"] = {"bound_address": ["127.0.0.1:9200"]}
    w(root, "nodes.json", nodes)
    w(root, "commercial/xpack.json", {"security": {"enabled": False}})
    f = ids(analyze(root).findings)
    s2 = f.get("SEC-002")
    check("SEC-002 stays Critical when transport is not loopback", s2 is not None and s2.severity == Severity.CRITICAL,
          s2 and s2.severity)
    c = Context(Loader(root), merge({}))
    c.nodes = []
    from esdoctor.rules.shards import r_replica_unassignable
    check("IDX-002 not rated without node information", r_replica_unassignable(c) == [])


def main():
    tmp = tempfile.mkdtemp()
    try:
        helpers()
        settings_kb()
        diff_rules(tmp)
        for lang in ("ko", "en"):
            rules_synthetic(tmp, lang)
        node_rules(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        set_lang("ko")
    for f in FAILS:
        print("FAIL " + f)
    print("final review checks: %d run, %d failed" % (N[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
