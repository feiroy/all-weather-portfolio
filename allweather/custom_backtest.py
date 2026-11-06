"""自定义固定权重策略的回测计算（H5 策略工厂与 Streamlit 策略工厂共用）。

只做「自定义百分比」一种模式：选若干回测资产、给每个百分比、按频率再平衡。
计算与内置策略回测同一份净值面板、同一套 perf_metrics 口径，不另写一套。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def fixed_weight_backtest(rets: pd.DataFrame, weights: pd.Series, freq: str = "M") -> pd.Series:
    """固定目标权重 + 定期再平衡的净值。freq: M=月, Q=季, N=不再平衡（买入持有）。

    与 Streamlit 版 `_fixed_weight_backtest` 完全一致：每期只用该期最后一条真实净值，
    期间内权重随涨跌漂移，换期才拉回目标权重。
    """
    w = (weights / weights.sum()).values
    h = w.copy()
    v = 1.0
    nv = pd.Series(index=rets.index, dtype=float)
    nv.iloc[0] = 1.0
    period = rets.index.to_period(freq) if freq != "N" else None
    arr = rets.values
    for i in range(1, len(rets)):
        r = arr[i]
        v *= 1 + float(np.dot(h, r))
        nv.iloc[i] = v
        h = h * (1 + r)
        s = h.sum()
        h = h / s if s > 0 else w.copy()
        if period is not None and period[i] != period[i - 1]:
            h = w.copy()
    return nv


def custom_compare(weights: dict, start: str = "2015-01-01", freq: str = "M", name: str = "我的组合") -> dict:
    """内置三策略（每月末调仓）+ 自定义权重策略的对比结果，结构与 /api/market/backtest 一致。

    weights: {资产 key: 百分比}，前端传的是 0~100 的数字，这里按合计归一。
    """
    from allweather.data import load_panel
    from allweather.pipeline import run_strategy_backtest
    from allweather.stats import perf_metrics

    panel = load_panel().loc[start:]
    rets = panel.pct_change().dropna()
    keys = [k for k, v in weights.items() if v is not None and float(v) > 0 and k in rets.columns]
    if not keys:
        raise ValueError("至少选一只基金并给一个大于 0 的权重")
    if freq not in ("M", "Q", "N"):
        freq = "M"
    w = pd.Series({k: float(weights[k]) for k in keys})
    w = w / w.sum()

    out, n_reb = {}, {}
    for n in ("V3-B 保守增强", "V3-B 风险平价", "V3c 多元"):
        r = run_strategy_backtest(rets, n, "monthly")
        out[n] = r.nv
        n_reb[n] = int(r.n_rebal)
    nv = fixed_weight_backtest(rets[keys], w, freq)
    nv.index = rets.index
    label = (str(name or "").strip()[:16]) or "我的组合"
    out[label] = nv / float(nv.iloc[0])
    if freq == "N":
        n_reb_custom = 0
    else:
        p = rets.index.to_period(freq)
        n_reb_custom = int((p[1:] != p[:-1]).sum())

    r4 = lambda x: round(float(x), 4)  # noqa: E731
    rows, curves = [], {}
    for k, nv0 in out.items():
        m = perf_metrics(nv0, rets=nv0.pct_change().dropna())
        short = len(nv0) < 252
        rows.append({
            "name": k, "ret": r4((float(nv0.iloc[-1]) / float(nv0.iloc[0]) - 1) * 100),
            "cagr": r4(m["cagr"] * 100), "mdd": r4(m["mdd"] * 100),
            "sharpe": None if short else r4(m["sharpe"]), "vol": r4(m["vol"] * 100),
            "n": n_reb_custom if k == label else n_reb.get(k, 0), "short": short,
        })
        s = nv0 if len(nv0) < 600 else nv0.resample("W-FRI").last().dropna()
        curves[k] = {"dates": [f"{d:%Y-%m-%d}" for d in s.index],
                     "ret": [round((float(v) / float(s.iloc[0]) - 1) * 100, 3) for v in s]}

    def _periods(freq_r, limit):
        acc = {}
        for k, nv0 in out.items():
            try:
                s = nv0.resample(freq_r).last().dropna()
                prev = nv0.iloc[0]
                for d, v in s.items():
                    key = f"{d:%Y-%m}" if freq_r == "ME" else f"{d:%Y}"
                    acc.setdefault(key, {})[k] = r4((float(v) / float(prev) - 1) * 100)
                    prev = v
            except Exception:  # noqa: BLE001
                continue
        return [{"k": k, "v": v} for k, v in sorted(acc.items(), reverse=True)[:limit]]
    periods = {"monthly": _periods("ME", 24), "yearly": _periods("YE", 12)}
    return {"rows": rows, "curves": curves, "periods": periods,
            "weights": {k: r4(w[k] * 100) for k in keys}, "freq": freq, "start": start}
