"""账户视图：一个账户的持仓、收益、调仓计划 —— 不依赖 Streamlit 的纯计算层。

H5 前端（api/server.py）和 Streamlit 版（streamlit_app/app.py）共用这一份：
账户重放、今日收益、调仓计划、结论、收益/本金指数、按入金节奏折算基准 —— 只在这里算，
两个前端只管展示，数字天然一致。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from . import holdings as HG
from .config import ETF_META

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "streamlit_app"))
import fund_lookup as FL  # noqa: E402

MONEY_IN = ("转入", "入金")
MONEY_OUT = ("转出", "出金")


def min_order(tgt_amt: float) -> float:
    """单只基金值不值得单独下一笔：目标金额的 5%，至少 1 元（见 app.py 同名函数的说明）。"""
    return max(1.0, abs(tgt_amt) * 0.05)


class Portfolio:
    """acct：账户文件内容（含 trades / holdings）；target_w：资产 key → 目标权重（策略算好的）。"""

    def __init__(self, acct: dict, target_w):
        self.has_acct = acct is not None
        self.acct = acct or {}
        self.holdings = ({s: HG._norm_slot(v) for s, v in self.acct["holdings"].items()}
                         if self.acct.get("holdings") else HG._default_holdings())
        self.trades = list(self.acct.get("trades") or [])
        self.panel = HG.nav_panel(self.holdings)
        self._navcache: dict[str, pd.Series] = {}
        self._rawcache: dict[str, pd.DatetimeIndex] = {}
        self.first_trade: dict[str, pd.Timestamp] = {}
        for t in self.trades:
            if t.get("side") not in ("买入", "卖出"):
                continue
            try:
                d = pd.Timestamp(t["date"])
            except Exception:  # noqa: BLE001
                continue
            c = str(t.get("code") or "")
            if c and (c not in self.first_trade or d < self.first_trade[c]):
                self.first_trade[c] = d
        self.daily, self.pos, self.cost, self.cash, self.units = self._replay()
        self.last = self.panel.index[-1] if len(self.panel) else pd.Timestamp.today().normalize()
        self.slot_w = HG.slot_weights(target_w, self.holdings)
        self.active_codes = {c for s in HG.active(self.holdings) for c in HG.codes(self.holdings[s])}
        self.cfg_codes = set(HG.all_codes(self.holdings))
        self.plan = self._plan()

    # ------------------------------------------------------------ 净值
    def nav(self, code: str) -> pd.Series:
        if code in self.panel.columns:
            col = self.panel[code].dropna()
            if len(col):
                return col
        if code not in self._navcache:
            self._navcache[code] = HG.nav_series(code)
        return self._navcache[code]

    def raw_dates(self, code: str) -> pd.DatetimeIndex:
        """真正公布过净值的日子（面板做过 ffill，拿它判断「当天有没有净值」永远为真）。"""
        if code not in self._rawcache:
            try:
                s = HG.nav_series(code)
                self._rawcache[code] = pd.DatetimeIndex(s.dropna().index) if len(s) else pd.DatetimeIndex([])
            except Exception:  # noqa: BLE001
                self._rawcache[code] = pd.DatetimeIndex([])
        return self._rawcache[code]

    def nav_on(self, code: str, day) -> float | None:
        col = self.nav(code)
        if not len(col):
            return None
        sub = col.loc[:pd.Timestamp(day)]
        return float(sub.iloc[-1]) if len(sub) else None

    # ------------------------------------------------------------ 重放（app.py::_replay_holdings）
    def _replay(self):
        created = self.acct.get("created")
        p = self.panel
        idx = p.index[p.index >= pd.Timestamp(created)] if (len(p) and created) else pd.DatetimeIndex([])
        if len(idx) == 0:
            idx = p.index[-1:] if len(p) else pd.DatetimeIndex([])
        capital = float(self.acct.get("capital") or 0)
        if len(idx) == 0:
            return pd.DataFrame(), {}, {}, capital, capital
        buckets: dict = {}
        for t in self.trades:
            try:
                d = pd.Timestamp(t.get("date"))
            except Exception:  # noqa: BLE001
                continue
            buckets.setdefault(idx[min(int(idx.searchsorted(d)), len(idx) - 1)], []).append(t)
        cash, units, last_nav = capital, capital, 1.0
        pos: dict[str, float] = {}
        cost: dict[str, float] = {}
        rows = []
        prev_mv: dict[str, float] = {}
        self.by_day = {}          # 日期 → {代码: (收益元, 收益率%, 状态, 动作)}（收益日历点开某天用）
        for d in idx:
            flow: dict[str, float] = {}
            for t in buckets.get(d, []):
                code = str(t.get("code", "") or "")
                sh = float(t.get("shares", 0) or 0)
                px = float(t.get("nav", 0) or 0)
                fee = float(t.get("fee", 0) or 0)
                side = t.get("side")
                if side == "买入" and code and sh > 0:
                    if px <= 0:
                        px = self.nav_on(code, d) or 0
                    cash -= sh * px + fee
                    flow[code] = flow.get(code, 0.0) + sh * px + fee
                    prev = pos.get(code, 0.0)
                    cost[code] = ((prev * cost.get(code, 0.0) + sh * px + fee) / (prev + sh)) if (prev + sh) > 0 else px
                    pos[code] = prev + sh
                elif side == "卖出" and code and sh > 0:
                    if px <= 0:
                        px = self.nav_on(code, d) or 0
                    cash += sh * px - fee
                    flow[code] = flow.get(code, 0.0) - (sh * px - fee)
                    pos[code] = pos.get(code, 0.0) - sh
                    if pos[code] <= 1e-9:
                        pos.pop(code, None)
                        cost.pop(code, None)
                elif side in MONEY_IN:
                    units += sh / (last_nav if last_nav > 0 else 1.0)
                    cash += sh
                elif side in MONEY_OUT:
                    units = max(1e-9, units - sh / (last_nav if last_nav > 0 else 1.0))
                    cash -= sh
            cur_mv = {c: sh * v for c, sh in pos.items() if (v := self.nav_on(c, d))}
            mv = sum(cur_mv.values())
            day = {}
            for code in set(prev_mv) | set(cur_mv) | set(flow):
                if code in pos and code not in cur_mv:
                    continue
                a, b, f = prev_mv.get(code, 0.0), cur_mv.get(code, 0.0), flow.get(code, 0.0)
                pnl, base = b - a - f, a + max(f, 0.0)
                raw = self.raw_dates(code)
                act = "" if abs(f) < 1e-9 else ("买入" if f > 0 else ("清仓" if code not in pos else "卖出"))
                state = "" if (act or d in raw) else ("待更新" if (not len(raw) or d > raw[-1]) else "无净值")
                day[code] = (pnl, (pnl / base * 100) if base > 0 else None, state, act)
            self.by_day[d] = day
            prev_mv = cur_mv
            eq = cash + mv
            last_nav = eq / units if units > 0 else 1.0
            # nav_twr：时间加权单位净值（转入按当时净值折份额），备查；页面上的 nav 是「收益 / 本金」口径
            rows.append({"date": d, "equity": eq, "cash": cash, "market": mv, "nav_twr": last_nav})
        daily = pd.DataFrame(rows).set_index("date")
        fl = self.flows(daily.index)
        inv = capital + fl.cumsum()
        peak = float(inv.max()) if len(inv) else 0.0
        daily["invested"] = inv
        daily["pnl"] = daily["equity"] - inv
        # 收益 / 本金口径的指数（app.py::_money_index）：今天的值 = 持有收益率
        daily["nav"] = (1.0 + daily["pnl"] / peak) if peak > 0 else 1.0
        return daily, pos, cost, cash, units

    def flows(self, idx) -> pd.Series:
        out = pd.Series(0.0, index=idx)
        for t in self.trades:
            side = t.get("side")
            if side not in MONEY_IN + MONEY_OUT:
                continue
            try:
                d = pd.Timestamp(t.get("date"))
            except Exception:  # noqa: BLE001
                continue
            i = min(int(idx.searchsorted(d)), len(idx) - 1)
            amt = float(t.get("shares", 0) or 0)
            out.iloc[i] += -amt if side in MONEY_OUT else amt
        return out

    def invested_now(self) -> float:
        v = float(self.acct.get("capital") or 0)
        for t in self.trades:
            if t.get("side") in MONEY_IN:
                v += float(t.get("shares") or 0)
            elif t.get("side") in MONEY_OUT:
                v -= float(t.get("shares") or 0)
        return v

    # ------------------------------------------------------------ 今日（app.py::_held_day）
    def held_day(self, code, shares, px, px_prev, prev_day=None) -> tuple[float, float | None]:
        shares, px, px_prev = float(shares or 0), float(px or 0), float(px_prev or 0)
        if shares <= 0 or px <= 0:
            return 0.0, None
        f = self.first_trade.get(str(code))
        if f is not None and prev_day is not None and f > pd.Timestamp(prev_day):
            return 0.0, None
        return (px - px_prev) * shares, ((px / px_prev - 1) * 100 if px_prev > 0 else None)

    # ------------------------------------------------------------ 调仓计划（app.py::_hg_plan）
    def _plan(self, slot_w: dict | None = None) -> dict:
        """slot_w：换一套位置目标权重算（「换策略」前的预览）；缺省用账户跟随的策略。"""
        sw = self.slot_w if slot_w is None else slot_w
        h, cash = self.holdings, float(self.cash or 0)
        mv_by_slot, seen = {}, set()
        for s in HG.active(h):
            v = 0.0
            for code in HG.codes(h[s]):
                if code in seen:
                    continue
                sh = float(self.pos.get(code, 0) or 0)
                if sh <= 0 or code not in self.panel.columns:
                    continue
                col = self.panel[code].dropna()
                if len(col):
                    v += sh * float(col.iloc[-1])
                    seen.add(code)
            if v > 0:
                mv_by_slot[s] = v
        asset = float(sum(mv_by_slot.values())) + cash
        rows, orders, by_code = [], [], {}
        buy_total = sell_total = mv_total = today = 0.0
        counted: dict[str, str] = {}
        for s in HG.active(h):
            funds = HG.funds(h[s])
            if not funds:
                continue
            tgt_w = float(sw.get(s, 0) or 0)
            tgt = tgt_w * asset
            items = []
            for f, x in zip(funds, HG.share_of(h[s])):
                code = f["code"]
                col = self.panel[code].dropna() if code in self.panel.columns else pd.Series(dtype=float)
                px = float(col.iloc[-1]) if len(col) else 0.0
                px_prev = float(col.iloc[-2]) if len(col) > 1 else px
                sh = float(self.pos.get(code, 0) or 0)
                cst = float(self.cost.get(code, 0) or 0)
                items.append({"f": f, "x": float(x), "code": code, "px": px, "px_prev": px_prev,
                              "px_prev_day": (col.index[-2] if len(col) > 1 else None),
                              "shares": sh, "cost": cst, "mv": sh * px, "dup": counted.get(code),
                              "pl": ((px / cst - 1) if (cst > 0 and px > 0) else None)})
                counted.setdefault(code, s)
            slot_mv = sum(it["mv"] for it in items if not it["dup"])
            mv_total += slot_mv
            today += sum(self.held_day(it["code"], it["shares"], it["px"], it["px_prev"],
                                       it["px_prev_day"])[0] for it in items if not it["dup"])
            slot_w = (slot_mv / asset) if asset else 0.0
            moved = abs(tgt - slot_mv) >= max(1.0, asset * 0.005)
            for i, it in enumerate(items):
                f = it["f"]
                diff = (tgt * it["x"] - it["mv"]) if moved else 0.0
                side, qty, amt, note, liq = "", 0.0, 0.0, "", False
                if it["px"] <= 0:
                    note = "缺净值"
                elif it["dup"]:
                    note = f'已在「{HG.SLOT_LABEL.get(it["dup"], it["dup"])}」计入'
                elif not moved or abs(diff) < min_order(tgt * it["x"]):
                    note = ""
                else:
                    qty, amt = HG.order_quantity(f, abs(diff), it["px"])
                    if qty <= 0:
                        note = "不足一手"
                    elif diff > 0:
                        side, buy_total = "买入", buy_total + amt
                    else:
                        side, sell_total = "卖出", sell_total + amt
                        liq = bool(it["shares"] > 0 and qty >= it["shares"] * (1 - 1e-9))
                it.update({"slot": s, "side": side, "qty": qty, "amount": amt, "note": note, "liq": liq,
                           "otc": HG.is_otc(f), "w_now": (0.0 if it["dup"] else it["mv"] / asset) if asset else 0.0,
                           "w_tgt": tgt_w * it["x"], "dev": ((slot_w - tgt_w) if i == 0 else 0.0),
                           "slot_w": slot_w, "slot_tgt_w": tgt_w, "slot_first": i == 0, "slot_n": len(items)})
                if side:
                    orders.append({"date": f"{self.last:%Y-%m-%d}", "slot": s, "code": it["code"], "side": side,
                                   "shares": round(float(qty), 4), "nav": round(it["px"], 4), "fee": 0.0,
                                   "amount": amt, "liq": liq})
                    by_code[it["code"]] = {"side": side, "amount": amt, "qty": qty}
                rows.append(it)
        other_mv = {c: sh * float(self.nav_on(c, self.last) or 0)
                    for c, sh in self.pos.items() if sh > 0 and c not in self.active_codes}
        other = [{"code": c, "mv": v, "in_cfg": c in self.cfg_codes} for c, v in other_mv.items() if v > 0]
        for c, sh in self.pos.items():
            if float(sh or 0) <= 0 or c in self.active_codes:
                continue
            nv = self.nav(c)
            if len(nv) > 1:
                today += self.held_day(c, float(sh), float(nv.iloc[-1]), float(nv.iloc[-2]), nv.index[-2])[0]
        total = mv_total + sum(o["mv"] for o in other) + cash
        base = self.invested_now()
        return {"asset": asset, "cash": cash, "mv": mv_total, "mv_all": mv_total + sum(o["mv"] for o in other),
                "total": total, "other": other, "rows": rows, "orders": orders, "by_code": by_code,
                "has_acct": self.has_acct,
                "buy": buy_total, "sell": sell_total, "today": today,
                "pnl": (total - base) if base > 0 else 0.0,
                "pnl_pct": ((total / base - 1) if base > 0 else 0.0)}

    # ------------------------------------------------------------ 结论（app.py::_plan_status）
    def status(self) -> dict:
        p = self.plan
        if p["orders"]:
            liq = [o for o in p["orders"] if o.get("liq")]
            return {"kind": "orders", "n": len(p["orders"]), "buy": p["buy"], "sell": p["sell"],
                    "liq": len(liq), "liq_amt": sum(o["shares"] * o["nav"] for o in liq)}
        over = sorted([it for it in p["rows"] if it.get("slot_first") and abs(it.get("dev") or 0) >= 0.005],
                      key=lambda it: -abs(it["dev"]))
        if not over:
            return {"kind": "calm"}
        w = over[0]
        return {"kind": "stuck", "n": len(over), "max_dev": abs(w["dev"]), "slots": [it["slot"] for it in over],
                "gap": abs(w["dev"]) * p["asset"], "lot": w["px"] * int(w["f"].get("lot") or 100),
                "note": w.get("note") or ""}

    # ------------------------------------------------------------ 给前端的结构
    def other_item(self, code: str, why: str) -> dict:
        nv = self.nav(code)
        px = float(nv.iloc[-1]) if len(nv) else 0.0
        px_prev = float(nv.iloc[-2]) if len(nv) > 1 else px
        sh, cst = float(self.pos.get(code, 0) or 0), float(self.cost.get(code, 0) or 0)
        meta = HG.fund_meta(self.holdings, code)[1] or {}
        return {"code": code, "f": meta, "slot": why, "x": 1.0, "slot_n": 1, "px": px, "px_prev": px_prev,
                "px_prev_day": (nv.index[-2] if len(nv) > 1 else None), "shares": sh, "cost": cst, "mv": sh * px,
                "pl": ((px / cst - 1) if (cst > 0 and px > 0) else None),
                "otc": HG.is_otc(meta) if meta else (HG.default_unit(code) == "份额"),
                "w_now": (sh * px / self.plan["total"]) if self.plan["total"] else 0.0, "w_tgt": None,
                "side": "", "qty": 0.0, "amount": 0.0, "note": "", "why": why, "dev": 0.0, "slot_first": True}

    def items(self) -> list[dict]:
        out = list(self.plan["rows"])
        for o in self.plan["other"]:
            out.append(self.other_item(o["code"], "位置已关闭" if o.get("in_cfg") else "不在配置里"))
        return out

    def holding(self, it: dict) -> dict:
        """一只基金 → 前端行（数值不格式化，前端自己排版）。"""
        code = it["code"]
        held = it["shares"] > 0
        day, day_pct = self.held_day(code, it["shares"], it["px"], it["px_prev"], it.get("px_prev_day"))
        hold = it["mv"] - it["shares"] * it["cost"]
        return {"code": code, "name": str(it["f"].get("name") or FL.fund_name(code) or code),
                "slot": HG.SLOT_LABEL.get(it["slot"], it["slot"]), "otc": bool(it["otc"]),
                "unit": "份" if it["otc"] else "股", "slot_n": it.get("slot_n", 1), "x": it.get("x", 1.0),
                "dup": bool(it.get("dup")), "held": held, "shares": it["shares"], "px": it["px"],
                "cost": it["cost"], "mv": it["mv"], "day": day if held else None,
                "day_pct": day_pct if held else None, "hold": hold if held else None,
                "hold_pct": (it["pl"] * 100 if (held and it["pl"] is not None) else None),
                "w_now": it["w_now"], "w_tgt": it.get("w_tgt"), "why": it.get("why", ""),
                "side": it.get("side", ""), "amount": it.get("amount", 0.0), "qty": it.get("qty", 0.0),
                "liq": bool(it.get("liq")), "note": it.get("note", "")}

    def month_curve(self) -> dict:
        """近一个月：起点记 0 的累计收益率(%) 与收益额（app.py::_head_month_curve_html 同口径）。"""
        d = self.daily
        if len(d) < 2:
            return {"dates": [], "ret": [], "money": []}
        nav, pnl = d["nav"].astype(float), d["pnl"].astype(float)
        i0 = int(nav.index.searchsorted(nav.index[-1] - pd.DateOffset(months=1), side="right")) - 1
        i0 = max(0, min(i0, len(nav) - 2))
        seg, ps = nav.iloc[i0:], pnl.iloc[i0:]
        return {"dates": [f"{x:%Y-%m-%d}" for x in seg.index],
                "ret": [round((float(v) / float(seg.iloc[0]) - 1) * 100, 4) for v in seg],
                "money": [round(float(v - ps.iloc[0]), 2) for v in ps]}

    def summary(self) -> dict:
        p = self.plan
        prev = p["total"] - p["today"]
        return {"total": p["total"], "today": p["today"], "today_pct": (p["today"] / prev * 100) if prev > 0 else 0.0,
                "pnl": p["pnl"], "pnl_pct": p["pnl_pct"] * 100, "cash": p["cash"],
                "asof": f"{self.last:%Y-%m-%d}", "created": self.acct.get("created"),
                "n_funds": len({r["code"] for r in p["rows"] if r["shares"] > 0}) + len(p["other"])}

    def slot_options(self) -> list[dict]:
        """记一笔可选的基金（app.py::_hg_slot_options）：参与调仓的在前，关掉的位置、已删的代码在后。"""
        out, off = [], []
        for s in HG.SLOTS:
            on = bool(self.holdings.get(s, {}).get("on", True))
            for f in HG.funds(self.holdings.get(s, {})):
                (out if on else off).append({"slot": s, "code": f["code"], "name": f.get("name") or FL.fund_name(f["code"]) or f["code"],
                                             "slot_label": HG.SLOT_LABEL[s] + ("（位置已关闭）" if not on else ""),
                                             "unit": "股" if str(f.get("unit") or HG.default_unit(f["code"])) == "股" else "份"})
        out += off
        have = {o["code"] for o in out}
        for c, sh in self.pos.items():
            if c not in have and float(sh or 0) > 0:
                out.append({"slot": "", "code": c, "name": FL.fund_name(c) or c, "slot_label": "已删除的位置",
                            "unit": "股" if HG.default_unit(c) == "股" else "份"})
        return out

    def held_on(self, code: str, day) -> float:
        held = 0.0
        for t in self.trades:
            if str(t.get("code") or "") != str(code) or str(t.get("date") or "") > str(day):
                continue
            if t.get("side") == "买入":
                held += float(t.get("shares") or 0)
            elif t.get("side") == "卖出":
                held -= float(t.get("shares") or 0)
        return held

    def trades_of(self, code: str | None = None) -> list[dict]:
        out = []
        for i, t in enumerate(self.trades):
            if code and str(t.get("code") or "") != code:
                continue
            sh, nv, fee = float(t.get("shares") or 0), float(t.get("nav") or 0), float(t.get("fee") or 0)
            side = t.get("side")
            amt = sh if side in MONEY_IN + MONEY_OUT else (sh * nv + fee if side == "买入" else sh * nv - fee)
            out.append({"i": i, "date": t.get("date"), "side": side, "code": t.get("code") or "",
                        "name": (FL.fund_name(str(t.get("code"))) or t.get("code") or "") if t.get("code") else "",
                        "shares": sh, "nav": nv, "fee": fee, "amount": amt})
        return sorted(out, key=lambda r: (str(r["date"]), r["i"]), reverse=True)


    # ------------------------------------------------------------ 新钱怎么分（app.py::_calc_dca）
    def dca(self, amount: float) -> dict:
        slots, meta, dead = {}, {}, []
        for it in self.plan["rows"]:
            g = slots.setdefault(it["slot"], {"slot": it["slot"], "w": float(it["slot_tgt_w"]), "mv": 0.0, "items": []})
            g["mv"] += float(it["mv"])
            if it["px"] <= 0:
                dead.append(it["code"])
                continue
            g["items"].append({"code": it["code"], "x": float(it["x"])})
            meta[it["code"]] = it
        rows, buy, lost = [], 0.0, 0.0
        for a in HG.plan_invest(list(slots.values()), float(amount)):
            m = meta.get(a["code"])
            if not m:
                continue
            want = float(a["amount"])
            qty, amt = HG.order_quantity(m["f"], want, float(m["px"]))
            note = ""
            if qty <= 0:
                note = (f'低于最低申购 ¥{float(m["f"].get("min_amount") or 1):,.0f}' if HG.is_otc(m["f"])
                        else f'不足一手（一手 ≈ ¥{int(m["f"].get("lot") or 100) * float(m["px"]):,.0f}）')
                lost += want
            else:
                buy += amt
            rows.append({"code": m["code"], "name": str(m["f"].get("name") or FL.fund_name(m["code"]) or m["code"]),
                         "slot": HG.SLOT_LABEL.get(a["slot"], a["slot"]), "otc": bool(m["otc"]),
                         "unit": "份" if m["otc"] else "股", "want": want, "amount": amt, "qty": float(qty),
                         "px": m["px"], "w_tgt": m["slot_tgt_w"], "x": a["x"], "slot_n": m["slot_n"], "note": note})
        return {"rows": rows, "buy": buy, "lost": lost, "n": sum(1 for r in rows if r["qty"] > 0),
                "after": self.plan["total"] + float(amount), "dead": dead}

    # ------------------------------------------------------------ 体检（app.py::_acct_health_view）
    def health(self) -> dict:
        rows = [r for r in self.plan["rows"] if float(r["shares"] or 0) > 0]
        if not rows:
            return {"items": [], "bad": [], "days": 0}
        nm = lambda r: str(r["f"].get("name") or r["code"])
        big = max(rows, key=lambda r: float(r["w_now"] or 0))
        slot_w: dict[str, float] = {}
        for r in rows:
            slot_w[r["slot"]] = slot_w.get(r["slot"], 0.0) + float(r["w_now"] or 0)
        sk, smax = max(slot_w.items(), key=lambda kv: kv[1])
        worst = min((r for r in rows if r.get("pl") is not None), key=lambda r: r["pl"], default=None)
        dev = max((r for r in rows if r.get("slot_first")), key=lambda r: abs(float(r["dev"])), default=None)
        nav = self.daily["nav"].astype(float) if len(self.daily) else pd.Series(dtype=float)
        mdd = float((nav / nav.cummax() - 1).min()) if len(nav) > 1 else None
        cash_r = self.plan["cash"] / self.plan["total"] if self.plan["total"] else 0.0
        items = []

        def add(label, now, line, over, why, bad):
            items.append({"label": label, "now": now, "line": line, "over": over if bad else "正常", "why": why, "bad": bool(bad)})

        if any(sum(1 for r in rows if r["slot"] == k) > 1 for k in slot_w):
            add("单只最大占比", f"{big['w_now'] * 100:.1f}%（{nm(big)}）", "25%", "偏高",
                "一只基金的涨跌就能左右整个账户；想分散就给这个位置再挂一只同类基金", float(big["w_now"]) > 0.25)
            add("单一位置最大占比", f"{smax * 100:.1f}%（{HG.SLOT_LABEL.get(sk, sk)}）", "50%", "偏高",
                "整个位置同涨同跌，相当于半个账户压在一个资产上", smax > 0.50)
        else:
            add("最大仓位", f"{smax * 100:.1f}%（{nm(big)}）", "25%", "偏高",
                "一只基金就占了账户这么多，它自己出问题等于账户出问题", smax > 0.25)
        if cash_r >= 0.005:
            add("现金占比", f"{cash_r * 100:.1f}%", "15%", "偏多", "钱还没买成基金，闲着拖低收益；到「调仓 · 新钱怎么分」买掉", cash_r > 0.15)
        add("最大回撤", f"{mdd * 100:.2f}%（账户 {len(self.daily)} 天）" if mdd is not None else "—", "12%", "超线",
            "从最高点回落的最大幅度，越深越考验能不能拿住", mdd is not None and mdd <= -0.12)
        if worst is not None:
            add("单只最大浮亏", f"{worst['pl'] * 100:.2f}%（{nm(worst)}）", "15%", "超线",
                "只说明这一只买贵了，不等于该卖；先看是整体下跌还是它自己的问题", float(worst["pl"]) <= -0.15)
        if dev is not None:
            add("偏离目标最大", f"{float(dev['dev']) * 100:+.1f}pp（{HG.SLOT_LABEL.get(dev['slot'], dev['slot'])}）", "±5pp",
                "该调了", "和策略目标已经拉开距离；调多少看「调仓」", abs(float(dev["dev"])) >= 0.05)
        return {"items": items, "bad": [i for i in items if i["bad"]], "days": len(self.daily)}

    # ------------------------------------------------------------ 收益：每天的数 + 当日明细
    def period(self) -> dict:
        d = self.daily
        if len(d) < 1:
            return {"dates": [], "nav": [], "pnl": [], "day": [], "detail": {}, "funds": {}}
        fl = self.flows(d.index)
        day = d["equity"].astype(float).diff() - fl
        names, detail = {}, {}
        for dt, rows in self.by_day.items():
            out = []
            for c, (pnl, pct, state, act) in rows.items():
                if c not in names:
                    names[c] = FL.fund_name(c) or c
                out.append([c, round(float(pnl), 2), None if pct is None else round(float(pct), 4), state, act])
            if out:
                detail[f"{dt:%Y-%m-%d}"] = sorted(out, key=lambda r: -r[1])
        return {"dates": [f"{x:%Y-%m-%d}" for x in d.index],
                "nav": [round(float(v), 6) for v in d["nav"]],
                "pnl": [round(float(v), 2) for v in d["pnl"]],
                "day": [None if pd.isna(v) or i == 0 else round(float(v), 2) for i, v in enumerate(day)],
                "detail": detail, "funds": names}

    # ------------------------------------------------------------ 对比：同样的入金节奏买基准
    def bench_index(self, bench) -> pd.Series:
        if bench is None or len(bench.dropna()) < 2 or not len(self.daily):
            return pd.Series(dtype=float)
        b = bench.dropna().sort_index()
        idx = self.daily.index[self.daily.index >= b.index[0]]
        if len(idx) < 2:
            return pd.Series(dtype=float)
        bb = b.reindex(b.index.union(idx)).ffill().reindex(idx)
        fl = self.flows(idx)
        fl.iloc[0] += float(self.acct.get("capital") or 0)
        val = (fl / bb).cumsum() * bb
        inv = fl.cumsum()
        return 1.0 + (val - inv) / (float(inv.max()) or 1.0)


def close_trade_idx(trades: list[dict], tol: float = 1e-6) -> set[int]:
    """哪些卖出把这只基金的份额清成了 0（台账打「清仓」标；同 app.py::_close_trade_idx）。"""
    out, held, items = set(), {}, []
    for k, t in enumerate(trades or []):
        if t.get("side") not in ("买入", "卖出") or float(t.get("shares") or 0) <= 0:
            continue
        try:
            items.append((pd.Timestamp(t.get("date")), k, t))
        except Exception:  # noqa: BLE001
            continue
    for _d, k, t in sorted(items, key=lambda x: (x[0], x[1])):
        c, sh = str(t.get("code") or ""), float(t.get("shares") or 0)
        if t.get("side") == "买入":
            held[c] = held.get(c, 0.0) + sh
            continue
        after = held.get(c, 0.0) - sh
        if held.get(c, 0.0) > tol and after <= tol:
            out.add(k)
        held[c] = 0.0 if after <= tol else after
    return out


def asset_meta(asset: str) -> dict:
    return ETF_META.get(asset, {})
