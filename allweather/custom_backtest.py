"""自定义策略的回测计算（H5 策略工厂）。

基金池里的每一项可以是：
  * 9 个策略资产 key（hs300 / gold / ...）—— 用 load_panel() 的长历史面板，与内置三策略同基准；
  * 任意 6 位基金代码 —— 用 streamlit_app/fund_lookup.py 的复权净值。

所有选中基金对齐到同一交易日轴，并自动把回测起点提升到「所有基金都有数据」的最早共同日，
保证自定义策略与内置三策略在同一区间、同一口径下对比。没数据的基金显式报错，不静默跳过。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# fund_lookup 在 streamlit_app/ 下，api/server.py 已把它加入 sys.path；
# 这里补一层兜底，便于单独 import 本模块跑测试。
_SS = Path(__file__).resolve().parent.parent / "streamlit_app"
if str(_SS) not in sys.path:
    sys.path.insert(0, str(_SS))


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


def _resolve(key: str, panel: pd.DataFrame):
    """一个 key → (净值序列, 名称, 来源, 展示代码)。"""
    import fund_lookup as FL
    from allweather.config import ETF_META

    code2asset = {v["code"]: k for k, v in ETF_META.items()}
    asset = code2asset.get(key, key)
    if asset in panel.columns:
        m = ETF_META.get(asset, {})
        return panel[asset], m.get("name") or asset, "策略资产", m.get("code") or key

    nav = FL.build_nav(key)
    if nav is None or len(nav) < 2:
        try:
            FL.ensure_fresh(key)
        except Exception:  # noqa: BLE001 — 网络失败在下面统一变成明确报错
            pass
        nav = FL.build_nav(key)
    if nav is None or len(nav) < 2:
        raise ValueError(f"基金 {key} 拉不到净值，换一只或先到「基金检索」查一次")
    return nav, FL.fund_name(key) or key, "基金净值", key


def custom_compare(weights: dict | None = None, start: str = "2015-01-01",
                   freq: str = "M", name: str = "我的组合",
                   funds: list | None = None) -> dict:
    """内置三策略（每月末调仓）+ 自定义基金组合的对比，结构与 /api/market/backtest 一致。

    funds: [{key: 资产key或6位代码, weight: 百分比, name?, code?}, ...]；
    不传 funds 时兼容旧的 {资产key: 百分比} 写法。权重按合计归一。
    """
    from allweather.data import load_panel
    from allweather.pipeline import run_strategy_backtest
    from allweather.stats import perf_metrics

    panel = load_panel()
    items = funds if funds is not None else [{"key": k, "weight": v} for k, v in (weights or {}).items()]
    items = [it for it in items
             if it.get("weight") is not None and float(it["weight"]) > 0]
    if not items:
        raise ValueError("至少选一只基金并给一个大于 0 的权重")
    if freq not in ("M", "Q", "N"):
        freq = "M"

    cols, meta, wmap = {}, {}, {}
    for it in items:
        key = str(it.get("key") or "").strip()
        if not key or key in cols:
            continue
        s, nm, src, code = _resolve(key, panel)
        cols[key] = s.reindex(panel.index).ffill()
        meta[key] = {"name": it.get("name") or nm, "code": it.get("code") or code, "src": src}
        wmap[key] = float(it["weight"])
    keys = list(cols)
    px = pd.DataFrame(cols)
    first = {k: px[k].first_valid_index() for k in keys}
    bad = [meta[k]["name"] for k in keys if first[k] is None]
    if bad:
        raise ValueError(f"{'、'.join(bad)} 在回测区间内没有净值")
    eff = max(pd.Timestamp(start), max(first.values()))
    seg = px.loc[eff:]
    if len(seg) < 2:
        raise ValueError("所选基金的可用区间太短，换更早成立的基金或把起点提前")
    fund_rets = seg.pct_change().iloc[1:]
    panel_rets = panel.loc[eff:].pct_change().iloc[1:]
    # 二者同起点同交易日轴；万一有缺行，补齐后按 0 收益处理，不让曲线错位
    if len(fund_rets) != len(panel_rets):
        fund_rets = fund_rets.reindex(panel_rets.index).fillna(0.0)

    w = pd.Series({k: wmap[k] for k in keys})
    w = w / w.sum()
    out, n_reb = {}, {}
    for n in ("V3-B 保守增强", "V3-B 风险平价", "V3c 多元"):
        r = run_strategy_backtest(panel_rets, n, "monthly")
        out[n] = r.nv
        n_reb[n] = int(r.n_rebal)
    nv = fixed_weight_backtest(fund_rets[keys], w, freq)
    nv.index = panel_rets.index
    label = (str(name or "").strip()[:16]) or "我的组合"
    if label in out:
        label = label[:12] + "·自定义"
    out[label] = nv / float(nv.iloc[0])
    n_reb_custom = 0 if freq == "N" else int(
        (panel_rets.index.to_period(freq)[1:] != panel_rets.index.to_period(freq)[:-1]).sum())

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
            "weights": {k: r4(w[k] * 100) for k in keys},
            "funds": [{"key": k, "name": meta[k]["name"], "code": meta[k]["code"],
                       "src": meta[k]["src"], "w": r4(w[k] * 100),
                       "from": f"{first[k]:%Y-%m-%d}"} for k in keys],
            "start": start, "start_actual": f"{eff:%Y-%m-%d}", "freq": freq}
