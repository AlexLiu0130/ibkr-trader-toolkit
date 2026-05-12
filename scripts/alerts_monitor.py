"""
告警监控 — 从 ~/.ibkr_alerts.yaml 读规则，对每个标的拉行情/期权数据并求值条件。

可在 condition 表达式中使用的变量：
  delta            期权 delta（持仓总和或拟议合约）
  iv               隐含波动率
  price            标的现价
  dte              到期天数（找匹配持仓）
  unrealized_pnl   组合中该标的的未实现盈亏

示例 ~/.ibkr_alerts.yaml：
  - symbol: AAPL
    condition: "price < 180 or unrealized_pnl < -500"
    on_trigger: "考虑展期或平仓 short put"
  - symbol: SPY
    condition: "iv > 0.25"
    on_trigger: "卖方机会出现"
  - symbol: NVDA
    condition: "abs(delta) > 100 and dte < 14"
    on_trigger: "delta 过大且临近到期"

用法：
  python alerts_monitor.py
  python alerts_monitor.py --config ~/.ibkr_alerts.yaml --output /tmp/alerts.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path

from contracts import resolve
from ib_client import ib_connect, log, qualify, req_historical_safe
from portfolio_positions import fetch_positions

CLIENT_ID_OFFSET = 16
DEFAULT_CONFIG = Path(os.path.expanduser("~/.ibkr_alerts.yaml"))


def _load_yaml(path: Path) -> list[dict]:
    if not path.exists():
        log(f"⚠️  配置文件不存在: {path}")
        return []
    try:
        import yaml  # type: ignore
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
        return data if isinstance(data, list) else []
    except ImportError:
        # 极简 fallback：每条规则三行 "- symbol: X" / "  condition: ..." / "  on_trigger: ..."
        rules: list[dict] = []
        cur: dict = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("- "):
                if cur:
                    rules.append(cur)
                cur = {}
                stripped = stripped[2:]
            if ":" in stripped:
                k, _, v = stripped.partition(":")
                cur[k.strip()] = v.strip().strip('"').strip("'")
        if cur:
            rules.append(cur)
        return rules


def _spot_price(ib, symbol: str) -> float | None:
    try:
        contract = resolve(symbol)
        q = qualify(ib, contract)
        bars = req_historical_safe(
            ib, q,
            endDateTime="",
            durationStr="2 D",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )
        if bars:
            return round(float(bars[-1].close), 4)
    except Exception as e:
        log(f"  {symbol} spot 获取失败: {e}")
    return None


def gather_values(ib, symbol: str, portfolio: dict) -> dict:
    """聚合该标的的 price / delta / iv / dte / unrealized_pnl。"""
    sym_positions = [p for p in portfolio.get("positions", [])
                     if p.get("symbol") == symbol]
    opt_positions = [p for p in sym_positions if p.get("sec_type") == "OPT"]

    # delta：仓位 delta 之和
    delta = 0.0
    iv_vals = []
    min_dte = None
    for p in opt_positions:
        pg = p.get("position_greeks") or {}
        if pg.get("delta") is not None:
            delta += pg["delta"]
        g = p.get("greeks") or {}
        if g.get("iv") is not None:
            iv_vals.append(g["iv"])
        exp = p.get("expiration")
        try:
            exp_date = datetime.strptime(exp, "%Y%m%d").date()
            dte = (exp_date - date.today()).days
            min_dte = dte if min_dte is None else min(min_dte, dte)
        except Exception:
            pass

    # 股票 delta 计入
    for p in sym_positions:
        if p.get("sec_type") == "STK":
            delta += float(p.get("position") or 0)

    iv = round(sum(iv_vals) / len(iv_vals), 4) if iv_vals else None

    unrealized = sum((p.get("unrealized_pnl") or 0) for p in sym_positions)

    price = None
    for p in opt_positions:
        g = p.get("greeks") or {}
        if g.get("und_price"):
            price = g["und_price"]
            break
    if price is None:
        price = _spot_price(ib, symbol)

    return {
        "price": price,
        "delta": round(delta, 2),
        "iv": iv,
        "dte": min_dte,
        "unrealized_pnl": round(unrealized, 2),
    }


_SAFE_BUILTINS = {"abs": abs, "min": min, "max": max, "round": round, "len": len}


def evaluate(condition: str, values: dict) -> tuple[bool, str | None]:
    safe_globals = {"__builtins__": _SAFE_BUILTINS}
    safe_locals = {k: (v if v is not None else float("nan")) for k, v in values.items()}
    try:
        return bool(eval(condition, safe_globals, safe_locals)), None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    parser = argparse.ArgumentParser(description="告警监控")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="规则文件路径 (default ~/.ibkr_alerts.yaml)")
    parser.add_argument("--output", help="输出文件路径（默认 stdout）")
    args = parser.parse_args()

    config_path = Path(os.path.expanduser(args.config))
    rules = _load_yaml(config_path)
    if not rules:
        log(f"❌ 无可用规则: {config_path}")
        result = {
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "rules_evaluated": 0,
            "triggers": [],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    log(f"🔄 评估 {len(rules)} 条规则 ...")

    triggers = []
    evaluated = 0
    try:
        with ib_connect(client_id_offset=CLIENT_ID_OFFSET) as ib:
            portfolio = fetch_positions(ib)
            cache: dict[str, dict] = {}
            for rule in rules:
                sym = rule.get("symbol")
                cond = rule.get("condition")
                if not sym or not cond:
                    continue
                if sym not in cache:
                    cache[sym] = gather_values(ib, sym, portfolio)
                values = cache[sym]

                fired, err = evaluate(cond, values)
                evaluated += 1
                if err:
                    log(f"  ⚠️  {sym} 规则错误: {err}")
                    continue
                if fired:
                    triggers.append({
                        "symbol": sym,
                        "condition": cond,
                        "current_values": values,
                        "message": rule.get("on_trigger", "triggered"),
                    })
    except Exception as e:
        log(f"❌ 失败: {e}")
        return 1

    result = {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "config_path": str(config_path),
        "rules_evaluated": evaluated,
        "triggers": triggers,
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

    log(f"✅ 完成: {len(triggers)}/{evaluated} 触发")
    return 0


if __name__ == "__main__":
    sys.exit(main())
