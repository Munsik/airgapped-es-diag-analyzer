#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Branch driver test.

A healthy bundle never reaches some finding branches (critical and warning variants, rare conditions).
Each scenario below mutates the bundle to force one of them, then checks
(1) that no rule raised an error and (2) that the expected finding ids were produced.
This catches defects hidden in rarely run branches, such as a format error in a "70% or more" message.

    python3 tests/drive_branches.py healthy_bundle.zip
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
from esdiag.i18n import set_lang  # noqa: E402

# Checks use finding ids and severities only, so they do not depend on the language.
set_lang("en")

GB = 1024 ** 3
NOW_MS = None


class B(object):
    """Helper for the bundle working directory."""

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

    # nodes
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
        """Clone nodes until there are `total` of them (shard placement is unchanged)."""
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


# Scenario: (name, mutation function, expected finding ids)
SCENARIOS = [
    ("status yellow, allocation explain", lambda b: (
        b.edit("cluster_health.json", lambda h: h.update(status="yellow", unassigned_shards=3)),
        b.put("allocation_explain.json", {"can_allocate": "no", "allocate_explanation": "x",
                                          "node_allocation_decisions": [{"node_name": "n", "deciders": [
                                              {"decider": "disk_threshold", "decision": "NO", "explanation": "e"}]}]})),
     ["CLU-001!WARNING", "CLU-003!WARNING"]),
    ("1 master", lambda b: _roles(b, [["master", "data_hot"], ["data_hot"], ["data_hot"]]), ["CLU-006"]),
    ("2 masters", lambda b: _roles(b, [["master", "data_hot"], ["master", "data_hot"], ["data_hot"]]), ["CLU-006"]),
    ("4 masters, no dedicated master", lambda b: (
        b.clone_nodes(7), _roles(b, [["master", "data_hot"]] * 4 + [["data_hot"]] * 3)), ["CLU-007"]),
    ("old version 7.17, heap 1GB", lambda b: (
        b.edit("version.json", lambda v: v["version"].update(number="7.17.0")),
        b.each_node(fn_stats=lambda i, s: s["jvm"]["mem"].update(heap_max_in_bytes=GB))),
     ["CLU-009!WARNING", "SHD-001!CRITICAL", "VER-001!INFO"]),
    ("old version 7.17, enough heap", lambda b: b.edit("version.json", lambda v: v["version"].update(number="7.17.0")),
     ["SHD-001!OK"]),
    ("mixed JVM versions", lambda b: b.each_node(fn_info=lambda i, n: n["jvm"].update(version="21.0.%d" % i)), ["CLU-010"]),
    ("shard limit, dangling, long task, recovery", lambda b: (
        b.edit("cluster_settings.json", lambda c: c["persistent"].update({"cluster.max_shards_per_node": "20"})),
        b.put("dangling_indices.json", {"dangling_indices": [{"index_name": "old", "index_uuid": "u",
                                                              "creation_date_millis": 1}]}),
        b.edit("tasks.json", lambda t: next(iter(t["nodes"].values()))["tasks"].update(
            {"x:1": {"action": "indices:data/read/search", "running_time_in_nanos": 900 * 10 ** 9,
                     "description": "heavy"}})),
        b.put("recovery.json", {"idx": {"shards": [{"id": 0, "stage": "INDEX", "type": "PEER",
                                                   "total_time": "10m", "index": {"size": {"percent": "40%"}}}]}})),
     ["CLU-015", "CLU-016", "CLU-017", "CLU-020"]),
    ("zone imbalance, no awareness", lambda b: (
        b.each_node(fn_info=lambda i, n: n.update(attributes={"availability_zone": "a" if i < 2 else "b"})),
        b.edit("cluster_settings.json", lambda c: [c[s].pop("cluster", None) for s in ("persistent", "transient")] and c),
        # awareness can also be set in yml (effective value = defaults section), so remove it there too to make it "unset"
        b.edit("cluster_settings_defaults.json",
               lambda c: c.get("defaults", {}).pop("cluster.routing.allocation.awareness.attributes", None) and c)),
     ["CLU-018", "CLU-019"]),
    ("settings: multiple data paths, yml shadowed, no changes", lambda b: (
        b.each_node(fn_info=lambda i, n: n["settings"].update(
            {"path": {"data": ["/d1", "/d2"], "home": "/usr/share/elasticsearch"},
             "search": {"max_buckets": "1000"}})),
        b.put("cluster_settings.json", {"persistent": {}, "transient": {}})),
     ["CFG-003!WARNING", "SET-001!OK"]),
    ("settings: yml shadowed", lambda b: (
        b.each_node(fn_info=lambda i, n: n["settings"].update({"search": {"max_buckets": "1000"}})),
        b.edit("cluster_settings.json", lambda c: c["persistent"].update({"search.max_buckets": "70000"}))),
     ["SET-003"]),
    ("heap, GC, restart, breaker, fielddata", lambda b: (
        b.each_node(fn_stats=lambda i, s: (
            s["jvm"]["mem"].update(heap_used_percent=80),
            s["os"]["mem"].update(adjusted_total_in_bytes=int(s["jvm"]["mem"]["heap_max_in_bytes"] * 1.5)),
            s["jvm"].update(uptime_in_millis=3600000),
            s["jvm"]["gc"]["collectors"]["old"].update(collection_count=3, collection_time_in_millis=108000),
            s["breakers"]["parent"].update(limit_size_in_bytes=1000, estimated_size_in_bytes=800, tripped=0))),
        b.put("fielddata.json", [{"node": "n1", "field": "message", "size": "200mb"}])),
     ["JVM-001!WARNING", "JVM-003!WARNING", "JVM-005!WARNING", "OS-006!WARNING", "BRK-002!WARNING", "FD-002!INFO"]),
    # A 1.6TB disk has an effective low of 87.65% and high of 90.74% because of max_headroom. Use 89%: above low, below high.
    ("disk flood/low/spread", lambda b: _set_disk(b, [0.96, 0.89, 0.30]), ["DISK-001!CRITICAL", "DISK-003!WARNING", "DISK-005!WARNING"]),
    ("disk near low", lambda b: _set_disk(b, [0.79, 0.78, 0.77]), ["DISK-004!WARNING"]),
    ("uneven heap in the same tier", lambda b: b.each_node(
        fn_stats=lambda i, s: s["jvm"]["mem"].update(heap_max_in_bytes=(8 + i * 4) * GB)), ["NODE-001"]),
    ("uneven shards in the same tier", lambda b: [b.add_index("skew-%d" % k, pri=5) for k in range(4)], ["SHD-006"]),
    ("license expired", lambda b: b.edit("licenses.json", lambda l: l["license"].update(status="expired")), ["LIC-001!CRITICAL"]),
    ("license 60 days", lambda b: b.edit("licenses.json", lambda l: l["license"].update(
        status="active", expiry_date="2026-10-13T00:00:00.000Z")), ["LIC-001!WARNING"]),
    ("no snapshots", lambda b: (b.put("repositories.json", {}), b.put("snapshot.json", {"snapshots": []})),
     ["SNP-001"]),
    ("old snapshot, in progress, SLM/ILM stopped", lambda b: (
        b.put("snapshot.json", {"snapshots": [
            {"snapshot": "s1", "repository": "r", "state": "SUCCESS", "end_time_in_millis": 1754000000000,
             "start_time_in_millis": 1754000000000},
            {"snapshot": "s2", "repository": "r", "state": "IN_PROGRESS", "start_time_in_millis": 1754000000000}]}),
        b.put("slm_status.json", {"operation_mode": "STOPPED"}),
        b.put("ilm_status.json", {"operation_mode": "STOPPED"})),
     ["SNP-003!CRITICAL", "SNP-004!INFO", "SNP-006!WARNING", "ILM-001!WARNING"]),
    ("RPO: a just-started in-progress snapshot does not hide an old successful one", lambda b: b.put("snapshot.json", {"snapshots": [
        {"snapshot": "old-ok", "state": "SUCCESS", "end_time_in_millis": 1754000000000},
        {"snapshot": "now", "state": "IN_PROGRESS", "start_time_in_millis": 1786680000000},
        {"snapshot": "fail", "state": "FAILED", "end_time_in_millis": 1786680000000}]}),
     ["SNP-003!CRITICAL", "SNP-002", "SNP-004"]),
    ("snapshots: no success, SLM failing", lambda b: (
        b.put("snapshot.json", {"snapshots": [{"snapshot": "f1", "state": "FAILED", "end_time_in_millis": 1786680000000}]}),
        b.edit("slm_policies.json", lambda p: [v.update(last_success=None,
                                                        last_failure={"time": 1786681900000, "time_string": "t",
                                                                      "details": "repository missing"})
                                               for v in p.values()] and p)),
     ["SNP-003!CRITICAL", "SNP-007!CRITICAL"]),
    ("snapshots: list without timestamps, RPO OK from the last SLM success", lambda b: b.put("snapshot.json", {"snapshots": [
        {"snapshot": "s1", "state": "SUCCESS"}]}),
     ["SNP-003!OK"]),
    ("ILM: rollover step failure is critical", lambda b: b.edit("ilm_explain.json", lambda d: next(iter(d["indices"].values())).update(
        managed=True, policy="p", phase="hot", step="ERROR", failed_step="check-rollover-ready",
        step_info={"reason": "rollover alias missing"})),
     ["ILM-002!CRITICAL"]),
    ("ILM: write index delete failure is a warning", lambda b: b.edit("ilm_explain.json", lambda d: next(iter(d["indices"].values())).update(
        managed=True, policy="p", phase="delete", step="ERROR", failed_step="delete",
        step_info={"reason": "index [x] is the write index for data stream [y]. stopping execution"})),
     ["ILM-002!WARNING"]),
    ("monitoring: self collection", lambda b: b.add_index(".ds-.monitoring-es-8-mb-2026.09.01-000001"), ["OPS-007!INFO"]),
    ("ML and transform failures", lambda b: (
        b.put("transform_stats.json", {"transforms": [{"id": "t1", "state": "failed", "reason": "x"}]}),
        b.put("ml_anomaly_detectors.json", {"jobs": [{"job_id": "j1", "state": "failed"}]})),
     ["ML-001", "ML-002"]),
    ("certificate 20 days", lambda b: b.put("ssl_certs.json", _cert(20)), ["SEC-001!CRITICAL"]),
    ("certificate 60 days", lambda b: b.put("ssl_certs.json", _cert(60)), ["SEC-001!WARNING"]),
    ("security disabled, GeoIP, CCR", lambda b: (
        b.edit("xpack.json", lambda x: x["features"]["security"].update(enabled=False) if "features" in x
               else x.setdefault("security", {}).update(enabled=False)),
        b.put("geoip_stats.json", {"stats": {"failed_downloads": 3, "expired_databases": 1}}),
        b.put("ccr_stats.json", {"follow_stats": {"indices": [{"index": "f", "shards": [
            {"shard_id": 0, "failed_read_requests": 2, "failed_write_requests": 0,
             "read_exceptions": [{"exception": "x"}]}]}]}})),
     ["OPS-001", "OPS-002"]),
    ("index: excess replicas, total fields, explicit refresh, lone block, delayed allocation", lambda b: (
        b.add_index("over-replica", {"number_of_replicas": "5"}),
        b.edit("cluster_stats.json", lambda c: c["indices"].setdefault("mappings", {}).update(total_field_count=200000)),
        b.add_index("heavy-refresh", {"refresh_interval": "1s"}, extra_stats={"total.indexing.index_total": 20000000}),
        b.add_index("archive-blocked", {"blocks": {"write": "true"}}),
        b.add_index("no-delay", {"unassigned": {"node_left": {"delayed_timeout": "0"}}})),
     ["IDX-002", "MAP-002", "IDX-007", "IDX-011", "CLU-021", "SHD-012"]),
    ("scale: average shard too small", lambda b: b.edit("cluster_stats.json", lambda c: c["indices"].update(
        shards={"total": 400}, store={"size_in_bytes": 60 * GB})), ["SHD-005!WARNING"]),
    ("data stream RED, too many rollovers", lambda b: (
        [b.add_index(".ds-logs-tiny-default-2026.01.%02d-%06d" % (k + 1, k), size=10 * 1024 ** 2) for k in range(7)],
        b.edit("data_stream.json", lambda d: d.setdefault("data_streams", []).append(
            {"name": "logs-tiny-default", "status": "RED", "ilm_policy": "logs",
             "indices": [{"index_name": ".ds-logs-tiny-default-2026.01.%02d-%06d" % (k + 1, k)} for k in range(7)]}),
            {"data_streams": []})),
     ["IDX-010", "OVS-002"]),
    ("low cache hit ratio", lambda b: b.edit("indices_stats.json", lambda s: s["_all"]["total"].update(
        query_cache={"hit_count": 100, "miss_count": 50000, "evictions": 9000},
        request_cache={"hit_count": 10, "miss_count": 20000, "evictions": 5000})), ["PERF-003!WARNING"]),
    ("index and mapping heap vs master heap", lambda b: (
        b.edit("cluster_stats.json", lambda c: c["indices"].update(count=95000)),
        b.each_node(fn_stats=lambda i, s: s["indices"].setdefault("mappings", {}).update(
            total_estimated_overhead_in_bytes=40 * GB))),
     ["SHD-009!CRITICAL", "SHD-010!WARNING"]),
    ("search load vs replicas, codec, large documents, result window, content length", lambda b: (
        b.add_index("search-heavy", {"number_of_replicas": "0"}, extra_stats={"total.search.query_total": 300000}),
        b.add_index("big-standard", size=60 * GB, docs=10 ** 7),
        b.add_index("fat-docs", size=5 * GB, docs=1000),
        b.add_index("deep-paging", {"max_result_window": "50000"}),
        b.each_node(fn_info=lambda i, n: n["settings"].update({"http": {"max_content_length": "500mb"}}))),
     ["PERF-007", "DISK-006", "GEN-001", "GEN-002", "GEN-003"]),
    ("vector memory shortfall, old-version template", lambda b: (
        b.edit("version.json", lambda v: v["version"].update(number="9.1.0")),
        b.add_index("vec-idx", extra_stats={"total.dense_vector": {"value_count": 10 ** 8, "off_heap": {
            "total_size_bytes": 900 * GB, "total_vec_size_bytes": 800 * GB, "total_veq_size_bytes": 0,
            "total_veb_size_bytes": 0, "total_vex_size_bytes": 100 * GB}}}),
        b.edit("index_templates.json", lambda t: t.setdefault("index_templates", []).append(
            {"name": "vec", "index_template": {"index_patterns": ["vec-*"], "template": {"mappings": {"properties": {
                "emb": {"type": "dense_vector", "dims": 768, "index_options": {"type": "hnsw"}}}}}}}))),
     ["VEC-001!WARNING", "VEC-002!WARNING", "VEC-003!INFO"]),
    ("desired balance not converged, legacy template shadowed", lambda b: (
        b.edit("allocation.json", lambda a: [r.update({"shards.undesired": "4"}) for r in a] and a),
        b.put("internal_desired_balance.json", {"stats": {"computation_converged": False}}),
        b.put("templates.json", {"legacy-logs": {"index_patterns": ["logs-*"], "order": 0}}),
        b.edit("index_templates.json", lambda t: t.setdefault("index_templates", []).append(
            {"name": "logs-new", "index_template": {"index_patterns": ["logs-app-*"], "priority": 100}}))),
     ["HOT-003", "HOT-004", "TPL-001"]),
    ("oversharding only in a mounted index", lambda b: b.add_index("restored-.ds-logs-m-default-2026.01.01-000001",
                                                   {"store": {"type": "snapshot", "snapshot": {"snapshot_name": "s"}}},
                                                   size=2 * GB, pri=5), ["OVS-001!INFO"]),
    ("logs included (no patterns)", lambda b: (
        os.makedirs(os.path.join(b.root, "logs", "n1"), exist_ok=True),
        open(os.path.join(b.root, "logs", "n1", "elasticsearch.log"), "w").write("[INFO ] started\n")),
     ["LOG-001!OK"]),
    # ---- files that were not read before (deep)
    ("mapping: field limit near, fielddata, nested, unquantized vector", lambda b: (
        b.add_index("wide-idx", {"mapping": {"total_fields": {"limit": "20"}, "nested_fields": {"limit": "5"}}}),
        b.edit("mapping.json", lambda m: m.update({"wide-idx": {"mappings": {"properties": dict(
            [("f%02d" % k, {"type": "keyword"}) for k in range(15)] +
            [("msg", {"type": "text", "fielddata": True}),
             ("emb", {"type": "dense_vector", "dims": 768, "index_options": {"type": "hnsw"}})] +
            [("n%d" % k, {"type": "nested", "properties": {"x": {"type": "keyword"}}}) for k in range(4)])}}}))),
     ["MAP-004!WARNING", "MAP-005!WARNING", "MAP-006!WARNING", "VEC-005!WARNING"]),
    ("ILM: rollover without size criterion, oversized shard criterion", lambda b: (
        b.add_index("ilm-a-000001"), b.add_index("ilm-b-000001"),
        b.edit("ilm_policies.json", lambda p: p.update({
            "age-only": {"policy": {"phases": {"hot": {"actions": {"rollover": {"max_age": "1d"}}},
                                               "delete": {"min_age": "30d", "actions": {"delete": {}}}}},
                         "in_use_by": {"indices": ["ilm-a-000001"], "data_streams": []}},
            "huge": {"policy": {"phases": {"hot": {"actions": {"rollover": {"max_primary_shard_size": "200gb"}}}}},
                     "in_use_by": {"indices": ["ilm-b-000001"], "data_streams": []}}}))),
     ["ILM-004!WARNING", "ILM-005!WARNING", "ILM-006!INFO"]),
    ("leftover voting exclusion, stalled shutdown, store exception, remote disconnected", lambda b: (
        b.edit("cluster_state.json", lambda c: c["metadata"]["cluster_coordination"].update(
            voting_config_exclusions=[{"node_id": "x1", "node_name": "old-master"}])),
        b.put("nodes_shutdown_status.json", {"nodes": [{"node_id": "gone", "type": "REMOVE", "status": "STALLED",
                                                        "shard_migration": {"status": "STALLED", "explanation": "no target"}}]}),
        b.put("shard_stores.json", {"indices": {"broken": {"shards": {"0": {"stores": [
            {"allocation": "primary", "store_exception": {"type": "corrupt_index_exception", "reason": "checksum failed"}}]}}}}}),
        b.put("remote_cluster_info.json", {"dr": {"connected": False, "mode": "sniff", "num_nodes_connected": 0}})),
     ["CLU-022!WARNING", "SHUT-001!CRITICAL", "IDX-012!CRITICAL", "OPS-003!WARNING"]),
    ("leftover shutdown record (COMPLETE)", lambda b: b.put("nodes_shutdown_status.json", {"nodes": [
        {"node_id": b.node_ids()[0], "type": "RESTART", "status": "COMPLETE", "shard_migration": {"status": "COMPLETE"}}]}),
     ["SHUT-001!WARNING"]),
    ("frozen cache churn, script limit, cluster state publish failure", lambda b: (
        b.put("searchable_snapshots_cache_stats.json", {"nodes": {b.node_ids()[0]: {"shared_cache": {
            "reads": 900, "bytes_read_in_bytes": 10 ** 9, "evictions": 5000, "num_regions": 100,
            "size_in_bytes": 1600 * 1024 ** 2}}}}),
        b.each_node(fn_stats=lambda i, s: (s["script"].update(compilation_limit_triggered=12),
                                           s["discovery"]["cluster_state_update"].setdefault("failure", {}).update(count=3)))),
     ["FRZ-001!WARNING", "PERF-010!WARNING", "CLU-024!WARNING"]),
    ("plugin mismatch, model deployment failure", lambda b: (
        b.each_node(fn_info=lambda i, n: n.update(plugins=[{"name": "analysis-nori", "version": "9.4.4"}] if i == 0 else [])),
        b.put("ml_trained_models_stats.json", {"trained_model_stats": [{"model_id": "e5", "deployment_stats": {
            "deployment_id": "e5", "state": "failed", "reason": "not enough memory",
            "allocation_status": {"state": "starting"}}}]})),
     ["CLU-023!WARNING", "ML-003!WARNING"]),
    ("search pattern: nested 99%", lambda b: b.edit("cluster_stats.json", lambda c: c["indices"].update(search={
        "total": 1000, "queries": {"bool": 1000, "nested": 990, "wildcard": 3}, "sections": {"query": 1000}})),
     ["PERF-011!WARNING"]),
    ("search pattern: low share", lambda b: b.edit("cluster_stats.json", lambda c: c["indices"].update(search={
        "total": 100000, "queries": {"bool": 100000, "wildcard": 5}, "sections": {"query": 100000, "script_fields": 2}})),
     ["PERF-011!INFO"]),
    ("disk I/O saturation", lambda b: b.each_node(fn_stats=lambda i, s: (
        s["jvm"].update(uptime_in_millis=10 ** 7),
        s["fs"].setdefault("io_stats", {}).update(devices=[{"device_name": "d"}],
                                                  total={"io_time_in_millis": 9 * 10 ** 6, "read_operations": 1,
                                                         "write_operations": 2}))),
     ["DISK-008!WARNING"]),
    ("watcher stopped, autoscaling, rollup", lambda b: (
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
            fails.append("%s: scenario setup failed %r" % (name, exc))
            continue
        r = analyze(d)
        ids = set(f.id.split(".")[0] for f in r.findings)
        sev_ids = set("%s!%s" % (f.id.split(".")[0], f.severity) for f in r.findings)
        errs = [e["rule"] + " " + e["error"].strip().splitlines()[-1] for e in r.errors]
        missing = [e for e in expect if (e not in sev_ids if "!" in e else e not in ids)]
        if errs or missing:
            fails.append("%s: rule errors %s / not detected %s" % (name, errs or "-", missing or "-"))
        else:
            passed += 1
    # Compare mode branches: restart, node left, past rejections
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
        fails.append("compare mode: rule errors %s / not detected %s" % ([e["rule"] for e in r.errors] or "-", miss or "-"))
    else:
        passed += 1
    shutil.rmtree(work, ignore_errors=True)
    for f in fails:
        print("FAIL " + f)
    print("%d scenarios: %d passed, %d failed" % (len(SCENARIOS) + 1, passed, len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
