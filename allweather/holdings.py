"""我的持仓：把策略的 8 个资产位置映射到**我自己实际买的基金**。

为什么要有这一层
----------------
策略（V3c / V3-B）算的是「资产位置」的目标权重：增长↑权益(A股)、增长↑权益(海外)、
收益垫、增长↓10Y、增长↓30Y、通胀↑黄金、通胀↑有色、通胀↑能源。
原版代码把这 8 个位置写死了 8 个场内 ETF 代码，实际买入的基金一换，
建仓/调仓/记账/指标全都对不上。

这里把「位置 → 基金」变成可编辑的配置，存 data/holdings.json：
    {"holdings": {"hs300": {"on": true, "funds": [
        {"code": "110020", "name": "...", "unit": "份额", "lot": 1,
         "min_amount": 10, "share": 0.6},
        {"code": "000961", "name": "...", "share": 0.4}]}}, "updated": "..."}

一个位置可以挂**多只**同类基金（share = 该位置内资金占比，全为 0 时按等权），
也可以一只都不挂（funds 为空 = 这个位置暂时不持有，权重让给同桶别的位置）。
旧的单只写法 {"code": "...", "unit": "..."} 在 load/save 时自动迁移成 funds 单元素。

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

# 单只基金的可配置字段（位置 dict 里 funds 的元素）
_FUND_KEYS = ("code", "name", "unit", "lot", "min_amount", "share")


def _fund(f: dict) -> dict:
    """把一只基金补齐成完整字段（缺省：场内按股 100 一手、场外按份额 1 元起）。"""
    code = str(f.get("code") or "").strip()
    unit = str(f.get("unit") or "股")
    return {
        "code": code,
        "name": str(f.get("name") or ""),
        "unit": unit,
        "lot": int(f.get("lot") or (100 if unit == "股" else 1)),
        "min_amount": float(f.get("min_amount") or 1.0),
        "share": float(f.get("share") or 0.0),
    }


def _norm_slot(h: dict | None) -> dict:
    """位置配置规范化：统一成 {"on": bool, "funds": [...]}；旧的单只结构自动迁移。"""
    h = h if isinstance(h, dict) else {}
    raw = h.get("funds")
    if not isinstance(raw, list):
        raw = [{k: h[k] for k in _FUND_KEYS if h.get(k) is not None}] if h.get("code") else []
    out = [_fund(f) for f in raw if isinstance(f, dict) and str(f.get("code") or "").strip()]
    # 占比全为 0（新加的第二只、或手改过）→ 等权，避免整只基金分不到钱
    if out and sum(f["share"] for f in out) <= 0:
        for f in out:
            f["share"] = round(1.0 / len(out), 6)
    return {"on": bool(h.get("on", True)), "funds": out}


def funds(h: dict | None) -> list[dict]:
    """某位置挂的所有基金（兼容旧的单只 {"code": ...} 写法，保证老配置能读）。"""
    if not isinstance(h, dict):
        return []
    raw = h.get("funds")
    if isinstance(raw, list):
        return [_fund(f) for f in raw if isinstance(f, dict) and str(f.get("code") or "").strip()]
    if str(h.get("code") or "").strip():
        return [_fund({k: h[k] for k in _FUND_KEYS if h.get(k) is not None})]
    return []


def codes(h: dict | None) -> list[str]:
    """某位置挂的基金代码列表（可能 0 只、1 只、多只）。"""
    return [f["code"] for f in funds(h)]


def share_of(h: dict | None) -> list[float]:
    """位置内各基金的资金占比，按顺序与 funds() 对齐，已归一化到 1。"""
    fs = funds(h)
    if not fs:
        return []
    raw = [max(0.0, float(f.get("share") or 0.0)) for f in fs]
    total = sum(raw)
    if total <= 0:
        return [1.0 / len(fs)] * len(fs)
    return [x / total for x in raw]


def all_codes(holdings: dict) -> list[str]:
    """配置里出现过的全部基金代码（去重、保序）。"""
    out: list[str] = []
    for s in SLOTS:
        for c in codes(holdings.get(s, {})):
            if c not in out:
                out.append(c)
    return out


def fund_meta(holdings: dict, code: str) -> tuple[str | None, dict]:
    """代码 → (位置, 该基金配置)；配置里没有时返回 (None, {})。"""
    for s in SLOTS:
        for f in funds(holdings.get(s, {})):
            if f["code"] == code:
                return s, f
    return None, {}


def add_fund(h: dict | None, code: str, name: str = "", unit: str | None = None) -> dict:
    """往某个位置加一只基金（已存在则原样返回）；占比按等权重算。

    unit 为空时按代码猜（场外份额 / 场内股），猜错了在「我的持仓」表里改。
    """
    slot = _norm_slot(h)
    if any(f["code"] == code for f in slot["funds"]):
        return slot
    slot["funds"].append(_fund({"code": code, "name": name or code,
                               "unit": unit or default_unit(code)}))
    for f in slot["funds"]:
        f["share"] = round(1.0 / len(slot["funds"]), 6)
    return slot


def remove_fund(h: dict | None, code: str) -> dict:
    """从某个位置删掉一只基金；删空后该位置变成「不持有」，其余占比保持原样。"""
    slot = _norm_slot(h)
    slot["funds"] = [f for f in slot["funds"] if f["code"] != code]
    if slot["funds"] and sum(f["share"] for f in slot["funds"]) <= 0:
        for f in slot["funds"]:
            f["share"] = round(1.0 / len(slot["funds"]), 6)
    return slot


def _default_holdings() -> dict:
    """默认持仓 = 项目原来的 8 个场内代码（与回测口径一致）。"""
    out = {}
    for s in SLOTS:
        meta = ETF_META.get(s, {})
        out[s] = {"on": True, "funds": [_fund({
            "code": meta.get("code", ""),
            "name": meta.get("name", s),
            "unit": "股",       # 场内按股，100 股/手
            "lot": 100,
        })]}
    return out


def load() -> dict:
    """读取持仓配置；不存在/损坏时回落到默认（原版 8 个代码）。"""
    if HOLDINGS_FILE.exists():
        try:
            data = json.loads(HOLDINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data.get("holdings"), dict):
                return {"holdings": {s: _norm_slot(v) for s, v in data["holdings"].items()},
                        "updated": data.get("updated", "")}
        except Exception:  # noqa: BLE001
            pass
    return {"holdings": _default_holdings(), "updated": ""}


def save(holdings: dict) -> None:
    HOLDINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    body = {"holdings": {s: _norm_slot(v) for s, v in (holdings or {}).items()},
            "updated": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")}
    HOLDINGS_FILE.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")


def active(holdings: dict) -> list[str]:
    """启用的位置（开关打开且至少挂了一只基金）。"""
    return [s for s in SLOTS
            if holdings.get(s, {}).get("on", True) and codes(holdings.get(s, {}))]


def slot_of(code: str, holdings: dict) -> str | None:
    """按基金代码反查位置（用于记账时自动归位）。"""
    for s, h in holdings.items():
        if code in codes(h):
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
    """所有持仓基金的净值面板（列 = **基金代码**，一个位置多只时就有多列）。"""
    cols = {}
    for s in active(holdings):
        for code in codes(holdings[s]):
            if code in cols:
                continue
            s_ = nav_series(code, ensure=ensure)
            if len(s_):
                cols[code] = s_
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


def plan_invest(slots: list[dict], amount: float) -> list[dict]:
    """定投分配：把一笔新钱按目标权重分下去，**只买不卖**。

    和「再平衡」的区别在钱的总量：
    - 再平衡：总资产不变，把现有仓位调回目标比例，可能同时有买有卖；
    - 定投：新增一笔钱（先进现金），目标市值要按**投后总额**重算，
      谁差得多谁多拿，已经超配的位置一分不给，剩下的再按目标权重摊掉。

    首次定投（还没有持仓）时缺口正好是 ``w × amount``，退化成「按目标权重均分」。

    Args:
        slots: [{"slot": 位置 key, "w": 位置目标权重(0~1),
                 "mv": 该位置当前市值, "items": [{"code", "x"(位置内占比), ...}]}]
        amount: 这次投入的金额（元）

    Returns:
        [{"slot", "code", "x", "amount"}]，amount 合计 ≈ 传入金额。
    """
    amount = float(amount or 0)
    if amount <= 0 or not slots:
        return []
    # 只有挂了基金、且净值齐全的位置才买得动；没挂基金/缺净值的位置仍计入总市值
    # （它的钱是真实存在的），但它的那份预算要让给能买的位置，否则钱会分不完。
    buyable = [s for s in slots if s.get("items")]
    if not buyable:
        return []
    wsum = sum(float(s.get("w") or 0) for s in buyable)
    if wsum <= 0:                       # 权重全 0（策略没给）→ 均分，避免整笔钱没处去
        wsum = float(len(buyable))
        w_of = {s["slot"]: 1.0 / len(buyable) for s in buyable}
    else:
        w_of = {s["slot"]: float(s.get("w") or 0) / wsum for s in buyable}
    base = sum(float(s.get("mv") or 0) for s in slots)
    target_total = base + amount

    need = {s["slot"]: max(0.0, w_of[s["slot"]] * target_total - float(s.get("mv") or 0))
            for s in buyable}
    tot_need = sum(need.values())
    if tot_need <= 0:                   # 全都超配（例如刚大跌后按市值算不再缺）→ 按权重摊
        alloc = {k: amount * w for k, w in w_of.items()}
    elif tot_need >= amount:            # 缺口比这笔钱还大 → 按缺口比例分
        alloc = {k: amount * v / tot_need for k, v in need.items()}
    else:                               # 缺口都补上还有剩 → 剩下的按目标权重摊
        left = amount - tot_need
        alloc = {k: need[k] + left * w_of[k] for k in need}

    out = []
    for s in buyable:
        a = float(alloc.get(s["slot"], 0.0))
        if a <= 0:
            continue
        items = [it for it in (s.get("items") or []) if it.get("code")]
        if not items:
            continue
        xs = sum(float(it.get("x") or 0) for it in items) or float(len(items))
        for it in items:
            x = float(it.get("x") or 0) or 1.0
            out.append({"slot": s["slot"], "code": it["code"], "x": x,
                        "amount": a * x / xs})
    return out


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


def period_performance(daily: pd.DataFrame, flows: pd.Series | None = None,
                       freq: str = "Y") -> list[dict]:
    """账户按年 / 按月切段：每段赚了多少钱、收益率多少、期内最深回撤多少。

    daily：index 是日期，必须含 equity（总资产）和 nav（账户单位净值）。
      nav 是「总资产 ÷ 份额」，转入按当时净值折份额，所以 **nav 本身已经扣掉入金的影响**，
      `nav 末期 / nav 期初 − 1` 就是这段时间真实的收益率。
    flows：index 是日期、值是当天净入金（转入为正、转出为负）；缺省当 0。

    每段的算法：
      期初总资产 = 上一段最后一个交易日的总资产（第一段 = 当天总资产 − 当天净入金，
                   即「打钱进来之前」的账户，通常是 0）
      收益（元） = 期末总资产 − 期初总资产 − 期内净入金
      收益率     = 期末 nav / 期初 nav − 1（第一段期初 nav 取 1.0，账户建仓日按面值起步）
      期内回撤   = 期内 nav 相对「期内最高点」的最大跌幅（每段重新起算，不跨段累计）

    收益（元）和收益率各回答一个问题：前者是「这段时间账户多/少了多少钱」，
    后者是「不管中间加了多少钱，这份钱本身涨跌了几个点」。加了钱不等于赚了钱，
    所以两者一定对不上，表里要并排给。

    返回**最新的一段在前**，每项：period / start / end / eq0 / eq1 / flow / pnl / ret / mdd / days。
    """
    if daily is None or len(daily) == 0:
        return []
    d = daily.copy()
    if "equity" not in d.columns or "nav" not in d.columns:
        return []
    d = d.sort_index()
    f = (flows.reindex(d.index).fillna(0.0) if flows is not None
         else pd.Series(0.0, index=d.index))
    freq = "Y" if str(freq).upper().startswith("Y") else "M"
    key = pd.Series(d.index, index=d.index).dt.to_period(freq)
    out: list[dict] = []
    prev_eq = prev_nav = None
    for per, block in d.groupby(key, sort=True):
        eq = block["equity"].astype(float)
        nav = block["nav"].astype(float)
        flow = float(f.loc[block.index].sum())
        if prev_eq is None:
            # 第一段：期初 = 第一天总资产 − 当天入金（否则「刚转入就建仓」会被算成一笔收益）
            first_flow = float(f.loc[block.index[0]])
            eq0 = float(eq.iloc[0]) - first_flow
            nav0 = 1.0          # 建仓日按面值 1.0 起步，第一段把当天的手续费一起算进收益
        else:
            eq0, nav0 = prev_eq, prev_nav
        eq1 = float(eq.iloc[-1])
        nav1 = float(nav.iloc[-1])
        peak = nav.cummax()
        mdd = float((nav / peak - 1).min()) if len(nav) else 0.0
        out.append({
            "period": (f"{per.year}年" if freq == "Y" else f"{per.year}年{per.month}月"),
            "start": block.index[0], "end": block.index[-1],
            "eq0": eq0, "eq1": eq1, "flow": flow,
            "pnl": eq1 - eq0 - flow,
            "ret": (nav1 / nav0 - 1) if nav0 > 0 else 0.0,
            "mdd": mdd, "days": int(len(block)),
        })
        prev_eq, prev_nav = eq1, nav1
    return list(reversed(out))
