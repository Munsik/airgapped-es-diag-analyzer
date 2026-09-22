# -*- coding: utf-8 -*-
"""과다 샤딩(over-sharding)·소형 샤드 분석.

공식 기준(Size your shards): 샤드당 10GB~50GB, 2억건 미만, 불필요한 소형 샤드 회피,
롤오버는 max_primary_shard_size(50GB) 기준, 빈 인덱스 삭제.
"""

import collections
import math

from ..model import Finding, Severity, table
from ..util import dig, fmt_bytes, fmt_num, dicts, num, parse_bytes

CAT = "샤드·인덱스"
GB = 1024 ** 3
D_SHARDS = ("Size your shards",
            "https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards")


def _write_indices(ctx):
    """데이터 스트림의 현재 write index(아직 채워지는 중이라 크기 판정에서 제외)."""
    out = set()
    for ds in ctx.data_streams or []:
        idxs = ds.get("indices") or []
        if idxs:
            out.add(idxs[-1].get("index_name"))
    return out


def _replicas(ctx, name):
    try:
        return int(ctx.index_setting(name, "index.number_of_replicas") or 0)
    except (TypeError, ValueError):
        return 0


def r_index_oversharding(ctx):
    """인덱스 단위 과다 샤딩.

    대상: 사용자 인덱스 중 primary >= 2 이고 데이터 스트림 write index·searchable snapshot 이 아닌 것.
    fully mounted(cold) 인덱스는 크기는 정확하지만 shrink 할 수 없으므로 과다 건수만 집계해 원인 조치를 안내한다.
    판정: primary 샤드당 평균 크기 < oversharding_floor_shard_gb(공식 하한 10GB) 이면 과다.
    권장 primary 수 = max(1, ceil(primary 전체 크기 / oversharding_target_shard_gb(공식 상한 50GB)))
    — 샤드당 50GB 를 넘지 않는 최소 개수. 초과 샤드 = (현재 − 권장) × (1 + replica).
    초과 샤드 합계 >= oversharding_excess_warn 또는 전체 샤드 대비 비중 >= oversharding_excess_ratio_warn → 주의,
    그 외 대상이 있으면 참고.
    """
    target = ctx.t["oversharding_target_shard_gb"] * GB
    floor = ctx.t["oversharding_floor_shard_gb"] * GB
    skip = _write_indices(ctx)
    rows, excess_total, mounted_over = [], 0, 0
    for name, st in ctx.indices_stats.items():
        if ctx.is_system_index(name) or name in skip or ctx.is_partial_mount(name):
            continue
        if ctx.is_searchable_snapshot(name):
            # fully mounted 는 크기는 정확하지만 샤드 수를 바꿀 수 없다(스냅샷의 샤드 구성을 그대로 씀) → 건수만 집계
            pri = ctx.primary_count(name)
            size = num(st, "primaries", "store", "size_in_bytes")
            if pri >= 2 and size / float(pri) < floor:
                mounted_over += 1
            continue
        pri = ctx.primary_count(name)
        if pri < 2:
            continue
        size = num(st, "primaries", "store", "size_in_bytes")
        if size / float(pri) >= floor:
            continue            # 공식 권장 범위(10~50GB) 이상이면 과다 아님
        rec = max(1, int(math.ceil(size / float(target))))
        if pri > rec:
            rep = _replicas(ctx, name)
            excess = (pri - rec) * (1 + rep)
            excess_total += excess
            rows.append([name, pri, rep, fmt_bytes(size), fmt_bytes(size / float(pri)), rec, excess])
    if not rows:
        if mounted_over:
            return [Finding(
                "OVS-001", CAT, Severity.INFO, "마운트된 인덱스의 과다 샤딩(조치 불가, 원인 확인)",
                observed="cold 에 fully mounted 된 인덱스 중 샤드당 평균 %dGB 미만인 인덱스 %d개."
                         % (ctx.t["oversharding_floor_shard_gb"], mounted_over),
                impact="마운트된 인덱스는 스냅샷의 샤드 구성을 그대로 써서 shrink 할 수 없습니다. hot 단계의 롤오버·primary 설정이 원인입니다.",
                recommend="원본 데이터 스트림의 롤오버 조건(max_primary_shard_size)과 템플릿의 number_of_shards 를 조정하면 "
                          "이후 마운트되는 인덱스부터 개선됩니다. ILM 에서 searchable_snapshot 전에 shrink 를 두는 것도 방법입니다.",
                refs=[D_SHARDS], source="indices_stats.json / settings.json")]
        return []
    rows.sort(key=lambda r: -r[6])
    # 분모는 초과 샤드 계산과 같은 출처(샤드 목록)를 쓴다
    total = len([x for x in ctx.shards if (x.get("state") or "").upper() != "UNASSIGNED"]) or \
        ctx.health.get("active_shards") or 1
    ratio = excess_total / float(total)
    sev = Severity.WARNING if (excess_total >= ctx.t["oversharding_excess_warn"]
                               or ratio >= ctx.t["oversharding_excess_ratio_warn"]) else Severity.INFO
    return [Finding(
        "OVS-001", CAT, sev, "인덱스 단위 과다 샤딩",
        observed="데이터 양에 비해 primary 가 많은 인덱스 %d개. 줄일 수 있는 샤드(replica 포함) %s개, 전체 샤드의 %.0f%%.%s"
                 % (len(rows), fmt_num(excess_total), ratio * 100,
                    (" 같은 상태로 cold 에 마운트된 인덱스 %d개는 샤드 수를 바꿀 수 없어 원인(롤오버·primary 설정)을 고쳐야 합니다."
                     % mounted_over) if mounted_over else ""),
        impact="샤드마다 heap·파일 핸들·cluster state 오버헤드가 붙고, 검색은 샤드 수만큼 fan-out 됩니다. "
               "공식 권장 크기(샤드당 10~50GB)보다 작게 쪼개면 데이터 대비 비용만 커집니다. "
               "다만 검색 병렬성을 위해 의도적으로 나눈 검색용 인덱스는 예외일 수 있습니다.",
        recommend="신규 인덱스는 템플릿의 number_of_shards 를 줄이고, 기존 인덱스는 shrink API 로 primary 수를 줄입니다"
                  "(shrink 는 원래 수의 약수로만 가능, 쓰기 차단 필요). 시계열 데이터는 롤오버를 "
                  "max_primary_shard_size 기준으로 바꿉니다.",
        evidence=table(["index", "primary", "replica", "primary 크기", "샤드당 평균", "권장 최대 primary", "줄일 샤드"],
                       rows[: ctx.t["top_n"]]),
        refs=[D_SHARDS], source="indices_stats.json / indices.json / settings.json")]


def r_datastream_small_rollover(ctx):
    """데이터 스트림의 롤오버가 너무 잦아 작은 백킹 인덱스가 쌓이는지 확인한다.

    write index 와 partial(frozen) 마운트 백킹 인덱스(크기가 캐시 크기)를 제외한 백킹 인덱스가
    ds_min_backing_indices 개 이상이고, 그 primary 샤드당 크기의 중앙값이
    ds_small_backing_shard_gb 미만이면 주의. 롤오버가 max_age 로만 일어나고 있다는 전형적인 신호다.
    """
    rows = []
    for ds in ctx.data_streams or []:
        name = ds.get("name")
        if not name or str(name).startswith("."):
            continue
        idxs = [i.get("index_name") for i in dicts(ds.get("indices"))][:-1]   # write index 제외
        sizes = []
        for ix in idxs:
            if ctx.is_partial_mount(ix):
                continue        # partial(frozen) 마운트는 크기가 캐시 크기라 제외, fully mounted(cold)는 실제 크기라 포함
            pri = ctx.primary_count(ix) or 1
            b = dig(ctx.indices_stats, ix, "primaries", "store", "size_in_bytes")
            if b is not None:
                sizes.append(b / float(pri))
        if len(sizes) < ctx.t["ds_min_backing_indices"]:
            continue
        sizes.sort()
        med = sizes[len(sizes) // 2]
        if med < ctx.t["ds_small_backing_shard_gb"] * GB:
            rows.append([name, len(sizes) + 1, fmt_bytes(med), ds.get("ilm_policy") or "-",
                         fmt_num(sum(ctx.shard_count(ix) for ix in idxs))])
    if not rows:
        return []
    return [Finding(
        "OVS-002", CAT, Severity.WARNING, "데이터 스트림 롤오버 과다(작은 백킹 인덱스 누적)",
        observed="백킹 인덱스의 샤드당 크기 중앙값이 %dGB 미만인 데이터 스트림 %d개."
                 % (ctx.t["ds_small_backing_shard_gb"], len(rows)),
        impact="수집량에 비해 롤오버가 잦으면(대개 max_age 1d 단독 조건) 작은 인덱스와 샤드가 매일 쌓입니다. "
               "보존 기간이 길수록 샤드 수가 선형으로 늘어 샤드 한도(CLU-015)와 heap 을 잠식합니다.",
        recommend="ILM 롤오버 조건에 max_primary_shard_size: 50gb 를 두고 max_age 는 보조 조건으로 늘립니다. "
                  "과거 백킹 인덱스는 warm 단계의 shrink·force-merge 로 정리합니다.",
        evidence=table(["data stream", "백킹 인덱스 수", "샤드당 크기 중앙값", "ILM 정책", "백킹 샤드 수(write 제외)"],
                       rows[: ctx.t["top_n"]]),
        refs=[D_SHARDS], source="data_stream.json / indices_stats.json")]


def r_shard_size_distribution(ctx):
    """사용자 인덱스 primary 샤드의 크기 분포(<1GB / 1~10GB / 10~50GB / 50GB+)를 사실 그대로 보고한다.

    데이터가 있는(문서 1건 이상) 사용자 primary(partial 마운트·write index 제외, fully mounted 는 포함)가 oversharding_min_shards 개 이상이고,
    그중 10GB 미만 비중 >= oversharding_small_share_warn 이며 사용자 데이터 합계가 oversharding_min_data_gb 이상이면
    '클러스터 전반의 과다 샤딩 경향' 으로 주의. 조건에 못 미치면 분포만 참고로 표기.
    """
    skip = _write_indices(ctx)
    buckets = collections.OrderedDict([("<1GB", 0), ("1~10GB", 0), ("10~50GB", 0), ("50GB 초과", 0)])
    total_b, n, n_small = 0, 0, 0
    for s in ctx.shards:
        if (s.get("prirep") or "").lower() != "p":
            continue
        idx = s.get("index")
        if ctx.is_system_index(idx) or idx in skip or ctx.is_searchable_snapshot(idx):
            continue
        try:
            docs = int(str(num(s, "docs")))
            b = parse_bytes(s.get("store")) or 0      # 바이트 숫자 또는 1.2gb 같은 단위 표기 모두 처리
        except ValueError:
            continue
        if docs <= 0:
            continue
        n += 1
        total_b += b
        if b < GB:
            buckets["<1GB"] += 1
        elif b < 10 * GB:
            buckets["1~10GB"] += 1
        elif b <= 50 * GB:
            buckets["10~50GB"] += 1
        else:
            buckets["50GB 초과"] += 1
        if b < 10 * GB:
            n_small += 1
    if not n:
        return []
    ev = table(["샤드 크기 구간", "primary 수", "비중"],
               [[k, fmt_num(v), "%.0f%%" % (v * 100.0 / n)] for k, v in buckets.items()])
    share = n_small / float(n)
    if (n >= ctx.t["oversharding_min_shards"] and share >= ctx.t["oversharding_small_share_warn"]
            and total_b >= ctx.t["oversharding_min_data_gb"] * GB):
        return [Finding(
            "OVS-003", CAT, Severity.WARNING, "클러스터 전반의 과다 샤딩 경향",
            observed="데이터가 있는 사용자 primary %s개 중 %.0f%%가 공식 권장 하한(10GB) 미만입니다(사용자 데이터 %s)."
                     % (fmt_num(n), share * 100, fmt_bytes(total_b)),
            impact="개별 인덱스 문제가 아니라 인덱스 설계·롤오버 정책 전반이 데이터 양보다 많은 샤드를 만들고 있다는 신호입니다.",
            recommend="OVS-001(인덱스별)·OVS-002(데이터 스트림별) 대상부터 정리하고, 템플릿의 기본 primary 수와 "
                      "롤오버 기준을 재설계합니다.",
            evidence=ev, refs=[D_SHARDS], source="indices.json")]
    return [Finding("OVS-003", CAT, Severity.INFO, "사용자 샤드 크기 분포",
                    observed="데이터가 있는 사용자 primary %s개(데이터 %s), 10GB 미만 비중 %.0f%%."
                             % (fmt_num(n), fmt_bytes(total_b), share * 100),
                    evidence=ev, refs=[D_SHARDS], source="indices.json")]


RULES = [r_index_oversharding, r_datastream_small_rollover, r_shard_size_distribution]
