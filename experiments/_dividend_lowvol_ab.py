"""A/B 实验：V3-B RP 的 A 股腿用 红利低波(H30269) 替换 沪深300 的对比。"""
import pandas as pd

from allweather.data import load_panel
from allweather.pipeline import strategy_backtest_kwargs
from allweather.strategy_b import backtest_b
from allweather.stats import perf_metrics, yearly_returns
from allweather.config import V3B_RP_ASSETS, V3B_RP_BUCKETS


def rp_run(panel, label):
    rets = panel.pct_change().dropna()
    kw = strategy_backtest_kwargs("V3-B 风险平价")
    res = backtest_b(rets[V3B_RP_ASSETS], **kw)
    m = perf_metrics(res.nv, rets=res.nv.pct_change().dropna())
    return res, m


if __name__ == "__main__":
    panel = load_panel()
    div = pd.read_csv("data/dividend_lowvol_idx.csv", parse_dates=["date"], index_col="date")["close"]
    panel2 = panel.copy()
    panel2["hs300"] = div.reindex(panel2.index).ffill()  # 仅替换 A 股腿，其余不动

    base, m1 = rp_run(panel, "基线")
    dl, m2 = rp_run(panel2, "红利低波")

    keys = ["cagr", "mdd", "sharpe", "calmar"]
    df = pd.DataFrame([{"方案": "V3-B RP 基线(沪深300)", **{k: m1.get(k) for k in keys}},
                       {"方案": "V3-B RP A股腿=红利低波", **{k: m2.get(k) for k in keys}}]).set_index("方案")
    print("===== V3-B RP 组合层面对比 =====")
    print(df.to_string())

    # 单独看两条腿自身
    h = panel["hs300"].loc[div.index.min():]
    d = div.reindex(panel.index).dropna().loc[div.index.min():]
    for name, s in [("沪深300", h), ("红利低波H30269", d)]:
        r = s.pct_change().dropna()
        years = (s.index[-1] - s.index[0]).days / 365.25
        cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1
        mdd = (s / s.cummax() - 1).min()
        print(f"\n{name}: CAGR {cagr:.2%}  MDD {mdd:.2%}  年化波动 {r.std()*252**0.5:.2%}  期间 {s.index[0].date()}→{s.index[-1].date()}")
