# -*- coding: utf-8 -*-
"""Operations and lifecycle rules (license, snapshots, ILM/SLM, ML, certificates)."""

import datetime

from ..i18n import T
from ..context import _parse_iso
from ..model import Finding, Severity, table
from ..util import dig, fmt_bytes, fmt_num, dicts, num, items

CAT = "ops"
SEC = "security"


def _now(ctx):
    return ctx.collection_time or datetime.datetime.now(datetime.timezone.utc)


def _days_until(ctx, dt):
    if dt is None:
        return None
    now = _now(ctx)
    if dt.tzinfo is None and now.tzinfo is not None:
        dt = dt.replace(tzinfo=now.tzinfo)
    if now.tzinfo is None and dt.tzinfo is not None:
        now = now.replace(tzinfo=dt.tzinfo)
    return (dt - now).total_seconds() / 86400.0


def r_license(ctx):
    """license.status != active → Critical. Time to expiry <= license_expiry_days_crit days → Critical, <= warn days → Warning, otherwise OK. The reference time is the bundle collection time."""
    lic = ctx.license or {}
    if not lic:
        return []
    status = (lic.get("status") or "").lower()
    exp = _parse_iso(lic.get("expiry_date"))
    days = _days_until(ctx, exp)
    ev = table([T("rules.ops.r_license.01"), T("rules.ops.r_license.02")],
               [["type", lic.get("type")], ["status", status],
                ["issued_to", lic.get("issued_to")],
                ["expiry", lic.get("expiry_date") or T("rules.ops.r_license.03")],
                ["max_nodes / max_resource_units",
                 "%s / %s" % (lic.get("max_nodes"), lic.get("max_resource_units"))]])
    if status not in ("active",):
        return [Finding("LIC-001", CAT, Severity.CRITICAL, T("rules.ops.r_license.04"),
                        observed="license status=%s (%s)" % (status, lic.get("type")),
                        impact=T("rules.ops.r_license.05"),
                        recommend=T("rules.ops.r_license.06"), evidence=ev, source="licenses.json")]
    if days is not None:
        if days <= ctx.t["license_expiry_days_crit"]:
            return [Finding("LIC-001", CAT, Severity.CRITICAL, T("rules.ops.r_license.07"),
                            observed=T("rules.ops.r_license.08") % (days, lic.get("expiry_date")),
                            impact=T("rules.ops.r_license.09"),
                            recommend=T("rules.ops.r_license.10"), evidence=ev,
                            source="licenses.json")]
        if days <= ctx.t["license_expiry_days_warn"]:
            return [Finding("LIC-001", CAT, Severity.WARNING, T("rules.ops.r_license.11"),
                            observed=T("rules.ops.r_license.08") % (days, lic.get("expiry_date")),
                            impact=T("rules.ops.r_license.12"),
                            recommend=T("rules.ops.r_license.13"), evidence=ev, source="licenses.json")]
    return [Finding("LIC-001", CAT, Severity.OK, T("rules.ops.r_license.14"),
                    observed=T("rules.ops.r_license.15") % (lic.get("type"),
                                                     "%.0f" % days if days else T("rules.ops.r_license.03")),
                    evidence=ev, source="licenses.json")]


def r_snapshots(ctx):
    """No repository and no snapshot → Critical (SNP-001). FAILED/PARTIAL snapshot present → Warning, and Critical if no later successful snapshot exists (SNP-002). Age of the last SUCCESS snapshot (the SLM policy's last_success time if snapshot.json has no time) >= snapshot_age_hours_crit → Critical, >= warn → Warning, otherwise OK (SNP-003; in-progress, failed and partial snapshots are excluded from the RPO calculation). Time data present but no successful snapshot → Critical. IN_PROGRESS present → Info (SNP-004). Cumulative SLM failures >= snapshot_failed_warn → Warning (SNP-005). SLM operation_mode != RUNNING → Warning (SNP-006). SLM policy whose last failure is more recent than its last success → Critical (SNP-007)."""
    out = []
    snaps = (ctx.snapshots or {}).get("snapshots") or []
    repos = ctx.repositories or []
    if not repos and not snaps:
        return [Finding(
            "SNP-001", CAT, Severity.CRITICAL, T("rules.ops.r_snapshots.01"),
            observed=T("rules.ops.r_snapshots.02"),
            impact=T("rules.ops.r_snapshots.03"),
            recommend=T("rules.ops.r_snapshots.04"),
            source="repositories.json")]
    failed = [s for s in snaps if (s.get("state") or "").upper() in ("FAILED", "PARTIAL")]
    in_prog = [s for s in snaps if (s.get("state") or "").upper() == "IN_PROGRESS"]
    # The recovery point (RPO) is based on the last successful snapshot. In-progress, failed and partial snapshots cannot be used for recovery.
    latest = None
    for s in dicts(snaps):
        if (s.get("state") or "").upper() != "SUCCESS":
            continue
        t = num(s, "end_time_in_millis") or num(s, "start_time_in_millis")
        if t and (latest is None or t > latest[0]):
            latest = (t, s)
    has_times = any(num(s, "end_time_in_millis") or num(s, "start_time_in_millis") for s in dicts(snaps))
    # If snapshot.json is a plain list (no timestamps), use the SLM policy last success time as the RPO basis
    rpo_source = "snapshot.json"
    if latest is None:
        for pname, pol in items(ctx.slm_policies):
            ls = pol.get("last_success") if isinstance(pol, dict) else None
            t = num(ls, "time") if isinstance(ls, dict) else 0
            if t and (latest is None or t > latest[0]):
                latest = (t, {"snapshot": "%s (SLM %s)" % (ls.get("snapshot_name"), pname)})
                rpo_source = "slm_policies.json"
    if failed:
        f_last = max([num(s, "end_time_in_millis") or num(s, "start_time_in_millis") for s in failed] or [0])
        recovered = bool(latest and f_last and latest[0] > f_last)
        out.append(Finding(
            "SNP-002", CAT, Severity.WARNING if recovered else Severity.CRITICAL, T("rules.ops.r_snapshots.05"),
            observed=T("rules.ops.r_snapshots.06") % len(failed),
            impact=T("rules.ops.r_snapshots.07"),
            recommend=T("rules.ops.r_snapshots.08"),
            evidence=table(["snapshot", "repository", "state", T("rules.ops.r_snapshots.09")],
                           [[s.get("snapshot"), s.get("repository"), s.get("state"),
                             "%s/%s" % (dig(s, "shards", "failed"), dig(s, "shards", "total"))]
                            for s in failed[: ctx.t["top_n"]]]),
            source="snapshot.json"))
    if latest:
        age_h = (_now(ctx).timestamp() * 1000 - latest[0]) / 3600000.0
        sev = None
        if age_h >= ctx.t["snapshot_age_hours_crit"]:
            sev = Severity.CRITICAL
        elif age_h >= ctx.t["snapshot_age_hours_warn"]:
            sev = Severity.WARNING
        if sev:
            out.append(Finding(
                "SNP-003", CAT, sev, T("rules.ops.r_snapshots.10"),
                observed=T("rules.ops.r_snapshots.11") % (latest[1].get("snapshot"), age_h),
                impact=T("rules.ops.r_snapshots.12"),
                recommend=T("rules.ops.r_snapshots.13"),
                source=rpo_source))
        else:
            out.append(Finding(
                "SNP-003", CAT, Severity.OK, T("rules.ops.r_snapshots.14"),
                observed=T("rules.ops.r_snapshots.15") % (age_h, len(snaps), rpo_source),
                source=rpo_source))
    # Per SLM policy: a last failure newer than the last success means the policy is failing now
    failing = []
    for pname, pol in items(ctx.slm_policies):
        if not isinstance(pol, dict):
            continue
        ls, lf = pol.get("last_success"), pol.get("last_failure")
        ts = num(ls, "time") if isinstance(ls, dict) else 0
        tf = num(lf, "time") if isinstance(lf, dict) else 0
        if tf and tf > ts:
            failing.append([pname, (lf or {}).get("time_string") or tf, (ls or {}).get("time_string") or "-",
                            str((lf or {}).get("details") or "")[:160]])
    if failing:
        out.append(Finding(
            "SNP-007", CAT, Severity.CRITICAL, T("rules.ops.r_snapshots.16"),
            observed=T("rules.ops.r_snapshots.17") % len(failing),
            impact=T("rules.ops.r_snapshots.18"),
            recommend=T("rules.ops.r_snapshots.19"),
            evidence=table([T("rules.ops.r_snapshots.20"), T("rules.ops.r_snapshots.21"), T("rules.ops.r_snapshots.22"), T("rules.ops.r_snapshots.23")], failing),
            source="slm_policies.json"))
    if latest is None and has_times and snaps:
        out.append(Finding(
            "SNP-003", CAT, Severity.CRITICAL, T("rules.ops.r_snapshots.24"),
            observed=T("rules.ops.r_snapshots.25") % len(snaps),
            impact=T("rules.ops.r_snapshots.26"),
            recommend=T("rules.ops.r_snapshots.27"), source="snapshot.json"))
    if in_prog:
        out.append(Finding(
            "SNP-004", CAT, Severity.INFO, T("rules.ops.r_snapshots.28"),
            observed=T("rules.ops.r_snapshots.29") % len(in_prog),
            impact=T("rules.ops.r_snapshots.30"),
            recommend=T("rules.ops.r_snapshots.31"),
            source="snapshot.json"))
    # SLM
    st = ctx.slm_stats or {}
    if st:
        fails = num(st, "total_snapshots_failed")
        if fails >= ctx.t["snapshot_failed_warn"]:
            out.append(Finding(
                "SNP-005", CAT, Severity.WARNING, T("rules.ops.r_snapshots.32"),
                observed=T("rules.ops.r_snapshots.33")
                         % (fmt_num(fails), fmt_num(st.get("total_snapshots_taken"))),
                impact=T("rules.ops.r_snapshots.34"),
                recommend=T("rules.ops.r_snapshots.35"),
                evidence=table(["policy", "taken", "failed", "deleted"],
                               [[p.get("policy"), fmt_num(p.get("snapshots_taken")),
                                 fmt_num(p.get("snapshots_failed")),
                                 fmt_num(p.get("snapshots_deleted"))]
                                for p in dicts(st.get("policy_stats"))]),
                source="commercial/slm_stats.json"))
    slm_mode = (ctx.slm_status or {}).get("operation_mode")
    if slm_mode and slm_mode.upper() != "RUNNING":
        out.append(Finding(
            "SNP-006", CAT, Severity.WARNING, T("rules.ops.r_snapshots.36"),
            observed="SLM operation_mode=%s" % slm_mode,
            impact=T("rules.ops.r_snapshots.37"),
            recommend=T("rules.ops.r_snapshots.38"),
            source="commercial/slm_status.json"))
    return out


def r_ilm(ctx):
    """ILM operation_mode != RUNNING → Warning (ILM-001). ilm_explain with step=ERROR or a failed_step → Critical if a rollover-related step failed, otherwise (delete, shrink or migrate steps, failure to delete a write index, etc.) Warning (ILM-002). User indices without ILM (managed=false) and primary > 10GB → Info (ILM-003)."""
    out = []
    mode = (ctx.ilm_status or {}).get("operation_mode")
    if mode and mode.upper() != "RUNNING":
        out.append(Finding(
            "ILM-001", CAT, Severity.WARNING, T("rules.ops.r_ilm.01"),
            observed="ILM operation_mode=%s" % mode,
            impact=T("rules.ops.r_ilm.02"),
            recommend=T("rules.ops.r_ilm.03"),
            source="commercial/ilm_status.json"))
    errors = []
    for name, ex in items(ctx.ilm_explain):
        if not isinstance(ex, dict):
            continue
        if ex.get("step") == "ERROR" or ex.get("failed_step"):
            errors.append([name, ex.get("policy"), ex.get("phase"), ex.get("failed_step"),
                           str(dig(ex, "step_info", "reason") or
                               dig(ex, "step_info", "type") or "")[:160]])
    if errors:
        # A stuck rollover step lets the write index keep growing (Critical). A stall in any other step is a lifecycle delay (Warning).
        rollover_steps = ("check-rollover-ready", "attempt-rollover", "update-rollover-lifecycle-date",
                          "wait-for-active-shards", "set-indexing-complete")
        stuck_rollover = [r for r in errors if str(r[3]) in rollover_steps]
        write_delete = [r for r in errors if "is the write index" in str(r[4])]
        sev = Severity.CRITICAL if stuck_rollover else Severity.WARNING
        note = []
        if stuck_rollover:
            note.append(T("rules.ops.r_ilm.04") % len(stuck_rollover))
        if write_delete:
            note.append(T("rules.ops.r_ilm.05") % len(write_delete))
        out.append(Finding(
            "ILM-002", CAT, sev, T("rules.ops.r_ilm.06"),
            observed=T("rules.ops.r_ilm.07") % (len(errors), (" (" + ", ".join(note) + ")") if note else ""),
            impact=T("rules.ops.r_ilm.08"),
            recommend=T("rules.ops.r_ilm.09"),
            evidence=table(["index", "policy", "phase", "failed_step", "reason"],
                           errors[: ctx.t["top_n"]]),
            source="commercial/ilm_explain.json"))
    # User indices not managed by ILM
    unmanaged = []
    for name, ex in items(ctx.ilm_explain):
        if ctx.is_system_index(name):
            continue
        if isinstance(ex, dict) and ex.get("managed") is False:
            size = num(ctx.indices_stats, name, "primaries", "store", "size_in_bytes")
            if size > 10 * 1024 ** 3:
                unmanaged.append([name, fmt_bytes(size), size])
    if unmanaged:
        unmanaged.sort(key=lambda r: -r[2])
        out.append(Finding(
            "ILM-003", CAT, Severity.INFO, T("rules.ops.r_ilm.10"),
            observed=T("rules.ops.r_ilm.11") % len(unmanaged),
            impact=T("rules.ops.r_ilm.12"),
            recommend=T("rules.ops.r_ilm.13"),
            evidence=table(["index", T("rules.ops.r_ilm.14")], [r[:2] for r in unmanaged[: ctx.t["top_n"]]]),
            source="commercial/ilm_explain.json"))
    return out


def r_ml_transform(ctx):
    """transform state failed/aborting → Warning (ML-001). Anomaly detection job state=failed → Warning (ML-002)."""
    out = []
    tstats = (ctx.transform_stats or {}).get("transforms") or []
    bad_t = [t for t in tstats if (t.get("state") or "").lower() in ("failed", "aborting")]
    if bad_t:
        out.append(Finding(
            "ML-001", CAT, Severity.WARNING, T("rules.ops.r_ml_transform.01"),
            observed=T("rules.ops.r_ml_transform.02") % len(bad_t),
            impact=T("rules.ops.r_ml_transform.03"),
            recommend=T("rules.ops.r_ml_transform.04"),
            evidence=table(["id", "state", "reason"],
                           [[t.get("id"), t.get("state"), str(t.get("reason"))[:160]]
                            for t in bad_t[: ctx.t["top_n"]]]),
            source="commercial/transform_stats.json"))
    # Anomaly detection jobs
    jobs = (ctx.ml_anomaly or {}).get("jobs") or []
    bad_j = []
    for j in jobs:
        if isinstance(j, dict) and (j.get("state") or "").lower() in ("failed",):
            bad_j.append([j.get("job_id"), j.get("state")])
    if bad_j:
        out.append(Finding(
            "ML-002", CAT, Severity.WARNING, T("rules.ops.r_ml_transform.05"),
            observed=T("rules.ops.r_ml_transform.06") % len(bad_j),
            impact=T("rules.ops.r_ml_transform.07"),
            recommend=T("rules.ops.r_ml_transform.08"),
            evidence=table(["job_id", "state"], bad_j), source="commercial/ml_anomaly_detectors.json"))
    return out


def r_certificates(ctx):
    """Time to certificate expiry in ssl_certs.json <= cert_expiry_days_crit days → Critical, <= warn days → Warning, otherwise OK. The reference time is the bundle collection time."""
    certs = ctx.ssl_certs or []
    if not certs:
        return []
    rows_crit, rows_warn, rows = [], [], []
    for c in certs:
        exp = _parse_iso(c.get("expiry"))
        d = _days_until(ctx, exp)
        if d is None:
            continue
        row = [c.get("path") or c.get("alias"), (c.get("subject_dn") or "")[:80],
               c.get("expiry"), T("rules.ops.r_certificates.01") % d]
        rows.append(row)
        if d <= ctx.t["cert_expiry_days_crit"]:
            rows_crit.append(row)
        elif d <= ctx.t["cert_expiry_days_warn"]:
            rows_warn.append(row)
    if rows_crit:
        return [Finding("SEC-001", SEC, Severity.CRITICAL, T("rules.ops.r_certificates.02"),
                        observed=T("rules.ops.r_certificates.03") % (ctx.t["cert_expiry_days_crit"],
                                                        len(rows_crit)),
                        impact=T("rules.ops.r_certificates.04"),
                        recommend=T("rules.ops.r_certificates.05"),
                        evidence=table(["path", "subject", "expiry", T("rules.ops.r_certificates.06")], rows_crit),
                        source="ssl_certs.json")]
    if rows_warn:
        return [Finding("SEC-001", SEC, Severity.WARNING, T("rules.ops.r_certificates.07"),
                        observed=T("rules.ops.r_certificates.03") % (ctx.t["cert_expiry_days_warn"],
                                                        len(rows_warn)),
                        impact=T("rules.ops.r_certificates.08"),
                        recommend=T("rules.ops.r_certificates.09"),
                        evidence=table(["path", "subject", "expiry", T("rules.ops.r_certificates.06")], rows_warn),
                        source="ssl_certs.json")]
    return [Finding("SEC-001", SEC, Severity.OK, T("rules.ops.r_certificates.10"),
                    observed=T("rules.ops.r_certificates.11")
                             % (len(rows), ctx.t["cert_expiry_days_warn"]),
                    source="ssl_certs.json")]


def r_security_enabled(ctx):
    """xpack security.enabled=false → Critical, otherwise OK."""
    sec = dig(ctx.xpack, "security", default={}) or {}
    if not sec:
        return []
    if sec.get("enabled") is False:
        hosts = [str(n.setting("network.host") or n.setting("http.host") or "") for n in ctx.nodes]
        loopback = bool(hosts) and all(h in ("127.0.0.1", "localhost", "::1", "_local_") for h in hosts)
        return [Finding("SEC-002", SEC, Severity.WARNING if loopback else Severity.CRITICAL,
                        T("rules.ops.r_security_enabled.01") + (T("rules.ops.r_security_enabled.02") if loopback else ""),
                        observed="xpack.security.enabled = false"
                                 + (T("rules.ops.r_security_enabled.03") % hosts[0] if loopback else ""),
                        impact=T("rules.ops.r_security_enabled.04"),
                        recommend=T("rules.ops.r_security_enabled.05"),
                        source="commercial/xpack.json")]
    return [Finding("SEC-002", SEC, Severity.OK, T("rules.ops.r_security_enabled.06"),
                    observed="xpack security enabled.", source="commercial/xpack.json")]


def r_geoip(ctx):
    """GeoIP failed_downloads or expired_databases > 0 → Info (can be normal in an air-gapped network)."""
    st = dig(ctx.geoip, "stats", default={}) or {}
    failed = num(st, "failed_downloads")
    expired = num(st, "expired_databases")
    if not failed and not expired:
        return []
    return [Finding(
        "OPS-001", CAT, Severity.INFO, T("rules.ops.r_geoip.01"),
        observed=T("rules.ops.r_geoip.02") % (fmt_num(failed), fmt_num(expired)),
        impact=T("rules.ops.r_geoip.03"),
        recommend=T("rules.ops.r_geoip.04"),
        source="geoip_stats.json")]


def r_ccr(ctx):
    """Warning if a CCR follower shard has read_exceptions or failed_read/write_requests."""
    follow = (ctx.ccr_stats or {}).get("follow_stats") or {}
    idxs = follow.get("indices") or []
    bad = []
    for i in idxs:
        for s in dicts(i.get("shards")):
            errs = s.get("read_exceptions") or []
            if errs or s.get("failed_read_requests") or s.get("failed_write_requests"):
                bad.append([i.get("index"), s.get("shard_id"),
                            fmt_num(s.get("failed_read_requests")),
                            fmt_num(s.get("failed_write_requests")),
                            str(errs[:1])[:160]])
    if not bad:
        return []
    return [Finding(
        "OPS-002", CAT, Severity.WARNING, T("rules.ops.r_ccr.01"),
        observed=T("rules.ops.r_ccr.02") % len(bad),
        impact=T("rules.ops.r_ccr.03"),
        recommend=T("rules.ops.r_ccr.04"),
        evidence=table(["index", "shard", "failed_read", "failed_write", "error"], bad),
        source="commercial/ccr_stats.json")]


def r_monitoring(ctx):
    """Whether cluster monitoring data exists (OPS-007, Info).

    If this cluster holds stack monitoring data (.monitoring-* or *stack_monitoring* data streams), it is monitoring itself
    (production should use a separate monitoring cluster). If there is none, the bundle cannot show whether the data goes to another cluster,
    so the report asks you to confirm. Legacy internal collection (xpack.monitoring.collection.enabled=true) is reported as well;
    from 9.5 the note adds that collecting with the monitoring plugin is deprecated and is removed in 10.0 (official deprecations).
    """
    import re as _re
    names = [n for n in ctx.indices_stats.keys() if _re.search(r"(^|\.)monitoring-|stack_monitoring", n)]
    legacy = str(ctx.setting("xpack.monitoring.collection.enabled")).lower() == "true"
    dep = T("rules.ops.r_monitoring.10") if legacy and ctx.version_tuple >= (9, 5, 0) else ""
    if names:
        return [Finding(
            "OPS-007", CAT, Severity.INFO, T("rules.ops.r_monitoring.01"),
            observed=T("rules.ops.r_monitoring.02")
                     % (len(names), T("rules.ops.r_monitoring.03") if legacy else "") + dep,
            impact=T("rules.ops.r_monitoring.04"),
            recommend=T("rules.ops.r_monitoring.05"),
            evidence=table(["index"], [[n] for n in sorted(names)[: ctx.t["top_n"]]]),
            source="indices_stats.json / cluster_settings.json")]
    return [Finding(
        "OPS-007", CAT, Severity.INFO, T("rules.ops.r_monitoring.06"),
        observed=T("rules.ops.r_monitoring.07") + dep,
        impact=T("rules.ops.r_monitoring.08"),
        recommend=T("rules.ops.r_monitoring.09"),
        source="indices_stats.json")]


RULES = [
    r_monitoring,
    r_license, r_snapshots, r_ilm, r_ml_transform, r_certificates,
    r_security_enabled, r_geoip, r_ccr,
]
