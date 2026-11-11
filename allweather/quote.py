"""场内 ETF 的现价 / 最新净值 / 溢价率 —— 只服务于「买之前值不值这个价」。

溢价率 = 场内现价 ÷ 最新公布单位净值 − 1。

**为什么是估算值，不是交易所 IOPV**：东财行情接口的 IOPV 字段（f78）恒为空，
新浪行情也不带，项目里没有第二个实时源。所以这里用「现价 ÷ 最新单位净值」：
- 对可申购的 ETF，套利盘会把溢价压回 0 附近，估算值和真实 IOPV 差不了几个 bp，
  用来做「买之前别追高」的提示够了；
- 对**暂停申购**的 QDII（513500 这类），套利通道是断的，溢价可以长期挂着；
  它的净值还常滞后 1 天（QDII 结算慢），所以估算值只当量级参考，页面必须把 nav_date 显示出来。

数据源（都给「最近一页」，不拉历史）：
- 现价：``push2.eastmoney.com/api/qt/ulist.np/get``，``fltt=2`` 直接返回浮点，
  一次最多几十只，10 只 ETF 一个请求搞定；
- 净值：``api.fund.eastmoney.com/f10/lsjz``，一页 20 条按日期倒序，取第一条的 DWJZ。

缓存：现价 30 秒、净值 10 分钟、取失败 5 分钟（失败也要缓存，否则断网时每次切页都卡超时）。
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}
_NAV_UA = {**_UA, "Referer": "https://fundf10.eastmoney.com/"}
_SINA_UA = {**_UA, "Referer": "https://finance.sina.com.cn/"}
_EM_QUOTE = "https://push2.eastmoney.com/api/qt/ulist.np/get"
_EM_NAV = "https://api.fund.eastmoney.com/f10/lsjz"

SPOT_TTL = 30.0      # 现价：秒级够用，切页不重复打接口
NAV_TTL = 600.0      # 净值：一天一个，10 分钟刷一次不影响判断
FAIL_TTL = 300.0     # 失败也别立刻重试，断网时不能把页面拖住

# 溢价分档：阈值从高到低排，(下限, key, 文案)。用于「买入提示」的颜色与阻断级别。
BANDS = (
    (0.05, "block", "溢价过高"),
    (0.03, "high", "溢价偏高"),
    (0.02, "warn", "溢价略高"),
)
OK, DISCOUNT = "ok", "折价"

_lock = threading.Lock()
_spot: dict[str, tuple[float, dict | None]] = {}
_nav: dict[str, tuple[float, dict | None]] = {}


def secid(code: str) -> str:
    """东财 secid：沪市 1.、深市 0.（5 开头是沪基，15/16 开头是深基）。"""
    return ("1." if code.startswith("5") else "0.") + code


def band(premium: float | None) -> tuple[str, str]:
    """溢价率 → (级别, 文案)。负溢价叫折价 —— 对买方是好事，不该报警。"""
    if premium is None:
        return OK, "—"
    if premium <= -0.01:
        return OK, "折价"
    for lo, key, text in BANDS:
        if premium >= lo:
            return key, text
    return OK, "正常"


def _get(url: str, params: dict, headers: dict, timeout: float = 6.0):
    r = requests.get(url, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _retry(fn, n: int = 3, wait: float = 0.3):
    """本机走代理，东财 push2 偶发 ProxyError（RemoteDisconnected）；一次失败不代表接口挂了。"""
    last = None
    for i in range(n):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(wait * (i + 1))
    raise last


def _spots_em(codes: list[str]) -> dict[str, dict]:
    j = _get(_EM_QUOTE, {"secids": ",".join(secid(c) for c in codes),
                         "fields": "f12,f14,f2,f3,f18", "fltt": "2", "invt": "2",
                         "_": int(time.time() * 1000)}, _UA)
    out = {}
    for d in ((j.get("data") or {}).get("diff") or []):
        px = d.get("f2")
        if not isinstance(px, (int, float)) or px <= 0:
            continue                      # 停牌 / 无报价，"-" 会走到这里
        out[str(d["f12"])] = {"name": d.get("f14"), "price": float(px),
                              "chg": float(d["f3"]) / 100 if isinstance(d.get("f3"), (int, float)) else None,
                              "prev": float(d["f18"]) if isinstance(d.get("f18"), (int, float)) else None}
    if not out:
        raise RuntimeError("东财无报价")
    return out


def _spots_sina(codes: list[str]) -> dict[str, dict]:
    """兜底行情。字段：0 名称 / 1 今开 / 2 昨收 / 3 现价（不带涨跌幅，自己按昨收算）。"""
    sym = ",".join(("sh" if c.startswith("5") else "sz") + c for c in codes)
    r = requests.get("https://hq.sinajs.cn/list=" + sym, headers=_SINA_UA, timeout=6)
    r.raise_for_status()
    r.encoding = "gbk"
    out = {}
    for line in r.text.splitlines():
        if '="' not in line:
            continue
        code = line.split("hq_str_", 1)[-1].split("=", 1)[0][-6:]
        f = line.split('="', 1)[1].rstrip('";').split(",")
        if len(f) < 4:
            continue
        try:
            px, prev = float(f[3]), float(f[2])
        except ValueError:
            continue
        if px <= 0:
            continue
        out[code] = {"name": f[0], "price": px, "prev": prev or None,
                     "chg": (px / prev - 1) if prev else None}
    if not out:
        raise RuntimeError("新浪无报价")
    return out


def _spots(codes: list[str]) -> dict[str, dict]:
    """一次请求拿全部现价。东财挂了用新浪补，两路都没响应才算失败。"""
    if not codes:
        return {}
    got: dict[str, dict] = {}
    try:
        got.update(_retry(lambda: _spots_em(codes)))
    except Exception:  # noqa: BLE001
        pass
    miss = [c for c in codes if c not in got]
    if miss:
        try:
            got.update(_retry(lambda: _spots_sina(miss), n=2))
        except Exception:  # noqa: BLE001
            pass
    if not got:
        raise RuntimeError("现价两路都取不到")
    return got


def _navs(codes: list[str]) -> dict[str, dict]:
    """一码一请求，取最近一页的第一条。并发跑，10 只约 1 秒。"""
    def one(code: str):
        def hit():
            j = _get(_EM_NAV, {"fundCode": code, "pageIndex": "1", "pageSize": "20",
                               "_": int(time.time() * 1000)}, _NAV_UA)
            rows = ((j.get("Data") or {}).get("LSJZList")) or []
            if not rows:
                raise RuntimeError("无净值")
            return {"nav": float(rows[0]["DWJZ"]), "nav_date": str(rows[0]["FSRQ"])[:10]}
        try:
            return code, _retry(hit, n=2)
        except Exception:  # noqa: BLE001
            return code, None

    with ThreadPoolExecutor(max_workers=8) as ex:
        return dict(ex.map(one, codes))


def snapshot(codes: list[str]) -> dict[str, dict]:
    """code → {name, price, chg, prev, nav, nav_date, premium, level, level_text, ok}。

    取不到就返回 ok=False 的占位，调用方（页面）不显示溢价、也绝不因此拦住买入。
    """
    codes = [str(c) for c in dict.fromkeys(codes) if c]
    now = time.time()
    with _lock:
        need_spot = [c for c in codes if now - _spot.get(c, (0.0, None))[0] >= SPOT_TTL]
        need_nav = [c for c in codes if now - _nav.get(c, (0.0, None))[0] >= NAV_TTL]

    # 失败也写回缓存，但把时间戳往前挪，等于把 TTL 拉长到 FAIL_TTL —— 断网时不会每次切页都等超时
    def store(box: dict, ttl: float, keys: list[str], fetch) -> None:
        if not keys:
            return
        try:
            got, stamp = fetch(keys), now
        except Exception:  # noqa: BLE001
            got, stamp = {k: None for k in keys}, now - (FAIL_TTL - ttl)
        with _lock:
            for c in keys:
                box[c] = (stamp, got.get(c))

    store(_spot, SPOT_TTL, need_spot, _spots)
    store(_nav, NAV_TTL, need_nav, _navs)

    out = {}
    with _lock:
        for c in codes:
            s = (_spot.get(c) or (0, None))[1]
            n = (_nav.get(c) or (0, None))[1]
            row = {"code": c, "name": (s or {}).get("name"), "price": (s or {}).get("price"),
                   "chg": (s or {}).get("chg"), "nav": (n or {}).get("nav"),
                   "nav_date": (n or {}).get("nav_date"), "premium": None,
                   "level": "na", "level_text": "—", "ok": bool(s and n)}
            if row["ok"] and row["nav"]:
                p = row["price"] / row["nav"] - 1.0
                row["premium"] = round(p, 5)
                row["level"], row["level_text"] = band(p)
            out[c] = row
    return out


def premium_of(code: str) -> dict | None:
    """单只的溢价信息，取不到返回 None（页面据此决定是否显示这一行）。"""
    r = snapshot([code]).get(str(code))
    return r if r and r.get("ok") else None
