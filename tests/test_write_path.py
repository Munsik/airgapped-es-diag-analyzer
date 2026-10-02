#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checks for the write path and operations findings added in 0.13.0. No external bundle needed (synthetic data).

Covers PERF-012 (flush/refresh/merge averages), OS-007 (most nodes restarted), SHD-016 (write-target shard skew),
IDX-014 (indexing throttled), IDX-015 (uncommitted translog, with the 8.8 default change), CLU-017 (long tasks grouped
by action), MAP-004 ordering and template owner, and DIF-013 (bundles from different clusters).
Every case runs in both languages and the reports are rendered.

    python3 tests/test_write_path.py
"""
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from esdoctor.engine import analyze  # noqa: E402
from esdoctor.i18n import set_lang  # noqa: E402
from esdoctor.model import Severity  # noqa: E402
from esdoctor.report import html as html_report  # noqa: E402
from esdoctor.report import text as text_report  # noqa: E402
from test_logsdb import Bundle, GB, M, w  # noqa: E402

HANGUL = re.compile(u"[가-힣]")
FAILS, N = [], [0]
NEW_IDS = ("PERF-012", "OS-007", "SHD-016", "IDX-014", "IDX-015", "CLU-017", "MAP-004", "DIF-013")


def check(name, cond, detail=""):
    N[0] += 1
    if not cond:
        FAILS.append(name + (" - " + str(detail) if detail else ""))


def load(root, rel):
    with open(os.path.join(root, rel)) as fh:
        return json.load(fh)


def build(root, version="9.4.4", uuid="uuid-A", name="c1", restart=False):
    b = Bundle(version=version)
    b.policies["p"] = {"policy": {"phases": {"hot": {"actions": {"rollover": {"max_primary_shard_size": "50gb"}}},
                                             "delete": {"min_age": "30d", "actions": {"delete": {}}}}},
                       "in_use_by": {"indices": [], "data_streams": ["logs-app-default"]}}
    # write index of logs-app-default: 6 primaries on hot-1 only (write hotspot in the hot tier)
    ds = [".ds-logs-app-default-2026.09.01-000001", ".ds-logs-app-default-2026.09.02-000002"]
    b.index(ds[0], 5 * GB, 10 * M, "logsdb", policy="p", node="hot-2")
    b.index(ds[1], 2 * GB, 1 * M, "logsdb", policy="p", pri=6, node="hot-1")
    b.stream("logs-app-default", ds, policy="p", index_mode="logsdb")
    # throttled now, throttled before, translog over the threshold
    b.index("throttled-now", GB, M, node="hot-2")
    b.index("throttled-past", GB, M, node="hot-2")
    b.index("tlog-big", GB, M, node="hot-2")
    b.index("tlog-custom", GB, M, node="hot-2")
    b.settings["tlog-custom"]["settings"]["index"]["translog"] = {"flush_threshold_size": "1gb"}
    b.stats[ds[1]]["total"]["indexing"] = {"index_total": 10 ** 6}
    b.stats["throttled-now"]["total"]["indexing"] = {"is_throttled": True, "throttle_time_in_millis": 5000}
    b.stats["throttled-past"]["total"]["indexing"] = {"is_throttled": False, "throttle_time_in_millis": 9000}
    b.stats["throttled-past"]["total"]["merges"] = {"total_throttled_time_in_millis": 70000}
    b.stats["tlog-big"]["total"]["translog"] = {"uncommitted_size_in_bytes": 12 * GB}     # 1 copy, default 10GB
    b.stats["tlog-custom"]["total"]["translog"] = {"uncommitted_size_in_bytes": 2 * GB}    # 1 copy, custom 1GB
    b.write(root)

    # second hot node, write latency counters, restart, uuid/name
    ni, ns = load(root, "nodes.json"), load(root, "nodes_stats.json")
    hot1 = [k for k, v in ni["nodes"].items() if v["name"] == "hot-1"][0]
    import copy
    ni["nodes"]["node99XXXXXXXXXXXXXXXXXX"] = dict(copy.deepcopy(ni["nodes"][hot1]), name="hot-2")
    ns["nodes"]["node99XXXXXXXXXXXXXXXXXX"] = dict(copy.deepcopy(ns["nodes"][hot1]), name="hot-2")
    for nid, st in ns["nodes"].items():
        slow = st["name"] == "hot-1"
        st["indices"] = {"flush": {"total": 1000, "total_time_in_millis": 1000 * (1500 if slow else 100)},
                         "refresh": {"total": 1000, "total_time_in_millis": 1000 * (50 if slow else 5)},
                         "merges": {"total": 1000, "total_time_in_millis": 1000 * 1000}}
        st["jvm"]["uptime_in_millis"] = 3600 * 1000 if restart else 10 ** 10
        st["indices"]["indexing"] = {"index_total": 10 ** 7 if st["name"].startswith("hot") else 1000}
        if st["name"] == "warm-1":       # force merges and an idle write index: long merges, almost no indexing
            st["indices"]["merges"]["total_time_in_millis"] = 1000 * 60000
        if st["name"] == "frozen-1":     # container with host load but idle CPU
            st["os"] = {"cpu": {"percent": 1, "load_average": {"1m": 4.0, "5m": 4.0, "15m": 4.0}},
                        "cgroup": {"cpu": {"stat": {"number_of_elapsed_periods": 100, "number_of_times_throttled": 0}}}}
    w(root, "nodes.json", ni)
    w(root, "nodes_stats.json", ns)
    w(root, "version.json", {"cluster_name": name, "cluster_uuid": uuid, "version": {"number": version}})
    # tasks: one write task over 1h on two nodes, one search over 5 minutes, one monitor task under 24h
    w(root, "tasks.json", {"nodes": {
        hot1: {"name": "hot-1", "tasks": {
            "a:1": {"action": "indices:data/write/reindex", "running_time_in_nanos": 2 * 3600 * 10 ** 9, "description": "reindex x"},
            "a:2": {"action": "indices:data/read/search", "running_time_in_nanos": 10 * 60 * 10 ** 9, "description": "q"},
            "a:3": {"action": "cluster:monitor/nodes/stats", "running_time_in_nanos": 2 * 3600 * 10 ** 9}}},
        "node99XXXXXXXXXXXXXXXXXX": {"name": "hot-2", "tasks": {
            "b:1": {"action": "indices:data/write/reindex", "running_time_in_nanos": 3 * 3600 * 10 ** 9, "description": "reindex y"}}}}})
    # mappings: an integration index with ignore_dynamic_beyond_limit, and a custom one without it
    b.settings = load(root, "settings.json")
    fields = dict(("f%03d" % i, {"type": "keyword"}) for i in range(95))
    w(root, "mapping.json", {
        ds[0]: {"mappings": {"properties": fields}},
        "custom-wide": {"mappings": {"properties": fields}},
        "partial-mounted-wide": {"mappings": {"properties": fields}}})
    b.settings[ds[0]]["settings"]["index"]["mapping"] = {"total_fields": {"limit": "100", "ignore_dynamic_beyond_limit": "true"}}
    b.settings["custom-wide"] = {"settings": {"index": {"number_of_shards": "1", "number_of_replicas": "0",
                                                        "mapping": {"total_fields": {"limit": "100"}}}}}
    b.settings["partial-mounted-wide"] = {"settings": {"index": {
        "number_of_shards": "1", "mapping": {"total_fields": {"limit": "100"}},
        "store": {"type": "snapshot", "snapshot": {"partial": "true", "snapshot_name": "s"}}}}}
    w(root, "settings.json", b.settings)
    w(root, "index_templates.json", {"index_templates": [
        {"name": "logs-app-default-tpl", "index_template": {"index_patterns": ["logs-app-*"],
                                                            "_meta": {"package": {"name": "app"}, "managed_by": "fleet"}}}]})


def findings(res):
    return dict((f.id, f) for f in res.findings)


def run_lang(lang, tmp):
    set_lang(lang)
    pre = "[%s] " % lang
    root = os.path.join(tmp, "a-" + lang)
    build(root)
    res = analyze(root)
    check(pre + "no rule errors", not res.errors, [e["rule"] + ": " + e["error"].strip().splitlines()[-1] for e in res.errors])
    f = findings(res)

    p12 = f.get("PERF-012")
    check(pre + "PERF-012 warning (flush 1.5s on hot-1)", p12 is not None and p12.severity == Severity.WARNING)
    check(pre + "PERF-012 lists hot-1 only", p12 and [r[0] for r in p12.evidence["rows"]] == ["hot-1"],
          p12 and p12.evidence["rows"])
    check(pre + "PERF-012 skips frozen", p12 and not any(r[0] == "frozen-1" for r in p12.evidence["rows"]))
    check(pre + "PERF-012 skips warm (force merges, no write targets)",
          p12 and not any(r[0] == "warm-1" for r in p12.evidence["rows"]))
    o1 = f.get("OS-001")
    check(pre + "OS-001 idle container node is Info only", o1 is not None and o1.severity == Severity.INFO
          and "frozen-1" in (o1.observed or ""), o1 and (o1.severity, o1.observed))

    s16 = f.get("SHD-016")
    check(pre + "SHD-016 warning (write shards on hot-1)", s16 is not None and s16.severity == Severity.WARNING)
    check(pre + "SHD-016 top row is hot-1", s16 and s16.evidence["rows"][0][1] == "hot-1", s16 and s16.evidence["rows"])

    i14 = f.get("IDX-014")
    check(pre + "IDX-014 warning (throttled now)", i14 is not None and i14.severity == Severity.WARNING)
    if i14:
        names = [r[0] for r in i14.evidence["rows"]]
        check(pre + "IDX-014 lists the current one first", names[:2] == ["throttled-now", "throttled-past"], names)

    i15 = f.get("IDX-015")
    check(pre + "IDX-015 warning", i15 is not None and i15.severity == Severity.WARNING)
    if i15:
        names = sorted(r[0] for r in i15.evidence["rows"])
        check(pre + "IDX-015 lists default and custom threshold", names == ["tlog-big", "tlog-custom"], names)

    c17 = f.get("CLU-017")
    check(pre + "CLU-017 warning (write task over 1h)", c17 is not None and c17.severity == Severity.WARNING)
    if c17:
        acts = [r[0] for r in c17.evidence["rows"]]
        check(pre + "CLU-017 groups by action", acts == ["indices:data/write/reindex", "indices:data/read/search"], acts)
        check(pre + "CLU-017 counts 2 reindex tasks", c17.evidence["rows"][0][2] == 2, c17.evidence["rows"][0])
        check(pre + "CLU-017 hides monitor task under 24h", "cluster:monitor/nodes/stats" not in acts)

    m4 = f.get("MAP-004")
    check(pre + "MAP-004 warning (custom index without ignore)", m4 is not None and m4.severity == Severity.WARNING)
    if m4:
        rows = m4.evidence["rows"]
        check(pre + "MAP-004 lists the index without ignore first", rows[0][0] == "custom-wide", rows)
        check(pre + "MAP-004 shows the Fleet package", any(r[5] == "fleet:app" for r in rows), rows)
        check(pre + "MAP-004 skips searchable snapshot mounts", not any(r[0] == "partial-mounted-wide" for r in rows), rows)
    i6 = f.get("IDX-006")
    check(pre + "IDX-006 not raised without failures", i6 is None)

    check(pre + "no OS-007 without a restart", "OS-007" not in f)

    try:
        text_report.console(res, show_ok=True) + text_report.markdown(res, show_ok=True) + html_report.render(res)
        check(pre + "reports render", True)
    except Exception as exc:  # noqa: BLE001
        check(pre + "reports render", False, repr(exc))

    # restart + comparison with another cluster
    root2 = os.path.join(tmp, "b-" + lang)
    build(root2, uuid="uuid-B", restart=True)
    res2 = analyze(root2, baseline=root)
    f2 = findings(res2)
    check(pre + "OS-007 warning when all nodes restarted", "OS-007" in f2 and f2["OS-007"].severity == Severity.WARNING)
    check(pre + "DIF-013 warning for a different cluster_uuid", "DIF-013" in f2 and f2["DIF-013"].severity == Severity.WARNING)
    root3 = os.path.join(tmp, "c-" + lang)
    build(root3)
    res3 = analyze(root3, baseline=root)
    check(pre + "no DIF-013 for the same cluster", "DIF-013" not in findings(res3))
    check(pre + "no rule errors in compare mode", not res2.errors and not res3.errors)

    if lang == "en":
        for res_ in (res, res2):
            for x in res_.findings:
                if x.id.split(".")[0] not in NEW_IDS:
                    continue
                text = " ".join([x.title, x.observed or "", x.impact or "", x.recommend or ""] +
                                [str(c) for c in (x.evidence or {}).get("columns", [])])
                check(pre + "%s has no Hangul" % x.id, not HANGUL.search(text), HANGUL.findall(text)[:5])
                check(pre + "%s has no dash" % x.id, not re.search(u"[–—]", text))
                check(pre + "%s has no plural marker" % x.id, not re.search(r"\[[a-z ]+\|[a-z ]+\]", text))


def run_variants(tmp):
    set_lang("en")
    # Before 8.8 the default flush threshold is 512MB: a 1GB uncommitted translog is above it
    root = os.path.join(tmp, "v87")
    build(root, version="8.7.1")
    st = load(root, "indices_stats.json")
    st["indices"]["throttled-past"]["total"]["translog"] = {"uncommitted_size_in_bytes": GB}
    w(root, "indices_stats.json", st)
    f = findings(analyze(root))
    names = [r[0] for r in f["IDX-015"].evidence["rows"]] if "IDX-015" in f else []
    check("8.7: 1GB uncommitted is above the old 512MB default", "throttled-past" in names, names)
    root = os.path.join(tmp, "v94")
    build(root)
    st = load(root, "indices_stats.json")
    st["indices"]["throttled-past"]["total"]["translog"] = {"uncommitted_size_in_bytes": GB}
    w(root, "indices_stats.json", st)
    f = findings(analyze(root))
    names = [r[0] for r in f["IDX-015"].evidence["rows"]] if "IDX-015" in f else []
    check("9.4: 1GB uncommitted is under the 10GB default", "throttled-past" not in names, names)


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
    print("write path checks: %d run, %d failed" % (N[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
