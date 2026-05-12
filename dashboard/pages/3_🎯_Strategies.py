"""Strategy recommendations page."""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from utils import get_lang, has_error, i18n, page_setup, run_script_cached, show_error


page_setup()
lang = get_lang()
st.title(f"🎯 {i18n('strategies', lang)}")

with st.form("strategy_form"):
    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    symbol = c1.text_input(i18n("symbol", lang), value="SPY").strip().upper()
    outlook = c2.selectbox(
        i18n("outlook", lang),
        options=["bullish", "bearish", "neutral", "volatile"],
    )
    risk = c3.selectbox(
        i18n("risk_profile", lang),
        options=["conservative", "moderate", "aggressive"],
        index=1,
    )
    iv_ctx = c4.checkbox(i18n("use_iv_context", lang), value=True)
    submitted = st.form_submit_button(i18n("submit", lang))

if not submitted:
    st.stop()

args = [symbol, "--outlook", outlook, "--risk-profile", risk]
if iv_ctx:
    args.append("--iv-context")

payload = run_script_cached("options_analyzer", tuple(args), timeout=120)
if has_error(payload):
    show_error(payload)
    st.stop()

recs = payload.get("recommendations") or payload.get("strategies") or []
if not recs:
    st.info(i18n("no_recommendations", lang))
    st.stop()

# Cards
for i, rec in enumerate(recs):
    with st.container(border=True):
        name = rec.get("strategy") or rec.get("name") or f"#{i+1}"
        st.subheader(name)
        legs = rec.get("legs") or []
        if legs:
            st.markdown(f"**{i18n('legs', lang)}:**")
            st.table(legs)
        mcols = st.columns(4)
        mcols[0].metric(i18n("max_profit", lang), f"{rec.get('max_profit', 'N/A')}")
        mcols[1].metric(i18n("max_loss", lang), f"{rec.get('max_loss', 'N/A')}")
        be = rec.get("breakeven")
        mcols[2].metric(
            i18n("breakeven", lang),
            f"{be}" if not isinstance(be, list) else ", ".join(str(b) for b in be),
        )
        prob = rec.get("probability")
        mcols[3].metric(i18n("probability", lang), f"{prob}" if prob is not None else "N/A")

# P&L diagram for top rec
st.subheader(i18n("max_profit", lang) + " / " + i18n("max_loss", lang))
top = recs[0]
mp = top.get("max_profit")
ml = top.get("max_loss")
be = top.get("breakeven")
if isinstance(be, (int, float)) and isinstance(mp, (int, float)) and isinstance(ml, (int, float)):
    center = float(be)
    xs = np.linspace(center * 0.85, center * 1.15, 50)
    # crude V-shape proxy if we don't have a real payoff function
    slope = max(abs(float(mp)), abs(float(ml))) / max(center * 0.1, 1.0)
    ys = []
    for x in xs:
        if x < center:
            ys.append(-float(ml) * (center - x) / max(center * 0.1, 1e-6))
        else:
            ys.append(float(mp) * (x - center) / max(center * 0.1, 1e-6))
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color="#1f77b4")))
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.add_vline(x=center, line_dash="dot", line_color="green")
    fig.update_layout(xaxis_title="Underlying", yaxis_title="P&L")
    st.plotly_chart(fig, use_container_width=True)
