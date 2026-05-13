"""
期权策略分析器 — 根据标的、市场观点和风险偏好推荐最优策略。

综合 McMillan《Options as a Strategic Investment》和 Overby《The Options Playbook》的
完整策略体系，分 4 级：Rookie → Intermediate → Advanced → Expert。

根据 outlook + risk_profile + IV 环境自动推荐并用实际期权链定价计算风险收益。

用法：
  python options_analyzer.py SPY --outlook bullish
  python options_analyzer.py AAPL --outlook neutral --risk-profile conservative
  python options_analyzer.py SPY --outlook bearish --chain-file /tmp/spy_chain.json
  python options_analyzer.py SPY --outlook bullish --iv-context
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, date
from typing import Optional

from contracts import resolve
from ib_client import ib_connect, log, qualify, req_historical_safe

CLIENT_ID_OFFSET = 10


# ═══════════════════════════════════════════════════════════════════
# 策略库（McMillan + Overby 综合）
# ═══════════════════════════════════════════════════════════════════

STRATEGIES = {
    # ─── Tier 1: Rookie（单腿基础）───
    "long_call": {
        "name": "Long Call",
        "name_cn": "买入看涨",
        "tier": "rookie",
        "direction": "bullish",
        "legs": [{"action": "BUY", "right": "C", "strike_offset": 0}],
        "risk_profiles": ["aggressive"],
        "iv_preference": "low",
        "description": "直接买入 call，看涨且预期大幅上涨。最大亏损为权利金，盈利无上限。",
    },
    "long_put": {
        "name": "Long Put",
        "name_cn": "买入看跌",
        "tier": "rookie",
        "direction": "bearish",
        "legs": [{"action": "BUY", "right": "P", "strike_offset": 0}],
        "risk_profiles": ["aggressive"],
        "iv_preference": "low",
        "description": "直接买入 put，看跌且预期大幅下跌。最大亏损为权利金。",
    },
    "cash_secured_put": {
        "name": "Cash-Secured Put",
        "name_cn": "现金担保卖出看跌",
        "tier": "rookie",
        "direction": "bullish",
        "legs": [{"action": "SELL", "right": "P", "strike_offset": -2}],
        "risk_profiles": ["conservative", "moderate"],
        "iv_preference": "high",
        "description": "卖出 put 并留足现金，愿意在低价接股票。收取权利金，若被行权则以行权价买入。",
    },
    "covered_call": {
        "name": "Covered Call",
        "name_cn": "备兑看涨",
        "tier": "rookie",
        "direction": "bullish",
        "legs": [{"action": "SELL", "right": "C", "strike_offset": 2}],
        "risk_profiles": ["conservative", "moderate"],
        "iv_preference": "high",
        "requires_stock": True,
        "description": "持有股票 + 卖出 OTM call，增加持仓收入。上行被限，但收取权利金降低成本。",
    },
    "protective_put": {
        "name": "Protective Put",
        "name_cn": "保护性看跌",
        "tier": "rookie",
        "direction": "neutral",
        "legs": [{"action": "BUY", "right": "P", "strike_offset": -2}],
        "risk_profiles": ["conservative"],
        "iv_preference": "low",
        "requires_stock": True,
        "description": "持有股票 + 买入 put，为持仓提供下行保护，类似保险。",
    },

    # ─── Tier 2: Intermediate（双腿价差）───
    "bull_call_spread": {
        "name": "Bull Call Spread",
        "name_cn": "牛市看涨价差",
        "tier": "intermediate",
        "direction": "bullish",
        "legs": [
            {"action": "BUY", "right": "C", "strike_offset": 0},
            {"action": "SELL", "right": "C", "strike_offset": 3},
        ],
        "risk_profiles": ["moderate"],
        "iv_preference": "neutral",
        "description": "买低行权价 call + 卖高行权价 call。温和看涨，限制成本和盈利上限。",
    },
    "bear_put_spread": {
        "name": "Bear Put Spread",
        "name_cn": "熊市看跌价差",
        "tier": "intermediate",
        "direction": "bearish",
        "legs": [
            {"action": "BUY", "right": "P", "strike_offset": 0},
            {"action": "SELL", "right": "P", "strike_offset": -3},
        ],
        "risk_profiles": ["moderate"],
        "iv_preference": "neutral",
        "description": "买高行权价 put + 卖低行权价 put。温和看跌，限制成本。",
    },
    "bull_put_spread": {
        "name": "Bull Put Spread",
        "name_cn": "牛市看跌价差（credit）",
        "tier": "intermediate",
        "direction": "bullish",
        "legs": [
            {"action": "SELL", "right": "P", "strike_offset": -1},
            {"action": "BUY", "right": "P", "strike_offset": -4},
        ],
        "risk_profiles": ["moderate"],
        "iv_preference": "high",
        "description": "卖高行权价 put + 买低行权价 put。看涨收权利金，有限风险。",
    },
    "bear_call_spread": {
        "name": "Bear Call Spread",
        "name_cn": "熊市看涨价差（credit）",
        "tier": "intermediate",
        "direction": "bearish",
        "legs": [
            {"action": "SELL", "right": "C", "strike_offset": 1},
            {"action": "BUY", "right": "C", "strike_offset": 4},
        ],
        "risk_profiles": ["moderate"],
        "iv_preference": "high",
        "description": "卖低行权价 call + 买高行权价 call。看跌收权利金。",
    },
    "long_straddle": {
        "name": "Long Straddle",
        "name_cn": "买入跨式",
        "tier": "intermediate",
        "direction": "volatile",
        "legs": [
            {"action": "BUY", "right": "C", "strike_offset": 0},
            {"action": "BUY", "right": "P", "strike_offset": 0},
        ],
        "risk_profiles": ["moderate", "aggressive"],
        "iv_preference": "low",
        "description": "买入同行权价 call + put。预期大幅波动方向不确定，需突破两端 breakeven。",
    },
    "short_straddle": {
        "name": "Short Straddle",
        "name_cn": "卖出跨式",
        "tier": "intermediate",
        "direction": "neutral",
        "legs": [
            {"action": "SELL", "right": "C", "strike_offset": 0},
            {"action": "SELL", "right": "P", "strike_offset": 0},
        ],
        "risk_profiles": ["aggressive"],
        "iv_preference": "high",
        "description": "卖出同行权价 call + put。预期横盘，收取双倍权利金，风险无限。",
    },
    "long_strangle": {
        "name": "Long Strangle",
        "name_cn": "买入宽跨式",
        "tier": "intermediate",
        "direction": "volatile",
        "legs": [
            {"action": "BUY", "right": "C", "strike_offset": 2},
            {"action": "BUY", "right": "P", "strike_offset": -2},
        ],
        "risk_profiles": ["moderate"],
        "iv_preference": "low",
        "description": "买 OTM call + OTM put。比 straddle 便宜，需更大幅度波动获利。",
    },
    "short_strangle": {
        "name": "Short Strangle",
        "name_cn": "卖出宽跨式",
        "tier": "intermediate",
        "direction": "neutral",
        "legs": [
            {"action": "SELL", "right": "C", "strike_offset": 3},
            {"action": "SELL", "right": "P", "strike_offset": -3},
        ],
        "risk_profiles": ["moderate", "aggressive"],
        "iv_preference": "high",
        "description": "卖 OTM call + OTM put。比 short straddle 更宽容错区间，风险仍无限。",
    },
    "collar": {
        "name": "Collar",
        "name_cn": "领口策略",
        "tier": "intermediate",
        "direction": "neutral",
        "legs": [
            {"action": "BUY", "right": "P", "strike_offset": -2},
            {"action": "SELL", "right": "C", "strike_offset": 2},
        ],
        "risk_profiles": ["conservative"],
        "iv_preference": "neutral",
        "requires_stock": True,
        "description": "持股 + 买 put + 卖 call。零成本保护，上行换下行。",
    },

    # ─── Tier 3: Advanced（三腿+复合）───
    "iron_condor": {
        "name": "Iron Condor",
        "name_cn": "铁秃鹰",
        "tier": "advanced",
        "direction": "neutral",
        "legs": [
            {"action": "SELL", "right": "P", "strike_offset": -2},
            {"action": "BUY", "right": "P", "strike_offset": -5},
            {"action": "SELL", "right": "C", "strike_offset": 2},
            {"action": "BUY", "right": "C", "strike_offset": 5},
        ],
        "risk_profiles": ["conservative", "moderate"],
        "iv_preference": "high",
        "description": "bull put spread + bear call spread。预期区间震荡，有限风险有限收益。",
    },
    "iron_butterfly": {
        "name": "Iron Butterfly",
        "name_cn": "铁蝶式",
        "tier": "advanced",
        "direction": "neutral",
        "legs": [
            {"action": "SELL", "right": "P", "strike_offset": 0},
            {"action": "BUY", "right": "P", "strike_offset": -3},
            {"action": "SELL", "right": "C", "strike_offset": 0},
            {"action": "BUY", "right": "C", "strike_offset": 3},
        ],
        "risk_profiles": ["moderate"],
        "iv_preference": "high",
        "description": "卖 ATM straddle + 买 OTM strangle 保护。比 iron condor 更窄，收益更高。",
    },
    "long_call_butterfly": {
        "name": "Long Call Butterfly",
        "name_cn": "买入蝶式（call）",
        "tier": "advanced",
        "direction": "neutral",
        "legs": [
            {"action": "BUY", "right": "C", "strike_offset": -3},
            {"action": "SELL", "right": "C", "strike_offset": 0, "quantity": 2},
            {"action": "BUY", "right": "C", "strike_offset": 3},
        ],
        "risk_profiles": ["moderate"],
        "iv_preference": "neutral",
        "description": "买低 call + 卖 2x 中 call + 买高 call。预期到期日价格锚定在中间行权价。",
    },
    "jade_lizard": {
        "name": "Jade Lizard",
        "name_cn": "翡翠蜥蜴",
        "tier": "advanced",
        "direction": "bullish",
        "legs": [
            {"action": "SELL", "right": "P", "strike_offset": -2},
            {"action": "SELL", "right": "C", "strike_offset": 2},
            {"action": "BUY", "right": "C", "strike_offset": 5},
        ],
        "risk_profiles": ["moderate"],
        "iv_preference": "high",
        "description": "卖 put + bear call spread。上行风险有限的收入策略。",
    },

    # ─── Tier 4: Expert（比率/合成）───
    "call_ratio_backspread": {
        "name": "Call Ratio Backspread",
        "name_cn": "看涨比率反向价差",
        "tier": "expert",
        "direction": "bullish",
        "legs": [
            {"action": "SELL", "right": "C", "strike_offset": 0},
            {"action": "BUY", "right": "C", "strike_offset": 3, "quantity": 2},
        ],
        "risk_profiles": ["aggressive"],
        "iv_preference": "low",
        "description": "卖 1x 低行权价 call + 买 2x 高行权价 call。大幅上涨获利无限。",
    },
    "put_ratio_backspread": {
        "name": "Put Ratio Backspread",
        "name_cn": "看跌比率反向价差",
        "tier": "expert",
        "direction": "bearish",
        "legs": [
            {"action": "SELL", "right": "P", "strike_offset": 0},
            {"action": "BUY", "right": "P", "strike_offset": -3, "quantity": 2},
        ],
        "risk_profiles": ["aggressive"],
        "iv_preference": "low",
        "description": "卖 1x 高行权价 put + 买 2x 低行权价 put。大幅下跌获利无限。",
    },
    "risk_reversal": {
        "name": "Risk Reversal",
        "name_cn": "风险反转",
        "tier": "expert",
        "direction": "bullish",
        "legs": [
            {"action": "BUY", "right": "C", "strike_offset": 2},
            {"action": "SELL", "right": "P", "strike_offset": -2},
        ],
        "risk_profiles": ["aggressive"],
        "iv_preference": "neutral",
        "description": "买 OTM call + 卖 OTM put。零成本方向性押注，有下行风险。",
    },
}

# ─── 策略选择矩阵 ───
# outlook → risk_profile → [strategy_keys]
SELECTION_MATRIX = {
    "bullish": {
        "conservative": ["covered_call", "cash_secured_put", "collar"],
        "moderate":     ["bull_call_spread", "bull_put_spread"],
        "aggressive":   ["long_call", "call_ratio_backspread", "risk_reversal"],
    },
    "bearish": {
        "conservative": ["protective_put", "bear_call_spread"],
        "moderate":     ["bear_put_spread"],
        "aggressive":   ["long_put", "put_ratio_backspread"],
    },
    "neutral": {
        "conservative": ["covered_call", "iron_condor"],
        "moderate":     ["iron_condor", "iron_butterfly", "jade_lizard"],
        "aggressive":   ["short_straddle", "short_strangle"],
    },
    "volatile": {
        "conservative": ["long_strangle"],
        "moderate":     ["long_straddle", "long_strangle"],
        "aggressive":   ["long_straddle", "call_ratio_backspread"],
    },
}


# ═══════════════════════════════════════════════════════════════════
# 期权链数据处理
# ═══════════════════════════════════════════════════════════════════

def _load_chain(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def _fetch_chain_inline(ib, symbol: str) -> dict:
    from options_chain import fetch_chain
    return fetch_chain(ib, symbol, num_strikes=10, dte_min=7, dte_max=60,
                       max_expirations=3)


def _find_option(chain_data: dict, expiration: str, strike: float,
                 right: str) -> Optional[dict]:
    side = "calls" if right == "C" else "puts"
    for exp_group in chain_data.get("chain", []):
        if exp_group["expiration"] == expiration:
            for opt in exp_group.get(side, []):
                if abs(opt["strike"] - strike) < 0.01:
                    return opt
    return None


def _best_expiration(chain_data: dict, target_dte: int = 30) -> Optional[dict]:
    best = None
    best_diff = 999
    for exp_group in chain_data.get("chain", []):
        diff = abs(exp_group["dte"] - target_dte)
        if diff < best_diff:
            best_diff = diff
            best = exp_group
    return best


def _atm_strike(exp_group: dict, underlying_price: float) -> float:
    all_strikes = [c["strike"] for c in exp_group.get("calls", [])]
    if not all_strikes:
        return underlying_price
    return min(all_strikes, key=lambda s: abs(s - underlying_price))


def _strike_step(exp_group: dict) -> float:
    strikes = sorted(set(c["strike"] for c in exp_group.get("calls", [])))
    if len(strikes) < 2:
        return 1.0
    diffs = [strikes[i+1] - strikes[i] for i in range(len(strikes)-1)]
    return min(diffs)


# ═══════════════════════════════════════════════════════════════════
# IV 环境分析
# ═══════════════════════════════════════════════════════════════════

def compute_historical_vol(ib, symbol: str, days: int = 20) -> Optional[float]:
    contract = resolve(symbol)
    try:
        q = qualify(ib, contract)
    except Exception:
        return None
    bars = req_historical_safe(
        ib, q,
        endDateTime="",
        durationStr=f"{days + 10} D",
        barSizeSetting="1 day",
        whatToShow="TRADES",
        useRTH=True,
        formatDate=1,
    )
    if not bars or len(bars) < days:
        return None
    closes = [b.close for b in bars[-(days + 1):]]
    log_returns = [math.log(closes[i] / closes[i-1]) for i in range(1, len(closes))]
    if not log_returns:
        return None
    variance = sum(r ** 2 for r in log_returns) / len(log_returns)
    return round(math.sqrt(variance * 252), 4)


def assess_iv_environment(chain_data: dict, hist_vol: Optional[float]) -> dict:
    ivs = []
    for exp_group in chain_data.get("chain", []):
        for opt in exp_group.get("calls", []) + exp_group.get("puts", []):
            iv = opt.get("iv")
            if iv and iv > 0:
                ivs.append(iv)
    if not ivs:
        return {"current_iv": None, "hist_vol_20d": hist_vol, "assessment": "数据不足"}
    avg_iv = round(sum(ivs) / len(ivs), 4)
    result = {
        "current_iv": avg_iv,
        "hist_vol_20d": hist_vol,
    }
    if hist_vol and hist_vol > 0:
        ratio = avg_iv / hist_vol
        if ratio > 1.3:
            result["assessment"] = "IV 偏高（期权偏贵）→ 偏卖方策略"
            result["iv_bias"] = "high"
        elif ratio < 0.8:
            result["assessment"] = "IV 偏低（期权偏便宜）→ 偏买方策略"
            result["iv_bias"] = "low"
        else:
            result["assessment"] = "IV 适中 → 价差策略为主"
            result["iv_bias"] = "neutral"
        result["iv_to_hv_ratio"] = round(ratio, 2)
    else:
        result["assessment"] = "无历史波动率对比"
        result["iv_bias"] = "neutral"
    return result


# ═══════════════════════════════════════════════════════════════════
# 策略构建与定价
# ═══════════════════════════════════════════════════════════════════

def _mid_price(opt: dict) -> Optional[float]:
    bid = opt.get("bid")
    ask = opt.get("ask")
    if bid and ask and bid > 0 and ask > 0:
        return round((bid + ask) / 2, 2)
    return opt.get("last")


def build_strategy(strategy_key: str, chain_data: dict,
                   underlying_price: float) -> Optional[dict]:
    strategy = STRATEGIES[strategy_key]
    exp_group = _best_expiration(chain_data, target_dte=30)
    if not exp_group:
        return None

    atm = _atm_strike(exp_group, underlying_price)
    step = _strike_step(exp_group)

    legs = []
    total_debit = 0.0
    all_priced = True

    for leg_def in strategy["legs"]:
        strike = atm + leg_def["strike_offset"] * step
        right = leg_def["right"]
        qty = leg_def.get("quantity", 1)

        opt = _find_option(chain_data, exp_group["expiration"], strike, right)
        if not opt:
            all_priced = False
            legs.append({
                "action": leg_def["action"],
                "strike": strike,
                "right": "Call" if right == "C" else "Put",
                "quantity": qty,
                "price": None,
            })
            continue

        price = _mid_price(opt)
        leg_info = {
            "action": leg_def["action"],
            "strike": strike,
            "right": "Call" if right == "C" else "Put",
            "expiration": exp_group["expiration"],
            "quantity": qty,
            "price": price,
            "iv": opt.get("iv"),
            "delta": opt.get("delta"),
        }
        legs.append(leg_info)

        if price:
            if leg_def["action"] == "BUY":
                total_debit += price * qty
            else:
                total_debit -= price * qty

    max_profit, max_loss, breakeven = _calc_risk_reward(
        strategy_key, legs, underlying_price, step,
    )

    prob_profit = None
    if legs and legs[0].get("delta") is not None:
        d = abs(legs[0]["delta"])
        if strategy["direction"] in ("bullish",):
            prob_profit = round(d * 100, 1) if legs[0]["right"] == "Call" else round((1 - d) * 100, 1)
        elif strategy["direction"] in ("bearish",):
            prob_profit = round(d * 100, 1) if legs[0]["right"] == "Put" else round((1 - d) * 100, 1)

    rr_ratio = None
    if isinstance(max_profit, (int, float)) and isinstance(max_loss, (int, float)) and max_loss != 0:
        rr_ratio = round(abs(max_profit / max_loss), 2)

    return {
        "strategy": strategy["name"],
        "strategy_cn": strategy["name_cn"],
        "tier": strategy["tier"],
        "direction": strategy["direction"],
        "legs": legs,
        "net_debit_credit": round(total_debit, 2) if all_priced else None,
        "type": "debit" if total_debit > 0 else "credit",
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakeven": breakeven,
        "risk_reward_ratio": rr_ratio,
        "probability_of_profit": prob_profit,
        "description": strategy["description"],
    }


def _calc_risk_reward(strategy_key: str, legs, underlying_price: float,
                      step: float):
    prices = [l.get("price") for l in legs]
    if not all(prices):
        return None, None, None

    s = STRATEGIES[strategy_key]
    num_legs = len(s["legs"])

    if num_legs == 1:
        price = prices[0]
        leg = s["legs"][0]
        if leg["action"] == "BUY":
            max_loss = round(-price * 100, 2)
            if leg["right"] == "C":
                max_profit = "unlimited"
                be = round(legs[0]["strike"] + price, 2)
            else:
                max_profit = round((legs[0]["strike"] - price) * 100, 2)
                be = round(legs[0]["strike"] - price, 2)
        else:
            max_profit = round(price * 100, 2)
            if leg["right"] == "P":
                max_loss = round(-(legs[0]["strike"] - price) * 100, 2)
                be = round(legs[0]["strike"] - price, 2)
            else:
                max_loss = "unlimited"
                be = round(legs[0]["strike"] + price, 2)
        return max_profit, max_loss, be

    if num_legs == 2 and s["legs"][0]["right"] == s["legs"][1]["right"]:
        width = abs(legs[0]["strike"] - legs[1]["strike"])
        net = sum(
            (-p if s["legs"][i]["action"] == "BUY" else p)
            for i, p in enumerate(prices)
        )
        if net > 0:
            max_profit = round(net * 100, 2)
            max_loss = round(-(width - net) * 100, 2)
        else:
            net_debit = abs(net)
            max_profit = round((width - net_debit) * 100, 2)
            max_loss = round(-net_debit * 100, 2)
        be_strike = min(legs[0]["strike"], legs[1]["strike"])
        be = round(be_strike + abs(net), 2) if s["legs"][0]["right"] == "C" else round(
            max(legs[0]["strike"], legs[1]["strike"]) - abs(net), 2
        )
        return max_profit, max_loss, be

    if strategy_key in ("long_straddle", "long_strangle"):
        net_debit = sum(prices)
        max_loss = round(-net_debit * 100, 2)
        max_profit = "unlimited"
        be = f"{round(legs[1]['strike'] - net_debit, 2)} / {round(legs[0]['strike'] + net_debit, 2)}"
        return max_profit, max_loss, be

    if strategy_key in ("short_straddle", "short_strangle"):
        net_credit = sum(prices)
        max_profit = round(net_credit * 100, 2)
        max_loss = "unlimited"
        be = f"{round(legs[1]['strike'] - net_credit, 2)} / {round(legs[0]['strike'] + net_credit, 2)}"
        return max_profit, max_loss, be

    if strategy_key in ("iron_condor", "iron_butterfly"):
        put_credit = prices[0] - prices[1]
        call_credit = prices[2] - prices[3]
        net_credit = put_credit + call_credit
        put_width = abs(legs[0]["strike"] - legs[1]["strike"])
        call_width = abs(legs[2]["strike"] - legs[3]["strike"])
        max_width = max(put_width, call_width)
        max_profit = round(net_credit * 100, 2)
        max_loss = round(-(max_width - net_credit) * 100, 2)
        be = f"{round(legs[0]['strike'] - net_credit, 2)} / {round(legs[2]['strike'] + net_credit, 2)}"
        return max_profit, max_loss, be

    return None, None, None


# ═══════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════

def analyze(
    chain_data: dict,
    outlook: str,
    risk_profile: str = "moderate",
    iv_context: Optional[dict] = None,
    portfolio_data: Optional[dict] = None,
) -> dict:
    underlying_price = chain_data["underlying_price"]
    candidates = SELECTION_MATRIX.get(outlook, {}).get(risk_profile, [])
    if not candidates:
        candidates = SELECTION_MATRIX.get(outlook, {}).get("moderate", [])

    if iv_context and iv_context.get("iv_bias"):
        bias = iv_context["iv_bias"]
        reordered = []
        for key in candidates:
            pref = STRATEGIES[key].get("iv_preference", "neutral")
            if pref == bias or pref == "neutral":
                reordered.insert(0, key)
            else:
                reordered.append(key)
        candidates = reordered

    recommendations = []
    for key in candidates:
        result = build_strategy(key, chain_data, underlying_price)
        if result:
            if iv_context:
                result["iv_context"] = iv_context
            recommendations.append(result)

    return {
        "symbol": chain_data["symbol"],
        "underlying_price": underlying_price,
        "outlook": outlook,
        "risk_profile": risk_profile,
        "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "recommendations": recommendations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="IBKR Options Strategy Analyzer")
    parser.add_argument("symbol", help="标的代码 (e.g. SPY, AAPL)")
    parser.add_argument("--outlook", required=True,
                        choices=["bullish", "bearish", "neutral", "volatile"],
                        help="市场观点")
    parser.add_argument("--risk-profile", default="moderate",
                        choices=["conservative", "moderate", "aggressive"],
                        help="风险偏好 (default: moderate)")
    parser.add_argument("--chain-file", help="期权链 JSON 文件（跳过实时获取）")
    parser.add_argument("--portfolio-file", help="持仓 JSON 文件")
    parser.add_argument("--iv-context", action="store_true",
                        help="计算 IV 环境（20 日历史波动率 vs 当前 IV）")
    parser.add_argument("--output", help="输出文件路径（默认 stdout）")
    args = parser.parse_args()

    log(f"🔄 分析 {args.symbol} 期权策略 "
        f"(outlook={args.outlook}, risk={args.risk_profile})...")

    chain_data = None
    iv_ctx = None
    portfolio_data = None

    if args.chain_file:
        log(f"  从文件加载期权链: {args.chain_file}")
        chain_data = _load_chain(args.chain_file)

    if args.portfolio_file:
        with open(args.portfolio_file) as f:
            portfolio_data = json.load(f)

    need_connection = chain_data is None or args.iv_context

    if need_connection:
        try:
            with ib_connect(client_id_offset=CLIENT_ID_OFFSET) as ib:
                if chain_data is None:
                    log("  实时获取期权链...")
                    chain_data = _fetch_chain_inline(ib, args.symbol)
                if args.iv_context:
                    log("  计算历史波动率...")
                    hist_vol = compute_historical_vol(ib, args.symbol)
                    iv_ctx = assess_iv_environment(chain_data, hist_vol)
                    log(f"  IV 环境: {iv_ctx.get('assessment', 'N/A')}")
        except Exception as e:
            log(f"❌ 连接失败: {e}")
            return 1
    else:
        if args.iv_context:
            iv_ctx = assess_iv_environment(chain_data, None)

    result = analyze(chain_data, args.outlook, args.risk_profile,
                     iv_ctx, portfolio_data)

    json_str = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        tmp = args.output + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json_str)
        os.rename(tmp, args.output)
        log(f"📁 已保存到 {args.output}")
    else:
        print(json_str)

    log(f"✅ 完成: {len(result['recommendations'])} 个策略推荐")
    return 0


if __name__ == "__main__":
    sys.exit(main())
