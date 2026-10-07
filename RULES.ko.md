# 판정 룰 명세 (RULES.ko.md)

> 이 문서는 `tools/gen_rules_doc.py` 가 소스 코드에서 자동 생성합니다. 직접 수정하지 마십시오.
> 임계값은 `esdoctor/thresholds.py` 의 현재 기본값이며, `--thresholds` 로 재정의할 수 있습니다.
> English version: [RULES.md](RULES.md)

## 기준점

| 항목 | 값 |
| --- | --- |
| 도구 버전 | esdoctor 0.14.3 |
| 판정 기준 Elasticsearch 버전 | 9.5 |
| 공식 문서 대조 시점 | 2026-10 |
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
| 8.8 | IDX-015 | index.translog.flush_threshold_size 기본값 10GB(이전 512MB) |
| 8.14 | VEC-002 | dense_vector index_options 미지정 시 int8_hnsw 기본(양자화) |
| 8.16 | SET-001 | cluster.routing.allocation.allow_rebalance 기본값이 always(이전 또는 balanced allocator 는 indices_all_active) |
| 9.0 | IDX-013 | logs-*-* data stream 에 logsdb 자동 적용(새 data stream 만) |
| 9.1 | VEC-002 | 384차원 이상 float 벡터는 bbq_hnsw 가 기본 |
| 9.2 | VEC-003 | index.mapping.exclude_source_vectors 기본 적용 |
| 9.5 | SET-006, DISK-006, DISK-007, IDX-013, PERF-008, OPS-007 | merge policy 기본값 변경(segments_per_tier 8, floor_segment 16mb, max_merge_at_once 16). columnar·logsdb_columnar 모드는 best_compression 과 synthetic _source 가 기본, vectordb_document 는 index.store.preload 를 스스로 설정, 모니터링 플러그인 수집은 10.0 제거 예고 |

분석 대상이 기준 버전보다 새로우면 리포트에 `VER-001` 이 표시됩니다.

## 판정 근거 구분

| 구분 | 의미 |
| --- | --- |
| 공식 기준 | 판정 기준 자체가 Elastic 공식 문서에 명시된 항목 |
| 사실 보고 | Elasticsearch 가 보고한 상태·오류·설정값을 그대로 전달(임계값 없음) |
| 도구 판단 | 공식 수치 기준이 없어 이 도구의 임계값으로 판단한 항목 |
| 비교 계산 | 두 번들 간 증가분·증가율·선형 외삽 |

## 입력 파일 규칙

각 룰은 필요한 입력 파일을 선언합니다(`esdoctor/rules/__init__.py` 의 `REQUIRES`). 파일이 번들에 없으면 해당 룰을 실행하지 않고 리포트의 '입력 미수집으로 판정하지 않은 항목' 에 기록합니다. '파일 없음(미수집)' 과 '설정 없음(미설정)' 을 구분하기 위함입니다.

## 목차

- [클러스터](#클러스터) — 12개 룰
- [설정 변경 (기본값 대비)](#설정-변경-기본값-대비) — 5개 룰
- [노드 (JVM · OS · 디스크 · 스레드풀)](#노드-jvm-os-디스크-스레드풀) — 13개 룰
- [샤드 · 인덱스](#샤드-인덱스) — 21개 룰
- [과다 샤딩 · 소형 샤드](#과다-샤딩-소형-샤드) — 3개 룰
- [공식 가이드 기준 (설정 · 샤드 · 성능 · 디스크 · 벡터)](#공식-가이드-기준-설정-샤드-성능-디스크-벡터) — 25개 룰
- [핫스팟 · 밸런싱](#핫스팟-밸런싱) — 7개 룰
- [스토리지 비용](#스토리지-비용) — 6개 룰
- [운영 · 보안](#운영-보안) — 9개 룰
- [매핑 · ILM 정책 · 클러스터 조정 · 세부 통계](#매핑-ilm-정책-클러스터-조정-세부-통계) — 18개 룰
- [런타임 (hot threads · 로그)](#런타임-hot-threads-로그) — 2개 룰
- [OS 설정 (local/remote 모드 syscalls/)](#os-설정-localremote-모드-syscalls) — 1개 룰
- [변화 추세 (--baseline 비교 모드)](#변화-추세---baseline-비교-모드) — 11개 룰
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
| 판정 항목 | CLU-004 Health API 지표 전체 green / CLU-004. Health API 지표 이상: %s (%s) |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 치명, 주의, 참고, 정상 |
| 필요 입력 | (internal_health.json) |
| 근거 파일 | internal_health.json |

**판정 로직**

Health API(_health_report) 지표를 그대로 전달한다. red 가 하나라도 있으면 치명, yellow 면 주의, 모두 green 이면 정상. unknown 은 평가하지 않는다. disk 지표가 green 이 아니어도 원인이 전용 frozen 노드의 flood_stage.frozen 초과뿐이면 참고(cache 전용).

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
| 임계값 | `dedicated_master_data_nodes` = 10 — [도구] 현장 기준: 전용 마스터가 필요해지는 데이터 노드 수 |
| 필요 입력 | (nodes.json) |
| 근거 파일 | nodes.json |

**판정 로직**

마스터 후보(roles 에 master 포함, voting_only 포함) 수. 0대 → 치명, 다중 노드인데 1대 → 치명이며,
나머지가 voting_only 라 선출 가능한 노드가 1대뿐인 경우도 치명(공식: voting-only 노드는 선출 마스터가 되지 않음).
2대 → 주의(1대 이탈 시 정족수 상실. 공식: 마스터 후보 2대 이하는 모두 살아 있어야 함). 짝수(4대 이상)는 ES 가 투표 구성에서 1대를 자동 제외하므로 판정하지 않는다(CLU-006). 전용 마스터가 없고 데이터 노드 >= dedicated_master_data_nodes 대 → 주의(CLU-007). 공식 문서는 노드가 몇 대를 넘으면 전용 마스터가 낫다고만 하며, 대수는 현장 기준이다.

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
| 판정 항목 | CLU-013 transient 클러스터 설정 사용 중 / CLU-014 Adaptive Replica Selection 비활성화 / CLU-011. 위험한 클러스터 설정: %s / CLU-012 노드 제외(exclude) 설정 잔존 |
| 근거 구분 | 공식 기준 / 사실 보고 |
| 가능 심각도 | 주의, 참고 |
| 필요 입력 | (cluster_settings.json) |
| 근거 파일 | cluster_settings.json |

**판정 로직**

기본값과 다른 설정을 판정한다: persistent/transient 에 명시된 값, 없으면 노드 elasticsearch.yml 의 값(그때의 실효값).
allocation.enable != all → 치명, rebalance.enable != all → 주의, disk.threshold_enabled=false → 치명, cluster.blocks.read_only(_allow_delete)=true → 치명, destructive_requires_name=false → 주의(CLU-011). allocation.exclude._name/_ip/_host 값 존재 → 주의(CLU-012). transient 설정 존재 → 참고(CLU-013, 7.16 부터 권장하지 않음. Elastic Cloud / ECE 플랫폼의 빈 placeholder 값은 무시). use_adaptive_replica_selection=false → 주의(CLU-014, 기본 true).

### CLU-015 — 클러스터 샤드 한도 임박

| 항목 | 내용 |
| --- | --- |
| 함수 | `cluster.r_shard_capacity` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 치명, 주의 |
| 임계값 | `max_shards_per_node_crit_pct` = 95 — [도구] cluster.max_shards_per_node 대비 치명이 되는 사용률<br>`max_shards_per_node_headroom_pct_warn` = 80 — [도구] cluster.max_shards_per_node 대비 사용률 |
| 필요 입력 | (cluster_settings.json) 그리고 (cluster_health.json) 그리고 (nodes.json) |
| 근거 파일 | cluster_health.json / cluster_settings.json |
| 참고 문서 | [샤드 사이징 가이드](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

클러스터 샤드 한도 사용률(CLU-015).

공식 계산 방식: cluster.max_shards_per_node 는 frozen 이 아닌 data 노드에 적용되고, open 인덱스의 primary 와 replica 샤드를
미할당까지 포함해 센다. closed 인덱스는 세지 않고, frozen(partial 마운트) 인덱스는 cluster.max_shards_per_node.frozen 으로
따로 센다. 사용률 = (active + unassigned - partial 마운트 인덱스 샤드 - closed 인덱스
샤드) / (cluster.max_shards_per_node x frozen 이 아닌 data 노드 수). closed 인덱스는 cat indices 의 status close 로 판단한다.
>= max_shards_per_node_headroom_pct_warn → 주의, >= max_shards_per_node_crit_pct → 치명.

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
| 가능 심각도 | 주의, 참고 |
| 임계값 | `long_running_task_ms_high` = 3,600,000 — [도구] 1시간: 장시간 task 를 주의로 올리는 기준<br>`long_running_task_ms_warn` = 300,000 — [도구] 5분<br>`monitoring_task_ms_info` = 86,400,000 — [도구] 24시간: 모니터링·내부 task 는 이 시간을 넘을 때만 보고<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (tasks.json) |
| 근거 파일 | tasks.json |

**판정 로직**

장시간 실행 중인 task 를 action 별로 묶는다(CLU-017). 계속 실행되는 persistent task 는 제외한다.

모니터링·내부 task(cluster:monitor/*, indices:monitor/*, internal:*)는 monitoring_task_ms_info 를 넘을 때만 보고한다.
그 밖의 task: 가장 긴 실행 시간 >= long_running_task_ms_high → 주의, >= long_running_task_ms_warn → 참고.
쓰기 경로 action(bulk, reindex, update/delete by query, forcemerge, shrink/split/clone)은 따로 표시한다. 멈춘 쓰기 task 는
자원을 잡고 후속 작업을 막기 때문이다. action 마다 한 행에 task 수와 가장 긴 실행 시간을 보여 준다.

### CLU-018, CLU-019 — 가용영역 간 데이터 노드 불균형

| 항목 | 내용 |
| --- | --- |
| 함수 | `cluster.r_zone_balance` |
| 판정 항목 | CLU-018 가용영역 간 데이터 노드 불균형 / CLU-019 shard allocation awareness 미설정 |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의 |
| 필요 입력 | (nodes.json) 그리고 (cluster_settings.json) |
| 근거 파일 | cluster_settings.json / nodes.json / nodes.json |

**판정 로직**

데이터 노드의 zone 속성(availability_zone / zone / logical_availability_zone / rack_id)이 2종 이상일 때만 판정.
영역별 노드 수는 data tier 별로 비교한다(tier 마다 영역 수를 다르게 두는 설계가 흔함):
영역이 2개 이상인 tier 에서 최대−최소 >= 2 또는 최대 >= 최소 x 2 → 주의(CLU-018). awareness.attributes 가 cluster
settings 에도, 어느 노드의 elasticsearch.yml 에도 없음 → 주의(CLU-019).

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

기본값이 공식 문서(settings_kb)에 등록된 설정은 '원래 기본값 / 방향(↑↓) / 변경 영향' 을 보고하고(SET-001),
미등록 설정은 값만 '설명 미등록' 으로 보고한다. 기본값과 같은 값을 명시한 경우는 참고(SET-002, '기본값과 동일')로 따로 보고한다.
심각도는 등록된 설정의 변경 방향별 위험도(risk) 중 최고값(최대 주의). 전용 룰(CLU-011 등)이 판정하는 설정은 목록에는 넣되 심각도에서 뺀다.
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
심각도는 변경 방향별 위험도 중 최고값(최대 주의, 전용 룰 설정 제외). node.processors, thread_pool.write.size, thread_pool.search.size
는 할당 CPU 수로 계산한 값과 같으면 변경으로 보지 않는다. ECH/ECE 로 감지되면 플랫폼 관리 값으로 보고 참고로 하향한다
(ECK 는 사용자가 Elasticsearch 리소스에 직접 넣는 값이라 그대로 판정).
static 설정은 모든 대상 노드의 yml 수정과 재기동이 필요하다.

### SET-005 — 데이터 노드 간 설정 불일치

| 항목 | 내용 |
| --- | --- |
| 함수 | `settings.r_node_setting_consistency` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (nodes.json) |
| 근거 파일 | nodes.json |

**판정 로직**

노드 간 일치해야 할 설정(인덱싱 버퍼·캐시·스레드풀·검색·전송 등)이 노드마다 다르거나 일부 노드에만 있는지 확인한다.

대상은 명시 설정된 키 중 _CONSISTENCY_PREFIX 아래이고 노드 고유 설정은 뺀다. 데이터 노드는 같은 데이터 tier 노드끼리만
비교한다(데이터 노드를 알 수 없으면 전체 노드). tier 는 보통 다른 하드웨어에서 돌아가므로 node.processors 같은 값은
tier 사이에서 다른 것이 정상이다. 일부 노드에만 있는 설정도 차이로 센다. 차이가 하나라도 있으면 → 주의
(ECH/ECE 로 감지되면 플랫폼이 yml 을 쓰므로 참고).

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
tier preference 등)는 등록 대상이 아니므로 자연히 제외된다. 시스템 인덱스와 searchable snapshot
마운트는 제외한다: 마운트 시 ES 가 write block, replica 0 등을 설정하며 바꿀 수 없다. data stream lifecycle 이
관리 인덱스에 기록하는 merge 설정(floor_segment, merge_factor)도 뺀다.
심각도는 변경 방향별 위험도 중 최고값(최대 주의, 전용 룰 설정 제외).

## 노드 (JVM · OS · 디스크 · 스레드풀)

### JVM-001 — JVM memory pressure 정상

| 항목 | 내용 |
| --- | --- |
| 함수 | `nodes.r_heap_usage` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 치명, 주의, 정상 |
| 임계값 | `heap_used_pct_crit` = 85 — [공식] 조치가 필요한 JVM memory pressure(high JVM memory pressure 가이드)<br>`heap_used_pct_warn` = 75 — [공식] Elastic Cloud 가 빨간색으로 표시하는 JVM memory pressure(old gen 사용량 / 최대) |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |
| 참고 문서 | [JVM 설정(heap 크기)](https://www.elastic.co/docs/reference/elasticsearch/jvm-settings) |

**판정 로직**

노드별 JVM memory pressure: old generation pool 사용량 / 최대(jvm.mem.pools.old). 공식 문서가 쓰는 기준이다.
>= heap_used_pct_crit(85, 공식: memory pressure 가 85% 를 계속 넘으면 조치) → 치명, >= heap_used_pct_warn(75, Elastic Cloud 가
memory pressure 를 빨간색으로 표시하는 수준) → 주의, 그 외 정상. 순간 heap_used_percent 는 young generation garbage 도
포함하므로 표시만 하며, old pool 이 보고되지 않을 때만 판정에 쓴다.

### JVM-002, JVM-003, JVM-004 — heap 이 compressed oops 경계를 넘음

| 항목 | 내용 |
| --- | --- |
| 함수 | `nodes.r_heap_sizing` |
| 판정 항목 | JVM-002 heap 이 compressed oops 경계를 넘음 / JVM-003 Heap 이 물리 메모리 대비 과다 / JVM-004 Xms 와 Xmx 불일치 |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `heap_max_bytes_crit` = 30GiB — [공식] compressed oops 경계는 약 30GB 까지 가능(JVM 플래그가 없을 때만 사용)<br>`heap_oops_safe_bytes` = 26GiB — [공식] 대부분의 시스템에서 26GB 는 안전(JVM 플래그가 없을 때만 사용)<br>`heap_vs_ram_pct_warn` = 50 — [공식] heap <= 전체 메모리의 50%<br>`heap_vs_ram_tolerance_pct` = 2 — [도구] 반올림·adjusted_total 오차 허용 |
| 필요 입력 | (nodes.json) 그리고 (nodes_stats.json) |
| 근거 파일 | nodes.json / nodes.json / nodes_stats.json |
| 참고 문서 | [JVM 설정(heap 크기)](https://www.elastic.co/docs/reference/elasticsearch/jvm-settings) |

**판정 로직**

compressed oops, RAM 대비 heap, Xms 와 Xmx(JVM-002~004).

JVM-002 는 JVM 이 보고한 플래그(nodes.json jvm.using_compressed_ordinary_object_pointers)로 판정한다: false → 주의, true 면
heap 크기와 관계없이 정상. 플래그가 없을 때만 heap 크기를 본다: 공식 문서는 대부분의 시스템에서 26GB 는 안전하고 경계가
약 30GB 까지 될 수 있다고 하므로 heap >= heap_max_bytes_crit(30GiB) → 주의, >= heap_oops_safe_bytes
(26GiB) → 참고.
heap_max / os.mem.adjusted_total > heap_vs_ram_pct_warn + heap_vs_ram_tolerance_pct → 주의(JVM-003). 역할이 master 하나뿐인
노드는 기준이 60% 다(ES 자동 heap 산정이 그런 노드에 메모리의 60% 를 줌). heap_init(Xms) != heap_max(Xmx) → 주의(JVM-004).

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

old 비중 = old collection_time / uptime, 시간당 old GC = old count / uptime(h), young 비중 = young time / uptime. old 비중 >= old_gc_time_ratio_crit 또는 시간당 >= old_gc_per_hour_crit → 치명. old 비중 >= warn, 시간당 >= warn, young 비중 >= young_gc_time_ratio_warn 중 하나 → 주의. 그 외 정상. uptime 이 1시간 미만인 노드는 표에만 넣고 판정하지 않는다(그런 노드만 있으면 보고하지 않음). 누적값이므로 비교 모드(DIF-006)가 더 정확하다.

### OS-001, OS-002, OS-003, OS-004, OS-005, OS-006, OS-007 — CPU load 높음

| 항목 | 내용 |
| --- | --- |
| 함수 | `nodes.r_os` |
| 판정 항목 | OS-001 CPU load 높음 / OS-002 Swap 활성화 / OS-003 컨테이너 CPU throttling 발생 / OS-004 파일 디스크립터 사용률 높음 / OS-005 bootstrap.memory_lock 미적용 / OS-006 최근 재기동된 노드 존재 / OS-007 대부분의 노드가 최근 재시작함 |
| 근거 구분 | 공식 기준 / 도구 판단 |
| 가능 심각도 | 치명, 주의, 참고 |
| 임계값 | `cgroup_throttle_ratio_crit` = 0.05 — [도구] throttled / elapsed periods<br>`cgroup_throttle_ratio_warn` = 0.01 — [도구] throttled / elapsed periods<br>`fd_used_pct_warn` = 70 — [도구] 열린 파일 / 최대(공식 최소 한도는 65,535)<br>`load_host_cpu_pct_max` = 50 — [도구] 이 CPU% 미만인 컨테이너 노드는 load average 로 판정하지 않음(호스트 값이므로)<br>`load_per_cpu_crit` = 1.5 — [도구] load15 / CPU 코어<br>`load_per_cpu_warn` = 1.0 — [도구] load15 / CPU 코어<br>`restart_share_warn` = 0.5 — [도구] uptime_short_hours 안에 재시작한 노드 비율<br>`uptime_short_hours` = 6 — [도구] 최근 재기동 판단 |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes.json / nodes_stats.json |

**판정 로직**

load15 / available_processors >= load_per_cpu_crit → 치명, >= warn → 주의(OS-001, 두 구간의 노드를 모두 표시). 컨테이너 노드(Elastic Cloud / ECE / ECK, 또는 cgroup CPU quota 나 memory limit 이 있음)에서 cpu% 가 load_host_cpu_pct_max 미만이면 판정하지 않는다. 컨테이너 안의 load average 는 호스트 값일 수 있으므로 참고로 표시한다. Linux 의 load average 는 디스크 대기 프로세스도 세므로, CPU 가 낮은데 load 가 높으면 대개 스토리지 문제다. swap_total > 0 이고 mlockall 이 true 가 아님 → 주의(OS-002). cgroup throttled / elapsed_periods >= cgroup_throttle_ratio_crit 이고 수집 시점 cpu% >= load_host_cpu_pct_max → 치명, 그 외 >= warn → 주의(OS-003, 카운터는 컨테이너 시작 이후 누적값). open_fd / max_fd >= fd_used_pct_warn → 주의(OS-004). mlockall=false 이고 swap 없음 → 참고(OS-005). uptime < uptime_short_hours → 주의(OS-006). uptime_short_hours 안에 재시작한 노드가 restart_share_warn 이상 → 주의(OS-007): 누적 카운터(GC, rejection, 캐시, 지연 평균)가 짧은 기간만 반영한다.

### DISK-001, DISK-002, DISK-003, DISK-004, DISK-005 — 디스크 flood stage 초과

| 항목 | 내용 |
| --- | --- |
| 함수 | `nodes.r_disk` |
| 판정 항목 | DISK-001 디스크 flood stage 초과 / DISK-002 디스크 high watermark 초과 / DISK-003 디스크 low watermark 초과 / DISK-004 디스크 사용률이 low 워터마크에 근접 / DISK-005 같은 tier 노드 간 디스크 사용률 편차 |
| 근거 구분 | 공식 기준 / 도구 판단 |
| 가능 심각도 | 치명, 주의, 참고, 정상 |
| 임계값 | `disk_imbalance_pct_warn` = 15 — [도구] 노드 간 디스크 사용률 편차(%p)<br>`disk_low_margin_pct` = 10 — [도구] 실효 low 워터마크까지 남은 %p |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |
| 참고 문서 | [디스크 기반 샤드 할당(워터마크)](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |

**판정 로직**

데이터 노드 사용률 = 1 − available / total. 실효 워터마크(max_headroom 반영, context.watermark_used_pct) 대비 flood 이상 → 치명(DISK-001. 전용 frozen 노드는 cache 전용이라 flood_stage.frozen 을 넘어도 별도 참고만 남기고 다른 조치는 없다), high 이상 → 치명(DISK-002, 샤드가 강제로 밀려나고 옮길 곳이 없으면 색인이 멈춘다), low 이상 → 주의(DISK-003), low − disk_low_margin_pct 이상 → 주의(DISK-004, 앞 세 항목이 없을 때만). 노드 간 사용률 최대−최소 >= disk_imbalance_pct_warn → 주의(DISK-005). 해당 없음 → 정상. 데이터 경로가 여럿이면 ES 처럼 flood·high 는 가용 공간이 가장 적은 경로, low 는 가장 많은 경로를 쓴다. disk.threshold_enabled=false 면 영향 문구에 워터마크가 적용되지 않는다고 적는다.

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

모든 스레드풀의 누적 rejected. 합계 > 0 → 주의, 합계 >= rejected_crit 이고 수집 시점에 rejection 이 난 풀의 queue > 0 → 치명(누적값만으로는 치명으로 올리지 않는다), 0 → 정상(TP-001). 주요 풀(write/search/get 등)의 queue > 0 → 참고(TP-002).

### BRK-001, BRK-002 — Circuit breaker 발동 이력

| 항목 | 내용 |
| --- | --- |
| 함수 | `nodes.r_breakers` |
| 판정 항목 | BRK-001 Circuit breaker 발동 이력 / BRK-002 Circuit breaker 사용률 높음 |
| 근거 구분 | 도구 판단 / 사실 보고 |
| 가능 심각도 | 치명, 주의 |
| 임계값 | `breaker_tripped_warn` = 1 — [도구] breaker 발동 횟수(1 = 이력 존재)<br>`breaker_used_pct_warn` = 70 — 높은 사용으로 보는 circuit breaker 추정 크기 / 한도(%) (request, fielddata, in_flight_requests 등)<br>`heap_used_pct_crit` = 85 — [공식] 조치가 필요한 JVM memory pressure(high JVM memory pressure 가이드) |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |

**판정 로직**

breaker.tripped >= breaker_tripped_warn → 주의, 수집 시점 사용률도 breaker_used_pct_warn 이상이면 치명(BRK-001.
누적 발동 이력만으로는 치명으로 올리지 않는다). 발동 이력은 없고 estimated / limit >= breaker_used_pct_warn →
주의(BRK-002).
indices.breaker.total.use_real_memory(기본 true)이면 parent 추정치는 young generation garbage 를 포함한 실제 heap 사용량이고,
발동 전에 ES 가 먼저 young GC 를 강제한다(소스의 G1OverLimitStrategy). 그래서 그 순간 사용률은 여기서
판정하지 않고, old generation 압박은 JVM-001 에서 판정한다. parent 발동(BRK-001)은 그대로 보고하며, 그 노드의
JVM memory pressure 가 heap_used_pct_crit 이상일 때만 치명이다.

### IP-001 — indexing pressure 거부

| 항목 | 내용 |
| --- | --- |
| 함수 | `nodes.r_indexing_pressure` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 주의 |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |

**판정 로직**

indexing_pressure.memory.total 의 coordinating, primary, replica 거부 중 하나라도 > 0 → 주의(util.ip_rejections. 다른
*_rejections 카운터는 표시만 하고 판정에 쓰지 않는다).

값이 -1 이면 노드가 카운터를 보고하지 못한 것(업그레이드 중 버전 혼재)이므로 무시한다.

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
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `ingest_fail_ratio_warn` = 0.01 — [도구] 파이프라인의 실패 / 처리 문서 비율<br>`ingest_failed_warn` = 1 — [도구]<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |

**판정 로직**

ingest 파이프라인 실패를 파이프라인별 실패율로 판정한다(ING-001).

ingest.total.failed >= ingest_failed_warn 인 노드가 있을 때 실행한다. 실패 건수와 처리 건수를 노드 전체에 걸쳐 파이프라인별로 합하고,
실패율 = 실패 / 처리. 실패율이 ingest_fail_ratio_warn 이상인 파이프라인이 있으면 → 주의, 없으면 참고.
노드 시작 이후 누적값이며, 다른 파이프라인에서 호출된 파이프라인은 양쪽에 모두 집계된다(호출한 쪽이 on_failure 나
ignore_failure 로 처리해도 중첩 파이프라인은 자기 실패를 센다). 어느 파이프라인에도 실패가 없으면(source 를 파싱할 수 없는 문서처럼
파이프라인 실행 전에 실패) 노드 합계 failed / count 로 판정한다.

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

같은 tier(데이터 역할 조합) 안에서 heap 또는 CPU 수가 다르면 주의(NODE-001).

tier 가 다르면 스펙이 다른 것이 정상 설계이므로 tier 간 차이는 판정하지 않고, tier 별 스펙 표만 참고로 보고한다
(NODE-003). 같은 tier 에서는 샤드가 균등 분배되므로 작은 노드가 먼저 포화되어 그 tier 의 처리 한계가 된다.

### PERF-012 — flush·refresh·merge 평균 시간이 김

| 항목 | 내용 |
| --- | --- |
| 함수 | `nodes.r_write_latency` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `flush_avg_ms_info` = 800 — [도구] 현장 기준: flush 1회 평균 시간<br>`flush_avg_ms_warn` = 1,200 — [도구] 현장 기준<br>`merge_avg_ms_info` = 20,000 — [도구] 현장 기준: merge 1회 평균 시간<br>`merge_avg_ms_warn` = 40,000 — [도구] 현장 기준<br>`refresh_avg_ms_info` = 40 — [도구] 현장 기준: refresh 1회 평균 시간<br>`refresh_avg_ms_warn` = 70 — [도구] 현장 기준<br>`write_latency_min_ops` = 100 — [도구] 노드 평균을 판정하기 위한 최소 flush/refresh/merge 횟수<br>`write_node_index_share_min` = 0.1 — [도구] 노드의 index_total 이 가장 많이 색인한 노드 대비 이 비율 이상이면 색인 노드로 봄 |
| 근거 파일 | nodes_stats.json (indices.flush / refresh / merges) |

**판정 로직**

노드별 flush, refresh, merge 평균 시간(nodes_stats indices.flush/refresh/merges 의 total_time / total).

실제로 색인하는 노드만 판정한다: 노드의 색인 속도(uptime 시간당 indices.indexing.index_total)가 가장 많이 색인한 data 노드의
write_node_index_share_min 이상. 시간당 값이라 최근 재시작한 노드도 같이 비교할 수 있다. data stream write index 를 가졌다는 것만으로는 부족하다. 수집량이 적은 stream 은 몇 달씩 쓰기가 거의 없는 write index 를
유지할 수 있기 때문이다. 색인하지 않는 노드의 merge 는 force merge(ILM forcemerge, searchable_snapshot 이 기본으로
앞 단계에서 하는 force merge, 수동 _forcemerge)이거나 rollover 직후 마무리 merge 다.
큰 segment 를 합치므로 평균이 긴 것이 스토리지가 느리다는 뜻은 아니다.
작업 수가 write_latency_min_ops 미만인 항목은 제외한다. merge 시간은 merge I/O throttling 으로 멈췄거나 중지된 시간까지
포함한 경과 시간이므로, throttled 와 stopped 시간을 먼저 뺀다.
평균 >= *_avg_ms_warn → 주의, >= *_avg_ms_info → 참고(PERF-012). 공식 수치가 아닌 현장 기준값이며,
노드 시작 이후 누적 평균이다. flush·merge 가 느리면 대개 스토리지가 따라가지 못하는 것이므로
IDX-005(merge throttling), IDX-014(indexing throttle)와 함께 본다.

### PERF-013 — CPU 는 낮은데 search 스레드가 바쁨

| 항목 | 내용 |
| --- | --- |
| 함수 | `nodes.r_search_pool_wait` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `search_io_cpu_pct_max` = 50 — [도구] search 풀이 바쁜데 노드 CPU 가 이보다 낮으면 대기 중인 것으로 봄<br>`search_pool_busy_share` = 0.8 — [도구] 활성 search 스레드 / 풀 크기가 이 이상이면 바쁜 것으로 봄 |
| 필요 입력 | (nodes.json) 그리고 (nodes_stats.json) |
| 근거 파일 | nodes.json / nodes_stats.json |

**판정 로직**

수집 시점 순간값 기준으로 노드 CPU 는 낮은데 search thread pool 이 바쁜 경우(PERF-013).

활성 search 스레드 >= 풀 크기(nodes.json thread_pool.search.size)의 search_pool_busy_share 이고 노드 CPU% <
search_io_cpu_pct_max. CPU 를 쓰지 않으면서 바쁜 스레드는 보통 무언가를 기다리고 있다. 대부분 스토리지 읽기(frozen shared
cache, 원격 스토리지)이고, 락이나 다른 노드 응답을 기다리는 경우도 있다. 그런 노드에 대기 중인 검색이 있으면 → 주의, 아니면 참고.
frozen 전용 노드는 원래 스냅샷 저장소에서 읽도록 설계되어 있으므로, 대기 중인 검색이 함께 있을 때만 해당으로 본다.
한 순간의 값이므로 hot threads(RT-001)와 스토리지 관련 판정(FRZ-002, PERF-009, DISK-008)과 함께 본다.

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

'heap 1GB당 샤드 20개' 는 8.3 미만 버전의 공식 기준이다. 8.3 부터 샤드당 heap 오버헤드가 크게 줄었고(Elastic 블로그)
공식 문서는 8.3.x 중에 이 기준을 '필드 매퍼 heap 산정(SHD-010)' 과 cluster.max_shards_per_node(CLU-015) 로 바꿨다.
따라서 8.3 이상(또는 버전을 알 수 없을 때)에서는 판정하지 않고 현황만 표기한다. 전용 frozen
노드는 별도 한도(cluster.max_shards_per_node.frozen) 아래 partial 마운트를 두므로 판정하지 않는다.

### SHD-006 — 같은 tier 노드 간 샤드 수 불균형

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_shard_balance` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `shard_balance_min_diff` = 10 — 같은 tier 노드 간 샤드 수 차이를 보고하는 최소 개수(SHD-006) |
| 필요 입력 | (indices.json 또는 shards.json 또는 cat_shards.txt) |
| 근거 파일 | indices.json / nodes.json |

**판정 로직**

같은 tier 안에서 노드 간 샤드 수 편차가 평균의 25% 이상이고 shard_balance_min_diff 개 이상이면
8.6 미만은 주의, 8.6 부터는 참고.

tier 마다 보관 데이터와 노드 수가 달라 tier 간 샤드 수 차이는 정상이므로 비교하지 않는다.
8.6 부터 desired balance allocator 는 write load 와 디스크 사용량도 반영하며, 공식 문서는 노드 작업을 고르게 하려고
샤드 수가 일부러 고르지 않을 수 있다고 하므로, 편차는 표시하되 문제로 판정하지 않는다.

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

query cache 와 shard request cache 의 효율.

request cache 만 판정한다(조회 10000건 이상, 적중률 < 20% 이고 eviction > hit → 주의). query cache eviction 은 merge 후 segment 가 닫히며 버려지는
항목도 세고, miss 에는 캐싱 정책이 캐시하지 않기로 한 조회도 들어가므로, query cache 적중률이 낮은 것 자체는
정상이라 표시만 한다.

### SHD-002, SHD-003 — 초대형 샤드 존재

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_shard_size` |
| 판정 항목 | SHD-002 초대형 샤드 존재 / SHD-003 대형 샤드 존재 |
| 근거 구분 | 공식 기준 / 도구 판단 |
| 가능 심각도 | 치명, 주의 |
| 임계값 | `docs_rollover_overshoot_pct` = 5 — [도구] 롤오버된 샤드가 2억건을 넘어도 되는 허용치(ILM 은 poll_interval 마다 확인)<br>`shard_size_gb_crit` = 200 — [도구] 복구 시간 기준 상한<br>`shard_size_gb_warn` = 50 — [공식] 샤드 10~50GB<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (indices.json 또는 shards.json 또는 cat_shards.txt) |
| 근거 파일 | indices.json |
| 참고 문서 | [샤드 사이징 가이드](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

primary 샤드 store >= shard_size_gb_crit → 치명(SHD-002), shard_size_gb_warn(공식 상한 50GB)을
docs_rollover_overshoot_pct 넘게 초과 → 주의(SHD-003). max_primary_shard_size 50gb 롤오버(기본 제공 정책)는
indices.lifecycle.poll_interval 마다 확인되므로, 샤드가 50GB 를 조금 넘어 끝나는 것은 설계상 정상이다.

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
현재 write index(데이터 스트림, failure store, rollover alias)는 아직 채워지는 중이라 작은 것이므로
소형으로 세지 않는다. 미할당 primary(store 크기 없음)는 건너뛴다. 근거 표는 사용자 소형 primary 를 데이터 스트림별(데이터 스트림 밖은 인덱스별)로 묶고,
shrink·force merge 가 안 되는 searchable snapshot 마운트가 몇 개인지 함께 보여 준다.

### IDX-001 — replica 0 인덱스 존재

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_replica_zero` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) 그리고 (indices_stats.json) |
| 근거 파일 | settings.json / indices_stats.json |

**판정 로직**

사용자 인덱스 중 number_of_replicas=0 이고 auto_expand_replicas 가 없거나 0-0 이며 searchable snapshot 인덱스가 아닌 것 → 주의.

data 노드가 1대면 replica 를 둘 곳이 없어 replica 0 이 green 이 되는 유일한 설정이므로 참고.

### IDX-002 — replica 수가 데이터 노드 수를 초과

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_replica_unassignable` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 주의 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) 그리고 (nodes.json) |
| 근거 파일 | settings.json |

**판정 로직**

number_of_replicas > (데이터 노드 수 − 1) → 주의(영구 미할당). auto_expand_replicas 인덱스는 제외. tier 별 노드 수는 보지 않으므로 보수적(미탐 가능, 오탐 없음) 판정이다. 노드 정보가 없으면 판정하지 않는다.

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

time-based 인덱스(context.time_based: 데이터 스트림과 @timestamp 필드가 있는 인덱스, 8.8 부터)는
LogByteSizeMergePolicy 를 쓴다. 이 정책은 인접 세그먼트만 합치고 크기 단계마다 최대 merge_factor - 1(기본 32 - 1)개의 세그먼트를 둔다
(Lucene LogMergePolicy: 한 단계는 merge_factor 로그 기준 floor_segment 위에서 0.75, 아래에서 1.5 폭). 20GB 샤드는 설계상 약 150개 세그먼트를 가질 수 있다.
그런 인덱스의 기준은 segments_per_shard_warn 과 (merge_factor - 1) x 단계 수 중 큰 값이다.

### IDX-005 — merge I/O throttle 관측

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_merge_throttle` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `merge_throttle_ratio_warn` = 0.05 — [도구]<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (indices_stats.json) |
| 근거 파일 | indices_stats.json |

**판정 로직**

merges.total_throttled_time / merges.total_time >= merge_throttle_ratio_warn 이고 throttled 누적 > 60초 → 표시.

throttled 시간은 merge scheduler 가 merge 디스크 쓰기 속도를 제한해(auto_throttle, merge 가 밀리면 올라가는 적응형 속도)
merge 가 쉰 시간이다. 비중이 높은 것만으로는 대개 merge 가 적은 동안 고르게 펴진 것이므로
참고. 같은 인덱스에서 색인 throttle(indexing.throttle_time_in_millis > 0, IDX-014 참고)도 있었을 때만 merge 가
밀린 것 → 주의.

### PERF-001, PERF-002 — 샤드당 평균 query 단계 시간이 높은 인덱스

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_search_latency` |
| 판정 항목 | PERF-001 샤드당 평균 query 단계 시간이 높은 인덱스 / PERF-002 색인 평균 지연 높은 인덱스 |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 치명, 주의 |
| 임계값 | `index_latency_ms_crit` = 200 — [도구] 문서당 평균 색인 시간<br>`index_latency_ms_warn` = 50 — [도구] 문서당 평균 색인 시간<br>`min_query_total_for_latency` = 100 — [도구] 표본이 적으면 판정 제외<br>`search_latency_ms_crit` = 1,000 — [도구] 인덱스 평균 query 지연<br>`search_latency_ms_warn` = 200 — [도구] 인덱스 평균 query 지연<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (indices_stats.json) |
| 근거 파일 | indices_stats.json |

**판정 로직**

query_total >= min_query_total_for_latency 인 인덱스의 샤드당 평균 query 단계 시간 = query_time / query_total(샤드마다 한 번씩 세며 요청 지연이 아님). >= search_latency_ms_crit → 치명, >= warn → 주의(PERF-001). 문서당 평균 색인 시간 = index_time / index_total 에 대해 index_latency_ms_crit / warn 으로 동일 판정(PERF-002). 누적 평균이며 p99 가 아니다. partial mount(frozen) 인덱스는 캐시에 없는 데이터를 스냅샷 저장소에서 읽으므로 검색이 느린 것이 정상이라 검색 지연을 판정하지 않는다(FRZ-001 참고).

### IDX-006 — 색인/검색 실패 카운터 존재

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_index_failures` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `query_failure_pct_warn` = 1 — [도구] 문제로 보는 사용자 인덱스의 query 실패 / query 수(%)(IDX-006)<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (indices_stats.json) |
| 근거 파일 | indices_stats.json |

**판정 로직**

indexing.index_failed 또는 search.query_failure > 0 인 인덱스.

index_failed 는 primary 의 엔진 단계에서 실패한 작업을 센다(소스의 IndexShard / InternalIndexingStats):
version conflict 와 엔진 오류. 문서 파싱·매핑 오류는 엔진 실행 전에 반환되므로
여기서 세지 않는다. 8.18 부터 통계가 index_failed_due_to_version_conflict 를 따로 보고하며, version conflict 는
op_type=create 재시도(Elastic Agent, Fleet)에서 정상적으로 생긴다. 비율은 primary 의 index_total 을 쓴다. index_failed 는
primary 에서만 세지만 total 의 index_total 은 replica 작업도 포함하기 때문이다.
query_failure 는 query 단계의 모든 예외를 세며 취소된 검색도 포함하므로 몇 건은 정상이다.
8.18 이전은 충돌을 구분할 수 없으므로 index_failed 만으로는 판정하지 않는다(메모와 함께 표시).
사용자 인덱스에 version conflict 외의 실패가 있거나, query 실패가 query 의 query_failure_pct_warn 퍼센트 이상(그리고 10건 이상)이면
주의, 아니면 참고. 표는 그런 인덱스가 앞에 오도록 정렬한다.

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

사용자 인덱스의 mapping.total_fields.limit > 1000(기본값) → 주의(MAP-001). 해당 인덱스가 모두
ignore_dynamic_beyond_limit=true(설정이 없으면 기본값: 최근 인덱스 버전의 logsdb 인덱스는 true)이거나 Elastic 통합 패키지의
데이터 스트림(_meta 의 package 또는 managed_by fleet)이라 한도가 제품 설정이면 참고. searchable
snapshot mount 는 읽기 전용이라 제외한다. cluster_stats 전체 필드 수 > 100,000 → 참고(MAP-002).

### IDX-007 — 대량 색인 인덱스에 refresh_interval 1초 이하 명시

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_refresh_interval` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 참고 |
| 임계값 | `heavy_index_docs` = 10,000,000 — [도구] 대량 색인 인덱스 기준<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) 그리고 (indices_stats.json) |
| 근거 파일 | settings.json / indices_stats.json |
| 참고 문서 | [Index modules (refresh_interval, search idle)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |

**판정 로직**

refresh 주기.

refresh_interval 을 명시하지 않은 인덱스는 search idle 동작이 적용된다.
index.search.idle.after(기본 30s) 동안 검색이 없던 샤드는 주기적 refresh 를 건너뛰므로,
'미지정 = 매초 refresh' 가 아니다. 따라서 명시적으로 1s 이하로 지정한 인덱스만 판정한다.

### IDX-008, IDX-011 — 쓰기 대상 인덱스 또는 flood stage 쓰기 차단

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_read_only_blocks` |
| 판정 항목 | IDX-008 쓰기 대상 인덱스 또는 flood stage 쓰기 차단 / IDX-011 write 대상이 아닌 인덱스의 쓰기 블록(의도 확인) |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 치명, 참고, 정상 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) |
| 근거 파일 | settings.json / alias.json / settings.json / commercial/data_stream.json / alias.json |

**판정 로직**

인덱스 쓰기 차단을 '정상 차단' 과 '문제 차단' 으로 구분한다.

정상(판정 안 함, 건수만 참고): searchable snapshot 마운트 인덱스, 롤오버가 끝난 인덱스
(데이터 스트림의 과거 백킹 인덱스·쓰기 대상이 아닌 alias 멤버·indexing_complete=true).
ILM 의 readonly·shrink·forcemerge·searchable_snapshot 단계는 롤오버 후 인덱스에 write 차단을 거는 것이 정상 동작이다.
문제(치명, IDX-008): index.blocks.read_only_allow_delete=true(대개 flood stage 흔적, 모든 인덱스 대상),
또는 현재 쓰기 대상(데이터 스트림 write index, failure store write index, alias write index,
legacy rollover alias)에 write·read_only 차단.
확인 필요(참고, IDX-011): 롤오버되지 않은 그 밖의 인덱스의 write·read_only 차단: 독립 인덱스, write index 가 없는
alias 의 멤버, is_write_index 표시가 없는 alias 의 유일한 멤버(대개 읽기 alias). 의도적
보관일 수 있다.

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

인덱스가 요구하는 데이터 tier 가 실제 노드에 존재하는지. 범용 data 역할은 frozen 을 포함한
모든 tier 로 친다(Elasticsearch 소스의 DataTier).

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

partial 마운트(frozen) 샤드는 store 크기가 0 으로 보고되므로 평균 계산의 샤드 수에서 뺀다.

### SHD-016 — 쓰기 대상 shard 가 일부 노드에 몰림

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_write_hotspot` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수<br>`write_shard_skew_min` = 3 — [도구] 보고할 최소 쓰기 대상 shard 차이<br>`write_shard_skew_warn` = 0.5 — [도구] tier 안 노드별 쓰기 대상 shard 의 (최대 - 최소) / 평균 |
| 근거 파일 | indices.json / commercial/data_stream.json / alias.json / indices_stats.json |

**판정 로직**

tier 안 노드별 쓰기 대상 shard 수(SHD-016).

쓰기 대상은 data stream write index, alias write index, 수집 시점에 색인 중인 index 중 indexing.index_total > 0 인 것이다(수집량 적은 stream 은 몇 달씩 쓰기가 없는 write index 를 유지할 수 있다). replica 도 색인하므로 포함한다.
tier 별로(frozen 과 노드 2대 미만 tier 제외) (최대 - 최소) / 평균 >= write_shard_skew_warn 이고
최대 - 최소 >= write_shard_skew_min → 주의. SHD-006 은 전체 shard 를 비교하고,
이 판정은 색인 부하가 실제로 걸리는 쓰기 대상 shard 만 비교한다.

### IDX-014 — 색인 throttle 발생

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_indexing_throttle` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 근거 파일 | indices_stats.json |
| 참고 문서 | [Merge settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/merge) |

**판정 로직**

색인이 throttle 된 상태(IDX-014).

공식: merge 의 I/O throttle 을 모두 풀어도 밀리면, merge 가 따라잡을 때까지 그 shard 의 색인을 throttle 한다. indexing
memory controller 도 indexing buffer 가 1.5 x indices.memory.index_buffer_size 를 넘으면 가장 바쁜 shard 를 throttle 한다(소스).
indices_stats indexing.is_throttled = true(수집 시점) → 주의. 누적 indexing.throttle_time > 0 만 있으면 → 참고.

### IDX-015 — 미커밋 translog 가 flush 기준을 넘음

| 항목 | 내용 |
| --- | --- |
| 함수 | `shards.r_translog_uncommitted` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수<br>`translog_flush_threshold_default` = 10gb — [공식] index.translog.flush_threshold_size 기본값(8.8+)<br>`translog_flush_threshold_legacy` = 512mb — [공식] 8.8 이전 기본값 |
| 근거 파일 | indices_stats.json / settings.json |
| 참고 문서 | [Translog settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/translog) |

**판정 로직**

shard 복제본당 미커밋 translog 를 index.translog.flush_threshold_size 와 비교한다(IDX-015).

공식: 미커밋 translog 가 flush_threshold_size(기본 10GB)에 닿으면 flush 가 실행되고, 미커밋 작업은 복구 때 다시 적용된다
(8.8 이전 기본값은 512MB). 8.8 부터 ES 는 이 기준을 디스크의 1%(최소 10MB)로도 제한하며(IndexSettings.getFlushThresholdSize),
그 인덱스를 가진 노드 중 가장 작은 디스크를 쓴다. 할당된 복제본당 평균 미커밋 크기(index 합계 / 복제본 수)가
실효 기준 이상 → 주의: flush 가 따라가지 못하고, 그 shard 를 복구하면
그만큼 다시 적용해야 한다.

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
빈 인덱스는 SHD-011 에서 다룬다.
권장 primary 수 = 샤드당 oversharding_target_shard_gb(공식 상한 50GB) 이하를 유지하는 현재 개수의 약수 중 가장 작은 값
(shrink 는 약수로만 가능). 초과 샤드 = (현재 − 권장) × (1 + replica).
초과 샤드 합계 >= oversharding_excess_warn 또는 전체 샤드 대비 비중 >= oversharding_excess_ratio_warn → 주의,
그 외 대상이 있으면 참고.

### OVS-002 — 데이터 스트림 롤오버 과다(작은 백킹 인덱스 누적)

| 항목 | 내용 |
| --- | --- |
| 함수 | `sharding.r_datastream_small_rollover` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `ds_min_backing_indices` = 5 — [도구] 데이터 스트림 판정 최소 백킹 수<br>`ds_small_backing_shard_gb` = 1 — [도구] 백킹 샤드 중앙값 기준<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (data_stream.json) 그리고 (indices_stats.json) |
| 근거 파일 | commercial/data_stream.json / indices_stats.json |
| 참고 문서 | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

데이터 스트림의 롤오버가 너무 잦아 작은 백킹 인덱스가 쌓이는지 확인한다.

write index 와 partial(frozen) 마운트 백킹 인덱스(크기가 캐시 크기)를 제외한 백킹 인덱스가
ds_min_backing_indices 개 이상이고, 그 primary 샤드당 크기의 중앙값이
ds_small_backing_shard_gb 미만이면 표시한다. ILM 롤오버에 크기·문서 수 조건(max_primary_shard_size, max_size,
max_docs, max_primary_shard_docs)이 없으면 원인은 기간만으로 일어나는 롤오버 → 주의. 그런 조건이 있으면(기본 제공 logs@lifecycle,
metrics@lifecycle 정책과 data stream lifecycle 은 primary 샤드당 50GB 에서 롤오버) 단지 수집량이 적은 것이므로
→ 참고이며, max_age 를 늘리거나 데이터 스트림 수를 줄이도록 안내한다. 다음 세대를 data stream lifecycle 이 관리하는 스트림은
lifecycle 기준으로 판단하고, 정책이나 rollover 액션이 번들에 없거나 ILM·lifecycle 이 모두 없으면
원인을 알 수 없음 또는 자동 롤오버 없음(참고)으로 표시한다.
Elasticsearch 가 스스로 관리하는 데이터 스트림(ilm-history-*)은 건너뛴다.

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

데이터가 있는(문서 1건 이상) 사용자 primary(크기가 캐시 크기인 partial 마운트와 write index 는
제외, fully mounted searchable snapshot 은 포함)가 oversharding_min_shards 개 이상이고,
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
| 참고 문서 | [Index modules (index.max_result_window)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules)<br>[Paginate search results](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/paginate-search-results) |

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
마운트하는 구조라 대상이 아니다. build_type 으로 판별한다. path.data 가 없으면
$ES_HOME/data 이며, zip(Windows) 경로는 구분자와 대소문자를 무시하고 비교한다.

### CFG-004, CFG-005, CFG-006 — discovery.seed_hosts 미설정

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_discovery` |
| 판정 항목 | CFG-004 discovery.seed_hosts 미설정 / CFG-005 cluster.initial_master_nodes 잔존 / CFG-006 development mode 로 동작 중인 노드 |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의 |
| 필요 입력 | (nodes.json) |
| 근거 파일 | nodes.json / nodes.json (transport_address) |
| 참고 문서 | [Important settings configuration](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/important-settings-configuration)<br>[Bootstrap checks](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/bootstrap-checks) |

**판정 로직**

다중 노드인데 discovery.seed_hosts / seed_providers(또는 7.x 의 discovery.zen 이름)가 없음 → 주의(CFG-004. nodes.json 에
설정이 없는 노드는 건너뜀). cluster.initial_master_nodes 가 남아 있음 → 주의(CFG-005). 개발 모드인 노드
(context.dev_mode: transport 가 loopback 에만 바인딩되었거나 discovery.type=single-node, 단 -Des.enforce.bootstrap.checks=true 는 예외)
→ 주의(CFG-006). 오케스트레이터 배포면 모두 참고로 하향.

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

### SHD-007, SHD-008, SHD-013 — 샤드 문서 수가 Lucene 한계에 근접

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_docs_per_shard` |
| 판정 항목 | SHD-007 샤드 문서 수가 Lucene 한계에 근접 / SHD-008 샤드당 문서 수 권장치 초과 / SHD-013 늦게 롤오버된 샤드 |
| 근거 구분 | 공식 기준 / 도구 판단 |
| 가능 심각도 | 치명, 주의, 참고 |
| 임계값 | `docs_per_shard_crit` = 1,500,000,000 — [도구] Lucene 한계(2,147,483,519) 접근 경보<br>`docs_per_shard_warn` = 200,000,000 — [공식] 샤드당 2억건 미만 권장<br>`docs_rollover_overshoot_pct` = 5 — [도구] 롤오버된 샤드가 2억건을 넘어도 되는 허용치(ILM 은 poll_interval 마다 확인)<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (indices.json 또는 shards.json 또는 cat_shards.txt) 그리고 (indices_stats.json) |
| 근거 파일 | indices.json / indices.json / commercial/ilm_explain.json |
| 참고 문서 | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards)<br>[Rollover (ILM): max_primary_shard_docs](https://www.elastic.co/docs/reference/elasticsearch/index-lifecycle-actions/ilm-rollover)<br>[ILM settings: indices.lifecycle.poll_interval](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/index-lifecycle-management-settings) |

**판정 로직**

샤드별 문서 수. 인덱스 평균이 아니라 샤드 단위(cat shards) 값으로 판정한다.

Lucene 한계(2,147,483,519)는 삭제 문서를 포함한 maxDoc 기준이다. cat shards 에는 삭제 수가 없어
인덱스 삭제 수를 primary 수로 나눈 값을 더한다(추정치임을 표기).
rollover 는 샤드 문서 수가 2억건에 닿으면 항상 실행되고, ILM 은 poll_interval(기본 10m)마다 조건을 확인하므로
롤오버가 끝난 인덱스는 보통 2억건을 조금 넘는다. 롤오버된 인덱스는 2억건을 docs_rollover_overshoot_pct 보다 크게
넘었을 때만 보고한다(SHD-013, rollover 지연): 데이터 스트림의 가장 최근 완료 세대(또는 데이터 스트림 밖 인덱스)가 늦게 끝났으면
주의, 이전 세대만 늦었으면 참고. 데이터 스트림 백킹 인덱스의 searchable snapshot mount(데이터 스트림에 있거나
mount 접두어를 뗀 이름이 .ds- 로 시작)도 쓰기가 없으므로 같게 판정하고, 그 밖의 mount 는 롤오버된 적이 없으므로
SHD-008 로 판정한다.
write index 와 rollover 를 쓰지 않는 인덱스는 SHD-008 로 판정한다. 암묵적 2억건 rollover 는 8.8 부터 있으므로(ILM 소스),
8.8 미만에서는 롤오버된 인덱스도 SHD-008 로 판정한다.

### SHD-014, SHD-015 — 도구 권장 범위보다 큰 logsdb shard

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_logsdb_shard_size` |
| 판정 항목 | SHD-014 도구 권장 범위보다 큰 logsdb shard / SHD-015 공식 권장 범위보다 작게 롤오버되는 logsdb 인덱스 |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 참고 |
| 임계값 | `ds_min_backing_indices` = 5 — [도구] 데이터 스트림 판정 최소 백킹 수<br>`ilm_implicit_max_shard_docs` = 200,000,000 — [공식] 샤드당 2억건이면 rollover 가 항상 실행됨. 더 큰 값은 효과 없음<br>`logsdb_rows_max` = 100 — [도구] logsdb shard 크기 표에 보여 줄 최대 인덱스 수<br>`logsdb_shard_gb_high` = 30 — [도구] logsdb shard 범위 상한(공식 상한은 50GB)<br>`logsdb_shard_gb_low` = 10 — [공식] 10~50GB 범위의 하한<br>`shard_size_gb_warn` = 50 — [공식] 샤드 10~50GB |
| 필요 입력 | (indices.json 또는 shards.json 또는 cat_shards.txt) 그리고 (settings.json 또는 data_stream.json) |
| 근거 파일 | indices.json / settings.json / commercial/data_stream.json / indices.json / settings.json / commercial/data_stream.json / commercial/ilm_policies.json |
| 참고 문서 | [Rollover (ILM): max_primary_shard_docs](https://www.elastic.co/docs/reference/elasticsearch/index-lifecycle-actions/ilm-rollover)<br>[Configure a logs data stream](https://www.elastic.co/docs/manage-data/data-store/data-streams/logs-data-stream-configure)<br>[Index sorting settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/sorting)<br>[Force merge API](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-indices-forcemerge)<br>[Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

logsdb 인덱스의 primary shard 크기를 10~30GB 범위와 비교한다(도구 판단, 참고).

근거: rollover 는 샤드 문서 수가 2억건에 닿으면 항상 실행되고(공식), 공식 문서도 공간 효율이 좋은 데이터는 50GB 전에
2억건에 닿는다고 설명한다. logsdb 는 기본으로 host.name, @timestamp 로 정렬하고(공식), index sorting 은 flush·merge 때
비용이 든다(공식). 1 segment force merge 는 shard 크기의 최대 3배 여유 공간이 필요하고(공식), 큰 shard 는 복구가 오래 걸린다(공식).
30GB 상한은 공식 수치가 아니다. logsdb·TSDB 에는 10~30GB 가 맞다는 Elastic 내부 논의를 따른다. 공식 10~50GB 범위와
SHD-003(50GB 이상)은 그대로 적용한다.

partial mount(frozen) 인덱스는 크기가 캐시 크기라 제외한다. 인덱스마다 가장 큰 primary shard 로 판정한다.
logsdb_shard_gb_high <= 최대 primary < shard_size_gb_warn → SHD-014(참고, 인덱스별 표). 단
searchable snapshot mount(바꿀 수 없음)와 현재 정책이 이미 max_primary_shard_size 를
logsdb_shard_gb_high 이하로 둔 인덱스는 제외한다. logsdb_shard_gb_low 이상의 max_primary_shard_size 로 끝난 인덱스는 작지 않은 것으로 본다.
SHD-015(참고)는 data stream 단위로 판정한다: 끝난 backing index(롤오버 또는 mount) 중 최대 primary 가
logsdb_shard_gb_low 미만이고 문서가 1건 이상 2억건 미만인 인덱스가 ds_min_backing_indices 개 이상인 data stream. 이 인덱스들은
문서 수 한도가 아니라 max_age 나 작은 크기 조건으로 끝났다. 빈 인덱스는 SHD-011 에서 다룬다.
표의 rollover 조건은 추정치다(SHD-015 는 data stream 별로 가장 많은 조건).

### IDX-013 — logsdb 가 적용되지 않은 logs-*-* data stream

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_logsdb_adoption` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 참고 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (data_stream.json) |
| 근거 파일 | commercial/data_stream.json / settings.json |
| 참고 문서 | [Logs data streams](https://www.elastic.co/docs/manage-data/data-store/data-streams/logs-data-stream)<br>[Configure a logs data stream](https://www.elastic.co/docs/manage-data/data-store/data-streams/logs-data-stream-configure) |

**판정 로직**

Elasticsearch 9.0 이상에서 write index 가 logsdb 가 아닌 logs-*-* data stream → 참고(IDX-013).

공식: 9.0 부터 새 logs-*-* data stream 에는 logsdb 가 자동 적용된다. 8.x 에서 업그레이드하기 전부터 있던 data stream
(integration·APM 포함)은 바뀌지 않는다. time_series, 또는 9.5 에 추가된 columnar·logsdb_columnar 모드로 설정된 data stream 은
제외하고, settings.json 과 data_stream.json 의 index_mode 가 모두 없어 mode 를 알 수 없는 번들도 제외한다.
이를 정하는 설정은 cluster.logsdb.enabled 다. 9.0 이전부터 logs 데이터가 있었으면(logsdb.prior_logs_usage) 기본값이 false 이고,
false 인 동안은 새 logs-*-* 인덱스도 standard 로 만들어진다. 번들에 값이 있으면 함께 보여 준다.

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

마스터 후보 노드 heap 1GB당 인덱스 3000개 기준. voting-only 노드는 뺀다: 선출 마스터가 되지 않으며
공식 문서는 heap 이 덜 필요할 수 있다고 한다. 용량의 80% 초과 → 주의, 100% 초과 → 치명.

### SHD-010 — 매핑 메타데이터가 heap 을 과도하게 점유

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_mapping_heap_overhead` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고, 정상 |
| 임계값 | `heap_baseline_bytes` = 512MiB — [공식] 필드 매퍼 산정 시 추가 여유 0.5GB<br>`mapping_heap_pct_warn` = 50 — [도구] 매핑 오버헤드 추정 / heap |
| 필요 입력 | (nodes_stats.json) 그리고 (cluster_stats.json) |
| 근거 파일 | cluster_stats.json / nodes_stats.json |
| 참고 문서 | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

데이터 노드별 필요 heap 추정 = cluster state 매핑 크기(중복 제거) + 노드 필드 오버헤드 + 0.5GB(공식 산정식).

공식 기준은 추정치가 heap 안에 들어가는지다: 추정치 >= heap_max → 주의. 추정치 / heap_max >= mapping_heap_pct_warn
(도구 판단) → 참고, 미만 → 정상. 전용 마스터·ML 노드는 산정 대상이 아니다.

### SHD-011 — 빈 인덱스 다수

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_empty_indices` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의 |
| 임계값 | `empty_index_count_warn` = 5 — [도구]<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (indices_stats.json) |
| 근거 파일 | indices_stats.json |
| 참고 문서 | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

docs.count=0 인 사용자 인덱스 수 >= empty_index_count_warn → 주의.

현재 쓰기 대상(데이터 스트림 write index, alias write index)은 막 롤오버되어 비어 있을 수 있으므로 제외한다.
searchable snapshot mount 도 쓰기가 없고 ILM 이 지우므로 제외한다.

### SHD-012 — 색인량 많은 인덱스에 total_shards_per_node 미설정

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_total_shards_per_node` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 참고 |
| 임계값 | `heavy_index_docs` = 10,000,000 — [도구] 대량 색인 인덱스 기준<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) 그리고 (indices_stats.json) |
| 근거 파일 | settings.json / indices_stats.json |
| 참고 문서 | [Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

핫스팟 방지용 index.routing.allocation.total_shards_per_node 설정 여부(대형 색인 인덱스).

롤오버된 인덱스와 searchable snapshot 인덱스는 쓰기가 없어 이 설정이 의미가 없다(데이터 스트림은
index template 에 둔다). primary 가 1개인 인덱스는 건너뛴다: 같은 샤드의 두 사본은 한 노드에 놓이지 않으므로
(SameShardAllocationDecider) 이 제한으로 더 분산할 수 없다. index_total 은 누적값이므로 지금 쓰기를 받는 인덱스만
표시한다: recent_write_load 가 1e-6 초과(9.1+ 통계), 아니면 write 대상이거나 수집 순간 색인 중인 인덱스. 색인 문서 수는
primary 기준이다(total 은 replica 작업도 포함).

### PERF-004 — 쓰기 대상 샤드당 indexing buffer 부족

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_index_buffer` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 참고 |
| 임계값 | `index_buffer_per_shard_warn` = 32MiB — [도구] 쓰기 대상 샤드당(공식 상한은 512MB) |
| 필요 입력 | (nodes.json) 그리고 (indices.json 또는 shards.json 또는 cat_shards.txt) |
| 근거 파일 | nodes.json / commercial/data_stream.json / indices.json |
| 참고 문서 | [Tune for indexing speed](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/indexing-speed) |

**판정 로직**

샤드당 indexing buffer.

indices.memory.index_buffer_size(기본 heap 10%)는 '최근 쓰기가 있는(active) 샤드' 가 나눠 쓴다.
5분 이상(indices.memory.shard_inactive_time, 소스 기준) 쓰기가 없는 샤드는 inactive 로 버퍼를 반납한다. 번들에서 active 여부를 직접 알 수 없으므로
실제 쓰기가 있는 샤드만 센다: recent_write_load(9.1+, 반감기 5분으로 줄어듦)가 있으면 쓰기 스레드의 1% 이상을 쓰는
샤드 복사본, 이전 버전은 수집 순간 색인 중인 인덱스.
버퍼는 균등하게 나뉘지 않는다: IndexingMemoryController 는 합계가 예산을 넘을 때만 가장 큰 샤드에 refresh 를 요청하므로
크기 안내(참고)다.
ES 는 nodes info 의 두 버퍼 필드를 반대로 기록하므로(total_indexing_buffer 에 바이트,
total_indexing_buffer_in_bytes 에 읽기용 값) 숫자인 쪽을 쓴다.

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

search.default_search_timeout 이 미설정 또는 -1(무제한. 0 은 무제한이 아니라 즉시 timeout)이면 참고. 번들에 클러스터 설정이 없으면 건너뛴다.

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

num_nodes 는 전체 data 노드가 아니라 인덱스가 있는 tier(primary 샤드의 tier)의 data 노드 수다.
searchable snapshot 마운트는 건너뛴다(설계상 replica 0).

### PERF-008 — index.store.preload 사용 인덱스

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_store_preload` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `preload_index_count_warn` = 5 — [도구]<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) |
| 근거 파일 | settings.json |
| 참고 문서 | [Tune for search speed](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/search-speed)<br>[Tune approximate kNN search](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/approximate-knn-search) |

**판정 로직**

index.store.preload 가 설정된 인덱스가 있으면 참고, 개수가 preload_index_count_warn 초과면 주의.

vectordb_document 인덱스(9.5)는 벡터 파일용 index.store.preload 가 자동으로 붙으므로 그 값 그대로면 나열하지 않는다.

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

nodes_stats fs.data[].type 이 네트워크 파일시스템(util.NET_FS: nfs / cifs / smb / fuse / glusterfs / ceph / lustre /
gpfs / beegfs / 9p, fuseblk 같은 로컬 FUSE 는 제외)이면 주의.

### DISK-006 — 대형 인덱스의 기본 codec

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_codec` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 참고 |
| 임계값 | `codec_check_min_bytes` = 50GiB — [도구]<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) 그리고 (indices_stats.json) |
| 근거 파일 | settings.json / indices_stats.json |
| 참고 문서 | [Tune for disk usage](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/disk-usage) |

**판정 로직**

primary store >= codec_check_min_bytes 이고 index.codec 를 기본값(미설정)으로 둔 사용자 인덱스 → 참고.

기본 codec 이 best_compression 인 index mode 는 뺀다: logsdb, 그리고 9.5 에 추가된 columnar·logsdb_columnar 모드
(공식 logsdb 문서와 Elasticsearch 소스의 IndexMode). standard, time_series, vectordb_document 인덱스는 기본이
LZ4 codec 이다. searchable snapshot 마운트는 건너뛰고(설정이 snapshot 에서 오며 바꿀 수 없음), 저장된 _source 가 없는
인덱스(synthetic 또는 time_series. codec 이 영향을 주는 저장 데이터가 적음)도 건너뛴다.

### DISK-007 — _source 비활성 인덱스

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_source_mode` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json 또는 mapping.json) |
| 근거 파일 | mapping.json / settings.json / settings.json |
| 참고 문서 | [Tune for disk usage](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/disk-usage)<br>[_source 필드](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/mapping-source-field) |

**판정 로직**

_source 비활성 → 주의, synthetic _source → 참고(DISK-007).

비활성은 두 가지로 찾는다: mapping.json 의 매핑 파라미터 "_source": {"enabled": false}(문서에 나온 방법)와 settings.json 의
index.mapping.source.mode=disabled. index.mapping.source.mode=synthetic 과 columnar_stored(9.5 columnar
모드)는 참고로 나열한다: 돌려받는 _source 는 원본이 아니라 다시 만든 것이다. stored 는 기본값이라 나열하지 않는다.
설정이 없으면 index mode 가 정한다(8.17 부터, 소스의 IndexMode.defaultSourceMode): logsdb, time_series,
9.5 columnar 모드는 기본이 synthetic 이다. 라이선스가 synthetic source 를 허용하지 않으면 ES 가 mode: stored 를
인덱스 설정에 기록하므로, 이 모드에서 설정이 없으면 synthetic 이다. 예전 매핑 형식 "_source": {"mode": "synthetic"} 도
센다. system 인덱스는 건너뛴다.

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

Elasticsearch 가 스스로 설치·관리하는 template(Fleet package 없이 _meta.managed: true)은 사용자가 고치지 않으므로
건너뛴다. 현재 어떤 인덱스나 데이터 스트림과도 맞지 않는 template 도 아직 영향이 없으므로 건너뛴다.
dynamic 이 없거나 true 이고 dynamic_templates 가 없는 template 을 표시한다.

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

인덱스별 dense_vector off-heap(total, 없으면 primaries). 상주 필요량 = (veq+veb 가 있으면 그 값, 없으면 vec) + vex,
DiskBBQ(IVF) 인덱스는 cenivf + veq + veb + vex. 합계 / Σ(그 인덱스 샤드를 가진 데이터 노드의 RAM − heap) >= vector_vs_fscache_pct_warn → 주의,
미만 → 참고. 그 노드들의 합계이며 노드별 분포는 보지 않는다. 벡터 인덱스가 모두 시스템 인덱스면 안내 문구가 그렇게 말한다.

### VEC-002, VEC-003 — 고차원 float 벡터에 비양자화 인덱스 사용

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_vector_quantization` |
| 판정 항목 | VEC-002 고차원 float 벡터에 비양자화 인덱스 사용 / VEC-003 _source 에 벡터 유지 |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수<br>`vector_dim_quantize_warn` = 384 — [공식] 384차원 이상 float 벡터는 양자화 권장 |
| 필요 입력 | (index_templates.json) |
| 근거 파일 | index_templates.json / component_templates.json |
| 참고 문서 | [Tune approximate kNN search](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/approximate-knn-search) |

**판정 로직**

고차원 float 벡터의 양자화 여부(component 병합 후 판정).

8.14 부터 index_options 가 없는 float dense_vector 는 기본으로 양자화된 HNSW 가 된다(int8_hnsw. 9.1 부터 384 차원 이상은 bbq_hnsw,
9.4 부터는 라이선스가 허용하면 bbq_disk). float 와 bfloat16 벡터를 판정하고, byte·bit 벡터는 양자화하지 않으므로
판정하지 않는다. 버전을 모르면 최신으로 본다.
그래서 8.14 이상에서 '미지정' 은 문제로 보지 않고, 명시적 비양자화 타입(hnsw/flat)만 판정한다(VEC-002).
index: false 인 필드(또는 dense_vector 가 기본으로 색인되지 않던 8.11 미만에서 index 파라미터가 없는 필드)는 HNSW 가 없어
건너뛰며, 양자화 타입이 없는 8.12 미만에서는 VEC-002 를 판정하지 않는다.
VEC-003(참고): 9.2 부터 index.mapping.exclude_source_vectors 가 기본으로 켜져 있으므로 이를 false 로 둔 template 만 표시한다.
9.2 미만에는 이 설정이 없으므로, mappings._source.excludes 가 벡터 필드를 덮지 않는 template 을 표시하고
그 방식으로 제외할 때의 trade-off 를 설명한다. _source 가 비활성이거나 synthetic 인 template(logsdb,
time_series 포함)은 건너뛴다: 그곳에서는 벡터가 _source 에 저장되지 않는다.

### VEC-004 — 벡터 인덱스의 세그먼트 수 과다

| 항목 | 내용 |
| --- | --- |
| 함수 | `guidance.r_vector_segments` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수<br>`vector_segments_per_shard_warn` = 20 — [도구] |
| 필요 입력 | (indices_stats.json) 그리고 (indices.json 또는 shards.json 또는 cat_shards.txt) |
| 근거 파일 | indices_stats.json / settings.json |
| 참고 문서 | [Tune approximate kNN search](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/approximate-knn-search) |

**판정 로직**

벡터 데이터가 있는 인덱스의 primary 세그먼트 / primary 샤드 >= vector_segments_per_shard_warn → 주의.

max_merged_segment 열은 설정이 없으면 실효 기본값(time-based 인덱스는 100gb)을 보여 주고, 값을 올리라는 안내는
표시된 인덱스 중 10GB 미만이 있을 때만 한다.

## 핫스팟 · 밸런싱

### HOT-005.(하위 항목) — %s tier 전체 CPU 포화

| 항목 | 내용 |
| --- | --- |
| 함수 | `hotspot.r_tier_saturation` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의 |
| 임계값 | `load_host_cpu_pct_max` = 50 — [도구] 이 CPU% 미만인 컨테이너 노드는 load average 로 판정하지 않음(호스트 값이므로)<br>`load_per_cpu_warn` = 1.0 — [도구] load15 / CPU 코어<br>`tier_cpu_pct_warn` = 75 — [도구] tier 전체 포화 판정 CPU% |
| 필요 입력 | (nodes_stats.json) 그리고 (nodes.json) |
| 근거 파일 | nodes_stats.json |
| 참고 문서 | [Hot spotting 문제 해결](https://www.elastic.co/docs/troubleshoot/elasticsearch/hotspotting) |

**판정 로직**

tier 단위 CPU 포화. 한 tier 의 모든 노드가 load15/CPU >= load_per_cpu_warn 또는 CPU% >= tier_cpu_pct_warn 이면 주의.
OS-001 과 같이, CPU 사용이 낮은 컨테이너 노드는 load 만으로 세지 않는다(load 가 호스트 값일 수 있음). load 만으로 세었고
CPU 가 load_host_cpu_pct_max 미만인 노드는 관측 문구에 적는다: load 가 CPU 가 아니라 디스크 대기일 수 있다.

노드 간 '편중'(HOT-001)과 다르다. 부하가 고르게 분산되어도 tier 전체가 한계에 있으면 노드를 추가하거나 부하를 줄여야 한다.
그 tier 의 cgroup CPU throttling(OS-003)과 write, write_coordination, search 스레드풀 rejection(TP-001)을 근거로 함께 제시한다.

### HOT-001 — 같은 tier 안에서 자원 사용률 편중(hot spotting 의심)

| 항목 | 내용 |
| --- | --- |
| 함수 | `hotspot.r_resource_hotspot` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 정상 |
| 임계값 | `disk_imbalance_pct_warn` = 15 — [도구] 노드 간 디스크 사용률 편차(%p)<br>`hotspot_cpu_pct_floor` = 50 — [도구]<br>`hotspot_cpu_pct_gap` = 40 — [도구]<br>`hotspot_disk_pct_floor` = 50 — [도구]<br>`hotspot_heap_pct_floor` = 70 — [도구] 최대값이 이 미만이면 무시<br>`hotspot_heap_pct_gap` = 30 — [도구] 노드 간 heap 편차(%p)<br>`node_compare_min_uptime_hours` = 24 — [도구] uptime 이 이보다 짧은 노드는 노드 간 비교에서 제외 |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |
| 참고 문서 | [Hot spotting 문제 해결](https://www.elastic.co/docs/troubleshoot/elasticsearch/hotspotting) |

**판정 로직**

같은 tier 안에서 heap / CPU% / 디스크% 가 일부 노드에 편중되는지(공식 hot spotting 탐지 지표).

tier 가 다르면 역할과 부하가 달라 비교하지 않는다. frozen tier 디스크는 shared cache 선점유라 제외.
heap 은 JVM 메모리 압력(old generation, JVM-001 과 같음)으로 비교한다. heap_used_percent 는 대개 노드가 young GC 주기의
어디쯤인지를 보여 줄 뿐이다. heap% 는 표에 그대로 둔다.
지표별로 tier 내 최대−최소 >= gap 이고 최대값 >= floor 일 때 주의. 수집 순간값이다.
uptime 이 node_compare_min_uptime_hours 미만인 노드는 heap·CPU 비교에서 뺀다(재시작 직후에는 캐시가 비어 있고
활성 샤드도 적어 한가해 보임). 디스크 사용량은 재시작해도 그대로라 디스크 비교에는 넣는다.
공식 문서는 지속되는 편중과 write·search 큐 적체를 신호로 본다. 수집 시점의 큐도 함께 보여 주며, 번들 하나로는
편중이 지속되는지 알 수 없다.

### HOT-002.(하위 항목) — 같은 tier 안에서 %s 작업량 편중

| 항목 | 내용 |
| --- | --- |
| 함수 | `hotspot.r_workload_hotspot` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의 |
| 임계값 | `node_compare_min_uptime_hours` = 24 — [도구] uptime 이 이보다 짧은 노드는 노드 간 비교에서 제외<br>`workload_skew_min_per_sec` = 10 — DIF-009 indexing 편중을 판정하는 tier 노드당 최소 평균 초당 처리량<br>`workload_skew_ratio_warn` = 1.8 — [도구] 최대 노드 / 평균 |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |
| 참고 문서 | [Hot spotting 문제 해결](https://www.elastic.co/docs/troubleshoot/elasticsearch/hotspotting) |

**판정 로직**

같은 tier 안에서 노드별 색인/검색 작업량 편중을 시간당 값(누적 횟수 / uptime)으로 비교한다.

최대 노드 / tier 평균 >= workload_skew_ratio_warn → 주의. uptime 이 node_compare_min_uptime_hours 미만인 노드는
뺀다(누적값이 짧은 구간만 담고 캐시도 비어 있음). 남은 노드가 2대 미만이거나, 합계 작업이 10000 건 미만이거나, 노드 평균이
workload_skew_min_per_sec 미만인 tier 는 건너뛴다. replica 작업이 포함된 값이다.

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

desired balance 미수렴. 원하는 위치에 있지 않은 샤드(cat allocation shards.undesired) >= undesired_shards_warn →
재배치·초기화 중인 샤드가 없으면(정체) 주의, rebalance 가 옮기는 중이면 참고(HOT-003). balance 계산이
아직 진행 중(내부 desired balance 통계 computation_active=true) → 참고(HOT-004).

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

indices.recovery.max_bytes_per_sec 의 기본값(40mb)은 그 자체로 문제가 아니며, 0 이하는 무제한이다.
복구·재배치가 실제로 진행 중일 때만 복구 시간의 병목 후보로 보고한다. 값이 기본값이고
메모리 기준 기본값이 40mb 보다 큰 전용 cold·frozen 노드가 있으면 관측 문구에 그렇게 적는다.

### TPL-001 — 레거시 템플릿이 composable 템플릿에 가려짐(추정)

| 항목 | 내용 |
| --- | --- |
| 함수 | `hotspot.r_template_conflict` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (templates.json) 그리고 (index_templates.json) |
| 근거 파일 | templates.json / index_templates.json |
| 참고 문서 | [Templates](https://www.elastic.co/docs/manage-data/data-store/templates) |

**판정 로직**

레거시(_template) 템플릿이 composable(_index_template) 템플릿에 가려지는지.

composable 템플릿이 하나라도 매칭되면 레거시 템플릿은 적용되지 않는다(공식 동작).
또한 composable 끼리 같은 우선순위로 겹치는 경우는 ES 가 생성을 거부하므로 여기서 보지 않는다.
패턴 겹침은 두 와일드카드 패턴이 공통 이름에 맞을 수 있는지로 판단한다.

### CLU-021 — node_left 지연 할당이 비활성화된 인덱스

| 항목 | 내용 |
| --- | --- |
| 함수 | `hotspot.r_delayed_allocation` |
| 근거 구분 | 공식 기준 |
| 가능 심각도 | 주의 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) |
| 근거 파일 | settings.json |
| 참고 문서 | [Delaying allocation when a node leaves](https://www.elastic.co/docs/deploy-manage/distributed-architecture/shard-allocation-relocation-recovery/delaying-allocation-when-node-leaves) |

**판정 로직**

노드 재기동 시 즉시 재복제를 막는 delayed_timeout 설정.

## 스토리지 비용

### COST-001 — 롤오버 후에도 hot tier 에 남은 인덱스

| 항목 | 내용 |
| --- | --- |
| 함수 | `cost.r_hot_rolled_over` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 참고 |
| 임계값 | `hot_rolled_days_info` = 30 — [도구] ILM hot phase 에 남은 인덱스의 롤오버 후 경과일<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (ilm_explain.json) 그리고 (indices_stats.json) 그리고 (indices.json 또는 shards.json 또는 cat_shards.txt) |
| 근거 파일 | commercial/ilm_explain.json / commercial/ilm_policies.json / indices_stats.json |
| 참고 문서 | [인덱스 수명 주기(phase)](https://www.elastic.co/docs/manage-data/lifecycle/index-lifecycle-management/index-lifecycle)<br>[데이터 tier](https://www.elastic.co/docs/manage-data/lifecycle/data-tiers) |

**판정 로직**

롤오버 후 한참 지났는데도 ILM hot phase 에 남아 있는 인덱스(COST-001).

데이터를 옮길 warm, cold, frozen tier 가 있을 때만 본다. ILM explain 의 phase 가 hot 이고, 롤오버를 마쳤고
write 대상이 아니며, 롤오버 이후 경과(lifecycle_date)가 hot_rolled_days_info 이상이고, 샤드가 하나라도 hot 노드에 있으면 대상이다.
ILM 정책별로 묶고 다음 phase 와 그 min_age 를 함께 보여 준다. min_age 는 롤오버 시점부터 센다.
참고로만 보고한다. 검색 속도나 짧은 보존 기간 때문에 일부러 hot 에 둘 수도 있다.

### COST-002 — 검색이 없는 인덱스의 추가 replica

| 항목 | 내용 |
| --- | --- |
| 함수 | `cost.r_idle_replicas` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 참고 |
| 임계값 | `cost_replicas_min` = 2 — [도구] 검색 없는 인덱스를 보고하는 replica 수<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (settings.json) 그리고 (indices_stats.json) |
| 근거 파일 | settings.json / indices_stats.json |
| 참고 문서 | [클러스터, 노드, 샤드](https://www.elastic.co/docs/deploy-manage/distributed-architecture/clusters-nodes-shards) |

**판정 로직**

replica 가 cost_replicas_min 개 이상인데 검색이 없는 인덱스(COST-002).

사용자 인덱스(system 인덱스, searchable snapshot 마운트, auto_expand_replicas 인덱스 제외) 중 number_of_replicas >= cost_replicas_min 이고, 문서가 있고,
indices_stats total.search.query_total 이 0 인 것. data 노드가 replica + 1 개 이상의 가용 영역에 걸쳐 있으면
영역마다 사본 하나씩 두는 의도된 구성이므로 넣지 않는다. 두 번째 이후 replica 는 노드 한 대 장애에 대한 가용성은 그대로인 채
디스크와 색인 작업만 늘린다. 검색 카운터는 샤드가 옮겨지거나 노드가 재시작하면 초기화되므로 0 은
'샤드가 시작된 뒤로 검색이 없음' 이라는 뜻이다. 참고로만 보고한다.

### COST-003 — data tier 간 디스크 사용률 차이가 큼

| 항목 | 내용 |
| --- | --- |
| 함수 | `cost.r_tier_usage` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 참고 |
| 임계값 | `tier_gap_pct` = 30 — [도구] hot 과 차가운 tier 의 디스크 사용률 차이(포인트)<br>`tier_hot_used_pct` = 70 — [도구] 차가운 tier 와 비교를 시작하는 hot tier 디스크 사용률<br>`tier_idle_used_pct` = 20 — [도구] 차가운 tier 사용률이 이보다 낮으면 대부분 비어 있는 것으로 봄 |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |
| 참고 문서 | [데이터 tier](https://www.elastic.co/docs/manage-data/lifecycle/data-tiers)<br>[인덱스 수명 주기(phase)](https://www.elastic.co/docs/manage-data/lifecycle/index-lifecycle-management/index-lifecycle) |

**판정 로직**

data tier 별 디스크 사용률(COST-003).

frozen 은 shared cache 가 디스크를 미리 잡으므로 보여 주기만 하고 비교하지 않는다. 조건:
(1) hot tier 가 tier_hot_used_pct 이상인데 warm 이나 cold tier 가 tier_gap_pct 포인트 이상 비어 있음. 보통
hot 디스크가 감당하는 것보다 늦게 데이터가 옮겨진다는 뜻이다. (2) warm 이나 cold tier 가 tier_idle_used_pct 미만. 담은
데이터보다 tier 가 크다는 신호다. frozen 이 아닌 tier 가 2개 이상일 때만 본다. 참고로만 보고한다.

### COST-004 — 수집 대상 tier 가 더 받을 수 있는 수집 일수

| 항목 | 내용 |
| --- | --- |
| 함수 | `cost.r_ingest_headroom` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `disk_projection_days_warn` = 30 — [도구]<br>`ingest_window_days` = 7 — [도구] 하루 수집량 추정에 쓰는 최근 인덱스 기간(일) |
| 필요 입력 | (settings.json) 그리고 (indices_stats.json) 그리고 (nodes_stats.json) |
| 근거 파일 | settings.json / indices_stats.json / nodes_stats.json |
| 참고 문서 | [데이터 tier](https://www.elastic.co/docs/manage-data/lifecycle/data-tiers) |

**판정 로직**

번들 하나로 수집 대상 tier 가 high watermark 까지 며칠치 수집량을 더 받을 수 있는지 계산한다(COST-004).

하루 수집량 = 최근 ingest_window_days 안에 만들어진 사용자 인덱스의 store 크기(replica 포함) + 그보다 오래된 write index 중
구간에 해당하는 부분(크기 × 구간 / 나이) + 구간 안에서 rollover 한 오래된 인덱스 중 구간 시작부터 rollover 까지
쓰인 부분(ilm_explain lifecycle_date)을 구간 일수로 나눈 값(클러스터가 더 젊으면
그 기간). system 인덱스는
뺀다. searchable snapshot 마운트는 마운트할 때 생성일이 새로
매겨지므로 데이터 기준으로 둔다: 백킹 인덱스 이름의 날짜부터 rollover 시점(ilm_explain lifecycle_date)까지 쓰였고,
크기는 snapshot 데이터 크기(total_data_set_size) × (1 + 데이터 스트림 write index 의 replica 수)이며,
그 기간 중 구간에 들어간 부분만 센다. failure store 인덱스는 해당 데이터 스트림으로 센다. 수집 대상 tier = write 대상 샤드가 있는 tier(frozen 제외). 그중 hot tier 가
있으면 hot tier 만 센다. 새 data stream 인덱스는 기본으로 hot 에 만들어지고, 다른 tier 에 있는 write 대상은 대개
rollover 없이 정책이 옮긴 작은 인덱스이기 때문이다.
여유 = 그 노드들의 (high watermark 에서 허용하는 바이트 − 사용 바이트) 합. 일수 = 여유 / 하루 수집량.
아무것도 옮기거나 지우지 않는다고 가정한다. 일수 <= disk_projection_days_warn 이면서 구간 데이터의 절반 넘게 아직 빠지지
않으면 → 주의, 아니면 참고. ILM 정책에 hot 다음 phase 가 있거나(rollover max_age 와 그 phase 의 min_age 의 합) data stream lifecycle 에
retention 이나 frozen_after 가 있고, 그 지연이 클러스터에서 가장 오래된 데이터의 나이보다 길지 않으면 빠지는 데이터다
(더 길면 아직 아무것도 빠지기 시작하지 않은 것, 예: 보존 기간이 긴 젊은 클러스터). shrink·downsample 사본은 마운트처럼 백킹 인덱스 이름의
날짜로 둔다(downsample 사본은 수집량보다 작으므로 하한값).
write 대상은 명시적인 것과 샤드 시작 이후 쓰기가 있었던 인덱스다. 비교 모드(DIF-008)는
실제 증가량을 잰다.

### COST-005 — 데이터 종류별 저장량

| 항목 | 내용 |
| --- | --- |
| 함수 | `cost.r_storage_by_type` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 참고 |
| 필요 입력 | (indices_stats.json) |
| 근거 파일 | indices_stats.json / commercial/data_stream.json / indices.json |
| 참고 문서 | [데이터 스트림 이름 규칙](https://www.elastic.co/docs/reference/fleet/data-streams)<br>[데이터 tier](https://www.elastic.co/docs/manage-data/lifecycle/data-tiers) |

**판정 로직**

데이터 종류와 tier 별 저장량(COST-005), 보고된 값 그대로.

인덱스마다 공식 데이터 스트림 이름 규칙(<type>-<dataset>-<namespace>: logs, metrics, traces,
synthetics), 보안 알림, system, 기타 데이터 스트림, 기타 인덱스 중 하나로 나눈다(failure store 인덱스는 해당
데이터 스트림으로). partial 마운트(frozen) 인덱스는 따로 보여 준다: 로컬 store 를 0 으로 보고하며, snapshot repository 에 있는
데이터 크기(total_data_set_size)는 본문에 따로 적는다. tier 는 primary 샤드가
있는 곳이다. 행마다 인덱스 수, 문서 수, primary 와 전체 store, 전체 store 대비 비중을 보여 준다. 참고로만 보고한다.

### COST-006 — tier 별 사이징 신호

| 항목 | 내용 |
| --- | --- |
| 함수 | `cost.r_tier_sizing` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 참고 |
| 임계값 | `heap_used_pct_crit` = 85 — [공식] 조치가 필요한 JVM memory pressure(high JVM memory pressure 가이드)<br>`size_idle_cpu_pct` = 20 — [도구] tier 의 모든 노드 CPU 가 이보다 낮으면 여유 큼 후보<br>`size_idle_disk_pct` = 30 — [도구] ... 그리고 디스크 사용률이 이보다 낮음(frozen 제외)<br>`size_idle_heap_pct` = 50 — [도구] ... 그리고 heap 사용률이 이보다 낮음<br>`size_idle_load_per_cpu` = 0.3 — [도구] ... 그리고 load15/CPU 가 이보다 낮음<br>`tier_cpu_pct_warn` = 75 — [도구] tier 전체 포화 판정 CPU% |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json |
| 참고 문서 | [데이터 tier](https://www.elastic.co/docs/manage-data/lifecycle/data-tiers) |

**판정 로직**

번들 하나로 본 data tier 별 사이징 신호(COST-006).

부족 신호: 모든 노드가 바쁨(load15/CPU >= load_per_cpu_warn 또는 CPU >= tier_cpu_pct_warn, 컨테이너 예외를 포함한 HOT-005 와 같은
기준), tier 노드의 write·
search 거부, indexing pressure 거부, high watermark 이상인 노드(frozen 제외), 또는
JVM memory pressure(JVM-001 과 같은 old generation 기준)가 heap_used_pct_crit 이상인 노드 중 하나라도 있음. 여유 큼: tier 의 모든 노드가
node_compare_min_uptime_hours 이상 떠 있었고 CPU < size_idle_cpu_pct, load15/CPU < size_idle_load_per_cpu, heap <
size_idle_heap_pct, 디스크 < size_idle_disk_pct(frozen 은 디스크 제외)이며 거부가 없음. 나머지는
"뚜렷한 신호 없음". 번들은 한 순간이므로 여유 큼은 "지금 줄여라" 가 아니라 "모니터링으로 확인해 볼 만함" 이다. 참고로만 보고한다.

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
확인을 안내한다. 레거시 내부 수집(cluster settings 또는 elasticsearch.yml 의 xpack.monitoring.collection.enabled=true)도 함께 표기하고
7.16 부터 deprecated 라는 점을 덧붙인다. 9.5 부터는 10.0 에서
제거된다는 점도 덧붙인다(공식 deprecations).

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

license.status != active → 치명. trial 라이선스(최대 30일)는 기간 중 주의. 만료까지 <= license_expiry_days_crit 일 → 치명, <= warn 일 → 주의, 그 외 정상. 기준 시각은 번들 수집 시각.

### SNP-001, SNP-002, SNP-007, SNP-003, SNP-004, SNP-006, SNP-005 — 스냅샷 저장소 미설정

| 항목 | 내용 |
| --- | --- |
| 함수 | `ops.r_snapshots` |
| 판정 항목 | SNP-001 스냅샷 저장소 미설정 / SNP-002 실패/부분 스냅샷 존재 / SNP-007 현재 실패 중인 SLM 정책 / SNP-003 성공한 스냅샷 없음 / SNP-004 진행 중인 스냅샷 / SNP-006 SLM 중지 상태 / SNP-005 SLM 스냅샷 실패 누적 |
| 근거 구분 | 도구 판단 / 사실 보고 |
| 가능 심각도 | 치명, 주의, 참고, 정상 |
| 임계값 | `snapshot_age_hours_crit` = 168 — [도구] 7일<br>`snapshot_age_hours_warn` = 36 — [도구] 최근 스냅샷 경과 시간<br>`snapshot_failed_warn` = 1 — [도구]<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (repositories.json 또는 snapshot.json) |
| 근거 파일 | commercial/slm_policies.json / commercial/slm_stats.json / commercial/slm_status.json / repositories.json / snapshot.json |

**판정 로직**

저장소도 스냅샷도 없음 → 치명(SNP-001. repositories.json 이 없거나 오류 응답이면 건너뜀). FAILED/PARTIAL 스냅샷 존재 → 주의, 그보다 늦은 성공 스냅샷이 없음이 확인되면 치명(SNP-002. 시각 없이 나열된 스냅샷은 주의로 둔다). 마지막 '성공(SUCCESS)' 스냅샷 경과(snapshot.json 에 시각이 없으면 SLM 정책의 last_success 시각) >= snapshot_age_hours_crit → 치명, >= warn → 주의, 그 외 정상(SNP-003, 진행 중·실패·부분 스냅샷은 RPO 산정에서 제외). SUCCESS 상태 스냅샷도 SLM 성공도 없음(스냅샷 상태로 판단. 저장소는 있는데 스냅샷이 없는 경우 포함) → 치명. 시각 없이 나열된 SUCCESS 스냅샷은 경과 시간을 알 수 없다. IN_PROGRESS 존재 → 참고(SNP-004). SLM 누적 실패 >= snapshot_failed_warn → 참고(SNP-005, 전체 기간 누적값). SLM 정책이 있는데 operation_mode != RUNNING → 주의(SNP-006). SLM 정책의 마지막 실패가 마지막 성공보다 최근이면 주의, 연속 5회 실패(invocations_since_last_success, SLM health 기준)이거나 마지막 성공이 snapshot_age_hours_crit 보다 오래되면 치명(SNP-007).

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

ILM operation_mode != RUNNING → 주의(ILM-001). ilm_explain 의 step=ERROR 또는 failed_step 존재 → 롤오버 관련 단계 실패가 있으면 치명, 그 외(삭제·축소·이동 단계, write index 삭제 실패 등)는 주의(ILM-002). ILM 미적용(managed=false) 사용자 인덱스 중 primary > 10GB → 참고(ILM-003). data stream lifecycle 이 관리하는 인덱스는 미적용으로 세지 않는다. 더 이상 쓰지 않는(롤오버된) 인덱스의 롤오버 단계 오류는 치명이 아니라 주의다.

### ML-001, ML-002 — Transform 실패 상태

| 항목 | 내용 |
| --- | --- |
| 함수 | `ops.r_ml_transform` |
| 판정 항목 | ML-001 Transform 실패 상태 / ML-002 ML 이상탐지 job 실패 |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 주의 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (transform_stats.json 또는 ml_stats.json 또는 ml_anomaly_detectors.json) |
| 근거 파일 | commercial/ml_stats.json / commercial/transform_stats.json |

**판정 로직**

transform state 가 failed/aborting → 주의(ML-001). 이상탐지 job state=failed → 주의(ML-002). job state 는
job 통계(commercial/ml_stats.json, GET _ml/anomaly_detectors/_stats)에 있으며 job 설정 파일에는 state 가 없다.

### SEC-001 — TLS 인증서 만료 여유

| 항목 | 내용 |
| --- | --- |
| 함수 | `ops.r_certificates` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 치명, 주의, 정상 |
| 임계값 | `cert_expiry_days_crit` = 30 — [도구]<br>`cert_expiry_days_warn` = 90 — [도구] |
| 필요 입력 | (ssl_certs.json) |
| 근거 파일 | ssl_certs.json |

**판정 로직**

ssl_certs.json 의 인증서 만료까지 <= cert_expiry_days_crit 일(이미 만료 포함) → 치명, <= warn 일 → 주의, 그 외 정상.
치명 구간의 인증서가 모두 trust store 의 CA(has_private_key=false)면 그 CA 가 서명한 체인에만 영향이 있으므로 주의.
ECH/ECE/ECK 에서는 플랫폼이 인증서를 관리하므로 안내에 그렇게 적는다. 기준 시각은 번들 수집 시각.

### SEC-002 — 보안 기능 활성화

| 항목 | 내용 |
| --- | --- |
| 함수 | `ops.r_security_enabled` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 치명, 주의, 정상 |
| 필요 입력 | (xpack.json) |
| 근거 파일 | commercial/xpack.json |

**판정 로직**

xpack security.enabled=false → 치명. 모든 노드가 HTTP 와 transport 를 loopback 에만 바인딩하면 주의(nodes info 필요.
없으면 주소를 알 수 없으므로 치명 유지). 그 외 정상.

### OPS-001 — GeoIP 데이터베이스 갱신 이슈

| 항목 | 내용 |
| --- | --- |
| 함수 | `ops.r_geoip` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 참고 |
| 필요 입력 | (geoip_stats.json) |
| 근거 파일 | geoip_stats.json |

**판정 로직**

GeoIP expired_databases > 0, 또는 데이터베이스를 하나도 받지 못한 채 failed_downloads > 0 → 참고(폐쇄망에서는 정상일 수 있음).

failed_downloads 는 누적값이다. 데이터베이스가 있고 만료된 것이 없으며 성공한 다운로드가 있으면 과거 실패는
재시도로 해결된 것이므로 보고하지 않는다. 만료된 데이터베이스(30일 동안 갱신 안 됨)는 geoip
processor 가 더 이상 쓰지 않으므로 그 조회는 위치 필드를 추가하지 않는다.

### OPS-002 — CCR 복제 오류

| 항목 | 내용 |
| --- | --- |
| 함수 | `ops.r_ccr` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 주의, 참고 |
| 필요 입력 | (ccr_stats.json) |
| 근거 파일 | commercial/ccr_stats.json |

**판정 로직**

CCR follower 샤드에 read_exceptions(현재 오류) 또는 fatal_exception 이 있으면 주의(OPS-002). failed_read/write_requests 는
follower task 별 누적값이므로, 이 카운터만 있는 샤드는 참고로 표시한다(과거 remote 재시작도 남김).

## 매핑 · ILM 정책 · 클러스터 조정 · 세부 통계

### PERF-011 — 비용이 큰 검색 패턴 비중 높음

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_search_usage` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `search_expensive_share_warn` = 10 — [도구] 비용이 큰 쿼리 유형의 검색 대비 비중(%) |
| 필요 입력 | (cluster_stats.json) |
| 근거 파일 | cluster_stats.json (indices.search) |

**판정 로직**

cluster_stats.indices.search 의 쿼리 유형·검색 구성 요소별 사용 횟수(누적)로 비용이 큰 검색 패턴의 비중을 본다.

비용이 큰 유형(EXPENSIVE: nested·parent-child 조인·script·wildcard·regexp·fuzzy·prefix·query_string·
runtime_mappings·script_fields)의 사용 비중이 search_expensive_share_warn(%) 이상이면 주의(PERF-011), 사용은 있으나
비중이 낮으면 참고. runtime_mappings 는 runtime field 를 정의한 요청을 사용 여부와 관계없이 세므로 표시만 하고 주의로 올리지 않는다. 쿼리 본문이 아니라 유형별 횟수이므로 '어떤 인덱스의 어떤 쿼리' 인지는 알 수 없다.

### DISK-008 — 디스크 I/O 사용률 높음

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_disk_io_utilization` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `disk_io_busy_pct_warn` = 60 — [도구] 기동 이후 평균 디스크 사용률 |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json (fs.io_stats) |

**판정 로직**

데이터 노드의 평균 디스크 사용률 = fs.io_stats.total.io_time_in_millis / JVM uptime (Linux 에서만 수집).

io_time 은 ES 기동 이후 장치가 I/O 를 처리한 누적 시간이다. >= disk_io_busy_pct_warn → 주의(DISK-008), 그 외 참고.
여러 장치를 쓰면 합계라 100% 를 넘을 수 있어 장치 수로 나눈 값을 쓴다. 누적 평균이므로 순간 포화는 가려질 수 있다.
Linux 는 장치의 io_ticks 를 부호 없는 32-bit 밀리초 카운터로 출력하므로(/proc/diskstats) 약 49.7일마다 한 바퀴 돌고,
노드 시작 시점 값을 빼는 ES 는 그때 음수 증가분을 보고한다. uptime 이 한 바퀴(2^32 ms)보다 짧으면
음수 장치 증가분에 2^32 를 더한 값이 실제 값이다. 그래도 0% 미만이나 100% 초과면 JVM uptime 과 맞지 않으므로
"확인 불가"로 표시하고 판정하지 않는다. uptime 이 한 바퀴 이상이면 양수 증가분도 그 값에 2^32 를 더한 것일 수 있어
역시 "확인 불가"다. 평균은 값이 있는 장치 수로 나눈다.
Elastic Cloud / ECE / ECK 에서는 같은 호스트의 다른 컨테이너가 장치를 함께 쓸 수 있어 이 값은 이 노드만이 아니라
장치 전체의 값이며, 본문에 그렇게 적는다.

### MAP-004, MAP-005, MAP-006 — 필드 수가 매핑 한도에 근접한 인덱스

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_mapping_limits_actual` |
| 판정 항목 | MAP-004 필드 수가 매핑 한도에 근접한 인덱스 / MAP-005 text 필드에 fielddata 활성화 / MAP-006 nested 필드 수가 한도에 근접 |
| 근거 구분 | 공식 기준 / 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `mapping_fields_near_limit_pct` = 90 — [도구] total_fields.limit 대비 필드 수<br>`nested_fields_near_limit_pct` = 80 — [도구] nested_fields.limit 대비 nested 필드 수<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (mapping.json) |
| 근거 파일 | mapping.json / mapping.json / settings.json |
| 참고 문서 | [Mapping limit settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/mapping-limit)<br>[fielddata mapping parameter](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/text#fielddata-mapping-param) |

**판정 로직**

mapping.json 의 실제 매핑으로 인덱스별 필드 수를 공식 산정 방식(필드·object·multi-field·runtime 각 1개)으로 센다.

필드 수 >= total_fields.limit × mapping_fields_near_limit_pct → 주의(MAP-004, 표시된 인덱스가 모두 ignore_dynamic_beyond_limit=true
(명시 또는 기본값: 최근 인덱스 버전의 logsdb 인덱스는 true)면 참고).
ignore_dynamic_beyond_limit 가 없는 인덱스는 색인이 실패할 수 있으므로 표의 앞에 둔다. data stream template 을 누가 관리하는지
(Fleet package 또는 Elastic)도 함께 보여 준다. integration template 은 대개 ignore 옵션을 켜 두기 때문이다.
searchable snapshot mount 와 롤오버된 인덱스는 새 필드가 들어오지 않으므로 MAP-004 에서 제외한다(MAP-005 와 MAP-006 은
mount 도 본다: 정렬·집계하면 fielddata 를 올리기 때문). runtime 필드는
8.5 부터 한도에 포함된다(소스의 MappingLookup).
text 필드의 fielddata=true → 주의(MAP-005). nested 필드 수 >= nested_fields.limit × nested_fields_near_limit_pct → 주의(MAP-006). 기본 한도는 9.3 이후 만든 인덱스는 100, 그 전은 50.

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

8.14 미만에 만든 인덱스(index version 8_505_0_00 미만)에서는 index_options 미지정도 비양자화이므로 포함한다.
index: false 인 필드는 HNSW 그래프가 없어 건너뛰며, dense_vector 가 기본으로 색인되지 않던 8.11 미만에 만든 인덱스
(index version 8_500_0_00 미만)에서 index 파라미터가 없는 필드도 건너뛴다. 8.12 미만에는 양자화 타입이 없어 판정하지 않는다.
템플릿 기준 판정(VEC-002)을 실제 인덱스로 보완한다.

### ILM-004, ILM-005, ILM-007, ILM-006 — 크기 기준 없이 롤오버하는 ILM 정책

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_ilm_policies` |
| 판정 항목 | ILM-004 크기 기준 없이 롤오버하는 ILM 정책 / ILM-005 롤오버 샤드 크기 기준이 권장 상한 초과 / ILM-007 효과 없는 max_primary_shard_docs 설정 / ILM-006 삭제 단계가 없는 ILM 정책 |
| 근거 구분 | 공식 기준 / 사실 보고 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `ilm_implicit_max_shard_docs` = 200,000,000 — [공식] 샤드당 2억건이면 rollover 가 항상 실행됨. 더 큰 값은 효과 없음<br>`ilm_rollover_max_shard_gb` = 50 — [공식] 롤오버 샤드 크기 권장 상한<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (ilm_policies.json) |
| 근거 파일 | commercial/ilm_policies.json |
| 참고 문서 | [Rollover (ILM)](https://www.elastic.co/docs/reference/elasticsearch/index-lifecycle-actions/ilm-rollover)<br>[Size your shards](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) |

**판정 로직**

사용자 인덱스가 쓰는 ILM 정책의 롤오버·삭제 구성.

hot 롤오버에 max_primary_shard_size(또는 max_size)가 없으면 주의(ILM-004): 공식 권장은 샤드 크기 기준 롤오버이며,
max_age 단독이면 수집량에 따라 작은 인덱스가 쌓인다(OVS-002 의 원인). 데이터 스트림이 쓰는 정책에 rollover 자체가
없으면 ILM-004 에 함께 표시한다: 그 데이터 스트림은 rollover 하지 않아 write index 가 끝없이 커지고
이전 backing index 가 있으면 delete 단계가 실패한다(유일한 backing index 면 스트림 전체를 삭제). data stream lifecycle 이 관리하는
데이터 스트림은 여기서 정책 사용자로 세지 않는다. max_primary_shard_size > 50GB 면 주의(ILM-005).
delete 단계가 없으면 참고(ILM-006, 보존 기간 무제한). Elastic 관리 정책(_meta.managed=true)도 똑같이 확인하고 표에 "(Elastic 관리)" 로 표시한다.
max_primary_shard_docs 가 200,000,000 을 넘으면 참고(ILM-007): 8.8 부터 rollover 는 샤드당 2억건에서 항상 실행되므로 더 큰
값은 효과가 없다(공식). 8.8 미만에는 이런 암묵 조건이 없으므로 ILM-007 을 내지 않는다.

### ILM-008, ILM-009 — force merge 여유 디스크 부족

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_forcemerge` |
| 판정 항목 | ILM-008 force merge 여유 디스크 부족 / ILM-009 오래 걸리는 force merge |
| 근거 구분 | 공식 기준 / 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `forcemerge_free_space_factor` = 3 — [공식] max_num_segments=1 은 shard 크기의 최대 3배 여유 공간이 필요할 수 있음<br>`forcemerge_stuck_hours` = 24 — [도구] force merge 단계에 이 시간 이상 머물면 보고<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (ilm_policies.json 또는 ilm_explain.json) 그리고 (nodes_stats.json) |
| 근거 파일 | commercial/ilm_explain.json / nodes_stats.json / commercial/ilm_policies.json / nodes_stats.json / indices.json |
| 참고 문서 | [Force merge API](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-indices-forcemerge)<br>[Force merge (ILM)](https://www.elastic.co/docs/reference/elasticsearch/index-lifecycle-actions/ilm-forcemerge) |

**판정 로직**

ILM 의 1 segment force merge: 여유 디스크와 진행 상황.

공식: max_num_segments=1 force merge 는 shard 크기의 최대 3배 여유 공간이 필요할 수 있고, force_merge thread pool 은
현재 버전에서 노드당 max(1, allocated processors / 8), 이전 버전은 1 이다(보고된 크기를 쓴다). 1 segment merge 는 forcemerge max_num_segments=1
(그 단계에서 실행)과 force_merge_index 가 켜진 searchable_snapshot(기본 true, 앞 단계의 tier 에서 실행,
이미 1 segment 로 merge 했다면 생략)이다. 이런 merge 가 있는 사용 중 정책에서, 실행 tier
(hot/warm/cold, 해당 tier 가 없으면 frozen 을 뺀 전체 data 노드) 노드의 여유 디스크가
정책을 실행하는 인덱스(지금 다른 정책을 쓰는 backing index 는 제외)의 가장 큰 primary shard x forcemerge_free_space_factor 보다 작으면
주의(ILM-008).
수집 시점에 forcemerge action(또는 searchable_snapshot 의 forcemerge step)에
forcemerge_stuck_hours 이상 머문 ilm_explain 항목 → 참고(ILM-009),
data 노드의 force_merge pool 크기와 대기 건수를 함께 표시한다. partial mount 인덱스는 크기가 캐시 크기라 제외한다.

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
| 근거 파일 | commercial/nodes_shutdown_status.json |
| 참고 문서 | [Node shutdown API](https://www.elastic.co/docs/api/doc/elasticsearch/group/endpoint-shutdown) |

**판정 로직**

nodes_shutdown_status 의 종료 레코드. STALLED → 치명, IN_PROGRESS → 참고, COMPLETE 인데 노드가 클러스터에 있음 → 주의(SHUT-001).

종료 레코드는 삭제하기 전까지 남는다. 작업 후 남으면 해당 노드로의 샤드 할당이 계속 제한될 수 있다.
REMOVE, REPLACE, SIGTERM 레코드가 그렇다. RESTART 레코드는 할당을 제한하지 않고(노드가 떠난 뒤 재할당만 늦춤)
바로 COMPLETE 로 보이므로, 완료된 RESTART 레코드는 참고로 둔다.

### IDX-012 — 샤드 저장소 예외(손상 의심)

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_shard_store_errors` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 치명, 주의 |
| 임계값 | `top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 필요 입력 | (shard_stores.json) |
| 근거 파일 | shard_stores.json |

**판정 로직**

shard_stores 에 store_exception 이 있는 샤드 사본(IDX-012). 손상 징후(CorruptIndexException, checksum, corrupt) →
치명. close 중 잡힌 shard lock, 없는 shard 경로 같은 그 외 store exception 은 일시적인 경우가 많아 → 주의.

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

### FRZ-001 — frozen shared cache 교체 과다

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_frozen_cache` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `frozen_cache_turnover_per_day` = 1.0 — 과도한 교체로 보는 frozen shared cache 일 평균 eviction(캐시 region 수의 배수, FRZ-001) |
| 필요 입력 | (searchable_snapshots_cache_stats.json) |
| 근거 파일 | commercial/searchable_snapshots_cache_stats.json |

**판정 로직**

frozen shared cache 통계(FRZ-001). eviction 은 노드 시작 이후 누적이며, partial 마운트 인덱스가 삭제되거나 옮겨질 때(ILM delete)
해제되는 region 도 세므로, 노드 uptime 기준 일 평균으로 바꿔 본다.
일 평균 eviction 이 frozen_cache_turnover_per_day x region 수를 넘으면(캐시 전체가 그만큼 자주 교체됨) → 주의.
검색 대상 대비 캐시가 작다는 신호다(도구 판단). 그 외 데이터가 있으면 참고.

### FRZ-002 — frozen shared cache 가 네트워크 파일시스템에 있음

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_frozen_network_storage` |
| 근거 구분 | 도구 판단 |
| 가능 심각도 | 치명, 주의 |
| 필요 입력 | (nodes_stats.json) |
| 근거 파일 | nodes_stats.json / commercial/searchable_snapshots_cache_stats.json / nodes_hot_threads.txt |
| 참고 문서 | [Searchable snapshots](https://www.elastic.co/docs/deploy-manage/tools/snapshot-and-restore/searchable-snapshots) |

**판정 로직**

frozen shared cache 가 있는 노드의 data path 가 네트워크 파일시스템인지 본다(FRZ-002).

캐시 통계에 shared cache 가 있거나, 전용 frozen 노드(기본으로 shared cache 를 가짐)이거나,
xpack.searchable.snapshot.shared_cache.size 가 설정되어 있으면 shared cache 가 있는 노드로 본다. shared cache 가 있는 노드는
data path 를 하나만 가질 수 있으므로 캐시 파일은 그 경로의 파일시스템에 있다. nodes_stats fs.data[].type 이 nfs / cifs / smb / fuse / glusterfs / ceph / lustre /
gpfs / beegfs / 9p 이면(fuseblk 같은 로컬 FUSE 는 제외) 주의.
검색은 캐시 파일을 읽고, 캐시 미스는 검색 중에 같은 파일에 쓴다. 한 번 쓰면 바뀌지 않는 다른 tier 의 세그먼트 파일과
다르다(모든 노드의 data path 는 PERF-009 가 본다).
노드별 보조 신호: searchable snapshot 캐시 코드 안에서 파일을 읽는 hot thread 수, search thread pool 의
queue 와 rejected. 서버 로그에 "Direct buffer memory" 오류가 있으면 → 치명.

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

hot threads(RT-001)에서 ingest 가 CPU 를 쓰는 것으로 보일 때 어떤 파이프라인·processor 가 원인인지 확인하는 근거다. 이전
버전은 조건(if)이 있는 processor 를 type conditional 로 보고하므로 key 에서 type 을 얻는다. 비동기
processor(enrich, inference)의 시간에는 조회나 ML 노드를 기다리는 시간이 포함된다.

### CLU-024 — 클러스터 상태 발행 실패

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

노드별 설치 플러그인(이름·버전)이 모두 같지 않으면 주의(CLU-023). 플러그인 정보가 없는 노드는 뺀다.

### ML-003 — ML 모델 배포 이상

| 항목 | 내용 |
| --- | --- |
| 함수 | `deep.r_ml_deployments` |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 주의 |
| 필요 입력 | (ml_trained_models_stats.json) |
| 근거 파일 | commercial/ml_trained_models_stats.json |

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
| 근거 파일 | commercial/autoscaling_capacity.json / commercial/rollup_jobs.json / commercial/watcher_stack.json |

**판정 로직**

watcher 가 수동 중지되었는데 watch 가 있으면 주의, 아니면 참고(OPS-005. watcher 를 중지하면 통계의 watch
수가 비워지므로 그때는 .watches 인덱스의 문서 수를 쓴다). 오토스케일링 요구 storage 또는 memory 가 현재보다 크면 참고(OPS-004).
rollup job 이 있으면 참고(OPS-006, rollup 은 8.11 부터 deprecated 되어 downsampling 으로 대체. 8.11 이전에는 그렇게 될 것이라고 적는다).

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
원인 분류는 각 스레드 스택에 시그니처를 대조한다: 맥락 시그니처(grok, painless, regexp, global ordinals 등)를 스택 전체에서 먼저 찾고, 그다음 일반 시그니처(ingest, 집계, 검색, merge 등)를 위쪽(실행 중) 프레임부터 대조해 처음 맞는 것으로 정한다.
CPU 0.5% 미만 스레드는 그보다 바쁜 스레드가 있으면 원인 집계에서 뺀다.

### LOG-001, LOG-000 — 서버 로그 오류 패턴 검출

| 항목 | 내용 |
| --- | --- |
| 함수 | `runtime.r_logs` |
| 판정 항목 | LOG-001 서버 로그 오류 패턴 검출 / LOG-000 서버 로그 미포함 진단 번들 |
| 근거 구분 | 사실 보고 |
| 가능 심각도 | 참고, 정상 |
| 임계값 | `log_scan_bytes` = 8MiB — [도구] 로그 파일당 스캔 크기(끝부분)<br>`top_n` = 15 — [도구] 근거 표 최대 행 수 |
| 근거 파일 | diagnostics.log / logs/ / manifest.json |

**판정 로직**

logs/ 디렉터리가 없으면 참고(LOG-000). local/remote 로 수집했는데 로그가 없으면 diagnostics.log 의 대상 노드 매칭 실패 기록을 근거로 수집 실패 원인을 알린다. 있으면 파일당 마지막 log_scan_bytes 만 최대 40개 파일 스캔해 고정 패턴(OOM, 긴 old GC, 마스터 미탐색, CircuitBreaking, rejected execution, 워터마크 초과, 노드 연결 끊김, 매핑 파싱 오류 등) 검출. 검출 패턴 중 가장 높은 심각도로 판정(LOG-001), 없으면 정상.

## OS 설정 (local/remote 모드 syscalls/)

### SYS-001, SYS-002, SYS-003, SYS-004 — mmap 사용 안 함(node.store.allow_mmap: false)

| 항목 | 내용 |
| --- | --- |
| 함수 | `syscalls.r_os_config` |
| 판정 항목 | SYS-001 mmap 사용 안 함(node.store.allow_mmap: false) / SYS-002 swap 이 있는데 vm.swappiness 가 높음 / SYS-003 Elasticsearch 프로세스 한도가 최소 요건 미달 / SYS-004 dmesg 를 읽지 못함 |
| 근거 구분 | 공식 기준 / 사실 보고 |
| 가능 심각도 | 치명, 주의, 참고, 정상 |
| 필요 입력 | (syscalls/sysctl.txt 또는 syscalls/proc-limit.txt 또는 syscalls/dmesg.txt) |
| 근거 파일 | syscalls/dmesg.txt / syscalls/proc-limit.txt / syscalls/sysctl.txt / syscalls/sysctl.txt / nodes.json |
| 참고 문서 | [vm.max_map_count 설정](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/vm-max-map-count)<br>[Bootstrap checks](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/bootstrap-checks)<br>[Swap 비활성화](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/setup-configuration-memory)<br>[File descriptors 설정](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/file-descriptors)<br>[스레드 수 한도 설정](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/max-number-of-threads) |

**판정 로직**

진단을 실행한 host 의 OS 설정(SYS-001~004).

syscalls/sysctl.txt 의 vm.max_map_count 가 262144(bootstrap check 최소값) 미만 → 치명, 1048576(8.16 부터 문서의 공식 권고값. 이전은 262144) 미만 → 참고, 이상 → 정상(SYS-001). sysctl 의 vm.swappiness 가 1 초과이고 swap_total > 0 이며 mlockall 이 true 가 아님 → 참고(SYS-002). syscalls/proc-limit.txt 의 Max open files 가 65535 미만 또는 Max processes 가 4096 미만(soft 기준) → 치명(SYS-003), 충족 → 정상. syscalls/dmesg.txt 의 OOM killer 기록이 elasticsearch 를 가리키면(서비스의 memcg 나 프로세스 이름) → 치명,
그 외 프로세스(단순 java 는 다른 JVM 일 수 있음) → 주의
(SYS-004), 기록 없음 → 정상. dmesg 출력에 커널 로그 줄이 없으면(root 없이 실행해 'read kernel buffer failed' 같은 오류만 있음) 정상이 아니라 참고.
모든 노드가 개발 모드(transport 가 loopback 이거나 single-node discovery)이면 bootstrap check 가 적용되지 않으므로 SYS-001 과 SYS-003 의 치명은 주의로 낮춘다.
모든 노드가 node.store.allow_mmap: false 이면 ES 가 max map count 검사를 건너뛰므로 SYS-001 은 참고로만 표시한다.

## 변화 추세 (--baseline 비교 모드)

### DIF-013 — 서로 다른 클러스터의 번들을 비교함

| 항목 | 내용 |
| --- | --- |
| 함수 | `diff.r_cluster_identity` |
| 근거 구분 | 비교 계산 |
| 가능 심각도 | 주의 |
| 근거 파일 | version.json / nodes.json |

**판정 로직**

두 번들이 서로 다른 클러스터에서 수집됨(DIF-013, 주의): cluster_uuid 가 다르거나, uuid 가 없을 때는
클러스터 이름이 다르고 노드 이름이 절반 미만으로 겹침. 이때 증감은 한 클러스터의 추세가 아니다.

### DIF-001 — 클러스터 상태 %s

| 항목 | 내용 |
| --- | --- |
| 함수 | `diff.r_status_change` |
| 근거 구분 | 비교 계산 |
| 가능 심각도 | 치명, 주의, 참고 |
| 근거 파일 | cluster_health.json (두 번들 비교) |

**판정 로직**

두 번들의 클러스터 상태가 다를 때(DIF-001). 나빠짐 → CLU-001 이 현재 상태에 주는 등급(red 치명, yellow 주의).
좋아짐 → 참고이며, 아직 green 이 아니면 다른 문구를 쓴다.

### DIF-002, DIF-003 — 노드 재기동 발생

| 항목 | 내용 |
| --- | --- |
| 함수 | `diff.r_node_restart` |
| 판정 항목 | DIF-002 노드 재기동 발생 / DIF-003 노드 구성 변경 |
| 근거 구분 | 비교 계산 |
| 가능 심각도 | 주의, 참고 |
| 근거 파일 | nodes.json (두 번들 비교) / nodes_stats.json (두 번들 비교) |

**판정 로직**

같은 이름의 노드가 재시작: uptime 이 줄었거나 간격보다 적게 늘었으면 → 주의, 두 번들 사이에 버전이 바뀌었으면(rolling upgrade) 참고(DIF-002, OS-006 의 최근 재시작과 같은 등급). 노드 이탈 → 주의, 신규만 → 참고(DIF-003).

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
구간 중 재시작(uptime 감소)했거나 새로 들어온(구간 안에 시작한) 노드는 0 부터 센다: 현재 값 전체가
uptime 동안의 증가분이다.

### DIF-006 — Old GC 발생 추이

| 항목 | 내용 |
| --- | --- |
| 함수 | `diff.r_gc_delta` |
| 근거 구분 | 비교 계산 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `old_gc_per_hour_warn` = 6 — [도구] 시간당 old GC 횟수<br>`old_gc_time_ratio_warn` = 0.02 — [도구] old GC 누적 시간 / uptime |
| 근거 파일 | nodes_stats.json (두 번들 비교) |

**판정 로직**

old GC 증가분. 시간당 증가 >= old_gc_per_hour_warn 또는 구간 GC 시간 비중 >= old_gc_time_ratio_warn → 주의, 그 외 참고.
재시작한 노드(uptime 감소)는 uptime 동안 0 부터 센다.

### DIF-007 — Circuit breaker 발동 진행 중

| 항목 | 내용 |
| --- | --- |
| 함수 | `diff.r_breaker_delta` |
| 근거 구분 | 비교 계산 |
| 가능 심각도 | 치명, 주의 |
| 임계값 | `breaker_delta_crit` = 10 — [도구] 두 번들 사이 breaker trip 증가분이 이 값 이상이면 DIF-007 치명 |
| 근거 파일 | nodes_stats.json (두 번들 비교) |

**판정 로직**

breaker tripped 증가분 > 0 → 주의, >= breaker_delta_crit → 치명(DIF-007). 구간 중 재시작(uptime 감소)했거나 새로 들어온(구간 안에 시작한) 노드는
0 부터 센다.

### DIF-008 — 디스크 증가율 기반 포화 예상

| 항목 | 내용 |
| --- | --- |
| 함수 | `diff.r_disk_projection` |
| 근거 구분 | 비교 계산 |
| 가능 심각도 | 치명, 주의, 참고 |
| 임계값 | `diff_min_hours_for_projection` = 1.0 — [도구] 이보다 짧은 간격은 외삽 안 함<br>`disk_projection_days_warn` = 30 — [도구] |
| 근거 파일 | nodes_stats.json (두 번들 비교) |

**판정 로직**

두 번들 사이 디스크 증가 속도로 데이터 티어별 high watermark 도달 시점을 추정한다(DIF-008).

같은 티어 안에서는 ILM 이동과 리밸런싱이 여유 있는 노드로 샤드를 옮기므로, 몇 시간 사이에 한 노드는 빠르게 늘고 다른 노드는
줄 수 있다. 실제로 차는 것은 티어 전체이므로 일수 = 티어 노드들의 high watermark 까지 남은 바이트 합 / 시간당 증가량 합.
노드별 값도 그대로 보여 준다. 티어 일수 <= 7 → 심각, <= disk_projection_days_warn
→ 주의, 그 외 참고. frozen 전용 노드는 shared cache 를 미리 잡아 두므로 제외한다. 증가량은 사용 바이트의 변화이므로
디스크 크기를 바꾼 것은 증가로 세지 않는다. 두 번들 사이에 노드 구성이 바뀐 티어는 표시만 하고
판정하지 않는다: 샤드가 노드 사이에서 옮겨졌으므로 그 증가는 수집량이 아니다.

### DIF-009 — 구간 처리량과 노드 간 분포

| 항목 | 내용 |
| --- | --- |
| 함수 | `diff.r_throughput` |
| 근거 구분 | 비교 계산 |
| 가능 심각도 | 주의, 참고 |
| 임계값 | `workload_skew_min_per_sec` = 10 — DIF-009 indexing 편중을 판정하는 tier 노드당 최소 평균 초당 처리량<br>`workload_skew_ratio_warn` = 1.8 — [도구] 최대 노드 / 평균 |
| 근거 파일 | nodes_stats.json (두 번들 비교) |

**판정 로직**

구간 동안 노드별 index_total / query_total 증가량을 초당 처리량으로 환산한다(replica 작업 포함).

data 노드만 센다. 편중은 tier 안에서 비교한다: 가장 바쁜 노드 / tier 평균 >= workload_skew_ratio_warn → 주의,
아니면 참고. tier 평균이 초당 workload_skew_min_per_sec 건 미만이면 판정하기에 너무 한산하다. 구간 중 재시작한 노드(uptime 감소)는 카운터가 초기화되었으므로 표에는 보이되
합계와 편중 계산에서는 뺀다.

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

인덱스 primary store 증가량 > index_growth_min_bytes → 참고(DIF-010). 사용자 인덱스 추가·삭제 → 참고(DIF-011).
restored-<name> 이나 partial-<name> 으로 다시 나타난 인덱스는 ILM 이 searchable snapshot 으로 마운트한 것이므로
새 인덱스 하나와 삭제 하나가 아니라 이동으로 표시한다.

### DIF-014 — 구간별 처리량(peak/off-peak)

| 항목 | 내용 |
| --- | --- |
| 함수 | `diff.r_interval_rates` |
| 근거 구분 | 비교 계산 |
| 가능 심각도 | 참고 |
| 근거 파일 | nodes_stats.json(연속된 번들) |

**판정 로직**

번들이 3개 이상일 때 구간별 처리량(DIF-014): peak 와 off-peak.

번들을 수집 시각 순으로 정렬하고 이어진 두 번들을 한 구간으로 본다. 구간마다 data 노드의 index_total 과
query_total 증가량을 초당 작업 수로 바꾼다(replica 작업 포함). 구간 중 uptime 이 줄어든 노드는
재시작했으므로 그 구간에서 뺀다. 서로 다른 클러스터 사이의 구간(DIF-013 기준)이나, 나중 번들의 data 노드 중
앞 번들에도 있는 노드가 절반 미만인 구간은 표에는 보이되 판정하지 않는다:
그 속도는 이 클러스터를 설명하지 않는다. 색인 속도가 가장 높은 구간이 peak,
가장 낮은 구간이 off-peak 이며 둘의 비율을 보여 준다. 사이징에 필요한 것은 peak 때의 data 노드당 속도이며, 전체 data 노드가 아니라
그 구간에 카운터가 움직인 노드 수로 나눈다(색인은 대개 hot tier).
참고로만 보고한다.

### DIF-012 — 판정 결과 변화

| 항목 | 내용 |
| --- | --- |
| 함수 | `diff._finding_delta` |
| 근거 구분 | 비교 계산 |
| 가능 심각도 | 치명, 주의, 참고 |
| 근거 파일 | 두 번들의 판정 결과 비교 |

**판정 로직**

이전 번들과 비교해 새로 생기거나, 나빠지거나, 해소된 치명·주의 결과(DIF-012, 항상 참고).

현재 번들에서 규칙이 실행되지 않았으면(입력 파일 없음 또는 규칙 실패, skipped 에 있음) 해소로 세지 않고,
이전 번들에서 실행되지 않았으면(base_skipped) 새 결과로 세지 않는다.

## 설정 지식 베이스

SET-001~006 이 사용하는 설정별 공식 기본값·종류·의미·변경 영향입니다(`esdoctor/settings_kb.py`).

- 적용 우선순위(공식): transient > persistent > elasticsearch.yml > 기본값
- dynamic 은 `PUT _cluster/settings`(또는 인덱스 설정 API)로 바꿀 수 있고, `null` 로 지정하면 기본값으로 돌아갑니다.
- static 은 모든 대상 노드의 elasticsearch.yml 에서만 바꿀 수 있고 재기동이 필요합니다. 인덱스 static 설정은 닫힌 인덱스에서만 바꿀 수 있습니다.
- 번들의 `cluster_settings_defaults` 는 yml 값이 반영된 값이고, API 로 명시한 키는 기본값을 보고하지 않습니다. 그래서 '원래 기본값' 은 이 표(공식 문서 기준 9.5)를 사용합니다.
- ↑ 는 기본값보다 크게, ↓ 는 작게 바꿨을 때의 영향입니다. 이 표에 없는 설정은 리포트에 '설명 미등록' 으로 값만 표기합니다.

| 설정 | 기본값 | 종류 | 범위 | 의미 | 변경 영향 | 위험도(↑/↓) | 문서 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `action.auto_create_index` | true | dynamic | cluster | 존재하지 않는 인덱스로 색인 시 자동 생성 허용 여부(패턴 지정 가능). | 제한하면 오타 인덱스 생성은 막지만, 허용 패턴에 없는 수집 대상은 색인이 실패합니다. 데이터 스트림·시스템 인덱스 패턴이 빠지면 기능이 멈출 수 있습니다. | INFO | [Index management settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/index-management-settings) |
| `action.destructive_requires_name` | true | dynamic | cluster | 와일드카드·_all 로 인덱스를 삭제하지 못하게 막음(8.0 부터 기본 true). | false 면 DELETE * 같은 요청 하나로 전체 인덱스가 삭제될 수 있습니다. | WARNING | [Index management settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/index-management-settings) |
| `bootstrap.memory_lock` | false (공식 문서에 없음, Elasticsearch 소스 기준) | static | node | heap 을 RAM 에 고정(swap 방지). | true 면 swap 을 막습니다. OS memlock 한도가 부족하면 기동 시 bootstrap check 가 실패합니다. | - | [Disable swapping](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/setup-configuration-memory) |
| `cluster.blocks.read_only` | false | dynamic | cluster | 클러스터 전체 읽기 전용. | true 면 모든 쓰기와 메타데이터 변경이 거부됩니다. | WARNING | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `cluster.blocks.read_only_allow_delete` | false | dynamic | cluster | 클러스터 전체 읽기 전용(삭제만 허용). | true 면 인덱스 삭제 외 모든 쓰기가 거부됩니다. | WARNING | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `cluster.indices.close.enable` | true | dynamic | cluster | 인덱스 close API 허용 여부. | false 면 인덱스를 닫을 수 없습니다(닫힌 인덱스는 복제·스냅샷 대상 관리가 어려워 막는 경우가 있음). | INFO | [Index management settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/index-management-settings) |
| `cluster.info.update.interval` | 30s | dynamic | cluster | 디스크 사용량 확인 주기. | ↑ 급격한 디스크 증가를 늦게 감지합니다.<br>↓ 마스터 부하가 조금 늘어납니다. | WARNING / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.max_shards_per_node` | 1000 | dynamic | cluster | non-frozen 데이터 노드당 열린 샤드 한도(클러스터 한도 = 값 × non-frozen 데이터 노드 수). | ↑ 한도 도달 시점은 늦어지지만, 한도가 막아 주던 과다 샤딩의 비용(heap·cluster state·마스터 부하)이 그대로 쌓입니다.<br>↓ 신규 인덱스 생성·롤오버가 더 일찍 실패합니다. | WARNING / INFO | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `cluster.max_shards_per_node.frozen` | 3000 | dynamic | cluster | data_frozen 역할 노드당 샤드 한도. | ↑ frozen 노드의 메타데이터 부하가 커집니다.<br>↓ 마운트 가능한 인덱스가 줄어듭니다. | INFO / INFO | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `cluster.metadata.display_name` | (없음) | dynamic | cluster | 사용자가 정하는 클러스터 메타데이터(ECH 는 배포 이름을 저장). Elasticsearch 설정이 아니므로 기본값이 없습니다. | 동작 영향 없음. | - | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `cluster.persistent_tasks.allocation.enable` | all | dynamic | cluster | persistent task(ML job, transform 등) 할당 허용. | none 이면 새 persistent task 가 할당되지 않습니다. | WARNING | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `cluster.routing.allocation.allow_rebalance` | always (8.16 이전 또는 balanced allocator 는 indices_all_active) | dynamic | cluster | 리밸런싱을 시작하는 조건(desired balance 할당기 기본 always, 이전 할당기는 indices_all_active). | 조건을 엄격히 하면(indices_primaries_active / indices_all_active) 복구가 끝날 때까지 리밸런싱이 미뤄져 편중 해소가 늦어집니다. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.awareness.attributes` | (없음) | dynamic | cluster | primary/replica 를 서로 다른 영역(zone·rack)에 배치하기 위한 노드 속성. | 설정 시 같은 샤드의 사본이 다른 영역에 배치됩니다. 영역별 노드 수가 다르면 일부 사본이 미할당될 수 있습니다. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.balance.disk_usage` | 2.0E-11 | dynamic | cluster | 노드별 디스크 사용량 균형 가중치. | 디스크 편중 분산 효과가 달라집니다. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.balance.index` | 0.55 | dynamic | cluster | 인덱스별 샤드 분산 가중치. | 가중치 변경은 대량 재배치를 유발할 수 있습니다. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.balance.shard` | 0.45 | dynamic | cluster | 노드별 전체 샤드 수 균형 가중치. | 가중치 조합을 바꾸면 desired balance 계산 결과가 달라져 대량 재배치가 발생할 수 있습니다. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.balance.threshold` | 1.0 | dynamic | cluster | 리밸런싱을 수행할 최소 불균형 정도. | ↑ 작은 불균형은 무시되어 이동이 줄지만 편중이 남습니다.<br>↓ 사소한 차이에도 이동이 잦아져 불필요한 I/O 가 생깁니다. | INFO / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.balance.write_load` | 10.0 | dynamic | cluster | 데이터 스트림 예상 쓰기 부하 균형 가중치. | 쓰기 핫스팟 분산 효과가 달라집니다. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.cluster_concurrent_rebalance` | 2 | dynamic | cluster | 클러스터 전체에서 동시에 리밸런싱할 샤드 수. | ↑ 이동 속도는 빨라지지만 네트워크·디스크 I/O 가 서비스 트래픽과 경합합니다.<br>↓ 편중 해소가 느려집니다. 0 이면 리밸런싱이 사실상 중단됩니다. | INFO / WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.disk.threshold_enabled` | true | dynamic | cluster | 디스크 워터마크 기반 할당 판단 사용 여부. | false 면 디스크가 가득 찰 때까지 샤드가 배치되어 flood stage 보호도 동작하지 않습니다. | WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.disk.watermark.flood_stage` | 95% | dynamic | cluster | 이 사용률을 넘은 노드의 인덱스에 쓰기 차단(read_only_allow_delete). | ↑ 쓰기 차단 전에 디스크가 완전히 찰 위험이 커집니다. 8.5 이상에서는 명시 설정하면 max_headroom 기본값(100GB)도 해제됩니다.<br>↓ 쓰기 차단이 이르게 발생합니다. | WARNING / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.disk.watermark.high` | 90% | dynamic | cluster | 이 사용률을 넘은 노드의 샤드를 다른 노드로 이동. | ↑ 이동이 늦게 시작되어 flood stage 도달 위험이 커집니다. 8.5 이상에서는 명시 설정하면 max_headroom 기본값(150GB)도 해제됩니다.<br>↓ 이동이 잦아집니다. | WARNING / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.disk.watermark.low` | 85% | dynamic | cluster | 이 사용률을 넘은 노드에는 새 샤드를 배치하지 않음. | ↑ 디스크를 더 채울 수 있지만 대응 여유가 줄어듭니다. 8.5 이상에서는 명시 설정하면 max_headroom 기본값(200GB)도 적용되지 않습니다.<br>↓ 여유 공간이 커도 샤드 배치가 막혀 일부 노드로 몰릴 수 있습니다. | INFO / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.enable` | all | dynamic | cluster | 어떤 샤드의 할당을 허용할지(all / primaries / new_primaries / none). | all 이 아니면 replica(또는 전체) 샤드가 할당되지 않아 노드 이탈 후 복구가 멈추고 yellow/red 가 지속됩니다. 롤링 재기동 중 임시로 바꾸는 값이며 작업 후 null 로 되돌려야 합니다. | WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.node_concurrent_incoming_recoveries` | 2 | dynamic | cluster | 노드당 동시 수신 복구 수. | ↑ 수신 노드의 I/O 경합이 커집니다.<br>↓ 복구가 느려집니다. | INFO / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.node_concurrent_outgoing_recoveries` | 2 | dynamic | cluster | 노드당 동시 송신 복구 수. | ↑ 송신 노드(대개 부하가 이미 큰 노드)의 I/O 경합이 커집니다.<br>↓ 복구가 느려집니다. | INFO / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.node_concurrent_recoveries` | 2 | dynamic | cluster | 노드당 incoming 과 outgoing 복구 한도를 함께 정합니다(각각 따로 셈). | ↑ 노드 교체 후 복구는 빨라지지만 해당 노드의 디스크·네트워크 포화 위험이 있습니다.<br>↓ 복구 시간이 길어져 yellow 상태가 오래 유지됩니다. | INFO / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.node_initial_primaries_recoveries` | 4 | dynamic | cluster | 노드 재기동 시 로컬 디스크에서 동시에 복구할 primary 수. | ↑ 재기동 직후 디스크 부하가 급증합니다.<br>↓ 전체 재기동 후 red 해소가 느려집니다. | INFO / INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.same_shard.host` | false | dynamic | cluster | 같은 호스트의 여러 노드에 동일 샤드 사본 배치 금지. | true 는 한 서버에 노드를 여러 개 띄운 구성에서 필요한 안전장치입니다. 단일 노드/호스트 구성에서 false 로 두면 호스트 장애 시 primary 와 replica 가 함께 사라질 수 있습니다. | INFO | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.total_shards_per_node` | -1 | dynamic | cluster | 노드당 전체 샤드 수 상한(-1=무제한). | ↓ 상한에 걸리면 샤드가 미할당으로 남습니다. 노드 장애 시 남은 노드로 옮길 수 없어 red 가 될 수 있습니다. | - / WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.rebalance.enable` | all | dynamic | cluster | 샤드 리밸런싱 허용 범위. | 리밸런싱이 제한되어 노드 증설 후에도 샤드가 새 노드로 이동하지 않고, 편중이 고착됩니다. | WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.use_adaptive_replica_selection` | true | dynamic | cluster | 검색 요청을 응답시간·큐 길이를 반영해 사본에 분배(ARS). | false 면 라운드로빈으로 분배되어, 느린 노드 1대가 전체 검색 p99 를 끌어올립니다. | WARNING | [Search shard routing](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/search-shard-routing) |
| `http.max_content_length` | 100mb | static | node | HTTP 요청 본문 최대 크기. | ↑ 대형 bulk·문서가 허용되어 heap 급증 위험이 커집니다(이 설정은 2GB, 즉 Integer.MAX_VALUE 바이트를 넘을 수 없음).<br>↓ 대형 bulk 요청이 413 으로 거부됩니다. | WARNING / INFO | [Networking settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/networking-settings) |
| `index.auto_expand_replicas` | false | dynamic | index | 데이터 노드 수에 맞춰 replica 수 자동 조정. | 범위 상한이 all 이거나 1 보다 크면 노드 증설 시 replica 가 자동으로 늘어 대형 인덱스에서 디스크·복구 부하가 급증합니다. | INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.blocks.read_only` | false | dynamic | index | 읽기 전용. | true 면 쓰기·메타데이터 변경이 거부됩니다. | WARNING | [Index blocks](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-block) |
| `index.blocks.read_only_allow_delete` | false | dynamic | index | 읽기 전용(삭제 허용). flood stage 가 자동 설정. | true 면 색인이 거부됩니다. 노드가 high watermark 아래로 내려가면 ES 가 자동으로 해제하며, 수동으로 건 경우는 수동으로 해제해야 합니다. | WARNING | [Index blocks](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-block) |
| `index.blocks.write` | false | dynamic | index | 쓰기 차단. | true 면 색인이 거부됩니다. | WARNING | [Index blocks](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-block) |
| `index.codec` | default(LZ4) | static | index | stored field 압축 방식(logsdb 와 9.5 의 columnar·logsdb_columnar 모드는 best_compression 기본, standard·time_series 는 LZ4). | best_compression 은 저장 공간을 줄이는 대신 문서 조회 시 압축 해제 비용이 늘어납니다. static 이라 닫힌 인덱스에서만 바꿀 수 있고, 기존 세그먼트는 merge 후 반영됩니다. | INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.highlight.max_analyzed_offset` | 1000000 | dynamic | index | 하이라이트 시 분석할 최대 문자 수. | ↑ 대형 문서 하이라이팅이 CPU·heap 을 크게 씁니다.<br>↓ 긴 문서의 하이라이트가 잘리거나 실패합니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.mapping.depth.limit` | 20 | dynamic | index | 객체 중첩 최대 깊이. | ↑ 깊은 중첩 문서가 허용됩니다.<br>↓ 색인이 거부될 수 있습니다. | INFO / INFO | [Mapping limit settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/mapping-limit) |
| `index.mapping.nested_fields.limit` | 100(9.3 이전에 만든 인덱스는 50) | dynamic | index | nested 타입 필드 수 한도. | ↑ nested 는 숨은 문서를 만들어 저장·검색 비용이 큽니다.<br>↓ 매핑이 거부됩니다. | WARNING / INFO | [Mapping limit settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/mapping-limit) |
| `index.mapping.nested_objects.limit` | 10000 | dynamic | index | 문서당 nested 객체 수 한도. | ↑ 문서 1건이 수만 개의 숨은 문서로 늘어 heap·디스크를 과점할 수 있습니다.<br>↓ 색인이 거부됩니다. | WARNING / INFO | [Mapping limit settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/mapping-limit) |
| `index.mapping.total_fields.limit` | 1000 | dynamic | index | 인덱스당 최대 필드 수(매핑 폭증 방지). | ↑ 필드가 늘수록 cluster state·heap 사용이 늘고 마스터 부하가 커집니다(매핑 폭증 신호).<br>↓ 새 필드가 들어오면 색인이 실패합니다. | WARNING / INFO | [Mapping limit settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/mapping-limit) |
| `index.max_docvalue_fields_search` | 100 | dynamic | index | 요청당 docvalue_fields 최대 수. | ↑ 응답 생성 비용이 늘어납니다.<br>↓ 해당 요청이 거부됩니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_inner_result_window` | 100 | dynamic | index | inner_hits·top_hits 의 from + size 최대값. | ↑ 집계 응답이 커져 heap 사용이 늘어납니다.<br>↓ 해당 쿼리가 거부됩니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_ngram_diff` | 1 | dynamic | index | ngram 토크나이저 min/max 차이 허용치. | ↑ 토큰 수가 급증해 색인 크기와 속도에 큰 영향을 줍니다.<br>↓ 분석기 정의가 거부됩니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_refresh_listeners` | 1000 (공식 문서에 없음, Elasticsearch 소스 기준) | dynamic | index | refresh=wait_for 대기자 최대 수. | ↑ 대기 요청이 heap 을 더 씁니다.<br>↓ 초과 요청은 강제 refresh 를 유발합니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_regex_length` | 1000 | dynamic | index | regexp 쿼리 최대 길이. | ↑ 복잡한 정규식이 CPU 를 과점할 수 있습니다.<br>↓ 해당 쿼리가 거부됩니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_result_window` | 10000 | dynamic | index | from + size 최대값. | ↑ 깊은 페이징이 허용되어 샤드마다 from+size 건을 모으므로 heap 사용이 페이지 깊이에 비례해 늘어납니다.<br>↓ 깊은 페이지 요청이 거부됩니다. | WARNING / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_script_fields` | 32 | dynamic | index | 요청당 script_fields 최대 수. | ↑ 검색 CPU 사용이 늘어납니다.<br>↓ 해당 요청이 거부됩니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_shingle_diff` | 3 | dynamic | index | shingle 필터 min/max 차이 허용치. | ↑ 토큰 수가 급증합니다.<br>↓ 분석기 정의가 거부됩니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.max_terms_count` | 65536 | dynamic | index | terms 쿼리의 최대 항목 수. | ↑ 대형 terms 쿼리가 CPU·heap 을 크게 씁니다.<br>↓ 해당 쿼리가 거부됩니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.merge.policy.floor_segment` | 16mb (9.5 이전 2mb) (공식 문서에 없음, Elasticsearch 소스 기준) | dynamic | index | merge 대상을 고를 때 이보다 작은 세그먼트는 이 크기로 간주합니다. | ↑ 작은 세그먼트를 더 빨리 합쳐 세그먼트는 줄지만 merge I/O 가 늘어납니다.<br>↓ 작은 세그먼트가 쌓여 검색이 더 많은 세그먼트를 거칩니다. | INFO / INFO | [Merge settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/merge) |
| `index.merge.policy.max_merge_at_once` | 16 (9.5 이전 10) (공식 문서에 없음, Elasticsearch 소스 기준) | dynamic | index | merge 한 번에 합치는 최대 세그먼트 수(tiered merge policy 기준. time-based 인덱스는 사용하지 않음). | ↑ merge 횟수는 줄고 한 번의 I/O 는 커집니다.<br>↓ 작은 merge 가 잦아지고 세그먼트 수가 천천히 줄어듭니다. | INFO / INFO | [Merge settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/merge) |
| `index.merge.policy.max_merged_segment` | 5gb (8.8 이후 time-based 인덱스, 즉 매핑에 색인된 @timestamp date 필드가 있으면 100gb) (공식 문서에 없음, Elasticsearch 소스 기준) | dynamic | index | merge 로 만들어지는 세그먼트의 최대 크기. | ↑ 세그먼트 수가 줄어 검색(특히 kNN)이 빨라지지만 merge 한 번의 I/O 가 커집니다.<br>↓ 세그먼트가 많아져 검색이 느려집니다. | INFO / INFO | [Merge settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/merge) |
| `index.merge.policy.segments_per_tier` | 8 (9.5 이전 10) (공식 문서에 없음, Elasticsearch 소스 기준) | dynamic | index | tier 당 허용 세그먼트 수(tiered merge policy 기준. time-based 인덱스는 이 값을 쓰지 않는 log byte size policy 를 씀). | ↑ merge 는 줄지만 세그먼트가 많아집니다.<br>↓ merge 가 잦아져 I/O 가 늘어납니다. | INFO / INFO | [Merge settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/merge) |
| `index.number_of_replicas` | 1 | dynamic | index | 샤드당 replica 수. | ↑ 가용성·검색 처리량은 늘지만 디스크와 색인 비용이 배수로 늘어납니다.<br>↓ 0 이면 노드 1대 장애로 데이터가 유실될 수 있습니다. | INFO / WARNING | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.queries.cache.enabled` | true | static | index | 노드 query(filter) 캐시 사용. | false 면 반복 필터를 매번 다시 계산합니다. | INFO | [Node query cache settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/node-query-cache-settings) |
| `index.refresh_interval` | 1s(미지정 시 search idle 적용) | dynamic | index | 새 문서가 검색에 보이기까지의 주기. | ↑ 색인 처리량이 늘고 merge 부담이 줄지만 검색 반영이 늦어집니다. -1 은 refresh 중지.<br>↓ 세그먼트가 잦게 생겨 CPU·merge 부담이 커집니다. 명시하면 search idle 최적화가 꺼집니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.requests.cache.enable` | true | dynamic | index | shard request 캐시 사용. | false 면 반복 집계를 매번 다시 계산합니다. | INFO | [The shard request cache](https://www.elastic.co/docs/deploy-manage/distributed-architecture/shard-request-cache) |
| `index.routing.allocation.total_shards_per_node` | -1 | dynamic | index | 이 인덱스의 노드당 샤드 수 상한(핫스팟 방지). | ↓ 너무 작으면 노드 장애 시 샤드를 옮길 곳이 없어 미할당됩니다. | - / WARNING | [Total shards per node](https://www.elastic.co/docs/reference/elasticsearch/index-settings/total-shards-per-node) |
| `index.search.idle.after` | 30s | dynamic | index | 검색이 없으면 주기적 refresh 를 건너뛰기 시작하는 시간. | ↑ refresh 생략 효과가 늦게 시작됩니다.<br>↓ 검색 idle 전환이 빨라져, 뜸한 첫 검색이 refresh 를 기다리게 됩니다. | INFO / INFO | [Index modules (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) |
| `index.translog.durability` | request | dynamic | index | 요청마다 translog 를 fsync 할지(request) 주기적으로 할지(async). | async 면 색인이 빨라지는 대신 노드 비정상 종료 시 sync_interval 동안의 확인 응답된 쓰기가 유실될 수 있습니다. | WARNING | [Translog settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/translog) |
| `index.translog.sync_interval` | 5s | dynamic | index | async 모드의 translog fsync 주기. | ↑ async 모드에서 유실 가능 구간이 길어집니다.<br>↓ fsync 가 잦아집니다. | INFO / INFO | [Translog settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/translog) |
| `index.unassigned.node_left.delayed_timeout` | 1m | dynamic | index | 노드 이탈 후 replica 재할당을 미루는 시간. | ↑ 노드 복귀를 기다리는 동안 yellow 가 길어지지만 불필요한 재복제는 줄어듭니다.<br>↓ 잠깐의 재기동에도 전체 재복제가 시작됩니다(0 이면 즉시). | INFO / WARNING | [Delaying allocation when a node leaves](https://www.elastic.co/docs/deploy-manage/distributed-architecture/shard-allocation-relocation-recovery/delaying-allocation-when-node-leaves) |
| `indices.breaker.fielddata.limit` | 40% | dynamic | cluster | fielddata 적재 한도(heap 대비). | ↑ text 필드 집계 등으로 heap 이 잠식되어 GC 압박이 커집니다.<br>↓ 집계가 더 일찍 거부됩니다. | WARNING / INFO | [Circuit breaker settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/circuit-breaker-settings) |
| `indices.breaker.request.limit` | 60% | dynamic | cluster | 요청 단위 메모리(집계 등) 한도. | ↑ 대형 집계가 heap 을 과점할 수 있습니다.<br>↓ 집계가 더 일찍 거부됩니다. | WARNING / INFO | [Circuit breaker settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/circuit-breaker-settings) |
| `indices.breaker.total.limit` | 95%(indices.breaker.total.use_real_memory 가 false 면 70%) | dynamic | cluster | parent breaker 한도(use_real_memory=true 기준 95%, false 면 70%). | ↑ OOM 직전까지 요청을 받아들여 노드가 OutOfMemoryError 로 종료될 위험이 커집니다.<br>↓ 정상 요청도 CircuitBreakingException 으로 거부됩니다. | WARNING / INFO | [Circuit breaker settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/circuit-breaker-settings) |
| `indices.breaker.total.use_real_memory` | true | dynamic | node | parent breaker 가 실제 heap 사용량을 기준으로 판단(8.1 부터 dynamic, 이전은 static). | false 면 추정치 기준(한도 기본 70%)으로 동작해 실제 heap 과 괴리가 생길 수 있습니다. | WARNING | [Circuit breaker settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/circuit-breaker-settings) |
| `indices.fielddata.cache.size` | unbounded | static | node | fielddata 캐시 상한(기본 무제한, 실제 상한은 fielddata breaker). | 상한을 두면 eviction 이 발생해 해당 집계가 매번 fielddata 를 다시 적재합니다. | INFO | [Field data cache settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/field-data-cache-settings) |
| `indices.lifecycle.poll_interval` | 10m | dynamic | cluster | ILM 조건 확인 주기. | ↑ 롤오버·삭제가 늦게 수행되어 샤드 크기·디스크가 계획보다 커집니다.<br>↓ 마스터 부하가 늘어납니다. 테스트 목적 외에는 줄이지 않습니다. | INFO / WARNING | [Index lifecycle management settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/index-lifecycle-management-settings) |
| `indices.memory.index_buffer_size` | 10% | static | node | 색인 버퍼(heap 대비). 쓰기 중인 샤드가 공유. | ↑ 대량 색인 효율은 좋아지지만 검색·집계에 쓸 heap 이 줄어듭니다.<br>↓ flush 가 잦아지고 작은 세그먼트가 늘어납니다. | INFO / INFO | [Indexing buffer settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/indexing-buffer-settings) |
| `indices.queries.cache.size` | 10% | static | node | 노드 query(filter) 캐시 크기(heap 대비). | ↑ heap 상주량이 늘어 GC 압박이 커집니다.<br>↓ 필터 캐시 적중률이 떨어집니다. | INFO / INFO | [Node query cache settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/node-query-cache-settings) |
| `indices.recovery.max_bytes_per_sec` | 40mb(전용 cold/frozen 노드는 전체 메모리에 따라 40mb~250mb) | dynamic | cluster | 노드당 복구 대역 상한(전용 cold/frozen 노드는 메모리 기반으로 자동 산정). | ↑ 복구가 빨라지지만 복구 트래픽이 서비스 I/O 를 잠식할 수 있습니다.<br>↓ 노드 교체·재기동 후 복구가 느려져 yellow 상태가 길어집니다. | INFO / WARNING | [Index recovery settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/index-recovery-settings) |
| `indices.requests.cache.size` | 1% | static | node | shard request 캐시 크기(heap 대비). | ↑ heap 상주량이 늘어납니다.<br>↓ 집계 결과 캐시 효과가 줄어듭니다. | INFO / INFO | [Shard request cache settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/shard-request-cache-settings) |
| `ingest.geoip.downloader.enabled` | true | dynamic | cluster | GeoIP DB 자동 다운로드. | 폐쇄망에서는 false 가 정상입니다. 이 경우 DB 를 수동으로 배포해야 geoip processor 가 동작합니다. | - | [GeoIP processor](https://www.elastic.co/docs/reference/enrich-processor/geoip-processor) |
| `logger.level` | INFO (공식 문서에 없음, Elasticsearch 소스 기준) | static | node | 시작 시 읽는 root 로그 레벨(노드 설정). | 바꾸려면 재기동이 필요합니다. 실행 중에 root 레벨을 바꾸려면 cluster settings API 로 logger._root 를 설정합니다. | INFO | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `network.breaker.inflight_requests.limit` | 100% | dynamic | cluster | 수신 중인 요청(transport/HTTP) 크기 한도. | ↑ 대형 bulk 가 한꺼번에 들어와 heap 이 급증할 수 있습니다.<br>↓ 대형 요청이 거부됩니다. | WARNING / INFO | [Circuit breaker settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/circuit-breaker-settings) |
| `node.processors` | 가용 프로세서 수(자동) | static | node | ES 가 인식하는 CPU 수(스레드풀 크기 산정 기준). | 실제보다 크게 잡으면 스레드가 과다해지고, 작게 잡으면 CPU 를 다 쓰지 못합니다. 컨테이너에서 CPU limit 과 맞출 때 사용합니다. | INFO | [Thread pool settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings) |
| `node.store.allow_mmap` | true | static | node | Lucene 파일 mmap 사용. | false 면 mmap 대신 NIO 로 읽어 검색 성능이 떨어질 수 있습니다(vm.max_map_count 를 못 올리는 환경용). | INFO | [Store (index settings)](https://www.elastic.co/docs/reference/elasticsearch/index-settings/store) |
| `script.max_compilations_rate` | 150/5m | dynamic | cluster | 스크립트 컴파일 속도 한도. | 올리면 매번 다른 스크립트를 보내는 잘못된 사용(파라미터 미사용)이 가려지고 CPU·메모리 부담이 커집니다. | INFO | [Circuit breaker settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/circuit-breaker-settings) |
| `search.allow_expensive_queries` | true | dynamic | cluster | script·wildcard·regexp·fuzzy 등 비싼 쿼리 허용 여부. | false 면 해당 쿼리가 거부됩니다(보호 목적). Kibana 일부 기능도 영향받을 수 있습니다. | INFO | [Query DSL](https://www.elastic.co/docs/reference/query-languages/querydsl) |
| `search.default_search_timeout` | -1 | dynamic | cluster | 요청에 timeout 이 없을 때 적용되는 검색 타임아웃(-1=무제한). | 짧게 두면 무거운 쿼리가 부분 결과로 끝나고, 무제한이면 비정상 쿼리가 자원을 계속 점유할 수 있습니다. | INFO | [The search API](https://www.elastic.co/docs/solutions/search/the-search-api) |
| `search.low_level_cancellation` | true (공식 문서에 없음, Elasticsearch 소스 기준) | dynamic | cluster | 검색 취소 요청을 세그먼트 단위로 빠르게 반영. | false 면 취소된 검색이 늦게 멈춰 자원을 더 오래 씁니다. | INFO | [Search settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/search-settings) |
| `search.max_buckets` | 65536 | dynamic | cluster | 단일 응답의 최대 집계 버킷 수. | ↑ 대형 집계가 허용되어 coordinating 노드 heap 압박·circuit breaker 발동 위험이 커집니다.<br>↓ 기존 대시보드 집계가 실패할 수 있습니다. | WARNING / INFO | [Search settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/search-settings) |
| `slm.retention_schedule` | 0 30 1 * * ? | dynamic | cluster | SLM 보존 정책(오래된 스냅샷 삭제) 실행 주기. | 실행 시각이 바뀝니다. 너무 드물면 스냅샷 저장소 용량이 계획보다 커집니다. | - | [Snapshot and restore settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/snapshot-restore-settings) |
| `thread_pool.search.queue_size` | 자동 산정(9.0 이상: search 스레드 수 × 1000, 8.x: 1000) | static | node | search 스레드풀 대기열 크기. | ↑ rejection 은 줄지만 검색 지연·heap 사용이 늘어납니다.<br>↓ rejection 이 더 빨리 발생합니다. | WARNING / INFO | [Thread pool settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings) |
| `thread_pool.search.size` | int((코어 수 × 3) / 2) + 1(자동) | static | node | search 스레드 수. | 임의 변경 시 CPU 경합이나 처리량 저하가 생깁니다. | WARNING | [Thread pool settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings) |
| `thread_pool.write.queue_size` | 10000(9.2부터 max(10000, 할당 프로세서 수 x 750)) | static | node | write 스레드풀 대기열 크기. | ↑ rejection 은 줄지만 요청이 큐에서 오래 대기해 지연과 heap 사용이 늘어납니다. 원인(과부하)이 가려집니다.<br>↓ rejection(429)이 더 빨리 발생합니다. | WARNING / INFO | [Thread pool settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings) |
| `thread_pool.write.size` | CPU 코어 수(자동) | static | node | write 스레드 수. | 할당 프로세서 + 1 을 넘을 수 없습니다(더 크면 시작 시 거부). 코어 수보다 크면 컨텍스트 스위칭만 늘어납니다. | WARNING | [Thread pool settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings) |
| `transport.compress` | indexing_data | static | node | 노드 간 전송 압축 대상. | true 는 모든 전송을 압축해 CPU 를 더 쓰고, false 는 색인 데이터도 압축하지 않아 네트워크 사용이 늘어납니다. | INFO | [Networking settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/networking-settings) |
| `xpack.mapping.synthetic_source_fallback_to_stored_source` | false (공식 문서에 없음, Elasticsearch 소스 기준) | dynamic | cluster | synthetic _source 를 쓸 새 인덱스를 라이선스와 관계없이 stored _source 로 만들게 합니다(operator 설정). 이 설정이 없어도 라이선스가 synthetic _source 를 허용하지 않으면 ES 가 알아서 stored 로 바꿉니다. | true: synthetic _source 를 쓸 인덱스를 stored _source 로 만듭니다. | - | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |
| `xpack.ml.max_machine_memory_percent` | 30 | dynamic | cluster | ML 작업이 쓸 수 있는 노드 메모리 비율. | ↑ ML 프로세스가 파일시스템 캐시·다른 프로세스 몫을 잠식합니다.<br>↓ ML job 이 할당되지 못할 수 있습니다. | INFO / INFO | [Machine learning settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/machine-learning-settings) |
| `xpack.ml.max_model_memory_limit` | 0b | dynamic | cluster | 이상 탐지 job 과 data frame analytics job 의 model_memory_limit 상한(0 = 제한 없음, xpack.ml.use_auto_machine_memory_percent 가 true 이면 자동 계산된 상한). | 이보다 많은 메모리를 요구하는 job 은 생성하거나 수정할 수 없습니다. | - | [Machine learning settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/machine-learning-settings) |
| `xpack.ml.use_auto_machine_memory_percent` | false | dynamic | cluster | ML 메모리를 노드 메모리에서 자동으로 정할지 여부(Elastic Cloud 에서는 operator 설정). | true: ML 메모리가 xpack.ml.max_machine_memory_percent 대신 노드 크기를 따릅니다. | - | [Machine learning settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/machine-learning-settings) |
| `xpack.monitoring.collection.enabled` | false | dynamic | cluster | 레거시 내부 모니터링 수집. deprecated 이며 모니터링 플러그인은 10.0 에서 제거됩니다. | true 면 클러스터 자신에 모니터링 데이터를 색인해 부하가 늘어납니다. 운영 모니터링은 별도 클러스터를 권장합니다. | INFO | [Monitoring settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/monitoring-settings) |
| `cluster.routing.allocation.exclude.*` | (없음) | dynamic | cluster | 지정한 노드(이름·IP·호스트·속성)에서 샤드를 빼냄. | 해당 노드에 샤드가 배치되지 않습니다. 유지보수 후 제거하지 않으면 용량이 남아도 샤드가 다른 노드로 몰립니다. | WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.include.*` | (없음) | dynamic | cluster | 지정한 노드에만 샤드 배치를 허용. | 조건에 맞지 않는 노드에는 샤드가 배치되지 않아 편중·미할당이 생길 수 있습니다. | WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `cluster.routing.allocation.require.*` | (없음) | dynamic | cluster | 지정한 조건을 모두 만족하는 노드에만 샤드 배치. | 조건을 만족하는 노드가 부족하면 샤드가 미할당됩니다. | WARNING | [Cluster-level shard allocation and routing](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings) |
| `logger.*` | INFO(로거별 기본) | dynamic | cluster | 로거 레벨. | DEBUG/TRACE 로 올리면 로그량이 급증해 디스크·I/O·성능에 영향을 줍니다. 조사 후 null 로 되돌려야 합니다. | INFO | [Miscellaneous cluster settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings) |

## 임계값 전체 목록

`[공식]` 은 공식 문서의 수치, `[도구]` 는 이 도구가 정한 값입니다. 주석이 없는 항목은 도구 판단 값입니다.

| 키 | 기본값 | 설명 |
| --- | --- | --- |
| `heap_used_pct_warn` | 75 | [공식] Elastic Cloud 가 빨간색으로 표시하는 JVM memory pressure(old gen 사용량 / 최대) |
| `heap_used_pct_crit` | 85 | [공식] 조치가 필요한 JVM memory pressure(high JVM memory pressure 가이드) |
| `heap_max_bytes_crit` | 30GiB | [공식] compressed oops 경계는 약 30GB 까지 가능(JVM 플래그가 없을 때만 사용) |
| `heap_oops_safe_bytes` | 26GiB | [공식] 대부분의 시스템에서 26GB 는 안전(JVM 플래그가 없을 때만 사용) |
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
| `dedicated_master_data_nodes` | 10 | [도구] 현장 기준: 전용 마스터가 필요해지는 데이터 노드 수 |
| `uptime_short_hours` | 6 | [도구] 최근 재기동 판단 |
| `node_compare_min_uptime_hours` | 24 | [도구] uptime 이 이보다 짧은 노드는 노드 간 비교에서 제외 |
| `disk_watermark_low_default` | 85% | [공식] ES 기본값(설정 파일이 없을 때만 사용) |
| `disk_watermark_high_default` | 90% | [공식] ES 기본값(설정 파일이 없을 때만 사용) |
| `disk_watermark_flood_default` | 95% | [공식] ES 기본값(설정 파일이 없을 때만 사용) |
| `disk_watermark_flood_frozen_default` | 95% | [공식] frozen 전용 노드 flood stage |
| `disk_watermark_flood_frozen_headroom_default` | 20GB | [공식] frozen flood max_headroom |
| `disk_imbalance_pct_warn` | 15 | [도구] 노드 간 디스크 사용률 편차(%p) |
| `disk_low_margin_pct` | 10 | [도구] 실효 low 워터마크까지 남은 %p |
| `rejected_crit` | 1,000 | [도구] 누적 rejection 합계 |
| `frozen_cache_turnover_per_day` | 1.0 | 과도한 교체로 보는 frozen shared cache 일 평균 eviction(캐시 region 수의 배수, FRZ-001) |
| `shard_balance_min_diff` | 10 | 같은 tier 노드 간 샤드 수 차이를 보고하는 최소 개수(SHD-006) |
| `breaker_tripped_warn` | 1 | [도구] breaker 발동 횟수(1 = 이력 존재) |
| `breaker_delta_crit` | 10 | [도구] 두 번들 사이 breaker trip 증가분이 이 값 이상이면 DIF-007 치명 |
| `breaker_used_pct_warn` | 70 | 높은 사용으로 보는 circuit breaker 추정 크기 / 한도(%) (request, fielddata, in_flight_requests 등) |
| `shards_per_gb_heap_warn` | 20 | [공식] heap 1GB당 샤드 20개(8.3 미만 전용) |
| `shards_per_gb_heap_crit` | 30 | [도구] 8.3 미만 전용 |
| `max_shards_per_node_headroom_pct_warn` | 80 | [도구] cluster.max_shards_per_node 대비 사용률 |
| `max_shards_per_node_crit_pct` | 95 | [도구] cluster.max_shards_per_node 대비 치명이 되는 사용률 |
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
| `flush_avg_ms_info` | 800 | [도구] 현장 기준: flush 1회 평균 시간 |
| `flush_avg_ms_warn` | 1,200 | [도구] 현장 기준 |
| `refresh_avg_ms_info` | 40 | [도구] 현장 기준: refresh 1회 평균 시간 |
| `refresh_avg_ms_warn` | 70 | [도구] 현장 기준 |
| `merge_avg_ms_info` | 20,000 | [도구] 현장 기준: merge 1회 평균 시간 |
| `merge_avg_ms_warn` | 40,000 | [도구] 현장 기준 |
| `write_latency_min_ops` | 100 | [도구] 노드 평균을 판정하기 위한 최소 flush/refresh/merge 횟수 |
| `load_host_cpu_pct_max` | 50 | [도구] 이 CPU% 미만인 컨테이너 노드는 load average 로 판정하지 않음(호스트 값이므로) |
| `write_node_index_share_min` | 0.1 | [도구] 노드의 index_total 이 가장 많이 색인한 노드 대비 이 비율 이상이면 색인 노드로 봄 |
| `write_shard_skew_warn` | 0.5 | [도구] tier 안 노드별 쓰기 대상 shard 의 (최대 - 최소) / 평균 |
| `write_shard_skew_min` | 3 | [도구] 보고할 최소 쓰기 대상 shard 차이 |
| `restart_share_warn` | 0.5 | [도구] uptime_short_hours 안에 재시작한 노드 비율 |
| `long_running_task_ms_high` | 3,600,000 | [도구] 1시간: 장시간 task 를 주의로 올리는 기준 |
| `monitoring_task_ms_info` | 86,400,000 | [도구] 24시간: 모니터링·내부 task 는 이 시간을 넘을 때만 보고 |
| `translog_flush_threshold_default` | 10gb | [공식] index.translog.flush_threshold_size 기본값(8.8+) |
| `translog_flush_threshold_legacy` | 512mb | [공식] 8.8 이전 기본값 |
| `docs_rollover_overshoot_pct` | 5 | [도구] 롤오버된 샤드가 2억건을 넘어도 되는 허용치(ILM 은 poll_interval 마다 확인) |
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
| `query_failure_pct_warn` | 1 | [도구] 문제로 보는 사용자 인덱스의 query 실패 / query 수(%)(IDX-006) |
| `workload_skew_min_per_sec` | 10 | DIF-009 indexing 편중을 판정하는 tier 노드당 최소 평균 초당 처리량 |
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
| `logsdb_shard_gb_high` | 30 | [도구] logsdb shard 범위 상한(공식 상한은 50GB) |
| `logsdb_shard_gb_low` | 10 | [공식] 10~50GB 범위의 하한 |
| `logsdb_rows_max` | 100 | [도구] logsdb shard 크기 표에 보여 줄 최대 인덱스 수 |
| `nested_fields_near_limit_pct` | 80 | [도구] nested_fields.limit 대비 nested 필드 수 |
| `mapping_fields_near_limit_pct` | 90 | [도구] total_fields.limit 대비 필드 수 |
| `ilm_rollover_max_shard_gb` | 50 | [공식] 롤오버 샤드 크기 권장 상한 |
| `ilm_implicit_max_shard_docs` | 200,000,000 | [공식] 샤드당 2억건이면 rollover 가 항상 실행됨. 더 큰 값은 효과 없음 |
| `forcemerge_free_space_factor` | 3 | [공식] max_num_segments=1 은 shard 크기의 최대 3배 여유 공간이 필요할 수 있음 |
| `forcemerge_stuck_hours` | 24 | [도구] force merge 단계에 이 시간 이상 머물면 보고 |
| `disk_io_busy_pct_warn` | 60 | [도구] 기동 이후 평균 디스크 사용률 |
| `search_expensive_share_warn` | 10 | [도구] 비용이 큰 쿼리 유형의 검색 대비 비중(%) |
| `search_pool_busy_share` | 0.8 | [도구] 활성 search 스레드 / 풀 크기가 이 이상이면 바쁜 것으로 봄 |
| `search_io_cpu_pct_max` | 50 | [도구] search 풀이 바쁜데 노드 CPU 가 이보다 낮으면 대기 중인 것으로 봄 |
| `ingest_fail_ratio_warn` | 0.01 | [도구] 파이프라인의 실패 / 처리 문서 비율 |
| `hot_rolled_days_info` | 30 | [도구] ILM hot phase 에 남은 인덱스의 롤오버 후 경과일 |
| `cost_replicas_min` | 2 | [도구] 검색 없는 인덱스를 보고하는 replica 수 |
| `tier_hot_used_pct` | 70 | [도구] 차가운 tier 와 비교를 시작하는 hot tier 디스크 사용률 |
| `tier_gap_pct` | 30 | [도구] hot 과 차가운 tier 의 디스크 사용률 차이(포인트) |
| `tier_idle_used_pct` | 20 | [도구] 차가운 tier 사용률이 이보다 낮으면 대부분 비어 있는 것으로 봄 |
| `size_idle_cpu_pct` | 20 | [도구] tier 의 모든 노드 CPU 가 이보다 낮으면 여유 큼 후보 |
| `size_idle_load_per_cpu` | 0.3 | [도구] ... 그리고 load15/CPU 가 이보다 낮음 |
| `size_idle_heap_pct` | 50 | [도구] ... 그리고 heap 사용률이 이보다 낮음 |
| `size_idle_disk_pct` | 30 | [도구] ... 그리고 디스크 사용률이 이보다 낮음(frozen 제외) |
| `ingest_window_days` | 7 | [도구] 하루 수집량 추정에 쓰는 최근 인덱스 기간(일) |
| `diff_min_hours_for_projection` | 1.0 | [도구] 이보다 짧은 간격은 외삽 안 함 |
| `disk_projection_days_warn` | 30 | [도구] |
| `node_change_noise_pct` | 5 | [도구] 노드별 비교에서 이 퍼센트 미만의 변화는 '변화 없음' 으로 표시 |
| `index_growth_min_bytes` | 1GiB | [도구] |
| `top_n` | 15 | [도구] 근거 표 최대 행 수 |
| `eol_major_below` | 8 | [도구] 이 메이저 미만은 구버전 경고 |
