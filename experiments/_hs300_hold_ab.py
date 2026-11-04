"""A/B：沪深300 抄底加仓「只在进场那次调仓」（基线，原项目口径） vs 「持有到退出条件满足」。

进场：沪深300 较历史最高点回撤 > 25% 且 PB 分位 < 30% 且 价格 > SMA120
退出：回撤收窄到 15% 以内（价格 ≥ 历史最高 × 0.85）且 PE 分位 > 70%
加仓：沪深300 权重 × 1.8，多出来的从城投债扣（城投债不够扣就不加）

两段区间：
  长区间 2005 起：只能跑保守增强、V3c（它们不用短融；短融指数 2015 才有，会把面板截到 2015）
  官方面板 2015 起：三个策略都跑（即网页「模型 · 回测」用的面板）
不改任何默认配置：开关 hs300_hold_until_exit 默认 False。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from allweather import data as D
from allweather.config import BACKTEST_START, BACKTEST_END, SAFETY_DEDUCT, STRESS_EVENTS
from allweather.pipeline import run_strategy_backtest
from allweather.risk import _precompute_percentile
from allweather.stats import perf_metrics


def long_panel() -> pd.DataFrame:
    """load_panel 去掉短融：其余 8 个资产都能回到 2005。"""
    b10 = D._load_bond_10y()
    nf = D.stitch_series(
        D.load_series("nonferr"),
        D.stitch_series(D.load_series("nonferr_idx"), D.load_series("shfe_copper"), annual_deduct=0.0095),
        annual_deduct=SAFETY_DEDUCT["nonferr"])
    p = pd.DataFrame({
        "hs300": D._load_with_index("hs300", "hs300_idx", annual_deduct=0.0),
        "us_sp500": D._load_sp500_cny(),
        "credit": D._load_with_index("bond_credit", "credit_idx", annual_deduct=0.0),
        "bond_10y": b10,
        "bond_30y": D.synthesize_bond_30y(b10, D.load_series("bond_30y_etf")),
        "gold": D._load_gold_cny(), "nonferr": nf, "wti": D._load_wti_cny(),
    })
    p.index = pd.to_datetime(p.index)
    p = p.sort_index().loc[BACKTEST_START:BACKTEST_END].ffill()
    return p.loc[p.apply(lambda s: s.first_valid_index()).max():].dropna()


def episodes(sig: pd.DataFrame) -> list[tuple]:
    """signal_df 的 active 列 → [(进场调仓日, 最后一个抄底调仓日)]。"""
    if sig is None or "active" not in sig:
        return []
    if "date" in sig.columns:
        sig = sig.set_index(pd.to_datetime(sig["date"]))
    a = sig["active"].fillna(False).astype(bool)
    out, s0, prev = [], None, None
    for d, v in a.items():
        if v and s0 is None:
            s0 = d
        if not v and s0 is not None:
            out.append((s0, prev)); s0 = None
        prev = d
    if s0 is not None:
        out.append((s0, prev))
    return out


def seg_ret(nv: pd.Series, a, b) -> float:
    s = nv.loc[a:b]
    return float(s.iloc[-1] / s.iloc[0] - 1) if len(s) > 1 else float("nan")


def seg_mdd(nv: pd.Series, a, b) -> float:
    s = nv.loc[a:b]
    return float((s / s.cummax() - 1).min()) if len(s) > 1 else float("nan")


def run(panel, strategy, hold):
    rets = panel.pct_change().dropna()
    return run_strategy_backtest(rets, strategy, track_weights=True, track_signals=True,
                                 hs300_pb_data=PB, hs300_pe_data=PE,
                                 hs300_pb_pct=PB_PCT, hs300_pe_pct=PE_PCT,
                                 hs300_hold_until_exit=hold)


def report(tag, panel, strategies):
    print(f"\n{'=' * 78}\n{tag}：{panel.index[0]:%Y-%m-%d} → {panel.index[-1]:%Y-%m-%d}"
          f"（{len(panel) / 252:.1f} 年）\n{'=' * 78}")
    rows = []
    for st in strategies:
        base, hold = run(panel, st, False), run(panel, st, True)
        mb = perf_metrics(base.nv, rets=base.nv.pct_change().dropna())
        mh = perf_metrics(hold.nv, rets=hold.nv.pct_change().dropna())
        wb, wh = base.weight_df["hs300"], hold.weight_df["hs300"]
        boosted_b = int((wb > 0).sum() and ((wh / wb.replace(0, np.nan)) > 1.3).sum())
        eps = episodes(hold.signal_df)
        rows.append([st, "进场那次", mb["cagr"], mb["mdd"], mb["sharpe"], mb["calmar"], mb["vol"],
                     float(base.nv.iloc[-1])])
        rows.append([st, "持有到退出", mh["cagr"], mh["mdd"], mh["sharpe"], mh["calmar"], mh["vol"],
                     float(hold.nv.iloc[-1])])
        print(f"\n【{st}】抄底期 {len(eps)} 段；「持有到退出」比基线多加仓的调仓月 {boosted_b} 个")
        for a, b in eps:
            print(f"  抄底期 {a:%Y-%m} → {b:%Y-%m}（{(wh.loc[a:b] > 0).sum()} 个调仓月）  "
                  f"区间收益 基线 {seg_ret(base.nv, a, b):+.2%} / 持有 {seg_ret(hold.nv, a, b):+.2%}  "
                  f"区间回撤 基线 {seg_mdd(base.nv, a, b):.2%} / 持有 {seg_mdd(hold.nv, a, b):.2%}  "
                  f"沪深300 平均权重 {wb.loc[a:b].mean():.1%} → {wh.loc[a:b].mean():.1%}")
        st_rows = []
        for nm, a, b in STRESS_EVENTS:
            if pd.Timestamp(a) < base.nv.index[0]:
                continue
            rb, rh = seg_ret(base.nv, a, b), seg_ret(hold.nv, a, b)
            if abs(rh - rb) >= 0.0005:
                st_rows.append(f"{nm} {rb:+.2%}→{rh:+.2%}")
        if st_rows:
            print("  压力区间有差别的：" + "；".join(st_rows))
        yb = base.nv.resample("YE").last().pct_change()
        yh = hold.nv.resample("YE").last().pct_change()
        dy = (yh - yb).dropna()
        dy = dy[dy.abs() >= 0.001]
        if len(dy):
            print("  逐年差（持有 − 基线）：" + "  ".join(f"{d.year} {v * 100:+.2f}pp" for d, v in dy.items()))
    df = pd.DataFrame(rows, columns=["策略", "抄底加仓", "年化", "最大回撤", "夏普", "卡玛", "波动", "期末净值"])
    fmt = {"年化": "{:.2%}", "最大回撤": "{:.2%}", "夏普": "{:.2f}", "卡玛": "{:.2f}",
           "波动": "{:.2%}", "期末净值": "{:.3f}"}
    print("\n" + df.to_string(index=False, formatters={k: v.format for k, v in fmt.items()}))
    return df


if __name__ == "__main__":
    PB, PE = D.load_hs300_pb(), D.load_hs300_pe()
    PB_PCT, PE_PCT = _precompute_percentile(PB), _precompute_percentile(PE)
    report("长区间（不含短融）", long_panel(), ["V3-B 保守增强", "V3c 多元"])
    report("官方面板（含短融）", D.load_panel(), ["V3-B 保守增强", "V3-B 风险平价", "V3c 多元"])
