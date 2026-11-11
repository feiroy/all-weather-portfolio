"""方案 A：拉 5 只「每一类都真实存在」的基金全历史净值（不做任何拼接）。

    ./myenv/bin/python experiments/_real_pool_fetch.py

口径：用官方日增长率 JZZZL 累乘出复权净值当收益序列。
不能用累计净值 LJJZ —— 它 = 单位净值 + 累计分红（分红不再投资），跌涨幅会被分红稀释；
场外基金（160706 / 050025 / 000032）分红比 ETF 频繁得多，直接用 LJJZ 会系统性低估收益。
LJJZ 仍然存下来，只用于对账。

东财接口固定 20 条/页，160706 有 5000+ 条 → 250 多页，所以按页并发抓。
"""
from __future__ import annotations

import concurrent.futures as cf
import math
import time
from pathlib import Path

import pandas as pd
import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36"
URL = "https://api.fund.eastmoney.com/f10/lsjz"
OUT = Path("data/real")

# key 沿用策略里的资产名，只换数据源：这样回测代码不用动，桶结构照旧
POOL = {
    "hs300":     ("160706", "嘉实沪深300（场外）",      "增长↑"),
    "us_sp500":  ("050025", "博时标普500（场外）",      "增长↑"),
    "credit":    ("000032", "易方达信用债A（场外）",    "收益垫"),
    "bond_10y":  ("511010", "国泰上证5年期国债ETF",     "增长↓"),
    "gold":      ("518880", "华安黄金ETF",              "通胀↑"),
    # A+ 追加：把通胀桶补回两个真实商品基金（原策略里的 nonferr / ene）
    "nonferr":   ("160221", "国泰有色（场外）",          "通胀↑"),
    "ene":       ("160216", "国泰大宗商品（场外, QDII）", "通胀↑"),
}


def _headers(code: str) -> dict:
    return {"User-Agent": UA, "Referer": f"https://fundf10.eastmoney.com/jjjz_{code}.html"}


def _page(code: str, page: int, start: str, end: str) -> list:
    for attempt in range(4):
        try:
            p = {"fundCode": code, "pageIndex": str(page), "pageSize": "20",
                 "startDate": start, "endDate": end, "_": round(time.time() * 1000)}
            return requests.get(URL, params=p, headers=_headers(code), timeout=25).json()["Data"]["LSJZList"]
        except Exception:
            time.sleep(0.6 * (attempt + 1))
    return []


def fetch(code: str, start="2005-01-01", end="2026-11-11") -> pd.DataFrame:
    p = {"fundCode": code, "pageIndex": "1", "pageSize": "20",
         "startDate": start, "endDate": end, "_": round(time.time() * 1000)}
    total = requests.get(URL, params=p, headers=_headers(code), timeout=25).json()["TotalCount"]
    pages = math.ceil(total / 20)
    rows = []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for chunk in ex.map(lambda i: _page(code, i, start, end), range(1, pages + 1)):
            rows += chunk
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.rename(columns={"FSRQ": "date", "DWJZ": "unit_nav", "LJJZ": "ljjz", "JZZZL": "chg"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in ("unit_nav", "ljjz", "chg"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["date"]).drop_duplicates("date").sort_values("date")
    return df[["date", "unit_nav", "ljjz", "chg"]].reset_index(drop=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"{'key':11s}{'代码':8s}{'条数':>6s}  {'首日':11s}{'末日':11s}{'缺chg':>6s}  名称")
    for key, (code, name, _bucket) in POOL.items():
        df = fetch(code)
        if df.empty:
            print(f"{key:11s}{code:8s}  抓取为空")
            continue
        df.to_csv(OUT / f"{key}.csv", index=False)
        miss = int(df["chg"].isna().sum())
        print(f"{key:11s}{code:8s}{len(df):6d}  {df['date'].iloc[0].date()!s:11s}"
              f"{df['date'].iloc[-1].date()!s:11s}{miss:6d}  {name}")
    print(f"\n已写入 {OUT}/")


if __name__ == "__main__":
    main()
