#!/usr/bin/env bash
# 전체 검증 한 번에 실행:  bash tests/run_all.sh 정상번들.zip
set -u
B="${1:?진단 번들 경로를 지정하십시오}"
cd "$(dirname "$0")/.."
rc=0
run() { echo "== $1"; shift; "$@" | tail -1; [ "${PIPESTATUS[0]}" -eq 0 ] || rc=1; }
run "포맷 문자열 정적 검사"   python3 tests/lint_format.py
run "계산 로직 단정문"        python3 tests/verify_logic.py "$B"
run "판정 분기 구동"          python3 tests/drive_branches.py "$B"
run "입력 변형 퍼징(현실적)"  python3 tests/fuzz_rules.py "$B" 45
run "RULES.md 정합성"         python3 tools/gen_rules_doc.py --check
run "문서 정합성"             python3 tests/check_docs.py "$B"
[ $rc -eq 0 ] && echo "전체 통과" || echo "실패 항목 있음"
exit $rc
