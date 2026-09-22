# -*- coding: utf-8 -*-
"""샤드 / 인덱스 레벨 판정 룰."""

import collections

from ..model import Finding, Severity, table
from ..util import dig, fmt_bytes, fmt_ms, fmt_num, parse_bytes, pct, num

CAT = "샤드·인덱스"
DOC_SIZE = ("샤드 사이징 가이드",
            "https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards")
DOC_MAPPING = ("매핑 폭증 방지",
               "https://www.elastic.co/docs/manage-data/data-store/mapping")

GB = 1024 ** 3


def _explicit_index_setting(ctx, index, key):
    """settings.json 의 settings 섹션(명시 설정)만 조회. defaults 는 보지 않는다."""
    from ..context import _flat_get
    return _flat_get(dig(ctx.index_settings, index, "settings") or {}, key)


def _is_snapshot_backed(ctx, index):
    """searchable snapshot(mounted) 인덱스 여부. 이들은 replica 0 이 정상 설계다."""
    return bool(ctx.index_setting(index, "index.store.snapshot.repository_name")
                or str(ctx.index_setting(index, "index.store.type") or "") == "snapshot")


def _primary_store(ctx, index):
    return num(ctx.indices_stats, index, "primaries", "store", "size_in_bytes")


def _total_store(ctx, index):
    return num(ctx.indices_stats, index, "total", "store", "size_in_bytes")


def r_shard_density(ctx):
    """노드당 샤드 밀도.

    'heap 1GB당 샤드 20개' 는 8.3 미만 버전의 공식 기준이다. 8.3 부터 샤드당 heap 오버헤드가 크게 줄어
    공식 문서가 이 기준을 폐기하고 '필드 매퍼 heap 산정(SHD-010)' 과 cluster.max_shards_per_node(CLU-015)
    로 대체했다. 따라서 8.3 이상에서는 판정하지 않고 현황만 표기한다.
    """
    counts = collections.Counter()
    for s in ctx.shards:
        node = s.get("node")
        if node:
            counts[node] += 1
    if not counts:
        return []
    legacy = ctx.version_tuple < (8, 3, 0)
    rows, bad = [], []
    for n in ctx.nodes:
        c = counts.get(n.name, 0)
        heap_gb = (n.heap_max or 0) / float(GB)
        per_gb = (c / heap_gb) if heap_gb else None
        rows.append([n.name, fmt_num(c), "%.1fGB" % heap_gb if heap_gb else "-",
                     "%.1f" % per_gb if per_gb else "-", ",".join(n.roles)])
        if legacy and per_gb is not None and per_gb >= ctx.t["shards_per_gb_heap_warn"]:
            bad.append((n.name, per_gb, c))
    ev = table(["node", "샤드 수", "heap", "샤드/heap GB", "roles"], rows)
    if not legacy:
        return [Finding("SHD-001", CAT, Severity.INFO, "노드당 샤드 수 현황",
                        observed="버전 %s 은 heap 1GB당 샤드 수 기준(8.3 미만 전용)이 적용되지 않습니다. "
                                 "샤드 한도는 CLU-015, heap 여유는 SHD-010 에서 판정합니다." % ctx.version,
                        evidence=ev, refs=[DOC_SIZE], source="indices.json / nodes_stats.json")]
    if not bad:
        return [Finding("SHD-001", CAT, Severity.OK, "노드당 샤드 밀도 정상",
                        observed="heap 1GB당 샤드 수가 %d개 미만입니다(8.3 미만 공식 기준)."
                                 % ctx.t["shards_per_gb_heap_warn"],
                        evidence=ev, source="indices.json / nodes_stats.json")]
    crit = [b for b in bad if b[1] >= ctx.t["shards_per_gb_heap_crit"]]
    return [Finding(
        "SHD-001", CAT, Severity.CRITICAL if crit else Severity.WARNING,
        "노드당 샤드 수 과다(8.3 미만 기준)",
        observed=", ".join("%s: %s개(heap GB당 %.1f)" % (n, fmt_num(c), p) for n, p, c in bad),
        impact="8.3 미만 버전은 샤드마다 heap 오버헤드가 상당해, heap 1GB당 20개를 넘으면 "
               "GC 압박과 마스터 부하가 커진다는 것이 공식 기준입니다.",
        recommend="롤오버 크기를 키워 인덱스 수를 줄이고, 소형 인덱스는 통합·shrink 합니다. "
                  "8.3 이상으로 업그레이드하면 샤드당 오버헤드 자체가 크게 줄어듭니다.",
        evidence=ev, affected=[b[0] for b in bad], refs=[DOC_SIZE],
        source="indices.json / nodes_stats.json")]


def r_shard_size(ctx):
    """primary 샤드 store >= shard_size_gb_crit → 치명(SHD-002), >= shard_size_gb_warn(공식 상한 50GB) → 주의(SHD-003)."""
    big, huge = [], []
    for s in ctx.shards:
        if (s.get("prirep") or "").lower() != "p" or ctx.is_partial_mount(s.get("index")):
            continue
        b = parse_bytes(s.get("store"))
        if not b:
            continue
        gb = b / float(GB)
        if gb >= ctx.t["shard_size_gb_crit"]:
            huge.append([s.get("index"), s.get("shard"), fmt_bytes(b), s.get("node")])
        elif gb >= ctx.t["shard_size_gb_warn"]:
            big.append([s.get("index"), s.get("shard"), fmt_bytes(b), s.get("node")])
    out = []
    if huge:
        out.append(Finding(
            "SHD-002", CAT, Severity.CRITICAL, "초대형 샤드 존재",
            observed="%dGB 이상 primary 샤드 %d개." % (ctx.t["shard_size_gb_crit"], len(huge)),
            impact="샤드 복구·재배치 시간이 길어져 노드 교체나 장애 복구가 수 시간 단위로 늘어납니다. "
                   "force-merge·스냅샷 복원도 함께 느려집니다.",
            recommend="해당 인덱스를 reindex 로 분할하거나, 롤오버 기준(max_primary_shard_size)을 "
                      "50GB 내외로 재설정합니다.",
            evidence=table(["index", "shard", "size", "node"], huge[: ctx.t["top_n"]]),
            refs=[DOC_SIZE], source="indices.json"))
    if big:
        out.append(Finding(
            "SHD-003", CAT, Severity.WARNING, "대형 샤드 존재",
            observed="%dGB 이상 primary 샤드 %d개." % (ctx.t["shard_size_gb_warn"], len(big)),
            impact="공식 권장 범위(샤드당 10~50GB)를 넘어 복구·재배치 비용이 큽니다.",
            recommend="롤오버 기준을 max_primary_shard_size 로 전환하는 것을 권장합니다.",
            evidence=table(["index", "shard", "size", "node"], big[: ctx.t["top_n"]]),
            refs=[DOC_SIZE], source="indices.json"))
    return out


def r_small_shards(ctx):
    """store < small_shard_mb 인 primary 중 사용자 인덱스 샤드 수 >= small_shard_count_warn 이고, 전체 primary 중 소형 비율 >= small_shard_ratio_warn → 주의. 시스템 인덱스는 사용자가 조정할 수 없어 판정 기준에서 제외."""
    small, total, user_small = 0, 0, 0
    rows = []
    per_index = collections.defaultdict(lambda: [0, 0])  # count, bytes
    for s in ctx.shards:
        if (s.get("prirep") or "").lower() != "p" or ctx.is_partial_mount(s.get("index")):
            continue
        b = parse_bytes(s.get("store")) or 0
        total += 1
        idx = s.get("index")
        per_index[idx][0] += 1
        per_index[idx][1] += b
        if b < ctx.t["small_shard_mb"] * 1024 * 1024:
            small += 1
            if not ctx.is_system_index(idx):
                user_small += 1
    if not total:
        return []
    ratio = small / float(total)
    # 시스템 인덱스(.kibana, .internal.alerts 등)는 사용자가 조정할 수 없으므로
    # 사용자 인덱스 기준으로 조치 필요 여부를 판단한다.
    if user_small < ctx.t["small_shard_count_warn"] or ratio < ctx.t["small_shard_ratio_warn"]:
        return []
    # 소형 샤드를 많이 만드는 인덱스 후보(샤드 여러 개인데 전체가 작은 인덱스)
    for idx, (cnt, byt) in per_index.items():
        if cnt >= 2 and byt < cnt * ctx.t["small_shard_mb"] * 1024 * 1024:
            rows.append([idx, cnt, fmt_bytes(byt), fmt_bytes(byt / cnt)])
    rows.sort(key=lambda r: -r[1])
    return [Finding(
        "SHD-004", CAT, Severity.WARNING, "소형 샤드 과다",
        observed="primary 샤드 %d개 중 %d개(%.0f%%)가 %dMB 미만이며, 이 중 사용자 인덱스가 %d개입니다."
                 % (total, small, ratio * 100, ctx.t["small_shard_mb"], user_small),
        impact="샤드 수만큼 고정 오버헤드(heap, 파일 핸들, 검색 fan-out)가 발생합니다. "
               "작은 샤드가 많으면 데이터 양에 비해 클러스터가 과도하게 무거워집니다.",
        recommend="인덱스당 primary 수를 1로 줄이거나(소형 인덱스), 롤오버 주기를 늘려 "
                  "샤드당 목표 크기(10~50GB)에 맞춥니다. 과거 인덱스는 shrink 후 force-merge 합니다.",
        evidence=table(["index", "primary 수", "총 크기", "샤드 평균"], rows[: ctx.t["top_n"]]),
        refs=[DOC_SIZE], source="indices.json")]


def r_replica_zero(ctx):
    """사용자 인덱스 중 number_of_replicas=0 이고 auto_expand_replicas 가 없으며 searchable snapshot 인덱스가 아닌 것 → 주의."""
    rows = []
    for name in ctx.indices_stats.keys():
        if ctx.is_system_index(name):
            continue
        rep = ctx.index_setting(name, "index.number_of_replicas")
        auto = ctx.index_setting(name, "index.auto_expand_replicas")
        if _is_snapshot_backed(ctx, name):
            continue        # 스냅샷이 원본이므로 replica 0 이 정상
        if str(rep) == "0" and (not auto or str(auto).lower() == "false"):
            rows.append([name, fmt_bytes(_primary_store(ctx, name)),
                         fmt_num(dig(ctx.indices_stats, name, "primaries", "docs", "count"))])
    if not rows:
        return []
    rows.sort(key=lambda r: -(parse_bytes(r[1]) or 0))
    return [Finding(
        "IDX-001", CAT, Severity.WARNING, "replica 0 인덱스 존재",
        observed="replica 가 0인 사용자 인덱스 %d개." % len(rows),
        impact="노드 1대만 빠져도 해당 인덱스는 즉시 red 가 되고, 디스크 장애 시 데이터가 유실됩니다. "
               "또한 검색 부하를 분산할 수 없습니다.",
        recommend="운영 데이터라면 replica 1 이상을 권장합니다. 의도적으로 0으로 둔 재색인 가능 데이터라면 "
                  "복구 절차가 문서화되어 있는지 확인합니다.",
        evidence=table(["index", "primary 크기", "문서 수"], rows[: ctx.t["top_n"]]),
        source="settings.json / indices_stats.json")]


def r_replica_unassignable(ctx):
    """number_of_replicas > (데이터 노드 수 − 1) → 치명(영구 미할당). auto_expand_replicas 인덱스는 제외. tier 별 노드 수는 보지 않으므로 보수적(미탐 가능, 오탐 없음) 판정이다."""
    data_nodes = len(ctx.data_nodes) or len(ctx.nodes)
    rows = []
    for name in ctx.index_settings.keys():
        auto = ctx.index_setting(name, "index.auto_expand_replicas")
        if auto and str(auto).lower() != "false":
            continue        # 노드 수에 맞춰 자동 조정되므로 초과가 발생하지 않는다
        rep = ctx.index_setting(name, "index.number_of_replicas")
        try:
            rep = int(rep)
        except (TypeError, ValueError):
            continue
        if rep > 0 and rep > data_nodes - 1:
            rows.append([name, rep, data_nodes])
    if not rows:
        return []
    return [Finding(
        "IDX-002", CAT, Severity.CRITICAL, "replica 수가 데이터 노드 수를 초과",
        observed="데이터 노드 %d대인데 replica 가 더 큰 인덱스 %d개." % (data_nodes, len(rows)),
        impact="같은 샤드의 복제본은 같은 노드에 둘 수 없으므로, 초과분은 영구 미할당으로 남아 "
               "클러스터가 계속 yellow 입니다.",
        recommend="replica 를 (데이터 노드 수 - 1) 이하로 조정하거나 노드를 증설합니다.",
        evidence=table(["index", "replicas", "데이터 노드"], rows[: ctx.t["top_n"]]),
        source="settings.json")]


def r_deleted_docs(ctx):
    """primary store >= 1GB 인 인덱스에서 deleted / (docs + deleted) >= deleted_docs_ratio_warn → 주의."""
    rows = []
    for name, st in ctx.indices_stats.items():
        if ctx.is_searchable_snapshot(name):
            continue
        docs = num(st, "primaries", "docs", "count")
        dele = num(st, "primaries", "docs", "deleted")
        size = num(st, "primaries", "store", "size_in_bytes")
        if docs + dele == 0 or size < GB:
            continue
        r = dele / float(docs + dele)
        if r >= ctx.t["deleted_docs_ratio_warn"]:
            rows.append([name, fmt_num(docs), fmt_num(dele), "%.0f%%" % (r * 100), fmt_bytes(size)])
    if not rows:
        return []
    rows.sort(key=lambda r: -float(r[3].rstrip("%")))
    return [Finding(
        "IDX-003", CAT, Severity.WARNING, "삭제 문서 비율 높음",
        observed="삭제 문서 비율 %d%% 이상 인덱스 %d개." % (ctx.t["deleted_docs_ratio_warn"] * 100, len(rows)),
        impact="삭제·업데이트된 문서는 merge 전까지 세그먼트에 남아 디스크와 검색 비용을 차지합니다. "
               "빈번한 업데이트 패턴에서 저장 공간이 실제 데이터의 몇 배가 되기도 합니다.",
        recommend="쓰기가 끝난 인덱스는 force-merge(only_expunge_deletes 또는 max_num_segments=1)를 "
                  "저부하 시간대에 수행합니다. 진행 중인 인덱스에 대한 force-merge 는 권장하지 않습니다.",
        evidence=table(["index", "문서", "삭제", "비율", "크기"], rows[: ctx.t["top_n"]]),
        source="indices_stats.json")]


def r_segments(ctx):
    """primary 세그먼트 수 / primary 샤드 수 >= segments_per_shard_warn 이고 primary store > 100MB → 주의."""
    rows = []
    for name, st in ctx.indices_stats.items():
        if ctx.is_searchable_snapshot(name):
            continue
        seg = num(st, "primaries", "segments", "count")
        shards = ctx.primary_count(name) or 1
        per = seg / float(shards)
        size = num(st, "primaries", "store", "size_in_bytes")
        if per >= ctx.t["segments_per_shard_warn"] and size > 100 * 1024 * 1024:
            rows.append([name, fmt_num(seg), shards, "%.0f" % per, fmt_bytes(size)])
    if not rows:
        return []
    rows.sort(key=lambda r: -float(r[3]))
    return [Finding(
        "IDX-004", CAT, Severity.WARNING, "샤드당 세그먼트 수 과다",
        observed="샤드당 세그먼트 %d개 이상인 인덱스 %d개." % (ctx.t["segments_per_shard_warn"], len(rows)),
        impact="세그먼트가 많으면 검색 시 모든 세그먼트를 순회해야 하므로 지연이 커지고, "
               "파일 핸들과 메모리도 더 사용합니다.",
        recommend="refresh_interval 이 지나치게 짧지 않은지 확인하고, 쓰기가 종료된 인덱스는 "
                  "force-merge 로 세그먼트를 정리합니다.",
        evidence=table(["index", "세그먼트", "primary 수", "샤드당", "크기"], rows[: ctx.t["top_n"]]),
        source="indices_stats.json")]


def r_merge_throttle(ctx):
    """merges.total_throttled_time / merges.total_time >= merge_throttle_ratio_warn 이고 throttled 누적 > 60초 → 주의."""
    rows = []
    for name, st in ctx.indices_stats.items():
        mt = num(st, "total", "merges", "total_time_in_millis")
        th = num(st, "total", "merges", "total_throttled_time_in_millis")
        if mt and th / float(mt) >= ctx.t["merge_throttle_ratio_warn"] and th > 60000:
            rows.append([name, fmt_ms(mt), fmt_ms(th), "%.0f%%" % (th / float(mt) * 100)])
    if not rows:
        return []
    rows.sort(key=lambda r: -float(r[3].rstrip("%")))
    return [Finding(
        "IDX-005", CAT, Severity.WARNING, "merge throttling 관측",
        observed="merge 시간 대비 throttle 비중이 큰 인덱스 %d개." % len(rows),
        impact="색인 속도가 merge(디스크 I/O)를 앞질러 ES 가 색인을 억제하고 있다는 뜻입니다. "
               "스토리지 대역폭이 병목일 가능성이 큽니다.",
        recommend="디스크를 SSD/NVMe 로 교체하거나, indices.store.throttle 관련 기본값을 유지한 채 "
                  "색인 속도·샤드 분산을 조정합니다. 회전 디스크라면 노드당 샤드 수도 줄입니다.",
        evidence=table(["index", "merge 시간", "throttle 시간", "비중"], rows[: ctx.t["top_n"]]),
        source="indices_stats.json")]


def r_search_latency(ctx):
    """query_total >= min_query_total_for_latency 인 인덱스의 평균 query 지연 = query_time / query_total. >= search_latency_ms_crit → 치명, >= warn → 주의(PERF-001). 문서당 평균 색인 시간 = index_time / index_total 에 대해 index_latency_ms_crit / warn 으로 동일 판정(PERF-002). 누적 평균이며 p99 가 아니다."""
    rows_slow, rows_idx = [], []
    for name, st in ctx.indices_stats.items():
        qt = num(st, "total", "search", "query_total")
        qm = num(st, "total", "search", "query_time_in_millis")
        if qt >= ctx.t["min_query_total_for_latency"]:
            avg = qm / float(qt)
            if avg >= ctx.t["search_latency_ms_warn"]:
                rows_slow.append([name, fmt_num(qt), "%.1fms" % avg,
                                  fmt_ms(dig(st, "total", "search", "fetch_time_in_millis")),
                                  fmt_bytes(dig(st, "total", "store", "size_in_bytes")), avg])
        it = num(st, "total", "indexing", "index_total")
        im = num(st, "total", "indexing", "index_time_in_millis")
        if it >= ctx.t["min_query_total_for_latency"]:
            avg_i = im / float(it)
            if avg_i >= ctx.t["index_latency_ms_warn"]:
                rows_idx.append([name, fmt_num(it), "%.1fms" % avg_i,
                                 fmt_num(dig(st, "total", "indexing", "index_failed")), avg_i])
    out = []
    if rows_slow:
        rows_slow.sort(key=lambda r: -r[5])
        crit = [r for r in rows_slow if r[5] >= ctx.t["search_latency_ms_crit"]]
        out.append(Finding(
            "PERF-001", CAT, Severity.CRITICAL if crit else Severity.WARNING,
            "검색 평균 지연 높은 인덱스",
            observed="평균 query 지연 %dms 이상 인덱스 %d개(최대 %s)."
                     % (ctx.t["search_latency_ms_warn"], len(rows_slow), rows_slow[0][2]),
            impact="누적 통계 기준 평균값입니다. 특정 인덱스의 쿼리 비용이 구조적으로 높다는 신호이며, "
                   "p99 는 이보다 훨씬 클 수 있습니다.",
            recommend="해당 인덱스의 쿼리 패턴을 확인합니다. wildcard/regex/script 사용, "
                      "과도한 aggregation, 샤드 수 과다(작은 샤드에 대한 fan-out), "
                      "docvalue 미사용 정렬이 주요 원인입니다. hot threads 결과와 대조합니다.",
            evidence=table(["index", "query 수", "평균 query", "fetch 누적", "크기"],
                           [r[:5] for r in rows_slow[: ctx.t["top_n"]]]),
            source="indices_stats.json"))
    if rows_idx:
        rows_idx.sort(key=lambda r: -r[4])
        out.append(Finding(
            "PERF-002", CAT,
            Severity.CRITICAL if rows_idx[0][4] >= ctx.t["index_latency_ms_crit"] else Severity.WARNING,
            "색인 평균 지연 높은 인덱스",
            observed="문서당 평균 색인 시간이 %dms 이상인 인덱스 %d개."
                     % (ctx.t["index_latency_ms_warn"], len(rows_idx)),
            impact="색인 지연은 수집 파이프라인 backpressure 로 전파되어 데이터 유입 지연을 만듭니다.",
            recommend="매핑 복잡도(필드 수, dynamic mapping, ingest pipeline), refresh_interval, "
                      "디스크 성능, replica 수를 순서대로 확인합니다.",
            evidence=table(["index", "색인 문서 수", "문서당 평균", "실패"],
                           [r[:4] for r in rows_idx[: ctx.t["top_n"]]]),
            source="indices_stats.json"))
    return out


def r_index_failures(ctx):
    """indexing.index_failed 또는 search.query_failure > 0 인 인덱스. 사용자 인덱스가 포함되면 주의, 시스템 인덱스뿐이면 참고."""
    rows, user_rows = [], []
    for name, st in ctx.indices_stats.items():
        failed = num(st, "total", "indexing", "index_failed")
        qf = num(st, "total", "search", "query_failure")
        if failed or qf:
            row = [name, fmt_num(failed), fmt_num(qf),
                   fmt_num(dig(st, "total", "indexing", "index_total")), failed + qf]
            rows.append(row)
            if not ctx.is_system_index(name):
                user_rows.append(row)
    if not rows:
        return []
    rows.sort(key=lambda r: -r[4])
    return [Finding(
        "IDX-006", CAT,
        Severity.WARNING if user_rows else Severity.INFO,
        "색인/검색 실패 카운터 존재" + ("" if user_rows else " (시스템 인덱스만 해당)"),
        observed="실패 카운터가 0이 아닌 인덱스 %d개." % len(rows),
        impact="매핑 충돌(strict/타입 불일치), 문서 크기 초과, 버전 충돌 등이 누적된 상태입니다. 버전 충돌(op_type=create 중복, "
               "동시 갱신)은 정상 운영에서도 늘어나므로 건수만으로 문제라고 단정할 수 없습니다. "
               "매핑 오류라면 수집 측에서 재시도하지 않는 한 데이터 누락입니다.",
        recommend="해당 인덱스의 매핑과 수집 파이프라인 에러 로그를 확인합니다. "
                  "누적값이므로 발생 시점은 별도 확인이 필요합니다.",
        evidence=table(["index", "index_failed", "query_failure", "index_total"],
                       [r[:4] for r in rows[: ctx.t["top_n"]]]),
        source="indices_stats.json")]


def r_mapping_limits(ctx):
    """사용자 인덱스의 mapping.total_fields.limit > 1000(기본값) → 주의(MAP-001). cluster_stats 전체 필드 수 > 100,000 → 주의(MAP-002)."""
    rows, ignored = [], 0
    for name in ctx.index_settings.keys():
        if ctx.is_system_index(name):
            continue        # Kibana/보안 등 시스템 인덱스는 제품이 설정한 값이라 조치 대상이 아니다
        lim = ctx.index_setting(name, "index.mapping.total_fields.limit")
        if lim is None:
            continue
        try:
            lim = int(lim)
        except (TypeError, ValueError):
            continue
        if lim > 1000:
            ign = str(ctx.index_setting(name, "index.mapping.total_fields.ignore_dynamic_beyond_limit")).lower() == "true"
            ignored += 1 if ign else 0
            rows.append([name, fmt_num(lim), "true" if ign else "false"])
    total_fields = dig(ctx.cluster_stats, "indices", "mappings", "total_field_count")
    out = []
    if rows:
        out.append(Finding(
            "MAP-001", CAT, Severity.INFO if ignored == len(rows) else Severity.WARNING,
            "매핑 필드 한도 상향 인덱스",
            observed="total_fields.limit 을 기본값(1000)보다 올린 인덱스 %d개(그중 ignore_dynamic_beyond_limit=true %d개)."
                     % (len(rows), ignored),
            impact="Elastic 통합(Fleet)·내장 logs 템플릿은 한도를 올리거나 ignore_dynamic_beyond_limit 를 켜 두는 경우가 많습니다. 이 설정이 true 면 한도를 넘는 "
                   "동적 필드는 매핑되지 않고 무시되어 색인이 실패하지 않습니다. 해당 설정 없이 한도만 올렸다면 매핑 폭증의 신호입니다. "
                   "실제 heap 영향은 SHD-010(매핑 heap 오버헤드)에서 판정합니다.",
            recommend="동적 필드가 무한 증식하는 구조인지 확인하고, 필요 시 flattened 타입이나 "
                      "dynamic:false + 명시 매핑으로 전환합니다.",
            evidence=table(["index", "total_fields.limit", "ignore_dynamic_beyond_limit"],
                           sorted(rows, key=lambda r: r[2])[: ctx.t["top_n"]]),
            refs=[DOC_MAPPING], source="settings.json"))
    if total_fields and total_fields > 100000:
        out.append(Finding(
            "MAP-002", CAT, Severity.INFO, "클러스터 전체 필드 수",
            observed="전체 매핑 필드 수 %s개." % fmt_num(total_fields),
            impact="인덱스별 필드 수의 단순 합계라 인덱스가 많으면 자연히 커집니다(공식 수치 기준 없음). "
                   "실제 부담은 중복 제거된 매핑 크기와 노드 heap 대비 비중(SHD-010), 마스터 부하(CLU-005)로 판단합니다.",
            recommend="유사 인덱스의 매핑 통합, 미사용 필드 제거, 템플릿 정리를 검토합니다.",
            refs=[DOC_MAPPING], source="cluster_stats.json"))
    return out


def r_refresh_interval(ctx):
    """refresh 주기.

    refresh_interval 을 명시하지 않은 인덱스는 search idle 동작이 적용된다.
    index.search.idle.after(기본 30s) 동안 검색이 없던 샤드는 주기적 refresh 를 건너뛰므로,
    '미지정 = 매초 refresh' 가 아니다. 따라서 명시적으로 1s 이하로 지정한 인덱스만 판정한다.
    """
    rows = []
    for name, st in ctx.indices_stats.items():
        if ctx.is_system_index(name):
            continue
        it = num(st, "total", "indexing", "index_total")
        if it < ctx.t["heavy_index_docs"]:
            continue
        explicit = _explicit_index_setting(ctx, name, "index.refresh_interval")
        if explicit is None:
            continue
        from ..util import parse_time_ms
        ms = parse_time_ms(explicit)
        if ms is not None and 0 < ms <= 1000:
            rows.append([name, str(explicit), fmt_num(it),
                         fmt_num(dig(st, "total", "refresh", "total")),
                         fmt_ms(dig(st, "total", "refresh", "total_time_in_millis"))])
    if not rows:
        return []
    return [Finding(
        "IDX-007", CAT, Severity.INFO, "대량 색인 인덱스에 refresh_interval 1초 이하 명시",
        observed="refresh_interval 을 1초 이하로 명시한 대량 색인 인덱스 %d개." % len(rows),
        impact="명시적으로 지정하면 search idle 최적화가 꺼져 검색이 없어도 매 주기마다 세그먼트가 "
               "생성됩니다. merge 부담과 CPU 사용이 늘어납니다.",
        recommend="검색 실시간성 요구가 없다면 설정을 제거(search idle 활용)하거나 30s 등으로 늘립니다. "
                  "초기 대량 적재 중에는 -1 로 끄는 것이 공식 권장입니다.",
        evidence=table(["index", "refresh_interval", "색인 문서", "refresh 횟수", "refresh 누적시간"],
                       rows[: ctx.t["top_n"]]),
        source="settings.json / indices_stats.json")]


def r_read_only_blocks(ctx):
    """인덱스 쓰기 차단을 '정상 차단' 과 '문제 차단' 으로 구분한다.

    정상(판정 안 함, 건수만 참고): searchable snapshot 마운트 인덱스, 롤오버가 끝난 인덱스
    (데이터 스트림의 과거 백킹 인덱스·쓰기 대상이 아닌 alias 멤버·indexing_complete=true).
    ILM 의 readonly·shrink·forcemerge·searchable_snapshot 단계는 롤오버 후 인덱스에 write 차단을 거는 것이 정상 동작이다.
    문제(치명, IDX-008): index.blocks.read_only_allow_delete=true(대개 flood stage 흔적, 모든 인덱스 대상),
    또는 현재 쓰기 대상(데이터 스트림 write index / alias write index)에 write·read_only 차단.
    확인 필요(참고, IDX-011): 데이터 스트림·alias 에 속하지 않는 단독 인덱스의 write·read_only 차단(의도적 보관일 수 있음).
    """
    targets = ctx.write_targets()
    bad, check, normal = [], [], collections.Counter()
    for name in ctx.index_settings.keys():
        flags = [k for k in ("index.blocks.read_only_allow_delete", "index.blocks.read_only",
                             "index.blocks.write") if str(ctx.index_setting(name, k)).lower() == "true"]
        if not flags:
            continue
        if "index.blocks.read_only_allow_delete" in flags:
            bad.append([name, "read_only_allow_delete", "flood stage 흔적(모든 인덱스 대상)"])
            continue
        if ctx.is_searchable_snapshot(name):
            normal["searchable snapshot"] += 1
            continue
        if name in targets:
            bad.append([name, ", ".join(f.split(".")[-1] for f in flags), "현재 쓰기 대상"])
            continue
        if ctx.rolled_over(name):
            normal["롤오버 완료"] += 1
            continue
        if ctx.is_system_index(name):
            normal["시스템 인덱스"] += 1
            continue
        check.append([name, ", ".join(f.split(".")[-1] for f in flags)])
    out = []
    note = (" 정상 차단으로 제외: %s." % ", ".join("%s %d개" % kv for kv in normal.items())) if normal else ""
    if bad:
        out.append(Finding(
            "IDX-008", CAT, Severity.CRITICAL, "쓰기 대상 인덱스 또는 flood stage 쓰기 차단",
            observed="문제가 되는 쓰기 차단 %d건.%s" % (len(bad), note),
            impact="현재 쓰기 대상에 차단이 걸리면 데이터 스트림·alias 로 들어오는 색인이 실패합니다. "
                   "read_only_allow_delete 는 디스크 flood stage 에서 자동으로 걸리는 차단입니다.",
            recommend="flood stage 흔적이면 디스크 여유를 먼저 확보합니다(8.x 이상은 여유 회복 시 자동 해제). "
                      "쓰기 대상의 차단이면 설정 경위를 확인한 뒤 null 로 해제하거나 롤오버합니다.",
            evidence=table(["index", "차단", "구분"], bad[: ctx.t["top_n"]]),
            source="settings.json / data_stream.json / alias.json"))
    if check:
        out.append(Finding(
            "IDX-011", CAT, Severity.INFO, "단독 인덱스의 쓰기 차단(의도 확인)",
            observed="데이터 스트림·alias 에 속하지 않은 인덱스의 쓰기 차단 %d건.%s" % (len(check), note),
            impact="보관 목적의 의도적 차단일 수 있습니다. 수집 대상이 이 인덱스로 직접 쓰고 있다면 색인이 실패합니다.",
            recommend="해당 인덱스로 쓰는 수집 경로가 있는지 확인합니다.",
            evidence=table(["index", "차단"], check[: ctx.t["top_n"]]),
            source="settings.json / alias.json"))
    if not bad and not check and normal:
        out.append(Finding(
            "IDX-008", CAT, Severity.OK, "쓰기 차단은 모두 정상 동작",
            observed="쓰기 차단 인덱스는 모두 롤오버 완료·searchable snapshot 등 정상 차단입니다.%s" % note,
            source="settings.json / data_stream.json / alias.json"))
    return out


def r_tier_preference(ctx):
    """인덱스가 요구하는 데이터 tier 가 실제 노드에 존재하는지."""
    available = set()
    for n in ctx.nodes:
        for r in n.roles:
            if r.startswith("data_"):
                available.add(r)
        if "data" in n.roles:
            available.update({"data_content", "data_hot", "data_warm", "data_cold"})
    if not available:
        return []
    rows = []
    for name in ctx.index_settings.keys():
        pref = ctx.index_setting(name, "index.routing.allocation.include._tier_preference")
        if not pref:
            continue
        tiers = [t.strip() for t in str(pref).split(",") if t.strip()]
        if tiers and not any(t in available for t in tiers):
            rows.append([name, pref, ", ".join(sorted(available))])
    if not rows:
        return []
    return [Finding(
        "IDX-009", CAT, Severity.CRITICAL, "존재하지 않는 data tier 를 요구하는 인덱스",
        observed="tier preference 를 만족하는 노드가 없는 인덱스 %d개." % len(rows),
        impact="해당 인덱스의 샤드는 할당될 수 없어 yellow/red 로 남습니다. "
               "ILM 이 warm/cold 로 이동시키려 할 때도 실패합니다.",
        recommend="해당 tier 역할의 노드를 추가하거나, 인덱스/ILM 정책의 tier 설정을 조정합니다.",
        evidence=table(["index", "요구 tier", "보유 tier"], rows[: ctx.t["top_n"]]),
        source="settings.json / nodes.json")]


def r_index_count(ctx):
    """샤드당 평균 크기(store / shards) < 200MB 이고 샤드 >= 300 이며 전체 store > 50GB → 주의. 그 외에는 규모 요약만 참고로 표기."""
    n_idx = dig(ctx.cluster_stats, "indices", "count") or len(ctx.indices_stats)
    shards = dig(ctx.cluster_stats, "indices", "shards", "total") or ctx.health.get("active_shards")
    store = dig(ctx.cluster_stats, "indices", "store", "size_in_bytes")
    docs = dig(ctx.cluster_stats, "indices", "docs", "count")
    avg = (store / shards) if (store and shards) else None
    ev = table(["항목", "값"],
               [["인덱스 수", fmt_num(n_idx)],
                ["샤드 수(전체)", fmt_num(shards)],
                ["문서 수", fmt_num(docs)],
                ["저장 용량", fmt_bytes(store)],
                ["샤드당 평균 크기", fmt_bytes(avg)]])
    if (avg is not None and avg < 200 * 1024 * 1024 and shards and shards >= 300
            and store and store > 50 * GB):
        return [Finding(
            "SHD-005", CAT, Severity.WARNING, "샤드당 평균 크기 과소",
            observed="샤드당 평균 %s (샤드 %s개, 총 %s)." % (fmt_bytes(avg), fmt_num(shards), fmt_bytes(store)),
            impact="데이터 양 대비 샤드가 지나치게 많아 오버헤드가 데이터보다 커지는 구간입니다.",
            recommend="인덱스 통합과 primary 수 축소로 샤드당 10~50GB 를 목표로 재설계합니다.",
            evidence=ev, refs=[DOC_SIZE], source="cluster_stats.json")]
    return [Finding("SHD-005", CAT, Severity.INFO, "인덱스/샤드 규모 요약",
                    observed="인덱스 %s개, 샤드 %s개, 저장 %s." % (fmt_num(n_idx), fmt_num(shards),
                                                          fmt_bytes(store)),
                    evidence=ev, source="cluster_stats.json")]




def r_shard_balance(ctx):
    """같은 tier 안에서 노드 간 샤드 수 편차가 평균의 25% 이상이면 주의.

    tier 마다 보관 데이터와 노드 수가 달라 tier 간 샤드 수 차이는 정상이므로 비교하지 않는다.
    """
    counts = collections.Counter(s.get("node") for s in ctx.shards if s.get("node"))
    rows, flagged = [], []
    for tier, nodes in ctx.data_tiers().items():
        vals = [(n.name, counts.get(n.name, 0)) for n in nodes]
        for name, c in vals:
            rows.append([tier, name, c])
        if len(vals) < 2:
            continue
        nums = [c for _, c in vals]
        avg = sum(nums) / float(len(nums))
        if avg and (max(nums) - min(nums)) / avg >= 0.25:
            flagged.append("%s tier 최대 %d / 최소 %d (평균 %.1f)" % (tier, max(nums), min(nums), avg))
    if not flagged:
        return []
    return [Finding(
        "SHD-006", CAT, Severity.WARNING, "같은 tier 노드 간 샤드 수 불균형",
        observed=" / ".join(flagged),
        impact="같은 tier 안에서 샤드가 몰린 노드가 먼저 CPU·heap·디스크 한계에 도달해 그 tier 의 처리 상한이 됩니다.",
        recommend="allocation filter(exclude/require), total_shards_per_node 제약, desired balance 수렴 상태(HOT-003)를 확인합니다.",
        evidence=table(["tier", "node", "샤드 수"], rows),
        source="indices.json / nodes.json")]


def r_data_stream_health(ctx):
    """data stream status 가 RED → 치명, YELLOW → 주의."""
    bad = []
    for ds in ctx.data_streams or []:
        st = (ds.get("status") or "").upper()
        if st in ("RED", "YELLOW"):
            bad.append([ds.get("name"), st, ds.get("generation"),
                        len(ds.get("indices") or []), ds.get("ilm_policy") or "-"])
    if not bad:
        return []
    red = [b for b in bad if b[1] == "RED"]
    return [Finding(
        "IDX-010", CAT, Severity.CRITICAL if red else Severity.WARNING,
        "데이터 스트림 상태 이상",
        observed="RED %d개 / YELLOW %d개." % (len(red), len(bad) - len(red)),
        impact="백킹 인덱스의 샤드가 정상 할당되지 않은 상태로, 수집 중인 데이터 스트림이면 "
               "쓰기 실패 또는 복제 부재로 이어집니다.",
        recommend="해당 백킹 인덱스의 미할당 사유를 allocation explain 으로 확인합니다.",
        evidence=table(["data_stream", "status", "generation", "백킹 인덱스", "ILM"], bad[: ctx.t["top_n"]]),
        source="commercial/data_stream.json")]


def r_cache_efficiency(ctx):
    """query(=shard request) cache / request cache 효율."""
    qc_hit = num(ctx.indices_stats_all, "total", "query_cache", "hit_count")
    qc_miss = num(ctx.indices_stats_all, "total", "query_cache", "miss_count")
    qc_evict = num(ctx.indices_stats_all, "total", "query_cache", "evictions")
    rc_hit = num(ctx.indices_stats_all, "total", "request_cache", "hit_count")
    rc_miss = num(ctx.indices_stats_all, "total", "request_cache", "miss_count")
    rc_evict = num(ctx.indices_stats_all, "total", "request_cache", "evictions")
    if qc_hit + qc_miss < 10000 and rc_hit + rc_miss < 10000:
        return []
    qc_rate = pct(qc_hit, qc_hit + qc_miss)
    rc_rate = pct(rc_hit, rc_hit + rc_miss)
    ev = table(["캐시", "hit", "miss", "hit율", "eviction"],
               [["query cache", fmt_num(qc_hit), fmt_num(qc_miss),
                 "%.1f%%" % qc_rate if qc_rate is not None else "-", fmt_num(qc_evict)],
                ["request cache", fmt_num(rc_hit), fmt_num(rc_miss),
                 "%.1f%%" % rc_rate if rc_rate is not None else "-", fmt_num(rc_evict)]])
    warn = (qc_rate is not None and qc_rate < 20 and qc_evict > qc_hit) or \
           (rc_rate is not None and rc_rate < 20 and rc_evict > rc_hit)
    if not warn:
        return [Finding("PERF-003", CAT, Severity.INFO, "캐시 사용 현황",
                        observed="query cache hit율 %s, request cache hit율 %s."
                                 % ("%.1f%%" % qc_rate if qc_rate is not None else "-",
                                    "%.1f%%" % rc_rate if rc_rate is not None else "-"),
                        evidence=ev, source="indices_stats.json")]
    return [Finding(
        "PERF-003", CAT, Severity.WARNING, "캐시 적중률 저조 + eviction 과다",
        observed="query cache hit율 %s / request cache hit율 %s, eviction 이 hit 보다 많습니다."
                 % ("%.1f%%" % qc_rate if qc_rate is not None else "-",
                    "%.1f%%" % rc_rate if rc_rate is not None else "-"),
        impact="캐시가 채워지자마자 밀려나는 상태로, 캐시 유지 비용만 쓰고 이득이 없습니다. "
               "쿼리에 now 같은 가변 값이 들어가거나 데이터가 계속 갱신될 때 발생합니다.",
        recommend="시간 범위를 now-15m/m 처럼 반올림해 캐시 키를 안정화하고, "
                  "캐시 크기(indices.queries.cache.size, indices.requests.cache.size)를 재검토합니다.",
        evidence=ev, source="indices_stats.json")]


RULES = [
    r_shard_density, r_shard_balance, r_data_stream_health, r_cache_efficiency, r_shard_size, r_small_shards, r_replica_zero,
    r_replica_unassignable, r_deleted_docs, r_segments, r_merge_throttle,
    r_search_latency, r_index_failures, r_mapping_limits, r_refresh_interval,
    r_read_only_blocks, r_tier_preference, r_index_count,
]
