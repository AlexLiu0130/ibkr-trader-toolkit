"""
财报日历查询 — 拉取指定标的的下一次财报日期，可选与持仓合并标记 at-risk 期权。

数据源：
  - yahoo_earnings_calendar (主)
  - Finnhub /calendar/earnings (备，若 FINNHUB_API_KEY 已设置)

用法：
  python earnings_calendar.py AAPL MSFT NVDA
  python earnings_calendar.py AAPL --days 14
  python earnings_calendar.py --portfolio-file /tmp/portfolio.json --output /tmp/earn.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, date, timedelta


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _parse_date(val) -> date | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        try:
            return datetime.utcfromtimestamp(val).date()
        except Exception:
            return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


def fetch_yahoo(symbol: str, days: int) -> dict | None:
    try:
        from yahoo_earnings_calendar import YahooEarningsCalendar
    except ImportError:
        log("  ⚠️  yahoo_earnings_calendar 未安装")
        return None

    yec = YahooEarningsCalendar()
    try:
        entries = yec.get_earnings_of(symbol) or []
    except Exception as e:
        log(f"  Yahoo {symbol}: {e}")
        return None

    today = date.today()
    cutoff = today + timedelta(days=days)
    future = []
    for entry in entries:
        edate = _parse_date(entry.get("startdatetime") or entry.get("date"))
        if edate and today <= edate <= cutoff:
            future.append((edate, entry))
    if not future:
        return None
    future.sort(key=lambda x: x[0])
    edate, entry = future[0]
    return {
        "symbol": symbol,
        "next_earnings_date": edate.isoformat(),
        "days_until": (edate - today).days,
        "fiscal_period": entry.get("epsestimate"),
        "source": "yahoo",
    }


def fetch_finnhub(symbol: str, days: int) -> dict | None:
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        return None
    try:
        import urllib.parse
        import urllib.request
    except ImportError:
        return None

    today = date.today()
    cutoff = today + timedelta(days=days)
    params = urllib.parse.urlencode({
        "symbol": symbol,
        "from": today.isoformat(),
        "to": cutoff.isoformat(),
        "token": api_key,
    })
    url = f"https://finnhub.io/api/v1/calendar/earnings?{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        log(f"  Finnhub {symbol}: {e}")
        return None

    items = data.get("earningsCalendar", [])
    if not items:
        return None
    items.sort(key=lambda i: i.get("date", ""))
    item = items[0]
    edate = _parse_date(item.get("date"))
    if not edate:
        return None
    return {
        "symbol": symbol,
        "next_earnings_date": edate.isoformat(),
        "days_until": (edate - today).days,
        "fiscal_period": f"{item.get('year')}Q{item.get('quarter')}",
        "source": "finnhub",
    }


def fetch_one(symbol: str, days: int) -> dict:
    info = fetch_yahoo(symbol, days)
    if info is None:
        info = fetch_finnhub(symbol, days)
    if info is None:
        return {
            "symbol": symbol,
            "next_earnings_date": None,
            "days_until": None,
            "fiscal_period": None,
            "source": None,
        }
    return info


def at_risk_positions(portfolio: dict, earnings: list[dict]) -> list[dict]:
    """找出 DTE 包含财报日的期权仓位。"""
    earn_map = {e["symbol"]: e for e in earnings if e.get("days_until") is not None}
    at_risk = []
    for pos in portfolio.get("positions", []):
        if pos.get("sec_type") != "OPT":
            continue
        sym = pos.get("symbol")
        info = earn_map.get(sym)
        if not info:
            continue

        exp = pos.get("expiration")
        try:
            if exp and "-" in exp:
                exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
            elif exp:
                exp_date = datetime.strptime(exp, "%Y%m%d").date()
            else:
                continue
        except Exception:
            continue

        dte = (exp_date - date.today()).days
        if 0 <= info["days_until"] <= dte:
            at_risk.append({
                "symbol": sym,
                "strike": pos.get("strike"),
                "right": pos.get("right"),
                "expiration": exp_date.isoformat(),
                "dte": dte,
                "earnings_date": info["next_earnings_date"],
                "earnings_days_until": info["days_until"],
                "position": pos.get("position"),
            })
    return at_risk


def main() -> int:
    parser = argparse.ArgumentParser(description="财报日历查询")
    parser.add_argument("symbols", nargs="*", help="标的列表")
    parser.add_argument("--days", type=int, default=30, help="未来 N 天 (default 30)")
    parser.add_argument("--portfolio-file", help="持仓 JSON 文件路径")
    parser.add_argument("--output", help="输出文件路径（默认 stdout）")
    args = parser.parse_args()

    symbols = set(args.symbols)

    portfolio = None
    if args.portfolio_file:
        try:
            with open(args.portfolio_file, encoding="utf-8") as f:
                portfolio = json.load(f)
            for pos in portfolio.get("positions", []):
                if pos.get("symbol"):
                    symbols.add(pos["symbol"])
        except Exception as e:
            log(f"⚠️  无法读取 {args.portfolio_file}: {e}")

    if not symbols:
        log("❌ 没有标的可查询")
        return 1

    log(f"🔄 查询 {len(symbols)} 个标的的财报 ({args.days} 天窗口) ...")
    earnings = [fetch_one(s, args.days) for s in sorted(symbols)]

    risk = at_risk_positions(portfolio, earnings) if portfolio else []

    result = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window_days": args.days,
        "symbols": earnings,
        "at_risk_positions": risk,
    }

    json_str = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        tmp = args.output + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json_str)
        os.rename(tmp, args.output)
        log(f"📁 已保存到 {args.output}")
    else:
        print(json_str)

    found = sum(1 for e in earnings if e["next_earnings_date"])
    log(f"✅ 完成: {found}/{len(earnings)} 找到财报日期, {len(risk)} 个 at-risk 期权")
    return 0


if __name__ == "__main__":
    sys.exit(main())
