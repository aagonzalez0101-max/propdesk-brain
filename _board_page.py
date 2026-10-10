"""Builds soccer_board.html from the day's soccer screen (_soccer.py) -- the page the user checks to see
what should hit and what should not. Republish after every screen:

    python _board_page.py _soccer_board_2026-10-01.json [more.json ...]   -> soccer_board.html
"""
import sys, json, datetime

CT = datetime.timezone(datetime.timedelta(hours=-5))
rows = []
for f in sys.argv[1:] or ["_soccer_board.json"]:
    rows += json.load(open(f, encoding="utf-8"))
for r in rows:
    st = datetime.datetime.fromisoformat(r["start"].replace("Z", "+00:00")).astimezone(CT)
    r["kick"] = "%s %s %d, %d:%s" % (st.strftime("%a"), st.strftime("%b"), st.day, (st.hour % 12) or 12, st.strftime("%M %p"))
    r["kick_sort"] = st.isoformat()
built = datetime.datetime.now(CT).strftime("%b %d, %I:%M %p CT").replace(" 0", " ")
data = json.dumps(dict(rows=rows, built=built, breakeven=0.577), ensure_ascii=False).replace("</", "<\\/")

html = r"""<title>Soccer Prop Board</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: a match-day sheet -- summary strip, filter bar, then one block per kickoff with a row per prop. */
:root{
  --bg:#eef1ec; --panel:#ffffff; --ink:#1b2420; --muted:#5d6b64; --rule:#d6ddd8; --turf:#1f6b4a;
  --hit:#1f7a4d; --hit-bg:#dcefe4; --lean:#9a6a06; --lean-bg:#f6ecd2; --avoid:#8b4a44; --avoid-bg:#f1e1df;
  --bar:#c9d3cd; --mark:#1b2420;
  --display:"Barlow Condensed","Arial Narrow",sans-serif; --body:"IBM Plex Sans",system-ui,sans-serif; --mono:"IBM Plex Mono",ui-monospace,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#121815; --panel:#1a221e; --ink:#e3ebe6; --muted:#93a39a; --rule:#2c3832; --turf:#5fbf8f;
  --hit:#6fd39f; --hit-bg:#1d3a2b; --lean:#e4b64e; --lean-bg:#3a311a; --avoid:#e08f86; --avoid-bg:#3a2422;
  --bar:#34423b; --mark:#e3ebe6; color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#121815; --panel:#1a221e; --ink:#e3ebe6; --muted:#93a39a; --rule:#2c3832; --turf:#5fbf8f;
  --hit:#6fd39f; --hit-bg:#1d3a2b; --lean:#e4b64e; --lean-bg:#3a311a; --avoid:#e08f86; --avoid-bg:#3a2422;
  --bar:#34423b; --mark:#e3ebe6; color-scheme:dark}
body{background:var(--bg);color:var(--ink);font-family:var(--body);font-size:14px;line-height:1.45}
.wrap{max-width:1080px;margin:0 auto;padding-inline:16px;padding-block:20px 48px;display:grid;gap:18px}
header{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:12px}
h1{font-family:var(--display);font-weight:700;font-size:40px;letter-spacing:.01em;margin:0;line-height:1;text-wrap:balance}
.sub{color:var(--muted);font-size:13px}
.strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.tile{background:var(--panel);border:1px solid var(--rule);border-radius:10px;padding:12px 14px;display:grid;gap:2px}
.tile b{font-family:var(--display);font-size:30px;line-height:1;font-variant-numeric:tabular-nums}
.tile span{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.tile.hit b{color:var(--hit)} .tile.lean b{color:var(--lean)} .tile.avoid b{color:var(--avoid)}
.bal{height:6px;border-radius:3px;background:var(--bar);overflow:hidden;margin-top:6px}
.bal i{display:block;height:100%;background:var(--turf)}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.chip{font:inherit;font-size:13px;border:1px solid var(--rule);background:var(--panel);color:var(--ink);border-radius:999px;padding:6px 12px;cursor:pointer}
.chip[aria-pressed="true"]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.chip:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--turf);outline-offset:2px}
select,input{font:inherit;font-size:13px;background:var(--panel);color:var(--ink);border:1px solid var(--rule);border-radius:8px;padding:6px 10px}
input{min-width:0;flex:1 1 160px}
.match{background:var(--panel);border:1px solid var(--rule);border-radius:12px;overflow:hidden}
.match h2{margin:0;padding:10px 14px;font-family:var(--display);font-size:20px;font-weight:600;letter-spacing:.02em;
  display:flex;flex-wrap:wrap;justify-content:space-between;gap:6px;border-bottom:1px solid var(--rule)}
.match h2 small{font-family:var(--body);font-size:12px;color:var(--muted);font-weight:500;letter-spacing:0}
.row{display:grid;grid-template-columns:76px minmax(0,1.5fr) minmax(0,1.1fr) 150px 120px;gap:12px;align-items:center;
  padding:10px 14px;border-top:1px solid var(--rule)}
.row:first-of-type{border-top:0}
.pill{font-family:var(--display);font-weight:700;font-size:14px;letter-spacing:.06em;text-align:center;border-radius:6px;padding:3px 0}
.pill.HIT{color:var(--hit);background:var(--hit-bg)} .pill.LEAN{color:var(--lean);background:var(--lean-bg)} .pill.AVOID{color:var(--avoid);background:var(--avoid-bg)}
.who{min-width:0} .who b{display:block;font-weight:600;overflow-wrap:anywhere} .who span{font-size:12px;color:var(--muted)}
.bet{min-width:0} .bet b{font-weight:600} .bet span{display:block;font-size:12px;color:var(--muted)} .bet .script{font-weight:600;color:var(--ink)}
.prob{display:grid;gap:4px}
.prob .num{font-family:var(--mono);font-size:13px;font-variant-numeric:tabular-nums}
.meter{position:relative;height:8px;border-radius:4px;background:var(--bar)}
.meter i{position:absolute;left:0;top:0;bottom:0;border-radius:4px;background:var(--muted)}
.row[data-v="HIT"] .meter i{background:var(--hit)} .row[data-v="LEAN"] .meter i{background:var(--lean)}
.meter u{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--mark);text-decoration:none}
.last{display:flex;gap:3px;align-items:flex-end;height:30px}
.last i{width:14px;border-radius:2px 2px 0 0;background:var(--bar);position:relative}
.last i.win{background:var(--turf)}
.last em{font-style:normal;font-family:var(--mono);font-size:10px;color:var(--muted);margin-left:4px;align-self:center;white-space:nowrap}
.flags{grid-column:2 / -1;display:flex;flex-wrap:wrap;gap:6px;margin-top:-4px}
.flag{font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:var(--avoid);border:1px solid var(--avoid);border-radius:4px;padding:1px 6px}
.note{color:var(--muted);font-size:12.5px;max-width:70ch}
.empty{padding:28px;text-align:center;color:var(--muted)}
.card{overflow-x:auto;border-bottom:1px solid var(--rule)}
.card table{border-collapse:collapse;font-size:12px;width:100%;min-width:520px;font-variant-numeric:tabular-nums}
.card th,.card td{padding:5px 10px;text-align:right;white-space:nowrap}
.card th:first-child,.card td:first-child{text-align:left;color:var(--muted);font-weight:500}
.card thead th{color:var(--muted);font-weight:500;text-transform:uppercase;letter-spacing:.05em;font-size:11px}
@media (max-width:720px){
  .row{grid-template-columns:64px minmax(0,1fr) 110px;grid-template-areas:"p w pr" "p b l"}
  .row .pill{grid-area:p;align-self:start} .row .who{grid-area:w} .row .bet{grid-area:b} .row .prob{grid-area:pr} .row .last{grid-area:l}
  .flags{grid-column:2 / -1}
}
@media (prefers-reduced-motion:no-preference){.meter i{transition:width .3s}}
</style>

<div class="wrap">
  <header>
    <div>
      <h1>Soccer Prop Board</h1>
      <div class="sub" id="sub"></div>
    </div>
    <div class="sub">PrizePicks standard lines &middot; 2-pick break-even <b>57.7%</b></div>
  </header>

  <section class="strip" id="strip" aria-label="Summary"></section>

  <section class="filters" aria-label="Filters">
    <button class="chip" id="f-all" aria-pressed="true" data-v="ALL">All</button>
    <button class="chip" id="f-hit" aria-pressed="false" data-v="HIT">Hit</button>
    <button class="chip" id="f-lean" aria-pressed="false" data-v="LEAN">Lean</button>
    <button class="chip" id="f-avoid" aria-pressed="false" data-v="AVOID">Avoid</button>
    <select id="f-stat" aria-label="Market"><option value="">Every market</option></select>
    <input id="f-q" type="search" placeholder="Player or team" aria-label="Search player or team">
  </section>

  <main id="board"></main>

  <p class="note">How to read it: the bar is the share of the player's last 15 starts (60+ minutes) that landed on the
  listed side, pulled toward 50% for small samples; the black tick is the 57.7% a PrizePicks 2-pick needs. Bars under the
  "last 5 starts" heading are those games, green when they cleared. HIT needs 60.7%+ with no rotation or injury flag;
  LEAN clears break-even but not the cushion. Soccer has no sharp prop price anywhere free, so these are model reads, graded
  on paper until the record earns real money. Each average is adjusted for tonight's opponent from its last 10 matches (passes it
  allows, shots and shots on target it creates and concedes), and FAV / EVEN / DOG is the team's win chance from Pinnacle's odds. A
  pick that runs against that game script (an under on a big favourite's passing, an over on its keeper's saves) is held to LEAN.</p>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
  var D = JSON.parse(document.getElementById("data").textContent);
  var BE = D.breakeven, rows = D.rows, state = {v:"ALL", stat:"", q:""};
  try { var saved = JSON.parse(localStorage.getItem("spb-filter")||"null"); if (saved) state = Object.assign(state, saved); } catch(e){}
  document.getElementById("sub").textContent = rows.length + " props screened · built " + D.built;

  var stats = Array.from(new Set(rows.map(function(r){return r.stat;}))).sort();
  var sel = document.getElementById("f-stat");
  stats.forEach(function(s){ var o=document.createElement("option"); o.value=s; o.textContent=s; sel.appendChild(o); });

  function esc(s){ return String(s==null?"":s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c];}); }
  function pct(x){ return Math.round(x*100) + "%"; }

  function strip(list){
    var c = {HIT:0,LEAN:0,AVOID:0}; list.forEach(function(r){c[r.verdict]++;});
    var hit = list.filter(function(r){return r.verdict==="HIT";});
    var ov = hit.length ? hit.filter(function(r){return r.side==="over";}).length/hit.length : 0;
    var bal = hit.length ? pct(ov) + " overs" : "no HIT legs";
    var warn = hit.length && Math.max(ov,1-ov) > .6 ? " · over the 60% cap" : "";
    document.getElementById("strip").innerHTML =
      '<div class="tile hit"><b>'+c.HIT+'</b><span>Hit</span></div>'+
      '<div class="tile lean"><b>'+c.LEAN+'</b><span>Lean</span></div>'+
      '<div class="tile avoid"><b>'+c.AVOID+'</b><span>Avoid</span></div>'+
      '<div class="tile"><b style="font-size:20px">'+esc(bal)+'</b><span>Hit balance'+esc(warn)+'</span><div class="bal"><i style="width:'+(ov*100)+'%"></i></div></div>';
  }

  function rowHTML(r){
    var line = r.line, side = r.side;
    var mx = Math.max.apply(null, r.last5.concat([line*1.5, 1]));
    var bars = r.last5.map(function(v){
      var win = side==="over" ? v>line : v<line;
      return '<i class="'+(win?"win":"")+'" style="height:'+Math.max(6, Math.round(v/mx*30))+'px" title="'+v+'"></i>';
    }).join("");
    var flags = (r.flags||[]).map(function(f){return '<span class="flag">'+esc(f)+'</span>';}).join("");
    return '<div class="row" data-v="'+r.verdict+'">'+
      '<div class="pill '+r.verdict+'">'+r.verdict+'</div>'+
      '<div class="who"><b>'+esc(r.player)+'</b><span>'+esc(r.team||"")+(r.position?" · "+esc(r.position):"")+'</span></div>'+
      '<div class="bet"><b>'+(side==="over"?"Over":"Under")+' '+line+' '+esc(r.stat)+'</b><span>'+(r.opp?'v '+esc(r.opp)+' · ':'')+(r.script?'<b class="script">'+esc(r.script)+'</b> · ':'')+'avg '+r.avg+(r.adj_avg!=null&&r.adj_avg!==r.avg?' → '+r.adj_avg+' vs this opponent':'')+' · '+r.hits+'/'+r.n+' starts</span></div>'+
      '<div class="prob"><span class="num">'+pct(r.p)+' '+(side)+'</span>'+(r.call?'<span class="num" style="font-size:11px;color:var(--muted)">proj '+r.adj_avg+' vs '+line+' → '+esc(r.call)+'</span>':'')+'<div class="meter" role="img" aria-label="'+pct(r.p)+' against 57.7% break-even"><i style="width:'+(r.p*100)+'%"></i><u style="left:'+(BE*100)+'%"></u></div></div>'+
      '<div class="last" aria-label="last 5 starts">'+bars+'<em>last 5</em></div>'+
      (flags?'<div class="flags">'+flags+'</div>':'')+
    '</div>';
  }

  function cardHTML(g){
    var r = g.find(function(x){ return x.card && x.card.team && x.card.opp; });
    if (!r) return "";
    var A = r.card.team, B = r.card.opp;
    var L = [["Possession %","poss"],["Passes","passes"],["Shots","shots"],["Shots on target","sot"],["xG","xg"],["Goals","goals"]];
    var f = function(v){ return v==null ? "–" : v; };
    var rows = L.map(function(x){ return '<tr><td>'+x[0]+'</td><td>'+f(A["f_"+x[1]])+'</td><td>'+f(A["a_"+x[1]])+'</td><td>'+f(B["f_"+x[1]])+'</td><td>'+f(B["a_"+x[1]])+'</td></tr>'; }).join("");
    return '<div class="card"><table><thead><tr><th>Last 10 matches</th><th>'+esc(r.team)+' makes</th><th>'+esc(r.team)+' allows</th><th>'+esc(r.opp)+' makes</th><th>'+esc(r.opp)+' allows</th></tr></thead><tbody>'+rows+'</tbody></table></div>';
  }

  function render(){
    ["f-all","f-hit","f-lean","f-avoid"].forEach(function(id){
      var b=document.getElementById(id); b.setAttribute("aria-pressed", String(b.dataset.v===state.v)); });
    sel.value = state.stat; document.getElementById("f-q").value = state.q;
    var q = state.q.toLowerCase();
    var list = rows.filter(function(r){
      return (state.v==="ALL"||r.verdict===state.v) && (!state.stat||r.stat===state.stat) &&
             (!q || (r.player+" "+(r.team||"")+" "+(r.opp_team||r.opp||"")).toLowerCase().indexOf(q)>=0);
    });
    strip(rows.filter(function(r){ return (!state.stat||r.stat===state.stat); }));
    var groups = {};
    list.forEach(function(r){ var k=r.kick_sort+"|"+r.kick; (groups[k]=groups[k]||[]).push(r); });
    var order = {HIT:0,LEAN:1,AVOID:2};
    var html = Object.keys(groups).sort().map(function(k){
      var g = groups[k].sort(function(a,b){ return order[a.verdict]-order[b.verdict] || b.p-a.p; });
      var teams = Array.from(new Set(g.map(function(r){return r.team;}).filter(Boolean))).slice(0,2).join(" v ");
      var nh = g.filter(function(r){return r.verdict==="HIT";}).length;
      return '<section class="match"><h2>'+esc(teams||"Match")+'<small>'+esc(k.split("|")[1])+' CT · '+nh+' hit</small></h2>'+cardHTML(g)+g.map(rowHTML).join("")+'</section>';
    }).join("");
    document.getElementById("board").innerHTML = html || '<div class="match empty">No props match these filters.</div>';
    try { localStorage.setItem("spb-filter", JSON.stringify(state)); } catch(e){}
  }

  document.querySelectorAll(".chip").forEach(function(b){ b.addEventListener("click", function(){ state.v=b.dataset.v; render(); }); });
  sel.addEventListener("change", function(){ state.stat=sel.value; render(); });
  document.getElementById("f-q").addEventListener("input", function(e){ state.q=e.target.value; render(); });
  render();
})();
</script>
"""
open("soccer_board.html", "w", encoding="utf-8").write(html.replace("__DATA__", data))
print("soccer_board.html: %d rows" % len(rows))
