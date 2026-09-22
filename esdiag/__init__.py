"""
esdiag - Elastic support-diagnostics offline analyzer.

폐쇄망(air-gapped) 환경에서 Elasticsearch support-diagnostics 번들을 분석한다.
Python 3.8+ 표준 라이브러리만 사용하며 외부 네트워크 호출이 전혀 없다.
"""

__version__ = "0.9.0"

# ---------------------------------------------------------------------------
# 판정 기준점(baseline)
#   - ES_BASELINE      : 판정 로직·기본값·권고가 대조된 Elasticsearch 문서 버전
#   - DOCS_CHECKED     : 공식 문서를 대조한 시점
#   - VALIDATED_BUNDLE : 실제 진단 번들로 검증한 Elasticsearch 버전
#   - SUPPORTED_MIN    : 룰이 의미 있게 동작하는 최소 버전(이하는 일부 룰만 동작)
# 기준보다 새 버전을 분석하면 VER-001 로 경고한다(기본값·동작이 바뀌었을 수 있음).
# ---------------------------------------------------------------------------
ES_BASELINE = (9, 4)
DOCS_CHECKED = "2026-09"
VALIDATED_BUNDLE = "9.4.4 (ECH, 3노드 단일 tier) / 9.5.3 (ECH, 14노드 hot·warm·cold·frozen) — api 모드"
FIELD_TESTED = "9.5.3 다중 tier 번들로 오탐·미탐 교정, 파일·필드 구조 대조, 대형 번들(cluster_state 190MB·mapping 178MB) 메모리 검증"
SUPPORTED_MIN = (8, 0)
VALIDATED_MODES = "api 모드만 검증 — local / remote 모드(서버 로그·OS 명령 결과 포함)는 확인이 필요할 수 있음"

# 버전에 따라 판정이 갈리는 지점(RULES.md 에도 동일 표기)
VERSION_GATES = [
    ((8, 0), "SET-*", "action.destructive_requires_name 기본값 true"),
    ((8, 3), "SHD-001", "heap 1GB당 샤드 20개 기준은 8.3 미만에만 적용"),
    ((8, 5), "DISK-*", "디스크 워터마크 max_headroom(200/150/100GB) 적용"),
    ((8, 14), "VEC-002", "dense_vector index_options 미지정 시 int8_hnsw 기본(양자화)"),
    ((9, 1), "VEC-002", "384차원 이상 float 벡터는 bbq_hnsw 가 기본"),
    ((9, 2), "VEC-003", "index.mapping.exclude_source_vectors 기본 적용"),
]
