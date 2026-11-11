"""策略有效性判定：7% 里有多少是「配置」、多少是「策略」、多少是「2024-2025 运气」。

    PYTHONPATH=. ./myenv/bin/python experiments/_alpha_decomp.py

三层拆解（都用一个池、一个区间，避免上次那种混淆）：
  ①  固定权重月度再平衡      = 纯配置的 beta
  ②  策略动态调权            = ① + 权重择时
  ③  去掉 2024、2025 后重跑  = 检验 ② 的超额是不是只靠这两年
  ④  前瞻票息                = 当前利率下「什么都不发生」能拿多少
"""
from __future__ import annotations

import warnings

import pandas as pd

warnings.filterwarnings("ignore")

from allweather import data as D, pipeline as P   # noqa: E402

STRATS = ("V3-B 保守增强", "V3-B 风险平价", "V3c 多元")
START = "2013-07-22"
# 当前实盘目标权重（B-Con）
W_CON = {"credit": 0.3393, "bond_10y": 0.2503, "bond_30y": 0.1474, "divlow": 0.0563,
         "hs300": 0.0556, "us_sp500": 0.0504, "gold": 0.0504, "ene": 0.0504}


def perf(nv: pd.Series) -> dict:
    nv = nv.dropna()
    if len(nv) < 2:
        return {}
    y = (nv.index[-1] - nv.index[0]).days / 365.25
    c = nv.iloc[-1] ** (1 / y) - 1
    m = (nv / nv.cummax() - 1).min()
    v = nv.pct_change().dropna().std() * 252 ** 0.5
    return {"y": y, "cagr": c * 100, "mdd": m * 100, "vol": v * 100, "sharpe": (c - .017) / v}


def fixed_weight(rets: pd.DataFrame, w: dict) -> pd.Series:
    cols = [c for c in w if c in rets.columns]
    s = rets[cols].mul([w[c] for c in cols]).sum(axis=1)
    return (1 + s).cumprod()


def main():
    rets = D.load_panel().pct_change().dropna(how="all").loc[START:]
    r24 = rets[~rets.index.year.isin((2024, 2025))]

    print(f"池：生产口径 9 资产  区间 {rets.index[0]:%Y-%m-%d} ~ {rets.index[-1]:%Y-%m-%d}\n")

    print("═" * 92)
    print("①  固定权重 vs 策略动态调权（同一池、同一区间）")
    print("═" * 92)
    print(f"{'口径':26s}{'年数':>6s}{'年化':>8s}{'回撤':>9s}{'波动':>8s}{'夏普':>7s}")
    print("─" * 92)
    fw = perf(fixed_weight(rets, W_CON))
    print(f"{'固定权重月再平衡':26s}{fw['y']:6.1f}{fw['cagr']:7.2f}%{fw['mdd']:8.2f}%"
          f"{fw['vol']:7.2f}%{fw['sharpe']:7.2f}")
    strat = {}
    for st in STRATS:
        s = perf(P.run_strategy_backtest(rets, st, "monthly").nv)
        strat[st] = s
        print(f"{st:26s}{s['y']:6.1f}{s['cagr']:7.2f}%{s['mdd']:8.2f}%{s['vol']:7.2f}%{s['sharpe']:7.2f}")
    print(f"\n权重择时超额（策略 − 固定权重）：")
    for st in STRATS:
        print(f"  {st:14s}{strat[st]['cagr']-fw['cagr']:+6.2f}pp   回撤 {strat[st]['mdd']-fw['mdd']:+5.2f}pp")

    print("\n" + "═" * 92)
    print("②  去掉 2024、2025 两年，同样三者重跑（检验超额是不是只靠这两年）")
    print("═" * 92)
    print(f"{'口径':26s}{'年数':>6s}{'年化':>8s}{'回撤':>9s}{'波动':>8s}{'夏普':>7s}")
    print("─" * 92)
    fw2 = perf(fixed_weight(r24, W_CON))
    print(f"{'固定权重月再平衡':26s}{fw2['y']:6.1f}{fw2['cagr']:7.2f}%{fw2['mdd']:8.2f}%"
          f"{fw2['vol']:7.2f}%{fw2['sharpe']:7.2f}")
    strat2 = {}
    for st in STRATS:
        s = perf(P.run_strategy_backtest(r24, st, "monthly").nv)
        strat2[st] = s
        print(f"{st:26s}{s['y']:6.1f}{s['cagr']:7.2f}%{s['mdd']:8.2f}%{s['vol']:7.2f}%{s['sharpe']:7.2f}")
    print(f"\n去掉 2024-2025 后的超额（策略 − 固定权重）：")
    for st in STRATS:
        print(f"  {st:14s}{strat2[st]['cagr']-fw2['cagr']:+6.2f}pp   回撤 {strat2[st]['mdd']-fw2['mdd']:+5.2f}pp")

    print("\n" + "═" * 92)
    print("③  前瞻：当前利率下，这个权重组合「什么都不发生」能拿多少")
    print("═" * 92)
    YTM = {"credit": 2.00, "bond_10y": 1.60, "bond_30y": 2.04}   # 2026-11-10 中债估值 + 信用利差
    bw = sum(W_CON[k] for k in YTM)
    by = sum(W_CON[k] * YTM[k] for k in YTM)
    eqw = W_CON["hs300"] + W_CON["us_sp500"] + W_CON["divlow"]
    cmw = W_CON["gold"] + W_CON["ene"]
    print(f"债券 {bw*100:.1f}% 加权票息 {by/bw:.2f}% → 贡献 {by:.2f}pp")
    print(f"权益 {eqw*100:.1f}%   商品 {cmw*100:.1f}%")
    print(f"\n{'情形':8s}{'权益假设':>10s}{'商品假设':>10s}{'前瞻年化':>10s}")
    print("─" * 92)
    for sc, eq, cm in (("悲观", 4, 0), ("中性", 7, 3), ("乐观", 10, 5)):
        print(f"{sc:8s}{eq:9d}%{cm:9d}%{by+eqw*eq+cmw*cm:9.2f}%")
    print(f"\n要 8%：非债券 {((eqw+cmw)*100):.1f}% 需贡献 {8-by:.2f}pp → 需年化 {(8-by)/(eqw+cmw):.0f}%")


if __name__ == "__main__":
    main()
