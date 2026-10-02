# 변경 이력

형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/) 를 따릅니다.
각 항목은 "이전 동작 → 현재 동작 (근거)" 로 적습니다. 이전 리포트와 결과가 다른 이유를 추적하는 용도입니다.

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
- 임계값 15개

### 변경

- CLU-017: 5분 이상 task 를 모두 주의로 표시 → action 별로 묶어 task 수와 가장 긴 실행 시간을 표시. 1시간 이상이면 주의, 5분 이상이면 참고. 모니터링·내부 task(`cluster:monitor/*`, `indices:monitor/*`, `internal:*`)는 24시간을 넘을 때만 보고. 쓰기 경로(bulk, reindex, update/delete by query, forcemerge, shrink/split/clone)를 구분해 표시. 실행 시간 정렬이 문자열 순으로 되던 문제도 수정
- MAP-004: ignore_dynamic_beyond_limit 가 없어 색인이 실패할 수 있는 인덱스를 표 앞에 표시(같은 사용률이면 integration 인덱스가 15행을 채워 가려지던 것), data stream template 관리 주체(`fleet:<package>` / `elastic`) 열 추가
- 14노드 9.5.3 실번들에서 확인한 오탐 정리
  - PERF-012: warm 노드의 merge 평균(40초)이 ILM force merge 때문에 길게 나오던 것 → 쓰기 대상 shard 가 있는 노드만 판정
  - OS-001: ECH master 노드처럼 CPU 사용률 0% 인데 load average 가 높은 컨테이너 노드를 치명으로 판정하던 것 → 컨테이너 안의 load 는 호스트 값일 수 있으므로 cpu% 20% 미만이면 참고로만 표시
  - MAP-001·MAP-004: 읽기 전용인 searchable snapshot mount 가 표 앞을 차지하던 것 → 제외
  - PERF-001: 스냅샷 저장소에서 읽는 partial mount(frozen) 인덱스의 검색 지연을 판정하던 것 → 제외(FRZ-001 에서 다룸)
  - IDX-006: 실패 비율 열을 추가하고 비율 순으로 정렬
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
