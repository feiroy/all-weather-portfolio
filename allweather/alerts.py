"""提醒：偏离提醒 / 估值提醒 / 账户体检。

三条独立的口径，互不混用：
- 偏离：我持仓的实际权重 vs 策略目标权重（都用我持仓的基金净值算市值）
- 估值：蛋卷估值（PE/PB 百分位、评分），只作加减仓参考，不进策略信号
- 体检：账户层面的累计收益、最大回撤、现金占比、与两条基准的差距
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# === 阈值 ===
DEV_WARN = 0.05      # 单桶偏离 5pp → 提示（<3pp 属于正常漂移）
DEV_URGENT = 0.12    # 单桶偏离 12pp → 需要动
CASH_WARN = 0.15     # 现金占比超过 15% → 钱闲着
CASH_INFO = 0.05     # 现金占比低于 5% → 调仓子弹不足
DRAWDOWN_WARN = 0.12  # 账户回撤 12% → 提示
LOSS_WARN = -0.15    # 单只浮亏 15% → 提示

_VAL_BUCKETS = [
    (18, "猎杀区", "低估，可加仓"),
    (14, "稳中求胜", "偏低，正常定投"),
    (10, "中性观察", "不贵不便宜"),
    (6, "高位警戒", "偏贵，少加或暂停"),
    (0, "泡沫区", "明显高估，考虑减仓"),
]


def bucket_of_score(score) -> tuple[str, str]:
    for lo, label, action in _VAL_BUCKETS:
        if score is not None and score >= lo:
            return label, action
    return "—", "无数据"


def compute(
    mv: dict[str, float],            # 位置 → 当前市值
    target_w: dict[str, float],      # 位置 → 目标权重（已按启用位置归一化）
    holdings: dict,                  # 持仓配置
    slot_label: dict[str, str],
    val_by_code: dict[str, dict],    # 基金代码 → {pe_pct, pb_pct, score, name}
    daily: pd.DataFrame | None = None,   # 账户日度净值
    cash: float = 0.0,
    pos: dict[str, float] | None = None,     # 基金代码 → 持有份额
    cost: dict[str, float] | None = None,    # 基金代码 → 成本单价
    bench: dict[str, pd.Series] | None = None,
    slot_of_code=None,                       # 代码 → 位置 的反查函数
) -> dict:
    """算出三类提醒。返回 {"偏离": [...], "估值": [...], "体检": [...], "指标": {...}}。"""
    total = float(sum(mv.values())) + float(cash or 0)
    out: dict = {"偏离": [], "估值": [], "体检": [], "指标": {}}

    # ---- 偏离 ----
    cur_w = {s: (v / total if total > 0 else 0.0) for s, v in mv.items()}
    for s in sorted(set(list(cur_w) + list(target_w))):
        cur = cur_w.get(s, 0.0)
        tgt = float(target_w.get(s, 0) or 0)
        dev = cur - tgt
        if abs(dev) < 0.03:
            continue
        level = "urgent" if abs(dev) >= DEV_URGENT else ("warn" if abs(dev) >= DEV_WARN else "info")
        out["偏离"].append({
            "slot": s, "label": slot_label.get(s, s), "cur": cur, "tgt": tgt, "dev": dev,
            "level": level,
            "text": f"{slot_label.get(s, s)} 现在 {cur*100:.1f}%，目标 {tgt*100:.1f}%，"
                    f"{'超出' if dev > 0 else '低于'} {abs(dev)*100:.1f} 个百分点"
                    + ("，建议调仓" if level == "urgent" else ""),
        })
    out["偏离"].sort(key=lambda x: -abs(x["dev"]))

    # ---- 估值 ----
    for s, h in holdings.items():
        code = h.get("code", "")
        v = val_by_code.get(code)
        if not v:
            continue
        score = v.get("score")
        label, action = bucket_of_score(score)
        cands = [p for p in (v.get("pe_pct"), v.get("pb_pct")) if p is not None]
        pct = max(cands) if cands else None
        level = "info"
        if score is not None:
            level = "urgent" if score >= 18 or score <= 6 else "warn"
        out["估值"].append({
            "slot": s, "code": code, "name": h.get("name") or v.get("name") or code,
            "score": score, "label": label, "action": action, "pct": pct, "level": level,
            "text": f"{h.get('name') or code}（{code}）估值评分 {score if score is not None else '—'}，{label}：{action}",
        })
    out["估值"].sort(key=lambda x: -(x["score"] if x["score"] is not None else 99))

    # ---- 体检 ----
    def add(level, text, tip=""):
        out["体检"].append({"level": level, "text": text, "tip": tip})

    nav = daily["nav"] if daily is not None and len(daily) else None
    if nav is not None and len(nav) > 1:
        ret = float(nav.iloc[-1] - 1)
        mdd = float((nav / nav.cummax() - 1).min())
        out["指标"]["累计收益"] = ret
        out["指标"]["最大回撤"] = mdd
        add("info", f"累计收益 {ret*100:+.2f}%", "按份额记账，资金进出不会虚增收益")
        if mdd <= -DRAWDOWN_WARN:
            add("warn", f"账户最大回撤 {mdd*100:.2f}%，超过 {DRAWDOWN_WARN*100:.0f}% 提醒线",
                "回撤是账户净值从最高点回落的最大幅度")
    if total > 0:
        cash_r = cash / total
        out["指标"]["现金占比"] = cash_r
        if cash_r >= CASH_WARN:
            add("warn", f"现金占比 {cash_r*100:.1f}%，超过 {CASH_WARN*100:.0f}%", "闲置资金拖低收益")
        elif cash_r <= CASH_INFO:
            add("info", f"现金占比 {cash_r*100:.1f}%，调仓子弹偏少", "调仓需要现金做先卖后买")
    for code, c in (cost or {}).items():
        s = slot_of_code(code) if slot_of_code else None
        shares = float((pos or {}).get(code, 0) or 0)
        if shares <= 0 or not c or s is None:
            continue
        cur_nav = mv.get(s, 0) / shares if shares else 0
        if cur_nav <= 0:
            continue
        pl = cur_nav / float(c) - 1
        out["指标"].setdefault("浮盈亏", {})[code] = pl
        if pl <= LOSS_WARN:
            add("warn", f"{slot_label.get(s, s)}（{holdings.get(s, {}).get('code', '')}）"
                        f"浮亏 {pl*100:.1f}%，超过 {abs(LOSS_WARN)*100:.0f}% 提醒线",
                "单只浮亏不等于该卖，先看是整体下跌还是这只基金本身的问题")
    if bench:
        for name, series in bench.items():
            if series is None or len(series) < 2:
                continue
            if nav is None or len(nav) < 2:
                continue
            end = min(series.index[-1], nav.index[-1])
            a = float(nav.loc[:end].iloc[-1])
            b = float(series.loc[:end].iloc[-1] / series.loc[:end].iloc[0])
            gap = a / b - 1 if b > 0 else None
            out["指标"][f"对比{name}"] = gap
            if gap is not None and abs(gap) >= 0.02:
                add("info" if abs(gap) < 0.05 else "warn",
                    f"与「{name}」差 {gap*100:+.2f}pp",
                    "差异来自换基金、调仓时点、申赎费用；超过 2pp 值得看一眼")
    return out
