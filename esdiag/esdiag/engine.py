# -*- coding: utf-8 -*-
"""룰 실행 엔진과 결과 집계."""

import collections
import traceback

from . import diff as diff_mod
from . import ES_BASELINE, DOCS_CHECKED, SUPPORTED_MIN, __version__
from .basis import basis_of
from .context import Context
from .loader import Bundle
from .model import Severity
from .rules import all_rules, missing_inputs
from .thresholds import merge
from .util import dig, fmt_bytes, num, items


class Result(object):
    def __init__(self, ctx, findings, errors, diff_summary=None):
        self.ctx = ctx
        self.findings = findings
        self.errors = errors
        self.diff_summary = diff_summary
        for f in self.findings:
            f.basis = basis_of(f.id)
        self.counts = {s: 0 for s in (Severity.CRITICAL, Severity.WARNING,
                                      Severity.INFO, Severity.OK)}
        for f in findings:
            self.counts[f.severity] = self.counts.get(f.severity, 0) + 1
        self.grade = self._grade()

    def _grade(self):
        """치명·주의 건수로만 정하는 단계. 가중치 점수는 쓰지 않는다(공식 기준이 없는 임의 산식이므로)."""
        if self.counts[Severity.CRITICAL] > 0:
            return "조치 필요"
        if self.counts[Severity.WARNING] >= 5:
            return "점검 권고"
        if self.counts[Severity.WARNING] > 0:
            return "양호(개선 여지)"
        return "양호"

    # 헬스 체크 영역: 보고서를 읽는 순서(가용성 → 자원 → 데이터 구조 → 성능 → 데이터 보호 → 보안 → 구성)
    AREAS = [
        ("가용성", ["클러스터"]),
        ("자원·용량", ["노드", "핫스팟·밸런싱"]),
        ("데이터 구조", ["샤드·인덱스", "벡터 검색"]),
        ("성능", ["성능 기준", "런타임"]),
        ("데이터 보호·운영", ["운영"]),
        ("보안", ["보안·인증"]),
        ("구성", ["설정 기준", "설정 변경"]),
        ("변화 추세", ["변화 추세"]),
    ]
    CATEGORY_ORDER = [c for _a, cats in AREAS for c in cats]

    def by_severity(self):
        """카테고리 순 -> 심각도 순으로 정렬(리포트 본문 순서)."""
        def key(f):
            try:
                c = self.CATEGORY_ORDER.index(f.category)
            except ValueError:
                c = len(self.CATEGORY_ORDER)
            return (c, Severity.ORDER.get(f.severity, 9), f.id)
        return sorted(self.findings, key=key)

    def area_summary(self):
        """헬스 체크 영역별 판정 건수와 상태. 판정이 하나도 없는 영역은 '판정 없음' 으로 표시한다."""
        rows = []
        for area, cats in self.AREAS:
            fs = [f for f in self.findings if f.category in cats]
            if area == "변화 추세" and not fs:
                continue
            c = collections.Counter(f.severity for f in fs)
            if c[Severity.CRITICAL]:
                status = "조치 필요"
            elif c[Severity.WARNING]:
                status = "점검 권고"
            elif fs:
                status = "양호"
            else:
                status = "판정 없음"
            rows.append({"area": area, "categories": cats, "status": status,
                         "critical": c[Severity.CRITICAL], "warning": c[Severity.WARNING],
                         "info": c[Severity.INFO], "ok": c[Severity.OK]})
        return rows

    def actionable_sorted(self):
        return sorted([f for f in self.findings
                       if f.severity in (Severity.CRITICAL, Severity.WARNING)],
                      key=lambda f: (Severity.ORDER.get(f.severity, 9), f.category, f.id))

    def actionable(self):
        return self.actionable_sorted()

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
            "baseline": "Elasticsearch %d.%d (공식 문서 %s 대조)" % (ES_BASELINE + (DOCS_CHECKED,)),
            "cluster_name": ctx.cluster_name,
            "cluster_uuid": ctx.version_doc.get("cluster_uuid"),
            "version": ctx.version,
            "collected_at": ctx.collection_time.isoformat() if ctx.collection_time else "-",
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
                "counts": self.counts,
            },
            "facts": self.facts(),
            "areas": self.area_summary(),
            "diff": self.diff_summary,
            "findings": [f.to_dict() for f in self.by_severity()],
            "rule_errors": self.errors,
            "skipped_rules": getattr(self.ctx, "skipped_rules", []),
        }


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
    """분석 대상 버전이 도구의 기준점과 다르면 알린다."""
    from .model import Finding
    v = ctx.version_tuple
    if not v or v == (0, 0, 0):
        return [Finding("VER-001", "클러스터", Severity.INFO, "클러스터 버전 확인 불가",
                        observed="version.json 에서 버전을 읽지 못했습니다.",
                        impact="버전에 따라 갈리는 판정(8.3 / 8.5 / 8.14 / 9.2 기준)이 최신 버전 기준으로 동작합니다.",
                        recommend="번들에 version.json 이 포함되었는지 확인합니다.", source="version.json")]
    base = "%d.%d" % ES_BASELINE
    if v[:2] > ES_BASELINE:
        return [Finding("VER-001", "클러스터", Severity.INFO,
                        "도구 기준 버전보다 새로운 클러스터",
                        observed="클러스터 %s / 도구 기준 %s (공식 문서 %s 대조)." % (ctx.version, base, DOCS_CHECKED),
                        impact="기준 이후 버전에서 기본값이나 동작이 바뀐 항목은 판정이 맞지 않을 수 있습니다.",
                        recommend="해당 버전의 릴리스 노트에서 기본값 변경(워터마크, 벡터, 샤드 한도 등)을 확인하고, "
                                  "필요하면 도구의 기준 버전을 갱신합니다.", source="version.json")]
    if v[:2] < SUPPORTED_MIN:
        return [Finding("VER-001", "클러스터", Severity.INFO,
                        "도구 지원 최소 버전보다 오래된 클러스터",
                        observed="클러스터 %s / 지원 최소 %d.%d." % ((ctx.version,) + SUPPORTED_MIN),
                        impact="Health API·desired balance·벡터 통계 등 해당 버전에 없는 API 기반 룰은 "
                               "입력 미수집으로 건너뜁니다. 버전별 기준(예: heap 1GB당 샤드 20개)은 해당 버전 값으로 적용됩니다.",
                        recommend="건너뛴 룰 목록을 확인하고, 필요한 항목은 수동으로 점검합니다.", source="version.json")]
    return []


def analyze(path, thresholds=None, only=None, skip_ok=False, baseline=None):
    """baseline 을 주면 두 번들을 비교해 '변화 추세' 판정을 추가한다."""
    t = merge(thresholds or {})
    bundle = Bundle(path)
    if not any(bundle.exists(f) for f in CORE_FILES):
        raise ValueError("support-diagnostics 번들로 인식할 수 없습니다. 핵심 파일(%s)이 없습니다: %s"
                         % (", ".join(CORE_FILES), path))
    ctx = Context(bundle, t)
    findings, errors = _run_rules(ctx, only, skip_ok)

    diff_summary = None
    if baseline:
        bb = Bundle(baseline)
        if not any(bb.exists(f) for f in CORE_FILES):
            raise ValueError("baseline 을 진단 번들로 인식할 수 없습니다: %s" % baseline)
        base_ctx = Context(bb, t)
        base_findings, _ = _run_rules(base_ctx, only, True)
        try:
            diff_summary, diff_findings = diff_mod.compare(
                base_ctx, ctx, t, base_findings, findings)
        except Exception:
            errors.append({"rule": "diff.compare",
                           "error": traceback.format_exc(limit=3)})
            diff_findings = []
        for f in diff_findings:
            if skip_ok and f.severity == Severity.OK:
                continue
            findings.append(f)
    return Result(ctx, findings, errors, diff_summary)
