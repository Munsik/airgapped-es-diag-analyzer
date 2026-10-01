#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checks for the Elastic Support summary (--support-summary) and masking. No external bundle needed (synthetic data).

Canary identifiers are planted across the bundle (cluster name, node names, hosts, IPs, paths, certificate,
license, repository, index, log, hot threads). Every check confirms that none survives in the summary.
All checks run in both languages (ko and en). The CLI part also checks the --lang output file names.

    python3 tests/test_handoff.py
"""
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import re  # noqa: E402

from esdiag.engine import analyze  # noqa: E402
from esdiag.i18n import T, set_lang  # noqa: E402
from esdiag.mask import Masker  # noqa: E402
from esdiag.report import handoff  # noqa: E402

FAILS, N = [], [0]
HANGUL = re.compile(u"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3]")

CLUSTER = "zetacorp-prod-cluster"
NODES = ["zetadata-node-01", "zetadata-node-02"]
HOSTS = ["zetahost01.zetacorp.internal", "zetahost02.zetacorp.internal"]
IPS = ["10.77.31.11", "10.77.31.12"]
INDEX = "zetasecret-orders-2026.09"
PATH_DATA = "/zetavol/esdata"
CERT_DN = "CN=zetacert.zetacorp.internal,OU=zetaorg,O=ZetaCorp"
LICENSEE = "ZetaCorp Holdings"
REPO_BUCKET = "zeta-snapshots-bucket"
LOG_SAMPLE = "zetalogtoken failed to connect to 10.77.31.99"
CANARY_ALWAYS = [CLUSTER] + NODES + HOSTS + IPS + [PATH_DATA, "zetacert", LICENSEE, REPO_BUCKET, "10.77.31.99"]
CANARY_STRICT_ONLY = [INDEX]
CANARY_RAW = ["zetalogtoken", "zetahotstack"]


def check(name, cond, detail=""):
    N[0] += 1
    if not cond:
        FAILS.append(name + (" - " + str(detail) if detail else ""))


def w(root, rel, data):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(data if isinstance(data, str) else json.dumps(data))


def build(root):
    w(root, "manifest.json", {"diagVersion": "9.4.1", "collectionDate": "2026-09-29T00:00:00Z",
                              "diagnosticInputs": "DiagnosticInputs: {, diagType='local', mode='full'}"})
    w(root, "version.json", {"cluster_name": CLUSTER, "cluster_uuid": "AbCdEfGhIjKlMnOpQrStUv",
                             "version": {"number": "8.19.21"}})
    w(root, "cluster_health.json", {"cluster_name": CLUSTER, "status": "red", "number_of_nodes": 2,
                                    "number_of_data_nodes": 2, "active_primary_shards": 1, "active_shards": 1,
                                    "unassigned_shards": 3, "unassigned_primary_shards": 1,
                                    "active_shards_percent_as_number": 25.0})
    nodes, stats = {}, {}
    for i in range(2):
        nid = "zetaNodeId%02dXXXXXXXXXXXX" % i
        nodes[nid] = {"name": NODES[i], "host": HOSTS[i], "ip": IPS[i], "version": "8.19.21",
                      "transport_address": IPS[i] + ":9300", "roles": ["master", "data"],
                      "attributes": {"zone": "zetazone-a", "k8s_node_name": HOSTS[i]},
                      "settings": {"path": {"data": [PATH_DATA], "logs": "/zetavol/eslogs"},
                                   "node": {"name": NODES[i]}, "cluster": {"name": CLUSTER}},
                      "jvm": {"mem": {"heap_max_in_bytes": 4 * 1024 ** 3}},
                      "os": {"allocated_processors": 4, "mem": {"total_in_bytes": 16 * 1024 ** 3}}}
        stats[nid] = {"name": NODES[i], "host": HOSTS[i], "ip": IPS[i],
                      "jvm": {"mem": {"heap_used_percent": 96, "heap_max_in_bytes": 4 * 1024 ** 3,
                                      "heap_used_in_bytes": 4000000000}},
                      "fs": {"total": {"total_in_bytes": 100 * 1024 ** 3, "available_in_bytes": 3 * 1024 ** 3,
                                       "free_in_bytes": 3 * 1024 ** 3}}}
    w(root, "nodes.json", {"nodes": nodes})
    w(root, "nodes_stats.json", {"nodes": stats})
    w(root, "indices.json", [
        {"index": INDEX, "shard": "0", "prirep": "p", "state": "STARTED", "node": NODES[0], "store": "1000"},
        {"index": INDEX, "shard": "0", "prirep": "r", "state": "UNASSIGNED", "node": None, "ur": "NODE_LEFT",
         "ud": "node_left [%s] ip %s" % (NODES[1], IPS[1])}])
    w(root, "licenses.json", {"license": {"type": "enterprise", "issued_to": LICENSEE, "uid": "zeta-uid-1234",
                                          "issuer": "API"}})
    w(root, "ssl_certs.json", [{"path": "/zetavol/certs/node.p12", "format": "PKCS12", "alias": "n",
                                "subject_dn": CERT_DN, "serial_number": "1", "has_private_key": True,
                                "expiry": "2026-10-01T00:00:00.000Z"}])
    w(root, "repositories.json", [{"id": "zetarepo", "type": "s3",
                                   "settings": {"bucket": REPO_BUCKET, "base_path": "zetabase"}}])
    w(root, "logs/c_server.json", '{"@timestamp":"2026-09-29T00:00:00Z","log.level":"ERROR","message":"%s",'
                                  '"log.logger":"o.e.x","elasticsearch.node.name":"%s"}\n' % (LOG_SAMPLE, NODES[0]))
    w(root, "nodes_hot_threads.txt", "::: {%s}{x}{%s}\n   99.0%% [cpu=99%%] zetahotstack\n" % (NODES[0], IPS[0]))


def render(res, level):
    m = Masker(res.ctx, level=level)
    return m, handoff.render(res, m, level, "test")


def run_lang(lang, tmp):
    """Masking and round-trip checks for one output language."""
    set_lang(lang)
    root = os.path.join(tmp, "b-" + lang)
    build(root)
    res = analyze(root)
    pre = "[%s] " % lang
    check(pre + "synthetic bundle yields critical/warning findings", len(res.priority()) > 0)

    # 1) Canary leak check per masking level
    for level in ("basic", "strict"):
        m, out = render(res, level)
        low = out.lower()
        for c in CANARY_ALWAYS + CANARY_RAW:
            check("%s%s: canary absent %s" % (pre, level, c), c.lower() not in low)
        if level == "strict":
            for c in CANARY_STRICT_ONLY:
                check(pre + "strict: index name absent", c.lower() not in low)
        check("%s%s: alias is used" % (pre, level), "node-001" in out)
        if lang == "en":
            check("%s%s: English summary has no Hangul" % (pre, level), not HANGUL.search(out),
                  HANGUL.findall(out)[:10])
    # basic keeps index names as they are (confirms the two levels differ)
    _m, out_b = render(res, "basic")
    check(pre + "basic: index name kept (only strict masks it)", "index-001" not in out_b)

    # 2) none does not mask
    m, out_n = render(res, "none")
    check(pre + "none: cluster name unchanged", CLUSTER in out_n)
    check(pre + "none: raw columns (samples, stacks) still excluded",
          "zetalogtoken" not in out_n and "zetahotstack" not in out_n)
    if lang == "en":
        check(pre + "none: English summary has no Hangul", not HANGUL.search(out_n), HANGUL.findall(out_n)[:10])

    # 3) Mapping round trip: every alias in the summary is in the map, and restoring gives the original names
    m, out = render(res, "strict")
    mp = m.mapping()
    check(pre + "mapping has the original node name", any(v["original"] == NODES[0] for v in mp.values()))
    restored = out
    for alias in sorted(mp, key=len, reverse=True):
        restored = restored.replace(alias, mp[alias]["original"])
    check(pre + "restore brings back the cluster name", CLUSTER in restored)
    check(pre + "restore brings back the node name", NODES[0] in restored)
    # the same value always gets the same alias
    check(pre + "consistency: same input, same alias", m.text(NODES[0]) == m.text(NODES[0]) != NODES[0])

    # 4) Fail closed: if masking fails, no summary is produced
    class Broken(Masker):
        def text(self, s):
            return s
    bm = Broken(res.ctx, level="basic")
    raised = False
    try:
        handoff.render(res, bm, "basic", "test")
    except handoff.MaskLeak as exc:
        raised = bool(exc.leaks)
    check(pre + "MaskLeak when masking fails", raised)


def run(cli, *extra, **kw):
    return subprocess.run(cli + list(extra), stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)


def cli_checks(tmp, root):
    cli = [sys.executable, os.path.join(ROOT, "analyze.py"), root, "--quiet"]

    # --lang both (the default): <name>.ko.md and <name>.en.md
    out_md = os.path.join(tmp, "sum.md")
    ko_md, en_md = os.path.join(tmp, "sum.ko.md"), os.path.join(tmp, "sum.en.md")
    p = run(cli, "--support-summary", out_md)
    check("CLI: default run exits 0", p.returncode == 0, p.stderr.decode("utf-8", "replace")[-300:])
    check("CLI: --lang both writes sum.ko.md", os.path.isfile(ko_md))
    check("CLI: --lang both writes sum.en.md", os.path.isfile(en_md))
    check("CLI: --lang both does not write the bare name", not os.path.exists(out_md))
    mp_path = out_md + ".mask-map.json"
    check("CLI: mapping file written", os.path.isfile(mp_path))
    if os.path.isfile(mp_path) and os.name == "posix":
        check("CLI: mapping file mode is 0600", stat.S_IMODE(os.stat(mp_path).st_mode) == 0o600)
    for lang, path in (("ko", ko_md), ("en", en_md)):
        if not os.path.isfile(path):
            continue
        raw = io.open(path, encoding="utf-8").read()
        set_lang(lang)
        check("CLI [%s]: no canary in summary" % lang,
              not any(c.lower() in raw.lower() for c in CANARY_ALWAYS + CANARY_RAW))
        check("CLI [%s]: Elastic Support heading present" % lang, T("report.handoff.render.01") in raw)
        check("CLI [%s]: alias used" % lang, "node-001" in raw)
        if lang == "en":
            check("CLI [en]: English summary has no Hangul", not HANGUL.search(raw), HANGUL.findall(raw)[:10])
        else:
            check("CLI [ko]: Korean summary has Hangul", bool(HANGUL.search(raw)))
    set_lang("ko")

    # --lang en / --lang ko write the exact path
    for lang in ("en", "ko"):
        exact = os.path.join(tmp, "only-%s.md" % lang)
        p = run(cli, "--support-summary", exact, "--lang", lang)
        check("CLI: --lang %s exits 0" % lang, p.returncode == 0, p.stderr.decode("utf-8", "replace")[-300:])
        check("CLI: --lang %s writes the exact path" % lang, os.path.isfile(exact))
        stem = os.path.join(tmp, "only-%s" % lang)
        check("CLI: --lang %s writes no language-suffixed file" % lang,
              not os.path.exists(stem + ".ko.md") and not os.path.exists(stem + ".en.md"))
        if os.path.isfile(exact):
            raw = io.open(exact, encoding="utf-8").read()
            check("CLI: --lang %s summary has no canary" % lang,
                  not any(c.lower() in raw.lower() for c in CANARY_ALWAYS + CANARY_RAW))
            if lang == "en":
                check("CLI: --lang en summary has no Hangul", not HANGUL.search(raw), HANGUL.findall(raw)[:10])
    # --lang en with --mask strict also keeps the index name out
    exact = os.path.join(tmp, "strict-en.md")
    run(cli, "--support-summary", exact, "--lang", "en", "--mask", "strict")
    if os.path.isfile(exact):
        raw = io.open(exact, encoding="utf-8").read().lower()
        check("CLI: --lang en --mask strict hides the index name", INDEX.lower() not in raw)
    else:
        check("CLI: --lang en --mask strict writes a summary", False)

    out2 = os.path.join(tmp, "n.md")
    p = run(cli, "--support-summary", out2, "--mask", "none")
    check("CLI: --mask none writes no mapping file",
          p.returncode == 0 and not os.path.exists(out2 + ".mask-map.json"))

    p = run(cli, "--mask", "strict")
    check("CLI: --mask alone is an error", p.returncode == 2, p.returncode)
    clean = os.path.join(tmp, "clean")
    os.makedirs(clean)
    p = run(cli, cwd=clean)
    check("CLI: no summary or mapping file without options", p.returncode == 0 and not os.listdir(clean))


def main():
    tmp = tempfile.mkdtemp()
    try:
        for lang in ("ko", "en"):
            run_lang(lang, tmp)
        cli_checks(tmp, os.path.join(tmp, "b-ko"))
    finally:
        set_lang("ko")
        shutil.rmtree(tmp, ignore_errors=True)
    print("handoff checks: %d run, %d failed" % (N[0], len(FAILS)))
    for f in FAILS:
        print("  FAIL:", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
