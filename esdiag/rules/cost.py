# -*- coding: utf-8 -*-
"""Storage cost: data kept on the hot tier, replicas nobody searches, uneven tier usage, and how many days of
ingest the landing tier can still hold.

None of these is a fault. They show where disk is spent, with the numbers needed to decide whether that is intended.
Every threshold is a tool threshold.
"""

import collections

from ..i18n import T, N_
from ..model import Finding, Severity, table
from ..util import dig, fmt_bytes, items, num

CAT = "cost"
DAY_MS = 86400000.0
LATER_PHASES = ("warm", "cold", "frozen", "delete")

D_TIERS = (N_("rules.cost._.01"),
           "https://www.elastic.co/docs/manage-data/lifecycle/data-tiers")
D_ILM_PHASES = (N_("rules.cost._.02"),
                "https://www.elastic.co/docs/manage-data/lifecycle/index-lifecycle-management/index-lifecycle")
D_REPLICA = (N_("rules.cost._.03"),
             "https://www.elastic.co/docs/deploy-manage/distributed-architecture/clusters-nodes-shards")


def _now_ms(ctx):
    t = ctx.collection_time
    if not t:
        return None
    try:
        if t.tzinfo is None:
            import datetime
            t = t.replace(tzinfo=datetime.timezone.utc)
        return t.timestamp() * 1000.0
    except Exception:
        return None


def _phases(ctx, policy):
    body = (ctx.ilm_policies or {}).get(policy) or {}
    ph = dig(body, "policy", "phases", default={})
    return ph if isinstance(ph, dict) else {}


def _next_phase(ctx, policy):
    """First phase after hot as 'name min_age', or None."""
    ph = _phases(ctx, policy)
    for name in LATER_PHASES:
        p = ph.get(name)
        if isinstance(p, dict):
            return "%s %s" % (name, p.get("min_age") or "0ms")
    return None


def _node_tiers(ctx):
    return dict((n.name, ctx.tier_of(n)) for n in ctx.data_nodes)


def _colder(tier):
    return bool(tier) and "hot" not in tier and ("warm" in tier or "cold" in tier)


def _has_colder_tier(ctx):
    return any(_colder(t) or t == "frozen" for t in _node_tiers(ctx).values())


def _index_tiers(ctx):
    tiers = _node_tiers(ctx)
    out = collections.defaultdict(set)
    for sh in ctx.shards:
        node = sh.get("node")
        if node and tiers.get(node):
            out[sh["index"]].add(tiers[node])
    return out


def r_hot_rolled_over(ctx):
    """Rolled-over indices still in the ILM hot phase long after rollover (COST-001).

    Runs only when the cluster has a warm, cold or frozen tier to move data to. An index is listed when ILM explain shows phase hot,
    the index has rolled over and is not a write target, its age since rollover (lifecycle_date) is >= hot_rolled_days_info, and at
    least one of its shards is on a hot node. Rows are grouped by ILM policy with the next phase and its min_age, which counts from
    rollover. Info only: keeping data on hot can be intended (search speed, short retention).
    """
    if not _has_colder_tier(ctx):
        return []
    now = _now_ms(ctx)
    if not now:
        return []
    where = _index_tiers(ctx)
    writes = set(ctx.write_targets())
    groups = collections.OrderedDict()
    for name, ex in items(ctx.ilm_explain):
        if not isinstance(ex, dict) or ex.get("phase") != "hot" or name in writes:
            continue
        if ctx.is_system_index(name) or not ctx.rolled_over(name):
            continue
        if not any("hot" in (t or "") for t in where.get(name, ())):
            continue
        since = ex.get("lifecycle_date_millis")
        try:
            days = (now - float(since)) / DAY_MS
        except (TypeError, ValueError):
            continue
        if days < ctx.t["hot_rolled_days_info"]:
            continue
        pol = ex.get("policy") or "-"
        g = groups.setdefault(pol, [0, 0, 0.0])
        g[0] += 1
        g[1] += num(ctx.indices_stats, name, "total", "store", "size_in_bytes")
        g[2] = max(g[2], days)
    if not groups:
        return []
    rows = sorted(([p, g[0], fmt_bytes(g[1]), "%.0f" % g[2], _next_phase(ctx, p) or T("rules.cost.r_hot_rolled_over.05")]
                   for p, g in groups.items()), key=lambda r: -groups[r[0]][1])
    total = sum(g[1] for g in groups.values())
    count = sum(g[0] for g in groups.values())
    return [Finding(
        "COST-001", CAT, Severity.INFO, T("rules.cost.r_hot_rolled_over.01"),
        observed=T("rules.cost.r_hot_rolled_over.02") % (count, ctx.t["hot_rolled_days_info"], fmt_bytes(total), len(groups)),
        impact=T("rules.cost.r_hot_rolled_over.03"),
        recommend=T("rules.cost.r_hot_rolled_over.04"),
        evidence=table(["ILM policy", T("rules.cost.r_hot_rolled_over.06"), T("rules.cost.r_hot_rolled_over.07"),
                        T("rules.cost.r_hot_rolled_over.08"), T("rules.cost.r_hot_rolled_over.09")], rows[: ctx.t["top_n"]]),
        refs=[D_ILM_PHASES, D_TIERS], source="ilm_explain.json / ilm_policies.json / indices_stats.json")]


def _zones(ctx):
    zs = set()
    for n in ctx.data_nodes:
        a = n.attrs or {}
        z = a.get("availability_zone") or a.get("zone") or a.get("logical_availability_zone")
        if z:
            zs.add(z)
    return len(zs)


def r_idle_replicas(ctx):
    """Indices with cost_replicas_min or more replicas and no searches (COST-002).

    User indices (system indices and searchable snapshot mounts excluded) with number_of_replicas >= cost_replicas_min, documents,
    and indices_stats total.search.query_total of 0. When the data nodes span at least replicas + 1 availability zones, one copy per
    zone is a deliberate layout and the index is not listed. The second and later replicas add disk and indexing work without
    adding availability against a single node loss. Search counters reset when a shard moves or its node restarts, so 0 means
    "no searches since the shards started". Info only.
    """
    zones = _zones(ctx)
    rows, saved = [], 0
    for name in ctx.index_settings.keys():
        if ctx.is_system_index(name) or ctx.is_searchable_snapshot(name):
            continue
        try:
            rep = int(str(ctx.index_setting(name, "index.number_of_replicas")))
        except (TypeError, ValueError):
            continue
        if rep < ctx.t["cost_replicas_min"] or (zones and zones >= rep + 1):
            continue
        st = ctx.indices_stats.get(name)
        if not isinstance(st, dict) or num(st, "primaries", "docs", "count") <= 0:
            continue
        if num(st, "total", "search", "query_total") > 0:
            continue
        pri = num(st, "primaries", "store", "size_in_bytes")
        extra = pri * (rep - 1)
        saved += extra
        rows.append([name, rep, fmt_bytes(pri), fmt_bytes(num(st, "total", "store", "size_in_bytes")), fmt_bytes(extra), extra])
    if not rows:
        return []
    rows.sort(key=lambda r: -r[5])
    return [Finding(
        "COST-002", CAT, Severity.INFO, T("rules.cost.r_idle_replicas.01"),
        observed=T("rules.cost.r_idle_replicas.02") % (len(rows), ctx.t["cost_replicas_min"], fmt_bytes(saved)),
        impact=T("rules.cost.r_idle_replicas.03"),
        recommend=T("rules.cost.r_idle_replicas.04"),
        evidence=table(["index", "replicas", T("rules.cost.r_idle_replicas.05"), T("rules.cost.r_idle_replicas.06"),
                        T("rules.cost.r_idle_replicas.07")], [r[:5] for r in rows[: ctx.t["top_n"]]]),
        refs=[D_REPLICA], source="settings.json / indices_stats.json")]


def _tier_usage(ctx):
    out = collections.OrderedDict()
    for tier, nodes in ctx.data_tiers().items():
        tot = sum(n.fs_total or 0 for n in nodes)
        avail = sum(n.fs_avail or 0 for n in nodes)
        out[tier] = (len(nodes), tot, tot - avail, ((tot - avail) * 100.0 / tot) if tot else None)
    return out


def r_tier_usage(ctx):
    """Disk usage across data tiers (COST-003).

    Frozen is shown but not compared, because its shared cache reserves the disk up front. Flags:
    (1) the hot tier is at tier_hot_used_pct or more while a warm or cold tier is tier_gap_pct points or more emptier, which
    usually means data moves off hot later than the hot disks allow; (2) a warm or cold tier is below tier_idle_used_pct, which
    suggests it is larger than the data it holds. Needs at least two non-frozen tiers. Info only.
    """
    use = _tier_usage(ctx)
    cmp_tiers = [t for t in use if t != "frozen"]
    if len(cmp_tiers) < 2:
        return []
    hot = [t for t in cmp_tiers if "hot" in t]
    cold = [t for t in cmp_tiers if _colder(t)]
    flags = []
    for h in hot:
        hp = use[h][3]
        if hp is None or hp < ctx.t["tier_hot_used_pct"]:
            continue
        for c in cold:
            cp = use[c][3]
            if cp is not None and hp - cp >= ctx.t["tier_gap_pct"]:
                flags.append(T("rules.cost.r_tier_usage.02") % (h, hp, c, cp))
    for c in cold:
        cp = use[c][3]
        if cp is not None and cp < ctx.t["tier_idle_used_pct"]:
            flags.append(T("rules.cost.r_tier_usage.03") % (c, cp, fmt_bytes(use[c][1] - use[c][2])))
    if not flags:
        return []
    rows = [[t, u[0], fmt_bytes(u[1]), fmt_bytes(u[2]), ("%.1f%%" % u[3]) if u[3] is not None else "-"]
            for t, u in use.items()]
    return [Finding(
        "COST-003", CAT, Severity.INFO, T("rules.cost.r_tier_usage.01"),
        observed=" / ".join(flags),
        impact=T("rules.cost.r_tier_usage.04"),
        recommend=T("rules.cost.r_tier_usage.05"),
        evidence=table(["tier", T("rules.cost.r_tier_usage.06"), T("rules.cost.r_tier_usage.07"),
                        T("rules.cost.r_tier_usage.08"), "disk%"], rows),
        refs=[D_TIERS, D_ILM_PHASES], source="nodes_stats.json")]


def _drains(ctx, name):
    """True when the index has an ILM policy with a phase after hot (moves to another tier or is deleted)."""
    pol = ctx.index_setting(name, "index.lifecycle.name")
    if not pol:
        return False
    ph = _phases(ctx, pol)
    return any(isinstance(ph.get(p), dict) for p in LATER_PHASES)


def r_ingest_headroom(ctx):
    """How many days of ingest the landing tier can still take before the high watermark (COST-004), from one bundle.

    Daily ingest = store size (replicas included) of user indices created in the last ingest_window_days, plus the part of older write
    indices that falls in the window (size x window / age), divided by the window (shorter if the cluster is younger). Searchable
    snapshot mounts and system indices are left out. Landing tier = tiers holding shards of write targets (frozen excluded).
    Headroom = sum over those nodes of (bytes allowed at the high watermark - bytes used). Days = headroom / daily ingest.
    This assumes nothing is moved or deleted. Days <= disk_projection_days_warn while more than half of the window's data has no ILM
    phase after hot (no move, no delete) → Warning; otherwise Info. Comparison mode (DIF-008) measures real growth instead.
    """
    now = _now_ms(ctx)
    if not now:
        return []
    win = ctx.t["ingest_window_days"] * DAY_MS
    writes = set(i for i in ctx.write_targets() if i)
    created = {}
    for name in ctx.index_settings.keys():
        if ctx.is_system_index(name) or ctx.is_searchable_snapshot(name):
            continue
        try:
            created[name] = float(str(ctx.index_setting(name, "index.creation_date")))
        except (TypeError, ValueError):
            continue
    if not created:
        return []
    span = min(win, now - min(created.values()))
    if span < DAY_MS:
        return []
    window_bytes, stays, contrib = 0.0, 0.0, collections.Counter()
    for name, c in created.items():
        size = num(ctx.indices_stats, name, "total", "store", "size_in_bytes")
        age = now - c
        if age <= 0 or not size:
            continue
        if age <= span:
            part = size
        elif name in writes:
            part = size * span / age
        else:
            continue
        window_bytes += part
        ds = ctx.data_stream_of(name)
        key = str(ds.get("name") or name) if isinstance(ds, dict) else name
        contrib[key] += part
        if not _drains(ctx, name):
            stays += part
    if window_bytes <= 0:
        return []
    daily = window_bytes / (span / DAY_MS)
    tiers = _node_tiers(ctx)
    landing = set()
    for sh in ctx.shards:
        if sh.get("index") in writes and sh.get("node") and tiers.get(sh["node"]) and tiers[sh["node"]] != "frozen":
            landing.add(tiers[sh["node"]])
    if not landing:
        landing = set(t for t in tiers.values() if t and ("hot" in t or t in ("content", "data(generic)")))
    head, nodes = 0.0, 0
    for n in ctx.data_nodes:
        if tiers.get(n.name) not in landing or not n.fs_total:
            continue
        high = ctx.watermark_used_pct("high", n.fs_total) or 90.0
        used = n.fs_total - (n.fs_avail or 0)
        head += max(0.0, high / 100.0 * n.fs_total - used)
        nodes += 1
    if not nodes:
        return []
    days = head / daily if daily else None
    stay_share = stays / window_bytes
    warn = days is not None and days <= ctx.t["disk_projection_days_warn"] and stay_share > 0.5
    top = [[k, fmt_bytes(v / (span / DAY_MS)) + "/d"] for k, v in contrib.most_common(10)]
    return [Finding(
        "COST-004", CAT, Severity.WARNING if warn else Severity.INFO, T("rules.cost.r_ingest_headroom.01"),
        observed=T("rules.cost.r_ingest_headroom.02") % (
            fmt_bytes(daily), span / DAY_MS, ", ".join(sorted(landing)), nodes, fmt_bytes(head),
            days if days is not None else 0, stay_share * 100),
        impact=T("rules.cost.r_ingest_headroom.03"),
        recommend=T("rules.cost.r_ingest_headroom.04"),
        evidence=table([T("rules.cost.r_ingest_headroom.05"), T("rules.cost.r_ingest_headroom.06")], top),
        refs=[D_TIERS], source="settings.json / indices_stats.json / nodes_stats.json")]


RULES = [r_hot_rolled_over, r_idle_replicas, r_tier_usage, r_ingest_headroom]
