"""one-off: team pages + team search + clickable team names (2026-09-30)"""
p = "site/desk_template.html"
s = open(p, encoding="utf-8").read()
if "function teamPage" in s:
    raise SystemExit("already patched")


def rep(a, b):
    global s
    assert a in s, a[:90]
    s = s.replace(a, b, 1)


js = open("site/desk_team.js", encoding="utf-8").read()
rep("\nfunction verdictCard(", "\n" + js + "\nfunction verdictCard(")
rep('function render(){ navSports(); if(state.view === "player" && state.player) playerPage(); else board(); }',
    'function render(){ navSports(); if(state.view === "player" && state.player) playerPage(); else if(state.view === "team" && state.team) teamPage(); else board(); }')
# search: teams too
rep('const INDEX = SPORTS.flatMap(sp => Object.values(DB[sp].players).map(P => ({sp, id:P.id, name:P.name, team:P.team_name||P.team, key:P.name.toLowerCase()})));',
    'const INDEX = SPORTS.flatMap(sp => Object.values(DB[sp].players).map(P => ({sp, id:P.id, name:P.name, team:P.team_name||P.team, key:P.name.toLowerCase()})))\n'
    '  .concat(SPORTS.flatMap(sp => Object.values(DB[sp].teams||{}).map(T => ({sp, id:T.id, name:T.name, team:"Team page", key:(T.name + " " + T.id).toLowerCase(), isTeam:true}))));')
rep('box.onclick = ev => { const b = ev.target.closest("button"); if(b){ const x = hits[+b.dataset.i]; box.hidden = true; $("#q").value = ""; openPlayer(x.sp, x.id); } };',
    'box.onclick = ev => { const b = ev.target.closest("button"); if(b){ const x = hits[+b.dataset.i]; box.hidden = true; $("#q").value = ""; x.isTeam ? openTeam(x.sp, x.id) : openPlayer(x.sp, x.id); } };')
rep('if(e.key === "Enter" && n){ const x = box._hits[hi]; box.hidden = true; e.target.value = ""; openPlayer(x.sp, x.id); }',
    'if(e.key === "Enter" && n){ const x = box._hits[hi]; box.hidden = true; e.target.value = ""; x.isTeam ? openTeam(x.sp, x.id) : openPlayer(x.sp, x.id); }')
rep('$("#q").placeholder', '$("#q").placeholder') if '$("#q").placeholder' in s else None
s = s.replace('placeholder="Search a player…"', 'placeholder="Search a player or team…"', 1)
# clickable team / opponent on the player page
rep('''<span class="tbadge">${esc(sp==="SOCCER"?"SOC":sp)}</span> ${esc(P.team_name||P.team)} · ''',
    '''<span class="tbadge">${esc(sp==="SOCCER"?"SOC":sp)}</span> <a href="#" class="tlink" data-t="${esc(P.team)}">${esc(P.team_name||P.team)}</a> · ''')
rep('''${P.opp ? ` · vs <b style="color:var(--ink)">${esc(P.opp_name||P.opp)}</b>` : " · opponent not matched"}''',
    '''${P.opp ? ` · vs <a href="#" class="tlink" data-t="${esc(P.opp)}"><b>${esc(P.opp_name||P.opp)}</b></a>` : " · opponent not matched"}''')
rep('''  $("#back").onclick = () => go({view:"board"});
  $("#tabs").onclick''', '''  $("#back").onclick = () => go({view:"board"});
  $("#view").querySelectorAll(".tlink").forEach(a => a.onclick = e => { e.preventDefault(); if((DB[sp].teams||{})[a.dataset.t]) openTeam(sp, a.dataset.t); });
  $("#tabs").onclick''')
s = s.replace("</style>", ".tlink{color:var(--accent-2);text-decoration:none;border-bottom:1px dashed var(--line-2)} .tlink:hover{color:var(--ink)}\n</style>", 1)
open(p, "w", encoding="utf-8").write(s)
print("patched")
