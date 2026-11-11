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
from starlette.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "streamlit_app"))

from allweather import accounts as AC  # noqa: E402
from allweather import holdings as HG  # noqa: E402
from allweather.chart_html import pnl_chart_html, trend_chart_data, trend_chart_html  # noqa: E402
from allweather.config import DATA_DIR, ETF_META, STRATEGY_PARAMS  # noqa: E402,F401
from allweather.portfolio import Portfolio, close_trade_idx  # noqa: E402
from allweather.sim_account import fund_pnl  # noqa: E402
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
    h = P.health()          # 体检异常要在资产首页露出来，不必等用户点进体检页
    warn = {"n": len(h["bad"]),
            "items": [{"label": i["label"], "over": i["over"]} for i in h["bad"]]}
    return J({"account": _acct_info(aid, a), "summary": {k: (_r(v) if isinstance(v, float) else v) for k, v in s.items()},
              "status": {k: (_r(v) if isinstance(v, float) else v) for k, v in P.status().items()},
              "health_warn": warn,
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


# ------------------------------------------------------------------ 持仓详情内嵌图表（iframe）
def _frame_doc(inner: str, height: int) -> str:
    """把组件 HTML 包成完整文档；body 上带 data-frame-height 供父页面自适应 iframe 高度。

    额外注入一段高度上报：手机窄屏时控件换行、stats 折行会让内容比预设高度高，
    ResizeObserver 把真实 scrollHeight postMessage 给父页面，避免图底被裁掉。
    """
    # 用 #wrap 的真实底部而不是 documentElement.scrollHeight：后者在内容不足时至少等于
    # iframe 视口高度，和「父页面按上报值放大 iframe」会形成正反馈，把卡片越撑越长。
    reporter = (
        '<script>(function(){'
        'var w=document.getElementById("wrap");'
        'function send(){try{'
        'var h=w?Math.ceil(w.getBoundingClientRect().bottom+window.scrollY+6):document.body.scrollHeight;'
        'parent.postMessage({__awFrameHeight:h},"*")'
        '}catch(e){}}'
        'addEventListener("load",send);'
        'if(w)new ResizeObserver(send).observe(w);'
        'send();'
        '})();</script>'
    )
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>基金走势</title>'
            '<style>html,body{font:13px/1.6 -apple-system,"PingFang SC",sans-serif;color:#334155}</style>'
            '</head>'
            f'<body data-frame-height="{int(height)}" style="margin:0">{inner}{reporter}</body></html>')


def _frame_notice(text: str, height: int = 170) -> str:
    """单点 / 无数据时给一句明确的说明，不留一个空白 iframe。"""
    return _frame_doc(
        '<div style="padding:22px 18px;color:#475569;background:#F8FAFC;'
        'border:1px solid #E2E8F0;border-radius:10px;margin:14px">'
        f'{text}</div>', height)


@acct_view
async def holding_chart(request, aid, P, a):
    """持仓详情图表：与 Streamlit 版 st.iframe 同源同码的完整 HTML。

    「买卖点」= 三层面板（净值 / 相对起点 / 单期涨跌）+ 全历史有界视窗拖动缩放 + 成交三角 tooltip；
    「累计盈亏」= 元为单位的零轴填色曲线。前端用 <iframe src> 加载，同源可共享 localStorage 区间记忆。
    """
    code = request.path_params["code"]
    view = request.query_params.get("view", "trade")
    it = next((x for x in P.items() if x["code"] == code and not x.get("dup")), None)
    if it is None:
        return HTMLResponse(_frame_notice("这只基金不在当前账户里。"))
    unit = P.holding(it).get("unit") or HG.default_unit(code)
    nv = P.nav(code)

    # 与 app.py::_code_trades 同口径：日期 2026/10/27、份额单位、逐笔份额与成交净值
    trades = []
    for t in P.trades_of(code):
        if t["side"] not in ("买入", "卖出"):
            continue
        try:
            day = pd.Timestamp(str(t["date"])).strftime("%Y/%m/%d")
        except Exception:  # noqa: BLE001 - 日期写坏了就跳过这一笔
            continue
        sh, nav = float(t["shares"]), float(t["nav"])
        qty = f"{sh:,.0f} 股" if unit == "股" else f"{sh:,.2f} 份"
        trades.append({"date": day, "side": t["side"],
                       "label": f"{qty} @ {nav:.4f}" if nav > 0 else qty})
    trades.sort(key=lambda x: x["date"])

    if view == "pnl":
        rows = [t for t in (a.get("trades") or []) if str(t.get("code") or "") == str(code)]
        pnl = fund_pnl(rows, nv)
        if len(pnl) <= 1:
            msg = ("累计盈亏要等有净值数据才能画：这只基金缺净值，拉取后自动出现。"
                   if not trades else "净值停在成交那天，之后还没有新的净值 —— "
                                      "下一个净值日出来，曲线才会从这一点往上（或往下）长。")
            return HTMLResponse(_frame_notice(msg))
        h = 460 if len(pnl) > 20 else 300
        inner = pnl_chart_html(pnl, trades=trades, store="awPnl.fund", default_range="近1月",
                               heading="", height=h)
        return HTMLResponse(_frame_doc(inner, h + 160))

    # 默认「买卖点」
    if len(nv) < 2:
        return HTMLResponse(_frame_notice("这只基金还没有净值数据，拉取后才有走势图。"))
    hist = trend_chart_data(nv)
    d = hist["日"]
    inner = trend_chart_html(d["labels"], d["prices"], d["windows"]["近1月"]["count"],
                             rets=d["rets"], histories=hist, trades=trades,
                             store="awTrend.fund", default_range="近1月", heading="", height=440)
    return HTMLResponse(_frame_doc(inner, 700))


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


def _hold_days(a: dict, code: str, day: str) -> int | None:
    """估算持有天数：取该基金最早一笔还没卖完的买入（赎回费按 FIFO 先进先出）。"""
    try:
        d = pd.Timestamp(day)
        buys = sorted(pd.Timestamp(t["date"]) for t in (a.get("trades") or [])
                      if t.get("code") == code and t.get("side") == "买入" and pd.Timestamp(t["date"]) <= d)
        return int((d - buys[0]).days) if buys else None
    except Exception:  # noqa: BLE001
        return None


def _trade_from_body(b: dict, a: dict, skip: int | None = None) -> dict:
    """记一笔 / 改一笔的校验，与 Streamlit 版同：金额、单价 > 0，卖出不超过当时持有。"""
    side, code, slot = b.get("side"), str(b.get("code") or ""), str(b.get("slot") or "")
    day = str(b.get("date") or "")[:10]
    amount, nav = float(b.get("amount") or 0), float(b.get("nav") or 0)
    # 手续费：前端没传就按该基金的真实费率算（场外申购/赎回费、场内佣金），传了就用传入值（可手工改）
    fee = b.get("fee")
    fee = None if fee is None or fee == "" else float(fee)
    # 账户模型里没有资金转入转出：钱全在基金里，只记买入 / 卖出
    if side in ("转入", "转出", "入金", "出金"):
        raise ValueError("这个账户只记买入和卖出 —— 钱都在基金里，没有「资金转入账户」这一步")
    if side not in ("买入", "卖出") or not code or not day:
        raise ValueError("类型、基金、日期都要填")
    if amount <= 0:
        raise ValueError("金额要大于 0")
    if nav <= 0:
        raise ValueError("单价要大于 0 —— 换一天或手工填那天的成交净值")
    if fee is None:
        from allweather import fees as FEES
        fee = FEES.buy_fee(code, amount) if side == "买入" else FEES.sell_fee(code, amount, _hold_days(a, code, day))
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
def _attach_quote(rows: list[dict]) -> None:
    """给场内单挂上「现价 / 溢价率」，买入提示用。

    溢价 = 场内现价 ÷ 最新净值 − 1。场外按净值申购，没有溢价这回事，所以只处理 otc=False。
    取不到（断网、接口改版）就留 None —— 页面不显示，绝不因此拦住下单。
    """
    from allweather import quote as QUOTE
    ex = [r for r in rows if r.get("code") and not r.get("otc")]
    if not ex:
        return
    try:
        q = QUOTE.snapshot([r["code"] for r in ex])
    except Exception:  # noqa: BLE001
        return
    for r in ex:
        r["quote"] = q.get(r["code"])


def _calc_payload(P: Portfolio, a: dict) -> dict:
    p = P.plan
    act = [_hj(P.holding(it)) | {"slot_w": _r(it["slot_w"] * 100), "slot_tgt_w": _r(it["slot_tgt_w"] * 100)}
           for it in p["rows"] if it.get("side")]
    _attach_quote(act)
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
    col = BENCH_COL.get(stg, "")
    curves = {}
    mine = P.daily["nav"].astype(float) if len(P.daily) else pd.Series(dtype=float)
    if len(mine) > 1:
        curves["我的账户"] = mine
    # 三条线：我的账户 / 默认基金·我的操作日 / 策略理论（标准执行）。
    # 中间这条 = 默认 9 只 ETF + 当期建议权重，但调仓日换成账户里真实的成交日，
    # 于是「我的账户 − 它」= 选基差异，「它 − 策略理论」= 下单时点差异，两个差各归各位。
    # （「项目默认基金·固定权重」那条已下线，它用今天这套权重往回套，没有执行意义。）
    tdays = sorted({pd.Timestamp(t["date"]) for t in (a.get("trades") or [])
                    if t.get("side") in ("买入", "卖出") and t.get("date")})
    if col and len(tdays) > 1:
        adv = BM.replay_advice(col, a.get("created"), tdays, nav_getter=HG.nav_series)
        if len(adv) > 1:
            ba = P.bench_index(adv)
            if len(ba) > 1:
                curves["默认基金 · 我的操作日"] = ba
    # 理论曲线口径：全量回测截止日，以及延长后覆盖到的行情日
    theory = {}
    try:
        nv = pd.read_csv(ROOT / "output" / "nv_curves.csv", index_col=0, parse_dates=True)
        if col in nv.columns:
            theory["backtest_end"] = f"{nv[col].dropna().index[-1]:%Y-%m-%d}"
    except Exception:  # noqa: BLE001
        pass
    full = BM.strategy_curve(col)
    if full is not None:
        theory["asof"] = f"{full.index[-1]:%Y-%m-%d}"
        created = a.get("created")
        s = full.loc[full.index >= pd.Timestamp(created)] if created else full
        bs = P.bench_index(s)
        if len(bs) > 1:
            curves["策略理论"] = bs
    theory["tracked"] = bool(theory.get("backtest_end") and theory.get("asof")
                             and theory["backtest_end"] != theory["asof"])
    out = {}
    for k, s in curves.items():
        s = s.dropna()
        out[k] = {"dates": [f"{d:%Y-%m-%d}" for d in s.index], "ret": [round((float(v) / float(s.iloc[0]) - 1) * 100, 4) for v in s]}
    gap = {}
    for k in ("默认基金 · 我的操作日", "策略理论"):
        if k in curves and "我的账户" in curves:
            x, y = curves["我的账户"], curves[k]
            e = min(x.index[-1], y.index[-1])
            gap[k] = _r((float(x.loc[:e].iloc[-1] / x.iloc[0]) - float(y.loc[:e].iloc[-1] / y.iloc[0])) * 100)
    return J({"account": _acct_info(aid, a), "curves": out, "gap": gap,
              "mine": _r(out["我的账户"]["ret"][-1]) if "我的账户" in out else None,
              "theory": theory})


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
               "bond_10y": "bond_10y_etf", "bond_30y": "bond_30y_etf", "gold": "gold", "nonferr": "nonferr", "ene": "ene"}
_SIGNALS = [
    ("nonferr_below_sma75", "nonferr", "跌破 SMA75", ["B-Con", "B-RP", "V3c"]),
    ("gold_below_sma75", "gold", "跌破 SMA75", ["B-RP", "V3c"]),
    ("sp500_below_sma75", "us_sp500", "跌破 SMA75", ["B-RP", "V3c"]),
    ("wti_below_sma75", "ene", "跌破 SMA75", ["B-Con", "B-RP", "V3c"]),
    ("hs300_below_sma30", "hs300", "跌破 SMA30", ["B-RP"]),
]


async def signals(request: Request):
    from allweather import benchmark as BM
    from allweather.rebalance import compute_signal_states, macro_season
    prices = pd.DataFrame({c: pd.read_csv(DATA_DIR / f"{f}.csv", parse_dates=["date"], index_col="date")["close"]
                           for c, f in _LIVE_FILES.items() if (DATA_DIR / f"{f}.csv").exists()}).sort_index().ffill().dropna()
    sg = compute_signal_states(prices)
    rows = [{"name": f'{ETF_META[a]["name"]} ({ETF_META[a]["code"]})', "desc": d, "on": bool(sg.get(k)),
             "applies": {s: (s in st) for s in KEYS}} for k, a, d, st in _SIGNALS]
    curves = {}
    # 必须走 benchmark.strategy_curve：它会把 nv_curves.csv 按「回测最后一期目标权重」延长到
    # 行情最新日（_extend_to_latest）。直接读 CSV 时曲线停在 main.py 上次跑完那天，
    # 而 asof 取的是行情最新日，页面就出现「截至 2026/11/06」配一条 10/16 收尾的曲线
    # （2026-11-09 验收发现：CSV 停在 10/16、asof 已是 11/06，近6月窗口整体错位）。
    for k in KEYS:
        s = BM.strategy_curve(BENCH_COL[k])
        if s is None or len(s) < 2:
            continue
        # 给全历史，前端用统一区间控件切（原来写死 tail(125) = 近半年，
        # 于是这页压根没有时间区间可选，被用户 2026-11-08 抓出来）
        s = s.dropna()
        curves[STRAT_NAME[k]] = {"dates": [f"{d:%Y-%m-%d}" for d in s.index],
                                 "ret": [round((float(v) / float(s.iloc[0]) - 1) * 100, 4) for v in s]}
    return J({"rows": rows, "strategies": [{"key": k, "name": STRAT_NAME[k]} for k in KEYS], "curves": curves,
              "asof": f"{prices.index[-1]:%Y-%m-%d}", "macro": macro_season(prices, sg)})


def _strategy_spec(name: str) -> dict:
    """内置策略的持仓与设置，供回测页展示、并作为自定义策略的参照模板。

    全部从 config / strategy_backtest_kwargs 现取，避免页面上的说明和真实回测跑偏。
    """
    from allweather.config import ETF_META, STRATEGY_PARAMS, RISK_PARITY_MAX_WEIGHT
    from allweather.pipeline import strategy_backtest_kwargs, STRATEGY_ASSETS

    kw = strategy_backtest_kwargs(name)
    key = "rp" if name.endswith("风险平价") else ("con" if name.endswith("保守增强") else "v3c")
    assets = [{"key": a, "code": ETF_META.get(a, {}).get("code") or a,
               "name": ETF_META.get(a, {}).get("name") or a}
              for a in STRATEGY_ASSETS[name] if a in ETF_META]
    eq_w = kw.get("equity_trend_windows") or {}
    eq_assets = kw.get("equity_trend_assets") or []
    equity = [{"key": a, "window": int(eq_w.get(a, kw.get("equity_trend_window") or 0))} for a in eq_assets]
    from allweather.config import V3B_RP_BUCKETS as _RPB
    return {
        "assets": assets,
        # 分桶结构：风险平价是 4 桶分层，复刻时要一起带过去，否则会退化成「每资产一桶」
        "rp_buckets": {k: [x for x in v if x in STRATEGY_ASSETS[name]] for k, v in _RPB.items()} if key == "rp" else None,
        "method": "分层风险平价（4 桶等权）" if key == "rp" else "逆波动率",
        "method_key": "risk_parity" if key == "rp" else "inverse_vol",
        "window": int(STRATEGY_PARAMS[key]["window"]),
        "max_w": float(kw.get("max_w", RISK_PARITY_MAX_WEIGHT)),
        "min_w": float(kw.get("min_w", 0.02)),
        "trend": {
            "commodity": int(kw.get("nonferr_trend_window") or 0),
            "ene": int(kw.get("wti_trend_window") or 0),
            "gold": int(kw.get("gold_trend_window") or 0) if kw.get("gold_trend_filter") else 0,
            "equity": equity,
            "equity_max": max([e["window"] for e in equity], default=0),
        },
        "target_vol": float(kw["target_vol"]) if kw.get("target_vol") else None,
        "freq": kw.get("rebal_freq") or "monthly",
    }


async def backtest(request: Request):
    from allweather.data import load_panel, panel_returns
    from allweather.pipeline import run_strategy_backtest, strategy_window
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
        rets = panel_returns(load_panel(end=pd.Timestamp.today().strftime("%Y-%m-%d")))
        ix = rets.index
        pre = [d for k, d in enumerate(ix) if d < c0 and (k + 1 == len(ix) or ix[k + 1].month != d.month)]
        for n in names:
            for tag, kw in (("我的操作日", {"rebal_dates": pre + dates}), ("月末", {})):
                r = run_strategy_backtest(rets, n, track_weights=True, **kw)
                nv = r.nv.loc[c0:]
                out[f"{n} · {tag}"] = (nv / float(nv.iloc[0]), int((r.weight_df.index >= c0).sum()))
            base[f"{n} · 我的操作日"] = f"{n} · 月末"
    else:
        panel = load_panel()
        rets = panel_returns(panel.loc[start:])   # 每个策略在 run_strategy_backtest 里按自己的资产定起点
        for n in names:
            r = run_strategy_backtest(rets, n, cad)
            lbl = n if cad == "monthly" else f"{n} · {dict(biweekly='双周', weekly='每周')[cad]}"
            out[lbl] = (r.nv, int(r.n_rebal))
            if cad != "monthly":
                r0 = run_strategy_backtest(rets, n)
                out[f"{n} · 月末"] = (r0.nv, int(r0.n_rebal))
                base[lbl] = f"{n} · 月末"
    # 真实可用的最早起点，与本次请求的 start 无关。
    # 前端原来拿「本次返回曲线的首日」反推起点选项，一旦选了 2015，返回曲线就从 2015 起，
    # 选项只剩 2015+，再也回不到 2013（2026-11-11 用户实测「只能从 15 年回放」）。
    # 这里由后端给出固定下限，前端直接用它生成选项。
    if cad == "mine":
        panel = load_panel()
    min_start = min(strategy_window(panel_returns(panel), n).index[0] for n in names)

    rows, curves = [], {}
    for k, (nv, n) in out.items():
        m = perf_metrics(nv, rets=nv.pct_change().dropna())
        short = len(nv) < 252
        row = {"name": k, "ret": _r((float(nv.iloc[-1]) / float(nv.iloc[0]) - 1) * 100), "cagr": _r(m["cagr"] * 100),
               "mdd": _r(m["mdd"] * 100), "sharpe": None if short else _r(m["sharpe"]), "vol": _r(m["vol"] * 100),
               "calmar": None if short else _r(m["calmar"]), "n": n, "short": short}
        if k in base:
            b, mb = out[base[k]][0], perf_metrics(out[base[k]][0], rets=out[base[k]][0].pct_change().dropna())
            row["vs"] = _r(((float(nv.iloc[-1] / nv.iloc[0]) - float(b.iloc[-1] / b.iloc[0])) if short
                            else (m["cagr"] - mb["cagr"])) * 100)
            row["vs_mdd"] = _r((m["mdd"] - mb["mdd"]) * 100)
        rows.append(row)
        # 不再把长区间降采样成周收盘：卡片里的「最大回撤」是按日净值算的，
        # 曲线若只到周收盘，同一页会出现「图 -3.45% / 卡 -3.89%」两个数（用户 2026-11-08 要求这页显示回撤）
        s = nv
        curves[k] = {"dates": [f"{d:%Y-%m-%d}" for d in s.index], "ret": [round((float(v) / float(s.iloc[0]) - 1) * 100, 3) for v in s]}
    # 月 / 年收益：只看基准三策略（月末调仓那条），按期间最后一条净值算，保留期首相对上期末的涨跌
    base_nv = {k: nv for k, (nv, _n) in out.items() if cad == "monthly" or k.endswith("· 月末")}
    def _periods(freq, limit):
        acc = {}
        for k, nv in base_nv.items():
            try:
                s = nv.resample(freq).last().dropna()
                prev = nv.iloc[0]
                for d, v in s.items():
                    key = f"{d:%Y-%m}" if freq == "ME" else f"{d:%Y}"
                    acc.setdefault(key, {})[k] = _r((float(v) / float(prev) - 1) * 100)
                    prev = v
            except Exception:  # noqa: BLE001
                continue
        return [{"k": k, "v": v} for k, v in sorted(acc.items(), reverse=True)[:limit]]
    periods = {"monthly": _periods("ME", 24), "yearly": _periods("YE", 12)}
    # 调频影响：高频 / 我的操作日 相对月末的年化与回撤差（绝对值与差值并列）
    gaps = [{"name": r["name"], "cagr": r["cagr"], "mdd": r["mdd"], "vs": r.get("vs"), "vs_mdd": r.get("vs_mdd")}
            for r in rows if r.get("vs") is not None]
    specs = {n: _strategy_spec(n) for n in names}
    return J({"rows": rows, "curves": curves, "cadence": cad, "start": start,
              "min_start": f"{min_start:%Y-%m-%d}",
              "periods": periods, "gaps": gaps, "specs": specs})


async def valuation(request: Request):
    from allweather import valuation as V
    from allweather.config import ETF_META
    snap = V.load_snapshot()
    if snap.empty:
        return J({"rows": [], "date": None})
    mine = {v: k for k, v in V.ASSET_INDEX.items()}
    rows = []
    for r in snap.to_dict("records"):
        dd = V.drawdown_10y(r["代码"])
        tot, vs, ps, lb = V.score(r["PE百分位"], r["PB百分位"], dd)
        rows.append({"code": r["代码"], "name": r["名称"], "mkt": r["市场"], "lv": r["估值"],
                     "pe": _r(r["PE"]), "pep": _r(r["PE百分位"]), "pb": _r(r["PB"]), "pbp": _r(r["PB百分位"]),
                     "dy": _r(r["股息率"]), "roe": _r(r["ROE"]), "dd": _r(dd * 100) if dd is not None else None,
                     "sc": tot, "rt": lb, "vs": vs, "ps": ps,
                     "mine": ETF_META.get(mine[r["代码"]], {}).get("name", "") if r["代码"] in mine else ""})
    return J({"rows": rows, "date": f"{pd.Timestamp(snap['数据日'].max()):%Y-%m-%d}"})


async def valuation_hist(request: Request):
    from allweather import valuation as V
    h = V.load_history(request.path_params["code"])
    if h.empty:
        return J({"dates": [], "pe": [], "pb": []})
    return J({"dates": [f"{d:%Y-%m-%d}" for d in h.index],
              "pe": [_r(v, 3) if pd.notna(v) and v > 0 else None for v in h.get("pe", pd.Series(index=h.index))],
              "pb": [_r(v, 4) if pd.notna(v) and v > 0 else None for v in h.get("pb", pd.Series(index=h.index))]})


async def etf_premium(request: Request):
    """场内 ETF 的现价 / 最新净值 / 溢价率（估算）。codes 逗号分隔，不传就查默认那 9 只。

    溢价率一律用**小数**返回（0.1146 = 11.46%），与 /calc 里挂的 quote 同一口径，
    格式化交给前端，免得两边一个百分数一个小数。
    """
    from allweather import quote as QUOTE
    codes = [c.strip() for c in (request.query_params.get("codes") or "").split(",") if c.strip()]
    if not codes:
        codes = [m["code"] for m in ETF_META.values()]
    rows = []
    for r in QUOTE.snapshot(codes).values():
        rows.append({**r, "price": _r(r["price"], 4), "nav": _r(r["nav"], 4),
                     "chg": _r(r["chg"], 5), "premium": _r(r["premium"], 5)})
    return J({"asof": f"{pd.Timestamp.now():%Y-%m-%d}", "rows": rows})


async def fund_search(request: Request):
    q = request.query_params.get("q") or ""
    d = FL.name_candidates(q, limit=20)
    return J({"rows": [{"code": r["代码"], "name": r["名称"], "src": r["来源"]} for r in d.to_dict("records")]})


async def fund_fee(request: Request):
    """某只基金的费率（申购/赎回/场内佣金）。记一笔时用它预估手续费，也让页面能解释费率来源。"""
    from allweather import fees as FEES
    code = request.path_params["code"]
    amt = float(request.query_params.get("amount") or 0)
    side = request.query_params.get("side") or "买入"
    out = dict(FEES.get(code))
    out["exchange"] = FEES.is_exchange(code)
    out["desc"] = FEES.describe(code)
    if amt > 0:
        out["fee"] = FEES.buy_fee(code, amt) if side == "买入" else FEES.sell_fee(code, amt, None)
    return J(out)


async def fund_detail(request: Request):
    code = request.path_params["code"]
    ok, msg = FL.ensure_fresh(code)
    nv = FL.build_nav(code)
    if nv is None or not len(nv):
        return J({"error": msg or "没有这只基金的净值"}, 404)
    # 基础信息 + 费率：基金规模/类型/成立/经理/公司/风险 + 申赎费（页面「基金检索」详情展示）
    from allweather import fees as FEES
    fr = FEES.get(code)
    meta = {"size": fr.get("size"), "size_text": FEES.size_text(fr.get("size")), "type": fr.get("type"),
            "inception": fr.get("inception"), "manager": fr.get("manager"), "company": fr.get("company"),
            "risk": fr.get("risk"), "exchange": fr.get("exchange"), "fee_desc": FEES.describe(code),
            "profile": FEES.profile_text(code),
            "buy_rate": fr.get("buy_rate"), "buy_rate_raw": fr.get("buy_rate_raw"),
            "redeem": fr.get("redeem") or [], "min_buy": fr.get("min_buy")}
    return J({"code": code, "name": FL.fund_name(code) or code, "msg": msg, "ok": bool(ok), "meta": meta,
              # 场内/场外与持仓里「买卖单位」同一套判断：fund_lookup 的申购表优先，
              # 查不到再按代码兜底（0 开头场外、5/15/16 开头场内），不在这里另立规则
              "otc": HG.default_unit(code) == "份额",
              "dates": [f"{d:%Y-%m-%d}" for d in nv.index], "values": [round(float(v), 4) for v in nv]})


# ------------------------------------------------------------------ 更新数据（后台线程）
_UPD = {"running": False, "errors": [], "finished": 0.0, "started": 0.0}
# 看门狗上限：akshare 内部大量 requests 不带 timeout，网络一旦半通（比如走了一个不回包的代理），
# 更新线程会永久阻塞在 read 上，running 永远是 True。
UPD_TIMEOUT = 15 * 60


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


# ------------------------------------------------------------------ 自定义策略（策略工厂）
async def strategy_funds(request: Request):
    """设计策略页的候选基金池：长历史策略资产 + 本地已缓存净值的基金，带各自数据起始日。

    另外回传 4 个桶名与「资产 → 桶」默认映射：编辑器给每只基金配桶，保存时从当前持仓现生成
    rp_buckets，不再沿用复刻时的静态快照（2026-11-09）。
    """
    from allweather.config import ETF_META, V3B_RP_BUCKETS
    from allweather.data import load_panel
    panel = load_panel()
    bucket_of = {a: b for b, arr in V3B_RP_BUCKETS.items() for a in arr}
    # 内部 key 与 6 位代码都能查到默认桶：用户用代码搜同一只 ETF 时也能自动归桶
    bucket_lookup = dict(bucket_of)
    bucket_lookup.update({ETF_META[a]["code"]: b for a, b in bucket_of.items()
                          if a in ETF_META and ETF_META[a].get("code")})
    assets = [{"key": k, "code": ETF_META[k]["code"], "name": ETF_META[k]["name"],
               "from": f"{panel[k].first_valid_index():%Y-%m-%d}", "src": "策略资产",
               "bucket": bucket_of.get(k, "")}
              for k in ETF_META if k in panel.columns]
    codes = {a["code"] for a in assets}
    funds = []
    for c in FL.cached_codes():
        if c in codes:
            continue
        s = FL.build_nav(c)
        if s is None or len(s) < 2:
            continue
        funds.append({"key": c, "code": c, "name": FL.fund_name(c) or c,
                      "from": f"{s.index[0]:%Y-%m-%d}", "src": "基金净值",
                      "bucket": bucket_lookup.get(c, "")})
    return J({"assets": assets, "funds": funds,
              "buckets": list(V3B_RP_BUCKETS), "asset_bucket": bucket_lookup,
              "safe_asset": "credit"})


async def custom_backtest(request: Request):
    """POST {funds:[{key,weight}], start, freq, name, method, window, ...}，返回内置三策略 + 自定义策略的对比。
    计算只在 allweather/custom_backtest.py，不在这重写；兼容旧 {weights} 写法。"""
    from allweather.custom_backtest import custom_compare
    try:
        b = await request.json()
        return J(custom_compare(weights=b.get("weights") or {},
                                start=b.get("start") or "2015-01-01",
                                freq=b.get("freq") or "M",
                                name=b.get("name") or "我的组合",
                                funds=b.get("funds"),
                                # 策略工厂参数：加权方式 / 窗口 / 上限 / 现金 / 三组趋势过滤窗口
                                method=b.get("method") or "fixed",
                                window=int(b.get("window") or 20),
                                max_w=float(b.get("max_w") if b.get("max_w") is not None else 0.25),
                                min_w=float(b.get("min_w") if b.get("min_w") is not None else 0.02),
                                cash_ratio=float(b.get("cash_ratio") or 0.0),
                                trend_commodity=int(b.get("trend_commodity") if b.get("trend_commodity") is not None else 75),
                                trend_gold=int(b.get("trend_gold") or 0),
                                trend_equity=int(b.get("trend_equity") or 0),
                                trend_map=b.get("trend_map"),
                                target_vol=b.get("target_vol"),
                                rp_buckets=b.get("rp_buckets"),
                                safe_asset=b.get("safe_asset") or "credit",   # 趋势避风港，默认城投债
                                engine_kwargs=b.get("engine_kwargs")))
    except ValueError as e:
        return J({"error": str(e)}, 400)
    except Exception as e:  # noqa: BLE001 — 数据异常要显式报给前端，服务端同时留痕
        import traceback
        traceback.print_exc()
        return J({"error": f"回测失败：{str(e)[:160]}"}, 400)


# ------------------------------------------------------------------ 报告导出
def _report_rows(P, a):
    """账户报告共用的数据：汇总 / 持仓 / 交易流水 / 每日收益。"""
    summ = P.summary()
    holds = [P.holding(it) for it in P.items() if not it.get("dup")]
    trades = P.trades_of()
    daily = P.daily
    curve = [{"date": f"{d:%Y-%m-%d}", "total": _r(float(daily["equity"].iloc[i])),
              "pnl": _r(float(daily["pnl"].iloc[i])), "ret": _r((float(daily["nav"].iloc[i]) - 1) * 100)}
             for i, d in enumerate(daily.index)]
    return summ, holds, trades, curve


async def export_report(request: Request):
    """导出账户报告：md = Markdown，xlsx = Excel（汇总/持仓/流水/每日收益 四张表）。"""
    import io
    from urllib.parse import quote
    from starlette.responses import Response
    aid = request.path_params["aid"]
    if not AC.path_of(aid).exists():
        return J({"error": "没有这个账户"}, 404)
    fmt = request.query_params.get("fmt") or "md"
    try:
        P, a = _portfolio(aid)
    except Exception as e:  # noqa: BLE001
        return J({"error": str(e)}, 500)
    summ, holds, trades, curve = _report_rows(P, a)
    name = quote((a.get("name") or aid).replace(" ", ""))
    if fmt == "md":
        L = [f"# {a.get('name')} · 账户报告", "",
             f"- 类型：{a.get('kind')}　跟随：{STRAT_NAME.get(a.get('strategy'), a.get('strategy'))}",
             f"- 建立：{a.get('created')}　数据截至：{summ['asof']}", "",
             "## 汇总", "",
             f"| 总资产 | 今日收益 | 今日收益率 | 持有收益 | 持有收益率 | 现金 |",
             "|---|---|---|---|---|---|",
             f"| ¥{summ['total']:,.2f} | ¥{summ['today']:,.2f} | {summ['today_pct']:.2f}% "
             f"| ¥{summ['pnl']:,.2f} | {summ['pnl_pct']:.2f}% | ¥{summ['cash']:,.2f} |", "",
             "## 持仓", "", "| 基金 | 代码 | 位置 | 市值 | 持有收益 | 占比 |", "|---|---|---|---|---|---|"]
        L += [f"| {h['name']} | {h['code']} | {h['slot']} | ¥{h['mv']:,.2f} "
              f"| {('¥%.2f' % h['hold']) if h['hold'] is not None else '—'} | {h['w_now'] * 100:.2f}% |" for h in holds]
        L += ["", "## 交易流水", "", "| 日期 | 方向 | 基金 | 数量 | 单价 | 金额 |", "|---|---|---|---|---|---|"]
        L += [f"| {t['date']} | {t['side']} | {t['name'] or '—'} | {t['shares']:,.2f} "
              f"| {t['nav']:.4f} | ¥{t['amount']:,.2f} |" for t in trades]
        L += ["", "## 每日收益（近 60 个交易日）", "", "| 日期 | 总资产 | 累计收益 | 收益率 |", "|---|---|---|---|"]
        L += [f"| {c['date']} | ¥{c['total']:,.2f} | ¥{c['pnl']:,.2f} | {c['ret']:.2f}% |" for c in curve[-60:]]
        text = "\n".join(L) + "\n"
        return Response(text, media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}-report.md"})
    try:
        from openpyxl import Workbook
        wb = Workbook()
        def sheet(title, headers, rows):
            ws = wb.create_sheet(title)
            ws.append(headers)
            for r in rows:
                ws.append(r)
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = max(12, min(28, max(len(str(c.value or "")) for c in col) + 2))
        sheet("汇总", ["项目", "数值"], [["账户", a.get("name")], ["类型", a.get("kind")],
              ["跟随", STRAT_NAME.get(a.get("strategy"), a.get("strategy"))], ["数据截至", summ["asof"]],
              ["总资产", summ["total"]], ["今日收益", summ["today"]], ["持有收益", summ["pnl"]],
              ["持有收益率(%)", summ["pnl_pct"]], ["现金", summ["cash"]]])
        sheet("持仓", ["基金", "代码", "位置", "市值", "持有收益", "占比(%)"],
              [[h["name"], h["code"], h["slot"], h["mv"], h["hold"], _r(h["w_now"] * 100)] for h in holds])
        sheet("交易流水", ["日期", "方向", "基金", "数量", "单价", "金额"],
              [[t["date"], t["side"], t["name"], t["shares"], t["nav"], t["amount"]] for t in trades])
        sheet("每日收益", ["日期", "总资产", "累计收益", "收益率(%)"],
              [[c["date"], c["total"], c["pnl"], c["ret"]] for c in curve])
        del wb["Sheet"]
        buf = io.BytesIO(); wb.save(buf)
        return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}-report.xlsx"})
    except ImportError:
        return J({"error": "没装 openpyxl，只能导出 Markdown"}, 400)


async def update(request: Request):
    # 看门狗：任务跑在后台线程里，网络挂住时它永远不会走到 finally，running 一直是 True ——
    # 前端那个按钮就会一直转圈、点不动，只能重启服务（2026-11-11 用户遇到的就是这个）。
    # 超时直接复位，让用户能重来一次；卡住的那次线程还在后台，但不再挡住界面。
    if _UPD["running"] and _UPD.get("started") and time.time() - _UPD["started"] > UPD_TIMEOUT:
        _UPD.update(running=False, finished=time.time(),
                    errors=[f"上次更新超过 {UPD_TIMEOUT // 60} 分钟没结束，已重置（多半是行情接口卡住，再点一次通常就好）"])
    if request.method == "POST" and not _UPD["running"]:
        _UPD.update(running=True, errors=[], started=time.time())
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
    Route("/api/acct/{aid}/holding/{code}/chart", holding_chart),
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
    Route("/api/market/custom-backtest", custom_backtest, methods=["POST"]),
    Route("/api/market/strategy-funds", strategy_funds),
    Route("/api/market/valuation", valuation),
    Route("/api/market/premium", etf_premium),
    Route("/api/market/valuation/{code}", valuation_hist),
    Route("/api/market/fund-search", fund_search),
    Route("/api/market/fund/{code}", fund_detail),
    Route("/api/market/fund/{code}/fee", fund_fee),
    Route("/api/acct/{aid}/export", export_report),
    Route("/api/update", update, methods=["GET", "POST"]),
]
if (DIST / "assets").exists():
    routes.append(Mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets"))
routes.append(Route("/{path:path}", spa))
app = Starlette(routes=routes, middleware=[Middleware(Auth)])
