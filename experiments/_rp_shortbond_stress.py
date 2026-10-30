"""RP+短融（2019 起）：股债双杀等压力场景收益对比。"""
import pandas as pd

from allweather.data import load_panel
from allweather.pipeline import strategy_backtest_kwargs
from allweather.strategy_b import backtest_b
from allweather.config import V3B_RP_ASSETS, V3B_RP_BUCKETS

EVENTS = [
    ("2020 疫情", "2020-02-19", "2020-03-23"),
    ("2022 股债双杀", "2022-01-04", "2022-11-30"),
    ("2022 理财赎回", "2022-10-30", "2022-12-31"),
    ("2024-08 长债", "2024-08-01", "2024-09-30"),
    ("2025-9 关税", "2025-09-01", "2025-10-31"),
    ("2026-10-30 股债双杀", "2026-10-28", "2026-10-30"),
]


def with_short(buckets):
    return {k: (["bond_short"] + v if k == "收益垫" else list(v)) for k, v in buckets.items()}


def rp(panel, buckets, assets):
    rets = panel.pct_change().dropna()
    kw = strategy_backtest_kwargs("V3-B 风险平价")
    kw["rp_buckets"] = buckets
    return backtest_b(rets[assets], **kw)


def event_ret(nv, start, end):
    seg = nv.loc[start:end]
    if len(seg) < 2:
        return None
    return float(seg.iloc[-1] / seg.iloc[0] - 1)


if __name__ == "__main__":
    # 压力场景覆盖 2022 年，不能从 2019 砍区间
    panel = load_panel()
    base = rp(panel, V3B_RP_BUCKETS, V3B_RP_ASSETS)
    short = rp(panel, with_short(V3B_RP_BUCKETS),
               ["hs300", "us_sp500", "credit", "bond_short", "bond_30y", "gold", "nonferr", "wti"])

    rows = []
    for name, start, end in EVENTS:
        b = event_ret(base.nv, start, end)
        s = event_ret(short.nv, start, end)
        if b is None:
            continue
        rows.append({"场景": name, "RP 基线": f"{b:.2%}", "RP+短融": f"{s:.2%}",
                     "差值": f"{(s - b) * 100:+.2f}pp"})
    print(pd.DataFrame(rows).set_index("场景").to_string())

    # 2022 股债双杀区间内的最大回撤（比区间收益更说明体感）
    for name, start, end in [("2022 股债双杀", "2022-01-04", "2022-11-30"),
                             ("2026-10-30", "2026-10-28", "2026-10-30")]:
        for label, res in [("基线", base), ("RP+短融", short)]:
            seg = res.nv.loc[start:end]
            if len(seg) < 2:
                continue
            dd = (seg / seg.cummax() - 1).min()
            print(f"{name} | {label}: 区间收益 {seg.iloc[-1]/seg.iloc[0]-1:+.2%}，区间内最大回撤 {dd:.2%}")
