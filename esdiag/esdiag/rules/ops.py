# -*- coding: utf-8 -*-
"""운영/수명주기 판정 룰 (라이선스, 스냅샷, ILM/SLM, ML, 인증서)."""

import datetime

from ..context import _parse_iso
from ..model import Finding, Severity, table
from ..util import dig, fmt_bytes, fmt_num, dicts, num, items

CAT = "운영"
SEC = "보안·인증"


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
    """license.status != active → 치명. 만료까지 <= license_expiry_days_crit 일 → 치명, <= warn 일 → 주의, 그 외 정상. 기준 시각은 번들 수집 시각."""
    lic = ctx.license or {}
    if not lic:
        return []
    status = (lic.get("status") or "").lower()
    exp = _parse_iso(lic.get("expiry_date"))
    days = _days_until(ctx, exp)
    ev = table(["항목", "값"],
               [["type", lic.get("type")], ["status", status],
                ["issued_to", lic.get("issued_to")],
                ["expiry", lic.get("expiry_date") or "무기한"],
                ["max_nodes / max_resource_units",
                 "%s / %s" % (lic.get("max_nodes"), lic.get("max_resource_units"))]])
    if status not in ("active",):
        return [Finding("LIC-001", CAT, Severity.CRITICAL, "라이선스 비활성 상태",
                        observed="license status=%s (%s)" % (status, lic.get("type")),
                        impact="만료 시 보안·알림·ML 등 상용 기능이 중단되거나 읽기 전용으로 전환됩니다.",
                        recommend="라이선스를 갱신합니다.", evidence=ev, source="licenses.json")]
    if days is not None:
        if days <= ctx.t["license_expiry_days_crit"]:
            return [Finding("LIC-001", CAT, Severity.CRITICAL, "라이선스 만료 임박",
                            observed="%.0f일 후 만료 (%s)" % (days, lic.get("expiry_date")),
                            impact="만료되면 상용 기능이 비활성화됩니다.",
                            recommend="갱신 절차를 즉시 진행합니다.", evidence=ev,
                            source="licenses.json")]
        if days <= ctx.t["license_expiry_days_warn"]:
            return [Finding("LIC-001", CAT, Severity.WARNING, "라이선스 만료 예정",
                            observed="%.0f일 후 만료 (%s)" % (days, lic.get("expiry_date")),
                            impact="갱신 누락 시 기능 중단으로 이어집니다.",
                            recommend="갱신 일정을 확정합니다.", evidence=ev, source="licenses.json")]
    return [Finding("LIC-001", CAT, Severity.OK, "라이선스 정상",
                    observed="%s 라이선스, 만료까지 %s일." % (lic.get("type"),
                                                     "%.0f" % days if days else "무기한"),
                    evidence=ev, source="licenses.json")]


def r_snapshots(ctx):
    """저장소도 스냅샷도 없음 → 치명(SNP-001). FAILED/PARTIAL 스냅샷 존재 → 치명(SNP-002). 마지막 '성공(SUCCESS)' 스냅샷 경과(snapshot.json 에 시각이 없으면 SLM 정책의 last_success 시각) >= snapshot_age_hours_crit → 치명, >= warn → 주의, 그 외 정상(SNP-003, 진행 중·실패·부분 스냅샷은 RPO 산정에서 제외). 시각 정보가 있는데 성공 스냅샷이 없으면 치명. IN_PROGRESS 존재 → 참고(SNP-004). SLM 누적 실패 >= snapshot_failed_warn → 주의(SNP-005). SLM operation_mode != RUNNING → 주의(SNP-006). SLM 정책의 마지막 실패가 마지막 성공보다 최근이면 치명(SNP-007)."""
    out = []
    snaps = (ctx.snapshots or {}).get("snapshots") or []
    repos = ctx.repositories or []
    if not repos and not snaps:
        return [Finding(
            "SNP-001", CAT, Severity.CRITICAL, "스냅샷 저장소 미설정",
            observed="등록된 스냅샷 저장소가 없습니다.",
            impact="클러스터 장애·실수 삭제 시 복구 수단이 없습니다.",
            recommend="스냅샷 저장소를 등록하고 SLM 정책으로 주기적 백업을 구성합니다.",
            source="repositories.json")]
    failed = [s for s in snaps if (s.get("state") or "").upper() in ("FAILED", "PARTIAL")]
    in_prog = [s for s in snaps if (s.get("state") or "").upper() == "IN_PROGRESS"]
    # 복구 가능 시점(RPO)은 '마지막으로 성공한' 스냅샷 기준이다. 진행 중·실패·부분 스냅샷은 복구에 쓸 수 없다.
    latest = None
    for s in dicts(snaps):
        if (s.get("state") or "").upper() != "SUCCESS":
            continue
        t = num(s, "end_time_in_millis") or num(s, "start_time_in_millis")
        if t and (latest is None or t > latest[0]):
            latest = (t, s)
    has_times = any(num(s, "end_time_in_millis") or num(s, "start_time_in_millis") for s in dicts(snaps))
    # snapshot.json 이 목록 형식(시각 없음)이면 SLM 정책의 마지막 성공 시각을 RPO 근거로 쓴다
    rpo_source = "snapshot.json"
    if latest is None:
        for pname, pol in items(ctx.slm_policies):
            ls = pol.get("last_success") if isinstance(pol, dict) else None
            t = num(ls, "time") if isinstance(ls, dict) else 0
            if t and (latest is None or t > latest[0]):
                latest = (t, {"snapshot": "%s (SLM %s)" % (ls.get("snapshot_name"), pname)})
                rpo_source = "slm_policies.json"
    if failed:
        out.append(Finding(
            "SNP-002", CAT, Severity.CRITICAL, "실패/부분 스냅샷 존재",
            observed="FAILED 또는 PARTIAL 상태 스냅샷 %d건." % len(failed),
            impact="해당 시점의 백업은 복구에 사용할 수 없습니다.",
            recommend="failures 필드의 샤드 오류 원인(디스크, 저장소 접근, 샤드 미할당)을 확인합니다.",
            evidence=table(["snapshot", "repository", "state", "shards(실패/전체)"],
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
                "SNP-003", CAT, sev, "마지막 성공 스냅샷이 오래됨",
                observed="마지막 성공 스냅샷 %s (약 %.1f시간 전)" % (latest[1].get("snapshot"), age_h),
                impact="복구 가능 시점(RPO)이 그만큼 뒤처져 있습니다.",
                recommend="SLM 정책 동작 여부와 저장소 접근성을 확인합니다.",
                source=rpo_source))
        else:
            out.append(Finding(
                "SNP-003", CAT, Severity.OK, "최근 스냅샷 정상",
                observed="마지막 성공 스냅샷 %.1f시간 전 (총 %d건 보관, 근거 %s)." % (age_h, len(snaps), rpo_source),
                source=rpo_source))
    # SLM 정책별: 마지막 실패가 마지막 성공보다 최근이면 지금 실패 중인 정책
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
            "SNP-007", CAT, Severity.CRITICAL, "현재 실패 중인 SLM 정책",
            observed="마지막 실행이 실패한 SLM 정책 %d개(마지막 실패가 마지막 성공보다 최근)." % len(failing),
            impact="누적 실패 건수(SNP-005)와 달리 지금 백업이 만들어지지 않고 있다는 뜻입니다. RPO 가 계속 늘어납니다.",
            recommend="실패 details 의 원인(저장소 접근·권한·동시 스냅샷·샤드 상태)을 해소하고 _slm/policy/<id>/_execute 로 즉시 재실행합니다.",
            evidence=table(["정책", "마지막 실패", "마지막 성공", "실패 내용"], failing),
            source="slm_policies.json"))
    if latest is None and has_times and snaps:
        out.append(Finding(
            "SNP-003", CAT, Severity.CRITICAL, "성공한 스냅샷 없음",
            observed="스냅샷 %d건이 있으나 SUCCESS 상태가 없습니다." % len(snaps),
            impact="복구에 쓸 수 있는 백업이 없습니다.",
            recommend="실패 사유(SNP-002)와 저장소 접근성을 확인합니다.", source="snapshot.json"))
    if in_prog:
        out.append(Finding(
            "SNP-004", CAT, Severity.INFO, "진행 중인 스냅샷",
            observed="IN_PROGRESS 스냅샷 %d건." % len(in_prog),
            impact="스냅샷 중에는 I/O 부하가 증가하고 일부 작업(인덱스 삭제 등)이 제한됩니다.",
            recommend="장시간 정체되면 저장소 성능과 네트워크를 확인합니다.",
            source="snapshot.json"))
    # SLM
    st = ctx.slm_stats or {}
    if st:
        fails = num(st, "total_snapshots_failed")
        if fails >= ctx.t["snapshot_failed_warn"]:
            out.append(Finding(
                "SNP-005", CAT, Severity.WARNING, "SLM 스냅샷 실패 누적",
                observed="SLM 누적 실패 %s건 / 성공 %s건."
                         % (fmt_num(fails), fmt_num(st.get("total_snapshots_taken"))),
                impact="정책 기반 백업이 일부 실패하고 있습니다.",
                recommend="policy_stats 의 실패 정책과 마지막 실패 사유를 확인합니다.",
                evidence=table(["policy", "taken", "failed", "deleted"],
                               [[p.get("policy"), fmt_num(p.get("snapshots_taken")),
                                 fmt_num(p.get("snapshots_failed")),
                                 fmt_num(p.get("snapshots_deleted"))]
                                for p in dicts(st.get("policy_stats"))]),
                source="commercial/slm_stats.json"))
    slm_mode = (ctx.slm_status or {}).get("operation_mode")
    if slm_mode and slm_mode.upper() != "RUNNING":
        out.append(Finding(
            "SNP-006", CAT, Severity.WARNING, "SLM 중지 상태",
            observed="SLM operation_mode=%s" % slm_mode,
            impact="예약된 스냅샷이 수행되지 않습니다.",
            recommend="유지보수 목적이 아니라면 POST _slm/start 로 재개합니다.",
            source="commercial/slm_status.json"))
    return out


def r_ilm(ctx):
    """ILM operation_mode != RUNNING → 주의(ILM-001). ilm_explain 의 step=ERROR 또는 failed_step 존재 → 롤오버 관련 단계 실패가 있으면 치명, 그 외(삭제·축소·이동 단계, write index 삭제 실패 등)는 주의(ILM-002). ILM 미적용(managed=false) 사용자 인덱스 중 primary > 10GB → 참고(ILM-003)."""
    out = []
    mode = (ctx.ilm_status or {}).get("operation_mode")
    if mode and mode.upper() != "RUNNING":
        out.append(Finding(
            "ILM-001", CAT, Severity.WARNING, "ILM 중지 상태",
            observed="ILM operation_mode=%s" % mode,
            impact="롤오버·tier 이동·삭제가 수행되지 않아 디스크가 계속 증가합니다.",
            recommend="유지보수 목적이 아니라면 POST _ilm/start 로 재개합니다.",
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
        # 롤오버 단계가 멈추면 write index 가 계속 커진다(치명). 그 외 단계의 정체는 수명주기 지연(주의).
        rollover_steps = ("check-rollover-ready", "attempt-rollover", "update-rollover-lifecycle-date",
                          "wait-for-active-shards", "set-indexing-complete")
        stuck_rollover = [r for r in errors if str(r[3]) in rollover_steps]
        write_delete = [r for r in errors if "is the write index" in str(r[4])]
        sev = Severity.CRITICAL if stuck_rollover else Severity.WARNING
        note = []
        if stuck_rollover:
            note.append("롤오버 단계 실패 %d개" % len(stuck_rollover))
        if write_delete:
            note.append("데이터 스트림 write index 라 삭제하지 못한 경우 %d개" % len(write_delete))
        out.append(Finding(
            "ILM-002", CAT, sev, "ILM 오류 상태 인덱스",
            observed="ILM 오류 인덱스 %d개%s." % (len(errors), (" (" + ", ".join(note) + ")") if note else ""),
            impact="롤오버 단계가 실패하면 write index 가 조건을 넘어 계속 커집니다(샤드 크기·복구 시간 증가). "
                   "그 외 단계의 오류는 해당 인덱스의 tier 이동·축소·삭제가 멈춰 디스크와 샤드 수가 늘어납니다. "
                   "write index 삭제 실패는 수집량이 적어 롤오버되지 않은 데이터 스트림에서 흔히 생깁니다.",
            recommend="실패 스텝의 사유를 해소한 뒤 POST <index>/_ilm/retry 를 수행합니다. write index 삭제 실패는 "
                      "데이터 스트림을 수동 롤오버(POST <data stream>/_rollover)하면 이전 인덱스가 정상적으로 삭제됩니다. "
                      "롤오버 실패는 alias·is_write_index 설정과 샤드 할당 상태를 먼저 확인합니다.",
            evidence=table(["index", "policy", "phase", "failed_step", "reason"],
                           errors[: ctx.t["top_n"]]),
            source="commercial/ilm_explain.json"))
    # 관리되지 않는 사용자 인덱스
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
            "ILM-003", CAT, Severity.INFO, "ILM 미적용 대형 인덱스",
            observed="ILM 이 적용되지 않은 10GB 이상 인덱스 %d개." % len(unmanaged),
            impact="보존 정책이 수동 관리에 의존하게 되어, 담당자 변경 시 무한 증가하기 쉽습니다.",
            recommend="롤오버·보존 기간이 필요한 데이터라면 ILM 정책과 데이터 스트림 적용을 검토합니다.",
            evidence=table(["index", "크기"], [r[:2] for r in unmanaged[: ctx.t["top_n"]]]),
            source="commercial/ilm_explain.json"))
    return out


def r_ml_transform(ctx):
    """transform state 가 failed/aborting → 주의(ML-001). 이상탐지 job state=failed → 주의(ML-002)."""
    out = []
    tstats = (ctx.transform_stats or {}).get("transforms") or []
    bad_t = [t for t in tstats if (t.get("state") or "").lower() in ("failed", "aborting")]
    if bad_t:
        out.append(Finding(
            "ML-001", CAT, Severity.WARNING, "Transform 실패 상태",
            observed="failed 상태 transform %d건." % len(bad_t),
            impact="집계 대상 인덱스가 갱신되지 않아 대시보드/탐지 로직이 과거 데이터로 동작합니다.",
            recommend="reason 필드를 확인하고 원인 해소 후 _start 합니다.",
            evidence=table(["id", "state", "reason"],
                           [[t.get("id"), t.get("state"), str(t.get("reason"))[:160]]
                            for t in bad_t[: ctx.t["top_n"]]]),
            source="commercial/transform_stats.json"))
    # 이상탐지 job
    jobs = (ctx.ml_anomaly or {}).get("jobs") or []
    bad_j = []
    for j in jobs:
        if isinstance(j, dict) and (j.get("state") or "").lower() in ("failed",):
            bad_j.append([j.get("job_id"), j.get("state")])
    if bad_j:
        out.append(Finding(
            "ML-002", CAT, Severity.WARNING, "ML 이상탐지 job 실패",
            observed="failed 상태 job %d건." % len(bad_j),
            impact="이상 탐지 결과가 생성되지 않습니다.",
            recommend="job 로그와 datafeed 상태를 확인합니다.",
            evidence=table(["job_id", "state"], bad_j), source="commercial/ml_anomaly_detectors.json"))
    return out


def r_certificates(ctx):
    """ssl_certs.json 의 인증서 만료까지 <= cert_expiry_days_crit 일 → 치명, <= warn 일 → 주의, 그 외 정상. 기준 시각은 번들 수집 시각."""
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
               c.get("expiry"), "%.0f일" % d]
        rows.append(row)
        if d <= ctx.t["cert_expiry_days_crit"]:
            rows_crit.append(row)
        elif d <= ctx.t["cert_expiry_days_warn"]:
            rows_warn.append(row)
    if rows_crit:
        return [Finding("SEC-001", SEC, Severity.CRITICAL, "TLS 인증서 만료 임박",
                        observed="%d일 이내 만료 인증서 %d건." % (ctx.t["cert_expiry_days_crit"],
                                                        len(rows_crit)),
                        impact="만료되면 노드 간 transport 통신과 HTTPS 접속이 끊겨 "
                               "클러스터가 분리되거나 전면 중단됩니다.",
                        recommend="갱신 일정을 즉시 확정하고, 갱신 절차(노드 롤링 반영)를 준비합니다.",
                        evidence=table(["path", "subject", "expiry", "남은 기간"], rows_crit),
                        source="ssl_certs.json")]
    if rows_warn:
        return [Finding("SEC-001", SEC, Severity.WARNING, "TLS 인증서 만료 예정",
                        observed="%d일 이내 만료 인증서 %d건." % (ctx.t["cert_expiry_days_warn"],
                                                        len(rows_warn)),
                        impact="갱신 누락 시 통신 중단으로 직결됩니다.",
                        recommend="갱신 일정을 등록합니다.",
                        evidence=table(["path", "subject", "expiry", "남은 기간"], rows_warn),
                        source="ssl_certs.json")]
    return [Finding("SEC-001", SEC, Severity.OK, "TLS 인증서 만료 여유",
                    observed="수집된 인증서 %d건 모두 %d일 이상 남았습니다."
                             % (len(rows), ctx.t["cert_expiry_days_warn"]),
                    source="ssl_certs.json")]


def r_security_enabled(ctx):
    """xpack security.enabled=false → 치명, 그 외 정상."""
    sec = dig(ctx.xpack, "security", default={}) or {}
    if not sec:
        return []
    if sec.get("enabled") is False:
        return [Finding("SEC-002", SEC, Severity.CRITICAL, "보안 기능 비활성화",
                        observed="xpack.security.enabled = false",
                        impact="인증·권한·전송 암호화가 없는 상태로, 네트워크에 접근 가능한 누구나 "
                               "데이터를 읽고 삭제할 수 있습니다.",
                        recommend="보안 기능을 활성화하고 TLS 와 역할 기반 접근제어를 구성합니다.",
                        source="commercial/xpack.json")]
    return [Finding("SEC-002", SEC, Severity.OK, "보안 기능 활성화",
                    observed="xpack security enabled.", source="commercial/xpack.json")]


def r_geoip(ctx):
    """GeoIP failed_downloads 또는 expired_databases > 0 → 참고(폐쇄망에서는 정상일 수 있음)."""
    st = dig(ctx.geoip, "stats", default={}) or {}
    failed = num(st, "failed_downloads")
    expired = num(st, "expired_databases")
    if not failed and not expired:
        return []
    return [Finding(
        "OPS-001", CAT, Severity.INFO, "GeoIP 데이터베이스 갱신 이슈",
        observed="실패 다운로드 %s건, 만료 DB %s건." % (fmt_num(failed), fmt_num(expired)),
        impact="폐쇄망에서는 GeoIP 자동 갱신이 불가능하므로 정상적인 현상일 수 있습니다. "
               "다만 geoip processor 를 쓰는 파이프라인은 위치 정보가 비어 들어갑니다.",
        recommend="폐쇄망이라면 ingest.geoip.downloader.enabled=false 로 두고 "
                  "DB 파일을 수동 배포하거나, geoip processor 사용 여부를 재검토합니다.",
        source="geoip_stats.json")]


def r_ccr(ctx):
    """CCR follower 샤드에 read_exceptions 또는 failed_read/write_requests 가 있으면 주의."""
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
        "OPS-002", CAT, Severity.WARNING, "CCR 복제 오류",
        observed="오류가 있는 follower 샤드 %d개." % len(bad),
        impact="원격 클러스터 복제가 지연되거나 중단되어 DR 사이트 데이터가 뒤처집니다.",
        recommend="원격 연결 상태, leader 인덱스의 soft delete 보존, 권한을 확인합니다.",
        evidence=table(["index", "shard", "failed_read", "failed_write", "error"], bad),
        source="commercial/ccr_stats.json")]


def r_monitoring(ctx):
    """클러스터 모니터링 데이터 존재 여부(OPS-007, 참고).

    이 클러스터 안에 스택 모니터링 데이터(.monitoring-* 또는 *stack_monitoring* 데이터 스트림)가 있으면 자기 자신에게
    수집하는 구성이다(운영 환경은 별도 모니터링 클러스터 권장). 없으면 별도 클러스터로 보내는지 번들만으로 알 수 없으므로
    확인을 안내한다. 레거시 내부 수집(xpack.monitoring.collection.enabled=true)도 함께 표기한다.
    """
    import re as _re
    names = [n for n in ctx.indices_stats.keys() if _re.search(r"(^|\.)monitoring-|stack_monitoring", n)]
    legacy = str(ctx.setting("xpack.monitoring.collection.enabled")).lower() == "true"
    if names:
        return [Finding(
            "OPS-007", CAT, Severity.INFO, "클러스터 자신에게 모니터링 데이터 수집",
            observed="모니터링 인덱스·데이터 스트림 %d개가 이 클러스터 안에 있습니다%s."
                     % (len(names), " (레거시 내부 수집 사용)" if legacy else ""),
            impact="장애 시 모니터링 데이터도 함께 볼 수 없게 되고, 모니터링 색인이 운영 부하에 더해집니다.",
            recommend="운영 환경은 별도 모니터링 클러스터로 수집하는 구성을 권장합니다(Elastic Agent·Metricbeat 기반).",
            evidence=table(["index"], [[n] for n in sorted(names)[: ctx.t["top_n"]]]),
            source="indices_stats.json / cluster_settings.json")]
    return [Finding(
        "OPS-007", CAT, Severity.INFO, "모니터링 구성 확인 필요",
        observed="이 클러스터 안에서 스택 모니터링 데이터가 보이지 않습니다.",
        impact="별도 모니터링 클러스터로 수집 중이면 정상입니다. 모니터링이 없다면 장애 전후의 추세(heap·GC·rejection·디스크)를 "
               "확인할 수 없어 원인 분석과 용량 계획이 어렵습니다. 이 리포트의 누적 통계 한계도 모니터링으로만 보완됩니다.",
        recommend="별도 모니터링 클러스터 수집 여부를 확인합니다(ECH 는 배포의 Logs and metrics 설정). 없다면 구성합니다.",
        source="indices_stats.json")]


RULES = [
    r_monitoring,
    r_license, r_snapshots, r_ilm, r_ml_transform, r_certificates,
    r_security_enabled, r_geoip, r_ccr,
]
