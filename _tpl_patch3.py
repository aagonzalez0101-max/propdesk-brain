"""one-off (2026-10-02): v4 views -- card, slip builder, track record, glitch watch, NPB -- plus + buttons and a toast."""
p = "site/desk_template.html"
s = open(p, encoding="utf-8").read()
if "function slipPage" in s:
    raise SystemExit("already patched")


def rep(a, b):
    global s
    assert a in s, a[:90]
    s = s.replace(a, b, 1)


css = """
#views{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none;width:100%;border-top:1px solid var(--line);padding-top:8px}
#views button{background:none;border:1px solid transparent;border-radius:999px;padding:6px 14px;font-weight:600;font-size:13px;color:var(--muted);cursor:pointer;white-space:nowrap}
#views button:hover{color:var(--ink);background:var(--panel)}
#views button[aria-pressed="true"]{color:#fff;background:linear-gradient(135deg,var(--accent),#7B5CFF)}
.add{display:inline-grid;place-items:center;width:28px;height:28px;border-radius:8px;border:1px solid var(--line-2);background:var(--panel-2);color:var(--accent-2);font-weight:800;cursor:pointer;flex:none}
.add:hover{background:var(--accent);color:#fff}
.add.on{background:var(--accent);color:#fff;border-color:var(--accent)}
#toast{position:fixed;left:50%;bottom:calc(24px + env(safe-area-inset-bottom,0px));transform:translate(-50%,20px);opacity:0;background:var(--raise);border:1px solid var(--line-2);color:var(--ink);padding:10px 16px;border-radius:12px;font-weight:600;font-size:13px;transition:all .2s;z-index:50;pointer-events:none;box-shadow:0 12px 30px rgba(0,0,0,.4)}
#toast.show{opacity:1;transform:translate(-50%,0)}
@media (prefers-reduced-motion:reduce){#toast{transition:none}}
.row{transition:border-color .15s,background .15s,transform .15s}
.row:hover{transform:translateY(-1px)}
"""
s = s.replace("</style>", css + "</style>", 1)
rep('''    <div class="search">''', '''    <nav id="views" aria-label="Pages"></nav>
    <div class="search">''')
s = s.replace('#views{display:flex', '#views{order:9;display:flex', 1)
js = open("site/desk_v4.js", encoding="utf-8").read()
rep("\nfunction verdictCard(", "\n" + js + "\nfunction verdictCard(")
rep('function render(){ navSports(); if(state.view === "player" && state.player) playerPage(); else if(state.view === "team" && state.team) teamPage(); else board(); }',
    'function render(){ navSports(); navViews(); const V = {card:cardPage, slip:slipPage, record:recordPage, glitch:glitchPage, npb:npbPage}[state.view];\n'
    '  if(V) V(); else if(state.view === "player" && state.player) playerPage(); else if(state.view === "team" && state.team) teamPage(); else board(); }')
# + button on every board row (rows are <button>s, so the + is a span handled in the row click)
rep('''      <div><span class="pill ${r.V.cls}">${esc(r.V.label)}</span>''',
    '''      <div style="display:flex;gap:8px;align-items:center"><span class="add ${SLIP.some(x=>legKey(x)===r.sp+"|"+r.P.id+"|"+r.sk)?"on":""}" data-add="${ROWS.indexOf(r)}" title="Add to my slip">+</span><div><span class="pill ${r.V.cls}">${esc(r.V.label)}</span>''')
rep('''<div class="sub" style="margin-top:4px">${r.V.best ? pct(r.V.best.p)+" vs "+pct(r.V.best.be) : ""}</div></div>''',
    '''<div class="sub" style="margin-top:4px">${r.V.best ? pct(r.V.best.p)+" vs "+pct(r.V.best.be) : ""}</div></div></div>''')
rep('''  $("#view").querySelectorAll(".row[data-i]").forEach(b => b.onclick = () => { const r = ROWS[+b.dataset.i]; openPlayer(r.sp, r.P.id, r.sk); });''',
    '''  $("#view").querySelectorAll(".row[data-i]").forEach(b => b.onclick = e => { const a = e.target.closest("[data-add]"); const r = ROWS[+b.dataset.i];
    if(a){ e.stopPropagation(); addLeg(r.sp, r.P.id, r.sk); a.classList.toggle("on"); return; } openPlayer(r.sp, r.P.id, r.sk); });''')
# + on the player page verdict card
rep('''    <div class="card-h" style="margin-bottom:6px"><h3>Our read</h3><span class="pill p-soft">${DB[sp].paper''',
    '''    <div class="card-h" style="margin-bottom:6px"><h3>Our read <span class="add ${SLIP.some(x=>legKey(x)===sp+"|"+P.id+"|"+sk)?"on":""}" id="addleg" title="Add to my slip" style="margin-left:6px;vertical-align:middle">+</span></h3><span class="pill p-soft">${DB[sp].paper''')
rep('''  $("#back").onclick = () => go({view:"board"});
  $("#view").querySelectorAll(".tlink")''', '''  $("#back").onclick = () => go({view:"board"});
  const al = document.getElementById("addleg"); if(al) al.onclick = () => { addLeg(sp, P.id, sk); al.classList.toggle("on"); };
  $("#view").querySelectorAll(".tlink")''')
open(p, "w", encoding="utf-8").write(s)
print("patched")
