# -*- coding: utf-8 -*-
"""핫스팟·밸런싱·복구 설정 룰.

근거: Elastic 공식 troubleshooting 문서 "Hot spotting"(자원 사용률이 일부 노드에 편중되는 현상)과
size-shards 문서의 desired balance allocator 설명.
"""


from ..model import Finding, Severity, table
from ..util import dig, fmt_num, parse_bytes, dicts, num, items, strs

HOT = "핫스팟·밸런싱"
CAT = "클러스터"

D_HOT = ("Hot spotting 문제 해결",
         "https://www.elastic.co/docs/troubleshoot/elasticsearch/hotspotting")
D_BAL = ("Unbalanced cluster 문제 해결",
         "https://www.elastic.co/docs/troubleshoot/elasticsearch/troubleshooting-unbalanced-cluster")
D_SHARDS = ("Size your shards",
            "https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards")
D_REC = ("복구(recovery) 설정",
         "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/index-recovery-settings")


def _spread(values):
    """최대/최소/편차."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    return max(vals), min(vals), max(vals) - min(vals)


def r_resource_hotspot(ctx):
    """같은 tier 안에서 heap% / CPU% / 디스크% 가 일부 노드에 편중되는지(공식 hot spotting 탐지 지표).

    tier 가 다르면 역할과 부하가 달라 비교하지 않는다. frozen tier 디스크는 shared cache 선점유라 제외.
    지표별로 tier 내 최대−최소 >= gap 이고 최대값 >= floor 일 때 주의. 수집 순간값이다.
    """
    rows, flags = [], []
    checks = (("heap 사용률", "heap", ctx.t["hotspot_heap_pct_gap"], ctx.t["hotspot_heap_pct_floor"]),
              ("CPU 사용률", "cpu", ctx.t["hotspot_cpu_pct_gap"], ctx.t["hotspot_cpu_pct_floor"]),
              ("디스크 사용률", "disk", ctx.t["disk_imbalance_pct_warn"], ctx.t["hotspot_disk_pct_floor"]))
    for tier, nodes in ctx.data_tiers().items():
        for n in nodes:
            rows.append([tier, n.name, "%s%%" % n.heap_used_pct if n.heap_used_pct is not None else "-",
                         "%s%%" % n.cpu_pct if n.cpu_pct is not None else "-",
                         "%.1f%%" % n.disk_used_pct if n.disk_used_pct is not None else "-"])
        if len(nodes) < 2:
            continue
        series = {"heap": [(n.name, n.heap_used_pct) for n in nodes],
                  "cpu": [(n.name, n.cpu_pct) for n in nodes],
                  "disk": [(n.name, n.disk_used_pct) for n in nodes] if tier != "frozen" else []}
        for label, key, gap, floor in checks:
            vals = [(v, k) for k, v in series[key] if v is not None]
            if len(vals) < 2:
                continue
            mx, mn = max(vals), min(vals)
            if mx[0] - mn[0] >= gap and mx[0] >= floor:
                flags.append("%s tier %s 편차 %.0f%%p (최대 %s: %.0f%%)" % (tier, label, mx[0] - mn[0], mx[1], mx[0]))
    ev = table(["tier", "node", "heap%", "cpu%", "disk%"], rows)
    if not flags:
        return [Finding("HOT-001", HOT, Severity.OK, "같은 tier 노드 간 자원 사용률 균등",
                        observed="tier 별로 heap·CPU·디스크 사용률이 크게 벌어지지 않았습니다.",
                        evidence=ev, refs=[D_HOT], source="nodes_stats.json")]
    return [Finding(
        "HOT-001", HOT, Severity.WARNING, "같은 tier 안에서 자원 사용률 편중(hot spotting 의심)",
        observed=" / ".join(flags),
        impact="같은 tier 의 특정 노드에만 부하가 몰리면 그 노드가 tier 전체의 처리 한계를 결정합니다. "
               "수집 순간값이므로 지속 여부를 모니터링으로 확인해야 합니다.",
        recommend="원인은 보통 (1) 같은 tier 내 스펙 불균일(NODE-001), (2) 샤드 분포 편중(SHD-006, HOT-002), "
                  "(3) 특정 작업 집중(RT-001, tasks)입니다. 샤드 분포가 원인이면 total_shards_per_node 로 상한을 둡니다.",
        evidence=ev, refs=[D_HOT], source="nodes_stats.json")]


def r_workload_hotspot(ctx):
    """같은 tier 안에서 노드별 누적 색인/검색 작업량 편중(최대 노드 / tier 평균 >= workload_skew_ratio_warn → 주의).

    누적값이며 replica 작업이 포함된다. uptime 이 다르면 왜곡되므로 시간당 환산값을 함께 제시한다.
    """
    out = []
    for key, label, path in (("index_total", "색인", ("indices", "indexing", "index_total")),
                             ("query_total", "검색", ("indices", "search", "query_total"))):
        flags, rows = [], []
        for tier, nodes in ctx.data_tiers().items():
            vals = []
            for n in nodes:
                v = num(n.stats, *path)
                up = (n.uptime_ms or 0) / 3600000.0
                vals.append(v)
                rows.append([tier, n.name, fmt_num(v), ("%.0f/h" % (v / up)) if up else "-"])
            if len(vals) < 2 or sum(vals) < 10000:
                continue
            avg = sum(vals) / float(len(vals))
            if avg and max(vals) / avg >= ctx.t["workload_skew_ratio_warn"]:
                flags.append("%s tier 최대 노드가 평균의 %.1f배" % (tier, max(vals) / avg))
        if flags:
            out.append(Finding(
                "HOT-002." + key, HOT, Severity.WARNING, "같은 tier 안에서 %s 작업량 편중" % label,
                observed=" / ".join(flags),
                impact="누적값 기준이며 replica 작업이 포함됩니다. 같은 tier 에서 쓰기 대상 샤드나 인기 인덱스의 샤드가 "
                       "특정 노드에 몰려 있다는 신호입니다. 검색 편중은 Adaptive Replica Selection(CLU-014)과 replica 배치의 영향도 받습니다.",
                recommend="해당 tier 의 쓰기 대상 인덱스 primary 수를 노드 수의 배수로 맞추거나 total_shards_per_node 로 상한을 둡니다. "
                          "노드 uptime 이 크게 다르면 시간당 값을 기준으로 보십시오.",
                evidence=table(["tier", "node", "누적", "시간당"], rows),
                refs=[D_HOT], source="nodes_stats.json"))
    return out


def r_desired_balance(ctx):
    """desired balance 미수렴(원하는 위치에 있지 않은 샤드)."""
    rows, undesired = [], 0
    for r in dicts(ctx.cat_allocation):
        if not isinstance(r, dict):
            continue
        try:
            u = int(str(num(r, "shards.undesired")))
        except ValueError:
            u = 0
        undesired += u
        rows.append([r.get("node"), r.get("shards"), u, r.get("write_load.forecast"),
                     r.get("disk.percent")])
    db = ctx.b.json("internal_desired_balance.json") or {}
    stats = db.get("stats") or {}
    out = []
    if undesired >= ctx.t["undesired_shards_warn"]:
        out.append(Finding(
            "HOT-003", HOT, Severity.WARNING, "desired balance 미수렴 샤드",
            observed="원하는 노드에 있지 않은 샤드 %d개." % undesired,
            impact="할당기는 데이터 스트림 쓰기량, 샤드 수, 디스크 사용량을 함께 보고 목표 배치를 계산합니다. "
                   "미수렴 상태가 지속되면 실제 배치가 목표와 달라 편중이 해소되지 않습니다. "
                   "리밸런스 제한, allocation filter, 디스크 여유 부족이 흔한 원인입니다.",
            recommend="cluster.routing.rebalance.enable 과 allocation filter 를 먼저 확인하고, "
                      "concurrent_rebalance 제한이 과도하게 낮지 않은지 봅니다. 대량 이동이 예상되면 "
                      "저부하 시간대에 진행합니다.",
            evidence=table(["node", "샤드", "미수렴 샤드", "write_load 예측", "disk%"], rows),
            refs=[D_BAL, D_SHARDS], source="allocation.json / internal_desired_balance.json"))
    if stats.get("computation_converged") is False:
        out.append(Finding(
            "HOT-004", HOT, Severity.INFO, "밸런스 계산 미완료",
            observed="desired balance 계산이 수렴하지 않은 상태입니다.",
            impact="마스터가 목표 배치를 계산 중이거나 계산이 반복 중단되고 있습니다.",
            recommend="마스터 부하(CLU-005)와 클러스터 상태 변경 빈도를 함께 확인합니다.",
            source="internal_desired_balance.json"))
    return out


def r_recovery_settings(ctx):
    """복구 대역 제한.

    indices.recovery.max_bytes_per_sec 의 기본값(40mb)은 그 자체로 문제가 아니다.
    복구·재배치가 실제로 진행 중일 때만 복구 시간의 병목 후보로 보고한다.
    """
    rate = ctx.setting("indices.recovery.max_bytes_per_sec")
    src = ctx.setting_source("indices.recovery.max_bytes_per_sec")
    b = parse_bytes(rate)
    moving = sum(ctx.health.get(k) or 0 for k in
                 ("initializing_shards", "relocating_shards", "delayed_unassigned_shards"))
    active_recoveries = 0
    for _idx, body in items(ctx.recovery):
        for sh in dicts(body.get("shards") if isinstance(body, dict) else None):
            if (sh.get("stage") or "").upper() != "DONE":
                active_recoveries += 1
    if b is None or b > ctx.t["recovery_rate_low_bytes"] or not (moving or active_recoveries):
        return []
    rows = [["indices.recovery.max_bytes_per_sec", str(rate), src],
            ["cluster.routing.allocation.node_concurrent_recoveries",
             str(ctx.setting("cluster.routing.allocation.node_concurrent_recoveries")),
             ctx.setting_source("cluster.routing.allocation.node_concurrent_recoveries")],
            ["진행 중 복구 / 이동 샤드", str(active_recoveries), str(moving)]]
    return [Finding(
        "REC-001", CAT, Severity.INFO, "복구 진행 중 — 복구 대역 제한 확인",
        observed="복구·이동 중인 샤드가 있고 max_bytes_per_sec = %s (%s)." % (rate, src),
        impact="노드당 복구 속도의 상한입니다. 대용량 샤드를 복구하는 동안 이 값이 병목이면 "
               "yellow 상태가 길어집니다.",
        recommend="복구 소요 시간이 문제라면 스토리지·네트워크 여유를 확인한 뒤 일시적으로 상향하고, "
                  "복구 완료 후 원복합니다.",
        evidence=table(["설정", "값", "출처"], rows), refs=[D_REC], source="cluster_settings.json / recovery.json")]


def r_template_conflict(ctx):
    """레거시(_template) 템플릿이 composable(_index_template) 템플릿에 가려지는지.

    composable 템플릿이 하나라도 매칭되면 레거시 템플릿은 적용되지 않는다(공식 동작).
    또한 composable 끼리 같은 우선순위로 겹치는 경우는 ES 가 생성을 거부하므로 여기서 보지 않는다.
    패턴 겹침은 와일드카드 비교로 추정한다.
    """
    import fnmatch
    comp = []
    for it in (ctx.index_templates or {}).get("index_templates") or []:
        for pat in dig(it, "index_template", "index_patterns", default=[]) or []:
            comp.append((it.get("name"), pat))
    legacy = ctx.legacy_templates or {}
    rows = []
    for lname, body in legacy.items():
        if not isinstance(body, dict) or str(lname).startswith("."):
            continue
        for lp in strs(body.get("index_patterns")):
            probe = str(lp).replace("*", "x")
            for cname, cp in comp:
                cprobe = str(cp).replace("*", "x")
                if fnmatch.fnmatch(probe, cp) or fnmatch.fnmatch(cprobe, lp):
                    rows.append([lname, lp, cname, cp])
    if not rows:
        return []
    return [Finding(
        "TPL-001", CAT, Severity.WARNING, "레거시 템플릿이 composable 템플릿에 가려짐(추정)",
        observed="composable 템플릿과 패턴이 겹치는 레거시 템플릿 %d건." % len(rows),
        impact="composable 템플릿이 매칭되는 인덱스에는 레거시 템플릿이 적용되지 않습니다. "
               "레거시 쪽 매핑·설정을 기대하고 있었다면 롤오버 후 새 인덱스에서 조용히 빠집니다.",
        recommend="POST _index_template/_simulate_index/<index명> 으로 실제 적용 결과를 확인하고, "
                  "레거시 템플릿의 내용을 composable 템플릿(또는 컴포넌트 템플릿)으로 옮깁니다.",
        evidence=table(["legacy 템플릿", "패턴", "composable 템플릿", "패턴"], rows[: ctx.t["top_n"]]),
        source="templates.json / index_templates.json")]


def r_delayed_allocation(ctx):
    """노드 재기동 시 즉시 재복제를 막는 delayed_timeout 설정."""
    rows = []
    for name in ctx.index_settings.keys():
        if ctx.is_system_index(name):
            continue
        v = ctx.index_setting(name, "index.unassigned.node_left.delayed_timeout")
        if v is not None and str(v) in ("0", "0ms", "0s"):
            rows.append([name, str(v)])
    if not rows:
        return []
    return [Finding(
        "CLU-021", CAT, Severity.WARNING, "node_left 지연 할당이 비활성화된 인덱스",
        observed="delayed_timeout 이 0인 인덱스 %d개." % len(rows),
        impact="노드가 잠시 재기동되기만 해도 즉시 전체 replica 재복제가 시작됩니다. 재기동이 끝나면 "
               "다시 되돌리는 이동이 발생해 불필요한 네트워크·디스크 부하가 두 번 발생합니다.",
        recommend="기본값(1m) 또는 운영 재기동 소요시간에 맞춘 값으로 되돌립니다.",
        evidence=table(["index", "delayed_timeout"], rows[: ctx.t["top_n"]]),
        source="settings.json")]


def r_tier_saturation(ctx):
    """tier 단위 CPU 포화. 한 tier 의 모든 노드가 load15/CPU >= load_per_cpu_warn 또는 CPU% >= tier_cpu_pct_warn 이면 주의.

    노드 간 '편중'(HOT-001)과 다르다. 부하가 고르게 분산되어도 tier 전체가 한계에 있으면 노드를 추가하거나 부하를 줄여야 한다.
    그 tier 의 cgroup CPU throttling(OS-003)과 쓰기 스레드풀 rejection(TP-001)을 근거로 함께 제시한다.
    """
    out = []
    for tier, nodes in ctx.data_tiers().items():
        rows, hot = [], 0
        for n in nodes:
            per = (n.load15 / n.processors) if (n.load15 and n.processors) else None
            elapsed = num(n.stats, "os", "cgroup", "cpu", "stat", "number_of_elapsed_periods")
            thr = num(n.stats, "os", "cgroup", "cpu", "stat", "number_of_times_throttled")
            rej = sum(num(st, "rejected") for pool, st in items(dig(n.stats, "thread_pool"))
                      if pool in ("write", "write_coordination", "search"))
            busy = (per is not None and per >= ctx.t["load_per_cpu_warn"]) or \
                   (n.cpu_pct is not None and n.cpu_pct >= ctx.t["tier_cpu_pct_warn"])
            hot += 1 if busy else 0
            rows.append([tier, n.name, n.processors, "%s%%" % n.cpu_pct if n.cpu_pct is not None else "-",
                         "%.2f" % per if per is not None else "-",
                         "%.1f%%" % (thr * 100.0 / elapsed) if elapsed else "-", fmt_num(rej)])
        if nodes and hot == len(nodes):
            out.append(Finding(
                "HOT-005." + tier, HOT, Severity.WARNING, "%s tier 전체 CPU 포화" % tier,
                observed="%s tier 노드 %d대가 모두 CPU 한계 근처입니다(load15/CPU >= %.1f 또는 CPU >= %d%%)."
                         % (tier, len(nodes), ctx.t["load_per_cpu_warn"], ctx.t["tier_cpu_pct_warn"]),
                impact="부하가 노드 간에 고르게 나뉘어 있어도 tier 전체가 한계면 편중 해소로는 해결되지 않습니다. "
                       "hot tier 라면 색인 지연과 수집 backpressure, 검색 지연이 함께 커집니다.",
                recommend="같은 스펙의 노드를 tier 에 추가하거나, 노드당 CPU 를 늘립니다. hot tier 의 원인이 ingest pipeline 이면 "
                          "hot threads(RT-001)에서 비싼 processor(grok 등)를 확인해 파싱 비용을 줄이는 것이 먼저입니다. "
                          "컨테이너 throttling 이 함께 보이면 CPU limit 도 확인합니다.",
                evidence=table(["tier", "node", "cpu수", "cpu%", "load15/cpu", "throttled", "누적 rejection"], rows),
                refs=[D_HOT], source="nodes_stats.json"))
    return out


RULES = [r_tier_saturation, r_resource_hotspot, r_workload_hotspot, r_desired_balance,
         r_recovery_settings, r_template_conflict, r_delayed_allocation]
