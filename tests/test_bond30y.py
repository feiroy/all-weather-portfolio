"""30Y 国债收益率重建（data.bond_total_return_from_yield / synthesize_bond_30y）的回归测试。"""
import numpy as np
import pandas as pd

from allweather.data import bond_total_return_from_yield, load_panel, load_series, synthesize_bond_30y


def _days(n, start="2020-01-02"):
    return pd.bdate_range(start, periods=n)


def test_flat_yield_earns_only_carry():
    # 收益率不变 → 总回报只有票息：一年约等于收益率本身（不能被放大）
    y = pd.Series(0.03, index=_days(260))
    tr = bond_total_return_from_yield(y, 30.0)
    yrs = (y.index[-1] - y.index[0]).days / 365.0
    assert abs((tr.iloc[-1] - 1) - 0.03 * yrs) < 2e-3


def test_yield_up_1bp_loses_about_duration_bp():
    # 30 年票面债修正久期约 19.6（y=3%），收益率 +1bp 当天价格约 -0.196%
    y = pd.Series([0.03, 0.0301], index=_days(2))
    r = bond_total_return_from_yield(y, 30.0).pct_change().iloc[-1]
    assert -0.0021 < r < -0.0018


def test_synth_30y_matches_etf_after_listing_and_has_no_extra_days():
    etf = load_series("bond_30y_etf")
    b10 = load_series("bond_10y_etf")
    s = synthesize_bond_30y(b10, etf)
    k = etf.index.min()
    # 上市后逐日收益与 ETF 一致
    a = s.loc[k:].pct_change().dropna()
    e = etf.pct_change().dropna().reindex(a.index)
    assert np.allclose(a.values, e.values, atol=1e-10)
    # 不引入交易所日历以外的日期（银行间调休周六）
    assert s.index.difference(b10.index.union(etf.index)).empty


def test_panel_bond30y_pre_listing_not_amplified():
    # 旧「10Y×3」做法 2015-01~2020-02 年化 11.36%；真实 30Y 收益率在这段重建上限约 6.45%
    p = load_panel()["bond_30y"].loc["2015-01-01":"2020-02-03"]
    yrs = (p.index[-1] - p.index[0]).days / 365.25
    cagr = (p.iloc[-1] / p.iloc[0]) ** (1 / yrs) - 1
    assert cagr < 0.07


def test_late_start_asset_does_not_truncate_other_strategies():
    # 2026-10-30 c7e0bc6 回归：短融（2015 起）只给风险平价用，不能把保守增强 / V3c 也截到 2015
    from allweather.data import panel_returns
    from allweather.pipeline import strategy_window
    r = panel_returns(load_panel())
    assert r["bond_short"].first_valid_index() >= pd.Timestamp("2015-01-01")
    # 三个策略都不用短融（风险平价 2026-11-08 撤掉），全部从面板共同起点（2006）开始
    for s in ("V3-B 保守增强", "V3-B 风险平价", "V3c 多元"):
        w = strategy_window(r, s)
        assert w.index[0] < pd.Timestamp("2007-01-01"), s
        assert "bond_short" not in w.columns and not w.isna().any().any()


def test_gold_has_no_splice_jump():
    # 上游 bug：持仓推算段拼接点取错，2006-07-14 单日 +85%
    from allweather.data import _load_gold_cny
    r = _load_gold_cny().pct_change().dropna()
    assert r.max() < 0.15
