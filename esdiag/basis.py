# -*- coding: utf-8 -*-
"""Basis of a finding: what the verdict rests on.

OFFICIAL : the criterion is stated in the official Elastic documentation, or it is a fact Elasticsearch
           reported itself (status, error, setting value)
FACT     : a value recorded in the bundle, reported as is (no threshold)
TOOL     : the official documentation gives no numeric criterion, so the verdict uses a threshold chosen
           by this tool; adjustable in thresholds.py
CALC     : a value computed between two bundles (increase, growth rate, extrapolation)

The constants are language-neutral ids. label() gives the display text in the current language.
"""

from .i18n import T

OFFICIAL, FACT, TOOL, CALC = "official", "fact", "tool", "calc"
ALL = (OFFICIAL, FACT, TOOL, CALC)


def label(basis):
    """Display label of a basis id in the current language."""
    return T("basis." + basis)


_MAP = {
    # cluster
    "CLU-001": FACT, "CLU-002": FACT, "CLU-003": FACT, "CLU-004": FACT,
    "CLU-005": TOOL, "CLU-006": OFFICIAL, "CLU-007": TOOL, "CLU-008": FACT,
    "CLU-009": TOOL, "CLU-010": FACT, "CLU-011": OFFICIAL, "CLU-012": FACT,
    "CLU-013": OFFICIAL, "CLU-014": OFFICIAL, "CLU-015": OFFICIAL, "CLU-016": FACT,
    "CLU-017": TOOL, "CLU-018": TOOL, "CLU-019": OFFICIAL, "CLU-020": FACT, "CLU-021": OFFICIAL,
    # nodes
    "JVM-001": TOOL, "JVM-002": OFFICIAL, "JVM-003": OFFICIAL, "JVM-004": OFFICIAL, "JVM-005": TOOL,
    "OS-001": TOOL, "OS-002": OFFICIAL, "OS-003": TOOL, "OS-004": OFFICIAL, "OS-005": OFFICIAL,
    "OS-006": TOOL,
    "DISK-001": OFFICIAL, "DISK-002": OFFICIAL, "DISK-003": OFFICIAL, "DISK-004": TOOL,
    "DISK-005": TOOL, "DISK-006": OFFICIAL, "DISK-007": OFFICIAL,
    "TP-001": FACT, "TP-002": FACT, "BRK-001": FACT, "BRK-002": TOOL, "IP-001": FACT,
    "FD-001": TOOL, "FD-002": FACT, "ING-001": FACT, "NODE-001": TOOL, "NODE-003": FACT,
    # configuration baseline
    "CFG-001": OFFICIAL, "CFG-002": OFFICIAL, "CFG-003": OFFICIAL, "CFG-004": OFFICIAL,
    "CFG-005": OFFICIAL, "CFG-006": OFFICIAL, "CFG-007": OFFICIAL, "CFG-008": OFFICIAL,
    "CFG-009": OFFICIAL,
    # shards and indices
    "SHD-001": OFFICIAL, "SHD-002": TOOL, "SHD-003": OFFICIAL, "SHD-004": TOOL, "SHD-005": TOOL,
    "SHD-006": TOOL, "SHD-007": OFFICIAL, "SHD-008": OFFICIAL, "SHD-009": OFFICIAL,
    "SHD-010": OFFICIAL, "SHD-011": OFFICIAL, "SHD-012": OFFICIAL,
    "SHD-013": TOOL, "SHD-014": TOOL, "SHD-015": OFFICIAL, "IDX-013": OFFICIAL,
    "SHD-016": TOOL, "IDX-014": FACT, "IDX-015": OFFICIAL, "PERF-012": TOOL, "OS-007": TOOL,
    "IDX-001": TOOL, "IDX-002": FACT, "IDX-003": TOOL, "IDX-004": TOOL, "IDX-005": TOOL,
    "IDX-006": FACT, "IDX-007": OFFICIAL, "IDX-008": FACT, "IDX-009": FACT, "IDX-010": FACT, "IDX-011": FACT,
    "MAP-001": TOOL, "MAP-002": TOOL, "MAP-003": OFFICIAL, "TPL-001": OFFICIAL,
    # performance
    "PERF-001": TOOL, "PERF-002": TOOL, "PERF-003": TOOL, "PERF-004": OFFICIAL,
    "PERF-005": TOOL, "PERF-006": OFFICIAL, "PERF-007": OFFICIAL, "PERF-008": OFFICIAL,
    "PERF-009": OFFICIAL, "GEN-001": OFFICIAL, "GEN-002": OFFICIAL, "GEN-003": TOOL,
    # vectors
    "VEC-001": TOOL, "VEC-002": OFFICIAL, "VEC-003": OFFICIAL, "VEC-004": OFFICIAL,
    # hotspots
    "HOT-001": OFFICIAL, "HOT-002": TOOL, "HOT-003": FACT, "HOT-005": TOOL, "HOT-004": FACT, "REC-001": TOOL,
    # operations
    "LIC-001": FACT, "SNP-001": FACT, "SNP-002": FACT, "SNP-003": TOOL, "SNP-004": FACT,
    "SNP-005": FACT, "SNP-006": FACT, "SNP-007": FACT, "ILM-001": FACT, "ILM-002": FACT, "ILM-003": TOOL,
    "ML-001": FACT, "ML-002": FACT, "SEC-001": FACT, "SEC-002": FACT, "OPS-001": FACT,
    "OPS-002": FACT,
    # runtime
    "RT-001": TOOL, "LOG-000": FACT, "LOG-001": FACT,
    "SYS-001": OFFICIAL, "SYS-002": OFFICIAL, "SYS-003": OFFICIAL, "SYS-004": FACT,
    # setting changes (defaults and effects follow the official docs, values are bundle facts)
    "SET-001": OFFICIAL, "SET-002": OFFICIAL, "SET-003": OFFICIAL, "SET-004": OFFICIAL,
    "SET-005": OFFICIAL, "SET-006": OFFICIAL,
    # over-sharding
    "OVS-001": OFFICIAL, "OVS-002": TOOL, "OVS-003": TOOL,
    # files that were not read before (deep)
    "PERF-011": TOOL, "DISK-008": TOOL, "MAP-004": TOOL, "MAP-005": OFFICIAL, "MAP-006": TOOL, "VEC-005": OFFICIAL,
    "ILM-004": OFFICIAL, "ILM-005": OFFICIAL, "ILM-006": FACT,
    "ILM-007": OFFICIAL, "ILM-008": OFFICIAL, "ILM-009": TOOL, "CLU-022": OFFICIAL, "SHUT-001": FACT,
    "IDX-012": FACT, "OPS-003": FACT, "FRZ-001": TOOL, "PERF-010": FACT, "ING-002": FACT, "CLU-023": FACT,
    "CLU-024": FACT, "ML-003": FACT, "OPS-004": FACT, "OPS-005": FACT, "OPS-006": FACT, "OPS-007": FACT,
    # meta
    "VER-001": FACT,
}


def basis_of(rule_id):
    base = str(rule_id).split(".")[0]
    if base.startswith("DIF-"):
        return CALC
    return _MAP.get(base, TOOL)
