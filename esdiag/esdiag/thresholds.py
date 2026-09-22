"""모든 판정 기준(decision point) 임계값.

--thresholds my.json 으로 일부만 덮어쓸 수 있다(딥 머지).
기본값은 Elastic 공식 가이드와 실무 운영 경험에서 통용되는 값이며,
클러스터 성격(검색/로그/보안)에 따라 조정해 쓰는 것을 전제로 한다.
"""

DEFAULTS = {
    # --- JVM ---
    "heap_used_pct_warn": 75,                        # [도구] 수집 순간 heap 사용률
    "heap_used_pct_crit": 85,                        # [도구] 수집 순간 heap 사용률
    "heap_max_bytes_crit": 32 * 1024 ** 3,           # [공식] compressed oops 경계(32GB 미만 권장)
    "heap_vs_ram_pct_warn": 50,                      # [공식] heap <= 전체 메모리의 50%
    "heap_vs_ram_tolerance_pct": 2,                  # [도구] 반올림·adjusted_total 오차 허용
    "old_gc_time_ratio_warn": 0.02,                  # [도구] old GC 누적 시간 / uptime
    "old_gc_time_ratio_crit": 0.05,                  # [도구] old GC 누적 시간 / uptime
    "young_gc_time_ratio_warn": 0.05,                # [도구] young GC 누적 시간 / uptime
    "old_gc_per_hour_warn": 6,                       # [도구] 시간당 old GC 횟수
    "old_gc_per_hour_crit": 30,                      # [도구] 시간당 old GC 횟수

    # --- OS / 프로세스 ---
    "load_per_cpu_warn": 1.0,                        # [도구] load15 / CPU 코어
    "load_per_cpu_crit": 1.5,                        # [도구] load15 / CPU 코어
    "fd_used_pct_warn": 70,                          # [도구] 열린 파일 / 최대(공식 최소 한도는 65,535)
    "cgroup_throttle_ratio_warn": 0.01,              # [도구] throttled / elapsed periods
    "cgroup_throttle_ratio_crit": 0.05,              # [도구] throttled / elapsed periods
    "uptime_short_hours": 6,                         # [도구] 최근 재기동 판단

    # --- 디스크 ---
    "disk_watermark_low_default": "85%",             # [공식] ES 기본값(설정 파일이 없을 때만 사용)
    "disk_watermark_high_default": "90%",            # [공식] ES 기본값(설정 파일이 없을 때만 사용)
    "disk_watermark_flood_default": "95%",           # [공식] ES 기본값(설정 파일이 없을 때만 사용)
    "disk_watermark_flood_frozen_default": "95%",     # [공식] frozen 전용 노드 flood stage
    "disk_watermark_flood_frozen_headroom_default": "20GB",  # [공식] frozen flood max_headroom
    "disk_imbalance_pct_warn": 15,                   # [도구] 노드 간 디스크 사용률 편차(%p)
    "disk_low_margin_pct": 10,                       # [도구] 실효 low 워터마크까지 남은 %p

    # --- 스레드풀 / 브레이커 ---
    "rejected_crit": 1000,                           # [도구] 누적 rejection 합계
    "breaker_tripped_warn": 1,                       # [도구] breaker 발동 횟수(1 = 이력 존재)

    # --- 샤드 / 인덱스 ---
    "shards_per_gb_heap_warn": 20,                   # [공식] heap 1GB당 샤드 20개(8.3 미만 전용)
    "shards_per_gb_heap_crit": 30,                   # [도구] 8.3 미만 전용
    "max_shards_per_node_headroom_pct_warn": 80,     # [도구] cluster.max_shards_per_node 대비 사용률
    "shard_size_gb_warn": 50,                        # [공식] 샤드 10~50GB
    "shard_size_gb_crit": 200,                       # [도구] 복구 시간 기준 상한
    "small_shard_mb": 1024,                          # [도구] 소형 샤드 기준
    "small_shard_count_warn": 50,                    # [도구]
    "small_shard_ratio_warn": 0.5,                   # [도구]
    "deleted_docs_ratio_warn": 0.25,                 # [도구]
    "segments_per_shard_warn": 50,                   # [도구]
    "merge_throttle_ratio_warn": 0.05,               # [도구]
    "search_latency_ms_warn": 200,                   # [도구] 인덱스 평균 query 지연
    "search_latency_ms_crit": 1000,                  # [도구] 인덱스 평균 query 지연
    "index_latency_ms_warn": 50,                     # [도구] 문서당 평균 색인 시간
    "index_latency_ms_crit": 200,                    # [도구] 문서당 평균 색인 시간
    "min_query_total_for_latency": 100,              # [도구] 표본이 적으면 판정 제외
    "fielddata_heap_pct_warn": 10,                   # [도구] fielddata / heap

    # --- 클러스터 ---
    "pending_tasks_warn": 10,                        # [도구]
    "pending_tasks_crit": 100,                       # [도구]
    "max_task_wait_ms_warn": 30000,                  # [도구]
    "long_running_task_ms_warn": 300000,             # [도구] 5분

    # --- 운영/수명주기 ---
    "license_expiry_days_warn": 90,                  # [도구]
    "license_expiry_days_crit": 30,                  # [도구]
    "cert_expiry_days_warn": 90,                     # [도구]
    "cert_expiry_days_crit": 30,                     # [도구]
    "snapshot_age_hours_warn": 36,                   # [도구] 최근 스냅샷 경과 시간
    "snapshot_age_hours_crit": 168,                  # [도구] 7일
    "snapshot_failed_warn": 1,                       # [도구]
    "ingest_failed_warn": 1,                         # [도구]

    # --- Hot threads ---
    "hot_thread_pct_warn": 50,                       # [도구] 단일 스레드 CPU%

    # --- 로그(local/remote 모드) ---
    "log_scan_bytes": 8 * 1024 ** 2,                 # [도구] 로그 파일당 스캔 크기(끝부분)

    # --- 공식 가이드 기준(production guidance) ---
    "docs_per_shard_warn": 200000000,                # [공식] 샤드당 2억건 미만 권장
    "docs_per_shard_crit": 1500000000,               # [도구] Lucene 한계(2,147,483,519) 접근 경보
    "indices_per_gb_master_heap": 3000,              # [공식] 마스터 heap 1GB당 인덱스 3000개
    "mapping_heap_pct_warn": 50,                     # [도구] 매핑 오버헤드 추정 / heap
    "heap_baseline_bytes": 512 * 1024 ** 2,          # [공식] 필드 매퍼 산정 시 추가 여유 0.5GB
    "empty_index_count_warn": 5,                     # [도구]
    "heavy_index_docs": 10000000,                    # [도구] 대량 색인 인덱스 기준
    "index_buffer_per_shard_warn": 32 * 1024 ** 2,   # [도구] 쓰기 대상 샤드당(공식 상한은 512MB)
    "open_contexts_warn": 100,                       # [도구]
    "search_heavy_query_total": 100000,              # [도구] 검색 부하 인덱스 기준
    "preload_index_count_warn": 5,                   # [도구]
    "codec_check_min_bytes": 50 * 1024 ** 3,         # [도구]
    "vector_vs_fscache_pct_warn": 60,                # [도구] 벡터 상주량 / (RAM - heap)
    "vector_dim_quantize_warn": 384,                 # [공식] 384차원 이상 float 벡터는 양자화 권장
    "vector_segments_per_shard_warn": 20,            # [도구]
    "avg_doc_bytes_warn": 1024 * 1024,               # [도구] 문서 평균 1MB

    # --- 핫스팟/밸런싱 ---
    "tier_cpu_pct_warn": 75,                        # [도구] tier 전체 포화 판정 CPU%
    "hotspot_heap_pct_gap": 30,                      # [도구] 노드 간 heap 편차(%p)
    "hotspot_heap_pct_floor": 70,                    # [도구] 최대값이 이 미만이면 무시
    "hotspot_cpu_pct_floor": 50,                     # [도구]
    "hotspot_disk_pct_floor": 50,                    # [도구]
    "hotspot_cpu_pct_gap": 40,                       # [도구]
    "workload_skew_ratio_warn": 1.8,                 # [도구] 최대 노드 / 평균
    "undesired_shards_warn": 1,                      # [도구]
    "recovery_rate_low_bytes": 40 * 1024 ** 2,       # [공식] indices.recovery.max_bytes_per_sec 기본값 40mb 이하

    # --- 과다 샤딩 ---
    "oversharding_floor_shard_gb": 10,              # [공식] 샤드 권장 하한 10GB
    "oversharding_target_shard_gb": 50,             # [공식] 샤드 권장 상한 50GB(권장 primary 수 산정)
    "oversharding_excess_warn": 20,                 # [도구] 줄일 수 있는 샤드 합계
    "oversharding_excess_ratio_warn": 0.1,          # [도구] 전체 샤드 대비 비중
    "oversharding_min_shards": 20,                  # [도구] 분포 판정 최소 표본
    "oversharding_small_share_warn": 0.8,           # [도구] 10GB 미만 비중
    "oversharding_min_data_gb": 100,                # [도구] 소규모 클러스터는 분포 판정 제외
    "ds_min_backing_indices": 5,                    # [도구] 데이터 스트림 판정 최소 백킹 수
    "ds_small_backing_shard_gb": 1,                 # [도구] 백킹 샤드 중앙값 기준

    # --- 매핑·ILM 정책 ---
    "mapping_fields_near_limit_pct": 90,            # [도구] total_fields.limit 대비 필드 수
    "ilm_rollover_max_shard_gb": 50,
    "disk_io_busy_pct_warn": 60,
    "search_expensive_share_warn": 10,              # [도구] 비용이 큰 쿼리 유형의 검색 대비 비중(%)                    # [도구] 기동 이후 평균 디스크 사용률                # [공식] 롤오버 샤드 크기 권장 상한

    # --- 번들 비교(diff) ---
    "diff_min_hours_for_projection": 1.0,            # [도구] 이보다 짧은 간격은 외삽 안 함
    "disk_projection_days_warn": 30,                 # [도구]
    "index_growth_min_bytes": 1024 ** 3,             # [도구]

    # --- 리포트 ---
    "top_n": 15,                                     # [도구] 근거 표 최대 행 수
    "eol_major_below": 8,                            # [도구] 이 메이저 미만은 구버전 경고
}


def merge(overrides):
    """기본값에 사용자 재정의를 덮는다. 알 수 없는 키는 무시하고 경고한다(오타로 인한 무효 설정 방지)."""
    import sys
    t = dict(DEFAULTS)
    for k, v in (overrides or {}).items():
        if k not in DEFAULTS:
            sys.stderr.write("경고: 알 수 없는 임계값 키 '%s' 는 무시합니다(--print-thresholds 로 목록 확인)\n" % k)
            continue
        t[k] = v
    return t
