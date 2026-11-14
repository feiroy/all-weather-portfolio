"""手续费口径回归（2026-11-14：用户要用场外基金实盘、拿网页对比收益时发现的两个 bug）。

1. is_exchange 只看首位数字，把 110020 / 161119 / 519xxx 这些场外基金当成场内，
   按「万 1.5 佣金、最低 5 元」收费，申购费和赎回阶梯全丢；
2. 赎回阶梯只取第一个数字，「大于等于7天，小于30天 0.10%」丢了上限，持有一年也按 0.10% 收；
   「大于等于1年」被当成 1 天。
"""
import pytest

from allweather import fees as F


def _html(rows):
    body = "".join(f"<tr><td>{c}</td><td>{r}</td></tr>" for c, r in rows)
    return f"<h4>赎回费率</h4><table>{body}</table>"


@pytest.mark.parametrize("cond,expect", [
    ("小于7天", (0, 7)),
    ("小于等于6天", (0, 7)),
    ("大于等于7天，小于30天", (7, 30)),
    ("大于等于7天，小于等于29天", (7, 30)),
    ("大于等于30天", (30, None)),
    ("大于等于1年，小于2年", (365, 730)),
    ("大于等于2年", (730, None)),
    ("大于6个月", (181, None)),
])
def test_parse_cond(cond, expect):
    assert F._parse_cond(cond) == expect


def test_parse_redeem_keeps_upper_bound():
    ladder = F._parse_redeem(_html([("小于7天", "1.50%"), ("大于等于7天，小于30天", "0.10%"),
                                    ("大于等于30天", "0.00%")]))
    assert ladder == [{"min_days": 0, "max_days": 7, "rate": 0.015},
                      {"min_days": 7, "max_days": 30, "rate": 0.001},
                      {"min_days": 30, "max_days": None, "rate": 0.0}]


def test_sell_fee_uses_band_by_holding_days(monkeypatch):
    ladder = F._parse_redeem(_html([("小于7天", "1.50%"), ("大于等于7天，小于365天", "0.50%"),
                                    ("大于等于1年，小于2年", "0.25%"), ("大于等于2年", "0.00%")]))
    monkeypatch.setattr(F, "get", lambda code: {"redeem": ladder, "buy_rate": 0.0012})
    monkeypatch.setattr(F, "is_exchange", lambda code: False)
    amt = 10000
    assert F.sell_fee("460300", amt, 3) == 150.0
    assert F.sell_fee("460300", amt, 100) == 50.0
    assert F.sell_fee("460300", amt, 400) == 25.0      # 1~2 年档
    assert F.sell_fee("460300", amt, 800) == 0.0       # 2 年以上免费；旧解析会一直按 0.50% 收
    assert F.buy_fee("460300", amt) == 12.0


def test_is_exchange_uses_purchase_table(monkeypatch):
    table = {"110020": ("开放申购", "开放赎回"), "161119": ("开放申购", "开放赎回"),
             "519671": ("开放申购", "开放赎回"), "511220": ("场内交易", "场内交易"),
             "513500": ("暂停申购", "场内交易")}     # QDII ETF 暂停申赎时，赎回状态仍是「场内交易」
    monkeypatch.setattr(F, "_purchase_status", lambda: table)
    for c in ("110020", "161119", "519671"):
        assert not F.is_exchange(c), c
    for c in ("511220", "513500"):
        assert F.is_exchange(c), c


def test_is_exchange_prefix_fallback(monkeypatch):
    monkeypatch.setattr(F, "_purchase_status", lambda: {})
    for c in ("510300", "511130", "512890", "159981", "563020", "588000"):
        assert F.is_exchange(c), c
    for c in ("110020", "161119", "519671", "006131", "020286", "000217", ""):
        assert not F.is_exchange(c), c


def test_otc_fund_charged_subscription_not_commission(monkeypatch):
    """场外基金买 1 万：按申购费（0.12% = 12 元），不再按佣金最低 5 元。"""
    monkeypatch.setattr(F, "_purchase_status", lambda: {"110020": ("开放申购", "开放赎回")})
    monkeypatch.setattr(F, "get", lambda code: {"redeem": [], "buy_rate": 0.0012})
    assert F.buy_fee("110020", 10000) == 12.0
    assert F.buy_fee("110020", 100) == 0.12


def test_purchase_refresh_only_when_stale(tmp_path, monkeypatch):
    """「更新数据」按钮：申购状态表新的就跳过，旧的 / 没有才重抓（用户只在网页操作，不跑命令）。"""
    import os
    import sys
    import time
    sys.path.insert(0, str(F.ROOT / "streamlit_app"))
    import fund_lookup as FL
    csv = tmp_path / "purchase_all.csv"
    monkeypatch.setattr(FL, "PURCHASE_CSV", csv)
    calls = []
    monkeypatch.setattr(F, "refresh_purchase", lambda: calls.append(1) or 28000)
    assert F.refresh_purchase_if_stale()[0] is True and len(calls) == 1          # 没有 → 抓
    csv.write_text("x")
    assert F.refresh_purchase_if_stale()[0] is False and len(calls) == 1         # 刚抓过 → 跳过
    old = time.time() - 13 * 3600
    os.utime(csv, (old, old))
    assert F.refresh_purchase_if_stale()[0] is True and len(calls) == 2          # 超过 12 小时 → 再抓


def test_all_codes_includes_configured_funds(tmp_path, monkeypatch):
    """新账户还没下单时，选基配置里挂的场外基金也要在费率刷新范围内。"""
    import json
    d = tmp_path / "data" / "accounts"
    d.mkdir(parents=True)
    (d / "sim-x.json").write_text(json.dumps({"trades": [], "holdings": {
        "credit": {"on": True, "funds": [{"code": "161119"}]}, "gold": {"on": True, "funds": [{"code": "000217"}]}}}))
    monkeypatch.setattr(F, "ROOT", tmp_path)
    codes = F.all_codes()
    assert "161119" in codes and "000217" in codes
