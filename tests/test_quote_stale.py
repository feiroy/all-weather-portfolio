"""`quote.spots_now` 的取数口径。

这个函数是「估值用现价」的唯一入口，两个性质不能被改坏：

1. **过期也返回**。只认 SPOT_TTL 内的价，30 秒后 `Portfolio.spot` 会突然变空，
   折溢价徽标消失、重建出来的 plan 又退回净值 —— 同一页面两次刷新两个数。
2. **同一批不重复打**。后台线程在飞的时候，每次请求都再踢一次会把东财打成筛子。
"""
from __future__ import annotations

import allweather.quote as Q


def _stub(monkeypatch, codes_prices):
    calls = []

    def fake(codes):
        calls.append(list(codes))
        return {c: {"price": codes_prices[c], "chg": 0.0} for c in codes}

    monkeypatch.setattr(Q, "_spots", fake)
    return calls


def _reset():
    Q._spot.clear()
    Q._fetching.clear()


def test_stale_price_is_still_returned(monkeypatch):
    import time

    _reset()
    Q._spot["511130"] = (time.time() - Q.SPOT_TTL - 5, {"price": 109.3, "chg": -0.003})
    monkeypatch.setattr(Q, "_kick", lambda codes: None)      # 别真起线程

    got = Q.spots_now(["511130"])
    assert got["511130"]["price"] == 109.3, "过期的价也要给，否则估值口径会翻回净值"


def test_really_old_price_is_dropped(monkeypatch):
    import time

    _reset()
    Q._spot["511130"] = (time.time() - Q.STALE_MAX - 1, {"price": 109.3, "chg": -0.003})
    monkeypatch.setattr(Q, "_kick", lambda codes: None)

    assert Q.spots_now(["511130"]) == {}, "跨交易日挂着的陈价不能当现价用"


def test_fresh_price_does_not_refetch(monkeypatch):
    import time

    _reset()
    Q._spot["511130"] = (time.time(), {"price": 109.3, "chg": -0.003})
    calls = _stub(monkeypatch, {"511130": 109.4})

    Q.spots_now(["511130"])
    assert calls == [], "TTL 内不该再打接口"


def test_failure_keeps_last_good_price(monkeypatch):
    """刷新失败要留上一次的价，并且时间戳往前走（否则每个请求都会再踢一次线程）。"""
    import time

    _reset()
    old = {"price": 109.3, "chg": -0.003}
    Q._spot["511130"] = (0.0, old)
    monkeypatch.setattr(Q, "_spots", lambda codes: (_ for _ in ()).throw(RuntimeError("断网")))

    Q._kick(["511130"])
    for _ in range(200):                     # 等后台线程收尾（_spots 立刻抛错，几毫秒）
        if not Q._fetching:
            break
        time.sleep(0.01)

    stamp, val = Q._spot["511130"]
    assert val is old, "取不到新价就别把老价丢了"
    assert stamp > 0, "失败也要盖时间戳，否则下一个请求立刻重试"


def test_kick_dedupes_in_flight(monkeypatch):
    """线程还没回来时再踢同一批，不能再起第二个线程（页面切来切去很频繁）。"""
    import threading

    _reset()
    started, gate = [], threading.Event()

    def slow(codes):
        started.append(list(codes))
        gate.wait(2)                         # 卡住第一次请求，模拟「还在飞」
        return {c: {"price": 1.0, "chg": 0.0} for c in codes}

    monkeypatch.setattr(Q, "_spots", slow)
    Q._kick(["511130"])
    Q._kick(["511130"])
    gate.set()
    for _ in range(200):
        if not Q._fetching:
            break
        threading.Event().wait(0.01)
    assert len(started) == 1
