# -*- coding: utf-8 -*-
"""Cluster-level rules."""

import collections

from ..i18n import T, N_, tr
from ..model import Finding, Severity, table
from ..util import dig, fmt_ms, fmt_num, dicts, num, items, truncate

CAT = "cluster"
DOC_ALLOC = (N_("rules.cluster._.01"),
             "https://www.elastic.co/docs/troubleshoot/elasticsearch/diagnose-unassigned-shards")
DOC_HEALTH = (N_("rules.cluster._.02"),
              "https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-cluster-health")
DOC_SIZE = (N_("rules.cluster._.03"),
            "https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards")


def r_cluster_status(ctx):
    """Reports cluster_health.status as is. red → Critical, yellow → Warning, green → OK."""
    st = (ctx.health.get("status") or "").lower()
    active_pct = ctx.health.get("active_shards_percent_as_number")
    ev = table(
        [T("rules.cluster.r_cluster_status.01"), T("rules.cluster.r_cluster_status.02")],
        [["status", st or "-"],
         [T("rules.cluster.r_cluster_status.03"), "%s / %s" % (ctx.health.get("number_of_nodes"),
                                            ctx.health.get("number_of_data_nodes"))],
         ["active primary / active total", "%s / %s" % (ctx.health.get("active_primary_shards"),
                                                       ctx.health.get("active_shards"))],
         ["unassigned / unassigned primary", "%s / %s" % (ctx.health.get("unassigned_shards"),
                                                          ctx.health.get("unassigned_primary_shards"))],
         ["relocating / initializing", "%s / %s" % (ctx.health.get("relocating_shards"),
                                                    ctx.health.get("initializing_shards"))],
         ["active_shards_percent", "%s%%" % active_pct]])
    if st == "red":
        return [Finding("CLU-001", CAT, Severity.CRITICAL, T("rules.cluster.r_cluster_status.04"),
                        observed=T("rules.cluster.r_cluster_status.05") %
                                 ctx.health.get("unassigned_primary_shards"),
                        impact=T("rules.cluster.r_cluster_status.06"),
                        recommend=T("rules.cluster.r_cluster_status.07"),
                        evidence=ev, refs=[DOC_ALLOC], source="cluster_health.json")]
    if st == "yellow":
        return [Finding("CLU-001", CAT, Severity.WARNING, T("rules.cluster.r_cluster_status.08"),
                        observed=T("rules.cluster.r_cluster_status.09") % ctx.health.get("unassigned_shards"),
                        impact=T("rules.cluster.r_cluster_status.10"),
                        recommend=T("rules.cluster.r_cluster_status.11"),
                        evidence=ev, refs=[DOC_ALLOC], source="cluster_health.json")]
    return [Finding("CLU-001", CAT, Severity.OK, T("rules.cluster.r_cluster_status.12"),
                    observed=T("rules.cluster.r_cluster_status.13"),
                    evidence=ev, source="cluster_health.json")]


def r_unassigned_reason(ctx):
    """Counts shards with state=UNASSIGNED in the shard list, grouped by unassigned.reason. Any unassigned primary → Critical; replicas only → Warning (CLU-002). If allocation_explain.json is present, the decider result is reported too: can_allocate != yes → Warning, otherwise Info (CLU-003)."""
    rows = []
    reasons = collections.Counter()
    for s in ctx.shards:
        if (s.get("state") or "").upper() == "UNASSIGNED" or s.get("ur"):
            reason = s.get("ur") or s.get("unassigned.reason") or "UNKNOWN"
            reasons[reason] += 1
            if len(rows) < ctx.t["top_n"]:
                rows.append([s.get("index"), s.get("shard"), s.get("prirep"),
                             reason, (s.get("ud") or s.get("unassigned.details") or "")[:120]])
    out = []
    if reasons:
        sev = Severity.CRITICAL if any(
            (s.get("prirep") == "p") for s in ctx.shards
            if (s.get("state") or "").upper() == "UNASSIGNED") else Severity.WARNING
        out.append(Finding(
            "CLU-002", CAT, sev, T("rules.cluster.r_unassigned_reason.01"),
            observed=T("rules.cluster.r_unassigned_reason.02") % (
                sum(reasons.values()),
                ", ".join("%s=%d" % (k, v) for k, v in reasons.most_common())),
            impact=T("rules.cluster.r_unassigned_reason.03"),
            recommend=T("rules.cluster.r_unassigned_reason.04"),
            evidence=table(["index", "shard", "p/r", "reason", "detail"], rows),
            refs=[DOC_ALLOC], source="indices.json / shards.json"))
    err = dig(ctx.allocation_explain, "error", "reason")
    if ctx.allocation_explain and not err:
        can_alloc = ctx.allocation_explain.get("can_allocate")
        expl = ctx.allocation_explain.get("allocate_explanation") or ""
        deciders = []
        for na in dicts(ctx.allocation_explain.get("node_allocation_decisions")):
            for d in dicts(na.get("deciders")):
                deciders.append([na.get("node_name"), d.get("decider"),
                                 d.get("decision"), truncate(d.get("explanation") or "", 240)])
        target = "%s[%s] %s" % (ctx.allocation_explain.get("index"), ctx.allocation_explain.get("shard"),
                                "primary" if ctx.allocation_explain.get("primary") else "replica")
        no_dec = sorted(set(r[1] for r in deciders if str(r[2]).upper() == "NO" and r[1]))
        out.append(Finding(
            "CLU-003", CAT, Severity.WARNING if can_alloc != "yes" else Severity.INFO,
            T("rules.cluster.r_unassigned_reason.05"),
            observed=(T("rules.cluster.r_unassigned_reason.06") % (target, can_alloc, ", ".join(no_dec)))
                     if no_dec else ("%s: can_allocate=%s. %s" % (target, can_alloc, truncate(expl, 200))),
            impact=T("rules.cluster.r_unassigned_reason.07"),
            recommend=T("rules.cluster.r_unassigned_reason.08"),
            evidence=table(["node", "decider", "decision", "explanation"],
                           deciders[: ctx.t["top_n"]]),
            refs=[DOC_ALLOC], source="allocation_explain.json"))
    return out


def r_internal_health(ctx):
    """Passes through the Health API (_health_report) indicators. Any indicator red → Critical, yellow → Warning, all green → OK. unknown is not rated."""
    inds = (ctx.internal_health or {}).get("indicators") or {}
    if not inds:
        return []
    bad = []
    rows = []
    for name, ind in items(inds):
        if not isinstance(ind, dict):
            continue
        status = (ind.get("status") or "").lower()
        rows.append([name, status, (ind.get("symptom") or "")[:120]])
        if status not in ("green", "unknown"):
            bad.append((name, ind))
    if not bad:
        return [Finding("CLU-004", CAT, Severity.OK, T("rules.cluster.r_internal_health.01"),
                        observed=T("rules.cluster.r_internal_health.02") % len(inds),
                        evidence=table(["indicator", "status", "symptom"], rows),
                        source="internal_health.json")]
    out = []
    for name, ind in bad:
        status = (ind.get("status") or "").lower()
        sev = Severity.CRITICAL if status == "red" else Severity.WARNING
        actions = []
        for d in dicts(ind.get("diagnosis")):
            actions.append((d.get("cause") or "") + " → " + (d.get("action") or ""))
        out.append(Finding(
            "CLU-004." + name, CAT, sev, T("rules.cluster.r_internal_health.03") % (name, status),
            observed=ind.get("symptom") or "",
            impact=T("rules.cluster.r_internal_health.04"),
            recommend=" / ".join(actions) if actions else
                      T("rules.cluster.r_internal_health.05"),
            evidence=table(["key", "value"],
                           [[k, str(v)[:200]] for k, v in items(ind.get("details"))]),
            source="internal_health.json"))
    return out


def r_pending_tasks(ctx):
    """Master pending tasks. Count >= pending_tasks_crit or longest wait >= max_task_wait_ms_warn x 4 → Critical; count >= pending_tasks_warn or longest wait >= max_task_wait_ms_warn → Warning."""
    n = num(ctx.health, "number_of_pending_tasks")
    wait = num(ctx.health, "task_max_waiting_in_queue_millis")
    tasks = (ctx.pending_tasks or {}).get("tasks") or []
    if n >= ctx.t["pending_tasks_crit"] or wait >= ctx.t["max_task_wait_ms_warn"] * 4:
        sev = Severity.CRITICAL
    elif n >= ctx.t["pending_tasks_warn"] or wait >= ctx.t["max_task_wait_ms_warn"]:
        sev = Severity.WARNING
    else:
        return []
    rows = [[t.get("priority"), t.get("source", "")[:100], t.get("time_in_queue")]
            for t in tasks[: ctx.t["top_n"]]]
    return [Finding(
        "CLU-005", CAT, sev, T("rules.cluster.r_pending_tasks.01"),
        observed=T("rules.cluster.r_pending_tasks.02") % (n, fmt_ms(wait)),
        impact=T("rules.cluster.r_pending_tasks.03"),
        recommend=T("rules.cluster.r_pending_tasks.04"),
        evidence=table(["priority", "source", "time_in_queue"], rows),
        source="cluster_health.json / cluster_pending_tasks.json")]


def r_master_quorum(ctx):
    """Number of master-eligible nodes (roles include master, voting_only included). 0 → Critical; 1 in a multi-node cluster → Critical; 2 → Warning (losing one node loses quorum; official guidance: with 2 or fewer master-eligible nodes, all of them must stay up). An even count (4 or more) is not rated, because ES automatically leaves one node out of the voting configuration (CLU-006). No dedicated master and >= dedicated_master_data_nodes data nodes → Warning (CLU-007). The official docs only say dedicated masters make sense once a cluster has more than a handful of nodes; the node count is a field guideline."""
    [n for n in ctx.master_nodes if not n.is_voting_only]
    total = len(ctx.master_nodes)
    out = []
    names = [n.name for n in ctx.master_nodes]
    if total == 0:
        return [Finding("CLU-006", CAT, Severity.CRITICAL, T("rules.cluster.r_master_quorum.01"),
                        observed=T("rules.cluster.r_master_quorum.02"),
                        impact=T("rules.cluster.r_master_quorum.03"),
                        recommend=T("rules.cluster.r_master_quorum.04"), source="nodes.json")]
    if total == 1 and len(ctx.nodes) > 1:
        out.append(Finding("CLU-006", CAT, Severity.CRITICAL, T("rules.cluster.r_master_quorum.05"),
                           observed=T("rules.cluster.r_master_quorum.06") % names[0],
                           impact=T("rules.cluster.r_master_quorum.07"),
                           recommend=T("rules.cluster.r_master_quorum.08"),
                           affected=names, source="nodes.json"))
    elif total == 2:
        out.append(Finding("CLU-006", CAT, Severity.WARNING, T("rules.cluster.r_master_quorum.09"),
                           observed=T("rules.cluster.r_master_quorum.10") % ", ".join(names),
                           impact=T("rules.cluster.r_master_quorum.11"),
                           recommend=T("rules.cluster.r_master_quorum.12"),
                           affected=names, source="nodes.json"))
    # Dedicated master recommendation
    dedicated = [n for n in ctx.master_nodes if n.is_dedicated_master]
    if not dedicated and len(ctx.data_nodes) >= ctx.t["dedicated_master_data_nodes"]:
        out.append(Finding("CLU-007", CAT, Severity.WARNING, T("rules.cluster.r_master_quorum.13"),
                           observed=T("rules.cluster.r_master_quorum.14")
                                    % len(ctx.data_nodes),
                           impact=T("rules.cluster.r_master_quorum.15"),
                           recommend=T("rules.cluster.r_master_quorum.16"),
                           source="nodes.json"))
    return out


def r_version_consistency(ctx):
    """More than 1 ES version across nodes → Warning (CLU-008). Major version < eol_major_below → Warning (CLU-009). More than 1 JVM version across nodes → Warning (CLU-010)."""
    out = []
    vers = collections.Counter(n.version for n in ctx.nodes if n.version)
    if len(vers) > 1:
        out.append(Finding(
            "CLU-008", CAT, Severity.WARNING, T("rules.cluster.r_version_consistency.01"),
            observed=T("rules.cluster.r_version_consistency.02") % ", ".join(T("rules.cluster.r_version_consistency.03") % (v, c) for v, c in vers.items()),
            impact=T("rules.cluster.r_version_consistency.04"),
            recommend=T("rules.cluster.r_version_consistency.05"),
            evidence=table(["node", "version"], [[n.name, n.version] for n in ctx.nodes]),
            source="nodes.json"))
    major = ctx.version_tuple[0]
    if major and major < ctx.t["eol_major_below"]:
        out.append(Finding(
            "CLU-009", CAT, Severity.WARNING, T("rules.cluster.r_version_consistency.06"),
            observed=T("rules.cluster.r_version_consistency.07") % ctx.version,
            impact=T("rules.cluster.r_version_consistency.08"),
            recommend=T("rules.cluster.r_version_consistency.09"),
            source="version.json"))
    jvms = collections.Counter(dig(n.info, "jvm", "version") for n in ctx.nodes
                               if dig(n.info, "jvm", "version"))
    if len(jvms) > 1:
        out.append(Finding(
            "CLU-010", CAT, Severity.WARNING, T("rules.cluster.r_version_consistency.10"),
            observed=T("rules.cluster.r_version_consistency.11") % ", ".join(T("rules.cluster.r_version_consistency.03") % (v, c) for v, c in jvms.items()),
            impact=T("rules.cluster.r_version_consistency.12"),
            recommend=T("rules.cluster.r_version_consistency.13"),
            evidence=table(["node", "jvm"], [[n.name, dig(n.info, "jvm", "version")]
                                             for n in ctx.nodes]),
            source="nodes.json"))
    return out


RISKY_SETTINGS = [
    ("cluster.routing.allocation.enable", lambda v: str(v).lower() not in ("all", "none_checked"),
     Severity.CRITICAL,
     N_("rules.cluster._.04"),
     N_("rules.cluster._.05")),
    ("cluster.routing.rebalance.enable", lambda v: str(v).lower() != "all", Severity.WARNING,
     N_("rules.cluster._.06"),
     N_("rules.cluster._.07")),
    ("cluster.routing.allocation.disk.threshold_enabled", lambda v: str(v).lower() == "false",
     Severity.CRITICAL,
     N_("rules.cluster._.08"),
     N_("rules.cluster._.09")),
    ("cluster.blocks.read_only", lambda v: str(v).lower() == "true", Severity.CRITICAL,
     N_("rules.cluster._.10"),
     N_("rules.cluster._.11")),
    ("cluster.blocks.read_only_allow_delete", lambda v: str(v).lower() == "true", Severity.CRITICAL,
     N_("rules.cluster._.12"),
     N_("rules.cluster._.13")),
    ("action.destructive_requires_name", lambda v: str(v).lower() == "false", Severity.WARNING,
     N_("rules.cluster._.14"),
     N_("rules.cluster._.15")),
    ("indices.recovery.max_bytes_per_sec", lambda v: False, Severity.INFO, "", ""),
]


def r_risky_settings(ctx):
    """Rates only cluster settings that differ from the default (explicitly set in persistent/transient). allocation.enable != all → Critical, rebalance.enable != all → Warning, disk.threshold_enabled=false → Critical, cluster.blocks.read_only(_allow_delete)=true → Critical, destructive_requires_name=false → Warning (CLU-011). A value in allocation.exclude._name/_ip/_host → Warning (CLU-012). Any transient setting → Info (CLU-013, no longer recommended since 7.16). use_adaptive_replica_selection=false → Warning (CLU-014, default is true)."""
    out = []
    rows = []
    for scope in ("persistent", "transient"):
        for k, v in items(ctx.cluster_settings.get(scope)):
            rows.append([scope, k, str(v)[:120]])
    for key, is_bad, sev, impact, rec in RISKY_SETTINGS:
        src = ctx.setting_source(key)
        if src == "default":
            continue
        v = ctx.setting(key)
        try:
            bad = is_bad(v)
        except Exception:
            bad = False
        if bad:
            out.append(Finding(
                "CLU-011." + key, CAT, sev, T("rules.cluster.r_risky_settings.01") % key,
                observed="%s = %s (%s)" % (key, v, src),
                impact=tr(impact), recommend=tr(rec),
                source="cluster_settings.json"))
    # Leftover allocation excludes
    for key in ("cluster.routing.allocation.exclude._name",
                "cluster.routing.allocation.exclude._ip",
                "cluster.routing.allocation.exclude._host"):
        v = ctx.setting(key)
        if v and str(v) not in ("", "null", "no_instances_excluded"):
            out.append(Finding(
                "CLU-012", CAT, Severity.WARNING, T("rules.cluster.r_risky_settings.02"),
                observed="%s = %s" % (key, v),
                impact=T("rules.cluster.r_risky_settings.03"),
                recommend=T("rules.cluster.r_risky_settings.04"),
                source="cluster_settings.json"))
    if ctx.cluster_settings.get("transient"):
        out.append(Finding(
            "CLU-013", CAT, Severity.INFO, T("rules.cluster.r_risky_settings.05"),
            observed=T("rules.cluster.r_risky_settings.06") % len(ctx.cluster_settings["transient"]),
            impact=T("rules.cluster.r_risky_settings.07"),
            recommend=T("rules.cluster.r_risky_settings.08"),
            evidence=table(["scope", "key", "value"],
                           [r for r in rows if r[0] == "transient"]),
            source="cluster_settings.json"))
    if ctx.setting("cluster.routing.use_adaptive_replica_selection") is not None and \
            str(ctx.setting("cluster.routing.use_adaptive_replica_selection")).lower() == "false":
        out.append(Finding(
            "CLU-014", CAT, Severity.WARNING, T("rules.cluster.r_risky_settings.09"),
            observed="cluster.routing.use_adaptive_replica_selection = false",
            impact=T("rules.cluster.r_risky_settings.10"),
            recommend=T("rules.cluster.r_risky_settings.11"),
            source="cluster_settings.json"))
    return out


def r_shard_capacity(ctx):
    """Usage of the cluster shard limit (CLU-015).

    Official counting: cluster.max_shards_per_node applies to non-frozen data nodes and counts the primary and replica shards of
    open indices, unassigned ones included; closed indices do not count, and frozen (partially mounted) indices count against
    cluster.max_shards_per_node.frozen instead. Usage = (active + unassigned - shards of partially mounted indices - shards of
    closed indices) / (cluster.max_shards_per_node x non-frozen data nodes). Closed indices come from cat indices (status close).
    >= max_shards_per_node_headroom_pct_warn → Warning, >= max_shards_per_node_crit_pct → Critical.
    """
    out = []
    max_per_node = ctx.setting("cluster.max_shards_per_node", 1000)
    try:
        max_per_node = int(max_per_node)
    except (TypeError, ValueError):
        max_per_node = 1000
    frozen_only = set(n.name for n in ctx.data_nodes
                      if [r for r in n.roles if r.startswith("data")] == ["data_frozen"])
    data_nodes = len([n for n in ctx.data_nodes if n.name not in frozen_only]) or len(ctx.nodes)
    limit = max_per_node * data_nodes
    frozen_shards = len([sh for sh in ctx.shards if ctx.is_partial_mount(sh.get("index"))])
    closed_shards = 0
    for r in ctx.cat_indices or []:
        if not isinstance(r, dict) or str(r.get("status") or "").lower() != "close":
            continue
        try:
            closed_shards += int(str(r.get("pri") or 0)) * (1 + int(str(r.get("rep") or 0)))
        except ValueError:
            continue
    open_shards = max(0, (num(ctx.health, "active_shards")) + (num(ctx.health, "unassigned_shards"))
                      - frozen_shards - closed_shards)
    used = (float(open_shards) / limit * 100.0) if limit else None
    if used is not None and used >= ctx.t["max_shards_per_node_headroom_pct_warn"]:
        out.append(Finding(
            "CLU-015", CAT,
            Severity.CRITICAL if used >= ctx.t["max_shards_per_node_crit_pct"] else Severity.WARNING,
            T("rules.cluster.r_shard_capacity.01"),
            observed=T("rules.cluster.r_shard_capacity.02")
                     % (fmt_num(open_shards), fmt_num(limit), used, max_per_node, data_nodes),
            impact=T("rules.cluster.r_shard_capacity.03"),
            recommend=T("rules.cluster.r_shard_capacity.04"),
            refs=[DOC_SIZE], source="cluster_health.json / cluster_settings.json"))
    return out


def r_dangling(ctx):
    """Warning if there is 1 or more dangling index."""
    d = (ctx.dangling or {}).get("dangling_indices") or []
    if not d:
        return []
    return [Finding(
        "CLU-016", CAT, Severity.WARNING, T("rules.cluster.r_dangling.01"),
        observed=T("rules.cluster.r_dangling.02") % len(d),
        impact=T("rules.cluster.r_dangling.03"),
        recommend=T("rules.cluster.r_dangling.04"),
        evidence=table(["index_name", "index_uuid", "creation_date"],
                       [[x.get("index_name"), x.get("index_uuid"),
                         x.get("creation_date_millis")] for x in d[: ctx.t["top_n"]]]),
        source="dangling_indices.json")]


# Always-running persistent tasks are expected to run for a long time, so they are excluded.
PERSISTENT_TASK_HINTS = ("[c]", "health-node", "geoip-downloader", "poller",
                         "xpack/ml/job", "xpack/ml/datafeed", "data_frame/transforms",
                         "monitoring", "security/token", "system_index_migration",
                         "indices:data/read/search/scroll/keep_alive")


def _is_persistent_task(action, desc):
    blob = "%s %s" % (action or "", desc or "")
    return any(h in blob for h in PERSISTENT_TASK_HINTS)


WRITE_TASK_PREFIXES = ("indices:data/write/bulk", "indices:data/write/reindex", "indices:data/write/update/byquery",
                       "indices:data/write/delete/byquery", "indices:admin/forcemerge", "indices:admin/resize")
MONITOR_TASK_PREFIXES = ("cluster:monitor/", "indices:monitor/", "internal:")


def r_long_tasks(ctx):
    """Long-running tasks grouped by action (CLU-017). Always-running persistent tasks are excluded.

    Monitoring and internal tasks (cluster:monitor/*, indices:monitor/*, internal:*) are reported only past
    monitoring_task_ms_info. Other tasks: longest run >= long_running_task_ms_high → Warning, >= long_running_task_ms_warn → Info.
    Write-path actions (bulk, reindex, update/delete by query, forcemerge, shrink/split/clone) are marked, because a stuck
    write task holds resources and blocks follow-up work. One row per action with the task count and the longest run.
    """
    groups = {}
    for _nid, node in items(ctx.tasks.get("nodes")):
        if not isinstance(node, dict):
            continue
        for _tid, t in items(node.get("tasks")):
            if not isinstance(t, dict):
                continue
            run = num(t, "running_time_in_nanos")
            ms = (run / 1e6) if run else 0
            action = str(t.get("action") or "")
            desc = str(t.get("description") or "")
            if not action or _is_persistent_task(action, desc):
                continue
            monitor = action.startswith(MONITOR_TASK_PREFIXES)
            limit = ctx.t["monitoring_task_ms_info"] if monitor else ctx.t["long_running_task_ms_warn"]
            if ms < limit:
                continue
            g = groups.setdefault(action, {"count": 0, "max": 0, "nodes": set(), "desc": "", "monitor": monitor})
            g["count"] += 1
            g["nodes"].add(str(node.get("name") or _nid))
            if ms > g["max"]:
                g["max"], g["desc"] = ms, desc
    if not groups:
        return []
    high = ctx.t["long_running_task_ms_high"]
    rows, warn = [], 0
    for action, g in sorted(groups.items(), key=lambda kv: -kv[1]["max"]):
        kind = T("rules.cluster.r_long_tasks.05") if action.startswith(WRITE_TASK_PREFIXES) else \
            (T("rules.cluster.r_long_tasks.06") if g["monitor"] else T("rules.cluster.r_long_tasks.07"))
        if not g["monitor"] and g["max"] >= high:
            warn += 1
        nodes = sorted(g["nodes"])
        rows.append([action, kind, g["count"], fmt_ms(g["max"]),
                     ", ".join(nodes[:3]) + (" +%d" % (len(nodes) - 3) if len(nodes) > 3 else ""), g["desc"][:100]])
    return [Finding(
        "CLU-017", CAT, Severity.WARNING if warn else Severity.INFO, T("rules.cluster.r_long_tasks.01"),
        observed=T("rules.cluster.r_long_tasks.02") % (len(groups), sum(g["count"] for g in groups.values()), warn, fmt_ms(high)),
        impact=T("rules.cluster.r_long_tasks.03"),
        recommend=T("rules.cluster.r_long_tasks.04"),
        evidence=table(["action", T("rules.cluster.r_long_tasks.08"), T("rules.cluster.r_long_tasks.09"),
                        T("rules.cluster.r_long_tasks.10"), "node", "description"], rows[: ctx.t["top_n"]]),
        source="tasks.json")]


def r_zone_balance(ctx):
    """Rated only when the data nodes have 2 or more distinct zone attribute values (availability_zone / zone / logical_availability_zone / rack_id). Node count per zone: max - min >= 2 or max >= min x 2 → Warning (CLU-018). awareness.attributes not set → Warning (CLU-019)."""
    zones = collections.Counter()
    for n in ctx.data_nodes:
        z = n.attrs.get("availability_zone") or n.attrs.get("zone") or \
            n.attrs.get("logical_availability_zone") or n.attrs.get("rack_id")
        if z:
            zones[z] += 1
    if len(zones) < 2:
        return []
    mx, mn = max(zones.values()), min(zones.values())
    awareness = ctx.setting("cluster.routing.allocation.awareness.attributes")
    out = []
    if mx - mn >= 2 or (mx > mn and mx >= 2 * mn):
        out.append(Finding(
            "CLU-018", CAT, Severity.WARNING, T("rules.cluster.r_zone_balance.01"),
            observed=T("rules.cluster.r_zone_balance.02") % ", ".join("%s=%d" % kv for kv in zones.items()),
            impact=T("rules.cluster.r_zone_balance.03"),
            recommend=T("rules.cluster.r_zone_balance.04"),
            source="nodes.json"))
    if not awareness and len(zones) >= 2:
        out.append(Finding(
            "CLU-019", CAT, Severity.WARNING, T("rules.cluster.r_zone_balance.05"),
            observed=T("rules.cluster.r_zone_balance.06")
                     % len(zones),
            impact=T("rules.cluster.r_zone_balance.07"),
            recommend=T("rules.cluster.r_zone_balance.08"),
            source="cluster_settings.json / nodes.json"))
    return out


def r_recovery_inflight(ctx):
    """Info if recovery.json has any shard with stage != DONE."""
    active = []
    for index, body in items(ctx.recovery):
        for sh in dicts(body.get("shards") if isinstance(body, dict) else None):
            if (sh.get("stage") or "").upper() != "DONE":
                active.append([index, sh.get("id"), sh.get("stage"), sh.get("type"),
                               sh.get("total_time"),
                               dig(sh, "index", "size", "percent") or "-"])
    if not active:
        return []
    return [Finding(
        "CLU-020", CAT, Severity.INFO, T("rules.cluster.r_recovery_inflight.01"),
        observed=T("rules.cluster.r_recovery_inflight.02") % len(active),
        impact=T("rules.cluster.r_recovery_inflight.03"),
        recommend=T("rules.cluster.r_recovery_inflight.04"),
        evidence=table(["index", "shard", "stage", "type", "elapsed", "progress"],
                       active[: ctx.t["top_n"]]),
        source="recovery.json")]


RULES = [
    r_cluster_status, r_unassigned_reason, r_internal_health, r_pending_tasks,
    r_master_quorum, r_version_consistency, r_risky_settings, r_shard_capacity,
    r_dangling, r_long_tasks, r_zone_balance, r_recovery_inflight,
]
