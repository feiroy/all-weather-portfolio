"""「更新数据」一直转圈（2026-11-15）：akshare 的请求不带 timeout，对方不回包就永久阻塞。

fetch 模块给没设超时的请求兜一个默认超时；同一台服务器超时一次后冷却期内直接判失败。
用本机一个「接受连接但永远不回包」的假服务器复现，不联网。
"""
import socket
import time

import pytest
import requests

from allweather import fetch as FT


@pytest.fixture()
def silent_server():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(8)                      # 只 listen 不 accept、不回包：连接能建立，读一直等
    yield f"http://127.0.0.1:{s.getsockname()[1]}/x"
    s.close()


def test_request_without_timeout_no_longer_hangs(silent_server, monkeypatch):
    monkeypatch.setattr(FT, "DEFAULT_HTTP_TIMEOUT", (1, 1))
    monkeypatch.setattr(FT, "_DEAD_HOSTS", {})
    t = time.time()
    with pytest.raises(requests.exceptions.Timeout):
        requests.get(silent_server)                       # 没传 timeout：原来会永远挂着
    assert time.time() - t < 5


def test_timed_out_host_is_skipped_during_cooldown(silent_server, monkeypatch):
    monkeypatch.setattr(FT, "DEFAULT_HTTP_TIMEOUT", (1, 1))
    monkeypatch.setattr(FT, "_DEAD_HOSTS", {})
    with pytest.raises(requests.exceptions.Timeout):
        requests.get(silent_server)
    t = time.time()
    with pytest.raises(requests.exceptions.ConnectTimeout, match="先跳过"):
        requests.get(silent_server)                       # 冷却期内：不再等，立刻失败
    assert time.time() - t < 0.5


def test_explicit_timeout_is_respected(silent_server, monkeypatch):
    monkeypatch.setattr(FT, "DEFAULT_HTTP_TIMEOUT", (30, 30))
    monkeypatch.setattr(FT, "_DEAD_HOSTS", {})
    t = time.time()
    with pytest.raises(requests.exceptions.Timeout):
        requests.get(silent_server, timeout=0.5)          # 调用方自己给了超时就用它的
    assert time.time() - t < 3


def test_history_only_proxies_not_refetched(tmp_path, monkeypatch):
    """国债总指数 / 中债收益率曲线只拼 ETF 上市前的历史：本地覆盖到拼接日就不再请求中债网。"""
    monkeypatch.setattr(FT, "DATA_DIR", tmp_path)
    (tmp_path / "bond_10y_etf.csv").write_text("date,close\n2017-08-04,1.0\n2026-11-13,1.4\n")
    (tmp_path / "bond_30y_etf.csv").write_text("date,close\n2024-03-20,1.0\n2026-11-13,1.1\n")
    (tmp_path / "treasury_idx.csv").write_text("date,close\n2008-01-02,100\n2026-11-10,214\n")
    (tmp_path / "cgb_yields.csv").write_text("曲线名称,日期,30年\nx,2006-03-01,3.5\nx,2026-11-10,2.0\n")
    assert FT._history_covered(tmp_path / "treasury_idx.csv", "bond_10y_etf")
    assert FT._history_covered(tmp_path / "cgb_yields.csv", "bond_30y_etf", date_col=1)
    # 本地只到 ETF 上市前 → 还缺拼接日，要去拉
    (tmp_path / "treasury_idx.csv").write_text("date,close\n2008-01-02,100\n2016-12-30,150\n")
    assert not FT._history_covered(tmp_path / "treasury_idx.csv", "bond_10y_etf")
    assert not FT._history_covered(tmp_path / "missing.csv", "bond_10y_etf")


def test_real_data_skips_chinabond():
    """用仓库里真实的数据文件：两项都已覆盖拼接日。"""
    assert FT._history_covered(FT.DATA_DIR / "treasury_idx.csv", "bond_10y_etf")
    assert FT._history_covered(FT.DATA_DIR / "cgb_yields.csv", "bond_30y_etf", date_col=1)
