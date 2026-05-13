"""
财报日历查询 — 拉取指定标的的下一次财报日期，可选与持仓合并标记 at-risk 期权。

数据源（按优先级）：
  - Nasdaq /api/calendar/earnings（公开，无需 key，按日期拉）
  - Finnhub /calendar/earnings（备，若 FINNHUB_API_KEY 已设置）

用法：
  python earnings_calendar.py AAPL MSFT NVDA
  python earnings_calendar.py AAPL --days 14
  python earnings_calendar.py --portfolio-file /tmp/portfolio.json --output /tmp/earn.json
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
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


def fetch_nasdaq_range(days: int) -> dict[str, date]:
    """拉取未来 days 天所有 earnings，返回 {symbol: earnings_date} 字典。"""
    today = date.today()
    result: dict[str, date] = {}
    for offset in range(days + 1):
        d = today + timedelta(days=offset)
        url = f"https://api.nasdaq.com/api/calendar/earnings?date={d.isoformat()}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        })
        try:
            data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        except Exception as e:
            log(f"  Nasdaq {d}: {e}")
            continue
        rows = (data.get("data") or {}).get("rows") or []
        for row in rows:
            sym = (row.get("symbol") or "").strip().upper()
            if sym and sym not in result:
                result[sym] = d
    return result


def fetch_finnhub_one(symbol: str, days: int) -> dict | None:
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
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
    today = date.today()

    log("  拉取 Nasdaq 财报日历 ...")
    nasdaq_map = fetch_nasdaq_range(args.days)
    log(f"  Nasdaq 返回 {len(nasdaq_map)} 个未来财报")

    earnings = []
    for sym in sorted(symbols):
        sym_u = sym.upper()
        edate = nasdaq_map.get(sym_u)
        if edate:
            earnings.append({
                "symbol": sym,
                "next_earnings_date": edate.isoformat(),
                "days_until": (edate - today).days,
                "fiscal_period": None,
                "source": "nasdaq",
            })
            continue
        # Fallback: Finnhub
        info = fetch_finnhub_one(sym, args.days)
        if info:
            earnings.append(info)
        else:
            earnings.append({
                "symbol": sym,
                "next_earnings_date": None,
                "days_until": None,
                "fiscal_period": None,
                "source": None,
            })

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
