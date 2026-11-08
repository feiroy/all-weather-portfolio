"""策略工厂（自定义策略）的回归测试。

核心诉求：页面上调参验证策略，**不能是另一套回测逻辑**，否则页面结论和正式回测会不一致。
所以这里的关键断言是：
  1. 把内置三策略的参数原样透传给自定义策略，净值必须与 run_strategy_backtest 逐点一致；
  2. 页面参数（加权方式/窗口/趋势过滤）只是「名字翻译」，映射到引擎参数后结果一致；
  3. 固定权重模式保持原有行为，不受影响。
"""
import numpy as np
import pandas as pd
import pytest

import allweather.pipeline as P
from allweather.custom_backtest import build_engine_kwargs, custom_compare, custom_series


@pytest.fixture(scope="module")
def panel():
    from allweather.data import load_panel
    return load_panel()


@pytest.mark.parametrize("strategy", ["V3-B 保守增强", "V3-B 风险平价", "V3c 多元"])
def test_engine_passthrough_reproduces_builtin(panel, strategy):
    """透传内置策略参数 → 自定义策略的指标必须与内置完全一致。"""
    rets = P.panel_returns(panel)
    builtin = P.run_strategy_backtest(rets, strategy)
    start = f"{builtin.nv.index[0]:%Y-%m-%d}"
    assets = [c for c in P.STRATEGY_ASSETS[strategy] if c in panel.columns]
    out = custom_compare(start=start, name="验证", method="inverse_vol",
                         funds=[{"key": a, "weight": 100 / len(assets)} for a in assets],
                         engine_kwargs=P.strategy_backtest_kwargs(strategy))
    row = out["rows"][-1]
    from allweather.stats import perf_metrics
    m = perf_metrics(builtin.nv)
    assert row["cagr"] == pytest.approx(round(m["cagr"] * 100, 4), abs=1e-6), strategy
    assert row["mdd"] == pytest.approx(round(m["mdd"] * 100, 4), abs=1e-6), strategy
    assert row["n"] == int(builtin.n_rebal), strategy
    assert out["start_actual"] == start, strategy


def test_build_engine_kwargs_translates_trends(panel):
    """趋势现在统一走「逐资产窗口」通道：专用参数应全部关闭，避免同一资产被处理两次。"""
    rets = P.panel_returns(panel)
    kw = build_engine_kwargs(rets, method="inverse_vol", window=20, max_w=0.25,
                             trend_map={"hs300": 30, "us_sp500": 75, "gold": 0})
    assert kw["nonferr_trend_window"] == 0 and kw["wti_trend_window"] == 0
    assert kw["gold_trend_filter"] is False
    assert kw["equity_trend_assets"] == ["hs300", "us_sp500"]      # gold 窗口 0 被剔除
    assert kw["equity_trend_windows"] == {"hs300": 30, "us_sp500": 75}
    assert kw["weighting_method"] == "inverse_vol" and kw["iv_window"] == 20

    # 旧的三组简化写法仍可用，会被翻译成逐资产窗口
    legacy = build_engine_kwargs(rets, method="inverse_vol", trend_commodity=75, trend_gold=75, trend_equity=30)
    assert legacy["equity_trend_windows"]["nonferr"] == 75
    assert legacy["equity_trend_windows"]["ene"] == 75
    assert legacy["equity_trend_windows"]["gold"] == 75
    assert legacy["equity_trend_windows"]["hs300"] == 30

    rp = build_engine_kwargs(rets[["hs300", "credit", "gold"]], method="risk_parity", window=20)
    assert rp["weighting_method"] == "hierarchical_rp"
    assert rp["rp_buckets"] == {"hs300": ["hs300"], "credit": ["credit"], "gold": ["gold"]}

    with pytest.raises(ValueError):
        build_engine_kwargs(rets, method="unknown")


def test_trend_filter_actually_changes_result(panel):
    """趋势过滤必须真的生效：关掉 vs 打开 75 日，净值不应相同。"""
    rets = P.panel_returns(panel)
    assets = [c for c in P.STRATEGY_ASSETS["V3-B 保守增强"] if c in rets.columns]
    r = rets[assets].dropna()
    on, n_on, _ = custom_series(r, method="inverse_vol", window=20, trend_commodity=75, trend_gold=75)
    off, n_off, _ = custom_series(r, method="inverse_vol", window=20, trend_commodity=0, trend_gold=0)
    assert n_on != n_off or abs(float(on.iloc[-1] / off.iloc[-1]) - 1) > 1e-4


def test_fixed_weight_unchanged(panel):
    """固定权重模式仍走老的 fixed_weight_backtest，权重按合计归一。"""
    rets = P.panel_returns(panel)
    funds = [{"key": "hs300", "weight": 60}, {"key": "credit", "weight": 40}]
    out = custom_compare(start="2019-01-01", name="半股半债", method="fixed", freq="M", funds=funds)
    row = out["rows"][-1]
    assert out["weights"]["hs300"] == pytest.approx(60.0, abs=0.05)
    assert out["weights"]["credit"] == pytest.approx(40.0, abs=0.05)
    assert row["n"] > 50           # 月频 7 年 ≈ 84 次
    assert out["method"] == "fixed"


def test_strategy_spec_matches_config():
    """回测页展示的「持仓 + 设置」必须和真实配置一致，否则用户照着抄会抄错。"""
    import importlib.util
    from pathlib import Path
    import allweather.pipeline as P
    from allweather.config import ETF_META

    spec = importlib.util.spec_from_file_location("srv", Path("api/server.py"))
    srv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(srv)
    for name in ("V3-B 保守增强", "V3-B 风险平价", "V3c 多元"):
        sp = srv._strategy_spec(name)
        assert [a["key"] for a in sp["assets"]] == list(P.STRATEGY_ASSETS[name])
        for a in sp["assets"]:
            assert a["code"] == ETF_META[a["key"]]["code"]
        kw = P.strategy_backtest_kwargs(name)
        assert sp["window"] == kw.get("rp_window") or sp["window"] == P.STRATEGY_PARAMS[
            {"V3-B 保守增强": "con", "V3-B 风险平价": "rp", "V3c 多元": "v3c"}[name]]["window"]
        assert sp["trend"]["commodity"] == kw["nonferr_trend_window"]
        assert sp["trend"]["ene"] == kw["wti_trend_window"]
        assert sp["method_key"] in ("inverse_vol", "risk_parity")


def _builtin_trend_map(kw):
    tm = {}
    if kw.get("nonferr_trend_window"): tm["nonferr"] = kw["nonferr_trend_window"]
    if kw.get("wti_trend_window"): tm["ene"] = kw["wti_trend_window"]
    if kw.get("gold_trend_filter"): tm["gold"] = kw.get("gold_trend_window", 75)
    for e in (kw.get("equity_trend_assets") or []):
        tm[e] = (kw.get("equity_trend_windows") or {}).get(e, kw.get("equity_trend_window"))
    return tm


@pytest.mark.parametrize("strategy", ["V3-B 保守增强", "V3-B 风险平价", "V3c 多元"])
def test_per_asset_trend_map_reproduces_builtin(panel, strategy):
    """逐资产趋势窗口（页面现在的配置方式）必须能逐位复现内置策略。

    这条最关键：内置用 nonferr/ene/gold 三个专用参数 + 权益列表，工厂统一改成「每资产一个窗口」，
    如果两条路径行为不一致，用户在页面上验证出来的结论就是错的。
    """
    from allweather.custom_backtest import custom_series
    from allweather.stats import perf_metrics
    import allweather.pipeline as P

    rets = P.panel_returns(panel)
    kw = P.strategy_backtest_kwargs(strategy)
    assets = [c for c in P.STRATEGY_ASSETS[strategy] if c in rets.columns]
    r = rets[assets].dropna()
    method = "risk_parity" if strategy.endswith("风险平价") else "inverse_vol"
    nv, n, _ = custom_series(r, method=method, window=kw.get("rp_window", 20),
                             max_w=kw.get("max_w") or 0.2, min_w=kw.get("min_w", 0.02),
                             trend_map=_builtin_trend_map(kw), target_vol=kw.get("target_vol"),
                             vol_window=kw.get("vol_target_window", 60), rp_buckets=kw.get("rp_buckets"))
    b = P.run_strategy_backtest(rets, strategy)
    mb, mc = perf_metrics(b.nv), perf_metrics(nv)
    assert mc["cagr"] == pytest.approx(mb["cagr"], abs=1e-9), strategy
    assert mc["mdd"] == pytest.approx(mb["mdd"], abs=1e-9), strategy
    assert n == int(b.n_rebal), strategy


def test_buckets_not_covering_all_assets_falls_back(panel):
    """用户加进来的基金不在原分桶里时，必须退化成「每资产一桶」，不能让它永远 0 权重。"""
    from allweather.custom_backtest import build_engine_kwargs

    rets = P.panel_returns(panel)[["hs300", "credit", "gold"]]
    kw = build_engine_kwargs(rets, method="risk_parity",
                             rp_buckets={"增长↑": ["hs300"], "收益垫": ["credit"]})   # gold 未覆盖
    assert kw["_buckets_fallback"] is True
    assert kw["rp_buckets"] == {"hs300": ["hs300"], "credit": ["credit"], "gold": ["gold"]}

    full = build_engine_kwargs(rets, method="risk_parity",
                               rp_buckets={"增长↑": ["hs300", "gold"], "收益垫": ["credit"]})
    assert not full.get("_buckets_fallback")
    assert full["rp_buckets"] == {"增长↑": ["hs300", "gold"], "收益垫": ["credit"]}


def test_bucket_plan_follows_current_holdings():
    """分桶必须按当前持仓重算：增 / 换 / 删 / 没带分桶四种情况都不能静默算错（2026-11-09）。"""
    from allweather.config import V3B_RP_BUCKETS
    from allweather.custom_backtest import bucket_plan

    base = list(P.STRATEGY_ASSETS["V3-B 风险平价"])
    bk, fb = bucket_plan(base, V3B_RP_BUCKETS)
    assert not fb and len(bk) == 4 and bk == {k: list(v) for k, v in V3B_RP_BUCKETS.items()}

    # 新增基金：旧分桶覆盖不全 → 明确退化，不能让新基金拿 0 权重还不告诉用户
    bk, fb = bucket_plan(base + ["515000"], V3B_RP_BUCKETS)
    assert fb and len(bk) == len(base) + 1 and bk["515000"] == ["515000"]

    # 删掉收益垫桶里唯一的资产：该桶被删掉，桶数从 4 变 3（页面要能显示这个变化）
    bk, fb = bucket_plan([c for c in base if c != "credit"], V3B_RP_BUCKETS)
    assert not fb and len(bk) == 3 and "收益垫" not in bk

    # 从零新建（没复刻内置）：每资产一桶
    bk, fb = bucket_plan(base, None)
    assert fb and len(bk) == len(base)

    # 引擎与展示共用同一个规则
    rets = pd.DataFrame(np.zeros((30, len(base))), columns=base)
    kw = build_engine_kwargs(rets, method="risk_parity", rp_buckets=V3B_RP_BUCKETS)
    plan, _ = bucket_plan(base, V3B_RP_BUCKETS)
    assert kw["rp_buckets"] == plan


def test_custom_compare_reports_effective_buckets():
    """接口必须回传「实际生效的分桶」，改过持仓时页面才能显示退化警告。"""
    from allweather.config import V3B_RP_BUCKETS

    funds = [{"key": "hs300", "weight": 50}, {"key": "credit", "weight": 50}]
    rp = {"增长↑": ["hs300"], "收益垫": ["credit"]}
    ok = custom_compare(start="2024-01-01", name="两资产", method="risk_parity",
                        funds=funds, rp_buckets=rp, trend_map={})
    assert ok["bucket_info"]["mode"] == "buckets"
    assert ok["bucket_info"]["count"] == 2
    assert ok["bucket_info"]["buckets"] == rp

    # 老策略：分桶是旧快照，持仓多了一只不在桶里的基金
    stale = custom_compare(start="2024-01-01", name="旧分桶", method="risk_parity",
                           funds=funds + [{"key": "gold", "weight": 30}],
                           rp_buckets=rp, trend_map={})
    assert stale["bucket_info"]["mode"] == "fallback"
    assert stale["bucket_info"]["count"] == 3
    assert stale["bucket_info"]["requested"] == 2


def test_trend_filter_requires_safe_asset():
    """没有 credit 时趋势过滤会静默失效（引擎 credit_idx=-1），必须显式报错而不是照跑。"""
    funds = [{"key": "hs300", "weight": 60}, {"key": "gold", "weight": 40}]
    with pytest.raises(ValueError, match="作避风港"):
        custom_compare(start="2024-01-01", name="无避风港", method="inverse_vol",
                       funds=funds, trend_map={"hs300": 30})

    # 关掉所有窗口，或补上城投债，都应该照常能跑
    assert "error" not in custom_compare(start="2024-01-01", name="关过滤", method="inverse_vol",
                                         funds=funds, trend_map={})
    safe = custom_compare(start="2024-01-01", name="有避风港", method="inverse_vol",
                          funds=funds + [{"key": "credit", "weight": 20}],
                          trend_map={"hs300": 30})
    assert safe["start_actual"]

    # 城投债在持仓里但权重填 0：上面会被过滤掉，不能笼统说「缺避风港」
    with pytest.raises(ValueError, match="权重是 0"):
        custom_compare(start="2024-01-01", name="零权重", method="inverse_vol",
                       funds=funds + [{"key": "credit", "weight": 0}],
                       trend_map={"hs300": 30})

    # 把城投债替换成别的债基：报错必须列出实际持仓代码，用户一眼看到 511220 不在
    with pytest.raises(ValueError, match="当前持仓代码") as ei:
        custom_compare(start="2024-01-01", name="换债基", method="inverse_vol",
                       funds=funds + [{"key": "511010", "code": "511010", "weight": 20}],
                       trend_map={"hs300": 30})
    assert "511010" in str(ei.value) and "511220" in str(ei.value)


def test_safe_asset_configurable():
    """避风港可配置：可以选持仓里任意一只承接跌破均线的权重（2026-11-09 用户要求）。

    默认仍必须是 credit，保证内置三策略与旧自定义策略逐位不变。
    """
    base = [{"key": "hs300", "weight": 50}, {"key": "credit", "weight": 30},
            {"key": "bond_30y", "weight": 20}]
    tm = {"hs300": 30}
    kw = dict(start="2021-01-01", method="inverse_vol", trend_map=tm)

    d = custom_compare(name="避风港对照", funds=base, **kw)
    assert d["safe_asset"] == "credit"                     # 不传就是城投债，行为不变
    c = custom_compare(name="避风港对照", funds=base, safe_asset="credit", **kw)
    assert c["rows"] == d["rows"] and c["safe_asset"] == "credit"

    # 换成 30 年国债当避风港：权重转移目标变了，结果必须不同
    b = custom_compare(name="避风港对照", funds=base, safe_asset="bond_30y", **kw)
    assert b["safe_asset"] == "bond_30y"
    assert b["rows"] != d["rows"], "避风港从 credit 换成 bond_30y 后结果应变化"

    # 指定的避风港不在持仓里 → 明确报错，不许静默回退
    with pytest.raises(ValueError, match="不在当前持仓里"):
        custom_compare(start="2021-01-01", name="x", method="inverse_vol",
                       funds=base, trend_map=tm, safe_asset="161119")


def test_safe_asset_accepts_code_alias():
    """输 6 位代码 511220 加的城投债，必须和用内部 key credit 完全等价（2026-11-09 用户截图）。

    `_resolve` 两种写法取到同一条净值，但引擎按列名找 credit_idx；不归一化会误报
    「缺避风港」，而且趋势过滤静默失效。分桶 / 趋势窗口里写代码的也要一起认。
    """
    from allweather.config import ETF_META
    from allweather.custom_backtest import canonical_key
    from allweather.data import load_panel

    panel = load_panel()
    code = ETF_META["credit"]["code"]
    assert canonical_key(code, panel) == "credit"
    assert canonical_key("credit", panel) == "credit"
    assert canonical_key("999999", panel) == "999999"   # 不在面板里的保持 6 位代码，走真实净值

    base = [{"key": "hs300", "weight": 40}, {"key": "credit", "weight": 40},
            {"key": "gold", "weight": 20}]
    by_code = [dict(f) for f in base]
    for f in by_code:
        if f["key"] == "credit":
            f["key"] = code
    tm = {"hs300": 30}
    bks = {"增长↑": ["hs300"], "收益垫": ["credit"], "通胀↑": ["gold"]}
    kw = dict(start="2024-01-01", method="risk_parity", trend_map=tm, rp_buckets=bks)
    a = custom_compare(name="别名对照", funds=base, **kw)
    b = custom_compare(name="别名对照", funds=by_code, **kw)
    assert b["rows"] == a["rows"], "代码写法与内部 key 写法必须逐位一致"
    assert b["curves"]["别名对照"] == a["curves"]["别名对照"]
    assert b["bucket_info"]["buckets"]["收益垫"] == ["credit"]

    # 分桶表里也写代码时，归一化后仍然是 3 桶，不退化
    c = custom_compare(name="别名对照", funds=by_code, start="2024-01-01",
                       method="risk_parity", trend_map=tm,
                       rp_buckets={"增长↑": ["hs300"], "收益垫": [code], "通胀↑": ["gold"]})
    assert c["bucket_info"]["mode"] == "buckets"
    assert c["bucket_info"]["buckets"]["收益垫"] == ["credit"]
    assert c["rows"] == a["rows"]
