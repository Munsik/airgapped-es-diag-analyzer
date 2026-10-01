#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Logic checks. Runs without external dependencies.

    python3 tests/verify_logic.py [healthy_bundle.zip]

With a bundle, the bundle-based checks also run: zero rule errors, zero changes when the bundle is
compared with itself, and a basis mapping for every finding. All checks run once per language (en, ko).
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from esdiag.basis import _MAP, basis_of                      # noqa: E402
from esdiag.i18n import T, tr, set_lang, get_lang            # noqa: E402
from esdiag.model import Severity                            # noqa: E402
from esdiag.rules.guidance import _gc_logging_enabled        # noqa: E402
from esdiag.util import parse_bytes, parse_time_ms           # noqa: E402

GB, TB = 1024 ** 3, 1024 ** 4
PASS, FAIL = [], []
LANGS = ("en", "ko")
set_lang("en")


def check(name, cond, detail=""):
    name = "[%s] %s" % (get_lang(), name)
    (PASS if cond else FAIL).append(name + ((": " + detail) if detail and not cond else ""))


def _small_shard_total_ok(observed, total):
    """True when the SHD-004 text states `total` as its primary shard count (other numbers are wildcards)."""
    sent = (total, 55555, 66666.0, 77777, 88888)
    pat = re.escape(str(T("rules.shards.r_small_shards.02") % sent))
    for tok in ("55555", "66666", "77777", "88888"):
        pat = pat.replace(tok, r"\d+")
    return re.search(pat, observed) is not None


class _FakeCtx(object):
    """Minimal context, only enough to verify watermark_used_pct."""
    def __init__(self, settings):
        self._s = settings
        self.t = {"disk_watermark_low_default": "85%", "disk_watermark_high_default": "90%",
                  "disk_watermark_flood_default": "95%"}

    def setting(self, key, default=None):
        return self._s.get(key, default)

    def watermark(self, kind):
        return self._s.get("cluster.routing.allocation.disk.watermark." + kind)


def test_units():
    check("parse_bytes 1.5tb", parse_bytes("1.5tb") == int(1.5 * TB))
    check("parse_bytes 150GB", parse_bytes("150GB") == 150 * GB)
    check("parse_bytes plain number", parse_bytes(1024) == 1024)
    check("parse_time 30s", parse_time_ms("30s") == 30000)
    check("parse_time -1", parse_time_ms("-1") == -1)


def test_watermark():
    from esdiag.context import Context
    defaults = {
        "cluster.routing.allocation.disk.watermark.low": "85%",
        "cluster.routing.allocation.disk.watermark.high": "90%",
        "cluster.routing.allocation.disk.watermark.flood_stage": "95%",
        "cluster.routing.allocation.disk.watermark.low.max_headroom": "200GB",
        "cluster.routing.allocation.disk.watermark.high.max_headroom": "150GB",
        "cluster.routing.allocation.disk.watermark.flood_stage.max_headroom": "100GB",
    }
    fc = _FakeCtx(defaults)
    f = Context.watermark_used_pct
    # 1TB: 10% = 102.4GB < 150GB, so the percentage applies as is (90%)
    check("1TB high = 90%", abs(f(fc, "high", TB) - 90.0) < 0.01, str(f(fc, "high", TB)))
    # 10TB: 10% = 1024GB > 150GB, so the 150GB headroom applies -> 98.535%
    exp = (1 - 150.0 / (10 * 1024)) * 100
    check("10TB high = headroom applied", abs(f(fc, "high", 10 * TB) - exp) < 0.01,
          "%s vs %s" % (f(fc, "high", 10 * TB), exp))
    # A byte-value watermark ignores headroom
    fc2 = _FakeCtx({"cluster.routing.allocation.disk.watermark.high": "100gb",
                    "cluster.routing.allocation.disk.watermark.high.max_headroom": "-1"})
    exp2 = (1 - 100.0 / 1024) * 100
    check("byte watermark 100gb @1TB", abs(f(fc2, "high", TB) - exp2) < 0.01)
    # An explicit headroom of -1 keeps the percentage as is
    fc3 = _FakeCtx({"cluster.routing.allocation.disk.watermark.high": "80%",
                    "cluster.routing.allocation.disk.watermark.high.max_headroom": "-1"})
    check("explicit 80%, headroom disabled @10TB", abs(f(fc3, "high", 10 * TB) - 80.0) < 0.01)


def test_gc_log():
    es_default = ["-Xlog:disable", "-Xlog:all=warning:stderr:utctime,level,tags",
                  "-Xlog:gc*,gc+age=trace,safepoint:file=logs/gc.log:utctime,level,pid,tags:filecount=32,filesize=64m"]
    check("ES default JVM options = GC log enabled", _gc_logging_enabled(es_default))
    check("GC log disabled when only disable is present", not _gc_logging_enabled(["-Xlog:disable", "-Xlog:all=warning:stderr"]))
    check("GC log disabled when the gc option comes before disable",
          not _gc_logging_enabled(["-Xlog:gc*:file=gc.log", "-Xlog:disable"]))


def test_basis():
    check("DIF is a computed basis", basis_of("DIF-005") == "calc")
    check("sub-id mapping", basis_of("CLU-004.disk") == basis_of("CLU-004"))


def test_bundle(path):
    from esdiag.engine import analyze
    r = analyze(path)
    check("healthy bundle: zero rule errors", not r.errors, str([e["rule"] for e in r.errors]))
    unmapped = sorted(set(f.id.split(".")[0] for f in r.findings
                          if f.id.split(".")[0] not in _MAP and not f.id.startswith("DIF")))
    check("every finding id is registered in the basis map", not unmapped, str(unmapped))
    check("every finding has a basis", all(f.basis for f in r.findings))
    r2 = analyze(path, baseline=path)
    difs = [f.id for f in r2.findings if f.id.startswith("DIF")]
    check("comparing a bundle with itself gives zero change findings", not difs, str(difs))
    check("compare mode: zero rule errors", not r2.errors)
    base_ids = sorted((f.id, f.severity) for f in r.findings)
    same_ids = sorted((f.id, f.severity) for f in r2.findings if f.category != "trend")
    check("compare mode: single-bundle findings equal the standalone analysis", base_ids == same_ids)
    ids = [f.id for f in r.findings]
    check("ECH bundle: initial_master_nodes is downgraded to info",
          all(f.severity == "INFO" for f in r.findings if f.id == "CFG-005"))
    check("docker install: CFG-002 does not apply", "CFG-002" not in ids)
    check("logsdb/time_series indices are excluded from the codec finding",
          not any(f.id == "DISK-006" and any("logsdb" in str(row) or "time_series" in str(row)
                                             for row in (f.evidence or {}).get("rows", []))
                  for f in r.findings))


def test_settings_kb():
    from esdiag.settings_kb import compare, KB, DOCS
    ch, d, *_ = compare("indices.recovery.max_bytes_per_sec", "100mb")
    check("setting compare: 40mb to 100mb is an increase", ch and d == "up")
    ch, d, *_ = compare("indices.recovery.max_bytes_per_sec", "40mb")
    check("setting compare: a value equal to the default is not a change", not ch)
    ch, d, *_ = compare("cluster.routing.allocation.disk.watermark.high", "0.95")
    check("setting compare: 90% to 0.95 is a change when the direction cannot be decided", ch and d in ("change", "up"))
    ch, d, *_ = compare("cluster.routing.allocation.exclude._name", "no_instances_excluded")
    check("setting compare: the ECH marker no_instances_excluded counts as default", not ch)
    ch, d, *_ = compare("thread_pool.write.queue_size", "5000")
    check("setting compare: queue 10000 to 5000 is a decrease", ch and d == "down")
    ch, d, spec, dft, src = compare("some.unknown.setting", "x")
    check("setting compare: an unregistered setting reports the value only", ch and spec is None and src == T("settings_kb.compare.03"))
    check("knowledge base: every entry has a doc key", all(v["doc"] in DOCS for v in KB.values()))
    check("knowledge base: kind values are valid", all(v["kind"] in ("dynamic", "static") for v in KB.values()))


def test_kb_against_bundle(path):
    """Compare KB defaults with the defaults ES reported. Only keys set in yml and auto-computed keys may differ."""
    from esdiag.loader import Bundle
    from esdiag.settings_kb import KB, compare, AUTO_DEFAULT
    from esdiag.rules.settings import _flat
    b = Bundle(path)
    d = _flat((b.json("cluster_settings_defaults.json") or {}).get("defaults") or {})
    yml = set()
    for n in (b.json("nodes.json") or {}).get("nodes", {}).values():
        yml |= set(_flat(n.get("settings") or {}).keys())
    bad = []
    for k, spec in KB.items():
        if spec["scope"] == "index" or k not in d or k in yml or k in AUTO_DEFAULT:
            continue
        if compare(k, d[k])[0]:
            bad.append("%s: KB=%s ES=%s" % (k, spec["default"], d[k]))
    check("knowledge base defaults = ES reported defaults (yml and auto-computed keys excluded)", not bad, "; ".join(bad))


def test_multitier(path):
    """Recreate a multi-tier, rollover and searchable snapshot setup (regression guard for false positives seen in a 9.5 multi-tier customer bundle)."""
    import json, shutil, tempfile, zipfile
    from esdiag.engine import analyze
    from esdiag.rules.runtime import _classify
    tmp = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(path) as z:
            z.extractall(tmp)
        root = [os.path.join(tmp, d) for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))][0]
        J = lambda n: json.load(open(os.path.join(root, n), encoding="utf-8"))
        W = lambda n, o: json.dump(o, open(os.path.join(root, n), "w", encoding="utf-8"))
        ni, ns = J("nodes.json"), J("nodes_stats.json")
        ids = list(ni["nodes"].keys())
        # Node 0: hot 15GB. Node 1: cold 7.5GB (other tier, other heap). Node 2: frozen (disk 90% = shared cache).
        roles = [["data_hot", "data_content", "master"], ["data_cold", "master"], ["data_frozen", "master"]]
        heaps = [15 * GB, 7.5 * GB, 2 * GB]
        # Spread all nodes over the 3 tiers whatever the node count (heap is equal within a tier)
        for i, nid in enumerate(ids):
            k = min(i, 2) if len(ids) <= 3 else i % 3
            ni["nodes"][nid]["roles"] = roles[k]
            ns["nodes"][nid]["roles"] = roles[k]
            ns["nodes"][nid]["jvm"]["mem"]["heap_max_in_bytes"] = int(heaps[k])
        for i, nid in enumerate(ids):
            k = min(i, 2) if len(ids) <= 3 else i % 3
            node = ns["nodes"][nid]
            node["os"]["cpu"]["available_processors"] = 4                    # CPU is equal within a tier
            ni["nodes"][nid].setdefault("os", {})["available_processors"] = 4
            ni["nodes"][nid]["os"]["allocated_processors"] = 4
            tot = node["fs"]["total"]["total_in_bytes"]
            # frozen uses 90% as shared cache, the others use 50%
            node["fs"]["total"]["available_in_bytes"] = int(tot * (0.099 if k == 2 else 0.5))
        W("nodes.json", ni); W("nodes_stats.json", ns)
        # Data stream: 2 older backing indices (write blocked, one is a partial mount) + 1 write index (no block)
        st = J("settings.json")
        base = {"settings": {"index": {"number_of_shards": "1", "number_of_replicas": "1"}}}   # minimal settings, independent of the bundle
        names = [".ds-logs-app-default-2026.01.01-000001", "partial-.ds-logs-app-default-2026.01.02-000002",
                 ".ds-logs-app-default-2026.01.03-000003"]
        for i, nm in enumerate(names):
            body = json.loads(json.dumps(base))
            body["settings"]["index"]["blocks"] = {"write": "true"} if i < 2 else {}
            if i == 1:
                body["settings"]["index"]["store"] = {"type": "snapshot", "snapshot": {"snapshot_name": "s1"}}
            st[nm] = body
        W("settings.json", st)
        ds = J(os.path.join("commercial", "data_stream.json"))
        ds.setdefault("data_streams", []).append({"name": "logs-app-default", "status": "GREEN",
                                                  "indices": [{"index_name": n} for n in names]})
        W(os.path.join("commercial", "data_stream.json"), ds)
        r = analyze(root)
        got = dict((f.id, f) for f in r.findings)
        check("multi-tier: zero rule errors", not r.errors, str([e["rule"] for e in r.errors]))
        check("frozen node disk at 90% (shared cache) is not a watermark breach",
              not any(i in got and got[i].severity in ("CRITICAL", "WARNING") for i in ("DISK-001", "DISK-002", "DISK-003")))
        check("a heap difference between tiers is not an imbalance finding", "NODE-001" not in got and "NODE-003" in got)
        check("write block on rolled-over backing indices and searchable snapshots is normal",
              "IDX-008" not in got or got["IDX-008"].severity == "OK")
        # A write block on the write index is critical
        st[names[2]]["settings"]["index"]["blocks"] = {"write": "true"}
        W("settings.json", st)
        r2 = analyze(root)
        g2 = dict((f.id, f) for f in r2.findings)
        check("write block on the current write index is critical",
              "IDX-008" in g2 and g2["IDX-008"].severity == "CRITICAL")
        check("a .ds- backing index is a user index", not r.ctx.is_system_index(".ds-logs-app-default-2026.01.01-000001"))
        check("a .ds-.kibana index is a system index", r.ctx.is_system_index(".ds-.kibana-event-log-ds-2026-000001"))
        label, _h = _classify(["app/org.elasticsearch.grok@9.5.3/org.elasticsearch.grok.Grok.match(Grok.java:239)",
                               "org.elasticsearch.index.mapper.DocumentParser.parse"], "write_coordination")
        check("hot threads: classified by the top frame (grok)", label == tr("rules.runtime._.03"), str(label))
        label2, _h2 = _classify([
            "org.elasticsearch.xcontent.impl@9.5.3/org.elasticsearch.xcontent.provider.json.JsonXContentGenerator.copyCurrentStructure",
            "app/org.elasticsearch.server@9.5.3/org.elasticsearch.index.mapper.XContentDataHelper.cloneSubContext",
            "app/org.elasticsearch.server@9.5.3/org.elasticsearch.index.mapper.DocumentParserContext.addIgnoredFieldFromContext"],
            "write")
        check("hot threads: classified by context (ignored field storage) even when the top frame is JSON copy", label2 and label2 == tr("rules.runtime._.09"), str(label2))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_capacity_and_mounts(path):
    """Regression guard: hot tier saturation, warning-level nodes listed, fully/partial mount size findings, empty write index."""
    import json, shutil, tempfile, zipfile
    from esdiag.engine import analyze
    tmp = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(path) as z:
            z.extractall(tmp)
        root = [os.path.join(tmp, d) for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))][0]
        J = lambda n: json.load(open(os.path.join(root, n), encoding="utf-8"))
        W = lambda n, o: json.dump(o, open(os.path.join(root, n), "w", encoding="utf-8"))
        ni, ns = J("nodes.json"), J("nodes_stats.json")
        ids = list(ni["nodes"].keys())
        spec = [(["data_hot", "data_content"], 4, 4.5, 79), (["data_hot", "data_content"], 4, 5.32, 70)] + \
            [(["data_cold"], 4, 0.3, 5)] * max(1, len(ids) - 2)
        for nid, (roles, cpu, load, pct) in zip(ids, spec):
            ni["nodes"][nid]["roles"] = roles
            ns["nodes"][nid]["roles"] = roles
            ns["nodes"][nid]["os"]["cpu"].update({"available_processors": cpu, "percent": pct,
                                                  "load_average": {"1m": load, "5m": load, "15m": load}})
        W("nodes.json", ni); W("nodes_stats.json", ns)
        # Small shards: 60 restored- (fully mounted, real size), 60 partial- (cache size), 1 empty write index
        st, ist, sh = J("settings.json"), J("indices_stats.json"), J("indices.json")
        tmpl = next(iter(ist["indices"].values()))
        node0 = ni["nodes"][ids[2]]["name"]
        def add(name, size, docs, extra):
            st[name] = {"settings": {"index": dict({"number_of_shards": "1", "number_of_replicas": "0"}, **extra)}}
            b = json.loads(json.dumps(tmpl))
            b["primaries"]["store"]["size_in_bytes"] = size
            b["primaries"]["docs"] = {"count": docs, "deleted": 0}
            ist["indices"][name] = b
            sh.append({"index": name, "shard": "0", "prirep": "p", "state": "STARTED", "docs": str(docs),
                       "store": str(size), "node": node0})
        snap = {"store": {"type": "snapshot", "snapshot": {"snapshot_name": "s"}}}
        for i in range(60):
            add("restored-.ds-logs-x-default-2026.01.%02d-%06d" % (i % 28 + 1, i), 50 * 1024 ** 2, 1000, snap)
            add("partial-.ds-logs-y-default-2026.01.%02d-%06d" % (i % 28 + 1, i), 1024 ** 2, 1000,
                {"store": {"type": "snapshot", "snapshot": {"snapshot_name": "s", "partial": "true"}}})
        add(".ds-logs-z-default-2026.09.21-000009", 0, 0, {})
        for k in range(6):
            add("empty-legacy-%d" % k, 0, 0, {})
        ds = J(os.path.join("commercial", "data_stream.json"))
        ds.setdefault("data_streams", []).append({"name": "logs-z-default", "status": "GREEN",
                                                  "indices": [{"index_name": ".ds-logs-z-default-2026.09.21-000009"}]})
        W("settings.json", st); W("indices_stats.json", ist); W("indices.json", sh)
        W(os.path.join("commercial", "data_stream.json"), ds)
        # Primaries of the original bundle minus partial mounts (excluded from the size finding), plus 67 of the added ones that count
        orig = [x for x in J("indices.json") if x.get("prirep") == "p"][:-127]
        def _partial(ix):
            snap = (((st.get(ix) or {}).get("settings") or {}).get("index") or {}).get("store") or {}
            return ix.startswith("partial-") or str((snap.get("snapshot") or {}).get("partial")).lower() == "true"
        base_pri = len([x for x in orig if not _partial(x.get("index", ""))])
        r = analyze(root)
        g = dict((f.id, f) for f in r.findings)
        check("capacity: zero rule errors", not r.errors, str([e["rule"] for e in r.errors]))
        check("hot tier overall CPU saturation finding (HOT-005)", "HOT-005.hot" in g)
        check("OS-001 also lists nodes in the warning range", "OS-001" in g and T("rules.nodes.r_os.05").split("%")[0] in g["OS-001"].observed)
        check("small shards: 60 fully mounted counted, 60 partial excluded",
              "SHD-004" in g and _small_shard_total_ok(g["SHD-004"].observed, base_pri + 60 + 7),
              g["SHD-004"].observed if "SHD-004" in g else "missing")
        e = g.get("SHD-011")
        rows = [row[0] for row in (e.evidence or {}).get("rows", [])] if e else []
        check("empty indices: the current write index is excluded",
              e is not None and ".ds-logs-z-default-2026.09.21-000009" not in rows and
              all(("empty-legacy-%d" % k) in rows for k in range(6)), str(rows))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_partial_bundle(path):
    """Partial bundle with core files only: there must be no false "not configured" findings."""
    import shutil
    import tempfile
    from esdiag.engine import analyze
    from esdiag.loader import Bundle
    src = Bundle(path)
    tmp = tempfile.mkdtemp()
    try:
        for name in ("cluster_health.json", "nodes_stats.json", "nodes.json", "version.json", "manifest.json"):
            rel = src.resolve(name)
            if rel:
                with open(os.path.join(tmp, name), "w", encoding="utf-8") as fh:
                    fh.write(src.text(name))
        r = analyze(tmp)
        ids = [f.id for f in r.findings]
        check("partial bundle: zero rule errors", not r.errors)
        check("partial bundle: uncollected repositories are not reported as not configured", "SNP-001" not in ids)
        check("partial bundle: uncollected awareness is not reported as not configured", "CLU-019" not in ids)
        check("partial bundle: skipped rules are recorded", len(getattr(r.ctx, "skipped_rules", [])) > 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    empty = tempfile.mkdtemp()
    try:
        analyze(empty)
        check("an empty directory is not recognized as a bundle", False)
    except ValueError:
        check("an empty directory is not recognized as a bundle", True)
    finally:
        shutil.rmtree(empty, ignore_errors=True)


def test_thresholds():
    import io, contextlib
    from esdiag.thresholds import merge, DEFAULTS
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        t = merge({"heap_used_pct_warnn": 1, "heap_used_pct_warn": 70})
    check("a misspelled threshold key is not applied", "heap_used_pct_warnn" not in t)
    check("a misspelled threshold key is warned about", "heap_used_pct_warnn" in buf.getvalue())
    check("a valid key is applied", t["heap_used_pct_warn"] == 70)
    check("the defaults object is not modified", DEFAULTS["heap_used_pct_warn"] != 70)


def main():
    for lang in LANGS:
        set_lang(lang)
        test_units()
        test_watermark()
        test_gc_log()
        test_basis()
        test_thresholds()
        test_settings_kb()
        if len(sys.argv) > 1:
            test_bundle(sys.argv[1])
            test_partial_bundle(sys.argv[1])
            test_kb_against_bundle(sys.argv[1])
            test_multitier(sys.argv[1])
            test_capacity_and_mounts(sys.argv[1])
    for p in PASS:
        print("  PASS  " + p)
    for f in FAIL:
        print("  FAIL  " + f)
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
