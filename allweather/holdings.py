"""我的持仓：把策略的 8 个资产位置映射到**我自己实际买的基金**。

为什么要有这一层
----------------
策略（V3c / V3-B）算的是「资产位置」的目标权重：增长↑权益(A股)、增长↑权益(海外)、
收益垫、增长↓10Y、增长↓30Y、通胀↑黄金、通胀↑有色、通胀↑能源。
原版代码把这 8 个位置写死了 8 个场内 ETF 代码，实际买入的基金一换，
建仓/调仓/记账/指标全都对不上。

这里把「位置 → 基金」变成可编辑的配置，存 data/holdings.json：
    {"holdings": {"hs300": {"code": "110020", "name": "...", "unit": "份额", ...}}, "updated": "..."}

口径说明（重要）
----------------
- 持仓市值、浮盈浮亏、账户净值：一律用**我自己那只基金的单位净值**（支付宝口径）。
- 策略目标权重、回测理论净值：仍然用项目默认的 8 个代码算，不去动策略。
- 「项目默认基金同期收益」：用同样 8 个位置的默认代码、同样的目标权重、
  同样月末再平衡重放出来的净值，只用来做对照，说明「换基金换来了多少差异」。
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .config import DATA_DIR, ETF_META, BUCKET_GROUPS

HOLDINGS_FILE = DATA_DIR / "holdings.json"

# 位置 → 所属桶（用于把策略权重按桶汇总，再跟我自己的持仓比）
SLOT_BUCKET = {a: b for b, members in BUCKET_GROUPS.items() for a in members}
# 老配置里 bond_10y / bond_30y 的桶名就是自身，BUCKET_GROUPS 已覆盖，兜底防缺失
for _a in ("hs300", "us_sp500", "credit", "bond_10y", "bond_30y", "gold", "nonferr", "wti"):
    SLOT_BUCKET.setdefault(_a, _a)

SLOTS = ["hs300", "us_sp500", "credit", "bond_10y", "bond_30y", "gold", "nonferr", "wti"]
SLOT_LABEL = {
    "hs300": "增长↑权益(A股)", "us_sp500": "增长↑权益(海外)", "credit": "收益垫(信用债)",
    "bond_10y": "增长↓10Y国债", "bond_30y": "增长↓30Y国债", "gold": "通胀↑黄金",
    "nonferr": "通胀↑有色", "wti": "通胀↑能源",
}

# 桶名（不同策略下桶的粒度不同，统一成这 8 个位置级别的桶来比）
BUCKET_LABEL = SLOT_LABEL


def _default_holdings() -> dict:
    """默认持仓 = 项目原来的 8 个场内代码（与回测口径一致）。"""
    out = {}
    for s in SLOTS:
        meta = ETF_META.get(s, {})
        out[s] = {
            "code": meta.get("code", ""),
            "name": meta.get("name", s),
            "unit": "股",       # 场内按股，100 股/手
            "lot": 100,
            "on": True,
        }
    return out


def load() -> dict:
    """读取持仓配置；不存在/损坏时回落到默认（原版 8 个代码）。"""
    if HOLDINGS_FILE.exists():
        try:
            data = json.loads(HOLDINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data.get("holdings"), dict):
                return data
        except Exception:  # noqa: BLE001
            pass
    return {"holdings": _default_holdings(), "updated": ""}


def save(holdings: dict) -> None:
    HOLDINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    body = {"holdings": holdings, "updated": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")}
    HOLDINGS_FILE.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")


def active(holdings: dict) -> list[str]:
    """启用的位置（有代码且开关打开）。"""
    return [s for s in SLOTS
            if holdings.get(s, {}).get("on", True) and holdings.get(s, {}).get("code")]


def slot_of(code: str, holdings: dict) -> str | None:
    """按基金代码反查位置（用于记账时自动归位）。"""
    for s, h in holdings.items():
        if h.get("code") == code:
            return s
    return None


def reset_to_default() -> dict:
    """恢复成项目默认的 8 个代码。"""
    h = _default_holdings()
    save(h)
    return h


def nav_detail_series(code: str, detail_dir: Path | None = None) -> pd.Series | None:
    """项目自带的净值明细（data/nav_detail/{asset}.csv）→ 复权单位净值。

    8 个默认的场内 ETF 走这里：它们的单位净值已经按支付宝口径整理好
    （平常按单位净值之比，分红日用官方日涨幅），不需要再联网。
    """
    if detail_dir is None:
        detail_dir = DATA_DIR / "nav_detail"
    if not detail_dir.exists():
        return None
    # data/nav_detail/{回测资产}.csv 里只有日期和净值，没有代码列，
    # 所以通过「回测资产 → 默认代码」反查文件（ETF_META 是单一事实源）
    detail_files = {
        "hs300": "hs300", "us_sp500": "us_sp500", "credit": "bond_credit",
        "bond_10y": "bond_10y_etf", "bond_30y": "bond_30y_etf", "gold": "gold",
        "nonferr": "nonferr", "wti": "wti",
    }
    fname = next((f for s, f in detail_files.items() if ETF_META.get(s, {}).get("code") == code), None)
    if not fname:
        return None
    fp = detail_dir / f"{fname}.csv"
    if fp.exists():
        try:
            d = pd.read_csv(fp, parse_dates=["date"]).dropna(subset=["unit_nav"]).set_index("date").sort_index()
            chg = pd.to_numeric(d.get("daily_chg"), errors="coerce")
            chg = chg.fillna(pd.to_numeric(d.get("acc_nav"), errors="coerce").pct_change() * 100)
            r_nav = d["unit_nav"] / d["unit_nav"].shift(1) - 1     # 单位净值之比
            use_chg = r_nav.isna() | ((r_nav - chg / 100).abs() > 0.0005)   # 分红/拆分日改用官方日涨幅
            r = r_nav.where(~use_chg, chg / 100).fillna(0.0)
            idx = (1 + r).cumprod()
            return (idx * float(d["unit_nav"].iloc[-1]) / float(idx.iloc[-1])).rename(code)
        except Exception:  # noqa: BLE001
            return None
    return None


def nav_series(code: str, ensure=False) -> pd.Series:
    """取某只基金的复权净值序列（口径 = 支付宝「历史业绩」）。

    先查项目自带的净值明细（8 个默认 ETF 都有），没有再走 fund_lookup 的场外缓存，
    ensure=True 时允许联网补拉。

    Args:
        code: 6 位基金代码
        ensure: True 时缓存过期会联网拉取（慢）

    Returns:
        index=date 的净值 Series；取不到时为空 Series。
    """
    s = nav_detail_series(code)
    if s is not None and len(s):
        return s
    try:
        import importlib
        FL = importlib.import_module("fund_lookup")
    except ImportError:  # pragma: no cover - 非 Streamlit 环境
        return pd.Series(dtype=float)
    try:
        if ensure:
            FL.ensure_fresh(code)
        out = FL.build_nav(code)          # 注意：不能用 `or`，Series 的真值判断会抛 ValueError
        return out if out is not None and len(out) else pd.Series(dtype=float)
    except Exception as exc:  # noqa: BLE001
        print(f"[holdings] nav_series({code}) 失败: {type(exc).__name__}: {exc}")
        return pd.Series(dtype=float)


def nav_panel(holdings: dict, ensure=False) -> pd.DataFrame:
    """所有持仓基金的单位净值面板（列 = 位置 key）。"""
    cols = {}
    for s in active(holdings):
        code = holdings[s]["code"]
        s_ = nav_series(code, ensure=ensure)
        if len(s_):
            cols[s] = s_
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols).sort_index().ffill()


def slot_weights(w: dict, holdings: dict) -> dict[str, float]:
    """策略权重（按资产 key）→ 按我启用的位置归一化。

    策略算出来的权重是 8 个资产位置的权重，和我持仓的位置是一一对应的，
    直接取用；被我关掉的位置，其权重按比例分给同桶里还开着的位置。
    """
    if not isinstance(w, dict):
        w = dict(w)      # 调用方传进来的可能是 pandas Series
    act = active(holdings)
    if not act:
        return {}
    raw = {s: float(w.get(s, 0) or 0) for s in act}
    total = sum(raw.values())
    if total <= 0:
        return {s: 0.0 for s in act}
    return {s: v / total for s, v in raw.items()}


def default_codes(holdings: dict) -> dict[str, str]:
    """项目默认代码（ETF_META），用于「项目默认基金同期收益」对照。"""
    return {s: ETF_META.get(s, {}).get("code", "") for s in active(holdings)}


def default_unit(code: str, otc: bool | None = None) -> str:
    """猜买卖单位：场外按份额申购，场内按股（100 股一手）。

    Args:
        code: 基金代码，兜底规则：0xxxxx 场外、5/15/16 开头场内
        otc: 由基金申购状态查出来的结论（fund_lookup 的 purchase 表），优先于兜底规则

    只是默认值，判断错了在「我的持仓」表里改「买卖单位」一列即可。
    """
    try:
        import importlib
        FL = importlib.import_module("fund_lookup")
        if otc is None and code:
            otc = FL.is_otc(code)
    except Exception:  # noqa: BLE001
        pass
    if otc is not None:
        return "份额" if otc else "股"
    return "份额" if str(code).startswith("0") else "股"


def is_otc(h: dict) -> bool:
    """场外基金（按份额/金额申购）→ True；场内（按股、100 股一手）→ False。"""
    return str(h.get("unit", "股")) == "份额"


def order_quantity(h: dict, amount: float, nav: float) -> tuple[float, float]:
    """把目标金额换成可下单的数量与实际金额。

    场内：按 100 股取整；场外：按元，受最小申购金额限制（默认 1 元）。
    返回 (数量, 实际金额)；净值为 0/缺失时返回 (0, 0)。
    """
    if not nav or nav <= 0 or amount <= 0:
        return 0.0, 0.0
    if is_otc(h):
        min_amt = float(h.get("min_amount") or 1.0)
        amt = amount if amount >= min_amt else (min_amt if amount > 0 else 0.0)
        return amt / nav, amt
    lot = int(h.get("lot") or 100)
    shares = int(amount / nav / lot) * lot
    return float(shares), shares * nav
