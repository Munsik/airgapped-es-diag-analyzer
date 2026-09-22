# -*- coding: utf-8 -*-
"""런타임 증거 분석: hot threads, 서버 로그(local/remote 모드)."""

import collections
import re

from ..model import Finding, Severity, table
from ..util import fmt_num, truncate

CAT = "런타임"

_NODE_RE = re.compile(r"^:::\s*\{([^}]*)\}")
_THREAD_RE = re.compile(
    r"^\s*([\d.]+)%\s*(?:\[([^\]]*)\]\s*)?\(([^)]*)\)\s*cpu usage by thread\s*'([^']+)'")

# 스택 프레임 -> 원인 분류
# 맥락 시그니처: 스택 어디에 있든 작업의 성격을 결정하는 호출(먼저 스택 전체에서 찾는다).
# 예) 맨 위 프레임이 JSON 복사여도 그 호출자가 ignored source 저장이면 작업의 성격은 '문서 파싱' 이다.
_CONTEXT = [
    ("OneMergeProgress.pauseNanos", "merge 대기(throttle)", "merge 가 I/O throttle 로 대기 중입니다(CPU 사용이 아니라 대기 시간). 색인량 대비 디스크 대역을 확인합니다."),
    ("org.elasticsearch.grok", "ingest grok 파싱", "ingest pipeline 의 grok 처리가 CPU 를 점유합니다. 패턴 단순화(dissect 전환, 앵커 사용)와 파이프라인 분리를 검토합니다."),
    ("org.elasticsearch.dissect", "ingest dissect 파싱", "ingest pipeline 의 dissect 처리 비용입니다."),
    ("org.elasticsearch.painless", "painless 스크립트", "painless 스크립트가 CPU 를 점유합니다. runtime field·스크립트 정렬·ingest script 를 점검합니다."),
    ("addIgnoredFieldFromContext", "문서 파싱: 무시된 필드 값 저장(synthetic _source)",
     "synthetic _source 인덱스가 매핑되지 않은 필드(필드 한도 초과로 무시된 동적 필드, ignore_above 등)의 값을 따로 저장하는 비용입니다. "
     "MAP-004(필드 한도 근접)·DISK-007(_source 모드)과 함께 보고, 불필요한 동적 필드 유입을 줄이는 것을 검토합니다."),
    ("GlobalOrdinals", "전역 서수 생성", "keyword 집계의 global ordinals 생성 비용입니다. eager_global_ordinals 설정을 검토합니다."),
    ("RegExp", "정규식/wildcard 쿼리", "regexp/wildcard 계열 쿼리는 매우 비쌉니다. 쿼리 구조 변경이 필요합니다."),
]

# 일반 시그니처: 맥락 시그니처가 없을 때 스택 위쪽(실행 중) 프레임부터 대조한다.
_SIGNATURES = [
    ("org.elasticsearch.ingest", "ingest pipeline", "ingest pipeline 처리 비용입니다. 무거운 processor(grok, script, enrich)를 확인합니다."),
    ("org.elasticsearch.search.aggregations", "집계 연산", "aggregation 비용이 큽니다. cardinality/terms size 를 확인합니다."),
    ("org.apache.lucene.search", "검색 실행", "Lucene 검색 실행이 CPU 를 점유합니다. 쿼리 비용과 샤드 수를 함께 봅니다."),
    ("Lucene Merge Thread", "세그먼트 merge", "색인량 대비 merge 가 밀리고 있습니다. 디스크 대역폭 또는 샤드당 색인량을 확인합니다."),
    ("org.apache.lucene.index", "Lucene 색인/merge", "세그먼트 기록·merge 비용입니다."),
    ("org.elasticsearch.index.mapper", "문서 파싱·매핑", "문서 파싱 또는 동적 매핑 갱신 비용입니다."),
    ("org.elasticsearch.index.engine", "색인 엔진", "색인 처리 자체가 CPU 를 점유하고 있습니다."),
    ("org.elasticsearch.xpack.ml", "ML 처리", "ML 작업이 CPU 를 점유합니다."),
    ("java.util.zip", "압축/해제", "네트워크 압축 또는 스냅샷 압축 비용입니다."),
    ("xcontent", "JSON 직렬화", "요청·응답 JSON 처리 비용입니다(대형 bulk·문서에서 커짐)."),
    ("org.elasticsearch.transport", "전송 계층", "네트워크 전송/직렬화 비용입니다."),
]


def _classify(stack, tname):
    """1) 맥락 시그니처를 스택 전체에서 찾는다(작업 성격 결정), 2) 없으면 위쪽 프레임부터 일반 시그니처 대조."""
    for sig, label, hint in _CONTEXT:
        if any(sig in frame for frame in stack):
            return label, hint
    for frame in stack:
        for sig, label, hint in _SIGNATURES:
            if sig in frame:
                return label, hint
    for sig, label, hint in _CONTEXT + _SIGNATURES:
        if sig in tname:
            return label, hint
    return None, None


_CPU_RE = re.compile(r"cpu=([\d.]+)%")


def parse_hot_threads(text):
    """(node, pct, thread_name, cpu_desc, stack_head) 목록 반환."""
    entries = []
    node = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = _NODE_RE.match(ln)
        if m:
            node = m.group(1).split("}{")[0].strip("{ ")
            i += 1
            continue
        m = _THREAD_RE.match(ln)
        if m:
            pct = float(m.group(1))
            detail = m.group(2) or ""
            cm = _CPU_RE.search(detail)
            if cm:
                pct = float(cm.group(1))      # 'other'(대기) 시간을 빼고 실제 CPU 점유율만 쓴다
            dur = m.group(3) or ""
            tname = m.group(4)
            stack = []
            j = i + 1
            while j < len(lines) and len(stack) < 40:
                s = lines[j]
                if _THREAD_RE.match(s) or _NODE_RE.match(s):
                    break
                s2 = s.strip()
                if s2 and not s2.startswith("Hot threads at"):
                    stack.append(s2)
                j += 1
            entries.append((node, pct, tname, detail or dur, stack))
            i = j
            continue
        i += 1
    return entries


def _frame(stack):
    """대표 스택 프레임 1줄 선택(snapshot 안내 문구는 건너뛴다)."""
    for s in stack:
        if "snapshot" in s.lower():
            continue
        if "org.elasticsearch" in s or "org.apache.lucene" in s:
            return s
    for s in stack:
        if "snapshot" not in s.lower():
            return s
    return stack[0] if stack else ""


def r_hot_threads(ctx):
    """nodes_hot_threads.txt 를 파싱해 스레드별 실제 CPU%(cpu=, 없으면 전체 %)를 추출한다.

    최대 CPU% >= hot_thread_pct_warn → 주의, 그 외 참고. 수집 순간 500ms 스냅샷 하나이므로 단독으로 치명 판정하지 않는다.
    원인 분류는 각 스레드 스택의 위쪽(실행 중) 프레임부터 시그니처(grok·ingest·painless·regexp·집계·검색·merge 등)를
    대조해 처음 맞는 것으로 정한다.
    """
    text = ctx.hot_threads_text
    if not text.strip():
        return []
    entries = parse_hot_threads(text)
    if not entries:
        return []
    busy = [e for e in entries if e[1] >= 0.5]
    top = sorted(busy or entries, key=lambda e: -e[1])[: (ctx.t["top_n"] if busy else 5)]
    rows, causes, hints = [], collections.Counter(), {}
    for e in top:
        label, hint = _classify(e[4], e[2])
        rows.append([e[0], "%.1f%%" % e[1], truncate(e[2], 60), label or "-", truncate(_frame(e[4]), 100)])
    for e in busy:
        label, hint = _classify(e[4], e[2])
        if label:
            causes[label] += 1
            hints[label] = hint
    hottest = top[0][1] if top else 0
    sev = Severity.WARNING if hottest >= ctx.t["hot_thread_pct_warn"] else Severity.INFO
    cause_txt = ", ".join("%s(%d)" % kv for kv in causes.most_common(5)) or "뚜렷한 패턴 없음"
    rec = " ".join(hints[k] for k, _ in causes.most_common(3)) or \
        "수집 순간 CPU 를 점유한 스레드가 없습니다. 부하 시점에 다시 수집하면 정확도가 올라갑니다."
    return [Finding(
        "RT-001", CAT, sev, "Hot threads 분석",
        observed="최상위 스레드 CPU 점유율 %.1f%%. 원인 분류(스레드 수): %s" % (hottest, cause_txt),
        impact="hot threads 는 수집 순간 500ms 의 스냅샷입니다. 한 번의 관측만으로 상시 문제라고 단정할 수 없으므로, "
               "문제 재현 시점에 여러 번 수집해 같은 스택이 반복되는지 확인해야 합니다.",
        recommend=rec,
        evidence=table(["node", "cpu%", "thread", "원인 분류", "대표 스택"], rows),
        source="nodes_hot_threads.txt")]


_LOG_PATTERNS = [
    (r"OutOfMemoryError", Severity.CRITICAL, "OutOfMemoryError",
     "JVM heap 고갈로 노드가 중단되었습니다. heap 압박 원인 제거가 최우선입니다."),
    (r"failed to obtain node lock", Severity.CRITICAL, "노드 락 획득 실패",
     "동일 data 경로에 중복 프로세스가 기동되었거나 비정상 종료 잔여물이 있습니다."),
    (r"master not discovered|no known master node|master_not_discovered",
     Severity.CRITICAL, "마스터 탐색 실패",
     "디스커버리/네트워크 문제로 마스터 선출에 실패했습니다. seed_hosts 와 방화벽을 확인합니다."),
    (r"failed to execute bulk item|MapperParsingException|mapper_parsing_exception",
     Severity.WARNING, "문서 색인 실패(매핑 오류)",
     "필드 타입 충돌 또는 파싱 오류입니다. 수집 측 스키마를 점검합니다."),
    (r"CircuitBreakingException", Severity.CRITICAL, "Circuit breaker 예외",
     "메모리 한도 초과로 요청이 거부되었습니다."),
    (r"EsRejectedExecutionException|rejected execution", Severity.WARNING, "스레드풀 거부",
     "큐 포화로 요청이 거부되었습니다."),
    (r"\[gc\]\[.*\]\[old\]|\[o\.e\.m\.j\.JvmGcMonitorService\].*\[old\]",
     Severity.WARNING, "Old GC 경고 로그",
     "JvmGcMonitorService 가 긴 GC 를 기록했습니다."),
    (r"failed to flush|translog", Severity.INFO, "translog/flush 관련 메시지", ""),
    (r"disk watermark \[.*\] exceeded|flood stage disk watermark",
     Severity.CRITICAL, "디스크 워터마크 초과 로그",
     "디스크 부족으로 샤드 이동 또는 쓰기 차단이 발생했습니다."),
    (r"transport.*Connection reset|NodeDisconnectedException|node_disconnected",
     Severity.WARNING, "노드 간 연결 끊김",
     "네트워크 불안정 또는 GC 로 인한 응답 지연입니다."),
    (r"ShardLockObtainFailedException", Severity.WARNING, "샤드 락 획득 실패",
     "샤드가 이전 상태에서 정리되지 않았습니다."),
]


def r_logs(ctx):
    """logs/ 디렉터리가 없으면 참고(LOG-000). 있으면 파일당 마지막 log_scan_bytes 만 최대 40개 파일 스캔해 고정 패턴(OOM, 긴 old GC, 마스터 미탐색, CircuitBreaking, rejected execution, 워터마크 초과, 노드 연결 끊김, 매핑 파싱 오류 등) 검출. 검출 패턴 중 가장 높은 심각도로 판정(LOG-001), 없으면 정상."""
    files = ctx.b.log_files()
    if not files:
        return [Finding(
            "LOG-000", CAT, Severity.INFO, "서버 로그 미포함 진단 번들",
            observed="diagType=%s 로 수집되어 elasticsearch.log / gc.log 가 포함되지 않았습니다."
                     % (ctx.diag_type or "api"),
            impact="장애 시점의 예외·GC 정지 시간·노드 이탈 기록을 확인할 수 없어, "
                   "원인 확정이 아닌 상태 기반 추정에 머무릅니다.",
            recommend="가능하면 local 또는 remote 모드로 다시 수집하십시오. "
                      "(diagnostics --type local) 로그가 포함되면 이 도구가 자동으로 함께 분석합니다.",
            source="manifest.json")]
    counts = collections.Counter()
    samples = {}
    scanned = 0
    for rel in files[:40]:
        text = ctx.b.read_log(rel, ctx.t["log_scan_bytes"])
        if not text:
            continue
        scanned += 1
        for pat, sev, label, hint in _LOG_PATTERNS:
            rx = re.compile(pat, re.IGNORECASE)
            n = 0
            for ln in text.splitlines():
                if rx.search(ln):
                    n += 1
                    if label not in samples:
                        samples[label] = (rel, truncate(ln.strip(), 220))
            if n:
                counts[(label, sev, hint)] += n
    out = []
    if not counts:
        return [Finding("LOG-001", CAT, Severity.OK, "로그에서 주요 오류 패턴 미검출",
                        observed="로그 파일 %d개를 스캔했으나 알려진 위험 패턴이 없습니다." % scanned,
                        source="logs/")]
    rows = []
    worst = Severity.INFO
    for (label, sev, hint), n in counts.most_common():
        src, sample = samples.get(label, ("", ""))
        rows.append([label, fmt_num(n), sev, truncate(sample, 140)])
        if Severity.ORDER[sev] < Severity.ORDER[worst]:
            worst = sev
    recs = [h for (_l, _s, h), _n in counts.most_common(5) if h]
    out.append(Finding(
        "LOG-001", CAT, worst, "서버 로그 오류 패턴 검출",
        observed="로그 %d개에서 %d종의 위험 패턴이 검출되었습니다." % (scanned, len(counts)),
        impact="로그는 이 도구가 볼 수 있는 유일한 '시점' 증거입니다. 상태 지표와 교차 확인하면 "
               "원인 추정이 확정으로 바뀝니다.",
        recommend=" ".join(recs),
        evidence=table(["패턴", "건수", "심각도", "샘플"], rows[: ctx.t["top_n"]]),
        source="logs/"))
    return out


RULES = [r_hot_threads, r_logs]
