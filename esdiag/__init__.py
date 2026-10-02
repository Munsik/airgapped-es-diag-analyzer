"""
esdiag - Elastic support-diagnostics offline analyzer.

Analyzes Elasticsearch support-diagnostics bundles in air-gapped environments.
Uses only the Python 3.8+ standard library and makes no outbound network calls.
"""
from .i18n import N_

__version__ = "0.14.0"

# ---------------------------------------------------------------------------
# Baseline for findings
#   - ES_BASELINE      : Elasticsearch docs version the rule logic, defaults and recommendations were checked against
#   - DOCS_CHECKED     : when the official docs were checked
#   - VALIDATED_BUNDLE : description of the real diagnostics bundles used for validation (catalog key)
#   - SUPPORTED_MIN    : lowest version where the rules work as intended (below it only some rules run)
# Analyzing a version newer than the baseline raises VER-001 (defaults and behavior may have changed).
# ---------------------------------------------------------------------------
ES_BASELINE = (9, 4)
DOCS_CHECKED = "2026-10"
VALIDATED_BUNDLE = N_("pkg.validated_bundle")
FIELD_TESTED = N_("pkg.field_tested")
SUPPORTED_MIN = (8, 0)
VALIDATED_MODES = N_("pkg.validated_modes")

# Points where findings differ by version (RULES.md lists the same gates)
VERSION_GATES = [
    ((8, 0), "SET-*", N_("pkg.gate.set")),
    ((8, 3), "SHD-001", N_("pkg.gate.shd001")),
    ((8, 5), "DISK-*", N_("pkg.gate.disk")),
    ((8, 8), "IDX-015", N_("pkg.gate.idx015")),
    ((8, 14), "VEC-002", N_("pkg.gate.vec002a")),
    ((9, 0), "IDX-013", N_("pkg.gate.idx013")),
    ((9, 1), "VEC-002", N_("pkg.gate.vec002b")),
    ((9, 2), "VEC-003", N_("pkg.gate.vec003")),
]
