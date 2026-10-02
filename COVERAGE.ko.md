# 공식 가이드 대비 점검 항목 커버리지

> Elastic 공식 문서의 항목이 어떤 룰로 반영되었는지(또는 왜 판정할 수 없는지)를 정리한 표입니다.
> 각 룰의 정확한 판정 조건·임계값은 [RULES.ko.md](RULES.ko.md), 변경 이력은 [CHANGELOG.ko.md](CHANGELOG.ko.md) 를 참조하십시오.
> 기준 버전: Elasticsearch 9.4 공식 문서(2026-09 대조).
> 검증 범위: **api 모드**(ECH 9.4.4·9.5.3)와 **local 모드**(self-managed 8.19.21 단일 노드) 실번들로 검증되었습니다. remote 모드와 다중 노드 local 모드는 아직 검증하지 않았습니다.

Elastic 공식 문서의 항목을 하나씩 대조해, 진단 번들로 판정 가능한 것은 룰로 구현하고
번들에 수집되지 않는 항목은 한계로 명시했습니다.

표기
- **구현**: 룰로 자동 판정
- **부분**: 일부 신호만 판정 가능(간접 지표)
- **불가**: 진단 번들에 해당 데이터가 없음 → 리포트에서 다루지 않음(현장 확인 필요)

---

## 1. Important settings configuration
`https://www.elastic.co/docs/deploy-manage/deploy/self-managed/important-settings-configuration`

| 문서 항목 | 상태 | 룰 |
| --- | --- | --- |
| Bootstrap checks (dev vs production mode) | 구현 | CFG-006 (실제 바인딩 주소 transport_address 가 loopback 이거나 single-node) |
| Path settings (path.data / path.logs 가 $ES_HOME 밖) | 구현 | CFG-002 (archive 설치에만 적용) |
| Multiple data paths (deprecated) | 구현 | CFG-003 |
| Cluster name setting | 구현 | CFG-001 (기본값 elasticsearch 사용 감지) |
| Node name setting | 부분 | 노드 요약 표에 표기(기본값=hostname 이 정상이라 경고 대상 아님) |
| Network host settings | 구현 | CFG-006 |
| discovery.seed_hosts | 구현 | CFG-004 |
| cluster.initial_master_nodes 제거 | 구현 | CFG-005 |
| Heap size settings | 구현 | JVM-002(32GB 경계), JVM-003(RAM 대비), JVM-004(Xms≠Xmx) |
| JVM heap dump path | 구현 | CFG-007 |
| GC logging settings | 구현 | CFG-008 |
| JVM fatal error log (ErrorFile) | 구현 | CFG-009 |
| Temporary directory settings | 불가 | $ES_TMPDIR 값이 번들에 없음 |
| Cluster backups (snapshot / SLM) | 구현 | SNP-001~006 |
| DNS cache settings | 부분 | JVM 인자에 있으면 확인 가능하나 기본값 권장이라 룰 없음 |

ECH/ECE/ECK 배포로 감지되면 위 CFG 항목은 오케스트레이터 관리 영역이므로 심각도를 참고로 낮추고
그 사실을 리포트에 명시합니다.

---

## 2. Size your shards
`.../production-guidance/optimize-performance/size-shards`

| 문서 항목 | 상태 | 룰 |
| --- | --- | --- |
| 샤드 크기 10~50GB | 구현 | SHD-003(50GB 초과), SHD-002(200GB 초과, 도구 기준), SHD-004(소형), SHD-005(평균), OVS-001~003(과다 샤딩) |
| 샤드당 문서 200M 이하 | 구현 | SHD-008(write index·rollover 미사용 인덱스), SHD-013(롤오버된 인덱스가 2억건을 크게 넘음: rollover 지연) |
| Lucene MAX_DOC(2,147,483,519) 한계 | 구현 | SHD-007 (docs.count + docs.deleted 기준) |
| 샤드 분포 / unbalanced cluster / hot spotting | 구현 | SHD-006·DISK-005(같은 tier 내 비교), HOT-003(desired balance 미수렴) |
| 검색은 샤드당 1스레드 → 샤드 과다 시 스레드풀 고갈 | 구현 | TP-001, CLU-015 (SHD-001 은 8.3 미만 전용) |
| 인덱스·샤드·세그먼트·필드별 오버헤드 | 구현 | IDX-004(세그먼트), MAP-001/002 |
| 마스터 heap 1GB당 인덱스 3000개 | 구현 | SHD-009 |
| cluster shard limit (1000/노드, frozen 3000) | 구현 | CLU-015 |
| 필드 매퍼 heap 여유(cluster state + 노드 오버헤드 + 0.5GB) | 구현 | SHD-010 |
| total_shards_per_node 로 핫스팟 방지 | 구현 | SHD-012 |
| 불필요한 동적 필드 회피 | 구현 | MAP-003 |
| 데이터 스트림 + ILM 사용 | 구현 | ILM-003, IDX-010 |
| 빈 인덱스 삭제 | 구현 | SHD-011 |
| force merge / shrink / reindex 통합 | 구현 | IDX-003, IDX-004 권고에 포함 |
| 문서 삭제 대신 인덱스 삭제 | 구현 | IDX-003 (삭제 문서 비율) |

---

## 3. Tune for indexing speed
`.../optimize-performance/indexing-speed`

| 문서 항목 | 상태 | 룰 |
| --- | --- | --- |
| Bulk 요청 사용 / 크기 조절 | 부분 | IP-001(indexing pressure rejection), TP-001(write rejection)로 과부하 신호 판정 |
| 다중 워커 사용, 429 감시 | 구현 | TP-001, IP-001 |
| refresh_interval 상향 | 구현 | IDX-007 |
| 초기 적재 시 replica 0 | 부분 | IDX-001 로 replica 0 인덱스를 표시(의도적 설정 여부는 사람이 판단) |
| swap 비활성화 | 구현 | OS-002, OS-005 |
| 파일시스템 캐시에 메모리 확보 | 구현 | JVM-003 |
| auto-generated id 사용 | 불가 | 색인 요청 내용이 번들에 없음 |
| 빠른 하드웨어(SSD), 로컬 vs 원격 스토리지 | 구현 | PERF-009, IDX-005(merge throttling) |
| indices.memory.index_buffer_size (샤드당 최대 512MB) | 구현 | PERF-004 |
| CCR 로 검색/색인 자원 분리 | 부분 | OPS-002 로 CCR 오류만 판정 |
| hot spotting 회피 | 구현 | HOT-001·HOT-002(같은 tier 내 편중), HOT-005(tier 전체 포화), SHD-006, SHD-012 |

---

## 4. Tune for search speed
`.../optimize-performance/search-speed`

| 문서 항목 | 상태 | 룰 |
| --- | --- | --- |
| 파일시스템 캐시에 메모리 확보 | 구현 | JVM-003 |
| readahead 값(128KiB) | 불가 | api 모드 번들에 없음. local / remote 모드의 `syscalls/readahead.txt`(lsblk RA)에 있으나 아직 미구현 |
| 빠른 하드웨어 / 로컬 스토리지 | 구현 | PERF-009 |
| 문서 모델링(nested·join 회피) | 부분 | PERF-011(nested·has_child·has_parent 사용 비중), MAP-006(nested 필드 수). 인덱스 특정은 불가 |
| 검색 대상 필드 최소화(copy_to) | 불가 | 쿼리 본문이 번들에 없음 |
| 사전 색인(pre-index) | 불가 | 동일 |
| 식별자를 keyword 로 매핑 | 부분 | 템플릿 매핑 범위에서만 확인 가능 |
| 스크립트 회피 | 부분 | PERF-011(script·script_score·script_fields·runtime_mappings 사용 비중), RT-001(painless 스택 분류) |
| 날짜 반올림으로 캐시 활용 | 구현 | PERF-003 (캐시 적중률 + eviction 으로 역추적) |
| 읽기 전용 인덱스 force-merge | 구현 | IDX-004 |
| global ordinals 예열 | 구현 | FD-001/002, RT-001(GlobalOrdinals 스택 분류) |
| index.store.preload | 구현 | PERF-008 |
| index sorting | 불가 | 권장 사항이며 판정 기준이 워크로드 의존 |
| preference 로 캐시 활용 | 부분 | PERF-003 |
| replica 수와 처리량 관계 | 구현 | PERF-007 (공식 권장식 적용) |
| ES\|QL 최적화 | 불가 | 쿼리 본문 필요 |
| Search Profiler | 불가 | 런타임 도구 |
| index_phrases / index_prefixes / constant_keyword | 불가 | 매핑·쿼리 상세 필요 |
| search.default_search_timeout | 구현 | PERF-006 |
| open search contexts 과다 | 구현 | PERF-005 |

---

## 5. Tune approximate kNN search
`.../optimize-performance/approximate-knn-search`

| 문서 항목 | 상태 | 룰 |
| --- | --- | --- |
| 벡터 메모리 사용량 축소(양자화) | 구현 | VEC-002 (384차원 이상 float 에 양자화 없음) |
| 벡터 차원 축소 | 구현 | VEC-002 근거 표에 dims 표기 |
| _source 에서 벡터 제외 | 구현 | VEC-003 (exclude_source_vectors 권장) |
| 데이터 노드 메모리 충분 여부(HNSW/DiskBBQ) | 구현 | VEC-001 (벡터 off-heap 합계 vs RAM-heap) |
| 파일시스템 캐시 예열(preload) | 구현 | PERF-008 (과다 사용 경고 포함) |
| 세그먼트 수 축소 / max_merged_segment 상향 | 구현 | VEC-004 |
| 대량 적재 시 큰 세그먼트 생성 | 구현 | VEC-004 권고에 포함 |
| GPU 가속 색인 | 불가 | 하드웨어 구성 정보 없음 |
| 검색 중 대량 색인 회피 | 부분 | PERF-002 + VEC-004 조합으로 신호 판정 |
| readahead | 불가 | api 모드 번들에 없음. local / remote 모드 `syscalls/readahead.txt` 는 아직 미구현 |
| on_disk_rescore | 구현 | VEC-001 권고에 포함 |

---

## 6. Tune for disk usage
`.../optimize-performance/disk-usage`

| 문서 항목 | 상태 | 룰 |
| --- | --- | --- |
| 불필요한 기능 비활성(index:false, match_only_text) | 부분 | 템플릿 매핑 범위에서만 확인 |
| 기본 동적 문자열 매핑 회피 | 구현 | MAP-003 |
| 샤드 크기 관리 | 구현 | SHD-002~005 |
| _source 오버헤드 축소(synthetic / disable) | 구현 | DISK-007 |
| best_compression codec | 구현 | DISK-006 |
| force merge | 구현 | IDX-003, IDX-004 |
| shrink index | 구현 | SHD-004 권고에 포함 |
| 최소 숫자 타입 사용 | 불가 | 매핑 상세 필요 |
| index sorting 으로 압축률 개선 | 불가 | 워크로드 의존 |
| 필드 순서 고정 | 불가 | 문서 본문 필요 |
| 데이터 수명주기 정의(ILM, downsampling) | 구현 | ILM-001~003 |

---

## 7. General recommendations
`.../production-guidance/general-recommendations`

| 문서 항목 | 상태 | 룰 |
| --- | --- | --- |
| 대량 결과 반환 회피(scroll / search_after 사용) | 구현 | GEN-001 (max_result_window 상향 감지), PERF-005 |
| 대형 문서 회피(http.max_content_length 100MB, Lucene 2GB) | 구현 | GEN-002 |
| 대형 문서의 네트워크·메모리·디스크 부담 | 구현 | GEN-003 (인덱스별 평균 문서 크기) |

## 8. Performance optimizations (상위 인덱스 페이지)
`.../production-guidance/optimize-performance`

하위 5개 문서를 모으는 목차 페이지로, 독립된 판정 항목은 없습니다.

---

---

## 9. 설정 체계(Static / Dynamic)와 Cluster update settings API
`https://www.elastic.co/docs/deploy-manage/stack-settings#static-dynamic`
`https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-cluster-put-settings`

| 문서 항목 | 상태 | 룰 |
| --- | --- | --- |
| 적용 우선순위 transient > persistent > elasticsearch.yml > 기본값 | 구현 | SET-001, SET-003 (yml 값이 API 값에 가려지는 경우) |
| transient 설정 비권장(불안정 시 예기치 않게 사라짐) | 구현 | CLU-013, SET-001 권고 |
| null 로 지정해 기본값으로 초기화 | 구현 | SET-001·SET-002 권고 |
| static 설정은 모든 대상 노드의 yml 에서만 변경, 재기동 필요 | 구현 | SET-004(노드 설정 변경), SET-005(노드 간 불일치) |
| 동적 설정은 API 로, yml 에는 static·노드 고유 설정만 | 구현 | SET-003 권고 |
| Elastic Cloud 는 user settings 로 관리 | 구현 | 배포 형태 감지 후 SET-004 참고로 하향 |
| 설정별 기본값·의미·부작용 | 구현 | 설정 지식 베이스 94종(RULES.md 부록) |

진단 번들의 한계: `cluster_settings_defaults` 는 순수 기본값이 아니라 yml 값이 반영된 값이며, API 로 명시한 키는
기본값을 보고하지 않습니다. `settings.json`(인덱스)에는 기본값 섹션이 없습니다. 그래서 원래 기본값은 지식 베이스를 씁니다.

## 10. 과다 샤딩 · 소형 샤드 (Size your shards)

| 문서 항목 | 상태 | 룰 |
| --- | --- | --- |
| 샤드 10GB~50GB | 구현 | OVS-001(하한 미달 인덱스·줄일 샤드 수), OVS-003(분포), SHD-002/003(상한 초과) |
| 불필요한 소형 샤드 회피 | 구현 | OVS-001, OVS-003, SHD-004 |
| max_primary_shard_size 기준 롤오버 | 구현 | OVS-002(롤오버 과다 데이터 스트림) |
| shrink 로 primary 축소 | 구현 | OVS-001 권고 |
| 빈 인덱스 삭제 | 구현 | SHD-011 |
| 샤드 한도 | 구현 | CLU-015 |

### 10-1. 문서 수 한도·logsdb·force merge

| 문서 항목 | 상태 | 룰 |
| --- | --- | --- |
| rollover 는 샤드당 2억건에서 항상 실행, `max_primary_shard_docs` 를 더 크게 줘도 효과 없음 (ILM rollover) | 구현 | SHD-013, ILM-007 |
| ILM 조건 확인 주기 `indices.lifecycle.poll_interval` 기본 10m (ILM settings) | 반영 | SHD-013 의 허용치(5%, 도구 판단) 근거 |
| 9.0 부터 새 `logs-*-*` data stream 에 logsdb 자동 적용, 업그레이드 전부터 있던 data stream 은 그대로 (Logs data streams) | 구현 | IDX-013 |
| logsdb 기본 정렬 host.name, @timestamp. synthetic _source 는 subscription 필요 (Configure a logs data stream) | 반영 | SHD-014, IDX-013 의 근거·권고 |
| index sorting 은 flush·merge 때 비용 (Index sorting) | 반영 | SHD-014, ILM-009 의 근거 |
| `max_num_segments=1` force merge 는 최대 3배 여유 공간, force_merge pool 은 `max(1, processors/8)` (Force merge API) | 구현 | ILM-008, ILM-009 |
| searchable_snapshot 의 `force_merge_index`(기본 true)는 앞 단계 tier 에서 1 segment 로 merge (ILM searchable snapshot) | 구현 | ILM-008 |
| logsdb shard 10~30GB | 도구 판단 | SHD-014(30GB 이상, 참고), SHD-015(10GB 미만 롤오버, 참고). 30GB 는 공식 수치가 아니라 Elastic 내부 논의를 따른 값이며, 공식 10~50GB 는 그대로 둠 |
| 암묵 2억건 조건과 `min_*` 조건의 우선순위 | 미반영 | 공식 문서에 관계가 적혀 있지 않음 |
| `logsdb_columnar` 모드 | 미반영 | GA 여부 미확인 |


### 10-2. 쓰기 경로·운영

| 항목 | 상태 | 룰 |
| --- | --- | --- |
| merge 가 밀리면 색인 throttle (Merge settings) | 구현 | IDX-014 |
| `index.translog.flush_threshold_size` 기본 10GB(8.8+), 미커밋 작업은 복구 때 재적용 (Translog settings) | 구현 | IDX-015 |
| flush·refresh·merge 평균 시간 | 도구 판단 | PERF-012(현장 기준값, 공식 수치 아님) |
| 쓰기 대상 shard 의 노드 편중 | 도구 판단 | SHD-016 |
| 대량 재시작 시 누적 카운터 신뢰도 | 도구 판단 | OS-007 |
| 비교 대상이 같은 클러스터인지 | 구현 | DIF-013 |
| 디스크 read/write 지연(ms/op) | 판정 불가 | nodes stats `fs.io_stats` 에 read/write 시간 필드가 없음 |

### 10-3. 병목 요약·재시작·스토리지 비용

| 항목 | 상태 | 룰 |
| --- | --- | --- |
| 색인이나 검색이 느릴 때 어디부터 볼지 | 도구 판단 | 병목 요약(증상 먼저, 그다음 정해진 순서로 원인 그룹) |
| 최근 재시작한 노드는 캐시가 비어 있고 카운터가 짧음 | 도구 판단 | 24시간 동안 HOT-001(heap·CPU), HOT-002, DIF-009 비교에서 제외. PERF-012 는 시간당 색인량으로 색인 노드를 고름 |
| shared cache 가 있는 노드는 data path 를 하나만 가질 수 있고, 재시작하면 캐시가 비워짐 (Searchable snapshots) | 활용 | FRZ-002(캐시 파일 위치, 권고) |
| 네트워크 파일시스템에 있는 frozen shared cache | 도구 판단 | FRZ-002 |
| CPU 는 낮은데 바쁜 search 스레드 | 도구 판단 | PERF-013(순간값) |
| ingest 파이프라인 실패율 | 도구 판단 | ING-001 |
| hot 에 남은 롤오버 데이터, 검색 없는 추가 replica, tier 별 디스크 사용, 수집 여유 | 도구 판단 | COST-001~004(참고, COST-004 는 주의도 가능) |
| hot threads 의 대기 시간("other")을 I/O 신호로 보기 | 사용 안 함 | 락 대기 시간도 포함되어 스토리지 대기를 구분하지 못함 |
| 코어 수보다 높은 load average 를 I/O 대기로 보기 | 사용 안 함 | 컨테이너 안에서는 load 가 호스트 값일 수 있음(OS-001) |

### 10-4. 공식 문서 재대조 (2026-10)

공식 기준으로 표기한 판정, 버전 분기, 설정 기본값 전체를 현재 공식 문서와 다시 대조했고, 문서에 없는 부분은 Elasticsearch 소스로 확인했습니다. 바뀐 내용은 CHANGELOG 0.14.0 의 "공식 문서 재대조" 에 있습니다.

| 항목 | 상태 | 룰 |
| --- | --- | --- |
| compressed oops: 대부분 26GB 는 안전, 약 30GB 까지 가능 (JVM settings) | 구현 | JVM-002(JVM 플래그를 먼저 봄) |
| closed 인덱스는 샤드 한도에 세지 않고, frozen 인덱스는 따로 셈 (Miscellaneous cluster settings) | 구현 | CLU-015 |
| `"_source": {"enabled": false}` 로 _source 비활성 (_source field) | 구현 | DISK-007 |
| 기본 max_headroom 은 8.5 부터, 워터마크를 직접 지정하지 않았을 때만 적용 | 구현 | DISK-001~005 |
| bootstrap check 는 운영 모드에서만 적용 | 구현 | SYS-001, SYS-003 |
| 노드가 몇 대를 넘으면 전용 마스터 노드 권장 | 도구 판단 | CLU-007(데이터 노드 10대, 현장 기준) |
| ERU 사용량 | 미구현 | 공식 문서에 계산식이 없고 과금은 계약에 따라 다르다고 명시 |

---

## 11. Troubleshooting 문서 (운영 판단 기준)

| 문서 | 반영 내용 | 룰 |
| --- | --- | --- |
| Hot spotting | 노드별 자원 사용률·작업량 편중 탐지. 같은 역할(tier)끼리만 비교 | HOT-001, HOT-002, HOT-005, SHD-006, DISK-005 |
| Unbalanced cluster / desired balance | 목표 배치에 도달하지 못한 샤드 | HOT-003, HOT-004 |
| Diagnose unassigned shards | 미할당 사유 분포와 allocation explain decider | CLU-002, CLU-003 |
| Disk watermarks (cluster-level shard allocation) | max_headroom 반영 실효 워터마크, frozen 전용 노드는 flood_stage.frozen 만 적용 | DISK-001~005 |
| Health API | 지표를 그대로 전달 | CLU-004 |
| Searchable snapshots | partial 마운트는 store 가 캐시 크기(크기 판정 제외), fully mounted 는 실제 크기(포함). 둘 다 shrink·force-merge 불가 | SHD-002~004, OVS-001~003, IDX-004, IDX-003 |
| ILM / 데이터 스트림 롤오버 | 롤오버된 인덱스의 쓰기 차단은 정상, 현재 쓰기 대상의 차단만 문제 | IDX-008, IDX-011, OVS-002, SHD-011 |

---

## 12. 진단 번들 파일 활용 현황

기준 번들(9.4.4·9.5.3, api 모드 — 두 번들의 파일 구성은 104개로 동일)의 파일 중 **62개를 판정에 사용**합니다. 나머지 42개는 아래 사유로 쓰지 않습니다.
새 수집 도구 버전에서 파일이 추가되면 이 표를 기준으로 활용 여부를 다시 판단합니다.
local / remote 모드 번들의 추가 파일(서버 로그, OS 명령 결과 등)은 아직 대조하지 않았습니다.

| 사유 | 파일 |
| --- | --- |
| 이미 읽는 JSON 의 텍스트판·부분 집합(중복) | `cat/cat_aliases.txt` `cat/cat_count.txt` `cat/cat_fielddata.txt` `cat/cat_health.txt` `cat/cat_master.txt` `cat/cat_nodeattrs.txt` `cat/cat_pending_tasks.txt` `cat/cat_recovery.txt` `cat/cat_repositories.txt` `cat/cat_segments.txt` `cat/cat_templates.txt` `count.json` `master.json` `nodes_short.json` `plugins.json`(nodes.json 의 플러그인 사용) `fielddata_stats.json`(nodes_stats·fielddata.json 사용) `segments.json`(indices_stats 의 세그먼트 수 사용) `allocation_explain_disk.json`(allocation_explain.json 사용) `commercial/ilm_explain_only_errors.json`(ilm_explain.json 사용) |
| 설정·정의 목록(상태 정보 없음) | `commercial/enrich_policies.json` `commercial/ccr_autofollow_patterns.json` `commercial/ml_datafeeds.json` `commercial/ml_dataframe.json` `commercial/ml_trained_models.json` `commercial/transform.json` `commercial/logstash_pipeline.json` `commercial/rollup_caps.json` `commercial/rollup_index_caps.json` |
| 대상 기능을 쓸 때만 내용이 있고 현재 판정 기준이 없음 | `commercial/ccr_follower_info.json` `commercial/enrich_stats.json` `commercial/ml_dataframe_stats.json` `commercial/ml_info.json` `commercial/ml_stats.json` `commercial/profiling_status.json` `commercial/searchable_snapshots_stats.json` `commercial/transform_basic_stats.json` `commercial/transform_node_stats.json` |
| 보안 구성(판정 범위 밖, 민감 정보) | `commercial/security_priv.json` `commercial/security_roles.json` `commercial/security_role_mappings.json` `commercial/security_users.json` |
| API 호출 통계(운영 참고 정보) | `nodes_usage.json` |

아직 읽지 않는 파일: `deprecation_info.json`(업그레이드 deprecation), `commercial/inference.json`, `commercial/connectors.json`, `streams_status.json`. 이미 읽는 `cluster_stats.indices.versions`(인덱스 생성 버전 분포)도 판정에 쓰지 않습니다.

이미 읽는 파일 안에서도 판정에 쓰지 않는 섹션이 있습니다. `nodes_stats` 의 `http.routes`(API 별 호출 분포), `transport`, `adaptive_selection`, `repositories`(스냅샷 저장소 throttle)는 운영 참고 정보라 판정하지 않습니다.

---

## 판정할 수 없는 항목과 이유

0. **remote 모드와 다중 노드 local 모드는 실번들로 검증하지 않았습니다.** local 모드는 단일 노드 테스트 환경 1건(서버 로그·`syscalls/` 포함)으로 확인했습니다.


아래는 도구의 문제가 아니라 support-diagnostics 수집 범위의 문제입니다.

1. **쿼리 본문이 없습니다.** 쿼리 유형별 누적 사용 횟수로 비용이 큰 패턴의 비중만 판정합니다(PERF-011). 어떤 쿼리가 느린지는 slowlog(local 모드) 또는 Search Profiler 로 확인해야 합니다.
2. **인덱스 설정의 기본값이 없습니다.** `settings.json` 에는 명시 설정만 있어, 인덱스 설정의 원래 기본값은 공식 문서 기준 지식 베이스를 씁니다.
   `GET <index>/_mapping` 결과를 별도로 받으면 정확도가 올라갑니다.
3. **OS 커널 설정** 중 vm.max_map_count·vm.swappiness·nofile·nproc·OOM killer 기록은 `syscalls/` 에서 읽습니다(SYS-001~004). readahead·THP·iostat·jstack·gc.log 는 아직 읽지 않습니다.
4. **모든 통계는 노드 기동 이후 누적값**입니다. 단일 번들만으로는 발생 시점을 알 수 없으므로,
   `--baseline` 으로 이전 번들과 비교해 증가분을 판정하십시오(DIF-004~009). 번들이 하나뿐이라면
   로그 또는 모니터링과 대조해야 합니다.

---
