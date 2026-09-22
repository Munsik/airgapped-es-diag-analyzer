#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Elasticsearch support-diagnostics 오프라인 분석기.

사용 예:
  python3 analyze.py diagnostic-xxxx.zip
  python3 analyze.py diagnostic-xxxx.zip --html report.html
  python3 analyze.py ./api-diagnostics-20260814-045134 --html r.html --md r.md --json r.json
  python3 analyze.py bundle.zip --thresholds my_thresholds.json --no-ok

외부 네트워크 접근이 전혀 없으며 Python 3.8+ 표준 라이브러리만 사용합니다.
"""

import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from esdiag import __version__
from esdiag.engine import analyze
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


def main(argv=None):
    _safe_stdout()
    p = argparse.ArgumentParser(
        description="Elasticsearch 진단 번들 오프라인 분석기 v%s" % __version__,
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("bundle", nargs="?", help="진단 번들 zip 파일 또는 압축 해제 디렉터리")
    p.add_argument("--baseline", metavar="FILE",
                   help="이전 시점의 진단 번들. 지정하면 두 번들을 비교해 증가분·증가율을 판정")
    p.add_argument("--html", metavar="FILE", help="HTML 리포트 출력 경로")
    p.add_argument("--md", metavar="FILE", help="Markdown 리포트 출력 경로")
    p.add_argument("--json", metavar="FILE", help="JSON 결과 출력 경로")
    p.add_argument("--out-dir", metavar="DIR",
                   help="지정 시 <DIR>/es-diag-report.{html,md,json} 으로 일괄 저장")
    p.add_argument("--no-ok", action="store_true", help="정상 판정 항목 숨김")
    p.add_argument("--quiet", action="store_true", help="콘솔 출력 생략")
    p.add_argument("--thresholds", metavar="FILE", help="임계값 재정의 JSON 파일")
    p.add_argument("--print-thresholds", action="store_true",
                   help="기본 임계값을 JSON 으로 출력하고 종료")
    p.add_argument("--only", metavar="MOD", action="append",
                   help="특정 룰 모듈만 실행 (cluster|nodes|shards|guidance|hotspot|ops|runtime), 반복 지정 가능")
    p.add_argument("--fail-on", choices=["critical", "warning", "never"], default="never",
                   help="해당 심각도 발견 시 종료코드 1 반환 (CI/배치 연계용)")
    p.add_argument("--debug", action="store_true", help="룰 실행 오류 상세 출력")
    p.add_argument("--check-env", action="store_true", help="실행 환경 사전 점검 후 종료")
    p.add_argument("--version", action="version", version="esdiag %s" % __version__)
    args = p.parse_args(argv)

    if args.check_env:
        from esdiag.envcheck import run as check_env
        return check_env(args.out_dir)
    if args.print_thresholds:
        print(json.dumps(DEFAULTS, indent=2, ensure_ascii=False))
        return 0
    if not args.bundle:
        p.error("분석할 진단 번들 경로가 필요합니다.")
    if not os.path.exists(args.bundle):
        print("입력 경로를 찾을 수 없습니다: %s" % args.bundle, file=sys.stderr)
        return 2

    overrides = {}
    if args.thresholds:
        with io.open(args.thresholds, "r", encoding="utf-8") as fh:
            overrides = json.load(fh)

    if args.baseline and not os.path.exists(args.baseline):
        print("baseline 경로를 찾을 수 없습니다: %s" % args.baseline, file=sys.stderr)
        return 2
    try:
        result = analyze(args.bundle, thresholds=overrides, only=args.only,
                         skip_ok=args.no_ok, baseline=args.baseline)
    except ValueError as exc:
        print("오류: %s" % exc, file=sys.stderr)
        return 2

    if not args.quiet:
        out = text_report.console(result, show_ok=not args.no_ok)
        try:
            print(out)
        except UnicodeEncodeError:              # 일부 윈도우 콘솔 대응
            sys.stdout.write(out.encode("utf-8", "replace").decode("utf-8", "replace") + "\n")

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

    if "html" in targets:
        _write(targets["html"], html_report.render(result))
    if "md" in targets:
        _write(targets["md"], text_report.markdown(result, show_ok=not args.no_ok))
    if "json" in targets:
        _write(targets["json"], json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    for kind, path in targets.items():
        print("생성: %s (%s)" % (path, kind), file=sys.stderr)

    if args.debug and result.errors:
        for err in result.errors:
            print("[룰 오류] %s\n%s" % (err["rule"], err["error"]), file=sys.stderr)

    if args.fail_on == "critical" and result.counts[Severity.CRITICAL] > 0:
        return 1
    if args.fail_on == "warning" and (result.counts[Severity.CRITICAL] or
                                      result.counts[Severity.WARNING]):
        return 1
    return 0


def _write(path, content):
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


if __name__ == "__main__":
    sys.exit(main())
