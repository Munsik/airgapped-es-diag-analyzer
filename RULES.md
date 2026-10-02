# Rule reference (RULES.md)

> This document is generated from the source code by `tools/gen_rules_doc.py`. Do not edit it by hand.
> Thresholds are the current defaults in `esdiag/thresholds.py`. Override them with `--thresholds`.
> Korean version: [RULES.ko.md](RULES.ko.md)

## Baseline

| Item | Value |
| --- | --- |
| Tool version | esdiag 0.13.0 |
| Elasticsearch baseline version | 9.4 |
| Official docs checked | 2026-09 |
| Validated on real bundles | 9.4.4 (ECH, 3 nodes, single tier) / 9.5.3 (ECH, 14 nodes, hot/warm/cold/frozen), api mode |
| Field-tested | Tuned for false positives and false negatives on a 9.5.3 multi-tier bundle. Compared file and field structure. Verified memory use on large bundles (cluster_state 190 MB, mapping 178 MB). |
| Validated collection modes | Validated in api mode only. local and remote modes (including server logs and OS command output) may need further verification. |
| Minimum supported version | 8.0 (older versions work only for the APIs that exist in them) |

### Version-specific rules

| Since | Applies to | Behavior |
| --- | --- | --- |
| 8.0 | SET-* | action.destructive_requires_name defaults to true |
| 8.3 | SHD-001 | The 20-shards-per-1-GB-heap guideline applies only below 8.3 |
| 8.5 | DISK-* | Disk watermark max_headroom (200/150/100 GB) applies |
| 8.8 | IDX-015 | index.translog.flush_threshold_size defaults to 10GB (512MB before) |
| 8.14 | VEC-002 | dense_vector defaults to int8_hnsw (quantized) when index_options is not set |
| 9.0 | IDX-013 | logsdb applies automatically to new logs-*-* data streams only |
| 9.1 | VEC-002 | float vectors with 384 or more dimensions default to bbq_hnsw |
| 9.2 | VEC-003 | index.mapping.exclude_source_vectors is enabled by default |

If the analyzed cluster is newer than the baseline version, the report shows `VER-001`.

## Evidence basis

| Basis | Meaning |
| --- | --- |
| Official | The criterion itself is stated in the official Elastic documentation |
| Reported fact | State, errors or settings reported by Elasticsearch, passed through as is (no threshold) |
| Tool threshold | No official numeric criterion exists, so the tool's own threshold decides |
| Computed | Increase, rate of increase or linear extrapolation between two bundles |

## Input file rules

Each rule declares the input files it needs (`REQUIRES` in `esdiag/rules/__init__.py`). If a file is missing from the bundle, the rule is not run and is listed in the report under 'Not evaluated: input not collected'. This keeps 'file missing (not collected)' apart from 'setting missing (not set)'.

## Contents

- [Cluster](#cluster): 12 rules
- [Settings changes (versus defaults)](#settings-changes-versus-defaults): 5 rules
- [Nodes (JVM, OS, disk, thread pools)](#nodes-jvm-os-disk-thread-pools): 12 rules
- [Shards and indices](#shards-and-indices): 21 rules
- [Oversharding and small shards](#oversharding-and-small-shards): 3 rules
- [Official guidance baselines (settings, shards, performance, disk, vectors)](#official-guidance-baselines-settings-shards-performance-disk-vectors): 25 rules
- [Hot spots and balancing](#hot-spots-and-balancing): 7 rules
- [Operations and security](#operations-and-security): 9 rules
- [Mappings, ILM policies, cluster coordination, detailed stats](#mappings-ilm-policies-cluster-coordination-detailed-stats): 17 rules
- [Runtime (hot threads, logs)](#runtime-hot-threads-logs): 2 rules
- [OS settings (syscalls/ in local and remote mode)](#os-settings-syscalls-in-local-and-remote-mode): 1 rule
- [Trend (--baseline comparison mode)](#trend---baseline-comparison-mode): 10 rules
- [Settings knowledge base](#settings-knowledge-base)
- [All thresholds](#all-thresholds)

## Cluster

### CLU-001: Cluster status is green

| Item | Details |
| --- | --- |
| Function | `cluster.r_cluster_status` |
| Evidence basis | Reported fact |
| Possible severities | Critical, Warning, OK |
| Required input | (cluster_health.json) |
| Source files | cluster_health.json |
| References | [Troubleshooting shard allocation](https://www.elastic.co/docs/troubleshoot/elasticsearch/diagnose-unassigned-shards) |

**Decision logic**

Reports cluster_health.status as is. red → Critical, yellow → Warning, green → OK.

### CLU-002, CLU-003: Unassigned shards present

| Item | Details |
| --- | --- |
| Function | `cluster.r_unassigned_reason` |
| Findings | CLU-002 Unassigned shards present / CLU-003 allocation explain result |
| Evidence basis | Reported fact |
| Possible severities | Critical, Warning, Info |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (indices.json or shards.json or cat_shards.txt) |
| Source files | allocation_explain.json / indices.json / shards.json |
| References | [Troubleshooting shard allocation](https://www.elastic.co/docs/troubleshoot/elasticsearch/diagnose-unassigned-shards) |

**Decision logic**

Counts shards with state=UNASSIGNED in the shard list, grouped by unassigned.reason. Any unassigned primary → Critical; replicas only → Warning (CLU-002). If allocation_explain.json is present, the decider result is reported too: can_allocate != yes → Warning, otherwise Info (CLU-003).

### CLU-004, CLU-004.(sub-items): All Health API indicators are green

| Item | Details |
| --- | --- |
| Function | `cluster.r_internal_health` |
| Findings | CLU-004 All Health API indicators are green / CLU-004. Health API indicator problem: %s (%s) |
| Evidence basis | Reported fact |
| Possible severities | Critical, Warning, OK |
| Required input | (internal_health.json) |
| Source files | internal_health.json |

**Decision logic**

Passes through the Health API (_health_report) indicators. Any indicator red → Critical, yellow → Warning, all green → OK. unknown is not rated.

### CLU-005: Master pending task backlog

| Item | Details |
| --- | --- |
| Function | `cluster.r_pending_tasks` |
| Evidence basis | Tool threshold |
| Possible severities | Critical, Warning |
| Thresholds | `max_task_wait_ms_warn` = 30,000 ([Tool])<br>`pending_tasks_crit` = 100 ([Tool])<br>`pending_tasks_warn` = 10 ([Tool])<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (cluster_health.json) |
| Source files | cluster_health.json / cluster_pending_tasks.json |

**Decision logic**

Master pending tasks. Count >= pending_tasks_crit or longest wait >= max_task_wait_ms_warn x 4 → Critical; count >= pending_tasks_warn or longest wait >= max_task_wait_ms_warn → Warning.

### CLU-006, CLU-007: No master-eligible nodes

| Item | Details |
| --- | --- |
| Function | `cluster.r_master_quorum` |
| Findings | CLU-006 No master-eligible nodes / CLU-007 No dedicated master nodes |
| Evidence basis | Official / Tool threshold |
| Possible severities | Critical, Warning |
| Required input | (nodes.json) |
| Source files | nodes.json |

**Decision logic**

Number of master-eligible nodes (roles include master, voting_only included). 0 → Critical; 1 in a multi-node cluster → Critical; 2 → Warning (losing one node loses quorum; official guidance: with 2 or fewer master-eligible nodes, all of them must stay up). An even count (4 or more) is not rated, because ES automatically leaves one node out of the voting configuration (CLU-006). No dedicated master and >= 6 data nodes → Warning (CLU-007).

### CLU-008, CLU-009, CLU-010: Node version mismatch

| Item | Details |
| --- | --- |
| Function | `cluster.r_version_consistency` |
| Findings | CLU-008 Node version mismatch / CLU-009 Old major version in use / CLU-010 JVM version mismatch between nodes |
| Evidence basis | Reported fact / Tool threshold |
| Possible severities | Warning |
| Thresholds | `eol_major_below` = 8 ([Tool] Majors below this trigger an old-version warning) |
| Required input | (nodes.json) |
| Source files | nodes.json / version.json |

**Decision logic**

More than 1 ES version across nodes → Warning (CLU-008). Major version < eol_major_below → Warning (CLU-009). More than 1 JVM version across nodes → Warning (CLU-010).

### CLU-013, CLU-014, CLU-011.(sub-items), CLU-012: Transient cluster settings in use

| Item | Details |
| --- | --- |
| Function | `cluster.r_risky_settings` |
| Findings | CLU-013 Transient cluster settings in use / CLU-014 Adaptive Replica Selection is disabled / CLU-011. Risky cluster setting: %s / CLU-012 Leftover node exclude setting |
| Evidence basis | Official / Reported fact |
| Possible severities | Warning, Info |
| Required input | (cluster_settings.json) |
| Source files | cluster_settings.json |

**Decision logic**

Rates only cluster settings that differ from the default (explicitly set in persistent/transient). allocation.enable != all → Critical, rebalance.enable != all → Warning, disk.threshold_enabled=false → Critical, cluster.blocks.read_only(_allow_delete)=true → Critical, destructive_requires_name=false → Warning (CLU-011). A value in allocation.exclude._name/_ip/_host → Warning (CLU-012). Any transient setting → Info (CLU-013, deprecated since 7.16). use_adaptive_replica_selection=false → Warning (CLU-014, default is true).

### CLU-015: Cluster shard limit nearly reached

| Item | Details |
| --- | --- |
| Function | `cluster.r_shard_capacity` |
| Evidence basis | Official |
| Possible severities | Critical, Warning |
| Thresholds | `max_shards_per_node_headroom_pct_warn` = 80 ([Tool] Usage against cluster.max_shards_per_node) |
| Required input | (cluster_settings.json) and (cluster_health.json) and (nodes.json) |
| Source files | cluster_health.json / cluster_settings.json |
| References | [Shard sizing guide](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**Decision logic**

Usage = (active + unassigned - shards on frozen-only nodes) / (cluster.max_shards_per_node x number of data nodes excluding frozen-only). >= max_shards_per_node_headroom_pct_warn → Warning, >= 95% → Critical.

### CLU-016: Dangling indices present

| Item | Details |
| --- | --- |
| Function | `cluster.r_dangling` |
| Evidence basis | Reported fact |
| Possible severities | Warning |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (dangling_indices.json) |
| Source files | dangling_indices.json |

**Decision logic**

Warning if there is 1 or more dangling index.

### CLU-017: Long-running tasks

| Item | Details |
| --- | --- |
| Function | `cluster.r_long_tasks` |
| Evidence basis | Tool threshold |
| Possible severities | Warning, Info |
| Thresholds | `long_running_task_ms_high` = 3,600,000 ([Tool] 1 hour: long task becomes a Warning)<br>`long_running_task_ms_warn` = 300,000 ([Tool] 5 minutes)<br>`monitoring_task_ms_info` = 86,400,000 ([Tool] 24 hours: monitoring/internal tasks are reported only past this)<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (tasks.json) |
| Source files | tasks.json |

**Decision logic**

Long-running tasks grouped by action (CLU-017). Always-running persistent tasks are excluded.

Monitoring and internal tasks (cluster:monitor/*, indices:monitor/*, internal:*) are reported only past
monitoring_task_ms_info. Other tasks: longest run >= long_running_task_ms_high → Warning, >= long_running_task_ms_warn → Info.
Write-path actions (bulk, reindex, update/delete by query, forcemerge, shrink/split/clone) are marked, because a stuck
write task holds resources and blocks follow-up work. One row per action with the task count and the longest run.

### CLU-018, CLU-019: Data nodes are unevenly spread across availability zones

| Item | Details |
| --- | --- |
| Function | `cluster.r_zone_balance` |
| Findings | CLU-018 Data nodes are unevenly spread across availability zones / CLU-019 Shard allocation awareness not set |
| Evidence basis | Official / Tool threshold |
| Possible severities | Warning |
| Required input | (nodes.json) and (cluster_settings.json) |
| Source files | cluster_settings.json / nodes.json / nodes.json |

**Decision logic**

Rated only when the data nodes have 2 or more distinct zone attribute values (availability_zone / zone / logical_availability_zone / rack_id). Node count per zone: max - min >= 2 or max >= min x 2 → Warning (CLU-018). awareness.attributes not set → Warning (CLU-019).

### CLU-020: Shard recovery in progress

| Item | Details |
| --- | --- |
| Function | `cluster.r_recovery_inflight` |
| Evidence basis | Reported fact |
| Possible severities | Info |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (recovery.json) |
| Source files | recovery.json |

**Decision logic**

Info if recovery.json has any shard with stage != DONE.

## Settings changes (versus defaults)

### SET-001, SET-002: Cluster settings changed from the default

| Item | Details |
| --- | --- |
| Function | `settings.r_cluster_setting_changes` |
| Findings | SET-001 Cluster settings changed from the default / SET-002 Cluster settings explicitly set to the default value |
| Evidence basis | Official |
| Possible severities | Info, OK |
| Required input | (cluster_settings.json) |
| Source files | cluster_settings.json |

**Decision logic**

Compares every cluster setting explicitly set in persistent / transient with the official default.

For settings whose default is registered in the official docs (settings_kb), reports 'original default / direction (↑↓) / impact of the change' (SET-001);
for unregistered settings, reports only the value as 'no description registered'. A value identical to the default is reported separately as Info (SET-002, 'same as default').
Severity is the highest risk among the change directions of the registered settings (Warning at most). Settings judged by a dedicated rule (CLU-011 and others) are listed but left out of the severity.
No changes → OK.

### SET-003: elasticsearch.yml value is overridden by the cluster settings API

| Item | Details |
| --- | --- |
| Function | `settings.r_yml_shadowed` |
| Evidence basis | Official |
| Possible severities | Info |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (cluster_settings.json) and (nodes.json) |
| Source files | nodes.json / cluster_settings.json |

**Decision logic**

Checks whether a value in elasticsearch.yml (node settings) is shadowed by persistent/transient.

If the same key is set in both node settings and cluster API settings with different values, the API value applies per the official precedence
and the yml value is ignored (Info). This tells you when editing the yml has no effect.

### SET-004: Node settings changed from the default (elasticsearch.yml)

| Item | Details |
| --- | --- |
| Function | `settings.r_node_setting_changes` |
| Evidence basis | Official |
| Possible severities | Info |
| Required input | (nodes.json) |
| Source files | nodes.json |

**Decision logic**

Checks whether node settings (elasticsearch.yml, including static ones) with a registered official default differ from that default.

Node-specific settings (name, paths, network, security certificates, etc.) are excluded. Values are collected across nodes and reported per setting and value;
severity is the highest risk among the change directions (Warning at most, settings with a dedicated rule excluded). node.processors, thread_pool.write.size and thread_pool.search.size
are not treated as changes when they equal the value derived from the allocated CPU count. If ECH/ECE/ECK is detected, the values are treated as platform-managed and reduced to Info.
A static setting needs a yml edit and a restart on every target node.

### SET-005: Settings differ across data nodes

| Item | Details |
| --- | --- |
| Function | `settings.r_node_setting_consistency` |
| Evidence basis | Official |
| Possible severities | Warning |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (nodes.json) |
| Source files | nodes.json |

**Decision logic**

Checks whether settings that should match across nodes (indexing buffer, caches, thread pools, search, transport, etc.) differ between nodes or are set on only some nodes.

The scope is explicitly set keys under _CONSISTENCY_PREFIX, minus node-specific settings. Only data nodes are compared with each other (all nodes if no data nodes are identified;
differences between nodes with different roles can be normal). A setting missing on some nodes counts as a difference. Any mismatch → Warning.

### SET-006: Index settings changed from the default

| Item | Details |
| --- | --- |
| Function | `settings.r_index_setting_changes` |
| Evidence basis | Official |
| Possible severities | Info |
| Required input | (settings.json) |
| Source files | settings.json |

**Decision logic**

Counts, per setting and value, the explicitly set settings of user indices that have a registered official default and differ from it.

Identity information added automatically at index creation (uuid, creation_date, version, provided_name, number_of_shards,
tier preference, etc.) has no registered default, so it is naturally excluded. System indices are excluded.
Severity is the highest risk among the change directions (Warning at most, settings with a dedicated rule excluded).

## Nodes (JVM, OS, disk, thread pools)

### JVM-001: Heap usage is OK

| Item | Details |
| --- | --- |
| Function | `nodes.r_heap_usage` |
| Evidence basis | Tool threshold |
| Possible severities | Critical, Warning, OK |
| Thresholds | `heap_used_pct_crit` = 85 ([Tool] Heap usage at collection time)<br>`heap_used_pct_warn` = 75 ([Tool] Heap usage at collection time) |
| Required input | (nodes_stats.json) |
| Source files | nodes_stats.json |
| References | [Heap size settings](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/important-settings-configuration) |

**Decision logic**

Per-node jvm.mem.heap_used_percent (point-in-time at collection). >= heap_used_pct_crit → Critical, >= heap_used_pct_warn → Warning, otherwise OK.

### JVM-002, JVM-003, JVM-004: Heap above the 32GB boundary (compressed oops may be lost)

| Item | Details |
| --- | --- |
| Function | `nodes.r_heap_sizing` |
| Findings | JVM-002 Heap above the 32GB boundary (compressed oops may be lost) / JVM-003 Heap too large relative to physical memory / JVM-004 Xms and Xmx differ |
| Evidence basis | Official |
| Possible severities | Warning |
| Thresholds | `heap_max_bytes_crit` = 32GiB ([Official] Compressed oops boundary (below 32GB recommended))<br>`heap_vs_ram_pct_warn` = 50 ([Official] Heap <= 50% of total memory)<br>`heap_vs_ram_tolerance_pct` = 2 ([Tool] Tolerance for rounding and adjusted_total error) |
| Required input | (nodes.json) and (nodes_stats.json) |
| Source files | nodes.json / nodes.json / nodes_stats.json |
| References | [Heap size settings](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/important-settings-configuration) |

**Decision logic**

heap_max >= heap_max_bytes_crit (32GiB) or using_compressed_ordinary_object_pointers=false → Warning (JVM-002). heap_max / os.mem.adjusted_total > heap_vs_ram_pct_warn + heap_vs_ram_tolerance_pct → Warning (JVM-003). heap_init (Xms) != heap_max (Xmx) → Warning (JVM-004).

### JVM-005: GC load is within the normal range

| Item | Details |
| --- | --- |
| Function | `nodes.r_gc` |
| Evidence basis | Tool threshold |
| Possible severities | Critical, Warning, OK |
| Thresholds | `old_gc_per_hour_crit` = 30 ([Tool] Old GC count per hour)<br>`old_gc_per_hour_warn` = 6 ([Tool] Old GC count per hour)<br>`old_gc_time_ratio_crit` = 0.05 ([Tool] Cumulative old GC time / uptime)<br>`old_gc_time_ratio_warn` = 0.02 ([Tool] Cumulative old GC time / uptime)<br>`young_gc_time_ratio_warn` = 0.05 ([Tool] Cumulative young GC time / uptime) |
| Required input | (nodes_stats.json) |
| Source files | nodes_stats.json |

**Decision logic**

old share = old collection_time / uptime, old GC per hour = old count / uptime (h), young share = young time / uptime. old share >= old_gc_time_ratio_crit or per-hour >= old_gc_per_hour_crit → Critical. Any of old share >= warn, per-hour >= warn, or young share >= young_gc_time_ratio_warn → Warning. Otherwise OK. These are cumulative values, so compare mode (DIF-006) is more accurate.

### OS-001, OS-002, OS-003, OS-004, OS-005, OS-006, OS-007: High CPU load

| Item | Details |
| --- | --- |
| Function | `nodes.r_os` |
| Findings | OS-001 High CPU load / OS-002 Swap enabled / OS-003 Container CPU throttling occurred / OS-004 High file descriptor usage / OS-005 bootstrap.memory_lock not applied / OS-006 Recently restarted nodes / OS-007 Most nodes restarted recently |
| Evidence basis | Official / Tool threshold |
| Possible severities | Critical, Warning, Info |
| Thresholds | `cgroup_throttle_ratio_crit` = 0.05 ([Tool] throttled / elapsed periods)<br>`cgroup_throttle_ratio_warn` = 0.01 ([Tool] throttled / elapsed periods)<br>`fd_used_pct_warn` = 70 ([Tool] Open files / maximum (official minimum limit is 65,535))<br>`load_host_cpu_pct_max` = 20 ([Tool] Container nodes below this CPU percentage are not rated on load average)<br>`load_per_cpu_crit` = 1.5 ([Tool] load15 / CPU cores)<br>`load_per_cpu_warn` = 1.0 ([Tool] load15 / CPU cores)<br>`restart_share_warn` = 0.5 ([Tool] Share of nodes restarted within uptime_short_hours)<br>`uptime_short_hours` = 6 ([Tool] Treats the node as recently restarted) |
| Required input | (nodes_stats.json) |
| Source files | nodes.json / nodes_stats.json |

**Decision logic**

load15 / available_processors >= load_per_cpu_crit → Critical, >= warn → Warning (OS-001, nodes in both ranges are listed). A container node (os.cgroup present) with cpu% below load_host_cpu_pct_max is not rated: inside a container the load average can be the host's, so it is listed as Info. swap_total > 0 and mlockall is not true → Warning (OS-002). cgroup throttled / elapsed_periods >= cgroup_throttle_ratio_crit → Critical, >= warn → Warning (OS-003). open_fd / max_fd >= fd_used_pct_warn → Warning (OS-004). mlockall=false and no swap → Info (OS-005). uptime < uptime_short_hours → Warning (OS-006). restart_share_warn or more of the nodes restarted within uptime_short_hours → Warning (OS-007): cumulative counters (GC, rejections, cache, latency averages) then cover only a short window.

### DISK-001, DISK-002, DISK-003, DISK-004, DISK-005: Disk flood stage exceeded

| Item | Details |
| --- | --- |
| Function | `nodes.r_disk` |
| Findings | DISK-001 Disk flood stage exceeded / DISK-002 Disk high watermark exceeded / DISK-003 Disk low watermark exceeded / DISK-004 Disk usage approaching the low watermark / DISK-005 Disk usage spread across nodes in the same tier |
| Evidence basis | Official / Tool threshold |
| Possible severities | Critical, Warning, OK |
| Thresholds | `disk_imbalance_pct_warn` = 15 ([Tool] Disk usage spread between nodes (percentage points))<br>`disk_low_margin_pct` = 10 ([Tool] Percentage points left before the effective low watermark) |
| Required input | (nodes_stats.json) |
| Source files | nodes_stats.json |
| References | [Disk-based shard allocation (watermarks)](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |

**Decision logic**

Data node usage = 1 - available / total. Against the effective watermarks (max_headroom applied, context.watermark_used_pct): at or above flood → Critical (DISK-001), at or above high → Critical (DISK-002), at or above low → Warning (DISK-003), at or above low - disk_low_margin_pct → Warning (DISK-004, only when none of the first three apply). Usage spread between nodes (max - min) >= disk_imbalance_pct_warn → Warning (DISK-005). Nothing applies → OK.

### TP-001, TP-002: Thread pool rejections occurred

| Item | Details |
| --- | --- |
| Function | `nodes.r_thread_pools` |
| Findings | TP-001 Thread pool rejections occurred / TP-002 Queue backlog at collection time |
| Evidence basis | Reported fact |
| Possible severities | Critical, Warning, Info, OK |
| Thresholds | `rejected_crit` = 1,000 ([Tool] Total cumulative rejections)<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (nodes_stats.json) |
| Source files | nodes_stats.json |
| References | [Thread pools and rejections](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings) |

**Decision logic**

Cumulative rejected count across all thread pools. Sum > 0 → Warning; sum >= rejected_crit and the queue > 0 on a pool that was rejecting at collection time → Critical (cumulative values alone never raise it to Critical); 0 → OK (TP-001). Queue > 0 on a main pool (write/search/get, etc.) → Info (TP-002).

### BRK-001, BRK-002: Circuit breaker trip history

| Item | Details |
| --- | --- |
| Function | `nodes.r_breakers` |
| Findings | BRK-001 Circuit breaker trip history / BRK-002 High circuit breaker usage |
| Evidence basis | Reported fact / Tool threshold |
| Possible severities | Critical, Warning |
| Thresholds | `breaker_tripped_warn` = 1 ([Tool] Breaker trip count (1 = any history)) |
| Required input | (nodes_stats.json) |
| Source files | nodes_stats.json |

**Decision logic**

breaker.tripped >= breaker_tripped_warn → Warning; Critical if usage at collection time is also 70% or more (BRK-001; the cumulative trip history alone never raises it to Critical). No trip history and estimated / limit >= 70% → Warning (BRK-002).

### IP-001: Indexing pressure rejection

| Item | Details |
| --- | --- |
| Function | `nodes.r_indexing_pressure` |
| Evidence basis | Reported fact |
| Possible severities | Warning |
| Required input | (nodes_stats.json) |
| Source files | nodes_stats.json |

**Decision logic**

Warning if any of the *_rejections (coordinating/primary/replica) under indexing_pressure.memory.total is > 0.

### FD-001, FD-002: fielddata uses a large share of the heap

| Item | Details |
| --- | --- |
| Function | `nodes.r_fielddata` |
| Findings | FD-001 fielddata uses a large share of the heap / FD-002 Top fielddata consumers |
| Evidence basis | Reported fact / Tool threshold |
| Possible severities | Warning, Info |
| Thresholds | `fielddata_heap_pct_warn` = 10 ([Tool] fielddata / heap)<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (nodes_stats.json) |
| Source files | fielddata.json / nodes_stats.json |

**Decision logic**

Node fielddata memory / heap_max >= fielddata_heap_pct_warn → Warning (FD-001). Largest field in fielddata.json above 64MB → Info (FD-002).

### ING-001: Ingest pipeline failures

| Item | Details |
| --- | --- |
| Function | `nodes.r_ingest_failures` |
| Evidence basis | Reported fact |
| Possible severities | Warning |
| Thresholds | `ingest_failed_warn` = 1 ([Tool])<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (nodes_stats.json) |
| Source files | nodes_stats.json |

**Decision logic**

Warning if any node has ingest.total.failed >= ingest_failed_warn. The count per failing pipeline is shown as evidence.

### NODE-001, NODE-003: Uneven node specs within the same tier

| Item | Details |
| --- | --- |
| Function | `nodes.r_node_heterogeneity` |
| Findings | NODE-001 Uneven node specs within the same tier / NODE-003 Node specs per tier |
| Evidence basis | Reported fact / Tool threshold |
| Possible severities | Warning, Info |
| Required input | (nodes.json) and (nodes_stats.json) |
| Source files | nodes.json / nodes.json / nodes_stats.json |

**Decision logic**

Different heap or CPU count within the same tier (data role combination) → Warning (NODE-001).

Different specs across tiers are normal design, so differences between tiers are not rated; only a spec table per tier is reported as Info
(NODE-003). Within a tier, shards are spread evenly, so the smaller node saturates first and sets the processing limit of that tier.

### PERF-012: Slow average flush, refresh or merge

| Item | Details |
| --- | --- |
| Function | `nodes.r_write_latency` |
| Evidence basis | Tool threshold |
| Possible severities | Warning, Info |
| Thresholds | `flush_avg_ms_info` = 800 ([Tool] Field baseline: average flush time per flush)<br>`flush_avg_ms_warn` = 1,200 ([Tool] Field baseline)<br>`merge_avg_ms_info` = 20,000 ([Tool] Field baseline: average merge time per merge)<br>`merge_avg_ms_warn` = 40,000 ([Tool] Field baseline)<br>`refresh_avg_ms_info` = 40 ([Tool] Field baseline: average refresh time per refresh)<br>`refresh_avg_ms_warn` = 70 ([Tool] Field baseline)<br>`write_latency_min_ops` = 100 ([Tool] Minimum flushes/refreshes/merges before a node average is rated) |
| Source files | nodes_stats.json (indices.flush / refresh / merges) |

**Decision logic**

Average flush, refresh and merge time per node (nodes_stats indices.flush/refresh/merges total_time / total).

Only nodes that hold write-target shards are rated. On a node without them, merges come from a force merge (ILM forcemerge,
the force merge that searchable_snapshot runs in the preceding phase by default, or a manual _forcemerge) or from merges
finishing after rollover. Those merge large segments, so a long average there does not mean slow storage.
Any metric with fewer than write_latency_min_ops operations is skipped.
Average >= *_avg_ms_warn → Warning, >= *_avg_ms_info → Info (PERF-012). These are field baselines, not official numbers,
and cumulative averages since node start. Slow flushes and merges usually point to storage that cannot keep up;
read them with IDX-005 (merge throttling) and IDX-014 (indexing throttled).

## Shards and indices

### SHD-001: Too many shards per node (guideline for versions before 8.3)

| Item | Details |
| --- | --- |
| Function | `shards.r_shard_density` |
| Evidence basis | Official |
| Possible severities | Critical, Warning, Info, OK |
| Thresholds | `shards_per_gb_heap_crit` = 30 ([Tool] Versions before 8.3 only)<br>`shards_per_gb_heap_warn` = 20 ([Official] 20 shards per 1GB of heap (versions before 8.3 only)) |
| Required input | (indices.json or shards.json or cat_shards.txt) and (nodes.json) |
| Source files | indices.json / nodes_stats.json |
| References | [Shard sizing guide](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**Decision logic**

Shard density per node.

'20 shards per 1GB of heap' is the official guideline for versions before 8.3. From 8.3 the heap overhead per shard dropped sharply,
and the official docs retired this guideline in favor of the 'field mapper heap estimate (SHD-010)' and cluster.max_shards_per_node (CLU-015).
So on 8.3 or later it is not rated and only the current numbers are shown.

### SHD-006: Uneven shard count across nodes in the same tier

| Item | Details |
| --- | --- |
| Function | `shards.r_shard_balance` |
| Evidence basis | Tool threshold |
| Possible severities | Warning |
| Required input | (indices.json or shards.json or cat_shards.txt) |
| Source files | indices.json / nodes.json |

**Decision logic**

Warning if the spread in shard count between nodes within the same tier is 25% of the average or more.

Each tier holds different data and has a different node count, so differences in shard count between tiers are normal and are not compared.

### IDX-010: Unhealthy data streams

| Item | Details |
| --- | --- |
| Function | `shards.r_data_stream_health` |
| Evidence basis | Reported fact |
| Possible severities | Critical, Warning |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (data_stream.json) |
| Source files | commercial/data_stream.json |

**Decision logic**

data stream status RED → Critical, YELLOW → Warning.

### PERF-003: Low cache hit rate with excessive evictions

| Item | Details |
| --- | --- |
| Function | `shards.r_cache_efficiency` |
| Evidence basis | Tool threshold |
| Possible severities | Warning, Info |
| Required input | (indices_stats.json) |
| Source files | indices_stats.json |

**Decision logic**

Efficiency of the query cache and the shard request cache.

### SHD-002, SHD-003: Very large shards

| Item | Details |
| --- | --- |
| Function | `shards.r_shard_size` |
| Findings | SHD-002 Very large shards / SHD-003 Large shards |
| Evidence basis | Official / Tool threshold |
| Possible severities | Critical, Warning |
| Thresholds | `shard_size_gb_crit` = 200 ([Tool] Upper bound based on recovery time)<br>`shard_size_gb_warn` = 50 ([Official] Shards of 10-50GB)<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (indices.json or shards.json or cat_shards.txt) |
| Source files | indices.json |
| References | [Shard sizing guide](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**Decision logic**

Primary shard store >= shard_size_gb_crit → Critical (SHD-002), >= shard_size_gb_warn (official upper bound 50GB) → Warning (SHD-003).

### SHD-004: Too many small shards

| Item | Details |
| --- | --- |
| Function | `shards.r_small_shards` |
| Evidence basis | Tool threshold |
| Possible severities | Warning |
| Thresholds | `small_shard_count_warn` = 50 ([Tool])<br>`small_shard_mb` = 1,024 ([Tool] Small shard threshold)<br>`small_shard_ratio_warn` = 0.5 ([Tool])<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (indices.json or shards.json or cat_shards.txt) |
| Source files | indices.json |
| References | [Shard sizing guide](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**Decision logic**

Warning if user-index primaries with store < small_shard_mb number at least small_shard_count_warn, and small primaries make up at least small_shard_ratio_warn of all primaries. System indices do not count toward the shard-count condition because users cannot tune them.

### IDX-001: Indices with 0 replicas

| Item | Details |
| --- | --- |
| Function | `shards.r_replica_zero` |
| Evidence basis | Tool threshold |
| Possible severities | Warning |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (settings.json) and (indices_stats.json) |
| Source files | settings.json / indices_stats.json |

**Decision logic**

User indices with number_of_replicas=0, no auto_expand_replicas, and not a searchable snapshot index → Warning.

### IDX-002: Replica count exceeds the number of data nodes

| Item | Details |
| --- | --- |
| Function | `shards.r_replica_unassignable` |
| Evidence basis | Reported fact |
| Possible severities | Warning |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (settings.json) and (nodes.json) |
| Source files | settings.json |

**Decision logic**

number_of_replicas > (number of data nodes - 1) → Warning (replicas stay unassigned permanently). Indices with auto_expand_replicas are excluded. The node count per tier is not checked, so the rating is conservative (it can miss cases but never raises a false alarm).

### IDX-003: High deleted-document ratio

| Item | Details |
| --- | --- |
| Function | `shards.r_deleted_docs` |
| Evidence basis | Tool threshold |
| Possible severities | Warning |
| Thresholds | `deleted_docs_ratio_warn` = 0.25 ([Tool])<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (indices_stats.json) |
| Source files | indices_stats.json |

**Decision logic**

For indices with primary store >= 1GB, deleted / (docs + deleted) >= deleted_docs_ratio_warn → Warning.

### IDX-004: Too many segments per shard

| Item | Details |
| --- | --- |
| Function | `shards.r_segments` |
| Evidence basis | Tool threshold |
| Possible severities | Warning |
| Thresholds | `segments_per_shard_warn` = 50 ([Tool])<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (indices_stats.json) and (indices.json or shards.json or cat_shards.txt) |
| Source files | indices_stats.json |

**Decision logic**

Primary segments / primary shards >= segments_per_shard_warn and primary store > 100MB → Warning.

### IDX-005: Merge throttling observed

| Item | Details |
| --- | --- |
| Function | `shards.r_merge_throttle` |
| Evidence basis | Tool threshold |
| Possible severities | Warning |
| Thresholds | `merge_throttle_ratio_warn` = 0.05 ([Tool])<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (indices_stats.json) |
| Source files | indices_stats.json |

**Decision logic**

merges.total_throttled_time / merges.total_time >= merge_throttle_ratio_warn and cumulative throttled time > 60 seconds → Warning.

### PERF-001, PERF-002: Indices with high average search latency

| Item | Details |
| --- | --- |
| Function | `shards.r_search_latency` |
| Findings | PERF-001 Indices with high average search latency / PERF-002 Indices with high average indexing latency |
| Evidence basis | Tool threshold |
| Possible severities | Critical, Warning |
| Thresholds | `index_latency_ms_crit` = 200 ([Tool] Average indexing time per document)<br>`index_latency_ms_warn` = 50 ([Tool] Average indexing time per document)<br>`min_query_total_for_latency` = 100 ([Tool] Indices with too few samples are not rated)<br>`search_latency_ms_crit` = 1,000 ([Tool] Average query latency per index)<br>`search_latency_ms_warn` = 200 ([Tool] Average query latency per index)<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (indices_stats.json) |
| Source files | indices_stats.json |

**Decision logic**

For indices with query_total >= min_query_total_for_latency, average query latency = query_time / query_total. >= search_latency_ms_crit → Critical, >= warn → Warning (PERF-001). Average indexing time per document = index_time / index_total is rated the same way with index_latency_ms_crit / warn (PERF-002). These are cumulative averages, not p99. Partially mounted (frozen) indices are not rated for search latency: they read from the snapshot repository on cache misses, so slower searches are expected there (see FRZ-001).

### IDX-006: Index/search failure counters are non-zero

| Item | Details |
| --- | --- |
| Function | `shards.r_index_failures` |
| Evidence basis | Reported fact |
| Possible severities | Warning, Info |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (indices_stats.json) |
| Source files | indices_stats.json |

**Decision logic**

Indices with indexing.index_failed or search.query_failure > 0. Warning if user indices are included, Info if only system indices are.
Sorted by the failure ratio, index_failed / (index_failed + index_total), so indices that lose a large share of their writes come first.

### MAP-001, MAP-002: Indices with a raised mapping field limit

| Item | Details |
| --- | --- |
| Function | `shards.r_mapping_limits` |
| Findings | MAP-001 Indices with a raised mapping field limit / MAP-002 Total fields in the cluster |
| Evidence basis | Tool threshold |
| Possible severities | Warning, Info |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (settings.json) |
| Source files | cluster_stats.json / settings.json |
| References | [Preventing mapping explosion](https://www.elastic.co/docs/manage-data/data-store/mapping) |

**Decision logic**

User index with mapping.total_fields.limit > 1000 (the default) → Warning (MAP-001), or Info if all such indices have ignore_dynamic_beyond_limit=true. Searchable snapshot mounts are skipped (read-only). Total field count in cluster_stats > 100,000 → Info (MAP-002).

### IDX-007: Heavily indexed indices with refresh_interval explicitly set to 1s or less

| Item | Details |
| --- | --- |
| Function | `shards.r_refresh_interval` |
| Evidence basis | Official |
| Possible severities | Info |
| Thresholds | `heavy_index_docs` = 10,000,000 ([Tool] Threshold for a heavily indexed index)<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (settings.json) and (indices_stats.json) |
| Source files | settings.json / indices_stats.json |

**Decision logic**

Refresh interval.

Indices without an explicit refresh_interval use the search idle behavior.
A shard with no search for index.search.idle.after (default 30s) skips the periodic refresh,
so 'not set' does not mean 'refresh every second'. Therefore only indices that explicitly set 1s or less are rated.

### IDX-008, IDX-011: Write block on a write target or left by flood stage

| Item | Details |
| --- | --- |
| Function | `shards.r_read_only_blocks` |
| Findings | IDX-008 Write block on a write target or left by flood stage / IDX-011 Write block on standalone index (confirm intent) |
| Evidence basis | Reported fact |
| Possible severities | Critical, Info, OK |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (settings.json) |
| Source files | settings.json / alias.json / settings.json / data_stream.json / alias.json |

**Decision logic**

Separates write blocks on indices into 'expected blocks' and 'problem blocks'.

Expected (not rated, count shown as Info): searchable snapshot mounted indices and indices that have finished rollover
(old backing indices of a data stream, alias members that are not the write target, indexing_complete=true).
It is normal for the ILM readonly, shrink, forcemerge and searchable_snapshot phases to put a write block on an index after rollover.
Problem (Critical, IDX-008): index.blocks.read_only_allow_delete=true (usually left over from flood stage, applies to all indices),
or a write/read_only block on a current write target (data stream write index / alias write index).
Needs checking (Info, IDX-011): a write/read_only block on a standalone index that belongs to no data stream or alias (may be intentional archiving).

### IDX-009: Indices that require a data tier that does not exist

| Item | Details |
| --- | --- |
| Function | `shards.r_tier_preference` |
| Evidence basis | Reported fact |
| Possible severities | Critical |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (settings.json) and (nodes.json) |
| Source files | settings.json / nodes.json |

**Decision logic**

Whether the data tier an index requires actually exists on the nodes.

### SHD-005: Index/shard scale summary

| Item | Details |
| --- | --- |
| Function | `shards.r_index_count` |
| Evidence basis | Tool threshold |
| Possible severities | Warning, Info |
| Required input | (cluster_stats.json) |
| Source files | cluster_stats.json |
| References | [Shard sizing guide](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**Decision logic**

Average size per shard (store / shards) < 200MB, shards >= 300, and total store > 50GB → Warning. Otherwise only a size summary is shown as Info.

### SHD-016: Write-target shards concentrated on some nodes

| Item | Details |
| --- | --- |
| Function | `shards.r_write_hotspot` |
| Evidence basis | Tool threshold |
| Possible severities | Warning |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table)<br>`write_shard_skew_min` = 3 ([Tool] Minimum difference in write-target shards before it is reported)<br>`write_shard_skew_warn` = 0.5 ([Tool] (max - min) / average of write-target shards per node in a tier) |
| Source files | indices.json / data_stream.json / alias.json / indices_stats.json |

**Decision logic**

Write-target shards per node within a tier (SHD-016).

Write targets are data stream write indices, alias write indices and indices indexing at collection time; replicas count
because they index too. Per tier (frozen skipped, tiers with fewer than 2 nodes skipped):
(max - min) / average >= write_shard_skew_warn and max - min >= write_shard_skew_min → Warning. SHD-006 compares all shards;
this one compares only shards that take writes, which is where indexing load lands.

### IDX-014: Indexing throttled because merges fell behind

| Item | Details |
| --- | --- |
| Function | `shards.r_indexing_throttle` |
| Evidence basis | Reported fact |
| Possible severities | Warning, Info |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Source files | indices_stats.json |
| References | [Merge settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/merge) |

**Decision logic**

Indexing throttled because merges fell behind (IDX-014).

Official: once merging is fully unthrottled and still behind, indexing for the shard is throttled until merges catch up.
indices_stats indexing.is_throttled = true at collection time → Warning. Only cumulative indexing.throttle_time > 0 → Info.

### IDX-015: Uncommitted translog above the flush threshold

| Item | Details |
| --- | --- |
| Function | `shards.r_translog_uncommitted` |
| Evidence basis | Official |
| Possible severities | Warning |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table)<br>`translog_flush_threshold_default` = 10gb ([Official] index.translog.flush_threshold_size default (8.8+))<br>`translog_flush_threshold_legacy` = 512mb ([Official] Default before 8.8) |
| Source files | indices_stats.json / settings.json |
| References | [Translog settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/translog) |

**Decision logic**

Uncommitted translog per shard copy against index.translog.flush_threshold_size (IDX-015).

Official: a flush runs once the uncommitted translog reaches flush_threshold_size (default 10GB), and uncommitted
operations are replayed on recovery (the default was 512MB before 8.8). Average uncommitted size per shard copy (index total / copies) at or above the
effective threshold → Warning: flushes are not keeping up, and recovery of those shards will replay that much.

## Oversharding and small shards

### OVS-001: Oversharding per index

| Item | Details |
| --- | --- |
| Function | `sharding.r_index_oversharding` |
| Evidence basis | Official |
| Possible severities | Warning, Info |
| Thresholds | `oversharding_excess_ratio_warn` = 0.1 ([Tool] Share of all shards)<br>`oversharding_excess_warn` = 20 ([Tool] Total number of shards that could be removed)<br>`oversharding_floor_shard_gb` = 10 ([Official] Recommended lower bound per shard, 10GB)<br>`oversharding_target_shard_gb` = 50 ([Official] Recommended upper bound per shard, 50GB (used for the recommended primary count))<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (indices_stats.json) and (indices.json or shards.json or cat_shards.txt) |
| Source files | indices_stats.json / indices.json / settings.json / indices_stats.json / settings.json |
| References | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**Decision logic**

Oversharding per index.

Scope: user indices with primary >= 2 that are not a data stream write index or a searchable snapshot.
Fully mounted (cold) indices have an accurate size but cannot be shrunk, so only the number of oversharded ones is counted, with guidance on fixing the cause.
Rating: average size per primary shard < oversharding_floor_shard_gb (official lower bound 10GB) means oversharded.
Recommended primary count = max(1, ceil(total primary size / oversharding_target_shard_gb (official upper bound 50GB)))
(the smallest count that keeps each shard at or under 50GB). Excess shards = (current - recommended) × (1 + replica).
Excess shard total >= oversharding_excess_warn or share of all shards >= oversharding_excess_ratio_warn → Warning;
any other indices in scope → Info.

### OVS-002: Too many rollovers in data streams (small backing indices piling up)

| Item | Details |
| --- | --- |
| Function | `sharding.r_datastream_small_rollover` |
| Evidence basis | Tool threshold |
| Possible severities | Warning |
| Thresholds | `ds_min_backing_indices` = 5 ([Tool] Minimum backing index count for the data stream rating)<br>`ds_small_backing_shard_gb` = 1 ([Tool] Median backing shard size threshold)<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (data_stream.json) and (indices_stats.json) |
| Source files | data_stream.json / indices_stats.json |
| References | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**Decision logic**

Checks whether a data stream rolls over too often and small backing indices pile up.

Excluding the write index and partial (frozen) mounted backing indices (whose size is the cache size), if there are
ds_min_backing_indices or more backing indices and the median size per primary shard is
below ds_small_backing_shard_gb → Warning. This is the typical sign of rollover happening on max_age only.

### OVS-003: User shard size distribution

| Item | Details |
| --- | --- |
| Function | `sharding.r_shard_size_distribution` |
| Evidence basis | Tool threshold |
| Possible severities | Warning, Info |
| Thresholds | `oversharding_min_data_gb` = 100 ([Tool] Small clusters are not rated on distribution)<br>`oversharding_min_shards` = 20 ([Tool] Minimum sample size for the distribution rating)<br>`oversharding_small_share_warn` = 0.8 ([Tool] Share of shards under 10GB) |
| Required input | (indices.json or shards.json or cat_shards.txt) |
| Source files | indices.json |
| References | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**Decision logic**

Reports the size distribution of user index primary shards (<1GB / 1-10GB / 10-50GB / 50GB+) as plain facts.

If user primaries with data (at least 1 document; searchable snapshot mounts and write indices excluded) number oversharding_min_shards or more,
the share under 10GB is >= oversharding_small_share_warn, and the total user data is at least oversharding_min_data_gb,
it is a Warning for a 'cluster-wide oversharding trend'. If the conditions are not met, only the distribution is shown as Info.

## Official guidance baselines (settings, shards, performance, disk, vectors)

### GEN-001: Indices with a raised max_result_window

| Item | Details |
| --- | --- |
| Function | `guidance.r_large_result_sets` |
| Evidence basis | Official |
| Possible severities | Warning |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (settings.json) |
| Source files | settings.json |
| References | [General recommendations](https://www.elastic.co/docs/deploy-manage/production-guidance/general-recommendations) |

**Decision logic**

Whether max_result_window has been raised (user indices).

### GEN-002, GEN-003: http.max_content_length raised

| Item | Details |
| --- | --- |
| Function | `guidance.r_large_documents` |
| Findings | GEN-002 http.max_content_length raised / GEN-003 Indices with a large average document size |
| Evidence basis | Official / Tool threshold |
| Possible severities | Warning, Info |
| Thresholds | `avg_doc_bytes_warn` = 1MiB ([Tool] Average document size of 1MB)<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (nodes.json) and (indices_stats.json) |
| Source files | indices_stats.json / nodes.json |
| References | [General recommendations](https://www.elastic.co/docs/deploy-manage/production-guidance/general-recommendations) |

**Decision logic**

Whether http.max_content_length has been raised, and the average document size.

### CFG-001: cluster.name is the default

| Item | Details |
| --- | --- |
| Function | `guidance.r_cluster_name` |
| Evidence basis | Official |
| Possible severities | Warning |
| Required input | (cluster_health.json) |
| Source files | cluster_health.json |
| References | [Important settings configuration](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/important-settings-configuration) |

**Decision logic**

Warning if cluster.name is the default 'elasticsearch'. Info if ECH/ECE/ECK is detected.

### CFG-002, CFG-003: data/logs paths are inside the ES install directory (archive install)

| Item | Details |
| --- | --- |
| Function | `guidance.r_path_settings` |
| Findings | CFG-002 data/logs paths are inside the ES install directory (archive install) / CFG-003 Multiple path.data paths in use |
| Evidence basis | Official |
| Possible severities | Warning |
| Required input | (nodes.json) |
| Source files | nodes.json |
| References | [Important settings configuration](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/important-settings-configuration) |

**Decision logic**

Location of path.data/path.logs.

The concern in the official docs is archive (tar.gz/zip) installs, where an upgrade replaces $ES_HOME
and deletes the data with it. rpm/deb already default to external paths (/var/lib, /var/log), and docker
mounts a volume, so neither is affected. The install type is determined from build_type.

### CFG-004, CFG-005, CFG-006: discovery.seed_hosts is not set

| Item | Details |
| --- | --- |
| Function | `guidance.r_discovery` |
| Findings | CFG-004 discovery.seed_hosts is not set / CFG-005 cluster.initial_master_nodes is still set / CFG-006 Nodes running in development mode |
| Evidence basis | Official |
| Possible severities | Warning |
| Required input | (nodes.json) |
| Source files | nodes.json / nodes.json (transport_address) |
| References | [Important settings configuration](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/important-settings-configuration) |

**Decision logic**

Multi-node cluster without discovery.seed_hosts / seed_providers → Warning (CFG-004). cluster.initial_master_nodes still set → Warning (CFG-005). Actual bound transport_address is loopback or discovery.type=single-node → Warning (CFG-006). On orchestrator deployments all of these drop to Info.

### CFG-007, CFG-008, CFG-009: No OOM heap dump setting

| Item | Details |
| --- | --- |
| Function | `guidance.r_jvm_diag_settings` |
| Findings | CFG-007 No OOM heap dump setting / CFG-008 GC log file output is disabled / CFG-009 JVM fatal error log path is not set |
| Evidence basis | Official |
| Possible severities | Warning, Info |
| Required input | (nodes.json) |
| Source files | nodes.json (jvm.input_arguments) |
| References | [Important settings configuration](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/important-settings-configuration) |

**Decision logic**

Based on jvm.input_arguments. No HeapDumpOnOutOfMemoryError → Warning (CFG-007). No gc file logging option after the last -Xlog:disable → Warning (CFG-008). No ErrorFile → Info (CFG-009). On orchestrator deployments these drop to Info.

### SHD-007, SHD-008, SHD-013: Shard document count close to the Lucene limit

| Item | Details |
| --- | --- |
| Function | `guidance.r_docs_per_shard` |
| Findings | SHD-007 Shard document count close to the Lucene limit / SHD-008 Documents per shard above the recommended value / SHD-013 Shards that rolled over late |
| Evidence basis | Official / Tool threshold |
| Possible severities | Critical, Warning |
| Thresholds | `docs_per_shard_crit` = 1,500,000,000 ([Tool] Alert when approaching the Lucene limit (2,147,483,519))<br>`docs_per_shard_warn` = 200,000,000 ([Official] Fewer than 200 million documents per shard recommended)<br>`docs_rollover_overshoot_pct` = 5 ([Tool] Allowed overshoot of a rolled-over shard past 200M docs (ILM checks every poll_interval))<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (indices.json or shards.json or cat_shards.txt) and (indices_stats.json) |
| Source files | indices.json / indices.json / commercial/ilm_explain.json |
| References | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards)<br>[Rollover (ILM): max_primary_shard_docs](https://www.elastic.co/docs/reference/elasticsearch/index-lifecycle-actions/ilm-rollover)<br>[ILM settings: indices.lifecycle.poll_interval](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/index-lifecycle-management-settings) |

**Decision logic**

Document count per shard. Rated on per-shard values (cat shards), not the index average.

The Lucene limit (2,147,483,519) applies to maxDoc, which includes deleted documents. cat shards has no deleted count,
so the index deleted count divided by the number of primaries is added (shown as an estimate).
Rollover always runs once a shard reaches 200M documents, and ILM checks the condition every poll_interval (10m by default),
so a rolled-over index normally ends a little above 200M. Rolled-over indices are reported only when they exceed 200M by more
than docs_rollover_overshoot_pct (SHD-013, rollover ran late). Searchable snapshot mounts take no writes and are rated the same way.
The write index and indices without rollover keep SHD-008.

### SHD-014, SHD-015: logsdb shards above the tool's recommended range

| Item | Details |
| --- | --- |
| Function | `guidance.r_logsdb_shard_size` |
| Findings | SHD-014 logsdb shards above the tool's recommended range / SHD-015 logsdb indices rolled over below the official shard size range |
| Evidence basis | Official / Tool threshold |
| Possible severities | Info |
| Thresholds | `ds_min_backing_indices` = 5 ([Tool] Minimum backing index count for the data stream rating)<br>`ilm_implicit_max_shard_docs` = 200,000,000 ([Official] Rollover always runs at 200M docs per shard; higher values have no effect)<br>`logsdb_rows_max` = 100 ([Tool] Maximum indices listed in the logsdb shard size table)<br>`logsdb_shard_gb_high` = 30 ([Tool] Upper end of the logsdb shard range (official upper bound is 50GB))<br>`logsdb_shard_gb_low` = 10 ([Official] Lower end of the 10-50GB shard range)<br>`shard_size_gb_warn` = 50 ([Official] Shards of 10-50GB) |
| Required input | (indices.json or shards.json or cat_shards.txt) and (settings.json or data_stream.json) |
| Source files | indices.json / settings.json / commercial/data_stream.json / indices.json / settings.json / commercial/data_stream.json / commercial/ilm_policies.json |
| References | [Rollover (ILM): max_primary_shard_docs](https://www.elastic.co/docs/reference/elasticsearch/index-lifecycle-actions/ilm-rollover)<br>[Configure a logs data stream](https://www.elastic.co/docs/manage-data/data-store/data-streams/logs-data-stream-configure)<br>[Index sorting settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/sorting)<br>[Force merge API](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-indices-forcemerge)<br>[Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**Decision logic**

Primary shard size of logsdb indices against the 10-30GB range (tool judgment, Info).

Basis: rollover always runs at 200M documents per shard (official), and the official docs note that space-efficient data
reaches 200M documents before 50GB. logsdb sorts by host.name and @timestamp by default (official), and index sorting
costs time at flush and merge (official). force merge to one segment needs up to 3x the shard size in free space (official),
and large shards take longer to recover (official). The 30GB upper end is not an official number: it follows an Elastic
internal discussion that 10-30GB suits logsdb and TSDB. The official 10-50GB range and SHD-003 (50GB and above) still apply.

Partially mounted (frozen) indices are skipped because their size is the cache size. Per index, the largest primary
shard is rated. logsdb_shard_gb_high <= largest primary < shard_size_gb_warn → SHD-014 (Info, listed per index).
SHD-015 (Info) is rated per data stream: a data stream with ds_min_backing_indices or more finished backing indices
(rolled over or mounted) whose largest primary is below logsdb_shard_gb_low with 1 to 200M documents. Those indices were
ended by max_age or a small size condition, not by the document limit. Empty indices are left to SHD-011.
The rollover condition shown is an estimate (the most common one per data stream for SHD-015).

### IDX-013: logs-*-* data streams not in logsdb mode

| Item | Details |
| --- | --- |
| Function | `guidance.r_logsdb_adoption` |
| Evidence basis | Official |
| Possible severities | Info |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (data_stream.json) |
| Source files | commercial/data_stream.json / settings.json |
| References | [Logs data streams](https://www.elastic.co/docs/manage-data/data-store/data-streams/logs-data-stream)<br>[Configure a logs data stream](https://www.elastic.co/docs/manage-data/data-store/data-streams/logs-data-stream-configure) |

**Decision logic**

Elasticsearch 9.0+ and logs-*-* data streams whose write index is not in logsdb mode → Info (IDX-013).

Official: from 9.0, logsdb is set automatically on new logs-*-* data streams. Data streams that existed before an
upgrade from 8.x, including integration and APM streams, are not switched. Data streams set to time_series are skipped,
and so are bundles without settings.json and data_stream.json index_mode, where the mode cannot be determined.

### SHD-009: Too many indices for the master node heap

| Item | Details |
| --- | --- |
| Function | `guidance.r_master_heap_per_index` |
| Evidence basis | Official |
| Possible severities | Critical, Warning |
| Thresholds | `indices_per_gb_master_heap` = 3,000 ([Official] 3000 indices per 1GB of master heap) |
| Required input | (nodes.json) and (cluster_stats.json) |
| Source files | cluster_stats.json / nodes.json |
| References | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**Decision logic**

Based on 3000 indices per 1GB of heap on master-eligible nodes.

### SHD-010: Mapping metadata takes too much of the heap

| Item | Details |
| --- | --- |
| Function | `guidance.r_mapping_heap_overhead` |
| Evidence basis | Official |
| Possible severities | Warning, OK |
| Thresholds | `heap_baseline_bytes` = 512MiB ([Official] Extra 0.5GB margin in the field mapper estimate)<br>`mapping_heap_pct_warn` = 50 ([Tool] Estimated mapping overhead / heap) |
| Required input | (nodes_stats.json) and (cluster_stats.json) |
| Source files | cluster_stats.json / nodes_stats.json |
| References | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**Decision logic**

Estimated heap needed per data node = cluster state mapping size (deduplicated) + node field overhead + 0.5GB (official formula).

Estimate / heap_max >= mapping_heap_pct_warn → Warning, below → OK. Dedicated master and ML nodes are not part of the calculation.

### SHD-011: Many empty indices

| Item | Details |
| --- | --- |
| Function | `guidance.r_empty_indices` |
| Evidence basis | Official |
| Possible severities | Warning |
| Thresholds | `empty_index_count_warn` = 5 ([Tool])<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (indices_stats.json) |
| Source files | indices_stats.json |
| References | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**Decision logic**

Number of user indices with docs.count=0 >= empty_index_count_warn → Warning.

Current write targets (data stream write index, alias write index) are excluded, because they may be empty right after a rollover.

### SHD-012: total_shards_per_node not set on heavily indexed indices

| Item | Details |
| --- | --- |
| Function | `guidance.r_total_shards_per_node` |
| Evidence basis | Official |
| Possible severities | Info |
| Thresholds | `heavy_index_docs` = 10,000,000 ([Tool] Threshold for a heavily indexed index)<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (settings.json) and (indices_stats.json) |
| Source files | settings.json / indices_stats.json |
| References | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**Decision logic**

Whether index.routing.allocation.total_shards_per_node is set to prevent hot spots (heavily indexed indices).

### PERF-004: Indexing buffer per actively written shard is too small

| Item | Details |
| --- | --- |
| Function | `guidance.r_index_buffer` |
| Evidence basis | Official |
| Possible severities | Info |
| Thresholds | `index_buffer_per_shard_warn` = 32MiB ([Tool] Per write-target shard (official upper bound is 512MB)) |
| Required input | (nodes.json) and (indices.json or shards.json or cat_shards.txt) |
| Source files | nodes.json / data_stream.json / indices.json |
| References | [Tune for indexing speed](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/indexing-speed) |

**Decision logic**

Indexing buffer per shard.

indices.memory.index_buffer_size (default 10% of heap) is shared by the 'recently written (active)' shards.
A shard with no writes for 5 minutes or more becomes inactive and gives its buffer back. The bundle cannot show directly which shards are active,
so only shards that are confirmed write targets (data stream write indices plus indices that were indexing at collection time) are counted.

### PERF-005: Too many open search contexts

| Item | Details |
| --- | --- |
| Function | `guidance.r_open_contexts` |
| Evidence basis | Tool threshold |
| Possible severities | Warning |
| Thresholds | `open_contexts_warn` = 100 ([Tool]) |
| Required input | (nodes_stats.json) |
| Source files | nodes_stats.json |
| References | [Tune for search speed](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/search-speed) |

**Decision logic**

Node search.open_contexts >= open_contexts_warn → Warning.

### PERF-006: Default search timeout is not set

| Item | Details |
| --- | --- |
| Function | `guidance.r_search_timeout` |
| Evidence basis | Official |
| Possible severities | Info |
| Required input | (cluster_settings.json) |
| Source files | cluster_settings.json |
| References | [Tune for search speed](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/search-speed) |

**Decision logic**

Info if search.default_search_timeout is not set or is -1 (unlimited).

### PERF-007: Indices with few replicas for their search load

| Item | Details |
| --- | --- |
| Function | `guidance.r_replica_throughput` |
| Evidence basis | Official |
| Possible severities | Info |
| Thresholds | `search_heavy_query_total` = 100,000 ([Tool] Threshold for a search-heavy index)<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (settings.json) and (indices_stats.json) and (indices.json or shards.json or cat_shards.txt) |
| Source files | settings.json / indices_stats.json |
| References | [Tune for search speed](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/search-speed) |

**Decision logic**

Formula recommended in the search-speed guide: replicas = max(max_failures, ceil(num_nodes/num_primaries) - 1).

### PERF-008: Indices using index.store.preload

| Item | Details |
| --- | --- |
| Function | `guidance.r_store_preload` |
| Evidence basis | Official |
| Possible severities | Warning, Info |
| Thresholds | `preload_index_count_warn` = 5 ([Tool])<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (settings.json) |
| Source files | settings.json |
| References | [Tune for search speed](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/search-speed)<br>[Tune approximate kNN search](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/approximate-knn-search) |

**Decision logic**

Info if any index has index.store.preload set; Warning if the count is > preload_index_count_warn.

### PERF-009: Data path on a network filesystem

| Item | Details |
| --- | --- |
| Function | `guidance.r_remote_storage` |
| Evidence basis | Official |
| Possible severities | Warning |
| Required input | (nodes_stats.json) |
| Source files | nodes_stats.json |
| References | [Tune for indexing speed](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/indexing-speed)<br>[Tune for search speed](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/search-speed) |

**Decision logic**

Warning if nodes_stats fs.data[].type includes nfs / cifs / smb / fuse / glusterfs / ceph.

### DISK-006: Default codec on large standard indices

| Item | Details |
| --- | --- |
| Function | `guidance.r_codec` |
| Evidence basis | Official |
| Possible severities | Info |
| Thresholds | `codec_check_min_bytes` = 50GiB ([Tool])<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (settings.json) and (indices_stats.json) |
| Source files | settings.json / indices_stats.json |
| References | [Tune for disk usage](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/disk-usage) |

**Decision logic**

User indices in standard mode with primary store >= codec_check_min_bytes and index.codec left at default (not set) → Info. logsdb and time_series are excluded because best_compression is their default.

### DISK-007: Indices with _source disabled

| Item | Details |
| --- | --- |
| Function | `guidance.r_source_mode` |
| Evidence basis | Official |
| Possible severities | Warning, Info |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (settings.json) |
| Source files | settings.json |
| References | [Tune for disk usage](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/disk-usage) |

**Decision logic**

index.mapping.source.mode=disabled → Warning. Any other mode (synthetic, etc.) → Info.

### MAP-003: Index templates without dynamic mapping control

| Item | Details |
| --- | --- |
| Function | `guidance.r_dynamic_mapping` |
| Evidence basis | Official |
| Possible severities | Info |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (index_templates.json) |
| Source files | index_templates.json / component_templates.json |
| References | [Tune for disk usage](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/disk-usage)<br>[Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**Decision logic**

Checks whether dynamic mapping is controlled, based on the result merged with the components.

### VEC-001: Vector data usage

| Item | Details |
| --- | --- |
| Function | `guidance.r_vector_memory` |
| Evidence basis | Tool threshold |
| Possible severities | Warning, Info |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table)<br>`vector_vs_fscache_pct_warn` = 60 ([Tool] Resident vector size / (RAM - heap)) |
| Required input | (indices_stats.json) and (nodes_stats.json) |
| Source files | indices_stats.json / indices_stats.json / nodes_stats.json |
| References | [Tune approximate kNN search](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/approximate-knn-search) |

**Decision logic**

Per-index dense_vector off-heap (total, or primaries if total is missing). Required resident size = (veq+veb if present, otherwise vec) + vex. Sum / Σ(data node RAM - heap) >= vector_vs_fscache_pct_warn → Warning, below → Info. This is a cluster-wide estimate and does not look at the per-node distribution.

### VEC-002, VEC-003: Non-quantized index for high-dimensional float vectors

| Item | Details |
| --- | --- |
| Function | `guidance.r_vector_quantization` |
| Findings | VEC-002 Non-quantized index for high-dimensional float vectors / VEC-003 Vector exclusion from _source not set |
| Evidence basis | Official |
| Possible severities | Warning, Info |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table)<br>`vector_dim_quantize_warn` = 384 ([Official] Quantization recommended for float vectors of 384 dimensions or more) |
| Required input | (index_templates.json) |
| Source files | index_templates.json / component_templates.json |
| References | [Tune approximate kNN search](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/approximate-knn-search) |

**Decision logic**

Whether high-dimension float vectors are quantized (rated after merging components).

From 8.14, a dense_vector without index_options gets quantized HNSW by default.
So 'not set' is not treated as a problem on 8.14 or later; only an explicit non-quantized type (hnsw/flat) is rated.

### VEC-004: Too many segments in vector indices

| Item | Details |
| --- | --- |
| Function | `guidance.r_vector_segments` |
| Evidence basis | Official |
| Possible severities | Warning |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table)<br>`vector_segments_per_shard_warn` = 20 ([Tool]) |
| Required input | (indices_stats.json) and (indices.json or shards.json or cat_shards.txt) |
| Source files | indices_stats.json / settings.json |
| References | [Tune approximate kNN search](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/approximate-knn-search) |

**Decision logic**

For indices with vector data, primary segments / primary shards >= vector_segments_per_shard_warn → Warning.

## Hot spots and balancing

### HOT-005.(sub-items): CPU saturated across the whole %s tier

| Item | Details |
| --- | --- |
| Function | `hotspot.r_tier_saturation` |
| Evidence basis | Tool threshold |
| Possible severities | Warning |
| Thresholds | `load_per_cpu_warn` = 1.0 ([Tool] load15 / CPU cores)<br>`tier_cpu_pct_warn` = 75 ([Tool] CPU% at which a whole tier counts as saturated) |
| Required input | (nodes_stats.json) and (nodes.json) |
| Source files | nodes_stats.json |
| References | [Troubleshooting hot spotting](https://www.elastic.co/docs/troubleshoot/elasticsearch/hotspotting) |

**Decision logic**

CPU saturation per tier. Warning if every node in a tier has load15/CPU >= load_per_cpu_warn or CPU% >= tier_cpu_pct_warn.

This differs from skew between nodes (HOT-001). Even when the load is spread evenly, a tier that is at its limit needs more nodes or less load.
The cgroup CPU throttling (OS-003) and the rejections of the write, write_coordination and search thread pools (TP-001) of that tier are shown as supporting evidence.

### HOT-001: Uneven resource usage within a tier (suspected hot spotting)

| Item | Details |
| --- | --- |
| Function | `hotspot.r_resource_hotspot` |
| Evidence basis | Official |
| Possible severities | Warning, OK |
| Thresholds | `disk_imbalance_pct_warn` = 15 ([Tool] Disk usage spread between nodes (percentage points))<br>`hotspot_cpu_pct_floor` = 50 ([Tool])<br>`hotspot_cpu_pct_gap` = 40 ([Tool])<br>`hotspot_disk_pct_floor` = 50 ([Tool])<br>`hotspot_heap_pct_floor` = 70 ([Tool] Ignored if the maximum is below this)<br>`hotspot_heap_pct_gap` = 30 ([Tool] Heap spread between nodes (percentage points)) |
| Required input | (nodes_stats.json) |
| Source files | nodes_stats.json |
| References | [Troubleshooting hot spotting](https://www.elastic.co/docs/troubleshoot/elasticsearch/hotspotting) |

**Decision logic**

Checks whether heap, CPU and disk usage are skewed toward a few nodes within the same tier (the official hot spotting indicators).

Tiers with different roles and loads are not compared with each other. Frozen tier disk is excluded because the shared cache pre-allocates it.
For each metric, Warning when max - min within the tier >= gap and the max is >= floor. Values are point-in-time at collection.

### HOT-002.(sub-items): Uneven %s workload within a tier

| Item | Details |
| --- | --- |
| Function | `hotspot.r_workload_hotspot` |
| Evidence basis | Tool threshold |
| Possible severities | Warning |
| Thresholds | `workload_skew_ratio_warn` = 1.8 ([Tool] Busiest node / average) |
| Required input | (nodes_stats.json) |
| Source files | nodes_stats.json |
| References | [Troubleshooting hot spotting](https://www.elastic.co/docs/troubleshoot/elasticsearch/hotspotting) |

**Decision logic**

Skew in cumulative indexing/search work per node within the same tier (busiest node / tier average >= workload_skew_ratio_warn → Warning). Tiers with fewer than 2 nodes or fewer than 10000 operations in total are skipped.

Values are cumulative and include replica work. Different uptimes distort them, so an hourly rate is shown as well.

### HOT-003, HOT-004: Shards not converged to desired balance

| Item | Details |
| --- | --- |
| Function | `hotspot.r_desired_balance` |
| Findings | HOT-003 Shards not converged to desired balance / HOT-004 Balance computation not finished |
| Evidence basis | Reported fact |
| Possible severities | Warning, Info |
| Thresholds | `undesired_shards_warn` = 1 ([Tool]) |
| Required input | (allocation.json or cat_allocation.txt) |
| Source files | allocation.json / internal_desired_balance.json / internal_desired_balance.json |
| References | [Troubleshooting an unbalanced cluster](https://www.elastic.co/docs/troubleshoot/elasticsearch/troubleshooting-unbalanced-cluster)<br>[Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**Decision logic**

Desired balance not converged (shards that are not in their desired location).

### REC-001: Recovery in progress: check the recovery bandwidth limit

| Item | Details |
| --- | --- |
| Function | `hotspot.r_recovery_settings` |
| Evidence basis | Tool threshold |
| Possible severities | Info |
| Thresholds | `recovery_rate_low_bytes` = 40MiB ([Official] indices.recovery.max_bytes_per_sec at or below the 40mb default) |
| Required input | (cluster_settings.json) |
| Source files | cluster_settings.json / recovery.json |
| References | [Recovery settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/index-recovery-settings) |

**Decision logic**

Recovery bandwidth limit.

The default of indices.recovery.max_bytes_per_sec (40mb) is not a problem by itself.
It is reported as a possible recovery bottleneck only while a recovery or relocation is actually running.

### TPL-001: Legacy template shadowed by composable template (presumed)

| Item | Details |
| --- | --- |
| Function | `hotspot.r_template_conflict` |
| Evidence basis | Official |
| Possible severities | Warning |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (templates.json) and (index_templates.json) |
| Source files | templates.json / index_templates.json |

**Decision logic**

Whether a legacy (_template) template is hidden by a composable (_index_template) template.

If any composable template matches, the legacy template is not applied (official behavior).
Composable templates that overlap at the same priority are rejected by ES at creation, so they are not checked here.
Pattern overlap is estimated by comparing wildcards.

### CLU-021: Indices with node_left delayed allocation disabled

| Item | Details |
| --- | --- |
| Function | `hotspot.r_delayed_allocation` |
| Evidence basis | Official |
| Possible severities | Warning |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (settings.json) |
| Source files | settings.json |

**Decision logic**

The delayed_timeout setting that prevents immediate re-replication when a node restarts.

## Operations and security

### OPS-007: Monitoring setup needs checking

| Item | Details |
| --- | --- |
| Function | `ops.r_monitoring` |
| Evidence basis | Reported fact |
| Possible severities | Info |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (indices_stats.json) |
| Source files | indices_stats.json / indices_stats.json / cluster_settings.json |

**Decision logic**

Whether cluster monitoring data exists (OPS-007, Info).

If this cluster holds stack monitoring data (.monitoring-* or *stack_monitoring* data streams), it is monitoring itself
(production should use a separate monitoring cluster). If there is none, the bundle cannot show whether the data goes to another cluster,
so the report asks you to confirm. Legacy internal collection (xpack.monitoring.collection.enabled=true) is reported as well.

### LIC-001: License is valid

| Item | Details |
| --- | --- |
| Function | `ops.r_license` |
| Evidence basis | Reported fact |
| Possible severities | Critical, Warning, OK |
| Thresholds | `license_expiry_days_crit` = 30 ([Tool])<br>`license_expiry_days_warn` = 90 ([Tool]) |
| Required input | (licenses.json) |
| Source files | licenses.json |

**Decision logic**

license.status != active → Critical. Time to expiry <= license_expiry_days_crit days → Critical, <= warn days → Warning, otherwise OK. The reference time is the bundle collection time.

### SNP-001, SNP-002, SNP-007, SNP-003, SNP-004, SNP-006, SNP-005: No snapshot repository configured

| Item | Details |
| --- | --- |
| Function | `ops.r_snapshots` |
| Findings | SNP-001 No snapshot repository configured / SNP-002 Failed or partial snapshots exist / SNP-007 SLM policies currently failing / SNP-003 No successful snapshot / SNP-004 Snapshots in progress / SNP-006 SLM is stopped / SNP-005 Cumulative SLM snapshot failures |
| Evidence basis | Reported fact / Tool threshold |
| Possible severities | Critical, Warning, Info, OK |
| Thresholds | `snapshot_age_hours_crit` = 168 ([Tool] 7 days)<br>`snapshot_age_hours_warn` = 36 ([Tool] Age of the latest snapshot)<br>`snapshot_failed_warn` = 1 ([Tool])<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (repositories.json or snapshot.json) |
| Source files | commercial/slm_stats.json / commercial/slm_status.json / repositories.json / slm_policies.json / snapshot.json |

**Decision logic**

No repository and no snapshot → Critical (SNP-001). FAILED/PARTIAL snapshot present → Warning, and Critical if no later successful snapshot exists (SNP-002). Age of the last SUCCESS snapshot (the SLM policy's last_success time if snapshot.json has no time) >= snapshot_age_hours_crit → Critical, >= warn → Warning, otherwise OK (SNP-003; in-progress, failed and partial snapshots are excluded from the RPO calculation). Time data present but no successful snapshot → Critical. IN_PROGRESS present → Info (SNP-004). Cumulative SLM failures >= snapshot_failed_warn → Warning (SNP-005). SLM operation_mode != RUNNING → Warning (SNP-006). SLM policy whose last failure is more recent than its last success → Critical (SNP-007).

### ILM-001, ILM-002, ILM-003: ILM is stopped

| Item | Details |
| --- | --- |
| Function | `ops.r_ilm` |
| Findings | ILM-001 ILM is stopped / ILM-002 Indices in ILM error state / ILM-003 Large indices without ILM |
| Evidence basis | Reported fact / Tool threshold |
| Possible severities | Critical, Warning, Info |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (ilm_explain.json or ilm_status.json) |
| Source files | commercial/ilm_explain.json / commercial/ilm_status.json |

**Decision logic**

ILM operation_mode != RUNNING → Warning (ILM-001). ilm_explain with step=ERROR or a failed_step → Critical if a rollover-related step failed, otherwise (delete, shrink or migrate steps, failure to delete a write index, etc.) Warning (ILM-002). User indices without ILM (managed=false) and primary > 10GB → Info (ILM-003).

### ML-001, ML-002: Transforms in failed state

| Item | Details |
| --- | --- |
| Function | `ops.r_ml_transform` |
| Findings | ML-001 Transforms in failed state / ML-002 ML anomaly detection jobs failed |
| Evidence basis | Reported fact |
| Possible severities | Warning |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (transform_stats.json or ml_anomaly_detectors.json) |
| Source files | commercial/ml_anomaly_detectors.json / commercial/transform_stats.json |

**Decision logic**

transform state failed/aborting → Warning (ML-001). Anomaly detection job state=failed → Warning (ML-002).

### SEC-001: TLS certificates are not close to expiry

| Item | Details |
| --- | --- |
| Function | `ops.r_certificates` |
| Evidence basis | Reported fact |
| Possible severities | Critical, Warning, OK |
| Thresholds | `cert_expiry_days_crit` = 30 ([Tool])<br>`cert_expiry_days_warn` = 90 ([Tool]) |
| Required input | (ssl_certs.json) |
| Source files | ssl_certs.json |

**Decision logic**

Time to certificate expiry in ssl_certs.json <= cert_expiry_days_crit days → Critical, <= warn days → Warning, otherwise OK. The reference time is the bundle collection time.

### SEC-002: Security is enabled

| Item | Details |
| --- | --- |
| Function | `ops.r_security_enabled` |
| Evidence basis | Reported fact |
| Possible severities | Critical, Warning, OK |
| Required input | (xpack.json) |
| Source files | commercial/xpack.json |

**Decision logic**

xpack security.enabled=false → Critical, otherwise OK.

### OPS-001: GeoIP database update issue

| Item | Details |
| --- | --- |
| Function | `ops.r_geoip` |
| Evidence basis | Reported fact |
| Possible severities | Info |
| Required input | (geoip_stats.json) |
| Source files | geoip_stats.json |

**Decision logic**

GeoIP failed_downloads or expired_databases > 0 → Info (can be normal in an air-gapped network).

### OPS-002: CCR replication errors

| Item | Details |
| --- | --- |
| Function | `ops.r_ccr` |
| Evidence basis | Reported fact |
| Possible severities | Warning |
| Required input | (ccr_stats.json) |
| Source files | commercial/ccr_stats.json |

**Decision logic**

Warning if a CCR follower shard has read_exceptions or failed_read/write_requests.

## Mappings, ILM policies, cluster coordination, detailed stats

### PERF-011: High share of expensive search patterns

| Item | Details |
| --- | --- |
| Function | `deep.r_search_usage` |
| Evidence basis | Tool threshold |
| Possible severities | Warning, Info |
| Thresholds | `search_expensive_share_warn` = 10 ([Tool] Share of expensive query types in all searches (%)) |
| Required input | (cluster_stats.json) |
| Source files | cluster_stats.json (indices.search) |

**Decision logic**

Uses the cumulative usage counts per query type and search component in cluster_stats.indices.search to see how much of the search load is expensive.

Expensive types (EXPENSIVE: nested, parent-child join, script, wildcard, regexp, fuzzy, prefix, query_string,
runtime_mappings, script_fields) with a usage share >= search_expensive_share_warn (%) → Warning (PERF-011); used but with a
low share → Info. These are counts per type, not query bodies, so which query on which index cannot be determined.

### DISK-008: High disk I/O utilization

| Item | Details |
| --- | --- |
| Function | `deep.r_disk_io_utilization` |
| Evidence basis | Tool threshold |
| Possible severities | Warning, Info |
| Thresholds | `disk_io_busy_pct_warn` = 60 ([Tool] Average disk utilization since startup) |
| Required input | (nodes_stats.json) |
| Source files | nodes_stats.json (fs.io_stats) |

**Decision logic**

Average disk utilization of data nodes = fs.io_stats.total.io_time_in_millis / JVM uptime (collected on Linux only).

io_time is the cumulative time the devices spent handling I/O since ES started. >= disk_io_busy_pct_warn → Warning (DISK-008), otherwise Info.
With several devices the values add up and can exceed 100%, so the result is divided by the device count. This is a cumulative average, so short saturation spikes can be hidden.
A result below 0% or above 100% means the device counter does not line up with the JVM uptime (for example a counter reset
on a hosted instance). Such a node is shown as "cannot be determined" and is not rated.

### MAP-004, MAP-005, MAP-006: Indices with field count close to the mapping limit

| Item | Details |
| --- | --- |
| Function | `deep.r_mapping_limits_actual` |
| Findings | MAP-004 Indices with field count close to the mapping limit / MAP-005 fielddata enabled on text fields / MAP-006 nested field count close to the limit |
| Evidence basis | Official / Tool threshold |
| Possible severities | Warning, Info |
| Thresholds | `mapping_fields_near_limit_pct` = 90 ([Tool] Field count against total_fields.limit)<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (mapping.json) |
| Source files | mapping.json / mapping.json / settings.json |
| References | [Mapping limit settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/mapping-limit)<br>[fielddata mapping parameter](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/text#fielddata-mapping-param) |

**Decision logic**

Counts fields per index from the actual mappings in mapping.json, using the official counting method (each field, object, multi-field and runtime field counts as 1).

Field count >= total_fields.limit × mapping_fields_near_limit_pct → Warning (MAP-004; Info only if every listed index has ignore_dynamic_beyond_limit=true).
Indices without ignore_dynamic_beyond_limit are listed first because they are the ones that can fail indexing; the table also shows
who manages the data stream template (Fleet package or Elastic), since integration templates usually set the ignore option.
Searchable snapshot mounts are skipped because they are read-only.
text field with fielddata=true → Warning (MAP-005). nested field count >= nested_fields.limit × 80% → Warning (MAP-006).

### VEC-005: High-dimension float vectors in live indices are not quantized

| Item | Details |
| --- | --- |
| Function | `deep.r_vector_mapping_actual` |
| Evidence basis | Official |
| Possible severities | Warning |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table)<br>`vector_dim_quantize_warn` = 384 ([Official] Quantization recommended for float vectors of 384 dimensions or more) |
| Required input | (mapping.json) |
| Source files | mapping.json |
| References | [Tune approximate kNN search](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/approximate-knn-search) |

**Decision logic**

Finds high-dimension float dense_vector fields in the actual index mappings that explicitly use a non-quantized type (hnsw, flat) (VEC-005, Warning).

Below 8.14, a missing index_options is also non-quantized, so those fields are included. This backs up the template-based rule (VEC-002) with the actual indices.

### ILM-004, ILM-005, ILM-007, ILM-006: ILM policies that roll over without a size condition

| Item | Details |
| --- | --- |
| Function | `deep.r_ilm_policies` |
| Findings | ILM-004 ILM policies that roll over without a size condition / ILM-005 Rollover shard size condition above the recommended maximum / ILM-007 max_primary_shard_docs set above the built-in limit / ILM-006 ILM policies without a delete phase |
| Evidence basis | Official / Reported fact |
| Possible severities | Warning, Info |
| Thresholds | `ilm_implicit_max_shard_docs` = 200,000,000 ([Official] Rollover always runs at 200M docs per shard; higher values have no effect)<br>`ilm_rollover_max_shard_gb` = 50 ([Official] Recommended upper bound for shard size at rollover)<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (ilm_policies.json) |
| Source files | ilm_policies.json |
| References | [Rollover (ILM)](https://www.elastic.co/docs/reference/elasticsearch/index-lifecycle-actions/ilm-rollover)<br>[Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**Decision logic**

Rollover and delete configuration of the ILM policies used by user indices.

No max_primary_shard_size (or max_size) in the hot rollover → Warning (ILM-004): the official recommendation is rollover by shard size,
and max_age alone leaves small indices piling up depending on the ingest rate (a cause of OVS-002). max_primary_shard_size > 50GB → Warning (ILM-005).
No delete phase → Info (ILM-006, unlimited retention). Elastic-managed policies (_meta.managed=true) are checked like the others and marked "(Elastic managed)" in the table.
max_primary_shard_docs above 200,000,000 → Info (ILM-007): rollover always runs at 200M documents per shard, so a higher value has no effect (official).

### ILM-008, ILM-009: Not enough free disk for force merge

| Item | Details |
| --- | --- |
| Function | `deep.r_forcemerge` |
| Findings | ILM-008 Not enough free disk for force merge / ILM-009 Long-running force merge |
| Evidence basis | Official / Tool threshold |
| Possible severities | Warning, Info |
| Thresholds | `forcemerge_free_space_factor` = 3 ([Official] max_num_segments=1 may need free space up to 3x the shard size)<br>`forcemerge_stuck_hours` = 24 ([Tool] Time in the forcemerge action before it is reported)<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (ilm_policies.json or ilm_explain.json) and (nodes_stats.json) |
| Source files | commercial/ilm_explain.json / nodes_stats.json / ilm_policies.json / nodes_stats.json / indices.json |
| References | [Force merge API](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-indices-forcemerge)<br>[Force merge (ILM)](https://www.elastic.co/docs/reference/elasticsearch/index-lifecycle-actions/ilm-forcemerge) |

**Decision logic**

ILM force merge to a single segment, disk headroom and progress.

Official: force merge with max_num_segments=1 may need free space up to three times the shard size, and the force_merge
thread pool has max(1, allocated processors / 8) threads per node. Merges to one segment are forcemerge with max_num_segments=1
(run in its own phase) and searchable_snapshot with force_merge_index (default true, run in the tier of the preceding phase,
a no-op after an earlier one-segment merge). A policy in use with such a merge where a node of the tier that runs it
(hot/warm/cold; all non-frozen data nodes when the tier is not used) has less free disk
than forcemerge_free_space_factor x the largest primary shard of the indices using the policy → Warning (ILM-008).
ilm_explain entries that have been in the forcemerge action (or the forcemerge step of searchable_snapshot) for
forcemerge_stuck_hours or more at collection time → Info (ILM-009),
with the force_merge pool size and queue of the data nodes. Partially mounted indices are skipped (size is the cache size).

### CLU-022: Leftover voting config exclusions

| Item | Details |
| --- | --- |
| Function | `deep.r_voting_exclusions` |
| Evidence basis | Official |
| Possible severities | Warning |
| Required input | (cluster_state.json) |
| Source files | cluster_state.json |
| References | [Voting configuration exclusions](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-cluster-post-voting-config-exclusions) |

**Decision logic**

voting_config_exclusions in cluster_state is not empty → Warning (CLU-022).

This is a temporary setting used when removing or replacing master-eligible nodes. If it is not cleared after the work, those nodes stay out of the vote and the quorum margin shrinks.

### SHUT-001: Node shutdown records

| Item | Details |
| --- | --- |
| Function | `deep.r_node_shutdown` |
| Evidence basis | Reported fact |
| Possible severities | Critical, Warning, Info |
| Required input | (nodes_shutdown_status.json) |
| Source files | nodes_shutdown_status.json |
| References | [Node shutdown API](https://www.elastic.co/docs/api/doc/elasticsearch/group/endpoint-shutdown) |

**Decision logic**

Shutdown records from nodes_shutdown_status. STALLED → Critical, IN_PROGRESS → Info, COMPLETE but the node is still in the cluster → Warning (SHUT-001).

A shutdown record stays until it is deleted. If it is left after the work, shard allocation to that node can stay restricted.

### IDX-012: Shard store exceptions (suspected corruption)

| Item | Details |
| --- | --- |
| Function | `deep.r_shard_store_errors` |
| Evidence basis | Reported fact |
| Possible severities | Critical |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (shard_stores.json) |
| Source files | shard_stores.json |

**Decision logic**

Shard copies with a store_exception in shard_stores → Critical (IDX-012, suspected data corruption).

### OPS-003: Remote cluster connection lost

| Item | Details |
| --- | --- |
| Function | `deep.r_remote_clusters` |
| Evidence basis | Reported fact |
| Possible severities | Warning |
| Required input | (remote_cluster_info.json) |
| Source files | remote_cluster_info.json |

**Decision logic**

Remote clusters with connected=false in remote_cluster_info → Warning (OPS-003).

### FRZ-001: Excessive frozen shared cache turnover

| Item | Details |
| --- | --- |
| Function | `deep.r_frozen_cache` |
| Evidence basis | Tool threshold |
| Possible severities | Warning, Info |
| Required input | (searchable_snapshots_cache_stats.json) |
| Source files | searchable_snapshots_cache_stats.json |

**Decision logic**

Frozen shared cache statistics. Warning if any node has more evictions than cache regions (FRZ-001); otherwise Info when there is data.

Evictions > region count means the whole cache has been replaced at least once, a sign that the cache is small compared to the searched data (tool threshold).

### PERF-010: Script compilation limit triggered

| Item | Details |
| --- | --- |
| Function | `deep.r_script_limit` |
| Evidence basis | Reported fact |
| Possible severities | Warning |
| Required input | (nodes_stats.json) |
| Source files | nodes_stats.json |

**Decision logic**

Nodes with nodes_stats.script.compilation_limit_triggered > 0 → Warning (PERF-010).

### ING-002: Time spent per ingest processor

| Item | Details |
| --- | --- |
| Function | `deep.r_ingest_processors` |
| Evidence basis | Reported fact |
| Possible severities | Info |
| Thresholds | `top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (nodes_stats.json) |
| Source files | nodes_stats.json |

**Decision logic**

Sums the cumulative processing time per processor from the node ingest statistics and reports the top processors (ING-002, Info).

When hot threads (RT-001) show ingest using CPU, this is the evidence for which pipeline or processor is responsible.

### CLU-024: Cluster state publication failures

| Item | Details |
| --- | --- |
| Function | `deep.r_cluster_state_publication` |
| Evidence basis | Reported fact |
| Possible severities | Warning, Info |
| Required input | (nodes_stats.json) |
| Source files | nodes_stats.json |

**Decision logic**

Cluster state publication statistics from nodes_stats.discovery.

cluster_state_update.failure present → Warning (CLU-024). If the serialized full state size (before compression) is available,
its size and the average commit time are reported as Info. Failure counts are summed across nodes. The master does the publishing, so the commit count, commit time and state size use the maximum across nodes.

### CLU-023: Plugin mismatch between nodes

| Item | Details |
| --- | --- |
| Function | `deep.r_plugin_consistency` |
| Evidence basis | Reported fact |
| Possible severities | Warning |
| Required input | (nodes.json) |
| Source files | nodes.json |

**Decision logic**

Warning if the installed plugins (name and version) are not identical on every node (CLU-023).

### ML-003: ML model deployment problem

| Item | Details |
| --- | --- |
| Function | `deep.r_ml_deployments` |
| Evidence basis | Reported fact |
| Possible severities | Warning |
| Required input | (ml_trained_models_stats.json) |
| Source files | ml_trained_models_stats.json |

**Decision logic**

Warning if a trained model deployment has a state other than started, or an allocation status other than fully_allocated (ML-003).

### OPS-005, OPS-004, OPS-006: Watcher stopped manually

| Item | Details |
| --- | --- |
| Function | `deep.r_watcher_autoscaling_rollup` |
| Findings | OPS-005 Watcher stopped manually / OPS-004 Autoscaling required capacity is larger than current capacity / OPS-006 rollup jobs in use (deprecated) |
| Evidence basis | Reported fact |
| Possible severities | Warning, Info |
| Required input | (watcher_stack.json or autoscaling_capacity.json or rollup_jobs.json) |
| Source files | autoscaling_capacity.json / rollup_jobs.json / watcher_stack.json |

**Decision logic**

Watcher manually stopped while watches exist → Warning (OPS-005). Autoscaling required capacity larger than current capacity → Info (OPS-004).
Rollup jobs present → Info (OPS-006, rollup is deprecated and replaced by downsampling).

## Runtime (hot threads, logs)

### RT-001: Hot threads analysis

| Item | Details |
| --- | --- |
| Function | `runtime.r_hot_threads` |
| Evidence basis | Tool threshold |
| Possible severities | Warning, Info |
| Thresholds | `hot_thread_pct_warn` = 50 ([Tool] CPU% of a single thread)<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Required input | (nodes_hot_threads.txt) |
| Source files | nodes_hot_threads.txt |

**Decision logic**

Parses nodes_hot_threads.txt and extracts the actual CPU usage per thread (cpu=, or the overall percentage if missing).

Max thread CPU >= hot_thread_pct_warn → Warning, otherwise Info. This is a single 500ms snapshot at collection time, so it is never rated Critical on its own.
The cause is classified by matching signatures against each thread's stack: context signatures (grok, painless, regexp, global ordinals, etc.) are searched over the whole stack first, then general signatures (ingest, aggregation, search, merge, etc.) starting from the top (running) frames; the first match wins.
Threads below 0.5% CPU are ignored for cause counting when any busier thread exists.

### LOG-001, LOG-000: Error patterns found in server logs

| Item | Details |
| --- | --- |
| Function | `runtime.r_logs` |
| Findings | LOG-001 Error patterns found in server logs / LOG-000 Diagnostics bundle without server logs |
| Evidence basis | Reported fact |
| Possible severities | Info, OK |
| Thresholds | `log_scan_bytes` = 8MiB ([Tool] Bytes scanned per log file (from the end))<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Source files | diagnostics.log / logs/ / manifest.json |

**Decision logic**

No logs/ directory → Info (LOG-000). If the bundle was collected in local/remote mode and diagnostics.log shows that the tool failed to match the target node, that failure is reported as the cause of the missing logs; otherwise the finding says the bundle has no server logs. If logs exist, scans only the last log_scan_bytes of each file, up to 40 files (gc.log* and duplicate _server.json excluded), for fixed patterns (OOM, long old GC, master not discovered, CircuitBreaking, rejected execution, watermark exceeded, node disconnected, mapping parse errors, etc.). The finding takes the highest severity among the detected patterns (LOG-001); none detected → OK.

## OS settings (syscalls/ in local and remote mode)

### SYS-001, SYS-002, SYS-003, SYS-004: vm.max_map_count is below the bootstrap check minimum

| Item | Details |
| --- | --- |
| Function | `syscalls.r_os_config` |
| Findings | SYS-001 vm.max_map_count is below the bootstrap check minimum / SYS-002 Swap is present and vm.swappiness is high / SYS-003 Elasticsearch process limits are below the minimum requirement / SYS-004 Kernel OOM killer records |
| Evidence basis | Official / Reported fact |
| Possible severities | Critical, Warning, Info, OK |
| Required input | (syscalls/sysctl.txt or syscalls/proc-limit.txt or syscalls/dmesg.txt) |
| Source files | syscalls/dmesg.txt / syscalls/proc-limit.txt / syscalls/sysctl.txt |
| References | [vm.max_map_count setting](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/vm-max-map-count)<br>[Bootstrap checks](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/bootstrap-checks)<br>[Swap disabled](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/setup-configuration-memory)<br>[File descriptors setting](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/file-descriptors)<br>[Thread count limit setting](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/max-number-of-threads) |

**Decision logic**

vm.max_map_count in syscalls/sysctl.txt below 262144 (the bootstrap check minimum) → Critical, below 1048576 (official recommendation) → Info, at or above → OK (SYS-001). sysctl vm.swappiness > 1, swap_total > 0 and mlockall not true → Info (SYS-002). Max open files below 65535 or Max processes below 4096 (soft limit) in syscalls/proc-limit.txt → Critical (SYS-003), otherwise OK. OOM killer entry in syscalls/dmesg.txt: target process is java/elasticsearch → Critical, any other process → Warning (SYS-004); no entry → OK.

## Trend (--baseline comparison mode)

### DIF-013: Bundles from different clusters

| Item | Details |
| --- | --- |
| Function | `diff.r_cluster_identity` |
| Evidence basis | Computed |
| Possible severities | Warning |
| Source files | version.json / nodes.json |

**Decision logic**

The two bundles come from different clusters (DIF-013, Warning): cluster_uuid differs, or, without a uuid,
the cluster name differs and fewer than half of the node names overlap. The deltas are then not a trend of one cluster.

### DIF-001: Cluster status %s

| Item | Details |
| --- | --- |
| Function | `diff.r_status_change` |
| Evidence basis | Computed |
| Possible severities | Critical, Info |
| Source files | cluster_health.json (comparison of the two bundles) |

**Decision logic**

When the cluster status differs between the two bundles. Worse -> critical, better -> info.

### DIF-002, DIF-003: Node restart detected

| Item | Details |
| --- | --- |
| Function | `diff.r_node_restart` |
| Findings | DIF-002 Node restart detected / DIF-003 Node membership changed |
| Evidence basis | Computed |
| Possible severities | Critical, Warning, Info |
| Source files | nodes.json (comparison of the two bundles) / nodes_stats.json (comparison of the two bundles) |

**Decision logic**

Node with the same name has a smaller uptime than before -> critical (DIF-002, restart). Node left -> warning, only new -> info (DIF-003).

### DIF-005, DIF-004: Thread pool rejections in progress

| Item | Details |
| --- | --- |
| Function | `diff.r_rejections_delta` |
| Findings | DIF-005 Thread pool rejections in progress / DIF-004 No increase in thread pool rejections |
| Evidence basis | Computed |
| Possible severities | Critical, Warning, Info |
| Thresholds | `rejected_crit` = 1,000 ([Tool] Total cumulative rejections)<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Source files | nodes_stats.json (comparison of the two bundles) |

**Decision logic**

Per node and pool increase in rejected. Total > 0 -> warning, >= rejected_crit -> critical (DIF-005). Cumulative value is not 0 but the increase is 0 -> info (DIF-004, past history).

### DIF-006: Old GC trend

| Item | Details |
| --- | --- |
| Function | `diff.r_gc_delta` |
| Evidence basis | Computed |
| Possible severities | Warning, Info |
| Thresholds | `old_gc_per_hour_warn` = 6 ([Tool] Old GC count per hour)<br>`old_gc_time_ratio_warn` = 0.02 ([Tool] Cumulative old GC time / uptime) |
| Source files | nodes_stats.json (comparison of the two bundles) |

**Decision logic**

Increase in old GC. Per-hour increase >= old_gc_per_hour_warn or GC time share of the interval >= old_gc_time_ratio_warn -> warning, otherwise info. Nodes whose counter went down (restart) are skipped.

### DIF-007: Circuit breakers tripping now

| Item | Details |
| --- | --- |
| Function | `diff.r_breaker_delta` |
| Evidence basis | Computed |
| Possible severities | Critical |
| Source files | nodes_stats.json (comparison of the two bundles) |

**Decision logic**

Increase in breaker tripped > 0 -> critical.

### DIF-008: Projected disk saturation from growth rate

| Item | Details |
| --- | --- |
| Function | `diff.r_disk_projection` |
| Evidence basis | Computed |
| Possible severities | Critical, Warning, Info |
| Thresholds | `diff_min_hours_for_projection` = 1.0 ([Tool] No extrapolation for intervals shorter than this)<br>`disk_projection_days_warn` = 30 ([Tool]) |
| Source files | nodes_stats.json (comparison of the two bundles) |

**Decision logic**

Estimates when the watermark is reached from the disk growth rate.

### DIF-009: Throughput in the interval and distribution across nodes

| Item | Details |
| --- | --- |
| Function | `diff.r_throughput` |
| Evidence basis | Computed |
| Possible severities | Warning, Info |
| Thresholds | `workload_skew_ratio_warn` = 1.8 ([Tool] Busiest node / average) |
| Source files | nodes_stats.json (comparison of the two bundles) |

**Decision logic**

Converts the per-node increase in index_total / query_total over the interval to throughput per second (replica work included). Max node / average >= workload_skew_ratio_warn -> warning, otherwise info.

### DIF-010, DIF-011: Top index growth

| Item | Details |
| --- | --- |
| Function | `diff.r_index_growth` |
| Findings | DIF-010 Top index growth / DIF-011 Index creation and deletion |
| Evidence basis | Computed |
| Possible severities | Info |
| Thresholds | `index_growth_min_bytes` = 1GiB ([Tool])<br>`top_n` = 15 ([Tool] Maximum rows in an evidence table) |
| Source files | indices_stats.json (comparison of the two bundles) |

**Decision logic**

Increase in index primary store > index_growth_min_bytes -> info (DIF-010). User indices added or deleted -> info (DIF-011).

### DIF-012: Change in findings

| Item | Details |
| --- | --- |
| Function | `diff._finding_delta` |
| Evidence basis | Computed |
| Possible severities | Critical, Warning, Info |
| Source files | Comparison of findings in the two bundles |

**Decision logic**

Compares the Critical and Warning finding ids of the previous and current bundle and lists what is new, worse or resolved. It summarizes other findings, so it is always Info (this avoids counting the same problem twice).

## Settings knowledge base

Official default, kind, meaning and effect of change for each setting used by SET-001 to SET-006 (`esdiag/settings_kb.py`).

- Precedence (official): transient > persistent > elasticsearch.yml > default
- A dynamic setting can be changed with `PUT _cluster/settings` (or the index settings API). Setting it to `null` restores the default.
- A static setting can only be changed in elasticsearch.yml on every target node and needs a restart. Static index settings can only be changed on a closed index.
- `cluster_settings_defaults` in the bundle already reflects yml values, and keys set through the API do not report a default. So the original default comes from this table (official docs for 9.4).
- ↑ is the effect of setting a value above the default, ↓ below it. A setting that is not in this table is shown in the report with its value only, marked as not documented.

| Setting | Default | Kind | Scope | Meaning | Effect of change | Risk (up/down) | Docs |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `action.auto_create_index` | true | dynamic | cluster | Whether indexing into a nonexistent index creates it automatically (patterns can be specified). | Restricting it prevents indices created by typos, but indexing fails for any ingest target that is not in the allowed patterns. If data stream or system index patterns are missing, features can stop working. | INFO | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `action.destructive_requires_name` | true | dynamic | cluster | Prevents deleting indices with wildcards or _all (default true since 8.0). | With false, a single request such as DELETE * can delete every index. | WARNING | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `bootstrap.memory_lock` | false | static | node | Locks the heap in RAM (prevents swapping). | With true, swapping is prevented. If the OS memlock limit is too low, the bootstrap check fails at startup. | - | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `cluster.blocks.read_only` | false | dynamic | cluster | Makes the whole cluster read-only. | With true, all writes and metadata changes are rejected. | WARNING | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `cluster.blocks.read_only_allow_delete` | false | dynamic | cluster | Makes the whole cluster read-only (deletes are still allowed). | With true, all writes except index deletion are rejected. | WARNING | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `cluster.indices.close.enable` | true | dynamic | cluster | Whether the close index API is allowed. | With false, indices cannot be closed (some environments block it because closed indices are hard to manage for replication and snapshots). | INFO | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `cluster.info.update.interval` | 30s | dynamic | cluster | How often disk usage is checked. | ↑ Rapid disk growth is detected later.<br>↓ The master gets slightly more load. | WARNING / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.max_shards_per_node` | 1000 | dynamic | cluster | Open shard limit per non-frozen data node (cluster limit = value x number of nodes). | ↑ The limit is reached later, but the costs of oversharding that the limit was holding back (heap, cluster state, master load) pile up unchecked.<br>↓ Creating new indices and rollover fail sooner. | WARNING / INFO | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |
| `cluster.max_shards_per_node.frozen` | 3000 | dynamic | cluster | Shard limit per frozen-only node. | ↑ Metadata load on frozen nodes increases.<br>↓ Fewer indices can be mounted. | INFO / INFO | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |
| `cluster.metadata.display_name` | (none) | dynamic | cluster | Display name of the cluster (Elastic Cloud metadata). | No effect on behavior. | - | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `cluster.persistent_tasks.allocation.enable` | all | dynamic | cluster | Allows persistent task allocation (ML jobs, transforms, and so on). | With none, new persistent tasks are not allocated. | WARNING | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `cluster.routing.allocation.allow_rebalance` | always | dynamic | cluster | When rebalancing may start (default always for the desired balance allocator, indices_all_active for the legacy allocator). | A stricter condition (indices_primaries_active / indices_all_active) postpones rebalancing until recovery finishes, so the uneven distribution is resolved later. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.awareness.attributes` | (none) | dynamic | cluster | Node attributes used to place primaries and replicas in different zones (zone, rack). | When set, copies of the same shard are placed in different zones. If the zones have different numbers of nodes, some copies can stay unassigned. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.balance.disk_usage` | 2.0E-11 | dynamic | cluster | Balance weight for disk usage per node. | Changes how well disk skew is spread out. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.balance.index` | 0.55 | dynamic | cluster | Weight for spreading the shards of each index. | Changing the weight can trigger large-scale relocation. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.balance.shard` | 0.45 | dynamic | cluster | Balance weight for the total number of shards per node. | Changing the weight combination changes the desired balance calculation and can trigger large-scale relocation. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.balance.threshold` | 1.0 | dynamic | cluster | Minimum imbalance that triggers rebalancing. | ↑ Small imbalances are ignored, so fewer shards move, but the skew remains.<br>↓ Shards move for even minor differences, which causes unnecessary I/O. | INFO / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.balance.write_load` | 10.0 | dynamic | cluster | Balance weight for the expected write load of data streams. | Changes how well write hot spots are spread out. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.cluster_concurrent_rebalance` | 2 | dynamic | cluster | Number of shards that can be rebalanced at the same time across the whole cluster. | ↑ Shards move faster, but network and disk I/O compete with service traffic.<br>↓ Skew is resolved more slowly. At 0, rebalancing effectively stops. | INFO / WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.disk.threshold_enabled` | true | dynamic | cluster | Whether allocation decisions use the disk watermarks. | With false, shards are placed until the disk is full, and flood stage protection does not work either. | WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.disk.watermark.flood_stage` | 95% | dynamic | cluster | Blocks writes (read_only_allow_delete) on indices of nodes above this usage. | ↑ The disk is more likely to fill completely before writes are blocked. When you set it explicitly, the max_headroom default (100GB) no longer applies.<br>↓ Writes are blocked earlier. | WARNING / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.disk.watermark.high` | 90% | dynamic | cluster | Shards on nodes above this usage are moved to other nodes. | ↑ Moves start later, which raises the risk of reaching flood stage. When you set it explicitly, the max_headroom default (150GB) no longer applies.<br>↓ Shards move more often. | WARNING / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.disk.watermark.low` | 85% | dynamic | cluster | New shards are not placed on nodes above this usage. | ↑ Disks can be filled further, but there is less room to react. When you set it explicitly, the max_headroom default (200GB) no longer applies.<br>↓ Shard placement is blocked even when plenty of free space remains, so shards can pile up on a few nodes. | INFO / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.enable` | all | dynamic | cluster | Which shards are allowed to be allocated (all / primaries / new_primaries / none). | Anything other than all stops replica (or all) shard allocation, so recovery after a node leaves stalls and yellow/red persists. This is a temporary value for rolling restarts. Set it back to null when the work is done. | WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.node_concurrent_incoming_recoveries` | 2 | dynamic | cluster | Number of concurrent incoming recoveries per node. | ↑ I/O contention on the receiving node increases.<br>↓ Recovery is slower. | INFO / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.node_concurrent_outgoing_recoveries` | 2 | dynamic | cluster | Number of concurrent outgoing recoveries per node. | ↑ I/O contention increases on the sending node (usually one that is already busy).<br>↓ Recovery is slower. | INFO / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.node_concurrent_recoveries` | 2 | dynamic | cluster | Number of concurrent recoveries per node (incoming + outgoing). | ↑ Recovery after a node replacement is faster, but the node's disk and network can saturate.<br>↓ Recovery takes longer and the cluster stays yellow longer. | INFO / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.node_initial_primaries_recoveries` | 4 | dynamic | cluster | Number of primaries recovered concurrently from local disk when a node restarts. | ↑ Disk load spikes right after a restart.<br>↓ Red status takes longer to clear after a full restart. | INFO / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.same_shard.host` | false | dynamic | cluster | Prevents copies of the same shard from being placed on multiple nodes of the same host. | true is a safeguard needed when several nodes run on one server. With false on a single-node or single-host setup, a host failure can take out the primary and its replica together. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.total_shards_per_node` | -1 | dynamic | cluster | Upper limit on the total number of shards per node (-1 = unlimited). | ↓ Shards that hit the limit stay unassigned. After a node failure they cannot move to the remaining nodes, which can turn the cluster red. | - / WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.rebalance.enable` | all | dynamic | cluster | Which shards are allowed to be rebalanced. | Rebalancing is restricted, so shards do not move to new nodes even after you add nodes, and the uneven distribution stays. | WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.use_adaptive_replica_selection` | true | dynamic | cluster | Distributes search requests across copies based on response time and queue length (adaptive replica selection, ARS). | With false, requests are distributed round-robin, and a single slow node raises the p99 of all searches. | WARNING | [Search settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/search-settings) |
| `http.max_content_length` | 100mb | static | node | Maximum size of an HTTP request body. | ↑ Large bulk requests and documents are allowed, which raises the risk of heap spikes (the Lucene limit of about 2GB still applies).<br>↓ Large bulk requests are rejected with 413. | WARNING / INFO | [Networking settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/networking-settings) |
| `index.auto_expand_replicas` | false | dynamic | index | Adjusts the replica count automatically to the number of data nodes. | On a large index, adding nodes automatically adds replicas, and disk and recovery load spike. | INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.blocks.read_only` | false | dynamic | index | Read-only. | With true, writes and metadata changes are rejected. | WARNING | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.blocks.read_only_allow_delete` | false | dynamic | index | Read-only (deletes allowed). Set automatically at flood stage. | With true, indexing is rejected. Clear it after freeing disk space (on 8.x it is cleared automatically once space recovers). | WARNING | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.blocks.write` | false | dynamic | index | Blocks writes. | With true, indexing is rejected. | WARNING | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.codec` | default(LZ4) | static | index | Compression method for stored fields (logsdb and time_series modes default to best_compression). | best_compression saves storage but adds decompression cost when fetching documents. It is a static setting, so it can only be changed on a closed index, and existing segments pick it up after a merge. | INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.highlight.max_analyzed_offset` | 1000000 | dynamic | index | Maximum number of characters analyzed for highlighting. | ↑ Highlighting large documents uses a lot of CPU and heap.<br>↓ Highlights of long documents are truncated or fail. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.mapping.depth.limit` | 20 | dynamic | index | Maximum object nesting depth. | ↑ Deeply nested documents are allowed.<br>↓ Indexing may be rejected. | INFO / INFO | [Mapping limit settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/mapping-limit) |
| `index.mapping.nested_fields.limit` | 50 | dynamic | index | Limit on the number of nested type fields. | ↑ Nested fields create hidden documents, which are expensive to store and search.<br>↓ Mappings are rejected. | WARNING / INFO | [Mapping limit settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/mapping-limit) |
| `index.mapping.nested_objects.limit` | 10000 | dynamic | index | Limit on the number of nested objects per document. | ↑ A single document can expand into tens of thousands of hidden documents and take most of the heap and disk.<br>↓ Indexing is rejected. | WARNING / INFO | [Mapping limit settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/mapping-limit) |
| `index.mapping.total_fields.limit` | 1000 | dynamic | index | Maximum number of fields per index (guards against mapping explosion). | ↑ More fields mean more cluster state and heap usage and more master load (a sign of mapping explosion).<br>↓ Indexing fails when a new field arrives. | WARNING / INFO | [Mapping limit settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/mapping-limit) |
| `index.max_docvalue_fields_search` | 100 | dynamic | index | Maximum number of docvalue_fields per request. | ↑ Response generation costs more.<br>↓ Those requests are rejected. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_inner_result_window` | 100 | dynamic | index | Maximum value of from + size for inner_hits and top_hits. | ↑ Aggregation responses get larger and heap usage increases.<br>↓ Those queries are rejected. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_ngram_diff` | 1 | dynamic | index | Allowed difference between min and max for the ngram tokenizer. | ↑ The number of tokens grows sharply, which strongly affects index size and speed.<br>↓ Analyzer definitions are rejected. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_refresh_listeners` | 1000 | dynamic | index | Maximum number of waiters for refresh=wait_for. | ↑ Waiting requests use more heap.<br>↓ Requests over the limit force a refresh. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_regex_length` | 1000 | dynamic | index | Maximum length of a regexp query. | ↑ Complex regular expressions can take most of the CPU.<br>↓ Those queries are rejected. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_result_window` | 10000 | dynamic | index | Maximum value of from + size. | ↑ Deep paging is allowed. Each shard collects from+size hits, so heap usage grows with page depth.<br>↓ Deep page requests are rejected. | WARNING / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_script_fields` | 32 | dynamic | index | Maximum number of script_fields per request. | ↑ Search CPU usage increases.<br>↓ Those requests are rejected. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_shingle_diff` | 3 | dynamic | index | Allowed difference between min and max for the shingle filter. | ↑ The number of tokens grows sharply.<br>↓ Analyzer definitions are rejected. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_terms_count` | 65536 | dynamic | index | Maximum number of terms in a terms query. | ↑ Large terms queries use a lot of CPU and heap.<br>↓ Those queries are rejected. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.merge.policy.max_merged_segment` | 5gb | dynamic | index | Maximum size of a segment produced by a merge. | ↑ Fewer segments make search faster (kNN in particular), but each merge does more I/O.<br>↓ Segments pile up and search gets slower. | INFO / INFO | [Merge settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/merge) |
| `index.merge.policy.segments_per_tier` | 10 | dynamic | index | Number of segments allowed per tier. | ↑ Fewer merges, but more segments.<br>↓ Merges run more often and I/O increases. | INFO / INFO | [Merge settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/merge) |
| `index.number_of_replicas` | 1 | dynamic | index | Number of replicas per shard. | ↑ Availability and search throughput increase, but disk and indexing cost grow in proportion to the replica count.<br>↓ With 0, the failure of a single node can lose data. | INFO / WARNING | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.queries.cache.enabled` | true | static | index | Use of the node query (filter) cache. | With false, repeated filters are recomputed every time. | INFO | [Node query cache settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/node-query-cache-settings) |
| `index.refresh_interval` | 1s (search idle applies when not set) | dynamic | index | How often new documents become visible to search. | ↑ Indexing throughput increases and merge load decreases, but documents become searchable later. -1 stops refresh.<br>↓ Segments are created more often, which increases CPU and merge load. Setting it explicitly turns off the search idle optimization. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.requests.cache.enable` | true | dynamic | index | Use of the shard request cache. | With false, repeated aggregations are recomputed every time. | INFO | [Node query cache settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/node-query-cache-settings) |
| `index.routing.allocation.total_shards_per_node` | -1 | dynamic | index | Upper limit on the number of shards of this index per node (prevents hot spots). | ↓ If it is too small, shards have nowhere to go when a node fails and stay unassigned. | - / WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `index.search.idle.after` | 30s | dynamic | index | How long without searches before periodic refresh is skipped. | ↑ The benefit of skipping refresh starts later.<br>↓ Search idle starts sooner, so an occasional first search has to wait for a refresh. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.translog.durability` | request | dynamic | index | Whether the translog is fsynced on every request (request) or periodically (async). | With async, indexing is faster, but an unclean node shutdown can lose acknowledged writes from the last sync_interval. | WARNING | [Translog settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/translog) |
| `index.translog.sync_interval` | 5s | dynamic | index | Translog fsync interval in async mode. | ↑ The window in which data can be lost in async mode gets longer.<br>↓ fsync runs more often. | INFO / INFO | [Translog settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/translog) |
| `index.unassigned.node_left.delayed_timeout` | 1m | dynamic | index | How long replica reallocation is delayed after a node leaves. | ↑ The cluster stays yellow longer while waiting for the node to come back, but unnecessary re-replication is reduced.<br>↓ Even a brief restart starts full re-replication (0 means immediately). | INFO / WARNING | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `indices.breaker.fielddata.limit` | 40% | dynamic | cluster | Limit for loading fielddata (relative to heap). | ↑ Aggregations on text fields and similar operations eat into heap and increase GC pressure.<br>↓ Aggregations are rejected sooner. | WARNING / INFO | [Circuit breaker settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/circuit-breaker-settings) |
| `indices.breaker.request.limit` | 60% | dynamic | cluster | Memory limit per request (for aggregations and so on). | ↑ A large aggregation can take most of the heap.<br>↓ Aggregations are rejected sooner. | WARNING / INFO | [Circuit breaker settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/circuit-breaker-settings) |
| `indices.breaker.total.limit` | 95% | dynamic | cluster | Parent breaker limit (95% when use_real_memory=true, 70% when false). | ↑ Requests are accepted until just before OOM, which raises the risk that the node dies with OutOfMemoryError.<br>↓ Even normal requests are rejected with CircuitBreakingException. | WARNING / INFO | [Circuit breaker settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/circuit-breaker-settings) |
| `indices.breaker.total.use_real_memory` | true | static | node | The parent breaker decides based on actual heap usage. | With false, it uses estimates (default limit 70%), which can diverge from actual heap usage. | WARNING | [Circuit breaker settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/circuit-breaker-settings) |
| `indices.fielddata.cache.size` | unbounded | static | node | Upper limit of the fielddata cache (unlimited by default; the effective limit is the fielddata breaker). | With a limit, evictions occur and those aggregations reload fielddata every time. | INFO | [Field data cache settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/field-data-cache-settings) |
| `indices.lifecycle.poll_interval` | 10m | dynamic | cluster | How often ILM conditions are checked. | ↑ Rollover and deletion run late, so shard sizes and disk usage grow beyond plan.<br>↓ Master load increases. Do not lower it except for testing. | INFO / WARNING | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `indices.memory.index_buffer_size` | 10% | static | node | Indexing buffer (relative to heap), shared by the shards that are being written to. | ↑ Bulk indexing is more efficient, but less heap is left for search and aggregations.<br>↓ Flushes become more frequent and small segments increase. | INFO / INFO | [Indexing buffer settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/indexing-buffer-settings) |
| `indices.queries.cache.size` | 10% | static | node | Size of the node query (filter) cache (relative to heap). | ↑ More heap stays occupied, which increases GC pressure.<br>↓ The filter cache hit rate drops. | INFO / INFO | [Node query cache settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/node-query-cache-settings) |
| `indices.recovery.max_bytes_per_sec` | 40mb | dynamic | cluster | Recovery bandwidth limit per node (dedicated cold/frozen nodes get a value calculated automatically from memory). | ↑ Recovery is faster, but recovery traffic can take I/O away from the service.<br>↓ Recovery after a node replacement or restart is slower, so the cluster stays yellow longer. | INFO / WARNING | [Index recovery settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/index-recovery-settings) |
| `indices.requests.cache.size` | 1% | static | node | Size of the shard request cache (relative to heap). | ↑ More heap stays occupied.<br>↓ The aggregation result cache helps less. | INFO / INFO | [Node query cache settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/node-query-cache-settings) |
| `ingest.geoip.downloader.enabled` | true | dynamic | cluster | Automatic download of the GeoIP database. | false is normal in an air-gapped environment. In that case you must distribute the database manually for the geoip processor to work. | - | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `network.breaker.inflight_requests.limit` | 100% | dynamic | cluster | Size limit for in-flight requests (transport/HTTP). | ↑ Large bulk requests arriving together can spike heap.<br>↓ Large requests are rejected. | WARNING / INFO | [Circuit breaker settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/circuit-breaker-settings) |
| `node.processors` | Number of available processors (automatic) | static | node | Number of CPUs that ES sees (the basis for thread pool sizing). | Setting it too high creates too many threads, and too low leaves CPU unused. Use it to match the CPU limit in a container. | INFO | [Thread pool settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings) |
| `node.store.allow_mmap` | true | static | node | Use of mmap for Lucene files. | With false, files are read through NIO instead of mmap, which can reduce search performance (for environments that cannot raise vm.max_map_count). | INFO | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `script.max_compilations_rate` | 150/5m | dynamic | cluster | Rate limit for script compilation. | Raising it hides misuse (sending a different script each time instead of using params) and increases CPU and memory load. | INFO | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `search.allow_expensive_queries` | true | dynamic | cluster | Whether expensive queries such as script, wildcard, regexp, and fuzzy are allowed. | With false, those queries are rejected (as a protection). Some Kibana features can be affected. | INFO | [Search settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/search-settings) |
| `search.default_search_timeout` | -1 | dynamic | cluster | Search timeout applied when the request has no timeout (-1 = unlimited). | A short value makes heavy queries end with partial results. With unlimited, a runaway query can hold resources indefinitely. | INFO | [Search settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/search-settings) |
| `search.low_level_cancellation` | true | dynamic | cluster | Applies search cancellation requests quickly at segment level. | With false, a cancelled search stops late and uses resources longer. | INFO | [Search settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/search-settings) |
| `search.max_buckets` | 65536 | dynamic | cluster | Maximum number of aggregation buckets in a single response. | ↑ Large aggregations are allowed, which raises the risk of heap pressure on the coordinating node and circuit breaker trips.<br>↓ Existing dashboard aggregations can fail. | WARNING / INFO | [Search settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/search-settings) |
| `slm.retention_schedule` | 0 30 1 * * ? | dynamic | cluster | How often the SLM retention policy (deletion of old snapshots) runs. | The run time changes. If it is too infrequent, the snapshot repository grows beyond plan. | - | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `thread_pool.search.queue_size` | Calculated automatically (observed on 9.4.4: number of search threads x 1000, 1000 per the documentation for 8.x and earlier) | static | node | Queue size of the search thread pool. | ↑ Fewer rejections, but search latency and heap usage increase.<br>↓ Rejections start sooner. | WARNING / INFO | [Thread pool settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings) |
| `thread_pool.search.size` | int((cores x 3) / 2) + 1 (automatic) | static | node | Number of search threads. | Arbitrary changes cause CPU contention or lower throughput. | WARNING | [Thread pool settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings) |
| `thread_pool.write.queue_size` | 10000 | static | node | Queue size of the write thread pool. | ↑ Fewer rejections, but requests wait longer in the queue, which adds latency and heap usage. It also hides the root cause (overload).<br>↓ Rejections (429) start sooner. | WARNING / INFO | [Thread pool settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings) |
| `thread_pool.write.size` | Number of CPU cores (automatic) | static | node | Number of write threads. | Setting it above the core count only adds context switching and does not increase throughput. | WARNING | [Thread pool settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings) |
| `transport.compress` | indexing_data | dynamic | cluster | What is compressed in node-to-node transport. | true compresses all transport and uses more CPU. false does not even compress indexing data, so network usage grows. | INFO | [Networking settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/networking-settings) |
| `xpack.ml.max_machine_memory_percent` | 30 | dynamic | cluster | Share of node memory that ML can use. | ↑ ML processes take memory away from the filesystem cache and other processes.<br>↓ ML jobs may fail to be allocated. | INFO / INFO | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `xpack.monitoring.collection.enabled` | false | dynamic | cluster | Legacy internal monitoring collection. | With true, monitoring data is indexed into the cluster itself, which adds load. Use a separate cluster for production monitoring. | INFO | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `cluster.routing.allocation.exclude.*` | (none) | dynamic | cluster | Moves shards off the specified nodes (by name, IP, host, or attribute). | No shards are placed on those nodes. If you do not remove the setting after maintenance, shards pile up on other nodes even though capacity is free. | WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.include.*` | (none) | dynamic | cluster | Allows shard placement only on the specified nodes. | Shards are not placed on nodes that do not match, which can cause uneven distribution or unassigned shards. | WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.require.*` | (none) | dynamic | cluster | Places shards only on nodes that meet all the specified conditions. | If too few nodes meet the conditions, shards stay unassigned. | WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `logger.*` | INFO (default per logger) | dynamic | cluster | Logger level. | Raising it to DEBUG/TRACE sharply increases log volume and affects disk, I/O, and performance. Set it back to null after the investigation. | INFO | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |

## All thresholds

`[Official]` marks a number taken from the official documentation, `[Tool]` a value chosen by this tool. Entries without a note are tool judgments.

| Key | Default | Description |
| --- | --- | --- |
| `heap_used_pct_warn` | 75 | [Tool] Heap usage at collection time |
| `heap_used_pct_crit` | 85 | [Tool] Heap usage at collection time |
| `heap_max_bytes_crit` | 32GiB | [Official] Compressed oops boundary (below 32GB recommended) |
| `heap_vs_ram_pct_warn` | 50 | [Official] Heap <= 50% of total memory |
| `heap_vs_ram_tolerance_pct` | 2 | [Tool] Tolerance for rounding and adjusted_total error |
| `old_gc_time_ratio_warn` | 0.02 | [Tool] Cumulative old GC time / uptime |
| `old_gc_time_ratio_crit` | 0.05 | [Tool] Cumulative old GC time / uptime |
| `young_gc_time_ratio_warn` | 0.05 | [Tool] Cumulative young GC time / uptime |
| `old_gc_per_hour_warn` | 6 | [Tool] Old GC count per hour |
| `old_gc_per_hour_crit` | 30 | [Tool] Old GC count per hour |
| `load_per_cpu_warn` | 1.0 | [Tool] load15 / CPU cores |
| `load_per_cpu_crit` | 1.5 | [Tool] load15 / CPU cores |
| `fd_used_pct_warn` | 70 | [Tool] Open files / maximum (official minimum limit is 65,535) |
| `cgroup_throttle_ratio_warn` | 0.01 | [Tool] throttled / elapsed periods |
| `cgroup_throttle_ratio_crit` | 0.05 | [Tool] throttled / elapsed periods |
| `uptime_short_hours` | 6 | [Tool] Treats the node as recently restarted |
| `disk_watermark_low_default` | 85% | [Official] ES default (used only when no settings file is present) |
| `disk_watermark_high_default` | 90% | [Official] ES default (used only when no settings file is present) |
| `disk_watermark_flood_default` | 95% | [Official] ES default (used only when no settings file is present) |
| `disk_watermark_flood_frozen_default` | 95% | [Official] Flood stage for frozen-only nodes |
| `disk_watermark_flood_frozen_headroom_default` | 20GB | [Official] Frozen flood max_headroom |
| `disk_imbalance_pct_warn` | 15 | [Tool] Disk usage spread between nodes (percentage points) |
| `disk_low_margin_pct` | 10 | [Tool] Percentage points left before the effective low watermark |
| `rejected_crit` | 1,000 | [Tool] Total cumulative rejections |
| `breaker_tripped_warn` | 1 | [Tool] Breaker trip count (1 = any history) |
| `shards_per_gb_heap_warn` | 20 | [Official] 20 shards per 1GB of heap (versions before 8.3 only) |
| `shards_per_gb_heap_crit` | 30 | [Tool] Versions before 8.3 only |
| `max_shards_per_node_headroom_pct_warn` | 80 | [Tool] Usage against cluster.max_shards_per_node |
| `shard_size_gb_warn` | 50 | [Official] Shards of 10-50GB |
| `shard_size_gb_crit` | 200 | [Tool] Upper bound based on recovery time |
| `small_shard_mb` | 1,024 | [Tool] Small shard threshold |
| `small_shard_count_warn` | 50 | [Tool] |
| `small_shard_ratio_warn` | 0.5 | [Tool] |
| `deleted_docs_ratio_warn` | 0.25 | [Tool] |
| `segments_per_shard_warn` | 50 | [Tool] |
| `merge_throttle_ratio_warn` | 0.05 | [Tool] |
| `search_latency_ms_warn` | 200 | [Tool] Average query latency per index |
| `search_latency_ms_crit` | 1,000 | [Tool] Average query latency per index |
| `index_latency_ms_warn` | 50 | [Tool] Average indexing time per document |
| `index_latency_ms_crit` | 200 | [Tool] Average indexing time per document |
| `min_query_total_for_latency` | 100 | [Tool] Indices with too few samples are not rated |
| `fielddata_heap_pct_warn` | 10 | [Tool] fielddata / heap |
| `pending_tasks_warn` | 10 | [Tool] |
| `pending_tasks_crit` | 100 | [Tool] |
| `max_task_wait_ms_warn` | 30,000 | [Tool] |
| `long_running_task_ms_warn` | 300,000 | [Tool] 5 minutes |
| `license_expiry_days_warn` | 90 | [Tool] |
| `license_expiry_days_crit` | 30 | [Tool] |
| `cert_expiry_days_warn` | 90 | [Tool] |
| `cert_expiry_days_crit` | 30 | [Tool] |
| `snapshot_age_hours_warn` | 36 | [Tool] Age of the latest snapshot |
| `snapshot_age_hours_crit` | 168 | [Tool] 7 days |
| `snapshot_failed_warn` | 1 | [Tool] |
| `ingest_failed_warn` | 1 | [Tool] |
| `hot_thread_pct_warn` | 50 | [Tool] CPU% of a single thread |
| `log_scan_bytes` | 8MiB | [Tool] Bytes scanned per log file (from the end) |
| `docs_per_shard_warn` | 200,000,000 | [Official] Fewer than 200 million documents per shard recommended |
| `flush_avg_ms_info` | 800 | [Tool] Field baseline: average flush time per flush |
| `flush_avg_ms_warn` | 1,200 | [Tool] Field baseline |
| `refresh_avg_ms_info` | 40 | [Tool] Field baseline: average refresh time per refresh |
| `refresh_avg_ms_warn` | 70 | [Tool] Field baseline |
| `merge_avg_ms_info` | 20,000 | [Tool] Field baseline: average merge time per merge |
| `merge_avg_ms_warn` | 40,000 | [Tool] Field baseline |
| `write_latency_min_ops` | 100 | [Tool] Minimum flushes/refreshes/merges before a node average is rated |
| `load_host_cpu_pct_max` | 20 | [Tool] Container nodes below this CPU percentage are not rated on load average |
| `write_shard_skew_warn` | 0.5 | [Tool] (max - min) / average of write-target shards per node in a tier |
| `write_shard_skew_min` | 3 | [Tool] Minimum difference in write-target shards before it is reported |
| `restart_share_warn` | 0.5 | [Tool] Share of nodes restarted within uptime_short_hours |
| `long_running_task_ms_high` | 3,600,000 | [Tool] 1 hour: long task becomes a Warning |
| `monitoring_task_ms_info` | 86,400,000 | [Tool] 24 hours: monitoring/internal tasks are reported only past this |
| `translog_flush_threshold_default` | 10gb | [Official] index.translog.flush_threshold_size default (8.8+) |
| `translog_flush_threshold_legacy` | 512mb | [Official] Default before 8.8 |
| `docs_rollover_overshoot_pct` | 5 | [Tool] Allowed overshoot of a rolled-over shard past 200M docs (ILM checks every poll_interval) |
| `docs_per_shard_crit` | 1,500,000,000 | [Tool] Alert when approaching the Lucene limit (2,147,483,519) |
| `indices_per_gb_master_heap` | 3,000 | [Official] 3000 indices per 1GB of master heap |
| `mapping_heap_pct_warn` | 50 | [Tool] Estimated mapping overhead / heap |
| `heap_baseline_bytes` | 512MiB | [Official] Extra 0.5GB margin in the field mapper estimate |
| `empty_index_count_warn` | 5 | [Tool] |
| `heavy_index_docs` | 10,000,000 | [Tool] Threshold for a heavily indexed index |
| `index_buffer_per_shard_warn` | 32MiB | [Tool] Per write-target shard (official upper bound is 512MB) |
| `open_contexts_warn` | 100 | [Tool] |
| `search_heavy_query_total` | 100,000 | [Tool] Threshold for a search-heavy index |
| `preload_index_count_warn` | 5 | [Tool] |
| `codec_check_min_bytes` | 50GiB | [Tool] |
| `vector_vs_fscache_pct_warn` | 60 | [Tool] Resident vector size / (RAM - heap) |
| `vector_dim_quantize_warn` | 384 | [Official] Quantization recommended for float vectors of 384 dimensions or more |
| `vector_segments_per_shard_warn` | 20 | [Tool] |
| `avg_doc_bytes_warn` | 1MiB | [Tool] Average document size of 1MB |
| `tier_cpu_pct_warn` | 75 | [Tool] CPU% at which a whole tier counts as saturated |
| `hotspot_heap_pct_gap` | 30 | [Tool] Heap spread between nodes (percentage points) |
| `hotspot_heap_pct_floor` | 70 | [Tool] Ignored if the maximum is below this |
| `hotspot_cpu_pct_floor` | 50 | [Tool] |
| `hotspot_disk_pct_floor` | 50 | [Tool] |
| `hotspot_cpu_pct_gap` | 40 | [Tool] |
| `workload_skew_ratio_warn` | 1.8 | [Tool] Busiest node / average |
| `undesired_shards_warn` | 1 | [Tool] |
| `recovery_rate_low_bytes` | 40MiB | [Official] indices.recovery.max_bytes_per_sec at or below the 40mb default |
| `oversharding_floor_shard_gb` | 10 | [Official] Recommended lower bound per shard, 10GB |
| `oversharding_target_shard_gb` | 50 | [Official] Recommended upper bound per shard, 50GB (used for the recommended primary count) |
| `oversharding_excess_warn` | 20 | [Tool] Total number of shards that could be removed |
| `oversharding_excess_ratio_warn` | 0.1 | [Tool] Share of all shards |
| `oversharding_min_shards` | 20 | [Tool] Minimum sample size for the distribution rating |
| `oversharding_small_share_warn` | 0.8 | [Tool] Share of shards under 10GB |
| `oversharding_min_data_gb` | 100 | [Tool] Small clusters are not rated on distribution |
| `ds_min_backing_indices` | 5 | [Tool] Minimum backing index count for the data stream rating |
| `ds_small_backing_shard_gb` | 1 | [Tool] Median backing shard size threshold |
| `logsdb_shard_gb_high` | 30 | [Tool] Upper end of the logsdb shard range (official upper bound is 50GB) |
| `logsdb_shard_gb_low` | 10 | [Official] Lower end of the 10-50GB shard range |
| `logsdb_rows_max` | 100 | [Tool] Maximum indices listed in the logsdb shard size table |
| `mapping_fields_near_limit_pct` | 90 | [Tool] Field count against total_fields.limit |
| `ilm_rollover_max_shard_gb` | 50 | [Official] Recommended upper bound for shard size at rollover |
| `ilm_implicit_max_shard_docs` | 200,000,000 | [Official] Rollover always runs at 200M docs per shard; higher values have no effect |
| `forcemerge_free_space_factor` | 3 | [Official] max_num_segments=1 may need free space up to 3x the shard size |
| `forcemerge_stuck_hours` | 24 | [Tool] Time in the forcemerge action before it is reported |
| `disk_io_busy_pct_warn` | 60 | [Tool] Average disk utilization since startup |
| `search_expensive_share_warn` | 10 | [Tool] Share of expensive query types in all searches (%) |
| `diff_min_hours_for_projection` | 1.0 | [Tool] No extrapolation for intervals shorter than this |
| `disk_projection_days_warn` | 30 | [Tool] |
| `index_growth_min_bytes` | 1GiB | [Tool] |
| `top_n` | 15 | [Tool] Maximum rows in an evidence table |
| `eol_major_below` | 8 | [Tool] Majors below this trigger an old-version warning |
