#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checks for local/remote mode files (logs/, syscalls/, diagnostics.log) and report aggregation
(priority grouping, --no-ok counts). No external bundle needed (synthetic data).
Every check runs in both languages (ko and en); assertions use finding ids and severities only.

    python3 tests/test_local_mode.py
"""
import gzip
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from esdoctor.engine import Result, analyze  # noqa: E402
from esdoctor.i18n import set_lang  # noqa: E402
from esdoctor.model import Finding  # noqa: E402

FAILS, N = [], [0]


def check(name, cond, detail=""):
    N[0] += 1
    if not cond:
        FAILS.append(name + (" - " + str(detail) if detail else ""))


def w(root, rel, data):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    mode = "wb" if isinstance(data, bytes) else "w"
    with open(p, mode) as fh:
        fh.write(data)


def build(root, sysctl=None, limits=None, dmesg=None, logs=None, dlog=None):
    w(root, "manifest.json", json.dumps({"diagVersion": "9.4.1", "collectionDate": "2026-09-29T00:00:00Z",
                                         "diagnosticInputs": "DiagnosticInputs: {, diagType='local', mode='full'}",
                                         "Product Version": {"major": 8, "minor": 19, "patch": 21, "version": "8.19.21"}}))
    w(root, "cluster_health.json", json.dumps({"cluster_name": "t", "status": "green", "number_of_nodes": 1,
                                               "number_of_data_nodes": 1, "active_primary_shards": 1,
                                               "active_shards": 1, "unassigned_shards": 0}))
    w(root, "version.json", json.dumps({"version": {"number": "8.19.21"}}))
    if dlog is not None:
        w(root, "diagnostics.log", dlog)
    if sysctl is not None:
        w(root, "syscalls/sysctl.txt", sysctl)
    if limits is not None:
        w(root, "syscalls/proc-limit.txt", limits)
    if dmesg is not None:
        w(root, "syscalls/dmesg.txt", dmesg)
    for rel, data in (logs or {}).items():
        w(root, rel, data)


def ids(res):
    return {f.id: f.severity for f in res.findings}


LIM_OK = ("Limit                     Soft Limit           Hard Limit           Units     \n"
          "Max processes             4096                 4096                 processes \n"
          "Max open files            65535                65535                files     \n")
LIM_BAD = LIM_OK.replace("65535                65535", "4096                 4096 ")
JVM_LINE = ("[2026-09-29T12:01:41,607][INFO ][o.e.b.Elasticsearch      ] [n1] JVM arguments "
            "[-XX:+HeapDumpOnOutOfMemoryError, -XX:+ExitOnOutOfMemoryError]\n")


def run_lang(lang, tmp):
    set_lang(lang)
    pre = "[%s] " % lang
    tmp = os.path.join(tmp, lang)

    # 1) Good values: all SYS findings OK, and the JVM options line is not counted as an OOM
    r1 = os.path.join(tmp, "ok")
    build(r1, sysctl="vm.max_map_count = 1048576\nvm.swappiness = 1\n", limits=LIM_OK,
          dmesg="[ 0.0] Booting Linux\n", logs={"logs/c.log": JVM_LINE, "logs/c_server.json": JVM_LINE})
    s = ids(analyze(r1))
    check(pre + "good: SYS-001 OK", s.get("SYS-001") == "OK", s.get("SYS-001"))
    check(pre + "good: SYS-003 OK", s.get("SYS-003") == "OK", s.get("SYS-003"))
    check(pre + "good: SYS-004 OK", s.get("SYS-004") == "OK", s.get("SYS-004"))
    check(pre + "good: swappiness 1 gives no SYS-002", "SYS-002" not in s)
    check(pre + "JVM options line is not an OOM false positive", s.get("LOG-001") == "OK", s.get("LOG-001"))

    # 1b) Above the bootstrap minimum (262144) but below the official recommendation (1048576): info
    r1b = os.path.join(tmp, "mid")
    build(r1b, sysctl="vm.max_map_count = 262144\n")
    check(pre + "262144: SYS-001 INFO", ids(analyze(r1b)).get("SYS-001") == "INFO")

    # 1c) With --no-ok the finding counts still include OK
    full, hid = analyze(r1), analyze(r1, skip_ok=True)
    check(pre + "--no-ok: OK findings are not listed", all(f.severity != "OK" for f in hid.findings))
    check(pre + "--no-ok: counts are unchanged", full.counts == hid.counts, (full.counts, hid.counts))

    # 2) Values below the limits: critical
    r2 = os.path.join(tmp, "bad")
    build(r2, sysctl="vm.max_map_count = 65530\n", limits=LIM_BAD,
          dmesg="[ 9.1] Out of memory: Killed process 42 (java) total-vm:1kB\n")
    s = ids(analyze(r2))
    for k in ("SYS-001", "SYS-003", "SYS-004"):
        check("%sbelow limit: %s CRITICAL" % (pre, k), s.get(k) == "CRITICAL", s.get(k))
    r2b = os.path.join(tmp, "bad2")
    build(r2b, dmesg="[ 9.1] Out of memory: Killed process 42 (backup) total-vm:1kB\n")
    check(pre + "OOM kill of a non-java process is WARNING", ids(analyze(r2b)).get("SYS-004") == "WARNING")

    # 3) A real OOM exception is found even inside a gz file; the same text in _server.json is not counted twice
    r3 = os.path.join(tmp, "oom")
    exc = "[2026-09-28T01:00:00,000][ERROR][o.e.b.ElasticsearchUncaughtExceptionHandler] [n1] java.lang.OutOfMemoryError: Java heap space\n"
    build(r3, logs={"logs/c.log": JVM_LINE, "logs/c-2026-09-28-1.log.gz": gzip.compress(exc.encode()),
                    "logs/c_server.json": exc, "logs/gc.log": "OutOfMemoryError in gc file\n"})
    res = analyze(r3)
    f = [x for x in res.findings if x.id == "LOG-001"][0]
    check(pre + "OOM inside gz is found: CRITICAL", f.severity == "CRITICAL", f.severity)
    cnt = int(f.evidence["rows"][0][1].replace(",", ""))
    check(pre + "one OOM (one gz file), no double count, gc.log excluded", cnt == 1, cnt)

    # 4) Target node not matched: LOG-000 notice
    r4 = os.path.join(tmp, "nomatch")
    build(r4, dlog="ERROR Could not find the target node\nINFO Bypassing system calls\n")
    check(pre + "unmatched target node gives LOG-000", "LOG-000" in ids(analyze(r4)))

    # 4b) Action priority: findings with the same cause (unassigned shards) are grouped into one item
    fs = [Finding("CLU-001", "cluster", "WARNING", "yellow"), Finding("CLU-002", "cluster", "WARNING", "unassigned"),
          Finding("IDX-002", "shard", "WARNING", "replica excess"), Finding("SEC-002", "security", "CRITICAL", "security")]
    pr = Result(analyze(r4).ctx, fs, []).priority()
    check(pre + "priority grouping: 4 findings become 2 items", len(pr) == 2,
          [(f.id, [r.id for r in rel]) for f, rel in pr])
    check(pre + "priority grouping: critical first, CLU-001 leads its group",
          pr[0][0].id == "SEC-002" and pr[1][0].id == "CLU-001"
          and [r.id for r in pr[1][1]] == ["CLU-002", "IDX-002"])

    # 5) Broken input raises no rule error
    r5 = os.path.join(tmp, "junk")
    build(r5, sysctl="garbage\n= =\nvm.max_map_count = abc\n", limits="???\n", dmesg="\x00\x01",
          logs={"logs/c.log.gz": b"not gzip"})
    res = analyze(r5)
    check(pre + "broken input: no rule errors", not res.errors, res.errors)


def main():
    tmp = tempfile.mkdtemp()
    try:
        for lang in ("ko", "en"):
            run_lang(lang, tmp)
    finally:
        set_lang("ko")
        shutil.rmtree(tmp, ignore_errors=True)
    print("local mode checks: %d run, %d failed" % (N[0], len(FAILS)))
    for f in FAILS:
        print("  FAIL", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
