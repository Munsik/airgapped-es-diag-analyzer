#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RULES.md 생성기.

룰 소스 코드를 AST 로 읽어 판정 ID · 가능 심각도 · 참조 임계값(현재 값) · 입력 파일 · 참고 문서 ·
판정 로직(docstring)을 추출한다. 문서를 사람이 따로 관리하지 않으므로 코드와 문서가 어긋나지 않는다.

    python3 tools/gen_rules_doc.py            # RULES.md 재생성
    python3 tools/gen_rules_doc.py --check    # 정합성 검사만(임계값 누락·미사용, docstring 누락)
"""

import ast
import io
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

import esdiag                                                     # noqa: E402
from esdiag import rules as rules_pkg                             # noqa: E402
from esdiag.basis import OFFICIAL, FACT, TOOL, CALC, basis_of     # noqa: E402
from esdiag.thresholds import DEFAULTS                            # noqa: E402

MODULE_TITLES = [
    ("cluster", "클러스터"),
    ("settings", "설정 변경 (기본값 대비)"),
    ("nodes", "노드 (JVM · OS · 디스크 · 스레드풀)"),
    ("shards", "샤드 · 인덱스"),
    ("sharding", "과다 샤딩 · 소형 샤드"),
    ("guidance", "공식 가이드 기준 (설정 · 샤드 · 성능 · 디스크 · 벡터)"),
    ("hotspot", "핫스팟 · 밸런싱"),
    ("ops", "운영 · 보안"),
    ("deep", "매핑 · ILM 정책 · 클러스터 조정 · 세부 통계"),
    ("runtime", "런타임 (hot threads · 로그)"),
    ("diff", "변화 추세 (--baseline 비교 모드)"),
]
SEV_KO = {"CRITICAL": "치명", "WARNING": "주의", "INFO": "참고", "OK": "정상"}


def _threshold_comments():
    """thresholds.py 의 '# [공식] ...' / '# [도구] ...' 주석을 키별로 수집."""
    out = {}
    path = os.path.join(ROOT, "esdiag", "thresholds.py")
    for ln in io.open(path, encoding="utf-8"):
        m = re.match(r'\s*"([a-z0-9_]+)":\s*[^#]*#\s*(.*)$', ln)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def _const_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _const_str(node.left)
        if left:
            return left + "*"
    return None


def _analyze_function(fn, module_obj):
    info = {"name": fn.name, "doc": ast.get_docstring(fn) or "", "ids": [], "titles": {},
            "sev": set(), "th": set(), "src": set(), "refs": []}
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "Finding" and n.args:
            fid = _const_str(n.args[0])
            if fid:
                if fid not in info["ids"]:
                    info["ids"].append(fid)
                if len(n.args) >= 4:
                    t = _const_str(n.args[3])
                    if t:
                        info["titles"].setdefault(fid, t.rstrip("*"))
            for kw in n.keywords:
                if kw.arg == "source":
                    s = _const_str(kw.value)
                    if s:
                        info["src"].add(s)
                if kw.arg == "refs" and isinstance(kw.value, ast.List):
                    for el in kw.value.elts:
                        if isinstance(el, ast.Name):
                            ref = getattr(module_obj, el.id, None)
                            if ref and ref not in info["refs"]:
                                info["refs"].append(ref)
        if isinstance(n, ast.Attribute) and getattr(n.value, "id", None) == "Severity" \
                and n.attr in SEV_KO:
            info["sev"].add(n.attr)
        if isinstance(n, ast.Subscript):
            base = n.value
            is_t = (isinstance(base, ast.Attribute) and base.attr == "t") or \
                   (isinstance(base, ast.Name) and base.id == "t")
            key = n.slice
            if hasattr(ast, "Index") and isinstance(key, getattr(ast, "Index")):   # py<3.9
                key = key.value
            if is_t and isinstance(key, ast.Constant) and isinstance(key.value, str):
                info["th"].add(key.value)
    return info


def collect():
    import importlib
    out = []
    for mod, title in MODULE_TITLES:
        modname = "esdiag.diff" if mod == "diff" else "esdiag.rules." + mod
        module_obj = importlib.import_module(modname)
        path = module_obj.__file__
        tree = ast.parse(io.open(path, encoding="utf-8").read())
        order = [f.__name__ for f in (getattr(module_obj, "DIFF_RULES", None)
                                      or getattr(module_obj, "RULES", []))]
        fns = dict((n.name, n) for n in tree.body if isinstance(n, ast.FunctionDef))
        items = []
        for name in order:
            if name in fns:
                items.append(_analyze_function(fns[name], module_obj))
        if mod == "diff":
            fdel = fns.get("_finding_delta")
            if fdel is not None:
                x = _analyze_function(fdel, module_obj)
                x["doc"] = ("이전 번들과 현재 번들의 치명·주의 판정 ID 를 비교해 신규 발생 / 악화 / 해소 목록을 만든다. "
                            "다른 판정의 요약이므로 항상 참고(점수·건수 이중 계산 방지).")
                items.append(x)
        out.append((mod, title, items))
    return out


def check(data):
    problems = []
    used = set()
    for _mod, _title, items in data:
        for it in items:
            used |= it["th"]
            if not it["doc"]:
                problems.append("docstring 누락: %s" % it["name"])
            for k in it["th"]:
                if k not in DEFAULTS:
                    problems.append("정의되지 않은 임계값 참조: %s → %s" % (it["name"], k))
    # engine/report/context 에서 쓰는 키
    for extra in ("top_n", "disk_watermark_low_default", "disk_watermark_high_default",
                  "disk_watermark_flood_default", "disk_watermark_flood_frozen_default",
                  "disk_watermark_flood_frozen_headroom_default"):
        used.add(extra)
    unused = sorted(k for k in DEFAULTS if k not in used)
    return problems, unused


def render(data, unused):
    tc = _threshold_comments()
    L = []
    w = L.append
    w("# 판정 룰 명세 (RULES.md)")
    w("")
    w("> 이 문서는 `tools/gen_rules_doc.py` 가 소스 코드에서 자동 생성합니다. 직접 수정하지 마십시오.")
    w("> 임계값은 `esdiag/thresholds.py` 의 현재 기본값이며, `--thresholds` 로 재정의할 수 있습니다.")
    w("")
    w("## 기준점")
    w("")
    w("| 항목 | 값 |")
    w("| --- | --- |")
    w("| 도구 버전 | esdiag %s |" % esdiag.__version__)
    w("| 판정 기준 Elasticsearch 버전 | %d.%d |" % esdiag.ES_BASELINE)
    w("| 공식 문서 대조 시점 | %s |" % esdiag.DOCS_CHECKED)
    w("| 실번들 검증 | %s |" % esdiag.VALIDATED_BUNDLE)
    w("| 현장 실행 확인 | %s |" % esdiag.FIELD_TESTED)
    w("| 검증된 수집 모드 | %s |" % esdiag.VALIDATED_MODES)
    w("| 지원 최소 버전 | %d.%d (미만은 해당 버전에 존재하는 API 범위에서만 동작) |" % esdiag.SUPPORTED_MIN)
    w("")
    w("### 버전별 판정 분기")
    w("")
    w("| 기준 버전 | 대상 | 내용 |")
    w("| --- | --- | --- |")
    for ver, target, desc in esdiag.VERSION_GATES:
        w("| %d.%d | %s | %s |" % (ver + (target, desc)))
    w("")
    w("분석 대상이 기준 버전보다 새로우면 리포트에 `VER-001` 이 표시됩니다.")
    w("")
    w("## 판정 근거 구분")
    w("")
    w("| 구분 | 의미 |")
    w("| --- | --- |")
    w("| %s | 판정 기준 자체가 Elastic 공식 문서에 명시된 항목 |" % OFFICIAL)
    w("| %s | Elasticsearch 가 보고한 상태·오류·설정값을 그대로 전달(임계값 없음) |" % FACT)
    w("| %s | 공식 수치 기준이 없어 이 도구의 임계값으로 판단한 항목 |" % TOOL)
    w("| %s | 두 번들 간 증가분·증가율·선형 외삽 |" % CALC)
    w("")
    w("## 입력 파일 규칙")
    w("")
    w("각 룰은 필요한 입력 파일을 선언합니다(`esdiag/rules/__init__.py` 의 `REQUIRES`). "
      "파일이 번들에 없으면 해당 룰을 실행하지 않고 리포트의 '입력 미수집으로 판정하지 않은 항목' 에 기록합니다. "
      "'파일 없음(미수집)' 과 '설정 없음(미설정)' 을 구분하기 위함입니다.")
    w("")
    w("## 목차")
    w("")
    for mod, title, items in data:
        w("- [%s](#%s) — %d개 룰" % (title, _anchor(title), len(items)))
    w("- [설정 지식 베이스](#설정-지식-베이스)")
    w("- [임계값 전체 목록](#임계값-전체-목록)")
    w("")
    for mod, title, items in data:
        w("## %s" % title)
        w("")
        for it in items:
            ids = it["ids"] or ["-"]
            head = ", ".join(i.rstrip("*") + ("(하위 항목)" if i.endswith("*") else "") for i in ids)
            first_title = it["titles"].get(ids[0], "")
            w("### %s — %s" % (head, first_title))
            w("")
            w("| 항목 | 내용 |")
            w("| --- | --- |")
            w("| 함수 | `%s.%s` |" % (mod, it["name"]))
            if len(ids) > 1:
                w("| 판정 항목 | %s |" % " / ".join("%s %s" % (i.rstrip("*"), it["titles"].get(i, ""))
                                                  for i in ids))
            w("| 근거 구분 | %s |" % " / ".join(sorted(set(basis_of(i.rstrip("*.")) for i in ids))))
            order = ["CRITICAL", "WARNING", "INFO", "OK"]
            w("| 가능 심각도 | %s |" % ", ".join(SEV_KO[s] for s in order if s in it["sev"]))
            if it["th"]:
                w("| 임계값 | %s |" % "<br>".join(
                    "`%s` = %s%s" % (k, _fmt_val(DEFAULTS.get(k)),
                                     (" — " + tc[k]) if k in tc else "") for k in sorted(it["th"])))
            req = rules_pkg.REQUIRES.get(it["name"])
            if req:
                w("| 필요 입력 | %s |" % " 그리고 ".join("(" + " 또는 ".join(g) + ")" for g in req))
            if it["src"]:
                w("| 근거 파일 | %s |" % " / ".join(sorted(it["src"])))
            if it["refs"]:
                w("| 참고 문서 | %s |" % "<br>".join("[%s](%s)" % r for r in it["refs"]))
            w("")
            w("**판정 로직**")
            w("")
            w(it["doc"].replace("\n    ", "\n").strip())
            w("")
    from esdiag import settings_kb as kb
    w("## 설정 지식 베이스")
    w("")
    w("SET-001~006 이 사용하는 설정별 공식 기본값·종류·의미·변경 영향입니다(`esdiag/settings_kb.py`).")
    w("")
    w("- 적용 우선순위(공식): transient > persistent > elasticsearch.yml > 기본값")
    w("- dynamic 은 `PUT _cluster/settings`(또는 인덱스 설정 API)로 바꿀 수 있고, `null` 로 지정하면 기본값으로 돌아갑니다.")
    w("- static 은 모든 대상 노드의 elasticsearch.yml 에서만 바꿀 수 있고 재기동이 필요합니다. 인덱스 static 설정은 닫힌 인덱스에서만 바꿀 수 있습니다.")
    w("- 번들의 `cluster_settings_defaults` 는 yml 값이 반영된 값이고, API 로 명시한 키는 기본값을 보고하지 않습니다. "
      "그래서 '원래 기본값' 은 이 표(공식 문서 기준 %d.%d)를 사용합니다." % esdiag.ES_BASELINE)
    w("- ↑ 는 기본값보다 크게, ↓ 는 작게 바꿨을 때의 영향입니다. 이 표에 없는 설정은 리포트에 '설명 미등록' 으로 값만 표기합니다.")
    w("")
    w("| 설정 | 기본값 | 종류 | 범위 | 의미 | 변경 영향 | 위험도(↑/↓) | 문서 |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- |")
    def _eff(spec):
        parts = []
        if spec.get("up"):
            parts.append("↑ " + spec["up"])
        if spec.get("down"):
            parts.append("↓ " + spec["down"])
        if spec.get("change"):
            parts.append(spec["change"])
        return "<br>".join(parts).replace("|", "/")
    def _risk(spec):
        r = spec.get("risk")
        if isinstance(r, tuple):
            return "%s / %s" % (r[0] or "-", r[1] or "-")
        return r or "-"
    for key in sorted(kb.KB):
        spec = kb.KB[key]
        t, u = kb.DOCS[spec["doc"]]
        w("| `%s` | %s | %s | %s | %s | %s | %s | [%s](%s) |" % (
            key, spec["default"] or "(없음)", spec["kind"], spec["scope"], spec["meaning"].replace("|", "/"),
            _eff(spec), _risk(spec), t, u))
    for prefix, spec in kb.PREFIX_RULES:
        t, u = kb.DOCS[spec["doc"]]
        w("| `%s*` | %s | %s | %s | %s | %s | %s | [%s](%s) |" % (
            prefix, spec["default"] or "(없음)", spec["kind"], spec["scope"], spec["meaning"],
            _eff(spec), _risk(spec), t, u))
    w("")
    w("## 임계값 전체 목록")
    w("")
    w("`[공식]` 은 공식 문서의 수치, `[도구]` 는 이 도구가 정한 값입니다. 주석이 없는 항목은 도구 판단 값입니다.")
    w("")
    w("| 키 | 기본값 | 설명 |")
    w("| --- | --- | --- |")
    for k in DEFAULTS:
        w("| `%s` | %s | %s |" % (k, _fmt_val(DEFAULTS[k]), tc.get(k, "")))
    w("")
    if unused:
        w("미사용 임계값(향후 확장용으로 남겨 둔 키): %s" % ", ".join("`%s`" % u for u in unused))
        w("")
    return "\n".join(L)


def _fmt_val(v):
    if isinstance(v, int) and v >= 1024 ** 2 and v % (1024 ** 2) == 0:
        for unit, div in (("TiB", 1024 ** 4), ("GiB", 1024 ** 3), ("MiB", 1024 ** 2)):
            if v % div == 0:
                return "%d%s" % (v // div, unit)
    if isinstance(v, int):
        return "{:,}".format(v)
    return str(v)


def _anchor(title):
    a = title.lower()
    a = re.sub(r"[^\w\s\-가-힣]", "", a)
    return re.sub(r"\s+", "-", a.strip())


def main():
    data = collect()
    problems, unused = check(data)
    for p in problems:
        print("문제: " + p)
    if "--check" in sys.argv:
        print("룰 %d개 검사, 문제 %d건, 미사용 임계값 %d개"
              % (sum(len(x[2]) for x in data), len(problems), len(unused)))
        if unused:
            print("미사용: " + ", ".join(unused))
        return 1 if problems else 0
    out = os.path.normpath(os.path.join(ROOT, "RULES.md"))
    with io.open(out, "w", encoding="utf-8") as fh:
        fh.write(render(data, unused))
    print("생성: %s (룰 %d개)" % (out, sum(len(x[2]) for x in data)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
