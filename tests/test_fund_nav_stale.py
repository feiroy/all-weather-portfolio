"""净值缓存「算不算落后」的判定。

这条规则直接决定「更新数据」有没有用。2026-11-16 用户点了十几次刷新，黄金的净值还是停在
三周前，就是因为旧规则只看 mtime：文件刚被写过一次（哪怕是坏的短文件），就当成新鲜的，
`ensure_fresh` 直接返回「本地已是最新」，一个网络请求都不发。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "streamlit_app"))
import fund_lookup as FL  # noqa: E402


@pytest.fixture()
def navdir(monkeypatch):
    # 不用 pytest 的 tmp_path：这个沙箱里 pytest-of-* 建目录会 FileExistsError
    import shutil, tempfile
    d = Path(tempfile.mkdtemp(prefix="awnav-"))
    monkeypatch.setattr(FL, "NAV_DIR", d)
    monkeypatch.setattr(FL, "expected_nav_date", lambda now=None: pd.Timestamp("2026-11-16"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _write(dirpath: Path, last: str) -> Path:
    idx = pd.bdate_range("2026-10-01", last)
    p = dirpath / "000217.csv"
    pd.DataFrame({"date": idx, "nav": 1.0, "chg": 0.0}).to_csv(p, index=False)
    return p


def test_long_gap_is_stale_even_if_file_just_written(navdir):
    """停在三周前的净值，哪怕文件是刚写的，也必须判落后 —— 否则永远补不上。"""
    _write(navdir, "2026-10-29")          # mtime 就是现在
    assert FL.is_stale("000217") is True


def test_one_day_gap_waits_an_hour(navdir):
    """今天净值还没出属正常，刚拉过就别再打接口。"""
    _write(navdir, "2026-11-13")
    assert FL.is_stale("000217") is False

    import os, time
    p = navdir / "000217.csv"
    old = time.time() - 3700              # 把 mtime 挪到 1 小时前
    os.utime(p, (old, old))
    assert FL.is_stale("000217") is True


def test_up_to_date_is_never_stale(navdir):
    _write(navdir, "2026-11-16")
    assert FL.is_stale("000217") is False


def test_missing_file_is_stale(navdir):
    assert FL.is_stale("999999") is True
