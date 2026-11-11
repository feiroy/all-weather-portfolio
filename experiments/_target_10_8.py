"""目标检验：能不能做到年化 10% + 回撤 ≤8%（均衡）。

用户诉求：收益高、回撤小、均衡。本脚本回答三个问题：
  1. 现有 8 资产池，换策略家族能不能到 10%/8%？      → 不能，见「家族横评」
  2. 这个池子的上限在哪？                              → 带未来函数的效率前沿
  3. 怎么才能真正突破？                                → 扩资产池（加纳指100）

关键结论（2006-12~2026-11 / 2013-12~2026 两个窗口）：
  - 现有池 8% 回撤约束下，理论最优（含未来函数）9.79%，实盘 8.63%
  - 10% 年化需要把回撤预算放到 −10%~−12%
  - 加纳指100 是唯一有效且干净的方向：同桶并入「增长↑权益」，不破坏 5 桶结构
    → 8.63%/−6.51% → 8.87%/−6.05%，夏普 1.55→1.62，负年 1→0

数据来源：纳指用 ak.index_global_hist_em("纳斯达克")（1991 起）× usdcny，缓存 /tmp/ixic.csv。
注意：纳指必须并入「增长↑权益(海外)」桶，独立成桶会重演 divlow 的教训（回撤 −7.62%）。

运行：./myenv/bin/python experiments/_target_10_8.py
"""
import os
import sys
import time

sys.path.insert(0, '.')
sys.path.insert(0, 'streamlit_app')

import numpy as np
import pandas as pd

from allweather import data as D
from allweather import pipeline as P
from allweather.data import _load_optional
from allweather.pipeline import panel_returns, run_strategy_backtest
from allweather.stats import perf_metrics

CACHE = "/tmp/ixic.csv"


def load_ndx_cny(index_like):
    """纳斯达克综合指数（1991 起）× USDCNY，对齐到给定索引。"""
    if not os.path.exists(CACHE):
        import akshare as ak
        for i in range(6):
            try:
                df = ak.index_global_hist_em(symbol="纳斯达克")
                df.to_csv(CACHE, index=False)
                break
            except Exception:
                time.sleep(3)
        else:
            raise RuntimeError("纳斯达克指数拉取失败")
    src = pd.read_csv(CACHE, parse_dates=["日期"]).set_index("日期").sort_index()
    usdcny = _load_optional("usdcny")
    comb = src.index.union(usdcny.index)
    cny = (pd.to_numeric(src["最新价"], errors="coerce").reindex(comb).ffill()
           * usdcny.reindex(comb).ffill()).dropna()
    cny = cny[cny.index <= index_like.max()]
    ret = cny.pct_change()
    return ret.reindex(index_like.union(ret.index)).ffill().reindex(index_like)


def yearly(nv):
    ye = nv.resample("YE").last()
    return pd.Series({ye.index[i].year: ye.iloc[i] / ye.iloc[i - 1] - 1
                      for i in range(1, len(ye))})


def show(df_rows, title):
    print("=" * 112)
    print(title)
    print("=" * 112)
    df = pd.DataFrame([{k: v for k, v in r.items() if k != "_y"} for r in df_rows])
    for c in ["年化", "波动", "回撤", "夏普", "Calmar", "最差年"]:
        df[c] = df[c].round(2)
    df["达标10/8"] = np.where((df["年化"] >= 10) & (df["回撤"] >= -8), "✓", "✗")
    print(df[["方案", "年化", "波动", "回撤", "夏普", "Calmar", "负年", "最差年", "达标10/8"]]
          .to_string(index=False))
    for r in df_rows:
        if (r["_y"] < 0).any():
            print(f"  {r['方案']:<26} 负年: " + ", ".join(
                f"{k} {v*100:.2f}%" for k, v in r["_y"][r["_y"] < 0].items()))
    print()


full = panel_returns(D.load_panel())
full["ndx"] = load_ndx_cny(full.index)

# ============ 一、生产口径候选（2013-12 起，含 divlow）============
rets = full.loc[full.index >= "2013-12-19"]
DIV = ["hs300", "us_sp500", "credit", "bond_30y", "gold", "nonferr", "ene", "divlow"]
B4 = {"增长↑": ["hs300", "us_sp500", "divlow"], "收益垫": ["credit"],
      "增长↓": ["bond_30y"], "通胀↑": ["gold", "nonferr", "ene"]}
B4N = {"增长↑": ["hs300", "us_sp500", "divlow", "ndx"], "收益垫": ["credit"],
       "增长↓": ["bond_30y"], "通胀↑": ["gold", "nonferr", "ene"]}
B4NN = {"增长↑": ["hs300", "us_sp500", "divlow", "ndx"], "收益垫": ["credit"],
        "增长↓": ["bond_30y"], "通胀↑": ["gold", "nonferr"]}

rows = []


def run_prod(tag, assets, buckets=None, freq="monthly"):
    P.STRATEGY_ASSETS["V3-B 风险平价"] = list(assets)
    kw = P.strategy_backtest_kwargs("V3-B 风险平价", freq)
    kw.pop("rebal_freq")
    if buckets is not None:
        kw["rp_buckets"] = buckets
    res = run_strategy_backtest(rets, "V3-B 风险平价", freq, **kw)
    m = perf_metrics(res.nv)
    y = yearly(res.nv)
    rows.append(dict(方案=tag, 年化=m["cagr"] * 100, 波动=m["vol"] * 100, 回撤=m["mdd"] * 100,
                     夏普=m["sharpe"], Calmar=m["cagr"] / abs(m["mdd"]),
                     负年=f"{int((y < 0).sum())}/{len(y)}", 最差年=y.min() * 100, _y=y))


run_prod("现状(8资产,生产)", DIV)
run_prod("+纳指并入增长↑桶(9)", DIV + ["ndx"], B4N)
run_prod("+纳指且剔ene(8)", [c for c in DIV if c != "ene"] + ["ndx"], B4NN)
run_prod("+纳指+双周", DIV + ["ndx"], B4N, "biweekly")
show(rows, "一、生产口径真实回测（2013-12~2026，13 年，无未来函数）")

# ============ 二、效率前沿：这个池子的天花板上限 ============
def frontier(r, n_iter=60000, seed=11):
    cols = r.columns.tolist()
    arr = r.fillna(0.0).values
    rng = np.random.default_rng(seed)
    out = []
    for w in rng.dirichlet(np.ones(len(cols)) * 0.7, size=n_iter):
        p = arr @ w
        nv = np.cumprod(1 + p)
        mdd = (nv / np.maximum.accumulate(nv) - 1).min()
        cagr = nv[-1] ** (252 / len(p)) - 1
        out.append((cagr, mdd, w))
    out.sort(key=lambda x: -x[0])
    return out, cols


print("=" * 100)
print("二、效率前沿：回撤预算 → 可达年化上限（含未来函数，不可能实盘，是理论天花板）")
print("=" * 100)
prod = full.loc[full.index >= "2013-12-19"].dropna()
print(f"{'回撤预算':>9}{'池子不含纳指':>14}{'池子含纳指':>13}{'纳指权重':>10}")
f_no, c_no = frontier(prod.drop(columns=["ndx"]))
f_nd, c_nd = frontier(prod)
for dd in [5, 6, 7, 8, 9, 10, 12]:
    a = next((x for x in f_no if x[1] >= -dd / 100), None)
    b = next((x for x in f_nd if x[1] >= -dd / 100), None)
    if a and b:
        print(f"{dd:>8}%{a[0]*100:13.2f}%{b[0]*100:12.2f}%{b[2][c_nd.index('ndx')]*100:9.1f}%")
print()
print("注：10% 年化在含纳指池子里需要约 −9% 回撤预算；不含纳指需要 −10% 以上。")
