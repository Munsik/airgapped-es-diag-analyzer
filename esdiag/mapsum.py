# -*- coding: utf-8 -*-
"""Index mapping summary. mapping.json can reach hundreds of MB, so only what the findings need is kept as it is read."""

from .util import items


def count_fields(props):
    """Counts fields the way total_fields.limit does: field and object mappings and multi-fields, one each.

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
                vectors.append((full, {"dims": f.get("dims"), "element_type": f.get("element_type"),
                                       "index_options": {"type": io.get("type")} if io.get("type") else {}}))
            subs = items(f.get("fields"))
            total += len(subs)
            for sub, sf in subs:
                if isinstance(sf, dict) and sf.get("type") == "text" and str(sf.get("fielddata")).lower() == "true":
                    fielddata.append(full + "." + sub)
            if isinstance(f.get("properties"), dict):
                stack.append((full, f["properties"]))
    return total, nested, fielddata, vectors


def summarize(pairs):
    """Takes an (index, body) iterator and builds {index: {total, nested, fielddata, vectors, runtime}}."""
    out = {}
    for name, body in pairs:
        m = body.get("mappings") if isinstance(body, dict) else None
        if not isinstance(m, dict):
            continue
        total, nested, fd, vec = count_fields(m.get("properties"))
        rt = len(items(m.get("runtime")))
        out[name] = {"total": total + rt, "nested": nested, "fielddata": fd, "vectors": vec, "runtime": rt}
    return out
