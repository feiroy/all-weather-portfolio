"""A/B 实验：红利低波(H30269) **替换** 沪深300（A股腿整体换掉），三策略 + 逐年收益。

口径警告：H30269 是价格指数（不含分红），红利低波全收益每年另含约 4-5pp 股息。
"""
import pandas as pd

from allweather.data import load_panel
from allweather.pipeline import strategy_backtest_kwargs
from allweather.strategy_b import backtest_b
from allweather.backtest import backtest_iv
from allweather.stats import perf_metrics
from allweather.config import V3B_RP_ASSETS, V3B_CON_ASSETS, V3C_ASSETS


def run(panel, strategy):
    rets = panel.pct_change().dropna()
    kw = strategy_backtest_kwargs(strategy)
    if strategy == "V3c 多元":
        return backtest_iv(rets, **kw)
    assets = V3B_RP_ASSETS if strategy == "V3-B 风险平价" else V3B_CON_ASSETS
    return backtest_b(rets[assets], **kw)


if __name__ == "__main__":
    panel = load_panel()
    div = pd.read_csv("data/dividend_lowvol_idx.csv", parse_dates=["date"], index_col="date")["close"]
    panel2 = panel.copy()
    panel2["hs300"] = div.reindex(panel2.index).ffill()

    rows = []
    yearly = {}
    for strat in ["V3-B 风险平价", "V3-B 保守增强", "V3c 多元"]:
        for label, p in [("基线", panel), ("红利低波替换", panel2)]:
            m = perf_metrics((res := run(p, strat)).nv, rets=res.nv.pct_change().dropna())
            rows.append({"策略": strat, "方案": label, "CAGR": m["cagr"], "MDD": m["mdd"],
                         "Sharpe": m["sharpe"], "Calmar": m["calmar"]})
            if strat == "V3-B 风险平价":
                yearly[label] = res.nv.resample("YE").last().pct_change()

    print("===== 三策略：红利低波替换沪深300 =====")
    print(pd.DataFrame(rows).set_index(["策略", "方案"]).to_string(float_format=lambda x: f"{x:.4f}"))

    y = pd.DataFrame(yearly)
    y.index = y.index.year
    y = (y * 100).round(2)
    print("\n===== V3-B RP 逐年收益（%，首年为部分年度）=====")
    print(y.to_string())
