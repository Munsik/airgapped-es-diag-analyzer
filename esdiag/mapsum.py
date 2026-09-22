# -*- coding: utf-8 -*-
"""인덱스 매핑 요약. mapping.json 은 수백 MB 가 될 수 있어, 읽는 즉시 판정에 필요한 요약만 남긴다."""

from .util import items


def count_fields(props):
    """공식 total_fields.limit 산정: 필드·object 매핑, multi-field 모두 1개씩.

    반환: (필드 수, nested 수, fielddata 활성 text 필드 목록, [(dense_vector 필드, {dims, element_type, index_options.type})])
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
    """(index, body) 반복자를 받아 {index: {total, nested, fielddata, vectors, runtime}} 요약을 만든다."""
    out = {}
    for name, body in pairs:
        m = body.get("mappings") if isinstance(body, dict) else None
        if not isinstance(m, dict):
            continue
        total, nested, fd, vec = count_fields(m.get("properties"))
        rt = len(items(m.get("runtime")))
        out[name] = {"total": total + rt, "nested": nested, "fielddata": fd, "vectors": vec, "runtime": rt}
    return out
