# -*- coding: utf-8 -*-
"""Oversharding and small shard analysis.

Official guidance (Size your shards): 10-50 GB per shard, fewer than 200 million documents, avoid unnecessary small shards,
roll over on max_primary_shard_size (50GB), delete empty indices.
"""

import collections
import math

from ..i18n import T
from ..model import Finding, Severity, table
from ..util import dig, fmt_bytes, fmt_num, dicts, num, parse_bytes

CAT = "shard"
GB = 1024 ** 3
D_SHARDS = ("Size your shards",
            "https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards")


def _write_indices(ctx):
    """Indices still being filled, excluded from size rating: data stream write indices and alias members flagged is_write_index
    (context.explicit_write_targets). An index behind a plain read alias is rated."""
    return set(ctx.explicit_write_targets())


def _replicas(ctx, name):
    try:
        return int(ctx.index_setting(name, "index.number_of_replicas") or 0)
    except (TypeError, ValueError):
        return 0


def r_index_oversharding(ctx):
    """Oversharding per index.

    Scope: user indices with primary >= 2 that are not a data stream write index or a searchable snapshot.
    Fully mounted (cold) indices have an accurate size but cannot be shrunk, so only the number of oversharded ones is counted, with guidance on fixing the cause.
    Rating: average size per primary shard < oversharding_floor_shard_gb (official lower bound 10GB) means oversharded.
    Empty indices are left to SHD-011.
    Recommended primary count = the smallest factor of the current count (shrink can only go to a factor) that keeps each shard at or
    under oversharding_target_shard_gb (official upper bound 50GB). Excess shards = (current - recommended) × (1 + replica).
    Excess shard total >= oversharding_excess_warn or share of all shards >= oversharding_excess_ratio_warn → Warning;
    any other indices in scope → Info.
    """
    target = ctx.t["oversharding_target_shard_gb"] * GB
    floor = ctx.t["oversharding_floor_shard_gb"] * GB
    skip = _write_indices(ctx)
    rows, excess_total, mounted_over = [], 0, 0
    for name, st in ctx.indices_stats.items():
        if ctx.is_system_index(name) or name in skip or ctx.is_partial_mount(name):
            continue
        if ctx.is_searchable_snapshot(name):
            # Fully mounted: the size is accurate but the shard count cannot be changed
            # (the snapshot layout is used as is), so only count
            pri = ctx.primary_count(name)
            size = num(st, "primaries", "store", "size_in_bytes")
            if pri >= 2 and size / float(pri) < floor:
                mounted_over += 1
            continue
        pri = ctx.primary_count(name)
        if pri < 2 or not num(st, "primaries", "docs", "count"):
            continue            # an empty index is reported by SHD-011 (delete it rather than shrink it)
        size = num(st, "primaries", "store", "size_in_bytes")
        if size / float(pri) >= floor:
            continue            # At or above the official range (10-50GB) is not oversharded
        need = max(1, int(math.ceil(size / float(target))))
        rec = min(f for f in range(1, pri + 1) if pri % f == 0 and f >= need)
        if pri > rec:
            rep = _replicas(ctx, name)
            excess = (pri - rec) * (1 + rep)
            excess_total += excess
            rows.append([name, pri, rep, fmt_bytes(size), fmt_bytes(size / float(pri)), rec, excess])
    if not rows:
        if mounted_over:
            return [Finding(
                "OVS-001", CAT, Severity.INFO, T("rules.sharding.r_index_oversharding.01"),
                observed=T("rules.sharding.r_index_oversharding.02")
                         % (ctx.t["oversharding_floor_shard_gb"], mounted_over),
                impact=T("rules.sharding.r_index_oversharding.03"),
                recommend=T("rules.sharding.r_index_oversharding.04"),
                refs=[D_SHARDS], source="indices_stats.json / settings.json")]
        return []
    rows.sort(key=lambda r: -r[6])
    # The denominator uses the same source as the excess shard count (the shard list)
    total = len([x for x in ctx.shards if (x.get("state") or "").upper() != "UNASSIGNED"]) or \
        ctx.health.get("active_shards") or 1
    ratio = excess_total / float(total)
    sev = Severity.WARNING if (excess_total >= ctx.t["oversharding_excess_warn"]
                               or ratio >= ctx.t["oversharding_excess_ratio_warn"]) else Severity.INFO
    return [Finding(
        "OVS-001", CAT, sev, T("rules.sharding.r_index_oversharding.05"),
        observed=T("rules.sharding.r_index_oversharding.06")
                 % (len(rows), fmt_num(excess_total), ratio * 100,
                    (T("rules.sharding.r_index_oversharding.07")
                     % mounted_over) if mounted_over else ""),
        impact=T("rules.sharding.r_index_oversharding.08"),
        recommend=T("rules.sharding.r_index_oversharding.09"),
        evidence=table(["index", "primary", "replica", T("rules.sharding.r_index_oversharding.10"), T("rules.sharding.r_index_oversharding.11"), T("rules.sharding.r_index_oversharding.12"), T("rules.sharding.r_index_oversharding.13")],
                       rows[: ctx.t["top_n"]]),
        refs=[D_SHARDS], source="indices_stats.json / indices.json / settings.json")]


def r_datastream_small_rollover(ctx):
    """Checks whether a data stream rolls over too often and small backing indices pile up.

    Excluding the write index and partial (frozen) mounted backing indices (whose size is the cache size), if there are
    ds_min_backing_indices or more backing indices and the median size per primary shard is
    below ds_small_backing_shard_gb, the data stream is listed. When its rollover has no size condition (max_primary_shard_size or
    max_size in the ILM policy) the cause is rollover on age alone → Warning. When a size condition exists (the built-in
    logs@lifecycle and metrics@lifecycle policies, and data stream lifecycle, roll over at 50GB per primary shard) the stream simply
    receives little data → Info, and the advice is a longer max_age or fewer data streams. Data streams Elasticsearch manages for
    itself (ilm-history-*) are skipped.
    """
    rows = []
    for ds in ctx.data_streams or []:
        name = ds.get("name")
        if not name or str(name).startswith(".") or ctx.es_managed_stream(ds):
            continue
        idxs = [i.get("index_name") for i in dicts(ds.get("indices"))][:-1]   # exclude the write index
        sizes = []
        for ix in idxs:
            if ctx.is_partial_mount(ix):
                continue        # Skip partial (frozen) mounts (size is the cache size); keep fully mounted (real size)
            pri = ctx.primary_count(ix) or 1
            b = dig(ctx.indices_stats, ix, "primaries", "store", "size_in_bytes")
            if b is not None:
                sizes.append(b / float(pri))
        if len(sizes) < ctx.t["ds_min_backing_indices"]:
            continue
        sizes.sort()
        med = sizes[len(sizes) // 2]
        if med < ctx.t["ds_small_backing_shard_gb"] * GB:
            pol = ds.get("ilm_policy")
            if pol:
                ro = ctx.rollover_conditions(pol)
                sized = bool(ro.get("max_primary_shard_size") or ro.get("max_size"))
            else:
                # data stream lifecycle rolls over at 50GB per primary shard by default; a stream with neither ILM nor an enabled
                # lifecycle never rolls over on its own
                lc = ds.get("lifecycle")
                sized = isinstance(lc, dict) and str(lc.get("enabled", True)).lower() != "false"
            rows.append([name, len(sizes) + 1, fmt_bytes(med), pol or "-",
                         fmt_num(sum(ctx.shard_count(ix) for ix in idxs)),
                         T("rules.sharding.r_datastream_small_rollover.10") if sized
                         else T("rules.sharding.r_datastream_small_rollover.11")])
    if not rows:
        return []
    age_only = [r for r in rows if r[5] == T("rules.sharding.r_datastream_small_rollover.11")]
    rows.sort(key=lambda r: (r[5] != T("rules.sharding.r_datastream_small_rollover.11"), r[0]))
    return [Finding(
        "OVS-002", CAT, Severity.WARNING if age_only else Severity.INFO, T("rules.sharding.r_datastream_small_rollover.01"),
        observed=T("rules.sharding.r_datastream_small_rollover.02")
                 % (ctx.t["ds_small_backing_shard_gb"], len(rows)) + T("rules.sharding.r_datastream_small_rollover.12") % len(age_only),
        impact=T("rules.sharding.r_datastream_small_rollover.03"),
        recommend=T("rules.sharding.r_datastream_small_rollover.04"),
        evidence=table(["data stream", T("rules.sharding.r_datastream_small_rollover.05"), T("rules.sharding.r_datastream_small_rollover.06"), T("rules.sharding.r_datastream_small_rollover.07"), T("rules.sharding.r_datastream_small_rollover.08"), T("rules.sharding.r_datastream_small_rollover.09")],
                       rows[: ctx.t["top_n"]]),
        refs=[D_SHARDS], source="data_stream.json / indices_stats.json")]


def r_shard_size_distribution(ctx):
    """Reports the size distribution of user index primary shards (<1GB / 1-10GB / 10-50GB / 50GB+) as plain facts.

    If user primaries with data (at least 1 document; searchable snapshot mounts and write indices excluded) number oversharding_min_shards or more,
    the share under 10GB is >= oversharding_small_share_warn, and the total user data is at least oversharding_min_data_gb,
    it is a Warning for a 'cluster-wide oversharding trend'. If the conditions are not met, only the distribution is shown as Info.
    """
    skip = _write_indices(ctx)
    buckets = collections.OrderedDict([("<1GB", 0), ("1~10GB", 0), ("10~50GB", 0), (T("rules.sharding.r_shard_size_distribution.01"), 0)])
    total_b, n, n_small = 0, 0, 0
    for s in ctx.shards:
        if (s.get("prirep") or "").lower() != "p":
            continue
        idx = s.get("index")
        if ctx.is_system_index(idx) or idx in skip or ctx.is_searchable_snapshot(idx):
            continue
        try:
            docs = int(str(num(s, "docs")))
            b = parse_bytes(s.get("store")) or 0      # handles both a byte count and unit notation such as 1.2gb
        except ValueError:
            continue
        if docs <= 0:
            continue
        n += 1
        total_b += b
        if b < GB:
            buckets["<1GB"] += 1
        elif b < 10 * GB:
            buckets["1~10GB"] += 1
        elif b <= 50 * GB:
            buckets["10~50GB"] += 1
        else:
            buckets[T("rules.sharding.r_shard_size_distribution.01")] += 1
        if b < 10 * GB:
            n_small += 1
    if not n:
        return []
    ev = table([T("rules.sharding.r_shard_size_distribution.02"), T("rules.sharding.r_shard_size_distribution.03"), T("rules.sharding.r_shard_size_distribution.04")],
               [[k, fmt_num(v), "%.0f%%" % (v * 100.0 / n)] for k, v in buckets.items()])
    share = n_small / float(n)
    if (n >= ctx.t["oversharding_min_shards"] and share >= ctx.t["oversharding_small_share_warn"]
            and total_b >= ctx.t["oversharding_min_data_gb"] * GB):
        return [Finding(
            "OVS-003", CAT, Severity.WARNING, T("rules.sharding.r_shard_size_distribution.05"),
            observed=T("rules.sharding.r_shard_size_distribution.06")
                     % (fmt_num(n), share * 100, fmt_bytes(total_b)),
            impact=T("rules.sharding.r_shard_size_distribution.07"),
            recommend=T("rules.sharding.r_shard_size_distribution.08"),
            evidence=ev, refs=[D_SHARDS], source="indices.json")]
    return [Finding("OVS-003", CAT, Severity.INFO, T("rules.sharding.r_shard_size_distribution.09"),
                    observed=T("rules.sharding.r_shard_size_distribution.10")
                             % (fmt_num(n), fmt_bytes(total_b), share * 100),
                    evidence=ev, refs=[D_SHARDS], source="indices.json")]


RULES = [r_index_oversharding, r_datastream_small_rollover, r_shard_size_distribution]
