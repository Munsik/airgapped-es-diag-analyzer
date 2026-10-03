# -*- coding: utf-8 -*-
"""Rules based on the official Elastic Production guidance / Important settings docs.

The refs of each rule name the source doc. Only items visible in the diagnostics bundle become rules;
items the bundle does not collect (OS readahead, query bodies, etc.) are listed as limits in COVERAGE.md.
"""

import collections

from ..i18n import T, N_, tr
from ..model import Finding, Severity, table
from ..settings_kb import BEST_COMPRESSION_MODES
from ..util import dicts, dig, fmt_bytes, fmt_num, parse_bytes, pct, num, items, strs

CFG = "config"
SIZ = "shard"
SPD = "perf"
VEC = "vector"

D_SETTINGS = ("Important settings configuration",
              "https://www.elastic.co/docs/deploy-manage/deploy/self-managed/important-settings-configuration")
D_SHARDS = ("Size your shards",
            "https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards")
D_INDEX = ("Tune for indexing speed",
           "https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/indexing-speed")
D_SEARCH = ("Tune for search speed",
            "https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/search-speed")
D_DISK = ("Tune for disk usage",
          "https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/disk-usage")
D_SOURCE = (N_("rules.guidance._.source"),
            "https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/mapping-source-field")
D_PAGINATE = ("Paginate search results",
              "https://www.elastic.co/docs/reference/elasticsearch/rest-apis/paginate-search-results")
D_INDEX_MODULES = ("Index modules (index.max_result_window)",
                   "https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules")
D_BOOT = ("Bootstrap checks",
          "https://www.elastic.co/docs/deploy-manage/deploy/self-managed/bootstrap-checks")
D_GEN = ("General recommendations",
         "https://www.elastic.co/docs/deploy-manage/production-guidance/general-recommendations")
D_KNN = ("Tune approximate kNN search",
         "https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/approximate-knn-search")
D_ROLLOVER = ("Rollover (ILM): max_primary_shard_docs",
              "https://www.elastic.co/docs/reference/elasticsearch/index-lifecycle-actions/ilm-rollover")
D_ILM_SETTINGS = ("ILM settings: indices.lifecycle.poll_interval",
                  "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/index-lifecycle-management-settings")
D_LOGS_DS = ("Logs data streams",
             "https://www.elastic.co/docs/manage-data/data-store/data-streams/logs-data-stream")
D_LOGSDB = ("Configure a logs data stream",
            "https://www.elastic.co/docs/manage-data/data-store/data-streams/logs-data-stream-configure")
D_SORT = ("Index sorting settings",
          "https://www.elastic.co/docs/reference/elasticsearch/index-settings/sorting")
D_FORCEMERGE = ("Force merge API",
                "https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-indices-forcemerge")

GB = 1024 ** 3


ORCH_NOTE = (N_("rules.guidance._.01"))


def _orch(ctx, sev, recommend):
    """For orchestrator-managed settings, lowers the severity and adds context."""
    if ctx.orchestrated:
        return Severity.INFO, (tr(ORCH_NOTE) % ctx.deployment) + " " + recommend
    return sev, recommend


def _jvm_args(n):
    return " ".join(n.jvm_args())


# ============================================================
# important-settings-configuration
# ============================================================

def r_cluster_name(ctx):
    """Warning if cluster.name is the default 'elasticsearch'. Info if ECH/ECE/ECK is detected."""
    name = ctx.cluster_name
    if name and str(name).lower() == "elasticsearch":
        sev, rec = _orch(ctx, Severity.WARNING,
                         T("rules.guidance.r_cluster_name.01"))
        return [Finding(
            "CFG-001", CFG, sev, T("rules.guidance.r_cluster_name.02"),
            observed="cluster.name = elasticsearch",
            impact=T("rules.guidance.r_cluster_name.03"),
            recommend=rec, refs=[D_SETTINGS], source="cluster_health.json")]
    return []


def r_path_settings(ctx):
    """Location of path.data/path.logs.

    The concern in the official docs is archive (tar.gz/zip) installs, where an upgrade replaces $ES_HOME
    and deletes the data with it. rpm/deb already default to external paths (/var/lib, /var/log), and docker
    mounts a volume, so neither is affected. The install type is determined from build_type.
    """
    out, rows, in_home, multi = [], [], [], []
    for n in ctx.nodes:
        build = str(n.info.get("build_type") or "").lower()
        home = n.setting("path.home") or ""
        data = n.setting("path.data")
        logs = n.setting("path.logs")
        rows.append([n.name, build or "-", str(data), str(logs), str(home)])
        data_list = data if isinstance(data, list) else ([data] if data else [])
        if isinstance(data, str) and "," in data:
            data_list = [x.strip() for x in data.split(",") if x.strip()]
        if len(data_list) > 1:
            multi.append(n.name)
        if build not in ("tar", "zip"):
            continue
        for pth in data_list + ([logs] if logs else []):
            if home and isinstance(pth, str) and pth.startswith(home):
                in_home.append(n.name)
                break
    if in_home:
        sev, rec = _orch(ctx, Severity.WARNING,
                         T("rules.guidance.r_path_settings.01"))
        out.append(Finding(
            "CFG-002", CFG, sev, T("rules.guidance.r_path_settings.02"),
            observed=T("rules.guidance.r_path_settings.03") % ", ".join(sorted(set(in_home))),
            impact=T("rules.guidance.r_path_settings.04"),
            recommend=rec,
            evidence=table(["node", "build_type", "path.data", "path.logs", "path.home"], rows),
            refs=[D_SETTINGS], source="nodes.json"))
    if multi:
        out.append(Finding(
            "CFG-003", CFG, Severity.WARNING, T("rules.guidance.r_path_settings.05"),
            observed=T("rules.guidance.r_path_settings.03") % ", ".join(multi),
            impact=T("rules.guidance.r_path_settings.06"),
            recommend=T("rules.guidance.r_path_settings.07"),
            refs=[D_SETTINGS], source="nodes.json"))
    return out


def r_discovery(ctx):
    """Multi-node cluster without discovery.seed_hosts / seed_providers → Warning (CFG-004). cluster.initial_master_nodes still set → Warning (CFG-005). Actual bound transport_address is loopback or discovery.type=single-node → Warning (CFG-006). On orchestrator deployments all of these drop to Info."""
    out = []
    missing_seed, initial_left, dev_mode = [], [], []
    for n in ctx.nodes:
        seeds = n.setting("discovery.seed_hosts") or n.setting("discovery.zen.ping.unicast.hosts")
        provider = n.setting("discovery.seed_providers")
        single = str(n.setting("discovery.type") or "") == "single-node"
        if len(ctx.nodes) > 1 and not seeds and not provider:
            missing_seed.append(n.name)
        if n.setting("cluster.initial_master_nodes"):
            initial_left.append(n.name)
        # Production mode is decided by whether the actually bound transport address is loopback.
        # The rating uses transport_address from nodes info (a fact), not the configured value.
        ta = str(n.info.get("transport_address") or "")
        if ta.startswith("127.") or ta.startswith("[::1]") or ta.startswith("localhost") or single:
            dev_mode.append("%s(%s)" % (n.name, "single-node" if single else ta))
    if missing_seed:
        sev, rec = _orch(ctx, Severity.WARNING,
                         T("rules.guidance.r_discovery.01"))
        out.append(Finding(
            "CFG-004", CFG, sev, T("rules.guidance.r_discovery.02"),
            observed=T("rules.guidance.r_discovery.03") % ", ".join(missing_seed),
            impact=T("rules.guidance.r_discovery.04"),
            recommend=rec, refs=[D_SETTINGS], source="nodes.json"))
    if initial_left:
        sev, rec = _orch(ctx, Severity.WARNING,
                         T("rules.guidance.r_discovery.05"))
        out.append(Finding(
            "CFG-005", CFG, sev, T("rules.guidance.r_discovery.06"),
            observed=T("rules.guidance.r_discovery.03") % ", ".join(initial_left),
            impact=T("rules.guidance.r_discovery.07"),
            recommend=rec, refs=[D_SETTINGS], source="nodes.json"))
    if dev_mode:
        sev, rec = _orch(ctx, Severity.WARNING,
                         T("rules.guidance.r_discovery.08"))
        out.append(Finding(
            "CFG-006", CFG, sev, T("rules.guidance.r_discovery.09"),
            observed=T("rules.guidance.r_discovery.10") % ", ".join(dev_mode),
            impact=T("rules.guidance.r_discovery.11"),
            recommend=rec, refs=[D_SETTINGS, D_BOOT], source="nodes.json (transport_address)"))
    return out


def _gc_logging_enabled(args):
    """For -Xlog options, a later option overrides an earlier one.

    Depending on the deployment type and version, '-Xlog:disable' can come before the GC logging options,
    so its presence alone is not treated as logging being off. The check looks for file-based gc logging after the last disable.
    """
    last_disable = -1
    for i, a in enumerate(args):
        if a.startswith("-Xlog:disable"):
            last_disable = i
    for a in args[last_disable + 1:]:
        if a.startswith("-Xlog:") and "gc" in a.split(":", 2)[1] and "file=" in a:
            return True
    return False


def r_jvm_diag_settings(ctx):
    """Based on jvm.input_arguments. No HeapDumpOnOutOfMemoryError → Warning (CFG-007). No gc file logging option after the last -Xlog:disable → Warning (CFG-008). No ErrorFile → Info (CFG-009). On orchestrator deployments these drop to Info."""
    out, no_dump, no_gclog, no_errfile = [], [], [], []
    for n in ctx.nodes:
        args = n.jvm_args()
        if not args:
            continue
        joined = " ".join(args)
        if "HeapDumpOnOutOfMemoryError" not in joined or "-XX:-HeapDumpOnOutOfMemoryError" in joined:
            no_dump.append(n.name)
        if not _gc_logging_enabled(args):
            no_gclog.append(n.name)
        if "ErrorFile" not in joined:
            no_errfile.append(n.name)
    if no_dump:
        sev, rec = _orch(ctx, Severity.WARNING,
                         T("rules.guidance.r_jvm_diag_settings.01"))
        out.append(Finding(
            "CFG-007", CFG, sev, T("rules.guidance.r_jvm_diag_settings.02"),
            observed=T("rules.guidance.r_jvm_diag_settings.03") % ", ".join(no_dump),
            impact=T("rules.guidance.r_jvm_diag_settings.04"),
            recommend=rec, refs=[D_SETTINGS], source="nodes.json (jvm.input_arguments)"))
    if no_gclog:
        sev, rec = _orch(ctx, Severity.WARNING,
                         T("rules.guidance.r_jvm_diag_settings.05"))
        out.append(Finding(
            "CFG-008", CFG, sev, T("rules.guidance.r_jvm_diag_settings.06"),
            observed=T("rules.guidance.r_jvm_diag_settings.03") % ", ".join(no_gclog),
            impact=T("rules.guidance.r_jvm_diag_settings.07"),
            recommend=rec, refs=[D_SETTINGS], source="nodes.json (jvm.input_arguments)"))
    if no_errfile:
        sev, rec = _orch(ctx, Severity.INFO, T("rules.guidance.r_jvm_diag_settings.08"))
        out.append(Finding(
            "CFG-009", CFG, sev, T("rules.guidance.r_jvm_diag_settings.09"),
            observed=T("rules.guidance.r_jvm_diag_settings.03") % ", ".join(no_errfile),
            impact=T("rules.guidance.r_jvm_diag_settings.10"),
            recommend=rec, refs=[D_SETTINGS], source="nodes.json (jvm.input_arguments)"))
    return out


def r_docs_per_shard(ctx):
    """Document count per shard. Rated on per-shard values (cat shards), not the index average.

    The Lucene limit (2,147,483,519) applies to maxDoc, which includes deleted documents. cat shards has no deleted count,
    so the index deleted count divided by the number of primaries is added (shown as an estimate).
    Rollover always runs once a shard reaches 200M documents, and ILM checks the condition every poll_interval (10m by default),
    so a rolled-over index normally ends a little above 200M. Rolled-over indices are reported only when they exceed 200M by more
    than docs_rollover_overshoot_pct (SHD-013, rollover ran late). Searchable snapshot mounts take no writes and are rated the same way.
    The write index and indices without rollover keep SHD-008.
    """
    pri_count = collections.Counter()
    for s in ctx.shards:
        if (s.get("prirep") or "").lower() == "p":
            pri_count[s.get("index")] += 1
    limit = ctx.t["docs_per_shard_warn"]
    late_limit = limit * (1 + ctx.t["docs_rollover_overshoot_pct"] / 100.0)
    warn, crit, late = [], [], []
    for s in ctx.shards:
        if (s.get("prirep") or "").lower() != "p":
            continue
        idx = s.get("index")
        try:
            docs = int(str(num(s, "docs")))
        except ValueError:
            continue
        deleted = num(ctx.indices_stats, idx, "primaries", "docs", "deleted")
        est = docs + (deleted / float(pri_count[idx] or 1))
        row = [idx, s.get("shard"), fmt_num(docs), fmt_num(int(est)), s.get("node")]
        if est >= ctx.t["docs_per_shard_crit"]:
            crit.append(row)
        elif docs >= limit:
            if ctx.rolled_over(idx) or ctx.is_searchable_snapshot(idx):
                if docs > late_limit:
                    ds = ctx.data_stream_of(idx)
                    late.append([idx, s.get("shard"), fmt_num(docs), "+%.1f%%" % ((docs / float(limit) - 1) * 100),
                                 (ds or {}).get("name") or "-", ctx.ilm_policy_of(idx) or "-"])
            else:
                warn.append(row)
    out = []
    cols = ["index", "shard", T("rules.guidance.r_docs_per_shard.01"), T("rules.guidance.r_docs_per_shard.02"), "node"]
    if crit:
        out.append(Finding(
            "SHD-007", SIZ, Severity.CRITICAL, T("rules.guidance.r_docs_per_shard.03"),
            observed=T("rules.guidance.r_docs_per_shard.04") % (fmt_num(ctx.t["docs_per_shard_crit"]), len(crit)),
            impact=T("rules.guidance.r_docs_per_shard.05"),
            recommend=T("rules.guidance.r_docs_per_shard.06"),
            evidence=table(cols, crit[: ctx.t["top_n"]]), refs=[D_SHARDS], source="indices.json"))
    if warn:
        out.append(Finding(
            "SHD-008", SIZ, Severity.WARNING, T("rules.guidance.r_docs_per_shard.07"),
            observed=T("rules.guidance.r_docs_per_shard.08") % (fmt_num(limit), len(warn)),
            impact=T("rules.guidance.r_docs_per_shard.09"),
            recommend=T("rules.guidance.r_docs_per_shard.10"),
            evidence=table(cols, warn[: ctx.t["top_n"]]), refs=[D_SHARDS, D_ROLLOVER], source="indices.json"))
    if late:
        late.sort(key=lambda r: -int(r[2].replace(",", "")))
        out.append(Finding(
            "SHD-013", SIZ, Severity.WARNING, T("rules.guidance.r_docs_per_shard.11"),
            observed=T("rules.guidance.r_docs_per_shard.12") % (len(late), fmt_num(limit), ctx.t["docs_rollover_overshoot_pct"]),
            impact=T("rules.guidance.r_docs_per_shard.13"),
            recommend=T("rules.guidance.r_docs_per_shard.14"),
            evidence=table(["index", "shard", T("rules.guidance.r_docs_per_shard.01"), T("rules.guidance.r_docs_per_shard.15"),
                            "data stream", "ILM policy"], late[: ctx.t["top_n"]]),
            refs=[D_ROLLOVER, D_ILM_SETTINGS], source="indices.json / commercial/ilm_explain.json"))
    return out


def _rollover_trigger(ctx, idx, docs, shard_bytes, is_write):
    """Best guess of the rollover condition that ended this index. The bundle does not record it."""
    if is_write:
        return T("rules.guidance.r_logsdb_shard_size.20")
    ro = ctx.rollover_conditions(ctx.ilm_policy_of(idx))
    if docs is not None and docs >= ctx.t["ilm_implicit_max_shard_docs"]:
        return T("rules.guidance.r_logsdb_shard_size.21")
    mds = num(ro, "max_primary_shard_docs", default=None)
    if mds and docs is not None and docs >= mds * 0.95:
        return "max_primary_shard_docs"
    for key in ("max_primary_shard_size", "max_size"):
        lim = parse_bytes(ro.get(key))
        if lim and shard_bytes >= lim * 0.9 / (1 if key == "max_primary_shard_size" else max(ctx.primary_count(idx), 1)):
            return key
    if ro.get("max_age"):
        return T("rules.guidance.r_logsdb_shard_size.22") % ro.get("max_age")
    return "-"


def r_logsdb_shard_size(ctx):
    """Primary shard size of logsdb indices against the 10-30GB range (tool judgment, Info).

    Basis: rollover always runs at 200M documents per shard (official), and the official docs note that space-efficient data
    reaches 200M documents before 50GB. logsdb sorts by host.name and @timestamp by default (official), and index sorting
    costs time at flush and merge (official). force merge to one segment needs up to 3x the shard size in free space (official),
    and large shards take longer to recover (official). The 30GB upper end is not an official number: it follows an Elastic
    internal discussion that 10-30GB suits logsdb and TSDB. The official 10-50GB range and SHD-003 (50GB and above) still apply.

    Partially mounted (frozen) indices are skipped because their size is the cache size. Per index, the largest primary
    shard is rated. logsdb_shard_gb_high <= largest primary < shard_size_gb_warn → SHD-014 (Info, listed per index).
    SHD-015 (Info) is rated per data stream: a data stream with ds_min_backing_indices or more finished backing indices
    (rolled over or mounted) whose largest primary is below logsdb_shard_gb_low with 1 to 200M documents. Those indices were
    ended by max_age or a small size condition, not by the document limit. Empty indices are left to SHD-011.
    The rollover condition shown is an estimate (the most common one per data stream for SHD-015).
    """
    hi, lo = ctx.t["logsdb_shard_gb_high"] * GB, ctx.t["logsdb_shard_gb_low"] * GB
    top = ctx.t["shard_size_gb_warn"] * GB
    biggest = {}
    for s in ctx.shards:
        if (s.get("prirep") or "").lower() != "p":
            continue
        idx = s.get("index")
        if not idx or ctx.is_system_index(idx) or ctx.is_partial_mount(idx):
            continue
        b = parse_bytes(s.get("store"))
        if b is None:
            continue
        try:
            docs = int(str(num(s, "docs")))
        except ValueError:
            docs = None
        if idx not in biggest or b > biggest[idx][0]:
            biggest[idx] = (b, docs)
    logsdb = [i for i in biggest if ctx.index_mode(i) == "logsdb"]
    if not logsdb:
        return []
    writes = ctx.write_targets()
    big = []
    small_by_ds = collections.defaultdict(list)
    done_by_ds = collections.Counter()
    for idx in logsdb:
        b, docs = biggest[idx]
        is_write = idx in writes
        ds = ctx.data_stream_of(idx)
        ds_name = str(ds.get("name")) if ds and ds.get("name") else None
        finished = not is_write and (ctx.rolled_over(idx) or ctx.is_searchable_snapshot(idx))
        if ds_name and finished:
            done_by_ds[ds_name] += 1
        if hi <= b < top:
            big.append((b, idx, docs, is_write))
        elif ds_name and finished and b < lo and docs and docs < ctx.t["ilm_implicit_max_shard_docs"]:
            small_by_ds[ds_name].append((b, idx, docs))
    small = []
    for name, lst in small_by_ds.items():
        if len(lst) < ctx.t["ds_min_backing_indices"]:
            continue
        sizes = sorted(x[0] for x in lst)
        dcs = sorted(x[2] for x in lst)
        trig = collections.Counter(_rollover_trigger(ctx, i, d, bb, False) for bb, i, d in lst).most_common(1)[0][0]
        pol = collections.Counter(ctx.ilm_policy_of(i) or "-" for _, i, _ in lst).most_common(1)[0][0]
        small.append((len(lst), name, [name, "%d / %d" % (len(lst), done_by_ds[name]), fmt_bytes(sizes[len(sizes) // 2]),
                                       fmt_num(dcs[len(dcs) // 2]), trig, pol]))
    lic = (ctx.license.get("type") or "-") if isinstance(ctx.license, dict) else "-"
    cols = ["index", "data stream", T("rules.guidance.r_logsdb_shard_size.01"), T("rules.guidance.r_logsdb_shard_size.02"),
            T("rules.guidance.r_logsdb_shard_size.03"), T("rules.guidance.r_logsdb_shard_size.04"), "ILM policy"]

    def rows(lst):
        out = []
        for b, idx, docs, is_write in lst[: ctx.t["logsdb_rows_max"]]:
            ds = ctx.data_stream_of(idx)
            out.append([idx, (ds or {}).get("name") or "-", fmt_bytes(b), fmt_num(docs),
                        ("%.0fB" % (b / float(docs))) if docs else "-",
                        _rollover_trigger(ctx, idx, docs, b, is_write), ctx.ilm_policy_of(idx) or "-"])
        return out
    out = []
    if big:
        big.sort(key=lambda r: -r[0])
        out.append(Finding(
            "SHD-014", SIZ, Severity.INFO, T("rules.guidance.r_logsdb_shard_size.05"),
            observed=T("rules.guidance.r_logsdb_shard_size.06")
                     % (len(logsdb), len(big), ctx.t["logsdb_shard_gb_high"], ctx.t["shard_size_gb_warn"], lic),
            impact=T("rules.guidance.r_logsdb_shard_size.07"),
            recommend=T("rules.guidance.r_logsdb_shard_size.08") % ctx.t["logsdb_shard_gb_high"],
            evidence=table(cols, rows(big)), affected=[r[1] for r in big],
            refs=[D_ROLLOVER, D_LOGSDB, D_SORT, D_FORCEMERGE, D_SHARDS],
            source="indices.json / settings.json / commercial/data_stream.json"))
    if small:
        small.sort(key=lambda r: (-r[0], r[1]))
        n_ds = len(set(str(n) for n in (((ctx.data_stream_of(i) or {}).get("name")) for i in logsdb) if n))
        out.append(Finding(
            "SHD-015", SIZ, Severity.INFO, T("rules.guidance.r_logsdb_shard_size.09"),
            observed=T("rules.guidance.r_logsdb_shard_size.10")
                     % (n_ds, len(small), ctx.t["logsdb_shard_gb_low"], ctx.t["ds_min_backing_indices"]),
            impact=T("rules.guidance.r_logsdb_shard_size.11"),
            recommend=T("rules.guidance.r_logsdb_shard_size.12"),
            evidence=table(["data stream", T("rules.guidance.r_logsdb_shard_size.13"), T("rules.guidance.r_logsdb_shard_size.14"),
                            T("rules.guidance.r_logsdb_shard_size.15"), T("rules.guidance.r_logsdb_shard_size.16"), "ILM policy"],
                           [r[2] for r in small[: ctx.t["logsdb_rows_max"]]]),
            affected=[r[1] for r in small],
            refs=[D_SHARDS, D_ROLLOVER], source="indices.json / settings.json / commercial/data_stream.json / commercial/ilm_policies.json"))
    return out


def r_logsdb_adoption(ctx):
    """Elasticsearch 9.0+ and logs-*-* data streams whose write index is not in logsdb mode → Info (IDX-013).

    Official: from 9.0, logsdb is set automatically on new logs-*-* data streams. Data streams that existed before an
    upgrade from 8.x, including integration and APM streams, are not switched. Data streams set to time_series, or to the
    columnar or logsdb_columnar modes added in 9.5, are skipped, and so are bundles without settings.json and data_stream.json index_mode, where the mode cannot be determined.
    The switch is cluster.logsdb.enabled: it defaults to false when logs data existed before 9.0 (logsdb.prior_logs_usage),
    and while it is false even new logs-*-* indices stay standard. Its value is shown when the bundle reports it.
    """
    if ctx.version_tuple < (9, 0, 0):
        return []
    rows = []
    for ds in dicts(ctx.data_streams):
        name = str(ds.get("name") or "")
        parts = name.split("-")
        if not name.startswith("logs-") or len(parts) < 3 or not all(parts[1:]):
            continue
        idxs = [i.get("index_name") for i in dicts(ds.get("indices"))]
        if not idxs:
            continue
        w = idxs[-1]
        known = ctx.index_setting(w, "index.mode") is not None or ds.get("index_mode") or \
            any(i.get("index_mode") for i in dicts(ds.get("indices"))) or w in ctx.index_settings
        mode = ctx.index_mode(w)
        if not known or mode in ("logsdb", "time_series", "columnar", "logsdb_columnar"):
            continue
        b = dig(ctx.indices_stats, w, "primaries", "store", "size_in_bytes")
        rows.append([name, w, mode, fmt_bytes(b) if b is not None else "-", ds.get("template") or "-"])
    if not rows:
        return []
    rows.sort()
    enabled = ctx.setting("cluster.logsdb.enabled")
    prior = ctx.setting("logsdb.prior_logs_usage")
    obs = T("rules.guidance.r_logsdb_adoption.02") % (ctx.version, len(rows))
    if enabled is not None:
        obs += T("rules.guidance.r_logsdb_adoption.06") % (str(enabled).lower(), str(prior).lower() if prior is not None else "-")
    return [Finding(
        "IDX-013", SIZ, Severity.INFO, T("rules.guidance.r_logsdb_adoption.01"),
        observed=obs,
        impact=T("rules.guidance.r_logsdb_adoption.03"),
        recommend=T("rules.guidance.r_logsdb_adoption.04"),
        evidence=table(["data stream", "write index", "index.mode", T("rules.guidance.r_logsdb_adoption.05"), "template"],
                       rows[: ctx.t["top_n"]]),
        affected=[r[0] for r in rows], refs=[D_LOGS_DS, D_LOGSDB],
        source="commercial/data_stream.json / settings.json")]


def r_master_heap_per_index(ctx):
    """Based on 3000 indices per 1GB of heap on master-eligible nodes."""
    n_idx = dig(ctx.cluster_stats, "indices", "count") or len(ctx.indices_stats)
    masters = [n for n in ctx.master_nodes if n.heap_max]
    if not masters or not n_idx:
        return []
    rows, bad = [], []
    for n in masters:
        heap_gb = n.heap_max / float(GB)
        capacity = heap_gb * ctx.t["indices_per_gb_master_heap"]
        rows.append([n.name, "%.1fGB" % heap_gb, fmt_num(int(capacity)), fmt_num(n_idx),
                     "%.0f%%" % (n_idx / capacity * 100) if capacity else "-"])
        if capacity and n_idx >= capacity * 0.8:
            bad.append(n.name)
    if not bad:
        return []
    return [Finding(
        "SHD-009", SIZ, Severity.CRITICAL if any(
            n_idx >= (n.heap_max / float(GB)) * ctx.t["indices_per_gb_master_heap"] for n in masters)
        else Severity.WARNING,
        T("rules.guidance.r_master_heap_per_index.01"),
        observed=T("rules.guidance.r_master_heap_per_index.02")
                 % (fmt_num(n_idx), fmt_num(ctx.t["indices_per_gb_master_heap"]), ", ".join(bad)),
        impact=T("rules.guidance.r_master_heap_per_index.03"),
        recommend=T("rules.guidance.r_master_heap_per_index.04"),
        evidence=table([T("rules.guidance.r_master_heap_per_index.05"), "heap", T("rules.guidance.r_master_heap_per_index.06"), T("rules.guidance.r_master_heap_per_index.07"), T("rules.guidance.r_master_heap_per_index.08")], rows),
        refs=[D_SHARDS], source="cluster_stats.json / nodes.json")]


def r_mapping_heap_overhead(ctx):
    """Estimated heap needed per data node = cluster state mapping size (deduplicated) + node field overhead + 0.5GB (official formula).

    The official check is that the estimate fits in the heap: estimate >= heap_max → Warning. Estimate / heap_max >= mapping_heap_pct_warn
    (tool threshold) → Info, below → OK. Dedicated master and ML nodes are not part of the calculation.
    """
    dedup = dig(ctx.cluster_stats, "indices", "mappings", "total_deduplicated_mapping_size_in_bytes")
    rows, bad = [], []
    # The official formula (heap per field + 0.5GB) applies to data nodes that hold shards. Dedicated master and ML nodes are excluded.
    for n in ctx.data_nodes:
        over = dig(n.stats, "indices", "mappings", "total_estimated_overhead_in_bytes")
        heap = n.heap_max
        if over is None or not heap:
            continue
        need = (over or 0) + (dedup or 0) + ctx.t["heap_baseline_bytes"]
        p = pct(need, heap)
        rows.append([n.name, fmt_bytes(dedup), fmt_bytes(over), fmt_bytes(need), fmt_bytes(heap),
                     "%.0f%%" % p if p else "-"])
        if p and p >= ctx.t["mapping_heap_pct_warn"]:
            bad.append((n.name, p))
    if not rows:
        return []
    ev = table(["node", T("rules.guidance.r_mapping_heap_overhead.01"), T("rules.guidance.r_mapping_heap_overhead.02"), T("rules.guidance.r_mapping_heap_overhead.03"), "heap", T("rules.guidance.r_mapping_heap_overhead.04")], rows)
    if not bad:
        return [Finding("SHD-010", SIZ, Severity.OK, T("rules.guidance.r_mapping_heap_overhead.05"),
                        observed=T("rules.guidance.r_mapping_heap_overhead.06")
                                 % ctx.t["mapping_heap_pct_warn"],
                        evidence=ev, refs=[D_SHARDS], source="cluster_stats.json / nodes_stats.json")]
    over = [b for b in bad if b[1] >= 100]
    return [Finding(
        "SHD-010", SIZ, Severity.WARNING if over else Severity.INFO, T("rules.guidance.r_mapping_heap_overhead.07"),
        observed=(T("rules.guidance.r_mapping_heap_overhead.11") % ", ".join(b[0] for b in over)) if over else
                 T("rules.guidance.r_mapping_heap_overhead.08") % (ctx.t["mapping_heap_pct_warn"], ", ".join(b[0] for b in bad)),
        impact=T("rules.guidance.r_mapping_heap_overhead.09"),
        recommend=T("rules.guidance.r_mapping_heap_overhead.10"),
        evidence=ev, refs=[D_SHARDS], source="cluster_stats.json / nodes_stats.json")]


def r_empty_indices(ctx):
    """Number of user indices with docs.count=0 >= empty_index_count_warn → Warning.

    Current write targets (data stream write index, alias write index) are excluded, because they may be empty right after a rollover.
    """
    rows = []
    targets = ctx.write_targets()
    for name, st in ctx.indices_stats.items():
        if ctx.is_system_index(name) or name in targets:
            continue        # Current write targets (e.g. a freshly rolled-over write index) are normally empty
        docs = dig(st, "primaries", "docs", "count")
        if docs == 0:
            shards = ctx.shard_count(name)
            rows.append([name, shards, fmt_bytes(dig(st, "total", "store", "size_in_bytes"))])
    if len(rows) < ctx.t["empty_index_count_warn"]:
        return []
    total_shards = sum(r[1] for r in rows)
    return [Finding(
        "SHD-011", SIZ, Severity.WARNING, T("rules.guidance.r_empty_indices.01"),
        observed=T("rules.guidance.r_empty_indices.02") % (len(rows), total_shards),
        impact=T("rules.guidance.r_empty_indices.03"),
        recommend=T("rules.guidance.r_empty_indices.04"),
        evidence=table(["index", T("rules.guidance.r_empty_indices.05"), T("rules.guidance.r_empty_indices.06")], rows[: ctx.t["top_n"]]),
        refs=[D_SHARDS], source="indices_stats.json")]


def r_total_shards_per_node(ctx):
    """Whether index.routing.allocation.total_shards_per_node is set to prevent hot spots (heavily indexed indices)."""
    rows = []
    for name, st in ctx.indices_stats.items():
        if ctx.is_system_index(name):
            continue
        it = num(st, "total", "indexing", "index_total")
        if it < ctx.t["heavy_index_docs"]:
            continue
        v = ctx.index_setting(name, "index.routing.allocation.total_shards_per_node")
        if v is None:
            rows.append([name, fmt_num(it),
                         ctx.shard_count(name)])
    if not rows:
        return []
    return [Finding(
        "SHD-012", SIZ, Severity.INFO, T("rules.guidance.r_total_shards_per_node.01"),
        observed=T("rules.guidance.r_total_shards_per_node.02") % len(rows),
        impact=T("rules.guidance.r_total_shards_per_node.03"),
        recommend=T("rules.guidance.r_total_shards_per_node.04"),
        evidence=table(["index", T("rules.guidance.r_total_shards_per_node.05"), T("rules.guidance.r_total_shards_per_node.06")], rows[: ctx.t["top_n"]]),
        refs=[D_SHARDS], source="settings.json / indices_stats.json")]


# ============================================================
# indexing-speed / search-speed
# ============================================================

def r_index_buffer(ctx):
    """Indexing buffer per shard.

    indices.memory.index_buffer_size (default 10% of heap) is shared by the 'recently written (active)' shards.
    A shard with no writes for 5 minutes or more (indices.memory.shard_inactive_time, from the source) becomes inactive and gives its buffer back. The bundle cannot show directly which shards are active,
    so only shards that are confirmed write targets (data stream write indices plus indices that were indexing at collection time) are counted.
    """
    write_idx = set()
    for ds in ctx.data_streams or []:
        idxs = ds.get("indices") or []
        if idxs:
            write_idx.add(idxs[-1].get("index_name"))
    for name, st in ctx.indices_stats.items():
        if (num(st, "total", "indexing", "index_current")) > 0:
            write_idx.add(name)
    if not write_idx:
        return []
    active = collections.Counter()
    for s in ctx.shards:
        if s.get("node") and s.get("index") in write_idx:
            active[s["node"]] += 1
    rows = []
    for n in ctx.nodes:
        buf = parse_bytes(dig(n.info, "total_indexing_buffer_in_bytes")
                          or dig(n.info, "total_indexing_buffer"))
        shards = active.get(n.name, 0)
        if not buf or not shards:
            continue
        per = buf / float(shards)
        if per < ctx.t["index_buffer_per_shard_warn"]:
            rows.append([n.name, fmt_bytes(buf), shards, fmt_bytes(per)])
    if not rows:
        return []
    return [Finding(
        "PERF-004", SPD, Severity.INFO, T("rules.guidance.r_index_buffer.01"),
        observed=T("rules.guidance.r_index_buffer.02")
                 % (fmt_bytes(ctx.t["index_buffer_per_shard_warn"]), len(rows)),
        impact=T("rules.guidance.r_index_buffer.03"),
        recommend=T("rules.guidance.r_index_buffer.04"),
        evidence=table(["node", "indexing buffer", T("rules.guidance.r_index_buffer.05"), T("rules.guidance.r_index_buffer.06")], rows),
        refs=[D_INDEX], source="nodes.json / data_stream.json / indices.json")]


def r_open_contexts(ctx):
    """Node search.open_contexts >= open_contexts_warn → Warning."""
    rows = []
    for n in ctx.nodes:
        oc = num(n.stats, "indices", "search", "open_contexts")
        sc = num(n.stats, "indices", "search", "scroll_current")
        if oc >= ctx.t["open_contexts_warn"]:
            rows.append([n.name, fmt_num(oc), fmt_num(sc),
                         fmt_num(dig(n.stats, "indices", "search", "scroll_total"))])
    if not rows:
        return []
    return [Finding(
        "PERF-005", SPD, Severity.WARNING, T("rules.guidance.r_open_contexts.01"),
        observed=T("rules.guidance.r_open_contexts.02") % (ctx.t["open_contexts_warn"], len(rows)),
        impact=T("rules.guidance.r_open_contexts.03"),
        recommend=T("rules.guidance.r_open_contexts.04"),
        evidence=table(["node", "open_contexts", T("rules.guidance.r_open_contexts.05"), T("rules.guidance.r_open_contexts.06")], rows),
        refs=[D_SEARCH], source="nodes_stats.json")]


def r_search_timeout(ctx):
    """Info if search.default_search_timeout is not set or is -1 (unlimited)."""
    v = ctx.setting("search.default_search_timeout")
    if v and str(v) not in ("-1", "-1ms", "0"):
        return []
    return [Finding(
        "PERF-006", SPD, Severity.INFO, T("rules.guidance.r_search_timeout.01"),
        observed=T("rules.guidance.r_search_timeout.02"),
        impact=T("rules.guidance.r_search_timeout.03"),
        recommend=T("rules.guidance.r_search_timeout.04"),
        refs=[D_SEARCH], source="cluster_settings.json")]


def r_replica_throughput(ctx):
    """Formula recommended in the search-speed guide: replicas = max(max_failures, ceil(num_nodes/num_primaries) - 1)."""
    import math
    data_nodes = len(ctx.data_nodes) or len(ctx.nodes)
    if data_nodes < 2:
        return []
    rows = []
    for name, st in ctx.indices_stats.items():
        if ctx.is_system_index(name):
            continue
        qt = num(st, "total", "search", "query_total")
        if qt < ctx.t["search_heavy_query_total"]:
            continue
        pri = ctx.primary_count(name)
        rep = ctx.index_setting(name, "index.number_of_replicas")
        try:
            rep = int(rep)
        except (TypeError, ValueError):
            continue
        if not pri:
            continue
        ideal = max(1, int(math.ceil(data_nodes / float(pri))) - 1)
        if rep < ideal:
            rows.append([name, fmt_num(qt), pri, rep, ideal])
    if not rows:
        return []
    return [Finding(
        "PERF-007", SPD, Severity.INFO, T("rules.guidance.r_replica_throughput.01"),
        observed=T("rules.guidance.r_replica_throughput.02") % len(rows),
        impact=T("rules.guidance.r_replica_throughput.03"),
        recommend=T("rules.guidance.r_replica_throughput.04"),
        evidence=table(["index", T("rules.guidance.r_replica_throughput.05"), "primary", T("rules.guidance.r_replica_throughput.06"), T("rules.guidance.r_replica_throughput.07")],
                       rows[: ctx.t["top_n"]]),
        refs=[D_SEARCH], source="settings.json / indices_stats.json")]


# index.store.preload that the vectordb_document index mode (9.5) sets on its own when the user leaves it unset
# (IndexMode.VECTORDB_DOCUMENT_MODE_PRELOAD_EXTENSIONS in the Elasticsearch source).
VECTORDB_PRELOAD = ("cenivf", "veb", "veq", "vex")


def r_store_preload(ctx):
    """Info if any index has index.store.preload set; Warning if the count is > preload_index_count_warn.

    vectordb_document indices (9.5) get index.store.preload for their vector files automatically, so that exact value is not listed.
    """
    rows = []
    for name in ctx.index_settings.keys():
        v = ctx.index_setting(name, "index.store.preload")
        if v and str(ctx.index_mode(name) or "").lower() == "vectordb_document" and \
                tuple(sorted(x.strip() for x in (v if isinstance(v, list) else str(v).strip("[]").split(",")) if x.strip())) == VECTORDB_PRELOAD:
            continue
        if v:
            rows.append([name, str(v)])
    if not rows:
        return []
    sev = Severity.WARNING if len(rows) > ctx.t["preload_index_count_warn"] else Severity.INFO
    return [Finding(
        "PERF-008", SPD, sev, T("rules.guidance.r_store_preload.01"),
        observed=T("rules.guidance.r_store_preload.02") % len(rows),
        impact=T("rules.guidance.r_store_preload.03"),
        recommend=T("rules.guidance.r_store_preload.04"),
        evidence=table(["index", "preload"], rows[: ctx.t["top_n"]]),
        refs=[D_SEARCH, D_KNN], source="settings.json")]


def r_remote_storage(ctx):
    """Warning if nodes_stats fs.data[].type includes nfs / cifs / smb / fuse / glusterfs / ceph."""
    rows = []
    for n in ctx.nodes:
        for d in dig(n.stats, "fs", "data", default=[]) or []:
            t = (d.get("type") or "").lower()
            if t and any(x in t for x in ("nfs", "cifs", "smb", "fuse", "glusterfs", "ceph")):
                rows.append([n.name, d.get("mount"), d.get("type"), fmt_bytes(d.get("total_in_bytes"))])
    if not rows:
        return []
    return [Finding(
        "PERF-009", SPD, Severity.WARNING, T("rules.guidance.r_remote_storage.01"),
        observed=T("rules.guidance.r_remote_storage.02") % len(rows),
        impact=T("rules.guidance.r_remote_storage.03"),
        recommend=T("rules.guidance.r_remote_storage.04"),
        evidence=table(["node", "mount", "type", T("rules.guidance.r_remote_storage.05")], rows),
        affected=sorted(set(r[0] for r in rows)), refs=[D_INDEX, D_SEARCH], source="nodes_stats.json")]


# ============================================================
# disk-usage
# ============================================================

def r_codec(ctx):
    """User indices with primary store >= codec_check_min_bytes and index.codec left at default (not set) → Info.

    Index modes whose default codec is best_compression are excluded: logsdb, and the columnar and logsdb_columnar modes added in 9.5
    (official logsdb docs, and IndexMode in the Elasticsearch source). standard, time_series and vectordb_document indices default to
    the LZ4 codec.
    """
    rows = []
    for name, st in ctx.indices_stats.items():
        if ctx.is_system_index(name):
            continue
        size = num(st, "primaries", "store", "size_in_bytes")
        if size < ctx.t["codec_check_min_bytes"]:
            continue
        mode = str(ctx.index_mode(name) or "standard").lower()
        if mode in BEST_COMPRESSION_MODES:
            continue        # best_compression is the default for this index mode
        codec = ctx.index_setting(name, "index.codec")
        if codec is None or str(codec).lower() == "default":
            rows.append([name, fmt_bytes(size), str(codec or "default"), mode, size])
    if not rows:
        return []
    rows.sort(key=lambda r: -r[4])
    total = sum(r[4] for r in rows)
    return [Finding(
        "DISK-006", SIZ, Severity.INFO, T("rules.guidance.r_codec.01"),
        observed=T("rules.guidance.r_codec.02")
                 % (fmt_bytes(ctx.t["codec_check_min_bytes"]), len(rows), fmt_bytes(total)),
        impact=T("rules.guidance.r_codec.03"),
        recommend=T("rules.guidance.r_codec.04"),
        evidence=table(["index", T("rules.guidance.r_codec.05"), "codec", "index.mode"], [r[:4] for r in rows[: ctx.t["top_n"]]]),
        refs=[D_DISK], source="settings.json / indices_stats.json")]


def r_source_mode(ctx):
    """_source disabled → Warning; synthetic _source → Info (DISK-007).

    Disabled is found two ways: the mapping parameter "_source": {"enabled": false} in mapping.json (the documented way), and
    index.mapping.source.mode=disabled in settings.json. index.mapping.source.mode=synthetic, and columnar_stored (9.5 columnar
    modes), are listed as Info: the returned _source is rebuilt, not the original. stored is the default and is not listed.
    System indices are skipped.
    """
    disabled, synthetic = [], []
    seen = set()
    for name, summ in items(ctx.mapping_summary):
        if ctx.is_system_index(name) or not isinstance(summ, dict):
            continue
        if summ.get("source_disabled"):
            disabled.append([name, "_source.enabled: false"])
            seen.add(name)
    for name in ctx.index_settings.keys():
        if ctx.is_system_index(name):
            continue
        mode = str(ctx.index_setting(name, "index.mapping.source.mode") or "").lower()
        if mode == "disabled" and name not in seen:
            disabled.append([name, "index.mapping.source.mode: disabled"])
        elif mode in ("synthetic", "columnar_stored"):
            synthetic.append([name, "index.mapping.source.mode: " + mode])
    if disabled:
        disabled.sort()
        return [Finding(
            "DISK-007", SIZ, Severity.WARNING, T("rules.guidance.r_source_mode.05"),
            observed=T("rules.guidance.r_source_mode.06") % len(disabled),
            impact=T("rules.guidance.r_source_mode.07"),
            recommend=T("rules.guidance.r_source_mode.08"),
            evidence=table(["index", T("rules.guidance.r_source_mode.09")], disabled[: ctx.t["top_n"]]),
            refs=[D_DISK, D_SOURCE], source="mapping.json / settings.json")]
    if synthetic:
        synthetic.sort()
        return [Finding(
            "DISK-007", SIZ, Severity.INFO, T("rules.guidance.r_source_mode.01"),
            observed=T("rules.guidance.r_source_mode.02") % len(synthetic),
            impact=T("rules.guidance.r_source_mode.03"),
            recommend=T("rules.guidance.r_source_mode.04"),
            evidence=table(["index", T("rules.guidance.r_source_mode.09")], synthetic[: ctx.t["top_n"]]),
            refs=[D_DISK, D_SOURCE], source="settings.json")]
    return []


def r_dynamic_mapping(ctx):
    """Checks whether dynamic mapping is controlled, based on the result merged with the components."""
    rows = []
    for name, mappings, _settings, patterns in _composed_templates(ctx):
        if str(name).startswith(".") or not patterns:
            continue
        if all(str(p).startswith(".") for p in patterns):
            continue
        dyn = mappings.get("dynamic")
        has_dyn_tpl = bool(mappings.get("dynamic_templates"))
        if dyn is None and not has_dyn_tpl:
            rows.append([name, ", ".join(patterns)[:80], T("rules.guidance.r_dynamic_mapping.01"), T("rules.guidance.r_dynamic_mapping.02")])
    if not rows:
        return []
    return [Finding(
        "MAP-003", SIZ, Severity.INFO, T("rules.guidance.r_dynamic_mapping.03"),
        observed=T("rules.guidance.r_dynamic_mapping.04") % len(rows),
        impact=T("rules.guidance.r_dynamic_mapping.05"),
        recommend=T("rules.guidance.r_dynamic_mapping.06"),
        evidence=table(["template", "index_patterns", "dynamic", T("rules.guidance.r_dynamic_mapping.07")], rows[: ctx.t["top_n"]]),
        refs=[D_DISK, D_SHARDS], source="index_templates.json / component_templates.json")]


def _deep_merge(a, b):
    out = dict(a or {})
    for k, v in items(b):
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _composed_templates(ctx):
    """Merges an index template with its composed_of components into the mappings/settings that 'actually apply'.

    ES merges the components in composed_of order, then applies the index template body last, overriding them.
    """
    comps = {}
    for c in (ctx.component_templates or {}).get("component_templates") or []:
        comps[c.get("name")] = dig(c, "component_template", "template", default={}) or {}
    out = []
    for it in (ctx.index_templates or {}).get("index_templates") or []:
        body = it.get("index_template") or {}
        merged = {}
        for cname in strs(body.get("composed_of")):
            merged = _deep_merge(merged, comps.get(cname) or {})
        merged = _deep_merge(merged, body.get("template") or {})
        out.append((it.get("name"), merged.get("mappings") or {}, merged.get("settings") or {},
                    body.get("index_patterns") or []))
    return out


def _vector_stats(ctx):
    """Per-index dense_vector off-heap usage (9.x indices stats)."""
    out = {}
    for name, st in ctx.indices_stats.items():
        # Searches also run on replicas, so use total (primary+replica).
        dv = dig(st, "total", "dense_vector", default={}) or \
            dig(st, "primaries", "dense_vector", default={}) or {}
        total = dig(dv, "off_heap", "total_size_bytes")
        if total is None:
            total = dv.get("off_heap_size_bytes")
        cnt = num(dv, "value_count")
        if total or cnt:
            vec = num(dv, "off_heap", "total_vec_size_bytes")
            veq = num(dv, "off_heap", "total_veq_size_bytes")
            veb = num(dv, "off_heap", "total_veb_size_bytes")
            vex = num(dv, "off_heap", "total_vex_size_bytes")
            # What must stay resident for HNSW traversal: quantized copy + graph if present, otherwise raw vectors + graph.
            # The raw vectors (vec) are read only for rescoring on quantized indices.
            if veq or veb or vec or vex:
                need = ((veq + veb) if (veq or veb) else vec) + vex
            else:
                need = total or 0
            out[name] = {"bytes": total or 0, "need": need, "count": cnt,
                         "vec": vec, "veq": veq, "veb": veb, "vex": vex}
    return out


def r_vector_memory(ctx):
    """Per-index dense_vector off-heap (total, or primaries if total is missing). Required resident size = (veq+veb if present, otherwise vec) + vex. Sum / Σ(data node RAM - heap) >= vector_vs_fscache_pct_warn → Warning, below → Info. This is a cluster-wide estimate and does not look at the per-node distribution."""
    vs = _vector_stats(ctx)
    total = sum(v["need"] for v in vs.values())
    if not total:
        return []
    # Available filesystem cache = data node RAM - heap
    avail = 0
    rows_node = []
    for n in ctx.data_nodes or ctx.nodes:
        ram, heap = n.ram_total or 0, n.heap_max or 0
        free = max(0, ram - heap)
        avail += free
        rows_node.append([n.name, fmt_bytes(ram), fmt_bytes(heap), fmt_bytes(free)])
    top = sorted(vs.items(), key=lambda kv: -kv[1]["need"])[: ctx.t["top_n"]]
    ev = table(["index", T("rules.guidance.r_vector_memory.01"), T("rules.guidance.r_vector_memory.02"), T("rules.guidance.r_vector_memory.03"), T("rules.guidance.r_vector_memory.04"),
                T("rules.guidance.r_vector_memory.05"), T("rules.guidance.r_vector_memory.06")],
               [[k, fmt_bytes(v["need"]), fmt_bytes(v["bytes"]), fmt_num(v["count"]),
                 fmt_bytes(v["vec"]), fmt_bytes(v["veq"] + v["veb"]), fmt_bytes(v["vex"])]
                for k, v in top])
    p = pct(total, avail)
    if p is not None and p >= ctx.t["vector_vs_fscache_pct_warn"]:
        return [Finding(
            "VEC-001", VEC, Severity.WARNING, T("rules.guidance.r_vector_memory.07"),
            observed=T("rules.guidance.r_vector_memory.08")
                     % (fmt_bytes(total), fmt_bytes(avail), p),
            impact=T("rules.guidance.r_vector_memory.09"),
            recommend=T("rules.guidance.r_vector_memory.10"),
            evidence=ev, refs=[D_KNN], source="indices_stats.json / nodes_stats.json")]
    return [Finding(
        "VEC-001", VEC, Severity.INFO, T("rules.guidance.r_vector_memory.11"),
        observed=T("rules.guidance.r_vector_memory.12")
                 % (fmt_bytes(total), fmt_bytes(avail), (" (%.0f%%)" % p) if p is not None else ""),
        impact=T("rules.guidance.r_vector_memory.13"),
        recommend=T("rules.guidance.r_vector_memory.14"),
        evidence=ev, refs=[D_KNN], source="indices_stats.json")]


def r_vector_quantization(ctx):
    """Whether high-dimension float vectors are quantized (rated after merging components).

    From 8.14, a float dense_vector without index_options gets quantized HNSW by default (int8_hnsw; bbq_hnsw for 384 dimensions
    or more from 9.1; bbq_disk from 9.4 when the license allows it). byte and bit vectors are not quantized and are not rated.
    So 'not set' is not treated as a problem on 8.14 or later; only an explicit non-quantized type (hnsw/flat) is rated.
    """
    quant_default = ctx.version_tuple >= (8, 14, 0)
    rows_dim, rows_src = [], []

    def walk(props, path, tname, bucket):
        for fname, f in items(props):
            if not isinstance(f, dict):
                continue
            full = (path + "." + fname) if path else fname
            if f.get("type") == "dense_vector":
                bucket.append(full)
                dims = f.get("dims")
                itype = str((f.get("index_options") or {}).get("type") or "")
                etype = str(f.get("element_type") or "float")
                quantized = any(q in itype for q in ("int8", "int4", "bbq"))
                unquantized_explicit = itype in ("hnsw", "flat")
                missing = not itype
                try:
                    dims_i = int(dims) if dims else 0
                except (TypeError, ValueError):
                    dims_i = 0
                if etype == "float" and dims_i >= ctx.t["vector_dim_quantize_warn"] and not quantized:
                    if unquantized_explicit or (missing and not quant_default):
                        rows_dim.append([tname, full, dims_i, itype or T("rules.guidance.r_vector_quantization.walk.01")])
            if f.get("properties"):
                walk(f["properties"], full, tname, bucket)

    for tname, mappings, settings, _patterns in _composed_templates(ctx):
        found = []
        walk(mappings.get("properties"), "", tname, found)
        if not found:
            continue
        excl = dig(settings, "index", "mapping", "exclude_source_vectors")
        if excl is None:
            excl = settings.get("index.mapping.exclude_source_vectors")
        if excl is None and ctx.version_tuple < (9, 2, 0):
            rows_src.append([tname, ", ".join(found)])
    out = []
    if rows_dim:
        out.append(Finding(
            "VEC-002", VEC, Severity.WARNING, T("rules.guidance.r_vector_quantization.01"),
            observed=T("rules.guidance.r_vector_quantization.02")
                     % (ctx.t["vector_dim_quantize_warn"], len(rows_dim)),
            impact=T("rules.guidance.r_vector_quantization.03"),
            recommend=T("rules.guidance.r_vector_quantization.04"),
            evidence=table(["template", T("rules.guidance.r_vector_quantization.05"), "dims", "index_options.type"], rows_dim[: ctx.t["top_n"]]),
            refs=[D_KNN], source="index_templates.json / component_templates.json"))
    if rows_src:
        out.append(Finding(
            "VEC-003", VEC, Severity.INFO, T("rules.guidance.r_vector_quantization.06"),
            observed=T("rules.guidance.r_vector_quantization.07")
                     % len(rows_src),
            impact=T("rules.guidance.r_vector_quantization.08"),
            recommend=T("rules.guidance.r_vector_quantization.09"),
            evidence=table(["template", T("rules.guidance.r_vector_quantization.10")], rows_src[: ctx.t["top_n"]]),
            refs=[D_KNN], source="index_templates.json / component_templates.json"))
    return out


def r_vector_segments(ctx):
    """For indices with vector data, primary segments / primary shards >= vector_segments_per_shard_warn → Warning."""
    vs = _vector_stats(ctx)
    if not vs:
        return []
    rows = []
    for name in vs:
        seg = num(ctx.indices_stats, name, "primaries", "segments", "count")
        shards = ctx.primary_count(name) or 1
        per = seg / float(shards)
        mms = ctx.index_setting(name, "index.merge.policy.max_merged_segment")
        if per >= ctx.t["vector_segments_per_shard_warn"]:
            rows.append([name, fmt_num(seg), shards, "%.0f" % per, str(mms or T("rules.guidance.r_vector_segments.01"))])
    if not rows:
        return []
    return [Finding(
        "VEC-004", VEC, Severity.WARNING, T("rules.guidance.r_vector_segments.02"),
        observed=T("rules.guidance.r_vector_segments.03")
                 % (ctx.t["vector_segments_per_shard_warn"], len(rows)),
        impact=T("rules.guidance.r_vector_segments.04"),
        recommend=T("rules.guidance.r_vector_segments.05"),
        evidence=table(["index", T("rules.guidance.r_vector_segments.06"), "primary", T("rules.guidance.r_vector_segments.07"), "max_merged_segment"],
                       rows[: ctx.t["top_n"]]),
        refs=[D_KNN], source="indices_stats.json / settings.json")]


def r_large_result_sets(ctx):
    """Whether max_result_window has been raised (user indices)."""
    rows = []
    for name in ctx.index_settings.keys():
        if ctx.is_system_index(name):
            continue
        v = ctx.index_setting(name, "index.max_result_window")
        try:
            v = int(v)
        except (TypeError, ValueError):
            continue
        if v > 10000:
            rows.append([name, fmt_num(v)])
    if not rows:
        return []
    rows.sort(key=lambda r: -int(str(r[1]).replace(",", "")))
    return [Finding(
        "GEN-001", SPD, Severity.WARNING, T("rules.guidance.r_large_result_sets.01"),
        observed=T("rules.guidance.r_large_result_sets.02") % (len(rows), rows[0][1]),
        impact=T("rules.guidance.r_large_result_sets.03"),
        recommend=T("rules.guidance.r_large_result_sets.04"),
        evidence=table(["index", "max_result_window"], rows[: ctx.t["top_n"]]),
        refs=[D_INDEX_MODULES, D_PAGINATE], source="settings.json")]


def r_large_documents(ctx):
    """Whether http.max_content_length has been raised, and the average document size."""
    out, rows = [], []
    for n in ctx.nodes:
        v = n.setting("http.max_content_length")
        b = parse_bytes(v)
        if b and b > 100 * 1024 ** 2:
            rows.append([n.name, str(v)])
    if rows:
        out.append(Finding(
            "GEN-002", SPD, Severity.WARNING, T("rules.guidance.r_large_documents.01"),
            observed=T("rules.guidance.r_large_documents.02") % len(rows),
            impact=T("rules.guidance.r_large_documents.03"),
            recommend=T("rules.guidance.r_large_documents.04"),
            evidence=table(["node", "http.max_content_length"], rows),
            refs=[D_GEN], source="nodes.json"))
    big = []
    for name, st in ctx.indices_stats.items():
        if ctx.is_system_index(name):
            continue
        docs = num(st, "primaries", "docs", "count")
        size = num(st, "primaries", "store", "size_in_bytes")
        if docs >= 1000 and size:
            avg = size / float(docs)
            if avg >= ctx.t["avg_doc_bytes_warn"]:
                big.append([name, fmt_num(docs), fmt_bytes(size), fmt_bytes(avg), avg])
    if big:
        big.sort(key=lambda r: -r[4])
        out.append(Finding(
            "GEN-003", SPD, Severity.INFO, T("rules.guidance.r_large_documents.05"),
            observed=T("rules.guidance.r_large_documents.06")
                     % (fmt_bytes(ctx.t["avg_doc_bytes_warn"]), len(big), big[0][3]),
            impact=T("rules.guidance.r_large_documents.07"),
            recommend=T("rules.guidance.r_large_documents.08"),
            evidence=table(["index", T("rules.guidance.r_large_documents.09"), T("rules.guidance.r_large_documents.10"), T("rules.guidance.r_large_documents.11")], [r[:4] for r in big[: ctx.t["top_n"]]]),
            refs=[D_GEN], source="indices_stats.json"))
    return out


RULES = [
    r_large_result_sets, r_large_documents,
    r_cluster_name, r_path_settings, r_discovery, r_jvm_diag_settings,
    r_docs_per_shard, r_logsdb_shard_size, r_logsdb_adoption, r_master_heap_per_index, r_mapping_heap_overhead,
    r_empty_indices, r_total_shards_per_node,
    r_index_buffer, r_open_contexts, r_search_timeout, r_replica_throughput,
    r_store_preload, r_remote_storage,
    r_codec, r_source_mode, r_dynamic_mapping,
    r_vector_memory, r_vector_quantization, r_vector_segments,
]
