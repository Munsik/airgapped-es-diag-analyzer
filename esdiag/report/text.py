# -*- coding: utf-8 -*-
"""Console and Markdown output."""

from ..i18n import T
from ..model import Severity, category_label
from ..util import truncate


def _mark(severity):
    """Severity tag for the console, such as [Critical]."""
    return "[%s]" % Severity.label(severity)


def console(result, show_ok=True, width=100):
    f = result.facts()
    lines = []
    bar = "=" * width
    lines.append(bar)
    lines.append(T("report.text.console.01"))
    lines.append(bar)
    lines.append(T("report.text.console.02") % (f["cluster_name"], f["version"]))
    lines.append(T("report.text.console.03")
                 % (f.get("collected_display") or f["collected_at"], f["diag_type"], T("report.text.console.04") if f["has_logs"] else T("report.text.console.05")))
    lines.append(T("report.text.console.06")
                 % (f["nodes_total"], f["data_nodes"], f["master_nodes"],
                    f["indices"], f["shards"], f["store"]))
    lines.append(T("report.text.console.07") % f["status"])
    lines.append(T("report.text.console.08") % (f.get("tool_version"), f.get("baseline")))
    lines.append("")
    c = result.counts
    lines.append(T("report.text.console.09") % result.grade)
    lines.append(T("report.text.console.10")
                 % (c[Severity.CRITICAL], c[Severity.WARNING], c[Severity.INFO], c[Severity.OK]))
    lines.append(bar)
    lines.append("")

    lines.append(T("report.text.console.11"))
    areas = result.area_summary()
    aw = max([len(a["area"]) for a in areas] or [0])
    sw = max([len(a["status"]) for a in areas] or [0])
    for a in areas:
        # Pad here so the column fits the longest label in the current language.
        lines.append(T("report.text.console.12")
                     % (a["area"].ljust(aw), a["status"].ljust(sw), a["critical"], a["warning"], a["info"], a["ok"]))
    lines.append("")
    ds = getattr(result, "diff_summary", None)
    if ds:
        lines.append(T("report.text.console.13")
                     % ((T("report.text.console.14") % ds["hours"]) if ds.get("hours") else T("report.text.console.15")))
        lines.extend("  " + ln for ln in _ascii_table(
            {"columns": ds["columns"], "rows": ds["rows"]}, max_rows=20))
        lines.append("")

    act = result.priority()
    if act:
        lines.append(T("report.text.console.16"))
        for i, (fd, rel) in enumerate(act, 1):
            lines.append(T("report.text.console.prio") % (i, _mark(fd.severity), fd.title, truncate(fd.observed, 160)))
            if rel:
                lines.append(T("report.text.console.17") % ", ".join(T("report.text.console.rel") % (r.title, r.id) for r in rel))
        lines.append("")

    cur = None
    for fd in result.by_severity():
        if fd.severity == Severity.OK and not show_ok:
            continue
        if fd.category != cur:
            cur = fd.category
            name = category_label(cur)
            lines.append("")
            lines.append("── %s " % name + "─" * max(0, width - len(name) - 4))
        lines.append("")
        lines.append("%s %s  (%s · %s)" % (_mark(fd.severity), fd.title, fd.id, fd.basis or ""))
        if fd.observed:
            lines.append(T("report.text.console.18") % fd.observed)
        if fd.impact:
            lines.append(T("report.text.console.19") % fd.impact)
        if fd.recommend:
            lines.append(T("report.text.console.20") % fd.recommend)
        if fd.evidence and fd.evidence.get("rows"):
            lines.append(T("report.text.console.21"))
            lines.extend("      " + ln for ln in _ascii_table(fd.evidence))
        if fd.source:
            lines.append(T("report.text.console.22") % fd.source)
    lines.append("")
    sk = getattr(result.ctx, "skipped_rules", [])
    if sk:
        lines.append(T("report.text.console.23")
                     % (len(sk), ", ".join(x["rule"].split(".")[-1] for x in sk)))
    if result.errors:
        lines.append(T("report.text.console.24")
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
        out.append(T("report.text._ascii_table.01") % (len(ev["rows"]) - max_rows))
    return out


def markdown(result, show_ok=True):
    f = result.facts()
    c = result.counts
    md = []
    md.append(T("report.text.markdown.01"))
    md.append("")
    md.append(T("report.text.markdown.02"))
    md.append("| --- | --- |")
    md.append(T("report.text.markdown.03") % f["cluster_name"])
    md.append(T("report.text.markdown.04") % f["version"])
    md.append(T("report.text.markdown.05") % (f.get("collected_display") or f["collected_at"]))
    md.append(T("report.text.markdown.06") % (f["diag_type"],
                                              T("report.text.markdown.07") if f["has_logs"] else T("report.text.markdown.08")))
    md.append(T("report.text.markdown.09")
              % (f["nodes_total"], f["data_nodes"], f["master_nodes"]))
    md.append(T("report.text.markdown.10")
              % (f["indices"], f["shards"], f["docs"], f["store"]))
    md.append(T("report.text.markdown.11") % f["status"])
    md.append(T("report.text.markdown.12") % (f.get("tool_version"), f.get("baseline")))
    md.append(T("report.text.markdown.13") % result.grade)
    md.append(T("report.text.markdown.14")
              % (c[Severity.CRITICAL], c[Severity.WARNING], c[Severity.INFO], c[Severity.OK]))
    md.append("")
    md.append(T("report.text.markdown.15"))
    md.append("")
    md.append(T("report.text.markdown.16"))
    md.append("| --- | --- | --- | --- | --- | --- | --- |")
    for a in result.area_summary():
        md.append("| %s | %s | %d | %d | %d | %d | %s |" % (a["area"], a["status"], a["critical"], a["warning"],
                                                         a["info"], a["ok"], " · ".join(a["categories"])))
    md.append("")
    ds = getattr(result, "diff_summary", None)
    if ds:
        md.append(T("report.text.markdown.17"))
        md.append("")
        md.append("| " + " | ".join(ds["columns"]) + " |")
        md.append("| " + " | ".join("---" for _ in ds["columns"]) + " |")
        for r in ds["rows"]:
            md.append("| " + " | ".join(str(x) for x in r) + " |")
        md.append("")
    act = result.priority()
    if act:
        md.append(T("report.text.markdown.18"))
        md.append("")
        md.append(T("report.text.markdown.19"))
        md.append("| --- | --- | --- | --- | --- |")
        for i, (fd, rel) in enumerate(act, 1):
            md.append("| %d | %s | %s | %s | %s |" % (i, Severity.label(fd.severity), fd.title,
                                                      truncate(fd.observed, 200).replace("|", "/"),
                                                      ", ".join(r.id for r in rel) or "-"))
        md.append("")
    cur = None
    for fd in result.by_severity():
        if fd.severity == Severity.OK and not show_ok:
            continue
        if fd.category != cur:
            cur = fd.category
            md.append("")
            md.append("## %s" % category_label(cur))
        md.append("")
        md.append("### [%s] %s  `%s` · %s" % (Severity.label(fd.severity), fd.title, fd.id,
                                                fd.basis or ""))
        md.append("")
        if fd.observed:
            md.append(T("report.text.markdown.20") % fd.observed)
        if fd.impact:
            md.append(T("report.text.markdown.21") % fd.impact)
        if fd.recommend:
            md.append(T("report.text.markdown.22") % fd.recommend)
        if fd.source:
            md.append(T("report.text.markdown.23") % fd.source)
        if fd.refs:
            md.append(T("report.text.markdown.24") + ", ".join("[%s](%s)" % (t, u) for t, u in fd.refs))
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
        md.append(T("report.text.markdown.25"))
        md.append("")
        md.append(T("report.text.markdown.26"))
        md.append("| --- | --- |")
        for x in sk:
            md.append("| %s | %s |" % (x["rule"], " / ".join(x["missing"])))
        md.append("")
    if result.errors:
        md.append(T("report.text.markdown.27"))
        md.append("")
        md.append(T("report.text.markdown.28"))
        md.append("")
        md.append(T("report.text.markdown.29"))
        md.append("| --- | --- |")
        for x in result.errors:
            last = [ln for ln in x["error"].strip().splitlines() if ln.strip()][-1:] or [""]
            md.append("| %s | %s |" % (x["rule"], last[0].replace("|", "/")[:200]))
        md.append("")
    md.append(T("report.text.markdown.30"))
    md.append("")
    md.append(T("report.text.markdown.31"))
    md.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for n in f["nodes"]:
        md.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            n["name"], n["roles"], n["version"],
            ("%s%%" % n["heap_used_pct"]) if n["heap_used_pct"] is not None else "-",
            n["heap_max"], n["ram"], n["cpu"], n["load15"],
            n["disk_used_pct"], n["disk_total"], n["zone"]))
    md.append("")
    return "\n".join(md)
