#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checks for the document limit, logsdb and force merge findings. No external bundle needed (synthetic data).

Covers SHD-008 / SHD-013 (200M documents and rollover), SHD-014 / SHD-015 (logsdb shard size),
IDX-013 (logs-*-* data streams not in logsdb mode), ILM-007 (max_primary_shard_docs above the limit),
ILM-008 (free disk for a one-segment force merge) and ILM-009 (long-running force merge).
Every case runs in both languages, and the reports are rendered to catch format errors.

    python3 tests/test_logsdb.py
"""
import json
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from esdoctor.engine import analyze  # noqa: E402
from esdoctor.i18n import set_lang  # noqa: E402
from esdoctor.model import Severity  # noqa: E402
from esdoctor.report import html as html_report  # noqa: E402
from esdoctor.report import text as text_report  # noqa: E402

GB = 1024 ** 3
M = 1000 * 1000
HANGUL = re.compile(u"[가-힣]")
FAILS, N = [], [0]
COLLECTED = "2026-10-01T00:00:00Z"
COLLECTED_MS = 1790812800000          # 2026-10-01T00:00:00Z


def check(name, cond, detail=""):
    N[0] += 1
    if not cond:
        FAILS.append(name + (" - " + str(detail) if detail else ""))


def w(root, rel, data):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(data if isinstance(data, str) else json.dumps(data))


class Bundle(object):
    def __init__(self, version="9.4.4"):
        self.version = version
        self.shards, self.settings, self.stats = [], {}, {}
        self.data_streams, self.policies, self.explain = [], {}, {}

    def index(self, name, size, docs, mode=None, pri=1, node="hot-1", policy=None, partial=False, set_mode=True):
        idx = {"number_of_shards": str(pri), "number_of_replicas": "1"}
        if mode and set_mode:
            idx["mode"] = mode
        if partial:
            idx["store"] = {"type": "snapshot", "snapshot": {"partial": "true", "snapshot_name": "s"}}
        if policy:
            idx["lifecycle"] = {"name": policy}
        self.settings[name] = {"settings": {"index": idx}}
        self.stats[name] = {"primaries": {"store": {"size_in_bytes": size * pri}, "docs": {"count": docs * pri, "deleted": 0}},
                            "total": {"store": {"size_in_bytes": size * pri * 2}, "docs": {"count": docs * pri * 2}}}
        for s in range(pri):
            self.shards.append({"index": name, "shard": str(s), "prirep": "p", "state": "STARTED",
                                "docs": str(docs), "store": str(size), "node": node})
        if policy:
            self.explain[name] = {"index": name, "managed": True, "policy": policy, "phase": "hot",
                                  "action": "complete", "step": "complete"}

    def stream(self, name, backing, policy=None, index_mode=None, write_mode_only_in_ds=False):
        ds = {"name": name, "indices": [{"index_name": b} for b in backing], "template": name + "-tpl",
              "status": "GREEN"}
        if policy:
            ds["ilm_policy"] = policy
        if index_mode:
            ds["index_mode"] = index_mode
        if write_mode_only_in_ds:
            for i in ds["indices"]:
                i["index_mode"] = index_mode
        self.data_streams.append(ds)

    def write(self, root):
        w(root, "manifest.json", {"diagVersion": "9.4.1", "collectionDate": COLLECTED,
                                  "diagnosticInputs": "DiagnosticInputs: {, diagType='api', mode='full'}"})
        w(root, "version.json", {"cluster_name": "c1", "version": {"number": self.version}})
        w(root, "cluster_health.json", {"cluster_name": "c1", "status": "green", "number_of_nodes": 3,
                                        "number_of_data_nodes": 3, "active_primary_shards": len(self.shards),
                                        "active_shards": len(self.shards), "unassigned_shards": 0,
                                        "active_shards_percent_as_number": 100.0})
        nodes, nstats = {}, {}
        for i, (name, roles, avail) in enumerate([
                ("hot-1", ["master", "data_hot", "data_content", "ingest"], 900 * GB),
                ("warm-1", ["master", "data_warm"], 50 * GB),
                ("frozen-1", ["master", "data_frozen"], 900 * GB)]):
            nid = "node%02dXXXXXXXXXXXXXXXXX" % i
            nodes[nid] = {"name": name, "host": name, "ip": "10.0.0.%d" % (i + 1), "version": self.version,
                          "roles": roles, "jvm": {"mem": {"heap_max_in_bytes": 8 * GB}},
                          "os": {"allocated_processors": 4, "available_processors": 4,
                                 "mem": {"total_in_bytes": 16 * GB}},
                          "thread_pool": {"force_merge": {"type": "fixed", "size": 1, "queue_size": -1}}}
            nstats[nid] = {"name": name, "roles": roles,
                           "jvm": {"mem": {"heap_used_percent": 40, "heap_max_in_bytes": 8 * GB,
                                           "heap_used_in_bytes": 3 * GB}},
                           "fs": {"total": {"total_in_bytes": 1000 * GB, "available_in_bytes": avail,
                                            "free_in_bytes": avail}},
                           "thread_pool": {"force_merge": {"threads": 1, "queue": 3, "active": 1, "rejected": 0}}}
            nstats[nid]["jvm"]["uptime_in_millis"] = 10 ** 8
            nstats[nid]["fs"]["io_stats"] = {"devices": [{"device_name": "d"}], "total": {
                "io_time_in_millis": [-2 * 10 ** 8, 9 * 10 ** 7, 10 ** 7][i], "read_operations": 1, "write_operations": 1}}
        w(root, "nodes.json", {"nodes": nodes})
        w(root, "nodes_stats.json", {"nodes": nstats})
        w(root, "indices.json", self.shards)
        w(root, "settings.json", self.settings)
        w(root, "indices_stats.json", {"indices": self.stats, "_all": {}})
        w(root, "licenses.json", {"license": {"type": "basic", "status": "active"}})
        w(root, "commercial/data_stream.json", {"data_streams": self.data_streams})
        w(root, "commercial/ilm_policies.json", self.policies)
        w(root, "commercial/ilm_explain.json", {"indices": self.explain})


def build_main():
    b = Bundle()
    hot_warm_ss = {"policy": {"phases": {
        "hot": {"actions": {"rollover": {"max_primary_shard_size": "50gb", "max_age": "30d"}}},
        "warm": {"min_age": "7d", "actions": {"forcemerge": {"max_num_segments": 1}}},
        "cold": {"min_age": "30d", "actions": {"searchable_snapshot": {"snapshot_repository": "r"}}},
        "delete": {"min_age": "90d", "actions": {"delete": {}}}}},
        "in_use_by": {"indices": [], "data_streams": ["logs-app-default", "logs-small-default", "logs-old-default"]}}
    b.policies["logs-hot-warm"] = hot_warm_ss
    b.policies["docs-too-high"] = {"policy": {"phases": {
        "hot": {"actions": {"rollover": {"max_primary_shard_docs": 300 * M, "max_primary_shard_size": "50gb"}}},
        "delete": {"min_age": "30d", "actions": {"delete": {}}}}},
        "in_use_by": {"indices": [], "data_streams": ["metrics-x-default"]}}

    # logs-app-default (logsdb): normal 200M rollover, late rollover, 35GB shard, write index over 200M
    app = [".ds-logs-app-default-2026.09.01-000001", ".ds-logs-app-default-2026.09.02-000002",
           ".ds-logs-app-default-2026.09.03-000003", ".ds-logs-app-default-2026.09.04-000004",
           ".ds-logs-app-default-2026.09.05-000005"]
    b.index(app[0], 12 * GB, 201 * M, "logsdb", policy="logs-hot-warm")             # normal: no finding
    b.index(app[1], 14 * GB, 230 * M, "logsdb", policy="logs-hot-warm")             # SHD-013
    b.index(app[2], 35 * GB, 150 * M, "logsdb", policy="logs-hot-warm", node="warm-1")  # SHD-014
    b.index(app[3], 55 * GB, 180 * M, "logsdb", policy="logs-hot-warm")             # SHD-003, not SHD-014
    b.index(app[4], 13 * GB, 205 * M, "logsdb", policy="logs-hot-warm")             # write index: SHD-008
    b.stream("logs-app-default", app, policy="logs-hot-warm", index_mode="logsdb")
    b.explain[app[2]].update(phase="warm", action="forcemerge", step="segment-count",
                             action_time_millis=COLLECTED_MS - 30 * 3600 * 1000,
                             step_time_millis=COLLECTED_MS - 29 * 3600 * 1000)  # ILM-009

    # logs-small-default (logsdb only in data_stream.json): 5 rollovers at 1-3GB on max_age → SHD-015 (per data stream)
    small = [".ds-logs-small-default-2026.09.0%d-00000%d" % (i, i) for i in range(1, 8)]
    for i, name in enumerate(small[:-2]):
        b.index(name, (1 + i % 3) * GB, (10 + i) * M, "logsdb", policy="logs-hot-warm", set_mode=False)
    b.index(small[5], 0, 0, "logsdb", policy="logs-hot-warm", set_mode=False)               # empty: left to SHD-011
    b.index(small[6], 1 * GB, 10 * M, "logsdb", policy="logs-hot-warm", set_mode=False)     # write index
    b.stream("logs-small-default", small, policy="logs-hot-warm", index_mode="logsdb", write_mode_only_in_ds=True)

    # logs-few-default: only 2 small rollovers → below ds_min_backing_indices, not SHD-015
    few = [".ds-logs-few-default-2026.09.01-000001", ".ds-logs-few-default-2026.09.02-000002",
           ".ds-logs-few-default-2026.09.03-000003"]
    for name in few:
        b.index(name, 2 * GB, 5 * M, "logsdb", policy="logs-hot-warm")
    b.stream("logs-few-default", few, policy="logs-hot-warm", index_mode="logsdb")

    # logs-old-default (standard, upgraded from 8.x): IDX-013; 35GB standard shard is not SHD-014
    old = [".ds-logs-old-default-2025.01.01-000001", ".ds-logs-old-default-2025.01.02-000002"]
    b.index(old[0], 35 * GB, 100 * M, None, policy="logs-hot-warm")
    b.index(old[1], 2 * GB, 1 * M, None, policy="logs-hot-warm")
    b.stream("logs-old-default", old, policy="logs-hot-warm")

    # metrics-x-default: policy with max_primary_shard_docs above 200M → ILM-007
    mx = [".ds-metrics-x-default-2026.09.01-000001"]
    b.index(mx[0], 5 * GB, 10 * M, None, policy="docs-too-high")
    b.stream("metrics-x-default", mx, policy="docs-too-high")

    # standalone index over 200M → SHD-008; partially mounted logsdb index is skipped
    b.index("legacy-big", 20 * GB, 250 * M, None)
    b.index("partial-.ds-logs-app-default-2026.01.01-000001", 40 * GB, 100 * M, "logsdb", partial=True, node="frozen-1")
    # mounted index outside any data stream, just above 200M: no writes, so not SHD-008
    b.index("partial-restored-.ds-logs-gone-default-2026.01.01-000001", 9 * GB, 201 * M, "logsdb", partial=True,
            node="frozen-1")
    return b


def findings(res):
    return dict((f.id, f) for f in res.findings)


def rows_of(f):
    return [r[0] for r in (f.evidence or {}).get("rows", [])] if f else []


def run_lang(lang, tmp):
    set_lang(lang)
    pre = "[%s] " % lang
    root = os.path.join(tmp, "main-" + lang)
    build_main().write(root)
    res = analyze(root)
    check(pre + "no rule errors", not res.errors, [e["rule"] + ": " + e["error"].strip().splitlines()[-1] for e in res.errors])
    f = findings(res)
    app = ".ds-logs-app-default-2026.09.0%d-00000%d"

    s8 = f.get("SHD-008")
    check(pre + "SHD-008 warning raised", s8 is not None and s8.severity == Severity.WARNING)
    check(pre + "SHD-008 lists the write index over 200M", app % (5, 5) in rows_of(s8), rows_of(s8))
    check(pre + "SHD-008 lists the standalone index", "legacy-big" in rows_of(s8), rows_of(s8))
    check(pre + "SHD-008 skips rolled-over indices", app % (1, 1) not in rows_of(s8) and app % (2, 2) not in rows_of(s8))

    s13 = f.get("SHD-013")
    # generation 2 ended late but the later generations 3 and 4 ended on time: history, so Info (0.14.3)
    check(pre + "SHD-013 raised as Info (older generation)", s13 is not None and s13.severity == Severity.INFO)
    check(pre + "SHD-013 lists the late rollover (230M)", app % (2, 2) in rows_of(s13), rows_of(s13))
    check(pre + "SHD-013 skips the normal rollover (201M)", app % (1, 1) not in rows_of(s13), rows_of(s13))

    s14 = f.get("SHD-014")
    check(pre + "SHD-014 info raised", s14 is not None and s14.severity == Severity.INFO)
    check(pre + "SHD-014 lists the 35GB logsdb index", app % (3, 3) in rows_of(s14), rows_of(s14))
    check(pre + "SHD-014 skips 50GB+ (SHD-003 covers it)", app % (4, 4) not in rows_of(s14))
    check(pre + "SHD-014 skips standard indices", not any("logs-old" in r for r in rows_of(s14)))
    check(pre + "SHD-014 skips partial mounts", not any(r.startswith("partial-") for r in rows_of(s14)))
    check(pre + "SHD-003 still flags the 55GB logsdb shard", "SHD-003" in f)
    if s14:
        cols = s14.evidence["columns"]
        row = s14.evidence["rows"][0]
        check(pre + "SHD-014 table has 7 columns", len(cols) == 7 and len(row) == 7, cols)
        check(pre + "SHD-014 shows the data stream", row[1] == "logs-app-default", row)
        check(pre + "SHD-014 shows bytes per doc", row[4].endswith("B") and row[4] != "-", row)

    check(pre + "SHD-008 skips a mounted index just above 200M",
          not any(r.startswith("partial-restored-") for r in rows_of(s8)), rows_of(s8))

    s15 = f.get("SHD-015")
    check(pre + "SHD-015 info raised (mode from data_stream.json)", s15 is not None and s15.severity == Severity.INFO)
    check(pre + "SHD-015 is per data stream", rows_of(s15) == ["logs-small-default"], rows_of(s15))
    if s15:
        row = s15.evidence["rows"][0]
        check(pre + "SHD-015 counts 5 small of 6 finished (empty one counted as finished only)", row[1] == "5 / 6", row)
        check(pre + "SHD-015 rollover condition estimated as max_age", "max_age" in row[4] and "30d" in row[4], row)

    i13 = f.get("IDX-013")
    check(pre + "IDX-013 info raised", i13 is not None and i13.severity == Severity.INFO)
    check(pre + "IDX-013 lists only logs-old-default", rows_of(i13) == ["logs-old-default"], rows_of(i13))

    i7 = f.get("ILM-007")
    check(pre + "ILM-007 info raised", i7 is not None and i7.severity == Severity.INFO)
    check(pre + "ILM-007 lists the policy", "docs-too-high" in rows_of(i7), rows_of(i7))

    i8 = f.get("ILM-008")
    check(pre + "ILM-008 warning raised", i8 is not None and i8.severity == Severity.WARNING)
    if i8:
        labels = [r[1] for r in i8.evidence["rows"]]
        check(pre + "ILM-008 warm forcemerge on the warm tier", any(l.startswith("warm: forcemerge") for l in labels), labels)
        check(pre + "ILM-008 searchable snapshot merge skipped after forcemerge",
              not any("searchable_snapshot" in l for l in labels), labels)
        check(pre + "ILM-008 node with least free disk is warm-1", all(r[5] == "warm-1" for r in i8.evidence["rows"]))

    i9 = f.get("ILM-009")
    check(pre + "ILM-009 info raised", i9 is not None and i9.severity == Severity.INFO)
    check(pre + "ILM-009 lists the index in forcemerge", app % (3, 3) in rows_of(i9), rows_of(i9))

    d8 = f.get("DISK-008")
    check(pre + "DISK-008 rates the 90% node", d8 is not None and d8.severity == Severity.WARNING and "warm-1" in (d8.observed or ""),
          d8 and d8.observed)
    if d8:
        bad = [r for r in d8.evidence["rows"] if r[0] == "hot-1"]
        check(pre + "DISK-008 negative counter shown as not determined", bad and not bad[0][2].endswith("%"), bad)
        check(pre + "DISK-008 negative counter not rated", "hot-1" not in (d8.observed or ""))

    # Rendering in this language
    try:
        out = text_report.console(res, show_ok=True) + text_report.markdown(res, show_ok=True) + html_report.render(res)
        ok = True
    except Exception as exc:  # noqa: BLE001
        out, ok = "", False
        check(pre + "reports render", False, repr(exc))
    if ok:
        check(pre + "reports render", True)
    new_ids = ("SHD-013", "SHD-014", "SHD-015", "IDX-013", "ILM-007", "ILM-008", "ILM-009")
    if lang == "en":
        for fid in new_ids:
            x = f.get(fid)
            if x:
                text = " ".join([x.title, x.observed or "", x.impact or "", x.recommend or ""] +
                                [str(c) for c in x.evidence["columns"]] + [str(c) for r in x.evidence["rows"] for c in r])
                check(pre + "%s has no Hangul" % fid, not HANGUL.search(text), HANGUL.findall(text)[:5])
                check(pre + "%s has no dash" % fid, not re.search(u"[–—]", text))
                check(pre + "%s has no unresolved plural marker" % fid, not re.search(r"\[[a-z ]+\|[a-z ]+\]", text), text[:200])


def run_variants(tmp):
    set_lang("en")
    # 8.x: no IDX-013
    b = build_main()
    b.version = "8.19.21"
    root = os.path.join(tmp, "v8")
    b.write(root)
    res = analyze(root)
    check("8.x: no IDX-013", "IDX-013" not in findings(res))
    check("8.x: no rule errors", not res.errors)

    # Healthy logsdb only: none of the new findings
    b = Bundle()
    b.policies["p"] = {"policy": {"phases": {"hot": {"actions": {"rollover": {"max_primary_shard_size": "50gb"}}},
                                             "delete": {"min_age": "30d", "actions": {"delete": {}}}}},
                       "in_use_by": {"indices": [], "data_streams": ["logs-ok-default"]}}
    ok = [".ds-logs-ok-default-2026.09.01-000001", ".ds-logs-ok-default-2026.09.02-000002"]
    b.index(ok[0], 12 * GB, 200 * M + 500000, "logsdb", policy="p")
    b.index(ok[1], 4 * GB, 60 * M, "logsdb", policy="p")
    b.stream("logs-ok-default", ok, policy="p", index_mode="logsdb")
    root = os.path.join(tmp, "healthy")
    b.write(root)
    res = analyze(root)
    ids = set(findings(res))
    for fid in ("SHD-008", "SHD-013", "SHD-014", "SHD-015", "IDX-013", "ILM-007", "ILM-008", "ILM-009"):
        check("healthy logsdb: no %s" % fid, fid not in ids)
    check("healthy logsdb: no rule errors", not res.errors)

    # No collection date: ILM-009 is not raised (age cannot be measured)
    b = build_main()
    root = os.path.join(tmp, "nodate")
    b.write(root)
    w(root, "manifest.json", {"diagVersion": "9.4.1"})
    res = analyze(root)
    check("no collection date: no ILM-009", "ILM-009" not in findings(res))


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
    print("logsdb checks: %d run, %d failed" % (N[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
