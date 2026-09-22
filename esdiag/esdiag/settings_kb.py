# -*- coding: utf-8 -*-
"""설정 지식 베이스.

진단 번들만으로는 '원래 기본값' 을 알 수 없다.
  - cluster_settings_defaults.json 의 defaults 섹션은 elasticsearch.yml 값이 반영된 값이다(순수 기본값 아님).
  - API 로 명시 설정한 키는 defaults 섹션에 나오지 않는다.
  - settings.json(인덱스)에는 defaults 섹션이 없다.
따라서 기본값·의미·변경 영향은 공식 문서 기준(ES_BASELINE)으로 이 파일에 정의한다.
여기에 없는 설정은 '설명 미등록' 으로 표기하며 값은 그대로 보고한다.

적용 우선순위(공식): transient > persistent > elasticsearch.yml > 기본값.
static 설정은 모든 대상 노드의 elasticsearch.yml 에서만 바꿀 수 있고 재기동이 필요하다.

필드
  default : 공식 기본값(문자열). 계산식 기본값은 설명으로 표기
  kind    : dynamic | static
  scope   : cluster | node | index
  meaning : 설정의 의미
  up/down : 값을 올렸을 때 / 내렸을 때의 영향 (숫자·크기·시간·비율형)
  change  : 비수치형 값이 바뀌었을 때의 영향
  risk    : 기본값과 다를 때 심각도 힌트 — (up, down) 또는 단일 값. None | "INFO" | "WARNING"
  doc     : 참고 문서 키(DOCS)
"""

import re

from .util import parse_bytes, parse_time_ms

DOCS = {
    "stack": ("Static / dynamic 설정과 적용 우선순위",
              "https://www.elastic.co/docs/deploy-manage/stack-settings#static-dynamic"),
    "put": ("Cluster update settings API",
            "https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-cluster-put-settings"),
    "alloc": ("Cluster-level shard allocation and routing",
              "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/cluster-level-shard-allocation-routing-settings"),
    "breaker": ("Circuit breaker settings",
                "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/circuit-breaker-settings"),
    "tp": ("Thread pool settings",
           "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/thread-pool-settings"),
    "recovery": ("Index recovery settings",
                 "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/index-recovery-settings"),
    "search": ("Search settings",
               "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/search-settings"),
    "misc": ("Miscellaneous cluster settings",
             "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/miscellaneous-cluster-settings"),
    "buffer": ("Indexing buffer settings",
               "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/indexing-buffer-settings"),
    "qcache": ("Node query cache settings",
               "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/node-query-cache-settings"),
    "fdcache": ("Field data cache settings",
                "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/field-data-cache-settings"),
    "net": ("Networking settings",
            "https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/networking-settings"),
    "index": ("Index modules (index settings)",
              "https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules"),
    "translog": ("Translog settings",
                 "https://www.elastic.co/docs/reference/elasticsearch/index-settings/translog"),
    "merge": ("Merge settings",
              "https://www.elastic.co/docs/reference/elasticsearch/index-settings/merge"),
    "maplimit": ("Mapping limit settings",
                 "https://www.elastic.co/docs/reference/elasticsearch/index-settings/mapping-limit"),
    "shards": ("Size your shards",
               "https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards"),
}


def S(default, kind, scope, meaning, up=None, down=None, change=None, risk=None, doc="misc"):
    return {"default": default, "kind": kind, "scope": scope, "meaning": meaning,
            "up": up, "down": down, "change": change, "risk": risk, "doc": doc}


KB = {
    # ------------------------------------------------------------ 클러스터: 샤드 할당
    "cluster.routing.allocation.enable": S(
        "all", "dynamic", "cluster", "어떤 샤드의 할당을 허용할지(all / primaries / new_primaries / none).",
        change="all 이 아니면 replica(또는 전체) 샤드가 할당되지 않아 노드 이탈 후 복구가 멈추고 yellow/red 가 지속됩니다. "
               "롤링 재기동 중 임시로 바꾸는 값이며 작업 후 null 로 되돌려야 합니다.",
        risk="WARNING", doc="alloc"),
    "cluster.routing.rebalance.enable": S(
        "all", "dynamic", "cluster", "샤드 리밸런싱 허용 범위.",
        change="리밸런싱이 제한되어 노드 증설 후에도 샤드가 새 노드로 이동하지 않고, 편중이 고착됩니다.",
        risk="WARNING", doc="alloc"),
    "cluster.routing.allocation.allow_rebalance": S(
        "always", "dynamic", "cluster",
        "리밸런싱을 시작하는 조건(desired balance 할당기 기본 always, 이전 할당기는 indices_all_active).",
        change="조건을 엄격히 하면(indices_primaries_active / indices_all_active) 복구가 끝날 때까지 리밸런싱이 미뤄져 "
               "편중 해소가 늦어집니다.", risk="INFO", doc="alloc"),
    "cluster.routing.allocation.cluster_concurrent_rebalance": S(
        "2", "dynamic", "cluster", "클러스터 전체에서 동시에 리밸런싱할 샤드 수.",
        up="이동 속도는 빨라지지만 네트워크·디스크 I/O 가 서비스 트래픽과 경합합니다.",
        down="편중 해소가 느려집니다. 0 이면 리밸런싱이 사실상 중단됩니다.",
        risk=("INFO", "WARNING"), doc="alloc"),
    "cluster.routing.allocation.node_concurrent_recoveries": S(
        "2", "dynamic", "cluster", "노드당 동시 복구(incoming+outgoing) 수.",
        up="노드 교체 후 복구는 빨라지지만 해당 노드의 디스크·네트워크 포화 위험이 있습니다.",
        down="복구 시간이 길어져 yellow 상태가 오래 유지됩니다.", risk=("INFO", "INFO"), doc="alloc"),
    "cluster.routing.allocation.node_concurrent_incoming_recoveries": S(
        "2", "dynamic", "cluster", "노드당 동시 수신 복구 수.",
        up="수신 노드의 I/O 경합이 커집니다.", down="복구가 느려집니다.", risk=("INFO", "INFO"), doc="alloc"),
    "cluster.routing.allocation.node_concurrent_outgoing_recoveries": S(
        "2", "dynamic", "cluster", "노드당 동시 송신 복구 수.",
        up="송신 노드(대개 부하가 이미 큰 노드)의 I/O 경합이 커집니다.", down="복구가 느려집니다.",
        risk=("INFO", "INFO"), doc="alloc"),
    "cluster.routing.allocation.node_initial_primaries_recoveries": S(
        "4", "dynamic", "cluster", "노드 재기동 시 로컬 디스크에서 동시에 복구할 primary 수.",
        up="재기동 직후 디스크 부하가 급증합니다.", down="전체 재기동 후 red 해소가 느려집니다.",
        risk=("INFO", "INFO"), doc="alloc"),
    "cluster.routing.allocation.same_shard.host": S(
        "false", "dynamic", "cluster", "같은 호스트의 여러 노드에 동일 샤드 사본 배치 금지.",
        change="true 는 한 서버에 노드를 여러 개 띄운 구성에서 필요한 안전장치입니다. 단일 노드/호스트 구성에서 false 로 두면 "
               "호스트 장애 시 primary 와 replica 가 함께 사라질 수 있습니다.", risk="INFO", doc="alloc"),
    "cluster.routing.allocation.total_shards_per_node": S(
        "-1", "dynamic", "cluster", "노드당 전체 샤드 수 상한(-1=무제한).",
        down="상한에 걸리면 샤드가 미할당으로 남습니다. 노드 장애 시 남은 노드로 옮길 수 없어 red 가 될 수 있습니다.",
        risk=(None, "WARNING"), doc="alloc"),
    "cluster.routing.allocation.awareness.attributes": S(
        "", "dynamic", "cluster", "primary/replica 를 서로 다른 영역(zone·rack)에 배치하기 위한 노드 속성.",
        change="설정 시 같은 샤드의 사본이 다른 영역에 배치됩니다. 영역별 노드 수가 다르면 일부 사본이 미할당될 수 있습니다.",
        risk="INFO", doc="alloc"),
    "cluster.routing.use_adaptive_replica_selection": S(
        "true", "dynamic", "cluster", "검색 요청을 응답시간·큐 길이를 반영해 사본에 분배(ARS).",
        change="false 면 라운드로빈으로 분배되어, 느린 노드 1대가 전체 검색 p99 를 끌어올립니다.",
        risk="WARNING", doc="search"),
    "cluster.routing.allocation.balance.shard": S(
        "0.45", "dynamic", "cluster", "노드별 전체 샤드 수 균형 가중치.",
        change="가중치 조합을 바꾸면 desired balance 계산 결과가 달라져 대량 재배치가 발생할 수 있습니다.",
        risk="INFO", doc="alloc"),
    "cluster.routing.allocation.balance.index": S(
        "0.55", "dynamic", "cluster", "인덱스별 샤드 분산 가중치.",
        change="가중치 변경은 대량 재배치를 유발할 수 있습니다.", risk="INFO", doc="alloc"),
    "cluster.routing.allocation.balance.threshold": S(
        "1.0", "dynamic", "cluster", "리밸런싱을 수행할 최소 불균형 정도.",
        up="작은 불균형은 무시되어 이동이 줄지만 편중이 남습니다.",
        down="사소한 차이에도 이동이 잦아져 불필요한 I/O 가 생깁니다.", risk=("INFO", "INFO"), doc="alloc"),
    "cluster.routing.allocation.balance.write_load": S(
        "10.0", "dynamic", "cluster", "데이터 스트림 예상 쓰기 부하 균형 가중치.",
        change="쓰기 핫스팟 분산 효과가 달라집니다.", risk="INFO", doc="alloc"),
    "cluster.routing.allocation.balance.disk_usage": S(
        "2.0E-11", "dynamic", "cluster", "노드별 디스크 사용량 균형 가중치.",
        change="디스크 편중 분산 효과가 달라집니다.", risk="INFO", doc="alloc"),
    # ------------------------------------------------------------ 클러스터: 디스크
    "cluster.routing.allocation.disk.threshold_enabled": S(
        "true", "dynamic", "cluster", "디스크 워터마크 기반 할당 판단 사용 여부.",
        change="false 면 디스크가 가득 찰 때까지 샤드가 배치되어 flood stage 보호도 동작하지 않습니다.",
        risk="WARNING", doc="alloc"),
    "cluster.routing.allocation.disk.watermark.low": S(
        "85%", "dynamic", "cluster", "이 사용률을 넘은 노드에는 새 샤드를 배치하지 않음.",
        up="디스크를 더 채울 수 있지만 대응 여유가 줄어듭니다. 명시 설정하면 max_headroom 기본값(200GB)이 적용되지 않습니다.",
        down="여유 공간이 커도 샤드 배치가 막혀 일부 노드로 몰릴 수 있습니다.", risk=("INFO", "INFO"), doc="alloc"),
    "cluster.routing.allocation.disk.watermark.high": S(
        "90%", "dynamic", "cluster", "이 사용률을 넘은 노드의 샤드를 다른 노드로 이동.",
        up="이동이 늦게 시작되어 flood stage 도달 위험이 커집니다. 명시 설정 시 max_headroom 기본값(150GB)이 해제됩니다.",
        down="이동이 잦아집니다.", risk=("WARNING", "INFO"), doc="alloc"),
    "cluster.routing.allocation.disk.watermark.flood_stage": S(
        "95%", "dynamic", "cluster", "이 사용률을 넘은 노드의 인덱스에 쓰기 차단(read_only_allow_delete).",
        up="쓰기 차단 전에 디스크가 완전히 찰 위험이 커집니다. 명시 설정 시 max_headroom 기본값(100GB)이 해제됩니다.",
        down="쓰기 차단이 이르게 발생합니다.", risk=("WARNING", "INFO"), doc="alloc"),
    "cluster.info.update.interval": S(
        "30s", "dynamic", "cluster", "디스크 사용량 확인 주기.",
        up="급격한 디스크 증가를 늦게 감지합니다.", down="마스터 부하가 조금 늘어납니다.",
        risk=("WARNING", "INFO"), doc="alloc"),
    # ------------------------------------------------------------ 클러스터: 한도·보호
    "cluster.max_shards_per_node": S(
        "1000", "dynamic", "cluster", "non-frozen 데이터 노드당 열린 샤드 한도(클러스터 한도 = 값 × 노드 수).",
        up="한도 도달 시점은 늦어지지만, 한도가 막아 주던 과다 샤딩의 비용(heap·cluster state·마스터 부하)이 그대로 쌓입니다.",
        down="신규 인덱스 생성·롤오버가 더 일찍 실패합니다.", risk=("WARNING", "INFO"), doc="shards"),
    "cluster.max_shards_per_node.frozen": S(
        "3000", "dynamic", "cluster", "frozen 전용 노드당 샤드 한도.",
        up="frozen 노드의 메타데이터 부하가 커집니다.", down="마운트 가능한 인덱스가 줄어듭니다.",
        risk=("INFO", "INFO"), doc="shards"),
    "cluster.blocks.read_only": S(
        "false", "dynamic", "cluster", "클러스터 전체 읽기 전용.",
        change="true 면 모든 쓰기와 메타데이터 변경이 거부됩니다.", risk="WARNING", doc="misc"),
    "cluster.blocks.read_only_allow_delete": S(
        "false", "dynamic", "cluster", "클러스터 전체 읽기 전용(삭제만 허용).",
        change="true 면 인덱스 삭제 외 모든 쓰기가 거부됩니다.", risk="WARNING", doc="misc"),
    "action.destructive_requires_name": S(
        "true", "dynamic", "cluster", "와일드카드·_all 로 인덱스를 삭제하지 못하게 막음(8.0 부터 기본 true).",
        change="false 면 DELETE * 같은 요청 하나로 전체 인덱스가 삭제될 수 있습니다.", risk="WARNING", doc="misc"),
    "action.auto_create_index": S(
        "true", "dynamic", "cluster", "존재하지 않는 인덱스로 색인 시 자동 생성 허용 여부(패턴 지정 가능).",
        change="제한하면 오타 인덱스 생성은 막지만, 허용 패턴에 없는 수집 대상은 색인이 실패합니다. "
               "데이터 스트림·시스템 인덱스 패턴이 빠지면 기능이 멈출 수 있습니다.", risk="INFO", doc="misc"),
    "cluster.indices.close.enable": S(
        "true", "dynamic", "cluster", "인덱스 close API 허용 여부.",
        change="false 면 인덱스를 닫을 수 없습니다(닫힌 인덱스는 복제·스냅샷 대상 관리가 어려워 막는 경우가 있음).",
        risk="INFO", doc="misc"),
    "cluster.persistent_tasks.allocation.enable": S(
        "all", "dynamic", "cluster", "persistent task(ML job, transform 등) 할당 허용.",
        change="none 이면 새 persistent task 가 할당되지 않습니다.", risk="WARNING", doc="misc"),
    # ------------------------------------------------------------ 클러스터: 복구·검색·브레이커
    "indices.recovery.max_bytes_per_sec": S(
        "40mb", "dynamic", "cluster", "노드당 복구 대역 상한(전용 cold/frozen 노드는 메모리 기반으로 자동 산정).",
        up="복구가 빨라지지만 복구 트래픽이 서비스 I/O 를 잠식할 수 있습니다.",
        down="노드 교체·재기동 후 복구가 느려져 yellow 상태가 길어집니다.", risk=("INFO", "WARNING"), doc="recovery"),
    "search.default_search_timeout": S(
        "-1", "dynamic", "cluster", "요청에 timeout 이 없을 때 적용되는 검색 타임아웃(-1=무제한).",
        change="짧게 두면 무거운 쿼리가 부분 결과로 끝나고, 무제한이면 비정상 쿼리가 자원을 계속 점유할 수 있습니다.",
        risk="INFO", doc="search"),
    "search.max_buckets": S(
        "65536", "dynamic", "cluster", "단일 응답의 최대 집계 버킷 수.",
        up="대형 집계가 허용되어 coordinating 노드 heap 압박·circuit breaker 발동 위험이 커집니다.",
        down="기존 대시보드 집계가 실패할 수 있습니다.", risk=("WARNING", "INFO"), doc="search"),
    "search.allow_expensive_queries": S(
        "true", "dynamic", "cluster", "script·wildcard·regexp·fuzzy 등 비싼 쿼리 허용 여부.",
        change="false 면 해당 쿼리가 거부됩니다(보호 목적). Kibana 일부 기능도 영향받을 수 있습니다.",
        risk="INFO", doc="search"),
    "search.low_level_cancellation": S(
        "true", "dynamic", "cluster", "검색 취소 요청을 세그먼트 단위로 빠르게 반영.",
        change="false 면 취소된 검색이 늦게 멈춰 자원을 더 오래 씁니다.", risk="INFO", doc="search"),
    "indices.breaker.total.limit": S(
        "95%", "dynamic", "cluster", "parent breaker 한도(use_real_memory=true 기준 95%, false 면 70%).",
        up="OOM 직전까지 요청을 받아들여 노드가 OutOfMemoryError 로 종료될 위험이 커집니다.",
        down="정상 요청도 CircuitBreakingException 으로 거부됩니다.", risk=("WARNING", "INFO"), doc="breaker"),
    "indices.breaker.fielddata.limit": S(
        "40%", "dynamic", "cluster", "fielddata 적재 한도(heap 대비).",
        up="text 필드 집계 등으로 heap 이 잠식되어 GC 압박이 커집니다.", down="집계가 더 일찍 거부됩니다.",
        risk=("WARNING", "INFO"), doc="breaker"),
    "indices.breaker.request.limit": S(
        "60%", "dynamic", "cluster", "요청 단위 메모리(집계 등) 한도.",
        up="대형 집계가 heap 을 과점할 수 있습니다.", down="집계가 더 일찍 거부됩니다.",
        risk=("WARNING", "INFO"), doc="breaker"),
    "network.breaker.inflight_requests.limit": S(
        "100%", "dynamic", "cluster", "수신 중인 요청(transport/HTTP) 크기 한도.",
        up="대형 bulk 가 한꺼번에 들어와 heap 이 급증할 수 있습니다.", down="대형 요청이 거부됩니다.",
        risk=("WARNING", "INFO"), doc="breaker"),
    "script.max_compilations_rate": S(
        "150/5m", "dynamic", "cluster", "스크립트 컴파일 속도 한도.",
        change="올리면 매번 다른 스크립트를 보내는 잘못된 사용(파라미터 미사용)이 가려지고 CPU·메모리 부담이 커집니다.",
        risk="INFO", doc="misc"),
    "indices.lifecycle.poll_interval": S(
        "10m", "dynamic", "cluster", "ILM 조건 확인 주기.",
        up="롤오버·삭제가 늦게 수행되어 샤드 크기·디스크가 계획보다 커집니다.",
        down="마스터 부하가 늘어납니다. 테스트 목적 외에는 줄이지 않습니다.", risk=("INFO", "WARNING"), doc="misc"),
    "xpack.monitoring.collection.enabled": S(
        "false", "dynamic", "cluster", "레거시 내부 모니터링 수집.",
        change="true 면 클러스터 자신에 모니터링 데이터를 색인해 부하가 늘어납니다. 운영 모니터링은 별도 클러스터를 권장합니다.",
        risk="INFO", doc="misc"),
    "ingest.geoip.downloader.enabled": S(
        "true", "dynamic", "cluster", "GeoIP DB 자동 다운로드.",
        change="폐쇄망에서는 false 가 정상입니다. 이 경우 DB 를 수동으로 배포해야 geoip processor 가 동작합니다.",
        risk=None, doc="misc"),
    "slm.retention_schedule": S(
        "0 30 1 * * ?", "dynamic", "cluster", "SLM 보존 정책(오래된 스냅샷 삭제) 실행 주기.",
        change="실행 시각이 바뀝니다. 너무 드물면 스냅샷 저장소 용량이 계획보다 커집니다.", risk=None, doc="misc"),
    "cluster.metadata.display_name": S(
        "", "dynamic", "cluster", "클러스터 표시 이름(Elastic Cloud 메타데이터).", change="동작 영향 없음.",
        risk=None, doc="misc"),
    "xpack.ml.max_machine_memory_percent": S(
        "30", "dynamic", "cluster", "ML 작업이 쓸 수 있는 노드 메모리 비율.",
        up="ML 프로세스가 파일시스템 캐시·다른 프로세스 몫을 잠식합니다.", down="ML job 이 할당되지 못할 수 있습니다.",
        risk=("INFO", "INFO"), doc="misc"),
    # ------------------------------------------------------------ 노드(static, elasticsearch.yml)
    "indices.memory.index_buffer_size": S(
        "10%", "static", "node", "색인 버퍼(heap 대비). 쓰기 중인 샤드가 공유.",
        up="대량 색인 효율은 좋아지지만 검색·집계에 쓸 heap 이 줄어듭니다.",
        down="flush 가 잦아지고 작은 세그먼트가 늘어납니다.", risk=("INFO", "INFO"), doc="buffer"),
    "indices.queries.cache.size": S(
        "10%", "static", "node", "노드 query(filter) 캐시 크기(heap 대비).",
        up="heap 상주량이 늘어 GC 압박이 커집니다.", down="필터 캐시 적중률이 떨어집니다.",
        risk=("INFO", "INFO"), doc="qcache"),
    "indices.requests.cache.size": S(
        "1%", "static", "node", "shard request 캐시 크기(heap 대비).",
        up="heap 상주량이 늘어납니다.", down="집계 결과 캐시 효과가 줄어듭니다.", risk=("INFO", "INFO"), doc="qcache"),
    "indices.fielddata.cache.size": S(
        "unbounded", "static", "node", "fielddata 캐시 상한(기본 무제한, 실제 상한은 fielddata breaker).",
        change="상한을 두면 eviction 이 발생해 해당 집계가 매번 fielddata 를 다시 적재합니다.",
        risk="INFO", doc="fdcache"),
    "indices.breaker.total.use_real_memory": S(
        "true", "static", "node", "parent breaker 가 실제 heap 사용량을 기준으로 판단.",
        change="false 면 추정치 기준(한도 기본 70%)으로 동작해 실제 heap 과 괴리가 생길 수 있습니다.",
        risk="WARNING", doc="breaker"),
    "thread_pool.write.queue_size": S(
        "10000", "static", "node", "write 스레드풀 대기열 크기.",
        up="rejection 은 줄지만 요청이 큐에서 오래 대기해 지연과 heap 사용이 늘어납니다. 원인(과부하)이 가려집니다.",
        down="rejection(429)이 더 빨리 발생합니다.", risk=("WARNING", "INFO"), doc="tp"),
    "thread_pool.search.queue_size": S(
        "자동 산정(9.4.4 관측: search 스레드 수 × 1000, 8.x 이전 문서 기준 1000)", "static", "node",
        "search 스레드풀 대기열 크기.",
        up="rejection 은 줄지만 검색 지연·heap 사용이 늘어납니다.", down="rejection 이 더 빨리 발생합니다.",
        risk=("WARNING", "INFO"), doc="tp"),
    "thread_pool.write.size": S(
        "CPU 코어 수(자동)", "static", "node", "write 스레드 수.",
        change="코어 수보다 크게 잡으면 컨텍스트 스위칭만 늘고 처리량은 늘지 않습니다.", risk="WARNING", doc="tp"),
    "thread_pool.search.size": S(
        "int((코어 수 × 3) / 2) + 1(자동)", "static", "node", "search 스레드 수.",
        change="임의 변경 시 CPU 경합이나 처리량 저하가 생깁니다.", risk="WARNING", doc="tp"),
    "node.processors": S(
        "가용 프로세서 수(자동)", "static", "node", "ES 가 인식하는 CPU 수(스레드풀 크기 산정 기준).",
        change="실제보다 크게 잡으면 스레드가 과다해지고, 작게 잡으면 CPU 를 다 쓰지 못합니다. "
               "컨테이너에서 CPU limit 과 맞출 때 사용합니다.", risk="INFO", doc="tp"),
    "http.max_content_length": S(
        "100mb", "static", "node", "HTTP 요청 본문 최대 크기.",
        up="대형 bulk·문서가 허용되어 heap 급증 위험이 커집니다(Lucene 한계 약 2GB 는 그대로).",
        down="대형 bulk 요청이 413 으로 거부됩니다.", risk=("WARNING", "INFO"), doc="net"),
    "transport.compress": S(
        "indexing_data", "dynamic", "cluster", "노드 간 전송 압축 대상.",
        change="true 는 모든 전송을 압축해 CPU 를 더 쓰고, false 는 색인 데이터도 압축하지 않아 네트워크 사용이 늘어납니다.",
        risk="INFO", doc="net"),
    "bootstrap.memory_lock": S(
        "false", "static", "node", "heap 을 RAM 에 고정(swap 방지).",
        change="true 면 swap 을 막습니다. OS memlock 한도가 부족하면 기동 시 bootstrap check 가 실패합니다.",
        risk=None, doc="misc"),
    "node.store.allow_mmap": S(
        "true", "static", "node", "Lucene 파일 mmap 사용.",
        change="false 면 mmap 대신 NIO 로 읽어 검색 성능이 떨어질 수 있습니다(vm.max_map_count 를 못 올리는 환경용).",
        risk="INFO", doc="misc"),
    # ------------------------------------------------------------ 인덱스
    "index.refresh_interval": S(
        "1s(미지정 시 search idle 적용)", "dynamic", "index", "새 문서가 검색에 보이기까지의 주기.",
        up="색인 처리량이 늘고 merge 부담이 줄지만 검색 반영이 늦어집니다. -1 은 refresh 중지.",
        down="세그먼트가 잦게 생겨 CPU·merge 부담이 커집니다. 명시하면 search idle 최적화가 꺼집니다.",
        risk=("INFO", "INFO"), doc="index"),
    "index.number_of_replicas": S(
        "1", "dynamic", "index", "샤드당 replica 수.",
        up="가용성·검색 처리량은 늘지만 디스크와 색인 비용이 배수로 늘어납니다.",
        down="0 이면 노드 1대 장애로 데이터가 유실될 수 있습니다.", risk=("INFO", "WARNING"), doc="index"),
    "index.translog.durability": S(
        "request", "dynamic", "index", "요청마다 translog 를 fsync 할지(request) 주기적으로 할지(async).",
        change="async 면 색인이 빨라지는 대신 노드 비정상 종료 시 sync_interval 동안의 확인 응답된 쓰기가 유실될 수 있습니다.",
        risk="WARNING", doc="translog"),
    "index.translog.sync_interval": S(
        "5s", "dynamic", "index", "async 모드의 translog fsync 주기.",
        up="async 모드에서 유실 가능 구간이 길어집니다.", down="fsync 가 잦아집니다.", risk=("INFO", "INFO"), doc="translog"),
    "index.max_result_window": S(
        "10000", "dynamic", "index", "from + size 최대값.",
        up="깊은 페이징이 허용되어 샤드마다 from+size 건을 모으므로 heap 사용이 페이지 깊이에 비례해 늘어납니다.",
        down="깊은 페이지 요청이 거부됩니다.", risk=("WARNING", "INFO"), doc="index"),
    "index.max_inner_result_window": S(
        "100", "dynamic", "index", "inner_hits·top_hits 의 from + size 최대값.",
        up="집계 응답이 커져 heap 사용이 늘어납니다.", down="해당 쿼리가 거부됩니다.", risk=("INFO", "INFO"), doc="index"),
    "index.max_terms_count": S(
        "65536", "dynamic", "index", "terms 쿼리의 최대 항목 수.",
        up="대형 terms 쿼리가 CPU·heap 을 크게 씁니다.", down="해당 쿼리가 거부됩니다.", risk=("INFO", "INFO"), doc="index"),
    "index.max_regex_length": S(
        "1000", "dynamic", "index", "regexp 쿼리 최대 길이.",
        up="복잡한 정규식이 CPU 를 과점할 수 있습니다.", down="해당 쿼리가 거부됩니다.", risk=("INFO", "INFO"), doc="index"),
    "index.mapping.total_fields.limit": S(
        "1000", "dynamic", "index", "인덱스당 최대 필드 수(매핑 폭증 방지).",
        up="필드가 늘수록 cluster state·heap 사용이 늘고 마스터 부하가 커집니다(매핑 폭증 신호).",
        down="새 필드가 들어오면 색인이 실패합니다.", risk=("WARNING", "INFO"), doc="maplimit"),
    "index.mapping.depth.limit": S(
        "20", "dynamic", "index", "객체 중첩 최대 깊이.", up="깊은 중첩 문서가 허용됩니다.", down="색인이 거부될 수 있습니다.",
        risk=("INFO", "INFO"), doc="maplimit"),
    "index.mapping.nested_fields.limit": S(
        "50", "dynamic", "index", "nested 타입 필드 수 한도.",
        up="nested 는 숨은 문서를 만들어 저장·검색 비용이 큽니다.", down="매핑이 거부됩니다.", risk=("WARNING", "INFO"),
        doc="maplimit"),
    "index.mapping.nested_objects.limit": S(
        "10000", "dynamic", "index", "문서당 nested 객체 수 한도.",
        up="문서 1건이 수만 개의 숨은 문서로 늘어 heap·디스크를 과점할 수 있습니다.", down="색인이 거부됩니다.",
        risk=("WARNING", "INFO"), doc="maplimit"),
    "index.unassigned.node_left.delayed_timeout": S(
        "1m", "dynamic", "index", "노드 이탈 후 replica 재할당을 미루는 시간.",
        up="노드 복귀를 기다리는 동안 yellow 가 길어지지만 불필요한 재복제는 줄어듭니다.",
        down="잠깐의 재기동에도 전체 재복제가 시작됩니다(0 이면 즉시).", risk=("INFO", "WARNING"), doc="index"),
    "index.codec": S(
        "default(LZ4)", "static", "index", "stored field 압축 방식(logsdb·time_series 모드는 best_compression 기본).",
        change="best_compression 은 저장 공간을 줄이는 대신 문서 조회 시 압축 해제 비용이 늘어납니다. "
               "static 이라 닫힌 인덱스에서만 바꿀 수 있고, 기존 세그먼트는 merge 후 반영됩니다.",
        risk="INFO", doc="index"),
    "index.routing.allocation.total_shards_per_node": S(
        "-1", "dynamic", "index", "이 인덱스의 노드당 샤드 수 상한(핫스팟 방지).",
        down="너무 작으면 노드 장애 시 샤드를 옮길 곳이 없어 미할당됩니다.", risk=(None, "WARNING"), doc="alloc"),
    "index.search.idle.after": S(
        "30s", "dynamic", "index", "검색이 없으면 주기적 refresh 를 건너뛰기 시작하는 시간.",
        up="refresh 생략 효과가 늦게 시작됩니다.", down="검색 idle 전환이 빨라져, 뜸한 첫 검색이 refresh 를 기다리게 됩니다.",
        risk=("INFO", "INFO"), doc="index"),
    "index.requests.cache.enable": S(
        "true", "dynamic", "index", "shard request 캐시 사용.", change="false 면 반복 집계를 매번 다시 계산합니다.",
        risk="INFO", doc="qcache"),
    "index.queries.cache.enabled": S(
        "true", "static", "index", "노드 query(filter) 캐시 사용.", change="false 면 반복 필터를 매번 다시 계산합니다.",
        risk="INFO", doc="qcache"),
    "index.merge.policy.max_merged_segment": S(
        "5gb", "dynamic", "index", "merge 로 만들어지는 세그먼트의 최대 크기.",
        up="세그먼트 수가 줄어 검색(특히 kNN)이 빨라지지만 merge 한 번의 I/O 가 커집니다.",
        down="세그먼트가 많아져 검색이 느려집니다.", risk=("INFO", "INFO"), doc="merge"),
    "index.merge.policy.segments_per_tier": S(
        "10", "dynamic", "index", "tier 당 허용 세그먼트 수.",
        up="merge 는 줄지만 세그먼트가 많아집니다.", down="merge 가 잦아져 I/O 가 늘어납니다.",
        risk=("INFO", "INFO"), doc="merge"),
    "index.highlight.max_analyzed_offset": S(
        "1000000", "dynamic", "index", "하이라이트 시 분석할 최대 문자 수.",
        up="대형 문서 하이라이팅이 CPU·heap 을 크게 씁니다.", down="긴 문서의 하이라이트가 잘리거나 실패합니다.",
        risk=("INFO", "INFO"), doc="index"),
    "index.max_ngram_diff": S(
        "1", "dynamic", "index", "ngram 토크나이저 min/max 차이 허용치.",
        up="토큰 수가 급증해 색인 크기와 속도에 큰 영향을 줍니다.", down="분석기 정의가 거부됩니다.",
        risk=("INFO", "INFO"), doc="index"),
    "index.max_shingle_diff": S(
        "3", "dynamic", "index", "shingle 필터 min/max 차이 허용치.",
        up="토큰 수가 급증합니다.", down="분석기 정의가 거부됩니다.", risk=("INFO", "INFO"), doc="index"),
    "index.max_script_fields": S(
        "32", "dynamic", "index", "요청당 script_fields 최대 수.", up="검색 CPU 사용이 늘어납니다.",
        down="해당 요청이 거부됩니다.", risk=("INFO", "INFO"), doc="index"),
    "index.max_docvalue_fields_search": S(
        "100", "dynamic", "index", "요청당 docvalue_fields 최대 수.", up="응답 생성 비용이 늘어납니다.",
        down="해당 요청이 거부됩니다.", risk=("INFO", "INFO"), doc="index"),
    "index.max_refresh_listeners": S(
        "1000", "dynamic", "index", "refresh=wait_for 대기자 최대 수.", up="대기 요청이 heap 을 더 씁니다.",
        down="초과 요청은 강제 refresh 를 유발합니다.", risk=("INFO", "INFO"), doc="index"),
    "index.auto_expand_replicas": S(
        "false", "dynamic", "index", "데이터 노드 수에 맞춰 replica 수 자동 조정.",
        change="대형 인덱스에 쓰면 노드 증설 시 replica 가 자동으로 늘어 디스크·복구 부하가 급증합니다.",
        risk="INFO", doc="index"),
    "index.blocks.write": S("false", "dynamic", "index", "쓰기 차단.", change="true 면 색인이 거부됩니다.",
                            risk="WARNING", doc="index"),
    "index.blocks.read_only": S("false", "dynamic", "index", "읽기 전용.", change="true 면 쓰기·메타데이터 변경이 거부됩니다.",
                                risk="WARNING", doc="index"),
    "index.blocks.read_only_allow_delete": S(
        "false", "dynamic", "index", "읽기 전용(삭제 허용). flood stage 가 자동 설정.",
        change="true 면 색인이 거부됩니다. 디스크 여유 확보 후 해제해야 합니다(8.x 는 여유 회복 시 자동 해제).",
        risk="WARNING", doc="index"),
}

# 기본값과 같은 것으로 취급할 값(배포 형태가 쓰는 표식 포함)
EQUIV_EMPTY = ("", "null", "none", "[]", "no_instances_excluded")

# 접두사 규칙: allocation filter
PREFIX_RULES = [
    ("cluster.routing.allocation.exclude.", S(
        "", "dynamic", "cluster", "지정한 노드(이름·IP·호스트·속성)에서 샤드를 빼냄.",
        change="해당 노드에 샤드가 배치되지 않습니다. 유지보수 후 제거하지 않으면 용량이 남아도 샤드가 다른 노드로 몰립니다.",
        risk="WARNING", doc="alloc")),
    ("cluster.routing.allocation.include.", S(
        "", "dynamic", "cluster", "지정한 노드에만 샤드 배치를 허용.",
        change="조건에 맞지 않는 노드에는 샤드가 배치되지 않아 편중·미할당이 생길 수 있습니다.", risk="WARNING", doc="alloc")),
    ("cluster.routing.allocation.require.", S(
        "", "dynamic", "cluster", "지정한 조건을 모두 만족하는 노드에만 샤드 배치.",
        change="조건을 만족하는 노드가 부족하면 샤드가 미할당됩니다.", risk="WARNING", doc="alloc")),
    ("logger.", S(
        "INFO(로거별 기본)", "dynamic", "cluster", "로거 레벨.",
        change="DEBUG/TRACE 로 올리면 로그량이 급증해 디스크·I/O·성능에 영향을 줍니다. 조사 후 null 로 되돌려야 합니다.",
        risk="INFO", doc="misc")),
]


def lookup(key):
    if key in KB:
        return KB[key]
    for prefix, spec in PREFIX_RULES:
        if key.startswith(prefix):
            return spec
    return None


def _norm(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return ",".join(str(x) for x in v)
    return str(v).strip()


def _num(v):
    """비교용 숫자(단위 무관 동일 척도). 해석 불가면 None."""
    s = _norm(v).lower()
    if not s or s in ("unbounded",):
        return None
    if s.endswith("%"):
        try:
            return ("pct", float(s[:-1]))
        except ValueError:
            return None
    t = parse_time_ms(s)
    if t is not None and re.match(r"^-?[\d.]+(ms|s|m|h|d|nanos|micros)$", s):
        return ("time", t)
    b = parse_bytes(s)
    if b is not None and re.match(r"^-?[\d.]+(b|kb|mb|gb|tb|pb)$", s):
        return ("bytes", float(b))
    try:
        return ("num", float(s))
    except ValueError:
        return None


AUTO_DEFAULT = ("thread_pool.write.size", "thread_pool.search.size", "thread_pool.search.queue_size",
                "node.processors")
UNBOUNDED = ("-1", "-1b", "unbounded")


def compare(key, value, es_default=None):
    """(changed, direction, spec, default_used, default_source)

    direction: "up" | "down" | "change" | None
    default_source: "공식 문서" | "번들(ES 보고)" | "미등록"
    """
    spec = lookup(key)
    if spec is not None:
        default, source = spec["default"], "공식 문서"
    elif es_default is not None:
        default, source = es_default, "번들(ES 보고)"
    else:
        return True, "change", None, None, "미등록"
    cur, dft = _norm(value), _norm(default)
    if key in AUTO_DEFAULT:
        return True, "change", spec, default, source      # 자동 산정값: 명시했다는 사실만 보고
    if cur.lower() in UNBOUNDED and dft.lower() in UNBOUNDED:
        return False, None, spec, default, source
    if cur.lower() in EQUIV_EMPTY and dft.lower() in EQUIV_EMPTY:
        return False, None, spec, default, source
    if cur.lower() == dft.lower():
        return False, None, spec, default, source
    a, b = _num(cur), _num(dft.split("(")[0])
    if a and b and a[0] == b[0]:
        if a[1] == b[1]:
            return False, None, spec, default, source
        return True, ("up" if a[1] > b[1] else "down"), spec, default, source
    return True, "change", spec, default, source


def effect_of(spec, direction):
    if not spec:
        return "설명 미등록(공식 문서에서 해당 설정의 의미를 확인하십시오)"
    if direction == "up" and spec.get("up"):
        return "↑ " + spec["up"]
    if direction == "down" and spec.get("down"):
        return "↓ " + spec["down"]
    return spec.get("change") or spec.get("up") or spec.get("down") or ""


def risk_of(spec, direction):
    if not spec:
        return "INFO"
    r = spec.get("risk")
    if isinstance(r, tuple):
        if direction == "up":
            return r[0]
        if direction == "down":
            return r[1]
        return r[0] or r[1]
    return r
