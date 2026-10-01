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


def _sign(v):
    if not v:
        return T("diff._sign.01")
    return ("+%s" % fmt_num(v)) if v > 0 else ("-%s" % fmt_num(abs(v)))


def _sign_bytes(v):
    if not v:
        return T("diff._sign_bytes.01")
    return ("+%s" % fmt_bytes(v)) if v > 0 else ("-%s" % fmt_bytes(abs(v)))


# ---------------------------------------------------------------- rules
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
    """Converts the per-node increase in index_total / query_total over the interval to throughput per second (replica work included). Max node / average >= workload_skew_ratio_warn -> warning, otherwise info."""
    if not hours:
        return []
    bm, cm = _node_map(base), _node_map(cur)
    rows = []
    tot_idx = tot_qry = 0
    for name, n in cm.items():
        if name not in bm:
            continue
        bi = num(bm[name].stats, "indices", "indexing", "index_total")
        ci = num(n.stats, "indices", "indexing", "index_total")
        bq = num(bm[name].stats, "indices", "search", "query_total")
        cq = num(n.stats, "indices", "search", "query_total")
        di, dq = max(0, ci - bi), max(0, cq - bq)
        tot_idx += di
        tot_qry += dq
        rows.append([name, fmt_num(di), "%.0f/s" % (di / (hours * 3600)),
                     fmt_num(dq), "%.0f/s" % (dq / (hours * 3600))])
    if not rows or (tot_idx + tot_qry) == 0:
        return []
    avg_i = tot_idx / float(len(rows))
    skew = (max(int(str(r[1]).replace(",", "")) for r in rows) / avg_i) if avg_i else 0
    return [Finding(
        "DIF-009", CAT,
        Severity.WARNING if skew >= t["workload_skew_ratio_warn"] else Severity.INFO,
        T("diff.r_throughput.01"),
        observed=T("diff.r_throughput.02") % (
            fmt_num(tot_idx), tot_idx / (hours * 3600),
            fmt_num(tot_qry), tot_qry / (hours * 3600),
            (T("diff.r_throughput.03") % skew)
            if skew >= t["workload_skew_ratio_warn"] else ""),
        impact=T("diff.r_throughput.04"),
        recommend=T("diff.r_throughput.05"),
        evidence=table(["node", T("diff.r_throughput.06"), T("diff.r_throughput.07"), T("diff.r_throughput.08"), T("diff.r_throughput.09")], rows),
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


DIFF_RULES = [r_status_change, r_node_restart, r_rejections_delta, r_gc_delta,
              r_breaker_delta, r_disk_projection, r_throughput, r_index_growth]


def compare(base, cur, thresholds, base_findings=None, cur_findings=None):
    """Returns (summary dict, [Finding])."""
    hours = _elapsed_hours(base, cur)
    findings = []
    for fn in DIFF_RULES:
        try:
            findings.extend(fn(base, cur, hours, thresholds) or [])
        except Exception:
            continue
    if base_findings is not None and cur_findings is not None:
        findings.extend(_finding_delta(base_findings, cur_findings))
    return summary(base, cur, hours), findings


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
