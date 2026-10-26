"""基准曲线：用来回答「我的实操跟理论差多少，差在哪」。

两条基准，用途不同，不要混：

1. 策略理论净值（``strategy_curve``）
   直接读 output/nv_curves.csv —— 回测跑出来的、用项目默认 8 个代码的长历史曲线。
   它代表的是「策略在历史上应该赚多少」，和我的建仓日期无关。

2. 同期对照（``replay_target``，页面上叫「项目默认基金」）
   从我的建仓日起，用**项目默认的 8 个基金代码**、**当前这套目标权重**、每月最后一个
   交易日再平衡，重放出来的净值。它和我的账户同时起步、同样的权重，
   唯一的差别是我换了基金、以及我的调仓时点和费用 —— 这正是想量出来的东西。

为什么不用当前权重一直持有：策略是每月再平衡的，用固定权重持有会高估或低估。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import ROOT, ETF_META


def _replay(prices: pd.DataFrame, weights: dict[str, float], start, rebal="ME") -> pd.Series:
    """月末再平衡重放：每天按持仓涨跌，月末复位到目标权重。"""
    px = prices.dropna(how="all")
    if start is not None:
        px = px.loc[px.index >= pd.Timestamp(start)]
    if len(px) < 2:
        return pd.Series(dtype=float)
    cols = [c for c in weights if c in px.columns and float(weights[c] or 0) > 0]
    if not cols:
        return pd.Series(dtype=float)
    w = np.array([float(weights[c]) for c in cols], dtype=float)
    w = w / w.sum()
    px = px[cols].ffill()
    reb_days = set(px.resample(rebal).last().dropna().index)
    shares = w / px.iloc[0].values
    nav, out = 1.0, []
    prev = px.iloc[0].values
    for i in range(len(px)):
        cur = px.iloc[i].values
        if i:
            nav = float(np.sum(shares * cur))
        out.append(nav)
        if px.index[i] in reb_days and nav > 0:
            shares = w * nav / cur
        prev = cur
    return pd.Series(out, index=px.index, name="bench")


def replay_target(strategy_weights: dict[str, float], start, prices: pd.DataFrame | None = None,
                  navs: dict[str, pd.Series] | None = None,
                  nav_getter=None) -> pd.Series:
    """用项目默认 8 个代码重放「如果一直按目标权重买默认基金」。

    Args:
        strategy_weights: 资产 key → 目标权重（原始口径，8 个资产）
        start: 起始日期（我的建仓日）
        prices: 资产价格面板（列 = 资产 key）；不给就读 data/*.csv
        navs: 可选，{资产 key: 净值序列}，优先于 prices
        nav_getter: 可选，callable(code) -> Series；用它按基金代码取净值
                    （data/nav_detail 的口径和页面展示一致，优先用它而不是 data/*.csv）

    Returns:
        净值 Series（起点 1.0）
    """
    if not isinstance(strategy_weights, dict):
        strategy_weights = dict(strategy_weights)     # 调用方传进来的可能是 pandas Series
    if not navs and nav_getter is not None:
        navs = {s: nav_getter(ETF_META.get(s, {}).get("code", ""))
                for s in strategy_weights if float(strategy_weights[s] or 0) > 0}
        navs = {k: v for k, v in navs.items() if v is not None and len(v)}
    if not navs:
        navs = default_navs(list(strategy_weights))
    if navs:
        panel = pd.DataFrame({k: v for k, v in navs.items() if len(v)}).sort_index().ffill()
        if len(panel.dropna(how="all")) > 1:
            return _replay(panel.dropna(how="all"), strategy_weights, start)
    if prices is None:
        prices = load_default_prices()
    if prices is None or not len(prices):
        return pd.Series(dtype=float)
    return _replay(prices, strategy_weights, start)


def load_default_prices() -> pd.DataFrame:
    """项目默认 8 个代码的价格面板（列 = 资产 key）。"""
    files = {
        "hs300": "hs300", "us_sp500": "us_sp500", "credit": "bond_credit",
        "bond_10y": "bond_10y_etf", "bond_30y": "bond_30y_etf", "gold": "gold",
        "nonferr": "nonferr", "wti": "wti",
    }
    cols = {}
    for key, fn in files.items():
        fp = ROOT / "data" / f"{fn}.csv"
        if fp.exists():
            df = pd.read_csv(fp, parse_dates=["date"], index_col="date")
            cols[key] = df["close"]
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols).sort_index().ffill()


def default_navs(slots: list[str]) -> dict[str, pd.Series]:
    """项目默认代码的复权净值（场内外一致口径），用于同期对照。"""
    try:
        import importlib
        FL = importlib.import_module("fund_lookup")
    except ImportError:  # pragma: no cover
        return {}
    out = {}
    for s in slots:
        code = ETF_META.get(s, {}).get("code", "")
        if not code:
            continue
        try:
            nav = FL.build_nav(code)
        except Exception:  # noqa: BLE001
            nav = None
        if nav is not None and len(nav):
            out[s] = nav
    return out


def strategy_curve(name: str, start=None) -> pd.Series | None:
    """回测理论净值（output/nv_curves.csv），可选从 start 起归一。"""
    fp = ROOT / "output" / "nv_curves.csv"
    if not fp.exists():
        return None
    try:
        df = pd.read_csv(fp, index_col=0, parse_dates=True)
    except Exception:  # noqa: BLE001
        return None
    if name not in df.columns:
        return None
    s = df[name].dropna()
    if start is not None:
        s = s.loc[s.index >= pd.Timestamp(start)]
    return s if len(s) > 1 else None
