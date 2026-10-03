# -*- coding: utf-8 -*-
"""Hot spot, balancing and recovery settings rules.

Basis: the Elastic troubleshooting page "Hot spotting" (resource usage concentrated on a few nodes) and
the desired balance allocator description in the size-shards docs.
"""


from ..i18n import T, N_
from ..model import Finding, Severity, table
from ..util import dig, fmt_ms, fmt_num, parse_bytes, dicts, num, items, strs

HOT = "hotspot"
CAT = "cluster"

D_HOT = (N_("rules.hotspot._.01"),
         "https://www.elastic.co/docs/troubleshoot/elasticsearch/hotspotting")
D_BAL = (N_("rules.hotspot._.02"),
         "https://www.elastic.co/docs/troubleshoot/elasticsearch/troubleshooting-unbalanced-cluster")
D_SHARDS = ("Size your shards",
            "https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards")
D_TPL = ("Templates",
         "https://www.elastic.co/docs/manage-data/data-store/templates")
D_DELAY = ("Delaying allocation when a node leaves",
           "https://www.elastic.co/docs/deploy-manage/distributed-architecture/shard-allocation-relocation-recovery/delaying-allocation-when-node-leaves")
D_REC = (N_("rules.hotspot._.03"),
         "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/index-recovery-settings")


def _spread(values):
    """Max / min / spread."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    return max(vals), min(vals), max(vals) - min(vals)


def r_resource_hotspot(ctx):
    """Checks whether heap, CPU and disk usage are skewed toward a few nodes within the same tier (the official hot spotting indicators).

    Tiers with different roles and loads are not compared with each other. Frozen tier disk is excluded because the shared cache pre-allocates it.
    For each metric, Warning when max - min within the tier >= gap and the max is >= floor. Values are point-in-time at collection.
    Nodes up for less than node_compare_min_uptime_hours are left out of the heap and CPU comparison (cold caches and
    fewer active shards right after a restart make them look idle). Disk usage does not reset on restart, so they stay in that one.
    The official docs look for skew that persists and for write and search queues backing up; the queues at collection are shown
    as well, and one bundle cannot show whether the skew persists.
    """
    rows, flags, skipped = [], [], []
    checks = ((T("rules.hotspot.r_resource_hotspot.01"), "heap", ctx.t["hotspot_heap_pct_gap"], ctx.t["hotspot_heap_pct_floor"]),
              (T("rules.hotspot.r_resource_hotspot.02"), "cpu", ctx.t["hotspot_cpu_pct_gap"], ctx.t["hotspot_cpu_pct_floor"]),
              (T("rules.hotspot.r_resource_hotspot.03"), "disk", ctx.t["disk_imbalance_pct_warn"], ctx.t["hotspot_disk_pct_floor"]))
    for tier, nodes in ctx.data_tiers().items():
        for n in nodes:
            fresh = ctx.recently_restarted(n)
            if fresh:
                skipped.append(n.name)
            rows.append([tier, n.name, "%s%%" % n.heap_used_pct if n.heap_used_pct is not None else "-",
                         "%s%%" % n.cpu_pct if n.cpu_pct is not None else "-",
                         "%.1f%%" % n.disk_used_pct if n.disk_used_pct is not None else "-",
                         "%d / %d" % (num(n.stats, "thread_pool", "write", "queue"), num(n.stats, "thread_pool", "search", "queue")),
                         fmt_ms(n.uptime_ms) + (T("rules.hotspot.r_resource_hotspot.10") if fresh else "")
                         if n.uptime_ms else "-"])
        if len(nodes) < 2:
            continue
        settled = [n for n in nodes if not ctx.recently_restarted(n)]
        series = {"heap": [(n.name, n.heap_used_pct) for n in settled],
                  "cpu": [(n.name, n.cpu_pct) for n in settled],
                  "disk": [(n.name, n.disk_used_pct) for n in nodes] if tier != "frozen" else []}
        for label, key, gap, floor in checks:
            vals = [(v, k) for k, v in series[key] if v is not None]
            if len(vals) < 2:
                continue
            mx, mn = max(vals), min(vals)
            if mx[0] - mn[0] >= gap and mx[0] >= floor:
                flags.append(T("rules.hotspot.r_resource_hotspot.04") % (tier, label, mx[0] - mn[0], mx[1], mx[0]))
    ev = table(["tier", "node", "heap%", "cpu%", "disk%", T("rules.hotspot.r_resource_hotspot.12"), "uptime"], rows)
    note = (T("rules.hotspot.r_resource_hotspot.11") % (ctx.t["node_compare_min_uptime_hours"], ", ".join(skipped))
            if skipped else "")
    if not flags:
        return [Finding("HOT-001", HOT, Severity.OK, T("rules.hotspot.r_resource_hotspot.05"),
                        observed=T("rules.hotspot.r_resource_hotspot.06") + note,
                        evidence=ev, refs=[D_HOT], source="nodes_stats.json")]
    return [Finding(
        "HOT-001", HOT, Severity.WARNING, T("rules.hotspot.r_resource_hotspot.07"),
        observed=" / ".join(flags) + note,
        impact=T("rules.hotspot.r_resource_hotspot.08"),
        recommend=T("rules.hotspot.r_resource_hotspot.09"),
        evidence=ev, refs=[D_HOT], source="nodes_stats.json")]


def r_workload_hotspot(ctx):
    """Skew in indexing/search work per node within the same tier, compared as an hourly rate (cumulative count / uptime).

    Busiest node / tier average >= workload_skew_ratio_warn → Warning. Nodes up for less than node_compare_min_uptime_hours
    are left out: their counters cover a short window and their caches are cold. Tiers with fewer than 2 remaining nodes
    or fewer than 10000 operations in total are skipped. Values include replica work.
    """
    out = []
    for key, label, path in (("index_total", T("rules.hotspot.r_workload_hotspot.01"), ("indices", "indexing", "index_total")),
                             ("query_total", T("rules.hotspot.r_workload_hotspot.02"), ("indices", "search", "query_total"))):
        flags, rows, skipped = [], [], []
        for tier, nodes in ctx.data_tiers().items():
            rates, total = [], 0
            for n in nodes:
                v = num(n.stats, *path)
                up = (n.uptime_ms or 0) / 3600000.0
                fresh = ctx.recently_restarted(n)
                rows.append([tier, n.name, fmt_num(v), ("%.0f/h" % (v / up)) if up else "-",
                             fmt_ms(n.uptime_ms) + (T("rules.hotspot.r_resource_hotspot.10") if fresh else "")
                             if n.uptime_ms else "-"])
                if fresh:
                    skipped.append(n.name)
                    continue
                total += v
                if up:
                    rates.append(v / up)
            if len(rates) < 2 or total < 10000:
                continue
            avg = sum(rates) / float(len(rates))
            if avg and max(rates) / avg >= ctx.t["workload_skew_ratio_warn"]:
                flags.append(T("rules.hotspot.r_workload_hotspot.03") % (tier, max(rates) / avg))
        if flags:
            note = (T("rules.hotspot.r_resource_hotspot.11") % (ctx.t["node_compare_min_uptime_hours"], ", ".join(skipped))
                    if skipped else "")
            out.append(Finding(
                "HOT-002." + key, HOT, Severity.WARNING, T("rules.hotspot.r_workload_hotspot.04") % label,
                observed=" / ".join(flags) + note,
                impact=T("rules.hotspot.r_workload_hotspot.05"),
                recommend=T("rules.hotspot.r_workload_hotspot.06"),
                evidence=table(["tier", "node", T("rules.hotspot.r_workload_hotspot.07"), T("rules.hotspot.r_workload_hotspot.08"), "uptime"], rows),
                refs=[D_HOT], source="nodes_stats.json"))
    return out


def r_desired_balance(ctx):
    """Desired balance not converged. Shards not in their desired location (cat allocation shards.undesired) >= undesired_shards_warn →
    Warning when nothing is relocating or initializing (stuck), Info while a rebalance is moving them (HOT-003). A balance computation
    still running (internal desired balance stats computation_active=true) → Info (HOT-004)."""
    rows, undesired = [], 0
    for r in dicts(ctx.cat_allocation):
        if not isinstance(r, dict):
            continue
        try:
            u = int(str(num(r, "shards.undesired")))
        except ValueError:
            u = 0
        undesired += u
        rows.append([r.get("node"), r.get("shards"), u, r.get("write_load.forecast"),
                     r.get("disk.percent")])
    db = ctx.b.json("internal_desired_balance.json") or {}
    stats = db.get("stats") or {}
    out = []
    if undesired >= ctx.t["undesired_shards_warn"]:
        # Undesired shards are normal while a rebalance is moving them; only when nothing is relocating are they stuck.
        moving = (ctx.health.get("relocating_shards") or 0) + (ctx.health.get("initializing_shards") or 0)
        out.append(Finding(
            "HOT-003", HOT, Severity.INFO if moving else Severity.WARNING, T("rules.hotspot.r_desired_balance.01"),
            observed=T("rules.hotspot.r_desired_balance.02") % undesired,
            impact=T("rules.hotspot.r_desired_balance.03"),
            recommend=T("rules.hotspot.r_desired_balance.04"),
            evidence=table(["node", T("rules.hotspot.r_desired_balance.05"), T("rules.hotspot.r_desired_balance.06"), T("rules.hotspot.r_desired_balance.07"), "disk%"], rows),
            refs=[D_BAL, D_SHARDS], source="allocation.json / internal_desired_balance.json"))
    # computation_converged is a counter; computation_active tells whether a balance computation is still running
    if stats.get("computation_active") is True:
        out.append(Finding(
            "HOT-004", HOT, Severity.INFO, T("rules.hotspot.r_desired_balance.08"),
            observed=T("rules.hotspot.r_desired_balance.09"),
            impact=T("rules.hotspot.r_desired_balance.10"),
            recommend=T("rules.hotspot.r_desired_balance.11"),
            source="internal_desired_balance.json"))
    return out


def r_recovery_settings(ctx):
    """Recovery bandwidth limit.

    The default of indices.recovery.max_bytes_per_sec (40mb) is not a problem by itself, and 0 or less means unlimited.
    It is reported as a possible recovery bottleneck only while a recovery or relocation is actually running.
    """
    rate = ctx.setting("indices.recovery.max_bytes_per_sec")
    src = ctx.setting_source("indices.recovery.max_bytes_per_sec")
    b = parse_bytes(rate)
    moving = sum(ctx.health.get(k) or 0 for k in ("initializing_shards", "relocating_shards"))
    active_recoveries = 0
    for _idx, body in items(ctx.recovery):
        for sh in dicts(body.get("shards") if isinstance(body, dict) else None):
            if (sh.get("stage") or "").upper() != "DONE":
                active_recoveries += 1
    if b is None or b <= 0 or b > ctx.t["recovery_rate_low_bytes"] or not (moving or active_recoveries):    # 0 or less = unlimited
        return []
    rows = [["indices.recovery.max_bytes_per_sec", str(rate), src],
            ["cluster.routing.allocation.node_concurrent_recoveries",
             str(ctx.setting("cluster.routing.allocation.node_concurrent_recoveries")),
             ctx.setting_source("cluster.routing.allocation.node_concurrent_recoveries")],
            [T("rules.hotspot.r_recovery_settings.01"), str(active_recoveries), str(moving)]]
    return [Finding(
        "REC-001", CAT, Severity.INFO, T("rules.hotspot.r_recovery_settings.02"),
        observed=T("rules.hotspot.r_recovery_settings.03") % (rate, src),
        impact=T("rules.hotspot.r_recovery_settings.04"),
        recommend=T("rules.hotspot.r_recovery_settings.05"),
        evidence=table([T("rules.hotspot.r_recovery_settings.06"), T("rules.hotspot.r_recovery_settings.07"), T("rules.hotspot.r_recovery_settings.08")], rows), refs=[D_REC], source="cluster_settings.json / recovery.json")]


def r_template_conflict(ctx):
    """Whether a legacy (_template) template is hidden by a composable (_index_template) template.

    If any composable template matches, the legacy template is not applied (official behavior).
    Composable templates that overlap at the same priority are rejected by ES at creation, so they are not checked here.
    Pattern overlap is estimated by comparing wildcards.
    """
    import fnmatch
    comp = []
    for it in (ctx.index_templates or {}).get("index_templates") or []:
        for pat in dig(it, "index_template", "index_patterns", default=[]) or []:
            comp.append((it.get("name"), pat))
    legacy = ctx.legacy_templates or {}
    rows = []
    for lname, body in legacy.items():
        if not isinstance(body, dict) or str(lname).startswith("."):
            continue
        for lp in strs(body.get("index_patterns")):
            probe = str(lp).replace("*", "x")
            for cname, cp in comp:
                cprobe = str(cp).replace("*", "x")
                if fnmatch.fnmatch(probe, cp) or fnmatch.fnmatch(cprobe, lp):
                    rows.append([lname, lp, cname, cp])
    if not rows:
        return []
    return [Finding(
        "TPL-001", CAT, Severity.WARNING, T("rules.hotspot.r_template_conflict.01"),
        observed=T("rules.hotspot.r_template_conflict.02") % len(set(r[0] for r in rows)),
        impact=T("rules.hotspot.r_template_conflict.03"),
        recommend=T("rules.hotspot.r_template_conflict.04"),
        evidence=table([T("rules.hotspot.r_template_conflict.05"), T("rules.hotspot.r_template_conflict.06"), T("rules.hotspot.r_template_conflict.07"), T("rules.hotspot.r_template_conflict.06")], rows[: ctx.t["top_n"]]),
        refs=[D_TPL], source="templates.json / index_templates.json")]


def r_delayed_allocation(ctx):
    """The delayed_timeout setting that prevents immediate re-replication when a node restarts."""
    rows = []
    for name in ctx.index_settings.keys():
        if ctx.is_system_index(name):
            continue
        v = ctx.index_setting(name, "index.unassigned.node_left.delayed_timeout")
        if v is not None and str(v) in ("0", "0ms", "0s"):
            rows.append([name, str(v)])
    if not rows:
        return []
    return [Finding(
        "CLU-021", CAT, Severity.WARNING, T("rules.hotspot.r_delayed_allocation.01"),
        observed=T("rules.hotspot.r_delayed_allocation.02") % len(rows),
        impact=T("rules.hotspot.r_delayed_allocation.03"),
        recommend=T("rules.hotspot.r_delayed_allocation.04"),
        evidence=table(["index", "delayed_timeout"], rows[: ctx.t["top_n"]]),
        refs=[D_DELAY], source="settings.json")]


def r_tier_saturation(ctx):
    """CPU saturation per tier. Warning if every node in a tier has load15/CPU >= load_per_cpu_warn or CPU% >= tier_cpu_pct_warn.
    As in OS-001, a container node with low CPU use does not count by load alone (the load can be the host's).

    This differs from skew between nodes (HOT-001). Even when the load is spread evenly, a tier that is at its limit needs more nodes or less load.
    The cgroup CPU throttling (OS-003) and the rejections of the write, write_coordination and search thread pools (TP-001) of that tier are shown as supporting evidence.
    """
    out = []
    for tier, nodes in ctx.data_tiers().items():
        rows, hot = [], 0
        for n in nodes:
            per = (n.load15 / n.processors) if (n.load15 and n.processors) else None
            elapsed = num(n.stats, "os", "cgroup", "cpu", "stat", "number_of_elapsed_periods")
            thr = num(n.stats, "os", "cgroup", "cpu", "stat", "number_of_times_throttled")
            rej = sum(num(st, "rejected") for pool, st in items(dig(n.stats, "thread_pool"))
                      if pool in ("write", "write_coordination", "search"))
            busy = ctx.load_high(n) or \
                   (n.cpu_pct is not None and n.cpu_pct >= ctx.t["tier_cpu_pct_warn"])
            hot += 1 if busy else 0
            rows.append([tier, n.name, n.processors, "%s%%" % n.cpu_pct if n.cpu_pct is not None else "-",
                         "%.2f" % per if per is not None else "-",
                         "%.1f%%" % (thr * 100.0 / elapsed) if elapsed else "-", fmt_num(rej)])
        if nodes and hot == len(nodes):
            out.append(Finding(
                "HOT-005." + tier, HOT, Severity.WARNING, T("rules.hotspot.r_tier_saturation.01") % tier,
                observed=T("rules.hotspot.r_tier_saturation.02")
                         % (tier, len(nodes), ctx.t["load_per_cpu_warn"], ctx.t["tier_cpu_pct_warn"]),
                impact=T("rules.hotspot.r_tier_saturation.03"),
                recommend=T("rules.hotspot.r_tier_saturation.04"),
                evidence=table(["tier", "node", T("rules.hotspot.r_tier_saturation.05"), "cpu%", "load15/cpu", "throttled", T("rules.hotspot.r_tier_saturation.06")], rows),
                affected=[n.name for n in nodes], refs=[D_HOT], source="nodes_stats.json"))
    return out


RULES = [r_tier_saturation, r_resource_hotspot, r_workload_hotspot, r_desired_balance,
         r_recovery_settings, r_template_conflict, r_delayed_allocation]
