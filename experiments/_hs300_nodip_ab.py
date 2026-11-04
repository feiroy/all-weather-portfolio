"""A/B：沪深300 抄底 三种做法 —— 不做 / 只在进场那次加（原项目口径） / 持有到退出。

不做 = hs300_value_dip=False，其余参数与 pipeline.strategy_backtest_kwargs 完全相同。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from allweather import data as D
from allweather.config import STRESS_EVENTS
from allweather.pipeline import run_strategy_backtest
from allweather.risk import _precompute_percentile
from allweather.stats import perf_metrics
from _hs300_hold_ab import long_panel, seg_ret

VARIANTS = [("不做", dict(hs300_value_dip=False)),
            ("进场那次加", dict()),
            ("持有到退出", dict(hs300_hold_until_exit=True))]


def run(panel, st, extra):
    rets = panel.pct_change().dropna()
    return run_strategy_backtest(rets, st, hs300_pb_data=PB, hs300_pe_data=PE,
                                 hs300_pb_pct=PB_PCT, hs300_pe_pct=PE_PCT, **extra).nv


def report(tag, panel, strategies):
    print(f"\n{'=' * 78}\n{tag}：{panel.index[0]:%Y-%m-%d} → {panel.index[-1]:%Y-%m-%d}"
          f"（{len(panel) / 252:.1f} 年）\n{'=' * 78}")
    rows = []
    for st in strategies:
        nvs = {nm: run(panel, st, ex) for nm, ex in VARIANTS}
        for nm, nv in nvs.items():
            m = perf_metrics(nv, rets=nv.pct_change().dropna())
            dd = nv / nv.cummax() - 1
            rows.append([st, nm, m["cagr"], m["mdd"], f"{dd.idxmin():%Y/%m}", m["sharpe"], m["calmar"],
                         m["vol"], float(nv.iloc[-1])])
        base = nvs["不做"]
        diffs = []
        for ev, a, b in STRESS_EVENTS:
            if pd.Timestamp(a) < base.index[0]:
                continue
            r = {nm: seg_ret(nv, a, b) for nm, nv in nvs.items()}
            if max(r.values()) - min(r.values()) >= 0.001:
                diffs.append(f"{ev} " + " / ".join(f"{v:+.2%}" for v in r.values()))
        if diffs:
            print(f"\n【{st}】压力区间（不做 / 进场那次加 / 持有到退出）：\n  " + "\n  ".join(diffs))
        yb = {nm: nv.resample("YE").last().pct_change() for nm, nv in nvs.items()}
        d1 = (yb["进场那次加"] - yb["不做"]).dropna()
        d1 = d1[d1.abs() >= 0.001]
        if len(d1):
            print("  逐年差（进场那次加 − 不做）：" + "  ".join(f"{d.year} {v * 100:+.2f}pp" for d, v in d1.items()))
    df = pd.DataFrame(rows, columns=["策略", "抄底", "年化", "最大回撤", "回撤最深", "夏普", "卡玛", "波动", "期末净值"])
    fmt = {"年化": "{:.2%}", "最大回撤": "{:.2%}", "夏普": "{:.2f}", "卡玛": "{:.2f}", "波动": "{:.2%}",
           "期末净值": "{:.3f}"}
    print("\n" + df.to_string(index=False, formatters={k: v.format for k, v in fmt.items()}))


if __name__ == "__main__":
    PB, PE = D.load_hs300_pb(), D.load_hs300_pe()
    PB_PCT, PE_PCT = _precompute_percentile(PB), _precompute_percentile(PE)
    report("长区间（不含短融）", long_panel(), ["V3-B 保守增强", "V3c 多元"])
    report("官方面板（含短融）", D.load_panel(), ["V3-B 保守增强", "V3-B 风险平价", "V3c 多元"])
