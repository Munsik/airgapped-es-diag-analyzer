# -*- coding: utf-8 -*-
"""Settings change analysis.

Official precedence: transient > persistent > elasticsearch.yml > default.
Finds settings that differ from the default and reports original default / current value / meaning / impact of the change / dynamic or static.
Defaults come from settings_kb (based on the official docs). Settings not registered there are reported with the value only.
"""

import collections

from ..i18n import T
from ..model import Finding, Severity, table
from ..util import items, num
from ..settings_kb import DOCS, compare, default_for, effect_of, lookup, risk_of

CAT = "settings"
_SEV = {"WARNING": Severity.WARNING, "INFO": Severity.INFO, None: Severity.INFO}

# Settings that normally differ per node, or that the tool does not judge
_NODE_SPECIFIC = ("node.name", "node.attr.", "node.id", "node.roles", "node.external_id", "path.",
                  "network.", "http.host", "http.port", "http.publish", "http.bind", "transport.host",
                  "transport.port", "transport.publish", "transport.bind", "discovery.",
                  "cluster.initial_master_nodes", "cluster.name", "pidfile", "client.type",
                  "xpack.security.", "xpack.ml.config_version", "xpack.transform.config_version",
                  "cloud.", "s3.client.", "gcs.client.", "azure.client.", "node.pidfile")

# Scope of settings that must match across nodes (when explicitly set)
_CONSISTENCY_PREFIX = ("indices.", "thread_pool.", "search.", "http.max_", "transport.compress",
                       "node.processors", "bootstrap.memory_lock", "xpack.ml.", "node.store.")


# Settings judged by a dedicated rule: listed in the table but excluded from the SET severity (avoids double findings)
DEDICATED = {
    "cluster.routing.allocation.enable": "CLU-011", "cluster.routing.rebalance.enable": "CLU-011",
    "cluster.routing.allocation.disk.threshold_enabled": "CLU-011", "cluster.blocks.read_only": "CLU-011",
    "cluster.blocks.read_only_allow_delete": "CLU-011", "action.destructive_requires_name": "CLU-011",
    "cluster.routing.use_adaptive_replica_selection": "CLU-014", "cluster.max_shards_per_node": "CLU-015",
    "indices.recovery.max_bytes_per_sec": "REC-001", "search.default_search_timeout": "PERF-006",
    "cluster.routing.allocation.awareness.attributes": "CLU-019",
    "index.blocks.write": "IDX-008", "index.blocks.read_only": "IDX-008",
    "index.blocks.read_only_allow_delete": "IDX-008", "index.number_of_replicas": "IDX-001",
    "index.max_result_window": "GEN-001", "index.mapping.total_fields.limit": "MAP-001",
    "index.unassigned.node_left.delayed_timeout": "CLU-021", "index.refresh_interval": "IDX-007",
    "index.codec": "DISK-006", "index.store.preload": "PERF-008",
}


def _dedicated_note(key):
    for k, rid in DEDICATED.items():
        if key == k or (k.endswith(".") and key.startswith(k)):
            return rid
    if key.startswith("cluster.routing.allocation.exclude."):
        return "CLU-012"
    return None


def _flat(d, prefix=""):
    out = {}
    for k, v in items(d):
        key = prefix + "." + k if prefix else k
        if isinstance(v, dict):
            out.update(_flat(v, key))
        else:
            out[key] = v
    return out


def _es_defaults(ctx):
    return _flat((ctx.cluster_settings_defaults or {}).get("defaults") or {})


def _refs(*keys):
    out = [DOCS["stack"]]
    for k in keys:
        if k and DOCS.get(k) and DOCS[k] not in out:
            out.append(DOCS[k])
    return out


def _worst(sevs):
    order = {Severity.WARNING: 0, Severity.INFO: 1}
    return sorted(sevs, key=lambda s: order.get(s, 9))[0] if sevs else Severity.INFO


def r_cluster_setting_changes(ctx):
    """Compares every cluster setting explicitly set in persistent / transient with the official default.

    For settings whose default is registered in the official docs (settings_kb), reports 'original default / direction (↑↓) / impact of the change' (SET-001);
    for unregistered settings, reports only the value as 'no description registered'. A value identical to the default is reported separately as Info (SET-002, 'same as default').
    Severity is the highest risk among the change directions of the registered settings (Warning at most). Settings judged by a dedicated rule (CLU-011 and others) are listed but left out of the severity.
    No changes → OK.
    """
    rows, sevs, docs, same = [], [], set(), []
    for scope in ("transient", "persistent"):
        for key, val in sorted(_flat(ctx.cluster_settings.get(scope) or {}).items()):
            changed, direction, spec, default, dsrc = compare(key, val, default=default_for(key, ctx))
            if not changed:
                same.append([scope, key, str(val)])
                continue
            kind = spec["kind"] if spec else "-"
            ded = _dedicated_note(key)
            rows.append([key, scope, str(default) if default is not None else T("rules.settings.r_cluster_setting_changes.01"), str(val),
                         kind, (spec or {}).get("meaning", T("rules.settings.r_cluster_setting_changes.02")),
                         effect_of(spec, direction) + ((T("rules.settings.r_cluster_setting_changes.03") % ded) if ded else "")])
            if not ded:
                sevs.append(_SEV.get(risk_of(spec, direction), Severity.INFO))
            if spec:
                docs.add(spec["doc"])
    out = []
    if rows:
        orch = (T("rules.settings.r_cluster_setting_changes.04") % ctx.deployment
                if ctx.orchestrated else "")
        out.append(Finding(
            "SET-001", CAT, _worst(sevs), T("rules.settings.r_cluster_setting_changes.05"),
            observed=T("rules.settings.r_cluster_setting_changes.06")
                     % len(rows) + orch + (T("rules.settings.r_cluster_setting_changes.07")
                                           if any(_dedicated_note(r[0]) for r in rows) else ""),
            impact=T("rules.settings.r_cluster_setting_changes.08"),
            recommend=T("rules.settings.r_cluster_setting_changes.09"),
            evidence=table([T("rules.settings.r_cluster_setting_changes.10"), T("rules.settings.r_cluster_setting_changes.11"), T("rules.settings.r_cluster_setting_changes.12"), T("rules.settings.r_cluster_setting_changes.13"), T("rules.settings.r_cluster_setting_changes.14"), T("rules.settings.r_cluster_setting_changes.15"), T("rules.settings.r_cluster_setting_changes.16")], rows),
            refs=_refs("put", *sorted(docs)), source="cluster_settings.json"))
    else:
        out.append(Finding("SET-001", CAT, Severity.OK, T("rules.settings.r_cluster_setting_changes.17"),
                           observed=T("rules.settings.r_cluster_setting_changes.18"),
                           refs=_refs("put"), source="cluster_settings.json"))
    if same:
        out.append(Finding(
            "SET-002", CAT, Severity.INFO, T("rules.settings.r_cluster_setting_changes.19"),
            observed=T("rules.settings.r_cluster_setting_changes.20") % len(same)
                     + ((T("rules.settings.r_cluster_setting_changes.04") % ctx.deployment) if ctx.orchestrated else ""),
            impact=T("rules.settings.r_cluster_setting_changes.21"),
            recommend=T("rules.settings.r_cluster_setting_changes.22"),
            evidence=table([T("rules.settings.r_cluster_setting_changes.11"), T("rules.settings.r_cluster_setting_changes.10"), T("rules.settings.r_cluster_setting_changes.23")], same), refs=_refs("put"), source="cluster_settings.json"))
    return out


def _node_settings(n):
    return _flat(n.info.get("settings") or {})


def r_yml_shadowed(ctx):
    """Checks whether a value in elasticsearch.yml (node settings) is shadowed by persistent/transient.

    If the same key is set in both node settings and cluster API settings with different values, the API value applies per the official precedence
    and the yml value is ignored (Info). This tells you when editing the yml has no effect.
    """
    api = {}
    for scope in ("persistent", "transient"):
        for k, v in _flat(ctx.cluster_settings.get(scope) or {}).items():
            api[k] = (scope, v)          # transient is applied later, so it wins
    rows = []
    for n in ctx.nodes:
        for k, v in _node_settings(n).items():
            if k in api and str(api[k][1]) != str(v):
                rows.append([k, n.name, str(v), api[k][0], str(api[k][1])])
    if not rows:
        return []
    return [Finding(
        "SET-003", CAT, Severity.INFO, T("rules.settings.r_yml_shadowed.01"),
        observed=T("rules.settings.r_yml_shadowed.02") % len(rows),
        impact=T("rules.settings.r_yml_shadowed.03"),
        recommend=T("rules.settings.r_yml_shadowed.04"),
        evidence=table([T("rules.settings.r_yml_shadowed.05"), T("rules.settings.r_yml_shadowed.06"), T("rules.settings.r_yml_shadowed.07"), T("rules.settings.r_yml_shadowed.08"), T("rules.settings.r_yml_shadowed.09")], rows[: ctx.t["top_n"] * 3]),
        refs=_refs("put"), source="nodes.json / cluster_settings.json")]


def r_node_setting_changes(ctx):
    """Checks whether node settings (elasticsearch.yml, including static ones) with a registered official default differ from that default.

    Node-specific settings (name, paths, network, security certificates, etc.) are excluded. Values are collected across nodes and reported per setting and value;
    severity is the highest risk among the change directions (Warning at most, settings with a dedicated rule excluded). node.processors, thread_pool.write.size and thread_pool.search.size
    are not treated as changes when they equal the value derived from the allocated CPU count. If ECH/ECE/ECK is detected, the values are treated as platform-managed and reduced to Info.
    A static setting needs a yml edit and a restart on every target node.
    """
    agg = collections.OrderedDict()
    for n in ctx.nodes:
        for k, v in sorted(_node_settings(n).items()):
            if k.startswith(_NODE_SPECIFIC):
                continue
            spec = lookup(k)
            if not spec:
                continue
            changed, direction, spec, default, _src = compare(k, v, default=default_for(k, ctx, node=n))
            if not changed:
                continue
            alloc = num(n.info, "os", "allocated_processors") or n.processors
            avail = num(n.info, "os", "available_processors") or None
            # allocated_processors is derived from node.processors itself, so node.processors is compared with the CPUs ES sees
            expected = {"node.processors": avail,
                        "thread_pool.write.size": alloc,
                        "thread_pool.search.size": (int(alloc * 3 / 2) + 1) if alloc else None}
            if k in expected and expected[k]:
                try:
                    if float(v) == float(expected[k]):
                        continue        # Same as the auto-computed value, so not a change
                except (TypeError, ValueError):
                    pass
            agg.setdefault((k, str(v)), {"nodes": [], "spec": spec, "dir": direction, "default": default})
            agg[(k, str(v))]["nodes"].append(n.name)
    if not agg:
        return []
    rows, sevs, docs = [], [], set()
    for (k, v), info in agg.items():
        spec = info["spec"]
        ded = _dedicated_note(k)
        rows.append([k, str(info["default"]), v, spec["kind"], T("rules.settings.r_node_setting_changes.01") % len(info["nodes"]),
                     spec["meaning"], effect_of(spec, info["dir"]) + ((T("rules.settings.r_node_setting_changes.02") % ded) if ded else "")])
        if not ded:
            sevs.append(_SEV.get(risk_of(spec, info["dir"]), Severity.INFO))
        docs.add(spec["doc"])
    sev = _worst(sevs) if sevs else Severity.INFO
    orch = ""
    if ctx.orchestrated:
        sev = Severity.INFO
        orch = (T("rules.settings.r_node_setting_changes.03")
                % ctx.deployment)
    # A dynamic key in node settings can be overridden through the API,
    # but if it is in the yml every new node gets the same value.
    return [Finding(
        "SET-004", CAT, sev, T("rules.settings.r_node_setting_changes.04"),
        observed=T("rules.settings.r_node_setting_changes.05") % len(rows) + orch,
        impact=T("rules.settings.r_node_setting_changes.06"),
        recommend=T("rules.settings.r_node_setting_changes.07"),
        evidence=table([T("rules.settings.r_node_setting_changes.08"), T("rules.settings.r_node_setting_changes.09"), T("rules.settings.r_node_setting_changes.10"), T("rules.settings.r_node_setting_changes.11"), T("rules.settings.r_node_setting_changes.12"), T("rules.settings.r_node_setting_changes.13"), T("rules.settings.r_node_setting_changes.14")], rows),
        refs=_refs(*sorted(docs)), source="nodes.json")]


def r_node_setting_consistency(ctx):
    """Checks whether settings that should match across nodes (indexing buffer, caches, thread pools, search, transport, etc.) differ between nodes or are set on only some nodes.

    The scope is explicitly set keys under _CONSISTENCY_PREFIX, minus node-specific settings. Data nodes are compared only with
    nodes of the same data tier (all nodes if no data nodes are identified): tiers usually run on different hardware, so values
    such as node.processors differ between tiers by design. A setting missing on some nodes counts as a difference. Any mismatch → Warning.
    """
    dn = ctx.data_nodes or ctx.nodes
    if len(dn) < 2:
        return []
    groups = collections.OrderedDict()
    for n in dn:
        groups.setdefault((ctx.tier_of(n) or "-") if ctx.data_nodes else "-", []).append(n)
    missing = T("rules.settings.r_node_setting_consistency.01")
    rows = []
    for tier, nodes in groups.items():
        if len(nodes) < 2:
            continue
        values = collections.defaultdict(dict)
        for n in nodes:
            for k, v in _node_settings(n).items():
                if k.startswith(_CONSISTENCY_PREFIX) and not k.startswith(_NODE_SPECIFIC):
                    values[k][n.name] = str(v)
        names = [n.name for n in nodes]
        for k, m in sorted(values.items()):
            if len(set(m.get(nm, missing) for nm in names)) > 1:
                rows.append([k, tier, ", ".join("%s=%s" % (nm, m.get(nm, missing)) for nm in names)[:300]])
    if not rows:
        return []
    return [Finding(
        "SET-005", CAT, Severity.WARNING, T("rules.settings.r_node_setting_consistency.02"),
        observed=T("rules.settings.r_node_setting_consistency.03") % len(rows),
        impact=T("rules.settings.r_node_setting_consistency.04"),
        recommend=T("rules.settings.r_node_setting_consistency.05"),
        evidence=table([T("rules.settings.r_node_setting_consistency.06"), "tier", T("rules.settings.r_node_setting_consistency.07")],
                       rows[: ctx.t["top_n"] * 2]),
        refs=_refs(), source="nodes.json")]


def r_index_setting_changes(ctx):
    """Counts, per setting and value, the explicitly set settings of user indices that have a registered official default and differ from it.

    Identity information added automatically at index creation (uuid, creation_date, version, provided_name, number_of_shards,
    tier preference, etc.) has no registered default, so it is naturally excluded. System indices are excluded, and so are searchable
    snapshot mounts: ES sets their write block, 0 replicas and other settings when it mounts them, and they cannot be changed. The
    merge settings that data stream lifecycle writes on the indices it manages (floor_segment, merge_factor) are left out too.
    Severity is the highest risk among the change directions (Warning at most, settings with a dedicated rule excluded).
    """
    agg = collections.OrderedDict()
    for name, body in items(ctx.index_settings):
        if ctx.is_system_index(name) or ctx.is_searchable_snapshot(name):
            continue
        flat = _flat((body or {}).get("settings") or {})
        dlm = None
        for k, v in flat.items():
            spec = lookup(k)
            if not spec or spec["scope"] != "index":
                continue
            if k in ("index.merge.policy.floor_segment", "index.merge.policy.merge_factor"):
                if dlm is None:
                    dlm = ctx.dlm_managed(name)
                if dlm:
                    continue        # set by data stream lifecycle (DataStreamLifecycleService target merge settings)
            changed, direction, spec, default, _src = compare(k, v, default=default_for(k, ctx, index=name))
            if not changed:
                continue
            key = (k, str(v))
            agg.setdefault(key, {"idx": [], "spec": spec, "dir": direction, "default": default})
            agg[key]["idx"].append(name)
    if not agg:
        return []
    rows, sevs, docs = [], [], set()
    for (k, v), info in sorted(agg.items(), key=lambda kv: (kv[0][0], -len(kv[1]["idx"]))):
        spec = info["spec"]
        sample = ", ".join(info["idx"][:3]) + (T("rules.settings.r_index_setting_changes.01") % (len(info["idx"]) - 3) if len(info["idx"]) > 3 else "")
        ded = _dedicated_note(k)
        rows.append([k, str(info["default"]), v, spec["kind"], T("rules.settings.r_index_setting_changes.02") % len(info["idx"]), sample,
                     effect_of(spec, info["dir"]) + ((T("rules.settings.r_index_setting_changes.03") % ded) if ded else "")])
        if not ded:
            sevs.append(_SEV.get(risk_of(spec, info["dir"]), Severity.INFO))
        docs.add(spec["doc"])
    return [Finding(
        "SET-006", CAT, _worst(sevs) if sevs else Severity.INFO, T("rules.settings.r_index_setting_changes.04"),
        observed=T("rules.settings.r_index_setting_changes.05") % len(rows),
        impact=T("rules.settings.r_index_setting_changes.06"),
        recommend=T("rules.settings.r_index_setting_changes.07"),
        evidence=table([T("rules.settings.r_index_setting_changes.08"), T("rules.settings.r_index_setting_changes.09"), T("rules.settings.r_index_setting_changes.10"), T("rules.settings.r_index_setting_changes.11"), T("rules.settings.r_index_setting_changes.12"), T("rules.settings.r_index_setting_changes.13"), T("rules.settings.r_index_setting_changes.14")], rows),
        refs=_refs("index", *sorted(docs)), source="settings.json")]


RULES = [r_cluster_setting_changes, r_yml_shadowed, r_node_setting_changes,
         r_node_setting_consistency, r_index_setting_changes]
