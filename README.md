# esdiag — Elasticsearch 진단 번들 오프라인 분석기

**버전 0.9.0** · 판정 기준 Elasticsearch 9.4 공식 문서 · Python 3.8+ · 외부 의존성 없음

Elastic [support-diagnostics](https://github.com/elastic/support-diagnostics) 가 만든 진단 번들을
**폐쇄망 안에서** 분석해 클러스터의 현재 이슈·잠재 이슈·설정 위험을 리포트로 만듭니다.

보안 등급 때문에 진단 파일을 외부로 반출할 수 없는 환경을 위해 만들었습니다.
네트워크 호출이 없고, Python 표준 라이브러리만 사용합니다.

> **검증 범위: 이 도구는 api 모드 진단 번들로 검증되었습니다. local / remote 모드(서버 로그·OS 명령 결과 포함) 번들은 파일 구성이 달라 확인이 필요할 수 있습니다.**
>
> **이 도구는 Elastic 공식 지원 도구가 아니며, Elastic Support 의 분석을 대체하지 않습니다.**
> 판정은 번들에 기록된 사실과 공개된 공식 문서 기준에 근거합니다. 모든 판정에 그 근거가
> 공식 기준인지, ES 가 보고한 사실인지, 도구가 정한 임계값인지 표기합니다.

---

## 목차

- [주요 특징](#주요-특징)
- [빠른 시작](#빠른-시작)
- [요구 사항과 실행 환경](#요구-사항과-실행-환경)
- [진단 번들 수집](#진단-번들-수집)
- [판정 기준점(버전)](#판정-기준점버전)
- [판정 체계](#판정-체계)
- [분석 원칙](#분석-원칙)
- [리포트 구성](#리포트-구성)
- [문서](#문서)
- [임계값 조정](#임계값-조정)
- [룰 추가](#룰-추가)
- [검증](#검증)
- [한계](#한계)
- [구조](#구조)

---

## 주요 특징

- **폐쇄망 전제** — 외부 통신·CDN·폰트·패키지 설치 없음. 파일 하나(`esdiag.pyz`)로 반입
- **의존성 없음** — Python 3.8 이상 표준 라이브러리만 사용
- **115개 판정 룰** — 단일 번들 106개 + 두 번들 비교 9개
- **판정 근거 구분** — 모든 판정에 공식 기준 / 사실 보고 / 도구 판단 / 비교 계산 표기
- **설정 변경 분석** — 기본값과 다른 클러스터·노드·인덱스 설정을 원래 기본값, dynamic/static, 의미, 올렸을 때·내렸을 때의 영향과 함께 보고(설정 94종 지식 베이스)
- **과다 샤딩 분석** — 인덱스별로 줄일 수 있는 샤드 수, 데이터 스트림 롤오버 과다, 샤드 크기 분포
- **tier 인식** — hot/warm/cold/frozen 을 구분해 같은 역할끼리만 비교
- **비교 모드** — 이전 번들과 비교해 누적 카운터를 "지금도 증가 중인가" 로 판정
- **대형 번들 대응** — 수백 MB 파일(cluster_state, mapping)은 필요한 조각만 파싱하거나 인덱스 단위로 요약하며 읽어 메모리를 제한
- **번들 활용 범위 명시** — 진단 번들 104개 파일 중 62개를 판정에 사용, 나머지 42개는 중복·기능 미사용 시 비어 있음·판정 대상 아님으로 사유를 [COVERAGE.md](COVERAGE.md) 에 기록
- **미수집·도구 오류 구분** — 파일이 없으면 판정하지 않고, 룰 하나가 실패해도 리포트는 끝까지 생성
- **투명한 명세** — 판정 조건·임계값을 코드에서 자동 추출한 [RULES.md](RULES.md)
- **단일 파일 HTML 리포트** — 인라인 CSS/JS 만 사용해 어떤 브라우저에서도 오프라인으로 열림

---

## 빠른 시작

```bash
# 실행 환경 점검
python3 esdiag.pyz --check-env

# 콘솔 요약
python3 esdiag.pyz diagnostic-20260814.zip

# HTML / Markdown / JSON 한 번에
python3 esdiag.pyz diagnostic-20260814.zip --out-dir ./report

# 이전 번들과 비교
python3 esdiag.pyz diag-0814.zip --baseline diag-0807.zip --html report.html
```

소스 폴더로 실행할 때는 `esdiag.pyz` 대신 `analyze.py` 를 씁니다.

### 옵션

| 옵션 | 설명 |
| --- | --- |
| `--html FILE` / `--md FILE` / `--json FILE` | 형식별 출력 경로 |
| `--out-dir DIR` | `es-diag-report.{html,md,json}` 일괄 생성 |
| `--baseline FILE` | 이전 시점 번들과 비교해 증가분·증가율 판정 |
| `--no-ok` | 정상 판정 숨김 |
| `--only MODULE` | 특정 룰 모듈만 실행(`cluster` `settings` `nodes` `shards` `sharding` `guidance` `hotspot` `ops` `deep` `runtime`), 반복 지정 가능 |
| `--thresholds FILE` | 임계값 재정의 JSON(알 수 없는 키는 경고 후 무시) |
| `--print-thresholds` | 기본 임계값 출력 |
| `--fail-on critical\|warning` | 해당 심각도가 있으면 종료 코드 1 |
| `--quiet` / `--debug` | 콘솔 출력 생략 / 도구 오류 상세 출력 |
| `--check-env` | 실행 환경 점검 |
| `--version` | 도구 버전 |

종료 코드: `0` 정상, `1` `--fail-on` 조건 충족, `2` 입력 오류(경로 없음, 진단 번들로 인식 불가).

---

## 요구 사항과 실행 환경

**외부 패키지 의존성이 없습니다.** `requirements.txt` 는 이를 명시하기 위해 두었습니다. 필요한 것은 Python 인터프리터 하나입니다.

| 항목 | 내용 |
| --- | --- |
| Python | 3.8 이상 — 3.8.20 / 3.12.3 에서 전체 검증 통과, 두 버전의 판정 결과 동일 |
| Python 3.6~3.7 | 정적 분석상 동작 가능(3.7 전용 기능 1곳에 폴백 있음), **실행 미검증** |
| 표준 모듈 | argparse, collections, datetime, fnmatch, html, io, json, math, os, re, sys, tempfile, traceback, zipfile, zlib |
| OS | Linux / macOS / Windows |
| 입력 | 진단 번들 zip 또는 압축 해제 디렉터리 |
| 규모·메모리 | 실번들(인덱스 2,494개, 번들 압축 해제 약 500MB) 7초·최대 약 0.9GB. 합성 번들(인덱스 2만·샤드 6만) 약 30초 |

`--check-env` 는 Python 버전, 표준 모듈, zlib(zip 해제), 콘솔 인코딩, 출력 경로 쓰기 권한을 확인합니다.
zlib 이 빠진 최소 빌드 Python 이면 번들을 압축 해제한 디렉터리를 입력하면 됩니다.
콘솔이 한글을 표시하지 못해도 분석은 중단되지 않으며, 파일 출력은 항상 UTF-8 입니다.

### 반입 형태

| 형태 | 파일 | 실행 |
| --- | --- | --- |
| 단일 파일(권장) | `esdiag.pyz` | `python3 esdiag.pyz ...` — `python3 tools/build_pyz.py` 로 생성 |
| 소스 폴더 | 저장소 전체 | `python3 analyze.py ...` |
| 단독 실행 파일 | `dist/esdiag` | `./esdiag ...` — Python 불필요, 직접 빌드 |

### 환경별 선택

| 대상 환경 | 방법 |
| --- | --- |
| Python 3.8 이상이 있음(RHEL 9 기본 3.9, Ubuntu 20.04 이상 등) | `esdiag.pyz` 반입 후 실행 |
| RHEL 8, python3 미설치 | 기본 포함된 `/usr/libexec/platform-python`(3.6)으로 실행 가능하나 미검증. 가능하면 python39 등 설치 |
| RHEL 7 | 기본 Python 이 2.7 이라 사용 불가. python3 설치 또는 단독 실행 파일 |
| 폐쇄망 내부 분석용 Windows PC | Python 설치본 사용. 설치가 막혀 있으면 python.org 의 Windows embeddable package 로 실행 가능(미검증) |
| Python 설치 자체가 불가 | 단독 실행 파일 빌드 |

어느 경우든 진단 번들은 폐쇄망 밖으로 나가지 않습니다. 서버가 아니라 폐쇄망 내부의 분석용 PC 에서 분석해도 됩니다.

### 단독 실행 파일 빌드(선택)

```bash
bash tools/build_binary.sh     # dist/esdiag (PyInstaller, 빌드 전용 가상환경 사용)
```

- PyInstaller 는 빌드 머신에만 필요합니다. 결과물은 Python 없이 실행됩니다.
- Linux 바이너리는 **빌드한 OS 의 glibc 버전 이상에서만** 실행됩니다. 대상 서버와 같거나 더 오래된 OS 에서 빌드하십시오.
  그래서 저장소에는 빌드된 바이너리를 넣지 않습니다.
- Windows 실행 파일은 Windows 에서 빌드해야 합니다.

---

## 진단 번들 수집

| 수집 모드 | 포함 내용 | 분석 범위 |
| --- | --- | --- |
| `api` | REST API 응답 | 상태·구성·통계 기반 판정 |
| `local` / `remote` | API + 서버 로그(elasticsearch.log, gc.log) | 위 전부 + 로그 패턴 분석 |

로그가 있어야 "언제" 발생했는지 확인할 수 있으므로 가능하면 `local` 또는 `remote` 로 수집하십시오.

> **주의:** 이 도구는 **api 모드** 진단 번들로 검증되었습니다. local / remote 모드(서버 로그·OS 명령 결과 포함) 번들은 파일 구성이 달라 확인이 필요할 수 있습니다. 서버 로그 분석(LOG-001)과 local 모드 전용 파일 처리는 실번들로 검증되지 않았습니다.
> local / remote 모드 번들을 분석할 때는 리포트 하단의 "입력 미수집" · "도구 오류" 항목을 함께 확인하십시오.
수집 방법은 [공식 문서](https://www.elastic.co/docs/troubleshoot/elasticsearch/diagnostic)를 참고하십시오.

**정기적으로 두 번 수집해 `--baseline` 으로 비교하는 것을 권장합니다.** rejection·GC·circuit breaker 는 노드 기동 이후 누적값이라,
번들 하나로는 지금도 발생 중인지 알 수 없습니다.

---

## 판정 기준점(버전)

| 항목 | 값 |
| --- | --- |
| 판정 기준 Elasticsearch 버전 | **9.4** |
| 공식 문서 대조 시점 | 2026-09 |
| 실번들 검증 | 9.4.4(ECH, 3노드 단일 tier) · 9.5.3(ECH, 14노드 hot/warm/cold/frozen) — api 모드 |
| 검증된 수집 모드 | **api 모드만 검증.** local / remote 모드는 확인이 필요할 수 있음 |
| 대형 번들 검증 | 9.5.3 번들(인덱스 2,494개, cluster_state 190MB, mapping 178MB): 분석 7초, 최대 메모리 약 0.9GB |
| 지원 최소 버전 | 8.0(미만은 해당 버전에 있는 API 범위에서만 동작) |

기준은 `esdiag/__init__.py` 에 고정되어 있고 모든 리포트 상단에 표기됩니다.
기준보다 새로운 버전을 분석하면 `VER-001`(참고)이 표시됩니다.

### 버전에 따라 판정이 갈리는 지점

| 버전 | 판정 | 내용 |
| --- | --- | --- |
| 8.0 | SET-* | `action.destructive_requires_name` 기본값 true |
| 8.3 | SHD-001 | heap 1GB당 샤드 20개 기준은 8.3 미만에만 적용(8.3 에서 공식 폐기) |
| 8.5 | DISK-* | 디스크 워터마크에 max_headroom(low 200GB / high 150GB / flood 100GB) 반영 |
| 8.14 | VEC-002 | dense_vector index_options 미지정 시 int8_hnsw 기본 |
| 9.1 | VEC-002 | 384차원 이상 float 벡터는 bbq_hnsw 기본 |
| 9.2 | VEC-003 | `index.mapping.exclude_source_vectors` 기본 적용 |

---

## 판정 체계

### 심각도

| 단계 | 의미 |
| --- | --- |
| 치명 | 지금 장애 중이거나 방치하면 곧 장애가 되는 항목 |
| 주의 | 성능·안정성·복구력이 이미 손상된 항목 |
| 참고 | 맥락 정보, 개선 여지 |
| 정상 | 점검했고 문제가 없는 항목(점검 범위를 보이기 위해 남김) |

### 판정 근거 구분

| 구분 | 의미 | 판정 ID 수 |
| --- | --- | --- |
| 공식 기준 | 판정 기준이 Elastic 공식 문서에 명시(예: heap ≤ RAM 50%, 샤드 10~50GB·2억건, 워터마크, 설정 기본값) | 61 |
| 사실 보고 | ES 가 보고한 상태·오류·설정을 그대로 전달, 임계값 없음(예: red, ILM 오류) | 55 |
| 도구 판단 | 공식 수치가 없어 도구가 정한 임계값(예: heap 사용률 75%, 평균 검색 지연 200ms) | 44 |
| 비교 계산 | 두 번들 간 증가분·증가율·선형 외삽 | DIF-001~012 |

고객에게 전달할 때 "공식 기준·사실 보고" 는 근거로, "도구 판단" 은 권고로 제시하십시오.

### 종합 판정

치명·주의 건수로만 정합니다. 치명이 있으면 **조치 필요**, 주의 5건 이상이면 **점검 권고**, 주의 1~4건이면 **양호(개선 여지)**, 없으면 **양호** 입니다.
가중치 점수는 쓰지 않습니다. 공식 기준이 없는 임의 산식이고, 대형 클러스터에서는 쉽게 0점이 되어 정보가 없기 때문입니다.

### 확인하지 못한 항목

두 종류를 구분해 리포트 하단에 따로 표시합니다. 둘 다 "문제 없음" 이 아니라 **"확인하지 못함"** 입니다.

| 구분 | 원인 | 조치 |
| --- | --- | --- |
| 입력 미수집 | 룰이 필요로 하는 파일이 번들에 없음(수집 모드·계정 권한·도구 버전) | 수집 조건 확인 후 재수집 |
| 도구 오류 | 이 도구가 해당 번들의 데이터 형식을 처리하지 못함 | JSON 출력의 `rule_errors` 를 도구 관리자에게 전달 |

룰 하나가 실패해도 나머지 판정과 리포트 생성은 계속됩니다.

---

## 분석 원칙

### tier 인식

데이터 노드는 역할 조합으로 tier(hot / content / warm / cold / frozen)를 나눕니다.
**스펙·샤드 수·자원 사용률·작업량은 같은 tier 끼리만 비교합니다.** tier 간 차이는 정상 설계라 판정하지 않고 NODE-003 에 tier 별 스펙 표만 둡니다.
다만 tier 의 모든 노드가 CPU 한계 근처라면 편중이 아니라 용량 부족이므로 HOT-005 로 판정합니다.
frozen 전용 노드는 shared cache 가 디스크 대부분을 미리 점유하므로 low/high 워터마크를 적용하지 않고 `flood_stage.frozen`(95%, max_headroom 20GB)만 봅니다.

### 인덱스 분류

- `.ds-<data stream>-*` 백킹 인덱스는 **사용자 데이터**입니다. 데이터 스트림 이름이 `.` 으로 시작할 때만(`.ds-.kibana-*` 등) 시스템 인덱스로 봅니다.
- searchable snapshot 은 마운트 방식에 따라 다르게 다룹니다.
  - **partial 마운트(frozen, `partial-*`)**: store 크기가 로컬 캐시 크기라 원본 크기가 아닙니다 → 크기 판정(소형·대형·과다 샤딩)에서 제외
  - **fully mounted(cold, `restored-*`)**: 샤드 전체가 로컬에 복사되어 store 크기가 실제 크기입니다 → 크기 판정에 포함
  - 둘 다 스냅샷이 원본이라 shrink·force-merge 를 할 수 없습니다 → 조치형 판정(세그먼트·삭제 문서·인덱스별 과다 샤딩)에서 제외하고, 원인(롤오버·primary 설정) 조치를 안내합니다.
- 쓰기 차단은 롤오버 완료 인덱스와 searchable snapshot 에서는 ILM 의 정상 동작이므로 판정하지 않습니다.
  **현재 쓰기 대상(데이터 스트림 write index, alias write index)의 차단과 flood stage 차단만** 치명으로 봅니다.

### 설정 변경 분석

기본값과 다른 설정을 찾아 **원래 기본값 / 현재 값 / dynamic·static / 의미 / 변경 영향(↑ 올림 · ↓ 내림)** 을 보고합니다.

| 판정 | 대상 |
| --- | --- |
| SET-001 | persistent / transient 에 명시된 클러스터 설정 중 기본값과 다른 것 |
| SET-002 | 기본값과 같은 값을 명시한 설정(업그레이드 시 새 기본값을 따라가지 못함) |
| SET-003 | elasticsearch.yml 값이 API 설정에 가려져 무시되는 경우 |
| SET-004 | 노드 설정(yml, static 포함) 중 기본값과 다른 것 |
| SET-005 | 데이터 노드 간 설정 불일치 |
| SET-006 | 사용자 인덱스 설정 중 기본값과 다른 것 |

공식 적용 우선순위(transient > persistent > elasticsearch.yml > 기본값)를 따릅니다.
번들의 `cluster_settings_defaults` 는 yml 값이 반영된 값이고, API 로 명시한 키는 기본값을 보고하지 않습니다.
그래서 **원래 기본값은 공식 문서 기준 지식 베이스(`esdiag/settings_kb.py`)** 를 쓰고, 등록되지 않은 설정은 "설명 미등록" 으로 값만 보고합니다.
전용 룰이 따로 판정하는 설정(예: ARS → CLU-014)은 표에 `[판정: 룰ID]` 로 표시하고 SET 심각도에서 빼서 이중 판정을 막습니다.

### 과다 샤딩 분석

| 판정 | 기준 |
| --- | --- |
| OVS-001 | primary 2개 이상 인덱스의 샤드당 평균이 공식 하한 10GB 미만 → 줄일 수 있는 샤드 = (현재 − ceil(크기/50GB)) × (1 + replica) |
| OVS-002 | 데이터 스트림 백킹 인덱스의 샤드당 크기 중앙값이 1GB 미만(롤오버 과다) |
| OVS-003 | 사용자 primary 샤드 크기 분포(<1GB / 1~10GB / 10~50GB / 50GB+), 10GB 미만이 80% 이상이면 전반적 과다 샤딩 |

데이터 스트림의 현재 write index 는 채워지는 중이라 크기 판정에서 제외합니다.

### 비교 모드

| 판정 | 내용 |
| --- | --- |
| DIF-001 | 클러스터 상태 악화/개선 |
| DIF-002~003 | 노드 재기동(uptime 역전), 노드 이탈·신규 |
| DIF-004~005 | rejection 증가분과 시간당 발생률(증가 없으면 과거 이력으로 분류) |
| DIF-006~007 | 구간 내 old GC 비중, circuit breaker 발동 증가분 |
| DIF-008 | 디스크 증가 속도 → high watermark 도달 예상일(선형 외삽, frozen 제외) |
| DIF-009~011 | 구간 처리량과 분포, 인덱스 증가량, 인덱스 생성·삭제 |
| DIF-012 | 판정 변화(신규 발생 / 악화 / 해소) |

---

## 리포트 구성

HTML 리포트(단일 파일)의 순서입니다. Markdown·콘솔도 같은 내용을 담습니다.

1. 헤더 — 클러스터, 버전, 배포 형태, 수집 시각·모드, 도구 버전·판정 기준, 종합 판정, 심각도 분포
2. **영역별 점검 결과** — 가용성 / 자원·용량 / 데이터 구조 / 성능 / 데이터 보호·운영 / 보안 / 구성의 상태와 건수
3. 이전 번들 대비 변화(`--baseline` 지정 시)
4. 조치 우선순위 — 치명·주의 목록, 클릭하면 해당 판정으로 이동
5. 노드 상태 한눈에 보기 — heap·CPU·load·디스크·샤드 수 막대
6. 저장 용량 상위 인덱스
7. 필터 — 심각도 × 분류 조합
8. 판정 결과 — 헬스 체크 영역 순서로, 관측 / 영향 / 권고 / 근거 표 / 출처 파일 / 참고 문서, 근거 구분 표기
9. 판정 근거 구분 설명, 확인하지 못한 항목(입력 미수집·도구 오류)

### 헬스 체크 영역

| 영역 | 포함 분류 | 대표 판정 |
| --- | --- | --- |
| 가용성 | 클러스터 | 상태·미할당 샤드·마스터 정족수·샤드 한도·노드 종료·voting exclusion |
| 자원·용량 | 노드, 핫스팟·밸런싱 | heap·GC·CPU·디스크·워터마크·스레드풀·circuit breaker·tier 포화·편중 |
| 데이터 구조 | 샤드·인덱스, 벡터 검색 | 샤드 크기·과다 샤딩·매핑 한도·쓰기 차단·벡터 메모리 |
| 성능 | 성능 기준, 런타임 | 비용이 큰 검색 패턴·캐시·ingest·hot threads·로그 |
| 데이터 보호·운영 | 운영 | 스냅샷 RPO·SLM·ILM·라이선스·모니터링·ML |
| 보안 | 보안·인증 | 보안 기능·TLS 인증서 만료 |
| 구성 | 설정 기준, 설정 변경 | 공식 필수 설정·기본값 대비 변경 |

---

## 문서

| 문서 | 내용 |
| --- | --- |
| [RULES.md](RULES.md) | 115개 룰 전체 명세 — 판정 조건, 임계값(현재 값·출처), 필요 입력, 참고 문서, 설정 지식 베이스. **코드에서 자동 생성** |
| [COVERAGE.md](COVERAGE.md) | Elastic 공식 문서 항목별 반영 여부와 판정할 수 없는 항목의 이유 |
| [CHANGELOG.md](CHANGELOG.md) | 변경 이력 — 이전 동작 → 현재 동작과 근거 |

RULES.md 는 직접 수정하지 않습니다. 룰을 바꾼 뒤 재생성합니다.

```bash
python3 tools/gen_rules_doc.py            # RULES.md 재생성
python3 tools/gen_rules_doc.py --check    # 임계값 누락·미사용, docstring 누락 검사
```

---

## 임계값 조정

```bash
python3 esdiag.pyz --print-thresholds > my.json   # 기본값 추출
# my.json 에서 필요한 키만 남기고 수정
python3 esdiag.pyz bundle.zip --thresholds my.json
```

임계값 99개의 출처(`[공식]` / `[도구]`)는 `esdiag/thresholds.py` 주석과 RULES.md 부록에 있습니다.
`[공식]` 값은 바꾸지 않는 것을 권장합니다.

---

## 룰 추가

1. 해당 모듈(`esdiag/rules/*.py`)에 함수를 만들고 `RULES` 에 등록합니다.
2. 함수 docstring 에 판정 조건을 정확히 적습니다(RULES.md 에 그대로 실립니다).
3. 필요한 입력 파일을 `esdiag/rules/__init__.py` 의 `REQUIRES` 에 선언합니다.
4. 판정 ID 의 근거 구분을 `esdiag/basis.py` 에 등록합니다.
5. 새 임계값은 `esdiag/thresholds.py` 에 출처 주석과 함께 추가합니다.
6. 숫자 필드는 `num()`, dict 목록은 `dicts()`, 문자열 목록은 `strs()`, dict 항목은 `items()` 로 읽습니다(버전별 형식 차이 대응).
7. `tests/drive_branches.py` 에 판정이 실제로 발생하는 시나리오를 추가합니다(미실행 분기가 남지 않게).
8. `bash tests/run_all.sh <번들>` 이 통과하는지 확인합니다.

```python
def r_example(ctx):
    """heap_used_percent >= example_warn 인 노드가 있으면 주의."""
    bad = [n.name for n in ctx.nodes if (n.heap_used_pct or 0) >= ctx.t["example_warn"]]
    if not bad:
        return []
    return [Finding("EX-001", "노드", Severity.WARNING, "예시 판정",
                    observed="대상 노드: %s" % ", ".join(bad),
                    impact="영향", recommend="권고",
                    evidence=table(["node"], [[b] for b in bad]),
                    source="nodes_stats.json")]
```

문자열에 `%` 를 쓰고 `%` 포맷을 적용할 때는 `%%` 로 씁니다(`tests/lint_format.py` 가 검사합니다).

---

## 검증

```bash
bash tests/run_all.sh diagnostic.zip
```

| 검사 | 내용 | 현재 결과 |
| --- | --- | --- |
| `tests/lint_format.py` | `%` 포맷 문자열 정적 검사 — 실행되지 않는 분기의 포맷 오류까지 | 442개, 문제 0 |
| `tests/verify_logic.py` | 계산 로직 단정문 — 워터마크, GC 로그, 설정 지식 베이스 교차 검증, 다중 tier·마운트 인덱스·쓰기 차단 재현 | 55개 통과 |
| `tests/drive_branches.py` | 시나리오 51개로 모든 판정 분기를 강제 실행하고 심각도까지 확인 | 51개 통과, 미실행 판정 분기 0 |
| `tests/fuzz_rules.py` | 필드 누락·null·문자열 숫자 변형(`--harsh` 는 임의 타입) | 실패 0 |
| `tools/gen_rules_doc.py --check` | 임계값·docstring 정합성 | 문제 0 |
| `tests/check_docs.py` | README·RULES·COVERAGE·CHANGELOG 의 수치·목록·링크가 코드와 일치하는지, 판정 ID 와 근거 구분 표 대조 | 불일치 0 |

`tests/make_broken_bundle.py` 는 정상 번들에 장애 상황을 주입한 번들을 만듭니다(리포트 예시·수동 확인용).

---

## 한계

- **api 모드에서만 검증되었습니다.** local / remote 모드 번들은 확인이 필요할 수 있습니다.

아래는 도구가 아니라 진단 번들 수집 범위에서 오는 한계입니다.

- **쿼리 본문이 없습니다.** 쿼리 유형별 누적 사용 횟수(`cluster_stats.indices.search`)로 비용이 큰 패턴의 비중은 판정하지만(PERF-011), 어떤 인덱스의 어떤 쿼리인지는 slowlog 나 Search Profiler 로 확인해야 합니다.
- **보안 구성(사용자·역할·권한)은 판정하지 않습니다.** 보안 감사 영역이고 민감 정보라, 보안 기능 활성화와 인증서 만료만 봅니다.
- **인덱스 설정의 기본값은 번들에 없습니다.** 인덱스 설정 지식 베이스(30종)는 공식 문서 기준이며 번들로 교차 검증되지 않습니다.
- **OS 커널 설정**(readahead, vm.swappiness, vm.max_map_count 원본값)은 판정하지 않습니다.
- **hot threads 는 수집 순간 500ms 스냅샷**입니다. 부하가 없을 때 수집하면 신호가 나오지 않습니다.
- 디스크 포화 예상(DIF-008)은 두 시점 사이의 선형 외삽입니다.

판정할 수 없는 항목 전체와 이유는 [COVERAGE.md](COVERAGE.md) 에 있습니다.

---

## 구조

```
.
├── analyze.py                  # CLI 진입점
├── requirements.txt            # 외부 의존성 없음(명시용)
├── esdiag/
│   ├── __init__.py             # 버전, 판정 기준점, 버전 분기
│   ├── loader.py               # zip/디렉터리 로딩, api·local·remote 레이아웃 흡수
│   ├── context.py              # 정규화 계층: 실효 워터마크, tier, 인덱스 분류, 쓰기 대상, 배포 형태
│   ├── thresholds.py           # 전체 임계값(출처 주석 포함)
│   ├── settings_kb.py          # 설정 지식 베이스(기본값·종류·의미·영향)
│   ├── basis.py                # 판정 근거 구분
│   ├── engine.py               # 룰 실행·격리, 미수집 처리, 종합 판정, 버전 점검
│   ├── envcheck.py             # 실행 환경 점검(--check-env)
│   ├── diff.py                 # 두 번들 비교
│   ├── model.py                # Finding / Severity
│   ├── util.py                 # 단위 파싱, 안전 접근자(num·dicts·strs·items)
│   ├── rules/                  # cluster · settings · nodes · shards · sharding · guidance · hotspot · ops · deep · runtime
│   └── report/                 # text(콘솔·Markdown) · html(단일 파일)
├── tools/
│   ├── gen_rules_doc.py        # RULES.md 생성기 + 정합성 검사
│   ├── build_pyz.py            # 단일 파일 배포본(esdiag.pyz)
│   └── build_binary.sh         # 단독 실행 파일 빌드(선택)
├── tests/
│   ├── run_all.sh              # 전체 검증
│   ├── check_docs.py           # 문서 정합성 검사
│   ├── lint_format.py          # 포맷 문자열 정적 검사
│   ├── verify_logic.py         # 계산 로직 단정문
│   ├── drive_branches.py       # 판정 분기 구동
│   ├── fuzz_rules.py           # 입력 변형 퍼징
│   └── make_broken_bundle.py   # 장애 주입 번들 생성
├── RULES.md                    # 룰 명세(자동 생성)
├── COVERAGE.md                 # 공식 문서 대조표
└── CHANGELOG.md                # 변경 이력
```

---

## 릴리스 절차

```bash
# 1) esdiag/__init__.py 의 __version__ 과 CHANGELOG.md 를 갱신
# 2) 명세 재생성과 전체 검증
python3 tools/gen_rules_doc.py
bash tests/run_all.sh <검증용 번들.zip>
# 3) 단일 파일 배포본 생성 → GitHub Releases 에 첨부(저장소에는 넣지 않음)
python3 tools/build_pyz.py        # dist/esdiag.pyz
git tag v0.9.0
```

검증용 진단 번들과 그 분석 리포트에는 고객 환경 정보(클러스터 이름, 인덱스 이름, 호스트)가 들어 있으므로 저장소에 올리지 않습니다.

---

## 라이선스

This project is open-sourced software licensed under the [MIT license](LICENSE).