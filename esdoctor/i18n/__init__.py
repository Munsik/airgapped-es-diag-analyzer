# -*- coding: utf-8 -*-
"""Message catalogs and language selection.

All user-facing text lives in esdoctor/i18n/<lang>.txt, one entry per line:

    key = "text"

Escapes inside the quotes: \\\\ \\" \\n \\t. Placeholders (%s, %d, %.1f, %%, %(name)s) must match
between ko.txt and en.txt, in the same order. Call sites keep the % operator:

    T("cluster.r_cluster_status.01") % (value,)

Language is process-wide state set once per output run with set_lang(). Rules and renderers
never cache translated text across a language switch.

Catalogs are read with pkgutil.get_data so they also work from a zipapp (esdoctor.pyz) and from a
PyInstaller bundle.
"""

import os
import re
import pkgutil

LANGS = ("ko", "en")
FALLBACK = "ko"

_lang = FALLBACK
_cache = {}


def _unesc(s):
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            nxt = s[i + 1]
            out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(nxt, "\\" + nxt))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def esc(s):
    """Inverse of _unesc, for writing catalog lines."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


def parse(text, name="catalog"):
    cat = {}
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, val = line.partition(" = ")
        val = val.strip()
        if not sep or len(val) < 2 or val[0] != '"' or val[-1] != '"':
            raise ValueError("%s:%d: bad catalog line: %s" % (name, n, line[:80]))
        cat[key.strip()] = _unesc(val[1:-1])
    return cat


def _read(lang):
    data = None
    try:
        data = pkgutil.get_data(__name__, lang + ".txt")
    except Exception:
        data = None
    if data is None:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), lang + ".txt"), "rb") as fh:
            data = fh.read()
    return data.decode("utf-8")


def catalog(lang):
    if lang not in _cache:
        _cache[lang] = parse(_read(lang), lang + ".txt")
    return _cache[lang]


def detect_lang():
    """ESDOCTOR_LANG, then the locale: ko when it starts with ko, otherwise en."""
    env = os.environ.get("ESDOCTOR_LANG", "").strip().lower()
    if env in LANGS:
        return env
    loc = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    if not loc:
        try:
            import locale
            loc = locale.getdefaultlocale()[0] or ""
        except Exception:
            loc = ""
    return "ko" if loc.lower().startswith("ko") else "en"


def set_lang(lang):
    global _lang
    _lang = lang if lang in LANGS else FALLBACK
    return _lang


def get_lang():
    return _lang


# Plural markers. A catalog text may contain [singular|plural] right after a number field:
#     "%d [node has|nodes have] left the cluster"
# The marker follows the most recent %-field before it and picks the singular form when that
# argument equals 1. Korean texts do not use markers.
_TOKEN = re.compile(r"%(?:\((?P<name>[^)]*)\))?[-#0 +]*(?:\d+)?(?:\.\d+)?[sdfrxXeEgGci%]"
                    r"|\[(?P<one>[^\[\]|%]*)\|(?P<many>[^\[\]|%]*)\]")


def _is_one(v):
    if isinstance(v, str):
        try:
            v = float(v.replace(",", "").strip())
        except ValueError:
            return False
    try:
        return v == 1
    except Exception:
        return False


def _resolve_plurals(text, args):
    out, end, idx, last = [], 0, 0, None
    for m in _TOKEN.finditer(text):
        out.append(text[end:m.start()])
        end = m.end()
        tok = m.group(0)
        if tok.startswith("%"):
            out.append(tok)
            if tok == "%%":
                continue
            name = m.group("name")
            if name is not None:
                last = args.get(name) if isinstance(args, dict) else None
            else:
                if isinstance(args, tuple):
                    last = args[idx] if idx < len(args) else None
                else:
                    last = args
                idx += 1
        else:
            out.append(m.group("one") if _is_one(last) else m.group("many"))
    out.append(text[end:])
    return "".join(out)


class Msg(str):
    """Catalog text. Formatting with % first resolves [singular|plural] markers."""
    __slots__ = ()

    def __mod__(self, args):
        text = str.__str__(self)
        if "|" in text and "[" in text:
            text = _resolve_plurals(text, args)
        return text % args


def T(key):
    """Text for key in the current language. Falls back to Korean, then to the key itself."""
    s = catalog(_lang).get(key)
    if s is None:
        s = catalog(FALLBACK).get(key, key)
    return Msg(s)


def tr(text):
    """Translate text when it is a catalog key, otherwise return it unchanged."""
    s = catalog(_lang).get(text)
    if s is None:
        s = catalog(FALLBACK).get(text)
    return text if s is None else Msg(s)


def all_T(key):
    """The text of key in every language (for matching text that may come from either)."""
    return set(catalog(l).get(key, "") for l in LANGS) - {""}


def N_(key):
    """Mark a module-level string for translation without resolving it yet.

    The key is resolved at use time with tr(), after the output language is known.
    """
    return key
