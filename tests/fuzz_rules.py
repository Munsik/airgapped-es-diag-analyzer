#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rule robustness fuzzing. Randomly replaces bundle JSON values with null, strings or empty containers,
runs every rule and collects the exceptions.

    python3 tests/fuzz_rules.py bundle.zip [runs] [--harsh]

Checks that rules do not crash when field formats differ between versions and deployment types.
"""
import collections
import copy
import os
import random
import sys
import traceback
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from esdiag.loader import Bundle
from esdiag.context import Context
from esdiag.thresholds import merge
from esdiag.rules import all_rules
from esdiag import diff as diff_mod
from esdiag.i18n import set_lang

# Only exceptions are collected, so the output language does not matter.
set_lang("en")

MUTANTS = [None, "", "abc", "-1", 0, -1, [], {}, "1.5gb", True]


def mutate_real(obj, rate, rnd):
    """Variations that can really occur across versions and collection conditions: missing key, null, number as string."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            r = rnd.random()
            if r < rate / 3:
                continue                                   # missing key
            if r < rate * 2 / 3:
                out[k] = None                              # null
            elif r < rate and isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = str(v)                            # number to string
            else:
                out[k] = mutate_real(v, rate, rnd)
        return out
    if isinstance(obj, list):
        return [mutate_real(v, rate, rnd) for v in obj]
    return obj


def mutate(obj, rate, rnd):
    if isinstance(obj, dict):
        return {k: (rnd.choice(MUTANTS) if rnd.random() < rate else mutate(v, rate, rnd)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [(rnd.choice(MUTANTS) if rnd.random() < rate else mutate(v, rate, rnd)) for v in obj]
    return obj


class FuzzBundle(Bundle):
    def __init__(self, path, seed, rate, real=False):
        Bundle.__init__(self, path)
        self._real = real
        self._rnd = random.Random(seed)
        self._rate = rate
        self._mut = {}

    def json(self, name, default=None):
        key = name
        if key not in self._mut:
            obj = Bundle.json(self, name, default)
            fn = mutate_real if self._real else mutate
            self._mut[key] = fn(copy.deepcopy(obj), self._rate, self._rnd) if obj is not None else obj
        return self._mut[key]


def main():
    path = sys.argv[1]
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    real = "--harsh" not in sys.argv
    print("mode: %s" % ("realistic mutations (missing, null, numeric strings), expect 0 failures" if real else
                        "harsh mutations (arbitrary types), the engine isolates failures per rule"))
    fails = collections.OrderedDict()
    for seed in range(runs):
        rate = (0.02, 0.1, 0.3)[seed % 3]
        try:
            ctx = Context(FuzzBundle(path, seed, rate, real), merge({}))
        except Exception:
            fails.setdefault("Context", traceback.format_exc(limit=2).strip().splitlines()[-1])
            continue
        for mod, fn in all_rules():
            try:
                fn(ctx)
            except Exception:
                tb = traceback.extract_tb(sys.exc_info()[2])[-1]
                key = "%s.%s @%s:%d" % (mod, fn.__name__, os.path.basename(tb.filename), tb.lineno)
                fails.setdefault(key, traceback.format_exc().strip().splitlines()[-1])
        try:
            base = Context(FuzzBundle(path, seed + 10000, rate, real), merge({}))
            diff_mod.compare(base, ctx, ctx.t, [], [])
        except Exception:
            tb = traceback.extract_tb(sys.exc_info()[2])[-1]
            fails.setdefault("diff @%s:%d" % (os.path.basename(tb.filename), tb.lineno),
                             traceback.format_exc().strip().splitlines()[-1])
    for k, v in fails.items():
        print("FAIL %s  %s" % (k, v))
    print("%d runs, %d failure points" % (runs, len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
