"""P&L analytics page."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils import get_lang, has_error, i18n, page_setup, run_script_cached, show_error


page_setup()
lang = get_lang()
st.title(f"💰 {i18n('pnl_analytics', lang)}")

c1, c2 = st.columns(2)
days = c1.slider(i18n("days", lang), 7, 365, 30)
by = c2.selectbox(i18n("filter_by", lang), options=["symbol", "right", "expiration"])

args = ("--days", str(days), "--by", by)
payload = run_script_cached("pnl_analytics", args, timeout=120)
if has_error(payload):
    show_error(payload)
    st.stop()

trades = payload.get("trades") or payload.get("realized") or []
stats = payload.get("stats") or {}

# Win rate gauge
win_rate = stats.get("win_rate")
if win_rate is None and trades:
    wins = sum(1 for t in trades if (t.get("pnl") or 0) > 0)
    win_rate = wins / len(trades) if trades else 0
win_rate = float(win_rate or 0) * (100 if win_rate and win_rate <= 1 else 1)

gauge = go.Figure(
    go.Indicator(
        mode="gauge+number",
        value=win_rate,
        number={"suffix": "%"},
        title={"text": i18n("win_rate", lang)},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": "#2ecc71" if win_rate >= 50 else "#e74c3c"},
            "steps": [
                {"range": [0, 50], "color": "#fde0dc"},
                {"range": [50, 100], "color": "#d4edda"},
            ],
        },
    )
)
st.plotly_chart(gauge, use_container_width=True)

# Distribution
st.subheader(i18n("pnl_distribution", lang))
if trades:
    df = pd.DataFrame(trades)
    if "pnl" in df.columns:
        fig = px.histogram(df, x="pnl", nbins=30, color_discrete_sequence=["#3498db"])
        fig.add_vline(x=0, line_dash="dash", line_color="gray")
        st.plotly_chart(fig, use_container_width=True)

    # Best / worst
    st.subheader(i18n("best_worst", lang))
    if "pnl" in df.columns:
        bcol, wcol = st.columns(2)
        bcol.dataframe(df.nlargest(5, "pnl"), use_container_width=True, hide_index=True)
        wcol.dataframe(df.nsmallest(5, "pnl"), use_container_width=True, hide_index=True)
else:
    st.info(i18n("no_data", lang))
