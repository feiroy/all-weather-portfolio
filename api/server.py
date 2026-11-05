"""H5 前端的 JSON 接口 + 静态文件。

    scripts/run_h5.sh            # 构建前端 + 启动，http://127.0.0.1:8600

计算全在 allweather/（portfolio.py 与 Streamlit 版同口径），这里只做：读账户 → 算 → 转成 JSON、
写账户时的校验、触发数据更新。只用 Starlette（Streamlit 自带），不新增 Python 依赖。

缓存：目标权重按「行情文件修改时间」缓存，账户视图再加账户文件修改时间 —— 都没变时切页只读内存。
密码：设了环境变量 AW_PASSWORD_SHA256（密码的 sha256）才启用；登录后发一个 cookie，接口都要带。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "streamlit_app"))

from allweather import accounts as AC  # noqa: E402
from allweather import holdings as HG  # noqa: E402
from allweather.config import DATA_DIR, ETF_META, STRATEGY_PARAMS  # noqa: E402,F401
from allweather.portfolio import Portfolio, close_trade_idx  # noqa: E402
import fund_lookup as FL  # noqa: E402

DIST = ROOT / "web" / "dist"
KEYS = ["B-Con", "B-RP", "V3c"]
STRAT_NAME = {"B-Con": "V3-B 保守增强", "B-RP": "V3-B 风险平价", "V3c": "V3c 多元"}
BENCH_COL = {"B-RP": "V3-B 风险平价(20d)_100% RP", "B-Con": "V3-B 保守增强(20d)_100% RP", "V3c": "V3c 多元_100% RP"}
_W: dict = {}
_P: dict = {}
_LOCK = threading.Lock()


def J(obj, status=200):
    return JSONResponse(_clean(obj), status_code=status)


def _clean(o):
    """NaN / inf / numpy 类型 → JSON 能认的。"""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (pd.Timestamp,)):
        return f"{o:%Y-%m-%d}"
    return o


def _r(v, d=2):
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else round(float(v), d)


# ------------------------------------------------------------------ 数据与缓存
def _data_ver() -> float:
    fs = list(DATA_DIR.glob("*.csv")) + list((DATA_DIR / "nav_detail").glob("*.csv"))
    return max((f.stat().st_mtime for f in fs), default=0.0)


def _live() -> dict:
    """三个策略的目标权重（含趋势过滤）与原始权重 + 行情面板 —— 按数据版本缓存一份。"""
    ver = _data_ver()
    with _LOCK:
        if _W.get("ver") != ver:
            from allweather.data import load_panel
            from allweather.pipeline import live_target_weights
            panel = load_panel(end=pd.Timestamp.today().strftime("%Y-%m-%d"))
            ws = {k: live_target_weights(k, panel) for k in KEYS}
            _W.clear()
            _W.update({"ver": ver, "panel": panel, "w": {k: v[0] for k, v in ws.items()},
                       "w0": {k: v[1] for k, v in ws.items()}})
            _P.clear()
        return _W


def _portfolio(aid: str, target=None) -> tuple[Portfolio, dict]:
    path = AC.path_of(aid)
    if not path.exists():
        raise KeyError(aid)
    a = AC.load(aid)
    live = _live()
    stg = target or a.get("strategy") or "B-Con"
    key = (aid, path.stat().st_mtime, live["ver"], stg)
    with _LOCK:
        if key not in _P:
            for k in [k for k in _P if k[0] == aid and k[3] == stg]:
                del _P[k]
            _P[key] = Portfolio(a, live["w"].get(stg, live["w"]["B-Con"]))
        return _P[key], a


def _acct_info(aid: str, a: dict) -> dict:
    stg = a.get("strategy") or "B-Con"
    return {"id": aid, "name": a.get("name") or aid, "kind": a.get("kind") or "实盘",
            "strategy": stg, "strategy_name": STRAT_NAME.get(stg, stg), "created": a.get("created")}


def _hj(h: dict) -> dict:
    return {**h, **{k: _r(h[k]) for k in ("mv", "day", "day_pct", "hold", "hold_pct", "amount")},
            "shares": _r(h["shares"], 4), "qty": _r(h.get("qty"), 4), "px": _r(h["px"], 4), "cost": _r(h["cost"], 4),
            "w_now": _r(h["w_now"] * 100, 2), "w_tgt": None if h["w_tgt"] is None else _r(h["w_tgt"] * 100, 2)}


def acct_view(fn):
    """路由装饰：取账户、找不到回 404，异常回 500 + 原因（前端直接显示）。"""
    async def run(request: Request):
        aid = request.path_params["aid"]
        try:
            P, a = _portfolio(aid)
        except KeyError:
            return J({"error": "没有这个账户"}, 404)
        try:
            return await fn(request, aid, P, a)
        except ValueError as e:
            return J({"error": str(e)}, 400)
    return run


# ------------------------------------------------------------------ 账户列表 / 管理
async def accounts(request: Request):
    out = []
    for a in AC.list_accounts():
        try:
            P, raw = _portfolio(a["id"])
            s, m = P.summary(), P.month_curve()
            out.append({**_acct_info(a["id"], raw), "n_trades": a["n_trades"], "total": _r(s["total"]),
                        "pnl": _r(s["pnl"]), "pnl_pct": _r(s["pnl_pct"]), "spark": m["ret"]})
        except Exception as e:  # noqa: BLE001 —— 一个账户坏了不影响列表
            out.append({**a, "error": str(e)[:120]})
    tr = [{**t, "deleted": None if pd.isna(t["deleted"]) else f'{t["deleted"]:%Y-%m-%d}'} for t in AC.trash()]
    return J({"accounts": out, "trash": tr, "asof": f'{_live()["panel"].index[-1]:%Y-%m-%d}'})


async def create_account(request: Request):
    b = await request.json()
    src = AC.load(b.get("from")) if b.get("from") else None
    copy_tr = bool(b.get("copy_trades")) and src
    h = (src.get("holdings") if src and src.get("holdings") else HG._default_holdings())
    aid = AC.create(b.get("name") or "新账户", b.get("kind") or "模拟", b.get("strategy") or "B-Con",
                    float(src.get("capital") or 0) if copy_tr else float(b.get("capital") or 0),
                    str(src["created"]) if copy_tr else str(b.get("created") or pd.Timestamp.today().date()),
                    {k: HG._norm_slot(v) for k, v in h.items()},
                    trades=[dict(t) for t in src.get("trades", [])] if copy_tr else None)
    return J({"id": aid})


async def patch_account(request: Request):
    aid, b = request.path_params["aid"], await request.json()
    if "kind" in b:
        return J({"error": "实盘 / 模拟只在新建账户时选一次，建好以后不能改"}, 400)
    try:
        AC.update(aid, **{k: v for k, v in b.items() if k == "name"})
    except (KeyError, ValueError) as e:
        return J({"error": str(e)}, 400)
    return J({"ok": True})


async def delete_account(request: Request):
    try:
        return J({"trash": AC.delete(request.path_params["aid"])})
    except (KeyError, ValueError) as e:
        return J({"error": str(e)}, 400)


_TRASH_NAME = re.compile(r"^[A-Za-z0-9_-]+__\d{8}-\d{6}\.json$")   # 只认回收站自己起的文件名，挡掉 .. 之类


async def trash_restore(request: Request):
    f = request.path_params["file"]
    if not _TRASH_NAME.match(f):
        return J({"error": "回收站里没有这个文件"}, 400)
    try:
        return J({"id": AC.restore(f)})
    except FileNotFoundError:
        return J({"error": "回收站里没有这个文件"}, 404)


async def trash_purge(request: Request):
    f = request.path_params["file"]
    if not _TRASH_NAME.match(f):
        return J({"error": "回收站里没有这个文件"}, 400)
    AC.purge(f)
    return J({"ok": True})


# ------------------------------------------------------------------ 资产 / 基金 / 记一笔
@acct_view
async def home(request, aid, P, a):
    s = P.summary()
    return J({"account": _acct_info(aid, a), "summary": {k: (_r(v) if isinstance(v, float) else v) for k, v in s.items()},
              "status": {k: (_r(v) if isinstance(v, float) else v) for k, v in P.status().items()},
              "month": P.month_curve(), "holdings": [_hj(P.holding(it)) for it in P.items() if not it.get("dup")]})


@acct_view
async def holding(request, aid, P, a):
    code = request.path_params["code"]
    it = next((x for x in P.items() if x["code"] == code and not x.get("dup")), None)
    if it is None:
        return J({"error": "这只基金不在当前账户里"}, 404)
    nv = P.nav(code)
    return J({"account": _acct_info(aid, a), "holding": _hj(P.holding(it)),
              "nav": {"dates": [f"{d:%Y-%m-%d}" for d in nv.index], "values": [round(float(v), 4) for v in nv]},
              "trades": [{**t, "shares": _r(t["shares"], 4), "nav": _r(t["nav"], 4), "amount": _r(t["amount"])}
                         for t in P.trades_of(code)]})


@acct_view
async def record_options(request, aid, P, a):
    return J({"account": _acct_info(aid, a), "funds": P.slot_options(), "cash": _r(P.cash), "asof": f"{P.last:%Y-%m-%d}"})


@acct_view
async def nav_on(request, aid, P, a):
    code = request.path_params["code"]
    day = request.query_params.get("date") or pd.Timestamp.today().strftime("%Y-%m-%d")
    skip = request.query_params.get("skip")
    held = P.held_on(code, day) if skip is None else _held_skip(a, code, day, int(skip))
    return J({"code": code, "date": day, "nav": _r(P.nav_on(code, day), 4), "held": _r(held, 4)})


def _held_skip(a, code, day, skip):
    h = 0.0
    for i, t in enumerate(a.get("trades") or []):
        if i == skip or str(t.get("code") or "") != code or str(t.get("date") or "") > day:
            continue
        h += float(t.get("shares") or 0) * (1 if t.get("side") == "买入" else -1 if t.get("side") == "卖出" else 0)
    return h


def _trade_from_body(b: dict, a: dict, skip: int | None = None) -> dict:
    """记一笔 / 改一笔的校验，与 Streamlit 版同：金额、单价 > 0，卖出不超过当时持有。"""
    side, code, slot = b.get("side"), str(b.get("code") or ""), str(b.get("slot") or "")
    day = str(b.get("date") or "")[:10]
    amount, nav, fee = float(b.get("amount") or 0), float(b.get("nav") or 0), float(b.get("fee") or 0)
    if side in ("转入", "转出"):          # 资金进出：shares 记金额、nav 记 1（与 Streamlit 版台账同）
        if amount <= 0 or not day:
            raise ValueError("金额要大于 0，日期要填")
        return {"date": day, "side": side, "slot": "", "code": "", "shares": round(amount, 2), "nav": 1.0, "fee": 0.0}
    if side not in ("买入", "卖出") or not code or not day:
        raise ValueError("类型、基金、日期都要填")
    if amount <= 0:
        raise ValueError("金额要大于 0")
    if nav <= 0:
        raise ValueError("单价要大于 0 —— 换一天或手工填那天的成交净值")
    shares = (amount - fee) / nav if side == "买入" else (amount + fee) / nav
    if side == "卖出":
        held = _held_skip(a, code, day, -1 if skip is None else skip)
        if shares > held + 1e-6:
            raise ValueError(f"卖不了这么多：到 {day} 只持有 {held:,.2f}，这次要卖 {shares:,.2f}。"
                             "改小金额，或先补录这笔之前漏记的买入。")
    return {"date": day, "side": side, "slot": slot, "code": code, "shares": round(shares, 4), "nav": nav, "fee": fee}


@acct_view
async def add_trade(request, aid, P, a):
    t = _trade_from_body(await request.json(), a)
    a.setdefault("trades", []).append(t)
    AC.save(aid, a)
    return J({"ok": True, "shares": t["shares"]})


@acct_view
async def edit_trade(request, aid, P, a):
    i = int(request.path_params["i"])
    tr = a.setdefault("trades", [])
    if not 0 <= i < len(tr):
        return J({"error": "没有这一笔"}, 404)
    if request.method == "DELETE":
        tr.pop(i)
    else:
        tr[i] = {**tr[i], **_trade_from_body(await request.json(), a, skip=i)}
    AC.save(aid, a)
    return J({"ok": True})


@acct_view
async def trades(request, aid, P, a):
    raw = a.get("trades") or []
    closed = close_trade_idx(raw)
    rows = []
    for t in P.trades_of():
        u = "份" if HG.default_unit(t["code"]) == "份额" else "股" if t["code"] else ""
        f = next((x for x in P.slot_options() if x["code"] == t["code"]), None)
        rows.append({**t, "unit": (f["unit"] if f else u), "close": t["i"] in closed,
                     "shares": _r(t["shares"], 4), "nav": _r(t["nav"], 4), "amount": _r(t["amount"]), "fee": _r(t["fee"])})
    codes = []
    for r in rows:
        if r["code"] and r["code"] not in [c["code"] for c in codes]:
            codes.append({"code": r["code"], "name": r["name"]})
    return J({"account": _acct_info(aid, a), "rows": rows, "codes": codes,
              "cash": _r(P.plan["cash"]), "mv": _r(P.plan["mv_all"]), "total": _r(P.plan["total"])})


# ------------------------------------------------------------------ 调仓 / 新钱怎么分
def _calc_payload(P: Portfolio, a: dict) -> dict:
    p = P.plan
    act = [_hj(P.holding(it)) | {"slot_w": _r(it["slot_w"] * 100), "slot_tgt_w": _r(it["slot_tgt_w"] * 100)}
           for it in p["rows"] if it.get("side")]
    hold = [_hj(P.holding(it)) | {"slot_w": _r(it["slot_w"] * 100), "slot_tgt_w": _r(it["slot_tgt_w"] * 100),
                                  "slot_first": it["slot_first"]} for it in p["rows"] if not it.get("side")]
    slots = []
    for it in p["rows"]:
        if it["slot_first"]:
            slots.append({"slot": HG.SLOT_LABEL.get(it["slot"], it["slot"]), "now": _r(it["slot_w"] * 100),
                          "tgt": _r(it["slot_tgt_w"] * 100), "dev": _r(it["dev"] * 100)})
    st = P.status()
    return {"status": {k: (_r(v) if isinstance(v, float) else v) for k, v in st.items()},
            "orders": act, "hold": hold, "slots": slots, "asset": _r(p["asset"]), "cash": _r(p["cash"]),
            "buy": _r(p["buy"]), "sell": _r(p["sell"]),
            "other": [{"code": o["code"], "name": FL.fund_name(o["code"]) or o["code"], "mv": _r(o["mv"])} for o in p["other"]]}


@acct_view
async def calc(request, aid, P, a):
    return J({"account": _acct_info(aid, a), **_calc_payload(P, a)})


@acct_view
async def dca(request, aid, P, a):
    amt = float(request.query_params.get("amount") or 0)
    d = P.dca(amt)
    d["rows"] = [r | {k: _r(r[k]) for k in ("want", "amount")} | {"qty": _r(r["qty"], 4), "w_tgt": _r(r["w_tgt"] * 100),
                                                                     "x": _r(r["x"] * 100)} for r in d["rows"]]
    return J({"account": _acct_info(aid, a), **{k: (_r(v) if isinstance(v, float) else v) for k, v in d.items()}})


# ------------------------------------------------------------------ 收益 / 对比 / 体检
@acct_view
async def period(request, aid, P, a):
    return J({"account": _acct_info(aid, a), **P.period()})


@acct_view
async def compare(request, aid, P, a):
    from allweather import benchmark as BM
    stg = a.get("strategy") or "B-Con"
    curves = {}
    mine = P.daily["nav"].astype(float) if len(P.daily) else pd.Series(dtype=float)
    if len(mine) > 1:
        curves["我的账户"] = mine
    bd = P.bench_index(BM.replay_target(_live()["w"][stg], a.get("created"), nav_getter=HG.nav_series))
    if len(bd) > 1:
        curves["项目默认基金"] = bd
    bs = P.bench_index(BM.strategy_curve(BENCH_COL.get(stg, ""), start=a.get("created")))
    if len(bs) > 1:
        curves["策略理论"] = bs
    out = {}
    for k, s in curves.items():
        s = s.dropna()
        out[k] = {"dates": [f"{d:%Y-%m-%d}" for d in s.index], "ret": [round((float(v) / float(s.iloc[0]) - 1) * 100, 4) for v in s]}
    gap = {}
    for k in ("项目默认基金", "策略理论"):
        if k in curves and "我的账户" in curves:
            x, y = curves["我的账户"], curves[k]
            e = min(x.index[-1], y.index[-1])
            gap[k] = _r((float(x.loc[:e].iloc[-1] / x.iloc[0]) - float(y.loc[:e].iloc[-1] / y.iloc[0])) * 100)
    return J({"account": _acct_info(aid, a), "curves": out, "gap": gap,
              "mine": _r(out["我的账户"]["ret"][-1]) if "我的账户" in out else None})


@acct_view
async def health(request, aid, P, a):
    return J({"account": _acct_info(aid, a), **P.health()})


# ------------------------------------------------------------------ 选基配置 / 换策略
def _note(k: str, asset: str) -> str:
    live = _live()
    b, f = float(live["w0"][k].get(asset, 0) or 0), float(live["w"][k].get(asset, 0) or 0)
    if b > 0 and f <= 1e-9:
        return "趋势过滤 → 0"
    if f > b * 1.05 + 1e-4:
        return f"接收 +{(f - b) * 100:.1f}pp"
    return ""


@acct_view
async def weights(request, aid, P, a):
    from allweather.rebalance import STRATEGIES
    live = _live()
    act = set(HG.active(P.holdings))
    assets = [x for x in ETF_META if any(x in STRATEGIES[k]["assets"] for k in KEYS)]
    rows = [{"asset": x, "name": ETF_META[x]["name"], "code": ETF_META[x]["code"],
             "mine": HG.SLOT_LABEL.get(x, "") if x in act else "",
             "w": {k: (None if x not in STRATEGIES[k]["assets"] else _r(float(live["w"][k].get(x, 0)) * 100))
                   for k in KEYS},
             "note": {k: _note(k, x) for k in KEYS}} for x in assets]
    slots = []
    for s in HG.SLOTS:
        h = P.holdings.get(s, {})
        slots.append({"slot": s, "label": HG.SLOT_LABEL[s], "on": bool(h.get("on", True)),
                      "funds": [{"code": f["code"], "name": f.get("name") or FL.fund_name(f["code"]) or f["code"],
                                 "unit": f.get("unit"), "share": _r(f.get("share") or 0, 4)} for f in HG.funds(h)]})
    return J({"account": _acct_info(aid, a), "strategies": [{"key": k, "name": STRAT_NAME[k]} for k in KEYS],
              "rows": rows, "slots": slots})


@acct_view
async def switch_preview(request, aid, P, a):
    to = request.query_params.get("to")
    if to not in KEYS:
        return J({"error": "没有这个策略"}, 400)
    Q, _ = _portfolio(aid, target=to)
    from allweather.rebalance import STRATEGIES
    liq = [o for o in Q.plan["orders"] if o.get("liq")]
    zero = [HG.SLOT_LABEL[s] for s in HG.active(Q.holdings)
            if float(Q.slot_w.get(s, 0) or 0) <= 0 and s not in STRATEGIES[to]["assets"]]
    unp = HG.unplaced_assets(_live()["w"][to], Q.holdings)
    return J({"to": to, "to_name": STRAT_NAME[to], "n_now": len(P.plan["orders"]), "n": len(Q.plan["orders"]),
              "buy": _r(Q.plan["buy"]), "sell": _r(Q.plan["sell"]),
              "liq": [{"name": FL.fund_name(o["code"]) or o["code"], "amount": _r(o["shares"] * o["nav"])} for o in liq],
              "zero": zero, "unplaced": [{"name": ETF_META.get(k, {}).get("name", k),
                                          "w": _r(float(_live()["w"][to].get(k, 0)) * 100), "to": v} for k, v in unp.items()]})


@acct_view
async def set_strategy(request, aid, P, a):
    to = (await request.json()).get("to")
    if to not in KEYS:
        return J({"error": "没有这个策略"}, 400)
    a["strategy"] = to
    AC.save(aid, a)
    return J({"ok": True})


@acct_view
async def edit_holdings(request, aid, P, a):
    """选基配置：开关位置 / 加一只 / 删一只 / 改买卖单位 / 改位置内占比。"""
    b = await request.json()
    s, op = b.get("slot"), b.get("op")
    if s not in HG.SLOTS:
        return J({"error": "没有这个位置"}, 400)
    h = {k: HG._norm_slot(v) for k, v in (a.get("holdings") or HG._default_holdings()).items()}
    slot = h.get(s, HG._norm_slot({}))
    code = str(b.get("code") or "")
    if op == "toggle":
        slot["on"] = bool(b.get("on"))
    elif op == "add":
        if not (code.isdigit() and len(code) == 6):
            return J({"error": "基金代码要 6 位数字"}, 400)
        slot = HG.add_fund(slot, code, FL.fund_name(code) or code)
    elif op == "remove":
        slot = HG.remove_fund(slot, code)
    elif op == "unit":
        for f in slot["funds"]:
            if f["code"] == code:
                f["unit"] = "股" if b.get("unit") == "股" else "份额"
                f["lot"] = 100 if f["unit"] == "股" else 1
    elif op == "shares":
        vals = {str(k): float(v or 0) for k, v in (b.get("shares") or {}).items()}
        tot = sum(vals.values())
        for f in slot["funds"]:
            f["share"] = round(vals.get(f["code"], 0) / tot, 6) if tot > 0 else round(1 / len(slot["funds"]), 6)
    elif op == "reset":                      # 只恢复这一个位置
        slot = HG._default_holdings()[s]
    else:
        return J({"error": "不认识的操作"}, 400)
    h[s] = HG._norm_slot(slot)
    a["holdings"] = h
    AC.save(aid, a)
    return J({"ok": True})


# ------------------------------------------------------------------ 市场（公共）
_LIVE_FILES = {"hs300": "hs300", "us_sp500": "us_sp500", "credit": "bond_credit", "bond_short": "bond_short_etf",
               "bond_10y": "bond_10y_etf", "bond_30y": "bond_30y_etf", "gold": "gold", "nonferr": "nonferr", "wti": "wti"}
_SIGNALS = [
    ("nonferr_below_sma75", "nonferr", "跌破 SMA75", ["B-Con", "B-RP", "V3c"]),
    ("gold_below_sma75", "gold", "跌破 SMA75", ["B-RP", "V3c"]),
    ("sp500_below_sma75", "us_sp500", "跌破 SMA75", ["B-RP", "V3c"]),
    ("wti_below_sma75", "wti", "跌破 SMA75", ["B-Con", "B-RP", "V3c"]),
    ("hs300_below_sma30", "hs300", "跌破 SMA30", ["B-RP"]),
]


async def signals(request: Request):
    from allweather.rebalance import compute_signal_states
    prices = pd.DataFrame({c: pd.read_csv(DATA_DIR / f"{f}.csv", parse_dates=["date"], index_col="date")["close"]
                           for c, f in _LIVE_FILES.items() if (DATA_DIR / f"{f}.csv").exists()}).sort_index().ffill().dropna()
    sg = compute_signal_states(prices)
    rows = [{"name": f'{ETF_META[a]["name"]} ({ETF_META[a]["code"]})', "desc": d, "on": bool(sg.get(k)),
             "applies": {s: (s in st) for s in KEYS}} for k, a, d, st in _SIGNALS]
    curves = {}
    fp = ROOT / "output" / "nv_curves.csv"
    if fp.exists():
        df = pd.read_csv(fp, index_col=0, parse_dates=True)
        for k in KEYS:
            if BENCH_COL[k] in df.columns:
                s = df[BENCH_COL[k]].dropna().tail(125)
                curves[STRAT_NAME[k]] = {"dates": [f"{d:%Y-%m-%d}" for d in s.index],
                                         "ret": [round((float(v) / float(s.iloc[0]) - 1) * 100, 4) for v in s]}
    return J({"rows": rows, "strategies": [{"key": k, "name": STRAT_NAME[k]} for k in KEYS], "curves": curves,
              "asof": f"{prices.index[-1]:%Y-%m-%d}", "hs300_dd": _r(sg.get("hs300_dd_pct", 0) * 100),
              "gold_dd": _r(sg.get("gold_dd_pct", 0) * 100), "pb": _r(sg.get("pb_pctile")), "pe": _r(sg.get("pe_pctile"))})


async def backtest(request: Request):
    from allweather.data import load_panel
    from allweather.pipeline import run_strategy_backtest
    from allweather.stats import perf_metrics
    start = request.query_params.get("start") or "2015-01-01"
    cad = request.query_params.get("cadence") or "monthly"
    aid = request.query_params.get("acct")
    names = ["V3-B 保守增强", "V3-B 风险平价", "V3c 多元"]
    out, base = {}, {}
    if cad == "mine":
        a = AC.load(aid) if aid else None
        dates = sorted({pd.Timestamp(t["date"]) for t in (a or {}).get("trades", []) if t.get("side") in ("买入", "卖出")})
        if not a or not dates:
            return J({"error": "这个账户还没有买卖记录，没有「操作日」可以回测"}, 400)
        c0 = pd.Timestamp(a.get("created") or dates[0])
        rets = load_panel(end=pd.Timestamp.today().strftime("%Y-%m-%d")).pct_change().dropna()
        ix = rets.index
        pre = [d for k, d in enumerate(ix) if d < c0 and (k + 1 == len(ix) or ix[k + 1].month != d.month)]
        for n in names:
            for tag, kw in (("我的操作日", {"rebal_dates": pre + dates}), ("月末", {})):
                r = run_strategy_backtest(rets, n, track_weights=True, **kw)
                nv = r.nv.loc[c0:]
                out[f"{n} · {tag}"] = (nv / float(nv.iloc[0]), int((r.weight_df.index >= c0).sum()))
            base[f"{n} · 我的操作日"] = f"{n} · 月末"
    else:
        rets = load_panel().loc[start:].pct_change().dropna()
        for n in names:
            r = run_strategy_backtest(rets, n, cad)
            lbl = n if cad == "monthly" else f"{n} · {dict(biweekly='双周', weekly='每周')[cad]}"
            out[lbl] = (r.nv, int(r.n_rebal))
            if cad != "monthly":
                r0 = run_strategy_backtest(rets, n)
                out[f"{n} · 月末"] = (r0.nv, int(r0.n_rebal))
                base[lbl] = f"{n} · 月末"
    rows, curves = [], {}
    for k, (nv, n) in out.items():
        m = perf_metrics(nv, rets=nv.pct_change().dropna())
        short = len(nv) < 252
        row = {"name": k, "ret": _r((float(nv.iloc[-1]) / float(nv.iloc[0]) - 1) * 100), "cagr": _r(m["cagr"] * 100),
               "mdd": _r(m["mdd"] * 100), "sharpe": None if short else _r(m["sharpe"]), "vol": _r(m["vol"] * 100),
               "n": n, "short": short}
        if k in base:
            b, mb = out[base[k]][0], perf_metrics(out[base[k]][0], rets=out[base[k]][0].pct_change().dropna())
            row["vs"] = _r(((float(nv.iloc[-1] / nv.iloc[0]) - float(b.iloc[-1] / b.iloc[0])) if short
                            else (m["cagr"] - mb["cagr"])) * 100)
            row["vs_mdd"] = _r((m["mdd"] - mb["mdd"]) * 100)
        rows.append(row)
        s = nv if len(nv) < 600 else nv.resample("W-FRI").last().dropna()
        curves[k] = {"dates": [f"{d:%Y-%m-%d}" for d in s.index], "ret": [round((float(v) / float(s.iloc[0]) - 1) * 100, 3) for v in s]}
    return J({"rows": rows, "curves": curves, "cadence": cad, "start": start})


async def valuation(request: Request):
    from allweather import valuation as V
    snap = V.load_snapshot()
    if snap.empty:
        return J({"rows": [], "date": None})
    rows = []
    for r in snap.to_dict("records"):
        dd = V.drawdown_10y(r["代码"])
        tot, _vs, _ps, lb = V.score(r["PE百分位"], r["PB百分位"], dd)
        rows.append({"code": r["代码"], "name": r["名称"], "mkt": r["市场"], "lv": r["估值"],
                     "pe": _r(r["PE"]), "pep": _r(r["PE百分位"]), "pb": _r(r["PB"]), "pbp": _r(r["PB百分位"]),
                     "dy": _r(r["股息率"]), "roe": _r(r["ROE"]), "dd": _r(dd * 100) if dd is not None else None,
                     "sc": tot, "rt": lb})
    return J({"rows": rows, "date": f"{pd.Timestamp(snap['数据日'].max()):%Y-%m-%d}"})


async def valuation_hist(request: Request):
    from allweather import valuation as V
    h = V.load_history(request.path_params["code"])
    if h.empty:
        return J({"dates": [], "pe": [], "pb": []})
    return J({"dates": [f"{d:%Y-%m-%d}" for d in h.index],
              "pe": [_r(v, 3) if pd.notna(v) and v > 0 else None for v in h.get("pe", pd.Series(index=h.index))],
              "pb": [_r(v, 4) if pd.notna(v) and v > 0 else None for v in h.get("pb", pd.Series(index=h.index))]})


async def fund_search(request: Request):
    q = request.query_params.get("q") or ""
    d = FL.name_candidates(q, limit=20)
    return J({"rows": [{"code": r["代码"], "name": r["名称"], "src": r["来源"]} for r in d.to_dict("records")]})


async def fund_detail(request: Request):
    code = request.path_params["code"]
    ok, msg = FL.ensure_fresh(code)
    nv = FL.build_nav(code)
    if nv is None or not len(nv):
        return J({"error": msg or "没有这只基金的净值"}, 404)
    return J({"code": code, "name": FL.fund_name(code) or code, "msg": msg,
              "dates": [f"{d:%Y-%m-%d}" for d in nv.index], "values": [round(float(v), 4) for v in nv]})


# ------------------------------------------------------------------ 更新数据（后台线程）
_UPD = {"running": False, "errors": [], "finished": 0.0}


def _do_update():
    try:
        from allweather.fetch import fetch_all, fetch_prices, update_nav_detail
        from allweather import valuation as V
        _ok, e1, _u = fetch_all(force=False, end=pd.Timestamp.today().strftime("%Y%m%d"))
        _pok, e2 = fetch_prices()
        _m, e3 = update_nav_detail()
        _vm, e4 = V.update_all()
        _UPD["errors"] = list(e1) + list(e2) + list(e3) + list(e4)
    except Exception as e:  # noqa: BLE001
        _UPD["errors"] = [f"更新失败：{str(e)[:160]}"]
    finally:
        _UPD["running"], _UPD["finished"] = False, time.time()


async def update(request: Request):
    if request.method == "POST" and not _UPD["running"]:
        _UPD.update(running=True, errors=[])
        threading.Thread(target=_do_update, daemon=True).start()
    return J({**_UPD, "asof": f'{_live()["panel"].index[-1]:%Y-%m-%d}' if not _UPD["running"] else None})


# ------------------------------------------------------------------ 密码
_PW = os.environ.get("AW_PASSWORD_SHA256", "").strip().lower()
_TOKEN = hashlib.sha256(f"aw-h5:{_PW}".encode()).hexdigest()[:32] if _PW else ""


async def login(request: Request):
    if request.method == "GET":
        return J({"required": bool(_PW)})
    pw = (await request.json()).get("password") or ""
    if not _PW or hmac.compare_digest(hashlib.sha256(pw.encode()).hexdigest(), _PW):
        r = J({"ok": True})
        if _PW:
            r.set_cookie("aw", _TOKEN, max_age=180 * 86400, httponly=True, samesite="lax")
        return r
    return J({"error": "密码不对"}, 401)


class Auth(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        p = request.url.path
        if _PW and p.startswith("/api/") and p != "/api/login" and request.cookies.get("aw") != _TOKEN:
            return J({"error": "需要登录", "login": True}, 401)
        return await call_next(request)


async def spa(request: Request):
    """前端是单页应用：/a/main/fund/511260 这类地址刷新时也回 index.html。"""
    f = (DIST / request.path_params.get("path", "")).resolve()
    if f.is_file() and f.is_relative_to(DIST.resolve()) and f.name != "index.html":
        return FileResponse(f)
    idx = DIST / "index.html"
    # index.html 不能缓存：重新构建后它指向新的带哈希资源，缓存住旧的就一直是旧页面
    return (FileResponse(idx, headers={"Cache-Control": "no-cache"}) if idx.exists()
            else J({"error": "前端还没构建：cd web && npm run build"}, 404))


routes = [
    Route("/api/login", login, methods=["GET", "POST"]),
    Route("/api/accounts", accounts),
    Route("/api/accounts", create_account, methods=["POST"]),
    Route("/api/acct/{aid}", patch_account, methods=["PATCH"]),
    Route("/api/acct/{aid}", delete_account, methods=["DELETE"]),
    Route("/api/trash/{file}/restore", trash_restore, methods=["POST"]),
    Route("/api/trash/{file}", trash_purge, methods=["DELETE"]),
    Route("/api/acct/{aid}/home", home),
    Route("/api/acct/{aid}/holding/{code}", holding),
    Route("/api/acct/{aid}/record-options", record_options),
    Route("/api/acct/{aid}/nav/{code}", nav_on),
    Route("/api/acct/{aid}/trades", trades),
    Route("/api/acct/{aid}/trades", add_trade, methods=["POST"]),
    Route("/api/acct/{aid}/trades/{i:int}", edit_trade, methods=["PUT", "DELETE"]),
    Route("/api/acct/{aid}/calc", calc),
    Route("/api/acct/{aid}/dca", dca),
    Route("/api/acct/{aid}/period", period),
    Route("/api/acct/{aid}/compare", compare),
    Route("/api/acct/{aid}/health", health),
    Route("/api/acct/{aid}/weights", weights),
    Route("/api/acct/{aid}/switch-preview", switch_preview),
    Route("/api/acct/{aid}/strategy", set_strategy, methods=["POST"]),
    Route("/api/acct/{aid}/holdings", edit_holdings, methods=["POST"]),
    Route("/api/market/signals", signals),
    Route("/api/market/backtest", backtest),
    Route("/api/market/valuation", valuation),
    Route("/api/market/valuation/{code}", valuation_hist),
    Route("/api/market/fund-search", fund_search),
    Route("/api/market/fund/{code}", fund_detail),
    Route("/api/update", update, methods=["GET", "POST"]),
]
if (DIST / "assets").exists():
    routes.append(Mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets"))
routes.append(Route("/{path:path}", spa))
app = Starlette(routes=routes, middleware=[Middleware(Auth)])
