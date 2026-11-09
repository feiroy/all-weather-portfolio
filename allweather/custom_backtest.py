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


# 老策略兼容：V7 基金池把「原油 LOF」换成了能源化工 ETF，ETF_META 里已经没有 wti。
# 用户浏览器里存着的旧策略仍带 'wti'（当年是资产 key、不是 6 位代码），不兜底就会报
# 「基金 wti 拉不到净值」——拿着内部 key 当代码去查，用户完全看不懂（2026-11-09 验收发现）。
_LEGACY_KEY_CODE = {"wti": "501018"}


def _resolve(key: str, panel: pd.DataFrame):
    """一个 key → (净值序列, 名称, 来源, 展示代码)。"""
    import fund_lookup as FL
    from allweather.config import ETF_META

    code2asset = {v["code"]: k for k, v in ETF_META.items()}
    asset = code2asset.get(key, key)
    if asset in panel.columns:
        m = ETF_META.get(asset, {})
        return panel[asset], m.get("name") or asset, "策略资产", m.get("code") or key

    key = _LEGACY_KEY_CODE.get(key, key)   # 已下线的老资产 key → 真实基金代码
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


def canonical_key(key, panel) -> str:
    """6 位代码 → 内部资产 key（仅当该资产在长历史面板里）。

    `_resolve` 用 '511220' 和 'credit' 取到的是同一条净值，但回测引擎按列名找避风港
    （`credit_idx = col_idx.get("credit", -1)`）、按列名配分桶和逐资产趋势窗口。用户输代码
    加进来的城投债会以 '511220' 当列名，于是趋势过滤静默失效，还会被误判成「缺避风港」
    （2026-11-09 用户截图）。这里在进引擎之前统一归一化，保证两种写法结果逐位一致。
    资产不在面板时保持 6 位代码，走真实基金净值，行为不变。
    """
    from allweather.config import ETF_META
    code2asset = {v["code"]: k for k, v in ETF_META.items() if v.get("code")}
    a = code2asset.get(str(key), str(key))
    return a if a in panel.columns else str(key)


# === 策略工厂：页面参数 → 回测引擎参数 ===
# 原则：这里只做「名字翻译」，不复制任何回测逻辑；真正的计算全部交给 allweather.backtest.backtest()。
# 这样页面验证的结果和改 config 跑出来的结果必然一致（tests/test_custom_strategy.py 有逐位一致性断言）。
METHODS = {"fixed": "固定权重", "inverse_vol": "逆波动率", "risk_parity": "风险平价"}
REBAL_FREQ = {"M": "monthly", "B": "biweekly", "W": "weekly"}


def bucket_plan(columns, rp_buckets: dict | None) -> tuple[dict, bool]:
    """实际生效的分桶结构 —— 引擎与页面展示的唯一事实源。

    分桶是 {桶名: [资产key]} 的静态表，但持仓随时可以增删改，所以每次回测都按当前持仓重算：
      1. 去掉持仓里已不存在的 key，再删掉随之变空的桶；
      2. 只要还有资产没被任何桶覆盖，就整表退化成「每资产一桶」，并返回 fallback=True。
    不能让新基金静默拿 0 权重，也不能让页面还以为在按原来的 4 桶跑（2026-11-09 用户指出）。
    """
    cols = list(columns)
    colset = set(cols)
    bk = {k: [x for x in v if x in colset] for k, v in (rp_buckets or {}).items()}
    bk = {k: v for k, v in bk.items() if v}
    covered = {a for v in bk.values() for a in v}
    if not bk or covered != colset:
        return {c: [c] for c in cols}, True
    return bk, False


def build_engine_kwargs(rets, method="inverse_vol", window=20, max_w=0.25, min_w=0.02,
                        cash_ratio=0.0, rebal="M", trend_commodity=75, trend_gold=0, trend_equity=0,
                        trend_map=None, target_vol=None, vol_window=60, rp_buckets=None,
                        safe_asset="credit"):
    """页面参数 → backtest() 的关键字参数。

    趋势过滤统一走引擎的「逐资产窗口」通道（equity_trend_assets / equity_trend_windows）：
    引擎对任意列都支持「收盘价跌破 N 日均线 → 该资产权重转给信用债」，与非农/黄金/能化那三个
    专用参数行为完全一致（见 backtest.py `_apply_trend` 第 48-77 行），所以这里不再用专用参数，
    资产名也不写死 —— 用户加任意基金（科技 ETF、行业 ETF）都能单独设窗口。

    trend_map: {资产key: SMA窗口}，0 或缺失 = 该资产不做过滤；优先级高于下面三个兼容参数。
    trend_commodity / trend_gold / trend_equity: 旧的三组简化写法，会翻译成 trend_map。
    """
    kw = dict(cash_ratio=float(cash_ratio or 0.0),
              rebal_freq=REBAL_FREQ.get(str(rebal).upper(), "monthly"),
              track_weights=True,
              safe_asset=str(safe_asset or "credit"),   # 趋势避风港：默认 credit，可指定持仓里任意一只
              hs300_value_dip=False,          # 抄底已于 2026-11-04 撤掉，工厂不再暴露
              gold_dip_threshold=None)
    if trend_map is None:
        wc, wg, we = (int(trend_commodity or 0), int(trend_gold or 0), int(trend_equity or 0))
        trend_map = {}
        for c in rets.columns:
            if c in ("nonferr", "ene"):
                trend_map[c] = wc
            elif c == "gold":
                trend_map[c] = wg
            elif c in ("hs300", "us_sp500", "divlow"):
                trend_map[c] = we
    tm = {str(k): int(v or 0) for k, v in (trend_map or {}).items() if int(v or 0) > 0 and k in rets.columns}
    if target_vol:
        # 波动率上限：组合年化波动超过它就等比降敞口（风险平价内置 9%），复刻时必须带上
        kw.update(target_vol=float(target_vol), vol_target_window=int(vol_window or 60))
    kw.update(nonferr_trend_window=0, wti_trend_window=0, gold_trend_filter=False,
              equity_trend_assets=list(tm) or None,
              equity_trend_windows=tm or None,
              equity_trend_window=0)
    m = str(method or "fixed").lower()
    if m == "risk_parity":
        # 分桶按当前持仓现算（bucket_plan 是唯一事实源）：覆盖不全就退化成每资产一桶并打标记，
        # 页面会把这个标记显示出来，不再出现「卡片写 4 桶、实际按 9 桶算」。
        bk, fallback = bucket_plan(rets.columns, rp_buckets)
        if fallback:
            kw["_buckets_fallback"] = True
        kw.update(weighting_method="hierarchical_rp", rp_window=int(window or 20),
                  rp_buckets=bk, bucket_method="equal",
                  max_w=float(max_w), min_w=float(min_w))
    elif m == "inverse_vol":
        kw.update(weighting_method="inverse_vol", iv_window=int(window or 20),
                  max_w=float(max_w), min_w=float(min_w))
    else:
        raise ValueError(f"未知加权方式 {method}（可选 fixed / inverse_vol / risk_parity）")
    return kw


def run_engine(rets, kw):
    """按 pipeline.run_strategy_backtest 的同一规则调度引擎。

    必须走 strategy_b.backtest_b / backtest_iv 这两个包装，不能用 backtest() 直调：
    backtest() 的 weighting_method 默认是 inverse_vol，而 backtest_b 默认 hierarchical_rp，
    直调会让「风险平价」静默变成「逆波动率」（实测年化 8.63% → 8.00%）。
    """
    from allweather.strategy_b import backtest_b
    from allweather.backtest import backtest_iv
    return backtest_iv(rets, **kw) if "assets" in kw else backtest_b(rets, **kw)


def custom_series(rets, method="fixed", weights=None, freq="M", **params):
    """自定义策略的净值序列。返回 (净值, 调仓次数, 期末目标权重)。

    method='fixed' 走原来的固定权重+定期再平衡；其余走统一回测引擎。
    """
    m = str(method or "fixed").lower()
    if m == "fixed":
        w = pd.Series(weights or {})
        w = w / w.sum()
        nv = fixed_weight_backtest(rets[list(w.index)], w, freq)
        return nv / float(nv.iloc[0]), (0 if freq == "N" else None), w
    kw = build_engine_kwargs(rets, method=m, rebal=freq, **params)
    kw.pop("_buckets_fallback", None)      # 仅内部标记（分桶覆盖不全 → 已降级为每资产一桶），不传给引擎
    # 这里直调 backtest() 是安全的：build_engine_kwargs 一定显式给出 weighting_method，
    # 不会踩到 backtest() 与 backtest_b() 默认值不同（inverse_vol vs hierarchical_rp）的坑。
    from allweather.backtest import backtest
    r = backtest(rets, **kw)
    last = r.weight_df.iloc[-1] if r.weight_df is not None and len(r.weight_df) else pd.Series(dtype=float)
    return r.nv, int(r.n_rebal), last


def custom_compare(weights: dict | None = None, start: str = "2015-01-01",
                   freq: str = "M", name: str = "我的组合",
                   funds: list | None = None, method: str = "fixed",
                   window: int = 20, max_w: float = 0.25, min_w: float = 0.02,
                   cash_ratio: float = 0.0, trend_commodity: int = 75,
                   trend_gold: int = 0, trend_equity: int = 0,
                   trend_map: dict | None = None, target_vol: float | None = None,
                   vol_window: int = 60, rp_buckets: dict | None = None,
                   safe_asset: str = "credit",
                   engine_kwargs: dict | None = None) -> dict:
    """内置三策略（每月末调仓）+ 自定义基金组合的对比，结构与 /api/market/backtest 一致。

    funds: [{key: 资产key或6位代码, weight: 百分比, name?, code?}, ...]；
    不传 funds 时兼容旧的 {资产key: 百分比} 写法。权重按合计归一。
    """
    from allweather.data import load_panel, panel_returns
    from allweather.pipeline import run_strategy_backtest
    from allweather.stats import perf_metrics

    panel = load_panel()
    raw_items = funds if funds is not None else [{"key": k, "weight": v} for k, v in (weights or {}).items()]
    items = [it for it in raw_items
             if it.get("weight") is not None and float(it["weight"]) > 0]
    if not items:
        raise ValueError("至少选一只基金并给一个大于 0 的权重")
    method = str(method or "fixed").lower()
    if method == "fixed":
        if freq not in ("M", "Q", "N"):
            freq = "M"
    elif freq not in ("M", "B", "W"):
        freq = "M"

    ck = lambda k: canonical_key(k, panel)  # noqa: E731 — 6 位代码统一转成内部资产 key
    cols, meta, wmap = {}, {}, {}
    for it in items:
        key = ck(str(it.get("key") or "").strip())
        if not key or key in cols:
            continue
        s, nm, src, code = _resolve(key, panel)
        cols[key] = s.reindex(panel.index).ffill()
        meta[key] = {"name": it.get("name") or nm, "code": it.get("code") or code, "src": src}
        wmap[key] = float(it["weight"])
    keys = list(cols)
    # 趋势窗口 / 分桶也是按资产 key 索引的，用户用 6 位代码带进来的要一起归一化，
    # 否则会「明明配了却匹配不上列名」。trend_map=None 时仍传 None，保持原来的兼容参数路径。
    tm_default = {"nonferr": trend_commodity, "ene": trend_commodity, "gold": trend_gold,
                  "hs300": trend_equity, "us_sp500": trend_equity, "divlow": trend_equity}
    tm_canon = None if trend_map is None else {ck(k): v for k, v in trend_map.items()}
    eff_tm = tm_canon if tm_canon is not None else {ck(k): v for k, v in tm_default.items()}
    rp_buckets = {b: [ck(x) for x in (v or [])] for b, v in (rp_buckets or {}).items()} or None
    # 趋势过滤的避风港是引擎里写死的 credit_idx（backtest.py:52）：组合里没有 credit 时，
    # 所有 `and credit_idx >= 0` 分支都不成立，趋势开关会静默失效（实测跌破均线仍满仓）。
    # 这里显式报错，让用户补上城投债或关掉窗口，而不是拿一条没有风控的曲线去下结论。
    # 避风港可配置：默认 credit（内置三策略口径），自定义策略可以指定持仓里的任意一只
    # （如把城投债换成 161119 中债 LOF）。这里先归一化，再按当前持仓校验。
    safe_asset = ck(str(safe_asset or "credit"))
    trend_on = any(int(v or 0) > 0 and str(k) in keys for k, v in (eff_tm or {}).items())
    if method != "fixed" and trend_on and safe_asset not in keys:
        # 报错要点名「实际收到哪些基金」：用户常把城投债替换成另一只债基（161119 等），
        # 数量不变，页面看着仍像内置 8 只，只说「缺避风港」根本定位不到（2026-11-09 用户连问三轮）。
        codes = "、".join(str(meta[k]["code"]) for k in keys)
        if any(ck(str(it.get("key") or "").strip()) == safe_asset for it in raw_items):
            raise ValueError(
                f"「{safe_asset}」的权重是 0，等于没持有，趋势过滤没有避风港。"
                "请给它一个大于 0 的权重，或把所有均线窗口设为 0。"
            )
        if safe_asset != "credit":
            raise ValueError(
                f"趋势过滤选的避风港「{safe_asset}」不在当前持仓里。当前持仓代码：{codes}。"
                "请在编辑器里把「避风港」改成持仓中的一只，或先把那只基金加进来。"
            )
        raise ValueError(
            "趋势过滤需要城投债 ETF（511220）作避风港（跌破均线时权重转到它）。"
            f"当前持仓代码：{codes} —— 里面没有 511220（可能被替换成了别的债基）。"
            "请在「常用资产」里加入「城投债 ETF」，或把所有均线窗口设为 0。"
        )
    px = pd.DataFrame(cols)
    first = {k: px[k].first_valid_index() for k in keys}
    bad = [meta[k]["name"] for k in keys if first[k] is None]
    if bad:
        raise ValueError(f"{'、'.join(bad)} 在回测区间内没有净值")
    # 起点取「所有选中基金都有日收益」的第一天（与 pipeline.strategy_window 同一规则）：
    # 只用价格首个有效日会多出一天 NaN 收益，风险平价/逆波动率的窗口会因此错位。
    px_rets = px.pct_change(fill_method=None).iloc[1:]
    first_ret = {k: px_rets[k].first_valid_index() for k in keys}
    eff = max(pd.Timestamp(start), max(v for v in first_ret.values() if v is not None))
    if len(px.loc[eff:]) < 2:
        raise ValueError("所选基金的可用区间太短，换更早成立的基金或把起点提前")
    # 收益必须先在全历史上算、再切片：内置引擎是「整条面板 pct_change 后丢首行」，
    # 若在切片后再 pct_change 会晚一天，导致自定义策略与内置策略差一个交易日（实测年化差 0.01pp）。
    fund_rets = px_rets.loc[eff:].dropna()
    panel_rets = panel_returns(panel).loc[eff:]
    # 二者同起点同交易日轴；万一有缺行，补齐后按 0 收益处理，不让曲线错位
    if len(fund_rets) != len(panel_rets):
        fund_rets = fund_rets.reindex(panel_rets.index).fillna(0.0)

    w = pd.Series({k: wmap[k] for k in keys})
    w = w / w.sum() if w.sum() > 0 else w
    out, n_reb = {}, {}
    for n in ("V3-B 保守增强", "V3-B 风险平价", "V3c 多元"):
        r = run_strategy_backtest(panel_rets, n, "monthly")
        out[n] = r.nv
        n_reb[n] = int(r.n_rebal)
    if method == "fixed" and w.sum() <= 0:
        raise ValueError("固定权重模式至少要给一只基金一个大于 0 的权重")
    if engine_kwargs:
        # 高级通道：直接把引擎参数原样透传（测试用它证明「参数化没有复制回测逻辑」）
        ekw = dict(engine_kwargs)
        ekw.setdefault("track_weights", True)
        r_c = run_engine(fund_rets[keys], ekw)
        nv, n_reb_custom = r_c.nv, int(r_c.n_rebal)
        last_w = r_c.weight_df.iloc[-1] if r_c.weight_df is not None and len(r_c.weight_df) else w
    else:
        nv, n_reb_custom, last_w = custom_series(
            fund_rets[keys], method=method,
            weights={k: float(w[k]) for k in keys}, freq=freq,
            window=window, max_w=max_w, min_w=min_w, cash_ratio=cash_ratio,
            trend_commodity=trend_commodity, trend_gold=trend_gold, trend_equity=trend_equity,
            trend_map=tm_canon, target_vol=target_vol, vol_window=vol_window,
            rp_buckets=rp_buckets, safe_asset=safe_asset)
    nv.index = panel_rets.index
    label = (str(name or "").strip()[:16]) or "我的组合"
    if label in out:
        label = label[:12] + "·自定义"
    out[label] = nv / float(nv.iloc[0])
    if n_reb_custom is None:      # 固定权重模式：按调仓周期数计
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
            "calmar": None if short else r4(m["calmar"]),
            "n": n_reb_custom if k == label else n_reb.get(k, 0), "short": short,
        })
        # 与内置接口同一口径：曲线保持日频，不要降采样成周收盘 ——
        # ① 卡片年化/回撤按日净值算，周收盘会让「图/卡」对不上；
        # ② 区间起点落在周中（如 2025/11/06 周四）时，周频曲线取不到起点值，tooltip 和区间指标全是「—」
        s = nv0
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
    # 把「实际生效的分桶」回传给页面：改过持仓后桶数/结构可能已经变了，卡片不能再说原来的 4 桶。
    bucket_info = None
    if method == "risk_parity":
        bk, fb = bucket_plan(keys, rp_buckets)
        bucket_info = {"mode": "fallback" if fb else "buckets", "count": len(bk),
                       "buckets": {k: list(v) for k, v in bk.items()},
                       "requested": len(rp_buckets or {})}
    return {"rows": rows, "curves": curves, "periods": periods, "bucket_info": bucket_info,
            "weights": {k: r4(float(last_w.get(k, 0.0)) * 100) for k in keys},
            "funds": [{"key": k, "name": meta[k]["name"], "code": meta[k]["code"],
                       "src": meta[k]["src"], "w": r4(float(last_w.get(k, 0.0)) * 100),
                       "from": f"{first[k]:%Y-%m-%d}"} for k in keys],
            "start": start, "start_actual": f"{eff:%Y-%m-%d}", "freq": freq,
            "method": method, "safe_asset": safe_asset}
