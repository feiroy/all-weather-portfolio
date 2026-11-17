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
    def __init__(self, code: str, aid: str = AID):
        self.path_params = {"aid": aid, "code": code}
        self.query_params = {}


def _payload(code: str) -> dict:
    from api import server as S

    a = AC.load(AID)
    if not a:
        pytest.skip(f"没有 {AID} 账户")
    resp = asyncio.run(S.holding_daily(_Req(code)))
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
