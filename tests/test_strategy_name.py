"""策略名长度（2026-11-14 用户：「V3-B 风险平价 - 替换城投」再多打一个字就打不进去）。

编辑器 maxlength、策略库截断、回测曲线名三处必须同一个上限；超过 16 字的名字回测页要能按名字取到曲线。
"""
from pathlib import Path

import pytest

from allweather import strategies as ST
from allweather.custom_backtest import custom_compare

LONG = "V3-B 风险平价 - 替换城投债对照组"      # 20 个字符


def test_norm_keeps_long_name():
    rec = ST.norm({"name": LONG, "funds": [{"key": "hs300", "weight": 50}, {"key": "credit", "weight": 50}]})
    assert rec["name"] == LONG
    assert len(ST.norm({"name": "字" * 40, "funds": [{"key": "hs300", "weight": 1}]})["name"]) == ST.NAME_MAX


def test_builtin_name_rejected():
    with pytest.raises(ValueError, match="内置策略的名字"):
        ST.norm({"name": "V3-B 风险平价", "funds": [{"key": "hs300", "weight": 1}]})


def test_compare_curve_named_by_full_name():
    d = custom_compare(start="2024-01-01", name=LONG, method="fixed",
                       funds=[{"key": "hs300", "weight": 50}, {"key": "credit", "weight": 50}])
    assert d["label"] == LONG and LONG in d["curves"]
    assert any(r["name"] == LONG for r in d["rows"])


def test_editor_maxlength_matches_backend():
    vue = Path(__file__).resolve().parent.parent / "web/src/views/StrategyNew.vue"
    assert f'maxlength="{ST.NAME_MAX}"' in vue.read_text(encoding="utf-8")
