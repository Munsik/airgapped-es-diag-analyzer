#!/usr/bin/env python3
"""Temporary debug helper: why a node counts as holding write-target shards.

    python3 tools/why_writer.py <bundle> <node> [<node> ...]
"""
import collections
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from esdiag.context import Context  # noqa: E402
from esdiag.loader import Bundle  # noqa: E402
from esdiag.thresholds import merge  # noqa: E402
from esdiag.util import dicts, num  # noqa: E402

ctx = Context(Bundle(sys.argv[1]), merge({}))
ds_write = set()
for ds in dicts(ctx.data_streams):
    idx = dicts(ds.get("indices"))
    if idx:
        ds_write.add(idx[-1].get("index_name"))
alias_write = ctx.write_targets() - ds_write
indexing_now = set(n for n, st in ctx.indices_stats.items() if num(st, "total", "indexing", "index_current") > 0)

for node in sys.argv[2:]:
    why = collections.Counter()
    sample = collections.defaultdict(list)
    for s in ctx.shards:
        if s.get("node") != node:
            continue
        i = s.get("index")
        for label, group in (("data stream write index", ds_write), ("alias write target", alias_write),
                             ("index_current > 0", indexing_now)):
            if i in group:
                why[label] += 1
                if len(sample[label]) < 3:
                    sample[label].append(i)
    print(node, dict(why))
    for label, names in sample.items():
        print("   %s: %s" % (label, ", ".join(names)))
