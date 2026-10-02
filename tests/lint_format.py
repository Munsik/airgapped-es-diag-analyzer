#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Static checks for message keys and %-format strings.

    python3 tests/lint_format.py

Without running any rule, this walks the AST of every module and checks:
  - every T("key"), N_("key") and tr("key") used in code exists in both ko.txt and en.txt
  - every catalog key is used somewhere (dynamic prefixes and documentation keys are exempt)
  - for 'text % args' (text is a literal or a catalog key) every % is a valid conversion,
    the count of fields matches a tuple of arguments, in both languages
  - plural markers [one|many] follow a number field
A literal '70% or more' written without %% raises ValueError at run time. A rarely executed branch is
never caught by tests, so this checks them all statically.
"""
import ast
import glob
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from esdiag.i18n import parse  # noqa: E402

SPEC = re.compile(r"%(\([^)]*\))?[#0\- +]*(\*|\d+)?(\.(\*|\d+))?[diouxXeEfFgGcrsa%]")
MARKER = re.compile(r"\[[^\[\]|%]*\|[^\[\]|%]*\]")
# Keys built at run time ("sev." + id, "cat." + id ...) and keys read by tools/gen_rules_doc.py.
DYNAMIC_PREFIXES = ("sev.", "cat.", "grade.", "area.", "status.", "basis.", "doc.", "th.", "gen.", "kb.",
                    "btl.q.", "btl.g.", "btl.c.", "btl.v.", "btl.n.")


def bad_percents(fmt):
    """Positions of % that no valid conversion explains."""
    covered = set()
    for m in SPEC.finditer(fmt):
        covered.update(range(m.start(), m.end()))
    return [i for i, ch in enumerate(fmt) if ch == "%" and i not in covered]


def count_specs(fmt):
    return len([m for m in SPEC.finditer(fmt) if not m.group(0).endswith("%")])


def load(lang):
    with open(os.path.join(ROOT, "esdiag", "i18n", lang + ".txt"), encoding="utf-8") as fh:
        return parse(fh.read(), lang + ".txt")


def key_of(node):
    """Catalog key when node is T("k") / tr("k") / N_("k"), else None."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("T", "tr", "N_") \
            and len(node.args) == 1 and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        return node.args[0].value
    return None


def main():
    cats = {"ko": load("ko"), "en": load("en")}
    problems = []
    used = set()
    checked = 0
    files = sorted(glob.glob(os.path.join(ROOT, "esdiag", "**", "*.py"), recursive=True)) + \
        [os.path.join(ROOT, "analyze.py")]
    for path in files:
        rel = os.path.relpath(path, ROOT)
        tree = ast.parse(open(path, encoding="utf-8").read())
        # Module-level string constants that are used as format strings (e.g. _SCOPE) are catalog keys now.
        consts = {}
        for n in tree.body:
            if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
                k = key_of(n.value)
                if k is not None:
                    consts[n.targets[0].id] = k
        for node in ast.walk(tree):
            # A key stored in a variable or tuple (e.g. a list of messages printed later) still counts as used.
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in cats["ko"]:
                used.add(node.value)
            k = key_of(node)
            if k is not None:
                used.add(k)
                for lang, cat in cats.items():
                    if k not in cat:
                        problems.append("%s:%d  key %r missing in %s.txt" % (rel, node.lineno, k, lang))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod)):
                continue
            left = node.left
            fmts = []
            k = key_of(left)
            if k is None and isinstance(left, ast.Name) and left.id in consts:
                k = consts[left.id]
            if k is not None:
                fmts = [(lang, cat[k]) for lang, cat in cats.items() if k in cat]
            elif isinstance(left, ast.Constant) and isinstance(left.value, str):
                fmts = [("code", left.value)]
            for lang, fmt in fmts:
                checked += 1
                bad = bad_percents(fmt)
                if bad:
                    i = bad[0]
                    problems.append("%s:%d  [%s] bad %% usage: ...%s..." % (
                        rel, node.lineno, lang, fmt[max(0, i - 12):i + 8].replace("\n", " ")))
                    continue
                if isinstance(node.right, ast.Tuple) and "%(" not in fmt:
                    n = count_specs(fmt)
                    if n != len(node.right.elts):
                        problems.append("%s:%d  [%s] %d fields but %d arguments" % (
                            rel, node.lineno, lang, n, len(node.right.elts)))
    # Catalog-only checks
    for lang, cat in cats.items():
        for k, v in cat.items():
            for m in MARKER.finditer(v):
                if lang == "ko":
                    problems.append("ko.txt: %s has a plural marker" % k)
                    break
                if not SPEC.search(v[:m.start()].replace("%%", "")):
                    problems.append("en.txt: %s plural marker without a number field before it" % k)
                    break
    for k in cats["ko"]:
        if k in used or k.startswith(DYNAMIC_PREFIXES):
            continue
        problems.append("ko.txt: key %s is not used by any module" % k)
    for p in problems:
        print("FAIL " + p)
    print("%d format strings checked, %d problems" % (checked, len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
