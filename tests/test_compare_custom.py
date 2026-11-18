"""「和基准比」三条线：跟随自定义策略的账户也要有基准（2026-11-18）。

内置三策略的净值在 output/nv_curves.csv、权重历史在 weight_history_*.csv；
自定义策略这两样都没有，`BENCH_COL` 也查不到它的名字 → 页面只剩「我的账户」一条线
（用户：「和基准比，这个页面咋都没展示了呢」）。

现在自定义策略走 `custom_backtest.strategy_curve()` 现算净值 + 权重，
权重交给 `benchmark.replay_weights()` 按账户真实成交日重放。
"""
from __future__ import annotations

import asyncio
import json

import pytest

from allweather import accounts as AC

AID = "sim-c01062"


def _compare(aid: str = AID) -> dict:
    from api import server as S

    if not AC.load(aid):
        pytest.skip(f"没有 {aid} 账户")

    class _Req:
        path_params = {"aid": aid}
        query_params = {}

    return json.loads(asyncio.run(S.compare(_Req())).body)


def test_custom_strategy_has_theory_curve():
    """跟随自定义策略时，「策略理论」这条必须有 —— 这是判断策略本身好不好的基准。"""
    a = AC.load(AID)
    if not str(a.get("strategy") or "").startswith("custom:"):
        pytest.skip("这个账户不是跟随自定义策略")
    d = _compare()
    assert "我的账户" in d["curves"]
    assert "策略理论" in d["curves"], "自定义策略没有理论曲线，页面就只剩一条线了"
    assert len(d["curves"]["策略理论"]["dates"]) > 1


def test_custom_strategy_has_default_fund_curve():
    """「默认基金 · 我的操作日」：建仓当天也算一次调仓日，只建过仓也要有。"""
    a = AC.load(AID)
    if not str(a.get("strategy") or "").startswith("custom:"):
        pytest.skip("这个账户不是跟随自定义策略")
    d = _compare()
    assert "默认基金 · 我的操作日" in d["curves"]
    assert len(d["curves"]["默认基金 · 我的操作日"]["dates"]) > 1


def test_all_curves_share_the_same_axis():
    """三条线必须同起点同日期，否则图上一比就错位。"""
    d = _compare()
    dates = {k: tuple(v["dates"]) for k, v in d["curves"].items()}
    uniq = set(dates.values())
    assert len(uniq) == 1, f"日期轴不一致：{ {k: len(v) for k, v in dates.items()} }"


def test_gap_only_against_curves_that_exist():
    """差值只在两条线都在时给，缺一条就别硬算。"""
    d = _compare()
    for k in d["gap"]:
        assert k in d["curves"] and "我的账户" in d["curves"]
