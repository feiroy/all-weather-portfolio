"""复现 GitHub 上的经典战术资产配置（TAA）策略，检验对本项目的帮助。

来源：
  oronimbus/tactical-asset-allocation (pyTAA)  src/pytaa/strategy/README.md
  jhbale11/Asset-Allocation                     DAA / VAA / Golden Butterfly
  原论文：Keller & Keuning (DAA/VAA/PAA)、Antonacci (GEM)、Faber (Ivy/GTAA)、
          Browne (Permanent)、Tyler (Golden Butterfly)

资产池映射（原策略用美股 ETF，这里换成项目面板）：
  SPY/T.Stock → hs300      EFA/海外 → us_sp500       QQQ/成长 → ndx
  小盘价值 → divlow        DBC/商品 → nonferr|ene    GLD → gold
  AGG/LQD/IEF → credit|bond_10y|bond_30y
  现金 → 0 收益

注意：原策略的阈值是按 12 个资产定的，这里资产数不同，按比例缩放并标注。

运行：./myenv/bin/python experiments/_taa_repro.py
"""
import sys

sys.path.insert(0, '.')
sys.path.insert(0, 'streamlit_app')

import numpy as np
import pandas as pd

from allweather import data as D
from allweather import pipeline as P
from allweather.config import V3B_RP_ASSETS
from allweather.data import _load_optional
from allweather.pipeline import panel_returns, run_strategy_backtest
from allweather.stats import perf_metrics


def load_ndx(index_like):
    import akshare as ak
    src = pd.read_csv('/tmp/ixic.csv', parse_dates=['日期']).set_index('日期').sort_index()
    usdcny = _load_optional("usdcny")
    comb = src.index.union(usdcny.index)
    cny = (pd.to_numeric(src["最新价"], errors="coerce").reindex(comb).ffill()
           * usdcny.reindex(comb).ffill()).dropna()
    cny = cny[cny.index <= index_like.max()]
    ret = cny.pct_change()
    return ret.reindex(index_like.union(ret.index)).ffill().reindex(index_like)


full = panel_returns(D.load_panel())
full["ndx"] = load_ndx(full.index)

RISK = ["hs300", "us_sp500", "ndx", "divlow", "gold", "nonferr"]
SAFE = ["credit", "bond_10y", "bond_30y"]


def yearly(nv):
    ye = nv.resample("YE").last()
    return pd.Series({ye.index[i].year: ye.iloc[i] / ye.iloc[i - 1] - 1
                      for i in range(1, len(ye))})


def M(tag, nv):
    q = perf_metrics(nv)
    y = yearly(nv)
    return dict(策略=tag, 年化=q["cagr"] * 100, 波动=q["vol"] * 100, 回撤=q["mdd"] * 100,
                夏普=q["sharpe"], Calmar=q["cagr"] / abs(q["mdd"]),
                负年=f"{int((y < 0).sum())}/{len(y)}", 最差年=y.min() * 100, _y=y)


def backtest_weights(rets, weight_fn, name):
    """weight_fn(date, i) -> pd.Series 目标权重；月度调仓，下一交易日起生效。"""
    dates = rets.index
    month_ends = pd.DatetimeIndex(sorted(set(
        pd.Series(dates, index=dates).groupby([dates.year, dates.month]).last().values)))
    idx = {d: i for i, d in enumerate(dates)}
    rows = {}
    for d in month_ends:
        i = idx[d]
        if i < 270:
            continue
        w = weight_fn(rets, i)
        if w is not None and w.sum() > 1e-9:
            rows[d] = w
    W = pd.DataFrame(rows).T.reindex(columns=rets.columns).fillna(0.0)
    r = rets.copy()
    r["__cash"] = 0.0
    ws = W.reindex(dates).ffill().shift(1).fillna(0.0)
    port = (ws * r.reindex(columns=ws.columns)).sum(axis=1)
    return M(name, (1 + port).cumprod())


def zscore(rets, i, col):
    """Keller 动量分 Z = 12*p/p-1 + 4*p/p-3 + 2*p/p-6 + p/p-12 - 19（月）。"""
    p = (1 + rets[col].iloc[:i + 1]).cumprod()

    def at(k):
        j = i - 21 * k
        return p.iloc[j] if j >= 0 else np.nan
    try:
        v = (12 * p.iloc[i] / at(1) + 4 * p.iloc[i] / at(3)
             + 2 * p.iloc[i] / at(6) + p.iloc[i] / at(12) - 19)
    except Exception:
        return np.nan
    return v if np.isfinite(v) else np.nan


def sma_ok(rets, i, col, months=10):
    p = (1 + rets[col].iloc[:i + 1]).cumprod()
    if len(p) < 21 * months:
        return False
    return p.iloc[-1] > p.iloc[-21 * months:].mean()


# ---------- 1. Ivy Portfolio（Faber）：等权，价格 > 10 月均线才持有 ----------
def ivy(rets, i):
    keep = [c for c in RISK if sma_ok(rets, i, c)]
    w = pd.Series(0.0, index=rets.columns)
    if keep:
        w[keep] = 1 / len(keep)
    return w


# ---------- 2. VAA-G4（Keller）：全正才满仓风险，否则全避险 ----------
def vaa_g4(rets, i):
    z = {c: zscore(rets, i, c) for c in RISK}
    z = {k: v for k, v in z.items() if np.isfinite(v)}
    w = pd.Series(0.0, index=rets.columns)
    if not z:
        return w
    if all(v > 0 for v in z.values()):
        w[max(z, key=z.get)] = 1.0
    else:
        zs = {c: zscore(rets, i, c) for c in SAFE}
        zs = {k: v for k, v in zs.items() if np.isfinite(v)}
        if zs:
            w[max(zs, key=zs.get)] = 1.0
    return w


# ---------- 3. DAA（Keller & Keuning）：canary 宽度决定攻守 ----------
CANARY = ["nonferr", "credit"]      # 周期品 + 信用，作为 risk-on/off 探针


def daa(rets, i):
    neg = 0
    for c in CANARY:
        z = zscore(rets, i, c)
        if np.isfinite(z) and z < 0:
            neg += 1
    w = pd.Series(0.0, index=rets.columns)
    iz = {c: zscore(rets, i, c) for c in RISK}
    iz = {k: v for k, v in iz.items() if np.isfinite(v)}
    sz = {c: zscore(rets, i, c) for c in SAFE}
    sz = {k: v for k, v in sz.items() if np.isfinite(v)}
    if neg >= 2:
        if sz:
            w[max(sz, key=sz.get)] = 1.0
    elif neg == 1:
        if sz:
            w[max(sz, key=sz.get)] = 0.5
        top = sorted(iz, key=iz.get, reverse=True)[:3]
        if top:
            for c in top:
                w[c] += 0.5 / len(top)
    else:
        top = sorted(iz, key=iz.get, reverse=True)[:6]
        for c in top:
            w[c] = 1.0 / len(top)
    return w


# ---------- 4. PAA（Keller）：相对 12 月均线的广度 ----------
def paa(rets, i):
    pos = 0
    for c in RISK:
        p = (1 + rets[c].iloc[:i + 1]).cumprod()
        if len(p) < 252:
            continue
        if p.iloc[-1] / p.iloc[-252:].mean() - 1 > 0:
            pos += 1
    w = pd.Series(0.0, index=rets.columns)
    n = len(RISK)
    thr = n // 2                       # 原版 12 个资产、阈值 6，按比例缩放
    sz = {c: zscore(rets, i, c) for c in SAFE}
    sz = {k: v for k, v in sz.items() if np.isfinite(v)}
    if pos < thr:
        if sz:
            w[max(sz, key=sz.get)] = 1.0
        return w
    safe_w = (n - pos) / (n - thr)
    if sz:
        w[max(sz, key=sz.get)] = safe_w
    iz = {c: zscore(rets, i, c) for c in RISK}
    iz = {k: v for k, v in iz.items() if np.isfinite(v)}
    top = sorted(iz, key=iz.get, reverse=True)[:max(1, pos)]
    for c in top:
        w[c] += (1 - safe_w) / len(top)
    return w


# ---------- 5. GEM 双动量（Antonacci） ----------
def gem(rets, i):
    def r12(c):
        s = rets[c].iloc[max(0, i - 252):i + 1]
        return (1 + s).prod() - 1
    w = pd.Series(0.0, index=rets.columns)
    rh, rc = r12("hs300"), r12("credit")
    if rh > 0:
        w["hs300" if rh >= rc else "us_sp500"] = 1.0
    else:
        w["credit"] = 1.0
    return w


# ---------- 6. 静态：Permanent / Golden Butterfly ----------
def permanent(rets, i):
    w = pd.Series(0.0, index=rets.columns)
    for c, x in [("hs300", .25), ("bond_30y", .25), ("gold", .25)]:
        w[c] = x
    return w          # 剩余 25% 现金（0 收益）


def golden_butterfly(rets, i):
    # 小盘价值用 divlow 代理；若该窗口没有 divlow，则并入 hs300
    w = pd.Series(0.0, index=rets.columns)
    legs = [("hs300", .20), ("bond_30y", .20), ("credit", .20), ("gold", .20)]
    if "divlow" in rets.columns:
        legs.append(("divlow", .20))
    else:
        legs[0] = ("hs300", .40)
    for c, x in legs:
        w[c] = x
    return w


# ================= 跑 =================
for tag, start in [("生产窗口 2013-12 起（含 divlow）", "2013-12-19"),
                   ("长样本 2006-12 起（剔 divlow，否则基线会被截断到 2013-12）", "2006-12-20")]:
    long_run = start.startswith("2006")
    drop = {"divlow"} if long_run else set()
    RISK = [c for c in ["hs300", "us_sp500", "ndx", "divlow", "gold", "nonferr"] if c not in drop]
    rets = full.loc[full.index >= start].dropna(subset=["ndx"]).copy()
    if drop:
        rets = rets.drop(columns=[c for c in drop if c in rets.columns])
    rows = []
    P.STRATEGY_ASSETS["V3-B 风险平价"] = [a for a in V3B_RP_ASSETS if a not in drop]
    base = run_strategy_backtest(rets, "V3-B 风险平价", "monthly")
    rows.append(M("【基线】V3-B 风险平价", base.nv))
    for fn, name in [(ivy, "Ivy(10月均线等权)"), (vaa_g4, "VAA-G4"),
                     (daa, "DAA(canary宽度)"), (paa, "PAA(12月均线广度)"),
                     (gem, "GEM双动量"), (permanent, "Permanent Portfolio"),
                     (golden_butterfly, "Golden Butterfly")]:
        try:
            rows.append(backtest_weights(rets, fn, name))
        except Exception as e:
            print(f"  {name} 失败: {repr(e)[:60]}")
    print("=" * 116)
    print(f"{tag}（{rets.index.min().date()} ~ {rets.index.max().date()}，{len(rets)/252:.1f} 年）")
    print("=" * 116)
    df = pd.DataFrame([{k: v for k, v in r.items() if k != "_y"} for r in rows])
    for c in ["年化", "波动", "回撤", "夏普", "Calmar", "最差年"]:
        df[c] = df[c].round(2)
    df["达标10/8"] = np.where((df["年化"] >= 10) & (df["回撤"] >= -8), "✓", "✗")
    print(df[["策略", "年化", "波动", "回撤", "夏普", "Calmar", "负年", "最差年", "达标10/8"]]
          .to_string(index=False))
    for r in rows:
        if (r["_y"] < 0).any():
            print(f"    {r['策略']:<26} 负年: " + ", ".join(
                f"{k} {v*100:.2f}%" for k, v in r["_y"][r["_y"] < 0].items()))
    print()
