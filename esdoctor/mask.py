# -*- coding: utf-8 -*-
"""Identifier masking for the summary sent to Elastic Support.

Collects known identifiers from the bundle and replaces them with consistent aliases (node-001, index-003 ...).
Masking is not added to each rule. It is applied once to the whole string at the output step that builds the summary.

Levels
  none   no masking.
  basic  cluster name and UUID, node name and ID, hostname, IP, paths, certificate subject, license issued-to, repository settings
  strict basic + indices, data streams, aliases, ILM/SLM policies, templates, snapshot and repository names, pipelines, ML/Transform names

Rules
  - System names starting with a dot (.kibana etc.) and built-in names containing '@' (logs@lifecycle etc.) are not identifying, so they are kept.
  - loopback (127.0.0.1, ::1) and 0.0.0.0 are kept (needed for bind problem findings).
  - Only known names are replaced, so identifiers missing from the lists can slip through. leaks() therefore checks again just before output,
    and no file is written if anything remains.
"""

import collections
import ipaddress
import re
from .i18n import T

LEVELS = ("none", "basic", "strict")

# common words that are not identifying (stops the same word in the text from being replaced when a node is named exactly that)
_COMMON = frozenset([
    "elasticsearch", "elastic", "kibana", "logstash", "master", "data", "hot", "warm", "cold", "frozen",
    "content", "ingest", "node", "nodes", "default", "logs", "log", "metrics", "cluster", "test", "true",
    "false", "none", "all", "auto", "index", "indices", "shard", "shards", "es", "yml", "json", "path",
    # alias prefixes (so aliases are not replaced again)
    "uuid", "host", "cert", "org", "value", "alias", "policy", "template", "repo", "snapshot", "pipeline",
    "job", "datastream", "ip",
])

# default install paths do not identify an environment, so they are kept
_DEFAULT_PATHS = frozenset([
    "/usr/share/elasticsearch", "/usr/share/elasticsearch/data", "/usr/share/elasticsearch/logs",
    "/usr/share/elasticsearch/config", "/var/lib/elasticsearch", "/var/log/elasticsearch",
    "/etc/elasticsearch", "data", "logs", "config",
])

_SPAN = re.compile(r"[\w.@:/\\-]+", re.UNICODE)
_DELIM = re.compile(r"([-.:/\\@])")
_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w])")
_IPV6 = re.compile(r"(?<![\w:])[0-9A-Fa-f:]{2,45}(?![\w:])")

# node settings whose value may be identifying (partial match)
_SETTING_HINT = re.compile(
    r"(path|host|address|url|endpoint|bucket|location|dir$|file$|keystore|truststore|certificate|"
    r"cluster\.name|node\.name|initial_master_nodes|seed_hosts|\.key$)", re.I)
# node attributes whose value is replaced (partial match). Values needed for diagnosis, such as availability_zone, are kept
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
    """string or list of strings -> list of strings."""
    if isinstance(v, str):
        return [v]
    if isinstance(v, (list, tuple)):
        return [x for x in v if isinstance(x, str)]
    return []


def _walk(obj, want, out, depth=0):
    """Walks nested JSON and collects string values whose key is in want (a set of key names) into out."""
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
    """settings that mix flat and nested keys -> list of (key, value)."""
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
    """'host/1.2.3.4:9300', '[::1]:9300', '10.0.0.1:9300' -> list of host and IP parts."""
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
    """identifier -> alias replacer. The same value always gets the same alias."""

    def __init__(self, ctx=None, level="basic"):
        if level not in LEVELS:
            raise ValueError(T("mask.Masker.__init__.01") % level)
        self.level = level
        self._alias = {}                # lowercase original -> alias
        self._orig = {}                 # alias -> original (for the mapping file)
        self._kind = {}                 # alias -> kind
        self._seq = collections.Counter()
        self._simple = {}               # lookup by delimiter-separated token (lowercase)
        self._special = []              # values with spaces or commas that cannot be found by token (longest first)
        self._max_parts = 1
        if ctx is not None and level != "none":
            self._collect(ctx)
            self._special.sort(key=lambda s: -len(s))

    #     # ---------------- registration ----------------
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
        if not re.search("[A-Za-z0-9\uac00-\ud7a3]", v):
            return
        if re.match(r"^_\w+_$", v) or re.match(r"^-?\d+(\.\d+)?$", v):      # values like _local_ or 9200
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

    #     # ---------------- replacement ----------------
    def _alloc_ip(self, text):
        low = text.lower()
        if low not in self._alias:
            self.add("ip", text)
        return self._alias.get(low, text)

    def text(self, s):
        """Masks one string."""
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
        toks = _DELIM.split(span)               # [value, delimiter, value, delimiter, ...]
        n = len(toks)
        if n == 1:
            return span
        out, i = [], 0
        while i < n:
            if i % 2:                           # do not start at a delimiter position
                out.append(toks[i])
                i += 1
                continue
            hit = None
            for j in range(min(n, i + 2 * self._max_parts), i, -1):
                if j % 2 == 0:
                    continue                    # only spans that end with a value
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
        """Recursively masked copy of a string, list or dict."""
        if isinstance(v, str):
            return self.text(v)
        if isinstance(v, list):
            return [self.value(x) for x in v]
        if isinstance(v, tuple):
            return tuple(self.value(x) for x in v)
        if isinstance(v, dict):
            return dict((k, self.value(x)) for k, x in v.items())
        return v

    #     # ---------------- check and mapping ----------------
    def leaks(self, text):
        """If the masked result still contains an original identifier or IP, returns [(kind, alias)].

        Uses a case-insensitive substring search separate from the replacement logic (to catch cases missed because of word boundaries).
        Values shorter than 6 characters can overlap with ordinary words, so they are excluded from the check.
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
                found.append(("ip", T("mask.Masker.leaks.01")))
        return found

    def mapping(self):
        """alias -> {original, kind}. Kept only inside the air-gapped network."""
        return dict((a, {"original": o, "kind": self._kind[a]}) for a, o in sorted(self._orig.items()))

    def counts(self):
        return dict(self._seq)
