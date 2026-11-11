"""债券 LOF 全谱系对比（2013-12 起，真实净值）。
候选：13 只 2013-12 前成立的债券 LOF + 511220（现状）+ 511010（2013-03 国债ETF）。
运行：./myenv/bin/python experiments/_lof_bonds.py
"""
import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'streamlit_app')

import numpy as np
import pandas as pd

from allweather import data as D
from allweather.pipeline import panel_returns
from allweather.stats import perf_metrics
import fund_lookup as FL

LOFS = {
    "161010": "富国天丰", "164105": "华富强债", "164902": "交银添利",
    "161216": "国投双债", "162215": "宏利聚利", "160513": "稳健债",
    "165311": "信用债LOF", "162712": "广发聚利", "161505": "银河通利",
    "161820": "银华纯债", "161119": "易方达新综债", "164814": "工银双债",
    "164703": "汇添富纯债", "164509": "国富恒利",
    # 补齐：按关键词 债LOF/债券LOF 二次枚举新增
    "166016": "中欧纯债", "161716": "招商双债增强", "166008": "中欧强债",
    "162108": "金鹰元盛",
}

base = panel_returns(D.load_panel())
base = base.loc[base.index >= "2013-12-19"]
rets = base.copy()
start = rets.index[0]
names = {}
for code, nm in LOFS.items():
    s = FL.build_nav(code)
    if s is None or len(s) < 100:
        continue
    s = s.sort_index(); s = s[~s.index.duplicated()]
    if s.index.min() > start:
        print(f"  跳过 {code} {nm}（净值从 {s.index.min().date()} 起）")
        continue
    s = s.reindex(s.index.union(rets.index)).ffill().reindex(rets.index)
    key = f"l{code}"
    rets[key] = s.pct_change().fillna(0.0)
    names[key] = f"{nm}({code})"

print("=" * 122)
print("一、画像（2013-12-19 起，真实净值；修正夏普 = (CAGR-1.7%)/vol）")
print("=" * 122)
b10, b30, hs = base["bond_10y"], base["bond_30y"], base["hs300"]
rows = []
for key in ["credit"] + list(names):
    s = rets[key].dropna()
    m = perf_metrics((1 + s).cumprod(), s)
    y, x = s.align(b10, join="inner")
    rows.append({
        "标的": "城投债511220(现状)" if key == "credit" else names[key],
        "年化%": round(m["cagr"] * 100, 2), "波动%": round(m["vol"] * 100, 2),
        "回撤%": round(m["mdd"] * 100, 2), "夏普": round(m["sharpe"], 2),
        "对10Y beta": round(np.cov(y, x)[0, 1] / np.var(x), 2),
        "与30Y": round(s.corr(b30), 2), "与沪深300": round(s.corr(hs), 2),
    })
df = pd.DataFrame(rows).sort_values("夏普", ascending=False)
print(df.to_string(index=False))
print(f"\n  数据起点：{start.date()}  交易日 {len(rets)}")
