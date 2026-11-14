"""回测起点只决定「从哪天开始算收益」，不能决定「从哪天开始攒均线」（2026-11-14 用户：
「2019 起最大回撤 3.6%，2020 起是 9%」——原来从起点开始跑，均线没预热，撞上 2020-03 疫情满仓扛跌）。
"""
import asyncio
import json

import pandas as pd
import pytest

from allweather.custom_backtest import custom_compare
from allweather.data import load_panel, panel_returns
from allweather.pipeline import run_strategy_backtest
from allweather.stats import perf_metrics

RP = "V3-B 风险平价"


@pytest.fixture(scope="module")
def full_cut():
    nv = run_strategy_backtest(panel_returns(load_panel()), RP, "monthly").nv

    def cut(s):
        x = nv.loc[s:]
        x = x / x.iloc[0]
        return perf_metrics(x, rets=x.pct_change().dropna())
    return cut


class _Req:
    def __init__(self, q):
        self.query_params = q


def _backtest_rows(start):
    from api import server as S
    r = asyncio.run(S.backtest(_Req({"start": start, "cadence": "monthly"})))
    return {x["name"]: x for x in json.loads(r.body)["rows"]}


@pytest.mark.parametrize("start", ["2019-01-01", "2020-01-01", "2021-01-01"])
def test_backtest_endpoint_equals_full_history_cut(full_cut, start):
    row = _backtest_rows(start)[RP]
    m = full_cut(start)
    assert abs(row["mdd"] - m["mdd"] * 100) < 0.006 and abs(row["cagr"] - m["cagr"] * 100) < 0.006   # 接口保留 2 位小数


def test_2020_start_no_longer_shows_covid_crash():
    # 2020 起与 2019 起覆盖同一个 2020-03：预热好之后最大回撤必须相同，不能再是 -9%
    a, b = _backtest_rows("2019-01-01")[RP], _backtest_rows("2020-01-01")[RP]
    assert abs(a["mdd"] - b["mdd"]) < 1e-6 and b["mdd"] > -5


def test_custom_compare_builtins_warmed(full_cut):
    d = custom_compare(start="2020-01-01", name="t", method="fixed",
                       funds=[{"key": "hs300", "weight": 50}, {"key": "credit", "weight": 50}])
    row = next(r for r in d["rows"] if r["name"] == RP)
    assert abs(row["mdd"] - full_cut("2020-01-01")["mdd"] * 100) < 1e-3


def test_late_fund_pushes_start_past_warmup():
    # 008702 华夏黄金联接 2020-04 才有数据，要 75 日均线：必须等预热完才开始算，并说明原因
    funds = [{"key": "credit", "weight": 50}, {"key": "008702", "code": "008702", "weight": 50}]
    d = custom_compare(start="2020-01-01", name="t", method="inverse_vol", funds=funds,
                       trend_map={"008702": 75})
    assert d["start_reason"] == "warmup" and d["warmup_days"] == 76
    days = len(pd.bdate_range(d["data_start"], d["start_actual"]))
    assert days >= 76, (d["data_start"], d["start_actual"])
    # 固定权重不需要预热：从基金有数据那天就开始
    f = custom_compare(start="2020-01-01", name="t", method="fixed", funds=funds)
    assert f["start_reason"] == "fund" and f["start_actual"] == f["data_start"]


def test_user_start_after_warmup_is_kept():
    funds = [{"key": "credit", "weight": 50}, {"key": "008702", "code": "008702", "weight": 50}]
    d = custom_compare(start="2022-01-01", name="t", method="inverse_vol", funds=funds, trend_map={"008702": 75})
    assert d["start_reason"] == "" and d["start_actual"].startswith("2022-01")
