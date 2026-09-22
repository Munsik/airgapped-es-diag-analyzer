# 판정 룰 명세 (RULES.md)

> 이 문서는 `tools/gen_rules_doc.py` 가 소스 코드에서 자동 생성합니다. 직접 수정하지 마십시오.
> 임계값은 `esdiag/thresholds.py` 의 현재 기본값이며, `--thresholds` 로 재정의할 수 있습니다.

## 기준점

| 항목 | 값 |
| --- | --- |
| 도구 버전 | esdiag 0.9.0 |
| 판정 기준 Elasticsearch 버전 | 9.4 |
| 공식 문서 대조 시점 | 2026-09 |
| 실번들 검증 | 9.4.4 (ECH, 3노드 단일 tier) / 9.5.3 (ECH, 14노드 hot·warm·cold·frozen) — api 모드 |
| 현장 실행 확인 | 9.5.3 다중 tier 번들로 오탐·미탐 교정, 파일·필드 구조 대조, 대형 번들(cluster_state 190MB·mapping 178MB) 메모리 검증 |
| 검증된 수집 모드 | api 모드만 검증 — local / remote 모드(서버 로그·OS 명령 결과 포함)는 확인이 필요할 수 있음 |
| 지원 최소 버전 | 8.0 (미만은 해당 버전에 존재하는 API 범위에서만 동작) |

### 버전별 판정 분기

| 기준 버전 | 대상 | 내용 |
| --- | --- | --- |
| 8.0 | SET-* | action.destructive_requires_name 기본값 true |
| 8.3 | SHD-001 | heap 1GB당 샤드 20개 기준은 8.3 미만에만 적용 |
| 8.5 | DISK-* | 디스크 워터마크 max_headroom(200/150/100GB) 적용 |
| 8.14 | VEC-002 | dense_vector index_options 미지정 시 int8_hnsw 기본(양자화) |
| 9.1 | VEC-002 | 384차원 이상 float 벡터는 bbq_hnsw 가 기본 |
| 9.2 | VEC-003 | index.mapping.exclude_source_vectors 기본 적용 |

분석 대상이 기준 버전보다 새로우면 리포트에 `VER-001` 이 표시됩니다.

## 판정 근거 구분

| 구분 | 의미 |
| --- | --- |
| 공식 기준 | 판정 기준 자체가 Elastic 공식 문서에 명시된 항목 |
| 사실 보고 | Elasticsearch 가 보고한 상태·오류·설정값을 그대로 전달(임계값 없음) |
| 도구 판단 | 공식 수치 기준이 없어 이 도구의 임계값으로 판단한 항목 |
| 비교 계산 | 두 번들 간 증가분·증가율·선형 외삽 |

## 입력 파일 규칙

각 룰은 필요한 입력 파일을 선언합니다(`esdiag/rules/__init__.py` 의 `REQUIRES`). 파일이 번들에 없으면 해당 룰을 실행하지 않고 리포트의 '입력 미수집으로 판정하지 않은 항목' 에 기록합니다. '파일 없음(미수집)' 과 '설정 없음(미설정)' 을 구분하기 위함입니다.

## 목차

- [클러스터](#클러스터) — 12개 룰
- [설정 변경 (기본값 대비)](#설정-변경-기본값-대비) — 5개 룰
- [노드 (JVM · OS · 디스크 · 스레드풀)](#노드-jvm-os-디스크-스레드풀) — 11개 룰
- [샤드 · 인덱스](#샤드-인덱스) — 18개 룰
- [과다 샤딩 · 소형 샤드](#과다-샤딩-소형-샤드) — 3개 룰
- [공식 가이드 기준 (설정 · 샤드 · 성능 · 디스크 · 벡터)](#공식-가이드-기준-설정-샤드-성능-디스크-벡터) — 23개 룰
- [핫스팟 · 밸런싱](#핫스팟-밸런싱) — 7개 룰
- [운영 · 보안](#운영-보안) — 9개 룰
- [매핑 · ILM 정책 · 클러스터 조정 · 세부 통계](#매핑-ilm-정책-클러스터-조정-세부-통계) — 16개 룰
- [런타임 (hot threads · 로그)](#런타임-hot-threads-로그) — 2개 룰
- [변화 추세 (--baseline 비교 모드)](#변화-추세---baseline-비교-모드) — 9개 룰
- [설정 지식 베이스](#설정-지식-베이스)
- [임계값 전체 목록](#임계값-전체-목록)

## 클러스터

### CLU-001 — 클러스터 상태 green

| 항목 | 내용 |
| --- | --- |
| 함수 | `cluster.r_cluster_status` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 치명, 주의, 정상 |
| 필요 입력 | (cluster_health.json) |
| 근거 파일 | cluster_health.json |
| 참고 문서 | [샤드 할당 문제 해결](https://www.elastic.co/docs/troubleshoot/elasticsearch/diagnose-unassigned-shards) |

**판정 로직**

cluster_health.status 를 그대로 판정. red → 치명, yellow → 주의, green → 정상.

### CLU-002, CLU-003 — 미할당 샤드 존재

| 항목 | 내용 |
| --- | --- |
| 함수 | `cluster.r_unassigned_reason` |
| 판정 항목 | CLU-002 미할당 샤드 존재 / CLU-003 allocation explain 결과 |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 치명, 주의, 참고 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (indices.json 또는 shards.json 또는 cat_shards.txt) |
| 근거 파일 | allocation_explain.json / indices.json / shards.json |
| 참고 문서 | [샤드 할당 문제 해결](https://www.elastic.co/docs/troubleshoot/elasticsearch/diagnose-unassigned-shards) |

**판정 로직**

샤드 목록에서 state=UNASSIGNED 인 샤드를 unassigned.reason 별로 집계. 미할당 primary 가 하나라도 있으면 치명, replica 만이면 주의(CLU-002). allocation_explain.json 이 있으면 decider 결과를 함께 보고: can_allocate != yes → 주의, 그 외 참고(CLU-003).

### CLU-004, CLU-004.(하위 항목) — Health API 지표 전체 green

| 항목 | 내용 |
| --- | --- |
| 함수 | `cluster.r_internal_health` |
| 판정 항목 | CLU-004 Health API 지표 전체 green / CLU-004.  |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 치명, 주의, 정상 |
| 필요 입력 | (internal_health.json) |
| 근거 파일 | internal_health.json |

**판정 로직**

Health API(_health_report) 지표를 그대로 전달. 지표별 red → 치명, yellow → 주의, 전 지표 green → 정상. unknown 은 판정하지 않는다.

### CLU-005 — 마스터 pending task 적체

| 항목 | 내용 |
| --- | --- |
| 함수 | `cluster.r_pending_tasks` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 치명, 주의 |
| 임계값 | `max_task_wait_ms_warn` = 30,000 — [도구]<br>`pending_tasks_crit` = 100 — [도구]<br>`pending_tasks_warn` = 10 — [도구]<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (cluster_health.json) |
| 근거 파일 | cluster_health.json / cluster_pending_tasks.json |

**판정 로직**

마스터 pending task. 건수 >= pending_tasks_crit 또는 최대 대기 >= max_task_wait_ms_warn x 4 → 치명, 건수 >= pending_tasks_warn 또는 최대 대기 >= max_task_wait_ms_warn → 주의.

### CLU-006, CLU-007 — 마스터 후보 노드 없음

| 항목 | 내용 |
| --- | --- |
| 함수 | `cluster.r_master_quorum` |
| 판정 항목 | CLU-006 마스터 후보 노드 없음 / CLU-007 전용 마스터 노드 부재 |
| 근거 구분 | 공식 기준 / 도구 판단 |
| 가능 심각도 | 치명, 주의 |
| 필요 입력 | (nodes.json) |
| 근거 파일 | nodes.json |

**판정 로직**

마스터 후보(roles 에 master 포함, voting_only 포함) 수. 0대 → 치명, 다중 노드인데 1대 → 치명, 2대 → 치명(1대 이탈 시 정족수 상실), 4대 이상 짝수 → 주의(CLU-006). 전용 마스터가 없고 데이터 노드 >= 6대 → 주의(CLU-007).

### CLU-008, CLU-009, CLU-010 — 노드 버전 불일치

| 항목 | 내용 |
| --- | --- |
| 함수 | `cluster.r_version_consistency` |
| 판정 항목 | CLU-008 노드 버전 불일치 / CLU-009 구버전 메이저 사용 / CLU-010 노드 간 JVM 버전 불일치 |
| 근거 구분 | 도구 판단 / 사실 보고 |
| 가능 심각도 | 주의 |
| 임계값 | `eol_major_below` = 8 — [도구] 이 메이저 미만은 구버전 경고 |
| 필요 입력 | (nodes.json) |
| 근거 파일 | nodes.json / version.json |

**판정 로직**

노드별 ES 버전 종류 > 1 → 주의(CLU-008). 메이저 버전 < eol_major_below → 주의(CLU-009). 노드별 JVM 버전 종류 > 1 → 주의(CLU-010).

### CLU-013, CLU-014, CLU-011.(하위 항목), CLU-012 — transient 클러스터 설정 사용 중

| 항목 | 내용 |
| --- | --- |
| 함수 | `cluster.r_risky_settings` |
| 판정 항목 | CLU-013 transient 클러스터 설정 사용 중 / CLU-014 Adaptive Replica Selection 비활성화 / CLU-011.  / CLU-012 노드 제외(exclude) 설정 잔존 |
| 근거 구분 | 공식 기준 / 사실 보고 |
| 가능 심각도 | 주의, 참고 |
| 필요 입력 | (cluster_settings.json) |
| 근거 파일 | cluster_settings.json |

**판정 로직**

기본값이 아닌(persistent/transient 에 명시된) 클러스터 설정만 판정. allocation.enable != all → 치명, rebalance.enable != all → 주의, disk.threshold_enabled=false → 치명, cluster.blocks.read_only(_allow_delete)=true → 치명, destructive_requires_name=false → 주의(CLU-011). allocation.exclude._name/_ip/_host 값 존재 → 주의(CLU-012). transient 설정 존재 → 참고(CLU-013, 7.16 부터 deprecated). use_adaptive_replica_selection=false → 주의(CLU-014, 기본 true).

### CLU-015 — 클러스터 샤드 한도 임박

| 항목 | 내용 |
| --- | --- |
| 함수 | `cluster.r_shard_capacity` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 치명, 주의 |
| 임계값 | `max_shards_per_node_headroom_pct_warn` = 80 — [도구] cluster.max_shards_per_node 대비 사용률 |
| 필요 입력 | (cluster_settings.json) 그리고 (cluster_health.json) 그리고 (nodes.json) |
| 근거 파일 | cluster_health.json / cluster_settings.json |
| 참고 문서 | [샤드 사이징 가이드](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

사용률 = (active + unassigned − frozen 전용 노드의 샤드) / (cluster.max_shards_per_node x frozen 전용을 제외한 데이터 노드 수). >= max_shards_per_node_headroom_pct_warn → 주의, >= 95% → 치명.

### CLU-016 — dangling 인덱스 존재

| 항목 | 내용 |
| --- | --- |
| 함수 | `cluster.r_dangling` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 주의 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (dangling_indices.json) |
| 근거 파일 | dangling_indices.json |

**판정 로직**

dangling 인덱스가 1개 이상이면 주의.

### CLU-017 — 장시간 수행 중인 태스크

| 항목 | 내용 |
| --- | --- |
| 함수 | `cluster.r_long_tasks` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의 |
| 임계값 | `long_running_task_ms_warn` = 300,000 — [도구] 5분<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (tasks.json) |
| 근거 파일 | tasks.json |

**판정 로직**

running_time >= long_running_task_ms_warn 인 태스크(상시 동작하는 persistent task 는 제외) → 주의.

### CLU-018, CLU-019 — 가용영역 간 데이터 노드 불균형

| 항목 | 내용 |
| --- | --- |
| 함수 | `cluster.r_zone_balance` |
| 판정 항목 | CLU-018 가용영역 간 데이터 노드 불균형 / CLU-019 shard allocation awareness 미설정 |
| 근거 구분 | 공식 기준 / 도구 판단 |
| 가능 심각도 | 주의 |
| 필요 입력 | (nodes.json) 그리고 (cluster_settings.json) |
| 근거 파일 | cluster_settings.json / nodes.json / nodes.json |

**판정 로직**

데이터 노드의 zone 속성(availability_zone / zone / logical_availability_zone / rack_id)이 2종 이상일 때만 판정. 영역별 노드 수 최대−최소 >= 2 또는 최대 >= 최소 x 2 → 주의(CLU-018). awareness.attributes 미설정 → 주의(CLU-019).

### CLU-020 — 진행 중인 샤드 복구

| 항목 | 내용 |
| --- | --- |
| 함수 | `cluster.r_recovery_inflight` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 참고 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (recovery.json) |
| 근거 파일 | recovery.json |

**판정 로직**

recovery.json 에서 stage != DONE 인 샤드가 있으면 참고.

## 설정 변경 (기본값 대비)

### SET-001, SET-002 — 기본값에서 변경된 클러스터 설정

| 항목 | 내용 |
| --- | --- |
| 함수 | `settings.r_cluster_setting_changes` |
| 판정 항목 | SET-001 기본값에서 변경된 클러스터 설정 / SET-002 기본값과 같은 값을 명시한 클러스터 설정 |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 참고, 정상 |
| 필요 입력 | (cluster_settings.json) |
| 근거 파일 | cluster_settings.json |

**판정 로직**

persistent / transient 에 명시된 모든 클러스터 설정을 공식 기본값과 비교한다.

기본값이 공식 문서(settings_kb)에 등록된 설정은 '원래 기본값 / 방향(↑↓) / 변경 영향' 을 보고하고,
미등록 설정은 값만 '설명 미등록' 으로 보고한다. 기본값과 같은 값을 명시한 경우는 '기본값과 동일' 로 참고 표기.
심각도는 등록된 설정의 변경 방향별 위험도(risk) 중 최고값(최대 주의). 치명급 설정은 CLU-011 이 별도로 판정한다.
변경 사항이 없으면 정상.

### SET-003 — elasticsearch.yml 값이 클러스터 설정 API 값에 가려짐

| 항목 | 내용 |
| --- | --- |
| 함수 | `settings.r_yml_shadowed` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 참고 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (cluster_settings.json) 그리고 (nodes.json) |
| 근거 파일 | nodes.json / cluster_settings.json |

**판정 로직**

elasticsearch.yml(노드 설정)에 있는 값이 persistent/transient 에 의해 가려지는지 확인한다.

같은 키가 노드 설정과 클러스터 API 설정에 모두 있고 값이 다르면, 공식 우선순위에 따라 API 값이 적용되고
yml 값은 무시된다(참고). yml 을 고쳐도 반영되지 않는 상황을 알리기 위함이다.

### SET-004 — 기본값에서 변경된 노드 설정(elasticsearch.yml)

| 항목 | 내용 |
| --- | --- |
| 함수 | `settings.r_node_setting_changes` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 참고 |
| 필요 입력 | (nodes.json) |
| 근거 파일 | nodes.json |

**판정 로직**

노드 설정(elasticsearch.yml, static 포함) 중 공식 기본값이 등록된 설정이 기본값과 다른지 확인한다.

노드 고유 설정(이름·경로·네트워크·보안 인증서 등)은 제외한다. 노드별 값을 모아 설정 단위로 보고하며,
심각도는 변경 방향별 위험도 중 최고값(최대 주의, 전용 룰 설정 제외). node.processors 는 실제 할당 CPU 수와
같으면 변경으로 보지 않는다. ECH/ECE/ECK 로 감지되면 플랫폼 관리 값으로 보고 참고로 하향한다.
static 설정은 모든 대상 노드의 yml 수정과 재기동이 필요하다.

### SET-005 — 데이터 노드 간 설정 불일치

| 항목 | 내용 |
| --- | --- |
| 함수 | `settings.r_node_setting_consistency` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (nodes.json) |
| 근거 파일 | nodes.json |

**판정 로직**

노드 간 일치해야 할 설정(인덱싱 버퍼·캐시·스레드풀·검색·전송 등)이 노드마다 다르거나 일부 노드에만 있는지 확인한다.

대상은 명시 설정된 키 중 _CONSISTENCY_PREFIX 범위이며 노드 고유 설정은 제외. 데이터 노드끼리만 비교한다
(역할이 다른 노드의 설정 차이는 정상일 수 있음). 불일치가 있으면 주의.

### SET-006 — 기본값에서 변경된 인덱스 설정

| 항목 | 내용 |
| --- | --- |
| 함수 | `settings.r_index_setting_changes` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 참고 |
| 필요 입력 | (settings.json) |
| 근거 파일 | settings.json |

**판정 로직**

사용자 인덱스의 명시 설정 중 공식 기본값이 등록된 설정이 기본값과 다른 것을 설정·값 단위로 집계한다.

인덱스 생성 시 자동으로 들어가는 식별 정보(uuid, creation_date, version, provided_name, number_of_shards,
tier preference 등)는 등록 대상이 아니므로 자연히 제외된다. 시스템 인덱스는 제외.
심각도는 변경 방향별 위험도 중 최고값(최대 주의, 전용 룰 설정 제외).

## 노드 (JVM · OS · 디스크 · 스레드풀)

### JVM-001 — Heap 사용률 정상

| 항목 | 내용 |
| --- | --- |
| 함수 | `nodes.r_heap_usage` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 치명, 주의, 정상 |
| 임계값 | `heap_used_pct_crit` = 85 — [도구] 수집 순간 heap 사용률<br>`heap_used_pct_warn` = 75 — [도구] 수집 순간 heap 사용률 |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |
| 참고 문서 | [Heap 크기 설정](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/important-settings-configuration) |

**판정 로직**

노드별 jvm.mem.heap_used_percent(수집 순간값). >= heap_used_pct_crit → 치명, >= heap_used_pct_warn → 주의, 그 외 정상.

### JVM-002, JVM-003, JVM-004 — Heap 32GB 경계 초과(compressed oops 손실 가능)

| 항목 | 내용 |
| --- | --- |
| 함수 | `nodes.r_heap_sizing` |
| 판정 항목 | JVM-002 Heap 32GB 경계 초과(compressed oops 손실 가능) / JVM-003 Heap 이 물리 메모리 대비 과다 / JVM-004 Xms 와 Xmx 불일치 |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의 |
| 임계값 | `heap_max_bytes_crit` = 32GiB — [공식] compressed oops 경계(32GB 미만 권장)<br>`heap_vs_ram_pct_warn` = 50 — [공식] heap <= 전체 메모리의 50%<br>`heap_vs_ram_tolerance_pct` = 2 — [도구] 반올림·adjusted_total 오차 허용 |
| 필요 입력 | (nodes.json) 그리고 (nodes_stats.json) |
| 근거 파일 | nodes.json / nodes.json / nodes_stats.json |
| 참고 문서 | [Heap 크기 설정](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/important-settings-configuration) |

**판정 로직**

heap_max >= heap_max_bytes_crit(32GiB) 또는 using_compressed_ordinary_object_pointers=false → 주의(JVM-002). heap_max / os.mem.adjusted_total > heap_vs_ram_pct_warn + heap_vs_ram_tolerance_pct → 주의(JVM-003). heap_init(Xms) != heap_max(Xmx) → 주의(JVM-004).

### JVM-005 — GC 부담 정상 범위

| 항목 | 내용 |
| --- | --- |
| 함수 | `nodes.r_gc` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 치명, 주의, 정상 |
| 임계값 | `old_gc_per_hour_crit` = 30 — [도구] 시간당 old GC 횟수<br>`old_gc_per_hour_warn` = 6 — [도구] 시간당 old GC 횟수<br>`old_gc_time_ratio_crit` = 0.05 — [도구] old GC 누적 시간 / uptime<br>`old_gc_time_ratio_warn` = 0.02 — [도구] old GC 누적 시간 / uptime<br>`young_gc_time_ratio_warn` = 0.05 — [도구] young GC 누적 시간 / uptime |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |

**판정 로직**

old 비중 = old collection_time / uptime, 시간당 old GC = old count / uptime(h), young 비중 = young time / uptime. old 비중 >= old_gc_time_ratio_crit 또는 시간당 >= old_gc_per_hour_crit → 치명. old 비중 >= warn, 시간당 >= warn, young 비중 >= young_gc_time_ratio_warn 중 하나 → 주의. 그 외 정상. 누적값이므로 비교 모드(DIF-006)가 더 정확하다.

### OS-001, OS-002, OS-003, OS-004, OS-005, OS-006 — CPU load 높음

| 항목 | 내용 |
| --- | --- |
| 함수 | `nodes.r_os` |
| 판정 항목 | OS-001 CPU load 높음 / OS-002 Swap 활성화 / OS-003 컨테이너 CPU throttling 발생 / OS-004 파일 디스크립터 사용률 높음 / OS-005 bootstrap.memory_lock 미적용 / OS-006 최근 재기동된 노드 존재 |
| 근거 구분 | 공식 기준 / 도구 판단 |
| 가능 심각도 | 치명, 주의, 참고 |
| 임계값 | `cgroup_throttle_ratio_crit` = 0.05 — [도구] throttled / elapsed periods<br>`cgroup_throttle_ratio_warn` = 0.01 — [도구] throttled / elapsed periods<br>`fd_used_pct_warn` = 70 — [도구] 열린 파일 / 최대(공식 최소 한도는 65,535)<br>`load_per_cpu_crit` = 1.5 — [도구] load15 / CPU 코어<br>`load_per_cpu_warn` = 1.0 — [도구] load15 / CPU 코어<br>`uptime_short_hours` = 6 — [도구] 최근 재기동 판단 |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes.json / nodes_stats.json |

**판정 로직**

load15 / available_processors >= load_per_cpu_crit → 치명, >= warn → 주의(OS-001, 두 구간의 노드를 모두 표시). swap_total > 0 이고 mlockall 이 true 가 아님 → 주의(OS-002). cgroup throttled / elapsed_periods >= cgroup_throttle_ratio_crit → 치명, >= warn → 주의(OS-003). open_fd / max_fd >= fd_used_pct_warn → 주의(OS-004). mlockall=false 이고 swap 없음 → 참고(OS-005). uptime < uptime_short_hours → 주의(OS-006).

### DISK-001, DISK-002, DISK-003, DISK-004, DISK-005 — 디스크 flood stage 초과

| 항목 | 내용 |
| --- | --- |
| 함수 | `nodes.r_disk` |
| 판정 항목 | DISK-001 디스크 flood stage 초과 / DISK-002 디스크 high watermark 초과 / DISK-003 디스크 low watermark 초과 / DISK-004 디스크 사용률 상승 / DISK-005 같은 tier 노드 간 디스크 사용률 편차 |
| 근거 구분 | 공식 기준 / 도구 판단 |
| 가능 심각도 | 치명, 주의, 정상 |
| 임계값 | `disk_imbalance_pct_warn` = 15 — [도구] 노드 간 디스크 사용률 편차(%p)<br>`disk_low_margin_pct` = 10 — [도구] 실효 low 워터마크까지 남은 %p |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |
| 참고 문서 | [디스크 기반 샤드 할당(워터마크)](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |

**판정 로직**

데이터 노드 사용률 = 1 − available / total. 실효 워터마크(max_headroom 반영, context.watermark_used_pct) 대비 flood 이상 → 치명(DISK-001), high 이상 → 치명(DISK-002), low 이상 → 주의(DISK-003), low − disk_low_margin_pct 이상 → 주의(DISK-004, 앞 세 항목이 없을 때만). 노드 간 사용률 최대−최소 >= disk_imbalance_pct_warn → 주의(DISK-005). 해당 없음 → 정상.

### TP-001, TP-002 — 스레드풀 rejection 발생

| 항목 | 내용 |
| --- | --- |
| 함수 | `nodes.r_thread_pools` |
| 판정 항목 | TP-001 스레드풀 rejection 발생 / TP-002 수집 시점 큐 적체 |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 치명, 주의, 참고, 정상 |
| 임계값 | `rejected_crit` = 1,000 — [도구] 누적 rejection 합계<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |
| 참고 문서 | [스레드풀과 rejection](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings) |

**판정 로직**

모든 스레드풀의 누적 rejected. 합계 > 0 → 주의, 합계 >= rejected_crit → 치명, 0 → 정상(TP-001). 주요 풀(write/search/get 등)의 queue > 0 → 참고(TP-002).

### BRK-001, BRK-002 — Circuit breaker 발동 이력

| 항목 | 내용 |
| --- | --- |
| 함수 | `nodes.r_breakers` |
| 판정 항목 | BRK-001 Circuit breaker 발동 이력 / BRK-002 Circuit breaker 사용률 높음 |
| 근거 구분 | 도구 판단 / 사실 보고 |
| 가능 심각도 | 치명, 주의 |
| 임계값 | `breaker_tripped_warn` = 1 — [도구] breaker 발동 횟수(1 = 이력 존재) |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |

**판정 로직**

breaker.tripped >= breaker_tripped_warn → 치명(BRK-001). 발동 이력은 없고 estimated / limit >= 70% → 주의(BRK-002).

### IP-001 — Indexing pressure rejection

| 항목 | 내용 |
| --- | --- |
| 함수 | `nodes.r_indexing_pressure` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 주의 |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |

**판정 로직**

indexing_pressure.memory.total 의 *_rejections(coordinating/primary/replica) 중 하나라도 > 0 → 주의.

### FD-001, FD-002 — fielddata 가 heap 을 과점

| 항목 | 내용 |
| --- | --- |
| 함수 | `nodes.r_fielddata` |
| 판정 항목 | FD-001 fielddata 가 heap 을 과점 / FD-002 fielddata 상위 소비 필드 |
| 근거 구분 | 도구 판단 / 사실 보고 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `fielddata_heap_pct_warn` = 10 — [도구] fielddata / heap<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | fielddata.json / nodes_stats.json |

**판정 로직**

노드 fielddata 메모리 / heap_max >= fielddata_heap_pct_warn → 주의(FD-001). fielddata.json 에서 가장 큰 필드가 64MB 초과 → 참고(FD-002).

### ING-001 — Ingest 파이프라인 처리 실패

| 항목 | 내용 |
| --- | --- |
| 함수 | `nodes.r_ingest_failures` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 주의 |
| 임계값 | `ingest_failed_warn` = 1 — [도구]<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |

**판정 로직**

ingest.total.failed >= ingest_failed_warn 인 노드가 있으면 주의. 실패 파이프라인별 건수를 근거로 제시.

### NODE-001, NODE-003 — 같은 tier 안에서 노드 스펙 불균일

| 항목 | 내용 |
| --- | --- |
| 함수 | `nodes.r_node_heterogeneity` |
| 판정 항목 | NODE-001 같은 tier 안에서 노드 스펙 불균일 / NODE-003 tier 별 노드 스펙 |
| 근거 구분 | 도구 판단 / 사실 보고 |
| 가능 심각도 | 주의, 참고 |
| 필요 입력 | (nodes.json) 그리고 (nodes_stats.json) |
| 근거 파일 | nodes.json / nodes.json / nodes_stats.json |

**판정 로직**

같은 tier(데이터 역할 조합) 안에서 heap 또는 CPU 수가 다르면 주의(NODE-001/002).

tier 가 다르면 스펙이 다른 것이 정상 설계이므로 tier 간 차이는 판정하지 않고, tier 별 스펙 표만 참고로 보고한다
(NODE-003). 같은 tier 에서는 샤드가 균등 분배되므로 작은 노드가 먼저 포화되어 그 tier 의 처리 한계가 된다.

## 샤드 · 인덱스

### SHD-001 — 노드당 샤드 수 과다(8.3 미만 기준)

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_shard_density` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 치명, 주의, 참고, 정상 |
| 임계값 | `shards_per_gb_heap_crit` = 30 — [도구] 8.3 미만 전용<br>`shards_per_gb_heap_warn` = 20 — [공식] heap 1GB당 샤드 20개(8.3 미만 전용) |
| 필요 입력 | (indices.json 또는 shards.json 또는 cat_shards.txt) 그리고 (nodes.json) |
| 근거 파일 | indices.json / nodes_stats.json |
| 참고 문서 | [샤드 사이징 가이드](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

노드당 샤드 밀도.

'heap 1GB당 샤드 20개' 는 8.3 미만 버전의 공식 기준이다. 8.3 부터 샤드당 heap 오버헤드가 크게 줄어
공식 문서가 이 기준을 폐기하고 '필드 매퍼 heap 산정(SHD-010)' 과 cluster.max_shards_per_node(CLU-015)
로 대체했다. 따라서 8.3 이상에서는 판정하지 않고 현황만 표기한다.

### SHD-006 — 같은 tier 노드 간 샤드 수 불균형

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_shard_balance` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의 |
| 필요 입력 | (indices.json 또는 shards.json 또는 cat_shards.txt) |
| 근거 파일 | indices.json / nodes.json |

**판정 로직**

같은 tier 안에서 노드 간 샤드 수 편차가 평균의 25% 이상이면 주의.

tier 마다 보관 데이터와 노드 수가 달라 tier 간 샤드 수 차이는 정상이므로 비교하지 않는다.

### IDX-010 — 데이터 스트림 상태 이상

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_data_stream_health` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 치명, 주의 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (data_stream.json) |
| 근거 파일 | commercial/data_stream.json |

**판정 로직**

data stream status 가 RED → 치명, YELLOW → 주의.

### PERF-003 — 캐시 적중률 저조 + eviction 과다

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_cache_efficiency` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 필요 입력 | (indices_stats.json) |
| 근거 파일 | indices_stats.json |

**판정 로직**

query(=shard request) cache / request cache 효율.

### SHD-002, SHD-003 — 초대형 샤드 존재

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_shard_size` |
| 판정 항목 | SHD-002 초대형 샤드 존재 / SHD-003 대형 샤드 존재 |
| 근거 구분 | 공식 기준 / 도구 판단 |
| 가능 심각도 | 치명, 주의 |
| 임계값 | `shard_size_gb_crit` = 200 — [도구] 복구 시간 기준 상한<br>`shard_size_gb_warn` = 50 — [공식] 샤드 10~50GB<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (indices.json 또는 shards.json 또는 cat_shards.txt) |
| 근거 파일 | indices.json |
| 참고 문서 | [샤드 사이징 가이드](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

primary 샤드 store >= shard_size_gb_crit → 치명(SHD-002), >= shard_size_gb_warn(공식 상한 50GB) → 주의(SHD-003).

### SHD-004 — 소형 샤드 과다

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_small_shards` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의 |
| 임계값 | `small_shard_count_warn` = 50 — [도구]<br>`small_shard_mb` = 1,024 — [도구] 소형 샤드 기준<br>`small_shard_ratio_warn` = 0.5 — [도구]<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (indices.json 또는 shards.json 또는 cat_shards.txt) |
| 근거 파일 | indices.json |
| 참고 문서 | [샤드 사이징 가이드](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

store < small_shard_mb 인 primary 중 사용자 인덱스 샤드 수 >= small_shard_count_warn 이고, 전체 primary 중 소형 비율 >= small_shard_ratio_warn → 주의. 시스템 인덱스는 사용자가 조정할 수 없어 판정 기준에서 제외.

### IDX-001 — replica 0 인덱스 존재

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_replica_zero` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) 그리고 (indices_stats.json) |
| 근거 파일 | settings.json / indices_stats.json |

**판정 로직**

사용자 인덱스 중 number_of_replicas=0 이고 auto_expand_replicas 가 없으며 searchable snapshot 인덱스가 아닌 것 → 주의.

### IDX-002 — replica 수가 데이터 노드 수를 초과

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_replica_unassignable` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 치명 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) 그리고 (nodes.json) |
| 근거 파일 | settings.json |

**판정 로직**

number_of_replicas > (데이터 노드 수 − 1) → 치명(영구 미할당). auto_expand_replicas 인덱스는 제외. tier 별 노드 수는 보지 않으므로 보수적(미탐 가능, 오탐 없음) 판정이다.

### IDX-003 — 삭제 문서 비율 높음

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_deleted_docs` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의 |
| 임계값 | `deleted_docs_ratio_warn` = 0.25 — [도구]<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (indices_stats.json) |
| 근거 파일 | indices_stats.json |

**판정 로직**

primary store >= 1GB 인 인덱스에서 deleted / (docs + deleted) >= deleted_docs_ratio_warn → 주의.

### IDX-004 — 샤드당 세그먼트 수 과다

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_segments` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의 |
| 임계값 | `segments_per_shard_warn` = 50 — [도구]<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (indices_stats.json) 그리고 (indices.json 또는 shards.json 또는 cat_shards.txt) |
| 근거 파일 | indices_stats.json |

**판정 로직**

primary 세그먼트 수 / primary 샤드 수 >= segments_per_shard_warn 이고 primary store > 100MB → 주의.

### IDX-005 — merge throttling 관측

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_merge_throttle` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의 |
| 임계값 | `merge_throttle_ratio_warn` = 0.05 — [도구]<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (indices_stats.json) |
| 근거 파일 | indices_stats.json |

**판정 로직**

merges.total_throttled_time / merges.total_time >= merge_throttle_ratio_warn 이고 throttled 누적 > 60초 → 주의.

### PERF-001, PERF-002 — 검색 평균 지연 높은 인덱스

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_search_latency` |
| 판정 항목 | PERF-001 검색 평균 지연 높은 인덱스 / PERF-002 색인 평균 지연 높은 인덱스 |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 치명, 주의 |
| 임계값 | `index_latency_ms_crit` = 200 — [도구] 문서당 평균 색인 시간<br>`index_latency_ms_warn` = 50 — [도구] 문서당 평균 색인 시간<br>`min_query_total_for_latency` = 100 — [도구] 표본이 적으면 판정 제외<br>`search_latency_ms_crit` = 1,000 — [도구] 인덱스 평균 query 지연<br>`search_latency_ms_warn` = 200 — [도구] 인덱스 평균 query 지연<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (indices_stats.json) |
| 근거 파일 | indices_stats.json |

**판정 로직**

query_total >= min_query_total_for_latency 인 인덱스의 평균 query 지연 = query_time / query_total. >= search_latency_ms_crit → 치명, >= warn → 주의(PERF-001). 문서당 평균 색인 시간 = index_time / index_total 에 대해 index_latency_ms_crit / warn 으로 동일 판정(PERF-002). 누적 평균이며 p99 가 아니다.

### IDX-006 — 색인/검색 실패 카운터 존재

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_index_failures` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (indices_stats.json) |
| 근거 파일 | indices_stats.json |

**판정 로직**

indexing.index_failed 또는 search.query_failure > 0 인 인덱스. 사용자 인덱스가 포함되면 주의, 시스템 인덱스뿐이면 참고.

### MAP-001, MAP-002 — 매핑 필드 한도 상향 인덱스

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_mapping_limits` |
| 판정 항목 | MAP-001 매핑 필드 한도 상향 인덱스 / MAP-002 클러스터 전체 필드 수 |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) |
| 근거 파일 | cluster_stats.json / settings.json |
| 참고 문서 | [매핑 폭증 방지](https://www.elastic.co/docs/manage-data/data-store/mapping) |

**판정 로직**

사용자 인덱스의 mapping.total_fields.limit > 1000(기본값) → 주의(MAP-001). cluster_stats 전체 필드 수 > 100,000 → 주의(MAP-002).

### IDX-007 — 대량 색인 인덱스에 refresh_interval 1초 이하 명시

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_refresh_interval` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 참고 |
| 임계값 | `heavy_index_docs` = 10,000,000 — [도구] 대량 색인 인덱스 기준<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) 그리고 (indices_stats.json) |
| 근거 파일 | settings.json / indices_stats.json |

**판정 로직**

refresh 주기.

refresh_interval 을 명시하지 않은 인덱스는 search idle 동작이 적용된다.
index.search.idle.after(기본 30s) 동안 검색이 없던 샤드는 주기적 refresh 를 건너뛰므로,
'미지정 = 매초 refresh' 가 아니다. 따라서 명시적으로 1s 이하로 지정한 인덱스만 판정한다.

### IDX-008, IDX-011 — 쓰기 대상 인덱스 또는 flood stage 쓰기 차단

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_read_only_blocks` |
| 판정 항목 | IDX-008 쓰기 대상 인덱스 또는 flood stage 쓰기 차단 / IDX-011 단독 인덱스의 쓰기 차단(의도 확인) |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 치명, 참고, 정상 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) |
| 근거 파일 | settings.json / alias.json / settings.json / data_stream.json / alias.json |

**판정 로직**

인덱스 쓰기 차단을 '정상 차단' 과 '문제 차단' 으로 구분한다.

정상(판정 안 함, 건수만 참고): searchable snapshot 마운트 인덱스, 롤오버가 끝난 인덱스
(데이터 스트림의 과거 백킹 인덱스·쓰기 대상이 아닌 alias 멤버·indexing_complete=true).
ILM 의 readonly·shrink·forcemerge·searchable_snapshot 단계는 롤오버 후 인덱스에 write 차단을 거는 것이 정상 동작이다.
문제(치명, IDX-008): index.blocks.read_only_allow_delete=true(대개 flood stage 흔적, 모든 인덱스 대상),
또는 현재 쓰기 대상(데이터 스트림 write index / alias write index)에 write·read_only 차단.
확인 필요(참고, IDX-011): 데이터 스트림·alias 에 속하지 않는 단독 인덱스의 write·read_only 차단(의도적 보관일 수 있음).

### IDX-009 — 존재하지 않는 data tier 를 요구하는 인덱스

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_tier_preference` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 치명 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) 그리고 (nodes.json) |
| 근거 파일 | settings.json / nodes.json |

**판정 로직**

인덱스가 요구하는 데이터 tier 가 실제 노드에 존재하는지.

### SHD-005 — 인덱스/샤드 규모 요약

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_index_count` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 필요 입력 | (cluster_stats.json) |
| 근거 파일 | cluster_stats.json |
| 참고 문서 | [샤드 사이징 가이드](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

샤드당 평균 크기(store / shards) < 200MB 이고 샤드 >= 300 이며 전체 store > 50GB → 주의. 그 외에는 규모 요약만 참고로 표기.

## 과다 샤딩 · 소형 샤드

### OVS-001 — 인덱스 단위 과다 샤딩

| 항목 | 내용 |
| --- | --- |
| 함수 | `sharding.r_index_oversharding` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `oversharding_excess_ratio_warn` = 0.1 — [도구] 전체 샤드 대비 비중<br>`oversharding_excess_warn` = 20 — [도구] 줄일 수 있는 샤드 합계<br>`oversharding_floor_shard_gb` = 10 — [공식] 샤드 권장 하한 10GB<br>`oversharding_target_shard_gb` = 50 — [공식] 샤드 권장 상한 50GB(권장 primary 수 산정)<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (indices_stats.json) 그리고 (indices.json 또는 shards.json 또는 cat_shards.txt) |
| 근거 파일 | indices_stats.json / indices.json / settings.json / indices_stats.json / settings.json |
| 참고 문서 | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

인덱스 단위 과다 샤딩.

대상: 사용자 인덱스 중 primary >= 2 이고 데이터 스트림 write index·searchable snapshot 이 아닌 것.
fully mounted(cold) 인덱스는 크기는 정확하지만 shrink 할 수 없으므로 과다 건수만 집계해 원인 조치를 안내한다.
판정: primary 샤드당 평균 크기 < oversharding_floor_shard_gb(공식 하한 10GB) 이면 과다.
권장 primary 수 = max(1, ceil(primary 전체 크기 / oversharding_target_shard_gb(공식 상한 50GB)))
— 샤드당 50GB 를 넘지 않는 최소 개수. 초과 샤드 = (현재 − 권장) × (1 + replica).
초과 샤드 합계 >= oversharding_excess_warn 또는 전체 샤드 대비 비중 >= oversharding_excess_ratio_warn → 주의,
그 외 대상이 있으면 참고.

### OVS-002 — 데이터 스트림 롤오버 과다(작은 백킹 인덱스 누적)

| 항목 | 내용 |
| --- | --- |
| 함수 | `sharding.r_datastream_small_rollover` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의 |
| 임계값 | `ds_min_backing_indices` = 5 — [도구] 데이터 스트림 판정 최소 백킹 수<br>`ds_small_backing_shard_gb` = 1 — [도구] 백킹 샤드 중앙값 기준<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (data_stream.json) 그리고 (indices_stats.json) |
| 근거 파일 | data_stream.json / indices_stats.json |
| 참고 문서 | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

데이터 스트림의 롤오버가 너무 잦아 작은 백킹 인덱스가 쌓이는지 확인한다.

write index 와 partial(frozen) 마운트 백킹 인덱스(크기가 캐시 크기)를 제외한 백킹 인덱스가
ds_min_backing_indices 개 이상이고, 그 primary 샤드당 크기의 중앙값이
ds_small_backing_shard_gb 미만이면 주의. 롤오버가 max_age 로만 일어나고 있다는 전형적인 신호다.

### OVS-003 — 사용자 샤드 크기 분포

| 항목 | 내용 |
| --- | --- |
| 함수 | `sharding.r_shard_size_distribution` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `oversharding_min_data_gb` = 100 — [도구] 소규모 클러스터는 분포 판정 제외<br>`oversharding_min_shards` = 20 — [도구] 분포 판정 최소 표본<br>`oversharding_small_share_warn` = 0.8 — [도구] 10GB 미만 비중 |
| 필요 입력 | (indices.json 또는 shards.json 또는 cat_shards.txt) |
| 근거 파일 | indices.json |
| 참고 문서 | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

사용자 인덱스 primary 샤드의 크기 분포(<1GB / 1~10GB / 10~50GB / 50GB+)를 사실 그대로 보고한다.

데이터가 있는(문서 1건 이상) 사용자 primary(partial 마운트·write index 제외, fully mounted 는 포함)가 oversharding_min_shards 개 이상이고,
그중 10GB 미만 비중 >= oversharding_small_share_warn 이며 사용자 데이터 합계가 oversharding_min_data_gb 이상이면
'클러스터 전반의 과다 샤딩 경향' 으로 주의. 조건에 못 미치면 분포만 참고로 표기.

## 공식 가이드 기준 (설정 · 샤드 · 성능 · 디스크 · 벡터)

### GEN-001 — max_result_window 상향 인덱스

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_large_result_sets` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) |
| 근거 파일 | settings.json |
| 참고 문서 | [General recommendations](https://www.elastic.co/docs/deploy-manage/production-guidance/general-recommendations) |

**판정 로직**

max_result_window 상향 여부(사용자 인덱스).

### GEN-002, GEN-003 — http.max_content_length 상향

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_large_documents` |
| 판정 항목 | GEN-002 http.max_content_length 상향 / GEN-003 평균 문서 크기가 큰 인덱스 |
| 근거 구분 | 공식 기준 / 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `avg_doc_bytes_warn` = 1MiB — [도구] 문서 평균 1MB<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (nodes.json) 그리고 (indices_stats.json) |
| 근거 파일 | indices_stats.json / nodes.json |
| 참고 문서 | [General recommendations](https://www.elastic.co/docs/deploy-manage/production-guidance/general-recommendations) |

**판정 로직**

http.max_content_length 상향 및 평균 문서 크기.

### CFG-001 — cluster.name 이 기본값

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_cluster_name` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의 |
| 필요 입력 | (cluster_health.json) |
| 근거 파일 | cluster_health.json |
| 참고 문서 | [Important settings configuration](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/important-settings-configuration) |

**판정 로직**

cluster.name 이 기본값 'elasticsearch' 이면 주의. ECH/ECE/ECK 로 감지되면 참고.

### CFG-002, CFG-003 — data/logs 경로가 ES 설치 디렉터리 내부(archive 설치)

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_path_settings` |
| 판정 항목 | CFG-002 data/logs 경로가 ES 설치 디렉터리 내부(archive 설치) / CFG-003 path.data 다중 경로 사용 |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의 |
| 필요 입력 | (nodes.json) |
| 근거 파일 | nodes.json |
| 참고 문서 | [Important settings configuration](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/important-settings-configuration) |

**판정 로직**

path.data/path.logs 위치.

공식 문서의 우려는 archive(tar.gz/zip) 설치에서 업그레이드 시 $ES_HOME 을 교체하며 데이터가 함께
지워지는 것이다. rpm/deb 는 기본 경로가 이미 외부(/var/lib, /var/log)이고, docker 는 볼륨을
마운트하는 구조라 대상이 아니다. build_type 으로 판별한다.

### CFG-004, CFG-005, CFG-006 — discovery.seed_hosts 미설정

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_discovery` |
| 판정 항목 | CFG-004 discovery.seed_hosts 미설정 / CFG-005 cluster.initial_master_nodes 잔존 / CFG-006 development mode 로 동작 중인 노드 |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의 |
| 필요 입력 | (nodes.json) |
| 근거 파일 | nodes.json / nodes.json (transport_address) |
| 참고 문서 | [Important settings configuration](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/important-settings-configuration) |

**판정 로직**

다중 노드인데 discovery.seed_hosts / seed_providers 가 없음 → 주의(CFG-004). cluster.initial_master_nodes 가 남아 있음 → 주의(CFG-005). 실제 바인딩된 transport_address 가 loopback 이거나 discovery.type=single-node → 주의(CFG-006). 오케스트레이터 배포면 모두 참고로 하향.

### CFG-007, CFG-008, CFG-009 — OOM heap dump 설정 없음

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_jvm_diag_settings` |
| 판정 항목 | CFG-007 OOM heap dump 설정 없음 / CFG-008 GC 로그 파일 출력 비활성 / CFG-009 JVM fatal error 로그 경로 미지정 |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의, 참고 |
| 필요 입력 | (nodes.json) |
| 근거 파일 | nodes.json (jvm.input_arguments) |
| 참고 문서 | [Important settings configuration](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/important-settings-configuration) |

**판정 로직**

jvm.input_arguments 기준. HeapDumpOnOutOfMemoryError 없음 → 주의(CFG-007). 마지막 -Xlog:disable 이후 gc 파일 로깅 옵션 없음 → 주의(CFG-008). ErrorFile 없음 → 참고(CFG-009). 오케스트레이터 배포면 참고로 하향.

### SHD-007, SHD-008 — 샤드 문서 수가 Lucene 한계에 근접

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_docs_per_shard` |
| 판정 항목 | SHD-007 샤드 문서 수가 Lucene 한계에 근접 / SHD-008 샤드당 문서 수 권장치 초과 |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 치명, 주의 |
| 임계값 | `docs_per_shard_crit` = 1,500,000,000 — [도구] Lucene 한계(2,147,483,519) 접근 경보<br>`docs_per_shard_warn` = 200,000,000 — [공식] 샤드당 2억건 미만 권장<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (indices.json 또는 shards.json 또는 cat_shards.txt) 그리고 (indices_stats.json) |
| 근거 파일 | indices.json |
| 참고 문서 | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

샤드별 문서 수. 인덱스 평균이 아니라 샤드 단위(cat shards) 값으로 판정한다.

Lucene 한계(2,147,483,519)는 삭제 문서를 포함한 maxDoc 기준이다. cat shards 에는 삭제 수가 없어
인덱스 삭제 수를 primary 수로 나눈 값을 더한다(추정치임을 표기).

### SHD-009 — 마스터 노드 heap 대비 인덱스 수 과다

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_master_heap_per_index` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 치명, 주의 |
| 임계값 | `indices_per_gb_master_heap` = 3,000 — [공식] 마스터 heap 1GB당 인덱스 3000개 |
| 필요 입력 | (nodes.json) 그리고 (cluster_stats.json) |
| 근거 파일 | cluster_stats.json / nodes.json |
| 참고 문서 | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

마스터 후보 노드 heap 1GB당 인덱스 3000개 기준.

### SHD-010 — 매핑 메타데이터가 heap 을 과도하게 점유

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_mapping_heap_overhead` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의, 정상 |
| 임계값 | `heap_baseline_bytes` = 512MiB — [공식] 필드 매퍼 산정 시 추가 여유 0.5GB<br>`mapping_heap_pct_warn` = 50 — [도구] 매핑 오버헤드 추정 / heap |
| 필요 입력 | (nodes_stats.json) 그리고 (cluster_stats.json) |
| 근거 파일 | cluster_stats.json / nodes_stats.json |
| 참고 문서 | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

데이터 노드별 필요 heap 추정 = cluster state 매핑 크기(중복 제거) + 노드 필드 오버헤드 + 0.5GB(공식 산정식).

추정치 / heap_max >= mapping_heap_pct_warn → 주의, 미만 → 정상. 전용 마스터·ML 노드는 산정 대상이 아니다.

### SHD-011 — 빈 인덱스 다수

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_empty_indices` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의 |
| 임계값 | `empty_index_count_warn` = 5 — [도구]<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (indices_stats.json) |
| 근거 파일 | indices_stats.json |
| 참고 문서 | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

docs.count=0 인 사용자 인덱스 수 >= empty_index_count_warn → 주의.

현재 쓰기 대상(데이터 스트림 write index, alias write index)은 막 롤오버되어 비어 있을 수 있으므로 제외한다.

### SHD-012 — 색인량 많은 인덱스에 total_shards_per_node 미설정

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_total_shards_per_node` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 참고 |
| 임계값 | `heavy_index_docs` = 10,000,000 — [도구] 대량 색인 인덱스 기준<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) 그리고 (indices_stats.json) |
| 근거 파일 | settings.json / indices_stats.json |
| 참고 문서 | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

핫스팟 방지용 index.routing.allocation.total_shards_per_node 설정 여부(대형 색인 인덱스).

### PERF-004 — 쓰기 대상 샤드당 indexing buffer 부족

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_index_buffer` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 참고 |
| 임계값 | `index_buffer_per_shard_warn` = 32MiB — [도구] 쓰기 대상 샤드당(공식 상한은 512MB) |
| 필요 입력 | (nodes.json) 그리고 (indices.json 또는 shards.json 또는 cat_shards.txt) |
| 근거 파일 | nodes.json / data_stream.json / indices.json |
| 참고 문서 | [Tune for indexing speed](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/indexing-speed) |

**판정 로직**

샤드당 indexing buffer.

indices.memory.index_buffer_size(기본 heap 10%)는 '최근 쓰기가 있는(active) 샤드' 가 나눠 쓴다.
5분 이상 쓰기가 없는 샤드는 inactive 로 버퍼를 반납한다. 번들에서 active 여부를 직접 알 수 없으므로
쓰기 대상으로 확정 가능한 샤드(데이터 스트림 write index + 수집 순간 색인 중인 인덱스)만 센다.

### PERF-005 — 열린 search context 과다

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_open_contexts` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의 |
| 임계값 | `open_contexts_warn` = 100 — [도구] |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |
| 참고 문서 | [Tune for search speed](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/search-speed) |

**판정 로직**

노드 search.open_contexts >= open_contexts_warn → 주의.

### PERF-006 — 기본 검색 타임아웃 미설정

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_search_timeout` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 참고 |
| 필요 입력 | (cluster_settings.json) |
| 근거 파일 | cluster_settings.json |
| 참고 문서 | [Tune for search speed](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/search-speed) |

**판정 로직**

search.default_search_timeout 이 미설정 또는 -1(무제한)이면 참고.

### PERF-007 — 검색 부하 대비 replica 수가 적은 인덱스

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_replica_throughput` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 참고 |
| 임계값 | `search_heavy_query_total` = 100,000 — [도구] 검색 부하 인덱스 기준<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) 그리고 (indices_stats.json) 그리고 (indices.json 또는 shards.json 또는 cat_shards.txt) |
| 근거 파일 | settings.json / indices_stats.json |
| 참고 문서 | [Tune for search speed](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/search-speed) |

**판정 로직**

search-speed 의 권장식: replicas = max(max_failures, ceil(num_nodes/num_primaries) - 1).

### PERF-008 — index.store.preload 사용 인덱스

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_store_preload` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `preload_index_count_warn` = 5 — [도구]<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) |
| 근거 파일 | settings.json |
| 참고 문서 | [Tune for search speed](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/search-speed)<br>[Tune approximate kNN search](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/approximate-knn-search) |

**판정 로직**

index.store.preload 가 설정된 인덱스가 있으면 참고, 그 수 > preload_index_count_warn 이면 주의.

### PERF-009 — 네트워크 파일시스템 기반 데이터 경로

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_remote_storage` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의 |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |
| 참고 문서 | [Tune for indexing speed](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/indexing-speed)<br>[Tune for search speed](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/search-speed) |

**판정 로직**

nodes_stats fs.data[].type 에 nfs / cifs / smb / fuse / glusterfs / ceph 가 포함되면 주의.

### DISK-006 — 대형 standard 인덱스에 기본 codec 사용

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_codec` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 참고 |
| 임계값 | `codec_check_min_bytes` = 50GiB — [도구]<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) 그리고 (indices_stats.json) |
| 근거 파일 | settings.json / indices_stats.json |
| 참고 문서 | [Tune for disk usage](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/disk-usage) |

**판정 로직**

standard 모드 사용자 인덱스 중 primary store >= codec_check_min_bytes 이고 index.codec 이 default(미지정) → 참고. logsdb·time_series 는 best_compression 이 기본이라 제외.

### DISK-007 — _source 비활성 인덱스

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_source_mode` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) |
| 근거 파일 | settings.json |
| 참고 문서 | [Tune for disk usage](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/disk-usage) |

**판정 로직**

index.mapping.source.mode=disabled → 주의. 그 외 모드(synthetic 등) 지정 → 참고.

### MAP-003 — 동적 매핑 통제가 없는 인덱스 템플릿

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_dynamic_mapping` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 참고 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (index_templates.json) |
| 근거 파일 | index_templates.json / component_templates.json |
| 참고 문서 | [Tune for disk usage](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/disk-usage)<br>[Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

컴포넌트까지 병합한 결과 기준으로 동적 매핑 통제 여부를 본다.

### VEC-001 — 벡터 데이터 사용 현황

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_vector_memory` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수<br>`vector_vs_fscache_pct_warn` = 60 — [도구] 벡터 상주량 / (RAM - heap) |
| 필요 입력 | (indices_stats.json) 그리고 (nodes_stats.json) |
| 근거 파일 | indices_stats.json / indices_stats.json / nodes_stats.json |
| 참고 문서 | [Tune approximate kNN search](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/approximate-knn-search) |

**판정 로직**

인덱스별 dense_vector off-heap(total, 없으면 primaries). 상주 필요량 = (veq+veb 가 있으면 그 값, 없으면 vec) + vex. 합계 / Σ(데이터 노드 RAM − heap) >= vector_vs_fscache_pct_warn → 주의, 미만 → 참고. 노드별 분포는 보지 않는 클러스터 합계 추정이다.

### VEC-002, VEC-003 — 고차원 float 벡터에 비양자화 인덱스 사용

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_vector_quantization` |
| 판정 항목 | VEC-002 고차원 float 벡터에 비양자화 인덱스 사용 / VEC-003 _source 벡터 제외 설정 미지정 |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수<br>`vector_dim_quantize_warn` = 384 — [공식] 384차원 이상 float 벡터는 양자화 권장 |
| 필요 입력 | (index_templates.json) |
| 근거 파일 | index_templates.json / component_templates.json |
| 참고 문서 | [Tune approximate kNN search](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/approximate-knn-search) |

**판정 로직**

고차원 float 벡터의 양자화 여부 (컴포넌트 병합 후 판정).

8.14 부터 dense_vector 의 index_options 를 지정하지 않으면 양자화 HNSW 가 기본 적용된다.
따라서 '미지정' 은 8.14 이상에서 문제로 보지 않고, 비양자화 타입(hnsw/flat)을 명시한 경우만 판정한다.

### VEC-004 — 벡터 인덱스의 세그먼트 수 과다

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_vector_segments` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수<br>`vector_segments_per_shard_warn` = 20 — [도구] |
| 필요 입력 | (indices_stats.json) 그리고 (indices.json 또는 shards.json 또는 cat_shards.txt) |
| 근거 파일 | indices_stats.json / settings.json |
| 참고 문서 | [Tune approximate kNN search](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/approximate-knn-search) |

**판정 로직**

벡터 데이터가 있는 인덱스의 primary 세그먼트 / primary 샤드 >= vector_segments_per_shard_warn → 주의.

## 핫스팟 · 밸런싱

### HOT-005.(하위 항목) — 

| 항목 | 내용 |
| --- | --- |
| 함수 | `hotspot.r_tier_saturation` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의 |
| 임계값 | `load_per_cpu_warn` = 1.0 — [도구] load15 / CPU 코어<br>`tier_cpu_pct_warn` = 75 — [도구] tier 전체 포화 판정 CPU% |
| 필요 입력 | (nodes_stats.json) 그리고 (nodes.json) |
| 근거 파일 | nodes_stats.json |
| 참고 문서 | [Hot spotting 문제 해결](https://www.elastic.co/docs/troubleshoot/elasticsearch/hotspotting) |

**판정 로직**

tier 단위 CPU 포화. 한 tier 의 모든 노드가 load15/CPU >= load_per_cpu_warn 또는 CPU% >= tier_cpu_pct_warn 이면 주의.

노드 간 '편중'(HOT-001)과 다르다. 부하가 고르게 분산되어도 tier 전체가 한계에 있으면 노드를 추가하거나 부하를 줄여야 한다.
그 tier 의 cgroup CPU throttling(OS-003)과 쓰기 스레드풀 rejection(TP-001)을 근거로 함께 제시한다.

### HOT-001 — 같은 tier 안에서 자원 사용률 편중(hot spotting 의심)

| 항목 | 내용 |
| --- | --- |
| 함수 | `hotspot.r_resource_hotspot` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의, 정상 |
| 임계값 | `disk_imbalance_pct_warn` = 15 — [도구] 노드 간 디스크 사용률 편차(%p)<br>`hotspot_cpu_pct_floor` = 50 — [도구]<br>`hotspot_cpu_pct_gap` = 40 — [도구]<br>`hotspot_disk_pct_floor` = 50 — [도구]<br>`hotspot_heap_pct_floor` = 70 — [도구] 최대값이 이 미만이면 무시<br>`hotspot_heap_pct_gap` = 30 — [도구] 노드 간 heap 편차(%p) |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |
| 참고 문서 | [Hot spotting 문제 해결](https://www.elastic.co/docs/troubleshoot/elasticsearch/hotspotting) |

**판정 로직**

같은 tier 안에서 heap% / CPU% / 디스크% 가 일부 노드에 편중되는지(공식 hot spotting 탐지 지표).

tier 가 다르면 역할과 부하가 달라 비교하지 않는다. frozen tier 디스크는 shared cache 선점유라 제외.
지표별로 tier 내 최대−최소 >= gap 이고 최대값 >= floor 일 때 주의. 수집 순간값이다.

### HOT-002.(하위 항목) — 

| 항목 | 내용 |
| --- | --- |
| 함수 | `hotspot.r_workload_hotspot` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의 |
| 임계값 | `workload_skew_ratio_warn` = 1.8 — [도구] 최대 노드 / 평균 |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |
| 참고 문서 | [Hot spotting 문제 해결](https://www.elastic.co/docs/troubleshoot/elasticsearch/hotspotting) |

**판정 로직**

같은 tier 안에서 노드별 누적 색인/검색 작업량 편중(최대 노드 / tier 평균 >= workload_skew_ratio_warn → 주의).

누적값이며 replica 작업이 포함된다. uptime 이 다르면 왜곡되므로 시간당 환산값을 함께 제시한다.

### HOT-003, HOT-004 — desired balance 미수렴 샤드

| 항목 | 내용 |
| --- | --- |
| 함수 | `hotspot.r_desired_balance` |
| 판정 항목 | HOT-003 desired balance 미수렴 샤드 / HOT-004 밸런스 계산 미완료 |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `undesired_shards_warn` = 1 — [도구] |
| 필요 입력 | (allocation.json 또는 cat_allocation.txt) |
| 근거 파일 | allocation.json / internal_desired_balance.json / internal_desired_balance.json |
| 참고 문서 | [Unbalanced cluster 문제 해결](https://www.elastic.co/docs/troubleshoot/elasticsearch/troubleshooting-unbalanced-cluster)<br>[Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

desired balance 미수렴(원하는 위치에 있지 않은 샤드).

### REC-001 — 복구 진행 중 — 복구 대역 제한 확인

| 항목 | 내용 |
| --- | --- |
| 함수 | `hotspot.r_recovery_settings` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 참고 |
| 임계값 | `recovery_rate_low_bytes` = 40MiB — [공식] indices.recovery.max_bytes_per_sec 기본값 40mb 이하 |
| 필요 입력 | (cluster_settings.json) |
| 근거 파일 | cluster_settings.json / recovery.json |
| 참고 문서 | [복구(recovery) 설정](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/index-recovery-settings) |

**판정 로직**

복구 대역 제한.

indices.recovery.max_bytes_per_sec 의 기본값(40mb)은 그 자체로 문제가 아니다.
복구·재배치가 실제로 진행 중일 때만 복구 시간의 병목 후보로 보고한다.

### TPL-001 — 레거시 템플릿이 composable 템플릿에 가려짐(추정)

| 항목 | 내용 |
| --- | --- |
| 함수 | `hotspot.r_template_conflict` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (templates.json) 그리고 (index_templates.json) |
| 근거 파일 | templates.json / index_templates.json |

**판정 로직**

레거시(_template) 템플릿이 composable(_index_template) 템플릿에 가려지는지.

composable 템플릿이 하나라도 매칭되면 레거시 템플릿은 적용되지 않는다(공식 동작).
또한 composable 끼리 같은 우선순위로 겹치는 경우는 ES 가 생성을 거부하므로 여기서 보지 않는다.
패턴 겹침은 와일드카드 비교로 추정한다.

### CLU-021 — node_left 지연 할당이 비활성화된 인덱스

| 항목 | 내용 |
| --- | --- |
| 함수 | `hotspot.r_delayed_allocation` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) |
| 근거 파일 | settings.json |

**판정 로직**

노드 재기동 시 즉시 재복제를 막는 delayed_timeout 설정.

## 운영 · 보안

### OPS-007 — 모니터링 구성 확인 필요

| 항목 | 내용 |
| --- | --- |
| 함수 | `ops.r_monitoring` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 참고 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (indices_stats.json) |
| 근거 파일 | indices_stats.json / indices_stats.json / cluster_settings.json |

**판정 로직**

클러스터 모니터링 데이터 존재 여부(OPS-007, 참고).

이 클러스터 안에 스택 모니터링 데이터(.monitoring-* 또는 *stack_monitoring* 데이터 스트림)가 있으면 자기 자신에게
수집하는 구성이다(운영 환경은 별도 모니터링 클러스터 권장). 없으면 별도 클러스터로 보내는지 번들만으로 알 수 없으므로
확인을 안내한다. 레거시 내부 수집(xpack.monitoring.collection.enabled=true)도 함께 표기한다.

### LIC-001 — 라이선스 정상

| 항목 | 내용 |
| --- | --- |
| 함수 | `ops.r_license` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 치명, 주의, 정상 |
| 임계값 | `license_expiry_days_crit` = 30 — [도구]<br>`license_expiry_days_warn` = 90 — [도구] |
| 필요 입력 | (licenses.json) |
| 근거 파일 | licenses.json |

**판정 로직**

license.status != active → 치명. 만료까지 <= license_expiry_days_crit 일 → 치명, <= warn 일 → 주의, 그 외 정상. 기준 시각은 번들 수집 시각.

### SNP-001, SNP-002, SNP-007, SNP-003, SNP-004, SNP-006, SNP-005 — 스냅샷 저장소 미설정

| 항목 | 내용 |
| --- | --- |
| 함수 | `ops.r_snapshots` |
| 판정 항목 | SNP-001 스냅샷 저장소 미설정 / SNP-002 실패/부분 스냅샷 존재 / SNP-007 현재 실패 중인 SLM 정책 / SNP-003 성공한 스냅샷 없음 / SNP-004 진행 중인 스냅샷 / SNP-006 SLM 중지 상태 / SNP-005 SLM 스냅샷 실패 누적 |
| 근거 구분 | 도구 판단 / 사실 보고 |
| 가능 심각도 | 치명, 주의, 참고, 정상 |
| 임계값 | `snapshot_age_hours_crit` = 168 — [도구] 7일<br>`snapshot_age_hours_warn` = 36 — [도구] 최근 스냅샷 경과 시간<br>`snapshot_failed_warn` = 1 — [도구]<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (repositories.json 또는 snapshot.json) |
| 근거 파일 | commercial/slm_stats.json / commercial/slm_status.json / repositories.json / slm_policies.json / snapshot.json |

**판정 로직**

저장소도 스냅샷도 없음 → 치명(SNP-001). FAILED/PARTIAL 스냅샷 존재 → 치명(SNP-002). 마지막 '성공(SUCCESS)' 스냅샷 경과(snapshot.json 에 시각이 없으면 SLM 정책의 last_success 시각) >= snapshot_age_hours_crit → 치명, >= warn → 주의, 그 외 정상(SNP-003, 진행 중·실패·부분 스냅샷은 RPO 산정에서 제외). 시각 정보가 있는데 성공 스냅샷이 없으면 치명. IN_PROGRESS 존재 → 참고(SNP-004). SLM 누적 실패 >= snapshot_failed_warn → 주의(SNP-005). SLM operation_mode != RUNNING → 주의(SNP-006). SLM 정책의 마지막 실패가 마지막 성공보다 최근이면 치명(SNP-007).

### ILM-001, ILM-002, ILM-003 — ILM 중지 상태

| 항목 | 내용 |
| --- | --- |
| 함수 | `ops.r_ilm` |
| 판정 항목 | ILM-001 ILM 중지 상태 / ILM-002 ILM 오류 상태 인덱스 / ILM-003 ILM 미적용 대형 인덱스 |
| 근거 구분 | 도구 판단 / 사실 보고 |
| 가능 심각도 | 치명, 주의, 참고 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (ilm_explain.json 또는 ilm_status.json) |
| 근거 파일 | commercial/ilm_explain.json / commercial/ilm_status.json |

**판정 로직**

ILM operation_mode != RUNNING → 주의(ILM-001). ilm_explain 의 step=ERROR 또는 failed_step 존재 → 롤오버 관련 단계 실패가 있으면 치명, 그 외(삭제·축소·이동 단계, write index 삭제 실패 등)는 주의(ILM-002). ILM 미적용(managed=false) 사용자 인덱스 중 primary > 10GB → 참고(ILM-003).

### ML-001, ML-002 — Transform 실패 상태

| 항목 | 내용 |
| --- | --- |
| 함수 | `ops.r_ml_transform` |
| 판정 항목 | ML-001 Transform 실패 상태 / ML-002 ML 이상탐지 job 실패 |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 주의 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (transform_stats.json 또는 ml_anomaly_detectors.json) |
| 근거 파일 | commercial/ml_anomaly_detectors.json / commercial/transform_stats.json |

**판정 로직**

transform state 가 failed/aborting → 주의(ML-001). 이상탐지 job state=failed → 주의(ML-002).

### SEC-001 — TLS 인증서 만료 여유

| 항목 | 내용 |
| --- | --- |
| 함수 | `ops.r_certificates` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 치명, 주의, 정상 |
| 임계값 | `cert_expiry_days_crit` = 30 — [도구]<br>`cert_expiry_days_warn` = 90 — [도구] |
| 필요 입력 | (ssl_certs.json) |
| 근거 파일 | ssl_certs.json |

**판정 로직**

ssl_certs.json 의 인증서 만료까지 <= cert_expiry_days_crit 일 → 치명, <= warn 일 → 주의, 그 외 정상. 기준 시각은 번들 수집 시각.

### SEC-002 — 보안 기능 활성화

| 항목 | 내용 |
| --- | --- |
| 함수 | `ops.r_security_enabled` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 치명, 정상 |
| 필요 입력 | (xpack.json) |
| 근거 파일 | commercial/xpack.json |

**판정 로직**

xpack security.enabled=false → 치명, 그 외 정상.

### OPS-001 — GeoIP 데이터베이스 갱신 이슈

| 항목 | 내용 |
| --- | --- |
| 함수 | `ops.r_geoip` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 참고 |
| 필요 입력 | (geoip_stats.json) |
| 근거 파일 | geoip_stats.json |

**판정 로직**

GeoIP failed_downloads 또는 expired_databases > 0 → 참고(폐쇄망에서는 정상일 수 있음).

### OPS-002 — CCR 복제 오류

| 항목 | 내용 |
| --- | --- |
| 함수 | `ops.r_ccr` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 주의 |
| 필요 입력 | (ccr_stats.json) |
| 근거 파일 | commercial/ccr_stats.json |

**판정 로직**

CCR follower 샤드에 read_exceptions 또는 failed_read/write_requests 가 있으면 주의.

## 매핑 · ILM 정책 · 클러스터 조정 · 세부 통계

### PERF-011 — 

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_search_usage` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `search_expensive_share_warn` = 10 — [도구] 비용이 큰 쿼리 유형의 검색 대비 비중(%)                    # [도구] 기동 이후 평균 디스크 사용률                # [공식] 롤오버 샤드 크기 권장 상한 |
| 필요 입력 | (cluster_stats.json) |
| 근거 파일 | cluster_stats.json (indices.search) |

**판정 로직**

cluster_stats.indices.search 의 쿼리 유형·검색 구성 요소별 사용 횟수(누적)로 비용이 큰 검색 패턴의 비중을 본다.

비용이 큰 유형(EXPENSIVE: nested·parent-child 조인·script·wildcard·regexp·fuzzy·prefix·query_string·
runtime_mappings·script_fields)의 사용 비중이 search_expensive_share_warn(%) 이상이면 주의(PERF-011), 사용은 있으나
비중이 낮으면 참고. 쿼리 본문이 아니라 유형별 횟수이므로 '어떤 인덱스의 어떤 쿼리' 인지는 알 수 없다.

### DISK-008 — 

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_disk_io_utilization` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `disk_io_busy_pct_warn` = 60 |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json (fs.io_stats) |

**판정 로직**

데이터 노드의 평균 디스크 사용률 = fs.io_stats.total.io_time_in_millis / JVM uptime (Linux 에서만 수집).

io_time 은 ES 기동 이후 장치가 I/O 를 처리한 누적 시간이다. >= disk_io_busy_pct_warn → 주의(DISK-008), 그 외 참고.
여러 장치를 쓰면 합계라 100%% 를 넘을 수 있어 장치 수로 나눈 값을 쓴다. 누적 평균이므로 순간 포화는 가려질 수 있다.

### MAP-004, MAP-005, MAP-006 — 필드 수가 매핑 한도에 근접한 인덱스

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_mapping_limits_actual` |
| 판정 항목 | MAP-004 필드 수가 매핑 한도에 근접한 인덱스 / MAP-005 text 필드에 fielddata 활성화 / MAP-006 nested 필드 수가 한도에 근접 |
| 근거 구분 | 공식 기준 / 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `mapping_fields_near_limit_pct` = 90 — [도구] total_fields.limit 대비 필드 수<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (mapping.json) |
| 근거 파일 | mapping.json / mapping.json / settings.json |
| 참고 문서 | [Mapping limit settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/mapping-limit)<br>[fielddata mapping parameter](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/text#fielddata-mapping-param) |

**판정 로직**

mapping.json 의 실제 매핑으로 인덱스별 필드 수를 공식 산정 방식(필드·object·multi-field·runtime 각 1개)으로 센다.

필드 수 >= total_fields.limit × mapping_fields_near_limit_pct → 주의(MAP-004, ignore_dynamic_beyond_limit=true 면 참고).
text 필드의 fielddata=true → 주의(MAP-005). nested 필드 수 >= nested_fields.limit × 80% → 주의(MAP-006).

### VEC-005 — 실제 인덱스의 고차원 float 벡터가 비양자화

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_vector_mapping_actual` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수<br>`vector_dim_quantize_warn` = 384 — [공식] 384차원 이상 float 벡터는 양자화 권장 |
| 필요 입력 | (mapping.json) |
| 근거 파일 | mapping.json |
| 참고 문서 | [Tune approximate kNN search](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/approximate-knn-search) |

**판정 로직**

실제 인덱스 매핑에서 비양자화(hnsw·flat)를 명시한 고차원 float dense_vector 를 찾는다(VEC-005, 주의).

8.14 미만에서는 index_options 미지정도 비양자화이므로 포함한다. 템플릿 기준 판정(VEC-002)을 실제 인덱스로 보완한다.

### ILM-004, ILM-005, ILM-006 — 크기 기준 없이 롤오버하는 ILM 정책

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_ilm_policies` |
| 판정 항목 | ILM-004 크기 기준 없이 롤오버하는 ILM 정책 / ILM-005 롤오버 샤드 크기 기준이 권장 상한 초과 / ILM-006 삭제 단계가 없는 ILM 정책 |
| 근거 구분 | 공식 기준 / 사실 보고 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `ilm_rollover_max_shard_gb` = 50<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (ilm_policies.json) |
| 근거 파일 | ilm_policies.json |
| 참고 문서 | [Rollover (ILM)](https://www.elastic.co/docs/reference/elasticsearch/index-lifecycle-actions/ilm-rollover)<br>[Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

사용자 인덱스가 쓰는 ILM 정책의 롤오버·삭제 구성.

hot 롤오버에 max_primary_shard_size(또는 max_size)가 없으면 주의(ILM-004): 공식 권장은 샤드 크기 기준 롤오버이며,
max_age 단독이면 수집량에 따라 작은 인덱스가 쌓인다(OVS-002 의 원인). max_primary_shard_size > 50GB 면 주의(ILM-005).
delete 단계가 없으면 참고(ILM-006, 보존 기간 무제한). Elastic 관리 정책(_meta.managed=true)은 표에 표시만 한다.

### CLU-022 — voting config exclusion 잔존

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_voting_exclusions` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의 |
| 필요 입력 | (cluster_state.json) |
| 근거 파일 | cluster_state.json |
| 참고 문서 | [Voting configuration exclusions](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-cluster-post-voting-config-exclusions) |

**판정 로직**

cluster_state 의 voting_config_exclusions 가 비어 있지 않으면 주의(CLU-022).

마스터 후보를 제거·교체할 때 쓰는 임시 설정이다. 작업 후 지우지 않으면 해당 노드가 투표에서 계속 빠져 정족수 여유가 줄어든다.

### SHUT-001 — 노드 종료(shutdown) 레코드

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_node_shutdown` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 치명, 주의, 참고 |
| 필요 입력 | (nodes_shutdown_status.json) |
| 근거 파일 | nodes_shutdown_status.json |
| 참고 문서 | [Node shutdown API](https://www.elastic.co/docs/api/doc/elasticsearch/group/endpoint-shutdown) |

**판정 로직**

nodes_shutdown_status 의 종료 레코드. STALLED → 치명, IN_PROGRESS → 참고, COMPLETE 인데 노드가 클러스터에 있음 → 주의(SHUT-001).

종료 레코드는 삭제하기 전까지 남는다. 작업 후 남으면 해당 노드로의 샤드 할당이 계속 제한될 수 있다.

### IDX-012 — 샤드 저장소 예외(손상 의심)

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_shard_store_errors` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 치명 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (shard_stores.json) |
| 근거 파일 | shard_stores.json |

**판정 로직**

shard_stores 에 store_exception 이 있는 샤드 사본 → 치명(IDX-012, 데이터 손상 의심).

### OPS-003 — 원격 클러스터 연결 끊김

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_remote_clusters` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 주의 |
| 필요 입력 | (remote_cluster_info.json) |
| 근거 파일 | remote_cluster_info.json |

**판정 로직**

remote_cluster_info 에서 connected=false 인 원격 클러스터 → 주의(OPS-003).

### FRZ-001 — 

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_frozen_cache` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 필요 입력 | (searchable_snapshots_cache_stats.json) |
| 근거 파일 | searchable_snapshots_cache_stats.json |

**판정 로직**

frozen shared cache 통계. eviction 이 캐시 region 수를 넘은 노드가 있으면 주의(FRZ-001), 그 외 데이터가 있으면 참고.

eviction > region 수는 캐시 전체가 최소 한 번 이상 교체되었다는 뜻으로, 검색 대상 대비 캐시가 작다는 신호다(도구 판단).

### PERF-010 — 스크립트 컴파일 한도 발동

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_script_limit` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 주의 |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |

**판정 로직**

nodes_stats.script.compilation_limit_triggered > 0 인 노드 → 주의(PERF-010).

### ING-002 — ingest processor 별 처리 시간

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_ingest_processors` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 참고 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |

**판정 로직**

노드 ingest 통계의 processor 별 누적 처리 시간을 합산해 상위 processor 를 보고한다(ING-002, 참고).

hot threads(RT-001)에서 ingest 가 CPU 를 쓰는 것으로 보일 때 어떤 파이프라인·processor 가 원인인지 확인하는 근거다.

### CLU-024 — 

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_cluster_state_publication` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 주의, 참고 |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |

**판정 로직**

nodes_stats.discovery 의 클러스터 상태 발행 통계.

cluster_state_update.failure 가 있으면 주의(CLU-024). 전체 상태 직렬화 크기(serialized full state, 압축 전)가 있으면
크기와 평균 commit 시간을 참고로 보고한다. 발행은 마스터가 하므로 노드 중 최대값을 쓴다.

### CLU-023 — 노드 간 플러그인 불일치

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_plugin_consistency` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 주의 |
| 필요 입력 | (nodes.json) |
| 근거 파일 | nodes.json |

**판정 로직**

노드별 설치 플러그인(이름·버전)이 모두 같지 않으면 주의(CLU-023).

### ML-003 — ML 모델 배포 이상

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_ml_deployments` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 주의 |
| 필요 입력 | (ml_trained_models_stats.json) |
| 근거 파일 | ml_trained_models_stats.json |

**판정 로직**

trained model 배포의 state 가 started 가 아니거나 할당 상태가 fully_allocated 가 아니면 주의(ML-003).

### OPS-005, OPS-004, OPS-006 — watcher 수동 중지

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_watcher_autoscaling_rollup` |
| 판정 항목 | OPS-005 watcher 수동 중지 / OPS-004 오토스케일링 요구 용량이 현재 용량보다 큼 / OPS-006 rollup job 사용(deprecated) |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 주의, 참고 |
| 필요 입력 | (watcher_stack.json 또는 autoscaling_capacity.json 또는 rollup_jobs.json) |
| 근거 파일 | autoscaling_capacity.json / rollup_jobs.json / watcher_stack.json |

**판정 로직**

watcher 가 수동 중지되었는데 watch 가 있으면 주의(OPS-005). 오토스케일링 요구 용량이 현재 용량보다 크면 참고(OPS-004).
rollup job 이 있으면 참고(OPS-006, rollup 은 downsampling 으로 대체되어 deprecated).

## 런타임 (hot threads · 로그)

### RT-001 — Hot threads 분석

| 항목 | 내용 |
| --- | --- |
| 함수 | `runtime.r_hot_threads` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `hot_thread_pct_warn` = 50 — [도구] 단일 스레드 CPU%<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (nodes_hot_threads.txt) |
| 근거 파일 | nodes_hot_threads.txt |

**판정 로직**

nodes_hot_threads.txt 를 파싱해 스레드별 실제 CPU%(cpu=, 없으면 전체 %)를 추출한다.

최대 CPU% >= hot_thread_pct_warn → 주의, 그 외 참고. 수집 순간 500ms 스냅샷 하나이므로 단독으로 치명 판정하지 않는다.
원인 분류는 각 스레드 스택의 위쪽(실행 중) 프레임부터 시그니처(grok·ingest·painless·regexp·집계·검색·merge 등)를
대조해 처음 맞는 것으로 정한다.

### LOG-001, LOG-000 — 서버 로그 오류 패턴 검출

| 항목 | 내용 |
| --- | --- |
| 함수 | `runtime.r_logs` |
| 판정 항목 | LOG-001 서버 로그 오류 패턴 검출 / LOG-000 서버 로그 미포함 진단 번들 |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 참고, 정상 |
| 임계값 | `log_scan_bytes` = 8MiB — [도구] 로그 파일당 스캔 크기(끝부분)<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 근거 파일 | logs/ / manifest.json |

**판정 로직**

logs/ 디렉터리가 없으면 참고(LOG-000). 있으면 파일당 마지막 log_scan_bytes 만 최대 40개 파일 스캔해 고정 패턴(OOM, 긴 old GC, 마스터 미탐색, CircuitBreaking, rejected execution, 워터마크 초과, 노드 연결 끊김, 매핑 파싱 오류 등) 검출. 검출 패턴 중 가장 높은 심각도로 판정(LOG-001), 없으면 정상.

## 변화 추세 (--baseline 비교 모드)

### DIF-001 — 

| 항목 | 내용 |
| --- | --- |
| 함수 | `diff.r_status_change` |
| 근거 구분 | 비교 계산 |
| 가능 심각도 | 치명, 참고 |
| 근거 파일 | cluster_health.json (두 번들 비교) |

**판정 로직**

두 번들의 cluster status 가 다를 때. 악화 → 치명, 개선 → 참고.

### DIF-002, DIF-003 — 노드 재기동 발생

| 항목 | 내용 |
| --- | --- |
| 함수 | `diff.r_node_restart` |
| 판정 항목 | DIF-002 노드 재기동 발생 / DIF-003 노드 구성 변경 |
| 근거 구분 | 비교 계산 |
| 가능 심각도 | 치명, 주의, 참고 |
| 근거 파일 | nodes.json (두 번들 비교) / nodes_stats.json (두 번들 비교) |

**판정 로직**

같은 이름 노드의 uptime 이 이전보다 작음 → 치명(DIF-002, 재기동). 노드 이탈 → 주의, 신규만 → 참고(DIF-003).

### DIF-005, DIF-004 — 스레드풀 rejection 진행 중

| 항목 | 내용 |
| --- | --- |
| 함수 | `diff.r_rejections_delta` |
| 판정 항목 | DIF-005 스레드풀 rejection 진행 중 / DIF-004 스레드풀 rejection 증가 없음 |
| 근거 구분 | 비교 계산 |
| 가능 심각도 | 치명, 주의, 참고 |
| 임계값 | `rejected_crit` = 1,000 — [도구] 누적 rejection 합계<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 근거 파일 | nodes_stats.json (두 번들 비교) |

**판정 로직**

노드·풀별 rejected 증가분. 합계 > 0 → 주의, >= rejected_crit → 치명(DIF-005). 누적값은 0 이 아니지만 증가분이 0 → 참고(DIF-004, 과거 이력).

### DIF-006 — Old GC 발생 추이

| 항목 | 내용 |
| --- | --- |
| 함수 | `diff.r_gc_delta` |
| 근거 구분 | 비교 계산 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `old_gc_per_hour_warn` = 6 — [도구] 시간당 old GC 횟수<br>`old_gc_time_ratio_warn` = 0.02 — [도구] old GC 누적 시간 / uptime |
| 근거 파일 | nodes_stats.json (두 번들 비교) |

**판정 로직**

old GC 증가분. 시간당 증가 >= old_gc_per_hour_warn 또는 구간 GC 시간 비중 >= old_gc_time_ratio_warn → 주의, 그 외 참고. 카운터가 줄어든(재기동) 노드는 제외.

### DIF-007 — Circuit breaker 발동 진행 중

| 항목 | 내용 |
| --- | --- |
| 함수 | `diff.r_breaker_delta` |
| 근거 구분 | 비교 계산 |
| 가능 심각도 | 치명 |
| 근거 파일 | nodes_stats.json (두 번들 비교) |

**판정 로직**

breaker tripped 증가분 > 0 → 치명.

### DIF-008 — 디스크 증가율 기반 포화 예상

| 항목 | 내용 |
| --- | --- |
| 함수 | `diff.r_disk_projection` |
| 근거 구분 | 비교 계산 |
| 가능 심각도 | 치명, 주의, 참고 |
| 임계값 | `diff_min_hours_for_projection` = 1.0 — [도구] 이보다 짧은 간격은 외삽 안 함<br>`disk_projection_days_warn` = 30 — [도구] |
| 근거 파일 | nodes_stats.json (두 번들 비교) |

**판정 로직**

디스크 증가율로 워터마크 도달 시점 추정.

### DIF-009 — 구간 처리량과 노드 간 분포

| 항목 | 내용 |
| --- | --- |
| 함수 | `diff.r_throughput` |
| 근거 구분 | 비교 계산 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `workload_skew_ratio_warn` = 1.8 — [도구] 최대 노드 / 평균 |
| 근거 파일 | nodes_stats.json (두 번들 비교) |

**판정 로직**

노드별 구간 index_total / query_total 증가분을 초당 처리량으로 환산(replica 작업 포함). 최대 노드 / 평균 >= workload_skew_ratio_warn → 주의, 그 외 참고.

### DIF-010, DIF-011 — 인덱스 증가량 상위

| 항목 | 내용 |
| --- | --- |
| 함수 | `diff.r_index_growth` |
| 판정 항목 | DIF-010 인덱스 증가량 상위 / DIF-011 인덱스 생성·삭제 |
| 근거 구분 | 비교 계산 |
| 가능 심각도 | 참고 |
| 임계값 | `index_growth_min_bytes` = 1GiB — [도구]<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 근거 파일 | indices_stats.json (두 번들 비교) |

**판정 로직**

인덱스 primary store 증가분 > index_growth_min_bytes → 참고(DIF-010). 사용자 인덱스 신규·삭제 → 참고(DIF-011).

### DIF-012 — 판정 결과 변화

| 항목 | 내용 |
| --- | --- |
| 함수 | `diff._finding_delta` |
| 근거 구분 | 비교 계산 |
| 가능 심각도 | 치명, 주의, 참고 |
| 근거 파일 | 두 번들의 판정 결과 비교 |

**판정 로직**

이전 번들과 현재 번들의 치명·주의 판정 ID 를 비교해 신규 발생 / 악화 / 해소 목록을 만든다. 다른 판정의 요약이므로 항상 참고(점수·건수 이중 계산 방지).

## 설정 지식 베이스

SET-001~006 이 사용하는 설정별 공식 기본값·종류·의미·변경 영향입니다(`esdiag/settings_kb.py`).

- 적용 우선순위(공식): transient > persistent > elasticsearch.yml > 기본값
- dynamic 은 `PUT _cluster/settings`(또는 인덱스 설정 API)로 바꿀 수 있고, `null` 로 지정하면 기본값으로 돌아갑니다.
- static 은 모든 대상 노드의 elasticsearch.yml 에서만 바꿀 수 있고 재기동이 필요합니다. 인덱스 static 설정은 닫힌 인덱스에서만 바꿀 수 있습니다.
- 번들의 `cluster_settings_defaults` 는 yml 값이 반영된 값이고, API 로 명시한 키는 기본값을 보고하지 않습니다. 그래서 '원래 기본값' 은 이 표(공식 문서 기준 9.4)를 사용합니다.
- ↑ 는 기본값보다 크게, ↓ 는 작게 바꿨을 때의 영향입니다. 이 표에 없는 설정은 리포트에 '설명 미등록' 으로 값만 표기합니다.

| 설정 | 기본값 | 종류 | 범위 | 의미 | 변경 영향 | 위험도(↑/↓) | 문서 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `action.auto_create_index` | true | dynamic | cluster | 존재하지 않는 인덱스로 색인 시 자동 생성 허용 여부(패턴 지정 가능). | 제한하면 오타 인덱스 생성은 막지만, 허용 패턴에 없는 수집 대상은 색인이 실패합니다. 데이터 스트림·시스템 인덱스 패턴이 빠지면 기능이 멈출 수 있습니다. | INFO | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `action.destructive_requires_name` | true | dynamic | cluster | 와일드카드·_all 로 인덱스를 삭제하지 못하게 막음(8.0 부터 기본 true). | false 면 DELETE * 같은 요청 하나로 전체 인덱스가 삭제될 수 있습니다. | WARNING | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `bootstrap.memory_lock` | false | static | node | heap 을 RAM 에 고정(swap 방지). | true 면 swap 을 막습니다. OS memlock 한도가 부족하면 기동 시 bootstrap check 가 실패합니다. | - | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `cluster.blocks.read_only` | false | dynamic | cluster | 클러스터 전체 읽기 전용. | true 면 모든 쓰기와 메타데이터 변경이 거부됩니다. | WARNING | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `cluster.blocks.read_only_allow_delete` | false | dynamic | cluster | 클러스터 전체 읽기 전용(삭제만 허용). | true 면 인덱스 삭제 외 모든 쓰기가 거부됩니다. | WARNING | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `cluster.indices.close.enable` | true | dynamic | cluster | 인덱스 close API 허용 여부. | false 면 인덱스를 닫을 수 없습니다(닫힌 인덱스는 복제·스냅샷 대상 관리가 어려워 막는 경우가 있음). | INFO | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `cluster.info.update.interval` | 30s | dynamic | cluster | 디스크 사용량 확인 주기. | ↑ 급격한 디스크 증가를 늦게 감지합니다.<br>↓ 마스터 부하가 조금 늘어납니다. | WARNING / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.max_shards_per_node` | 1000 | dynamic | cluster | non-frozen 데이터 노드당 열린 샤드 한도(클러스터 한도 = 값 × 노드 수). | ↑ 한도 도달 시점은 늦어지지만, 한도가 막아 주던 과다 샤딩의 비용(heap·cluster state·마스터 부하)이 그대로 쌓입니다.<br>↓ 신규 인덱스 생성·롤오버가 더 일찍 실패합니다. | WARNING / INFO | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |
| `cluster.max_shards_per_node.frozen` | 3000 | dynamic | cluster | frozen 전용 노드당 샤드 한도. | ↑ frozen 노드의 메타데이터 부하가 커집니다.<br>↓ 마운트 가능한 인덱스가 줄어듭니다. | INFO / INFO | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |
| `cluster.metadata.display_name` | (없음) | dynamic | cluster | 클러스터 표시 이름(Elastic Cloud 메타데이터). | 동작 영향 없음. | - | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `cluster.persistent_tasks.allocation.enable` | all | dynamic | cluster | persistent task(ML job, transform 등) 할당 허용. | none 이면 새 persistent task 가 할당되지 않습니다. | WARNING | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `cluster.routing.allocation.allow_rebalance` | always | dynamic | cluster | 리밸런싱을 시작하는 조건(desired balance 할당기 기본 always, 이전 할당기는 indices_all_active). | 조건을 엄격히 하면(indices_primaries_active / indices_all_active) 복구가 끝날 때까지 리밸런싱이 미뤄져 편중 해소가 늦어집니다. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.awareness.attributes` | (없음) | dynamic | cluster | primary/replica 를 서로 다른 영역(zone·rack)에 배치하기 위한 노드 속성. | 설정 시 같은 샤드의 사본이 다른 영역에 배치됩니다. 영역별 노드 수가 다르면 일부 사본이 미할당될 수 있습니다. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.balance.disk_usage` | 2.0E-11 | dynamic | cluster | 노드별 디스크 사용량 균형 가중치. | 디스크 편중 분산 효과가 달라집니다. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.balance.index` | 0.55 | dynamic | cluster | 인덱스별 샤드 분산 가중치. | 가중치 변경은 대량 재배치를 유발할 수 있습니다. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.balance.shard` | 0.45 | dynamic | cluster | 노드별 전체 샤드 수 균형 가중치. | 가중치 조합을 바꾸면 desired balance 계산 결과가 달라져 대량 재배치가 발생할 수 있습니다. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.balance.threshold` | 1.0 | dynamic | cluster | 리밸런싱을 수행할 최소 불균형 정도. | ↑ 작은 불균형은 무시되어 이동이 줄지만 편중이 남습니다.<br>↓ 사소한 차이에도 이동이 잦아져 불필요한 I/O 가 생깁니다. | INFO / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.balance.write_load` | 10.0 | dynamic | cluster | 데이터 스트림 예상 쓰기 부하 균형 가중치. | 쓰기 핫스팟 분산 효과가 달라집니다. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.cluster_concurrent_rebalance` | 2 | dynamic | cluster | 클러스터 전체에서 동시에 리밸런싱할 샤드 수. | ↑ 이동 속도는 빨라지지만 네트워크·디스크 I/O 가 서비스 트래픽과 경합합니다.<br>↓ 편중 해소가 느려집니다. 0 이면 리밸런싱이 사실상 중단됩니다. | INFO / WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.disk.threshold_enabled` | true | dynamic | cluster | 디스크 워터마크 기반 할당 판단 사용 여부. | false 면 디스크가 가득 찰 때까지 샤드가 배치되어 flood stage 보호도 동작하지 않습니다. | WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.disk.watermark.flood_stage` | 95% | dynamic | cluster | 이 사용률을 넘은 노드의 인덱스에 쓰기 차단(read_only_allow_delete). | ↑ 쓰기 차단 전에 디스크가 완전히 찰 위험이 커집니다. 명시 설정 시 max_headroom 기본값(100GB)이 해제됩니다.<br>↓ 쓰기 차단이 이르게 발생합니다. | WARNING / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.disk.watermark.high` | 90% | dynamic | cluster | 이 사용률을 넘은 노드의 샤드를 다른 노드로 이동. | ↑ 이동이 늦게 시작되어 flood stage 도달 위험이 커집니다. 명시 설정 시 max_headroom 기본값(150GB)이 해제됩니다.<br>↓ 이동이 잦아집니다. | WARNING / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.disk.watermark.low` | 85% | dynamic | cluster | 이 사용률을 넘은 노드에는 새 샤드를 배치하지 않음. | ↑ 디스크를 더 채울 수 있지만 대응 여유가 줄어듭니다. 명시 설정하면 max_headroom 기본값(200GB)이 적용되지 않습니다.<br>↓ 여유 공간이 커도 샤드 배치가 막혀 일부 노드로 몰릴 수 있습니다. | INFO / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.enable` | all | dynamic | cluster | 어떤 샤드의 할당을 허용할지(all / primaries / new_primaries / none). | all 이 아니면 replica(또는 전체) 샤드가 할당되지 않아 노드 이탈 후 복구가 멈추고 yellow/red 가 지속됩니다. 롤링 재기동 중 임시로 바꾸는 값이며 작업 후 null 로 되돌려야 합니다. | WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.node_concurrent_incoming_recoveries` | 2 | dynamic | cluster | 노드당 동시 수신 복구 수. | ↑ 수신 노드의 I/O 경합이 커집니다.<br>↓ 복구가 느려집니다. | INFO / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.node_concurrent_outgoing_recoveries` | 2 | dynamic | cluster | 노드당 동시 송신 복구 수. | ↑ 송신 노드(대개 부하가 이미 큰 노드)의 I/O 경합이 커집니다.<br>↓ 복구가 느려집니다. | INFO / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.node_concurrent_recoveries` | 2 | dynamic | cluster | 노드당 동시 복구(incoming+outgoing) 수. | ↑ 노드 교체 후 복구는 빨라지지만 해당 노드의 디스크·네트워크 포화 위험이 있습니다.<br>↓ 복구 시간이 길어져 yellow 상태가 오래 유지됩니다. | INFO / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.node_initial_primaries_recoveries` | 4 | dynamic | cluster | 노드 재기동 시 로컬 디스크에서 동시에 복구할 primary 수. | ↑ 재기동 직후 디스크 부하가 급증합니다.<br>↓ 전체 재기동 후 red 해소가 느려집니다. | INFO / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.same_shard.host` | false | dynamic | cluster | 같은 호스트의 여러 노드에 동일 샤드 사본 배치 금지. | true 는 한 서버에 노드를 여러 개 띄운 구성에서 필요한 안전장치입니다. 단일 노드/호스트 구성에서 false 로 두면 호스트 장애 시 primary 와 replica 가 함께 사라질 수 있습니다. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.total_shards_per_node` | -1 | dynamic | cluster | 노드당 전체 샤드 수 상한(-1=무제한). | ↓ 상한에 걸리면 샤드가 미할당으로 남습니다. 노드 장애 시 남은 노드로 옮길 수 없어 red 가 될 수 있습니다. | - / WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.rebalance.enable` | all | dynamic | cluster | 샤드 리밸런싱 허용 범위. | 리밸런싱이 제한되어 노드 증설 후에도 샤드가 새 노드로 이동하지 않고, 편중이 고착됩니다. | WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.use_adaptive_replica_selection` | true | dynamic | cluster | 검색 요청을 응답시간·큐 길이를 반영해 사본에 분배(ARS). | false 면 라운드로빈으로 분배되어, 느린 노드 1대가 전체 검색 p99 를 끌어올립니다. | WARNING | [Search settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/search-settings) |
| `http.max_content_length` | 100mb | static | node | HTTP 요청 본문 최대 크기. | ↑ 대형 bulk·문서가 허용되어 heap 급증 위험이 커집니다(Lucene 한계 약 2GB 는 그대로).<br>↓ 대형 bulk 요청이 413 으로 거부됩니다. | WARNING / INFO | [Networking settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/networking-settings) |
| `index.auto_expand_replicas` | false | dynamic | index | 데이터 노드 수에 맞춰 replica 수 자동 조정. | 대형 인덱스에 쓰면 노드 증설 시 replica 가 자동으로 늘어 디스크·복구 부하가 급증합니다. | INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.blocks.read_only` | false | dynamic | index | 읽기 전용. | true 면 쓰기·메타데이터 변경이 거부됩니다. | WARNING | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.blocks.read_only_allow_delete` | false | dynamic | index | 읽기 전용(삭제 허용). flood stage 가 자동 설정. | true 면 색인이 거부됩니다. 디스크 여유 확보 후 해제해야 합니다(8.x 는 여유 회복 시 자동 해제). | WARNING | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.blocks.write` | false | dynamic | index | 쓰기 차단. | true 면 색인이 거부됩니다. | WARNING | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.codec` | default(LZ4) | static | index | stored field 압축 방식(logsdb·time_series 모드는 best_compression 기본). | best_compression 은 저장 공간을 줄이는 대신 문서 조회 시 압축 해제 비용이 늘어납니다. static 이라 닫힌 인덱스에서만 바꿀 수 있고, 기존 세그먼트는 merge 후 반영됩니다. | INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.highlight.max_analyzed_offset` | 1000000 | dynamic | index | 하이라이트 시 분석할 최대 문자 수. | ↑ 대형 문서 하이라이팅이 CPU·heap 을 크게 씁니다.<br>↓ 긴 문서의 하이라이트가 잘리거나 실패합니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.mapping.depth.limit` | 20 | dynamic | index | 객체 중첩 최대 깊이. | ↑ 깊은 중첩 문서가 허용됩니다.<br>↓ 색인이 거부될 수 있습니다. | INFO / INFO | [Mapping limit settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/mapping-limit) |
| `index.mapping.nested_fields.limit` | 50 | dynamic | index | nested 타입 필드 수 한도. | ↑ nested 는 숨은 문서를 만들어 저장·검색 비용이 큽니다.<br>↓ 매핑이 거부됩니다. | WARNING / INFO | [Mapping limit settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/mapping-limit) |
| `index.mapping.nested_objects.limit` | 10000 | dynamic | index | 문서당 nested 객체 수 한도. | ↑ 문서 1건이 수만 개의 숨은 문서로 늘어 heap·디스크를 과점할 수 있습니다.<br>↓ 색인이 거부됩니다. | WARNING / INFO | [Mapping limit settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/mapping-limit) |
| `index.mapping.total_fields.limit` | 1000 | dynamic | index | 인덱스당 최대 필드 수(매핑 폭증 방지). | ↑ 필드가 늘수록 cluster state·heap 사용이 늘고 마스터 부하가 커집니다(매핑 폭증 신호).<br>↓ 새 필드가 들어오면 색인이 실패합니다. | WARNING / INFO | [Mapping limit settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/mapping-limit) |
| `index.max_docvalue_fields_search` | 100 | dynamic | index | 요청당 docvalue_fields 최대 수. | ↑ 응답 생성 비용이 늘어납니다.<br>↓ 해당 요청이 거부됩니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_inner_result_window` | 100 | dynamic | index | inner_hits·top_hits 의 from + size 최대값. | ↑ 집계 응답이 커져 heap 사용이 늘어납니다.<br>↓ 해당 쿼리가 거부됩니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_ngram_diff` | 1 | dynamic | index | ngram 토크나이저 min/max 차이 허용치. | ↑ 토큰 수가 급증해 색인 크기와 속도에 큰 영향을 줍니다.<br>↓ 분석기 정의가 거부됩니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_refresh_listeners` | 1000 | dynamic | index | refresh=wait_for 대기자 최대 수. | ↑ 대기 요청이 heap 을 더 씁니다.<br>↓ 초과 요청은 강제 refresh 를 유발합니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_regex_length` | 1000 | dynamic | index | regexp 쿼리 최대 길이. | ↑ 복잡한 정규식이 CPU 를 과점할 수 있습니다.<br>↓ 해당 쿼리가 거부됩니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_result_window` | 10000 | dynamic | index | from + size 최대값. | ↑ 깊은 페이징이 허용되어 샤드마다 from+size 건을 모으므로 heap 사용이 페이지 깊이에 비례해 늘어납니다.<br>↓ 깊은 페이지 요청이 거부됩니다. | WARNING / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_script_fields` | 32 | dynamic | index | 요청당 script_fields 최대 수. | ↑ 검색 CPU 사용이 늘어납니다.<br>↓ 해당 요청이 거부됩니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_shingle_diff` | 3 | dynamic | index | shingle 필터 min/max 차이 허용치. | ↑ 토큰 수가 급증합니다.<br>↓ 분석기 정의가 거부됩니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_terms_count` | 65536 | dynamic | index | terms 쿼리의 최대 항목 수. | ↑ 대형 terms 쿼리가 CPU·heap 을 크게 씁니다.<br>↓ 해당 쿼리가 거부됩니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.merge.policy.max_merged_segment` | 5gb | dynamic | index | merge 로 만들어지는 세그먼트의 최대 크기. | ↑ 세그먼트 수가 줄어 검색(특히 kNN)이 빨라지지만 merge 한 번의 I/O 가 커집니다.<br>↓ 세그먼트가 많아져 검색이 느려집니다. | INFO / INFO | [Merge settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/merge) |
| `index.merge.policy.segments_per_tier` | 10 | dynamic | index | tier 당 허용 세그먼트 수. | ↑ merge 는 줄지만 세그먼트가 많아집니다.<br>↓ merge 가 잦아져 I/O 가 늘어납니다. | INFO / INFO | [Merge settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/merge) |
| `index.number_of_replicas` | 1 | dynamic | index | 샤드당 replica 수. | ↑ 가용성·검색 처리량은 늘지만 디스크와 색인 비용이 배수로 늘어납니다.<br>↓ 0 이면 노드 1대 장애로 데이터가 유실될 수 있습니다. | INFO / WARNING | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.queries.cache.enabled` | true | static | index | 노드 query(filter) 캐시 사용. | false 면 반복 필터를 매번 다시 계산합니다. | INFO | [Node query cache settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/node-query-cache-settings) |
| `index.refresh_interval` | 1s(미지정 시 search idle 적용) | dynamic | index | 새 문서가 검색에 보이기까지의 주기. | ↑ 색인 처리량이 늘고 merge 부담이 줄지만 검색 반영이 늦어집니다. -1 은 refresh 중지.<br>↓ 세그먼트가 잦게 생겨 CPU·merge 부담이 커집니다. 명시하면 search idle 최적화가 꺼집니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.requests.cache.enable` | true | dynamic | index | shard request 캐시 사용. | false 면 반복 집계를 매번 다시 계산합니다. | INFO | [Node query cache settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/node-query-cache-settings) |
| `index.routing.allocation.total_shards_per_node` | -1 | dynamic | index | 이 인덱스의 노드당 샤드 수 상한(핫스팟 방지). | ↓ 너무 작으면 노드 장애 시 샤드를 옮길 곳이 없어 미할당됩니다. | - / WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `index.search.idle.after` | 30s | dynamic | index | 검색이 없으면 주기적 refresh 를 건너뛰기 시작하는 시간. | ↑ refresh 생략 효과가 늦게 시작됩니다.<br>↓ 검색 idle 전환이 빨라져, 뜸한 첫 검색이 refresh 를 기다리게 됩니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.translog.durability` | request | dynamic | index | 요청마다 translog 를 fsync 할지(request) 주기적으로 할지(async). | async 면 색인이 빨라지는 대신 노드 비정상 종료 시 sync_interval 동안의 확인 응답된 쓰기가 유실될 수 있습니다. | WARNING | [Translog settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/translog) |
| `index.translog.sync_interval` | 5s | dynamic | index | async 모드의 translog fsync 주기. | ↑ async 모드에서 유실 가능 구간이 길어집니다.<br>↓ fsync 가 잦아집니다. | INFO / INFO | [Translog settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/translog) |
| `index.unassigned.node_left.delayed_timeout` | 1m | dynamic | index | 노드 이탈 후 replica 재할당을 미루는 시간. | ↑ 노드 복귀를 기다리는 동안 yellow 가 길어지지만 불필요한 재복제는 줄어듭니다.<br>↓ 잠깐의 재기동에도 전체 재복제가 시작됩니다(0 이면 즉시). | INFO / WARNING | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `indices.breaker.fielddata.limit` | 40% | dynamic | cluster | fielddata 적재 한도(heap 대비). | ↑ text 필드 집계 등으로 heap 이 잠식되어 GC 압박이 커집니다.<br>↓ 집계가 더 일찍 거부됩니다. | WARNING / INFO | [Circuit breaker settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/circuit-breaker-settings) |
| `indices.breaker.request.limit` | 60% | dynamic | cluster | 요청 단위 메모리(집계 등) 한도. | ↑ 대형 집계가 heap 을 과점할 수 있습니다.<br>↓ 집계가 더 일찍 거부됩니다. | WARNING / INFO | [Circuit breaker settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/circuit-breaker-settings) |
| `indices.breaker.total.limit` | 95% | dynamic | cluster | parent breaker 한도(use_real_memory=true 기준 95%, false 면 70%). | ↑ OOM 직전까지 요청을 받아들여 노드가 OutOfMemoryError 로 종료될 위험이 커집니다.<br>↓ 정상 요청도 CircuitBreakingException 으로 거부됩니다. | WARNING / INFO | [Circuit breaker settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/circuit-breaker-settings) |
| `indices.breaker.total.use_real_memory` | true | static | node | parent breaker 가 실제 heap 사용량을 기준으로 판단. | false 면 추정치 기준(한도 기본 70%)으로 동작해 실제 heap 과 괴리가 생길 수 있습니다. | WARNING | [Circuit breaker settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/circuit-breaker-settings) |
| `indices.fielddata.cache.size` | unbounded | static | node | fielddata 캐시 상한(기본 무제한, 실제 상한은 fielddata breaker). | 상한을 두면 eviction 이 발생해 해당 집계가 매번 fielddata 를 다시 적재합니다. | INFO | [Field data cache settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/field-data-cache-settings) |
| `indices.lifecycle.poll_interval` | 10m | dynamic | cluster | ILM 조건 확인 주기. | ↑ 롤오버·삭제가 늦게 수행되어 샤드 크기·디스크가 계획보다 커집니다.<br>↓ 마스터 부하가 늘어납니다. 테스트 목적 외에는 줄이지 않습니다. | INFO / WARNING | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `indices.memory.index_buffer_size` | 10% | static | node | 색인 버퍼(heap 대비). 쓰기 중인 샤드가 공유. | ↑ 대량 색인 효율은 좋아지지만 검색·집계에 쓸 heap 이 줄어듭니다.<br>↓ flush 가 잦아지고 작은 세그먼트가 늘어납니다. | INFO / INFO | [Indexing buffer settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/indexing-buffer-settings) |
| `indices.queries.cache.size` | 10% | static | node | 노드 query(filter) 캐시 크기(heap 대비). | ↑ heap 상주량이 늘어 GC 압박이 커집니다.<br>↓ 필터 캐시 적중률이 떨어집니다. | INFO / INFO | [Node query cache settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/node-query-cache-settings) |
| `indices.recovery.max_bytes_per_sec` | 40mb | dynamic | cluster | 노드당 복구 대역 상한(전용 cold/frozen 노드는 메모리 기반으로 자동 산정). | ↑ 복구가 빨라지지만 복구 트래픽이 서비스 I/O 를 잠식할 수 있습니다.<br>↓ 노드 교체·재기동 후 복구가 느려져 yellow 상태가 길어집니다. | INFO / WARNING | [Index recovery settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/index-recovery-settings) |
| `indices.requests.cache.size` | 1% | static | node | shard request 캐시 크기(heap 대비). | ↑ heap 상주량이 늘어납니다.<br>↓ 집계 결과 캐시 효과가 줄어듭니다. | INFO / INFO | [Node query cache settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/node-query-cache-settings) |
| `ingest.geoip.downloader.enabled` | true | dynamic | cluster | GeoIP DB 자동 다운로드. | 폐쇄망에서는 false 가 정상입니다. 이 경우 DB 를 수동으로 배포해야 geoip processor 가 동작합니다. | - | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `network.breaker.inflight_requests.limit` | 100% | dynamic | cluster | 수신 중인 요청(transport/HTTP) 크기 한도. | ↑ 대형 bulk 가 한꺼번에 들어와 heap 이 급증할 수 있습니다.<br>↓ 대형 요청이 거부됩니다. | WARNING / INFO | [Circuit breaker settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/circuit-breaker-settings) |
| `node.processors` | 가용 프로세서 수(자동) | static | node | ES 가 인식하는 CPU 수(스레드풀 크기 산정 기준). | 실제보다 크게 잡으면 스레드가 과다해지고, 작게 잡으면 CPU 를 다 쓰지 못합니다. 컨테이너에서 CPU limit 과 맞출 때 사용합니다. | INFO | [Thread pool settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings) |
| `node.store.allow_mmap` | true | static | node | Lucene 파일 mmap 사용. | false 면 mmap 대신 NIO 로 읽어 검색 성능이 떨어질 수 있습니다(vm.max_map_count 를 못 올리는 환경용). | INFO | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `script.max_compilations_rate` | 150/5m | dynamic | cluster | 스크립트 컴파일 속도 한도. | 올리면 매번 다른 스크립트를 보내는 잘못된 사용(파라미터 미사용)이 가려지고 CPU·메모리 부담이 커집니다. | INFO | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `search.allow_expensive_queries` | true | dynamic | cluster | script·wildcard·regexp·fuzzy 등 비싼 쿼리 허용 여부. | false 면 해당 쿼리가 거부됩니다(보호 목적). Kibana 일부 기능도 영향받을 수 있습니다. | INFO | [Search settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/search-settings) |
| `search.default_search_timeout` | -1 | dynamic | cluster | 요청에 timeout 이 없을 때 적용되는 검색 타임아웃(-1=무제한). | 짧게 두면 무거운 쿼리가 부분 결과로 끝나고, 무제한이면 비정상 쿼리가 자원을 계속 점유할 수 있습니다. | INFO | [Search settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/search-settings) |
| `search.low_level_cancellation` | true | dynamic | cluster | 검색 취소 요청을 세그먼트 단위로 빠르게 반영. | false 면 취소된 검색이 늦게 멈춰 자원을 더 오래 씁니다. | INFO | [Search settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/search-settings) |
| `search.max_buckets` | 65536 | dynamic | cluster | 단일 응답의 최대 집계 버킷 수. | ↑ 대형 집계가 허용되어 coordinating 노드 heap 압박·circuit breaker 발동 위험이 커집니다.<br>↓ 기존 대시보드 집계가 실패할 수 있습니다. | WARNING / INFO | [Search settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/search-settings) |
| `slm.retention_schedule` | 0 30 1 * * ? | dynamic | cluster | SLM 보존 정책(오래된 스냅샷 삭제) 실행 주기. | 실행 시각이 바뀝니다. 너무 드물면 스냅샷 저장소 용량이 계획보다 커집니다. | - | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `thread_pool.search.queue_size` | 자동 산정(9.4.4 관측: search 스레드 수 × 1000, 8.x 이전 문서 기준 1000) | static | node | search 스레드풀 대기열 크기. | ↑ rejection 은 줄지만 검색 지연·heap 사용이 늘어납니다.<br>↓ rejection 이 더 빨리 발생합니다. | WARNING / INFO | [Thread pool settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings) |
| `thread_pool.search.size` | int((코어 수 × 3) / 2) + 1(자동) | static | node | search 스레드 수. | 임의 변경 시 CPU 경합이나 처리량 저하가 생깁니다. | WARNING | [Thread pool settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings) |
| `thread_pool.write.queue_size` | 10000 | static | node | write 스레드풀 대기열 크기. | ↑ rejection 은 줄지만 요청이 큐에서 오래 대기해 지연과 heap 사용이 늘어납니다. 원인(과부하)이 가려집니다.<br>↓ rejection(429)이 더 빨리 발생합니다. | WARNING / INFO | [Thread pool settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings) |
| `thread_pool.write.size` | CPU 코어 수(자동) | static | node | write 스레드 수. | 코어 수보다 크게 잡으면 컨텍스트 스위칭만 늘고 처리량은 늘지 않습니다. | WARNING | [Thread pool settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings) |
| `transport.compress` | indexing_data | dynamic | cluster | 노드 간 전송 압축 대상. | true 는 모든 전송을 압축해 CPU 를 더 쓰고, false 는 색인 데이터도 압축하지 않아 네트워크 사용이 늘어납니다. | INFO | [Networking settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/networking-settings) |
| `xpack.ml.max_machine_memory_percent` | 30 | dynamic | cluster | ML 작업이 쓸 수 있는 노드 메모리 비율. | ↑ ML 프로세스가 파일시스템 캐시·다른 프로세스 몫을 잠식합니다.<br>↓ ML job 이 할당되지 못할 수 있습니다. | INFO / INFO | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `xpack.monitoring.collection.enabled` | false | dynamic | cluster | 레거시 내부 모니터링 수집. | true 면 클러스터 자신에 모니터링 데이터를 색인해 부하가 늘어납니다. 운영 모니터링은 별도 클러스터를 권장합니다. | INFO | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `cluster.routing.allocation.exclude.*` | (없음) | dynamic | cluster | 지정한 노드(이름·IP·호스트·속성)에서 샤드를 빼냄. | 해당 노드에 샤드가 배치되지 않습니다. 유지보수 후 제거하지 않으면 용량이 남아도 샤드가 다른 노드로 몰립니다. | WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.include.*` | (없음) | dynamic | cluster | 지정한 노드에만 샤드 배치를 허용. | 조건에 맞지 않는 노드에는 샤드가 배치되지 않아 편중·미할당이 생길 수 있습니다. | WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.require.*` | (없음) | dynamic | cluster | 지정한 조건을 모두 만족하는 노드에만 샤드 배치. | 조건을 만족하는 노드가 부족하면 샤드가 미할당됩니다. | WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `logger.*` | INFO(로거별 기본) | dynamic | cluster | 로거 레벨. | DEBUG/TRACE 로 올리면 로그량이 급증해 디스크·I/O·성능에 영향을 줍니다. 조사 후 null 로 되돌려야 합니다. | INFO | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |

## 임계값 전체 목록

`[공식]` 은 공식 문서의 수치, `[도구]` 는 이 도구가 정한 값입니다. 주석이 없는 항목은 도구 판단 값입니다.

| 키 | 기본값 | 설명 |
| --- | --- | --- |
| `heap_used_pct_warn` | 75 | [도구] 수집 순간 heap 사용률 |
| `heap_used_pct_crit` | 85 | [도구] 수집 순간 heap 사용률 |
| `heap_max_bytes_crit` | 32GiB | [공식] compressed oops 경계(32GB 미만 권장) |
| `heap_vs_ram_pct_warn` | 50 | [공식] heap <= 전체 메모리의 50% |
| `heap_vs_ram_tolerance_pct` | 2 | [도구] 반올림·adjusted_total 오차 허용 |
| `old_gc_time_ratio_warn` | 0.02 | [도구] old GC 누적 시간 / uptime |
| `old_gc_time_ratio_crit` | 0.05 | [도구] old GC 누적 시간 / uptime |
| `young_gc_time_ratio_warn` | 0.05 | [도구] young GC 누적 시간 / uptime |
| `old_gc_per_hour_warn` | 6 | [도구] 시간당 old GC 횟수 |
| `old_gc_per_hour_crit` | 30 | [도구] 시간당 old GC 횟수 |
| `load_per_cpu_warn` | 1.0 | [도구] load15 / CPU 코어 |
| `load_per_cpu_crit` | 1.5 | [도구] load15 / CPU 코어 |
| `fd_used_pct_warn` | 70 | [도구] 열린 파일 / 최대(공식 최소 한도는 65,535) |
| `cgroup_throttle_ratio_warn` | 0.01 | [도구] throttled / elapsed periods |
| `cgroup_throttle_ratio_crit` | 0.05 | [도구] throttled / elapsed periods |
| `uptime_short_hours` | 6 | [도구] 최근 재기동 판단 |
| `disk_watermark_low_default` | 85% | [공식] ES 기본값(설정 파일이 없을 때만 사용) |
| `disk_watermark_high_default` | 90% | [공식] ES 기본값(설정 파일이 없을 때만 사용) |
| `disk_watermark_flood_default` | 95% | [공식] ES 기본값(설정 파일이 없을 때만 사용) |
| `disk_watermark_flood_frozen_default` | 95% | [공식] frozen 전용 노드 flood stage |
| `disk_watermark_flood_frozen_headroom_default` | 20GB | [공식] frozen flood max_headroom |
| `disk_imbalance_pct_warn` | 15 | [도구] 노드 간 디스크 사용률 편차(%p) |
| `disk_low_margin_pct` | 10 | [도구] 실효 low 워터마크까지 남은 %p |
| `rejected_crit` | 1,000 | [도구] 누적 rejection 합계 |
| `breaker_tripped_warn` | 1 | [도구] breaker 발동 횟수(1 = 이력 존재) |
| `shards_per_gb_heap_warn` | 20 | [공식] heap 1GB당 샤드 20개(8.3 미만 전용) |
| `shards_per_gb_heap_crit` | 30 | [도구] 8.3 미만 전용 |
| `max_shards_per_node_headroom_pct_warn` | 80 | [도구] cluster.max_shards_per_node 대비 사용률 |
| `shard_size_gb_warn` | 50 | [공식] 샤드 10~50GB |
| `shard_size_gb_crit` | 200 | [도구] 복구 시간 기준 상한 |
| `small_shard_mb` | 1,024 | [도구] 소형 샤드 기준 |
| `small_shard_count_warn` | 50 | [도구] |
| `small_shard_ratio_warn` | 0.5 | [도구] |
| `deleted_docs_ratio_warn` | 0.25 | [도구] |
| `segments_per_shard_warn` | 50 | [도구] |
| `merge_throttle_ratio_warn` | 0.05 | [도구] |
| `search_latency_ms_warn` | 200 | [도구] 인덱스 평균 query 지연 |
| `search_latency_ms_crit` | 1,000 | [도구] 인덱스 평균 query 지연 |
| `index_latency_ms_warn` | 50 | [도구] 문서당 평균 색인 시간 |
| `index_latency_ms_crit` | 200 | [도구] 문서당 평균 색인 시간 |
| `min_query_total_for_latency` | 100 | [도구] 표본이 적으면 판정 제외 |
| `fielddata_heap_pct_warn` | 10 | [도구] fielddata / heap |
| `pending_tasks_warn` | 10 | [도구] |
| `pending_tasks_crit` | 100 | [도구] |
| `max_task_wait_ms_warn` | 30,000 | [도구] |
| `long_running_task_ms_warn` | 300,000 | [도구] 5분 |
| `license_expiry_days_warn` | 90 | [도구] |
| `license_expiry_days_crit` | 30 | [도구] |
| `cert_expiry_days_warn` | 90 | [도구] |
| `cert_expiry_days_crit` | 30 | [도구] |
| `snapshot_age_hours_warn` | 36 | [도구] 최근 스냅샷 경과 시간 |
| `snapshot_age_hours_crit` | 168 | [도구] 7일 |
| `snapshot_failed_warn` | 1 | [도구] |
| `ingest_failed_warn` | 1 | [도구] |
| `hot_thread_pct_warn` | 50 | [도구] 단일 스레드 CPU% |
| `log_scan_bytes` | 8MiB | [도구] 로그 파일당 스캔 크기(끝부분) |
| `docs_per_shard_warn` | 200,000,000 | [공식] 샤드당 2억건 미만 권장 |
| `docs_per_shard_crit` | 1,500,000,000 | [도구] Lucene 한계(2,147,483,519) 접근 경보 |
| `indices_per_gb_master_heap` | 3,000 | [공식] 마스터 heap 1GB당 인덱스 3000개 |
| `mapping_heap_pct_warn` | 50 | [도구] 매핑 오버헤드 추정 / heap |
| `heap_baseline_bytes` | 512MiB | [공식] 필드 매퍼 산정 시 추가 여유 0.5GB |
| `empty_index_count_warn` | 5 | [도구] |
| `heavy_index_docs` | 10,000,000 | [도구] 대량 색인 인덱스 기준 |
| `index_buffer_per_shard_warn` | 32MiB | [도구] 쓰기 대상 샤드당(공식 상한은 512MB) |
| `open_contexts_warn` | 100 | [도구] |
| `search_heavy_query_total` | 100,000 | [도구] 검색 부하 인덱스 기준 |
| `preload_index_count_warn` | 5 | [도구] |
| `codec_check_min_bytes` | 50GiB | [도구] |
| `vector_vs_fscache_pct_warn` | 60 | [도구] 벡터 상주량 / (RAM - heap) |
| `vector_dim_quantize_warn` | 384 | [공식] 384차원 이상 float 벡터는 양자화 권장 |
| `vector_segments_per_shard_warn` | 20 | [도구] |
| `avg_doc_bytes_warn` | 1MiB | [도구] 문서 평균 1MB |
| `tier_cpu_pct_warn` | 75 | [도구] tier 전체 포화 판정 CPU% |
| `hotspot_heap_pct_gap` | 30 | [도구] 노드 간 heap 편차(%p) |
| `hotspot_heap_pct_floor` | 70 | [도구] 최대값이 이 미만이면 무시 |
| `hotspot_cpu_pct_floor` | 50 | [도구] |
| `hotspot_disk_pct_floor` | 50 | [도구] |
| `hotspot_cpu_pct_gap` | 40 | [도구] |
| `workload_skew_ratio_warn` | 1.8 | [도구] 최대 노드 / 평균 |
| `undesired_shards_warn` | 1 | [도구] |
| `recovery_rate_low_bytes` | 40MiB | [공식] indices.recovery.max_bytes_per_sec 기본값 40mb 이하 |
| `oversharding_floor_shard_gb` | 10 | [공식] 샤드 권장 하한 10GB |
| `oversharding_target_shard_gb` | 50 | [공식] 샤드 권장 상한 50GB(권장 primary 수 산정) |
| `oversharding_excess_warn` | 20 | [도구] 줄일 수 있는 샤드 합계 |
| `oversharding_excess_ratio_warn` | 0.1 | [도구] 전체 샤드 대비 비중 |
| `oversharding_min_shards` | 20 | [도구] 분포 판정 최소 표본 |
| `oversharding_small_share_warn` | 0.8 | [도구] 10GB 미만 비중 |
| `oversharding_min_data_gb` | 100 | [도구] 소규모 클러스터는 분포 판정 제외 |
| `ds_min_backing_indices` | 5 | [도구] 데이터 스트림 판정 최소 백킹 수 |
| `ds_small_backing_shard_gb` | 1 | [도구] 백킹 샤드 중앙값 기준 |
| `mapping_fields_near_limit_pct` | 90 | [도구] total_fields.limit 대비 필드 수 |
| `ilm_rollover_max_shard_gb` | 50 |  |
| `disk_io_busy_pct_warn` | 60 |  |
| `search_expensive_share_warn` | 10 | [도구] 비용이 큰 쿼리 유형의 검색 대비 비중(%)                    # [도구] 기동 이후 평균 디스크 사용률                # [공식] 롤오버 샤드 크기 권장 상한 |
| `diff_min_hours_for_projection` | 1.0 | [도구] 이보다 짧은 간격은 외삽 안 함 |
| `disk_projection_days_warn` | 30 | [도구] |
| `index_growth_min_bytes` | 1GiB | [도구] |
| `top_n` | 15 | [도구] 근거 표 최대 행 수 |
| `eol_major_below` | 8 | [도구] 이 메이저 미만은 구버전 경고 |
