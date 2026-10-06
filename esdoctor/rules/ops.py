# -*- coding: utf-8 -*-
"""Operations and lifecycle rules (license, snapshots, ILM/SLM, ML, certificates)."""

import datetime
import re

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
    """license.status != active → Critical. A trial license (30 days at most) → Warning while it runs. Time to expiry <= license_expiry_days_crit days → Critical, <= warn days → Warning, otherwise OK. The reference time is the bundle collection time."""
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
    if days is not None and str(lic.get("type") or "").lower() == "trial":
        # a trial always lasts 30 days at most; when it ends the cluster reverts to Basic
        return [Finding("LIC-001", CAT, Severity.WARNING, T("rules.ops.r_license.17"),
                        observed=T("rules.ops.r_license.08") % (days, lic.get("expiry_date")),
                        impact=T("rules.ops.r_license.18"),
                        recommend=T("rules.ops.r_license.19"), evidence=ev, source="licenses.json")]
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
                    observed=(T("rules.ops.r_license.15") % (lic.get("type"), "%.0f" % days)) if days is not None
                    else (T("rules.ops.r_license.16") % lic.get("type")),
                    evidence=ev, source="licenses.json")]


def r_snapshots(ctx):
    """No repository and no snapshot → Critical (SNP-001; skipped when repositories.json is missing or an error body). FAILED/PARTIAL snapshot present → Warning, and Critical if a later successful snapshot is known not to exist (SNP-002; snapshots listed without times stay Warning). Age of the last SUCCESS snapshot (the SLM policy's last_success time if snapshot.json has no time) >= snapshot_age_hours_crit → Critical, >= warn → Warning, otherwise OK (SNP-003; in-progress, failed and partial snapshots are excluded from the RPO calculation). No snapshot in SUCCESS state and no SLM success (snapshot states decide; a registered repository with no snapshot counts) → Critical; a SUCCESS snapshot listed without times gives no age. IN_PROGRESS present → Info (SNP-004). Cumulative SLM failures >= snapshot_failed_warn → Info (SNP-005, lifetime counter). SLM operation_mode != RUNNING while SLM policies exist → Warning (SNP-006). SLM policy whose last failure is more recent than its last success → Warning, Critical when it has failed 5 times in a row (invocations_since_last_success, the SLM health threshold) or its last success is older than snapshot_age_hours_crit (SNP-007)."""
    out = []
    snaps = (ctx.snapshots or {}).get("snapshots") or []
    repos = ctx.repositories or []
    repos_known = ctx.b.json("repositories.json") is not None    # missing or an error body (for example 403): cannot be checked
    if repos_known and not repos and not snaps:
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
        # The diagnostics list snapshots with verbose=false, which carries no times. Without a time it cannot be told whether a
        # success came later, so the result stays Warning (SNP-007 still reports an SLM policy that is failing now).
        recovered = bool(latest and f_last and latest[0] > f_last) or not f_last
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
            inv = pol.get("invocations_since_last_success")
            if inv is None:
                inv = dig(pol, "stats", "invocations_since_last_success")
            age_h = (_now(ctx).timestamp() * 1000 - ts) / 3600000.0 if ts else None
            # ES's SLM health indicator turns yellow after slm.health.failed_snapshot_warn_threshold (5) failures in a row
            bad = (inv is not None and num(inv) >= 5) or age_h is None or age_h >= ctx.t["snapshot_age_hours_crit"]
            failing.append([pname, (lf or {}).get("time_string") or tf, (ls or {}).get("time_string") or "-",
                            "-" if inv is None else fmt_num(inv), str((lf or {}).get("details") or "")[:160], bad])
    if failing:
        out.append(Finding(
            "SNP-007", CAT, Severity.CRITICAL if any(r[5] for r in failing) else Severity.WARNING, T("rules.ops.r_snapshots.16"),
            observed=T("rules.ops.r_snapshots.17") % len(failing),
            impact=T("rules.ops.r_snapshots.18"),
            recommend=T("rules.ops.r_snapshots.19"),
            evidence=table([T("rules.ops.r_snapshots.20"), T("rules.ops.r_snapshots.21"), T("rules.ops.r_snapshots.22"),
                            "invocations_since_last_success", T("rules.ops.r_snapshots.23")], [r[:5] for r in failing]),
            source="commercial/slm_policies.json"))
    any_success = any((s.get("state") or "").upper() == "SUCCESS" for s in dicts(snaps))
    if latest is None and not any_success and (snaps or (repos and ctx.b.json("snapshot.json") is not None)):
        # decided on the snapshot states (the diagnostics list snapshots with verbose=false, without times)
        out.append(Finding(
            "SNP-003", CAT, Severity.CRITICAL, T("rules.ops.r_snapshots.24"),
            observed=(T("rules.ops.r_snapshots.25") % len(snaps)) if snaps else T("rules.ops.r_snapshots.39"),
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
            # Cumulative over the life of the cluster (kept in cluster metadata), so history alone is Info; SNP-007 covers current failures.
            out.append(Finding(
                "SNP-005", CAT, Severity.INFO, T("rules.ops.r_snapshots.32"),
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
    if slm_mode and slm_mode.upper() != "RUNNING" and ctx.slm_policies:     # no policy: nothing is scheduled (ES reports green)
        out.append(Finding(
            "SNP-006", CAT, Severity.WARNING, T("rules.ops.r_snapshots.36"),
            observed="SLM operation_mode=%s" % slm_mode,
            impact=T("rules.ops.r_snapshots.37"),
            recommend=T("rules.ops.r_snapshots.38"),
            source="commercial/slm_status.json"))
    return out


def r_ilm(ctx):
    """ILM operation_mode != RUNNING → Warning (ILM-001). ilm_explain with step=ERROR or a failed_step → Critical if a rollover-related step failed, otherwise (delete, shrink or migrate steps, failure to delete a write index, etc.) Warning (ILM-002). User indices without ILM (managed=false) and primary > 10GB → Info (ILM-003); indices managed by data stream lifecycle are not counted as unmanaged. A rollover-step error on an index that is no longer written (rolled over) is Warning, not Critical."""
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
        # Only an index that is still written can grow: a rollover error on an old index (for example after a manual alias swap) is a delay
        # "rollover alias does not point to index": no writes reach the index through the alias, so it cannot keep growing
        stuck_rollover = [r for r in errors if str(r[3]) in rollover_steps and not ctx.rolled_over(r[0])
                          and "does not point to index" not in str(r[4])]
        write_delete = [r for r in errors if re.search(r"is the( failure store)? write index", str(r[4]))]
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
        if isinstance(ex, dict) and ex.get("managed") is False and not ctx.dlm_managed(name):
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
    """transform state failed/aborting → Warning (ML-001). Anomaly detection job state=failed → Warning (ML-002). The job state is in
    the job stats (commercial/ml_stats.json, GET _ml/anomaly_detectors/_stats); the job config file has no state."""
    out = []
    tstats = (ctx.transform_stats or {}).get("transforms") or []
    bad_t = [t for t in tstats if (t.get("state") or "").lower() in ("failed", "aborting")]
    if bad_t:
        out.append(Finding(
            "ML-001", CAT, Severity.WARNING, T("rules.ops.r_ml_transform.01"),
            observed=T("rules.ops.r_ml_transform.02") % len(bad_t)
                     + ((T("rules.ops.r_ml_transform.09") % len(tstats)) if num(ctx.transform_stats, "count") > len(tstats) else ""),
            impact=T("rules.ops.r_ml_transform.03"),
            recommend=T("rules.ops.r_ml_transform.04"),
            evidence=table(["id", "state", "reason"],
                           [[t.get("id"), t.get("state"), str(t.get("reason"))[:160]]
                            for t in bad_t[: ctx.t["top_n"]]]),
            source="commercial/transform_stats.json"))
    # Anomaly detection jobs
    jobs = (ctx.ml_job_stats or {}).get("jobs") or (ctx.ml_anomaly or {}).get("jobs") or []
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
            evidence=table(["job_id", "state"], bad_j), source="commercial/ml_stats.json"))
    return out


def r_certificates(ctx):
    """Time to certificate expiry in ssl_certs.json <= cert_expiry_days_crit days (already expired included) → Critical, <= warn days → Warning, otherwise OK.
    When every certificate in the Critical range is a CA in a trust store (has_private_key=false), it is Warning: it affects only the chains it signs.
    On ECH/ECE/ECK the certificates are platform-managed and the advice says so. The reference time is the bundle collection time."""
    certs = ctx.ssl_certs or []
    if not certs:
        return []
    rows_crit, rows_warn, rows = [], [], []
    for c in certs:
        exp = _parse_iso(c.get("expiry"))
        d = _days_until(ctx, exp)
        if d is None:
            continue
        ca = str(c.get("has_private_key")).lower() == "false"      # a CA in a trust store, not the node's own certificate
        row = [c.get("path") or c.get("alias"), (c.get("subject_dn") or "")[:80],
               c.get("expiry"), T("rules.ops.r_certificates.01") % d + (T("rules.ops.r_certificates.12") if ca else ""), ca, d]
        rows.append(row)
        if d <= ctx.t["cert_expiry_days_crit"]:
            rows_crit.append(row)
        elif d <= ctx.t["cert_expiry_days_warn"]:
            rows_warn.append(row)
    orch = (T("rules.ops.r_certificates.13") % ctx.deployment) if ctx.orchestrated else ""
    if rows_crit:
        expired = len([r for r in rows_crit if r[5] < 0])
        node_cert = any(not r[4] for r in rows_crit)
        return [Finding("SEC-001", SEC, Severity.CRITICAL if node_cert else Severity.WARNING, T("rules.ops.r_certificates.02"),
                        observed=T("rules.ops.r_certificates.03") % (ctx.t["cert_expiry_days_crit"], len(rows_crit))
                                 + ((T("rules.ops.r_certificates.14") % expired) if expired else ""),
                        impact=T("rules.ops.r_certificates.04") if node_cert else T("rules.ops.r_certificates.15"),
                        recommend=T("rules.ops.r_certificates.05") + orch,
                        evidence=table(["path", "subject", "expiry", T("rules.ops.r_certificates.06")], [r[:4] for r in rows_crit]),
                        source="ssl_certs.json")]
    if rows_warn:
        return [Finding("SEC-001", SEC, Severity.WARNING, T("rules.ops.r_certificates.07"),
                        observed=T("rules.ops.r_certificates.03") % (ctx.t["cert_expiry_days_warn"],
                                                        len(rows_warn)),
                        impact=T("rules.ops.r_certificates.08") if any(not r[4] for r in rows_warn) else T("rules.ops.r_certificates.15"),
                        recommend=T("rules.ops.r_certificates.09") + orch,
                        evidence=table(["path", "subject", "expiry", T("rules.ops.r_certificates.06")], [r[:4] for r in rows_warn]),
                        source="ssl_certs.json")]
    return [Finding("SEC-001", SEC, Severity.OK, T("rules.ops.r_certificates.10"),
                    observed=T("rules.ops.r_certificates.11")
                             % (len(rows), ctx.t["cert_expiry_days_warn"]),
                    source="ssl_certs.json")]


def _http_host(n):
    """Where HTTP listens: the bound/publish address reported in nodes info, else http.host, then network.host, then the default
    (_local_, loopback). http.host overrides network.host for HTTP."""
    for path in (("http", "bound_address"), ("http", "publish_address")):
        v = dig(n.info, *path)
        if v:
            return ",".join(str(x) for x in v) if isinstance(v, list) else str(v)
    v = n.setting("http.host") or n.setting("network.host")
    if isinstance(v, list):
        v = ",".join(str(x) for x in v)
    return str(v or "_local_")


def _is_loopback(h):
    parts = [p.strip().strip("[]") for p in str(h).split(",") if p.strip()]
    return bool(parts) and all(p.startswith(("127.", "localhost", "::1", "_local_")) for p in parts)


def r_security_enabled(ctx):
    """xpack security.enabled=false → Critical, or Warning when every node binds both HTTP and transport only to loopback (nodes info
    required; without it the addresses are unknown and it stays Critical). Otherwise OK."""
    sec = dig(ctx.xpack, "security", default={}) or {}
    if not sec:
        return []
    if sec.get("enabled") is False:
        hosts = [_http_host(n) for n in ctx.nodes]
        # unknown when nodes info is missing; transport has no authentication either with security off, so it must be loopback too
        known = bool(ctx.nodes) and all((n.info or {}).get("http") or (n.info or {}).get("settings") for n in ctx.nodes)
        tports = [dig(n.info, "transport", "bound_address") or n.info.get("transport_address") for n in ctx.nodes]
        tport_loop = all(t and _is_loopback(",".join(t) if isinstance(t, list) else t) for t in tports)
        loopback = known and bool(hosts) and all(_is_loopback(h) for h in hosts) and tport_loop
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
    """GeoIP expired_databases > 0, or failed_downloads > 0 with no database downloaded → Info (can be normal in an air-gapped network).

    failed_downloads is cumulative. With databases present, none expired and successful downloads, a past failed download was
    retried successfully, so nothing is reported. An expired database (not updated for 30 days) is no longer used by the geoip
    processor, so lookups against it add no location fields.
    """
    st = dig(ctx.geoip, "stats", default={}) or {}
    failed = num(st, "failed_downloads")
    expired = num(st, "expired_databases")
    if not expired and (not failed or (num(st, "databases_count") and num(st, "successful_downloads"))):
        return []
    return [Finding(
        "OPS-001", CAT, Severity.INFO, T("rules.ops.r_geoip.01"),
        observed=T("rules.ops.r_geoip.02") % (fmt_num(failed), fmt_num(expired)),
        impact=T("rules.ops.r_geoip.03"),
        recommend=T("rules.ops.r_geoip.04"),
        source="geoip_stats.json")]


def r_ccr(ctx):
    """CCR follower shards with read_exceptions (current errors) or a fatal_exception → Warning (OPS-002). failed_read/write_requests
    are cumulative per follower task, so a shard with only those counters is listed at Info (a past remote restart leaves them)."""
    follow = (ctx.ccr_stats or {}).get("follow_stats") or {}
    idxs = follow.get("indices") or []
    bad, live = [], False
    for i in idxs:
        for s in dicts(i.get("shards")):
            errs = s.get("read_exceptions") or []
            live = live or bool(errs) or bool(s.get("fatal_exception"))
            if errs or s.get("fatal_exception") or s.get("failed_read_requests") or s.get("failed_write_requests"):
                bad.append([i.get("index"), s.get("shard_id"),
                            fmt_num(s.get("failed_read_requests")),
                            fmt_num(s.get("failed_write_requests")),
                            str(errs[:1])[:160]])
    if not bad:
        return []
    return [Finding(
        "OPS-002", CAT, Severity.WARNING if live else Severity.INFO, T("rules.ops.r_ccr.01"),
        observed=T("rules.ops.r_ccr.02") % len(bad),
        impact=T("rules.ops.r_ccr.03"),
        recommend=T("rules.ops.r_ccr.04"),
        evidence=table(["index", "shard", "failed_read", "failed_write", "error"], bad),
        source="commercial/ccr_stats.json")]


def r_monitoring(ctx):
    """Whether cluster monitoring data exists (OPS-007, Info).

    If this cluster holds stack monitoring data (.monitoring-* or *stack_monitoring* data streams), it is monitoring itself
    (production should use a separate monitoring cluster). If there is none, the bundle cannot show whether the data goes to another cluster,
    so the report asks you to confirm. Legacy internal collection (xpack.monitoring.collection.enabled=true, in cluster settings or
    elasticsearch.yml) is reported as well, with a note that it has been deprecated since 7.16; from 9.5 the note adds that it is
    removed in 10.0 (official deprecations).
    """
    import re as _re
    names = [n for n in ctx.indices_stats.keys() if _re.search(r"(^|\.)monitoring-|stack_monitoring", n)]
    key = "xpack.monitoring.collection.enabled"
    legacy = str(ctx.setting(key)).lower() == "true" or any(str(n.setting(key)).lower() == "true" for n in ctx.nodes)
    dep = (T("rules.ops.r_monitoring.10") if ctx.version_tuple >= (9, 5, 0) else T("rules.ops.r_monitoring.11")) if legacy else ""
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
