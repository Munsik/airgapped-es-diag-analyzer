# -*- coding: utf-8 -*-
"""Rule execution engine and result aggregation."""

import collections
import traceback

from . import bottleneck as btl_mod
from . import diff as diff_mod
from . import ES_BASELINE, DOCS_CHECKED, SUPPORTED_MIN, __version__
from .basis import basis_of, label as basis_label
from .context import Context
from .i18n import T
from .loader import Bundle
from .model import Severity, category_label
from .rules import all_rules, missing_inputs
from .thresholds import merge
from .util import dig, fmt_bytes, num, items


class Result(object):
    def __init__(self, ctx, findings, errors, diff_summary=None, hidden_ok=None):
        self.ctx = ctx
        self.findings = findings
        # OK findings hidden by --no-ok. They are not shown but still count in the totals and area summary.
        self.hidden_ok = hidden_ok or []
        self.errors = errors
        self.diff_summary = diff_summary
        for f in self.findings:
            f.basis_id = basis_of(f.id)
            f.basis = basis_label(f.basis_id)
        self.counts = {s: 0 for s in (Severity.CRITICAL, Severity.WARNING,
                                      Severity.INFO, Severity.OK)}
        for f in list(findings) + self.hidden_ok:
            self.counts[f.severity] = self.counts.get(f.severity, 0) + 1
        self.grade_id = self._grade()
        self.grade = T("grade." + self.grade_id)

    def _grade(self):
        """Grade id, decided only by the number of critical and warning findings. No weighted score is used
        (such a formula would be arbitrary, with no official basis)."""
        if self.counts[Severity.CRITICAL] > 0:
            return "action"
        if self.counts[Severity.WARNING] >= 5:
            return "review"
        if self.counts[Severity.WARNING] > 0:
            return "fair"
        return "good"

    # Health check areas, in reading order of the report
    # (availability, capacity, data structure, performance, data protection, security, configuration).
    # Area and category ids are language-neutral; labels come from the catalog (area.<id>, cat.<id>).
    AREAS = [
        ("availability", ["cluster"]),
        ("capacity", ["node", "hotspot", "cost"]),
        ("structure", ["shard", "vector"]),
        ("performance", ["perf", "runtime"]),
        ("protection", ["ops"]),
        ("security", ["security"]),
        ("config", ["config", "settings", "os"]),
        ("trend", ["trend"]),
    ]
    CATEGORY_ORDER = [c for _a, cats in AREAS for c in cats]

    def by_severity(self):
        """Sort by category, then severity (the order of the report body)."""
        def key(f):
            try:
                c = self.CATEGORY_ORDER.index(f.category)
            except ValueError:
                c = len(self.CATEGORY_ORDER)
            return (c, Severity.ORDER.get(f.severity, 9), f.id)
        return sorted(self.findings, key=key)

    def area_summary(self):
        """Finding counts and status per health check area. An area with no findings shows status "none"."""
        rows = []
        for area, cats in self.AREAS:
            fs = [f for f in list(self.findings) + self.hidden_ok if f.category in cats]
            if area == "trend" and not fs:
                continue
            c = collections.Counter(f.severity for f in fs)
            if c[Severity.CRITICAL]:
                status = "action"
            elif c[Severity.WARNING]:
                status = "review"
            elif fs:
                status = "good"
            else:
                status = "none"
            rows.append({"area": T("area." + area), "area_id": area,
                         "categories": [category_label(x) for x in cats], "category_ids": cats,
                         "status": T("status." + status), "status_id": status,
                         "critical": c[Severity.CRITICAL], "warning": c[Severity.WARNING],
                         "info": c[Severity.INFO], "ok": c[Severity.OK]})
        return rows

    def actionable_sorted(self):
        return sorted([f for f in self.findings
                       if f.severity in (Severity.CRITICAL, Severity.WARNING)],
                      key=lambda f: (Severity.ORDER.get(f.severity, 9), self._cat_rank(f.category), f.id))

    def _cat_rank(self, cat):
        try:
            return self.CATEGORY_ORDER.index(cat)
        except ValueError:
            return len(self.CATEGORY_ORDER)

    def actionable(self):
        return self.actionable_sorted()

    def bottleneck(self):
        """Bottleneck summary rows (see bottleneck.py). OK findings hidden by --no-ok are included."""
        return btl_mod.summarize(self.ctx, list(self.findings) + self.hidden_ok)

    # Findings that share a root cause. The first one present in a group leads and the rest are attached
    # as related findings. The body keeps every finding; only the action priority list drops the duplicates.
    ROOT_GROUPS = [
        ["CLU-001", "CLU-002", "CLU-003", "CLU-004.shards_availability", "IDX-002"],   # unassigned shards
        ["DISK-001", "DISK-002", "DISK-003", "CLU-004.disk"],                          # disk watermarks
    ]

    def priority(self):
        """Action priority: [(leading finding, [related findings...]), ...]. A root-cause group becomes one entry."""
        act = self.actionable_sorted()
        by_id = dict((f.id, f) for f in act)
        absorbed, related = set(), {}
        for grp in self.ROOT_GROUPS:
            present = [i for i in grp if i in by_id]
            if len(present) < 2:
                continue
            # The most severe finding leads. On a tie, group order decides (symptom, then detailed cause).
            lead = min(present, key=lambda i: (Severity.ORDER.get(by_id[i].severity, 9), grp.index(i)))
            related[lead] = [by_id[i] for i in present if i != lead]
            absorbed.update(i for i in present if i != lead)
        return [(f, related.get(f.id, [])) for f in act if f.id not in absorbed]

    def facts(self):
        ctx = self.ctx
        cs = ctx.cluster_stats
        import collections as _c
        shard_count = _c.Counter()
        for sh in ctx.shards:
            if sh.get("node"):
                shard_count[sh["node"]] += 1
        top_indices = []
        for name, st in items(ctx.indices_stats):
            size = num(st, "total", "store", "size_in_bytes")
            qt = num(st, "total", "search", "query_total")
            qm = num(st, "total", "search", "query_time_in_millis")
            top_indices.append({
                "name": name, "size": size, "size_h": fmt_bytes(size),
                "docs": num(st, "primaries", "docs", "count"),
                "shards": ctx.shard_count(name),
                "latency": (qm / float(qt)) if qt else None})
        top_indices.sort(key=lambda x: -x["size"])
        top_indices = top_indices[:10]
        nodes_summary = []
        for n in ctx.nodes:
            nodes_summary.append({
                "name": n.name,
                "roles": ",".join(n.roles),
                "version": n.version,
                "heap_used_pct": n.heap_used_pct,
                "heap_max": fmt_bytes(n.heap_max),
                "ram": fmt_bytes(n.ram_total),
                "cpu": n.processors,
                "load15": n.load15,
                "disk_used_pct": ("%.1f%%" % n.disk_used_pct) if n.disk_used_pct is not None else "-",
                "disk_total": fmt_bytes(n.fs_total),
                "zone": n.attrs.get("availability_zone") or n.attrs.get("zone")
                        or n.attrs.get("logical_availability_zone") or "-",
                "heap_pct_num": n.heap_used_pct,
                "disk_pct_num": round(n.disk_used_pct, 1) if n.disk_used_pct is not None else None,
                "cpu_pct_num": n.cpu_pct,
                "load_per_cpu": round(n.load15 / n.processors, 2)
                                if (n.load15 and n.processors) else None,
                "shard_count": shard_count.get(n.name, 0),
                "is_data": n.is_data,
                "is_master": n.is_master_eligible,
            })
        return {
            "tool_version": __version__,
            "baseline": "Elasticsearch %d.%d (%s)" % (ES_BASELINE + (T("engine.docs_checked") % DOCS_CHECKED,)),
            "cluster_name": ctx.cluster_name,
            "cluster_uuid": ctx.version_doc.get("cluster_uuid"),
            "version": ctx.version,
            "collected_at": ctx.collection_time.isoformat() if ctx.collection_time else "-",
            "collected_display": _fmt_collected(ctx.collection_time),
            "diag_type": ctx.diag_type,
            "has_logs": ctx.has_logs,
            "status": ctx.health.get("status"),
            "nodes_total": len(ctx.nodes),
            "data_nodes": len(ctx.data_nodes),
            "master_nodes": len(ctx.master_nodes),
            "indices": dig(cs, "indices", "count") or len(ctx.indices_stats),
            "shards": dig(cs, "indices", "shards", "total") or ctx.health.get("active_shards"),
            "docs": dig(cs, "indices", "docs", "count"),
            "store": fmt_bytes(dig(cs, "indices", "store", "size_in_bytes")),
            "license": (ctx.license or {}).get("type"),
            "deployment": getattr(ctx, "deployment", "-"),
            "nodes": nodes_summary,
            "top_indices": top_indices,
        }

    def to_dict(self):
        return {
            "summary": {
                "grade": self.grade,
                "grade_id": self.grade_id,
                "counts": self.counts,
            },
            "facts": self.facts(),
            "areas": self.area_summary(),
            "bottleneck": [dict((k, r[k]) for k in ("id", "question", "state", "verdict_id", "verdict", "basis", "causes", "next"))
                           for r in self.bottleneck()],
            "priority": [{"id": f.id, "severity": f.severity, "title": f.title,
                          "related": [r.id for r in rel]} for f, rel in self.priority()],
            "diff": self.diff_summary,
            "findings": [f.to_dict() for f in self.by_severity()],
            "rule_errors": self.errors,
            "skipped_rules": getattr(self.ctx, "skipped_rules", []),
        }


def _fmt_collected(t):
    """Collection time for the report: UTC, plus Korea time (UTC+9, no daylight saving) in the Korean report."""
    if not t:
        return "-"
    try:
        import datetime as _dt
        if t.tzinfo is None:
            t = t.replace(tzinfo=_dt.timezone.utc)
        u = t.astimezone(_dt.timezone.utc)
        k = u + _dt.timedelta(hours=9)
        return T("engine._fmt_collected.01") % (u.strftime("%Y-%m-%d %H:%M:%S"), k.strftime("%Y-%m-%d %H:%M"))
    except Exception:
        return str(t)


CORE_FILES = ("cluster_health.json", "nodes_stats.json", "nodes.json")


def _run_rules(ctx, only=None, skip_ok=False):
    findings, errors, skipped = [], [], []
    for module_name, fn in all_rules():
        if only and module_name not in only:
            continue
        miss = missing_inputs(ctx.b, fn)
        if miss:
            skipped.append({"rule": "%s.%s" % (module_name, fn.__name__), "missing": miss})
            continue
        try:
            res = fn(ctx) or []
        except Exception:
            errors.append({"rule": "%s.%s" % (module_name, fn.__name__),
                           "error": traceback.format_exc(limit=3)})
            continue
        for f in res:
            if skip_ok and f.severity == Severity.OK:
                continue
            findings.append(f)
    ctx.skipped_rules = skipped
    findings.extend(_version_findings(ctx))
    return findings, errors


def _version_findings(ctx):
    """Warns when the analyzed version differs from the tool baseline."""
    from .model import Finding
    v = ctx.version_tuple
    if not v or v == (0, 0, 0):
        return [Finding("VER-001", "cluster", Severity.INFO, T("engine._version_findings.01"),
                        observed=T("engine._version_findings.02"),
                        impact=T("engine._version_findings.03"),
                        recommend=T("engine._version_findings.04"), source="version.json")]
    base = "%d.%d" % ES_BASELINE
    if v[:2] > ES_BASELINE:
        return [Finding("VER-001", "cluster", Severity.INFO,
                        T("engine._version_findings.05"),
                        observed=T("engine._version_findings.06") % (ctx.version, base, DOCS_CHECKED),
                        impact=T("engine._version_findings.07"),
                        recommend=T("engine._version_findings.08"), source="version.json")]
    if v[:2] < SUPPORTED_MIN:
        return [Finding("VER-001", "cluster", Severity.INFO,
                        T("engine._version_findings.09"),
                        observed=T("engine._version_findings.10") % ((ctx.version,) + SUPPORTED_MIN),
                        impact=T("engine._version_findings.11"),
                        recommend=T("engine._version_findings.12"), source="version.json")]
    return []


def _open_bundle(path, bundles):
    """Open a bundle, reusing one already opened by an earlier language pass."""
    if bundles is not None and path in bundles:
        return bundles[path]
    b = Bundle(path)
    if bundles is not None:
        bundles[path] = b
    return b


def analyze(path, thresholds=None, only=None, skip_ok=False, baseline=None, bundles=None):
    """Run every rule against a bundle.

    With baseline (one path or a list), the analyzed bundle is compared with the latest earlier one and trend findings are added.
    With two or more baselines, throughput per interval (peak and off-peak) is added as well.
    bundles is an optional dict that caches opened Bundle objects by path, so a second pass in
    another language does not parse the same files again.
    """
    t = merge(thresholds or {})
    bundle = _open_bundle(path, bundles)
    if not any(bundle.exists(f) for f in CORE_FILES):
        raise ValueError(T("engine.analyze.01")
                         % (", ".join(CORE_FILES), path))
    ctx = Context(bundle, t)
    ctx.only_modules = only
    findings, errors = _run_rules(ctx, only, False)

    diff_summary = None
    baselines = [baseline] if isinstance(baseline, str) else [b for b in (baseline or []) if b]
    if baselines:
        ctxs = []
        for path_b in baselines:
            bb = _open_bundle(path_b, bundles)
            if not any(bb.exists(f) for f in CORE_FILES):
                raise ValueError(T("engine.analyze.02") % path_b)
            ctxs.append(Context(bb, t))
        # Oldest first. The bundle right before the analyzed one is the comparison base; with two or more baselines
        # every interval also feeds the peak/off-peak throughput (DIF-014).
        ctxs.sort(key=lambda c: c.collection_time.timestamp() if c.collection_time else 0)
        base_ctx = ctxs[-1]
        base_findings, _ = _run_rules(base_ctx, only, True)
        try:
            diff_summary, diff_findings = diff_mod.compare(
                base_ctx, ctx, t, base_findings, findings)
        except Exception:
            errors.append({"rule": "diff.compare",
                           "error": traceback.format_exc(limit=3)})
            diff_findings = []
        if len(ctxs) >= 2:
            try:
                diff_findings.extend(diff_mod.r_interval_rates(ctxs + [ctx], t))
            except Exception:
                errors.append({"rule": "diff.r_interval_rates",
                               "error": traceback.format_exc(limit=3)})
        findings.extend(diff_findings)
    hidden = []
    if skip_ok:
        hidden = [f for f in findings if f.severity == Severity.OK]
        findings = [f for f in findings if f.severity != Severity.OK]
    return Result(ctx, findings, errors, diff_summary, hidden_ok=hidden)
