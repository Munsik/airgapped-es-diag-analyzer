# -*- coding: utf-8 -*-
"""Elastic 공식 Support 팀 문의 시 케이스에 기재할 내용을 정리한 요약(Markdown).

분석 리포트와 달리 다음을 지킨다.
  - 치명·주의 판정을 관측 사실과 근거 파일 위주로 정리한다. 도구의 권고 문구는 넣지 않는다.
  - 서버 로그 발췌와 hot threads 스택은 원문이 실리므로 표에서 해당 열을 뺀다.
  - 모든 문자열에 마스킹을 적용하고, 결과에 식별자가 남으면 만들지 않는다(mask.Masker.leaks).
"""

from ..model import Severity
from ..util import truncate

# 원문(로그 줄, 스레드 이름, 스택)이 실리는 근거 열. 요약에서는 뺀다.
DROP_COLUMNS = frozenset(["샘플", "대표 스택", "thread"])
MAX_EVIDENCE_ROWS = 10


class MaskLeak(Exception):
    """마스킹 후에도 식별자가 남아 요약을 만들지 않았다."""

    def __init__(self, leaks):
        Exception.__init__(self, "마스킹되지 않은 식별자 %d건" % len(leaks))
        self.leaks = leaks


def _cell(masker, v):
    s = "" if v is None else str(v)
    return masker.text(s).replace("|", "/").replace("\n", " ")


def _evidence(masker, ev):
    """근거 표를 Markdown 줄 목록으로. 원문 열은 뺀다."""
    if not ev or not ev.get("rows"):
        return []
    cols = list(ev["columns"])
    keep = [i for i, c in enumerate(cols) if str(c) not in DROP_COLUMNS]
    if not keep:
        return []
    rows = ev["rows"][:MAX_EVIDENCE_ROWS]
    out = ["", "| " + " | ".join(_cell(masker, cols[i]) for i in keep) + " |",
           "| " + " | ".join("---" for _ in keep) + " |"]
    for r in rows:
        out.append("| " + " | ".join(_cell(masker, r[i] if i < len(r) else "") for i in keep) + " |")
    if len(ev["rows"]) > MAX_EVIDENCE_ROWS:
        out.append("")
        out.append("(외 %d행 생략)" % (len(ev["rows"]) - MAX_EVIDENCE_ROWS))
    return out


def render(result, masker, level, tool_version):
    """요약 Markdown 문자열. 마스킹 후 식별자가 남으면 MaskLeak 을 일으킨다."""
    f = result.facts()
    c = result.counts
    T = masker.text
    md = []
    md.append("# Elasticsearch 진단 요약 (Elastic 공식 Support 팀 문의 참고용)")
    md.append("")
    md.append("| 항목 | 값 |")
    md.append("| --- | --- |")
    md.append("| 생성 도구 | esdiag v%s — Elastic 공식 도구가 아니며, Elastic 공식 Support 팀의 분석을 대체하지 않습니다 |"
              % tool_version)
    md.append("| 클러스터 | %s |" % _cell(masker, f["cluster_name"]))
    md.append("| 버전 · 배포 | %s · %s |" % (f["version"], f.get("deployment") or "-"))
    md.append("| 수집 | %s · 수집 모드 %s (서버 로그 %s) |"
              % (f.get("collected_display") or f["collected_at"], f["diag_type"],
                 "포함" if f["has_logs"] else "미포함"))
    md.append("| 구성 | 노드 %s대 (데이터 %s / 마스터후보 %s), 인덱스 %s, 샤드 %s, 저장 %s |"
              % (f["nodes_total"], f["data_nodes"], f["master_nodes"], f["indices"], f["shards"], f["store"]))
    md.append("| 클러스터 상태 | %s |" % f["status"])
    md.append("| 종합 판정 | %s (치명 %d / 주의 %d / 참고 %d / 정상 %d) |"
              % (result.grade, c[Severity.CRITICAL], c[Severity.WARNING], c[Severity.INFO], c[Severity.OK]))
    if level == "none":
        md.append("| 마스킹 | 적용하지 않음 |")
    else:
        md.append("| 마스킹 | %s 단계 — 노드·호스트·IP 등을 별칭으로 바꿨습니다. 원래 이름은 별도 매핑 파일에만 있습니다 |"
                  % level)
    md.append("")

    md.append("## 영역별 점검 결과")
    md.append("")
    md.append("| 영역 | 상태 | 치명 | 주의 | 참고 | 정상 |")
    md.append("| --- | --- | --- | --- | --- | --- |")
    for a in result.area_summary():
        md.append("| %s | %s | %d | %d | %d | %d |"
                  % (a["area"], a["status"], a["critical"], a["warning"], a["info"], a["ok"]))
    md.append("")

    act = result.priority()
    md.append("## 케이스에 기재할 판정 (치명·주의)")
    md.append("")
    if not act:
        md.append("치명·주의 판정이 없습니다.")
        md.append("")
    else:
        md.append("| # | ID | 심각도 | 판정 | 근거 구분 | 번들 내 근거 파일 | 관련 판정 |")
        md.append("| --- | --- | --- | --- | --- | --- | --- |")
        for i, (fd, rel) in enumerate(act, 1):
            md.append("| %d | %s | %s | %s | %s | %s | %s |"
                      % (i, fd.id, Severity.LABEL_KO[fd.severity], _cell(masker, fd.title), fd.basis or "-",
                         _cell(masker, fd.source) or "-", ", ".join(r.id for r in rel) or "-"))
        md.append("")
        for i, (fd, rel) in enumerate(act, 1):
            md.append("### %d. [%s] %s `%s`" % (i, Severity.LABEL_KO[fd.severity], T(fd.title), fd.id))
            md.append("")
            if fd.observed:
                md.append("- **관측**: %s" % _cell(masker, fd.observed))
            md.append("- **근거 구분**: %s" % (fd.basis or "-"))
            if fd.source:
                md.append("- **번들 내 근거 파일**: `%s`" % _cell(masker, fd.source))
            md.extend(_evidence(masker, fd.evidence))
            md.append("")

    ds = getattr(result, "diff_summary", None)
    if ds:
        md.append("## 이전 번들 대비 변화")
        md.append("")
        md.append("| " + " | ".join(_cell(masker, x) for x in ds["columns"]) + " |")
        md.append("| " + " | ".join("---" for _ in ds["columns"]) + " |")
        for r in ds["rows"][:MAX_EVIDENCE_ROWS + 5]:
            md.append("| " + " | ".join(_cell(masker, x) for x in r) + " |")
        md.append("")

    info = [fd for fd in result.by_severity() if fd.severity == Severity.INFO]
    if info:
        md.append("## 참고 판정")
        md.append("")
        md.append("| ID | 판정 | 관측 |")
        md.append("| --- | --- | --- |")
        for fd in info:
            md.append("| %s | %s | %s |" % (fd.id, _cell(masker, fd.title),
                                            _cell(masker, truncate(fd.observed, 120))))
        md.append("")

    sk = getattr(result.ctx, "skipped_rules", [])
    if sk or result.errors:
        md.append("## 확인하지 못한 항목")
        md.append("")
        md.append("문제 없음이 아니라 확인하지 못한 항목입니다.")
        md.append("")
        if sk:
            md.append("- 입력 미수집으로 판정하지 않은 룰 %d개: %s"
                      % (len(sk), ", ".join(x["rule"].split(".")[-1] for x in sk)))
        if result.errors:
            md.append("- 도구 오류로 판정하지 못한 룰 %d개: %s"
                      % (len(result.errors), ", ".join(x["rule"].split(".")[-1] for x in result.errors)))
        md.append("")

    md.append("## 노드 요약")
    md.append("")
    md.append("| 노드 | 역할 | 버전 | heap 사용률 | heap | RAM | CPU | 디스크 사용률 | 디스크 | zone |")
    md.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for n in f["nodes"]:
        md.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            _cell(masker, n["name"]), n["roles"], n["version"],
            ("%s%%" % n["heap_used_pct"]) if n["heap_used_pct"] is not None else "-",
            n["heap_max"], n["ram"], n["cpu"], n["disk_used_pct"], n["disk_total"], _cell(masker, n["zone"])))
    md.append("")

    out = "\n".join(md)
    leaks = masker.leaks(out)
    if leaks:
        raise MaskLeak(leaks)
    return out
