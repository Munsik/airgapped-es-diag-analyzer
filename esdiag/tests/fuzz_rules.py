#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""룰 견고성 퍼징. 번들 JSON 값을 무작위로 null·문자열·빈 컨테이너로 바꿔 모든 룰을 실행하고 예외를 모은다.

    python3 tests/fuzz_rules.py 번들.zip [반복수]

버전·배포 형태가 다른 번들에서 필드 형식이 달라도 룰이 죽지 않는지 확인하는 용도.
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

MUTANTS = [None, "", "abc", "-1", 0, -1, [], {}, "1.5gb", True]


def mutate_real(obj, rate, rnd):
    """버전·수집 조건 차이로 실제 생길 수 있는 변형: 키 누락, null, 숫자가 문자열로 옴."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            r = rnd.random()
            if r < rate / 3:
                continue                                   # 키 누락
            if r < rate * 2 / 3:
                out[k] = None                              # null
            elif r < rate and isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = str(v)                            # 숫자 → 문자열
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
    print("모드: %s" % ("현실적 변형(누락·null·문자열 숫자) — 실패 0 이어야 함" if real else
                        "극단적 변형(임의 타입) — 실패해도 엔진이 룰 단위로 격리"))
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
    print("%d회 실행, 실패 지점 %d곳" % (runs, len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
