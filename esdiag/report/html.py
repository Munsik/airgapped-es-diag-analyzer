# -*- coding: utf-8 -*-
"""Single-file HTML report. It references no external CSS, JS, fonts or images (air-gapped use).

Charts are plain CSS bars. No chart library is used, so one file opens in any browser.
"""

import html as _h
import json

from ..i18n import T, get_lang
from .. import bottleneck as btl
from ..model import Severity, category_label
from ..util import truncate

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
ol.prio .rel{font-size:12.5px;color:var(--muted);margin:3px 0 0}
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
html[lang=en] dt{width:110px} html[lang=en] dd{margin-left:124px}
details{margin-top:12px}
summary{cursor:pointer;color:var(--muted);font-size:13px}
table{border-collapse:collapse;width:100%;margin-top:10px;font-size:13px}
th,td{border:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:middle;
  word-break:break-word}
th{background:#eef0f1;font-weight:600}
html[lang=en] th,html[lang=en] td{word-break:normal;overflow-wrap:break-word}
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
@media (max-width:640px){dt,html[lang=en] dt{float:none;width:auto;font-weight:600} dd,html[lang=en] dd{margin-left:0}}
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
    var fc=document.getElementById('fcount'); if(fc){fc.textContent=_T.shown.replace('%d',shown);}
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
    """Render a number as a bar cell. scale is the value that maps to a 100% bar."""
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
    o.append("<!DOCTYPE html><html lang='%s'><head><meta charset='utf-8'>" % get_lang())
    o.append("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    o.append(T("report.html.render.01") % e(f["cluster_name"]))
    o.append("<style>%s</style></head><body><div class='wrap'>" % CSS)

    # ---------- header ----------
    o.append("<header>")
    o.append(T("report.html.render.02"))
    o.append("<p class='cluster'>%s</p>" % e(f["cluster_name"]))
    o.append(T("report.html.render.03")
             % (e(f["version"]), e(f.get("deployment")), e(f.get("collected_display") or f["collected_at"]),
                e(f["diag_type"]), T("report.html.render.04") if f["has_logs"] else T("report.html.render.05")))
    o.append(T("report.html.render.06")
             % (e(f.get("tool_version")), e(f.get("baseline"))))
    total = max(1, sum(c.values()))
    o.append(T("report.html.render.07")
             % e(result.grade))
    o.append("<div class='sevbar'>")
    for key, cls in ((Severity.CRITICAL, "c"), (Severity.WARNING, "w"),
                     (Severity.INFO, "i"), (Severity.OK, "o")):
        if c[key]:
            o.append("<i class='%s' style='width:%.1f%%'></i>" % (cls, c[key] / float(total) * 100))
    o.append("</div><div class='pills'>")
    o.append(T("report.html.render.08") % c[Severity.CRITICAL])
    o.append(T("report.html.render.09") % c[Severity.WARNING])
    o.append(T("report.html.render.10") % c[Severity.INFO])
    o.append(T("report.html.render.11") % c[Severity.OK])
    o.append("</div></div></div>")
    o.append("<div class='facts'>")
    for label, val in [
        (T("report.html.render.12"), f["status"]), (T("report.html.render.13"), T("report.html.render.14") % f["nodes_total"]),
        (T("report.html.render.15"), T("report.html.render.14") % f["data_nodes"]), (T("report.html.render.16"), T("report.html.render.14") % f["master_nodes"]),
        (T("report.html.render.17"), f["indices"]), (T("report.html.render.18"), f["shards"]),
        (T("report.html.render.19"), "{:,}".format(f["docs"]) if isinstance(f["docs"], int) else f["docs"]),
        (T("report.html.render.20"), f["store"]), (T("report.html.render.21"), f["license"]),
    ]:
        o.append("<div><span>%s</span><strong>%s</strong></div>" % (e(label), e(val)))
    o.append("</div></header>")

    # ---------- Bottleneck summary ----------
    rows = result.bottleneck()
    if rows:
        o.append("<h2>%s<small>%s</small></h2><div class='scroll'><table><thead><tr><th>%s</th><th>%s</th><th>%s</th><th>%s</th></tr></thead><tbody>"
                 % (e(T("btl.title")), e(T("btl.intro")), e(T("btl.col.q")), e(T("btl.col.v")), e(T("btl.col.b")), e(T("btl.col.n"))))
        for r in rows:
            q, v, b, nx = btl.cells(r)
            links = ", ".join("<a href='#%s' data-jump='%s'>%s</a>" % (e(i), e(i), e(i)) for i in r["causes"])
            basis = " / ".join(e(x) for x in r["basis"])
            if links:
                basis = (basis + " / " if basis else "") + (e(T("btl.findings")) % links)
            o.append("<tr><td class='n'>%s</td><td><span class='tag %s'>%s</span></td><td>%s</td><td>%s</td></tr>"
                     % (e(q), btl.css(r), e(v), basis or "-", e(nx)))
        o.append("</tbody></table></div>")

    # ---------- Action priority ----------
    act = result.priority()
    if act:
        n_all = len(result.actionable())
        sub = (T("report.html.render.22") % n_all) if n_all == len(act) else \
              (T("report.html.render.23") % (n_all, len(act)))
        o.append(T("report.html.render.24") % sub)
        for fd, rel in act:
            relh = ""
            if rel:
                relh = T("report.html.render.25") % " · ".join(
                    "<a href='#%s' data-jump='%s'>%s</a>" % (e(r.id), e(r.id), e(r.title)) for r in rel)
            o.append(T("report.html.prio") % (_CLS[fd.severity], Severity.label(fd.severity), e(fd.id), e(fd.id),
                        e(fd.title), e(truncate(fd.observed, 220)), relh))
        o.append("</ol>")

    # ---------- Results by area ----------
    o.append(T("report.html.render.26"))
    _st = {"action": "c", "review": "w", "good": "o", "none": "i"}
    for a in result.area_summary():
        o.append("<tr><td class='n'>%s</td><td><span class='tag %s'>%s</span></td><td>%d</td><td>%d</td>"
                 "<td>%d</td><td>%d</td><td>%s</td></tr>"
                 % (e(a["area"]), _st[a["status_id"]], e(a["status"]), a["critical"], a["warning"], a["info"], a["ok"],
                    e(" · ".join(a["categories"]))))
    o.append("</tbody></table></div>")

    # ---------- Change summary (diff) ----------
    ds = getattr(result, "diff_summary", None)
    if ds:
        hrs = ds.get("hours")
        o.append(T("report.html.render.27")
                 % ((T("report.html.render.28") % hrs) if hrs else T("report.html.render.29")))
        o.append("<div class='scroll'>")
        o.append(_table({"columns": ds["columns"], "rows": ds["rows"]}))
        o.append("</div>")
        o.append(T("report.html.render.30"))

    # ---------- Node status matrix ----------
    if f["nodes"]:
        o.append(T("report.html.render.31"))
        o.append(T("report.html.render.32"))
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
            # Shard count is colored by deviation from the average (all green when evenly distributed)
            o.append(_bar(n.get("shard_count"), avg_shards * 1.3, avg_shards * 1.6,
                          suffix="", scale=max_shards))
            o.append("<td>%s</td><td>%s</td><td>%s</td></tr>"
                     % (e(n["heap_max"]), e(n["ram"]), e(n["zone"])))
        o.append("</tbody></table></div>")
        o.append(T("report.html.render.33"))

    # ---------- Top indices ----------
    tops = [t for t in (f.get("top_indices") or []) if t.get("size")]
    if tops:
        o.append(T("report.html.render.34") % len(tops))
        o.append(T("report.html.render.35"))
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

    # ---------- Filter + category navigation ----------
    cats = []
    for fd in result.by_severity():
        if fd.category not in cats:
            cats.append(fd.category)
    o.append(T("report.html.render.36"))
    for cat in cats:
        o.append("<button data-cat='%s'>%s</button>" % (e(category_label(cat)), e(category_label(cat))))
    o.append("<span id='fcount' style='color:var(--muted);font-size:12px;margin-left:auto'></span></div>")

    # ---------- Findings ----------
    cur = None
    for fd in result.by_severity():
        if fd.category != cur:
            cur = fd.category
            n_cat = len([x for x in result.findings if x.category == cur])
            o.append(T("report.html.render.37")
                     % (e(category_label(cur)), _cat_id(category_label(cur)), e(category_label(cur)), n_cat))
        cls = _CLS[fd.severity]
        o.append("<div class='f %s' data-sev='%s' data-cat='%s' id='%s'>" % (cls, fd.severity, e(category_label(fd.category)), e(fd.id)))
        o.append("<h3><span class='tag %s'>%s</span>%s<span class='rid'>%s · %s</span></h3>"
                 % (cls, Severity.label(fd.severity), e(fd.title), e(fd.basis or ""), e(fd.id)))
        o.append("<dl>")
        if fd.observed:
            o.append(T("report.html.render.38") % e(fd.observed))
        if fd.impact:
            o.append(T("report.html.render.39") % e(fd.impact))
        if fd.recommend:
            o.append(T("report.html.render.40") % e(fd.recommend))
        if fd.affected:
            o.append(T("report.html.render.41") % e(", ".join(fd.affected[:30])))
        o.append("</dl>")
        if fd.evidence and fd.evidence.get("rows"):
            opened = " open" if fd.severity == Severity.CRITICAL else ""
            o.append(T("report.html.render.42")
                     % (opened, len(fd.evidence["rows"])))
            o.append(_table(fd.evidence))
            o.append("</div></details>")
        src = T("report.html.render.43") % e(fd.source) if fd.source else ""
        refs = " · ".join("<a href='%s'>%s</a>" % (e(u), e(t)) for t, u in fd.refs)
        if src or refs:
            o.append("<p class='src'>%s%s</p>" % (src, (" · " + refs) if refs else ""))
        o.append("</div>")

    skipped = getattr(result.ctx, "skipped_rules", [])
    if skipped:
        o.append(T("report.html.render.44") % len(skipped))
        o.append(T("report.html.render.45"))
        o.append("<div class='scroll'>")
        o.append(_table({"columns": [T("report.html.render.46"), T("report.html.render.47")],
                         "rows": [[x["rule"], " / ".join(x["missing"])] for x in skipped]}))
        o.append("</div>")

    if result.errors:
        o.append(T("report.html.render.48") % len(result.errors))
        o.append(T("report.html.render.49"))
        o.append(T("report.html.render.50"))
        o.append(_table({"columns": [T("report.html.render.46"), T("report.html.render.51")],
                         "rows": [[x["rule"], ([ln for ln in x["error"].strip().splitlines() if ln.strip()][-1:]
                                               or [""])[0]] for x in result.errors]}))
        o.append("<pre style='white-space:pre-wrap;font-size:12px'>%s</pre>"
                 % e("\n\n".join("%s\n%s" % (x["rule"], x["error"]) for x in result.errors)))
        o.append("</div></details>")

    o.append(T("report.html.render.52"))
    o.append(T("report.html.render.53"))
    o.append("</div><script>var _T={shown:%s};%s</script></body></html>" % (json.dumps(T("html.shown"), ensure_ascii=False), JS))
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
