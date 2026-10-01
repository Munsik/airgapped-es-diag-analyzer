#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Catalog checks for esdiag/i18n/ko.txt and en.txt.

    python3 tests/i18n_check.py                      # check the full catalogs
    python3 tests/i18n_check.py --chunk en_part.txt  # check a partial English file against ko.txt

Checks:
  - same keys in ko and en
  - same %-format fields in the same order (%s, %d, %.1f, %(name)s, %%)
  - same HTML tags (by tag name and count)
  - leading and trailing spaces kept (fragments are glued together in code)
  - same number of line breaks
  - no Hangul in en, no em dash or en dash in en, no phrases listed in docs/STYLE.md
"""
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from esdiag.i18n import parse  # noqa: E402

HANGUL = re.compile("[가-힣ㄱ-ㆎ]")
DASHES = ("—", "–")
BANNED_EN = ["it's worth noting", "it is worth noting", "crucial", "robust", "seamless", "leverage", "delve",
             "comprehensive", "furthermore", "moreover", "utilize", "in order to", "plays a key role",
             "ensure that", "streamline", "holistic"]
BANNED_KO = ["하는 것이 중요", "살펴보겠", "다양한", "효과적으로", "를 통해", "을 통해"]
TAG = re.compile(r"</?(b|i|u|em|strong|code|pre|br|span|a|small|div|p|ul|ol|li|table|tr|td|th|h[1-6])\b", re.I)
FIELD = re.compile(r"%(?:\([^)]*\))?[-#0 +]*(?:\d+|\*)?(?:\.\d+)?[sdfrxXeEgGci%]")


def load(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    cat = parse(text, os.path.basename(path))
    order = []
    for line in text.split("\n"):
        if line.strip() and not line.lstrip().startswith("#"):
            order.append(line.partition(" = ")[0].strip())
    return cat, order


def fields(s):
    """Format fields in order. %% is ignored; named fields are compared as a sorted list."""
    out = [re.sub(r"^(%(?:\([^)]*\))?)[-#0 +]*(?:\d+|\*)?", r"\1", f) for f in FIELD.findall(s) if f != "%%"]
    if any(f.startswith("%(") for f in out):
        return sorted(out)
    return out


def check(ko, en, keys=None):
    errs = []
    keys = list(keys if keys is not None else ko.keys())
    for k in sorted(set(en) - set(ko)):
        errs.append("%s: key not in ko.txt" % k)
    for k in keys:
        if k not in en:
            errs.append("%s: missing in en" % k)
            continue
        if k not in ko:
            continue
        a, b = ko[k], en[k]
        if fields(a) != fields(b):
            errs.append("%s: format fields differ ko=%s en=%s" % (k, fields(a), fields(b)))
        if Counter(t.lower() for t in TAG.findall(a)) != Counter(t.lower() for t in TAG.findall(b)):
            errs.append("%s: HTML tags differ" % k)
        for side, x, y in (("leading", a[:1].isspace(), b[:1].isspace()), ("trailing", a[-1:].isspace(), b[-1:].isspace())):
            if x != y:
                errs.append("%s: %s space differs" % (k, side))
        if a.count("\n") != b.count("\n"):
            errs.append("%s: line break count differs" % k)
        if HANGUL.search(b):
            errs.append("%s: Hangul in en" % k)
    for name, cat, banned in (("ko", dict((k, ko[k]) for k in keys if k in ko), BANNED_KO),
                              ("en", dict((k, en[k]) for k in keys if k in en), BANNED_EN)):
        for k, v in cat.items():
            if name == "en" and any(d in v for d in DASHES):
                errs.append("%s %s: em/en dash" % (name, k))
            low = v.lower()
            for w in banned:
                if w in low:
                    errs.append("%s %s: avoid '%s'" % (name, k, w))
    return errs


def main():
    ko, _ = load(os.path.join(ROOT, "esdiag", "i18n", "ko.txt"))
    if len(sys.argv) == 3 and sys.argv[1] == "--chunk":
        en, order = load(sys.argv[2])
        errs = check(ko, en, keys=order)
    else:
        en, _ = load(os.path.join(ROOT, "esdiag", "i18n", "en.txt"))
        errs = check(ko, en)
    for e in errs:
        print(e)
    print("%d problems" % len(errs))
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
