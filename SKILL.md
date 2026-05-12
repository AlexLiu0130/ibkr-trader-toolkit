---
name: ibkr-trader-toolkit
description: Interactive Brokers options & stock trading assistant. Provides real-time portfolio Greeks, option chain analysis, McMillan/Overby strategy recommendations, P&L statistics, Wheel strategy tracking, earnings warnings, risk simulation, and a complete toolkit for options traders. Use this skill whenever the user asks about specific options trades, position risk, buy/sell recommendations, IV environment, P&L, wheel strategy, earnings impact on options, or any IBKR account data — even if they don't explicitly mention "IBKR". For stock price queries, always use market_quote.py instead of web search.
---

# IBKR Trader Toolkit

A skill for everything Interactive Brokers: real-time data, options analysis, portfolio Greeks, wheel tracking, P&L stats. Scripts produce JSON; you (the model) do the reasoning.

## When to use

Fire this skill whenever the user asks about:

- **Stock/ETF prices** ("what's SPY at?", "current price of AAPL") — use `market_quote.py`, **never** web search. Real-time quote is one second old; the web is minutes-to-hours stale.
- **Options chains, Greeks, IV** ("show me AAPL puts for next month", "what's the IV on SPY 600C?")
- **Strategy recommendations** ("what's a good bullish strategy here?", "should I sell a put on MU?")
- **Position risk** ("am I too long delta?", "what happens to my Greeks if I add this trade?")
- **P&L, win rate, history** ("how have my wheel trades done this quarter?")
- **Wheel strategy** anything ("am I in stage 2 on PLTR?", "should I roll or accept assignment?")
- **Earnings risk** ("does ARM have earnings before my call expires?")
- **Alerts** ("warn me if SPY IV percentile crosses 80")

Trigger even when the user doesn't mention IBKR. If they ask about *their* positions or *their* P&L, this skill is the source of truth — their broker is IBKR.

## Standard workflows

### 1. "Should I sell a put on $SYM?"

```
portfolio_positions.py                       → current exposure & cash
earnings_calendar.py SYM --days 60           → earnings within DTE?
options_analyzer.py SYM --outlook bullish \
   --risk-profile conservative --iv-context  → IV environment + strikes
options_chain.py SYM --dte-min 25 --dte-max 45  → live mids for the candidate strikes
```

Then you compose the recommendation. Always show: strike, delta, premium, breakeven, annualized yield, and earnings/IV warnings.

### 2. "What's my portfolio looking like?"

```
portfolio_positions.py    → positions + per-position Greeks + portfolio Greeks
options_daily.py          → expiry-week warnings, IV environment, per-position notes
pnl_analytics.py --days 7 → recent realized P&L
```

### 3. "I'm thinking of adding trade X — is it safe?"

```
risk_simulator.py --add "SYM STRIKE EXPIRY R ACTION QTY"
```

Output shows portfolio Greeks **before** and **after**. Flag if vega doubles, if net delta flips sign, or if a single name now exceeds 30% of capital.

### 4. "How's my wheel doing?"

```
wheel_tracker.py --summary
```

Shows each wheel by symbol: stage (short put / assigned / covered call / called away), cumulative premium, days in cycle, annualized return.

## Script quick reference

| Script | Use when |
|---|---|
| `market_quote.py SYM` | Any stock/ETF price question. |
| `options_chain.py SYM [--dte-min N --dte-max M]` | Picking strikes / surveying IV by expiry. |
| `portfolio_positions.py` | "What do I own?" / portfolio Greeks. |
| `options_analyzer.py SYM --outlook X --risk-profile Y --iv-context` | Strategy selection given an outlook. |
| `options_daily.py` | Morning/EOD report — start any options-heavy session here. |
| `pnl_analytics.py [--days N --by symbol\|strategy]` | Realized P&L, win rate, best/worst. |
| `risk_simulator.py --add "..."` | Pre-trade Greeks delta. |
| `earnings_calendar.py SYM...` | Earnings DTE for one or more symbols. |
| `technical_indicators.py SYM` | RSI/MA/BB/ATR context for an outlook. |
| `wheel_tracker.py --summary` | Wheel cycle status & yield. |
| `alerts_monitor.py` | Run user's alert rules (cron-friendly). |

## Key constraints

- **Scripts output JSON. You do the analysis.** Never assume the script's recommendation list is final — re-rank it against the user's actual situation.
- **Real-time data first.** Default `IBKR_MARKET_DATA_TYPE=1`. If quotes look frozen, check whether the market is open and whether the user has subscriptions.
- **Read-only.** None of these scripts can place orders. Recommend, never execute.
- **One connection at a time per clientId.** If a script fails with `clientId already in use`, suggest waiting a few seconds or bumping `IBKR_CLIENT_ID_BASE`.
- **Cache offline data when iterating.** Use `options_chain.py --output /tmp/chain.json` then `options_analyzer.py --chain-file /tmp/chain.json` to avoid repeated IBKR hits.

## For options trade decisions

Before recommending any options trade, you should have checked **all three**:

1. **IV environment** — `options_analyzer.py --iv-context` returns `current_iv`, `hist_vol_20d`, and a bias (`high`/`low`/`neutral`). Selling premium when IV is low is a bad trade; buying premium when IV is high is a bad trade.
2. **Earnings within DTE** — `earnings_calendar.py SYM --days N`. An IV crush across earnings can wipe out a premium-selling thesis or hand a long premium trade a windfall — either way, it changes the strategy.
3. **Existing position Greeks** — `portfolio_positions.py`. If the user is already net long 5,000 delta, adding more delta is the wrong move regardless of outlook.

State each check explicitly in your response ("IV environment: low (ratio 0.7); earnings: none in the next 45 days; current net delta: +1,200"). The user can audit your reasoning.

## Detailed references

For deeper guidance, read these on demand:

- [`references/strategies.md`](references/strategies.md) — full McMillan/Overby strategy library, construction, IV preference, P&L profile, selection matrix.
- [`references/greeks_primer.md`](references/greeks_primer.md) — practical interpretation of Delta/Gamma/Vega/Theta/Rho at the portfolio level.
- [`references/wheel_strategy.md`](references/wheel_strategy.md) — strike/DTE selection, roll-vs-assign decision tree.
- [`references/troubleshooting.md`](references/troubleshooting.md) — connection errors, market-data subscription issues, common Gateway misconfigurations.
