"""Option chain page — calls/puts tables + IV smile."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from utils import get_lang, has_error, i18n, page_setup, run_script_cached, show_error


page_setup()
lang = get_lang()
st.title(f"📈 {i18n('option_chain', lang)}")

with st.form("chain_form"):
    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    symbol = c1.text_input(i18n("symbol", lang), value="SPY").strip().upper()
    strikes = c2.slider(i18n("strikes", lang), 4, 30, 10)
    dte_min = c3.slider(i18n("dte_min", lang), 0, 60, 7)
    dte_max = c4.slider(i18n("dte_max", lang), 1, 365, 60)
    max_exp = st.slider(i18n("max_expirations", lang), 1, 8, 3)
    submitted = st.form_submit_button(i18n("submit", lang))

if not submitted and not symbol:
    st.stop()

args = (
    symbol,
    "--strikes",
    str(strikes),
    "--dte-min",
    str(dte_min),
    "--dte-max",
    str(dte_max),
    "--max-expirations",
    str(max_exp),
)
payload = run_script_cached("options_chain", args, timeout=120)
if has_error(payload):
    show_error(payload)
    st.stop()

# The chain may be {expirations: [...]} or {calls: [...], puts: [...]} — handle both.
calls_all: list[dict] = []
puts_all: list[dict] = []
for exp in payload.get("expirations") or []:
    calls_all.extend(exp.get("calls") or [])
    puts_all.extend(exp.get("puts") or [])
if not calls_all and not puts_all:
    calls_all = payload.get("calls") or []
    puts_all = payload.get("puts") or []

col_c, col_p = st.columns(2)
with col_c:
    st.subheader(i18n("calls", lang))
    if calls_all:
        st.dataframe(pd.DataFrame(calls_all), use_container_width=True, hide_index=True)
    else:
        st.info(i18n("no_data", lang))
with col_p:
    st.subheader(i18n("puts", lang))
    if puts_all:
        st.dataframe(pd.DataFrame(puts_all), use_container_width=True, hide_index=True)
    else:
        st.info(i18n("no_data", lang))

# IV smile
st.subheader(i18n("iv_smile", lang))
smile_rows = []
for row in calls_all:
    if row.get("iv") is not None and row.get("strike") is not None:
        smile_rows.append({"strike": row["strike"], "iv": row["iv"], "right": "C", "expiry": row.get("expiry")})
for row in puts_all:
    if row.get("iv") is not None and row.get("strike") is not None:
        smile_rows.append({"strike": row["strike"], "iv": row["iv"], "right": "P", "expiry": row.get("expiry")})
if smile_rows:
    df = pd.DataFrame(smile_rows)
    fig = px.scatter(df, x="strike", y="iv", color="right", symbol="expiry" if "expiry" in df else None)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info(i18n("no_data", lang))
