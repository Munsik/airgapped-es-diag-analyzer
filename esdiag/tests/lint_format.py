#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""% 포맷 문자열 정적 검사.

'문자열 % 값' 형태에서 포맷 문자열 안의 '%' 가 올바른 변환 지정자(%s, %d, %.1f, %% 등)인지 확인한다.
'70% 이상' 처럼 리터럴 % 를 %% 로 쓰지 않으면 실행 시 ValueError 가 난다. 해당 분기가 드물게 실행되면
테스트로는 잡히지 않으므로, 코드를 실행하지 않고 AST 로 전수 검사한다.

    python3 tests/lint_format.py
"""
import ast
import glob
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SPEC = re.compile(r"%(\([^)]*\))?[#0\- +]*(\*|\d+)?(\.(\*|\d+))?[diouxXeEfFgGcrsa%]")


def bad_percents(fmt):
    """유효한 지정자로 설명되지 않는 % 위치 목록."""
    covered = set()
    for m in SPEC.finditer(fmt):
        covered.update(range(m.start(), m.end()))
    return [i for i, ch in enumerate(fmt) if ch == "%" and i not in covered]


def count_specs(fmt):
    return len([m for m in SPEC.finditer(fmt) if not m.group(0).endswith("%")])


def main():
    problems = []
    files = sorted(glob.glob(os.path.join(ROOT, "esdiag", "**", "*.py"), recursive=True)) + \
        [os.path.join(ROOT, "analyze.py")]
    checked = 0
    for path in files:
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)
        # 모듈 수준 문자열 상수(ORCH_NOTE 등)도 포맷 문자열로 쓰이면 검사한다
        consts = {}
        for n in tree.body:
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        consts[t.id] = n.value.value
        for node in ast.walk(tree):
            if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod)):
                continue
            if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
                fmt = node.left.value
            elif isinstance(node.left, ast.Name) and node.left.id in consts:
                fmt = consts[node.left.id]
            else:
                continue
            if True:
                checked += 1
                bad = bad_percents(fmt)
                if bad:
                    i = bad[0]
                    problems.append("%s:%d  잘못된 %% 사용: ...%s..." % (
                        os.path.relpath(path, ROOT), node.lineno, fmt[max(0, i - 12):i + 8].replace("\n", " ")))
                    continue
                # 인자 개수 대조(튜플 리터럴일 때만 확정 가능)
                if isinstance(node.right, ast.Tuple) and "%(" not in fmt:
                    n = count_specs(fmt)
                    if n != len(node.right.elts):
                        problems.append("%s:%d  지정자 %d개 / 인자 %d개 불일치" % (
                            os.path.relpath(path, ROOT), node.lineno, n, len(node.right.elts)))
    for p in problems:
        print("FAIL " + p)
    print("포맷 문자열 %d개 검사, 문제 %d건" % (checked, len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
