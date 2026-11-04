"""实盘目标权重 = 回测引擎「假如这一天调仓」；rebal_dates 指定调仓日。"""
import pandas as pd
import pytest

from allweather.pipeline import run_strategy_backtest, live_target_weights


@pytest.fixture(scope="module")
def panel(synthetic_prices):
    p = synthetic_prices.copy()
    p["bond_short"] = p["credit"] * 0.999        # 风险平价资产池里有短融
    return p


def test_rebal_dates_only_rebalances_on_given_days(panel):
    rets = panel.pct_change().dropna()
    days = [rets.index[150], rets.index[300], rets.index[420]]
    r = run_strategy_backtest(rets, "V3-B 保守增强", track_weights=True, rebal_dates=days)
    assert list(r.weight_df.index) == days
    assert r.n_rebal == 3


def test_rebal_dates_roll_forward_to_next_trading_day(panel):
    rets = panel.pct_change().dropna()
    sat = rets.index[200] + pd.Timedelta(days=1)            # 合成数据是工作日，挑一个不在索引里的日子
    while sat in rets.index:
        sat += pd.Timedelta(days=1)
    r = run_strategy_backtest(rets, "V3c 多元", track_weights=True, rebal_dates=[sat])
    assert r.weight_df.index[0] == rets.index[rets.index.searchsorted(sat)]


@pytest.mark.parametrize("key,name", [("B-Con", "V3-B 保守增强"), ("B-RP", "V3-B 风险平价"), ("V3c", "V3c 多元")])
def test_live_weights_equal_backtest_rebalance_row(panel, key, name):
    """实盘目标必须和回测在同一天调仓时的那一行一模一样 —— 只有一份规则。"""
    w, w0 = live_target_weights(key, panel)
    rets = panel.pct_change().dropna()
    r = run_strategy_backtest(rets, name, track_weights=True, rebal_dates=[rets.index[-1]])
    row = r.weight_df.iloc[-1]
    pd.testing.assert_series_equal(w, row / row.sum(), check_names=False)
    assert abs(float(w.sum()) - 1) < 1e-9 and abs(float(w0.sum()) - 1) < 1e-9


def test_live_weights_apply_rp_hs300_trend_filter(panel):
    """沪深300 跌破 30 日线时，风险平价目标里沪深300 必须是 0（原来实盘漏了这条）。"""
    p = panel.copy()
    p.iloc[-5:, p.columns.get_loc("hs300")] *= 0.85     # 最后几天砸下去
    w, w0 = live_target_weights("B-RP", p)
    assert float(w0["hs300"]) > 0
    assert float(w["hs300"]) == 0.0
