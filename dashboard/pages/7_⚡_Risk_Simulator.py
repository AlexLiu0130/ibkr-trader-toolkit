"""Risk simulator page — add proposed legs and compare Greeks."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils import get_lang, has_error, i18n, page_setup, run_script, run_script_cached, show_error


page_setup()
lang = get_lang()
st.title(f"⚡ {i18n('risk_simulator', lang)}")

if "sim_legs" not in st.session_state:
    st.session_state.sim_legs = []  # list[dict]

with st.form("leg_form", clear_on_submit=True):
    c1, c2, c3, c4, c5, c6 = st.columns([2, 1, 1, 1, 1, 1])
    sym = c1.text_input(i18n("symbol", lang), value="SPY").strip().upper()
    strike = c2.number_input(i18n("strike", lang), min_value=0.0, value=500.0, step=1.0)
    expiry = c3.text_input(i18n("expiry", lang), value="20260619")  # YYYYMMDD
    right = c4.selectbox(i18n("right", lang), options=["C", "P"])
    action = c5.selectbox(i18n("action", lang), options=["BUY", "SELL"])
    qty = c6.number_input(i18n("qty", lang), min_value=1, value=1, step=1)
    add = st.form_submit_button(i18n("add_leg", lang))
    if add and sym:
        st.session_state.sim_legs.append(
            {
                "symbol": sym,
                "strike": float(strike),
                "expiry": expiry,
                "right": right,
                "action": action,
                "qty": int(qty),
            }
        )

if st.session_state.sim_legs:
    st.dataframe(pd.DataFrame(st.session_state.sim_legs), use_container_width=True, hide_index=True)
    cc1, cc2 = st.columns([1, 1])
    if cc1.button(i18n("clear_legs", lang)):
        st.session_state.sim_legs = []
        st.rerun()
    simulate = cc2.button(i18n("simulate", lang), type="primary")
else:
    simulate = False
    st.info(i18n("no_data", lang))

if not simulate:
    st.stop()

# Build --add args for each leg
args: list[str] = []
for leg in st.session_state.sim_legs:
    spec = f"{leg['symbol']} {leg['strike']} {leg['expiry']} {leg['right']} {leg['action']} {leg['qty']}"
    args.extend(["--add", spec])

with st.spinner(i18n("loading", lang)):
    sim = run_script("risk_simulator", args, timeout=180)
if has_error(sim):
    show_error(sim)
    st.stop()

current = sim.get("current_greeks") or {}
simulated = sim.get("simulated_greeks") or {}
warnings = sim.get("warnings") or []

# Fall back to live portfolio if `current` missing
if not current:
    port = run_script_cached("portfolio_positions", (), timeout=90)
    if not has_error(port):
        current = port.get("portfolio_greeks") or {}

st.subheader(i18n("current_vs_simulated", lang))
greek_names = ["delta", "gamma", "theta", "vega", "rho"]
cur_vals = [float(current.get(g, 0) or 0) for g in greek_names]
sim_vals = [float(simulated.get(g, 0) or 0) for g in greek_names]
fig = go.Figure(
    data=[
        go.Bar(name="Current", x=greek_names, y=cur_vals, marker_color="#3498db"),
        go.Bar(name="Simulated", x=greek_names, y=sim_vals, marker_color="#e67e22"),
    ]
)
fig.update_layout(barmode="group")
st.plotly_chart(fig, use_container_width=True)

if warnings:
    st.subheader(i18n("warnings", lang))
    for w in warnings:
        st.warning(w if isinstance(w, str) else str(w))
