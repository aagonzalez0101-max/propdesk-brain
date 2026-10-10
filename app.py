"""
Sports Betting AI — Main Dashboard
Run:  streamlit run app.py
"""
import time
import datetime
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from config import ODDS_API_KEY, TRACKED_SPORTS, SPORT_LABELS, REFRESH_INTERVAL
from data.db import (get_upcoming_games, get_recent_predictions,
                     get_sharp_alerts, get_odds_history, get_best_odds,
                     get_latest_odds)
from collectors.odds_api import fetch_all_odds, generate_demo_odds
from engine.sharp_money import run_sharp_scan
from engine.models import get_predictions

# ─── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Sports Betting AI",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .main { background: #0e1117; }
  .metric-card {
      background: #1e2130; border-radius: 10px;
      padding: 16px; margin: 4px; text-align: center;
  }
  .pick-card {
      background: #1a1f2e; border-left: 4px solid #00d4ff;
      border-radius: 8px; padding: 14px; margin: 6px 0;
  }
  .sharp-high   { border-left-color: #ff4b4b !important; }
  .sharp-medium { border-left-color: #ffa500 !important; }
  .sharp-low    { border-left-color: #00d4ff !important; }
  .tag {
      display: inline-block; padding: 2px 8px;
      border-radius: 4px; font-size: 0.75em; font-weight: bold;
  }
  .tag-nfl  { background: #003f7f; color: white; }
  .tag-nba  { background: #c9082a; color: white; }
  .tag-mlb  { background: #002d62; color: white; }
  .tag-nhl  { background: #111; color: #c8a900; }
  .stMetric label { color: #aaa; font-size: 0.8em; }
</style>
""", unsafe_allow_html=True)


# ─── Session state ────────────────────────────────────────────────────────────
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh   = 0
if "predictions"  not in st.session_state:
    st.session_state.predictions    = []
if "sharp_alerts" not in st.session_state:
    st.session_state.sharp_alerts   = []
if "games"        not in st.session_state:
    st.session_state.games          = []


def refresh_data(force=False):
    now = time.time()
    if force or (now - st.session_state.last_refresh) > REFRESH_INTERVAL:
        with st.spinner("Fetching latest odds and running models..."):
            if ODDS_API_KEY:
                fetch_all_odds()
            else:
                generate_demo_odds()

            games = get_upcoming_games(limit=60)
            st.session_state.games        = games
            st.session_state.predictions  = get_predictions(games)
            st.session_state.sharp_alerts = run_sharp_scan(games)
            st.session_state.last_refresh = now
        st.success(f"Refreshed {len(games)} games at "
                   f"{datetime.datetime.now().strftime('%H:%M:%S')}")


# ─── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://img.icons8.com/color/96/dart.png", width=60)
    st.title("Sports Betting AI")

    if not ODDS_API_KEY:
        st.warning(
            "Running in **Demo Mode**.\n\n"
            "Add your free API key from [the-odds-api.com](https://the-odds-api.com/) "
            "to `config.py` → `ODDS_API_KEY` for live odds."
        )
    else:
        st.success("Live odds connected")

    st.divider()
    page = st.radio(
        "Navigate",
        ["Live Odds", "AI Picks", "Sharp Money", "Line Movement", "Performance"],
        index=0,
    )

    st.divider()
    sport_filter = st.multiselect(
        "Sports",
        options=list(SPORT_LABELS.keys()),
        default=list(SPORT_LABELS.keys()),
        format_func=lambda k: SPORT_LABELS[k],
    )

    min_confidence = st.slider("Min Confidence %", 50, 95, 60, step=5)
    show_value_only = st.checkbox("Show value picks only (edge > 0)", value=False)

    st.divider()
    if st.button("Refresh Data", type="primary"):
        refresh_data(force=True)

    last_upd = st.session_state.last_refresh
    if last_upd:
        st.caption(f"Last update: {datetime.datetime.fromtimestamp(last_upd).strftime('%H:%M:%S')}")

# ─── Initial load ─────────────────────────────────────────────────────────────
if not st.session_state.last_refresh:
    refresh_data(force=True)

preds   = st.session_state.predictions
alerts  = st.session_state.sharp_alerts
games   = st.session_state.games

# Filter by sport
preds  = [p for p in preds  if p["sport"] in sport_filter]
alerts = [a for a in alerts if a.get("sport", a.get("home_team", "")) in
          [g["sport"] for g in games if g["game_id"] == a.get("game_id")]]
games  = [g for g in games if g["sport"] in sport_filter]


# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE: LIVE ODDS
# ═══════════════════════════════════════════════════════════════════════════════
if page == "Live Odds":
    st.header("Live Odds Board")

    cols = st.columns(4)
    cols[0].metric("Games Today",    len(games))
    cols[1].metric("Active Books",   "5+")
    cols[2].metric("Sharp Alerts",   len(st.session_state.sharp_alerts))
    cols[3].metric("AI Picks",       len([p for p in preds if p["confidence"] >= min_confidence]))

    st.divider()

    if not games:
        st.info("No upcoming games found. Click Refresh Data.")
    else:
        rows = []
        for g in games:
            gid    = g["game_id"]
            sport  = SPORT_LABELS.get(g["sport"], g["sport"])
            gametime = datetime.datetime.fromtimestamp(g["commence_ts"]).strftime("%m/%d %H:%M")

            best_h2h  = get_best_odds(gid, "h2h")
            best_spd  = get_best_odds(gid, "spreads")
            best_tot  = get_best_odds(gid, "totals")

            def _fmt_ml(v):
                if v is None: return "N/A"
                return f"+{int(v)}" if v >= 0 else str(int(v))

            home_ml = away_ml = spread = total = "—"
            if best_h2h:
                home_ml = _fmt_ml(best_h2h["best_home"].get("home_price"))
                away_ml = _fmt_ml(best_h2h["best_away"].get("away_price"))
            if best_spd and best_spd["best_home"].get("home_point") is not None:
                spv = best_spd["best_home"]["home_point"]
                spread = f"{'+' if spv > 0 else ''}{spv}"
            if best_tot and best_tot["best_home"].get("home_point") is not None:
                total = f"O/U {best_tot['best_home']['home_point']}"

            # Sharp flag
            has_sharp = any(a.get("game_id") == gid for a in st.session_state.sharp_alerts)

            rows.append({
                "Sport":     sport,
                "Game Time": gametime,
                "Home":      g["home_team"],
                "Away":      g["away_team"],
                "Home ML":   home_ml,
                "Away ML":   away_ml,
                "Spread":    spread,
                "Total":     total,
                "Sharp":     "SHARP" if has_sharp else "",
            })

        df = pd.DataFrame(rows)

        def highlight_sharp(row):
            if row["Sharp"] == "SHARP":
                return ["background-color: #2a1a1a"] * len(row)
            return [""] * len(row)

        st.dataframe(
            df.style.apply(highlight_sharp, axis=1),
            use_container_width=True,
            hide_index=True,
            height=min(800, 60 + len(rows) * 35),
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE: AI PICKS
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "AI Picks":
    st.header("AI Picks — Ensemble Model")

    filtered = [p for p in preds if p["confidence"] >= min_confidence]
    if show_value_only:
        filtered = [p for p in filtered if p["value_edge"] > 0]

    top = filtered[:3]
    c1, c2, c3 = st.columns(3)
    for col, pick in zip([c1, c2, c3], top + [{}] * (3 - len(top))):
        if not pick:
            col.empty()
            continue
        with col:
            sport = SPORT_LABELS.get(pick["sport"], pick["sport"])
            gametime = datetime.datetime.fromtimestamp(pick["commence_ts"]).strftime("%m/%d %H:%M")
            col.markdown(f"""
<div class="metric-card">
  <div style="color:#aaa;font-size:.8em">{sport} · {gametime}</div>
  <div style="font-size:1.3em;font-weight:bold;color:#00d4ff">{pick['pick_team']}</div>
  <div style="color:#aaa">{pick['home_team']} vs {pick['away_team']}</div>
  <div style="font-size:1.1em;margin-top:6px">Confidence: <b>{pick['confidence']:.0f}%</b></div>
  <div style="color:{'#00d4ff' if pick['value_edge']>0 else '#ff6b6b'}">
      Edge: {'+' if pick['value_edge']>0 else ''}{pick['value_edge']:.1f}%
  </div>
</div>
""", unsafe_allow_html=True)

    st.divider()
    st.subheader(f"All Picks ({len(filtered)} total)")

    if not filtered:
        st.info("No picks meet the current confidence threshold.")
    else:
        for p in filtered:
            sport    = SPORT_LABELS.get(p["sport"], p["sport"])
            gametime = datetime.datetime.fromtimestamp(p["commence_ts"]).strftime("%m/%d %H:%M")
            agree_icon = "MODELS AGREE" if p["models_agree"] else "Split Signal"
            sharp_dir  = ""
            if p["sharp_signal"] > 0.2:
                sharp_dir = "SHARP HOME"
            elif p["sharp_signal"] < -0.2:
                sharp_dir = "SHARP AWAY"

            ml_display = ""
            if p["pick_side"] == "home":
                v = p.get("curr_home_ml", -110)
                ml_display = f"+{int(v)}" if v > 0 else str(int(v))
            else:
                v = p.get("curr_away_ml", -110)
                ml_display = f"+{int(v)}" if v > 0 else str(int(v))

            st.markdown(f"""
<div class="pick-card">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <div>
      <span style="font-size:.75em;color:#888">{sport} · {gametime}</span><br>
      <b style="font-size:1.1em">{p['home_team']} vs {p['away_team']}</b>
    </div>
    <div style="text-align:right">
      <div style="font-size:1.3em;font-weight:bold;color:#00d4ff">{p['pick_team']}</div>
      <div style="color:#aaa;font-size:.9em">ML {ml_display}</div>
    </div>
  </div>
  <hr style="margin:8px 0;border-color:#333">
  <div style="display:flex;gap:16px;flex-wrap:wrap">
    <span>Conf: <b>{p['confidence']:.0f}%</b></span>
    <span style="color:{'#00d4ff' if p['value_edge']>0 else '#ff6b6b'}">Edge: {'+' if p['value_edge']>0 else ''}{p['value_edge']:.1f}%</span>
    <span>Spread: {p['curr_spread']:+.1f}</span>
    <span>O/U: {p['curr_total']:.1f}</span>
    <span style="color:#ffa500">{agree_icon}</span>
    {f'<span style="color:#ff4b4b">{sharp_dir}</span>' if sharp_dir else ''}
  </div>
</div>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE: SHARP MONEY
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "Sharp Money":
    st.header("Sharp Money Tracker")
    st.caption(
        "Detects professional betting patterns: reverse line movement, "
        "steam moves, line freezes, late moves, and bet/money discrepancies."
    )

    all_alerts = get_sharp_alerts(limit=100)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Alerts", len(all_alerts))
    c2.metric("High Severity",   sum(1 for a in all_alerts if a.get("severity") == "high"))
    c3.metric("Medium Severity", sum(1 for a in all_alerts if a.get("severity") == "medium"))
    c4.metric("Low Severity",    sum(1 for a in all_alerts if a.get("severity") == "low"))

    # Alert type breakdown
    if all_alerts:
        type_counts = {}
        for a in all_alerts:
            t = a.get("alert_type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

        fig = px.bar(
            x=list(type_counts.keys()),
            y=list(type_counts.values()),
            color=list(type_counts.values()),
            color_continuous_scale="Reds",
            labels={"x": "Alert Type", "y": "Count"},
            title="Sharp Alert Breakdown",
        )
        fig.update_layout(
            paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
            font_color="white", height=300,
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    sev_filter = st.multiselect(
        "Severity filter", ["high", "medium", "low"],
        default=["high", "medium"],
    )

    shown = [a for a in all_alerts if a.get("severity") in sev_filter]

    if not shown:
        st.info("No sharp alerts detected yet. Data will accumulate as odds are refreshed.")
    else:
        for a in shown:
            sev_class = f"sharp-{a.get('severity','low')}"
            ts = datetime.datetime.fromtimestamp(a.get("created_ts", 0)).strftime("%m/%d %H:%M")
            atype = a.get("alert_type", "").replace("_", " ").title()
            st.markdown(f"""
<div class="pick-card {sev_class}">
  <div style="display:flex;justify-content:space-between">
    <div>
      <b style="color:#fff">{a.get('home_team','?')} vs {a.get('away_team','?')}</b>
      <span style="color:#aaa;font-size:.8em"> · {ts}</span>
    </div>
    <span style="color:{'#ff4b4b' if a['severity']=='high' else '#ffa500'};font-weight:bold">
      {atype} [{a.get('severity','').upper()}]
    </span>
  </div>
  <div style="color:#ccc;margin-top:6px;font-size:.9em">{a.get('details','')}</div>
</div>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE: LINE MOVEMENT
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "Line Movement":
    st.header("Line Movement Charts")

    if not games:
        st.info("No games loaded. Click Refresh Data.")
    else:
        game_options = {
            f"{SPORT_LABELS.get(g['sport'],g['sport'])} | "
            f"{g['home_team']} vs {g['away_team']} "
            f"({datetime.datetime.fromtimestamp(g['commence_ts']).strftime('%m/%d %H:%M')})": g
            for g in games
        }
        selected_label = st.selectbox("Select game", list(game_options.keys()))
        selected_game  = game_options[selected_label]
        gid = selected_game["game_id"]

        mkt_tab = st.tabs(["Moneyline", "Spread", "Total"])

        for mkt, tab in zip(["h2h", "spreads", "totals"], mkt_tab):
            with tab:
                history = get_odds_history(gid, mkt)
                if not history:
                    st.info("No history yet for this market.")
                    continue

                df = pd.DataFrame(history)
                df["time"] = pd.to_datetime(df["snapshot_ts"], unit="s")
                books = df["bookmaker"].unique()

                if mkt == "h2h":
                    fig = go.Figure()
                    for bk in books:
                        sub = df[df["bookmaker"] == bk]
                        fig.add_trace(go.Scatter(
                            x=sub["time"], y=sub["home_price"],
                            mode="lines+markers", name=f"{bk} Home ML", line=dict(width=2),
                        ))
                    fig.update_layout(
                        title=f"Moneyline — {selected_game['home_team']}",
                        yaxis_title="American Odds",
                        paper_bgcolor="#0e1117", plot_bgcolor="#1e2130",
                        font_color="white", height=400,
                        legend=dict(bgcolor="#1e2130"),
                    )
                    st.plotly_chart(fig, use_container_width=True)

                elif mkt == "spreads":
                    fig = go.Figure()
                    for bk in books:
                        sub = df[df["bookmaker"] == bk]
                        fig.add_trace(go.Scatter(
                            x=sub["time"], y=sub["home_point"],
                            mode="lines+markers", name=f"{bk} Home Spread", line=dict(width=2),
                        ))
                    fig.add_hline(
                        y=df["home_point"].iloc[0] if len(df) else 0,
                        line_dash="dash", line_color="gray",
                        annotation_text="Opening line",
                    )
                    fig.update_layout(
                        title=f"Spread Movement — {selected_game['home_team']}",
                        yaxis_title="Points",
                        paper_bgcolor="#0e1117", plot_bgcolor="#1e2130",
                        font_color="white", height=400,
                    )
                    st.plotly_chart(fig, use_container_width=True)

                else:  # totals
                    fig = go.Figure()
                    for bk in books:
                        sub = df[df["bookmaker"] == bk]
                        fig.add_trace(go.Scatter(
                            x=sub["time"], y=sub["home_point"],
                            mode="lines+markers", name=f"{bk} Total", line=dict(width=2),
                        ))
                    fig.update_layout(
                        title="Total (O/U) Movement",
                        yaxis_title="Points",
                        paper_bgcolor="#0e1117", plot_bgcolor="#1e2130",
                        font_color="white", height=400,
                    )
                    st.plotly_chart(fig, use_container_width=True)

                # Raw data table
                with st.expander("Raw snapshot data"):
                    st.dataframe(df.drop(columns=["snapshot_ts"]), use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE: PERFORMANCE
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "Performance":
    st.header("Model Performance & Tracking")

    all_preds = get_recent_predictions(200)

    total    = len(all_preds)
    wins     = sum(1 for p in all_preds if p.get("result") == "win")
    losses   = sum(1 for p in all_preds if p.get("result") == "loss")
    pending  = sum(1 for p in all_preds if p.get("result") == "pending")
    roi      = ((wins - losses * 1.1) / max(total - pending, 1)) * 100 if total else 0
    win_rate = (wins / max(wins + losses, 1)) * 100

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Picks", total)
    c2.metric("Wins",        wins,    delta=f"+{wins}")
    c3.metric("Losses",      losses,  delta=f"-{losses}", delta_color="inverse")
    c4.metric("Win Rate",    f"{win_rate:.1f}%")
    c5.metric("Est. ROI",    f"{roi:.1f}%",
              delta_color="normal" if roi >= 0 else "inverse")

    st.divider()

    if total:
        df = pd.DataFrame(all_preds)
        df["date"] = pd.to_datetime(df["commence_ts"], unit="s").dt.date

        # Confidence distribution
        fig = px.histogram(
            df, x="confidence", nbins=20,
            title="Confidence Distribution",
            color_discrete_sequence=["#00d4ff"],
        )
        fig.update_layout(paper_bgcolor="#0e1117", plot_bgcolor="#1e2130",
                           font_color="white", height=300)
        st.plotly_chart(fig, use_container_width=True)

        # Picks by sport
        sport_df = df.groupby("sport").size().reset_index(name="count")
        sport_df["sport"] = sport_df["sport"].map(SPORT_LABELS)
        fig2 = px.pie(sport_df, values="count", names="sport",
                      title="Picks by Sport", color_discrete_sequence=px.colors.qualitative.Set2)
        fig2.update_layout(paper_bgcolor="#0e1117", font_color="white", height=350)
        st.plotly_chart(fig2, use_container_width=True)

        # Recent picks table
        st.subheader("Recent Predictions")
        display_df = df[["sport", "home_team", "away_team", "pick_side",
                         "confidence", "value_edge", "result"]].copy()
        display_df["sport"] = display_df["sport"].map(SPORT_LABELS)
        display_df.columns = ["Sport", "Home", "Away", "Pick", "Conf%", "Edge%", "Result"]

        def color_result(val):
            if val == "win":   return "color: #00ff88"
            if val == "loss":  return "color: #ff4b4b"
            return "color: #aaa"

        st.dataframe(
            display_df.style.applymap(color_result, subset=["Result"]),
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("No predictions in the database yet. Generate some picks first.")

    # ── How to improve ──────────────────────────────────────────────────────
    with st.expander("How to improve model accuracy"):
        st.markdown("""
### Upgrading from demo to production

**1. Get a free API key** → [the-odds-api.com](https://the-odds-api.com/) (500 req/month free)
- Add it to `config.py` → `ODDS_API_KEY`

**2. Add public betting data**
- Sources: Action Network, BetQL, Covers
- Feeds into reverse-line-movement detection

**3. Replace synthetic training data** with real historical results
- Download from [sports-reference.com](https://www.sports-reference.com/) via `sportsipy`
- Match game IDs from odds history → actual outcomes → train models

**4. Add more features**
- Injury reports (ESPN API)
- Travel distance / rest days
- Weather (outdoor sports)
- Referee/umpire tendencies
- Home/away splits by venue

**5. Track Closing Line Value (CLV)**
- Record closing odds the moment the game starts
- Compare your bet price vs. closing price
- Consistent positive CLV = real edge
""")

# ─── Auto-refresh hint ────────────────────────────────────────────────────────
st.sidebar.divider()
st.sidebar.caption(
    f"Auto-refresh every {REFRESH_INTERVAL//60} min. "
    "Or click Refresh Data anytime."
)
