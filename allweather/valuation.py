"""指数估值数据：两个来源，各管一件事，不混用。

1. 策略信号用（乐咕乐股，akshare stock_index_pe_lg / stock_index_pb_lg）
   - 写入 data/hs300_pe.csv、data/hs300_pb.csv，列名与历史文件一致（已核对重叠 255 天差值 0）。
   - 回测和实盘的 HS300 抄底信号（PB<30%ile 入场 / PE>70%ile 出场）只读这两个文件。

2. 估值展示用（蛋卷基金公开接口，与 etf-dashboard-auto 同源）
   - 快照：https://danjuanapp.com/djapi/index_eva/dj  → 63 个指数的 PE/PB/百分位/股息率/ROE/估值档
   - 历史：.../index_eva/{pe|pb}_history/{code}?day=all → 近 10 年周频 PE/PB
   - 写入 data/valuation/，只用于「估值」页和基金走势页的估值标签，**不进入策略计算**
     （口径不同：沪深300 蛋卷 PB 百分位 26.8% vs 策略口径 72.2%）。
   - 非官方文档接口，可能改版；拉取失败时页面继续用本地缓存。
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

from .config import DATA_DIR

VAL_DIR = DATA_DIR / "valuation"
SNAP_JSON = VAL_DIR / "danjuan_snapshot.json"     # 最新一次快照（原样保存）
SNAP_LOG = VAL_DIR / "danjuan_snapshots.csv"      # 每日快照累积（自己攒历史）
HIST_DIR = VAL_DIR / "history"                    # 每个指数一份 PE/PB 历史
PRICE_DIR = VAL_DIR / "price"                     # 每个指数一份点位（算近10年回撤用）

_DJ = "https://danjuanapp.com/djapi/index_eva"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Referer": "https://danjuanapp.com/"}

# 指数代码 → 市场分组（用于估值页筛选）
_HK = {"HKHSTECH", "HKHSI", "HKHSCEI", "HKHSSCNE", "HSFML25", "SPHCMSHP"}
_OVERSEA = {"SP500", "NDX", "GDAXI", "SPACEVCP", "SPCQVCP", "CSPSADRP", "935600"}
_CN_OVERSEA = {"CSIH30533", "CSIH11136", "CSI716567"}   # 中概/中国互联/MSCI中国

# 本项目资产 / 常见基金 → 蛋卷指数代码（基金走势页估值标签用）
ASSET_INDEX = {"hs300": "SH000300", "us_sp500": "SP500"}
FUND_INDEX = {
    "510300": "SH000300", "159919": "SH000300", "460300": "SH000300", "006131": "SH000300",
    "000051": "SH000300", "110020": "SH000300", "100038": "SH000300",
    "513500": "SP500", "161125": "SP500", "050025": "SP500", "021277": None,
    "513100": "NDX", "159941": "NDX", "016452": "NDX", "019441": "NDX", "539001": "NDX", "040046": "NDX",
    "510500": "SH000905", "159922": "SH000905", "512170": "SZ399989", "159915": "SZ399006",
    "588000": "SH000688", "512880": "SZ399975", "515180": "SH000922", "513050": "CSIH30533",
    "513180": "HKHSTECH", "159920": "HKHSI", "512980": "SZ399971", "159928": "SH000932",
}
# 名称关键词兜底匹配（按顺序，先具体后宽泛）
_NAME_RULES = [
    ("纳斯达克", "NDX"), ("纳指", "NDX"), ("标普500", "SP500"), ("标普 500", "SP500"),
    ("恒生科技", "HKHSTECH"), ("恒生指数", "HKHSI"), ("中概互联", "CSIH30533"),
    ("沪深300", "SH000300"), ("沪深 300", "SH000300"), ("中证500", "SH000905"), ("中证1000", "SH000852"),
    ("创业板", "SZ399006"), ("科创50", "SH000688"), ("上证50", "SH000016"), ("中证红利", "SH000922"),
    ("红利低波", "CSIH30269"), ("中证医疗", "SZ399989"), ("中证白酒", "SZ399997"), ("证券公司", "SZ399975"),
    ("中证银行", "SZ399986"), ("中证军工", "SZ399967"), ("德国", "GDAXI"),
]


def market_of(code: str) -> str:
    if code in _OVERSEA:
        return "海外"
    if code in _HK:
        return "港股"
    if code in _CN_OVERSEA:
        return "中概"
    return "A股"


# ---------------------------------------------------------------------------
# 1) 策略用：沪深300 PE/PB（乐咕乐股）
# ---------------------------------------------------------------------------
def update_hs300_pe_pb() -> tuple[list[str], list[str]]:
    """增量更新 data/hs300_pe.csv / hs300_pb.csv。返回 (成功说明, 错误)。"""
    import akshare as ak
    msgs, errs = [], []
    jobs = [
        ("hs300_pe.csv", lambda: ak.stock_index_pe_lg(symbol="沪深300"), None),
        ("hs300_pb.csv", lambda: ak.stock_index_pb_lg(symbol="沪深300"),
         {"日期": "date", "指数": "index", "市净率": "pb", "等权市净率": "pb_weighted", "市净率中位数": "pb_median"}),
    ]
    for fname, fetch, rename in jobs:
        path = DATA_DIR / fname
        try:
            new = fetch()
            if new is None or (hasattr(new, "empty") and new.empty):
                # 数据源返回空（akshare 接口变更 / 沙箱无外网）：本地有数据就沿用，不弹红字
                if path.exists():
                    _old = pd.read_csv(path)
                    _last = pd.to_datetime(_old[_old.columns[0]]).max()
                    msgs.append(f"{fname} 源暂不可用，沿用本地至 {_last:%Y/%m/%d}")
                else:
                    errs.append(f"{fname}: 源返回空且无本地数据")
                continue
            if rename:
                new = new.rename(columns=rename)
            date_col = new.columns[0]
            new[date_col] = pd.to_datetime(new[date_col])
            if path.exists():
                old = pd.read_csv(path)
                old[old.columns[0]] = pd.to_datetime(old[old.columns[0]])
                if list(old.columns) != list(new.columns):
                    errs.append(f"{fname}: 接口列名变化 {list(new.columns)}，已拒绝写入")
                    continue
                add = new[new[date_col] > old[date_col].max()]
                if add.empty:
                    msgs.append(f"{fname} 已最新（至 {old[date_col].max():%Y/%m/%d}）")
                    continue
                out = pd.concat([old, add], ignore_index=True)
            else:
                out, add = new, new
            out = out.drop_duplicates(subset=date_col, keep="last").sort_values(date_col)
            out[date_col] = out[date_col].dt.strftime("%Y-%m-%d")
            out.to_csv(path, index=False)
            msgs.append(f"{fname} +{len(add)} 行（至 {pd.Timestamp(out[date_col].iloc[-1]):%Y/%m/%d}）")
        except Exception as e:  # noqa: BLE001
            # 数据源不可用（akshare 接口变更 / 沙箱无外网）时降级为沿用本地，避免红字告警
            if path.exists():
                _old = pd.read_csv(path)
                _last = pd.to_datetime(_old[_old.columns[0]]).max()
                msgs.append(f"{fname} 源暂不可用，沿用本地至 {_last:%Y/%m/%d}")
            else:
                errs.append(f"{fname}: {str(e).splitlines()[0][:120]}")
    return msgs, errs


# ---------------------------------------------------------------------------
# 2) 展示用：蛋卷估值快照 + 历史
# ---------------------------------------------------------------------------
def _get(url: str) -> dict:
    last = None
    for i in range(3):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=20)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1 + i)
    raise RuntimeError(str(last))


def fetch_snapshot() -> pd.DataFrame:
    items = _get(f"{_DJ}/dj")["data"]["items"]
    VAL_DIR.mkdir(parents=True, exist_ok=True)
    SNAP_JSON.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    df = _snapshot_frame(items)
    # 每日快照累积：同一数据日只保留一份
    log = df.assign(抓取=pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"))
    if SNAP_LOG.exists():
        old = pd.read_csv(SNAP_LOG, dtype={"代码": str})
        log = pd.concat([old, log], ignore_index=True).drop_duplicates(subset=["数据日", "代码"], keep="last")
    log.to_csv(SNAP_LOG, index=False, encoding="utf-8-sig")
    return df


def _snapshot_frame(items: list[dict]) -> pd.DataFrame:
    rows = []
    for it in items:
        code = str(it.get("index_code", ""))
        pe = it.get("pe")
        rows.append({
            "代码": code, "名称": it.get("name", ""), "市场": market_of(code),
            "PE": pe if pe and pe > 0 else None,
            "PE百分位": (it.get("pe_percentile") or 0) * 100 if pe and pe > 0 else None,
            "PB": it.get("pb"), "PB百分位": (it.get("pb_percentile") or 0) * 100,
            "股息率": (it.get("yeild") or 0) * 100, "ROE": (it.get("roe") or 0) * 100,
            "估值": {"low": "低估", "mid": "适中", "high": "高估"}.get(it.get("eva_type"), "—"),
            "数据日": pd.to_datetime(it.get("ts"), unit="ms").strftime("%Y-%m-%d") if it.get("ts") else "",
        })
    return pd.DataFrame(rows)


def load_snapshot() -> pd.DataFrame:
    """读本地快照（不发请求）；没有则返回空表。"""
    if not SNAP_JSON.exists():
        return pd.DataFrame()
    return _snapshot_frame(json.loads(SNAP_JSON.read_text(encoding="utf-8")))


def _fetch_history(code: str) -> pd.DataFrame:
    parts = []
    for k in ("pe", "pb"):
        lst = _get(f"{_DJ}/{k}_history/{code}?day=all")["data"][f"index_eva_{k}_growths"]
        d = pd.DataFrame(lst)
        if d.empty:
            continue
        d["date"] = pd.to_datetime(d["ts"], unit="ms").dt.normalize()
        parts.append(d.set_index("date")[[k]])
    out = pd.concat(parts, axis=1).sort_index() if parts else pd.DataFrame()
    if not out.empty:
        HIST_DIR.mkdir(parents=True, exist_ok=True)
        out.reset_index().assign(date=lambda x: x["date"].dt.strftime("%Y-%m-%d")).to_csv(HIST_DIR / f"{code}.csv", index=False)
    return out


def load_history(code: str) -> pd.DataFrame:
    """读本地 PE/PB 历史（周频，index=date，列 pe/pb）；没有返回空表。"""
    p = HIST_DIR / f"{code}.csv"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()


def update_danjuan(workers: int = 8) -> tuple[list[str], list[str]]:
    """拉蛋卷快照 + 全部指数历史（有界并发，约 10 秒）。当天已拉过则跳过历史。"""
    msgs, errs = [], []
    try:
        snap = fetch_snapshot()
        msgs.append(f"估值快照 {len(snap)} 个指数（数据日 {pd.Timestamp(snap['数据日'].max()):%Y/%m/%d}）")
    except Exception as e:  # noqa: BLE001
        return msgs, [f"蛋卷估值快照: {str(e)[:120]}"]
    import datetime as _dt
    today = _dt.date.today()
    todo = [c for c in snap["代码"]
            if not (HIST_DIR / f"{c}.csv").exists()
            or _dt.date.fromtimestamp((HIST_DIR / f"{c}.csv").stat().st_mtime) != today]
    if not todo:
        msgs.append("估值历史今日已更新")
        return msgs, errs
    fails = []

    def one(code):
        try:
            _fetch_history(code)
        except Exception as e:  # noqa: BLE001
            fails.append(f"{code}: {str(e)[:60]}")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, todo))
    msgs.append(f"估值历史 {len(todo) - len(fails)}/{len(todo)} 个指数")
    if fails:
        errs.append(f"估值历史失败 {len(fails)} 个：" + "；".join(fails[:3]))
    return msgs, errs


# ---------------------------------------------------------------------------
# 3) 指数点位 → 近10年回撤 + 评分（口径与 etf-dashboard-auto 一致）
# ---------------------------------------------------------------------------
_US = {"SP500": ".INX", "NDX": ".NDX"}
import threading as _th
_SINA_LOCK = _th.Lock()   # 新浪行情接口内部用 mini_racer(V8) 解码，多线程同时调用会直接崩进程 → 串行


def _fetch_index_price(code: str) -> pd.DataFrame:
    """按指数代码路由到可用的 akshare 行情源，返回 date/close。拿不到抛异常。"""
    import akshare as ak

    def csi(sym):
        start = (pd.Timestamp.today() - pd.DateOffset(years=11)).strftime("%Y%m%d")
        d = ak.stock_zh_index_hist_csindex(symbol=sym, start_date=start, end_date=pd.Timestamp.today().strftime("%Y%m%d"))
        return pd.DataFrame({"date": pd.to_datetime(d["日期"]), "close": pd.to_numeric(d["收盘"], errors="coerce")})

    if code.startswith(("SH", "SZ")):
        with _SINA_LOCK:
            d = ak.stock_zh_index_daily(symbol=code.lower())
        d = pd.DataFrame({"date": pd.to_datetime(d["date"]), "close": pd.to_numeric(d["close"], errors="coerce")})
        # 新浪部分中证指数停更在 2019 年 → 改用中证官网
        if d["date"].max() < pd.Timestamp.today() - pd.Timedelta(days=30):
            d = csi(code[2:])
        return d
    if code.startswith("CSIH"):
        return csi("H" + code[4:])
    if code.startswith("CSI"):
        return csi(code[3:])
    if code.startswith("HK"):
        with _SINA_LOCK:
            d = ak.stock_hk_index_daily_sina(symbol=code[2:])
        return pd.DataFrame({"date": pd.to_datetime(d["date"]), "close": pd.to_numeric(d["close"], errors="coerce")})
    if code in _US:
        with _SINA_LOCK:
            d = ak.index_us_stock_sina(symbol=_US[code])
        return pd.DataFrame({"date": pd.to_datetime(d["date"]), "close": pd.to_numeric(d["close"], errors="coerce")})
    raise RuntimeError("暂无行情源")


def update_index_prices(codes, workers: int = 6) -> tuple[list[str], list[str]]:
    """拉全部指数点位（当天已拉过的跳过）。失败的只记录，不影响其他。"""
    import datetime as _dt
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    today = _dt.date.today()
    todo = [c for c in codes if not (PRICE_DIR / f"{c}.csv").exists()
            or _dt.date.fromtimestamp((PRICE_DIR / f"{c}.csv").stat().st_mtime) != today]
    fails = []

    def one(code):
        try:
            d = _fetch_index_price(code).dropna().sort_values("date")
            d.assign(date=d["date"].dt.strftime("%Y-%m-%d")).to_csv(PRICE_DIR / f"{code}.csv", index=False)
        except Exception as e:  # noqa: BLE001
            fails.append(f"{code}: {str(e).splitlines()[0][:50]}")

    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(one, todo))
    msgs = [f"指数点位 {len(todo) - len(fails)}/{len(todo)} 个" if todo else "指数点位今日已更新"]
    # 已知没有行情源的指数（海外风格指数、MSCI、部分港股）每次都会缺，属正常情况，不算拉取失败
    known = {"HSFML25", "SPACEVCP", "CSPSADRP", "CSI716567", "SPCQVCP", "SPHCMSHP", "GDAXI", "935600"}
    unexpected = [f for f in fails if f.split(":")[0] not in known]
    if len(fails) > len(unexpected):
        msgs.append(f"{len(fails) - len(unexpected)} 个指数暂无行情源（回撤显示 —）")
    return msgs, ([f"指数点位拉取失败 {len(unexpected)} 个：" + "；".join(unexpected[:3])] if unexpected else [])


def drawdown_10y(code: str) -> float | None:
    """当前点位距近10年最高点的跌幅（0~1）。数据不足 2 年返回 None（窗口太短的回撤没有可比性）。"""
    p = PRICE_DIR / f"{code}.csv"
    if not p.exists():
        return None
    d = pd.read_csv(p, parse_dates=["date"]).dropna().sort_values("date").set_index("date")["close"]
    if d.empty or (d.index[-1] - d.index[0]).days < 730:
        return None
    w = d[d.index >= d.index[-1] - pd.DateOffset(years=10)]
    return float(max(0.0, 1 - w.iloc[-1] / w.max()))


RATING_BUCKETS = [(18, "猎杀区"), (14, "稳中求胜"), (10, "中性观察"), (6, "高位警戒"), (0, "泡沫区")]


def score(pe_pct, pb_pct, dd):
    """综合评分（满分 20），完全沿用 etf-dashboard-auto：
    - 估值分 0~12 = round((100 − max(PE百分位, PB百分位)) / 8)，缺 PE/PB 按 100% 计（无法判断便宜）
    - 回撤分 0~8  = round(近10年回撤 × 16)，即回撤 50% 封顶
    返回 (总分, 估值分, 回撤分, 档位)；回撤缺失时回撤分记 0。
    """
    vp = max(pe_pct if pe_pct is not None and pd.notna(pe_pct) else 100.0,
             pb_pct if pb_pct is not None and pd.notna(pb_pct) else 100.0)
    vs = int(min(12, max(0, round((100 - vp) / 8))))
    ps = int(min(8, max(0, round((dd or 0.0) * 16))))
    total = vs + ps
    label = next(lb for mn, lb in RATING_BUCKETS if total >= mn)
    return total, vs, ps, label


def update_all() -> tuple[list[str], list[str]]:
    """「更新数据」按钮里与行情一起调用：策略用 PE/PB + 展示用蛋卷估值。"""
    m1, e1 = update_hs300_pe_pb()
    m2, e2 = update_danjuan()
    snap = load_snapshot()
    m3, e3 = update_index_prices(list(snap["代码"])) if not snap.empty else ([], [])
    return m1 + m2 + m3, e1 + e2 + e3


def index_for_fund(code: str | None, name: str = "", asset: str | None = None) -> str | None:
    """基金/资产 → 蛋卷指数代码（只对指数型能对应上的返回，主动管理型返回 None）。"""
    if asset and asset in ASSET_INDEX:
        return ASSET_INDEX[asset]
    if code and code in FUND_INDEX:
        return FUND_INDEX[code]
    if name and ("指数" in name or "ETF" in name or "联接" in name or "LOF" in name):
        for kw, idx in _NAME_RULES:
            if kw in name:
                return idx
    return None
