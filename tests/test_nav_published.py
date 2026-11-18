"""画图只用真净值，不吃面板 ffill（2026-11-18 用户：「都没数据的情况下你不能瞎画，
把 17 号的结果当成 18 号的结果」）。

净值面板为了对齐交易日会一路 ffill：场外基金当天净值 21:00 后才出，图上就多出一段
水平线，tooltip 还把 11/17 的净值标成 11/18。`Portfolio.nav_published()` 把 ffill 出来的
点全部去掉 —— 估值仍用面板（份额要按最新净值计价），只有画图用它。
"""
from __future__ import annotations

import os
import time

import pytest

from allweather import accounts as AC

AID = "sim-c01062"


def _portfolio():
    import api.server as S

    if not AC.load(AID):
        pytest.skip(f"没有 {AID} 账户")
    return S._portfolio(AID)[0]


def test_nav_published_has_no_filled_points():
    """published 序列的每一天都必须是真实公布过净值的日子。"""
    P = _portfolio()
    codes = [c for c, sh in P.pos.items() if float(sh or 0) > 0]
    if not codes:
        pytest.skip("账户没有持仓")
    for code in codes:
        raw = P.raw_dates(code)
        if not len(raw):
            continue
        pub = P.nav_published(code)
        assert len(pub) <= len(P.nav(code)), f"{code}: 不能比面板还长"
        assert pub.index[-1] == raw[-1], f"{code}: 最后一个点必须是真净值日"
        assert set(pub.index) <= set(raw), f"{code}: 混进了 ffill 出来的日子"


def test_nav_published_keeps_real_days():
    """不是把序列清空：真实有净值的日子一个不少。"""
    P = _portfolio()
    code = next((c for c, sh in P.pos.items() if float(sh or 0) > 0 and len(P.raw_dates(c))), None)
    if code is None:
        pytest.skip("账户没有带净值的持仓")
    pub = P.nav_published(code)
    assert len(pub) >= len(P.raw_dates(code)) - 1     # 面板起点可能更晚
    assert float(pub.iloc[-1]) == pytest.approx(float(P.nav(code).loc[P.raw_dates(code)[-1]]))


def test_stale_grace_is_short_when_only_today_missing():
    """只落后一天（今天的净值还没出）时，宽限期是 10 分钟，不是 1 小时。

    原来 1 小时：21:06 拉空一次就卡到 22:06 才重试，用户会以为「一直不更新」。
    2026-11-18 实测：21:31 时 007467 的 11/18 净值在东方财富已经能拉到，
    只是本地缓存说「已是最新」。
    """
    from fund_lookup import NAV_DIR, is_stale, load_cached, expected_nav_date

    code = "007467"
    p = NAV_DIR / f"{code}.csv"
    if not p.exists():
        pytest.skip(f"本地没有 {code} 的净值缓存")
    d = load_cached(code)
    if d is None or not len(d) or d.index[-1] >= expected_nav_date():
        pytest.skip("这只基金今天已经更新，构造不出「只落后一天」")

    old = p.stat().st_mtime
    try:
        os.utime(p, (time.time() - 30 * 60, time.time() - 30 * 60))   # 30 分钟前抓的
        assert is_stale(code) is True, "落后一天 + 半小时前抓过 → 该重试了"
    finally:
        os.utime(p, (old, old))
