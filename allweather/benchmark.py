"""基准曲线：用来回答「我的实操跟理论差多少，差在哪」。

两条基准，用途不同，不要混：

1. 策略理论净值（``strategy_curve``）
   直接读 output/nv_curves.csv —— ``py main.py`` 全量回测跑出来的净值，用的就是
   ETF_META 那 9 只项目默认基金的真实净值（ETF 上市前的历史段才用指数/汇率/商品
   proxy 拼接），每月最后一个交易日按当时信号动态调权再平衡。回测报告里的
   CAGR / MDD / Sharpe 由 perf_metrics() 从同一条曲线算出，不是另一套模型假设。
   全量回测只跑到 BACKTEST_END，而行情 CSV 会继续更新；因此本模块会用回测
   最后一期目标权重（无前视）+ 最新资产行情，把净值延长到数据最新日，
   避免 bench_index 把过期净值 ffill 冻结、把新入金的盈亏稀释成一条 0 线。

2. 同期对照（``replay_target``，页面上叫「项目默认基金」）
   从我的建仓日起，用**同一批默认基金**、**当前这套固定目标权重**、每月最后一个
   交易日再平衡，重放出来的净值。它和我的账户同时起步、同样的权重，
   唯一的差别是我换了基金、以及我的调仓时点和费用 —— 这正是想量出来的东西。

三者关系：我的账户(真实结果) → 项目默认基金(标准执行) → 策略理论(回测净值)，
相邻两层的差分别是「选基/执行/费用」和「历史动态权重 vs 当前固定权重 + 起算区间」。
三条线用的是同一批基金，不是「真实基金 vs 虚构模型」。

为什么不用当前权重一直持有：策略是每月再平衡的，用固定权重持有会高估或低估。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import ROOT, ETF_META

# 默认 9 只都是场内 ETF，按佣金万 1.5 双边计（与回测引擎 fee_rate 同口径）
COMMISSION = 1.5e-4


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
            cur_w = shares * cur / nav
            turn = 0.5 * float(np.abs(w - cur_w).sum())
            if turn > 1e-9:
                nav *= 1.0 - turn * 2.0 * COMMISSION
                out[-1] = nav
            shares = w * nav / cur
        prev = cur
    return pd.Series(out, index=px.index, name="bench")


def replay_target(strategy_weights: dict[str, float], start, prices: pd.DataFrame | None = None,
                  navs: dict[str, pd.Series] | None = None,
                  nav_getter=None) -> pd.Series:
    """用项目默认基金重放「如果一直按目标权重买默认基金」。

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


def replay_advice(strategy_col: str, start, rebal_dates, nav_getter=None) -> pd.Series:
    """默认 9 只 ETF，按「我自己的调仓日」重放，权重取当期建议权重。

    和 ``_replay`` 的唯一区别：调仓日不是月末，而是传入的日期（账户里那几笔成交日）；
    每个调仓日拿的是 weight_history_*.csv 里 **该日或之前最近一期**的建议权重，
    与策略理论（每月末按当时信号算权重）口径一致，只是把「月末」换成「我下单那天」。

    Args:
        strategy_col: 回测列名，如 "V3-B 保守增强(20d)_100% RP"
        start: 建仓日
        rebal_dates: 我的实际调仓日（成交日期，可重复）
        nav_getter: callable(code) -> Series，按基金代码取净值（与页面展示同口径）

    Returns:
        净值 Series（起点 1.0），日期 = 资产行情交易日
    """
    key = strategy_col.rsplit("_", 1)[0]
    fp = ROOT / "output" / _WEIGHT_FILES.get(key, "")
    if not fp.exists():
        return pd.Series(dtype=float)
    try:
        wh = pd.read_csv(fp, index_col=0, parse_dates=True).sort_index()
    except Exception:  # noqa: BLE001
        return pd.Series(dtype=float)
    if wh.empty:
        return pd.Series(dtype=float)
    last_w = wh.iloc[-1].reindex(wh.columns).fillna(0.0).astype(float)
    assets = [c for c in wh.columns if float(last_w[c] or 0) > 0] or list(wh.columns)

    panel = None
    if nav_getter is not None:
        navs = {}
        for a in assets:
            code = ETF_META.get(a, {}).get("code", "")
            ser = nav_getter(code) if code else None
            if ser is not None and len(ser):
                navs[a] = ser
        if navs:
            panel = pd.DataFrame(navs).sort_index().ffill()
    if panel is None or not len(panel):
        panel = load_default_prices()
        if panel is None or not len(panel):
            return pd.Series(dtype=float)
    px = panel.dropna(how="all")
    if start is not None:
        px = px.loc[px.index >= pd.Timestamp(start)]
    cols = [c for c in assets if c in px.columns]
    if len(px) < 2 or not cols:
        return pd.Series(dtype=float)
    px = px[cols].ffill()
    reb = {pd.Timestamp(d) for d in (rebal_dates or [])}

    def weights_asof(day):
        w = wh.loc[:day].iloc[-1] if len(wh.loc[:day]) else wh.iloc[0]
        w = w.reindex(cols).fillna(0.0).astype(float)
        return w.values / w.values.sum() if w.values.sum() > 0 else None

    nav, out, shares = 1.0, [], None
    for i in range(len(px)):
        cur = px.iloc[i].values
        if i:
            nav = float(np.sum(shares * cur))
        out.append(nav)
        if shares is None or px.index[i] in reb:
            w = weights_asof(px.index[i])
            if w is not None and nav > 0:
                if shares is not None:
                    cur_w = shares * cur / nav
                    turn = 0.5 * float(np.abs(w - cur_w).sum())
                    if turn > 1e-9:
                        nav *= 1.0 - turn * 2.0 * COMMISSION
                        out[-1] = nav
                shares = w * nav / cur
    return pd.Series(out, index=px.index, name="advice")

def load_default_prices() -> pd.DataFrame:
    """项目默认基金的价格面板（列 = 资产 key）。"""
    files = {
        "hs300": "hs300", "us_sp500": "us_sp500", "credit": "bond_credit",
        "bond_10y": "bond_10y_etf", "bond_30y": "bond_30y_etf", "gold": "gold",
        "nonferr": "nonferr", "ene": "ene",
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


# nv_curves.csv 列名前缀 → 回测末期权重命名文件
_WEIGHT_FILES = {
    "V3-B 风险平价(20d)": "weight_history_V3-B_风险平价20d.csv",
    "V3-B 保守增强(20d)": "weight_history_V3-B_保守增强20d.csv",
    "V3c 多元": "weight_history_V3c_多元.csv",
}


def _extend_to_latest(s: pd.Series, name: str) -> pd.Series:
    """把回测净值延长到行情最新日。

    nv_curves.csv 由全量回测生成，截止 BACKTEST_END；行情 CSV 会持续更新。
    不延长的话，bench_index 对截止日之后只能 ffill 出一个常数净值，
    这期间新入金买到的份额盈亏恒为 0，折算收益率被稀释成一条 0 线。
    这里用回测最后一期目标权重（当时已可得，无前视）按最新资产收益继续跟踪。
    """
    key = name.rsplit("_", 1)[0]
    fp = ROOT / "output" / _WEIGHT_FILES.get(key, "")
    px = load_default_prices()
    if not fp.exists() or px.empty or len(s) < 2:
        return s
    try:
        wh = pd.read_csv(fp, index_col=0, parse_dates=True)
    except Exception:  # noqa: BLE001
        return s
    if wh.empty:
        return s
    w = wh.iloc[-1].reindex(px.columns).fillna(0.0).astype(float)
    if float(w.sum()) <= 0:
        return s
    w = w / w.sum()
    ext = px.loc[px.index > s.index[-1]]
    if not len(ext):
        return s
    base = px.loc[px.index <= s.index[-1]]
    if base.empty:
        return s
    px2 = pd.concat([base.tail(1), ext])
    r = px2.pct_change().fillna(0.0)
    port_r = (r * w.values).sum(axis=1).loc[ext.index]
    growth = (1.0 + port_r).cumprod()
    return pd.concat([s, s.iloc[-1] * growth])


def strategy_curve(name: str, start=None) -> pd.Series | None:
    """回测理论净值（output/nv_curves.csv），先延长到最新行情日再按 start 截取。"""
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
    if len(s) < 2:
        return None
    s = _extend_to_latest(s, name)
    if start is not None:
        s = s.loc[s.index >= pd.Timestamp(start)]
    return s if len(s) > 1 else None
