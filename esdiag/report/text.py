# -*- coding: utf-8 -*-
"""콘솔 / 마크다운 출력."""

from ..model import Severity

MARK = {
    Severity.CRITICAL: "[치명]",
    Severity.WARNING: "[주의]",
    Severity.INFO: "[참고]",
    Severity.OK: "[정상]",
}


def console(result, show_ok=True, width=100):
    f = result.facts()
    lines = []
    bar = "=" * width
    lines.append(bar)
    lines.append("Elasticsearch 진단 분석 결과")
    lines.append(bar)
    lines.append("클러스터      : %s (%s)" % (f["cluster_name"], f["version"]))
    lines.append("수집 시각     : %s  /  수집 모드: %s  /  서버 로그 포함: %s"
                 % (f["collected_at"], f["diag_type"], "예" if f["has_logs"] else "아니오"))
    lines.append("구성          : 노드 %s대 (데이터 %s / 마스터후보 %s), 인덱스 %s, 샤드 %s, 저장 %s"
                 % (f["nodes_total"], f["data_nodes"], f["master_nodes"],
                    f["indices"], f["shards"], f["store"]))
    lines.append("클러스터 상태 : %s" % f["status"])
    lines.append("판정 기준     : esdiag v%s / %s" % (f.get("tool_version"), f.get("baseline")))
    lines.append("")
    c = result.counts
    lines.append("종합 판정     : %s" % result.grade)
    lines.append("판정 건수     : 치명 %d / 주의 %d / 참고 %d / 정상 %d"
                 % (c[Severity.CRITICAL], c[Severity.WARNING], c[Severity.INFO], c[Severity.OK]))
    lines.append(bar)
    lines.append("")

    lines.append("■ 영역별 점검 결과")
    for a in result.area_summary():
        lines.append("  %-14s %-10s 치명 %d / 주의 %d / 참고 %d / 정상 %d"
                     % (a["area"], a["status"], a["critical"], a["warning"], a["info"], a["ok"]))
    lines.append("")
    ds = getattr(result, "diff_summary", None)
    if ds:
        lines.append("■ 이전 번들 대비 변화 (%s)"
                     % (("%.1f시간 간격" % ds["hours"]) if ds.get("hours") else "간격 불명"))
        lines.extend("  " + ln for ln in _ascii_table(
            {"columns": ds["columns"], "rows": ds["rows"]}, max_rows=20))
        lines.append("")

    act = result.actionable()
    if act:
        lines.append("■ 조치 우선순위")
        for i, fd in enumerate(act, 1):
            lines.append("  %2d. %s %s — %s" % (i, MARK[fd.severity], fd.title, fd.observed))
        lines.append("")

    cur = None
    for fd in result.by_severity():
        if fd.severity == Severity.OK and not show_ok:
            continue
        if fd.category != cur:
            cur = fd.category
            lines.append("")
            lines.append("── %s " % cur + "─" * max(0, width - len(cur) - 4))
        lines.append("")
        lines.append("%s %s  (%s · %s)" % (MARK[fd.severity], fd.title, fd.id, fd.basis or ""))
        if fd.observed:
            lines.append("   관측 : %s" % fd.observed)
        if fd.impact:
            lines.append("   영향 : %s" % fd.impact)
        if fd.recommend:
            lines.append("   권고 : %s" % fd.recommend)
        if fd.evidence and fd.evidence.get("rows"):
            lines.append("   근거 :")
            lines.extend("      " + ln for ln in _ascii_table(fd.evidence))
        if fd.source:
            lines.append("   출처 : %s" % fd.source)
    lines.append("")
    sk = getattr(result.ctx, "skipped_rules", [])
    if sk:
        lines.append("※ 입력 파일 미수집으로 판정하지 않은 룰 %d개 (문제 없음이 아니라 확인 불가): %s"
                     % (len(sk), ", ".join(x["rule"].split(".")[-1] for x in sk)))
    if result.errors:
        lines.append("※ 도구 오류로 판정하지 못한 룰 %d개: %s (--debug 로 상세 확인)"
                     % (len(result.errors), ", ".join(x["rule"].split(".")[-1] for x in result.errors)))
    return "\n".join(lines)


def _ascii_table(ev, max_rows=15):
    cols = [str(c) for c in ev["columns"]]
    rows = [[("" if v is None else str(v)) for v in r] for r in ev["rows"][:max_rows]]
    widths = [len(c) for c in cols]
    for r in rows:
        for i, v in enumerate(r[:len(widths)]):
            widths[i] = max(widths[i], min(len(v), 60))
    def fmt(r):
        return "  ".join(str(v)[:60].ljust(widths[i]) for i, v in enumerate(r[:len(widths)]))
    out = [fmt(cols), "  ".join("-" * w for w in widths)]
    out.extend(fmt(r) for r in rows)
    if len(ev["rows"]) > max_rows:
        out.append("... 외 %d행" % (len(ev["rows"]) - max_rows))
    return out


def markdown(result, show_ok=True):
    f = result.facts()
    c = result.counts
    md = []
    md.append("# Elasticsearch 진단 분석 결과")
    md.append("")
    md.append("| 항목 | 값 |")
    md.append("| --- | --- |")
    md.append("| 클러스터 | %s |" % f["cluster_name"])
    md.append("| 버전 | %s |" % f["version"])
    md.append("| 수집 시각 | %s |" % f["collected_at"])
    md.append("| 수집 모드 | %s (서버 로그 %s) |" % (f["diag_type"],
                                              "포함" if f["has_logs"] else "미포함"))
    md.append("| 구성 | 노드 %s대 (데이터 %s / 마스터후보 %s) |"
              % (f["nodes_total"], f["data_nodes"], f["master_nodes"]))
    md.append("| 규모 | 인덱스 %s, 샤드 %s, 문서 %s, 저장 %s |"
              % (f["indices"], f["shards"], f["docs"], f["store"]))
    md.append("| 클러스터 상태 | %s |" % f["status"])
    md.append("| 판정 기준 | esdiag v%s / %s |" % (f.get("tool_version"), f.get("baseline")))
    md.append("| 종합 판정 | **%s** |" % result.grade)
    md.append("| 판정 건수 | 치명 %d / 주의 %d / 참고 %d / 정상 %d |"
              % (c[Severity.CRITICAL], c[Severity.WARNING], c[Severity.INFO], c[Severity.OK]))
    md.append("")
    md.append("## 영역별 점검 결과")
    md.append("")
    md.append("| 영역 | 상태 | 치명 | 주의 | 참고 | 정상 | 포함 분류 |")
    md.append("| --- | --- | --- | --- | --- | --- | --- |")
    for a in result.area_summary():
        md.append("| %s | %s | %d | %d | %d | %d | %s |" % (a["area"], a["status"], a["critical"], a["warning"],
                                                         a["info"], a["ok"], " · ".join(a["categories"])))
    md.append("")
    ds = getattr(result, "diff_summary", None)
    if ds:
        md.append("## 이전 번들 대비 변화")
        md.append("")
        md.append("| " + " | ".join(ds["columns"]) + " |")
        md.append("| " + " | ".join("---" for _ in ds["columns"]) + " |")
        for r in ds["rows"]:
            md.append("| " + " | ".join(str(x) for x in r) + " |")
        md.append("")
    act = result.actionable()
    if act:
        md.append("## 조치 우선순위")
        md.append("")
        md.append("| # | 심각도 | 항목 | 관측 |")
        md.append("| --- | --- | --- | --- |")
        for i, fd in enumerate(act, 1):
            md.append("| %d | %s | %s | %s |" % (i, Severity.LABEL_KO[fd.severity],
                                                 fd.title, fd.observed.replace("|", "/")))
        md.append("")
    cur = None
    for fd in result.by_severity():
        if fd.severity == Severity.OK and not show_ok:
            continue
        if fd.category != cur:
            cur = fd.category
            md.append("")
            md.append("## %s" % cur)
        md.append("")
        md.append("### [%s] %s  `%s` · %s" % (Severity.LABEL_KO[fd.severity], fd.title, fd.id,
                                                fd.basis or ""))
        md.append("")
        if fd.observed:
            md.append("- **관측**: %s" % fd.observed)
        if fd.impact:
            md.append("- **영향**: %s" % fd.impact)
        if fd.recommend:
            md.append("- **권고**: %s" % fd.recommend)
        if fd.source:
            md.append("- **출처**: `%s`" % fd.source)
        if fd.refs:
            md.append("- **참고**: " + ", ".join("[%s](%s)" % (t, u) for t, u in fd.refs))
        if fd.evidence and fd.evidence.get("rows"):
            md.append("")
            md.append("| " + " | ".join(str(x) for x in fd.evidence["columns"]) + " |")
            md.append("| " + " | ".join("---" for _ in fd.evidence["columns"]) + " |")
            for r in fd.evidence["rows"][:20]:
                md.append("| " + " | ".join(("" if v is None else str(v)).replace("|", "/")
                                            for v in r) + " |")
    md.append("")
    sk = getattr(result.ctx, "skipped_rules", [])
    if sk:
        md.append("## 입력 미수집으로 판정하지 않은 항목")
        md.append("")
        md.append("| 룰 | 필요한 파일 |")
        md.append("| --- | --- |")
        for x in sk:
            md.append("| %s | %s |" % (x["rule"], " / ".join(x["missing"])))
        md.append("")
    if result.errors:
        md.append("## 도구 오류로 판정하지 못한 항목")
        md.append("")
        md.append("클러스터 문제가 아니라 이 도구가 해당 번들의 데이터 형식을 처리하지 못한 것입니다. 해당 룰은 '확인하지 못함' 입니다.")
        md.append("")
        md.append("| 룰 | 오류 |")
        md.append("| --- | --- |")
        for x in result.errors:
            last = [ln for ln in x["error"].strip().splitlines() if ln.strip()][-1:] or [""]
            md.append("| %s | %s |" % (x["rule"], last[0].replace("|", "/")[:200]))
        md.append("")
    md.append("## 노드 요약")
    md.append("")
    md.append("| 노드 | 역할 | 버전 | heap 사용률 | heap | RAM | CPU | load15m | 디스크 사용률 | 디스크 | zone |")
    md.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for n in f["nodes"]:
        md.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            n["name"], n["roles"], n["version"],
            ("%s%%" % n["heap_used_pct"]) if n["heap_used_pct"] is not None else "-",
            n["heap_max"], n["ram"], n["cpu"], n["load15"],
            n["disk_used_pct"], n["disk_total"], n["zone"]))
    md.append("")
    return "\n".join(md)
