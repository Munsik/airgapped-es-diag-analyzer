# -*- coding: utf-8 -*-
"""Summary (Markdown) of what to put in the case when contacting Elastic Support.

Unlike the analysis report, it follows these rules:
  - Critical and Warning findings are listed as observed facts and evidence files. The tool's recommendation text is left out.
  - Server log excerpts and hot threads stacks carry raw text, so those columns are dropped from the tables.
  - Masking is applied to every string, and no summary is produced if an identifier survives (mask.Masker.leaks).
"""

from .. import bottleneck as btl
from ..i18n import T, N_, all_T
from ..model import Severity
from ..util import truncate

# Evidence columns that carry raw text (log lines, thread names, stacks). They are dropped from the summary.
# Column titles are matched in every language, whichever one the report is rendered in.
_DROP_KEYS = ("report.handoff._.01", "report.handoff._.02")
MAX_EVIDENCE_ROWS = 10


class MaskLeak(Exception):
    """An identifier survived masking, so no summary was produced."""

    def __init__(self, leaks):
        Exception.__init__(self, T("report.handoff.MaskLeak.__init__.01") % len(leaks))
        self.leaks = leaks


def _cell(masker, v):
    s = "" if v is None else str(v)
    return masker.text(s).replace("|", "/").replace("\n", " ")


def _drop_columns():
    drop = set(["thread"])
    for k in _DROP_KEYS:
        drop |= all_T(k)
    return drop


def _evidence(masker, ev):
    """Evidence table as a list of Markdown lines. Raw text columns are dropped."""
    if not ev or not ev.get("rows"):
        return []
    cols = list(ev["columns"])
    keep = [i for i, c in enumerate(cols) if str(c) not in _drop_columns()]
    if not keep:
        return []
    rows = ev["rows"][:MAX_EVIDENCE_ROWS]
    out = ["", "| " + " | ".join(_cell(masker, cols[i]) for i in keep) + " |",
           "| " + " | ".join("---" for _ in keep) + " |"]
    for r in rows:
        out.append("| " + " | ".join(_cell(masker, r[i] if i < len(r) else "") for i in keep) + " |")
    if len(ev["rows"]) > MAX_EVIDENCE_ROWS:
        out.append("")
        out.append(T("report.handoff._evidence.01") % (len(ev["rows"]) - MAX_EVIDENCE_ROWS))
    return out


def render(result, masker, level, tool_version):
    """Summary as a Markdown string. Raises MaskLeak if an identifier survives masking."""
    f = result.facts()
    c = result.counts
    mtext = masker.text
    md = []
    md.append(T("report.handoff.render.01"))
    md.append("")
    md.append(T("report.handoff.render.02"))
    md.append("| --- | --- |")
    md.append(T("report.handoff.render.03")
              % tool_version)
    md.append(T("report.handoff.render.04") % _cell(masker, f["cluster_name"]))
    md.append(T("report.handoff.render.05") % (f["version"], f.get("deployment") or "-"))
    md.append(T("report.handoff.render.06")
              % (f.get("collected_display") or f["collected_at"], f["diag_type"],
                 T("report.handoff.render.07") if f["has_logs"] else T("report.handoff.render.08")))
    md.append(T("report.handoff.render.09")
              % (f["nodes_total"], f["data_nodes"], f["master_nodes"], f["indices"], f["shards"], f["store"]))
    md.append(T("report.handoff.render.10") % f["status"])
    md.append(T("report.handoff.render.11")
              % (result.grade, c[Severity.CRITICAL], c[Severity.WARNING], c[Severity.INFO], c[Severity.OK]))
    if level == "none":
        md.append(T("report.handoff.render.12"))
    else:
        md.append(T("report.handoff.render.13")
                  % level)
    md.append("")

    md.append(T("report.handoff.render.14"))
    md.append("")
    md.append(T("report.handoff.render.15"))
    md.append("| --- | --- | --- | --- | --- | --- |")
    for a in result.area_summary():
        md.append("| %s | %s | %d | %d | %d | %d |"
                  % (a["area"], a["status"], a["critical"], a["warning"], a["info"], a["ok"]))
    md.append("")

    rows = result.bottleneck()
    if rows:
        md.append("## " + T("btl.title"))
        md.append("")
        md.append("| %s | %s | %s |" % (T("btl.col.q"), T("btl.col.v"), T("btl.col.b")))
        md.append("| --- | --- | --- |")
        for r in rows:
            q, v, b, _nx = btl.cells(r)
            md.append("| %s | %s | %s |" % (_cell(masker, q), _cell(masker, v), _cell(masker, b)))
        md.append("")

    act = result.priority()
    md.append(T("report.handoff.render.16"))
    md.append("")
    if not act:
        md.append(T("report.handoff.render.17"))
        md.append("")
    else:
        md.append(T("report.handoff.render.18"))
        md.append("| --- | --- | --- | --- | --- | --- | --- |")
        for i, (fd, rel) in enumerate(act, 1):
            md.append("| %d | %s | %s | %s | %s | %s | %s |"
                      % (i, fd.id, Severity.label(fd.severity), _cell(masker, fd.title), fd.basis or "-",
                         _cell(masker, fd.source) or "-", ", ".join(r.id for r in rel) or "-"))
        md.append("")
        for i, (fd, rel) in enumerate(act, 1):
            md.append("### %d. [%s] %s `%s`" % (i, Severity.label(fd.severity), mtext(fd.title), fd.id))
            md.append("")
            if fd.observed:
                md.append(T("report.handoff.render.19") % _cell(masker, fd.observed))
            md.append(T("report.handoff.render.20") % (fd.basis or "-"))
            if fd.source:
                md.append(T("report.handoff.render.21") % _cell(masker, fd.source))
            md.extend(_evidence(masker, fd.evidence))
            md.append("")

    ds = getattr(result, "diff_summary", None)
    if ds:
        md.append(T("report.handoff.render.22"))
        md.append("")
        md.append("| " + " | ".join(_cell(masker, x) for x in ds["columns"]) + " |")
        md.append("| " + " | ".join("---" for _ in ds["columns"]) + " |")
        for r in ds["rows"][:MAX_EVIDENCE_ROWS + 5]:
            md.append("| " + " | ".join(_cell(masker, x) for x in r) + " |")
        md.append("")

    info = [fd for fd in result.by_severity() if fd.severity == Severity.INFO]
    if info:
        md.append(T("report.handoff.render.23"))
        md.append("")
        md.append(T("report.handoff.render.24"))
        md.append("| --- | --- | --- |")
        for fd in info:
            md.append("| %s | %s | %s |" % (fd.id, _cell(masker, fd.title),
                                            _cell(masker, truncate(fd.observed, 120))))
        md.append("")

    sk = getattr(result.ctx, "skipped_rules", [])
    if sk or result.errors:
        md.append(T("report.handoff.render.25"))
        md.append("")
        md.append(T("report.handoff.render.26"))
        md.append("")
        if sk:
            md.append(T("report.handoff.render.27")
                      % (len(sk), ", ".join(x["rule"].split(".")[-1] for x in sk)))
        if result.errors:
            md.append(T("report.handoff.render.28")
                      % (len(result.errors), ", ".join(x["rule"].split(".")[-1] for x in result.errors)))
        md.append("")

    md.append(T("report.handoff.render.29"))
    md.append("")
    md.append(T("report.handoff.render.30"))
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
