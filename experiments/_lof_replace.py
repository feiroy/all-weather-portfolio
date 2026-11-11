"""债券 LOF 实战对比：整只替换 credit / 作为趋势过滤避风港（三策略）。
运行：./myenv/bin/python experiments/_lof_replace.py
"""
import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'streamlit_app')

import numpy as np
import pandas as pd

from allweather import data as D
from allweather.config import V3B_RP_ASSETS, V3B_CON_ASSETS, V3C_ASSETS
from allweather import pipeline as P
from allweather.pipeline import run_strategy_backtest, panel_returns
from allweather.stats import perf_metrics
import fund_lookup as FL

TOP = {"161820": "银华纯债", "161119": "易方达新综债",
       "164703": "汇添富纯债", "161716": "招商双债增强"}

base = panel_returns(D.load_panel())
base = base.loc[base.index >= "2013-12-19"]
rets = base.copy()
for code in TOP:
    s = FL.build_nav(code).sort_index()
    s = s[~s.index.duplicated()]
    s = s.reindex(s.index.union(rets.index)).ffill().reindex(rets.index)
    rets[f"l{code}"] = s.pct_change().fillna(0.0)

STRATS = ["V3-B 保守增强", "V3c 多元", "V3-B 风险平价"]
LIMIT = {"V3-B 保守增强": (-7.0, 5.0), "V3c 多元": (-8.5, 6.0), "V3-B 风险平价": (-9.0, 7.0)}


def metrics(sname, df):
    r = run_strategy_backtest(df, sname, "monthly")
    m = perf_metrics(r.nv)
    yr = r.nv.resample("YE").last().pct_change().dropna()
    return m, yr.min(), (yr > 0).mean()


def line(tag, m, worst, pos, b=None):
    x = ""
    if b:
        d = m["cagr"] - b[0]["cagr"], m["mdd"] - b[0]["mdd"], m["sharpe"] - b[0]["sharpe"]
        x = f"   ← 年化 {d[0]*100:+.2f}pp | 回撤 {d[1]*100:+.2f}pp | 夏普 {d[2]:+.2f}"
    return (f"{tag:<26} 年化 {m['cagr']*100:5.2f}% | 波动 {m['vol']*100:4.2f}% | "
            f"回撤 {m['mdd']*100:6.2f}% | 夏普 {m['sharpe']:4.2f} | "
            f"最差年 {worst*100:6.2f}% | 正年 {pos*100:4.0f}%{x}")


print("=" * 126)
print("二、整只替换 credit（其余参数一字不改）")
print("=" * 126)
for sname in STRATS:
    b = metrics(sname, base)
    print(f"\n  {sname}")
    print(line("城投债511220（现状）", *b))
    for code, nm in TOP.items():
        r2 = rets[base.columns].copy()
        r2["credit"] = rets[f"l{code}"]
        m, w, p = metrics(sname, r2)
        ok = "✓" if (m["mdd"] * 100 >= LIMIT[sname][0] and m["vol"] * 100 <= LIMIT[sname][1]) else "✗"
        print(line(f"{nm}({code}) {ok}", m, w, p, b))

print()
print("=" * 126)
print("三、作为趋势过滤的避风港（B-RP，同池公平对比）")
print("=" * 126)
extra = [f"l{c}" for c in TOP]
P.STRATEGY_ASSETS["V3-B 风险平价"] = list(V3B_RP_ASSETS) + extra
b = metrics("V3-B 风险平价", rets)
print(line("城投债（现状）", *b))
for code, nm in TOP.items():
    r = run_strategy_backtest(rets, "V3-B 风险平价", "monthly", safe_asset=f"l{code}")
    m = perf_metrics(r.nv)
    yr = r.nv.resample("YE").last().pct_change().dropna()
    print(line(f"{nm}({code})", m, yr.min(), (yr > 0).mean(), b))
