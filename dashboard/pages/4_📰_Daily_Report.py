"""Daily report page — expiry warnings, IV analysis, recommendations."""
from __future__ import annotations

import streamlit as st

from utils import get_lang, has_error, i18n, page_setup, run_script, show_error


page_setup()
lang = get_lang()
st.title(f"📰 {i18n('daily_report', lang)}")

extra = st.text_input(i18n("extra_symbols", lang), value="")
go = st.button(i18n("generate_report", lang))

if not go:
    st.stop()

args: list[str] = []
extras = [s.strip().upper() for s in extra.split() if s.strip()]
if extras:
    args = ["--symbols", *extras]

with st.spinner(i18n("loading", lang)):
    payload = run_script("options_daily", args, timeout=300)
if has_error(payload):
    show_error(payload)
    st.stop()

warnings = payload.get("expiry_warnings") or payload.get("warnings") or []
iv_section = payload.get("iv_analysis") or payload.get("iv") or {}
recs = payload.get("recommendations") or []

col1, col2, col3 = st.columns(3)

with col1:
    st.subheader(i18n("expiry_warnings", lang))
    if warnings:
        for w in warnings:
            with st.container(border=True):
                st.json(w)
    else:
        st.info(i18n("no_data", lang))

with col2:
    st.subheader(i18n("iv_analysis", lang))
    if iv_section:
        if isinstance(iv_section, list):
            for row in iv_section:
                with st.container(border=True):
                    st.json(row)
        else:
            st.json(iv_section)
    else:
        st.info(i18n("no_data", lang))

with col3:
    st.subheader(i18n("recommendations", lang))
    if recs:
        for r in recs:
            with st.container(border=True):
                st.json(r)
    else:
        st.info(i18n("no_data", lang))
