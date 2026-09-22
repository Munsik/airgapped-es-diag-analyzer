# -*- coding: utf-8 -*-
"""노드 레벨 판정 룰 (JVM / OS / 디스크 / 스레드풀 / 브레이커)."""

import collections

from ..model import Finding, Severity, table
from ..util import dig, fmt_bytes, fmt_ms, fmt_num, pct, dicts, num, items

CAT = "노드"
DOC_HEAP = ("Heap 크기 설정",
            "https://www.elastic.co/docs/deploy-manage/deploy/self-managed/important-settings-configuration")
DOC_DISK = ("디스크 기반 샤드 할당(워터마크)",
            "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings")
DOC_TP = ("스레드풀과 rejection",
          "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings")


def r_heap_usage(ctx):
    """노드별 jvm.mem.heap_used_percent(수집 순간값). >= heap_used_pct_crit → 치명, >= heap_used_pct_warn → 주의, 그 외 정상."""
    rows, warn, crit = [], [], []
    for n in ctx.nodes:
        used = n.heap_used_pct
        if used is None:
            continue
        rows.append([n.name, "%s%%" % used, fmt_bytes(n.heap_used), fmt_bytes(n.heap_max),
                     fmt_bytes(n.ram_total), ",".join(n.roles)])
        if used >= ctx.t["heap_used_pct_crit"]:
            crit.append(n.name)
        elif used >= ctx.t["heap_used_pct_warn"]:
            warn.append(n.name)
    if not rows:
        return []
    if crit:
        return [Finding(
            "JVM-001", CAT, Severity.CRITICAL, "Heap 사용률 위험 수준",
            observed="heap 사용률 %d%% 이상 노드: %s" % (ctx.t["heap_used_pct_crit"], ", ".join(crit)),
            impact="old GC 가 잦아지고 STW 시간이 길어지면서 요청 지연·circuit breaker·노드 이탈로 이어집니다.",
            recommend="수집 시점의 순간값이므로 먼저 지속성을 확인합니다. 원인은 대개 "
                      "(1) 과도한 샤드 수, (2) fielddata/aggregation 메모리, (3) 대용량 bulk/스크롤, "
                      "(4) 매핑 폭증 중 하나입니다. 아래 샤드·fielddata 항목과 함께 봅니다.",
            evidence=table(["node", "heap%", "used", "max", "RAM", "roles"], rows),
            affected=crit, refs=[DOC_HEAP], source="nodes_stats.json")]
    if warn:
        return [Finding(
            "JVM-001", CAT, Severity.WARNING, "Heap 사용률 높음",
            observed="heap 사용률 %d%% 이상 노드: %s" % (ctx.t["heap_used_pct_warn"], ", ".join(warn)),
            impact="여유 heap 이 줄면 GC 빈도가 올라가고 응답시간 변동이 커집니다.",
            recommend="샤드 수, fielddata, 대형 aggregation 사용 여부를 함께 점검합니다.",
            evidence=table(["node", "heap%", "used", "max", "RAM", "roles"], rows),
            affected=warn, refs=[DOC_HEAP], source="nodes_stats.json")]
    return [Finding("JVM-001", CAT, Severity.OK, "Heap 사용률 정상",
                    observed="모든 노드가 %d%% 미만입니다." % ctx.t["heap_used_pct_warn"],
                    evidence=table(["node", "heap%", "used", "max", "RAM", "roles"], rows),
                    source="nodes_stats.json")]


def r_heap_sizing(ctx):
    """heap_max >= heap_max_bytes_crit(32GiB) 또는 using_compressed_ordinary_object_pointers=false → 주의(JVM-002). heap_max / os.mem.adjusted_total > heap_vs_ram_pct_warn + heap_vs_ram_tolerance_pct → 주의(JVM-003). heap_init(Xms) != heap_max(Xmx) → 주의(JVM-004)."""
    out, rows = [], []
    oops_off, oversize, mismatch, too_big_vs_ram = [], [], [], []
    for n in ctx.nodes:
        hm, ram, hi = n.heap_max, n.ram_total, n.heap_init
        oops = dig(n.info, "jvm", "using_compressed_ordinary_object_pointers")
        ratio = pct(hm, ram)
        rows.append([n.name, fmt_bytes(hm), fmt_bytes(hi), fmt_bytes(ram),
                     "%.0f%%" % ratio if ratio else "-", str(oops)])
        if hm and hm >= ctx.t["heap_max_bytes_crit"]:
            oversize.append(n.name)
        if str(oops).lower() == "false":
            oops_off.append(n.name)
        if hm and hi and hm != hi:
            mismatch.append(n.name)
        if ratio and ratio > ctx.t["heap_vs_ram_pct_warn"] + ctx.t["heap_vs_ram_tolerance_pct"]:
            too_big_vs_ram.append(n.name)
    ev = table(["node", "heap_max", "heap_init(Xms)", "RAM", "heap/RAM", "compressed_oops"], rows)
    if oops_off or oversize:
        targets = sorted(set(oops_off) | set(oversize))
        out.append(Finding(
            "JVM-002", CAT, Severity.WARNING, "Heap 32GB 경계 초과(compressed oops 손실 가능)",
            observed="대상 노드: %s" % ", ".join(targets),
            impact="heap 이 압축 포인터 경계를 넘으면 객체 포인터가 8바이트로 커져 "
                   "같은 데이터를 담는 데 더 많은 heap 을 쓰게 됩니다. 26~30GB 보다 오히려 불리할 수 있습니다.",
            recommend="heap 을 30GB 이하(권장 26~30GB)로 낮추고, 남는 메모리는 파일시스템 캐시로 둡니다. "
                      "메모리가 더 필요하면 노드를 수직 확장하기보다 노드를 늘립니다.",
            evidence=ev, affected=targets, refs=[DOC_HEAP], source="nodes.json / nodes_stats.json"))
    if too_big_vs_ram:
        out.append(Finding(
            "JVM-003", CAT, Severity.WARNING, "Heap 이 물리 메모리 대비 과다",
            observed="heap/RAM 비율이 %d%% 를 넘는 노드: %s"
                     % (ctx.t["heap_vs_ram_pct_warn"], ", ".join(too_big_vs_ram)),
            impact="Lucene 은 off-heap(파일시스템 캐시)에서 세그먼트를 읽습니다. heap 을 키울수록 "
                   "캐시에 남는 메모리가 줄어 디스크 I/O 가 늘고 검색이 느려집니다.",
            recommend="공식 권장은 Xms/Xmx 를 전체 메모리의 50% 이하로 두는 것입니다. "
                      "컨테이너 환경에서는 cgroup 메모리 한도 기준입니다.",
            evidence=ev, affected=too_big_vs_ram, refs=[DOC_HEAP], source="nodes.json"))
    if mismatch:
        out.append(Finding(
            "JVM-004", CAT, Severity.WARNING, "Xms 와 Xmx 불일치",
            observed="대상 노드: %s" % ", ".join(mismatch),
            impact="heap 이 동적으로 확장되면서 재할당과 GC 패턴 변동이 생깁니다.",
            recommend="Xms 와 Xmx 를 동일한 값으로 고정합니다.",
            evidence=ev, affected=mismatch, source="nodes.json"))
    return out


def r_gc(ctx):
    """old 비중 = old collection_time / uptime, 시간당 old GC = old count / uptime(h), young 비중 = young time / uptime. old 비중 >= old_gc_time_ratio_crit 또는 시간당 >= old_gc_per_hour_crit → 치명. old 비중 >= warn, 시간당 >= warn, young 비중 >= young_gc_time_ratio_warn 중 하나 → 주의. 그 외 정상. 누적값이므로 비교 모드(DIF-006)가 더 정확하다."""
    rows, warn, crit = [], [], []
    for n in ctx.nodes:
        up = n.uptime_ms or 0
        oc, ot = n.gc("old")
        yc, yt = n.gc("young")
        if not up:
            continue
        old_ratio = ot / float(up) if up else 0
        young_ratio = yt / float(up) if up else 0
        old_per_hour = oc / (up / 3600000.0) if up else 0
        rows.append([n.name, fmt_ms(up), fmt_num(oc), fmt_ms(ot), "%.3f%%" % (old_ratio * 100),
                     fmt_num(yc), fmt_ms(yt), "%.2f%%" % (young_ratio * 100),
                     "%.1f" % old_per_hour])
        if old_ratio >= ctx.t["old_gc_time_ratio_crit"] or old_per_hour >= ctx.t["old_gc_per_hour_crit"]:
            crit.append(n.name)
        elif (old_ratio >= ctx.t["old_gc_time_ratio_warn"]
              or old_per_hour >= ctx.t["old_gc_per_hour_warn"]
              or young_ratio >= ctx.t["young_gc_time_ratio_warn"]):
            warn.append(n.name)
    if not rows:
        return []
    ev = table(["node", "uptime", "old GC 횟수", "old GC 시간", "old 비중",
                "young 횟수", "young 시간", "young 비중", "old GC/시간"], rows)
    if crit:
        return [Finding(
            "JVM-005", CAT, Severity.CRITICAL, "Old GC 과다",
            observed="old GC 부담이 큰 노드: %s" % ", ".join(crit),
            impact="old GC 는 대부분 stop-the-world 를 동반합니다. 누적 시간이 uptime 의 수 % 를 넘으면 "
                   "요청 타임아웃, 마스터 연결 끊김(node left), 클러스터 불안정으로 직결됩니다.",
            recommend="heap 압박 원인을 제거합니다. 샤드 수 축소, fielddata/전역 서수 사용 축소, "
                      "대형 aggregation 의 partition 처리, bulk 크기 축소 순으로 확인합니다. "
                      "local 모드 진단이면 gc.log 에서 실제 STW 시간을 함께 확인합니다.",
            evidence=ev, affected=crit, source="nodes_stats.json")]
    if warn:
        return [Finding(
            "JVM-005", CAT, Severity.WARNING, "GC 부담 관찰됨",
            observed="GC 비중이 기준을 넘는 노드: %s" % ", ".join(warn),
            impact="응답시간 꼬리(p99)가 길어지는 원인이 됩니다.",
            recommend="heap 사용률 추이와 함께 관찰하고, 지속되면 heap 압박 원인을 제거합니다.",
            evidence=ev, affected=warn, source="nodes_stats.json")]
    return [Finding("JVM-005", CAT, Severity.OK, "GC 부담 정상 범위",
                    observed="old GC 누적 시간이 uptime 대비 %.1f%% 미만입니다."
                             % (ctx.t["old_gc_time_ratio_warn"] * 100),
                    evidence=ev, source="nodes_stats.json")]


def r_os(ctx):
    """load15 / available_processors >= load_per_cpu_crit → 치명, >= warn → 주의(OS-001, 두 구간의 노드를 모두 표시). swap_total > 0 이고 mlockall 이 true 가 아님 → 주의(OS-002). cgroup throttled / elapsed_periods >= cgroup_throttle_ratio_crit → 치명, >= warn → 주의(OS-003). open_fd / max_fd >= fd_used_pct_warn → 주의(OS-004). mlockall=false 이고 swap 없음 → 참고(OS-005). uptime < uptime_short_hours → 주의(OS-006)."""
    out = []
    rows, load_warn, load_crit, swap_on, throttle = [], [], [], [], []
    for n in ctx.nodes:
        cpus = n.processors or 0
        l1, l5, l15 = n.load1, n.load5, n.load15
        per = (l15 / cpus) if (l15 and cpus) else None
        rows.append([n.name, ctx.tier_of(n) or ("master" if n.is_master_eligible else ",".join(n.roles)),
                     fmt_num(cpus), n.cpu_pct if n.cpu_pct is not None else "-",
                     l1, l5, l15, ("%.2f" % per) if per else "-", fmt_bytes(n.swap_total)])
        if per is not None:
            if per >= ctx.t["load_per_cpu_crit"]:
                load_crit.append(n.name)
            elif per >= ctx.t["load_per_cpu_warn"]:
                load_warn.append(n.name)
        # 공식 문서의 swap 대책은 (1) swap 비활성 (2) swappiness=1 (3) memory_lock 중 하나.
        # memory_lock 이 적용되어 있으면 heap 은 swap 대상이 아니므로 경고하지 않는다.
        if n.swap_total and n.mlockall is not True:
            swap_on.append(n.name)
        elapsed = dig(n.stats, "os", "cgroup", "cpu", "stat", "number_of_elapsed_periods")
        thr = dig(n.stats, "os", "cgroup", "cpu", "stat", "number_of_times_throttled")
        if elapsed and thr:
            ratio = float(thr) / float(elapsed)
            if ratio >= ctx.t["cgroup_throttle_ratio_warn"]:
                throttle.append((n.name, ratio,
                                 dig(n.stats, "os", "cgroup", "cpu", "stat", "time_throttled_nanos")))
    ev = table(["node", "tier/역할", "cpu수", "cpu%", "load1m", "load5m", "load15m", "load/cpu", "swap"], rows)
    if load_crit or load_warn:
        parts = []
        if load_crit:
            parts.append("위험(>= %.1f): %s" % (ctx.t["load_per_cpu_crit"], ", ".join(load_crit)))
        if load_warn:
            parts.append("주의(>= %.1f): %s" % (ctx.t["load_per_cpu_warn"], ", ".join(load_warn)))
        out.append(Finding(
            "OS-001", CAT, Severity.CRITICAL if load_crit else Severity.WARNING,
            "CPU load 높음",
            observed="load15m/CPU 가 기준을 넘는 노드 — " + " / ".join(parts),
            impact="CPU 포화는 검색 큐 적체와 rejection, 색인 지연으로 이어집니다.",
            recommend="hot threads 결과(아래 항목)와 대조해 무엇이 CPU 를 쓰는지 확정합니다. "
                      "merge/검색/스크립트/GC 중 어느 쪽인지에 따라 조치가 다릅니다.",
            evidence=ev, affected=load_crit + load_warn, source="nodes_stats.json"))
    if swap_on:
        out.append(Finding(
            "OS-002", CAT, Severity.WARNING, "Swap 활성화",
            observed="swap 이 설정된 노드: %s" % ", ".join(swap_on),
            impact="JVM heap 일부가 디스크로 내려가면 GC 시간이 수십 배로 늘어 노드가 사실상 멈춥니다.",
            recommend="swap 비활성화, vm.swappiness=1, bootstrap.memory_lock=true 중 하나를 적용합니다. "
                      "(vm.swappiness 값은 api 모드 번들에 수집되지 않으므로 서버에서 확인이 필요합니다.)",
            evidence=ev, affected=swap_on, source="nodes_stats.json"))
    if throttle:
        out.append(Finding(
            "OS-003", CAT,
            Severity.CRITICAL if any(r >= ctx.t["cgroup_throttle_ratio_crit"] for _, r, _ in throttle)
            else Severity.WARNING,
            "컨테이너 CPU throttling 발생",
            observed="cgroup CPU 제한에 걸린 노드: %s"
                     % ", ".join("%s(%.1f%%)" % (n, r * 100) for n, r, _ in throttle),
            impact="컨테이너/k8s CPU limit 때문에 실제로 쓸 수 있는 CPU 가 주기적으로 차단됩니다. "
                   "평균 CPU 사용률은 낮아 보이는데 지연만 튀는 전형적인 원인입니다.",
            recommend="CPU limit 을 request 와 동일하게 올리거나 limit 을 제거합니다.",
            evidence=table(["node", "throttled 비율", "throttled 누적(ns)"],
                           [[n, "%.2f%%" % (r * 100), fmt_num(t)] for n, r, t in throttle]),
            source="nodes_stats.json"))
    # 파일 디스크립터
    fd_rows, fd_bad = [], []
    for n in ctx.nodes:
        o, m = n.open_fd, n.max_fd
        p = pct(o, m)
        if p is None:
            continue
        fd_rows.append([n.name, fmt_num(o), fmt_num(m), "%.1f%%" % p])
        if p >= ctx.t["fd_used_pct_warn"]:
            fd_bad.append(n.name)
    if fd_bad:
        out.append(Finding(
            "OS-004", CAT, Severity.WARNING, "파일 디스크립터 사용률 높음",
            observed="대상 노드: %s" % ", ".join(fd_bad),
            impact="한계에 도달하면 세그먼트 파일/소켓을 열지 못해 색인·검색이 실패합니다.",
            recommend="nofile 한도를 65535 이상으로 올리고, 세그먼트 수(샤드/인덱스 과다)도 함께 줄입니다.",
            evidence=table(["node", "open", "max", "사용률"], fd_rows),
            affected=fd_bad, source="nodes_stats.json"))
    # mlockall
    unlocked = [n.name for n in ctx.nodes if n.mlockall is False]
    if unlocked and not swap_on:
        out.append(Finding(
            "OS-005", CAT, Severity.INFO, "bootstrap.memory_lock 미적용",
            observed="memory lock 이 적용되지 않은 노드: %s" % ", ".join(unlocked),
            impact="현재 swap 이 꺼져 있어 즉시 위험은 아니지만, 설정 변경 시 heap 이 swap 될 수 있습니다.",
            recommend="bootstrap.memory_lock=true 와 OS 의 memlock 한도(unlimited)를 함께 설정합니다.",
            source="nodes.json"))
    # 최근 재기동
    short = [(n.name, n.uptime_ms) for n in ctx.nodes
             if n.uptime_ms and n.uptime_ms < ctx.t["uptime_short_hours"] * 3600000]
    if short:
        out.append(Finding(
            "OS-006", CAT, Severity.WARNING, "최근 재기동된 노드 존재",
            observed=", ".join("%s(uptime %s)" % (n, fmt_ms(u)) for n, u in short),
            impact="의도한 재기동이 아니라면 OOM kill, 하드웨어 이슈, 컨테이너 재스케줄을 의심해야 합니다. "
                   "또한 캐시가 비어 있어 당분간 검색 지연이 큽니다.",
            recommend="계획된 작업 여부를 확인하고, 아니라면 커널 로그와 heap dump 경로를 점검합니다.",
            source="nodes_stats.json"))
    return out


def r_disk(ctx):
    """데이터 노드 사용률 = 1 − available / total. 실효 워터마크(max_headroom 반영, context.watermark_used_pct) 대비 flood 이상 → 치명(DISK-001), high 이상 → 치명(DISK-002), low 이상 → 주의(DISK-003), low − disk_low_margin_pct 이상 → 주의(DISK-004, 앞 세 항목이 없을 때만). 노드 간 사용률 최대−최소 >= disk_imbalance_pct_warn → 주의(DISK-005). 해당 없음 → 정상."""
    rows, over_low, over_high, over_flood, warn = [], [], [], [], []
    by_tier = {}
    for n in ctx.data_nodes or ctx.nodes:
        total, avail = n.fs_total, n.fs_avail
        up = n.disk_used_pct
        if up is None:
            continue
        tier = ctx.tier_of(n) or "-"
        if tier == "frozen":
            # frozen 전용 노드: 디스크 대부분을 shared cache 가 미리 점유(기본 90%)하므로 사용률이 높은 것이 정상.
            # 공식 동작상 low/high 워터마크는 적용되지 않고 flood_stage.frozen 만 적용된다.
            fflood = ctx.watermark_used_pct("flood_stage.frozen", total)
            rows.append([n.name, tier, "%.1f%%" % up, fmt_bytes(total), fmt_bytes(avail),
                         "해당 없음", "해당 없음", ("%.2f%% (frozen)" % fflood) if fflood else "-"])
            if fflood and up >= fflood:
                over_flood.append(n.name)
            continue
        by_tier.setdefault(tier, []).append(up)
        low = ctx.watermark_used_pct("low", total)
        high = ctx.watermark_used_pct("high", total)
        flood = ctx.watermark_used_pct("flood_stage", total)
        rows.append([n.name, tier, "%.1f%%" % up, fmt_bytes(total), fmt_bytes(avail),
                     "%.2f%%" % low if low else "-", "%.2f%%" % high if high else "-",
                     "%.2f%%" % flood if flood else "-"])
        if flood and up >= flood:
            over_flood.append(n.name)
        elif high and up >= high:
            over_high.append(n.name)
        elif low and up >= low:
            over_low.append(n.name)
        elif low and up >= low - ctx.t["disk_low_margin_pct"]:
            warn.append(n.name)
    if not rows:
        return []
    ev = table(["node", "tier", "사용률", "총 용량", "가용", "실효 low", "실효 high", "실효 flood"], rows)
    out = []
    if over_flood:
        out.append(Finding(
            "DISK-001", CAT, Severity.CRITICAL, "디스크 flood stage 초과",
            observed="대상 노드: %s" % ", ".join(over_flood),
            impact="해당 노드의 인덱스에 read-only-allow-delete 블록이 걸려 색인이 중단됩니다.",
            recommend="즉시 공간을 확보(오래된 인덱스 삭제/이동)한 뒤 "
                      "index.blocks.read_only_allow_delete 를 null 로 해제합니다.",
            evidence=ev, affected=over_flood, refs=[DOC_DISK], source="nodes_stats.json"))
    if over_high:
        out.append(Finding(
            "DISK-002", CAT, Severity.CRITICAL, "디스크 high watermark 초과",
            observed="대상 노드: %s" % ", ".join(over_high),
            impact="해당 노드에서 샤드가 다른 노드로 강제 이동합니다. 이동 자체가 I/O·네트워크 부하를 만들고, "
                   "받을 노드가 없으면 미할당으로 남습니다.",
            recommend="용량 증설 또는 데이터 정리. ILM 으로 warm/cold 이동, 오래된 인덱스 삭제를 검토합니다.",
            evidence=ev, affected=over_high, refs=[DOC_DISK], source="nodes_stats.json"))
    if over_low:
        out.append(Finding(
            "DISK-003", CAT, Severity.WARNING, "디스크 low watermark 초과",
            observed="대상 노드: %s" % ", ".join(over_low),
            impact="신규 샤드가 해당 노드에 배치되지 않습니다. 롤오버 시 샤드가 일부 노드로 몰립니다.",
            recommend="용량 계획을 재점검합니다.",
            evidence=ev, affected=over_low, refs=[DOC_DISK], source="nodes_stats.json"))
    if warn and not (over_flood or over_high or over_low):
        out.append(Finding(
            "DISK-004", CAT, Severity.WARNING, "디스크 사용률 상승",
            observed="실효 low 워터마크까지 %d%%p 이내인 노드: %s"
                     % (ctx.t["disk_low_margin_pct"], ", ".join(warn)),
            impact="워터마크 도달까지 여유가 크지 않습니다.",
            recommend="증가 추세와 보존 정책을 확인합니다.",
            evidence=ev, affected=warn, source="nodes_stats.json"))
    gaps = [(t, max(v), min(v)) for t, v in by_tier.items()
            if len(v) >= 2 and max(v) - min(v) >= ctx.t["disk_imbalance_pct_warn"]]
    if gaps:
        out.append(Finding(
            "DISK-005", CAT, Severity.WARNING, "같은 tier 노드 간 디스크 사용률 편차",
            observed=" / ".join("%s tier 최대 %.1f%% · 최소 %.1f%% (편차 %.1f%%p)" % (t, mx, mn, mx - mn)
                                for t, mx, mn in gaps),
            impact="특정 노드만 먼저 워터마크에 도달해 전체 쓰기 용량이 제한됩니다. "
                   "샤드 크기 편차나 allocation filter 가 흔한 원인입니다.",
            recommend="대형 인덱스의 샤드 분포와 allocation 설정(exclude/require/tier)을 확인합니다.",
            evidence=ev, source="nodes_stats.json"))
    if not out:
        out.append(Finding("DISK-001", CAT, Severity.OK, "디스크 여유 정상",
                           observed="모든 데이터 노드가 워터마크 이하입니다.",
                           evidence=ev, source="nodes_stats.json"))
    return out


IMPORTANT_POOLS = ("write", "search", "search_worker", "get", "bulk", "index",
                   "management", "refresh", "flush", "force_merge", "snapshot",
                   "warmer", "system_write", "system_read", "esql_worker",
                   "search_coordination", "write_coordination")


def r_thread_pools(ctx):
    """모든 스레드풀의 누적 rejected. 합계 > 0 → 주의, 합계 >= rejected_crit → 치명, 0 → 정상(TP-001). 주요 풀(write/search/get 등)의 queue > 0 → 참고(TP-002)."""
    rejected_rows, queue_rows = [], []
    total_rej = 0
    for n in ctx.nodes:
        for pool, st in items(dig(n.stats, "thread_pool")):
            rej = num(st, "rejected")
            if rej > 0:
                total_rej += rej
                rejected_rows.append([n.name, pool, fmt_num(rej), fmt_num(st.get("completed")),
                                      st.get("active"), st.get("queue"), st.get("largest")])
            q, threads = num(st, "queue"), num(st, "threads")
            if pool in IMPORTANT_POOLS and q > 0 and threads:
                queue_rows.append([n.name, pool, q, st.get("active"), threads])
    out = []
    if rejected_rows:
        rejected_rows.sort(key=lambda r: -int(str(r[2]).replace(",", "")))
        sev = Severity.CRITICAL if total_rej >= ctx.t["rejected_crit"] else Severity.WARNING
        pools = sorted(set(r[1] for r in rejected_rows))
        out.append(Finding(
            "TP-001", CAT, sev, "스레드풀 rejection 발생",
            observed="누적 rejection %s건, 대상 풀: %s" % (fmt_num(total_rej), ", ".join(pools)),
            impact="rejection 은 클라이언트에 429 로 반환되어 데이터 유실(재시도 없는 경우)이나 "
                   "수집 지연으로 이어집니다. 누적값이므로 최근 발생 여부는 별도 확인이 필요합니다.",
            recommend="write 풀이면 bulk 크기 축소·동시성 조절·노드 증설, search 풀이면 "
                      "무거운 쿼리 튜닝과 샤드 수 축소가 우선입니다. 큐 크기를 키우는 것은 "
                      "지연을 뒤로 미룰 뿐 해결책이 아닙니다.",
            evidence=table(["node", "pool", "rejected", "completed", "active", "queue", "largest"],
                           rejected_rows[: ctx.t["top_n"]]),
            refs=[DOC_TP], source="nodes_stats.json"))
    else:
        out.append(Finding("TP-001", CAT, Severity.OK, "스레드풀 rejection 없음",
                           observed="모든 노드/풀의 누적 rejection 이 0입니다.",
                           source="nodes_stats.json"))
    if queue_rows:
        out.append(Finding(
            "TP-002", CAT, Severity.INFO, "수집 시점 큐 적체",
            observed="큐에 대기 중인 작업이 있는 풀 %d건." % len(queue_rows),
            impact="순간값이지만 반복 관측되면 해당 풀이 병목입니다.",
            recommend="동일 풀에서 rejection 이 함께 보이면 우선 조치 대상입니다.",
            evidence=table(["node", "pool", "queue", "active", "threads"],
                           queue_rows[: ctx.t["top_n"]]),
            source="nodes_stats.json"))
    return out


def r_breakers(ctx):
    """breaker.tripped >= breaker_tripped_warn → 치명(BRK-001). 발동 이력은 없고 estimated / limit >= 70% → 주의(BRK-002)."""
    rows, tripped = [], []
    for n in ctx.nodes:
        for name, br in items(dig(n.stats, "breakers")):
            t = num(br, "tripped")
            est = num(br, "estimated_size_in_bytes")
            lim = num(br, "limit_size_in_bytes")
            use = pct(est, lim)
            if t >= ctx.t["breaker_tripped_warn"]:
                tripped.append([n.name, name, fmt_num(t), fmt_bytes(est), fmt_bytes(lim),
                                "%.1f%%" % use if use else "-"])
            elif use and use >= 70:
                rows.append([n.name, name, fmt_num(t), fmt_bytes(est), fmt_bytes(lim), "%.1f%%" % use])
    out = []
    if tripped:
        out.append(Finding(
            "BRK-001", CAT, Severity.CRITICAL, "Circuit breaker 발동 이력",
            observed="발동 이력이 있는 브레이커 %d건." % len(tripped),
            impact="요청이 거부되며(429/CircuitBreakingException) 해당 쿼리·bulk 는 실패합니다. "
                   "parent 브레이커가 발동했다면 heap 압박이 실재한다는 강한 신호입니다.",
            recommend="fielddata 브레이커면 text 필드 정렬/집계를 keyword 로 전환, "
                      "request 면 대형 집계 분할, inflight_requests 면 bulk/요청 크기 축소가 기본 조치입니다.",
            evidence=table(["node", "breaker", "tripped", "estimated", "limit", "사용률"], tripped),
            source="nodes_stats.json"))
    if rows:
        out.append(Finding(
            "BRK-002", CAT, Severity.WARNING, "Circuit breaker 사용률 높음",
            observed="한도의 70%% 이상을 사용 중인 브레이커 %d건." % len(rows),
            impact="조금만 더 큰 요청이 들어오면 거부됩니다.",
            recommend="해당 브레이커 유형에 맞춰 요청 크기와 메모리 사용 패턴을 조정합니다.",
            evidence=table(["node", "breaker", "tripped", "estimated", "limit", "사용률"], rows),
            source="nodes_stats.json"))
    return out


def r_indexing_pressure(ctx):
    """indexing_pressure.memory.total 의 *_rejections(coordinating/primary/replica) 중 하나라도 > 0 → 주의."""
    rows = []
    for n in ctx.nodes:
        mem = dig(n.stats, "indexing_pressure", "memory", default={}) or {}
        tot = mem.get("total") or {}
        rej = {k: v for k, v in tot.items() if k.endswith("rejections") and v}
        if rej:
            rows.append([n.name, ", ".join("%s=%s" % (k, fmt_num(v)) for k, v in rej.items()),
                         fmt_bytes(dig(mem, "current", "all_in_bytes")),
                         fmt_bytes(mem.get("limit_in_bytes"))])
    if not rows:
        return []
    return [Finding(
        "IP-001", CAT, Severity.WARNING, "Indexing pressure rejection",
        observed="색인 메모리 한도 초과로 거부된 요청이 있는 노드 %d대." % len(rows),
        impact="coordinating/primary/replica 단계에서 bulk 요청이 거부됩니다. "
               "클라이언트가 재시도하지 않으면 데이터 유실입니다.",
        recommend="bulk 요청 크기(5~15MB 권장)와 동시 전송 수를 줄이고, 필요 시 색인 노드를 증설합니다.",
        evidence=table(["node", "rejections", "current", "limit"], rows),
        source="nodes_stats.json")]


def r_fielddata(ctx):
    """노드 fielddata 메모리 / heap_max >= fielddata_heap_pct_warn → 주의(FD-001). fielddata.json 에서 가장 큰 필드가 64MB 초과 → 참고(FD-002)."""
    rows = []
    for n in ctx.nodes:
        fd = dig(n.stats, "indices", "fielddata", default={}) or {}
        size = num(fd, "memory_size_in_bytes")
        ev = num(fd, "evictions")
        hm = n.heap_max or 0
        p = pct(size, hm)
        if size and p and p >= ctx.t["fielddata_heap_pct_warn"]:
            rows.append([n.name, fmt_bytes(size), "%.1f%%" % p, fmt_num(ev)])
    out = []
    if rows:
        out.append(Finding(
            "FD-001", CAT, Severity.WARNING, "fielddata 가 heap 을 과점",
            observed="heap 대비 %d%% 이상 fielddata 를 사용하는 노드 %d대."
                     % (ctx.t["fielddata_heap_pct_warn"], len(rows)),
            impact="fielddata 는 heap 에 상주합니다. text 필드 집계/정렬이 원인인 경우가 대부분이며, "
                   "해제되지 않으면 만성적 heap 압박을 만듭니다.",
            recommend="text 필드 대신 keyword 하위 필드로 집계/정렬하도록 쿼리를 수정합니다. "
                      "불가피하면 indices.fielddata.cache.size 로 상한을 둡니다.",
            evidence=table(["node", "fielddata", "heap 대비", "evictions"], rows),
            source="nodes_stats.json"))
    # 필드별 상위 소비자
    top = []
    for r in dicts(ctx.fielddata_cat):
        from ..util import parse_bytes
        b = parse_bytes(r.get("size"))
        if b:
            top.append([r.get("node"), r.get("field"), fmt_bytes(b), b])
    if top:
        top.sort(key=lambda r: -r[3])
        if top[0][3] > 64 * 1024 * 1024:
            out.append(Finding(
                "FD-002", CAT, Severity.INFO, "fielddata 상위 소비 필드",
                observed="가장 큰 fielddata 필드: %s (%s)" % (top[0][1], top[0][2]),
                impact="해당 필드에 대한 집계/정렬이 heap 사용의 직접 원인입니다.",
                recommend="필드 타입과 쿼리 사용처를 확인합니다.",
                evidence=table(["node", "field", "size"], [r[:3] for r in top[: ctx.t["top_n"]]]),
                source="fielddata.json"))
    return out


def r_ingest_failures(ctx):
    """ingest.total.failed >= ingest_failed_warn 인 노드가 있으면 주의. 실패 파이프라인별 건수를 근거로 제시."""
    rows = []
    for n in ctx.nodes:
        tot = dig(n.stats, "ingest", "total", default={}) or {}
        failed = num(tot, "failed")
        if failed >= ctx.t["ingest_failed_warn"]:
            rows.append([n.name, fmt_num(failed), fmt_num(tot.get("count")),
                         fmt_ms(tot.get("time_in_millis"))])
    pipe_rows = []
    for n in ctx.nodes:
        for pname, p in items(dig(n.stats, "ingest", "pipelines")):
            if (num(p, "failed")) > 0:
                pipe_rows.append([n.name, pname, fmt_num(p.get("failed")), fmt_num(p.get("count"))])
    if not rows:
        return []
    pipe_rows.sort(key=lambda r: -int(str(r[2]).replace(",", "")))
    return [Finding(
        "ING-001", CAT, Severity.WARNING, "Ingest 파이프라인 처리 실패",
        observed="실패 건수가 있는 노드 %d대, 실패 파이프라인 %d개." % (len(rows), len(pipe_rows)),
        impact="파이프라인 실패는 문서 누락 또는 원본 그대로 저장되는 결과를 낳아, "
               "필드 파싱이 필요한 대시보드/탐지룰이 조용히 오동작합니다.",
        recommend="실패 파이프라인의 on_failure 처리와 입력 데이터 형식을 확인합니다.",
        evidence=table(["node", "pipeline", "failed", "count"], pipe_rows[: ctx.t["top_n"]])
        if pipe_rows else table(["node", "failed", "count", "time"], rows),
        source="nodes_stats.json")]


def r_node_heterogeneity(ctx):
    """같은 tier(데이터 역할 조합) 안에서 heap 또는 CPU 수가 다르면 주의(NODE-001/002).

    tier 가 다르면 스펙이 다른 것이 정상 설계이므로 tier 간 차이는 판정하지 않고, tier 별 스펙 표만 참고로 보고한다
    (NODE-003). 같은 tier 에서는 샤드가 균등 분배되므로 작은 노드가 먼저 포화되어 그 tier 의 처리 한계가 된다.
    """
    tiers = ctx.data_tiers()
    if not tiers:
        return []
    out, rows_in, rows_all = [], [], []
    for tier, nodes in tiers.items():
        heaps = collections.Counter(fmt_bytes(n.heap_max) for n in nodes if n.heap_max)
        cpus = collections.Counter(n.processors for n in nodes if n.processors)
        rows_all.append([tier, len(nodes), ", ".join("%s(%d대)" % kv for kv in heaps.items()),
                         ", ".join("%s코어(%d대)" % kv for kv in cpus.items())])
        if len(heaps) > 1 or len(cpus) > 1:
            for n in nodes:
                rows_in.append([tier, n.name, fmt_bytes(n.heap_max), n.processors, fmt_bytes(n.ram_total)])
    if rows_in:
        out.append(Finding(
            "NODE-001", CAT, Severity.WARNING, "같은 tier 안에서 노드 스펙 불균일",
            observed="heap 또는 CPU 수가 노드마다 다른 tier: %s"
                     % ", ".join(sorted(set(r[0] for r in rows_in))),
            impact="같은 tier 안에서는 샤드가 거의 균등하게 배치됩니다. 작은 노드가 먼저 heap·CPU 한계에 도달해 "
                   "그 tier 전체의 처리 상한이 됩니다.",
            recommend="같은 tier 의 노드는 동일 스펙으로 맞춥니다. 증설·교체 중이라면 완료 후 다시 확인합니다.",
            evidence=table(["tier", "node", "heap", "cpu", "RAM"], rows_in),
            source="nodes.json / nodes_stats.json"))
    if len(tiers) > 1:
        out.append(Finding(
            "NODE-003", CAT, Severity.INFO, "tier 별 노드 스펙",
            observed="데이터 tier %d개: %s" % (len(tiers), ", ".join("%s %d대" % (t, len(v)) for t, v in tiers.items())),
            impact="tier 마다 스펙이 다른 것은 정상 설계입니다(hot 은 CPU·빠른 디스크, cold/frozen 은 용량 위주). "
                   "tier 간 샤드 수·디스크 사용률·부하 차이도 이 전제로 해석해야 합니다.",
            recommend="tier 별 역할에 맞는 스펙인지(예: hot 에 색인 부하 대비 충분한 CPU) 확인합니다.",
            evidence=table(["tier", "노드 수", "heap 분포", "CPU 분포"], rows_all),
            source="nodes.json"))
    return out


RULES = [
    r_heap_usage, r_heap_sizing, r_gc, r_os, r_disk, r_thread_pools,
    r_breakers, r_indexing_pressure, r_fielddata, r_ingest_failures,
    r_node_heterogeneity,
]
