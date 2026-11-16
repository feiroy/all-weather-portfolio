"""自检：一次把「页面上的数对不对」的几条硬约束全查一遍。

为什么要有这个
--------------
2026-11-16 一天之内连着出了四五个症状（收益率用净值、今日收益为空、页面变慢、净值曲线是直线），
每次都是靠用户截图 + 一句话反问才定位到根因。这些根因其实都能用同一个脚本查出来：

- 净值有没有停（`nav_freshness`）
- 行情有没有到（`quote.spots_now`）
- 缓存是不是旧口径（`Portfolio.used_spot`）
- 三处口径是否自洽（`plan.total` vs `equity` 末端、`by_day` 合计 vs 头卡「今日」）

用法：`scripts/doctor.py`（命令行，红/黄/绿），或 `GET /api/selftest`（JSON）。
"""
from __future__ import annotations

from datetime import date

OK, WARN, BAD = "ok", "warn", "bad"
_ICON = {OK: "绿", WARN: "黄", BAD: "红"}


def _c(cid: str, level: str, title: str, detail: str = "", fix: str = "") -> dict:
    return {"id": cid, "level": level, "icon": _ICON[level], "title": title, "detail": detail, "fix": fix}


def _days(a, b) -> int:
    return (b.date() - a.date()).days if hasattr(a, "date") else (b - a).days


# ------------------------------------------------------------------ 数据文件
def data_checks() -> list[dict]:
    """五组数据文件各自最新到哪天 —— 少扫一组，就会出「文件更新了但页面不动」。"""
    from .dataversion import data_files, newest

    out, groups = [], data_files()
    newest_map = newest(groups)
    today = date.today()
    for name, files in groups.items():
        mt, fn = newest_map.get(name, (0.0, ""))
        if not files:
            out.append(_c(f"data.{name}", WARN, f"{name}：没有文件", "这一组是空的，相关功能会没数据"))
            continue
        d = date.fromtimestamp(mt)
        lag = (today - d).days
        level = OK if lag <= 1 else (WARN if lag <= 3 else BAD)
        out.append(_c(f"data.{name}", level, f"{name}：{len(files)} 个文件，最新 {d:%Y/%m/%d}（{fn}）",
                      fix="" if level == OK else "点页面右上「更新数据」，或跑 scripts/doctor.py --fix"))
    return out


# ------------------------------------------------------------------ 净值新鲜度
def nav_checks(acct: dict) -> list[dict]:
    from . import holdings as HG

    codes: set[str] = {str(t.get("code") or "") for t in (acct.get("trades") or [])}
    try:
        codes |= set(HG.all_codes(acct.get("holdings") or {}))
    except Exception:  # noqa: BLE001
        pass
    codes.discard("")
    out, bad, lagging = [], [], []
    try:
        import fund_lookup as FL
        expect = FL.expected_nav_date().date()
    except Exception:  # noqa: BLE001
        expect = date.today()
    for code in sorted(codes):
        last, stale = HG.nav_freshness(code)
        if not last:
            bad.append(code)
            out.append(_c(f"nav.{code}", BAD, f"{code} 没有净值", "这只基金一条净值都取不到，图表会空"))
            continue
        gap = (expect - date.fromisoformat(last)).days
        if gap > 7:
            bad.append(code)
            out.append(_c(f"nav.{code}", BAD, f"{code} 净值停在 {last}（落后 {gap} 天）",
                          "面板会把它 ffill 成一条直线，市值和今日收益都会算错",
                          "点「更新数据」，或 scripts/doctor.py --fix"))
        elif gap > 0:
            lagging.append(f"{code}({gap}天)")
    if lagging:
        out.append(_c("nav.lag", WARN, "有基金的净值还没公布：" + "、".join(lagging),
                      "场外净值一般 21:00 后才出，QDII 还会晚一天；不是故障"))
    if not bad and not lagging:
        out.append(_c("nav.ok", OK, f"净值都在最新（{len(codes)} 只）"))
    return out


# ------------------------------------------------------------------ 行情
def quote_checks(acct: dict, blocking: bool = False) -> list[dict]:
    """场内标的能不能拿到市价。拿不到就退回净值估值 —— 不算错，但要知道。"""
    from . import holdings as HG
    from . import quote as QUOTE

    codes = sorted({str(t.get("code") or "") for t in (acct.get("trades") or [])} - {""})
    need = [c for c in codes if not HG.is_otc(HG.fund_meta(acct.get("holdings") or {}, c)[1] or {})]
    if not need:
        return [_c("quote.na", OK, "没有场内持仓，不需要行情")]
    got = QUOTE.snapshot(need) if blocking else {c: QUOTE.premium_of(c) for c in need}
    miss = [c for c in need if not (got.get(c) or {}).get("price")]
    out = [_c("quote.ok", OK, f"场内市价齐了（{len(need) - len(miss)}/{len(need)}）",
              "、" .join(f"{c} {got[c]['price']}" for c in need if c not in miss))]
    if miss:
        out = [_c("quote.miss", WARN, "这几只拿不到市价：" + "、".join(miss),
                  "估值会退回净值，折溢价徽标不显示",
                  "断网或东财接口没回，过一会儿再试")]
    # 折溢价只提示、不判错：QDII 暂停申购时溢价长期挂着是正常的
    wide = []
    for c in need:
        row = got.get(c) or {}
        p = row.get("premium")
        if p is not None and abs(p) > 0.05:
            wide.append(f"{c} {p * 100:+.2f}%")
    if wide:
        out.append(_c("quote.premium", WARN, "折溢价偏大：" + "、".join(wide),
                      "QDII / 暂停申购的品种常见，买之前多看一眼，不是数据错"))
    return out


# ------------------------------------------------------------------ 口径自洽
def value_checks(P) -> list[dict]:
    """三处数字必须同一个口径，否则用户会看到「总资产和日历对不上」这种无解问题。"""
    out = []
    total = float(P.plan.get("total") or 0.0)
    eq = float(P.daily["equity"].iloc[-1]) if len(P.daily) else 0.0
    diff = abs(total - eq)
    out.append(_c("value.total", OK if diff <= 1.0 else BAD,
                  f"总资产 {total:,.2f} vs 曲线末端 {eq:,.2f}（差 {diff:.2f}）",
                  fix="" if diff <= 1.0 else "plan 与 equity 不同口径：检查 _replay 最后一天是否用市价"))

    today = float(P.plan.get("today") or 0.0)
    rows = (P.by_day.get(P.last) or {}).values()
    s = float(sum(r[0] for r in rows))
    d = abs(today - s)
    out.append(_c("value.today", OK if d <= 0.01 else BAD,
                  f"头卡今日 {today:,.2f} vs 收益日历合计 {s:,.2f}（差 {d:.2f}）",
                  fix="" if d <= 0.01 else "两处取数不一致：`_today_total` 要和 by_day 同一份"))

    bad_mv = []
    for it in P.items():
        sh, px = float(it.get("shares") or 0.0), float(it.get("px") or 0.0)
        mv = float(it.get("mv") or 0.0)
        if sh > 0 and abs(mv - sh * px) > max(0.05, mv * 1e-4):
            bad_mv.append(f"{it['code']} 市值 {mv:,.2f} ≠ {sh:g}×{px}")
    out.append(_c("value.mv", OK if not bad_mv else BAD,
                  "每只持仓市值 = 份额 × 估值价" if not bad_mv else "；".join(bad_mv)))
    return out


def cache_checks(P) -> list[dict]:
    """这份 Portfolio 是不是市价口径 —— 决定页面显示的是券商的钱还是净值。"""
    out = []
    n_spot = len(P.spot or {})
    out.append(_c("cache.spot", OK if P.used_spot else WARN,
                  f"估值口径：{'市价' if P.used_spot else '净值'}（行情缓存 {n_spot} 只）",
                  "" if P.used_spot else "行情还没到位或全部取不到；等几秒刷新，或点「更新数据」",
                  "" if P.used_spot else "启动预热会灌一次现价，实在没有就检查网络"))
    return out


# ------------------------------------------------------------------ 汇总
def run(P=None, acct: dict | None = None, blocking_quotes: bool = False,
        error: str | None = None) -> dict:
    """跑全部检查。

    P 算不出来（`error`）时也要把净值/行情那几条跑完 —— 账户页 400 最常见的原因就是
    某只基金净值断档，直接甩一句「回测引擎没返回权重表」，等于把线索丢了。
    """
    acct = acct or {}
    checks: list[dict] = []
    checks += data_checks()
    checks += nav_checks(acct)
    checks += quote_checks(acct, blocking=blocking_quotes)
    if P is not None:
        checks += value_checks(P)
        checks += cache_checks(P)
    elif error:
        checks.append(_c("acct", BAD, f"账户算不出来：{error}",
                         "先看上面几条红项，通常就是同一个原因",
                         "按提示修，或 scripts/doctor.py --fix"))
    bad = [c for c in checks if c["level"] == BAD]
    warn = [c for c in checks if c["level"] == WARN]
    return {"ok": not bad, "bad": len(bad), "warn": len(warn),
            "checks": checks, "asof": f"{P.last:%Y-%m-%d}" if P is not None else None}
