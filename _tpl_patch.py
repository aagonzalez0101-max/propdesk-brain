"""one-off: add photos, the esports hero, and the write-up engine to site/desk_template.html (2026-09-30)"""
p = "site/desk_template.html"
s = open(p, encoding="utf-8").read()
if "function heroCard" in s:
    raise SystemExit("already patched")

css = """
/* photos */
img.av{object-fit:cover;object-position:top;background:var(--raise)}
/* why list */
.why{display:grid;gap:8px;margin:12px 0 4px}
.why h4{margin:6px 0 0;font:700 12px/1 var(--body);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.wi{display:grid;grid-template-columns:20px minmax(0,1fr);gap:9px;align-items:start;font-size:13.5px;line-height:1.5}
.wi .d{width:20px;height:20px;border-radius:6px;display:grid;place-items:center;font-size:10px;font-weight:800;margin-top:1px}
.wi .d.up{background:var(--over-soft);color:var(--over)} .wi .d.dn{background:var(--under-soft);color:var(--under)} .wi .d.nt{background:var(--panel-2);color:var(--muted)}
.wi b{color:var(--ink)}
.math{margin-top:12px;padding-top:12px;border-top:1px solid var(--line)}
/* esports hero */
.hero{position:relative;overflow:hidden;border-radius:18px;border:1px solid var(--line-2);margin-bottom:16px;min-height:300px;
  background:linear-gradient(120deg,var(--c1,#1b2340) 0%,var(--c2,#0f1629) 55%,var(--bg) 100%)}
.hero .art{position:absolute;right:-30px;bottom:-10px;height:118%;max-width:62%;object-fit:contain;object-position:right bottom;
  filter:drop-shadow(0 20px 40px rgba(0,0,0,.55));pointer-events:none}
.hero .glow{position:absolute;inset:0;background:radial-gradient(600px 300px at 80% 30%,var(--c3,rgba(255,255,255,.10)),transparent 70%);pointer-events:none}
.hero .in{position:relative;padding:22px;display:grid;gap:16px;max-width:660px}
.hero .who2{display:flex;gap:14px;align-items:center}
.hero h1{font-size:46px;text-transform:uppercase;letter-spacing:.02em;text-shadow:0 2px 18px rgba(0,0,0,.4)}
.hero .tag{font:700 12px/1 var(--body);letter-spacing:.12em;text-transform:uppercase;color:rgba(255,255,255,.78)}
.kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px}
@media (max-width:760px){.kpis{grid-template-columns:repeat(3,minmax(0,1fr))}.hero .art{opacity:.35;max-width:90%}.hero h1{font-size:34px}}
.kpi{background:rgba(8,12,24,.55);backdrop-filter:blur(6px);border:1px solid rgba(255,255,255,.12);border-radius:12px;padding:9px 10px}
.kpi span{display:block;font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:rgba(255,255,255,.66)}
.kpi b{font:700 24px/1.1 var(--display);color:#fff}
.pool{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.ag{position:relative;overflow:hidden;border-radius:14px;border:1px solid var(--line-2);padding:12px;background:linear-gradient(160deg,var(--a1,#1a2542),var(--panel) 75%)}
.ag .ic{width:46px;height:46px;border-radius:10px;background:rgba(0,0,0,.25);display:block}
.ag .nm{font:700 18px/1 var(--display);text-transform:uppercase;letter-spacing:.04em;margin-top:8px}
.ag .rl{font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.ag .sh{height:5px;border-radius:3px;background:rgba(255,255,255,.08);margin:8px 0 6px;overflow:hidden}
.ag .sh i{display:block;height:100%;background:var(--a2,var(--accent))}
.ag dl{display:grid;grid-template-columns:1fr 1fr;gap:3px 8px;margin:0;font-size:12px}
.ag dt{color:var(--muted)} .ag dd{margin:0;text-align:right;font-weight:700}
.ag.main{border-color:var(--a2,var(--accent));box-shadow:0 0 0 1px var(--a2,var(--accent)) inset}
"""
s = s.replace("</style>", css + "</style>", 1)

def rep(a, b):
    global s
    assert a in s, a[:80]
    s = s.replace(a, b, 1)

rep('let state = {view:"board"', 'let IMG = {players:{}, agents:{}};\n'
    'function avatar(sp, P, cls=""){ const u = ((IMG.players||{})[sp]||{})[P.id]; return u ? `<img class="av ${cls}" src="${u}" alt="">` : `<div class="av ${cls}">${esc(initials(P.name))}</div>`; }\n'
    'let state = {view:"board"')
rep('<div class="who"><div class="av">${esc(initials(P.name))}</div>', '<div class="who">${avatar(r.sp, P)}')
rep('  <div class="phead"><div class="av big">${esc(initials(P.name))}</div>',
    '  ${heroCard(sp, P)}\n  <div class="phead" ${(sp==="VAL"||sp==="CS2")&&P.profile?"hidden":""}>${avatar(sp, P, "big")}')
rep('<span class="av" style="width:30px;height:30px;font-size:12px">${esc(initials(x.name))}</span>',
    '${avatar(x.sp, {id:x.id, name:x.name}).replace(\'class="av \', \'style="width:30px;height:30px;font-size:12px" class="av \')}')
rep("\nrender();\n</script>",
    "\nrender();\nfetch(\"img.json\").then(r => r.ok ? r.json() : null).then(j => { if(j){ IMG = j; render(); } }).catch(() => {});\n</script>")

js = open("site/desk_why.js", encoding="utf-8").read()
rep("\nfunction verdictCard(", "\n" + js + "\nfunction verdictCard(")

rep('''    <p class="vsent">${sentence(sp, P, sk, V)}</p>
    <div class="pvbe">''',
    '''    ${whyHTML(why(sp, P, sk, V.side, V.line))}
    <div class="math"><h3 style="font-size:12px;color:var(--muted);margin-bottom:6px">The number</h3><p class="vsent" style="margin-top:0">${sentence(sp, P, sk, V)}</p></div>
    <div class="pvbe">''')
rep('''  if(!V.r) return `<div class="verdict"><div class="card-h" style="margin-bottom:6px"><h3>Our read</h3><span class="pill p-soft">No read yet</span></div><div class="vbig" style="color:var(--muted)">Research only</div><p class="vsent">${esc((P.lines[sk]||{}).read_note || "Not enough games on file to read this line.")}</p></div>`;''',
    '''  if(!V.r){ const G0 = gamesFor(P, statDefs(sp,P)[sk][2]), c0 = G0.filter(g => g.cur), a0 = avg(c0.length >= 3 ? c0 : G0), sd0 = a0 != null && a0 > V.line ? "over" : "under";
    return `<div class="verdict"><div class="card-h" style="margin-bottom:6px"><h3>Our read</h3><span class="pill p-soft">No read yet</span></div><div class="vbig" style="color:var(--muted)">Research only</div>
    <p class="vsent">${esc((P.lines[sk]||{}).read_note || "Not enough games on file to read this line.")}</p>${whyHTML(why(sp, P, sk, sd0, V.line), "Points toward the " + sd0)}</div>`; }''')
open(p, "w", encoding="utf-8").write(s)
print("patched")
