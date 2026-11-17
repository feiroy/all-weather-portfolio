"""折溢价必须是「同一天两个价」的关系（2026-11-17）。

用户截图里 511130 挂着「溢价 +0.50%」，而它 11/16 收盘价 109.30 对 11/16 净值
109.6706 其实是**折价 0.34%** —— 差 0.84pp 全是当天的涨幅。

原因：`quote.snapshot` 的 premium = 实时价 ÷ 最新净值，而最新净值是上一交易日的
（今天 21:00 后才出）。于是「今天的涨跌」被算进了「折溢价」，同一个页面里
「市价涨了」和「溢价了」两句话互相打架。

没有实时 IOPV 的情况下，能算准的只有同日口径：最近一个有收盘价的交易日，
收盘价 ÷ 同日净值 − 1。`api.server._same_day_premium()` 负责这个覆盖。
"""
from __future__ import annotations

import pytest

from allweather import holdings as HG


def test_same_day_premium_is_self_consistent():
    from api.server import _same_day_premium

    got = _same_day_premium("511130")
    if not got:
        pytest.skip("本地没有 511130 的收盘价 / 净值存档")
    assert got["premium"] == pytest.approx(got["premium_price"] / got["premium_base"] - 1, abs=1e-5)
    # 日期必须是真有收盘价的那天，不能是「今天」
    assert got["premium_date"] in {f"{d:%Y-%m-%d}" for d in HG.price_series("511130").index}


def test_same_day_premium_ignores_today_move():
    """实时价配上一净值日净值会把今天的涨跌算成溢价 —— 同日口径必须和它不同。"""
    from api.server import _same_day_premium
    from allweather import quote as Q

    got = _same_day_premium("511130")
    snap = Q.snapshot(["511130"]).get("511130") or {}
    if not got or not snap.get("ok") or snap.get("premium") is None:
        pytest.skip("行情或净值存档缺失")
    if snap.get("price") == got["premium_price"]:
        pytest.skip("此刻实时价正好等于上一收盘价，两者本来就该相等")
    assert got["premium"] != pytest.approx(snap["premium"], abs=1e-6)


def test_same_day_premium_missing_data_returns_empty():
    from api.server import _same_day_premium

    assert _same_day_premium("999999") == {}
