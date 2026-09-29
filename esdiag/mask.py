# -*- coding: utf-8 -*-
"""Elastic 공식 Support 팀 전달용 요약의 식별자 마스킹.

번들에서 알려진 식별자를 모아 일관된 별칭(node-001, index-003 ...)으로 바꾼다.
룰마다 마스킹을 넣지 않고, 요약을 만드는 출력 단계에서 문자열 전체에 한 번 적용한다.

단계
  none   마스킹하지 않는다.
  basic  클러스터명·UUID, 노드명·ID, 호스트명, IP, 경로, 인증서 subject, 라이선스 발급 대상, 저장소 설정값
  strict basic + 인덱스·데이터 스트림·별칭, ILM/SLM 정책, 템플릿, 스냅샷·저장소 이름, 파이프라인, ML/Transform 이름

원칙
  - 점(.)으로 시작하는 시스템 이름(.kibana 등)과 '@' 가 들어간 기본 제공 이름(logs@lifecycle 등)은 식별 정보가 아니므로 바꾸지 않는다.
  - loopback(127.0.0.1, ::1)과 0.0.0.0 은 바꾸지 않는다(바인딩 문제 판정에 필요).
  - 알려진 이름만 바꾸는 방식이라 목록에 없는 식별자는 놓칠 수 있다. 그래서 출력 직전에 leaks() 로 다시 검사하고,
    남아 있으면 파일을 쓰지 않는다.
"""

import collections
import ipaddress
import re

LEVELS = ("none", "basic", "strict")

# 식별 정보가 아닌 흔한 단어(노드 이름이 이 단어 자체일 때 본문의 같은 단어까지 바뀌는 것을 막는다)
_COMMON = frozenset([
    "elasticsearch", "elastic", "kibana", "logstash", "master", "data", "hot", "warm", "cold", "frozen",
    "content", "ingest", "node", "nodes", "default", "logs", "log", "metrics", "cluster", "test", "true",
    "false", "none", "all", "auto", "index", "indices", "shard", "shards", "es", "yml", "json", "path",
    # 별칭 접두어(별칭이 다시 치환되지 않도록)
    "uuid", "host", "cert", "org", "value", "alias", "policy", "template", "repo", "snapshot", "pipeline",
    "job", "datastream", "ip",
])

# 기본 설치 경로는 환경을 특정하지 않으므로 그대로 둔다
_DEFAULT_PATHS = frozenset([
    "/usr/share/elasticsearch", "/usr/share/elasticsearch/data", "/usr/share/elasticsearch/logs",
    "/usr/share/elasticsearch/config", "/var/lib/elasticsearch", "/var/log/elasticsearch",
    "/etc/elasticsearch", "data", "logs", "config",
])

_SPAN = re.compile(r"[\w.@:/\\-]+", re.UNICODE)
_DELIM = re.compile(r"([-.:/\\@])")
_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w])")
_IPV6 = re.compile(r"(?<![\w:])[0-9A-Fa-f:]{2,45}(?![\w:])")

# 노드 설정 중 값이 식별 정보일 수 있는 키(부분 일치)
_SETTING_HINT = re.compile(
    r"(path|host|address|url|endpoint|bucket|location|dir$|file$|keystore|truststore|certificate|"
    r"cluster\.name|node\.name|initial_master_nodes|seed_hosts|\.key$)", re.I)
# 노드 attributes 중 값을 바꿀 키(부분 일치). availability_zone 처럼 진단에 필요한 값은 그대로 둔다
_ATTR_HINT = re.compile(r"(host|name|rack|pod|ip$|addr)", re.I)

_KIND_PREFIX = collections.OrderedDict([
    ("cluster", "cluster"), ("uuid", "uuid"), ("node", "node"), ("node_id", "node-id"), ("host", "host"),
    ("ip", "ip"), ("path", "path"), ("cert", "cert"), ("org", "org"), ("setting", "value"),
    ("index", "index"), ("datastream", "datastream"), ("alias", "alias"), ("policy", "policy"),
    ("template", "template"), ("repo", "repo"), ("snapshot", "snapshot"), ("pipeline", "pipeline"),
    ("job", "job"),
])


def _is_ip(text):
    try:
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def _keep_ip(text):
    try:
        a = ipaddress.ip_address(text)
    except ValueError:
        return True
    return a.is_loopback or a.is_unspecified


def _strs(v):
    """문자열 또는 문자열 목록 → 문자열 목록."""
    if isinstance(v, str):
        return [v]
    if isinstance(v, (list, tuple)):
        return [x for x in v if isinstance(x, str)]
    return []


def _walk(obj, want, out, depth=0):
    """중첩 JSON 을 훑어 want(키 이름 집합)에 해당하는 문자열 값을 out 에 모은다."""
    if depth > 8:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in want:
                out.extend(_strs(v))
            if isinstance(v, (dict, list)):
                _walk(v, want, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj[:5000]:
            if isinstance(v, (dict, list)):
                _walk(v, want, out, depth + 1)


def _flatten(d, prefix=""):
    """평탄/중첩이 섞인 settings 를 (키, 값) 목록으로."""
    out = []
    if isinstance(d, dict):
        for k, v in d.items():
            key = "%s%s" % (prefix, k)
            if isinstance(v, dict):
                out.extend(_flatten(v, key + "."))
            else:
                out.append((key, v))
    return out


def _addr_parts(text):
    """'host/1.2.3.4:9300', '[::1]:9300', '10.0.0.1:9300' → 호스트·IP 부분 목록."""
    parts = []
    for piece in str(text).split("/"):
        piece = piece.strip()
        if not piece:
            continue
        if piece.startswith("["):
            piece = piece[1:].split("]")[0]
        elif piece.count(":") == 1:
            piece = piece.split(":")[0]
        parts.append(piece)
    return parts


class Masker(object):
    """식별자 → 별칭 치환기. 같은 값은 항상 같은 별칭이 된다."""

    def __init__(self, ctx=None, level="basic"):
        if level not in LEVELS:
            raise ValueError("알 수 없는 마스킹 단계: %s" % level)
        self.level = level
        self._alias = {}                # 소문자 원본 → 별칭
        self._orig = {}                 # 별칭 → 원본(매핑 파일용)
        self._kind = {}                 # 별칭 → 종류
        self._seq = collections.Counter()
        self._simple = {}               # 구분자 단위 조회용(소문자)
        self._special = []              # 공백·쉼표 등이 들어 있어 구분자 단위로 못 찾는 값(긴 것부터)
        self._max_parts = 1
        if ctx is not None and level != "none":
            self._collect(ctx)
            self._special.sort(key=lambda s: -len(s))

    # ---------------- 등록 ----------------
    def add(self, kind, value):
        if self.level == "none" or not isinstance(value, str):
            return
        v = value.strip()
        if len(v) < 3:
            return
        low = v.lower()
        if low in self._alias or low in _COMMON or low in _DEFAULT_PATHS:
            return
        if v.startswith(".") or ("@" in v and kind in ("policy", "template")):
            return
        if not re.search(r"[A-Za-z0-9가-힣]", v):
            return
        if re.match(r"^_\w+_$", v) or re.match(r"^-?\d+(\.\d+)?$", v):      # _local_, 9200 같은 값
            return
        if _is_ip(v) and _keep_ip(v):
            return
        self._seq[kind] += 1
        alias = "%s-%03d" % (_KIND_PREFIX.get(kind, kind), self._seq[kind])
        self._alias[low] = alias
        self._orig[alias] = v
        self._kind[alias] = kind
        if _SPAN.fullmatch(v):
            self._simple[low] = alias
            self._max_parts = max(self._max_parts, len(_DELIM.split(v)))
        else:
            self._special.append(v)

    def _collect(self, ctx):
        add = self.add
        # ---- basic ----
        add("cluster", ctx.cluster_name if ctx.cluster_name != "-" else None)
        add("uuid", ctx.version_doc.get("cluster_uuid"))
        for n in ctx.nodes:
            add("node", n.name)
            add("node_id", n.id)
            add("host", n.host)
            for src in (n.info, n.stats):
                add("ip", src.get("ip"))
                add("host", src.get("host"))
                for p in _addr_parts(src.get("transport_address") or ""):
                    add("ip" if _is_ip(p) else "host", p)
            for grp in ("http", "transport"):
                blk = n.info.get(grp) if isinstance(n.info.get(grp), dict) else {}
                for key in ("publish_address", "bound_address"):
                    for a in _strs(blk.get(key)):
                        for p in _addr_parts(a):
                            add("ip" if _is_ip(p) else "host", p)
            for k, v in (n.attrs or {}).items():
                if _ATTR_HINT.search(str(k)):
                    for s in _strs(v):
                        add("host", s)
            for k, v in _flatten(n.info.get("settings") or {}):
                if _SETTING_HINT.search(k):
                    kind = "path" if "path" in k else "setting"
                    for s in _strs(v):
                        for piece in (s.split(",") if "hosts" in k or "master_nodes" in k else [s]):
                            add(kind, piece.strip())
        for row in list(ctx.shards) + list(ctx.cat_nodes) + list(ctx.cat_allocation):
            if isinstance(row, dict):
                for key in ("node", "name", "host", "ip", "id"):
                    add("ip" if key == "ip" else "node", row.get(key))
        ad = []
        _walk(ctx.allocation_explain, {"node_name", "node_id", "transport_address"}, ad)
        _walk(ctx.recovery, {"source_node", "target_node", "source_host", "target_host", "host", "ip",
                             "transport_address"}, ad)
        for s in ad:
            for p in _addr_parts(s):
                add("ip" if _is_ip(p) else "node", p)
        for c in ctx.ssl_certs:
            if isinstance(c, dict):
                add("path", c.get("path"))
                dn = c.get("subject_dn")
                add("cert", dn)
                for s in _strs(dn):
                    for m in re.finditer(r"(?:CN|O|OU|DC|L|ST|C)=([^,]+)", s):
                        add("cert", m.group(1).strip())
        lic = ctx.license or {}
        add("org", lic.get("issued_to"))
        add("uuid", lic.get("uid"))
        add("org", lic.get("issuer"))
        rp = []
        _walk(ctx.repositories, {"bucket", "base_path", "location", "container", "endpoint", "client"}, rp)
        for s in rp:
            add("setting", s)
        if self.level != "strict":
            return
        # ---- strict ----
        for name in ctx.indices_stats:
            add("index", name)
        for sh in ctx.shards:
            add("index", sh.get("index"))
        for row in ctx.cat_indices:
            if isinstance(row, dict):
                add("index", row.get("index"))
        for name, body in (ctx.index_settings or {}).items():
            add("index", name)
            st = (body or {}).get("settings") if isinstance(body, dict) else None
            idx = (st or {}).get("index") if isinstance(st, dict) else None
            if isinstance(idx, dict):
                add("index", idx.get("provided_name"))
                add("uuid", idx.get("uuid"))
        for name, body in (ctx.aliases or {}).items():
            add("index", name)
            for alias in ((body or {}).get("aliases") or {}) if isinstance(body, dict) else []:
                add("alias", alias)
        for ds in ctx.data_streams or []:
            if isinstance(ds, dict):
                add("datastream", ds.get("name"))
                for i in ds.get("indices") or []:
                    if isinstance(i, dict):
                        add("index", i.get("index_name"))
                        add("uuid", i.get("index_uuid"))
        for name in ctx.ilm_explain or {}:
            add("index", name)
        for name in list(ctx.ilm_policies or {}) + list(ctx.slm_policies or {}):
            add("policy", name)
        for t in (ctx.index_templates or {}).get("index_templates") or []:
            if isinstance(t, dict):
                add("template", t.get("name"))
                pats = []
                _walk(t, {"index_patterns"}, pats)
                for p in pats:
                    add("template", p)
        for t in (ctx.component_templates or {}).get("component_templates") or []:
            if isinstance(t, dict):
                add("template", t.get("name"))
        for name in ctx.legacy_templates or {}:
            add("template", name)
        for name in ctx.pipelines or {}:
            add("pipeline", name)
        for r in ctx.repositories:
            if isinstance(r, dict):
                add("repo", r.get("id") or r.get("name"))
        misc = []
        _walk(ctx.snapshots, {"snapshot", "repository"}, misc)
        for s in misc:
            add("snapshot", s)
        ids = []
        _walk([ctx.ml_anomaly, ctx.ml_datafeed_stats, ctx.transform_stats, ctx.rollup_jobs, ctx.ml_trained_stats],
              {"job_id", "datafeed_id", "model_id", "id"}, ids)
        for s in ids:
            add("job", s)

    # ---------------- 치환 ----------------
    def _alloc_ip(self, text):
        low = text.lower()
        if low not in self._alias:
            self.add("ip", text)
        return self._alias.get(low, text)

    def text(self, s):
        """문자열 한 개를 마스킹한다."""
        if self.level == "none" or not isinstance(s, str) or not s:
            return s
        for v in self._special:
            if v.lower() in s.lower():
                s = re.sub(re.escape(v), self._alias[v.lower()], s, flags=re.I)
        s = _SPAN.sub(lambda m: self._span(m.group(0)), s)
        s = _IPV4.sub(lambda m: self._ip4(m.group(0)), s)
        s = _IPV6.sub(lambda m: self._ip6(m.group(0)), s)
        return s

    def _span(self, span):
        low = span.lower()
        if low in self._simple:
            return self._simple[low]
        toks = _DELIM.split(span)               # [값, 구분자, 값, 구분자, ...]
        n = len(toks)
        if n == 1:
            return span
        out, i = [], 0
        while i < n:
            if i % 2:                           # 구분자 위치에서는 시작하지 않는다
                out.append(toks[i])
                i += 1
                continue
            hit = None
            for j in range(min(n, i + 2 * self._max_parts), i, -1):
                if j % 2 == 0:
                    continue                    # 값으로 끝나는 구간만
                cand = "".join(toks[i:j]).lower()
                if cand in self._simple:
                    hit = (j, self._simple[cand])
                    break
            if hit:
                out.append(hit[1])
                i = hit[0]
            else:
                out.append(toks[i])
                i += 1
        return "".join(out)

    def _ip4(self, text):
        if any(int(p) > 255 for p in text.split(".")) or _keep_ip(text):
            return text
        return self._alloc_ip(text)

    def _ip6(self, text):
        if text.count(":") < 2 or not (("::" in text) or text.count(":") == 7):
            return text
        if not _is_ip(text) or _keep_ip(text):
            return text
        return self._alloc_ip(text)

    def value(self, v):
        """문자열·목록·dict 를 재귀적으로 마스킹한 사본."""
        if isinstance(v, str):
            return self.text(v)
        if isinstance(v, list):
            return [self.value(x) for x in v]
        if isinstance(v, tuple):
            return tuple(self.value(x) for x in v)
        if isinstance(v, dict):
            return dict((k, self.value(x)) for k, x in v.items())
        return v

    # ---------------- 검사·매핑 ----------------
    def leaks(self, text):
        """마스킹 결과에 원본 식별자나 IP 가 남아 있으면 [(종류, 별칭)] 로 돌려준다.

        치환 로직과 별개로 대소문자 무시 부분 문자열 검색을 쓴다(단어 경계 때문에 놓친 경우를 잡기 위함).
        길이 6 미만 값은 일반 단어와 겹칠 수 있어 검사에서 제외한다.
        """
        if self.level == "none":
            return []
        low = text.lower()
        found = []
        for alias, orig in self._orig.items():
            if len(orig) >= 6 and orig.lower() in low:
                found.append((self._kind[alias], alias))
        for m in _IPV4.finditer(text):
            if not any(int(p) > 255 for p in m.group(0).split(".")) and not _keep_ip(m.group(0)):
                found.append(("ip", "(미등록 IP)"))
        return found

    def mapping(self):
        """별칭 → {원본, 종류}. 폐쇄망 안에서만 보관한다."""
        return dict((a, {"original": o, "kind": self._kind[a]}) for a, o in sorted(self._orig.items()))

    def counts(self):
        return dict(self._seq)
