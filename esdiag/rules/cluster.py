# -*- coding: utf-8 -*-
"""클러스터 레벨 판정 룰."""

import collections

from ..model import Finding, Severity, table
from ..util import dig, fmt_ms, fmt_num, dicts, num, items

CAT = "클러스터"
DOC_ALLOC = ("샤드 할당 문제 해결",
             "https://www.elastic.co/docs/troubleshoot/elasticsearch/diagnose-unassigned-shards")
DOC_HEALTH = ("클러스터 헬스 API",
              "https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-cluster-health")
DOC_SIZE = ("샤드 사이징 가이드",
            "https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards")


def r_cluster_status(ctx):
    """cluster_health.status 를 그대로 판정. red → 치명, yellow → 주의, green → 정상."""
    st = (ctx.health.get("status") or "").lower()
    active_pct = ctx.health.get("active_shards_percent_as_number")
    ev = table(
        ["항목", "값"],
        [["status", st or "-"],
         ["노드 수 / 데이터 노드 수", "%s / %s" % (ctx.health.get("number_of_nodes"),
                                            ctx.health.get("number_of_data_nodes"))],
         ["active primary / active total", "%s / %s" % (ctx.health.get("active_primary_shards"),
                                                       ctx.health.get("active_shards"))],
         ["unassigned / unassigned primary", "%s / %s" % (ctx.health.get("unassigned_shards"),
                                                          ctx.health.get("unassigned_primary_shards"))],
         ["relocating / initializing", "%s / %s" % (ctx.health.get("relocating_shards"),
                                                    ctx.health.get("initializing_shards"))],
         ["active_shards_percent", "%s%%" % active_pct]])
    if st == "red":
        return [Finding("CLU-001", CAT, Severity.CRITICAL, "클러스터 상태 red",
                        observed="primary 샤드 %s개가 할당되지 않아 상태가 red입니다." %
                                 ctx.health.get("unassigned_primary_shards"),
                        impact="해당 인덱스는 색인/검색이 일부 또는 전부 실패합니다. 데이터 유실 가능성도 함께 확인해야 합니다.",
                        recommend="_cluster/allocation/explain 으로 미할당 원인을 먼저 확정하고, "
                                  "노드 이탈·디스크 워터마크·allocation filter·스냅샷 복구 순으로 좁혀갑니다.",
                        evidence=ev, refs=[DOC_ALLOC], source="cluster_health.json")]
    if st == "yellow":
        return [Finding("CLU-001", CAT, Severity.WARNING, "클러스터 상태 yellow",
                        observed="replica 샤드 %s개가 할당되지 않았습니다." % ctx.health.get("unassigned_shards"),
                        impact="primary는 정상이라 서비스는 되지만, 노드 1대만 더 빠져도 데이터 유실·red 전환 위험이 있습니다.",
                        recommend="replica 수가 데이터 노드 수를 초과하지 않는지, allocation filter/tier 설정이 "
                                  "replica 배치를 막고 있지 않은지 확인합니다.",
                        evidence=ev, refs=[DOC_ALLOC], source="cluster_health.json")]
    return [Finding("CLU-001", CAT, Severity.OK, "클러스터 상태 green",
                    observed="모든 primary/replica 샤드가 정상 할당된 상태입니다.",
                    evidence=ev, source="cluster_health.json")]


def r_unassigned_reason(ctx):
    """샤드 목록에서 state=UNASSIGNED 인 샤드를 unassigned.reason 별로 집계. 미할당 primary 가 하나라도 있으면 치명, replica 만이면 주의(CLU-002). allocation_explain.json 이 있으면 decider 결과를 함께 보고: can_allocate != yes → 주의, 그 외 참고(CLU-003)."""
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
            "CLU-002", CAT, sev, "미할당 샤드 존재",
            observed="미할당 샤드 %d개. 사유 분포: %s" % (
                sum(reasons.values()),
                ", ".join("%s=%d" % (k, v) for k, v in reasons.most_common())),
            impact="ALLOCATION_FAILED/NODE_LEFT 는 즉시 조치 대상이고, "
                   "INDEX_CREATED/REPLICA_ADDED 는 일시적일 수 있습니다.",
            recommend="사유별 조치가 다릅니다. ALLOCATION_FAILED 는 allocation explain 의 decider 메시지, "
                      "NODE_LEFT 는 노드 복구, DISK 관련은 워터마크 해소가 우선입니다.",
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
                                 d.get("decision"), (d.get("explanation") or "")[:160]])
        out.append(Finding(
            "CLU-003", CAT, Severity.WARNING if can_alloc != "yes" else Severity.INFO,
            "allocation explain 결과",
            observed="can_allocate=%s / %s" % (can_alloc, expl[:200]),
            impact="decider 가 no 를 반환한 사유가 미할당의 직접 원인입니다.",
            recommend="아래 decider 메시지를 그대로 근거로 사용해 조치합니다.",
            evidence=table(["node", "decider", "decision", "explanation"],
                           deciders[: ctx.t["top_n"]]),
            refs=[DOC_ALLOC], source="allocation_explain.json"))
    return out


def r_internal_health(ctx):
    """Health API(_health_report) 지표를 그대로 전달. 지표별 red → 치명, yellow → 주의, 전 지표 green → 정상. unknown 은 판정하지 않는다."""
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
        return [Finding("CLU-004", CAT, Severity.OK, "Health API 지표 전체 green",
                        observed="master 안정성·디스크·샤드 가용성·ILM/SLM 등 %d개 지표 모두 green." % len(inds),
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
            "CLU-004." + name, CAT, sev, "Health API 지표 이상: %s (%s)" % (name, status),
            observed=ind.get("symptom") or "",
            impact="Elasticsearch 자체 헬스 진단이 문제로 판정한 항목입니다.",
            recommend=" / ".join(actions) if actions else
                      "해당 지표의 details 를 확인하고 원인 영역부터 조치합니다.",
            evidence=table(["key", "value"],
                           [[k, str(v)[:200]] for k, v in items(ind.get("details"))]),
            source="internal_health.json"))
    return out


def r_pending_tasks(ctx):
    """마스터 pending task. 건수 >= pending_tasks_crit 또는 최대 대기 >= max_task_wait_ms_warn x 4 → 치명, 건수 >= pending_tasks_warn 또는 최대 대기 >= max_task_wait_ms_warn → 주의."""
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
        "CLU-005", CAT, sev, "마스터 pending task 적체",
        observed="pending task %d건, 최대 대기 %s." % (n, fmt_ms(wait)),
        impact="클러스터 상태 변경(매핑 업데이트, 샤드 할당, 인덱스 생성)이 직렬 처리되며 지연됩니다. "
               "마스터 과부하 또는 대형 cluster state 가 흔한 원인입니다.",
        recommend="원인 task source 를 확인합니다. put-mapping/create-index 가 다수라면 매핑 폭증·"
                  "인덱스 과다 생성, shard-started/failed 가 다수라면 할당 불안정입니다. "
                  "전용 마스터 노드 분리도 함께 검토합니다.",
        evidence=table(["priority", "source", "time_in_queue"], rows),
        source="cluster_health.json / cluster_pending_tasks.json")]


def r_master_quorum(ctx):
    """마스터 후보(roles 에 master 포함, voting_only 포함) 수. 0대 → 치명, 다중 노드인데 1대 → 치명, 2대 → 치명(1대 이탈 시 정족수 상실), 4대 이상 짝수 → 주의(CLU-006). 전용 마스터가 없고 데이터 노드 >= 6대 → 주의(CLU-007)."""
    [n for n in ctx.master_nodes if not n.is_voting_only]
    total = len(ctx.master_nodes)
    out = []
    names = [n.name for n in ctx.master_nodes]
    if total == 0:
        return [Finding("CLU-006", CAT, Severity.CRITICAL, "마스터 후보 노드 없음",
                        observed="master 역할 노드를 찾지 못했습니다.",
                        impact="클러스터 상태 변경이 불가능합니다.",
                        recommend="노드 role 설정을 확인합니다.", source="nodes.json")]
    if total == 1 and len(ctx.nodes) > 1:
        out.append(Finding("CLU-006", CAT, Severity.CRITICAL, "마스터 후보 단일 노드",
                           observed="마스터 후보가 1대(%s)뿐입니다." % names[0],
                           impact="해당 노드 장애 시 클러스터 전체가 상태 변경 불가 상태가 됩니다(SPOF).",
                           recommend="마스터 후보를 3대로 구성합니다.",
                           affected=names, source="nodes.json"))
    elif total == 2:
        out.append(Finding("CLU-006", CAT, Severity.CRITICAL, "마스터 후보 2대 구성",
                           observed="마스터 후보가 2대입니다(%s)." % ", ".join(names),
                           impact="정족수가 2이므로 1대만 이탈해도 마스터 선출이 불가능합니다. "
                                  "가용성 측면에서 1대 구성보다 나을 게 없습니다.",
                           recommend="마스터 후보를 3대(홀수)로 맞춥니다.",
                           affected=names, source="nodes.json"))
    elif total >= 4 and total % 2 == 0:
        out.append(Finding("CLU-006", CAT, Severity.WARNING, "마스터 후보 짝수 대 구성",
                           observed="마스터 후보 %d대(짝수)." % total,
                           impact="짝수 구성은 추가 내결함성 없이 정족수만 올라갑니다.",
                           recommend="홀수(3 또는 5)로 조정합니다.",
                           affected=names, source="nodes.json"))
    # 전용 마스터 권고
    dedicated = [n for n in ctx.master_nodes if n.is_dedicated_master]
    if not dedicated and len(ctx.data_nodes) >= 6:
        out.append(Finding("CLU-007", CAT, Severity.WARNING, "전용 마스터 노드 부재",
                           observed="데이터 노드 %d대 규모인데 마스터 후보가 모두 데이터 역할을 겸하고 있습니다."
                                    % len(ctx.data_nodes),
                           impact="무거운 검색/색인 부하가 마스터 스레드와 GC에 영향을 주어 "
                                  "클러스터 상태 변경 지연·마스터 이탈로 번질 수 있습니다.",
                           recommend="전용 마스터 3대 분리를 검토합니다.",
                           source="nodes.json"))
    return out


def r_version_consistency(ctx):
    """노드별 ES 버전 종류 > 1 → 주의(CLU-008). 메이저 버전 < eol_major_below → 주의(CLU-009). 노드별 JVM 버전 종류 > 1 → 주의(CLU-010)."""
    out = []
    vers = collections.Counter(n.version for n in ctx.nodes if n.version)
    if len(vers) > 1:
        out.append(Finding(
            "CLU-008", CAT, Severity.WARNING, "노드 버전 불일치",
            observed="버전 분포: %s" % ", ".join("%s(%d대)" % (v, c) for v, c in vers.items()),
            impact="롤링 업그레이드 중이라면 정상이지만, 장기 혼재는 샤드 할당 제약(상위→하위 복제 불가)과 "
                   "기능 비활성을 유발합니다.",
            recommend="업그레이드를 완료하거나 롤백해 단일 버전으로 수렴시킵니다.",
            evidence=table(["node", "version"], [[n.name, n.version] for n in ctx.nodes]),
            source="nodes.json"))
    major = ctx.version_tuple[0]
    if major and major < ctx.t["eol_major_below"]:
        out.append(Finding(
            "CLU-009", CAT, Severity.WARNING, "구버전 메이저 사용",
            observed="클러스터 버전 %s" % ctx.version,
            impact="보안 패치·버그 수정이 중단된 구간일 수 있고, 최신 진단/헬스 API 가 없어 "
                   "문제 원인 파악 수단도 제한됩니다.",
            recommend="지원 버전으로 업그레이드 계획을 수립합니다. "
                      "(패치 최신 여부는 폐쇄망에서 판단 불가하므로 별도 확인 필요)",
            source="version.json"))
    jvms = collections.Counter(dig(n.info, "jvm", "version") for n in ctx.nodes
                               if dig(n.info, "jvm", "version"))
    if len(jvms) > 1:
        out.append(Finding(
            "CLU-010", CAT, Severity.WARNING, "노드 간 JVM 버전 불일치",
            observed="JVM 분포: %s" % ", ".join("%s(%d대)" % (v, c) for v, c in jvms.items()),
            impact="GC 동작·성능 특성이 노드마다 달라져 원인 분석이 어려워집니다.",
            recommend="번들 JDK 사용으로 통일하는 것을 권장합니다.",
            evidence=table(["node", "jvm"], [[n.name, dig(n.info, "jvm", "version")]
                                             for n in ctx.nodes]),
            source="nodes.json"))
    return out


RISKY_SETTINGS = [
    ("cluster.routing.allocation.enable", lambda v: str(v).lower() not in ("all", "none_checked"),
     Severity.CRITICAL,
     "샤드 할당이 전체 허용(all) 상태가 아닙니다. 롤링 재기동 후 원복을 빠뜨린 경우가 많습니다.",
     "PUT _cluster/settings 로 null 처리하거나 all 로 되돌립니다."),
    ("cluster.routing.rebalance.enable", lambda v: str(v).lower() != "all", Severity.WARNING,
     "리밸런스가 제한되어 노드 간 샤드 불균형이 고착될 수 있습니다.",
     "작업이 끝났다면 설정을 제거합니다."),
    ("cluster.routing.allocation.disk.threshold_enabled", lambda v: str(v).lower() == "false",
     Severity.CRITICAL,
     "디스크 워터마크 검사가 꺼져 있어 디스크 100% 도달 시 인덱스가 read-only 로 잠길 위험이 큽니다.",
     "true 로 되돌립니다."),
    ("cluster.blocks.read_only", lambda v: str(v).lower() == "true", Severity.CRITICAL,
     "클러스터 전체가 read-only 입니다.",
     "원인(수동 설정/디스크 flood stage) 확인 후 해제합니다."),
    ("cluster.blocks.read_only_allow_delete", lambda v: str(v).lower() == "true", Severity.CRITICAL,
     "flood stage 로 인한 쓰기 차단 상태입니다.",
     "디스크 확보 후 블록을 해제합니다."),
    ("action.destructive_requires_name", lambda v: str(v).lower() == "false", Severity.WARNING,
     "와일드카드 인덱스 삭제가 허용된 상태입니다.",
     "운영 클러스터는 true 로 둡니다."),
    ("indices.recovery.max_bytes_per_sec", lambda v: False, Severity.INFO, "", ""),
]


def r_risky_settings(ctx):
    """기본값이 아닌(persistent/transient 에 명시된) 클러스터 설정만 판정. allocation.enable != all → 치명, rebalance.enable != all → 주의, disk.threshold_enabled=false → 치명, cluster.blocks.read_only(_allow_delete)=true → 치명, destructive_requires_name=false → 주의(CLU-011). allocation.exclude._name/_ip/_host 값 존재 → 주의(CLU-012). transient 설정 존재 → 참고(CLU-013, 7.16 부터 deprecated). use_adaptive_replica_selection=false → 주의(CLU-014, 기본 true)."""
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
                "CLU-011." + key, CAT, sev, "위험한 클러스터 설정: %s" % key,
                observed="%s = %s (%s)" % (key, v, src),
                impact=impact, recommend=rec,
                source="cluster_settings.json"))
    # 잔존 allocation exclude
    for key in ("cluster.routing.allocation.exclude._name",
                "cluster.routing.allocation.exclude._ip",
                "cluster.routing.allocation.exclude._host"):
        v = ctx.setting(key)
        if v and str(v) not in ("", "null", "no_instances_excluded"):
            out.append(Finding(
                "CLU-012", CAT, Severity.WARNING, "노드 제외(exclude) 설정 잔존",
                observed="%s = %s" % (key, v),
                impact="해당 노드에 샤드가 배치되지 않습니다. 유지보수 후 원복을 누락하면 "
                       "용량이 남아도 샤드가 몰리고 디스크 편중이 생깁니다.",
                recommend="작업이 끝났다면 해당 설정을 null 로 제거합니다.",
                source="cluster_settings.json"))
    if ctx.cluster_settings.get("transient"):
        out.append(Finding(
            "CLU-013", CAT, Severity.INFO, "transient 클러스터 설정 사용 중",
            observed="transient 설정 %d건." % len(ctx.cluster_settings["transient"]),
            impact="transient 설정은 전체 클러스터 재기동 시 사라지며 8.x 이후 deprecated 입니다.",
            recommend="유지해야 할 값은 persistent 로 옮깁니다.",
            evidence=table(["scope", "key", "value"],
                           [r for r in rows if r[0] == "transient"]),
            source="cluster_settings.json"))
    if ctx.setting("cluster.routing.use_adaptive_replica_selection") is not None and \
            str(ctx.setting("cluster.routing.use_adaptive_replica_selection")).lower() == "false":
        out.append(Finding(
            "CLU-014", CAT, Severity.WARNING, "Adaptive Replica Selection 비활성화",
            observed="cluster.routing.use_adaptive_replica_selection = false",
            impact="검색 요청이 응답시간/부하를 고려하지 않고 라운드로빈으로 분배되어, "
                   "느린 노드 1대가 전체 p99 를 끌어내립니다.",
            recommend="특별한 사유가 없으면 true(기본값)로 되돌립니다.",
            source="cluster_settings.json"))
    return out


def r_shard_capacity(ctx):
    """사용률 = (active + unassigned − frozen 전용 노드의 샤드) / (cluster.max_shards_per_node x frozen 전용을 제외한 데이터 노드 수). >= max_shards_per_node_headroom_pct_warn → 주의, >= 95% → 치명."""
    out = []
    max_per_node = ctx.setting("cluster.max_shards_per_node", 1000)
    try:
        max_per_node = int(max_per_node)
    except (TypeError, ValueError):
        max_per_node = 1000
    # cluster.max_shards_per_node 는 frozen 전용 노드를 제외한 데이터 노드 그룹에 적용되고,
    # frozen 전용 노드는 cluster.max_shards_per_node.frozen(기본 3000)으로 별도 계산된다.
    frozen_only = set(n.name for n in ctx.data_nodes
                      if [r for r in n.roles if r.startswith("data")] == ["data_frozen"])
    data_nodes = len([n for n in ctx.data_nodes if n.name not in frozen_only]) or len(ctx.nodes)
    limit = max_per_node * data_nodes
    frozen_shards = len([sh for sh in ctx.shards if sh.get("node") in frozen_only])
    open_shards = ((num(ctx.health, "active_shards")) + (num(ctx.health, "unassigned_shards"))
                   - frozen_shards)
    used = (float(open_shards) / limit * 100.0) if limit else None
    if used is not None and used >= ctx.t["max_shards_per_node_headroom_pct_warn"]:
        out.append(Finding(
            "CLU-015", CAT,
            Severity.CRITICAL if used >= 95 else Severity.WARNING,
            "클러스터 샤드 한도 임박",
            observed="non-frozen 샤드 %s개 / 한도 %s개 (%.1f%% 사용). max_shards_per_node=%s, "
                     "대상 데이터 노드 %d대(frozen 전용 제외)."
                     % (fmt_num(open_shards), fmt_num(limit), used, max_per_node, data_nodes),
            impact="한도에 도달하면 신규 인덱스 생성과 롤오버가 실패하여 수집이 중단됩니다.",
            recommend="작은 인덱스 통합·ILM 롤오버 주기 조정·오래된 인덱스 삭제/동결로 샤드 수를 먼저 줄입니다. "
                      "한도 상향은 임시 조치로만 사용합니다.",
            refs=[DOC_SIZE], source="cluster_health.json / cluster_settings.json"))
    return out


def r_dangling(ctx):
    """dangling 인덱스가 1개 이상이면 주의."""
    d = (ctx.dangling or {}).get("dangling_indices") or []
    if not d:
        return []
    return [Finding(
        "CLU-016", CAT, Severity.WARNING, "dangling 인덱스 존재",
        observed="dangling 인덱스 %d개." % len(d),
        impact="과거 노드에 남아 있던 인덱스 데이터가 클러스터 메타데이터와 어긋난 상태입니다. "
               "자동 임포트되면 예기치 않은 인덱스가 되살아납니다.",
        recommend="필요한 데이터면 _dangling API 로 명시적으로 임포트하고, 아니면 삭제합니다.",
        evidence=table(["index_name", "index_uuid", "creation_date"],
                       [[x.get("index_name"), x.get("index_uuid"),
                         x.get("creation_date_millis")] for x in d[: ctx.t["top_n"]]]),
        source="dangling_indices.json")]


# 상시 동작하는 persistent task 는 장시간 실행이 정상이므로 제외한다.
PERSISTENT_TASK_HINTS = ("[c]", "health-node", "geoip-downloader", "poller",
                         "xpack/ml/job", "xpack/ml/datafeed", "data_frame/transforms",
                         "monitoring", "security/token", "system_index_migration",
                         "indices:data/read/search/scroll/keep_alive")


def _is_persistent_task(action, desc):
    blob = "%s %s" % (action or "", desc or "")
    return any(h in blob for h in PERSISTENT_TASK_HINTS)


def r_long_tasks(ctx):
    """running_time >= long_running_task_ms_warn 인 태스크(상시 동작하는 persistent task 는 제외) → 주의."""
    rows = []
    limit = ctx.t["long_running_task_ms_warn"]
    for _nid, node in items(ctx.tasks.get("nodes")):
        if not isinstance(node, dict):
            continue
        for tid, t in items(node.get("tasks")):
            if not isinstance(t, dict):
                continue
            run = num(t, "running_time_in_nanos")
            ms = (run / 1e6) if run else 0
            action = t.get("action") or ""
            desc = t.get("description") or ""
            if ms >= limit and action and not _is_persistent_task(action, desc):
                rows.append([node.get("name"), action, fmt_ms(ms), desc[:120]])
    if not rows:
        return []
    rows.sort(key=lambda r: r[2])
    return [Finding(
        "CLU-017", CAT, Severity.WARNING, "장시간 수행 중인 태스크",
        observed="%s 이상 수행 중인 태스크 %d건." % (fmt_ms(limit), len(rows)),
        impact="장시간 실행 중인 검색/리인덱스/force-merge 는 스레드풀과 heap 을 점유해 "
               "다른 요청의 지연과 rejection 을 유발합니다.",
        recommend="불필요한 작업은 _tasks/<id>/_cancel 로 취소하고, 반복된다면 쿼리/작업 스케줄을 재설계합니다.",
        evidence=table(["node", "action", "running", "description"], rows[: ctx.t["top_n"]]),
        source="tasks.json")]


def r_zone_balance(ctx):
    """데이터 노드의 zone 속성(availability_zone / zone / logical_availability_zone / rack_id)이 2종 이상일 때만 판정. 영역별 노드 수 최대−최소 >= 2 또는 최대 >= 최소 x 2 → 주의(CLU-018). awareness.attributes 미설정 → 주의(CLU-019)."""
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
            "CLU-018", CAT, Severity.WARNING, "가용영역 간 데이터 노드 불균형",
            observed="영역별 데이터 노드 수: %s" % ", ".join("%s=%d" % kv for kv in zones.items()),
            impact="영역 단위 장애 시 남은 용량이 부족하거나, 샤드가 특정 영역에 몰려 복구가 실패할 수 있습니다.",
            recommend="영역별 노드 수를 동일하게 맞추고, awareness 속성을 설정합니다.",
            source="nodes.json"))
    if not awareness and len(zones) >= 2:
        out.append(Finding(
            "CLU-019", CAT, Severity.WARNING, "shard allocation awareness 미설정",
            observed="가용영역 %d개가 감지되었으나 cluster.routing.allocation.awareness.attributes 가 없습니다."
                     % len(zones),
            impact="primary 와 replica 가 같은 영역에 배치될 수 있어, 영역 장애가 곧 데이터 유실이 됩니다.",
            recommend="노드 attribute 를 기준으로 awareness.attributes 를 설정합니다.",
            source="cluster_settings.json / nodes.json"))
    return out


def r_recovery_inflight(ctx):
    """recovery.json 에서 stage != DONE 인 샤드가 있으면 참고."""
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
        "CLU-020", CAT, Severity.INFO, "진행 중인 샤드 복구",
        observed="복구 진행 중 샤드 %d개." % len(active),
        impact="복구 중에는 네트워크/디스크 대역과 스레드가 소모되어 일반 요청 지연이 커질 수 있습니다.",
        recommend="장시간 정체된 복구는 indices.recovery.max_bytes_per_sec 와 소스 노드 부하를 확인합니다.",
        evidence=table(["index", "shard", "stage", "type", "elapsed", "progress"],
                       active[: ctx.t["top_n"]]),
        source="recovery.json")]


RULES = [
    r_cluster_status, r_unassigned_reason, r_internal_health, r_pending_tasks,
    r_master_quorum, r_version_consistency, r_risky_settings, r_shard_capacity,
    r_dangling, r_long_tasks, r_zone_balance, r_recovery_inflight,
]
