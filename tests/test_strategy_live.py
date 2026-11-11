"""自定义策略上实盘：动态位置 + 策略库读写。

用户要求（2026-11-11）：「我自己加的策略可以保存为模板，然后按照我自己的策略进行买卖」，
并明确要支持**第 10 只新基金**、策略存**服务端 data/strategies.json**。

这两条各有各的坑，这里锁住：
  · 位置原来写死 9 个 —— 新基金的权重会被摊到别的位置上，买出来完全不是用户要的；
  · 策略原来只存浏览器 —— 服务端读不到就算不出实盘权重，换设备还会丢。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from allweather import holdings as HG        # noqa: E402
from allweather import strategies as ST     # noqa: E402


def _fund(code: str, unit: str = "股") -> dict:
    return HG._fund({"code": code, "unit": unit, "lot": 100 if unit == "股" else 1})


def make_holdings(codes: dict[str, str] | None = None) -> dict:
    """只造给定的这几个位置（不用 _default_holdings：那会把 9 个内置位置全带上）。"""
    return {s: {"on": True, "funds": [_fund(c)]} for s, c in (codes or {}).items()}


class DynamicSlots(unittest.TestCase):
    """位置不再写死 9 个：自定义策略可以带第 10 只基金。"""

    def test_slots_of_keeps_builtin_order_then_custom(self):
        h = make_holdings({"hs300": "510300", "credit": "511220"})
        h["zzz"] = {"on": True, "label": "纳指", "funds": [_fund("513100")]}
        h["aaa"] = {"on": True, "label": "科技", "funds": [_fund("515000")]}
        s = HG.slots_of(h)
        self.assertEqual(s[:2], ["hs300", "credit"], "内置位置顺序固定，不跟着 dict 插入顺序漂")
        self.assertEqual(s[2:], ["zzz", "aaa"], "自定义位置按配置里的先后追加在后面")

    def test_slots_of_skips_builtin_not_configured(self):
        h = make_holdings({"hs300": "510300"})
        self.assertEqual(HG.slots_of(h), ["hs300"])

    def test_slot_label_falls_back_to_fund_name(self):
        h = make_holdings()
        h["159915"] = {"on": True, "label": "", "funds": [_fund("159915")],
                       }
        h["159915"]["funds"][0]["name"] = "创业板ETF"
        self.assertEqual(HG.slot_label(h, "159915"), "创业板ETF")
        self.assertEqual(HG.slot_label(h, "hs300"), "增长↑权益(A股)")

    def test_ensure_slots_creates_only_missing_and_keeps_edits(self):
        h = make_holdings({"hs300": "110020"})          # 用户在 hs300 换过基金
        out, added = HG.ensure_slots(h, {
            "hs300": {"code": "510300", "name": "沪深300ETF"},     # 已有位置 → 不动
            "credit": {"code": "511220", "name": "城投债ETF"},      # 内置但没配 → 新建
            "159915": {"code": "159915", "name": "创业板ETF"},      # 真·新基金 → 新建
        })
        self.assertEqual(added, ["credit", "159915"])
        self.assertEqual(HG.codes(out["hs300"]), ["110020"], "用户换过的基金不能被策略覆盖")
        self.assertEqual(HG.codes(out["159915"]), ["159915"])
        self.assertEqual(out["159915"]["label"], "创业板ETF")
        # 幂等：再调一次不重复建
        _, again = HG.ensure_slots(out, {"159915": {"code": "159915", "name": "创业板ETF"}})
        self.assertEqual(again, [])

    def test_new_fund_weight_lands_on_its_own_slot(self):
        """核心回归：有位置时不外溢，没位置时才摊到别的位置上。"""
        w = {"credit": 0.4, "hs300": 0.3, "159915": 0.3}
        before = make_holdings({"hs300": "510300", "credit": "511220"})
        smeared = HG.slot_weights(w, HG.ensure_slots(before, {})[0])
        self.assertNotIn("159915", smeared)
        self.assertAlmostEqual(sum(smeared.values()), 1.0)
        self.assertGreater(smeared["hs300"], 0.3, "没有位置时 30% 被摊到 hs300/credit 上（所以要建位置）")

        h, added = HG.ensure_slots(before, {"159915": {"code": "159915", "name": "创业板ETF"}})
        placed = HG.slot_weights(w, h)
        self.assertEqual(added, ["159915"])
        self.assertAlmostEqual(placed["159915"], 0.3, places=6)
        self.assertAlmostEqual(placed["hs300"], 0.3, places=6)
        self.assertAlmostEqual(placed["credit"], 0.4, places=6)


class StrategyStore(unittest.TestCase):
    """策略库：校验 + 归一化 + 落盘（路径指向临时文件，不碰真实 data/strategies.json）。"""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp()) / "strategies.json"
        self._old = ST.PATH
        ST.PATH = self.tmp

    def tearDown(self):
        ST.PATH = self._old

    def _rec(self, **kw):
        base = {"name": "六四组合", "method": "fixed", "freq": "M",
                "funds": [{"key": "credit", "code": "511220", "weight": 60},
                          {"key": "hs300", "code": "510300", "weight": 40}]}
        base.update(kw)
        return base

    def test_norm_rejects_bad_input(self):
        with self.assertRaisesRegex(ValueError, "名字"):
            ST.norm({"name": "  ", "funds": self._rec()["funds"]})
        with self.assertRaisesRegex(ValueError, "至少给一只基金"):
            ST.norm({"name": "空", "funds": [{"key": "hs300", "weight": 0}]})
        with self.assertRaisesRegex(ValueError, "未知加权方式"):
            ST.norm(self._rec(method="magic"))

    def test_norm_clamps_and_defaults(self):
        r = ST.norm(self._rec(window=9999, cash_ratio=5, freq="X"))
        self.assertEqual(r["window"], 250)
        self.assertEqual(r["cash_ratio"], 0.9)
        self.assertEqual(r["freq"], "M", "非法频率回落到每月")
        self.assertEqual(r["safe_asset"], "credit")

    def test_upsert_assigns_id_and_preserves_on_edit(self):
        a = ST.upsert(self._rec())
        self.assertTrue(a["id"].startswith("cs-"))
        self.assertEqual(a["created"], a["updated"])
        b = ST.upsert(self._rec(id=a["id"], name="改了名"))
        self.assertEqual(b["id"], a["id"])
        self.assertEqual(b["created"], a["created"])
        self.assertEqual([x["name"] for x in ST.load()], ["改了名"], "同 id 是覆盖，不是新增")

    def test_upsert_canonicalizes_code_keys(self):
        """511220 存进去要变成 credit，否则实盘按 key 找不到位置。"""
        r = ST.upsert(self._rec(funds=[{"key": "511220", "code": "511220", "weight": 70},
                                       {"key": "159915", "code": "159915", "weight": 30}]))
        self.assertEqual([f["key"] for f in r["funds"]], ["credit", "159915"])

    def test_fund_map_for_ensure_slots(self):
        r = ST.upsert(self._rec(funds=[{"key": "159915", "code": "159915",
                                        "name": "创业板ETF", "weight": 100}]))
        self.assertEqual(ST.fund_map(r), {"159915": {"code": "159915", "name": "创业板ETF"}})

    def test_delete(self):
        a = ST.upsert(self._rec())
        ST.delete(a["id"])
        self.assertEqual(ST.load(), [])
        with self.assertRaises(KeyError):
            ST.delete(a["id"])

    def test_load_tolerates_missing_or_broken_file(self):
        self.assertEqual(ST.load(), [])
        self.tmp.write_text("{ 坏掉的 json", encoding="utf-8")
        self.assertEqual(ST.load(), [], "文件坏了不能让页面打不开")

    def test_write_is_atomic(self):
        ST.upsert(self._rec())
        self.assertFalse(self.tmp.with_suffix(".json.tmp").exists(), "临时文件要 rename 掉")
        json.loads(self.tmp.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
