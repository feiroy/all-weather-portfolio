"""我的持仓 / 提醒 / 基准：换基金后按自己的基金算口径的单元测试。"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from allweather import alerts as AL     # noqa: E402
from allweather import benchmark as BM  # noqa: E402
from allweather import holdings as HG   # noqa: E402


def make_holdings(codes: dict[str, str] | None = None) -> dict:
    h = HG._default_holdings()
    for s, c in (codes or {}).items():
        h[s]["code"] = c
        # 测试不联网，直接指定单位，不依赖 default_unit 的申购状态查询
        h[s]["unit"] = "份额" if str(c).startswith("0") or c == "110020" else "股"
        h[s]["lot"] = 100 if h[s]["unit"] == "股" else 1
    return h


class HoldingsConfig(unittest.TestCase):
    def test_default_matches_backtest_codes(self):
        h = HG._default_holdings()
        self.assertEqual([h[s]["code"] for s in HG.SLOTS],
                         ["510300", "513500", "511220", "511260", "511130", "518850", "159980", "501018"])

    def test_active_skips_disabled_and_empty(self):
        h = make_holdings()
        h["wti"]["on"] = False
        h["gold"]["code"] = ""
        self.assertNotIn("wti", HG.active(h))
        self.assertNotIn("gold", HG.active(h))

    def test_slot_of_reverse_lookup(self):
        h = make_holdings({"hs300": "110020"})
        self.assertEqual(HG.slot_of("110020", h), "hs300")
        self.assertIsNone(HG.slot_of("999999", h))

    def test_slot_weights_renormalizes_over_active(self):
        h = make_holdings()
        h["wti"]["on"] = False                       # wti 权重不为 0 时关掉它
        w = {"hs300": .2, "us_sp500": .2, "credit": .2, "bond_10y": .1,
             "bond_30y": .1, "gold": .1, "nonferr": .1, "wti": .1}
        out = HG.slot_weights(w, h)
        self.assertNotIn("wti", out)
        self.assertAlmostEqual(sum(out.values()), 1.0)

    def test_slot_weights_accepts_pandas_series(self):
        """权重从 apply_signal_overrides 出来是 Series，不能假设是 dict。"""
        h = make_holdings()
        w = pd.Series({"hs300": .5, "us_sp500": .5})
        out = HG.slot_weights(w, h)
        self.assertAlmostEqual(out["hs300"], 0.5)

    def test_every_slot_has_a_bucket(self):
        for s in HG.SLOTS:
            self.assertIn(s, HG.SLOT_BUCKET)


class OrderQuantity(unittest.TestCase):
    def test_exchange_traded_rounds_to_lot(self):
        h = make_holdings()["hs300"]          # 场内，100 股一手
        qty, amt = HG.order_quantity(h, 41519, 4.18)
        self.assertEqual(qty % 100, 0)
        self.assertAlmostEqual(amt, qty * 4.18)

    def test_off_exchange_buys_by_amount(self):
        h = make_holdings({"hs300": "110020"})["hs300"]
        qty, amt = HG.order_quantity(h, 41519, 1.6987)
        self.assertAlmostEqual(amt, 41519.0)
        self.assertAlmostEqual(qty * 1.6987, amt, places=4)

    def test_off_exchange_respects_min_amount(self):
        h = make_holdings({"hs300": "110020"})["hs300"]
        h["min_amount"] = 100.0
        qty, amt = HG.order_quantity(h, 20, 1.6987)
        self.assertEqual(amt, 100.0)

    def test_zero_nav_gives_no_order(self):
        self.assertEqual(HG.order_quantity(make_holdings()["hs300"], 1000, 0), (0.0, 0.0))

    def test_is_otc_by_unit(self):
        self.assertTrue(HG.is_otc({"unit": "份额"}))
        self.assertFalse(HG.is_otc({"unit": "股"}))


class Benchmark(unittest.TestCase):
    def test_monthly_rebalance_resets_to_target(self):
        idx = pd.bdate_range("2024-01-01", "2024-06-30")
        px = pd.DataFrame({"a": np.linspace(10, 12, len(idx)),
                           "b": np.linspace(20, 18, len(idx))}, index=idx)
        s = BM._replay(px, {"a": .5, "b": .5}, "2024-01-01")
        self.assertGreater(len(s), 100)
        self.assertAlmostEqual(float(s.iloc[0]), 1.0)
        # 全部区间内 a 涨 b 跌，权重再平衡后净值应落在两者之间
        self.assertTrue(min(12 / 10, 18 / 20) <= float(s.iloc[-1]) <= max(12 / 10, 18 / 20))

    def test_replay_target_accepts_series_weights(self):
        px = pd.DataFrame({"hs300": np.linspace(4, 4.4, 60)},
                          index=pd.bdate_range("2024-01-01", periods=60))
        s = BM.replay_target(pd.Series({"hs300": 1.0}), "2024-01-01", prices=px)
        self.assertGreater(len(s), 1)

    def test_empty_weights_give_empty_curve(self):
        px = pd.DataFrame({"hs300": [4.0, 4.1]}, index=pd.bdate_range("2024-01-01", periods=2))
        self.assertEqual(len(BM.replay_target({}, "2024-01-01", prices=px)), 0)

    def test_strategy_curve_missing_file_returns_none(self):
        self.assertIsNone(BM.strategy_curve("不存在的曲线"))


class Alerts(unittest.TestCase):
    def setUp(self):
        self.h = make_holdings({"hs300": "110020"})
        self.label = HG.SLOT_LABEL

    def test_deviation_ignores_small_drift(self):
        w = {"hs300": .5, "us_sp500": .5}
        mv = {"hs300": 510., "us_sp500": 490.}          # 偏离 2pp
        out = AL.compute(mv, w, self.h, self.label, {})
        self.assertEqual(out["偏离"], [])

    def test_deviation_levels(self):
        w = {"hs300": .5, "us_sp500": .5}
        mv = {"hs300": 800., "us_sp500": 200.}          # 偏离 30pp
        out = AL.compute(mv, w, self.h, self.label, {})
        self.assertEqual(out["偏离"][0]["level"], "urgent")
        self.assertIn("建议调仓", out["偏离"][0]["text"])

    def test_cash_alerts(self):
        out = AL.compute({"hs300": 100.}, {"hs300": 1.0}, self.h, self.label, {}, cash=900.)
        self.assertTrue(any("现金占比" in x["text"] for x in out["体检"]))

    def test_valuation_bucket_boundaries(self):
        self.assertEqual(AL.bucket_of_score(20)[0], "猎杀区")
        self.assertEqual(AL.bucket_of_score(15)[0], "稳中求胜")
        self.assertEqual(AL.bucket_of_score(10)[0], "中性观察")
        self.assertEqual(AL.bucket_of_score(6)[0], "高位警戒")
        self.assertEqual(AL.bucket_of_score(3)[0], "泡沫区")
        self.assertEqual(AL.bucket_of_score(None)[0], "—")

    def test_valuation_alert_uses_my_fund_code(self):
        val = {"110020": {"name": "易方达沪深300", "pe_pct": 80., "pb_pct": 70., "score": 5}}
        out = AL.compute({"hs300": 100.}, {"hs300": 1.0}, self.h, self.label, val)
        self.assertEqual(len(out["估值"]), 1)
        self.assertIn("110020", out["估值"][0]["text"])

    def test_benchmark_gap_over_threshold_raises_alert(self):
        idx = pd.bdate_range("2024-01-01", periods=40)
        mine = pd.DataFrame({"nav": np.linspace(1.0, 1.10, 40), "equity": 1.0}, index=idx)
        bench = pd.Series(np.linspace(1.0, 1.02, 40), index=idx)
        out = AL.compute({"hs300": 100.}, {"hs300": 1.0}, self.h, self.label, {},
                         daily=mine, bench={"默认": bench})
        self.assertIn("对比默认", out["指标"])
        self.assertTrue(any("与「默认」差" in x["text"] for x in out["体检"]))

    def test_unrealized_loss_alert(self):
        out = AL.compute({"hs300": 85.}, {"hs300": 1.0}, self.h, self.label, {},
                         pos={"110020": 100.}, cost={"110020": 1.0},
                         slot_of_code=lambda c: HG.slot_of(c, self.h))
        self.assertTrue(any("浮亏" in x["text"] for x in out["体检"]))


if __name__ == "__main__":
    unittest.main()
