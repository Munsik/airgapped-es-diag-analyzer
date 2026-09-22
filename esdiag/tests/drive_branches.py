#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""판정 분기 구동 테스트.

정상 번들만으로는 실행되지 않는 판정 분기(치명·주의 변형, 드문 조건)를 시나리오별로 강제로 발생시켜
(1) 룰 실행 오류가 없는지, (2) 기대한 판정 ID 가 실제로 나오는지 확인한다.
'70% 이상' 같은 포맷 오류처럼 드물게 실행되는 분기에 숨은 결함을 잡기 위한 것이다.

    python3 tests/drive_branches.py 정상번들.zip
"""
import copy
import json
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from esdiag.engine import analyze  # noqa: E402

GB = 1024 ** 3
NOW_MS = None


class B(object):
    """번들 작업 디렉터리 헬퍼."""

    def __init__(self, root):
        self.root = root

    def p(self, name):
        for cand in (name, os.path.join("commercial", name)):
            full = os.path.join(self.root, cand)
            if os.path.exists(full):
                return full
        return os.path.join(self.root, name)

    def get(self, name, default=None):
        path = self.p(name)
        if not os.path.exists(path):
            return copy.deepcopy(default)
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def put(self, name, obj):
        with open(self.p(name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh)

    def edit(self, name, fn, default=None):
        o = self.get(name, default)
        r = fn(o)
        self.put(name, o if r is None else r)

    # 노드
    def node_ids(self):
        return list(self.get("nodes.json")["nodes"].keys())

    def each_node(self, fn_info=None, fn_stats=None, only=None):
        ni, ns = self.get("nodes.json"), self.get("nodes_stats.json")
        for i, nid in enumerate(ni["nodes"]):
            if only is not None and i not in only:
                continue
            if fn_info:
                fn_info(i, ni["nodes"][nid])
            if fn_stats:
                fn_stats(i, ns["nodes"][nid])
        self.put("nodes.json", ni)
        self.put("nodes_stats.json", ns)

    def clone_nodes(self, total):
        """노드를 복제해 total 대로 늘린다(샤드 배치는 그대로)."""
        ni, ns = self.get("nodes.json"), self.get("nodes_stats.json")
        ids = list(ni["nodes"].keys())
        k = 0
        while len(ni["nodes"]) < total:
            src = ids[k % len(ids)]
            nid = "clone%02d" % k
            a, b = copy.deepcopy(ni["nodes"][src]), copy.deepcopy(ns["nodes"][src])
            a["name"] = b["name"] = "clone-%02d" % k
            ni["nodes"][nid], ns["nodes"][nid] = a, b
            k += 1
        self.put("nodes.json", ni)
        self.put("nodes_stats.json", ns)

    def user_index(self):
        st = self.get("settings.json")
        return [n for n in st if not n.startswith(".")][0]

    def add_index(self, name, settings=None, size=GB, docs=1000, pri=1, node=None, extra_stats=None):
        st, ist, sh = self.get("settings.json"), self.get("indices_stats.json"), self.get("indices.json")
        tmpl = copy.deepcopy(next(iter(ist["indices"].values())))
        st[name] = {"settings": {"index": dict({"number_of_shards": str(pri), "number_of_replicas": "1"},
                                              **(settings or {}))}}
        tmpl["primaries"]["store"]["size_in_bytes"] = size
        tmpl["total"]["store"]["size_in_bytes"] = size * 2
        tmpl["primaries"]["docs"] = {"count": docs, "deleted": 0}
        for path, val in (extra_stats or {}).items():
            cur = tmpl
            keys = path.split(".")
            for k2 in keys[:-1]:
                cur = cur.setdefault(k2, {})
            cur[keys[-1]] = val
        ist["indices"][name] = tmpl
        node = node or self.get("nodes.json")["nodes"][self.node_ids()[0]]["name"]
        for s in range(pri):
            sh.append({"index": name, "shard": str(s), "prirep": "p", "state": "STARTED",
                       "docs": str(docs // pri), "store": str(size // pri), "node": node})
        self.put("settings.json", st)
        self.put("indices_stats.json", ist)
        self.put("indices.json", sh)


def _set_disk(b, used):
    def f(i, s):
        if i < len(used):
            t = s["fs"]["total"]["total_in_bytes"]
            s["fs"]["total"]["available_in_bytes"] = int(t * (1 - used[i]))
    b.each_node(fn_stats=f)


def _roles(b, roles):
    def fi(i, n):
        if i < len(roles):
            n["roles"] = roles[i]

    def fs(i, n):
        if i < len(roles):
            n["roles"] = roles[i]
    b.each_node(fi, fs)


def _cert(days):
    import datetime
    t = datetime.datetime(2026, 8, 14) + datetime.timedelta(days=days)
    return [{"path": "certs/http.p12", "alias": "http", "subject_dn": "CN=es", "expiry": t.strftime("%Y-%m-%dT%H:%M:%S.000Z")}]


# 시나리오: (이름, 변형 함수, 기대 판정 ID 목록)
SCENARIOS = [
    ("상태 yellow·할당 설명", lambda b: (
        b.edit("cluster_health.json", lambda h: h.update(status="yellow", unassigned_shards=3)),
        b.put("allocation_explain.json", {"can_allocate": "no", "allocate_explanation": "x",
                                          "node_allocation_decisions": [{"node_name": "n", "deciders": [
                                              {"decider": "disk_threshold", "decision": "NO", "explanation": "e"}]}]})),
     ["CLU-001!WARNING", "CLU-003!WARNING"]),
    ("마스터 1대", lambda b: _roles(b, [["master", "data_hot"], ["data_hot"], ["data_hot"]]), ["CLU-006"]),
    ("마스터 2대", lambda b: _roles(b, [["master", "data_hot"], ["master", "data_hot"], ["data_hot"]]), ["CLU-006"]),
    ("마스터 4대·전용 마스터 없음", lambda b: (
        b.clone_nodes(7), _roles(b, [["master", "data_hot"]] * 4 + [["data_hot"]] * 3)), ["CLU-006", "CLU-007"]),
    ("구버전 7.17·heap 1GB", lambda b: (
        b.edit("version.json", lambda v: v["version"].update(number="7.17.0")),
        b.each_node(fn_stats=lambda i, s: s["jvm"]["mem"].update(heap_max_in_bytes=GB))),
     ["CLU-009!WARNING", "SHD-001!CRITICAL", "VER-001!INFO"]),
    ("구버전 7.17·heap 충분", lambda b: b.edit("version.json", lambda v: v["version"].update(number="7.17.0")),
     ["SHD-001!OK"]),
    ("JVM 버전 혼재", lambda b: b.each_node(fn_info=lambda i, n: n["jvm"].update(version="21.0.%d" % i)), ["CLU-010"]),
    ("샤드 한도·dangling·장시간 태스크·복구", lambda b: (
        b.edit("cluster_settings.json", lambda c: c["persistent"].update({"cluster.max_shards_per_node": "20"})),
        b.put("dangling_indices.json", {"dangling_indices": [{"index_name": "old", "index_uuid": "u",
                                                              "creation_date_millis": 1}]}),
        b.edit("tasks.json", lambda t: next(iter(t["nodes"].values()))["tasks"].update(
            {"x:1": {"action": "indices:data/read/search", "running_time_in_nanos": 900 * 10 ** 9,
                     "description": "heavy"}})),
        b.put("recovery.json", {"idx": {"shards": [{"id": 0, "stage": "INDEX", "type": "PEER",
                                                   "total_time": "10m", "index": {"size": {"percent": "40%"}}}]}})),
     ["CLU-015", "CLU-016", "CLU-017", "CLU-020"]),
    ("가용영역 불균형·awareness 없음", lambda b: (
        b.each_node(fn_info=lambda i, n: n.update(attributes={"availability_zone": "a" if i < 2 else "b"})),
        b.edit("cluster_settings.json", lambda c: [c[s].pop("cluster", None) for s in ("persistent", "transient")] and c),
        # awareness 는 yml 에도 있을 수 있다(실효값 = defaults 섹션) → 함께 제거해야 '미설정' 이 된다
        b.edit("cluster_settings_defaults.json",
               lambda c: c.get("defaults", {}).pop("cluster.routing.allocation.awareness.attributes", None) and c)),
     ["CLU-018", "CLU-019"]),
    ("설정: 다중 data path·yml 가려짐·변경 없음", lambda b: (
        b.each_node(fn_info=lambda i, n: n["settings"].update(
            {"path": {"data": ["/d1", "/d2"], "home": "/usr/share/elasticsearch"},
             "search": {"max_buckets": "1000"}})),
        b.put("cluster_settings.json", {"persistent": {}, "transient": {}})),
     ["CFG-003!WARNING", "SET-001!OK"]),
    ("설정: yml 가려짐", lambda b: (
        b.each_node(fn_info=lambda i, n: n["settings"].update({"search": {"max_buckets": "1000"}})),
        b.edit("cluster_settings.json", lambda c: c["persistent"].update({"search.max_buckets": "70000"}))),
     ["SET-003"]),
    ("heap·GC·재기동·브레이커·fielddata", lambda b: (
        b.each_node(fn_stats=lambda i, s: (
            s["jvm"]["mem"].update(heap_used_percent=80),
            s["os"]["mem"].update(adjusted_total_in_bytes=int(s["jvm"]["mem"]["heap_max_in_bytes"] * 1.5)),
            s["jvm"].update(uptime_in_millis=3600000),
            s["jvm"]["gc"]["collectors"]["old"].update(collection_count=3, collection_time_in_millis=108000),
            s["breakers"]["parent"].update(limit_size_in_bytes=1000, estimated_size_in_bytes=800, tripped=0))),
        b.put("fielddata.json", [{"node": "n1", "field": "message", "size": "200mb"}])),
     ["JVM-001!WARNING", "JVM-003!WARNING", "JVM-005!WARNING", "OS-006!WARNING", "BRK-002!WARNING", "FD-002!INFO"]),
    # 1.6TB 디스크는 max_headroom 때문에 실효 low 87.65% / high 90.74% — low 초과·high 미만인 89% 사용
    ("디스크 flood/low/편차", lambda b: _set_disk(b, [0.96, 0.89, 0.30]), ["DISK-001!CRITICAL", "DISK-003!WARNING", "DISK-005!WARNING"]),
    ("디스크 low 근접", lambda b: _set_disk(b, [0.79, 0.78, 0.77]), ["DISK-004!WARNING"]),
    ("같은 tier heap 불균일", lambda b: b.each_node(
        fn_stats=lambda i, s: s["jvm"]["mem"].update(heap_max_in_bytes=(8 + i * 4) * GB)), ["NODE-001"]),
    ("같은 tier 샤드 불균형", lambda b: [b.add_index("skew-%d" % k, pri=5) for k in range(4)], ["SHD-006"]),
    ("라이선스 만료", lambda b: b.edit("licenses.json", lambda l: l["license"].update(status="expired")), ["LIC-001!CRITICAL"]),
    ("라이선스 60일", lambda b: b.edit("licenses.json", lambda l: l["license"].update(
        status="active", expiry_date="2026-10-13T00:00:00.000Z")), ["LIC-001!WARNING"]),
    ("스냅샷 없음", lambda b: (b.put("repositories.json", {}), b.put("snapshot.json", {"snapshots": []})),
     ["SNP-001"]),
    ("스냅샷 오래됨·진행 중·SLM/ILM 중지", lambda b: (
        b.put("snapshot.json", {"snapshots": [
            {"snapshot": "s1", "repository": "r", "state": "SUCCESS", "end_time_in_millis": 1754000000000,
             "start_time_in_millis": 1754000000000},
            {"snapshot": "s2", "repository": "r", "state": "IN_PROGRESS", "start_time_in_millis": 1754000000000}]}),
        b.put("slm_status.json", {"operation_mode": "STOPPED"}),
        b.put("ilm_status.json", {"operation_mode": "STOPPED"})),
     ["SNP-003!CRITICAL", "SNP-004!INFO", "SNP-006!WARNING", "ILM-001!WARNING"]),
    ("RPO: 방금 시작된 진행 중 스냅샷이 오래된 성공 스냅샷을 가리지 않음", lambda b: b.put("snapshot.json", {"snapshots": [
        {"snapshot": "old-ok", "state": "SUCCESS", "end_time_in_millis": 1754000000000},
        {"snapshot": "now", "state": "IN_PROGRESS", "start_time_in_millis": 1786680000000},
        {"snapshot": "fail", "state": "FAILED", "end_time_in_millis": 1786680000000}]}),
     ["SNP-003!CRITICAL", "SNP-002", "SNP-004"]),
    ("스냅샷: 성공 없음·SLM 실패 중", lambda b: (
        b.put("snapshot.json", {"snapshots": [{"snapshot": "f1", "state": "FAILED", "end_time_in_millis": 1786680000000}]}),
        b.edit("slm_policies.json", lambda p: [v.update(last_success=None,
                                                        last_failure={"time": 1786681900000, "time_string": "t",
                                                                      "details": "repository missing"})
                                               for v in p.values()] and p)),
     ["SNP-003!CRITICAL", "SNP-007!CRITICAL"]),
    ("스냅샷: 시각 없는 목록 → SLM 마지막 성공으로 RPO 정상", lambda b: b.put("snapshot.json", {"snapshots": [
        {"snapshot": "s1", "state": "SUCCESS"}]}),
     ["SNP-003!OK"]),
    ("ILM: 롤오버 단계 실패는 치명", lambda b: b.edit("ilm_explain.json", lambda d: next(iter(d["indices"].values())).update(
        managed=True, policy="p", phase="hot", step="ERROR", failed_step="check-rollover-ready",
        step_info={"reason": "rollover alias missing"})),
     ["ILM-002!CRITICAL"]),
    ("ILM: write index 삭제 실패는 주의", lambda b: b.edit("ilm_explain.json", lambda d: next(iter(d["indices"].values())).update(
        managed=True, policy="p", phase="delete", step="ERROR", failed_step="delete",
        step_info={"reason": "index [x] is the write index for data stream [y]. stopping execution"})),
     ["ILM-002!WARNING"]),
    ("모니터링: 자기 수집", lambda b: b.add_index(".ds-.monitoring-es-8-mb-2026.09.01-000001"), ["OPS-007!INFO"]),
    ("ML·transform 실패", lambda b: (
        b.put("transform_stats.json", {"transforms": [{"id": "t1", "state": "failed", "reason": "x"}]}),
        b.put("ml_anomaly_detectors.json", {"jobs": [{"job_id": "j1", "state": "failed"}]})),
     ["ML-001", "ML-002"]),
    ("인증서 20일", lambda b: b.put("ssl_certs.json", _cert(20)), ["SEC-001!CRITICAL"]),
    ("인증서 60일", lambda b: b.put("ssl_certs.json", _cert(60)), ["SEC-001!WARNING"]),
    ("보안 비활성·GeoIP·CCR", lambda b: (
        b.edit("xpack.json", lambda x: x["features"]["security"].update(enabled=False) if "features" in x
               else x.setdefault("security", {}).update(enabled=False)),
        b.put("geoip_stats.json", {"stats": {"failed_downloads": 3, "expired_databases": 1}}),
        b.put("ccr_stats.json", {"follow_stats": {"indices": [{"index": "f", "shards": [
            {"shard_id": 0, "failed_read_requests": 2, "failed_write_requests": 0,
             "read_exceptions": [{"exception": "x"}]}]}]}})),
     ["OPS-001", "OPS-002"]),
    ("인덱스: replica 초과·필드 합계·refresh 명시·단독 차단·지연 할당", lambda b: (
        b.add_index("over-replica", {"number_of_replicas": "5"}),
        b.edit("cluster_stats.json", lambda c: c["indices"].setdefault("mappings", {}).update(total_field_count=200000)),
        b.add_index("heavy-refresh", {"refresh_interval": "1s"}, extra_stats={"total.indexing.index_total": 20000000}),
        b.add_index("archive-blocked", {"blocks": {"write": "true"}}),
        b.add_index("no-delay", {"unassigned": {"node_left": {"delayed_timeout": "0"}}})),
     ["IDX-002", "MAP-002", "IDX-007", "IDX-011", "CLU-021", "SHD-012"]),
    ("규모: 평균 샤드 과소", lambda b: b.edit("cluster_stats.json", lambda c: c["indices"].update(
        shards={"total": 400}, store={"size_in_bytes": 60 * GB})), ["SHD-005!WARNING"]),
    ("데이터 스트림 RED·롤오버 과다", lambda b: (
        [b.add_index(".ds-logs-tiny-default-2026.01.%02d-%06d" % (k + 1, k), size=10 * 1024 ** 2) for k in range(7)],
        b.edit("data_stream.json", lambda d: d.setdefault("data_streams", []).append(
            {"name": "logs-tiny-default", "status": "RED", "ilm_policy": "logs",
             "indices": [{"index_name": ".ds-logs-tiny-default-2026.01.%02d-%06d" % (k + 1, k)} for k in range(7)]}),
            {"data_streams": []})),
     ["IDX-010", "OVS-002"]),
    ("캐시 적중률 저조", lambda b: b.edit("indices_stats.json", lambda s: s["_all"]["total"].update(
        query_cache={"hit_count": 100, "miss_count": 50000, "evictions": 9000},
        request_cache={"hit_count": 10, "miss_count": 20000, "evictions": 5000})), ["PERF-003!WARNING"]),
    ("마스터 heap 대비 인덱스·매핑 heap", lambda b: (
        b.edit("cluster_stats.json", lambda c: c["indices"].update(count=95000)),
        b.each_node(fn_stats=lambda i, s: s["indices"].setdefault("mappings", {}).update(
            total_estimated_overhead_in_bytes=40 * GB))),
     ["SHD-009!CRITICAL", "SHD-010!WARNING"]),
    ("검색 부하 대비 replica·codec·대형 문서·result window·content length", lambda b: (
        b.add_index("search-heavy", {"number_of_replicas": "0"}, extra_stats={"total.search.query_total": 300000}),
        b.add_index("big-standard", size=60 * GB, docs=10 ** 7),
        b.add_index("fat-docs", size=5 * GB, docs=1000),
        b.add_index("deep-paging", {"max_result_window": "50000"}),
        b.each_node(fn_info=lambda i, n: n["settings"].update({"http": {"max_content_length": "500mb"}}))),
     ["PERF-007", "DISK-006", "GEN-001", "GEN-002", "GEN-003"]),
    ("벡터 메모리 부족·구버전 템플릿", lambda b: (
        b.edit("version.json", lambda v: v["version"].update(number="9.1.0")),
        b.add_index("vec-idx", extra_stats={"total.dense_vector": {"value_count": 10 ** 8, "off_heap": {
            "total_size_bytes": 900 * GB, "total_vec_size_bytes": 800 * GB, "total_veq_size_bytes": 0,
            "total_veb_size_bytes": 0, "total_vex_size_bytes": 100 * GB}}}),
        b.edit("index_templates.json", lambda t: t.setdefault("index_templates", []).append(
            {"name": "vec", "index_template": {"index_patterns": ["vec-*"], "template": {"mappings": {"properties": {
                "emb": {"type": "dense_vector", "dims": 768, "index_options": {"type": "hnsw"}}}}}}}))),
     ["VEC-001!WARNING", "VEC-002!WARNING", "VEC-003!INFO"]),
    ("desired balance 미수렴·레거시 템플릿 가려짐", lambda b: (
        b.edit("allocation.json", lambda a: [r.update({"shards.undesired": "4"}) for r in a] and a),
        b.put("internal_desired_balance.json", {"stats": {"computation_converged": False}}),
        b.put("templates.json", {"legacy-logs": {"index_patterns": ["logs-*"], "order": 0}}),
        b.edit("index_templates.json", lambda t: t.setdefault("index_templates", []).append(
            {"name": "logs-new", "index_template": {"index_patterns": ["logs-app-*"], "priority": 100}}))),
     ["HOT-003", "HOT-004", "TPL-001"]),
    ("마운트 인덱스만 과다 샤딩", lambda b: b.add_index("restored-.ds-logs-m-default-2026.01.01-000001",
                                                   {"store": {"type": "snapshot", "snapshot": {"snapshot_name": "s"}}},
                                                   size=2 * GB, pri=5), ["OVS-001!INFO"]),
    ("로그 포함(패턴 없음)", lambda b: (
        os.makedirs(os.path.join(b.root, "logs", "n1"), exist_ok=True),
        open(os.path.join(b.root, "logs", "n1", "elasticsearch.log"), "w").write("[INFO ] started\n")),
     ["LOG-001!OK"]),
    # ---- 이전에 읽지 않던 파일(deep)
    ("매핑: 필드 한도 근접·fielddata·nested·비양자화 벡터", lambda b: (
        b.add_index("wide-idx", {"mapping": {"total_fields": {"limit": "20"}, "nested_fields": {"limit": "5"}}}),
        b.edit("mapping.json", lambda m: m.update({"wide-idx": {"mappings": {"properties": dict(
            [("f%02d" % k, {"type": "keyword"}) for k in range(15)] +
            [("msg", {"type": "text", "fielddata": True}),
             ("emb", {"type": "dense_vector", "dims": 768, "index_options": {"type": "hnsw"}})] +
            [("n%d" % k, {"type": "nested", "properties": {"x": {"type": "keyword"}}}) for k in range(4)])}}}))),
     ["MAP-004!WARNING", "MAP-005!WARNING", "MAP-006!WARNING", "VEC-005!WARNING"]),
    ("ILM: 크기 기준 없는 롤오버·과대 샤드 기준", lambda b: (
        b.add_index("ilm-a-000001"), b.add_index("ilm-b-000001"),
        b.edit("ilm_policies.json", lambda p: p.update({
            "age-only": {"policy": {"phases": {"hot": {"actions": {"rollover": {"max_age": "1d"}}},
                                               "delete": {"min_age": "30d", "actions": {"delete": {}}}}},
                         "in_use_by": {"indices": ["ilm-a-000001"], "data_streams": []}},
            "huge": {"policy": {"phases": {"hot": {"actions": {"rollover": {"max_primary_shard_size": "200gb"}}}}},
                     "in_use_by": {"indices": ["ilm-b-000001"], "data_streams": []}}}))),
     ["ILM-004!WARNING", "ILM-005!WARNING", "ILM-006!INFO"]),
    ("투표 제외 잔존·종료 정체·저장소 예외·원격 끊김", lambda b: (
        b.edit("cluster_state.json", lambda c: c["metadata"]["cluster_coordination"].update(
            voting_config_exclusions=[{"node_id": "x1", "node_name": "old-master"}])),
        b.put("nodes_shutdown_status.json", {"nodes": [{"node_id": "gone", "type": "REMOVE", "status": "STALLED",
                                                        "shard_migration": {"status": "STALLED", "explanation": "no target"}}]}),
        b.put("shard_stores.json", {"indices": {"broken": {"shards": {"0": {"stores": [
            {"allocation": "primary", "store_exception": {"type": "corrupt_index_exception", "reason": "checksum failed"}}]}}}}}),
        b.put("remote_cluster_info.json", {"dr": {"connected": False, "mode": "sniff", "num_nodes_connected": 0}})),
     ["CLU-022!WARNING", "SHUT-001!CRITICAL", "IDX-012!CRITICAL", "OPS-003!WARNING"]),
    ("종료 레코드 잔존(COMPLETE)", lambda b: b.put("nodes_shutdown_status.json", {"nodes": [
        {"node_id": b.node_ids()[0], "type": "RESTART", "status": "COMPLETE", "shard_migration": {"status": "COMPLETE"}}]}),
     ["SHUT-001!WARNING"]),
    ("frozen 캐시 교체·스크립트 한도·상태 발행 실패", lambda b: (
        b.put("searchable_snapshots_cache_stats.json", {"nodes": {b.node_ids()[0]: {"shared_cache": {
            "reads": 900, "bytes_read_in_bytes": 10 ** 9, "evictions": 5000, "num_regions": 100,
            "size_in_bytes": 1600 * 1024 ** 2}}}}),
        b.each_node(fn_stats=lambda i, s: (s["script"].update(compilation_limit_triggered=12),
                                           s["discovery"]["cluster_state_update"].setdefault("failure", {}).update(count=3)))),
     ["FRZ-001!WARNING", "PERF-010!WARNING", "CLU-024!WARNING"]),
    ("플러그인 불일치·모델 배포 실패", lambda b: (
        b.each_node(fn_info=lambda i, n: n.update(plugins=[{"name": "analysis-nori", "version": "9.4.4"}] if i == 0 else [])),
        b.put("ml_trained_models_stats.json", {"trained_model_stats": [{"model_id": "e5", "deployment_stats": {
            "deployment_id": "e5", "state": "failed", "reason": "not enough memory",
            "allocation_status": {"state": "starting"}}}]})),
     ["CLU-023!WARNING", "ML-003!WARNING"]),
    ("검색 패턴: nested 99%", lambda b: b.edit("cluster_stats.json", lambda c: c["indices"].update(search={
        "total": 1000, "queries": {"bool": 1000, "nested": 990, "wildcard": 3}, "sections": {"query": 1000}})),
     ["PERF-011!WARNING"]),
    ("검색 패턴: 비중 낮음", lambda b: b.edit("cluster_stats.json", lambda c: c["indices"].update(search={
        "total": 100000, "queries": {"bool": 100000, "wildcard": 5}, "sections": {"query": 100000, "script_fields": 2}})),
     ["PERF-011!INFO"]),
    ("디스크 I/O 포화", lambda b: b.each_node(fn_stats=lambda i, s: (
        s["jvm"].update(uptime_in_millis=10 ** 7),
        s["fs"].setdefault("io_stats", {}).update(devices=[{"device_name": "d"}],
                                                  total={"io_time_in_millis": 9 * 10 ** 6, "read_operations": 1,
                                                         "write_operations": 2}))),
     ["DISK-008!WARNING"]),
    ("watcher 중지·오토스케일링·rollup", lambda b: (
        b.put("watcher_stack.json", {"manually_stopped": True, "stats": [{"watch_count": 4}]}),
        b.put("autoscaling_capacity.json", {"policies": {"data_hot": {
            "required_capacity": {"total": {"storage": 2 * 10 ** 12, "memory": 10 ** 11}},
            "current_capacity": {"total": {"storage": 10 ** 12, "memory": 10 ** 11}}}}}),
        b.put("rollup_jobs.json", {"jobs": [{"config": {"id": "r1"}, "status": {"job_state": "started"}}]})),
     ["OPS-005!WARNING", "OPS-004!INFO", "OPS-006!INFO"]),
]


def main():
    src = sys.argv[1]
    work = tempfile.mkdtemp()
    base = os.path.join(work, "base")
    with zipfile.ZipFile(src) as z:
        z.extractall(base)
    root_name = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))][0]
    fails, passed = [], 0
    for name, mut, expect in SCENARIOS:
        d = os.path.join(work, "s")
        if os.path.exists(d):
            shutil.rmtree(d)
        shutil.copytree(os.path.join(base, root_name), d)
        try:
            mut(B(d))
        except Exception as exc:
            fails.append("%s: 시나리오 구성 실패 %r" % (name, exc))
            continue
        r = analyze(d)
        ids = set(f.id.split(".")[0] for f in r.findings)
        sev_ids = set("%s!%s" % (f.id.split(".")[0], f.severity) for f in r.findings)
        errs = [e["rule"] + " " + e["error"].strip().splitlines()[-1] for e in r.errors]
        missing = [e for e in expect if (e not in sev_ids if "!" in e else e not in ids)]
        if errs or missing:
            fails.append("%s: 룰 오류 %s / 미검출 %s" % (name, errs or "-", missing or "-"))
        else:
            passed += 1
    # 비교 모드 분기: 재기동·노드 이탈·과거 rejection
    d1, d2 = os.path.join(work, "prev"), os.path.join(work, "cur")
    for dd in (d1, d2):
        if os.path.exists(dd):
            shutil.rmtree(dd)
        shutil.copytree(os.path.join(base, root_name), dd)
    B(d1).each_node(fn_stats=lambda i, s: (s["jvm"].update(uptime_in_millis=10 ** 10),
                                           s["thread_pool"]["write"].update(rejected=50)))
    B(d2).each_node(fn_stats=lambda i, s: (s["jvm"].update(uptime_in_millis=10 ** 6),
                                           s["thread_pool"]["write"].update(rejected=50)))
    ni, ns = B(d2).get("nodes.json"), B(d2).get("nodes_stats.json")
    drop = list(ni["nodes"].keys())[-1]
    ni["nodes"].pop(drop)
    ns["nodes"].pop(drop)
    B(d2).put("nodes.json", ni)
    B(d2).put("nodes_stats.json", ns)
    B(d2).edit("manifest.json", lambda m: m.update(collectionDate="2026-08-15T04:51:34.007Z"))
    r = analyze(d2, baseline=d1)
    ids = set(f.id for f in r.findings)
    miss = [x for x in ("DIF-002", "DIF-003", "DIF-004") if x not in ids]
    if r.errors or miss:
        fails.append("비교 모드: 룰 오류 %s / 미검출 %s" % ([e["rule"] for e in r.errors] or "-", miss or "-"))
    else:
        passed += 1
    shutil.rmtree(work, ignore_errors=True)
    for f in fails:
        print("FAIL " + f)
    print("시나리오 %d개 중 통과 %d, 실패 %d" % (len(SCENARIOS) + 1, passed, len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
