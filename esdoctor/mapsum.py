# -*- coding: utf-8 -*-
"""Index mapping summary. mapping.json can reach hundreds of MB, so only what the findings need is kept as it is read."""

from .util import items


def count_fields(props):
    """Counts fields the way total_fields.limit does: field and object mappings and multi-fields (and their own multi-fields), one each.

    Returns: (field count, nested count, fielddata-enabled text fields, [(dense_vector field, {dims, element_type, index_options.type})])
    """
    total, nested = 0, 0
    fielddata, vectors = [], []
    stack = [("", props)]
    while stack:
        path, pr = stack.pop()
        for name, f in items(pr):
            if not isinstance(f, dict):
                continue
            full = path + "." + name if path else name
            total += 1
            t = f.get("type")
            if t == "nested":
                nested += 1
            if t == "text" and str(f.get("fielddata")).lower() == "true":
                fielddata.append(full)
            if t == "dense_vector":
                io = f.get("index_options") if isinstance(f.get("index_options"), dict) else {}
                vectors.append((full, {"dims": f.get("dims"), "element_type": f.get("element_type"), "index": f.get("index"),
                                       "index_options": {"type": io.get("type")} if io.get("type") else {}}))
            subs = items(f.get("fields"))
            total += len(subs)
            deeper = [sf for _s, sf in subs if isinstance(sf, dict)]
            while deeper:                       # multi-fields of multi-fields count too
                nxt = []
                for sf in deeper:
                    more = [x for _k, x in items(sf.get("fields")) if isinstance(x, dict)]
                    total += len(more)
                    nxt.extend(more)
                deeper = nxt
            for sub, sf in subs:
                if isinstance(sf, dict) and sf.get("type") == "text" and str(sf.get("fielddata")).lower() == "true":
                    fielddata.append(full + "." + sub)
            if isinstance(f.get("properties"), dict):
                stack.append((full, f["properties"]))
    return total, nested, fielddata, vectors


def summarize(pairs):
    """Takes an (index, body) iterator and builds {index: {total, nested, fielddata, vectors, runtime, source_disabled}}."""
    out = {}
    for name, body in pairs:
        m = body.get("mappings") if isinstance(body, dict) else None
        if not isinstance(m, dict):
            continue
        total, nested, fd, vec = count_fields(m.get("properties"))
        rt = len(items(m.get("runtime")))
        src = m.get("_source") if isinstance(m.get("_source"), dict) else {}
        mode = str(src.get("mode") or "").lower()
        ts = (m.get("properties") or {}).get("@timestamp") if isinstance(m.get("properties"), dict) else None
        out[name] = {"total": total + rt, "nested": nested, "fielddata": fd, "vectors": vec, "runtime": rt,
                     "source_disabled": str(src.get("enabled")).lower() == "false" or mode == "disabled",
                     "source_mode": mode,
                     "timestamp": isinstance(ts, dict) and ts.get("type") in ("date", "date_nanos"),
                     "ts_index": isinstance(ts, dict) and str(ts.get("index", True)).lower() != "false",
                     "ts_dv": isinstance(ts, dict) and str(ts.get("doc_values", True)).lower() != "false"}
    return out
