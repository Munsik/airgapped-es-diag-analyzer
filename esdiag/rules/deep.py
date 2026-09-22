# -*- coding: utf-8 -*-
"""번들에 있으나 이전에 읽지 않던 파일 기반 판정.

mapping.json(실제 인덱스 매핑), ilm_policies.json, cluster_state.json(voting exclusions),
nodes_shutdown_status.json, shard_stores.json, remote_cluster_info.json,
searchable_snapshots_cache_stats.json, nodes_stats 의 script·ingest processors·discovery 섹션,
nodes.json 플러그인, ML trained model 배포, watcher, autoscaling, rollup.
"""

import collections

from ..model import Finding, Severity, table
from ..util import dicts, dig, fmt_bytes, fmt_ms, fmt_num, items, num, parse_bytes, strs

MAPC, OPS, CLU, PERF, VEC = "샤드·인덱스", "운영", "클러스터", "성능 기준", "벡터 검색"
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


# ------------------------------------------------------------------ 매핑
def _mappings(ctx):
    for name, summ in items(ctx.mapping_summary):
        if ctx.is_system_index(name) or not isinstance(summ, dict):
            continue
        yield name, summ


def r_mapping_limits_actual(ctx):
    """mapping.json 의 실제 매핑으로 인덱스별 필드 수를 공식 산정 방식(필드·object·multi-field·runtime 각 1개)으로 센다.

    필드 수 >= total_fields.limit × mapping_fields_near_limit_pct → 주의(MAP-004, ignore_dynamic_beyond_limit=true 면 참고).
    text 필드의 fielddata=true → 주의(MAP-005). nested 필드 수 >= nested_fields.limit × 80% → 주의(MAP-006).
    """
    near, fd_rows, nest_rows = [], [], []
    ignored = 0
    for name, m in _mappings(ctx):
        total, nested, fielddata = m["total"], m["nested"], m["fielddata"]
        try:
            limit = int(ctx.index_setting(name, "index.mapping.total_fields.limit") or 1000)
        except (TypeError, ValueError):
            limit = 1000
        if limit > 0 and total >= limit * ctx.t["mapping_fields_near_limit_pct"] / 100.0:
            ign = str(ctx.index_setting(name, "index.mapping.total_fields.ignore_dynamic_beyond_limit")).lower() == "true"
            ignored += 1 if ign else 0
            near.append([name, fmt_num(total), fmt_num(limit), "%.0f%%" % (total * 100.0 / limit), "true" if ign else "false"])
        for f in fielddata:
            fd_rows.append([name, f])
        try:
            nlimit = int(ctx.index_setting(name, "index.mapping.nested_fields.limit") or 50)
        except (TypeError, ValueError):
            nlimit = 50
        if nlimit and nested >= nlimit * 0.8:
            nest_rows.append([name, nested, nlimit])
    out = []
    if near:
        near.sort(key=lambda r: -float(r[3].rstrip("%")))
        out.append(Finding(
            "MAP-004", MAPC, Severity.INFO if ignored == len(near) else Severity.WARNING,
            "필드 수가 매핑 한도에 근접한 인덱스",
            observed="필드 수가 total_fields.limit 의 %d%% 이상인 인덱스 %d개(그중 ignore_dynamic_beyond_limit=true %d개)."
                     % (ctx.t["mapping_fields_near_limit_pct"], len(near), ignored),
            impact="한도에 도달하면 새 필드가 들어오는 문서의 색인이 실패합니다. ignore_dynamic_beyond_limit=true 면 "
                   "한도를 넘는 동적 필드는 매핑되지 않고 무시되어 색인은 되지만, 그 필드로 검색·집계할 수 없습니다.",
            recommend="불필요한 동적 필드를 막고(dynamic:false 또는 dynamic_templates), 로그성 가변 필드는 flattened 로 모읍니다. "
                      "한도 상향은 heap·cluster state 비용을 늘리므로 마지막 수단입니다.",
            evidence=table(["index", "필드 수", "한도", "사용률", "ignore_dynamic_beyond_limit"], near[: ctx.t["top_n"]]),
            refs=[D_MAP], source="mapping.json / settings.json"))
    if fd_rows:
        out.append(Finding(
            "MAP-005", MAPC, Severity.WARNING, "text 필드에 fielddata 활성화",
            observed="fielddata=true 인 text 필드 %d개." % len(fd_rows),
            impact="text 필드의 fielddata 는 분석된 모든 토큰을 heap 에 올립니다. 대량 heap 을 쓰고 GC 압박과 "
                   "circuit breaker 발동의 흔한 원인입니다.",
            recommend="정렬·집계는 keyword 하위 필드(multi-field)로 하고 fielddata 는 끕니다.",
            evidence=table(["index", "field"], fd_rows[: ctx.t["top_n"]]),
            refs=[D_FD], source="mapping.json"))
    if nest_rows:
        out.append(Finding(
            "MAP-006", MAPC, Severity.WARNING, "nested 필드 수가 한도에 근접",
            observed="nested 필드 수가 nested_fields.limit 의 80%% 이상인 인덱스 %d개." % len(nest_rows),
            impact="nested 객체마다 숨은 Lucene 문서가 만들어져 저장·검색 비용이 큽니다. 한도에 도달하면 매핑 변경이 거부됩니다.",
            recommend="nested 가 꼭 필요한 관계인지 검토하고, 평탄화(flattened·keyword 배열)나 문서 분리를 고려합니다.",
            evidence=table(["index", "nested 필드", "한도"], nest_rows[: ctx.t["top_n"]]),
            refs=[D_MAP], source="mapping.json / settings.json"))
    return out


def r_vector_mapping_actual(ctx):
    """실제 인덱스 매핑에서 비양자화(hnsw·flat)를 명시한 고차원 float dense_vector 를 찾는다(VEC-005, 주의).

    8.14 미만에서는 index_options 미지정도 비양자화이므로 포함한다. 템플릿 기준 판정(VEC-002)을 실제 인덱스로 보완한다.
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
                rows.append([name, field, dims, itype or "(미지정)"])
    if not rows:
        return []
    return [Finding(
        "VEC-005", VEC, Severity.WARNING, "실제 인덱스의 고차원 float 벡터가 비양자화",
        observed="%d차원 이상 float dense_vector 필드 %d개가 양자화 없이 색인되어 있습니다."
                 % (ctx.t["vector_dim_quantize_warn"], len(rows)),
        impact="양자화(int8·int4·bbq)하면 HNSW 탐색 메모리가 약 4배·8배·최대 32배 줄어듭니다. 메모리가 부족하면 검색이 디스크를 읽어 급격히 느려집니다.",
        recommend="템플릿의 index_options 를 양자화 타입으로 바꾸고 재색인합니다. 재현율을 측정해 수준을 고릅니다.",
        evidence=table(["index", "field", "dims", "index_options.type"], rows[: ctx.t["top_n"]]),
        refs=[D_KNN], source="mapping.json")]


# ------------------------------------------------------------------ ILM 정책
def r_ilm_policies(ctx):
    """사용자 인덱스가 쓰는 ILM 정책의 롤오버·삭제 구성.

    hot 롤오버에 max_primary_shard_size(또는 max_size)가 없으면 주의(ILM-004): 공식 권장은 샤드 크기 기준 롤오버이며,
    max_age 단독이면 수집량에 따라 작은 인덱스가 쌓인다(OVS-002 의 원인). max_primary_shard_size > 50GB 면 주의(ILM-005).
    delete 단계가 없으면 참고(ILM-006, 보존 기간 무제한). Elastic 관리 정책(_meta.managed=true)은 표에 표시만 한다.
    """
    no_size, too_big, no_delete = [], [], []
    for pname, body in items(ctx.ilm_policies):
        if not isinstance(body, dict):
            continue
        users = [i for i in strs(dig(body, "in_use_by", "indices")) if not ctx.is_system_index(i)]
        users += [d for d in strs(dig(body, "in_use_by", "data_streams")) if not d.startswith(".")]
        if not users:
            continue
        managed = str(dig(body, "policy", "_meta", "managed")).lower() == "true"
        phases = dig(body, "policy", "phases", default={}) or {}
        ro = dig(phases, "hot", "actions", "rollover")
        label = pname + (" (Elastic 관리)" if managed else "")
        if isinstance(ro, dict):
            size = ro.get("max_primary_shard_size") or ro.get("max_size")
            if not size:
                no_size.append([label, ", ".join("%s=%s" % kv for kv in ro.items()), len(users)])
            else:
                b = parse_bytes(ro.get("max_primary_shard_size"))
                if b and b > ctx.t["ilm_rollover_max_shard_gb"] * 1024 ** 3:
                    too_big.append([label, str(ro.get("max_primary_shard_size")), len(users)])
        if "delete" not in phases:
            no_delete.append([label, ", ".join(sorted(phases.keys())), len(users)])
    out = []
    if no_size:
        out.append(Finding(
            "ILM-004", OPS, Severity.WARNING, "크기 기준 없이 롤오버하는 ILM 정책",
            observed="사용자 인덱스가 쓰는 정책 중 롤오버에 max_primary_shard_size 가 없는 정책 %d개." % len(no_size),
            impact="max_age·max_docs 만으로 롤오버하면 수집량이 적은 데이터는 작은 인덱스가 계속 쌓이고(과다 샤딩), "
                   "수집량이 많으면 샤드가 권장 크기를 넘습니다. OVS-002(롤오버 과다)의 직접 원인인 경우가 많습니다.",
            recommend="rollover 에 max_primary_shard_size: 50gb 를 두고 max_age 는 보조 조건으로 둡니다.",
            evidence=table(["정책", "rollover 조건", "사용 인덱스·데이터 스트림 수"], no_size[: ctx.t["top_n"]]),
            refs=[D_ILM, D_SHARDS], source="ilm_policies.json"))
    if too_big:
        out.append(Finding(
            "ILM-005", OPS, Severity.WARNING, "롤오버 샤드 크기 기준이 권장 상한 초과",
            observed="max_primary_shard_size 가 %dGB 를 넘는 정책 %d개." % (ctx.t["ilm_rollover_max_shard_gb"], len(too_big)),
            impact="샤드가 공식 권장 상한(50GB)보다 커져 복구·재배치 시간이 길어집니다.",
            recommend="max_primary_shard_size 를 50gb 이하로 조정합니다.",
            evidence=table(["정책", "max_primary_shard_size", "사용 수"], too_big[: ctx.t["top_n"]]),
            refs=[D_ILM, D_SHARDS], source="ilm_policies.json"))
    if no_delete:
        out.append(Finding(
            "ILM-006", OPS, Severity.INFO, "삭제 단계가 없는 ILM 정책",
            observed="사용자 인덱스가 쓰는 정책 중 delete 단계가 없는 정책 %d개." % len(no_delete),
            impact="보존 기간이 무제한이라 디스크와 샤드 수가 계속 늘어납니다. 의도한 영구 보관이라면 문제없습니다.",
            recommend="보존 요건을 확인하고 delete 단계(min_age)를 둡니다. 장기 보관은 frozen tier·스냅샷으로 옮깁니다.",
            evidence=table(["정책", "단계", "사용 수"], no_delete[: ctx.t["top_n"]]),
            refs=[D_ILM], source="ilm_policies.json"))
    return out


# ------------------------------------------------------------------ 클러스터 조정·노드 종료·저장소
def r_voting_exclusions(ctx):
    """cluster_state 의 voting_config_exclusions 가 비어 있지 않으면 주의(CLU-022).

    마스터 후보를 제거·교체할 때 쓰는 임시 설정이다. 작업 후 지우지 않으면 해당 노드가 투표에서 계속 빠져 정족수 여유가 줄어든다.
    """
    ex = dicts(dig(ctx.cluster_state, "metadata", "cluster_coordination", "voting_config_exclusions"))
    if not ex:
        return []
    return [Finding(
        "CLU-022", CLU, Severity.WARNING, "voting config exclusion 잔존",
        observed="투표 구성에서 제외된 노드 %d개: %s" % (len(ex), ", ".join(str(x.get("node_name") or x.get("node_id")) for x in ex)),
        impact="제외된 마스터 후보는 투표에 참여하지 않습니다. 작업이 끝났는데 남아 있으면 정족수 여유가 줄어 "
               "마스터 노드 1대 장애에도 선출이 불가능해질 수 있습니다.",
        recommend="노드 제거·교체가 끝났다면 DELETE _cluster/voting_config_exclusions 로 지웁니다.",
        evidence=table(["node_id", "node_name"], [[x.get("node_id"), x.get("node_name")] for x in ex]),
        refs=[D_VOTE], source="cluster_state.json")]


def r_node_shutdown(ctx):
    """nodes_shutdown_status 의 종료 레코드. STALLED → 치명, IN_PROGRESS → 참고, COMPLETE 인데 노드가 클러스터에 있음 → 주의(SHUT-001).

    종료 레코드는 삭제하기 전까지 남는다. 작업 후 남으면 해당 노드로의 샤드 할당이 계속 제한될 수 있다.
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
        "SHUT-001", CLU, sev, "노드 종료(shutdown) 레코드",
        observed="종료 레코드 %d건(%s)." % (len(recs), ", ".join(sorted(set(r[2] for r in rows)))),
        impact="STALLED 는 샤드를 옮기지 못해 종료가 멈춘 상태입니다. 완료된 레코드가 남아 있으면 그 노드에 샤드 배치가 제한될 수 있습니다.",
        recommend="STALLED 는 explanation 의 사유(대상 노드 부족·allocation filter)를 해소합니다. 끝난 작업의 레코드는 "
                  "DELETE _nodes/<id>/shutdown 으로 지웁니다.",
        evidence=table(["node_id", "type", "status", "shard_migration", "explanation"], rows),
        refs=[D_SHUT], source="nodes_shutdown_status.json")]


def r_shard_store_errors(ctx):
    """shard_stores 에 store_exception 이 있는 샤드 사본 → 치명(IDX-012, 데이터 손상 의심)."""
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
        "IDX-012", MAPC, Severity.CRITICAL, "샤드 저장소 예외(손상 의심)",
        observed="store_exception 이 있는 샤드 사본 %d개." % len(rows),
        impact="해당 사본의 Lucene 파일을 열 수 없는 상태입니다. 다른 사본이 없으면 데이터 유실로 이어집니다.",
        recommend="다른 정상 사본이 있으면 손상 사본을 재할당(reroute)으로 교체하고, 없으면 스냅샷에서 복원합니다. "
                  "디스크·파일시스템 오류 로그도 확인합니다.",
        evidence=table(["index", "shard", "allocation", "exception"], rows[: ctx.t["top_n"]]),
        source="shard_stores.json")]


def r_remote_clusters(ctx):
    """remote_cluster_info 에서 connected=false 인 원격 클러스터 → 주의(OPS-003)."""
    rows = [[name, str(body.get("connected")), body.get("mode"), num(body, "num_nodes_connected")]
            for name, body in items(ctx.remote_clusters) if isinstance(body, dict) and body.get("connected") is False]
    if not rows:
        return []
    return [Finding(
        "OPS-003", OPS, Severity.WARNING, "원격 클러스터 연결 끊김",
        observed="연결되지 않은 원격 클러스터 %d개." % len(rows),
        impact="cross-cluster search 와 cross-cluster replication 이 해당 원격 클러스터에 대해 실패합니다.",
        recommend="원격 클러스터의 seed 주소·방화벽·인증서·API key 를 확인합니다.",
        evidence=table(["remote", "connected", "mode", "연결된 노드"], rows),
        source="remote_cluster_info.json")]


def r_frozen_cache(ctx):
    """frozen shared cache 통계. eviction 이 캐시 region 수를 넘은 노드가 있으면 주의(FRZ-001), 그 외 데이터가 있으면 참고.

    eviction > region 수는 캐시 전체가 최소 한 번 이상 교체되었다는 뜻으로, 검색 대상 대비 캐시가 작다는 신호다(도구 판단).
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
        "frozen shared cache 교체 과다" if hot else "frozen shared cache 현황",
        observed=("eviction 이 캐시 region 수를 넘은 frozen 노드 %d대." % hot) if hot else
                 "frozen 노드 %d대의 shared cache 현황." % len(rows),
        impact="frozen 검색은 캐시에 없는 데이터를 스냅샷 저장소에서 읽어 옵니다. 캐시가 자주 교체되면 같은 검색도 매번 "
               "저장소를 읽어 느려지고 저장소 요청 비용이 늘어납니다.",
        recommend="frozen 노드의 디스크(캐시 크기)를 늘리거나 노드를 추가합니다. 자주 검색하는 기간은 cold tier 에 두는 것도 방법입니다.",
        evidence=table(["node", "캐시 크기", "region", "reads", "읽은 양", "evictions"], rows),
        source="searchable_snapshots_cache_stats.json")]


# ------------------------------------------------------------------ 노드 통계 세부
def r_script_limit(ctx):
    """nodes_stats.script.compilation_limit_triggered > 0 인 노드 → 주의(PERF-010)."""
    rows = [[n.name, fmt_num(num(n.stats, "script", "compilation_limit_triggered")),
             fmt_num(num(n.stats, "script", "compilations")), fmt_num(num(n.stats, "script", "cache_evictions"))]
            for n in ctx.nodes if num(n.stats, "script", "compilation_limit_triggered") > 0]
    if not rows:
        return []
    return [Finding(
        "PERF-010", PERF, Severity.WARNING, "스크립트 컴파일 한도 발동",
        observed="script.max_compilations_rate 에 걸린 노드 %d대." % len(rows),
        impact="한도에 걸린 요청은 실패합니다. 대개 스크립트에 값을 직접 넣어 매번 새 스크립트로 컴파일되는 경우입니다.",
        recommend="스크립트 본문은 고정하고 값은 params 로 넘깁니다. 한도 상향은 원인을 가리므로 권장하지 않습니다.",
        evidence=table(["node", "한도 발동", "누적 컴파일", "캐시 eviction"], rows),
        source="nodes_stats.json")]


def r_ingest_processors(ctx):
    """노드 ingest 통계의 processor 별 누적 처리 시간을 합산해 상위 processor 를 보고한다(ING-002, 참고).

    hot threads(RT-001)에서 ingest 가 CPU 를 쓰는 것으로 보일 때 어떤 파이프라인·processor 가 원인인지 확인하는 근거다.
    """
    agg = collections.Counter()
    cnt = collections.Counter()
    for n in ctx.nodes:
        for pname, p in items(dig(n.stats, "ingest", "pipelines")):
            for proc in dicts(p.get("processors") if isinstance(p, dict) else None):
                for key, body in items(proc):
                    ptype = (body or {}).get("type") if isinstance(body, dict) else None
                    if ptype == "pipeline":
                        continue            # 하위 파이프라인 호출은 중복 합산을 피하려 제외
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
        "ING-002", PERF, Severity.INFO, "ingest processor 별 처리 시간",
        observed="누적 ingest processor 시간 %s 중 %s 유형이 %.0f%%." % (fmt_ms(total), t0, ms0 * 100.0 / total),
        impact="노드 기동 이후 누적값입니다. 비중이 큰 processor 가 색인 CPU 의 주 소비원입니다(hot threads 결과와 대조).",
        recommend="grok 은 패턴을 앵커(^)로 시작하고 후보 패턴 수를 줄이거나 dissect 로 바꿉니다. script·enrich 는 호출 빈도를 줄입니다.",
        evidence=table(["pipeline", "processor", "type", "누적 시간", "비중", "처리 건수", "건당"], rows),
        source="nodes_stats.json")]


def r_cluster_state_publication(ctx):
    """nodes_stats.discovery 의 클러스터 상태 발행 통계.

    cluster_state_update.failure 가 있으면 주의(CLU-024). 전체 상태 직렬화 크기(serialized full state, 압축 전)가 있으면
    크기와 평균 commit 시간을 참고로 보고한다. 발행은 마스터가 하므로 노드 중 최대값을 쓴다.
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
    ev = table(["항목", "값"], [["상태 변경 실패 누적", fmt_num(fails)], ["성공한 상태 변경", fmt_num(commits)],
                                ["평균 commit 시간", ("%.1fms" % avg_commit) if avg_commit is not None else "-"],
                                ["전체 상태 직렬화 크기(평균, 압축 전)", fmt_bytes(size) if size else "-"]])
    return [Finding(
        "CLU-024", CLU, Severity.WARNING if fails else Severity.INFO,
        "클러스터 상태 발행 실패" if fails else "클러스터 상태 발행 현황",
        observed=("클러스터 상태 변경 실패 누적 %s건." % fmt_num(fails)) if fails else
                 "평균 commit %s, 전체 상태 크기 %s." % (("%.1fms" % avg_commit) if avg_commit is not None else "-",
                                                  fmt_bytes(size) if size else "-"),
        impact="상태 변경 실패는 매핑 갱신·인덱스 생성·샤드 할당이 반영되지 않았다는 뜻입니다. 상태가 크고 commit 이 느리면 "
               "모든 메타데이터 변경이 느려집니다.",
        recommend="실패가 있으면 마스터 로그와 pending task(CLU-005)를 확인합니다. 상태가 크면 인덱스·필드 수를 줄입니다.",
        evidence=ev, source="nodes_stats.json")]


def r_plugin_consistency(ctx):
    """노드별 설치 플러그인(이름·버전)이 모두 같지 않으면 주의(CLU-023)."""
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
        "CLU-023", CLU, Severity.WARNING, "노드 간 플러그인 불일치",
        observed="일부 노드에만 있거나 버전이 다른 플러그인 %d개." % len(rows),
        impact="플러그인이 제공하는 분석기·저장소·타입을 쓰는 샤드는 플러그인이 없는 노드에 할당되지 않거나 실패합니다.",
        recommend="모든 노드에 같은 플러그인·버전을 설치합니다.",
        evidence=table(["플러그인", "없는 노드"], rows), source="nodes.json")]


# ------------------------------------------------------------------ ML·watcher·autoscaling·rollup
def r_ml_deployments(ctx):
    """trained model 배포의 state 가 started 가 아니거나 할당 상태가 fully_allocated 가 아니면 주의(ML-003)."""
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
        "ML-003", OPS, Severity.WARNING, "ML 모델 배포 이상",
        observed="정상 시작·완전 할당 상태가 아닌 모델 배포 %d개." % len(rows),
        impact="이 모델을 쓰는 ingest(임베딩·NER 등)·semantic 검색이 실패하거나 처리량이 떨어집니다.",
        recommend="ML 노드 메모리·프로세서 여유를 확인하고, 할당 수(number_of_allocations)를 가용 자원에 맞춥니다.",
        evidence=table(["model", "deployment", "state", "allocation", "reason"], rows),
        source="ml_trained_models_stats.json")]


def r_watcher_autoscaling_rollup(ctx):
    """watcher 가 수동 중지되었는데 watch 가 있으면 주의(OPS-005). 오토스케일링 요구 용량이 현재 용량보다 크면 참고(OPS-004).
    rollup job 이 있으면 참고(OPS-006, rollup 은 downsampling 으로 대체되어 deprecated).
    """
    out = []
    ws = ctx.watcher_stack
    watches = sum(num(s, "watch_count") for s in dicts(ws.get("stats")))
    if ws.get("manually_stopped") is True and watches:
        out.append(Finding(
            "OPS-005", OPS, Severity.WARNING, "watcher 수동 중지",
            observed="watcher 가 수동 중지 상태이고 등록된 watch 가 %d개 있습니다." % watches,
            impact="watch 기반 알림이 발송되지 않습니다.", recommend="의도한 중지가 아니라면 POST _watcher/_start 로 재개합니다.",
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
            "OPS-004", OPS, Severity.INFO, "오토스케일링 요구 용량이 현재 용량보다 큼",
            observed="요구 용량이 현재 용량을 넘는 오토스케일링 정책 %d개." % len(rows),
            impact="오토스케일링이 켜져 있으면 곧 확장되고, 최대 크기에 막혀 있으면 용량 부족이 해소되지 않습니다.",
            recommend="배포의 오토스케일링 최대 크기 설정과 확장 이력을 확인합니다.",
            evidence=table(["정책", "현재 저장", "요구 저장", "현재 메모리", "요구 메모리"], rows),
            source="autoscaling_capacity.json"))
    jobs = dicts(ctx.rollup_jobs.get("jobs"))
    if jobs:
        out.append(Finding(
            "OPS-006", OPS, Severity.INFO, "rollup job 사용(deprecated)",
            observed="rollup job %d개." % len(jobs),
            impact="rollup 은 deprecated 되었고 시계열 데이터 스트림의 downsampling 으로 대체되었습니다.",
            recommend="downsampling 으로 전환을 계획합니다.",
            evidence=table(["job", "상태"], [[dig(j, "config", "id"), dig(j, "status", "job_state")] for j in jobs]),
            source="rollup_jobs.json"))
    return out


def r_disk_io_utilization(ctx):
    """데이터 노드의 평균 디스크 사용률 = fs.io_stats.total.io_time_in_millis / JVM uptime (Linux 에서만 수집).

    io_time 은 ES 기동 이후 장치가 I/O 를 처리한 누적 시간이다. >= disk_io_busy_pct_warn → 주의(DISK-008), 그 외 참고.
    여러 장치를 쓰면 합계라 100%% 를 넘을 수 있어 장치 수로 나눈 값을 쓴다. 누적 평균이므로 순간 포화는 가려질 수 있다.
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
        rows.append([n.name, ctx.tier_of(n) or "-", "%.1f%%" % util, fmt_num(num(io, "total", "read_operations")),
                     fmt_num(num(io, "total", "write_operations")), devs])
        if util >= ctx.t["disk_io_busy_pct_warn"]:
            busy.append(n.name)
    if not rows:
        return []
    return [Finding(
        "DISK-008", "노드", Severity.WARNING if busy else Severity.INFO,
        "디스크 I/O 사용률 높음" if busy else "디스크 I/O 사용률",
        observed=("평균 디스크 사용률 %d%% 이상인 노드: %s" % (ctx.t["disk_io_busy_pct_warn"], ", ".join(busy))) if busy
                 else "데이터 노드 %d대의 기동 이후 평균 디스크 사용률." % len(rows),
        impact="디스크가 대부분의 시간 바쁘면 merge 가 밀려 색인이 억제(merge throttling)되고, 캐시에 없는 검색이 느려집니다.",
        recommend="IDX-005(merge throttling)·PERF-002(색인 지연)와 함께 보고, 지속되면 더 빠른 스토리지나 노드 추가를 검토합니다.",
        evidence=table(["node", "tier", "평균 사용률", "읽기 작업", "쓰기 작업", "장치 수"], rows),
        source="nodes_stats.json (fs.io_stats)")]


# 공식 문서가 비용이 크다고 명시한 쿼리 유형·검색 구성 요소
#   - Tune for search speed: nested 는 수 배, parent-child(has_child/has_parent)는 수백 배 느려질 수 있음, 스크립트 회피
#   - search.allow_expensive_queries 가 막는 유형: script, fuzzy, regexp, prefix, wildcard, 조인 쿼리 등
EXPENSIVE = [
    ("nested", "query", "nested 쿼리 — 문서 모델링 비용(공식: 수 배 느려질 수 있음)"),
    ("has_child", "query", "parent-child 조인(공식: 수백 배 느려질 수 있음)"),
    ("has_parent", "query", "parent-child 조인(공식: 수백 배 느려질 수 있음)"),
    ("script", "query", "script 쿼리"), ("script_score", "query", "script_score 쿼리"),
    ("wildcard", "query", "wildcard 쿼리"), ("regexp", "query", "regexp 쿼리"),
    ("fuzzy", "query", "fuzzy 쿼리"), ("prefix", "query", "prefix 쿼리"),
    ("query_string", "query", "query_string(선행 와일드카드·정규식 허용 시 비쌈)"),
    ("runtime_mappings", "section", "검색 시점 runtime field(검색마다 값 계산)"),
    ("script_fields", "section", "script_fields(결과마다 스크립트 실행)"),
]


def r_search_usage(ctx):
    """cluster_stats.indices.search 의 쿼리 유형·검색 구성 요소별 사용 횟수(누적)로 비용이 큰 검색 패턴의 비중을 본다.

    비용이 큰 유형(EXPENSIVE: nested·parent-child 조인·script·wildcard·regexp·fuzzy·prefix·query_string·
    runtime_mappings·script_fields)의 사용 비중이 search_expensive_share_warn(%) 이상이면 주의(PERF-011), 사용은 있으나
    비중이 낮으면 참고. 쿼리 본문이 아니라 유형별 횟수이므로 '어떤 인덱스의 어떤 쿼리' 인지는 알 수 없다.
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
        rows.append([key, "쿼리 유형" if kind == "query" else "검색 구성 요소", fmt_num(cnt), "%.2f%%" % share, desc])
        if share >= ctx.t["search_expensive_share_warn"]:
            heavy.append("%s %.1f%%" % (key, share))
    if not rows:
        return []
    rows.sort(key=lambda r: -float(r[3].rstrip("%")))
    top = sorted(((k, v) for k, v in items(q)), key=lambda kv: -num(kv[1]))[:8]
    return [Finding(
        "PERF-011", PERF, Severity.WARNING if heavy else Severity.INFO,
        "비용이 큰 검색 패턴 비중 높음" if heavy else "비용이 큰 검색 패턴 사용 현황",
        observed=("누적 검색 %s건 중 비중 %d%% 이상: %s." % (fmt_num(total), ctx.t["search_expensive_share_warn"], ", ".join(heavy)))
                 if heavy else "누적 검색 %s건 중 비용이 큰 유형 %d종이 쓰였으나 비중은 낮습니다." % (fmt_num(total), len(rows)),
        impact="검색 지연(PERF-001)·검색 스레드풀 포화·CPU 부하의 원인 후보입니다. nested 는 숨은 문서까지 검색하고, "
               "runtime field·script 는 검색마다 값을 계산하며, wildcard·regexp 는 많은 term 을 순회합니다. "
               "(참고: 가장 많이 쓰인 쿼리 유형 %s)" % ", ".join("%s %s" % (k, fmt_num(num(v))) for k, v in top),
        recommend="nested 는 평탄화나 문서 분리를 검토하고, 자주 쓰는 runtime field 는 색인 시점 필드로 전환합니다. "
                  "wildcard·prefix 는 wildcard 필드 타입이나 index_prefixes 로, 반복되는 script 는 색인 시점 계산으로 바꿉니다. "
                  "어떤 인덱스의 쿼리인지는 slowlog 나 Search Profiler 로 확인합니다.",
        evidence=table(["항목", "구분", "누적 사용", "검색 대비 비중", "설명"], rows),
        refs=[("Tune for search speed",
               "https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/search-speed")],
        source="cluster_stats.json (indices.search)")]


RULES = [r_search_usage, r_disk_io_utilization, r_mapping_limits_actual, r_vector_mapping_actual, r_ilm_policies, r_voting_exclusions,
         r_node_shutdown, r_shard_store_errors, r_remote_clusters, r_frozen_cache, r_script_limit,
         r_ingest_processors, r_cluster_state_publication, r_plugin_consistency, r_ml_deployments,
         r_watcher_autoscaling_rollup]
