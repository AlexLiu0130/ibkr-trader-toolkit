"""IBKR Trader Toolkit — landing page."""
from __future__ import annotations

import streamlit as st

from utils import (
    get_lang,
    has_error,
    i18n,
    page_setup,
    run_script_cached,
    show_error,
)


page_setup()
lang = get_lang()

# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
header_left, header_right = st.columns([4, 1])
with header_left:
    st.title(f"📊 {i18n('app_title', lang)}")
with header_right:
    # Gateway connection probe: a single SPY quote, cached 60s.
    gateway_probe = run_script_cached("market_quote", ("SPY",), timeout=30)
    if has_error(gateway_probe):
        st.markdown(f":red[● {i18n('gateway_status', lang)}: {i18n('disconnected', lang)}]")
    else:
        st.markdown(f":green[● {i18n('gateway_status', lang)}: {i18n('connected', lang)}]")

st.divider()


# --------------------------------------------------------------------------- #
# KPI cards
# --------------------------------------------------------------------------- #
def _extract_kpis(payload: dict) -> dict:
    """Robustly pull the 4 KPI numbers from portfolio_positions output."""
    summary = payload.get("summary") or payload.get("portfolio") or {}
    positions = payload.get("positions") or []

    portfolio_value = (
        summary.get("portfolio_value")
        or summary.get("net_liquidation")
        or payload.get("portfolio_value")
        or 0.0
    )
    unrealized = (
        summary.get("unrealized_pnl")
        or summary.get("unrealizedPnL")
        or payload.get("unrealized_pnl")
        or 0.0
    )
    greeks = payload.get("portfolio_greeks") or summary.get("greeks") or {}
    net_delta = greeks.get("delta", 0.0)

    expiring = 0
    for p in positions:
        dte = p.get("dte")
        if dte is not None and dte <= 7:
            expiring += 1
    return {
        "portfolio_value": portfolio_value,
        "unrealized_pnl": unrealized,
        "net_delta": net_delta,
        "expiring": expiring,
    }


portfolio = run_script_cached("portfolio_positions", (), timeout=90)

if has_error(portfolio):
    show_error(portfolio)
else:
    kpis = _extract_kpis(portfolio)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(i18n("portfolio_value", lang), f"${kpis['portfolio_value']:,.2f}")
    pnl_val = kpis["unrealized_pnl"]
    c2.metric(
        i18n("unrealized_pnl", lang),
        f"${pnl_val:,.2f}",
        delta=f"{pnl_val:,.2f}",
        delta_color="normal",
    )
    c3.metric(i18n("net_delta", lang), f"{kpis['net_delta']:,.2f}")
    c4.metric(i18n("expiring_soon", lang), kpis["expiring"])

st.divider()

# --------------------------------------------------------------------------- #
# Intro
# --------------------------------------------------------------------------- #
st.write(i18n("intro", lang))

nav_keys = [
    ("positions", "1_📊_Positions"),
    ("option_chain", "2_📈_Option_Chain"),
    ("strategies", "3_🎯_Strategies"),
    ("daily_report", "4_📰_Daily_Report"),
    ("pnl_analytics", "5_💰_P&L_Analytics"),
    ("earnings", "6_📅_Earnings"),
    ("risk_simulator", "7_⚡_Risk_Simulator"),
]

cols = st.columns(len(nav_keys))
for col, (key, _page) in zip(cols, nav_keys):
    with col:
        st.markdown(f"**{i18n(key, lang)}**")
