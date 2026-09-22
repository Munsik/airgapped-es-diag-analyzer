# -*- coding: utf-8 -*-
"""Elastic 공식 Production guidance / Important settings 문서 기준 판정 룰.

각 룰의 refs 에 근거 문서를 명시한다. 진단 번들에서 확인 가능한 항목만 룰로 만들고,
번들에 수집되지 않는 항목(OS readahead, 쿼리 본문 등)은 COVERAGE.md 에 한계로 기록한다.
"""

import collections

from ..model import Finding, Severity, table
from ..util import dig, fmt_bytes, fmt_num, parse_bytes, pct, num, items, strs

CFG = "설정 기준"
SIZ = "샤드·인덱스"
SPD = "성능 기준"
VEC = "벡터 검색"

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
D_GEN = ("General recommendations",
         "https://www.elastic.co/docs/deploy-manage/production-guidance/general-recommendations")
D_KNN = ("Tune approximate kNN search",
         "https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/approximate-knn-search")

GB = 1024 ** 3


ORCH_NOTE = ("이 클러스터는 %s 배포로 보입니다. 아래 항목은 오케스트레이터가 관리하므로 "
             "고객이 직접 변경하지 않는 것이 정상입니다. 참고 정보로만 확인하십시오.")


def _orch(ctx, sev, recommend):
    """오케스트레이터 관리 설정이면 심각도를 낮추고 맥락을 덧붙인다."""
    if ctx.orchestrated:
        return Severity.INFO, (ORCH_NOTE % ctx.deployment) + " " + recommend
    return sev, recommend


def _jvm_args(n):
    return " ".join(n.jvm_args())


# ============================================================
# important-settings-configuration
# ============================================================

def r_cluster_name(ctx):
    """cluster.name 이 기본값 'elasticsearch' 이면 주의. ECH/ECE/ECK 로 감지되면 참고."""
    name = ctx.cluster_name
    if name and str(name).lower() == "elasticsearch":
        sev, rec = _orch(ctx, Severity.WARNING,
                         "용도를 알 수 있는 고유한 이름으로 변경합니다. 변경에는 전체 클러스터 재기동이 필요합니다.")
        return [Finding(
            "CFG-001", CFG, sev, "cluster.name 이 기본값",
            observed="cluster.name = elasticsearch",
            impact="기본 이름을 쓰면 같은 네트워크의 다른 클러스터 노드가 실수로 합류할 수 있습니다. "
                   "환경(운영/검증)별로 이름이 같은 경우도 같은 위험입니다.",
            recommend=rec, refs=[D_SETTINGS], source="cluster_health.json")]
    return []


def r_path_settings(ctx):
    """path.data/path.logs 위치.

    공식 문서의 우려는 archive(tar.gz/zip) 설치에서 업그레이드 시 $ES_HOME 을 교체하며 데이터가 함께
    지워지는 것이다. rpm/deb 는 기본 경로가 이미 외부(/var/lib, /var/log)이고, docker 는 볼륨을
    마운트하는 구조라 대상이 아니다. build_type 으로 판별한다.
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
                         "path.data 와 path.logs 를 $ES_HOME 밖의 전용 경로로 옮깁니다.")
        out.append(Finding(
            "CFG-002", CFG, sev, "data/logs 경로가 ES 설치 디렉터리 내부(archive 설치)",
            observed="대상 노드: %s" % ", ".join(sorted(set(in_home))),
            impact="archive 설치는 업그레이드 시 설치 디렉터리를 교체하므로, 그 안의 데이터와 로그가 "
                   "함께 사라질 수 있습니다.",
            recommend=rec,
            evidence=table(["node", "build_type", "path.data", "path.logs", "path.home"], rows),
            refs=[D_SETTINGS], source="nodes.json"))
    if multi:
        out.append(Finding(
            "CFG-003", CFG, Severity.WARNING, "path.data 다중 경로 사용",
            observed="대상 노드: %s" % ", ".join(multi),
            impact="다중 data path 는 deprecated 입니다. 경로 하나가 고장나면 노드 전체가 영향을 받고, "
                   "경로 간 용량 편차 관리도 어렵습니다.",
            recommend="RAID 또는 LVM 등으로 단일 볼륨을 구성하고 path.data 를 단일 경로로 변경합니다.",
            refs=[D_SETTINGS], source="nodes.json"))
    return out


def r_discovery(ctx):
    """다중 노드인데 discovery.seed_hosts / seed_providers 가 없음 → 주의(CFG-004). cluster.initial_master_nodes 가 남아 있음 → 주의(CFG-005). 실제 바인딩된 transport_address 가 loopback 이거나 discovery.type=single-node → 주의(CFG-006). 오케스트레이터 배포면 모두 참고로 하향."""
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
        # production mode 여부는 '실제 바인딩된 transport 주소' 가 loopback 인지로 결정된다.
        # 설정값이 아니라 nodes info 의 transport_address(사실)를 근거로 판정한다.
        ta = str(n.info.get("transport_address") or "")
        if ta.startswith("127.") or ta.startswith("[::1]") or ta.startswith("localhost") or single:
            dev_mode.append("%s(%s)" % (n.name, "single-node" if single else ta))
    if missing_seed:
        sev, rec = _orch(ctx, Severity.WARNING,
                         "마스터 후보 노드 주소를 discovery.seed_hosts 에 명시합니다.")
        out.append(Finding(
            "CFG-004", CFG, sev, "discovery.seed_hosts 미설정",
            observed="대상 노드: %s" % ", ".join(missing_seed),
            impact="노드가 서로를 찾지 못해 재기동 후 클러스터에 합류하지 못할 수 있습니다.",
            recommend=rec, refs=[D_SETTINGS], source="nodes.json"))
    if initial_left:
        sev, rec = _orch(ctx, Severity.WARNING,
                         "클러스터가 이미 구성되었다면 모든 노드의 elasticsearch.yml 에서 이 설정을 제거합니다.")
        out.append(Finding(
            "CFG-005", CFG, sev, "cluster.initial_master_nodes 잔존",
            observed="대상 노드: %s" % ", ".join(initial_left),
            impact="최초 부트스트랩 이후에는 무시되는 설정이지만, 남겨 두면 노드를 새 데이터 경로로 "
                   "재구성하는 등의 상황에서 별도 클러스터가 부트스트랩될 위험이 있어 공식 문서가 제거를 권고합니다.",
            recommend=rec, refs=[D_SETTINGS], source="nodes.json"))
    if dev_mode:
        sev, rec = _orch(ctx, Severity.WARNING,
                         "운영 환경이라면 network.host(또는 transport.host)를 실제 서비스 주소로 지정해 "
                         "production mode 로 전환합니다.")
        out.append(Finding(
            "CFG-006", CFG, sev, "development mode 로 동작 중인 노드",
            observed="transport 가 loopback 에 바인딩되었거나 single-node 인 노드: %s" % ", ".join(dev_mode),
            impact="development mode 에서는 bootstrap check 실패가 경고로만 기록되고 기동됩니다. "
                   "운영 환경에서는 잘못된 OS·JVM 설정이 그대로 통과합니다.",
            recommend=rec, refs=[D_SETTINGS], source="nodes.json (transport_address)"))
    return out


def _gc_logging_enabled(args):
    """-Xlog 옵션은 뒤에 나온 것이 앞의 것을 덮는다.

    배포 형태·버전에 따라 '-Xlog:disable' 이 GC 로깅 옵션보다 앞에 들어가는 경우가 있으므로,
    '-Xlog:disable' 존재만으로 꺼짐으로 보지 않고 마지막 disable 이후에 gc 파일 로깅이 있는지로 판단한다.
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
    """jvm.input_arguments 기준. HeapDumpOnOutOfMemoryError 없음 → 주의(CFG-007). 마지막 -Xlog:disable 이후 gc 파일 로깅 옵션 없음 → 주의(CFG-008). ErrorFile 없음 → 참고(CFG-009). 오케스트레이터 배포면 참고로 하향."""
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
                         "-XX:+HeapDumpOnOutOfMemoryError 와 -XX:HeapDumpPath 를 설정하고, "
                         "heap 크기 이상의 여유 디스크를 확보합니다.")
        out.append(Finding(
            "CFG-007", CFG, sev, "OOM heap dump 설정 없음",
            observed="대상 노드: %s" % ", ".join(no_dump),
            impact="OutOfMemoryError 발생 시 heap dump 가 남지 않아 사후 원인 분석이 불가능합니다.",
            recommend=rec, refs=[D_SETTINGS], source="nodes.json (jvm.input_arguments)"))
    if no_gclog:
        sev, rec = _orch(ctx, Severity.WARNING,
                         "jvm.options 의 기본 GC 로깅(-Xlog:gc*,...:file=...)을 유지합니다.")
        out.append(Finding(
            "CFG-008", CFG, sev, "GC 로그 파일 출력 비활성",
            observed="대상 노드: %s" % ", ".join(no_gclog),
            impact="GC 정지 시간(STW)을 사후에 확인할 수 없어, 지연 장애가 GC 때문인지 판정할 수 없습니다.",
            recommend=rec, refs=[D_SETTINGS], source="nodes.json (jvm.input_arguments)"))
    if no_errfile:
        sev, rec = _orch(ctx, Severity.INFO, "-XX:ErrorFile 을 로그 디렉터리로 지정합니다.")
        out.append(Finding(
            "CFG-009", CFG, sev, "JVM fatal error 로그 경로 미지정",
            observed="대상 노드: %s" % ", ".join(no_errfile),
            impact="JVM 자체가 비정상 종료될 때 남는 hs_err 파일 위치를 특정하기 어렵습니다.",
            recommend=rec, refs=[D_SETTINGS], source="nodes.json (jvm.input_arguments)"))
    return out


def r_docs_per_shard(ctx):
    """샤드별 문서 수. 인덱스 평균이 아니라 샤드 단위(cat shards) 값으로 판정한다.

    Lucene 한계(2,147,483,519)는 삭제 문서를 포함한 maxDoc 기준이다. cat shards 에는 삭제 수가 없어
    인덱스 삭제 수를 primary 수로 나눈 값을 더한다(추정치임을 표기).
    """
    pri_count = collections.Counter()
    for s in ctx.shards:
        if (s.get("prirep") or "").lower() == "p":
            pri_count[s.get("index")] += 1
    warn, crit = [], []
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
        elif docs >= ctx.t["docs_per_shard_warn"]:
            warn.append(row)
    out = []
    cols = ["index", "shard", "문서", "삭제 포함(추정)", "node"]
    if crit:
        out.append(Finding(
            "SHD-007", SIZ, Severity.CRITICAL, "샤드 문서 수가 Lucene 한계에 근접",
            observed="삭제 포함 %s건 이상인 샤드 %d개." % (fmt_num(ctx.t["docs_per_shard_crit"]), len(crit)),
            impact="Lucene 샤드는 삭제 문서를 포함해 2,147,483,519건을 넘을 수 없습니다. "
                   "도달하면 해당 샤드로의 색인이 실패합니다.",
            recommend="롤오버·split·reindex 로 분할하고, 삭제 문서가 많다면 저부하 시간대에 "
                      "force-merge(only_expunge_deletes=true)를 수행합니다.",
            evidence=table(cols, crit[: ctx.t["top_n"]]), refs=[D_SHARDS], source="indices.json"))
    if warn:
        out.append(Finding(
            "SHD-008", SIZ, Severity.WARNING, "샤드당 문서 수 권장치 초과",
            observed="문서 %s건 이상인 샤드 %d개." % (fmt_num(ctx.t["docs_per_shard_warn"]), len(warn)),
            impact="공식 권장은 샤드당 2억건 미만입니다.",
            recommend="롤오버 조건에 max_primary_shard_docs 를 함께 지정합니다.",
            evidence=table(cols, warn[: ctx.t["top_n"]]), refs=[D_SHARDS], source="indices.json"))
    return out


def r_master_heap_per_index(ctx):
    """마스터 후보 노드 heap 1GB당 인덱스 3000개 기준."""
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
        "마스터 노드 heap 대비 인덱스 수 과다",
        observed="인덱스 %s개. 기준은 마스터 heap 1GB당 %s개이며, 여유가 20%% 미만인 노드: %s"
                 % (fmt_num(n_idx), fmt_num(ctx.t["indices_per_gb_master_heap"]), ", ".join(bad)),
        impact="마스터가 관리할 수 있는 인덱스 수는 heap 크기에 비례합니다. 초과하면 cluster state 처리가 "
               "느려지고 pending task 적체, 노드 조인 지연이 발생합니다.",
        recommend="인덱스를 통합하거나 오래된 인덱스를 삭제·동결합니다. 전용 마스터 노드 heap 증설도 함께 검토합니다.",
        evidence=table(["master 후보", "heap", "관리 가능 인덱스(기준)", "현재 인덱스", "사용률"], rows),
        refs=[D_SHARDS], source="cluster_stats.json / nodes.json")]


def r_mapping_heap_overhead(ctx):
    """데이터 노드별 필요 heap 추정 = cluster state 매핑 크기(중복 제거) + 노드 필드 오버헤드 + 0.5GB(공식 산정식).

    추정치 / heap_max >= mapping_heap_pct_warn → 주의, 미만 → 정상. 전용 마스터·ML 노드는 산정 대상이 아니다.
    """
    dedup = dig(ctx.cluster_stats, "indices", "mappings", "total_deduplicated_mapping_size_in_bytes")
    rows, bad = [], []
    # 공식 산정식(필드당 heap + 0.5GB)은 샤드를 가진 데이터 노드 기준이다. 전용 마스터·ML 노드는 대상이 아니다.
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
            bad.append(n.name)
    if not rows:
        return []
    ev = table(["node", "cluster state 매핑", "노드 필드 오버헤드", "필요 heap(추정)", "heap", "비중"], rows)
    if not bad:
        return [Finding("SHD-010", SIZ, Severity.OK, "매핑 heap 오버헤드 여유",
                        observed="매핑 관련 heap 소요가 각 노드 heap 의 %d%% 미만입니다."
                                 % ctx.t["mapping_heap_pct_warn"],
                        evidence=ev, refs=[D_SHARDS], source="cluster_stats.json / nodes_stats.json")]
    return [Finding(
        "SHD-010", SIZ, Severity.WARNING, "매핑 메타데이터가 heap 을 과도하게 점유",
        observed="필요 heap 추정치가 실제 heap 의 %d%% 를 넘는 노드: %s"
                 % (ctx.t["mapping_heap_pct_warn"], ", ".join(bad)),
        impact="cluster state 의 매핑 정보와 데이터 노드의 필드 오버헤드는 상시 heap 을 점유합니다. "
               "여기에 색인·검색·집계용 heap 이 추가로 필요하므로, 비중이 크면 만성적인 heap 압박이 됩니다.",
        recommend="미사용 필드를 제거하고 dynamic mapping 을 통제합니다. 함께 쓰는 필드는 copy_to 로 통합하고, "
                  "드물게 쓰는 필드는 runtime field 로 전환합니다.",
        evidence=ev, refs=[D_SHARDS], source="cluster_stats.json / nodes_stats.json")]


def r_empty_indices(ctx):
    """docs.count=0 인 사용자 인덱스 수 >= empty_index_count_warn → 주의.

    현재 쓰기 대상(데이터 스트림 write index, alias write index)은 막 롤오버되어 비어 있을 수 있으므로 제외한다.
    """
    rows = []
    targets = ctx.write_targets()
    for name, st in ctx.indices_stats.items():
        if ctx.is_system_index(name) or name in targets:
            continue        # 현재 쓰기 대상(막 롤오버된 write index 등)은 비어 있는 게 정상
        docs = dig(st, "primaries", "docs", "count")
        if docs == 0:
            shards = ctx.shard_count(name)
            rows.append([name, shards, fmt_bytes(dig(st, "total", "store", "size_in_bytes"))])
    if len(rows) < ctx.t["empty_index_count_warn"]:
        return []
    total_shards = sum(r[1] for r in rows)
    return [Finding(
        "SHD-011", SIZ, Severity.WARNING, "빈 인덱스 다수",
        observed="문서가 0건인 사용자 인덱스 %d개(샤드 %d개 점유)." % (len(rows), total_shards),
        impact="ILM 롤오버를 max_age 기준으로만 운영하면 데이터가 없는 인덱스가 계속 생성됩니다. "
               "아무 이득 없이 샤드 수와 cluster state 만 키웁니다.",
        recommend="빈 인덱스를 삭제하고, 롤오버 조건을 max_primary_shard_size 중심으로 변경합니다.",
        evidence=table(["index", "샤드 수", "크기"], rows[: ctx.t["top_n"]]),
        refs=[D_SHARDS], source="indices_stats.json")]


def r_total_shards_per_node(ctx):
    """핫스팟 방지용 index.routing.allocation.total_shards_per_node 설정 여부(대형 색인 인덱스)."""
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
        "SHD-012", SIZ, Severity.INFO, "색인량 많은 인덱스에 total_shards_per_node 미설정",
        observed="대상 인덱스 %d개." % len(rows),
        impact="색인 부하가 큰 인덱스의 샤드가 한 노드에 몰리면 그 노드가 핫스팟이 됩니다. "
               "ES 의 기본 밸런싱은 샤드 개수 기준이라 이를 막지 못할 수 있습니다.",
        recommend="index.routing.allocation.total_shards_per_node 로 노드당 샤드 수 상한을 둡니다. "
                  "값이 너무 작으면 샤드가 미할당되므로 여유를 두고 설정합니다.",
        evidence=table(["index", "색인 문서 수", "샤드 수"], rows[: ctx.t["top_n"]]),
        refs=[D_SHARDS], source="settings.json / indices_stats.json")]


# ============================================================
# indexing-speed / search-speed
# ============================================================

def r_index_buffer(ctx):
    """샤드당 indexing buffer.

    indices.memory.index_buffer_size(기본 heap 10%)는 '최근 쓰기가 있는(active) 샤드' 가 나눠 쓴다.
    5분 이상 쓰기가 없는 샤드는 inactive 로 버퍼를 반납한다. 번들에서 active 여부를 직접 알 수 없으므로
    쓰기 대상으로 확정 가능한 샤드(데이터 스트림 write index + 수집 순간 색인 중인 인덱스)만 센다.
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
        "PERF-004", SPD, Severity.INFO, "쓰기 대상 샤드당 indexing buffer 부족",
        observed="쓰기 대상 샤드당 indexing buffer 가 %s 미만인 노드 %d대."
                 % (fmt_bytes(ctx.t["index_buffer_per_shard_warn"]), len(rows)),
        impact="버퍼가 작으면 flush 가 잦아져 작은 세그먼트가 많이 생기고 merge 부담이 커집니다. "
               "공식 문서의 기준은 집중 색인 중인 샤드당 최대 512MB 이며, 그 이상은 효과가 없습니다.",
        recommend="쓰기 대상 샤드 수(동시에 쓰는 인덱스 × primary 수)를 줄이는 것이 우선이고, "
                  "색인 전용 노드라면 index_buffer_size 상향을 검토합니다.",
        evidence=table(["node", "indexing buffer", "쓰기 대상 샤드", "샤드당"], rows),
        refs=[D_INDEX], source="nodes.json / data_stream.json / indices.json")]


def r_open_contexts(ctx):
    """노드 search.open_contexts >= open_contexts_warn → 주의."""
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
        "PERF-005", SPD, Severity.WARNING, "열린 search context 과다",
        observed="open_contexts 가 %d 이상인 노드 %d대." % (ctx.t["open_contexts_warn"], len(rows)),
        impact="search context 는 shard 단위 read lock 이자 heap 점유입니다. scroll 을 제때 닫지 않으면 "
               "누적되어 heap 압박과 세그먼트 미해제(디스크 미회수)를 유발합니다.",
        recommend="scroll 사용처를 확인해 완료 즉시 clear scroll 을 호출하고, scroll timeout 을 줄입니다. "
                  "깊은 페이징은 search_after 로 전환합니다. 검색 큐 적체가 동반되는지도 함께 봅니다.",
        evidence=table(["node", "open_contexts", "진행 중 scroll", "누적 scroll"], rows),
        refs=[D_SEARCH], source="nodes_stats.json")]


def r_search_timeout(ctx):
    """search.default_search_timeout 이 미설정 또는 -1(무제한)이면 참고."""
    v = ctx.setting("search.default_search_timeout")
    if v and str(v) not in ("-1", "-1ms", "0"):
        return []
    return [Finding(
        "PERF-006", SPD, Severity.INFO, "기본 검색 타임아웃 미설정",
        observed="search.default_search_timeout 이 설정되어 있지 않습니다(기본: 무제한).",
        impact="잘못 만들어진 쿼리 하나가 끝없이 자원을 점유할 수 있습니다. 검색 스레드풀 포화의 흔한 경로입니다.",
        recommend="업무 특성에 맞는 기본 타임아웃(예: 30s)을 클러스터 설정으로 지정하는 것을 검토합니다. "
                  "장시간 배치 쿼리가 필요한 경우 요청 단위로 타임아웃을 지정합니다.",
        refs=[D_SEARCH], source="cluster_settings.json")]


def r_replica_throughput(ctx):
    """search-speed 의 권장식: replicas = max(max_failures, ceil(num_nodes/num_primaries) - 1)."""
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
        "PERF-007", SPD, Severity.INFO, "검색 부하 대비 replica 수가 적은 인덱스",
        observed="검색 요청이 많은 인덱스 중 권장 replica 수에 못 미치는 인덱스 %d개." % len(rows),
        impact="primary 수가 데이터 노드 수보다 적으면 일부 노드가 해당 인덱스의 검색에 참여하지 못합니다. "
               "replica 를 늘리면 검색 처리량이 늘지만, 노드당 샤드 수가 늘어 파일시스템 캐시 몫은 줄어듭니다.",
        recommend="공식 권장식은 max(허용 장애 노드 수, ceil(노드 수 / primary 수) - 1) 입니다. "
                  "캐시 효율과 처리량의 균형을 보고 조정합니다.",
        evidence=table(["index", "검색 횟수", "primary", "현재 replica", "권장 replica"],
                       rows[: ctx.t["top_n"]]),
        refs=[D_SEARCH], source="settings.json / indices_stats.json")]


def r_store_preload(ctx):
    """index.store.preload 가 설정된 인덱스가 있으면 참고, 그 수 > preload_index_count_warn 이면 주의."""
    rows = []
    for name in ctx.index_settings.keys():
        v = ctx.index_setting(name, "index.store.preload")
        if v:
            rows.append([name, str(v)])
    if not rows:
        return []
    sev = Severity.WARNING if len(rows) > ctx.t["preload_index_count_warn"] else Severity.INFO
    return [Finding(
        "PERF-008", SPD, sev, "index.store.preload 사용 인덱스",
        observed="preload 가 설정된 인덱스 %d개." % len(rows),
        impact="preload 는 지정한 확장자의 파일을 파일시스템 캐시로 미리 올립니다. 대상 인덱스가 많으면 "
               "캐시가 서로를 밀어내 오히려 검색이 느려집니다.",
        recommend="핵심 인덱스와 필요한 확장자로만 한정합니다. 양자화 벡터 인덱스라면 원본 벡터(vec)까지 "
                  "preload 하지 않는 편이 낫습니다.",
        evidence=table(["index", "preload"], rows[: ctx.t["top_n"]]),
        refs=[D_SEARCH, D_KNN], source="settings.json")]


def r_remote_storage(ctx):
    """nodes_stats fs.data[].type 에 nfs / cifs / smb / fuse / glusterfs / ceph 가 포함되면 주의."""
    rows = []
    for n in ctx.nodes:
        for d in dig(n.stats, "fs", "data", default=[]) or []:
            t = (d.get("type") or "").lower()
            if t and any(x in t for x in ("nfs", "cifs", "smb", "fuse", "glusterfs", "ceph")):
                rows.append([n.name, d.get("mount"), d.get("type"), fmt_bytes(d.get("total_in_bytes"))])
    if not rows:
        return []
    return [Finding(
        "PERF-009", SPD, Severity.WARNING, "네트워크 파일시스템 기반 데이터 경로",
        observed="원격/네트워크 파일시스템으로 보이는 data path %d건." % len(rows),
        impact="Elasticsearch 는 직접 연결된 로컬 스토리지에서 가장 좋은 성능을 냅니다. 원격 스토리지는 "
               "지연이 커서 검색·색인·복구 모두 느려지고, 일부 구성은 데이터 정합성 문제도 있습니다.",
        recommend="로컬 SSD/NVMe 사용을 권장합니다. 불가피하다면 실제 워크로드로 벤치마크한 뒤 도입합니다.",
        evidence=table(["node", "mount", "type", "크기"], rows),
        refs=[D_INDEX, D_SEARCH], source="nodes_stats.json")]


# ============================================================
# disk-usage
# ============================================================

def r_codec(ctx):
    """standard 모드 사용자 인덱스 중 primary store >= codec_check_min_bytes 이고 index.codec 이 default(미지정) → 참고. logsdb·time_series 는 best_compression 이 기본이라 제외."""
    rows = []
    for name, st in ctx.indices_stats.items():
        if ctx.is_system_index(name):
            continue
        size = num(st, "primaries", "store", "size_in_bytes")
        if size < ctx.t["codec_check_min_bytes"]:
            continue
        mode = str(ctx.index_setting(name, "index.mode") or "standard").lower()
        if mode in ("logsdb", "time_series"):
            continue        # 이 인덱스 모드는 best_compression 이 기본값이다
        codec = ctx.index_setting(name, "index.codec")
        if codec is None or str(codec).lower() == "default":
            rows.append([name, fmt_bytes(size), str(codec or "default"), mode, size])
    if not rows:
        return []
    rows.sort(key=lambda r: -r[4])
    total = sum(r[4] for r in rows)
    return [Finding(
        "DISK-006", SIZ, Severity.INFO, "대형 standard 인덱스에 기본 codec 사용",
        observed="%s 이상 standard 모드 인덱스 %d개(합계 %s)가 best_compression 을 쓰지 않습니다."
                 % (fmt_bytes(ctx.t["codec_check_min_bytes"]), len(rows), fmt_bytes(total)),
        impact="best_compression 은 stored field(_source 포함)를 더 강하게 압축하는 대신, 문서를 "
               "읽어 올 때 압축 해제 비용이 늘어납니다. logsdb·time_series 모드는 이미 기본 적용이라 제외했습니다.",
        recommend="개별 문서 조회보다 검색·집계 위주인 데이터라면 적용을 검토합니다. "
                  "기존 세그먼트는 merge 또는 reindex 후에 반영됩니다.",
        evidence=table(["index", "크기", "codec", "index.mode"], [r[:4] for r in rows[: ctx.t["top_n"]]]),
        refs=[D_DISK], source="settings.json / indices_stats.json")]


def r_source_mode(ctx):
    """index.mapping.source.mode=disabled → 주의. 그 외 모드(synthetic 등) 지정 → 참고."""
    rows = []
    for name in ctx.index_settings.keys():
        mode = ctx.index_setting(name, "index.mapping.source.mode")
        if mode:
            rows.append([name, str(mode)])
    if not rows:
        return []
    disabled = [r for r in rows if str(r[1]).lower() == "disabled"]
    if not disabled:
        return [Finding(
            "DISK-007", SIZ, Severity.INFO, "synthetic _source 사용 인덱스",
            observed="_source mode 가 지정된 인덱스 %d개." % len(rows),
            impact="synthetic _source 는 저장 용량을 줄이지만, 원본 문서와 완전히 동일하지 않을 수 있습니다.",
            recommend="재색인·하이라이팅 요구사항을 확인합니다.",
            evidence=table(["index", "source.mode"], rows[: ctx.t["top_n"]]),
            refs=[D_DISK], source="settings.json")]
    return [Finding(
        "DISK-007", SIZ, Severity.WARNING, "_source 비활성 인덱스",
        observed="_source 가 disabled 인 인덱스 %d개." % len(disabled),
        impact="update, reindex, highlight 가 동작하지 않습니다. 매핑 변경이 필요할 때 재색인이 불가능해 "
               "원본 데이터를 외부에서 다시 확보해야 합니다.",
        recommend="용량이 목적이라면 _source 비활성 대신 synthetic _source 또는 best_compression 을 검토합니다.",
        evidence=table(["index", "source.mode"], disabled[: ctx.t["top_n"]]),
        refs=[D_DISK], source="settings.json")]


def r_dynamic_mapping(ctx):
    """컴포넌트까지 병합한 결과 기준으로 동적 매핑 통제 여부를 본다."""
    rows = []
    for name, mappings, _settings, patterns in _composed_templates(ctx):
        if str(name).startswith(".") or not patterns:
            continue
        if all(str(p).startswith(".") for p in patterns):
            continue
        dyn = mappings.get("dynamic")
        has_dyn_tpl = bool(mappings.get("dynamic_templates"))
        if dyn is None and not has_dyn_tpl:
            rows.append([name, ", ".join(patterns)[:80], "dynamic=true(기본)", "dynamic_templates 없음"])
    if not rows:
        return []
    return [Finding(
        "MAP-003", SIZ, Severity.INFO, "동적 매핑 통제가 없는 인덱스 템플릿",
        observed="컴포넌트 템플릿까지 병합해도 dynamic 설정·dynamic_templates 가 없는 템플릿 %d개." % len(rows),
        impact="기본 동적 매핑은 문자열 필드를 text 와 keyword 두 가지로 모두 색인합니다. "
               "하나만 필요하면 디스크를 이중으로 쓰고, 새 필드가 들어올 때마다 매핑이 늘어납니다.",
        recommend="dynamic_templates 로 문자열을 keyword 또는 text 한쪽으로 고정하거나, "
                  "dynamic:false 와 명시 매핑으로 통제합니다.",
        evidence=table(["template", "index_patterns", "dynamic", "비고"], rows[: ctx.t["top_n"]]),
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
    """index template 을 composed_of 컴포넌트와 합쳐 '실제로 적용될' mappings/settings 로 만든다.

    ES 는 composed_of 순서대로 컴포넌트를 병합한 뒤 index template 본문을 마지막에 덮는다.
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
    """인덱스별 dense_vector off-heap 사용량(9.x indices stats)."""
    out = {}
    for name, st in ctx.indices_stats.items():
        # 검색은 replica 에서도 수행되므로 total(primary+replica) 기준으로 본다.
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
            # HNSW 탐색에 상주해야 하는 부분: 양자화본이 있으면 양자화본+그래프, 없으면 원본+그래프.
            # 원본(vec)은 양자화 인덱스에서 rescore 할 때만 읽는다.
            if veq or veb or vec or vex:
                need = ((veq + veb) if (veq or veb) else vec) + vex
            else:
                need = total or 0
            out[name] = {"bytes": total or 0, "need": need, "count": cnt,
                         "vec": vec, "veq": veq, "veb": veb, "vex": vex}
    return out


def r_vector_memory(ctx):
    """인덱스별 dense_vector off-heap(total, 없으면 primaries). 상주 필요량 = (veq+veb 가 있으면 그 값, 없으면 vec) + vex. 합계 / Σ(데이터 노드 RAM − heap) >= vector_vs_fscache_pct_warn → 주의, 미만 → 참고. 노드별 분포는 보지 않는 클러스터 합계 추정이다."""
    vs = _vector_stats(ctx)
    total = sum(v["need"] for v in vs.values())
    if not total:
        return []
    # 사용 가능한 파일시스템 캐시 = 데이터 노드 RAM - heap
    avail = 0
    rows_node = []
    for n in ctx.data_nodes or ctx.nodes:
        ram, heap = n.ram_total or 0, n.heap_max or 0
        free = max(0, ram - heap)
        avail += free
        rows_node.append([n.name, fmt_bytes(ram), fmt_bytes(heap), fmt_bytes(free)])
    top = sorted(vs.items(), key=lambda kv: -kv[1]["need"])[: ctx.t["top_n"]]
    ev = table(["index", "상주 필요(추정)", "전체 off-heap", "벡터 수", "원본(vec)",
                "양자화(veq/veb)", "HNSW 그래프(vex)"],
               [[k, fmt_bytes(v["need"]), fmt_bytes(v["bytes"]), fmt_num(v["count"]),
                 fmt_bytes(v["vec"]), fmt_bytes(v["veq"] + v["veb"]), fmt_bytes(v["vex"])]
                for k, v in top])
    p = pct(total, avail)
    if p is not None and p >= ctx.t["vector_vs_fscache_pct_warn"]:
        return [Finding(
            "VEC-001", VEC, Severity.WARNING, "벡터 데이터가 파일시스템 캐시 용량에 근접",
            observed="HNSW 상주 필요량(replica 포함) %s / 데이터 노드 가용 캐시(RAM-heap) %s (%.0f%%)."
                     % (fmt_bytes(total), fmt_bytes(avail), p),
            impact="HNSW 는 벡터 데이터와 그래프가 메모리에 상주해야 성능이 나옵니다. 캐시에 들어가지 못하면 "
                   "매 검색이 디스크를 읽어 지연이 급격히 커집니다. 이 메모리는 JVM heap 이 아니라 "
                   "off-heap(파일시스템 캐시)이라는 점에 유의합니다.",
            recommend="양자화(int8/int4/bbq)로 메모리 사용량을 줄이거나, 차원 수를 낮추거나, 노드 RAM 을 늘립니다. "
                      "양자화 인덱스인데 RAM 이 부족하면 on_disk_rescore 적용도 검토합니다. "
                      "DiskBBQ 는 HNSW 보다 적은 메모리에서 선형적으로 동작합니다.",
            evidence=ev, refs=[D_KNN], source="indices_stats.json / nodes_stats.json")]
    return [Finding(
        "VEC-001", VEC, Severity.INFO, "벡터 데이터 사용 현황",
        observed="HNSW 상주 필요량(replica 포함) %s / 가용 캐시 %s%s."
                 % (fmt_bytes(total), fmt_bytes(avail), (" (%.0f%%)" % p) if p is not None else ""),
        impact="벡터 검색 성능은 파일시스템 캐시 적중률에 직접 좌우됩니다.",
        recommend="증가 추세를 관찰하고, 캐시 대비 비중이 커지기 전에 양자화 적용을 검토합니다.",
        evidence=ev, refs=[D_KNN], source="indices_stats.json")]


def r_vector_quantization(ctx):
    """고차원 float 벡터의 양자화 여부 (컴포넌트 병합 후 판정).

    8.14 부터 dense_vector 의 index_options 를 지정하지 않으면 양자화 HNSW 가 기본 적용된다.
    따라서 '미지정' 은 8.14 이상에서 문제로 보지 않고, 비양자화 타입(hnsw/flat)을 명시한 경우만 판정한다.
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
                        rows_dim.append([tname, full, dims_i, itype or "(미지정: 8.14 미만 기본 hnsw)"])
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
            "VEC-002", VEC, Severity.WARNING, "고차원 float 벡터에 비양자화 인덱스 사용",
            observed="%d차원 이상 float dense_vector 필드 %d개가 양자화 없이 색인됩니다."
                     % (ctx.t["vector_dim_quantize_warn"], len(rows_dim)),
            impact="양자화하면 HNSW 탐색에 필요한 메모리가 int8 은 약 4배, int4 는 약 8배, bbq 는 최대 약 32배 "
                   "줄어듭니다. 원본 벡터도 함께 보관하므로 디스크 사용량은 소폭 늘어납니다.",
            recommend="정확도 요구에 맞춰 int8_hnsw / int4_hnsw / bbq_hnsw 중 선택하고 재현율을 측정합니다. "
                      "적용에는 재색인이 필요합니다.",
            evidence=table(["template", "필드", "dims", "index_options.type"], rows_dim[: ctx.t["top_n"]]),
            refs=[D_KNN], source="index_templates.json / component_templates.json"))
    if rows_src:
        out.append(Finding(
            "VEC-003", VEC, Severity.INFO, "_source 벡터 제외 설정 미지정",
            observed="벡터 필드를 가진 템플릿 %d개에 index.mapping.exclude_source_vectors 가 없습니다."
                     % len(rows_src),
            impact="_source 에 고차원 벡터가 남아 있으면 검색 결과를 만들 때마다 큰 JSON 을 읽어 반환해 "
                   "kNN 검색이 느려집니다.",
            recommend="index.mapping.exclude_source_vectors 를 사용합니다. 9.2 이상에서 생성된 인덱스는 "
                      "기본 적용이며, 재색인·복구 시 벡터가 자동 복원됩니다.",
            evidence=table(["template", "벡터 필드"], rows_src[: ctx.t["top_n"]]),
            refs=[D_KNN], source="index_templates.json / component_templates.json"))
    return out


def r_vector_segments(ctx):
    """벡터 데이터가 있는 인덱스의 primary 세그먼트 / primary 샤드 >= vector_segments_per_shard_warn → 주의."""
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
            rows.append([name, fmt_num(seg), shards, "%.0f" % per, str(mms or "5gb(기본)")])
    if not rows:
        return []
    return [Finding(
        "VEC-004", VEC, Severity.WARNING, "벡터 인덱스의 세그먼트 수 과다",
        observed="샤드당 세그먼트 %d개 이상인 벡터 인덱스 %d개."
                 % (ctx.t["vector_segments_per_shard_warn"], len(rows)),
        impact="kNN 검색은 세그먼트마다 별도의 벡터 구조를 검사합니다. 세그먼트가 많을수록 검색이 느려집니다.",
        recommend="index.merge.policy.max_merged_segment 를 10GB~20GB 로 올려 세그먼트 수를 줄이고, "
                  "초기 대량 적재 시에는 refresh_interval=-1 과 충분한 indexing buffer 로 큰 세그먼트를 만듭니다. "
                  "쓰기가 끝난 인덱스는 force-merge 합니다.",
        evidence=table(["index", "세그먼트", "primary", "샤드당", "max_merged_segment"],
                       rows[: ctx.t["top_n"]]),
        refs=[D_KNN], source="indices_stats.json / settings.json")]


def r_large_result_sets(ctx):
    """max_result_window 상향 여부(사용자 인덱스)."""
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
        "GEN-001", SPD, Severity.WARNING, "max_result_window 상향 인덱스",
        observed="기본값(10,000)보다 큰 사용자 인덱스 %d개(최대 %s)." % (len(rows), rows[0][1]),
        impact="from+size 로 깊은 페이지를 읽으면 각 샤드가 from+size 건을 모아 coordinating 노드로 "
               "보내므로 heap 사용량이 페이지 깊이에 비례해 커집니다.",
        recommend="전체 결과가 필요하면 search_after + PIT 를 사용하고, max_result_window 는 기본값으로 되돌립니다.",
        evidence=table(["index", "max_result_window"], rows[: ctx.t["top_n"]]),
        refs=[D_GEN], source="settings.json")]


def r_large_documents(ctx):
    """http.max_content_length 상향 및 평균 문서 크기."""
    out, rows = [], []
    for n in ctx.nodes:
        v = n.setting("http.max_content_length")
        b = parse_bytes(v)
        if b and b > 100 * 1024 ** 2:
            rows.append([n.name, str(v)])
    if rows:
        out.append(Finding(
            "GEN-002", SPD, Severity.WARNING, "http.max_content_length 상향",
            observed="기본값(100MB)보다 크게 설정된 노드 %d대." % len(rows),
            impact="대형 문서는 네트워크·메모리·디스크에 모두 부담을 줍니다. 색인 시 원본 크기의 몇 배에 "
                   "해당하는 메모리를 쓰고, phrase 검색과 하이라이팅 비용도 문서 크기에 비례합니다. "
                   "한도를 올려도 Lucene 자체 한계(약 2GB)는 남습니다.",
            recommend="문서 단위를 재검토합니다. 책 한 권이 아니라 장·문단 단위로 나누고 식별자로 묶는 편이 "
                      "성능과 검색 품질 모두에 낫습니다.",
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
            "GEN-003", SPD, Severity.INFO, "평균 문서 크기가 큰 인덱스",
            observed="문서 평균 크기가 %s 이상인 인덱스 %d개(최대 %s)."
                     % (fmt_bytes(ctx.t["avg_doc_bytes_warn"]), len(big), big[0][3]),
            impact="저장 크기 기준 추정치입니다(_source 압축 후). 큰 문서는 _source 를 요청하지 않는 검색에서도 "
                   "비용을 올리고, 하이라이팅·근접 검색을 특히 느리게 만듭니다.",
            recommend="문서 분할이 가능한 구조인지 검토합니다. 분할이 어렵다면 _source 압축(best_compression)과 "
                      "필요한 필드만 반환하는 방식(fields/_source filtering)을 적용합니다.",
            evidence=table(["index", "문서 수", "크기", "문서 평균"], [r[:4] for r in big[: ctx.t["top_n"]]]),
            refs=[D_GEN], source="indices_stats.json"))
    return out


RULES = [
    r_large_result_sets, r_large_documents,
    r_cluster_name, r_path_settings, r_discovery, r_jvm_diag_settings,
    r_docs_per_shard, r_master_heap_per_index, r_mapping_heap_overhead,
    r_empty_indices, r_total_shards_per_node,
    r_index_buffer, r_open_contexts, r_search_timeout, r_replica_throughput,
    r_store_preload, r_remote_storage,
    r_codec, r_source_mode, r_dynamic_mapping,
    r_vector_memory, r_vector_quantization, r_vector_segments,
]
