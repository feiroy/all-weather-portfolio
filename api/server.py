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
from contextlib import asynccontextmanager
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
from allweather import strategies as ST  # noqa: E402
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
_SW: dict = {}          # 自定义策略的目标权重缓存：(策略key, 数据版本) → (权重, 诊断)
_WF: dict = {}          # 按账户持仓算的内置策略权重：(策略key, 持仓指纹, 数据版本) → (权重, 原始权重, 诊断)
# 用可重入锁：`_live()` / `strategy_weights()` / `_portfolio()` 之间会互相调用，
# 普通 Lock 一旦有人在持锁时调了另一个（2026-11-12 就这么挂过一次），
# 同一线程重入会**永久阻塞**，整个事件循环跟着死，所有接口都不响应。
# 真正的解法是别在锁里跑重计算（见 _portfolio），这把锁只是防再犯的兜底。
_LOCK = threading.RLock()


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
# 版本号的定义搬到了 allweather/dataversion.py：接口层的缓存和 scripts/doctor.py
# 必须用同一份判断，否则又会出「文件更新了但页面不动」。这里只留一个别名。
from allweather.dataversion import data_ver  # noqa: E402


def _data_ver(fresh: bool = False) -> float:
    return data_ver(fresh=fresh)


def _live() -> dict:
    """三个内置策略的目标权重（含趋势过滤）与原始权重 + 行情面板 —— 按数据版本缓存。

    这里的权重是**项目默认标的**口径（live["w"] / live["w0"]），只当基准对照用；
    账户实际下单的权重走 `_w_full()`，那一个按账户的选基配置算。
    """
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
            _SW.clear()
            _WF.clear()
        return _W


def _hold_sig(hs: dict | None) -> str:
    """选基配置指纹。定义在 holdings 里，Streamlit 和接口层共用同一份。"""
    return HG.holdings_sig(hs)


def _w_full(key: str, a: dict | None) -> tuple[dict, dict, dict]:
    """内置策略 → (目标权重, 趋势过滤前的原始权重, 诊断)，**按账户实际持有的基金算**。

    2026-11-16 用户：「我要买场内和场外基金混合验证，如果我不问，都不知道你里面的算法策略
    都没适配」。原来三个内置策略一律用项目默认的 8 只 ETF 序列算权重，用户拿 006131 /
    161119 / 000217 去买，波动率和均线都不一样，分到的钱自然对不上。

    结果按 (策略, 选基配置指纹, 数据版本) 缓存：算一次要跑两遍回测引擎（约 0.2 秒），
    每次切页都重算没必要。
    """
    live = _live()
    hs = (a or {}).get("holdings") or {}
    if not hs:
        return (live["w"].get(key, live["w"]["B-Con"]),
                live["w0"].get(key, live["w0"]["B-Con"]), {"used": [], "skipped": []})
    ck = (key, _hold_sig(hs), live["ver"])
    with _LOCK:
        hit = _WF.get(ck)
    if hit is not None:
        return hit
    from allweather.pipeline import live_target_weights
    info: dict = {}
    w, w0 = live_target_weights(key, live["panel"], holdings=hs, info=info)
    val = (w, w0, info)
    with _LOCK:
        if len(_WF) > 64:
            _WF.clear()
        _WF[ck] = val
    return val


def strategy_weights(key: str | None, a: dict | None = None) -> tuple[dict, dict]:
    """策略 key → (目标权重, 诊断)。内置三策略走 pipeline，`custom:<id>` 走策略库 + 回测引擎。

    传了账户（`a`）就按**这个账户实际持有的基金**算内置策略的权重；不传就是项目默认标的口径。
    自定义策略按 (key, 数据版本) 缓存：它的权重靠跑一遍回测引擎算（约 0.2~2 秒），
    每次切页都重算没必要；改了策略文件或行情，_data_ver() 会变，缓存自然失效。
    """
    live = _live()
    key = str(key or "B-Con")
    if not key.startswith("custom:"):
        w, _w0, info = _w_full(key if key in live["w"] else "B-Con", a)
        return w, info
    ck = (key, live["ver"])
    with _LOCK:
        hit = _SW.get(ck)
    if hit is not None:
        return hit
    from allweather.custom_backtest import live_custom_weights
    rec = ST.get(key.split(":", 1)[1])
    if rec is None:
        # 用 ValueError 而不是 KeyError：KeyError 在 acct_view 里被当成「没有这个账户」，
        # 会把「策略被删了」误报成账户不存在（用户就找不到原因了）
        raise ValueError("跟随的自定义策略不存在了，可能已被删除，请给它换个策略")
    w, diag = live_custom_weights(rec, live["panel"])
    with _LOCK:
        _SW.clear()
        _SW[ck] = (w, diag)
    return w, diag


def _portfolio(aid: str, target=None) -> tuple[Portfolio, dict]:
    path = AC.path_of(aid)
    if not path.exists():
        raise KeyError(aid)
    a = AC.load(aid)
    live = _live()
    stg = target or a.get("strategy") or "B-Con"
    key = (aid, path.stat().st_mtime, live["ver"], stg)
    with _LOCK:
        hit = _P.get(key)
    if hit is not None:
        # 构造时行情还没拉回来 → 整份 plan 是净值口径。行情补上以后要重建一次，
        # 否则页面永远停在净值（2026-11-16 实测：spot=True 但 mv/px 还是净值）。
        if hit.used_spot or not hit.spot_ready():
            return hit, a
    # 算权重（自定义策略要跑一遍回测引擎）和建 Portfolio（读几十条净值序列）都是重活，
    # 必须放在锁外面：
    # ① 锁里跑重活会让所有请求串行排队，页面像卡死；
    # ② `strategy_weights()` 第一行就是 `_live()`，它也要这把锁 —— 持锁调用会自我死锁。
    #    2026-11-12 就是上一版把它挪进 `with _LOCK` 里，导致服务整整卡住一小时。
    # 先算权重再建 Portfolio 的顺序仍然保留：算权重时会把新基金的净值拉进本地缓存，
    # Portfolio 建面板才读得到它（否则新加的第 10 只基金定不出价）。
    w = strategy_weights(stg, a)[0]
    P = Portfolio(a, w)
    with _LOCK:
        for k in [k for k in _P if k[0] == aid and k[3] == stg]:
            del _P[k]
        _P[key] = P
    return P, a


def _strategy_name(key: str) -> str:
    """策略 key → 显示名。自定义策略的名字来自策略库，策略被删了要看得出来。"""
    key = str(key or "B-Con")
    if key in STRAT_NAME:
        return STRAT_NAME[key]
    if key.startswith("custom:"):
        rec = ST.get(key.split(":", 1)[1])
        return (rec or {}).get("name") or "自定义策略（已删除）"
    return key


def _strategy_rec(key: str):
    """校验策略 key：内置三个返回 None，自定义返回它的记录；不存在就抛 ValueError。"""
    key = str(key or "")
    if key in KEYS:
        return None
    if key.startswith("custom:"):
        rec = ST.get(key.split(":", 1)[1])
        if rec:
            return rec
        raise ValueError("这个自定义策略不存在了，可能已被删除")
    raise ValueError("没有这个策略")


def _strategy_assets(key: str) -> list[str]:
    """策略用到的资产位置：内置看 pipeline.STRATEGY_ASSETS，自定义看策略库里的基金（key 已归一化）。"""
    from allweather.pipeline import LIVE_STRATEGY, STRATEGY_ASSETS
    rec = _strategy_rec(key)
    return list(ST.fund_map(rec)) if rec else list(STRATEGY_ASSETS[LIVE_STRATEGY[key]])


def _switch_holdings(a: dict, to: str, P=None) -> tuple[dict, list[str], list[str], list[str]]:
    """换策略后的位置体系 → (holdings, 新建的位置, 打开的位置, 关闭的位置)。

    预览和真换必须走这一个函数，否则预览的笔数金额会和真下单对不上（11-11 踩过：14 笔 vs 15 笔）。
    """
    rec = _strategy_rec(to)
    hs, added = (HG.ensure_slots(a.get("holdings") or {}, ST.fund_map(rec)) if rec
                 else (a.get("holdings") or {}, []))
    held = {r["slot"] for r in (P.plan["rows"] if P is not None else []) if float(r.get("shares") or 0) > 0}
    # 策略资产 → 账户位置（161119 挂在收益垫上，就是收益垫要开着，而不是另开一个「161119」）
    use = [HG.slot_for_key(hs, k) or k for k in _strategy_assets(to)]
    hs, opened, closed = HG.apply_strategy_slots(hs, use, held)
    return hs, added, opened, closed


def _acct_info(aid: str, a: dict) -> dict:
    stg = a.get("strategy") or "B-Con"
    return {"id": aid, "name": a.get("name") or aid, "kind": a.get("kind") or "实盘",
            "strategy": stg, "strategy_name": _strategy_name(stg), "created": a.get("created")}


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
        except ValueError as e:
            # 账户本身在、但算不出目标权重（比如跟随的自定义策略被删了）
            return J({"error": str(e)}, 400)
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
    stg = b.get("strategy") or "B-Con"
    if not src:
        # 新账户：策略不用的内置位置默认关（风险平价 / V3c 没有 10 年国债）。从别的账户复制的配置原样保留
        try:
            h, _, _ = HG.apply_strategy_slots(h, _strategy_assets(stg))
        except (ValueError, KeyError):
            pass
    aid = AC.create(b.get("name") or "新账户", b.get("kind") or "模拟", stg,
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
    h = P.holding(it)
    # 有没有「市价走势」页签：ETF_META 里登记过的场内标才有 price_*.csv
    has_price = any(str(m.get("code")) == str(code) for m in ETF_META.values())
    # 净值末端停在哪天：场外基金的缓存没人拉就一直停着，面板 ffill 之后是一条直线，
    # 看着像「净值没了」。落后的顺手在后台补一次，前端据此提示一句。
    nav_last, nav_stale = HG.nav_freshness(code)
    return J({"account": _acct_info(aid, a), "holding": _hj(h),
              "has_price": has_price, "nav_last": nav_last, "nav_stale": nav_stale,
              "nav": {"dates": [f"{d:%Y-%m-%d}" for d in nv.index], "values": [round(float(v), 4) for v in nv]},
              "trades": [{**t, "shares": _r(t["shares"], 4), "nav": _r(t["nav"], 4), "amount": _r(t["amount"])}
                         for t in P.trades_of(code)]})


def _bucket(day: pd.Timestamp, period: str) -> tuple[tuple, str]:
    """日期 → (排序键, 显示标签)。日/周/月/年四种粒度。"""
    if period == "week":
        iso = day.isocalendar()
        return (int(iso[0]), int(iso[1])), f"{int(iso[0])}年第{int(iso[1])}周"
    if period == "month":
        return (day.year, day.month), f"{day.year}年{day.month}月"
    if period == "year":
        return (day.year,), f"{day.year}年"
    return (day,), f"{day:%Y/%m/%d}"


@acct_view
async def holding_daily(request, aid, P, a):
    """这只基金逐日（可聚合到周/月/年）的持仓盈亏明细 —— 给用户手算核对用的。

    用户 2026-11-17：「把每一天的收益值、收益率直接展示到净值走势下面，方便我对照
    验证计算」→「把市价也填进去，我计算的时候需要用市值计算，因为场内用的是市价
    计算的收益，并且把手续费也显示出来，各种费用都显示出来，并且需要考虑按照日、
    周、月、年显示」。

    每行都是收益日历里那一格的原样导出，不另算一套：

    - 市值 = 份额 × **估值价**（场内当日收盘市价 / 最后一天实时价，场外净值）
    - 收益 = 市值变化 − 当日净流入（买入不会把本金算成收益，卖出也不会算成亏损）
    - 收益率 = 收益 ÷ (昨市值 + 当日买入额)
    - 费用 = 台账里这一天这笔交易的费用（场外申购/赎回费、场内佣金），聚合时求和

    `period=day|week|month|year`；聚合行的收益率按「区间收益 ÷ 区间占用资金」算，
    不是把每日收益率加总（那样会随天数虚增）。
    """
    code = request.path_params["code"]
    it = next((x for x in P.items() if x["code"] == code and not x.get("dup")), None)
    if it is None:
        return J({"error": "这只基金不在当前账户里"}, 404)

    period = (request.query_params.get("period") or "day").lower()
    if period not in ("day", "week", "month", "year"):
        period = "day"

    otc = bool(it["otc"])
    live_px = float(it["px"] or 0)          # plan 里那个价（场内=实时市价）
    has_live = bool(it.get("spot"))          # 真有行情才叫「市价」，否则是净值

    # 台账：按日汇总费用与净流入（买入 +，卖出 −），与 _replay 的 flow 同口径
    fee_of: dict[str, float] = {}
    flow_of: dict[str, float] = {}
    fee_kind: dict[str, float] = {}
    for t in P.trades_of(code):
        side, ds = t.get("side"), str(t.get("date") or "")
        if side not in ("买入", "卖出") or not ds:
            continue
        amt, fee = float(t.get("amount") or 0), float(t.get("fee") or 0)
        flow_of[ds] = flow_of.get(ds, 0.0) + (amt if side == "买入" else -amt)
        fee_of[ds] = fee_of.get(ds, 0.0) + fee
        kind = ("佣金" if not otc else ("申购费" if side == "买入" else "赎回费"))
        fee_kind[kind] = fee_kind.get(kind, 0.0) + fee

    rows, prev_mv = [], 0.0
    for d in sorted(P.by_day):
        r = P.by_day[d].get(str(code))
        if not r:
            continue
        pnl, pct, state, act = r
        ds = f"{d:%Y-%m-%d}"
        sh = float(P.held_on(code, d) or 0)
        # 最后一天用 plan 的实时价（和头卡同一个数），更早的用当日收盘价
        px = live_px if (d == P.last and live_px > 0) else (P.px_on(code, d) or 0)
        mv = sh * px
        flow = flow_of.get(ds, 0.0)
        base = prev_mv + max(flow, 0.0)
        key, label = _bucket(d, period)
        rows.append({"date": ds, "label": label, "nav": _r(P.nav_on(code, d), 4), "px": _r(px, 4),
                     "px_kind": "市价" if (not otc and has_live) else "净值",
                     "shares": _r(sh, 4), "mv": _r(mv), "base": _r(base),
                     "pnl": _r(pnl), "pct": (None if pct is None else _r(pct, 4)),
                     "fee": _r(fee_of.get(ds, 0.0)), "act": act, "state": state,
                     "_key": key})
        prev_mv = mv

    if period != "day":
        rows = _collapse(rows)

    for r in rows:
        r.pop("_key", None)

    return J({"code": code, "rows": rows, "period": period,
              "unit": P.holding(it).get("unit") or "份",
              "fee_total": _r(sum(fee_of.values())), "fee_kind": {k: _r(v) for k, v in fee_kind.items() if v},
              "px_date": (P.quote_at() or None) if has_live else None})


def _collapse(rows: list[dict]) -> list[dict]:
    """按 `_key` 把逐日行折成周/月/年：收益与费用求和，收益率用**期初占用资金**重算。

    - 分母取这一期**第一天**的 base（= 上期末市值 + 当天买入额），不是把每天的分母
      加起来 —— 那是「资金 × 天数」，会把一周的收益率摊成五分之一的日收益。
    - 期末状态取这一期最后一天的份额 / 净值 / 市价，否则「这周结束时手上多少」读不出来。
    """
    out: list[dict] = []
    for r in rows:
        if out and out[-1]["_key"] == r["_key"]:
            g = out[-1]
            g["pnl"] = round(float(g["pnl"] or 0) + float(r["pnl"] or 0), 2)
            g["fee"] = round(float(g["fee"] or 0) + float(r["fee"] or 0), 2)
            g["shares"], g["nav"], g["px"], g["mv"] = r["shares"], r["nav"], r["px"], r["mv"]
            g["date"] = r["date"]
            if r["act"]:
                g["act"] = r["act"] if g["act"] in ("", r["act"]) else f"{g['act']}/{r['act']}"
        else:
            out.append(dict(r))
    for g in out:
        b = float(g.get("base") or 0)
        g["pct"] = round(float(g["pnl"]) / b * 100, 4) if b > 0 else None
    return out


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
    # 画图用「只有真净值」的序列：面板 ffill 出来的今天不是今天的数据，
    # 画上去就是把昨天复制成今天（2026-11-18 用户要求）
    nv = P.nav_published(code)

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
    if view == "price":
        # 场内 ETF 的二级市场收盘价（data/price_*.csv）+ 今天这一笔实时价。
        # 场外基金没有这个序列 —— 申购赎回都按净值成交，前端会把这个页签藏掉，走不到这里。
        px = P.price_series_live(code)
        if len(px) < 2:
            return HTMLResponse(_frame_notice(
                "这只基金没有场内市价历史（场外按净值成交），看「净值走势」就行。"))
        hist = trend_chart_data(px)
        d = hist["日"]
        inner = trend_chart_html(d["labels"], d["prices"], d["windows"]["近1月"]["count"],
                                 rets=d["rets"], histories=hist, trades=trades,
                                 store="awTrend.fundPx", default_range="近1月", heading="",
                                 height=440, label="市价")
        return HTMLResponse(_frame_doc(inner, 700))
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


def _trade_strategy(b: dict, a: dict, skip: int | None = None) -> str:
    """这笔单是「跟随哪个策略」时下的 —— 换过策略以后还能回答当时的权重依据。

    2026-11-16 踩过的坑：账户只存一个 strategy 字段（当前值），换过策略就查不出
    之前的成交是按哪套权重下的，只能靠份额反推。所以每笔记一笔都存一份快照。
    优先级：前端显式传的 > 原来那笔的（编辑时保留，别把历史冲掉）> 账户当前策略。
    """
    if b.get("strategy"):
        return str(b["strategy"])
    if skip is not None:
        old = a.get("trades") or []
        if 0 <= skip < len(old) and old[skip].get("strategy"):
            return str(old[skip]["strategy"])
    return str(a.get("strategy") or "")


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
    return {"date": day, "side": side, "slot": slot, "code": code, "shares": round(shares, 4), "nav": nav, "fee": fee,
            "strategy": _trade_strategy(b, a, skip)}


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
        # strategy 是记这笔时快照下来的（老记录没有，留空让前端显示「未记录」）
        stg = str((raw[t["i"]] if 0 <= t["i"] < len(raw) else {}).get("strategy") or "")
        rows.append({**t, "unit": (f["unit"] if f else u), "close": t["i"] in closed, "strategy": stg,
                     "strategy_name": _strategy_name(stg) if stg else "",
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
            slots.append({"slot": HG.slot_label(P.holdings, it["slot"]), "now": _r(it["slot_w"] * 100),
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
    # 场内按现价算份数（溢价 / 折价时净值会算错手数）；取不到行情就退回净值，绝不因此拦单
    exch = [r["code"] for r in P.plan["rows"] if not HG.is_otc(r["f"])]
    prices = {}
    if amt > 0 and exch:
        try:
            from allweather import quote as QUOTE
            prices = {c: q["price"] for c, q in QUOTE.snapshot(exch).items() if q.get("ok") and q.get("price")}
        except Exception:  # noqa: BLE001
            prices = {}
    d = P.dca(amt, prices)
    d["rows"] = [r | {k: _r(r[k]) for k in ("want", "amount", "fee")} | {"qty": _r(r["qty"], 4), "w_tgt": _r(r["w_tgt"] * 100),
                                                                            "x": _r(r["x"] * 100), "px": _r(r["px"], 4)}
                 for r in d["rows"]]
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
def _note(w0: dict, w: dict, asset: str) -> str:
    b, f = float(w0.get(asset, 0) or 0), float(w.get(asset, 0) or 0)
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
    # 三个内置策略的权重都按**这个账户实际持有的基金**算，同时把项目默认标的的权重一起给出来，
    # 页面才能回答「换了 3 只基金以后权重到底差在哪」。
    ws, w0s, infos = {}, {}, {}
    for k in KEYS:
        w, w0, info = _w_full(k, a)
        ws[k], w0s[k], infos[k] = w, w0, info
    stg = a.get("strategy") or "B-Con"
    sub = infos.get(stg) or infos.get("B-Con") or {}
    assets = [x for x in ETF_META if any(x in STRATEGIES[k]["assets"] for k in KEYS)]
    rows = [{"asset": x, "name": ETF_META[x]["name"], "code": ETF_META[x]["code"],
             "mine": HG.SLOT_LABEL.get(x, "") if x in act else "",
             "w": {k: (None if x not in STRATEGIES[k]["assets"] else _r(float(ws[k].get(x, 0)) * 100))
                   for k in KEYS},
             "base": {k: (None if x not in STRATEGIES[k]["assets"] else _r(float(live["w"][k].get(x, 0)) * 100))
                      for k in KEYS},
             "note": {k: _note(w0s[k], ws[k], x) for k in KEYS}} for x in assets]
    slots = []
    for s in HG.slots_of(P.holdings):
        h = P.holdings.get(s, {})
        slots.append({"slot": s, "label": HG.slot_label(P.holdings, s), "on": bool(h.get("on", True)),
                      "funds": [{"code": f["code"], "name": f.get("name") or FL.fund_name(f["code"]) or f["code"],
                                 "unit": f.get("unit"), "share": _r(f.get("share") or 0, 4)} for f in HG.funds(h)]})
    return J({"account": _acct_info(aid, a), "strategies": [{"key": k, "name": STRAT_NAME[k]} for k in KEYS],
              "rows": rows, "slots": slots,
              # 当前策略的目标权重是拿哪些基金算的：used = 已按我的基金算，skipped = 仍用项目默认
              "sub": {"used": sub.get("used") or [], "skipped": sub.get("skipped") or []}})


@acct_view
async def switch_preview(request, aid, P, a):
    to = str(request.query_params.get("to") or "")
    rec = _strategy_rec(to)
    # 预览必须按「换过去之后」的位置体系算（和 set_strategy 同一个 _switch_holdings）：
    # 否则新基金那 30% 会被摊到别的位置上，笔数、卖出金额、清仓名单全跟真下出来的不一样。
    hs, added, opened, closed = _switch_holdings(a, to, P)
    # 权重也按「换过去之后的选基配置」算：内置策略的目标权重是拿我这个位置挂的基金序列算的，
    # 换策略会开关位置，用换之前的配置算出来的权重和真下出来的对不上。
    w_to, diag = strategy_weights(to, {**a, "holdings": hs})
    Q = Portfolio({**a, "holdings": hs}, w_to) if (added or opened or closed) else _portfolio(aid, target=to)[0]
    liq = [o for o in Q.plan["orders"] if o.get("liq")]
    # 目标为 0 的位置 = 换过去以后会被清掉的位置（原来只比内置策略的 assets 列表，
    # 自定义策略没有那张表，直接按算出来的权重看，逻辑反而更准）
    zero = [HG.slot_label(Q.holdings, s) for s in HG.active(Q.holdings)
            if float(Q.slot_w.get(s, 0) or 0) <= 0]
    unp = HG.unplaced_assets(w_to, Q.holdings)
    names = {k: v.get("name") or k for k, v in ((ST.fund_map(rec) if rec else {}) or {}).items()}
    return J({"to": to, "to_name": _strategy_name(to), "n_now": len(P.plan["orders"]), "n": len(Q.plan["orders"]),
              "buy": _r(Q.plan["buy"]), "sell": _r(Q.plan["sell"]),
              "liq": [{"name": FL.fund_name(o["code"]) or o["code"], "amount": _r(o["shares"] * o["nav"])} for o in liq],
              "zero": zero, "added": added, "diag": diag,
              "opened": [HG.slot_label(hs, s) for s in opened], "closed": [HG.slot_label(hs, s) for s in closed],
              "unplaced": [{"name": names.get(k) or ETF_META.get(k, {}).get("name", k),
                            "w": _r(float(w_to.get(k, 0)) * 100), "to": v} for k, v in unp.items()]})


@acct_view
async def set_strategy(request, aid, P, a):
    to = str((await request.json()).get("to") or "")
    hs, added, opened, closed = _switch_holdings(a, to, P)
    a["strategy"] = to
    a["holdings"] = hs
    AC.save(aid, a)
    with _LOCK:
        _P.clear()          # 账户文件变了，Portfolio 缓存全作废（含换策略后的旧对象）
    return J({"ok": True, "to": to, "to_name": _strategy_name(to), "added": added,
              "opened": opened, "closed": closed})


@acct_view
async def edit_holdings(request, aid, P, a):
    """选基配置：开关位置 / 加一只 / 删一只 / 改买卖单位 / 改位置内占比。"""
    b = await request.json()
    s, op = b.get("slot"), b.get("op")
    if s not in HG.slots_of(a.get("holdings") or {}):
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
        # 全历史跑权重、只在起点切净值（2026-11-14 用户：「2019 起回撤 3.6%、2020 起回撤 9%」）。
        # 原来先把行情截到起点再跑：30/75 日均线、20 日权重窗口全都从零攒，起点后两三个月过滤不生效，
        # 2020-01 起正好撞上 3 月疫情，标普 / 有色 / 能化满仓扛跌，风险平价回撤 -3.39% → -9.07%。
        rets = panel_returns(panel)
        s0 = pd.Timestamp(start)

        def _cut(r):
            nv = r.nv.loc[s0:]
            n_in = int((r.weight_df.index >= nv.index[0]).sum()) if r.weight_df is not None else int(r.n_rebal)
            return nv / float(nv.iloc[0]), n_in

        for n in names:
            r = run_strategy_backtest(rets, n, cad, track_weights=True)
            lbl = n if cad == "monthly" else f"{n} · {dict(biweekly='双周', weekly='每周')[cad]}"
            out[lbl] = _cut(r)
            if cad != "monthly":
                out[f"{n} · 月末"] = _cut(run_strategy_backtest(rets, n, track_weights=True))
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


def _same_day_premium(code: str) -> dict:
    """同一天口径的折溢价：最近一个有收盘价的交易日，收盘价 ÷ 同日净值 − 1。

    数据不全就返回空 dict，调用方保留 `quote.snapshot` 那份（页面照常显示，不空着）。
    """
    from allweather import quote as QUOTE

    try:
        px, nv = HG.price_series(code), HG.nav_series(code)
        if not len(px) or not len(nv):
            return {}
        px = px[~px.index.duplicated(keep="last")]
        nv = nv[~nv.index.duplicated(keep="last")]
        nv = nv.reindex(px.index).dropna()
        if not len(nv):
            return {}
        d = nv.index[-1]
        p, n = float(px.loc[d]), float(nv.loc[d])
        if p <= 0 or n <= 0:
            return {}
        prem = p / n - 1
        level, text = QUOTE.band(prem)
        return {"premium": round(prem, 5), "premium_date": f"{d:%Y-%m-%d}",
                "premium_price": round(p, 4), "premium_base": round(n, 4),
                "level": level, "level_text": text}
    except Exception:  # noqa: BLE001  算不出就退回实时价口径，不拦页面
        return {}


async def etf_premium(request: Request):
    """场内 ETF 的现价 / 最新净值 / 折溢价。codes 逗号分隔，不传就查默认那 9 只。

    溢价率一律用**小数**返回（0.1146 = 11.46%），格式化交给前端。

    **折溢价必须用同一天的两个价**：`snapshot` 里是「实时价 ÷ 最新净值」，而最新净值
    是上一交易日的（今天 21:00 后才出），于是今天的涨跌全被算进溢价 —— 511130 在
    11/17 盘中显示「溢价 +0.50%」，实际 11/16 收盘价 109.30 对净值 109.6706 是**折价
    0.34%**，差了 0.84pp（2026-11-17 用户截图里的徽标）。这里改用「最近同日收盘价 vs
    同日净值」：没有实时 IOPV 的情况下，这才是折溢价本身，不是「折溢价 + 今日涨跌」。
    """
    from allweather import quote as QUOTE
    codes = [c.strip() for c in (request.query_params.get("codes") or "").split(",") if c.strip()]
    if not codes:
        codes = [m["code"] for m in ETF_META.values()]
    rows = []
    for r in QUOTE.snapshot(codes).values():
        row = {**r, "price": _r(r["price"], 4), "nav": _r(r["nav"], 4),
               "chg": _r(r["chg"], 5), "premium": _r(r["premium"], 5)}
        for k, v in _same_day_premium(r["code"]).items():
            row[k] = v
        rows.append(row)
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


# ------------------------------------------------------------------ 自定义策略库
async def list_strategies(request: Request):
    """策略工厂保存的模板。前端拿它做「换策略」列表，实盘绑定时也按它算权重。"""
    rows = ST.load()
    return J({"rows": [{"id": r.get("id"), "name": r.get("name"), "method": r.get("method"),
                        "freq": r.get("freq"), "n_funds": len(r.get("funds") or []),
                        "updated": r.get("updated"), **r} for r in rows]})


async def save_strategy(request: Request):
    b = await request.json()
    try:
        rec = ST.upsert(b)
    except ValueError as e:
        return J({"error": str(e)}, 400)
    with _LOCK:
        _SW.clear()          # 策略改了，缓存的权重立刻作废
        _P.clear()
    return J({"ok": True, "strategy": rec})


async def delete_strategy(request: Request):
    sid = request.path_params["sid"]
    try:
        ST.delete(sid)
    except KeyError:
        return J({"error": "没有这条策略"}, 404)
    with _LOCK:
        _SW.clear()
        _P.clear()
    return J({"ok": True})


# ------------------------------------------------------------------ 更新数据（后台线程）
_UPD = {"running": False, "errors": [], "finished": 0.0, "started": 0.0}
# 看门狗上限：akshare 内部大量 requests 不带 timeout，网络一旦半通（比如走了一个不回包的代理），
# 更新线程会永久阻塞在 read 上，running 永远是 True。
UPD_TIMEOUT = 15 * 60


def _refresh_fund_nav() -> list[str]:
    """把账户里**场外**基金的净值缓存补到最新 —— 「更新数据」按钮的另一半。

    `fetch_all` / `update_nav_detail` 管的是行情和场内净值，场外基金的净值（fund_lookup
    那套 CSV）原来在任何按钮后面都没人拉：用户点无数次「更新数据」，000217 的净值还是
    三周前那份，图就一直是一条平线（2026-11-16）。有自带 nav_detail 的场内标直接跳过。
    """
    try:
        import fund_lookup as FL
    except Exception:  # noqa: BLE001
        return []
    codes: set[str] = set()
    for rec in AC.list_accounts():
        a = AC.load(rec["id"]) or {}
        codes |= {str(t.get("code") or "") for t in (a.get("trades") or [])}
        try:
            codes |= set(HG.all_codes(a.get("holdings") or {}))
        except Exception:  # noqa: BLE001  配置坏了不影响别的账户
            pass
    out, stuck = [], []
    for code in sorted(codes - {""}):
        if HG.nav_detail_series(code) is not None:      # 项目自带明细，归 update_nav_detail 管
            continue
        try:
            ok, msg = FL.ensure_fresh(code)
        except Exception as e:  # noqa: BLE001
            ok, msg = False, str(e)[:80]
        if not ok:
            stuck.append(f"{code} 净值没更新上：{msg[:80]}")
    out.extend(stuck)
    return out


def _do_update():
    try:
        from allweather.fetch import fetch_all, fetch_prices, update_nav_detail
        from allweather import valuation as V
        _ok, e1, _u = fetch_all(force=False, end=pd.Timestamp.today().strftime("%Y%m%d"))
        _pok, e2 = fetch_prices()
        _m, e3 = update_nav_detail()
        _vm, e4 = V.update_all()
        # 申购状态表（场内 / 场外计费、QDII 限购）和费率也挂在这个按钮上：用户只在网页操作，不跑命令。
        # 单独 try：它们失败不影响行情更新，只在按钮的红字里报一条
        e5 = []
        try:
            from allweather import fees as FEES
            FEES.refresh_purchase_if_stale()
            FEES._PURCHASE = None
            FEES.refresh(force=False)           # 只补缺失 / 超过 30 天的
        except Exception as e:  # noqa: BLE001
            e5 = [f"申购状态 / 费率没更新上：{str(e)[:120]}（不影响行情，下次再点一次）"]
        # 场外基金净值：上面四步都不碰它，单独一步补
        e6 = _refresh_fund_nav()
        _UPD["errors"] = list(e1) + list(e2) + list(e3) + list(e4) + e5 + e6
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


async def selftest(request: Request):
    """自检：把「页面上的数对不对」的硬约束一次查完，给红/黄/绿。

    与 `scripts/doctor.py` 同一份逻辑（`allweather/selfcheck.py`）——
    页面上觉得不对就先调这个，不用再猜是数据没拉到还是缓存没失效。
    """
    from allweather import selfcheck

    aid = request.query_params.get("acct") or AC.last() or "main"
    a = AC.load(aid) or {}
    try:
        P = _portfolio(aid)[0]
        return J(selfcheck.run(P, a))
    except Exception as e:  # noqa: BLE001  账户算不出来时也要把净值/行情查完
        return J(selfcheck.run(None, a, error=str(e)))


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
    Route("/api/acct/{aid}/holding/{code}/daily", holding_daily),
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
    Route("/api/strategies", list_strategies),
    Route("/api/strategies", save_strategy, methods=["POST"]),
    Route("/api/strategies/{sid}", delete_strategy, methods=["DELETE"]),
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
    Route("/api/selftest", selftest),
]
if (DIST / "assets").exists():
    routes.append(Mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets"))
routes.append(Route("/{path:path}", spa))


def _warm_up() -> None:
    """启动后先在后台把默认账户算一遍。

    ① 策略权重和净值面板首算 2 秒多，不预热就是「刚启动那次打开特别慢」；
    ② 顺便**同步**拉一次场内现价（2~3 秒）。估值要用市价，而 `spots_now` 是非阻塞的：
       不先把缓存填上，第一个请求构造出来的 plan 就是净值口径，得等下一次重建才对
       （2026-11-16 用户「打开页面很慢」+「怎么还是净值」都是这个链条）。
    """
    try:
        aid = AC.last() or "main"
        a = AC.load(aid) or {}
        codes = sorted({str(t.get("code") or "") for t in (a.get("trades") or [])} - {""})
        if codes:
            try:
                from allweather import quote as QUOTE
                QUOTE.snapshot(codes)
            except Exception:  # noqa: BLE001  行情慢就慢点，不影响账户计算
                pass
        _portfolio(aid)
    except Exception:  # noqa: BLE001  预热失败不影响正事
        pass


@asynccontextmanager
async def _lifespan(_app):
    threading.Thread(target=_warm_up, daemon=True, name="aw-warmup").start()
    yield


app = Starlette(routes=routes, middleware=[Middleware(Auth)], lifespan=_lifespan)
