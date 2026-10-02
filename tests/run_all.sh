#!/usr/bin/env bash
# Run every check in one go:  bash tests/run_all.sh healthy-bundle.zip
# verify_logic and drive_branches assert against an ECH multi-node api bundle, so they can fail on other bundles.
# test_local_mode.py, test_handoff.py, test_logsdb.py, test_write_path.py and test_bottleneck_cost.py use synthetic data and must always pass without a bundle.
# They run both languages internally, so they run once here.
set -u
B="${1:?Give the path to a diagnostics bundle}"
cd "$(dirname "$0")/.."
rc=0
run() { echo "== $1"; shift; "$@" | tail -1; [ "${PIPESTATUS[0]}" -eq 0 ] || rc=1; }
run "i18n catalog check"                         python3 tests/i18n_check.py
run "format string static check"                 python3 tests/lint_format.py
run "local mode synthetic checks (no bundle)"    python3 tests/test_local_mode.py
run "Support summary and masking (no bundle)"    python3 tests/test_handoff.py
run "logsdb and force merge (no bundle)"         python3 tests/test_logsdb.py
run "write path and operations (no bundle)"     python3 tests/test_write_path.py
run "bottleneck summary and cost (no bundle)"    python3 tests/test_bottleneck_cost.py
run "calculation assertions"                     python3 tests/verify_logic.py "$B"
run "finding branch driver"                      python3 tests/drive_branches.py "$B"
run "input mutation fuzzing (realistic)"         python3 tests/fuzz_rules.py "$B" 45
run "RULES.md consistency"                       python3 tools/gen_rules_doc.py --check
run "docs consistency"                           python3 tests/check_docs.py "$B"
[ $rc -eq 0 ] && echo "all passed" || echo "some checks failed"
exit $rc
