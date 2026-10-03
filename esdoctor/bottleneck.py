# -*- coding: utf-8 -*-
"""Bottleneck summary: answers five questions from the findings and a few raw counters.

1. Is ingest keeping up?   2. Is search slow?   3. Is storage limiting?   4. Is a restart or recovery skewing the numbers?
5. Is it capacity or concentration?

Each question looks for symptoms first (rejections, queues, throttling, high latency). Only when a symptom exists does it walk the
cause groups in a fixed order and name the first group that has a finding; the other groups with findings are listed as well.
For search, a busy search pool with low CPU (PERF-013) moves storage to the front, because it shows threads waiting.
When the symptom is tied to nodes (a queue or rejections on some nodes, PERF-013 nodes), the scope is those nodes plus the other
nodes of their data tiers (a bulk write waits for the replicas on the other nodes of the tier, a search waits for every shard copy it
hits). A cause finding that names nodes counts only if it names one in scope: high heap on a frozen node does not explain a write
queue on a hot node. Findings that name no node (cluster wide, or indices) always count.
The groups reuse the findings in the report, so the summary never contradicts the body. It is a reading aid: the order is the
tool's judgment of where to look first, not an official decision tree.
"""

from .i18n import T
from .model import Severity
from .util import dig, fmt_num, items, num

ACTIVE = (Severity.CRITICAL, Severity.WARNING)
# Findings that count as a cause even at Info: they only fire on a pattern, never as a plain report.
INFO_CAUSES = ("PERF-013",)

INGEST_CAUSES = [
    ("storage", ("IDX-005", "PERF-012", "IDX-014", "DISK-008", "IDX-015", "PERF-009")),
    ("memory", ("JVM-001", "JVM-005", "BRK-001", "BRK-002", "IP-001")),
    ("cpu", ("HOT-005", "OS-001", "OS-003")),
    ("distribution", ("SHD-016", "HOT-002.index_total", "HOT-001", "SHD-006", "SHD-012")),
    ("pipeline", ("ING-002", "ING-001")),
    ("settings", ("IDX-007", "PERF-004")),
]
SEARCH_CAUSES = [
    ("memory", ("JVM-001", "JVM-005", "FD-001", "BRK-001", "BRK-002")),
    ("cpu", ("HOT-005", "OS-001", "OS-003")),
    ("storage", ("PERF-013", "FRZ-002", "FRZ-001", "DISK-008", "PERF-009", "PERF-003")),
    ("query", ("PERF-011", "PERF-010", "PERF-005", "GEN-001")),
    ("shards", ("SHD-001", "OVS-001", "OVS-003", "SHD-004", "SHD-009")),
    ("distribution", ("HOT-002.query_total", "HOT-001", "PERF-007", "SHD-006")),
]
STORAGE = ("IDX-005", "PERF-012", "IDX-014", "DISK-008", "PERF-013", "FRZ-002", "FRZ-001", "PERF-009", "IDX-015")
RESTART = [
    ("mass", ("OS-007",)),
    ("interval", ("DIF-002",)),
    ("recent", ("OS-006",)),
    ("recovery", ("CLU-020", "REC-001", "HOT-003")),
]
CAPACITY = [
    ("cpu", ("HOT-005",)),
    ("disk", ("DISK-001", "DISK-002", "DISK-003", "DIF-008", "COST-004")),
    ("concentration", ("HOT-001", "HOT-002", "SHD-006", "SHD-016", "NODE-001")),
]


def _match(fid, pattern):
    return fid == pattern or fid.startswith(pattern + ".")


def _scoped(f, scope, known):
    """False when the finding names nodes and none of them is in scope. scope None means no node scoping."""
    if not scope:
        return True
    nodes = set(a for a in (f.affected or []) if a in known)
    return not nodes or bool(nodes & scope)


def _hits(findings, patterns, scope=None, known=()):
    """Finding ids among patterns that are Critical/Warning (or an Info cause), in pattern order, without duplicates.
    With a node scope, findings that name only other nodes are skipped."""
    out = []
    for p in patterns:
        for f in findings:
            if f.id in out or not _match(f.id, p) or not _scoped(f, scope, known):
                continue
            if f.severity in ACTIVE or (f.severity == Severity.INFO and any(_match(f.id, x) for x in INFO_CAUSES)):
                out.append(f.id)
    return out


def _walk(findings, groups, scope=None, known=()):
    """[(group, [ids])] for every group with a hit, in group order."""
    out = []
    for name, patterns in groups:
        ids = _hits(findings, patterns, scope, known)
        if ids:
            out.append((name, ids))
    return out


def _pool_sums(ctx, pools):
    """(rejected, queued, names of nodes with either)."""
    rej = queue = 0
    where = set()
    for n in ctx.nodes:
        for pool, st in items(dig(n.stats, "thread_pool")):
            if pool in pools:
                r, q = num(st, "rejected"), num(st, "queue")
                rej += r
                queue += q
                if r or q:
                    where.add(n.name)
    return rej, queue, where


def _row(qid, state, verdict, basis, causes, nxt, worst=None):
    return {"id": qid, "question": T("btl.q." + qid), "state": state, "verdict_id": verdict,
            "verdict": T("btl.v.%s.%s" % (qid, verdict)), "basis": basis, "causes": causes,
            "next": T("btl.n.%s.%s" % (qid, verdict)) if nxt else "", "worst": worst}


def _worst(findings, ids):
    sev = [f.severity for f in findings if f.id in ids]
    return min(sev, key=lambda s: Severity.ORDER.get(s, 9)) if sev else None


def _tier_scope(ctx, scope):
    """The symptom nodes plus every node of their data tiers. A symptom node that holds no data (coordinating-only, ingest)
    passes its work on to the data nodes of every tier, so then the scope is every data node."""
    if not scope:
        return scope
    if any(not n.is_data for n in ctx.nodes if n.name in scope):
        return set(scope) | set(n.name for n in ctx.data_nodes)
    tiers = set(ctx.tier_of(n) for n in ctx.nodes if n.name in scope) - set([None])
    return set(scope) | set(n.name for n in ctx.nodes if tiers and ctx.tier_of(n) in tiers)


def _causal(qid, findings, groups, symptoms, scope=None, known=()):
    """Walk the cause groups once a symptom exists, limited to the symptom scope when one is given."""
    found = _walk(findings, groups, scope, known)
    ids = [i for _g, xs in found for i in xs]
    if not found:
        return _row(qid, "symptom", "unknown", symptoms, [], True)
    lead = found[0][0]
    also = [g for g, _x in found[1:]]
    r = _row(qid, "issue", lead, symptoms, ids, True, _worst(findings, ids))
    if also:
        r["verdict"] += T("btl.also") % ", ".join(T("btl.g." + g) for g in also)
    return r


def _ingest(ctx, findings):
    if not sum(num(n.stats, "indices", "indexing", "index_total") for n in ctx.data_nodes):
        return _row("ingest", "idle", "idle", [], [], False)
    sym, wide = [], False
    rej, queue, scope = _pool_sums(ctx, ("write", "write_coordination"))
    if rej:
        sym.append(T("btl.s.write_rejected") % fmt_num(rej))
    if queue:
        sym.append(T("btl.s.write_queue") % fmt_num(queue))
    ip = 0
    for n in ctx.nodes:
        v = sum(num(x) for k, x in items(dig(n.stats, "indexing_pressure", "memory", "total")) if k.endswith("rejections"))
        if v:
            ip += v
            scope.add(n.name)
    if ip:
        sym.append(T("btl.s.pressure") % fmt_num(ip))
    thr = [f for f in findings if f.id == "IDX-014" and f.severity in ACTIVE]
    if thr:
        sym.append(T("btl.s.throttled"))
        wide = True             # throttling is reported per index, so it does not point at nodes
    if not sym:
        return _row("ingest", "clear", "clear", [], [], True)
    known = set(n.name for n in ctx.nodes)
    return _causal("ingest", findings, INGEST_CAUSES, sym, None if wide else _tier_scope(ctx, scope), known)


def _search(ctx, findings):
    if not sum(num(n.stats, "indices", "search", "query_total") for n in ctx.data_nodes):
        return _row("search", "idle", "idle", [], [], False)
    sym, wide = [], False
    rej, queue, scope = _pool_sums(ctx, ("search",))
    if rej:
        sym.append(T("btl.s.search_rejected") % fmt_num(rej))
    if queue:
        sym.append(T("btl.s.search_queue") % fmt_num(queue))
    slow = _hits(findings, ("PERF-001", "PERF-002"))
    known = set(n.name for n in ctx.nodes)
    if slow:
        sym.append(T("btl.s.search_slow") % ", ".join(slow))
        named = set(a for f in findings if f.id in slow for a in (f.affected or []) if a in known)
        if named:
            scope |= named
        else:
            wide = True
    busy = _hits(findings, ("PERF-013",))
    if busy:
        sym.append(T("btl.s.search_busy"))
        scope |= set(a for f in findings if f.id in busy for a in (f.affected or []) if a in known)
    if not sym:
        return _row("search", "clear", "clear", [], [], True)
    groups = SEARCH_CAUSES
    if busy:
        # Threads that are busy without CPU are a direct observation of waiting, so storage is checked first.
        groups = [g for g in SEARCH_CAUSES if g[0] == "storage"] + [g for g in SEARCH_CAUSES if g[0] != "storage"]
    return _causal("search", findings, groups, sym, None if wide else _tier_scope(ctx, scope), known)


def _storage(findings):
    ids = _hits(findings, STORAGE)
    if not ids:
        return _row("storage", "clear", "clear", [], [], True)
    return _row("storage", "issue", "signals", [], ids, True, _worst(findings, ids))


def _restart(findings):
    found = _walk(findings, RESTART)
    if not found:
        return _row("restart", "clear", "clear", [], [], True)
    ids = [i for _g, xs in found for i in xs]
    return _row("restart", "issue", found[0][0], [], ids, True, _worst(findings, ids))


def _capacity(findings):
    found = _walk(findings, CAPACITY)
    if not found:
        return _row("capacity", "clear", "clear", [], [], True)
    ids = [i for _g, xs in found for i in xs]
    lead = found[0][0]
    r = _row("capacity", "issue", lead, [], ids, True, _worst(findings, ids))
    also = [g for g, _x in found[1:]]
    if also:
        r["verdict"] += T("btl.also") % ", ".join(T("btl.c." + g) for g in also)
    return r


def summarize(ctx, findings):
    """List of row dicts, one per question. Empty when only some rule modules ran (the summary would be partial)."""
    if getattr(ctx, "only_modules", None):
        return []
    fs = list(findings)
    return [_ingest(ctx, fs), _search(ctx, fs), _storage(fs), _restart(fs), _capacity(fs)]


def cells(row):
    """(question, verdict, basis text, next step) as display strings."""
    basis = list(row["basis"])
    if row["causes"]:
        basis.append(T("btl.findings") % ", ".join(row["causes"]))
    return row["question"], row["verdict"], " / ".join(basis) or "-", row["next"] or "-"


def css(row):
    """Severity-like class for the verdict tag: c, w, i or o."""
    if row["state"] == "issue":
        return "c" if row.get("worst") == Severity.CRITICAL else "w"
    if row["state"] == "symptom":
        return "w"
    if row["state"] == "idle":
        return "i"
    return "o"
