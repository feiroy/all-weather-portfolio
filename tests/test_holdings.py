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


def _fund(code: str, unit: str | None = None, **kw) -> dict:
    """造一只基金配置（测试不联网，单位直接指定，不走 default_unit 的申购状态查询）。"""
    if unit is None:
        unit = "份额" if (str(code).startswith("0") or code == "110020") else "股"
    return HG._fund({"code": code, "unit": unit,
                     "lot": 100 if unit == "股" else 1, **kw})


def make_holdings(codes: dict[str, str] | None = None) -> dict:
    h = HG._default_holdings()
    for s, c in (codes or {}).items():
        h[s] = {"on": True, "funds": [_fund(c)]}
    return h


def one(slot: str, h: dict | None = None) -> dict:
    """取某个位置的第一只基金配置（下单/单位判断都按基金，不按位置）。"""
    return HG.funds((h or make_holdings())[slot])[0]


class HoldingsConfig(unittest.TestCase):
    def test_default_matches_backtest_codes(self):
        h = HG._default_holdings()
        self.assertEqual([HG.codes(h[s]) for s in HG.SLOTS],
                         [["510300"], ["513500"], ["511220"], ["511260"], ["511130"],
                          ["518850"], ["159980"], ["501018"]])

    def test_active_skips_disabled_and_empty(self):
        h = make_holdings()
        h["wti"]["on"] = False
        h["gold"] = {"on": True, "funds": []}        # 一只都不挂 = 不持有
        self.assertNotIn("wti", HG.active(h))
        self.assertNotIn("gold", HG.active(h))

    def test_slot_of_reverse_lookup(self):
        h = make_holdings({"hs300": "110020"})
        self.assertEqual(HG.slot_of("110020", h), "hs300")
        self.assertIsNone(HG.slot_of("999999", h))

    def test_slot_of_finds_second_fund_in_slot(self):
        h = make_holdings()
        h["hs300"] = {"on": True, "funds": [_fund("110020"), _fund("000961")]}
        self.assertEqual(HG.slot_of("000961", h), "hs300")

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


class MultiFundPerSlot(unittest.TestCase):
    """一个位置可以挂多只基金，也可以一只都不挂。"""

    def test_equal_share_when_unspecified(self):
        h = {"on": True, "funds": [_fund("110020"), _fund("000961")]}
        self.assertEqual([round(x, 3) for x in HG.share_of(h)], [0.5, 0.5])
        self.assertEqual(HG.codes(h), ["110020", "000961"])

    def test_explicit_share_is_normalized(self):
        h = {"on": True, "funds": [_fund("110020", share=3.0), _fund("000961", share=1.0)]}
        self.assertEqual([round(x, 3) for x in HG.share_of(h)], [0.75, 0.25])

    def test_add_fund_dedupes_and_rebalances(self):
        h = {"on": True, "funds": [_fund("110020")]}
        h = HG.add_fund(h, "110020", unit="份额")            # 重复加不生效
        self.assertEqual(HG.codes(h), ["110020"])
        h = HG.add_fund(h, "000961", unit="份额")            # 第二只 → 等权
        self.assertEqual(HG.codes(h), ["110020", "000961"])
        self.assertEqual([round(x, 3) for x in HG.share_of(h)], [0.5, 0.5])

    def test_remove_last_fund_makes_slot_inactive(self):
        h = make_holdings()
        h["wti"] = HG.remove_fund(h["wti"], "501018")
        self.assertEqual(HG.funds(h["wti"]), [])
        self.assertNotIn("wti", HG.active(h))
        self.assertIsNone(HG.slot_of("501018", h))

    def test_remove_one_keeps_other_shares(self):
        h = {"on": True, "funds": [_fund("110020", share=0.6), _fund("000961", share=0.4)]}
        h = HG.remove_fund(h, "000961")
        self.assertEqual(HG.codes(h), ["110020"])
        self.assertEqual([round(x, 3) for x in HG.share_of(h)], [1.0])

    def test_all_codes_and_fund_meta(self):
        h = make_holdings()
        h["hs300"] = {"on": True, "funds": [_fund("110020", name="易方达沪深300"),
                                            _fund("000961", name="天弘沪深300")]}
        self.assertIn("000961", HG.all_codes(h))
        s, f = HG.fund_meta(h, "000961")
        self.assertEqual((s, f["name"]), ("hs300", "天弘沪深300"))
        self.assertEqual(HG.fund_meta(h, "999999"), (None, {}))

    def test_legacy_single_fund_structure_still_readable(self):
        """老的 {"code": ...} 配置必须还能读，否则升级一次配置全丢。"""
        old = {"hs300": {"code": "110020", "name": "沪深300联接", "unit": "份额",
                         "lot": 1, "on": True}}
        self.assertEqual(HG.codes(old["hs300"]), ["110020"])
        self.assertEqual(HG.active(old), ["hs300"])
        self.assertEqual(HG.slot_of("110020", old), "hs300")
        norm = HG._norm_slot(old["hs300"])
        self.assertEqual(norm["funds"][0]["code"], "110020")
        self.assertEqual(norm["funds"][0]["share"], 1.0)

    def test_load_migrates_and_save_roundtrips(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            fp = Path(d) / "holdings.json"
            fp.write_text(json.dumps({"holdings": {"hs300": {"code": "110020", "unit": "份额"}},
                                      "updated": ""}, ensure_ascii=False), encoding="utf-8")
            with patch.object(HG, "HOLDINGS_FILE", fp):
                loaded = HG.load()
                self.assertEqual(HG.codes(loaded["holdings"]["hs300"]), ["110020"])
                HG.save(loaded["holdings"])
                again = HG.load()
                self.assertEqual(HG.codes(again["holdings"]["hs300"]), ["110020"])
                self.assertIn("funds", json.loads(fp.read_text(encoding="utf-8"))["holdings"]["hs300"])


class OrderQuantity(unittest.TestCase):
    def test_exchange_traded_rounds_to_lot(self):
        h = one("hs300")                              # 场内，100 股一手
        qty, amt = HG.order_quantity(h, 41519, 4.18)
        self.assertEqual(qty % 100, 0)
        self.assertAlmostEqual(amt, qty * 4.18)

    def test_off_exchange_buys_by_amount(self):
        h = one("hs300", make_holdings({"hs300": "110020"}))
        qty, amt = HG.order_quantity(h, 41519, 1.6987)
        self.assertAlmostEqual(amt, 41519.0)
        self.assertAlmostEqual(qty * 1.6987, amt, places=4)

    def test_off_exchange_respects_min_amount(self):
        h = one("hs300", make_holdings({"hs300": "110020"}))
        h["min_amount"] = 100.0
        qty, amt = HG.order_quantity(h, 20, 1.6987)
        self.assertEqual(amt, 100.0)

    def test_zero_nav_gives_no_order(self):
        self.assertEqual(HG.order_quantity(one("hs300"), 1000, 0), (0.0, 0.0))

    def test_is_otc_by_unit(self):
        self.assertTrue(HG.is_otc({"unit": "份额"}))
        self.assertFalse(HG.is_otc({"unit": "股"}))


class PlanInvest(unittest.TestCase):
    """定投分配：只买不卖，按目标权重补缺口。"""

    @staticmethod
    def _slot(key, w, mv, items=None):
        return {"slot": key, "w": w, "mv": mv,
                "items": items or [{"code": f"{key}_code", "x": 1.0}]}

    def test_first_invest_splits_by_weight(self):
        slots = [self._slot("hs300", .5, 0), self._slot("credit", .3, 0),
                 self._slot("gold", .2, 0)]
        out = HG.plan_invest(slots, 10000)
        got = {o["slot"]: o["amount"] for o in out}
        self.assertAlmostEqual(got["hs300"], 5000, places=2)
        self.assertAlmostEqual(got["credit"], 3000, places=2)
        self.assertAlmostEqual(got["gold"], 2000, places=2)
        self.assertAlmostEqual(sum(got.values()), 10000, places=4)

    def test_underweight_slot_gets_more(self):
        # 目标 50/50，实际 40/60 → 新钱先补 a 的缺口，投完正好对齐
        slots = [self._slot("a", .5, 4000), self._slot("b", .5, 6000)]
        out = {o["slot"]: o["amount"] for o in HG.plan_invest(slots, 10000)}
        self.assertGreater(out["a"], out["b"])
        self.assertAlmostEqual(out["a"] + out["b"], 10000, places=4)
        self.assertAlmostEqual(out["a"], 6000, places=2)   # 缺口 6000，投后 1:1
        self.assertAlmostEqual(out["b"], 4000, places=2)

    def test_overweight_slot_gets_nothing_and_rest_is_spread(self):
        # 目标 50/50，实际 80/20：a 已超配（16000 > 目标 15000），钱全给 b
        slots = [self._slot("a", .5, 16000), self._slot("b", .5, 4000)]
        out = {o["slot"]: o["amount"] for o in HG.plan_invest(slots, 10000)}
        self.assertNotIn("a", out)                      # 超配的一分不给
        self.assertAlmostEqual(out["b"], 10000, places=4)

    def test_fully_balanced_falls_back_to_weight(self):
        # 已经完全对齐 → 缺口为 0，按权重摊（否则这笔钱无处可去）
        slots = [self._slot("a", .6, 6000), self._slot("b", .4, 4000)]
        out = {o["slot"]: o["amount"] for o in HG.plan_invest(slots, 5000)}
        self.assertAlmostEqual(out["a"], 3000, places=2)
        self.assertAlmostEqual(out["b"], 2000, places=2)

    def test_split_inside_slot_by_ratio(self):
        slots = [{"slot": "hs300", "w": 1.0, "mv": 0.0,
                  "items": [{"code": "110020", "x": .7}, {"code": "000051", "x": .3}]}]
        out = {o["code"]: o["amount"] for o in HG.plan_invest(slots, 10000)}
        self.assertAlmostEqual(out["110020"], 7000, places=2)
        self.assertAlmostEqual(out["000051"], 3000, places=2)

    def test_bad_input_returns_empty(self):
        self.assertEqual(HG.plan_invest([], 5000), [])
        self.assertEqual(HG.plan_invest([self._slot("a", 1, 0)], 0), [])

    def test_zero_weights_split_evenly(self):
        slots = [self._slot("a", 0, 0), self._slot("b", 0, 0)]
        out = {o["slot"]: o["amount"] for o in HG.plan_invest(slots, 1000)}
        self.assertAlmostEqual(out["a"], 500, places=2)
        self.assertAlmostEqual(out["b"], 500, places=2)


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

    def test_valuation_lists_every_fund_in_one_slot(self):
        """一个位置挂两只 → 估值提醒要各出一条，不能只报第一只。"""
        h = make_holdings()
        h["hs300"] = {"on": True, "funds": [_fund("110020"), _fund("000961")]}
        val = {"110020": {"score": 5}, "000961": {"score": 20}}
        out = AL.compute({"hs300": 100.}, {"hs300": 1.0}, h, self.label, val)
        self.assertEqual({x["code"] for x in out["估值"]}, {"110020", "000961"})

    def test_unrealized_loss_uses_each_fund_nav(self):
        """位置市值 ÷ 份额 在挂多只时会算错净值，必须按代码各自的净值判断浮亏。"""
        h = make_holdings()
        h["hs300"] = {"on": True, "funds": [_fund("110020"), _fund("000961")]}
        out = AL.compute({"hs300": 200.}, {"hs300": 1.0}, h, self.label, {},
                         pos={"110020": 100., "000961": 100.},
                         cost={"110020": 1.0, "000961": 1.0},
                         slot_of_code=lambda c: HG.slot_of(c, h),
                         nav_by_code={"110020": 0.5, "000961": 1.5})
        self.assertTrue(any("110020" in x["text"] and "浮亏" in x["text"] for x in out["体检"]))
        self.assertFalse(any("000961" in x["text"] for x in out["体检"]))


if __name__ == "__main__":
    unittest.main()
