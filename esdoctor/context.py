"""Normalization layer shared by all rules."""

import collections
import datetime
import re

from .util import dicts, dig, items, parse_bytes, parse_cat_table, num


def _parse_iso(ts):
    if not ts:
        return None
    s = str(ts).replace("Z", "+00:00")
    try:
        return datetime.datetime.fromisoformat(s)
    except (ValueError, AttributeError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.datetime.strptime(str(ts), fmt)
        except ValueError:
            continue
    return None


class NodeView(object):
    """View of one node: info + stats combined."""

    def __init__(self, node_id, info, stats):
        self.id = node_id
        self.info = info if isinstance(info, dict) else {}
        self.stats = stats if isinstance(stats, dict) else {}
        self.name = self.info.get("name") or self.stats.get("name") or node_id
        roles = self.info.get("roles") or self.stats.get("roles") or []
        self.roles = [r for r in roles if isinstance(r, str)] if isinstance(roles, list) else []
        self.version = self.info.get("version")
        self.host = self.info.get("host") or self.stats.get("host")
        self.attrs = _d(self.info.get("attributes"))

    # roles
    @property
    def is_master_eligible(self):
        return "master" in self.roles

    @property
    def is_voting_only(self):
        return "voting_only" in self.roles

    @property
    def is_data(self):
        return any(r == "data" or r.startswith("data_") for r in self.roles)

    @property
    def is_dedicated_master(self):
        return self.is_master_eligible and not self.is_data

    @property
    def is_ml(self):
        return "ml" in self.roles

    # JVM
    @property
    def heap_max(self):
        return num(self.stats, "jvm", "mem", "heap_max_in_bytes", default=None) or num(self.info, "jvm", "mem", "heap_max_in_bytes", default=None)

    @property
    def heap_used(self):
        return num(self.stats, "jvm", "mem", "heap_used_in_bytes", default=None)

    @property
    def heap_used_pct(self):
        return num(self.stats, "jvm", "mem", "heap_used_percent", default=None)

    @property
    def memory_pressure_pct(self):
        """JVM memory pressure as Elastic defines it: old generation pool used / max (nodes stats jvm.mem.pools.old).
        Heap% at one moment also counts young generation garbage that the next young GC frees. Falls back to heap% when the
        old pool is not reported."""
        used = num(self.stats, "jvm", "mem", "pools", "old", "used_in_bytes", default=None)
        mx = num(self.stats, "jvm", "mem", "pools", "old", "max_in_bytes", default=None)
        if used is not None and mx and mx > 0:
            return used * 100.0 / mx
        return self.heap_used_pct

    @property
    def heap_init(self):
        return num(self.info, "jvm", "mem", "heap_init_in_bytes", default=None)

    @property
    def uptime_ms(self):
        return num(self.stats, "jvm", "uptime_in_millis", default=None)

    def gc(self, kind):
        """kind: 'young' | 'old' -> (count, time_ms)"""
        cols = dig(self.stats, "jvm", "gc", "collectors", default={})
        cols = cols if isinstance(cols, dict) else {}
        if kind in cols:
            c = cols[kind]
        else:
            # some versions use the raw name such as 'G1 Young Generation'
            c = None
            for k, v in cols.items():
                kl = k.lower()
                if kind == "old" and ("old" in kl or "tenured" in kl or "marksweep" in kl):
                    c = v
                    break
                if kind == "young" and ("young" in kl or "scavenge" in kl or "eden" in kl):
                    c = v
                    break
        if not c:
            return (0, 0)
        if not isinstance(c, dict):
            return (0, 0)
        return (num(c, "collection_count"), num(c, "collection_time_in_millis"))

    # OS / FS
    @property
    def cpu_pct(self):
        return num(self.stats, "os", "cpu", "percent", default=None)

    @property
    def processors(self):
        return num(self.stats, "os", "cpu", "available_processors", default=None) or num(self.info, "os", "available_processors", default=None)

    @property
    def load1(self):
        return num(self.stats, "os", "cpu", "load_average", "1m", default=None)

    @property
    def load5(self):
        return num(self.stats, "os", "cpu", "load_average", "5m", default=None)

    @property
    def load15(self):
        return num(self.stats, "os", "cpu", "load_average", "15m", default=None)

    @property
    def ram_total(self):
        return num(self.stats, "os", "mem", "adjusted_total_in_bytes", default=None) or num(self.stats, "os", "mem", "total_in_bytes", default=None)

    @property
    def swap_total(self):
        return num(self.stats, "os", "swap", "total_in_bytes", default=None)

    @property
    def fs_total(self):
        return num(self.stats, "fs", "total", "total_in_bytes", default=None)

    @property
    def fs_avail(self):
        v = num(self.stats, "fs", "total", "available_in_bytes", default=None)
        if v is None:
            v = num(self.stats, "fs", "total", "free_in_bytes", default=None)
        return v

    def _most_path(self):
        """(total, available) of the data path with the most available bytes: ES checks the low watermark (allocation of new
        shards) on that path (DiskThresholdDecider, most-available disk usage)."""
        paths = []
        for p in (dig(self.stats, "fs", "data") or []):
            if isinstance(p, dict):
                t = num(p, "total_in_bytes", default=None)
                a = num(p, "available_in_bytes", default=None)
                if a is None:
                    a = num(p, "free_in_bytes", default=None)
                if t and a is not None:
                    paths.append((a, t))
        if len(paths) >= 2:
            a, t = max(paths)
            return t, a
        return self.fs_total, self.fs_avail

    def _least_path(self):
        """(total, available) of the data path with the least available bytes, as ES judges disk thresholds
        (ClusterInfo least-available disk usage); fs.total when the node has a single path or no per-path data."""
        paths = []
        for p in (dig(self.stats, "fs", "data") or []):
            if not isinstance(p, dict):
                continue
            t = num(p, "total_in_bytes", default=None)
            a = num(p, "available_in_bytes", default=None)
            if a is None:
                a = num(p, "free_in_bytes", default=None)
            if t and a is not None:
                paths.append((a, t))
        if len(paths) >= 2:
            a, t = min(paths)
            return t, a
        return self.fs_total, self.fs_avail

    @property
    def disk_path_total(self):
        """Total bytes of the path ES uses for the disk watermarks (see _least_path)."""
        return self._least_path()[0]

    @property
    def disk_used_pct(self):
        t, a = self._least_path()
        if not t or a is None:
            return None
        return (1.0 - float(a) / float(t)) * 100.0

    @property
    def open_fd(self):
        return num(self.stats, "process", "open_file_descriptors", default=None)

    @property
    def max_fd(self):
        return num(self.stats, "process", "max_file_descriptors", default=None)

    @property
    def mlockall(self):
        v = dig(self.info, "process", "mlockall")
        if v is None:
            v = dig(self.stats, "process", "mlockall")
        return v

    def jvm_args(self):
        return dig(self.info, "jvm", "input_arguments", default=[]) or []

    def setting(self, dotted, default=None):
        """settings in nodes.json mix flat and nested keys; support both."""
        v = _flat_get(self.info.get("settings") or {}, dotted)
        return default if v is None else v


class Context(object):
    def __init__(self, bundle, thresholds):
        self.b = bundle
        self.t = thresholds
        self._build()

    #     # ---------------- loading ----------------
    def _build(self):
        b = self.b
        self._stat_cache = {}

        def sj(name):
            if name not in self._stat_cache:
                self._stat_cache[name] = _coerce(b.json(name))
            return self._stat_cache[name]
        self.manifest = b.json("manifest.json") or _d(b.json("diagnostic_manifest.json"))
        self.version_doc = _d(b.json("version.json"))
        self.health = _d(sj("cluster_health.json"))
        self.internal_health = _d(b.json("internal_health.json"))
        self.cluster_stats = _d(sj("cluster_stats.json"))
        self.cluster_settings = _d(b.json("cluster_settings.json"))
        self.cluster_settings_defaults = _d(b.json("cluster_settings_defaults.json"))
        self.pending_tasks = _d(sj("cluster_pending_tasks.json"))
        self.license = _d(_d(b.json("licenses.json")).get("license"))
        self.index_settings = _d(b.json("settings.json"))
        self.indices_stats = _d(_d(sj("indices_stats.json")).get("indices"))
        self.indices_stats_all = _d(_d(sj("indices_stats.json")).get("_all"))
        self.recovery = _d(sj("recovery.json"))
        self.tasks = _d(sj("tasks.json"))
        self.allocation_explain = _d(b.json("allocation_explain.json"))
        self.snapshots = _d(b.json("snapshot.json"))
        # GET _snapshot returns {repo name: {type, settings}}; older tooling or tests may give a list
        repos = b.json("repositories.json")
        if isinstance(repos, dict) and "error" not in repos:
            self.repositories = [dict(v, name=k) if isinstance(v, dict) else {"name": k} for k, v in repos.items()]
        else:
            self.repositories = _l(repos)
        self.ssl_certs = _l(b.json("ssl_certs.json"))
        self.dangling = _d(b.json("dangling_indices.json"))
        self.data_streams = _l(_d(b.json("commercial/data_stream.json")).get("data_streams"))
        self.ilm_explain = _d(_d(b.json("commercial/ilm_explain.json")).get("indices"))
        self.ilm_status = _d(b.json("commercial/ilm_status.json"))
        self.slm_stats = _d(b.json("commercial/slm_stats.json"))
        self.slm_policies = _d(b.json("commercial/slm_policies.json"))
        self.slm_status = _d(b.json("commercial/slm_status.json"))
        self.transform_stats = _d(b.json("commercial/transform_stats.json"))
        self.ml_anomaly = _d(b.json("commercial/ml_anomaly_detectors.json"))
        self.ml_job_stats = _d(b.json("commercial/ml_stats.json"))        # job state lives in _ml/anomaly_detectors/_stats
        self.ml_datafeed_stats = _d(b.json("commercial/ml_datafeeds_stats.json"))
        self.ml_memory = _d(b.json("commercial/ml_memory_stats.json"))
        self.xpack = _d(b.json("commercial/xpack.json"))
        self.ccr_stats = _d(b.json("commercial/ccr_stats.json"))
        self.watcher_stats = _d(b.json("commercial/watcher_stats.json"))
        self.geoip = _d(b.json("geoip_stats.json"))
        self.hot_threads_text = b.text("nodes_hot_threads.txt") or ""
        self.fielddata_cat = _l(b.json("fielddata.json"))
        self.pipelines = _d(b.json("pipelines.json"))
        self.aliases = _d(b.json("alias.json"))
        from .mapsum import summarize
        self.mapping_summary = summarize(b.iter_object("mapping.json"))
        self.ilm_policies = _d(b.json("commercial/ilm_policies.json"))
        # cluster_state is large (can be hundreds of MB), so only the piece the findings use (voting config exclusions) is cut out and parsed
        _vx = b.extract_array("cluster_state.json", "cluster_coordination", "voting_config_exclusions")
        self.cluster_state = {"metadata": {"cluster_coordination": {
            "voting_config_exclusions": _vx if isinstance(_vx, list) else []}}}
        self.shutdown_status = _d(b.json("commercial/nodes_shutdown_status.json"))
        self.shard_stores = _d(b.json("shard_stores.json"))
        self.remote_clusters = _d(b.json("remote_cluster_info.json"))
        self.frozen_cache = _d(b.json("commercial/searchable_snapshots_cache_stats.json"))
        self.ml_trained_stats = _d(b.json("commercial/ml_trained_models_stats.json"))
        self.watcher_stack = _d(b.json("commercial/watcher_stack.json"))
        self.autoscaling = _d(b.json("commercial/autoscaling_capacity.json"))
        self.rollup_jobs = _d(b.json("commercial/rollup_jobs.json"))
        self.index_templates = _d(b.json("index_templates.json"))
        self.component_templates = _d(b.json("component_templates.json"))
        self.legacy_templates = _d(b.json("templates.json"))

        # shard list: indices.json (extended cat/shards) first, else shards.json
        shards = b.json("indices.json")
        if not isinstance(shards, list) or not shards:
            shards = b.json("shards.json")
        if not isinstance(shards, list):
            shards = parse_cat_table(b.text("cat/cat_shards.txt"))
        # shard rows: index is a string, and the other text fields are normalized to strings too (malformed rows are dropped)
        clean = []
        for x in (shards or []):
            if not isinstance(x, dict) or not isinstance(x.get("index"), str):
                continue
            for k in ("prirep", "state", "node", "ur", "ud"):
                if x.get(k) is not None and not isinstance(x.get(k), str):
                    x = dict(x)
                    x[k] = str(x[k])
            if " -> " in (x.get("node") or ""):
                # RELOCATING rows read "source -> ip id target"; the shard still lives on the source node
                x = dict(x)
                x["node"] = x["node"].split(" -> ")[0].strip()
            clean.append(x)
        self.shards = clean
        # count shards per index once (avoids an index x shard loop, needed for large clusters)
        self._shards_by_index = collections.Counter()
        self._primaries_by_index = collections.Counter()
        for sh in self.shards:
            idx = sh.get("index")
            self._shards_by_index[idx] += 1
            if (sh.get("prirep") or "").lower() == "p":
                self._primaries_by_index[idx] += 1

        self.cat_indices = parse_cat_table(b.text("cat/cat_indices.txt"))
        self.cat_nodes = parse_cat_table(b.text("cat/cat_nodes.txt"))
        self.cat_allocation = _l(b.json("allocation.json")) or parse_cat_table(
            b.text("cat/cat_allocation.txt"))
        self.cat_thread_pool = parse_cat_table(b.text("cat/cat_thread_pool.txt"))

        # node views
        info = _d(_d(b.json("nodes.json")).get("nodes"))
        stats = _d(_d(sj("nodes_stats.json")).get("nodes"))
        ids = set(info.keys()) | set(stats.keys())
        self.nodes = [NodeView(i, _d(info.get(i)), _d(stats.get(i))) for i in sorted(ids)]
        self.nodes_by_name = dict((n.name, n) for n in self.nodes)

        self.collection_time = _parse_iso(
            self.manifest.get("collectionDate") or self.manifest.get("timestamp"))

        self.diag_type = "unknown"
        flags = str(self.manifest.get("diagnosticInputs") or self.manifest.get("flags") or "")
        m = re.search(r"diagType='([^']+)'", flags)
        if m:
            self.diag_type = m.group(1)
        self.has_logs = bool(b.log_files())
        self.deployment = self._detect_deployment()

    def _detect_deployment(self):
        """Tells ECH/ECE/ECK/self-managed apart. Settings managed by the orchestrator cannot be changed by the customer."""
        runner = str(self.manifest.get("runner") or "").lower()
        if runner in ("ess", "ech"):
            return "ECH"
        if runner == "ece":
            return "ECE"
        for n in self.nodes:
            attrs = n.attrs or {}
            if attrs.get("instance_configuration") or attrs.get("logical_availability_zone"):
                return "ECH/ECE"
            # generic settings such as node.store.allow_mmap are also used on self-managed, so they are not used to detect the platform
            if attrs.get("k8s_node_name"):
                return "ECK"
        return "self-managed"

    @property
    def orchestrated(self):
        return self.deployment != "self-managed"

    @property
    def platform_managed(self):
        """ECH / ECE, where the platform writes elasticsearch.yml and sets the instance resources. On ECK the user sets both in the
        Elasticsearch resource, so it is orchestrated but not platform managed."""
        return self.deployment in ("ECH", "ECE", "ECH/ECE")

    def load_high(self, node):
        """load15 per CPU >= load_per_cpu_warn, except in a container with low CPU use, where the load can be the host's (as in OS-001)."""
        per = (node.load15 / node.processors) if (node.load15 and node.processors) else None
        if per is None or per < self.t["load_per_cpu_warn"]:
            return False
        return not (self.in_container(node) and node.cpu_pct is not None and node.cpu_pct < self.t["load_host_cpu_pct_max"])

    def in_container(self, node):
        """Whether the node runs under a CPU or memory limit (container), where the load average can be the host's.

        os.cgroup alone is not enough: ES reports cgroup stats on any Linux host with cgroups (a systemd service on bare metal too).
        A container is assumed on Elastic Cloud / ECE / ECK, or when the cgroup has a CPU quota (cfs_quota_micros > 0) or a memory limit.
        """
        if self.orchestrated:
            return True
        cg = dig(node.stats, "os", "cgroup") or {}
        if not isinstance(cg, dict) or not cg:
            return False
        try:
            if int(dig(cg, "cpu", "cfs_quota_micros") or -1) > 0:
                return True
        except (TypeError, ValueError):
            pass
        lim = str(dig(cg, "memory", "limit_in_bytes") or "").strip().lower()
        return lim.isdigit() and int(lim) < (1 << 60)

    #     # ---------------- convenience accessors ----------------
    def shard_count(self, index):
        return self._shards_by_index.get(index, 0)

    def primary_count(self, index):
        return self._primaries_by_index.get(index, 0)

    @property
    def cluster_name(self):
        return self.health.get("cluster_name") or self.version_doc.get("cluster_name") or "-"

    @property
    def version(self):
        v = dig(self.version_doc, "version", "number")
        if not v:
            v = dig(self.manifest, "Product Version", "version")
        return v or "-"

    @property
    def version_tuple(self):
        try:
            parts = re.split(r"[.\-]", str(self.version))
            return tuple(int(p) for p in parts[:3])
        except (ValueError, TypeError):
            return (0, 0, 0)

    def setting(self, key, default=None):
        """Looks up a cluster setting in the order transient -> persistent -> defaults (transient overrides persistent in ES)."""
        for scope in ("transient", "persistent"):
            d = self.cluster_settings.get(scope) or {}
            v = _flat_get(d, key)
            if v is not None:
                return v
        v = _flat_get(self.cluster_settings_defaults.get("defaults") or
                      self.cluster_settings_defaults, key)
        return v if v is not None else default

    def setting_source(self, key):
        for scope in ("transient", "persistent"):
            if _flat_get(self.cluster_settings.get(scope) or {}, key) is not None:
                return scope
        return "default"

    @property
    def data_nodes(self):
        return [n for n in self.nodes if n.is_data]

    @property
    def master_nodes(self):
        return [n for n in self.nodes if n.is_master_eligible]

    def time_based(self, index):
        """Whether ES uses the time-based merge policy (LogByteSizeMergePolicy, from 8.8) for the index.

        ES decides per shard from the @timestamp date field in the mapping (MappingLookup in the source): indexed and with doc values
        (8.8 to 9.0); with doc values and either indexed or a doc values skipper (9.1, 9.2); indexed or a doc values skipper (9.3+,
        getTimestampFieldType). The skipper is assumed for the logsdb, time_series and columnar modes. index.merge.policy.type
        overrides it. Without the mapping in the bundle, data stream membership is used (data streams always map @timestamp).
        """
        if not self.version_tuple or self.version_tuple < (8, 8, 0):
            return False
        typ = str(self.index_setting(index, "index.merge.policy.type") or "").lower()
        if typ in ("tiered", "time_based"):
            return typ == "time_based"
        summ = (getattr(self, "mapping_summary", None) or {}).get(index)
        if isinstance(summ, dict) and "timestamp" in summ:
            if not summ.get("timestamp"):
                return False
            idx, dv = summ.get("ts_index", True), summ.get("ts_dv", True)
            skip = dv and self.index_mode(index) in ("logsdb", "time_series", "logsdb_columnar", "columnar")
            if self.version_tuple >= (9, 3, 0):
                return bool(idx or skip)
            if self.version_tuple >= (9, 1, 0):
                return bool(dv and (idx or skip))
            return bool(idx and dv)
        return bool(self.data_stream_of(index))

    def index_setting(self, index, key, default=None):
        d = dig(self.index_settings, index, "settings") or {}
        v = _flat_get(d, key)
        if v is None:
            d2 = dig(self.index_settings, index, "defaults") or {}
            v = _flat_get(d2, key)
        return v if v is not None else default

    def is_system_index(self, name):
        """Whether the index is a system (product-internal) index.

        An index starting with '.' is still user data if it is a data stream backing index (.ds-<data stream>-...).
        A backing index counts as system when the data stream name starts with '.' (e.g. .ds-.kibana-event-log), or when the data stream
        is one Elasticsearch manages for itself (hidden and _meta.managed without a Fleet package, e.g. ilm-history-7).
        Searchable snapshot mount names (restored-/partial-) are judged by the original name.
        """
        if not name:
            return False
        n = name
        for prefix in ("partial-restored-", "restored-", "partial-"):
            if n.startswith(prefix):
                n = n[len(prefix):]
                break
        if n.startswith((".ds-", ".fs-")):        # data stream backing and failure store indices
            if n[4:].startswith("."):
                return True
            return self.es_managed_stream(self.stream_of(name) or self.stream_of(n))
        return n.startswith(".")

    def is_searchable_snapshot(self, name):
        """Whether the index is a searchable snapshot mount (by setting, else guessed from the name prefix).

        The snapshot is the source of truth, so actions like shrink, force-merge and settings changes are not possible (excluded from actionable findings).
        Only partial mounts have a size that differs from the original (see is_partial_mount).
        """
        if self.index_setting(name, "index.store.snapshot.snapshot_name") or \
                self.index_setting(name, "index.store.snapshot.repository_name") or \
                str(self.index_setting(name, "index.store.type") or "") == "snapshot":
            return True
        # The name is only a guess for indices without settings: a normal restore can also be renamed restored-*.
        return bool(name) and name not in self.index_settings and name.startswith(("restored-", "partial-"))

    def is_partial_mount(self, name):
        """Whether the index is partially mounted (frozen). The store size is the local cache size, not the original shard size.

        Fully mounted (restored-, cold) indices copy whole shards locally, so the store size is the real size and is included in size findings.
        """
        if str(self.index_setting(name, "index.store.snapshot.partial") or "").lower() == "true":
            return True
        return bool(name) and name not in self.index_settings and name.startswith("partial-")

    def _alias_members(self):
        """{alias: [(index, is_write_index flag as bool or None)]}, built once."""
        if getattr(self, "_alias_map", None) is None:
            by_alias = {}
            for idx, body in items(self.aliases or {}):
                al = (body or {}).get("aliases") if isinstance(body, dict) else None
                for alias, meta in items(al or {}):
                    w = (meta or {}).get("is_write_index") if isinstance(meta, dict) else None
                    flag = None if w is None else str(w).lower() == "true"
                    by_alias.setdefault(alias, []).append((idx, flag))
            self._alias_map = by_alias
        return self._alias_map

    def explicit_write_targets(self):
        """Indices that are being filled for sure: data stream write indices (and failure store write indices), alias members flagged
        is_write_index=true, and the only member of an alias without the flag when that index names the alias as its ILM rollover
        alias (a legacy rollover alias without is_write_index moves to the new index at each rollover). Any other plain alias over one
        index is left out: it is as often a read alias (products -> products-v3) as a write one."""
        if getattr(self, "_explicit_wt", None) is not None:
            return self._explicit_wt
        out = set()
        for ds in dicts(self.data_streams):
            for idxs in (dicts(ds.get("indices")), dicts((ds.get("failure_store") or {}).get("indices"))):
                if idxs:
                    out.add(idxs[-1].get("index_name"))
        for alias, members in self._alias_members().items():
            out.update(i for i, w in members if w is True)
            if len(members) == 1 and members[0][1] is None:
                i = members[0][0]
                if str(self.index_setting(i, "index.lifecycle.rollover_alias") or "") == alias and \
                        str(self.index_setting(i, "index.lifecycle.indexing_complete") or "").lower() != "true":
                    out.add(i)
        out.discard(None)
        self._explicit_wt = out
        return out

    def write_targets(self):
        """Indices that can take writes: explicit_write_targets plus the only member of an alias without an is_write_index flag
        (ES writes through such an alias), unless that member is a searchable snapshot mount, which cannot take writes."""
        if getattr(self, "_write_targets", None) is not None:
            return self._write_targets
        out = set(self.explicit_write_targets())
        for members in self._alias_members().values():
            if len(members) == 1 and members[0][1] is None and not self.is_searchable_snapshot(members[0][0]):
                out.add(members[0][0])
        self._write_targets = out
        return out

    def data_stream_of(self, name):
        """Data stream dict that has this backing index, or None."""
        if getattr(self, "_ds_of", None) is None:
            self._ds_of = {}
            for ds in dicts(self.data_streams):
                for i in dicts(ds.get("indices")):
                    if i.get("index_name"):
                        self._ds_of[i["index_name"]] = ds
        return self._ds_of.get(name)

    def stream_of(self, name):
        """Data stream dict that holds this index as a backing index or as a failure store index, or None."""
        ds = self.data_stream_of(name)
        if ds is not None:
            return ds
        if getattr(self, "_fs_of", None) is None:
            self._fs_of = {}
            for d in dicts(self.data_streams):
                for i in dicts((d.get("failure_store") or {}).get("indices")):
                    if i.get("index_name"):
                        self._fs_of[i["index_name"]] = d
        return self._fs_of.get(name)

    @staticmethod
    def es_managed_stream(ds):
        """A data stream that Elasticsearch creates and manages for itself (ilm-history-*, for example): hidden, and its template
        metadata says managed without a Fleet package. Users cannot tune it."""
        if not isinstance(ds, dict) or str(ds.get("hidden")).lower() != "true":
            return False
        meta = ds.get("_meta") if isinstance(ds.get("_meta"), dict) else {}
        return str(meta.get("managed")).lower() == "true" and not meta.get("package") and meta.get("managed_by") != "fleet"

    def index_mode(self, name):
        """index.mode of an index: standard, logsdb, time_series, lookup ...

        Read from settings.json first. GET _data_stream also reports index_mode per backing index and per
        data stream (8.15+), which covers bundles where the setting is not in settings.json.
        Returns "standard" when nothing says otherwise.
        """
        v = self.index_setting(name, "index.mode")
        if not v:
            ds = self.data_stream_of(name)
            if ds:
                for i in dicts(ds.get("indices")):
                    if i.get("index_name") == name and i.get("index_mode"):
                        v = i.get("index_mode")
                        break
                v = v or ds.get("index_mode")
        return str(v or "standard").lower()

    def ilm_policy_of(self, name):
        """ILM policy name managing the index, or None: from ILM explain when the index is there, else index.lifecycle.name, else
        the ilm_policy of its data stream backing entry when that entry says ILM manages it."""
        ex = (self.ilm_explain or {}).get(name)
        if isinstance(ex, dict):
            # managed=false with a policy name means data stream lifecycle wins (prefer_ilm false): ILM does not run it
            return ex.get("policy") if ex.get("managed") else None
        pol = self.index_setting(name, "index.lifecycle.name")
        if pol:
            return pol
        for ds in dicts(self.data_streams):
            for i in dicts(ds.get("indices")):
                if i.get("index_name") == name:
                    return i.get("ilm_policy") if "index lifecycle" in str(i.get("managed_by") or "").lower() else None
        return None

    def dlm_managed(self, name):
        """Whether a backing index is managed by data stream lifecycle (not ILM): the backing index entry says so (8.11+), or the
        data stream has an enabled lifecycle and no ILM policy. Failure store indices (.fs-) are managed by data stream lifecycle
        (their entry under failure_store says so)."""
        if name.startswith(".fs-"):
            for ds in dicts(self.data_streams):
                for i in dicts((ds.get("failure_store") or {}).get("indices")):
                    if i.get("index_name") == name:
                        return "ilm" not in str(i.get("managed_by") or "").lower() \
                            and "index lifecycle" not in str(i.get("managed_by") or "").lower()
        ds = self.data_stream_of(name)
        if not isinstance(ds, dict):
            return False
        for i in dicts(ds.get("indices")):
            if i.get("index_name") == name and i.get("managed_by"):
                return "lifecycle" in str(i.get("managed_by")).lower() and "ilm" not in str(i.get("managed_by")).lower() \
                    and "index lifecycle" not in str(i.get("managed_by")).lower()
        lc = ds.get("lifecycle")
        return isinstance(lc, dict) and str(lc.get("enabled", True)).lower() != "false" and not ds.get("ilm_policy")

    def rollover_conditions(self, policy):
        """Rollover action of the hot phase of an ILM policy as a dict ({} when there is none)."""
        ro = dig(self.ilm_policies, policy, "policy", "phases", "hot", "actions", "rollover") if policy else None
        return ro if isinstance(ro, dict) else {}

    def rolled_over(self, name):
        """Whether the index is rolled over (no longer written): past backing index of a data stream, indexing_complete, or a member
        of an alias whose write index is another index. A plain read alias over several indices does not make them rolled over."""
        if name in self.write_targets():
            return False
        if str(self.index_setting(name, "index.lifecycle.indexing_complete") or "").lower() == "true":
            return True
        for ds in dicts(self.data_streams):
            for idxs in (dicts(ds.get("indices")), dicts((ds.get("failure_store") or {}).get("indices"))):
                if any(i.get("index_name") == name for i in idxs[:-1]):
                    return True
        if getattr(self, "_rolled_by_alias", None) is None:
            rolled = set()
            for members in self._alias_members().values():
                writers = set(i for i, w in members if w is True)
                if writers:
                    rolled.update(i for i, _w in members if i not in writers)
            self._rolled_by_alias = rolled
        return name in self._rolled_by_alias

    def tier_of(self, node):
        """Tier label of a data node. The role combination is the comparison unit (specs and load are compared only within the same tier)."""
        r = set(node.roles)
        if "data" in r:
            return "data(generic)"
        tiers = [t for t in ("data_hot", "data_content", "data_warm", "data_cold", "data_frozen") if t in r]
        if not tiers:
            return None
        if tiers == ["data_frozen"]:
            return "frozen"
        if "data_hot" in tiers:
            return "hot"
        if tiers == ["data_content"]:
            return "content"
        return "+".join(t.replace("data_", "") for t in tiers)

    def data_tiers(self):
        """tier label -> list of data nodes."""
        out = collections.OrderedDict()
        for n in self.data_nodes:
            t = self.tier_of(n)
            if t:
                out.setdefault(t, []).append(n)
        return out

    def is_frozen_only(self, node):
        return self.tier_of(node) == "frozen"

    def frozen_disk_only_alarm(self):
        """True when a dedicated frozen node is over flood_stage.frozen and no other data node is at or above its high watermark.
        Frozen nodes only cache data that lives in the snapshot repository, so a full disk there is expected."""
        frozen_over, other_over = False, False
        for n in self.data_nodes or self.nodes:
            total, _avail = n._least_path()
            up = n.disk_used_pct
            if up is None or not total:
                continue
            if self.tier_of(n) == "frozen":
                fl = self.watermark_used_pct("flood_stage.frozen", total)
                if fl and up >= fl:
                    frozen_over = True
            else:
                hi = self.watermark_used_pct("high", total)
                if hi and up >= hi:
                    other_over = True
        return frozen_over and not other_over

    def dev_mode(self, node):
        """True when the node runs in development mode: its transport publish address and every bound address are loopback,
        or discovery.type is single-node (BootstrapChecks.enforceLimits). -Des.enforce.bootstrap.checks=true forces production
        mode. Bootstrap checks are enforced only in production mode (official)."""
        if any(str(a).startswith("-Des.enforce.bootstrap.checks=true") for a in (node.jvm_args() or [])):
            return False
        if str(node.setting("discovery.type") or "") == "single-node":
            return True

        def loop(a):
            a = str(a or "")
            return a.startswith("127.") or a.startswith("[::1]") or a.startswith("localhost")
        ta = node.info.get("transport_address")
        if not loop(ta):
            return False
        bound = dig(node.info, "transport", "bound_address")
        return all(loop(b) for b in bound) if isinstance(bound, list) and bound else True

    def recently_restarted(self, node):
        """True when the node has been up for less than node_compare_min_uptime_hours.

        Such a node has cold caches and cumulative counters that cover a short window, so it is left out
        when nodes are compared with each other. Unknown uptime counts as settled.
        """
        up = node.uptime_ms
        return bool(up) and up < self.t["node_compare_min_uptime_hours"] * 3600000

    def explicitly_set(self, key):
        """True when the setting is set in cluster settings or in the elasticsearch.yml of any node (not just a default)."""
        if self.setting_source(key) != "default":
            return True
        # nested yml settings: a dict here is a child key (for example ...flood_stage.frozen), not this setting
        return any(n.setting(key) is not None and not isinstance(n.setting(key), dict) for n in self.nodes)

    def watermark(self, kind):
        """kind: low|high|flood_stage|flood_stage.frozen -> raw string"""
        key = "cluster.routing.allocation.disk.watermark." + kind
        v = self.setting(key)
        if v is None:
            v = self.t.get({"low": "disk_watermark_low_default", "high": "disk_watermark_high_default",
                            "flood_stage": "disk_watermark_flood_default",
                            "flood_stage.frozen": "disk_watermark_flood_frozen_default"}.get(kind, ""))
        return v

    def watermark_used_pct(self, kind, node_total_bytes):
        """Converts a watermark to 'used %' for the given node.

        Follows the ES 8.5+ formula as is:
          - Percentage watermark: required free space = total x (1 - ratio)
          - If max_headroom is set: required free space = min(value above, max_headroom)
            (defaults: low 200GB / high 150GB / flood_stage 100GB, applied only when the watermark is not set explicitly)
          - Byte watermark: required free space = the given value (max_headroom does not apply)
        On large disks max_headroom makes the effective threshold much higher than 90% used.
        """
        raw = self.watermark(kind)
        if raw is None or not node_total_bytes:
            return None
        s = str(raw).strip()
        total = float(node_total_bytes)
        if s.endswith("%") or re.match(r"^0?\.\d+$", s):
            try:
                ratio = float(s[:-1]) / 100.0 if s.endswith("%") else float(s)
            except ValueError:
                return None
            need_free = total * (1.0 - ratio)
            hkey = "cluster.routing.allocation.disk.watermark.%s.max_headroom" % kind
            wkey = "cluster.routing.allocation.disk.watermark." + kind
            head = self.setting(hkey)
            yml_head = [n.setting(hkey) for n in self.nodes if n.setting(hkey) is not None]
            if self.setting_source(hkey) == "default" and yml_head:
                head = yml_head[0]          # max_headroom set in elasticsearch.yml
            elif self.setting_source(hkey) == "default":
                # The default headroom (200/150/100GB, 20GB for frozen flood stage) applies only while the watermark itself is
                # not set explicitly, in cluster settings or in elasticsearch.yml (official). The non-frozen ones exist from 8.5.
                # The defaults section of the bundle shows the default headroom even when yml sets the watermark, so it is not trusted then.
                old = kind != "flood_stage.frozen" and (0, 0, 0) < self.version_tuple < (8, 5, 0)
                if old or self.explicitly_set(wkey):
                    head = None
                elif head is None and kind == "flood_stage.frozen":
                    head = self.t.get("disk_watermark_flood_frozen_headroom_default")
            head_b = parse_bytes(head) if head not in (None, "-1", -1) else None
            if head_b is not None and head_b >= 0:
                need_free = min(need_free, float(head_b))
            return (1.0 - need_free / total) * 100.0
        free_bytes = parse_bytes(s)
        if free_bytes is None:
            return None
        return (1.0 - float(free_bytes) / total) * 100.0


_NUMERIC = re.compile(r"^-?\d+(\.\d+)?$")
# Stats-type files: numeric fields are treated as numbers even if they arrive as strings (config files keep the original)
_STAT_FILES = ("nodes_stats.json", "indices_stats.json", "cluster_health.json", "cluster_stats.json",
               "recovery.json", "tasks.json", "cluster_pending_tasks.json")


def _num_str(x):
    try:
        f = float(x)
        return int(f) if f.is_integer() and "." not in x else f
    except ValueError:
        return x


def _coerce(x):
    """Converts numeric strings to numbers in place, so no copy of a large stats file is made."""
    stack = [x]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if isinstance(v, (dict, list)):
                    stack.append(v)
                elif isinstance(v, str) and _NUMERIC.match(v):
                    cur[k] = _num_str(v)
        elif isinstance(cur, list):
            for i, v in enumerate(cur):
                if isinstance(v, (dict, list)):
                    stack.append(v)
                elif isinstance(v, str) and _NUMERIC.match(v):
                    cur[i] = _num_str(v)
    return x


def _d(x):
    """Empty dict if not a dict. Keeps the analysis going when the bundle file format differs by version or collection mode."""
    return x if isinstance(x, dict) else {}


def _l(x):
    return x if isinstance(x, list) else []


def _flat_get(d, dotted):
    """Supports flat keys ('a.b.c'), nested dicts, and a mix of both. ES renders a key that is both a value and a prefix
    (watermark.low and watermark.low.max_headroom) as a dotted key inside the parent map (Settings, "." notation fallback),
    so at every level the remaining path is also tried as one dotted key."""
    if not isinstance(d, dict):
        return None
    parts = dotted.split(".")

    def walk(cur, i):
        for j in range(len(parts), i, -1):
            key = ".".join(parts[i:j])
            if key in cur:
                if j == len(parts):
                    return cur[key]
                if isinstance(cur[key], dict):
                    v = walk(cur[key], j)
                    if v is not None:
                        return v
        return None
    return walk(d, 0)
