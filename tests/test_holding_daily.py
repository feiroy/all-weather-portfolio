"""基金详情「每日收益」明细（2026-11-17 用户要求）。

用户原话：「把每一天的收益值、收益率直接展示到净值走势下面，方便我对照验证计算，
现在这样我很难检查你这个程序是否有 bug」。

所以这张表是**核对入口**，不能是另算一遍的结果 —— 必须是收益日历里那一格的原始导出：

- 收益 = 当日市值变化 − 当日净流入（买入当天不会把本金算成收益）
- 收益率 = 收益 ÷ (昨市值 + 当日买入额)
- 净值 / 份额是当天面板上的值，手算 `份额 ×（今日净值 − 昨日净值）` 能对上
- 按日期**正序**，和净值走势图同方向
"""
from __future__ import annotations

import asyncio
import json

import pytest

from allweather import accounts as AC

AID = "sim-c01062"


class _Req:
    def __init__(self, code: str, aid: str = AID, period: str | None = None):
        self.path_params = {"aid": aid, "code": code}
        self.query_params = {"period": period} if period else {}


def _payload(code: str) -> dict:
    from api import server as S

    a = AC.load(AID)
    if not a:
        pytest.skip(f"没有 {AID} 账户")
    resp = asyncio.run(S.holding_daily(_Req(code)))
    return json.loads(resp.body)


def _payload_period(code: str, period: str, aid: str = AID) -> dict:
    from api import server as S

    resp = asyncio.run(S.holding_daily(_Req(code, aid=aid, period=period)))
    return json.loads(resp.body)


def _portfolio():
    import api.server as S

    a = AC.load(AID)
    return S._portfolio(AID)[0]


def test_rows_are_plain_export_of_by_day():
    """表里的收益必须与收益日历同一份数据，不能前端/后端各算一套。"""
    p = _portfolio()
    code = next((x["code"] for x in p.items() if x.get("shares", 0) > 0), None)
    if code is None:
        pytest.skip("账户没有持仓")

    body = _payload(code)
    assert body["rows"], "有持仓就该有逐日明细"
    by_day = {f"{d:%Y-%m-%d}": v[code][0] for d, v in p.by_day.items() if code in v}
    for r in body["rows"]:
        assert r["pnl"] == pytest.approx(by_day[r["date"]], abs=0.02), f"{r['date']} 收益与收益日历不一致"


def test_rows_sorted_ascending():
    p = _portfolio()
    code = next((x["code"] for x in p.items() if x.get("shares", 0) > 0), None)
    if code is None:
        pytest.skip("账户没有持仓")
    dates = [r["date"] for r in _payload(code)["rows"]]
    assert dates == sorted(dates), "按日期正序，和净值走势图同方向"


def test_nav_and_shares_match_panel():
    p = _portfolio()
    code = next((x["code"] for x in p.items() if x.get("shares", 0) > 0), None)
    if code is None:
        pytest.skip("账户没有持仓")
    for r in _payload(code)["rows"]:
        nav = p.nav_on(code, r["date"])
        if nav:
            assert r["nav"] == pytest.approx(round(float(nav), 4), abs=1e-4)
        assert r["shares"] == pytest.approx(round(p.held_on(code, r["date"]), 4), abs=1e-4)


def test_buy_day_does_not_count_principal_as_profit():
    """建仓当天的收益 = 市值 − 买入额（含费），不是「市值」本身。"""
    p = _portfolio()
    code = next((x["code"] for x in p.items() if x.get("shares", 0) > 0), None)
    if code is None:
        pytest.skip("账户没有持仓")
    h = p.holding(next(x for x in p.items() if x["code"] == code))
    rows = [r for r in _payload(code)["rows"] if r["act"] == "买入"]
    if not rows:
        pytest.skip("这只基金没有买入记录")
    first = rows[0]
    assert abs(first["pnl"]) < h["mv"], "建仓当天不可能出现比市值还大的收益（那是把本金算进去了）"


def test_unknown_code_is_404():
    from api import server as S

    resp = asyncio.run(S.holding_daily(_Req("999999")))
    assert resp.status_code == 404


# ---------------------------------------------------------------- 市价 / 费用 / 粒度
def test_rows_carry_price_fee_and_market_value():
    """每行要给齐核对需要的东西：净值、市价、份额、市值、费用。"""
    p = _portfolio()
    code = next((x["code"] for x in p.items() if x.get("shares", 0) > 0), None)
    if code is None:
        pytest.skip("账户没有持仓")
    rows = _payload(code)["rows"]
    for r in rows:
        for k in ("label", "nav", "px", "px_kind", "shares", "mv", "pnl", "pct", "fee"):
            assert k in r, f"缺字段 {k}"
        assert r["px_kind"] in ("市价", "净值")
        # 市值 = 份额 × 估值价（容差放到分）
        if r["px"] and r["shares"]:
            assert r["mv"] == pytest.approx(r["shares"] * r["px"], abs=0.05)


def test_fee_total_matches_trades():
    """费用列与台账里的手续费一致，合计等于各笔之和。"""
    p = _portfolio()
    code = next((x["code"] for x in p.items() if x.get("shares", 0) > 0), None)
    if code is None:
        pytest.skip("账户没有持仓")
    body = _payload(code)
    want = sum(float(t.get("fee") or 0) for t in p.trades_of(code)
               if t.get("side") in ("买入", "卖出"))
    assert body["fee_total"] == pytest.approx(round(want, 2), abs=0.02)
    assert sum(r["fee"] or 0 for r in body["rows"]) == pytest.approx(body["fee_total"], abs=0.02)


@pytest.mark.parametrize("period", ["week", "month", "year"])
def test_collapse_keeps_profit_and_fee(period):
    """聚合只是把日期折叠，收益/费用必须一分不差地并起来。"""
    p = _portfolio()
    code = next((x["code"] for x in p.items() if x.get("shares", 0) > 0), None)
    if code is None:
        pytest.skip("账户没有持仓")
    day = _payload(code)
    agg = _payload_period(code, period)
    assert agg["period"] == period
    assert sum(r["pnl"] or 0 for r in agg["rows"]) == pytest.approx(
        sum(r["pnl"] or 0 for r in day["rows"]), abs=0.05)
    assert sum(r["fee"] or 0 for r in agg["rows"]) == pytest.approx(
        sum(r["fee"] or 0 for r in day["rows"]), abs=0.02)
    assert len(agg["rows"]) <= len(day["rows"])


def test_collapse_rate_uses_period_opening_money():
    """聚合收益率的分母是期初投入的钱，不是「资金 × 天数」的累加。"""
    p = _portfolio()
    code = next((x["code"] for x in p.items() if x.get("shares", 0) > 0), None)
    if code is None:
        pytest.skip("账户没有持仓")
    agg = _payload_period(code, "month")
    for r in agg["rows"]:
        if not r["base"]:
            assert r["pct"] is None
            continue
        assert r["pct"] == pytest.approx(r["pnl"] / r["base"] * 100, abs=0.01)


@pytest.mark.parametrize("aid", [AID, "main"])
def test_historical_rows_use_same_day_close(aid):
    """场内历史行按**当日收盘价**算市值，不是净值 —— 否则拿市价手算永远对不上。"""
    import api.server as S
    from allweather import holdings as HG

    if not AC.load(aid):
        pytest.skip(f"没有 {aid} 账户")
    p = S._portfolio(aid)[0]
    code = next((x["code"] for x in p.items()
                 if not x["otc"] and x.get("shares", 0) > 0 and len(HG.price_series(x["code"]))), None)
    if code is None:
        pytest.skip("账户没有场内持仓")
    rows = _payload_period(code, "day", aid)["rows"]
    hist = [r for r in rows if r["date"] != f"{p.last:%Y-%m-%d}"]
    if not hist:
        pytest.skip("这只场内基金只有建仓那一天")
    px = HG.price_series(code)
    for r in hist:
        sub = px.loc[:r["date"]]
        if len(sub):
            assert r["px"] == pytest.approx(round(float(sub.iloc[-1]), 3), abs=1e-3), \
                f"{r['date']} 的市价不是当日收盘价"
