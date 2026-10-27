"""模拟实操账户：按成交记录重放，得到日度净值、持仓与现金。

设计要点
- 采用"份额记账"：账户创建即视为转入一笔起始资金，``units`` = 初始资金；后续转入/转出按当时
  净值折算份额，因此外部资金进出不会让收益率虚增。
- 「转入/转出」= 账户外部资金进出（加钱进来、取钱出去）；旧数据里的「入金/出金」含义相同，读取时兼容。
- 净值 = (持仓市值 + 现金) / units，费用直接计入成本，会压低净值。
- 成交日若为非交易日，自动顺延到下一个交易日生效。
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

SIDES = ("买入", "卖出", "转入", "转出")
MONEY_SIDES = ("转入", "转出", "入金", "出金")   # 外部资金进出（后两个是旧数据里的写法）


def load_acct(path: Path):
    """读取账户；文件不存在或损坏时返回 None。"""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_acct(acct: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(acct, ensure_ascii=False, indent=1), encoding="utf-8")


def replay(trades, prices: pd.DataFrame, capital: float, created: str):
    """按日重放成交。

    Args:
        trades: [{"date","asset","side","shares","price","fee"}, ...]
        prices: 日频收盘价面板（列名为资产 key）
        capital: 初始资金
        created: 起始日期 YYYY-MM-DD

    Returns:
        (daily, pos, cost, cash, units)
        daily: index=date, 列 = equity / nav / cash / market
    """
    capital = float(capital or 0)
    start = pd.Timestamp(created)
    idx = prices.index[prices.index >= start]
    if len(idx) == 0:
        # 建仓日晚于最新行情（例如周末建仓、行情只到上周五）：
        # 以最新可用交易日为唯一起点，仍能算出持仓与现金，只是暂时没有曲线
        idx = prices.index[-1:]

    # 成交日顺延到对应的交易日；晚于最新数据日的按最新可用日生效
    # （用户当天录入成交时数据往往还没更新到今天，不能直接丢弃）
    buckets: dict[pd.Timestamp, list] = {}
    for t in trades or []:
        try:
            d = pd.Timestamp(t["date"])
        except Exception:
            continue
        i = int(idx.searchsorted(d))
        i = min(i, len(idx) - 1)
        buckets.setdefault(idx[i], []).append(t)

    cash, units = capital, capital
    pos: dict[str, float] = {}
    cost: dict[str, float] = {}
    rows, last_nav = [], 1.0

    for d in idx:
        for t in buckets.get(d, []):
            a = t.get("asset")
            sh = float(t.get("shares", 0) or 0)
            px = float(t.get("price", 0) or 0)
            fee = float(t.get("fee", 0) or 0)
            side = t.get("side")

            if side == "买入":
                cash -= sh * px + fee
                prev = pos.get(a, 0.0)
                if prev + sh > 0:
                    cost[a] = (prev * cost.get(a, 0.0) + sh * px + fee) / (prev + sh)
                pos[a] = prev + sh
            elif side == "卖出":
                cash += sh * px - fee
                pos[a] = pos.get(a, 0.0) - sh
            elif side in ("转入", "入金"):
                base = last_nav if last_nav > 0 else 1.0
                units += sh / base
                cash += sh
            elif side in ("转出", "出金"):
                base = last_nav if last_nav > 0 else 1.0
                units = max(1e-9, units - sh / base)
                cash -= sh

        mv = 0.0
        for a, sh in pos.items():
            if sh and a in prices.columns:
                v = prices.at[d, a]
                if pd.notna(v):
                    mv += sh * float(v)
        eq = cash + mv
        nav = eq / units if units > 0 else 1.0
        last_nav = nav
        rows.append({"date": d, "equity": eq, "nav": nav, "cash": cash, "market": mv})

    daily = pd.DataFrame(rows).set_index("date")
    return daily, pos, cost, cash, units


def fund_pnl(trades, nav: pd.Series) -> pd.Series:
    """单只基金的累计盈亏曲线（元）—— 口径对齐支付宝「累计盈亏」。

    累计盈亏 = 当前持仓市值 + 累计卖出净额 − 累计买入总额（买入含手续费、卖出扣手续费）。
    所以卖出后曲线不会掉下来（已经落袋的收益还在），而「持有收益」只算手上这一部分。
    转入/转出是账户层面的钱，与单只基金无关，这里不参与。

    Args:
        trades: 这只基金自己的成交 [{"date","side","shares","nav","fee"}]，只认买入 / 卖出
        nav: 这只基金的单位净值序列（DatetimeIndex）
    """
    nav = pd.Series(nav).dropna().sort_index()
    if nav.empty:
        return pd.Series(dtype=float)
    rows = [t for t in (trades or [])
            if t.get("side") in ("买入", "卖出") and float(t.get("shares") or 0) > 0]
    if not rows:
        return pd.Series(dtype=float)

    buckets: dict[pd.Timestamp, list] = {}
    for t in rows:
        try:
            d = pd.Timestamp(t.get("date"))
        except Exception:  # noqa: BLE001
            continue
        i = min(int(nav.index.searchsorted(d)), len(nav) - 1)   # 非交易日顺延到下一个有净值的交易日
        buckets.setdefault(nav.index[i], []).append(t)
    if not buckets:
        return pd.Series(dtype=float)

    start = min(buckets)
    out_cash = in_cash = shares = 0.0
    out: dict[pd.Timestamp, float] = {}
    for d, px_d in zip(nav.index, nav.values):
        if d < start:
            continue
        for t in buckets.get(d, []):
            sh, fee = float(t.get("shares") or 0), float(t.get("fee") or 0)
            px = float(t.get("nav") or 0) or float(px_d)     # 没记净值的成交按当日净值算
            if t.get("side") == "买入":
                out_cash += sh * px + fee
                shares += sh
            else:
                in_cash += sh * px - fee
                shares -= sh
        out[d] = shares * float(px_d) + in_cash - out_cash
    return pd.Series(out, dtype=float)


def stats(daily: pd.DataFrame) -> dict:
    """净值曲线指标：累计收益、最大回撤。"""
    if daily is None or not len(daily):
        return {"nav": 1.0, "ret": 0.0, "mdd": 0.0}
    nav = daily["nav"]
    return {
        "nav": float(nav.iloc[-1]),
        "ret": float(nav.iloc[-1] - 1),
        "mdd": float((nav / nav.cummax() - 1).min()),
    }
