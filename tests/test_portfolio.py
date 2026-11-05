"""allweather/portfolio.py：H5 和 Streamlit 共用的计算层。用主账户跑一遍，核对账目自洽（不依赖具体某天的数字）。"""
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


def test_period_detail_matches_day(P):
    """收益日历：某天各只基金的收益加起来 = 那天格子里的金额（同一次重放、同一口径）。"""
    d = P.period()
    for i, day in enumerate(d["dates"]):
        if i == 0 or d["day"][i] is None or day not in d["detail"]:
            continue
        assert abs(sum(r[1] for r in d["detail"][day]) - d["day"][i]) < 0.05, day


def test_plan_with_other_weights(P):
    """换策略预览：传同一套位置权重 = 原计划；传全 0 = 只卖不买。"""
    same = P._plan(P.slot_w)
    assert abs(same["buy"] - P.plan["buy"]) < 1e-6 and abs(same["sell"] - P.plan["sell"]) < 1e-6
    zero = P._plan({s: 0.0 for s in P.slot_w})
    assert zero["buy"] == 0 and all(o["side"] == "卖出" for o in zero["orders"])
    assert P.plan is not same           # 预览不改动账户自己的那份计划


def test_streamlit_fields(P):
    """Streamlit 版读的字段：时间加权净值、has_acct、by_code、stuck 的 slots。"""
    assert "nav_twr" in P.daily.columns and P.plan["has_acct"] is True
    assert set(P.plan["by_code"]) == {o["code"] for o in P.plan["orders"]}
    st = P.status()
    if st["kind"] == "stuck":
        assert st["slots"]
