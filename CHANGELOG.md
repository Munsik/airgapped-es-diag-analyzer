# Changelog

English · [한국어](CHANGELOG.ko.md)

This file follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Each entry is written as "previous behavior → current behavior (reason)". Use it to trace why a result differs from an earlier report.

## [0.14.3] - 2026-10-03

A zero-base review of every finding's logic. Each rule was read again against the Elasticsearch source (8.x and 9.5), the support-diagnostics file layout and the official docs. Confirmed errors were fixed; findings that change are listed below.

### Fixed: inputs and context

- Cluster settings: persistent was read before transient → transient wins, as in Elasticsearch
- A file holding an API error response (`{"error": ..., "status": N}`) was parsed as data → treated as missing
- `repositories.json` (`GET _snapshot`, keyed by repository name) was read as a list → converted, so SNP-001 sees the repositories
- ML-002 read the job state from the job config file, which has none → `commercial/ml_stats.json` (job stats)
- Failure store indices (`.fs-`) are judged like `.ds-` (user data unless the data stream name starts with "."). The failure store write index counts as a write target, older ones as rolled over, and all of them as managed by data stream lifecycle (ILM-003, SHD-011)
- Searchable snapshot detection by name prefix is only a fallback when the index has no settings in the bundle
- An index counts as rolled over through an alias only when another index is that alias's write index (a plain read alias no longer counts)
- A RELOCATING shard is counted on its source node
- Watermark headroom: the default `max_headroom` is dropped when the watermark is set explicitly, and a `max_headroom` set in elasticsearch.yml is used
- Container detection (OS-001, HOT-005, COST-006): any cgroup data → Elastic Cloud / ECE / ECK, or a cgroup CPU quota or memory limit (cgroup stats exist on any Linux host)
- Rolled JSON logs (`*.json.gz`) are read, and a `.gz` log is read from its end instead of its start
- `max_merged_segment` default: data stream membership → an indexed `@timestamp` date field in the mapping (how Elasticsearch picks the time-based merge policy); `segments_per_tier` and `max_merge_at_once` note that the time-based policy ignores them

### Fixed: findings

- CLU-001: red with no unassigned primary now says primaries are initializing
- CLU-002: a shard with a state other than UNASSIGNED is not counted because of a leftover unassigned reason
- CLU-006: a cluster whose only electable master is one node next to voting-only nodes → Critical. CLU-007 does not count voting-only nodes as dedicated masters
- CLU-011: the flood stage text points to the index-level block it sets
- CLU-018: node count per zone is compared within each data tier; awareness is also read from elasticsearch.yml (CLU-019)
- OVS-001: recommended primaries = the smallest factor of the current count that keeps shards at or under 50GB (shrink only goes to a factor)
- OVS-002: a stream whose rollover has a size condition (or data stream lifecycle) only receives little data → Info; age-only rollover stays Warning
- OS-001: high load with low CPU on Linux also points to disk wait; OS-004 basis → tool threshold
- BRK-002: the usage line is a threshold (70%). With real memory accounting (the default) the parent breaker estimate is the whole heap, young generation garbage included, and ES forces a young GC before it trips (G1OverLimitStrategy), so its usage at one moment is no longer rated; JVM-001 rates old generation pressure. Parent trips (BRK-001) are still reported, and are Critical only when the node's JVM memory pressure is high
- IP-001: -1 (counter not reported) is ignored
- PERF-012: merge time minus throttled and stopped time
- DISK-001: a dedicated frozen node above `flood_stage.frozen` → Info only. Frozen nodes cache data that lives in the snapshot repository, so a full disk is expected. The same applies to its log line (LOG-001) and to a non-green health disk indicator caused only by such a node (CLU-004)
- SYS-001: Info when every node sets `node.store.allow_mmap: false` (the check is skipped). SYS-004 counts victim lines only
- SHD-001: frozen-only nodes are not rated. SHD-003 allows the rollover overshoot past 50GB. SHD-005 leaves out partial mounts. SHD-006 needs a minimum difference (`shard_balance_min_diff`) and is Info from 8.6
- IDX-001: Info with a single data node. IDX-005: Info unless the same index also had indexing throttled. IDX-006: Warning only for failures other than version conflicts, or query failures of 1% or more of an index's queries (at least 10); the failure ratio uses the primaries' index_total (index_failed is counted on the primary only), and the text no longer says mapping errors are counted (they are returned before the engine runs). IDX-009: the generic data role covers frozen. IDX-012: Critical only for corruption signs. IDX-014: both causes of indexing throttling are named. IDX-015: unknown version uses the 10GB default
- PERF-003: only the request cache is rated
- SHD-008/013 and the rollover hint: the implicit 200M document rollover applies from 8.8. ILM-007 is not raised before 8.8
- SHD-009 and the master heap estimate leave out voting-only nodes. SHD-012 skips rolled-over indices, searchable snapshots and one-primary indices (two copies of a shard never share a node). SHD-014 covers logsdb_columnar
- PERF-004: a write index with no recent write load is left out. PERF-007: node count of the index's own tier
- CFG-002: path prefixes match on "/" boundaries. CFG-007: the last heap dump flag wins
- DISK-006: searchable snapshots and indices without stored _source (synthetic, time_series) are skipped
- VEC-002/005: not rated below 8.12, and fields with `index: false` (or no index parameter below 8.11) are skipped; VEC-005 uses the index creation version. VEC-003: from 9.2 only templates that turn `exclude_source_vectors` off; before 9.2, templates whose `_source.excludes` miss the vector fields
- MAP-004: rolled-over indices are skipped; runtime fields count only from 8.5. Multi-fields of multi-fields are counted
- SHUT-001: a completed RESTART record is not a Warning
- FRZ-001: evictions per day against the region count. FRZ-002: Direct buffer OOM lines are tied to the flagged node
- ING-002 skips `pipeline:` keys. CLU-024 takes count and time from the same node. ILM-008 matches tiers by role
- OPS-004 compares storage and memory separately. OPS-005 reads the manually stopped flag
- SNP-002 without times stays Warning. SNP-005 → Info (lifetime counter)
- ILM-002: a rollover error on an index that is already rolled over → Warning. ILM-003 skips indices managed by data stream lifecycle
- SEC-002 reads the HTTP bind address (`http.host` before `network.host`). OPS-002: only current read or fatal errors → Warning
- OPS-007: legacy collection also read from elasticsearch.yml; deprecated since 7.16, with removal in 10.0 announced in 9.5
- HOT-003: Info while shards relocate. HOT-004: `computation_active`. HOT-005 and COST-006 use the container guard. TPL-001 counts distinct templates. REC-001: 0 or less is unlimited
- COST-004 no longer counts shrink and downsample copies as new ingest (placed by their name date, see the final review); data stream lifecycle retention counts as draining
- Logs: `[gc][old]` and GC overhead patterns; low watermark log lines → Warning, high and flood → Critical; master not discovered → Warning; hot threads classify global ordinals building and skip Lucene frames on search threads
- SET-001/006: a unitless 0 or -1 is compared as the same kind; `default` equals `default(LZ4)`; `node.processors` is compared with the available processors

### Fixed: second review on a real Elastic Cloud bundle

Every finding was recomputed from the raw files of a 14-node Elastic Cloud 9.5.3 bundle and compared with the Elasticsearch 9.5 source.

- JVM-001: heap% at one moment (young generation garbage included) → JVM memory pressure, old generation used / max, as the official high JVM memory pressure guide defines it; 75% and 85% are now official thresholds. A frozen node at 87% heap but 58% old generation was Critical
- DISK-008: Linux prints io_ticks as a 32-bit millisecond counter that wraps every 49.7 days, so ES reported a negative value and a hot node at 96.6% was "cannot be determined". The wrap is corrected. On Elastic Cloud / ECE / ECK the text says the device can be shared by other instances on the host, and that high utilization on NVMe does not always mean saturation
- OS-001: inside a container the load average is the host's (nodes on one host report the same load), so a container node is rated on load only when its own CPU is at least 50%. OS-003 on Elastic Cloud: the advice is instance size or less CPU work, not the container limit. OS-005 is no longer raised on Elastic Cloud / ECE / ECK (platform-managed, swap off)
- IDX-004: time-based indices use LogByteSizeMergePolicy (merge factor 32), which keeps up to 31 segments per size level by design; their line is (merge factor - 1) x levels. 52 data stream indices were false positives
- SHD-012: a plain index taking writes directly had dropped out (0.14.3 regression), and one-primary indices were listed although the setting cannot change their placement. An index is listed only when it takes writes now (recent_write_load, or a write target, or indexing at collection), since index_total is cumulative
- OVS-001: an index behind a plain read alias was skipped as a write index (0.14.3 regression); empty indices are left to SHD-011. Only data stream write indices, alias members flagged is_write_index, and the only member of a legacy ILM rollover alias without the flag count as still being filled
- VEC-003: not raised at all below 8.12 (0.14.3 regression). Templates with synthetic or disabled _source are skipped, and _source.excludes patterns are matched as wildcards
- SET-001/002/006: searchable snapshot mounts (their settings are set by the mount) and the merge settings data stream lifecycle writes are no longer listed; three operator settings were added to the knowledge base (99 settings in the knowledge base); a unitless 0 or -1 on a rate or a timeout is a change, not "lowered"; the dedicated-rule marker reads "rated by"
- CLU-011 also rates a risky value set in elasticsearch.yml (`action.destructive_requires_name: false` was rated nowhere). CLU-013 ignores the Elastic Cloud transient placeholder
- DISK-007: logsdb, time_series and the columnar modes default to synthetic _source (from 8.17), so 2,185 indices instead of 170
- SHD-005 shows the real shard total (partial mounts were subtracted from the displayed count). SHD-004 does not count current write indices as small. SHD-013 is a Warning only when the latest finished generation ended late
- SHD-014 skips searchable snapshot mounts and indices whose policy already caps shards at 30GB; SHD-015 skips indices ended by a max_primary_shard_size of 10GB or more; the rollover trigger names a size condition only within 90-120% of it
- ILM-004 also lists a policy without rollover used by a data stream (the write index can never be deleted, the root cause of an ILM-002 delete error); the ILM-002 text says so. A "rollover alias does not point to index" error is a Warning
- Data streams Elasticsearch manages for itself (hidden, `_meta.managed` without a Fleet package, such as ilm-history-7) are system data
- MAP-003 skips Elasticsearch-managed templates and templates that match nothing. OPS-001 is not raised while databases are present, none has expired and downloads have succeeded (the counters are cumulative). TP-002 includes the merge pool. FRZ-001 Info text is neutral. RT-001 classifies ingest processor frames (json) as ingest pipeline. PERF-004 reads the right indexing buffer field (ES swaps the two)
- COST-004 counts data that ILM has already mounted to cold or frozen inside the window, and the share of older indices that rolled over inside it (115 → 152GB per day on the bundle); failure stores count under their data stream. COST-005 shows the snapshot data of partial mounts. COST-006 counts high memory pressure. COST-001 advice covers hot-only managed policies
- Bottleneck: when only write_coordination waits, CPU and the ingest pipeline are checked first (it was storage); capacity also reads DISK-004 and memory pressure
- LOG-001: the frozen flood stage log line (no block) is Info. LOG-000 on Elastic Cloud points to the deployment logs. SHD-009 and CLU-015 no longer suggest the removed freeze API. SNP-005 reads as history
- Comparison mode: a restart is also detected when uptime grew less than the interval. CLU-001 does not claim primaries are initializing without a shard list. `explicitly_set` ignores nested yml child keys. `rolled_over` is no longer quadratic on clusters with many aliases. FRZ-002 ties a Direct buffer OOM to the node of its log event

### Fixed: comparison mode

- The comparison base was the newest baseline even when it was collected after the analyzed bundle → the latest earlier one; when every baseline is later, the run stops with a message
- DIF-005/006/007: a node that restarted counts from 0 over its uptime (its rejections, GC and trips are new) instead of being skipped or read as past history
- DIF-013: two different clusters → only DIF-013 is reported. A `_na_` cluster_uuid is ignored
- DIF-001: an unknown status is not a change
- DIF-008: growth is the change in used bytes (a resized disk is not growth); a tier whose nodes changed is listed but not rated
- DIF-009: a tier below `workload_skew_min_per_sec` is not rated for skew
- DIF-012: a finding whose rule did not run on the current bundle is not "resolved"
- A failing trend rule is recorded as a rule error instead of being dropped
- DIF-014 sorts all bundles together

### Fixed: final per-rule review

Every finding ID was reviewed again, one rule at a time, against the Elasticsearch source of the matching versions, Lucene, the support-diagnostics layout and the official docs. A separate review then checked the changes themselves.

- Shared parsing: a setting rendered as a dotted key inside its parent map (`watermark.low.max_headroom` next to `watermark.low`) was not found, so a yml max_headroom was ignored; byte values with one-letter units (`500m`, `1g`) were not read; a cat table row with spaces in the last column split a number in two. The ILM policy of an index that data stream lifecycle manages (ILM explain `managed: false`) is no longer used
- Settings knowledge base (100 settings in the knowledge base): `thread_pool.search.queue_size` was always "changed" and Warning → its default is search threads x 1000 from 9.0 and 1000 before; a watermark written as a ratio (`0.85`) equals 85%, and an absolute watermark against a percentage default has no direction (Info); `auto_expand_replicas` text depends on the range; SET-003 compares lists with comma strings; `logger.level` is a static node setting; `use_real_memory` is dynamic from 8.1 (static before); incoming and outgoing recoveries default to `node_concurrent_recoveries`; 7.17 defaults for `destructive_requires_name` and `transport.compress`; ML, http.max_content_length, write pool and synthetic source fallback texts corrected. SET-004/005 are lowered to Info on ECH and ECE only (on ECK the user writes the yml)
- Time-based merge policy: from 8.8, not 8.11; 9.1 and 9.2 require doc values; IDX-004 uses the Lucene LogMergePolicy level span (0.75 above floor_segment, 1.5 below), so a 20GB shard holds about 150 segments by design, and shows the line per index
- CLU: CLU-001 counts only green indicators as OK and names primaries still being created; CLU-006 needs nodes; CLU-015 is skipped when only dedicated frozen data nodes exist; the persistent task test matches the action only
- Nodes: JVM-003 allows 60% for master-only nodes (ES automatic sizing); JVM-005 does not rate nodes up for less than an hour; DISK-002 (high watermark) stays Critical on hot, warm and cold nodes (shards are forced off and indexing can stop soon); a dedicated frozen node over its flood stage is Info only (cache); disk usage per data path as ES does (least available for flood and high, most available for low); with `threshold_enabled: false` the texts say nothing is enforced; OS-003 is Critical only when the CPU is busy at collection; OS-006 names its nodes; IP-001 counts coordinating, primary and replica rejections only (also in COST-006 and the bottleneck)
- Syscalls and logs: SYS-004 reported OK when dmesg could not be read → Info; a killed java that is not tied to Elasticsearch is a Warning; vm.max_map_count recommendation dated 8.16. LOG-001: indexing pressure, native thread OOM, long young GC and DocumentParsingException have their own patterns; a logged breaker trip is a Warning; docker container logs are read; LOG-000 quotes the marker that matched and gives remote mode advice. RT-001 recognizes stored field compression
- Shards: SHD-004 evidence groups small primaries by data stream with mounts counted, and skips unassigned primaries; IDX-002 is not rated without node information; IDX-001 treats `0-0` as no replicas; PERF-003 needs 10000 request cache lookups and its text names LRU eviction (requests using `now` are never cached); PERF-001 is the per-shard query phase time; IDX-006 before 8.18 cannot tell version conflicts apart and is not rated on index_failed alone; IDX-015 applies the 1% of disk cap (8.8+) and counts assigned copies; MAP-001/004 apply the logsdb default of `ignore_dynamic_beyond_limit` and treat integration package limits as product-set; IDX-008 is Critical only for explicit write targets, an unflagged single-member alias goes to IDX-011; OVS-002 counts doc-count rollover conditions and data stream lifecycle, and shows unknown or no-rollover cases as Info; OVS-003 includes fully mounted indices
- Guidance: CFG-008 accepts JDK 8 `-Xloggc`; CFG-004 skips nodes without settings and reads `discovery.zen.hosts_provider`; CFG-006 uses the bound addresses and `es.enforce.bootstrap.checks`, with its own single-node advice; CFG-002 reads Windows paths and the default `path.data`; CFG-001 is case-sensitive; SHD-008 before 8.8 gives the right rollover advice; SHD-011 skips mounts and is version aware; PERF-004 counts shards with real write load; VEC-001 handles DiskBBQ and only the nodes holding vector shards; VEC-004 uses the effective max_merged_segment; PERF-006 is skipped without cluster settings; PERF-009 and FRZ-002 share one network filesystem list
- Hot spots and cost: HOT-001 compares JVM memory pressure, not heap%; HOT-002 needs a minimum rate; HOT-005 names load without CPU (often disk wait); CLU-021 reads any zero time value; TPL-001 tests real pattern intersection; COST-002 skips auto-expanded indices; COST-004 places shrink and downsample copies by their name date, counts data as draining only when the cluster already holds data older than the move or delete delay (a young cluster with a long retention keeps growing), and uses explicit write targets
- Operations: SNP-001 is skipped when repositories.json is an error body; SNP-003 is Critical when no snapshot ever succeeded, decided on states; SNP-007 is a Warning until 5 failures in a row or an old last success; SNP-006 needs an SLM policy; LIC-001: a trial is a Warning, the expiry impact text is accurate, the basic license text reads well; SEC-001 rates CA certificates in a trust store as Warning and notes platform managed certificates; SEC-002 stays Critical unless both HTTP and transport are loopback; ILM-002 also sees the failure store write index; ML-001 notes when only 100 transforms were collected; OPS-007 text fits a dedicated monitoring cluster
- Deep checks: MAP-006 shows the configured percentage; ILM-004 says when a delete removes the whole data stream and leaves out streams that data stream lifecycle manages; ILM-008 uses only indices that run the policy; DISK-008 does not rate an ambiguous value after 49.7 days; PERF-011 does not raise a Warning on runtime_mappings alone; IDX-012 without a corruption sign has its own title; OPS-003 shows skip_unavailable; ING-002 reads the processor type of 8.0 conditional processors and explains async processors; OPS-004 includes tiers with no node yet; CLU-023 skips nodes without plugin information; OPS-005 reads the .watches index; OPS-006 is version aware
- Comparison and reports: DIF-011 lists a searchable snapshot mount as moved; DIF-004/005/006/007 count a node that joined inside the interval from 0; DIF-001 uses the CLU-001 severity of the current status and does not call yellow "resolved"; DIF-002 restart is a Warning (Info on a version change); DIF-007 is Critical from `breaker_delta_crit`; DIF-012 ignores rules that did not run or failed on either bundle; DIF-014 divides by the nodes that did the work; the summary shows "-" for missing values; per-hour rates keep a decimal. Bottleneck: cumulative rejections that did not increase are history, a breaker trip history is not memory pressure, the queue names its pool. HTML node colors follow the rules. DIF-008 puts the tier totals first; markdown notes cut rows; evidence file paths include `commercial/`

### Changed

- Bottleneck summary: a symptom on a coordinating-only node widens the scope to every data node
- Basis relabeled to tool threshold where the deciding number is the tool's: HOT-001, CLU-015, SHD-010, SHD-012, SHD-015, PERF-004, PERF-008, VEC-004, OS-004, and in the final review SEC-001, SHD-007, SHD-011, DISK-006; JVM-001 to official
- New thresholds: `breaker_used_pct_warn` 70, `shard_balance_min_diff` 10, `frozen_cache_turnover_per_day` 1.0, `workload_skew_min_per_sec` 10, `query_failure_pct_warn` 1, `breaker_delta_crit` 10 (147 thresholds). `load_host_cpu_pct_max` 20 → 50
- `ml_stats.json` moves from the unused to the used files in COVERAGE
- `tests/test_audit_0143.py`, `tests/test_audit_final.py`

## [0.14.2] - 2026-10-03

The defaults of all 92 settings in the knowledge base (the 4 prefix rules have no single default) were compared in the Elasticsearch source of 8.0, 8.19, 9.0 and 9.5, so that settings findings use the default of the cluster's own version. Two more defaults depend on the version or the index mode; the rest are the same from 8.0 to 9.5, or were already computed per version.

### Changed

- `cluster.routing.allocation.allow_rebalance`: always "always" → "always" from 8.16 with the desired_balance allocator, "indices_all_active" before 8.16 or when a node sets `cluster.routing.allocation.type: balanced`. SET-001 compares against the right one
- `index.queries.cache.enabled`: always "true" → "false" for the columnar and logsdb_columnar modes (9.5), "true" otherwise

### Checked, no change needed

- Already computed per version: merge policy (9.5), `index.mapping.nested_fields.limit` (9.3), `thread_pool.write.queue_size` (9.2), `index.codec` (index mode), `indices.breaker.total.limit`, `indices.recovery.max_bytes_per_sec`
- Only differs on serverless (stateless) nodes, not on the clusters this tool reads: `index.refresh_interval`, `index.unassigned.node_left.delayed_timeout`
- Same default in all four versions: the other settings, including disk watermarks, shard limits, balance factors, thread pool sizes, search and HTTP limits, translog, ILM and SLM

## [0.14.1] - 2026-10-03

The baseline moves to Elasticsearch 9.5. The 9.5 release notes, breaking changes and deprecations were checked against every finding, and the Elasticsearch 9.5 source where the docs give no value. 96 settings in the knowledge base.

### Changed

- Baseline: Elasticsearch 9.4 → 9.5. A 9.5 cluster no longer raises VER-001
- Merge policy defaults by version (Elasticsearch source, MergePolicyConfig): `segments_per_tier` 10 → 8, `floor_segment` 2mb → 16mb and `max_merge_at_once` 10 → 16 from 9.5. `max_merged_segment` was always 5gb → 100gb for data stream indices from 8.11 (time-based merge policy), 5gb otherwise. SET-006 compares against the default of the cluster version. `floor_segment` and `max_merge_at_once` were added to the knowledge base
- DISK-006: only logsdb was skipped → the columnar and logsdb_columnar modes (9.5, tech preview) default to best_compression too and are skipped. SET-006 treats best_compression on these modes as the default
- DISK-007: `index.mapping.source.mode: columnar_stored` (columnar modes) is listed with synthetic, as the returned _source is rebuilt
- IDX-013: data streams in columnar or logsdb_columnar mode are not told to move to logsdb
- PERF-008: the vectordb_document mode (9.5) sets `index.store.preload` for its vector files on its own; that exact value is no longer listed
- OPS-007: with legacy internal collection on 9.5 or later, the finding adds that collecting with the monitoring plugin is deprecated and is removed in 10.0 (official deprecations)
- Knowledge base: `index.codec` no longer says time_series defaults to best_compression (only logsdb and the columnar modes do)
- `tests/test_es95.py`

### Checked, no change needed

- 9.5 breaking changes (CCS exclusion order, ES|QL FUSE, TSDB look-ahead window) and 9.5.1 (ILM allocate removes auto_expand_replicas) do not touch any finding
- New 9.5 defaults with no finding behind them: batched query phase, ES95 TSDB doc values codec, adaptive replica selection, OTLP logs and traces

## [0.14.0] - 2026-10-02

A bottleneck summary at the top of every report, recently restarted nodes left out of node comparisons, frozen shared cache on network storage, storage cost and sizing findings, throughput per interval across several bundles, a per node comparison table, a text filter in the HTML report, and fixes from a full check against the official docs. Every threshold without an official number is marked `[Tool]` and can be changed with `--thresholds`.

### Renamed

- The package `esdiag` is now `esdoctor` (esdiag is the name of an official Elastic tool). The package folder is `esdoctor/`, the single-file build is `dist/esdoctor.pyz`, the standalone build is `dist/esdoctor`, and the language variable is `ESDOCTOR_LANG`. `python3 analyze.py` works as before

### Added

- Bottleneck summary in every output (HTML, Markdown, console, JSON `bottleneck`, Support summary): five questions (is ingest keeping up, is search slow, is storage the limit, do restarts or recoveries skew the numbers, capacity or concentration). Each looks at symptoms first (rejections, queues, throttling, latency) and names a cause only when a symptom exists, by walking cause groups in a fixed order over the findings in the report. The order is the tool's judgment, not an official decision tree. It is left out when `--only` runs part of the rules
- FRZ-002 (Warning, tool threshold): a node with a frozen shared cache whose data path is on a network filesystem (nfs, cifs, smb, fuse, glusterfs, ceph). Nodes with a shared cache can only have a single data path, so the cache file is on that filesystem. The table shows hot threads reading the cache file and the search queue and rejections. "Direct buffer memory" errors in the server logs → Critical
- PERF-013 (tool threshold): search thread pool busy (active >= 80% of the pool size) while node CPU is under 50% at collection. Queued searches → Warning, otherwise Info
- COST-001 (Info): rolled-over indices still in the ILM hot phase 30 days or more after rollover, grouped by policy with the next phase and its min_age. Only when a warm, cold or frozen tier exists
- COST-002 (Info): indices with 2 or more replicas and no searches since the shards started, with the space freed at 1 replica. Not listed when the data nodes span replicas + 1 availability zones
- COST-003 (Info): disk use between tiers. Hot at 70% or more with a warm or cold tier 30 points emptier, or a warm or cold tier under 20%. Frozen is shown but not compared
- COST-004 (Info, Warning): days of ingest the landing tier can take before the high watermark, from one bundle. Daily ingest comes from indices created in the last 7 days. Warning at 30 days or less when more than half of that data has no ILM phase after hot
- COST-005 (Info, reported fact): storage by data type and tier. Types follow the official data stream naming scheme (logs, metrics, traces, synthetics), plus security alerts, system, other data streams and other indices. Partial mounts are a separate row because their store size is only the cache
- COST-006 (Info): sizing signals per tier from one bundle. "Pressure" when every node is busy, rejections occur, indexing pressure rejects or a node reaches the high watermark. "Large headroom" only when every node has been up for 24 hours and CPU, load, heap and disk are all low with no rejections. One bundle is one moment, so large headroom means "check with monitoring", not "shrink now"
- DIF-014 (Info): with three or more bundles (`--baseline` repeated), throughput per interval: indexing and search per second, per data node, the peak and lowest interval and their ratio. Nodes restarted in an interval are left out of it
- Comparison mode: a before/now table per node (uptime, heap, CPU, load15, disk, shards, indexing and search rate, rejections, old GC). Changes under 5% show as "="
- `--baseline` can be repeated. Bundles are ordered by collection time; the latest one is the comparison base
- HTML report: a text box next to the filters narrows findings, and the rows of their evidence tables, to an index, node or tier name
- 5 thresholds: `node_change_noise_pct`, `size_idle_cpu_pct`, `size_idle_load_per_cpu`, `size_idle_heap_pct`, `size_idle_disk_pct`
- New category "Storage cost" in the Capacity area, and module `cost` for `--only`
- `tests/test_bottleneck_cost.py`, and 7 scenarios in `tests/drive_branches.py`
- 10 thresholds: `node_compare_min_uptime_hours`, `search_pool_busy_share`, `search_io_cpu_pct_max`, `ingest_fail_ratio_warn`, `hot_rolled_days_info`, `cost_replicas_min`, `tier_hot_used_pct`, `tier_gap_pct`, `tier_idle_used_pct`, `ingest_window_days`

### Changed

- HOT-001: a node restarted moments ago looked idle and created a heap or CPU gap → nodes up for less than 24 hours are left out of the heap and CPU comparison and named in the finding. Disk use does not reset on restart, so it is still compared
- HOT-002: compared cumulative totals, which favor nodes that have run longer → compares the hourly rate and leaves out nodes up for less than 24 hours
- PERF-012: an indexing node was picked by its cumulative index_total, so a recently restarted writer was skipped → picked by hourly rate
- DIF-009: every node was in one average (dedicated masters pulled it down) → data nodes only, skew per tier, and nodes that restarted between the bundles are shown but left out of the totals
- ING-001: any failure was a Warning → failures are summed per pipeline across nodes with a failure ratio. 1% or more → Warning, otherwise Info. The basis is now a tool threshold
- Console: column alignment counts Hangul as two columns
- 122 single-bundle rules and 11 bundle-comparison rules (184 finding IDs plus comparison DIF-001~014)

### Review against a real bundle

A 14-node hot/warm/cold/frozen cluster was analyzed with this version, alone and as a series of bundles. These results were wrong or misleading and are fixed:

- Bottleneck summary: any Critical or Warning in a cause group counted, so high heap on a frozen node or a breaker on a warm node was named as a cause of a write queue on a hot node → when the symptom is on certain nodes, a cause that names nodes counts only if it names one of those nodes or another node of the same data tier (a bulk write waits for the replicas, a search for every shard copy). Findings that name no node still count. BRK-001, BRK-002, OS-003, DISK-008, FD-001, IP-001, HOT-005 and PERF-009 now record the nodes they are about
- PERF-013: two of two search threads busy on a 1-core frozen node was enough → on frozen-only nodes it needs searches waiting in the queue as well, because frozen searches read from the snapshot repository by design
- DIF-008: each node was extrapolated alone, so a warm node that received ILM moves for 17 hours read as "full in 3.7 days" (Critical) while another node of the tier shrank → the tier total decides (bytes left before the high watermark over the tier / growth per hour of the tier). Node rows stay, with a total row per tier
- DIF-014: an interval where only 1 of 10 data nodes matched by name produced the "lowest" rate → an interval between different clusters, or where fewer than half of the data nodes match, is shown as not rated and left out of the peak and lowest
- SET-005: node.processors differed between tiers (4, 2, 1 core) and raised a Warning → data nodes are compared within their tier only
- COST-004: a write target on a warm node made warm part of the landing tier and doubled the headroom → when a hot tier receives writes, only hot tiers count (new data stream indices go to hot by default)
- Change per node table: "1% → 1% ▼" when the rounded values were equal, and shard counts as "0.00" → equal display shows "=", shard counts are integers, ML nodes show "ml"

### Official documentation audit

Every finding labeled Official, every version gate and the defaults in the settings knowledge base were checked again against the current docs (9.x), and against the Elasticsearch source where the docs are silent or disagree between versions.

- CLU-013: transient settings were called "deprecated since 7.16" → "no longer recommended since 7.16" (the 7.16 migration guide says they are not deprecated)
- JVM-002: 32GiB was labeled the official boundary → the flag the JVM reports (`using_compressed_ordinary_object_pointers`) decides: false → Warning, true → no finding at any size. Only without the flag: 30GB or more → Warning, 26GB or more → Info (the docs: 26GB is safe on most systems, up to about 30GB)
- DISK-006: time_series was skipped as "best_compression by default" → only logsdb defaults to best_compression (Elasticsearch source, IndexMode), so time_series indices are checked too
- DISK-007: only `index.mapping.source.mode` was read → the documented mapping parameter `"_source": {"enabled": false}` is found in mapping.json as well. `stored` (the default) is no longer listed
- IDX-013: shows `cluster.logsdb.enabled` and `logsdb.prior_logs_usage`. On a cluster with logs data from before 9.0, `cluster.logsdb.enabled` defaults to false and even new logs-*-* indices stay standard. The recommendation now offers turning it on, and says that without the required subscription logsdb keeps the original _source
- CLU-015: shards of closed indices were counted → the official count covers open indices only (closed indices come from cat indices). Frozen shards are now told apart by index type (partial mount) instead of by node. The Critical line (95%) is a labeled tool threshold
- CLU-007: dedicated masters were expected from 6 data nodes → from 10 data nodes (`dedicated_master_data_nodes`, field guideline). The docs only say "more than a handful"
- SHD-010: Warning at 50% of the heap → Warning when the estimate is larger than the heap (the official check), Info from 50% (tool threshold)
- MAP-006: the default nested limit was 50 → 100 for indices created on 9.3 or later, 50 before (by index version). The 80% line is a labeled tool threshold
- Disk watermarks: the default max_headroom (200/150/100GB) from the defaults section was used as is → it applies only from 8.5 and only while the watermark itself is not set explicitly (official)
- SYS-001, SYS-003: when every node runs in development mode (loopback transport or single-node discovery), bootstrap checks are not enforced, so Critical drops to Warning
- HOT-001: write and search queues are shown, as the docs use them as a hot spot indicator
- CLU-019: basis changed from Official to Tool threshold (awareness is an option in the docs, not a requirement)
- Settings knowledge base: `transport.compress` is static and node scoped. Defaults that depend on the context are computed: `thread_pool.write.queue_size` max(10000, processors x 750) from 9.2, `index.mapping.nested_fields.limit` by index version, `indices.breaker.total.limit` 70% when use_real_memory is false, `indices.recovery.max_bytes_per_sec` by role and memory on dedicated cold/frozen nodes. Defaults found only in the source are labeled (`search.low_level_cancellation`, merge policy, `index.max_refresh_listeners`, `bootstrap.memory_lock`). `xpack.monitoring.collection.enabled` is marked deprecated. 23 settings point to the page that documents them
- Reference links: JVM findings point to JVM settings; GEN-001 to index modules and pagination; IDX-007, CFG-006, TPL-001 and CLU-021 gained references
- Wording: VEC-002 (float vectors only; bbq_hnsw from 9.1, bbq_disk from 9.4 with a license), SHD-001 (the 8.3 boundary comes from the Elastic blog), SHD-011 (ILM does not roll over empty indices by default), SYS-001 (1048576 recommended since the 8.15 to 8.17 docs), PERF-004 (the 5 minute inactive time is from the source), CLU-021 (0 is valid when a node will not return)
- `tests/test_doc_audit.py` and 3 more `tests/drive_branches.py` scenarios. 4 thresholds: `dedicated_master_data_nodes`, `heap_oops_safe_bytes`, `max_shards_per_node_crit_pct`, `nested_fields_near_limit_pct`

### Reviewed but not added

- Thread wait time in hot threads ("other") as an I/O signal: it also includes waiting on locks
- Load average above the core count as I/O wait: inside a container the load can be the host's (see OS-001)

## [0.13.0] - 2026-10-02

Write path and operations checks that were missing, found by comparing with the decision logic of another diagnostics tool. Every threshold without an official number is marked `[Tool]` and can be changed with `--thresholds`.

### Added

- PERF-012 (tool threshold): average flush, refresh and merge time per node. flush 800ms / 1200ms, refresh 40ms / 70ms, merge 20s / 40s → Info / Warning. Frozen-only nodes and metrics with few operations are skipped
- SHD-016 (Warning, tool threshold): write-target shards (write indices, alias write indices, indices indexing at collection time) concentrated on some nodes of a tier. (max - min) / average >= 0.5 and a difference of 3 or more. SHD-006 compares all shards
- IDX-014 (reported fact): indexing throttled because merges fell behind. `is_throttled=true` at collection time → Warning, cumulative throttle time only → Info
- IDX-015 (Warning, official): uncommitted translog per shard copy at or above `index.translog.flush_threshold_size` (10GB on 8.8+, 512MB before). A fixed 1GB threshold is not used because it is a false positive when the default is 10GB
- OS-007 (Warning, tool threshold): half or more of the nodes restarted within 6 hours. Flags that findings based on cumulative counters cover only a short window
- DIF-013 (Warning): in comparison mode, the two bundles look like different clusters (cluster_uuid differs, or without a uuid the names differ and fewer than half of the nodes overlap)
- `tests/test_write_path.py`: every branch of the new findings on synthetic data, in both languages (no external bundle needed)
- 16 thresholds

### Changed

- CLU-017: every task over 5 minutes was a Warning → grouped by action with the task count and the longest run. 1 hour or more → Warning, 5 minutes or more → Info. Monitoring and internal tasks (`cluster:monitor/*`, `indices:monitor/*`, `internal:*`) are reported only past 24 hours. Write-path actions (bulk, reindex, update/delete by query, forcemerge, shrink/split/clone) are marked. Also fixes sorting by running time, which sorted as text
- MAP-004: indices without ignore_dynamic_beyond_limit, which can fail indexing, are listed first (at equal usage, integration indices used to fill the 15 rows and hide them), and a column shows who manages the data stream template (`fleet:<package>` / `elastic`)
- False positives found on a real 14-node 9.5.3 bundle
  - PERF-012: warm nodes without write targets showed 26 to 41 s average merges as a Warning → only nodes that actually index are rated (node index_total at least 10% of the busiest node). The first version used "holds a data stream write index", but warm nodes in this bundle held write indices with almost no writes since January (`logs-gitlab.audit`, `logs-gitlab.pages`), so it now uses the actual indexing volume. Merges on a node without writes come from a force merge (ILM forcemerge, the force merge that searchable_snapshot in cold or frozen runs in the preceding tier by default, or a manual _forcemerge) or from merges finishing after rollover. They merge large segments, so a long average is not a sign of slow storage. A warm tier does not force merge on its own
  - OS-001: container nodes with 0% CPU but a high load average (such as ECH master nodes) were Critical → the load inside a container can be the host's, so nodes under 20% CPU are listed as Info only
  - MAP-001, MAP-004: read-only searchable snapshot mounts filled the top of the table → skipped
  - PERF-001: partially mounted (frozen) indices, which read from the snapshot repository, were rated for search latency → skipped (FRZ-001 covers them)
  - IDX-006: failure ratio column added and rows sorted by it
  - SHD-016: write indices with indexing.index_total of 0 (idle for a long time) are left out
- 114 single-bundle rules and 10 bundle-comparison rules (176 finding IDs plus comparison DIF-001~013)

### Reviewed but not added

- Disk read/write latency (ms/op): `fs.io_stats` in nodes stats has operation counts and `io_time_in_millis` only, with no read or write time fields (checked in the Elasticsearch `FsInfo` source)
- OS memory use of 95% or more: Elasticsearch nodes normally use almost all memory for the filesystem cache, so it would always fire
- Any old GC, heap over 32GB as an estimate, load1m: already rated more precisely with the hourly ratio (JVM-005), the actual compressed oops flag (JVM-002 to 004) and load15 (OS-001)
- Enterprise ERU usage: to be decided after checking the formula against the official docs

## [0.12.0] - 2026-10-02

### Added

- SHD-013 (Warning, tool threshold): a shard of a rolled-over index more than 5% above 200M documents is reported as a late rollover. The recommendation lists the likely causes (ILM stopped or failing, poll_interval, `min_*` conditions, no lifecycle attached)
- SHD-014 (Info, tool threshold): the largest primary shard of a logsdb index is 30GB or more and under 50GB. The table shows, per index, the data stream, largest shard size, document count, bytes per document, estimated rollover condition and ILM policy. 30GB is not an official number; it follows an Elastic internal discussion, and the finding states the reasons (implicit 200M rollover, merge cost of index sorting, free space for force merge, recovery time)
- SHD-015 (Info, official lower bound): a logsdb data stream with 5 or more indices rolled over under 10GB and under 200M documents (ended by max_age or similar). One row per data stream with the count of small rollovers, median size and documents, and the most common rollover condition (a per-index list ran past 1,000 rows on a real bundle). Empty indices are left to SHD-011
- IDX-013 (Info): on 9.0 or later, `logs-*-*` data streams whose write index is not in logsdb mode (streams that existed before an upgrade from 8.x)
- ILM-007 (Info): `max_primary_shard_docs` above 200M (no effect)
- ILM-008 (Warning): free disk on the tier that runs a one-segment force merge (forcemerge `max_num_segments=1`, searchable_snapshot `force_merge_index`) is under 3 times the largest primary shard
- ILM-009 (Info, tool threshold): indices in force merge for 24 hours or more, with the force_merge thread pool size and queue
- 7 thresholds: `docs_rollover_overshoot_pct`, `logsdb_shard_gb_high`, `logsdb_shard_gb_low`, `logsdb_rows_max`, `ilm_implicit_max_shard_docs`, `forcemerge_free_space_factor`, `forcemerge_stuck_hours`
- Index mode detection: `index.mode` from `settings.json`, else `index_mode` from `data_stream.json`
- `tests/test_logsdb.py`: every branch of the new findings on synthetic data, in both languages (no external bundle needed)

### Changed

- SHD-008: every shard at 200M documents or more was a Warning → only write indices and indices without rollover. A rolled-over index within 5% of 200M is not reported (rollover always runs at 200M and ILM checks every 10m, so ending a little above is normal; official ILM rollover docs)
- SHD-008 recommendation: "also set max_primary_shard_docs" → explains that rollover runs on its own at 200M under ILM (the limit applies even when not set)
- ILM-004 recommendation: notes that the 200M document condition applies even when not set
- SHD-008: searchable snapshot mounts (restored-, partial-) take no writes, so they are rated like rolled-over indices (SHD-013)
- 110 single-bundle rules and 9 bundle-comparison rules (171 finding IDs plus comparison DIF-001~012)

### Fixed

- `tests/drive_branches.py`: the scenarios assumed the bundle they were built on (3-node ECH, collected 2026-08-14) and 10 to 16 failed on other bundles → the collection date is pinned to 2026-08-14 (the reference for certificate, license and snapshot dates), single-node bundles are cloned to 3 nodes, role scenarios remove the master role from the other nodes, disk scenarios use 100GB disks (so max_headroom does not interfere), added indices go to the first data node, and the shard skew and excess replica scenarios scale to the bundle size. Disk scenarios use non-frozen data nodes and remove custom watermark settings, the shard limit scenario uses 1 shard per node, and SLM scenarios bring their own policy
- DISK-008: when the device counter did not line up with the JVM uptime, average utilization came out negative or above 100% (-131% and -198% on ECH hot and frozen nodes in a real bundle) → shown as "cannot be determined" and not rated

## [0.11.0] - 2026-10-01

### Added

- English support. Console, Markdown, HTML, JSON, and the Support summary now come out in Korean and English. User-facing text moved to the `esdiag/i18n/ko.txt` and `en.txt` catalogs. The catalogs are read with `pkgutil`, so they also work in `esdiag.pyz` and the standalone executable
- `--lang both|ko|en|auto` (default `both`): `both` writes both languages and adds `.ko` / `.en` to the file name (`report.html` → `report.ko.html`, `report.en.html`). `ko` / `en` write one language to the exact name given. The console language comes from the locale or `ESDIAG_LANG`. The bundle is opened once, and the masking map file is written once
- Language-neutral IDs in the JSON: `category_id`, `basis_id`, `grade_id`, and per-area `area_id` / `status_id` / `category_ids`. Process these values, not the report text
- `RULES.md` (English) and `RULES.ko.md` (Korean). Both are generated from the catalogs by `tools/gen_rules_doc.py` (`--lang`, `--check`)
- `README.md`, `COVERAGE.md`, and `CHANGELOG.md` are in English. The Korean versions are `*.ko.md`
- `docs/STYLE.md`: style, glossary, and placeholder rules. `tests/i18n_check.py`: checks that both catalogs have the same keys, and checks `%` fields, HTML tags, dashes, and banned phrases

### Changed

- Code comments, docstrings, tests, and tool scripts are now in English. Korean output is byte-for-byte identical to the previous version (compared on 3 synthetic bundles)
- Finding logic that depended on Korean strings now uses language-neutral IDs (category, grade, area, evidence type)
- The console area table computes column widths in code, so alignment holds when English labels are longer

## [0.10.0] - 2026-09-29

### Added

- `--support-summary FILE`: a summary Markdown to attach to the case when contacting Elastic Support. It is generated only when specified. It contains the observed value, evidence type, evidence file, and evidence table for Critical and Warning findings. It does not contain recommended actions, server log excerpts, or hot threads stacks
- `--mask none|basic|strict` (default basic): replaces identifiers in the summary with aliases (`node-001` and so on). basic covers cluster, node, host, IP, path, certificate, license, and repository. strict adds index, policy, template, and similar names
- `--mask-map FILE`: alias ↔ original name map (permission 0600). The default path is the summary file name + `.mask-map.json`
- If an original identifier or an unregistered IPv4 address remains after masking, the summary and map are not written and the exit code is 2
- `tests/test_handoff.py`: synthetic verification based on canary identifiers (no external bundle needed)

### Changed

- README wording: "Elastic Support" → "Elastic 공식 Support 팀" (the official Elastic Support team, in the Korean README). The format-string check count in the README is corrected to the actual value

## [0.9.3] - 2026-09-29

Reflects findings from the final review (two local bundles, Python 3.8.20 / 3.12, HTML rendering on desktop and mobile).

### Changed

- Action priorities: one line per finding → findings with the same cause are grouped into one representative entry plus related findings (unassigned shards: CLU-001, 002, 003, 004.shards_availability, IDX-002; disk watermark: DISK-001 to 003, CLU-004.disk). Applies to console, Markdown, HTML, and JSON (`priority`). The finding list in the body is unchanged
- Action priority order: within the same severity, category names in Korean alphabetical order → report area order (Availability → Capacity → ... → Configuration)
- SYS-001: OK at 262144 or higher → Critical below 262144 (bootstrap check), Info below 1048576 (official recommendation: if the default is lower than 1048576, set it to 1048576), OK at or above
- CLU-003: the generic guidance text from allocation explain → the target shard and the name of the decider that denied it (for example `test-index[0] replica: can_allocate=no` with decider `same_shard`)
- Collection time: raw ISO string → `2026-09-29 03:34:09 UTC (Korea time 2026-09-29 12:34)`. `collected_at` in the JSON is unchanged, and `collected_display` is added

### Fixed

- Area results: the "OS settings" category (SYS-001 to 004) belonged to no area and was left out of the totals → now included in the Configuration area
- `--no-ok`: OK showed as 0 in the finding counts and area summary → hidden from the display only, still included in the counts
- `--only`: the module list in the help was out of date and missed settings, sharding, deep, and syscalls, and a misspelled name ran no rules → the list is generated from the actual modules, and an invalid name is an error
- Backticks (`) in recommendation text showed literally in the HTML → removed. Official documentation links added to SYS-001 to 003
- CLU-024: an empty value showed as "total state size -." when no value existed → only the values that exist are shown
- Long observed values in action priorities were cut off with no ellipsis → shown with `…`

### Verification

- `tests/test_local_mode.py`: 13 → 18 assertions (SYS-001 recommended-value ranges, `--no-ok` counts, priority grouping)
- Confirmed that Python 3.8.20 and 3.12 give the same findings for both bundles

## [0.9.2] - 2026-09-29

### Added

- 107 single-bundle rules and 9 bundle-comparison rules (164 finding IDs plus comparison DIF-001~012)
- `syscalls/` analysis (local/remote mode): SYS-001 vm.max_map_count (minimum 262144), SYS-002 vm.swappiness when swap exists, SYS-003 ES process nofile 65535 / nproc 4096, SYS-004 kernel OOM killer records in dmesg

### Verification

- Wider validation scope: in addition to api mode, validated on a real local-mode bundle (self-managed 8.19.21, single node). Remote and multi-node local are not validated
- Added `tests/test_local_mode.py`: 13 assertions on local-mode branches using synthetic data, no external bundle needed (confirmed that it fails if the LOG-001 false positive returns)

### Fixed

- LOG-001: JVM option lines in the startup log (such as `-XX:+ExitOnOutOfMemoryError`) were matched as OutOfMemoryError and judged Critical → startup option lines are excluded (a false positive found on a real bundle)
- Log scan: `.log.gz` was read without decompression → decompressed before scanning. `gc.log*` (JVM log) and `*_server.json` (the JSON copy of the same content) are excluded from the scan. The `translog` word match is narrowed to `failed to flush`

## [0.9.1] - 2026-09-29

### Changed

- Deployment type detection: ECK was assumed whenever the `node.store.allow_mmap` setting was present → removed (this setting is common in self-managed clusters too, which wrongly lowered CFG-* and SET-004 to Info)
- CLU-006: 4 or more master-eligible nodes, even count, was a Warning → no finding (official: with an even count, ES excludes one node from the voting configuration and fault tolerance does not drop). 2 nodes: Critical → Warning
- TP-001: 1,000 or more cumulative rejections was Critical → Critical only when the pool still has a queue at collection time, otherwise Warning
- BRK-001: Critical on trip history alone → Critical only when usage at collection time is 70% or higher, otherwise Warning
- SNP-002: Critical if any failed or partial snapshot exists → Warning if a successful snapshot exists after it
- IDX-002: Critical → Warning (the primary is fine and only the replica is unassigned)
- SEC-002: lowered to Warning when every node binds only to loopback
- IDX-005: fixed a recommendation that pointed to the nonexistent `indices.store.throttle` setting
- OS-002: now also reports swap usage
- LOG-000: when a local or remote collection lacks syscalls or logs because the target node did not match, the cause and how to recollect are explained based on `diagnostics.log`
- `RULES.md` generator: fixed empty titles for rules whose title is a conditional expression, the `%%` notation in DISK-008, and threshold comments leaking into the text
- `tests/check_docs.py`: fixed a check that failed on markdown escaping in the README table (`SET-\*`)

## [0.9.0] - 2026-09-22

This is the first public version (0.9.0). Until 1.0, finding criteria and output formats may change. **This tool is validated with api-mode diagnostics bundles. Bundles from local / remote mode (including server logs and OS command output) have a different file layout and may need checking.** Finding criteria follow the official Elasticsearch 9.4 documentation (checked 2026-09).
Real-bundle validation used 9.4.4 (Elastic Cloud Hosted, 3 nodes, single tier). False positives and false negatives were corrected using results from a 9.5.3 multi-tier (hot/warm/cold/frozen) cluster.

### Added

- 106 single-bundle rules and 9 bundle-comparison rules (160 finding IDs plus comparison DIF-001~012)
- Every finding shows its evidence type: Official / Reported fact / Tool threshold / Computed
- Settings change analysis (SET-001 to 006) and 94 settings in the knowledge base (default, dynamic/static, meaning, impact by direction)
- Oversharding analysis (OVS-001 to 003) and tier-wide CPU saturation (HOT-005)
- `--baseline` comparison mode: cumulative counters are judged as increments and hourly rates, with projected disk-full date and finding changes (new/worse/resolved)
- Handling of uncollected input: if a required file is missing, the rule makes no finding and records "cannot be determined"
- Rule isolation: if one rule fails, the other findings and the report still complete. Failed rules are listed under "Items not evaluated because of a tool error"
- Deployment type detection (ECH/ECE/ECK/self-managed): settings managed by the orchestrator are lowered to Info
- Version baseline and VER-001 (notice when a version newer than the baseline is analyzed)
- Single-file distribution `esdiag.pyz`, a build script for the standalone executable, and `--check-env`
- Automatic `RULES.md` generator (extracts conditions, thresholds, inputs, and documentation from the code)
- Verification tools: assertions on calculation logic, driving of finding branches, input mutation fuzzing, static check of format strings, and a full-run script

### Final adjustments for a health-check view

- Added **results by area** at the top of the report: Availability / Capacity / Data structure / Performance / Data protection and operations / Security / Configuration (same in console, Markdown, HTML, and JSON)
- Changed the finding order to health-check priority (Availability → Capacity → Data structure → Performance → Data protection → Security → Configuration). Settings changes, mostly Info, no longer come first
- Added a monitoring setup check (OPS-007): whether monitoring data exists in the cluster, with guidance to check for a separate monitoring cluster
- ILM-002: every ILM error was Critical → only a failure in the rollover step is Critical (the write index keeps growing). Failures in other steps and failures to delete the write index are Warning
- IDX-006: added a note that version conflicts also grow during normal operation

### Wider use of the bundle (zero-base review)

A full comparison against the 104 files in a diagnostics bundle found 53 that were not being read. The files that hold facts relevant to stability are now used, bringing the total to 62.

- `mapping.json`: field count near the limit (MAP-004), fielddata on text fields (MAP-005), nested limit (MAP-006), unquantized vectors in actual indices (VEC-005)
- `ilm_policies.json`: rollover without a size condition (ILM-004, a cause of too many rollovers), rollover condition above 50GB (ILM-005), no delete phase (ILM-006)
- `cluster_state.json`: leftover voting config exclusions (CLU-022)
- `nodes_shutdown_status.json`: stalled shutdowns and leftover records (SHUT-001)
- `shard_stores.json`: store exceptions (IDX-012)
- `remote_cluster_info.json`: disconnected remote clusters (OPS-003)
- `searchable_snapshots_cache_stats.json`: excessive frozen shared cache eviction (FRZ-001)
- `nodes_stats`: script compilation limit tripped (PERF-010), time per ingest processor (ING-002), cluster state publication failures and size (CLU-024), disk I/O utilization (DISK-008)
- `nodes.json`: plugin mismatch between nodes (CLU-023)
- `slm_policies.json`: when `snapshot.json` is a list without timestamps, RPO is calculated from the last SLM success time (previously the RPO finding was missing). Also policies whose last failure is newer than the last success (SNP-007, backups failing now)
- `ml_trained_models_stats.json`, `watcher_stack.json`, `autoscaling_capacity.json`, `rollup_jobs.json`: model deployment problems (ML-003), Watcher stopped manually (OPS-005), autoscaling required capacity (OPS-004), deprecated rollup (OPS-006)

### 9.5.3 bundle validation (second real bundle)

- The file layout is the same as 9.4.4 (104 files). Comparing the field structure of the main files showed that the settings added in 9.5 (ES|QL, telemetry) do not affect findings
- Added a finding for the share of expensive search patterns (PERF-011) using the per-query-type usage counts in `cluster_stats.indices.search`. Corrected the earlier documentation statement "query-related findings are not possible" to "the share by type is judged, but the index cannot be identified"
- hot threads classification now has 2 stages: first look through the whole stack for calls that decide the kind of work (grok, painless, storing ignored fields, and so on), and if none is found, classify from the top frames. Fixed a document-parsing thread whose top frame is a JSON copy being misclassified as "JSON serialization". Parsed frames raised from 12 to 40
- **Memory**: for a large bundle, peak per analysis 3.3GB → about 0.9GB, and 17 seconds → 7 seconds. cluster_state parses only the arrays it needs, mapping is parsed and summarized per index and then discarded, the raw string cache is removed, and number normalization is done in place
- Test fixtures that assumed a 3-node bundle (node reassignment, index settings copy, expected value calculation) no longer depend on the bundle. Both bundles pass all 55 assertions, and the knowledge base defaults also match the values reported by 9.5.3

### Documentation fact correction

- "api mode has no per-index mapping" was wrong. api-mode bundles also contain `mapping.json` (`GET _mapping`), and it is now used for findings.

### Corrected criteria (did not match official documentation or ES behavior)

| Item | Previous | Current | Reason |
| --- | --- | --- | --- |
| Disk watermark | Fixed 85/90/95% | Effective watermark that applies max_headroom (200/150/100GB) | Defaults reported by ES in the bundle, allocation settings documentation |
| Disk on frozen-only nodes | low/high applied → the shared cache pre-allocation (90%) judged Critical | Only `flood_stage.frozen` (95%, headroom 20GB) applies | Frozen tier behavior |
| 20 shards per 1GB of heap | Applied to all versions | Applied only below 8.3 | Officially retired in 8.3 and replaced by a field mapper heap estimate |
| heap/RAM | 55% | 50% (2 percentage points of tolerance) | Important settings |
| Large shard | 60GB | 50GB | Size your shards (10-50GB) |
| refresh_interval | Indices without a value were also judged | Only when 1 second or less is set explicitly | When unset, refresh is skipped while the index is search idle |
| swap | Warning if swap exists | Excluded when memory_lock is applied | Meets one of the 3 swap mitigations |
| GC log | `-Xlog:disable` present → judged off | Whether gc file logging exists after the last disable | Order in which JVM options apply |
| dense_vector quantization | Warning even when index_options is unset | Only when unquantized (hnsw/flat) is set explicitly | Default int8_hnsw in 8.14, bbq_hnsw for 384 dimensions or more in 9.1 |
| codec | All large indices | logsdb and time_series excluded | Those modes default to best_compression |
| allow_rebalance default | indices_all_active | always | Value 9.4.4 reports without a yml (cross-checked) |
| search queue default | Fixed 1000 | Auto-sized (threads × 1000, observed on 9.4.4); only stated facts are reported | Value reported by ES in the bundle |
| Snapshot RPO | In-progress and failed snapshot times were used as the "last snapshot" | Based on the last successful (SUCCESS) snapshot; Critical if there is none | Only a recoverable backup counts toward RPO |

### False positives removed

| Item | Previous | Current |
| --- | --- | --- |
| Write block (IDX-008) | Every blocked index was Critical (for example 1,634 rolled-over backing indices) | Critical only for current write targets and flood stage blocks. Rolled-over indices and searchable snapshots are OK. Standalone indices are Info (IDX-011) |
| Node comparison (spec, shard count, resources, workload) | All data nodes compared together | Compared only within the same tier. Differences between tiers go to the NODE-003 reference table |
| System index detection | Everything starting with `.` is a system index → `.ds-*` user data missed | `.ds-<name>` is judged by the data stream name |
| hot threads | % including wait time, classified in signature list order, could be Critical | Uses only the `cpu=` value, classified from the top frame, at most Warning because it is a 500ms snapshot |
| Mapping heap (SHD-010) | Included master and ML nodes | Data nodes only (the target of the official formula) |
| Field limit (MAP-001) | All Warning | Info if ignore_dynamic_beyond_limit=true |
| Total field count (MAP-002) | Warning | Info (a sum across indices, so no official criterion) |
| Partial bundle | A file not collected was judged "not set" (for example, no snapshot repository was Critical) | No finding when the input was not collected |
| Double judgment of settings | ARS and others counted twice, in SET-001 and in a dedicated rule | Settings with a dedicated rule are marked `[finding: rule ID]` and excluded from SET severity |
| Empty index (SHD-011) | Included a write index that had just rolled over | Current write targets excluded |
| node.processors | Reported as changed even if only set explicitly | Not a change when equal to the CPUs actually allocated |
| Version notice (VER-001) | Warning (included in the action list) | Info |
| Oversharding (OVS-001) | Excessive if under 50GB per shard | Only when under the official lower bound of 10GB. The recommended count is calculated with the 50GB upper bound |

### False negatives fixed

| Item | Previous | Current |
| --- | --- | --- |
| OS-001 | When a node was at risk, Warning nodes were left out of the list | Nodes in both the risk and warning ranges are shown |
| Tier-wide saturation | Signal lost after switching to tier comparison | Judged separately by HOT-005 (a capacity shortage, not skew) |
| fully mounted (cold) indices | All searchable snapshots excluded from size findings | Only partial (frozen) are excluded. fully mounted is included because its size is real |
| Component templates | `composed_of` was not merged → MAP-003, VEC-002, and VEC-003 could not see component mappings | Merge fixed |
| TPL-001 | Could never fire because the pattern list was filtered | Works, and its target is redefined as "a legacy template hidden by a composable template" (ES refuses to create duplicates with the same priority) |

### Reliability

- The `"70% or higher"` text in `BRK-002` was read as a `%` format specifier and raised an error at run time → changed to `%%`, and a static check of all format strings in the code was added
- Removed a path where a different bundle file format stopped the whole run at the start of analysis
- Numeric strings in stats files are normalized to numbers on load, and safe accessors for numbers, dicts, and string lists were added
- Removed the repeated index count × shard count loop (handles 20,000 indices and 60,000 shards)
- A misspelled threshold key was silently ignored → now a warning
- Removed 12 unused thresholds (values that had no effect when tuned)

### Report

- Removed the weighted score (an arbitrary formula with no official basis, and 0 points on large clusters) → only the overall judgment based on counts is shown
- The area filter used anchor jumps and did not work in sandboxed viewers → severity × area combination filter buttons
- Rule execution errors appeared directly in the body → summarized under "Items not evaluated because of a tool error" at the bottom, with the trace collapsed. Also included in Markdown
- Node status matrix, top indices by storage, severity distribution bar, and print styles
