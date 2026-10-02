# 변경 이력

형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/) 를 따릅니다.
각 항목은 "이전 동작 → 현재 동작 (근거)" 로 적습니다. 이전 리포트와 결과가 다른 이유를 추적하는 용도입니다.

## [0.14.0] - 2026-10-02

모든 리포트 맨 위에 병목 요약을 넣고, 최근 재시작한 노드를 노드 간 비교에서 빼고, 네트워크 스토리지 위의 frozen shared cache, 스토리지 비용과 사이징 판정, 여러 번들의 구간별 처리량, 노드별 비교 표, HTML 리포트 검색창을 추가했습니다. 공식 문서와 전체를 다시 대조해 고친 내용도 담았습니다. 공식 수치가 없는 임계값은 모두 `[도구]` 로 표기하고 `--thresholds` 로 바꿀 수 있습니다.

### 이름 변경

- 패키지 이름 `esdiag` → `esdoctor`(esdiag 는 Elastic 공식 툴이 쓰는 이름). 패키지 폴더는 `esdoctor/`, 단일 파일 빌드는 `dist/esdoctor.pyz`, 단독 실행 파일은 `dist/esdoctor`, 언어 환경 변수는 `ESDOCTOR_LANG`. `python3 analyze.py` 실행 방법은 그대로

### 추가

- 병목 요약(HTML, Markdown, 콘솔, JSON `bottleneck`, Support 팀 요약): 색인이 따라가는가, 검색이 느린가, 스토리지가 한계인가, 재시작이나 복구가 수치를 왜곡하는가, 용량 부족인가 편중인가의 다섯 가지 질문. 증상(거부, 큐, throttle, 지연)을 먼저 보고, 증상이 있을 때만 리포트의 판정을 정해진 순서의 원인 그룹으로 훑어 원인을 짚음. 순서는 도구 판단이며 공식 판단 트리가 아님. `--only` 로 일부 룰만 돌리면 빠짐
- FRZ-002(주의, 도구 판단): frozen shared cache 가 있는 노드의 data path 가 네트워크 파일시스템(nfs, cifs, smb, fuse, glusterfs, ceph). shared cache 가 있는 노드는 data path 를 하나만 가질 수 있으므로 캐시 파일이 그 파일시스템에 있음. 표에 캐시 파일을 읽는 hot thread 수와 search 큐·거부를 함께 보여 줌. 서버 로그에 "Direct buffer memory" 오류가 있으면 치명
- PERF-013(도구 판단): 수집 시점에 노드 CPU 가 50% 미만인데 search thread pool 이 바쁨(활성 >= 풀 크기의 80%). 대기 중인 검색이 있으면 주의, 아니면 참고
- COST-001(참고): 롤오버 후 30일 이상 지나도 ILM hot phase 에 있는 인덱스. 정책별로 묶어 다음 phase 와 min_age 를 표시. warm, cold, frozen tier 가 있을 때만
- COST-002(참고): replica 가 2개 이상인데 샤드 시작 이후 검색이 없는 인덱스와 replica 1개로 줄일 때 확보되는 공간. data 노드가 replica + 1 개 이상 가용 영역에 걸쳐 있으면 제외
- COST-003(참고): tier 간 디스크 사용. hot 이 70% 이상인데 warm·cold tier 가 30 포인트 이상 비어 있거나, warm·cold tier 가 20% 미만. frozen 은 보여 주기만 하고 비교하지 않음
- COST-004(참고, 주의): 번들 하나로 계산한, 수집 대상 tier 가 high watermark 까지 더 받을 수 있는 수집 일수. 하루 수집량은 최근 7일 안에 만들어진 인덱스로 추정. 30일 이하이면서 그 데이터의 절반 넘게 hot 다음 ILM phase 가 없으면 주의
- COST-005(참고, 사실 보고): 데이터 종류와 tier 별 저장량. 종류는 공식 데이터 스트림 이름 규칙(logs, metrics, traces, synthetics)에 보안 알림, system, 기타 데이터 스트림, 기타 인덱스를 더함. partial 마운트는 store 크기가 캐시 크기라 따로 표시
- COST-006(참고): 번들 하나로 본 tier 별 사이징 신호. 모든 노드가 바쁘거나, 거부가 있거나, indexing pressure 가 거부했거나, high watermark 에 닿은 노드가 있으면 "부족 신호". 모든 노드가 24시간 이상 떠 있었고 CPU, load, heap, 디스크가 모두 낮으며 거부가 없을 때만 "여유 큼". 번들은 한 순간이라 여유 큼은 "지금 줄여라" 가 아니라 "모니터링으로 확인해 볼 만함"
- DIF-014(참고): 번들이 3개 이상(`--baseline` 반복 지정)이면 구간별 처리량. 초당 색인·검색, data 노드당 값, peak 와 최저 구간, 둘의 비율. 구간 중 재시작한 노드는 그 구간에서 뺌
- 비교 모드: 노드별 이전/지금 표(uptime, heap, CPU, load15, 디스크, 샤드, 색인·검색 속도, 거부, old GC). 5% 미만 변화는 "=" 로 표시
- `--baseline` 반복 지정 가능. 번들을 수집 시각 순으로 정렬해 가장 최근 번들을 비교 기준으로 씀
- HTML 리포트: 필터 옆 검색창으로 판정과 근거 표의 행을 인덱스·노드·tier 이름으로 거름
- 임계값 5개: `node_change_noise_pct`, `size_idle_cpu_pct`, `size_idle_load_per_cpu`, `size_idle_heap_pct`, `size_idle_disk_pct`
- 자원·용량 영역에 "스토리지 비용" 분류, `--only` 용 `cost` 모듈
- `tests/test_bottleneck_cost.py`, `tests/drive_branches.py` 시나리오 7개
- 임계값 10개: `node_compare_min_uptime_hours`, `search_pool_busy_share`, `search_io_cpu_pct_max`, `ingest_fail_ratio_warn`, `hot_rolled_days_info`, `cost_replicas_min`, `tier_hot_used_pct`, `tier_gap_pct`, `tier_idle_used_pct`, `ingest_window_days`

### 변경

- HOT-001: 방금 재시작한 노드가 한가해 보여 heap·CPU 편차를 만들었음 → uptime 24시간 미만 노드는 heap·CPU 비교에서 빼고 판정에 이름을 적음. 디스크 사용량은 재시작해도 그대로라 계속 비교
- HOT-002: 누적 합계를 비교해 오래 떠 있던 노드가 유리했음 → 시간당 값으로 비교하고 uptime 24시간 미만 노드는 뺌
- PERF-012: 누적 index_total 로 색인 노드를 골라 최근 재시작한 쓰기 노드가 빠졌음 → 시간당 색인량으로 고름
- DIF-009: 모든 노드를 한 평균에 넣어 전용 master 노드가 평균을 끌어내렸음 → data 노드만, tier 별로 편중을 보고, 두 번들 사이에 재시작한 노드는 표에만 두고 합계에서 뺌
- ING-001: 실패가 하나라도 있으면 주의 → 파이프라인별로 노드 전체 실패를 합해 실패율을 계산. 1% 이상이면 주의, 아니면 참고. 근거 구분은 도구 판단으로 바뀜
- 콘솔: 한글을 두 칸으로 계산해 열을 맞춤
- 단일 번들 판정 룰 122개, 두 번들 비교 룰 11개(판정 ID 184개 + 비교 DIF-001~014)

### 실제 번들 검토 반영

hot/warm/cold/frozen 14노드 클러스터를 이 버전으로 단일 번들과 연속 번들로 분석했고, 틀리거나 오해를 부르는 결과를 고쳤습니다.

- 병목 요약: 원인 그룹에 주의 이상 판정만 있으면 원인으로 셌기 때문에 frozen 노드의 높은 heap 이나 warm 노드의 breaker 가 hot 노드 write 큐의 원인으로 나옴 → 증상이 특정 노드에 있으면, 노드를 지목하는 원인 판정은 그 노드나 같은 데이터 tier 의 다른 노드를 지목할 때만 셈(bulk 쓰기는 replica 를, 검색은 맞닿는 모든 샤드 복사본을 기다림). 노드를 지목하지 않는 판정은 그대로 셈. BRK-001, BRK-002, OS-003, DISK-008, FD-001, IP-001, HOT-005, PERF-009 가 대상 노드를 기록함
- PERF-013: 1코어 frozen 노드에서 search 스레드 2개 중 2개가 바쁘기만 해도 해당 → frozen 전용 노드는 대기 중인 검색도 있어야 해당. frozen 검색은 원래 스냅샷 저장소에서 읽도록 설계되어 있음
- DIF-008: 노드마다 따로 외삽해서, 17시간 동안 ILM 이동을 받은 warm 노드 하나가 "3.7일 후 가득"(심각)으로 나오고 같은 tier 다른 노드는 줄어듦 → tier 합계로 판정(tier 의 high watermark 까지 남은 바이트 / tier 의 시간당 증가량). 노드별 행은 남기고 tier 합계 행을 추가
- DIF-014: data 노드 10대 중 1대만 이름이 일치한 구간이 "최저" 속도가 됨 → 서로 다른 클러스터이거나 일치하는 data 노드가 절반 미만인 구간은 "판정 제외"로 표시하고 peak 와 최저 계산에서 뺌
- SET-005: tier 마다 다른 node.processors(4, 2, 1 코어)로 주의가 나옴 → 데이터 노드는 같은 tier 끼리만 비교
- COST-004: warm 노드에 있는 write 대상 하나 때문에 warm 이 수집 대상 tier 에 들어가 여유가 두 배로 잡힘 → hot tier 가 쓰기를 받으면 hot tier 만 셈(새 data stream 인덱스는 기본으로 hot 에 만들어짐)
- 노드별 변화 표: 반올림 값이 같은데 "1% → 1% ▼", 샤드 수가 "0.00" → 표시 값이 같으면 "=", 샤드 수는 정수, ML 노드는 "ml"

### 공식 문서 재대조

공식 기준으로 표기한 판정, 버전 분기, 설정 지식 베이스의 기본값을 현재 공식 문서(9.x)와 다시 대조했습니다. 문서에 없거나 버전마다 다른 부분은 Elasticsearch 소스로 확인했습니다.

- CLU-013: transient 설정을 "7.16 부터 deprecated" 로 적었음 → "7.16 부터 권장하지 않음"(7.16 마이그레이션 가이드는 deprecated 가 아니라고 함)
- JVM-002: 32GiB 를 공식 경계로 표기했음 → JVM 이 보고한 플래그(`using_compressed_ordinary_object_pointers`)로 판정. false 면 주의, true 면 크기와 관계없이 정상. 플래그가 없을 때만 30GB 이상 주의, 26GB 이상 참고(공식: 대부분 26GB 는 안전, 약 30GB 까지 가능)
- DISK-006: time_series 를 "기본 best_compression" 이라 제외했음 → 기본 codec 이 best_compression 인 것은 logsdb 뿐(Elasticsearch 소스 IndexMode)이라 time_series 도 점검
- DISK-007: `index.mapping.source.mode` 만 봤음 → 문서화된 매핑 파라미터 `"_source": {"enabled": false}` 도 mapping.json 에서 찾음. 기본값인 `stored` 는 더 이상 나열하지 않음
- IDX-013: `cluster.logsdb.enabled` 와 `logsdb.prior_logs_usage` 를 표시. 9.0 이전부터 logs 데이터가 있던 클러스터는 `cluster.logsdb.enabled` 기본값이 false 라 새 logs-*-* 인덱스도 standard 로 만들어짐. 권고에 이 설정을 켜는 방법을 추가하고, 필요한 구독이 없으면 원래 _source 를 저장한다고 안내
- CLU-015: closed 인덱스 샤드까지 셌음 → 공식 계산은 open 인덱스만 셈(closed 는 cat indices 로 판단). frozen 샤드는 노드가 아니라 인덱스 종류(partial 마운트)로 구분. 치명 기준(95%)은 도구 임계값으로 표기
- CLU-007: 데이터 노드 6대부터 전용 마스터 권고 → 10대부터(`dedicated_master_data_nodes`, 현장 기준). 공식 문서는 "노드가 몇 대를 넘으면" 이라고만 함
- SHD-010: heap 의 50% 에서 주의 → 추정치가 heap 보다 크면 주의(공식 기준), 50% 부터는 참고(도구 판단)
- MAP-006: nested 기본 한도를 50 으로 봤음 → 9.3 이후 만든 인덱스는 100, 그 전은 50(인덱스 버전 기준). 80% 기준은 도구 임계값으로 표기
- 디스크 워터마크: defaults 의 기본 max_headroom(200/150/100GB)을 그대로 썼음 → 8.5 부터, 그리고 워터마크를 직접 지정하지 않았을 때만 적용(공식)
- SYS-001, SYS-003: 모든 노드가 개발 모드(loopback transport 또는 single-node discovery)면 bootstrap check 가 적용되지 않으므로 치명을 주의로 낮춤
- HOT-001: 공식 문서가 핫스팟 지표로 쓰는 write·search 큐를 함께 표시
- CLU-019: 근거 구분을 공식 기준에서 도구 판단으로 변경(공식 문서에서 awareness 는 선택 사항)
- 설정 지식 베이스: `transport.compress` 는 static·노드 설정. 상황에 따라 달라지는 기본값을 계산: `thread_pool.write.queue_size` 는 9.2 부터 max(10000, 프로세서 수 x 750), `index.mapping.nested_fields.limit` 은 인덱스 버전별, `indices.breaker.total.limit` 는 use_real_memory 가 false 면 70%, `indices.recovery.max_bytes_per_sec` 는 전용 cold/frozen 노드에서 역할과 메모리별. 소스에만 있는 기본값은 따로 표기(`search.low_level_cancellation`, merge policy, `index.max_refresh_listeners`, `bootstrap.memory_lock`). `xpack.monitoring.collection.enabled` 는 deprecated 로 표기. 설정 23개의 참고 링크를 실제로 설명하는 페이지로 수정
- 참고 링크: JVM 판정은 JVM settings, GEN-001 은 index modules 와 페이지네이션 문서로. IDX-007, CFG-006, TPL-001, CLU-021 에 참고 문서 추가
- 문구: VEC-002(float 벡터만 해당, 9.1 부터 bbq_hnsw, 9.4 부터 라이선스에 따라 bbq_disk), SHD-001(8.3 경계 근거는 Elastic 블로그), SHD-011(ILM 은 기본으로 빈 인덱스를 롤오버하지 않음), SYS-001(1048576 권고는 8.15~8.17 문서부터), PERF-004(5분 비활성 기준은 소스), CLU-021(노드가 돌아오지 않을 때는 0 도 유효)
- `tests/test_doc_audit.py`, `tests/drive_branches.py` 시나리오 3개 추가. 임계값 4개: `dedicated_master_data_nodes`, `heap_oops_safe_bytes`, `max_shards_per_node_crit_pct`, `nested_fields_near_limit_pct`

### 검토했지만 넣지 않은 것

- hot threads 의 대기 시간("other")을 I/O 신호로 보기: 락 대기 시간도 포함됨
- 코어 수보다 높은 load average 를 I/O 대기로 보기: 컨테이너 안에서는 load 가 호스트 값일 수 있음(OS-001 참고)

## [0.13.0] - 2026-10-02

다른 진단 도구의 판정 기준과 비교해 빠져 있던 쓰기 경로·운영 판정을 추가했습니다. 공식 수치가 없는 임계값은 모두 `[도구]` 로 표기하고 `--thresholds` 로 바꿀 수 있습니다.

### 추가

- PERF-012(도구 판단): 노드별 flush·refresh·merge 평균 시간. flush 800ms / 1200ms, refresh 40ms / 70ms, merge 20초 / 40초 이상이면 참고 / 주의. frozen 전용 노드와 작업 수가 적은 항목은 제외
- SHD-016(주의, 도구 판단): tier 안에서 쓰기 대상 shard(write index, alias write index, 수집 시점에 색인 중인 index)가 일부 노드에 몰림. (최대 - 최소) / 평균 >= 0.5 이고 차이 3개 이상. SHD-006 은 전체 shard 수를 비교
- IDX-014(사실 보고): merge 가 밀려 색인이 throttle 됨. 수집 시점에 `is_throttled=true` 면 주의, 누적 throttle 시간만 있으면 참고
- IDX-015(주의, 공식 기준): shard 복제본당 미커밋 translog 가 `index.translog.flush_threshold_size`(8.8+ 기본 10GB, 이전 512MB) 이상. 1GB 같은 고정 기준은 기본값이 10GB 인 버전에서 오탐이라 쓰지 않음
- OS-007(주의, 도구 판단): 노드의 절반 이상이 6시간 안에 재시작. 누적 카운터 기반 판정이 짧은 기간만 반영한다고 알림
- DIF-013(주의): 비교 모드에서 두 번들의 cluster_uuid 가 다르거나(uuid 가 없으면 이름이 다르고 노드가 절반 미만 겹침) 다른 클러스터로 보이면 경고
- `tests/test_write_path.py`: 새 판정의 분기를 합성 데이터로 두 언어 모두 검증(외부 번들 불필요)
- 임계값 16개

### 변경

- CLU-017: 5분 이상 task 를 모두 주의로 표시 → action 별로 묶어 task 수와 가장 긴 실행 시간을 표시. 1시간 이상이면 주의, 5분 이상이면 참고. 모니터링·내부 task(`cluster:monitor/*`, `indices:monitor/*`, `internal:*`)는 24시간을 넘을 때만 보고. 쓰기 경로(bulk, reindex, update/delete by query, forcemerge, shrink/split/clone)를 구분해 표시. 실행 시간 정렬이 문자열 순으로 되던 문제도 수정
- MAP-004: ignore_dynamic_beyond_limit 가 없어 색인이 실패할 수 있는 인덱스를 표 앞에 표시(같은 사용률이면 integration 인덱스가 15행을 채워 가려지던 것), data stream template 관리 주체(`fleet:<package>` / `elastic`) 열 추가
- 14노드 9.5.3 실번들에서 확인한 오탐 정리
  - PERF-012: 쓰기 대상이 없는 warm 노드의 merge 평균(26~41초)이 Warning 으로 나오던 것 → 실제로 색인하는 노드만 판정(노드 index_total 이 가장 많이 색인한 노드의 10% 이상). 처음에는 data stream write index 보유 여부로 골랐지만, 이 번들의 warm 노드에 1월 이후 쓰기가 거의 없는 write index(`logs-gitlab.audit`, `logs-gitlab.pages`)가 있어 실제 색인량으로 바꿈. 쓰기가 없는 노드의 merge 는 force merge(ILM forcemerge, cold·frozen 의 searchable_snapshot 이 기본으로 앞 단계 tier 에서 하는 force merge, 수동 _forcemerge)나 rollover 직후 마무리 merge 라서 큰 segment 를 합치며, 평균이 긴 것이 스토리지가 느리다는 뜻이 아님. warm tier 라고 자동으로 force merge 를 하는 것은 아님
  - OS-001: ECH master 노드처럼 CPU 사용률 0% 인데 load average 가 높은 컨테이너 노드를 치명으로 판정하던 것 → 컨테이너 안의 load 는 호스트 값일 수 있으므로 cpu% 20% 미만이면 참고로만 표시
  - MAP-001·MAP-004: 읽기 전용인 searchable snapshot mount 가 표 앞을 차지하던 것 → 제외
  - PERF-001: 스냅샷 저장소에서 읽는 partial mount(frozen) 인덱스의 검색 지연을 판정하던 것 → 제외(FRZ-001 에서 다룸)
  - IDX-006: 실패 비율 열을 추가하고 비율 순으로 정렬
  - SHD-016: 쓰기 대상 중 indexing.index_total 이 0 인(오래 쓰기가 없는) write index 는 제외
- 단일 번들 판정 룰 114개, 두 번들 비교 룰 10개(판정 ID 176개 + 비교 DIF-001~013)

### 검토했지만 넣지 않은 것

- 디스크 read/write 지연(ms/op): nodes stats 의 `fs.io_stats` 에는 작업 수와 `io_time_in_millis` 만 있고 read/write 시간 필드가 없어 계산할 수 없음(Elasticsearch `FsInfo` 소스로 확인)
- OS 메모리 사용률 95% 이상: ES 노드는 filesystem cache 로 메모리를 거의 다 쓰는 것이 정상이라 상시 오탐
- old GC 1회 이상, heap 32GB 초과 추정, load1m 기준: 이미 시간당 비율(JVM-005), 실제 compressed oops 값(JVM-002~004), load15 기준(OS-001)으로 더 정확하게 판정 중
- Enterprise ERU 사용량: 계산식을 공식 문서로 확인한 뒤 판단

## [0.12.0] - 2026-10-02

### 추가

- SHD-013(주의, 도구 판단): 롤오버가 끝난 인덱스의 샤드가 2억건을 5% 넘게 초과하면 rollover 지연으로 보고. 원인 후보(ILM 정지·오류, poll_interval, `min_*` 조건, lifecycle 미연결)를 권고에 표시
- SHD-014(참고, 도구 판단): logsdb 인덱스의 최대 primary shard 가 30GB 이상 50GB 미만. 인덱스별로 data stream, 최대 shard 크기, 문서 수, 문서당 크기, 추정 rollover 조건, ILM 정책을 표로 보여 줌. 30GB 는 공식 수치가 아니라 Elastic 내부 논의를 따른 값이며, 근거(암묵 2억건 rollover, index sorting 의 merge 비용, force merge 여유 공간, 복구 시간)를 판정에 함께 표시
- SHD-015(참고, 공식 하한): logsdb data stream 에서 10GB 미만, 2억건 미만으로 롤오버된 인덱스가 5개 이상(max_age 등으로 끝난 인덱스). data stream 별로 작게 롤오버된 수, 중앙값 크기·문서 수, 가장 많은 rollover 조건을 표시(인덱스별로 보여 주면 실번들에서 1,000건이 넘어 data stream 단위로 묶음). 빈 인덱스는 SHD-011 에 맡김
- IDX-013(참고): 9.0 이상에서 write index 가 logsdb 가 아닌 `logs-*-*` data stream(8.x 에서 업그레이드하기 전부터 있던 data stream)
- ILM-007(참고): `max_primary_shard_docs` 가 2억건 초과(효과 없음)
- ILM-008(주의): 1 segment force merge(forcemerge `max_num_segments=1`, searchable_snapshot `force_merge_index`)를 하는 tier 의 여유 디스크가 가장 큰 primary shard 의 3배 미만
- ILM-009(참고, 도구 판단): force merge 단계에 24시간 이상 머문 인덱스와 force_merge thread pool 크기·대기 건수
- 임계값 7개: `docs_rollover_overshoot_pct`, `logsdb_shard_gb_high`, `logsdb_shard_gb_low`, `logsdb_rows_max`, `ilm_implicit_max_shard_docs`, `forcemerge_free_space_factor`, `forcemerge_stuck_hours`
- index mode 판별: `settings.json` 의 `index.mode`, 없으면 `data_stream.json` 의 `index_mode`
- `tests/test_logsdb.py`: 새 판정의 모든 분기를 합성 데이터로 두 언어 모두 검증(외부 번들 불필요)

### 변경

- SHD-008: 2억건 이상이면 모두 주의 → write index 와 rollover 를 쓰지 않는 인덱스만 주의. 롤오버가 끝난 인덱스는 5% 이내 초과면 판정하지 않음(rollover 는 2억건에서 항상 실행되고 ILM 은 10m 마다 확인하므로 조금 넘는 것은 정상, 공식 ILM rollover 문서)
- SHD-008 권고: "max_primary_shard_docs 를 함께 지정" → ILM 적용 시 2억건에서 자동 rollover 됨을 안내(지정하지 않아도 암묵 적용되므로)
- ILM-004 권고: 문서 수 조건은 지정하지 않아도 2억건이 암묵 적용됨을 추가
- SHD-008: searchable snapshot mount(restored-, partial-)는 쓰기가 없으므로 롤오버된 인덱스와 같이 판정(SHD-013 기준)
- 단일 번들 판정 룰 110개, 두 번들 비교 룰 9개(판정 ID 171개 + 비교 DIF-001~012)

### 수정

- `tests/drive_branches.py`: 시나리오가 처음 만든 번들(3노드 ECH, 2026-08-14 수집)을 전제로 해 다른 번들에서 10~16건 실패하던 것 → 수집 시각을 2026-08-14 로 고정(인증서·라이선스·스냅샷 날짜 기준), 1노드 번들은 3노드로 복제, master 역할 시나리오는 나머지 노드의 master 를 제거, 디스크 시나리오는 100GB 디스크로 고정(max_headroom 영향 제거), 인덱스 추가는 첫 data 노드에, shard 편중·replica 과다 시나리오는 번들 규모에 맞춰 수치를 키움. 디스크 시나리오는 frozen 이 아닌 data 노드를 쓰고 사용자 정의 watermark 를 지움, shard 한도 시나리오는 노드당 1개로, SLM 시나리오는 정책을 직접 넣음
- DISK-008: 장치 카운터가 JVM uptime 과 맞지 않아 평균 사용률이 음수나 100% 초과로 나오던 것(실번들의 ECH hot·frozen 노드에서 -131%, -198%) → "확인 불가"로 표시하고 판정에서 제외

## [0.11.0] - 2026-10-01

### 추가

- 영어 지원. 콘솔·Markdown·HTML·JSON·Support 팀 요약이 한국어와 영어로 나옵니다. 사용자에게 보이는 문구는 `esdiag/i18n/ko.txt` 와 `en.txt` 카탈로그로 옮겼고, 카탈로그는 `pkgutil` 로 읽으므로 `esdiag.pyz` 와 단독 실행 파일에서도 동작합니다
- `--lang both|ko|en|auto`(기본 `both`): `both` 는 두 언어를 모두 쓰고 파일명에 `.ko` / `.en` 을 붙임(`report.html` → `report.ko.html`, `report.en.html`). `ko` / `en` 은 지정한 이름 그대로 한 언어만 씀. 콘솔 언어는 로캘 또는 `ESDIAG_LANG`. 번들은 한 번만 열고, 마스킹 매핑 파일도 한 번만 씀
- JSON 에 언어와 무관한 ID 추가: `category_id`, `basis_id`, `grade_id`, 영역별 `area_id` / `status_id` / `category_ids`. 리포트 문구가 아니라 이 값으로 처리하십시오
- `RULES.md`(영어)와 `RULES.ko.md`(한국어). 둘 다 `tools/gen_rules_doc.py` 가 카탈로그에서 생성(`--lang`, `--check`)
- `README.md` / `COVERAGE.md` / `CHANGELOG.md` 는 영어, 한국어는 `*.ko.md`
- `docs/STYLE.md`: 문체·용어·placeholder 규칙. `tests/i18n_check.py`: 두 카탈로그의 키 일치, `%` 필드, HTML 태그, 대시, 금지 표현 검사

### 변경

- 코드 주석·docstring·테스트·도구 스크립트를 영어로 전환. 한국어 출력은 바이트 단위로 이전 버전과 같음(합성 번들 3종으로 비교)
- 판정 로직이 한국어 문자열에 의존하던 곳을 언어 중립 ID 로 교체(카테고리, 등급, 영역, 근거 구분)
- 콘솔 영역 표의 열 너비를 코드에서 계산(영어 라벨이 길어도 정렬 유지)

## [0.10.0] - 2026-09-29

### 추가

- `--support-summary FILE`: Elastic 공식 Support 팀 문의 시 케이스에 붙일 요약 Markdown. 지정한 때만 생성. 치명·주의 판정의 관측·근거 구분·근거 파일·근거 표를 담고, 조치 권고·서버 로그 발췌·hot threads 스택은 담지 않음
- `--mask none|basic|strict`(기본 basic): 요약의 식별자를 별칭(`node-001` 등)으로 치환. basic 은 클러스터·노드·호스트·IP·경로·인증서·라이선스·저장소, strict 는 인덱스·정책·템플릿 등 추가
- `--mask-map FILE`: 별칭 ↔ 원래 이름 매핑(권한 0600). 기본 경로는 요약 파일명 + `.mask-map.json`
- 마스킹 후 원본 식별자나 미등록 IPv4 가 남으면 요약과 매핑을 쓰지 않고 종료 코드 2
- `tests/test_handoff.py`: 카나리 식별자 기반 합성 검증(외부 번들 불필요)

### 변경

- README 문구: "Elastic Support" → "Elastic 공식 Support 팀". README 의 포맷 문자열 검사 건수를 실제 값으로 수정

## [0.9.3] - 2026-09-29

최종 점검(두 local 번들, Python 3.8.20 / 3.12, HTML 데스크톱·모바일 렌더링)에서 확인된 사항 반영.

### 변경

- 조치 우선순위: 판정마다 1줄 → 같은 원인 묶음(샤드 미할당: CLU-001·002·003·004.shards_availability·IDX-002, 디스크 워터마크: DISK-001~003·CLU-004.disk)을 대표 1건 + 관련 판정으로 표시. 콘솔·Markdown·HTML·JSON(`priority`) 공통. 본문 판정은 그대로
- 조치 우선순위 정렬: 같은 심각도 안에서 카테고리 이름 가나다순 → 보고서 영역 순서(가용성 → 자원 → … → 구성)
- SYS-001: 262144 이상이면 정상 → 262144 미만 치명(bootstrap check), 1048576 미만 참고(공식 권고값: 기본값이 1048576 보다 낮으면 1048576 으로 설정), 이상 정상
- CLU-003: allocation explain 의 일반 안내문 원문 → 대상 샤드와 거부한 decider 이름(예: `test-index[0] replica: can_allocate=no. 거부한 decider: same_shard`)
- 수집 시각: ISO 원문 → `2026-09-29 03:34:09 UTC (한국 시간 2026-09-29 12:34)`. JSON 의 `collected_at` 은 그대로 두고 `collected_display` 추가

### 수정

- 영역별 점검 결과: `OS 설정`(SYS-001~004) 카테고리가 어느 영역에도 속하지 않아 집계에서 빠지던 것 → `구성` 영역에 포함
- `--no-ok`: 판정 건수·영역 요약에서 정상이 0 으로 표시되던 것 → 화면에서만 숨기고 건수에는 포함
- `--only`: 도움말의 모듈 목록이 오래되어 settings·sharding·deep·syscalls 가 빠져 있고 오타를 넣으면 아무 룰도 실행하지 않던 것 → 실제 모듈 목록에서 생성, 잘못된 이름은 오류
- 권고 문구의 백틱(`)이 HTML 에 그대로 보이던 것 제거, SYS-001~003 에 공식 문서 링크 추가
- CLU-024: 값이 없을 때 "전체 상태 크기 -." 처럼 빈 값이 표시되던 것 → 있는 값만 표시
- 조치 우선순위의 긴 관측값이 말줄임표 없이 잘리던 것 → `…` 표시

### 검증

- `tests/test_local_mode.py`: 13개 → 18개(SYS-001 권고값 구간, `--no-ok` 건수, 우선순위 묶음)
- Python 3.8.20 과 3.12 에서 두 번들 판정 결과 동일 확인

## [0.9.2] - 2026-09-29

### 추가

- 단일 번들 판정 룰 107개, 두 번들 비교 룰 9개(판정 ID 164개 + 비교 DIF-001~012)
- `syscalls/` 분석(local/remote 모드): SYS-001 vm.max_map_count(최소 262144), SYS-002 swap 이 있을 때 vm.swappiness, SYS-003 ES 프로세스 nofile 65535 / nproc 4096, SYS-004 dmesg 의 커널 OOM killer 기록

### 검증

- 검증 범위 확대: api 모드에 더해 local 모드(self-managed 8.19.21 단일 노드) 실번들 검증. remote·다중 노드 local 은 미검증
- `tests/test_local_mode.py` 추가: 외부 번들 없이 합성 데이터로 local 모드 분기 13개 단정 (LOG-001 오탐이 되살아나면 실패하는 것 확인)

### 수정

- LOG-001: 기동 로그의 JVM 옵션 줄(`-XX:+ExitOnOutOfMemoryError` 등)을 OutOfMemoryError 로 잡아 치명으로 판정하던 것 → 기동 옵션 줄 제외 (실번들에서 확인된 오탐)
- 로그 스캔: `.log.gz` 를 압축 해제 없이 읽던 것 → 해제 후 스캔, `gc.log*`(JVM 로그)와 `*_server.json`(같은 내용의 JSON 판)은 스캔 대상에서 제외, `translog` 단어 매칭 → `failed to flush` 로 축소

## [0.9.1] - 2026-09-29

### 변경

- 배포 형태 감지: `node.store.allow_mmap` 설정만 있으면 ECK 로 판정하던 것 → 제외 (self-managed 에서도 흔한 설정이라 CFG-*·SET-004 가 참고로 잘못 내려감)
- CLU-006: 마스터 후보 4대 이상 짝수를 주의로 보던 것 → 판정 안 함 (공식: 짝수면 ES 가 투표 구성에서 1대를 제외하며 내결함성은 줄지 않음). 2대는 치명 → 주의
- TP-001: 누적 rejection 1,000건 이상이면 치명 → 수집 시점에 해당 풀 queue 가 남아 있을 때만 치명, 그 외 주의
- BRK-001: 발동 이력만으로 치명 → 수집 시점 사용률 70% 이상일 때만 치명, 그 외 주의
- SNP-002: 실패/부분 스냅샷이 있으면 치명 → 그 뒤에 성공 스냅샷이 있으면 주의
- IDX-002: 치명 → 주의 (primary 는 정상이고 복제본만 미할당)
- SEC-002: 모든 노드가 loopback 에만 바인딩되어 있으면 주의로 하향
- IDX-005: 존재하지 않는 `indices.store.throttle` 설정을 안내하던 권고 문구 수정
- OS-002: swap 사용량을 함께 보고
- LOG-000: local / remote 로 수집했으나 대상 노드 매칭 실패로 syscalls·logs 가 빠진 경우 `diagnostics.log` 를 근거로 원인과 재수집 방법 안내
- RULES.md 생성기: 제목이 조건식인 룰의 빈 제목, DISK-008 의 `%%` 표기, 임계값 주석 혼입 수정
- `tests/check_docs.py`: README 표의 markdown escape(`SET-\*`) 때문에 실패하던 검사 수정

## [0.9.0] - 2026-09-22

첫 공개 버전(0.9.0)입니다. 1.0 전까지는 판정 기준·출력 형식이 바뀔 수 있습니다. **이 도구는 api 모드 진단 번들로 검증되었습니다. local / remote 모드(서버 로그·OS 명령 결과 포함) 번들은 파일 구성이 달라 확인이 필요할 수 있습니다.** 판정 기준은 Elasticsearch 9.4 공식 문서(2026-09 대조)입니다.
실번들 검증은 9.4.4(Elastic Cloud Hosted, 3노드 단일 tier)로 했고, 9.5.3 다중 tier(hot/warm/cold/frozen) 클러스터의
실행 결과로 오탐·미탐을 교정했습니다.

### 추가

- 단일 번들 판정 룰 106개, 두 번들 비교 룰 9개(판정 ID 160개 + 비교 DIF-001~012)
- 모든 판정에 근거 구분 표기: 공식 기준 / 사실 보고 / 도구 판단 / 비교 계산
- 설정 변경 분석(SET-001~006)과 설정 지식 베이스 94종(기본값·dynamic/static·의미·방향별 영향)
- 과다 샤딩 분석(OVS-001~003), tier 전체 CPU 포화(HOT-005)
- `--baseline` 비교 모드: 누적 카운터를 증가분·시간당 발생률로 판정, 디스크 포화 예상일, 판정 변화(신규/악화/해소)
- 입력 미수집 처리: 필요한 파일이 없으면 판정하지 않고 "확인하지 못함" 으로 기록
- 룰 격리: 룰 하나가 실패해도 나머지 판정과 리포트 생성은 계속, 실패 룰은 "도구 오류로 판정하지 못한 항목" 에 기록
- 배포 형태 감지(ECH/ECE/ECK/self-managed): 오케스트레이터 관리 설정은 참고로 하향
- 버전 기준점과 VER-001(기준보다 새 버전 분석 시 알림)
- 단일 파일 배포본 `esdiag.pyz`, 단독 실행 파일 빌드 스크립트, `--check-env`
- `RULES.md` 자동 생성기(코드에서 조건·임계값·입력·문서를 추출)
- 검증 도구: 계산 로직 단정문, 판정 분기 구동, 입력 변형 퍼징, 포맷 문자열 정적 검사, 전체 실행 스크립트

### 헬스 체크 관점 최종 조정

- 리포트 맨 앞에 **영역별 점검 결과** 추가: 가용성 / 자원·용량 / 데이터 구조 / 성능 / 데이터 보호·운영 / 보안 / 구성(콘솔·Markdown·HTML·JSON 공통)
- 판정 분류 순서를 헬스 체크 우선순위로 변경(가용성 → 자원 → 데이터 구조 → 성능 → 데이터 보호 → 보안 → 구성). 대부분 참고인 설정 변경이 앞에 오던 순서를 조정
- 모니터링 구성 확인 추가(OPS-007): 클러스터 안의 모니터링 데이터 유무와 별도 모니터링 클러스터 확인 안내
- ILM-002: 모든 ILM 오류를 치명 → 롤오버 단계 실패만 치명(write index 가 계속 커짐), 그 외 단계·write index 삭제 실패는 주의
- IDX-006: 버전 충돌은 정상 운영에서도 증가한다는 해석 안내 추가

### 번들 활용 확대 (제로베이스 점검)

진단 번들 104개 파일을 전수 대조한 결과 53개를 읽지 않고 있었습니다. 안정성 판단에 쓰이는 사실을 담은 파일을 추가로 활용해 현재 62개를 씁니다.

- `mapping.json`: 필드 수 한도 근접(MAP-004), text 필드 fielddata(MAP-005), nested 한도(MAP-006), 실제 인덱스의 비양자화 벡터(VEC-005)
- `ilm_policies.json`: 크기 기준 없는 롤오버(ILM-004, 롤오버 과다의 원인), 롤오버 기준 50GB 초과(ILM-005), 삭제 단계 없음(ILM-006)
- `cluster_state.json`: voting config exclusion 잔존(CLU-022)
- `nodes_shutdown_status.json`: 종료 정체·레코드 잔존(SHUT-001)
- `shard_stores.json`: 저장소 예외(IDX-012)
- `remote_cluster_info.json`: 원격 클러스터 연결 끊김(OPS-003)
- `searchable_snapshots_cache_stats.json`: frozen shared cache 교체 과다(FRZ-001)
- `nodes_stats`: 스크립트 컴파일 한도 발동(PERF-010), ingest processor 별 시간(ING-002), 클러스터 상태 발행 실패·크기(CLU-024), 디스크 I/O 사용률(DISK-008)
- `nodes.json`: 노드 간 플러그인 불일치(CLU-023)
- `slm_policies.json`: `snapshot.json` 이 시각 없는 목록 형식이면 SLM 의 마지막 성공 시각으로 RPO 산정(이전에는 RPO 판정 자체가 빠짐), 마지막 실패가 마지막 성공보다 최근인 정책(SNP-007, 지금 백업 실패 중)
- `ml_trained_models_stats.json`, `watcher_stack.json`, `autoscaling_capacity.json`, `rollup_jobs.json`: 모델 배포 이상(ML-003), watcher 수동 중지(OPS-005), 오토스케일링 요구 용량(OPS-004), deprecated rollup(OPS-006)

### 9.5.3 번들 검증 (두 번째 실번들)

- 파일 구성은 9.4.4 와 동일(104개). 주요 파일의 필드 구조를 대조해 9.5 에서 추가된 설정(ES|QL·telemetry)은 판정 무관으로 확인
- `cluster_stats.indices.search` 의 쿼리 유형별 사용 횟수를 활용해 비용이 큰 검색 패턴 비중 판정 추가(PERF-011). 이전 문서의 "쿼리 관련 판정 불가" 를 "유형 비중은 판정, 인덱스 특정은 불가" 로 정정
- hot threads 분류를 2단계로 변경: 작업 성격을 결정하는 호출(grok·painless·무시된 필드 저장 등)을 스택 전체에서 먼저 찾고, 없으면 위쪽 프레임부터 분류. 맨 위가 JSON 복사인 문서 파싱 스레드가 "JSON 직렬화" 로 잘못 분류되던 문제 수정. 파싱 프레임 수 12 → 40
- **메모리**: 대형 번들에서 분석 1회 최대 3.3GB → 약 0.9GB, 17초 → 7초. cluster_state 는 필요한 배열만 잘라 파싱, mapping 은 인덱스 단위로 파싱·요약 후 폐기, 원문 문자열 캐시 제거, 숫자 정규화를 제자리 변환으로
- 테스트 픽스처가 3노드 번들을 전제하던 부분(노드 재배정·인덱스 설정 복사·기대값 계산)을 번들 무관하게 수정. 두 번들 모두 단정문 55개 통과, 설정 지식 베이스 기본값이 9.5.3 보고값과도 일치

### 문서 사실 오류 정정

- "api 모드에는 인덱스별 매핑이 없다" → 틀린 서술. api 모드 번들에도 `mapping.json`(`GET _mapping`)이 있으며 이제 판정에 사용합니다.

### 판정 기준 교정 (공식 문서·ES 동작과 불일치하던 것)

| 항목 | 이전 | 현재 | 근거 |
| --- | --- | --- | --- |
| 디스크 워터마크 | 85/90/95% 고정 | max_headroom(200/150/100GB) 반영한 실효 워터마크 | 번들의 ES 보고 기본값, 할당 설정 문서 |
| frozen 전용 노드 디스크 | low/high 적용 → shared cache 선점유(90%)를 치명으로 판정 | `flood_stage.frozen`(95%, headroom 20GB)만 적용 | frozen tier 동작 |
| heap 1GB당 샤드 20개 | 전 버전 적용 | 8.3 미만만 적용 | 8.3 릴리스에서 공식 폐기, 필드 매퍼 heap 산정으로 대체 |
| heap/RAM | 55% | 50% (+2%p 오차 허용) | Important settings |
| 대형 샤드 | 60GB | 50GB | Size your shards (10~50GB) |
| refresh_interval | 미지정 인덱스도 판정 | 1초 이하를 명시한 경우만 | 미지정 시 search idle 로 refresh 생략 |
| swap | swap 존재 시 경고 | memory_lock 적용 시 제외 | swap 대책 3가지 중 하나 충족 |
| GC 로그 | `-Xlog:disable` 있으면 꺼짐으로 판정 | 마지막 disable 이후 gc 파일 로깅 유무 | JVM 옵션 적용 순서 |
| dense_vector 양자화 | index_options 미지정도 경고 | 비양자화(hnsw/flat) 명시만 | 8.14 기본 int8_hnsw, 9.1 384차원 이상 bbq_hnsw |
| codec | 모든 대형 인덱스 | logsdb·time_series 제외 | 해당 모드는 best_compression 기본 |
| allow_rebalance 기본값 | indices_all_active | always | 9.4.4 가 yml 없이 보고한 값(교차 검증) |
| search 큐 기본값 | 1000 고정 | 자동 산정(스레드 수 × 1000, 9.4.4 관측) — 명시 사실만 보고 | 번들 ES 보고값 |
| 스냅샷 RPO | 진행 중·실패 스냅샷 시각까지 '마지막 스냅샷' 으로 사용 | 마지막 성공(SUCCESS) 스냅샷 기준, 성공 없으면 치명 | 복구 가능한 백업만 RPO 에 해당 |

### 오탐 제거

| 항목 | 이전 | 현재 |
| --- | --- | --- |
| 쓰기 차단(IDX-008) | 차단된 모든 인덱스를 치명(롤오버된 백킹 인덱스 1,634개 등) | 현재 쓰기 대상·flood stage 차단만 치명, 롤오버 완료·searchable snapshot 은 정상, 단독 인덱스는 참고(IDX-011) |
| 노드 비교(스펙·샤드 수·자원·작업량) | 전체 데이터 노드를 한꺼번에 비교 | 같은 tier 끼리만 비교, tier 간 차이는 NODE-003 참고 표 |
| 시스템 인덱스 판별 | `.` 시작 전부 시스템 → `.ds-*` 사용자 데이터 누락 | `.ds-<이름>` 은 데이터 스트림 이름 기준으로 판별 |
| hot threads | 대기 시간 포함 %, 시그니처 목록 순서로 분류, 치명 가능 | `cpu=` 값만 사용, 최상위 프레임부터 분류, 500ms 스냅샷이라 최대 주의 |
| 매핑 heap(SHD-010) | 마스터·ML 노드 포함 | 데이터 노드만(공식 산정식 대상) |
| 필드 한도(MAP-001) | 모두 주의 | ignore_dynamic_beyond_limit=true 면 참고 |
| 전체 필드 수(MAP-002) | 주의 | 참고(인덱스별 합계라 공식 기준 없음) |
| 부분 번들 | 파일 미수집을 '미설정' 으로 판정(예: 스냅샷 저장소 없음 치명) | 입력 미수집이면 판정하지 않음 |
| 설정 이중 판정 | ARS 등이 SET-001 과 전용 룰에서 중복 | 전용 룰 설정은 `[판정: 룰ID]` 표기, SET 심각도에서 제외 |
| 빈 인덱스(SHD-011) | 막 롤오버된 write index 포함 | 현재 쓰기 대상 제외 |
| node.processors | 명시만 해도 변경으로 보고 | 실제 할당 CPU 와 같으면 변경 아님 |
| 버전 알림(VER-001) | 주의(조치 목록에 포함) | 참고 |
| 과다 샤딩(OVS-001) | 샤드당 50GB 미만이면 과다 | 공식 하한 10GB 미만일 때만, 권장 개수는 상한 50GB 로 산정 |

### 미탐 보완

| 항목 | 이전 | 현재 |
| --- | --- | --- |
| OS-001 | 위험 노드가 있으면 주의 노드를 목록에서 누락 | 위험·주의 구간 노드를 모두 표시 |
| tier 전체 포화 | tier 비교로 바꾼 뒤 신호 소실 | HOT-005 로 별도 판정(편중이 아닌 용량 부족) |
| fully mounted(cold) 인덱스 | searchable snapshot 전체를 크기 판정에서 제외 | partial(frozen)만 제외, fully mounted 는 실제 크기라 포함 |
| 컴포넌트 템플릿 | `composed_of` 가 병합되지 않음 → MAP-003·VEC-002·VEC-003 이 컴포넌트 매핑을 보지 못함 | 병합 정상화 |
| TPL-001 | 패턴 목록이 걸러져 발생 불가 | 정상 동작, 대상도 '레거시 템플릿이 composable 에 가려지는 경우' 로 재설계(동일 priority 중복은 ES 가 생성 거부) |

### 견고성

- `BRK-002` 의 `"70% 이상"` 이 `%` 포맷 지정자로 해석되어 실행 시 오류 → `%%` 로 수정, 코드 전체 포맷 문자열 정적 검사 도입
- 번들 파일 형식이 다르면 분석 시작 단계에서 전체가 멈추던 경로 제거
- 통계 파일의 숫자 문자열을 적재 시 숫자로 정규화, 숫자·dict·문자열 목록 안전 접근자 도입
- 인덱스 수 × 샤드 수 반복 제거(인덱스 2만·샤드 6만 규모 대응)
- 오타 난 임계값 키를 조용히 무시하던 동작 → 경고
- 사용하지 않는 임계값 12개 제거(조정해도 효과가 없던 값)

### 리포트

- 가중치 점수 제거(공식 기준 없는 임의 산식, 대형 클러스터에서 0점) → 건수 기반 종합 판정만 표시
- 영역 필터가 앵커 이동이라 샌드박스 뷰어에서 동작하지 않음 → 심각도 × 영역 조합 필터 버튼
- 룰 실행 오류가 본문에 그대로 노출 → 하단 "도구 오류로 판정하지 못한 항목" 에 요약, 추적 정보는 접어서 표시. Markdown 에도 포함
- 노드 상태 매트릭스, 저장 용량 상위 인덱스, 심각도 분포 막대, 인쇄용 스타일
