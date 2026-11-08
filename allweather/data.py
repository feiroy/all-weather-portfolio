"""数据加载层 - 从 data/ 读取 CSV，处理 30Y 国债合成，返回回测期价格表。"""
import functools
import pandas as pd
import numpy as np
from .config import DATA_DIR, BACKTEST_START, BACKTEST_END, BOND_30Y_TENOR, SAFETY_DEDUCT


@functools.lru_cache(maxsize=32)
def load_series(name: str) -> pd.Series:
    """从 CSV 加载单资产收盘价时间序列（按日期升序）。

    若文件不存在（旧的 ETF 文件可能尚未替换），返回空 Series 而非抛错，
    让调用方有机会降级到 proxy-only 方案。
    """
    path = DATA_DIR / f"{name}.csv"
    if not path.exists():
        return pd.Series(dtype=float)
    df = pd.read_csv(path, parse_dates=["date"])
    return df.set_index("date")["close"].sort_index()


@functools.lru_cache(maxsize=32)
def _load_optional(name: str) -> pd.Series | None:
    """加载可选数据文件；不存在返回 None。"""
    path = DATA_DIR / f"{name}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["date"])
    return df.set_index("date")["close"].sort_index()


def stitch_series(etf: pd.Series, proxy: pd.Series,
                  annual_deduct: float = 0.0) -> pd.Series:
    """ETF 上市前用 proxy，归一化对齐 + 安全扣减后拼接。

    1. 合并 proxy + etf 交易日历，proxy reindex + ffill（对齐不同市场日历）
    2. proxy 日收益扣减 safety margin
    3. 在 etf 起始日归一化：proxy *= etf[0] / proxy[stitch_date]
    4. 拼接 proxy[:stitch_date) + etf[stitch_date:]
    """
    if proxy.empty or etf.empty:
        raise ValueError("proxy 或 etf 数据为空，无法缝合")

    # 合并日历：保留 proxy 的全部历史 + ETF 的交易日历
    combined_cal = proxy.index.union(etf.index).sort_values()
    proxy = proxy.reindex(combined_cal).ffill()

    # 安全扣减应用于 proxy 日收益率（无扣减时跳过 roundtrip）
    if annual_deduct > 0:
        first_date = combined_cal[0]
        daily_deduct = annual_deduct / 252.0
        proxy_ret = proxy.pct_change().dropna()
        proxy_ret = proxy_ret - daily_deduct
        proxy = (1 + proxy_ret).cumprod()
        proxy = pd.concat([pd.Series(1.0, index=[first_date]), proxy]).sort_index()

    # 在 etf 起始日归一化
    stitch_date = etf.index.min()
    if stitch_date not in proxy.index:
        raise ValueError(f"缝合日 {stitch_date.date()} 不在 proxy 索引中")
    proxy = proxy * (etf.iloc[0] / proxy.loc[stitch_date])

    # 拼接
    proxy_part = proxy[proxy.index < stitch_date]
    return pd.concat([proxy_part, etf]).sort_index()


def _load_cgb_yield(tenor_col: str = "30年") -> pd.Series:
    """中债国债收益率曲线某个期限的日序列（小数，如 0.0203）。文件没有返回空序列。

    cgb_yields.csv 是 akshare bond_china_yield 原样落盘：列 1 = 日期，列名「30年」「10年」…；
    取不到中文列名时按位置回退（列 9 = 30 年）。
    """
    path = DATA_DIR / "cgb_yields.csv"
    if not path.exists():
        return pd.Series(dtype=float)
    df = pd.read_csv(path)
    if df.empty or len(df.columns) < 10:
        return pd.Series(dtype=float)
    col = tenor_col if tenor_col in df.columns else df.columns[9]
    y = pd.to_numeric(df[col], errors="coerce")
    y.index = pd.to_datetime(df[df.columns[1]], errors="coerce")
    y = y[~y.index.duplicated(keep="last")].dropna().sort_index()
    return y / 100.0


def bond_total_return_from_yield(y: pd.Series, tenor: float) -> pd.Series:
    """恒定期限票面国债的总回报指数（起点 1.0），只用收益率曲线、不依赖任何 ETF。

    每个交易日：按昨日收益率 y0 买入票面利率 = y0 的面值债，持有 dt 年后按今日收益率 y1、
    剩余期限 tenor-dt 重新定价（年付息票面债精确定价），再加持有期票息 y0·dt。
    即 票息 + 久期×Δy + 凸性，全部来自真实收益率，不会像「10Y 日收益 × 3」那样把票息也放大 3 倍。
    """
    y = y.dropna()
    dt = y.index.to_series().diff().dt.days.fillna(0) / 365.0
    y0, n = y.shift(1), tenor - dt
    price = y0 / y * (1 - (1 + y) ** -n) + (1 + y) ** -n
    r = (price - 1) + y0 * dt
    return (1 + r.fillna(0.0)).cumprod()


def synthesize_bond_30y(s_10y: pd.Series | None, s_30y_etf: pd.Series) -> pd.Series:
    """30Y 国债序列：511130 上市前用中债 30 年收益率重建总回报，上市后用 ETF 真实累计净值。

    2026-11-08 审计后重写。旧做法「2015-02~2020-02 用 10Y 指数日收益 ×3、2020-02~2024-03 利差法」
    有两个问题：① 10Y 指数日收益里含票息，×3 把票息也放大了 3 倍 —— 实测该段年化 11.36%，
    而用中债 30Y 收益率重建的上限只有 6.45%（高估 4.91pp/年，2018 年 +24.0% vs +16.7%）；
    ② 利差数据只拉到了 2020 年（见 fetch_cgb_yields），2021 后实际又退化成 ×3。
    修正后三策略全区间年化下降 0.53~0.78pp，见 CLAUDE.md「数据口径：30 年国债」。

    重建段扣 SAFETY_DEDUCT["bond_30y"]：用 511130 上市后的重合期校准（重建比 ETF 高约 0.5pp/年，
    即管理费 + 跟踪误差）。s_10y 只用来提供交易所交易日历。
    """
    y30 = _load_cgb_yield("30年")
    if y30.empty or s_30y_etf.empty:
        raise FileNotFoundError(
            "合成 30Y 需要 data/cgb_yields.csv（中债国债收益率曲线，2014 起）和 bond_30y_etf.csv；"
            "运行 py main.py 或 python -c 'from allweather.fetch import fetch_all; fetch_all()' 拉取")
    # 面板共同起点是 2015-01（中证短融指数起点），收益率必须覆盖到它之前，否则 30Y 会把整个面板截短
    if y30.index.min() > pd.Timestamp("2015-01-05"):
        raise ValueError(f"cgb_yields.csv 只从 {y30.index.min().date()} 开始，覆盖不到回测起点 2015-01；"
                         "删掉该文件后重新拉取（fetch_all 会按年补全到 2014）")
    recon = bond_total_return_from_yield(y30, BOND_30Y_TENOR)
    # 对齐到交易所日历：银行间在调休周六也有收益率（2015~2026 多 46 天），不对齐会把这些日子
    # 塞进面板 —— 其它资产当天收益为 0、月末判断也会落到周六。用 10Y ETF/指数的交易日历。
    if s_10y is not None and len(s_10y):
        cal = s_10y.index.union(s_30y_etf.index)
        recon = recon.reindex(recon.index.union(cal)).ffill().reindex(cal).dropna()
    return stitch_series(s_30y_etf, recon, annual_deduct=SAFETY_DEDUCT["bond_30y"])


def _load_bond_10y() -> pd.Series:
    """加载 10Y 国债序列：ETF (2017-08+) + 国债总指数 (2008-2017) + 企债指数 (2005-2008)。"""
    etf = load_series("bond_10y_etf")
    treasury_idx = load_series("treasury_idx")
    credit_idx = load_series("credit_idx")

    if etf.empty and treasury_idx.empty:
        raise FileNotFoundError("bond_10y_etf 和 treasury_idx 都不可用")

    if etf.empty:
        return treasury_idx

    if treasury_idx.empty:
        proxy = credit_idx
    else:
        proxy = stitch_series(treasury_idx, credit_idx, annual_deduct=0.0)

    return stitch_series(etf, proxy, annual_deduct=0.0)


def _load_macro_gold_cached():
    """宏观黄金ETF持仓数据，本地缓存避免每次 40s+ HTTP 请求。"""
    cache_path = DATA_DIR / "_ak_macro_gold_cache.csv"
    if cache_path.exists():
        df = pd.read_csv(cache_path)
        return df
    try:
        import akshare as ak
        mg = ak.macro_cons_gold()
        mg.to_csv(cache_path, index=False)
        return mg
    except Exception as e:
        print(f"  [WARN] 宏观黄金数据获取失败: {e}")
        return None


def _load_gold_cny() -> pd.Series:
    """黄金 CNY：ETF (2013+) + 伦敦金×USDCNY (2006-2013) + ETF 持仓推算 (2005-2006)。"""
    etf = load_series("gold")
    london = _load_optional("london_gold")
    usdcny = _load_optional("usdcny")

    if etf.empty and london is None:
        raise FileNotFoundError("gold ETF 和 london_gold 都不可用")

    if london is None or usdcny is None:
        return etf

    combined = london.index.union(usdcny.index).union(etf.index).sort_values()
    london = london.reindex(combined).ffill()
    usdcny = usdcny.reindex(combined).ffill()
    gold_cny = london * usdcny
    gold_cny.name = "close"

    # 2005-2006: 黄金 ETF 持仓数据推算金价（伦敦金数据从 2006-05 起）
    mg = _load_macro_gold_cached()
    if mg is not None:
        mg["date"] = pd.to_datetime(mg["日期"])
        mg["proxy"] = mg["总价值"] / mg["总库存"]
        mg = mg.set_index("date").sort_index()

        cd = mg.index.intersection(gold_cny.index)
        if len(cd) > 10:
            ratio = (gold_cny.loc[cd] / mg.loc[cd, "proxy"]).mean()
            mg_pre = mg[mg.index < gold_cny.index.min()].copy()
            if len(mg_pre) > 0:
                mg_pre["gold_cny"] = mg_pre["proxy"] * ratio
                full_cal = mg_pre.index.union(usdcny.index).union(
                    pd.date_range(mg_pre.index.min(), gold_cny.index.min(), freq="B"))
                mg_daily = mg_pre["gold_cny"].reindex(full_cal).sort_index().ffill()
                mg_daily = mg_daily[mg_daily.index < gold_cny.index.min()]
                if len(mg_daily) > 0:
                    gold_cny = pd.concat([mg_daily, gold_cny]).sort_index()

    if etf.empty:
        return gold_cny

    return stitch_series(etf, gold_cny, annual_deduct=0.0)


def _load_sp500_cny() -> pd.Series:
    """标普500 CNY：ETF (2015+) + .INX×USDCNY。

    us_sp500.csv 当前存的是 ETF NAV（已含 CNY），
    若存在 sp500_idx.csv 则用于 pre-ETF 拼接。
    """
    etf = load_series("us_sp500")
    # 尝试加载 S&P500 指数原始数据 + USDCNY
    sp500_usd = _load_optional("sp500_idx")
    usdcny = _load_optional("usdcny")

    if sp500_usd is None or usdcny is None:
        return etf if not etf.empty else load_series("us_sp500")

    combined = sp500_usd.index.union(usdcny.index).union(etf.index if not etf.empty else []).sort_values()
    sp500_usd = sp500_usd.reindex(combined).ffill()
    usdcny = usdcny.reindex(combined).ffill()
    sp500_cny = sp500_usd * usdcny
    sp500_cny.name = "close"

    if etf.empty:
        return sp500_cny

    return stitch_series(etf, sp500_cny, annual_deduct=0.0)


def _load_with_index(etf_name: str, idx_name: str, annual_deduct: float = 0.0) -> pd.Series:
    """通用：ETF + 指数 proxy 拼接。两文件都不存在则抛错。"""
    etf = load_series(etf_name)
    proxy = _load_optional(idx_name)

    if etf.empty and proxy is None:
        raise FileNotFoundError(f"{etf_name} 和 {idx_name} 都不可用")

    if proxy is None:
        return etf
    if etf.empty:
        return proxy

    return stitch_series(etf, proxy, annual_deduct=annual_deduct)




def _load_bond_short() -> pd.Series:
    """短融 ETF 511360 (2020-09+) + 中证短融指数 H11014 (2015+) 拼接。"""
    return _load_with_index("bond_short_etf", "shortbond_idx", annual_deduct=0.0)


def load_panel(include_wti: bool = True, end: str | None = None) -> pd.DataFrame:
    """加载 8 资产收盘价面板（含缝合，对齐到回测期间，前向填充）。

    2008+ 延长回测：ETF 上市前的期间用指数/国际价格拼接。

    end: 面板截止日（默认 BACKTEST_END，回测用）；实盘再平衡传今天，
    保留回测截止日之后新拉取的行情。
    """
    # 权益：ETF + 指数 proxy
    hs300 = _load_with_index("hs300", "hs300_idx", annual_deduct=0.0)
    credit = _load_with_index("bond_credit", "credit_idx", annual_deduct=0.0)

    # 海外权益 & 黄金：需要用汇率换算
    us_sp500 = _load_sp500_cny()
    gold = _load_gold_cny()

    # 债券
    bond_10y = _load_bond_10y()
    s_30y_etf = load_series("bond_30y_etf")
    bond_30y = synthesize_bond_30y(bond_10y, s_30y_etf)
    bond_short = _load_bond_short()

    # nonferr: 沪铜 (2008-2013) → 申万有色指数 (2013-2019) → ETF (2019+)
    nonferr_etf = load_series("nonferr")
    nonferr_idx = load_series("nonferr_idx")
    shfe_copper = load_series("shfe_copper")

    # 构建 pre-ETF 的完整 proxy 链（铜 → 指数）
    # 沪铜段扣 0.0095：159980 期货 ETF vs 沪铜 6.4 年重合期年度拖累 -0.95%（费率+移仓损耗），同 WTI 校准法
    if not shfe_copper.empty and not nonferr_idx.empty:
        nonferr_proxy = stitch_series(nonferr_idx, shfe_copper, annual_deduct=0.0095)
    elif not nonferr_idx.empty:
        nonferr_proxy = nonferr_idx
    else:
        nonferr_proxy = shfe_copper

    if not nonferr_etf.empty and not nonferr_proxy.empty:
        nonferr = stitch_series(nonferr_etf, nonferr_proxy,
                                annual_deduct=SAFETY_DEDUCT["nonferr"])
    elif not nonferr_etf.empty:
        nonferr = nonferr_etf
    elif not nonferr_proxy.empty:
        nonferr = nonferr_proxy
    else:
        raise FileNotFoundError(
            "nonferr 三级回退全部为空：需要 nonferr.csv（ETF）、"
            "nonferr_idx.csv（指数）或 shfe_copper.csv（沪铜）至少一个")

    # 原油（501018 LOF 优先，WTI USD×USDCNY 拼接）
    if include_wti:
        wti_cny = _load_wti_cny()

    panel = pd.DataFrame({
        "hs300":    hs300,
        "us_sp500": us_sp500,
        "credit":   credit,
        "bond_short": bond_short,
        "bond_10y": bond_10y,
        "bond_30y": bond_30y,
        "gold":     gold,
        "nonferr":  nonferr,
    })
    if include_wti:
        panel["wti"] = wti_cny
    panel.index = pd.to_datetime(panel.index)
    panel = panel.sort_index()
    # 默认不截断到 BACKTEST_END：那个常量是「上一次跑全量回测的截止日」，
    # 行情每天在更新，页面/回测却停在旧日期（2026-11-08 用户问「都 11 月 8 号了为啥还停在 10 月 16」）。
    # 现在默认用数据里最新的共同日期；要复现历史某次回测再显式传 end。
    panel_end = end
    panel = (panel.loc[BACKTEST_START:panel_end] if panel_end else panel.loc[BACKTEST_START:]).ffill()

    # 找到所有资产都开始有数据的起始日，而非一个资产缺失就整行删除
    # 避免早期部分资产无 proxy 时截断太狠
    valid_start = panel.apply(lambda s: s.first_valid_index())
    earliest_all_valid = valid_start.max()  # 最晚的 first-valid = 全部就绪日
    if earliest_all_valid is not None and earliest_all_valid > panel.index[0]:
        panel = panel.loc[earliest_all_valid:]

    # 至此所有资产都有数据；dropna 仅做安全网（应无操作）
    panel = panel.dropna()

    return panel



def _load_wti_cny() -> pd.Series:
    """南方原油 CNY（501018 LOF）：LOF 优先，2016年前用 WTI USD × USDCNY 拼接。

    南方原油 LOF（501018）2019-04-26 上市，有 2016-06 起的历史 NAV 回算数据。
    此前用 WTI CL × USDCNY 做历史代理。
    """
    sc = _load_optional("wti")       # 501018 LOF, ~2016+
    wti_usd = _load_optional("wti_usd")  # WTI CL USD, 1996+
    usdcny = _load_optional("usdcny")

    has_lof = sc is not None and not sc.empty
    has_wti = wti_usd is not None and not wti_usd.empty and usdcny is not None and not usdcny.empty

    # 只有 WTI 无 LOF → WTI×USDCNY（回退兼容）
    if not has_lof and has_wti:
        combined = wti_usd.index.union(usdcny.index).sort_values()
        w = wti_usd.reindex(combined).ffill()
        u = usdcny.reindex(combined).ffill()
        wti_cny = (w * u).dropna()
        return wti_cny

    # 只有 LOF 无 WTI → 直接用 LOF
    if has_lof and not has_wti:
        return sc

    # 两者都有 → 拼接: WTI proxy pre-LOF, LOF 2016+
    if not has_lof or not has_wti:
        raise FileNotFoundError("wti / wti_usd 数据均不可用")

    combined = wti_usd.index.union(usdcny.index).sort_values()
    w = wti_usd.reindex(combined).ffill()
    u = usdcny.reindex(combined).ffill()
    wti_proxy = (w * u).dropna()

    return stitch_series(sc, wti_proxy, annual_deduct=0.009)


def load_hs300_pe(col_index: int = 2) -> pd.Series:
    """加载沪深300 PE 时间序列（日频）。不存在返回空 Series。

    col_index: PE 列索引，默认 2（等权静态市盈率），推荐 7（滚动市盈率中位数）。
    """
    path = DATA_DIR / "hs300_pe.csv"
    if not path.exists():
        return pd.Series(dtype=float)
    df = pd.read_csv(path)
    date_col = df.columns[0]
    pe_col = df.columns[col_index]
    df[date_col] = pd.to_datetime(df[date_col])
    return df.set_index(date_col)[pe_col].sort_index()


def load_hs300_pb(col_index: int = 3) -> pd.Series:
    """加载沪深300 PB 时间序列（日频）。不存在返回空 Series。

    col_index: PB 列索引，默认 3（PB 中位数），2=加权PB，1=PB。
    """
    path = DATA_DIR / "hs300_pb.csv"
    if not path.exists():
        return pd.Series(dtype=float)
    df = pd.read_csv(path)
    date_col = df.columns[0]
    pb_col = df.columns[col_index]
    df[date_col] = pd.to_datetime(df[date_col])
    return df.set_index(date_col)[pb_col].sort_index()


