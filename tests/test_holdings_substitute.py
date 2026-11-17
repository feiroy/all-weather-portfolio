"""内置策略的权重必须按「我实际持有的基金」算（2026-11-16 用户要求）。

原来三个内置策略一律用项目默认的 8 只 ETF 序列算权重，用户换成场外联接
（006131 / 161119 / 000217 / 007467）去买，波动率和均线都不一样，分到的钱自然对不上。
这里锁住四件事：
  1. 换了基金 → 面板对应列在该基金有数据之后，用的就是它的收益；
  2. 挂的就是项目默认那只 → 不替换（结果和以前逐位一致）；
  3. 净值太短 / 停在几天前 → 不替换，并给出**人话原因**（不能静默用它算）；
  4. 一个位置挂多只 → 按位置内占比加权合成。
"""
import numpy as np
import pandas as pd
import pytest

from allweather import holdings as HG
from allweather.config import ETF_META

IDX = pd.bdate_range("2024-01-01", periods=400)


def _panel(cols, seed=0):
    """造一份收益面板：列 = 资产 key，值 = 日收益。"""
    rng = np.random.default_rng(seed)
    return pd.DataFrame({c: rng.normal(0.0004, v, len(IDX))
                         for c, v in cols.items()}, index=IDX)


def _nav(ret, start="2024-01-01"):
    """日收益 → 净值序列（起点可晚于面板，模拟新基金）。"""
    r = ret.dropna()
    return (1 + r).cumprod() * 100.0


def _slot(*funds):
    n = len(funds)
    return {"on": True, "funds": [{"code": c, "name": c, "share": 1.0 / n} for c in funds]}


@pytest.fixture
def fake_nav(monkeypatch):
    """把 nav_series 换成「我给的序列」，不联网、不读本地缓存。"""
    book: dict[str, pd.Series] = {}

    def _get(code, ensure=False):
        return book.get(code, pd.Series(dtype=float))

    monkeypatch.setattr(HG, "nav_series", _get)
    return book


def test_换成联接基金后_面板那一列改用它的收益(fake_nav):
    rets = _panel({"hs300": 0.012, "credit": 0.001})
    # 我的沪深300 联接从 2024-03 才成立，之后走势和面板完全不同（每天固定 +0.5%）
    mine = _nav(pd.Series(0.005, index=IDX[40:]))
    fake_nav["006131"] = mine
    out, info = HG.substitute_returns(rets, {"hs300": _slot("006131")})

    assert [u["slot"] for u in info["used"]] == ["hs300"]
    assert info["used"][0]["codes"] == ["006131"]
    # since = 这只基金第一个「有日收益」的日子（净值首日算不出收益，往后一天）
    assert info["used"][0]["since"] == f"{IDX[41]:%Y-%m-%d}"
    # 起点之前仍是项目默认标的，起点之后必须是 0.5%（联接基金自己的收益）
    assert out["hs300"].iloc[:41].equals(rets["hs300"].iloc[:41])
    assert out["hs300"].iloc[41:].round(9).eq(0.005).all()
    # 没换的位置一动不动
    assert out["credit"].equals(rets["credit"])


def test_挂的就是项目默认标的不替换_结果与以前一致(fake_nav):
    rets = _panel({"hs300": 0.012})
    out, info = HG.substitute_returns(rets, {"hs300": _slot(ETF_META["hs300"]["code"])})
    assert info["used"] == [] and info["skipped"] == []      # kind=default 不算问题，不报
    assert out.equals(rets)


def test_净值太短不替换_并说明原因(fake_nav):
    rets = _panel({"hs300": 0.012})
    fake_nav["006131"] = (1 + pd.Series(0.001, index=IDX[-40:])).cumprod() * 100
    out, info = HG.substitute_returns(rets, {"hs300": _slot("006131")})
    assert out.equals(rets)
    assert info["skipped"] and "交易日净值" in info["skipped"][0]["why"]
    assert info["skipped"][0]["slot"] == "hs300"


def test_净值停在几天前不替换(fake_nav):
    rets = _panel({"hs300": 0.012})
    fake_nav["006131"] = (1 + pd.Series(0.001, index=IDX[:-20])).cumprod() * 100
    out, info = HG.substitute_returns(rets, {"hs300": _slot("006131")})
    assert out.equals(rets)
    assert "净值只到" in info["skipped"][0]["why"]


def test_一处多只按占比加权(fake_nav):
    rets = _panel({"hs300": 0.012})
    fake_nav["A00001"] = (1 + pd.Series(0.0, index=IDX[10:])).cumprod() * 100       # 不动
    fake_nav["A00002"] = (1 + pd.Series(0.01, index=IDX[10:])).cumprod() * 100      # 每天 +1%
    out, info = HG.substitute_returns(rets, {"hs300": _slot("A00001", "A00002")})
    assert info["used"][0]["codes"] == ["A00001", "A00002"]
    assert out["hs300"].iloc[15:].round(9).eq(0.005).all()      # (0 + 1%) / 2


# ---------------------------------------------------------------- 端到端：权重真的会变
def _long_panel(seed=7, n=600):
    """够长的价格面板（8 个资产），让均线 / 风险平价窗口都攒得满。"""
    idx = pd.bdate_range("2023-01-02", periods=n)
    rng = np.random.default_rng(seed)
    cols = {"hs300": 0.012, "us_sp500": 0.010, "credit": 0.0015, "bond_30y": 0.004,
            "gold": 0.009, "nonferr": 0.011, "ene": 0.013, "divlow": 0.010}
    return pd.DataFrame({c: (1 + rng.normal(0.0003, v, n)).cumprod() * 100
                         for c, v in cols.items()}, index=idx)


def test_低波动替代基金会被风险平价多分钱(fake_nav):
    """这条是用户那个问题的验收：换了基金，权重必须跟着基金算，不能还按 ETF 算。"""
    from allweather.pipeline import live_target_weights

    panel = _long_panel()
    w_def, _ = live_target_weights("B-RP", panel)
    # 我的沪深300 联接波动比 ETF 小得多（每天 ±0.04% 震荡、整体缓涨，站得住均线）
    i = np.arange(len(IDX))
    quiet = pd.Series(0.001 + 0.0004 * ((i % 2) * 2 - 1), index=IDX)
    fake_nav["006131"] = (1 + quiet).cumprod() * 100
    info: dict = {}
    w_mine, _ = live_target_weights("B-RP", panel, holdings={"hs300": _slot("006131")}, info=info)

    assert [u["slot"] for u in info["used"]] == ["hs300"]
    assert abs(float(w_def.sum()) - 1) < 1e-9 and abs(float(w_mine.sum()) - 1) < 1e-9
    assert float(w_mine.get("hs300", 0)) > float(w_def.get("hs300", 0)) + 1e-4


def test_不给持仓就还是项目默认口径():
    """老调用点（命令行 / 测试）不传 holdings，行为必须和以前逐位一致。"""
    from allweather.pipeline import live_target_weights

    panel = _long_panel()
    a, a0 = live_target_weights("B-Con", panel)
    b, b0 = live_target_weights("B-Con", panel, holdings=None, info={})
    assert a.equals(b) and a0.equals(b0)
