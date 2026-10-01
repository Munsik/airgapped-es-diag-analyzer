"""Diagnostic result model."""

from .i18n import T, tr


class Severity(object):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"
    OK = "OK"

    ORDER = {CRITICAL: 0, WARNING: 1, INFO: 2, OK: 3}
    # Health score penalty weights
    WEIGHT = {CRITICAL: 18, WARNING: 6, INFO: 0, OK: 0}
    # Catalog keys of the display labels
    LABEL_KEY = {
        CRITICAL: "sev.critical",
        WARNING: "sev.warning",
        INFO: "sev.info",
        OK: "sev.ok",
    }

    @classmethod
    def label(cls, severity):
        """Display label of a severity in the current language."""
        return T(cls.LABEL_KEY[severity])


def category_label(category):
    """Display label of a category id (cluster, node, shard ...) in the current language."""
    return T("cat." + str(category))


class Finding(object):
    """Result of one rule.

    id           : rule id (for example JVM-001)
    category     : category id (cluster, node, shard, ops, security ...); category_label() gives the text
    severity     : Severity value
    title        : one-line title
    observed     : the value actually observed (the fact)
    impact       : what this state causes
    recommend    : recommended action (may include commands or settings)
    evidence     : table {"columns": [...], "rows": [[...], ...]} or None
    affected     : affected targets (node or index names)
    refs         : reference documents, (title, URL); a title that is a catalog key is translated
    source       : name of the file the finding rests on
    basis        : basis label in the current language (set by the engine); basis_id is the neutral id
    """

    __slots__ = (
        "id", "category", "severity", "title", "observed", "impact",
        "recommend", "evidence", "affected", "refs", "source", "basis", "basis_id",
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
        self.refs = [(tr(t), u) for t, u in (refs or [])]
        self.source = source
        self.basis = None
        self.basis_id = None

    def to_dict(self):
        return {
            "id": self.id,
            "category": category_label(self.category),
            "category_id": self.category,
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
            "basis_id": self.basis_id,
        }

    def __repr__(self):
        return "<Finding %s %s %s>" % (self.id, self.severity, self.title)


def table(columns, rows):
    return {"columns": list(columns), "rows": [list(r) for r in rows]}
