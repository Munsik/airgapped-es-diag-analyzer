# -*- coding: utf-8 -*-
"""Settings knowledge base.

A diagnostics bundle cannot tell you the original default of a setting.
  - The defaults section of cluster_settings_defaults.json already reflects elasticsearch.yml values (not pure defaults).
  - Keys set explicitly through the API do not appear in the defaults section.
  - settings.json (index level) has no defaults section.
So defaults, meaning and change impact are defined in this file from the official docs (ES_BASELINE).
A setting that is not listed here is reported as "no description registered", and its value is reported as is.

Precedence (official): transient > persistent > elasticsearch.yml > default.
Static settings can only be changed in elasticsearch.yml on every target node and need a restart.

Fields
  default : official default (string). Defaults that are computed are described in text
  kind    : dynamic | static
  scope   : cluster | node | index
  meaning : what the setting does
  up/down : impact of raising / lowering the value (numeric, size, time and ratio types)
  change  : impact when a non-numeric value changes
  risk    : severity hint when the value differs from the default: (up, down) or a single value. None | "INFO" | "WARNING"
  doc     : reference doc key (DOCS)
  basis   : "docs" when the default is in the official docs, "source" when it is only in the Elasticsearch source code
"""

import re

from .i18n import T, N_, tr
from .util import parse_bytes, parse_time_ms

DOCS = {
    "stack": (N_("settings_kb._.01"),
              "https://www.elastic.co/docs/deploy-manage/stack-settings#static-dynamic"),
    "put": ("Cluster update settings API",
            "https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-cluster-put-settings"),
    "alloc": ("Cluster-level shard allocation and routing",
              "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings"),
    "breaker": ("Circuit breaker settings",
                "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/circuit-breaker-settings"),
    "tp": ("Thread pool settings",
           "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings"),
    "recovery": ("Index recovery settings",
                 "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/index-recovery-settings"),
    "search": ("Search settings",
               "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/search-settings"),
    "misc": ("Miscellaneous cluster settings",
             "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings"),
    "buffer": ("Indexing buffer settings",
               "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/indexing-buffer-settings"),
    "qcache": ("Node query cache settings",
               "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/node-query-cache-settings"),
    "fdcache": ("Field data cache settings",
                "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/field-data-cache-settings"),
    "net": ("Networking settings",
            "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/networking-settings"),
    "index": ("Index modules (index settings)",
              "https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules"),
    "translog": ("Translog settings",
                 "https://www.elastic.co/docs/reference/elasticsearch/index-settings/translog"),
    "merge": ("Merge settings",
              "https://www.elastic.co/docs/reference/elasticsearch/index-settings/merge"),
    "maplimit": ("Mapping limit settings",
                 "https://www.elastic.co/docs/reference/elasticsearch/index-settings/mapping-limit"),
    "shards": ("Size your shards",
               "https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards"),
    "idxmgmt": ("Index management settings",
                "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/index-management-settings"),
    "ars": ("Search shard routing",
            "https://www.elastic.co/docs/reference/elasticsearch/rest-apis/search-shard-routing"),
    "querydsl": ("Query DSL",
                 "https://www.elastic.co/docs/reference/query-languages/querydsl"),
    "searchapi": ("The search API",
                  "https://www.elastic.co/docs/solutions/search/the-search-api"),
    "ilm": ("Index lifecycle management settings",
            "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/index-lifecycle-management-settings"),
    "geoip": ("GeoIP processor",
              "https://www.elastic.co/docs/reference/enrich-processor/geoip-processor"),
    "snapshot": ("Snapshot and restore settings",
                 "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/snapshot-restore-settings"),
    "monitoring": ("Monitoring settings",
                   "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/monitoring-settings"),
    "ml": ("Machine learning settings",
           "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/machine-learning-settings"),
    "store": ("Store (index settings)",
              "https://www.elastic.co/docs/reference/elasticsearch/index-settings/store"),
    "reqcache_node": ("Shard request cache settings",
                      "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/shard-request-cache-settings"),
    "reqcache": ("The shard request cache",
                 "https://www.elastic.co/docs/deploy-manage/distributed-architecture/shard-request-cache"),
    "delayed": ("Delaying allocation when a node leaves",
                "https://www.elastic.co/docs/deploy-manage/distributed-architecture/shard-allocation-relocation-recovery/delaying-allocation-when-node-leaves"),
    "total_shards": ("Total shards per node",
                     "https://www.elastic.co/docs/reference/elasticsearch/index-settings/total-shards-per-node"),
    "blocks": ("Index blocks",
               "https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-block"),
    "memory": ("Disable swapping",
               "https://www.elastic.co/docs/deploy-manage/deploy/self-managed/setup-configuration-memory"),
}


def S(default, kind, scope, meaning, up=None, down=None, change=None, risk=None, doc="misc", basis="docs"):
    return {"default": default, "kind": kind, "scope": scope, "meaning": meaning,
            "up": up, "down": down, "change": change, "risk": risk, "doc": doc, "basis": basis}


KB = {
    # ------------------------------------------------------------ cluster: shard allocation
    "cluster.routing.allocation.enable": S(
        "all", "dynamic", "cluster", N_("settings_kb._.02"),
        change=N_("settings_kb._.03"),
        risk="WARNING", doc="alloc"),
    "cluster.routing.rebalance.enable": S(
        "all", "dynamic", "cluster", N_("settings_kb._.04"),
        change=N_("settings_kb._.05"),
        risk="WARNING", doc="alloc"),
    "cluster.routing.allocation.allow_rebalance": S(
        N_("settings_kb.allow_rebalance_default"), "dynamic", "cluster",
        N_("settings_kb._.06"),
        change=N_("settings_kb._.07"), risk="INFO", doc="alloc"),
    "cluster.routing.allocation.cluster_concurrent_rebalance": S(
        "2", "dynamic", "cluster", N_("settings_kb._.08"),
        up=N_("settings_kb._.09"),
        down=N_("settings_kb._.10"),
        risk=("INFO", "WARNING"), doc="alloc"),
    "cluster.routing.allocation.node_concurrent_recoveries": S(
        "2", "dynamic", "cluster", N_("settings_kb._.11"),
        up=N_("settings_kb._.12"),
        down=N_("settings_kb._.13"), risk=("INFO", "INFO"), doc="alloc"),
    "cluster.routing.allocation.node_concurrent_incoming_recoveries": S(
        "2", "dynamic", "cluster", N_("settings_kb._.14"),
        up=N_("settings_kb._.15"), down=N_("settings_kb._.16"), risk=("INFO", "INFO"), doc="alloc"),
    "cluster.routing.allocation.node_concurrent_outgoing_recoveries": S(
        "2", "dynamic", "cluster", N_("settings_kb._.17"),
        up=N_("settings_kb._.18"), down=N_("settings_kb._.16"),
        risk=("INFO", "INFO"), doc="alloc"),
    "cluster.routing.allocation.node_initial_primaries_recoveries": S(
        "4", "dynamic", "cluster", N_("settings_kb._.19"),
        up=N_("settings_kb._.20"), down=N_("settings_kb._.21"),
        risk=("INFO", "INFO"), doc="alloc"),
    "cluster.routing.allocation.same_shard.host": S(
        "false", "dynamic", "cluster", N_("settings_kb._.22"),
        change=N_("settings_kb._.23"), risk="INFO", doc="alloc"),
    "cluster.routing.allocation.total_shards_per_node": S(
        "-1", "dynamic", "cluster", N_("settings_kb._.24"),
        down=N_("settings_kb._.25"),
        risk=(None, "WARNING"), doc="alloc"),
    "cluster.routing.allocation.awareness.attributes": S(
        "", "dynamic", "cluster", N_("settings_kb._.26"),
        change=N_("settings_kb._.27"),
        risk="INFO", doc="alloc"),
    "cluster.routing.use_adaptive_replica_selection": S(
        "true", "dynamic", "cluster", N_("settings_kb._.28"),
        change=N_("settings_kb._.29"),
        risk="WARNING", doc="ars"),
    "cluster.routing.allocation.balance.shard": S(
        "0.45", "dynamic", "cluster", N_("settings_kb._.30"),
        change=N_("settings_kb._.31"),
        risk="INFO", doc="alloc"),
    "cluster.routing.allocation.balance.index": S(
        "0.55", "dynamic", "cluster", N_("settings_kb._.32"),
        change=N_("settings_kb._.33"), risk="INFO", doc="alloc"),
    "cluster.routing.allocation.balance.threshold": S(
        "1.0", "dynamic", "cluster", N_("settings_kb._.34"),
        up=N_("settings_kb._.35"),
        down=N_("settings_kb._.36"), risk=("INFO", "INFO"), doc="alloc"),
    "cluster.routing.allocation.balance.write_load": S(
        "10.0", "dynamic", "cluster", N_("settings_kb._.37"),
        change=N_("settings_kb._.38"), risk="INFO", doc="alloc"),
    "cluster.routing.allocation.balance.disk_usage": S(
        "2.0E-11", "dynamic", "cluster", N_("settings_kb._.39"),
        change=N_("settings_kb._.40"), risk="INFO", doc="alloc"),
    # ------------------------------------------------------------ cluster: disk
    "cluster.routing.allocation.disk.threshold_enabled": S(
        "true", "dynamic", "cluster", N_("settings_kb._.41"),
        change=N_("settings_kb._.42"),
        risk="WARNING", doc="alloc"),
    "cluster.routing.allocation.disk.watermark.low": S(
        "85%", "dynamic", "cluster", N_("settings_kb._.43"),
        up=N_("settings_kb._.44"),
        down=N_("settings_kb._.45"), risk=("INFO", "INFO"), doc="alloc"),
    "cluster.routing.allocation.disk.watermark.high": S(
        "90%", "dynamic", "cluster", N_("settings_kb._.46"),
        up=N_("settings_kb._.47"),
        down=N_("settings_kb._.48"), risk=("WARNING", "INFO"), doc="alloc"),
    "cluster.routing.allocation.disk.watermark.flood_stage": S(
        "95%", "dynamic", "cluster", N_("settings_kb._.49"),
        up=N_("settings_kb._.50"),
        down=N_("settings_kb._.51"), risk=("WARNING", "INFO"), doc="alloc"),
    "cluster.info.update.interval": S(
        "30s", "dynamic", "cluster", N_("settings_kb._.52"),
        up=N_("settings_kb._.53"), down=N_("settings_kb._.54"),
        risk=("WARNING", "INFO"), doc="alloc"),
    # ------------------------------------------------------------ cluster: limits and protection
    "cluster.max_shards_per_node": S(
        "1000", "dynamic", "cluster", N_("settings_kb._.55"),
        up=N_("settings_kb._.56"),
        down=N_("settings_kb._.57"), risk=("WARNING", "INFO"), doc="misc"),
    "cluster.max_shards_per_node.frozen": S(
        "3000", "dynamic", "cluster", N_("settings_kb._.58"),
        up=N_("settings_kb._.59"), down=N_("settings_kb._.60"),
        risk=("INFO", "INFO"), doc="misc"),
    "cluster.blocks.read_only": S(
        "false", "dynamic", "cluster", N_("settings_kb._.61"),
        change=N_("settings_kb._.62"), risk="WARNING", doc="misc"),
    "cluster.blocks.read_only_allow_delete": S(
        "false", "dynamic", "cluster", N_("settings_kb._.63"),
        change=N_("settings_kb._.64"), risk="WARNING", doc="misc"),
    "action.destructive_requires_name": S(
        "true", "dynamic", "cluster", N_("settings_kb._.65"),
        change=N_("settings_kb._.66"), risk="WARNING", doc="idxmgmt"),
    "action.auto_create_index": S(
        "true", "dynamic", "cluster", N_("settings_kb._.67"),
        change=N_("settings_kb._.68"), risk="INFO", doc="idxmgmt"),
    "cluster.indices.close.enable": S(
        "true", "dynamic", "cluster", N_("settings_kb._.69"),
        change=N_("settings_kb._.70"),
        risk="INFO", doc="idxmgmt"),
    "cluster.persistent_tasks.allocation.enable": S(
        "all", "dynamic", "cluster", N_("settings_kb._.71"),
        change=N_("settings_kb._.72"), risk="WARNING", doc="misc"),
    # ------------------------------------------------------------ cluster: recovery, search, breakers
    "indices.recovery.max_bytes_per_sec": S(
        N_("settings_kb.recovery_default"), "dynamic", "cluster", N_("settings_kb._.73"),
        up=N_("settings_kb._.74"),
        down=N_("settings_kb._.75"), risk=("INFO", "WARNING"), doc="recovery"),
    "search.default_search_timeout": S(
        "-1", "dynamic", "cluster", N_("settings_kb._.76"),
        change=N_("settings_kb._.77"),
        risk="INFO", doc="searchapi"),
    "search.max_buckets": S(
        "65536", "dynamic", "cluster", N_("settings_kb._.78"),
        up=N_("settings_kb._.79"),
        down=N_("settings_kb._.80"), risk=("WARNING", "INFO"), doc="search"),
    "search.allow_expensive_queries": S(
        "true", "dynamic", "cluster", N_("settings_kb._.81"),
        change=N_("settings_kb._.82"),
        risk="INFO", doc="querydsl"),
    "search.low_level_cancellation": S(
        "true", "dynamic", "cluster", N_("settings_kb._.83"),
        change=N_("settings_kb._.84"), risk="INFO", doc="search", basis="source"),
    "indices.breaker.total.limit": S(
        N_("settings_kb.breaker_total_default"), "dynamic", "cluster", N_("settings_kb._.85"),
        up=N_("settings_kb._.86"),
        down=N_("settings_kb._.87"), risk=("WARNING", "INFO"), doc="breaker"),
    "indices.breaker.fielddata.limit": S(
        "40%", "dynamic", "cluster", N_("settings_kb._.88"),
        up=N_("settings_kb._.89"), down=N_("settings_kb._.90"),
        risk=("WARNING", "INFO"), doc="breaker"),
    "indices.breaker.request.limit": S(
        "60%", "dynamic", "cluster", N_("settings_kb._.91"),
        up=N_("settings_kb._.92"), down=N_("settings_kb._.90"),
        risk=("WARNING", "INFO"), doc="breaker"),
    "network.breaker.inflight_requests.limit": S(
        "100%", "dynamic", "cluster", N_("settings_kb._.93"),
        up=N_("settings_kb._.94"), down=N_("settings_kb._.95"),
        risk=("WARNING", "INFO"), doc="breaker"),
    "script.max_compilations_rate": S(
        "150/5m", "dynamic", "cluster", N_("settings_kb._.96"),
        change=N_("settings_kb._.97"),
        risk="INFO", doc="breaker"),
    "indices.lifecycle.poll_interval": S(
        "10m", "dynamic", "cluster", N_("settings_kb._.98"),
        up=N_("settings_kb._.99"),
        down=N_("settings_kb._.100"), risk=("INFO", "WARNING"), doc="ilm"),
    "xpack.monitoring.collection.enabled": S(
        "false", "dynamic", "cluster", N_("settings_kb._.101"),
        change=N_("settings_kb._.102"),
        risk="INFO", doc="monitoring"),
    "ingest.geoip.downloader.enabled": S(
        "true", "dynamic", "cluster", N_("settings_kb._.103"),
        change=N_("settings_kb._.104"),
        risk=None, doc="geoip"),
    "slm.retention_schedule": S(
        "0 30 1 * * ?", "dynamic", "cluster", N_("settings_kb._.105"),
        change=N_("settings_kb._.106"), risk=None, doc="snapshot"),
    "cluster.metadata.display_name": S(
        "", "dynamic", "cluster", N_("settings_kb._.107"), change=N_("settings_kb._.108"),
        risk=None, doc="misc"),
    "xpack.ml.max_machine_memory_percent": S(
        "30", "dynamic", "cluster", N_("settings_kb._.109"),
        up=N_("settings_kb._.110"), down=N_("settings_kb._.111"),
        risk=("INFO", "INFO"), doc="ml"),
    # ------------------------------------------------------------ node (static, elasticsearch.yml)
    "indices.memory.index_buffer_size": S(
        "10%", "static", "node", N_("settings_kb._.112"),
        up=N_("settings_kb._.113"),
        down=N_("settings_kb._.114"), risk=("INFO", "INFO"), doc="buffer"),
    "indices.queries.cache.size": S(
        "10%", "static", "node", N_("settings_kb._.115"),
        up=N_("settings_kb._.116"), down=N_("settings_kb._.117"),
        risk=("INFO", "INFO"), doc="qcache"),
    "indices.requests.cache.size": S(
        "1%", "static", "node", N_("settings_kb._.118"),
        up=N_("settings_kb._.119"), down=N_("settings_kb._.120"), risk=("INFO", "INFO"), doc="reqcache_node"),
    "indices.fielddata.cache.size": S(
        "unbounded", "static", "node", N_("settings_kb._.121"),
        change=N_("settings_kb._.122"),
        risk="INFO", doc="fdcache"),
    "indices.breaker.total.use_real_memory": S(
        "true", "static", "node", N_("settings_kb._.123"),
        change=N_("settings_kb._.124"),
        risk="WARNING", doc="breaker"),
    "thread_pool.write.queue_size": S(
        N_("settings_kb.write_queue_default"), "static", "node", N_("settings_kb._.125"),
        up=N_("settings_kb._.126"),
        down=N_("settings_kb._.127"), risk=("WARNING", "INFO"), doc="tp"),
    "thread_pool.search.queue_size": S(
        N_("settings_kb._.128"), "static", "node",
        N_("settings_kb._.129"),
        up=N_("settings_kb._.130"), down=N_("settings_kb._.131"),
        risk=("WARNING", "INFO"), doc="tp"),
    "thread_pool.write.size": S(
        N_("settings_kb._.132"), "static", "node", N_("settings_kb._.133"),
        change=N_("settings_kb._.134"), risk="WARNING", doc="tp"),
    "thread_pool.search.size": S(
        N_("settings_kb._.135"), "static", "node", N_("settings_kb._.136"),
        change=N_("settings_kb._.137"), risk="WARNING", doc="tp"),
    "node.processors": S(
        N_("settings_kb._.138"), "static", "node", N_("settings_kb._.139"),
        change=N_("settings_kb._.140"), risk="INFO", doc="tp"),
    "http.max_content_length": S(
        "100mb", "static", "node", N_("settings_kb._.141"),
        up=N_("settings_kb._.142"),
        down=N_("settings_kb._.143"), risk=("WARNING", "INFO"), doc="net"),
    "transport.compress": S(
        "indexing_data", "static", "node", N_("settings_kb._.144"),
        change=N_("settings_kb._.145"),
        risk="INFO", doc="net"),
    "bootstrap.memory_lock": S(
        "false", "static", "node", N_("settings_kb._.146"),
        change=N_("settings_kb._.147"),
        risk=None, doc="memory", basis="source"),
    "node.store.allow_mmap": S(
        "true", "static", "node", N_("settings_kb._.148"),
        change=N_("settings_kb._.149"),
        risk="INFO", doc="store"),
    # ------------------------------------------------------------ index
    "index.refresh_interval": S(
        N_("settings_kb._.150"), "dynamic", "index", N_("settings_kb._.151"),
        up=N_("settings_kb._.152"),
        down=N_("settings_kb._.153"),
        risk=("INFO", "INFO"), doc="index"),
    "index.number_of_replicas": S(
        "1", "dynamic", "index", N_("settings_kb._.154"),
        up=N_("settings_kb._.155"),
        down=N_("settings_kb._.156"), risk=("INFO", "WARNING"), doc="index"),
    "index.translog.durability": S(
        "request", "dynamic", "index", N_("settings_kb._.157"),
        change=N_("settings_kb._.158"),
        risk="WARNING", doc="translog"),
    "index.translog.sync_interval": S(
        "5s", "dynamic", "index", N_("settings_kb._.159"),
        up=N_("settings_kb._.160"), down=N_("settings_kb._.161"), risk=("INFO", "INFO"), doc="translog"),
    "index.max_result_window": S(
        "10000", "dynamic", "index", N_("settings_kb._.162"),
        up=N_("settings_kb._.163"),
        down=N_("settings_kb._.164"), risk=("WARNING", "INFO"), doc="index"),
    "index.max_inner_result_window": S(
        "100", "dynamic", "index", N_("settings_kb._.165"),
        up=N_("settings_kb._.166"), down=N_("settings_kb._.167"), risk=("INFO", "INFO"), doc="index"),
    "index.max_terms_count": S(
        "65536", "dynamic", "index", N_("settings_kb._.168"),
        up=N_("settings_kb._.169"), down=N_("settings_kb._.167"), risk=("INFO", "INFO"), doc="index"),
    "index.max_regex_length": S(
        "1000", "dynamic", "index", N_("settings_kb._.170"),
        up=N_("settings_kb._.171"), down=N_("settings_kb._.167"), risk=("INFO", "INFO"), doc="index"),
    "index.mapping.total_fields.limit": S(
        "1000", "dynamic", "index", N_("settings_kb._.172"),
        up=N_("settings_kb._.173"),
        down=N_("settings_kb._.174"), risk=("WARNING", "INFO"), doc="maplimit"),
    "index.mapping.depth.limit": S(
        "20", "dynamic", "index", N_("settings_kb._.175"), up=N_("settings_kb._.176"), down=N_("settings_kb._.177"),
        risk=("INFO", "INFO"), doc="maplimit"),
    "index.mapping.nested_fields.limit": S(
        N_("settings_kb.nested_default"), "dynamic", "index", N_("settings_kb._.178"),
        up=N_("settings_kb._.179"), down=N_("settings_kb._.180"), risk=("WARNING", "INFO"),
        doc="maplimit"),
    "index.mapping.nested_objects.limit": S(
        "10000", "dynamic", "index", N_("settings_kb._.181"),
        up=N_("settings_kb._.182"), down=N_("settings_kb._.183"),
        risk=("WARNING", "INFO"), doc="maplimit"),
    "index.unassigned.node_left.delayed_timeout": S(
        "1m", "dynamic", "index", N_("settings_kb._.184"),
        up=N_("settings_kb._.185"),
        down=N_("settings_kb._.186"), risk=("INFO", "WARNING"), doc="delayed"),
    "index.codec": S(
        "default(LZ4)", "static", "index", N_("settings_kb._.187"),
        change=N_("settings_kb._.188"),
        risk="INFO", doc="index"),
    "index.routing.allocation.total_shards_per_node": S(
        "-1", "dynamic", "index", N_("settings_kb._.189"),
        down=N_("settings_kb._.190"), risk=(None, "WARNING"), doc="total_shards"),
    "index.search.idle.after": S(
        "30s", "dynamic", "index", N_("settings_kb._.191"),
        up=N_("settings_kb._.192"), down=N_("settings_kb._.193"),
        risk=("INFO", "INFO"), doc="index"),
    "index.requests.cache.enable": S(
        "true", "dynamic", "index", N_("settings_kb._.194"), change=N_("settings_kb._.195"),
        risk="INFO", doc="reqcache"),
    "index.queries.cache.enabled": S(
        "true", "static", "index", N_("settings_kb._.196"), change=N_("settings_kb._.197"),
        risk="INFO", doc="qcache"),
    "index.merge.policy.max_merged_segment": S(
        N_("settings_kb.max_merged_default"), "dynamic", "index", N_("settings_kb._.198"),
        up=N_("settings_kb._.199"),
        down=N_("settings_kb._.200"), risk=("INFO", "INFO"), doc="merge", basis="source"),
    "index.merge.policy.segments_per_tier": S(
        N_("settings_kb.segments_per_tier_default"), "dynamic", "index", N_("settings_kb._.201"),
        up=N_("settings_kb._.202"), down=N_("settings_kb._.203"),
        risk=("INFO", "INFO"), doc="merge", basis="source"),
    "index.merge.policy.floor_segment": S(
        N_("settings_kb.floor_segment_default"), "dynamic", "index", N_("settings_kb._.237"),
        up=N_("settings_kb._.238"), down=N_("settings_kb._.239"),
        risk=("INFO", "INFO"), doc="merge", basis="source"),
    "index.merge.policy.max_merge_at_once": S(
        N_("settings_kb.max_merge_at_once_default"), "dynamic", "index", N_("settings_kb._.240"),
        up=N_("settings_kb._.241"), down=N_("settings_kb._.242"),
        risk=("INFO", "INFO"), doc="merge", basis="source"),
    "index.highlight.max_analyzed_offset": S(
        "1000000", "dynamic", "index", N_("settings_kb._.204"),
        up=N_("settings_kb._.205"), down=N_("settings_kb._.206"),
        risk=("INFO", "INFO"), doc="index"),
    "index.max_ngram_diff": S(
        "1", "dynamic", "index", N_("settings_kb._.207"),
        up=N_("settings_kb._.208"), down=N_("settings_kb._.209"),
        risk=("INFO", "INFO"), doc="index"),
    "index.max_shingle_diff": S(
        "3", "dynamic", "index", N_("settings_kb._.210"),
        up=N_("settings_kb._.211"), down=N_("settings_kb._.209"), risk=("INFO", "INFO"), doc="index"),
    "index.max_script_fields": S(
        "32", "dynamic", "index", N_("settings_kb._.212"), up=N_("settings_kb._.213"),
        down=N_("settings_kb._.214"), risk=("INFO", "INFO"), doc="index"),
    "index.max_docvalue_fields_search": S(
        "100", "dynamic", "index", N_("settings_kb._.215"), up=N_("settings_kb._.216"),
        down=N_("settings_kb._.214"), risk=("INFO", "INFO"), doc="index"),
    "index.max_refresh_listeners": S(
        "1000", "dynamic", "index", N_("settings_kb._.217"), up=N_("settings_kb._.218"),
        down=N_("settings_kb._.219"), risk=("INFO", "INFO"), doc="index", basis="source"),
    "index.auto_expand_replicas": S(
        "false", "dynamic", "index", N_("settings_kb._.220"),
        change=N_("settings_kb._.221"),
        risk="INFO", doc="index"),
    "index.blocks.write": S("false", "dynamic", "index", N_("settings_kb._.222"), change=N_("settings_kb._.223"),
                            risk="WARNING", doc="blocks"),
    "index.blocks.read_only": S("false", "dynamic", "index", N_("settings_kb._.224"), change=N_("settings_kb._.225"),
                                risk="WARNING", doc="blocks"),
    "index.blocks.read_only_allow_delete": S(
        "false", "dynamic", "index", N_("settings_kb._.226"),
        change=N_("settings_kb._.227"),
        risk="WARNING", doc="blocks"),
}

# Values treated as equal to the default (including markers used by deployment types)
EQUIV_EMPTY = ("", "null", "none", "[]", "no_instances_excluded")

# Prefix rules: allocation filter
PREFIX_RULES = [
    ("cluster.routing.allocation.exclude.", S(
        "", "dynamic", "cluster", N_("settings_kb._.228"),
        change=N_("settings_kb._.229"),
        risk="WARNING", doc="alloc")),
    ("cluster.routing.allocation.include.", S(
        "", "dynamic", "cluster", N_("settings_kb._.230"),
        change=N_("settings_kb._.231"), risk="WARNING", doc="alloc")),
    ("cluster.routing.allocation.require.", S(
        "", "dynamic", "cluster", N_("settings_kb._.232"),
        change=N_("settings_kb._.233"), risk="WARNING", doc="alloc")),
    ("logger.", S(
        N_("settings_kb._.234"), "dynamic", "cluster", N_("settings_kb._.235"),
        change=N_("settings_kb._.236"),
        risk="INFO", doc="misc")),
]


def _localized(spec):
    """Copy of a KB entry with its text fields translated into the current language."""
    out = dict(spec)
    for f in ("default", "meaning", "up", "down", "change"):
        if isinstance(out.get(f), str):
            out[f] = tr(out[f])
    return out


def lookup(key):
    if key in KB:
        return _localized(KB[key])
    for prefix, spec in PREFIX_RULES:
        if key.startswith(prefix):
            return _localized(spec)
    return None


def _norm(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return ",".join(str(x) for x in v)
    return str(v).strip()


def _num(v):
    """Number for comparison (one common scale regardless of unit). None if it cannot be parsed."""
    s = _norm(v).lower()
    if not s or s in ("unbounded",):
        return None
    if s.endswith("%"):
        try:
            return ("pct", float(s[:-1]))
        except ValueError:
            return None
    t = parse_time_ms(s)
    if t is not None and re.match(r"^-?[\d.]+(ms|s|m|h|d|nanos|micros)$", s):
        return ("time", t)
    b = parse_bytes(s)
    if b is not None and re.match(r"^-?[\d.]+(b|kb|mb|gb|tb|pb)$", s):
        return ("bytes", float(b))
    try:
        return ("num", float(s))
    except ValueError:
        return None


AUTO_DEFAULT = ("thread_pool.write.size", "thread_pool.search.size", "thread_pool.search.queue_size",
                "node.processors")
UNBOUNDED = ("-1", "-1b", "unbounded")


_GIB = 1024 ** 3


def _recovery_default(node):
    """indices.recovery.max_bytes_per_sec default of a node (RecoverySettings): 40mb, except on dedicated cold/frozen nodes,
    where it grows with total memory (40/60/90/125/250mb at <=4/8/16/32GB/above)."""
    data = [r for r in (node.roles or []) if r.startswith("data")]
    if not data or any(r not in ("data_cold", "data_frozen") for r in data):
        return "40mb"
    ram = node.ram_total or 0
    for limit, val in ((4, "40mb"), (8, "60mb"), (16, "90mb"), (32, "125mb")):
        if ram <= limit * _GIB:
            return val
    return "250mb"


# Index modes whose default codec is best_compression (IndexMode.getDefaultCodec in the Elasticsearch source):
# logsdb, and the columnar modes added in 9.5 (tech preview). standard, time_series, lookup and vectordb_document use the default (LZ4).
BEST_COMPRESSION_MODES = ("logsdb", "columnar", "logsdb_columnar")


def default_for(key, ctx=None, node=None, index=None):
    """Default that depends on the version, the node or the index, or None to use the KB value.

    thread_pool.write.queue_size: max(10000, allocated processors x 750) from 9.2 (10000 before).
    index.mapping.nested_fields.limit: 100 for indices created on index version 9_050_0_00 (9.3) or later, 50 before.
    indices.breaker.total.limit: 95% with use_real_memory (default), 70% when a node turns it off.
    indices.recovery.max_bytes_per_sec: per node role and memory (see _recovery_default).
    index.codec: best_compression for index modes that default to it (BEST_COMPRESSION_MODES), default otherwise.
    index.merge.policy.*: 9.5 changed segments_per_tier 10 → 8, floor_segment 2mb → 16mb and max_merge_at_once 10 → 16.
    max_merged_segment is 100gb for time-based indices (mapping with an indexed @timestamp date field, from 8.11; data stream
    membership when the mapping is not in the bundle) and 5gb otherwise.
    cluster.routing.allocation.allow_rebalance: always from 8.16 with the desired_balance allocator, indices_all_active before
    8.16 or when a node sets cluster.routing.allocation.type: balanced.
    index.queries.cache.enabled: false for the columnar and logsdb_columnar modes (9.5), true otherwise.
    All taken from the Elasticsearch source of the matching versions.
    """
    try:
        if key == "thread_pool.write.queue_size" and ctx is not None and node is not None:
            if ctx.version_tuple >= (9, 2, 0):
                alloc = int(node.info.get("os", {}).get("allocated_processors") or node.processors or 0)
                return str(max(10000, alloc * 750))
            return "10000"
        if key == "index.mapping.nested_fields.limit" and ctx is not None and index is not None:
            created = ctx.index_setting(index, "index.version.created")
            if created is not None:
                return "100" if int(str(created)) >= 9050000 else "50"
            return None
        if key == "indices.breaker.total.limit" and ctx is not None:
            if str(ctx.setting("indices.breaker.total.use_real_memory", "true")).lower() == "false":
                return "70%"        # dynamic from 8.x (source), so it can be set through the API too
            for n in ctx.nodes:
                if str(n.setting("indices.breaker.total.use_real_memory", "true")).lower() == "false":
                    return "70%"
            return "95%"
        if key == "indices.recovery.max_bytes_per_sec" and node is not None:
            return _recovery_default(node)
        if key == "cluster.routing.allocation.allow_rebalance" and ctx is not None:
            balanced = any(str(n.setting("cluster.routing.allocation.type", "")).lower() == "balanced" for n in ctx.nodes)
            return "indices_all_active" if (ctx.version_tuple < (8, 16, 0) or balanced) else "always"
        if key == "index.queries.cache.enabled" and ctx is not None and index is not None:
            mode = str(ctx.index_mode(index) or "standard").lower()
            return "false" if mode in ("columnar", "logsdb_columnar") else "true"
        if key == "index.codec" and ctx is not None and index is not None:
            mode = str(ctx.index_mode(index) or "standard").lower()
            return "best_compression" if mode in BEST_COMPRESSION_MODES else None
        if key.startswith("index.merge.policy.") and ctx is not None:
            new = ctx.version_tuple >= (9, 5, 0)
            if key == "index.merge.policy.segments_per_tier":
                return "8" if new else "10"
            if key == "index.merge.policy.floor_segment":
                return "16mb" if new else "2mb"
            if key == "index.merge.policy.max_merge_at_once":
                return "16" if new else "10"
            if key == "index.merge.policy.max_merged_segment" and index is not None:
                # ES picks the time-based merge policy when the mapping has an indexed @timestamp date field
                summ = (getattr(ctx, "mapping_summary", None) or {}).get(index)
                has_ts = summ.get("timestamp") if isinstance(summ, dict) and "timestamp" in summ else bool(ctx.data_stream_of(index))
                timed = ctx.version_tuple >= (8, 11, 0) and has_ts
                return "100gb" if timed else "5gb"
    except (TypeError, ValueError, AttributeError):
        return None
    return None


def compare(key, value, es_default=None, default=None):
    """(changed, direction, spec, default_used, default_source)

    direction: "up" | "down" | "change" | None
    default_source: "official docs" | "bundle (reported by ES)" | "not registered"
    default: a context-dependent default from default_for(), used instead of the KB value when given.
    """
    spec = lookup(key)
    if spec is not None:
        if default is None:
            default = spec["default"]
        source = T("settings_kb.compare.04") if spec.get("basis") == "source" else T("settings_kb.compare.01")
    elif es_default is not None:
        default, source = es_default, T("settings_kb.compare.02")
    else:
        return True, "change", None, None, T("settings_kb.compare.03")
    cur, dft = _norm(value), _norm(default)
    if key in AUTO_DEFAULT:
        return True, "change", spec, default, source      # auto-computed value: report only that it was set explicitly
    if cur.lower() in UNBOUNDED and dft.lower() in UNBOUNDED:
        return False, None, spec, default, source
    if cur.lower() in EQUIV_EMPTY and dft.lower() in EQUIV_EMPTY:
        return False, None, spec, default, source
    if cur.lower() == dft.lower():
        return False, None, spec, default, source
    a, b = _num(cur), _num(dft.split("(")[0])
    if a and b and a[0] == "num" and b[0] in ("time", "bytes") and a[1] in (0.0, -1.0):
        a = (b[0], a[1])           # a unitless 0 or -1 on a time or byte setting means zero or disabled/unlimited, same kind
    if dft.split("(")[0].strip().lower() == cur.lower():
        return False, None, spec, default, source      # "default" vs "default(LZ4)"
    if a and b and a[0] == b[0]:
        if a[1] == b[1]:
            return False, None, spec, default, source
        return True, ("up" if a[1] > b[1] else "down"), spec, default, source
    return True, "change", spec, default, source


def effect_of(spec, direction):
    if not spec:
        return T("settings_kb.effect_of.01")
    if direction == "up" and spec.get("up"):
        return "↑ " + spec["up"]
    if direction == "down" and spec.get("down"):
        return "↓ " + spec["down"]
    return spec.get("change") or spec.get("up") or spec.get("down") or ""


def risk_of(spec, direction):
    if not spec:
        return "INFO"
    r = spec.get("risk")
    if isinstance(r, tuple):
        if direction == "up":
            return r[0]
        if direction == "down":
            return r[1]
        return r[0] or r[1]
    return r
