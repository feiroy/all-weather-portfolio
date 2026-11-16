"""「新钱怎么分」建仓单（2026-11-14 用户「操作的时候应该提示下，否则不知道怎么买」）。

原来场内一律向下取整、剩下的钱不知去向：10 万建仓 30 年国债只给 1 手（11%，目标 20%），
少投 9 千多。现在：场内取最接近目标的整手，取整差额和佣金由最大那笔场外兜底，整笔花完；
每行带下单顺序和怎么买。账户只在内存里构造，不读写 data/accounts。
"""
import pandas as pd
import pytest

from allweather.portfolio import Portfolio

PX = {"511130": 110.418, "159981": 1.812}


def _fund(code, otc):
    return {"code": code, "name": code, "unit": "份额" if otc else "股", "lot": 1 if otc else 100}


def _acct(slots):
    return {"name": "t", "kind": "模拟", "strategy": "B-RP", "capital": 0, "created": "2026-11-14",
            "trades": [], "holdings": {s: {"on": True, "funds": [_fund(c, otc)]} for s, (c, otc) in slots.items()}}


SLOTS = {"credit": ("161119", True), "bond_30y": ("511130", False),
         "ene": ("159981", False), "divlow": ("007467", True)}
W = pd.Series({"credit": 0.6291, "bond_30y": 0.20, "ene": 0.0539, "divlow": 0.1171})


@pytest.fixture(scope="module")
def P():
    p = Portfolio(_acct(SLOTS), W)
    if any(r["px"] <= 0 for r in p.plan["rows"]):
        pytest.skip("本地缺这几只基金的净值缓存")
    return p


def test_build_spends_all_and_rounds_to_nearest_lot(P):
    d = P.dca(100000, PX)
    by = {r["code"]: r for r in d["rows"]}
    assert by["511130"]["qty"] == 200          # 目标 2 万、一手 1.1 万：取 2 手，不是向下的 1 手
    assert by["159981"]["qty"] == 3000         # 目标 5,388、一手 181：取 30 手
    assert abs(d["buy"] - 100000) < 0.01       # 整笔花完，不再剩 9 千
    assert d["lost"] == 0
    # 兜底那笔 = 本金 − 场内成交 − 场内佣金 − 其它场外
    exch = sum(by[c]["amount"] + by[c]["fee"] for c in ("511130", "159981"))
    assert abs(by["161119"]["amount"] - (100000 - exch - by["007467"]["amount"])) < 0.01


def test_rows_carry_order_and_instructions(P):
    d = P.dca(100000, PX)
    steps = [r["step"] for r in d["rows"] if r["amount"] > 0]
    assert steps == sorted(steps) and steps[0] == 1 and steps[-1] == 3
    last = [r for r in d["rows"] if r["step"] == 3]
    assert len(last) == 1 and last[0]["code"] == "161119"          # 最大那笔场外兜底
    assert all(r["how"] for r in d["rows"] if r["amount"] > 0)
    assert "取 2 手" in next(r for r in d["rows"] if r["code"] == "511130")["note"]
    assert any("先买场内" in s for s in d["steps"]) and any("记一笔" in s for s in d["steps"])
    assert next(r for r in d["rows"] if r["code"] == "511130")["px_src"] == "现价"


def test_rounding_up_never_overspends(P):
    # 30 年国债要 9 千、一手 1.1 万：四舍五入会买 1 手超预算 → 必须退回 0 手，钱并进兜底那笔
    p = Portfolio(_acct({"credit": ("161119", True), "bond_30y": ("511130", False)}),
                  pd.Series({"credit": 0.1, "bond_30y": 0.9}))
    d = p.dca(10000, PX)
    by = {r["code"]: r for r in d["rows"]}
    assert by["511130"]["qty"] == 0 and "并进" in by["511130"]["note"]
    assert abs(by["161119"]["amount"] - 10000) < 0.01 and abs(d["buy"] - 10000) < 0.01


def test_without_otc_falls_back_to_floor(P):
    p = Portfolio(_acct({"bond_30y": ("511130", False), "ene": ("159981", False)}),
                  pd.Series({"bond_30y": 0.8, "ene": 0.2}))
    d = p.dca(30000, PX)
    by = {r["code"]: r for r in d["rows"]}
    assert by["511130"]["qty"] == 200            # 24,000 / 11,042 = 2.17 → 2 手（没有兜底只能向下）
    assert d["buy"] <= 30000
    assert not any(r["step"] == 3 for r in d["rows"])


def test_otc_shares_deduct_subscription_fee(P):
    """场外份数必须扣申购费（2026-11-16）。

    页面给场外的是「实付金额」（含申购费），份额应该是 `金额 × (1-费率) / 净值`。
    原来直接用 `金额 / 净值`，161119 费率 0.08% 时 10 万建仓多给约 30 份，
    跟 App 的确认份额对不上，记「记一笔」时会算少。
    """
    from allweather import fees as FEES

    d = P.dca(100000, PX)
    by = {r["code"]: r for r in d["rows"]}
    for code in ("161119", "007467"):
        r = by[code]
        rate = float(FEES.get(code).get("buy_rate") or 0)
        fee = round(r["amount"] * rate, 2)          # 和 fee_of 一样按分取整
        assert r["qty"] == pytest.approx((r["amount"] - fee) / r["px"], abs=1e-3), \
            f"{code} 的份数没扣申购费（费率 {rate}）"


def test_total_spend_equals_amount_with_otc_fee(P):
    """申购费含在买入金额里：总支出仍正好等于投入的钱，不会超。"""
    d = P.dca(100000, PX)
    exch = [r for r in d["rows"] if not r["otc"]]
    otc = [r for r in d["rows"] if r["otc"]]
    total = sum(r["amount"] + r["fee"] for r in exch) + sum(r["amount"] for r in otc)
    assert total == pytest.approx(100000, abs=1.0)


def test_order_quantity_fee_rate_contract():
    """`order_quantity` 的费率契约：传了就扣份额，不传保持老行为。"""
    from allweather.holdings import order_quantity

    otc = {"unit": "份额", "lot": 1, "min_amount": 1}
    qty, amt = order_quantity(otc, 10000, 2.0, fee_rate=0.0008)
    assert amt == 10000
    assert qty == pytest.approx(10000 * (1 - 0.0008) / 2.0)

    qty0, _ = order_quantity(otc, 10000, 2.0)          # 默认不扣，老调用点不变
    assert qty0 == pytest.approx(5000)

    exch = {"unit": "股", "lot": 100}
    q1, a1 = order_quantity(exch, 25000, 110.0, fee_rate=0.0008)   # 场内不看费率
    assert q1 == 200 and a1 == pytest.approx(22000)
