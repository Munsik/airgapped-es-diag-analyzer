"""Thresholds for every decision point.

`--thresholds my.json` can override any subset (deep merge).
The defaults come from the Elastic official guidance and common operating practice.
They are meant to be tuned to the cluster type (search, logging, security).
"""
from .i18n import T

DEFAULTS = {
    # --- JVM ---
    "heap_used_pct_warn": 75,                        # [Tool] Heap usage at collection time
    "heap_used_pct_crit": 85,                        # [Tool] Heap usage at collection time
    "heap_max_bytes_crit": 32 * 1024 ** 3,           # [Official] Compressed oops boundary (below 32GB recommended)
    "heap_vs_ram_pct_warn": 50,                      # [Official] Heap <= 50% of total memory
    "heap_vs_ram_tolerance_pct": 2,                  # [Tool] Tolerance for rounding and adjusted_total error
    "old_gc_time_ratio_warn": 0.02,                  # [Tool] Cumulative old GC time / uptime
    "old_gc_time_ratio_crit": 0.05,                  # [Tool] Cumulative old GC time / uptime
    "young_gc_time_ratio_warn": 0.05,                # [Tool] Cumulative young GC time / uptime
    "old_gc_per_hour_warn": 6,                       # [Tool] Old GC count per hour
    "old_gc_per_hour_crit": 30,                      # [Tool] Old GC count per hour

    # --- OS / process ---
    "load_per_cpu_warn": 1.0,                        # [Tool] load15 / CPU cores
    "load_per_cpu_crit": 1.5,                        # [Tool] load15 / CPU cores
    "fd_used_pct_warn": 70,                          # [Tool] Open files / maximum (official minimum limit is 65,535)
    "cgroup_throttle_ratio_warn": 0.01,              # [Tool] throttled / elapsed periods
    "cgroup_throttle_ratio_crit": 0.05,              # [Tool] throttled / elapsed periods
    "uptime_short_hours": 6,                         # [Tool] Treats the node as recently restarted

    # --- Disk ---
    "disk_watermark_low_default": "85%",             # [Official] ES default (used only when no settings file is present)
    "disk_watermark_high_default": "90%",            # [Official] ES default (used only when no settings file is present)
    "disk_watermark_flood_default": "95%",           # [Official] ES default (used only when no settings file is present)
    "disk_watermark_flood_frozen_default": "95%",     # [Official] Flood stage for frozen-only nodes
    "disk_watermark_flood_frozen_headroom_default": "20GB",  # [Official] Frozen flood max_headroom
    "disk_imbalance_pct_warn": 15,                   # [Tool] Disk usage spread between nodes (percentage points)
    "disk_low_margin_pct": 10,                       # [Tool] Percentage points left before the effective low watermark

    # --- Thread pools / breakers ---
    "rejected_crit": 1000,                           # [Tool] Total cumulative rejections
    "breaker_tripped_warn": 1,                       # [Tool] Breaker trip count (1 = any history)

    # --- Shards / indices ---
    "shards_per_gb_heap_warn": 20,                   # [Official] 20 shards per 1GB of heap (versions before 8.3 only)
    "shards_per_gb_heap_crit": 30,                   # [Tool] Versions before 8.3 only
    "max_shards_per_node_headroom_pct_warn": 80,     # [Tool] Usage against cluster.max_shards_per_node
    "shard_size_gb_warn": 50,                        # [Official] Shards of 10-50GB
    "shard_size_gb_crit": 200,                       # [Tool] Upper bound based on recovery time
    "small_shard_mb": 1024,                          # [Tool] Small shard threshold
    "small_shard_count_warn": 50,                    # [Tool]
    "small_shard_ratio_warn": 0.5,                   # [Tool]
    "deleted_docs_ratio_warn": 0.25,                 # [Tool]
    "segments_per_shard_warn": 50,                   # [Tool]
    "merge_throttle_ratio_warn": 0.05,               # [Tool]
    "search_latency_ms_warn": 200,                   # [Tool] Average query latency per index
    "search_latency_ms_crit": 1000,                  # [Tool] Average query latency per index
    "index_latency_ms_warn": 50,                     # [Tool] Average indexing time per document
    "index_latency_ms_crit": 200,                    # [Tool] Average indexing time per document
    "min_query_total_for_latency": 100,              # [Tool] Indices with too few samples are not rated
    "fielddata_heap_pct_warn": 10,                   # [Tool] fielddata / heap

    # --- Cluster ---
    "pending_tasks_warn": 10,                        # [Tool]
    "pending_tasks_crit": 100,                       # [Tool]
    "max_task_wait_ms_warn": 30000,                  # [Tool]
    "long_running_task_ms_warn": 300000,             # [Tool] 5 minutes

    # --- Operations / lifecycle ---
    "license_expiry_days_warn": 90,                  # [Tool]
    "license_expiry_days_crit": 30,                  # [Tool]
    "cert_expiry_days_warn": 90,                     # [Tool]
    "cert_expiry_days_crit": 30,                     # [Tool]
    "snapshot_age_hours_warn": 36,                   # [Tool] Age of the latest snapshot
    "snapshot_age_hours_crit": 168,                  # [Tool] 7 days
    "snapshot_failed_warn": 1,                       # [Tool]
    "ingest_failed_warn": 1,                         # [Tool]

    # --- Hot threads ---
    "hot_thread_pct_warn": 50,                       # [Tool] CPU% of a single thread

    # --- Logs (local/remote mode) ---
    "log_scan_bytes": 8 * 1024 ** 2,                 # [Tool] Bytes scanned per log file (from the end)

    # --- Official guidance (production guidance) ---
    "docs_per_shard_warn": 200000000,                # [Official] Fewer than 200 million documents per shard recommended
    "flush_avg_ms_info": 800,                        # [Tool] Field baseline: average flush time per flush
    "flush_avg_ms_warn": 1200,                       # [Tool] Field baseline
    "refresh_avg_ms_info": 40,                       # [Tool] Field baseline: average refresh time per refresh
    "refresh_avg_ms_warn": 70,                       # [Tool] Field baseline
    "merge_avg_ms_info": 20000,                      # [Tool] Field baseline: average merge time per merge
    "merge_avg_ms_warn": 40000,                      # [Tool] Field baseline
    "write_latency_min_ops": 100,                    # [Tool] Minimum flushes/refreshes/merges before a node average is rated
    "load_host_cpu_pct_max": 20,                     # [Tool] Container node below this cpu% is not rated on load average
    "write_node_index_share_min": 0.1,               # [Tool] A node indexes if its index_total is this share of the busiest node
    "write_shard_skew_warn": 0.5,                    # [Tool] (max - min) / average of write-target shards per node in a tier
    "write_shard_skew_min": 3,                       # [Tool] Minimum difference in write-target shards before it is reported
    "restart_share_warn": 0.5,                       # [Tool] Share of nodes restarted within uptime_short_hours
    "long_running_task_ms_high": 3600000,            # [Tool] 1 hour: long task becomes a Warning
    "monitoring_task_ms_info": 86400000,             # [Tool] 24 hours: monitoring/internal tasks are reported only past this
    "translog_flush_threshold_default": "10gb",      # [Official] index.translog.flush_threshold_size default (8.8+)
    "translog_flush_threshold_legacy": "512mb",      # [Official] Default before 8.8
    "docs_rollover_overshoot_pct": 5,                # [Tool] Allowed overshoot of a rolled-over shard past 200M docs (ILM checks every poll_interval)
    "docs_per_shard_crit": 1500000000,               # [Tool] Alert when approaching the Lucene limit (2,147,483,519)
    "indices_per_gb_master_heap": 3000,              # [Official] 3000 indices per 1GB of master heap
    "mapping_heap_pct_warn": 50,                     # [Tool] Estimated mapping overhead / heap
    "heap_baseline_bytes": 512 * 1024 ** 2,          # [Official] Extra 0.5GB margin in the field mapper estimate
    "empty_index_count_warn": 5,                     # [Tool]
    "heavy_index_docs": 10000000,                    # [Tool] Threshold for a heavily indexed index
    "index_buffer_per_shard_warn": 32 * 1024 ** 2,   # [Tool] Per write-target shard (official upper bound is 512MB)
    "open_contexts_warn": 100,                       # [Tool]
    "search_heavy_query_total": 100000,              # [Tool] Threshold for a search-heavy index
    "preload_index_count_warn": 5,                   # [Tool]
    "codec_check_min_bytes": 50 * 1024 ** 3,         # [Tool]
    "vector_vs_fscache_pct_warn": 60,                # [Tool] Resident vector size / (RAM - heap)
    "vector_dim_quantize_warn": 384,                 # [Official] Quantization recommended for float vectors of 384 dimensions or more
    "vector_segments_per_shard_warn": 20,            # [Tool]
    "avg_doc_bytes_warn": 1024 * 1024,               # [Tool] Average document size of 1MB

    # --- Hot spots / balancing ---
    "tier_cpu_pct_warn": 75,                        # [Tool] CPU% at which a whole tier counts as saturated
    "hotspot_heap_pct_gap": 30,                      # [Tool] Heap spread between nodes (percentage points)
    "hotspot_heap_pct_floor": 70,                    # [Tool] Ignored if the maximum is below this
    "hotspot_cpu_pct_floor": 50,                     # [Tool]
    "hotspot_disk_pct_floor": 50,                    # [Tool]
    "hotspot_cpu_pct_gap": 40,                       # [Tool]
    "workload_skew_ratio_warn": 1.8,                 # [Tool] Busiest node / average
    "undesired_shards_warn": 1,                      # [Tool]
    "recovery_rate_low_bytes": 40 * 1024 ** 2,       # [Official] indices.recovery.max_bytes_per_sec at or below the 40mb default

    # --- Oversharding ---
    "oversharding_floor_shard_gb": 10,              # [Official] Recommended lower bound per shard, 10GB
    "oversharding_target_shard_gb": 50,             # [Official] Recommended upper bound per shard, 50GB (used for the recommended primary count)
    "oversharding_excess_warn": 20,                 # [Tool] Total number of shards that could be removed
    "oversharding_excess_ratio_warn": 0.1,          # [Tool] Share of all shards
    "oversharding_min_shards": 20,                  # [Tool] Minimum sample size for the distribution rating
    "oversharding_small_share_warn": 0.8,           # [Tool] Share of shards under 10GB
    "oversharding_min_data_gb": 100,                # [Tool] Small clusters are not rated on distribution
    "ds_min_backing_indices": 5,                    # [Tool] Minimum backing index count for the data stream rating
    "ds_small_backing_shard_gb": 1,                 # [Tool] Median backing shard size threshold
    "logsdb_shard_gb_high": 30,                     # [Tool] Upper end of the logsdb shard range (official upper bound is 50GB)
    "logsdb_shard_gb_low": 10,                      # [Official] Lower end of the 10-50GB shard range
    "logsdb_rows_max": 100,                         # [Tool] Maximum indices listed in the logsdb shard size table

    # --- Mapping / ILM policy ---
    "mapping_fields_near_limit_pct": 90,            # [Tool] Field count against total_fields.limit
    "ilm_rollover_max_shard_gb": 50,                # [Official] Recommended upper bound for shard size at rollover
    "ilm_implicit_max_shard_docs": 200000000,       # [Official] Rollover always runs at 200M docs per shard; higher values have no effect
    "forcemerge_free_space_factor": 3,              # [Official] max_num_segments=1 may need free space up to 3x the shard size
    "forcemerge_stuck_hours": 24,                   # [Tool] Time in the forcemerge action before it is reported
    "disk_io_busy_pct_warn": 60,                    # [Tool] Average disk utilization since startup
    "search_expensive_share_warn": 10,              # [Tool] Share of expensive query types in all searches (%)

    # --- Bundle comparison (diff) ---
    "diff_min_hours_for_projection": 1.0,            # [Tool] No extrapolation for intervals shorter than this
    "disk_projection_days_warn": 30,                 # [Tool]
    "index_growth_min_bytes": 1024 ** 3,             # [Tool]

    # --- Report ---
    "top_n": 15,                                     # [Tool] Maximum rows in an evidence table
    "eol_major_below": 8,                            # [Tool] Majors below this trigger an old-version warning
}


def merge(overrides):
    """Apply user overrides on top of the defaults. Unknown keys are skipped with a warning (catches typos)."""
    import sys
    t = dict(DEFAULTS)
    for k, v in (overrides or {}).items():
        if k not in DEFAULTS:
            sys.stderr.write(T("thresholds.merge.01") % k)
            continue
        t[k] = v
    return t
