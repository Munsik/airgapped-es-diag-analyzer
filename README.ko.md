# esdoctor — Elasticsearch 진단 번들 오프라인 분석기

[English](README.md) · 한국어

**버전 0.14.1** · 판정 기준 Elasticsearch 9.5 공식 문서 · Python 3.8+ · 외부 의존성 없음

Elastic [support-diagnostics](https://github.com/elastic/support-diagnostics) 가 만든 진단 번들을 **폐쇄망 안에서** 분석해 클러스터의 현재 이슈·잠재 이슈·설정 위험을 리포트로 만듭니다.

보안 등급 때문에 진단 파일을 외부로 반출할 수 없는 환경을 위해 만들었습니다.
네트워크 호출이 없고, Python 표준 라이브러리만 사용합니다.

> **검증 범위: api 모드(ECH 9.4.4·9.5.3)와 local 모드(self-managed 8.19.21 단일 노드, 서버 로그·`syscalls/` 포함) 실번들로 검증되었습니다. remote 모드와 다중 노드 local 모드 번들은 아직 실번들로 검증하지 않았습니다.**
>
> **이 도구는 Elastic 공식 지원 도구가 아니며, Elastic 공식 Support 팀의 분석을 대체하지 않습니다.** 판정은 번들에 기록된 사실과 공개된 공식 문서 기준에 근거합니다. 모든 판정에 그 근거가 공식 기준인지, ES 가 보고한 사실인지, 도구가 정한 임계값인지 표기합니다.

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
- [Elastic 공식 Support 팀 요약](#elastic-공식-support-팀-요약)
- [문서](#문서)
- [임계값 조정](#임계값-조정)
- [룰 추가](#룰-추가)
- [검증](#검증)
- [한계](#한계)
- [구조](#구조)

---

## 주요 특징

- **폐쇄망 전제** — 외부 통신·CDN·폰트·패키지 설치 없음. 저장소를 그대로 반입해 실행
- **의존성 없음** — Python 3.8 이상 표준 라이브러리만 사용
- **133개 판정 룰** — 단일 번들 122개 + 두 번들 비교 11개
- **병목 요약** — 리포트 맨 위에서 다섯 가지 질문(색인이 따라가는가, 검색이 느린가, 스토리지가 한계인가, 재시작이 수치를 왜곡하는가, 용량 부족인가 편중인가)에 답합니다. 증상을 먼저 보고, 그 증상을 설명하는 판정을 이어서 짚습니다
- **스토리지 비용** — 롤오버 후에도 hot 에 남은 데이터, 검색되지 않는 replica, tier 간 디스크 사용 차이, 수집 대상 tier 가 며칠치 수집량을 더 받을 수 있는지
- **원인 단위 조치 우선순위** — 같은 원인에서 나온 판정(예: yellow·미할당 샤드·allocation explain·replica 초과)은 대표 1건으로 묶고 나머지는 관련 판정으로 표시
- **판정 근거 구분** — 모든 판정에 공식 기준 / 사실 보고 / 도구 판단 / 비교 계산 표기
- **설정 변경 분석** — 기본값과 다른 클러스터·노드·인덱스 설정을 원래 기본값, dynamic/static, 의미, 올렸을 때·내렸을 때의 영향과 함께 보고(설정 96종 지식 베이스)
- **과다 샤딩 분석** — 인덱스별로 줄일 수 있는 샤드 수, 데이터 스트림 롤오버 과다, 샤드 크기 분포
- **tier 인식** — hot/warm/cold/frozen 을 구분해 같은 역할끼리만 비교
- **비교 모드** — 이전 번들과 비교해 누적 카운터를 "지금도 증가 중인가" 로 판정하고, 노드별 이전/지금 표를 보여 줌. 번들이 3개 이상이면 사이징용 구간별 처리량(peak/off-peak)도 계산
- **대형 번들 대응** — 수백 MB 파일(cluster_state, mapping)은 필요한 조각만 파싱하거나 인덱스 단위로 요약하며 읽어 메모리를 제한
- **번들 활용 범위 명시** — 진단 번들 104개 파일 중 62개를 판정에 사용, 나머지 42개는 중복·기능 미사용 시 비어 있음·판정 대상 아님으로 사유를 [COVERAGE.md](COVERAGE.md) 에 기록
- **미수집·도구 오류 구분** — 파일이 없으면 판정하지 않고, 룰 하나가 실패해도 리포트는 끝까지 생성
- **투명한 명세** — 판정 조건·임계값을 코드에서 자동 추출한 [RULES.md](RULES.md)
- **단일 파일 HTML 리포트** — 인라인 CSS/JS 만 사용해 어떤 브라우저에서도 오프라인으로 열림

---

## 빠른 시작

```bash
# 저장소 클론 후 바로 실행 — pip install 불필요
git clone https://github.com/Munsik/airgapped-es-diag-analyzer.git
cd airgapped-es-diag-analyzer

# 실행 환경 점검
python3 analyze.py --check-env

# 콘솔 요약
python3 analyze.py diagnostic-20260814.zip

# HTML / Markdown / JSON 한 번에
python3 analyze.py diagnostic-20260814.zip --out-dir ./report

# 이전 번들과 비교
python3 analyze.py diag-0814.zip --baseline diag-0807.zip --html report.html

# 번들 3개 이상: 구간별 처리량(peak/off-peak)
python3 analyze.py diag-0814-1800.zip --baseline diag-0814-0900.zip --baseline diag-0814-0300.zip
```

인터넷이 없는 폐쇄망에서는 저장소를 zip 으로 내려받아 반입한 뒤 압축을 풀고 같은 방식으로 실행합니다.

### 옵션

| 옵션 | 설명 |
| --- | --- |
| `--html FILE` / `--md FILE` / `--json FILE` | 형식별 출력 경로 |
| `--out-dir DIR` | `es-diag-report.{html,md,json}` 일괄 생성 |
| `--baseline FILE` | 이전 시점 번들과 비교해 증가분·증가율 판정. 여러 번 지정할 수 있으며, 번들을 수집 시각 순으로 정렬해 가장 최근 번들을 비교 기준으로 쓰고, 전체 번들이 3개 이상이면 구간별 처리량(DIF-014)도 계산 |
| `--support-summary FILE` | Elastic 공식 Support 팀 문의용 요약(Markdown)을 함께 만듭니다. 지정한 때만 생성 |
| `--mask none\|basic\|strict` | 요약의 마스킹 단계(기본 `basic`). `--support-summary` 와 함께 사용 |
| `--mask-map FILE` | 별칭 ↔ 원래 이름 매핑 JSON 경로(기본: 요약 파일명 + `.mask-map.json`). `--support-summary` 와 함께 사용 |
| `--lang both\|ko\|en\|auto` | 출력 언어(기본 `both`). `both` 는 한국어와 영어를 모두 만들며 파일명에 `.ko` / `.en` 을 붙입니다(`report.html` → `report.ko.html`, `report.en.html`). `ko` / `en` 은 한 언어만 지정한 이름 그대로 씁니다. `auto` 는 로캘을 따릅니다. 환경 변수 `ESDOCTOR_LANG` 으로도 지정합니다 |
| `--no-ok` | 정상 판정 숨김 |
| `--only MODULE` | 특정 룰 모듈만 실행(`cluster` `settings` `nodes` `shards` `sharding` `guidance` `hotspot` `cost` `ops` `deep` `runtime` `syscalls`), 반복 지정 가능 |
| `--thresholds FILE` | 임계값 재정의 JSON(알 수 없는 키는 경고 후 무시) |
| `--print-thresholds` | 기본 임계값 출력 |
| `--fail-on critical\|warning` | 해당 심각도가 있으면 종료 코드 1 |
| `--quiet` / `--debug` | 콘솔 출력 생략 / 도구 오류 상세 출력 |
| `--check-env` | 실행 환경 점검 |
| `--version` | 도구 버전 |

종료 코드: `0` 정상, `1` `--fail-on` 조건 충족, `2` 입력 오류(경로 없음, 진단 번들로 인식 불가) 또는 요약 마스킹 실패(아래 참고).

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

| 형태 | 방법 |
| --- | --- |
| 소스 클론(기본) | `git clone` 후 `python3 analyze.py ...` |
| 소스 zip 반입 | GitHub 에서 zip 다운로드 후 압축 해제 → `python3 analyze.py ...` |
| 단일 파일(선택) | `python3 tools/build_pyz.py` 로 `dist/esdoctor.pyz` 생성 → `python3 esdoctor.pyz ...` |
| 단독 실행 파일(선택) | `bash tools/build_binary.sh` 로 `dist/esdoctor` 생성 → `./esdoctor ...` (Python 불필요) |

### 환경별 선택

| 대상 환경 | 방법 |
| --- | --- |
| Python 3.8 이상이 있음(RHEL 9 기본 3.9, Ubuntu 20.04 이상 등) | 저장소 반입 후 `python3 analyze.py` 실행 |
| RHEL 8, python3 미설치 | 기본 포함된 `/usr/libexec/platform-python`(3.6)으로 실행 가능하나 미검증. 가능하면 python39 등 설치 |
| RHEL 7 | 기본 Python 이 2.7 이라 사용 불가. python3 설치 또는 단독 실행 파일 |
| 폐쇄망 내부 분석용 Windows PC | Python 설치본 사용. 설치가 막혀 있으면 python.org 의 Windows embeddable package 로 실행 가능(미검증) |
| Python 설치 자체가 불가 | 단독 실행 파일 빌드 |

어느 경우든 진단 번들은 폐쇄망 밖으로 나가지 않습니다. 서버가 아니라 폐쇄망 내부의 분석용 PC 에서 분석해도 됩니다.

### 단독 실행 파일 빌드(선택)

```bash
bash tools/build_binary.sh     # dist/esdoctor (PyInstaller, 빌드 전용 가상환경 사용)
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
| `local` / `remote` | API + 서버 로그(elasticsearch.log, gc.log) + `syscalls/` | 위 전부 + 로그 패턴 분석 + OS 설정(SYS-001~004) |

로그가 있어야 "언제" 발생했는지 확인할 수 있으므로 가능하면 `local` 또는 `remote` 로 수집하십시오.

> **참고:** local 모드의 `syscalls/` 는 진단을 실행한 호스트 한 대의 값만 담습니다.
> local / remote 모드 번들을 분석할 때는 리포트 하단의 "입력 미수집" · "도구 오류" 항목을 함께 확인하십시오.
> 수집 방법은 [공식 문서](https://www.elastic.co/docs/troubleshoot/elasticsearch/diagnostic)를 참고하십시오.

**정기적으로 두 번 수집해 `--baseline` 으로 비교하는 것을 권장합니다.** rejection·GC·circuit breaker 는 노드 기동 이후 누적값이라, 번들 하나로는 지금도 발생 중인지 알 수 없습니다.

---

## 판정 기준점(버전)

| 항목 | 값 |
| --- | --- |
| 판정 기준 Elasticsearch 버전 | **9.5** |
| 공식 문서 대조 시점 | 2026-10 |
| 실번들 검증 | 9.4.4(ECH, 3노드 단일 tier) · 9.5.3(ECH, 14노드 hot/warm/cold/frozen) — api 모드 |
| 검증된 수집 모드 | **api**(위 두 번들) · **local**(diagnostics 9.4.1 로 수집한 self-managed ES 8.19.21 단일 노드, Rocky Linux 9). **remote 와 다중 노드 local 은 미검증** |
| 대형 번들 검증 | 9.5.3 번들(인덱스 2,494개, cluster\_state 190MB, mapping 178MB): 분석 7초, 최대 메모리 약 0.9GB |
| 지원 최소 버전 | 8.0(미만은 해당 버전에 있는 API 범위에서만 동작) |

기준은 `esdoctor/__init__.py` 에 고정되어 있고 모든 리포트 상단에 표기됩니다.
기준보다 새로운 버전을 분석하면 `VER-001`(참고)이 표시됩니다.

### 버전에 따라 판정이 갈리는 지점

| 버전 | 판정 | 내용 |
| --- | --- | --- |
| 8.0 | SET-\* | `action.destructive_requires_name` 기본값 true |
| 8.3 | SHD-001 | heap 1GB당 샤드 20개 기준은 8.3 미만에만 적용(8.3 에서 공식 폐기) |
| 8.5 | DISK-\* | 디스크 워터마크에 max\_headroom(low 200GB / high 150GB / flood 100GB) 반영 |
| 8.8 | IDX-015 | `index.translog.flush_threshold_size` 기본값 10GB(이전 512MB) |
| 8.14 | VEC-002 | dense\_vector index\_options 미지정 시 int8\_hnsw 기본 |
| 9.1 | VEC-002 | 384차원 이상 float 벡터는 bbq\_hnsw 기본 |
| 9.0 | IDX-013 | 새 `logs-*-*` data stream 에 logsdb 자동 적용. 8.x 에서 업그레이드하기 전부터 있던 data stream 은 그대로 |
| 9.2 | VEC-003 | `index.mapping.exclude_source_vectors` 기본 적용 |
| 9.5 | SET-006, DISK-006, DISK-007, IDX-013, PERF-008, OPS-007 | merge policy 기본값 변경(segments_per_tier 8, floor_segment 16mb, max_merge_at_once 16), columnar·logsdb_columnar 는 best_compression·synthetic _source 기본, vectordb_document 는 index.store.preload 자동 설정, 모니터링 플러그인 수집 deprecated |

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
| 공식 기준 | 판정 기준이 Elastic 공식 문서에 명시(예: heap ≤ RAM 50%, 샤드 10~50GB·2억건, 워터마크, 설정 기본값) | 68 |
| 사실 보고 | ES 가 보고한 상태·오류·설정을 그대로 전달, 임계값 없음(예: red, ILM 오류) | 57 |
| 도구 판단 | 공식 수치가 없어 도구가 정한 임계값(예: heap 사용률 75%, 평균 검색 지연 200ms) | 59 |
| 비교 계산 | 두 번들 간 증가분·증가율·선형 외삽 | DIF-001~013 |

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

데이터 노드는 역할 조합으로 tier(hot / content / warm / cold / frozen)를 나눕니다. **스펙·샤드 수·자원 사용률·작업량은 같은 tier 끼리만 비교합니다.** tier 간 차이는 정상 설계라 판정하지 않고 NODE-003 에 tier 별 스펙 표만 둡니다.
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
| SET-005 | 같은 tier 데이터 노드 간 설정 불일치 |
| SET-006 | 사용자 인덱스 설정 중 기본값과 다른 것 |

공식 적용 우선순위(transient > persistent > elasticsearch.yml > 기본값)를 따릅니다.
번들의 `cluster_settings_defaults` 는 yml 값이 반영된 값이고, API 로 명시한 키는 기본값을 보고하지 않습니다.
그래서 **원래 기본값은 공식 문서 기준 지식 베이스(`esdoctor/settings_kb.py`)** 를 쓰고, 등록되지 않은 설정은 "설명 미등록" 으로 값만 보고합니다.
전용 룰이 따로 판정하는 설정(예: ARS → CLU-014)은 표에 `[판정: 룰ID]` 로 표시하고 SET 심각도에서 빼서 이중 판정을 막습니다.

### 과다 샤딩 분석

| 판정 | 기준 |
| --- | --- |
| OVS-001 | primary 2개 이상 인덱스의 샤드당 평균이 공식 하한 10GB 미만 → 줄일 수 있는 샤드 = (현재 − ceil(크기/50GB)) × (1 + replica) |
| OVS-002 | 데이터 스트림 백킹 인덱스의 샤드당 크기 중앙값이 1GB 미만(롤오버 과다) |
| OVS-003 | 사용자 primary 샤드 크기 분포(<1GB / 1~10GB / 10~50GB / 50GB+), 10GB 미만이 80% 이상이면 전반적 과다 샤딩 |

데이터 스트림의 현재 write index 는 채워지는 중이라 크기 판정에서 제외합니다.

### 문서 수 한도와 logsdb

rollover 는 샤드 문서 수가 2억건에 닿으면 조건과 관계없이 항상 실행됩니다. `max_primary_shard_docs` 를 2억건보다 크게 줘도 효과가 없습니다(공식). ILM 은 `indices.lifecycle.poll_interval`(기본 10m)마다 조건을 확인하므로, 롤오버가 끝난 인덱스는 보통 2억건을 조금 넘습니다.

| 판정 | 기준 |
| --- | --- |
| SHD-008 | write index 나 rollover 를 쓰지 않는 인덱스의 샤드가 2억건 이상(공식). searchable snapshot mount 는 쓰기가 없으므로 SHD-013 기준으로 판정 |
| SHD-013 | 롤오버가 끝난 인덱스의 샤드가 2억건을 5% 넘게 초과: rollover 지연(도구 판단) |
| SHD-014 | logsdb 인덱스의 최대 primary shard 가 30GB 이상 50GB 미만(도구 판단, 참고) |
| SHD-015 | logsdb data stream 에서 10GB 미만, 2억건 미만으로 롤오버된 인덱스가 5개 이상(공식 하한, 참고, data stream 별 표) |
| IDX-013 | 9.0 이상에서 write index 가 logsdb 가 아닌 `logs-*-*` data stream(참고) |
| ILM-007 | `max_primary_shard_docs` 가 2억건 초과(효과 없음, 공식) |
| ILM-008 | 1 segment force merge 를 하는 tier 의 여유 디스크가 가장 큰 primary shard 의 3배 미만(공식) |
| ILM-009 | force merge 단계에 24시간 이상 머문 인덱스(도구 판단, 참고) |

logsdb 는 공간 효율이 좋아 대개 50GB 보다 2억건에 먼저 닿습니다. 공식 범위는 10~50GB 그대로 두고, logsdb 에만 30GB 를 도구 기준 상한으로 둡니다. 이유는 index sorting 의 merge 비용, 1 segment force merge 의 여유 공간(최대 3배), 복구 시간입니다(각각 공식 문서 근거). 30GB 자체는 공식 수치가 아니라 Elastic 내부 논의를 따른 값이며, 판정 표에 인덱스별 최대 shard 크기, 문서 수, 문서당 크기, 추정 rollover 조건을 보여 줍니다. partial mount(frozen) 인덱스는 크기가 캐시 크기라 제외합니다.

### 비교 모드

| 판정 | 내용 |
| --- | --- |
| DIF-001 | 클러스터 상태 악화/개선 |
| DIF-002~003 | 노드 재기동(uptime 역전), 노드 이탈·신규 |
| DIF-004~005 | rejection 증가분과 시간당 발생률(증가 없으면 과거 이력으로 분류) |
| DIF-006~007 | 구간 내 old GC 비중, circuit breaker 발동 증가분 |
| DIF-008 | 디스크 증가 속도 → high watermark 도달 예상일, tier 단위 판정(선형 외삽, frozen 제외) |
| DIF-009~011 | 구간 처리량과 분포, 인덱스 증가량, 인덱스 생성·삭제 |
| DIF-012 | 판정 변화(신규 발생 / 악화 / 해소) |
| DIF-013 | 두 번들이 다른 클러스터(cluster_uuid 불일치 등)면 경고. 비교 판정은 참고로만 볼 것 |

---

## 리포트 구성

HTML 리포트(단일 파일)의 순서입니다. Markdown·콘솔도 같은 내용을 담습니다.

1. 헤더 — 클러스터, 버전, 배포 형태, 수집 시각·모드, 도구 버전·판정 기준, 종합 판정, 심각도 분포
2. **병목 요약** — 다섯 가지 질문별 판단, 그 판단의 근거가 된 증상과 판정, 다음에 볼 곳(아래 참고)
3. 조치 우선순위 — 치명·주의 목록, 클릭하면 해당 판정으로 이동
4. **영역별 점검 결과** — 가용성 / 자원·용량 / 데이터 구조 / 성능 / 데이터 보호·운영 / 보안 / 구성의 상태와 건수
5. 이전 번들 대비 변화(`--baseline` 지정 시), 노드별 이전/지금 표 포함
6. 노드 상태 한눈에 보기 — heap·CPU·load·디스크·샤드 수 막대
7. 저장 용량 상위 인덱스
8. 필터 — 심각도 × 분류 조합, 그리고 인덱스·노드·tier 이름으로 판정과 근거 표의 행을 거르는 검색창
9. 판정 결과 — 헬스 체크 영역 순서로, 관측 / 영향 / 권고 / 근거 표 / 출처 파일 / 참고 문서, 근거 구분 표기
10. 판정 근거 구분 설명, 확인하지 못한 항목(입력 미수집·도구 오류)

### 병목 요약

| 질문 | 먼저 보는 증상 | 증상이 있을 때 원인을 보는 순서 |
| --- | --- | --- |
| 색인이 따라가고 있는가 | write 거부, write 큐, indexing pressure 거부, 현재 색인 throttle | 스토리지(IDX-005, PERF-012, IDX-014, DISK-008, IDX-015, PERF-009) → 메모리(JVM-001, JVM-005, BRK-*, IP-001) → CPU(HOT-005, OS-001, OS-003) → 쓰기 부하 편중(SHD-016, HOT-002, HOT-001, SHD-006, SHD-012) → ingest 파이프라인(ING-002, ING-001) → 인덱스 설정(IDX-007, PERF-004) |
| 검색이 느린가 | search 거부, search 큐, 높은 지연(PERF-001·002), CPU 는 낮은데 바쁜 search 풀(PERF-013) | 메모리 → CPU → 스토리지(PERF-013, FRZ-*, DISK-008, PERF-009, PERF-003) → 쿼리 비용(PERF-011, PERF-010, PERF-005, GEN-001) → 샤드 수(SHD-001, OVS-*, SHD-004, SHD-009) → 검색 부하 편중. PERF-013 이 있으면 스토리지를 맨 앞에서 본다 |
| 스토리지가 한계인가 | 없음 | IDX-005, PERF-012, IDX-014, DISK-008, PERF-013, FRZ-002, FRZ-001, PERF-009, IDX-015 |
| 재시작이나 복구가 수치를 왜곡하는가 | 없음 | OS-007 → DIF-002 → OS-006 → CLU-020, REC-001, HOT-003 |
| 용량 부족인가, 편중인가 | 없음 | tier CPU(HOT-005) → 디스크(DISK-001~003, DIF-008, COST-004) → 편중(HOT-001, HOT-002, SHD-006, SHD-016, NODE-001) |

원인은 해당 판정이 치명이나 주의일 때만 셉니다(PERF-013 은 참고여도 셉니다). 증상이 특정 노드에 있으면(그 노드의 큐나 거부, PERF-013 노드), 노드를 지목하는 판정은 그 노드나 같은 데이터 tier 의 다른 노드를 지목할 때만 셉니다. 그래서 frozen 노드의 높은 heap 은 hot 노드 write 큐의 원인으로 나오지 않습니다. 판정이 있는 첫 그룹이 판단이 되고, 판정이 있는 나머지 그룹은 뒤에 함께 적습니다. 증상이 없으면 그렇다고만 적고 원인은 짚지 않습니다. 증상은 있는데 어느 그룹에도 판정이 없으면 Elasticsearch 밖(클라이언트, 쿼리)을 보라고 안내합니다. 이 순서는 어디부터 볼지에 대한 도구 판단이며 공식 판단 트리가 아닙니다. `--only` 로 룰 일부만 돌리면 요약은 빠집니다. Markdown, 콘솔, JSON(`bottleneck`), Support 팀 요약에도 들어갑니다.

### 헬스 체크 영역

| 영역 | 포함 분류 | 대표 판정 |
| --- | --- | --- |
| 가용성 | 클러스터 | 상태·미할당 샤드·마스터 정족수·샤드 한도·노드 종료·voting exclusion |
| 자원·용량 | 노드, 핫스팟·밸런싱, 스토리지 비용 | heap·GC·CPU·디스크·워터마크·스레드풀·circuit breaker·tier 포화·편중·hot 잔류 데이터·검색 없는 replica·수집 여유·데이터 종류별 저장량·tier 별 사이징 신호 |
| 데이터 구조 | 샤드·인덱스, 벡터 검색 | 샤드 크기·과다 샤딩·매핑 한도·쓰기 차단·벡터 메모리 |
| 성능 | 성능 기준, 런타임 | 비용이 큰 검색 패턴·캐시·ingest·hot threads·로그 |
| 데이터 보호·운영 | 운영 | 스냅샷 RPO·SLM·ILM·라이선스·모니터링·ML |
| 보안 | 보안·인증 | 보안 기능·TLS 인증서 만료 |
| 구성 | 설정 기준, 설정 변경 | 공식 필수 설정·기본값 대비 변경 |

---

## Elastic 공식 Support 팀 요약

`--support-summary FILE` 을 지정하면 분석 리포트와 별도로, Elastic 공식 Support 팀에 문의할 때 케이스에 붙일 수 있는 요약 Markdown 을 만듭니다. 지정하지 않으면 만들지 않습니다.

```bash
python3 analyze.py diagnostic.zip --support-summary support-summary.md            # 기본 basic 마스킹
python3 analyze.py diagnostic.zip --support-summary support-summary.md --mask strict
```

**담는 것**: 클러스터 개요, 영역별 점검 결과, 치명·주의 판정의 관측 사실·근거 구분·번들 내 근거 파일·근거 표(최대 10행), 참고 판정, 확인하지 못한 항목, 노드 요약.
**담지 않는 것**: 도구의 조치 권고 문구, 서버 로그 발췌 원문, hot threads 스레드 이름과 스택. 로그 판정은 건수·분류만 남습니다.

마스킹은 값을 `node-001`, `ip-001`, `path-001` 같은 별칭으로 바꾸며, 같은 값은 항상 같은 별칭입니다. 원래 값은 매핑 파일(`*.mask-map.json`, 권한 0600)에만 있으므로 Support 팀 답변의 별칭을 되돌려 볼 수 있습니다. **매핑 파일은 고객 환경 밖으로 내보내지 마십시오.**

| 단계 | 대상 |
| --- | --- |
| `none` | 마스킹하지 않음 |
| `basic`(기본) | 클러스터 이름·UUID, 노드 이름·ID·호스트·IP·전송 주소, 노드 설정의 경로·주소·URL·버킷 값, 인증서 경로·subject, 라이선스 발급 대상, 저장소 버킷·경로·엔드포인트 |
| `strict` | basic + 인덱스·별칭·데이터 스트림·백킹 인덱스, ILM·SLM 정책, 템플릿, 파이프라인, 저장소·스냅샷, ML·transform·rollup ID |

출력 문자열마다 마스킹을 적용한 뒤, 원본 식별자(대소문자 무시)와 등록되지 않은 IPv4 가 남았는지 별도로 검사합니다. 하나라도 남으면 **요약과 매핑 파일을 쓰지 않고** 종료 코드 2 로 끝납니다. 이 검사는 번들에서 수집한 식별자 기준이므로, 요약을 보내기 전에 눈으로 한 번 확인하십시오.

한계: 6자 미만 값은 일반 단어와 겹칠 수 있어 남았는지 검사하지 않습니다. `.` 로 시작하는 시스템 인덱스, 기본 설치 경로, 루프백 주소, 버전·시각은 마스킹하지 않습니다. 이 요약은 Support 케이스를 대신하지 않으며, 원본 진단 번들을 요청받는 경우는 별도입니다.

---

## 문서

| 문서 | 내용 |
| --- | --- |
| [RULES.ko.md](RULES.ko.md) ([English](RULES.md)) | 133개 룰 전체 명세 — 판정 조건, 임계값(현재 값·출처), 필요 입력, 참고 문서, 설정 지식 베이스. **코드에서 자동 생성** |
| [COVERAGE.ko.md](COVERAGE.ko.md) ([English](COVERAGE.md)) | Elastic 공식 문서 항목별 반영 여부와 판정할 수 없는 항목의 이유 |
| [CHANGELOG.ko.md](CHANGELOG.ko.md) ([English](CHANGELOG.md)) | 변경 이력 — 이전 동작 → 현재 동작과 근거 |

RULES.md 와 RULES.ko.md 는 직접 수정하지 않습니다. 룰을 바꾼 뒤 재생성합니다.

```bash
python3 tools/gen_rules_doc.py            # RULES.md, RULES.ko.md 재생성
python3 tools/gen_rules_doc.py --check    # 임계값 누락·미사용, docstring 누락 검사
```

---

## 임계값 조정

```bash
python3 analyze.py --print-thresholds > my.json   # 기본값 추출
# my.json 에서 필요한 키만 남기고 수정
python3 analyze.py bundle.zip --thresholds my.json
```

임계값 141개의 출처(`[공식]` / `[도구]`)는 `esdoctor/thresholds.py` 주석과 RULES.md 부록에 있습니다. `[공식]` 값은 바꾸지 않는 것을 권장합니다.

---

## 룰 추가

1. 해당 모듈(`esdoctor/rules/*.py`)에 함수를 만들고 `RULES` 에 등록합니다.
2. 함수 docstring 에 판정 조건을 정확히 적습니다(RULES.md 에 그대로 실립니다).
3. 필요한 입력 파일을 `esdoctor/rules/__init__.py` 의 `REQUIRES` 에 선언합니다.
4. 판정 ID 의 근거 구분을 `esdoctor/basis.py` 에 등록합니다.
5. 새 임계값은 `esdoctor/thresholds.py` 에 출처 주석과 함께 추가합니다.
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

사용자에게 보이는 문구는 코드에 직접 쓰지 않고 `esdoctor/i18n/ko.txt` 와 `en.txt` 에 같은 키로 넣고 `T("키")` 로 읽습니다. 표 안의 문구는 `N_("키")` 로 표시하고 쓰는 곳에서 `tr()` 로 바꿉니다. 문체와 용어는 [docs/STYLE.md](docs/STYLE.md) 를 따르고, `tests/i18n_check.py` 가 두 카탈로그의 키·`%` 필드·대시를 검사합니다.

문자열에 `%` 를 쓰고 `%` 포맷을 적용할 때는 `%%` 로 씁니다(`tests/lint_format.py` 가 검사합니다).

---

## 검증

```bash
bash tests/run_all.sh diagnostic.zip
```

| 검사 | 내용 | 현재 결과 |
| --- | --- | --- |
| `tests/lint_format.py` | `%` 포맷 문자열 정적 검사 — 실행되지 않는 분기의 포맷 오류까지 | 985개, 문제 0 |
| `tests/verify_logic.py` | 계산 로직 단정문 — 워터마크, GC 로그, 설정 지식 베이스 교차 검증, 다중 tier·마운트 인덱스·쓰기 차단 재현. 한국어·영어 두 언어로 실행 | 110개 통과 |
| `tests/drive_branches.py` | 시나리오 63개로 모든 판정 분기를 강제 실행하고 심각도까지 확인 | 63개 통과, 미실행 판정 분기 0 |
| `tests/fuzz_rules.py` | 필드 누락·null·문자열 숫자 변형(`--harsh` 는 임의 타입) | 실패 0 |
| `tools/gen_rules_doc.py --check` | 임계값·docstring 정합성 | 문제 0 |
| `tests/test_local_mode.py` | local/remote 모드 전용 처리(logs/ 오탐·gz·이중 집계, syscalls/ 분기, 수집 실패 안내)를 합성 데이터로 검증. 외부 번들 불필요 | 실패 0 |
| `tests/test_logsdb.py` | 문서 수 한도·logsdb·force merge 판정(SHD-008·013·014·015, IDX-013, ILM-007·008·009)의 모든 분기를 합성 데이터로 두 언어 모두 검증. 외부 번들 불필요 | 실패 0 |
| `tests/test_write_path.py` | 쓰기 경로·운영 판정(PERF-012, OS-007, SHD-016, IDX-014·015, CLU-017, MAP-004, DIF-013)의 분기를 합성 데이터로 두 언어 모두 검증. 외부 번들 불필요 | 실패 0 |
| `tests/test_doc_audit.py` | 공식 문서 재대조로 고친 부분(JVM-002 oops 플래그, CLU-007, DISK-006, DISK-007, IDX-013, CLU-015, SHD-010, MAP-006, max_headroom 조건, 개발 모드, 상황에 따라 달라지는 설정 기본값)을 합성 데이터로 두 언어 모두 검증. 외부 번들 불필요 | 실패 0 |
| `tests/test_es95.py` | Elasticsearch 9.5 기준: 버전별 merge policy 기본값, columnar·logsdb_columnar·vectordb_document index mode(DISK-006, DISK-007, IDX-013, PERF-008, SET-006), 모니터링 플러그인 deprecation(OPS-007)을 합성 데이터로 두 언어 모두 검증. 외부 번들 불필요 | 실패 0 |
| `tests/test_bottleneck_cost.py` | 병목 요약, 최근 재시작 노드의 비교 제외(HOT-001·002, PERF-012, DIF-009), FRZ-002, PERF-013, ING-001, COST-001~006, 증상 tier 로 좁힌 병목 원인, tier 단위 DIF-008, DIF-014 구간 검사, tier 단위 SET-005 를 합성 데이터로 두 언어 모두 검증. 외부 번들 불필요 | 실패 0 |
| `tests/test_handoff.py` | Support 팀 요약: 카나리 식별자(클러스터·노드·호스트·IP·경로·인증서·라이선스·저장소·인덱스·로그·스택)가 단계별로 남지 않는지, 매핑 왕복, 마스킹 실패 시 요약 미생성, CLI 옵션. 외부 번들 불필요 | 실패 0 |
| `tests/check_docs.py` | README·RULES·COVERAGE·CHANGELOG 의 수치·목록·링크가 코드와 일치하는지, 판정 ID 와 근거 구분 표 대조 | 불일치 0 |

`tests/make_broken_bundle.py` 는 정상 번들에 장애 상황을 주입한 번들을 만듭니다(리포트 예시·수동 확인용).

---

## 한계

- **remote 모드와 다중 노드 local 모드는 실번들로 검증하지 않았습니다.** local 모드는 단일 노드 테스트 환경 1건으로 확인했으며, 운영 규모 번들에서는 파일 구성(예: 노드별 로그 파일명)이 다를 수 있습니다.

아래는 도구가 아니라 진단 번들 수집 범위에서 오는 한계입니다.

- **쿼리 본문이 없습니다.** 쿼리 유형별 누적 사용 횟수(`cluster_stats.indices.search`)로 비용이 큰 패턴의 비중은 판정하지만(PERF-011), 어떤 인덱스의 어떤 쿼리인지는 slowlog 나 Search Profiler 로 확인해야 합니다.
- **보안 구성(사용자·역할·권한)은 판정하지 않습니다.** 보안 감사 영역이고 민감 정보라, 보안 기능 활성화와 인증서 만료만 봅니다.
- **인덱스 설정의 기본값은 번들에 없습니다.** 인덱스 설정 지식 베이스(32종)는 공식 문서 기준이며 번들로 교차 검증되지 않습니다.
- **OS 커널 설정**(readahead, vm.swappiness, vm.max_map_count 원본값)은 api 모드 번들에 없어 판정하지 않습니다. local / remote 모드의 `syscalls/` 중 sysctl(vm.max_map_count, vm.swappiness), proc-limit(nofile, nproc), dmesg(OOM killer)만 읽습니다(SYS-001~004). readahead, THP, iostat, jstack, netstat 등은 아직 읽지 않습니다.
- **hot threads 는 수집 순간 500ms 스냅샷**입니다. 부하가 없을 때 수집하면 신호가 나오지 않습니다.
- 디스크 포화 예상(DIF-008)은 두 시점 사이의 선형 외삽입니다.

판정할 수 없는 항목 전체와 이유는 [COVERAGE.ko.md](COVERAGE.ko.md) 에 있습니다.

---

## 구조

```
.
├── analyze.py                  # CLI 진입점
├── requirements.txt            # 외부 의존성 없음(명시용)
├── esdoctor/
│   ├── __init__.py             # 버전, 판정 기준점, 버전 분기
│   ├── loader.py               # zip/디렉터리 로딩, api·local·remote 레이아웃 흡수
│   ├── context.py              # 정규화 계층: 실효 워터마크, tier, 인덱스 분류, 쓰기 대상, 배포 형태
│   ├── thresholds.py           # 전체 임계값(출처 주석 포함)
│   ├── settings_kb.py          # 설정 지식 베이스(기본값·종류·의미·영향)
│   ├── basis.py                # 판정 근거 구분
│   ├── engine.py               # 룰 실행·격리, 미수집 처리, 종합 판정, 버전 점검
│   ├── envcheck.py             # 실행 환경 점검(--check-env)
│   ├── mask.py                 # Support 팀 요약용 마스킹(별칭 치환, 누출 검사)
│   ├── diff.py                 # 두 번들 비교
│   ├── bottleneck.py           # 병목 요약(증상과 판정으로 다섯 가지 질문에 답함)
│   ├── i18n/                   # ko.txt · en.txt 메시지 카탈로그, T() / tr() / N_()
│   ├── model.py                # Finding / Severity
│   ├── util.py                 # 단위 파싱, 안전 접근자(num·dicts·strs·items)
│   ├── rules/                  # cluster · settings · nodes · shards · sharding · guidance · hotspot · cost · ops · deep · runtime
│   └── report/                 # text(콘솔·Markdown) · html(단일 파일) · handoff(Support 팀 요약)
├── tools/
│   ├── gen_rules_doc.py        # RULES.md 생성기 + 정합성 검사
│   ├── build_pyz.py            # 단일 파일 배포본(esdoctor.pyz) 빌드(선택)
│   └── build_binary.sh         # 단독 실행 파일 빌드(선택)
├── tests/
│   ├── run_all.sh              # 전체 검증
│   ├── i18n_check.py           # 메시지 카탈로그 검사(키·필드·대시)
│   ├── check_docs.py           # 문서 정합성 검사
│   ├── lint_format.py          # 포맷 문자열 정적 검사
│   ├── verify_logic.py         # 계산 로직 단정문
│   ├── drive_branches.py       # 판정 분기 구동
│   ├── fuzz_rules.py           # 입력 변형 퍼징
│   ├── test_handoff.py         # Support 팀 요약·마스킹 검증(합성 데이터)
│   ├── test_logsdb.py          # 문서 수 한도·logsdb·force merge 판정 검증(합성 데이터)
│   ├── test_write_path.py      # 쓰기 경로·운영 판정 검증(합성 데이터)
│   ├── test_bottleneck_cost.py # 병목 요약·스토리지 비용 판정 검증(합성 데이터)
│   ├── test_doc_audit.py       # 공식 문서 재대조 수정 사항 검증(합성 데이터)
│   ├── test_es95.py            # Elasticsearch 9.5 기준 검증(합성 데이터)
│   └── make_broken_bundle.py   # 장애 주입 번들 생성
├── docs/STYLE.md              # 문체·용어 규칙
├── README.md / README.ko.md
├── RULES.md / RULES.ko.md      # 룰 명세(자동 생성)
├── COVERAGE.md / .ko.md        # 공식 문서 대조표
└── CHANGELOG.md / .ko.md       # 변경 이력
```

---

## 릴리스 절차

```bash
# 1) esdoctor/__init__.py 의 __version__ 과 CHANGELOG.md 를 갱신
# 2) 명세 재생성과 전체 검증
python3 tools/gen_rules_doc.py
bash tests/run_all.sh <검증용 번들.zip>
# 3) (선택) 단일 파일 배포본 생성 → GitHub Releases 에 첨부(저장소에는 넣지 않음)
python3 tools/build_pyz.py        # dist/esdoctor.pyz
git tag v0.13.0
```

검증용 진단 번들과 그 분석 리포트에는 고객 환경 정보(클러스터 이름, 인덱스 이름, 호스트)가 들어 있으므로 저장소에 올리지 않습니다.

---

## 라이선스

This project is open-sourced software licensed under the [MIT license](LICENSE).
