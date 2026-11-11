"""避风港（safe_asset）该选哪只债：波动更小的债基是不是更好？

用户质疑：城投债兜底好，为什么不买债券基金？债基波动更小。

结论：不能只看波动。含 2013 钱荒的 14 年窗口里，城投债的回撤最小、Calmar 最高。
     债基在 13 年窗口（2013-12 起）看起来更好，是因为恰好排除了 2013 这一次债券熊市。

关键陷阱：V3B_RP_ASSETS 不含 divlow 时窗口才不会被截断到 2013-12；本脚本显式剔除
divlow/ene，并从 2012-11（161119 起点）起算，才能真正覆盖 2013 钱荒。
另注意 safe_asset 指向池外资产会静默退化为 safe_idx=-1（不报错、结果雷同），
故下面每次调用前都断言 sa 在 STRATEGY_ASSETS 里。

运行：./myenv/bin/python experiments/_safe_asset_choice.py
"""
import sys

sys.path.insert(0, '.')
sys.path.insert(0, 'streamlit_app')

import numpy as np
import pandas as pd

from allweather import data as D
from allweather import pipeline as P
from allweather.config import V3B_RP_ASSETS, V3B_RP_BUCKETS
from allweather.pipeline import panel_returns, run_strategy_backtest
from allweather.stats import perf_metrics
import fund_lookup as FL

full = panel_returns(D.load_panel())
for code in ['161820', '161119']:
    s = FL.build_nav(code).sort_index()
    s = s[~s.index.duplicated()]
    s = s.reindex(s.index.union(full.index)).ffill().reindex(full.index)
    full[f'l{code}'] = s.pct_change().fillna(0.0)

DROP = ("divlow", "ene")
rets = full.loc[full.index >= "2012-11-08"].drop(columns=[c for c in DROP if c in full.columns])
BASE_AL = [a for a in V3B_RP_ASSETS if a not in DROP]
BK = {k: [x for x in v if x not in DROP] for k, v in V3B_RP_BUCKETS.items()}
BK = {k: v for k, v in BK.items() if v}

CANDS = [("credit", "城投债ETF(0.83%)"), ("l161820", "银华纯债(1.00%)"),
         ("l161119", "易方达新综债(1.26%)"), ("bond_10y", "10年国债(2.18%)"),
         ("bond_30y", "30年国债(6.20%)")]


def yearly(nv):
    ye = nv.resample("YE").last()
    return pd.Series({ye.index[i].year: ye.iloc[i] / ye.iloc[i - 1] - 1
                      for i in range(1, len(ye))})


rows = []
for sa, label in CANDS:
    if sa not in rets.columns:
        continue
    P.STRATEGY_ASSETS["V3-B 风险平价"] = list(dict.fromkeys(BASE_AL + [sa]))
    assert sa in P.STRATEGY_ASSETS["V3-B 风险平价"], f"{sa} 不在池内，会静默退化"
    r = run_strategy_backtest(rets, "V3-B 风险平价", "monthly",
                              rp_buckets=BK, safe_asset=sa)
    q = perf_metrics(r.nv)
    y = yearly(r.nv)
    rows.append(dict(避风港=label, 年化=q["cagr"] * 100, 波动=q["vol"] * 100,
                     回撤=q["mdd"] * 100, 夏普=q["sharpe"],
                     Calmar=q["cagr"] / abs(q["mdd"]),
                     负年=f"{int((y < 0).sum())}/{len(y)}", 最差年=y.min() * 100,
                     _2013=y.get(2013, np.nan) * 100))

print("=" * 108)
print(f"避风港对比（{rets.index.min().date()}~{rets.index.max().date()}，"
      f"{len(rets)/252:.1f} 年，含 2013 钱荒，已剔 divlow/ene）")
print("=" * 108)
df = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith('_')} for r in rows])
for c in ["年化", "波动", "回撤", "夏普", "Calmar", "最差年"]:
    df[c] = df[c].round(2)
df["2013年"] = [round(r["_2013"], 2) for r in rows]
print(df[["避风港", "年化", "波动", "回撤", "夏普", "Calmar", "负年", "最差年", "2013年"]]
      .to_string(index=False))
