# -*- coding: utf-8 -*-
"""Comparison of two diagnostics bundles (diff).

A single bundle holds cumulative counters, so it can only say "the value is not 0".
Comparing with an earlier bundle of the same cluster shows whether a counter is still increasing,
and disk and shard growth rates give an estimate of when capacity runs out.
"""

import collections

from .i18n import T
from .model import Finding, Severity, table
from .util import dig, fmt_bytes, fmt_ms, fmt_num, num, items

CAT = "trend"


def _elapsed_hours(base, cur):
    if not base.collection_time or not cur.collection_time:
        return None
    try:
        sec = (cur.collection_time - base.collection_time).total_seconds()
    except TypeError:
        return None
    return sec / 3600.0 if sec > 0 else None


def _node_map(ctx):
    return dict((n.name, n) for n in ctx.nodes)


def _tp_rejected(node):
    out = collections.Counter()
    for pool, st in items(dig(node.stats, "thread_pool")):
        r = num(st, "rejected")
        if r:
            out[pool] += r
    return out


def _breaker_tripped(node):
    out = collections.Counter()
    for name, br in items(dig(node.stats, "breakers")):
        t = num(br, "tripped")
        if t:
            out[name] += t
    return out


def _per_hour(delta, hours):
    if hours is None or hours <= 0:
        return None
    return delta / hours


def summary(base, cur, hours):
    """Comparison summary shown at the top of the report."""
    def idx_count(ctx):
        return dig(ctx.cluster_stats, "indices", "count") or len(ctx.indices_stats)

    def store(ctx):
        return num(ctx.cluster_stats, "indices", "store", "size_in_bytes")

    rows = [
        (T("diff.summary.01"), base.collection_time.isoformat() if base.collection_time else "-",
         cur.collection_time.isoformat() if cur.collection_time else "-",
         (T("diff.summary.02") % hours) if hours else T("diff.summary.03")),
        (T("diff.summary.04"), base.health.get("status"), cur.health.get("status"), ""),
        (T("diff.summary.05"), base.version, cur.version, ""),
        (T("diff.summary.06"), len(base.nodes), len(cur.nodes),
         _sign(len(cur.nodes) - len(base.nodes))),
        (T("diff.summary.07"), fmt_num(idx_count(base)), fmt_num(idx_count(cur)),
         _sign(idx_count(cur) - idx_count(base))),
        (T("diff.summary.08"), fmt_num(base.health.get("active_shards")),
         fmt_num(cur.health.get("active_shards")),
         _sign((num(cur.health, "active_shards")) - (num(base.health, "active_shards")))),
        (T("diff.summary.09"), fmt_num(base.health.get("unassigned_shards")),
         fmt_num(cur.health.get("unassigned_shards")),
         _sign((num(cur.health, "unassigned_shards"))
               - (num(base.health, "unassigned_shards")))),
        (T("diff.summary.10"), fmt_bytes(store(base)), fmt_bytes(store(cur)),
         _sign_bytes(store(cur) - store(base))),
        (T("diff.summary.11"), fmt_num(dig(base.cluster_stats, "indices", "docs", "count")),
         fmt_num(dig(cur.cluster_stats, "indices", "docs", "count")),
         _sign((num(cur.cluster_stats, "indices", "docs", "count"))
               - (num(base.cluster_stats, "indices", "docs", "count")))),
    ]
    return {"columns": [T("diff.summary.12"), T("diff.summary.13"), T("diff.summary.14"), T("diff.summary.15")],
            "rows": [[a, b, c, d] for a, b, c, d in rows],
            "hours": hours}


def summary_with_nodes(base, cur, hours, t):
    out = summary(base, cur, hours)
    try:
        out["nodes"] = node_changes(base, cur, hours, t)
    except Exception:
        out["nodes"] = None
    return out


def _shard_counts(ctx):
    out = collections.Counter()
    for sh in ctx.shards:
        if sh.get("node"):
            out[sh["node"]] += 1
    return out


def _cell(b, c, fmt, noise):
    """'before → now ▲' or 'now =' when the change is within noise percent. None on either side shows '-'."""
    if c is None:
        return "-"
    if b is None:
        return fmt(c)
    base = abs(b) if b else 0.0
    if (b == c) or (base and abs(c - b) / base * 100.0 < noise) or (not base and not c):
        return "%s =" % fmt(c)
    return "%s → %s %s" % (fmt(b), fmt(c), "▲" if c > b else "▼")


def node_changes(base, cur, hours, t):
    """Per node, before and now for the main metrics (uptime, heap, CPU, load15, disk, shards, indexing and search rate,
    rejections, old GC). A change smaller than node_change_noise_pct percent is shown as '='. Indexing and search rates are
    the increase over the interval per second; a node that restarted in the interval (uptime went down) shows 'restarted'."""
    noise = t["node_change_noise_pct"]
    bm = _node_map(base)
    bs, cs = _shard_counts(base), _shard_counts(cur)
    pct = lambda v: "%.0f%%" % v
    plain = lambda v: "%.2f" % v if isinstance(v, float) and v < 10 else fmt_num(int(round(v)))
    rows = []
    for n in cur.nodes:
        b = bm.get(n.name)
        tier = cur.tier_of(n) or ("master" if n.is_master_eligible else "-")
        if b is None:
            rows.append([n.name, tier, T("diff.node.new")] + ["-"] * 9)
            continue
        reset = bool(b.uptime_ms and n.uptime_ms and n.uptime_ms < b.uptime_ms)
        sec = hours * 3600.0 if hours else None

        def rate(path):
            if reset:
                return T("diff.node.restarted")
            if not sec:
                return "-"
            d = num(n.stats, *path) - num(b.stats, *path)
            return "%.0f/s" % (max(0, d) / sec)
        rej_b, rej_c = sum(_tp_rejected(b).values()), sum(_tp_rejected(n).values())
        gc_b, gc_c = b.gc("old")[0], n.gc("old")[0]
        rows.append([
            n.name, tier,
            (fmt_ms(n.uptime_ms) + (" (%s)" % T("diff.node.restarted") if reset else "")) if n.uptime_ms else "-",
            _cell(b.heap_used_pct, n.heap_used_pct, pct, noise),
            _cell(b.cpu_pct, n.cpu_pct, pct, noise),
            _cell(b.load15, n.load15, plain, noise),
            _cell(b.disk_used_pct, n.disk_used_pct, pct, noise),
            _cell(float(bs.get(n.name, 0)), float(cs.get(n.name, 0)), plain, noise),
            rate(("indices", "indexing", "index_total")),
            rate(("indices", "search", "query_total")),
            T("diff.node.restarted") if reset else ("+%s" % fmt_num(max(0, rej_c - rej_b))),
            T("diff.node.restarted") if reset else ("+%s" % fmt_num(max(0, gc_c - gc_b))),
        ])
    cm = _node_map(cur)
    for name in bm:
        if name not in cm:
            rows.append([name, cur.tier_of(bm[name]) or "-", T("diff.node.left")] + ["-"] * 9)
    cols = ["node", "tier", "uptime", "heap%", "cpu%", "load15", "disk%", T("diff.node.shards"),
            T("diff.node.index_rate"), T("diff.node.search_rate"), T("diff.node.rejected"), "old GC"]
    return {"columns": cols, "rows": rows}


def _sign(v):
    if not v:
        return T("diff._sign.01")
    return ("+%s" % fmt_num(v)) if v > 0 else ("-%s" % fmt_num(abs(v)))


def _sign_bytes(v):
    if not v:
        return T("diff._sign_bytes.01")
    return ("+%s" % fmt_bytes(v)) if v > 0 else ("-%s" % fmt_bytes(abs(v)))


# ---------------------------------------------------------------- rules
def r_cluster_identity(base, cur, hours, t):
    """The two bundles come from different clusters (DIF-013, Warning): cluster_uuid differs, or, without a uuid,
    the cluster name differs and fewer than half of the node names overlap. The deltas are then not a trend of one cluster."""
    bu, cu = base.version_doc.get("cluster_uuid"), cur.version_doc.get("cluster_uuid")
    reasons = []
    if bu and cu and bu != cu:
        reasons.append(T("diff.r_cluster_identity.01") % (bu, cu))
    bn, cn = set(n.name for n in base.nodes), set(n.name for n in cur.nodes)
    overlap = len(bn & cn) / float(max(len(bn), len(cn), 1))
    if not (bu and cu) and base.cluster_name != cur.cluster_name and overlap < 0.5:
        reasons.append(T("diff.r_cluster_identity.02") % (base.cluster_name, cur.cluster_name, overlap * 100))
    if not reasons:
        return []
    return [Finding(
        "DIF-013", CAT, Severity.WARNING, T("diff.r_cluster_identity.03"),
        observed=" ".join(reasons),
        impact=T("diff.r_cluster_identity.04"),
        recommend=T("diff.r_cluster_identity.05"),
        source="version.json / nodes.json")]


def r_status_change(base, cur, hours, t):
    """When the cluster status differs between the two bundles. Worse -> critical, better -> info."""
    b, c = (base.health.get("status") or "").lower(), (cur.health.get("status") or "").lower()
    order = {"green": 0, "yellow": 1, "red": 2}
    if b == c:
        return []
    worse = order.get(c, 0) > order.get(b, 0)
    return [Finding(
        "DIF-001", CAT, Severity.CRITICAL if worse else Severity.INFO,
        T("diff.r_status_change.01") % (T("diff.r_status_change.02") if worse else T("diff.r_status_change.03")),
        observed="%s → %s" % (b or "-", c or "-"),
        impact=T("diff.r_status_change.04") if worse
               else T("diff.r_status_change.05"),
        recommend=T("diff.r_status_change.06") if worse else "",
        source=T("diff.r_status_change.07"))]


def r_node_restart(base, cur, hours, t):
    """Node with the same name has a smaller uptime than before -> critical (DIF-002, restart). Node left -> warning, only new -> info (DIF-003)."""
    bm, cm = _node_map(base), _node_map(cur)
    restarted, left, joined = [], [], []
    for name, n in cm.items():
        if name not in bm:
            joined.append(name)
            continue
        bu, cu = bm[name].uptime_ms, n.uptime_ms
        if bu and cu and cu < bu:
            restarted.append([name, fmt_ms(bu), fmt_ms(cu)])
    for name in bm:
        if name not in cm:
            left.append(name)
    out = []
    if restarted:
        out.append(Finding(
            "DIF-002", CAT, Severity.CRITICAL, T("diff.r_node_restart.01"),
            observed=T("diff.r_node_restart.02") % len(restarted),
            impact=T("diff.r_node_restart.03"),
            recommend=T("diff.r_node_restart.04"),
            evidence=table(["node", T("diff.r_node_restart.05"), T("diff.r_node_restart.06")], restarted),
            source=T("diff.r_node_restart.07")))
    if left or joined:
        out.append(Finding(
            "DIF-003", CAT, Severity.WARNING if left else Severity.INFO, T("diff.r_node_restart.08"),
            observed=T("diff.r_node_restart.09") % (len(left), len(joined)),
            impact=T("diff.r_node_restart.10"),
            recommend=T("diff.r_node_restart.11"),
            evidence=table([T("diff.r_node_restart.12"), T("diff.r_node_restart.13")],
                           [[T("diff.r_node_restart.14"), n] for n in left] + [[T("diff.r_node_restart.15"), n] for n in joined]),
            source=T("diff.r_node_restart.16")))
    return out


def r_rejections_delta(base, cur, hours, t):
    """Per node and pool increase in rejected. Total > 0 -> warning, >= rejected_crit -> critical (DIF-005). Cumulative value is not 0 but the increase is 0 -> info (DIF-004, past history)."""
    bm, cm = _node_map(base), _node_map(cur)
    rows, total = [], 0
    for name, n in cm.items():
        if name not in bm:
            continue
        b, c = _tp_rejected(bm[name]), _tp_rejected(n)
        for pool in set(list(b.keys()) + list(c.keys())):
            d = c[pool] - b[pool]
            if d > 0:
                total += d
                rate = _per_hour(d, hours)
                rows.append([name, pool, fmt_num(b[pool]), fmt_num(c[pool]), fmt_num(d),
                             ("%.0f/h" % rate) if rate else "-"])
    if not rows:
        if any(_tp_rejected(n) for n in cm.values()):
            return [Finding(
                "DIF-004", CAT, Severity.INFO, T("diff.r_rejections_delta.01"),
                observed=T("diff.r_rejections_delta.02"),
                impact=T("diff.r_rejections_delta.03"),
                recommend=T("diff.r_rejections_delta.04"),
                source=T("diff.r_rejections_delta.05"))]
        return []
    rows.sort(key=lambda r: -int(str(r[4]).replace(",", "")))
    return [Finding(
        "DIF-005", CAT, Severity.CRITICAL if total >= t["rejected_crit"] else Severity.WARNING,
        T("diff.r_rejections_delta.06"),
        observed=T("diff.r_rejections_delta.07") % (
            fmt_num(total), (T("diff.r_rejections_delta.08") % _per_hour(total, hours)) if hours else ""),
        impact=T("diff.r_rejections_delta.09"),
        recommend=T("diff.r_rejections_delta.10"),
        evidence=table(["node", "pool", T("diff.r_rejections_delta.11"), T("diff.r_rejections_delta.12"), T("diff.r_rejections_delta.13"), T("diff.r_rejections_delta.14")], rows[: t["top_n"]]),
        source=T("diff.r_rejections_delta.05"))]


def r_gc_delta(base, cur, hours, t):
    """Increase in old GC. Per-hour increase >= old_gc_per_hour_warn or GC time share of the interval >= old_gc_time_ratio_warn -> warning, otherwise info. Nodes whose counter went down (restart) are skipped."""
    bm, cm = _node_map(base), _node_map(cur)
    rows, bad = [], False
    for name, n in cm.items():
        if name not in bm:
            continue
        bc, bt = bm[name].gc("old")
        cc, ct = n.gc("old")
        if cc < bc:          # counter reset by restart
            continue
        dc, dt = cc - bc, ct - bt
        if dc <= 0:
            continue
        rate = _per_hour(dc, hours)
        ratio = (dt / (hours * 3600000.0) * 100) if hours else None
        rows.append([name, fmt_num(dc), fmt_ms(dt),
                     (T("diff.r_gc_delta.01") % rate) if rate else "-",
                     ("%.2f%%" % ratio) if ratio is not None else "-"])
        if rate and rate >= t["old_gc_per_hour_warn"]:
            bad = True
        if ratio is not None and ratio >= t["old_gc_time_ratio_warn"] * 100:
            bad = True
    if not rows:
        return []
    return [Finding(
        "DIF-006", CAT, Severity.WARNING if bad else Severity.INFO,
        T("diff.r_gc_delta.02"),
        observed=T("diff.r_gc_delta.03") % len(rows),
        impact=T("diff.r_gc_delta.04"),
        recommend=T("diff.r_gc_delta.05"),
        evidence=table(["node", T("diff.r_gc_delta.06"), T("diff.r_gc_delta.07"), T("diff.r_gc_delta.08"), T("diff.r_gc_delta.09")], rows),
        source=T("diff.r_gc_delta.10"))]


def r_breaker_delta(base, cur, hours, t):
    """Increase in breaker tripped > 0 -> critical."""
    bm, cm = _node_map(base), _node_map(cur)
    rows, total = [], 0
    for name, n in cm.items():
        if name not in bm:
            continue
        b, c = _breaker_tripped(bm[name]), _breaker_tripped(n)
        for k in set(list(b.keys()) + list(c.keys())):
            d = c[k] - b[k]
            if d > 0:
                total += d
                rows.append([name, k, fmt_num(b[k]), fmt_num(c[k]), fmt_num(d)])
    if not rows:
        return []
    return [Finding(
        "DIF-007", CAT, Severity.CRITICAL, T("diff.r_breaker_delta.01"),
        observed=T("diff.r_breaker_delta.02") % fmt_num(total),
        impact=T("diff.r_breaker_delta.03"),
        recommend=T("diff.r_breaker_delta.04"),
        evidence=table(["node", "breaker", T("diff.r_breaker_delta.05"), T("diff.r_breaker_delta.06"), T("diff.r_breaker_delta.07")], rows),
        source=T("diff.r_breaker_delta.08"))]


def r_disk_projection(base, cur, hours, t):
    """Estimates when the watermark is reached from the disk growth rate."""
    if not hours or hours < t["diff_min_hours_for_projection"]:
        return []
    bm, cm = _node_map(base), _node_map(cur)
    rows, soon = [], []
    for name, n in cm.items():
        if name not in bm or not n.is_data or cur.is_frozen_only(n):
            continue        # frozen-only nodes pre-allocate the shared cache, so growth rate extrapolation does not apply
        ba = bm[name].fs_avail
        ct, ca = n.fs_total, n.fs_avail
        if not ct or ba is None or ca is None:
            continue
        growth = (ba - ca)                      # shrinking free space
        rate = growth / hours                   # bytes/hour
        used_pct = (1 - ca / float(ct)) * 100
        high = cur.watermark_used_pct("high", ct) or 90.0
        head = (high / 100.0 * ct) - (ct - ca)  # bytes left until high
        if head <= 0:
            label, days = T("diff.r_disk_projection.01"), None
        elif rate > 0:
            days = head / rate / 24.0
            label = T("diff.r_disk_projection.02") % days
        else:
            label, days = T("diff.r_disk_projection.03"), None
        rows.append([name, "%.1f%%" % used_pct, fmt_bytes(rate) + "/h", label, "%.0f%%" % high])
        if days is not None and days <= t["disk_projection_days_warn"]:
            soon.append((name, days))
    if not rows:
        return []
    sev = Severity.CRITICAL if any(d <= 7 for _, d in soon) else (
        Severity.WARNING if soon else Severity.INFO)
    return [Finding(
        "DIF-008", CAT, sev, T("diff.r_disk_projection.04"),
        observed=T("diff.r_disk_projection.05") % (
            ", ".join("%s %s" % (r[0], r[3]) for r in rows) or T("diff.r_disk_projection.06")),
        impact=T("diff.r_disk_projection.07"),
        recommend=T("diff.r_disk_projection.08"),
        evidence=table(["node", T("diff.r_disk_projection.09"), T("diff.r_disk_projection.10"), T("diff.r_disk_projection.11"), T("diff.r_disk_projection.12")], rows),
        source=T("diff.r_disk_projection.13"))]


def r_throughput(base, cur, hours, t):
    """Converts the per-node increase in index_total / query_total over the interval to throughput per second (replica work included).

    Only data nodes are counted. The skew is compared within each tier: busiest node / tier average >= workload_skew_ratio_warn -> warning,
    otherwise info. A node that restarted during the interval (uptime went down) has reset counters, so it is shown but left out of
    the totals and the skew.
    """
    if not hours:
        return []
    bm = _node_map(base)
    rows, skews, restarted = [], [], []
    tot_idx = tot_qry = 0
    per_tier = collections.OrderedDict()
    for n in cur.data_nodes:
        name = n.name
        if name not in bm:
            continue
        bu, cu = bm[name].uptime_ms, n.uptime_ms
        reset = bool(bu and cu and cu < bu)
        bi = num(bm[name].stats, "indices", "indexing", "index_total")
        ci = num(n.stats, "indices", "indexing", "index_total")
        bq = num(bm[name].stats, "indices", "search", "query_total")
        cq = num(n.stats, "indices", "search", "query_total")
        di, dq = max(0, ci - bi), max(0, cq - bq)
        tier = cur.tier_of(n) or "-"
        if reset:
            restarted.append(name)
            rows.append([name, tier, "-", "-", "-", "-"])
            continue
        tot_idx += di
        tot_qry += dq
        per_tier.setdefault(tier, []).append(di)
        rows.append([name, tier, fmt_num(di), "%.0f/s" % (di / (hours * 3600)),
                     fmt_num(dq), "%.0f/s" % (dq / (hours * 3600))])
    if not rows or (tot_idx + tot_qry) == 0:
        return []
    for tier, vals in per_tier.items():
        avg = sum(vals) / float(len(vals)) if len(vals) >= 2 else 0
        if avg and max(vals) / avg >= t["workload_skew_ratio_warn"]:
            skews.append(T("diff.r_throughput.11") % (tier, max(vals) / avg))
    note = (T("diff.r_throughput.12") % ", ".join(restarted)) if restarted else ""
    return [Finding(
        "DIF-009", CAT,
        Severity.WARNING if skews else Severity.INFO,
        T("diff.r_throughput.01"),
        observed=T("diff.r_throughput.02") % (
            fmt_num(tot_idx), tot_idx / (hours * 3600),
            fmt_num(tot_qry), tot_qry / (hours * 3600),
            (" " + " / ".join(skews)) if skews else "") + note,
        impact=T("diff.r_throughput.04"),
        recommend=T("diff.r_throughput.05"),
        evidence=table(["node", "tier", T("diff.r_throughput.06"), T("diff.r_throughput.07"), T("diff.r_throughput.08"), T("diff.r_throughput.09")], rows),
        source=T("diff.r_throughput.10"))]


def r_index_growth(base, cur, hours, t):
    """Increase in index primary store > index_growth_min_bytes -> info (DIF-010). User indices added or deleted -> info (DIF-011)."""
    rows, new_idx, gone = [], [], []
    bset = set(base.indices_stats.keys())
    cset = set(cur.indices_stats.keys())
    for name in cset - bset:
        if not cur.is_system_index(name):
            new_idx.append(name)
    for name in bset - cset:
        if not base.is_system_index(name):
            gone.append(name)
    for name in cset & bset:
        b = num(base.indices_stats, name, "primaries", "store", "size_in_bytes")
        c = num(cur.indices_stats, name, "primaries", "store", "size_in_bytes")
        d = c - b
        if d > t["index_growth_min_bytes"]:
            rate = _per_hour(d, hours)
            rows.append([name, fmt_bytes(b), fmt_bytes(c), fmt_bytes(d),
                         (fmt_bytes(rate) + "/h") if rate else "-", d])
    out = []
    if rows:
        rows.sort(key=lambda r: -r[5])
        out.append(Finding(
            "DIF-010", CAT, Severity.INFO, T("diff.r_index_growth.01"),
            observed=T("diff.r_index_growth.02") % (len(rows), rows[0][3]),
            impact=T("diff.r_index_growth.03"),
            recommend=T("diff.r_index_growth.04"),
            evidence=table(["index", T("diff.r_index_growth.05"), T("diff.r_index_growth.06"), T("diff.r_index_growth.07"), T("diff.r_index_growth.08")],
                           [r[:5] for r in rows[: t["top_n"]]]),
            source=T("diff.r_index_growth.09")))
    if new_idx or gone:
        out.append(Finding(
            "DIF-011", CAT, Severity.INFO, T("diff.r_index_growth.10"),
            observed=T("diff.r_index_growth.11") % (len(new_idx), len(gone)),
            impact=T("diff.r_index_growth.12"),
            recommend=T("diff.r_index_growth.13"),
            evidence=table([T("diff.r_index_growth.14"), T("diff.r_index_growth.15")],
                           [[T("diff.r_index_growth.16"), n] for n in new_idx[: t["top_n"]]]
                           + [[T("diff.r_index_growth.17"), n] for n in gone[: t["top_n"]]]),
            source=T("diff.r_index_growth.09")))
    return out


def r_interval_rates(series, t):
    """Throughput per interval when three or more bundles are given (DIF-014): peak and off-peak.

    The bundles are sorted by collection time and every consecutive pair is one interval. For each interval the increase in
    index_total and query_total of the data nodes is turned into operations per second (replica work included). A node whose uptime
    went down in the interval restarted, so it is left out of that interval. The busiest interval by indexing rate is the peak,
    the quietest the off-peak, and their ratio is shown. The per data node rate at the peak is what sizing needs.
    Info only.
    """
    rows, rates = [], []
    for a, b in zip(series, series[1:]):
        hours = _elapsed_hours(a, b)
        if not hours:
            continue
        am = _node_map(a)
        di = dq = 0
        nodes, skipped = 0, 0
        for n in b.data_nodes:
            p = am.get(n.name)
            if p is None:
                continue
            if p.uptime_ms and n.uptime_ms and n.uptime_ms < p.uptime_ms:
                skipped += 1
                continue
            di += max(0, num(n.stats, "indices", "indexing", "index_total") - num(p.stats, "indices", "indexing", "index_total"))
            dq += max(0, num(n.stats, "indices", "search", "query_total") - num(p.stats, "indices", "search", "query_total"))
            nodes += 1
        if not nodes:
            continue
        sec = hours * 3600.0
        ir, qr = di / sec, dq / sec
        label = "%s → %s" % (a.collection_time.strftime("%m-%d %H:%M"), b.collection_time.strftime("%m-%d %H:%M"))
        rates.append((ir, qr, label, nodes))
        rows.append([label, "%.1f" % hours, "%.0f" % ir, "%.0f" % (ir / nodes), "%.0f" % qr, "%.0f" % (qr / nodes),
                     nodes, skipped])
    if len(rates) < 2:
        return []
    peak = max(rates, key=lambda r: r[0])
    low = min(rates, key=lambda r: r[0])
    ratio = (peak[0] / low[0]) if low[0] else None
    qpeak = max(rates, key=lambda r: r[1])
    return [Finding(
        "DIF-014", CAT, Severity.INFO, T("diff.r_interval_rates.01"),
        observed=T("diff.r_interval_rates.02") % (
            len(rates), peak[2], peak[0], peak[0] / peak[3], low[2], low[0],
            ("%.1f" % ratio) if ratio else "-", qpeak[2], qpeak[1], qpeak[1] / qpeak[3]),
        impact=T("diff.r_interval_rates.03"),
        recommend=T("diff.r_interval_rates.04"),
        evidence=table([T("diff.r_interval_rates.05"), T("diff.r_interval_rates.06"), T("diff.r_interval_rates.07"),
                        T("diff.r_interval_rates.08"), T("diff.r_interval_rates.09"), T("diff.r_interval_rates.10"),
                        T("diff.r_interval_rates.11"), T("diff.r_interval_rates.12")], rows),
        source=T("diff.r_interval_rates.13"))]


r_interval_rates.series = True       # takes the whole series of bundles, run by the engine, not by compare()

DIFF_RULES = [r_cluster_identity, r_status_change, r_node_restart, r_rejections_delta, r_gc_delta,
              r_breaker_delta, r_disk_projection, r_throughput, r_index_growth, r_interval_rates]


def compare(base, cur, thresholds, base_findings=None, cur_findings=None):
    """Returns (summary dict, [Finding])."""
    hours = _elapsed_hours(base, cur)
    findings = []
    for fn in DIFF_RULES:
        if getattr(fn, "series", False):
            continue
        try:
            findings.extend(fn(base, cur, hours, thresholds) or [])
        except Exception:
            continue
    if base_findings is not None and cur_findings is not None:
        findings.extend(_finding_delta(base_findings, cur_findings))
    return summary_with_nodes(base, cur, hours, thresholds), findings


def _finding_delta(base_findings, cur_findings):
    """Findings that are new or resolved compared with the earlier bundle."""
    sev_rank = Severity.ORDER
    bmap = dict((f.id, f) for f in base_findings
                if f.severity in (Severity.CRITICAL, Severity.WARNING))
    cmap = dict((f.id, f) for f in cur_findings
                if f.severity in (Severity.CRITICAL, Severity.WARNING))
    new = [cmap[k] for k in cmap if k not in bmap]
    fixed = [bmap[k] for k in bmap if k not in cmap]
    worse = [cmap[k] for k in cmap
             if k in bmap and sev_rank[cmap[k].severity] < sev_rank[bmap[k].severity]]
    if not (new or fixed or worse):
        return []
    rows = ([[T("diff._finding_delta.01"), f.id, f.title] for f in new]
            + [[T("diff._finding_delta.02"), f.id, f.title] for f in worse]
            + [[T("diff._finding_delta.03"), f.id, f.title] for f in fixed])
    # This is a summary of other findings, so it has no severity of its own (avoids double counting in score and counts).
    return [Finding(
        "DIF-012", CAT, Severity.INFO, T("diff._finding_delta.04"),
        observed=T("diff._finding_delta.05") % (len(new), len(worse), len(fixed)),
        impact=T("diff._finding_delta.06"),
        recommend=T("diff._finding_delta.07"),
        evidence=table([T("diff._finding_delta.08"), T("diff._finding_delta.09"), T("diff._finding_delta.10")], rows),
        source=T("diff._finding_delta.11"))]
