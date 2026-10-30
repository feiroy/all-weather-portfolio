"""A/B 实验：V3-B 两个变体纳入 bond_short（511360 短融ETF + H11014 指数拼接）前后对比。

不改配置，直接按 pipeline.strategy_backtest_kwargs 的参数构造基线与实验组。
"""
import pandas as pd

from allweather.data import load_panel
from allweather.pipeline import strategy_backtest_kwargs
from allweather.strategy_b import backtest_b
from allweather.stats import perf_metrics
from allweather.config import (
    V3B_RP_ASSETS, V3B_RP_BUCKETS, V3B_CON_ASSETS,
)


def with_short(buckets: dict) -> dict:
    return {k: (["bond_short"] + v if k == "收益垫" else list(v)) for k, v in buckets.items()}


def run(name, assets, buckets, strategy):
    rets = PANEL.pct_change().dropna()
    kw = strategy_backtest_kwargs(strategy)
    kw.pop("assets", None)
    if buckets is not None:
        kw["rp_buckets"] = buckets
    res = backtest_b(rets[assets], **kw)
    m = perf_metrics(res.nv, rets=res.nv.pct_change().dropna())
    return res, m


if __name__ == "__main__":
    PANEL = load_panel()
    print(f"面板: {PANEL.index[0].date()} → {PANEL.index[-1].date()}, {PANEL.shape[1]} 资产, {len(PANEL)} 日")
    print(f"bond_short 覆盖: {PANEL['bond_short'].first_valid_index().date()} 起\n")

    rows = []
    nvs = {}
    for label, assets, buckets, strat in [
        ("V3-B RP 基线", V3B_RP_ASSETS, V3B_RP_BUCKETS, "V3-B 风险平价"),
        ("V3-B RP +短融", ["hs300", "us_sp500", "credit", "bond_short", "bond_30y", "gold", "nonferr", "wti"],
         with_short(V3B_RP_BUCKETS), "V3-B 风险平价"),
        ("V3-B Con 基线", V3B_CON_ASSETS, None, "V3-B 保守增强"),
        ("V3-B Con +短融", ["hs300", "us_sp500", "credit", "bond_short", "bond_10y", "bond_30y", "gold", "nonferr", "wti"],
         None, "V3-B 保守增强"),
    ]:
        res, m = run(label, assets, buckets, strat)
        nvs[label] = res.nv
        rows.append({"方案": label, **{k: m.get(k) for k in m}})
        w = res.weight_df
        if w is not None and len(w):
            last = w.iloc[-1]
            print(f"{label}: 最新权重 " + ", ".join(f"{k}={v:.1%}" for k, v in last.items() if v > 0.005))

    print("\n===== 指标对比 =====")
    keys = ["cagr", "mdd", "sharpe", "calmar", "ann_vol", "win_rate"]
    df = pd.DataFrame(rows).set_index("方案")
    cols = [c for c in df.columns if any(k in c.lower() for k in keys)]
    if not cols:
        cols = list(df.columns)
    print(df[cols].to_string())
