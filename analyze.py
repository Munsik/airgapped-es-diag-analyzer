#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Offline analyzer for Elasticsearch support-diagnostics bundles.

Examples:
  python3 analyze.py diagnostic-xxxx.zip
  python3 analyze.py diagnostic-xxxx.zip --html report.html
  python3 analyze.py ./api-diagnostics-20260814-045134 --html r.html --md r.md --json r.json
  python3 analyze.py bundle.zip --thresholds my_thresholds.json --no-ok
  python3 analyze.py bundle.zip --html r.html --lang en

Reports are written in Korean and English by default (r.ko.html and r.en.html).
Use --lang ko or --lang en to write one language under the exact name you give.
No network access is made. Python 3.8+ standard library only.
"""

import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from esdiag.i18n import LANGS, T, detect_lang, set_lang
from esdiag import __version__
from esdiag.engine import analyze
from esdiag.rules import MODULES
from esdiag.model import Severity
from esdiag.report import html as html_report
from esdiag.report import text as text_report
from esdiag.thresholds import DEFAULTS


def _safe_stdout():
    try:
        enc = (sys.stdout.encoding or "").lower()
        if enc and "utf" not in enc and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass


def _pre_lang(argv):
    """Language named by --lang on the raw command line, read before argparse builds the help text."""
    argv = list(sys.argv[1:] if argv is None else argv)
    found = None
    for i, a in enumerate(argv):
        if a.startswith("--lang="):
            found = a.split("=", 1)[1]
        elif a == "--lang" and i + 1 < len(argv):
            found = argv[i + 1]
    if found in LANGS:
        return found
    return detect_lang()


def _lang_path(path, lang, multi):
    """report.html -> report.ko.html when several languages are written, otherwise unchanged."""
    if not multi:
        return path
    stem, ext = os.path.splitext(path)
    return "%s.%s%s" % (stem, lang, ext)


def main(argv=None):
    _safe_stdout()
    set_lang(_pre_lang(argv))
    p = argparse.ArgumentParser(
        description=T("analyze.main.01") % __version__,
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("bundle", nargs="?", help=T("analyze.main.02"))
    p.add_argument("--baseline", metavar="FILE",
                   help=T("analyze.main.03"))
    p.add_argument("--html", metavar="FILE", help=T("analyze.main.04"))
    p.add_argument("--md", metavar="FILE", help=T("analyze.main.05"))
    p.add_argument("--json", metavar="FILE", help=T("analyze.main.06"))
    p.add_argument("--out-dir", metavar="DIR",
                   help=T("analyze.main.07"))
    p.add_argument("--support-summary", metavar="FILE",
                   help=T("analyze.main.08"))
    p.add_argument("--mask", choices=["none", "basic", "strict"], default=None,
                   help=T("analyze.main.09"))
    p.add_argument("--mask-map", metavar="FILE",
                   help=T("analyze.main.10"))
    p.add_argument("--lang", choices=["both", "ko", "en", "auto"], default="both",
                   help=T("analyze.main.lang"))
    p.add_argument("--no-ok", action="store_true", help=T("analyze.main.11"))
    p.add_argument("--quiet", action="store_true", help=T("analyze.main.12"))
    p.add_argument("--thresholds", metavar="FILE", help=T("analyze.main.13"))
    p.add_argument("--print-thresholds", action="store_true",
                   help=T("analyze.main.14"))
    mods = [m.__name__.split(".")[-1] for m in MODULES]
    p.add_argument("--only", metavar="MOD", action="append", choices=mods,
                   help=T("analyze.main.15") % "|".join(mods))
    p.add_argument("--fail-on", choices=["critical", "warning", "never"], default="never",
                   help=T("analyze.main.16"))
    p.add_argument("--debug", action="store_true", help=T("analyze.main.17"))
    p.add_argument("--check-env", action="store_true", help=T("analyze.main.18"))
    p.add_argument("--version", action="version", version="esdiag %s" % __version__)
    args = p.parse_args(argv)

    if args.check_env:
        from esdiag.envcheck import run as check_env
        return check_env(args.out_dir)
    if args.print_thresholds:
        print(json.dumps(DEFAULTS, indent=2, ensure_ascii=False))
        return 0
    if not args.bundle:
        p.error(T("analyze.main.19"))
    if not os.path.exists(args.bundle):
        print(T("analyze.main.20") % args.bundle, file=sys.stderr)
        return 2

    overrides = {}
    if args.thresholds:
        with io.open(args.thresholds, "r", encoding="utf-8") as fh:
            overrides = json.load(fh)

    if (args.mask or args.mask_map) and not args.support_summary:
        p.error(T("analyze.main.21"))

    if args.baseline and not os.path.exists(args.baseline):
        print(T("analyze.main.22") % args.baseline, file=sys.stderr)
        return 2

    # Screen language: --lang ko|en as given, otherwise the locale. The console language always runs first
    # so that errors appear in it.
    screen = detect_lang() if args.lang in ("both", "auto") else args.lang
    langs = [screen] + [l for l in LANGS if l != screen] if args.lang == "both" else [screen]
    multi = len(langs) > 1

    targets = {}
    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
        targets["html"] = os.path.join(args.out_dir, "es-diag-report.html")
        targets["md"] = os.path.join(args.out_dir, "es-diag-report.md")
        targets["json"] = os.path.join(args.out_dir, "es-diag-report.json")
    if args.html:
        targets["html"] = args.html
    if args.md:
        targets["md"] = args.md
    if args.json:
        targets["json"] = args.json

    bundles = {}                    # opened once, shared by every language pass
    written = []                    # (message key, arguments), printed in the screen language at the end
    first_map = None
    for lang in langs:
        set_lang(lang)
        try:
            result = analyze(args.bundle, thresholds=overrides, only=args.only,
                             skip_ok=args.no_ok, baseline=args.baseline, bundles=bundles)
        except ValueError as exc:
            print(T("analyze.main.23") % exc, file=sys.stderr)
            return 2

        if lang == screen and not args.quiet:
            out = text_report.console(result, show_ok=not args.no_ok)
            try:
                print(out)
            except UnicodeEncodeError:              # some Windows consoles
                sys.stdout.write(out.encode("utf-8", "replace").decode("utf-8", "replace") + "\n")

        if args.support_summary:
            rc, first_map = _support_summary(result, args, lang, multi, first_map, written)
            if rc:
                return rc
        if "html" in targets:
            path = _lang_path(targets["html"], lang, multi)
            _write(path, html_report.render(result))
            written.append(("analyze.main.24", (path, "html")))
        if "md" in targets:
            path = _lang_path(targets["md"], lang, multi)
            _write(path, text_report.markdown(result, show_ok=not args.no_ok))
            written.append(("analyze.main.24", (path, "md")))
        if "json" in targets:
            path = _lang_path(targets["json"], lang, multi)
            _write(path, json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            written.append(("analyze.main.24", (path, "json")))
        if lang == screen:
            screen_result = result

    set_lang(screen)
    for key, margs in written:
        print(T(key) % margs, file=sys.stderr)

    if args.debug and screen_result.errors:
        for err in screen_result.errors:
            print(T("analyze.main.25") % (err["rule"], err["error"]), file=sys.stderr)

    if args.fail_on == "critical" and screen_result.counts[Severity.CRITICAL] > 0:
        return 1
    if args.fail_on == "warning" and (screen_result.counts[Severity.CRITICAL] or
                                      screen_result.counts[Severity.WARNING]):
        return 1
    return 0


def _support_summary(result, args, lang, multi, first_map, written):
    """Write the summary for Elastic Support. If an identifier survives masking, write nothing and return 2.

    Returns (exit code, alias map of the first language). The map file is written once; a later language
    gets its own map file only if its aliases differ.
    """
    from esdiag.mask import Masker
    from esdiag.report import handoff
    level = args.mask or "basic"
    masker = Masker(result.ctx, level=level)
    try:
        content = handoff.render(result, masker, level, __version__)
    except handoff.MaskLeak as exc:
        print(T("analyze._support_summary.01") % len(exc.leaks), file=sys.stderr)
        return 2, first_map
    path = _lang_path(args.support_summary, lang, multi)
    _write(path, content)
    written.append(("analyze._support_summary.02", (path, level)))
    if level != "none":
        mapping = masker.mapping()
        map_path = args.mask_map or (args.support_summary + ".mask-map.json")
        if first_map is None:
            _write(map_path, json.dumps(mapping, indent=2, ensure_ascii=False))
            try:
                os.chmod(map_path, 0o600)
            except OSError:
                pass
            written.append(("analyze._support_summary.03", (map_path,)))
            first_map = mapping
        elif mapping != first_map:
            alt = _lang_path(map_path, lang, True)
            _write(alt, json.dumps(mapping, indent=2, ensure_ascii=False))
            try:
                os.chmod(alt, 0o600)
            except OSError:
                pass
            written.append(("analyze._support_summary.03", (alt,)))
    return 0, first_map


def _write(path, content):
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


if __name__ == "__main__":
    sys.exit(main())
