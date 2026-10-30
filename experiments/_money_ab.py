"""A/B 实验：收益垫桶加入 货币ETF(511880) vs 短融ETF(511360)，三策略对比。"""
import pandas as pd

from allweather.data import load_panel
from allweather.pipeline import strategy_backtest_kwargs
from allweather.strategy_b import backtest_b
from allweather.backtest import backtest_iv
from allweather.stats import perf_metrics
from allweather.config import V3B_RP_ASSETS, V3B_RP_BUCKETS, V3B_CON_ASSETS, V3C_ASSETS


def metric(res):
    return perf_metrics(res.nv, rets=res.nv.pct_change().dropna())


def add_bucket(buckets, asset):
    return {k: ([asset] + v if k == "收益垫" else list(v)) for k, v in buckets.items()}


if __name__ == "__main__":
    import os
    panel = load_panel()
    start = os.environ.get("BT_START", "2015-01-01")
    panel = panel.loc[start:]
    print(f"回测起点: {start}（{panel.index[0].date()} 起）")
    # 货币用中证货币基金指数 H11025（全收益口径）；
    # 511880 价格序列含分红除权，不能直接用（价格 CAGR 仅 0.06% 是除权假象）
    money = pd.read_csv("data/moneyfund_idx.csv", parse_dates=["date"], index_col="date")["close"]
    panel["money"] = money.reindex(panel.index).ffill().bfill()  # 前2日为假期，用后续值回填
    assert panel["money"].notna().all()

    rows = []
    for label, strategy, assets, buckets in [
        ("RP 基线", "V3-B 风险平价", V3B_RP_ASSETS, V3B_RP_BUCKETS),
        ("RP +短融", "V3-B 风险平价", V3B_RP_ASSETS + ["bond_short"], add_bucket(V3B_RP_BUCKETS, "bond_short")),
        ("RP +货币", "V3-B 风险平价", V3B_RP_ASSETS + ["money"], add_bucket(V3B_RP_BUCKETS, "money")),
        ("RP +短融+货币", "V3-B 风险平价", V3B_RP_ASSETS + ["bond_short", "money"],
         {k: (["bond_short", "money"] + v if k == "收益垫" else list(v)) for k, v in V3B_RP_BUCKETS.items()}),
        ("Con 基线", "V3-B 保守增强", V3B_CON_ASSETS, None),
        ("Con +短融", "V3-B 保守增强", V3B_CON_ASSETS + ["bond_short"], None),
        ("Con +货币", "V3-B 保守增强", V3B_CON_ASSETS + ["money"], None),
        ("V3c 基线", "V3c 多元", V3C_ASSETS, None),
        ("V3c +短融", "V3c 多元", V3C_ASSETS + ["bond_short"], None),
        ("V3c +货币", "V3c 多元", V3C_ASSETS + ["money"], None),
    ]:
        rets = panel.pct_change().dropna()
        kw = strategy_backtest_kwargs(strategy)
        if buckets is not None:
            kw["rp_buckets"] = buckets
        if strategy == "V3c 多元":
            kw["assets"] = assets
            res = backtest_iv(rets, **kw)
        else:
            res = backtest_b(rets[assets], **kw)
        m = metric(res)
        rows.append({"方案": label, "CAGR": m["cagr"], "MDD": m["mdd"], "Sharpe": m["sharpe"], "Calmar": m["calmar"]})

    print("===== 短融 vs 货币 全策略对比（2015-01 → 2026-10）=====")
    print(pd.DataFrame(rows).set_index("方案").to_string(float_format=lambda x: f"{x:.4f}"))

    # 两个资产自身的画像
    print("\n===== 资产自身画像（同期）=====")
    for name, s in [("短融511360", panel["bond_short"]), ("货币511880", panel["money"]), ("城投511220", panel["credit"])]:
        r = s.pct_change().dropna()
        years = (s.index[-1] - s.index[0]).days / 365.25
        print(f"{name}: CAGR {(s.iloc[-1]/s.iloc[0])**(1/years)-1:.2%}  年化波动 {r.std()*252**0.5:.3%}  最大回撤 {(s/s.cummax()-1).min():.2%}")
