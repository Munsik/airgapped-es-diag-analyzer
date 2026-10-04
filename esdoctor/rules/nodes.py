# -*- coding: utf-8 -*-
"""Node-level rules (JVM / OS / disk / thread pools / breakers)."""

import collections

from ..i18n import T, N_
from ..model import Finding, Severity, table
from ..util import dig, fmt_bytes, fmt_ms, fmt_num, pct, dicts, num, items

CAT = "node"
DOC_HEAP = (N_("rules.nodes._.01"),
            "https://www.elastic.co/docs/reference/elasticsearch/jvm-settings")
DOC_DISK = (N_("rules.nodes._.02"),
            "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings")
DOC_TP = (N_("rules.nodes._.03"),
          "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings")


def r_heap_usage(ctx):
    """JVM memory pressure per node: old generation pool used / max (jvm.mem.pools.old), the measure the official docs use.
    >= heap_used_pct_crit (85, official: act when memory pressure stays above 85%) → Critical, >= heap_used_pct_warn (75, the
    level at which Elastic Cloud shows memory pressure in red) → Warning, otherwise OK. heap_used_percent at one moment also counts
    young generation garbage, so it is only shown; it is used for the rating only when the old pool is not reported."""
    rows, warn, crit = [], [], []
    for n in ctx.nodes:
        used = n.memory_pressure_pct
        if used is None:
            continue
        hp = n.heap_used_pct
        rows.append([n.name, "%.0f%%" % used, ("%s%%" % hp) if hp is not None else "-", fmt_bytes(n.heap_used),
                     fmt_bytes(n.heap_max), fmt_bytes(n.ram_total), ",".join(n.roles)])
        if used >= ctx.t["heap_used_pct_crit"]:
            crit.append(n.name)
        elif used >= ctx.t["heap_used_pct_warn"]:
            warn.append(n.name)
    if not rows:
        return []
    if crit:
        return [Finding(
            "JVM-001", CAT, Severity.CRITICAL, T("rules.nodes.r_heap_usage.01"),
            observed=T("rules.nodes.r_heap_usage.02") % (ctx.t["heap_used_pct_crit"], ", ".join(crit)),
            impact=T("rules.nodes.r_heap_usage.03"),
            recommend=T("rules.nodes.r_heap_usage.04"),
            evidence=table(["node", T("rules.nodes.r_heap_usage.10"), "heap%", "used", "max", "RAM", "roles"], rows),
            affected=crit, refs=[DOC_HEAP], source="nodes_stats.json")]
    if warn:
        return [Finding(
            "JVM-001", CAT, Severity.WARNING, T("rules.nodes.r_heap_usage.05"),
            observed=T("rules.nodes.r_heap_usage.02") % (ctx.t["heap_used_pct_warn"], ", ".join(warn)),
            impact=T("rules.nodes.r_heap_usage.06"),
            recommend=T("rules.nodes.r_heap_usage.07"),
            evidence=table(["node", T("rules.nodes.r_heap_usage.10"), "heap%", "used", "max", "RAM", "roles"], rows),
            affected=warn, refs=[DOC_HEAP], source="nodes_stats.json")]
    return [Finding("JVM-001", CAT, Severity.OK, T("rules.nodes.r_heap_usage.08"),
                    observed=T("rules.nodes.r_heap_usage.09") % ctx.t["heap_used_pct_warn"],
                    evidence=table(["node", T("rules.nodes.r_heap_usage.10"), "heap%", "used", "max", "RAM", "roles"], rows),
                    source="nodes_stats.json")]


def r_heap_sizing(ctx):
    """Compressed oops, heap versus RAM, and Xms versus Xmx (JVM-002 to 004).

    JVM-002 rests on the flag the JVM reports (nodes.json jvm.using_compressed_ordinary_object_pointers): false → Warning, true → fine
    whatever the heap size. Only when the flag is missing is the heap size used: the official docs say 26GB is safe on most systems
    and the boundary can be as high as about 30GB, so heap >= heap_max_bytes_crit (30GiB) → Warning and >= heap_oops_safe_bytes
    (26GiB) → Info.
    heap_max / os.mem.adjusted_total > heap_vs_ram_pct_warn + heap_vs_ram_tolerance_pct → Warning (JVM-003). heap_init (Xms) != heap_max (Xmx) → Warning (JVM-004).
    """
    out, rows = [], []
    oops_off, oversize, near, mismatch, too_big_vs_ram = [], [], [], [], []
    for n in ctx.nodes:
        hm, ram, hi = n.heap_max, n.ram_total, n.heap_init
        oops = dig(n.info, "jvm", "using_compressed_ordinary_object_pointers")
        ratio = pct(hm, ram)
        rows.append([n.name, fmt_bytes(hm), fmt_bytes(hi), fmt_bytes(ram),
                     "%.0f%%" % ratio if ratio else "-", str(oops)])
        flag = str(oops).lower() if oops is not None else ""
        if flag == "false":
            oops_off.append(n.name)
        elif flag != "true" and hm:
            if hm >= ctx.t["heap_max_bytes_crit"]:
                oversize.append(n.name)
            elif hm >= ctx.t["heap_oops_safe_bytes"]:
                near.append(n.name)
        if hm and hi and hm != hi:
            mismatch.append(n.name)
        if ratio and ratio > ctx.t["heap_vs_ram_pct_warn"] + ctx.t["heap_vs_ram_tolerance_pct"]:
            too_big_vs_ram.append(n.name)
    ev = table(["node", "heap_max", "heap_init(Xms)", "RAM", "heap/RAM", "compressed_oops"], rows)
    if oops_off or oversize or near:
        targets = sorted(set(oops_off) | set(oversize) | set(near))
        obs = []
        if oops_off:
            obs.append(T("rules.nodes.r_heap_sizing.12") % ", ".join(oops_off))
        if oversize:
            obs.append(T("rules.nodes.r_heap_sizing.13") % (fmt_bytes(ctx.t["heap_max_bytes_crit"]), ", ".join(oversize)))
        if near:
            obs.append(T("rules.nodes.r_heap_sizing.14") % (fmt_bytes(ctx.t["heap_oops_safe_bytes"]), ", ".join(near)))
        out.append(Finding(
            "JVM-002", CAT, Severity.WARNING if (oops_off or oversize) else Severity.INFO,
            T("rules.nodes.r_heap_sizing.01"),
            observed=" / ".join(obs),
            impact=T("rules.nodes.r_heap_sizing.03"),
            recommend=T("rules.nodes.r_heap_sizing.04"),
            evidence=ev, affected=targets, refs=[DOC_HEAP], source="nodes.json / nodes_stats.json"))
    if too_big_vs_ram:
        out.append(Finding(
            "JVM-003", CAT, Severity.WARNING, T("rules.nodes.r_heap_sizing.05"),
            observed=T("rules.nodes.r_heap_sizing.06")
                     % (ctx.t["heap_vs_ram_pct_warn"], ", ".join(too_big_vs_ram)),
            impact=T("rules.nodes.r_heap_sizing.07"),
            recommend=T("rules.nodes.r_heap_sizing.08"),
            evidence=ev, affected=too_big_vs_ram, refs=[DOC_HEAP], source="nodes.json"))
    if mismatch:
        out.append(Finding(
            "JVM-004", CAT, Severity.WARNING, T("rules.nodes.r_heap_sizing.09"),
            observed=T("rules.nodes.r_heap_sizing.02") % ", ".join(mismatch),
            impact=T("rules.nodes.r_heap_sizing.10"),
            recommend=T("rules.nodes.r_heap_sizing.11"),
            evidence=ev, affected=mismatch, source="nodes.json"))
    return out


def r_gc(ctx):
    """old share = old collection_time / uptime, old GC per hour = old count / uptime (h), young share = young time / uptime. old share >= old_gc_time_ratio_crit or per-hour >= old_gc_per_hour_crit → Critical. Any of old share >= warn, per-hour >= warn, or young share >= young_gc_time_ratio_warn → Warning. Otherwise OK. These are cumulative values, so compare mode (DIF-006) is more accurate."""
    rows, warn, crit = [], [], []
    for n in ctx.nodes:
        up = n.uptime_ms or 0
        oc, ot = n.gc("old")
        yc, yt = n.gc("young")
        if not up:
            continue
        old_ratio = ot / float(up) if up else 0
        young_ratio = yt / float(up) if up else 0
        old_per_hour = oc / (up / 3600000.0) if up else 0
        rows.append([n.name, fmt_ms(up), fmt_num(oc), fmt_ms(ot), "%.3f%%" % (old_ratio * 100),
                     fmt_num(yc), fmt_ms(yt), "%.2f%%" % (young_ratio * 100),
                     "%.1f" % old_per_hour])
        if old_ratio >= ctx.t["old_gc_time_ratio_crit"] or old_per_hour >= ctx.t["old_gc_per_hour_crit"]:
            crit.append(n.name)
        elif (old_ratio >= ctx.t["old_gc_time_ratio_warn"]
              or old_per_hour >= ctx.t["old_gc_per_hour_warn"]
              or young_ratio >= ctx.t["young_gc_time_ratio_warn"]):
            warn.append(n.name)
    if not rows:
        return []
    ev = table(["node", "uptime", T("rules.nodes.r_gc.01"), T("rules.nodes.r_gc.02"), T("rules.nodes.r_gc.03"),
                T("rules.nodes.r_gc.04"), T("rules.nodes.r_gc.05"), T("rules.nodes.r_gc.06"), T("rules.nodes.r_gc.07")], rows)
    if crit:
        return [Finding(
            "JVM-005", CAT, Severity.CRITICAL, T("rules.nodes.r_gc.08"),
            observed=T("rules.nodes.r_gc.09") % ", ".join(crit),
            impact=T("rules.nodes.r_gc.10"),
            recommend=T("rules.nodes.r_gc.11"),
            evidence=ev, affected=crit, source="nodes_stats.json")]
    if warn:
        return [Finding(
            "JVM-005", CAT, Severity.WARNING, T("rules.nodes.r_gc.12"),
            observed=T("rules.nodes.r_gc.13") % ", ".join(warn),
            impact=T("rules.nodes.r_gc.14"),
            recommend=T("rules.nodes.r_gc.15"),
            evidence=ev, affected=warn, source="nodes_stats.json")]
    return [Finding("JVM-005", CAT, Severity.OK, T("rules.nodes.r_gc.16"),
                    observed=T("rules.nodes.r_gc.17")
                             % (ctx.t["old_gc_time_ratio_warn"] * 100),
                    evidence=ev, source="nodes_stats.json")]


def r_os(ctx):
    """load15 / available_processors >= load_per_cpu_crit → Critical, >= warn → Warning (OS-001, nodes in both ranges are listed). A container node (Elastic Cloud / ECE / ECK, or a cgroup CPU quota or memory limit) with cpu% below load_host_cpu_pct_max is not rated: inside a container the load average can be the host's, so it is listed as Info. On Linux the load average also counts processes waiting on disk, so high load with low CPU often points to storage. swap_total > 0 and mlockall is not true → Warning (OS-002). cgroup throttled / elapsed_periods >= cgroup_throttle_ratio_crit → Critical, >= warn → Warning (OS-003). open_fd / max_fd >= fd_used_pct_warn → Warning (OS-004). mlockall=false and no swap → Info (OS-005). uptime < uptime_short_hours → Warning (OS-006). restart_share_warn or more of the nodes restarted within uptime_short_hours → Warning (OS-007): cumulative counters (GC, rejections, cache, latency averages) then cover only a short window."""
    out = []
    rows, load_warn, load_crit, swap_on, throttle, load_host = [], [], [], [], [], []
    swap_used = []
    for n in ctx.nodes:
        cpus = n.processors or 0
        l1, l5, l15 = n.load1, n.load5, n.load15
        per = (l15 / cpus) if (l15 and cpus) else None
        rows.append([n.name, ctx.tier_of(n) or ("master" if n.is_master_eligible else ",".join(n.roles)),
                     fmt_num(cpus), n.cpu_pct if n.cpu_pct is not None else "-",
                     l1, l5, l15, ("%.2f" % per) if per else "-", fmt_bytes(n.swap_total)])
        in_container = ctx.in_container(n)
        if per is not None and per >= ctx.t["load_per_cpu_warn"] and in_container \
                and n.cpu_pct is not None and n.cpu_pct < ctx.t["load_host_cpu_pct_max"]:
            load_host.append(n.name)    # load average inside a container can be the host's; the node itself is idle
        elif per is not None:
            if per >= ctx.t["load_per_cpu_crit"]:
                load_crit.append(n.name)
            elif per >= ctx.t["load_per_cpu_warn"]:
                load_warn.append(n.name)
        # The official swap remedies are one of: (1) disable swap, (2) swappiness=1, (3) memory_lock.
        # With memory_lock applied the heap is never swapped, so do not warn.
        if n.swap_total and n.mlockall is not True:
            swap_on.append(n.name)
            su = num(n.stats, "os", "swap", "used_in_bytes")
            if su:
                swap_used.append(T("rules.nodes.r_os.01") % (n.name, fmt_bytes(su), fmt_bytes(n.swap_total)))
        elapsed = dig(n.stats, "os", "cgroup", "cpu", "stat", "number_of_elapsed_periods")
        thr = dig(n.stats, "os", "cgroup", "cpu", "stat", "number_of_times_throttled")
        if elapsed and thr:
            ratio = float(thr) / float(elapsed)
            if ratio >= ctx.t["cgroup_throttle_ratio_warn"]:
                throttle.append((n.name, ratio,
                                 dig(n.stats, "os", "cgroup", "cpu", "stat", "time_throttled_nanos")))
    ev = table(["node", T("rules.nodes.r_os.02"), T("rules.nodes.r_os.03"), "cpu%", "load1m", "load5m", "load15m", "load/cpu", "swap"], rows)
    if load_crit or load_warn:
        parts = []
        if load_crit:
            parts.append(T("rules.nodes.r_os.04") % (ctx.t["load_per_cpu_crit"], ", ".join(load_crit)))
        if load_warn:
            parts.append(T("rules.nodes.r_os.05") % (ctx.t["load_per_cpu_warn"], ", ".join(load_warn)))
        out.append(Finding(
            "OS-001", CAT, Severity.CRITICAL if load_crit else Severity.WARNING,
            T("rules.nodes.r_os.06"),
            observed=T("rules.nodes.r_os.07") + " / ".join(parts),
            impact=T("rules.nodes.r_os.08"),
            recommend=T("rules.nodes.r_os.09"),
            evidence=ev, affected=load_crit + load_warn, source="nodes_stats.json"))
    if load_host and not (load_crit or load_warn):
        out.append(Finding(
            "OS-001", CAT, Severity.INFO, T("rules.nodes.r_os.37"),
            observed=T("rules.nodes.r_os.38") % (ctx.t["load_host_cpu_pct_max"], ", ".join(load_host)),
            impact=T("rules.nodes.r_os.39"),
            recommend=T("rules.nodes.r_os.40"),
            evidence=ev, affected=load_host, source="nodes_stats.json"))
    elif load_host:
        out[-1].observed += T("rules.nodes.r_os.41") % ", ".join(load_host)
    if swap_on:
        out.append(Finding(
            "OS-002", CAT, Severity.WARNING, T("rules.nodes.r_os.10"),
            observed=T("rules.nodes.r_os.11") % ", ".join(swap_on)
                     + (T("rules.nodes.r_os.12") % ", ".join(swap_used) if swap_used else ""),
            impact=T("rules.nodes.r_os.13"),
            recommend=T("rules.nodes.r_os.14"),
            evidence=ev, affected=swap_on, source="nodes_stats.json"))
    if throttle:
        out.append(Finding(
            "OS-003", CAT,
            Severity.CRITICAL if any(r >= ctx.t["cgroup_throttle_ratio_crit"] for _, r, _ in throttle)
            else Severity.WARNING,
            T("rules.nodes.r_os.15"),
            observed=T("rules.nodes.r_os.16")
                     % ", ".join("%s(%.1f%%)" % (n, r * 100) for n, r, _ in throttle),
            impact=T("rules.nodes.r_os.17"),
            recommend=T("rules.nodes.r_os.42") if ctx.orchestrated else T("rules.nodes.r_os.18"),
            evidence=table(["node", T("rules.nodes.r_os.19"), T("rules.nodes.r_os.20")],
                           [[n, "%.2f%%" % (r * 100), fmt_num(t)] for n, r, t in throttle]),
            affected=[n for n, _r, _t in throttle], source="nodes_stats.json"))
    # File descriptors
    fd_rows, fd_bad = [], []
    for n in ctx.nodes:
        o, m = n.open_fd, n.max_fd
        p = pct(o, m)
        if p is None:
            continue
        fd_rows.append([n.name, fmt_num(o), fmt_num(m), "%.1f%%" % p])
        if p >= ctx.t["fd_used_pct_warn"]:
            fd_bad.append(n.name)
    if fd_bad:
        out.append(Finding(
            "OS-004", CAT, Severity.WARNING, T("rules.nodes.r_os.21"),
            observed=T("rules.nodes.r_os.22") % ", ".join(fd_bad),
            impact=T("rules.nodes.r_os.23"),
            recommend=T("rules.nodes.r_os.24"),
            evidence=table(["node", "open", "max", T("rules.nodes.r_os.25")], fd_rows),
            affected=fd_bad, source="nodes_stats.json"))
    # mlockall
    # With swap off there is nothing to protect against (the official docs list memory_lock as one of three swap remedies), and on
    # Elastic Cloud / ECE / ECK the platform owns the setting, so it is only reported on self-managed nodes.
    unlocked = [n.name for n in ctx.nodes if n.mlockall is False]
    if unlocked and not swap_on and not ctx.orchestrated:
        out.append(Finding(
            "OS-005", CAT, Severity.INFO, T("rules.nodes.r_os.26"),
            observed=T("rules.nodes.r_os.27") % ", ".join(unlocked),
            impact=T("rules.nodes.r_os.28"),
            recommend=T("rules.nodes.r_os.29"),
            source="nodes.json"))
    # Recent restart
    short = [(n.name, n.uptime_ms) for n in ctx.nodes
             if n.uptime_ms and n.uptime_ms < ctx.t["uptime_short_hours"] * 3600000]
    if short:
        out.append(Finding(
            "OS-006", CAT, Severity.WARNING, T("rules.nodes.r_os.30"),
            observed=", ".join("%s(uptime %s)" % (n, fmt_ms(u)) for n, u in short),
            impact=T("rules.nodes.r_os.31"),
            recommend=T("rules.nodes.r_os.32"),
            source="nodes_stats.json"))
    timed = [n for n in ctx.nodes if n.uptime_ms]
    if len(timed) >= 2 and len(short) >= len(timed) * ctx.t["restart_share_warn"]:
        out.append(Finding(
            "OS-007", CAT, Severity.WARNING, T("rules.nodes.r_os.33"),
            observed=T("rules.nodes.r_os.34") % (len(short), len(timed), ctx.t["uptime_short_hours"]),
            impact=T("rules.nodes.r_os.35"),
            recommend=T("rules.nodes.r_os.36"),
            affected=[n for n, _ in short], source="nodes_stats.json"))
    return out


def r_write_latency(ctx):
    """Average flush, refresh and merge time per node (nodes_stats indices.flush/refresh/merges total_time / total).

    Only nodes that actually index are rated: indexing rate of the node (indices.indexing.index_total per hour of uptime)
    >= write_node_index_share_min of the busiest data node. The hourly rate keeps a recently restarted node comparable. Holding a data stream write index is not enough, because a low-volume stream can keep an idle write index
    for months. On a node that does not index, merges come from a force merge (ILM forcemerge, the force merge that
    searchable_snapshot runs in the preceding phase by default, or a manual _forcemerge) or from merges finishing after rollover.
    Those merge large segments, so a long average there does not mean slow storage.
    Any metric with fewer than write_latency_min_ops operations is skipped. Merge time is wall-clock time that includes the time
    a merge was paused by merge I/O throttling or stopped, so throttled and stopped time are subtracted first.
    Average >= *_avg_ms_warn → Warning, >= *_avg_ms_info → Info (PERF-012). These are field baselines, not official numbers,
    and cumulative averages since node start. Slow flushes and merges usually point to storage that cannot keep up;
    read them with IDX-005 (merge throttling) and IDX-014 (indexing throttled).
    """
    specs = (("flush", "flush", ctx.t["flush_avg_ms_info"], ctx.t["flush_avg_ms_warn"]),
             ("refresh", "refresh", ctx.t["refresh_avg_ms_info"], ctx.t["refresh_avg_ms_warn"]),
             ("merge", "merges", ctx.t["merge_avg_ms_info"], ctx.t["merge_avg_ms_warn"]))
    indexed = dict((n.name, num(n.stats, "indices", "indexing", "index_total") / (n.uptime_ms / 3600000.0)
                    if n.uptime_ms else num(n.stats, "indices", "indexing", "index_total")) for n in ctx.data_nodes)
    top = max(indexed.values() or [0])
    writers = set(k for k, v in indexed.items() if top and v >= top * ctx.t["write_node_index_share_min"])
    rows, warn, info = [], [], []
    for n in ctx.data_nodes:
        if ctx.is_frozen_only(n) or n.name not in writers:
            continue
        cells, hit = [], None
        for key, sect, lim_info, lim_warn in specs:
            tot = num(n.stats, "indices", sect, "total")
            ms = num(n.stats, "indices", sect, "total_time_in_millis")
            if sect == "merges":
                ms = max(0.0, ms - num(n.stats, "indices", sect, "total_throttled_time_in_millis")
                         - num(n.stats, "indices", sect, "total_stopped_time_in_millis"))
            if tot < ctx.t["write_latency_min_ops"] or not ms:
                cells.append("-")
                continue
            avg = ms / float(tot)
            cells.append(fmt_ms(avg))
            if avg >= lim_warn:
                hit = "warn"
                warn.append("%s %s %s" % (n.name, key, fmt_ms(avg)))
            elif avg >= lim_info:
                hit = hit or "info"
                info.append("%s %s %s" % (n.name, key, fmt_ms(avg)))
        if hit:
            rows.append([n.name, ctx.tier_of(n) or "-"] + cells)
    if not rows:
        return []
    return [Finding(
        "PERF-012", "perf", Severity.WARNING if warn else Severity.INFO, T("rules.nodes.r_write_latency.01"),
        observed=T("rules.nodes.r_write_latency.02") % ", ".join((warn + info)[:12]),
        impact=T("rules.nodes.r_write_latency.03"),
        recommend=T("rules.nodes.r_write_latency.04")
                  % (ctx.t["flush_avg_ms_info"], ctx.t["refresh_avg_ms_info"], ctx.t["merge_avg_ms_info"] // 1000),
        evidence=table(["node", "tier", T("rules.nodes.r_write_latency.05"), T("rules.nodes.r_write_latency.06"),
                        T("rules.nodes.r_write_latency.07")], rows),
        affected=[r[0] for r in rows], source="nodes_stats.json (indices.flush / refresh / merges)")]


def r_disk(ctx):
    """Data node usage = 1 - available / total. Against the effective watermarks (max_headroom applied, context.watermark_used_pct): at or above flood → Critical (DISK-001; on dedicated frozen nodes ES only logs a warning at flood_stage.frozen and blocks nothing, so those are a separate Warning), at or above high → Critical (DISK-002), at or above low → Warning (DISK-003), at or above low - disk_low_margin_pct → Warning (DISK-004, only when none of the first three apply). Usage spread between nodes (max - min) >= disk_imbalance_pct_warn → Warning (DISK-005). Nothing applies → OK."""
    rows, over_low, over_high, over_flood, warn, frozen_flood = [], [], [], [], [], []
    by_tier = {}
    for n in ctx.data_nodes or ctx.nodes:
        total, avail = n.fs_total, n.fs_avail
        up = n.disk_used_pct
        if up is None:
            continue
        tier = ctx.tier_of(n) or "-"
        if tier == "frozen":
            # Frozen-only node: the shared cache reserves most of the disk up front (90% by default), so high usage is normal.
            # Per the official behavior, the low/high watermarks do not apply; only flood_stage.frozen does.
            fflood = ctx.watermark_used_pct("flood_stage.frozen", total)
            rows.append([n.name, tier, "%.1f%%" % up, fmt_bytes(total), fmt_bytes(avail),
                         T("rules.nodes.r_disk.01"), T("rules.nodes.r_disk.01"), ("%.2f%% (frozen)" % fflood) if fflood else "-"])
            if fflood and up >= fflood:
                frozen_flood.append(n.name)     # ES only logs a warning here: no index block on dedicated frozen nodes
            continue
        by_tier.setdefault(tier, []).append(up)
        low = ctx.watermark_used_pct("low", total)
        high = ctx.watermark_used_pct("high", total)
        flood = ctx.watermark_used_pct("flood_stage", total)
        rows.append([n.name, tier, "%.1f%%" % up, fmt_bytes(total), fmt_bytes(avail),
                     "%.2f%%" % low if low else "-", "%.2f%%" % high if high else "-",
                     "%.2f%%" % flood if flood else "-"])
        if flood and up >= flood:
            over_flood.append(n.name)
        elif high and up >= high:
            over_high.append(n.name)
        elif low and up >= low:
            over_low.append(n.name)
        elif low and up >= low - ctx.t["disk_low_margin_pct"]:
            warn.append(n.name)
    if not rows:
        return []
    ev = table(["node", "tier", T("rules.nodes.r_disk.02"), T("rules.nodes.r_disk.03"), T("rules.nodes.r_disk.04"), T("rules.nodes.r_disk.05"), T("rules.nodes.r_disk.06"), T("rules.nodes.r_disk.07")], rows)
    out = []
    if over_flood:
        out.append(Finding(
            "DISK-001", CAT, Severity.CRITICAL, T("rules.nodes.r_disk.08"),
            observed=T("rules.nodes.r_disk.09") % ", ".join(over_flood),
            impact=T("rules.nodes.r_disk.10"),
            recommend=T("rules.nodes.r_disk.11"),
            evidence=ev, affected=over_flood, refs=[DOC_DISK], source="nodes_stats.json"))
    if frozen_flood:
        out.append(Finding(
            "DISK-001", CAT, Severity.WARNING, T("rules.nodes.r_disk.30"),
            observed=T("rules.nodes.r_disk.31") % ", ".join(frozen_flood),
            impact=T("rules.nodes.r_disk.32"),
            recommend=T("rules.nodes.r_disk.33"),
            evidence=ev, affected=frozen_flood, refs=[DOC_DISK], source="nodes_stats.json"))
    if over_high:
        out.append(Finding(
            "DISK-002", CAT, Severity.CRITICAL, T("rules.nodes.r_disk.12"),
            observed=T("rules.nodes.r_disk.09") % ", ".join(over_high),
            impact=T("rules.nodes.r_disk.13"),
            recommend=T("rules.nodes.r_disk.14"),
            evidence=ev, affected=over_high, refs=[DOC_DISK], source="nodes_stats.json"))
    if over_low:
        out.append(Finding(
            "DISK-003", CAT, Severity.WARNING, T("rules.nodes.r_disk.15"),
            observed=T("rules.nodes.r_disk.09") % ", ".join(over_low),
            impact=T("rules.nodes.r_disk.16"),
            recommend=T("rules.nodes.r_disk.17"),
            evidence=ev, affected=over_low, refs=[DOC_DISK], source="nodes_stats.json"))
    if warn and not (over_flood or over_high or over_low):
        out.append(Finding(
            "DISK-004", CAT, Severity.WARNING, T("rules.nodes.r_disk.18"),
            observed=T("rules.nodes.r_disk.19")
                     % (ctx.t["disk_low_margin_pct"], ", ".join(warn)),
            impact=T("rules.nodes.r_disk.20"),
            recommend=T("rules.nodes.r_disk.21"),
            evidence=ev, affected=warn, source="nodes_stats.json"))
    gaps = [(t, max(v), min(v)) for t, v in by_tier.items()
            if len(v) >= 2 and max(v) - min(v) >= ctx.t["disk_imbalance_pct_warn"]]
    if gaps:
        out.append(Finding(
            "DISK-005", CAT, Severity.WARNING, T("rules.nodes.r_disk.22"),
            observed=" / ".join(T("rules.nodes.r_disk.23") % (t, mx, mn, mx - mn)
                                for t, mx, mn in gaps),
            impact=T("rules.nodes.r_disk.24"),
            recommend=T("rules.nodes.r_disk.25"),
            evidence=ev, source="nodes_stats.json"))
    if not out:
        out.append(Finding("DISK-001", CAT, Severity.OK, T("rules.nodes.r_disk.26"),
                           observed=T("rules.nodes.r_disk.27"),
                           evidence=ev, source="nodes_stats.json"))
    return out


IMPORTANT_POOLS = ("write", "search", "search_worker", "get", "bulk", "index",
                   "management", "refresh", "flush", "force_merge", "snapshot",
                   "warmer", "system_write", "system_read", "esql_worker",
                   "search_coordination", "write_coordination", "merge")


def r_thread_pools(ctx):
    """Cumulative rejected count across all thread pools. Sum > 0 → Warning; sum >= rejected_crit and the queue > 0 on a pool that was rejecting at collection time → Critical (cumulative values alone never raise it to Critical); 0 → OK (TP-001). Queue > 0 on a main pool (write/search/get, etc.) → Info (TP-002)."""
    rejected_rows, queue_rows = [], []
    total_rej = 0
    live_queue = False
    for n in ctx.nodes:
        for pool, st in items(dig(n.stats, "thread_pool")):
            rej = num(st, "rejected")
            if rej > 0:
                total_rej += rej
                if num(st, "queue") > 0:
                    live_queue = True
                rejected_rows.append([n.name, pool, fmt_num(rej), fmt_num(st.get("completed")),
                                      st.get("active"), st.get("queue"), st.get("largest")])
            q, threads = num(st, "queue"), num(st, "threads")
            if pool in IMPORTANT_POOLS and q > 0 and threads:
                queue_rows.append([n.name, pool, q, st.get("active"), threads])
    out = []
    if rejected_rows:
        rejected_rows.sort(key=lambda r: -int(str(r[2]).replace(",", "")))
        sev = (Severity.CRITICAL if (total_rej >= ctx.t["rejected_crit"] and live_queue)
               else Severity.WARNING)
        pools = sorted(set(r[1] for r in rejected_rows))
        out.append(Finding(
            "TP-001", CAT, sev, T("rules.nodes.r_thread_pools.01"),
            observed=T("rules.nodes.r_thread_pools.02") % (fmt_num(total_rej), ", ".join(pools)),
            impact=T("rules.nodes.r_thread_pools.03"),
            recommend=T("rules.nodes.r_thread_pools.04"),
            evidence=table(["node", "pool", "rejected", "completed", "active", "queue", "largest"],
                           rejected_rows[: ctx.t["top_n"]]),
            refs=[DOC_TP], source="nodes_stats.json"))
    else:
        out.append(Finding("TP-001", CAT, Severity.OK, T("rules.nodes.r_thread_pools.05"),
                           observed=T("rules.nodes.r_thread_pools.06"),
                           source="nodes_stats.json"))
    if queue_rows:
        out.append(Finding(
            "TP-002", CAT, Severity.INFO, T("rules.nodes.r_thread_pools.07"),
            observed=T("rules.nodes.r_thread_pools.08") % len(queue_rows),
            impact=T("rules.nodes.r_thread_pools.09"),
            recommend=T("rules.nodes.r_thread_pools.10"),
            evidence=table(["node", "pool", "queue", "active", "threads"],
                           queue_rows[: ctx.t["top_n"]]),
            source="nodes_stats.json"))
    return out


def r_breakers(ctx):
    """breaker.tripped >= breaker_tripped_warn → Warning; Critical if usage at collection time is also at breaker_used_pct_warn (BRK-001;
    the cumulative trip history alone never raises it to Critical). No trip history and estimated / limit >= breaker_used_pct_warn →
    Warning (BRK-002).
    With indices.breaker.total.use_real_memory (default true) the parent estimate is the real heap use, young generation garbage
    included, and before it trips ES first forces a young GC (G1OverLimitStrategy in the source). Its usage at one moment is then not
    rated here; old generation pressure is rated in JVM-001. Its trips (BRK-001) are still reported, and they are Critical only when
    that node's JVM memory pressure is at heap_used_pct_crit or above."""
    rows, tripped = [], []
    tripped_live = False
    real = str(ctx.setting("indices.breaker.total.use_real_memory") or "true").lower() != "false"
    for n in ctx.nodes:
        for name, br in items(dig(n.stats, "breakers")):
            t = num(br, "tripped")
            est = num(br, "estimated_size_in_bytes")
            lim = num(br, "limit_size_in_bytes")
            use = pct(est, lim)
            line = ctx.t["breaker_used_pct_warn"]
            if t >= ctx.t["breaker_tripped_warn"]:
                if name == "parent" and real:
                    # the momentary parent estimate includes young garbage: live pressure is the old generation (JVM-001)
                    mp = n.memory_pressure_pct
                    if mp is not None and mp >= ctx.t["heap_used_pct_crit"]:
                        tripped_live = True
                elif use and use >= line:
                    tripped_live = True
                tripped.append([n.name, name, fmt_num(t), fmt_bytes(est), fmt_bytes(lim),
                                "%.1f%%" % use if use else "-"])
            elif use and use >= line and not (name == "parent" and real):
                rows.append([n.name, name, fmt_num(t), fmt_bytes(est), fmt_bytes(lim), "%.1f%%" % use])
    out = []
    if tripped:
        out.append(Finding(
            "BRK-001", CAT, Severity.CRITICAL if tripped_live else Severity.WARNING,
            T("rules.nodes.r_breakers.01"),
            observed=T("rules.nodes.r_breakers.02") % len(tripped),
            impact=T("rules.nodes.r_breakers.03"),
            recommend=T("rules.nodes.r_breakers.04"),
            evidence=table(["node", "breaker", "tripped", "estimated", "limit", T("rules.nodes.r_breakers.05")], tripped),
            affected=sorted(set(r[0] for r in tripped)), source="nodes_stats.json"))
    if rows:
        out.append(Finding(
            "BRK-002", CAT, Severity.WARNING, T("rules.nodes.r_breakers.06"),
            observed=T("rules.nodes.r_breakers.07") % (len(rows), ctx.t["breaker_used_pct_warn"]),
            impact=T("rules.nodes.r_breakers.08"),
            recommend=T("rules.nodes.r_breakers.09"),
            evidence=table(["node", "breaker", "tripped", "estimated", "limit", T("rules.nodes.r_breakers.05")], rows),
            affected=sorted(set(r[0] for r in rows)), source="nodes_stats.json"))
    return out


def r_indexing_pressure(ctx):
    """Warning if any of the *_rejections (coordinating/primary/replica) under indexing_pressure.memory.total is > 0.

    A value of -1 means the node could not report the counter (mixed versions during an upgrade) and is ignored."""
    rows = []
    for n in ctx.nodes:
        mem = dig(n.stats, "indexing_pressure", "memory", default={}) or {}
        tot = mem.get("total") or {}
        rej = {k: v for k, v in tot.items() if k.endswith("rejections") and num(v) > 0}
        if rej:
            rows.append([n.name, ", ".join("%s=%s" % (k, fmt_num(v)) for k, v in rej.items()),
                         fmt_bytes(dig(mem, "current", "all_in_bytes")),
                         fmt_bytes(mem.get("limit_in_bytes"))])
    if not rows:
        return []
    return [Finding(
        "IP-001", CAT, Severity.WARNING, T("rules.nodes.r_indexing_pressure.04"),
        observed=T("rules.nodes.r_indexing_pressure.01") % len(rows),
        impact=T("rules.nodes.r_indexing_pressure.02"),
        recommend=T("rules.nodes.r_indexing_pressure.03"),
        evidence=table(["node", "rejections", "current", "limit"], rows),
        affected=[r[0] for r in rows], source="nodes_stats.json")]


def r_fielddata(ctx):
    """Node fielddata memory / heap_max >= fielddata_heap_pct_warn → Warning (FD-001). Largest field in fielddata.json above 64MB → Info (FD-002)."""
    rows = []
    for n in ctx.nodes:
        fd = dig(n.stats, "indices", "fielddata", default={}) or {}
        size = num(fd, "memory_size_in_bytes")
        ev = num(fd, "evictions")
        hm = n.heap_max or 0
        p = pct(size, hm)
        if size and p and p >= ctx.t["fielddata_heap_pct_warn"]:
            rows.append([n.name, fmt_bytes(size), "%.1f%%" % p, fmt_num(ev)])
    out = []
    if rows:
        out.append(Finding(
            "FD-001", CAT, Severity.WARNING, T("rules.nodes.r_fielddata.01"),
            observed=T("rules.nodes.r_fielddata.02")
                     % (ctx.t["fielddata_heap_pct_warn"], len(rows)),
            impact=T("rules.nodes.r_fielddata.03"),
            recommend=T("rules.nodes.r_fielddata.04"),
            evidence=table(["node", "fielddata", T("rules.nodes.r_fielddata.05"), "evictions"], rows),
            affected=[r[0] for r in rows], source="nodes_stats.json"))
    # Top consumers per field
    top = []
    for r in dicts(ctx.fielddata_cat):
        from ..util import parse_bytes
        b = parse_bytes(r.get("size"))
        if b:
            top.append([r.get("node"), r.get("field"), fmt_bytes(b), b])
    if top:
        top.sort(key=lambda r: -r[3])
        if top[0][3] > 64 * 1024 * 1024:
            out.append(Finding(
                "FD-002", CAT, Severity.INFO, T("rules.nodes.r_fielddata.06"),
                observed=T("rules.nodes.r_fielddata.07") % (top[0][1], top[0][2]),
                impact=T("rules.nodes.r_fielddata.08"),
                recommend=T("rules.nodes.r_fielddata.09"),
                evidence=table(["node", "field", "size"], [r[:3] for r in top[: ctx.t["top_n"]]]),
                source="fielddata.json"))
    return out


def r_ingest_failures(ctx):
    """Ingest pipeline failures, rated by failure ratio per pipeline (ING-001).

    Runs when any node has ingest.total.failed >= ingest_failed_warn. Failed and processed counts are summed per pipeline across nodes,
    and the failure ratio is failed / processed. Any pipeline at or above ingest_fail_ratio_warn → Warning, otherwise Info.
    Counters are cumulative since node start, and a pipeline called from another pipeline is counted in both.
    """
    rows = []
    for n in ctx.nodes:
        tot = dig(n.stats, "ingest", "total", default={}) or {}
        failed = num(tot, "failed")
        if failed >= ctx.t["ingest_failed_warn"]:
            rows.append([n.name, fmt_num(failed), fmt_num(tot.get("count")),
                         fmt_ms(tot.get("time_in_millis"))])
    if not rows:
        return []
    agg = collections.OrderedDict()
    for n in ctx.nodes:
        for pname, p in items(dig(n.stats, "ingest", "pipelines")):
            a = agg.setdefault(pname, [0, 0, set()])
            a[0] += num(p, "failed")
            a[1] += num(p, "count")
            if num(p, "failed"):
                a[2].add(n.name)
    pipes = [(k, v[0], v[1], (v[0] / float(v[1])) if v[1] else 1.0, len(v[2]))
             for k, v in agg.items() if v[0] > 0]
    pipes.sort(key=lambda r: (-r[3], -r[1]))
    high = [r for r in pipes if r[3] >= ctx.t["ingest_fail_ratio_warn"]]
    sev = Severity.WARNING if high else Severity.INFO
    obs = T("rules.nodes.r_ingest_failures.02") % (len(rows), len(pipes))
    if high:
        obs += T("rules.nodes.r_ingest_failures.05") % (len(high), ctx.t["ingest_fail_ratio_warn"] * 100)
    else:
        obs += T("rules.nodes.r_ingest_failures.06") % (ctx.t["ingest_fail_ratio_warn"] * 100)
    return [Finding(
        "ING-001", CAT, sev, T("rules.nodes.r_ingest_failures.01"),
        observed=obs,
        impact=T("rules.nodes.r_ingest_failures.03"),
        recommend=T("rules.nodes.r_ingest_failures.04"),
        evidence=table(["pipeline", "failed", "count", T("rules.nodes.r_ingest_failures.07"), "nodes"],
                       [[r[0], fmt_num(r[1]), fmt_num(r[2]), "%.2f%%" % (r[3] * 100), r[4]] for r in pipes[: ctx.t["top_n"]]])
        if pipes else table(["node", "failed", "count", "time"], rows),
        source="nodes_stats.json")]


def r_node_heterogeneity(ctx):
    """Different heap or CPU count within the same tier (data role combination) → Warning (NODE-001).

    Different specs across tiers are normal design, so differences between tiers are not rated; only a spec table per tier is reported as Info
    (NODE-003). Within a tier, shards are spread evenly, so the smaller node saturates first and sets the processing limit of that tier.
    """
    tiers = ctx.data_tiers()
    if not tiers:
        return []
    out, rows_in, rows_all = [], [], []
    for tier, nodes in tiers.items():
        heaps = collections.Counter(fmt_bytes(n.heap_max) for n in nodes if n.heap_max)
        cpus = collections.Counter(n.processors for n in nodes if n.processors)
        rows_all.append([tier, len(nodes), ", ".join(T("rules.nodes.r_node_heterogeneity.01") % kv for kv in heaps.items()),
                         ", ".join(T("rules.nodes.r_node_heterogeneity.02") % kv for kv in cpus.items())])
        if len(heaps) > 1 or len(cpus) > 1:
            for n in nodes:
                rows_in.append([tier, n.name, fmt_bytes(n.heap_max), n.processors, fmt_bytes(n.ram_total)])
    if rows_in:
        out.append(Finding(
            "NODE-001", CAT, Severity.WARNING, T("rules.nodes.r_node_heterogeneity.03"),
            observed=T("rules.nodes.r_node_heterogeneity.04")
                     % ", ".join(sorted(set(r[0] for r in rows_in))),
            impact=T("rules.nodes.r_node_heterogeneity.05"),
            recommend=T("rules.nodes.r_node_heterogeneity.06"),
            evidence=table(["tier", "node", "heap", "cpu", "RAM"], rows_in),
            source="nodes.json / nodes_stats.json"))
    if len(tiers) > 1:
        out.append(Finding(
            "NODE-003", CAT, Severity.INFO, T("rules.nodes.r_node_heterogeneity.07"),
            observed=T("rules.nodes.r_node_heterogeneity.08") % (len(tiers), ", ".join(T("rules.nodes.r_node_heterogeneity.09") % (t, len(v)) for t, v in tiers.items())),
            impact=T("rules.nodes.r_node_heterogeneity.10"),
            recommend=T("rules.nodes.r_node_heterogeneity.11"),
            evidence=table(["tier", T("rules.nodes.r_node_heterogeneity.12"), T("rules.nodes.r_node_heterogeneity.13"), T("rules.nodes.r_node_heterogeneity.14")], rows_all),
            source="nodes.json"))
    return out


def r_search_pool_wait(ctx):
    """Search thread pool busy while the node CPU is low (PERF-013), from the point-in-time values at collection.

    active search threads >= search_pool_busy_share of the pool size (nodes.json thread_pool.search.size) and node CPU% <
    search_io_cpu_pct_max. Threads that are busy without using CPU are usually waiting, most often on storage reads (frozen shared
    cache, remote storage) and sometimes on locks or other nodes. Queued searches on such a node → Warning, otherwise Info.
    On frozen-only nodes, searches read from the snapshot repository by design, so a busy pool there counts only when searches
    are also queued. This is a single moment, so read it with hot threads (RT-001) and the storage findings (FRZ-002, PERF-009, DISK-008).
    """
    rows, warn = [], False
    for n in ctx.data_nodes:
        size = dig(n.info, "thread_pool", "search", "size")
        sp = dig(n.stats, "thread_pool", "search", default={}) or {}
        active = num(sp, "active")
        try:
            size = int(size)
        except (TypeError, ValueError):
            continue
        if size <= 0 or n.cpu_pct is None:
            continue
        if active >= size * ctx.t["search_pool_busy_share"] and n.cpu_pct < ctx.t["search_io_cpu_pct_max"]:
            q = num(sp, "queue")
            if not q and ctx.is_frozen_only(n):
                continue
            warn = warn or q > 0
            rows.append([n.name, ctx.tier_of(n) or "-", "%d / %d" % (active, size), fmt_num(q),
                         fmt_num(num(sp, "rejected")), "%s%%" % n.cpu_pct])
    if not rows:
        return []
    return [Finding(
        "PERF-013", "perf", Severity.WARNING if warn else Severity.INFO, T("rules.nodes.r_search_pool_wait.01"),
        observed=T("rules.nodes.r_search_pool_wait.02") % (len(rows), ", ".join(r[0] for r in rows)),
        impact=T("rules.nodes.r_search_pool_wait.03"),
        recommend=T("rules.nodes.r_search_pool_wait.04"),
        evidence=table(["node", "tier", T("rules.nodes.r_search_pool_wait.05"), "queue", "rejected", "cpu%"], rows),
        affected=[r[0] for r in rows], source="nodes.json / nodes_stats.json")]


RULES = [
    r_heap_usage, r_heap_sizing, r_gc, r_os, r_disk, r_thread_pools,
    r_breakers, r_indexing_pressure, r_fielddata, r_ingest_failures,
    r_node_heterogeneity, r_write_latency, r_search_pool_wait,
]
