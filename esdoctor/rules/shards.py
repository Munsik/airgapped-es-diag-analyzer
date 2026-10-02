# -*- coding: utf-8 -*-
"""Shard and index level rules."""

import collections

from ..i18n import T, N_
from ..model import Finding, Severity, table
from ..util import dig, fmt_bytes, fmt_ms, fmt_num, parse_bytes, pct, num

CAT = "shard"
DOC_INDEX_MODULES = ("Index modules (refresh_interval, search idle)",
                     "https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules")
DOC_MERGE = ("Merge settings", "https://www.elastic.co/docs/reference/elasticsearch/index-settings/merge")
DOC_TRANSLOG = ("Translog settings", "https://www.elastic.co/docs/reference/elasticsearch/index-settings/translog")
DOC_SIZE = (N_("rules.shards._.01"),
            "https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards")
DOC_MAPPING = (N_("rules.shards._.02"),
               "https://www.elastic.co/docs/manage-data/data-store/mapping")

GB = 1024 ** 3


def _explicit_index_setting(ctx, index, key):
    """Reads only the settings section (explicitly set values) of settings.json. The defaults section is not used."""
    from ..context import _flat_get
    return _flat_get(dig(ctx.index_settings, index, "settings") or {}, key)


def _is_snapshot_backed(ctx, index):
    """Whether the index is a searchable snapshot (mounted) index. Replica 0 is the normal design for these."""
    return bool(ctx.index_setting(index, "index.store.snapshot.repository_name")
                or str(ctx.index_setting(index, "index.store.type") or "") == "snapshot")


def _primary_store(ctx, index):
    return num(ctx.indices_stats, index, "primaries", "store", "size_in_bytes")


def _total_store(ctx, index):
    return num(ctx.indices_stats, index, "total", "store", "size_in_bytes")


def r_shard_density(ctx):
    """Shard density per node.

    '20 shards per 1GB of heap' is the official guideline for versions before 8.3. From 8.3 the heap overhead per shard dropped sharply
    (Elastic blog), and the docs replaced the guideline during 8.3.x with the 'field mapper heap estimate (SHD-010)' and cluster.max_shards_per_node (CLU-015).
    So on 8.3 or later it is not rated and only the current numbers are shown.
    """
    counts = collections.Counter()
    for s in ctx.shards:
        node = s.get("node")
        if node:
            counts[node] += 1
    if not counts:
        return []
    legacy = ctx.version_tuple < (8, 3, 0)
    rows, bad = [], []
    for n in ctx.nodes:
        c = counts.get(n.name, 0)
        heap_gb = (n.heap_max or 0) / float(GB)
        per_gb = (c / heap_gb) if heap_gb else None
        rows.append([n.name, fmt_num(c), "%.1fGB" % heap_gb if heap_gb else "-",
                     "%.1f" % per_gb if per_gb else "-", ",".join(n.roles)])
        if legacy and per_gb is not None and per_gb >= ctx.t["shards_per_gb_heap_warn"]:
            bad.append((n.name, per_gb, c))
    ev = table(["node", T("rules.shards.r_shard_density.01"), "heap", T("rules.shards.r_shard_density.02"), "roles"], rows)
    if not legacy:
        return [Finding("SHD-001", CAT, Severity.INFO, T("rules.shards.r_shard_density.03"),
                        observed=T("rules.shards.r_shard_density.04") % ctx.version,
                        evidence=ev, refs=[DOC_SIZE], source="indices.json / nodes_stats.json")]
    if not bad:
        return [Finding("SHD-001", CAT, Severity.OK, T("rules.shards.r_shard_density.05"),
                        observed=T("rules.shards.r_shard_density.06")
                                 % ctx.t["shards_per_gb_heap_warn"],
                        evidence=ev, source="indices.json / nodes_stats.json")]
    crit = [b for b in bad if b[1] >= ctx.t["shards_per_gb_heap_crit"]]
    return [Finding(
        "SHD-001", CAT, Severity.CRITICAL if crit else Severity.WARNING,
        T("rules.shards.r_shard_density.07"),
        observed=", ".join(T("rules.shards.r_shard_density.08") % (n, fmt_num(c), p) for n, p, c in bad),
        impact=T("rules.shards.r_shard_density.09"),
        recommend=T("rules.shards.r_shard_density.10"),
        evidence=ev, affected=[b[0] for b in bad], refs=[DOC_SIZE],
        source="indices.json / nodes_stats.json")]


def r_shard_size(ctx):
    """Primary shard store >= shard_size_gb_crit → Critical (SHD-002), >= shard_size_gb_warn (official upper bound 50GB) → Warning (SHD-003)."""
    big, huge = [], []
    for s in ctx.shards:
        if (s.get("prirep") or "").lower() != "p" or ctx.is_partial_mount(s.get("index")):
            continue
        b = parse_bytes(s.get("store"))
        if not b:
            continue
        gb = b / float(GB)
        if gb >= ctx.t["shard_size_gb_crit"]:
            huge.append([s.get("index"), s.get("shard"), fmt_bytes(b), s.get("node")])
        elif gb >= ctx.t["shard_size_gb_warn"]:
            big.append([s.get("index"), s.get("shard"), fmt_bytes(b), s.get("node")])
    out = []
    if huge:
        out.append(Finding(
            "SHD-002", CAT, Severity.CRITICAL, T("rules.shards.r_shard_size.01"),
            observed=T("rules.shards.r_shard_size.02") % (ctx.t["shard_size_gb_crit"], len(huge)),
            impact=T("rules.shards.r_shard_size.03"),
            recommend=T("rules.shards.r_shard_size.04"),
            evidence=table(["index", "shard", "size", "node"], huge[: ctx.t["top_n"]]),
            refs=[DOC_SIZE], source="indices.json"))
    if big:
        out.append(Finding(
            "SHD-003", CAT, Severity.WARNING, T("rules.shards.r_shard_size.05"),
            observed=T("rules.shards.r_shard_size.02") % (ctx.t["shard_size_gb_warn"], len(big)),
            impact=T("rules.shards.r_shard_size.06"),
            recommend=T("rules.shards.r_shard_size.07"),
            evidence=table(["index", "shard", "size", "node"], big[: ctx.t["top_n"]]),
            refs=[DOC_SIZE], source="indices.json"))
    return out


def r_small_shards(ctx):
    """Warning if user-index primaries with store < small_shard_mb number at least small_shard_count_warn, and small primaries make up at least small_shard_ratio_warn of all primaries. System indices do not count toward the shard-count condition because users cannot tune them."""
    small, total, user_small = 0, 0, 0
    rows = []
    per_index = collections.defaultdict(lambda: [0, 0])  # count, bytes
    for s in ctx.shards:
        if (s.get("prirep") or "").lower() != "p" or ctx.is_partial_mount(s.get("index")):
            continue
        b = parse_bytes(s.get("store")) or 0
        total += 1
        idx = s.get("index")
        per_index[idx][0] += 1
        per_index[idx][1] += b
        if b < ctx.t["small_shard_mb"] * 1024 * 1024:
            small += 1
            if not ctx.is_system_index(idx):
                user_small += 1
    if not total:
        return []
    ratio = small / float(total)
    # System indices (.kibana, .internal.alerts, etc.) cannot be tuned by the user,
    # so the action-needed decision is based on user indices only.
    if user_small < ctx.t["small_shard_count_warn"] or ratio < ctx.t["small_shard_ratio_warn"]:
        return []
    # Candidates that create many small shards (several shards but a small total size)
    for idx, (cnt, byt) in per_index.items():
        if cnt >= 2 and byt < cnt * ctx.t["small_shard_mb"] * 1024 * 1024:
            rows.append([idx, cnt, fmt_bytes(byt), fmt_bytes(byt / cnt)])
    rows.sort(key=lambda r: -r[1])
    return [Finding(
        "SHD-004", CAT, Severity.WARNING, T("rules.shards.r_small_shards.01"),
        observed=T("rules.shards.r_small_shards.02")
                 % (total, small, ratio * 100, ctx.t["small_shard_mb"], user_small),
        impact=T("rules.shards.r_small_shards.03"),
        recommend=T("rules.shards.r_small_shards.04"),
        evidence=table(["index", T("rules.shards.r_small_shards.05"), T("rules.shards.r_small_shards.06"), T("rules.shards.r_small_shards.07")], rows[: ctx.t["top_n"]]),
        refs=[DOC_SIZE], source="indices.json")]


def r_replica_zero(ctx):
    """User indices with number_of_replicas=0, no auto_expand_replicas, and not a searchable snapshot index → Warning."""
    rows = []
    for name in ctx.indices_stats.keys():
        if ctx.is_system_index(name):
            continue
        rep = ctx.index_setting(name, "index.number_of_replicas")
        auto = ctx.index_setting(name, "index.auto_expand_replicas")
        if _is_snapshot_backed(ctx, name):
            continue        # The snapshot is the source of truth, so replica 0 is normal
        if str(rep) == "0" and (not auto or str(auto).lower() == "false"):
            rows.append([name, fmt_bytes(_primary_store(ctx, name)),
                         fmt_num(dig(ctx.indices_stats, name, "primaries", "docs", "count"))])
    if not rows:
        return []
    rows.sort(key=lambda r: -(parse_bytes(r[1]) or 0))
    return [Finding(
        "IDX-001", CAT, Severity.WARNING, T("rules.shards.r_replica_zero.01"),
        observed=T("rules.shards.r_replica_zero.02") % len(rows),
        impact=T("rules.shards.r_replica_zero.03"),
        recommend=T("rules.shards.r_replica_zero.04"),
        evidence=table(["index", T("rules.shards.r_replica_zero.05"), T("rules.shards.r_replica_zero.06")], rows[: ctx.t["top_n"]]),
        source="settings.json / indices_stats.json")]


def r_replica_unassignable(ctx):
    """number_of_replicas > (number of data nodes - 1) → Warning (replicas stay unassigned permanently). Indices with auto_expand_replicas are excluded. The node count per tier is not checked, so the rating is conservative (it can miss cases but never raises a false alarm)."""
    data_nodes = len(ctx.data_nodes) or len(ctx.nodes)
    rows = []
    for name in ctx.index_settings.keys():
        auto = ctx.index_setting(name, "index.auto_expand_replicas")
        if auto and str(auto).lower() != "false":
            continue        # Adjusted to the node count automatically, so it cannot exceed it
        rep = ctx.index_setting(name, "index.number_of_replicas")
        try:
            rep = int(rep)
        except (TypeError, ValueError):
            continue
        if rep > 0 and rep > data_nodes - 1:
            rows.append([name, rep, data_nodes])
    if not rows:
        return []
    return [Finding(
        "IDX-002", CAT, Severity.WARNING, T("rules.shards.r_replica_unassignable.01"),
        observed=T("rules.shards.r_replica_unassignable.02") % (data_nodes, len(rows)),
        impact=T("rules.shards.r_replica_unassignable.03"),
        recommend=T("rules.shards.r_replica_unassignable.04"),
        evidence=table(["index", "replicas", T("rules.shards.r_replica_unassignable.05")], rows[: ctx.t["top_n"]]),
        source="settings.json")]


def r_deleted_docs(ctx):
    """For indices with primary store >= 1GB, deleted / (docs + deleted) >= deleted_docs_ratio_warn → Warning."""
    rows = []
    for name, st in ctx.indices_stats.items():
        if ctx.is_searchable_snapshot(name):
            continue
        docs = num(st, "primaries", "docs", "count")
        dele = num(st, "primaries", "docs", "deleted")
        size = num(st, "primaries", "store", "size_in_bytes")
        if docs + dele == 0 or size < GB:
            continue
        r = dele / float(docs + dele)
        if r >= ctx.t["deleted_docs_ratio_warn"]:
            rows.append([name, fmt_num(docs), fmt_num(dele), "%.0f%%" % (r * 100), fmt_bytes(size)])
    if not rows:
        return []
    rows.sort(key=lambda r: -float(r[3].rstrip("%")))
    return [Finding(
        "IDX-003", CAT, Severity.WARNING, T("rules.shards.r_deleted_docs.01"),
        observed=T("rules.shards.r_deleted_docs.02") % (ctx.t["deleted_docs_ratio_warn"] * 100, len(rows)),
        impact=T("rules.shards.r_deleted_docs.03"),
        recommend=T("rules.shards.r_deleted_docs.04"),
        evidence=table(["index", T("rules.shards.r_deleted_docs.05"), T("rules.shards.r_deleted_docs.06"), T("rules.shards.r_deleted_docs.07"), T("rules.shards.r_deleted_docs.08")], rows[: ctx.t["top_n"]]),
        source="indices_stats.json")]


def r_segments(ctx):
    """Primary segments / primary shards >= segments_per_shard_warn and primary store > 100MB → Warning."""
    rows = []
    for name, st in ctx.indices_stats.items():
        if ctx.is_searchable_snapshot(name):
            continue
        seg = num(st, "primaries", "segments", "count")
        shards = ctx.primary_count(name) or 1
        per = seg / float(shards)
        size = num(st, "primaries", "store", "size_in_bytes")
        if per >= ctx.t["segments_per_shard_warn"] and size > 100 * 1024 * 1024:
            rows.append([name, fmt_num(seg), shards, "%.0f" % per, fmt_bytes(size)])
    if not rows:
        return []
    rows.sort(key=lambda r: -float(r[3]))
    return [Finding(
        "IDX-004", CAT, Severity.WARNING, T("rules.shards.r_segments.01"),
        observed=T("rules.shards.r_segments.02") % (ctx.t["segments_per_shard_warn"], len(rows)),
        impact=T("rules.shards.r_segments.03"),
        recommend=T("rules.shards.r_segments.04"),
        evidence=table(["index", T("rules.shards.r_segments.05"), T("rules.shards.r_segments.06"), T("rules.shards.r_segments.07"), T("rules.shards.r_segments.08")], rows[: ctx.t["top_n"]]),
        source="indices_stats.json")]


def r_merge_throttle(ctx):
    """merges.total_throttled_time / merges.total_time >= merge_throttle_ratio_warn and cumulative throttled time > 60 seconds → Warning."""
    rows = []
    for name, st in ctx.indices_stats.items():
        mt = num(st, "total", "merges", "total_time_in_millis")
        th = num(st, "total", "merges", "total_throttled_time_in_millis")
        if mt and th / float(mt) >= ctx.t["merge_throttle_ratio_warn"] and th > 60000:
            rows.append([name, fmt_ms(mt), fmt_ms(th), "%.0f%%" % (th / float(mt) * 100)])
    if not rows:
        return []
    rows.sort(key=lambda r: -float(r[3].rstrip("%")))
    return [Finding(
        "IDX-005", CAT, Severity.WARNING, T("rules.shards.r_merge_throttle.01"),
        observed=T("rules.shards.r_merge_throttle.02") % len(rows),
        impact=T("rules.shards.r_merge_throttle.03"),
        recommend=T("rules.shards.r_merge_throttle.04"),
        evidence=table(["index", T("rules.shards.r_merge_throttle.05"), T("rules.shards.r_merge_throttle.06"), T("rules.shards.r_merge_throttle.07")], rows[: ctx.t["top_n"]]),
        source="indices_stats.json")]


def r_search_latency(ctx):
    """For indices with query_total >= min_query_total_for_latency, average query latency = query_time / query_total. >= search_latency_ms_crit → Critical, >= warn → Warning (PERF-001). Average indexing time per document = index_time / index_total is rated the same way with index_latency_ms_crit / warn (PERF-002). These are cumulative averages, not p99. Partially mounted (frozen) indices are not rated for search latency: they read from the snapshot repository on cache misses, so slower searches are expected there (see FRZ-001)."""
    rows_slow, rows_idx = [], []
    for name, st in ctx.indices_stats.items():
        qt = num(st, "total", "search", "query_total")
        qm = num(st, "total", "search", "query_time_in_millis")
        if qt >= ctx.t["min_query_total_for_latency"] and not ctx.is_partial_mount(name):
            avg = qm / float(qt)
            if avg >= ctx.t["search_latency_ms_warn"]:
                rows_slow.append([name, fmt_num(qt), "%.1fms" % avg,
                                  fmt_ms(dig(st, "total", "search", "fetch_time_in_millis")),
                                  fmt_bytes(dig(st, "total", "store", "size_in_bytes")), avg])
        it = num(st, "total", "indexing", "index_total")
        im = num(st, "total", "indexing", "index_time_in_millis")
        if it >= ctx.t["min_query_total_for_latency"]:
            avg_i = im / float(it)
            if avg_i >= ctx.t["index_latency_ms_warn"]:
                rows_idx.append([name, fmt_num(it), "%.1fms" % avg_i,
                                 fmt_num(dig(st, "total", "indexing", "index_failed")), avg_i])
    out = []
    if rows_slow:
        rows_slow.sort(key=lambda r: -r[5])
        crit = [r for r in rows_slow if r[5] >= ctx.t["search_latency_ms_crit"]]
        out.append(Finding(
            "PERF-001", CAT, Severity.CRITICAL if crit else Severity.WARNING,
            T("rules.shards.r_search_latency.01"),
            observed=T("rules.shards.r_search_latency.02")
                     % (ctx.t["search_latency_ms_warn"], len(rows_slow), rows_slow[0][2]),
            impact=T("rules.shards.r_search_latency.03"),
            recommend=T("rules.shards.r_search_latency.04"),
            evidence=table(["index", T("rules.shards.r_search_latency.05"), T("rules.shards.r_search_latency.06"), T("rules.shards.r_search_latency.07"), T("rules.shards.r_search_latency.08")],
                           [r[:5] for r in rows_slow[: ctx.t["top_n"]]]),
            source="indices_stats.json"))
    if rows_idx:
        rows_idx.sort(key=lambda r: -r[4])
        out.append(Finding(
            "PERF-002", CAT,
            Severity.CRITICAL if rows_idx[0][4] >= ctx.t["index_latency_ms_crit"] else Severity.WARNING,
            T("rules.shards.r_search_latency.09"),
            observed=T("rules.shards.r_search_latency.10")
                     % (ctx.t["index_latency_ms_warn"], len(rows_idx)),
            impact=T("rules.shards.r_search_latency.11"),
            recommend=T("rules.shards.r_search_latency.12"),
            evidence=table(["index", T("rules.shards.r_search_latency.13"), T("rules.shards.r_search_latency.14"), T("rules.shards.r_search_latency.15")],
                           [r[:4] for r in rows_idx[: ctx.t["top_n"]]]),
            source="indices_stats.json"))
    return out


def r_index_failures(ctx):
    """Indices with indexing.index_failed or search.query_failure > 0. Warning if user indices are included, Info if only system indices are.
    Sorted by the failure ratio, index_failed / (index_failed + index_total), so indices that lose a large share of their writes come first."""
    rows, user_rows = [], []
    for name, st in ctx.indices_stats.items():
        failed = num(st, "total", "indexing", "index_failed")
        qf = num(st, "total", "search", "query_failure")
        if failed or qf:
            it = num(st, "total", "indexing", "index_total")
            ratio = failed / float(failed + it) if (failed + it) else 0
            row = [name, fmt_num(failed), "%.1f%%" % (ratio * 100) if failed else "-", fmt_num(qf),
                   fmt_num(it), (ratio, failed + qf)]
            rows.append(row)
            if not ctx.is_system_index(name):
                user_rows.append(row)
    if not rows:
        return []
    rows.sort(key=lambda r: (-r[5][0], -r[5][1]))
    return [Finding(
        "IDX-006", CAT,
        Severity.WARNING if user_rows else Severity.INFO,
        T("rules.shards.r_index_failures.01") + ("" if user_rows else T("rules.shards.r_index_failures.02")),
        observed=T("rules.shards.r_index_failures.03") % len(rows),
        impact=T("rules.shards.r_index_failures.04"),
        recommend=T("rules.shards.r_index_failures.05"),
        evidence=table(["index", "index_failed", T("rules.shards.r_index_failures.06"), "query_failure", "index_total"],
                       [r[:5] for r in rows[: ctx.t["top_n"]]]),
        source="indices_stats.json")]


def r_mapping_limits(ctx):
    """User index with mapping.total_fields.limit > 1000 (the default) → Warning (MAP-001), or Info if all such indices have ignore_dynamic_beyond_limit=true. Searchable snapshot mounts are skipped (read-only). Total field count in cluster_stats > 100,000 → Info (MAP-002)."""
    rows, ignored = [], 0
    for name in ctx.index_settings.keys():
        if ctx.is_system_index(name) or ctx.is_searchable_snapshot(name):
            continue        # System indices use product-set values; searchable snapshot mounts are read-only, nothing to act on
        lim = ctx.index_setting(name, "index.mapping.total_fields.limit")
        if lim is None:
            continue
        try:
            lim = int(lim)
        except (TypeError, ValueError):
            continue
        if lim > 1000:
            ign = str(ctx.index_setting(name, "index.mapping.total_fields.ignore_dynamic_beyond_limit")).lower() == "true"
            ignored += 1 if ign else 0
            rows.append([name, fmt_num(lim), "true" if ign else "false"])
    total_fields = dig(ctx.cluster_stats, "indices", "mappings", "total_field_count")
    out = []
    if rows:
        out.append(Finding(
            "MAP-001", CAT, Severity.INFO if ignored == len(rows) else Severity.WARNING,
            T("rules.shards.r_mapping_limits.01"),
            observed=T("rules.shards.r_mapping_limits.02")
                     % (len(rows), ignored),
            impact=T("rules.shards.r_mapping_limits.03"),
            recommend=T("rules.shards.r_mapping_limits.04"),
            evidence=table(["index", "total_fields.limit", "ignore_dynamic_beyond_limit"],
                           sorted(rows, key=lambda r: r[2])[: ctx.t["top_n"]]),
            refs=[DOC_MAPPING], source="settings.json"))
    if total_fields and total_fields > 100000:
        out.append(Finding(
            "MAP-002", CAT, Severity.INFO, T("rules.shards.r_mapping_limits.05"),
            observed=T("rules.shards.r_mapping_limits.06") % fmt_num(total_fields),
            impact=T("rules.shards.r_mapping_limits.07"),
            recommend=T("rules.shards.r_mapping_limits.08"),
            refs=[DOC_MAPPING], source="cluster_stats.json"))
    return out


def r_refresh_interval(ctx):
    """Refresh interval.

    Indices without an explicit refresh_interval use the search idle behavior.
    A shard with no search for index.search.idle.after (default 30s) skips the periodic refresh,
    so 'not set' does not mean 'refresh every second'. Therefore only indices that explicitly set 1s or less are rated.
    """
    rows = []
    for name, st in ctx.indices_stats.items():
        if ctx.is_system_index(name):
            continue
        it = num(st, "total", "indexing", "index_total")
        if it < ctx.t["heavy_index_docs"]:
            continue
        explicit = _explicit_index_setting(ctx, name, "index.refresh_interval")
        if explicit is None:
            continue
        from ..util import parse_time_ms
        ms = parse_time_ms(explicit)
        if ms is not None and 0 < ms <= 1000:
            rows.append([name, str(explicit), fmt_num(it),
                         fmt_num(dig(st, "total", "refresh", "total")),
                         fmt_ms(dig(st, "total", "refresh", "total_time_in_millis"))])
    if not rows:
        return []
    return [Finding(
        "IDX-007", CAT, Severity.INFO, T("rules.shards.r_refresh_interval.01"),
        observed=T("rules.shards.r_refresh_interval.02") % len(rows),
        impact=T("rules.shards.r_refresh_interval.03"),
        recommend=T("rules.shards.r_refresh_interval.04"),
        evidence=table(["index", "refresh_interval", T("rules.shards.r_refresh_interval.05"), T("rules.shards.r_refresh_interval.06"), T("rules.shards.r_refresh_interval.07")],
                       rows[: ctx.t["top_n"]]),
        refs=[DOC_INDEX_MODULES], source="settings.json / indices_stats.json")]


def r_read_only_blocks(ctx):
    """Separates write blocks on indices into 'expected blocks' and 'problem blocks'.

    Expected (not rated, count shown as Info): searchable snapshot mounted indices and indices that have finished rollover
    (old backing indices of a data stream, alias members that are not the write target, indexing_complete=true).
    It is normal for the ILM readonly, shrink, forcemerge and searchable_snapshot phases to put a write block on an index after rollover.
    Problem (Critical, IDX-008): index.blocks.read_only_allow_delete=true (usually left over from flood stage, applies to all indices),
    or a write/read_only block on a current write target (data stream write index / alias write index).
    Needs checking (Info, IDX-011): a write/read_only block on a standalone index that belongs to no data stream or alias (may be intentional archiving).
    """
    targets = ctx.write_targets()
    bad, check, normal = [], [], collections.Counter()
    for name in ctx.index_settings.keys():
        flags = [k for k in ("index.blocks.read_only_allow_delete", "index.blocks.read_only",
                             "index.blocks.write") if str(ctx.index_setting(name, k)).lower() == "true"]
        if not flags:
            continue
        if "index.blocks.read_only_allow_delete" in flags:
            bad.append([name, "read_only_allow_delete", T("rules.shards.r_read_only_blocks.01")])
            continue
        if ctx.is_searchable_snapshot(name):
            normal["searchable snapshot"] += 1
            continue
        if name in targets:
            bad.append([name, ", ".join(f.split(".")[-1] for f in flags), T("rules.shards.r_read_only_blocks.02")])
            continue
        if ctx.rolled_over(name):
            normal[T("rules.shards.r_read_only_blocks.03")] += 1
            continue
        if ctx.is_system_index(name):
            normal[T("rules.shards.r_read_only_blocks.04")] += 1
            continue
        check.append([name, ", ".join(f.split(".")[-1] for f in flags)])
    out = []
    note = (T("rules.shards.r_read_only_blocks.05") % ", ".join(T("rules.shards.r_read_only_blocks.06") % kv for kv in normal.items())) if normal else ""
    if bad:
        out.append(Finding(
            "IDX-008", CAT, Severity.CRITICAL, T("rules.shards.r_read_only_blocks.07"),
            observed=T("rules.shards.r_read_only_blocks.08") % (len(bad), note),
            impact=T("rules.shards.r_read_only_blocks.09"),
            recommend=T("rules.shards.r_read_only_blocks.10"),
            evidence=table(["index", T("rules.shards.r_read_only_blocks.11"), T("rules.shards.r_read_only_blocks.12")], bad[: ctx.t["top_n"]]),
            source="settings.json / data_stream.json / alias.json"))
    if check:
        out.append(Finding(
            "IDX-011", CAT, Severity.INFO, T("rules.shards.r_read_only_blocks.13"),
            observed=T("rules.shards.r_read_only_blocks.14") % (len(check), note),
            impact=T("rules.shards.r_read_only_blocks.15"),
            recommend=T("rules.shards.r_read_only_blocks.16"),
            evidence=table(["index", T("rules.shards.r_read_only_blocks.11")], check[: ctx.t["top_n"]]),
            source="settings.json / alias.json"))
    if not bad and not check and normal:
        out.append(Finding(
            "IDX-008", CAT, Severity.OK, T("rules.shards.r_read_only_blocks.17"),
            observed=T("rules.shards.r_read_only_blocks.18") % note,
            source="settings.json / data_stream.json / alias.json"))
    return out


def r_tier_preference(ctx):
    """Whether the data tier an index requires actually exists on the nodes."""
    available = set()
    for n in ctx.nodes:
        for r in n.roles:
            if r.startswith("data_"):
                available.add(r)
        if "data" in n.roles:
            available.update({"data_content", "data_hot", "data_warm", "data_cold"})
    if not available:
        return []
    rows = []
    for name in ctx.index_settings.keys():
        pref = ctx.index_setting(name, "index.routing.allocation.include._tier_preference")
        if not pref:
            continue
        tiers = [t.strip() for t in str(pref).split(",") if t.strip()]
        if tiers and not any(t in available for t in tiers):
            rows.append([name, pref, ", ".join(sorted(available))])
    if not rows:
        return []
    return [Finding(
        "IDX-009", CAT, Severity.CRITICAL, T("rules.shards.r_tier_preference.01"),
        observed=T("rules.shards.r_tier_preference.02") % len(rows),
        impact=T("rules.shards.r_tier_preference.03"),
        recommend=T("rules.shards.r_tier_preference.04"),
        evidence=table(["index", T("rules.shards.r_tier_preference.05"), T("rules.shards.r_tier_preference.06")], rows[: ctx.t["top_n"]]),
        source="settings.json / nodes.json")]


def r_index_count(ctx):
    """Average size per shard (store / shards) < 200MB, shards >= 300, and total store > 50GB → Warning. Otherwise only a size summary is shown as Info."""
    n_idx = dig(ctx.cluster_stats, "indices", "count") or len(ctx.indices_stats)
    shards = dig(ctx.cluster_stats, "indices", "shards", "total") or ctx.health.get("active_shards")
    store = dig(ctx.cluster_stats, "indices", "store", "size_in_bytes")
    docs = dig(ctx.cluster_stats, "indices", "docs", "count")
    avg = (store / shards) if (store and shards) else None
    ev = table([T("rules.shards.r_index_count.01"), T("rules.shards.r_index_count.02")],
               [[T("rules.shards.r_index_count.03"), fmt_num(n_idx)],
                [T("rules.shards.r_index_count.04"), fmt_num(shards)],
                [T("rules.shards.r_index_count.05"), fmt_num(docs)],
                [T("rules.shards.r_index_count.06"), fmt_bytes(store)],
                [T("rules.shards.r_index_count.07"), fmt_bytes(avg)]])
    if (avg is not None and avg < 200 * 1024 * 1024 and shards and shards >= 300
            and store and store > 50 * GB):
        return [Finding(
            "SHD-005", CAT, Severity.WARNING, T("rules.shards.r_index_count.08"),
            observed=T("rules.shards.r_index_count.09") % (fmt_bytes(avg), fmt_num(shards), fmt_bytes(store)),
            impact=T("rules.shards.r_index_count.10"),
            recommend=T("rules.shards.r_index_count.11"),
            evidence=ev, refs=[DOC_SIZE], source="cluster_stats.json")]
    return [Finding("SHD-005", CAT, Severity.INFO, T("rules.shards.r_index_count.12"),
                    observed=T("rules.shards.r_index_count.13") % (fmt_num(n_idx), fmt_num(shards),
                                                          fmt_bytes(store)),
                    evidence=ev, source="cluster_stats.json")]




def r_shard_balance(ctx):
    """Warning if the spread in shard count between nodes within the same tier is 25% of the average or more.

    Each tier holds different data and has a different node count, so differences in shard count between tiers are normal and are not compared.
    """
    counts = collections.Counter(s.get("node") for s in ctx.shards if s.get("node"))
    rows, flagged = [], []
    for tier, nodes in ctx.data_tiers().items():
        vals = [(n.name, counts.get(n.name, 0)) for n in nodes]
        for name, c in vals:
            rows.append([tier, name, c])
        if len(vals) < 2:
            continue
        nums = [c for _, c in vals]
        avg = sum(nums) / float(len(nums))
        if avg and (max(nums) - min(nums)) / avg >= 0.25:
            flagged.append(T("rules.shards.r_shard_balance.01") % (tier, max(nums), min(nums), avg))
    if not flagged:
        return []
    return [Finding(
        "SHD-006", CAT, Severity.WARNING, T("rules.shards.r_shard_balance.02"),
        observed=" / ".join(flagged),
        impact=T("rules.shards.r_shard_balance.03"),
        recommend=T("rules.shards.r_shard_balance.04"),
        evidence=table(["tier", "node", T("rules.shards.r_shard_balance.05")], rows),
        source="indices.json / nodes.json")]


def r_data_stream_health(ctx):
    """data stream status RED → Critical, YELLOW → Warning."""
    bad = []
    for ds in ctx.data_streams or []:
        st = (ds.get("status") or "").upper()
        if st in ("RED", "YELLOW"):
            bad.append([ds.get("name"), st, ds.get("generation"),
                        len(ds.get("indices") or []), ds.get("ilm_policy") or "-"])
    if not bad:
        return []
    red = [b for b in bad if b[1] == "RED"]
    return [Finding(
        "IDX-010", CAT, Severity.CRITICAL if red else Severity.WARNING,
        T("rules.shards.r_data_stream_health.01"),
        observed=T("rules.shards.r_data_stream_health.02") % (len(red), len(bad) - len(red)),
        impact=T("rules.shards.r_data_stream_health.03"),
        recommend=T("rules.shards.r_data_stream_health.04"),
        evidence=table(["data_stream", "status", "generation", T("rules.shards.r_data_stream_health.05"), "ILM"], bad[: ctx.t["top_n"]]),
        source="commercial/data_stream.json")]


def r_cache_efficiency(ctx):
    """Efficiency of the query cache and the shard request cache."""
    qc_hit = num(ctx.indices_stats_all, "total", "query_cache", "hit_count")
    qc_miss = num(ctx.indices_stats_all, "total", "query_cache", "miss_count")
    qc_evict = num(ctx.indices_stats_all, "total", "query_cache", "evictions")
    rc_hit = num(ctx.indices_stats_all, "total", "request_cache", "hit_count")
    rc_miss = num(ctx.indices_stats_all, "total", "request_cache", "miss_count")
    rc_evict = num(ctx.indices_stats_all, "total", "request_cache", "evictions")
    if qc_hit + qc_miss < 10000 and rc_hit + rc_miss < 10000:
        return []
    qc_rate = pct(qc_hit, qc_hit + qc_miss)
    rc_rate = pct(rc_hit, rc_hit + rc_miss)
    ev = table([T("rules.shards.r_cache_efficiency.01"), "hit", "miss", T("rules.shards.r_cache_efficiency.02"), "eviction"],
               [["query cache", fmt_num(qc_hit), fmt_num(qc_miss),
                 "%.1f%%" % qc_rate if qc_rate is not None else "-", fmt_num(qc_evict)],
                ["request cache", fmt_num(rc_hit), fmt_num(rc_miss),
                 "%.1f%%" % rc_rate if rc_rate is not None else "-", fmt_num(rc_evict)]])
    warn = (qc_rate is not None and qc_rate < 20 and qc_evict > qc_hit) or \
           (rc_rate is not None and rc_rate < 20 and rc_evict > rc_hit)
    if not warn:
        return [Finding("PERF-003", CAT, Severity.INFO, T("rules.shards.r_cache_efficiency.03"),
                        observed=T("rules.shards.r_cache_efficiency.04")
                                 % ("%.1f%%" % qc_rate if qc_rate is not None else "-",
                                    "%.1f%%" % rc_rate if rc_rate is not None else "-"),
                        evidence=ev, source="indices_stats.json")]
    return [Finding(
        "PERF-003", CAT, Severity.WARNING, T("rules.shards.r_cache_efficiency.05"),
        observed=T("rules.shards.r_cache_efficiency.06")
                 % ("%.1f%%" % qc_rate if qc_rate is not None else "-",
                    "%.1f%%" % rc_rate if rc_rate is not None else "-"),
        impact=T("rules.shards.r_cache_efficiency.07"),
        recommend=T("rules.shards.r_cache_efficiency.08"),
        evidence=ev, source="indices_stats.json")]



def _write_targets_now(ctx):
    """Indices being written: data stream write indices, alias write targets and indices indexing at collection time."""
    out = set(i for i in ctx.write_targets() if i)
    for name, st in ctx.indices_stats.items():
        if num(st, "total", "indexing", "index_current") > 0:
            out.add(name)
    return out


def r_write_hotspot(ctx):
    """Write-target shards per node within a tier (SHD-016).

    Write targets are data stream write indices, alias write indices and indices indexing at collection time, limited to those with
    indexing.index_total > 0 (a low-volume stream can keep an idle write index for months); replicas count because they index too. Per tier (frozen skipped, tiers with fewer than 2 nodes skipped):
    (max - min) / average >= write_shard_skew_warn and max - min >= write_shard_skew_min → Warning. SHD-006 compares all shards;
    this one compares only shards that take writes, which is where indexing load lands.
    """
    writes = set(i for i in _write_targets_now(ctx)
                 if num(ctx.indices_stats, i, "total", "indexing", "index_total") > 0)
    if not writes:
        return []
    counts = collections.Counter(s.get("node") for s in ctx.shards
                                 if s.get("node") and s.get("index") in writes
                                 and (s.get("state") or "STARTED").upper() == "STARTED")
    rows, flagged = [], []
    for tier, nodes in ctx.data_tiers().items():
        if tier == "frozen" or len(nodes) < 2:
            continue
        vals = [(n.name, counts.get(n.name, 0)) for n in nodes]
        nums = [c for _, c in vals]
        avg = sum(nums) / float(len(nums))
        spread = max(nums) - min(nums)
        if not avg or spread < ctx.t["write_shard_skew_min"] or spread / avg < ctx.t["write_shard_skew_warn"]:
            continue
        flagged.append(T("rules.shards.r_write_hotspot.01") % (tier, max(nums), min(nums), avg))
        for name, c in sorted(vals, key=lambda x: -x[1]):
            rows.append([tier, name, c, "%+.0f%%" % ((c - avg) / avg * 100)])
    if not flagged:
        return []
    return [Finding(
        "SHD-016", CAT, Severity.WARNING, T("rules.shards.r_write_hotspot.02"),
        observed=" / ".join(flagged),
        impact=T("rules.shards.r_write_hotspot.03"),
        recommend=T("rules.shards.r_write_hotspot.04"),
        evidence=table(["tier", "node", T("rules.shards.r_write_hotspot.05"), T("rules.shards.r_write_hotspot.06")],
                       rows[: ctx.t["top_n"] * 2]),
        source="indices.json / data_stream.json / alias.json / indices_stats.json")]


def r_indexing_throttle(ctx):
    """Indexing throttled because merges fell behind (IDX-014).

    Official: once merging is fully unthrottled and still behind, indexing for the shard is throttled until merges catch up.
    indices_stats indexing.is_throttled = true at collection time → Warning. Only cumulative indexing.throttle_time > 0 → Info.
    """
    now, past = [], []
    for name, st in ctx.indices_stats.items():
        thr = dig(st, "total", "indexing", "is_throttled")
        ms = num(st, "total", "indexing", "throttle_time_in_millis")
        if str(thr).lower() == "true":
            now.append([name, "true", fmt_ms(ms) if ms else "-",
                        fmt_ms(num(st, "total", "merges", "total_throttled_time_in_millis"))])
        elif ms:
            past.append([name, "false", fmt_ms(ms),
                         fmt_ms(num(st, "total", "merges", "total_throttled_time_in_millis")), ms])
    if not (now or past):
        return []
    past.sort(key=lambda r: -r[4])
    rows = now + [r[:4] for r in past]
    return [Finding(
        "IDX-014", CAT, Severity.WARNING if now else Severity.INFO, T("rules.shards.r_indexing_throttle.01"),
        observed=T("rules.shards.r_indexing_throttle.02") % (len(now), len(past)),
        impact=T("rules.shards.r_indexing_throttle.03"),
        recommend=T("rules.shards.r_indexing_throttle.04"),
        evidence=table(["index", "is_throttled", T("rules.shards.r_indexing_throttle.05"),
                        T("rules.shards.r_indexing_throttle.06")], rows[: ctx.t["top_n"]]),
        refs=[DOC_MERGE], source="indices_stats.json")]


def r_translog_uncommitted(ctx):
    """Uncommitted translog per shard copy against index.translog.flush_threshold_size (IDX-015).

    Official: a flush runs once the uncommitted translog reaches flush_threshold_size (default 10GB), and uncommitted
    operations are replayed on recovery (the default was 512MB before 8.8). Average uncommitted size per shard copy (index total / copies) at or above the
    effective threshold → Warning: flushes are not keeping up, and recovery of those shards will replay that much.
    """
    default = parse_bytes(ctx.t["translog_flush_threshold_default"] if ctx.version_tuple >= (8, 8, 0)
                          else ctx.t["translog_flush_threshold_legacy"]) or 10 * 1024 ** 3
    rows = []
    for name, st in ctx.indices_stats.items():
        unc = num(st, "total", "translog", "uncommitted_size_in_bytes")
        copies = ctx.shard_count(name) or 1
        if not unc:
            continue
        limit = parse_bytes(ctx.index_setting(name, "index.translog.flush_threshold_size")) or default
        per = unc / float(copies)
        if per >= limit:
            rows.append([name, fmt_bytes(unc), copies, fmt_bytes(per), fmt_bytes(limit), per])
    if not rows:
        return []
    rows.sort(key=lambda r: -r[5])
    return [Finding(
        "IDX-015", CAT, Severity.WARNING, T("rules.shards.r_translog_uncommitted.01"),
        observed=T("rules.shards.r_translog_uncommitted.02") % len(rows),
        impact=T("rules.shards.r_translog_uncommitted.03"),
        recommend=T("rules.shards.r_translog_uncommitted.04"),
        evidence=table(["index", T("rules.shards.r_translog_uncommitted.05"), T("rules.shards.r_translog_uncommitted.06"),
                        T("rules.shards.r_translog_uncommitted.07"), "flush_threshold_size"],
                       [r[:5] for r in rows[: ctx.t["top_n"]]]),
        refs=[DOC_TRANSLOG], source="indices_stats.json / settings.json")]

RULES = [
    r_shard_density, r_shard_balance, r_data_stream_health, r_cache_efficiency, r_shard_size, r_small_shards, r_replica_zero,
    r_replica_unassignable, r_deleted_docs, r_segments, r_merge_throttle,
    r_search_latency, r_index_failures, r_mapping_limits, r_refresh_interval,
    r_read_only_blocks, r_tier_preference, r_index_count,
    r_write_hotspot, r_indexing_throttle, r_translog_uncommitted,
]
