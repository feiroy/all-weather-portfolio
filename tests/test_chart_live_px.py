"""市价走势图不能少今天那一点（2026-11-18 用户：「图怎么没画出来」）。

头上「场内市价 110.65（11/18 21:05）」已经显示了，市价走势却停在 11/17 —— 折线到
11/17 就断了，右端空一格。原因和「待更新」同源：图的序列直接读 `data/price_*.csv`，
而这份 CSV 由行情任务批量写，比实时行情晚一步。

`Portfolio.price_series_live()` 把当天的实时价接在后面（CSV 已有就不重复加）。
"""
from __future__ import annotations

import asyncio
import time

import pandas as pd
import pytest

from allweather import accounts as AC
from allweather import holdings as HG

AID = "sim-c01062"
ETF = "511130"          # 30 年国债 ETF，场内
OTC = "007467"          # 场外，没有市价序列


def _portfolio():
    import api.server as S

    if not AC.load(AID):
        pytest.skip(f"没有 {AID} 账户")
    if not len(HG.price_series(ETF)):
        pytest.skip(f"{ETF} 没有收盘价序列")
    return S._portfolio(AID)[0]


def _pin_spot(P, spot: dict) -> None:
    """塞一份行情进去，并顶住 2 秒节流，防止马上被真行情覆盖。"""
    P._spot = spot
    P._spot_at = time.time()


def _quote_at(day: pd.Timestamp, price: float) -> dict:
    return {ETF: {"price": price, "chg": 0.0034, "at": day.timestamp() + 21 * 3600}}


def test_live_price_appended_when_csv_is_behind():
    """CSV 停在昨天、今天有实时价 → 序列补上今天这一点。"""
    P, base = _portfolio(), HG.price_series(ETF)
    day = base.index[-1] + pd.Timedelta(days=1)
    _pin_spot(P, _quote_at(day, 110.65))
    s = P.price_series_live(ETF)
    assert s.index[-1] == day, f"最后一个点应该是 {day:%Y/%m/%d}"
    assert float(s.iloc[-1]) == pytest.approx(110.65)
    assert len(s) == len(base) + 1


def test_no_duplicate_when_csv_already_has_today():
    """CSV 已经有今天了 → 不能再加一个同一天的点。"""
    P, base = _portfolio(), HG.price_series(ETF)
    last = base.index[-1]
    _pin_spot(P, _quote_at(last, 110.65))
    s = P.price_series_live(ETF)
    assert len(s) == len(base)
    assert s.index[-1] == last


def test_stale_quote_is_ignored():
    """行情是昨天的 → 不是今天的价，不接。"""
    P, base = _portfolio(), HG.price_series(ETF)
    _pin_spot(P, {ETF: {"price": 110.65, "chg": 0.0,
                        "at": base.index[-1].timestamp() - 86400}})
    assert len(P.price_series_live(ETF)) == len(base)


def test_otc_has_no_price_series():
    """场外没有二级市场价，别给它编一条。"""
    P = _portfolio()
    base = HG.price_series(OTC)
    _pin_spot(P, {OTC: {"price": 1.0, "chg": 0.0, "at": P.last.timestamp() + 21 * 3600}})
    assert len(P.price_series_live(OTC)) == len(base)


def test_chart_html_contains_today():
    """接口出的 HTML 里必须有点：头上显示的价格和图上最后一个点得是同一根。"""
    from api import server as S

    P, base = _portfolio(), HG.price_series(ETF)
    day = base.index[-1] + pd.Timedelta(days=1)
    _pin_spot(P, _quote_at(day, 110.65))

    class _Req:
        path_params = {"aid": AID, "code": ETF}
        query_params = {"view": "price"}

    orig = S._portfolio
    S._portfolio = lambda aid: (P, AC.load(AID))
    try:
        resp = asyncio.run(S.holding_chart(_Req()))
    finally:
        S._portfolio = orig

    html = resp.body.decode()
    assert f"{day:%Y/%m/%d}" in html, "图里没有今天这一点"
    assert "110.65" in html
