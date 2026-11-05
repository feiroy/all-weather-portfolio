"""H5 前端的 JSON 接口 + 静态文件（原型：资产首页 / 基金详情 / 记一笔）。

    ./myenv/bin/python -m uvicorn api.server:app --host 127.0.0.1 --port 8600

计算全在 allweather/（portfolio.py 与 Streamlit 版同口径），这里只做：读账户 → 算 → 转成 JSON，
以及「记一笔」的校验和写盘。只用 Starlette（Streamlit 自带），不新增依赖。
缓存：目标权重按「行情文件最新修改时间 + 策略」缓存，账户视图再加上账户文件修改时间 ——
数据和账户都没变时切页只是读内存，变了自动重算。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from allweather import accounts as AC  # noqa: E402
from allweather import holdings as HG  # noqa: E402
from allweather.config import DATA_DIR  # noqa: E402
from allweather.portfolio import Portfolio  # noqa: E402

DIST = ROOT / "web" / "dist"
STRAT_NAME = {"B-Con": "V3-B 保守增强", "B-RP": "V3-B 风险平价", "V3c": "V3c 多元"}
_W: dict = {}
_P: dict = {}


def _data_ver() -> float:
    fs = list(DATA_DIR.glob("*.csv")) + list((DATA_DIR / "nav_detail").glob("*.csv"))
    return max((f.stat().st_mtime for f in fs), default=0.0)


def _weights(strategy: str):
    ver = _data_ver()
    key = (strategy, ver)
    if key not in _W:
        from allweather.data import load_panel
        from allweather.pipeline import live_target_weights
        panel = load_panel(end=pd.Timestamp.today().strftime("%Y-%m-%d"))
        _W.clear()
        _W[key] = live_target_weights(strategy if strategy in STRAT_NAME else "B-Con", panel)[0]
    return _W[key]


def _portfolio(aid: str) -> tuple[Portfolio, dict]:
    path = AC.path_of(aid)
    if not path.exists():
        raise KeyError(aid)
    a = AC.load(aid)
    key = (aid, path.stat().st_mtime, _data_ver())
    if key not in _P:
        for k in [k for k in _P if k[0] == aid]:
            del _P[k]
        _P[key] = Portfolio(a, _weights(a.get("strategy") or "B-Con"))
    return _P[key], a


def _r(v, d=2):
    return None if v is None else round(float(v), d)


def _acct_info(aid: str, a: dict) -> dict:
    return {"id": aid, "name": a.get("name") or aid, "kind": a.get("kind") or "实盘",
            "strategy": a.get("strategy") or "B-Con",
            "strategy_name": STRAT_NAME.get(a.get("strategy") or "B-Con", a.get("strategy"))}


def _holding_json(P: Portfolio, h: dict) -> dict:
    return {**h, **{k: _r(h[k]) for k in ("mv", "day", "day_pct", "hold", "hold_pct", "amount")},
            "shares": _r(h["shares"], 4), "px": _r(h["px"], 4), "cost": _r(h["cost"], 4),
            "w_now": _r(h["w_now"] * 100, 2), "w_tgt": None if h["w_tgt"] is None else _r(h["w_tgt"] * 100, 2)}


# ------------------------------------------------------------------ 路由
async def accounts(request: Request):
    out = []
    for a in AC.list_accounts():
        try:
            P, raw = _portfolio(a["id"])
            s, m = P.summary(), P.month_curve()
            out.append({**_acct_info(a["id"], raw), "n_trades": a["n_trades"], "created": a.get("created"),
                        "total": _r(s["total"]), "pnl": _r(s["pnl"]), "pnl_pct": _r(s["pnl_pct"]),
                        "spark": m["ret"]})
        except Exception as e:  # noqa: BLE001 —— 一个账户坏了不影响列表
            out.append({**a, "error": str(e)[:120]})
    return JSONResponse({"accounts": out})


async def home(request: Request):
    aid = request.path_params["aid"]
    try:
        P, a = _portfolio(aid)
    except KeyError:
        return JSONResponse({"error": "没有这个账户"}, status_code=404)
    s = P.summary()
    return JSONResponse({
        "account": _acct_info(aid, a),
        "summary": {k: (_r(v) if isinstance(v, float) else v) for k, v in s.items()},
        "status": {k: (_r(v) if isinstance(v, float) else v) for k, v in P.status().items()},
        "month": P.month_curve(),
        "holdings": [_holding_json(P, P.holding(it)) for it in P.items() if not it.get("dup")],
    })


async def holding(request: Request):
    aid, code = request.path_params["aid"], request.path_params["code"]
    try:
        P, a = _portfolio(aid)
    except KeyError:
        return JSONResponse({"error": "没有这个账户"}, status_code=404)
    it = next((x for x in P.items() if x["code"] == code and not x.get("dup")), None)
    if it is None:
        return JSONResponse({"error": "这只基金不在当前账户里"}, status_code=404)
    nv = P.nav(code)
    return JSONResponse({
        "account": _acct_info(aid, a), "holding": _holding_json(P, P.holding(it)),
        "nav": {"dates": [f"{d:%Y-%m-%d}" for d in nv.index], "values": [round(float(v), 4) for v in nv]},
        "trades": [{**t, "shares": _r(t["shares"], 4), "nav": _r(t["nav"], 4), "amount": _r(t["amount"])}
                   for t in P.trades_of(code)],
    })


async def record_options(request: Request):
    aid = request.path_params["aid"]
    try:
        P, a = _portfolio(aid)
    except KeyError:
        return JSONResponse({"error": "没有这个账户"}, status_code=404)
    return JSONResponse({"account": _acct_info(aid, a), "funds": P.slot_options(),
                         "cash": _r(P.cash), "asof": f"{P.last:%Y-%m-%d}"})


async def nav_on(request: Request):
    aid, code = request.path_params["aid"], request.path_params["code"]
    day = request.query_params.get("date") or pd.Timestamp.today().strftime("%Y-%m-%d")
    P, _ = _portfolio(aid)
    v = P.nav_on(code, day)
    return JSONResponse({"code": code, "date": day, "nav": _r(v, 4),
                         "held": _r(P.held_on(code, day), 4)})


async def add_trade(request: Request):
    """记一笔：和 Streamlit 版同一套校验 —— 金额 / 单价 > 0、卖出不能超过当时持有。"""
    aid = request.path_params["aid"]
    try:
        P, a = _portfolio(aid)
    except KeyError:
        return JSONResponse({"error": "没有这个账户"}, status_code=404)
    b = await request.json()
    side, code, slot = b.get("side"), str(b.get("code") or ""), str(b.get("slot") or "")
    day = str(b.get("date") or "")[:10]
    amount, nav, fee = float(b.get("amount") or 0), float(b.get("nav") or 0), float(b.get("fee") or 0)
    if side not in ("买入", "卖出") or not code or not day:
        return JSONResponse({"error": "类型、基金、日期都要填"}, status_code=400)
    if amount <= 0:
        return JSONResponse({"error": "金额要大于 0"}, status_code=400)
    if nav <= 0:
        return JSONResponse({"error": "单价要大于 0 —— 换一天或手工填那天的成交净值"}, status_code=400)
    shares = (amount - fee) / nav if side == "买入" else (amount + fee) / nav
    if side == "卖出":
        held = P.held_on(code, day)
        if shares > held + 1e-6:
            return JSONResponse({"error": f"卖不了这么多：到 {day} 只持有 {held:,.2f}，这次要卖 {shares:,.2f}。"
                                          "改小金额，或先补录这笔之前漏记的买入。"}, status_code=400)
    a.setdefault("trades", []).append({"date": day, "side": side, "slot": slot, "code": code,
                                        "shares": round(shares, 4), "nav": nav, "fee": fee})
    AC.save(aid, a)
    return JSONResponse({"ok": True, "shares": round(shares, 4)})


async def spa(request: Request):
    """前端是单页应用：/a/main/fund/511260 这类地址刷新时也回 index.html。"""
    f = DIST / request.path_params.get("path", "")
    if f.is_file():
        return FileResponse(f)
    idx = DIST / "index.html"
    return FileResponse(idx) if idx.exists() else JSONResponse({"error": "前端还没构建：cd web && npm run build"}, 404)


routes = [
    Route("/api/accounts", accounts),
    Route("/api/acct/{aid}/home", home),
    Route("/api/acct/{aid}/holding/{code}", holding),
    Route("/api/acct/{aid}/record-options", record_options),
    Route("/api/acct/{aid}/nav/{code}", nav_on),
    Route("/api/acct/{aid}/trades", add_trade, methods=["POST"]),
]
if (DIST / "assets").exists():
    routes.append(Mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets"))
routes.append(Route("/{path:path}", spa))
app = Starlette(routes=routes)
