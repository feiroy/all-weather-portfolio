"""多账户存储：一个账户一个文件，交易记录和选基配置一起跟着账户走。

    data/accounts/
      index.json          {"order": ["main", "sim-3fa9c1"], "last": "main"}
      main.json           {"name", "kind", "strategy", "capital", "created", "trades", "holdings", "updated"}
      sim-3fa9c1.json
      .trash/             删掉的账户先挪到这里，可恢复

为什么选基配置也放进账户：调仓清单就是按它把目标权重落到具体基金上的。全站一份的话，
在模拟账户里关掉 10Y、换一只联接基金，实盘账户的清单也跟着变。

文件名用随机短 id，改名不动文件；写入走「先写临时文件再替换」，写一半断电不会留下半个 JSON。
第一次运行（没有 index.json）时，把旧的 data/sim_account.json + data/holdings.json 合成 main.json。
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

import pandas as pd

from .config import DATA_DIR

ACCOUNTS_DIR = DATA_DIR / "accounts"
TRASH_DIR = ACCOUNTS_DIR / ".trash"
INDEX_FILE = ACCOUNTS_DIR / "index.json"
LEGACY_ACCOUNT = DATA_DIR / "sim_account.json"
KINDS = ("实盘", "模拟")
_FIELDS = ("name", "kind", "strategy", "capital", "created", "trades", "holdings")


def _now() -> str:
    return pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")


def _write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def path_of(aid: str) -> Path:
    return ACCOUNTS_DIR / f"{aid}.json"


def _index() -> dict:
    d = _read(INDEX_FILE) or {}
    order = [a for a in d.get("order", []) if path_of(a).exists()]
    # 目录里有、索引里没有的（比如另一台机器 git pull 进来的）补到末尾
    for f in sorted(ACCOUNTS_DIR.glob("*.json")):
        if f.name != INDEX_FILE.name and f.stem not in order:
            order.append(f.stem)
    last = d.get("last") if d.get("last") in order else (order[0] if order else None)
    return {"order": order, "last": last}


def _save_index(ix: dict) -> None:
    _write(INDEX_FILE, {"order": ix["order"], "last": ix.get("last")})


def ensure(legacy_holdings: dict | None = None) -> None:
    """没有 index.json 就初始化；旧的 sim_account.json 在就迁成 main（只做一次，旧文件不删）。

    legacy_holdings：旧的全站选基配置（holdings.load()["holdings"]），由调用方传进来，
    免得这里反向依赖 holdings 模块。
    """
    if INDEX_FILE.exists():
        return
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    order = []
    old = _read(LEGACY_ACCOUNT) if LEGACY_ACCOUNT.exists() else None
    if old and not path_of("main").exists():
        body = {"name": "我的账户", "kind": "实盘",
                "strategy": old.get("strategy") or "B-Con",
                "capital": float(old.get("capital") or 0), "created": old.get("created"),
                "trades": list(old.get("trades") or []),
                "holdings": legacy_holdings or {}, "updated": _now()}
        _write(path_of("main"), body)
    if path_of("main").exists():
        order.append("main")
    _save_index({"order": order, "last": order[0] if order else None})


def list_accounts() -> list[dict]:
    """[{id, name, kind, strategy, created, n_trades}]，按 index 里的顺序。"""
    out = []
    for aid in _index()["order"]:
        a = _read(path_of(aid))
        if not a:
            continue
        out.append({"id": aid, "name": a.get("name") or aid, "kind": a.get("kind") or "实盘",
                    "strategy": a.get("strategy") or "B-Con", "created": a.get("created"),
                    "n_trades": len(a.get("trades") or [])})
    return out


def last() -> str | None:
    return _index()["last"]


def set_last(aid: str) -> None:
    ix = _index()
    if aid in ix["order"] and ix.get("last") != aid:
        ix["last"] = aid
        _save_index(ix)


def load(aid: str | None) -> dict | None:
    if not aid:
        return None
    a = _read(path_of(aid))
    if a is None:
        return None
    a.setdefault("trades", [])
    a.setdefault("holdings", {})
    return a


def save(aid: str, acct: dict) -> None:
    body = {k: acct.get(k) for k in _FIELDS}
    body.update({k: v for k, v in acct.items() if k not in body})   # 不认识的字段原样保留
    body["updated"] = _now()
    _write(path_of(aid), body)


def create(name: str, kind: str, strategy: str, capital: float, created: str,
           holdings: dict, trades: list | None = None) -> str:
    """新建账户，返回 id。名字只用来显示，可以重名（文件名是随机 id）。"""
    if kind not in KINDS:
        raise ValueError(f"账户类型只能是 {KINDS}")
    aid = ("sim-" if kind == "模拟" else "acct-") + secrets.token_hex(3)
    while path_of(aid).exists():
        aid = ("sim-" if kind == "模拟" else "acct-") + secrets.token_hex(3)
    save(aid, {"name": (name or "").strip() or "新账户", "kind": kind, "strategy": strategy,
               "capital": float(capital or 0), "created": str(created),
               "trades": list(trades or []), "holdings": holdings or {}})
    ix = _index()
    if aid not in ix["order"]:
        ix["order"].append(aid)
    ix["last"] = aid
    _save_index(ix)
    return aid


def update(aid: str, **fields) -> None:
    """改名、改类型等：只动给出的字段。"""
    a = load(aid)
    if a is None:
        raise KeyError(aid)
    if "kind" in fields and fields["kind"] not in KINDS:
        raise ValueError(f"账户类型只能是 {KINDS}")
    a.update(fields)
    save(aid, a)


def delete(aid: str) -> str:
    """挪进回收站，返回回收站里的文件名。最后一个账户不能删。"""
    ix = _index()
    if aid not in ix["order"]:
        raise KeyError(aid)
    if len(ix["order"]) <= 1:
        raise ValueError("最后一个账户不能删：至少得留一个")
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    dst = TRASH_DIR / f"{aid}__{pd.Timestamp.now():%Y%m%d-%H%M%S}.json"
    os.replace(path_of(aid), dst)
    ix["order"].remove(aid)
    if ix.get("last") == aid:
        ix["last"] = ix["order"][0]
    _save_index(ix)
    return dst.name


def trash() -> list[dict]:
    """回收站：[{file, id, name, kind, deleted}]，最近删的在前。"""
    out = []
    for f in sorted(TRASH_DIR.glob("*.json"), reverse=True) if TRASH_DIR.exists() else []:
        a = _read(f) or {}
        aid, _, ts = f.stem.partition("__")
        out.append({"file": f.name, "id": aid, "name": a.get("name") or aid, "kind": a.get("kind") or "",
                    "deleted": pd.to_datetime(ts, format="%Y%m%d-%H%M%S", errors="coerce")})
    return out


def restore(file: str) -> str:
    """从回收站恢复，返回账户 id（id 被占了就换一个新 id）。"""
    src = TRASH_DIR / file
    if not src.exists():
        raise FileNotFoundError(file)
    aid = src.stem.partition("__")[0]
    if path_of(aid).exists():
        aid = aid.split("-")[0] + "-" + secrets.token_hex(3)
    os.replace(src, path_of(aid))
    ix = _index()
    if aid not in ix["order"]:
        ix["order"].append(aid)
    _save_index(ix)
    return aid


def purge(file: str) -> None:
    """彻底删除回收站里的一个账户。"""
    p = TRASH_DIR / file
    if p.exists() and p.parent == TRASH_DIR:
        p.unlink()
