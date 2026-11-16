"""数据版本号：五组文件必须都算进去。

少一组就会出「文件更新了但页面不动」——2026-11-16 一天踩了两回：
场外净值目录没算进版本号，净值补上了、缓存不失效，研究页（直读文件）正常、详情页（读缓存）一条直线。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "streamlit_app"))

from allweather import dataversion as DV  # noqa: E402


@pytest.fixture()
def sandbox(monkeypatch):
    """造一个只含五组文件的小数据目录（不用 pytest 的 tmp_path：沙箱里会 FileExistsError）。"""
    import shutil, tempfile
    base = Path(tempfile.mkdtemp(prefix="awver-"))
    (base / "nav_detail").mkdir()
    (base / "valuation" / "history").mkdir(parents=True)
    navdir = base / "otc"
    navdir.mkdir()
    for p in (base / "hs300.csv", base / "nav_detail" / "gold.csv",
              base / "valuation" / "history" / "v.csv", navdir / "000217.csv"):
        p.write_text("date,close\n2026-01-01,1\n", encoding="utf-8")
    (base / "strategies.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(DV, "DATA_DIR", base)
    stub = SimpleNamespace(NAV_DIR=navdir)
    monkeypatch.setitem(sys.modules, "fund_lookup", stub)
    yield base, navdir
    shutil.rmtree(base, ignore_errors=True)


def test_all_five_groups_are_collected(sandbox):
    groups = DV.data_files()
    assert set(groups) == {"行情", "场内净值", "场外净值", "估值", "策略库"}, "五组缺一不可"


@pytest.mark.parametrize("rel", [
    "hs300.csv",                       # 行情
    "nav_detail/gold.csv",             # 场内净值明细
    "otc/000217.csv",                  # 场外净值缓存
    "valuation/history/v.csv",         # 估值缓存
    "strategies.json",                 # 策略库
])
def test_touching_any_group_bumps_version(sandbox, rel):
    base, _ = sandbox
    before = DV.data_ver(fresh=True)
    target = base / rel
    future = time.time() + 60
    import os
    os.utime(target, (future, future))
    assert DV.data_ver(fresh=True) > before, f"{rel} 改了，版本号必须变，否则缓存不会失效"


def test_version_is_cached_for_a_second(sandbox):
    base, _ = sandbox
    v1 = DV.data_ver()
    assert DV.data_ver() == v1                  # 1 秒内命中缓存
    future = time.time() + 60
    import os
    os.utime(base / "hs300.csv", (future, future))
    assert DV.data_ver() == v1, "缓存期内不该重新扫描"
    assert DV.data_ver(fresh=True) > v1, "fresh=True 要立刻反映最新"
