#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Documentation consistency check.

Verifies that the numbers, lists and links in README, RULES, COVERAGE and CHANGELOG match the code,
in both languages (English files and *.ko.md files).

    python3 tests/check_docs.py [bundle.zip]

With a bundle, the verification counts (assertions, scenarios, format strings) are also compared
with what the test scripts actually print.
"""
import ast
import collections
import io
import os
import re
import subprocess
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

import esdoctor                                                  # noqa: E402
from esdoctor.basis import _MAP                                  # noqa: E402
from esdoctor.diff import DIFF_RULES                             # noqa: E402
from esdoctor.rules import MODULES, all_rules                    # noqa: E402
from esdoctor.settings_kb import KB, PREFIX_RULES                # noqa: E402
from esdoctor.thresholds import DEFAULTS                         # noqa: E402

FAILS, OKS = [], []


def check(name, cond, detail=""):
    (OKS if cond else FAILS).append(name + ("" if cond else ": " + detail))


def read(name):
    return io.open(os.path.join(ROOT, name), encoding="utf-8").read()


# Phrases the documents use, per language. {…} fields are filled from the code.
P = {
    "en": dict(
        files=("README.md", "RULES.md", "COVERAGE.md", "CHANGELOG.md"),
        rules="**%d rules**: %d for a single bundle and %d for comparing two bundles",
        docrow="| [RULES.md](RULES.md) ([한국어](RULES.ko.md)) | Full specification of all %d rules",
        basis=dict(official="Official", fact="Reported fact", tool="Tool threshold"),
        thr="%d thresholds", kb_index="index settings knowledge base (%d settings)",
        chg_rules="%d single-bundle rules and %d bundle-comparison rules", chg_ids="%d finding IDs",
        chg_kb="%d settings in the knowledge base",
        ver="**Version %s**", rules_ver="| Tool version | esdoctor %s |",
        base="| Elasticsearch version used as the baseline | **%d.%d** |",
        checked="| Date checked against the official docs | %s |",
        opts="### Options", exit="\nExit codes:",
        lint="| %s strings, 0 problems |", vl="| %s passed |", db="with %s scenarios", db2="| %s passed, 0 finding branches not run |"),
    "ko": dict(
        files=("README.ko.md", "RULES.ko.md", "COVERAGE.ko.md", "CHANGELOG.ko.md"),
        rules="**%d개 판정 룰** \u2014 단일 번들 %d개 + 두 번들 비교 %d개",
        docrow="| [RULES.ko.md](RULES.ko.md) ([English](RULES.md)) | %d개 룰",
        basis=dict(official="공식 기준", fact="사실 보고", tool="도구 판단"),
        thr="임계값 %d개", kb_index="인덱스 설정 지식 베이스(%d종)",
        chg_rules="단일 번들 판정 룰 %d개, 두 번들 비교 룰 %d개", chg_ids="판정 ID %d개",
        chg_kb="설정 지식 베이스 %d종",
        ver="**버전 %s**", rules_ver="| 도구 버전 | esdoctor %s |",
        base="| 판정 기준 Elasticsearch 버전 | **%d.%d** |",
        checked="| 공식 문서 대조 시점 | %s |",
        opts="### 옵션", exit="\n종료 코드:",
        lint="| %s개, 문제 0 |", vl="| %s개 통과 |", db="시나리오 %s개로", db2="| %s개 통과, 미실행 판정 분기 0 |"),
}


def check_lang(lang, bundle):
    p = P[lang]
    readme, rules_md, cov, chg = [read(f) for f in p["files"]]
    tag = "[%s] " % lang
    single, diff = len(all_rules()), len(DIFF_RULES) + 1
    total = single + diff
    basis = collections.Counter(_MAP.values())

    check(tag + "README rule count", p["rules"] % (total, single, diff) in readme, "code: %d = %d + %d" % (total, single, diff))
    check(tag + "README docs table rule count", p["docrow"] % total in readme)
    n_rule_heads = len(re.findall(r"\n### [A-Z]{2,4}-\d{3}", rules_md))
    check(tag + "RULES rule count", n_rule_heads == total, "RULES %d / code %d" % (n_rule_heads, total))
    for key, label in p["basis"].items():
        n = basis[key]
        check(tag + "README basis count (%s)" % label, re.search(r"\| %s \|[^\n]*\| %d \|" % (label, n), readme) is not None, "code: %d" % n)
    check(tag + "README threshold count", p["thr"] % len(DEFAULTS) in readme, "code: %d" % len(DEFAULTS))
    n_index_kb = len([v for v in KB.values() if v["scope"] == "index"])
    check(tag + "README index settings KB count", p["kb_index"] % n_index_kb in readme, "code: %d" % n_index_kb)
    n_kb = len(KB) + len(PREFIX_RULES)
    check(tag + "README settings KB count", str(n_kb) in readme, "code: %d" % n_kb)
    check(tag + "CHANGELOG rule count", p["chg_rules"] % (single, diff) in chg)
    check(tag + "CHANGELOG finding id count", p["chg_ids"] % len(_MAP) in chg, "code: %d" % len(_MAP))
    check(tag + "CHANGELOG KB count", p["chg_kb"] % n_kb in chg)

    check(tag + "README tool version", p["ver"] % esdoctor.__version__ in readme, "code: %s" % esdoctor.__version__)
    check(tag + "CHANGELOG latest version", "## [%s]" % esdoctor.__version__ in chg, "code: %s" % esdoctor.__version__)
    check(tag + "RULES tool version", p["rules_ver"] % esdoctor.__version__ in rules_md)
    check(tag + "README baseline version", p["base"] % esdoctor.ES_BASELINE in readme)
    check(tag + "README docs check date", p["checked"] % esdoctor.DOCS_CHECKED in readme)
    for ver, target, _desc in esdoctor.VERSION_GATES:
        check(tag + "README version gate %d.%d %s" % (ver + (target,)),
              "| %d.%d | %s |" % (ver + (target,)) in readme.replace("\\*", "*"))

    mods = [m.__name__.split(".")[-1] for m in MODULES]
    check(tag + "README --only module list", all("`%s`" % m in readme.split("--only MODULE")[1].split("\n")[0] for m in mods), ", ".join(mods))
    opts = re.findall(r'add_argument\("(--[a-z-]+)"', read("analyze.py"))
    table = readme.split(p["opts"])[1].split(p["exit"])[0]
    missing = [o for o in opts if o not in table]
    check(tag + "README options table lists every CLI option", not missing, "missing: %s" % missing)

    for name in re.findall(r"`((?:esdoctor|tools|tests|docs)/[\w/]+\.(?:py|sh|md))`", readme + cov + chg):
        check(tag + "referenced file exists: %s" % name, os.path.exists(os.path.join(ROOT, name)))
    for name in re.findall(r"\]\(([A-Za-z]+(?:\.ko)?\.md)\)", readme + cov + chg + rules_md):
        check(tag + "linked document exists: %s" % name, os.path.exists(os.path.join(ROOT, name)))

    ids_in_rules = set(re.findall(r"\b([A-Z]{2,4}-\d{3})\b", rules_md))
    missing_ids = sorted(i for i in _MAP if i not in ids_in_rules)
    check(tag + "every finding id is in RULES", not missing_ids, str(missing_ids))

    # Language hygiene: English files carry no em/en dash and no Hangul except links to the Korean files.
    if lang == "en":
        for f, text in zip(p["files"], (readme, rules_md, cov, chg)):
            stripped = re.sub(r"\[[^\]]*[\uac00-\ud7a3][^\]]*\]\([^)]*\)", "", text)
            stripped = stripped.replace("Elastic 공식 Support 팀", "")
            check(tag + "%s has no em/en dash" % f, not re.search("[\u2013\u2014]", text))
            check(tag + "%s has no Hangul outside links" % f, not re.search("[\uac00-\ud7a3]", stripped))

    if bundle:
        def last(cmd):
            r = subprocess.run([sys.executable] + cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               universal_newlines=True, cwd=ROOT)
            return r.stdout.strip().splitlines()[-1]
        lf = re.search(r"(\d+) format strings", last(["tests/lint_format.py"])).group(1)
        vl = re.search(r"(\d+) passed", last(["tests/verify_logic.py", bundle])).group(1)
        db = re.search(r"(\d+) scenarios", last(["tests/drive_branches.py", bundle])).group(1)
        check(tag + "README format string count", p["lint"] % lf in readme, "run: %s" % lf)
        check(tag + "README assertion count", p["vl"] % vl in readme, "run: %s" % vl)
        check(tag + "README scenario count", p["db"] % db in readme and p["db2"] % db in readme, "run: %s" % db)


def main():
    bundle = sys.argv[1] if len(sys.argv) > 1 else None
    for lang in ("en", "ko"):
        check_lang(lang, bundle)

    for gen_lang, f in (("en", "RULES.md"), ("ko", "RULES.ko.md")):
        out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "gen_rules_doc.py"), "--check"],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        check("rules generator consistency", out.returncode == 0, out.stdout.strip()[-200:])
        break

    emitted = set()
    for path in [os.path.join(ROOT, "esdoctor", "rules", f) for f in os.listdir(os.path.join(ROOT, "esdoctor", "rules"))
                 if f.endswith(".py")] + [os.path.join(ROOT, "esdoctor", "engine.py")]:
        for node in ast.walk(ast.parse(read(os.path.relpath(path, ROOT)))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Finding" and node.args:
                a = node.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    emitted.add(a.value.split(".")[0])
                elif isinstance(a, ast.BinOp) and isinstance(a.left, ast.Constant):
                    emitted.add(a.left.value.rstrip("."))
    check("basis table has no id the code never emits", not sorted(set(_MAP) - emitted), str(sorted(set(_MAP) - emitted)))
    check("every emitted id is in the basis table", not sorted(emitted - set(_MAP)), str(sorted(emitted - set(_MAP))))

    for f in FAILS:
        print("FAIL " + f)
    print("%d doc checks, %d mismatches" % (len(OKS) + len(FAILS), len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
