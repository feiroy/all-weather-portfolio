"""这套策略能不能稳定拿到 8%？—— 用纯真实基金数据给确定性结论。

    PYTHONPATH=. ./myenv/bin/python experiments/_real_pool_8pct.py

不做任何拼接。资产池 = 方案 A（5 只真实基金，2013-07 起 13.3 年）：
    hs300 160706 / us_sp500 050025 / credit 000032 / bond_10y 511010 / gold 518880

四道检验：
  1. 已实现：13.3 年真实净值跑出来的年化
  2. 滚动窗口：任意连续 3 年 / 5 年入场，年化落在哪，≥8% 的占比
  3. Block bootstrap：5 年持有期年化的分布，P(≥8%)、P(亏损)
  4. 成本：按实际换手率扣双边交易成本，看净年化
  5. 归因：把黄金抽掉 / 把最好的两年抽掉，年化掉到多少 —— 判断 8% 靠的是能力还是行情
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from allweather import pipeline as P      # noqa: E402
from experiments._real_pool_abc import build_rets, stats, POOLS   # noqa: E402

STRATS = ("V3-B 保守增强", "V3-B 风险平价", "V3c 多元")
POOL = [p for p in POOLS if p["tag"] == "A"][0]

# 交易成本假设（单边）
COST_ETF = 0.00025          # 场内 ETF 佣金 万2.5
SLIP = 0.0005               # 买卖价差 + 滑点 5bp
COST_ROUND = 2 * (COST_ETF + SLIP)   # 一次「卖掉 + 买进」= 0.15%


def run(rets: pd.DataFrame, keys, buckets, track=False):
    P.STRATEGY_ASSETS = {k: list(keys) for k in STRATS}
    P.V3B_RP_BUCKETS = {k: list(v) for k, v in buckets.items()}
    r = rets[[c for c in keys if c in rets.columns]]
    out = {}
    for st in STRATS:
        kw = {"assets": list(keys)} if st == "V3c 多元" else {}
        if track:
            kw.update(track_weights=True)
        out[st] = P.run_strategy_backtest(r, st, "monthly", **kw)
    return out


def roll_annual(nv: pd.Series, years: int) -> pd.Series:
    """任意连续 N 年入场，年化落在哪。按日历滚动，不是按行数。"""
    out = {}
    for i, d0 in enumerate(nv.index):
        end = d0 + pd.DateOffset(years=years)
        if end > nv.index[-1]:
            break
        seg = nv.loc[d0:end]
        if len(seg) < 60:
            continue
        yrs = (seg.index[-1] - seg.index[0]).days / 365.25
        out[d0] = (seg.iloc[-1] / seg.iloc[0]) ** (1 / yrs) - 1
    return pd.Series(out) * 100


def block_bootstrap(r: pd.Series, horizon_days=252 * 5, n=5000, block=21, seed=42):
    rng = np.random.default_rng(seed)
    x = r.dropna().to_numpy()
    n_blk = int(np.ceil(horizon_days / block))
    starts = rng.integers(0, len(x) - block, size=(n, n_blk))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n, -1)[:, :horizon_days]
    sims = np.cumprod(1 + x[idx], axis=1)[:, -1]
    return (sims ** (252 / horizon_days) - 1) * 100


def pct(s: pd.Series, q):
    return float(np.percentile(s, q))


def main():
    rets = build_rets(POOL["spec"])
    keys = list(POOL["spec"])
    print(f"真实池 {len(keys)} 只  {rets.index[0]:%Y-%m-%d} ~ {rets.index[-1]:%Y-%m-%d}  "
          f"{len(rets)} 个交易日\n")

    res = run(rets, keys, POOL["buckets"])
    res_t = run(rets, keys, POOL["buckets"], track=True)

    # ---------------------------------------------------------- 1. 已实现
    print("═" * 96)
    print("① 已实现（13.3 年纯真实净值，月频调仓，零成本）")
    print("═" * 96)
    print(f"{'策略':14s}{'年化':>8s}{'回撤':>9s}{'波动':>8s}{'夏普':>7s}{'Calmar':>8s}"
          f"{'终值':>7s}  分年")
    print("─" * 96)
    for st in STRATS:
        r = res[st]
        s = stats(r.nv)
        yr = r.nv.groupby(r.nv.index.year).last().pct_change().dropna() * 100
        print(f"{st:14s}{s['cagr']:7.2f}%{s['mdd']:8.2f}%{s['vol']:7.2f}%{s['sharpe']:7.2f}"
              f"{s['calmar']:8.2f}{r.nv.iloc[-1]:7.2f}  "
              + " ".join(f"{y}:{v:+.1f}" for y, v in yr.items()))

    # ---------------------------------------------------------- 2. 滚动窗口
    print("\n" + "═" * 96)
    print("② 任意连续窗口入场 · 年化分布（%）")
    print("═" * 96)
    print(f"{'策略':14s}{'窗口':6s}{'样本':>5s}{'最差':>8s}{'25%':>8s}{'中位':>8s}"
          f"{'75%':>8s}{'最好':>8s}{'≥8%占比':>9s}")
    print("─" * 96)
    for st in STRATS:
        for yr in (3, 5):
            s = roll_annual(res[st].nv, yr)
            if s.empty:
                continue
            print(f"{st:14s}{f'{yr}年':6s}{len(s):5d}{s.min():7.2f}%{pct(s,25):7.2f}%"
                  f"{s.median():7.2f}%{pct(s,75):7.2f}%{s.max():7.2f}%"
                  f"{(s>=8).mean()*100:8.1f}%")
        print()

    # ---------------------------------------------------------- 3. Bootstrap
    print("═" * 96)
    print("③ Block bootstrap · 持有 5 年的年化分布（21 日块，5000 次）")
    print("═" * 96)
    print(f"{'策略':14s}{'5%':>8s}{'25%':>8s}{'中位':>8s}{'75%':>8s}{'95%':>8s}"
          f"{'P(≥8%)':>9s}{'P(亏损)':>9s}")
    print("─" * 96)
    bs = {}
    for st in STRATS:
        b = block_bootstrap(res[st].nv.pct_change().dropna())
        bs[st] = b
        print(f"{st:14s}{pct(b,5):7.2f}%{pct(b,25):7.2f}%{np.median(b):7.2f}%"
              f"{pct(b,75):7.2f}%{pct(b,95):7.2f}%{(b>=8).mean()*100:8.1f}%"
              f"{(b<0).mean()*100:8.1f}%")

    # ---------------------------------------------------------- 4. 成本
    print("\n" + "═" * 96)
    print("④ 扣交易成本（单边 佣金 2.5bp + 滑点 5bp，一次换仓 0.15%）")
    print("═" * 96)
    print(f"{'策略':14s}{'年换手':>8s}{'年成本':>8s}{'毛年化':>8s}{'净年化':>8s}{'掉多少':>8s}")
    print("─" * 96)
    for st in STRATS:
        w = res_t[st].weight_df
        turn = w.diff().abs().sum(axis=1) / 2          # 单边换手
        s = stats(res[st].nv)
        per_year = turn.sum() / max(s["years"], 1e-9)
        cost_yr = per_year * COST_ROUND
        print(f"{st:14s}{per_year*100:7.1f}%{cost_yr*100:7.2f}%{s['cagr']:7.2f}%"
              f"{s['cagr']-cost_yr*100:7.2f}%{-cost_yr*100:+7.2f}pp")

    # ---------------------------------------------------------- 5. 归因
    print("\n" + "═" * 96)
    print("⑤ 8% 靠能力还是靠行情：抽掉某个资产 / 某段行情后的年化")
    print("═" * 96)
    variants = [
        ("基准（5 资产）", None),
        ("抽掉黄金", ("gold",)),
        ("抽掉沪深300", ("hs300",)),
        ("抽掉信用债", ("credit",)),
        ("抽掉 2024-2025", "years"),
    ]
    print(f"{'情形':18s}{'保守增强':>10s}{'风险平价':>10s}{'V3c':>10s}{'保守增强回撤':>13s}")
    print("─" * 96)
    for name, v in variants:
        if v == "years":
            cut = rets[~rets.index.year.isin((2024, 2025))]
            keys2 = keys
            buckets2 = POOL["buckets"]
        elif v is None:
            cut, keys2, buckets2 = rets, keys, POOL["buckets"]
        else:
            keys2 = [k for k in keys if k not in v]
            buckets2 = {k: [a for a in lst if a not in v] for k, lst in POOL["buckets"].items()}
            buckets2 = {k: a for k, a in buckets2.items() if a}
            cut = rets
        rr = run(cut, keys2, buckets2)
        cagrs = [stats(rr[st].nv)["cagr"] for st in STRATS]
        mdd = stats(rr[STRATS[0]].nv)
        print(f"{name:18s}{cagrs[0]:9.2f}%{cagrs[1]:9.2f}%{cagrs[2]:9.2f}%{mdd['mdd']:12.2f}%")

    # ---------------------------------------------------------- 判定
    print("\n" + "═" * 96)
    print("判定")
    print("═" * 96)
    for st in STRATS:
        s = stats(res[st].nv)
        b = bs[st]
        print(f"{st:14s} 已实现 {s['cagr']:5.2f}%  ·  bootstrap 5 年中位 {np.median(b):5.2f}%  "
              f"·  P(≥8%) {(b>=8).mean()*100:4.1f}%  ·  【{s['cagr']:.2f}% 的 13 年】")


if __name__ == "__main__":
    main()
