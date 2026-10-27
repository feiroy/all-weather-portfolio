"""账户重放：转入 / 转出（旧写法入金 / 出金）必须等价，且不能让收益率虚增。"""
from __future__ import annotations

import unittest

import pandas as pd

from allweather.sim_account import MONEY_SIDES, fund_pnl, replay


def _prices(days=4, value=1.0):
    idx = pd.bdate_range("2024-01-02", periods=days)
    return pd.DataFrame({"A": [value] * days}, index=idx)


def _trade(day, side, amount, price=0.0, asset=""):
    return {"date": str(day), "side": side, "asset": asset,
            "shares": amount, "price": price, "fee": 0.0}


class TestMoneySides(unittest.TestCase):
    def test_new_words_are_the_public_ones(self):
        self.assertIn("转入", MONEY_SIDES)
        self.assertIn("转出", MONEY_SIDES)
        # 旧数据里的写法仍要认，否则历史记录会被当成未知类型静默丢掉
        self.assertIn("入金", MONEY_SIDES)
        self.assertIn("出金", MONEY_SIDES)

    def test_transfer_in_raises_cash_and_units_but_not_nav(self):
        prices = _prices()
        daily, _, _, cash, units = replay(
            [_trade("2024-01-03", "转入", 500.0)], prices, capital=1000.0, created="2024-01-02")
        self.assertAlmostEqual(cash, 1500.0, places=6)
        self.assertAlmostEqual(units, 1500.0, places=6)      # 净值 1.0 时金额即份额
        self.assertAlmostEqual(float(daily["nav"].iloc[-1]), 1.0, places=6)   # 不虚增收益
        self.assertAlmostEqual(float(daily["equity"].iloc[-1]), 1500.0, places=6)

    def test_old_words_behave_exactly_the_same(self):
        prices = _prices()
        a = replay([_trade("2024-01-03", "转入", 500.0)], prices, 1000.0, "2024-01-02")
        b = replay([_trade("2024-01-03", "入金", 500.0)], prices, 1000.0, "2024-01-02")
        self.assertAlmostEqual(a[3], b[3], places=6)         # cash
        self.assertAlmostEqual(a[4], b[4], places=6)         # units
        self.assertAlmostEqual(float(a[0]["nav"].iloc[-1]), float(b[0]["nav"].iloc[-1]), places=9)

    def test_transfer_out_lowers_cash_and_units(self):
        prices = _prices()
        daily, _, _, cash, units = replay(
            [_trade("2024-01-03", "转出", 400.0)], prices, capital=1000.0, created="2024-01-02")
        self.assertAlmostEqual(cash, 600.0, places=6)
        self.assertAlmostEqual(units, 600.0, places=6)
        self.assertAlmostEqual(float(daily["nav"].iloc[-1]), 1.0, places=6)

    def test_transfer_in_nav_stays_neutral_when_prices_moved(self):
        """净值已经涨到 1.2 时再转入：新份额按 1.2 折算，收益率不应被这笔钱拉高。"""
        idx = pd.bdate_range("2024-01-02", periods=4)
        prices = pd.DataFrame({"A": [1.0, 1.0, 1.2, 1.2]}, index=idx)
        daily, pos, _, cash, units = replay(
            [_trade("2024-01-02", "买入", 1000.0, price=1.0, asset="A"),
             _trade("2024-01-04", "转入", 1200.0)],
            prices, capital=1000.0, created="2024-01-02")
        self.assertAlmostEqual(pos["A"], 1000.0, places=6)
        # 转入当天按**上一交易日**净值折算份额（既有口径）：1200 / 1.0 = 1200 份
        self.assertAlmostEqual(units, 2200.0, places=6)
        self.assertAlmostEqual(cash, 1200.0, places=6)
        nav = float(daily["nav"].iloc[-1])
        self.assertAlmostEqual(nav, 2400.0 / 2200.0, places=6)
        # 关键：钱进来不能变成收益。若不折算份额，1000 份配 2400 元资产会算成 2.4 的净值（虚假翻倍）
        self.assertLess(nav, 1.2)

    def test_buy_then_transfer_does_not_double_count(self):
        """买入只是现金换成基金，总资产不变；再转入的钱才增加总资产。"""
        prices = _prices(value=2.0)
        daily, pos, _, cash, _ = replay(
            [_trade("2024-01-03", "买入", 100.0, price=2.0, asset="A"),
             _trade("2024-01-04", "转入", 300.0)],
            prices, capital=1000.0, created="2024-01-02")
        self.assertAlmostEqual(pos.get("A", 0.0), 100.0, places=6)
        self.assertAlmostEqual(cash, 1000.0 - 200.0 + 300.0, places=6)
        self.assertAlmostEqual(float(daily["equity"].iloc[-1]), 1000.0 + 300.0, places=6)


def _nav(values, start="2024-01-02"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)))


class TestFundPnl(unittest.TestCase):
    """单只基金的累计盈亏曲线（支付宝「累计盈亏」口径）：买入当天从 0 起，卖出后已实现收益不能消失。"""

    def test_buy_day_starts_at_zero_and_follows_nav(self):
        nav = _nav([1.0, 1.1, 1.2])
        pnl = fund_pnl([{"date": "2024-01-02", "side": "买入", "shares": 1000.0,
                         "nav": 1.0, "fee": 0.0}], nav)
        self.assertAlmostEqual(float(pnl.iloc[0]), 0.0, places=6)     # 按当天净值成交，当天不赚不亏
        self.assertAlmostEqual(float(pnl.iloc[1]), 100.0, places=6)   # 1000 份 × 0.1
        self.assertAlmostEqual(float(pnl.iloc[2]), 200.0, places=6)

    def test_fee_counts_as_loss_from_day_one(self):
        pnl = fund_pnl([{"date": "2024-01-02", "side": "买入", "shares": 1000.0,
                         "nav": 1.0, "fee": 5.0}], _nav([1.0, 1.0]))
        self.assertAlmostEqual(float(pnl.iloc[0]), -5.0, places=6)

    def test_sell_keeps_realized_profit(self):
        """涨到 1.2 全卖：曲线停在 +200，不能因为份额清零就归 0（这正是和「持有收益」的差别）。"""
        pnl = fund_pnl([
            {"date": "2024-01-02", "side": "买入", "shares": 1000.0, "nav": 1.0, "fee": 0.0},
            {"date": "2024-01-03", "side": "卖出", "shares": 1000.0, "nav": 1.2, "fee": 0.0},
        ], _nav([1.0, 1.2, 1.2]))
        self.assertAlmostEqual(float(pnl.iloc[2]), 200.0, places=6)

    def test_partial_sell_matches_holding_plus_realized(self):
        pnl = fund_pnl([
            {"date": "2024-01-02", "side": "买入", "shares": 1000.0, "nav": 1.0, "fee": 0.0},
            {"date": "2024-01-03", "side": "卖出", "shares": 400.0, "nav": 1.5, "fee": 0.0},
        ], _nav([1.0, 1.5]))
        # 卖 400 份得 600（成本 400），剩 600 份值 900（成本 600）
        self.assertAlmostEqual(float(pnl.iloc[1]), (900 - 600) + (600 - 400), places=6)

    def test_money_sides_do_not_produce_a_curve(self):
        self.assertTrue(fund_pnl([{"date": "2024-01-02", "side": "转入", "shares": 1000.0}],
                                 _nav([1.0, 1.1])).empty)

    def test_trade_older_than_nav_history_still_draws(self):
        """成交日早于净值起点（净值只回看最近两年）时，从第一条净值开始画，不能整条空掉。"""
        pnl = fund_pnl([{"date": "2020-01-02", "side": "买入", "shares": 100.0,
                         "nav": 1.0, "fee": 0.0}], _nav([1.2, 1.3]))
        self.assertEqual(len(pnl), 2)
        self.assertAlmostEqual(float(pnl.iloc[-1]), 100 * 1.3 - 100.0, places=6)


if __name__ == "__main__":
    unittest.main()