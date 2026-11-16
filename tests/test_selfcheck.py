"""自检本身要对：口径不自洽时必须报红，别自己先瞎了。

这几条约束是「页面上的数看着不对」的公共根因，`scripts/doctor.py` 和 `/api/selftest`
都靠它们。如果自检漏报，排查就又回到靠猜。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "streamlit_app"))

from allweather import selfcheck as SC  # noqa: E402


class FakeP:
    """够 value_checks / cache_checks 用的最小 Portfolio。"""

    def __init__(self, total=1000.0, equity=1000.0, today=-5.0, by_day=-5.0, mv=None):
        self.plan = {"total": total, "today": today}
        self.daily = pd.DataFrame({"equity": [1000.0, equity]},
                                  index=pd.to_datetime(["2026-11-13", "2026-11-16"]))
        self.last = self.daily.index[-1]
        self.by_day = {self.last: {"511130": (by_day, -0.5)}}
        self._mv = mv if mv is not None else 1000.0
        self.spot = {"511130": {"price": 100.0}}
        self.used_spot = True

    def items(self):
        return [{"code": "511130", "shares": 10.0, "px": 100.0, "mv": self._mv}]


def _by_id(checks, cid):
    return next(c for c in checks if c["id"] == cid)


def test_consistent_account_is_all_green():
    checks = SC.value_checks(FakeP())
    assert all(c["level"] == "ok" for c in checks)
    assert SC.cache_checks(FakeP())[0]["level"] == "ok"


def test_total_mismatch_is_red():
    """plan.total 是市价、equity 末端是净值时，差的就是折溢价 —— 必须报红。"""
    c = _by_id(SC.value_checks(FakeP(total=998.0, equity=1000.0)), "value.total")
    assert c["level"] == "bad"


def test_today_mismatch_is_red():
    c = _by_id(SC.value_checks(FakeP(today=-5.0, by_day=-37.0)), "value.today")
    assert c["level"] == "bad"


def test_market_value_must_equal_shares_times_price():
    c = _by_id(SC.value_checks(FakeP(mv=1500.0)), "value.mv")
    assert c["level"] == "bad"


def test_nav_based_valuation_is_flagged_yellow():
    P = FakeP()
    P.used_spot = False
    assert SC.cache_checks(P)[0]["level"] == "warn"


def test_stale_nav_is_red_and_names_the_code(monkeypatch):
    from allweather import holdings as HG
    monkeypatch.setattr(HG, "nav_freshness", lambda c: ("2026-10-29", True))
    monkeypatch.setattr(HG, "all_codes", lambda h: ["000217"])
    checks = SC.nav_checks({"trades": [], "holdings": {}})
    hit = _by_id(checks, "nav.000217")
    assert hit["level"] == "bad"
    assert "2026/10/29" in hit["title"] or "2026-10-29" in hit["title"]


def test_account_error_still_runs_nav_checks(monkeypatch):
    """账户算不出来时，净值那几条必须照跑 —— 否则「为什么 400」这条线索就丢了。"""
    from allweather import holdings as HG
    monkeypatch.setattr(HG, "nav_freshness", lambda c: ("2026-10-29", True))
    monkeypatch.setattr(HG, "all_codes", lambda h: ["000217"])
    rep = SC.run(None, {"trades": [], "holdings": {}}, error="策略算不出今天的权重")
    ids = {c["id"] for c in rep["checks"]}
    assert "nav.000217" in ids and "acct" in ids
    assert rep["ok"] is False
