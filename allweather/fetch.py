"""数据拉取 - 调用 akshare 拉取 ETF / 指数日频，写入 data/。

仅在数据不齐全时调用；正常回测从已有 CSV 读取。
"""
import time
import math
import requests
import pandas as pd
from .config import DATA_DIR, BACKTEST_END

RETRY_TIMES = 3
RETRY_DELAY = 5  # 秒

DEFAULT_START = "20050101"
DEFAULT_END   = BACKTEST_END.replace("-", "")

# 资产清单：name -> (kind, symbol)
TARGETS = {
    # A 股权益 ETF NAV（含分红，不用价格指数）
    "hs300":      ("etf_nav", "510300"),
    # 债券指数
    # ETF 净值（避开折溢价）
    "bond_30y_etf": ("etf_nav", "511130"),
    "bond_10y_etf": ("etf_nav", "511260"),
    "bond_credit":  ("etf_nav", "511220"),
    "bond_short_etf": ("etf_nav", "511360"),
    "gold":         ("etf_nav", "518850"),
    "nonferr":      ("etf_nav", "159980"),
    # QDII
    "us_sp500":     ("etf_nav", "513500"),
    # 短债/货币
    # 缝合用替代数据
    "nonferr_idx":  ("idx", "sh000823"),   # 中证有色金属指数
    # 2008+ 延长回测数据源
    "hs300_idx":    ("idx", "sh000300"),   # CSI 300 指数 (2008+)
    "credit_idx":   ("idx", "sh000013"),   # 上证企债指数 (2008+)
    "treasury_idx": ("treasury", None),    # 国债总指数 (2008+)
    "london_gold":  ("foreign_fut", "XAU"),  # 伦敦金 USD/oz (2006+)
    "shfe_copper":  ("sina_fut", "CU0"),   # 沪铜连续 (2005+)
    "usdcny":       ("fx_boc", "USDCNY"),  # 美元人民币汇率 (2008+)
    "sp500_idx":    ("sp500", None),       # S&P500 指数 USD (2008+)
    "wti":          ("etf_nav", "501018"), # 南方原油 LOF (2016+), 普通账户可买
    "wti_usd":      ("foreign_fut", "CL"), # WTI 原油连续 USD (1996+) — SC0前历史proxy
}


def _fetch_idx(sym):
    import akshare as ak
    df = ak.stock_zh_index_daily(symbol=sym)
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "close"]].sort_values("date")

def _fetch_idx_tx(sym):
    """腾讯证券指数接口，作为备用。"""
    import akshare as ak
    df = ak.stock_zh_index_daily_tx(symbol=sym)
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "close"]].sort_values("date")


def _fetch_idx_em(sym):
    import akshare as ak
    df = ak.stock_zh_index_daily_em(symbol=sym)
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "close"]].sort_values("date")


def _fetch_etf_nav(code, start, end):
    """策略用：累计净值（LJJZ）序列，列 date/close。口径沿用历史回测，不在此改动。"""
    df = _fetch_etf_nav_full(code, start, end)
    return df[["date", "close"]] if not df.empty else pd.DataFrame(columns=["date", "close"])


def _fetch_etf_nav_full(code, start, end):
    """直接调 eastmoney API 获取 ETF 历史净值，避免 akshare 列数硬编码 bug。

    返回 date / close(累计净值) / unit_nav(单位净值) / daily_chg(官方日增长率%)。
    注意：累计净值 = 单位净值 + 历年分红（分红不再投资），其涨跌幅会被分红稀释，
    与支付宝/天天基金显示的「日涨幅」（按单位净值、分红日复权）不同。
    """
    url = "https://api.fund.eastmoney.com/f10/lsjz"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36",
        "Referer": f"https://fundf10.eastmoney.com/jjjz_{code}.html",
    }
    params = {
        "fundCode": code,
        "pageIndex": "1",
        "pageSize": "20",
        "startDate": "-".join([start[:4], start[4:6], start[6:]]),
        "endDate": "-".join([end[:4], end[4:6], end[6:]]),
        "_": round(time.time() * 1000),
    }
    r = requests.get(url, params=params, headers=headers, timeout=30)
    data_json = r.json()
    total_page = math.ceil(data_json["TotalCount"] / 20)
    df_list = []
    for page in range(1, total_page + 1):
        if page > 1:
            params["pageIndex"] = str(page)
            params["_"] = round(time.time() * 1000)
            r = requests.get(url, params=params, headers=headers, timeout=30)
            data_json = r.json()
        temp_df = pd.DataFrame(data_json["Data"]["LSJZList"])
        df_list.append(temp_df)
    if not df_list:
        # 区间内无数据（周末/节假日/无新净值）：返回空表，
        # 让上层 fetch_one 降级到 _fetch_etf_hist 或标记"已最新"，
        # 避免 pd.concat([]) 抛 "No objects to concatenate"
        return pd.DataFrame(columns=["date", "close", "unit_nav", "daily_chg"])
    big_df = pd.concat(df_list, ignore_index=True)
    col_map = {
        "FSRQ": "date", "DWJZ": "unit_nav", "LJJZ": "close",
        "JZZZL": "daily_chg", "SGZT": "buy", "SHZT": "sell",
    }
    big_df = big_df[list(col_map.keys())].rename(columns=col_map)
    big_df["date"] = pd.to_datetime(big_df["date"], errors="coerce")
    for col in ["close", "unit_nav", "daily_chg"]:
        big_df[col] = pd.to_numeric(big_df[col], errors="coerce")
    close_mid = big_df["close"].median()
    unit_mid = big_df["unit_nav"].median()
    if not (0.1 <= close_mid <= 5000):
        raise ValueError(f"{code}: close 中位数={close_mid}，超出预期")
    if not (0.1 <= unit_mid <= 5000):
        raise ValueError(f"{code}: unit_nav 中位数={unit_mid}，超出预期")
    big_df = big_df.dropna(subset=["date", "close"])
    return big_df[["date", "close", "unit_nav", "daily_chg"]].sort_values("date").reset_index(drop=True)


def _fetch_etf_hist(code, start, end):
    """ETF 行情兜底：改用新浪接口（东财行情域名 push2his 常无法连接）。"""
    import akshare as ak
    prefix = "sh" if str(code).startswith("5") else "sz"
    df = ak.fund_etf_hist_sina(symbol=f"{prefix}{code}")
    df["date"] = pd.to_datetime(df["date"])
    df = df[["date", "close"]]
    s = pd.to_datetime(start, format="%Y%m%d")
    e = pd.to_datetime(end, format="%Y%m%d")
    df = df[(df["date"] >= s) & (df["date"] <= e)]
    return df.sort_values("date").reset_index(drop=True)


def _fetch_fut_dce(sym, start, end):
    """拉取 DCE 期货主力连续合约日频数据。"""
    import akshare as ak
    df = ak.futures_main_sina(symbol=sym)
    df = df.rename(columns={"日期": "date", "收盘价": "close"})
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["date", "close"])
    df = df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))]
    return df[["date", "close"]].sort_values("date")


def fetch_one(name, kind, sym, start=DEFAULT_START, end=DEFAULT_END):
    last_err = None
    for attempt in range(1, RETRY_TIMES + 1):
        try:
            if kind == "idx":
                df = _fetch_idx(sym)
                # 新浪接口数据可能截止较早，不覆盖请求范围时降级到腾讯
                if df.empty or df["date"].max() < pd.to_datetime(end) - pd.Timedelta(days=30):
                    df = _fetch_idx_tx(sym)
            elif kind == "idx_em":
                try:
                    df = _fetch_idx_em(sym)
                    if df.empty or df["date"].max() < pd.to_datetime(end) - pd.Timedelta(days=30):
                        raise ValueError("数据不足，降级到腾讯")
                except Exception:
                    df = _fetch_idx_tx(sym)
            elif kind == "fut_dce":
                df = _fetch_fut_dce(sym, start, end)
            elif kind == "etf_nav":
                df = _fetch_etf_nav(sym, start, end)
                # 仅全量拉取才降级到收盘价；增量时空表=净值未发布（QDII 滞后 1~2 日），
                # 降级会把收盘价拼到累计净值序列上（513500 曾因此 -45% 跳变）
                if df.empty and start <= DEFAULT_START:
                    df = _fetch_etf_hist(sym, start, end)
            elif kind == "treasury":
                df = _fetch_treasury_idx(start, end)
            elif kind == "foreign_fut":
                df = _fetch_foreign_fut(sym, start, end)
            elif kind == "sina_fut":
                df = _fetch_sina_fut(sym, start, end)
            elif kind == "fx_boc":
                df = _fetch_fx_boc(start, end)
            elif kind == "sp500":
                df = _fetch_sp500_idx(start, end)
            else:
                raise ValueError(f"unknown kind: {kind}")
            df = df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))]
            return df
        except ValueError:
            raise
        except Exception as e:
            last_err = e
            if attempt < RETRY_TIMES:
                print(f"    重试 {attempt}/{RETRY_TIMES - 1}，等待 {RETRY_DELAY}s... ({e})", flush=True)
                time.sleep(RETRY_DELAY)
    raise last_err


def _fetch_treasury_idx(start, end):
    """国债总指数 (bond_treasury_index_cbond)，2008+。"""
    import akshare as ak
    df = ak.bond_treasury_index_cbond()
    df["date"] = pd.to_datetime(df["date"])
    df = df.rename(columns={"value": "close"})
    df = df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))]
    return df[["date", "close"]].sort_values("date")


def _fetch_foreign_fut(sym, start, end):
    """国际期货历史数据 (futures_foreign_hist)，例如 XAU 伦敦金。"""
    import akshare as ak
    df = ak.futures_foreign_hist(symbol=sym)
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))]
    return df[["date", "close"]].sort_values("date")


def _fetch_sina_fut(sym, start, end):
    """新浪期货主力连续 (futures_main_sina)，如 CU0 沪铜。"""
    import akshare as ak
    df = ak.futures_main_sina(symbol=sym)
    df = df.rename(columns={"日期": "date", "收盘价": "close"})
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["date", "close"])
    df = df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))]
    return df[["date", "close"]].sort_values("date")


def _fetch_fx_boc(start, end):
    """美元人民币汇率 (currency_boc_sina)，取央行中间价。"""
    import akshare as ak
    df = ak.currency_boc_sina(symbol="美元", start_date=start, end_date=end)
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "close"])
    df = df.rename(columns={"日期": "date", "央行中间价": "close"})
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce") / 100.0  # 分→元
    close_mid = df["close"].median()
    if pd.isna(close_mid):
        # 区间内无有效汇率（周末/节假日），返回空表，由上层标记"已最新"
        return pd.DataFrame(columns=["date", "close"])
    if not (5 < close_mid < 10):
        raise ValueError(f"USDCNY 中间价中位数={close_mid}，预期 ~7 元，可能单位已变更")
    df = df.dropna(subset=["date", "close"])
    return df[["date", "close"]].sort_values("date")


def _fetch_sp500_idx(start, end):
    """S&P500 指数 USD (index_us_stock_sina .INX)。"""
    import akshare as ak
    df = ak.index_us_stock_sina(symbol=".INX")
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))]
    return df[["date", "close"]].sort_values("date")


def fetch_cgb_yields():
    """拉取中债国债收益率曲线。失败返回 None。

    返回的 DataFrame 通过位置匹配列名，避免中文编码问题。
    """
    try:
        import akshare as ak
        df = ak.bond_china_yield()
        if df is None or df.empty:
            return None
        if "曲线名称" in df.columns:
            df = df[df["曲线名称"].str.contains("国债", na=False)]
        return df
    except Exception:
        return None


def _last_trading_day(end: str) -> str:
    """把结束日期回退到最近的工作日（周六/周日回退到周五）。

    作用：周末点击"拉取最新数据"时，数据本来就没有新净值，
    回退后 next_date >= end，可直接标记"已最新"，避免无谓网络请求。
    注意：只处理周末，不处理法定节假日（节假日仍会请求，但返回空会走"已最新"）。
    """
    d = pd.Timestamp(end)
    while d.weekday() >= 5:  # 5=周六, 6=周日
        d -= pd.Timedelta(days=1)
    return d.strftime("%Y%m%d")


def fetch_all(force: bool = False, start: str = DEFAULT_START, end: str = DEFAULT_END):
    """拉取所有目标资产。支持增量更新 —— 已有文件只补充缺失日期。

    Args:
        force: True 时覆盖已有文件
        start: 起始日期，格式 YYYYMMDD，默认 20050101
        end:   结束日期，格式 YYYYMMDD，默认 20260530
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _end_orig = end
    end = _last_trading_day(end)
    print(f"[fetch] 数据目录: {DATA_DIR}")
    if end != _end_orig:
        print(f"[fetch] 拉取区间: {start} ~ {end}（{_end_orig} 非交易日，已回退到最近工作日）")
    else:
        print(f"[fetch] 拉取区间: {start} ~ {end}")

    ok, errors, up_to_date = {}, [], []

    for name, (kind, sym) in TARGETS.items():
        path = DATA_DIR / f"{name}.csv"
        # 全量接口（不支持增量）：treasury/sp500/fx 等每次调用都会下全量，
        # 若今天已经拉过（文件 mtime 是今天），直接跳过，避免重复下载。
        FULL_FETCH_KINDS = {"treasury", "sp500"}
        if (not force) and kind in FULL_FETCH_KINDS and path.exists():
            import datetime as _dt
            mday = _dt.date.fromtimestamp(path.stat().st_mtime)
            if mday == _dt.date.today():
                up_to_date.append(name)
                print(f"  >> {name} 今日已更新，跳过（全量接口）", flush=True)
                continue
        if path.exists() and not force:
            # 增量模式 —— 跳过已有日期，只拉新数据
            existing = pd.read_csv(path, parse_dates=["date"])
            if existing.empty:
                # CSV 空文件，走全量拉取
                print(f"  >> {name} [空文件重拉]", flush=True)
                try:
                    df = fetch_one(name, kind, sym, start=start, end=end)
                    df.to_csv(path, index=False)
                    ok[name] = (df["date"].min(), df["date"].max(), len(df))
                    print(f"    ok  {df['date'].min().date()} → {df['date'].max().date()}  n={len(df)}")
                except Exception as e:
                    errors.append(f"{name}: {str(e)[:200]}")
                continue
            last_date = existing["date"].max()
            next_date = last_date + pd.Timedelta(days=1)
            # 用 > 而不是 >=：已有至 10/22、最近交易日为 10/23 时 next_date == end，仍需请求 10/23
            if next_date > pd.Timestamp(end):
                up_to_date.append(name)
                print(f"  -- {name} 已最新（已有至 {last_date.date()}，无需请求）", flush=True)
                continue
            inc_start = next_date.strftime("%Y%m%d")
            print(f"  >> {name} 增量 {inc_start}~{end}（已有至 {last_date.date()}）", flush=True)
            try:
                df = fetch_one(name, kind, sym, start=inc_start, end=end)
                if df is None or df.empty:
                    up_to_date.append(name)
                    continue
                # 口径校验：新段首值与旧段末值偏离 >15% 视为口径混用，拒绝写入
                _jump = float(df["close"].iloc[0]) / float(existing["close"].iloc[-1]) - 1
                if abs(_jump) > 0.15:
                    errors.append(f"{name}: 增量首值与已有末值偏离 {_jump:+.1%}，疑似净值/收盘价口径混用，已拒绝写入")
                    continue
                combined = pd.concat([existing, df[["date", "close"]]], ignore_index=True)
                combined = combined.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
                combined.to_csv(path, index=False)
                new_rows = len(combined) - len(existing)
                ok[name] = (combined["date"].min(), combined["date"].max(), len(combined))
                print(f"    ok  {combined['date'].min().date()} → {combined['date'].max().date()}  +{new_rows} 行")
            except Exception as e:
                errors.append(f"{name}: {str(e)[:200]}")
        else:
            tag = "[强制覆盖]" if force else "[首次拉取]"
            print(f"  >> {name} {tag}", flush=True)
            try:
                df = fetch_one(name, kind, sym, start=start, end=end)
                df.to_csv(path, index=False)
                ok[name] = (df["date"].min(), df["date"].max(), len(df))
                print(f"    ok  {df['date'].min().date()} → {df['date'].max().date()}  n={len(df)}")
            except Exception as e:
                errors.append(f"{name}: {str(e)[:200]}")

    # 尝试拉取中债国债收益率曲线（bond_china_yield 不支持日期参数，全量接口）
    # 当日缓存：今天已经拉过就跳过，避免每次点击都重新下载
    import datetime as _dt
    yield_path = DATA_DIR / "cgb_yields.csv"
    _skip_yield = (
        (not force)
        and yield_path.exists()
        and _dt.date.fromtimestamp(yield_path.stat().st_mtime) == _dt.date.today()
    )
    if _skip_yield:
        print(f"  >> cgb_yields 今日已更新，跳过（全量接口）", flush=True)
    else:
        print(f"  >> cgb_yields (bond_china_yield)", flush=True)
        yield_df = fetch_cgb_yields()
        if yield_df is not None and not yield_df.empty:
            yield_df.to_csv(yield_path, index=False, encoding="utf-8")
            print(f"    ok  n={len(yield_df)}")
        else:
            print(f"    WARN  中债收益率曲线拉取失败，将使用久期放大回退方案合成 30Y")

    print(f"\n=== 拉取摘要 ===")
    print(f"  成功: {len(ok)}    已最新: {len(up_to_date)}    失败: {len(errors)}")
    if ok:
        for name, (mn, mx, n) in ok.items():
            print(f"    {name}: {mn.date()} → {mx.date()}  ({n} 行)")
    if up_to_date:
        print(f"  已最新（未发起请求）: {', '.join(up_to_date)}")
    if errors:
        print("  失败明细:")
        for e in errors:
            print(f"    {e}")
    return ok, errors, up_to_date


NAV_DETAIL_DIR = DATA_DIR / "nav_detail"


def update_nav_detail(force: bool = False, end: str | None = None):
    """维护 data/nav_detail/{name}.csv：date / unit_nav / acc_nav / daily_chg（官方日增长率%）。

    只供页面展示（与支付宝一致的单位净值和日涨幅），策略回测仍读 data/{name}.csv 的累计净值。
    首次全量（按页拉取，较慢），之后增量。返回 (更新说明, 错误)。
    """
    NAV_DETAIL_DIR.mkdir(parents=True, exist_ok=True)
    end = _last_trading_day(end or pd.Timestamp.today().strftime("%Y%m%d"))
    msgs, errs = [], []
    for name, (kind, sym) in TARGETS.items():
        if kind != "etf_nav":
            continue
        path = NAV_DETAIL_DIR / f"{name}.csv"
        old = pd.read_csv(path, parse_dates=["date"]) if path.exists() and not force else None
        start = DEFAULT_START if old is None or old.empty else (old["date"].max() + pd.Timedelta(days=1)).strftime("%Y%m%d")
        if pd.Timestamp(start) > pd.Timestamp(end):
            continue
        try:
            df = _fetch_etf_nav_full(sym, start, end)
            if df.empty:
                continue
            df = df.rename(columns={"close": "acc_nav"})[["date", "unit_nav", "acc_nav", "daily_chg"]]
            out = df if old is None or old.empty else pd.concat([old, df], ignore_index=True)
            out = out.drop_duplicates(subset="date", keep="last").sort_values("date")
            out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
            out.to_csv(path, index=False)
            msgs.append(f"{name} 净值明细 +{len(df)} 行")
        except Exception as e:  # noqa: BLE001
            errs.append(f"{name} 净值明细: {str(e)[:120]}")
    return msgs, errs


def check_data_complete() -> bool:
    """检查回测必需的 CSV 是否齐全。"""
    required = ["hs300", "bond_30y_etf",
                "bond_credit", "gold", "nonferr", "us_sp500"]
    missing = [n for n in required if not (DATA_DIR / f"{n}.csv").exists()]
    return len(missing) == 0, missing


# === 场内收盘价（与净值分离，供"基金走势"页看盘用）===
# 净值 CSV（data/{name}.csv）存累计净值 LJJZ，用于回测；这里的收盘价
# CSV（data/price_{name}.csv）存场内 ETF 交易价（open/high/low/close/volume），
# 用于"看股价"，两者口径不同、独立存放，互不污染。
_PRICE_SYMBOLS = {
    "hs300":     "510300",
    "us_sp500":  "513500",
    "bond_30y":  "511130",
    "bond_10y":  "511260",
    "credit":    "511220",
    "bond_short": "511360",
    "gold":      "518850",
    "nonferr":   "159980",
    "wti":       "501018",
}


def _sina_symbol(code: str) -> str:
    """新浪 ETF 代码前缀：5 开头沪市 sh，其余深市 sz。"""
    return ("sh" if str(code).startswith("5") else "sz") + str(code)


def _fetch_etf_price(code: str):
    """拉取场内 ETF 日线（含 OHLC + 成交量），新浪接口。"""
    import akshare as ak
    df = ak.fund_etf_hist_sina(symbol=_sina_symbol(code))
    df["date"] = pd.to_datetime(df["date"])
    cols = ["date", "open", "high", "low", "close", "volume"]
    df = df[[c for c in cols if c in df.columns]]
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def fetch_prices(force: bool = False):
    """拉取所有资产的场内收盘价，写入 data/price_{name}.csv（独立于净值）。"""
    ok, errors = {}, []
    for name, code in _PRICE_SYMBOLS.items():
        path = DATA_DIR / f"price_{name}.csv"
        if path.exists() and not force:
            # 增量：只补缺失日期
            existing = pd.read_csv(path, parse_dates=["date"])
            last = existing["date"].max()
            try:
                df = _fetch_etf_price(code)
                new = df[df["date"] > last]
                if new.empty:
                    continue
                combined = pd.concat([existing, new], ignore_index=True)
                combined = combined.drop_duplicates(subset="date").sort_values("date")
                combined.to_csv(path, index=False)
                ok[name] = len(combined)
            except Exception as e:
                errors.append(f"{name}: {str(e)[:150]}")
        else:
            try:
                df = _fetch_etf_price(code)
                df.to_csv(path, index=False)
                ok[name] = len(df)
            except Exception as e:
                errors.append(f"{name}: {str(e)[:150]}")
    return ok, errors


if __name__ == "__main__":
    fetch_all()