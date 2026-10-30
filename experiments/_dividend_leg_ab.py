"""A/B 实验：红利低波(H30269) 作为新增腿 + V3c 补短融对比。

注意：H30269 为价格指数（不含分红），红利低波全收益每年另含约 4-5pp 股息，
本实验对红利低波腿是**偏保守（低估收益）**的估计。
"""
import pandas as pd

from allweather.data import load_panel
from allweather.pipeline import strategy_backtest_kwargs
from allweather.strategy_b import backtest_b
from allweather.backtest import backtest_iv
from allweather.stats import perf_metrics
from allweather.config import V3B_RP_ASSETS, V3B_RP_BUCKETS, V3C_ASSETS


def with_short(buckets):
    return {k: (["bond_short"] + v if k == "收益垫" else list(v)) for k, v in buckets.items()}


def rp(panel, buckets, assets):
    rets = panel.pct_change().dropna()
    kw = strategy_backtest_kwargs("V3-B 风险平价")
    kw["rp_buckets"] = buckets
    return backtest_b(rets[assets], **kw)


def v3c(panel, assets):
    rets = panel.pct_change().dropna()
    kw = strategy_backtest_kwargs("V3c 多元")
    kw["assets"] = assets
    return backtest_iv(rets, **kw)


def metric(res):
    return perf_metrics(res.nv, rets=res.nv.pct_change().dropna())


if __name__ == "__main__":
    panel = load_panel()
    div = pd.read_csv("data/dividend_lowvol_idx.csv", parse_dates=["date"], index_col="date")["close"]
    panel["div_lowvol"] = div.reindex(panel.index).ffill()
    assert panel["div_lowvol"].notna().all()

    RP_SHORT_ASSETS = ["hs300", "us_sp500", "credit", "bond_short", "bond_30y", "gold", "nonferr", "wti"]
    RP_DIV_ASSETS = V3B_RP_ASSETS + ["div_lowvol"]
    RP_BOTH_ASSETS = RP_SHORT_ASSETS + ["div_lowvol"]
    DIV_BUCKETS = {**V3B_RP_BUCKETS, "增长↑": ["hs300", "div_lowvol", "us_sp500"]}

    rows = []
    for label, fn in [
        ("RP 基线", lambda: rp(panel, V3B_RP_BUCKETS, V3B_RP_ASSETS)),
        ("RP +短融", lambda: rp(panel, with_short(V3B_RP_BUCKETS), RP_SHORT_ASSETS)),
        ("RP +红利低波腿", lambda: rp(panel, DIV_BUCKETS, RP_DIV_ASSETS)),
        ("RP +短融 +红利低波腿", lambda: rp(panel, with_short(DIV_BUCKETS), RP_BOTH_ASSETS)),
        ("V3c 基线", lambda: v3c(panel, V3C_ASSETS)),
        ("V3c +短融", lambda: v3c(panel, V3C_ASSETS + ["bond_short"])),
        ("V3c +红利低波腿", lambda: v3c(panel, V3C_ASSETS + ["div_lowvol"])),
        ("V3c +短融 +红利低波腿", lambda: v3c(panel, V3C_ASSETS + ["bond_short", "div_lowvol"])),
    ]:
        m = metric(fn())
        rows.append({"方案": label, "CAGR": m["cagr"], "MDD": m["mdd"], "Sharpe": m["sharpe"], "Calmar": m["calmar"]})

    df = pd.DataFrame(rows).set_index("方案")
    print("===== 组合层面对比（2015-01 → 2026-10）=====")
    print(df.to_string(float_format=lambda x: f"{x:.4f}"))
