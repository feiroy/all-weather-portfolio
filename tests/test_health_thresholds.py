"""体检阈值：集中度按「策略目标」判，不按固定 25% / 50%（2026-11-18）。

用户问「体检阈值是怎么判断的」，翻开一看那条「最大仓位 25%」对 sim-c01062 是：
信用债实际 61.3%、策略目标 62.2%，偏离只有 −0.8pp，账目完全健康，却天天亮红灯，
还建议「给这个位置再挂一只同类基金」——同一资产再拆一只，风险一分没降，只多付一份管理费。

25% 那条线是从股票账户「别押单只个股」搬过来的常识，和资产配置策略天生冲突：
风险平价本来就靠债券吃大头。真正该判的是「实际离策略目标有多远」，也就是原来那条 ±5pp。
两条合并成一条，体检从 5 项变成 3 项（偏离 / 回撤 / 单只浮亏）。

顺带修掉同一段里的两处 bug：
  · else 分支显示 `smax`（位置权重）、判定却用 `big["w_now"]`（单只权重），数字和规则不同源；
  · 名字取最大单只、百分比取最大位置，一个位置挂多只时必然张冠李戴。
现在「谁 / 占多少 / 目标多少 / 偏离几 pp」全部来自同一行。
"""
from __future__ import annotations

import types

import pandas as pd

from allweather.portfolio import Portfolio


def _fake(rows: list[dict], holdings: dict | None = None, nav: list[float] | None = None):
    """只喂 health() 真正会读的三个字段（plan.rows / holdings / daily），不建整套面板。"""
    P = types.SimpleNamespace(plan={"rows": rows}, holdings=holdings or {},
                              daily=pd.DataFrame({"nav": nav or []}))
    P.health = types.MethodType(Portfolio.health, P)
    return P


def _row(code, name, slot, w_now, dev=0.0, first=True, shares=100, pl=None):
    return {"code": code, "f": {"code": code, "name": name}, "slot": slot,
            "w_now": w_now, "dev": dev, "slot_first": first, "shares": shares, "pl": pl}


def test_big_weight_matching_target_is_not_a_warning():
    """61.3% 撞 25% 那条老线会误报；目标就是 62.1%，偏离 −0.8pp，应该全绿。"""
    P = _fake([_row("161119", "易方达中债新综指", "credit", 0.613, dev=-0.008)])
    h = P.health()
    assert h["bad"] == [], f"不该报警：{h['bad']}"
    item = h["items"][0]
    assert item["label"] == "最大偏离"
    assert "61.3%" in item["now"] and "目标 62.1%" in item["now"] and "-0.8pp" in item["now"]
    assert item["line"] == "±5pp"


def test_over_target_5pp_is_a_warning():
    """实际 40%、目标 30%（+10pp）→ 越线，这是真超配。"""
    P = _fake([_row("511220", "城投债 ETF", "credit", 0.40, dev=0.10)])
    h = P.health()
    assert len(h["bad"]) == 1
    it = h["bad"][0]
    assert it["label"] == "最大偏离" and it["over"] == "该调了"
    assert "+10.0pp" in it["now"]


def test_no_fixed_concentration_line_left():
    """守住回退：25% / 50% 那两条固定线不能再出现。"""
    P = _fake([_row("161119", "易方达中债新综指", "credit", 0.613, dev=-0.008)])
    lines = {i["line"] for i in P.health()["items"]}
    assert "25%" not in lines and "50%" not in lines


def test_label_and_pct_come_from_the_same_slot():
    """一个位置挂两只（30% + 35% = 65%）时，名字必须是位置名 + 只数，不能是最大单只的名字。"""
    rows = [
        _row("161119", "易方达中债新综指", "credit", 0.30, dev=-0.03, first=True),
        _row("000033", "易方达信用债 C", "credit", 0.35, dev=0.0, first=False),
    ]
    h = _fake(rows).health()
    now = h["items"][0]["now"]
    assert now.startswith("65.0%"), now          # 位置汇总，不是 35%
    assert "2 只" in now and "易方达信用债 C" not in now


def test_empty_account():
    assert _fake([]).health() == {"items": [], "bad": [], "days": 0}


def test_live_accounts_use_the_new_items():
    """真实账户：体检项只能是这三类，别再冒出「最大仓位」这种固定线。"""
    from allweather import accounts as AC

    allowed = {"最大偏离", "最大回撤", "单只最大浮亏"}
    seen = 0
    for aid in ("sim-c01062", "main"):
        if not AC.load(aid):
            continue
        import api.server as S

        h = S._portfolio(aid)[0].health()
        assert {i["label"] for i in h["items"]} <= allowed, h["items"]
        seen += 1
    if not seen:
        import pytest

        pytest.skip("没有可用的真实账户")
