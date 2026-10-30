"""RP+短融（2019 起）：完整净值/回撤曲线 + 逐年收益 + 回撤明细。"""
import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from allweather.data import load_panel
from allweather.pipeline import strategy_backtest_kwargs
from allweather.strategy_b import backtest_b
from allweather.stats import perf_metrics
from allweather.config import V3B_RP_ASSETS, V3B_RP_BUCKETS

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def with_short(buckets):
    return {k: (["bond_short"] + v if k == "收益垫" else list(v)) for k, v in buckets.items()}


def rp(panel, buckets, assets):
    rets = panel.pct_change().dropna()
    kw = strategy_backtest_kwargs("V3-B 风险平价")
    kw["rp_buckets"] = buckets
    return backtest_b(rets[assets], **kw)


def drawdown_episodes(nv, top=5):
    dd = nv / nv.cummax() - 1
    episodes, cur = [], None
    for d, v in dd.items():
        if v < 0 and cur is None:
            cur = {"start": d, "trough": d, "trough_dd": v}
        elif v < 0 and cur is not None:
            if v < cur["trough_dd"]:
                cur["trough"], cur["trough_dd"] = d, v
        elif v >= 0 and cur is not None:
            cur["end"] = d
            episodes.append(cur)
            cur = None
    if cur is not None:
        cur["end"] = None
        episodes.append(cur)
    episodes.sort(key=lambda e: e["trough_dd"])
    return episodes[:top]


if __name__ == "__main__":
    panel = load_panel().loc["2019-01-01":]
    base = rp(panel, V3B_RP_BUCKETS, V3B_RP_ASSETS)
    short_assets = ["hs300", "us_sp500", "credit", "bond_short", "bond_30y", "gold", "nonferr", "wti"]
    short = rp(panel, with_short(V3B_RP_BUCKETS), short_assets)
    for name, res in [("RP 基线", base), ("RP+短融", short)]:
        m = perf_metrics(res.nv, rets=res.nv.pct_change().dropna())
        print(f"{name}: CAGR {m['cagr']:.2%} MDD {m['mdd']:.2%} Sharpe {m['sharpe']:.2f} Calmar {m['calmar']:.2f}")

    # 图
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 1]})
    ax1.plot(base.nv.index, base.nv.values, label="RP 基线", color="#202124", lw=1.4)
    ax1.plot(short.nv.index, short.nv.values, label="RP + 短融 ETF", color="#d93025", lw=1.6)
    ax1.set_title("V3-B 风险平价：加入短融 ETF（2019-01 → 2026-10）", fontsize=14)
    ax1.set_ylabel("累计净值")
    ax1.legend(loc="upper left")
    ax1.grid(alpha=.25)
    for ax, res, c in [(ax2, base, "#9aa0a6"), (ax2, short, "#d93025")]:
        dd = res.nv / res.nv.cummax() - 1
        ax.fill_between(dd.index, dd.values * 100, 0, color=c, alpha=.4 if res is base else .5,
                        label="基线回撤" if res is base else "短融回撤")
    ax2.set_ylabel("回撤 %")
    ax2.legend(loc="lower left")
    ax2.grid(alpha=.25)
    fig.tight_layout()
    out = "outputs/rp_shortbond_2019.png"
    fig.savefig(out, dpi=130)
    print("图:", out)

    # 逐年收益
    print("\n===== 逐年收益 %（2019 起）=====")
    for name, res in [("基线", base), ("RP+短融", short)]:
        y = res.nv.resample("YE").last()
        y = pd.concat([pd.Series([1.0], index=[res.nv.index[0]]), y])
        yr = y.pct_change().dropna()
        print(name, {str(k.year): round(v * 100, 2) for k, v in yr.items()})

    # 回撤明细
    print("\n===== RP+短融 回撤 TOP5 =====")
    for e in drawdown_episodes(short.nv):
        print(f"  {e['trough_dd']:.2%} | {e['start'].date()} → {e['trough'].date()}（谷底）| 修复: {e['end'].date() if e['end'] else '未修复'}")

    # 净值导出
    pd.DataFrame({"RP 基线": base.nv, "RP+短融": short.nv}).to_csv("outputs/rp_shortbond_2019.csv")
    print("净值CSV: outputs/rp_shortbond_2019.csv")
