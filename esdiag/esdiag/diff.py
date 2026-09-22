# -*- coding: utf-8 -*-
"""두 진단 번들 비교(diff).

단일 번들 분석은 누적 카운터를 보기 때문에 "값이 0이 아니다"까지만 말할 수 있다.
같은 클러스터의 이전 번들과 비교하면 "지금도 증가 중인가"를 판정할 수 있고,
디스크·샤드 증가율로 포화 시점을 추정할 수 있다.
"""

import collections

from .model import Finding, Severity, table
from .util import dig, fmt_bytes, fmt_ms, fmt_num, num, items

CAT = "변화 추세"


def _elapsed_hours(base, cur):
    if not base.collection_time or not cur.collection_time:
        return None
    try:
        sec = (cur.collection_time - base.collection_time).total_seconds()
    except TypeError:
        return None
    return sec / 3600.0 if sec > 0 else None


def _node_map(ctx):
    return dict((n.name, n) for n in ctx.nodes)


def _tp_rejected(node):
    out = collections.Counter()
    for pool, st in items(dig(node.stats, "thread_pool")):
        r = num(st, "rejected")
        if r:
            out[pool] += r
    return out


def _breaker_tripped(node):
    out = collections.Counter()
    for name, br in items(dig(node.stats, "breakers")):
        t = num(br, "tripped")
        if t:
            out[name] += t
    return out


def _per_hour(delta, hours):
    if hours is None or hours <= 0:
        return None
    return delta / hours


def summary(base, cur, hours):
    """리포트 상단에 표기할 비교 요약."""
    def idx_count(ctx):
        return dig(ctx.cluster_stats, "indices", "count") or len(ctx.indices_stats)

    def store(ctx):
        return num(ctx.cluster_stats, "indices", "store", "size_in_bytes")

    rows = [
        ("수집 시각", base.collection_time.isoformat() if base.collection_time else "-",
         cur.collection_time.isoformat() if cur.collection_time else "-",
         ("%.1f시간 경과" % hours) if hours else "경과 시간 산출 불가"),
        ("클러스터 상태", base.health.get("status"), cur.health.get("status"), ""),
        ("버전", base.version, cur.version, ""),
        ("노드 수", len(base.nodes), len(cur.nodes),
         _sign(len(cur.nodes) - len(base.nodes))),
        ("인덱스 수", fmt_num(idx_count(base)), fmt_num(idx_count(cur)),
         _sign(idx_count(cur) - idx_count(base))),
        ("샤드 수", fmt_num(base.health.get("active_shards")),
         fmt_num(cur.health.get("active_shards")),
         _sign((num(cur.health, "active_shards")) - (num(base.health, "active_shards")))),
        ("미할당 샤드", fmt_num(base.health.get("unassigned_shards")),
         fmt_num(cur.health.get("unassigned_shards")),
         _sign((num(cur.health, "unassigned_shards"))
               - (num(base.health, "unassigned_shards")))),
        ("저장 용량", fmt_bytes(store(base)), fmt_bytes(store(cur)),
         _sign_bytes(store(cur) - store(base))),
        ("문서 수", fmt_num(dig(base.cluster_stats, "indices", "docs", "count")),
         fmt_num(dig(cur.cluster_stats, "indices", "docs", "count")),
         _sign((num(cur.cluster_stats, "indices", "docs", "count"))
               - (num(base.cluster_stats, "indices", "docs", "count")))),
    ]
    return {"columns": ["항목", "이전", "현재", "증감"],
            "rows": [[a, b, c, d] for a, b, c, d in rows],
            "hours": hours}


def _sign(v):
    if not v:
        return "변화 없음"
    return ("+%s" % fmt_num(v)) if v > 0 else ("-%s" % fmt_num(abs(v)))


def _sign_bytes(v):
    if not v:
        return "변화 없음"
    return ("+%s" % fmt_bytes(v)) if v > 0 else ("-%s" % fmt_bytes(abs(v)))


# ---------------------------------------------------------------- 룰
def r_status_change(base, cur, hours, t):
    """두 번들의 cluster status 가 다를 때. 악화 → 치명, 개선 → 참고."""
    b, c = (base.health.get("status") or "").lower(), (cur.health.get("status") or "").lower()
    order = {"green": 0, "yellow": 1, "red": 2}
    if b == c:
        return []
    worse = order.get(c, 0) > order.get(b, 0)
    return [Finding(
        "DIF-001", CAT, Severity.CRITICAL if worse else Severity.INFO,
        "클러스터 상태 %s" % ("악화" if worse else "개선"),
        observed="%s → %s" % (b or "-", c or "-"),
        impact="이전 수집 시점 대비 가용성이 바뀌었습니다." if worse
               else "이전 수집 시점의 문제가 해소되었습니다.",
        recommend="악화된 경우 미할당 샤드 사유(CLU-002)부터 확인합니다." if worse else "",
        source="cluster_health.json (두 번들 비교)")]


def r_node_restart(base, cur, hours, t):
    """같은 이름 노드의 uptime 이 이전보다 작음 → 치명(DIF-002, 재기동). 노드 이탈 → 주의, 신규만 → 참고(DIF-003)."""
    bm, cm = _node_map(base), _node_map(cur)
    restarted, left, joined = [], [], []
    for name, n in cm.items():
        if name not in bm:
            joined.append(name)
            continue
        bu, cu = bm[name].uptime_ms, n.uptime_ms
        if bu and cu and cu < bu:
            restarted.append([name, fmt_ms(bu), fmt_ms(cu)])
    for name in bm:
        if name not in cm:
            left.append(name)
    out = []
    if restarted:
        out.append(Finding(
            "DIF-002", CAT, Severity.CRITICAL, "노드 재기동 발생",
            observed="uptime 이 역전된 노드 %d대." % len(restarted),
            impact="두 수집 사이에 프로세스가 재시작되었습니다. 계획된 작업이 아니라면 OOM kill, "
                   "컨테이너 재스케줄, 하드웨어 이슈를 의심해야 합니다. 재기동 후에는 파일시스템 캐시가 "
                   "비어 한동안 검색이 느립니다.",
            recommend="계획 작업 여부를 확인하고, 아니라면 해당 노드의 로그와 heap dump 경로(CFG-007)를 "
                      "점검합니다.",
            evidence=table(["node", "이전 uptime", "현재 uptime"], restarted),
            source="nodes_stats.json (두 번들 비교)"))
    if left or joined:
        out.append(Finding(
            "DIF-003", CAT, Severity.WARNING if left else Severity.INFO, "노드 구성 변경",
            observed="이탈 %d대 / 신규 %d대" % (len(left), len(joined)),
            impact="노드가 빠지면 샤드 재배치가 일어나고, 새 노드가 들어오면 리밸런싱 트래픽이 발생합니다.",
            recommend="계획된 증설·교체인지 확인합니다.",
            evidence=table(["구분", "노드"],
                           [["이탈", n] for n in left] + [["신규", n] for n in joined]),
            source="nodes.json (두 번들 비교)"))
    return out


def r_rejections_delta(base, cur, hours, t):
    """노드·풀별 rejected 증가분. 합계 > 0 → 주의, >= rejected_crit → 치명(DIF-005). 누적값은 0 이 아니지만 증가분이 0 → 참고(DIF-004, 과거 이력)."""
    bm, cm = _node_map(base), _node_map(cur)
    rows, total = [], 0
    for name, n in cm.items():
        if name not in bm:
            continue
        b, c = _tp_rejected(bm[name]), _tp_rejected(n)
        for pool in set(list(b.keys()) + list(c.keys())):
            d = c[pool] - b[pool]
            if d > 0:
                total += d
                rate = _per_hour(d, hours)
                rows.append([name, pool, fmt_num(b[pool]), fmt_num(c[pool]), fmt_num(d),
                             ("%.0f/h" % rate) if rate else "-"])
    if not rows:
        if any(_tp_rejected(n) for n in cm.values()):
            return [Finding(
                "DIF-004", CAT, Severity.INFO, "스레드풀 rejection 증가 없음",
                observed="누적 rejection 은 0이 아니지만 두 수집 사이에는 증가하지 않았습니다.",
                impact="과거에 발생했고 현재는 멈춘 상태입니다. 단일 번들만 보면 진행 중인 문제로 "
                       "오인하기 쉬운 항목입니다.",
                recommend="과거 발생 시점만 확인하고 즉시 조치 대상에서는 제외합니다.",
                source="nodes_stats.json (두 번들 비교)")]
        return []
    rows.sort(key=lambda r: -int(str(r[4]).replace(",", "")))
    return [Finding(
        "DIF-005", CAT, Severity.CRITICAL if total >= t["rejected_crit"] else Severity.WARNING,
        "스레드풀 rejection 진행 중",
        observed="두 수집 사이 증가분 %s건%s." % (
            fmt_num(total), (" (%.0f건/시간)" % _per_hour(total, hours)) if hours else ""),
        impact="누적값이 아니라 증가분입니다. 현재도 요청이 거부되고 있다는 확정적 근거입니다.",
        recommend="write 풀이면 bulk 크기·동시성 조정과 색인 노드 증설, search 풀이면 무거운 쿼리 "
                  "튜닝과 샤드 수 축소가 우선입니다.",
        evidence=table(["node", "pool", "이전", "현재", "증가", "시간당"], rows[: t["top_n"]]),
        source="nodes_stats.json (두 번들 비교)")]


def r_gc_delta(base, cur, hours, t):
    """old GC 증가분. 시간당 증가 >= old_gc_per_hour_warn 또는 구간 GC 시간 비중 >= old_gc_time_ratio_warn → 주의, 그 외 참고. 카운터가 줄어든(재기동) 노드는 제외."""
    bm, cm = _node_map(base), _node_map(cur)
    rows, bad = [], False
    for name, n in cm.items():
        if name not in bm:
            continue
        bc, bt = bm[name].gc("old")
        cc, ct = n.gc("old")
        if cc < bc:          # 재기동으로 카운터 리셋
            continue
        dc, dt = cc - bc, ct - bt
        if dc <= 0:
            continue
        rate = _per_hour(dc, hours)
        ratio = (dt / (hours * 3600000.0) * 100) if hours else None
        rows.append([name, fmt_num(dc), fmt_ms(dt),
                     ("%.1f회/h" % rate) if rate else "-",
                     ("%.2f%%" % ratio) if ratio is not None else "-"])
        if rate and rate >= t["old_gc_per_hour_warn"]:
            bad = True
        if ratio is not None and ratio >= t["old_gc_time_ratio_warn"] * 100:
            bad = True
    if not rows:
        return []
    return [Finding(
        "DIF-006", CAT, Severity.WARNING if bad else Severity.INFO,
        "Old GC 발생 추이",
        observed="두 수집 사이 old GC 가 발생한 노드 %d대." % len(rows),
        impact="구간 평균 기준이라 누적값보다 현재 상태를 잘 반영합니다. 구간 내 GC 시간 비중이 "
               "수 %% 를 넘으면 지금 heap 압박이 있다는 뜻입니다.",
        recommend="비중이 높은 노드의 heap 사용률·fielddata·샤드 수를 같은 시점 기준으로 확인합니다.",
        evidence=table(["node", "old GC 증가", "GC 시간 증가", "시간당", "구간 내 GC 비중"], rows),
        source="nodes_stats.json (두 번들 비교)")]


def r_breaker_delta(base, cur, hours, t):
    """breaker tripped 증가분 > 0 → 치명."""
    bm, cm = _node_map(base), _node_map(cur)
    rows, total = [], 0
    for name, n in cm.items():
        if name not in bm:
            continue
        b, c = _breaker_tripped(bm[name]), _breaker_tripped(n)
        for k in set(list(b.keys()) + list(c.keys())):
            d = c[k] - b[k]
            if d > 0:
                total += d
                rows.append([name, k, fmt_num(b[k]), fmt_num(c[k]), fmt_num(d)])
    if not rows:
        return []
    return [Finding(
        "DIF-007", CAT, Severity.CRITICAL, "Circuit breaker 발동 진행 중",
        observed="두 수집 사이 발동 증가분 %s건." % fmt_num(total),
        impact="현재도 메모리 한도 초과로 요청이 거부되고 있습니다. 단발성 과거 이력이 아닙니다.",
        recommend="발동한 브레이커 종류에 맞춰 조치합니다(fielddata → keyword 집계 전환, "
                  "request → 집계 분할, inflight_requests → bulk 크기 축소).",
        evidence=table(["node", "breaker", "이전", "현재", "증가"], rows),
        source="nodes_stats.json (두 번들 비교)")]


def r_disk_projection(base, cur, hours, t):
    """디스크 증가율로 워터마크 도달 시점 추정."""
    if not hours or hours < t["diff_min_hours_for_projection"]:
        return []
    bm, cm = _node_map(base), _node_map(cur)
    rows, soon = [], []
    for name, n in cm.items():
        if name not in bm or not n.is_data or cur.is_frozen_only(n):
            continue        # frozen 전용 노드는 shared cache 선점유라 증가율 외삽 대상이 아니다
        ba = bm[name].fs_avail
        ct, ca = n.fs_total, n.fs_avail
        if not ct or ba is None or ca is None:
            continue
        growth = (ba - ca)                      # 줄어든 여유 공간
        rate = growth / hours                   # bytes/hour
        used_pct = (1 - ca / float(ct)) * 100
        high = cur.watermark_used_pct("high", ct) or 90.0
        head = (high / 100.0 * ct) - (ct - ca)  # high 까지 남은 바이트
        if head <= 0:
            label, days = "이미 high 초과", None
        elif rate > 0:
            days = head / rate / 24.0
            label = "%.1f일" % days
        else:
            label, days = "증가 없음", None
        rows.append([name, "%.1f%%" % used_pct, fmt_bytes(rate) + "/h", label, "%.0f%%" % high])
        if days is not None and days <= t["disk_projection_days_warn"]:
            soon.append((name, days))
    if not rows:
        return []
    sev = Severity.CRITICAL if any(d <= 7 for _, d in soon) else (
        Severity.WARNING if soon else Severity.INFO)
    return [Finding(
        "DIF-008", CAT, sev, "디스크 증가율 기반 포화 예상",
        observed="high watermark 도달까지: %s" % (
            ", ".join("%s %s" % (r[0], r[3]) for r in rows) or "산출 대상 없음"),
        impact="두 수집 사이의 증가 속도를 단순 선형 외삽한 값입니다. 보존 정책 변경이나 "
               "수집량 변동이 있으면 달라지므로 용량 계획의 출발점으로만 사용합니다.",
        recommend="7일 이내로 나오면 즉시 증설 또는 보존 기간 단축을 검토합니다. "
                  "ILM 의 delete/이동 단계가 예상대로 동작하는지도 함께 확인합니다.",
        evidence=table(["node", "현재 사용률", "증가 속도", "high 도달 예상", "high 기준"], rows),
        source="nodes_stats.json (두 번들 비교)")]


def r_throughput(base, cur, hours, t):
    """노드별 구간 index_total / query_total 증가분을 초당 처리량으로 환산(replica 작업 포함). 최대 노드 / 평균 >= workload_skew_ratio_warn → 주의, 그 외 참고."""
    if not hours:
        return []
    bm, cm = _node_map(base), _node_map(cur)
    rows = []
    tot_idx = tot_qry = 0
    for name, n in cm.items():
        if name not in bm:
            continue
        bi = num(bm[name].stats, "indices", "indexing", "index_total")
        ci = num(n.stats, "indices", "indexing", "index_total")
        bq = num(bm[name].stats, "indices", "search", "query_total")
        cq = num(n.stats, "indices", "search", "query_total")
        di, dq = max(0, ci - bi), max(0, cq - bq)
        tot_idx += di
        tot_qry += dq
        rows.append([name, fmt_num(di), "%.0f/s" % (di / (hours * 3600)),
                     fmt_num(dq), "%.0f/s" % (dq / (hours * 3600))])
    if not rows or (tot_idx + tot_qry) == 0:
        return []
    avg_i = tot_idx / float(len(rows))
    skew = (max(int(str(r[1]).replace(",", "")) for r in rows) / avg_i) if avg_i else 0
    return [Finding(
        "DIF-009", CAT,
        Severity.WARNING if skew >= t["workload_skew_ratio_warn"] else Severity.INFO,
        "구간 처리량과 노드 간 분포",
        observed="구간 색인 %s건(%.0f/s), 검색 %s건(%.0f/s).%s" % (
            fmt_num(tot_idx), tot_idx / (hours * 3600),
            fmt_num(tot_qry), tot_qry / (hours * 3600),
            (" 최대 노드가 평균의 %.1f배로 색인 편중." % skew)
            if skew >= t["workload_skew_ratio_warn"] else ""),
        impact="누적값이 아닌 구간 실측 처리량입니다. 노드 레벨 카운터라 replica 색인 작업이 포함되므로 "
               "클라이언트가 보낸 문서 수보다 (replica 수 + 1)배 가까이 큽니다. 노드별 분포가 고르지 않으면 "
               "hot spotting 입니다.",
        recommend="편중이 있으면 해당 인덱스의 primary 수와 total_shards_per_node 를 확인합니다.",
        evidence=table(["node", "구간 색인", "색인 rate", "구간 검색", "검색 rate"], rows),
        source="nodes_stats.json (두 번들 비교)")]


def r_index_growth(base, cur, hours, t):
    """인덱스 primary store 증가분 > index_growth_min_bytes → 참고(DIF-010). 사용자 인덱스 신규·삭제 → 참고(DIF-011)."""
    rows, new_idx, gone = [], [], []
    bset = set(base.indices_stats.keys())
    cset = set(cur.indices_stats.keys())
    for name in cset - bset:
        if not cur.is_system_index(name):
            new_idx.append(name)
    for name in bset - cset:
        if not base.is_system_index(name):
            gone.append(name)
    for name in cset & bset:
        b = num(base.indices_stats, name, "primaries", "store", "size_in_bytes")
        c = num(cur.indices_stats, name, "primaries", "store", "size_in_bytes")
        d = c - b
        if d > t["index_growth_min_bytes"]:
            rate = _per_hour(d, hours)
            rows.append([name, fmt_bytes(b), fmt_bytes(c), fmt_bytes(d),
                         (fmt_bytes(rate) + "/h") if rate else "-", d])
    out = []
    if rows:
        rows.sort(key=lambda r: -r[5])
        out.append(Finding(
            "DIF-010", CAT, Severity.INFO, "인덱스 증가량 상위",
            observed="두 수집 사이 증가한 인덱스 %d개(최대 %s)." % (len(rows), rows[0][3]),
            impact="용량 증가를 주도하는 인덱스를 특정할 수 있습니다. 보존 정책 검토의 출발점입니다.",
            recommend="상위 인덱스의 ILM 정책과 보존 기간이 의도대로인지 확인합니다.",
            evidence=table(["index", "이전", "현재", "증가", "시간당"],
                           [r[:5] for r in rows[: t["top_n"]]]),
            source="indices_stats.json (두 번들 비교)"))
    if new_idx or gone:
        out.append(Finding(
            "DIF-011", CAT, Severity.INFO, "인덱스 생성·삭제",
            observed="신규 %d개 / 삭제 %d개" % (len(new_idx), len(gone)),
            impact="롤오버·ILM 삭제가 정상 동작하면 자연스러운 변화입니다. 신규만 계속 늘고 삭제가 "
                   "없다면 보존 정책이 동작하지 않는 것입니다.",
            recommend="삭제가 0이고 신규만 있다면 ILM delete 단계를 확인합니다.",
            evidence=table(["구분", "인덱스"],
                           [["신규", n] for n in new_idx[: t["top_n"]]]
                           + [["삭제", n] for n in gone[: t["top_n"]]]),
            source="indices_stats.json (두 번들 비교)"))
    return out


DIFF_RULES = [r_status_change, r_node_restart, r_rejections_delta, r_gc_delta,
              r_breaker_delta, r_disk_projection, r_throughput, r_index_growth]


def compare(base, cur, thresholds, base_findings=None, cur_findings=None):
    """(summary dict, [Finding]) 반환."""
    hours = _elapsed_hours(base, cur)
    findings = []
    for fn in DIFF_RULES:
        try:
            findings.extend(fn(base, cur, hours, thresholds) or [])
        except Exception:
            continue
    if base_findings is not None and cur_findings is not None:
        findings.extend(_finding_delta(base_findings, cur_findings))
    return summary(base, cur, hours), findings


def _finding_delta(base_findings, cur_findings):
    """이전 번들 대비 새로 발생/해소된 판정."""
    sev_rank = Severity.ORDER
    bmap = dict((f.id, f) for f in base_findings
                if f.severity in (Severity.CRITICAL, Severity.WARNING))
    cmap = dict((f.id, f) for f in cur_findings
                if f.severity in (Severity.CRITICAL, Severity.WARNING))
    new = [cmap[k] for k in cmap if k not in bmap]
    fixed = [bmap[k] for k in bmap if k not in cmap]
    worse = [cmap[k] for k in cmap
             if k in bmap and sev_rank[cmap[k].severity] < sev_rank[bmap[k].severity]]
    if not (new or fixed or worse):
        return []
    rows = ([["신규 발생", f.id, f.title] for f in new]
            + [["악화", f.id, f.title] for f in worse]
            + [["해소", f.id, f.title] for f in fixed])
    # 다른 판정의 요약이므로 자체 심각도를 갖지 않는다(점수·건수 이중 계산 방지).
    return [Finding(
        "DIF-012", CAT, Severity.INFO, "판정 결과 변화",
        observed="신규 %d건 / 악화 %d건 / 해소 %d건" % (len(new), len(worse), len(fixed)),
        impact="이전 점검 이후 실제로 바뀐 항목만 추린 목록입니다. 조치 효과 확인과 "
               "신규 이슈 식별에 그대로 사용할 수 있습니다.",
        recommend="신규·악화 항목을 우선 처리하고, 해소 항목은 조치 결과로 보고합니다.",
        evidence=table(["구분", "룰", "항목"], rows),
        source="두 번들의 판정 결과 비교")]
