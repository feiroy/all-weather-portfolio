"""allweather/portfolio.py：H5 用的计算层。用主账户跑一遍，核对账目自洽（不依赖具体某天的数字）。"""
import pandas as pd
import pytest

from allweather import accounts as AC
from allweather.portfolio import Portfolio


@pytest.fixture(scope="module")
def P():
    a = AC.load("main")
    if not a:
        pytest.skip("没有主账户")
    from allweather.data import load_panel
    from allweather.pipeline import live_target_weights
    w, _ = live_target_weights(a.get("strategy") or "B-Con", load_panel(end=pd.Timestamp.today().strftime("%Y-%m-%d")))
    return Portfolio(a, w)


def test_books_balance(P):
    p = P.plan
    assert abs(p["total"] - (p["mv_all"] + p["cash"])) < 0.01
    assert abs(p["pnl"] - (p["total"] - P.invested_now())) < 0.01
    # 每日序列最后一天 = 头卡总金额（重放和调仓计划两条路算出来要一样）
    assert abs(float(P.daily["equity"].iloc[-1]) - p["total"]) < 1.0


def test_orders_sum(P):
    p = P.plan
    assert abs(sum(o["amount"] for o in p["orders"] if o["side"] == "买入") - p["buy"]) < 0.01
    assert abs(sum(o["amount"] for o in p["orders"] if o["side"] == "卖出") - p["sell"]) < 0.01
    assert P.status()["kind"] in ("orders", "stuck", "calm")


def test_holdings_not_double_counted(P):
    hs = [P.holding(it) for it in P.items() if not it.get("dup")]
    assert len({h["code"] for h in hs}) == len(hs)
    assert abs(sum(h["mv"] for h in hs) - P.plan["mv_all"]) < 0.01


def test_held_on_and_month_curve(P):
    for c, sh in P.pos.items():
        assert abs(P.held_on(c, "2099-12-31") - sh) < 1e-6
    m = P.month_curve()
    assert len(m["dates"]) == len(m["ret"]) == len(m["money"]) and m["ret"][0] == 0
