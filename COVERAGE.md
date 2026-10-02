# Coverage against the official guides

English · [한국어](COVERAGE.ko.md)

> This table shows which rule covers each item in the Elastic documentation, or why the item cannot be evaluated.
> For the exact conditions and thresholds of each rule, see [RULES.md](RULES.md). For the change history, see [CHANGELOG.md](CHANGELOG.md).
> Reference version: Elasticsearch 9.4 documentation (checked 2026-09).
> Validation scope: tested on real bundles in **api mode** (ECH 9.4.4 and 9.5.3) and **local mode** (self-managed 8.19.21, single node). Remote mode and multi-node local mode are not validated yet.

Each item in the Elastic documentation was checked one by one. Items that a diagnostics bundle can prove are implemented as rules.
Items the bundle does not collect are listed as limits.

Status labels
- **Implemented**: evaluated automatically by a rule
- **Partial**: only some signals can be evaluated (indirect indicators)
- **Not possible**: the bundle has no data for this item, so the report does not cover it (check on site)

---

## 1. Important settings configuration
`https://www.elastic.co/docs/deploy-manage/deploy/self-managed/important-settings-configuration`

| Documentation item | Status | Rule |
| --- | --- | --- |
| Bootstrap checks (dev vs production mode) | Implemented | CFG-006 (the actual bound address, transport_address, is loopback, or the cluster is single-node) |
| Path settings (path.data / path.logs outside $ES_HOME) | Implemented | CFG-002 (archive installs only) |
| Multiple data paths (deprecated) | Implemented | CFG-003 |
| Cluster name setting | Implemented | CFG-001 (detects the default name elasticsearch) |
| Node name setting | Partial | Shown in the node summary table (the default, the hostname, is normal, so it is not flagged) |
| Network host settings | Implemented | CFG-006 |
| discovery.seed_hosts | Implemented | CFG-004 |
| Remove cluster.initial_master_nodes | Implemented | CFG-005 |
| Heap size settings | Implemented | JVM-002 (32 GB boundary), JVM-003 (relative to RAM), JVM-004 (Xms differs from Xmx) |
| JVM heap dump path | Implemented | CFG-007 |
| GC logging settings | Implemented | CFG-008 |
| JVM fatal error log (ErrorFile) | Implemented | CFG-009 |
| Temporary directory settings | Not possible | The $ES_TMPDIR value is not in the bundle |
| Cluster backups (snapshot / SLM) | Implemented | SNP-001 to SNP-006 |
| DNS cache settings | Partial | Visible if set in the JVM arguments, but the default is recommended, so there is no rule |

When the deployment is detected as ECH, ECE, or ECK, the CFG items above fall under the orchestrator's control.
The tool lowers their severity to Info and says so in the report.

---

## 2. Size your shards
`.../production-guidance/optimize-performance/size-shards`

| Documentation item | Status | Rule |
| --- | --- | --- |
| Shard size 10-50 GB | Implemented | SHD-003 (over 50 GB), SHD-002 (over 200 GB, tool threshold), SHD-004 (small shards), SHD-005 (average), OVS-001 to OVS-003 (oversharding) |
| At most 200M documents per shard | Implemented | SHD-008 (write index, or index without rollover), SHD-013 (rolled-over index far above 200M: rollover ran late) |
| Lucene MAX_DOC limit (2,147,483,519) | Implemented | SHD-007 (based on docs.count + docs.deleted) |
| Shard distribution / unbalanced cluster / hot spotting | Implemented | SHD-006 and DISK-005 (compared within the same tier), HOT-003 (desired balance has not converged) |
| A search uses one thread per shard, so too many shards exhaust the thread pool | Implemented | TP-001, CLU-015 (SHD-001 applies only below 8.3) |
| Overhead per index, shard, segment, and field | Implemented | IDX-004 (segments), MAP-001/002 |
| 3000 indices per 1 GB of master heap | Implemented | SHD-009 |
| Cluster shard limit (1000 per node, 3000 for frozen) | Implemented | CLU-015 |
| Heap headroom for field mappers (cluster state + node overhead + 0.5 GB) | Implemented | SHD-010 |
| Prevent hot spots with total_shards_per_node | Implemented | SHD-012 |
| Avoid unnecessary dynamic fields | Implemented | MAP-003 |
| Use data streams + ILM | Implemented | ILM-003, IDX-010 |
| Delete empty indices | Implemented | SHD-011 |
| Consolidate with force merge / shrink / reindex | Implemented | Included in the IDX-003 and IDX-004 recommendations |
| Delete indices instead of deleting documents | Implemented | IDX-003 (share of deleted documents) |

---

## 3. Tune for indexing speed
`.../optimize-performance/indexing-speed`

| Documentation item | Status | Rule |
| --- | --- | --- |
| Use bulk requests / tune their size | Partial | Overload is detected through IP-001 (indexing pressure rejections) and TP-001 (write rejections) |
| Use multiple workers, watch for 429 | Implemented | TP-001, IP-001 |
| Increase refresh_interval | Implemented | IDX-007 |
| Use 0 replicas for the initial load | Partial | IDX-001 lists indices with 0 replicas (whether this is intentional is a human call) |
| Disable swap | Implemented | OS-002, OS-005 |
| Leave memory for the filesystem cache | Implemented | JVM-003 |
| Use auto-generated ids | Not possible | The indexing requests are not in the bundle |
| Fast hardware (SSD), local vs remote storage | Implemented | PERF-009, IDX-005 (merge throttling) |
| indices.memory.index_buffer_size (512 MB maximum per shard) | Implemented | PERF-004 |
| Separate search and indexing resources with CCR | Partial | OPS-002 evaluates only CCR errors |
| Avoid hot spotting | Implemented | HOT-001 and HOT-002 (skew within the same tier), HOT-005 (whole tier saturated), SHD-006, SHD-012 |

---

## 4. Tune for search speed
`.../optimize-performance/search-speed`

| Documentation item | Status | Rule |
| --- | --- | --- |
| Leave memory for the filesystem cache | Implemented | JVM-003 |
| Readahead value (128 KiB) | Not possible | Not in api mode bundles. It is in `syscalls/readahead.txt` (lsblk RA) in local and remote mode, but the tool does not read it yet |
| Fast hardware / local storage | Implemented | PERF-009 |
| Document modeling (avoid nested and join) | Partial | PERF-011 (share of nested, has_child, has_parent use), MAP-006 (number of nested fields). The affected index cannot be identified |
| Minimize searched fields (copy_to) | Not possible | The query bodies are not in the bundle |
| Pre-index data | Not possible | Same as above |
| Map identifiers as keyword | Partial | Visible only within template mappings |
| Avoid scripts | Partial | PERF-011 (share of script, script_score, script_fields, runtime_mappings use), RT-001 (painless stack classification) |
| Round dates to use the cache | Implemented | PERF-003 (inferred from cache hit ratio and evictions) |
| Force-merge read-only indices | Implemented | IDX-004 |
| Warm up global ordinals | Implemented | FD-001/002, RT-001 (GlobalOrdinals stack classification) |
| index.store.preload | Implemented | PERF-008 |
| Index sorting | Not possible | It is a recommendation, and the criteria depend on the workload |
| Use preference to benefit from the cache | Partial | PERF-003 |
| Relationship between replica count and throughput | Implemented | PERF-007 (applies the official recommended formula) |
| ES\|QL optimization | Not possible | Needs the query bodies |
| Search Profiler | Not possible | Runtime tool |
| index_phrases / index_prefixes / constant_keyword | Not possible | Needs mapping and query details |
| search.default_search_timeout | Implemented | PERF-006 |
| Too many open search contexts | Implemented | PERF-005 |

---

## 5. Tune approximate kNN search
`.../optimize-performance/approximate-knn-search`

| Documentation item | Status | Rule |
| --- | --- | --- |
| Reduce vector memory use (quantization) | Implemented | VEC-002 (float vectors with 384 or more dimensions and no quantization) |
| Reduce vector dimensions | Implemented | VEC-002 evidence table shows dims |
| Exclude vectors from _source | Implemented | VEC-003 (recommends exclude_source_vectors) |
| Enough data node memory (HNSW/DiskBBQ) | Implemented | VEC-001 (total vector off-heap vs RAM minus heap) |
| Warm up the filesystem cache (preload) | Implemented | PERF-008 (also warns about overuse) |
| Fewer segments / raise max_merged_segment | Implemented | VEC-004 |
| Create large segments for bulk loads | Implemented | Included in the VEC-004 recommendation |
| GPU-accelerated indexing | Not possible | No hardware configuration data |
| Avoid heavy indexing during search | Partial | Signal-based, from PERF-002 combined with VEC-004 |
| Readahead | Not possible | Not in api mode bundles. `syscalls/readahead.txt` in local and remote mode is not read yet |
| on_disk_rescore | Implemented | Included in the VEC-001 recommendation |

---

## 6. Tune for disk usage
`.../optimize-performance/disk-usage`

| Documentation item | Status | Rule |
| --- | --- | --- |
| Disable unneeded features (index:false, match_only_text) | Partial | Visible only within template mappings |
| Avoid the default dynamic string mapping | Implemented | MAP-003 |
| Manage shard size | Implemented | SHD-002 to SHD-005 |
| Reduce _source overhead (synthetic / disable) | Implemented | DISK-007 |
| best_compression codec | Implemented | DISK-006 |
| Force merge | Implemented | IDX-003, IDX-004 |
| Shrink index | Implemented | Included in the SHD-004 recommendation |
| Use the smallest numeric type | Not possible | Needs mapping details |
| Improve compression with index sorting | Not possible | Depends on the workload |
| Keep field order fixed | Not possible | Needs the document bodies |
| Define the data lifecycle (ILM, downsampling) | Implemented | ILM-001 to ILM-003 |

---

## 7. General recommendations
`.../production-guidance/general-recommendations`

| Documentation item | Status | Rule |
| --- | --- | --- |
| Avoid returning large result sets (use scroll / search_after) | Implemented | GEN-001 (detects a raised max_result_window), PERF-005 |
| Avoid large documents (http.max_content_length 100MB, Lucene 2GB) | Implemented | GEN-002 |
| Network, memory, and disk cost of large documents | Implemented | GEN-003 (average document size per index) |

## 8. Performance optimizations (parent index page)
`.../production-guidance/optimize-performance`

This page is a table of contents for the five documents above. It has no separate items to evaluate.

---

---

## 9. Static and dynamic settings, and the cluster update settings API
`https://www.elastic.co/docs/deploy-manage/stack-settings#static-dynamic`
`https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-cluster-put-settings`

| Documentation item | Status | Rule |
| --- | --- | --- |
| Precedence: transient > persistent > elasticsearch.yml > default | Implemented | SET-001, SET-003 (a yml value is overridden by an API value) |
| Transient settings are discouraged (they can disappear unexpectedly when the cluster is unstable) | Implemented | CLU-013, SET-001 recommendation |
| Set a value to null to reset it to the default | Implemented | SET-001 and SET-002 recommendations |
| Static settings are changed only in the yml of every target node and need a restart | Implemented | SET-004 (node settings changed), SET-005 (mismatch between nodes) |
| Change dynamic settings through the API; keep only static and node-specific settings in yml | Implemented | SET-003 recommendation |
| Elastic Cloud is managed through user settings | Implemented | After the deployment type is detected, SET-004 is lowered to Info |
| Default, meaning, and side effects of each setting | Implemented | Settings knowledge base with 94 entries (RULES.md appendix) |

Limits of the diagnostics bundle: `cluster_settings_defaults` does not hold pure defaults. It reflects values from the yml, and it does not report a default for any key set explicitly through the API.
`settings.json` (per index) has no defaults section. The tool therefore uses its knowledge base for the original defaults.

## 10. Oversharding and small shards (Size your shards)

| Documentation item | Status | Rule |
| --- | --- | --- |
| Shard size 10-50 GB | Implemented | OVS-001 (indices below the lower bound, and how many shards to remove), OVS-003 (distribution), SHD-002/003 (over the upper bound) |
| Avoid unnecessary small shards | Implemented | OVS-001, OVS-003, SHD-004 |
| Roll over based on max_primary_shard_size | Implemented | OVS-002 (data streams that roll over too often) |
| Reduce primaries with shrink | Implemented | OVS-001 recommendation |
| Delete empty indices | Implemented | SHD-011 |
| Shard limit | Implemented | CLU-015 |

### 10-1. Document limit, logsdb and force merge

| Documentation item | Status | Rule |
| --- | --- | --- |
| Rollover always runs at 200M documents per shard; a higher `max_primary_shard_docs` has no effect (ILM rollover) | Implemented | SHD-013, ILM-007 |
| ILM checks conditions every `indices.lifecycle.poll_interval`, 10m by default (ILM settings) | Used | Basis for the SHD-013 allowance (5%, tool threshold) |
| From 9.0, logsdb applies to new `logs-*-*` data streams; streams that existed before an upgrade stay as they are (Logs data streams) | Implemented | IDX-013 |
| logsdb sorts by host.name and @timestamp by default; synthetic _source needs a subscription (Configure a logs data stream) | Used | Reasons and recommendations of SHD-014 and IDX-013 |
| Index sorting costs time at flush and merge (Index sorting) | Used | Reasons in SHD-014 and ILM-009 |
| `max_num_segments=1` can need up to 3 times the shard size in free space; the force_merge pool is `max(1, processors/8)` (Force merge API) | Implemented | ILM-008, ILM-009 |
| searchable_snapshot `force_merge_index` (default true) merges to one segment in the tier of the preceding phase (ILM searchable snapshot) | Implemented | ILM-008 |
| logsdb shards of 10-30 GB | Tool threshold | SHD-014 (30 GB or more, Info), SHD-015 (rolled over under 10 GB, Info). 30 GB is not an official number; it follows an Elastic internal discussion. The official 10-50 GB range stays as it is |
| Priority between the implicit 200M condition and `min_*` conditions | Not implemented | The official docs do not describe how they interact |
| `logsdb_columnar` mode | Not implemented | GA status not confirmed |


### 10-2. Write path and operations

| Item | Status | Rule |
| --- | --- | --- |
| Indexing is throttled when merges fall behind (Merge settings) | Implemented | IDX-014 |
| `index.translog.flush_threshold_size` defaults to 10GB (8.8+); uncommitted operations are replayed on recovery (Translog settings) | Implemented | IDX-015 |
| Average flush, refresh and merge time | Tool threshold | PERF-012 (field baseline, not an official number) |
| Write-target shards concentrated on some nodes | Tool threshold | SHD-016 |
| Reliability of cumulative counters after a mass restart | Tool threshold | OS-007 |
| Whether the compared bundles are from the same cluster | Implemented | DIF-013 |
| Disk read/write latency (ms/op) | Cannot be evaluated | nodes stats `fs.io_stats` has no read or write time fields |

### 10-3. Bottleneck summary, restarts and storage cost

| Item | Status | Rule |
| --- | --- | --- |
| Where to look first when ingest or search is slow | Tool judgment | Bottleneck summary (symptoms first, then cause groups in a fixed order) |
| Recently restarted nodes have cold caches and short counters | Tool threshold | Left out of HOT-001 (heap, CPU), HOT-002 and DIF-009 for 24 hours; PERF-012 picks indexing nodes by hourly rate |
| Nodes with a shared cache can only have a single data path; the cache is cleared on restart (Searchable snapshots) | Used | FRZ-002 (cache file location, recommendation) |
| Frozen shared cache on a network filesystem | Tool threshold | FRZ-002 |
| Search threads busy while CPU is low | Tool threshold | PERF-013 (point in time) |
| Ingest pipeline failure ratio | Tool threshold | ING-001 |
| Rolled-over data on hot, idle extra replicas, tier disk use, ingest headroom | Tool threshold | COST-001 to COST-004 (Info, COST-004 can be Warning) |
| Search thread wait time in hot threads ("other") as an I/O signal | Not used | It also counts time waiting on locks, so it does not identify storage waits |
| Load average above the core count as I/O wait | Not used | Inside a container the load can be the host's (OS-001) |

### 10-4. Official documentation re-check (2026-10)

Every finding labeled Official, every version gate and every settings default was checked again against the current docs, and against the Elasticsearch source where the docs are silent. The changes are listed in CHANGELOG 0.14.0 under "Official documentation audit".

| Item | Status | Rule |
| --- | --- | --- |
| Compressed oops: 26GB safe on most systems, up to about 30GB (JVM settings) | Implemented | JVM-002 (the JVM flag decides first) |
| Closed indices do not count toward the shard limit; frozen indices have their own limit (Miscellaneous cluster settings) | Implemented | CLU-015 |
| `"_source": {"enabled": false}` disables _source (_source field) | Implemented | DISK-007 |
| Default max_headroom applies from 8.5 and only when the watermark is not set explicitly | Implemented | DISK-001 to DISK-005 |
| Bootstrap checks apply only in production mode | Implemented | SYS-001, SYS-003 |
| Dedicated master nodes "once a cluster has more than a handful of nodes" | Tool threshold | CLU-007 (10 data nodes, field guideline) |
| ERU consumption | Not implemented | The docs give no formula and say billing depends on the contract |

---

## 11. Troubleshooting documents (operational criteria)

| Document | What the tool reflects | Rule |
| --- | --- | --- |
| Hot spotting | Detects uneven resource use and workload across nodes. Compares only nodes with the same role (tier) | HOT-001, HOT-002, HOT-005, SHD-006, DISK-005 |
| Unbalanced cluster / desired balance | Shards that have not reached the target placement | HOT-003, HOT-004 |
| Diagnose unassigned shards | Distribution of unassigned reasons and the allocation explain deciders | CLU-002, CLU-003 |
| Disk watermarks (cluster-level shard allocation) | Effective watermarks with max_headroom applied. Frozen-only nodes use only flood_stage.frozen | DISK-001 to DISK-005 |
| Health API | Passes the indicators through as reported | CLU-004 |
| Searchable snapshots | For a partially mounted index, the store size is the cache size (excluded from size findings). For a fully mounted index it is the real size (included). Neither can be shrunk or force-merged | SHD-002 to SHD-004, OVS-001 to OVS-003, IDX-004, IDX-003 |
| ILM / data stream rollover | A write block on a rolled-over index is normal. Only a block on the current write index is a problem | IDX-008, IDX-011, OVS-002, SHD-011 |

---

## 12. Which diagnostics bundle files are used

The reference bundles (9.4.4 and 9.5.3, api mode) have the same file layout of 104 files. The tool uses **62 of them** for findings. It does not use the other 42, for the reasons below.
When a newer collection tool adds files, use this table to decide again whether to use them.
Extra files in local and remote mode bundles (server logs, OS command output, and so on) have not been checked yet.

| Reason | Files |
| --- | --- |
| Text version or subset of a JSON file the tool already reads (duplicate) | `cat/cat_aliases.txt` `cat/cat_count.txt` `cat/cat_fielddata.txt` `cat/cat_health.txt` `cat/cat_master.txt` `cat/cat_nodeattrs.txt` `cat/cat_pending_tasks.txt` `cat/cat_recovery.txt` `cat/cat_repositories.txt` `cat/cat_segments.txt` `cat/cat_templates.txt` `count.json` `master.json` `nodes_short.json` `plugins.json` (plugin use is read from nodes.json) `fielddata_stats.json` (nodes_stats and fielddata.json are used) `segments.json` (segment counts come from indices_stats) `allocation_explain_disk.json` (allocation_explain.json is used) `commercial/ilm_explain_only_errors.json` (ilm_explain.json is used) |
| Lists of settings and definitions (no state information) | `commercial/enrich_policies.json` `commercial/ccr_autofollow_patterns.json` `commercial/ml_datafeeds.json` `commercial/ml_dataframe.json` `commercial/ml_trained_models.json` `commercial/transform.json` `commercial/logstash_pipeline.json` `commercial/rollup_caps.json` `commercial/rollup_index_caps.json` |
| Has content only when the feature is in use, and there is no finding criterion yet | `commercial/ccr_follower_info.json` `commercial/enrich_stats.json` `commercial/ml_dataframe_stats.json` `commercial/ml_info.json` `commercial/ml_stats.json` `commercial/profiling_status.json` `commercial/searchable_snapshots_stats.json` `commercial/transform_basic_stats.json` `commercial/transform_node_stats.json` |
| Security configuration (outside the scope of findings, sensitive) | `commercial/security_priv.json` `commercial/security_roles.json` `commercial/security_role_mappings.json` `commercial/security_users.json` |
| API call statistics (operational reference only) | `nodes_usage.json` |

Files the tool does not read yet: `deprecation_info.json` (upgrade deprecations), `commercial/inference.json`, `commercial/connectors.json`, `streams_status.json`. The tool reads `cluster_stats.indices.versions` (distribution of index creation versions) but does not use it for findings.

Some sections of files the tool does read are also not used for findings. In `nodes_stats`, these are `http.routes` (call distribution per API), `transport`, `adaptive_selection`, and `repositories` (snapshot repository throttle). They are operational reference information, so the tool does not evaluate them.

---

## Items that cannot be evaluated, and why

0. **Remote mode and multi-node local mode are not validated on real bundles.** Local mode was tested on one single-node test environment (including server logs and `syscalls/`).


The items below are limits of what support-diagnostics collects, not defects in the tool.

1. **Query bodies are not collected.** The tool evaluates only the share of costly query patterns, using cumulative counts per query type (PERF-011). To find which queries are slow, use the slowlog (local mode) or the Search Profiler.
2. **Index setting defaults are not collected.** `settings.json` has only explicitly set values, so the tool uses a knowledge base built from the official documentation for the original defaults.
   Accuracy improves if you also collect the output of `GET <index>/_mapping`.
3. **OS kernel settings:** vm.max_map_count, vm.swappiness, nofile, nproc, and OOM killer records are read from `syscalls/` (SYS-001 to SYS-004). readahead, THP, iostat, jstack, and gc.log are not read yet.
4. **All statistics are cumulative since node start.** A single bundle cannot show when something happened.
   Use `--baseline` to compare against an earlier bundle and evaluate the increase (DIF-004 to DIF-009). If you have only one bundle,
   compare it against the logs or monitoring.

---
