#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""local/remote 모드 전용 파일(logs/, syscalls/, diagnostics.log) 처리 검증. 외부 번들 불필요(합성 데이터).

    python3 tests/test_local_mode.py
"""
import gzip
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from esdiag.engine import analyze  # noqa: E402

FAILS, N = [], [0]


def check(name, cond, detail=""):
    N[0] += 1
    if not cond:
        FAILS.append(name + (" — " + str(detail) if detail else ""))


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


def main():
    tmp = tempfile.mkdtemp()
    try:
        # 1) 정상 값 → SYS 전부 정상, 기동 옵션 줄은 OOM 으로 잡히지 않음
        r1 = os.path.join(tmp, "ok")
        build(r1, sysctl="vm.max_map_count = 262144\nvm.swappiness = 1\n", limits=LIM_OK,
              dmesg="[ 0.0] Booting Linux\n", logs={"logs/c.log": JVM_LINE, "logs/c_server.json": JVM_LINE})
        s = ids(analyze(r1))
        check("정상: SYS-001 OK", s.get("SYS-001") == "OK", s.get("SYS-001"))
        check("정상: SYS-003 OK", s.get("SYS-003") == "OK", s.get("SYS-003"))
        check("정상: SYS-004 OK", s.get("SYS-004") == "OK", s.get("SYS-004"))
        check("정상: swappiness 1 은 SYS-002 없음", "SYS-002" not in s)
        check("JVM 옵션 줄은 OOM 오탐이 아님", s.get("LOG-001") == "OK", s.get("LOG-001"))

        # 2) 미달 값 → 치명
        r2 = os.path.join(tmp, "bad")
        build(r2, sysctl="vm.max_map_count = 65530\n", limits=LIM_BAD,
              dmesg="[ 9.1] Out of memory: Killed process 42 (java) total-vm:1kB\n")
        s = ids(analyze(r2))
        for k in ("SYS-001", "SYS-003", "SYS-004"):
            check("미달: %s CRITICAL" % k, s.get(k) == "CRITICAL", s.get(k))
        r2b = os.path.join(tmp, "bad2")
        build(r2b, dmesg="[ 9.1] Out of memory: Killed process 42 (backup) total-vm:1kB\n")
        check("java 아닌 프로세스 OOM kill 은 WARNING", ids(analyze(r2b)).get("SYS-004") == "WARNING")

        # 3) 실제 OOM 예외는 gz 안에 있어도 검출, 같은 내용의 _server.json 은 이중 집계 안 함
        r3 = os.path.join(tmp, "oom")
        exc = "[2026-09-28T01:00:00,000][ERROR][o.e.b.ElasticsearchUncaughtExceptionHandler] [n1] java.lang.OutOfMemoryError: Java heap space\n"
        build(r3, logs={"logs/c.log": JVM_LINE, "logs/c-2026-09-28-1.log.gz": gzip.compress(exc.encode()),
                        "logs/c_server.json": exc, "logs/gc.log": "OutOfMemoryError in gc file\n"})
        res = analyze(r3)
        f = [x for x in res.findings if x.id == "LOG-001"][0]
        check("gz 안의 OOM 검출 → CRITICAL", f.severity == "CRITICAL", f.severity)
        cnt = int(f.evidence["rows"][0][1].replace(",", ""))
        check("OOM 1건(gz 1개), 이중 집계·gc.log 제외", cnt == 1, cnt)

        # 4) 대상 노드 매칭 실패 → LOG-000 안내
        r4 = os.path.join(tmp, "nomatch")
        build(r4, dlog="ERROR Could not find the target node\nINFO Bypassing system calls\n")
        check("매칭 실패 안내 LOG-000", "LOG-000" in ids(analyze(r4)))

        # 5) 깨진 입력에도 룰 오류 없음
        r5 = os.path.join(tmp, "junk")
        build(r5, sysctl="garbage\n= =\nvm.max_map_count = abc\n", limits="???\n", dmesg="\x00\x01",
              logs={"logs/c.log.gz": b"not gzip"})
        res = analyze(r5)
        check("깨진 입력에 룰 오류 0", not res.errors, res.errors)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("local 모드 검증 %d개 중 실패 %d" % (N[0], len(FAILS)))
    for f in FAILS:
        print("  FAIL", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
