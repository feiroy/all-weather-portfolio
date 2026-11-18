"""每日明细的「待更新」判定（2026-11-18 用户：「净值都收到了，但是收益算不出来？」）。

原来 `state` 只看**收盘价序列**（`price_dates`）。收盘价要等行情落盘，比实时行情晚一步，
于是出现：11/18 的净值 1.7405 已经显示在表里、市价 1.712 也有，收益却整行写「待更新」——
用户当然看不懂。收益其实早就算好了，只是被这个状态挡住了。

现在的口径：**这一天的估值价只要有来源，就不算待更新**
  1. 当天有交易（成交价就是价格）
  2. 净值已公布（`raw_dates`，不是面板 ffill 出来的）
  3. 收盘价已落盘（`price_dates`）
  4. 场内 ETF 今天拿到了实时价（收盘后它就是收盘价）

场外没有实时价，净值没到就老老实实「待更新」。
"""
from __future__ import annotations

import time

import pytest

from allweather import accounts as AC

AID = "sim-c01062"


def _portfolio():
    import api.server as S

    if not AC.load(AID):
        pytest.skip(f"没有 {AID} 账户")
    return S._portfolio(AID)[0]


def _pin_spot(P, spot: dict) -> None:
    """塞一份行情进去，并把 2 秒节流顶住，防止马上被真行情覆盖。"""
    P._spot = spot
    P._spot_at = time.time()


def test_state_and_price_agree_on_last_day():
    """最后一天：有价就必须有数字；两样来源都没有才待更新。"""
    P = _portfolio()
    for code, (_, _, state, act) in P.by_day[P.last].items():
        has_px = bool(act) or P.last in P.price_dates(code) or P.last in P.raw_dates(code) \
            or P.live_px_day(code, P.last)
        assert (state == "") == bool(has_px), f"{code}: state={state!r} 但有价={has_px}"


def test_nav_arrived_is_enough_for_otc():
    """场外：净值已公布 → 能算；停在上一净值日（面板 ffill）→ 待更新。"""
    P = _portfolio()
    otc = [c for c in P.by_day[P.last] if P._is_otc(c)]
    if not otc:
        pytest.skip("这个账户没有场外持仓")
    for code in otc:
        state = P.by_day[P.last][code][2]
        published = P.last in P.raw_dates(code)
        assert (state == "") == published, f"{code}: 净值公布={published} 但 state={state!r}"


def test_intraday_quote_counts_as_today_price():
    """场内：实时价的日期就是当天 → 视为有价；隔夜缓存 → 不算。"""
    P = _portfolio()
    etf = next((c for c in P.by_day[P.last] if not P._is_otc(c)), None)
    if etf is None:
        pytest.skip("这个账户没有场内持仓")
    today = P.last.timestamp() + 15 * 3600          # 当天 15:00 收盘
    _pin_spot(P, {etf: {"price": 1.0, "chg": 0.0, "at": today}})
    assert P.live_px_day(etf, P.last) is True
    _pin_spot(P, {etf: {"price": 1.0, "chg": 0.0, "at": today - 86400}})
    assert P.live_px_day(etf, P.last) is False, "昨天的价不能当今天的"


def test_otc_never_uses_live_quote():
    """场外没有实时价：净值没到就是待更新，不能拿行情顶。"""
    P = _portfolio()
    otc = next((c for c in P.by_day[P.last] if P._is_otc(c)), None)
    if otc is None:
        pytest.skip("这个账户没有场外持仓")
    _pin_spot(P, {otc: {"price": 1.0, "chg": 0.0, "at": P.last.timestamp() + 15 * 3600}})
    assert P.live_px_day(otc, P.last) is False


# ---------------------------------------------------------------- 头卡别把「还没出」当 0
def test_holding_day_state_matches_by_day():
    """基金详情头卡的今日收益：待更新时 state 必须带出来，前端才敢写「待更新」。"""
    P = _portfolio()
    for it in P.items():
        h = P.holding(it)
        if not h["held"]:
            continue
        row = P.by_day.get(P.last, {}).get(h["code"])
        expect = row[2] if row else ""
        assert h["day_state"] == expect, f"{h['code']}: {h['day_state']!r} != {expect!r}"
        # 待更新那格给的是 0（不是涨跌为零），必须靠 state 遮住
        if expect:
            assert h["day"] == 0.0


def test_summary_today_state_counts_pending():
    """账户合计三态：全没出 → 待更新；出一部分 → 部分；都出了 → 空。"""
    P = _portfolio()
    s = P.summary()
    pend = [c for c, v in (P.by_day.get(P.last) or {}).items()
            if v[2] and float(P.pos.get(c, 0) or 0) > 0]
    held_n = sum(1 for c in P.pos if float(P.pos.get(c, 0) or 0) > 0)
    assert s["today_pending"] == len(pend)
    want = "" if not pend else ("待更新" if len(pend) >= held_n else "部分")
    assert s["today_state"] == want
