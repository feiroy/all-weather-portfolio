"""交易记录里的「策略快照」（2026-11-16）。

事故背景：账户只存一个 `strategy` 字段（当前值），换过策略以后就查不出
「之前这 4 笔是按哪套权重下的单」，只能靠份额跟两套策略的建议反推，
用户和开发者各说各话查了很久。现在每笔记一笔都存一份当时的策略。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import api.server as S  # noqa: E402


def body(**kw) -> dict:
    b = {"side": "买入", "code": "161119", "slot": "credit", "date": "2026-11-16",
         "amount": 10000, "nav": 1.8, "fee": 1.0}
    b.update(kw)
    return b


def old_trade(**kw) -> dict:
    t = {"date": "2026-11-16", "side": "买入", "slot": "credit", "code": "161119",
         "shares": 5555.0, "nav": 1.8, "fee": 1.0}
    t.update(kw)
    return t


class TradeStrategySnapshot(unittest.TestCase):
    def test_custom_strategy_is_recorded(self):
        a = {"strategy": "custom:s1794201271532", "trades": []}
        self.assertEqual(S._trade_from_body(body(), a)["strategy"], "custom:s1794201271532")

    def test_builtin_strategy_is_recorded(self):
        a = {"strategy": "B-RP", "trades": []}
        self.assertEqual(S._trade_from_body(body(), a)["strategy"], "B-RP")

    def test_edit_keeps_the_original_snapshot(self):
        """改一笔不能把历史快照冲成「当前策略」，否则快照就没有意义了。"""
        a = {"strategy": "custom:new", "trades": [old_trade(strategy="B-RP")]}
        self.assertEqual(S._trade_from_body(body(), a, skip=0)["strategy"], "B-RP")

    def test_explicit_strategy_wins(self):
        """前端显式传的优先（补录历史成交时要能指定当时的策略）。"""
        a = {"strategy": "custom:new", "trades": []}
        self.assertEqual(S._trade_from_body(body(strategy="B-Con"), a)["strategy"], "B-Con")

    def test_old_trade_without_snapshot_backfills_current(self):
        """老记录没有 strategy：改一次就补上当前值，比一直留空强。"""
        a = {"strategy": "B-RP", "trades": [old_trade()]}
        self.assertEqual(S._trade_from_body(body(), a, skip=0)["strategy"], "B-RP")

    def test_no_strategy_field_on_account_still_valid(self):
        """账户文件里没有 strategy（异常数据）也不能炸。"""
        a = {"trades": []}
        self.assertEqual(S._trade_from_body(body(), a)["strategy"], "")

    def test_snapshot_does_not_break_other_fields(self):
        a = {"strategy": "B-RP", "trades": []}
        t = S._trade_from_body(body(), a)
        self.assertEqual(t["code"], "161119")
        self.assertEqual(t["slot"], "credit")
        self.assertAlmostEqual(t["shares"], (10000 - 1) / 1.8, places=4)
        self.assertEqual(t["date"], "2026-11-16")


if __name__ == "__main__":
    unittest.main()
