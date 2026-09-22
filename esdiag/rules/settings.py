# -*- coding: utf-8 -*-
"""설정 변경 분석.

공식 우선순위: transient > persistent > elasticsearch.yml > 기본값.
기본값과 다른 설정을 찾아 '원래 기본값 / 현재 값 / 의미 / 변경 영향 / dynamic·static' 을 보고한다.
기본값의 출처는 settings_kb(공식 문서 기준)이며, 등록되지 않은 설정은 값만 보고한다.
"""

import collections

from ..model import Finding, Severity, table
from ..util import items, num
from ..settings_kb import DOCS, compare, effect_of, lookup, risk_of

CAT = "설정 변경"
_SEV = {"WARNING": Severity.WARNING, "INFO": Severity.INFO, None: Severity.INFO}

# 노드마다 달라야 정상이거나 도구 판단 대상이 아닌 설정
_NODE_SPECIFIC = ("node.name", "node.attr.", "node.id", "node.roles", "node.external_id", "path.",
                  "network.", "http.host", "http.port", "http.publish", "http.bind", "transport.host",
                  "transport.port", "transport.publish", "transport.bind", "discovery.",
                  "cluster.initial_master_nodes", "cluster.name", "pidfile", "client.type",
                  "xpack.security.", "xpack.ml.config_version", "xpack.transform.config_version",
                  "cloud.", "s3.client.", "gcs.client.", "azure.client.", "node.pidfile")

# 노드 간 일치해야 하는 설정을 볼 범위(명시 설정된 경우)
_CONSISTENCY_PREFIX = ("indices.", "thread_pool.", "search.", "http.max_", "transport.compress",
                       "node.processors", "bootstrap.memory_lock", "xpack.ml.", "node.store.")


# 전용 룰이 따로 판정하는 설정 — 표에는 싣되 SET 판정의 심각도에는 반영하지 않는다(이중 판정 방지)
DEDICATED = {
    "cluster.routing.allocation.enable": "CLU-011", "cluster.routing.rebalance.enable": "CLU-011",
    "cluster.routing.allocation.disk.threshold_enabled": "CLU-011", "cluster.blocks.read_only": "CLU-011",
    "cluster.blocks.read_only_allow_delete": "CLU-011", "action.destructive_requires_name": "CLU-011",
    "cluster.routing.use_adaptive_replica_selection": "CLU-014", "cluster.max_shards_per_node": "CLU-015",
    "indices.recovery.max_bytes_per_sec": "REC-001", "search.default_search_timeout": "PERF-006",
    "cluster.routing.allocation.awareness.attributes": "CLU-019",
    "index.blocks.write": "IDX-008", "index.blocks.read_only": "IDX-008",
    "index.blocks.read_only_allow_delete": "IDX-008", "index.number_of_replicas": "IDX-001",
    "index.max_result_window": "GEN-001", "index.mapping.total_fields.limit": "MAP-001",
    "index.unassigned.node_left.delayed_timeout": "CLU-021", "index.refresh_interval": "IDX-007",
    "index.codec": "DISK-006", "index.store.preload": "PERF-008",
}


def _dedicated_note(key):
    for k, rid in DEDICATED.items():
        if key == k or (k.endswith(".") and key.startswith(k)):
            return rid
    if key.startswith("cluster.routing.allocation.exclude."):
        return "CLU-012"
    return None


def _flat(d, prefix=""):
    out = {}
    for k, v in items(d):
        key = prefix + "." + k if prefix else k
        if isinstance(v, dict):
            out.update(_flat(v, key))
        else:
            out[key] = v
    return out


def _es_defaults(ctx):
    return _flat((ctx.cluster_settings_defaults or {}).get("defaults") or {})


def _refs(*keys):
    out = [DOCS["stack"]]
    for k in keys:
        if k and DOCS.get(k) and DOCS[k] not in out:
            out.append(DOCS[k])
    return out


def _worst(sevs):
    order = {Severity.WARNING: 0, Severity.INFO: 1}
    return sorted(sevs, key=lambda s: order.get(s, 9))[0] if sevs else Severity.INFO


def r_cluster_setting_changes(ctx):
    """persistent / transient 에 명시된 모든 클러스터 설정을 공식 기본값과 비교한다.

    기본값이 공식 문서(settings_kb)에 등록된 설정은 '원래 기본값 / 방향(↑↓) / 변경 영향' 을 보고하고,
    미등록 설정은 값만 '설명 미등록' 으로 보고한다. 기본값과 같은 값을 명시한 경우는 '기본값과 동일' 로 참고 표기.
    심각도는 등록된 설정의 변경 방향별 위험도(risk) 중 최고값(최대 주의). 치명급 설정은 CLU-011 이 별도로 판정한다.
    변경 사항이 없으면 정상.
    """
    rows, sevs, docs, same = [], [], set(), []
    for scope in ("transient", "persistent"):
        for key, val in sorted(_flat(ctx.cluster_settings.get(scope) or {}).items()):
            changed, direction, spec, default, dsrc = compare(key, val)
            if not changed:
                same.append([scope, key, str(val)])
                continue
            kind = spec["kind"] if spec else "-"
            ded = _dedicated_note(key)
            rows.append([key, scope, str(default) if default is not None else "(미등록)", str(val),
                         kind, (spec or {}).get("meaning", "설명 미등록"),
                         effect_of(spec, direction) + ((" [판정: %s]" % ded) if ded else "")])
            if not ded:
                sevs.append(_SEV.get(risk_of(spec, direction), Severity.INFO))
            if spec:
                docs.add(spec["doc"])
    out = []
    if rows:
        orch = (" 이 클러스터는 %s 배포로 감지되어 일부 값은 플랫폼이 설정한 것일 수 있습니다." % ctx.deployment
                if ctx.orchestrated else "")
        out.append(Finding(
            "SET-001", CAT, _worst(sevs), "기본값에서 변경된 클러스터 설정",
            observed="persistent/transient 에 명시되어 기본값과 다른 클러스터 설정 %d건."
                     % len(rows) + orch + " [판정: …] 표시는 전용 룰이 따로 판정하므로 이 항목의 심각도에서 제외했습니다.",
            impact="공식 우선순위는 transient > persistent > elasticsearch.yml > 기본값입니다. 여기 있는 값이 "
                   "yml 과 기본값보다 우선 적용되고 있습니다. 표의 '변경 영향' 은 기본값 대비 방향(↑ 올림 / ↓ 내림)에 따른 "
                   "공식 문서 기준 부작용입니다.",
            recommend="의도한 변경인지, 임시 조치(롤링 재기동·장애 대응)가 남은 것인지 확인합니다. 임시 값은 "
                      "PUT _cluster/settings 에서 null 로 지정해 기본값으로 되돌립니다. transient 는 비권장이므로 "
                      "유지할 값은 persistent 로 옮깁니다.",
            evidence=table(["설정", "범위", "기본값", "현재 값", "종류", "의미", "변경 영향"], rows),
            refs=_refs("put", *sorted(docs)), source="cluster_settings.json"))
    else:
        out.append(Finding("SET-001", CAT, Severity.OK, "기본값에서 변경된 클러스터 설정 없음",
                           observed="persistent/transient 에 기본값과 다른 설정이 없습니다.",
                           refs=_refs("put"), source="cluster_settings.json"))
    if same:
        out.append(Finding(
            "SET-002", CAT, Severity.INFO, "기본값과 같은 값을 명시한 클러스터 설정",
            observed="기본값과 같은 값이 persistent/transient 에 명시된 설정 %d건." % len(same),
            impact="동작은 기본값과 같지만, 명시된 값은 이후 버전에서 기본값이 바뀌어도 따라가지 않습니다.",
            recommend="특별한 이유가 없다면 null 로 지정해 명시를 해제하는 것이 버전 업그레이드에 유리합니다.",
            evidence=table(["범위", "설정", "값"], same), refs=_refs("put"), source="cluster_settings.json"))
    return out


def _node_settings(n):
    return _flat(n.info.get("settings") or {})


def r_yml_shadowed(ctx):
    """elasticsearch.yml(노드 설정)에 있는 값이 persistent/transient 에 의해 가려지는지 확인한다.

    같은 키가 노드 설정과 클러스터 API 설정에 모두 있고 값이 다르면, 공식 우선순위에 따라 API 값이 적용되고
    yml 값은 무시된다(참고). yml 을 고쳐도 반영되지 않는 상황을 알리기 위함이다.
    """
    api = {}
    for scope in ("persistent", "transient"):
        for k, v in _flat(ctx.cluster_settings.get(scope) or {}).items():
            api[k] = (scope, v)          # transient 가 나중이므로 우선
    rows = []
    for n in ctx.nodes:
        for k, v in _node_settings(n).items():
            if k in api and str(api[k][1]) != str(v):
                rows.append([k, n.name, str(v), api[k][0], str(api[k][1])])
    if not rows:
        return []
    return [Finding(
        "SET-003", CAT, Severity.INFO, "elasticsearch.yml 값이 클러스터 설정 API 값에 가려짐",
        observed="yml 과 API 에 모두 있고 값이 다른 설정 %d건(노드 기준)." % len(rows),
        impact="yml 값은 무시되고 API 값이 적용됩니다. yml 을 수정해도 반영되지 않아 설정 추적이 어려워집니다.",
        recommend="한 곳으로 정리합니다. 동적 설정은 API(persistent)로, static 설정과 노드 고유 설정만 yml 에 둡니다.",
        evidence=table(["설정", "노드", "yml 값", "API 범위", "API 값(적용됨)"], rows[: ctx.t["top_n"] * 3]),
        refs=_refs("put"), source="nodes.json / cluster_settings.json")]


def r_node_setting_changes(ctx):
    """노드 설정(elasticsearch.yml, static 포함) 중 공식 기본값이 등록된 설정이 기본값과 다른지 확인한다.

    노드 고유 설정(이름·경로·네트워크·보안 인증서 등)은 제외한다. 노드별 값을 모아 설정 단위로 보고하며,
    심각도는 변경 방향별 위험도 중 최고값(최대 주의, 전용 룰 설정 제외). node.processors 는 실제 할당 CPU 수와
    같으면 변경으로 보지 않는다. ECH/ECE/ECK 로 감지되면 플랫폼 관리 값으로 보고 참고로 하향한다.
    static 설정은 모든 대상 노드의 yml 수정과 재기동이 필요하다.
    """
    agg = collections.OrderedDict()
    for n in ctx.nodes:
        for k, v in sorted(_node_settings(n).items()):
            if k.startswith(_NODE_SPECIFIC):
                continue
            spec = lookup(k)
            if not spec:
                continue
            changed, direction, spec, default, _src = compare(k, v)
            if not changed:
                continue
            alloc = num(n.info, "os", "allocated_processors") or n.processors
            expected = {"node.processors": alloc,
                        "thread_pool.write.size": alloc,
                        "thread_pool.search.size": (int(alloc * 3 / 2) + 1) if alloc else None}
            if k in expected and expected[k]:
                try:
                    if float(v) == float(expected[k]):
                        continue        # 자동 산정값과 같으면 변경이 아니다
                except (TypeError, ValueError):
                    pass
            agg.setdefault((k, str(v)), {"nodes": [], "spec": spec, "dir": direction, "default": default})
            agg[(k, str(v))]["nodes"].append(n.name)
    if not agg:
        return []
    rows, sevs, docs = [], [], set()
    for (k, v), info in agg.items():
        spec = info["spec"]
        ded = _dedicated_note(k)
        rows.append([k, str(info["default"]), v, spec["kind"], "%d대" % len(info["nodes"]),
                     spec["meaning"], effect_of(spec, info["dir"]) + ((" [판정: %s]" % ded) if ded else "")])
        if not ded:
            sevs.append(_SEV.get(risk_of(spec, info["dir"]), Severity.INFO))
        docs.add(spec["doc"])
    sev = _worst(sevs) if sevs else Severity.INFO
    orch = ""
    if ctx.orchestrated:
        sev = Severity.INFO
        orch = (" %s 배포로 감지되어 노드 설정은 플랫폼이 관리하는 값으로 보고 참고로 표시합니다."
                % ctx.deployment)
    # 노드 설정의 동적 키는 API 로 덮을 수 있으나, yml 에 있으면 신규 노드마다 같은 값이 들어간다.
    return [Finding(
        "SET-004", CAT, sev, "기본값에서 변경된 노드 설정(elasticsearch.yml)",
        observed="공식 기본값과 다른 노드 설정 %d건." % len(rows) + orch,
        impact="노드 설정은 해당 노드에만 적용됩니다. static 설정은 재기동해야 바뀌며, 노드마다 값이 다르면 "
               "노드 간 동작이 달라집니다(SET-005).",
        recommend="변경 사유를 확인합니다. 특히 스레드풀 크기·큐, breaker, 캐시 크기 변경은 증상을 가리는 경우가 많으므로 "
                  "원인(부하·쿼리·샤드 수) 해결 후 기본값 복귀를 검토합니다.",
        evidence=table(["설정", "기본값", "현재 값", "종류", "적용 노드", "의미", "변경 영향"], rows),
        refs=_refs(*sorted(docs)), source="nodes.json")]


def r_node_setting_consistency(ctx):
    """노드 간 일치해야 할 설정(인덱싱 버퍼·캐시·스레드풀·검색·전송 등)이 노드마다 다르거나 일부 노드에만 있는지 확인한다.

    대상은 명시 설정된 키 중 _CONSISTENCY_PREFIX 범위이며 노드 고유 설정은 제외. 데이터 노드끼리만 비교한다
    (역할이 다른 노드의 설정 차이는 정상일 수 있음). 불일치가 있으면 주의.
    """
    dn = ctx.data_nodes or ctx.nodes
    if len(dn) < 2:
        return []
    values = collections.defaultdict(dict)
    for n in dn:
        for k, v in _node_settings(n).items():
            if k.startswith(_CONSISTENCY_PREFIX) and not k.startswith(_NODE_SPECIFIC):
                values[k][n.name] = str(v)
    rows = []
    names = [n.name for n in dn]
    for k, m in sorted(values.items()):
        distinct = set(m.get(nm, "(미설정)") for nm in names)
        if len(distinct) > 1:
            rows.append([k, ", ".join("%s=%s" % (nm, m.get(nm, "(미설정)")) for nm in names)[:300]])
    if not rows:
        return []
    return [Finding(
        "SET-005", CAT, Severity.WARNING, "데이터 노드 간 설정 불일치",
        observed="데이터 노드끼리 값이 다르거나 일부 노드에만 있는 설정 %d건." % len(rows),
        impact="static 설정은 '모든 대상 노드에 동일하게' 설정해야 한다는 것이 공식 권고입니다. 노드마다 스레드풀·캐시·버퍼가 "
               "다르면 샤드가 어느 노드에 있느냐에 따라 성능이 달라져 hot spotting 과 구분하기 어려워집니다.",
        recommend="구성 관리 도구로 yml 을 통일하고, 재기동 일정에 맞춰 반영합니다.",
        evidence=table(["설정", "노드별 값"], rows[: ctx.t["top_n"] * 2]),
        refs=_refs(), source="nodes.json")]


def r_index_setting_changes(ctx):
    """사용자 인덱스의 명시 설정 중 공식 기본값이 등록된 설정이 기본값과 다른 것을 설정·값 단위로 집계한다.

    인덱스 생성 시 자동으로 들어가는 식별 정보(uuid, creation_date, version, provided_name, number_of_shards,
    tier preference 등)는 등록 대상이 아니므로 자연히 제외된다. 시스템 인덱스는 제외.
    심각도는 변경 방향별 위험도 중 최고값(최대 주의, 전용 룰 설정 제외).
    """
    agg = collections.OrderedDict()
    for name, body in items(ctx.index_settings):
        if ctx.is_system_index(name):
            continue
        flat = _flat((body or {}).get("settings") or {})
        for k, v in flat.items():
            spec = lookup(k)
            if not spec or spec["scope"] != "index":
                continue
            changed, direction, spec, default, _src = compare(k, v)
            if not changed:
                continue
            key = (k, str(v))
            agg.setdefault(key, {"idx": [], "spec": spec, "dir": direction, "default": default})
            agg[key]["idx"].append(name)
    if not agg:
        return []
    rows, sevs, docs = [], [], set()
    for (k, v), info in sorted(agg.items(), key=lambda kv: (kv[0][0], -len(kv[1]["idx"]))):
        spec = info["spec"]
        sample = ", ".join(info["idx"][:3]) + (" 외 %d개" % (len(info["idx"]) - 3) if len(info["idx"]) > 3 else "")
        ded = _dedicated_note(k)
        rows.append([k, str(info["default"]), v, spec["kind"], "%d개" % len(info["idx"]), sample,
                     effect_of(spec, info["dir"]) + ((" [판정: %s]" % ded) if ded else "")])
        if not ded:
            sevs.append(_SEV.get(risk_of(spec, info["dir"]), Severity.INFO))
        docs.add(spec["doc"])
    return [Finding(
        "SET-006", CAT, _worst(sevs) if sevs else Severity.INFO, "기본값에서 변경된 인덱스 설정",
        observed="공식 기본값과 다른 인덱스 설정 조합 %d건(사용자 인덱스 기준)." % len(rows),
        impact="인덱스 설정은 템플릿에서 상속되는 경우가 대부분이라, 같은 값이 여러 인덱스에 반복됩니다. "
               "static 설정(codec, queries.cache.enabled 등)은 닫힌 인덱스에서만 바꿀 수 있습니다.",
        recommend="의도한 튜닝인지 확인하고, 반복되는 값은 인덱스 템플릿에서 관리합니다. "
                  "쓰기 차단(blocks)·translog async·replica 0 은 우선 확인 대상입니다.",
        evidence=table(["설정", "기본값", "현재 값", "종류", "인덱스 수", "예시", "변경 영향"], rows),
        refs=_refs("index", *sorted(docs)), source="settings.json")]


RULES = [r_cluster_setting_changes, r_yml_shadowed, r_node_setting_changes,
         r_node_setting_consistency, r_index_setting_changes]
