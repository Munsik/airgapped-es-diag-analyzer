#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checks for 0.14.0: bottleneck summary, recently restarted nodes left out of node comparisons, frozen shared cache on a
network filesystem (FRZ-002), busy search pool with low CPU (PERF-013), ingest failure ratio (ING-001) and the storage cost
findings (COST-001 to COST-006), and the fixes from the review of a real 14-node bundle (bottleneck causes scoped to the
symptom tiers, PERF-013 on frozen nodes, DIF-008 per tier, DIF-014 interval checks, SET-005 per tier, node change table cells,
COST-004 landing tier). No external bundle needed (synthetic data). Every case runs in both languages.

    python3 tests/test_bottleneck_cost.py
"""
import copy
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from esdiag.engine import analyze  # noqa: E402
from esdiag.i18n import set_lang  # noqa: E402
from esdiag.mask import Masker  # noqa: E402
from esdiag.model import Severity  # noqa: E402
from esdiag.report import handoff as handoff_report  # noqa: E402
from esdiag.report import html as html_report  # noqa: E402
from esdiag.report import text as text_report  # noqa: E402
from test_logsdb import Bundle, COLLECTED_MS, GB, M, w  # noqa: E402

HANGUL = re.compile(u"[가-힣]")
FAILS, N = [], [0]
NEW_IDS = ("FRZ-002", "PERF-013", "ING-001", "COST-001", "COST-002", "COST-003", "COST-004", "COST-005", "COST-006",
           "HOT-001", "HOT-002", "DIF-009", "DIF-014")
DAY = 86400000
HOUR = 3600000

HOT_THREADS = """::: {frozen-1}{node02XXXXXXXXXXXXXXXXX}{x}{frozen-1}{10.0.0.3}{10.0.0.3:9300}{f}
   Hot threads at 2026-10-01T00:00:00Z, interval=500ms, busiestThreads=3, ignoreIdleThreads=true:

   90.0% [cpu=2.0%, other=88.0%] (450ms out of 500ms) cpu usage by thread 'elasticsearch[frozen-1][search][T#3]'
     10/10 snapshots sharing following 6 elements
       java.base@21/sun.nio.ch.FileDispatcherImpl.pread0(Native Method)
       java.base@21/sun.nio.ch.FileChannelImpl.readInternal(FileChannelImpl.java:800)
       java.base@21/sun.nio.ch.FileChannelImpl.read(FileChannelImpl.java:780)
       org.elasticsearch.blobcache.shared.SharedBytes$IO.read(SharedBytes.java:300)
       org.elasticsearch.xpack.searchablesnapshots.store.input.FrozenIndexInput.readWithoutBlobCache(FrozenIndexInput.java:100)
       org.apache.lucene.search.IndexSearcher.search(IndexSearcher.java:500)
"""


def check(name, cond, detail=""):
    N[0] += 1
    if not cond:
        FAILS.append(name + (" - " + str(detail) if detail else ""))


def load(root, rel):
    with open(os.path.join(root, rel)) as fh:
        return json.load(fh)


def _by_name(doc):
    return dict((v["name"], k) for k, v in doc["nodes"].items())


def build(root, symptoms=True, zones=False, restart_hot2=True, hot2_index_total=10 ** 6):
    """hot-1, hot-2 (restarted 2 hours ago), warm-1, frozen-1 (NFS)."""
    b = Bundle()
    b.policies["p2"] = {"policy": {"phases": {"hot": {"actions": {"rollover": {"max_primary_shard_size": "50gb"}}},
                                              "warm": {"min_age": "60d", "actions": {}}}}}
    ds = [".ds-logs-a-default-2026.08.01-000001", ".ds-logs-a-default-2026.09.29-000002"]
    b.index(ds[0], 10 * GB, M, policy="p2", node="hot-1")
    b.index(ds[1], 5 * GB, M, policy="p2", node="hot-1")
    b.stream("logs-a-default", ds, policy="p2")
    b.explain[ds[0]]["lifecycle_date_millis"] = COLLECTED_MS - 40 * DAY
    b.explain[ds[1]]["lifecycle_date_millis"] = COLLECTED_MS - 2 * DAY
    b.index("idle-3rep", 20 * GB, M, node="hot-1")
    b.settings["idle-3rep"]["settings"]["index"]["number_of_replicas"] = "2"
    b.index("searched-3rep", 20 * GB, M, node="hot-1")
    b.settings["searched-3rep"]["settings"]["index"]["number_of_replicas"] = "2"
    b.stats["searched-3rep"]["total"]["search"] = {"query_total": 50}
    b.index("bulk-noilm", 350 * GB, M, node="hot-2")      # 700GB with replica, created 2 days ago, no ILM
    b.index("old-index", GB, M, node="warm-1")
    created = {"bulk-noilm": COLLECTED_MS - 2 * DAY, "old-index": COLLECTED_MS - 30 * DAY,
               ds[0]: COLLECTED_MS - 61 * DAY, ds[1]: COLLECTED_MS - 2 * DAY,
               "idle-3rep": COLLECTED_MS - 20 * DAY, "searched-3rep": COLLECTED_MS - 20 * DAY}
    for name, c in created.items():
        b.settings[name]["settings"]["index"]["creation_date"] = str(c)
    b.write(root)

    ni, ns = load(root, "nodes.json"), load(root, "nodes_stats.json")
    ids = _by_name(ni)
    hot1 = ids["hot-1"]
    ni["nodes"]["node99XXXXXXXXXXXXXXXXXX"] = dict(copy.deepcopy(ni["nodes"][hot1]), name="hot-2")
    ns["nodes"]["node99XXXXXXXXXXXXXXXXXX"] = dict(copy.deepcopy(ns["nodes"][hot1]), name="hot-2")
    for nid, info in ni["nodes"].items():
        info["thread_pool"]["search"] = {"type": "fixed", "size": 13, "queue_size": 1000}
        if zones:
            info["attributes"] = {"availability_zone": "z%d" % (hash(info["name"]) % 3)}
    zi = 0
    for nid, info in sorted(ni["nodes"].items()):
        if zones:
            info["attributes"] = {"availability_zone": "z%d" % (zi % 3)}
            zi += 1
    for nid, st in ns["nodes"].items():
        name = st["name"]
        st["jvm"]["uptime_in_millis"] = 2 * HOUR if (name == "hot-2" and restart_hot2) else 100 * DAY
        st["os"] = {"cpu": {"percent": 30, "load_average": {"1m": 1, "5m": 1, "15m": 1}}}
        st["thread_pool"]["search"] = {"threads": 13, "active": 1, "queue": 0, "rejected": 0}
        st["thread_pool"]["write"] = {"threads": 4, "active": 1, "queue": 0, "rejected": 0}
        st["indices"] = {"indexing": {"index_total": 0}, "search": {"query_total": 0},
                         "flush": {"total": 1000, "total_time_in_millis": 1000 * 100},
                         "refresh": {"total": 1000, "total_time_in_millis": 1000 * 5},
                         "merges": {"total": 1000, "total_time_in_millis": 1000 * 1000}}
        if name.startswith("hot"):
            st["fs"]["total"] = {"total_in_bytes": 1000 * GB, "available_in_bytes": 250 * GB, "free_in_bytes": 250 * GB}
            st["jvm"]["mem"]["heap_used_percent"] = 90 if name == "hot-1" else 10
            st["os"]["cpu"]["percent"] = 60 if name == "hot-1" else 5
            st["indices"]["indexing"]["index_total"] = 10 ** 8 if name == "hot-1" else hot2_index_total
            st["indices"]["search"]["query_total"] = 10 ** 6
        if name == "hot-2":
            st["indices"]["flush"]["total_time_in_millis"] = 1000 * 1500
        if name == "warm-1":
            st["fs"]["total"] = {"total_in_bytes": 1000 * GB, "available_in_bytes": 950 * GB, "free_in_bytes": 950 * GB}
        if name == "frozen-1":
            st["fs"]["data"] = [{"path": "/data", "mount": "/data (nas:/vol1)", "type": "nfs4",
                                 "total_in_bytes": 1000 * GB}]
            st["indices"]["search"]["query_total"] = 1000
            if symptoms:
                st["os"]["cpu"]["percent"] = 5
                st["thread_pool"]["search"] = {"threads": 13, "active": 13, "queue": 40, "rejected": 7}
        if name == "hot-1" and symptoms:
            st["thread_pool"]["write"]["rejected"] = 500
            st["ingest"] = {"total": {"count": 101000, "failed": 51, "time_in_millis": 1000},
                            "pipelines": {"p-bad": {"count": 1000, "failed": 50},
                                          "p-ok": {"count": 100000, "failed": 1}}}
    w(root, "nodes.json", ni)
    w(root, "nodes_stats.json", ns)
    fz = ids["frozen-1"]
    w(root, "commercial/searchable_snapshots_cache_stats.json", {"nodes": {fz: {"shared_cache": {
        "num_regions": 100, "size_in_bytes": 900 * GB, "reads": 10, "bytes_read_in_bytes": GB, "evictions": 1}}}})
    if symptoms:
        w(root, "nodes_hot_threads.txt", HOT_THREADS)
        w(root, "logs/c1.log", "[2026-10-01T00:00:00,000][WARN ][o.e.b.ElasticsearchUncaughtExceptionHandler] "
                                "fatal error in thread [elasticsearch[frozen-1][search][T#3]], exiting\n"
                                "java.lang.OutOfMemoryError: Direct buffer memory\n")


def findings(res):
    return dict((f.id, f) for f in res.findings)


def rows_of(f):
    return (f.evidence or {}).get("rows", []) if f else []


def run_lang(lang, tmp):
    set_lang(lang)
    pre = "[%s] " % lang
    root = os.path.join(tmp, "a-" + lang)
    build(root)
    res = analyze(root)
    check(pre + "no rule errors", not res.errors, [e["rule"] + ": " + e["error"].strip().splitlines()[-1] for e in res.errors])
    f = findings(res)

    # restarted node left out of node comparisons
    h1 = f.get("HOT-001")
    check(pre + "HOT-001 not raised by the restarted node's low heap/CPU", h1 is not None and h1.severity == Severity.OK,
          h1 and (h1.severity, h1.observed))
    check(pre + "HOT-001 names the excluded node", h1 is not None and "hot-2" in (h1.observed or ""), h1 and h1.observed)
    check(pre + "HOT-002 not raised with one settled hot node", not any(k.startswith("HOT-002") for k in f))
    p12 = f.get("PERF-012")
    check(pre + "PERF-012 rates the restarted writer by hourly rate", p12 is not None and
          any(r[0] == "hot-2" for r in rows_of(p12)), rows_of(p12))

    # frozen on NFS, busy search pool
    fz = f.get("FRZ-002")
    check(pre + "FRZ-002 critical with Direct buffer memory in the logs", fz is not None and fz.severity == Severity.CRITICAL,
          fz and fz.severity)
    check(pre + "FRZ-002 lists frozen-1 with a hot thread reading the cache file",
          fz is not None and rows_of(fz) and rows_of(fz)[0][0] == "frozen-1" and rows_of(fz)[0][4] == "1", rows_of(fz))
    check(pre + "FRZ-002 skips hot nodes (no shared cache)", fz is not None and len(rows_of(fz)) == 1)
    p13 = f.get("PERF-013")
    check(pre + "PERF-013 warning (13/13 active, queue, CPU 5%)", p13 is not None and p13.severity == Severity.WARNING,
          p13 and p13.severity)
    check(pre + "PERF-013 lists frozen-1 only", p13 is not None and [r[0] for r in rows_of(p13)] == ["frozen-1"], rows_of(p13))

    # ingest failure ratio
    i1 = f.get("ING-001")
    check(pre + "ING-001 warning (p-bad 5%)", i1 is not None and i1.severity == Severity.WARNING)
    check(pre + "ING-001 sorts by failure ratio", i1 is not None and rows_of(i1)[0][0] == "p-bad", rows_of(i1))

    # cost
    c1 = f.get("COST-001")
    check(pre + "COST-001 lists the 40-day-old rolled-over index under p2", c1 is not None and rows_of(c1)
          and rows_of(c1)[0][0] == "p2" and rows_of(c1)[0][1] == 1, rows_of(c1))
    check(pre + "COST-001 shows the next phase", c1 is not None and "warm 60d" in str(rows_of(c1)[0][4]), rows_of(c1))
    c2 = f.get("COST-002")
    check(pre + "COST-002 lists only the unsearched index", c2 is not None and [r[0] for r in rows_of(c2)] == ["idle-3rep"],
          rows_of(c2))
    c3 = f.get("COST-003")
    check(pre + "COST-003 flags full hot and empty warm", c3 is not None and "hot" in c3.observed and "warm" in c3.observed,
          c3 and c3.observed)
    c4 = f.get("COST-004")
    check(pre + "COST-004 warning (about 3 days of headroom, data never leaves)", c4 is not None and c4.severity == Severity.WARNING,
          c4 and (c4.severity, c4.observed))
    check(pre + "COST-004 top contributor is bulk-noilm", c4 is not None and rows_of(c4)[0][0] == "bulk-noilm", rows_of(c4))

    # bottleneck summary
    rows = dict((r["id"], r) for r in res.bottleneck())
    check(pre + "summary has five questions", list(rows) == ["ingest", "search", "storage", "restart", "capacity"], list(rows))
    check(pre + "ingest: storage first (PERF-012)", rows["ingest"]["verdict_id"] == "storage" and "PERF-012" in rows["ingest"]["causes"],
          rows["ingest"])
    check(pre + "ingest: symptom names write rejections", any("500" in s for s in rows["ingest"]["basis"]), rows["ingest"]["basis"])
    check(pre + "search: storage reads (PERF-013, FRZ-002)", rows["search"]["verdict_id"] == "storage"
          and "FRZ-002" in rows["search"]["causes"], rows["search"])
    check(pre + "storage: signals", rows["storage"]["state"] == "issue", rows["storage"])
    check(pre + "storage tag critical (FRZ-002)", rows["storage"]["worst"] == Severity.CRITICAL)
    check(pre + "restart: recent (OS-006)", rows["restart"]["verdict_id"] == "recent", rows["restart"])
    check(pre + "capacity: disk (COST-004)", rows["capacity"]["verdict_id"] == "disk", rows["capacity"])
    d = res.to_dict()
    check(pre + "JSON has the summary", len(d.get("bottleneck") or []) == 5)

    try:
        out = text_report.console(res, show_ok=True)
        md = text_report.markdown(res, show_ok=True)
        ht = html_report.render(res)
        hf = handoff_report.render(res, Masker(res.ctx, level="basic"), "basic", "test")
        from esdiag.i18n import T
        title = T("btl.title")
        check(pre + "summary in every report", all(title in x for x in (out, md, ht, hf)))
    except Exception as exc:  # noqa: BLE001
        check(pre + "reports render", False, repr(exc))

    # --only gives no summary (it would be partial)
    res_o = analyze(root, only=["nodes"])
    check(pre + "no summary with --only", res_o.bottleneck() == [])

    if lang == "en":
        for x in res.findings:
            if x.id.split(".")[0] not in NEW_IDS:
                continue
            text = " ".join([x.title, x.observed or "", x.impact or "", x.recommend or ""] +
                            [str(c) for c in (x.evidence or {}).get("columns", [])])
            check(pre + "%s has no Hangul" % x.id, not HANGUL.search(text), HANGUL.findall(text)[:5])
            check(pre + "%s has no dash" % x.id, not re.search(u"[–—]", text))
            check(pre + "%s has no plural marker" % x.id, not re.search(r"\[[a-z ]+\|[a-z ]+\]", text))
        for r in res.bottleneck():
            text = " ".join(r["basis"] + [r["question"], r["verdict"], r["next"]])
            check(pre + "summary %s has no Hangul" % r["id"], not HANGUL.search(text))
            check(pre + "summary %s has no dash" % r["id"], not re.search(u"[–—]", text))


def run_variants(tmp):
    set_lang("en")
    # no symptoms: ingest keeping up, search clear
    root = os.path.join(tmp, "quiet")
    build(root, symptoms=False, restart_hot2=False, hot2_index_total=10 ** 8)
    res = analyze(root)
    f = findings(res)
    rows = dict((r["id"], r) for r in res.bottleneck())
    check("quiet: ingest clear", rows["ingest"]["state"] == "clear", rows["ingest"])
    check("quiet: search clear", rows["search"]["state"] == "clear", rows["search"])
    check("quiet: restart clear", rows["restart"]["state"] == "clear", rows["restart"])
    check("quiet: no FRZ-002 Critical without logs", f.get("FRZ-002") is not None and f["FRZ-002"].severity == Severity.WARNING)
    check("quiet: no PERF-013", "PERF-013" not in f)
    check("quiet: no ING-001", "ING-001" not in f)
    # both hot nodes settled: heap gap 80 points and hourly indexing skew are reported again
    check("settled: HOT-001 warning", f.get("HOT-001") is not None and f["HOT-001"].severity == Severity.WARNING,
          f.get("HOT-001") and f["HOT-001"].observed)

    # three zones and two replicas: one copy per zone is deliberate
    root = os.path.join(tmp, "zones")
    build(root, zones=True)
    f = findings(analyze(root))
    check("zones: COST-002 not raised", "COST-002" not in f, f.get("COST-002") and rows_of(f["COST-002"]))

    # hourly rate decides HOT-002: hot-2 settled with 10x fewer operations per hour
    root = os.path.join(tmp, "rate")
    build(root, restart_hot2=False, hot2_index_total=10 ** 7)
    f = findings(analyze(root))
    check("rate: HOT-002 indexing skew", "HOT-002.index_total" in f, sorted(f))

    # comparison: hot-2 restarted in the interval, left out of the totals
    base = os.path.join(tmp, "base")
    build(base, restart_hot2=False)
    ns = load(base, "nodes_stats.json")
    for st in ns["nodes"].values():
        st["jvm"]["uptime_in_millis"] = 100 * DAY - 6 * HOUR
        st["indices"]["indexing"]["index_total"] = max(0, st["indices"]["indexing"]["index_total"] - 10 ** 5)
    w(base, "nodes_stats.json", ns)
    w(base, "manifest.json", dict(load(base, "manifest.json"), collectionDate="2026-09-30T18:00:00Z"))
    cur = os.path.join(tmp, "cur")
    build(cur)
    ns_b = load(base, "nodes_stats.json")
    for st in ns_b["nodes"].values():
        if st["name"] == "hot-2":
            st["indices"]["indexing"]["index_total"] = 10 ** 8
    w(base, "nodes_stats.json", ns_b)
    res = analyze(cur, baseline=base)
    f = findings(res)
    d9 = f.get("DIF-009")
    check("diff: no rule errors", not res.errors, res.errors[:1])
    check("diff: DIF-009 notes the restarted node", d9 is not None and "hot-2" in d9.observed, d9 and d9.observed)
    check("diff: restarted node has no rate", d9 is not None and any(r[0] == "hot-2" and r[2] == "-" for r in rows_of(d9)),
          rows_of(d9))
    check("diff: only data nodes in DIF-009", d9 is not None and len(rows_of(d9)) == 4, rows_of(d9))
    rows = dict((r["id"], r) for r in res.bottleneck())
    check("diff: restart row picks the interval restart", rows["restart"]["verdict_id"] in ("interval", "recent"), rows["restart"])

    # per node change table in comparison mode
    nd = (res.diff_summary or {}).get("nodes") or {}
    nrows = dict((r[0], r) for r in nd.get("rows", []))
    check("diff: node table lists every node", set(nrows) >= {"hot-1", "hot-2", "warm-1", "frozen-1"}, list(nrows))
    check("diff: node table marks the restarted node", "hot-2" in nrows and "restarted" in nrows["hot-2"][2], nrows.get("hot-2"))
    check("diff: node table shows an indexing rate for a settled node", "hot-1" in nrows and nrows["hot-1"][8].endswith("/s"),
          nrows.get("hot-1"))
    for render in (text_report.console, text_report.markdown, html_report.render):
        out = render(res)
        check("diff: node table rendered by %s" % render.__name__, "Change per node" in out)

    # three bundles: throughput per interval (DIF-014)
    b1 = os.path.join(tmp, "s1")
    build(b1, restart_hot2=False, symptoms=False)
    w(b1, "manifest.json", dict(load(b1, "manifest.json"), collectionDate="2026-09-30T00:00:00Z"))
    ns = load(b1, "nodes_stats.json")
    for st in ns["nodes"].values():
        st["jvm"]["uptime_in_millis"] = 99 * DAY
        st["indices"]["indexing"]["index_total"] = max(0, st["indices"]["indexing"]["index_total"] - 9 * 10 ** 6)
    w(b1, "nodes_stats.json", ns)
    b2 = os.path.join(tmp, "s2")
    build(b2, restart_hot2=False, symptoms=False)
    w(b2, "manifest.json", dict(load(b2, "manifest.json"), collectionDate="2026-09-30T12:00:00Z"))
    ns = load(b2, "nodes_stats.json")
    for st in ns["nodes"].values():
        st["jvm"]["uptime_in_millis"] = 99 * DAY + 12 * HOUR
        st["indices"]["indexing"]["index_total"] = max(0, st["indices"]["indexing"]["index_total"] - 10 ** 6)
    w(b2, "nodes_stats.json", ns)
    cur3 = os.path.join(tmp, "s3")
    build(cur3, restart_hot2=False, symptoms=False)
    res3 = analyze(cur3, baseline=[b2, b1])
    f3 = findings(res3)
    d14 = f3.get("DIF-014")
    check("series: no rule errors", not res3.errors, res3.errors[:1])
    check("series: DIF-014 with two intervals", d14 is not None and len(rows_of(d14)) == 2, d14 and rows_of(d14))
    check("series: peak is the first interval (8M ops in 12h)", d14 is not None and "09-30 00:00" in d14.observed.split("Search")[0],
          d14 and d14.observed)
    check("series: comparison base is the latest baseline", res3.diff_summary and res3.diff_summary.get("hours")
          and abs(res3.diff_summary["hours"] - 12.0) < 0.01, res3.diff_summary and res3.diff_summary.get("hours"))
    check("series: one baseline gives no DIF-014", "DIF-014" not in findings(analyze(cur3, baseline=b2)))

    # storage by type and tier sizing
    root = os.path.join(tmp, "types")
    build(root, symptoms=True)
    f = findings(analyze(root))
    c5 = f.get("COST-005")
    types = set(r[0] for r in rows_of(c5))
    check("COST-005 classifies logs data streams and other indices", c5 is not None and "logs" in types and "other indices" in types,
          types)
    c6 = f.get("COST-006")
    sig = dict((r[0], r[7]) for r in rows_of(c6))
    check("COST-006 frozen tier under pressure (search rejections)", sig.get("frozen") == "pressure", sig)
    check("COST-006 hot tier under pressure (write rejections)", sig.get("hot") == "pressure", sig)
    root = os.path.join(tmp, "idle")
    build(root, symptoms=False, restart_hot2=False, hot2_index_total=10 ** 8)
    ns = load(root, "nodes_stats.json")
    for st in ns["nodes"].values():
        if st["name"] == "warm-1":
            st["os"]["cpu"]["percent"] = 3
            st["os"]["cpu"]["load_average"] = {"1m": 0.1, "5m": 0.1, "15m": 0.1}
            st["jvm"]["mem"]["heap_used_percent"] = 20
    w(root, "nodes_stats.json", ns)
    sig = dict((r[0], r[7]) for r in rows_of(findings(analyze(root)).get("COST-006")))
    check("COST-006 idle warm tier has large headroom", sig.get("warm") == "large headroom", sig)

    # HTML text filter is present
    out = html_report.render(analyze(root))
    check("HTML has the text filter", "id='fq'" in out and "qi.addEventListener" in out)


def run_review(tmp):
    """Cases from the review of a real 14-node bundle."""
    from esdiag import diff as diff_mod
    set_lang("en")

    # bottleneck: a cause on another tier does not explain the symptom
    root = os.path.join(tmp, "scope")
    build(root)
    ns = load(root, "nodes_stats.json")
    for st in ns["nodes"].values():
        st["jvm"]["mem"]["heap_used_percent"] = 95 if st["name"] == "warm-1" else 40
    w(root, "nodes_stats.json", ns)
    res = analyze(root)
    f = findings(res)
    rows = dict((r["id"], r) for r in res.bottleneck())
    check("review: JVM-001 names warm-1 only", f.get("JVM-001") is not None and f["JVM-001"].affected == ["warm-1"],
          f.get("JVM-001") and f["JVM-001"].affected)
    check("review: warm heap is not an ingest cause for hot rejections", "JVM-001" not in rows["ingest"]["causes"], rows["ingest"])
    check("review: nor a search cause for frozen queueing", "JVM-001" not in rows["search"]["causes"], rows["search"])
    check("review: same-tier cause still counts (PERF-012 on hot-2)", "PERF-012" in rows["ingest"]["causes"], rows["ingest"])
    ns = load(root, "nodes_stats.json")
    for st in ns["nodes"].values():
        if st["name"] == "frozen-1":
            st["jvm"]["mem"]["heap_used_percent"] = 95
    w(root, "nodes_stats.json", ns)
    rows = dict((r["id"], r) for r in analyze(root).bottleneck())
    check("review: frozen heap is a search cause for frozen queueing", "JVM-001" in rows["search"]["causes"], rows["search"])

    # PERF-013: a busy frozen pool without queued searches is how frozen works
    root = os.path.join(tmp, "frz")
    build(root, symptoms=False, restart_hot2=False)
    ns = load(root, "nodes_stats.json")
    for st in ns["nodes"].values():
        if st["name"] == "frozen-1":
            st["os"]["cpu"]["percent"] = 5
            st["thread_pool"]["search"] = {"threads": 13, "active": 13, "queue": 0, "rejected": 0}
    w(root, "nodes_stats.json", ns)
    check("review: no PERF-013 on a frozen node without a queue", "PERF-013" not in findings(analyze(root)))
    for st in ns["nodes"].values():
        if st["name"] == "frozen-1":
            st["thread_pool"]["search"]["queue"] = 3
    w(root, "nodes_stats.json", ns)
    p13 = findings(analyze(root)).get("PERF-013")
    check("review: PERF-013 on a frozen node with a queue", p13 is not None and p13.severity == Severity.WARNING, p13)

    # SET-005 compares nodes of the same tier only
    root = os.path.join(tmp, "set5")
    build(root, symptoms=False, restart_hot2=False)
    ni = load(root, "nodes.json")
    procs = {"hot-1": "4.0", "hot-2": "4.0", "warm-1": "2.0", "frozen-1": "0.5"}
    for info in ni["nodes"].values():
        info["settings"] = dict(info.get("settings") or {}, node={"processors": procs[info["name"]]})
    w(root, "nodes.json", ni)
    check("review: SET-005 not raised for different tiers", "SET-005" not in findings(analyze(root)))
    for info in ni["nodes"].values():
        if info["name"] == "hot-2":
            info["settings"]["node"]["processors"] = "3.0"
    w(root, "nodes.json", ni)
    s5 = findings(analyze(root)).get("SET-005")
    check("review: SET-005 raised within the hot tier", s5 is not None and rows_of(s5) and rows_of(s5)[0][1] == "hot",
          s5 and rows_of(s5))

    # DIF-008: data moving between nodes of one tier is not growth
    base = os.path.join(tmp, "d8b")
    build(base, symptoms=False, restart_hot2=False)
    w(base, "manifest.json", dict(load(base, "manifest.json"), collectionDate="2026-09-30T12:00:00Z"))
    cur = os.path.join(tmp, "d8c")
    build(cur, symptoms=False, restart_hot2=False)
    ns = load(cur, "nodes_stats.json")
    nb = load(base, "nodes_stats.json")
    for doc, delta in ((nb, 0), (ns, 1)):
        for st in doc["nodes"].values():
            if st["name"] in ("hot-1", "hot-2"):
                avail = 500 * GB + (1 if st["name"] == "hot-1" else -1) * delta * 200 * GB
                st["fs"]["total"] = {"total_in_bytes": 1000 * GB, "available_in_bytes": avail, "free_in_bytes": avail}
    w(base, "nodes_stats.json", nb)
    w(cur, "nodes_stats.json", ns)
    d8 = findings(analyze(cur, baseline=base)).get("DIF-008")
    check("review: DIF-008 judges the tier total (one hot node up, one down)", d8 is not None and d8.severity == Severity.INFO
          and "hot no growth" in d8.observed, d8 and (d8.severity, d8.observed))
    check("review: DIF-008 keeps the node rows and adds a tier row", d8 is not None and any(r[0] == "hot-2" for r in rows_of(d8))
          and any(r[0] == "hot tier total" for r in rows_of(d8)), d8 and rows_of(d8))

    # node change table: equal display means no arrow
    pct = lambda v: "%.0f%%" % v
    check("review: 1.2% vs 1.1% shows '='", diff_mod._cell(1.2, 1.1, pct, 5) == "1% =", diff_mod._cell(1.2, 1.1, pct, 5))
    check("review: shard count shows as an integer", diff_mod._cell(0, 0, lambda v: str(v), 5) == "0 =")

    # COST-004: a write target on warm does not make warm a landing tier when hot exists
    root = os.path.join(tmp, "land")
    b = Bundle()
    b.index(".ds-logs-h-default-2026.09.29-000001", 50 * GB, M, node="hot-1")
    b.stream("logs-h-default", [".ds-logs-h-default-2026.09.29-000001"])
    b.index(".ds-logs-w-default-2026.09.01-000001", GB, M, node="warm-1")
    b.stream("logs-w-default", [".ds-logs-w-default-2026.09.01-000001"])
    b.index("seed", GB, M, node="hot-1")
    for name, c in ((".ds-logs-h-default-2026.09.29-000001", COLLECTED_MS - 2 * DAY),
                    (".ds-logs-w-default-2026.09.01-000001", COLLECTED_MS - 30 * DAY), ("seed", COLLECTED_MS - 30 * DAY)):
        b.settings[name]["settings"]["index"]["creation_date"] = str(c)
    b.write(root)
    c4 = findings(analyze(root)).get("COST-004")
    check("review: COST-004 landing tier is hot only", c4 is not None and "Landing tier hot (" in c4.observed,
          c4 and c4.observed)

    # DIF-014: an interval from another cluster or with few matching nodes is not rated
    b0 = os.path.join(tmp, "s0")
    shutil.copytree(os.path.join(tmp, "s1"), b0)
    w(b0, "manifest.json", dict(load(b0, "manifest.json"), collectionDate="2026-09-29T20:00:00Z"))
    ni = load(b0, "nodes.json")
    ns = load(b0, "nodes_stats.json")
    for doc in (ni, ns):
        for v in doc["nodes"].values():
            if v["name"] != "hot-1":
                v["name"] = "other-" + v["name"]
    w(b0, "nodes.json", ni)
    w(b0, "nodes_stats.json", ns)
    res = analyze(os.path.join(tmp, "s3"), baseline=[os.path.join(tmp, "s2"), os.path.join(tmp, "s1"), b0])
    d14 = findings(res).get("DIF-014")
    check("review: DIF-014 shows the unmatched interval as not rated", d14 is not None
          and any(r[0].startswith("09-29 20:00") and r[2] == "-" for r in rows_of(d14)), d14 and rows_of(d14))
    check("review: DIF-014 says one interval was not rated", d14 is not None and "1 interval not rated" in d14.observed,
          d14 and d14.observed)
    check("review: unmatched interval is not the off-peak", d14 is not None and "lowest 09-29" not in d14.observed,
          d14 and d14.observed)


def main():
    tmp = tempfile.mkdtemp()
    try:
        for lang in ("ko", "en"):
            run_lang(lang, tmp)
        run_variants(tmp)
        run_review(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        set_lang("ko")
    for f in FAILS:
        print("FAIL " + f)
    print("bottleneck and cost checks: %d run, %d failed" % (N[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
