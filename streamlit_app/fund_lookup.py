"""按基金代码/名称查询任意场外基金，并给出与回测同口径的指标。

目的：避免在对话里"瞎算瞎写"——所有数字都在这里从同一份净值数据算出来，
页面上可直接查、可对比、可核对。

数据口径（重要）：
- 复权：平常日子用单位净值之比（精确），分红/拆分日（单位净值跳变，如 003377 在 2023-09-25 -4.59%）改用 chg。
  不直接累乘 chg：chg 只有 2 位小数，长期累乘有舍入误差。
- 区间涨跌与支付宝一致：基准 = 区间起点当天（或之前最近一个交易日）的净值；今年来基准 = 去年最后一个交易日。
- 年化 = (期末/期初)^(1/年数) - 1；波动 = 日收益标准差 × √252；最大回撤在区间内算。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

# 场外基金净值缓存目录。优先级：环境变量 AW_FUND_NAV_DIR → 本机调仓脚本目录 rebal/nav（与之共用，避免重复拉取）
# → 项目内 data/fund_nav（线上部署时用这个，见 scripts/build_web.py）
_PROJECT = Path(__file__).resolve().parent.parent
_LOCAL_REBAL = Path.home() / "WorkBuddy" / "2026-10-23-10-28-09" / "rebal" / "nav"
NAV_DIR = Path(os.environ.get("AW_FUND_NAV_DIR") or (_LOCAL_REBAL if _LOCAL_REBAL.exists() else _PROJECT / "data" / "fund_nav"))
PURCHASE_CSV = NAV_DIR.parent / "purchase_all.csv" if NAV_DIR == _LOCAL_REBAL else NAV_DIR / "purchase_all.csv"   # 全市场申购状态
NAME_CACHE = Path(__file__).resolve().parent / "_fund_names.json"   # 代码→名称缓存
PALETTE = ["#2563EB", "#DC2626", "#059669", "#D97706", "#7C3AED",
           "#0891B2", "#DB2777", "#65A30D", "#EA580C", "#4F46E5"]


def _ensure_project_path():
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def load_cached(code: str) -> pd.DataFrame | None:
    """读本地缓存的净值文件；返回 date/nav/chg 三列，无则 None。"""
    p = NAV_DIR / f"{code}.csv"
    if not p.exists():
        return None
    try:
        d = pd.read_csv(p, parse_dates=["date"])
        if not {"date", "nav", "chg"}.issubset(d.columns):
            return None
        return d.set_index("date").sort_index()[["nav", "chg"]]
    except Exception:
        return None


def cached_codes() -> list[str]:
    if not NAV_DIR.exists():
        return []
    return sorted(p.name[:-4] for p in NAV_DIR.glob("*.csv"))


# 模块级缓存：Streamlit 每次交互都会整页重跑，名录(2.8万条)和净值文件不能每次重读。
# 进程内缓存即可；fetch_fund / refresh_names 成功后会失效对应缓存。
_NM: dict | None = None       # 全市场名录
_PM: dict | None = None       # 申购状态表
_POOL: pd.DataFrame | None = None  # 本地缓存基金池


def _purchase_map() -> dict:
    """代码 → (名称, 类型, 申购状态, 日限额, 申购费)。"""
    global _PM
    if _PM is not None:
        return _PM
    out = {}
    if not PURCHASE_CSV.exists():
        return out
    try:
        d = pd.read_csv(PURCHASE_CSV, dtype=str)
        for _, r in d.iterrows():
            c = str(r.get("基金代码", "")).strip()
            if not c:
                continue
            lim = r.get("日累计限定金额", "")
            try:
                lim = float(lim)
            except Exception:
                lim = None
            out[c] = {"name": str(r.get("基金简称", "")).strip(),
                      "type": str(r.get("基金类型", "")).strip(),
                      "buy": str(r.get("申购状态", "")).strip(),
                      "limit": lim,
                      "fee": str(r.get("手续费", "")).strip()}
    except Exception:
        pass
    _PM = out
    return out


def name_map() -> dict:
    """代码 → 名称。优先用 akshare 全市场基金名录的本地缓存，没有名字则回落到空串。"""
    global _NM
    if _NM is not None:
        return _NM
    out = {}
    if NAME_CACHE.exists():
        try:
            out = json.loads(NAME_CACHE.read_text(encoding="utf-8"))
        except Exception:
            out = {}
    if not out:
        try:
            import akshare as ak
            df = ak.fund_name_em()
            out = dict(zip(df["基金代码"].astype(str), df["基金简称"].astype(str)))
            NAME_CACHE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        except Exception:
            out = {}
    _NM = out
    return out


def refresh_names() -> str:
    """强制重拉全市场基金名录（第一次约需十几秒）。"""
    global _NM
    try:
        import akshare as ak
        df = ak.fund_name_em()
        out = dict(zip(df["基金代码"].astype(str), df["基金简称"].astype(str)))
        NAME_CACHE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        _NM = out
        return f"已更新 {len(out)} 只基金名称"
    except Exception as e:
        return f"拉取失败：{str(e)[:120]}"


def fund_name(code: str) -> str:
    m = _purchase_map().get(code)
    if m and m["name"]:
        return m["name"]
    return name_map().get(code, "")


def pool() -> pd.DataFrame:
    """可立即画的基金池（本地已有净值缓存的）。"""
    global _POOL
    if _POOL is not None:
        return _POOL
    rows = []
    pm = _purchase_map()
    for c in cached_codes():
        d = load_cached(c)
        m = pm.get(c, {})
        rows.append({"代码": c, "名称": m.get("name", "") or fund_name(c), "类型": m.get("type", ""),
                     "起": d.index[0].date().isoformat() if d is not None and len(d) else "",
                     "止": d.index[-1].date().isoformat() if d is not None and len(d) else "",
                     "申购": m.get("buy", ""), "日限额": m.get("limit"), "申购费": m.get("fee", "")})
    _POOL = pd.DataFrame(rows)
    return _POOL


def search_local(kw: str) -> pd.DataFrame:
    kw = (kw or "").strip()
    if not kw:
        return pool()
    p = pool()
    name_hit = p["名称"].fillna("").str.contains(kw, case=False, regex=False)
    code_hit = p["代码"].str.contains(kw, regex=False)
    return p[name_hit | code_hit]


def fetch_fund(code: str) -> tuple[bool, str]:
    """用 akshare 拉一只基金的净值走势并写入缓存。成功返回 (True, 说明)。"""
    code = (code or "").strip()
    if not code.isdigit() or len(code) != 6:
        return False, f"“{code}”不是 6 位基金代码"
    p = NAV_DIR / f"{code}.csv"
    if p.exists() and not is_stale(code):
        return True, "本地已是最新"
    name = name_map().get(code, "")
    if name.endswith("(后端)"):
        front = [c for c, n in name_map().items() if n == name[:-4] and c != code]
        hint = f"，请改选前端代码 {front[0]}（同一只基金，净值相同）" if front else ""
        return False, f"{code} 是后端收费份额，东方财富不提供单独净值{hint}"
    try:
        import akshare as ak
        df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
        df = df.rename(columns={"净值日期": "date", "单位净值": "nav", "日增长率": "chg"})
        need = ["date", "nav", "chg"]
        if not set(need).issubset(df.columns):
            return False, f"返回字段不含 {need}，实际 {list(df.columns)[:8]}"
        NAV_DIR.mkdir(parents=True, exist_ok=True)
        df[need].to_csv(p, index=False)
        global _POOL
        _POOL = None                    # 新基金入库，基金池缓存失效
        # 注意：不失效 _OPTS——选项文案若在拉取后变化（加 ✓），selectbox 会因找不到当前值而重置选择
        return True, f"已拉取 {len(df)} 条（{df['date'].min()} ~ {df['date'].max()}）"
    except Exception as e:
        msg = str(e)
        if "doctype" in msg.lower() or "Unexpected token" in msg:
            # 东财对已清盘/停止运作/无净值的代码返回 HTML 页面，akshare 按 JS 解析时报这个错
            return False, f"{code} 在东方财富没有净值数据（可能已清盘、转型或暂停披露）"
        return False, f"{code} 拉取失败：{msg.splitlines()[0][:120]}"


def expected_nav_date(now: pd.Timestamp | None = None) -> pd.Timestamp:
    """此刻应当已公布的最新净值日：工作日 21:00 后算当天，否则上一个工作日（不含节假日判断）。"""
    now = now or pd.Timestamp.now()
    d = now.normalize() if (now.weekday() < 5 and now.hour >= 21) else now.normalize() - pd.Timedelta(days=1)
    while d.weekday() >= 5:
        d -= pd.Timedelta(days=1)
    return d


def is_stale(code: str) -> bool:
    """缓存是否落后：最后一条净值早于应公布日，且距上次拉取已超过 1 小时（节假日/QDII 晚一天公布时不反复请求）。"""
    p = NAV_DIR / f"{code}.csv"
    if not p.exists():
        return True
    d = load_cached(code)
    if d is None or d.empty:
        return True
    if d.index[-1] >= expected_nav_date():
        return False
    return (pd.Timestamp.now() - pd.Timestamp.fromtimestamp(p.stat().st_mtime)) > pd.Timedelta(hours=1)


def ensure_fresh(code: str) -> tuple[bool, str]:
    """页面展示前调用：没有缓存或缓存落后就拉取；已最新直接返回。"""
    return fetch_fund(code) if is_stale(code) else (True, "本地已是最新")


def _score(q: str, name: str) -> float:
    """名称匹配度：0~1。用最长公共子串占比，避免"易方达新综合"这种漏字/换序匹配不上。"""
    q, name = q.lower(), (name or "").lower()
    if not q or not name:
        return 0.0
    if q in name:
        return 0.6 + 0.4 * len(q) / len(name)
    # 逐字命中率
    hit = sum(1 for ch in set(q) if ch in name)
    return 0.5 * hit / max(len(set(q)), 1)


def name_candidates(kw: str, limit: int = 10) -> pd.DataFrame:
    """搜索提示：本地缓存 + 全市场名录（约 2.8 万只）合并出候选，按匹配度排序，缓存优先。

    支持三种输入：名称子串 / 模糊名（漏字换序）/ 代码前缀（如 "161" 提示 161 开头的基金）。
    """
    kw = (kw or "").strip()
    cols = ["代码", "名称", "来源"]
    if not kw:
        return pd.DataFrame(columns=cols)
    rows, cached = [], set()
    digit_kw = kw.isdigit()
    for _, r in pool().iterrows():
        if digit_kw and r["代码"].startswith(kw):
            sc = 1.0                                   # 已缓存的代码前缀命中，排最前
        else:
            sc = _score(kw, r["名称"]) if r["名称"] else 0.0
        if sc > 0:
            rows.append({"代码": r["代码"], "名称": r["名称"], "来源": "已缓存", "_s": sc + 0.1})
            cached.add(r["代码"])
    nm = name_map()
    kw_l = kw.lower()
    for c, n in nm.items():
        if c in cached:
            continue
        if digit_kw:
            if c.startswith(kw):
                rows.append({"代码": c, "名称": n, "来源": "全市场名录", "_s": 0.9})
            continue
        if not n:
            continue
        n_l = n.lower()
        if kw_l in n_l:
            sc = 0.6 + 0.4 * len(kw_l) / len(n_l)
        elif len(kw) >= 2:
            sc = _score(kw, n)
            if sc < 0.75:
                continue
        else:
            continue
        rows.append({"代码": c, "名称": n, "来源": "全市场名录", "_s": sc})
    d = pd.DataFrame(rows)
    if d.empty:
        return pd.DataFrame(columns=cols)
    d = d.sort_values("_s", ascending=False).drop_duplicates("代码").head(limit)
    return d[cols]


_OPTS: list | None = None       # 全市场 selectbox 选项


def all_options() -> list[str]:
    """全市场名录 → ["代码 名称", ...] 选项列表，供 selectbox 输入即提示（前端实时过滤）。

    本地已有净值缓存的排最前并加 ✓ 前缀。进程内缓存，拉取新基金后由 fetch_fund 失效重建。
    """
    global _OPTS
    if _OPTS is not None:
        return _OPTS
    nm = name_map()
    cached = set(cached_codes())
    head = [f"✓ {c} {nm.get(c, '')}".rstrip() for c in sorted(cached)]
    # 后端收费份额（名称带"(后端)"，约 190 只）在东财没有独立净值页，拉取必失败；
    # 与同名前端份额是同一只基金、净值相同，直接不放进选项，选前端份额即可
    tail = [f"{c} {n}".rstrip() for c, n in nm.items() if c not in cached and not n.endswith("(后端)")]
    _OPTS = head + tail
    return _OPTS


def option_code(opt: str) -> str | None:
    """从 all_options 的选项里取出 6 位代码（兼容 ✓ 前缀）。"""
    if not opt:
        return None
    parts = opt.replace("✓ ", "").split()
    return parts[0] if parts and parts[0].isdigit() and len(parts[0]) == 6 else None


def resolve(kw: str, pool_df: pd.DataFrame | None = None) -> str | None:
    """把"代码或名称"解析成 6 位代码。名称只接受唯一高分命中，否则返回 None 交给调用方提示。"""
    kw = (kw or "").strip()
    if not kw:
        return None
    if kw.isdigit() and len(kw) == 6:
        return kw
    c = name_candidates(kw, limit=5)
    if len(c) == 0:
        return None
    top = c.iloc[0]
    # 已缓存的最高分直接采用；来自全市场名录则要求明显领先第二名
    if top["来源"] == "已缓存":
        return str(top["代码"])
    return str(top["代码"]) if len(c) == 1 else None


def adjusted_returns(nav: pd.Series, chg: pd.Series) -> pd.Series:
    """每日复权收益率（小数）。

    - 平常日子：单位净值之比 nav_t / nav_{t-1} − 1，精确到净值的 4 位小数；
    - 分红/拆分日：单位净值会跳变（如 003377 在 2023/09/25 −4.59%），此时改用官方日增长率 chg（已含分红）。
    判定：两者相差超过 0.05 个百分点即视为分红/拆分日。
    不直接累乘 chg：chg 只保留 2 位小数，长期累乘有舍入误差（161119 近6月 2.10% vs 支付宝 2.13%）。
    """
    nav = pd.to_numeric(nav, errors="coerce")
    chg = pd.to_numeric(chg, errors="coerce") / 100.0
    r_nav = nav / nav.shift(1) - 1
    use_chg = r_nav.isna() | ((r_nav - chg).abs() > 0.0005)
    r = r_nav.where(~use_chg, chg)
    return r.fillna(0.0)


def build_index(code: str) -> pd.Series | None:
    """复权总收益指数（起点 1.0），口径见 adjusted_returns。"""
    d = load_cached(code)
    if d is None or len(d) < 2:
        return None
    idx = (1 + adjusted_returns(d["nav"], d["chg"])).cumprod()
    idx.name = code
    return idx


def build_nav(code: str) -> pd.Series | None:
    """复权净值：最新值 = 最新单位净值；往前按复权收益率倒推。

    无分红区间里任意两天之比 = 单位净值之比，所以区间涨跌和支付宝「历史业绩」完全一致。
    """
    idx = build_index(code)
    if idx is None:
        return None
    d = load_cached(code)
    nav = pd.to_numeric(d["nav"], errors="coerce").reindex(idx.index).dropna()
    nav = nav[nav > 0]
    if len(nav):
        idx = idx * (float(nav.iloc[-1]) / float(idx.loc[nav.index[-1]]))
    idx.name = code
    return idx


def backtest_index(asset: str) -> pd.Series | None:
    """回测资产（hs300/credit/...）的价格序列，起点归一到 1.0，可与基金指数叠加。"""
    _ensure_project_path()
    try:
        from allweather.data import load_panel  # 项目数据层
        panel = load_panel()
        if asset not in panel.columns:
            return None
        s = pd.to_numeric(panel[asset], errors="coerce").dropna()
        if len(s) < 30:
            return None
        s = s / s.iloc[0]
        s.name = asset
        return s
    except Exception:
        return None


def _max_drawdown(idx: pd.Series) -> float:
    return float((idx / idx.cummax() - 1).min())


def stats(idx: pd.Series, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> dict:
    """区间指标：区间收益、年化、波动、最大回撤、最差日。"""
    x = idx.dropna()
    if start is not None:
        x = x[x.index >= pd.Timestamp(start)]
    if end is not None:
        x = x[x.index <= pd.Timestamp(end)]
    if len(x) < 2:
        return {}
    yrs = max((x.index[-1] - x.index[0]).days / 365.25, 1 / 365.25)
    total = float(x.iloc[-1] / x.iloc[0] - 1)
    ret = x.pct_change(fill_method=None).dropna()
    vol = float(ret.std() * np.sqrt(252)) if len(ret) > 2 else float("nan")
    cagr = float((1 + total) ** (1 / yrs) - 1) if yrs > 0 else float("nan")
    return {"区间收益": total, "年化": cagr, "波动": vol, "最大回撤": _max_drawdown(x), "最差日": float(ret.min()) if len(ret) else float("nan"),
            "起": x.index[0], "止": x.index[-1], "年数": yrs}


def yearly(idx: pd.Series) -> pd.DataFrame:
    """逐年收益与年内最大回撤（日历年）。"""
    x = idx.dropna()
    rows = []
    for y, g in x.groupby(x.index.year):
        if len(g) < 10:
            continue
        r = (float(g.iloc[-1] / g.iloc[0] - 1) * 100, _max_drawdown(g) * 100)
        rows.append({"年份": int(y), "收益%": round(r[0], 2), "最大回撤%": round(r[1], 2),
                     "交易日": len(g)})
    return pd.DataFrame(rows)


def to_chart_df(series_map: dict[str, pd.Series], start=None, end=None,
                freq: str = "日", mode: str = "累计") -> pd.DataFrame:
    """多只基金 → 长表 DataFrame（date / 基金 / 值），供 Altair 画多条线。"""
    frames = []
    for name, s in series_map.items():
        if s is None:
            continue
        x = s.dropna().copy()
        if start is not None:
            x = x[x.index >= pd.Timestamp(start)]
        if end is not None:
            x = x[x.index <= pd.Timestamp(end)]
        if len(x) < 2:
            continue
        if freq in ("月", "年"):
            x = x.resample("ME" if freq == "月" else "YE").last()
        if mode == "累计":
            x = x / x.iloc[0]
        else:                      # 每期收益（%）
            x = x.pct_change(fill_method=None) * 100
            x = x.dropna()
        if len(x) == 0:
            continue
        frames.append(pd.DataFrame({"date": x.index, "基金": name, "值": x.values}))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["date", "基金", "值"])
