"""룰이 공통으로 사용하는 정규화 계층."""

import collections
import datetime
import re

from .util import dig, parse_bytes, parse_cat_table, num


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
    """노드 1대의 info + stats 를 묶은 뷰."""

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

    # 역할
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
            # 일부 버전은 'G1 Young Generation' 등 원 이름을 쓴다
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

    @property
    def disk_used_pct(self):
        t, a = self.fs_total, self.fs_avail
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
        """nodes.json 의 settings 는 평탄/중첩이 섞여 있어 둘 다 지원."""
        s = self.info.get("settings") or {}
        if dotted in s:
            return s[dotted]
        cur = s
        for part in dotted.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur


class Context(object):
    def __init__(self, bundle, thresholds):
        self.b = bundle
        self.t = thresholds
        self._build()

    # ---------------- 로딩 ----------------
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
        self.repositories = _l(b.json("repositories.json"))
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
        # cluster_state 는 대형(수백 MB 가능)이라 판정에 쓰는 조각(voting config exclusions)만 잘라 파싱한다
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

        # 샤드 목록: indices.json(확장 cat/shards) 우선, 없으면 shards.json
        shards = b.json("indices.json")
        if not isinstance(shards, list) or not shards:
            shards = b.json("shards.json")
        if not isinstance(shards, list):
            shards = parse_cat_table(b.text("cat/cat_shards.txt"))
        # 샤드 행: index 는 문자열, 나머지 문자 필드도 문자열로 정규화(형식이 다른 행은 버린다)
        clean = []
        for x in (shards or []):
            if not isinstance(x, dict) or not isinstance(x.get("index"), str):
                continue
            for k in ("prirep", "state", "node", "ur", "ud"):
                if x.get(k) is not None and not isinstance(x.get(k), str):
                    x = dict(x)
                    x[k] = str(x[k])
            clean.append(x)
        self.shards = clean
        # 인덱스별 샤드 수를 한 번만 집계한다(인덱스 x 샤드 반복 방지 — 대형 클러스터 대응)
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

        # 노드 뷰
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
        """ECH/ECE/ECK/self-managed 구분. 오케스트레이터가 관리하는 설정은 고객이 직접 바꿀 수 없다."""
        runner = str(self.manifest.get("runner") or "").lower()
        if runner in ("ess", "ech"):
            return "ECH"
        if runner == "ece":
            return "ECE"
        for n in self.nodes:
            attrs = n.attrs or {}
            if attrs.get("instance_configuration") or attrs.get("logical_availability_zone"):
                return "ECH/ECE"
            if attrs.get("k8s_node_name") or n.setting("node.store.allow_mmap") is not None:
                return "ECK"
        for n in self.nodes:
            if n.setting("cloud.node.name") or n.setting("xpack.ml.enabled") == "false":
                pass
        return "self-managed"

    @property
    def orchestrated(self):
        return self.deployment != "self-managed"

    # ---------------- 편의 접근 ----------------
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
        """persistent -> transient -> defaults 순서로 클러스터 설정 조회."""
        for scope in ("persistent", "transient"):
            d = self.cluster_settings.get(scope) or {}
            v = _flat_get(d, key)
            if v is not None:
                return v
        v = _flat_get(self.cluster_settings_defaults.get("defaults") or
                      self.cluster_settings_defaults, key)
        return v if v is not None else default

    def setting_source(self, key):
        for scope in ("persistent", "transient"):
            if _flat_get(self.cluster_settings.get(scope) or {}, key) is not None:
                return scope
        return "default"

    @property
    def data_nodes(self):
        return [n for n in self.nodes if n.is_data]

    @property
    def master_nodes(self):
        return [n for n in self.nodes if n.is_master_eligible]

    def index_setting(self, index, key, default=None):
        d = dig(self.index_settings, index, "settings") or {}
        v = _flat_get(d, key)
        if v is None:
            d2 = dig(self.index_settings, index, "defaults") or {}
            v = _flat_get(d2, key)
        return v if v is not None else default

    def is_system_index(self, name):
        """시스템(제품 내부) 인덱스 여부.

        '.' 으로 시작하는 인덱스라도 데이터 스트림 백킹 인덱스(.ds-<data stream>-...)는 사용자 데이터다.
        백킹 인덱스는 데이터 스트림 이름이 '.' 으로 시작할 때만(.ds-.kibana-event-log 등) 시스템으로 본다.
        searchable snapshot 마운트 이름(restored-/partial-)은 원래 이름 기준으로 판단한다.
        """
        if not name:
            return False
        n = name
        for prefix in ("partial-restored-", "restored-", "partial-"):
            if n.startswith(prefix):
                n = n[len(prefix):]
                break
        if n.startswith(".ds-"):
            return n[4:].startswith(".")
        return n.startswith(".")

    def is_searchable_snapshot(self, name):
        """searchable snapshot 마운트 인덱스 여부(설정 기준, 없으면 이름 접두사로 추정).

        스냅샷이 원본이라 shrink·force-merge·설정 변경 같은 조치를 할 수 없다(조치형 판정에서 제외).
        크기가 원본이 아닌 것은 partial 마운트뿐이다(is_partial_mount).
        """
        if self.index_setting(name, "index.store.snapshot.snapshot_name") or \
                self.index_setting(name, "index.store.snapshot.repository_name") or \
                str(self.index_setting(name, "index.store.type") or "") == "snapshot":
            return True
        return bool(name) and name.startswith(("restored-", "partial-"))

    def is_partial_mount(self, name):
        """partially mounted(frozen) 인덱스 여부. store 크기가 로컬 캐시 크기라 원본 샤드 크기가 아니다.

        fully mounted(restored-, cold) 인덱스는 샤드 전체가 로컬에 복사되므로 store 크기가 실제 크기다 — 크기 판정에 포함한다.
        """
        if str(self.index_setting(name, "index.store.snapshot.partial") or "").lower() == "true":
            return True
        return bool(name) and name.startswith("partial-")

    def write_targets(self):
        """현재 쓰기 대상 인덱스: 데이터 스트림 write index + alias 의 is_write_index=true (없으면 단일 인덱스 alias)."""
        if getattr(self, "_write_targets", None) is not None:
            return self._write_targets
        out = set()
        for ds in self.data_streams or []:
            idxs = ds.get("indices") or []
            if idxs:
                out.add(idxs[-1].get("index_name"))
        by_alias = {}
        for idx, body in (self.aliases or {}).items():
            for alias, meta in ((body or {}).get("aliases") or {}).items():
                by_alias.setdefault(alias, []).append((idx, (meta or {}).get("is_write_index")))
        for alias, members in by_alias.items():
            flagged = [i for i, w in members if w is True]
            if flagged:
                out.update(flagged)
            elif len(members) == 1:
                out.add(members[0][0])
        self._write_targets = out
        return out

    def rolled_over(self, name):
        """롤오버 완료(쓰기 종료) 인덱스 여부: 데이터 스트림의 과거 백킹 인덱스, indexing_complete, 쓰기 대상이 아닌 alias 멤버."""
        if name in self.write_targets():
            return False
        if str(self.index_setting(name, "index.lifecycle.indexing_complete") or "").lower() == "true":
            return True
        for ds in self.data_streams or []:
            if any(i.get("index_name") == name for i in (ds.get("indices") or [])[:-1]):
                return True
        body = (self.aliases or {}).get(name) or {}
        return bool(body.get("aliases"))

    def tier_of(self, node):
        """데이터 노드의 tier 라벨. 역할 조합이 곧 비교 단위다(같은 tier 끼리만 스펙·부하를 비교)."""
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
        """tier 라벨 → 데이터 노드 목록."""
        out = collections.OrderedDict()
        for n in self.data_nodes:
            t = self.tier_of(n)
            if t:
                out.setdefault(t, []).append(n)
        return out

    def is_frozen_only(self, node):
        return self.tier_of(node) == "frozen"

    def watermark(self, kind):
        """kind: low|high|flood_stage|flood_stage.frozen -> 원문 문자열"""
        key = "cluster.routing.allocation.disk.watermark." + kind
        v = self.setting(key)
        if v is None:
            v = self.t.get({"low": "disk_watermark_low_default", "high": "disk_watermark_high_default",
                            "flood_stage": "disk_watermark_flood_default",
                            "flood_stage.frozen": "disk_watermark_flood_frozen_default"}.get(kind, ""))
        return v

    def watermark_used_pct(self, kind, node_total_bytes):
        """워터마크를 해당 노드 기준 '사용률 %' 로 환산한다.

        ES 8.5+ 의 계산식을 그대로 따른다.
          - 비율(%) 워터마크: 필요 여유공간 = total x (1 - 비율)
          - max_headroom 이 설정되어 있으면 필요 여유공간 = min(위 값, max_headroom)
            (기본값: low 200GB / high 150GB / flood_stage 100GB, 워터마크를 직접 지정하지 않은 경우에만 적용)
          - 바이트 워터마크: 필요 여유공간 = 지정값 (max_headroom 미적용)
        대용량 디스크에서는 max_headroom 때문에 실제 임계 사용률이 90% 보다 훨씬 높아진다.
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
            head = self.setting("cluster.routing.allocation.disk.watermark.%s.max_headroom" % kind)
            if head is None and kind == "flood_stage.frozen":
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
# 통계성 파일은 숫자 필드가 문자열로 와도 숫자로 다룬다(설정 파일은 원문 유지)
_STAT_FILES = ("nodes_stats.json", "indices_stats.json", "cluster_health.json", "cluster_stats.json",
               "recovery.json", "tasks.json", "cluster_pending_tasks.json")


def _num_str(x):
    try:
        f = float(x)
        return int(f) if f.is_integer() and "." not in x else f
    except ValueError:
        return x


def _coerce(x):
    """숫자 문자열을 숫자로 바꾼다. 대형 통계 파일의 복사본을 만들지 않도록 제자리에서 변환한다."""
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
    """dict 가 아니면 빈 dict. 번들 파일 형식이 버전·수집 조건에 따라 달라도 분석이 멈추지 않게 한다."""
    return x if isinstance(x, dict) else {}


def _l(x):
    return x if isinstance(x, list) else []


def _flat_get(d, dotted):
    """평탄 키('a.b.c')와 중첩 dict 둘 다 지원."""
    if not isinstance(d, dict):
        return None
    if dotted in d:
        return d[dotted]
    cur = d
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur
