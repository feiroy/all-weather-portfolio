"""自定义策略库：H5「策略工厂」保存下来的模板，实盘也要按它下单。

    data/strategies.json
      {"strategies": [ {...}, {...} ], "updated": "2026-11-11 21:00"}

为什么从浏览器搬到服务端（2026-11-11 用户要求「保存为模板，按我自己的策略买卖」）
--------------------------------------------------------------------------------
原来策略只存在浏览器 localStorage（`aw-strategies`）：服务端读不到，就没法拿它算实盘目标权重；
顺带还有两个毛病 —— 换设备/换浏览器就没了，多端之间也不一致。现在它和账户文件一样落在 data/，
跟着 git 走。前端保留 localStorage 只做一次性迁移来源（见 `web/src/strategyStore.js`）。

一条策略的结构（与 StrategyNew.vue 保存的字段一一对应）

    id, name, freq, method, window, max_w, cash_ratio, target_vol,
    trend_map:  {资产key: 均线窗口}
    rp_buckets: {桶名: [资产key]}      仅 risk_parity
    safe_asset: 趋势过滤的避风港
    funds:      [{key, code, name, weight}]   key 已归一成资产 key 或 6 位代码

注意：这里只做「存 + 校验 + 归一化 key」，不复制任何回测/加权逻辑 —— 算权重仍然只走
allweather/custom_backtest.py（`build_engine_kwargs` + `custom_series`），和回测页是同一份代码。
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

import pandas as pd

from .config import DATA_DIR

PATH = DATA_DIR / "strategies.json"

METHODS = ("fixed", "inverse_vol", "risk_parity")
FREQ_FIXED = ("M", "Q", "N")
FREQ_DYNAMIC = ("M", "B", "W")

_DEFAULTS = {"method": "fixed", "freq": "M", "window": 20, "max_w": 0.25, "min_w": 0.02,
             "cash_ratio": 0.0, "target_vol": None, "safe_asset": "credit"}


def _now() -> str:
    return pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")


def _write(obj: dict) -> None:
    """先写临时文件再替换：写一半断电不会留下半个 JSON（与 accounts.py 同一套）。"""
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, PATH)


def load() -> list[dict]:
    """全部策略（按文件里的顺序）。文件不存在或坏了就当空库，不让页面因此打不开。"""
    try:
        d = json.loads(Path(PATH).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    rows = d.get("strategies") if isinstance(d, dict) else d
    return [r for r in (rows or []) if isinstance(r, dict) and r.get("id")]


def save_all(rows: list[dict]) -> list[dict]:
    _write({"strategies": list(rows), "updated": _now()})
    return rows


def get(sid: str) -> dict | None:
    return next((r for r in load() if r.get("id") == sid), None)


def canonicalize(rec: dict) -> dict:
    """把 6 位代码形式的 key 归一成资产 key（511220 → credit），再按当前持仓去重。

    必须和回测页走同一套 `custom_backtest.canonical_key`：否则用户用代码保存的策略，
    实盘按 key 找不到位置，权重会被摊到别的位置上，买出来完全不是他要的。
    """
    from .custom_backtest import canonical_key
    from .data import load_panel
    try:
        panel = load_panel()
    except Exception:  # noqa: BLE001 — 数据没就绪时先存原样，下次保存再归
        return rec
    seen, out = set(), []
    for f in rec.get("funds") or []:
        k = str(f.get("key") or f.get("code") or "").strip()
        if not k:
            continue
        k = canonical_key(k, panel)
        if k in seen:
            continue
        seen.add(k)
        out.append({**f, "key": k, "code": str(f.get("code") or k)})
    rec = dict(rec)
    rec["funds"] = out
    for fld in ("trend_map", "rp_buckets"):
        if fld == "trend_map" and isinstance(rec.get(fld), dict):
            rec[fld] = {canonical_key(k, panel): v for k, v in rec[fld].items()}
        elif fld == "rp_buckets" and isinstance(rec.get(fld), dict):
            rec[fld] = {b: [canonical_key(x, panel) for x in (v or [])] for b, v in rec[fld].items()}
    if rec.get("safe_asset"):
        rec["safe_asset"] = canonical_key(str(rec["safe_asset"]), panel)
    return rec


def norm(rec: dict) -> dict:
    """校验 + 补默认值。字段不对就抛 ValueError（页面直接把这句话显示给用户）。"""
    rec = dict(rec or {})
    name = str(rec.get("name") or "").strip()
    if not name:
        raise ValueError("策略得有个名字")
    rec["name"] = name[:16]
    method = str(rec.get("method") or "fixed").lower()
    if method not in METHODS:
        raise ValueError(f"未知加权方式 {method}（可选 fixed / inverse_vol / risk_parity）")
    rec["method"] = method
    freq = str(rec.get("freq") or "M").upper()
    rec["freq"] = freq if freq in (FREQ_FIXED if method == "fixed" else FREQ_DYNAMIC) else "M"
    for k in ("window", "max_w", "min_w", "cash_ratio"):
        rec[k] = rec.get(k) if rec.get(k) is not None else _DEFAULTS[k]
    rec["window"] = max(5, min(250, int(rec["window"] or 20)))
    rec["max_w"] = float(rec["max_w"] or 0.25)
    rec["min_w"] = float(rec["min_w"] if rec.get("min_w") is not None else 0.02)
    rec["cash_ratio"] = max(0.0, min(0.9, float(rec["cash_ratio"] or 0.0)))
    tv = rec.get("target_vol")
    rec["target_vol"] = None if not tv else max(0.01, min(0.6, float(tv)))
    rec["safe_asset"] = str(rec.get("safe_asset") or "credit")
    rec["trend_map"] = {str(k): int(v) for k, v in (rec.get("trend_map") or {}).items() if int(v or 0) > 0}
    rec["rp_buckets"] = rec.get("rp_buckets") or None
    funds = [f for f in (rec.get("funds") or []) if float(f.get("weight") or 0) > 0]
    if not funds:
        raise ValueError("至少给一只基金大于 0 的权重")
    rec["funds"] = [{**f, "weight": float(f["weight"])} for f in funds]
    return rec


def upsert(rec: dict) -> dict:
    """新增或覆盖一条策略，返回存下来的那条（带 id / created / updated）。"""
    rows = load()
    rec = norm(canonicalize(rec))
    sid = str(rec.get("id") or "").strip()
    old = next((r for r in rows if r.get("id") == sid), None) if sid else None
    if old is None:
        sid = sid or ("cs-" + secrets.token_hex(3))
        while any(r.get("id") == sid for r in rows):
            sid = "cs-" + secrets.token_hex(3)
        rec = {**rec, "id": sid, "created": (rec.get("created") or _now())}
        rows.append(rec)
    else:
        rec = {**rec, "id": sid, "created": old.get("created") or _now()}
        rows[rows.index(old)] = rec
    rec["updated"] = _now()
    save_all(rows)
    return rec


def delete(sid: str) -> None:
    rows = load()
    left = [r for r in rows if r.get("id") != sid]
    if len(left) == len(rows):
        raise KeyError(sid)
    save_all(left)


def fund_map(rec: dict) -> dict[str, dict]:
    """{资产key: {code, name}} —— 绑定实盘时用它给新基金建位置（HG.ensure_slots）。"""
    out = {}
    for f in rec.get("funds") or []:
        k = str(f.get("key") or "")
        if k:
            out[k] = {"code": str(f.get("code") or k), "name": str(f.get("name") or k)}
    return out
