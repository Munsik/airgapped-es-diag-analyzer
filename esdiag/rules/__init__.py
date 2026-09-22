# -*- coding: utf-8 -*-
"""룰 모듈 집합. 새 룰은 함수를 만들어 해당 모듈의 RULES 에 추가하면 된다.

REQUIRES: '설정이 없다' 또는 '대상이 없다' 를 판정하는 룰은 원본 파일이 수집되었을 때만 실행한다.
파일이 없는 것(미수집)과 값이 없는 것(미설정)은 다른 사실이기 때문이다.
각 항목은 any-of 목록이며, 하나라도 있으면 실행한다.
"""

from . import cluster, deep, guidance, hotspot, nodes, ops, runtime, settings, sharding, shards

MODULES = [cluster, settings, nodes, shards, sharding, guidance, hotspot, ops, deep, runtime]

_NODES = ["nodes.json"]
_STATS = ["nodes_stats.json"]
_CS = ["cluster_settings.json"]
_IDX = ["indices_stats.json"]
_SET = ["settings.json"]
_SH = ["indices.json", "shards.json", "cat_shards.txt"]

REQUIRES = {
    # cluster
    "r_cluster_status": [["cluster_health.json"]],
    "r_unassigned_reason": [_SH],
    "r_internal_health": [["internal_health.json"]],
    "r_pending_tasks": [["cluster_health.json"]],
    "r_master_quorum": [_NODES],
    "r_version_consistency": [_NODES],
    "r_risky_settings": [_CS],
    "r_shard_capacity": [_CS, ["cluster_health.json"], _NODES],
    "r_dangling": [["dangling_indices.json"]],
    "r_long_tasks": [["tasks.json"]],
    "r_zone_balance": [_NODES, _CS],
    "r_recovery_inflight": [["recovery.json"]],
    # nodes
    "r_heap_usage": [_STATS], "r_heap_sizing": [_NODES, _STATS], "r_gc": [_STATS],
    "r_os": [_STATS], "r_disk": [_STATS], "r_thread_pools": [_STATS], "r_breakers": [_STATS],
    "r_indexing_pressure": [_STATS], "r_fielddata": [_STATS], "r_ingest_failures": [_STATS],
    "r_node_heterogeneity": [_NODES, _STATS],
    # shards
    "r_shard_density": [_SH, _NODES], "r_shard_balance": [_SH], "r_data_stream_health": [["data_stream.json"]],
    "r_cache_efficiency": [_IDX], "r_shard_size": [_SH], "r_small_shards": [_SH],
    "r_replica_zero": [_SET, _IDX], "r_replica_unassignable": [_SET, _NODES], "r_deleted_docs": [_IDX],
    "r_segments": [_IDX, _SH], "r_merge_throttle": [_IDX], "r_search_latency": [_IDX],
    "r_index_failures": [_IDX], "r_mapping_limits": [_SET], "r_refresh_interval": [_SET, _IDX],
    "r_read_only_blocks": [_SET], "r_tier_preference": [_SET, _NODES], "r_index_count": [["cluster_stats.json"]],
    # guidance
    "r_large_result_sets": [_SET], "r_large_documents": [_NODES, _IDX],
    "r_cluster_name": [["cluster_health.json"]], "r_path_settings": [_NODES],
    "r_discovery": [_NODES], "r_jvm_diag_settings": [_NODES],
    "r_docs_per_shard": [_SH, _IDX], "r_master_heap_per_index": [_NODES, ["cluster_stats.json"]],
    "r_mapping_heap_overhead": [_STATS, ["cluster_stats.json"]], "r_empty_indices": [_IDX],
    "r_total_shards_per_node": [_SET, _IDX], "r_index_buffer": [_NODES, _SH],
    "r_open_contexts": [_STATS], "r_search_timeout": [_CS], "r_replica_throughput": [_SET, _IDX, _SH],
    "r_store_preload": [_SET], "r_remote_storage": [_STATS],
    "r_codec": [_SET, _IDX], "r_source_mode": [_SET], "r_dynamic_mapping": [["index_templates.json"]],
    "r_vector_memory": [_IDX, _STATS], "r_vector_quantization": [["index_templates.json"]],
    "r_vector_segments": [_IDX, _SH],
    # hotspot
    "r_tier_saturation": [_STATS, _NODES], "r_resource_hotspot": [_STATS], "r_workload_hotspot": [_STATS],
    "r_desired_balance": [["allocation.json", "cat_allocation.txt"]],
    "r_recovery_settings": [_CS], "r_template_conflict": [["templates.json"], ["index_templates.json"]],
    "r_delayed_allocation": [_SET],
    # ops
    "r_monitoring": [_IDX], "r_license": [["licenses.json"]], "r_snapshots": [["repositories.json", "snapshot.json"]],
    "r_ilm": [["ilm_explain.json", "ilm_status.json"]],
    "r_ml_transform": [["transform_stats.json", "ml_anomaly_detectors.json"]],
    "r_certificates": [["ssl_certs.json"]], "r_security_enabled": [["xpack.json"]],
    "r_geoip": [["geoip_stats.json"]], "r_ccr": [["ccr_stats.json"]],
    # runtime
    "r_hot_threads": [["nodes_hot_threads.txt"]],
    # settings
    "r_cluster_setting_changes": [_CS], "r_yml_shadowed": [_CS, _NODES],
    "r_node_setting_changes": [_NODES], "r_node_setting_consistency": [_NODES],
    "r_index_setting_changes": [_SET],
    # deep (이전에 읽지 않던 파일)
    "r_search_usage": [["cluster_stats.json"]], "r_disk_io_utilization": [_STATS], "r_mapping_limits_actual": [["mapping.json"]], "r_vector_mapping_actual": [["mapping.json"]],
    "r_ilm_policies": [["ilm_policies.json"]], "r_voting_exclusions": [["cluster_state.json"]],
    "r_node_shutdown": [["nodes_shutdown_status.json"]], "r_shard_store_errors": [["shard_stores.json"]],
    "r_remote_clusters": [["remote_cluster_info.json"]],
    "r_frozen_cache": [["searchable_snapshots_cache_stats.json"]], "r_script_limit": [_STATS],
    "r_ingest_processors": [_STATS], "r_cluster_state_publication": [_STATS],
    "r_plugin_consistency": [_NODES], "r_ml_deployments": [["ml_trained_models_stats.json"]],
    "r_watcher_autoscaling_rollup": [["watcher_stack.json", "autoscaling_capacity.json", "rollup_jobs.json"]],
    # sharding
    "r_index_oversharding": [_IDX, _SH], "r_datastream_small_rollover": [["data_stream.json"], _IDX],
    "r_shard_size_distribution": [_SH],
}


def missing_inputs(bundle, fn):
    """충족되지 않은 입력 그룹 목록(비어 있으면 실행 가능)."""
    miss = []
    for group in REQUIRES.get(fn.__name__, []):
        if not any(bundle.exists(f) for f in group):
            miss.append(" 또는 ".join(group))
    return miss


def all_rules():
    out = []
    for m in MODULES:
        for fn in getattr(m, "RULES", []):
            out.append((m.__name__.split(".")[-1], fn))
    return out
