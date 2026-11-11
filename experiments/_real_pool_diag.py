"""方案 A 的诊断：把「真实 vs 拼接」的差异拆干净。

    PYTHONPATH=. ./myenv/bin/python experiments/_real_pool_diag.py

上面那张对照表里，5 资产真实池 vs 现有 9 资产拼接池，差异混了两件事：
  ① 数据真假（真实净值 vs 指数/重建代理）
  ② 资产替换（30Y→5Y 国债、城投债→信用债、砍掉 divlow/nonferr/ene）
这里只用两边都有的 4 个资产（沪深300 / 标普500 / 信用债 / 黄金）跑同一套策略，
差异就只剩 ①。
"""
from __future__ import annotations

import pandas as pd

from allweather import data as D

KEYS4 = ["hs300", "us_sp500", "credit", "gold"]
BUCKETS4 = {"增长↑": ["hs300", "us_sp500"], "收益垫": ["credit"], "通胀↑": ["gold"]}


def stats(nv: pd.Series) -> dict:
    nv = nv.dropna()
    yrs = (nv.index[-1] - nv.index[0]).days / 365.25
    cagr = nv.iloc[-1] ** (1 / yrs) - 1
    mdd = (nv / nv.cummax() - 1).min()
    vol = nv.pct_change().dropna().std() * (252 ** 0.5)
    return {"years": yrs, "cagr": cagr * 100, "mdd": mdd * 100, "vol": vol * 100,
            "sharpe": (cagr - 0.017) / vol}


def run(rets: pd.DataFrame, keys: list, buckets: dict) -> dict:
    from allweather import pipeline as P
    P.STRATEGY_ASSETS = {k: list(keys) for k in
                         ("V3-B 风险平价", "V3-B 保守增强", "V3c 多元")}
    P.V3B_RP_BUCKETS = {k: list(v) for k, v in buckets.items()}
    out = {}
    for st in ("V3-B 保守增强", "V3-B 风险平价", "V3c 多元"):
        kw = dict(nonferr_trend_window=0, wti_trend_window=0)
        if st == "V3c 多元":
            kw["assets"] = list(keys)
        r = P.run_strategy_backtest(rets, st, "monthly", **kw)
        out[st] = (stats(r.nv), r)
    return out


def main():
    real = pd.read_csv("data/real/_rets_5.csv", index_col=0, parse_dates=True)
    panel = D.load_panel()
    legacy = panel.pct_change().dropna(how="all")

    start = "2013-07-18"
    real4 = real[KEYS4].loc[start:]
    leg4 = legacy[KEYS4].loc[start:]

    a = run(real4, KEYS4, BUCKETS4)
    b = run(leg4, KEYS4, BUCKETS4)

    print("同池 4 资产（沪深300 / 标普500 / 信用债 / 黄金）· 2013-07-18 起 13.3 年")
    print(f"{'策略':14s}{'口径':16s}{'年化':>8s}{'回撤':>9s}{'波动':>8s}{'夏普':>7s}")
    for st in a:
        for src, name in ((a, "真实净值"), (b, "拼接代理")):
            s = src[st][0]
            print(f"{st:14s}{name:16s}{s['cagr']:7.2f}%{s['mdd']:8.2f}%{s['vol']:7.2f}%{s['sharpe']:7.2f}")
        print(f"{'':14s}{'差（真实−拼接）':16s}{a[st][0]['cagr']-b[st][0]['cagr']:+7.2f}pp"
              f"{a[st][0]['mdd']-b[st][0]['mdd']:+8.2f}pp")
        print()

    # 最大回撤落在哪一段（用真实 5 资产池的保守增强）
    r5 = pd.read_csv("data/real/_rets_5.csv", index_col=0, parse_dates=True).loc[start:]
    res = run(r5, ["hs300", "us_sp500", "credit", "bond_10y", "gold"],
              {"增长↑": ["hs300", "us_sp500"], "收益垫": ["credit"],
               "增长↓": ["bond_10y"], "通胀↑": ["gold"]})
    print("5 资产真实池：最大回撤区间")
    for st, (_s, r) in res.items():
        nv = r.nv.dropna()
        peak = nv.cummax()
        trough = (nv / peak - 1).idxmin()
        peakday = nv.loc[:trough].idxmax()
        print(f"  {st:14s} 峰 {peakday.date()} → 谷 {trough.date()}  "
              f"{(nv.loc[trough]/nv.loc[peakday]-1)*100:.2f}%")

    print("\n2022 年（股债双杀）各资产真实收益：")
    y22 = r5.loc["2022-01-01":"2022-12-31"]
    for k in r5.columns:
        print(f"  {k:10s}{((1+y22[k]).prod()-1)*100:+7.2f}%")


if __name__ == "__main__":
    main()
