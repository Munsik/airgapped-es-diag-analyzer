#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generator for RULES.md (English) and RULES.ko.md (Korean).

Reads the rule source with the ast module and extracts finding ids, possible severities, referenced
thresholds (with their current values), input files, reference docs and the decision logic (the rule
docstring text from the message catalog). Nobody edits the document by hand, so code and document
cannot drift apart.

    python3 tools/gen_rules_doc.py            # regenerate RULES.md and RULES.ko.md
    python3 tools/gen_rules_doc.py --lang en  # only RULES.md
    python3 tools/gen_rules_doc.py --check    # consistency check only (missing or unused thresholds, docs)
"""

import ast
import io
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

import esdoctor                                                     # noqa: E402
from esdoctor import rules as rules_pkg                             # noqa: E402
from esdoctor.basis import OFFICIAL, FACT, TOOL, CALC, basis_of     # noqa: E402
from esdoctor.basis import label as basis_label                     # noqa: E402
from esdoctor.i18n import LANGS, T, catalog, set_lang, tr           # noqa: E402
from esdoctor.model import Severity                                 # noqa: E402
from esdoctor.thresholds import DEFAULTS                            # noqa: E402

MODULES = ["cluster", "settings", "nodes", "shards", "sharding", "guidance", "hotspot", "cost", "ops", "deep",
           "runtime", "syscalls", "diff"]
OUT_FILES = {"en": "RULES.md", "ko": "RULES.ko.md"}


def _resolve(text):
    """Turn a catalog key found in the source into text of the current language."""
    return tr(text) if text else text


def _const_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _const_str(node.left)
        if left:
            return left + "*"
    return None


def _first_str(node):
    """When the title is a conditional or a format expression, use the first string constant inside it."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value.strip():
            return sub.value.strip().rstrip("*")
    return None


def _analyze_function(fn, module_obj, mod):
    key = "doc.%s.%s" % ("diff" if mod == "diff" else "rules." + mod, fn.name)
    info = {"name": fn.name, "doc_key": key, "ids": [], "titles": {},
            "sev": set(), "th": set(), "src": set(), "refs": []}
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "Finding" and n.args:
            fid = _const_str(n.args[0])
            if fid:
                if fid not in info["ids"]:
                    info["ids"].append(fid)
                if len(n.args) >= 4:
                    t = _const_str(n.args[3]) or _first_str(n.args[3])
                    if t:
                        info["titles"].setdefault(fid, t.rstrip("*"))
            for kw in n.keywords:
                if kw.arg == "source":
                    s = _const_str(kw.value)
                    if s is None and isinstance(kw.value, ast.Call) and kw.value.args:
                        s = _const_str(kw.value.args[0])       # T("catalog key")
                    if s:
                        info["src"].add(s)
                if kw.arg == "refs" and isinstance(kw.value, ast.List):
                    for el in kw.value.elts:
                        if isinstance(el, ast.Name):
                            ref = getattr(module_obj, el.id, None)
                            if ref and ref not in info["refs"]:
                                info["refs"].append(ref)
        if isinstance(n, ast.Attribute) and getattr(n.value, "id", None) == "Severity" \
                and n.attr in Severity.ORDER:
            info["sev"].add(n.attr)
        if isinstance(n, ast.Subscript):
            base = n.value
            is_t = (isinstance(base, ast.Attribute) and base.attr == "t") or \
                   (isinstance(base, ast.Name) and base.id == "t")
            key_node = n.slice
            if hasattr(ast, "Index") and isinstance(key_node, getattr(ast, "Index")):   # py<3.9
                key_node = key_node.value
            if is_t and isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                info["th"].add(key_node.value)
    return info


def collect():
    import importlib
    out = []
    for mod in MODULES:
        modname = "esdoctor.diff" if mod == "diff" else "esdoctor.rules." + mod
        module_obj = importlib.import_module(modname)
        path = module_obj.__file__
        tree = ast.parse(io.open(path, encoding="utf-8").read())
        order = [f.__name__ for f in (getattr(module_obj, "DIFF_RULES", None)
                                      or getattr(module_obj, "RULES", []))]
        fns = dict((n.name, n) for n in tree.body if isinstance(n, ast.FunctionDef))
        items = []
        for name in order:
            if name in fns:
                items.append(_analyze_function(fns[name], module_obj, mod))
        if mod == "diff":
            fdel = fns.get("_finding_delta")
            if fdel is not None:
                items.append(_analyze_function(fdel, module_obj, mod))
        out.append((mod, items))
    return out


def check(data):
    problems = []
    used = set()
    for _mod, items in data:
        for it in items:
            used |= it["th"]
            for lang in LANGS:
                if not catalog(lang).get(it["doc_key"]):
                    problems.append("missing %s text for %s (%s)" % (lang, it["name"], it["doc_key"]))
            for k in it["th"]:
                if k not in DEFAULTS:
                    problems.append("undefined threshold referenced: %s -> %s" % (it["name"], k))
    for k in DEFAULTS:
        for lang in LANGS:
            if "th." + k not in catalog(lang):
                problems.append("threshold %s has no th.%s entry in %s.txt" % (k, k, lang))
    # keys used by engine, reports and context
    for extra in ("top_n", "disk_watermark_low_default", "disk_watermark_high_default",
                  "disk_watermark_flood_default", "disk_watermark_flood_frozen_default",
                  "disk_watermark_flood_frozen_headroom_default", "node_change_noise_pct"):
        used.add(extra)
    unused = sorted(k for k in DEFAULTS if k not in used)
    return problems, unused


def render(data, unused, filename):
    L = []
    w = L.append
    sev_names = [("CRITICAL", Severity.CRITICAL), ("WARNING", Severity.WARNING),
                 ("INFO", Severity.INFO), ("OK", Severity.OK)]
    w("# " + T("gen.title") % filename)
    w("")
    w(T("gen.intro1"))
    w(T("gen.intro2"))
    w(T("gen.otherlang"))
    w("")
    w(T("gen.h.base"))
    w("")
    w(T("gen.th.item.value"))
    w("| --- | --- |")
    w(T("gen.row.version") % esdoctor.__version__)
    w(T("gen.row.baseline") % esdoctor.ES_BASELINE)
    w(T("gen.row.docs") % esdoctor.DOCS_CHECKED)
    w(T("gen.row.validated") % tr(esdoctor.VALIDATED_BUNDLE))
    w(T("gen.row.field") % tr(esdoctor.FIELD_TESTED))
    w(T("gen.row.modes") % tr(esdoctor.VALIDATED_MODES))
    w(T("gen.row.min") % esdoctor.SUPPORTED_MIN)
    w("")
    w(T("gen.h.gates"))
    w("")
    w(T("gen.th.gates"))
    w("| --- | --- | --- |")
    for ver, target, desc in esdoctor.VERSION_GATES:
        w("| %d.%d | %s | %s |" % (ver + (target, tr(desc))))
    w("")
    w(T("gen.gate.note"))
    w("")
    w(T("gen.h.basis"))
    w("")
    w(T("gen.th.basis"))
    w("| --- | --- |")
    w("| %s | %s |" % (basis_label(OFFICIAL), T("gen.basis.official")))
    w("| %s | %s |" % (basis_label(FACT), T("gen.basis.fact")))
    w("| %s | %s |" % (basis_label(TOOL), T("gen.basis.tool")))
    w("| %s | %s |" % (basis_label(CALC), T("gen.basis.calc")))
    w("")
    w(T("gen.h.inputs"))
    w("")
    w(T("gen.inputs.text"))
    w("")
    w(T("gen.h.toc"))
    w("")
    for mod, items in data:
        title = T("gen.mod." + mod)
        w(T("gen.toc.line") % (title, _anchor(title), len(items)))
    w(T("gen.toc.kb"))
    w(T("gen.toc.th"))
    w("")
    for mod, items in data:
        w("## %s" % T("gen.mod." + mod))
        w("")
        for it in items:
            doc = T(it["doc_key"])
            ids = it["ids"] or ["-"]
            head = ", ".join(i.rstrip("*") + (T("gen.sub") if i.endswith("*") else "") for i in ids)
            titles = dict((k, _resolve(v)) for k, v in it["titles"].items())
            first_title = titles.get(ids[0], "") or (doc.split(".")[0].strip()[:40] if doc else "")
            w(T("gen.rule.heading") % (head, first_title))
            w("")
            w(T("gen.th.rule"))
            w("| --- | --- |")
            w(T("gen.row.function") % (mod, it["name"]))
            if len(ids) > 1:
                w(T("gen.row.findings") % " / ".join("%s %s" % (i.rstrip("*"), titles.get(i, ""))
                                                     for i in ids))
            w(T("gen.row.basis") % " / ".join(sorted(set(basis_label(basis_of(i.rstrip("*."))) for i in ids))))
            w(T("gen.row.severity") % ", ".join(Severity.label(s) for n, s in sev_names if n in it["sev"]))
            if it["th"]:
                w(T("gen.row.thresholds") % "<br>".join(
                    "`%s` = %s%s" % (k, _fmt_val(DEFAULTS.get(k)),
                                     (T("gen.th.suffix") % T("th." + k)) if ("th." + k) in catalog(esdoctor_lang()) else "")
                    for k in sorted(it["th"])))
            req = rules_pkg.REQUIRES.get(it["name"])
            if req:
                w(T("gen.row.requires") % T("gen.and").join(
                    "(" + T("gen.or").join(g) + ")" for g in req))
            if it["src"]:
                w(T("gen.row.sources") % " / ".join(sorted(_resolve(x) for x in it["src"])))
            if it["refs"]:
                w(T("gen.row.refs") % "<br>".join("[%s](%s)" % (tr(r[0]), r[1]) for r in it["refs"]))
            w("")
            w(T("gen.logic"))
            w("")
            w(doc.replace("\n    ", "\n").strip())
            w("")
    from esdoctor import settings_kb as kb
    w(T("gen.h.kb"))
    w("")
    w(T("gen.kb.intro"))
    w("")
    w(T("gen.kb.b1"))
    w(T("gen.kb.b2"))
    w(T("gen.kb.b3"))
    w(T("gen.kb.b4") % esdoctor.ES_BASELINE)
    w(T("gen.kb.b5"))
    w("")
    w(T("gen.th.kb"))
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
        spec = kb.lookup(key)
        t, u = kb.DOCS[spec["doc"]]
        w("| `%s` | %s | %s | %s | %s | %s | %s | [%s](%s) |" % (
            key, (spec["default"] or T("gen.none")) + (T("gen.kb.src") if spec.get("basis") == "source" else ""),
            spec["kind"], spec["scope"], spec["meaning"].replace("|", "/"),
            _eff(spec), _risk(spec), tr(t), u))
    for prefix, spec in kb.PREFIX_RULES:
        spec = kb._localized(spec)
        t, u = kb.DOCS[spec["doc"]]
        w("| `%s*` | %s | %s | %s | %s | %s | %s | [%s](%s) |" % (
            prefix, spec["default"] or T("gen.none"), spec["kind"], spec["scope"], spec["meaning"],
            _eff(spec), _risk(spec), tr(t), u))
    w("")
    w(T("gen.h.th"))
    w("")
    w(T("gen.th.intro"))
    w("")
    w(T("gen.th.all"))
    w("| --- | --- | --- |")
    for k in DEFAULTS:
        w("| `%s` | %s | %s |" % (k, _fmt_val(DEFAULTS[k]), catalog(esdoctor_lang()).get("th." + k, "")))
    w("")
    if unused:
        w(T("gen.unused") % ", ".join("`%s`" % u for u in unused))
        w("")
    return "\n".join(L)


def esdoctor_lang():
    from esdoctor.i18n import get_lang
    return get_lang()


def _fmt_val(v):
    if isinstance(v, int) and v >= 1024 ** 2 and v % (1024 ** 2) == 0:
        for unit, div in (("TiB", 1024 ** 4), ("GiB", 1024 ** 3), ("MiB", 1024 ** 2)):
            if v % div == 0:
                return "%d%s" % (v // div, unit)
    if isinstance(v, int):
        return "{:,}".format(v)
    return str(v)


def _anchor(title):
    """GitHub-style heading anchor (lowercase, punctuation dropped, spaces to hyphens)."""
    a = title.lower()
    a = re.sub("[^\\w\\s\\-가-힣]", "", a)
    return re.sub(r"\s+", "-", a.strip())


def main():
    langs = list(LANGS)
    if "--lang" in sys.argv:
        langs = [sys.argv[sys.argv.index("--lang") + 1]]
    set_lang("en")
    data = collect()
    problems, unused = check(data)
    for p in problems:
        print("problem: " + p)
    if "--check" in sys.argv:
        print("%d rules checked, %d problems, %d unused thresholds"
              % (sum(len(x[1]) for x in data), len(problems), len(unused)))
        if unused:
            print("unused: " + ", ".join(unused))
        return 1 if problems else 0
    for lang in langs:
        set_lang(lang)
        name = OUT_FILES[lang]
        out = os.path.normpath(os.path.join(ROOT, name))
        with io.open(out, "w", encoding="utf-8") as fh:
            fh.write(render(data, unused, name))
        print("wrote %s (%d rules)" % (out, sum(len(x[1]) for x in data)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
