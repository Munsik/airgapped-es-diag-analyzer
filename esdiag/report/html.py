# -*- coding: utf-8 -*-
"""단일 파일 HTML 리포트. 외부 CSS/JS/폰트/이미지를 전혀 참조하지 않는다(폐쇄망 전제).

시각화는 CSS 막대로만 구성한다. 차트 라이브러리를 쓰지 않으므로 파일 하나로 어떤 브라우저에서도 열린다.
"""

import html as _h

from ..model import Severity

CSS = """
:root{
  --paper:#f4f5f6; --surface:#ffffff; --ink:#15181b; --muted:#5c646c;
  --line:#d8dcdf; --crit:#a3231d; --warn:#8a5a00; --info:#26527d; --ok:#1f6244;
  --crit-bg:#fbecea; --warn-bg:#fbf3e2; --info-bg:#eaf0f7; --ok-bg:#e9f2ed;
  --bar-ok:#3f8f6b; --bar-warn:#c68a1e; --bar-crit:#b8453e; --bar-track:#e6e9ea;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font-family:"Pretendard","Apple SD Gothic Neo","Noto Sans KR","Malgun Gothic",
  "Helvetica Neue",Arial,sans-serif;font-size:14px;line-height:1.65;
  font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:32px 24px 80px}
header{border-bottom:2px solid var(--ink);padding-bottom:20px;margin-bottom:28px}
h1{font-size:15px;font-weight:600;letter-spacing:.02em;margin:0 0 14px;color:var(--muted)}
.cluster{font-size:30px;font-weight:700;letter-spacing:-.01em;margin:0;word-break:break-all}
.sub{color:var(--muted);margin-top:6px}
.verdict{display:flex;flex-wrap:wrap;gap:28px;align-items:center;margin-top:22px}
.verdict>div{margin-right:20px}
.grade{font-size:18px;font-weight:600}
.sevbar{display:flex;height:10px;width:320px;max-width:60vw;margin-top:10px;
  border:1px solid var(--line);background:var(--bar-track)}
.sevbar i{display:block;height:100%}
.sevbar i.c{background:var(--crit)} .sevbar i.w{background:var(--warn)}
.sevbar i.i{background:var(--info)} .sevbar i.o{background:var(--bar-ok)}
.pills{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.pill{border:1px solid var(--line);background:var(--surface);padding:3px 10px;border-radius:2px;
  font-size:13px}
.pill.c{color:var(--crit);border-color:#e6bcb8} .pill.w{color:var(--warn);border-color:#e6d3a8}
.pill.i{color:var(--info);border-color:#bcccdd} .pill.o{color:var(--ok);border-color:#b7d3c6}
.facts{display:flex;flex-wrap:wrap;background:var(--line);border:1px solid var(--line);
  margin-top:24px;gap:1px}
.facts div{background:var(--surface);padding:10px 12px;flex:1 1 150px;min-width:150px}
.facts span{display:block;color:var(--muted);font-size:12px}
.facts strong{font-weight:600;font-size:15px}
h2{scroll-margin-top:64px;font-size:16px;margin:36px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h2 small{font-weight:400;color:var(--muted);font-size:13px;margin-left:8px}
ol.prio{margin:0;padding-left:22px}
ol.prio li{margin-bottom:6px}
ol.prio a{color:inherit;text-decoration:none;border-bottom:1px solid var(--line)}
ol.prio a:hover{border-bottom-color:var(--ink)}
.tag{font-size:12px;font-weight:700;padding:1px 6px;border-radius:2px;margin-right:6px}
.tag.c{background:var(--crit-bg);color:var(--crit)} .tag.w{background:var(--warn-bg);color:var(--warn)}
.tag.i{background:var(--info-bg);color:var(--info)} .tag.o{background:var(--ok-bg);color:var(--ok)}
.nav{position:sticky;top:0;background:var(--paper);padding:10px 0;z-index:5;
  border-bottom:1px solid var(--line);display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.nav button,.nav a{font:inherit;font-size:13px;padding:4px 12px;border:1px solid var(--line);
  background:var(--surface);cursor:pointer;border-radius:2px;color:inherit;text-decoration:none}
.nav button[aria-pressed="true"]{background:var(--ink);color:#fff;border-color:var(--ink)}
.nav .sep{width:1px;height:20px;background:var(--line)}
.f{scroll-margin-top:72px;background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--line);
  padding:16px 18px;margin:12px 0}
.f.c{border-left-color:var(--crit)} .f.w{border-left-color:var(--warn)}
.f.i{border-left-color:var(--info)} .f.o{border-left-color:var(--ok)}
.f h3{margin:0 0 10px;font-size:15px;font-weight:600;display:flex;align-items:baseline;gap:6px;
  flex-wrap:wrap}
.f h3 .rid{margin-left:auto;color:var(--muted);font-size:12px;font-weight:400}
dl{margin:0;overflow:hidden}
dt{color:var(--muted);font-size:13px;float:left;width:44px;clear:left;padding-top:1px}
dd{margin:0 0 4px 58px}
details{margin-top:12px}
summary{cursor:pointer;color:var(--muted);font-size:13px}
table{border-collapse:collapse;width:100%;margin-top:10px;font-size:13px}
th,td{border:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:middle;
  word-break:break-word}
th{background:#eef0f1;font-weight:600}
tbody tr:nth-child(even){background:#fafbfb}
.scroll{overflow-x:auto}
.matrix td.n{font-weight:600}
.bar{display:flex;align-items:center;gap:8px;min-width:120px}
.bar .track{flex:1;height:8px;background:var(--bar-track);position:relative;min-width:60px}
.bar .fill{position:absolute;left:0;top:0;height:100%;background:var(--bar-ok)}
.bar .fill.w{background:var(--bar-warn)} .bar .fill.c{background:var(--bar-crit)}
.bar .v{width:52px;text-align:right;font-size:12px}
.legend{color:var(--muted);font-size:12px;margin-top:6px}
.src{color:var(--muted);font-size:12px;margin-top:8px}
.src a{color:var(--info)}
footer{margin-top:48px;padding-top:16px;border-top:1px solid var(--line);
  color:var(--muted);font-size:12px}
@media print{
  .nav{display:none} .f{break-inside:avoid} body{background:#fff}
  details>summary{display:none} details{display:block}
  .wrap{max-width:none;padding:0}
}
@media (max-width:640px){dt{float:none;width:auto;font-weight:600} dd{margin-left:0}}
"""

JS = """
(function(){
  var level='all', cat='all';
  var lb=document.querySelectorAll('.nav button[data-level]');
  var cb=document.querySelectorAll('.nav button[data-cat]');
  function apply(){
    var shown=0;
    document.querySelectorAll('.f').forEach(function(el){
      var s=el.getAttribute('data-sev'), c=el.getAttribute('data-cat');
      var okL = level==='all' || s===level || (level==='act' && (s==='CRITICAL'||s==='WARNING'));
      var okC = cat==='all' || c===cat;
      var show = okL && okC;
      el.style.display = show ? '' : 'none';
      if(show){shown++;}
    });
    document.querySelectorAll('h2[data-cat]').forEach(function(h){
      var any=false,n=h.nextElementSibling;
      while(n && n.tagName!=='H2'){ if(n.classList&&n.classList.contains('f')&&n.style.display!=='none'){any=true;} n=n.nextElementSibling;}
      h.style.display=any?'':'none';
    });
    lb.forEach(function(b){b.setAttribute('aria-pressed', b.dataset.level===level);});
    cb.forEach(function(b){b.setAttribute('aria-pressed', b.dataset.cat===cat);});
    var fc=document.getElementById('fcount'); if(fc){fc.textContent='표시 '+shown+'건';}
  }
  lb.forEach(function(b){b.addEventListener('click',function(){level=b.dataset.level;apply();});});
  cb.forEach(function(b){b.addEventListener('click',function(){cat=b.dataset.cat;apply();
    var first=document.querySelector('h2[data-cat]:not([style*="none"])');
    if(first){first.scrollIntoView({behavior:'smooth',block:'start'});}});});
  document.querySelectorAll('a[data-jump]').forEach(function(a){
    a.addEventListener('click',function(ev){
      ev.preventDefault(); level='all'; cat='all'; apply();
      var t=document.getElementById(a.getAttribute('data-jump'));
      if(t){t.scrollIntoView({behavior:'smooth',block:'center'}); t.style.outline='2px solid #15181b';
        setTimeout(function(){t.style.outline='';},1500);}
    });
  });
  apply();
})();
"""

_CLS = {Severity.CRITICAL: "c", Severity.WARNING: "w", Severity.INFO: "i", Severity.OK: "o"}


def e(s):
    return _h.escape("" if s is None else str(s))


def _cat_id(cat):
    return "cat-" + "".join("%02x" % (ord(ch) % 256) for ch in str(cat))[:24]


def _bar(value, warn, crit, suffix="%", scale=100.0, label=None):
    """수치를 막대 셀로 변환. scale 은 막대 100% 에 해당하는 값."""
    if value is None:
        return "<td>-</td>"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "<td>%s</td>" % e(value)
    cls = "c" if v >= crit else ("w" if v >= warn else "")
    width = max(0.0, min(100.0, (v / scale * 100.0) if scale else 0.0))
    text = label if label is not None else ("%g%s" % (v, suffix))
    return ("<td><div class='bar'><span class='v'>%s</span>"
            "<span class='track'><span class='fill %s' style='width:%.1f%%'></span></span>"
            "</div></td>") % (e(text), cls, width)


def render(result):
    f = result.facts()
    c = result.counts
    o = []
    o.append("<!DOCTYPE html><html lang='ko'><head><meta charset='utf-8'>")
    o.append("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    o.append("<title>ES 진단 분석 - %s</title>" % e(f["cluster_name"]))
    o.append("<style>%s</style></head><body><div class='wrap'>" % CSS)

    # ---------- header ----------
    o.append("<header>")
    o.append("<h1>Elasticsearch 진단 번들 분석 결과</h1>")
    o.append("<p class='cluster'>%s</p>" % e(f["cluster_name"]))
    o.append("<p class='sub'>버전 %s · 배포 형태 %s · 수집 %s · 수집 모드 %s · 서버 로그 %s</p>"
             % (e(f["version"]), e(f.get("deployment")), e(f["collected_at"]),
                e(f["diag_type"]), "포함" if f["has_logs"] else "미포함"))
    o.append("<p class='sub'>분석 도구 esdiag v%s · 판정 기준 %s</p>"
             % (e(f.get("tool_version")), e(f.get("baseline"))))
    total = max(1, sum(c.values()))
    o.append("<div class='verdict'><div><div class='grade' style='font-size:24px'>종합 판정: %s</div>"
             % e(result.grade))
    o.append("<div class='sevbar'>")
    for key, cls in ((Severity.CRITICAL, "c"), (Severity.WARNING, "w"),
                     (Severity.INFO, "i"), (Severity.OK, "o")):
        if c[key]:
            o.append("<i class='%s' style='width:%.1f%%'></i>" % (cls, c[key] / float(total) * 100))
    o.append("</div><div class='pills'>")
    o.append("<span class='pill c'>치명 <b>%d</b></span>" % c[Severity.CRITICAL])
    o.append("<span class='pill w'>주의 <b>%d</b></span>" % c[Severity.WARNING])
    o.append("<span class='pill i'>참고 <b>%d</b></span>" % c[Severity.INFO])
    o.append("<span class='pill o'>정상 <b>%d</b></span>" % c[Severity.OK])
    o.append("</div></div></div>")
    o.append("<div class='facts'>")
    for label, val in [
        ("클러스터 상태", f["status"]), ("노드", "%s대" % f["nodes_total"]),
        ("데이터 노드", "%s대" % f["data_nodes"]), ("마스터 후보", "%s대" % f["master_nodes"]),
        ("인덱스", f["indices"]), ("샤드", f["shards"]),
        ("문서", "{:,}".format(f["docs"]) if isinstance(f["docs"], int) else f["docs"]),
        ("저장 용량", f["store"]), ("라이선스", f["license"]),
    ]:
        o.append("<div><span>%s</span><strong>%s</strong></div>" % (e(label), e(val)))
    o.append("</div></header>")

    # ---------- 조치 우선순위 ----------
    act = result.actionable()
    if act:
        o.append("<h2>조치 우선순위<small>치명·주의 %d건</small></h2><ol class='prio'>" % len(act))
        for fd in act:
            o.append("<li><span class='tag %s'>%s</span><a href='#%s' data-jump='%s'>%s</a> — %s</li>"
                     % (_CLS[fd.severity], Severity.LABEL_KO[fd.severity], e(fd.id), e(fd.id),
                        e(fd.title), e(fd.observed)))
        o.append("</ol>")

    # ---------- 영역별 점검 결과 ----------
    o.append("<h2>영역별 점검 결과<small>헬스 체크 영역별 상태</small></h2><div class='scroll'><table><thead><tr>"
             "<th>영역</th><th>상태</th><th>치명</th><th>주의</th><th>참고</th><th>정상</th><th>포함 분류</th>"
             "</tr></thead><tbody>")
    _st = {"조치 필요": "c", "점검 권고": "w", "양호": "o", "판정 없음": "i"}
    for a in result.area_summary():
        o.append("<tr><td class='n'>%s</td><td><span class='tag %s'>%s</span></td><td>%d</td><td>%d</td>"
                 "<td>%d</td><td>%d</td><td>%s</td></tr>"
                 % (e(a["area"]), _st[a["status"]], e(a["status"]), a["critical"], a["warning"], a["info"], a["ok"],
                    e(" · ".join(a["categories"]))))
    o.append("</tbody></table></div>")

    # ---------- 변화 요약(diff) ----------
    ds = getattr(result, "diff_summary", None)
    if ds:
        hrs = ds.get("hours")
        o.append("<h2>이전 번들 대비 변화<small>%s</small></h2>"
                 % (("%.1f시간 간격" % hrs) if hrs else "수집 간격 산출 불가"))
        o.append("<div class='scroll'>")
        o.append(_table({"columns": ds["columns"], "rows": ds["rows"]}))
        o.append("</div>")
        o.append("<p class='legend'>누적 카운터(rejection·GC·circuit breaker)는 '변화 추세' "
                 "카테고리에서 증가분으로 판정합니다. 증가가 없으면 과거 이력일 뿐 현재 문제가 "
                 "아닙니다.</p>")

    # ---------- 노드 상태 매트릭스 ----------
    if f["nodes"]:
        o.append("<h2>노드 상태 한눈에 보기<small>자원 편중(hot spotting) 확인용</small></h2>")
        o.append("<div class='scroll'><table class='matrix'><thead><tr>"
                 "<th>노드</th><th>역할</th><th>heap 사용률</th><th>CPU</th><th>load15/코어</th>"
                 "<th>디스크 사용률</th><th>샤드 수</th><th>heap</th><th>RAM</th><th>zone</th>"
                 "</tr></thead><tbody>")
        counts = [n.get("shard_count") or 0 for n in f["nodes"]]
        max_shards = max(counts or [1]) or 1
        avg_shards = (sum(counts) / float(len(counts))) if counts else 1
        for n in f["nodes"]:
            roles = []
            if n.get("is_master"):
                roles.append("master")
            if n.get("is_data"):
                roles.append("data")
            o.append("<tr><td class='n'>%s</td><td>%s</td>"
                     % (e(n["name"]), e("/".join(roles) or "-")))
            o.append(_bar(n.get("heap_pct_num"), 75, 85))
            o.append(_bar(n.get("cpu_pct_num"), 70, 90))
            o.append(_bar(n.get("load_per_cpu"), 1.0, 1.5, suffix="", scale=2.0))
            o.append(_bar(n.get("disk_pct_num"), 75, 85))
            # 샤드 수는 평균 대비 편차로 색을 준다(전체가 균등하면 모두 초록)
            o.append(_bar(n.get("shard_count"), avg_shards * 1.3, avg_shards * 1.6,
                          suffix="", scale=max_shards))
            o.append("<td>%s</td><td>%s</td><td>%s</td></tr>"
                     % (e(n["heap_max"]), e(n["ram"]), e(n["zone"])))
        o.append("</tbody></table></div>")
        o.append("<p class='legend'>초록=정상, 주황=주의 기준 초과, 빨강=위험 기준 초과. "
                 "load15/코어는 2.0, 샤드 수는 노드 최대값을 100% 로 정규화했습니다. "
                 "막대 길이가 노드마다 크게 다르면 hot spotting 을 의심합니다.</p>")

    # ---------- 상위 인덱스 ----------
    tops = [t for t in (f.get("top_indices") or []) if t.get("size")]
    if tops:
        o.append("<h2>저장 용량 상위 인덱스<small>상위 %d개</small></h2>" % len(tops))
        o.append("<div class='scroll'><table><thead><tr><th>인덱스</th><th>크기</th>"
                 "<th>문서 수</th><th>샤드</th><th>평균 검색 지연</th></tr></thead><tbody>")
        mx = float(tops[0]["size"]) or 1.0
        for t in tops:
            lat = t.get("latency")
            latcls = "c" if (lat and lat >= 1000) else ("w" if (lat and lat >= 200) else "o")
            o.append("<tr><td class='n'>%s</td>" % e(t["name"]))
            o.append("<td><div class='bar'><span class='v'>%s</span>"
                     "<span class='track'><span class='fill' style='width:%.1f%%'></span></span>"
                     "</div></td>" % (e(t["size_h"]), t["size"] / mx * 100))
            o.append("<td>%s</td><td>%s</td><td>%s</td></tr>"
                     % ("{:,}".format(t["docs"]), t["shards"],
                        ("<span class='tag %s'>%.0fms</span>" % (latcls, lat)) if lat else "-"))
        o.append("</tbody></table></div>")

    # ---------- 필터 + 카테고리 이동 ----------
    cats = []
    for fd in result.by_severity():
        if fd.category not in cats:
            cats.append(fd.category)
    o.append("<div class='nav'><span style='color:var(--muted);font-size:13px'>심각도</span>"
             "<button data-level='all'>전체</button>"
             "<button data-level='act'>조치 대상</button>"
             "<button data-level='CRITICAL'>치명</button>"
             "<button data-level='WARNING'>주의</button>"
             "<button data-level='INFO'>참고</button>"
             "<button data-level='OK'>정상</button><span class='sep'></span>"
             "<span style='color:var(--muted);font-size:13px'>영역</span>"
             "<button data-cat='all'>전체</button>")
    for cat in cats:
        o.append("<button data-cat='%s'>%s</button>" % (e(cat), e(cat)))
    o.append("<span id='fcount' style='color:var(--muted);font-size:12px;margin-left:auto'></span></div>")

    # ---------- 판정 결과 ----------
    cur = None
    for fd in result.by_severity():
        if fd.category != cur:
            cur = fd.category
            n_cat = len([x for x in result.findings if x.category == cur])
            o.append("<h2 data-cat='%s' id='%s'>%s<small>%d건</small></h2>"
                     % (e(cur), _cat_id(cur), e(cur), n_cat))
        cls = _CLS[fd.severity]
        o.append("<div class='f %s' data-sev='%s' data-cat='%s' id='%s'>" % (cls, fd.severity, e(fd.category), e(fd.id)))
        o.append("<h3><span class='tag %s'>%s</span>%s<span class='rid'>%s · %s</span></h3>"
                 % (cls, Severity.LABEL_KO[fd.severity], e(fd.title), e(fd.basis or ""), e(fd.id)))
        o.append("<dl>")
        if fd.observed:
            o.append("<dt>관측</dt><dd>%s</dd>" % e(fd.observed))
        if fd.impact:
            o.append("<dt>영향</dt><dd>%s</dd>" % e(fd.impact))
        if fd.recommend:
            o.append("<dt>권고</dt><dd>%s</dd>" % e(fd.recommend))
        if fd.affected:
            o.append("<dt>대상</dt><dd>%s</dd>" % e(", ".join(fd.affected[:30])))
        o.append("</dl>")
        if fd.evidence and fd.evidence.get("rows"):
            opened = " open" if fd.severity == Severity.CRITICAL else ""
            o.append("<details%s><summary>근거 데이터 %d행</summary><div class='scroll'>"
                     % (opened, len(fd.evidence["rows"])))
            o.append(_table(fd.evidence))
            o.append("</div></details>")
        src = "출처: %s" % e(fd.source) if fd.source else ""
        refs = " · ".join("<a href='%s'>%s</a>" % (e(u), e(t)) for t, u in fd.refs)
        if src or refs:
            o.append("<p class='src'>%s%s</p>" % (src, (" · " + refs) if refs else ""))
        o.append("</div>")

    skipped = getattr(result.ctx, "skipped_rules", [])
    if skipped:
        o.append("<h2>입력 미수집으로 판정하지 않은 항목<small>%d개 룰</small></h2>" % len(skipped))
        o.append("<p class='legend'>번들에 해당 파일이 없어 판정하지 않았습니다. '문제 없음' 이 아니라 "
                 "'확인하지 못함' 입니다. 수집 모드·계정 권한·support-diagnostics 버전을 확인하십시오.</p>")
        o.append("<div class='scroll'>")
        o.append(_table({"columns": ["룰", "필요한 파일"],
                         "rows": [[x["rule"], " / ".join(x["missing"])] for x in skipped]}))
        o.append("</div>")

    if result.errors:
        o.append("<h2>도구 오류로 판정하지 못한 항목<small>%d개 룰</small></h2>" % len(result.errors))
        o.append("<p class='legend'>클러스터 문제가 아니라, 이 도구가 해당 번들의 데이터 형식을 처리하지 못한 것입니다. "
                 "해당 룰은 '확인하지 못함' 이며 나머지 판정에는 영향이 없습니다. 상세 추적 정보는 개발자 확인용입니다.</p>")
        o.append("<details><summary>상세 추적 정보(개발자용)</summary><div class='scroll'>")
        o.append(_table({"columns": ["룰", "오류"],
                         "rows": [[x["rule"], ([ln for ln in x["error"].strip().splitlines() if ln.strip()][-1:]
                                               or [""])[0]] for x in result.errors]}))
        o.append("<pre style='white-space:pre-wrap;font-size:12px'>%s</pre>"
                 % e("\n\n".join("%s\n%s" % (x["rule"], x["error"]) for x in result.errors)))
        o.append("</div></details>")

    o.append("<h2>판정 근거 구분</h2><div class='scroll'><table><thead><tr><th>구분</th><th>의미</th>"
             "</tr></thead><tbody>"
             "<tr><td>공식 기준</td><td>판정 기준이 Elastic 공식 문서에 명시된 항목</td></tr>"
             "<tr><td>사실 보고</td><td>Elasticsearch 가 보고한 상태·오류·설정값을 그대로 전달(임계값 없음)</td></tr>"
             "<tr><td>도구 판단</td><td>공식 수치 기준이 없어 이 도구의 임계값으로 판단한 항목. "
             "thresholds.py 에서 조정 가능</td></tr>"
             "<tr><td>비교 계산</td><td>두 번들 간 증가분·증가율·선형 외삽 결과</td></tr>"
             "</tbody></table></div>")
    o.append("<footer>이 리포트는 support-diagnostics 산출물만을 근거로 오프라인에서 생성되었습니다. "
             "수집 시점의 스냅샷 값(누적 카운터 포함)에 기반하므로, 시계열 추세가 필요한 항목은 "
             "모니터링 데이터와 교차 확인하십시오.</footer>")
    o.append("</div><script>%s</script></body></html>" % JS)
    return "\n".join(o)


def _table(ev):
    o = ["<table><thead><tr>"]
    for c in ev["columns"]:
        o.append("<th>%s</th>" % e(c))
    o.append("</tr></thead><tbody>")
    for r in ev["rows"]:
        o.append("<tr>" + "".join("<td>%s</td>" % e(v) for v in r) + "</tr>")
    o.append("</tbody></table>")
    return "".join(o)
