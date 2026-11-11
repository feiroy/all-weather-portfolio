"""长样本（2006-12 起 20 年）复测此前所有收益提升方向。

背景：此前所有实验都从 2013-12-19 起（受 divlow 上市日限制），恰好切掉了 2013 钱荒
这一次唯一的债券熊市，导致 30Y 兜底、161119 等结论被系统性高估。本脚本在
「8 个有 20 年数据的资产」上重跑，检验哪些方向是真成立、哪些只是样本期挑出来的。

可用的 8 个资产：hs300 / us_sp500 / credit / bond_10y / bond_30y / gold / nonferr / ene
（bond_short 2015 起、divlow 2013-12 起，都剔除）

默认权重上限：rp 0.20 / con 0.25 / v3c 0.25 —— 所以对 B-RP 来说「上限 20%」是空操作，
这里改成放宽 25% / 收紧 15% 才看得出方向。

运行：./myenv/bin/python experiments/_long20_directions.py
"""
import sys

sys.path.insert(0, '.')
sys.path.insert(0, 'streamlit_app')

import numpy as np
import pandas as pd

from allweather import data as D
from allweather.pipeline import panel_returns, run_strategy_backtest
from allweather.stats import perf_metrics

LONG8 = ["hs300", "us_sp500", "credit", "bond_10y", "bond_30y", "gold", "nonferr", "ene"]

# 去掉 divlow 后的桶结构（原结构里 divlow 与 hs300 同桶）
RP4 = {"增长↑": ["hs300", "us_sp500"], "收益垫": ["credit"],
       "增长↓": ["bond_30y"], "通胀↑": ["gold", "nonferr", "ene"]}
RP4_NOENE = {"增长↑": ["hs300", "us_sp500"], "收益垫": ["credit"],
             "增长↓": ["bond_30y"], "通胀↑": ["gold", "nonferr"]}
RP5 = {"增长↑A股": ["hs300"], "增长↑海外": ["us_sp500"], "收益垫": ["credit"],
       "增长↓": ["bond_30y"], "通胀↑": ["gold", "nonferr", "ene"]}
RP6 = {"增长↑": ["hs300", "us_sp500"], "收益垫": ["credit"], "增长↓": ["bond_30y"],
       "通胀↑黄金": ["gold"], "通胀↑有色": ["nonferr"], "通胀↑能源": ["ene"]}

CON5 = {"增长↑": ["hs300", "us_sp500"], "收益垫": ["credit"],
        "增长↓10Y": ["bond_10y"], "增长↓30Y": ["bond_30y"],
        "通胀↑": ["gold", "nonferr", "ene"]}
CON5_NOENE = {"增长↑": ["hs300", "us_sp500"], "收益垫": ["credit"],
              "增长↓10Y": ["bond_10y"], "增长↓30Y": ["bond_30y"],
              "通胀↑": ["gold", "nonferr"]}

V3C8 = ["hs300", "us_sp500", "credit", "bond_30y", "gold", "nonferr", "ene"]
V3C7 = ["hs300", "us_sp500", "credit", "bond_30y", "gold", "nonferr"]

rets = panel_returns(D.load_panel())
rets = rets[[c for c in LONG8 if c in rets.columns]]
print(f"面板 {rets.index.min().date()} → {rets.index.max().date()}  "
      f"{len(rets)} 交易日 ≈ {len(rets)/252:.1f} 年，资产 {len(rets.columns)} 个\n")


def yearly(nv):
    ye = nv.resample("YE").last()
    return pd.Series({ye.index[i].year: ye.iloc[i] / ye.iloc[i - 1] - 1
                      for i in range(1, len(ye))})


def turnover(w):
    if w is None or len(w) < 3:
        return np.nan
    yrs = max((w.index[-1] - w.index[0]).days / 365.25, 1e-9)
    return (w.diff().abs().sum(axis=1) / 2).iloc[1:].sum() / yrs


def run(strategy, asset_list, label, **kw):
    from allweather import pipeline as P
    P.STRATEGY_ASSETS[strategy] = list(asset_list)
    freq = kw.pop("freq", "monthly")
    r = run_strategy_backtest(rets, strategy, freq, track_weights=True, **kw)
    m = perf_metrics(r.nv)
    y = yearly(r.nv)
    return dict(方案=label, 年化=m["cagr"] * 100, 波动=m["vol"] * 100, 回撤=m["mdd"] * 100,
                夏普=m["sharpe"], 负年=f"{int((y < 0).sum())}/{len(y)}",
                最差年=y.min() * 100, 最差年名=str(y.idxmin()),
                换手=turnover(r.weight_df), _y=y)


def show(title, rows, base_key=0):
    print("=" * 122)
    print(title)
    print("=" * 122)
    df = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")} for r in rows])
    b = df.iloc[base_key]
    df["Δ年化"] = df["年化"] - b["年化"]
    df["Δ回撤"] = df["回撤"] - b["回撤"]
    df["Δ夏普"] = df["夏普"] - b["夏普"]
    cols = ["方案", "年化", "Δ年化", "波动", "回撤", "Δ回撤", "夏普", "Δ夏普", "负年", "最差年", "最差年名", "换手"]
    out = df[cols].copy()
    for c in ["年化", "Δ年化", "波动", "回撤", "Δ回撤", "最差年", "夏普", "Δ夏普", "换手"]:
        out[c] = out[c].round(2)
    print(out.to_string(index=False))
    for r in rows:
        if (r["_y"] < 0).any():
            print(f"    {r['方案']:<22} 负年: " + ", ".join(f"{k} {v*100:.2f}%"
                                                        for k, v in r["_y"][r["_y"] < 0].items()))
    print()


# ---------------- V3-B 风险平价 ----------------
rp = []
rp.append(run("V3-B 风险平价", LONG8, "基线(4桶,现状)", rp_buckets=RP4))
rp.append(run("V3-B 风险平价", [a for a in LONG8 if a != "ene"], "删 ene", rp_buckets=RP4_NOENE))
rp.append(run("V3-B 风险平价", LONG8, "桶间逆波动", rp_buckets=RP4, bucket_method="inverse_vol"))
rp.append(run("V3-B 风险平价", LONG8, "5桶(美股独立)", rp_buckets=RP5))
rp.append(run("V3-B 风险平价", LONG8, "6桶(+黄金独立)", rp_buckets=RP6))
rp.append(run("V3-B 风险平价", LONG8, "权重上限放宽25%", rp_buckets=RP4, max_w=0.25))
rp.append(run("V3-B 风险平价", LONG8, "权重上限收紧15%", rp_buckets=RP4, max_w=0.15))
rp.append(run("V3-B 风险平价", LONG8, "避风港→bond_30y", rp_buckets=RP4, safe_asset="bond_30y"))
rp.append(run("V3-B 风险平价", LONG8, "波动目标8%", rp_buckets=RP4, target_vol=0.08))
show("一、V3-B 风险平价：长样本 20 年（2006-12 起）", rp)

# ---------------- 趋势窗口 ----------------
tr = [rp[0]]
for k, tag in [(0.5, "趋势窗口×0.5(38d)"), (1.5, "趋势窗口×1.5(113d)")]:
    tr.append(run("V3-B 风险平价", LONG8, tag, rp_buckets=RP4,
                  nonferr_trend_window=int(75 * k), wti_trend_window=int(75 * k),
                  gold_trend_window=int(75 * k),
                  equity_trend_windows={"us_sp500": int(75 * k), "hs300": int(30 * k)}))
show("二、V3-B 风险平价：趋势过滤窗口（此前 38d 在短样本上是尖峰）", tr)

# ---------------- 调仓频率 ----------------
fr = [rp[0]]
for f, tag in [("biweekly", "调仓双周"), ("weekly", "调仓周频")]:
    fr.append(run("V3-B 风险平价", LONG8, tag, rp_buckets=RP4, freq=f))
show("三、V3-B 风险平价：调仓频率（红线：年换手 ≤2.0）", fr)

# ---------------- V3-B 保守增强 ----------------
con = []
con.append(run("V3-B 保守增强", LONG8, "基线(5桶,现状)", rp_buckets=CON5))
con.append(run("V3-B 保守增强", [a for a in LONG8 if a != "ene"], "删 ene", rp_buckets=CON5_NOENE))
con.append(run("V3-B 保守增强", LONG8, "ERC 真等风险", rp_buckets=CON5, weighting_method="erc"))
con.append(run("V3-B 保守增强", LONG8, "桶间逆波动", rp_buckets=CON5, bucket_method="inverse_vol"))
con.append(run("V3-B 保守增强", LONG8, "权重上限收紧20%", rp_buckets=CON5, max_w=0.20))
con.append(run("V3-B 保守增强", LONG8, "避风港→bond_30y", rp_buckets=CON5, safe_asset="bond_30y"))
show("四、V3-B 保守增强：长样本 20 年", con)

# ---------------- V3c ----------------
v3 = []
v3.append(run("V3c 多元", V3C8, "基线(现状)", assets=V3C8))
v3.append(run("V3c 多元", V3C7, "删 ene", assets=V3C7))
v3.append(run("V3c 多元", V3C8, "权重上限收紧20%", assets=V3C8, max_w=0.20))
v3.append(run("V3c 多元", V3C8, "避风港→bond_30y", assets=V3C8, safe_asset="bond_30y"))
show("五、V3c 多元：长样本 20 年", v3)
