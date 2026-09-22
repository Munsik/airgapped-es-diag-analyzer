#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""계산 로직 검증. 외부 의존성 없이 실행된다.

    python3 tests/verify_logic.py [정상번들.zip]

번들을 주면 번들 기반 검증(룰 오류 0, 자기 비교 시 변화 0, 모든 판정의 근거 구분 매핑)까지 수행한다.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from esdiag.basis import _MAP, basis_of                      # noqa: E402
from esdiag.rules.guidance import _gc_logging_enabled        # noqa: E402
from esdiag.util import parse_bytes, parse_time_ms           # noqa: E402

GB, TB = 1024 ** 3, 1024 ** 4
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name + ((" — " + detail) if detail and not cond else ""))


class _FakeCtx(object):
    """watermark_used_pct 만 검증하기 위한 최소 컨텍스트."""
    def __init__(self, settings):
        self._s = settings
        self.t = {"disk_watermark_low_default": "85%", "disk_watermark_high_default": "90%",
                  "disk_watermark_flood_default": "95%"}

    def setting(self, key, default=None):
        return self._s.get(key, default)

    def watermark(self, kind):
        return self._s.get("cluster.routing.allocation.disk.watermark." + kind)


def test_units():
    check("parse_bytes 1.5tb", parse_bytes("1.5tb") == int(1.5 * TB))
    check("parse_bytes 150GB", parse_bytes("150GB") == 150 * GB)
    check("parse_bytes 숫자", parse_bytes(1024) == 1024)
    check("parse_time 30s", parse_time_ms("30s") == 30000)
    check("parse_time -1", parse_time_ms("-1") == -1)


def test_watermark():
    from esdiag.context import Context
    defaults = {
        "cluster.routing.allocation.disk.watermark.low": "85%",
        "cluster.routing.allocation.disk.watermark.high": "90%",
        "cluster.routing.allocation.disk.watermark.flood_stage": "95%",
        "cluster.routing.allocation.disk.watermark.low.max_headroom": "200GB",
        "cluster.routing.allocation.disk.watermark.high.max_headroom": "150GB",
        "cluster.routing.allocation.disk.watermark.flood_stage.max_headroom": "100GB",
    }
    fc = _FakeCtx(defaults)
    f = Context.watermark_used_pct
    # 1TB: 10% = 102.4GB < 150GB 이므로 비율 그대로 90%
    check("1TB high = 90%", abs(f(fc, "high", TB) - 90.0) < 0.01, str(f(fc, "high", TB)))
    # 10TB: 10% = 1024GB > 150GB 이므로 여유 150GB 기준 -> 98.535%
    exp = (1 - 150.0 / (10 * 1024)) * 100
    check("10TB high = headroom 적용", abs(f(fc, "high", 10 * TB) - exp) < 0.01,
          "%s vs %s" % (f(fc, "high", 10 * TB), exp))
    # 바이트 워터마크는 headroom 미적용
    fc2 = _FakeCtx({"cluster.routing.allocation.disk.watermark.high": "100gb",
                    "cluster.routing.allocation.disk.watermark.high.max_headroom": "-1"})
    exp2 = (1 - 100.0 / 1024) * 100
    check("바이트 워터마크 100gb @1TB", abs(f(fc2, "high", TB) - exp2) < 0.01)
    # 명시 설정으로 headroom 이 -1 이면 비율 그대로
    fc3 = _FakeCtx({"cluster.routing.allocation.disk.watermark.high": "80%",
                    "cluster.routing.allocation.disk.watermark.high.max_headroom": "-1"})
    check("명시 80%, headroom 해제 @10TB", abs(f(fc3, "high", 10 * TB) - 80.0) < 0.01)


def test_gc_log():
    es_default = ["-Xlog:disable", "-Xlog:all=warning:stderr:utctime,level,tags",
                  "-Xlog:gc*,gc+age=trace,safepoint:file=logs/gc.log:utctime,level,pid,tags:filecount=32,filesize=64m"]
    check("ES 기본 JVM 옵션 = GC 로그 켜짐", _gc_logging_enabled(es_default))
    check("disable 만 있으면 꺼짐", not _gc_logging_enabled(["-Xlog:disable", "-Xlog:all=warning:stderr"]))
    check("gc 로그가 disable 앞에 있으면 꺼짐",
          not _gc_logging_enabled(["-Xlog:gc*:file=gc.log", "-Xlog:disable"]))


def test_basis():
    check("DIF 는 비교 계산", basis_of("DIF-005") == "비교 계산")
    check("하위 ID 매핑", basis_of("CLU-004.disk") == basis_of("CLU-004"))


def test_bundle(path):
    from esdiag.engine import analyze
    r = analyze(path)
    check("정상 번들 룰 오류 0", not r.errors, str([e["rule"] for e in r.errors]))
    unmapped = sorted(set(f.id.split(".")[0] for f in r.findings
                          if f.id.split(".")[0] not in _MAP and not f.id.startswith("DIF")))
    check("모든 판정 ID 가 근거 구분에 등록됨", not unmapped, str(unmapped))
    check("모든 판정에 basis 부여", all(f.basis for f in r.findings))
    r2 = analyze(path, baseline=path)
    difs = [f.id for f in r2.findings if f.id.startswith("DIF")]
    check("자기 자신과 비교하면 변화 판정 0건", not difs, str(difs))
    check("비교 모드도 룰 오류 0", not r2.errors)
    base_ids = sorted((f.id, f.severity) for f in r.findings)
    same_ids = sorted((f.id, f.severity) for f in r2.findings if f.category != "변화 추세")
    check("비교 모드의 단일 번들 판정은 단독 분석과 동일", base_ids == same_ids)
    ids = [f.id for f in r.findings]
    check("ECH 번들: initial_master_nodes 는 참고로 하향",
          all(f.severity == "INFO" for f in r.findings if f.id == "CFG-005"))
    check("docker 설치: CFG-002 미적용", "CFG-002" not in ids)
    check("logsdb/time_series 인덱스는 codec 판정 제외",
          not any(f.id == "DISK-006" and any("logsdb" in str(row) or "time_series" in str(row)
                                             for row in (f.evidence or {}).get("rows", []))
                  for f in r.findings))


def test_settings_kb():
    from esdiag.settings_kb import compare, KB, DOCS
    ch, d, *_ = compare("indices.recovery.max_bytes_per_sec", "100mb")
    check("설정 비교: 40mb→100mb 는 증가", ch and d == "up")
    ch, d, *_ = compare("indices.recovery.max_bytes_per_sec", "40mb")
    check("설정 비교: 기본값과 같으면 변경 아님", not ch)
    ch, d, *_ = compare("cluster.routing.allocation.disk.watermark.high", "0.95")
    check("설정 비교: 90% → 0.95 는 방향 판정 불가 시 '변경'", ch and d in ("change", "up"))
    ch, d, *_ = compare("cluster.routing.allocation.exclude._name", "no_instances_excluded")
    check("설정 비교: ECH 표식 no_instances_excluded 는 기본값 취급", not ch)
    ch, d, *_ = compare("thread_pool.write.queue_size", "5000")
    check("설정 비교: queue 10000→5000 은 감소", ch and d == "down")
    ch, d, spec, dft, src = compare("some.unknown.setting", "x")
    check("설정 비교: 미등록 설정은 값만 보고", ch and spec is None and src == "미등록")
    check("지식 베이스: 모든 항목에 문서 키 존재", all(v["doc"] in DOCS for v in KB.values()))
    check("지식 베이스: kind 값 유효", all(v["kind"] in ("dynamic", "static") for v in KB.values()))


def test_kb_against_bundle(path):
    """KB 기본값을 ES 가 보고한 기본값과 대조. yml 에 명시된 키와 자동 산정 키만 불일치가 허용된다."""
    from esdiag.loader import Bundle
    from esdiag.settings_kb import KB, compare, AUTO_DEFAULT
    from esdiag.rules.settings import _flat
    b = Bundle(path)
    d = _flat((b.json("cluster_settings_defaults.json") or {}).get("defaults") or {})
    yml = set()
    for n in (b.json("nodes.json") or {}).get("nodes", {}).values():
        yml |= set(_flat(n.get("settings") or {}).keys())
    bad = []
    for k, spec in KB.items():
        if spec["scope"] == "index" or k not in d or k in yml or k in AUTO_DEFAULT:
            continue
        if compare(k, d[k])[0]:
            bad.append("%s: KB=%s ES=%s" % (k, spec["default"], d[k]))
    check("지식 베이스 기본값 = ES 보고 기본값(yml·자동 산정 제외)", not bad, "; ".join(bad))


def test_multitier(path):
    """다중 tier·롤오버·searchable snapshot 구성 재현(9.5 멀티 tier 고객 번들에서 드러난 오탐 회귀 방지)."""
    import json, shutil, tempfile, zipfile
    from esdiag.engine import analyze
    from esdiag.rules.runtime import _classify
    tmp = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(path) as z:
            z.extractall(tmp)
        root = [os.path.join(tmp, d) for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))][0]
        J = lambda n: json.load(open(os.path.join(root, n), encoding="utf-8"))
        W = lambda n, o: json.dump(o, open(os.path.join(root, n), "w", encoding="utf-8"))
        ni, ns = J("nodes.json"), J("nodes_stats.json")
        ids = list(ni["nodes"].keys())
        # 노드 0: hot 15GB, 노드 1: cold 7.5GB(다른 tier·다른 heap), 노드 2: frozen(디스크 90% = shared cache)
        roles = [["data_hot", "data_content", "master"], ["data_cold", "master"], ["data_frozen", "master"]]
        heaps = [15 * GB, 7.5 * GB, 2 * GB]
        # 번들 노드 수와 무관하게 모든 노드를 3개 tier 에 나눠 배정(tier 안에서는 heap 동일)
        for i, nid in enumerate(ids):
            k = min(i, 2) if len(ids) <= 3 else i % 3
            ni["nodes"][nid]["roles"] = roles[k]
            ns["nodes"][nid]["roles"] = roles[k]
            ns["nodes"][nid]["jvm"]["mem"]["heap_max_in_bytes"] = int(heaps[k])
        for i, nid in enumerate(ids):
            k = min(i, 2) if len(ids) <= 3 else i % 3
            node = ns["nodes"][nid]
            node["os"]["cpu"]["available_processors"] = 4                    # tier 안 CPU 동일
            ni["nodes"][nid].setdefault("os", {})["available_processors"] = 4
            ni["nodes"][nid]["os"]["allocated_processors"] = 4
            tot = node["fs"]["total"]["total_in_bytes"]
            # frozen 은 shared cache 로 90% 사용, 나머지는 50% 사용
            node["fs"]["total"]["available_in_bytes"] = int(tot * (0.099 if k == 2 else 0.5))
        W("nodes.json", ni); W("nodes_stats.json", ns)
        # 데이터 스트림: 과거 백킹 2개(write 차단, 하나는 partial 마운트) + write index 1개(차단 없음)
        st = J("settings.json")
        base = {"settings": {"index": {"number_of_shards": "1", "number_of_replicas": "1"}}}   # 번들과 무관한 최소 설정
        names = [".ds-logs-app-default-2026.01.01-000001", "partial-.ds-logs-app-default-2026.01.02-000002",
                 ".ds-logs-app-default-2026.01.03-000003"]
        for i, nm in enumerate(names):
            body = json.loads(json.dumps(base))
            body["settings"]["index"]["blocks"] = {"write": "true"} if i < 2 else {}
            if i == 1:
                body["settings"]["index"]["store"] = {"type": "snapshot", "snapshot": {"snapshot_name": "s1"}}
            st[nm] = body
        W("settings.json", st)
        ds = J(os.path.join("commercial", "data_stream.json"))
        ds.setdefault("data_streams", []).append({"name": "logs-app-default", "status": "GREEN",
                                                  "indices": [{"index_name": n} for n in names]})
        W(os.path.join("commercial", "data_stream.json"), ds)
        r = analyze(root)
        got = dict((f.id, f) for f in r.findings)
        check("다중 tier: 룰 오류 0", not r.errors, str([e["rule"] for e in r.errors]))
        check("frozen 노드 디스크 90%(shared cache)는 워터마크 초과가 아님",
              not any(i in got and got[i].severity in ("CRITICAL", "WARNING") for i in ("DISK-001", "DISK-002", "DISK-003")))
        check("tier 가 다르면 heap 차이는 불균일 판정 아님", "NODE-001" not in got and "NODE-003" in got)
        check("롤오버된 백킹·searchable snapshot 의 쓰기 차단은 정상",
              "IDX-008" not in got or got["IDX-008"].severity == "OK")
        # write index 에 차단을 걸면 치명
        st[names[2]]["settings"]["index"]["blocks"] = {"write": "true"}
        W("settings.json", st)
        r2 = analyze(root)
        g2 = dict((f.id, f) for f in r2.findings)
        check("현재 쓰기 대상(write index)의 쓰기 차단은 치명",
              "IDX-008" in g2 and g2["IDX-008"].severity == "CRITICAL")
        check(".ds- 백킹 인덱스는 사용자 인덱스", not r.ctx.is_system_index(".ds-logs-app-default-2026.01.01-000001"))
        check(".ds-.kibana 계열은 시스템 인덱스", r.ctx.is_system_index(".ds-.kibana-event-log-ds-2026-000001"))
        label, _h = _classify(["app/org.elasticsearch.grok@9.5.3/org.elasticsearch.grok.Grok.match(Grok.java:239)",
                               "org.elasticsearch.index.mapper.DocumentParser.parse"], "write_coordination")
        check("hot threads: 최상위 프레임 기준 분류(grok)", label == "ingest grok 파싱", str(label))
        label2, _h2 = _classify([
            "org.elasticsearch.xcontent.impl@9.5.3/org.elasticsearch.xcontent.provider.json.JsonXContentGenerator.copyCurrentStructure",
            "app/org.elasticsearch.server@9.5.3/org.elasticsearch.index.mapper.XContentDataHelper.cloneSubContext",
            "app/org.elasticsearch.server@9.5.3/org.elasticsearch.index.mapper.DocumentParserContext.addIgnoredFieldFromContext"],
            "write")
        check("hot threads: 맨 위가 JSON 복사여도 맥락(무시된 필드 저장)으로 분류", label2 and label2.startswith("문서 파싱"), str(label2))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_capacity_and_mounts(path):
    """hot tier 포화·주의 노드 표시·fully/partial 마운트 크기 판정·빈 write index 회귀 방지."""
    import json, shutil, tempfile, zipfile
    from esdiag.engine import analyze
    tmp = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(path) as z:
            z.extractall(tmp)
        root = [os.path.join(tmp, d) for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))][0]
        J = lambda n: json.load(open(os.path.join(root, n), encoding="utf-8"))
        W = lambda n, o: json.dump(o, open(os.path.join(root, n), "w", encoding="utf-8"))
        ni, ns = J("nodes.json"), J("nodes_stats.json")
        ids = list(ni["nodes"].keys())
        spec = [(["data_hot", "data_content"], 4, 4.5, 79), (["data_hot", "data_content"], 4, 5.32, 70)] + \
            [(["data_cold"], 4, 0.3, 5)] * max(1, len(ids) - 2)
        for nid, (roles, cpu, load, pct) in zip(ids, spec):
            ni["nodes"][nid]["roles"] = roles
            ns["nodes"][nid]["roles"] = roles
            ns["nodes"][nid]["os"]["cpu"].update({"available_processors": cpu, "percent": pct,
                                                  "load_average": {"1m": load, "5m": load, "15m": load}})
        W("nodes.json", ni); W("nodes_stats.json", ns)
        # 소형 샤드: restored-(fully mounted, 실제 크기) 60개 / partial-(캐시 크기) 60개 / 빈 write index 1개
        st, ist, sh = J("settings.json"), J("indices_stats.json"), J("indices.json")
        tmpl = next(iter(ist["indices"].values()))
        node0 = ni["nodes"][ids[2]]["name"]
        def add(name, size, docs, extra):
            st[name] = {"settings": {"index": dict({"number_of_shards": "1", "number_of_replicas": "0"}, **extra)}}
            b = json.loads(json.dumps(tmpl))
            b["primaries"]["store"]["size_in_bytes"] = size
            b["primaries"]["docs"] = {"count": docs, "deleted": 0}
            ist["indices"][name] = b
            sh.append({"index": name, "shard": "0", "prirep": "p", "state": "STARTED", "docs": str(docs),
                       "store": str(size), "node": node0})
        snap = {"store": {"type": "snapshot", "snapshot": {"snapshot_name": "s"}}}
        for i in range(60):
            add("restored-.ds-logs-x-default-2026.01.%02d-%06d" % (i % 28 + 1, i), 50 * 1024 ** 2, 1000, snap)
            add("partial-.ds-logs-y-default-2026.01.%02d-%06d" % (i % 28 + 1, i), 1024 ** 2, 1000,
                {"store": {"type": "snapshot", "snapshot": {"snapshot_name": "s", "partial": "true"}}})
        add(".ds-logs-z-default-2026.09.21-000009", 0, 0, {})
        for k in range(6):
            add("empty-legacy-%d" % k, 0, 0, {})
        ds = J(os.path.join("commercial", "data_stream.json"))
        ds.setdefault("data_streams", []).append({"name": "logs-z-default", "status": "GREEN",
                                                  "indices": [{"index_name": ".ds-logs-z-default-2026.09.21-000009"}]})
        W("settings.json", st); W("indices_stats.json", ist); W("indices.json", sh)
        W(os.path.join("commercial", "data_stream.json"), ds)
        # 원본 번들의 primary 중 partial 마운트(크기 판정 제외 대상)를 뺀 수 + 이번에 추가한 것 중 판정 대상 67개
        orig = [x for x in J("indices.json") if x.get("prirep") == "p"][:-127]
        def _partial(ix):
            snap = (((st.get(ix) or {}).get("settings") or {}).get("index") or {}).get("store") or {}
            return ix.startswith("partial-") or str((snap.get("snapshot") or {}).get("partial")).lower() == "true"
        base_pri = len([x for x in orig if not _partial(x.get("index", ""))])
        r = analyze(root)
        g = dict((f.id, f) for f in r.findings)
        check("용량: 룰 오류 0", not r.errors, str([e["rule"] for e in r.errors]))
        check("hot tier 전체 CPU 포화 판정(HOT-005)", "HOT-005.hot" in g)
        check("OS-001 이 주의 구간 노드도 표시", "OS-001" in g and "주의" in g["OS-001"].observed)
        check("소형 샤드: fully mounted 60개 포함·partial 60개 제외",
              "SHD-004" in g and ("primary 샤드 %d개" % (base_pri + 60 + 7)) in g["SHD-004"].observed,
              g["SHD-004"].observed if "SHD-004" in g else "없음")
        e = g.get("SHD-011")
        rows = [row[0] for row in (e.evidence or {}).get("rows", [])] if e else []
        check("빈 인덱스: 현재 write index 는 제외",
              e is not None and ".ds-logs-z-default-2026.09.21-000009" not in rows and
              all(("empty-legacy-%d" % k) in rows for k in range(6)), str(rows))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_partial_bundle(path):
    """핵심 파일만 있는 부분 번들: '미설정' 오탐이 없어야 한다."""
    import shutil
    import tempfile
    from esdiag.engine import analyze
    from esdiag.loader import Bundle
    src = Bundle(path)
    tmp = tempfile.mkdtemp()
    try:
        for name in ("cluster_health.json", "nodes_stats.json", "nodes.json", "version.json", "manifest.json"):
            rel = src.resolve(name)
            if rel:
                with open(os.path.join(tmp, name), "w", encoding="utf-8") as fh:
                    fh.write(src.text(name))
        r = analyze(tmp)
        ids = [f.id for f in r.findings]
        check("부분 번들: 룰 오류 0", not r.errors)
        check("부분 번들: 저장소 미수집을 '미설정' 으로 판정하지 않음", "SNP-001" not in ids)
        check("부분 번들: awareness 미수집을 '미설정' 으로 판정하지 않음", "CLU-019" not in ids)
        check("부분 번들: 건너뛴 룰이 기록됨", len(getattr(r.ctx, "skipped_rules", [])) > 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    empty = tempfile.mkdtemp()
    try:
        analyze(empty)
        check("빈 디렉터리는 번들로 인식하지 않음", False)
    except ValueError:
        check("빈 디렉터리는 번들로 인식하지 않음", True)
    finally:
        shutil.rmtree(empty, ignore_errors=True)


def test_thresholds():
    import io, contextlib
    from esdiag.thresholds import merge, DEFAULTS
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        t = merge({"heap_used_pct_warnn": 1, "heap_used_pct_warn": 70})
    check("임계값 오타 키는 적용되지 않음", "heap_used_pct_warnn" not in t)
    check("임계값 오타 키는 경고됨", "heap_used_pct_warnn" in buf.getvalue())
    check("정상 키는 적용됨", t["heap_used_pct_warn"] == 70)
    check("기본값 원본은 변하지 않음", DEFAULTS["heap_used_pct_warn"] != 70)


def main():
    test_units()
    test_watermark()
    test_gc_log()
    test_basis()
    test_thresholds()
    test_settings_kb()
    if len(sys.argv) > 1:
        test_bundle(sys.argv[1])
        test_partial_bundle(sys.argv[1])
        test_kb_against_bundle(sys.argv[1])
        test_multitier(sys.argv[1])
        test_capacity_and_mounts(sys.argv[1])
    for p in PASS:
        print("  PASS  " + p)
    for f in FAIL:
        print("  FAIL  " + f)
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
