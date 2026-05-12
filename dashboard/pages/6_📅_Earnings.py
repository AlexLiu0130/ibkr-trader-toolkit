"""Earnings calendar page."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from utils import get_lang, has_error, i18n, page_setup, run_script_cached, show_error


page_setup()
lang = get_lang()
st.title(f"📅 {i18n('earnings', lang)}")

# Pull portfolio symbols
portfolio = run_script_cached("portfolio_positions", (), timeout=90)
if has_error(portfolio):
    show_error(portfolio)
    st.stop()

positions = portfolio.get("positions") or []
symbols = sorted({(p.get("symbol") or "").upper() for p in positions if p.get("symbol")})
extra = st.text_input(i18n("extra_symbols", lang), value="")
for s in extra.split():
    s = s.strip().upper()
    if s and s not in symbols:
        symbols.append(s)

if not symbols:
    st.info(i18n("no_data", lang))
    st.stop()

args = (*symbols, "--days", "30")
payload = run_script_cached("earnings_calendar", args, timeout=120)
if has_error(payload):
    show_error(payload)
    st.stop()

events = payload.get("events") or payload.get("earnings") or []
if not events:
    st.info(i18n("no_data", lang))
    st.stop()

today = datetime.now().date()


def _color(days_until: int) -> str:
    if days_until <= 7:
        return "#e74c3c"
    if days_until <= 14:
        return "#f1c40f"
    return "#2ecc71"


rows = []
for e in events:
    date_str = e.get("date") or e.get("earnings_date")
    if not date_str:
        continue
    try:
        d = datetime.fromisoformat(str(date_str)[:10]).date()
    except ValueError:
        continue
    days_until = (d - today).days
    rows.append(
        {
            "symbol": e.get("symbol"),
            "date": d,
            "days_until": days_until,
            "color": _color(days_until),
            "time": e.get("time", ""),
        }
    )

if not rows:
    st.info(i18n("no_data", lang))
    st.stop()

df = pd.DataFrame(rows).sort_values("date")
st.subheader(i18n("timeline", lang))

# Gantt-style: each event is a 1-day bar
df["end"] = df["date"] + timedelta(days=1)
fig = px.timeline(
    df,
    x_start="date",
    x_end="end",
    y="symbol",
    color="color",
    color_discrete_map="identity",
    hover_data=["days_until", "time"],
)
fig.update_yaxes(autorange="reversed")
st.plotly_chart(fig, use_container_width=True)

st.dataframe(
    df[["symbol", "date", "days_until", "time"]],
    use_container_width=True,
    hide_index=True,
)
