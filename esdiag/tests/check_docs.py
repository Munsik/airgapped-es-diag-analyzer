#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""문서 정합성 검사. README·RULES.md·COVERAGE.md·CHANGELOG.md 에 적힌 수치와 목록이 코드와 맞는지 확인한다.

    python3 tests/check_docs.py [번들.zip]

번들을 주면 검증 수치(단정문·시나리오·포맷 문자열 개수)까지 실제 실행 결과와 대조한다.
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

import esdiag                                                  # noqa: E402
from esdiag.basis import _MAP                                  # noqa: E402
from esdiag.diff import DIFF_RULES                             # noqa: E402
from esdiag.rules import MODULES, all_rules                    # noqa: E402
from esdiag.settings_kb import KB, PREFIX_RULES                # noqa: E402
from esdiag.thresholds import DEFAULTS                         # noqa: E402

FAILS, OKS = [], []


def check(name, cond, detail=""):
    (OKS if cond else FAILS).append(name + ("" if cond else " — " + detail))


def read(name):
    return io.open(os.path.join(ROOT, name), encoding="utf-8").read()


def main():
    readme, rules_md, cov, chg = read("README.md"), read("RULES.md"), read("COVERAGE.md"), read("CHANGELOG.md")
    single, diff = len(all_rules()), len(DIFF_RULES) + 1
    total = single + diff
    basis = collections.Counter(_MAP.values())

    check("README 룰 수", "**%d개 판정 룰** — 단일 번들 %d개 + 두 번들 비교 %d개" % (total, single, diff) in readme,
          "코드: %d = %d + %d" % (total, single, diff))
    check("README 문서 표의 룰 수", "| [RULES.md](RULES.md) | %d개 룰" % total in readme)
    n_rule_heads = len(re.findall(r"\n### [A-Z]{2,4}-\d{3}", rules_md))
    check("RULES.md 룰 수", n_rule_heads == total, "RULES.md %d / 코드 %d" % (n_rule_heads, total))
    for label in ("공식 기준", "사실 보고", "도구 판단"):
        check("README 근거 구분 수(%s)" % label, re.search(r"\| %s \|[^\n]*\| %d \|" % (label, basis[label]), readme) is not None,
              "코드: %d" % basis[label])
    check("README 임계값 수", "임계값 %d개" % len(DEFAULTS) in readme, "코드: %d" % len(DEFAULTS))
    n_index_kb = len([v for v in KB.values() if v["scope"] == "index"])
    check("README 인덱스 설정 지식 베이스 수", "인덱스 설정 지식 베이스(%d종)" % n_index_kb in readme, "코드: %d" % n_index_kb)
    check("README 설정 지식 베이스 수", "설정 %d종 지식 베이스" % (len(KB) + len(PREFIX_RULES)) in readme,
          "코드: %d" % (len(KB) + len(PREFIX_RULES)))
    check("CHANGELOG 룰 수", "단일 번들 판정 룰 %d개, 두 번들 비교 룰 %d개" % (single, diff) in chg)
    check("CHANGELOG 판정 ID 수", "판정 ID %d개" % len(_MAP) in chg, "코드: %d" % len(_MAP))
    check("CHANGELOG 지식 베이스 수", "설정 지식 베이스 %d종" % (len(KB) + len(PREFIX_RULES)) in chg)

    # 도구 버전
    check("README 도구 버전", "**버전 %s**" % esdiag.__version__ in readme, "코드: %s" % esdiag.__version__)
    check("CHANGELOG 최신 버전", "## [%s]" % esdiag.__version__ in chg, "코드: %s" % esdiag.__version__)
    check("RULES.md 도구 버전", "| 도구 버전 | esdiag %s |" % esdiag.__version__ in rules_md)

    # 버전 기준점·분기
    check("README 기준 버전", "| 판정 기준 Elasticsearch 버전 | **%d.%d** |" % esdiag.ES_BASELINE in readme)
    check("README 문서 대조 시점", "| 공식 문서 대조 시점 | %s |" % esdiag.DOCS_CHECKED in readme)
    for ver, target, _desc in esdiag.VERSION_GATES:
        check("README 버전 분기 %d.%d %s" % (ver + (target,)), "| %d.%d | %s |" % (ver + (target,)) in readme)

    # 모듈·옵션 목록
    mods = [m.__name__.split(".")[-1] for m in MODULES]
    check("README --only 모듈 목록", all("`%s`" % m in readme.split("--only MODULE")[1].split("\n")[0] for m in mods),
          ", ".join(mods))
    src = read("analyze.py")
    opts = re.findall(r'add_argument\("(--[a-z-]+)"', src)
    table = readme.split("### 옵션")[1].split("\n종료 코드:")[0]
    missing = [o for o in opts if o not in table]
    check("README 옵션 표에 모든 CLI 옵션", not missing, "누락: %s" % missing)

    # 파일 참조 존재
    for name in re.findall(r"`((?:esdiag|tools|tests)/[\w/]+\.(?:py|sh))`", readme + cov + chg):
        check("문서가 참조하는 파일 존재: %s" % name, os.path.exists(os.path.join(ROOT, name)))
    for name in re.findall(r"\]\(([A-Z]+\.md)\)", readme + cov + chg):
        check("문서 링크 존재: %s" % name, os.path.exists(os.path.join(ROOT, name)))

    # RULES.md 가 최신인지(재생성 결과와 동일)
    out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "gen_rules_doc.py"), "--check"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    check("RULES.md 생성기 정합성", out.returncode == 0, out.stdout.strip()[-200:])
    ids_in_rules = set(re.findall(r"\b([A-Z]{2,4}-\d{3})\b", rules_md))
    missing_ids = sorted(i for i in _MAP if i not in ids_in_rules)
    check("모든 판정 ID 가 RULES.md 에 있음", not missing_ids, str(missing_ids))

    emitted = set()
    for path in [os.path.join(ROOT, "esdiag", "rules", f) for f in os.listdir(os.path.join(ROOT, "esdiag", "rules"))
                 if f.endswith(".py")] + [os.path.join(ROOT, "esdiag", "engine.py")]:
        for node in ast.walk(ast.parse(read(os.path.relpath(path, ROOT)))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Finding" and node.args:
                a = node.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    emitted.add(a.value.split(".")[0])
                elif isinstance(a, ast.BinOp) and isinstance(a.left, ast.Constant):
                    emitted.add(a.left.value.rstrip("."))
    check("근거 구분 표에 코드가 내지 않는 ID 없음", not sorted(set(_MAP) - emitted), str(sorted(set(_MAP) - emitted)))
    check("코드가 내는 ID 는 모두 근거 구분 표에 있음", not sorted(emitted - set(_MAP)), str(sorted(emitted - set(_MAP))))

    # 검증 수치(번들이 있으면 실제 실행 결과와 대조)
    if len(sys.argv) > 1:
        b = sys.argv[1]
        def last(cmd):
            p = subprocess.run([sys.executable] + cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               universal_newlines=True, cwd=ROOT)
            return p.stdout.strip().splitlines()[-1]
        lf = re.search(r"포맷 문자열 (\d+)개", last(["tests/lint_format.py"])).group(1)
        vl = re.search(r"(\d+) passed", last(["tests/verify_logic.py", b])).group(1)
        db = re.search(r"시나리오 (\d+)개", last(["tests/drive_branches.py", b])).group(1)
        check("README 포맷 문자열 수", "| %s개, 문제 0 |" % lf in readme, "실행: %s" % lf)
        check("README 단정문 수", "| %s개 통과 |" % vl in readme, "실행: %s" % vl)
        check("README 시나리오 수", "시나리오 %s개로" % db in readme and "| %s개 통과, 미실행 판정 분기 0 |" % db in readme,
              "실행: %s" % db)

    for f in FAILS:
        print("FAIL " + f)
    print("문서 정합성 %d개 확인, 불일치 %d건" % (len(OKS) + len(FAILS), len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
