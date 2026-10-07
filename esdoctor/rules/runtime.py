# -*- coding: utf-8 -*-
"""Runtime evidence analysis: hot threads and server logs (local/remote mode)."""

import collections
import re

from ..i18n import T, N_, tr
from ..model import Finding, Severity, table
from ..util import fmt_num, truncate

CAT = "runtime"

_NODE_RE = re.compile(r"^:::\s*\{([^}]*)\}")
_THREAD_RE = re.compile(
    r"^\s*([\d.]+)%\s*(?:\[([^\]]*)\]\s*)?\(([^)]*)\)\s*cpu usage by thread\s*'([^']+)'")

# Stack frame -> cause classification
# Context signatures: calls that decide the kind of work wherever they appear in the stack
# (searched first, over the whole stack).
# Example: even if the top frame is a JSON copy, a caller that stores ignored source makes the work 'document parsing'.
_CONTEXT = [
    ("OneMergeProgress.pauseNanos", N_("rules.runtime._.01"), N_("rules.runtime._.02")),
    ("org.elasticsearch.grok", N_("rules.runtime._.03"), N_("rules.runtime._.04")),
    ("org.elasticsearch.dissect", N_("rules.runtime._.05"), N_("rules.runtime._.06")),
    ("org.elasticsearch.painless", N_("rules.runtime._.07"), N_("rules.runtime._.08")),
    ("addIgnoredFieldFromContext", N_("rules.runtime._.09"),
     N_("rules.runtime._.10")),
    ("GlobalOrdinalsBuilder", N_("rules.runtime._.11"), N_("rules.runtime._.12")),
    ("OrdinalMap.build", N_("rules.runtime._.11"), N_("rules.runtime._.12")),
    ("RegExp", N_("rules.runtime._.13"), N_("rules.runtime._.14")),
    # ingest processors (json, set, rename, ...): the JSON parsing frames above them are the processor's work, not request I/O
    ("org.elasticsearch.ingest.common.", "ingest pipeline", N_("rules.runtime._.15")),
]

# General signatures: used when no context signature matches; compared starting from the top (running) frames.
_SIGNATURES = [
    ("org.elasticsearch.ingest", "ingest pipeline", N_("rules.runtime._.15")),
    ("org.elasticsearch.search.aggregations", N_("rules.runtime._.16"), N_("rules.runtime._.17")),
    ("org.apache.lucene.search", N_("rules.runtime._.18"), N_("rules.runtime._.19")),
    ("Lucene Merge Thread", N_("rules.runtime._.20"), N_("rules.runtime._.21")),
    ("org.apache.lucene.index", N_("rules.runtime._.22"), N_("rules.runtime._.23")),
    ("org.elasticsearch.index.mapper", N_("rules.runtime._.24"), N_("rules.runtime._.25")),
    ("org.elasticsearch.index.engine", N_("rules.runtime._.26"), N_("rules.runtime._.27")),
    ("org.elasticsearch.xpack.ml", N_("rules.runtime._.28"), N_("rules.runtime._.29")),
    ("java.util.zip", N_("rules.runtime._.30"), N_("rules.runtime._.31")),
    ("xcontent", N_("rules.runtime._.32"), N_("rules.runtime._.33")),
    ("org.elasticsearch.transport", N_("rules.runtime._.34"), N_("rules.runtime._.35")),
]


def _classify(stack, tname):
    """1) Look for a context signature anywhere in the stack (this decides the kind of work), 2) if none, match the general signatures starting from the top frames, 3) if still none, match the signatures against the thread name."""
    for sig, label, hint in _CONTEXT:
        if any(sig in frame for frame in stack):
            return tr(label), tr(hint)
    search_thread = any(p in tname for p in ("[search]", "[search_worker]", "[search_throttled]"))
    for i, frame in enumerate(stack):
        if "java.util.zip" in frame and any("org.apache.lucene.codecs" in f for f in stack[i + 1:]):
            return tr(N_("rules.runtime._.67")), tr(N_("rules.runtime._.68"))    # best_compression stored fields (Deflate)
        for sig, label, hint in _SIGNATURES:
            if search_thread and sig == "org.apache.lucene.index":
                continue            # index readers (TermsEnum, doc values) on a search thread are search work, not indexing
            if sig in frame:
                return tr(label), tr(hint)
    for sig, label, hint in _CONTEXT + _SIGNATURES:
        if sig in tname:
            return tr(label), tr(hint)
    return None, None


_CPU_RE = re.compile(r"cpu=([\d.]+)%")


def parse_hot_threads(text):
    """Returns a list of (node, pct, thread_name, cpu_desc, stack), where stack holds up to 40 stack lines."""
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
                pct = float(cm.group(1))      # Drop the 'other' (waiting) time and use only the actual CPU share
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
    """Picks one representative stack frame line, preferring org.elasticsearch and org.apache.lucene frames (skips the snapshot notice text)."""
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
    """Parses nodes_hot_threads.txt and extracts the actual CPU usage per thread (cpu=, or the overall percentage if missing).

    Max thread CPU >= hot_thread_pct_warn → Warning, otherwise Info. This is a single 500ms snapshot at collection time, so it is never rated Critical on its own.
    The cause is classified by matching signatures against each thread's stack: context signatures (grok, painless, regexp, global ordinals, etc.) are searched over the whole stack first, then general signatures (ingest, aggregation, search, merge, etc.) starting from the top (running) frames; the first match wins.
    Threads below 0.5% CPU are ignored for cause counting when any busier thread exists.
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
    cause_txt = ", ".join("%s(%d)" % kv for kv in causes.most_common(5)) or T("rules.runtime.r_hot_threads.01")
    rec = " ".join(hints[k] for k, _ in causes.most_common(3)) or \
        T("rules.runtime.r_hot_threads.02")
    return [Finding(
        "RT-001", CAT, sev, T("rules.runtime.r_hot_threads.03"),
        observed=T("rules.runtime.r_hot_threads.04") % (hottest, cause_txt),
        impact=T("rules.runtime.r_hot_threads.05"),
        recommend=rec,
        evidence=table(["node", "cpu%", "thread", T("rules.runtime.r_hot_threads.06"), T("rules.runtime.r_hot_threads.07")], rows),
        source="nodes_hot_threads.txt")]


_LOG_PATTERNS = [
    (r"OutOfMemoryError: unable to create (?:new )?native thread", Severity.CRITICAL, "OutOfMemoryError (native thread)",
     N_("rules.runtime._.62")),
    (r"^(?!.*unable to create (?:new )?native thread).*OutOfMemoryError", Severity.CRITICAL, "OutOfMemoryError",
     N_("rules.runtime._.36")),
    (r"failed to obtain node lock", Severity.CRITICAL, N_("rules.runtime._.37"),
     N_("rules.runtime._.38")),
    (r"master not discovered|no known master node|master_not_discovered",
     Severity.WARNING, N_("rules.runtime._.39"),
     N_("rules.runtime._.40")),
    (r"failed to execute bulk item|MapperParsingException|mapper_parsing_exception|DocumentParsingException|document_parsing_exception",
     Severity.WARNING, N_("rules.runtime._.41"),
     N_("rules.runtime._.42")),
    # a logged trip is the same evidence as a tripped counter: Warning, as in BRK-001
    (r"CircuitBreakingException", Severity.WARNING, N_("rules.runtime._.43"),
     N_("rules.runtime._.44")),
    (r"rejected execution of (?:coordinating|primary|replica) operation", Severity.WARNING, N_("rules.runtime._.63"),
     N_("rules.runtime._.64")),
    (r"^(?!.*rejected execution of (?:coordinating|primary|replica) operation).*(?:EsRejectedExecutionException|rejected execution)",
     Severity.WARNING, N_("rules.runtime._.45"), N_("rules.runtime._.46")),
    (r"\[gc\]\[old\]|\[gc\]\[\d+\] overhead, spent",
     Severity.WARNING, N_("rules.runtime._.47"),
     N_("rules.runtime._.48")),
    # JvmGcMonitorService logs a young collection at WARN once it exceeds monitor.jvm.gc.collector.young.warn (1s); with G1 most
    # long stop-the-world pauses are young collections
    (r"WARN.*\[gc\]\[young\]\[\d+\]\[\d+\] duration", Severity.WARNING, N_("rules.runtime._.65"),
     N_("rules.runtime._.66")),
    (r"failed to flush", Severity.INFO, N_("rules.runtime._.49"), ""),
    (r"high disk watermark \[[^\]]*\] exceeded|flood stage disk watermark \[[^\]]*\] exceeded on .*marked read-only",
     Severity.CRITICAL, N_("rules.runtime._.50"),
     N_("rules.runtime._.51")),
    # a dedicated frozen node only logs the flood stage and blocks nothing (DiskThresholdMonitor)
    (r"flood stage disk watermark \[[^\]]*\] exceeded on (?!.*marked read-only)",
     Severity.INFO, N_("rules.runtime._.58"),
     N_("rules.runtime._.59")),
    (r"low disk watermark \[[^\]]*\] exceeded",
     Severity.WARNING, N_("rules.runtime._.56"),
     N_("rules.runtime._.57")),
    (r"transport.*Connection reset|NodeDisconnectedException|node_disconnected",
     Severity.WARNING, N_("rules.runtime._.52"),
     N_("rules.runtime._.53")),
    (r"ShardLockObtainFailedException", Severity.WARNING, N_("rules.runtime._.54"),
     N_("rules.runtime._.55")),
]


# JVM option lines printed at startup (-XX:+ExitOnOutOfMemoryError, HeapDumpOnOutOfMemoryError, etc.) are not errors
_STARTUP_NOISE = re.compile(r"JVM arguments|-XX:[+-]\w*OutOfMemoryError|JVM home|JVM version")


def _es_log_files(files):
    """Keeps only ES server logs. gc.log* is a JVM unified log, so ES patterns do not apply to it,
    and <cluster>_server.json is the JSON version of the same content as <cluster>.log, so it is excluded when that .log file is present, to avoid counting twice (a rolled .json.gz likewise when the
    matching .log.gz is present).
    """
    names = set(files)
    out = []
    for f in files:
        base = f.rsplit("/", 1)[-1].lower()
        if base.startswith("gc.log"):
            continue
        if base.endswith("_server.json"):
            twin = f[: -len("_server.json")] + ".log"
            if twin in names:
                continue
        if base.endswith(".json.gz") and (f[: -len(".json.gz")] + ".log.gz") in names:
            continue
        out.append(f)
    return out


def r_logs(ctx):
    """No logs/ directory → Info (LOG-000). If the bundle was collected in local/remote mode and diagnostics.log shows that the tool failed to match the target node, that failure is reported as the cause of the missing logs; otherwise the finding says the bundle has no server logs. If logs exist, scans only the last log_scan_bytes of each file, up to 40 files (gc.log* and duplicate _server.json excluded), for fixed patterns (OOM, long old GC, master not discovered, CircuitBreaking, rejected execution, watermark exceeded, node disconnected, mapping parse errors, etc.). The finding takes the highest severity among the detected patterns (LOG-001); none detected → OK."""
    files = ctx.b.log_files()
    if not files:
        dlog = ctx.b.text("diagnostics.log") or ""
        marker = next((m for m in ("Could not find the target node", "Could not match node publish address",
                                   "Error occurred checking the network hosts information", "Bypassing system calls")
                       if m in dlog), None)
        if marker and (ctx.diag_type or "") in ("local", "remote"):
            return [Finding(
                "LOG-000", CAT, Severity.INFO, T("rules.runtime.r_logs.01") % ctx.diag_type,
                observed=T("rules.runtime.r_logs.02") % marker,
                impact=T("rules.runtime.r_logs.03"),
                recommend=T("rules.runtime.r_logs.04") if ctx.diag_type == "local" else T("rules.runtime.r_logs.19"),
                source="diagnostics.log")]
        return [Finding(
            "LOG-000", CAT, Severity.INFO, T("rules.runtime.r_logs.05"),
            observed=T("rules.runtime.r_logs.06")
                     % (ctx.diag_type or "api"),
            impact=T("rules.runtime.r_logs.07"),
            recommend=T("rules.runtime.r_logs.18") if ctx.orchestrated else T("rules.runtime.r_logs.08"),
            source="manifest.json")]
    counts = collections.Counter()
    samples = {}
    scanned = 0
    files = _es_log_files(files)
    for rel in files[:40]:
        text = ctx.b.read_log(rel, ctx.t["log_scan_bytes"])
        if not text:
            continue
        scanned += 1
        for pat, sev, label, hint in _LOG_PATTERNS:
            rx = re.compile(pat, re.IGNORECASE)
            label, hint = tr(label), tr(hint)
            n = 0
            for ln in text.splitlines():
                if _STARTUP_NOISE.search(ln):
                    continue
                if rx.search(ln):
                    n += 1
                    if label not in samples:
                        samples[label] = (rel, truncate(ln.strip(), 220))
            if n:
                counts[(label, sev, hint)] += n
    out = []
    if not counts:
        return [Finding("LOG-001", CAT, Severity.OK, T("rules.runtime.r_logs.09"),
                        observed=T("rules.runtime.r_logs.10") % scanned,
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
        "LOG-001", CAT, worst, T("rules.runtime.r_logs.11"),
        observed=T("rules.runtime.r_logs.12") % (scanned, len(counts)),
        impact=T("rules.runtime.r_logs.13"),
        recommend=" ".join(recs),
        evidence=table([T("rules.runtime.r_logs.14"), T("rules.runtime.r_logs.15"), T("rules.runtime.r_logs.16"), T("rules.runtime.r_logs.17")], rows[: ctx.t["top_n"]]),
        source="logs/"))
    return out


RULES = [r_hot_threads, r_logs]
