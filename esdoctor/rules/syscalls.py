# -*- coding: utf-8 -*-
"""OS settings analysis: the syscalls/ directory of a local/remote mode bundle.

Local mode holds values for the one host where diagnostics ran. They do not apply to other nodes in the cluster.
"""

import re

from ..i18n import T, N_, tr
from ..model import Finding, Severity, table

CAT = "os"

_MIN_MAP_COUNT = 262144      # [Official] minimum for the bootstrap check (maximum map count check)
_REC_MAP_COUNT = 1048576     # [Official] recommended value (if the default is lower, set it to 1048576)
_MIN_NOFILE = 65535          # [Official] minimum for max file descriptors
_MIN_NPROC = 4096            # [Official] minimum for the thread creation limit
_OOM_RE = re.compile(r"out of memory: kill(?:ed)? process \d+ \(([^)]*)\)|oom-kill:|invoked oom-killer", re.I)
_BASE = "https://www.elastic.co/docs/deploy-manage/deploy/self-managed/"
REF_MAP = (N_("rules.syscalls._.01"), _BASE + "vm-max-map-count")
REF_SWAP = (N_("rules.syscalls._.02"), _BASE + "setup-configuration-memory")
REF_FD = (N_("rules.syscalls._.03"), _BASE + "file-descriptors")
REF_THR = (N_("rules.syscalls._.04"), _BASE + "max-number-of-threads")
REF_BOOT = ("Bootstrap checks", _BASE + "bootstrap-checks")
_SCOPE = N_("rules.syscalls._.05")


def _sysctl(ctx):
    txt = ctx.b.text("syscalls/sysctl.txt") or ""
    out = {}
    for ln in txt.splitlines():
        if "=" in ln and not ln.lstrip().startswith("#"):
            k, _, v = ln.partition("=")
            out[k.strip()] = v.strip()
    return out


def _proc_limits(ctx):
    txt = ctx.b.text("syscalls/proc-limit.txt") or ""
    out = {}
    for ln in txt.splitlines():
        m = re.match(r"^(Max [a-z ]+?)\s{2,}(\S+)\s+(\S+)", ln)
        if m:
            out[m.group(1).strip().lower()] = (m.group(2), m.group(3))
    return out


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def r_os_config(ctx):
    """OS settings of the host where diagnostics ran (SYS-001 to SYS-004).

    vm.max_map_count in syscalls/sysctl.txt below 262144 (the bootstrap check minimum) → Critical, below 1048576 (official recommendation, in the docs since 8.15 to 8.17; 262144 before) → Info, at or above → OK (SYS-001). sysctl vm.swappiness > 1, swap_total > 0 and mlockall not true → Info (SYS-002). Max open files below 65535 or Max processes below 4096 (soft limit) in syscalls/proc-limit.txt → Critical (SYS-003), otherwise OK. OOM killer entry in syscalls/dmesg.txt: target process is java/elasticsearch → Critical, any other process → Warning (SYS-004); no entry → OK.
    When every node runs in development mode (loopback transport or single-node discovery), bootstrap checks are not enforced, so the Critical results of SYS-001 and SYS-003 drop to Warning.
    When every node sets node.store.allow_mmap: false, ES skips the max map count check, so SYS-001 is Info only.
    """
    out = []
    sc = _sysctl(ctx)
    pl = _proc_limits(ctx)
    if not sc and not pl and not ctx.b.exists("syscalls/dmesg.txt"):
        return out

    dev = bool(ctx.nodes) and all(ctx.dev_mode(n) for n in ctx.nodes)
    boot_sev = Severity.WARNING if dev else Severity.CRITICAL
    dev_note = T("rules.syscalls.r_os_config.dev") if dev else ""
    mmc = _int(sc.get("vm.max_map_count"))
    # The max map count bootstrap check runs only when node.store.allow_mmap is true (the default).
    no_mmap = bool(ctx.nodes) and all(str(n.setting("node.store.allow_mmap", "true")).lower() == "false" for n in ctx.nodes)
    if mmc is not None and no_mmap:
        out.append(Finding("SYS-001", CAT, Severity.INFO, T("rules.syscalls.r_os_config.40"),
                           observed=T("rules.syscalls.r_os_config.41") % mmc,
                           refs=[REF_MAP, REF_BOOT], source="syscalls/sysctl.txt / nodes.json"))
    elif mmc is not None:
        if mmc < _MIN_MAP_COUNT:
            out.append(Finding(
                "SYS-001", CAT, boot_sev, T("rules.syscalls.r_os_config.01"),
                observed=T("rules.syscalls.r_os_config.02") % (mmc, _MIN_MAP_COUNT, tr(_SCOPE)) + dev_note,
                impact=T("rules.syscalls.r_os_config.03"),
                recommend=T("rules.syscalls.r_os_config.04"),
                refs=[REF_MAP, REF_BOOT], source="syscalls/sysctl.txt"))
        elif mmc < _REC_MAP_COUNT:
            out.append(Finding(
                "SYS-001", CAT, Severity.INFO, T("rules.syscalls.r_os_config.05"),
                observed=T("rules.syscalls.r_os_config.06")
                         % (mmc, _MIN_MAP_COUNT, _REC_MAP_COUNT, tr(_SCOPE)),
                impact=T("rules.syscalls.r_os_config.07"),
                recommend=T("rules.syscalls.r_os_config.08"),
                refs=[REF_MAP], source="syscalls/sysctl.txt"))
        else:
            out.append(Finding("SYS-001", CAT, Severity.OK, T("rules.syscalls.r_os_config.09"),
                               observed=T("rules.syscalls.r_os_config.10") % (mmc, _REC_MAP_COUNT),
                               refs=[REF_MAP], source="syscalls/sysctl.txt"))

    sw = _int(sc.get("vm.swappiness"))
    if sw is not None and sw > 1:
        swap_nodes = [n for n in ctx.nodes if n.swap_total and n.mlockall is not True]
        if swap_nodes:
            out.append(Finding(
                "SYS-002", CAT, Severity.INFO, T("rules.syscalls.r_os_config.11"),
                observed=T("rules.syscalls.r_os_config.12") % (sw, ", ".join(n.name for n in swap_nodes), tr(_SCOPE)),
                impact=T("rules.syscalls.r_os_config.13"),
                recommend=T("rules.syscalls.r_os_config.14"),
                refs=[REF_SWAP], source="syscalls/sysctl.txt"))

    if pl:
        nf = _int(pl.get("max open files", (None,))[0])
        np_ = _int(pl.get("max processes", (None,))[0])
        bad, rows = [], []
        for label, val, need in (("Max open files", nf, _MIN_NOFILE), ("Max processes", np_, _MIN_NPROC)):
            if val is None:
                continue
            rows.append([label, val, need, T("rules.syscalls.r_os_config.15") if val < need else T("rules.syscalls.r_os_config.16")])
            if val < need:
                bad.append(T("rules.syscalls.r_os_config.17") % (label, val, need))
        if bad:
            out.append(Finding(
                "SYS-003", CAT, boot_sev, T("rules.syscalls.r_os_config.18"),
                observed="; ".join(bad) + ". " + tr(_SCOPE) + dev_note,
                impact=T("rules.syscalls.r_os_config.19"),
                recommend=T("rules.syscalls.r_os_config.20"),
                evidence=table([T("rules.syscalls.r_os_config.21"), T("rules.syscalls.r_os_config.22"), T("rules.syscalls.r_os_config.23"), T("rules.syscalls.r_os_config.24")], rows),
                refs=[REF_FD, REF_THR], source="syscalls/proc-limit.txt"))
        elif rows:
            out.append(Finding("SYS-003", CAT, Severity.OK, T("rules.syscalls.r_os_config.25"),
                               observed=", ".join("%s %s" % (r[0], r[1]) for r in rows),
                               evidence=table([T("rules.syscalls.r_os_config.21"), T("rules.syscalls.r_os_config.22"), T("rules.syscalls.r_os_config.23"), T("rules.syscalls.r_os_config.24")], rows),
                               source="syscalls/proc-limit.txt"))

    dm = ctx.b.text("syscalls/dmesg.txt")
    if dm is not None:
        # One kernel OOM event logs several lines (invoked oom-killer, oom-kill:, Killed process); count the victim lines,
        # and fall back to the other lines only when no victim line is present.
        hits = [(m.group(1) or "") for m in _OOM_RE.finditer(dm)]
        victims = [h for h in hits if h]
        if victims:
            hits = victims
        if hits:
            java = [h for h in hits if re.search(r"java|elasticsearch", h, re.I)]
            out.append(Finding(
                "SYS-004", CAT, Severity.CRITICAL if java else Severity.WARNING, T("rules.syscalls.r_os_config.26"),
                observed=T("rules.syscalls.r_os_config.27")
                         % (len(hits), ", ".join(sorted(set(h for h in hits if h))) or T("rules.syscalls.r_os_config.28"), tr(_SCOPE)),
                impact=T("rules.syscalls.r_os_config.29"),
                recommend=T("rules.syscalls.r_os_config.30"),
                source="syscalls/dmesg.txt"))
        else:
            out.append(Finding("SYS-004", CAT, Severity.OK, T("rules.syscalls.r_os_config.31"),
                               observed=T("rules.syscalls.r_os_config.32"), source="syscalls/dmesg.txt"))
    return out


RULES = [r_os_config]
