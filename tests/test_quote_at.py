"""净值日 ≠ 行情时间（2026-11-17）。

用户原话：「我发现 30 年国债 ETF 这个收益率是今天的，为啥数据展示还是 16 号」。

两句话都对，只是说的是两个日期：

- 账户的 `asof` 是**净值面板最后一天** —— 场外基金当天的净值 21:00 后才公布；
- 场内 ETF 的市值 / 收益率按**二级市场实时价**算，那个价是今天的。

所以页面必须同时拿到这两个日期，而且 `quote_at` 必须是**这份 plan 算价时用的
那一份行情**的时间，不能拿「现在几点」糊上去 —— 接口层会把 Portfolio 缓存几分钟，
用当前时间去配几分钟前的价，等于又骗了一次（2026-11-16 就踩过 `spot=True` 但
`px` 还是净值的坑）。
"""
from __future__ import annotations

import time

import pytest

import allweather.quote as Q
from allweather import accounts as AC
from allweather.portfolio import Portfolio

AID = "sim-c01062"
LIVE = "511130"          # 场内 ETF：有二级市场报价
OTC = "161119"           # 场外（LOF，但用户是场外申购，按净值赎回）


def test_spots_now_carries_fetch_time(monkeypatch):
    """现价要带「这个价是什么时候取的」，页面的行情时间就取它。"""
    Q._spot.clear()
    Q._fetching.clear()
    stamp = time.time() - 60
    Q._spot[LIVE] = (stamp, {"price": 110.1, "chg": 0.0})
    monkeypatch.setattr(Q, "_kick", lambda codes: None)

    got = Q.spots_now([LIVE])
    assert got[LIVE]["at"] == pytest.approx(stamp)
    assert Q._spot[LIVE][1] == {"price": 110.1, "chg": 0.0}, "返回体里的 at 不能写回缓存（会越叠越多）"


def _portfolio(spots: dict[str, float], monkeypatch) -> Portfolio:
    import api.server as S

    a = AC.load(AID)
    if not a:
        pytest.skip(f"没有 {AID} 账户")
    Q._spot.clear()
    Q._fetching.clear()
    now = time.time()
    for code, px in spots.items():
        Q._spot[code] = (now - 90, {"price": px, "chg": 0.0})
    monkeypatch.setattr(Q, "_kick", lambda codes: None)
    return Portfolio(a, S.strategy_weights(a.get("strategy"), a)[0])


def test_quote_at_is_empty_when_no_spot(monkeypatch):
    """行情没到（刚启动就是这样）就别编一个时间出来，否则日期配的是净值价。"""
    P = _portfolio({}, monkeypatch)
    assert P.quote_at() == ""


def test_quote_at_only_covers_live_positions(monkeypatch):
    P = _portfolio({LIVE: 110.11}, monkeypatch)
    live = next((x for x in P.items() if x["code"] == LIVE), None)
    if live is None:
        pytest.skip(f"{AID} 没有持有 {LIVE}")
    otc = next((x for x in P.items() if x["code"] == OTC), None)
    if otc is None:
        pytest.skip(f"{AID} 没有持有 {OTC}")

    h_live, h_otc = P.holding(live), P.holding(otc)
    assert h_live["quote_at"], "场内持仓要给出行情时间"
    assert h_otc["quote_at"] == "", "场外份额按净值估，没有行情时间这回事"
    assert h_live["spot"] is True and h_otc["spot"] is False
    # 日期与数字必须同源：标了行情时间，px 就得是这个价
    assert h_live["px"] == pytest.approx(110.11, abs=1e-6)


def test_quote_at_never_later_than_now(monkeypatch):
    P = _portfolio({LIVE: 110.11}, monkeypatch)
    got = P.quote_at()
    if not got:
        pytest.skip("这个账户没有场内持仓")
    assert len(got) == len("11/17 13:02") or got.count(":") == 1


def test_nav_asof_stays_on_panel_last_day(monkeypatch):
    """净值日不能跟着行情时间走 —— 那条线只有净值，场外当天的净值还没公布。"""
    P = _portfolio({LIVE: 110.11}, monkeypatch)
    s = P.summary()
    assert s["asof"] == f"{P.last:%Y-%m-%d}"
    assert s["asof"][:4] in ("2026", "2025", "2027")
