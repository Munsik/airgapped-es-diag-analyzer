"""진단 결과 모델."""


class Severity(object):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"
    OK = "OK"

    ORDER = {CRITICAL: 0, WARNING: 1, INFO: 2, OK: 3}
    # 헬스 스코어 감점 가중치
    WEIGHT = {CRITICAL: 18, WARNING: 6, INFO: 0, OK: 0}
    LABEL_KO = {
        CRITICAL: "치명",
        WARNING: "주의",
        INFO: "참고",
        OK: "정상",
    }


class Finding(object):
    """룰 1건의 판정 결과.

    id           : 룰 식별자 (예: JVM-001)
    category     : 화면 분류 (클러스터/노드/샤드·인덱스/운영/보안)
    severity     : Severity 값
    title        : 한 줄 제목
    observed     : 실제로 관측된 값(사실)
    impact       : 이 상태가 유발하는 영향
    recommend    : 조치 권고 (명령/설정 포함 가능)
    evidence     : 표 형태 근거 {"columns": [...], "rows": [[...], ...]} 또는 None
    affected     : 영향 대상 목록(노드명/인덱스명)
    refs         : 참고 문서 경로(오프라인에서도 의미 있는 문서 제목 + URL)
    source       : 근거 파일명
    """

    __slots__ = (
        "id", "category", "severity", "title", "observed", "impact",
        "recommend", "evidence", "affected", "refs", "source", "basis",
    )

    def __init__(self, id, category, severity, title, observed="",
                 impact="", recommend="", evidence=None, affected=None,
                 refs=None, source=""):
        self.id = id
        self.category = category
        self.severity = severity
        self.title = title
        self.observed = observed
        self.impact = impact
        self.recommend = recommend
        self.evidence = evidence
        self.affected = affected or []
        self.refs = refs or []
        self.source = source
        self.basis = None

    def to_dict(self):
        return {
            "id": self.id,
            "category": self.category,
            "severity": self.severity,
            "title": self.title,
            "observed": self.observed,
            "impact": self.impact,
            "recommend": self.recommend,
            "evidence": self.evidence,
            "affected": self.affected,
            "refs": self.refs,
            "source": self.source,
            "basis": self.basis,
        }

    def __repr__(self):
        return "<Finding %s %s %s>" % (self.id, self.severity, self.title)


def table(columns, rows):
    return {"columns": list(columns), "rows": [list(r) for r in rows]}
