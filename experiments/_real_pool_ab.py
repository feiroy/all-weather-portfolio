"""方案 A：纯真实基金（5 只，无任何拼接）vs 现有拼接版，同一时间区间对照。

    ./myenv/bin/python experiments/_real_pool_ab.py

方案 A 的池（每类都是真实存在、有真实净值的基金）：
    增长↑  160706 嘉实沪深300 / 050025 博时标普500
    收益垫 000032 易方达信用债A
    增长↓ 511010 国泰上证5年期国债ETF
    通胀↑ 518880 华安黄金ETF
公共起点 2013-07-18（黄金 ETF 上市日），13.3 年。

对照：现有面板（含指数/收益率重建等拼接）截到同一天，跑同样三策略。
差异 = 「合成数据把结果做漂亮了多少」。
"""
from __future__ import annotations

import pandas as pd

from allweather import data as D
from allweather import pipeline as P

REAL_KEYS = ["hs300", "us_sp500", "credit", "bond_10y", "gold"]
REAL_BUCKETS = {"增长↑": ["hs300", "us_sp500"], "收益垫": ["credit"],
                "增长↓": ["bond_10y"], "通胀↑": ["gold"]}


def stats(nv: pd.Series) -> dict:
    nv = nv.dropna()
    yrs = (nv.index[-1] - nv.index[0]).days / 365.25
    cagr = nv.iloc[-1] ** (1 / yrs) - 1
    mdd = (nv / nv.cummax() - 1).min()
    r = nv.pct_change().dropna()
    vol = r.std() * (252 ** 0.5)
    yv = nv.groupby(nv.index.year).last()
    yr = yv.pct_change()
    yr.iloc[0] = yv.iloc[0] / nv.iloc[0] - 1
    return {"years": yrs, "cagr": cagr * 100, "mdd": mdd * 100, "vol": vol * 100,
            "sharpe": (cagr - 0.017) / vol if vol else float("nan"),
            "calmar": cagr / abs(mdd) if mdd else float("nan"),
            "neg": {int(i): round(v * 100, 2) for i, v in yr[yr < 0].items()}}


def run_real() -> dict:
    rets = pd.read_csv("data/real/_rets_5.csv", index_col=0, parse_dates=True)
    P.STRATEGY_ASSETS = {k: list(REAL_KEYS) for k in
                         ("V3-B 风险平价", "V3-B 保守增强", "V3c 多元")}
    P.V3B_RP_BUCKETS = {k: list(v) for k, v in REAL_BUCKETS.items()}
    out = {}
    for st in ("V3-B 保守增强", "V3-B 风险平价", "V3c 多元"):
        kw = dict(nonferr_trend_window=0, wti_trend_window=0)
        if st == "V3c 多元":
            kw["assets"] = list(REAL_KEYS)
        out[st] = stats(P.run_strategy_backtest(rets, st, "monthly", **kw).nv)
    return out


def run_legacy(start: str) -> dict:
    """现有面板（拼接版），截到同一区间。"""
    from allweather import pipeline as PP
    import importlib
    importlib.reload(PP)                      # 清掉上面 patch 过的全局
    panel = D.load_panel()
    rets = panel.pct_change().dropna(how="all").loc[start:]
    out = {}
    for st in ("V3-B 保守增强", "V3-B 风险平价", "V3c 多元"):
        out[st] = stats(PP.run_strategy_backtest(rets, st, "monthly").nv)
    return out


def main():
    real = run_real()
    start = "2013-07-18"
    legacy = run_legacy(start)

    hdr = f"{'策略':14s}{'口径':22s}{'年数':>5s}{'年化':>8s}{'回撤':>9s}{'波动':>8s}{'夏普':>7s}{'Calmar':>8s}  负年"
    print(hdr)
    print("-" * len(hdr))
    for st in ("V3-B 保守增强", "V3-B 风险平价", "V3c 多元"):
        for src, name in ((real, "方案A 纯真实 5 只"), (legacy, "现有拼接版")):
            s = src[st]
            print(f"{st:14s}{name:22s}{s['years']:5.1f}{s['cagr']:7.2f}%{s['mdd']:8.2f}%"
                  f"{s['vol']:7.2f}%{s['sharpe']:7.2f}{s['calmar']:8.2f}  {s['neg']}")
        d = real[st]["cagr"] - legacy[st]["cagr"]
        dm = real[st]["mdd"] - legacy[st]["mdd"]
        print(f"{'':14s}{'差（真实 − 拼接）':22s}{'':5s}{d:+7.2f}pp{dm:+8.2f}pp")
        print()


if __name__ == "__main__":
    main()
