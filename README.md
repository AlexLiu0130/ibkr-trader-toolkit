# ibkr-trader-toolkit

> A complete options & stock trading assistant for Interactive Brokers — real-time Greeks, McMillan/Overby strategy library, P&L analytics, Wheel tracking, earnings warnings, and risk simulation. Designed to plug straight into Claude Code as a skill.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![IBKR](https://img.shields.io/badge/broker-Interactive%20Brokers-red.svg)](https://www.interactivebrokers.com/)

<!-- screenshot: hero -->

---

## Table of Contents

- [Features](#-features)
- [Requirements](#-requirements)
- [IBKR Market Data Subscriptions](#-ibkr-market-data-subscriptions)
- [Quick Start](#-quick-start)
- [Claude Code Integration](#-claude-code-integration)
- [Command Reference](#-command-reference)
- [Configuration](#-configuration)
- [Troubleshooting](#-troubleshooting)
- [Advanced](#-advanced)
- [Contributing](#-contributing)
- [License](#-license)
- [Disclaimer](#-disclaimer)

---

## ✨ Features

13 focused Python scripts. Every script outputs JSON so Claude (or any other agent) can reason about the data; the toolkit itself never gives buy/sell signals.

**Data & quotes**
- `market_quote.py` — Real-time bid/ask/last/IV/volume for stocks, ETFs, options.
- `contracts.py` — Universal contract resolver (`SPY`, `AAPL 2026-06-19 200 C`, etc.).
- `technical_indicators.py` — RSI, MA(20/50/200), Bollinger, ATR with text summary.

**Options analysis**
- `options_chain.py` — Full option chain with Greeks, OI, volume, IV per expiry.
- `options_analyzer.py` — McMillan/Overby strategy recommender (20+ strategies across 4 tiers, IV-aware).
- `options_daily.py` — End-of-day options report: warnings, IV environment, position-specific suggestions.

**Portfolio & P&L**
- `portfolio_positions.py` — Live positions with per-leg and portfolio-level Greeks.
- `pnl_analytics.py` — Realized P&L, win rate, best/worst trades (from `ib.executions` + optional Flex CSV).
- `risk_simulator.py` — "What if I add this trade?" Greeks delta preview before execution.

**Strategy automation**
- `wheel_tracker.py` — Track wheel cycles (short put → assignment → covered call → called away) with cumulative premium and annualized yield.
- `earnings_calendar.py` — Next earnings date for portfolio symbols, flags options positions expiring across earnings.
- `alerts_monitor.py` — YAML-driven threshold alerts (delta, IV percentile, DTE, P&L) for cron use.

**Connection layer**
- `ib_client.py` — Shared IB Gateway connection with readonly safety, per-script clientId offsets, and historical-data pacing.

---

## 📋 Requirements

| Requirement | Notes |
|---|---|
| **Python** | 3.10 or newer |
| **IBKR account** | Live or paper. Paper account is fine for learning. |
| **IB Gateway** | Free download from [IBKR](https://www.interactivebrokers.com/en/trading/ibgateway-stable.php). TWS also works (different port). |
| **Market data subscriptions** | See [next section](#-ibkr-market-data-subscriptions) — needed for realtime quotes & Greeks. Delayed data is free. |
| **OS** | macOS / Linux / Windows. All scripts are pure Python. |

> **Why IB Gateway, not TWS?** Gateway is headless, uses less memory, and is the standard choice for programmatic access. TWS works too — set `IBKR_PORT=7497` (paper) or `7496` (live).

---

## 💳 IBKR Market Data Subscriptions

This toolkit's value depends heavily on **what data IBKR will send you**. Subscriptions are configured per account at Client Portal → Settings → User Settings → Market Data Subscriptions.

### What each feature needs

| Feature | Subscriptions needed | Works on delayed? |
|---------|---------------------|-------------------|
| Stock/ETF price (`market_quote.py`) | None — Snapshot bundle for realtime, otherwise delayed | ✅ Yes |
| Portfolio positions & P&L (`portfolio_positions.py`, `pnl_analytics.py`) | None — account data is always available | ✅ Yes |
| Option chain bid/ask (`options_chain.py`) | **OPRA Top of Book** | ⚠️ Partial — bid/ask only, no Greeks |
| **Option Greeks** (IV, delta, gamma, vega, theta) | **OPRA + the underlying's stock exchange** | ❌ **No** — Greeks require realtime |
| Earnings calendar (`earnings_calendar.py`) | None — uses Nasdaq public API | ✅ Yes |
| Technical indicators (`technical_indicators.py`) | None — uses historical bars (free) | ✅ Yes |

**Key insight from IBKR API docs:**
> *"To receive live Greek values it is necessary to have market data subscriptions for both the option and the underlying contract."*

Translation: if you only subscribe to OPRA but not (say) NYSE ARCA, you get SPY option **prices** but not SPY option **Greeks** — because IBKR can't compute delta/gamma without realtime underlying.

### Recommended bundles for this toolkit

| Bundle | Monthly cost | Waived if | What you get |
|--------|--------------|-----------|--------------|
| **Free (delayed)** | $0 | always | Stock prices, bid/ask, portfolio data, historical bars. **No Greeks**, no live IV environment. |
| **OPRA only** | $1.50 | $20+ commissions/mo | Realtime option bid/ask. Greeks only for symbols whose underlying you also subscribe to. |
| **US Securities Bundle + OPRA** ⭐ recommended | $11.50 | $30+ commissions/mo | Realtime stock + option data + Greeks for all US-listed symbols. The toolkit's full feature set. |

**Bundle contents (US Securities Snapshot and Futures Value Bundle):**
- Consolidated realtime NBBO for US stocks/ETFs
- Top-of-book for major futures (CME, CBOT, COMEX, NYMEX)
- OTC Markets quotes

> **Commission waiver math:** If you trade 1 lot of options per week (~4 contracts × $0.65 commission ≈ $2.60/wk = ~$10/mo), you're partway there. Two roundtrip options trades per month usually clears the $30 threshold.

### How to subscribe

1. Log into [IBKR Client Portal](https://www.interactivebrokers.com/sso/Login)
2. Settings (top right) → User Settings → Market Data Subscriptions
3. Click "Configure"
4. Search and add:
   - **"US Securities Snapshot and Futures Value Bundle"** (NL)
   - **"OPRA Top of Book"** (NL)
5. Confirm and accept
6. Subscriptions usually activate within 10 minutes; restart IB Gateway

### How the toolkit handles missing subscriptions

The default `IBKR_MARKET_DATA_TYPE=3` (delayed-smart) tells IBKR:
> *"Give me realtime if I'm subscribed; fall back to delayed if I'm not."*

This means **the toolkit works on day one with $0 subscriptions** — you just won't have Greeks until you upgrade. No Error 10089 crashes.

If you ever want to force a specific mode:
- `IBKR_MARKET_DATA_TYPE=1` — strict realtime (errors on unsubscribed)
- `IBKR_MARKET_DATA_TYPE=3` — smart delayed (default; auto-upgrades)
- `IBKR_MARKET_DATA_TYPE=4` — delayed-frozen (last cached value, useful after-hours)

**Sources:**
- [IBKR Market Data Pricing](https://www.interactivebrokers.com/en/pricing/market-data-pricing.php)
- [TWS API: Option Greeks docs](https://interactivebrokers.github.io/tws-api/option_computations.html)

---

## 🚀 Quick Start

### 1. Install IB Gateway

Download from [interactivebrokers.com/en/trading/ibgateway-stable.php](https://www.interactivebrokers.com/en/trading/ibgateway-stable.php) and install. Launch it and log in with your IBKR credentials (use **paper** mode for testing).

<!-- screenshot: gateway-login -->

### 2. Enable the API

Inside IB Gateway:

1. `Configure → Settings → API → Settings`
2. Check **Enable ActiveX and Socket Clients**
3. Check **Read-Only API** (recommended — this toolkit is read-only by design)
4. **Socket port**: `4001` (live) or `4002` (paper). Match this to `IBKR_PORT` in your `.env`.
5. **Trusted IPs**: add `127.0.0.1`
6. Uncheck **Allow connections from localhost only** is NOT needed; leaving it checked is safer.
7. Click **OK** and restart Gateway.

<!-- screenshot: gateway-api-settings -->

### 3. Clone & install

```bash
git clone https://github.com/AlexLiu0130/ibkr-trader-toolkit.git
cd ibkr-trader-toolkit

python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
$EDITOR .env
```

Minimum fields to review (defaults usually work):

```ini
IBKR_HOST=127.0.0.1
IBKR_PORT=4001                  # 4002 if paper, 7497 if TWS paper
IBKR_CLIENT_ID_BASE=11
IBKR_MARKET_DATA_TYPE=1         # 3 if you have no real-time subscription
```

### 5. First call

With Gateway logged in:

```bash
python scripts/market_quote.py SPY
```

Expected output (JSON):

```json
{
  "symbol": "SPY",
  "last": 612.34,
  "bid": 612.31,
  "ask": 612.35,
  "volume": 28931402,
  "timestamp": "2026-05-12 10:14:22"
}
```

If you see this — you're done. Try `python scripts/portfolio_positions.py` next.

---

## 🤖 Claude Code Integration

This repo ships a `SKILL.md` so Claude Code can use it directly. Two ways to install:

### Option A — Symlink (recommended for development)

```bash
mkdir -p ~/.claude/skills
ln -s "$(pwd)" ~/.claude/skills/ibkr-trader-toolkit
```

Restart Claude Code. Ask: *"What's SPY trading at right now?"* — Claude will trigger `market_quote.py` instead of doing a web search.

### Option B — Plugin

If you use the Claude Code plugin system, point the marketplace at this repo and install `ibkr-trader-toolkit` from your plugin manager.

### Trigger phrases

The skill description (see `SKILL.md`) is tuned to fire whenever you mention any of: options strategy, position risk, Greeks, IV, wheel, earnings impact on options, P&L analysis, or stock price. You usually don't need to say "use IBKR".

---

## 📖 Command Reference

All scripts read `.env` automatically and accept `--help`. Every script prints JSON to stdout and logs to stderr — pipe stdout into `jq` or `--output file.json`.

| Script | One-liner | Example |
|---|---|---|
| `market_quote.py` | Real-time quote for one symbol | `python scripts/market_quote.py SPY` |
| `options_chain.py` | Option chain with Greeks | `python scripts/options_chain.py AAPL --dte-min 7 --dte-max 45` |
| `portfolio_positions.py` | Live positions + Greeks | `python scripts/portfolio_positions.py` |
| `options_analyzer.py` | Strategy recommender | `python scripts/options_analyzer.py SPY --outlook bullish --iv-context` |
| `options_daily.py` | End-of-day options report | `python scripts/options_daily.py --output ~/daily.json` |
| `pnl_analytics.py` | Realized P&L summary | `python scripts/pnl_analytics.py --days 30 --by symbol` |
| `earnings_calendar.py` | Next earnings + DTE | `python scripts/earnings_calendar.py AAPL ARM MU --days 30` |
| `risk_simulator.py` | Pre-trade Greeks preview | `python scripts/risk_simulator.py --add "AAPL 200 2026-06-26 P SELL 2"` |
| `technical_indicators.py` | RSI / MA / BB / ATR | `python scripts/technical_indicators.py NVDA --indicators rsi,ma,bb` |
| `wheel_tracker.py` | Wheel cycle journal | `python scripts/wheel_tracker.py --summary` |
| `alerts_monitor.py` | Threshold alerts | `python scripts/alerts_monitor.py --config ~/.ibkr_alerts.yaml` |
| `contracts.py` | (library) contract resolver | imported by other scripts |
| `ib_client.py` | (library) shared connection | imported by other scripts |

### Common patterns

**Save a chain then analyze offline** (avoids hammering IBKR):

```bash
python scripts/options_chain.py AAPL --output /tmp/aapl_chain.json
python scripts/options_analyzer.py AAPL --outlook neutral \
       --chain-file /tmp/aapl_chain.json --iv-context
```

**Cron a daily alerts check** (every weekday at 9:33am):

```cron
33 9 * * 1-5 cd /path/to/ibkr-trader-toolkit && \
    .venv/bin/python scripts/alerts_monitor.py >> ~/.ibkr_alerts.log 2>&1
```

**Risk-check before a trade**:

```bash
python scripts/risk_simulator.py \
    --add "SPY 600 2026-06-19 P SELL 1" \
    --add "SPY 580 2026-06-19 P BUY 1"
```

---

## 🔧 Configuration

All configuration lives in `.env` (copied from `.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `IBKR_HOST` | `127.0.0.1` | Gateway host. Almost always localhost. |
| `IBKR_PORT` | `4001` | `4001` Gateway live · `4002` Gateway paper · `7496` TWS live · `7497` TWS paper |
| `IBKR_CLIENT_ID_BASE` | `11` | Scripts add an offset (7–16); the resulting clientId must be unique across all your apps. |
| `IBKR_MARKET_DATA_TYPE` | `1` | `1` realtime · `2` frozen · `3` delayed (free) · `4` delayed-frozen |
| `FINNHUB_API_KEY` | *(unset)* | Optional. Falls back when `yahoo-earnings-calendar` is unavailable. Free at <https://finnhub.io>. |
| `IBKR_FLEX_TOKEN` | *(unset)* | Optional. IBKR Flex Web Service token for full historical P&L (beyond the ~2-day execution window). |
| `IBKR_FLEX_QUERY_ID` | *(unset)* | Optional. Flex Query ID. |

### ClientId offsets

Each script reserves a unique offset so they can coexist:

```
market_quote.py        offset 7   → clientId = base + 7
options_chain.py       offset 8
portfolio_positions.py offset 9
options_analyzer.py    offset 10
options_daily.py       offset 11
pnl_analytics.py       offset 12
risk_simulator.py      offset 13
technical_indicators   offset 14
wheel_tracker.py       offset 15
alerts_monitor.py      offset 16
```

With `IBKR_CLIENT_ID_BASE=11` (default), `market_quote.py` uses clientId `18`. If you run TWS/Gateway with **another** app on clientId `18`, raise the base.

### User data (outside the repo)

These files live in your home dir and are not committed:

- `~/.ibkr_wheel_journal.json` — wheel cycle entries
- `~/.ibkr_alerts.yaml` — alert rules
- `~/.ibkr_flex/*.csv` — Flex Statement exports

---

## ❓ Troubleshooting

Full guide: [`references/troubleshooting.md`](references/troubleshooting.md). The five issues that cover 90% of first-run problems:

### 1. `clientId X already in use`

Two scripts (or two copies of one script) hit IB Gateway with the same clientId. Either:
- Wait for the previous script to disconnect (usually a couple of seconds), **or**
- Raise `IBKR_CLIENT_ID_BASE` to a value no other app uses, **or**
- Confirm you don't have TWS *and* Gateway running at the same time on overlapping clientIds.

### 2. `Error 200: No security definition has been found`

The contract didn't resolve. Causes:
- Typo in the symbol (`SPYY` → `SPY`).
- Expired option date.
- Strike doesn't exist (e.g. `599.5` when only `599` and `600` are listed).
- Exchange routing — for some tickers you need to pass `--exchange ARCA` instead of `SMART`.

### 3. `Error 10091: subscription required`

You don't have a real-time market-data subscription for that exchange. Two fixes:
- Switch to delayed: `IBKR_MARKET_DATA_TYPE=3` in `.env`.
- Subscribe (Account Management → Settings → Market Data Subscriptions).

### 4. Connection refused / `TimeoutError`

Gateway isn't reachable. Checklist:
- Is Gateway running and **logged in**? (A logged-out Gateway doesn't accept connections.)
- Is the port in `.env` the same as Gateway's `API → Settings → Socket port`?
- Is `127.0.0.1` in **Trusted IPs**?
- Restart Gateway after changing API settings — they don't take effect live.

### 5. `modelGreeks is None`

The market is closed and there's no cached delayed-Greeks snapshot. Either wait for the next open, or set `IBKR_MARKET_DATA_TYPE=4` (delayed-frozen) and retry — delayed-frozen serves the last delayed snapshot from previous session.

---

## 📚 Advanced

| Topic | Doc |
|---|---|
| Full strategy library (20+ McMillan/Overby strategies with construction, IV preference, P&L profile) | [`references/strategies.md`](references/strategies.md) |
| Greeks primer (Delta, Gamma, Vega, Theta, Rho — practical interpretation) | [`references/greeks_primer.md`](references/greeks_primer.md) |
| Wheel strategy in depth (strike/DTE selection, roll-vs-assign decision tree) | [`references/wheel_strategy.md`](references/wheel_strategy.md) |
| All known errors and fixes | [`references/troubleshooting.md`](references/troubleshooting.md) |

---

## 🤝 Contributing

PRs and issues welcome. Keep it minimal:

- One concern per PR.
- New scripts should output JSON to stdout, log to stderr, and reserve a unique `CLIENT_ID_OFFSET`.
- No hard-coded paths — read configuration from `os.getenv()`.
- No buy/sell recommendations baked into the scripts; the toolkit produces *data*, the user (or Claude) makes decisions.

---

## 📜 License

[MIT](LICENSE). Use it, fork it, ship it.

---

## ⚠️ Disclaimer

**This software is for educational and personal use only. It is not financial advice.**

- The toolkit is **read-only by design**: it queries data and does Greeks math; it does not place orders. The repo never calls `placeOrder()`.
- All trading decisions are yours. Options trading involves substantial risk of loss and is not appropriate for every investor.
- The `options_analyzer.py` recommendations are educational mappings from outlook + risk profile → strategy templates. They do not consider your personal situation, capital, or tax position.
- Past performance shown by `pnl_analytics.py` does not predict future results.
- IBKR connectivity, market data quality, and third-party APIs (Yahoo, Finnhub) can fail. Verify critical numbers against your broker's UI before acting.

By using this software you agree that the authors and contributors are not liable for any trading losses, missed trades, or data errors.
