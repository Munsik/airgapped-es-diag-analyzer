# -*- coding: utf-8 -*-
"""OS 설정 분석: local/remote 모드 번들의 syscalls/ 디렉터리.

local 모드는 진단을 실행한 호스트 한 대의 값만 담는다. 클러스터의 다른 노드에는 적용되지 않는다.
"""

import re

from ..model import Finding, Severity, table

CAT = "OS 설정"

_MIN_MAP_COUNT = 262144      # [공식] bootstrap check(maximum map count check) 최소값
_MIN_NOFILE = 65535          # [공식] max file descriptors 최소값
_MIN_NPROC = 4096            # [공식] 스레드 생성 한도 최소값
_OOM_RE = re.compile(r"out of memory: kill(?:ed)? process \d+ \(([^)]*)\)|oom-kill:|invoked oom-killer", re.I)
_SCOPE = "이 값은 진단을 실행한 호스트 한 대의 것입니다(local 모드). 다른 노드는 각자 확인해야 합니다."


def _sysctl(ctx):
    txt = ctx.b.text("syscalls/sysctl.txt") or ""
    out = {}
    for ln in txt.splitlines():
        if "=" in ln and not ln.lstrip().startswith("#"):
            k, _, v = ln.partition("=")
            out[k.strip()] = v.strip()
    return out


def _proc_limits(ctx):
    txt = ctx.b.text("syscalls/proc-limit.txt") or ""
    out = {}
    for ln in txt.splitlines():
        m = re.match(r"^(Max [a-z ]+?)\s{2,}(\S+)\s+(\S+)", ln)
        if m:
            out[m.group(1).strip().lower()] = (m.group(2), m.group(3))
    return out


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def r_os_config(ctx):
    """syscalls/sysctl.txt 의 vm.max_map_count 가 262144 미만 → 치명(SYS-001), 이상 → 정상. sysctl 의 vm.swappiness 가 1 초과이고 swap_total > 0 이며 mlockall 이 true 가 아님 → 참고(SYS-002). syscalls/proc-limit.txt 의 Max open files 가 65535 미만 또는 Max processes 가 4096 미만(soft 기준) → 치명(SYS-003), 충족 → 정상. syscalls/dmesg.txt 에 OOM killer 기록이 있고 대상 프로세스가 java/elasticsearch → 치명, 그 외 프로세스 → 주의(SYS-004), 기록 없음 → 정상."""
    out = []
    sc = _sysctl(ctx)
    pl = _proc_limits(ctx)
    if not sc and not pl and not ctx.b.exists("syscalls/dmesg.txt"):
        return out

    mmc = _int(sc.get("vm.max_map_count"))
    if mmc is not None:
        if mmc < _MIN_MAP_COUNT:
            out.append(Finding(
                "SYS-001", CAT, Severity.CRITICAL, "vm.max_map_count 가 최소 요건 미달",
                observed="vm.max_map_count = %d (최소 %d). %s" % (mmc, _MIN_MAP_COUNT, _SCOPE),
                impact="production 모드에서 bootstrap check 가 실패해 노드가 기동하지 않거나, mmap 실패로 샤드가 깨질 수 있습니다.",
                recommend="`sysctl -w vm.max_map_count=1048576` 후 /etc/sysctl.d/ 에 영구 반영합니다(262144 이상이면 요건 충족).",
                source="syscalls/sysctl.txt"))
        else:
            out.append(Finding("SYS-001", CAT, Severity.OK, "vm.max_map_count 충족",
                               observed="vm.max_map_count = %d (최소 %d)" % (mmc, _MIN_MAP_COUNT),
                               source="syscalls/sysctl.txt"))

    sw = _int(sc.get("vm.swappiness"))
    if sw is not None and sw > 1:
        swap_nodes = [n for n in ctx.nodes if n.swap_total and n.mlockall is not True]
        if swap_nodes:
            out.append(Finding(
                "SYS-002", CAT, Severity.INFO, "swap 이 있는데 vm.swappiness 가 높음",
                observed="vm.swappiness = %d, swap 설정 노드: %s. %s" % (sw, ", ".join(n.name for n in swap_nodes), _SCOPE),
                impact="swap 을 완전히 끌 수 없다면 공식 권고는 vm.swappiness=1 입니다. 값이 크면 JVM heap 이 swap out 될 여지가 커집니다.",
                recommend="swap 비활성화가 가장 안전합니다. 어렵다면 `vm.swappiness=1` 또는 bootstrap.memory_lock: true 를 적용합니다(OS-002 참조).",
                source="syscalls/sysctl.txt"))

    if pl:
        nf = _int(pl.get("max open files", (None,))[0])
        np_ = _int(pl.get("max processes", (None,))[0])
        bad, rows = [], []
        for label, val, need in (("Max open files", nf, _MIN_NOFILE), ("Max processes", np_, _MIN_NPROC)):
            if val is None:
                continue
            rows.append([label, val, need, "미달" if val < need else "충족"])
            if val < need:
                bad.append("%s %d (최소 %d)" % (label, val, need))
        if bad:
            out.append(Finding(
                "SYS-003", CAT, Severity.CRITICAL, "Elasticsearch 프로세스 한도가 최소 요건 미달",
                observed="; ".join(bad) + ". " + _SCOPE,
                impact="열린 파일 한도가 낮으면 샤드·세그먼트 파일 오픈 실패와 bootstrap check 실패가, 프로세스 한도가 낮으면 스레드 생성 실패가 발생합니다.",
                recommend="systemd 서비스는 LimitNOFILE / LimitNPROC 로, 그 외에는 limits.conf(nofile, nproc)로 올립니다. 재기동 후 다시 수집해 확인합니다.",
                evidence=table(["항목", "soft 한도", "최소", "판정"], rows),
                source="syscalls/proc-limit.txt"))
        elif rows:
            out.append(Finding("SYS-003", CAT, Severity.OK, "프로세스 한도 충족",
                               observed=", ".join("%s %s" % (r[0], r[1]) for r in rows),
                               evidence=table(["항목", "soft 한도", "최소", "판정"], rows),
                               source="syscalls/proc-limit.txt"))

    dm = ctx.b.text("syscalls/dmesg.txt")
    if dm is not None:
        hits = [(m.group(1) or "") for m in _OOM_RE.finditer(dm)]
        if hits:
            java = [h for h in hits if re.search(r"java|elasticsearch", h, re.I)]
            out.append(Finding(
                "SYS-004", CAT, Severity.CRITICAL if java else Severity.WARNING, "커널 OOM killer 기록",
                observed="dmesg 에서 OOM killer 기록 %d건. 종료된 프로세스: %s. %s"
                         % (len(hits), ", ".join(sorted(set(h for h in hits if h))) or "확인 불가", _SCOPE),
                impact="호스트 메모리가 부족해 커널이 프로세스를 강제 종료했습니다. Elasticsearch 가 대상이면 노드가 예고 없이 이탈합니다.",
                recommend="heap 이 물리 메모리의 50% 이하인지, 같은 호스트의 다른 프로세스와 off-heap 사용량을 함께 점검합니다.",
                source="syscalls/dmesg.txt"))
        else:
            out.append(Finding("SYS-004", CAT, Severity.OK, "커널 OOM killer 기록 없음",
                               observed="dmesg 에 OOM killer 기록이 없습니다.", source="syscalls/dmesg.txt"))
    return out


RULES = [r_os_config]
