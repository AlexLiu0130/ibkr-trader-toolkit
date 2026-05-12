"""Shared utilities for the IBKR Trader Toolkit Streamlit dashboard.

Wraps the JSON-emitting scripts in scripts/ via subprocess.run and provides
i18n + session-state helpers used by every page.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

import streamlit as st


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
DASHBOARD_DIR = Path(__file__).resolve().parent
PROJECT_DIR = DASHBOARD_DIR.parent
SCRIPTS_DIR = PROJECT_DIR / "scripts"


# --------------------------------------------------------------------------- #
# i18n
# --------------------------------------------------------------------------- #
TRANSLATIONS: dict[str, dict[str, str]] = {
    "app_title": {"zh": "IBKR 交易工具箱", "en": "IBKR Trader Toolkit"},
    "language": {"zh": "语言", "en": "Language"},
    "gateway_status": {"zh": "网关状态", "en": "Gateway Status"},
    "connected": {"zh": "已连接", "en": "Connected"},
    "disconnected": {"zh": "未连接", "en": "Disconnected"},
    "portfolio_value": {"zh": "组合市值", "en": "Portfolio Value"},
    "unrealized_pnl": {"zh": "未实现盈亏", "en": "Unrealized P&L"},
    "net_delta": {"zh": "净 Delta", "en": "Net Delta"},
    "expiring_soon": {"zh": "≤7 天到期", "en": "Expirations ≤7d"},
    "intro": {
        "zh": "通过左侧导航访问持仓、期权链、策略推荐、日报、盈亏分析、财报日历、风险模拟器等模块。所有数据由 scripts/ 下的脚本实时获取。",
        "en": "Use the sidebar to navigate to Positions, Option Chain, Strategies, Daily Report, P&L Analytics, Earnings, and Risk Simulator. All data is fetched live via the scripts in scripts/.",
    },
    "error_script": {"zh": "脚本执行失败", "en": "Script execution failed"},
    "error_hint": {
        "zh": "请确认 IB Gateway / TWS 已启动并已登录，端口与 clientId 配置正确。",
        "en": "Make sure IB Gateway / TWS is running and logged in, and the port + clientId are configured correctly.",
    },
    "positions": {"zh": "持仓", "en": "Positions"},
    "option_chain": {"zh": "期权链", "en": "Option Chain"},
    "strategies": {"zh": "策略推荐", "en": "Strategies"},
    "daily_report": {"zh": "每日报告", "en": "Daily Report"},
    "pnl_analytics": {"zh": "盈亏分析", "en": "P&L Analytics"},
    "earnings": {"zh": "财报日历", "en": "Earnings"},
    "risk_simulator": {"zh": "风险模拟器", "en": "Risk Simulator"},
    "symbol": {"zh": "标的代码", "en": "Symbol"},
    "symbols": {"zh": "标的代码（空格分隔）", "en": "Symbols (space separated)"},
    "strikes": {"zh": "行权价数量", "en": "Strikes"},
    "dte_min": {"zh": "最小到期天数", "en": "Min DTE"},
    "dte_max": {"zh": "最大到期天数", "en": "Max DTE"},
    "max_expirations": {"zh": "最多到期日", "en": "Max Expirations"},
    "outlook": {"zh": "市场观点", "en": "Outlook"},
    "risk_profile": {"zh": "风险偏好", "en": "Risk Profile"},
    "use_iv_context": {"zh": "使用 IV 上下文", "en": "Use IV Context"},
    "submit": {"zh": "提交", "en": "Submit"},
    "loading": {"zh": "加载中…", "en": "Loading…"},
    "no_data": {"zh": "暂无数据", "en": "No data"},
    "calls": {"zh": "看涨期权", "en": "Calls"},
    "puts": {"zh": "看跌期权", "en": "Puts"},
    "iv_smile": {"zh": "IV 微笑曲线", "en": "IV Smile"},
    "max_profit": {"zh": "最大盈利", "en": "Max Profit"},
    "max_loss": {"zh": "最大亏损", "en": "Max Loss"},
    "breakeven": {"zh": "盈亏平衡点", "en": "Breakeven"},
    "probability": {"zh": "胜率", "en": "Probability"},
    "legs": {"zh": "腿", "en": "Legs"},
    "generate_report": {"zh": "生成今日报告", "en": "Generate Today's Report"},
    "expiry_warnings": {"zh": "到期提醒", "en": "Expiry Warnings"},
    "iv_analysis": {"zh": "IV 分析", "en": "IV Analysis"},
    "recommendations": {"zh": "推荐", "en": "Recommendations"},
    "filter_by": {"zh": "筛选维度", "en": "Filter By"},
    "days": {"zh": "天数", "en": "Days"},
    "pnl_distribution": {"zh": "盈亏分布", "en": "P&L Distribution"},
    "win_rate": {"zh": "胜率", "en": "Win Rate"},
    "best_worst": {"zh": "最佳 / 最差交易", "en": "Best / Worst Trades"},
    "add_leg": {"zh": "添加期权腿", "en": "Add Leg"},
    "clear_legs": {"zh": "清空", "en": "Clear"},
    "simulate": {"zh": "模拟", "en": "Simulate"},
    "current_vs_simulated": {"zh": "当前 vs 模拟", "en": "Current vs Simulated"},
    "warnings": {"zh": "警告", "en": "Warnings"},
    "strike": {"zh": "行权价", "en": "Strike"},
    "expiry": {"zh": "到期日", "en": "Expiry"},
    "right": {"zh": "类型", "en": "Right"},
    "action": {"zh": "买/卖", "en": "Action"},
    "qty": {"zh": "数量", "en": "Qty"},
    "net_greeks": {"zh": "组合希腊值", "en": "Net Greeks"},
    "greeks_by_symbol": {"zh": "按标的的希腊值占比", "en": "Greeks by Symbol"},
    "timeline": {"zh": "时间线", "en": "Timeline"},
    "extra_symbols": {"zh": "额外标的（可选）", "en": "Extra Symbols (optional)"},
    "no_recommendations": {"zh": "暂无推荐", "en": "No recommendations"},
}


def i18n(key: str, lang: str | None = None) -> str:
    """Translate `key` into `lang` (zh|en). Falls back to the key itself."""
    if lang is None:
        lang = get_lang()
    entry = TRANSLATIONS.get(key)
    if not entry:
        return key
    return entry.get(lang, entry.get("en", key))


def get_lang() -> str:
    """Return the current UI language code (zh|en)."""
    return st.session_state.get("lang", "zh")


def language_selector(location=None) -> None:
    """Render a compact language picker that writes to st.session_state.lang."""
    target = location if location is not None else st
    options = {"zh": "中文", "en": "English"}
    current = get_lang()
    choice = target.selectbox(
        i18n("language", current),
        options=list(options.keys()),
        index=list(options.keys()).index(current) if current in options else 0,
        format_func=lambda k: options[k],
        key="lang_selector",
    )
    st.session_state.lang = choice


# --------------------------------------------------------------------------- #
# Script runner
# --------------------------------------------------------------------------- #
def run_script(
    script_name: str,
    args: list[str] | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Run scripts/{script_name}.py with the given args, return parsed JSON.

    All scripts support `--output FILE` for JSON. We always write to a tempfile
    so stdout chatter doesn't pollute the payload. On any failure (non-zero exit,
    timeout, missing script, invalid JSON) we return `{"error": "..."}`.
    """
    args = args or []
    script_path = SCRIPTS_DIR / f"{script_name}.py"
    if not script_path.exists():
        return {"error": f"Script not found: {script_path}"}

    out_file = Path(tempfile.gettempdir()) / f"ibkr_{script_name}_{uuid.uuid4().hex}.json"
    cmd = [sys.executable, str(script_path), *args, "--output", str(out_file)]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(PROJECT_DIR),
        )
    except subprocess.TimeoutExpired:
        return {"error": f"Timeout after {timeout}s running {script_name}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"Subprocess error: {e}"}

    if result.returncode != 0:
        stderr_tail = (result.stderr or "")[-500:]
        return {
            "error": f"{script_name} exited {result.returncode}",
            "stderr": stderr_tail,
        }

    if out_file.exists():
        try:
            data = json.loads(out_file.read_text())
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON from {script_name}: {e}"}
        finally:
            try:
                out_file.unlink()
            except OSError:
                pass
        return data

    # Fall back to stdout if the script didn't honor --output
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": f"No JSON output from {script_name}", "stdout": result.stdout[-500:]}


@st.cache_data(ttl=60, show_spinner=False)
def run_script_cached(
    script_name: str,
    args_tuple: tuple[str, ...] = (),
    timeout: int = 120,
) -> dict[str, Any]:
    """Cached variant of run_script keyed by (script, args). 60s TTL."""
    return run_script(script_name, list(args_tuple), timeout=timeout)


def has_error(payload: dict[str, Any]) -> bool:
    return isinstance(payload, dict) and "error" in payload


def show_error(payload: dict[str, Any]) -> None:
    """Render an error payload with a troubleshooting hint."""
    lang = get_lang()
    msg = payload.get("error", "Unknown error")
    st.error(f"{i18n('error_script', lang)}: {msg}")
    if payload.get("stderr"):
        with st.expander("stderr"):
            st.code(payload["stderr"])
    st.info(i18n("error_hint", lang))


# --------------------------------------------------------------------------- #
# Page bootstrap
# --------------------------------------------------------------------------- #
def page_setup(page_title: str | None = None) -> None:
    """Common st.set_page_config + sidebar language picker."""
    lang = get_lang()
    title = page_title or i18n("app_title", lang)
    st.set_page_config(
        page_title=title,
        page_icon="📊",
        layout="wide",
    )
    with st.sidebar:
        language_selector()
