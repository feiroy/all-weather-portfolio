"""基金费率（申购 / 赎回 / 场内佣金）—— 一次性抓取、落盘缓存、全站共用一份。

数据来源（天天基金）：
- 申购费率：``fundmobapi.eastmoney.com/FundMApi/FundBaseTypeInformation.ashx``
  返回 ``RATE``（优惠后，如 0.10%）与 ``SOURCERATE``（原价，如 1.00%）。
- 赎回费率：``fundf10.eastmoney.com/jjfl_<code>.html`` 的「赎回费率」表，
  按持有期分档（如「小于7天 1.50%」「大于等于7天 0.05%」）。

场内 ETF/LOF（代码 5/1 开头）没有申购赎回费，收佣金：默认万 1.5、每笔最低 5 元。

用法：
    python -m allweather.fees              # 刷新 data/fund_fees.json（幂等，只补缺失/过期）
    python -m allweather.fees --refresh     # 强制全部重抓
    python -m allweather.fees --show        # 打印当前缓存
    python -m allweather.fees --purchase    # 重抓全市场申购状态表（场内/场外判定、QDII 限购）
"""
from __future__ import annotations

import json
import re
import time
from datetime import date
from pathlib import Path

import requests

from .config import ROOT, ETF_META

CACHE = ROOT / "data" / "fund_fees.json"
CACHE_DAYS = 30                 # 费率变动很慢，一个月刷一次足够

# 场内：佣金万 1.5、单笔最低 5 元（券商普遍口径）
COMMISSION_RATE = 1.5e-4
COMMISSION_MIN = 5.0

_UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://fundf10.eastmoney.com/"}


_PURCHASE: dict | None = None


def _purchase_status() -> dict:
    """代码 → (申购状态, 赎回状态)，来自全市场申购状态表（fund_lookup.PURCHASE_CSV）。取不到返回空表。"""
    global _PURCHASE
    if _PURCHASE is not None:
        return _PURCHASE
    out: dict = {}
    try:
        import sys
        ss = str(ROOT / "streamlit_app")
        if ss not in sys.path:
            sys.path.insert(0, ss)
        import fund_lookup as FL  # noqa: PLC0415
        import pandas as pd  # noqa: PLC0415
        if FL.PURCHASE_CSV.exists():
            d = pd.read_csv(FL.PURCHASE_CSV, dtype=str, usecols=["基金代码", "申购状态", "赎回状态"])
            out = {str(r[0]).strip(): (str(r[1] or ""), str(r[2] or "")) for r in d.itertuples(index=False)}
    except Exception:  # noqa: BLE001 —— 没有状态表就退回代码前缀规则
        out = {}
    _PURCHASE = out
    return out


def is_exchange(code: str) -> bool:
    """按「场内买卖、收佣金」计费吗？

    原来只看首位「1/5 开头 = 场内」，把 110020（易方达沪深300联接）、519xxx、LOF 场外申购
    全算成「万 1.5 佣金、最低 5 元」，申购费和赎回阶梯一概不收（2026-11-14 用户要用场外基金
    实盘对比网页时发现）。现在先查全市场申购状态表：申购或赎回状态是「场内交易」才算场内；
    在表里但不是场内交易（含 LOF 在 App 里申购）一律按场外。表里查不到才退回代码前缀：
    159xxx（深 ETF）与 51/52/56/58 开头（沪 ETF，519 除外）。
    """
    c = str(code or "").strip()
    if len(c) != 6:
        return False
    st = _purchase_status().get(c)
    if st is not None:
        return "场内交易" in st[0] or "场内交易" in st[1]
    return c.startswith("159") or (c[:2] in ("51", "52", "56", "58") and not c.startswith("519"))


def _pct(s) -> float | None:
    """'0.10%' → 0.001；空/异常 → None。"""
    if s is None:
        return None
    m = re.search(r"([\d.]+)\s*%", str(s))
    return round(float(m.group(1)) / 100, 6) if m else None


_UNIT_DAYS = {"天": 1, "日": 1, "个月": 30, "月": 30, "年": 365}
_COND = re.compile(r"(大于等于|大于|小于等于|小于|≥|>|≤|<)\s*(\d+(?:\.\d+)?)\s*(个月|天|日|月|年)?")


def _parse_cond(cond: str) -> tuple[int, int | None] | None:
    """「大于等于7天，小于30天」→ (7, 30)，区间左闭右开、单位换成天；认不出返回 None。

    原解析只取第一个数字：丢了上限（≥7 天 0.10% 被当成永远 0.10%），也不认「年/月」
    （「大于等于1年」被当成 1 天）。2026-11-14 修。
    """
    lo, hi, hit = 0, None, False
    for op, num, unit in _COND.findall(cond):
        n = float(num) * _UNIT_DAYS.get(unit or "天", 1)
        hit = True
        if op in ("大于等于", "≥"):
            lo = int(round(n))
        elif op in ("大于", ">"):
            lo = int(round(n)) + 1
        elif op in ("小于等于", "≤"):
            hi = int(round(n)) + 1
        else:
            hi = int(round(n))
    return (lo, hi) if hit else None


def _parse_redeem(html: str) -> list[dict]:
    """从费率页解析赎回费阶梯 → [{'min_days': 0, 'max_days': 7, 'rate': 0.015}, ...]（按 min_days 升序）。"""
    i = html.find("赎回费率")
    if i < 0:
        return []
    seg = html[i:i + 4000]
    rows = re.findall(r"<tr><td>(.*?)</td><td>(.*?)</td></tr>", seg, re.S)
    out = []
    for cond, rate in rows:
        cond = re.sub(r"<[^>]+>", "", cond).strip()
        r = _pct(rate)
        if r is None:
            continue
        rng = _parse_cond(cond)
        if rng is None:
            continue
        out.append({"min_days": rng[0], "max_days": rng[1], "rate": r})
    out.sort(key=lambda x: x["min_days"])
    return out


def fetch_one(code: str, retries: int = 3) -> dict:
    """抓一只基金的费率。失败返回 {'code':..., 'error':...}，不抛异常。"""
    code = str(code).strip()
    rec = {"code": code, "name": "", "exchange": is_exchange(code),
           "buy_rate": None, "buy_rate_raw": None, "redeem": [], "fetched_at": str(date.today()),
           # 基础信息（页面「基金检索」详情用）：规模 / 类型 / 成立日 / 经理 / 公司 / 风险等级
           "size": None, "type": None, "inception": None, "manager": None, "company": None, "risk": None,
           "min_buy": None}
    if rec["exchange"]:
        rec["buy_rate"] = COMMISSION_RATE
        rec["note"] = "场内佣金"
        # 场内 ETF 也要基础信息（规模/成立日/经理），所以继续往下拉一次接口

    for attempt in range(retries):
        try:
            r = requests.get("https://fundmobapi.eastmoney.com/FundMApi/FundBaseTypeInformation.ashx",
                             params={"FCODE": code, "deviceid": "1", "plat": "Iphone",
                                     "product": "EFund", "version": "6.2.8"},
                             headers=_UA, timeout=10)
            d = (r.json() or {}).get("Datas") or {}
            rec["name"] = d.get("SHORTNAME") or ""
            rec["buy_rate"] = _pct(d.get("RATE"))
            rec["buy_rate_raw"] = _pct(d.get("SOURCERATE"))
            try:
                rec["size"] = float(d.get("ENDNAV")) if d.get("ENDNAV") else None
            except Exception:  # noqa: BLE001
                rec["size"] = None
            rec["type"] = d.get("FTYPE") or None
            rec["inception"] = (d.get("ISSBDATE") or "")[:10] or None
            rec["manager"] = d.get("JJJL") or None
            rec["company"] = d.get("JJGS") or None
            rec["risk"] = {"1": "低", "2": "中低", "3": "中", "4": "中高", "5": "高"}.get(str(d.get("RISKLEVEL") or ""), None)
            try:
                rec["min_buy"] = float(d.get("MINSG")) if d.get("MINSG") else None
            except Exception:  # noqa: BLE001
                rec["min_buy"] = None
            break
        except Exception as e:  # noqa: BLE001
            if attempt == retries - 1:
                rec["error"] = f"基础信息: {e}"
            time.sleep(0.8 * (attempt + 1))
    for attempt in range(retries):
        try:
            r = requests.get(f"https://fundf10.eastmoney.com/jjfl_{code}.html", headers=_UA, timeout=10)
            raw = r.content
            for enc in ("gb18030", "utf-8"):
                try:
                    html = raw.decode(enc)
                    break
                except Exception:  # noqa: BLE001
                    continue
            rec["redeem"] = _parse_redeem(html)
            break
        except Exception as e:  # noqa: BLE001
            if attempt == retries - 1:
                rec["error"] = (rec.get("error", "") + f" 赎回费: {e}").strip()
            time.sleep(0.8 * (attempt + 1))
    return rec


def load(force: bool = False) -> dict:
    if not CACHE.exists():
        return {}
    try:
        d = json.loads(CACHE.read_text())
    except Exception:  # noqa: BLE001
        return {}
    if force:
        return d
    return d


def save(data: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True))


def all_codes() -> list[str]:
    """账户里出现过的代码 + 项目默认 9 只 ETF。"""
    codes = {v.get("code") for v in ETF_META.values() if v.get("code")}
    try:
        for p in (ROOT / "data" / "accounts").glob("*.json"):
            if p.name == "index.json":
                continue
            a = json.loads(p.read_text())
            codes |= {t.get("code") for t in (a.get("trades") or []) if t.get("code")}
    except Exception:  # noqa: BLE001
        pass
    return sorted(c for c in codes if c)


def refresh(force: bool = False, codes: list[str] | None = None) -> dict:
    """补齐缺失/过期（> CACHE_DAYS 天）的费率。"""
    data = load()
    todo = []
    for c in (codes or all_codes()):
        rec = data.get(c)
        if force or not rec or not rec.get("fetched_at"):
            todo.append(c)
        else:
            try:
                age = (date.today() - date.fromisoformat(rec["fetched_at"])).days
            except Exception:  # noqa: BLE001
                age = 999
            if age > CACHE_DAYS:
                todo.append(c)
    for c in todo:
        data[c] = fetch_one(c)
        print(f"  {c} {data[c].get('name', '')[:14]:<14} 申购 {data[c].get('buy_rate')} 赎回 {[x['rate'] for x in data[c].get('redeem', [])]}")
    if todo:
        save(data)
    return data


def get(code: str) -> dict:
    """读缓存；没有就现抓一只并写回。"""
    c = str(code).strip()
    data = load()
    if c in data:
        return data[c]
    rec = fetch_one(c)
    data[c] = rec
    save(data)
    return rec


def buy_fee(code: str, amount: float) -> float:
    """买入手续费（元）：场内按佣金（含最低 5 元），场外按申购费。"""
    amt = float(amount or 0)
    if amt <= 0:
        return 0.0
    if is_exchange(code):
        return round(max(amt * COMMISSION_RATE, COMMISSION_MIN), 2)
    r = get(code).get("buy_rate")
    return round(amt * (r if r is not None else 0.0), 2)


def sell_fee(code: str, amount: float, hold_days: int | None = None) -> float:
    """卖出手续费（元）。场外按持有期查赎回费阶梯（不知道持有天数时按最短档最保守）。"""
    amt = float(amount or 0)
    if amt <= 0:
        return 0.0
    if is_exchange(code):
        return round(max(amt * COMMISSION_RATE, COMMISSION_MIN), 2)
    ladder = get(code).get("redeem") or []
    if not ladder:
        return 0.0
    days = 99999 if hold_days is None else int(hold_days)
    rate = ladder[0]["rate"]
    for band in ladder:
        lo, hi = band.get("min_days", 0), band.get("max_days")
        if days >= lo and (hi is None or days < hi):
            rate = band["rate"]
            break
    return round(amt * rate, 2)


def profile_text(code: str) -> str:
    """基金档案一行：类型 · 成立日 · 规模 · 经理（缺的自动跳过）。"""
    r = get(code)
    bits = []
    if r.get("type"):
        bits.append(r["type"])
    if r.get("inception"):
        bits.append(f"{r['inception']} 成立")
    if r.get("size"):
        bits.append(f"规模 {size_text(r['size'])}")
    if r.get("manager"):
        bits.append(f"经理 {r['manager']}")
    if r.get("company"):
        bits.append(r["company"])
    return " · ".join(bits)


def size_text(size: float | None) -> str:
    """规模（元）→ 「1068.79 亿」/「3.21 亿」/「5230 万」。"""
    if not size:
        return '—'
    if size >= 1e8:
        return f"{size / 1e8:.2f} 亿"
    if size >= 1e4:
        return f"{size / 1e4:.0f} 万"
    return f"{size:.0f} 元"


def describe(code: str) -> str:
    """一行说明，给页面/日志用。"""
    r = get(code)
    if is_exchange(code):          # 不读缓存里的 exchange：老缓存是按旧前缀规则写的
        return f"场内佣金 万{COMMISSION_RATE * 1e4:.1f}（单笔最低 {COMMISSION_MIN:.0f} 元）· 无申购赎回费"
    b = r.get("buy_rate")
    raw = r.get("buy_rate_raw")
    red = r.get("redeem") or []
    # 打折后和原价差得多就把原价也带上（0.12% vs 1.20%，不写出来看不出打了折）
    disc = f"（原 {raw * 100:.2f}%）" if (raw and b is not None and raw > b + 1e-9) else ""
    parts = [f"申购 {(b or 0) * 100:.2f}%{disc}"]
    if red:
        parts.append("赎回 " + " / ".join(
            f"{'<' if x.get('max_days') else '≥'}{(x.get('max_days') or x.get('min_days'))}天 "
            + ("免费" if not x["rate"] else f"{x['rate'] * 100:.2f}%")
            for x in red))
    return " · ".join(parts)


def refresh_purchase() -> int:
    """重抓全市场申购状态表（akshare.fund_purchase_em，约 2.8 万行），写到 fund_lookup.PURCHASE_CSV。

    它决定「场内 / 场外」计费口径，也是 QDII 限购、暂停申购的唯一来源。返回行数。
    """
    global _PURCHASE
    import sys
    ss = str(ROOT / "streamlit_app")
    if ss not in sys.path:
        sys.path.insert(0, ss)
    import akshare as ak  # noqa: PLC0415
    import fund_lookup as FL  # noqa: PLC0415
    d = ak.fund_purchase_em()
    FL.PURCHASE_CSV.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(FL.PURCHASE_CSV, index=False)
    _PURCHASE = None
    FL._PM = None
    return len(d)


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if "--purchase" in args:
        print("刷新全市场申购状态表…")
        print("完成，", refresh_purchase(), "行")
    elif "--show" in args:
        for c, r in sorted(load().items()):
            print(c, r.get("name", "")[:16], "申购", r.get("buy_rate"),
                  "赎回", [x["rate"] for x in r.get("redeem", [])], r.get("fetched_at"))
    else:
        print(f"刷新费率（{len(all_codes())} 只）…")
        refresh(force="--refresh" in args)
        print("完成 →", CACHE)
