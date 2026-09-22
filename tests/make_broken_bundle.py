#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""정상 진단 번들을 변조해 '문제 있는 클러스터' 번들을 만든다.

룰이 실제로 동작하는지 검증하거나, 고객에게 리포트 예시를 보여줄 때 사용한다.
    python3 tests/make_broken_bundle.py <정상번들.zip> <출력디렉터리>
"""

import json
import os
import shutil
import sys
import zipfile


def load(d, name):
    p = os.path.join(d, name)
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save(d, name, obj):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1)


def main():
    src, out = sys.argv[1], sys.argv[2]
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    with zipfile.ZipFile(src) as z:
        z.extractall(out)
    root = os.path.join(out, [d for d in os.listdir(out)
                              if os.path.isdir(os.path.join(out, d))][0])

    # 1) 클러스터 red + 미할당 샤드
    h = load(root, "cluster_health.json")
    h.update({"status": "red", "unassigned_shards": 12, "unassigned_primary_shards": 4,
              "active_shards_percent_as_number": 91.3, "number_of_pending_tasks": 137,
              "task_max_waiting_in_queue_millis": 92000, "relocating_shards": 3})
    save(root, "cluster_health.json", h)

    idx = load(root, "indices.json")
    for i in range(12):
        s = dict(idx[i])
        s.update({"state": "UNASSIGNED", "node": None,
                  "prirep": "p" if i < 4 else "r",
                  "ur": "ALLOCATION_FAILED" if i % 2 else "NODE_LEFT",
                  "ud": "failed shard on node [xyz]: shard failure, reason [merge failed]"})
        idx[i] = s
    # 초대형 샤드 + 대형 샤드
    idx[20] = dict(idx[20], store=str(240 * 1024 ** 3), prirep="p")
    idx[21] = dict(idx[21], store=str(80 * 1024 ** 3), prirep="p")
    save(root, "indices.json", idx)

    # 2) 노드 상태 악화
    ns = load(root, "nodes_stats.json")
    for i, (nid, n) in enumerate(ns["nodes"].items()):
        n["jvm"]["mem"]["heap_used_percent"] = [92, 88, 61][i % 3]
        n["jvm"]["gc"]["collectors"]["old"] = {
            "collection_count": 4200, "collection_time_in_millis": 620000}
        n["os"]["swap"]["total_in_bytes"] = 4 * 1024 ** 3
        n["os"]["cpu"]["load_average"]["15m"] = 14.5
        n["os"]["cgroup"]["cpu"]["stat"]["number_of_times_throttled"] = 42000
        n["fs"]["total"]["available_in_bytes"] = int(n["fs"]["total"]["total_in_bytes"] * 0.06)
        n["process"]["open_file_descriptors"] = int(n["process"].get("max_file_descriptors", 65535) * 0.91)
        n["thread_pool"]["write"]["rejected"] = 15342
        n["thread_pool"]["search"]["rejected"] = 288
        n["thread_pool"]["search"]["queue"] = 640
        n["breakers"]["parent"] = {"limit_size_in_bytes": 10 ** 10,
                                   "estimated_size_in_bytes": 9 * 10 ** 9,
                                   "tripped": 37, "overhead": 1.0}
        n["indices"]["fielddata"] = {"memory_size_in_bytes": 6 * 1024 ** 3, "evictions": 1200}
        n["indexing_pressure"] = {"memory": {"total": {"coordinating_rejections": 55,
                                                       "primary_rejections": 12},
                                             "limit_in_bytes": 10 ** 9}}
        n["ingest"] = {"total": {"count": 100000, "failed": 4213, "time_in_millis": 5000},
                       "pipelines": {"logs-generic": {"count": 90000, "failed": 4213}}}
    save(root, "nodes_stats.json", ns)

    ni = load(root, "nodes.json")
    for i, (nid, n) in enumerate(ni["nodes"].items()):
        if i == 0:
            n["jvm"]["mem"]["heap_max_in_bytes"] = 48 * 1024 ** 3
            n["jvm"]["mem"]["heap_init_in_bytes"] = 32 * 1024 ** 3
            n["jvm"]["using_compressed_ordinary_object_pointers"] = "false"
            n["version"] = "9.3.0"
        n["process"]["mlockall"] = False
    save(root, "nodes.json", ni)

    # 3) 라이선스 만료 임박
    lic = load(root, "licenses.json")
    lic["license"]["expiry_date"] = "2026-08-30T00:00:00.000Z"
    lic["license"]["expiry_date_in_millis"] = 1787011200000
    save(root, "licenses.json", lic)

    # 4) ILM 오류 / SLM 실패 / 스냅샷 실패
    ilm = load(root, os.path.join("commercial", "ilm_explain.json"))
    keys = list(ilm["indices"].keys())[:3]
    for k in keys:
        ilm["indices"][k] = {"index": k, "managed": True, "policy": "logs-policy",
                             "phase": "warm", "step": "ERROR", "failed_step": "shrink",
                             "step_info": {"type": "illegal_state_exception",
                                           "reason": "no data_warm nodes available"}}
    save(root, os.path.join("commercial", "ilm_explain.json"), ilm)

    slm = load(root, os.path.join("commercial", "slm_stats.json"))
    slm["total_snapshots_failed"] = 19
    save(root, os.path.join("commercial", "slm_stats.json"), slm)

    snap = load(root, "snapshot.json")
    if snap.get("snapshots"):
        snap["snapshots"][0]["state"] = "PARTIAL"
        snap["snapshots"][0]["shards"] = {"total": 139, "failed": 7, "successful": 132}
        for s in snap["snapshots"]:
            s["end_time_in_millis"] = 1785000000000      # 오래된 스냅샷
            s["start_time_in_millis"] = 1785000000000
    save(root, "snapshot.json", snap)

    # 5) 위험한 클러스터 설정
    cs = load(root, "cluster_settings.json")
    cs["persistent"].update({
        "cluster.routing.allocation.enable": "primaries",
        "cluster.routing.allocation.disk.threshold_enabled": "false",
        "action.destructive_requires_name": "false",
    })
    cs["transient"]["cluster.routing.allocation.exclude._name"] = "instance-0000000121"
    save(root, "cluster_settings.json", cs)

    # 6) 인덱스 설정: replica 0, 과도한 replica, 블록, 없는 tier
    st = load(root, "settings.json")
    names = [n for n in st.keys() if not n.startswith(".")][:3] or list(st.keys())[:3]
    if names:
        st[names[0]]["settings"]["index"]["number_of_replicas"] = "0"
        st[names[0]]["settings"]["index"]["blocks"] = {"read_only_allow_delete": "true"}
    if len(names) > 1:
        st[names[1]]["settings"]["index"]["number_of_replicas"] = "7"
        st[names[1]]["settings"]["index"].setdefault("routing", {}).setdefault(
            "allocation", {}).setdefault("include", {})["_tier_preference"] = "data_cold"
        st[names[1]]["settings"]["index"].setdefault("mapping", {})["total_fields"] = {"limit": "6000"}
    save(root, "settings.json", st)

    # 7) 인덱스 통계: 느린 검색, 삭제 문서, merge throttle
    istat = load(root, "indices_stats.json")
    tnames = list(istat["indices"].keys())[:3]
    for t in tnames:
        tot = istat["indices"][t]["total"]
        tot["search"].update({"query_total": 50000, "query_time_in_millis": 95000000,
                              "query_failure": 42})
        tot["indexing"].update({"index_total": 2000000, "index_time_in_millis": 900000000,
                                "index_failed": 311})
        tot["merges"].update({"total_time_in_millis": 600000,
                              "total_throttled_time_in_millis": 420000})
        pri = istat["indices"][t]["primaries"]
        pri["docs"] = {"count": 1000000, "deleted": 900000}
        pri["store"] = {"size_in_bytes": 40 * 1024 ** 3}
        pri["segments"] = dict(pri.get("segments", {}), count=900)
    save(root, "indices_stats.json", istat)

    # 8) internal health 지표 악화
    ih = load(root, "internal_health.json")
    ih["status"] = "red"
    ih["indicators"]["shards_availability"] = {
        "status": "red", "symptom": "This cluster has unavailable shards.",
        "details": {"unassigned_primaries": 4, "unassigned_replicas": 8},
        "diagnosis": [{"cause": "primary 샤드가 할당되지 않음",
                       "action": "allocation explain 으로 decider 사유를 확인"}]}
    ih["indicators"]["disk"]["status"] = "yellow"
    ih["indicators"]["disk"]["symptom"] = "2 nodes are over the high watermark."
    save(root, "internal_health.json", ih)

    # 9) 서버 로그 추가(local 모드 흉내)
    logdir = os.path.join(root, "logs", "instance-0000000120")
    os.makedirs(logdir, exist_ok=True)
    with open(os.path.join(logdir, "elasticsearch.log"), "w", encoding="utf-8") as fh:
        fh.write("\n".join([
            "[2026-08-14T03:10:02,113][WARN ][o.e.m.j.JvmGcMonitorService] [node-1] [gc][old][11231][47] duration [5.2s], collections [1]/[6s]",
            "[2026-08-14T03:11:44,001][ERROR][o.e.b.ElasticsearchUncaughtExceptionHandler] [node-1] fatal error java.lang.OutOfMemoryError: Java heap space",
            "[2026-08-14T03:12:01,552][WARN ][o.e.c.r.a.DiskThresholdMonitor] [node-1] high disk watermark [90%] exceeded on [abc][node-2] free: 40gb[5.1%]",
            "[2026-08-14T03:12:07,113][WARN ][o.e.t.TcpTransport] [node-1] exception caught NodeDisconnectedException[node-3 disconnected]",
            "[2026-08-14T03:13:11,900][DEBUG][o.e.a.b.TransportShardBulkAction] [node-1] failed to execute bulk item (index) MapperParsingException[failed to parse field [ts]]",
            "[2026-08-14T03:14:00,000][WARN ][o.e.c.InternalClusterInfoService] [node-1] EsRejectedExecutionException: rejected execution of coordinating operation",
        ]) + "\n")

    # 10) self-managed 처럼 보이게(오케스트레이터 관리 설정 룰 검증용)
    man = load(root, "manifest.json")
    man["runner"] = "local"
    save(root, "manifest.json", man)
    ni = load(root, "nodes.json")
    for nid, n in ni["nodes"].items():
        n["attributes"] = {"rack_id": "r1"}
        st = n.setdefault("settings", {})
        st["path"] = {"data": "/usr/share/elasticsearch/data",
                      "logs": "/usr/share/elasticsearch/logs",
                      "home": "/usr/share/elasticsearch"}
        st["cluster"] = {"initial_master_nodes": "node-1,node-2", "name": "elasticsearch"}
        st["network"] = {"host": "127.0.0.1"}
        st.pop("discovery", None)
        n["jvm"]["input_arguments"] = ["-Xms8g", "-Xmx8g", "-XX:+UseG1GC"]
        n["build_type"] = "tar"                                  # archive 설치
        n["transport_address"] = "127.0.0.1:9300"                # 실제 바인딩 주소 = loopback
        n["total_indexing_buffer_in_bytes"] = 64 * 1024 ** 2
    save(root, "nodes.json", ni)
    h = load(root, "cluster_health.json")
    h["cluster_name"] = "elasticsearch"
    save(root, "cluster_health.json", h)

    # 11) 문서 수/매핑 오버헤드/search context/벡터
    istat = load(root, "indices_stats.json")
    names = list(istat["indices"].keys())
    istat["indices"][names[5]]["primaries"]["docs"] = {"count": 900000000, "deleted": 5000}
    istat["indices"][names[6]]["primaries"]["docs"] = {"count": 1900000000, "deleted": 100000}
    istat["indices"][names[7]]["primaries"]["dense_vector"] = {
        "value_count": 20000000,
        "off_heap": {"total_size_bytes": 300 * 1024 ** 3,
                     "total_vec_size_bytes": 280 * 1024 ** 3,
                     "total_veq_size_bytes": 0, "total_veb_size_bytes": 0,
                     "total_vex_size_bytes": 20 * 1024 ** 3}}
    istat["indices"][names[7]]["primaries"]["segments"] = {"count": 400}
    for nm in names[8:14]:
        istat["indices"][nm]["primaries"]["docs"] = {"count": 0, "deleted": 0}
    save(root, "indices_stats.json", istat)

    ns = load(root, "nodes_stats.json")
    for nid, n in ns["nodes"].items():
        n["indices"]["mappings"] = {"total_estimated_overhead_in_bytes": 9 * 1024 ** 3}
        n["indices"]["search"]["open_contexts"] = 850
        n["indices"]["search"]["scroll_current"] = 120
        n["fs"]["data"] = [{"mount": "/data", "type": "nfs4", "total_in_bytes": 10 * 1024 ** 4}]
    save(root, "nodes_stats.json", ns)

    cs = load(root, "cluster_stats.json")
    cs.setdefault("indices", {})["count"] = 45000
    cs["indices"].setdefault("mappings", {})["total_deduplicated_mapping_size_in_bytes"] = 2 * 1024 ** 3
    save(root, "cluster_stats.json", cs)

    st2 = load(root, "settings.json")
    k = list(st2.keys())[4]
    st2[k]["settings"]["index"]["store"] = {"preload": ["*"]}
    st2[k]["settings"]["index"].setdefault("mapping", {})["source"] = {"mode": "disabled"}
    save(root, "settings.json", st2)

    it = load(root, "index_templates.json")
    it.setdefault("index_templates", []).append({
        "name": "vectors-template",
        "index_template": {"index_patterns": ["vectors-*"], "template": {
            "mappings": {"properties": {
                "embedding": {"type": "dense_vector", "dims": 1024, "element_type": "float",
                              "index_options": {"type": "hnsw", "m": 16}}}}}}})
    save(root, "index_templates.json", it)

    # 11-b) 샤드 단위 문서 수(cat shards)
    idx2 = load(root, "indices.json")
    for j, sh in enumerate(idx2):
        if sh.get("prirep") == "p" and sh.get("state") == "STARTED":
            sh["docs"] = str(2100000000 if j % 7 == 0 else (450000000 if j % 7 == 1 else sh.get("docs")))
    save(root, "indices.json", idx2)

    # 11-c) 설정 변경 + 과다 샤딩 주입
    cs3 = load(root, "cluster_settings.json")
    cs3["persistent"]["search"] = {"max_buckets": "500000"}
    cs3["persistent"]["indices"] = {"breaker": {"total": {"limit": "98%"}}}
    save(root, "cluster_settings.json", cs3)
    ni3 = load(root, "nodes.json")
    for j, (nid, n) in enumerate(ni3["nodes"].items()):
        n.setdefault("settings", {})["thread_pool"] = {"write": {"queue_size": str(50000 if j == 0 else 10000)}}
    save(root, "nodes.json", ni3)
    st3 = load(root, "settings.json")
    ist3 = load(root, "indices_stats.json")
    sh3 = load(root, "indices.json")
    nodes3 = sorted(set(x["node"] for x in sh3 if x.get("node")))
    for k in range(12):
        nm = "logs-oversharded-%02d" % k
        st3[nm] = {"settings": {"index": {"number_of_shards": "10", "number_of_replicas": "1",
                                          "translog": {"durability": "async"}}}}
        base = json.loads(json.dumps(ist3["indices"][list(ist3["indices"].keys())[0]]))
        base["primaries"]["store"]["size_in_bytes"] = 20 * 1024 ** 3        # 20GB 를 10개로 = 샤드당 2GB
        base["primaries"]["docs"] = {"count": 1000000, "deleted": 0}
        ist3["indices"][nm] = base
        for p_ in range(10):
            for rp in ("p", "r"):
                sh3.append({"index": nm, "shard": str(p_), "prirep": rp, "state": "STARTED",
                            "docs": "100000", "store": str(2 * 1024 ** 3), "node": nodes3[(p_ + (rp == "r")) % len(nodes3)]})
    save(root, "settings.json", st3)
    save(root, "indices_stats.json", ist3)
    save(root, "indices.json", sh3)

    # 12) 수집 시각을 8시간 뒤로(=diff 비교용 '현재' 번들)
    import datetime
    man = load(root, "manifest.json")
    ts = man.get("collectionDate")
    if ts:
        dt = datetime.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S") + datetime.timedelta(hours=8)
        man["collectionDate"] = dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    save(root, "manifest.json", man)
    ns = load(root, "nodes_stats.json")
    for nid, n in ns["nodes"].items():
        n["jvm"]["uptime_in_millis"] = (n["jvm"].get("uptime_in_millis") or 0) + 8 * 3600 * 1000
        n["indices"]["indexing"]["index_total"] = \
            (n["indices"]["indexing"].get("index_total") or 0) + 12000000
        n["indices"]["search"]["query_total"] = \
            (n["indices"]["search"].get("query_total") or 0) + 400000
    save(root, "nodes_stats.json", ns)

    zip_path = os.path.join(out, "broken-diagnostic.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for dp, _dn, fns in os.walk(root):
            for fn in fns:
                full = os.path.join(dp, fn)
                z.write(full, os.path.relpath(full, out))
    print(zip_path)


if __name__ == "__main__":
    main()
