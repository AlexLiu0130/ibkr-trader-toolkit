"""Positions page — holdings overview, Greeks pie, net Greeks summary."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from utils import get_lang, has_error, i18n, page_setup, run_script_cached, show_error


page_setup()
lang = get_lang()
st.title(f"📊 {i18n('positions', lang)}")

payload = run_script_cached("portfolio_positions", (), timeout=90)
if has_error(payload):
    show_error(payload)
    st.stop()

positions = payload.get("positions") or []
portfolio_greeks = payload.get("portfolio_greeks") or {}

# Net Greeks summary
st.subheader(i18n("net_greeks", lang))
gcols = st.columns(5)
for col, name in zip(gcols, ["delta", "gamma", "theta", "vega", "rho"]):
    val = portfolio_greeks.get(name, 0.0) or 0.0
    col.metric(name.capitalize(), f"{val:,.2f}")

st.divider()

if not positions:
    st.info(i18n("no_data", lang))
    st.stop()

df = pd.DataFrame(positions)
st.dataframe(df, use_container_width=True, hide_index=True)

# Greeks pie by symbol (|delta| as size proxy)
st.subheader(i18n("greeks_by_symbol", lang))
if "symbol" in df.columns and "delta" in df.columns:
    agg = df.assign(abs_delta=df["delta"].abs()).groupby("symbol", as_index=False)["abs_delta"].sum()
    fig = px.pie(agg, names="symbol", values="abs_delta", hole=0.4)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info(i18n("no_data", lang))
