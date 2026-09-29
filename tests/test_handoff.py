#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Elastic 공식 Support 팀 요약(--support-summary)과 마스킹 검증. 외부 번들 불필요(합성 데이터).

카나리 식별자를 번들 곳곳(클러스터명, 노드명, 호스트, IP, 경로, 인증서, 라이선스, 저장소, 인덱스, 로그, hot threads)에
심고, 요약 어디에도 남지 않는지 단계별로 확인한다.

    python3 tests/test_handoff.py
"""
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from esdiag.engine import analyze  # noqa: E402
from esdiag.mask import Masker  # noqa: E402
from esdiag.report import handoff  # noqa: E402

FAILS, N = [], [0]

CLUSTER = "zetacorp-prod-cluster"
NODES = ["zetadata-node-01", "zetadata-node-02"]
HOSTS = ["zetahost01.zetacorp.internal", "zetahost02.zetacorp.internal"]
IPS = ["10.77.31.11", "10.77.31.12"]
INDEX = "zetasecret-orders-2026.09"
PATH_DATA = "/zetavol/esdata"
CERT_DN = "CN=zetacert.zetacorp.internal,OU=zetaorg,O=ZetaCorp"
LICENSEE = "ZetaCorp Holdings"
REPO_BUCKET = "zeta-snapshots-bucket"
LOG_SAMPLE = "zetalogtoken failed to connect to 10.77.31.99"
CANARY_ALWAYS = [CLUSTER] + NODES + HOSTS + IPS + [PATH_DATA, "zetacert", LICENSEE, REPO_BUCKET, "10.77.31.99"]
CANARY_STRICT_ONLY = [INDEX]
CANARY_RAW = ["zetalogtoken", "zetahotstack"]


def check(name, cond, detail=""):
    N[0] += 1
    if not cond:
        FAILS.append(name + (" — " + str(detail) if detail else ""))


def w(root, rel, data):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(data if isinstance(data, str) else json.dumps(data))


def build(root):
    w(root, "manifest.json", {"diagVersion": "9.4.1", "collectionDate": "2026-09-29T00:00:00Z",
                              "diagnosticInputs": "DiagnosticInputs: {, diagType='local', mode='full'}"})
    w(root, "version.json", {"cluster_name": CLUSTER, "cluster_uuid": "AbCdEfGhIjKlMnOpQrStUv",
                             "version": {"number": "8.19.21"}})
    w(root, "cluster_health.json", {"cluster_name": CLUSTER, "status": "red", "number_of_nodes": 2,
                                    "number_of_data_nodes": 2, "active_primary_shards": 1, "active_shards": 1,
                                    "unassigned_shards": 3, "unassigned_primary_shards": 1,
                                    "active_shards_percent_as_number": 25.0})
    nodes, stats = {}, {}
    for i in range(2):
        nid = "zetaNodeId%02dXXXXXXXXXXXX" % i
        nodes[nid] = {"name": NODES[i], "host": HOSTS[i], "ip": IPS[i], "version": "8.19.21",
                      "transport_address": IPS[i] + ":9300", "roles": ["master", "data"],
                      "attributes": {"zone": "zetazone-a", "k8s_node_name": HOSTS[i]},
                      "settings": {"path": {"data": [PATH_DATA], "logs": "/zetavol/eslogs"},
                                   "node": {"name": NODES[i]}, "cluster": {"name": CLUSTER}},
                      "jvm": {"mem": {"heap_max_in_bytes": 4 * 1024 ** 3}},
                      "os": {"allocated_processors": 4, "mem": {"total_in_bytes": 16 * 1024 ** 3}}}
        stats[nid] = {"name": NODES[i], "host": HOSTS[i], "ip": IPS[i],
                      "jvm": {"mem": {"heap_used_percent": 96, "heap_max_in_bytes": 4 * 1024 ** 3,
                                      "heap_used_in_bytes": 4000000000}},
                      "fs": {"total": {"total_in_bytes": 100 * 1024 ** 3, "available_in_bytes": 3 * 1024 ** 3,
                                       "free_in_bytes": 3 * 1024 ** 3}}}
    w(root, "nodes.json", {"nodes": nodes})
    w(root, "nodes_stats.json", {"nodes": stats})
    w(root, "indices.json", [
        {"index": INDEX, "shard": "0", "prirep": "p", "state": "STARTED", "node": NODES[0], "store": "1000"},
        {"index": INDEX, "shard": "0", "prirep": "r", "state": "UNASSIGNED", "node": None, "ur": "NODE_LEFT",
         "ud": "node_left [%s] ip %s" % (NODES[1], IPS[1])}])
    w(root, "licenses.json", {"license": {"type": "enterprise", "issued_to": LICENSEE, "uid": "zeta-uid-1234",
                                          "issuer": "API"}})
    w(root, "ssl_certs.json", [{"path": "/zetavol/certs/node.p12", "format": "PKCS12", "alias": "n",
                                "subject_dn": CERT_DN, "serial_number": "1", "has_private_key": True,
                                "expiry": "2026-10-01T00:00:00.000Z"}])
    w(root, "repositories.json", [{"id": "zetarepo", "type": "s3",
                                   "settings": {"bucket": REPO_BUCKET, "base_path": "zetabase"}}])
    w(root, "logs/c_server.json", '{"@timestamp":"2026-09-29T00:00:00Z","log.level":"ERROR","message":"%s",'
                                  '"log.logger":"o.e.x","elasticsearch.node.name":"%s"}\n' % (LOG_SAMPLE, NODES[0]))
    w(root, "nodes_hot_threads.txt", "::: {%s}{x}{%s}\n   99.0%% [cpu=99%%] zetahotstack\n" % (NODES[0], IPS[0]))


def render(res, level):
    m = Masker(res.ctx, level=level)
    return m, handoff.render(res, m, level, "test")


def main():
    tmp = tempfile.mkdtemp()
    try:
        root = os.path.join(tmp, "b")
        build(root)
        res = analyze(root)
        check("합성 번들에서 치명·주의 판정이 나옴", len(res.priority()) > 0)

        # 1) 단계별 카나리 누출 검사
        for level in ("basic", "strict"):
            m, out = render(res, level)
            low = out.lower()
            for c in CANARY_ALWAYS + CANARY_RAW:
                check("%s: 카나리 미검출 %s" % (level, c), c.lower() not in low)
            if level == "strict":
                for c in CANARY_STRICT_ONLY:
                    check("strict: 인덱스명 미검출", c.lower() not in low)
            check("%s: 별칭이 사용됨" % level, "node-001" in out)
        # basic 은 인덱스명을 그대로 둔다(단계 구분 확인)
        _m, out_b = render(res, "basic")
        check("basic: 인덱스명은 유지(strict 에서만 가림)", "index-001" not in out_b)

        # 2) none 은 마스킹하지 않는다
        m, out_n = render(res, "none")
        check("none: 클러스터명 그대로", CLUSTER in out_n)
        check("none: 원문 열(샘플·스택)은 여전히 제외", "zetalogtoken" not in out_n and "zetahotstack" not in out_n)

        # 3) 매핑 왕복: 요약의 모든 별칭이 매핑에 있고, 복원하면 원래 이름이 나온다
        m, out = render(res, "strict")
        mp = m.mapping()
        check("매핑에 원본 노드명", any(v["original"] == NODES[0] for v in mp.values()))
        restored = out
        for alias in sorted(mp, key=len, reverse=True):
            restored = restored.replace(alias, mp[alias]["original"])
        check("복원 시 클러스터명 나타남", CLUSTER in restored)
        check("복원 시 노드명 나타남", NODES[0] in restored)
        # 같은 값은 항상 같은 별칭
        check("일관성: 같은 입력은 같은 별칭", m.text(NODES[0]) == m.text(NODES[0]) != NODES[0])

        # 4) fail closed: 마스킹이 실패하면 요약을 만들지 않는다
        class Broken(Masker):
            def text(self, s):
                return s
        bm = Broken(res.ctx, level="basic")
        raised = False
        try:
            handoff.render(res, bm, "basic", "test")
        except handoff.MaskLeak as exc:
            raised = bool(exc.leaks)
        check("마스킹 실패 시 MaskLeak", raised)

        # 5) CLI
        cli = [sys.executable, os.path.join(ROOT, "analyze.py"), root, "--quiet"]
        out_md = os.path.join(tmp, "sum.md")
        p = subprocess.run(cli + ["--support-summary", out_md], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        check("CLI: 기본 실행 종료코드 0", p.returncode == 0, p.stderr.decode("utf-8", "replace")[-300:])
        check("CLI: 요약 생성", os.path.isfile(out_md))
        mp_path = out_md + ".mask-map.json"
        check("CLI: 매핑 파일 생성", os.path.isfile(mp_path))
        if os.path.isfile(mp_path) and os.name == "posix":
            check("CLI: 매핑 파일 권한 0600", stat.S_IMODE(os.stat(mp_path).st_mode) == 0o600)
        if os.path.isfile(out_md):
            raw = io.open(out_md, encoding="utf-8").read()
            check("CLI: 요약에 카나리 없음", not any(c.lower() in raw.lower() for c in CANARY_ALWAYS + CANARY_RAW))
            check("CLI: 공식 Support 팀 문구", "Elastic 공식 Support 팀" in raw)

        out2 = os.path.join(tmp, "n.md")
        p = subprocess.run(cli + ["--support-summary", out2, "--mask", "none"], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
        check("CLI: --mask none 은 매핑 파일을 만들지 않음", p.returncode == 0 and not os.path.exists(out2 + ".mask-map.json"))

        p = subprocess.run(cli + ["--mask", "strict"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        check("CLI: --mask 단독 사용은 오류", p.returncode == 2, p.returncode)
        clean = os.path.join(tmp, "clean")
        os.makedirs(clean)
        p = subprocess.run(cli, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=clean)
        check("CLI: 옵션 없이는 요약·매핑 파일이 생기지 않음", p.returncode == 0 and not os.listdir(clean))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("handoff 검증: %d건 중 실패 %d건" % (N[0], len(FAILS)))
    for f in FAILS:
        print("  실패:", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
