# -*- coding: utf-8 -*-
"""Rules based on bundle files that were not read before.

mapping.json (actual index mappings), ilm_policies.json, cluster_state.json (voting exclusions),
nodes_shutdown_status.json, shard_stores.json, remote_cluster_info.json,
searchable_snapshots_cache_stats.json, the script, ingest processors and discovery sections of nodes_stats,
nodes.json plugins, ML trained model deployments, watcher, autoscaling, rollup.
"""

import collections
import datetime

from ..i18n import T, N_, tr
from ..model import Finding, Severity, table
from ..settings_kb import default_for
from ..util import dicts, dig, fmt_bytes, fmt_ms, fmt_num, items, num, parse_bytes, strs

MAPC, OPS, CLU, PERF, VEC = "shard", "ops", "cluster", "perf", "vector"
D_MAP = ("Mapping limit settings",
         "https://www.elastic.co/docs/reference/elasticsearch/index-settings/mapping-limit")
D_FD = ("fielddata mapping parameter",
        "https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/text#fielddata-mapping-param")
D_ILM = ("Rollover (ILM)",
         "https://www.elastic.co/docs/reference/elasticsearch/index-lifecycle-actions/ilm-rollover")
D_SHARDS = ("Size your shards",
            "https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards")
D_VOTE = ("Voting configuration exclusions",
          "https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-cluster-post-voting-config-exclusions")
D_SHUT = ("Node shutdown API",
          "https://www.elastic.co/docs/api/doc/elasticsearch/group/endpoint-shutdown")
D_KNN = ("Tune approximate kNN search",
         "https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/approximate-knn-search")


# ------------------------------------------------------------------ Mappings
def _mappings(ctx):
    for name, summ in items(ctx.mapping_summary):
        if ctx.is_system_index(name) or not isinstance(summ, dict):
            continue
        yield name, summ


def _template_owner(ctx, index):
    """Who manages the index template of a data stream backing index: "fleet:<package>", "elastic", or "-"."""
    ds = ctx.data_stream_of(index)
    tname = (ds or {}).get("template") if ds else None
    if not tname:
        return "-"
    if getattr(ctx, "_tpl_meta", None) is None:
        ctx._tpl_meta = {}
        for t in dicts((ctx.index_templates or {}).get("index_templates")):
            ctx._tpl_meta[t.get("name")] = dig(t, "index_template", "_meta") or {}
    meta = ctx._tpl_meta.get(tname) or {}
    if not isinstance(meta, dict):
        return "-"
    pkg = dig(meta, "package", "name")
    if pkg:
        return "fleet:%s" % pkg
    if str(meta.get("managed")).lower() == "true" or meta.get("managed_by"):
        return "elastic"
    return "-"


def r_mapping_limits_actual(ctx):
    """Counts fields per index from the actual mappings in mapping.json, using the official counting method (each field, object, multi-field and runtime field counts as 1).

    Field count >= total_fields.limit × mapping_fields_near_limit_pct → Warning (MAP-004; Info only if every listed index has ignore_dynamic_beyond_limit=true).
    Indices without ignore_dynamic_beyond_limit are listed first because they are the ones that can fail indexing; the table also shows
    who manages the data stream template (Fleet package or Elastic), since integration templates usually set the ignore option.
    Searchable snapshot mounts are skipped because they are read-only.
    text field with fielddata=true → Warning (MAP-005). nested field count >= nested_fields.limit × nested_fields_near_limit_pct → Warning (MAP-006). The default limit is 100 for indices created on 9.3 or later and 50 before.
    """
    near, fd_rows, nest_rows = [], [], []
    ignored = 0
    for name, m in _mappings(ctx):
        if ctx.is_searchable_snapshot(name):
            continue        # mounted indices are read-only: no new fields can arrive
        total, nested, fielddata = m["total"], m["nested"], m["fielddata"]
        try:
            limit = int(ctx.index_setting(name, "index.mapping.total_fields.limit") or 1000)
        except (TypeError, ValueError):
            limit = 1000
        if limit > 0 and total >= limit * ctx.t["mapping_fields_near_limit_pct"] / 100.0:
            ign = str(ctx.index_setting(name, "index.mapping.total_fields.ignore_dynamic_beyond_limit")).lower() == "true"
            ignored += 1 if ign else 0
            near.append([name, fmt_num(total), fmt_num(limit), "%.0f%%" % (total * 100.0 / limit), "true" if ign else "false",
                         _template_owner(ctx, name)])
        for f in fielddata:
            fd_rows.append([name, f])
        try:
            nlimit = int(ctx.index_setting(name, "index.mapping.nested_fields.limit")
                         or default_for("index.mapping.nested_fields.limit", ctx, index=name)
                         or (100 if ctx.version_tuple >= (9, 3, 0) else 50))
        except (TypeError, ValueError):
            nlimit = 100 if ctx.version_tuple >= (9, 3, 0) else 50
        if nlimit and nested >= nlimit * ctx.t["nested_fields_near_limit_pct"] / 100.0:
            nest_rows.append([name, nested, nlimit])
    out = []
    if near:
        near.sort(key=lambda r: (r[4] == "true", -float(r[3].rstrip("%"))))
        out.append(Finding(
            "MAP-004", MAPC, Severity.INFO if ignored == len(near) else Severity.WARNING,
            T("rules.deep.r_mapping_limits_actual.01"),
            observed=T("rules.deep.r_mapping_limits_actual.02")
                     % (ctx.t["mapping_fields_near_limit_pct"], len(near), ignored),
            impact=T("rules.deep.r_mapping_limits_actual.03"),
            recommend=T("rules.deep.r_mapping_limits_actual.04"),
            evidence=table(["index", T("rules.deep.r_mapping_limits_actual.05"), T("rules.deep.r_mapping_limits_actual.06"), T("rules.deep.r_mapping_limits_actual.07"), "ignore_dynamic_beyond_limit", "template _meta"], near[: ctx.t["top_n"]]),
            refs=[D_MAP], source="mapping.json / settings.json"))
    if fd_rows:
        out.append(Finding(
            "MAP-005", MAPC, Severity.WARNING, T("rules.deep.r_mapping_limits_actual.08"),
            observed=T("rules.deep.r_mapping_limits_actual.09") % len(fd_rows),
            impact=T("rules.deep.r_mapping_limits_actual.10"),
            recommend=T("rules.deep.r_mapping_limits_actual.11"),
            evidence=table(["index", "field"], fd_rows[: ctx.t["top_n"]]),
            refs=[D_FD], source="mapping.json"))
    if nest_rows:
        out.append(Finding(
            "MAP-006", MAPC, Severity.WARNING, T("rules.deep.r_mapping_limits_actual.12"),
            observed=T("rules.deep.r_mapping_limits_actual.13") % len(nest_rows),
            impact=T("rules.deep.r_mapping_limits_actual.14"),
            recommend=T("rules.deep.r_mapping_limits_actual.15"),
            evidence=table(["index", T("rules.deep.r_mapping_limits_actual.16"), T("rules.deep.r_mapping_limits_actual.06")], nest_rows[: ctx.t["top_n"]]),
            refs=[D_MAP], source="mapping.json / settings.json"))
    return out


def r_vector_mapping_actual(ctx):
    """Finds high-dimension float dense_vector fields in the actual index mappings that explicitly use a non-quantized type (hnsw, flat) (VEC-005, Warning).

    Below 8.14, a missing index_options is also non-quantized, so those fields are included. This backs up the template-based rule (VEC-002) with the actual indices.
    """
    quant_default = ctx.version_tuple >= (8, 14, 0)
    rows = []
    for name, m in _mappings(ctx):
        for field, f in m["vectors"]:
            try:
                dims = int(f.get("dims") or 0)
            except (TypeError, ValueError):
                dims = 0
            itype = str(dig(f, "index_options", "type") or "")
            if str(f.get("element_type") or "float") != "float" or dims < ctx.t["vector_dim_quantize_warn"]:
                continue
            if itype in ("hnsw", "flat") or (not itype and not quant_default):
                rows.append([name, field, dims, itype or T("rules.deep.r_vector_mapping_actual.01")])
    if not rows:
        return []
    return [Finding(
        "VEC-005", VEC, Severity.WARNING, T("rules.deep.r_vector_mapping_actual.02"),
        observed=T("rules.deep.r_vector_mapping_actual.03")
                 % (ctx.t["vector_dim_quantize_warn"], len(rows)),
        impact=T("rules.deep.r_vector_mapping_actual.04"),
        recommend=T("rules.deep.r_vector_mapping_actual.05"),
        evidence=table(["index", "field", "dims", "index_options.type"], rows[: ctx.t["top_n"]]),
        refs=[D_KNN], source="mapping.json")]


# ------------------------------------------------------------------ ILM policies
def r_ilm_policies(ctx):
    """Rollover and delete configuration of the ILM policies used by user indices.

    No max_primary_shard_size (or max_size) in the hot rollover → Warning (ILM-004): the official recommendation is rollover by shard size,
    and max_age alone leaves small indices piling up depending on the ingest rate (a cause of OVS-002). max_primary_shard_size > 50GB → Warning (ILM-005).
    No delete phase → Info (ILM-006, unlimited retention). Elastic-managed policies (_meta.managed=true) are checked like the others and marked "(Elastic managed)" in the table.
    max_primary_shard_docs above 200,000,000 → Info (ILM-007): rollover always runs at 200M documents per shard, so a higher value has no effect (official).
    """
    no_size, too_big, no_delete, docs_noop = [], [], [], []
    for pname, body in items(ctx.ilm_policies):
        if not isinstance(body, dict):
            continue
        users = [i for i in strs(dig(body, "in_use_by", "indices")) if not ctx.is_system_index(i)]
        users += [d for d in strs(dig(body, "in_use_by", "data_streams")) if not d.startswith(".")]
        if not users:
            continue
        managed = str(dig(body, "policy", "_meta", "managed")).lower() == "true"
        phases = dig(body, "policy", "phases", default={}) or {}
        if not isinstance(phases, dict):
            continue
        ro = dig(phases, "hot", "actions", "rollover")
        label = pname + (T("rules.deep.r_ilm_policies.01") if managed else "")
        if isinstance(ro, dict):
            size = ro.get("max_primary_shard_size") or ro.get("max_size")
            if not size:
                no_size.append([label, ", ".join("%s=%s" % kv for kv in ro.items()), len(users)])
            else:
                b = parse_bytes(ro.get("max_primary_shard_size"))
                if b and b > ctx.t["ilm_rollover_max_shard_gb"] * 1024 ** 3:
                    too_big.append([label, str(ro.get("max_primary_shard_size")), len(users)])
            mds = num(ro, "max_primary_shard_docs", default=None)
            if mds and mds > ctx.t["ilm_implicit_max_shard_docs"]:
                docs_noop.append([label, fmt_num(mds), len(users)])
        if "delete" not in phases:
            no_delete.append([label, ", ".join(sorted(phases.keys())), len(users)])
    out = []
    if no_size:
        out.append(Finding(
            "ILM-004", OPS, Severity.WARNING, T("rules.deep.r_ilm_policies.02"),
            observed=T("rules.deep.r_ilm_policies.03") % len(no_size),
            impact=T("rules.deep.r_ilm_policies.04"),
            recommend=T("rules.deep.r_ilm_policies.05"),
            evidence=table([T("rules.deep.r_ilm_policies.06"), T("rules.deep.r_ilm_policies.07"), T("rules.deep.r_ilm_policies.08")], no_size[: ctx.t["top_n"]]),
            refs=[D_ILM, D_SHARDS], source="ilm_policies.json"))
    if too_big:
        out.append(Finding(
            "ILM-005", OPS, Severity.WARNING, T("rules.deep.r_ilm_policies.09"),
            observed=T("rules.deep.r_ilm_policies.10") % (ctx.t["ilm_rollover_max_shard_gb"], len(too_big)),
            impact=T("rules.deep.r_ilm_policies.11"),
            recommend=T("rules.deep.r_ilm_policies.12"),
            evidence=table([T("rules.deep.r_ilm_policies.06"), "max_primary_shard_size", T("rules.deep.r_ilm_policies.13")], too_big[: ctx.t["top_n"]]),
            refs=[D_ILM, D_SHARDS], source="ilm_policies.json"))
    if docs_noop:
        out.append(Finding(
            "ILM-007", OPS, Severity.INFO, T("rules.deep.r_ilm_policies.19"),
            observed=T("rules.deep.r_ilm_policies.20") % (len(docs_noop), fmt_num(ctx.t["ilm_implicit_max_shard_docs"])),
            impact=T("rules.deep.r_ilm_policies.21"),
            recommend=T("rules.deep.r_ilm_policies.22"),
            evidence=table([T("rules.deep.r_ilm_policies.06"), "max_primary_shard_docs", T("rules.deep.r_ilm_policies.13")],
                           docs_noop[: ctx.t["top_n"]]),
            refs=[D_ILM, D_SHARDS], source="ilm_policies.json"))
    if no_delete:
        out.append(Finding(
            "ILM-006", OPS, Severity.INFO, T("rules.deep.r_ilm_policies.14"),
            observed=T("rules.deep.r_ilm_policies.15") % len(no_delete),
            impact=T("rules.deep.r_ilm_policies.16"),
            recommend=T("rules.deep.r_ilm_policies.17"),
            evidence=table([T("rules.deep.r_ilm_policies.06"), T("rules.deep.r_ilm_policies.18"), T("rules.deep.r_ilm_policies.13")], no_delete[: ctx.t["top_n"]]),
            refs=[D_ILM], source="ilm_policies.json"))
    return out


# ------------------------------------------------------------------ Cluster coordination, node shutdown, stores
def r_voting_exclusions(ctx):
    """voting_config_exclusions in cluster_state is not empty → Warning (CLU-022).

    This is a temporary setting used when removing or replacing master-eligible nodes. If it is not cleared after the work, those nodes stay out of the vote and the quorum margin shrinks.
    """
    ex = dicts(dig(ctx.cluster_state, "metadata", "cluster_coordination", "voting_config_exclusions"))
    if not ex:
        return []
    return [Finding(
        "CLU-022", CLU, Severity.WARNING, T("rules.deep.r_voting_exclusions.01"),
        observed=T("rules.deep.r_voting_exclusions.02") % (len(ex), ", ".join(str(x.get("node_name") or x.get("node_id")) for x in ex)),
        impact=T("rules.deep.r_voting_exclusions.03"),
        recommend=T("rules.deep.r_voting_exclusions.04"),
        evidence=table(["node_id", "node_name"], [[x.get("node_id"), x.get("node_name")] for x in ex]),
        refs=[D_VOTE], source="cluster_state.json")]


def r_node_shutdown(ctx):
    """Shutdown records from nodes_shutdown_status. STALLED → Critical, IN_PROGRESS → Info, COMPLETE but the node is still in the cluster → Warning (SHUT-001).

    A shutdown record stays until it is deleted. If it is left after the work, shard allocation to that node can stay restricted.
    """
    recs = dicts(ctx.shutdown_status.get("nodes"))
    if not recs:
        return []
    present = set(n.id for n in ctx.nodes)
    rows, sev = [], Severity.INFO
    for r in recs:
        st = str(r.get("status") or "").upper()
        shard = str(dig(r, "shard_migration", "status") or "")
        rows.append([r.get("node_id"), r.get("type"), st, shard, str(dig(r, "shard_migration", "explanation") or "")[:120]])
        if st == "STALLED":
            sev = Severity.CRITICAL
        elif st == "COMPLETE" and r.get("node_id") in present and sev != Severity.CRITICAL:
            sev = Severity.WARNING
    return [Finding(
        "SHUT-001", CLU, sev, T("rules.deep.r_node_shutdown.01"),
        observed=T("rules.deep.r_node_shutdown.02") % (len(recs), ", ".join(sorted(set(r[2] for r in rows)))),
        impact=T("rules.deep.r_node_shutdown.03"),
        recommend=T("rules.deep.r_node_shutdown.04"),
        evidence=table(["node_id", "type", "status", "shard_migration", "explanation"], rows),
        refs=[D_SHUT], source="nodes_shutdown_status.json")]


def r_shard_store_errors(ctx):
    """Shard copies with a store_exception in shard_stores → Critical (IDX-012, suspected data corruption)."""
    rows = []
    for index, body in items(ctx.shard_stores.get("indices")):
        for sid, sh in items(dig(body, "shards")):
            for st in dicts(dig(sh, "stores")):
                exc = st.get("store_exception")
                if exc:
                    rows.append([index, sid, st.get("allocation"),
                                 str(dig(exc, "reason") or exc)[:160]])
    if not rows:
        return []
    return [Finding(
        "IDX-012", MAPC, Severity.CRITICAL, T("rules.deep.r_shard_store_errors.01"),
        observed=T("rules.deep.r_shard_store_errors.02") % len(rows),
        impact=T("rules.deep.r_shard_store_errors.03"),
        recommend=T("rules.deep.r_shard_store_errors.04"),
        evidence=table(["index", "shard", "allocation", "exception"], rows[: ctx.t["top_n"]]),
        source="shard_stores.json")]


def r_remote_clusters(ctx):
    """Remote clusters with connected=false in remote_cluster_info → Warning (OPS-003)."""
    rows = [[name, str(body.get("connected")), body.get("mode"), num(body, "num_nodes_connected")]
            for name, body in items(ctx.remote_clusters) if isinstance(body, dict) and body.get("connected") is False]
    if not rows:
        return []
    return [Finding(
        "OPS-003", OPS, Severity.WARNING, T("rules.deep.r_remote_clusters.01"),
        observed=T("rules.deep.r_remote_clusters.02") % len(rows),
        impact=T("rules.deep.r_remote_clusters.03"),
        recommend=T("rules.deep.r_remote_clusters.04"),
        evidence=table(["remote", "connected", "mode", T("rules.deep.r_remote_clusters.05")], rows),
        source="remote_cluster_info.json")]


def r_frozen_cache(ctx):
    """Frozen shared cache statistics. Warning if any node has more evictions than cache regions (FRZ-001); otherwise Info when there is data.

    Evictions > region count means the whole cache has been replaced at least once, a sign that the cache is small compared to the searched data (tool threshold).
    """
    rows, hot = [], 0
    for nid, body in items(ctx.frozen_cache.get("nodes")):
        sc = dig(body, "shared_cache", default={}) or {}
        regions = num(sc, "num_regions")
        if not regions:
            continue
        ev = num(sc, "evictions")
        name = next((n.name for n in ctx.nodes if n.id == nid), nid)
        rows.append([name, fmt_bytes(num(sc, "size_in_bytes")), fmt_num(regions), fmt_num(num(sc, "reads")),
                     fmt_bytes(num(sc, "bytes_read_in_bytes")), fmt_num(ev)])
        if ev > regions:
            hot += 1
    if not rows:
        return []
    return [Finding(
        "FRZ-001", OPS, Severity.WARNING if hot else Severity.INFO,
        T("rules.deep.r_frozen_cache.01") if hot else T("rules.deep.r_frozen_cache.02"),
        observed=(T("rules.deep.r_frozen_cache.03") % hot) if hot else
                 T("rules.deep.r_frozen_cache.04") % len(rows),
        impact=T("rules.deep.r_frozen_cache.05"),
        recommend=T("rules.deep.r_frozen_cache.06"),
        evidence=table(["node", T("rules.deep.r_frozen_cache.07"), "region", "reads", T("rules.deep.r_frozen_cache.08"), "evictions"], rows),
        source="searchable_snapshots_cache_stats.json")]


D_SNAP = ("Searchable snapshots",
          "https://www.elastic.co/docs/deploy-manage/tools/snapshot-and-restore/searchable-snapshots")
NET_FS = ("nfs", "cifs", "smb", "fuse", "glusterfs", "ceph")
# Stack frames of a thread reading a file, and of the searchable snapshot / blob cache code that owns the shared cache file
_FILE_READ = ("FileChannelImpl.read", "FileDispatcherImpl.pread", "FileDispatcherImpl.read", "IOUtil.read", "NIOFSDirectory")
_CACHE_CODE = ("blobcache", "searchablesnapshots", "SharedBytes", "FrozenIndexInput")


def _has_shared_cache(ctx, n, cache_sizes):
    if cache_sizes.get(n.name):
        return True
    if ctx.is_frozen_only(n):
        return True
    v = n.setting("xpack.searchable.snapshot.shared_cache.size")
    return v is not None and str(v).strip().lower() not in ("0", "0b", "0%", "")


def _cache_file_reads(ctx):
    """node name -> number of hot threads reading a file inside the searchable snapshot cache code."""
    from .runtime import parse_hot_threads
    out = collections.Counter()
    if not ctx.hot_threads_text.strip():
        return out
    for node, _pct, _tname, _d, stack in parse_hot_threads(ctx.hot_threads_text):
        if any(any(sig in fr for sig in _FILE_READ) for fr in stack) and \
                any(any(sig in fr for sig in _CACHE_CODE) for fr in stack):
            out[node] += 1
    return out


def _direct_buffer_oom(ctx):
    """Lines with 'Direct buffer memory' in the server logs (local/remote mode only)."""
    from .runtime import _es_log_files
    hits = 0
    for rel in _es_log_files(ctx.b.log_files())[:40]:
        text = ctx.b.read_log(rel, ctx.t["log_scan_bytes"]) or ""
        hits += sum(1 for ln in text.splitlines() if "Direct buffer memory" in ln)
    return hits


def r_frozen_network_storage(ctx):
    """Nodes with a frozen shared cache whose data path is on a network filesystem (FRZ-002).

    A node has a shared cache when the cache stats show one, when it is a dedicated frozen node (which gets a shared cache by default),
    or when xpack.searchable.snapshot.shared_cache.size is set. Nodes with a shared cache can only have a single data path, so the
    cache file sits on the filesystem of that path. If nodes_stats fs.data[].type is nfs / cifs / smb / fuse / glusterfs / ceph → Warning.
    Searches read the cache file and cache misses write to it while searches run, unlike the segment files of other tiers, which do
    not change once written (PERF-009 covers the data path of every node).
    Supporting signals per node: hot threads reading a file inside the searchable snapshot cache code, and the search thread pool
    queue and rejections. "Direct buffer memory" errors in the server logs → Critical.
    """
    sizes = {}
    for nid, body in items(ctx.frozen_cache.get("nodes")):
        name = next((n.name for n in ctx.nodes if n.id == nid), nid)
        sizes[name] = num(body, "shared_cache", "size_in_bytes")
    reads = None
    rows, names = [], []
    for n in ctx.data_nodes:
        if not _has_shared_cache(ctx, n, sizes):
            continue
        for d in dig(n.stats, "fs", "data", default=[]) or []:
            t = str((d or {}).get("type") or "").lower()
            if not t or not any(x in t for x in NET_FS):
                continue
            if reads is None:
                reads = _cache_file_reads(ctx)
            sp = dig(n.stats, "thread_pool", "search", default={}) or {}
            names.append(n.name)
            rows.append([n.name, d.get("mount") or d.get("path") or "-", d.get("type"),
                         fmt_bytes(sizes[n.name]) if sizes.get(n.name) else "-",
                         fmt_num(reads.get(n.name, 0)) if ctx.hot_threads_text.strip() else "-",
                         fmt_num(num(sp, "queue")), fmt_num(num(sp, "rejected"))])
            break
    if not rows:
        return []
    oom = _direct_buffer_oom(ctx) if ctx.has_logs else 0
    sev = Severity.CRITICAL if oom else Severity.WARNING
    obs = T("rules.deep.r_frozen_network_storage.02") % (len(rows), ", ".join(names))
    if oom:
        obs += T("rules.deep.r_frozen_network_storage.03") % oom
    return [Finding(
        "FRZ-002", PERF, sev, T("rules.deep.r_frozen_network_storage.01"),
        observed=obs,
        impact=T("rules.deep.r_frozen_network_storage.04"),
        recommend=T("rules.deep.r_frozen_network_storage.05"),
        evidence=table(["node", "mount", "type", T("rules.deep.r_frozen_network_storage.06"),
                        T("rules.deep.r_frozen_network_storage.07"), "search queue", "search rejected"], rows),
        affected=names, refs=[D_SNAP], source="nodes_stats.json / searchable_snapshots_cache_stats.json / nodes_hot_threads.txt")]


# ------------------------------------------------------------------ Node stats details
def r_script_limit(ctx):
    """Nodes with nodes_stats.script.compilation_limit_triggered > 0 → Warning (PERF-010)."""
    rows = [[n.name, fmt_num(num(n.stats, "script", "compilation_limit_triggered")),
             fmt_num(num(n.stats, "script", "compilations")), fmt_num(num(n.stats, "script", "cache_evictions"))]
            for n in ctx.nodes if num(n.stats, "script", "compilation_limit_triggered") > 0]
    if not rows:
        return []
    return [Finding(
        "PERF-010", PERF, Severity.WARNING, T("rules.deep.r_script_limit.01"),
        observed=T("rules.deep.r_script_limit.02") % len(rows),
        impact=T("rules.deep.r_script_limit.03"),
        recommend=T("rules.deep.r_script_limit.04"),
        evidence=table(["node", T("rules.deep.r_script_limit.05"), T("rules.deep.r_script_limit.06"), T("rules.deep.r_script_limit.07")], rows),
        source="nodes_stats.json")]


def r_ingest_processors(ctx):
    """Sums the cumulative processing time per processor from the node ingest statistics and reports the top processors (ING-002, Info).

    When hot threads (RT-001) show ingest using CPU, this is the evidence for which pipeline or processor is responsible.
    """
    agg = collections.Counter()
    cnt = collections.Counter()
    for n in ctx.nodes:
        for pname, p in items(dig(n.stats, "ingest", "pipelines")):
            for proc in dicts(p.get("processors") if isinstance(p, dict) else None):
                for key, body in items(proc):
                    ptype = (body or {}).get("type") if isinstance(body, dict) else None
                    if ptype == "pipeline":
                        continue            # nested pipeline calls are skipped to avoid double counting
                    agg[(pname, key, ptype)] += num(body, "stats", "time_in_millis")
                    cnt[(pname, key, ptype)] += num(body, "stats", "count")
    total = sum(agg.values())
    if not total:
        return []
    top = agg.most_common(ctx.t["top_n"])
    rows = [[p, k, t, fmt_ms(ms), "%.0f%%" % (ms * 100.0 / total), fmt_num(cnt[(p, k, t)]),
             ("%.3fms" % (ms / float(cnt[(p, k, t)]))) if cnt[(p, k, t)] else "-"] for (p, k, t), ms in top]
    by_type = collections.Counter()
    for (p, k, t), ms in agg.items():
        by_type[t] += ms
    t0, ms0 = by_type.most_common(1)[0]
    return [Finding(
        "ING-002", PERF, Severity.INFO, T("rules.deep.r_ingest_processors.01"),
        observed=T("rules.deep.r_ingest_processors.02") % (fmt_ms(total), t0, ms0 * 100.0 / total),
        impact=T("rules.deep.r_ingest_processors.03"),
        recommend=T("rules.deep.r_ingest_processors.04"),
        evidence=table(["pipeline", "processor", "type", T("rules.deep.r_ingest_processors.05"), T("rules.deep.r_ingest_processors.06"), T("rules.deep.r_ingest_processors.07"), T("rules.deep.r_ingest_processors.08")], rows),
        source="nodes_stats.json")]


def r_cluster_state_publication(ctx):
    """Cluster state publication statistics from nodes_stats.discovery.

    cluster_state_update.failure present → Warning (CLU-024). If the serialized full state size (before compression) is available,
    its size and the average commit time are reported as Info. Failure counts are summed across nodes. The master does the publishing, so the commit count, commit time and state size use the maximum across nodes.
    """
    fails, size, commits, commit_ms = 0, 0, 0, 0
    for n in ctx.nodes:
        cu = dig(n.stats, "discovery", "cluster_state_update", default={}) or {}
        fails += num(cu, "failure", "count")
        commits = max(commits, num(cu, "success", "count"))
        commit_ms = max(commit_ms, num(cu, "success", "commit_time_millis"))
        fs = dig(n.stats, "discovery", "serialized_cluster_states", "full_states", default={}) or {}
        c = num(fs, "count")
        if c:
            size = max(size, num(fs, "uncompressed_size_in_bytes") / float(c))
    if not (fails or size or commits):
        return []
    avg_commit = (commit_ms / float(commits)) if commits else None
    ev = table([T("rules.deep.r_cluster_state_publication.01"), T("rules.deep.r_cluster_state_publication.02")], [[T("rules.deep.r_cluster_state_publication.03"), fmt_num(fails)], [T("rules.deep.r_cluster_state_publication.04"), fmt_num(commits)],
                                [T("rules.deep.r_cluster_state_publication.05"), ("%.1fms" % avg_commit) if avg_commit is not None else "-"],
                                [T("rules.deep.r_cluster_state_publication.06"), fmt_bytes(size) if size else "-"]])
    return [Finding(
        "CLU-024", CLU, Severity.WARNING if fails else Severity.INFO,
        T("rules.deep.r_cluster_state_publication.07") if fails else T("rules.deep.r_cluster_state_publication.08"),
        observed=(T("rules.deep.r_cluster_state_publication.09") % fmt_num(fails)) if fails else
                 ", ".join(x for x in ((T("rules.deep.r_cluster_state_publication.10") % avg_commit) if avg_commit is not None else "",
                                       (T("rules.deep.r_cluster_state_publication.11") % fmt_bytes(size)) if size else "") if x) + ".",
        impact=T("rules.deep.r_cluster_state_publication.12"),
        recommend=T("rules.deep.r_cluster_state_publication.13"),
        evidence=ev, source="nodes_stats.json")]


def r_plugin_consistency(ctx):
    """Warning if the installed plugins (name and version) are not identical on every node (CLU-023)."""
    sigs = {}
    for n in ctx.nodes:
        plugs = sorted("%s:%s" % (p.get("name"), p.get("version")) for p in dicts(n.info.get("plugins")))
        sigs[n.name] = plugs
    if len(sigs) < 2 or len(set(tuple(v) for v in sigs.values())) <= 1:
        return []
    allp = sorted(set(p for v in sigs.values() for p in v))
    rows = [[p, ", ".join(nm for nm, v in sigs.items() if p not in v)] for p in allp
            if any(p not in v for v in sigs.values())]
    return [Finding(
        "CLU-023", CLU, Severity.WARNING, T("rules.deep.r_plugin_consistency.01"),
        observed=T("rules.deep.r_plugin_consistency.02") % len(rows),
        impact=T("rules.deep.r_plugin_consistency.03"),
        recommend=T("rules.deep.r_plugin_consistency.04"),
        evidence=table([T("rules.deep.r_plugin_consistency.05"), T("rules.deep.r_plugin_consistency.06")], rows), source="nodes.json")]


# ------------------------------------------------------------------ ML, watcher, autoscaling, rollup
def r_ml_deployments(ctx):
    """Warning if a trained model deployment has a state other than started, or an allocation status other than fully_allocated (ML-003)."""
    rows = []
    for m in dicts(ctx.ml_trained_stats.get("trained_model_stats")):
        dep = m.get("deployment_stats")
        if not isinstance(dep, dict):
            continue
        st = str(dep.get("state") or "")
        alloc = str(dig(dep, "allocation_status", "state") or "")
        if st.lower() != "started" or (alloc and alloc.lower() != "fully_allocated"):
            rows.append([m.get("model_id"), dep.get("deployment_id"), st, alloc, str(dep.get("reason") or "")[:120]])
    if not rows:
        return []
    return [Finding(
        "ML-003", OPS, Severity.WARNING, T("rules.deep.r_ml_deployments.01"),
        observed=T("rules.deep.r_ml_deployments.02") % len(rows),
        impact=T("rules.deep.r_ml_deployments.03"),
        recommend=T("rules.deep.r_ml_deployments.04"),
        evidence=table(["model", "deployment", "state", "allocation", "reason"], rows),
        source="ml_trained_models_stats.json")]


def r_watcher_autoscaling_rollup(ctx):
    """Watcher manually stopped while watches exist → Warning (OPS-005). Autoscaling required capacity larger than current capacity → Info (OPS-004).
    Rollup jobs present → Info (OPS-006, rollup is deprecated and replaced by downsampling).
    """
    out = []
    ws = ctx.watcher_stack
    watches = sum(num(s, "watch_count") for s in dicts(ws.get("stats")))
    if ws.get("manually_stopped") is True and watches:
        out.append(Finding(
            "OPS-005", OPS, Severity.WARNING, T("rules.deep.r_watcher_autoscaling_rollup.01"),
            observed=T("rules.deep.r_watcher_autoscaling_rollup.02") % watches,
            impact=T("rules.deep.r_watcher_autoscaling_rollup.03"), recommend=T("rules.deep.r_watcher_autoscaling_rollup.04"),
            source="watcher_stack.json"))
    rows = []
    for pname, p in items(ctx.autoscaling.get("policies")):
        req = num(p, "required_capacity", "total", "storage") + num(p, "required_capacity", "total", "memory")
        cur = num(p, "current_capacity", "total", "storage") + num(p, "current_capacity", "total", "memory")
        if req > cur > 0:
            rows.append([pname, fmt_bytes(num(p, "current_capacity", "total", "storage")),
                         fmt_bytes(num(p, "required_capacity", "total", "storage")),
                         fmt_bytes(num(p, "current_capacity", "total", "memory")),
                         fmt_bytes(num(p, "required_capacity", "total", "memory"))])
    if rows:
        out.append(Finding(
            "OPS-004", OPS, Severity.INFO, T("rules.deep.r_watcher_autoscaling_rollup.05"),
            observed=T("rules.deep.r_watcher_autoscaling_rollup.06") % len(rows),
            impact=T("rules.deep.r_watcher_autoscaling_rollup.07"),
            recommend=T("rules.deep.r_watcher_autoscaling_rollup.08"),
            evidence=table([T("rules.deep.r_watcher_autoscaling_rollup.09"), T("rules.deep.r_watcher_autoscaling_rollup.10"), T("rules.deep.r_watcher_autoscaling_rollup.11"), T("rules.deep.r_watcher_autoscaling_rollup.12"), T("rules.deep.r_watcher_autoscaling_rollup.13")], rows),
            source="autoscaling_capacity.json"))
    jobs = dicts(ctx.rollup_jobs.get("jobs"))
    if jobs:
        out.append(Finding(
            "OPS-006", OPS, Severity.INFO, T("rules.deep.r_watcher_autoscaling_rollup.14"),
            observed=T("rules.deep.r_watcher_autoscaling_rollup.15") % len(jobs),
            impact=T("rules.deep.r_watcher_autoscaling_rollup.16"),
            recommend=T("rules.deep.r_watcher_autoscaling_rollup.17"),
            evidence=table(["job", T("rules.deep.r_watcher_autoscaling_rollup.18")], [[dig(j, "config", "id"), dig(j, "status", "job_state")] for j in jobs]),
            source="rollup_jobs.json"))
    return out


def r_disk_io_utilization(ctx):
    """Average disk utilization of data nodes = fs.io_stats.total.io_time_in_millis / JVM uptime (collected on Linux only).

    io_time is the cumulative time the devices spent handling I/O since ES started. >= disk_io_busy_pct_warn → Warning (DISK-008), otherwise Info.
    With several devices the values add up and can exceed 100%, so the result is divided by the device count. This is a cumulative average, so short saturation spikes can be hidden.
    A result below 0% or above 100% means the device counter does not line up with the JVM uptime (for example a counter reset
    on a hosted instance). Such a node is shown as "cannot be determined" and is not rated.
    """
    rows, busy = [], []
    for n in ctx.data_nodes:
        io = dig(n.stats, "fs", "io_stats", default={}) or {}
        t = num(io, "total", "io_time_in_millis")
        up = n.uptime_ms or 0
        devs = max(1, len(dicts(io.get("devices"))))
        if not t or not up:
            continue
        util = t / float(up) / devs * 100.0
        valid = 0 <= util <= 100
        rows.append([n.name, ctx.tier_of(n) or "-", ("%.1f%%" % util) if valid else T("rules.deep.r_disk_io_utilization.11"),
                     fmt_num(num(io, "total", "read_operations")), fmt_num(num(io, "total", "write_operations")), devs])
        if valid and util >= ctx.t["disk_io_busy_pct_warn"]:
            busy.append(n.name)
    if not rows:
        return []
    return [Finding(
        "DISK-008", "node", Severity.WARNING if busy else Severity.INFO,
        T("rules.deep.r_disk_io_utilization.01") if busy else T("rules.deep.r_disk_io_utilization.02"),
        observed=(T("rules.deep.r_disk_io_utilization.03") % (ctx.t["disk_io_busy_pct_warn"], ", ".join(busy))) if busy
                 else T("rules.deep.r_disk_io_utilization.04") % len(rows),
        impact=T("rules.deep.r_disk_io_utilization.05"),
        recommend=T("rules.deep.r_disk_io_utilization.06"),
        evidence=table(["node", "tier", T("rules.deep.r_disk_io_utilization.07"), T("rules.deep.r_disk_io_utilization.08"), T("rules.deep.r_disk_io_utilization.09"), T("rules.deep.r_disk_io_utilization.10")], rows),
        source="nodes_stats.json (fs.io_stats)")]


# Query types and search components that the official docs call expensive
#   - Tune for search speed: nested can be several times slower, parent-child (has_child/has_parent) hundreds of times; avoid scripts
#   - Types blocked by search.allow_expensive_queries: script, fuzzy, regexp, prefix, wildcard, join queries, etc.
EXPENSIVE = [
    ("nested", "query", N_("rules.deep._.01")),
    ("has_child", "query", N_("rules.deep._.02")),
    ("has_parent", "query", N_("rules.deep._.02")),
    ("script", "query", N_("rules.deep._.03")), ("script_score", "query", N_("rules.deep._.04")),
    ("wildcard", "query", N_("rules.deep._.05")), ("regexp", "query", N_("rules.deep._.06")),
    ("fuzzy", "query", N_("rules.deep._.07")), ("prefix", "query", N_("rules.deep._.08")),
    ("query_string", "query", N_("rules.deep._.09")),
    ("runtime_mappings", "section", N_("rules.deep._.10")),
    ("script_fields", "section", N_("rules.deep._.11")),
]


def r_search_usage(ctx):
    """Uses the cumulative usage counts per query type and search component in cluster_stats.indices.search to see how much of the search load is expensive.

    Expensive types (EXPENSIVE: nested, parent-child join, script, wildcard, regexp, fuzzy, prefix, query_string,
    runtime_mappings, script_fields) with a usage share >= search_expensive_share_warn (%) → Warning (PERF-011); used but with a
    low share → Info. These are counts per type, not query bodies, so which query on which index cannot be determined.
    """
    su = dig(ctx.cluster_stats, "indices", "search", default={}) or {}
    total = num(su, "total")
    if not total:
        return []
    q, sec = su.get("queries") or {}, su.get("sections") or {}
    rows, heavy = [], []
    for key, kind, desc in EXPENSIVE:
        cnt = num(q if kind == "query" else sec, key)
        if not cnt:
            continue
        share = cnt * 100.0 / total
        rows.append([key, T("rules.deep.r_search_usage.01") if kind == "query" else T("rules.deep.r_search_usage.02"), fmt_num(cnt), "%.2f%%" % share, tr(desc)])
        if share >= ctx.t["search_expensive_share_warn"]:
            heavy.append("%s %.1f%%" % (key, share))
    if not rows:
        return []
    rows.sort(key=lambda r: -float(r[3].rstrip("%")))
    top = sorted(((k, v) for k, v in items(q)), key=lambda kv: -num(kv[1]))[:8]
    return [Finding(
        "PERF-011", PERF, Severity.WARNING if heavy else Severity.INFO,
        T("rules.deep.r_search_usage.03") if heavy else T("rules.deep.r_search_usage.04"),
        observed=(T("rules.deep.r_search_usage.05") % (fmt_num(total), ctx.t["search_expensive_share_warn"], ", ".join(heavy)))
                 if heavy else T("rules.deep.r_search_usage.06") % (fmt_num(total), len(rows)),
        impact=T("rules.deep.r_search_usage.07") % ", ".join("%s %s" % (k, fmt_num(num(v))) for k, v in top),
        recommend=T("rules.deep.r_search_usage.08"),
        evidence=table([T("rules.deep.r_search_usage.09"), T("rules.deep.r_search_usage.10"), T("rules.deep.r_search_usage.11"), T("rules.deep.r_search_usage.12"), T("rules.deep.r_search_usage.13")], rows),
        refs=[("Tune for search speed",
               "https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/search-speed")],
        source="cluster_stats.json (indices.search)")]



# ------------------------------------------------------------------ force merge
D_FORCEMERGE = ("Force merge API",
                "https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-indices-forcemerge")
D_ILM_FM = ("Force merge (ILM)",
            "https://www.elastic.co/docs/reference/elasticsearch/index-lifecycle-actions/ilm-forcemerge")
_PHASE_TIER = {"hot": "hot", "warm": "warm", "cold": "cold"}


def _policy_indices(ctx, body):
    names = [i for i in strs(dig(body, "in_use_by", "indices")) if not ctx.is_system_index(i)]
    for ds_name in strs(dig(body, "in_use_by", "data_streams")):
        if ds_name.startswith("."):
            continue
        for ds in dicts(ctx.data_streams):
            if ds.get("name") == ds_name:
                names += [i.get("index_name") for i in dicts(ds.get("indices")) if i.get("index_name")]
    return set(names)


def _merge_points(phases):
    """(phase whose tier runs the merge, label) for every merge down to one segment in an ILM policy.

    forcemerge with max_num_segments=1 runs in its own phase. searchable_snapshot with force_merge_index (default true)
    merges to one segment in the tier of the preceding phase, and is a no-op if the index was already merged to one segment.
    """
    out, merged, prev = [], False, None
    if not isinstance(phases, dict):
        return out
    for phase in ("hot", "warm", "cold", "frozen"):
        body = phases.get(phase)
        if not isinstance(body, dict):
            continue
        acts = body.get("actions")
        if not isinstance(acts, dict):
            continue
        fm = acts.get("forcemerge")
        if isinstance(fm, dict) and str(fm.get("max_num_segments")) == "1":
            out.append((phase, "%s: forcemerge" % phase))
            merged = True
        ss = acts.get("searchable_snapshot")
        if isinstance(ss, dict) and str(ss.get("force_merge_index", True)).lower() != "false" and not merged:
            run = prev or phase
            out.append((run, "%s: searchable_snapshot (%s)" % (run, phase)))
            merged = True
        prev = phase
    return out


def _fm_pool(n):
    """force_merge pool size of a node: the reported size, else max(1, allocated processors / 8) (official default)."""
    size = num(n.info, "thread_pool", "force_merge", "max", default=None) or \
        num(n.info, "thread_pool", "force_merge", "size", default=None)
    if size:
        return int(size)
    proc = num(n.info, "os", "allocated_processors", default=None) or n.processors
    return max(1, int(proc // 8)) if proc else None


def r_forcemerge(ctx):
    """ILM force merge to a single segment, disk headroom and progress.

    Official: force merge with max_num_segments=1 may need free space up to three times the shard size, and the force_merge
    thread pool has max(1, allocated processors / 8) threads per node. Merges to one segment are forcemerge with max_num_segments=1
    (run in its own phase) and searchable_snapshot with force_merge_index (default true, run in the tier of the preceding phase,
    a no-op after an earlier one-segment merge). A policy in use with such a merge where a node of the tier that runs it
    (hot/warm/cold; all non-frozen data nodes when the tier is not used) has less free disk
    than forcemerge_free_space_factor x the largest primary shard of the indices using the policy → Warning (ILM-008).
    ilm_explain entries that have been in the forcemerge action (or the forcemerge step of searchable_snapshot) for
    forcemerge_stuck_hours or more at collection time → Info (ILM-009),
    with the force_merge pool size and queue of the data nodes. Partially mounted indices are skipped (size is the cache size).
    """
    biggest = collections.Counter()
    for s in ctx.shards:
        if (s.get("prirep") or "").lower() == "p" and not ctx.is_partial_mount(s.get("index")):
            b = parse_bytes(s.get("store")) or 0
            if b > biggest[s.get("index")]:
                biggest[s.get("index")] = b
    tiers = ctx.data_tiers()
    hot_like = [n for n in ctx.data_nodes if not ctx.is_frozen_only(n)]
    factor = ctx.t["forcemerge_free_space_factor"]
    rows = []
    for pname, body in items(ctx.ilm_policies):
        if not isinstance(body, dict):
            continue
        users = _policy_indices(ctx, body)
        if not users:
            continue
        largest = max([biggest.get(i, 0) for i in users] or [0])
        if not largest:
            continue
        for run_phase, label in _merge_points(dig(body, "policy", "phases", default={}) or {}):
            tier = _PHASE_TIER.get(run_phase)
            nodes = tiers.get(tier) if tier in tiers else hot_like
            cand = [(n.fs_avail, n.name) for n in nodes or [] if n.fs_avail is not None]
            if not cand:
                continue
            avail, nname = min(cand)
            if avail < factor * largest:
                rows.append([pname, label, tier if tier in tiers else T("rules.deep.r_forcemerge.01"),
                             fmt_bytes(largest), fmt_bytes(factor * largest), nname, fmt_bytes(avail)])
    out = []
    if rows:
        out.append(Finding(
            "ILM-008", OPS, Severity.WARNING, T("rules.deep.r_forcemerge.02"),
            observed=T("rules.deep.r_forcemerge.03") % (len(rows), factor),
            impact=T("rules.deep.r_forcemerge.04"),
            recommend=T("rules.deep.r_forcemerge.05"),
            evidence=table([T("rules.deep.r_ilm_policies.06"), T("rules.deep.r_forcemerge.15"), "tier",
                            T("rules.deep.r_forcemerge.06"), T("rules.deep.r_forcemerge.07"),
                            T("rules.deep.r_forcemerge.08"), T("rules.deep.r_forcemerge.09")], rows[: ctx.t["top_n"]]),
            refs=[D_FORCEMERGE, D_ILM_FM], source="ilm_policies.json / nodes_stats.json / indices.json"))

    now = ctx.collection_time
    stuck = []
    if now is not None:
        if now.tzinfo is None:
            now = now.replace(tzinfo=datetime.timezone.utc)
        now_ms = now.timestamp() * 1000
        limit_ms = ctx.t["forcemerge_stuck_hours"] * 3600000
        for name, ex in items(ctx.ilm_explain):
            if not isinstance(ex, dict) or ctx.is_system_index(name):
                continue
            if ex.get("action") == "forcemerge":
                since = num(ex, "action_time_millis", default=None) or num(ex, "step_time_millis", default=None)
            elif ex.get("action") == "searchable_snapshot" and ex.get("step") == "forcemerge":
                since = num(ex, "step_time_millis", default=None)
            else:
                continue
            if since and now_ms - since >= limit_ms:
                stuck.append([name, ex.get("phase") or "-", ex.get("step") or "-", fmt_ms(now_ms - since),
                              ex.get("policy") or "-", fmt_bytes(biggest.get(name)) if biggest.get(name) else "-"])
    if stuck:
        stuck.sort(key=lambda r: r[0])
        pools = [(n, _fm_pool(n)) for n in ctx.data_nodes if not ctx.is_frozen_only(n)]
        single = len([1 for n, sz in pools if sz == 1])
        queue = sum(int(num(n.stats, "thread_pool", "force_merge", "queue", default=0) or 0) for n, _ in pools)
        active = sum(int(num(n.stats, "thread_pool", "force_merge", "active", default=0) or 0) for n, _ in pools)
        out.append(Finding(
            "ILM-009", OPS, Severity.INFO, T("rules.deep.r_forcemerge.10"),
            observed=T("rules.deep.r_forcemerge.11") % (len(stuck), ctx.t["forcemerge_stuck_hours"], single, len(pools), active, queue),
            impact=T("rules.deep.r_forcemerge.12"),
            recommend=T("rules.deep.r_forcemerge.13"),
            evidence=table(["index", "phase", "step", T("rules.deep.r_forcemerge.14"), "ILM policy",
                            T("rules.deep.r_forcemerge.06")], stuck[: ctx.t["top_n"]]),
            affected=[r[0] for r in stuck], refs=[D_FORCEMERGE, D_ILM_FM],
            source="commercial/ilm_explain.json / nodes_stats.json"))
    return out

RULES = [r_search_usage, r_disk_io_utilization, r_mapping_limits_actual, r_vector_mapping_actual, r_ilm_policies, r_forcemerge, r_voting_exclusions,
         r_node_shutdown, r_shard_store_errors, r_remote_clusters, r_frozen_cache, r_frozen_network_storage, r_script_limit,
         r_ingest_processors, r_cluster_state_publication, r_plugin_consistency, r_ml_deployments,
         r_watcher_autoscaling_rollup]
