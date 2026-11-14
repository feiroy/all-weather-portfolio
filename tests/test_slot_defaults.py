"""位置默认开关跟着策略走（2026-11-14 用户：风险平价里没有 10 年国债，「如果没有，默认不要勾选」）。

账户数据全部在临时目录里，不碰 data/accounts。
"""
import asyncio
import json

import pytest

from allweather import accounts as AC
from allweather import holdings as HG
from allweather.pipeline import LIVE_STRATEGY, STRATEGY_ASSETS

RP = STRATEGY_ASSETS[LIVE_STRATEGY["B-RP"]]
CON = STRATEGY_ASSETS[LIVE_STRATEGY["B-Con"]]


def test_rp_and_v3c_do_not_use_bond_10y():
    assert "bond_10y" not in RP
    assert "bond_10y" not in STRATEGY_ASSETS[LIVE_STRATEGY["V3c"]]
    assert "bond_10y" in CON


def test_new_account_defaults_follow_strategy():
    h, opened, closed = HG.apply_strategy_slots(HG._default_holdings(), RP)
    assert h["bond_10y"]["on"] is False and closed == ["bond_10y"] and opened == []
    assert all(h[s]["on"] for s in RP)
    # 保守增强要用 10 年国债：全开
    h2, _, closed2 = HG.apply_strategy_slots(HG._default_holdings(), CON)
    assert closed2 == [] and h2["bond_10y"]["on"] is True


def test_switch_opens_needed_and_keeps_held_slots():
    h, _, _ = HG.apply_strategy_slots(HG._default_holdings(), RP)
    # 换回保守增强：10 年国债必须重新打开，否则它的权重会被摊给别的位置
    h2, opened, closed = HG.apply_strategy_slots(h, CON)
    assert opened == ["bond_10y"] and closed == [] and h2["bond_10y"]["on"] is True
    # 从保守增强换到风险平价，但 10 年国债还有持仓：不能关，关了就看不到也卖不掉
    h3, _, closed3 = HG.apply_strategy_slots(h2, RP, held={"bond_10y"})
    assert closed3 == [] and h3["bond_10y"]["on"] is True
    # 已经关着、又有持仓：保持原样，不替用户打开
    h4, opened4, _ = HG.apply_strategy_slots(h, RP, held={"bond_10y"})
    assert opened4 == [] and h4["bond_10y"]["on"] is False


def test_custom_slots_untouched():
    h = HG._default_holdings()
    h["159915"] = {"on": True, "label": "创业板", "funds": [{"code": "159915"}]}
    out, opened, closed = HG.apply_strategy_slots(h, RP)
    assert out["159915"]["on"] is True and "159915" not in opened + closed


def _user_holdings():
    """用户 2026-11-14 的「模拟实操」：先在内置位置上换好了场外基金。"""
    h = HG._default_holdings()
    for s, c in {"credit": "161119", "hs300": "006131", "divlow": "007467", "gold": "000217"}.items():
        h[s] = {"on": True, "funds": [{"code": c, "name": c, "unit": "份额"}]}
    return h


def test_custom_strategy_reuses_slot_already_holding_fund():
    """「用它实盘」时，内置位置已经挂着策略里的基金 → 用那个位置，不再另建同名位置（原来会乱成两份）。"""
    h = _user_holdings()
    fm = {k: {"code": k, "name": k} for k in ("us_sp500", "bond_30y", "nonferr", "ene",
                                                "161119", "006131", "007467", "000217", "159915")}
    out, added = HG.ensure_slots(h, fm)
    assert added == ["159915"], added                      # 只有真正的新基金才建位置
    use = [HG.slot_for_key(out, k) or k for k in fm]
    out2, opened, closed = HG.apply_strategy_slots(out, use)
    assert closed == ["bond_10y"], closed                  # 收益垫 / A股 / 红利低波 / 黄金都保持开着
    for s in ("credit", "hs300", "divlow", "gold", "159915"):
        assert out2[s]["on"] is True, s


def test_weights_keyed_by_code_land_on_holding_slot():
    h = _user_holdings()
    h["bond_10y"]["on"] = False
    w = {"161119": 0.6, "bond_30y": 0.2, "ene": 0.05, "007467": 0.15}
    sw = HG.slot_weights(w, h)
    assert abs(sw["credit"] - 0.6) < 1e-9 and abs(sw["divlow"] - 0.15) < 1e-9
    assert abs(sum(sw.values()) - 1) < 1e-9
    assert HG.unplaced_assets(w, h) == {}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    d = tmp_path / "accounts"
    monkeypatch.setattr(AC, "ACCOUNTS_DIR", d)
    monkeypatch.setattr(AC, "TRASH_DIR", d / ".trash")
    monkeypatch.setattr(AC, "INDEX_FILE", d / "index.json")
    monkeypatch.setattr(AC, "LEGACY_ACCOUNT", tmp_path / "sim_account.json")
    return tmp_path


class _Req:
    def __init__(self, body):
        self._b = body
        self.query_params = {}

    async def json(self):
        return self._b


def _call(fn, body):
    r = asyncio.run(fn(_Req(body)))
    return json.loads(r.body)


@pytest.mark.parametrize("stg,on10", [("B-RP", False), ("V3c", False), ("B-Con", True)])
def test_create_account_endpoint(store, stg, on10):
    from api import server as S
    aid = _call(S.create_account, {"name": "t", "kind": "模拟", "strategy": stg})["id"]
    h = AC.load(aid)["holdings"]
    assert h["bond_10y"]["on"] is on10
    assert all(h[s]["on"] for s in STRATEGY_ASSETS[LIVE_STRATEGY[stg]])


def test_create_from_copy_keeps_source_switches(store):
    from api import server as S
    src = _call(S.create_account, {"name": "src", "kind": "模拟", "strategy": "B-Con"})["id"]
    a = AC.load(src)
    a["holdings"]["gold"]["on"] = False
    AC.save(src, a)
    aid = _call(S.create_account, {"name": "copy", "kind": "模拟", "strategy": "B-RP", "from": src})["id"]
    h = AC.load(aid)["holdings"]
    assert h["gold"]["on"] is False and h["bond_10y"]["on"] is True   # 复制的配置原样保留
