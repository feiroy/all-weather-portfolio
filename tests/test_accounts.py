"""多账户存储：迁移、增删改、回收站。全部在临时目录里跑，不碰 data/。"""
import json

import pytest

from allweather import accounts as AC


@pytest.fixture()
def store(tmp_path, monkeypatch):
    d = tmp_path / "accounts"
    monkeypatch.setattr(AC, "ACCOUNTS_DIR", d)
    monkeypatch.setattr(AC, "TRASH_DIR", d / ".trash")
    monkeypatch.setattr(AC, "INDEX_FILE", d / "index.json")
    monkeypatch.setattr(AC, "LEGACY_ACCOUNT", tmp_path / "sim_account.json")
    return tmp_path


def test_migrate_legacy_into_main(store):
    (store / "sim_account.json").write_text(json.dumps(
        {"strategy": "B-Con", "capital": 100.0, "created": "2026-09-04",
         "trades": [{"date": "2026-09-04", "side": "买入", "code": "000961", "shares": 1, "nav": 1}]}),
        encoding="utf-8")
    AC.ensure(legacy_holdings={"hs300": {"on": True, "funds": [{"code": "000961"}]}})
    ls = AC.list_accounts()
    assert [a["id"] for a in ls] == ["main"]
    a = AC.load("main")
    assert a["name"] == "我的账户" and a["kind"] == "实盘" and a["capital"] == 100.0
    assert len(a["trades"]) == 1 and a["holdings"]["hs300"]["funds"][0]["code"] == "000961"
    # 只迁一次：再调 ensure 不会覆盖 main 里后来的改动
    AC.update("main", name="改过名")
    AC.ensure(legacy_holdings={})
    assert AC.load("main")["name"] == "改过名"


def test_ensure_without_legacy_starts_empty(store):
    AC.ensure()
    assert AC.list_accounts() == [] and AC.last() is None


def test_create_rename_and_last(store):
    AC.ensure()
    a1 = AC.create("实盘", "实盘", "B-Con", 1000, "2026-01-01", {})
    a2 = AC.create("试 V3c", "模拟", "V3c", 5e5, "2026-02-01", {"hs300": {"on": False, "funds": []}})
    assert a2.startswith("sim-") and a1.startswith("acct-")
    assert [a["id"] for a in AC.list_accounts()] == [a1, a2]
    assert AC.last() == a2                     # 新建的就是当前账户
    AC.update(a2, name="试试 V3c", kind="实盘")
    got = AC.load(a2)
    assert got["name"] == "试试 V3c" and got["kind"] == "实盘"
    assert AC.path_of(a2).exists()             # 改名不改文件名
    with pytest.raises(ValueError):
        AC.update(a2, kind="别的")


def test_accounts_are_independent(store):
    AC.ensure()
    a1 = AC.create("A", "实盘", "B-Con", 1, "2026-01-01", {"hs300": {"on": True, "funds": []}})
    a2 = AC.create("B", "模拟", "B-Con", 1, "2026-01-01", {"hs300": {"on": True, "funds": []}})
    x = AC.load(a2)
    x["holdings"]["hs300"]["on"] = False
    x["trades"].append({"date": "2026-01-02", "side": "买入"})
    AC.save(a2, x)
    assert AC.load(a1)["holdings"]["hs300"]["on"] is True
    assert AC.load(a1)["trades"] == []


def test_delete_to_trash_restore_purge(store):
    AC.ensure()
    a1 = AC.create("A", "实盘", "B-Con", 1, "2026-01-01", {})
    a2 = AC.create("B", "模拟", "B-Con", 1, "2026-01-01", {})
    f = AC.delete(a2)
    assert [a["id"] for a in AC.list_accounts()] == [a1]
    assert AC.last() == a1                     # 删的是当前账户 → 切回剩下的
    assert [t["file"] for t in AC.trash()] == [f] and AC.trash()[0]["name"] == "B"
    with pytest.raises(ValueError):
        AC.delete(a1)                          # 最后一个不能删
    rid = AC.restore(f)
    assert rid == a2 and AC.load(rid)["name"] == "B" and AC.trash() == []
    f2 = AC.delete(rid)
    AC.purge(f2)
    assert AC.trash() == [] and len(AC.list_accounts()) == 1


def test_index_picks_up_files_added_elsewhere(store):
    """另一台机器 git pull 进来一个新账户文件：索引里没有也要列出来。"""
    AC.ensure()
    a1 = AC.create("A", "实盘", "B-Con", 1, "2026-01-01", {})
    AC._write(AC.path_of("sim-abcdef"), {"name": "别处建的", "kind": "模拟", "trades": []})
    assert [a["id"] for a in AC.list_accounts()] == [a1, "sim-abcdef"]
